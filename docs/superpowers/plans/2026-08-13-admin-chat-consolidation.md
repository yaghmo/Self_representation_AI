# Admin Chat Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the working admin-chat logic from the standalone `web/` app into `cookbook-web`, and rebuild its UI as a GPT-like layout (sidebar + centered chat column + composer) using the shadcn components already installed there.

**Architecture:** `web/lib/{types,toolSchemas,agentLoop,followup}.ts` and `web/hooks/useAgentLoop.ts` move into `cookbook-web` under `lib/chat/` and `hooks/`, unchanged in behavior — only import paths change. The bare, unstyled components (`web/components/{ChatPanel,ConfirmDialog,Sidebar,StoryBar}.tsx`) are rebuilt from scratch as shadcn-based components under `cookbook-web/components/chat/`, wired together on a new `cookbook-web/app/admin/page.tsx` route. `web/` is left in place, untouched, until this is verified working.

**Tech Stack:** Next.js 16.2.6 (App Router, client components), React 19.2.4, TypeScript 5, Tailwind v4 + shadcn (`style: base-rhea`, `baseColor: neutral`), Vitest (new to `cookbook-web`, scoped to two files).

## Global Constraints

- No backend changes in this pass. Every endpoint used (`/chat`, `/admin/tool`, `/admin/proposal/apply`, `/admin/snapshots`, `/admin/snapshots/restore`, `/admin/story/route`, `/admin/story/propose`, `/ingest`, `/model`, `/model/load`, `/model/unload`, `/health`) already exists in `service/main.py`.
- `web/` is not deleted or modified in this pass. It stays in place until the ported route is verified equivalent — a follow-up, not a step here.
- The fan-facing page is out of scope. Do not build it, stub it, or reserve a route for it.
- No auth/gating added — matches every other surface in this repo today (single local user).
- `lib/chat/*` and `hooks/useAgentLoop.ts` are a straight behavioral port from `web/lib/*` and `web/hooks/useAgentLoop.ts` — the logic must not change, only its file location and import paths.
- New shadcn primitives are added only via `npx shadcn add <name>`, only the ones actually used: `textarea`, `scroll-area`, `input`, `separator`.
- Vitest is added to `cookbook-web` scoped to `lib/chat/agentLoop.ts` and `lib/chat/followup.ts` only — no test framework work for UI components, matching this repo's existing norm of hand-verifying UI.
- `NEXT_PUBLIC_SERVICE_URL` (default `http://127.0.0.1:8000`) is the chat/admin backend (`service/main.py`). `NEXT_PUBLIC_COOKBOOK_API_URL` (default `http://127.0.0.1:8001`) is the unrelated cookbook-wizard backend (`cookbook/api.py`). Never conflate the two — they are different FastAPI processes.

## File Structure

```
cookbook-web/
  lib/
    chat/
      types.ts          # NEW — ported from web/lib/types.ts, unchanged
      toolSchemas.ts     # NEW — ported from web/lib/toolSchemas.ts, unchanged
      api.ts             # NEW — ported from web/lib/api.ts, unchanged (own SERVICE_URL)
      agentLoop.ts        # NEW — ported from web/lib/agentLoop.ts, unchanged
      agentLoop.test.ts   # NEW — ported from web/lib/agentLoop.test.ts, unchanged
      followup.ts          # NEW — ported from web/lib/followup.ts, unchanged
      followup.test.ts     # NEW — ported from web/lib/followup.test.ts, unchanged
  hooks/
    useAgentLoop.ts      # NEW — ported from web/hooks/useAgentLoop.ts, import paths updated
  components/
    chat/
      ChatPanel.tsx           # NEW — rebuilt with shadcn (thread + composer + step trace)
      ConfirmProposalDialog.tsx  # NEW — rebuilt with shadcn Dialog
      ModelSidebar.tsx        # NEW — rebuilt with shadcn (status, load/unload, generation, snapshots)
      StoryComposer.tsx        # NEW — rebuilt with shadcn (the /story bar)
    ui/
      textarea.tsx    # NEW — via shadcn CLI
      scroll-area.tsx # NEW — via shadcn CLI
      input.tsx        # NEW — via shadcn CLI
      separator.tsx    # NEW — via shadcn CLI
  app/
    admin/
      page.tsx    # NEW — assembles the above into the GPT-like layout
  vitest.config.ts   # NEW
  package.json       # MODIFY — add vitest devDependency + "test" script
  .env.local.example # NEW — documents NEXT_PUBLIC_SERVICE_URL + NEXT_PUBLIC_COOKBOOK_API_URL
  README.md          # MODIFY — note the two backends and how to run this route
```

---

### Task 1: Chat data layer — types, tool schemas, API client

