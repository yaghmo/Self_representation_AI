"use client";

import type { Proposal } from "@/lib/admin/types";

export function ConfirmDialog({
  proposal,
  onApply,
  onDecline,
}: {
  proposal: Proposal;
  onApply: () => void;
  onDecline: () => void;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div style={{ background: "white", color: "#111", padding: 24, maxWidth: 900, width: "90%", maxHeight: "80vh", overflow: "auto" }}>
        <h2>Confirm this change</h2>
        <p>{proposal.summary} — nothing has been written yet.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <strong>Before</strong>
            <pre>{proposal.before || "new — nothing is being replaced"}</pre>
          </div>
          <div>
            <strong>After</strong>
            <pre>{proposal.after}</pre>
          </div>
        </div>
        <details>
          <summary>Unified diff</summary>
          <pre>{proposal.diff}</pre>
        </details>
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button onClick={onApply}>Apply</button>
          <button onClick={onDecline}>Decline</button>
        </div>
      </div>
    </div>
  );
}
