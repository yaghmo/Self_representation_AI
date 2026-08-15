# Fan Web Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fan-facing social-media-style profile page (banner, pfp, bio, empty post grid, sticky bottom bar) with a floating mock chatbot widget, in `cookbook-web`.

**Architecture:** One new client-rendered route, `cookbook-web/app/fan/page.tsx`, composed from four presentational components under `cookbook-web/components/fan/`. No backend calls — chat replies are canned strings on a timer, matching the approved design's UI-first scope.

**Tech Stack:** Next.js 16 (App Router), React 19, Tailwind CSS v4, shadcn-derived `components/ui/*` primitives (`Button`, `Input`), `lucide-react` icons. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-14-fan-web-page-design.md`

## Global Constraints

- No new npm dependencies — no animation library, no `Avatar` primitive. Use Tailwind's built-in `animate-bounce` utility for the typing indicator and CSS `group-hover` for the bottom-bar `+` label.
- No streaming; bot replies appear whole after a fixed ~1s delay.
- Posts ship in empty-state only — no fake post content.
- Social icons in the bottom bar are placeholders: `aria-disabled`, no `href`, visually muted.
- The chat disclosure banner ("This is an AI, not the real [name].") is non-dismissible — no close control on it.
- Chat bubble button must sit above the sticky bottom bar, never overlapped by it.
- This repo has no JS/TS test framework use for markup-only components (per spec's Testing section) — verification is `npx tsc --noEmit` after each task plus a manual dev-server walkthrough at the end.

---

## File Structure

- `cookbook-web/app/fan/page.tsx` — the route; composes the four components below with mock data.
- `cookbook-web/components/fan/types.ts` — shared `FanProfile`, `Post`, `ChatMessage` types.
- `cookbook-web/components/fan/mockData.ts` — mock profile (name, bio) and empty posts array.
- `cookbook-web/components/fan/ProfileHeader.tsx` — banner, pfp, name, bio.
- `cookbook-web/components/fan/PostGrid.tsx` — 3-col grid, empty-state tile.
- `cookbook-web/components/fan/BottomBar.tsx` — sticky social-icon bar with hover-reveal `+`.
- `cookbook-web/components/fan/ChatWidget.tsx` — floating bubble + messenger panel (disclosure banner, message list, typing indicator, composer, canned replies).

---

### Task 1: Route skeleton, shared types, mock data

**Files:**
- Create: `cookbook-web/components/fan/types.ts`
- Create: `cookbook-web/components/fan/mockData.ts`
- Create: `cookbook-web/app/fan/page.tsx`

**Interfaces:**
- Produces: `FanProfile { name: string; bio: string }`, `Post { id: string; imageUrl: string; caption: string }`, `ChatMessage { id: string; role: "user" | "bot"; text: string }` — all consumed by later tasks' components.
- Produces: `mockProfile: FanProfile`, `mockPosts: Post[]` (empty array) — consumed by `page.tsx` and, later, `ProfileHeader`/`PostGrid`.

- [ ] **Step 1: Create the shared types file**

`cookbook-web/components/fan/types.ts`:

```ts
export type FanProfile = {
  name: string
  bio: string
}

export type Post = {
  id: string
  imageUrl: string
  caption: string
}

export type ChatMessage = {
  id: string
  role: "user" | "bot"
  text: string
}
```

- [ ] **Step 2: Create the mock data file**

`cookbook-web/components/fan/mockData.ts`:

```ts
import type { FanProfile, Post } from "./types"

export const mockProfile: FanProfile = {
  name: "Jordan Rivers",
  bio: "Creator, storyteller, occasional chaos agent. Ask me anything.",
}

export const mockPosts: Post[] = []
```

- [ ] **Step 3: Create the route skeleton**

`cookbook-web/app/fan/page.tsx`:

```tsx
"use client"

import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <p>{mockProfile.name}</p>
      <p>{mockPosts.length} posts</p>
    </div>
  )
}
```

- [ ] **Step 4: Verify it compiles and the route loads**

Run: `cd cookbook-web && npx tsc --noEmit`
Expected: no errors.

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/fan`
Expected: page shows "Jordan Rivers" and "0 posts". Stop the dev server after checking.

- [ ] **Step 5: Commit**

```bash
git add cookbook-web/components/fan/types.ts cookbook-web/components/fan/mockData.ts cookbook-web/app/fan/page.tsx
git commit -m "feat(fan): scaffold fan route with shared types and mock data"
```

---

### Task 2: ProfileHeader

**Files:**
- Create: `cookbook-web/components/fan/ProfileHeader.tsx`
- Modify: `cookbook-web/app/fan/page.tsx`

**Interfaces:**
- Consumes: `FanProfile` from `./types` (Task 1).
- Produces: `ProfileHeader({ profile: FanProfile })` — a default-exportless named component, consumed by `page.tsx`.

- [ ] **Step 1: Create ProfileHeader**

