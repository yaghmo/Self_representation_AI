export interface Social {
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

export class SocialApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${SERVICE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new SocialApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export interface SocialListResult {
  bio: string | null
  contactEmail: string | null
  socials: Social[]
  pfpVersion: number | null
  bannerVersion: number | null
}

export function getSocials(): Promise<SocialListResult> {
  return request("/admin/social/list")
}

export function pfpUrl(version: number): string {
  return `${SERVICE_URL}/social/pfp?v=${version}`
}

export function bannerUrl(version: number): string {
  return `${SERVICE_URL}/social/banner?v=${version}`
}

async function uploadImage(path: string, blob: Blob): Promise<{ version: number }> {
  const res = await fetch(`${SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": blob.type },
    body: blob,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new SocialApiError(res.status, detail)
  }
  const body = await res.json()
  return { version: body.pfpVersion ?? body.bannerVersion }
}

export function uploadPfp(blob: Blob): Promise<{ version: number }> {
  return uploadImage("/admin/social/pfp", blob)
}

export function uploadBanner(blob: Blob): Promise<{ version: number }> {
  return uploadImage("/admin/social/banner", blob)
}

export interface AddSocialParams {
  platform: string
  username: string
  url: string
  bio?: string
  followerCount?: number
  pfpUrl?: string
  isAlt?: boolean
}

export function addSocial(params: AddSocialParams): Promise<Social> {
  return request("/admin/social/add", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export interface UpdateSocialParams extends Partial<AddSocialParams> {
  id: string
}

export function updateSocial(params: UpdateSocialParams): Promise<Social> {
  return request("/admin/social/update", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export function deleteSocial(id: string): Promise<{ deleted: string }> {
  return request("/admin/social/delete", {
    method: "POST",
    body: JSON.stringify({ id }),
  })
}

export interface PreviewSocialParams {
  url: string
  id?: string
}

export interface SocialMention {
  type: "platform" | "email"
  platform: string | null
  value: string
}

export interface PreviewSocialResult {
  platform: string
  username: string
  pfpUrl: string | null
  followerCount: number | null
  bio: string | null
  isAlt: boolean
  mentions: SocialMention[]
}

export function previewSocial(
  params: PreviewSocialParams,
  signal?: AbortSignal
): Promise<PreviewSocialResult> {
  return request("/admin/social/preview", {
    method: "POST",
    body: JSON.stringify(params),
    signal,
  })
}

export function generateBio(): Promise<{ bio: string }> {
  return request("/admin/social/bio/generate", { method: "POST" })
}

export function saveBio(bio: string): Promise<{ bio: string }> {
  return request("/admin/social/bio", {
    method: "POST",
    body: JSON.stringify({ bio }),
  })
}

export function saveContactEmail(email: string | null): Promise<{ contactEmail: string | null }> {
  return request("/admin/social/contact_email", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export function refreshPosts(): Promise<{ posts: unknown[] }> {
  return request("/admin/social/posts/refresh", { method: "POST" })
}

export interface TiktokStatus {
  connected: boolean
  openId?: string
  scope?: string
}

export function tiktokStatus(): Promise<TiktokStatus> {
  return request("/admin/tiktok/status")
}

export function tiktokLoginUrl(): Promise<{ authorizeUrl: string }> {
  return request("/admin/tiktok/login")
}

export function tiktokDisconnect(): Promise<{ connected: boolean }> {
  return request("/admin/tiktok/disconnect", { method: "POST" })
}
