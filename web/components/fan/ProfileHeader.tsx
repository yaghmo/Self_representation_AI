"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown, Mail } from "lucide-react"
import { cn } from "@/lib/utils"
import { PlayOnceVideo, type PlayOnceVideoHandle } from "@/components/media/PlayOnceVideo"
import { isVideo } from "@/lib/introSplash"
import type { FanProfile } from "./types"

const PFP_REPLAY_INTERVAL_MS = 60_000
const INTRO_TRANSITION_MS = 900
const INTRO_PFP_SIZE = "min(85vmin, 900px)"
const INTRO_PFP_RADIUS = `calc(${INTRO_PFP_SIZE} / 2)`

// Punches a circular hole through an otherwise-solid black panel: black
// (opaque, panel visible) everywhere outside the circle, transparent
// (panel hidden, real content shows through) inside it.
function introMask(centerY: "0%" | "100%"): string {
  return `radial-gradient(circle at 50% ${centerY}, transparent calc(${INTRO_PFP_RADIUS} - 1px), black ${INTRO_PFP_RADIUS})`
}

const BANNER_HEIGHT = 420
const EXPANDED_PFP = 176
const COMPACT_PFP = 112
const EXPANDED_MARGIN_PERCENT = 10
const COMPACT_MARGIN_PERCENT = 4

function ProfileHeader({
  profile,
  expanded,
  introPlaying = false,
  onIntroEnded,
  onCollapse,
}: {
  profile: FanProfile
  expanded: boolean
  introPlaying?: boolean
  onIntroEnded?: () => void
  onCollapse: () => void
}) {
  const dockedPfpSize = expanded ? EXPANDED_PFP : COMPACT_PFP
  const nameSize = expanded ? 1.75 : 1.25
  const marginPercent = expanded ? EXPANDED_MARGIN_PERCENT : COMPACT_MARGIN_PERCENT
  const pfpVideoRef = useRef<PlayOnceVideoHandle>(null)
  const bannerVideoRef = useRef<PlayOnceVideoHandle>(null)
  const bannerIsVideo = isVideo(profile.bannerMime)

  // Splits the full-screen intro apart (top half up, bottom half down, like
  // a visor opening) before actually ending it, instead of popping straight
  // to the normal layout the instant the video finishes.
  const [shrinking, setShrinking] = useState(false)

  function handleIntroEnd() {
    setShrinking(true)
    setTimeout(() => {
      setShrinking(false)
      onIntroEnded?.()
      // The docked pfp/banner have been autoplaying behind the overlay the
      // whole time and are likely already frozen on their last frame —
      // replay them so the reveal looks like they're starting fresh.
      pfpVideoRef.current?.replay()
      bannerVideoRef.current?.replay()
    }, INTRO_TRANSITION_MS)
  }

  // The docked pfp auto-replays on a timer so a gif/clip pfp isn't frozen
  // after the first play.
  useEffect(() => {
    if (!isVideo(profile.pfpMime)) return
    const id = setInterval(() => pfpVideoRef.current?.replay(), PFP_REPLAY_INTERVAL_MS)
    return () => clearInterval(id)
  }, [profile.pfpMime])

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
              // Forces its own GPU compositing layer — a clipped (rounded,
              // overflow-hidden) <video> otherwise falls off the hardware
              // decode path onto software compositing in some browsers,
              // which shows up as visible stutter at this size even though
              // the same file plays smoothly outside the browser.
              className="size-full object-cover [transform:translateZ(0)]"
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
          {profile.pfpUrl && (
            isVideo(profile.pfpMime) ? (
              <PlayOnceVideo ref={pfpVideoRef} src={profile.pfpUrl} className="size-full object-cover" />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element -- served from our own service, not a next/image remote host
              <img src={profile.pfpUrl} alt="" className="size-full object-cover" />
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

      {introPlaying && profile.landingPfpUrl && (
        <>
          {/* One real video, decoded once — two independently-playing
              copies of the same clip drift out of sync within seconds. It
              sits centered and completely still; the two black panels each
              have a circular hole (CSS mask) punched where the video
              already is, so at rest they fully hide everything except that
              one continuous, centered circle. Splitting them apart just
              reveals more of the (unmoving) video underneath. */}
          <div
            className="fixed left-1/2 top-1/2 z-40 overflow-hidden rounded-full transition-transform ease-[cubic-bezier(.65,0,.35,1)]"
            style={{
              width: INTRO_PFP_SIZE,
              height: INTRO_PFP_SIZE,
              transitionDuration: `${INTRO_TRANSITION_MS}ms`,
              // Rides down with the bottom panel instead of sitting still
              // in the middle of the screen once the panels have parted —
              // a full viewport height clears it off-screen regardless of
              // how big the circle itself is.
              transform: shrinking ? "translate(-50%, calc(-50% + 100vh))" : "translate(-50%, -50%)",
            }}
          >
            <PlayOnceVideo
              src={profile.landingPfpUrl}
              className="size-full object-cover"
              onEnded={handleIntroEnd}
            />
          </div>
          <div
            className={cn(
              "fixed inset-x-0 top-0 z-50 h-1/2 bg-black transition-transform ease-[cubic-bezier(.65,0,.35,1)]",
              shrinking && "-translate-y-full"
            )}
            style={{
              transitionDuration: `${INTRO_TRANSITION_MS}ms`,
              WebkitMaskImage: introMask("100%"),
              maskImage: introMask("100%"),
            }}
          />
          <div
            className={cn(
              "fixed inset-x-0 bottom-0 z-50 h-1/2 bg-black transition-transform ease-[cubic-bezier(.65,0,.35,1)]",
              shrinking && "translate-y-full"
            )}
            style={{
              transitionDuration: `${INTRO_TRANSITION_MS}ms`,
              WebkitMaskImage: introMask("0%"),
              maskImage: introMask("0%"),
            }}
          />
        </>
      )}

      {expanded && !introPlaying && (
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
