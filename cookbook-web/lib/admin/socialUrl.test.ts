import { describe, expect, it } from "vitest"
import { parseSocialUrl } from "./socialUrl"

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
})
