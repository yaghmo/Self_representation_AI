export type FanProfile = {
  name: string
  bio: string
}

export type Post = {
  id: string
  imageUrl: string
  caption: string
}

export type ChatMessage = {
  id: string
  role: "user" | "bot"
  text: string
}
