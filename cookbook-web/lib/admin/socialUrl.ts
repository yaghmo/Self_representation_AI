export interface ParsedSocialUrl {
  platform: string
  username: string
}

const DOMAIN_PLATFORMS: Record<string, string> = {
  "instagram.com": "instagram",
  "tiktok.com": "tiktok",
  "x.com": "x",
  "twitter.com": "x",
  "youtube.com": "youtube",
  "linkedin.com": "linkedin",
}

// Pure string parsing, zero network requests — see the plan's Global
// Constraints on why this feature does no fetching.
export function parseSocialUrl(url: string): ParsedSocialUrl | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  const host = parsed.hostname.replace(/^www\./, "")
  const platform = DOMAIN_PLATFORMS[host]
  if (!platform) return null
  const username = parsed.pathname.split("/").filter(Boolean)[0] ?? ""
  if (!username) return null
  return { platform, username }
}
