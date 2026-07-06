"""Writes the story + scene spec that the rest of the pipeline builds on.

Talks only to llm_provider.get_provider(), never to a vendor SDK directly,
so the Gemini/Anthropic switch in config.yaml is the only thing that needs
to change to move providers.
"""

from __future__ import annotations

import json
import re

from llm_provider import get_provider

SYSTEM_TEMPLATE = """You are {persona_name}, the narrator of a short-form AI horror
story channel. Your tone: {persona_tone}. You write tight, atmospheric horror
stories meant to be narrated aloud in under a minute. You always end your
stories with a variation on your signature signoff: "{persona_signoff}"."""

USER_TEMPLATE = """Write one original short horror story for a ~{min_dur}-{max_dur} second
narrated vertical video (YouTube Shorts). Requirements:

- Total narration word count: 110-165 words (this must read aloud in {min_dur}-{max_dur}
  seconds at a slow, deliberate horror pace).
- Split the narration into 6-10 short scenes. Each scene is a few sentences of
  narration plus a one-sentence text-to-image prompt describing that scene's
  visual, in this rendering style: "{visual_style}". Image prompts must not
  contain any text/words to render, and must not depict real identifiable
  people.
- Also give each scene a "sfx_keyword": a literal, concrete 1-4 word phrase
  naming that scene's key sound SOURCE (e.g. "door creak", "footsteps on
  gravel", "distant thunder", "clock ticking", "static", "heartbeat"). This is
  used to search a sound-effects library by keyword, so name the physical
  sound, not a mood or adjective.
- The story must have a clear hook in the first scene and a twist or gut-punch
  in the final scene.
- Do NOT reuse these previously-used premises or twists (write something
  meaningfully different): {history_block}
- Also write a one-line "premise_summary" (under 20 words) capturing this
  story's core premise/twist, to be recorded so future stories can avoid
  repeating it.
- Also write a short "pinned_comment_draft": a friendly, in-character comment
  a creator might pin under the video (this will be reviewed and edited by a
  human before posting, never posted automatically).

Respond with ONLY raw JSON (no markdown fences, no commentary) matching this
exact schema:

{{
  "title": "string, under 60 chars",
  "premise_summary": "string, under 20 words",
  "scenes": [
    {{"narration": "string", "image_prompt": "string", "sfx_keyword": "string, 1-4 words, literal sound source"}}
  ],
  "pinned_comment_draft": "string"
}}
"""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def _select_persona(config: dict, history: dict) -> dict:
    personas = config["personas"]
    last_index = history.get("last_persona_index", -1)
    next_index = (last_index + 1) % len(personas)
    history["last_persona_index"] = next_index
    return personas[next_index]


def _select_visual_style(config: dict, history: dict) -> str:
    styles = config["image_gen"]["styles"]
    last_index = history.get("last_style_index", -1)
    next_index = (last_index + 1) % len(styles)
    history["last_style_index"] = next_index
    return styles[next_index]


def _history_block(history: dict, window: int) -> str:
    premises = history.get("premises", [])[-window:]
    if not premises:
        return "(none yet)"
    return "; ".join(premises)


def run(config: dict, history: dict) -> dict:
    """Generates one story spec. Mutates `history` in place (persona/style
    rotation cursors, premise log) — pipeline.py is responsible for
    persisting it back to state/history.json.
    """
    persona = _select_persona(config, history)
    visual_style = _select_visual_style(config, history)

    system = SYSTEM_TEMPLATE.format(
        persona_name=persona["name"],
        persona_tone=persona["tone"],
        persona_signoff=persona["signoff"],
    )
    user_prompt = USER_TEMPLATE.format(
        min_dur=config["channel"]["min_duration_sec"],
        max_dur=config["channel"]["max_duration_sec"],
        visual_style=visual_style,
        history_block=_history_block(history, config["run"]["history_window"]),
    )

    provider = get_provider(config["llm"])
    raw = provider.generate_story(prompt=user_prompt, system=system)

    try:
        story = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"director_agent: LLM did not return valid JSON. Raw output:\n{raw}"
        ) from exc

    for key in ("title", "premise_summary", "scenes", "pinned_comment_draft"):
        if key not in story:
            raise RuntimeError(f"director_agent: LLM output missing required key {key!r}: {story}")
    if not story["scenes"]:
        raise RuntimeError("director_agent: LLM returned zero scenes.")

    story["persona"] = persona
    story["visual_style"] = visual_style
    story["full_narration"] = " ".join(scene["narration"] for scene in story["scenes"])

    history.setdefault("premises", []).append(story["premise_summary"])
    history["premises"] = history["premises"][-config["run"]["history_window"] :]

    return story
