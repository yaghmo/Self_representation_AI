# Chat Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat history and its compaction summary survive a restart, for both the admin and fan surfaces of `chat_app.py`, without adding retrieval or multi-visitor session identity.

**Architecture:** A new pure module, `runtime/chat_log.py`, appends every turn and every fresh compaction summary to one JSONL file per surface (`data/chats/admin.jsonl` / `data/chats/fan.jsonl`). On startup, `chat_app.py` reads the tail of that file — a configurable window, default 20 messages — back into `st.session_state`. The window size (`history_window`) rides the same `stack.json` → `Model.from_config` → `Model.status()` path `bible_strategy` already takes.

**Tech Stack:** Python stdlib only (`json`, `pathlib`). No new dependency — matches the repo's existing `_self_check()` / `assert` testing idiom, no pytest.

## Global Constraints

- `data/` is gitignored wholesale (`.gitignore` line `data/`) — nothing here needs a new ignore rule.
- The corpus/profile privacy rule from CLAUDE.md applies to chat transcripts the same way: never write instance-specific content into a tracked file.
- Every write-side function in this repo is a plain function over a path, testable without a model or server (`tools.py`, `index.py`, `bible.py` all follow this). `chat_log.py` follows the same shape.
- Self-checks are `assert`-based, run via `python -m runtime.<module>`, no framework.
- `st.session_state["history"]` entries are plain `{"role": ..., "content": ...}` dicts, never `Message` objects and never carrying `tool_calls` — confirmed by reading every append site in `chat_app.py` (agent-mode tool turns are reconstructed fresh from this same dict shape at `chat_app.py:703`, dropping `tool_calls`). `chat_log.py`'s turn shape matches this exactly — no translation layer.

---

### Task 1: `runtime/chat_log.py` — the persistence module

**Files:**
- Create: `runtime/chat_log.py`
- Test: none separate — `_self_check()` inside the same file, run via `python -m runtime.chat_log`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (used by Task 3):
  - `CHATS_DIR: Path` — `data/chats/`
  - `log_path(agent_mode: bool) -> Path` — `CHATS_DIR / "admin.jsonl"` or `CHATS_DIR / "fan.jsonl"`
  - `append_turn(path: Path, role: str, content: str) -> None`
  - `append_summary(path: Path, text: str) -> None`
  - `load_recent(path: Path, window: int) -> tuple[list[dict], str]` — `(turns, summary)`; `turns` are `{"role": str, "content": str}` dicts, oldest-first, at most `window` of them; `summary` is `""` if none was ever logged
  - `clear(path: Path) -> None` — deletes the file if present

- [ ] **Step 1: Write the self-check (it will fail — nothing exists yet)**

Create `runtime/chat_log.py` with just the module docstring, imports, and this `_self_check()`:

```python
"""Append-only chat history on disk, one JSONL file per surface.

Two record shapes on disk, one per line:

    {"role": "user"|"assistant"|"tool", "content": "..."}
    {"type": "summary", "text": "..."}

The file is the full record and is never truncated or rewritten in place —
only appended to. `load_recent` bounds what comes *back* into memory; it
never bounds what's on disk. A line that fails to parse is skipped rather
than raised, because a damaged log must not block the app from starting —
same stance `index.py:load_index` takes on a corrupt `.npz`.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHATS_DIR = REPO_ROOT / "data" / "chats"


def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.jsonl"

        # A missing file loads as empty, no summary — matches today's
        # behaviour exactly, so a fresh corpus with no log yet is a no-op.
        turns, summary = load_recent(path, window=20)
        assert turns == [], turns
        assert summary == "", repr(summary)

        # Writing a turn then reading it back round-trips byte-for-byte.
        append_turn(path, "user", "hello")
        append_turn(path, "assistant", "hi there")
        turns, summary = load_recent(path, window=20)
        assert turns == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ], turns
        assert summary == "", "no summary written yet"

        # The last summary record wins when more than one is present.
        append_summary(path, "first summary")
        append_summary(path, "second summary")
        _, summary = load_recent(path, window=20)
        assert summary == "second summary", summary

        # Only the last `window` turns come back; older ones are ignored,
        # not deleted — the file itself keeps growing underneath.
        for n in range(30):
            append_turn(path, "user", f"turn {n}")
        turns, _ = load_recent(path, window=5)
        assert [t["content"] for t in turns] == [f"turn {n}" for n in range(25, 30)], turns
        assert len(path.read_text(encoding="utf-8").splitlines()) > 5, (
            "load_recent must not truncate the file on disk"
        )

        # A corrupt/truncated line is skipped, not fatal, and does not take
        # the lines around it down with it.
        path.write_text(
            '{"role": "user", "content": "before"}\n'
            'not valid json at all\n'
            '{"role": "user", "content": "after"}\n',
            encoding="utf-8",
        )
        turns, _ = load_recent(path, window=20)
        assert [t["content"] for t in turns] == ["before", "after"], turns

        # Admin and fan resolve to different files under the same root.
        admin_path = log_path(agent_mode=True)
        fan_path = log_path(agent_mode=False)
        assert admin_path != fan_path
        assert admin_path.parent == CHATS_DIR
        assert admin_path.name == "admin.jsonl"
        assert fan_path.name == "fan.jsonl"

        # clear() removes the file; clearing a file that doesn't exist is a
        # no-op, not an error — the Clear button doesn't know or care
        # whether anything has ever been written yet.
        append_turn(path, "user", "will be cleared")
        clear(path)
        assert not path.exists()
        clear(path)  # second call on an already-missing file must not raise

    print("chat_log: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m runtime.chat_log`
