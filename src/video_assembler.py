"""Assembles the final vertical video: Ken Burns motion on each scene still,
burned-in word-grouped captions, muxed with the mixed audio track. All via
ffmpeg subprocess calls — no video-editing library dependency.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UPSCALE_FACTOR = 2  # scale stills up before zoompan so the zoom doesn't pixelate
MAX_ZOOM = 1.4


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"video_assembler: ffmpeg failed:\n{result.stderr}")


def _build_scene_clip(image_path: Path, duration: float, out_path: Path, video_cfg: dict) -> None:
    width, height, fps = video_cfg["width"], video_cfg["height"], video_cfg["fps"]
    frames = max(round(duration * fps), 1)
    zoom_increment = video_cfg["ken_burns_zoom_per_sec"] / fps
    upscale_w, upscale_h = width * UPSCALE_FACTOR, height * UPSCALE_FACTOR

    vf = (
        f"scale={upscale_w}:{upscale_h}:force_original_aspect_ratio=increase,"
        f"crop={upscale_w}:{upscale_h},"
        f"zoompan=z='min(zoom+{zoom_increment},{MAX_ZOOM})':d={frames}:s={width}x{height}:fps={fps}"
    )
    _run_ffmpeg([
        "-loop", "1", "-i", str(image_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        str(out_path),
    ])


def _concat_clips(clip_paths: list[Path], out_path: Path, output_dir: Path) -> None:
    list_path = output_dir / "video" / "concat_list.txt"
    list_path.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths),
        encoding="utf-8",
    )
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(out_path)])


def _seconds_to_ass_time(seconds: float) -> str:
    seconds = max(seconds, 0)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _group_captions(words: list[dict], max_words: int) -> list[dict]:
    groups = []
    for i in range(0, len(words), max_words):
        chunk = words[i : i + max_words]
        groups.append({
            "text": " ".join(w["text"] for w in chunk),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return groups


def _write_ass_file(story: dict, caption_cfg: dict, video_cfg: dict, out_path: Path) -> None:
    margin_v = 320 if caption_cfg["position"] == "bottom_safe" else 60
    groups = _group_captions(story["captions"], caption_cfg["max_words_per_caption"])

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_cfg['width']}
PlayResY: {video_cfg['height']}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{caption_cfg['font']},{caption_cfg['font_size']},{caption_cfg['color']},{caption_cfg['outline_color']},1,{caption_cfg['outline_width']},0,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Text
"""
    lines = [header]
    for group in groups:
        start = _seconds_to_ass_time(group["start"])
        end = _seconds_to_ass_time(group["end"])
        text = group["text"].replace("\n", " ")
        lines.append(f"Dialogue: 0,{start},{end},Default,{text}\n")

    out_path.write_text("".join(lines), encoding="utf-8")


def _escape_ffmpeg_filter_path(path: Path) -> str:
    # ffmpeg's filtergraph parser treats ':' as a syntax character, which
    # collides with Windows drive letters (C:\...) — escape it.
    return path.resolve().as_posix().replace(":", "\\:")


def run(config: dict, story: dict, output_dir: Path) -> Path:
    video_cfg = config["video_assembler"]
    caption_cfg = video_cfg["caption"]

    video_dir = output_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    clip_paths = []
    for index, scene in enumerate(story["scenes"]):
        duration = scene["end_sec"] - scene["start_sec"]
        clip_path = video_dir / f"clip_{index:02d}.mp4"
        _build_scene_clip(Path(scene["image_path"]), duration, clip_path, video_cfg)
        clip_paths.append(clip_path)

    silent_video_path = video_dir / "silent.mp4"
    _concat_clips(clip_paths, silent_video_path, output_dir)

    ass_path = video_dir / "captions.ass"
    _write_ass_file(story, caption_cfg, video_cfg, ass_path)

    duration = story["narration_duration_sec"]
    min_dur, max_dur = config["channel"]["min_duration_sec"], config["channel"]["max_duration_sec"]
    if not (min_dur - 5 <= duration <= max_dur + 5):
        print(
            f"video_assembler: WARNING narration duration {duration:.1f}s is outside the "
            f"target {min_dur}-{max_dur}s range.",
            file=sys.stderr,
        )

    final_path = output_dir / "final_video.mp4"
    _run_ffmpeg([
        "-i", str(silent_video_path),
        "-i", str(story["mixed_audio_path"]),
        "-vf", f"ass={_escape_ffmpeg_filter_path(ass_path)}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(final_path),
    ])

    story["video_path"] = str(final_path)
    return final_path
