"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { Proposal } from "@/lib/chat/types";

export function ConfirmProposalDialog({
  proposal,
  onApply,
  onDecline,
}: {
  proposal: Proposal;
  onApply: () => void;
  onDecline: () => void;
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && onDecline()}>
      <DialogContent className="max-h-[92vh] w-[95vw] max-w-5xl overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Confirm this change</DialogTitle>
          <DialogDescription>{proposal.summary} — nothing has been written yet.</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="mb-1 text-sm font-medium">Before</p>
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs">
              {proposal.before || "new — nothing is being replaced"}
            </pre>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">After</p>
            <pre className="max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs">
              {proposal.after}
            </pre>
          </div>
        </div>
        <details>
          <summary className="cursor-pointer text-sm text-muted-foreground">Unified diff</summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md border bg-muted p-3 text-xs">
            {proposal.diff}
          </pre>
        </details>
        <DialogFooter>
          <Button variant="outline" onClick={onDecline}>
            Decline
          </Button>
          <Button onClick={onApply}>Apply</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
