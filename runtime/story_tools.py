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
from runtime.tools import NoChange, Proposal, _propose

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "data" / "redaction-policy.md"

DUPLICATE_THRESHOLD = 0.95
AMENDMENT_THRESHOLD = 0.60
# The paragraph inside the story the coarse layer picked. Without a floor the
# closest event always wins however weak the match, so unrelated pasted
# material would overwrite whichever paragraph ranked first. Below this,
# `Routing` reports the story as resolved but the paragraph as not — an
# honest unresolved, not a new failure path.
#
# Lower than AMENDMENT_THRESHOLD on purpose: the summary layer already
# established relevance, this only separates "this paragraph" from "some
# other paragraph of the same story". Untuned against a real corpus, like the
# two above it — too high just sends routed amendments to the explicit
# `ST-###/E-###` syntax, the safe direction to be wrong in. Unvalidated by
# the self-check's toy embedder too: its score scale is a hash function's,
# not bge-m3's, so the tests neutralise this constant rather than satisfy it.
EVENT_THRESHOLD = 0.50


@dataclass
class Routing:
    """On the "amend" branch, an empty `event_id` means the story resolved
    but no paragraph inside it did — unresolved, not a hint to guess (e.g.
    the last event). Treat it as a case the caller must surface, never as an
    edit target.
    """

    branch: str  # "duplicate" | "amend" | "append" | "new"
    # "append" is never returned by `route()` — similarity cannot tell
    # "belongs to this story" from "rewrites a line in it". Only a creator
    # naming a bare `ST-###` produces it.
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


# One bounded call, not the agent loop: redaction and segmentation are a fixed
# transform, and a loop would spend turns deciding to do what it was told. The
# policy is interpolated fresh on every ingestion rather than baked in at
# startup, so a creator who loosens a row sees it on their next story.
INGEST_PROMPT = """You are preparing the creator's story for their own corpus.

Apply this redaction policy to every detail before you write anything:

{policy}

Reduce on the way in. This corpus is reachable by the public-facing bot, so
anything exact you write here can be surfaced, and removing it later does not
unpublish it. A bracketed value is always a fuzzed replacement — never write
the precise value you were given.

Keep the creator's phrasing. Reduce specifics, never rewrite voice. Do not add
events, details, names, or feelings that are not in the text you were handed.

`logged` is the period the text itself gives. If it gives none, return "".
A period you worked out from context is a date the creator never said, and an
invented date is worse than no date — leave it empty and it can be asked.

Return JSON only:
{{"summary": "one sentence", "keywords": ["..."], "logged": "[~period]" or "",
  "events": [{{"title": "short", "text": "the creator's words, redacted"}}]}}
"""


# The amend contract, stated rather than implied. Running `INGEST_PROMPT`
# (a segmentation prompt) over a merge instead framed the new detail as
# something to *reduce* — one run dropped it, another wrote a fuzzed-value
# marker copied out of the redaction rules it carries. Same failure class as
# the invented dates `keep_logged` catches: the model does the task the
# prompt describes, and merging was never described.
#
# The policy still rides along — a merged detail is new material entering
# the corpus, reduced on the way in like anything else.
AMEND_PROMPT = """You are editing one paragraph of the creator's own story.

Apply this redaction policy to every detail before you write anything:

{policy}

You are given new information, then the paragraph as it currently stands.
Return that paragraph rewritten so the new information is part of it.

Keep every detail the paragraph already has unless the new information
contradicts it. Keep the creator's phrasing and rhythm — you are working their
words, not replacing them. Add nothing they did not say.

The new information belongs in the prose, in their voice. Do not summarise it,
do not mention it in the third person, and never record it as a bracketed
marker: brackets mark a value you fuzzed under the policy, and are not a way to
note that something was said. A detail you cannot state under the policy is
reduced, never annotated.

If the new information is already fully present in the paragraph, return the
paragraph unchanged — an amendment that changes nothing is reported as such.

Return JSON only, with exactly one event holding the rewritten paragraph:
{{"summary": "one sentence", "keywords": ["..."], "logged": "[~period]" or "",
  "events": [{{"title": "short", "text": "the rewritten paragraph"}}]}}
"""


# Anything that could be a time reference. Deliberately generous — this decides
# whether the creator said *when*, not what they said.
TEMPORAL = re.compile(
    r"\b(19|20)\d{2}\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"
    r"|\b(mon|tues|wednes|thurs|fri|satur|sun)day\b"
    r"|\b(spring|summer|autumn|fall|winter)\b"
    r"|\b(yesterday|today|tonight|tomorrow|weekend)\b"
    r"|\b(last|next|this|past)\s+(night|week|month|year|summer|winter|spring|autumn|fall)\b"
    # Bare `ago`, not `\d+ (days|weeks) ago` — "three days ago" spells its
    # number, and "ago" alone is never anything but a time reference.
    r"|\bago\b",
    re.IGNORECASE,
)


