# Next.js Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `runtime/chat_app.py`'s admin side with a Next.js client that talks to the FastAPI service directly, porting the agent loop, proposal confirm flow, snapshots, and `/story` (text-only) to TypeScript.

**Architecture:** A single Next.js App Router app under `web/`, all client components, fetching `SERVICE_URL` directly from the browser (no proxy layer). The agent loop is a ported async generator (`lib/agentLoop.ts`) driven by a `useAgentLoop` hook, mirroring `runtime/agent.py::run()` exactly. `service/main.py` gets one small addition: CORS middleware.

**Tech Stack:** Next.js (App Router, TypeScript, client components), Vitest (unit tests for `agentLoop.ts`/`followup.ts` only — nothing else in this repo has JS/TS tooling yet). No UI framework, no state library — plain React state/hooks, matching the existing "no framework where a loop suffices" ethos (`runtime/agent.py`'s own docstring).

## Global Constraints

- No proxy/BFF layer — the browser calls `SERVICE_URL` directly (design doc `docs/superpowers/specs/2026-08-10-nextjs-admin-ui-design.md`, Architecture section).
- Chat history persistence, `/story` file upload, and voice recording are **out of scope** — do not add routes or UI for them.
- `chat_app.py` is not deleted or modified by this plan. It stays working until this ships and is verified.
- Every ported piece of logic (agent loop, `followup()`, `entry_id_of`, `entry_feeds`) must match its Python source's behavior exactly — same iteration cap (`MAX_ITERATIONS = 8`), same repeat-guard key shape, same schema names.
- `TOOL_SCHEMAS` / `FOLLOWUP_SCHEMAS` are ported as literal TypeScript constants copied from `runtime/tools.py:666-830` — not fetched from the server (no endpoint serves them).

---

## File Structure

```
web/
  package.json
  tsconfig.json
  next.config.ts
  vitest.config.ts
  app/
    layout.tsx
    page.tsx
    globals.css
  lib/
    types.ts          # shared request/response/domain types
    api.ts             # fetch wrappers, one per service endpoint
    toolSchemas.ts      # TOOL_SCHEMAS / FOLLOWUP_SCHEMAS, ported literally
    agentLoop.ts         # ported run() state machine
    agentLoop.test.ts     # vitest, mirrors agent.py::_self_check()
    followup.ts           # ported followup()/entry_id_of()/entry_feeds()
    followup.test.ts
  hooks/
    useAgentLoop.ts      # owns history/seen/story-scoping, drives agentLoop.ts
  components/
    ChatPanel.tsx
    ConfirmDialog.tsx
    Sidebar.tsx
    StoryBar.tsx

service/main.py           # +CORS middleware only
```

---

### Task 1: Backend — enable CORS for the Next.js client

**Files:**
- Modify: `service/main.py` (near `app = FastAPI(...)`, currently line 197)

**Interfaces:**
- Produces: `service/main.py` accepts cross-origin requests from `http://localhost:3000` (the Next.js dev server's default origin) for every route, so no later task blocks on a browser CORS rejection.

- [ ] **Step 1: Add the CORS middleware**

In `service/main.py`, add the import near the other `fastapi` imports (the file already does `from fastapi import FastAPI, HTTPException, Request` — add alongside it):

```python
from fastapi.middleware.cors import CORSMiddleware
```

Immediately after `app = FastAPI(title="Character chat service", version="0.1.0", lifespan=lifespan)` (line 197), add:

```python
# The Next.js admin UI (sub-project 2) calls this service from the browser,
# not server-to-server like chat_app.py's httpx client did — browsers enforce
# CORS, curl and httpx don't. Restricted to the dev server's own origin; a
# deployed instance's origin is a later, Docker-time decision.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ADMIN_UI_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

- [ ] **Step 2: Verify the service still starts and self-check still passes**

Run: `python -m service.main` (from the repo root, with a Python env that has `fastapi`/`uvicorn`/`httpx` installed — see the admin-api-routes branch's fix-round notes for which conda env has these, e.g. `C:\Users\yaghm\anaconda3\envs\env\python.exe -m service.main`)
Expected: `service self-check: ok ...` (or the no-`data/`-skip variant), no import errors from the new `CORSMiddleware` import.

- [ ] **Step 3: Commit**

```bash
git add service/main.py
git commit -m "feat: enable CORS for the Next.js admin UI origin"
```

---

### Task 2: Next.js scaffold + shared types + API client

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/next.config.ts`, `web/app/layout.tsx`, `web/app/globals.css`
- Create: `web/lib/types.ts`
- Create: `web/lib/api.ts`
- Create: `web/app/page.tsx` (minimal — model/health status only, proves the pipe end-to-end)

**Interfaces:**
- Produces (`lib/types.ts`): `Message`, `ToolCall`, `Step` (kind: `"tool_call" | "tool_result" | "proposal" | "answer" | "stopped"`), `Proposal`, `ModelStatus`, `HealthStatus`.
- Produces (`lib/api.ts`): `getHealth()`, `getModelStatus()`, `loadModel()`, `unloadModel()`, `postChat(body)`, `postAdminTool(name, arguments)`, `postProposalApply(proposal)`, `getSnapshots()`, `postSnapshotRestore(name)`, `postStoryRoute(text)`, `postStoryPropose(body)`, `postIngest(body)`, `postSummarize(body)`. Every wrapper throws `ApiError` (with `.status` and `.detail`) on a non-2xx response.

- [ ] **Step 1: Scaffold the Next.js app**

`web/package.json`:

```json
{
  "name": "admin-ui",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "vitest": "^2.1.0"
  }
}
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "paths": { "@/*": ["./*"] },
    "plugins": [{ "name": "next" }]
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

`web/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {};

export default nextConfig;
```

`web/app/layout.tsx`:

```typescript
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Admin",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

`web/app/globals.css`:

```css
body {
  margin: 0;
  font-family: system-ui, sans-serif;
}
```

- [ ] **Step 2: Install dependencies**

Run: `cd web && npm install`
Expected: exits 0, `node_modules/` created, `package-lock.json` created.

- [ ] **Step 3: Write shared types**

`web/lib/types.ts`:

```typescript
export type Role = "system" | "user" | "assistant" | "tool";

export interface Message {
  role: Role;
  content: string;
  toolCalls?: ToolCall[];
  toolCallId?: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export function messageToApi(m: Message): Record<string, unknown> {
  const out: Record<string, unknown> = { role: m.role, content: m.content };
  if (m.toolCalls) out.tool_calls = m.toolCalls;
  if (m.toolCallId) out.tool_call_id = m.toolCallId;
  return out;
}

export interface Proposal {
  path: string;
  new_text: string;
  summary: string;
  diff: string;
  before: string;
  after: string;
  old: string;
}

export type StepKind = "tool_call" | "tool_result" | "proposal" | "answer" | "stopped";

export interface Step {
  kind: StepKind;
  text: string;
  name: string;
  proposal?: Proposal;
  callId?: string;
  history?: Message[];
}

export interface HealthStatus {
  status: string;
  model_loaded: boolean;
  model: string | null;
}

export interface ModelStatus {
  name?: string;
  agent?: boolean;
  source?: string;
  context_tokens?: number;
  bible_strategy?: string;
  history_window?: number;
  loaded?: boolean;
  detail?: string;
  mode?: string;
  vram_needed?: string;
  vram_available?: string;
  placement_error?: string;
}

export interface ChatResponse {
  content: string;
  reasoning: string;
  tool_calls: { id: string; type: "function"; function: { name: string; arguments: string } }[];
  prompt_tokens: number;
  completion_tokens: number;
}

export interface StoryRouteResponse {
  branch: "new" | "append" | "amend" | "duplicate";
  story_id: string;
  story_title: string;
  event_id: string;
  text: string;
  runners_up: { story_id: string; score: number }[];
}

export interface ToolResponse {
  result: string | null;
  proposal: Proposal | null;
}
```

- [ ] **Step 4: Write the API client**

`web/lib/api.ts`:

```typescript
import type {
  ChatResponse,
  HealthStatus,
  Message,
  ModelStatus,
  Proposal,
  StoryRouteResponse,
  ToolResponse,
} from "./types";
import { messageToApi } from "./types";

const SERVICE_URL = process.env.NEXT_PUBLIC_SERVICE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${SERVICE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthStatus> {
  return request("/health");
}

export function getModelStatus(): Promise<ModelStatus> {
  return request("/model");
}

export function loadModel(port = 8080): Promise<ModelStatus & { status: string }> {
  return request("/model/load", { method: "POST", body: JSON.stringify({ port }) });
}

export function unloadModel(): Promise<{ status: string; model?: string }> {
  return request("/model/unload", { method: "POST" });
}

export interface ChatParams {
  messages: Message[];
  temperature: number;
  maxTokens: number;
  thinking: boolean;
  tools?: Record<string, unknown>[];
  summary?: string;
}

export function postChat(params: ChatParams): Promise<ChatResponse> {
  return request("/chat", {
    method: "POST",
    body: JSON.stringify({
      messages: params.messages.map(messageToApi),
      temperature: params.temperature,
      max_tokens: params.maxTokens,
      thinking: params.thinking,
      tools: params.tools ?? null,
      summary: params.summary ?? "",
    }),
  });
}

export function postAdminTool(name: string, args: Record<string, unknown>): Promise<ToolResponse> {
  return request("/admin/tool", {
    method: "POST",
    body: JSON.stringify({ name, arguments: args }),
  });
}

export function postProposalApply(proposal: Proposal): Promise<{ path: string }> {
  return request("/admin/proposal/apply", {
    method: "POST",
    body: JSON.stringify(proposal),
  });
}

export function getSnapshots(): Promise<{ snapshots: string[] }> {
  return request("/admin/snapshots");
}

export function postSnapshotRestore(name: string): Promise<{ restored: string }> {
  return request("/admin/snapshots/restore", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function postStoryRoute(text: string): Promise<StoryRouteResponse> {
  return request("/admin/story/route", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export interface StoryProposeParams {
  branch: "new" | "append" | "amend";
  storyId?: string;
  eventId?: string;
  text?: string;
  merge?: boolean;
  summary?: string;
  logged?: string;
  keywords?: string[];
  events: { title: string; text: string }[];
}

export function postStoryPropose(params: StoryProposeParams): Promise<ToolResponse> {
  return request("/admin/story/propose", {
    method: "POST",
    body: JSON.stringify({
      branch: params.branch,
      story_id: params.storyId ?? "",
      event_id: params.eventId ?? "",
      text: params.text ?? "",
      merge: params.merge ?? false,
      summary: params.summary ?? "",
      logged: params.logged ?? "",
      keywords: params.keywords ?? [],
      events: params.events,
    }),
  });
}

export interface IngestParams {
  text: string;
  existing?: string;
  merge?: boolean;
}

export function postIngest(params: IngestParams): Promise<{ content: string }> {
  return request("/ingest", {
    method: "POST",
    body: JSON.stringify({
      text: params.text,
      existing: params.existing ?? "",
      merge: params.merge ?? false,
    }),
  });
}

export function postSummarize(messages: Message[], maxTokens = 256): Promise<{ content: string }> {
  return request("/summarize", {
    method: "POST",
    body: JSON.stringify({ messages: messages.map(messageToApi), max_tokens: maxTokens }),
  });
}
```

- [ ] **Step 5: Minimal page proving the pipe works**

`web/app/page.tsx`:

```typescript
"use client";

import { useEffect, useState } from "react";
import { getHealth, getModelStatus } from "@/lib/api";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export default function Page() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e) => setError(String(e)));
    getModelStatus()
      .then(setStatus)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <pre>Backend unreachable: {error}</pre>;

  return (
    <main style={{ padding: 24 }}>
      <h1>Admin</h1>
      <p>health: {health ? JSON.stringify(health) : "loading..."}</p>
      <p>model: {status ? JSON.stringify(status) : "loading..."}</p>
    </main>
  );
}
```

- [ ] **Step 4: Run it against the real service and verify**

Run: `python -m service.main &` (or `uvicorn service.main:app --port 8000`, in the Python env with deps — start it in the background) then `cd web && npm run dev`
Expected: visiting `http://localhost:3000` shows `health: {"status":"ok",...}` and `model: {...}` — no CORS error in the browser console (confirms Task 1's middleware works from an actual browser, not just curl).

- [ ] **Step 5: Commit**

```bash
cd web
git add package.json tsconfig.json next.config.ts app lib
git commit -m "feat: scaffold Next.js admin UI, API client, and status page"
```

---

### Task 3: Port the agent loop (`lib/agentLoop.ts`)

**Files:**
- Create: `web/lib/toolSchemas.ts`
- Create: `web/lib/agentLoop.ts`
- Test: `web/lib/agentLoop.test.ts`
- Create: `web/vitest.config.ts`

**Interfaces:**
- Consumes: `Message`, `Step`, `ToolCall` from `lib/types.ts` (Task 2); `postAdminTool` shape from `lib/api.ts` is *not* called directly here — the caller injects a `dispatch` function so this module has no fetch dependency and is unit-testable without a server (mirrors `runtime/agent.py::run()`'s injected `post` parameter).
- Produces: `runAgentLoop(post, messages, opts)` — an async generator yielding `Step`s. `opts: { maxIterations?: number; tools?: Record<string, unknown>[]; seen?: Map<string, number>; dispatch: (name: string, args: Record<string, unknown>) => Promise<ToolOutcome> }` where `ToolOutcome = { kind: "result"; text: string } | { kind: "proposal"; proposal: Proposal; summary: string }`. Also produces `resumed(step: Step, outcome: string): Message[]`.

- [ ] **Step 1: Vitest config**

`web/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node" },
});
```

- [ ] **Step 2: Port the tool schemas**

`web/lib/toolSchemas.ts` — copied literally from `runtime/tools.py:666-830`:

```typescript
export const TOOL_SCHEMAS: Record<string, unknown>[] = [
  {
    type: "function",
    function: {
      name: "search_sources",
      description:
        "Search the creator's logged answers. Returns whole entries whose text contains every word of the query. Capped — narrow the query rather than asking for more.",
      parameters: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_profile_section",
      description:
        "Read one section of the character profile. Use the heading exactly as listed in the system prompt.",
      parameters: {
        type: "object",
        properties: { heading: { type: "string" } },
        required: ["heading"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "append_source",
      description:
        "Propose appending a new entry to the sources file, verbatim, inside the Source log section. The entry id is assigned automatically. The creator must approve before anything is written.",
      parameters: {
        type: "object",
        properties: {
          answer: { type: "string", description: "The creator's answer, verbatim — do not tidy the phrasing." },
          question: { type: "string", description: "The question as asked, verbatim." },
          entry_type: {
            type: "string",
            description: "One of: direct answer | interview | public post | observed event | existing bio.",
          },
          tags: {
            type: "array",
            items: { type: "string" },
            description: "Short topic tags, e.g. personality, fears.",
          },
          date: {
            type: "string",
            description:
              "YYYY-MM-DD the answer was given, fuzzed per the redaction policy if needed. Use the literal string 'unknown' if the date is not known — today's date is filled in for you. Never guess a date.",
          },
          feeds: {
            type: "array",
            items: { type: "string" },
            description: "Profile sections this entry should feed, e.g. '6. Voice'.",
          },
        },
        required: ["answer", "question", "entry_type", "tags", "date", "feeds"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "add_profile_line",
      description:
        "Propose adding ONE line to a profile section. Read the section first so you do not repeat something already there. The line must carry the cite of the entry it comes from, e.g. '- **Lives in:** Berlin [S-075]'. Everything else in the file stays exactly as it is. The creator must approve.",
      parameters: {
        type: "object",
        properties: {
          heading: { type: "string", description: "Section heading, exactly as listed in the system prompt." },
          line: {
            type: "string",
            description: "The single line to add, including its [S-###] cite. Match the bullet style already used in that section.",
          },
        },
        required: ["heading", "line"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "replace_profile_line",
      description:
        "Propose rewriting ONE existing line in a profile section. Read the section first. `find` must identify exactly one line — if it matches several the call is refused. Keep every [S-###] cite the old line carried; add the new one alongside. The creator must approve.",
      parameters: {
        type: "object",
        properties: {
          heading: { type: "string", description: "Section heading, exactly as listed in the system prompt." },
          find: { type: "string", description: "Distinctive text from the line to replace, e.g. 'Where she's from'." },
          line: { type: "string", description: "The full replacement line, cites included." },
        },
        required: ["heading", "find", "line"],
      },
    },
  },
];

const FOLLOWUP_TOOL_NAMES = new Set(["add_profile_line", "replace_profile_line"]);

export const FOLLOWUP_SCHEMAS: Record<string, unknown>[] = TOOL_SCHEMAS.filter(
  (schema) => FOLLOWUP_TOOL_NAMES.has((schema.function as { name: string }).name)
);
```

- [ ] **Step 3: Write the failing tests first**

`web/lib/agentLoop.test.ts` — ports the first four scenarios from `runtime/agent.py::_self_check()` (lines 296-397 of that file: a tool call then an answer; an unknown tool refused; malformed JSON arguments; the max-iterations stop). The proposal-pause/resume scenario is Step 5 below, added once the basic loop passes:

```typescript
import { describe, expect, it } from "vitest";
import { runAgentLoop } from "./agentLoop";
import type { Message, Step } from "./types";

function call(id: string, name: string, args: string) {
  return { id, type: "function" as const, function: { name, arguments: args } };
}

async function collect(gen: AsyncGenerator<Step>): Promise<Step[]> {
  const out: Step[] = [];
  for await (const step of gen) out.push(step);
  return out;
}

describe("runAgentLoop", () => {
  it("dispatches a tool call, folds the result back, then answers", async () => {
    let calls = 0;
    const post = async (_history: Message[], _tools: Record<string, unknown>[]) => {
      calls += 1;
      if (calls === 1) {
        return { content: "", tool_calls: [call("c1", "search_sources", JSON.stringify({ query: "x" }))] };
      }
      return { content: "done", tool_calls: [] };
    };
    const dispatch = async () => ({ kind: "result" as const, text: "alpha answer" });

    const steps = await collect(runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch }));
    expect(steps.map((s) => s.kind)).toEqual(["tool_call", "tool_result", "answer"]);
    expect(steps[steps.length - 1].text).toBe("done");
    expect(calls).toBe(2);
  });

  it("refuses a tool call outside the offered set", async () => {
    const post = async (history: Message[]) => {
      if (history.length < 3) return { content: "", tool_calls: [call("c1", "nope", "{}")] };
      return { content: "recovered", tool_calls: [] };
    };
    const dispatch = async () => ({ kind: "result" as const, text: "should not be called" });

    const steps = await collect(runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch }));
    expect(steps[1].text).toContain("not available for this task");
    expect(steps[1].text).toContain("search_sources");
    expect(steps[steps.length - 1].text).toBe("recovered");
  });

  it("reports malformed JSON arguments as a tool result, not a crash", async () => {
    const post = async (history: Message[]) => {
      if (history.length < 3) return { content: "", tool_calls: [call("c1", "search_sources", "{not json")] };
      return { content: "ok", tool_calls: [] };
    };
    const dispatch = async () => ({ kind: "result" as const, text: "unreached" });

    const steps = await collect(runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch }));
    expect(steps[1].text).toContain("could not parse");
  });

  it("stops after max_iterations without an answer", async () => {
    const post = async () => ({ content: "", tool_calls: [call("c1", "search_sources", "{}")] });
    const dispatch = async () => ({ kind: "result" as const, text: "x" });

    const steps = await collect(
      runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch, maxIterations: 3 })
    );
    expect(steps[steps.length - 1].kind).toBe("stopped");
    expect(steps[steps.length - 1].text).toContain("3");
  });

  it("nudges instead of re-answering a repeated identical call", async () => {
    let calls = 0;
    const post = async () => {
      calls += 1;
      if (calls < 3) return { content: "", tool_calls: [call(`c${calls}`, "search_sources", JSON.stringify({ query: "alpha" }))] };
      return { content: "moved on", tool_calls: [] };
    };
    const dispatch = async () => ({ kind: "result" as const, text: "alpha answer" });

    const steps = await collect(runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch }));
    const results = steps.filter((s) => s.kind === "tool_result").map((s) => s.text);
    expect(results[0]).toContain("alpha answer");
    expect(results[1]).toContain("already called");
    expect(steps[steps.length - 1].text).toBe("moved on");
  });
});
```

- [ ] **Step 4: Run the tests and confirm they fail with "not defined"**

Run: `cd web && npm run test`
Expected: FAIL — `agentLoop.ts` does not exist yet, or `runAgentLoop` is not exported.

- [ ] **Step 5: Add the proposal pause/resume test**

Append to `web/lib/agentLoop.test.ts` (this mirrors `_self_check()` lines 400-439 of `runtime/agent.py` — the pause-and-resume contract):

```typescript
import { resumed } from "./agentLoop";

describe("proposal pause and resume", () => {
  it("stops the loop on a write tool and resumes cleanly after Apply", async () => {
    const post = async () => ({
      content: "",
      tool_calls: [
        call(
          "c1",
          "append_source",
          JSON.stringify({ answer: "a", question: "q", entry_type: "direct answer", tags: [], date: "unknown", feeds: [] })
        ),
      ],
    });
    const proposal = { path: "sources.md", new_text: "x", summary: "log S-075", diff: "d", before: "", after: "x", old: "" };
    const dispatch = async () => ({ kind: "proposal" as const, proposal, summary: "log S-075" });

    const gen = runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch });
    const first = await gen.next();
    expect(first.value?.kind).toBe("tool_call");
    const second = await gen.next();
    expect(second.value?.kind).toBe("proposal");
    expect(second.value?.callId).toBe("c1");

    const continued = resumed(second.value as Step, "applied");
    expect(continued[continued.length - 1]).toEqual({ role: "tool", content: "applied", toolCallId: "c1" });
    const assistantTurn = continued.filter((m) => m.role === "assistant").pop();
    expect(assistantTurn?.toolCalls?.length).toBe(1);

    const postAfter = async (history: Message[]) => {
      expect(history[history.length - 1].role).toBe("tool");
      return { content: "logged", tool_calls: [] };
    };
    const afterSteps = await collect(runAgentLoop(postAfter, continued, { dispatch }));
    expect(afterSteps.map((s) => s.kind)).toEqual(["answer"]);
  });
});
```

- [ ] **Step 6: Implement `lib/agentLoop.ts`**

Direct TypeScript port of `runtime/agent.py::run()` (lines 155-287) and `resumed()` (lines 143-152):

```typescript
import type { Message, Proposal, Step } from "./types";
import { TOOL_SCHEMAS } from "./toolSchemas";

export const MAX_ITERATIONS = 8;

export type ToolOutcome =
  | { kind: "result"; text: string }
  | { kind: "proposal"; proposal: Proposal; summary: string };

export type PostTurn = (
  history: Message[],
  tools: Record<string, unknown>[]
) => Promise<{ content: string; tool_calls: { id: string; type: "function"; function: { name: string; arguments: string } }[] }>;

export interface RunOptions {
  dispatch: (name: string, args: Record<string, unknown>) => Promise<ToolOutcome>;
  maxIterations?: number;
  tools?: Record<string, unknown>[];
  seen?: Map<string, number>;
}

function resultMessage(callId: string, text: string): Message {
  return { role: "tool", content: text, toolCallId: callId };
}

export async function* runAgentLoop(
  post: PostTurn,
  messages: Message[],
  options: RunOptions
): AsyncGenerator<Step> {
  const tools = options.tools ?? TOOL_SCHEMAS;
  const maxIterations = options.maxIterations ?? MAX_ITERATIONS;
  const seen = options.seen ?? new Map<string, number>();
  const allowed = new Set(
    tools.map((schema) => (schema.function as { name: string }).name)
  );

  const history = [...messages];

  for (let iteration = 0; iteration < maxIterations; iteration++) {
    const reply = await post(history, tools);
    const toolCalls = reply.tool_calls ?? [];

    if (toolCalls.length === 0) {
      yield { kind: "answer", text: reply.content ?? "", name: "" };
      return;
    }

    history.push({ role: "assistant", content: reply.content ?? "", toolCalls });

    for (const call of toolCalls) {
      const name = call.function?.name ?? "";
      const callId = call.id ?? "";
      yield { kind: "tool_call", text: call.function?.arguments ?? "", name };

      const raw = call.function?.arguments || "{}";
      let args: unknown;
      try {
        args = JSON.parse(raw);
      } catch (exc) {
        const text = `could not parse the arguments to ${name}: ${exc}`;
        history.push(resultMessage(callId, text));
        yield { kind: "tool_result", text, name };
        continue;
      }

      if (typeof args !== "object" || args === null || Array.isArray(args)) {
        const text = `the arguments to ${name} must be a JSON object, got ${typeof args}`;
        history.push(resultMessage(callId, text));
        yield { kind: "tool_result", text, name };
        continue;
      }

      if (!allowed.has(name)) {
        const refusal = `${name} is not available for this task. You have: ${[...allowed].sort().join(", ")}.`;
        history.push(resultMessage(callId, refusal));
        yield { kind: "tool_result", text: refusal, name };
        continue;
      }

      const signature = `${name}:${JSON.stringify(args, Object.keys(args as object).sort())}`;
      const count = (seen.get(signature) ?? 0) + 1;
      seen.set(signature, count);
      if (count > 1) {
        const repeat = `you already called ${name} with these arguments earlier in this conversation — the answer has not changed. Use what it returned and take the next step, or write the edit.`;
        history.push(resultMessage(callId, repeat));
        yield { kind: "tool_result", text: repeat, name };
        continue;
      }

      const outcome = await options.dispatch(name, args as Record<string, unknown>);

      if (outcome.kind === "proposal") {
        yield {
          kind: "proposal",
          name,
          proposal: outcome.proposal,
          text: outcome.summary,
          callId,
          history: [...history],
        };
        return;
      }

      history.push(resultMessage(callId, outcome.text));
      yield { kind: "tool_result", text: outcome.text, name };
    }
  }

  yield {
    kind: "stopped",
    text: `stopped after ${maxIterations} turns without an answer — the model kept calling tools. Say what you want in fewer steps, or check the tool results above for one it is misreading.`,
    name: "",
  };
}

export function resumed(step: Step, outcome: string): Message[] {
  if (!step.history) {
    throw new Error("only a proposal step can be resumed");
  }
  return [...step.history, resultMessage(step.callId ?? "", outcome)];
}
```

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `cd web && npm run test`
Expected: PASS — all six `describe`/`it` blocks green.

- [ ] **Step 8: Commit**

```bash
cd web
git add lib/toolSchemas.ts lib/agentLoop.ts lib/agentLoop.test.ts vitest.config.ts package.json
git commit -m "feat: port the agent loop state machine to TypeScript"
```

---

### Task 4: Port the follow-up phase (`lib/followup.ts`)

**Files:**
- Create: `web/lib/followup.ts`
- Test: `web/lib/followup.test.ts`

**Interfaces:**
- Consumes: `Message` from `lib/types.ts`.
- Produces: `entryIdOf(entry: string): string`, `entryFeeds(entry: string): string[]`, `buildFollowup(entry: string, readSection: (heading: string) => Promise<string>): Promise<Message[]>`.

- [ ] **Step 1: Write the failing tests**

`web/lib/followup.test.ts` — ports `runtime/agent.py::_self_check()` lines 475-510 (the `followup()` scenarios) plus `entry_id_of`/`entry_feeds`'s own behavior from `runtime/tools.py:616-633`:

```typescript
import { describe, expect, it } from "vitest";
import { buildFollowup, entryFeeds, entryIdOf } from "./followup";

const ENTRY = [
  "### S-042",
  "- **Date:** 2026-01-09",
  "- **Q:** placeholder question",
  "- **A:** placeholder answer",
  "- **Feeds:** 0. At a Glance, 6. Voice",
].join("\n");

describe("entryIdOf", () => {
  it("extracts the S-### an entry declares", () => {
    expect(entryIdOf(ENTRY)).toBe("S-042");
  });
  it("returns empty string when there is no entry heading", () => {
    expect(entryIdOf("no heading here")).toBe("");
  });
});

describe("entryFeeds", () => {
  it("parses the comma-separated Feeds line", () => {
    expect(entryFeeds(ENTRY)).toEqual(["0. At a Glance", "6. Voice"]);
  });
  it("returns an empty list for an em-dash Feeds line", () => {
    expect(entryFeeds("### S-043\n- **Feeds:** —\n")).toEqual([]);
  });
});

describe("buildFollowup", () => {
  it("reads each fed section once and includes the entry and current content", async () => {
    const asked: string[] = [];
    const readSection = async (heading: string) => {
      asked.push(heading);
      return `## ${heading}\n- existing line [S-001]\n`;
    };

    const task = await buildFollowup(ENTRY, readSection);
    expect(asked).toEqual(["0. At a Glance", "6. Voice"]);
    expect(task.length).toBe(1);
    expect(task[0].role).toBe("user");
    expect(task[0].content).toContain("S-042");
    expect(task[0].content).toContain("placeholder answer");
    expect(task[0].content).toContain("existing line [S-001]");
    expect(task[0].content).toContain("at a time");
  });

  it("says there is nothing to add when Feeds names no sections", async () => {
    const task = await buildFollowup("### S-043\n- **Feeds:** —\n", async () => "");
    expect(task[0].content).toContain("nothing to add");
  });

  it("reports a section that fails to read instead of throwing", async () => {
    const readSection = async (heading: string) => {
      throw new Error(`no section ${heading}`);
    };
    const task = await buildFollowup(ENTRY, readSection);
    expect(task[0].content).toContain("could not read this section");
  });
});
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd web && npm run test`
Expected: FAIL — `followup.ts` doesn't exist.

- [ ] **Step 3: Implement `lib/followup.ts`**

Ports `entry_id_of`/`entry_feeds` (`runtime/tools.py:616-633`) and `followup()` (`runtime/agent.py:86-140`), dropping the `_elsewhere()` hint per the design doc's Scope section (it depends on `bible.py::section_index()`, which has no HTTP-reachable equivalent):

```typescript
import type { Message } from "./types";

