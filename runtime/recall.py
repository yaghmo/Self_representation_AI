"""recall(query) — the one read-only tool the fan surface may call.

Searches the story corpus at chat time. Flat over event chunks only:
chapter and summary chunks exist for *ingestion routing* (which story a new
paste belongs to), and are the wrong signal here — see
2026-08-07-context-budgeting-design.md's "fan retrieval shape" note. Two
near-identical story summaries make the coarse layer the least
discriminative signal for two stories that differ only in one event.

No pinning, no stickiness bookkeeping. Native tool-calling judgement (the
model only calls this when it decides a question needs it) plus the
existing bible.plan_compaction (old turns age out of the prompt over a long
conversation) already give "stays on topic -> doesn't re-search; a stale
fact eventually falls out of context" for free.
"""

from __future__ import annotations

from .index import Embedder, Index

def recall_schema(include_profile: bool) -> dict:
    """The fan surface's one tool. Wording changes with the mode: in
    whole-persona mode the model already has every profile fact in context,
    so the tool is purely for stories the profile doesn't cover — in
    compact mode it also has to reach the profile's own retrievable
    sections, and the description has to say so or the model will never
    think to call it for an ordinary personality/background question.
    """
    if include_profile:
        description = (
            "Look up something about her — a personal story, or a profile "
            "detail (background, preferences, personality, relationships, "
            "skills, goals) not already in what you've been given. Use this "
            "whenever a question needs more than what's in front of you. "
            "Returns the closest matching material, or says none were found."
        )
    else:
        description = (
            "Search the creator's logged personal stories for one that "
            "answers the question. Use this when something asks about a "
            "specific event, memory, or experience the character profile "
            "does not cover. Returns the closest matching moments, or says "
            "none were found."
        )
    return {
        "type": "function",
        "function": {
            "name": "recall",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


RESULT_LIMIT = 3


def recall(
    query: str,
    index: Index,
    embed: Embedder,
    limit: int = RESULT_LIMIT,
    include_profile: bool = False,
    profile_index: Index | None = None,
) -> str:
    """Event-level story hits, each hydrated with its story's own summary
    chunk. When include_profile is set and a profile_index is supplied,
    also searches whole profile sections and merges them in by score — a
    profile-section hit needs no hydration, its own text already stands
    alone.

    Never raises: a search failure degrades to the same shape as a "no
    hits" result, so one bad call costs the model a turn, not the whole
    request — matching tools.run_tool's "a handler must never kill the
    loop" stance already established for the admin side.
    """
    try:
        hits = index.search(query, embed, limit=limit, kind="event")
        if include_profile and profile_index is not None:
            hits = hits + profile_index.search(query, embed, limit=limit, kind="profile_section")
            hits.sort(key=lambda h: h.score, reverse=True)
            hits = hits[:limit]
    except Exception as exc:
        return f"recall failed: {exc}"

    if not hits:
        return f"no matching stories for {query!r}"

    by_key = {c.key: c for c in index.chunks}
    parts = []
    for hit in hits:
        if hit.chunk.kind == "profile_section":
            parts.append(hit.chunk.text)
        else:
            summary = by_key.get(f"{hit.chunk.story_id}/summary")
            header = summary.text if summary is not None else hit.chunk.story_id
            parts.append(f"{header}\n\n{hit.chunk.text}")
    return "\n\n---\n\n".join(parts)


def _self_check() -> None:
    import re
    import zlib

    import numpy as np

    from .index import build, chunks_of
    from .stories import Event, Story

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
    from .index import Chunk as _Chunk

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

    print("recall: ok")


if __name__ == "__main__":
    _self_check()