`cookbook-web/components/fan/ProfileHeader.tsx`:

```tsx
import type { FanProfile } from "./types"

function ProfileHeader({ profile }: { profile: FanProfile }) {
  return (
    <header className="relative">
      <div className="h-40 w-full bg-gradient-to-r from-primary/40 via-accent to-primary/20 sm:h-56" />
      <div className="relative -mt-12 flex flex-col items-start gap-3 px-4 sm:-mt-16 sm:px-6">
        <div className="size-24 shrink-0 rounded-full border-4 border-background bg-muted sm:size-32" />
        <div>
          <h1 className="text-xl font-semibold sm:text-2xl">{profile.name}</h1>
          <p className="mt-1 max-w-prose text-sm text-muted-foreground sm:text-base">
            {profile.bio}
          </p>
        </div>
      </div>
    </header>
  )
}

export { ProfileHeader }
```

- [ ] **Step 2: Wire it into the page**

Replace the body of `cookbook-web/app/fan/page.tsx` with:

```tsx
"use client"

import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <ProfileHeader profile={mockProfile} />
      <p>{mockPosts.length} posts</p>
    </div>
  )
}
```

- [ ] **Step 3: Verify**

Run: `cd cookbook-web && npx tsc --noEmit`
Expected: no errors.

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/fan`
Expected: gradient banner, circular pfp placeholder overlapping its bottom edge, name and bio below it. Stop the dev server after checking.

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/components/fan/ProfileHeader.tsx cookbook-web/app/fan/page.tsx
git commit -m "feat(fan): add profile header with banner, pfp, bio"
```

---

### Task 3: PostGrid

**Files:**
- Create: `cookbook-web/components/fan/PostGrid.tsx`
- Modify: `cookbook-web/app/fan/page.tsx`

**Interfaces:**
- Consumes: `Post` from `./types` (Task 1).
- Produces: `PostGrid({ posts: Post[] })`, consumed by `page.tsx`.

- [ ] **Step 1: Create PostGrid**

`cookbook-web/components/fan/PostGrid.tsx`:

```tsx
import type { Post } from "./types"

function PostGrid({ posts }: { posts: Post[] }) {
  if (posts.length === 0) {
    return (
      <div className="mx-4 mt-8 rounded-2xl border border-dashed border-border py-16 text-center text-sm text-muted-foreground sm:mx-6">
        No posts yet.
      </div>
    )
  }

  return (
    <div className="mx-4 mt-8 grid grid-cols-3 gap-1 sm:mx-6 sm:gap-2">
      {posts.map((post) => (
        <div
          key={post.id}
          className="aspect-square overflow-hidden rounded-md bg-muted"
        >
          <img
            src={post.imageUrl}
            alt={post.caption}
            className="size-full object-cover"
          />
        </div>
      ))}
    </div>
  )
}

export { PostGrid }
```

- [ ] **Step 2: Wire it into the page**

Replace the body of `cookbook-web/app/fan/page.tsx` with:

```tsx
"use client"

import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <ProfileHeader profile={mockProfile} />
      <PostGrid posts={mockPosts} />
    </div>
  )
}
```

- [ ] **Step 3: Verify**

Run: `cd cookbook-web && npx tsc --noEmit`
Expected: no errors.

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/fan`
Expected: below the profile header, a dashed-border tile reading "No posts yet." Stop the dev server after checking.

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/components/fan/PostGrid.tsx cookbook-web/app/fan/page.tsx
git commit -m "feat(fan): add post grid with empty state"
```

---

### Task 4: BottomBar

**Files:**
- Create: `cookbook-web/components/fan/BottomBar.tsx`
- Modify: `cookbook-web/app/fan/page.tsx`

**Interfaces:**
- Consumes: `lucide-react`'s `Link2`, `Plus` icons.
- Produces: `BottomBar()` (no props), consumed by `page.tsx`.

- [ ] **Step 1: Create BottomBar**

`cookbook-web/components/fan/BottomBar.tsx`:

```tsx
import { Link2, Plus } from "lucide-react"

function BottomBar() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex items-center justify-center gap-6 border-t border-border bg-background/95 py-3 backdrop-blur">
      <span
        aria-disabled="true"
        className="flex size-9 items-center justify-center rounded-full text-muted-foreground/50"
      >
        <Link2 className="size-5" />
      </span>
      <span
        aria-disabled="true"
        className="flex size-9 items-center justify-center rounded-full text-muted-foreground/50"
      >
        <Link2 className="size-5" />
      </span>
      <div className="group relative flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground">
        <Plus className="size-5" />
        <span className="pointer-events-none absolute -top-8 rounded-md bg-foreground px-2 py-1 text-xs whitespace-nowrap text-background opacity-0 transition-opacity group-hover:opacity-100">
          More
        </span>
      </div>
    </nav>
  )
}

export { BottomBar }
```

