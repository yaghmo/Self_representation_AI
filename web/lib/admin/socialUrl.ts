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
  "twitch.tv": "twitch",
  "t.me": "telegram",
  "telegram.me": "telegram",
  "throne.com": "throne",
  "discord.gg": "discord",
  "linktr.ee": "linktree",
  "linktree.com": "linktree",
}

// Pure string parsing, zero network requests — see the plan's Global
// Constraints on why this feature does no fetching.
export function parseSocialUrl(url: string): ParsedSocialUrl | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    // A bare domain pasted without "https://" (e.g. copied from a bio field
    // that displays links without a scheme) is a real link, not garbage —
    // only retry once, so genuine non-URL text ("not a url") still fails.
    try {
      parsed = new URL(`https://${url}`)
    } catch {
      return null
    }
  }
  const host = parsed.hostname.replace(/^www\./, "")
  const platform = DOMAIN_PLATFORMS[host]
  if (!platform) return null
  const segments = parsed.pathname.split("/").filter(Boolean)
  // YouTube alone has legacy URL shapes with a type prefix before the
  // actual identifier — /c/CustomName, /channel/UCxxxx, /user/LegacyName —
  // alongside the modern /@handle every other platform's plain-username
  // path matches. Only those three prefixes get the second segment;
  // everything else (including a bare /@handle) keeps the first.
  const username =
    (platform === "youtube" && ["c", "channel", "user"].includes(segments[0]) && segments[1]) ||
    segments[0] ||
    ""
  if (!username) return null
  return { platform, username }
}

// The inverse of DOMAIN_PLATFORMS, for constructing a link from a bare
// platform + handle (e.g. a bio-mention suggestion) — one canonical domain
// per platform, not every domain that parses to it.
const CANONICAL_DOMAIN: Record<string, string> = {
  instagram: "instagram.com",
  tiktok: "tiktok.com",
  x: "x.com",
  youtube: "youtube.com",
  twitch: "twitch.tv",
  telegram: "t.me",
  throne: "throne.com",
  discord: "discord.gg",
}

export function buildSocialUrl(platform: string, handle: string): string | null {
  const domain = CANONICAL_DOMAIN[platform]
  if (!domain) return null
  const bare = handle.replace(/^@/, "")
  // YouTube and TikTok's canonical URL shape is /@handle — a bare path
  // (tiktok.com/name, no @) doesn't resolve to the profile at all. Every
  // other platform here uses a bare username path.
  return platform === "youtube" || platform === "tiktok"
    ? `https://${domain}/@${bare}`
    : `https://${domain}/${bare}`
}
