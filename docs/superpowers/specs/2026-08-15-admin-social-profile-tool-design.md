# Admin social profile tool

## Problem

The creator has no way to attach their social accounts (Instagram, TikTok,
etc.) to their portfolio. The fan-facing `BottomBar` already ships two
disabled placeholder icons waiting for this. The admin console has no way to
manage this data either.

The eventual vision (stated by the user): paste a Linktree, have the tool
scrape it and every linked platform, auto-detect further accounts referenced
in each platform's bio (graph-like discovery), and confirm each one via a
scraped preview (pfp, username, follower count) before it's saved.

## Scope: v1 is manual-only, no fetching

Decided during brainstorming: **v1 does no scraping, no HTTP requests to any
social platform, no third-party API calls.** This is a deliberate,
significant scope cut from the vision above, made for two reasons:

1. This project's `CLAUDE.md` has a hard stack rule — a third-party API is a
   supported fallback for the LLM role only. Instagram/TikTok scraping would
   either mean unauthenticated HTML scraping (fragile: JS-rendered pages,
   bot-blocking, ToS risk) or official APIs (OAuth, app review, a linked
   Business account — real setup friction, and arguably the kind of
   third-party dependency the stack rule exists to avoid).
2. It lets the data model, the CRUD admin UI, and the fan-facing wiring get
   built and proven out now, independent of that unresolved question.

**Auto-discovery (scraping, graph traversal, "is this yours?" preview
confirmation, popularity-based ranking when duplicates are found) is
explicitly out of scope for this spec and is a separate, later follow-up.**
When it's built, it should slot into the same data model and the same
`SocialDialog` UI this spec defines — see "Forward compatibility" below.

## Data model

New file: `data/profile.json` — gitignored like the rest of `data/` (no
`.gitignore` change needed, it already denies `data/` by default). Does not
exist until the first social is added; its absence is exactly the "no
profile linked to this account yet" empty state.

```json
{
  "version": 1,
  "socials": [
    {
      "id": "instagram-1755280800000",
      "platform": "instagram",
      "username": "handle",
      "url": "https://instagram.com/handle",
      "bio": "Free-text bio, manually entered.",
      "followerCount": 12345,
      "pfpUrl": "https://example.com/pfp.jpg",
      "isAlt": false
    }
  ]
}
```

Field notes:

- `id` — server-generated on add, `<platform>-<epoch-ms>`. Stable, used by
  update/delete.
- `platform` — a lowercase string (`"instagram"`, `"tiktok"`, `"x"`, ...).
  No closed enum — the admin form offers a `<select>` of common platforms
  plus a free-text "Other" option, since the set of platforms a creator
  might link is not fixed.
- `followerCount`, `pfpUrl`, `bio` — all optional (`null` if omitted). None
  of them are fetched; the creator types what they want to show.
- `isAlt` — `false` by default. `true` marks a second-or-later entry for a
  platform that already has one. Purely a display tag (renders an "-Alt"
  label next to the entry) — it does not change any ordering or validation
  logic in v1, since nothing is being auto-ranked.

This is **not** subject to the bible's cite/confirm-diff machinery
(`character.md`/`sources.md`'s `Proposal` → confirm → `apply()` gate,
`runtime/tools.py`). That machinery exists specifically for the "creator
authors, nothing else does" citation-tracking rule on character claims.
Social links are simple structured contact data the creator enters
directly — no cite, no authorship question, no redaction-policy
interaction (these are links the creator wants public, not source material
being logged for the character bible).

## Backend

New routes in `service/main.py`, following the existing route patterns
(`_require_loaded`, `_require_agent` for the admin surface; the fan surface
gets a plain unauthenticated read).

**Admin surface** (agent-gated, like `/admin/story/*`):

- `GET /admin/social/list` → `{ "socials": [...] }` — full list, every
  field, for the admin UI.
- `POST /admin/social/add` — body: `{ platform, username, url, bio?,
  followerCount?, pfpUrl?, isAlt? }`. Generates `id`, appends to
  `data/profile.json`, creates the file if it doesn't exist yet. Returns
  the created entry.
- `POST /admin/social/update` — body: `{ id, ...fields to change }`.
  404 if `id` doesn't exist. Returns the updated entry.
- `POST /admin/social/delete` — body: `{ id }`. 404 if `id` doesn't exist.
  Returns `{ deleted: id }`.

No `Proposal`/apply two-step, no `.backups` snapshot — direct writes, same
trust level as the existing `/admin/voice/*` routes (simple admin-owned
state, not corpus content).

