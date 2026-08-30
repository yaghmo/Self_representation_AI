"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown, Mail } from "lucide-react"
import { cn } from "@/lib/utils"
import { PlayOnceVideo, type PlayOnceVideoHandle } from "@/components/media/PlayOnceVideo"
import { introAlreadySeen, isVideo, markIntroSeen } from "@/lib/introSplash"
import type { FanProfile } from "./types"

const PFP_REPLAY_INTERVAL_MS = 60_000
const INTRO_PFP_SIZE = 320
const INTRO_TRANSITION_MS = 700

const BANNER_HEIGHT = 420
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
  const dockedPfpSize = expanded ? EXPANDED_PFP : COMPACT_PFP
  const nameSize = expanded ? 1.75 : 1.25
  const marginPercent = expanded ? EXPANDED_MARGIN_PERCENT : COMPACT_MARGIN_PERCENT
  // The landing hero gets its own uploaded asset (often a clip) instead of
  // reusing the docked pfp — falls back to the regular pfp when unset.
  const showingLandingHero = expanded && !!profile.landingPfpUrl
  const heroUrl = showingLandingHero ? profile.landingPfpUrl : profile.pfpUrl
  const heroMime = showingLandingHero ? profile.landingPfpMime : profile.pfpMime
  const pfpVideoRef = useRef<PlayOnceVideoHandle>(null)
  const bannerVideoRef = useRef<PlayOnceVideoHandle>(null)
  const bannerIsVideo = isVideo(profile.bannerMime)

  const introEligible = showingLandingHero && isVideo(heroMime)
  const [showIntro, setShowIntro] = useState(false)
  const [introShrinking, setIntroShrinking] = useState(false)

  // Decided once, on mount: a video hero that hasn't been seen before gets
  // the full-screen intro; everything else renders normally, same as today.
  useEffect(() => {
    if (!introEligible || introAlreadySeen()) return
    markIntroSeen()
    setShowIntro(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally mount-only
  }, [])

  function handleIntroEnd() {
    setIntroShrinking(true)
    setTimeout(() => {
      setShowIntro(false)
      // The docked pfp/banner have been autoplaying behind the overlay the
      // whole time and are likely already frozen on their last frame —
      // replay them so the reveal looks like they're starting fresh.
      pfpVideoRef.current?.replay()
      bannerVideoRef.current?.replay()
    }, INTRO_TRANSITION_MS)
  }

  // Only the main pfp (not the landing hero) auto-replays — it plays once
  // on mount like any other slot, then re-triggers itself on a timer so a
  // gif/clip pfp isn't frozen after the first play.
  useEffect(() => {
    if (showingLandingHero || !isVideo(heroMime)) return
    const id = setInterval(() => pfpVideoRef.current?.replay(), PFP_REPLAY_INTERVAL_MS)
    return () => clearInterval(id)
  }, [showingLandingHero, heroMime])

  return (
    <header className="relative">
      <div
        className="overflow-hidden rounded-3xl bg-gradient-to-r from-primary/40 via-accent to-primary/20 transition-[height,margin] duration-500 ease-out"
        style={{ height: BANNER_HEIGHT, marginInline: `${marginPercent}%` }}
      >
        {profile.bannerUrl && (
          bannerIsVideo ? (
            <PlayOnceVideo
              ref={bannerVideoRef}
              src={profile.bannerUrl}
              className="size-full object-cover"
            />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- served from our own service, not a next/image remote host
            <img src={profile.bannerUrl} alt="" className="size-full object-cover" />
          )
        )}
      </div>
      <div
        className={cn(
          "relative flex flex-col gap-3 transition-[padding] duration-500 ease-out",
          expanded ? "items-center text-center" : "items-start text-left"
        )}
        style={{ marginTop: -dockedPfpSize / 2, paddingInline: `${marginPercent}%` }}
      >
        <div
          className="shrink-0 overflow-hidden rounded-full border-4 border-background bg-muted transition-[width,height] duration-500 ease-out"
          style={{ width: dockedPfpSize, height: dockedPfpSize }}
        >
          {heroUrl && (
            isVideo(heroMime) ? (
              <PlayOnceVideo
                ref={pfpVideoRef}
                src={heroUrl}
                className="size-full object-cover"
              />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element -- served from our own service, not a next/image remote host
              <img src={heroUrl} alt="" className="size-full object-cover" />
            )
          )}
        </div>
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
          {profile.contactEmail && (
            <a
              href={`mailto:${profile.contactEmail}`}
              className="mt-2 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
            >
              <Mail className="size-3.5 shrink-0" />
              {profile.contactEmail}
            </a>
          )}
        </div>
      </div>

      {showIntro && heroUrl && (
        <div
          className={cn(
            "fixed inset-0 z-50 flex items-center justify-center bg-black transition-all ease-out",
            introShrinking ? "scale-0 opacity-0" : "scale-100 opacity-100"
          )}
          style={{ transitionDuration: `${INTRO_TRANSITION_MS}ms` }}
        >
          <PlayOnceVideo
            src={heroUrl}
            className="rounded-full object-cover"
            style={{ width: INTRO_PFP_SIZE, height: INTRO_PFP_SIZE }}
            onEnded={handleIntroEnd}
          />
        </div>
      )}

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
