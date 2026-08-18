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

const TIKTOK_EMBED_TIMEOUT_MS = 1000

function TikTokEmbed({ post }: { post: Post }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
    // TikTok's official embed.js only scans the DOM for .tiktok-embed
    // blockquotes at script-execution time (no public re-render API), so
    // each mount injects its own fresh script tag to trigger a scan. It can
    // still silently fail to turn the blockquote into a real iframe (blocked
    // request, TikTok-side error, private/removed video) — that shows as a
    // permanently black box with nothing to click, so fall back to a plain
    // link if no iframe shows up within a few seconds.
    const script = document.createElement("script")
    script.src = "https://www.tiktok.com/embed.js"
    script.async = true
    containerRef.current?.appendChild(script)

    const timer = setTimeout(() => {
      if (!containerRef.current?.querySelector("iframe")) setFailed(true)
    }, TIKTOK_EMBED_TIMEOUT_MS)

    return () => {
      clearTimeout(timer)
      script.remove()
    }
  }, [post.embedId])

  if (failed) {
    return (
      <a
        href={post.url}
        target="_blank"
        rel="noreferrer"
        className="group relative flex size-full flex-col items-center justify-center gap-2 overflow-hidden bg-muted p-6 text-center text-sm text-white"
      >
        {post.thumbnailUrl && (
          // eslint-disable-next-line @next/next/no-img-element -- third-party platform thumbnail, not a next/image remote host
          <img
            src={post.thumbnailUrl}
            alt=""
            className="absolute inset-0 size-full object-cover"
          />
        )}
        <div className="absolute inset-0 bg-black/50 transition-colors group-hover:bg-black/60" />
        {post.title && <span className="relative line-clamp-4">{post.title}</span>}
        <span className="relative underline">Couldn&apos;t load — open on TikTok</span>
      </a>
    )
  }

  return (
    <div ref={containerRef} className="size-full overflow-hidden">
      <blockquote
        className="tiktok-embed"
        cite={post.url}
        data-video-id={post.embedId}
        style={{ maxWidth: "100%", minWidth: "100%" }}
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