const ENTRY = /^### (S-\d+)/m;

export function entryIdOf(entry: string): string {
  const match = ENTRY.exec(entry);
  return match ? match[1] : "";
}

export function entryFeeds(entry: string): string[] {
  for (const line of entry.split("\n")) {
    const stripped = line.trim().replace(/^-+/, "").trim();
    if (stripped.toLowerCase().startsWith("**feeds:**")) {
      const listed = stripped.split("**").slice(2).join("**").trim();
      return listed
        .split(",")
        .map((part) => part.trim())
        .filter((part) => part && part !== "—");
    }
  }
  return [];
}

export async function buildFollowup(
  entry: string,
  readSection: (heading: string) => Promise<string>
): Promise<Message[]> {
  const entryId = entryIdOf(entry) || "the entry above";
  const sections = entryFeeds(entry);

  if (sections.length === 0) {
    return [
      {
        role: "user",
        content: `${entry}\n\nThis entry names no sections in its Feeds line, so there is nothing to add to the profile. Say so and stop.`,
      },
    ];
  }

  const current: string[] = [];
  for (const name of sections) {
    try {
      current.push(await readSection(name));
    } catch (exc) {
      current.push(`## ${name}\n[could not read this section: ${exc}]`);
    }
  }
  const joined = current.join("\n\n");

  const content =
    `This entry was just logged:\n\n${entry}\n\n` +
    `It feeds ${sections.length} section(s): ${sections.join(", ")}.\n` +
    `Here they are as they stand:\n\n${joined}\n\n` +
    `Record what ${entryId} says in each of those sections, one call at a time. The sections are above — you have everything you need, so do not go looking for more.\n\n` +
    `If the section already has a line for this field — an Age row, a Nationality row, a **Family:** bullet — use \`replace_profile_line\` on that line, keeping every cite it already carries and adding ${entryId}. Use \`add_profile_line\` only for a field that is not there at all. Never copy a line that is already in the section: leave the ones this entry does not change exactly as they are.\n\n` +
    `Every line you write carries ${entryId}. Match the shape already used — a row where there is a table, a bullet where there are bullets. One fact goes in one line: do not file the same thing again under a second label.\n\n` +
    `When the sections are done, say what you changed and stop.`;

  return [{ role: "user", content }];
}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd web && npm run test`
Expected: PASS — all `describe` blocks green.

- [ ] **Step 5: Commit**

```bash
cd web
git add lib/followup.ts lib/followup.test.ts
git commit -m "feat: port the follow-up phase (entry_id_of, entry_feeds, followup)"
```

---

### Task 5: `useAgentLoop` hook

**Files:**
- Create: `web/hooks/useAgentLoop.ts`

**Interfaces:**
- Consumes: `runAgentLoop`, `resumed`, `ToolOutcome` from `lib/agentLoop.ts` (Task 3); `buildFollowup`, `entryIdOf` from `lib/followup.ts` (Task 4); `postChat`, `postAdminTool`, `postProposalApply` from `lib/api.ts` (Task 2); `TOOL_SCHEMAS`, `FOLLOWUP_SCHEMAS` from `lib/toolSchemas.ts`.
- Produces: `useAgentLoop(genParams: { temperature: number; maxTokens: number; thinking: boolean }) => { transcript: Message[]; steps: Step[]; pending: Proposal | null; currentStory: string | null; send: (text: string) => Promise<void>; applyPending: () => Promise<void>; declinePending: () => void; reset: () => void }`. `transcript` is the persisted user/assistant turns for the scrollback (mirrors `chat_app.py`'s `session_state["history"]`, rendered by `st.chat_message` at lines 438-441); `steps` is only the *current* turn's live trace (tool_call/tool_result/proposal/stopped — reset at the start of every `drive()` call), matching how `chat_app.py`'s per-`Step` rendering (lines 782-797) only ever shows what one script run just produced, never a growing log across turns.

- [ ] **Step 1: Implement the hook**

`web/hooks/useAgentLoop.ts` — ports `chat_app.py`'s agent-mode branch (lines 726-802) plus `confirm_dialog`'s Apply path (lines 150-203) and the story-landing scoping rule from the design doc:

```typescript
"use client";