**Files:**
- Create: `cookbook-web/lib/chat/types.ts`
- Create: `cookbook-web/lib/chat/toolSchemas.ts`
- Create: `cookbook-web/lib/chat/api.ts`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces: `Role`, `Message`, `ToolCall`, `messageToApi()`, `Proposal`, `StepKind`, `Step`, `HealthStatus`, `ModelStatus`, `ChatResponse`, `StoryRouteResponse`, `ToolResponse` (from `types.ts`); `TOOL_SCHEMAS`, `FOLLOWUP_SCHEMAS` (from `toolSchemas.ts`); `ApiError`, `getHealth()`, `getModelStatus()`, `loadModel()`, `unloadModel()`, `postChat(params: ChatParams)`, `postAdminTool(name, args)`, `postProposalApply(proposal)`, `getSnapshots()`, `postSnapshotRestore(name)`, `postStoryRoute(text)`, `postStoryPropose(params: StoryProposeParams)`, `postIngest(params: IngestParams)`, `postSummarize(messages, maxTokens?)` (from `api.ts`). All later tasks import these from `@/lib/chat/types` / `@/lib/chat/toolSchemas` / `@/lib/chat/api`.

- [ ] **Step 1: Create `lib/chat/types.ts`**

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

- [ ] **Step 2: Create `lib/chat/toolSchemas.ts`**

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

- [ ] **Step 3: Create `lib/chat/api.ts`**

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

- [ ] **Step 4: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors from the three new files (unused-export warnings are fine — nothing imports them yet).

- [ ] **Step 5: Commit**

```bash
git add cookbook-web/lib/chat/types.ts cookbook-web/lib/chat/toolSchemas.ts cookbook-web/lib/chat/api.ts
git commit -m "feat(cookbook-web): port chat types, tool schemas, and API client from web/"
```

---

### Task 2: Agent loop — Vitest setup + ported state machine

**Files:**
- Modify: `cookbook-web/package.json`
- Create: `cookbook-web/vitest.config.ts`
- Create: `cookbook-web/lib/chat/agentLoop.test.ts`
- Create: `cookbook-web/lib/chat/agentLoop.ts`

**Interfaces:**
- Consumes: `Message`, `Proposal`, `Step` from `./types` (Task 1); `TOOL_SCHEMAS` from `./toolSchemas` (Task 1).
- Produces: `MAX_ITERATIONS`, `ToolOutcome`, `PostTurn`, `RunOptions`, `runAgentLoop(post, messages, options)` (async generator yielding `Step`), `resumed(step, outcome)`. Task 4 (`useAgentLoop.ts`) imports `runAgentLoop` and `resumed` from `@/lib/chat/agentLoop`.

- [ ] **Step 1: Add Vitest to `cookbook-web/package.json`**

Add `"test": "vitest run"` to `scripts`, and add to `devDependencies`:

```json
"vitest": "^2.1.0"
```

- [ ] **Step 2: Install**

Run: `cd cookbook-web && npm install`
Expected: `vitest` appears in `node_modules`, `package-lock.json` updates.

- [ ] **Step 3: Create `vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node" },
});
```

- [ ] **Step 4: Write the ported test file `lib/chat/agentLoop.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { runAgentLoop, resumed } from "./agentLoop";
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

  it("distinguishes calls with different nested argument values as separate invocations", async () => {
    let postCalls = 0;
    const post = async () => {
      postCalls += 1;
      if (postCalls === 1) {
        return { content: "", tool_calls: [call("c1", "append_source", JSON.stringify({ question: "q1", answer: "a1", entry_type: "direct answer", tags: [], date: "unknown", feeds: [] }))] };
      }
      if (postCalls === 2) {
        return { content: "", tool_calls: [call("c2", "append_source", JSON.stringify({ question: "q1", answer: "a2", entry_type: "direct answer", tags: [], date: "unknown", feeds: [] }))] };
      }
      return { content: "done", tool_calls: [] };
    };
    let dispatchCount = 0;
    const dispatch = async (name: string, args: Record<string, unknown>) => {
      dispatchCount += 1;
      if (dispatchCount === 1) {
        expect((args as Record<string, unknown>).answer).toBe("a1");
      } else if (dispatchCount === 2) {
        expect((args as Record<string, unknown>).answer).toBe("a2");
      }
      return { kind: "result" as const, text: `result ${dispatchCount}` };
    };

    const steps = await collect(runAgentLoop(post, [{ role: "user", content: "hi" }], { dispatch }));
    expect(dispatchCount).toBe(2);
    expect(steps[steps.length - 1].text).toBe("done");
  });
});

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

- [ ] **Step 5: Run test to verify it fails**

Run: `cd cookbook-web && npx vitest run lib/chat/agentLoop.test.ts`
Expected: FAIL — `Cannot find module './agentLoop'` (the file doesn't exist yet).

- [ ] **Step 6: Create `lib/chat/agentLoop.ts`**

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

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value as object).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify((value as Record<string, unknown>)[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
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

      const signature = `${name}:${stableStringify(args)}`;
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

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd cookbook-web && npx vitest run lib/chat/agentLoop.test.ts`
Expected: PASS — 7 tests.

- [ ] **Step 8: Commit**