def keep_logged(logged: str, source: str) -> str:
    """`logged`, but only if the source actually said when.

    The ingestion pass invents periods. Told to return "" when the text gives
    no time, it returns `[~mid-July]` anyway — that string is an example inside
    the redaction policy the same prompt carries, and the model pattern-matches
    it. Prompting harder does not fix a model copying its own instructions, so
    the check is here instead of there: no temporal marker in what the creator
    wrote means no period logged, whatever came back.

    An invented date is not a small error in this corpus. It is a fact the
    creator never stated, becoming canon the bot will assert.

    ponytail: a regex over obvious time words, not a date parser. It answers
    "did they mention when at all", and the cost of a miss is an empty field
    the creator can fill — reach for dateparser only if that gets annoying.
    """
    return logged if TEMPORAL.search(source) else ""


# A leading story id, optionally naming an event inside it, and only at the
# very start. Anchored so prose beginning with an id-shaped word is left alone.
# The separator is optional because the creator types this by hand: `st003`,
# `ST 3`, `#ST-003` all name one story, and a rejected id is not a harmless
# miss — it falls through to route(), which logs the amendment as a new story.
LEADING_ID = re.compile(
    r"^\s*#?\s*ST[-_ ]?(\d+)"
    r"(?:\s*/?\s*E[-_ ]?(\d+))?"
    r"\b[:,]?\s*",
    re.IGNORECASE,
)


def parse_story_command(raw: str) -> tuple[str, str, str]:
    """Split a leading `ST-###` or `ST-###/E-###` off the narrative.

    Returns (story_id, event_id, rest). The manual override for a mis-route,
    and the only way to state intent rather than have it guessed:

    - `ST-003 …` names the story and nothing else, so the text is **appended**
      to it as a new event.
    - `ST-003/E-002 …` names the paragraph, so that paragraph is rewritten.

    Appending is the bare-id default deliberately. Picking a paragraph by
    similarity has no floor — the closest of a story's events wins however
    weak the match — and a wrong append costs one delete, where a wrong
    amendment overwrites words that exist nowhere else.

    Returns ("", "", raw) when no id leads, so the caller falls through to
    `route()` unchanged.

    Numbers are zero-padded to the corpus's three-digit form, so `st3/e2` and
    `ST-003/E-002` resolve to the same paragraph. An id that names nothing is
    refused by the caller — never silently turned into a new story.
    """
    found = LEADING_ID.match(raw)
    if not found:
        return "", "", raw
    event = f"E-{int(found.group(2)):03d}" if found.group(2) else ""
    return f"ST-{int(found.group(1)):03d}", event, raw[found.end():].strip()


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
    # it. limit=None: filtering by story must happen before truncation, not
    # after — a capped limit here can crowd every event of the target story
    # out once the corpus holds more stories than the cap, making `events`
    # come back empty for a reason unrelated to matching.
    events = [h for h in index.search(text, embed, limit=None, kind="event")
              if h.chunk.story_id == target]
    # No event of the target story matched *well enough* — leave it unresolved
    # rather than guessing (ranking always produces a winner, and a mutable
    # story file can't afford one picked by default).
    event_id = (
        events[0].chunk.event_id
        if events and events[0].score >= EVENT_THRESHOLD
        else ""
    )
    return Routing(branch="amend", story=story, event_id=event_id, runners_up=summaries[1:])


def merge_keywords(existing: list[str], incoming: list[str]) -> list[str]:
    """`existing` plus whatever `incoming` adds, in that order, no duplicates.

    Keywords ride on every chunk of a story and feed the lexical term of the
    score, so a story that grows while its keywords describe only its first
    events gets harder to find as it gets richer. Unioning is free: `digest()`
    hashes chunk *text*, so changed keywords re-embed nothing, and `refresh()`
    swaps the chunk objects in anyway.

    Order is existing-first so unchanged stories serialise to unchanged bytes.
    Matching is case-insensitive, and the spelling already in the story wins —
    a story is not re-rendered because the pass capitalised "Beach" this time.

    ponytail: unions without a cap, so a heavily amended story accumulates
    keywords and scores higher on generic queries than a fresh one. Cap it —
    or weight by how many events carry the term — if that shows up in routing;
    picking what to drop needs a real corpus, and there isn't one yet.
    """
    merged = list(existing)
    seen = {k.strip().lower() for k in existing if k.strip()}
    for keyword in incoming:
        cleaned = keyword.strip()
        if cleaned and cleaned.lower() not in seen:
            merged.append(cleaned)
            seen.add(cleaned.lower())
    return merged


