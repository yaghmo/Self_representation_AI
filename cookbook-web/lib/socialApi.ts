export interface PublicSocial {
  id: string
  platform: string
  username: string
  url: string
  bio: string | null
  followerCount: number | null
  pfpUrl: string | null
  isAlt: boolean
}

const SERVICE_URL = process.env.NEXT_PUBLIC_SERVICE_URL ?? "http://127.0.0.1:8000"

export interface PublicProfile {
  bio: string | null
  contactEmail: string | null
  socials: PublicSocial[]
  pfpVersion: number | null
  bannerVersion: number | null
  chatIconVersion: number | null
  landingPfpVersion: number | null
  pfpMime: string | null
  bannerMime: string | null
  chatIconMime: string | null
  landingPfpMime: string | null
}

const EMPTY_PROFILE: PublicProfile = {
  bio: null,
  contactEmail: null,
  socials: [],
  pfpVersion: null,
  bannerVersion: null,
  chatIconVersion: null,
  landingPfpVersion: null,
  pfpMime: null,
  bannerMime: null,
  chatIconMime: null,
  landingPfpMime: null,
}

// No auth, no agent gate on the backend side — this is public contact info
// a fan is meant to see, same trust level as a link already on the profile.
export async function getPublicProfile(): Promise<PublicProfile> {
  const res = await fetch(`${SERVICE_URL}/social/list`)
  if (!res.ok) return EMPTY_PROFILE
  return (await res.json()) as PublicProfile
}

export async function getPublicSocials(): Promise<PublicSocial[]> {
  return (await getPublicProfile()).socials
}

export function publicPfpUrl(version: number): string {
  return `${SERVICE_URL}/social/pfp?v=${version}`
}

export function publicBannerUrl(version: number): string {
  return `${SERVICE_URL}/social/banner?v=${version}`
}

export function publicChatIconUrl(version: number): string {
  return `${SERVICE_URL}/social/chat_icon?v=${version}`
}

export function publicLandingPfpUrl(version: number): string {
  return `${SERVICE_URL}/social/landing_pfp?v=${version}`
}

export interface PublicPost {
  id: string
  platform: string
  kind: string
  embedId: string
  url: string
  title: string | null
  thumbnailUrl: string | null
}

export async function getPublicPosts(): Promise<PublicPost[]> {
  const res = await fetch(`${SERVICE_URL}/social/posts`)
  if (!res.ok) return []
  const body = (await res.json()) as { posts: PublicPost[] }
  return body.posts
}
