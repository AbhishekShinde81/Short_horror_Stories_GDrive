"""Uploads a full pipeline run to a Google Drive folder for manual review.
Uses the narrowest OAuth scope (drive.file) — the app can only see/touch
files it created itself, never the rest of the user's Drive.

Each run gets its own Drive subfolder (named by timestamp + run ID) under
config.yaml -> drive.folder_id, containing every artifact the pipeline
produced -- story JSON, scene images, narration/mixed audio, intermediate
video clips, captions -- so a run can be reviewed without re-running the
pipeline locally. The finished video is uploaded under a distinct
Final_Render_* name so it stands out among the intermediates.

One-time local authorization: `python src/drive_uploader.py --authorize`.
That produces drive_token.json, which CI injects from a GitHub secret and
this module refreshes headlessly (no browser) on every run.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

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


def _create_folder(service, name: str, parent_id: str) -> str:
    metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]}
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _upload_one(service, file_path: Path, parent_id: str, name: str | None = None) -> None:
    from googleapiclient.http import MediaFileUpload

    mime_type, _ = mimetypes.guess_type(file_path.name)
    metadata = {"name": name or file_path.name, "parents": [parent_id]}
    media = MediaFileUpload(str(file_path), mimetype=mime_type or "application/octet-stream", resumable=True)
    service.files().create(body=metadata, media_body=media, fields="id").execute()


def run(config: dict, video_path: Path, story: dict, output_dir: Path) -> None:
    """Creates one Drive subfolder for this run under config.yaml ->
    drive.folder_id and uploads every artifact under `output_dir` into it,
    mirroring its images/audio/video subfolder layout. The final video is
    uploaded separately under a Final_Render_* name.
    """
    from googleapiclient.discovery import build

    review_folder_id = config["drive"]["folder_id"]
    if not review_folder_id or review_folder_id == "REPLACE_WITH_YOUR_DRIVE_FOLDER_ID":
        raise RuntimeError("drive_uploader: config.yaml -> drive.folder_id is not set.")

    creds = _load_credentials()
    service = build("drive", "v3", credentials=creds)

    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    run_folder_name = f"{output_dir.name}_{run_id}"
    run_folder_id = _create_folder(service, run_folder_name, review_folder_id)

    subfolder_ids: dict[str, str] = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_dir() or path == video_path:
            continue  # the final video is uploaded separately below, under its Final_Render_* name

        relative_dir = str(path.parent.relative_to(output_dir))
        if relative_dir == ".":
            parent_id = run_folder_id
        else:
            if relative_dir not in subfolder_ids:
                subfolder_ids[relative_dir] = _create_folder(service, relative_dir, run_folder_id)
            parent_id = subfolder_ids[relative_dir]

        _upload_one(service, path, parent_id)

    final_name = f"Final_Render_{output_dir.name}.mp4"
    _upload_one(service, video_path, run_folder_id, name=final_name)

    print(f"drive_uploader: uploaded run '{run_folder_name}' (folder id={run_folder_id}) to Drive")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drive uploader — one-time local OAuth authorization.")
    parser.add_argument("--authorize", action="store_true", help="Run the local OAuth consent flow.")
    args = parser.parse_args()
    if args.authorize:
        _authorize()
    else:
        parser.print_help()
