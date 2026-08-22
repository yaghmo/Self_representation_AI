"use client"

import { useEffect, useRef, useState } from "react"
import { MessageCircle, Send, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { ChatApiError, postChat } from "@/lib/chatApi"
import { MarkdownMessage } from "@/components/chat/Markdown"
import type { ChatMessage } from "./types"

// The model already tends to write in blank-line-separated thoughts (see
// character.md §6: several short messages rather than one long one) — split
// on those rather than re-deriving message boundaries some other way.
function splitIntoBubbles(text: string): string[] {
  const parts = text
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)
  return parts.length > 0 ? parts : [text]
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

const BUBBLE_DELAY_MS = 5000

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

const DEFAULT_WIDTH = 352 // 22rem
const DEFAULT_HEIGHT = 448 // 28rem
const MIN_WIDTH = 256 // 16rem
const MIN_HEIGHT = 320 // 20rem

function ChatWidget({ botName }: { botName: string }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const [size, setSize] = useState({ width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT })
  // Creator can drop a custom chat icon at /chat-icon.png; falls back to the
  // default lucide icon when nothing has been saved for that slot.
  const [customIconFailed, setCustomIconFailed] = useState(false)
  const iconRef = useRef<HTMLImageElement>(null)
  // While dragging the resize handle, the icon's `bottom` offset is
  // recomputed every pointermove tick to keep tracking the panel's top
  // edge — animating that would lag a full transition behind the cursor,
  // so the icon's transition is suppressed for the drag's duration.
  const [isResizing, setIsResizing] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // The panel is anchored bottom-right (`right-4 bottom-36`), so a native
  // `resize: both` handle lands in the corner already jammed against the
  // page edge — the opposite corner, top-left, is the one that's actually
  // reachable, and CSS `resize` can't be told which corner to use. Custom
  // drag it is: dragging left/up grows the panel while its right/bottom
  // edges stay put.
  function handleResizeStart(event: React.PointerEvent) {
    event.preventDefault()
    const startX = event.clientX
    const startY = event.clientY
    const startWidth = size.width
    const startHeight = size.height
    setIsResizing(true)

    function handleMove(moveEvent: PointerEvent) {
      const maxWidth = window.innerWidth - 32 // matches max-w-[calc(100vw-2rem)]
      const maxHeight = window.innerHeight - 128 // matches max-h-[calc(100dvh-8rem)]
      setSize({
        width: clamp(startWidth + (startX - moveEvent.clientX), MIN_WIDTH, maxWidth),
        height: clamp(startHeight + (startY - moveEvent.clientY), MIN_HEIGHT, maxHeight),
      })
    }

    function handleUp() {
      setIsResizing(false)
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleUp)
    }

    window.addEventListener("pointermove", handleMove)
    window.addEventListener("pointerup", handleUp)
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, isTyping, isOpen])

  useEffect(() => {
    if (isOpen && !isTyping) inputRef.current?.focus()
  }, [isOpen, isTyping])

  // SSR renders this <img> before hydration attaches onError — a fast 404
  // (hard refresh) can fire and get missed. `complete` is true either way;
  // `naturalWidth` stays 0 only on failure, so this catches it post-mount.
  useEffect(() => {
    if (iconRef.current?.complete && iconRef.current.naturalWidth === 0) {
      setCustomIconFailed(true)
    }
  }, [])

  async function sendMessage() {
    const text = draft.trim()
    if (!text || isTyping) return

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text,
    }
    const history = [...messages, userMessage]
    setMessages(history)
    setDraft("")
    setIsTyping(true)

    let replyText: string
    try {
      replyText = await postChat(history)
    } catch (error) {
      replyText =
        error instanceof ChatApiError
          ? `Sorry, the chat is unavailable right now (${error.status}).`
          : "Sorry, the chat is unavailable right now."
    }

    const bubbles = splitIntoBubbles(replyText)
    for (let i = 0; i < bubbles.length; i++) {
      if (i > 0) await wait(BUBBLE_DELAY_MS)
      const botMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "bot",
        text: bubbles[i],
      }
      setMessages((prev) => [...prev, botMessage])
    }
    setIsTyping(false)
  }

  // Only hidden case: chat open with no working icon image — the panel's
  // own header close button is the sole control then. Otherwise, when an
  // image loads, it stays on screen and moves to sit on the panel's top
  // edge instead of disappearing.
  const hideToggle = isOpen && customIconFailed
  const stuckOnTop = isOpen && !customIconFailed
  // Panel is anchored `bottom-16` (64px), flush against the bottom bar, so
  // its top edge sits at 64 + panel height from the viewport bottom. Resting
  // the icon's own bottom edge there sits it entirely above the panel,
  // touching but never overlapping into the header.
  const panelTop = 64 + size.height

  return (
    <>
      {!hideToggle && (
        <button
          type="button"
          onClick={() => setIsOpen((open) => !open)}
          aria-label={isOpen ? "Close chat" : "Open chat"}
          style={stuckOnTop ? { bottom: panelTop } : undefined}
          className={cn(
            "fixed right-8 z-40 flex items-center justify-center text-primary-foreground transition-[transform,bottom] ease-out hover:scale-105 sm:right-10",
            isResizing ? "duration-0" : "duration-300",
            customIconFailed
              ? "h-14 w-24 rounded-t-full bg-primary bottom-16 shadow-lg"
              : cn("size-[120px]", !stuckOnTop && "bottom-16")
          )}
        >
          {customIconFailed ? (
            <MessageCircle className="size-6" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- local static asset, not a next/image remote host
            <img
              // No saved chat icon on this route on purpose, to exercise the
              // fallback (default lucide icon, toggle hides while open).
              ref={iconRef}
              src="/chat-icon-fan-unset.png"
              alt=""
              className="size-full object-contain drop-shadow-lg"
              onError={() => setCustomIconFailed(true)}
            />
          )}
        </button>
      )}

      <div
        style={{ width: size.width, height: size.height }}
        className={cn(
          "fixed right-4 bottom-16 z-30 flex max-h-[calc(100dvh-8rem)] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-t-2xl border border-border bg-card shadow-2xl transition-[transform,opacity] ease-out sm:right-6",
          isOpen
            ? "translate-y-0 opacity-100 duration-300"
            : "pointer-events-none translate-y-8 opacity-0 duration-0"
        )}
      >
          <div
            onPointerDown={handleResizeStart}
            aria-hidden="true"
            className="absolute left-0 top-0 z-10 size-4 touch-none cursor-nwse-resize rounded-tl-2xl hover:bg-border/40"
          />
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="font-medium">{botName}</span>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              aria-label="Close chat"
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </div>

          <div className="border-b border-border bg-muted/60 px-4 py-2 text-xs text-muted-foreground">
            This is an AI, not the real {botName}.
          </div>

          <div
            ref={scrollRef}
            className="flex-1 space-y-2 overflow-y-auto px-4 py-3"
          >
            {messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "w-fit max-w-[80%] rounded-2xl px-3 py-2 text-sm break-words",
                  message.role === "user"
                    ? "ml-auto bg-primary text-primary-foreground"
                    : "mr-auto bg-muted text-foreground"
                )}
              >
                <MarkdownMessage text={message.text} />
              </div>
            ))}
            {isTyping && (
              <div className="mr-auto flex w-fit items-center gap-1 rounded-2xl bg-muted px-3 py-2">
                <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
                <span className="size-1.5 animate-bounce rounded-full bg-muted-foreground" />
              </div>
            )}
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault()
              sendMessage()
            }}
            className="flex items-center gap-2 border-t border-border p-3"
          >
            <Input
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Send a message..."
              disabled={isTyping}
            />
            <Button
              type="submit"
              size="icon"
              disabled={isTyping || draft.trim() === ""}
            >
              <Send className="size-4" />
            </Button>
          </form>
      </div>
    </>
  )
}

export { ChatWidget }
