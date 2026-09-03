import { describe, expect, it } from "vitest"
import { buildSocialUrl, parseSocialUrl } from "./socialUrl"

describe("parseSocialUrl", () => {
  it("parses an instagram profile url", () => {
    expect(parseSocialUrl("https://instagram.com/handle")).toEqual({
      platform: "instagram",
      username: "handle",
    })
  })

  it("parses a tiktok profile url with a leading @ in the path", () => {
    expect(parseSocialUrl("https://www.tiktok.com/@handle")).toEqual({
      platform: "tiktok",
      username: "@handle",
    })
  })

  it("treats twitter.com and x.com as the same platform", () => {
    expect(parseSocialUrl("https://twitter.com/handle")?.platform).toBe("x")
    expect(parseSocialUrl("https://x.com/handle")?.platform).toBe("x")
  })

  it("returns null for an unrecognized domain", () => {
    expect(parseSocialUrl("https://example.com/handle")).toBeNull()
  })

  it("returns null for a URL with no path", () => {
    expect(parseSocialUrl("https://instagram.com")).toBeNull()
  })

  it("returns null for a non-URL string", () => {
    expect(parseSocialUrl("not a url")).toBeNull()
  })

  it("parses a bare domain pasted without a scheme", () => {
    expect(parseSocialUrl("throne.com/handle")).toEqual({
      platform: "throne",
      username: "handle",
    })
  })

  it("still returns null for an unrecognized bare domain", () => {
    expect(parseSocialUrl("example.com/handle")).toBeNull()
  })
})

describe("buildSocialUrl", () => {
  it("adds the @ prefix for tiktok — a bare path doesn't resolve to the profile", () => {
    expect(buildSocialUrl("tiktok", "handle")).toBe("https://tiktok.com/@handle")
  })

  it("adds the @ prefix for youtube", () => {
    expect(buildSocialUrl("youtube", "handle")).toBe("https://youtube.com/@handle")
  })

  it("strips a leading @ the caller already included, instead of doubling it", () => {
    expect(buildSocialUrl("tiktok", "@handle")).toBe("https://tiktok.com/@handle")
  })

  it("uses a bare path for platforms without an @-handle URL shape", () => {
    expect(buildSocialUrl("instagram", "handle")).toBe("https://instagram.com/handle")
    expect(buildSocialUrl("x", "handle")).toBe("https://x.com/handle")
  })

  it("returns null for a platform with no canonical domain", () => {
    expect(buildSocialUrl("myspace", "handle")).toBeNull()
  })
})
