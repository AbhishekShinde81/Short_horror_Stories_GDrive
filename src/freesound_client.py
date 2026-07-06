"""Sources audio from Freesound.org's free API, filtered to CC0-licensed
("Creative Commons 0") results only -- no attribution requirement and no
ambiguity for commercial use.

This is what audio_mixer.py uses for both:
- per-scene SFX one-shots (fetch_sfx), when audio_mixer.sfx_source is
  "freesound" (the default)
- the whole-video ambient music bed (fetch_music), when
  audio_mixer.music_source is "freesound" (the default) -- the real
  free/legal alternative to AI music generation. Hugging Face's Inference
  API serves zero providers for any text-to-audio model (MusicGen, Stable
  Audio Open, etc. all show an empty inferenceProviderMapping as of
  2026-07 -- see README), so there is no working free AI music-generation
  path; Freesound's CC0 catalog includes full ambient tracks/loops, not
  just short SFX, which covers the same need legally and for free.

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


def _cache_path(cache_dir: Path, keyword: str) -> Path:
    digest = hashlib.sha1(keyword.strip().lower().encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{digest}.mp3"


def _fetch(keyword: str, cache_dir: Path, duration_filter: str, sort: str) -> Path:
    api_key = os.environ.get("FREESOUND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "freesound_client: FREESOUND_API_KEY is not set. Get a free key at "
            "https://freesound.org/apiv2/apply/."
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(cache_dir, keyword)
    if cached.exists():
        return cached

    cc0_filter = f'license:"Creative Commons 0" {duration_filter}'
    try:
        response = requests.get(
            SEARCH_URL,
            params={
                "query": keyword,
                "filter": cc0_filter,
                "fields": "id,name,previews",
                "sort": sort,
                "page_size": 1,
            },
            headers={"Authorization": f"Token {api_key}"},
            timeout=REQUEST_TIMEOUT_SEC,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"freesound_client: search request failed for keyword {keyword!r}: {exc}") from exc

    results = response.json().get("results", [])
    if not results:
        raise RuntimeError(
            f"freesound_client: no CC0-licensed sound found for keyword {keyword!r}. "
            "Try a more common/generic keyword."
        )

    preview_url = results[0]["previews"]["preview-hq-mp3"]
    try:
        audio_response = requests.get(preview_url, timeout=REQUEST_TIMEOUT_SEC)
        audio_response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"freesound_client: preview download failed for keyword {keyword!r}: {exc}") from exc

    cached.write_bytes(audio_response.content)
    return cached


def fetch_sfx(keyword: str, cache_dir: Path) -> Path:
    """Returns a local path to a CC0-licensed one-shot SFX clip matching
    `keyword` (a scene's sfx_keyword), downloading and caching it by keyword
    so repeat keywords don't re-hit the API. Raises RuntimeError on a missing
    API key, no CC0 match, or a request failure -- callers decide whether
    that's fatal (audio_mixer.py skips the scene's SFX rather than failing
    the whole run).
    """
    # Duration capped at 12s -- these are one-shot cues, not beds.
    return _fetch(keyword, cache_dir, "duration:[0.1 TO 12]", sort="score")


def fetch_music(keyword: str, cache_dir: Path) -> Path:
    """Returns a local path to a CC0-licensed ambient track matching
    `keyword`, long enough to loop under narration (audio_mixer.py already
    loops the music input via ffmpeg's -stream_loop, so an exact-length
    match isn't required). Raises RuntimeError on a missing API key, no CC0
    match, or a request failure -- audio_mixer.py treats that as a hard
    failure for music, matching user_supplied's existing behavior.
    """
    # Sorted by rating, not raw relevance score -- an ambient bed plays under
    # the whole video, so a well-regarded track matters more here than for a
    # one-shot SFX cue.
    return _fetch(keyword, cache_dir, "duration:[15 TO 180]", sort="rating_desc")
