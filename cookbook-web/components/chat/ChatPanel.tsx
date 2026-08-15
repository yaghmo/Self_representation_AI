"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Bot, Brain, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Message, Proposal, Step } from "@/lib/chat/types";
import { StoryComposer } from "@/components/chat/StoryComposer";
import { HelpDialog } from "@/components/chat/HelpDialog";

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

function TypingIndicator() {
  return (
    <div className="flex h-8 items-center gap-1 pl-11" aria-label="Working" role="status">
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:-0.4s]" />
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:-0.2s]" />
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
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
  onStoryProposal,
  thinking,
  onThinkingChange,
}: {
  transcript: Message[];
  steps: Step[];
  error: string | null;
  busy: boolean;
  onSend: (text: string) => void;
  onStoryProposal: (proposal: Proposal) => void;
  thinking: boolean;
  onThinkingChange: (next: boolean) => void;
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
            <MessageBubble key={i} message={message} />
          ))}
          {steps
            .filter((step) => step.kind !== "answer" && step.kind !== "stopped")
            .map((step, i) => (
              <StepTrace key={i} step={step} />
            ))}
          {busy && <TypingIndicator />}
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
                  variant={thinking ? "default" : "outline"}
                  size="icon"
                  aria-label="Reasoning"
                  aria-pressed={thinking}
                  onClick={() => onThinkingChange(!thinking)}
                />
              }
            >
              <Brain className="size-4" />
            </TooltipTrigger>
            <TooltipContent>
              Reasoning — makes the model think before it answers. Slower, better on
              anything ambiguous or multi-step.
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
            placeholder="Tell it about yourself, or what to do…"
            className="min-h-10 flex-1 resize-none border-0 shadow-none focus-visible:ring-0"
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
