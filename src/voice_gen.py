"""TTS narration + word-level timestamps, via edge-tts (free, no API key,
uses Microsoft Edge's TTS endpoint).

Synthesizes the full narration in one call so the captions and per-scene
screen-time allocation stay aligned to a single continuous audio track,
rather than stitching together separately-synthesized scene clips.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

TICKS_PER_SECOND = 1e7  # edge-tts reports offset/duration in 100-nanosecond ticks


async def _synthesize(text: str, voice: str, rate: str, pitch: str, audio_path: Path) -> list[dict]:
    import edge_tts

    # boundary="WordBoundary" is required explicitly on edge-tts >= 7.1 --
    # it now defaults to sentence-level boundaries, which would silently
    # starve the per-word caption timing this pipeline depends on.
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    words: list[dict] = []
    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS_PER_SECOND
                end = start + chunk["duration"] / TICKS_PER_SECOND
                words.append({"text": chunk["text"], "start": start, "end": end})
    return words


def _assign_scene_timings(story: dict, total_duration: float) -> None:
    """Allocates screen-time to each scene proportional to its share of the
    total narration word count. An approximation (not aligned to exact
    per-scene word-boundary indices), but robust to edge-tts tokenizing
    words slightly differently than a naive whitespace split would.
    """
    scenes = story["scenes"]
    word_counts = [max(len(scene["narration"].split()), 1) for scene in scenes]
    total_words = sum(word_counts)

    cursor = 0.0
    for scene, word_count in zip(scenes, word_counts):
        share = total_duration * (word_count / total_words)
        scene["start_sec"] = cursor
        scene["end_sec"] = cursor + share
        cursor += share
    scenes[-1]["end_sec"] = total_duration  # pin exactly, avoid float drift


def run(config: dict, story: dict, output_dir: Path) -> dict:
    """Synthesizes narration audio, records word-level caption timestamps
    and per-scene screen-time on `story`, and returns it.
    """
    voice_cfg = config["voice_gen"]
    persona_name = story["persona"]["name"]
    voice_id = voice_cfg["voice_map"].get(persona_name)
    if not voice_id:
        raise RuntimeError(
            f"voice_gen: no voice mapped for persona {persona_name!r} in config.yaml voice_gen.voice_map"
        )

    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / "narration.mp3"

    words = asyncio.run(
        _synthesize(
            text=story["full_narration"],
            voice=voice_id,
            rate=voice_cfg["rate"],
            pitch=voice_cfg["pitch"],
            audio_path=audio_path,
        )
    )
    if not words:
        raise RuntimeError("voice_gen: edge-tts returned no word-boundary timestamps.")

    total_duration = words[-1]["end"]
    story["narration_audio_path"] = str(audio_path)
    story["narration_duration_sec"] = total_duration
    story["captions"] = words
    _assign_scene_timings(story, total_duration)

    return story
