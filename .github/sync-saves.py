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
MAX_SLOTS = 128
SLOT_ENTRY = re.compile(r"slots/([1-9][0-9]{0,2})/(image\.bin|key\.bin|name\.txt)")
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
    return unpack(content, platform)


def unpack(content, platform):
    expected = {"image.bin", "key.bin"} if platform == "ps4" else {"image.bin"}
    with ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = {item.filename for item in entries}
        if not entries or len(names) != len(entries) or sum(item.file_size for item in entries) > LIMIT:
            raise ValueError("Invalid ZIP entries or unpacked size")

        def read_slot(prefix):
            if not archive.getinfo(prefix + "image.bin").file_size:
                raise ValueError("Save image is empty")
            key = b""
            if platform == "ps4":
                if archive.getinfo(prefix + "key.bin").file_size != 96:
                    raise ValueError("PS4 key must be 96 bytes")
                key = archive.read(prefix + "key.bin")
            return key + archive.read(prefix + "image.bin")

        if names == expected:
            return [(None, None, read_slot(""))]
        slots = {}
        for name in names:
            match = SLOT_ENTRY.fullmatch(name)
            if not match or int(match[1]) > MAX_SLOTS:
                raise ValueError("Invalid slot path")
            slots.setdefault(int(match[1]), set()).add(match[2])
        result = []
        for slot, files in sorted(slots.items()):
            prefix = f"slots/{slot}/"
            if files != expected | {"name.txt"} or not 0 < archive.getinfo(prefix + "name.txt").file_size <= 256:
                raise ValueError("Incomplete slot or invalid name length")
            name = archive.read(prefix + "name.txt").decode("utf-8")
            if not name.strip() or re.search(r"[\x00-\x1f\x7f]", name):
                raise ValueError("Invalid slot name")
            result.append((slot, name, read_slot(prefix)))
        return result


def filename(issue, slot=None):
    return f"{issue}.bin" if slot is None else f"{issue}-{slot}.bin"


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
    old = {}
    for item in json.loads(catalogue.read_text(encoding="utf-8-sig"))["items"]:
        old.setdefault(item["issue"], []).append(item)
    folder = Path("saves")
    folder.mkdir(exist_ok=True)
    items = []
    published = 0
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
                previous = old.get(number, [])
                if previous and all(item["attachment"] == attachment and item["platform"] == platform
                                    and (folder / filename(number, item.get("slot"))).is_file() for item in previous):
                    items.extend(dict(item, title=title, description=description) for item in previous)
                else:
                    submitted = []
                    for slot, name, data in package(attachment, platform):
                        (folder / filename(number, slot)).write_bytes(data)
                        item = dict(issue=number, title=title, description=description, platform=platform,
                                    attachment=attachment, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                        if slot is not None:
                            item.update(slot=slot, slotName=name)
                        submitted.append(item)
                    items.extend(submitted)
                published += 1
            except (OSError, ValueError, BadZipFile, RuntimeError, NotImplementedError):
                print(f"Issue #{number} has no usable save package.")
            if published == MAX_SAVES:
                break
        if len(issues) < 100 or published == MAX_SAVES:
            break
    active = {filename(item["issue"], item.get("slot")) for item in items}
    for file in folder.glob("*.bin"):
        if re.fullmatch(r"\d+(?:-\d+)?", file.stem) and file.name not in active:
            file.unlink()
    catalogue.write_text(json.dumps({"schemaVersion": 1, "items": items}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sync()