```bash
git add cookbook-web/package.json cookbook-web/package-lock.json cookbook-web/vitest.config.ts cookbook-web/lib/chat/agentLoop.ts cookbook-web/lib/chat/agentLoop.test.ts
git commit -m "feat(cookbook-web): add vitest and port the agent loop state machine"
```

---

### Task 3: Follow-up phase — ported module + tests

**Files:**
- Create: `cookbook-web/lib/chat/followup.test.ts`
- Create: `cookbook-web/lib/chat/followup.ts`

**Interfaces:**
- Consumes: `Message` from `./types` (Task 1).
- Produces: `entryIdOf(entry)`, `entryFeeds(entry)`, `buildFollowup(entry, readSection)`. Task 4 (`useAgentLoop.ts`) imports `entryIdOf` and `buildFollowup` from `@/lib/chat/followup`.

- [ ] **Step 1: Write the ported test file `lib/chat/followup.test.ts`**

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
    expect(task[0].content).toContain("could not read this section: no section");
    expect(task[0].content).not.toContain("Error: no section");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cookbook-web && npx vitest run lib/chat/followup.test.ts`
Expected: FAIL — `Cannot find module './followup'`.

- [ ] **Step 3: Create `lib/chat/followup.ts`**

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
      current.push(`## ${name}\n[could not read this section: ${exc instanceof Error ? exc.message : exc}]`);
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cookbook-web && npx vitest run lib/chat/followup.test.ts`
Expected: PASS — 6 tests.

- [ ] **Step 5: Run the full test suite**

Run: `cd cookbook-web && npm test`
Expected: PASS — 13 tests total (7 from Task 2 + 6 from this task).

- [ ] **Step 6: Commit**

```bash
git add cookbook-web/lib/chat/followup.ts cookbook-web/lib/chat/followup.test.ts
git commit -m "feat(cookbook-web): port the follow-up phase (log-a-source → update-profile)"
```

---

### Task 4: `useAgentLoop` hook

**Files:**
- Create: `cookbook-web/hooks/useAgentLoop.ts`

**Interfaces:**
- Consumes: `postAdminTool`, `postChat`, `postProposalApply`, `ApiError` from `@/lib/chat/api` (Task 1); `runAgentLoop`, `resumed`, `ToolOutcome` from `@/lib/chat/agentLoop` (Task 2); `buildFollowup`, `entryIdOf` from `@/lib/chat/followup` (Task 3); `TOOL_SCHEMAS`, `FOLLOWUP_SCHEMAS` from `@/lib/chat/toolSchemas` (Task 1); `Message`, `Proposal`, `Step` from `@/lib/chat/types` (Task 1).
- Produces: `GenerationParams` type, `useAgentLoop(params: GenerationParams)` returning `{ transcript, steps, pending, currentStory, error, busy, send, applyPending, declinePending, reset, proposeExternal }`. Tasks 6–10 (the components and the page) consume this hook and its return shape directly.

- [ ] **Step 1: Create `hooks/useAgentLoop.ts`**

```typescript
"use client";

import { useCallback, useRef, useState } from "react";
import { postAdminTool, postChat, postProposalApply, ApiError } from "@/lib/chat/api";
import { runAgentLoop, resumed, type ToolOutcome } from "@/lib/chat/agentLoop";
import { buildFollowup, entryIdOf } from "@/lib/chat/followup";
import { TOOL_SCHEMAS, FOLLOWUP_SCHEMAS } from "@/lib/chat/toolSchemas";
import type { Message, Proposal, Step } from "@/lib/chat/types";

export interface GenerationParams {
  temperature: number;
  maxTokens: number;
  thinking: boolean;
}

interface PendingState {
  proposal: Proposal;
  step: Step | null; // null for a /story-originated proposal — nothing paused to close
}

function messageOf(exc: unknown): string {
  if (exc instanceof ApiError) return exc.detail;
  return exc instanceof Error ? exc.message : String(exc);
}

