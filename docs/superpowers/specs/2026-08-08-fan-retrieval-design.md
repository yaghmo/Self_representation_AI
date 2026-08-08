# Fan-path retrieval — `recall(query)` over the story corpus

**Date:** 2026-08-08
**Status:** design, approved
**Touches:** `runtime/recall.py` (new), `service/main.py`, `runtime/chat_app.py`

The last unbuilt piece named in CLAUDE.md's status section: `bible.assemble()`
already holds the profile whole, and the embedder/index built for `/story`
routing are otherwise unused at chat time. This spec wires them into the fan
surface as a model-invoked, read-only tool — nothing reads `sources.md`,
nothing writes anything, and `character.md` stays exactly as it is today
(whole, in context, never retrieved).

## Why a tool, not automatic retrieval

Two shapes were considered: the server always embeds the latest user message
and injects top-k results every turn (no tool-calling requirement, but
retrieves even on "thanks!" and risks surfacing an irrelevant story), versus
the model deciding via a tool call whether a question needs a specific
personal story at all. Chosen: the tool. Precision over simplicity — the
model only searches when it judges the question needs it.

## Where it runs — server-side, invisible to the client

`runtime/agent.py`'s own docstring is explicit: "The loop runs client-side
... so no deployment can reach `data/` over HTTP." That rule is about
*write* tools reaching `data/` from a public deployment — a different trust
boundary than one server-supplied, read-only search over content the
creator already chose to make answerable. It does not apply here, and
carving out a second, server-side loop for exactly one safe tool is cleaner
than stretching the client-side loop (built for proposals, confirm gates,
and multi-tool admin flows) to cover a fan surface that has none of that.

Consequence: **`chat_app.py`'s fan branch needs zero changes.** It already
posts one message to `/chat` and renders one reply. The internal loop —
deciding whether to search, running the search, feeding the result back,
looping until there's a real answer — lives entirely inside
`service/main.py`, inside the existing `ChatResponse` contract.

## `/chat/stream` is untouched

It keeps refusing tool calls exactly as today. Fan mode simply stops using
it — no streaming, no per-token latency win, replaced by a brief pause
(the internal loop resolving) before the whole reply appears at once. A
messenger-style chat, not a token-by-token one. `chat_app.py`'s stream
checkbox is forced off (or hidden) whenever `agent_mode` is `False`; the
admin path is unaffected.

## `runtime/recall.py` (new)

Same family as `bible.py` / `tools.py` — a schema plus a pure-ish function,
no HTTP, no model.

```python
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

def recall(query: str, index: Index, embed: Embedder, limit: int = 3) -> str:
    ...
```

**Search scope:** `index.search(query, embed, limit=limit, kind="event")`
only. Chapter and summary chunks exist for *ingestion routing* — deciding
which story a new paste belongs to — and are the wrong signal here for the
same reason recorded in `2026-08-07-context-budgeting-design.md`'s "fan
retrieval shape" note: near-identical story summaries make the coarse layer
the least discriminative signal for two similar stories that differ only in
one event. Flat, event-level search is what was already decided; this spec
just builds it.

**Hydration:** each hit is an event chunk. Its parent story's context comes
from the *existing* summary chunk already sitting in the same loaded index —
`next(c for c in index.chunks if c.key == f"{hit.chunk.story_id}/summary")`
— not a second lookup path through `stories.py`. One dict-shaped scan over
chunks already in memory.

**Ordering:** by score, most-relevant first. The "stable id ordering" rule
in CLAUDE.md's fan-prompt-layout constraints is about a block that gets
*pinned and re-shown* across turns without changing — reordering it turn to
turn would invalidate the KV prefix for no reason. Nothing here is pinned or
re-shown: a tool result, once written into a request's transcript, is never
recomputed or reordered later. That constraint doesn't bind a one-shot
result, so score order (what actually matters for a single call) is used
instead.

**No stickiness machinery.** CLAUDE.md speculatively describes pinning the
retrieved block while on-topic and rebuilding on a shift. Not built — two
things already do that job:

1. Native tool-calling semantics: the model only calls `recall` when it
   judges the current question needs it. It doesn't re-search a topic it's
   already answered in this exchange, because the answer it already gave is
   sitting right there in the transcript.
2. `bible.plan_compaction`, already built (`2026-08-07-context-budgeting-design.md`),
   ages old turns out of the prompt over a long conversation. A much older
   recalled fact naturally falls out of context the same way any old turn
   does; if it's still needed, the model just calls `recall` again.

