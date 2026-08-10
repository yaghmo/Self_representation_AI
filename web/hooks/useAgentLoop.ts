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
  // to `drive()` and never assigned back — chat_app.py:801-802 is the only
  // place Python appends, and it appends one assistant reply.
  const historyRef = useRef<Message[]>([]);
  const seenRef = useRef(new Map<string, number>());
  // chat_app.py:764-767 — once the follow-up phase is open, resuming a call
  // inside it re-offers FOLLOWUP_SCHEMAS, never append_source.
  const followupActiveRef = useRef(false);
  // chat_app.py:175 — a landed story is on disk and indexed, so its turns
  // stop being sent while staying on screen.
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
      // Typing instead of deciding abandons the paused turn and any open
      // phase — mirrors chat_app.py:662-668.
      setPending(null);
      setError(null);
      seenRef.current = new Map();
      followupActiveRef.current = false;
      const userMessage: Message = { role: "user", content: text };
      historyRef.current = [...historyRef.current, userMessage];
      setTranscript((prev) => [...prev, userMessage]);
      // chat_app.py:673-674 — send only what is above the floor.
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
        // what gets resent on later turns, per chat_app.py:167-179.
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
        // and its tool set, have not changed (chat_app.py:766-767).
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

  // A /story proposal arrives fully formed from StoryBar, with no paused
  // tool call in the agent loop to resume — step is null, matching
  // PendingState's modeling of chat_app.py's confirm_dialog.
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
