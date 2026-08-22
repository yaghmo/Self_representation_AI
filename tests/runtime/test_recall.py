from runtime.recall import recall


def test_recall_self_check():
    import re
    import zlib

    import numpy as np

    from runtime.index import Chunk as _Chunk
    from runtime.index import build, chunks_of
    from runtime.stories import Event, Story

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
        keywords=["hiking"],
        logged="",
        events=[
            Event("E-001", "meeting the guide", "He was already waiting when we pulled in.\n"),
            Event("E-002", "the storm", "It came in fast on the second afternoon.\n"),
        ],
    )
    chunks = chunks_of(story)
    index = build(chunks, fake_embed)

    # An event hit is hydrated with its story's summary chunk as a header.
    # kind="event" means the hit itself is never a summary/chapter chunk.
    result = recall("waiting when we pulled in", index, fake_embed)
    header, _, body = result.partition("\n\n")
    assert header == f"{story.title}. {story.summary}", header
    assert "He was already waiting" in body, body
    assert "meeting the guide" in body, body

    # No match returns the "no matching stories" shape, not an exception or "".
    empty_index = build([], fake_embed)
    none_result = recall("anything", empty_index, fake_embed)
    assert "no matching stories" in none_result, none_result

    # A search failure is caught and degrades to the same non-raising shape.
    class Explodes:
        def search(self, *args, **kwargs):
            raise RuntimeError("index corrupt")

    boom = recall("anything", Explodes(), fake_embed)
    assert boom.startswith("recall failed:"), boom

    # Multiple hits stay ordered by score, highest first — recall() must not
    # reshuffle what Index.search already returned.
    other_story = Story(
        id="ST-002", title="a quiet week", summary="not much happened",
        keywords=[], logged="",
        events=[Event("E-001", "the coffee machine broke", "It died on Tuesday.\n")],
    )
    combined = build(chunks_of(story) + chunks_of(other_story), fake_embed)
    multi = recall("coffee machine broke Tuesday", combined, fake_embed, limit=2)
    first_block = multi.split("\n\n---\n\n")[0]
    assert "coffee machine" in first_block, (multi,)

    # -- profile-section retrieval, folded into the same tool ----------------
    profile_chunks = [
        _Chunk(
            key="profile/5", kind="profile_section", story_id="", event_id="",
            text="## 5. Preferences & Texture\n\n- loves hiking, apparently",
            keywords=[],
        ),
    ]
    profile_index = build(profile_chunks, fake_embed)

    # Default (include_profile=False): a profile-section chunk is never
    # returned, even if it would have scored highest, and even if a
    # profile_index was passed — whole-persona mode's story search must stay
    # byte-identical to today regardless of what's available.
    default_result = recall("hiking", index, fake_embed, profile_index=profile_index)
    assert "loves hiking" not in default_result, (
        "include_profile=False must never surface a profile-section chunk"
    )

    # include_profile=True but no profile_index supplied: same as the
    # default — a caller can't accidentally search profile content by
    # flipping one flag without also holding the index.
    no_index_result = recall("hiking", index, fake_embed, include_profile=True)
    assert "loves hiking" not in no_index_result, (
        "include_profile=True with profile_index=None must not search profile content"
    )

    # include_profile=True, profile_index supplied, only a profile hit
    # matches: returned as raw chunk text, no summary-header hydration
    # attempted (there is no story summary for a profile chunk).
    only_profile = recall(
        "hiking", build([], fake_embed), fake_embed,
        include_profile=True, profile_index=profile_index,
    )
    assert "loves hiking" in only_profile, only_profile
    assert "no matching stories" not in only_profile, only_profile

    # Both a story hit and a profile-section hit, close enough to both
    # score: both appear, each formatted correctly for its own kind, in one
    # call.
    mixed = recall(
        "waiting when we pulled in, loves hiking", index, fake_embed,
        include_profile=True, profile_index=profile_index,
    )
    assert "He was already waiting" in mixed, mixed
    assert "meeting the guide" in mixed, "story hit must still be hydrated with its summary"
    assert "loves hiking" in mixed, "profile-section hit must also appear"
