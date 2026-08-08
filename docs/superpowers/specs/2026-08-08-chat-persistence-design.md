# Chat persistence — resumable history for admin and fan chat

**Date:** 2026-08-08
**Status:** design, approved
**Touches:** `runtime/chat_app.py`, `runtime/chat_log.py` (new), `runtime/model.py`, `config/stack.json`

Today `st.session_state["history"]` is the only place a conversation lives.
Close the tab, restart Streamlit, or the process dies, and the thread is gone
— including any `plan_compaction` summary, which is session-only and was never
written anywhere. This makes both the creator's own testing sessions and a
future fan's conversation stateless across restarts, which is not what either
one wants.

This spec adds one thing: an append-only on-disk log per surface, loaded back
on startup. It does not touch retrieval (`recall(query)` — separate spec,
recorded as out of scope in `2026-08-07-context-budgeting-design.md`) and does
not add multi-visitor session identity — a real fan deployment behind Docker,
with concurrent visitors each needing their own thread, is a later problem.
Today `chat_app.py` runs as one process for one person at a time, whichever
mode (`agent`) the stack is configured for, and this spec covers exactly that.

## Storage

Two files, chosen by the existing `agent_mode` flag
(`status.get("agent")`, `chat_app.py:376`):

```
data/chats/admin.jsonl
data/chats/fan.jsonl
```

Kept separate so an admin session full of tool-call debugging (`/story`,
proposals, applies) never ends up looking like fan-voice testing transcript,
and vice versa. Both live under `data/`, which is gitignored by default per
CLAUDE.md's privacy rule — nothing new needed there.

One JSON object per line, two shapes:

```jsonc
{"role": "user", "content": "...", "tool_calls": null, "tool_call_id": null}
{"type": "summary", "text": "Earlier in this conversation: ..."}
```

The turn shape mirrors `Message`/`ChatMessage` exactly (`role`, `content`,
`tool_calls`, `tool_call_id`) — no translation layer between what's on disk
and what `assemble()` already accepts.

The file is append-only and unbounded. It is the full record; nothing ever
truncates it. Only *loading* is bounded — see below.

## Config: `history_window`

New field in `config/stack.json`, default `20`:

```json
"history_window": 20
```

Flows the same path `bible_strategy` already takes:
`stack.json` → `Model.from_config` (`model.py:61`) → `Model.status()`
(`model.py:196`) → `chat_app.py` reads `status["history_window"]`. No new
plumbing, one more field on an existing dataclass and an existing dict.

This one number governs two things, deliberately not split into separate
knobs:

1. how many messages get rehydrated from disk into `session_state["history"]`
   on startup
2. how many of those get rendered in the chat UI loop (`chat_app.py:371`)

Nothing beyond `history_window` messages ever enters memory, so the fan-side
render-weight question (does showing the whole history get heavy?) is moot by
construction — there is no "whole history" in memory to render. The full log
still exists on disk if a "load more" is ever wanted; not built here.

## Load

In the existing `if "history" not in st.session_state:` block
(`chat_app.py:323`):

1. Pick the file by `agent_mode`.
2. File missing → today's behaviour: empty history, no summary.
3. File present → read it line by line:
   - the **last** `summary` record found seeds `session_state["summary"]`
   - the **last `history_window`** turn records (in file order) seed
     `session_state["history"]`
4. A line that fails to parse is skipped, not fatal. Matches the degrade-
   rather-than-crash stance `index.py:load_index` already takes on a corrupt
   `.npz` — a damaged log must not block the app from starting.

## Save

- Every message appended to `session_state["history"]` (user turn, assistant
  reply, and any tool/tool-result pair in agent mode) is also appended to the
  JSONL file, same shape, immediately — not batched.
- Every time `plan_compaction` produces a new summary and
  `session_state["summary"]` is updated, a fresh `{"type": "summary", ...}`
  line is appended. The load step already takes the *last* one, so old
  summary lines are inert history, not something that needs cleaning up.

## What this deliberately does not handle

- **Tool-call orphaning at the rehydration cut.** If the last-`history_window`
  slice cuts off an assistant's tool call but keeps the tool result after it,
  the result sits in `session_state["history"]` as an orphan. No new guard
  needed: `bible._whole_tool_pairs` already drops exactly this case at
  prompt-build time, regardless of how the orphan got there. Duplicating that
  check at load time would be the same rule written twice.
- **Concurrent writers.** One local process, one chat at a time. No file
  locking.
- **Reload-survival for a real multi-visitor fan deployment.** Needs a durable
  per-visitor session id (URL param, most likely) and Docker to even be a real
  scenario. Explicitly deferred until that deployment work starts.
- **Retrieval.** `recall(query)` and its interaction with the persisted log
  (do retrieved passages ever get written to disk?) is a separate spec.

## Testing

`runtime/chat_log.py` is a new, small module — not inline in `chat_app.py`,
since Streamlit scripts are hard to unit test directly and the read/write
logic needs to be plain functions over a path, exercised the same
`assert`-based way as the rest of the repo. Its own `_self_check()` covers:

- writing a turn then reading it back round-trips byte-for-byte
- the last summary record wins when more than one is present
- only the last `history_window` turns are returned, oldest ones ignored
- a corrupt/truncated line is skipped, not fatal, and does not lose the lines
  around it
- a missing file loads as empty history with no summary, matching current
  behaviour exactly (no regression when the file has never been created)
- admin and fan write to different files under the same `data/chats/` root
