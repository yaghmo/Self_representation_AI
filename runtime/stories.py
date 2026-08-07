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


def _self_check() -> None:
    text = (
        "# ST-001 — a weekend hiking trip\n"
        "**Summary:** the guide at the trailhead, the storm, getting back after dark\n"
        "**Keywords:** hiking, mountains, weather\n"
        "**Logged:** [~early 2026]\n"
        "\n"
        "## E-001 — meeting the guide\n"
        "He was already waiting when we pulled in.\n"
        "\n"
        "## E-002 — the storm\n"
        "It came in fast on the second afternoon.\n"
    )

    story = parse_story(text)
    assert story.id == "ST-001", story.id
    assert story.title == "a weekend hiking trip", story.title
    assert story.keywords == ["hiking", "mountains", "weather"], story.keywords
    assert story.logged == "[~early 2026]", story.logged
    assert [e.id for e in story.events] == ["E-001", "E-002"]
    assert story.events[1].title == "the storm"
    assert story.events[0].text.strip() == "He was already waiting when we pulled in."

    # Round-trip is exact. The index is derived from these files, so a render
    # that reflows text would silently re-embed chunks that never changed.
    assert render_story(story) == text, "round-trip changed the file"

    # Amending an event edits its text and leaves every id alone. Renumbering
    # would break stable-id ordering, and with it the KV prefix cache.
    story.events[0].text = "He was already waiting, red jacket, when we pulled in.\n"
    amended = parse_story(render_story(story))
    assert [e.id for e in amended.events] == ["E-001", "E-002"], "ids moved"
    assert "red jacket" in amended.events[0].text

    # Ids are allocated from the maximum, never from the count — a deleted
    # event must not free its number for reuse.
    assert next_story_id(["ST-001", "ST-004"]) == "ST-005"
    assert next_story_id([]) == "ST-001"
    assert next_event_id(story) == "E-003"

    malformed = "no heading here\n"
    try:
        parse_story(malformed)
    except MalformedStory:
        pass
    else:
        raise AssertionError("malformed story was accepted")

    # Trailing significant whitespace (markdown hard breaks) must survive round-trip.
    # This catches silent data loss from over-aggressive whitespace stripping.
    text_with_hardbreak = (
        "# ST-002 — test\n"
        "**Summary:** test\n"
        "**Keywords:** test\n"
        "**Logged:** test\n"
        "\n"
        "## E-001 — line with hard break\n"
        "End with two spaces  \n"  # Two trailing spaces = markdown hard line break
    )
    story_hb = parse_story(text_with_hardbreak)
    assert "  \n" in story_hb.events[0].text, "trailing spaces lost in parse"
    rendered_hb = render_story(story_hb)
    assert "  \n" in rendered_hb, "trailing spaces lost in render"
    assert rendered_hb == text_with_hardbreak, "round-trip with trailing spaces failed"

    print("stories: ok")


if __name__ == "__main__":
    _self_check()
