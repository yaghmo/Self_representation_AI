# Voice Sample Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the admin record one reference audio clip of their own voice (in a Streamlit dialog, native mic capture, confirm-to-save / cancel-to-redo), for future TTS voice cloning.

**Architecture:** A new pure-function module (`runtime/voice_sample.py`) owns storage — one file, `data/voice/sample.wav`, snapshotted before every overwrite via the existing `runtime/tools.py::snapshot()`. A new sidebar section + `st.dialog` in `runtime/chat_app.py` is the only caller, admin-mode only.

**Tech Stack:** Streamlit's native `st.audio_input` (already available — `streamlit>=1.40` is pinned in `cookbook/requirements.txt`). No new dependency.

## Global Constraints

- Voice-sample writes are admin-only (`status.get("agent")` gate) — the fan surface gets no writes, per `CLAUDE.md`.
- `data/voice/` lives under `data/`, already gitignored by default — no `.gitignore` change needed.
- One file, always overwritten (`data/voice/sample.wav`) — no per-language files, per the design spec.
- Snapshot-before-overwrite reuses `runtime/tools.py::snapshot(path)` unchanged — do not modify `tools.py`.
- No pytest in this repo (`tests/` doesn't exist) — every `runtime/*.py` module instead carries a `_self_check()` under `if __name__ == "__main__":`, plain asserts, run via `python -m runtime.<module>`. Follow that convention, not pytest.
- Full design: `docs/superpowers/specs/2026-08-09-voice-sample-recording-design.md`.

---

### Task 1: `runtime/voice_sample.py`

**Files:**
- Create: `runtime/voice_sample.py`

**Interfaces:**
- Consumes: `runtime.bible.PROFILE_PATH` (`Path`, already exists — `data/character.md`), `runtime.tools.snapshot` (`Callable[[Path], Path | None]`, already exists).
- Produces (for Task 2): `LANGUAGES: list[tuple[str, str]]` (code, display name), `PHRASES: dict[str, str]` (code -> phrase text, keys exactly match `LANGUAGES` codes), `save_sample(data: bytes) -> Path`, `sample_status() -> str | None`.

- [ ] **Step 1: Write the module with a failing self-check**

Create `runtime/voice_sample.py`:

```python
"""Reference-audio capture for TTS voice cloning.

Zero-shot cloning models (XTTS-v2, F5-TTS, Qwen3-TTS-CustomVoice) clone
timbre from one reference clip and can synthesize in any language the model
supports from it — the reference's own language doesn't have to match the
output language. So there is exactly one file, not one per language. The
language picker in the UI only decides which phrase is shown to read aloud,
never which file gets written.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .bible import PROFILE_PATH
from .tools import snapshot

VOICE_DIR = PROFILE_PATH.parent / "voice"
SAMPLE_PATH = VOICE_DIR / "sample.wav"

LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("ru", "Russian"),
    ("es", "Spanish"),
    ("pt", "Portuguese"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ar", "Arabic"),
]

# Static reference scripts, not character content — CLAUDE.md's cite/
# authorship rule doesn't apply here. Chosen for verifiable correctness
# (well-known public texts) over invented-per-language sentences: classic
# pangrams for the Latin/Cyrillic-script languages, and for the two
# languages without a Western-style pangram tradition, the text each
# language actually uses for phonetic-coverage purposes — Li Bai's 静夜思
# for Chinese, いろは (Iroha) for Japanese.
PHRASES: dict[str, str] = {
    "en": (
        "The quick brown fox jumps over the lazy dog. Pack my box with five "
        "dozen liquor jugs. How vexingly quick daft zebras jump!"
    ),
    "fr": (
        "Portez ce vieux whisky au juge blond qui fume. Voix ambiguë d'un "
        "cœur qui au zéphyr préfère les jattes de kiwis."
    ),
    "de": "Zwölf Boxkämpfer jagen Viktor quer über den großen Sylter Deich.",
    "ru": "Съешь же ещё этих мягких французских булок, да выпей чаю.",
    "es": (
        "El veloz murciélago hindú comía feliz cardillo y kiwi. La cigüeña "
        "tocaba el saxofón detrás del palenque de paja."
    ),
    "pt": "Um pequeno jabuti xereta viu dez cegonhas felizes.",
    "zh": "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
    "ja": (
        "いろはにほへと ちりぬるを わかよたれそ つねならむ "
        "うゐのおくやま けふこえて あさきゆめみし ゑひもせす（ん）"
    ),
    "ar": "نص حكيم له سر قاطع وذو شأن عظيم مكتوب على ثوب أخضر ومغلف بجلد أزرق",
}


def save_sample(data: bytes) -> Path:
    """Snapshot the existing clip (if any), then write `data` over it."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_PATH.exists():
        snapshot(SAMPLE_PATH)
    SAMPLE_PATH.write_bytes(data)
    return SAMPLE_PATH


def sample_status() -> str | None:
    """'recorded <UTC date>', or None if nothing has been captured yet."""
    if not SAMPLE_PATH.exists():
        return None
    stamp = datetime.fromtimestamp(SAMPLE_PATH.stat().st_mtime, tz=timezone.utc)
    return f"recorded {stamp:%Y-%m-%d}"


def _self_check() -> None:
    import tempfile

    global VOICE_DIR, SAMPLE_PATH
    original_dir, original_sample = VOICE_DIR, SAMPLE_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            VOICE_DIR = Path(tmp) / "voice"
            SAMPLE_PATH = VOICE_DIR / "sample.wav"

            assert sample_status() is None, "a fresh directory has no sample"

            first = save_sample(b"first-take")
            assert first == SAMPLE_PATH
            assert SAMPLE_PATH.read_bytes() == b"first-take"
            assert sample_status() is not None
            assert not (VOICE_DIR / ".backups").exists(), (
                "the first write has nothing to snapshot"
            )

            save_sample(b"second-take")
            assert SAMPLE_PATH.read_bytes() == b"second-take"
            backups = list((VOICE_DIR / ".backups").iterdir())
            assert len(backups) == 1, "the second write must snapshot the first take"
            assert backups[0].read_bytes() == b"first-take"

            assert set(PHRASES) == {code for code, _ in LANGUAGES}, (
                "every language in the picker needs a phrase, and vice versa"
            )
            assert all(text.strip() for text in PHRASES.values())
    finally:
        VOICE_DIR, SAMPLE_PATH = original_dir, original_sample

    print("voice_sample: all checks passed")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run the self-check**

Run: `python -m runtime.voice_sample`
Expected: `voice_sample: all checks passed`

(There is no separate "fails first" step here — unlike a pytest test written
against not-yet-written code, this project's `_self_check()` convention is
written and run against the finished module in the same step. If it doesn't
print the success line, the assert that fired names exactly what's wrong;
fix and re-run.)

- [ ] **Step 3: Commit**

```bash
git add runtime/voice_sample.py
git commit -m "feat: capture a single reference clip for TTS voice cloning"
```

---

### Task 2: Admin UI — record dialog in `runtime/chat_app.py`

**Files:**
- Modify: `runtime/chat_app.py:44-53` (imports), `runtime/chat_app.py:293-320` (sidebar, after the Snapshots section), `runtime/chat_app.py:802-804` (bottom, alongside the existing `confirm_dialog` trigger)

**Interfaces:**
- Consumes: `runtime.voice_sample.LANGUAGES`, `runtime.voice_sample.PHRASES`, `runtime.voice_sample.save_sample`, `runtime.voice_sample.sample_status` (all from Task 1, signatures as declared there).
- Produces: nothing consumed elsewhere — this is the top-level UI.

- [ ] **Step 1: Add the import**

In `runtime/chat_app.py`, add alongside the other `runtime.*` imports (near line 34, after `from runtime.stories import STORIES_DIR, load_story`):

```python
from runtime.voice_sample import LANGUAGES, PHRASES, sample_status, save_sample
```

- [ ] **Step 2: Add the sidebar section**

In `runtime/chat_app.py`, immediately after the Snapshots block closes (the `st.button("Restore", ...)` block ends around line 320, still inside `if status.get("agent"):`), add:

```python
        st.divider()
        st.header("Voice sample")
        st.caption(sample_status() or "Not recorded yet.")
        if st.button("Record voice sample", width="stretch"):
            st.session_state["voice_dialog_open"] = True
            st.rerun()
```

This sits inside the existing `if status.get("agent"):` block (the same one
that gates Snapshots), so it never renders on the fan surface.

- [ ] **Step 3: Add the dialog function**

In `runtime/chat_app.py`, add a new function right after `confirm_dialog` (after its closing line, currently line 207, before the `# ---- sidebar ----` comment):

```python
@st.dialog("Record voice sample", width="large")
def record_voice_dialog() -> None:
    """Nothing reaches disk until Save. Cancel closes with no write — the
    admin can also just hit the widget's own re-record control before
    deciding either way.
    """
    phrase_by_code = dict(LANGUAGES)
    lang = st.selectbox(
        "Language",
        [code for code, _ in LANGUAGES],
        format_func=lambda code: phrase_by_code[code],
        key="voice_lang",
    )
    st.markdown(f"> {PHRASES[lang]}")
    audio = st.audio_input("Record")

    left, right = st.columns(2)
    if left.button(
        "Save", type="primary", width="stretch", disabled=audio is None
    ):
        save_sample(audio.getvalue())
        st.session_state["voice_dialog_open"] = False
        st.session_state["applied_note"] = f"Saved voice sample ({sample_status()})"
        st.rerun()
    if right.button("Cancel", width="stretch"):
        st.session_state["voice_dialog_open"] = False
        st.rerun()
```

- [ ] **Step 4: Trigger the dialog at the bottom of the script**

In `runtime/chat_app.py`, at the very end of the file (after the existing
`pending = st.session_state.get("pending"); if pending is not None:
confirm_dialog(pending)` block, currently lines 802-804), add:

```python

if st.session_state.get("voice_dialog_open"):
    record_voice_dialog()
```

This mirrors the existing `confirm_dialog` trigger pattern exactly: a
session-state flag, checked at the bottom of every rerun, keeps the dialog
open across the reruns Streamlit performs while the admin interacts with
widgets inside it (picking a language, recording, re-recording).

- [ ] **Step 5: Manual verification (no automated UI test — Streamlit has none in this repo)**

Run:
```bash
uvicorn service.main:app --port 8000
```
In a second terminal:
```bash
streamlit run runtime/chat_app.py
```
In the browser, with the stack in agent mode (`config/stack.json` ->
`"agent": true`, or whatever this machine is currently configured for):
- Confirm the sidebar shows a "Voice sample" section reading "Not recorded
  yet."
- Click "Record voice sample" — dialog opens, shows a language picker and a
  phrase.
- Switch languages — phrase text changes, nothing is written yet.
- Click the mic icon, speak, stop — a playback control appears.
- Click "Cancel" — dialog closes, sidebar still reads "Not recorded yet.",
  and `data/voice/` was not created.
- Re-open, record again, click "Save" — dialog closes, a success toast
  reading "Saved voice sample (recorded <today's date>)" appears, and the
  sidebar caption updates to match.
- Re-open, record a second clip, Save again — confirm
  `data/voice/.backups/` now holds one snapshot of the first clip, and
  `data/voice/sample.wav` holds the second.
- Confirm the saved file is a real WAV: open `data/voice/sample.wav` in a
  hex viewer (or `python -c "print(open('data/voice/sample.wav','rb').read(4))"`)
  and check it starts with `RIFF`.
- Open the dialog and press Esc instead of Cancel — confirm the dialog
  reopens rather than closing (same behavior as the existing `confirm_dialog`;
  only the Cancel button actually closes it).

If the fan surface is what this machine's `stack.json` currently serves
(`"agent": false`), temporarily flip it to verify, then flip it back — do
not leave a debug-only config change in place.

- [ ] **Step 6: Commit**

```bash
git add runtime/chat_app.py
git commit -m "feat: add voice sample recording to the admin sidebar"
```

---

### Task 3: Update `CLAUDE.md` Status

**Files:**
- Modify: `CLAUDE.md` (Status section)

This repo's convention (see the `fan-retrieval` feature's final commit,
`0093e83`) is to mark a completed piece of work in `CLAUDE.md`'s Status
section immediately, so it doesn't drift stale.

- [ ] **Step 1: Add a line to the Status section**

In `CLAUDE.md`, under `## Status`, add one line reflecting this feature,
consistent with the existing bullet style (✅ for done, one line, no new
subsection):

```markdown
- ✅ Voice sample capture — `runtime/voice_sample.py`, one reference clip at
  `data/voice/sample.wav` for future TTS cloning, recorded from the admin
  sidebar (`st.audio_input`, language picker only changes the read-aloud
  phrase). Actually running a cloning model against it is separate, later
  work.
```

Place it near the other ✅ entries (after the fan-retrieval line), not
inside the "Docker, and the web page after Streamlit" unbuilt-items line.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note voice sample capture in Status"
```
