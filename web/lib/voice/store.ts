"use client"

import { postVoiceSpeak } from "@/lib/chatApi"

// One shared cache and one shared "currently playing" slot for the whole
// tab, not per-SpeakButton state — so warming starts the moment a bubble's
// text is final (not on click), a second warm() for the same id is a
// no-op, and starting one clip stops whatever else is playing.
type Status = "idle" | "loading" | "ready" | "error"

const urls = new Map<string, string>()
const statuses = new Map<string, Status>()
// One Audio element per id, reused across play/pause so pausing and
// resuming continues from the same position instead of restarting.
const audios = new Map<string, HTMLAudioElement>()
let playingId: string | null = null
const listeners = new Set<() => void>()

function notify(): void {
  listeners.forEach((fn) => fn())
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function getStatus(id: string): Status {
  return statuses.get(id) ?? "idle"
}

export function isPlaying(id: string): boolean {
  return playingId === id
}

// api tts resolves the blob so quickly that clicking Play right as the
// button appears can outrace the browser actually registering the fresh
// blob URL — first click plays nothing, second click (a beat later) works.
// This delay is a buffer for that gap, not a fix for a slow request.
const READY_BUFFER_MS = 400

// Fire-and-forget, called once a bubble's text is final. No voice
// configured, or the request fails, both land on "error" — the button
// just never appears, same silent-fail contract the old SpeakButton had.
export function warm(id: string, text: string): void {
  if (statuses.has(id)) return
  statuses.set(id, "loading")
  notify()
  postVoiceSpeak(text)
    .then((blob) => {
      urls.set(id, URL.createObjectURL(blob))
      setTimeout(() => {
        statuses.set(id, "ready")
        notify()
      }, READY_BUFFER_MS)
    })
    .catch(() => {
      statuses.set(id, "error")
      notify()
    })
}

function getAudio(id: string, url: string): HTMLAudioElement {
  let audio = audios.get(id)
  if (!audio) {
    audio = new Audio(url)
    audio.onended = () => {
      if (playingId === id) playingId = null
      notify()
    }
    audios.set(id, audio)
  }
  return audio
}

export function play(id: string): void {
  const url = urls.get(id)
  if (!url) return
  if (playingId && playingId !== id) audios.get(playingId)?.pause()
  const audio = getAudio(id, url)
  playingId = id
  notify()
  audio.play()
}

export function pause(id: string): void {
  audios.get(id)?.pause()
  if (playingId === id) playingId = null
  notify()
}
