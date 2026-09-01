import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { introAlreadySeen, isVideo, markIntroSeen } from "./introSplash"

function fakeLocalStorage() {
  const store = new Map<string, string>()
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  }
}

describe("isVideo", () => {
  it("recognizes a video mime type", () => {
    expect(isVideo("video/mp4")).toBe(true)
  })

  it("rejects an image mime type, null, and undefined", () => {
    expect(isVideo("image/jpeg")).toBe(false)
    expect(isVideo(null)).toBe(false)
    expect(isVideo(undefined)).toBe(false)
  })
})

describe("intro-seen tracking", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", fakeLocalStorage())
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("is unseen until marked, then stays seen within the hour", () => {
    expect(introAlreadySeen()).toBe(false)
    markIntroSeen()
    expect(introAlreadySeen()).toBe(true)

    vi.setSystemTime(new Date("2026-01-01T00:59:59Z"))
    expect(introAlreadySeen()).toBe(true)
  })

  it("replays again once an hour has passed", () => {
    markIntroSeen()

    vi.setSystemTime(new Date("2026-01-01T01:00:01Z"))
    expect(introAlreadySeen()).toBe(false)
  })

  it("never crashes when localStorage throws (private browsing)", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked")
      },
      setItem: () => {
        throw new Error("blocked")
      },
    })

    expect(introAlreadySeen()).toBe(false)
    expect(() => markIntroSeen()).not.toThrow()
  })
})