export function useAgentLoop(params: GenerationParams) {
  // The persisted transcript (user + assistant turns) the UI renders as
  // chat bubbles — mirrors `session_state["history"]`. Separate from
  // `steps`, which is only the current turn's live tool-call trace.
  const [transcript, setTranscript] = useState<Message[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [pending, setPending] = useState<PendingState | null>(null);
  const [currentStory, setCurrentStory] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The persistent conversation, mirroring `session_state["history"]`: only
  // user turns and finished assistant replies ever land here. A run's own
  // transient history (a resumed tool exchange, a follow-up task) is passed
  // to `drive()` and never assigned back.
  const historyRef = useRef<Message[]>([]);
  const seenRef = useRef(new Map<string, number>());
  // Once the follow-up phase is open, resuming a call inside it re-offers
  // FOLLOWUP_SCHEMAS, never append_source.
  const followupActiveRef = useRef(false);
  // A landed story is on disk and indexed, so its turns stop being sent
  // while staying on screen.
  const promptFloorRef = useRef(0);

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
      setBusy(true);
      const post = async (turnHistory: Message[], turnTools: Record<string, unknown>[]) =>
        postChat({
          messages: turnHistory,
          temperature: params.temperature,
          maxTokens: params.maxTokens,
          thinking: params.thinking,
          tools: turnTools,
        });

      try {
        for await (const step of runAgentLoop(post, history, { dispatch, tools, seen: seenRef.current })) {
          setSteps((prev) => [...prev, step]);
          if (step.kind === "proposal") {
            setPending({ proposal: step.proposal as Proposal, step });
          }
          if (step.kind === "answer" || step.kind === "stopped") {
            // `history` is this run's own material — it may carry a tool
            // exchange or a synthetic follow-up task. Only the reply is
            // persisted, onto the real conversation.
            const assistantMessage: Message = { role: "assistant", content: step.text };
            historyRef.current = [...historyRef.current, assistantMessage];
            setTranscript((prev) => [...prev, assistantMessage]);
          }
        }
      } catch (exc) {
        setError(messageOf(exc));
      } finally {
        setBusy(false);
      }
    },
    [dispatch, params.maxTokens, params.temperature, params.thinking]
  );

  const send = useCallback(
    async (text: string) => {
      // Typing instead of deciding abandons the paused turn and any open phase.
      setPending(null);
      setError(null);
      seenRef.current = new Map();
      followupActiveRef.current = false;
      const userMessage: Message = { role: "user", content: text };
      historyRef.current = [...historyRef.current, userMessage];
      setTranscript((prev) => [...prev, userMessage]);
      // Send only what is above the floor.
      await drive(historyRef.current.slice(promptFloorRef.current), TOOL_SCHEMAS);
    },
    [drive]
  );

  const resolveProposal = useCallback(
    async (outcome: string, appliedPath?: string) => {
      const current = pending;
      setPending(null);
      if (!current) return;
      setError(null);

      try {
        // Story-landing scoping: a proposal that landed under stories/ resets
        // what gets resent on later turns.
        if (appliedPath && /[/\\]stories[/\\][^/\\]+\.md$/.test(appliedPath)) {
          const landed = appliedPath.replace(/\.md$/, "").split(/[/\\]/).pop() ?? null;
          if (landed && landed !== currentStory) {
            setCurrentStory(landed);
            promptFloorRef.current = historyRef.current.length;
          }
        }

        // A /story-originated proposal has no paused tool call to close.
        if (!current.step) return;

        // Follow-up phase: an applied sources.md proposal carrying an entry id
        // starts a fresh bounded conversation instead of a plain resume.
        const isSourceEntry = appliedPath?.endsWith("sources.md") && entryIdOf(current.proposal.after);
        if (isSourceEntry) {
          const entryText = current.proposal.after;
          const task = await buildFollowup(entryText, async (heading) => {
            const result = await postAdminTool("read_profile_section", { heading });
            return result.result ?? "";
          });
          followupActiveRef.current = true;
          await drive(task, FOLLOWUP_SCHEMAS);
          return;
        }

        // Applying one line of a follow-up resumes the follow-up — the phase,
        // and its tool set, have not changed.
        await drive(
          resumed(current.step, outcome),
          followupActiveRef.current ? FOLLOWUP_SCHEMAS : TOOL_SCHEMAS
        );
      } catch (exc) {
        setError(messageOf(exc));
      }
    },
    [currentStory, drive, pending]
  );

  const applyPending = useCallback(async () => {
    if (!pending) return;
    setError(null);
    const summary = pending.proposal.summary;
    let path: string | undefined;
    let failure = "";
    try {
      path = (await postProposalApply(pending.proposal)).path;
    } catch (exc) {
      failure = messageOf(exc);
    }
    const shown = failure ? `[not applied: ${failure}]` : `[applied: ${summary}]`;
    setTranscript((prev) => [...prev, { role: "user", content: shown }]);
    await resolveProposal(
      failure
        ? `not applied — ${failure}`
        : `applied — ${summary}. This write is done; do not repeat it.`,
      path
    );
  }, [pending, resolveProposal]);

  const declinePending = useCallback(() => {
    if (!pending) return;
    setTranscript((prev) => [...prev, { role: "user", content: `[declined: ${pending.proposal.summary}]` }]);
    void resolveProposal(`declined by the creator — ${pending.proposal.summary}. Do not retry it.`);
  }, [pending, resolveProposal]);

  const reset = useCallback(() => {
    setTranscript([]);
    setSteps([]);
    setPending(null);
    setCurrentStory(null);
    setError(null);
    historyRef.current = [];
    seenRef.current = new Map();
    followupActiveRef.current = false;
    promptFloorRef.current = 0;
  }, []);

  // A /story proposal arrives fully formed from StoryComposer, with no paused
  // tool call in the agent loop to resume — step is null.
  const proposeExternal = useCallback((proposal: Proposal) => {
    setPending({ proposal, step: null });
  }, []);

  return {
    transcript,
    steps,
    pending: pending?.proposal ?? null,
    currentStory,
    error,
    busy,
    send,
    applyPending,
    declinePending,
    reset,
    proposeExternal,
  };
}
```

- [ ] **Step 2: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cookbook-web/hooks/useAgentLoop.ts
git commit -m "feat(cookbook-web): port the useAgentLoop hook"
```

