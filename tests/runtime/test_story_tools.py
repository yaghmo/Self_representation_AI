import copy
import re

import numpy as np

import runtime.story_tools as story_tools_module
from runtime.index import build, all_chunks
from runtime.stories import Event, Story, parse_story, render_story
from runtime.story_tools import (
    NoChange,
    keep_logged,
    merge_keywords,
    parse_story_command,
    propose_addition,
    propose_amendment,
    propose_new_story,
    route,
)


def test_story_tools_self_check(tmp_path):
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
    import zlib

    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, zlib.crc32(word.encode("utf-8")) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    directory = tmp_path / "main"
    directory.mkdir()
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
    trunc_dir = tmp_path / "trunc"
    trunc_dir.mkdir()
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
    #
    # Patched on the module object, not via a bare `global` in this test
    # function — `route()` lives in `runtime.story_tools` and resolves
    # EVENT_THRESHOLD against THAT module's globals, not this test
    # module's. A `global EVENT_THRESHOLD` here would rebind only this
    # file's own (nonexistent) global and silently do nothing.
    restore = story_tools_module.EVENT_THRESHOLD
    story_tools_module.EVENT_THRESHOLD = 0.0
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
        story_tools_module.EVENT_THRESHOLD = 1.01
        floored = route(overlap_query, trunc_index, fake_embed, trunc_dir)
        assert floored.branch == "amend", floored.branch
        assert floored.story is not None and floored.story.id == "ST-001"
        assert floored.event_id == "", (
            "a paragraph under the floor was picked anyway: "
            f"{floored.event_id}"
        )
    finally:
        story_tools_module.EVENT_THRESHOLD = restore

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
