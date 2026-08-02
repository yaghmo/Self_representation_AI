# Fan-side prompt assembly — design

Date: 2026-07-31
Status: approved, not yet implemented

## Problem

The chat surface works end to end — Streamlit client, FastAPI service, llama.cpp
server, local model on GPU — but the model has never seen the character. The
system prompt is a text box the operator types into, and `chat_app.py` says so in
its own help text: *"The bible is not wired in yet. This is the entire context the
model gets."*

Meanwhile `config/stack.user.json` records `"bible_strategy": "retrieval"`. That
value is written by the cookbook, read by `Model.from_config`, reported by
`status()`, and displayed in the UI sidebar — and consumed by nothing. The config
describes a system that does not exist.

## Decision that shapes everything else

**The audience-facing bot reads `character.md` only. `sources.md` is admin-only.**

`sources.md` holds the creator's unedited answers, question-and-answer, with dates
and tags. Redacted, but still hers. A retrieval hit would surface a whole entry to
a stranger. It stays the evidence layer that the admin agent edits and cites.

The consequence is large and good: the profile body is ~7.8k tokens. At a 16k
context that leaves ~8k for conversation. **The fan side needs no retrieval, no
embedding model, no chunking, and no tool calls.** One file, in context, whole.

This also restores the constraint CLAUDE.md already states for the user surface —
plain LLM chat, no tools, no skills.

## Components

### `runtime/bible.py` (new)

The only new module. Responsibilities:

- **Load** `data/character.md`.
- **Slice** to the bot-facing part: everything from `# CHARACTER` up to
  `## Changelog`. The file's opening sections ("How this file works", canon rules,
  the update loop) and its changelog are instructions to the humans maintaining
  the file, not to the model.
- **Strip cites.** 187 `[S-###]` markers. They are the audit trail and they stay
  in the file; they must not reach a fan. Stripping is done at assembly, never by
  editing the source.
- **Assemble** the system prompt: the sliced profile, plus one short framing line
  telling the model it *is* this character and must answer in voice.

  The behavioural rules are **not** written by this module. `character.md` §10
  "Interaction Rules" and "Hard constraints — what the bot may never do" are the
  creator's, already in the file, and they arrive with the profile. The module adds
  framing, never policy — inventing rules here would be the transcriber authoring
  the character, which the project forbids.
- **Count and budget.** See below.
- **Core sections** — §0 At a Glance, §6 Voice & Speech Patterns, §10 Interaction
  Rules. Exposed now, used only by the growth branch later. Identity, voice, and
  the hard constraints: the parts that may never be dropped, because a bot that
  loses §10 fabricates.

Rejected alternative: assemble inside `service/main.py`. That puts file parsing and
token budgeting in the HTTP layer, and the admin surface needs the same loader.

### `service/main.py` (changed)

`/chat` and `/chat/stream` stop accepting a client-supplied system prompt. The
request body carries the conversation only; the service prepends the assembled
persona.

This is a trust boundary, not a refactor. Today the client sends
`{"role": "system", ...}` from a text box and the service forwards it verbatim, so
any client can replace the persona — including the §10 hard constraints — with one
HTTP request. A deployed fan-facing instance must not allow that.

A debug override remains, gated behind the environment variable
`ALLOW_SYSTEM_PROMPT_OVERRIDE`. Unset — the deployed case — the service rejects any
client-supplied system message. Set, the service accepts one and the Streamlit page
shows its text box. Default-closed: a deployment that forgets to configure anything
is safe, and enabling the override is a deliberate act.

### `cookbook/fit.py` (changed)

`BIBLE_TOKENS = 23_000` is now wrong for the user surface, and it has been making
the fitter buy a 32k context — and therefore a smaller model — to hold something
the fan side never loads.

Replace the constant with a measurement: measure `data/character.md` when it
exists, fall back to a default when it does not, since the repo ships templates and
`data/` may be absent. The admin surface keeps the larger figure, because that
surface does read `sources.md`.

### `config/stack.user.json` (re-cut)

Currently 8192 context. The profile alone nearly fills it. Re-run the cookbook to
write 16k. Not a hand edit — the config's own `_warning` says to re-run rather than
edit by hand, and hand-editing would desync it from the fit that produced it.

## The budget check

Every assembled prompt is counted before it is sent. This is not an optimization;
it is what stops silent truncation. When a prompt exceeds `--ctx-size`,
`llama-server` drops the front — and the front is where the persona rules live. The
bot keeps answering, quietly having lost the rules that stop it fabricating.

Counting uses `llama-server`'s `/tokenize` endpoint: exact, already available, one
HTTP call. The profile is a file, so the count is cached and invalidated on mtime.
When the server is not up (status display before load), fall back to a chars/4
estimate, clearly labelled as an estimate.

Three outcomes:

| Case | Behaviour |
|---|---|
| Profile + reserve fits | Send whole. Today's case at 16k. |
| Profile alone exceeds budget | Refuse at load, loudly, naming both numbers. Never truncate the persona. |
| Profile fits, history has outgrown budget | Drop oldest turns until it fits. Keep the system prompt. |

The third case is not hypothetical: `chat_app.py` sends unbounded history today, so
a 16k context with a 7.8k persona breaks at roughly 30 turns.

## Growth

`character.md` grows sublinearly with `sources.md`. Most new entries attach another
cite to a claim that already exists (~6 tokens); only a genuinely new trait or event
adds a sentence. 74 entries produced 7.8k tokens, but entry 75 does not add 105.

When it does cross the budget, the design does not change — the numbers do. The
second branch is: always-on core (§0, §6, §10) plus retrieved sections from §1–§5
and §7–§9, which are already `###`-delimited, so the chunk boundaries exist in the
file. This is exactly what CLAUDE.md already describes as the fallback, applied to
the profile rather than the whole bible.

That branch is **a marked seam with a real error behind it, not a stub**. Building a
retriever now would mean tuning it against a file that fits in context, which
teaches nothing. When the count crosses, it gets built against a real number.

`/rebuild` is the other pressure valve: a profile bloated with weak single-cite
claims can be regenerated rather than paid for in context.

## Errors

- `data/character.md` missing → clear error naming the path, at load, not at first
  chat.
- Profile exceeds budget → refuse to load, name profile tokens and context budget.
- `/tokenize` unreachable → estimate, label it as an estimate, do not fail.
- Client sends a system message to `/chat` without the debug flag → reject the
  request rather than silently dropping the message, so a misconfigured client is
  visible instead of quietly unpersonated.

## Testing

One runnable check, per the repo's habit — the smallest thing that fails if the
logic breaks:

- Slice and strip: a fixture profile with cites and meta sections in, expected
  prompt out. Asserts no `[S-` survives and no meta section leaks.
- Budget: a profile larger than a small context refuses rather than truncates.
- History trim: oldest turns dropped, system prompt survives.

No framework, no fixtures directory, no per-function suite.

## Out of scope

- Embedding model, chunking, retriever, `details` skill.
- TTS.
- The admin agent loop.
- The six defects found in the audit (layering inversion, `service/` not
  whitelisted in `.gitignore`, dead API path, `probe.scan_installed_repos` reading
  the wrong directory, `Model.status()` raising past its own guard,
  `service/main.py` reaching into `model._backend`) — except where this work sits
  directly on one.
