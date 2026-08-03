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

import copy
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
    """On the "amend" branch, an empty `event_id` means the story resolved
    but no paragraph inside it did — unresolved, not a hint to guess (e.g.
    the last event). Treat it as a case the caller must surface, never as an
    edit target.
    """

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

    # Coarse layer picked the story; fine layer picks the paragraph inside
    # it. limit=None: the ranked list must be filtered by story before it is
    # truncated, not after. A capped limit here (`hits[:8]` then filter)
    # crowds every event of the target story out once the corpus holds more
    # than that many stories, `events` comes back empty for a reason that
    # has nothing to do with matching, and a fallback that guesses would
    # silently amend the wrong paragraph — the exact failure mode a mutable
    # story file cannot afford (see the module docstring).
    events = [h for h in index.search(text, embed, limit=None, kind="event")
              if h.chunk.story_id == target]
    # No event of the target story matched at all — leave it unresolved
    # rather than guessing. This cannot cross into another story: the list
    # is already filtered to `target` before this is read.
    event_id = events[0].chunk.event_id if events else ""
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

    # Resolve `target` against the disk-parsed story, not the caller's
    # in-memory one, and edit that same object. The two can drift — a
    # second pending proposal, a concurrent /add — and validating against
    # `story` while editing a separately-parsed `amended` lets the guard
    # pass while the loop matches nothing: the file round-trips
    # byte-identical and the proposal still reports the new text in `after`,
    # so the gate looks correct while the amendment silently vanishes.
    # `copy.deepcopy`, not `story` itself, when there is no file yet: the
    # caller's own object must not be mutated before the write is approved.
    amended = parse_story(old) if old else copy.deepcopy(story)
    target = next((e for e in amended.events if e.id == event_id), None)
    if target is None:
        raise ValueError(
            f"{story.id} has no {event_id}. Events present: "
            f"{', '.join(e.id for e in amended.events) or 'none'}"
        )

    before = target.text
    target.text = new_text if new_text.endswith("\n") else new_text + "\n"

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

        # The motivating case — "the guide from that hiking trip had a red
        # jacket." This query shares two verbatim content words with the
        # summary chunk ("guide", "trailhead") and still scores only 0.574
        # against it — below AMENDMENT_THRESHOLD (0.60) — so it routes to
        # "new". A truer allusion, one with no shared nouns at all, scores
        # lower still (0.23-0.35 across phrasings): this toy
        # hashed-bag-of-words embedder cannot
        # express the allusive case at any realistic phrasing, with or
        # without incidental word overlap. That is an honest report of this
        # fake embedder's ceiling, not a passing test of the design —
        # whether bge-m3 resolves the allusion is unverified and needs
        # checking against the real embedder, not this one.
        motivating = route(
            "the guide at the trailhead was wearing a red jacket",
            index, fake_embed, directory,
        )
        assert motivating.branch == "new", motivating.branch

        # Unrelated material is a new story, not a forced amendment.
        fresh = route(
            "a quiet afternoon rearranging every shelf in the kitchen",
            index, fake_embed, directory,
        )
        assert fresh.branch == "new", fresh.branch
        assert fresh.story is None

        # The same text pasted twice is refused, and the refusal names what it
        # duplicates so the creator can tell it apart from a rejection. What a
        # creator actually re-pastes is an event's body — never its title, an
        # editorial label the corpus adds, not text they would retype. Scored
        # directly, that verbatim body gets 0.9308 against its own chunk
        # (title + body), below DUPLICATE_THRESHOLD (0.95): a real re-paste of
        # already-logged material does NOT trip this branch under the toy
        # embedder today. That is the module's actual behaviour, recorded
        # rather than papered over; whether bge-m3's dense score clears the
        # gap on real text is unverified.
        body_paste = route(
            "It came in fast on the second afternoon.", index, fake_embed, directory
        )
        assert body_paste.branch == "new", body_paste.branch

        # The branch itself is reachable: text matching a chunk's full
        # rendered form (title and body both) clears the threshold, so
        # "duplicate" is wired correctly even though the realistic case above
        # currently falls short of it.
        full_chunk_paste = route(
            "the storm. It came in fast on the second afternoon.", index, fake_embed, directory
        )
        assert full_chunk_paste.branch == "duplicate", full_chunk_paste.branch
        assert (
            full_chunk_paste.runners_up
            and full_chunk_paste.runners_up[0].chunk.story_id == "ST-001"
        )

        # ---- amend routing under real lexical overlap, and the truncation
        # bug it used to hit past eight stories --------------------------
        # This is NOT the allusion case above — it is quoted vocabulary from
        # the summary, honestly exercising route()'s "amend" branch: does it
        # pick the right story and the right paragraph inside it? A corpus of
        # nine stories (the target plus eight decoys, each carrying an event
        # that scores far above the real match) reproduces the bug the
        # reviewer found: the old code ranked globally with limit=8 and
        # filtered by story afterwards, so all eight decoys filled the ranked
        # list and the target story's own events were truncated away before
        # the filter ever saw them — event_id fell back to "the last event",
        # which was the wrong paragraph. limit=None fixes it by filtering the
        # full ranked list before truncating.
        with tempfile.TemporaryDirectory() as trunc_raw:
            trunc_dir = Path(trunc_raw)
            (trunc_dir / "ST-001.md").write_text(render_story(existing), encoding="utf-8")
            overlap_query = (
                "the guide at the trailhead, back after dark from the storm, "
                "was wearing a red jacket"
            )
            # The decoy body must outscore the real E-001 match (0.41) so it
            # crowds the ranked list, but stay well under DUPLICATE_THRESHOLD
            # (0.95) so the duplicate check above doesn't intercept this
            # query first — this fixture is about the "amend" branch, not the
            # "duplicate" one. A partial word-overlap body (0.76) does both.
            decoy_body = "at the trailhead back after dark from the storm"
            for i in range(1, 9):
                decoy = Story(
                    id=f"ST-{100 + i}",
                    title=f"decoy story {i}",
                    summary="notes about grocery shopping and a weekly budget for produce",
                    keywords=[],
                    logged="[~early 2026]",
                    events=[Event("E-001", "filler", decoy_body + "\n")],
                )
                (trunc_dir / f"{decoy.id}.md").write_text(render_story(decoy), encoding="utf-8")
            trunc_index = build(all_chunks(trunc_dir), fake_embed)

            overlap = route(overlap_query, trunc_index, fake_embed, trunc_dir)
            assert overlap.branch == "amend", overlap.branch
            assert overlap.story is not None and overlap.story.id == "ST-001"
            assert overlap.event_id == "E-001", (
                "truncated before the filter — picked the wrong paragraph: "
                f"{overlap.event_id}"
            )

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

        # `existing` is now stale — disk has "red jacket", the in-memory
        # object still says "He was already waiting when we pulled in.".
        # target must resolve against the disk parse, not the caller's
        # object: an event id present only in the caller's stale copy must
        # be refused rather than silently matching nothing.
        phantom = copy.deepcopy(existing)
        phantom.events.append(Event("E-999", "an event disk has never seen", "x\n"))
        try:
            propose_amendment(phantom, "E-999", "y\n", directory)
        except ValueError as exc:
            assert "E-999" in str(exc) and "E-001, E-002" in str(exc), str(exc)
        else:
            raise AssertionError(
                "expected ValueError for an event id absent from disk — the old "
                "code validated against the caller's object and matched nothing, "
                "producing a proposal whose write was a silent no-op"
            )

        # Milder mirror: the id exists both places, but the caller's copy of
        # its text is stale. `before` must reflect what disk actually holds
        # right now, not what the caller's object last saw — the gate's
        # before/after panel is only honest if `before` is real.
        stale_before = propose_amendment(
            existing, "E-001", "a third rewrite\n", directory
        )
        assert stale_before.before == after.events[0].text, stale_before.before
        assert "red jacket" in stale_before.before, (
            "before must come from disk, not the caller's stale copy"
        )

        # No file on disk yet: the caller's own Story object must not be
        # mutated by composing a proposal — only apply() may change anything,
        # and this one is never applied.
        untouched = Story(
            id="ST-999", title="not yet written", summary="s", keywords=[],
            logged="[~early 2026]",
            events=[Event("E-001", "only event", "original text\n")],
        )
        original_text = untouched.events[0].text
        propose_amendment(untouched, "E-001", "mutated?\n", directory)
        assert untouched.events[0].text == original_text, (
            "composing a proposal must not mutate the caller's object"
        )

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
