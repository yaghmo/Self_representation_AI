"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Bot, Brain, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Message, Proposal, Step } from "@/lib/chat/types";
import { StoryComposer } from "@/components/chat/StoryComposer";
import { HelpDialog } from "@/components/chat/HelpDialog";
import { MarkdownMessage } from "@/components/chat/Markdown";

function MessageBubble({ message, chatIconSrc }: { message: Message; chatIconSrc: string | null }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted">
        {isUser ? (
          <User className="h-4 w-4" />
        ) : chatIconSrc ? (
          // eslint-disable-next-line @next/next/no-img-element -- proxied, arbitrary-origin image, same as SocialRow's
          <img src={chatIconSrc} alt="" className="h-full w-full object-cover" />
        ) : (
          <Bot className="h-4 w-4" />
        )}
      </div>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2 text-sm",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        )}
      >
        <MarkdownMessage text={message.content} />
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex h-8 items-center gap-1 pl-11" aria-label="Working" role="status">
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:-0.4s]" />
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:-0.2s]" />
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
    </div>
  );
}

// Plain, non-technical status text — the tool name and raw JSON args/result
// are implementation detail an audience member (or the creator, mid-chat)
// doesn't need to see. Same idea as ChatGPT's "Searching…" line.
const TOOL_LABELS: Record<string, string> = {
  search_sources: "Looking through what you've told it before…",
  read_profile_section: "Checking the profile…",
  append_source: "Logging a note…",
  add_profile_line: "Updating the profile…",
  replace_profile_line: "Updating the profile…",
  remove_profile_line: "Removing something from the profile…",
};

// One line, replaced in place as the turn progresses — not a growing list of
// every step a multi-step agent turn took.
function ToolStatusLine({ text }: { text: string }) {
  return (
    <div className="flex h-8 items-center gap-2 pl-11 text-xs text-muted-foreground">
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
      {text}
    </div>
  );
}

function StepTrace({ step }: { step: Step }) {
  switch (step.kind) {
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
  onStoryProposal,
  thinking,
  onThinkingChange,
  thinkingAvailable = true,
  chatIconSrc = null,
}: {
  transcript: Message[];
  steps: Step[];
  error: string | null;
  busy: boolean;
  onSend: (text: string) => void;
  onStoryProposal: (proposal: Proposal) => void;
  thinking: boolean;
  onThinkingChange: (next: boolean) => void;
  // False on an API-backed model — reasoning is a llama.cpp-only extension,
  // and the toggle does nothing there. Defaults true (local).
  thinkingAvailable?: boolean;
  // Creator's set chat avatar (same slot the fan widget uses) — falls back
  // to the plain Bot icon when nothing's set, same as the fan side.
  chatIconSrc?: string | null;
}) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [transcript, steps, busy]);

  function submit() {
    if (busy) return; // one turn at a time — concurrent drives interleave history writes
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    onSend(text);
  }

  return (
    <div className="flex h-full flex-col">
      <ScrollArea className="min-h-0 flex-1 px-6 py-4 focus-visible:outline-none [&_[data-slot=scroll-area-viewport]]:focus-visible:ring-0 [&_[data-slot=scroll-area-viewport]]:focus-visible:outline-none">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {transcript.length === 0 && steps.length === 0 && !busy && (
            <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
              <Bot className="h-8 w-8" />
              <p className="text-sm font-medium text-foreground">The agent is waiting for instructions</p>
              <p className="max-w-sm text-xs">
                Tell it about yourself to log a new source, ask it to update or check the
                profile, or paste a story to add to the corpus. Every write pauses for your
                confirmation before anything is saved.
              </p>
            </div>
          )}
          {transcript.map((message, i) => (
            <MessageBubble key={i} message={message} chatIconSrc={chatIconSrc} />
          ))}
          {steps
            .filter((step) => step.kind === "proposal" || step.kind === "stopped")
            .map((step, i) => (
              <StepTrace key={i} step={step} />
            ))}
          {busy &&
            (() => {
              const latestCall = [...steps].reverse().find((step) => step.kind === "tool_call");
              return latestCall ? (
                <ToolStatusLine text={TOOL_LABELS[latestCall.name] ?? "Working on it…"} />
              ) : (
                <TypingIndicator />
              );
            })()}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
      <div className="mx-auto w-full max-w-2xl px-6 pb-4">
        {error && (
          <Alert variant="destructive" className="mb-2">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex items-center gap-2 rounded-2xl border bg-background p-2 shadow-sm">
          <StoryComposer onProposal={onStoryProposal} />
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant={thinking && thinkingAvailable ? "default" : "outline"}
                  size="icon"
                  disabled={!thinkingAvailable}
                  aria-label="Reasoning"
                  aria-pressed={thinking && thinkingAvailable}
                  onClick={() => onThinkingChange(!thinking)}
                />
              }
            >
              <Brain className="size-4" />
            </TooltipTrigger>
            <TooltipContent>
              {thinkingAvailable
                ? "Reasoning — makes the model think before it answers. Slower, better on anything ambiguous or multi-step."
                : "Reasoning only works on a local model — this one's API-backed."}
            </TooltipContent>
          </Tooltip>
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="Tell it about yourself, or ask it to check the profile…"
            className="min-h-10 flex-1 resize-none border-0 py-2.5 shadow-none focus-visible:ring-0"
          />
          <Button
            onClick={submit}
            disabled={busy || !draft.trim()}
            size="icon"
            aria-label={busy ? "Working…" : "Send"}
          >
            <ArrowUp className="size-4" />
          </Button>
          <HelpDialog />
        </div>
      </div>
    </div>
  );
}
