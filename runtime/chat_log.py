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


def log_path(agent_mode: bool) -> Path:
    # ponytail: one file per surface, not per visitor. Safe while this is one
    # local process for one person. A multi-visitor fan deployment needs a
    # per-visitor id in this path first — see 2026-08-08-chat-persistence-design.md.
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
        if not isinstance(record, dict):
            continue
        if record.get("type") == "summary":
            summary = record.get("text", "")
        elif "role" in record and "content" in record:
            turns.append({"role": record["role"], "content": record["content"]})
    return (turns[-window:] if window > 0 else []), summary


def clear(path: Path) -> None:
    path.unlink(missing_ok=True)


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

        # A syntactically valid but non-dict JSON line (e.g. a bare scalar)
        # is skipped the same way, not a crash, and doesn't take the
        # well-formed records around it down with it.
        path.write_text(
            '{"role": "user", "content": "before"}\n'
            '42\n'
            '{"role": "user", "content": "after"}\n',
            encoding="utf-8",
        )
        turns, _ = load_recent(path, window=20)
        assert [t["content"] for t in turns] == ["before", "after"], turns

        # window=0 means "nothing", not "everything" — plain slicing would
        # read `[-0:]` as `[0:]` and hand back the full list, which would
        # make `history_window: 0` in stack.json silently rehydrate the
        # entire log instead of none of it.
        path.write_text(
            '{"role": "user", "content": "a"}\n'
            '{"type": "summary", "text": "sum"}\n',
            encoding="utf-8",
        )
        turns, summary = load_recent(path, window=0)
        assert turns == [], turns
        assert summary == "sum", summary

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