---

### Task 5: Add missing shadcn primitives

**Files:**
- Create: `cookbook-web/components/ui/textarea.tsx`
- Create: `cookbook-web/components/ui/scroll-area.tsx`
- Create: `cookbook-web/components/ui/input.tsx`
- Create: `cookbook-web/components/ui/separator.tsx`

**Interfaces:**
- Consumes: nothing project-specific — generated by the shadcn CLI against the existing `components.json` config (`style: base-rhea`, `baseColor: neutral`).
- Produces: `Textarea`, `ScrollArea`, `Input`, `Separator` components under `@/components/ui/*`. Tasks 6–8 import these directly.

- [ ] **Step 1: Run the shadcn CLI**

Run: `cd cookbook-web && npx shadcn@latest add textarea scroll-area input separator`
Expected: four new files created under `components/ui/`, no errors.

- [ ] **Step 2: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cookbook-web/components/ui/textarea.tsx cookbook-web/components/ui/scroll-area.tsx cookbook-web/components/ui/input.tsx cookbook-web/components/ui/separator.tsx
git commit -m "chore(cookbook-web): add textarea, scroll-area, input, separator via shadcn"
```

---

### Task 6: `ChatPanel` — GPT-like message thread + composer

**Files:**
- Create: `cookbook-web/components/chat/ChatPanel.tsx`

**Interfaces:**
- Consumes: `Message`, `Step` from `@/lib/chat/types` (Task 1); `Button` (`@/components/ui/button`), `Textarea` (Task 5), `ScrollArea` (Task 5), `Alert`/`AlertDescription` (`@/components/ui/alert`), `Badge` (`@/components/ui/badge`), `cn` (`@/lib/utils`) — all pre-existing in `cookbook-web` except `Textarea`/`ScrollArea`.
- Produces: `ChatPanel({ transcript, steps, error, busy, onSend })`. Task 10 (`app/admin/page.tsx`) renders this with `useAgentLoop`'s `transcript`, `steps`, `error`, `busy`, `send`.

- [ ] **Step 1: Create `components/chat/ChatPanel.tsx`**

```tsx
"use client";

import { useState } from "react";
import { Bot, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Message, Step } from "@/lib/chat/types";

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted">
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        )}
      >
        {message.content}
      </div>
    </div>
  );
}

function StepTrace({ step }: { step: Step }) {
  switch (step.kind) {
    case "tool_call":
      return (
        <div className="pl-11 text-xs text-muted-foreground">
          <Badge variant="outline">{step.name}</Badge>{" "}
          <span className="font-mono">{step.text}</span>
        </div>
      );
    case "tool_result":
      return (
        <details className="pl-11 text-xs text-muted-foreground">
          <summary className="cursor-pointer">{step.name} result</summary>
          <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted p-2">{step.text}</pre>
        </details>
      );
    case "proposal":
      return <div className="pl-11 text-xs text-amber-600 dark:text-amber-400">{step.text}</div>;
    case "stopped":
      return <div className="pl-11 text-xs text-destructive">{step.text}</div>;
    default:
      return null;
  }
}

