"use client"

import { useEffect, useRef, useState } from "react"
import { MessageCircle, Send, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { ChatMessage } from "./types"

const CANNED_REPLIES = [
  "Thanks for the message! This is a mock reply while the real chat isn't wired up yet.",
  "Good question — I don't have a real answer yet, this is just a placeholder response.",
  "Appreciate you reaching out. Real answers are coming once the chat is connected.",
]

let replyIndex = 0

function nextCannedReply() {
  const reply = CANNED_REPLIES[replyIndex % CANNED_REPLIES.length]
  replyIndex += 1
  return reply
}

function ChatWidget({ botName }: { botName: string }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, isTyping])

  function sendMessage() {
    const text = draft.trim()
    if (!text || isTyping) return

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text,
    }
    setMessages((prev) => [...prev, userMessage])
    setDraft("")
    setIsTyping(true)

    setTimeout(() => {
      const botMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "bot",
        text: nextCannedReply(),
      }
      setMessages((prev) => [...prev, botMessage])
      setIsTyping(false)
    }, 1000)
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={isOpen ? "Close chat" : "Open chat"}
        className="fixed right-4 bottom-20 z-30 flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 sm:right-6"
      >
        {isOpen ? <X className="size-6" /> : <MessageCircle className="size-6" />}
      </button>

      {isOpen && (
        <div className="fixed right-4 bottom-36 z-30 flex h-[28rem] w-[22rem] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl sm:right-6">
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
                  "max-w-[80%] rounded-2xl px-3 py-2 text-sm",
                  message.role === "user"
                    ? "ml-auto bg-primary text-primary-foreground"
                    : "mr-auto bg-muted text-foreground"
                )}
              >
                {message.text}
              </div>
            ))}
            {isTyping && (
              <div className="mr-auto flex items-center gap-1 rounded-2xl bg-muted px-3 py-2">
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
      )}
    </>
  )
}

export { ChatWidget }
