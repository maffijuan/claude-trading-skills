#!/usr/bin/env python3
"""Upload files to a Google Drive folder using a service account.

Used by the After-Hours Market Screener GitHub Action to push the daily report
to Drive, but generic enough for any file. Credentials and target folder come
from environment variables so nothing secret is committed:

    GDRIVE_SERVICE_ACCOUNT_JSON  Service-account key, either the raw JSON string
                                 or a path to a .json file.
    GDRIVE_FOLDER_ID             Destination Drive folder ID (the part of the
                                 folder URL after ``/folders/``).

Usage:
    python3 scripts/upload_to_drive.py reports/after_hours_screener_*.md

The Google client libraries are imported lazily so the rest of the repo (and
its test suite) does not need them installed. The GitHub Action installs them.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _load_credentials():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        print("ERROR: GDRIVE_SERVICE_ACCOUNT_JSON not set", file=sys.stderr)
        return None
    from google.oauth2 import service_account

    # Accept either a path to a JSON file or the JSON content itself.
    if raw.startswith("{"):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    if Path(raw).is_file():
        return service_account.Credentials.from_service_account_file(raw, scopes=SCOPES)
    print("ERROR: GDRIVE_SERVICE_ACCOUNT_JSON is neither JSON nor a file path", file=sys.stderr)
    return None


def _expand(patterns: list[str]) -> list[str]:
    files: list[str] = []
    for pat in patterns:
        matched = glob.glob(pat)
        files.extend(matched if matched else ([pat] if Path(pat).is_file() else []))
    # De-dup, keep order.
    seen, out = set(), []
    for f in files:
        if f not in seen and Path(f).is_file():
            seen.add(f)
            out.append(f)
    return out


def upload(patterns: list[str]) -> int:
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        print("ERROR: GDRIVE_FOLDER_ID not set", file=sys.stderr)
        return 1

    files = _expand(patterns)
    if not files:
        print("WARN: no files matched; nothing to upload", file=sys.stderr)
        return 0

    creds = _load_credentials()
    if creds is None:
        return 1

    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    for path in files:
        meta = {"name": Path(path).name, "parents": [folder_id]}
        media = MediaFileUpload(path, resumable=True)
        created = (
            service.files()
            .create(body=meta, media_body=media, fields="id,name", supportsAllDrives=True)
            .execute()
        )
        print(f"Uploaded {path} -> Drive file id {created.get('id')}")
    return 0


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("Usage: upload_to_drive.py <file_or_glob> [more...]", file=sys.stderr)
        return 2
    return upload(argv)


if __name__ == "__main__":
    raise SystemExit(main())