export function ChatPanel({
  transcript,
  steps,
  error,
  busy,
  onSend,
}: {
  transcript: Message[];
  steps: Step[];
  error: string | null;
  busy: boolean;
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");

  function submit() {
    if (busy) return; // one turn at a time — concurrent drives interleave history writes
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onSend(text);
  }

  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="flex-1 px-6 py-4">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {transcript.map((message, i) => (
            <MessageBubble key={i} message={message} />
          ))}
          {steps
            .filter((step) => step.kind !== "answer" && step.kind !== "stopped")
            .map((step, i) => (
              <StepTrace key={i} step={step} />
            ))}
          {busy && <div className="pl-11 text-xs text-muted-foreground">thinking…</div>}
        </div>
      </ScrollArea>
      <div className="mx-auto w-full max-w-2xl px-6 pb-4">
        {error && (
          <Alert variant="destructive" className="mb-2">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex items-end gap-2 rounded-2xl border bg-background p-2 shadow-sm">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Message the character…"
            className="min-h-10 flex-1 resize-none border-0 shadow-none focus-visible:ring-0"
          />
          <Button onClick={submit} disabled={busy || !draft.trim()}>
            {busy ? "Working…" : "Send"}
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cookbook-web/components/chat/ChatPanel.tsx
git commit -m "feat(cookbook-web): add ChatPanel with GPT-like thread and composer"
```

---

### Task 7: `ConfirmProposalDialog` — the write confirm-gate

**Files:**
- Create: `cookbook-web/components/chat/ConfirmProposalDialog.tsx`

**Interfaces:**
- Consumes: `Proposal` from `@/lib/chat/types` (Task 1); `Dialog`, `DialogContent`, `DialogDescription`, `DialogFooter`, `DialogHeader`, `DialogTitle` (`@/components/ui/dialog`, pre-existing); `Button` (`@/components/ui/button`, pre-existing).
- Produces: `ConfirmProposalDialog({ proposal, onApply, onDecline })`. Task 10 renders this when `useAgentLoop`'s `pending` is non-null, wired to `applyPending`/`declinePending`.

- [ ] **Step 1: Create `components/chat/ConfirmProposalDialog.tsx`**

```tsx
"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { Proposal } from "@/lib/chat/types";

export function ConfirmProposalDialog({
  proposal,
  onApply,
  onDecline,
}: {
  proposal: Proposal;
  onApply: () => void;
  onDecline: () => void;
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && onDecline()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Confirm this change</DialogTitle>
          <DialogDescription>{proposal.summary} — nothing has been written yet.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="mb-1 text-sm font-medium">Before</p>
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs">
              {proposal.before || "new — nothing is being replaced"}
            </pre>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">After</p>
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs">
              {proposal.after}
            </pre>
          </div>
        </div>
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground">Unified diff</summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs">
            {proposal.diff}
          </pre>
        </details>
        <DialogFooter>
          <Button variant="outline" onClick={onDecline}>
            Decline
          </Button>
          <Button onClick={onApply}>Apply</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cookbook-web/components/chat/ConfirmProposalDialog.tsx
git commit -m "feat(cookbook-web): add ConfirmProposalDialog for the write confirm-gate"
```

---

### Task 8: `ModelSidebar` — status, generation, snapshots

**Files:**
- Create: `cookbook-web/components/chat/ModelSidebar.tsx`

**Interfaces:**
- Consumes: `getHealth`, `getModelStatus`, `getSnapshots`, `loadModel`, `postSnapshotRestore`, `unloadModel` from `@/lib/chat/api` (Task 1); `GenerationParams` from `@/hooks/useAgentLoop` (Task 4); `HealthStatus`, `ModelStatus` from `@/lib/chat/types` (Task 1); `Card`/`CardContent`/`CardHeader`/`CardTitle`, `Button`, `Badge`, `Slider`, `Checkbox`, `Label`, `Select`/`SelectContent`/`SelectItem`/`SelectTrigger`/`SelectValue`, `Alert`/`AlertDescription` (all pre-existing); `Separator` (Task 5).
- Produces: `ModelSidebar({ generation, onGeneration, onRestored })`. Task 10 renders this with the page's local `generation` state and `useAgentLoop`'s `reset` (as `onRestored`).

- [ ] **Step 1: Create `components/chat/ModelSidebar.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getHealth,
  getModelStatus,
  getSnapshots,
  loadModel,
  postSnapshotRestore,
  unloadModel,
} from "@/lib/chat/api";
import type { GenerationParams } from "@/hooks/useAgentLoop";
import type { HealthStatus, ModelStatus } from "@/lib/chat/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function ModelSidebar({
  generation,
  onGeneration,
  onRestored,
}: {
  generation: GenerationParams;
  onGeneration: (next: Partial<GenerationParams>) => void;
  onRestored: () => void;
}) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [refresh]);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    try {
      await loadModel();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleUnload() {
    setError(null);
    try {
      await unloadModel();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRestore() {
    if (!selected) return;
    setError(null);
    try {
      await postSnapshotRestore(selected);
      await refresh();
      onRestored();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <aside className="flex w-80 shrink-0 flex-col gap-4 overflow-y-auto border-l bg-muted/30 p-4">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Model</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Badge variant={health?.status === "ok" ? "default" : "destructive"}>
            {health ? (health.status === "ok" ? "Backend up" : health.status) : "…"}
          </Badge>
          {status?.name && <p className="text-sm font-medium">{status.name}</p>}
          {status?.detail && <p className="text-xs text-muted-foreground">{status.detail}</p>}
          {health?.model_loaded ? (
            <Button variant="outline" size="sm" className="w-full" onClick={handleUnload}>
              Unload
            </Button>
          ) : (
            <Button size="sm" className="w-full" onClick={handleLoad} disabled={loading}>
              {loading ? "Loading…" : "Load model"}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Generation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Temperature</span>
              <span>{generation.temperature.toFixed(2)}</span>
            </div>
            <Slider
              min={0}
              max={1.5}
              step={0.05}
              value={[generation.temperature]}
              onValueChange={([v]) => onGeneration({ temperature: v })}
            />
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Max tokens</span>
              <span>{generation.maxTokens}</span>
            </div>
            <Slider
              min={64}
              max={2048}
              step={64}
              value={[generation.maxTokens]}
              onValueChange={([v]) => onGeneration({ maxTokens: v })}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="thinking"
              checked={generation.thinking}
              onCheckedChange={(checked) => onGeneration({ thinking: checked === true })}
            />
            <Label htmlFor="thinking" className="text-sm font-normal">
              Reasoning
            </Label>
          </div>
        </CardContent>
      </Card>

      {status?.agent && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Snapshots</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {snapshots.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No snapshots yet — one is taken before every write.
              </p>
            ) : (
              <>
                <Select value={selected} onValueChange={setSelected}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Choose a snapshot" />
                  </SelectTrigger>
                  <SelectContent>
                    {snapshots.map((name) => (
                      <SelectItem key={name} value={name}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button variant="outline" size="sm" className="w-full" onClick={handleRestore}>
                  Restore
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Separator />
      <p className="text-xs text-muted-foreground">
        Writes to the character profile always pause for your confirmation.
      </p>
    </aside>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cookbook-web/components/chat/ModelSidebar.tsx
git commit -m "feat(cookbook-web): add ModelSidebar with status, generation, snapshots"
```

---

### Task 9: `StoryComposer` — `/story` text ingestion bar

**Files:**
- Create: `cookbook-web/components/chat/StoryComposer.tsx`

**Interfaces:**
- Consumes: `postIngest`, `postStoryPropose`, `postStoryRoute` from `@/lib/chat/api` (Task 1); `Proposal` from `@/lib/chat/types` (Task 1); `Input` (Task 5), `Button` (pre-existing).
- Produces: `StoryComposer({ onProposal })`. Task 10 renders this wired to `useAgentLoop`'s `proposeExternal`.

- [ ] **Step 1: Create `components/chat/StoryComposer.tsx`**

```tsx
"use client";

import { useState } from "react";
import { postIngest, postStoryPropose, postStoryRoute } from "@/lib/chat/api";
import type { Proposal } from "@/lib/chat/types";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

function parseStoryCommand(text: string): { wantedId: string; wantedEvent: string; rest: string } {
  const match = /^(ST-\d+)(?:\/(E-\d+))?\s*/.exec(text.trim());
  if (!match) return { wantedId: "", wantedEvent: "", rest: text.trim() };
  return { wantedId: match[1], wantedEvent: match[2] ?? "", rest: text.slice(match[0].length).trim() };
}

export function StoryComposer({ onProposal }: { onProposal: (proposal: Proposal) => void }) {
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [isError, setIsError] = useState(false);
  const [busy, setBusy] = useState(false);

  function fail(message: string) {
    setStatus(message);
    setIsError(true);
  }

  async function submit() {
    const text = draft.replace(/^\/story/, "").trim();
    if (!text) {
      fail("`/story` needs the narrative — type it after the command.");
      return;
    }
    setBusy(true);
    setStatus("");
    setIsError(false);
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
        branch: routing.branch,
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
        fail("No proposal came back — nothing to confirm.");
      }
    } catch (exc) {
      fail(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl items-center gap-2 border-t px-6 py-3">
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="/story <narrative>, or ST-001 <addition>, or ST-001/E-001 <rewrite>"
        className="flex-1"
      />
      <Button variant="secondary" onClick={submit} disabled={busy}>
        {busy ? "Working…" : "Log story"}
      </Button>
      {status && (
        <span className={isError ? "text-xs text-destructive" : "text-xs text-emerald-600"}>{status}</span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add cookbook-web/components/chat/StoryComposer.tsx
git commit -m "feat(cookbook-web): add StoryComposer for /story text ingestion"
```

---

### Task 10: Assemble `/admin` page + env config

**Files:**
- Create: `cookbook-web/app/admin/page.tsx`
- Create: `cookbook-web/.env.local.example`
- Modify: `cookbook-web/README.md`

**Interfaces:**
- Consumes: `useAgentLoop`, `GenerationParams` (Task 4); `ChatPanel` (Task 6); `ConfirmProposalDialog` (Task 7); `ModelSidebar` (Task 8); `StoryComposer` (Task 9).
- Produces: the `/admin` route, reachable at `http://localhost:3000/admin` once `next dev` is running.

- [ ] **Step 1: Create `app/admin/page.tsx`**

```tsx
"use client";

import { useState } from "react";
import { useAgentLoop, type GenerationParams } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ConfirmProposalDialog } from "@/components/chat/ConfirmProposalDialog";
import { ModelSidebar } from "@/components/chat/ModelSidebar";
import { StoryComposer } from "@/components/chat/StoryComposer";

export default function AdminPage() {
  const [generation, setGeneration] = useState<GenerationParams>({
    temperature: 0.7,
    maxTokens: 512,
    thinking: false,
  });
  const loop = useAgentLoop(generation);

  return (
    <div className="flex h-screen">
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="border-b px-6 py-3">
          <h1 className="text-sm font-semibold">Admin</h1>
        </header>
        <div className="flex-1 overflow-hidden">
          <ChatPanel
            transcript={loop.transcript}
            steps={loop.steps}
            error={loop.error}
            busy={loop.busy}
            onSend={loop.send}
          />
        </div>
        <StoryComposer onProposal={loop.proposeExternal} />
      </div>
      <ModelSidebar
        generation={generation}
        onGeneration={(next) => setGeneration((prev) => ({ ...prev, ...next }))}
        onRestored={loop.reset}
      />
      {loop.pending && (
        <ConfirmProposalDialog
          proposal={loop.pending}
          onApply={loop.applyPending}
          onDecline={loop.declinePending}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create `.env.local.example`**

```
# The chat/admin backend — service/main.py (uvicorn service.main:app --port 8000)
NEXT_PUBLIC_SERVICE_URL=http://127.0.0.1:8000

# The cookbook wizard backend — cookbook/api.py
NEXT_PUBLIC_COOKBOOK_API_URL=http://127.0.0.1:8001
```

- [ ] **Step 3: Update `README.md`**

Append this section to `cookbook-web/README.md`:

```markdown
## Backends

This app talks to two separate FastAPI processes:

- `NEXT_PUBLIC_COOKBOOK_API_URL` (default `http://127.0.0.1:8001`) — `cookbook/api.py`, the hardware-probe/fit wizard at `/`.
- `NEXT_PUBLIC_SERVICE_URL` (default `http://127.0.0.1:8000`) — `service/main.py`, the chat/admin backend at `/admin`.

Copy `.env.local.example` to `.env.local` and adjust if either backend runs on a different host/port.

## Admin chat

`/admin` is the creator's chat interface: the model, a tool-call trace, and a confirm-gate dialog before any write touches `data/character.md` or `data/sources.md`. Requires `service/main.py` running in agent mode.
```

- [ ] **Step 4: Typecheck and build**

Run: `cd cookbook-web && npm run typecheck && npm run build`
Expected: both succeed, `/admin` appears in the build output route list.

- [ ] **Step 5: Commit**

```bash
git add cookbook-web/app/admin/page.tsx cookbook-web/.env.local.example cookbook-web/README.md
git commit -m "feat(cookbook-web): assemble the /admin route and document the two backends"
```

---

### Task 11: Manual verification against a running backend

**Files:** none — this task runs the app, no code changes.

**Interfaces:**
- Consumes: the full `/admin` route from Task 10, a running `service/main.py` in agent mode.
- Produces: nothing — a pass/fail record of the golden path, satisfying this repo's "test UI changes in a real browser" norm.

- [ ] **Step 1: Start the backend in agent mode**

Run (from the repo root, a separate terminal): `uvicorn service.main:app --port 8000`
Confirm `config/stack.json` has `"agent": true` — if not, agent-only UI (snapshots, tool calls, confirm-gate) won't appear, and this verification can't cover them.

- [ ] **Step 2: Start `cookbook-web`**

Run: `cd cookbook-web && npm run dev`
Open `http://localhost:3000/admin`.

- [ ] **Step 3: Verify model status and load**

Confirm the sidebar shows "Backend up" and the model name/detail. Click "Load model", confirm it flips to "Unload" once loaded.

- [ ] **Step 4: Verify a plain chat turn**

Send a message with no reason to call a tool (e.g. "hello"). Confirm a reply renders as a bubble, no tool trace appears.

- [ ] **Step 5: Verify a read-tool turn**

Send a message that should trigger `search_sources` (e.g. ask about something specific to the creator's logged answers). Confirm a `tool_call` badge and a collapsible `tool_result` appear above the final answer.

- [ ] **Step 6: Verify the write confirm-gate — Apply**

Prompt the model to log a new fact (triggers `append_source`). Confirm the `ConfirmProposalDialog` opens with Before/After/diff. Click Apply. Confirm: the dialog closes, `[applied: …]` appears in the transcript, and the follow-up phase runs automatically (further tool calls/proposals filing the entry into `character.md` sections, each going through the same dialog).

- [ ] **Step 7: Verify the write confirm-gate — Decline**

Trigger another write proposal. Click Decline. Confirm the dialog closes, `[declined: …]` appears in the transcript, and the model's next reply acknowledges it rather than repeating the write.

- [ ] **Step 8: Verify snapshots**

In the sidebar, confirm at least one snapshot now appears (taken automatically before the Task 6 write). Restore it. Confirm the transcript clears (via `onRestored` → `loop.reset`).

- [ ] **Step 9: Verify `/story`**

In the bottom bar, submit `/story <a short narrative>`. Confirm routing resolves (new/append/amend/duplicate) and, for a non-duplicate result, `ConfirmProposalDialog` opens with the proposed story content.

- [ ] **Step 10: Verify model unload**

Click "Unload" in the sidebar. Confirm status flips back to "Load model".

- [ ] **Step 11: Record the result**

If every step passed, this plan is complete and `cookbook-web/app/admin` is verified equivalent to `web/`'s functionality (styling aside). `web/`'s retirement is a follow-up, not part of this task — do not delete it here.
