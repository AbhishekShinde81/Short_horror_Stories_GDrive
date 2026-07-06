"""Sources short one-shot SFX per scene from Freesound.org's free API,
filtered to CC0-licensed ("Creative Commons 0") sounds only -- no attribution
requirement and no ambiguity for commercial use, unlike the CC-BY-NC dead end
investigated for music in music_gen.py.

Requires a free Freesound account + API key (FREESOUND_API_KEY env var) --
see https://freesound.org/apiv2/apply/.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import requests

SEARCH_URL = "https://freesound.org/apiv2/search/text/"
REQUEST_TIMEOUT_SEC = 30
# Duration capped at 12s -- these are one-shot cues layered under a scene,
# not ambient beds.
CC0_FILTER = 'license:"Creative Commons 0" duration:[0.1 TO 12]'


def _cache_path(cache_dir: Path, keyword: str) -> Path:
    digest = hashlib.sha1(keyword.strip().lower().encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}.mp3"


def fetch(keyword: str, cache_dir: Path) -> Path:
    """Returns a local path to a CC0-licensed one-shot SFX clip matching
    `keyword`, downloading and caching it by keyword so repeat keywords
    (across scenes or runs) don't re-hit the API. Raises RuntimeError on a
    missing API key, no CC0 match, or a request failure -- callers decide
    whether that's fatal (see audio_mixer.py, which skips the scene's SFX
    rather than failing the whole run).
    """
    api_key = os.environ.get("FREESOUND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "freesound_sfx: FREESOUND_API_KEY is not set but audio_mixer.sfx_source "
            "is 'freesound'. Get a free key at https://freesound.org/apiv2/apply/."
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(cache_dir, keyword)
    if cached.exists():
        return cached

    try:
        response = requests.get(
            SEARCH_URL,
            params={
                "query": keyword,
                "filter": CC0_FILTER,
                "fields": "id,name,previews",
                "sort": "score",
                "page_size": 1,
            },
            headers={"Authorization": f"Token {api_key}"},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"freesound_sfx: search request failed for keyword {keyword!r}: {exc}") from exc

    results = response.json().get("results", [])
    if not results:
        raise RuntimeError(
            f"freesound_sfx: no CC0-licensed sound found for keyword {keyword!r}. "
            "Try a more common/generic keyword."
        )

    preview_url = results[0]["previews"]["preview-hq-mp3"]
    try:
        audio_response = requests.get(preview_url, timeout=REQUEST_TIMEOUT_SEC)
        audio_response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"freesound_sfx: preview download failed for keyword {keyword!r}: {exc}") from exc

    cached.write_bytes(audio_response.content)
    return cached
