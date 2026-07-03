"""Uploads the finished video directly to YouTube via the Data API v3.
Defaults to unlisted when run.publish_mode is "review" — public posting is
an explicit config choice, never the default.

One-time local authorization: `python src/youtube_uploader.py --authorize`.
That produces token.json, which CI injects from a GitHub secret and this
module refreshes headlessly (no browser) on every run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET_PATH = REPO_ROOT / "client_secret.json"
TOKEN_PATH = REPO_ROOT / "token.json"


def _load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"{TOKEN_PATH} not found. Run `python src/youtube_uploader.py --authorize` "
            "locally once, then store its contents as the YOUTUBE_TOKEN_JSON GitHub secret."
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
    print(f"Saved YouTube credentials to {TOKEN_PATH}")


def run(config: dict, video_path: Path, story: dict) -> None:
    """Uploads video_path to YouTube using story['title'] / persona for
    metadata. publish_mode 'review' -> unlisted; 'public' -> public.
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt_cfg = config["youtube"]
    publish_mode = config["run"]["publish_mode"]
    privacy_status = (
        yt_cfg["privacy_status_public"] if publish_mode == "public" else yt_cfg["privacy_status_review"]
    )

    creds = _load_credentials()
    service = build("youtube", "v3", credentials=creds)

    description = (
        f"{story['premise_summary']}\n\n"
        f"Narrated by {story['persona']['name']}.\n\n"
        "This video was created with AI-generated narration, imagery, and voice."
    )

    body = {
        "snippet": {
            "title": story["title"][:100],
            "description": description,
            "tags": yt_cfg["tags"],
            "categoryId": yt_cfg["category_id"],
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": bool(yt_cfg["self_certify_synthetic"]),
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()

    print(f"youtube_uploader: uploaded video id={response['id']} privacyStatus={privacy_status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube uploader — one-time local OAuth authorization.")
    parser.add_argument("--authorize", action="store_true", help="Run the local OAuth consent flow.")
    args = parser.parse_args()
    if args.authorize:
        _authorize()
    else:
        parser.print_help()
