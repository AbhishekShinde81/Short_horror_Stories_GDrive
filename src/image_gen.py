"""One text-to-image call per scene via Pollinations.ai (free, no API key).

Pollinations enforces an anonymous rate limit (~1 request per 15s), so calls
are spaced out with a fixed delay rather than fired concurrently.
"""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

import requests

POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"
REQUEST_DELAY_SEC = 16
REQUEST_TIMEOUT_SEC = 90
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SEC = 20


def _generate_one(prompt: str, width: int, height: int, model: str, seed: int) -> bytes:
    encoded_prompt = urllib.parse.quote(prompt, safe="")
    url = f"{POLLINATIONS_BASE_URL}/{encoded_prompt}"
    params = {
        "width": width,
        "height": height,
        "model": model,
        "seed": seed,
        "nologo": "true",
    }

    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC)
            response.raise_for_status()
            return response.content
        except requests.exceptions.HTTPError as exc:
            # A 4xx (bad prompt/params) won't fix itself on retry -- fail immediately.
            if exc.response is not None and exc.response.status_code < 500:
                raise
            last_exc = exc
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc

        if attempt < MAX_ATTEMPTS:
            print(f"image_gen: attempt {attempt}/{MAX_ATTEMPTS} failed ({last_exc}); retrying in {RETRY_BACKOFF_SEC}s")
            time.sleep(RETRY_BACKOFF_SEC)

    raise RuntimeError(f"image_gen: Pollinations request failed after {MAX_ATTEMPTS} attempts: {last_exc}") from last_exc


def run(config: dict, story: dict, output_dir: Path) -> dict:
    """Fetches one image per scene, writes it to output_dir/images/, and
    records the path on each scene dict. Mutates and returns `story`.
    """
    image_cfg = config["image_gen"]
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    for index, scene in enumerate(story["scenes"]):
        prompt = f"{scene['image_prompt']}, {story['visual_style']}"
        seed = abs(hash((story["title"], index))) % (2**31)

        image_bytes = _generate_one(
            prompt=prompt,
            width=image_cfg["width"],
            height=image_cfg["height"],
            model=image_cfg["model"],
            seed=seed,
        )

        image_path = images_dir / f"scene_{index:02d}.png"
        image_path.write_bytes(image_bytes)
        scene["image_path"] = str(image_path)

        if index < len(story["scenes"]) - 1:
            time.sleep(REQUEST_DELAY_SEC)

    return story