import { useCallback, useRef, useState } from "react";
import { postAdminTool, postChat, postProposalApply, ApiError } from "@/lib/api";
import { runAgentLoop, resumed, type ToolOutcome } from "@/lib/agentLoop";
import { buildFollowup, entryIdOf } from "@/lib/followup";
import { TOOL_SCHEMAS, FOLLOWUP_SCHEMAS } from "@/lib/toolSchemas";
import type { Message, Proposal, Step } from "@/lib/types";

export interface GenerationParams {
  temperature: number;
  maxTokens: number;
  thinking: boolean;
}

interface PendingState {
  proposal: Proposal;
  step: Step | null; // null for a /story-originated proposal — nothing paused to close
}

export function useAgentLoop(params: GenerationParams) {
  // The persisted transcript (user + assistant turns) the UI renders as
  // chat bubbles — mirrors `session_state["history"]`. Separate from
  // `steps`, which is only the current turn's live tool-call trace.
  const [transcript, setTranscript] = useState<Message[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [pending, setPending] = useState<PendingState | null>(null);
  const [currentStory, setCurrentStory] = useState<string | null>(null);
  const historyRef = useRef<Message[]>([]);
  const seenRef = useRef(new Map<string, number>());

  const dispatch = useCallback(async (name: string, args: Record<string, unknown>): Promise<ToolOutcome> => {
    const response = await postAdminTool(name, args);
    if (response.proposal) {
      return { kind: "proposal", proposal: response.proposal, summary: response.proposal.summary };
    }
    return { kind: "result", text: response.result ?? "" };
  }, []);

  const drive = useCallback(
    async (history: Message[], tools: Record<string, unknown>[]) => {
      setSteps([]); // a fresh turn starts with an empty trace
      const post = async (turnHistory: Message[], turnTools: Record<string, unknown>[]) =>
        postChat({
          messages: turnHistory,
          temperature: params.temperature,
          maxTokens: params.maxTokens,
          thinking: params.thinking,
          tools: turnTools,
        });

      for await (const step of runAgentLoop(post, history, { dispatch, tools, seen: seenRef.current })) {
        setSteps((prev) => [...prev, step]);
        if (step.kind === "proposal") {
          setPending({ proposal: step.proposal as Proposal, step });
        }
        if (step.kind === "answer") {
          const assistantMessage: Message = { role: "assistant", content: step.text };
          historyRef.current = [...history, assistantMessage];
          setTranscript((prev) => [...prev, assistantMessage]);
        }
      }
    },
    [dispatch, params.maxTokens, params.temperature, params.thinking]
  );

  const send = useCallback(
    async (text: string) => {
      const userMessage: Message = { role: "user", content: text };
      const nextHistory = [...historyRef.current, userMessage];
      historyRef.current = nextHistory;
      setTranscript((prev) => [...prev, userMessage]);
      await drive(nextHistory, TOOL_SCHEMAS);
    },
    [drive]
  );

  const resolveProposal = useCallback(
    async (outcome: string, appliedPath?: string) => {
      const current = pending;
      setPending(null);
      if (!current) return;

      // Story-landing scoping: a proposal that landed under stories/ resets
      // what gets resent on later turns, per the design doc's Data flow.
      if (appliedPath && /[/\\]stories[/\\][^/\\]+\.md$/.test(appliedPath)) {
        const landed = appliedPath.replace(/\.md$/, "").split(/[/\\]/).pop() ?? null;
        if (landed && landed !== currentStory) {
          setCurrentStory(landed);
        }
      }

      // A /story-originated proposal has no paused tool call to close.
      if (!current.step) return;

      let continuedHistory = resumed(current.step, outcome);

      // Follow-up phase: an applied sources.md proposal carrying an entry id
      // starts a fresh bounded conversation instead of a plain resume.
      const isSourceEntry = appliedPath?.endsWith("sources.md") && entryIdOf(current.proposal.after);
      if (isSourceEntry) {
        const entryText = current.proposal.after;
        const task = await buildFollowup(entryText, async (heading) => {
          const result = await postAdminTool("read_profile_section", { heading });
          return result.result ?? "";
        });
        historyRef.current = task;
        await drive(task, FOLLOWUP_SCHEMAS);
        return;
      }

      historyRef.current = continuedHistory;
      await drive(continuedHistory, TOOL_SCHEMAS);
    },
    [currentStory, drive, pending]
  );

  const applyPending = useCallback(async () => {
    if (!pending) return;
    try {
      const result = await postProposalApply(pending.proposal);
      await resolveProposal(`applied — ${pending.proposal.summary}. This write is done; do not repeat it.`, result.path);
    } catch (exc) {
      const message = exc instanceof ApiError ? exc.detail : String(exc);
      await resolveProposal(`not applied — ${message}`);
    }
  }, [pending, resolveProposal]);

  const declinePending = useCallback(() => {
    if (!pending) return;
    void resolveProposal(`declined by the creator — ${pending.proposal.summary}. Do not retry it.`);
  }, [pending, resolveProposal]);

  const reset = useCallback(() => {
    setTranscript([]);
    setSteps([]);
    setPending(null);
    setCurrentStory(null);
    historyRef.current = [];
    seenRef.current = new Map();
  }, []);

  return {
    transcript,
    steps,
    pending: pending?.proposal ?? null,
    currentStory,
    send,
    applyPending,
    declinePending,
    reset,
  };
}
```

- [ ] **Step 2: Type-check the hook**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd web
git add hooks/useAgentLoop.ts
git commit -m "feat: add useAgentLoop hook wiring the loop, follow-up phase, and story scoping"
```

---

### Task 6: Chat panel

**Files:**
- Create: `web/components/ChatPanel.tsx`
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes: `useAgentLoop`'s `transcript` and `steps` (Task 5).
- Produces: a working chat UI — this is the first task where a human can type a message and see the model answer.

- [ ] **Step 1: Implement `ChatPanel`**

`web/components/ChatPanel.tsx` — renders `transcript` as chat bubbles, mirroring `chat_app.py`'s message loop (lines 438-441), and `steps` as the current turn's live trace below it, mirroring the per-`Step`-kind rendering inside the agent-mode branch (lines 782-797). A `stepped` `"answer"` is never rendered a second time here — it already landed in `transcript` via the hook, and `steps` is cleared at the start of the next turn regardless:

```typescript
"use client";

import { useState } from "react";
import type { Message, Step } from "@/lib/types";

export function ChatPanel({
  transcript,
  steps,
  onSend,
}: {
  transcript: Message[];
  steps: Step[];
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");

  function submit() {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onSend(text);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {transcript.map((message, i) => (
          <div key={i}>
            <strong>{message.role}: </strong>
            {message.content}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {steps
          .filter((step) => step.kind !== "answer")
          .map((step, i) => (
            <StepView key={i} step={step} />
          ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Say something, or /story to log one"
          style={{ flex: 1 }}
        />
        <button onClick={submit}>Send</button>
      </div>
    </div>
  );
}

function StepView({ step }: { step: Step }) {
  switch (step.kind) {
    case "tool_call":
      return <div style={{ color: "#666" }}>{step.name}({step.text})</div>;
    case "tool_result":
      return (
        <details>
          <summary>{step.name} result</summary>
          <pre>{step.text}</pre>
        </details>
      );
    case "proposal":
      return <div style={{ color: "#a60" }}>{step.text}</div>;
    case "stopped":
      return <div style={{ color: "red" }}>{step.text}</div>;
    default:
      return null;
  }
}
```

- [ ] **Step 2: Wire it into the page**

Modify `web/app/page.tsx` to add the chat panel below the existing status text:

```typescript
"use client";

import { useEffect, useState } from "react";
import { getHealth, getModelStatus } from "@/lib/api";
import { useAgentLoop } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/ChatPanel";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export default function Page() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loop = useAgentLoop({ temperature: 0.7, maxTokens: 512, thinking: false });

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e)));
    getModelStatus().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  if (error) return <pre>Backend unreachable: {error}</pre>;

  return (
    <main style={{ padding: 24, maxWidth: 800 }}>
      <h1>Admin</h1>
      <p>health: {health ? JSON.stringify(health) : "loading..."}</p>
      <p>model: {status ? JSON.stringify(status) : "loading..."}</p>
      <ChatPanel transcript={loop.transcript} steps={loop.steps} onSend={loop.send} />
    </main>
  );
}
```

- [ ] **Step 3: Manually verify against a loaded model**

Run: `service` running with a model loaded (agent mode, per `config/stack.json`), `cd web && npm run dev`, visit `http://localhost:3000`.
Expected: typing a plain question and pressing Enter/Send shows an `answer` step with the model's reply. This exercises the whole path: `ChatPanel` → `useAgentLoop.send` → `runAgentLoop` → `postChat` → real service → real model.

- [ ] **Step 4: Commit**

```bash
cd web
git add components/ChatPanel.tsx app/page.tsx
git commit -m "feat: add ChatPanel, wire plain chat turns end to end"
```

---

### Task 7: Proposal confirm dialog

**Files:**
- Create: `web/components/ConfirmDialog.tsx`
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes: `useAgentLoop`'s `pending`, `applyPending`, `declinePending` (Task 5).
- Produces: a working Apply/Decline flow — the second manually-verified milestone (a tool call that writes something can be approved or rejected).

- [ ] **Step 1: Implement `ConfirmDialog`**

`web/components/ConfirmDialog.tsx` — direct port of `confirm_dialog` (`chat_app.py:108-208`), minus the story-index-refresh and voice-specific pieces that live server-side now:

```typescript
"use client";

import type { Proposal } from "@/lib/types";

export function ConfirmDialog({
  proposal,
  onApply,
  onDecline,
}: {
  proposal: Proposal;
  onApply: () => void;
  onDecline: () => void;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div style={{ background: "white", padding: 24, maxWidth: 900, width: "90%", maxHeight: "80vh", overflow: "auto" }}>
        <h2>Confirm this change</h2>
        <p>{proposal.summary} — nothing has been written yet.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <strong>Before</strong>
            <pre>{proposal.before || "new — nothing is being replaced"}</pre>
          </div>
          <div>
            <strong>After</strong>
            <pre>{proposal.after}</pre>
          </div>
        </div>
        <details>
          <summary>Unified diff</summary>
          <pre>{proposal.diff}</pre>
        </details>
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button onClick={onApply}>Apply</button>
          <button onClick={onDecline}>Decline</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into the page**

Modify `web/app/page.tsx` — add the dialog, rendered when `loop.pending` is set:

```typescript
// add to the imports
import { ConfirmDialog } from "@/components/ConfirmDialog";

// add just before the closing </main>, after <ChatPanel .../>
{loop.pending && (
  <ConfirmDialog proposal={loop.pending} onApply={loop.applyPending} onDecline={loop.declinePending} />
)}
```

- [ ] **Step 3: Manually verify the full write path**

With the service running in agent mode and a real `data/` (or a throwaway fixture copy — same setup earlier fix-rounds used, never the real `data/` for a manual write test): ask the chat to log something (e.g. "remember that I like tea"), let the model call `append_source`, confirm the dialog shows Before/After/diff, click Apply.
Expected: the dialog closes, the chat continues (into the follow-up phase, since a `sources.md` entry was just applied), and `data/sources.md` has the new `S-###` entry on disk. Click Decline on a second attempt and confirm nothing is written.

- [ ] **Step 4: Commit**

```bash
cd web
git add components/ConfirmDialog.tsx app/page.tsx
git commit -m "feat: add ConfirmDialog, wire Apply/Decline through useAgentLoop"
```

---

### Task 8: Sidebar — model control and snapshots

**Files:**
- Create: `web/components/Sidebar.tsx`
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes: `getModelStatus`, `getHealth`, `loadModel`, `unloadModel`, `getSnapshots`, `postSnapshotRestore` from `lib/api.ts`.
- Produces: model load/unload control and the snapshot-restore undo path, both currently only in Streamlit's sidebar.

- [ ] **Step 1: Implement `Sidebar`**

`web/components/Sidebar.tsx` — ports the model-control block (`chat_app.py:242-357`, minus the voice-sample section, out of scope):

```typescript
"use client";

import { useCallback, useEffect, useState } from "react";
import { getHealth, getModelStatus, getSnapshots, loadModel, postSnapshotRestore, unloadModel } from "@/lib/api";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export function Sidebar({ onRestored }: { onRestored: () => void }) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const [h, s] = await Promise.all([getHealth(), getModelStatus()]);
    setHealth(h);
    setStatus(s);
    if (s.agent) {
      const snap = await getSnapshots();
      setSnapshots(snap.snapshots);
      setSelected((prev) => prev || snap.snapshots[0] || "");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleLoad() {
    setLoading(true);
    try {
      await loadModel();
      await refresh();
    } finally {
      setLoading(false);
    }
  }

  async function handleUnload() {
    await unloadModel();
    await refresh();
  }

  async function handleRestore() {
    if (!selected) return;
    await postSnapshotRestore(selected);
    await refresh();
    onRestored();
  }

  return (
    <aside style={{ width: 260, padding: 16, borderLeft: "1px solid #ddd" }}>
      <h3>Service</h3>
      {health ? <p>{health.status === "ok" ? "Backend up" : health.status}</p> : <p>...</p>}

      <h3>Model</h3>
      {status?.name && <p>{status.name}</p>}
      {status?.detail && <p>{status.detail}</p>}
      {health?.model_loaded ? (
        <button onClick={handleUnload}>Unload</button>
      ) : (
        <button onClick={handleLoad} disabled={loading}>
          {loading ? "Loading..." : "Load model"}
        </button>
      )}

      {status?.agent && (
        <>
          <h3>Snapshots</h3>
          {snapshots.length === 0 ? (
            <p>No snapshots yet — one is taken before every write.</p>
          ) : (
            <>
              <select value={selected} onChange={(e) => setSelected(e.target.value)}>
                {snapshots.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button onClick={handleRestore}>Restore</button>
            </>
          )}
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 2: Wire it into the page**

Modify `web/app/page.tsx`: import `Sidebar`, lay it out alongside the chat panel, and pass `loop.reset` (already produced by Task 5's `useAgentLoop`) as `onRestored` — matching `chat_app.py:344-345`'s `history = []` on restore. Since persistence is out of scope, this clears the in-memory transcript rather than an on-disk log.

Update `web/app/page.tsx`:

```typescript
import { Sidebar } from "@/components/Sidebar";

// replace the <main> contents' layout:
return (
  <div style={{ display: "flex" }}>
    <main style={{ padding: 24, maxWidth: 800, flex: 1 }}>
      <h1>Admin</h1>
      <ChatPanel transcript={loop.transcript} steps={loop.steps} onSend={loop.send} />
      {loop.pending && (
        <ConfirmDialog proposal={loop.pending} onApply={loop.applyPending} onDecline={loop.declinePending} />
      )}
    </main>
    <Sidebar onRestored={loop.reset} />
  </div>
);
```

(Drop the standalone `error`/`health`/`status` state and effect from Step 2 of Task 6/Task 2 — `Sidebar` now owns that display.)

- [ ] **Step 3: Manually verify**

With the service running: Load model via the sidebar button, confirm status updates; make a write (as in Task 7) and confirm a snapshot appears in the dropdown after Apply; Restore it and confirm the chat panel clears and the file reverts.

- [ ] **Step 4: Commit**

```bash
cd web
git add components/Sidebar.tsx app/page.tsx hooks/useAgentLoop.ts
git commit -m "feat: add Sidebar for model control and snapshot restore"
```

---

### Task 9: `/story` command (text only)

**Files:**
- Create: `web/components/StoryBar.tsx`
- Modify: `web/app/page.tsx`

**Interfaces:**
- Consumes: `postStoryRoute`, `postIngest`, `postStoryPropose` from `lib/api.ts`; needs a way to hand the resulting proposal into the same pending-proposal state `ConfirmDialog` reads from `useAgentLoop` — add a `proposeExternal(proposal: Proposal)` entry point to the hook (a `/story` proposal has no paused tool call, matching `PendingState.step: null` already modeled in Task 5).

- [ ] **Step 1: Add an external-proposal entry point to the hook**

Modify `web/hooks/useAgentLoop.ts` — add to the returned object:

```typescript
    proposeExternal: useCallback((proposal: Proposal) => {
      setPending({ proposal, step: null });
    }, []),
```

- [ ] **Step 2: Implement `StoryBar`**

`web/components/StoryBar.tsx` — ports the `/story` text path (`chat_app.py:483-652`, file-upload branch at lines 485-501 omitted per Scope):

```typescript
"use client";

import { useState } from "react";
import { postIngest, postStoryPropose, postStoryRoute } from "@/lib/api";
import type { Proposal } from "@/lib/types";

function parseStoryCommand(text: string): { wantedId: string; wantedEvent: string; rest: string } {
  const match = /^(ST-\d+)(?:\/(E-\d+))?\s*/.exec(text.trim());
  if (!match) return { wantedId: "", wantedEvent: "", rest: text.trim() };
  return { wantedId: match[1], wantedEvent: match[2] ?? "", rest: text.slice(match[0].length).trim() };
}

export function StoryBar({ onProposal }: { onProposal: (proposal: Proposal) => void }) {
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    const text = draft.replace(/^\/story/, "").trim();
    if (!text) {
      setStatus("`/story` needs the narrative — type it after the command.");
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      const { wantedId, wantedEvent, rest } = parseStoryCommand(text);
      const routing = await postStoryRoute(rest);

      if (routing.branch === "duplicate") {
        const top = routing.runners_up[0];
        setStatus(`Already logged — ${(top.score * 100).toFixed(0)}% similar to ${top.story_id}. Nothing ingested.`);
        return;
      }

      const merge = Boolean(wantedEvent);
      const existing = routing.branch === "amend" ? routing.text : "";
      const ingested = await postIngest({ text: rest, existing, merge });
      const parsed = JSON.parse(ingested.content.replace(/^```json\n?|\n?```$/g, ""));

      const proposeResult = await postStoryPropose({
        branch: routing.branch === "duplicate" ? "append" : routing.branch,
        storyId: routing.story_id || wantedId,
        eventId: routing.event_id || wantedEvent,
        text: rest,
        merge,
        summary: parsed.summary,
        logged: parsed.logged ?? "",
        keywords: parsed.keywords ?? [],
        events: (parsed.events ?? []).map((e: { title: string; text: string }) => ({ title: e.title, text: e.text })),
      });

      if (proposeResult.proposal) {
        onProposal(proposeResult.proposal);
        setDraft("");
      } else {
        setStatus("No proposal came back — nothing to confirm.");
      }
    } catch (exc) {
      setStatus(String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "flex", gap: 8, marginTop: 16, borderTop: "1px solid #ddd", paddingTop: 8 }}>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="/story <narrative>, or ST-001 <addition>, or ST-001/E-001 <rewrite>"
        style={{ flex: 1 }}
      />
      <button onClick={submit} disabled={busy}>
        {busy ? "Working..." : "Log story"}
      </button>
      {status && <span>{status}</span>}
    </div>
  );
}
```

- [ ] **Step 3: Wire it into the page**

Modify `web/app/page.tsx`:

```typescript
import { StoryBar } from "@/components/StoryBar";

