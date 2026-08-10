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
