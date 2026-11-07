"""Copy valid public GitHub issue attachments into the Manager download catalogue."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zipfile import BadZipFile, ZipFile

LIMIT = 25_000_000
MAX_SAVES = 40
ATTACHMENT = re.compile(r"https://github\.com/user-attachments/files/\d+/[A-Za-z0-9_.%~-]+\.zip")
REDIRECT_HOSTS = {"github.com", "objects.githubusercontent.com",
                  "user-images.githubusercontent.com", "github-production-user-asset-6210df.s3.amazonaws.com",
                  "release-assets.githubusercontent.com", "private-user-images.githubusercontent.com"}


class AttachmentRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.netloc not in REDIRECT_HOSTS:
            raise ValueError("Unexpected attachment host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def package(url, platform):
    with build_opener(AttachmentRedirect()).open(url, timeout=20) as response:
        content = response.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise ValueError("ZIP exceeds the attachment limit")
    with ZipFile(io.BytesIO(content)) as archive:
        expected = {"image.bin", "key.bin"} if platform == "ps4" else {"image.bin"}
        entries = archive.infolist()
        if len(entries) != len(expected) or {item.filename for item in entries} != expected:
            raise ValueError("ZIP needs image.bin and a key.bin only for PS4")
        if sum(item.file_size for item in entries) > LIMIT or not archive.getinfo("image.bin").file_size:
            raise ValueError("Save exceeds the unpacked size limit or is empty")
        if platform == "ps4" and archive.getinfo("key.bin").file_size != 96:
            raise ValueError("PS4 key must be 96 bytes")
        return (archive.read("key.bin") if platform == "ps4" else b"") + archive.read("image.bin")


def metadata(issue):
    fields = dict(re.findall(r"^### ([^\n]+)\n\n(.*?)(?=\n### |\Z)",
                             issue["body"].replace("\r\n", "\n"), re.M | re.S))
    title = fields.get("Title ID", "").strip().upper()
    description = fields.get("Description", "").strip()
    urls = ATTACHMENT.findall(fields.get("Save ZIP", ""))
    if (not re.fullmatch(r"(?:CUSA|PPSA)\d{5}", title) or not 0 < len(description) <= 240
            or re.search(r"[\x00-\x1f\x7f]", description) or len(urls) != 1
            or not re.search(r"^- \[[xX]\] I have permission to share this save publicly\.$",
                             fields.get("Public sharing", "").strip(), re.M)):
        raise ValueError("Missing title ID, description, consent, or one ZIP")
    return title, description, urls[0]


def sync():
    base = "https://api.github.com/repos/ItssJustAaron/PSN-HUB-Saves/issues"
    headers = {"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"}
    catalogue = Path("catalog.json")
    old = {item["issue"]: item for item in json.loads(catalogue.read_text(encoding="utf-8-sig"))["items"]}
    folder = Path("saves")
    folder.mkdir(exist_ok=True)
    items = []
    for page in range(1, 11):
        request = Request(f"{base}?state=open&sort=created&direction=asc&per_page=100&page={page}", headers=headers)
        with urlopen(request, timeout=20) as response:
            issues = json.load(response)
        for issue in issues:
            if "pull_request" in issue or not issue.get("body"):
                continue
            number = issue["number"]
            try:
                title, description, attachment = metadata(issue)
                platform = "ps4" if title.startswith("CUSA") else "ps5"
                file = folder / f"{number}.bin"
                previous = old.get(number, {})
                if previous.get("attachment") == attachment and previous.get("platform") == platform and file.is_file():
                    data = file.read_bytes()
                else:
                    data = package(attachment, platform)
                    file.write_bytes(data)
                items.append(dict(issue=number, title=title, description=description, platform=platform,
                                  attachment=attachment, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
            except (OSError, ValueError, BadZipFile, RuntimeError, NotImplementedError):
                print(f"Issue #{number} has no usable save package.")
            if len(items) == MAX_SAVES:
                break
        if len(issues) < 100 or len(items) == MAX_SAVES:
            break
    active = {str(item["issue"]) for item in items}
    for file in folder.glob("*.bin"):
        if file.stem.isdecimal() and file.stem not in active:
            file.unlink()
    catalogue.write_text(json.dumps({"schemaVersion": 1, "items": items}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sync()
