export type FanProfile = {
  name: string
  bio: string
  contactEmail?: string | null
  pfpUrl?: string | null
  pfpMime?: string | null
  bannerUrl?: string | null
  chatIconUrl?: string | null
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
}

export type ChatMessage = {
  id: string
  role: "user" | "bot"
  text: string
}
