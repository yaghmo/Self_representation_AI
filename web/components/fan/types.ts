export type FanProfile = {
  name: string
  bio: string
  contactEmail?: string | null
  pfpUrl?: string | null
  pfpMime?: string | null
  bannerUrl?: string | null
  bannerMime?: string | null
  chatIconUrl?: string | null
  chatIconMime?: string | null
  landingPfpUrl?: string | null
  landingPfpMime?: string | null
}

export type Post = {
  id: string
  platform: string
  kind: string
  embedId: string
  url: string
  title: string | null
  thumbnailUrl: string | null
  // Instagram only — the post's own og:video/og:image, scraped once during
  // the admin post refresh (see runtime/posts.py). Lets the player render a
  // plain <video>/<img> instead of Instagram's embed.js widget, which needs
  // an app-level oEmbed token Instagram never gave this app and can render
  // nothing at all without one.
  mediaUrl?: string | null
  // Which tag the scrape actually found — NOT the same as `kind` above,
  // which is only a guess from the post's /reel/ vs /p/ URL shape.
  // Instagram doesn't expose og:video for every reel, so a reel can still
  // resolve to a still image here; trust this field, not `kind`, when
  // deciding whether to render a <video> or an <img>.
  mediaKind?: "video" | "image" | null
}

export type ChatMessage = {
  id: string
  role: "user" | "bot"
  text: string
  // True only on the last bubble of a bot turn — that's the one bubble that
  // carries the play button, reading the whole turn's text in one TTS call
  // (see ChatWidget.sendMessage). Per-bubble TTS synthesized each thought in
  // isolation, cutting the voice off wherever a bubble happened to end.
  final?: boolean
}
