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

RECALL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "recall",
        "description": (
            "Search the creator's logged personal stories for one that "
            "answers the question. Use this when something asks about a "
            "specific event, memory, or experience the character profile "
            "does not cover. Returns the closest matching moments, or says "
            "none were found."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

RESULT_LIMIT = 3


def recall(query: str, index: Index, embed: Embedder, limit: int = RESULT_LIMIT) -> str:
    """Event-level hits, each hydrated with its story's own summary chunk.

    Never raises: a search failure degrades to the same shape as a "no
    hits" result, so one bad call costs the model a turn, not the whole
    request — matching tools.run_tool's "a handler must never kill the
    loop" stance already established for the admin side.
    """
    try:
        hits = index.search(query, embed, limit=limit, kind="event")
    except Exception as exc:
        return f"recall failed: {exc}"

    if not hits:
        return f"no matching stories for {query!r}"

    by_key = {c.key: c for c in index.chunks}
    parts = []
    for hit in hits:
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

    print("recall: ok")


if __name__ == "__main__":
    _self_check()
