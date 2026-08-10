"use client";

import { useAgentLoop } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/ChatPanel";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Sidebar } from "@/components/Sidebar";

export default function Page() {
  const loop = useAgentLoop({ temperature: 0.7, maxTokens: 512, thinking: false });

  return (
    <div style={{ display: "flex" }}>
      <main style={{ padding: 24, maxWidth: 800, flex: 1 }}>
        <h1>Admin</h1>
        <ChatPanel transcript={loop.transcript} steps={loop.steps} onSend={loop.send} />
        {loop.pending && (
          <ConfirmDialog proposal={loop.pending} onApply={loop.applyPending} onDecline={loop.declinePending} />
        )}
      </main>
      <Sidebar onRestored={loop.reset} />
    </div>
  );
}
