"use client";

import { useState } from "react";
import type { Message, Step } from "@/lib/types";

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
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {error && <p style={{ color: "red" }}>{error}</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {transcript.map((message, i) => (
          <div key={i}>
            <strong>{message.role}: </strong>
            {message.content}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {steps
          .filter((step) => step.kind !== "answer" && step.kind !== "stopped")
          .map((step, i) => (
            <StepView key={i} step={step} />
          ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="Say something (use the /story bar below to log a story)"
          style={{ flex: 1 }}
        />
        <button onClick={submit} disabled={busy}>
          {busy ? "Working..." : "Send"}
        </button>
      </div>
    </div>
  );
}

function StepView({ step }: { step: Step }) {
  switch (step.kind) {
    case "tool_call":
      return <div style={{ color: "#666" }}>{step.name}({step.text})</div>;
    case "tool_result":
      return (
        <details>
          <summary>{step.name} result</summary>
          <pre>{step.text}</pre>
        </details>
      );
    case "proposal":
      return <div style={{ color: "#a60" }}>{step.text}</div>;
    case "stopped":
      return <div style={{ color: "red" }}>{step.text}</div>;
    default:
      return null;
  }
}
