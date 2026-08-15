"use client";

import { useState } from "react";
import { useAgentLoop, type GenerationParams } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/admin/ChatPanel";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { Sidebar } from "@/components/admin/Sidebar";
import { StoryBar } from "@/components/admin/StoryBar";

export default function Page() {
  // chat_app.py:283-301 — the sidebar sliders own these, and they are what
  // gets sent to /chat.
  const [generation, setGeneration] = useState<GenerationParams>({
    temperature: 0.7,
    maxTokens: 512,
    thinking: false,
  });
  const loop = useAgentLoop(generation);

  return (
    <div style={{ display: "flex" }}>
      <main style={{ padding: 24, maxWidth: 800, flex: 1 }}>
        <h1>Admin</h1>
        <ChatPanel
          transcript={loop.transcript}
          steps={loop.steps}
          error={loop.error}
          busy={loop.busy}
          onSend={loop.send}
        />
        <StoryBar onProposal={loop.proposeExternal} />
        {loop.pending && (
          <ConfirmDialog proposal={loop.pending} onApply={loop.applyPending} onDecline={loop.declinePending} />
        )}
      </main>
      <Sidebar
        generation={generation}
        onGeneration={(next) => setGeneration((prev) => ({ ...prev, ...next }))}
        onRestored={loop.reset}
      />
    </div>
  );
}
