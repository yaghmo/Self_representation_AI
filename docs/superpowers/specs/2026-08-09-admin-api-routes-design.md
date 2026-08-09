# Admin API routes — moving tool execution from Streamlit into FastAPI

**Date:** 2026-08-09
**Status:** design, approved
**Touches:** `service/main.py`
**Part of:** the Streamlit → Next.js migration. Sub-project 1 of 4 (admin routes → Next.js admin UI → Next.js fan site → Docker). This sub-project is backend-only and produces working, curl-testable software on its own — no frontend depends on existing yet for it to be verified.

## Why this exists

`runtime/agent.py`'s docstring states the current security boundary plainly:
"The loop runs client-side. The service passes tools through and returns
tool calls but never executes one, so no deployment can reach `data/` over
HTTP." Concretely, `runtime/chat_app.py` (Streamlit) imports and calls
`run_tool`, `list_backups`, `restore_backup`, `route`, `propose_*`, and now
`save_sample` **directly, in-process** — none of that goes over HTTP today.
`service/main.py` only exposes `/health /model /model/load /model/unload
/chat /chat/stream /ingest /summarize`.

A Next.js client cannot import Python modules, so admin write-capability has
to become reachable over HTTP. This sub-project adds it — gated exactly the
way `_reject_tools` and `ingest` already gate agent-only behavior today (a
per-request `if not model.agent: raise HTTPException(...)` check, not a
route-registration-time decision), relying on the standing design goal "a
deployed instance exposes only the user side" to keep these off any fan
deployment. No new gating mechanism is invented.

**Explicitly out of scope:** the agent loop's orchestration — deciding what
to do with each step, pausing at a proposal for a human decision, resuming
after Apply/Decline. That logic (`runtime/agent.py::run_agent`, `resumed`,
`followup`) stays client-side per design; porting it to the Next.js client
is sub-project 2. This sub-project only has to expose the granular
operations that orchestration will call.

## Design principle: proposals are stateless

A `Proposal` (`runtime/tools.py`) is already just strings: `path, new_text,
summary, diff, before, after, old`. `apply()` already re-reads the file and
compares against `old`, raising `StaleProposal` if it moved — that check
exists specifically so a proposal is safe to treat as a plain, re-verifiable
value rather than a live object. So: no server-side proposal store, no
session concept, no id to leak across tabs or lose on restart. The client
gets the full proposal back as JSON, and to apply it, echoes the whole thing
back. This mirrors how `chat_app.py`'s `confirm_dialog` already behaves —
the "session" holding the pending proposal was always just next to the
call site, never a separate store — it is simply relocated from Streamlit's
`session_state` to being the client's problem to hold and repost.

## New endpoints

All of these live in `service/main.py`, gated `if not model.agent: raise
HTTPException(400, ...)` at the top of the handler — same style as
`_reject_tools`.

### `POST /admin/tool`
Body: `{name: str, arguments: dict}`. Wraps `runtime.tools.run_tool(name,
arguments)` — the exact dispatcher the agent loop already calls for every
tool call, so behavior (unknown tool names, bad arguments, truncation) is
unchanged. Returns `{result: str}` for a read tool, or a serialized
proposal (below) for a write tool.

### `POST /admin/proposal/apply`
Body: the proposal fields the client received from `/admin/tool` or
`/admin/story/propose`, echoed back unmodified: `{path, new_text, summary,
diff, before, after, old}`.

**Security note — this is a new attack surface, not a relocated one.**
Today `Proposal.path` is only ever constructed by trusted server code
(`add_profile_line`, `propose_addition`, etc.) — never from external input,
so `apply()` has never needed to validate it. Once a proposal round-trips
through the client, `path` becomes client-supplied, and `Proposal(**body)`
would otherwise write to whatever string is in it. Before reconstructing
the proposal, this endpoint validates `path` resolves (after `.resolve()`,
so `..` can't escape it) to exactly one of a closed allowlist: `PROFILE_PATH`,
`SOURCES_PATH`, a file directly under `STORIES_DIR` matching the existing
`STORY_NAME` pattern, or `SAMPLE_PATH` (`runtime/voice_sample.py`). Anything
else is a 400, not a write. This is the same shape of check
`restore_backup`'s `_corpus_roots` already does for the same reason (a
closed, hardcoded set beats deriving a directory from untrusted input) —
extended here to cover `apply()`'s destinations rather than restore's.

Once validated: reconstruct `Proposal(**body)` and call `.apply()`. Returns
`{path: str}`, or 409 with the `StaleProposal` message on a race. Decline
needs no endpoint — the client already never calls anything on Decline
today either.

### `GET /admin/snapshots`
Wraps `list_backups()`. Returns the list of backup filenames (relative, not
full paths — nothing about the container's filesystem layout needs to
reach the client).

### `POST /admin/snapshots/restore`
Body: `{name: str}` — one of the names `GET /admin/snapshots` returned.
Wraps `restore_backup()`, which already refuses anything outside the
closed bible/stories pair. Returns `{restored: str}`.

### `POST /admin/story/route`
Body: `{text: str}`. Runs `parse_story_command` then `route()`, using a
module-level lazy-loaded index+embedder — the exact `_get_recall()` pattern
`service/main.py` already has for the fan retrieval path, reused rather
than duplicated (same `_story_index`/`_story_embed` globals, or siblings
built the same way). Returns the routing decision: branch, story id/title
if resolved, event id if amend, runners-up with scores — enough for the
client to render "Adding to ST-003" / "Already logged, 95% similar" the way
`chat_app.py`'s `story_command` block does today.

### `POST /admin/story/propose`
Body: `{branch, story_id, event_id, events: [{title, text}], keywords,
merge}` — the caller has already gone through `/admin/story/route` and
(for existing branches) `POST /ingest` (already exists, unchanged) to get
segmented events. Dispatches to `propose_addition` / `propose_amendment` /
`propose_new_story` by `branch`. Returns a serialized proposal, same shape
as `/admin/tool`'s write-tool response.

### `GET /admin/voice/status`
Wraps `runtime.voice_sample.sample_status()`. Returns `{status: str |
None}`.

### `POST /admin/voice/sample`
Body: raw bytes (`audio/wav`, `Content-Type` set accordingly). Wraps
`save_sample()` — which already validates the `RIFF` header and raises
`ValueError` on non-WAV data; that becomes a 400. Returns `{status: str}`
(the fresh `sample_status()` value).

## Error handling

Every wrapped function already raises a specific exception for its one
real failure mode (`StaleProposal`, `NoChange`, `ValueError` for
not-a-WAV, `ValueError` for a story id that doesn't exist). These map to
HTTP status the same way `_prompt_for`'s existing exception handling
already maps `ProfileMissing`/`ProfileTooLarge`/`MessageTooLarge` to
424/507/413 — a small `except`/`raise HTTPException` per route, not a new
generic error-translation layer.

## Testing

This repo has no pytest; `service/main.py` already carries a `_self_check()`
under `if __name__ == "__main__":` that spins up a `TestClient` and asserts
against it (see the existing agent-mode/non-agent-mode assertions around
lines 680-735). New endpoints get new assertions in that same function,
following the same pattern — not a new test file, not a new framework.
