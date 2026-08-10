# Next.js admin UI — replacing chat_app.py's admin side

**Date:** 2026-08-10
**Status:** design, approved
**Touches:** new `web/` directory (Next.js app), `service/main.py` (CORS only)
**Part of:** the Streamlit → Next.js migration. Sub-project 2 of 4 (admin routes → **Next.js admin UI** → Next.js fan site → Docker). Sub-project 1 (`docs/superpowers/specs/2026-08-09-admin-api-routes-design.md`) added the HTTP surface this sub-project's client drives; it explicitly deferred agent-loop orchestration to here.

## Why this exists

`runtime/chat_app.py` (Streamlit) is the creator's only interface today, and it does more than call HTTP endpoints — it *runs* the agent loop in-process. `runtime/agent.py::run()` calls `run_tool()` directly, not over HTTP; `Proposal.apply()` is called directly too. A Next.js client cannot import either. This sub-project ports that orchestration to TypeScript, calling the admin routes sub-project 1 already built (`/admin/tool`, `/admin/proposal/apply`, `/admin/snapshots`, `/admin/snapshots/restore`, `/admin/story/route`, `/admin/story/propose`) plus the existing `/chat`, `/model`, `/model/load`, `/model/unload`, `/ingest`, `/summarize`.

Streamlit was always the test-phase surface (`chat_app.py`'s own docstring: "Deliberately not the product"). This sub-project supersedes it for the admin/creator surface. `chat_app.py` is left in place until this ships and is verified equivalent, then removed.

## Scope

**In scope**, ported 1:1 from `chat_app.py`:
- Chat turns (persona-driven conversation, `/chat`)
- The agent loop: tool-call dispatch, pause-on-write-proposal, Apply/Decline, resume
- Snapshots sidebar (list + restore)
- Model status / load / unload, generation params (temperature, max_tokens, thinking)
- `/story <text>` command (route → ingest → propose), **text input only**
- Compaction (`plan_compaction` client-side threshold logic → `/summarize`)

**Explicitly out of scope for this sub-project**, each because it depends on backend surface sub-project 1 never built, or has its own real complexity:
- **Chat history persistence.** `data/chats/admin.jsonl` (from `2026-08-08-chat-persistence-design.md`) is read/written by `chat_app.py` importing `runtime/chat_log.py` in-process. No HTTP route wraps it. This sub-project's chat is in-memory only, reset on page reload. Persistence returns in a later pass, as new small HTTP routes wrapping `chat_log.py`.
- **`/story` file upload.** `to_markdown()` (`runtime/convert.py`, handles md/txt/docx/pdf) also only runs in-process. No conversion endpoint exists. `/story` accepts pasted/typed text only.
- **Voice sample recording.** `POST /admin/voice/sample` requires raw WAV bytes (RIFF-header validated). Browser `MediaRecorder` produces WebM/Opus by default; real WAV capture needs Web Audio API PCM work. Deferred rather than either bolting on client-side encoding or loosening the already-merged backend validation.

These three are each small, well-bounded follow-ups once this sub-project's core loop is proven — not blockers to it.

## Architecture

A single Next.js app (App Router, client components only — no server-side data fetching; this is a stateful, interactive tool, not a page that benefits from SSR) under a new top-level `web/` directory. It talks directly to the FastAPI service via `fetch`, filling the same role `httpx` plays in `chat_app.py` today, just from the browser instead of a Python process.

No proxy/BFF layer. One backend change: add `CORSMiddleware` to `service/main.py`, origin restricted to the Next.js dev/serve origin — nothing today issues browser-origin requests to the service, since Streamlit's calls were server-to-server.

This was chosen over a Next.js-as-proxy approach (Route Handlers relaying every call to FastAPI) because it's the smallest diff and matches the existing architecture's thin-client philosophy. A proxy/auth layer can be added later without restructuring this — it would sit in front of an app that still works the same way underneath. Deferred rather than built now because there is no auth requirement yet (single local user, matching every other surface in this repo today) and the whole-branch review's auth finding was about pinning `localhost` before Docker exposure, not about needing auth during local development.

## Components

- **`lib/api.ts`** — thin fetch wrappers, one per endpoint (`getModelStatus`, `loadModel`, `unloadModel`, `postChat`, `postAdminTool`, `postProposalApply`, `getSnapshots`, `postSnapshotRestore`, `postStoryRoute`, `postStoryPropose`, `postIngest`, `postSummarize`). Each throws on non-2xx with the parsed `detail` message attached.
- **`lib/agentLoop.ts`** — the ported `run()` state machine: a TypeScript async generator mirroring `runtime/agent.py::run()` exactly — same iteration cap (`MAX_ITERATIONS = 8`), same `seen` repeat-guard (keyed on `name + sorted-JSON-args`), same tool-call dispatch order, same `Step` shape (`tool_call | tool_result | proposal | answer | stopped`). Where Python called `run_tool()` in-process, this calls `postAdminTool()` over HTTP.
- **`useAgentLoop`** (hook) — owns conversation history, the `seen` map, and drives the generator from React. Exposes `{ steps, pending, send(text), resolveProposal(outcome) }`.
- **`components/ChatPanel.tsx`** — message list + input box. Direct port of the `st.chat_message` render loop and `st.chat_input`.
- **`components/ConfirmDialog.tsx`** — Before/After columns + unified diff + Apply/Decline. Direct port of `confirm_dialog`. Apply calls `postProposalApply`; on success (or on `StaleProposal`'s 409) the outcome message flows into `resolveProposal`, which closes the paused tool call and restarts the generator (mirrors `resumed()` + re-invoking `run`). Decline resolves locally with no HTTP call, same as today.
- **`components/Sidebar.tsx`** — model status/load/unload, generation params, snapshots list + restore. Fetches `/model` + `/health` on mount and after any action that could change them (load, unload, restore). No background polling — matches Streamlit's rerun-on-action model, where status only ever changes in response to a button press on this same page.
- **`components/StoryBar.tsx`** — the `/story <text>` path: parse the command, call `postStoryRoute`, surface the routing decision (branch, story id/title, runners-up), call `postIngest` then the matching `postStoryPropose`, and hand the resulting proposal into the same pending-proposal state `ConfirmDialog` renders from.

## Data flow

- **Normal turn:** user submits text → `useAgentLoop` appends the user message to history → generator calls `/chat` with the scoped history + tool schemas → no `tool_calls` in the reply → yields `answer` → rendered, loop ends for this turn.
- **Tool-call turn:** reply carries `tool_calls` → generator dispatches each via `POST /admin/tool`. A read tool's result is folded back into history and the loop continues (re-calls `/chat`). A write tool yields `proposal` and **stops**, exactly like `run()`'s `return` — `ConfirmDialog` takes over. Apply → `POST /admin/proposal/apply` → success or `StaleProposal` (409) both produce an outcome string → `resolveProposal(outcome)` closes the paused call (same shape as `resumed()`) and the generator restarts from that point. Decline resolves the same way with a decline note and no HTTP call.
- **`/story` turn:** bypasses the agent loop — `postStoryRoute` → (on a resolvable branch) `postIngest` → `postStoryPropose` → same `ConfirmDialog` state as a tool-originated proposal.
- **Model status:** fetched on mount; refetched after Load/Unload/Restore. Nothing polls in the background.

## Error handling

Every `lib/api.ts` wrapper throws on a non-2xx response with the server's `detail` message attached. Callers catch at the point of use and render the message inline — the same granularity `chat_app.py` uses (`st.error(...)` right where the call happens), not a generic error-translation layer. `StaleProposal`'s 409 gets its own message text on Apply, matching today's `except StaleProposal` branch in `confirm_dialog`.

## Testing

This repo has no JS/TS tooling yet — everything today follows Python's `_self_check()` convention (an `assert`-based function under `if __name__ == "__main__":`, no pytest). `lib/agentLoop.ts` is a pure state machine with a direct Python analog that already has extensive coverage: `runtime/agent.py::_self_check()` exercises unknown-tool refusal, malformed-JSON arguments, non-object arguments, the repeat-call nudge, the max-iterations stop, and proposal pause/resume closing the call correctly. Porting those same scenarios 1:1 against a scripted `post` function is the highest-value test coverage available here, and needs a minimal runner: **Vitest** (zero-config, no additional framework surface), scoped to this one file only.

Everything else (the components) is verified by running the app against a loaded model and walking the golden path plus the proposal-pause/resume path by hand — matching this repo's existing norm of not writing a test for every trivial thing.

## Migration

`chat_app.py` is not deleted as part of this sub-project. It stays in place, still fully functional, until the Next.js admin UI is running and verified against the same backend for the in-scope flows above. Removal is a follow-up once that's confirmed working, not a step here.
