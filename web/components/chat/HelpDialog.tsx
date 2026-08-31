"use client";

import { HelpCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

export function HelpDialog() {
  return (
    <Dialog>
      <DialogTrigger
        render={<Button variant="outline" size="icon" aria-label="Help" title="Help" />}
      >
        <HelpCircle className="size-4" />
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>What this agent does</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm text-muted-foreground">
          <p>
            Tell it about yourself in plain language and it logs a new source,
            checks the profile for what&apos;s already recorded, or updates a
            section — say what you want.
          </p>
          <p>
            <span className="font-medium text-foreground">Every write pauses for confirmation.</span>{" "}
            Nothing touches <code>character.md</code> or <code>sources.md</code>{" "}
            until you approve the before/after diff.
          </p>
          <p>
            <span className="font-medium text-foreground">+</span> pastes a
            longer narrative, or attaches a file (doc, PDF, slides, text),
            straight into the story corpus — bypasses chat, nothing is
            written until you confirm.
          </p>
          <p>
            <span className="font-medium text-foreground">The brain icon</span>{" "}
            turns reasoning on — the model thinks before it answers. Slower,
            but better on anything ambiguous or multi-step; leave it off for
            quick, ordinary turns.
          </p>
          <p>
            The sidebar controls generation (temperature, max tokens), the
            loaded model, your voice sample, and snapshots — every write
            takes one automatically, restorable from there.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
