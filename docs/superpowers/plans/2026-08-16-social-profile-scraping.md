# Social Profile: YouTube Scraping, Combined Bio, -Alt Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add best-effort YouTube channel scraping (pfp/follower-count/bio) via `yt-dlp` to the admin social-links tool, a single LLM-combined bio across all socials, and fix the dead `-Alt` flag by detecting it server-side.

**Architecture:** A new `runtime/youtube_scrape.py` wraps `yt-dlp` behind a `scrape_channel(url) -> dict | None` function that never raises. A new `POST /admin/social/preview` route runs URL parsing + isAlt detection + (for YouTube) the scrape, in one round trip the frontend already debounces. `data/profile.json` gains a top-level `bio` field with its own get/set/generate/save routes, reusing the existing `model.chat()` call pattern from `/summarize`.

**Tech Stack:** FastAPI + Pydantic (backend), Next.js/React/TypeScript + shadcn (frontend), `yt-dlp` (new dependency).

**Spec:** `docs/superpowers/specs/2026-08-16-social-profile-scraping-design.md`

## Global Constraints

- No OAuth, no official platform APIs (Instagram Graph API, YouTube Data API, etc.) — scraping only, YouTube only.
- `yt-dlp` goes in `pyproject.toml`'s base `dependencies`, not the `runtime` extra (it's used by `service/main.py`, which is part of the base install).
- Wire format is camelCase, matching every existing `Social*Request` model — no translation layer.
- Every new `/admin/*` route is gated `model = _require_loaded(); _require_agent(model)`, exactly like every existing `/admin/social/*` route.
- `scrape_channel()` is best-effort: any exception (network, yt-dlp internals, missing fields) returns `None`, never raises. A broken scrape must never block adding a link.
- No new frontend test file for UI components — this repo's existing norm is hand-verified admin UI; `lib/admin/socialUrl.test.ts` is the one exception (pure function).
- Backend testing follows this repo's existing convention: an in-process `_self_check()` function per module, run via `python -m <module>`, using `assert` — not pytest.

---

### Task 1: `runtime/youtube_scrape.py` — best-effort YouTube channel scrape

**Files:**
- Create: `runtime/youtube_scrape.py`
- Modify: `pyproject.toml` (add `yt-dlp` to `dependencies`)

**Interfaces:**
- Consumes: nothing project-specific (leaf module, wraps the `yt-dlp` package).
- Produces: `scrape_channel(url: str) -> dict | None` returning `{"pfp_url": str | None, "follower_count": int | None, "bio": str | None}` on success, `None` on any failure. Task 3 imports this.

- [ ] **Step 1: Add `yt-dlp` to `pyproject.toml`**

In `pyproject.toml`, add to the `dependencies` list (after `"uvicorn[standard]>=0.51.0",`):

```toml
    "yt-dlp>=2024.8.6",
```

- [ ] **Step 2: Install it**

Run: `uv sync`
Expected: `yt-dlp` appears in the resolved lockfile, install succeeds.

- [ ] **Step 3: Create `runtime/youtube_scrape.py`**

```python
"""Best-effort YouTube channel metadata via yt-dlp — no API key, no OAuth.

The scrape can fail for any reason (network, yt-dlp internals, YouTube
changing its markup) and must never block adding the link: every caller
treats None as "no scrape data available", the same as any other platform
that never had a scraper in the first place.
"""

from __future__ import annotations


def scrape_channel(url: str) -> dict | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    try:
        with yt_dlp.YoutubeDL(
            {"quiet": True, "skip_download": True, "extract_flat": True}
        ) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not info:
        return None
    return {
        "pfp_url": info.get("thumbnail"),
        "follower_count": info.get("channel_follower_count"),
        "bio": info.get("description"),
    }


def _self_check() -> None:
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_channel("https://www.youtube.com/@YouTube")
    assert result is not None, "expected a successful scrape of a real, stable channel"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"

    # An unrecognized/garbage URL fails cleanly, not with an exception.
    assert scrape_channel("https://www.youtube.com/@this-channel-should-not-exist-xyz123") is None
    assert scrape_channel("not a url at all") is None

    print("youtube_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 4: Run the self-check**

Run: `uv run python -m runtime.youtube_scrape`
Expected: `youtube_scrape: all checks passed`. If `pfp_url`/`follower_count`/`bio` come back empty on the real channel, YouTube's page structure has shifted from what `extract_flat` returns — retry without `"extract_flat": True` (slower, resolves full channel info) before concluding the fields moved elsewhere.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock runtime/youtube_scrape.py
git commit -m "feat(runtime): add best-effort YouTube channel scraping via yt-dlp"
```

