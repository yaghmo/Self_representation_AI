"use client"

import { forwardRef, useImperativeHandle, useRef } from "react"

export type PlayOnceVideoHandle = {
  replay: () => void
}

// Muted+inline autoplay, freezes on its own last frame (pause on `ended`)
// instead of looping — shared by the fan/yuumii pfp, banner, and chat-icon
// slots so that logic lives in exactly one place. `replay()` is for callers
// that re-trigger playback (the chat icon on open/send) rather than firing
// once on mount.
const PlayOnceVideo = forwardRef<PlayOnceVideoHandle, {
  src: string
  className?: string
  style?: React.CSSProperties
  autoPlay?: boolean
  onEnded?: () => void
  onError?: () => void
}>(function PlayOnceVideo({ src, className, style, autoPlay = true, onEnded, onError }, ref) {
  const videoRef = useRef<HTMLVideoElement>(null)

  useImperativeHandle(ref, () => ({
    replay: () => {
      const video = videoRef.current
      if (!video) return
      video.currentTime = 0
      // play() can reject (AbortError) if the browser's power-saver pauses
      // a video-only autoplay mid-request — always a possibility for any
      // programmatic play(), not a bug to chase, just one to not crash on.
      video.play().catch(() => {})
    },
  }))

  return (
    <video
      ref={videoRef}
      src={src}
      className={className}
      style={style}
      muted
      playsInline
      autoPlay={autoPlay}
      onEnded={(e) => {
        e.currentTarget.pause()
        onEnded?.()
      }}
      onError={onError}
    />
  )
})

export { PlayOnceVideo }
