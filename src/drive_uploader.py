"""Uploads the finished video + story JSON to a Google Drive folder for
manual review. Uses the narrowest OAuth scope (drive.file) — the app can
only see/touch files it created itself, never the rest of the user's Drive.

One-time local authorization: `python src/drive_uploader.py --authorize`.
That produces drive_token.json, which CI injects from a GitHub secret and
this module refreshes headlessly (no browser) on every run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET_PATH = REPO_ROOT / "client_secret.json"
TOKEN_PATH = REPO_ROOT / "drive_token.json"


def _load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"{TOKEN_PATH} not found. Run `python src/drive_uploader.py --authorize` "
            "locally once, then store its contents as the GOOGLE_DRIVE_TOKEN_JSON GitHub secret."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _authorize() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_SECRET_PATH.exists():
        raise RuntimeError(
            f"{CLIENT_SECRET_PATH} not found. Download a Desktop app OAuth client "
            "from Google Cloud Console -> Credentials and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved Drive credentials to {TOKEN_PATH}")


def run(config: dict, video_path: Path, story: dict) -> None:
    """Uploads the video and story JSON into config.yaml -> drive.folder_id."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    folder_id = config["drive"]["folder_id"]
    if not folder_id or folder_id == "REPLACE_WITH_YOUR_DRIVE_FOLDER_ID":
        raise RuntimeError("drive_uploader: config.yaml -> drive.folder_id is not set.")

    creds = _load_credentials()
    service = build("drive", "v3", credentials=creds)

    video_metadata = {"name": video_path.name, "parents": [folder_id]}
    video_media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    service.files().create(body=video_metadata, media_body=video_media, fields="id").execute()

    story_path = video_path.parent / "story.json"
    story_path.write_text(json.dumps(story, indent=2), encoding="utf-8")
    story_metadata = {"name": story_path.name, "parents": [folder_id]}
    story_media = MediaFileUpload(str(story_path), mimetype="application/json")
    service.files().create(body=story_metadata, media_body=story_media, fields="id").execute()

    print(f"drive_uploader: uploaded {video_path.name} and story.json to Drive folder {folder_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drive uploader — one-time local OAuth authorization.")
    parser.add_argument("--authorize", action="store_true", help="Run the local OAuth consent flow.")
    args = parser.parse_args()
    if args.authorize:
        _authorize()
    else:
        parser.print_help()
