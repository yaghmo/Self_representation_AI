"use client";

import { useEffect, useState } from "react";
import { getHealth, getModelStatus } from "@/lib/api";
import { useAgentLoop } from "@/hooks/useAgentLoop";
import { ChatPanel } from "@/components/ChatPanel";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export default function Page() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loop = useAgentLoop({ temperature: 0.7, maxTokens: 512, thinking: false });

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e)));
    getModelStatus().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  if (error) return <pre>Backend unreachable: {error}</pre>;

  return (
    <main style={{ padding: 24, maxWidth: 800 }}>
      <h1>Admin</h1>
      <p>health: {health ? JSON.stringify(health) : "loading..."}</p>
      <p>model: {status ? JSON.stringify(status) : "loading..."}</p>
      <ChatPanel transcript={loop.transcript} steps={loop.steps} onSend={loop.send} />
      {loop.pending && (
        <ConfirmDialog proposal={loop.pending} onApply={loop.applyPending} onDecline={loop.declinePending} />
      )}
    </main>
  );
}