def _append_events(story: Story, events: list[tuple[str, str]]) -> list[Event]:
    """Add (title, body) pairs to a story in place, returning what was added.

    Ids come from `next_event_id`, which allocates from the maximum, so
    appending never renumbers an event the index already holds a vector for.
    """
    added = []
    for title, body in events:
        event = Event(
            id=next_event_id(story),
            title=title,
            text=body if body.endswith("\n") else body + "\n",
        )
        story.events.append(event)
        added.append(event)
    return added


def propose_addition(
    story: Story,
    events: list[tuple[str, str]],
    directory: Path | None = None,
    keywords: list[str] | None = None,
) -> Proposal:
    """Add new events to a story that already exists, changing nothing in it.

    What `/story ST-003 …` means. The creator names the story the material
    belongs to and nothing inside it is touched, so there is no edit target to
    resolve and nothing to get wrong beyond the story itself — which they
    stated rather than the index guessing.
    """
    directory = directory or STORIES_DIR
    path = directory / f"{story.id}.md"
    if not path.exists():
        raise ValueError(f"{story.id} is not in the corpus — nothing to add to")

    # Parsed from disk, never from the caller's object, for the reason spelled
    # out in propose_amendment: the two drift, and editing the wrong one lets
    # the file round-trip byte-identical while the proposal reports a change.
    grown = parse_story(path.read_text(encoding="utf-8"))
    added = _append_events(grown, events)
    if not added:
        raise ValueError(f"nothing to add to {story.id} — the pass returned no events")
    grown.keywords = merge_keywords(grown.keywords, keywords or [])

    return _propose(
        path=path,
        old=path.read_text(encoding="utf-8"),
        new=render_story(grown),
        summary=f"add to {story.id} — {len(added)} new event(s): "
        + ", ".join(e.id for e in added),
        before="",
        after="\n".join(f"{e.title}\n{e.text}" for e in added).strip(),
    )


def propose_amendment(
    story: Story,
    event_id: str,
    new_text: str,
    directory: Path | None = None,
    additions: list[tuple[str, str]] | None = None,
    keywords: list[str] | None = None,
) -> Proposal:
    """Rewrite one paragraph, and append whatever the paste added beyond it.

    `additions` is (title, body) pairs, already segmented and redacted. The
    creator pastes a longer version of a story they already logged: the first
    segment is the paragraph being amended, and everything after it is new
    material about the same story. Dropping it loses the creator's words
    silently — the one thing this corpus cannot afford — and logging it as a
    separate story splits one narrative in two.

    Appended events take fresh `E-###` ids from the maximum, so nothing already
    embedded is renumbered.

    ponytail: the story's own summary and keywords are left as they stand, so
    the summary chunk goes slightly stale when events are appended. Rewriting
    them would be the model editing text the creator approved earlier under a
    different confirm gate. Revisit if coarse-layer recall measurably suffers.
    """
    directory = directory or STORIES_DIR
    path = directory / f"{story.id}.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""

    # Resolve `target` against the disk-parsed story, not the caller's
    # in-memory one, and edit that same object — the two can drift (a second
    # pending proposal, a concurrent /add), and validating against one while
    # editing the other lets the gate look correct while the amendment
    # silently vanishes. `copy.deepcopy`, not `story` itself, when there's no
    # file yet: the caller's object must not mutate before approval.
    amended = parse_story(old) if old else copy.deepcopy(story)
    target = next((e for e in amended.events if e.id == event_id), None)
    if target is None:
        raise ValueError(
            f"{story.id} has no {event_id}. Events present: "
            f"{', '.join(e.id for e in amended.events) or 'none'}"
        )

    before = target.text
    target.text = new_text if new_text.endswith("\n") else new_text + "\n"

    appended = _append_events(amended, additions or [])
    # The rewritten paragraph is new material too — a detail merged into it is
    # exactly what a later query would search for.
    amended.keywords = merge_keywords(amended.keywords, keywords or [])

    summary = f"amend {story.id}/{event_id} — {target.title}"
    if appended:
        summary += f", and {len(appended)} new event(s): " + ", ".join(
            e.id for e in appended
        )

    return _propose(
        path=path,
        old=old,
        new=render_story(amended),
        summary=summary,
        before=before,
        # The gate's after-panel must show everything the write lands, not just
        # the rewritten paragraph — an appended event the creator never saw is
        # an unreviewed write.
        after="\n".join([target.text, *(f"{e.title}\n{e.text}" for e in appended)]).strip(),
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
