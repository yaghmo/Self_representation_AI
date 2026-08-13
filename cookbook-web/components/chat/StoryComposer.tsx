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