Expected: `NameError: name 'load_recent' is not defined` (or similar — none of the functions exist yet).

- [ ] **Step 3: Implement the module**

Insert the real functions above `_self_check()`:

```python
def log_path(agent_mode: bool) -> Path:
    return CHATS_DIR / ("admin.jsonl" if agent_mode else "fan.jsonl")


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def append_turn(path: Path, role: str, content: str) -> None:
    _append(path, {"role": role, "content": content})


def append_summary(path: Path, text: str) -> None:
    _append(path, {"type": "summary", "text": text})


def load_recent(path: Path, window: int) -> tuple[list[dict], str]:
    if not path.exists():
        return [], ""
    turns: list[dict] = []
    summary = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "summary":
            summary = record.get("text", "")
        elif "role" in record and "content" in record:
            turns.append({"role": record["role"], "content": record["content"]})
    return turns[-window:], summary


def clear(path: Path) -> None:
    path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python -m runtime.chat_log`
Expected: `chat_log: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/chat_log.py
git commit -m "feat: persist chat history and its compaction summary to disk"
```

---

### Task 2: `history_window` config — `runtime/model.py`

**Files:**
- Modify: `runtime/model.py:42-56` (the `Model` dataclass), `:60-81` (`from_config`), `:190-198` (`status`)

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Task 3): `Model.status()["history_window"]`, an `int`, default `20` when `config/stack.json` has no such key.

There is no `_self_check()` in `model.py` today (it requires real hardware probing to exercise meaningfully), so this task has no automated test of its own — it is exercised end-to-end by Task 3's manual verification. This mirrors how `bible_strategy` was added in the same file with no dedicated test.

- [ ] **Step 1: Add the field to the dataclass**

In `runtime/model.py`, in the `Model` dataclass (around line 50, right after `bible_strategy: str = "retrieval"`):

```python
    bible_strategy: str = "retrieval"
    history_window: int = 20
```

- [ ] **Step 2: Read it in `from_config`**

Around line 79, right after `bible_strategy=config.get("bible_strategy", "retrieval"),`:

```python
            bible_strategy=config.get("bible_strategy", "retrieval"),
            history_window=config.get("history_window", 20),
```

- [ ] **Step 3: Expose it in `status()`**

Around line 196, right after `"bible_strategy": self.bible_strategy,`:

```python
            "bible_strategy": self.bible_strategy,
            "history_window": self.history_window,
```

- [ ] **Step 4: Verify by hand**

Run: `python -c "from runtime.model import Model; m = Model(entry=None, role_config={}, context_tokens=8192); print(m.history_window)"`
Expected: `20`

Then, with `config/stack.json` present (it is — probed by the cookbook already), confirm the default survives round-tripping through `from_config`:

Run: `python -c "from runtime.model import Model; print(Model.from_config().history_window)"`
Expected: `20` (no `history_window` key exists in the current `config/stack.json` yet, so the `.get(..., 20)` default applies).

- [ ] **Step 5: Commit**

```bash
git add runtime/model.py
git commit -m "feat: add history_window to the stack config, default 20"
```

---

### Task 3: Wire persistence into `runtime/chat_app.py`

**Files:**
- Modify: `runtime/chat_app.py` — import, one new helper, the startup block, five append call-sites, the compaction block, the Clear button, the Restore button.

**Interfaces:**
- Consumes: `chat_log.log_path`, `chat_log.append_turn`, `chat_log.append_summary`, `chat_log.load_recent`, `chat_log.clear` (Task 1); `status["history_window"]` (Task 2, already flowing through the existing `status = get("/model").json()` call at `chat_app.py:216`).
- Produces: nothing consumed elsewhere — this is the leaf that wires the two prior tasks into the running app.

No automated test — `chat_app.py` is a Streamlit script with no existing test harness (confirmed: no `_self_check` anywhere in the file today). Verified by hand, per the repo's established pattern for this file.

- [ ] **Step 1: Import the new module**

In `runtime/chat_app.py`, add to the import block (near line 27, alongside the other `runtime.*` imports):

```python
from runtime import chat_log
```

- [ ] **Step 2: Add the shared `add_turn` helper**

Insert right after the `stream_reply` function (after line 94, before `@st.dialog` on line 97):

