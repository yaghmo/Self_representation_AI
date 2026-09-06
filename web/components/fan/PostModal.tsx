"use client"

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { PostPlayer } from "./PostPlayer"
import type { Post } from "./types"

// Only YouTube/Twitch are genuinely flexible-width landscape video — their
// player fills whatever width the iframe is given, so growing the dialog
// with the screen actually grows the video. TikTok (fixed ~325px card),
// X (Twitter's tweet widget maxes out around its own ~550px regardless of
// container size), and Instagram (real media, sized to its own aspect ratio
// via object-contain) all have a natural width of their own — a wider
// dialog around any of them is just empty space on the sides, not a bigger
// video.
//
// dialog.tsx's own default carries a hardcoded `sm:max-w-md`. An unprefixed
// class like `max-w-sm` does NOT beat that: they're different responsive
// variants to Tailwind, both survive a `cn()` merge independently, and the
// breakpoint-scoped one wins on any screen ≥640px regardless of what the
// unprefixed class says. Every override below is `sm:`-prefixed so it
// actually replaces the default instead of merely coexisting with it.
const DIALOG_WIDTH: Record<string, string> = {
  tiktok: "sm:max-w-[325px]",
  x: "sm:max-w-[550px]",
  instagram: "sm:max-w-lg",
}
const DEFAULT_DIALOG_WIDTH = "sm:w-[50vw] sm:max-w-none"

function PostModal({ post, onClose }: { post: Post; onClose: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      {/* No forced box shape — every platform embeds at its own natural
          size (see PostPlayer), so the dialog just wraps whatever that is.
          `w-fit` here would shrink this box to its content's own size —
          but an iframe/video sized with `w-full` has nothing real to be
          100% *of* in a shrink-wrapped parent, and collapses to a tiny
          default. Keeping the default `w-full` (capped by max-width above)
          gives those percentage widths something concrete, and it's also
          what makes the whole thing respond to the browser being resized
          rather than sitting at one fixed size. Click anywhere on it closes
          it, same as clicking the dark backdrop already does — darkened
          further than the shared default so a big-monitor background feed
          doesn't compete with it. */}
      <DialogContent
        className={`${DIALOG_WIDTH[post.platform] ?? DEFAULT_DIALOG_WIDTH} gap-0 overflow-hidden border-0 bg-transparent p-0 shadow-none`}
        overlayClassName="bg-black/70"
        onClick={onClose}
        showCloseButton={false}
      >
        <DialogTitle className="sr-only">{post.title ?? `${post.platform} post`}</DialogTitle>
        <PostPlayer post={post} />
      </DialogContent>
    </Dialog>
  )
}

export { PostModal }
