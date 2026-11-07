# PSN-HUB Saves

Public archive for reviewed PS4 and PS5 saves shared through PSN-HUB Community Saves.

[Browse the catalogue](catalog.json) · [Download approved saves](https://github.com/ItssJustAaron/PSN-HUB-Saves/releases) · [Community Saves guide](https://github.com/ItssJustAaron/PSN-HUB2/blob/main/Manager/COMMUNITY-SAVES.md)

The catalogue starts empty. Entries are added after review and consent to public sharing.

## Publishing an approved save

1. In the Community Saves reviewer view, verify the save and confirm the submitter agreed to public distribution. Approve it and download the encrypted image and the companion key for PS4, if present.
2. ZIP the image and any required key. Keep the files together. Attach the ZIP to a GitHub Release with a unique tag.
3. Add an entry to `catalog.json` with `title` (game name), `titleId` (CUSA or PPSA ID), `platform` (`ps4` or `ps5`), `description`, `downloadUrl` (the public release asset link), and `sha256` (the ZIP's SHA-256 in lowercase hex).
4. Verify the download link and checksum. If a save is withdrawn, remove the release asset and its catalogue entry.

To use a downloaded save, extract the ZIP and open **Saves → Advanced save tools** in PSN-HUB Manager. Select the correct platform and console user. For PS4, select both the image and its companion key.
