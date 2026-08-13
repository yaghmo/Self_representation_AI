"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getHealth,
  getModelStatus,
  getSnapshots,
  loadModel,
  postSnapshotRestore,
  unloadModel,
} from "@/lib/chat/api";
import type { GenerationParams } from "@/hooks/useAgentLoop";
import type { HealthStatus, ModelStatus } from "@/lib/chat/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";

export function ModelSidebar({
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
    <aside className="flex w-80 shrink-0 flex-col gap-4 overflow-y-auto border-l bg-muted/30 p-4">
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Model</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Badge variant={health?.status === "ok" ? "default" : "destructive"}>
            {health ? (health.status === "ok" ? "Backend up" : health.status) : "…"}
          </Badge>
          {status?.name && <p className="text-sm font-medium">{status.name}</p>}
          {status?.detail && <p className="text-xs text-muted-foreground">{status.detail}</p>}
          {health?.model_loaded ? (
            <Button variant="outline" size="sm" className="w-full" onClick={handleUnload}>
              Unload
            </Button>
          ) : (
            <Button size="sm" className="w-full" onClick={handleLoad} disabled={loading}>
              {loading ? "Loading…" : "Load model"}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Generation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Temperature</span>
              <span>{generation.temperature.toFixed(2)}</span>
            </div>
            <Slider
              min={0}
              max={1.5}
              step={0.05}
              value={[generation.temperature]}
              onValueChange={(v) => Array.isArray(v) && onGeneration({ temperature: v[0] })}
            />
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Max tokens</span>
              <span>{generation.maxTokens}</span>
            </div>
            <Slider
              min={64}
              max={2048}
              step={64}
              value={[generation.maxTokens]}
              onValueChange={(v) => Array.isArray(v) && onGeneration({ maxTokens: v[0] })}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="thinking"
              checked={generation.thinking}
              onCheckedChange={(checked) => onGeneration({ thinking: checked === true })}
            />
            <Label htmlFor="thinking" className="text-sm font-normal">
              Reasoning
            </Label>
          </div>
        </CardContent>
      </Card>

      {status?.agent && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Snapshots</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {snapshots.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No snapshots yet — one is taken before every write.
              </p>
            ) : (
              <>
                <Select value={selected} onValueChange={(v) => v !== null && setSelected(v)}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Choose a snapshot" />
                  </SelectTrigger>
                  <SelectContent>
                    {snapshots.map((name) => (
                      <SelectItem key={name} value={name}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button variant="outline" size="sm" className="w-full" onClick={handleRestore}>
                  Restore
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Separator />
      <p className="text-xs text-muted-foreground">
        Writes to the character profile always pause for your confirmation.
      </p>
    </aside>
  );
}
