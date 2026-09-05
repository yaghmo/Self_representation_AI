"use client"

import { useEffect, useRef, useState } from "react"
import type { Post } from "./types"

function YouTubeEmbed({ post }: { post: Post }) {
  return (
    <iframe
      src={`https://www.youtube.com/embed/${post.embedId}?autoplay=1`}
      title={post.title ?? "YouTube video"}
      allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
      allowFullScreen
      className="aspect-video w-full border-0"
    />
  )
}

function TwitchEmbed({ post }: { post: Post }) {
  // Twitch refuses to load its player without a `parent` matching the
  // embedding page's hostname exactly — only known client-side.
  const [hostname, setHostname] = useState<string | null>(null)
  useEffect(() => setHostname(window.location.hostname), [])
  if (!hostname) return <div className="aspect-video w-full animate-pulse bg-muted" />
  return (
    <iframe
      src={`https://player.twitch.tv/?video=${post.embedId}&parent=${hostname}&autoplay=true`}
      title={post.title ?? "Twitch VOD"}
      allowFullScreen
      className="aspect-video w-full border-0"
    />
  )
}

function TikTokEmbed({ post }: { post: Post }) {
  // No crop, no scale hack — every platform's own natural size, cropping
  // never matched consistently across all of them. This is TikTok's embed
  // page rendered exactly as TikTok renders it, chrome and all.
  return (
    <iframe
      src={`https://www.tiktok.com/embed/v2/${post.embedId}`}
      title={post.title ?? "TikTok video"}
      allow="encrypted-media; picture-in-picture"
      allowFullScreen
      className="h-[80vh] max-h-[740px] w-[325px] max-w-full border-0"
    />
  )
}

declare global {
  interface Window {
    instgrm?: { Embeds: { process: () => void } }
  }
}

// If embed.js can't actually render (Instagram's oEmbed has needed an
// app-level access token since their Graph API changes — a bare public
// embed.js call can silently do nothing), the blockquote just sits there
// unprocessed and reads as a blank/broken screen. Rather than leave that,
// fall back to a plain link out after giving it a few seconds to render.
const INSTAGRAM_RENDER_TIMEOUT_MS = 4000

function InstagramEmbed({ post }: { post: Post }) {
  // The post's own scraped media (see runtime/posts.py) — a plain <video>/
  // <img> at its own natural size, no widget, no white-screen risk. Falls
  // back to the embed.js path below only for posts scraped before this
  // existed, or where the per-post scrape itself failed.
  if (post.mediaUrl) {
    return post.mediaKind === "video" ? (
      <video
        src={post.mediaUrl}
        controls
        autoPlay
        muted
        loop
        playsInline
        // PostModal closes the dialog on any click so the whole card acts as
        // its own close target — except here, where a click is someone
        // using the play/pause/seek controls, not dismissing the post.
        onClick={(e) => e.stopPropagation()}
        className="max-h-[80vh] w-full"
      />
    ) : (
      // eslint-disable-next-line @next/next/no-img-element -- third-party CDN, not a next/image remote host
      <img src={post.mediaUrl} alt="" className="max-h-[80vh] w-full object-contain" />
    )
  }
  return <InstagramWidgetEmbed post={post} />
}

function InstagramWidgetEmbed({ post }: { post: Post }) {
  // Unlike TikTok/X, Instagram's embed page sends frame-ancestors headers
  // that refuse a raw iframe outright ("instagram.com refused to connect").
  // Their own embed.js widget is the only way in: it replaces this
  // blockquote with the iframe itself once loaded.
  const containerRef = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    // No reset-on-mount needed: PostModal conditionally renders this
    // component (unmount/remount per open), so `failed` already starts
    // false every time a post opens.
    if (window.instgrm) {
      window.instgrm.Embeds.process()
    } else {
      const script = document.createElement("script")
      script.src = "https://www.instagram.com/embed.js"
      script.async = true
      script.onload = () => window.instgrm?.Embeds.process()
      document.body.appendChild(script)
      // embed.js is a singleton Instagram expects to stay on the page and be
      // reused by every blockquote that shows up later — not torn down here.
    }
    // Success swaps the <blockquote> for an <iframe> in place. If that
    // hasn't happened after a few seconds, stop showing a dead white box.
    const timer = setTimeout(() => {
      if (!containerRef.current?.querySelector("iframe")) setFailed(true)
    }, INSTAGRAM_RENDER_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [post.url])

  if (failed) {
    return (
      <a
        href={post.url}
        target="_blank"
        rel="noreferrer"
        className="flex h-40 w-full items-center justify-center bg-muted px-4 text-center text-sm text-muted-foreground underline underline-offset-2"
      >
        Could not load the embed — view on Instagram ↗
      </a>
    )
  }

  return (
    <div ref={containerRef} className="max-h-[80vh] w-full overflow-y-auto bg-white">
      <blockquote
        className="instagram-media"
        data-instgrm-permalink={post.url}
        data-instgrm-version="14"
        style={{ margin: 0, width: "100%", minWidth: 0 }}
      />
    </div>
  )
}

function XEmbed({ post }: { post: Post }) {
  // platform.twitter.com's embed page needs no widgets.js on our side —
  // same direct-iframe approach as TikTok/Instagram above. Its own natural
  // card size, no forced aspect ratio.
  return (
    <iframe
      src={`https://platform.twitter.com/embed/Tweet.html?id=${post.embedId}`}
      title={post.title ?? "X post"}
      className="h-[550px] max-h-[80vh] w-full border-0"
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
