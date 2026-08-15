# Admin Social Profile Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the creator manually add/update/delete their social accounts through an admin dialog, stored in `data/profile.json`, and show them as real linked icons on the fan-facing `BottomBar` instead of the current disabled placeholders.

**Architecture:** A plain-CRUD data layer (`runtime/social.py`) reading/writing `data/profile.json` directly — no scraping, no bible-style confirm/snapshot machinery. Five new `service/main.py` routes: four agent-gated admin routes (list/add/update/delete) and one public unauthenticated fan route (list). Two new admin components (`SocialCard` in the sidebar, `SocialDialog` for the CRUD form) styled like the rest of the plain-CSS admin console. `BottomBar` fetches the public route on mount and renders real social icons.

**Tech Stack:** Python/FastAPI (`service/main.py`), Next.js/React/TypeScript (`cookbook-web`), vitest (already added to `cookbook-web` from the admin-merge work).

**Spec:** `docs/superpowers/specs/2026-08-15-admin-social-profile-tool-design.md`

## Global Constraints

- No scraping, no HTTP fetch to any social platform, no third-party API calls — v1 is entirely manual entry (spec's core scope cut).
- `profile.json`'s fields are exactly: `id`, `platform`, `username`, `url`, `bio`, `followerCount`, `pfpUrl`, `isAlt`. These are camelCase **both on disk and on the wire** (request/response JSON) — a deliberate choice for this feature so the data model, the API, and the frontend types all share one shape with no translation layer, even though it diverges from this file's other endpoints (which are snake_case, e.g. `max_tokens`, `story_id`).
- No `Proposal`/confirm-diff/`.backups` snapshot machinery — direct reads/writes, same trust level as the existing `/admin/voice/*` routes.
- The four `/admin/social/*` routes follow the existing house convention every other `/admin/*` route uses: `_require_loaded()` then `_require_agent(model)` — even though this feature never touches the LLM itself, matching established pattern beats a one-off exception.
- `GET /social/list` is the one public, unauthenticated route — no `_require_loaded()`, no agent gate. It's a flat file read, nothing to do with the model.
- Admin frontend styling is plain inline styles/CSS, matching `ChatPanel.tsx`/`Sidebar.tsx`/`ConfirmDialog.tsx` — no Tailwind classes in `components/admin/*`.
- Do not touch `character.md`, `sources.md`, or the bible tools (`runtime/tools.py`'s `Proposal`/`snapshot` machinery is read for reference, not modified).

---

## Task 1: Data layer — `runtime/social.py`

**Files:**
- Create: `runtime/social.py`

**Interfaces:**
- Produces: `PROFILE_JSON_PATH: Path`, `list_socials() -> list[dict]`, `add_social(fields: dict) -> dict`, `update_social(id: str, fields: dict) -> dict`, `delete_social(id: str) -> None`, `class SocialNotFound(Exception)` — all consumed by Task 2's `service/main.py` routes.

- [ ] **Step 1: Write the module**

Create `runtime/social.py`:

```python
"""Manual CRUD for the creator's linked social accounts.

No scraping, no third-party API calls — every field here is typed in by the
creator through the admin dialog. `data/profile.json` is a flat list, not
subject to the bible's cite/confirm-diff machinery in `tools.py`: this is
contact data the creator wants public, not a claim about the character that
needs a citation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .bible import PROFILE_PATH

PROFILE_JSON_PATH = PROFILE_PATH.parent / "profile.json"


class SocialNotFound(Exception):
    """Raised by update_social/delete_social when `id` doesn't match anything."""


def _load() -> list[dict]:
    if not PROFILE_JSON_PATH.exists():
        return []
    data = json.loads(PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    return data.get("socials", [])


def _save(socials: list[dict]) -> None:
    PROFILE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_JSON_PATH.write_text(
        json.dumps({"version": 1, "socials": socials}, indent=2),
        encoding="utf-8",
    )


def list_socials() -> list[dict]:
    return _load()


def add_social(fields: dict) -> dict:
    """`fields` must include platform, username, url; may include bio,
    followerCount, pfpUrl, isAlt. Generates `id`, appends, saves."""
    socials = _load()
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
    _save(socials)
    return entry


def update_social(id: str, fields: dict) -> dict:
    """`fields` should already be filtered to only the keys the caller wants
    changed — this function overwrites exactly what it's given, nothing
    more, so an unset field a caller left out is not touched."""
    socials = _load()
    for entry in socials:
        if entry["id"] == id:
            entry.update(fields)
            _save(socials)
            return entry
    raise SocialNotFound(id)


def delete_social(id: str) -> None:
    socials = _load()
    remaining = [e for e in socials if e["id"] != id]
    if len(remaining) == len(socials):
        raise SocialNotFound(id)
    _save(remaining)


def _self_check() -> None:
    import tempfile

    global PROFILE_JSON_PATH
    original = PROFILE_JSON_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            PROFILE_JSON_PATH = Path(tmp) / "profile.json"

            assert list_socials() == [], "a fresh directory has no socials"

            entry = add_social({
                "platform": "instagram",
                "username": "handle",
                "url": "https://instagram.com/handle",
                "bio": "a bio",
                "followerCount": 100,
            })
            assert entry["id"].startswith("instagram-")
            assert entry["isAlt"] is False, "isAlt defaults to False"
            assert entry["pfpUrl"] is None, "unset optional fields are None"
            assert list_socials() == [entry]

            updated = update_social(entry["id"], {"followerCount": 200})
            assert updated["followerCount"] == 200
            assert updated["bio"] == "a bio", "fields not in the update are untouched"
            assert list_socials()[0]["followerCount"] == 200

            second = add_social({
                "platform": "instagram",
                "username": "handle2",
                "url": "https://instagram.com/handle2",
                "isAlt": True,
            })
            assert second["isAlt"] is True
            assert len(list_socials()) == 2

            delete_social(entry["id"])
            remaining = list_socials()
            assert len(remaining) == 1
            assert remaining[0]["id"] == second["id"]

            try:
                update_social("no-such-id", {"bio": "x"})
            except SocialNotFound:
                pass
            else:
                raise AssertionError("update_social accepted an unknown id")

            try:
                delete_social("no-such-id")
            except SocialNotFound:
                pass
            else:
                raise AssertionError("delete_social accepted an unknown id")
    finally:
        PROFILE_JSON_PATH = original

    print("social: all checks passed")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run the self-check**

Run: `python -m runtime.social`
Expected: `social: all checks passed`

- [ ] **Step 3: Commit**

```bash
git add runtime/social.py
git commit -m "feat(runtime): add manual social-links CRUD data layer"
```

---

## Task 2: Backend routes — `service/main.py`

**Files:**
- Modify: `service/main.py:320-323` (new Pydantic models, inserted before the `# ---- model --` comment)
- Modify: `service/main.py:538-541` (new public route, inserted between `/model/unload` and `/chat`)
- Modify: `service/main.py:1000-1003` (four new admin routes, inserted between `/admin/voice/sample` and `_self_check`)
- Modify: `service/main.py:1003` onward (`_self_check()` additions)

**Interfaces:**
- Consumes: `list_socials`, `add_social`, `update_social`, `delete_social`, `SocialNotFound` from `runtime.social` (Task 1).
- Produces: `GET /social/list`, `GET /admin/social/list`, `POST /admin/social/add`, `POST /admin/social/update`, `POST /admin/social/delete` — consumed by Task 3's frontend clients.

- [ ] **Step 1: Add the import**

Edit `service/main.py`, in the import block near the top (alongside the other `from runtime...` imports, e.g. right after the `from runtime.recall import RECALL_SCHEMA, recall` line):

```diff
 from runtime.recall import RECALL_SCHEMA, recall
+from runtime.social import (
+    SocialNotFound,
+    add_social,
+    delete_social,
+    list_socials,
+    update_social,
+)
```

- [ ] **Step 2: Add the request models**

Edit `service/main.py`, insert right before the `# -------------------------------------------------------------------- model --` comment (currently line 323, right after `StoryProposeRequest`'s closing `events: list[StoryEvent] = Field(default_factory=list)` line):

```python
class SocialAddRequest(BaseModel):
    # camelCase deliberately — see Global Constraints in the plan this
    # implements: this feature's wire format matches profile.json's on-disk
    # shape exactly, no translation layer.
    platform: str
    username: str
    url: str
    bio: str | None = None
    followerCount: int | None = None
    pfpUrl: str | None = None
    isAlt: bool = False


class SocialUpdateRequest(BaseModel):
    id: str
    platform: str | None = None
    username: str | None = None
    url: str | None = None
    bio: str | None = None
    followerCount: int | None = None
    pfpUrl: str | None = None
    isAlt: bool | None = None


class SocialDeleteRequest(BaseModel):
    id: str
```

- [ ] **Step 3: Add the public route**

Edit `service/main.py`, insert between `model_unload()`'s closing `return {"status": "unloaded", "model": name}` and the `@app.post("/chat", response_model=ChatResponse)` line:

```python
@app.get("/social/list")
def social_list() -> dict:
    """Public, unauthenticated — the fan `BottomBar` calls this directly.
    A flat file read, nothing to do with the model, so no `_require_loaded()`
    and no agent gate."""
    return {"socials": list_socials()}
```

- [ ] **Step 4: Add the four admin routes**

Edit `service/main.py`, insert between `admin_voice_sample()`'s closing `return {"status": sample_status()}` and `def _self_check() -> None:`:

```python
@app.get("/admin/social/list")
def admin_social_list() -> dict:
    model = _require_loaded()
    _require_agent(model)
    return {"socials": list_socials()}


@app.post("/admin/social/add")
def admin_social_add(request: SocialAddRequest) -> dict:
    model = _require_loaded()
    _require_agent(model)
    return add_social(request.model_dump())


@app.post("/admin/social/update")
def admin_social_update(request: SocialUpdateRequest) -> dict:
    model = _require_loaded()
    _require_agent(model)
    fields = request.model_dump(exclude_unset=True, exclude={"id"})
    try:
        return update_social(request.id, fields)
    except SocialNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"no social with id {exc}"
        ) from exc


@app.post("/admin/social/delete")
def admin_social_delete(request: SocialDeleteRequest) -> dict:
    model = _require_loaded()
    _require_agent(model)
    try:
        delete_social(request.id)
    except SocialNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"no social with id {exc}"
        ) from exc
    return {"deleted": request.id}
```

- [ ] **Step 5: Add self-check coverage**

Edit `service/main.py`'s `_self_check()` function — insert a new block right before the final `if data_available: ... print(...)` lines at the end of the function (i.e., right after the `-- /admin/voice --` block's closing `_model.agent = False`):

```python
    # -- /social + /admin/social ----------------------------------------------
    import runtime.social as social_module

    with tempfile.TemporaryDirectory() as tmp:
        original_profile_json = social_module.PROFILE_JSON_PATH
        social_module.PROFILE_JSON_PATH = Path(tmp) / "profile.json"
        try:
            # The public route needs no loaded model and no agent mode —
            # it must work even in whatever state `_model` is currently in.
            response = client.get("/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"socials": []}

            # The admin routes are refused like every other /admin/* route
            # when not in agent mode.
            _model.agent = False
            response = client.get("/admin/social/list")
            assert response.status_code == 403, (response.status_code, response.text)

            _model.agent = True
            response = client.post(
                "/admin/social/add",
                json={
                    "platform": "instagram",
                    "username": "handle",
                    "url": "https://instagram.com/handle",
                    "followerCount": 100,
                },
            )
            assert response.status_code == 200, (response.status_code, response.text)
            created = response.json()
            assert created["id"].startswith("instagram-")
            assert created["isAlt"] is False

            # The public route now reflects the admin-added entry.
            response = client.get("/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert len(response.json()["socials"]) == 1

            response = client.post(
                "/admin/social/update",
                json={"id": created["id"], "followerCount": 200},
            )
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["followerCount"] == 200

            # An unknown id is a 404, not a silent no-op.
            response = client.post(
                "/admin/social/update", json={"id": "no-such-id", "bio": "x"}
            )
            assert response.status_code == 404, (response.status_code, response.text)

            response = client.post(
                "/admin/social/delete", json={"id": created["id"]}
            )
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"deleted": created["id"]}

            response = client.get("/admin/social/list")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json() == {"socials": []}

            response = client.post(
                "/admin/social/delete", json={"id": "no-such-id"}
            )
            assert response.status_code == 404, (response.status_code, response.text)
        finally:
            social_module.PROFILE_JSON_PATH = original_profile_json
    _model.agent = False
```

- [ ] **Step 6: Run the self-check**

Run: `python -m service.main`
Expected: no assertion errors; the existing final print statement runs (`service self-check: ok ...`).

- [ ] **Step 7: Commit**

```bash
git add service/main.py
git commit -m "feat(service): add social-links CRUD routes, admin + public"
```

---

## Task 3: Admin API client + URL parser — `cookbook-web/lib/admin/`

**Files:**
- Create: `cookbook-web/lib/admin/socialApi.ts`
- Create: `cookbook-web/lib/admin/socialUrl.ts`
- Create: `cookbook-web/lib/admin/socialUrl.test.ts`

**Interfaces:**
- Produces: `interface Social` (`id`, `platform`, `username`, `url`, `bio: string | null`, `followerCount: number | null`, `pfpUrl: string | null`, `isAlt: boolean`), `getSocials(): Promise<{ socials: Social[] }>`, `addSocial(params: AddSocialParams): Promise<Social>`, `updateSocial(params: UpdateSocialParams): Promise<Social>`, `deleteSocial(id: string): Promise<{ deleted: string }>`, `class SocialApiError` — all consumed by Task 4's `SocialCard`/`SocialDialog`.
- Produces: `interface ParsedSocialUrl` (`platform`, `username`), `parseSocialUrl(url: string): ParsedSocialUrl | null` — consumed by Task 4's `SocialDialog`.

- [ ] **Step 1: Write `socialApi.ts`**

Create `cookbook-web/lib/admin/socialApi.ts`:

```typescript
export interface Social {
  id: string
  platform: string
  username: string
  url: string
  bio: string | null
  followerCount: number | null
  pfpUrl: string | null
  isAlt: boolean
}

const SERVICE_URL = process.env.NEXT_PUBLIC_SERVICE_URL ?? "http://127.0.0.1:8000"

export class SocialApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${SERVICE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // body wasn't JSON — keep statusText
    }
    throw new SocialApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export function getSocials(): Promise<{ socials: Social[] }> {
  return request("/admin/social/list")
}

export interface AddSocialParams {
  platform: string
  username: string
  url: string
  bio?: string
  followerCount?: number
  pfpUrl?: string
  isAlt?: boolean
}

export function addSocial(params: AddSocialParams): Promise<Social> {
  return request("/admin/social/add", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export interface UpdateSocialParams extends Partial<AddSocialParams> {
  id: string
}

export function updateSocial(params: UpdateSocialParams): Promise<Social> {
  return request("/admin/social/update", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export function deleteSocial(id: string): Promise<{ deleted: string }> {
  return request("/admin/social/delete", {
    method: "POST",
    body: JSON.stringify({ id }),
  })
}
```

- [ ] **Step 2: Write `socialUrl.ts`**

Create `cookbook-web/lib/admin/socialUrl.ts`:

```typescript
export interface ParsedSocialUrl {
  platform: string
  username: string
}

const DOMAIN_PLATFORMS: Record<string, string> = {
  "instagram.com": "instagram",
  "tiktok.com": "tiktok",
  "x.com": "x",
  "twitter.com": "x",
  "youtube.com": "youtube",
  "linkedin.com": "linkedin",
}

// Pure string parsing, zero network requests — see the plan's Global
// Constraints on why this feature does no fetching.
export function parseSocialUrl(url: string): ParsedSocialUrl | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return null
  }
  const host = parsed.hostname.replace(/^www\./, "")
  const platform = DOMAIN_PLATFORMS[host]
  if (!platform) return null
  const username = parsed.pathname.split("/").filter(Boolean)[0] ?? ""
  if (!username) return null
  return { platform, username }
}
```

- [ ] **Step 3: Write the failing test**

Create `cookbook-web/lib/admin/socialUrl.test.ts`:

```typescript
import { describe, expect, it } from "vitest"
import { parseSocialUrl } from "./socialUrl"

describe("parseSocialUrl", () => {
  it("parses an instagram profile url", () => {
    expect(parseSocialUrl("https://instagram.com/handle")).toEqual({
      platform: "instagram",
      username: "handle",
    })
  })

  it("parses a tiktok profile url with a leading @ in the path", () => {
    expect(parseSocialUrl("https://www.tiktok.com/@handle")).toEqual({
      platform: "tiktok",
      username: "@handle",
    })
  })

  it("treats twitter.com and x.com as the same platform", () => {
    expect(parseSocialUrl("https://twitter.com/handle")?.platform).toBe("x")
    expect(parseSocialUrl("https://x.com/handle")?.platform).toBe("x")
  })

  it("returns null for an unrecognized domain", () => {
    expect(parseSocialUrl("https://example.com/handle")).toBeNull()
  })

  it("returns null for a URL with no path", () => {
    expect(parseSocialUrl("https://instagram.com")).toBeNull()
  })

  it("returns null for a non-URL string", () => {
    expect(parseSocialUrl("not a url")).toBeNull()
  })
})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd cookbook-web && npm test`
Expected: `lib/admin/socialUrl.test.ts` passes (6/6), alongside the two pre-existing suites (still 14/14) — 20/20 total.

- [ ] **Step 5: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add cookbook-web/lib/admin/socialApi.ts cookbook-web/lib/admin/socialUrl.ts cookbook-web/lib/admin/socialUrl.test.ts
git commit -m "feat(admin): add social API client and URL-parsing helper"
```

---

## Task 4: Admin UI — `SocialCard`, `SocialDialog`, wire into `Sidebar`

**Files:**
- Create: `cookbook-web/components/admin/SocialCard.tsx`
- Create: `cookbook-web/components/admin/SocialDialog.tsx`
- Modify: `cookbook-web/components/admin/Sidebar.tsx`

**Interfaces:**
- Consumes: `Social`, `getSocials`, `addSocial`, `updateSocial`, `deleteSocial` from `@/lib/admin/socialApi` (Task 3); `parseSocialUrl` from `@/lib/admin/socialUrl` (Task 3).
- Produces: `SocialCard` (no props) — rendered inside `Sidebar`.

- [ ] **Step 1: Write `SocialDialog.tsx`**

Create `cookbook-web/components/admin/SocialDialog.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import {
  addSocial,
  deleteSocial,
  getSocials,
  updateSocial,
  type Social,
} from "@/lib/admin/socialApi";
import { parseSocialUrl } from "@/lib/admin/socialUrl";

const COMMON_PLATFORMS = ["instagram", "tiktok", "x", "youtube", "linkedin"];

type FormState = {
  id?: string;
  platform: string;
  platformOther: string;
  username: string;
  url: string;
  bio: string;
  followerCount: string;
  pfpUrl: string;
  isAlt: boolean;
};

const EMPTY_FORM: FormState = {
  platform: "instagram",
  platformOther: "",
  username: "",
  url: "",
  bio: "",
  followerCount: "",
  pfpUrl: "",
  isAlt: false,
};

export function SocialDialog({ onClose }: { onClose: () => void }) {
  const [socials, setSocials] = useState<Social[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    setLoading(true);
    try {
      const res = await getSocials();
      setSocials(res.socials);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function startAdd() {
    setForm({ ...EMPTY_FORM });
  }

  function startEdit(social: Social) {
    const known = COMMON_PLATFORMS.includes(social.platform);
    setForm({
      id: social.id,
      platform: known ? social.platform : "other",
      platformOther: known ? "" : social.platform,
      username: social.username,
      url: social.url,
      bio: social.bio ?? "",
      followerCount:
        social.followerCount != null ? String(social.followerCount) : "",
      pfpUrl: social.pfpUrl ?? "",
      isAlt: social.isAlt,
    });
  }

  function handleUrlChange(url: string) {
    if (!form) return;
    const parsed = parseSocialUrl(url);
    if (!parsed) {
      setForm({ ...form, url });
      return;
    }
    const known = COMMON_PLATFORMS.includes(parsed.platform);
    setForm({
      ...form,
      url,
      platform: known ? parsed.platform : "other",
      platformOther: known ? "" : parsed.platform,
      username: form.username || parsed.username,
    });
  }

  async function handleSave() {
    if (!form) return;
    const platform =
      form.platform === "other" ? form.platformOther.trim() : form.platform;
    if (!platform || !form.username || !form.url) {
      setError("platform, username, and url are required");
      return;
    }
    const params = {
      platform,
      username: form.username,
      url: form.url,
      bio: form.bio || undefined,
      followerCount: form.followerCount ? Number(form.followerCount) : undefined,
      pfpUrl: form.pfpUrl || undefined,
      isAlt: form.isAlt,
    };
    try {
      if (form.id) {
        await updateSocial({ id: form.id, ...params });
      } else {
        await addSocial(params);
      }
      setForm(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this social?")) return;
    try {
      await deleteSocial(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function platformHasOtherEntry(platform: string) {
    return socials.some((s) => s.platform === platform && s.id !== form?.id);
  }

  const activePlatform =
    form?.platform === "other" ? form.platformOther : form?.platform ?? "";

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          background: "white",
          color: "#111",
          padding: 24,
          maxWidth: 600,
          width: "90%",
          maxHeight: "80vh",
          overflow: "auto",
        }}
      >
        <h2>Profile</h2>
        {error && <p style={{ color: "red" }}>{error}</p>}

        {loading ? (
          <p>Loading...</p>
        ) : socials.length === 0 && !form ? (
          <p>No profile linked to this account yet</p>
        ) : (
          socials.map((social) => (
            <div
              key={social.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 0",
                borderBottom: "1px solid #eee",
              }}
            >
              <span>{social.platform}</span>
              <span>{social.username}</span>
              {social.followerCount != null && (
                <span>{social.followerCount} followers</span>
              )}
              {social.isAlt && (
                <span style={{ fontSize: 11, color: "#888" }}>-Alt</span>
              )}
              <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                <button onClick={() => startEdit(social)}>Update</button>
                <button onClick={() => handleDelete(social.id)}>Delete</button>
              </div>
            </div>
          ))
        )}

        {form ? (
          <div style={{ marginTop: 16 }}>
            <h3>{form.id ? "Update social" : "Add social"}</h3>
            <label style={{ display: "block" }}>
              Link
              <input
                value={form.url}
                onChange={(e) => handleUrlChange(e.target.value)}
                style={{ width: "100%" }}
              />
            </label>
            <label style={{ display: "block" }}>
              Platform
              <select
                value={form.platform}
                onChange={(e) => setForm({ ...form, platform: e.target.value })}
              >
                {COMMON_PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
                <option value="other">Other</option>
              </select>
            </label>
            {form.platform === "other" && (
              <label style={{ display: "block" }}>
                Platform name
                <input
                  value={form.platformOther}
                  onChange={(e) =>
                    setForm({ ...form, platformOther: e.target.value })
                  }
                />
              </label>
            )}
            <label style={{ display: "block" }}>
              Username
              <input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </label>
            <label style={{ display: "block" }}>
              Bio
              <textarea
                value={form.bio}
                onChange={(e) => setForm({ ...form, bio: e.target.value })}
              />
            </label>
            <label style={{ display: "block" }}>
              Follower count
              <input
                type="number"
                value={form.followerCount}
                onChange={(e) =>
                  setForm({ ...form, followerCount: e.target.value })
                }
              />
            </label>
            <label style={{ display: "block" }}>
              Profile picture URL
              <input
                value={form.pfpUrl}
                onChange={(e) => setForm({ ...form, pfpUrl: e.target.value })}
              />
            </label>
            {activePlatform && platformHasOtherEntry(activePlatform) && (
              <label style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={form.isAlt}
                  onChange={(e) =>
                    setForm({ ...form, isAlt: e.target.checked })
                  }
                />{" "}
                -Alt (a second account for this platform)
              </label>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={handleSave}>Save</button>
              <button onClick={() => setForm(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <button onClick={startAdd} style={{ marginTop: 16 }}>
            Add social
          </button>
        )}

        <div style={{ marginTop: 16 }}>
          <button onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Write `SocialCard.tsx`**

Create `cookbook-web/components/admin/SocialCard.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { getSocials } from "@/lib/admin/socialApi";
import { SocialDialog } from "./SocialDialog";

export function SocialCard() {
  const [count, setCount] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(() => {
    getSocials()
      .then((res) => setCount(res.socials.length))
      .catch(() => setCount(null));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <h3>Profile</h3>
      <p>
        {count === null
          ? "..."
          : count === 0
            ? "No profile linked to this account yet"
            : `${count} social${count === 1 ? "" : "s"} linked`}
      </p>
      <button onClick={() => setOpen(true)}>View/Update Profile</button>
      {open && (
        <SocialDialog
          onClose={() => {
            setOpen(false);
            refresh();
          }}
        />
      )}
    </>
  );
}
```

- [ ] **Step 3: Wire `SocialCard` into `Sidebar.tsx`**

Edit `cookbook-web/components/admin/Sidebar.tsx` — add the import:

```diff
 import { getHealth, getModelStatus, getSnapshots, loadModel, postSnapshotRestore, unloadModel } from "@/lib/admin/api";
 import type { GenerationParams } from "@/hooks/useAgentLoop";
 import type { HealthStatus, ModelStatus } from "@/lib/admin/types";
+import { SocialCard } from "./SocialCard";
```

And render it — the file's closing lines today are:

```tsx
      {status?.agent && (
        <>
          <h3>Snapshots</h3>
          {snapshots.length === 0 ? (
            <p>No snapshots yet — one is taken before every write.</p>
          ) : (
            <>
              <select value={selected} onChange={(e) => setSelected(e.target.value)}>
                {snapshots.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button onClick={handleRestore}>Restore</button>
            </>
          )}
        </>
      )}
    </aside>
  );
}
```

Change the last four lines so `<SocialCard />` renders unconditionally (not gated behind `status?.agent`, matching the spec's "a card in sidebar" placement — Social management isn't tied to whether a model happens to be loaded):

```diff
         </>
       )}
+
+      <SocialCard />
     </aside>
   );
 }
```

- [ ] **Step 4: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Manual verification**

Run: `cd cookbook-web && npm run dev`, with `service/main.py` running and a model loaded (`POST /model/load`) and in agent mode. Open `/admin`, confirm the "Profile" card appears in the sidebar showing "No profile linked to this account yet", click **View/Update Profile**, add a social, confirm it appears in the list with Update/Delete buttons, confirm the sidebar card's count updates after closing the dialog.

- [ ] **Step 6: Commit**

```bash
git add cookbook-web/components/admin/SocialCard.tsx cookbook-web/components/admin/SocialDialog.tsx cookbook-web/components/admin/Sidebar.tsx
git commit -m "feat(admin): add SocialCard + SocialDialog, wire into Sidebar"
```

---

## Task 5: Fan wiring — `BottomBar`

**Files:**
- Create: `cookbook-web/lib/socialApi.ts`
- Modify: `cookbook-web/components/fan/BottomBar.tsx`

**Interfaces:**
- Consumes: nothing from earlier frontend tasks (this is the fan surface — deliberately a separate, simpler client than `lib/admin/socialApi.ts`, per the spec's "public route, own client" decision) — but does consume `GET /social/list` from Task 2.
- Produces: `interface PublicSocial`, `getPublicSocials(): Promise<PublicSocial[]>` — consumed by `BottomBar.tsx` in this same task.

- [ ] **Step 1: Write `lib/socialApi.ts`**

Create `cookbook-web/lib/socialApi.ts`:

```typescript
export interface PublicSocial {
  id: string
  platform: string
  username: string
  url: string
  bio: string | null
  followerCount: number | null
  pfpUrl: string | null
  isAlt: boolean
}

const SERVICE_URL = process.env.NEXT_PUBLIC_SERVICE_URL ?? "http://127.0.0.1:8000"

// No auth, no agent gate on the backend side — this is public contact info
// a fan is meant to see, same trust level as a link already on the profile.
export async function getPublicSocials(): Promise<PublicSocial[]> {
  const res = await fetch(`${SERVICE_URL}/social/list`)
  if (!res.ok) return []
  const data = (await res.json()) as { socials: PublicSocial[] }
  return data.socials
}
```

- [ ] **Step 2: Wire `BottomBar.tsx`**

Read the current file first (`cookbook-web/components/fan/BottomBar.tsx`) — it has no `"use client"` directive today, since it was a static server component; it needs one now for `useState`/`useEffect`. Replace the whole file:

```tsx
"use client"

import { useEffect, useState } from "react"
import { Instagram, Link2, Plus } from "lucide-react"
import { getPublicSocials, type PublicSocial } from "@/lib/socialApi"

function platformIcon(platform: string) {
  if (platform === "instagram") return Instagram
  return Link2
}

function BottomBar() {
  const [socials, setSocials] = useState<PublicSocial[]>([])

  useEffect(() => {
    getPublicSocials().then(setSocials)
  }, [])

  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex h-16 items-center justify-center gap-6 border-t border-border bg-background/95 backdrop-blur">
      {socials.map((social) => {
        const Icon = platformIcon(social.platform)
        return (
          <a
            key={social.id}
            href={social.url}
            target="_blank"
            rel="noreferrer"
            className="flex size-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Icon className="size-5" />
          </a>
        )
      })}
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

(The two disabled placeholder `Link2` spans are gone — replaced by the real `socials.map(...)`. The `+`/"More" button is unchanged, still a placeholder for whatever it was already going to become.)

- [ ] **Step 3: Typecheck**

Run: `cd cookbook-web && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Manual verification**

With a social already added via the admin dialog (Task 4's verification step) and `service/main.py` still running, open `/fan`. Confirm the added social's icon appears in `BottomBar`, links to the right URL, opens in a new tab. Delete the social from the admin dialog, refresh `/fan`, confirm the icon disappears and only the `+` button remains.

- [ ] **Step 5: Commit**

```bash
git add cookbook-web/lib/socialApi.ts cookbook-web/components/fan/BottomBar.tsx
git commit -m "feat(fan): wire BottomBar to real linked socials"
```

---

## Task 6: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend self-check**

Run: `python -m service.main`
Expected: `service self-check: ok ...` — proves Tasks 1-2's routes and the pre-existing suite are all still green together.

- [ ] **Step 2: Full frontend suite**

Run: `cd cookbook-web && npm run typecheck && npm test`
Expected: typecheck clean; vitest 20/20 (14 pre-existing + 6 from `socialUrl.test.ts`).

- [ ] **Step 3: Full manual click-through**

With `service/main.py` running, model loaded, agent mode on, and `cookbook-web`'s dev server running:

1. `/admin` — add two Instagram entries (second one checking `-Alt`), one TikTok entry. Confirm all three list correctly, the `-Alt` tag shows on the second Instagram row only, and pasting `https://tiktok.com/@someone` into the Link field auto-fills platform=tiktok and username=`@someone` before you finish the rest of the form.
2. Update one entry's bio, confirm it persists after closing and reopening the dialog.
3. Delete the `-Alt` Instagram entry, confirm only two remain.
4. `/fan` — confirm `BottomBar` shows two icons (Instagram + TikTok's fallback `Link2` icon, since TikTok has no dedicated lucide icon), both linking correctly.
5. Restart `service/main.py` (kill and re-run `python -m service.main`, or however it's normally started) and confirm `/fan`'s icons survive — proving `data/profile.json` actually persisted to disk, not just in-memory.

- [ ] **Step 4: Report**

No commit for this task — it's verification only. If every check in Steps 1-3 passes, the feature is complete.
