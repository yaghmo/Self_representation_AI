const INTRO_SEEN_KEY = "introSeen"
const INTRO_REPLAY_INTERVAL_MS = 60 * 60 * 1000

export function isVideo(mime: string | null | undefined): boolean {
  return !!mime?.startsWith("video/")
}

// Real browser storage can throw (private mode, cleared site data) — a
// missed "already seen" timestamp just means the intro replays once more,
// never a crash. Stores when it last played, not just whether it ever did,
// so it replays again after an hour instead of once forever per browser.
export function introAlreadySeen(): boolean {
  try {
    const seenAt = Number(localStorage.getItem(INTRO_SEEN_KEY))
    return Number.isFinite(seenAt) && Date.now() - seenAt < INTRO_REPLAY_INTERVAL_MS
  } catch {
    return false
  }
}

export function markIntroSeen(): void {
  try {
    localStorage.setItem(INTRO_SEEN_KEY, String(Date.now()))
  } catch {
    // Ignored — worst case the intro plays again next visit.
  }
}