- [ ] **Step 2: Wire it into the page**

Replace the body of `cookbook-web/app/fan/page.tsx` with:

```tsx
"use client"

import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { BottomBar } from "@/components/fan/BottomBar"
import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <ProfileHeader profile={mockProfile} />
      <PostGrid posts={mockPosts} />
      <BottomBar />
    </div>
  )
}
```

- [ ] **Step 3: Verify**

Run: `cd cookbook-web && npx tsc --noEmit`
Expected: no errors.

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/fan`
Expected: a sticky bar pinned to the bottom of the viewport with two greyed link icons and a `+`; hovering the `+` shows a "More" label above it. Stop the dev server after checking.

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/components/fan/BottomBar.tsx cookbook-web/app/fan/page.tsx
git commit -m "feat(fan): add sticky bottom bar with placeholder social icons"
```

---

### Task 5: ChatWidget

**Files:**
- Create: `cookbook-web/components/fan/ChatWidget.tsx`
- Modify: `cookbook-web/app/fan/page.tsx`

**Interfaces:**
- Consumes: `ChatMessage` from `./types` (Task 1); `Button` from `@/components/ui/button`; `Input` from `@/components/ui/input`; `cn` from `@/lib/utils`; `MessageCircle`, `Send`, `X` from `lucide-react`.
- Produces: `ChatWidget({ botName: string })`, consumed by `page.tsx`.

- [ ] **Step 1: Create ChatWidget**

`cookbook-web/components/fan/ChatWidget.tsx`:

```tsx
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
```

- [ ] **Step 2: Wire it into the page**

Replace the body of `cookbook-web/app/fan/page.tsx` with:

```tsx
"use client"

import { ProfileHeader } from "@/components/fan/ProfileHeader"
import { PostGrid } from "@/components/fan/PostGrid"
import { BottomBar } from "@/components/fan/BottomBar"
import { ChatWidget } from "@/components/fan/ChatWidget"
import { mockProfile, mockPosts } from "@/components/fan/mockData"

export default function FanPage() {
  return (
    <div className="min-h-screen pb-24">
      <ProfileHeader profile={mockProfile} />
      <PostGrid posts={mockPosts} />
      <BottomBar />
      <ChatWidget botName={mockProfile.name} />
    </div>
  )
}
```

- [ ] **Step 3: Verify**

Run: `cd cookbook-web && npx tsc --noEmit`
Expected: no errors.

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/fan`
Expected: a round chat bubble floats bottom-right, above the bottom bar. Clicking it opens a panel with a header, a non-closable disclosure line ("This is an AI, not the real Jordan Rivers."), an empty message area, and a composer. Typing a message and sending it shows the message right-aligned, then three bouncing dots for about a second, then a left-aligned canned reply. Stop the dev server after checking.

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/components/fan/ChatWidget.tsx cookbook-web/app/fan/page.tsx
git commit -m "feat(fan): add floating chat widget with mock typing and canned replies"
```

---

### Task 6: Full walkthrough and lint/typecheck pass

**Files:** none created or modified — verification only, plus any small fixes the walkthrough turns up.

**Interfaces:** none.

- [ ] **Step 1: Run typecheck and lint**

Run: `cd cookbook-web && npx tsc --noEmit`
Expected: no errors.

Run: `cd cookbook-web && npm run lint`
Expected: no errors in `app/fan/` or `components/fan/`. Pre-existing warnings elsewhere in the repo (e.g. `CookbookPage.tsx`) are out of scope — do not fix them here.

- [ ] **Step 2: Manual walkthrough against the spec's Testing checklist**

Run: `cd cookbook-web && npm run dev`, open `http://localhost:3000/fan`, and confirm each of the following (from `docs/superpowers/specs/2026-08-14-fan-web-page-design.md`'s Testing section):

- Banner, pfp, name, and bio render.
- Post grid shows the empty state ("No posts yet."), no fake posts.
- Bottom bar is sticky at the viewport bottom; hovering `+` reveals "More".
- Chat bubble sits above the bottom bar, never overlapped by it.
- Clicking the bubble opens the floating panel; clicking again (or the panel's `X`) closes it.
- The disclosure banner stays visible and has no close control, even as messages scroll.
- Sending a message shows it right-aligned immediately, then a bouncing-dots typing indicator for ~1s, then a left-aligned canned reply.
- Resize the window to a narrow (mobile) width — panel stays within the viewport (`max-w-[calc(100vw-2rem)]`), bottom bar and profile header remain usable.

If any check fails, fix it in the relevant component file from Tasks 1-5 before proceeding. Stop the dev server when done.

- [ ] **Step 3: Commit any fixes**

Only if Step 2 required changes:

```bash
git add cookbook-web/components/fan cookbook-web/app/fan
git commit -m "fix(fan): address walkthrough findings"
```

If no changes were needed, skip this step — there is nothing to commit.