```python
def add_turn(role: str, content: str) -> None:
    """Append to the live session and the on-disk log in one call.

    Five call sites need this; one place keeps the two from drifting apart.
    """
    st.session_state["history"].append({"role": role, "content": content})
    chat_log.append_turn(st.session_state["chat_log_path"], role, content)
```

- [ ] **Step 3: Replace the startup block to rehydrate from disk**

Replace (around line 323-324):

```python
if "history" not in st.session_state:
    st.session_state["history"] = []
```

with:

```python
if "history" not in st.session_state:
    path = chat_log.log_path(bool(status.get("agent")))
    window = int(status.get("history_window", 20))
    turns, summary = chat_log.load_recent(path, window)
    st.session_state["history"] = turns
    if summary:
        st.session_state["summary"] = summary
    st.session_state["chat_log_path"] = path
```

- [ ] **Step 4: Replace the five raw `.append()` call sites with `add_turn`**

In `confirm_dialog`'s `resolved()` function (line 135):

```python
        st.session_state["history"].append({"role": "user", "content": shown})
```
→
```python
        add_turn("user", shown)
```

Duplicate-story refusal (lines 485-487):

```python
        st.session_state["history"].append(
            {"role": "user", "content": f"[/story refused as a duplicate of {top.chunk.key}]"}
        )
```
→
```python
        add_turn("user", f"[/story refused as a duplicate of {top.chunk.key}]")
```

User prompt (line 604):

```python
        st.session_state["history"].append({"role": "user", "content": prompt})
```
→
```python
        add_turn("user", prompt)
```

Agent-mode assistant reply (line 736):

```python
        if reply:
            st.session_state["history"].append({"role": "assistant", "content": reply})
```
→
```python
        if reply:
            add_turn("assistant", reply)
```

Non-agent assistant reply (line 768):

```python
    st.session_state["history"].append({"role": "assistant", "content": reply})
```
→
```python
    add_turn("assistant", reply)
```

- [ ] **Step 5: Persist a fresh compaction summary**

Around lines 628-630:

```python
            st.session_state["summary"] = (
                f"{previous} {fresh}".strip() if previous else fresh
            )
```

becomes:

```python
            st.session_state["summary"] = (
                f"{previous} {fresh}".strip() if previous else fresh
            )
            chat_log.append_summary(st.session_state["chat_log_path"], st.session_state["summary"])
```

- [ ] **Step 6: Clear the on-disk log when the visible chat is cleared**

Two places reset `st.session_state["history"] = []`. Both must also clear the file — otherwise the next restart resurrects exactly what was just wiped, which is the whole feature working against the user in that moment.

The Clear button (around line 360-364):

```python
if columns[0].button("Clear"):
    st.session_state["history"] = []
    for key in ("prompt_floor", "summary", "current_story", "logged_stories"):
        st.session_state.pop(key, None)
    st.rerun()
```
→
```python
if columns[0].button("Clear"):
    chat_log.clear(st.session_state["chat_log_path"])
    st.session_state["history"] = []
    for key in ("prompt_floor", "summary", "current_story", "logged_stories"):
        st.session_state.pop(key, None)
    st.rerun()
```

The Restore-snapshot button (around line 289-296):

```python
            if st.button("Restore", width="stretch"):
                restored = restore_backup(choice)
                st.session_state["history"] = []
                st.session_state["applied_note"] = (
                    f"Restored {restored} from {choice.name} — chat cleared, since "
                    "the history described a file that no longer says that."
                )
                st.rerun()
```
→
```python
            if st.button("Restore", width="stretch"):
                restored = restore_backup(choice)
                chat_log.clear(st.session_state["chat_log_path"])
                st.session_state["history"] = []
                st.session_state["applied_note"] = (
                    f"Restored {restored} from {choice.name} — chat cleared, since "
                    "the history described a file that no longer says that."
                )
                st.rerun()
```

- [ ] **Step 7: Verify by hand**

Start the backend and the app:

```bash
uvicorn service.main:app --port 8000
streamlit run runtime/chat_app.py
```

1. Load the model, send two or three messages, wait for replies.
2. Check `data/chats/admin.jsonl` (or `fan.jsonl`, depending on `config/stack.json`'s `agent` flag) exists and has one JSON line per turn.
3. Stop Streamlit (`Ctrl+C`), restart it (`streamlit run runtime/chat_app.py`). The prior turns should reappear in the chat window on load, without sending anything new.
4. Click **Clear**. Confirm the chat window empties. Restart Streamlit again — the chat must stay empty (the file was deleted, not just the session).
5. Send enough turns to trip compaction (or lower `room` temporarily / send long messages) and confirm a `{"type": "summary", ...}` line appears in the log file after compaction fires.

- [ ] **Step 8: Commit**

```bash
git add runtime/chat_app.py
git commit -m "feat: wire chat history persistence into the chat app"
```
