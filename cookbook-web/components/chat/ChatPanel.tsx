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
      <ScrollArea className="min-h-0 flex-1 px-6 py-4">
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
