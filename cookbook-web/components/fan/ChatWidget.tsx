"use client"

import { useEffect, useRef, useState } from "react"
import { MessageCircle, Send, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { ChatApiError, postChat } from "@/lib/chatApi"
import type { ChatMessage } from "./types"

function ChatWidget({ botName }: { botName: string }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [isTyping, setIsTyping] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages, isTyping, isOpen])

  useEffect(() => {
    if (isOpen && !isTyping) inputRef.current?.focus()
  }, [isOpen, isTyping])

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

    const botMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "bot",
      text: replyText,
    }
    setMessages((prev) => [...prev, botMessage])
    setIsTyping(false)
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={isOpen ? "Close chat" : "Open chat"}
        className="fixed right-8 bottom-16 z-30 flex h-14 w-24 items-center justify-center rounded-t-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 sm:right-10"
      >
        {isOpen ? <X className="size-6" /> : <MessageCircle className="size-6" />}
      </button>

      {isOpen && (
        <div className="fixed right-4 bottom-36 z-30 flex h-[28rem] max-h-[calc(100dvh-10rem)] w-[22rem] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl sm:right-6">
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
                {message.text}
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
      )}
    </>
  )
}

export { ChatWidget }
