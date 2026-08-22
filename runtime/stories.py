"""The story corpus: parse, render, and allocate ids.

A story is narrative material the creator writes down whole — a day, an
event, a story about the character. It is a third corpus, neither the
append-only source log nor the cited profile derived from it.

Story text is mutable by design: an amendment edits the story in place rather
than appending a note beside it, so that a retrieved chunk reads as one
coherent paragraph. What is never mutable is an id. `ST-###` and `E-###` are
assigned once and survive every edit, because retrieved chunks are ordered by
id so that unchanged content serialises to identical bytes and the model
server's prefix cache survives between turns.

This module is pure text. Embeddings live in `runtime/index.py` and writes go
through `runtime/story_tools.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STORIES_DIR = REPO_ROOT / "data" / "stories"

TITLE = re.compile(r"^# (ST-\d+) — (.+)$", re.MULTILINE)
EVENT = re.compile(r"^## (E-\d+) — (.+)$", re.MULTILINE)
FIELD = re.compile(r"^\*\*(Summary|Keywords|Logged):\*\* (.*)$", re.MULTILINE)


class MalformedStory(ValueError):
    """The file is not a story. Reported rather than guessed at."""


@dataclass
class Event:
    id: str
    title: str
    text: str


@dataclass
class Story:
    id: str
    title: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    logged: str = ""
    events: list[Event] = field(default_factory=list)


def render_story(story: Story) -> str:
    parts = [
        f"# {story.id} — {story.title}\n",
        f"**Summary:** {story.summary}\n",
        f"**Keywords:** {', '.join(story.keywords)}\n",
        f"**Logged:** {story.logged}\n",
    ]
    for event in story.events:
        parts.append(f"\n## {event.id} — {event.title}\n")
        parts.append(event.text if event.text.endswith("\n") else event.text + "\n")
    return "".join(parts)


def load_story(path: Path) -> Story:
    return parse_story(path.read_text(encoding="utf-8"))


def load_all(directory: Path | None = None) -> list[Story]:
    directory = directory or STORIES_DIR
    if not directory.is_dir():
        return []
    return [load_story(p) for p in sorted(directory.glob("ST-*.md"))]


def parse_story(text: str) -> Story:
    heading = TITLE.search(text)
    if heading is None:
        raise MalformedStory("no '# ST-### — title' heading found")

    fields = {name: value.strip() for name, value in FIELD.findall(text)}
    keywords = [k.strip() for k in fields.get("Keywords", "").split(",") if k.strip()]

    events: list[Event] = []
    marks = list(EVENT.finditer(text))
    for position, mark in enumerate(marks):
        end = marks[position + 1].start() if position + 1 < len(marks) else len(text)
        raw = text[mark.end():end].lstrip("\n")
        # Strip trailing newlines only; preserve significant whitespace like markdown hard breaks
        event_text = raw.rstrip("\n") + "\n" if raw.strip() else ""
        events.append(Event(id=mark.group(1), title=mark.group(2).strip(),
                            text=event_text))

    return Story(
        id=heading.group(1),
        title=heading.group(2).strip(),
        summary=fields.get("Summary", ""),
        keywords=keywords,
        logged=fields.get("Logged", ""),
        events=events,
    )


def _next(ids: list[str], prefix: str) -> str:
    # From the maximum, never the count: a deleted id must not be handed out
    # again to different content the index may still hold a vector for.
    numbers = [int(i.split("-")[1]) for i in ids if i.startswith(f"{prefix}-")]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def next_story_id(existing: list[str]) -> str:
    return _next(existing, "ST")


def next_event_id(story: Story) -> str:
    return _next([e.id for e in story.events], "E")
