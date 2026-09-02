import { describe, expect, it } from "vitest"
import { stripEmotionTags } from "./emotionTags"

describe("stripEmotionTags", () => {
  it("strips a tag and collapses the resulting whitespace", () => {
    expect(stripEmotionTags("hehehe [chuckling] that's wild")).toBe("hehehe that's wild")
  })

  it("is case-insensitive", () => {
    expect(stripEmotionTags("[Laughing] no way")).toBe("no way")
  })

  it("matches a multi-word tag as one unit", () => {
    expect(stripEmotionTags("well... [long pause] anyway")).toBe("well... anyway")
  })

  it("leaves plain text untouched", () => {
    expect(stripEmotionTags("nothing to strip here")).toBe("nothing to strip here")
  })
})
