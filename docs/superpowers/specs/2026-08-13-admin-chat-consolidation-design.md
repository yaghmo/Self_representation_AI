# Admin chat — consolidate web/ into cookbook-web, GPT-like UI

**Date:** 2026-08-13
**Status:** design, approved
**Touches:** `cookbook-web/` (new admin route + ported logic), `web/` (retired once verified equivalent)
**Supersedes:** `2026-08-10-nextjs-admin-ui-design.md`'s target directory (`web/` → `cookbook-web/`). That spec's scope, architecture, and data-flow decisions (agent loop port, follow-up phase, proposal pause/resume, story-landing context scoping) stand — this document only changes *where* it lives and *what it looks like*.

## Why this exists

`2026-08-10-nextjs-admin-ui-design.md` was built as planned: `web/` (a separate, bare Next.js 15 app — no Tailwind, no shadcn) has a working agent loop, tool-call dispatch, proposal confirm-gate, follow-up phase, snapshots sidebar, and `/story` text ingestion, all committed (`feat(web)`/`fix(web)` history). Independently, `cookbook-web` was built after it — a second Next.js app, shadcn + Tailwind wired in, containing only the launch-time hardware-probe wizard. The two never merged; they share no code today.

The creator wants the admin surface to read as a real product — a GPT-like layout (sidebar + centered chat column + composer) — and `cookbook-web` is where the design system already lives. Rebuilding the design system inside `web/` would duplicate work that already exists one folder over. So: port `web/`'s logic into `cookbook-web`, rebuild the UI there with shadcn, retire `web/` once the port is verified equivalent.

The fan-facing page is explicitly **undecided and out of scope** for this pass — nothing here builds it, stubs it, or reserves a route for it. It's a separate later decision.

## Scope

**Ported, logic unchanged from `web/`:**
- `lib/agentLoop.ts` + its Vitest suite — the agent-loop state machine (tool dispatch, pause-on-proposal, `seen` repeat guard, `MAX_ITERATIONS`).
- `lib/followup.ts` + its Vitest suite — the post-`append_source` follow-up phase.
- `lib/toolSchemas.ts` — `TOOL_SCHEMAS`/`FOLLOWUP_SCHEMAS` (hand-mirrored from `runtime/tools.py`; this pre-existing drift risk is not this pass's problem to fix).
- `lib/api.ts` fetch wrappers and `lib/types.ts` — namespaced under `cookbook-web/lib/chat/` (as `api.ts`, `types.ts`, `agentLoop.ts`, `followup.ts`, `toolSchemas.ts`) rather than merged into `cookbook-web/lib/api.ts` / `lib/types.ts`, which already own the wizard's `Probe`/`Catalogue`/`Fit` types and have no chat-related overlap to resolve — separate concerns, separate files, same convention `CookbookPage.tsx` already established for the wizard.
- `hooks/useAgentLoop.ts` — ported as-is into `cookbook-web/hooks/`.
- All backend behavior: `/chat`, `/admin/tool`, `/admin/proposal/apply`, `/admin/snapshots`, `/admin/snapshots/restore`, `/admin/story/route`, `/admin/story/propose`, `/ingest`, `/summarize`, `/model`, `/model/load`, `/model/unload`, `/health`. No backend changes in this pass.

**Rebuilt, not ported — the UI layer:**
- New route `cookbook-web/app/admin/page.tsx`.
- GPT-like layout: a left sidebar (model status, load/unload, generation params, snapshots — the content of `web/components/Sidebar.tsx`, restyled) and a centered chat column (message thread, composer input, tool-call trace inline in the transcript rather than bare `<pre>` text, the confirm-gate dialog as a shadcn `Dialog`, `/story` entry folded into the composer rather than a separate bar if that reads cleaner — final layout call happens during build, informed by the taste/impeccable design guidance).
- New shadcn primitives get added as the build needs them (e.g. `sidebar`, `scroll-area`, `textarea`, `avatar`) via `npx shadcn add` — not enumerated exhaustively here.

**Explicitly not in this pass:**
- The fan-facing page — undecided, not stubbed.
- Any backend change — this is a frontend consolidation + restyle, not a new capability.
- Auth / admin-fan gating — deferred per your earlier call; whatever toggle or nav exists is unguarded for now.
- Chat history persistence, `/story` file upload, voice recording — already deferred by the spec this supersedes, still deferred.

## Data flow

Unchanged from `2026-08-10-nextjs-admin-ui-design.md`'s Data Flow section: normal turn → `/chat` → answer or tool_calls; tool-call turn → `POST /admin/tool` per call, proposal pauses the loop for `ConfirmDialog`, Apply/Decline resumes; source-entry Apply routes into the follow-up phase; `/story` bypasses the loop via route → ingest → propose. Only the rendering layer changes.

## Testing

Vitest gets added to `cookbook-web` (currently has none) scoped to the ported `lib/chat/agentLoop.ts` and `lib/chat/followup.ts` files, carrying over the existing test suites from `web/` — same rationale as the superseded spec: these are pure state machines with a direct Python analog (`runtime/agent.py::_self_check()`) already proven to catch the failure modes that matter. UI verified by running the dev server and driving the golden path plus the proposal pause/resume path by hand, per this repo's standing norm.

## Migration

`web/` is not deleted in this pass. It stays in place until the ported `cookbook-web/app/admin` route is running and verified equivalent for the in-scope flows above — same staged-retirement pattern the original spec used for `chat_app.py`. Removal is a follow-up once confirmed.
