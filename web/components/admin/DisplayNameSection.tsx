"use client";

import { useState } from "react";
import { saveDisplayName } from "@/lib/admin/socialApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function DisplayNameSection({
  displayName,
  onSaved,
}: {
  displayName: string | null;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleEdit() {
    setDraft(displayName ?? "");
  }

  async function handleConfirm() {
    if (draft === null) return;
    setBusy(true);
    setError(null);
    try {
      await saveDisplayName(draft.trim() || null);
      setDraft(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Name</p>
      {draft === null ? (
        <>
          <p className="text-xs text-muted-foreground">{displayName || "no name set yet."}</p>
          <Button variant="outline" size="sm" onClick={handleEdit} disabled={busy}>
            Update
          </Button>
        </>
      ) : (
        <>
          <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Display name" />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleConfirm} disabled={busy}>
              Confirm
            </Button>
            <Button variant="outline" size="sm" onClick={() => setDraft(null)} disabled={busy}>
              Cancel
            </Button>
          </div>
        </>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
