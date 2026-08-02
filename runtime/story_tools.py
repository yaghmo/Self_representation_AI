"""`/story`: route incoming narrative, and compose the write it implies.

Three branches, decided by retrieval rather than by a flag the creator has to
remember. Material that matches nothing becomes a new story; material that
matches an existing one becomes an amendment to it; material that matches
almost exactly is refused as a duplicate.

Every branch produces a `Proposal`, never a write. The confirm gate names the
branch it took and the story it picked, with the runners-up beside it, so a
misroute costs one rejection. That matters more here than in the bible tools:
story text is mutable, so a wrong edit target overwrites the creator's own
words rather than adding a line beside them.

Thresholds are starting values to be tuned against a real corpus. Both can be
wrong without causing damage, because nothing is written until a human looks
at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from runtime.index import Embedder, Hit, Index, all_chunks, build
from runtime.stories import (
    STORIES_DIR,
    Event,
    Story,
    load_all,
    load_story,
    next_event_id,
    next_story_id,
    parse_story,
    render_story,
)
from runtime.tools import Proposal, _propose

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "data" / "redaction-policy.md"

DUPLICATE_THRESHOLD = 0.95
AMENDMENT_THRESHOLD = 0.60


@dataclass
class Routing:
    branch: str  # "duplicate" | "amend" | "new"
    story: Story | None = None
    event_id: str = ""
    runners_up: list[Hit] = field(default_factory=list)


def read_policy(path: Path | None = None) -> str:
    """The redaction policy, read before anything is written.

    One policy governs every corpus. Reduction happens on the way in: this
    corpus is reachable by the fan-facing bot, so anything exact written here
    can be surfaced to the public, and deleting it later does not unpublish it.
    """
    path = path or POLICY_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. The redaction policy governs every corpus and "
            "is read before any ingestion — restore it before logging anything."
        )
    return path.read_text(encoding="utf-8")


def route(
    text: str,
    index: Index,
    embed: Embedder,
    directory: Path | None = None,
) -> Routing:
    directory = directory or STORIES_DIR
    everything = index.search(text, embed, limit=5)
    if not everything:
        return Routing(branch="new")

    if everything[0].score >= DUPLICATE_THRESHOLD:
        return Routing(branch="duplicate", runners_up=everything)

    summaries = index.search(text, embed, limit=3, kind="summary")
    if not summaries or summaries[0].score < AMENDMENT_THRESHOLD:
        return Routing(branch="new", runners_up=summaries)

    target = summaries[0].chunk.story_id
    story = load_story(directory / f"{target}.md")

    # Coarse layer picked the story; fine layer picks the paragraph inside it.
    events = [h for h in index.search(text, embed, limit=8, kind="event")
              if h.chunk.story_id == target]
    event_id = events[0].chunk.event_id if events else (
        story.events[-1].id if story.events else ""
    )
    return Routing(branch="amend", story=story, event_id=event_id, runners_up=summaries[1:])


def propose_amendment(
    story: Story,
    event_id: str,
    new_text: str,
    directory: Path | None = None,
) -> Proposal:
    directory = directory or STORIES_DIR
    path = directory / f"{story.id}.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""

    target = next((e for e in story.events if e.id == event_id), None)
    if target is None:
        raise ValueError(
            f"{story.id} has no {event_id}. Events present: "
            f"{', '.join(e.id for e in story.events) or 'none'}"
        )

    before = target.text
    amended = parse_story(old) if old else story
    for event in amended.events:
        if event.id == event_id:
            event.text = new_text if new_text.endswith("\n") else new_text + "\n"

    return _propose(
        path=path,
        old=old,
        new=render_story(amended),
        summary=f"amend {story.id}/{event_id} — {target.title}",
        before=before,
        after=new_text,
    )


def propose_new_story(
    summary: str,
    keywords: list[str],
    logged: str,
    events: list[tuple[str, str]],
    directory: Path | None = None,
) -> Proposal:
    """`events` is a list of (title, body) pairs, already segmented and redacted."""
    directory = directory or STORIES_DIR
    story_id = next_story_id([s.id for s in load_all(directory)])
    story = Story(
        id=story_id,
        title=summary.split(",")[0].strip() or "an untitled story",
        summary=summary,
        keywords=list(keywords),
        logged=logged,
        events=[],
    )
    for title, body in events:
        story.events.append(Event(id=next_event_id(story), title=title, text=body))

    path = directory / f"{story_id}.md"
    return _propose(
        path=path,
        old="",
        new=render_story(story),
        summary=f"new story {story_id} — {story.title} ({len(story.events)} events)",
        before="",
        after=render_story(story),
    )


def _self_check() -> None:
    import tempfile
    import zlib

    # zlib.crc32, not the builtin hash(): str hashing is salted per-process
    # (PEP 456), so builtin hash() buckets words differently on every run and
    # a couple of this check's assertions sit close enough to their threshold
    # to flip with the seed. crc32 is deterministic across runs and keeps the
    # only properties this fake embedder needs — same text gives the same
    # vector, shared words give a higher cosine.
    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, zlib.crc32(word.encode("utf-8")) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        existing = Story(
            id="ST-001",
            title="a weekend hiking trip",
            summary="the guide at the trailhead, the storm, getting back after dark",
            keywords=["hiking", "mountains", "weather"],
            logged="[~early 2026]",
            events=[
                Event("E-001", "meeting the guide", "He was already waiting when we pulled in.\n"),
                Event("E-002", "the storm", "It came in fast on the second afternoon.\n"),
            ],
        )
        (directory / "ST-001.md").write_text(render_story(existing), encoding="utf-8")
        index = build(all_chunks(directory), fake_embed)

        # A detail naming its target only by allusion routes to the story it
        # belongs to, and to the event inside it. This is the case the whole
        # design exists for.
        routing = route(
            "the guide at the trailhead, back after dark from the storm, was wearing a red jacket",
            index, fake_embed, directory,
        )
        assert routing.branch == "amend", routing.branch
        assert routing.story is not None and routing.story.id == "ST-001"
        assert routing.event_id == "E-001", routing.event_id

        # Unrelated material is a new story, not a forced amendment.
        fresh = route(
            "a quiet afternoon rearranging every shelf in the kitchen",
            index, fake_embed, directory,
        )
        assert fresh.branch == "new", fresh.branch
        assert fresh.story is None

        # The same text pasted twice is refused, and the refusal names what it
        # duplicates so the creator can tell it apart from a rejection.
        again = route(
            "the storm came in fast on the second afternoon", index, fake_embed, directory
        )
        assert again.branch == "duplicate", again.branch
        assert again.runners_up and again.runners_up[0].chunk.story_id == "ST-001"

        # Amending composes a Proposal, never a write. Nothing lands until the
        # creator approves it at the gate.
        proposal = propose_amendment(
            existing, "E-001",
            "He was already waiting, red jacket, when we pulled in.\n",
            directory,
        )
        assert "red jacket" in proposal.new_text
        assert "ST-001" in proposal.summary
        on_disk = (directory / "ST-001.md").read_text(encoding="utf-8")
        assert "red jacket" not in on_disk, "proposal wrote to disk before approval"

        proposal.apply()
        after = parse_story((directory / "ST-001.md").read_text(encoding="utf-8"))
        assert "red jacket" in after.events[0].text
        assert [e.id for e in after.events] == ["E-001", "E-002"], "ids moved on amend"
        assert (directory / ".backups").is_dir(), "no snapshot taken before the write"

        # A new story takes the next free id and lands as its own file.
        created = propose_new_story(
            summary="rearranging every shelf in the kitchen",
            keywords=["home", "cleaning"],
            logged="[~early 2026]",
            events=[("an afternoon of it", "It took longer than it should have.\n")],
            directory=directory,
        )
        assert created.path.name == "ST-002.md", created.path.name
        created.apply()
        made = parse_story((directory / "ST-002.md").read_text(encoding="utf-8"))
        assert made.id == "ST-002" and made.events[0].id == "E-001"

    print("story_tools: ok")


if __name__ == "__main__":
    _self_check()
