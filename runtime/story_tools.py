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
# closest of a story's events wins however weak the match, so naming a story
# and pasting unrelated material proposed overwriting whichever paragraph
# happened to rank first. Below this the story resolves and the paragraph does
# not, which `Routing` already treats as unresolved and the caller already
# reports — no new failure path, just an honest one.
#
# Lower than AMENDMENT_THRESHOLD on purpose: the summary layer has already
# established the story is relevant, so this only has to separate "this
# paragraph" from "some other paragraph of the same story". Untuned against a
# real corpus, like the two above it. Too high sends routed amendments to the
# explicit `ST-###/E-###` syntax, which is the safe direction to be wrong in.
#
# Unvalidated, and not validatable here: the self-check's toy embedder scores a
# legitimate match at 0.41, but its scale is a hash function's, not bge-m3's.
# The tests below neutralise this constant rather than satisfy it, and prove
# the floor gates by cranking it past 1.0. First real corpus decides the value.
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


# The amend contract, stated rather than implied. `INGEST_PROMPT` is a
# segmentation prompt, and running it over "the wave contained popcorn" plus the
# paragraph being edited framed the new detail as something to *reduce*: one run
# dropped it entirely, the next wrote `[~popcorn mentioned]` — a fuzzed-value
# marker copied out of the redaction rules the same prompt carries. Same failure
# as the invented `[~mid-July]` that `keep_logged` exists to catch: the model
# does the task the prompt describes, and merging was never described.
#
# The policy still rides along, because a merged detail is new material entering
# the corpus and has to be reduced on the way in like anything else.
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
    # it. limit=None: the ranked list must be filtered by story before it is
    # truncated, not after. A capped limit here (`hits[:8]` then filter)
    # crowds every event of the target story out once the corpus holds more
    # than that many stories, `events` comes back empty for a reason that
    # has nothing to do with matching, and a fallback that guesses would
    # silently amend the wrong paragraph — the exact failure mode a mutable
    # story file cannot afford (see the module docstring).
    events = [h for h in index.search(text, embed, limit=None, kind="event")
              if h.chunk.story_id == target]
    # No event of the target story matched *well enough* — leave it unresolved
    # rather than guessing. This cannot cross into another story: the list is
    # already filtered to `target` before this is read. The floor is what
    # separates "this paragraph" from "the least bad of three": ranking always
    # produces a winner, and a mutable story file cannot afford one picked by
    # default (see the module docstring).
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


