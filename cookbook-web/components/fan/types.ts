export type FanProfile = {
  name: string
  bio: string
  pfpUrl?: string | null
  bannerUrl?: string | null
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
