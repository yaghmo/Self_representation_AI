# Fan web page — social-media-style profile + chat widget

**Date:** 2026-08-14
**Status:** design, approved
**Touches:** new `cookbook-web/app/fan/` route, new `cookbook-web/components/fan/` directory
**Part of:** the Next.js migration's third sub-project (admin API routes → Next.js admin UI → **Next.js fan site** → Docker), per `2026-08-10-nextjs-admin-ui-design.md`'s roadmap comment. This pass builds the fan UI only — no backend wiring.

## Why this exists

CLAUDE.md's stack section splits the app into two surfaces: admin (creator, agentic) and fan (audience, "needs voice and speed"). The admin side has a working Next.js UI (`components/CookbookPage.tsx` and the admin chat work referenced in `2026-08-13-admin-chat-consolidation-design.md`). The fan side has no UI at all yet — `runtime/recall.py` and the non-agent `/chat` path in `service/main.py` exist server-side, but nothing renders them for an audience member. This sub-project is that page.

## Scope

**In scope:**
- A social-media-style profile page (Instagram-like): banner, circular pfp overlapping the banner, bio text, grid of post cards in an empty state (no posts yet — no fake content).
- A sticky bottom bar: placeholder/greyed social icons + a `+` icon that reveals a "More" label on hover.
- A floating chat bubble (sits above the bottom bar, bottom-right) that opens a floating messenger-style panel.
- Chat panel: header, a sticky non-dismissible AI-disclosure banner, scrollable message list, CSS-only typing-dots indicator, composer input.
- Mock/canned bot behavior: user sends a message, a fixed delay shows the typing indicator, then a canned reply appears. No streaming (matches the fan requirement of no streaming needed here).

**Explicitly out of scope, deferred to a later sub-project:**
- Wiring the chat to `service/main.py`'s real `/chat` endpoint and `recall()` tool. This pass is UI-only with mock responses.
- Real post content / any data source for posts — the grid ships in its empty state only.
- Real social links — icons are placeholders, styled but inert (per CLAUDE.md: "the socials will be taken care of later").
- Auth, rate limiting, or any hardening needed before public deployment (CLAUDE.md: "Nothing is public" today).

## Architecture

New route `cookbook-web/app/fan/page.tsx`, a client component (this page is entirely interactive — chat state, hover reveal — no server-rendering benefit, matching the admin UI's own "client components only" precedent from `2026-08-10-nextjs-admin-ui-design.md`).

No new dependencies. `package.json` today has no animation library (no framer-motion) and no `Avatar` primitive in `components/ui/`. The design uses plain CSS (`@keyframes`, `group-hover`) for the typing indicator and hover reveal, and a plain styled `<img>`/`<div>` for the pfp circle — adding a dependency or a new shadcn component for either would be scope creep for a mock-data pass.

## Components

- **`components/fan/ProfileHeader.tsx`** — full-width banner (placeholder image or gradient), circular pfp positioned absolutely, overlapping the banner's bottom-left edge (standard Instagram layout), name + bio text block beneath. All content (name, bio, banner/pfp image) comes from a local mock-data object at the top of `page.tsx`, so swapping in real data later is a one-file change.
- **`components/fan/PostGrid.tsx`** — 3-column CSS grid of square tiles. Takes a `posts` prop (typed, currently passed `[]`); renders an empty-state tile ("No posts yet") when the array is empty. Built to take real posts without changes to its own logic.
- **`components/fan/BottomBar.tsx`** — `fixed bottom-0` sticky bar. Row of greyed-out `lucide-react` icons (placeholder social links, `aria-disabled`, no href yet) plus a `+` icon; hovering the `+` reveals a "More" label via CSS `group-hover` (no JS state).
- **`components/fan/ChatWidget.tsx`** — owns all chat state (`isOpen`, `messages`, `isTyping`) via `useState`. Renders:
  - A floating round button (fixed bottom-right, offset above `BottomBar`'s height) toggling `isOpen`.
  - When open, a floating panel (fixed position, not full-screen — per the approved design) with:
    - Header: bot name/icon + close button.
    - A sticky disclosure banner directly under the header (`sticky top-0` within the scrollable message area, or simply pinned outside the scroll region — whichever keeps it visible regardless of scroll position), text: "This is an AI, not the real [name]." Non-dismissible — no close affordance on this banner.
    - Scrollable message list: user bubbles right-aligned, bot bubbles left-aligned.
    - Typing indicator: three dots, CSS `@keyframes` bounce with staggered `animation-delay` per dot, shown for a fixed ~1s `setTimeout` after the user sends a message, before the canned bot reply is appended.
    - Composer: text input + send button, disabled while `isTyping`.

## Data flow

User types in composer → Enter/send appends a user message to `messages` → `isTyping` set true, typing indicator renders → after ~1s `setTimeout`, a canned reply (fixed string or simple rotation among a couple of strings) is appended to `messages` and `isTyping` set false. Everything is local component state; nothing leaves the browser this pass.

## Error handling

None needed — no network calls in this pass. The only failure mode (e.g., missing mock image asset) degrades to broken-image/placeholder styling, not a thrown error.

## Testing

No JS/TS test framework use here beyond what already exists (Vitest, added for `lib/agentLoop.ts` per the admin UI spec) — this page has no state machine or pure logic worth a unit test; it's markup, CSS, and a couple of `useState` calls. Verified by running `npm run dev` and walking the page by hand: banner/pfp/bio render, empty post grid renders, bottom bar hover reveal works, chat bubble opens the panel, disclosure banner stays visible while scrolling messages, typing indicator animates, canned reply appears after the delay.

## Migration

Net-new route; nothing existing changes. No migration concerns.
