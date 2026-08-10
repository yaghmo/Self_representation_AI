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