---

### Task 2: `runtime/social.py` — top-level `bio` field

**Files:**
- Modify: `runtime/social.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_bio() -> str | None`, `set_bio(text: str) -> None` (new). `list_socials`, `add_social`, `update_social`, `delete_social` keep their exact existing signatures and behavior — only their internal storage shape changes. Task 3 imports `get_bio`/`set_bio` alongside the existing four functions.

- [ ] **Step 1: Extend the self-check with bio assertions (will fail — `get_bio`/`set_bio` don't exist yet)**

In `runtime/social.py`, inside `_self_check()`, right after `assert list_socials() == [], "a fresh directory has no socials"`:

```python
            assert get_bio() is None, "a fresh directory has no bio"
            set_bio("a combined bio")
            assert get_bio() == "a combined bio"
```

And after the `second = add_social(...)` block's assertions (before `delete_social(entry["id"])`):

```python
            assert get_bio() == "a combined bio", "adding a social must not touch the bio"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m runtime.social`
Expected: `NameError: name 'get_bio' is not defined`

- [ ] **Step 3: Rewrite `_load`/`_save` to carry `bio`, add `get_bio`/`set_bio`, update every caller**

Replace the whole `_load` through `delete_social` block:

```python
def _load() -> dict:
    if not PROFILE_JSON_PATH.exists():
        return {"bio": None, "socials": []}
    data = json.loads(PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    return {"bio": data.get("bio"), "socials": data.get("socials", [])}


def _save(bio: str | None, socials: list[dict]) -> None:
    PROFILE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_JSON_PATH.write_text(
        json.dumps({"version": 1, "bio": bio, "socials": socials}, indent=2),
        encoding="utf-8",
    )


def list_socials() -> list[dict]:
    return _load()["socials"]


def get_bio() -> str | None:
    return _load()["bio"]


def set_bio(text: str) -> None:
    data = _load()
    _save(text, data["socials"])


def add_social(fields: dict) -> dict:
    """`fields` must include platform, username, url; may include bio,
    followerCount, pfpUrl, isAlt. Generates `id`, appends, saves."""
    data = _load()
    socials = data["socials"]
    entry = {
        "id": f"{fields['platform']}-{int(time.time() * 1000)}",
        "platform": fields["platform"],
        "username": fields["username"],
        "url": fields["url"],
        "bio": fields.get("bio"),
        "followerCount": fields.get("followerCount"),
        "pfpUrl": fields.get("pfpUrl"),
        "isAlt": fields.get("isAlt", False),
    }
    socials.append(entry)
    _save(data["bio"], socials)
    return entry


def update_social(id: str, fields: dict) -> dict:
    """`fields` should already be filtered to only the keys the caller wants
    changed — this function overwrites exactly what it's given, nothing
    more, so an unset field a caller left out is not touched."""
    data = _load()
    socials = data["socials"]
    for entry in socials:
        if entry["id"] == id:
            entry.update(fields)
            _save(data["bio"], socials)
            return entry
    raise SocialNotFound(id)


def delete_social(id: str) -> None:
    data = _load()
    socials = data["socials"]
    remaining = [e for e in socials if e["id"] != id]
    if len(remaining) == len(socials):
        raise SocialNotFound(id)
    _save(data["bio"], remaining)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m runtime.social`
Expected: `social: all checks passed`

- [ ] **Step 5: Commit**

```bash
git add runtime/social.py
git commit -m "feat(runtime): add a top-level bio field to profile.json"
```

---

### Task 3: `service/main.py` — preview route, bio routes, list-route bio field

**Files:**
- Modify: `service/main.py`

**Interfaces:**
- Consumes: `scrape_channel` from `runtime.youtube_scrape` (Task 1); `get_bio`, `set_bio` from `runtime.social` (Task 2, alongside the existing `SocialNotFound, add_social, delete_social, list_socials, update_social` import).
- Produces: `POST /admin/social/preview`, `POST /admin/social/bio/generate`, `POST /admin/social/bio` routes; `GET /social/list` and `GET /admin/social/list` now return `{"bio": ..., "socials": [...]}`. Task 4's `socialApi.ts` calls these exact routes and shapes.

- [ ] **Step 1: Import the two new dependencies**

In `service/main.py`, change:

```python
from runtime.social import (
    SocialNotFound,
    add_social,
    delete_social,
    list_socials,
    update_social,
)
```

to:

```python
from runtime.social import (
    SocialNotFound,
    add_social,
    delete_social,
    get_bio,
    list_socials,
    set_bio,
    update_social,
)
from runtime.youtube_scrape import scrape_channel
```

- [ ] **Step 2: Add the URL-parsing helper and new request/response models**

After the existing `SocialDeleteRequest` class (around line 356), add:

```python
_SOCIAL_DOMAIN_PLATFORMS = {
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "linkedin.com": "linkedin",
}


def _parse_social_url(url: str) -> tuple[str, str] | None:
    """Server-side mirror of cookbook-web/lib/admin/socialUrl.ts's
    parseSocialUrl — intentionally duplicated, not shared, since one is
    TypeScript and one is Python; see the spec's "Duplicating the URL
    parser" note."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    platform = _SOCIAL_DOMAIN_PLATFORMS.get(host)
    if not platform:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    return platform, segments[0]


class SocialPreviewRequest(BaseModel):
    url: str
    id: str | None = None


class SocialPreviewResponse(BaseModel):
    platform: str
    username: str
    pfpUrl: str | None = None
    followerCount: int | None = None
    bio: str | None = None
    isAlt: bool


class BioGenerateResponse(BaseModel):
    bio: str


class BioSaveRequest(BaseModel):
    bio: str


class BioSaveResponse(BaseModel):
    bio: str


BIO_GENERATE_PROMPT = (
    "Write one short bio (2-4 sentences, no hashtags, no emoji) that combines "
    "the following per-platform bios into a single overview. Do not invent "
    "anything not stated in them."
)
```

- [ ] **Step 3: Update the two list routes to include `bio`**

Change:

```python
@app.get("/social/list")
def social_list() -> dict:
```
...its body's `return {"socials": list_socials()}` to `return {"bio": get_bio(), "socials": list_socials()}`.

And the same for `admin_social_list`'s `return {"socials": list_socials()}` → `return {"bio": get_bio(), "socials": list_socials()}`.

- [ ] **Step 4: Add the three new routes**

Right after `admin_social_delete` (after its closing `return {"deleted": request.id}`), add:

```python
@app.post("/admin/social/preview", response_model=SocialPreviewResponse)
def admin_social_preview(request: SocialPreviewRequest) -> SocialPreviewResponse:
    model = _require_loaded()
    _require_agent(model)
    parsed = _parse_social_url(request.url)
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail="unrecognized link — paste a link from instagram, tiktok, x, youtube, or linkedin",
        )
    platform, username = parsed
    is_alt = any(
        s["platform"] == platform and s["id"] != request.id for s in list_socials()
    )
    pfp_url = follower_count = bio = None
    if platform == "youtube":
        scraped = scrape_channel(request.url)
        if scraped:
            pfp_url = scraped["pfp_url"]
            follower_count = scraped["follower_count"]
            bio = scraped["bio"]
    return SocialPreviewResponse(
        platform=platform,
        username=username,
        pfpUrl=pfp_url,
        followerCount=follower_count,
        bio=bio,
        isAlt=is_alt,
    )


@app.post("/admin/social/bio/generate", response_model=BioGenerateResponse)
def admin_social_bio_generate() -> BioGenerateResponse:
    model = _require_loaded()
    _require_agent(model)
    bios = [s["bio"] for s in list_socials() if s.get("bio")]
    if not bios:
        raise HTTPException(
            status_code=422, detail="no social has a bio yet — nothing to combine"
        )
    transcript = "\n\n".join(bios)
    content = model.chat(
        [Message("user", f"{BIO_GENERATE_PROMPT}\n\n{transcript}")],
        temperature=0.4,
        max_tokens=256,
        thinking=False,
    )
    return BioGenerateResponse(bio=content)


@app.post("/admin/social/bio", response_model=BioSaveResponse)
def admin_social_bio_save(request: BioSaveRequest) -> BioSaveResponse:
    model = _require_loaded()
    _require_agent(model)
    set_bio(request.bio)
    return BioSaveResponse(bio=request.bio)
```

- [ ] **Step 5: Extend the self-check block**

In `_self_check()`, inside the `# -- /social + /admin/social --` block, change the two shape assertions and add new coverage. Replace:

```python
            response = client.get("/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"socials": []}
```

with:

```python
            response = client.get("/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"bio": None, "socials": []}
```

And replace the later:

```python
            response = client.get("/admin/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"socials": []}
```

with:

```python
            response = client.get("/admin/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"bio": None, "socials": []}
```

Then, right before the final `finally:` in that block, add:

```python
            # /admin/social/preview: parses + detects isAlt without touching
            # the network — instagram, not youtube, so this doesn't depend
            # on a live scrape (that's youtube_scrape.py's own self-check).
            response = client.post(
                "/admin/social/add",
                json={
                    "platform": "instagram",
                    "username": "first",
                    "url": "https://instagram.com/first",
                },
            )
            first_id = response.json()["id"]

            response = client.post(
                "/admin/social/preview",
                json={"url": "https://instagram.com/second"},
            )
            assert response.status_code == 200, (response.status_code, response.text)
            body = response.json()
            assert body["platform"] == "instagram"
            assert body["username"] == "second"
            assert body["isAlt"] is True, "a second instagram link must be flagged -Alt"

            # Editing the existing entry's own link is not -Alt against itself.
            response = client.post(
                "/admin/social/preview",
                json={"url": "https://instagram.com/first-renamed", "id": first_id},
            )
            assert response.json()["isAlt"] is False

            response = client.post(
                "/admin/social/preview", json={"url": "not a real url"}
            )
            assert response.status_code == 422, (response.status_code, response.text)

            client.post("/admin/social/delete", json={"id": first_id})

            # /admin/social/bio/generate + /admin/social/bio
            response = client.post("/admin/social/bio/generate")
            assert response.status_code == 422, (response.status_code, response.text)
            assert "nothing to combine" in response.json()["detail"]

            created = client.post(
                "/admin/social/add",
                json={
                    "platform": "youtube",
                    "username": "handle",
                    "url": "https://youtube.com/@handle",
                    "bio": "I make videos about cats.",
                },
            ).json()

            seen.clear()
            response = client.post("/admin/social/bio/generate")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["bio"] == "ok", "the fake model always returns 'ok'"
            assert "I make videos about cats." in seen["messages"][0].content

            response = client.post("/admin/social/bio", json={"bio": "a combined bio"})
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"bio": "a combined bio"}

            response = client.get("/social/list")
            assert response.json()["bio"] == "a combined bio"

            client.post("/admin/social/delete", json={"id": created["id"]})
```

- [ ] **Step 6: Run the self-check**

Run: `uv run python -m service.main`
Expected: `service self-check: ok ...` (no assertion errors).

- [ ] **Step 7: Commit**

```bash
git add service/main.py
git commit -m "feat(service): add social preview/bio routes, fix -Alt detection server-side"
```

---

### Task 4: `cookbook-web/lib/admin/socialApi.ts` — client for the new routes

**Files:**
- Modify: `cookbook-web/lib/admin/socialApi.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: `previewSocial(params: PreviewSocialParams): Promise<PreviewSocialResult>`, `generateBio(): Promise<{ bio: string }>`, `saveBio(bio: string): Promise<{ bio: string }>`. `getSocials()`'s return type changes from `Promise<{ socials: Social[] }>` to `Promise<{ bio: string | null; socials: Social[] }>`. Task 5 and Task 6 import these.

- [ ] **Step 1: Update `getSocials`'s return type**

Change:

```ts
export function getSocials(): Promise<{ socials: Social[] }> {
  return request("/admin/social/list")
}
```

to:

```ts
export function getSocials(): Promise<{ bio: string | null; socials: Social[] }> {
  return request("/admin/social/list")
}
```

- [ ] **Step 2: Add the preview and bio functions**

At the end of the file, after `deleteSocial`:

```ts
export interface PreviewSocialParams {
  url: string
  id?: string
}

export interface PreviewSocialResult {
  platform: string
  username: string
  pfpUrl: string | null
  followerCount: number | null
  bio: string | null
  isAlt: boolean
}

export function previewSocial(params: PreviewSocialParams): Promise<PreviewSocialResult> {
  return request("/admin/social/preview", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export function generateBio(): Promise<{ bio: string }> {
  return request("/admin/social/bio/generate", { method: "POST" })
}

export function saveBio(bio: string): Promise<{ bio: string }> {
  return request("/admin/social/bio", {
    method: "POST",
    body: JSON.stringify({ bio }),
  })
}
```

- [ ] **Step 3: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors — `SocialDialog.tsx`'s existing `const res = await getSocials(); setSocials(res.socials)` still typechecks against the widened return type (the new `bio` field is just unused there until Task 6).

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/lib/admin/socialApi.ts
git commit -m "feat(cookbook-web): add previewSocial/generateBio/saveBio API client"
```

---

### Task 5: `SocialDialog.tsx` — wire the debounced preview call

**Files:**
- Modify: `cookbook-web/components/admin/SocialDialog.tsx`

**Interfaces:**
- Consumes: `previewSocial` from `@/lib/admin/socialApi` (Task 4).
- Produces: no new exports — `SocialDialog`'s own behavior changes (the preview now shows real scraped data and correct `isAlt`).

- [ ] **Step 1: Import `previewSocial` and add the debounce state**

Change the import block's first entry:

```ts
import {
  addSocial,
  deleteSocial,
  getSocials,
  updateSocial,
  type Social,
} from "@/lib/admin/socialApi";
```

to:

```ts
import {
  addSocial,
  deleteSocial,
  getSocials,
  previewSocial,
  updateSocial,
  type Social,
} from "@/lib/admin/socialApi";
```

And change:

```ts
import { useEffect, useState } from "react";
```

to:

```ts
import { useEffect, useRef, useState } from "react";
```

- [ ] **Step 2: Add the debounced preview effect**

Inside `SocialDialog`, right after the `const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });` line, add:

```ts
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewRequestRef = useRef(0);

  useEffect(() => {
    const parsed = parseSocialUrl(form.url);
    if (!parsed) {
      setPreviewLoading(false);
      return;
    }
    const requestId = ++previewRequestRef.current;
    const url = form.url;
    const id = form.id;
    setPreviewLoading(true);
    const timer = setTimeout(() => {
      previewSocial({ url, id })
        .then((data) => {
          if (previewRequestRef.current !== requestId) return; // superseded by a newer edit
          setForm((prev) =>
            prev.url === url
              ? {
                  ...prev,
                  followerCount:
                    data.followerCount != null ? String(data.followerCount) : prev.followerCount,
                  pfpUrl: data.pfpUrl ?? prev.pfpUrl,
                  bio: data.bio ?? prev.bio,
                  isAlt: data.isAlt,
                }
              : prev
          );
        })
        .catch(() => {
          // best-effort — a failed preview call just means no scraped data,
          // the local parseSocialUrl-derived preview still shows
        })
        .finally(() => {
          if (previewRequestRef.current === requestId) setPreviewLoading(false);
        });
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.url, form.id]);
```

- [ ] **Step 3: Add the loading indicator to the preview block**

`refresh()` needs no change in this task — `res.socials` already exists on the widened `getSocials()` return type from Task 4; `res.bio` gets consumed in Task 6. Change:

```tsx
          {preview && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">This is how it will show:</p>
```

to:

```tsx
          {preview && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                {previewLoading ? "This is how it will show (scraping…):" : "This is how it will show:"}
              </p>
```

- [ ] **Step 4: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add cookbook-web/components/admin/SocialDialog.tsx
git commit -m "feat(cookbook-web): debounce a real preview call, fixing -Alt and adding scraped data"
```

---

### Task 6: `BioSection.tsx` — combined bio generate/confirm UI

**Files:**
- Create: `cookbook-web/components/admin/BioSection.tsx`
- Modify: `cookbook-web/components/admin/SocialDialog.tsx`

**Interfaces:**
- Consumes: `generateBio`, `saveBio` from `@/lib/admin/socialApi` (Task 4).
- Produces: `BioSection({ bio, onSaved }: { bio: string | null; onSaved: () => void })`. `SocialDialog` renders this above the list, passing the `bio` field from `getSocials()`'s response.

- [ ] **Step 1: Create `BioSection.tsx`**

```tsx
"use client";

import { useState } from "react";
import { generateBio, saveBio } from "@/lib/admin/socialApi";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function BioSection({
  bio,
  onSaved,
}: {
  bio: string | null;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setBusy(true);
    setError(null);
    try {
      const result = await generateBio();
      setDraft(result.bio);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (draft === null) return;
    setBusy(true);
    setError(null);
    try {
      await saveBio(draft);
      setDraft(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Bio</p>
      {draft === null ? (
        <>
          <p className="text-xs text-muted-foreground">{bio || "no bio yet."}</p>
          <Button variant="outline" size="sm" onClick={handleGenerate} disabled={busy}>
            {busy ? "Generating…" : "Generate"}
          </Button>
        </>
      ) : (
        <>
          <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
          <div className="flex gap-2">
            <Button size="sm" onClick={handleConfirm} disabled={busy}>
              Confirm
            </Button>
            <Button variant="outline" size="sm" onClick={() => setDraft(null)} disabled={busy}>
              Cancel
            </Button>
          </div>
        </>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `SocialDialog.tsx`**

Add the import, right after the `platformIcon` import line:

```ts
import { BioSection } from "@/components/admin/BioSection";
```

Add a `bio` state next to `socials`:

```ts
  const [socials, setSocials] = useState<Social[]>([]);
  const [bio, setBio] = useState<string | null>(null);
```

Update `refresh()` to capture it:

```ts
  async function refresh() {
    setLoading(true);
    try {
      const res = await getSocials();
      setSocials(res.socials);
      setBio(res.bio);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }
```

Render `<BioSection>` between the add/update form panel and the list. Change:

```tsx
        <Separator />

        {loading ? (
```

to:

```tsx
        <Separator />

        <BioSection bio={bio} onSaved={refresh} />

        <Separator />

        {loading ? (
```

- [ ] **Step 3: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add cookbook-web/components/admin/BioSection.tsx cookbook-web/components/admin/SocialDialog.tsx
git commit -m "feat(cookbook-web): add combined-bio generate/confirm UI above the socials list"
```

---

### Task 7: End-to-end verification

**Files:** none (manual verification only).

- [ ] **Step 1: Start both backends and the frontend**

```bash
uv run uvicorn service.main:app --port 8000
cd cookbook-web && npm run dev
```

- [ ] **Step 2: Load the model, open the admin Profile dialog**

Navigate to `http://localhost:3000/admin`, load the model from the sidebar, click the Profile card's "View/Update Profile".

- [ ] **Step 3: Add a YouTube link, verify the scrape**

Paste a real YouTube channel URL (e.g. `https://www.youtube.com/@YouTube`) into the Link field. Within ~400ms the preview should show "scraping…" then settle to show a real profile picture and follower count. Click Confirm — the row appears in the list with the scraped pfp/followers/bio.

- [ ] **Step 4: Verify -Alt detection**

Add a second link for a platform you already have an entry for (e.g. a second Instagram URL). The preview should show the "-Alt" tag before you even click Confirm.

- [ ] **Step 5: Verify Update is still link-only**

Click the pencil icon on an existing entry — only the Link field should be editable, matching the existing behavior (Task 5/6 didn't touch this).

- [ ] **Step 6: Generate the combined bio**

With at least one social carrying a non-empty bio (the YouTube one just added should have one from the scrape), click "Generate" in the new Bio section. A draft appears in an editable textarea. Click Confirm — it saves and displays above the list. Reopen the dialog to confirm it persisted.

- [ ] **Step 7: Verify the zero-bio error path**

Delete every social (or start from a fresh `data/profile.json`), click "Generate" — expect the error "no social has a bio yet — nothing to combine" to surface in the UI, not a crash.

- [ ] **Step 8: Run the full backend + frontend self-checks one more time**

```bash
uv run python -m runtime.youtube_scrape
uv run python -m runtime.social
uv run python -m service.main
cd cookbook-web && npm run typecheck && npm test
```

Expected: everything green.
