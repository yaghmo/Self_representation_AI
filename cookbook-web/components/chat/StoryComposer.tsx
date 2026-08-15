"use client";

import { useRef, useState } from "react";
import { Paperclip, Plus, X } from "lucide-react";
import { postConvertFile, postIngest, postStoryPropose, postStoryRoute } from "@/lib/chat/api";
import type { Proposal } from "@/lib/chat/types";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

function parseStoryCommand(text: string): { wantedId: string; wantedEvent: string; rest: string } {
  const match = /^(ST-\d+)(?:\/(E-\d+))?\s*/.exec(text.trim());
  if (!match) return { wantedId: "", wantedEvent: "", rest: text.trim() };
  return { wantedId: match[1], wantedEvent: match[2] ?? "", rest: text.slice(match[0].length).trim() };
}

export function StoryComposer({ onProposal }: { onProposal: (proposal: Proposal) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("");
  const [isError, setIsError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attachedName, setAttachedName] = useState("");
  const [converting, setConverting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // dragenter/dragleave fire on every child boundary crossing, not just the
  // container's — a counter is the standard fix for the flicker that comes
  // from tracking "is something being dragged over me" with a plain boolean.
  const dragDepthRef = useRef(0);

  function fail(message: string) {
    setStatus(message);
    setIsError(true);
  }

  async function handleFile(file: File) {
    setConverting(true);
    setStatus("");
    setIsError(false);
    try {
      const { text } = await postConvertFile(file);
      setDraft((prev) => (prev ? `${prev}\n\n${text}` : text));
      setAttachedName(file.name);
    } catch (exc) {
      fail(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setConverting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function submit() {
    const text = draft.trim();
    if (!text) {
      fail("Paste the narrative first — or ST-001 <addition>, or ST-001/E-001 <rewrite>.");
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
        setAttachedName("");
        setOpen(false);
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
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="outline" size="icon" aria-label="Add a story" title="Add a story" />
        }
      >
        <Plus className="size-4" />
      </DialogTrigger>
      <DialogContent
        className={cn(
          "max-w-xl transition-colors",
          dragging && "outline-2 outline-dashed outline-primary outline-offset-4"
        )}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepthRef.current += 1;
          if (e.dataTransfer.types.includes("Files")) setDragging(true);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
          if (dragDepthRef.current === 0) setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          dragDepthRef.current = 0;
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void handleFile(file);
        }}
      >
        <DialogHeader>
          <DialogTitle>Add a story</DialogTitle>
          <DialogDescription>
            Paste the narrative, or attach a file — doc, PDF, slides, plain
            text, or drag one in — to add it to the story corpus. Prefix with{" "}
            <code>ST-001</code> to add to an existing story, or{" "}
            <code>ST-001/E-001</code> to rewrite one event. This bypasses the
            chat — nothing is written until you confirm the proposal.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Paste a story, or ST-001 <addition>, or ST-001/E-001 <rewrite>…"
          className="min-h-40"
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".md,.markdown,.txt,.docx,.pptx,.xlsx,.odt,.epub,.pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
          }}
        />
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={converting}
            onClick={() => fileInputRef.current?.click()}
          >
            <Paperclip className="size-3.5" />
            {converting ? "Converting…" : "Attach a file"}
          </Button>
          {attachedName && !converting && (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              {attachedName}
              <button
                type="button"
                onClick={() => setAttachedName("")}
                aria-label="Clear attached filename"
                className="hover:text-foreground"
              >
                <X className="size-3" />
              </button>
            </span>
          )}
        </div>
        {status && (
          <p className={isError ? "text-xs text-destructive" : "text-xs text-emerald-600"}>{status}</p>
        )}
        <DialogFooter>
          <Button onClick={submit} disabled={busy}>
            {busy ? "Working…" : "Route it"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
