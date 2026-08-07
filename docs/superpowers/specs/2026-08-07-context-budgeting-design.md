# Context budgeting — ingestion reply budget and chat compaction

**Date:** 2026-08-07
**Status:** design, approved
**Touches:** `runtime/bible.py`, `service/main.py`, `runtime/chat_app.py`

Two independent problems that share one chokepoint. `assemble()` has exactly
three callers — `_prompt_for()` (`service/main.py:193`), `ingest()`
(`service/main.py:382`), and its own `_self_check()` — so both fixes land in
one function rather than in every caller.

## Motivating measurements

Taken from `logs/service.log` on 2026-08-07, `qwen3-8b-instruct-q4km`,
`context_tokens: 8192`.

| Observation | Value |
|---|---|
| Chat prompt floor, 1 message in history | 5,273 tokens |
| Chat prompt after ~9 turns | 7,081 tokens (86% of window) |
| Room after persona | ~1,895 tokens |
| `/ingest` prompt (INGEST_PROMPT + policy) | ~1,075 tokens |
| Longest observed history | 23 messages in one session |

The persona is ~5.2k of an 8,192 window. The ingestion prompt is ~1k, so a
story has far more headroom than a chat turn — the two paths need different
budgets, not one shared cap.

## Part 1 — ingestion reply budget

### The defect

`runtime/chat_app.py:440` posts to `/ingest` without `max_tokens`:

```python
response = post("/ingest", {"text": text, "existing": existing})
```

`IngestRequest.max_tokens` defaults to 1024, so the *reply* is capped at 1024
tokens regardless of input size. The reply echoes the creator's text back
redacted — policy preserves phrasing, so it barely shrinks — plus a summary,
keywords, event titles and JSON scaffolding.

A story over roughly 900 tokens (~3.5k chars) therefore produces more than
1024 tokens of JSON, gets cut mid-object, `json_block()` returns `None`, and
the creator sees "The ingestion pass did not return JSON. Nothing ingested."
The message names the symptom and hides the cause: nothing about the story
was wrong, and no length was ever stated.

Meanwhile `assemble()` will happily accept ~5k tokens of input, because
`reserve_tokens` is `max(1024, max_tokens * 2)` and `max_tokens` never grows.
Input is allowed to be roughly 5x what the output can express.

### The fix

The server decides, because the server holds the tokeniser. `max_tokens`
becomes optional on `IngestRequest`; `None` means auto:

```
reply_budget = int(input_tokens * REPLY_RATIO) + REPLY_FLOOR
REPLY_RATIO = 1.4
REPLY_FLOOR = 256
```

`REPLY_RATIO` is a guess, and gets a `ponytail:` comment saying so. 1.0 covers
the echoed text; the remaining 0.4 covers summary, keywords, titles and JSON
syntax. The honest upgrade path is measuring the realised ratio once a real
corpus exists — until then it is deliberately generous, because being wrong
low means a truncated reply and being wrong high means a slightly early
refusal.

The input cap is derived, not chosen separately:

```
persona + input + (input * 1.4 + 256) <= context
input <= (context - persona - 256) / 2.4
```

At `context=8192`, `persona≈1075`: **~2,858 tokens (~11k chars)**, roughly 3x
what can be ingested today.

Over that, `/ingest` returns **413** naming real numbers and the remedy:

> This story is ~N tokens. The ingestion cap is ~2,858 tokens (about 11k
> characters) at the current context size. Split it at a scene break and send
> the halves as two `/story` calls — they route independently, and the second
> will offer to amend the first if they overlap.

`chat_app.py` stops sending `max_tokens` entirely and surfaces the 413 detail
verbatim.

### Rejected: auto-splitting long stories

Chunking at paragraph boundaries and merging the events into one story handles
any length, but merging summaries and keywords across passes is real
complexity, and the routing decision (new / amend / duplicate) becomes
ambiguous when only some chunks match an existing story. Splitting is a
judgement call about where a story breaks, which is the creator's to make.

