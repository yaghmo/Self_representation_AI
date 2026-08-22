import type { ChatMessage } from "@/components/fan/types"

const CHAT_API_URL =
  process.env.NEXT_PUBLIC_CHAT_API_URL ?? "http://127.0.0.1:8000"

export class ChatApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

// service/main.py's ChatMessage role is system|user|assistant|tool; the fan
// widget only ever has "user" | "bot" turns, so "bot" maps to "assistant".
function toBackendRole(role: ChatMessage["role"]): "user" | "assistant" {
  return role === "bot" ? "assistant" : "user"
}

// Server default is 512 — sized for the admin surface, which sends its own
// max_tokens explicitly. The fan widget renders replies as chat bubbles, so a
// long single-block answer just means more scrolling; capped well below the
// server default keeps replies to the few-short-messages length §6 of the
// character profile already asks for.
const FAN_MAX_TOKENS = 120

export async function postChat(history: ChatMessage[]): Promise<string> {
  const res = await fetch(`${CHAT_API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: history.map((m) => ({
        role: toBackendRole(m.role),
        content: m.text,
      })),
      max_tokens: FAN_MAX_TOKENS,
      // Tried `thinking: true` for coherence — reverted. Persona alone is
      // 6601 tokens against an 8192 context; thinking's flat +1024 reserve
      // pushes the budget negative before the first message sends (507
      // ProfileTooLarge). Needs a bigger context or smaller persona, not a
      // per-request flag.
    }),
  })

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new ChatApiError(res.status, detail)
  }

  const data = (await res.json()) as { content: string }
  return data.content
}
