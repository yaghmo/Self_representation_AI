const INTRO_SEEN_KEY = "introSeen"

export function isVideo(mime: string | null | undefined): boolean {
  return !!mime?.startsWith("video/")
}

// Real browser storage can throw (private mode, cleared site data) — a
// missed "already seen" flag just means the intro replays once more, never
// a crash.
export function introAlreadySeen(): boolean {
  try {
    return localStorage.getItem(INTRO_SEEN_KEY) === "1"
  } catch {
    return false
  }
}

export function markIntroSeen(): void {
  try {
    localStorage.setItem(INTRO_SEEN_KEY, "1")
  } catch {
    // Ignored — worst case the intro plays again next visit.
  }
}
