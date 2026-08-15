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

// No auth, no agent gate on the backend side — this is public contact info
// a fan is meant to see, same trust level as a link already on the profile.
export async function getPublicSocials(): Promise<PublicSocial[]> {
  const res = await fetch(`${SERVICE_URL}/social/list`)
  if (!res.ok) return []
  const data = (await res.json()) as { socials: PublicSocial[] }
  return data.socials
}
