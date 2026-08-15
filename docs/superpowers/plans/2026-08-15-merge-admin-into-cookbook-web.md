# Merge admin-ui into cookbook-web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the separate `web/` (admin-ui) Next.js project into `cookbook-web` as a `/admin` route, so local dev runs one project on one port instead of two, with a nav bar to click between `/` (cookbook wizard), `/fan`, and `/admin`.

**Architecture:** Pure file relocation (`git mv`) plus import-path fixups — no rewritten logic, no restyling, no runtime gating. `web/lib/*` and `web/components/*` land under `cookbook-web/lib/admin/` and `cookbook-web/components/admin/` (namespaced to avoid colliding with cookbook-web's existing unrelated `lib/types.ts` and `lib/api.ts`). `web/hooks/useAgentLoop.ts` lands at `cookbook-web/hooks/useAgentLoop.ts` unchanged (no collision). The two `service`-facing API clients (`lib/chatApi.ts` for fan, `lib/admin/api.ts` for admin) stay separate. `web/` is deleted once the move is verified.

**Tech Stack:** Next.js 16 / React 19 / TypeScript (cookbook-web's existing versions — the moved code only needs bare `next`/`react`, which cookbook-web already exceeds), vitest (newly added to cookbook-web for the two ported test files).

**Spec:** `docs/superpowers/specs/2026-08-15-merge-admin-into-cookbook-web-design.md`

## Global Constraints

- No restyling of the admin console — move its plain CSS/inline-style components in as-is. Restyling is a separate, later task.
- No runtime gating of `/admin` by `config/stack.json`'s `agent` flag — this merge is a local dev convenience only.
- Do not consolidate `lib/chatApi.ts` and the ported `lib/admin/api.ts` — they stay separate clients, both hitting `service` on :8000.
- Do not touch `service/main.py` or anything under `runtime/`.
- Confirm with the user before deleting `web/` in the final task — it's a whole-project removal even though git history preserves it.

---

## Task 1: Add vitest + move `lib/admin/*`

**Files:**
- Modify: `cookbook-web/package.json`
- Create: `cookbook-web/vitest.config.ts`
- Move (git mv): `web/lib/types.ts` → `cookbook-web/lib/admin/types.ts`
- Move (git mv): `web/lib/toolSchemas.ts` → `cookbook-web/lib/admin/toolSchemas.ts`
- Move (git mv): `web/lib/agentLoop.ts` → `cookbook-web/lib/admin/agentLoop.ts`
- Move (git mv): `web/lib/agentLoop.test.ts` → `cookbook-web/lib/admin/agentLoop.test.ts`
- Move (git mv): `web/lib/followup.ts` → `cookbook-web/lib/admin/followup.ts`
- Move (git mv): `web/lib/followup.test.ts` → `cookbook-web/lib/admin/followup.test.ts`
- Move (git mv): `web/lib/api.ts` → `cookbook-web/lib/admin/api.ts`

**Interfaces:**
- Produces: `cookbook-web/lib/admin/types.ts` exports `Message`, `Proposal`, `Step`, `HealthStatus`, `ModelStatus`, `ChatResponse`, `StoryRouteResponse`, `ToolResponse`, `messageToApi` (unchanged from `web/lib/types.ts` — verify exact export list when moving, this list is what Task 2/3/4 import).
- Produces: `cookbook-web/lib/admin/api.ts` exports `ApiError`, `getHealth`, `getModelStatus`, `loadModel`, `unloadModel`, `postChat`, `postAdminTool`, `postProposalApply`, `getSnapshots`, `postSnapshotRestore`, `postStoryRoute`, `postStoryPropose`, `postIngest`, `postSummarize`.
- Produces: `cookbook-web/lib/admin/agentLoop.ts` exports `runAgentLoop`, `resumed`, `ToolOutcome` (type).
- Produces: `cookbook-web/lib/admin/followup.ts` exports `buildFollowup`, `entryIdOf`, `entryFeeds`.
- Produces: `cookbook-web/lib/admin/toolSchemas.ts` exports `TOOL_SCHEMAS`, `FOLLOWUP_SCHEMAS`.

These six files only import each other via relative paths (`./types`, `./toolSchemas`, `./agentLoop`, `./followup`) — moving them together into the same new directory means **none of their internal imports need to change**. Only consumers outside this directory (Tasks 2-4) need import-path fixes.

- [ ] **Step 1: Add vitest to cookbook-web**

Edit `cookbook-web/package.json` — add a `test` script and the `vitest` devDependency:

```diff
   "scripts": {
     "dev": "next dev",
     "build": "next build",
     "start": "next start",
     "lint": "eslint",
     "format": "prettier --write \"**/*.{ts,tsx}\"",
-    "typecheck": "tsc --noEmit"
+    "typecheck": "tsc --noEmit",
+    "test": "vitest run"
   },
```

```diff
   "devDependencies": {
     "@tailwindcss/postcss": "^4.3.3",
     "@types/node": "^20",
     "@types/react": "^19",
     "@types/react-dom": "^19",
     "eslint": "^9",
     "eslint-config-next": "16.2.6",
     "prettier": "^3.8.3",
     "prettier-plugin-tailwindcss": "^0.8.0",
     "tailwindcss": "^4",
-    "typescript": "^5"
+    "typescript": "^5",
+    "vitest": "^2.1.0"
   },
```

- [ ] **Step 2: Create the vitest config**

Create `cookbook-web/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node" },
});
```

(Identical to `web/vitest.config.ts` — the ported test files only use relative imports, no `@/` alias resolution needed.)

- [ ] **Step 3: Install**

Run: `cd cookbook-web && npm install`
Expected: installs cleanly, `vitest` present in `node_modules`.

- [ ] **Step 4: Move the six lib files**

```bash
mkdir -p cookbook-web/lib/admin
git mv web/lib/types.ts cookbook-web/lib/admin/types.ts
git mv web/lib/toolSchemas.ts cookbook-web/lib/admin/toolSchemas.ts
git mv web/lib/agentLoop.ts cookbook-web/lib/admin/agentLoop.ts
git mv web/lib/agentLoop.test.ts cookbook-web/lib/admin/agentLoop.test.ts
git mv web/lib/followup.ts cookbook-web/lib/admin/followup.ts
git mv web/lib/followup.test.ts cookbook-web/lib/admin/followup.test.ts
git mv web/lib/api.ts cookbook-web/lib/admin/api.ts
```

- [ ] **Step 5: Run the ported tests**

Run: `cd cookbook-web && npm test`
Expected: PASS — both `lib/admin/agentLoop.test.ts` and `lib/admin/followup.test.ts` run and pass, unchanged from how they passed in `web/`.

- [ ] **Step 6: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no new errors from `lib/admin/*` (these files only reference each other, all now in place).

- [ ] **Step 7: Commit**

```bash
git add cookbook-web/package.json cookbook-web/package-lock.json cookbook-web/vitest.config.ts cookbook-web/lib/admin
git commit -m "chore: add vitest, move admin lib files into cookbook-web"
```

---

## Task 2: Move `hooks/useAgentLoop.ts`

**Files:**
- Move (git mv): `web/hooks/useAgentLoop.ts` → `cookbook-web/hooks/useAgentLoop.ts`
- Modify: `cookbook-web/hooks/useAgentLoop.ts` (import paths only)

**Interfaces:**
- Consumes: `postAdminTool`, `postChat`, `postProposalApply`, `ApiError` from `cookbook-web/lib/admin/api` (Task 1); `runAgentLoop`, `resumed`, `ToolOutcome` from `cookbook-web/lib/admin/agentLoop` (Task 1); `buildFollowup`, `entryIdOf` from `cookbook-web/lib/admin/followup` (Task 1); `TOOL_SCHEMAS`, `FOLLOWUP_SCHEMAS` from `cookbook-web/lib/admin/toolSchemas` (Task 1); `Message`, `Proposal`, `Step` (types) from `cookbook-web/lib/admin/types` (Task 1).
- Produces: `useAgentLoop(generation: GenerationParams)` hook, exported `GenerationParams` type — consumed by Task 4's `app/admin/page.tsx` and Task 3's `Sidebar.tsx`, both via `@/hooks/useAgentLoop` (path unchanged from `web/`, since this file lands at the same relative location, `hooks/useAgentLoop.ts`).

- [ ] **Step 1: Move the file**

```bash
git mv web/hooks/useAgentLoop.ts cookbook-web/hooks/useAgentLoop.ts
```

(`cookbook-web/hooks/` currently contains only `.gitkeep` — no collision. Remove the placeholder: `git rm cookbook-web/hooks/.gitkeep`.)

- [ ] **Step 2: Fix the four `@/lib/*` imports**

Edit `cookbook-web/hooks/useAgentLoop.ts` lines 4-8:

```diff
-import { postAdminTool, postChat, postProposalApply, ApiError } from "@/lib/api";
-import { runAgentLoop, resumed, type ToolOutcome } from "@/lib/agentLoop";
-import { buildFollowup, entryIdOf } from "@/lib/followup";
-import { TOOL_SCHEMAS, FOLLOWUP_SCHEMAS } from "@/lib/toolSchemas";
-import type { Message, Proposal, Step } from "@/lib/types";
+import { postAdminTool, postChat, postProposalApply, ApiError } from "@/lib/admin/api";
+import { runAgentLoop, resumed, type ToolOutcome } from "@/lib/admin/agentLoop";
+import { buildFollowup, entryIdOf } from "@/lib/admin/followup";
+import { TOOL_SCHEMAS, FOLLOWUP_SCHEMAS } from "@/lib/admin/toolSchemas";
+import type { Message, Proposal, Step } from "@/lib/admin/types";
```

- [ ] **Step 3: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors referencing `hooks/useAgentLoop.ts`.

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/hooks/useAgentLoop.ts cookbook-web/hooks/.gitkeep
git commit -m "chore: move useAgentLoop hook into cookbook-web"
```

---

## Task 3: Move `components/admin/*`

**Files:**
- Move (git mv): `web/components/ChatPanel.tsx` → `cookbook-web/components/admin/ChatPanel.tsx`
- Move (git mv): `web/components/ConfirmDialog.tsx` → `cookbook-web/components/admin/ConfirmDialog.tsx`
- Move (git mv): `web/components/Sidebar.tsx` → `cookbook-web/components/admin/Sidebar.tsx`
- Move (git mv): `web/components/StoryBar.tsx` → `cookbook-web/components/admin/StoryBar.tsx`
- Modify: all four (import paths only)

**Interfaces:**
- Consumes: `Message`, `Step`, `Proposal`, `HealthStatus`, `ModelStatus` (types) from `cookbook-web/lib/admin/types` (Task 1); `getHealth`, `getModelStatus`, `getSnapshots`, `loadModel`, `postSnapshotRestore`, `unloadModel`, `postIngest`, `postStoryPropose`, `postStoryRoute` from `cookbook-web/lib/admin/api` (Task 1); `GenerationParams` (type) from `@/hooks/useAgentLoop` (Task 2, path unchanged).
- Produces: `ChatPanel`, `ConfirmDialog`, `Sidebar`, `StoryBar` components — consumed by Task 4's `app/admin/page.tsx` via `@/components/admin/*`.

- [ ] **Step 1: Move the four files**

```bash
mkdir -p cookbook-web/components/admin
git mv web/components/ChatPanel.tsx cookbook-web/components/admin/ChatPanel.tsx
git mv web/components/ConfirmDialog.tsx cookbook-web/components/admin/ConfirmDialog.tsx
git mv web/components/Sidebar.tsx cookbook-web/components/admin/Sidebar.tsx
git mv web/components/StoryBar.tsx cookbook-web/components/admin/StoryBar.tsx
```

- [ ] **Step 2: Fix imports in `ChatPanel.tsx`**

```diff
-import type { Message, Step } from "@/lib/types";
+import type { Message, Step } from "@/lib/admin/types";
```

- [ ] **Step 3: Fix imports in `ConfirmDialog.tsx`**

```diff
-import type { Proposal } from "@/lib/types";
+import type { Proposal } from "@/lib/admin/types";
```

- [ ] **Step 4: Fix imports in `Sidebar.tsx`**

```diff
-import { getHealth, getModelStatus, getSnapshots, loadModel, postSnapshotRestore, unloadModel } from "@/lib/api";
+import { getHealth, getModelStatus, getSnapshots, loadModel, postSnapshotRestore, unloadModel } from "@/lib/admin/api";
 import type { GenerationParams } from "@/hooks/useAgentLoop";
-import type { HealthStatus, ModelStatus } from "@/lib/types";
+import type { HealthStatus, ModelStatus } from "@/lib/admin/types";
```

(the `@/hooks/useAgentLoop` line is unchanged — leave it as-is.)

- [ ] **Step 5: Fix imports in `StoryBar.tsx`**

```diff
-import { postIngest, postStoryPropose, postStoryRoute } from "@/lib/api";
-import type { Proposal } from "@/lib/types";
+import { postIngest, postStoryPropose, postStoryRoute } from "@/lib/admin/api";
+import type { Proposal } from "@/lib/admin/types";
```

- [ ] **Step 6: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors referencing `components/admin/*`. (These components are not yet imported anywhere, so this only validates the files compile standalone against their own imports — full wiring is verified in Task 4.)

- [ ] **Step 7: Commit**

```bash
git add cookbook-web/components/admin
git commit -m "chore: move admin components into cookbook-web"
```

---

## Task 4: Move `/admin` page + route metadata

**Files:**
- Create: `cookbook-web/app/admin/layout.tsx`
- Move (git mv): `web/app/page.tsx` → `cookbook-web/app/admin/page.tsx`
- Modify: `cookbook-web/app/admin/page.tsx` (import paths only)

**Interfaces:**
- Consumes: `useAgentLoop`, `GenerationParams` from `@/hooks/useAgentLoop` (Task 2); `ChatPanel`, `ConfirmDialog`, `Sidebar`, `StoryBar` from `@/components/admin/*` (Task 3).

`web/app/page.tsx` starts with `"use client"`, and Next.js's App Router does not allow a client component to export `metadata` — that has to come from a server component ancestor. `web/app/layout.tsx`'s only job was setting the page title ("Admin"), so instead of porting a whole second layout, a small server-component `layout.tsx` under `app/admin/` carries just that title; the root layout (fonts, `ThemeProvider`) already wraps it.

- [ ] **Step 1: Create the admin route's layout (title only)**

Create `cookbook-web/app/admin/layout.tsx`:

```tsx
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Admin",
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <>{children}</>
}
```

- [ ] **Step 2: Move the page**

```bash
mkdir -p cookbook-web/app/admin
git mv web/app/page.tsx cookbook-web/app/admin/page.tsx
```

- [ ] **Step 3: Fix the component imports**

Edit `cookbook-web/app/admin/page.tsx` lines 4-8 (the `@/hooks/useAgentLoop` import is unchanged):

```diff
 import { useState } from "react";
 import { useAgentLoop, type GenerationParams } from "@/hooks/useAgentLoop";
-import { ChatPanel } from "@/components/ChatPanel";
-import { ConfirmDialog } from "@/components/ConfirmDialog";
-import { Sidebar } from "@/components/Sidebar";
-import { StoryBar } from "@/components/StoryBar";
+import { ChatPanel } from "@/components/admin/ChatPanel";
+import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
+import { Sidebar } from "@/components/admin/Sidebar";
+import { StoryBar } from "@/components/admin/StoryBar";
```

- [ ] **Step 4: Drop `web/app/globals.css` (not ported)**

Its entire content was a 3-line `body { margin: 0; font-family: system-ui, sans-serif; }` reset, already superseded by `cookbook-web/app/globals.css`'s Tailwind preflight. No action needed — just don't move it; it's deleted along with the rest of `web/` in Task 6.

- [ ] **Step 5: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors referencing `app/admin/page.tsx` or `app/admin/layout.tsx`.

- [ ] **Step 6: Manual verification**

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/admin`.
Expected: page renders (title bar "Admin" in the browser tab, the chat panel / sidebar / story bar layout from `web/`'s original page — same look, since no restyling happened). Functional testing against a live `service` backend is covered by Task 6's manual click-through; this step only confirms the route renders without a build/runtime error.

- [ ] **Step 7: Commit**

```bash
git add cookbook-web/app/admin
git commit -m "chore: move admin page into cookbook-web as /admin route"
```

---

## Task 5: Add nav bar

**Files:**
- Create: `cookbook-web/components/Nav.tsx`
- Modify: `cookbook-web/app/layout.tsx`

**Interfaces:**
- Produces: `Nav` component (client component, no props) — rendered once in the root layout, appears above `{children}` on every route.

- [ ] **Step 1: Create the nav component**

Create `cookbook-web/components/Nav.tsx`:

```tsx
"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"

const LINKS = [
  { href: "/", label: "Cookbook" },
  { href: "/fan", label: "Fan" },
  { href: "/admin", label: "Admin" },
] as const

function Nav() {
  const pathname = usePathname()

  return (
    <nav className="flex items-center gap-4 border-b border-border bg-card px-4 py-2 text-sm">
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={cn(
            "font-medium transition-colors hover:text-foreground",
            pathname === link.href
              ? "text-foreground"
              : "text-muted-foreground"
          )}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  )
}

export { Nav }
```

- [ ] **Step 2: Wire it into the root layout**

Edit `cookbook-web/app/layout.tsx`:

```diff
 import "./globals.css"
 import { ThemeProvider } from "@/components/theme-provider"
+import { Nav } from "@/components/Nav"
 import { Geist, Geist_Mono } from "next/font/google"
```

```diff
       <body>
-        <ThemeProvider>{children}</ThemeProvider>
+        <ThemeProvider>
+          <Nav />
+          {children}
+        </ThemeProvider>
       </body>
```

- [ ] **Step 3: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Manual verification**

Run: `cd cookbook-web && npm run dev`. Visit `/`, `/fan`, `/admin` in the browser.
Expected: the nav bar appears at the top of all three routes, the current route's link is visually distinct (`text-foreground` vs `text-muted-foreground`), clicking each link navigates correctly without a full page reload.

- [ ] **Step 5: Commit**

```bash
git add cookbook-web/components/Nav.tsx cookbook-web/app/layout.tsx
git commit -m "feat: add nav bar to switch between cookbook, fan, and admin routes"
```

---

## Task 6: Delete `web/`

**Files:**
- Delete: `web/` (entire directory)

- [ ] **Step 1: Confirm with the user**

Before running the delete, confirm: "Tasks 1-5 verified — `/`, `/fan`, `/admin` all work from `cookbook-web` on one dev server. OK to delete the now-redundant `web/` directory?" Do not proceed to Step 2 without an explicit yes.

- [ ] **Step 2: Re-run full verification**

Run: `cd cookbook-web && npm run typecheck && npm test`
Expected: both PASS (sanity check before removing the source they were ported from).

- [ ] **Step 3: Delete**

```bash
git rm -r web
```

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove web/ — admin console now lives at cookbook-web/app/admin"
```

- [ ] **Step 5: Final sanity check**

Run: `cd cookbook-web && npm run dev`, click through `/`, `/fan`, `/admin` once more.
Expected: all three routes still work — nothing depended on files outside `cookbook-web/`.
