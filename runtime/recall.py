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
