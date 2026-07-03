"""Mixes narration + a music bed + optional SFX into one master audio track,
with the music sidechain-ducked under the narration via ffmpeg.

Music/SFX are licensed assets the user supplies locally (assets/music/,
assets/sfx/) — nothing here downloads audio. A missing music bed is a hard
failure, not a silent skip, since a ducked music bed is part of the spec.
"""

from __future__ import annotations

import random
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = REPO_ROOT / "assets" / "music"
SFX_DIR = REPO_ROOT / "assets" / "sfx"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


def _pick_random_asset(directory: Path) -> Path | None:
    candidates = [p for p in directory.glob("*") if p.suffix.lower() in AUDIO_EXTENSIONS]
    return random.choice(candidates) if candidates else None


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"audio_mixer: ffmpeg failed:\n{result.stderr}")


def run(config: dict, story: dict, output_dir: Path) -> dict:
    """Builds the ducked music+narration(+sfx) mix and writes it to
    output_dir/audio/mixed.mp3. Mutates and returns `story`.
    """
    mixer_cfg = config["audio_mixer"]
    narration_path = Path(story["narration_audio_path"])
    duration = story["narration_duration_sec"]

    music_path = _pick_random_asset(MUSIC_DIR)
    if music_path is None:
        raise RuntimeError(
            f"audio_mixer: no music files found in {MUSIC_DIR}. "
            "Add at least one royalty-free track (.mp3/.wav/.m4a/.ogg) before running the pipeline."
        )
    sfx_path = _pick_random_asset(SFX_DIR)

    mixed_path = output_dir / "audio" / "mixed.mp3"
    mixed_path.parent.mkdir(parents=True, exist_ok=True)

    inputs = [
        "-i", str(narration_path),
        "-stream_loop", "-1", "-i", str(music_path),
    ]
    if sfx_path is not None:
        inputs += ["-i", str(sfx_path)]

    filter_parts = [
        f"[1:a]volume={mixer_cfg['music_volume_db']}dB[music_pre]",
        "[music_pre][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=400[music_ducked]",
        # normalize=0: amix defaults to normalizing by input count (~-6dB for
        # 2 inputs), which would silently undercut the explicit dB levels
        # above. Levels are already set deliberately — don't let amix rescale them.
        "[0:a][music_ducked]amix=inputs=2:duration=first:weights=1 1:normalize=0[mix1]",
    ]
    final_label = "mix1"
    if sfx_path is not None:
        filter_parts.append(f"[2:a]volume={mixer_cfg['sfx_volume_db']}dB[sfx_pre]")
        filter_parts.append("[mix1][sfx_pre]amix=inputs=2:duration=first:normalize=0[mix2]")
        final_label = "mix2"

    fade_start = max(duration - mixer_cfg["fade_out_sec"], 0)
    filter_parts.append(
        f"[{final_label}]afade=t=out:st={fade_start}:d={mixer_cfg['fade_out_sec']}[mixed]"
    )

    args = [
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[mixed]",
        "-t", str(duration),
        str(mixed_path),
    ]
    _run_ffmpeg(args)

    story["mixed_audio_path"] = str(mixed_path)
    return story
