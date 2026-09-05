"use client";

import { useEffect, useState } from "react";
import { Settings } from "lucide-react";
import { useAgentLoop, type GenerationParams } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { ConfirmProposalDialog } from "@/components/chat/ConfirmProposalDialog";
import { ModelSidebar } from "@/components/chat/ModelSidebar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import CookbookPage from "@/components/CookbookPage";
import { getSocials, chatIconUrl } from "@/lib/admin/socialApi";
import { isVideo } from "@/lib/introSplash";

export default function AdminPage() {
  const [generation, setGeneration] = useState<GenerationParams>({
    temperature: 0.7,
    maxTokens: 512,
    thinking: false,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatIconSrc, setChatIconSrc] = useState<string | null>(null);
  // Reasoning is a llama.cpp-only extension (chat_template_kwargs /
  // reasoning_reserve in runtime/backend.py's LocalBackend) — ApiBackend
  // ignores it entirely, so the toggle does nothing on an API-backed model.
  const [thinkingAvailable, setThinkingAvailable] = useState(true);
  const loop = useAgentLoop(generation);

  // Same chat-avatar slot the fan widget reads — a video icon is the fan
  // page's cinematic touch, not appropriate for a small per-message avatar
  // here, so only a static image counts.
  useEffect(() => {
    getSocials()
      .then((res) => {
        if (res.chatIconVersion != null && !isVideo(res.chatIconMime)) {
          setChatIconSrc(chatIconUrl(res.chatIconVersion));
        }
      })
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-screen">
      <ModelSidebar
        generation={generation}
        onGeneration={(next) => setGeneration((prev) => ({ ...prev, ...next }))}
        onRestored={loop.reset}
        onStatus={(status) => {
          const local = status.source !== "api";
          setThinkingAvailable(local);
          if (!local) setGeneration((prev) => ({ ...prev, thinking: false }));
        }}
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
            thinkingAvailable={thinkingAvailable}
            chatIconSrc={chatIconSrc}
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
