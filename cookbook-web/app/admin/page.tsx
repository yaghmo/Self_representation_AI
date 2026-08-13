"use client";

import { useState } from "react";
import { useAgentLoop, type GenerationParams } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ConfirmProposalDialog } from "@/components/chat/ConfirmProposalDialog";
import { ModelSidebar } from "@/components/chat/ModelSidebar";
import { StoryComposer } from "@/components/chat/StoryComposer";

export default function AdminPage() {
  const [generation, setGeneration] = useState<GenerationParams>({
    temperature: 0.7,
    maxTokens: 512,
    thinking: false,
  });
  const loop = useAgentLoop(generation);

  return (
    <div className="flex h-screen">
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="border-b px-6 py-3">
          <h1 className="text-sm font-semibold">Admin</h1>
        </header>
        <div className="flex-1 overflow-hidden">
          <ChatPanel
            transcript={loop.transcript}
            steps={loop.steps}
            error={loop.error}
            busy={loop.busy}
            onSend={loop.send}
          />
        </div>
        <StoryComposer onProposal={loop.proposeExternal} />
      </div>
      <ModelSidebar
        generation={generation}
        onGeneration={(next) => setGeneration((prev) => ({ ...prev, ...next }))}
        onRestored={loop.reset}
      />
      {loop.pending && (
        <ConfirmProposalDialog
          proposal={loop.pending}
          onApply={loop.applyPending}
          onDecline={loop.declinePending}
        />
      )}
    </div>
  );
}
