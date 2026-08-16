"use client";

import { useState } from "react";
import { generateBio, saveBio } from "@/lib/admin/socialApi";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function BioSection({
  bio,
  onSaved,
}: {
  bio: string | null;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setBusy(true);
    setError(null);
    try {
      const result = await generateBio();
      setDraft(result.bio);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (draft === null) return;
    setBusy(true);
    setError(null);
    try {
      await saveBio(draft);
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
      <p className="text-sm font-medium">Bio</p>
      {draft === null ? (
        <>
          <p className="text-xs text-muted-foreground">{bio || "no bio yet."}</p>
          <Button variant="outline" size="sm" onClick={handleGenerate} disabled={busy}>
            {busy ? "Generating…" : "Generate"}
          </Button>
        </>
      ) : (
        <>
          <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
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
