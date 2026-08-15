# Merge admin-ui into cookbook-web

## Problem

Two separate Next.js projects exist:

- `cookbook-web/` — `/` is the cookbook setup wizard (`CookbookPage`, talks to
  the cookbook API on :8001), `/fan` is the fan-facing chat page (talks to
  `service` on :8000).
- `web/` (package name `admin-ui`) — the agent-mode admin chat/tools console
  (`ChatPanel`, `ConfirmDialog`, `Sidebar`, `StoryBar`, talks to `service` on
  :8000). Plain CSS, no Tailwind/shadcn. Own vitest suite
  (`agentLoop.test.ts`, `followup.test.ts`).

Two `npm run dev` processes on two ports to check progress on both surfaces
during local development is annoying. Goal: one project, one dev server, easy
to click between the three routes.

## Scope

- Move `web/`'s admin console into `cookbook-web` as a third route, `/admin`.
- No visual restyling of the admin console — move it in as-is, plain CSS
  scoped under `/admin`. Restyling is a separate, later task.
- No runtime gating of `/admin` by `config/stack.json`'s `agent` flag. This is
  a local dev convenience merge, not a deployment-hardening task. Exposure
  control at deploy time stays a separate, later task (matches the project's
  own status notes — "web/, deployment gating" is not yet built regardless of
  this merge).
- Delete `web/` once the move is verified working in `cookbook-web`.

## File moves

All moves are `git mv` (preserve history), then import paths fixed up.

| From (`web/`) | To (`cookbook-web/`) |
|---|---|
| `app/page.tsx` | `app/admin/page.tsx` |
| `app/layout.tsx` (title only) | dropped — root layout already wraps every route; `/admin` gets its title via a per-route `export const metadata` in `app/admin/page.tsx` instead |
| `app/globals.css` | dropped — its entire content is a 3-line `body { margin: 0; font-family: system-ui, sans-serif; }` reset, already superseded by cookbook-web's own Tailwind preflight + globals.css |
| `components/*.tsx` | `components/admin/*.tsx` |
| `hooks/useAgentLoop.ts` | `hooks/useAgentLoop.ts` (cookbook-web's `hooks/` dir is currently empty except `.gitkeep` — no collision) |
| `lib/agentLoop.ts`, `lib/agentLoop.test.ts` | `lib/admin/agentLoop.ts`, `lib/admin/agentLoop.test.ts` |
| `lib/followup.ts`, `lib/followup.test.ts` | `lib/admin/followup.ts`, `lib/admin/followup.test.ts` |
| `lib/toolSchemas.ts` | `lib/admin/toolSchemas.ts` |
| `lib/types.ts` | `lib/admin/types.ts` — **namespaced**: cookbook-web already has an unrelated `lib/types.ts` (cookbook probe/fit types); a flat move would silently overwrite it |
| `lib/api.ts` | `lib/admin/api.ts` — **namespaced**: cookbook-web already has an unrelated `lib/api.ts` (cookbook probe/fit API client) |

Every moved file's internal `@/...` imports get updated to the new paths
(e.g. `@/lib/types` → `@/lib/admin/types`, `@/components/ChatPanel` →
`@/components/admin/ChatPanel`).

## API clients stay separate

`cookbook-web/lib/chatApi.ts` (added when the fan chat widget was wired up —
minimal, just `/chat`) and the ported `cookbook-web/lib/admin/api.ts` (full
surface: `/health`, `/model`, `/model/load`, `/model/unload`, `/chat`,
`/admin/tool`, `/admin/proposal/apply`, `/admin/snapshots*`,
`/admin/story/*`, `/ingest`, `/summarize`) both call `service` on :8000, but
carry different message shapes (`ChatMessage` role `"user"|"bot"` vs.
`Message` with `messageToApi`). Consolidating them into one client is a real
cleanup but out of scope here — not what was asked, and touching the fan
chat path right after wiring it up is unnecessary risk. Noted as a known
duplication, not fixed.

Env var naming: `chatApi.ts` reads `NEXT_PUBLIC_CHAT_API_URL`, ported
`lib/admin/api.ts` reads `NEXT_PUBLIC_SERVICE_URL`. Both default to
`http://127.0.0.1:8000`. Left as-is (two independently-defaulting env vars,
same default) — unifying them touches working code for a naming
preference, no functional benefit.

## Config merge

`cookbook-web/package.json` gains:

- `vitest` as a devDependency (version matches what `web/package.json` used,
  `^2.1.0`, unless that's now behind cookbook-web's other tooling — check at
  implementation time)
- a `"test": "vitest run"` script

No new runtime dependencies — `web/` only used bare `next`/`react`/`react-dom`,
versions cookbook-web already exceeds.

`web/vitest.config.ts` moves to `cookbook-web/vitest.config.ts` unchanged
(`{ test: { environment: "node" } }`).

## Nav

A small link bar in `cookbook-web/app/layout.tsx` (or a `Nav` component it
renders), three links: Cookbook (`/`), Fan (`/fan`), Admin (`/admin`). This is
the actual "switch between them easily" ask — one dev server, one port,
click between routes instead of running two processes on two ports.

## Testing

- `npm run typecheck` (tsc --noEmit) passes across the merged tree.
- `npm test` (vitest) passes — the two ported test files (`agentLoop.test.ts`,
  `followup.test.ts`) run unchanged.
- Manual: `npm run dev` in `cookbook-web`, click through `/`, `/fan`, `/admin`
  — cookbook wizard, fan chat (already verified working against `service`),
  and admin console (model load/chat/tools/story/snapshots against `service`)
  all functional on the one dev server.

## Out of scope (explicitly, per user answers during brainstorming)

- Restyling admin console to Tailwind/shadcn.
- Runtime `/admin` gating by `stack.json`'s `agent` flag.
- Consolidating the two `service`-facing API clients.
- Any change to `service/main.py` or anything under `runtime/`.

## Cleanup

Once the moved tree is verified (typecheck + vitest + manual click-through),
delete `web/` in its entirety (`.next/`, `node_modules/`, `package-lock.json`,
source — everything). Confirm with the user before this delete, since it's a
whole-project removal even though git history preserves it.
