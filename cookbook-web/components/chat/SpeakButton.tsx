"use client"

import { useSyncExternalStore } from "react"
import { Pause, Volume2 } from "lucide-react"
import { getStatus, isPlaying, pause, play, subscribe } from "@/lib/voice/store"

// Warming happens elsewhere (store.warm(), fired once a bubble's text is
// final) — this button only renders once that finishes, per the "appears
// once generation is done" design. No loading spinner: nothing to show
// while there's nothing to click yet.
export function SpeakButton({ id }: { id: string }) {
  const status = useSyncExternalStore(subscribe, () => getStatus(id))
  const playing = useSyncExternalStore(subscribe, () => isPlaying(id))

  if (status !== "ready") return null

  return (
    <button
      type="button"
      onClick={() => (playing ? pause(id) : play(id))}
      aria-label={playing ? "Playing" : "Play voice"}
      className="mt-1 text-muted-foreground/70 hover:text-foreground"
    >
      {playing ? <Pause className="size-3.5" /> : <Volume2 className="size-3.5" />}
    </button>
  )
}