// inside <main>, below <ChatPanel .../>:
<StoryBar onProposal={loop.proposeExternal} />
```

- [ ] **Step 4: Manually verify**

With the service running in agent mode and a story corpus present (or a throwaway fixture): type `/story` followed by a short narrative with no `ST-###` prefix, click "Log story".
Expected: routing resolves to `new` (or `append`/`amend` if it matches an existing story), a proposal appears via `ConfirmDialog`, Apply writes the story file and takes a snapshot under `data/stories/.backups/`.

- [ ] **Step 5: Commit**

```bash
cd web
git add components/StoryBar.tsx app/page.tsx hooks/useAgentLoop.ts
git commit -m "feat: add StoryBar for text-only /story logging"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-08-10-nextjs-admin-ui-design.md`):
- Architecture (client-side SPA, CORS, no proxy) → Task 1, Task 2. ✓
- `lib/api.ts`, `lib/agentLoop.ts`, `lib/followup.ts`, `useAgentLoop`, `ChatPanel`, `ConfirmDialog`, `Sidebar`, `StoryBar` → Tasks 2-9, one task per component named in the spec. ✓
- Follow-up phase and story-landing scoping (added during spec self-review) → Task 5. ✓
- Vitest scoped to `agentLoop.ts`/`followup.ts` only, porting `_self_check()`'s scenarios → Task 3 Steps 3/5, Task 4 Step 1. ✓
- Explicitly-out-of-scope items (chat persistence, file upload, voice recording) → not present in any task; `StoryBar` (Task 9) omits the file-upload branch by name. ✓
- Migration note (`chat_app.py` untouched) → Global Constraints. ✓

