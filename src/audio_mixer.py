"""Mixes narration + a music bed + optional per-scene SFX into one master
audio track, with the music sidechain-ducked under the narration via ffmpeg.

Both the music bed and SFX default to auto-sourcing from Freesound (see
freesound_client.py) rather than requiring locally-supplied files — there is
no working free AI audio-generation path (see music_gen.py's docstring), but
Freesound's CC0-licensed catalog covers the same need legally and for free:

- SFX: one CC0 one-shot per scene, timed to that scene's start_sec, using
  the "sfx_keyword" director_agent wrote for each scene. A failed lookup for
  one scene's keyword is skipped rather than failing the whole run — SFX is
  a nice-to-have, matching the old behavior where a missing assets/sfx/
  directory silently meant no SFX at all. Set audio_mixer.sfx_source to
  "user_supplied" to fall back to a single random track from assets/sfx/.
- Music: one CC0 ambient track using the "music_keyword" director_agent
  rotates per run, looped under the narration. A missing music bed is a hard
  failure, not a silent skip (matching user_supplied's existing behavior),
  since a ducked music bed is part of the spec. Set audio_mixer.music_source
  to "user_supplied" to fall back to a random track from assets/music/.
"""

from __future__ import annotations

import os
import random
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = REPO_ROOT / "assets" / "music"
SFX_DIR = REPO_ROOT / "assets" / "sfx"
FREESOUND_CACHE_ROOT = REPO_ROOT / "state" / "freesound_cache"
SFX_CACHE_DIR = FREESOUND_CACHE_ROOT / "sfx"
MUSIC_CACHE_DIR = FREESOUND_CACHE_ROOT / "music"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}


def _pick_random_asset(directory: Path) -> Path | None:
    candidates = [p for p in directory.glob("*") if p.suffix.lower() in AUDIO_EXTENSIONS]
    return random.choice(candidates) if candidates else None


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"audio_mixer: ffmpeg failed:\n{result.stderr}")


def _collect_sfx_cues(sfx_source: str, story: dict) -> list[tuple[float, Path]]:
    """Returns (start_sec, clip_path) pairs to overlay on the mix."""
    if sfx_source == "user_supplied":
        single = _pick_random_asset(SFX_DIR)
        return [(0.0, single)] if single is not None else []

    if sfx_source != "freesound":
        raise ValueError(
            f"audio_mixer: unknown audio_mixer.sfx_source {sfx_source!r} "
            "(expected 'user_supplied' or 'freesound')"
        )

    if not os.environ.get("FREESOUND_API_KEY"):
        raise RuntimeError(
            "audio_mixer: FREESOUND_API_KEY is not set but audio_mixer.sfx_source "
            "is 'freesound'. Get a free key at https://freesound.org/apiv2/apply/."
        )

    import freesound_client

    cues: list[tuple[float, Path]] = []
    for scene in story["scenes"]:
        keyword = scene.get("sfx_keyword")
        if not keyword:
            continue
        try:
            clip_path = freesound_client.fetch_sfx(keyword, SFX_CACHE_DIR)
        except RuntimeError as exc:
            print(f"audio_mixer: WARNING skipping SFX for {keyword!r}: {exc}")
            continue
        cues.append((scene["start_sec"], clip_path))
    return cues


def run(config: dict, story: dict, output_dir: Path) -> dict:
    """Builds the ducked music+narration(+sfx) mix and writes it to
    output_dir/audio/mixed.mp3. Mutates and returns `story`.
    """
    mixer_cfg = config["audio_mixer"]
    narration_path = Path(story["narration_audio_path"])
    duration = story["narration_duration_sec"]

    music_source = mixer_cfg.get("music_source", "user_supplied")
    if music_source == "musicgen_experimental_nc":
        import music_gen

        musicgen_cfg = mixer_cfg["musicgen"]
        music_path = music_gen.generate(
            prompt=musicgen_cfg["prompt"],
            model=musicgen_cfg["model"],
            out_path=output_dir / "audio" / "musicgen_track.wav",
        )
    elif music_source == "freesound":
        if not os.environ.get("FREESOUND_API_KEY"):
            raise RuntimeError(
                "audio_mixer: FREESOUND_API_KEY is not set but audio_mixer.music_source "
                "is 'freesound'. Get a free key at https://freesound.org/apiv2/apply/."
            )
        keyword = story.get("music_keyword")
        if not keyword:
            raise RuntimeError(
                "audio_mixer: story has no 'music_keyword' but audio_mixer.music_source "
                "is 'freesound' -- director_agent should have set this."
            )

        import freesound_client

        music_path = freesound_client.fetch_music(keyword, MUSIC_CACHE_DIR)
    elif music_source == "user_supplied":
        music_path = _pick_random_asset(MUSIC_DIR)
        if music_path is None:
            raise RuntimeError(
                f"audio_mixer: no music files found in {MUSIC_DIR}. "
                "Add at least one royalty-free track (.mp3/.wav/.m4a/.ogg) before running the pipeline."
            )
    else:
        raise ValueError(
            f"audio_mixer: unknown audio_mixer.music_source {music_source!r} "
            "(expected 'user_supplied', 'freesound', or 'musicgen_experimental_nc')"
        )

    sfx_source = mixer_cfg.get("sfx_source", "user_supplied")
    sfx_cues = _collect_sfx_cues(sfx_source, story)

    mixed_path = output_dir / "audio" / "mixed.mp3"
    mixed_path.parent.mkdir(parents=True, exist_ok=True)

    inputs = [
        "-i", str(narration_path),
        "-stream_loop", "-1", "-i", str(music_path),
    ]
    for _, clip_path in sfx_cues:
        inputs += ["-i", str(clip_path)]

    filter_parts = [
        f"[1:a]volume={mixer_cfg['music_volume_db']}dB[music_pre]",
        "[music_pre][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=400[music_ducked]",
        # normalize=0: amix defaults to normalizing by input count (~-6dB for
        # 2 inputs), which would silently undercut the explicit dB levels
        # above. Levels are already set deliberately — don't let amix rescale them.
        "[0:a][music_ducked]amix=inputs=2:duration=first:weights=1 1:normalize=0[mix1]",
    ]
    final_label = "mix1"
    if sfx_cues:
        sfx_labels = []
        for index, (start_sec, _) in enumerate(sfx_cues):
            input_index = 2 + index
            delay_ms = max(round(start_sec * 1000), 0)
            label = f"sfx{index}"
            filter_parts.append(
                f"[{input_index}:a]adelay=delays={delay_ms}:all=1,"
                f"volume={mixer_cfg['sfx_volume_db']}dB[{label}]"
            )
            sfx_labels.append(f"[{label}]")
        filter_parts.append(
            f"[mix1]{''.join(sfx_labels)}amix=inputs={len(sfx_cues) + 1}:duration=first:normalize=0[mix2]"
        )
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
