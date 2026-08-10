"use client";

import { useCallback, useEffect, useState } from "react";
import { getHealth, getModelStatus, getSnapshots, loadModel, postSnapshotRestore, unloadModel } from "@/lib/api";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export function Sidebar({ onRestored }: { onRestored: () => void }) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    const [h, s] = await Promise.all([getHealth(), getModelStatus()]);
    setHealth(h);
    setStatus(s);
    if (s.agent) {
      const snap = await getSnapshots();
      setSnapshots(snap.snapshots);
      setSelected((prev) => prev || snap.snapshots[0] || "");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleLoad() {
    setLoading(true);
    try {
      await loadModel();
      await refresh();
    } finally {
      setLoading(false);
    }
  }

  async function handleUnload() {
    await unloadModel();
    await refresh();
  }

  async function handleRestore() {
    if (!selected) return;
    await postSnapshotRestore(selected);
    await refresh();
    onRestored();
  }

  return (
    <aside style={{ width: 260, padding: 16, borderLeft: "1px solid #ddd" }}>
      <h3>Service</h3>
      {health ? <p>{health.status === "ok" ? "Backend up" : health.status}</p> : <p>...</p>}

      <h3>Model</h3>
      {status?.name && <p>{status.name}</p>}
      {status?.detail && <p>{status.detail}</p>}
      {health?.model_loaded ? (
        <button onClick={handleUnload}>Unload</button>
      ) : (
        <button onClick={handleLoad} disabled={loading}>
          {loading ? "Loading..." : "Load model"}
        </button>
      )}

      {status?.agent && (
        <>
          <h3>Snapshots</h3>
          {snapshots.length === 0 ? (
            <p>No snapshots yet — one is taken before every write.</p>
          ) : (
            <>
              <select value={selected} onChange={(e) => setSelected(e.target.value)}>
                {snapshots.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button onClick={handleRestore}>Restore</button>
            </>
          )}
        </>
      )}
    </aside>
  );
}
