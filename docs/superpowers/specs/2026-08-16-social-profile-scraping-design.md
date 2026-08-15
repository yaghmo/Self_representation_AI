# Social profile: YouTube scraping + combined bio + -Alt fix

Follow-up to `docs/superpowers/specs/2026-08-15-admin-social-profile-tool-design.md`
("Auto-discovery ... is explicitly out of scope for this spec and is a
separate, later follow-up"). This is that follow-up — scoped down hard from
the original vision (paste any link, scrape every platform, graph-discover
more accounts) to something buildable without signing up for anything.

## Why scraping, not an official API

The creator does not want to create a developer account or API key for any
platform — not even YouTube's free, keyless-adjacent Data API (it still
means standing up a Google Cloud project). That rules out every official
platform API for this pass; scraping a public page is the only path left
that needs zero signup.

This does **not** need a CLAUDE.md amendment. That file's hard constraint —
"a third-party API is a supported fallback for the LLM role only" — is
about the model backend choice (local vs. hosted LLM), not a general ban on
outbound HTTP. A plain `GET` of a public channel page is not "a third-party
API" in the sense that rule addresses; there's no account, no contract, no
auth. It carries its own, separate risk (the page markup can change, and
scraping is against most platforms' ToS even without a registered API) —
that risk is accepted here explicitly, scoped to one platform, not decided
silently.

## Scope: YouTube only

Instagram and TikTok are JS-rendered and actively bot-blocked; scraping
them reliably needs a headless browser and constant maintenance against
detection. YouTube channel pages are still server-rendered enough for a
plain HTTP fetch. X and LinkedIn are left completely alone.

Adding a `tiktok`/`instagram`/`x`/`linkedin` link still works exactly as
today (`parseSocialUrl`, manual link-only add/update) — it just never gets
auto-filled pfp/follower-count/bio. The new `/admin/social/preview` round
trip described below fires for every recognized platform (it's also how
the -Alt fix gets computed), but only a `youtube.com` URL causes that
route to actually invoke `yt-dlp`; every other platform gets a preview
response with no scrape, same as today's local-only parse.

## Mechanism: `yt-dlp`, not hand-rolled parsing

Two ways to pull channel metadata without an API key:

1. Regex out YouTube's embedded `ytInitialData` JSON from the raw page
   HTML with `requests` — zero new dependencies, but that JSON's shape is
   undocumented and drifts; the parser becomes something *we* have to keep
   patching every time YouTube changes it.
2. Use `yt-dlp` (already the de facto standard for this exact problem,
   actively maintained specifically to survive YouTube's changes) to pull
   `uploader`, `thumbnail`, `channel_follower_count`, `description` from a
   channel URL via `YoutubeDL(...).extract_info(url, download=False)`.

Going with **yt-dlp** — one new dependency, but the fragility risk moves to
an upstream project that exists to absorb it, instead of code this repo
has to hand-maintain against an undocumented JSON blob.

## Backend

### `runtime/youtube_scrape.py` (new)

```python
def scrape_channel(url: str) -> dict | None:
    """Best-effort. Returns {"pfp_url", "follower_count", "bio"} or None
    on any failure — a broken scrape must never block adding the link."""
```

Wraps `yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True}).extract_info(url, download=False)`
in a `try/except Exception`, mapping `thumbnail` → `pfp_url`,
`channel_follower_count` → `follower_count`, `description` → `bio`. Any
exception (network, yt-dlp internal, missing fields) returns `None` — the
caller falls back to platform+username only, same as every other platform
today.

### `pyproject.toml`

Add `yt-dlp` to `dependencies`.

### `service/main.py` — `POST /admin/social/preview`

```
body: { url: str, id?: str }   # id present only when this is an Update
returns: { platform, username, pfpUrl?, followerCount?, bio?, isAlt }
```

Gated like every other `/admin/social/*` route (`_require_loaded()` +
`_require_agent(model)` — the existing convention here uses that pair as
the admin-surface check, not because this route calls the model). Runs
`parseSocialUrl`-equivalent server-side (reuses the same domain table —
see "Duplicating the URL parser" below), and when `platform == "youtube"`,
calls `scrape_channel`. `isAlt` is computed here too: `True` when
`list_socials()` already has an entry for that platform (see the -Alt fix
below).

### `runtime/social.py` — top-level `bio` field

`_load`/`_save` currently hardcode `{"version": 1, "socials": [...]}`.
Extend to `{"version": 1, "bio": str | None, "socials": [...]}`. New
functions:

```python
def get_bio() -> str | None: ...
def set_bio(text: str) -> None: ...
```

`GET /admin/social/list` and `GET /social/list` both add `"bio"` to their
response alongside `"socials"` — the combined bio is exactly as public as
the per-social bios it's built from (spec 1's existing reasoning: "a fan
clicking the Instagram icon sees the bio ... on Instagram itself anyway").

### `service/main.py` — `POST /admin/social/bio/generate` and `POST /admin/social/bio`

`generate` builds a prompt from every non-empty `social.bio` in
`list_socials()`, calls `model.chat(...)` (same pattern as `/summarize`),
and returns the draft **without saving it**. `POST /admin/social/bio` with
`{ "bio": str }` is the actual save, called separately when the creator
confirms the draft. Both gated `_require_loaded()` + `_require_agent()`;
`generate` needs the model for real this time.

If there are zero non-empty per-social bios, `generate` returns a 422 with
a clear message ("no social has a bio yet — nothing to combine") rather
than asking the model to invent one from nothing.

## The -Alt fix

Today `isAlt` is dead: the form that could set it was removed, so every
add saves `isAlt: false` regardless of whether the platform already has an
entry. Fix moves detection server-side, into `POST /admin/social/preview`:
the request body carries an optional `id` (sent when `form.id` is set,
i.e. this is an Update, not an Add), and the route computes `isAlt` as
"does `list_socials()` already contain this platform, in an entry other
than `id`."

The preview response's `isAlt` flows straight into the `SocialRow` preview
(the "-Alt" tag already renders whenever `isAlt` is true — no new UI, it
was already wired, just never fed real data) and into the save payload on
Confirm.

## Frontend (`cookbook-web`)

### Duplicating the URL parser

`lib/admin/socialUrl.ts`'s `parseSocialUrl` already does platform+username
parsing client-side with zero network calls — that stays exactly as-is for
the *first-keystroke* feedback (instant, no round-trip). The new
`/admin/social/preview` call is a **second**, debounced step once a
recognized URL is fully parsed: it re-derives platform+username
server-side (so the one bit of parsing logic isn't split between two
languages long-term, this is accepted duplication for now, not a refactor
trigger) and adds the scrape + isAlt on top.

### `SocialDialog.tsx`

- `handleUrlChange` keeps its current instant local-parse behavior (so the
  input never feels laggy), but now also kicks off a debounced (400ms)
  call to `/admin/social/preview` when `parseSocialUrl` recognizes the
  URL. A `previewLoading` boolean drives a small spinner/"scraping…" state
  in the preview card while the call is in flight.
- The preview response's `pfpUrl`/`followerCount`/`bio`/`isAlt` get merged
  into `form` (still never rendered as editable inputs — same "link only"
  UI as today, these fields just silently carry the scraped/detected
  values through to `handleSave`).
- A non-YouTube link (or a YouTube link where the scrape failed) shows the
  exact same preview it does today — icon, placeholder avatar, username,
  no follower count, no bio, isAlt from the same detection logic (which
  works for every platform, not just YouTube).

### New "Bio" section, above the list

- Reads `bio` from the same `GET /admin/social/list` response (already
  extended above) alongside `socials`.
- Shows the saved bio as plain text (or "no bio yet." — same placeholder
  convention as per-social bios) plus a **Generate** button.
- Generate calls `POST /admin/social/bio/generate`, puts the returned
  draft into an editable `Textarea` beneath the display text, with
  **Confirm** (calls `POST /admin/social/bio`, then refetches) and
  **Cancel** (discards the draft, no call).

## Testing

- `runtime/youtube_scrape.py` — self-check block per this repo's pattern
  (`ponytail`'s "leave one runnable check"): a `demo()`/`__main__` guard
  that scrapes one real, stable YouTube channel and asserts the three
  fields come back non-empty. This one hits the real network — acceptable
  here since there is no mock-able seam worth building for a single
  best-effort scraper, and the self-check pattern in this repo already
  accepts that (e.g. `runtime/model.py`'s self-check needs a real model).
- `runtime/social.py`'s existing self-check gets the `bio`/`get_bio`/
  `set_bio` assertions added alongside what's already there.
- `service/main.py`'s existing in-process self-check block gets the three
  new routes exercised the same way `/admin/social/*` already is.
- No new frontend test file — this repo's existing norm (per the original
  spec) is hand-verified UI for admin components; `socialUrl.test.ts`
  stays as the one exception (pure function, easy to unit test).

## Out of scope, still

Instagram/TikTok/X/LinkedIn scraping or APIs, OAuth of any kind, and
auto-discovery/graph-traversal from a Linktree — all still explicitly
deferred, same as the original spec said.
