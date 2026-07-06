# AI Horror Shorts Pipeline

Fully automated pipeline that generates short-form AI-narrated horror stories
as vertical videos (1080x1920, 40-58s), and either saves the finished video
to a Google Drive folder for manual review or uploads it directly to
YouTube — controlled by `config.yaml`, not a code change. Runs on a daily
GitHub Actions schedule, entirely on free tiers unless you opt into the
Anthropic LLM path.

## Pipeline

```
director_agent -> image_gen -> voice_gen -> audio_mixer -> video_assembler -> uploader
```

Every stage is its own module in `src/` with a single `run()` entry point,
so any stage can be tested or swapped independently. A failed run exits
non-zero and shows up as a failed GitHub Actions run — the pipeline never
silently retries with different content.

## Setup

Do these in order.

| # | What | Free? | Where |
|---|------|-------|-------|
| 1 | Google account | — | for AI Studio, Cloud Console, Drive, YouTube |
| 2 | `GEMINI_API_KEY` | Yes, free tier | [aistudio.google.com](https://aistudio.google.com) -> Get API Key |
| 3 | `ANTHROPIC_API_KEY` (optional, only if `llm.provider: anthropic`) | No, billed | [console.anthropic.com](https://console.anthropic.com) |
| 4 | Google Cloud project with **YouTube Data API v3** + **Google Drive API** enabled | Yes | [console.cloud.google.com](https://console.cloud.google.com) |
| 5 | OAuth 2.0 Client (**Desktop app** type) -> `client_secret.json` | Yes | same Cloud project, Credentials page |
| 6 | One-time local OAuth authorization -> `token.json` (YouTube) and/or `drive_token.json` (Drive) | Yes | run each uploader's `--authorize` flag locally (see below) |
| 7 | GitHub account + new repo | Yes | for code + Actions scheduling |
| 8 | GitHub repo secrets: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` (optional), `YOUTUBE_TOKEN_JSON`, `GOOGLE_DRIVE_TOKEN_JSON`, `FREESOUND_API_KEY` | Yes | repo Settings -> Secrets and variables -> Actions |
| 9 | ffmpeg | Yes | installed on the GitHub Actions runner via `apt`; install locally too for local testing |
| 10 | Pollinations.ai (image gen) | Yes, no key needed | called directly, no signup |
| 11 | edge-tts (voice gen) | Yes, no key needed | Python package, uses Microsoft Edge's TTS endpoint |
| 12 | `FREESOUND_API_KEY` (music + SFX sourcing, default for both) | Yes, free forever | [freesound.org/apiv2/apply](https://freesound.org/apiv2/apply/) — needs a free Freesound account first |

> **Anthropic billing note:** `ANTHROPIC_API_KEY` usage is billed separately
> through the Anthropic API/Console. A Claude.ai / Claude Pro subscription
> does **not** include API credits — you need a funded API account to use
> `llm.provider: anthropic`.

> **Model names drift.** Google and Anthropic periodically rename or
> deprecate model IDs. Before a long-lived deployment, double-check
> `config.yaml -> llm.gemini.model` / `llm.anthropic.model` are still valid
> at [aistudio.google.com/models](https://aistudio.google.com/models) and
> the [Claude model docs](https://platform.claude.com/docs/en/about-claude/models/overview).

### Step-by-step

1. **Clone this repo** and `pip install -r requirements.txt` locally (Python 3.11+, plus a local `ffmpeg` install for testing).
2. **Get a Gemini API key** (step 2 above) — this is the default, free LLM provider.
3. **Create a Google Cloud project**, enable the YouTube Data API v3 and Google Drive API, and create an OAuth 2.0 **Desktop app** client. Download it as `client_secret.json` into the repo root (it's gitignored — never commit it).
4. **Authorize locally, once per destination you plan to use:**
   ```
   python src/drive_uploader.py --authorize     # -> drive_token.json
   python src/youtube_uploader.py --authorize   # -> token.json
   ```
   Each opens a browser consent screen and writes a token file to the repo root.
5. **Nothing to add to `assets/music/` or `assets/sfx/` by default** — both
   music and SFX auto-source from Freesound (see "Music" and "SFX" below).
   Those folders only matter if you switch either `audio_mixer.music_source`
   or `.sfx_source` to `"user_supplied"`.
6. **Set `drive.folder_id`** in `config.yaml` to the target Drive folder's ID (from its URL).
7. **Create a new GitHub repo**, push this code, and add the repo secrets listed in row 8 of the table above — paste the full contents of `token.json` / `drive_token.json` as the secret values.
8. The workflow in `.github/workflows/publish.yml` runs once/day and on manual dispatch (`workflow_dispatch`).

## Running one video locally

```
pip install -r requirements.txt
export GEMINI_API_KEY=...          # or set ANTHROPIC_API_KEY if using that provider
export FREESOUND_API_KEY=...       # default source for both music and SFX
python src/pipeline.py
```

Output lands in `output/<timestamp>/` — story JSON, per-scene images, audio,
and `final_video.mp4`. This directory is gitignored.

## Flipping the switches

Both switches are pure config — no code edits.

**LLM provider** (`config.yaml -> llm.provider`):
```yaml
llm:
  provider: "anthropic"   # was "gemini"
```
Only the env var matching the active provider is required at runtime —
switching to `anthropic` does not require `GEMINI_API_KEY` to be set, and
vice versa.

**Upload destination** (`config.yaml -> run.destination`):
```yaml
run:
  destination: "youtube"   # was "drive"
  publish_mode: "review"   # "review" = unlisted, "public" = public
```

## Music & SFX: why Freesound instead of AI generation

There is no working free AI audio-generation path as of 2026-07. Every
serious free text-to-audio option was checked and is a dead end:

- **Hugging Face Inference API** (`facebook/musicgen-small/medium/large`,
  `musicgen-melody`, `stabilityai/stable-audio-open-1.0`/`-small`,
  `declare-lab/tango2`) — confirmed live via HF's own model API
  (`inferenceProviderMapping` is `{}` for every one of them): zero providers,
  including HF's own `hf-inference`, currently serve any of these models.
  This fails immediately regardless of `HF_API_TOKEN`. Even when this path
  worked, MusicGen's weights are CC-BY-NC 4.0 (non-commercial), so it was
  personal/offline preview only, never suitable for a monetized or public
  channel.
- **Pollinations.ai's `elevenmusic`** — works, but costs ~$0.40/generation
  with no free tier, and its commercial-use terms are unresolved even for
  paid use — see
  [pollinations/pollinations#8741](https://github.com/pollinations/pollinations/issues/8741),
  an open licensing question with no response.

**The actual fix: [Freesound.org](https://freesound.org)'s free API isn't
just short SFX — its CC0 ("Creative Commons 0") catalog also includes full
ambient tracks and loops.** CC0 has no attribution requirement and no
commercial-use ambiguity, so this is safe for a monetized/public channel,
unlike every AI-generation option above. `freesound_client.py` is the shared
module both of the below use — same API key, same license guarantee, nothing
to manually source or keep in the repo.

`config.yaml -> audio_mixer.music_source` (default `"freesound"`):
- **`"freesound"`** — `director_agent` rotates through
  `audio_mixer.freesound_music_keywords` once per run (round-robin, same
  pattern as persona/visual-style rotation), searches for a CC0 track
  15-180s long sorted by rating, downloads it, and loops it under the
  narration (ffmpeg `-stream_loop`). Cached in `state/freesound_cache/music/`
  by keyword. A missing/failed match is a **hard failure** (matching
  `user_supplied`'s original behavior) since a music bed is part of the spec.
- **`"user_supplied"`** — picks a random track from `assets/music/` instead —
  useful if you'd rather curate your own tracks.
- **`"musicgen_experimental_nc"`** — kept in the code in case HF adds a
  provider back; currently dead weight, see above.

`config.yaml -> audio_mixer.sfx_source` (default `"freesound"`):
- **`"freesound"`** — `director_agent` writes a short, literal `sfx_keyword`
  per scene (e.g. "door creak", "distant thunder"), searched for a CC0
  one-shot (under 12s) and overlaid at that scene's start time. Cached in
  `state/freesound_cache/sfx/` by keyword. A scene whose keyword returns no
  CC0 match is skipped (logged as a warning), not a hard failure — SFX is a
  nice-to-have.
- **`"user_supplied"`** — picks one random track from `assets/sfx/` for the
  whole video (or plays no SFX at all if that folder is empty).

Both require a free `FREESOUND_API_KEY` (see setup table above).

## Anti-flagging / "doesn't look like a spam bot" features

- Rotating narrator persona (name, tone, signoff) and rotating visual style,
  both cycled round-robin via `state/history.json` (committed back to the
  repo by the workflow), so the channel has a consistent voice per video
  instead of looking templated.
- `director_agent` tracks recently-used story premises/twists in
  `state/history.json` and instructs the LLM to avoid repeating them within
  `run.history_window` runs.
- `director_agent` writes a suggested pinned-comment draft into the story
  JSON output — see "What this does NOT do" below.
- `self_certify_synthetic` (config.yaml -> youtube.self_certify_synthetic)
  sets YouTube's `containsSyntheticMedia` disclosure flag when
  `destination: youtube`.

## What this does NOT do

- **Does not auto-post the pinned comment.** `director_agent` writes a
  `pinned_comment_draft` into the story JSON as a suggestion. A human should
  read it, edit it, and post it themselves — it is intentionally never
  posted automatically.
- **Does not auto-retry with different content on failure.** Any stage
  failing exits the whole pipeline non-zero. It does not silently regenerate
  the story, swap providers, or retry with different inputs — you get a
  visibly failed GitHub Actions run to investigate.
- **Does not manage your Drive or YouTube account beyond what it creates.**
  The Drive integration uses the `drive.file` scope, which only lets the app
  see files it created itself.

## Repo structure

```
config.yaml               # every behavioral knob
requirements.txt
src/
  llm_provider.py          # Gemini/Anthropic interface + both implementations
  director_agent.py
  image_gen.py
  voice_gen.py
  audio_mixer.py
  freesound_client.py      # CC0 music/SFX search+download, used by default for both
  music_gen.py             # dead (non-commercial + no HF provider) MusicGen path, kept opt-in
  video_assembler.py
  drive_uploader.py
  youtube_uploader.py
  pipeline.py
assets/music/                    # only used if music_source: "user_supplied"
assets/sfx/                      # only used if sfx_source: "user_supplied"
state/history.json               # rotation cursors + recent premises, committed by CI
state/freesound_cache/{music,sfx}/  # downloaded Freesound clips, gitignored, regenerable
.github/workflows/publish.yml
```
