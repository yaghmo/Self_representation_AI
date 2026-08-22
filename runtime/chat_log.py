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