## Part 2 — chat compaction

### Current behaviour

`assemble()` (`runtime/bible.py:224-231`) walks history newest-first and stops
at the first message that doesn't fit. Everything older is dropped, silently.
The model forgets, and nothing says so.

### Design

`assemble()` stays pure — state lives in the caller, which is also what
CLAUDE.md asks for ("the user writes their own RAG and manages their own
context windows"). Two additions to `runtime/bible.py`:

**`plan_compaction(history, room, count) -> tuple[list[Message], list[Message]] | None`**

Pure, no model call. Returns `None` when no compaction is needed. Otherwise
returns `(to_summarize, to_keep)`.

- Trips when history exceeds **80%** of post-persona room. Compacting before
  the wall rather than at it means a long reply never lands mid-turn.
- Splits at the **60%-of-tokens** mark — oldest 60% summarized, newest 40%
  verbatim. Measured in tokens, not message count, so one long turn doesn't
  skew the split.
- **Snaps the boundary forward past any tool-call pair**, so a `tool` result
  never outlives the assistant turn that called it. `_whole_tool_pairs()`
  already drops orphans downstream; this prevents creating them.

**`assemble(..., summary: str = "")`**

When `summary` is non-empty, inserts it directly after the persona.

### Prompt layout

```
[system]  persona          <- byte-identical, always first
[user]    summary block    <- only when compaction has happened
[...]     verbatim tail
```

The persona stays first and unchanged, so the KV prefix survives compaction.
Only tokens after the persona are recomputed, and only once per compaction —
not once per turn.

### Stickiness

The summary is computed **once** when the threshold trips, then frozen and
passed back unchanged on subsequent turns. Re-summarizing every turn would
rewrite the prefix every turn and defeat the cache continuously.

The caller owns this: on compaction it drops the summarized messages from its
own history and stores the summary in session state. On the *next* compaction
it prepends the existing summary to the material being summarized, so
summaries fold rather than nest.

### Why the summary is a user message, not a system message

`_reject_client_system()` exists so a fan cannot supply system content. A
`summary` field that lands in a system message reopens exactly that hole — a
forged request could carry a persona override, including past the §10 hard
constraints.

As a **user-role** message (`Earlier in this conversation: …`) it grants no
authority a client didn't already have, since a client can already write user
turns. The persona is still assembled server-side, still first, still
un-overridable. No session store, no new state on the service.

### Fabrication guard

The summary is model-generated text that re-enters context as if it were
transcript. Observed in `logs/service.log` the same day, unprompted:

> "it is reasonable to infer that you are also from Neria"

If a compaction summary invents a detail like that, the bot inherits it as
memory and asserts it downstream, with no cite and nothing marking it as
derived. Two mitigations:

1. The summary prompt carries the ingestion prompt's rule verbatim — nothing
   added that was not in the turns being summarized.
2. The block is labeled in-context as a summary, so a later reader can tell
   derived text from actual turns.

## Testing

Extends the existing `_self_check()` in `runtime/bible.py` — `assert`-based,
run with `python -m runtime.bible`. No framework, no fixtures, per the repo's
established idiom. A fake summarizer (returns a fixed string) keeps it offline.

- `plan_compaction` returns `None` below the threshold and a split above it
- the split never separates a tool call from its result
- persona remains first and byte-identical after compaction
- a second compaction folds the prior summary rather than nesting it
- `assemble(summary="")` is byte-identical to today's output (no regression)

For Part 1, in `service/main.py`'s `_self_check()`:

- auto `max_tokens` scales with input length
- input over the derived cap returns 413, not a truncated 200

## Out of scope

- Retrieval on the fan path. `recall(query)` remains unbuilt; this work makes
  the window last longer, it does not add retrieval.
- The redaction field-consistency defect (keywords line carries the
  unredacted original while the body is fuzzed). Separate bug, separate pass.
- The extrapolation defect quoted above, on the chat path. Also separate.
