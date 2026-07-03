"""Orchestrates one end-to-end run:

    director_agent -> image_gen -> voice_gen -> audio_mixer
        -> video_assembler -> (drive_uploader | youtube_uploader)

Each stage is an independent module with a single run() entry point, so any
stage can be tested or swapped in isolation. This file only wires them
together and owns the top-level failure boundary: any exception here exits
non-zero (a visible failed run in GitHub Actions) rather than retrying with
different content.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

import audio_mixer
import director_agent
import image_gen
import video_assembler
import voice_gen

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
HISTORY_PATH = REPO_ROOT / "state" / "history.json"
OUTPUT_ROOT = REPO_ROOT / "output"


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def _make_output_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / stamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _upload(config: dict, video_path: Path, story: dict) -> None:
    destination = config["run"]["destination"]
    if destination == "drive":
        import drive_uploader

        drive_uploader.run(config, video_path, story)
    elif destination == "youtube":
        import youtube_uploader

        youtube_uploader.run(config, video_path, story)
    else:
        raise ValueError(f"Unknown run.destination: {destination!r} (expected 'drive' or 'youtube')")


def main() -> None:
    config = _load_config()
    history = _load_history()
    output_dir = _make_output_dir()

    print(f"pipeline: writing outputs to {output_dir}")

    story = director_agent.run(config, history)
    print(f"pipeline: director_agent wrote story {story['title']!r} ({len(story['scenes'])} scenes)")

    story = image_gen.run(config, story, output_dir)
    print("pipeline: image_gen generated all scene images")

    story = voice_gen.run(config, story, output_dir)
    print(f"pipeline: voice_gen synthesized narration ({story['narration_duration_sec']:.1f}s)")

    story = audio_mixer.run(config, story, output_dir)
    print("pipeline: audio_mixer produced the mixed audio track")

    video_path = video_assembler.run(config, story, output_dir)
    print(f"pipeline: video_assembler produced {video_path}")

    story_path = output_dir / "story.json"
    story_path.write_text(json.dumps(story, indent=2), encoding="utf-8")

    _upload(config, video_path, story)

    _save_history(history)
    print("pipeline: done.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
