"use client"

import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import type { FanProfile } from "./types"

const EXPANDED_BANNER = 420
const COMPACT_BANNER = 208
const EXPANDED_PFP = 176
const COMPACT_PFP = 112
const EXPANDED_MARGIN_PERCENT = 10
const COMPACT_MARGIN_PERCENT = 4

function ProfileHeader({
  profile,
  expanded,
  onCollapse,
}: {
  profile: FanProfile
  expanded: boolean
  onCollapse: () => void
}) {
  const bannerHeight = expanded ? EXPANDED_BANNER : COMPACT_BANNER
  const pfpSize = expanded ? EXPANDED_PFP : COMPACT_PFP
  const nameSize = expanded ? 1.75 : 1.25
  const marginPercent = expanded ? EXPANDED_MARGIN_PERCENT : COMPACT_MARGIN_PERCENT

  return (
    <header className="relative">
      <div
        className="rounded-3xl bg-gradient-to-r from-primary/40 via-accent to-primary/20 transition-[height,margin] duration-500 ease-out"
        style={{ height: bannerHeight, marginInline: `${marginPercent}%` }}
      />
      <div
        className={cn(
          "relative flex flex-col gap-3 transition-[padding] duration-500 ease-out",
          expanded ? "items-center text-center" : "items-start text-left"
        )}
        style={{ marginTop: -pfpSize / 2, paddingInline: `${marginPercent}%` }}
      >
        <div
          className="shrink-0 rounded-full border-4 border-background bg-muted transition-[width,height] duration-500 ease-out"
          style={{ width: pfpSize, height: pfpSize }}
        />
        <div>
          <h1
            className="font-semibold transition-[font-size] duration-500 ease-out"
            style={{ fontSize: `${nameSize}rem` }}
          >
            {profile.name}
          </h1>
          <p className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground sm:text-base">
            {profile.bio}
          </p>
        </div>
      </div>

      {expanded && (
        <button
          type="button"
          onClick={onCollapse}
          aria-label="Scroll down"
          className="group fixed inset-x-0 bottom-20 z-30 flex flex-col-reverse items-center gap-1"
        >
          <ChevronDown className="size-6 animate-bounce text-muted-foreground transition-colors group-hover:text-primary" />
          <span className="text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
            Click to see more
          </span>
        </button>
      )}
    </header>
  )
}

export { ProfileHeader }
