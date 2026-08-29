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
  // TikTok's embed.js widget is unreliable — it can silently claim the
  // blockquote without ever inserting the iframe. Direct iframe embed (no
  // widget JS) works instead, same as YouTube/Twitch above.
  //
  // ponytail: TikTok's embed page renders a fixed-size card (logo, video,
  // caption, cookie banner) that won't stretch to fill an arbitrary iframe.
  // Scale/crop numbers below are tuned by eye against TikTok's current
  // layout — re-tune against a live embed if TikTok reflows the page.
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

function InstagramEmbed({ post }: { post: Post }) {
  // post.url is the profile-grid permalink ("/p/{id}/" or "/reel/{id}/"),
  // and both accept the same "embed" suffix — no separate widget JS needed,
  // same direct-iframe approach as TikTok above.
  return (
    <iframe
      src={`${post.url}embed`}
      title={post.title ?? "Instagram post"}
      allowFullScreen
      className="size-full border-0"
    />
  )
}

function XEmbed({ post }: { post: Post }) {
  // platform.twitter.com's embed page needs no widgets.js on our side —
  // same direct-iframe approach as TikTok/Instagram above.
  return (
    <iframe
      src={`https://platform.twitter.com/embed/Tweet.html?id=${post.embedId}`}
      title={post.title ?? "X post"}
      className="size-full border-0"
    />
  )
}

function PostPlayer({ post }: { post: Post }) {
  if (post.platform === "youtube") return <YouTubeEmbed post={post} />
  if (post.platform === "twitch") return <TwitchEmbed post={post} />
  if (post.platform === "tiktok") return <TikTokEmbed post={post} />
  if (post.platform === "instagram") return <InstagramEmbed post={post} />
  if (post.platform === "x") return <XEmbed post={post} />
  return null
}

export { PostPlayer }
