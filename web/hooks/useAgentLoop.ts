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
