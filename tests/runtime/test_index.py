import re
import zlib
from pathlib import Path

import numpy as np

from runtime.index import CHAPTER_SIZE, Hit, build, chapter_of, chunks_of, in_id_order, load_index
from runtime.stories import Event, Story


def test_index_self_check(tmp_path):
    # A deterministic stand-in for bge-m3: hash each word into a fixed number
    # of buckets. Shares the only properties the index depends on — same text
    # gives the same vector, shared words give a higher cosine — and needs no
    # weights, so this check runs anywhere.
    #
    # zlib.crc32, not the builtin hash(): str hashing is salted per-process
    # (PEP 456), so hash(word) % width buckets words differently on every
    # run and any assertion sitting close to its threshold flips depending on
    # the process's random seed. crc32 is deterministic across processes and
    # machines, so the same corpus always buckets the same way.
    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, zlib.crc32(word.encode("utf-8")) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    story = Story(
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

    chunks = chunks_of(story)
    assert [c.key for c in chunks] == ["ST-001/summary", "ST-001/E-001", "ST-001/E-002"]
    assert chunks[0].kind == "summary" and chunks[1].kind == "event"
    assert chunks[1].event_id == "E-001"

    # -- chapters ------------------------------------------------------------
    # A short story gets none: one chapter over it would be a near-duplicate of
    # the story summary, competing for the same queries.
    short = Story(id="ST-009", title="short", summary="s", keywords=[], logged="",
                  events=[Event(f"E-{n:03d}", f"t{n}", f"body {n}\n")
                          for n in range(1, CHAPTER_SIZE + 1)])
    assert not [c for c in chunks_of(short) if "/C-" in c.key], "chaptered below the threshold"

    long_story = Story(
        id="ST-010", title="a long one", summary="the original three events",
        keywords=["k"], logged="",
        events=[Event(f"E-{n:03d}", f"title {n}", f"body {n}\n") for n in range(1, 8)],
    )
    chaptered = chunks_of(long_story)
    assert [c.key for c in chaptered if "/C-" in c.key] == ["ST-010/C-001", "ST-010/C-002"]
    first = next(c for c in chaptered if c.key == "ST-010/C-001")
    # Chapters are coarse chunks, so routing sees them as it sees any summary
    # and resolves them to their story with no idea chapters exist.
    assert first.kind == "summary" and first.story_id == "ST-010" and first.event_id == ""
    assert first.text == "title 1. body 1 title 2. body 2 title 3. body 3 title 4. body 4", (
        first.text
    )
    # No story-title prefix: it is the same in every chapter of a story, so it
    # dominates the vector and flattens them into each other. Measured — see
    # `_chapters`.
    assert not first.text.startswith("a long one"), first.text

    # The invariant the whole scheme rests on. Membership comes from the
    # event's own number, so appending cannot move an earlier event into a
    # different chapter and re-embed content that never changed. Ids are
    # allocated from the maximum and never reused, so this holds under
    # deletion too.
    before = {c.key: c.digest() for c in chunks_of(long_story) if "/C-" in c.key}
    long_story.events.append(Event("E-008", "title 8", "body 8\n"))
    after = {c.key: c.digest() for c in chunks_of(long_story) if "/C-" in c.key}
    assert before["ST-010/C-001"] == after["ST-010/C-001"], "a full chapter was rewritten"
    assert before["ST-010/C-002"] != after["ST-010/C-002"], "the filling chapter must grow"
    assert chapter_of("E-001") == 1 and chapter_of("E-004") == 1
    assert chapter_of("E-005") == 2 and chapter_of("E-008") == 2
    # A gap left by a deleted event does not renumber what follows it.
    assert chapter_of("E-009") == 3

    index = build(chunks, fake_embed)

    # Coarse layer finds the story; fine layer finds the event inside it.
    summaries = index.search("hiking trip storm", fake_embed, kind="summary")
    assert summaries[0].chunk.story_id == "ST-001", summaries[0].chunk.key
    events = index.search("waiting when we pulled in", fake_embed, kind="event")
    assert events[0].chunk.event_id == "E-001", events[0].chunk.key

    # Identical text scores 1.0 (convex blend: 0.85 * dense + 0.15 * lexical, ceiling 1.0).
    # The chunk text for E-002 is "the storm. It came in fast on the second afternoon."
    identical_query = "the storm. It came in fast on the second afternoon."
    same = index.search(identical_query, fake_embed)
    assert same[0].chunk.event_id == "E-002", f"matched wrong chunk: {same[0].chunk.key}"
    assert same[0].score >= 0.99, f"identical text scored {same[0].score}, expected >= 0.99"
    assert same[0].score <= 1.0, f"score {same[0].score} exceeds 1.0"

    # A near-miss: shares most words but is not identical text must score below 0.95.
    # "the storm. It came in fast on the second morning" differs by one word.
    near_miss = index.search("the storm. It came in fast on the second morning.", fake_embed)
    assert near_miss[0].score < 0.95, f"near-miss scored {near_miss[0].score}, expected < 0.95"

    # All scores from search must stay within [0, 1.0].
    all_scores = index.search("hiking", fake_embed, limit=None)
    for hit in all_scores:
        assert 0 <= hit.score <= 1.0, f"score {hit.score} out of bounds"

    # Ranked by score for routing, but re-ordered by stable id for the prompt.
    # Both orderings are needed and they are not the same list.
    shuffled = [Hit(chunks[2], 0.9), Hit(chunks[0], 0.8), Hit(chunks[1], 0.7)]
    assert [h.chunk.key for h in in_id_order(shuffled)] == [
        "ST-001/summary", "ST-001/E-001", "ST-001/E-002"
    ]

    # An amendment re-embeds only what changed. A one-line edit that rebuilt
    # the corpus would make every amendment cost a full pass.
    story.events[0].text = "He was already waiting, red jacket, when we pulled in.\n"
    changed = index.refresh(chunks_of(story), fake_embed)
    assert changed == 1, f"re-embedded {changed} chunks, expected 1"
    assert index.refresh(chunks_of(story), fake_embed) == 0, "re-embedded an unchanged corpus"

    # Refreshing an empty index must take its width from the incoming vectors,
    # not from the placeholder an empty index carries.
    grown = build([], fake_embed)
    assert grown.refresh(chunks_of(story), fake_embed) == 3
    assert grown.vectors.shape == (3, 64), grown.vectors.shape

    path = index.save(tmp_path / "stories.npz")
    reloaded = load_index(path)
    assert [c.key for c in reloaded.chunks] == [c.key for c in index.chunks]
    assert np.allclose(reloaded.vectors, index.vectors)

    # A corrupt index file (garbage bytes) must not crash; degrade to empty.
    corrupt_path = tmp_path / "corrupt.npz"
    corrupt_path.write_bytes(b"not a valid npz file\x00\xff\xfe")
    corrupt = load_index(corrupt_path)
    assert len(corrupt.chunks) == 0, "corrupt index should return empty"
    assert corrupt.vectors.shape == (0, 1), "corrupt index should have empty vector shape"

    # A truncated file (interrupted write mid-save) must not crash; degrade to empty.
    # This is the most common real-world corruption mode.
    truncated_path = tmp_path / "truncated.npz"
    full_data = path.read_bytes()
    truncated_path.write_bytes(full_data[:len(full_data) // 2])
    truncated = load_index(truncated_path)
    assert len(truncated.chunks) == 0, "truncated index should return empty"
    assert truncated.vectors.shape == (0, 1), "truncated index should have empty vector shape"
