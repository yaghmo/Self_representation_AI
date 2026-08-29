"""TikTok Login Kit OAuth — one-time creator consent, needed because
`video.list` requires a *user* access token; app credentials alone
(`TIKTOK_CLIENT_KEY`/`SECRET`) aren't enough, unlike Twitch's app-token
flow in `twitch_scrape.py`.

Redirect URI must be HTTPS and match exactly what's registered on the
TikTok app's Login Kit settings (a local dev tunnel, e.g. cloudflared,
stands in for a real domain until this is deployed).

Missing credentials, no connected account, or any request failure returns
None/[] — never blocks the rest of a post refresh, same contract as every
other scraper in this repo.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx

from .bible import PROFILE_PATH

_AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
_VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"
_VIDEO_FIELDS = "id,create_time,cover_image_url,share_url,title"
# user.info.profile (not just .basic) is what actually gets the `username`
# field back — display_name alone isn't enough to check against the linked
# social's handle, same nickname-vs-handle gap handle_resolve.py exists for.
_SCOPE = "user.info.basic,user.info.profile,video.list"

TOKEN_PATH = PROFILE_PATH.parent / "tiktok_token.json"

# Short-lived, in-memory only — this is a single-admin local app, so one
# pending authorize request at a time is all the CSRF `state` check needs;
# no reason to persist it or survive a process restart.
_pending_state: str | None = None


class InvalidState(Exception):
    """The callback's `state` didn't match the pending authorize request —
    a stale link, a replayed callback, or a forged request."""


def authorize_url(redirect_uri: str) -> str:
    global _pending_state
    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    if not client_key:
        raise ValueError("TIKTOK_CLIENT_KEY not set")
    _pending_state = uuid.uuid4().hex
    return (
        f"{_AUTHORIZE_URL}?client_key={client_key}&response_type=code"
        f"&scope={_SCOPE}&redirect_uri={redirect_uri}&state={_pending_state}"
    )


def _load_token() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def _save_token(data: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def handle_callback(code: str, state: str, redirect_uri: str) -> None:
    global _pending_state
    if not _pending_state or state != _pending_state:
        raise InvalidState(state)
    _pending_state = None
    response = httpx.post(
        _TOKEN_URL,
        data={
            "client_key": os.environ.get("TIKTOK_CLIENT_KEY"),
            "client_secret": os.environ.get("TIKTOK_CLIENT_SECRET"),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if "access_token" not in data:
        raise ValueError(f"token exchange failed: {data}")
    data["obtained_at"] = int(time.time())
    data["username"] = _fetch_username(data["access_token"])
    _save_token(data)


def _fetch_username(access_token: str) -> str | None:
    """Best-effort — a failure here shouldn't fail the whole connect flow,
    it just leaves `username` unset until the next successful call (see
    `_ensure_username`, which retries on every status/match check)."""
    try:
        response = httpx.get(
            _USER_INFO_URL,
            params={"fields": "username"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["data"]["user"]["username"]
    except Exception:
        return None


def _ensure_username(token: dict) -> dict:
    """Backfills `username` on a token saved before this field existed, or
    left unset by a `_fetch_username` failure at connect time."""
    if token.get("username"):
        return token
    access_token = _valid_access_token()
    if not access_token:
        return token
    username = _fetch_username(access_token)
    if username:
        token["username"] = username
        _save_token(token)
    return token


def connection_status() -> dict:
    token = _load_token()
    if not token:
        return {"connected": False}
    token = _ensure_username(token)
    return {
        "connected": True,
        "openId": token.get("open_id"),
        "username": token.get("username"),
        "scope": token.get("scope"),
    }


def is_connected_to(username: str) -> bool:
    """Whether the OAuth-connected account is the same one behind a given
    @handle — the connected account can silently be a different one than
    the profile actually listed on the site (wrong login, a test account,
    an old connection nobody re-checked), so callers that would otherwise
    trust "connected == True" alone must check this instead."""
    token = _load_token()
    if not token:
        return False
    token = _ensure_username(token)
    connected_username = token.get("username")
    if not connected_username:
        return False
    return connected_username.lstrip("@").lower() == username.lstrip("@").lower()


def disconnect() -> None:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


def _refresh(token: dict) -> dict | None:
    try:
        response = httpx.post(
            _TOKEN_URL,
            data={
                "client_key": os.environ.get("TIKTOK_CLIENT_KEY"),
                "client_secret": os.environ.get("TIKTOK_CLIENT_SECRET"),
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if "access_token" not in data:
            return None
        data["obtained_at"] = int(time.time())
        _save_token(data)
        return data
    except Exception:
        return None


def _valid_access_token() -> str | None:
    token = _load_token()
    if not token:
        return None
    expires_at = token["obtained_at"] + token.get("expires_in", 0)
    if time.time() > expires_at - 60:
        token = _refresh(token)
        if not token:
            return None
    return token.get("access_token")


def list_videos(limit: int = 6) -> list[dict]:
    access_token = _valid_access_token()
    if not access_token:
        return []
    try:
        response = httpx.post(
            _VIDEO_LIST_URL,
            params={"fields": _VIDEO_FIELDS},
            json={"max_count": limit},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
        videos = response.json().get("data", {}).get("videos") or []
        results = []
        for video in videos[:limit]:
            create_time = video.get("create_time")
            results.append({
                "kind": "video",
                "embedId": video["id"],
                "url": video.get("share_url"),
                "title": video.get("title"),
                "thumbnailUrl": video.get("cover_image_url"),
                "publishedAt": (
                    datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat()
                    if create_time
                    else None
                ),
            })
        return results
    except Exception:
        return []


