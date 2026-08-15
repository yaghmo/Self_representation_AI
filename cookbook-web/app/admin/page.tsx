"use client";

import { useState } from "react";
import { Settings } from "lucide-react";
import { useAgentLoop, type GenerationParams } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ConfirmProposalDialog } from "@/components/chat/ConfirmProposalDialog";
import { ModelSidebar } from "@/components/chat/ModelSidebar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import CookbookPage from "@/components/CookbookPage";

export default function AdminPage() {
  const [generation, setGeneration] = useState<GenerationParams>({
    temperature: 0.7,
    maxTokens: 512,
    thinking: false,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const loop = useAgentLoop(generation);

  return (
    <div className="flex h-screen">
      <ModelSidebar
        generation={generation}
        onGeneration={(next) => setGeneration((prev) => ({ ...prev, ...next }))}
        onRestored={loop.reset}
      />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <h1 className="text-sm font-semibold">Admin</h1>
          <Button
            variant="outline"
            size="icon"
            aria-label="Settings — reconfigure the stack"
            title="Settings — reconfigure the stack"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings className="size-4" />
          </Button>
        </header>
        <div className="flex-1 overflow-hidden">
          <ChatPanel
            transcript={loop.transcript}
            steps={loop.steps}
            error={loop.error}
            busy={loop.busy}
            onSend={loop.send}
            onStoryProposal={loop.proposeExternal}
            thinking={generation.thinking}
            onThinkingChange={(next) => setGeneration((prev) => ({ ...prev, thinking: next }))}
          />
        </div>
      </div>
      {loop.pending && (
        <ConfirmProposalDialog
          proposal={loop.pending}
          onApply={loop.applyPending}
          onDecline={loop.declinePending}
        />
      )}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent
          className="max-h-[90vh] w-[95vw] max-w-5xl overflow-y-auto sm:max-w-5xl"
          showCloseButton={false}
        >
          <DialogTitle className="sr-only">Settings</DialogTitle>
          <CookbookPage onCancel={() => setSettingsOpen(false)} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