**Fan surface** (public, no agent gate — this mirrors `recall`'s
read-only/no-write rule for the fan path, but doesn't need model/LLM
involvement at all, it's a flat file read):

- `GET /social/list` → `{ "socials": [...] }` — same shape as the admin
  list. All fields are already meant to be public (a fan clicking the
  Instagram icon sees the bio and follower count on Instagram itself
  anyway), so nothing is filtered out.

Both `GET` routes return `{ "socials": [] }` (empty list) if
`data/profile.json` doesn't exist yet — no 424. There's no analogous "this
deployment isn't configured for this feature" case the way there is for the
character profile (`ProfileMissing` in `bible.py`); an empty social list is
a normal, expected state for a fresh instance, not an error. The admin UI's
true-empty-state ("nothing added yet") and "zero socials after deleting
everything" collapse to the same state and show the same message ("No
profile linked to this account yet").

## Admin frontend

**`cookbook-web/components/admin/SocialCard.tsx`** — new file, rendered in
`Sidebar.tsx` alongside the existing generation-params and snapshot-restore
sections. Shows a count ("3 socials linked") or "No profile linked yet",
plus a **View/Update Profile** button.

**`cookbook-web/components/admin/SocialDialog.tsx`** — new file, opened by
the button above. Fetches `GET /admin/social/list` on open. Renders:

- One row per existing social: platform icon, `username`, `followerCount`
  (if set), an "-Alt" tag if `isAlt`, and **Update** / **Delete** buttons at
  the far right (your exact requested layout).
- An **Add** form: a link/URL field, a platform `<select>` (or "Other" +
  free-text), username, bio (textarea), follower count (number), pfp URL,
  and an `isAlt` checkbox — shown only when the selected platform already
  has at least one entry in the list.

**The one "paste a link" affordance kept from your original vision, done
with zero network requests:** typing or pasting into the URL field runs a
small client-side parser (`parseSocialUrl(url): { platform, username } |
null` in `cookbook-web/lib/admin/socialUrl.ts`) that recognizes common
platform domains (`instagram.com`, `tiktok.com`, `x.com`/`twitter.com`,
`youtube.com`, `linkedin.com`) and prefills the platform `<select>` and
username field from the URL's path. Unrecognized domains leave both fields
for manual entry. This is pure string parsing — no `fetch()` call, nothing
that touches the "no third-party API" boundary.

**Update** re-opens the Add form pre-filled with the entry's current
values, keyed by `id`, submitting through `POST /admin/social/update`
instead of `/add`.

**Delete** asks for confirmation (a native `confirm()` is fine here — this
is admin-only tooling, not the fan surface, and the existing admin console
already uses plain browser-native UI, no custom modal system) then calls
`POST /admin/social/delete`.

Styling: plain inline styles / CSS, matching the rest of the admin console
(`ChatPanel.tsx`, `Sidebar.tsx`, etc.) — no Tailwind classes, consistent
with the "move in as-is, don't restyle" decision from the admin-merge work
that just landed.

## Fan frontend

**`cookbook-web/components/fan/BottomBar.tsx`** — modified. On mount,
fetches `GET /social/list` (via a new `getSocials()` in
`cookbook-web/lib/chatApi.ts`, or a new small `lib/socialApi.ts` if
`chatApi.ts` shouldn't grow unrelated responsibilities — leaning toward a
separate file since `chatApi.ts` is scoped to `/chat` specifically).
Replaces the two placeholder `Link2` spans with one `<a>` per social,
`href={social.url}`, `target="_blank"`, icon from a small
`platformIcon(platform)` lookup (lucide-react's `Instagram` icon where a
match exists, `Link2` as the fallback for everything else — no new icon
library dependency). The `+`/"More" button is untouched.

Loading state: render nothing extra while fetching (the bar already shows
the `+` button immediately; social icons pop in once loaded — no skeleton
needed, this is a fast local-network call in dev and a fast static-file
read in any deployment).

Empty state (zero socials, e.g. a fresh instance before the creator adds
any): render just the `+` button, same as today, no placeholder icons.

## Forward compatibility (for the later auto-discovery follow-up)

Not building this now, but the data model and UI are shaped to make it a
clean addition later:

- `profile.json`'s schema doesn't change — auto-discovery would populate
  the same fields, just via a fetch instead of a form.
- The `SocialDialog`'s Add form is where a future "Auto-discover" button
  would live, alongside the manual fields — triggering a fetch that
  pre-fills the form (instead of leaving it blank) and, for the
  Linktree-style graph traversal, driving a sequence of confirm dialogs
  reusing the same row-rendering this spec already builds.
- `isAlt` and multi-entry-per-platform already exist in the schema, so
  future "only suggest the most popular account" ranking logic has
  something to rank against without a migration.

## Testing

- Backend: a `_self_check()`-style block in `service/main.py` (matching
  the existing pattern) exercising add/list/update/delete against a temp
  `profile.json`, plus the agent-gate check on the four admin routes and
  the public/no-gate check on `/social/list`.
- Frontend: `parseSocialUrl()` gets a small `lib/admin/socialUrl.test.ts`
  (vitest, now available in `cookbook-web` from the admin-merge work) —
  pure function, easy table-driven test over the recognized domains plus
  an unrecognized-domain case.
- Manual: add a social through the admin dialog, confirm it appears in
  `BottomBar` on `/fan`; update it, confirm the change reflects; delete it,
  confirm `BottomBar` falls back to just the `+` button.

## Out of scope (explicitly)

- Any scraping, HTTP fetch to a social platform, or third-party API call.
- The "is this yours?" confirm-preview dialog (nothing is scraped to
  preview in v1).
- Graph traversal / auto-detecting further accounts from a bio.
- Popularity-based ranking when duplicate platforms exist (`isAlt` is
  manual in v1).
- Any change to `character.md`, `sources.md`, or the bible tools.
