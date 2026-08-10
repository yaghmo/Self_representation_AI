"use client";

import { useCallback, useEffect, useState } from "react";
import { getHealth, getModelStatus, getSnapshots, loadModel, postSnapshotRestore, unloadModel } from "@/lib/api";
import type { GenerationParams } from "@/hooks/useAgentLoop";
import type { HealthStatus, ModelStatus } from "@/lib/types";

export function Sidebar({
  generation,
  onGeneration,
  onRestored,
}: {
  generation: GenerationParams;
  onGeneration: (next: Partial<GenerationParams>) => void;
  onRestored: () => void;
}) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [snapshots, setSnapshots] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [refresh]);

  async function handleLoad() {
    setLoading(true);
    setError(null);
    try {
      await loadModel();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleUnload() {
    setError(null);
    try {
      await unloadModel();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRestore() {
    if (!selected) return;
    setError(null);
    try {
      await postSnapshotRestore(selected);
      await refresh();
      onRestored();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <aside style={{ width: 260, padding: 16, borderLeft: "1px solid #ddd" }}>
      <h3>Service</h3>
      {error && <p style={{ color: "red" }}>{error}</p>}
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

      <h3>Generation</h3>
      <label style={{ display: "block" }}>
        Temperature: {generation.temperature.toFixed(2)}
        <input
          type="range"
          min={0}
          max={1.5}
          step={0.05}
          value={generation.temperature}
          onChange={(e) => onGeneration({ temperature: Number(e.target.value) })}
          style={{ width: "100%" }}
        />
      </label>
      <label style={{ display: "block" }}>
        Max tokens: {generation.maxTokens}
        <input
          type="range"
          min={64}
          max={2048}
          step={64}
          value={generation.maxTokens}
          onChange={(e) => onGeneration({ maxTokens: Number(e.target.value) })}
          style={{ width: "100%" }}
        />
      </label>
      <label style={{ display: "block" }}>
        <input
          type="checkbox"
          checked={generation.thinking}
          onChange={(e) => onGeneration({ thinking: e.target.checked })}
        />{" "}
        Reasoning
      </label>

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
