# Context budgeting — ingestion reply budget and chat compaction

**Date:** 2026-08-07
**Status:** design, approved
**Touches:** `runtime/bible.py`, `service/main.py`, `runtime/chat_app.py`

Four changes to how the admin and fan surfaces spend their context window.
Parts 1 and 2 are budget defects; Parts 3 and 4 are about *which* context is
worth spending it on.

`assemble()` has exactly three callers — `_prompt_for()`
(`service/main.py:193`), `ingest()` (`service/main.py:382`), and its own
`_self_check()` — so Parts 1 and 2 land in one function rather than in every
caller. Parts 3 and 4 sit in `chat_app`'s session-state handling, which is why
they ride along rather than getting their own pass: they touch the same
plumbing.

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

It has to be a parameter rather than just the first entry in `history`.
`assemble()` trims oldest-first, so a summary placed at the front of history
would be the very first message evicted — the compaction would be undone by
the next turn that needed room. The parameter pins it outside the trimming
loop, and its cost is subtracted from the budget before the loop runs.

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

For Parts 3 and 4, in `runtime/story_tools.py`'s `_self_check()` — the id
parsing is pure text and testable without a model or an embedder:

- `/story ST-001 text` targets `ST-001` and strips the id from the text
- an unknown id is refused by name, never routed as a new story
- no leading id falls through to `route()` unchanged
- a switch is detected only when an *applied* landing differs from the current
  story id

## Part 3 — admin story-scoped context

Part 2 compacts under token pressure, which is the wrong primary trigger for
the admin surface. The dominant admin pattern is the creator dumping a lot of
material about *one* story across many turns, then moving to a different
story. Those two situations want different handling.

| Trigger | Action | Why |
|---|---|---|
| an **applied** `/story` lands on a different story id | drop the prior story's turns from the prompt | it is already written to disk, parsed and indexed — keeping it in context duplicates a file `route()` can reach in one call |
| token pressure **within** one story | Part 2 compaction | not yet persisted, and it is the thread being actively built |

### Switch detection

`route()` already returns the landing: `Routing.story.id` on amend, the newly
allocated `ST-###` on new. No detector to build and no extra embedding call.

The switch is evaluated **only on an applied proposal** — the creator saw the
confirm gate, read the Before/After, and hit Apply. The routing decision is
therefore creator-ratified before it is allowed to move any context.

This matters because `AMENDMENT_THRESHOLD` (0.60) is uncalibrated — it sits
within 0.01 of its decision boundary on the toy cases, and cannot be tuned
until a real corpus exists. An untuned threshold may *propose* a wrong
landing; gating on Apply means it can never *act* on one unobserved. Firing
on declined proposals, or on embedding drift in plain chat, both give this up.

Note that while the corpus is empty every `/story` routes to `new`, so the
switch fires on each one. That is correct behaviour, not a bug — each is
genuinely a different story.

### Display history is not prompt history

`chat_app` currently uses `st.session_state["history"]` as both the visible
transcript and the payload sent to the model. These separate: dropping turns
from the prompt must not blank the creator's screen. The creator keeps
scrolling back through the whole session; only what is *sent* is scoped.

### What survives a switch

One pinned line, roughly 15 tokens:

```
Earlier this session you logged: ST-004, ST-006.
```

Enough that "what have we done so far" gets a true answer instead of a blank
one, without paying to restate material that is on disk and retrievable.

## Part 4 — explicit story id on `/story`

`chat_app.py:404` calls `route(text, ...)` on the whole input with no id
parsing. So `/story ST-001 blabla` embeds the literal `ST-001` as narrative,
matches it lexically as content, and writes it into the story text as if the
creator had typed it as prose.

A leading story id becomes an explicit routing override: `/story ST-001 …`
skips `route()`, targets `ST-001` directly, and strips the id from the text
before ingestion. Unrecognised ids are refused by name rather than silently
falling through to routing — a typo must not become a new story.

This is the manual correction path for a mis-route, which is what makes
Part 3 safe to key off routing at all.

## Recorded for later — fan retrieval shape

Not built here. Recorded so it is not re-litigated when retrieval is specced.

Retrieval searches **flat over event chunks**, then hydrates each hit with its
parent story's summary as a header (`chunk.story_id` is already on every
chunk, so it is a dict lookup).

The rejected alternative is the two-stage shape `route()` uses — summary layer
picks the story, event layer picks the paragraph inside it. That is correct
for *ingestion*, which must make a story-level decision. It is wrong for
retrieval when stories are similar and differ only in small events, which is
the expected shape of lifestyle material: near-identical summaries make the
summary layer the *least* discriminative signal, and stage one commits to a
story on that signal while discarding every other story — throwing away
exactly the detail that distinguishes them.

```
query: "the time the coffee machine broke"

two-stage:  ST-003 "a normal week at home"  0.61
            ST-007 "a quiet week at home"   0.60   <- coin flip
            -> commits to ST-003, searches only inside it
            -> the event is in ST-007, never seen

flat:       ST-007/E-014 "the coffee machine died"  0.88
```

A stories-and-summaries manifest file was also rejected: the markdown and the
index already hold that data, `load_all()` parses every story with no embedder
and no index, and a third copy has nothing keeping it in sync.

## Out of scope

- Retrieval on the fan path. `recall(query)` remains unbuilt; this work makes
  the window last longer, it does not add retrieval. Its shape is recorded
  above; building it is a separate spec, and it wants a real corpus to tune
  against.
- Chunk metadata — carrying `logged` onto `Chunk` (`chunks_of()` drops it
  today, so nothing can filter by period) and giving events their own keywords
  instead of inheriting the story's. Both are small, both are prerequisites
  for retrieval, and both belong with that spec rather than this one.
- The redaction field-consistency defect (keywords line carries the
  unredacted original while the body is fuzzed). Separate bug, separate pass.
- The extrapolation defect quoted above, on the chat path. Also separate.