def _self_check() -> None:
    import tempfile
    import zlib

    # -- explicit story id ---------------------------------------------------
    # A bare story id appends; only `ST-###/E-###` names an edit target.
    assert parse_story_command("ST-001 we drove to the lake") == (
        "ST-001",
        "",
        "we drove to the lake",
    ), "a leading id targets that story and leaves the narrative behind"
    assert parse_story_command("st-001 we drove") == ("ST-001", "", "we drove"), "case insensitive"
    assert parse_story_command("we drove to the lake") == (
        "",
        "",
        "we drove to the lake",
    ), "no id means route() decides"
    # A bare id with no narrative is not a story.
    assert parse_story_command("ST-001") == ("ST-001", "", "")
    # Must not eat text that merely starts with something id-shaped.
    assert parse_story_command("STORY about a lake") == ("", "", "STORY about a lake")
    # The separator is optional and the number is padded: the creator types the
    # id by hand, and an id that fails to parse falls through to route(), which
    # logs an amendment as a brand new story.
    assert parse_story_command("st003 i walked toward the rocks") == (
        "ST-003",
        "",
        "i walked toward the rocks",
    ), "a hyphenless id is still an id"
    assert parse_story_command("ST 3 we drove") == ("ST-003", "", "we drove"), "space separator"
    assert parse_story_command("#ST-003 we drove") == ("ST-003", "", "we drove"), "leading hash"
    assert parse_story_command("st_003: we drove") == ("ST-003", "", "we drove"), "underscore"
    # Padding never mangles an id already wider than three digits.
    assert parse_story_command("ST-1234 we drove") == ("ST-1234", "", "we drove")
    # A saint is not a story id — the separator is optional, the digits are not.
    assert parse_story_command("St. Peter's was closed") == ("", "", "St. Peter's was closed")

    # An event id names the paragraph to rewrite, in every spelling the story
    # id accepts. Without it the material is new, and appending is what the
    # creator meant — the destructive reading must be the one they type out.
    assert parse_story_command("ST-003/E-002 red jacket") == ("ST-003", "E-002", "red jacket")
    assert parse_story_command("st3/e2 red jacket") == ("ST-003", "E-002", "red jacket")
    assert parse_story_command("ST-003 / E-002: red jacket") == (
        "ST-003", "E-002", "red jacket",
    ), "spaces around the slash"
    # The slash is optional too. Without this, `ST-003 E-002 …` appends and the
    # id text itself is swallowed into the narrative — redacted, embedded and
    # stored as the creator's own words, with no gate anywhere to catch it.
    assert parse_story_command("ST-003 E-002 red jacket") == ("ST-003", "E-002", "red jacket")
    assert parse_story_command("st 3 e 4 red jacket") == ("ST-003", "E-004", "red jacket")
    assert parse_story_command("st3 e4 red jacket") == ("ST-003", "E-004", "red jacket")
    # `E` still has to be followed by digits, so prose stays prose.
    assert parse_story_command("ST-003 elephants everywhere") == (
        "ST-003", "", "elephants everywhere",
    )
    # A slash that is not an event id belongs to the narrative.
    assert parse_story_command("ST-003 he/she waved") == ("ST-003", "", "he/she waved")

    # -- keywords -----------------------------------------------------------
    # Existing first, so a story whose keywords did not change renders to the
    # same bytes; the spelling already on disk wins a case-only collision.
    assert merge_keywords(["beach", "waves"], ["Beach", "popcorn"]) == [
        "beach", "waves", "popcorn",
    ]
    assert merge_keywords([], ["a", "a", " a ", "b"]) == ["a", "b"], "dedupes within incoming"
    assert merge_keywords(["beach"], []) == ["beach"]
    assert merge_keywords(["beach"], ["", "  "]) == ["beach"], "blanks are not keywords"

    # A period survives only when the creator's own words carry a time. The
    # observed failure is the model returning `[~mid-July]` for text with no
    # date in it at all, copied out of the example in the policy it was handed.
    assert keep_logged("[~mid-July]", "On 15 July I flew to Lisbon.") == "[~mid-July]"
    assert keep_logged("[~2023]", "We went back the summer after that.") == "[~2023]"
    assert keep_logged("[~last week]", "It rained three days ago and we stayed in.")
    assert keep_logged("[~mid-July]", "I fixed a bicycle chain and got grease everywhere.") == ""
    assert keep_logged("[~late summer 2023]", "She laughed at the door handle.") == ""
    # "May" is a month and a verb. Generous on purpose — a spurious period the
    # creator can delete beats an invented one they have to notice.
    assert keep_logged("[~May]", "I may go back at some point.") == "[~May]"

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

            # EVENT_THRESHOLD is neutralised here, not satisfied. The real
            # E-001 match scores 0.41 under the toy embedder, whose scale is a
            # hash function's and has nothing to do with bge-m3's — a fixture
            # built on it can show *which* paragraph ranks first, never whether
            # a score clears an absolute floor. What is under test is the
            # filter-before-truncate fix, so the floor is taken out of the way.
            global EVENT_THRESHOLD
            restore, EVENT_THRESHOLD = EVENT_THRESHOLD, 0.0
            try:
                overlap = route(overlap_query, trunc_index, fake_embed, trunc_dir)
                assert overlap.branch == "amend", overlap.branch
                assert overlap.story is not None and overlap.story.id == "ST-001"
                assert overlap.event_id == "E-001", (
                    "truncated before the filter — picked the wrong paragraph: "
                    f"{overlap.event_id}"
                )

                # And the floor itself: the same query, the same ranked list,
                # a threshold nothing can clear. The story still resolves, the
                # paragraph does not, and unresolved is the outcome — never
                # the best of a bad set.
                EVENT_THRESHOLD = 1.01
                floored = route(overlap_query, trunc_index, fake_embed, trunc_dir)
                assert floored.branch == "amend", floored.branch
                assert floored.story is not None and floored.story.id == "ST-001"
                assert floored.event_id == "", (
                    "a paragraph under the floor was picked anyway: "
                    f"{floored.event_id}"
                )
            finally:
                EVENT_THRESHOLD = restore

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

        # The observed failure: the ingestion pass hands back the paragraph it
        # was given, the file round-trips byte-identical, and the gate reports
        # a write that never happened. Refused rather than proposed.
        try:
            propose_amendment(
                after, "E-001", after.events[0].text, directory,
            )
        except NoChange:
            pass
        else:
            raise AssertionError("an amendment that changes nothing was proposed")

        # The other half of that failure: the paste was a longer version of the
        # whole story, so the ingestion pass segmented it and everything past
        # the first segment used to be dropped on the floor.
        grew = propose_amendment(
            after,
            "E-001",
            after.events[0].text,
            directory,
            additions=[("meeting a stranger", "She offered me her hand.\n"),
                       ("the sunset", "We sat and watched it go down.\n")],
        )
        landed = parse_story(grew.new_text)
        assert [e.id for e in landed.events] == ["E-001", "E-002", "E-003", "E-004"], (
            f"appended events did not land or renumbered: {[e.id for e in landed.events]}"
        )
        assert "red jacket" in landed.events[0].text, "the amended paragraph was lost"
        assert landed.events[2].title == "meeting a stranger", landed.events[2].title
        assert "watched it go down" in landed.events[3].text
        assert "E-003" in grew.summary and "E-004" in grew.summary, grew.summary

        # `/story ST-001 …` — new material for a story that exists, touching
        # nothing already in it. No edit target to resolve, so nothing to
        # overwrite by guessing wrong.
        added = propose_addition(
            after, [("the drive home", "We got back after dark.\n")], directory,
            keywords=["mountains", "headlights"],
        )
        with_new = parse_story(added.new_text)
        # New events bring their keywords with them, or the story gets harder
        # to find as it gets richer. Existing ones are kept, never replaced.
        assert with_new.keywords[:3] == ["hiking", "mountains", "weather"], with_new.keywords
        assert "headlights" in with_new.keywords, with_new.keywords
        assert [e.id for e in with_new.events] == ["E-001", "E-002", "E-003"], (
            f"append renumbered or dropped: {[e.id for e in with_new.events]}"
        )
        assert with_new.events[0].text == after.events[0].text, "append edited an existing event"
        assert with_new.events[1].text == after.events[1].text, "append edited an existing event"
        assert "got back after dark" in with_new.events[2].text
        assert (directory / "ST-001.md").read_text(encoding="utf-8") == render_story(after), (
            "proposal wrote to disk before approval"
        )
        # An empty pass is a failure to report, not a write of nothing.
        try:
            propose_addition(after, [], directory)
        except ValueError as exc:
            assert "no events" in str(exc), str(exc)
        else:
            raise AssertionError("an empty addition was proposed")
        # Everything the write lands has to be visible at the gate.
        assert "She offered me her hand." in grew.after, grew.after
        assert (directory / "ST-001.md").read_text(encoding="utf-8") == render_story(after), (
            "proposal wrote appended events to disk before approval"
        )

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
