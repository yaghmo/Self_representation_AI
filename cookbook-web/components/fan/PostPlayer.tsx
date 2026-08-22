"use client"

import { useEffect, useState } from "react"
import type { Post } from "./types"

function YouTubeEmbed({ post }: { post: Post }) {
  return (
    <iframe
      src={`https://www.youtube.com/embed/${post.embedId}?autoplay=1`}
      title={post.title ?? "YouTube video"}
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
      allowFullScreen
      className="size-full border-0"
    />
  )
}

function TwitchEmbed({ post }: { post: Post }) {
  // Twitch refuses to load its player without a `parent` matching the
  // embedding page's hostname exactly — only known client-side.
  const [hostname, setHostname] = useState<string | null>(null)
  useEffect(() => setHostname(window.location.hostname), [])
  if (!hostname) return <div className="size-full animate-pulse bg-muted" />
  return (
    <iframe
      src={`https://player.twitch.tv/?video=${post.embedId}&parent=${hostname}&autoplay=true`}
      title={post.title ?? "Twitch VOD"}
      allowFullScreen
      className="size-full border-0"
    />
  )
}

function TikTokEmbed({ post }: { post: Post }) {
  // TikTok's official embed.js widget (blockquote + script scan) is
  // unreliable in practice — it can silently claim the blockquote without
  // ever inserting the iframe, with no error surfaced anywhere to detect
  // it. TikTok's own direct iframe embed (no widget JS involved) works the
  // same way YouTube's and Twitch's do below, so use that instead.
  //
  // ponytail: TikTok's embed page renders its own fixed-size card (logo
  // header, video, caption, cookie banner) that doesn't stretch to fill an
  // arbitrary iframe box. Scaling the iframe up and cropping it to the
  // shared aspect box shows mostly the video instead of that whole card
  // shrunk inside ours. The scale/crop numbers are tuned by eye against
  // TikTok's current embed layout — if TikTok reflows that page, this
  // needs re-tuning against a live embed, not guessed at.
  return (
    <div className="relative size-full overflow-hidden bg-black">
      <iframe
        src={`https://www.tiktok.com/embed/v2/${post.embedId}`}
        title={post.title ?? "TikTok video"}
        allow="encrypted-media; picture-in-picture"
        allowFullScreen
        className="absolute left-1/2 w-[325px] origin-top border-0"
        style={{ top: -160, height: 2000, transform: "translateX(-50%) scale(1.6)" }}
      />
    </div>
  )
}

function PostPlayer({ post }: { post: Post }) {
  if (post.platform === "youtube") return <YouTubeEmbed post={post} />
  if (post.platform === "twitch") return <TwitchEmbed post={post} />
  if (post.platform === "tiktok") return <TikTokEmbed post={post} />
  return null
}

export { PostPlayer }
