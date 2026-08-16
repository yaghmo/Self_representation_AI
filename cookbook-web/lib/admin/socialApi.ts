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

export function getSocials(): Promise<{ bio: string | null; socials: Social[] }> {
  return request("/admin/social/list")
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

export interface PreviewSocialResult {
  platform: string
  username: string
  pfpUrl: string | null
  followerCount: number | null
  bio: string | null
  isAlt: boolean
}

export function previewSocial(params: PreviewSocialParams): Promise<PreviewSocialResult> {
  return request("/admin/social/preview", {
    method: "POST",
    body: JSON.stringify(params),
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