**Formatting a "no hits" result:** `index.search` returning nothing (or
under some minimum score — no threshold added here, first cut is "however
many `limit` returns") produces a plain string like
`"no matching stories for {query!r}"`, so the model can say it doesn't know
rather than treating an empty tool result as a crash.

## `service/main.py`

**Index + embedder lifecycle:** loaded once, lazily, the same shape as
`_get_model()` — a module-level cache, populated on first use by a non-agent
`/chat` request. If loading fails (no embedder configured, per
`EmbeddingNotConfigured` — the same exception `chat_app.py` already
catches for `/story`), the tool is simply never offered that session. No
error surfaced to the fan — the bot answers from persona alone, same as
`/story` degrading gracefully on the admin side today. This is a genuine
gap in observability (the creator has no signal that fan retrieval is
silently off), acceptable for now since the admin already has an equivalent
blind spot for `/story`.

**The internal loop**, only entered when `not model.agent`:

```
messages = assemble(...)                      # existing _prompt_for path
for _ in range(MAX_RECALL_ITERATIONS):         # = 3
    reply = model.chat(messages, tools=[RECALL_SCHEMA], ...)
    calls = model._backend.last_tool_calls
    if not calls:
        return reply                            # done — real answer
    messages.append(assistant turn carrying calls)
    for call in calls:
        result = recall(call.query, index, embed)   # never raises — see below
        messages.append(Message("tool", result, tool_call_id=call.id))
# cap hit and still calling tools: force a real answer
return model.chat(messages, ...)                 # no tools param this time
```

`recall()` itself never raises out to this loop — a search failure (corrupt
index, embed error) is caught and turned into the same shape as a "no hits"
result (`"recall failed: {reason}"`), so one bad call degrades to the model
saying it couldn't find something rather than a 502 for the whole turn.
Mirrors `tools.run_tool`'s "a handler must never kill the loop" stance,
already established for the admin side.

**Not touching `_reject_tools`.** It only inspects `request.messages` —
client-supplied input. The internal loop's tool-call and tool-result
messages are appended to the already-validated, already-assembled prompt
*after* that check runs, entirely server-generated. A client still cannot
supply its own `tools`, still cannot forge a `tool`-role message into
`request.messages` — both rejected exactly as today.

**Ephemeral, not persisted.** The tool-call/tool-result exchange inside one
`/chat` request never reaches the client and is discarded once that request
returns. The next user turn resends only the plain-text history
`chat_app.py` already keeps (per `2026-08-08-chat-persistence-design.md`) —
the *substance* of what was recalled survives in the assistant's own prior
answer, in prose; the raw retrieved chunk does not need to persist for that
to work.

## Out of scope

- **`bible_strategy` / retrieving `character.md` itself.** That config
  field exists on `Model` and is threaded through `status()`, but nothing in
  `bible.py` currently branches on it — `build_persona()` always loads the
  whole profile. This spec does not change that. It's a separate, still-open
  question about the *persona*, not the story corpus, and conflating the two
  would be scope creep.
- **`sources.md` retrieval.** Admin-only by design (`bible.py`'s own
  docstring) — a retrieval hit there would surface a whole raw entry to a
  stranger. Never in scope for this tool.
- **Recall on the admin surface.** Admin's tool set (`tools.TOOL_SCHEMAS`) is
  curated separately; adding `recall` there is a future, independent
  decision, not required by anything here.
- **Retrieval quality tuning** (score thresholds, reranking, multi-query).
  The story corpus is currently empty (per CLAUDE.md status) — nothing to
  tune against yet. First cut is deliberately plain.
- **Observability for a silently-unavailable embedder on the fan path** —
  noted above as a real gap, not fixed here.

## Testing

`runtime/recall.py` gets its own `_self_check()`, same shape as
`index.py`'s — a fake deterministic embedder, no real weights, no server.
Covers:

- an event-chunk hit is hydrated with its story's summary text, not just
  the bare event
- `kind="summary"`/chapter chunks are never returned directly as hits
- results come back ordered by score, highest first
- an empty/no-match search returns the "no matching stories" string, not an
  exception or an empty string
- a search that raises (simulated) is caught and returns the
  `"recall failed: ..."` shape rather than propagating

`service/main.py`'s existing `_self_check()` (TestClient-based, no real
model) gets cases for the internal loop, with a scripted fake backend:

- a non-agent request where the model answers immediately (no tool call):
  identical behavior to today, `recall` never invoked
- a non-agent request where the model calls `recall` once, then answers:
  final content reflects the tool result, and the tool exchange never
  appears in the HTTP response body
- the `MAX_RECALL_ITERATIONS` cap: a model that keeps calling `recall`
  forever still gets a bounded number of searches and returns *something*,
  not an infinite loop or a timeout
- agent-mode requests are completely unaffected — `recall` is never in
  their tool list, existing admin `_self_check` cases keep passing unchanged
- a client-supplied `tools` list or forged `tool`-role message on a
  non-agent request is still rejected exactly as today (regression guard —
  confirms `_reject_tools` needed no changes)
