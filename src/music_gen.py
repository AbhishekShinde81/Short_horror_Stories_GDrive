"""EXPERIMENTAL, NON-COMMERCIAL music generation via Hugging Face's free
Inference API (facebook/musicgen-small by default).

MusicGen's model weights are licensed CC-BY-NC 4.0 (non-commercial), and that
restriction covers audio generated with them -- not just the code. Do not
enable this (audio_mixer.music_source: "musicgen_experimental_nc" in
config.yaml) for a monetized or public-facing channel. It exists for
personal/offline previewing of the pipeline only. The default config uses
your own royalty-free tracks in assets/music/ instead, which is the only
path here with a clean, verifiable commercial license.

Requires a free Hugging Face account + access token (HF_API_TOKEN env var) --
see huggingface.co/settings/tokens.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

NON_COMMERCIAL_WARNING = (
    "music_gen: using MusicGen-generated audio (CC-BY-NC 4.0, NON-COMMERCIAL "
    "ONLY per Meta's model license). Do not publish this to a monetized or "
    "public YouTube channel -- personal/offline preview use only."
)


def generate(prompt: str, model: str, out_path: Path) -> Path:
    """Generates one instrumental clip from `prompt` and writes it to
    `out_path`. Raises RuntimeError with a clear message on any failure
    (missing token, model error) rather than silently falling back.
    """
    print(NON_COMMERCIAL_WARNING, file=sys.stderr)

    token = os.environ.get("HF_API_TOKEN")
    if not token:
        raise RuntimeError(
            "music_gen: HF_API_TOKEN is not set but audio_mixer.music_source "
            "is 'musicgen_experimental_nc'. Get a free token at "
            "https://huggingface.co/settings/tokens."
        )

    from huggingface_hub import InferenceClient

    client = InferenceClient(token=token, provider="hf-inference")
    try:
        audio_bytes = client.text_to_speech(text=prompt, model=model)
    except Exception as exc:
        raise RuntimeError(f"music_gen: generation failed for model {model!r}: {exc}") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)
    return out_path
