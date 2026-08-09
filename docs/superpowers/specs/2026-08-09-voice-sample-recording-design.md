# Voice sample recording — capture a reference clip for TTS cloning

**Date:** 2026-08-09
**Status:** design, approved
**Touches:** `runtime/voice_sample.py` (new), `runtime/chat_app.py`

The cookbook already fits a TTS model with voice cloning (`cookbook/fit.py`,
`cookbook/catalogue.json` — XTTS-v2, F5-TTS, and eventually
Qwen3-TTS-12Hz-1.7B-CustomVoice, `Placement.cloning`) and the container brings
it up as a resident server (`cookbook/README.md`). Nothing yet captures the
one thing every one of those models clones from: a reference clip of the
creator's actual voice. This spec adds exactly that capture step. It does not
touch TTS inference, model serving, or the cookbook's model selection —
those are later work.

## Storage

One file:

```
data/voice/sample.wav
```

Zero-shot cloning models (XTTS-v2, F5-TTS, Qwen3-TTS-CustomVoice) clone
timbre from a single reference clip and can synthesize in any language the
model supports from it — the reference's language does not have to match the
output language. So one clip is sufficient; there is no per-language file.
`data/voice/` sits under `data/`, gitignored by default per CLAUDE.md's
privacy rule — nothing new needed there.

Re-recording overwrites `sample.wav`. Before the overwrite, the existing file
is copied into `data/voice/.backups/sample.wav.<UTC timestamp>` — the exact
`snapshot()` helper `runtime/tools.py` already uses for the bible and story
writes, imported as-is, no changes to it. Same undo story as everywhere else
in the corpus: `data/` has no version control, so this snapshot is the only
way back.

## Phrase text

The language picker selects which phrase is shown to read aloud — it has no
effect on the file that gets written (there is only ever one file). It exists
because the admin may find one language more natural to read fluently than
another, and a comfortably-read take makes a better reference clip than a
stumbled-through one.

Phrases are static, hardcoded, and chosen for verifiable correctness rather
than invented per language — this is a reading script, not character content,
so CLAUDE.md's cite/authorship rule doesn't apply to it, but a mistranslated
sentence is still a bad script. Nine languages, each a well-known public text
long enough to read in roughly 15–25 seconds:

| Lang | Text |
|---|---|
| `en` | English pangram trio (fox/box/zebras) |
| `fr` | Classic French pangrams (whisky/juge; voix ambiguë) |
| `de` | Classic German pangram (Boxkämpfer) |
| `ru` | Classic Russian pangram (булок) |
| `es` | Classic Spanish pangram pair (murciélago; cigüeña) |
| `pt` | Classic Portuguese pangram (jabuti) |
| `zh` | Li Bai's 静夜思 — a four-line poem essentially every native speaker knows |
| `ja` | いろは (Iroha) — traditionally *the* Japanese phonetic-coverage text, one of every kana |
| `ar` | The standard Arabic font-test pangram |

Full text lives in `runtime/voice_sample.py::PHRASES`, one dict, easy to
correct later if a phrase turns out wrong — this spec does not claim
linguistic authority, just a reasonable starting script.

## `runtime/voice_sample.py` (new)

```python
VOICE_DIR = PROFILE_PATH.parent / "voice"      # data/voice
SAMPLE_PATH = VOICE_DIR / "sample.wav"

LANGUAGES: list[tuple[str, str]]                # [(code, display name), ...]
PHRASES: dict[str, str]                         # code -> phrase text

def save_sample(data: bytes) -> Path:
    """Snapshot the existing sample (if any), then write `data` over it."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_PATH.exists():
        snapshot(SAMPLE_PATH)          # runtime/tools.py, reused unchanged
    SAMPLE_PATH.write_bytes(data)
    return SAMPLE_PATH

def sample_status() -> str | None:
    """Human-readable 'recorded <date>' or None if never recorded."""
```

`_self_check()` under `if __name__ == "__main__"`, matching the convention
every other `runtime/*.py` module already follows (`tools.py`,
`story_tools.py`, `index.py`): writes bytes to a temp `SAMPLE_PATH` override,
confirms a snapshot is taken on the second write and not the first, confirms
`sample_status()` reflects presence/absence. No pytest, no fixtures — a
plain assert script, run directly.

## UI — `runtime/chat_app.py` sidebar

New section, agent-mode only (`status.get("agent")`), next to the existing
Snapshots section — the fan surface gets no writes, per CLAUDE.md, and this
is a write.

```
Sidebar
  ...
  ── Voice sample ──────────────
  "recorded 2026-08-09" / "not recorded yet"
  [ Record voice sample ]  → opens dialog
```

`st.dialog` (same pattern as `confirm_dialog`):

- `st.selectbox` — language, from `LANGUAGES`
- the phrase for the selected language, shown as read-along text
- `st.audio_input` — Streamlit's native mic-capture widget (ships in
  `streamlit>=1.40`, already pinned in `cookbook/requirements.txt` — no new
  dependency). Its own UI already lets the admin re-record before deciding
  anything; nothing is written to disk until Save.
- **Save** (enabled once something is recorded) → `save_sample(audio.getvalue())`,
  success toast, `st.rerun()` closes the dialog
- **Cancel** → closes the dialog, nothing touches disk

No diff view — unlike the text proposals `confirm_dialog` shows, this is
binary audio; the widget's own playback is the "before you commit" check.

## Out of scope

- Actually running a TTS model against `sample.wav` (inference, serving,
  which library vs. which model) — separate, later work.
- Multiple stored takes / take history — one file, overwritten, is enough per
  the single-clip-clones-everything reasoning above.
- Recording quality checks (silence detection, clipping, duration minimums) —
  can be added later if a bad take turns out to produce bad clones; not
  guessed at now.
- `data/voice/sample.wav` is the most directly identifying artifact in the
  repo — a voiceprint of a real person. It's gitignored and unreachable from
  any surface today (this feature adds no HTTP endpoint). Whatever eventually
  serves TTS inference must expose synthesis only, never this file, and any
  future backup/export tooling must exclude `data/voice/` explicitly — not
  designed now, just flagged so it isn't rediscovered later.