**Correction, added after the final whole-branch review found the claim above incomplete:** this table checked that each *named component* in the design spec had a task, not that each *Scope bullet* did. Two design-spec Scope items (`docs/superpowers/specs/2026-08-10-nextjs-admin-ui-design.md:20,24`) had no task anywhere in this plan: story-landing scoping resetting `prompt_floor` and dropping the active summary (only the `currentStory` half of that bullet got built, and it was inert with no `prompt_floor` to act on), and compaction (`plan_compaction` → `/summarize`) — `postSummarize` exists in `lib/api.ts` but nothing calls it. The final review's ruling: compaction genuinely can ship as a documented follow-up (it has an ordering dependency on persistence, which is also deferred, and on generation-params being settable, which was a separate missed Scope item), but `prompt_floor` is cheap enough that the fix wave wires it rather than leaving `currentStory` as dead state. For sub-project 3: check spec coverage one row per Scope *bullet*, not one row per named component — that's the method gap this missed, not an implementer error.

**Placeholder scan:** no "TBD"/"TODO"/"add appropriate" phrasing in any step; every code block is complete, runnable TypeScript or Python, not a sketch.

**Type consistency:** `Step`, `Proposal`, `Message` (with `toolCalls`/`toolCallId`, camelCase per Task 2's `lib/types.ts`) are used identically across Tasks 3, 5, 6, 7, 9. `ToolOutcome`'s two-variant shape (Task 3) matches exactly how Task 5's `dispatch` constructs it from `ToolResponse`. `PendingState.step: Step | null` (Task 5) is read the same way by both Task 7's Apply/Decline (closes a real step) and Task 9's `proposeExternal` (passes `null`, matching `confirm_dialog`'s "a `/story` proposal has no paused tool call" comment in `chat_app.py:140-144`).

**Pre-flight fix (caught before dispatching Task 1):** the first draft of Task 5 only exposed `steps` (the live `Step` stream) with no persisted, role-tagged transcript — `ChatPanel` would never have rendered what the user typed, since user messages never become `Step`s. Fixed by adding `transcript: Message[]` to `useAgentLoop`'s return (populated in `send()` and on every `"answer"` step), with `steps` narrowed to mean only the current turn's live trace, cleared at the start of each `drive()` call. `ChatPanel` (Task 6) now renders both. Also removed a dead no-op line (`setSteps(...).slice(0, -1)`) that was accidentally left in the first draft of `send()`.
