"""Twitch channel metadata via the Helix API — needs a free app registration
at dev.twitch.tv, its Client ID/Secret set as the TWITCH_CLIENT_ID/
TWITCH_CLIENT_SECRET env vars. Uses an app access token (client-credentials
grant — no per-user OAuth, no browser login): `Get Users` for pfp/bio,
`Get Channel Followers` for the count. That second endpoint's per-follower
`data` list needs the broadcaster's own OAuth token (moderator:read:followers)
— we never request that list, only its `total` field, which Twitch does
serve to a plain app token (verified directly against the live API, not
assumed from the docs).

`scrape_panel_links` and `scrape_social_medias` are separate and need none
of that: a channel's other socials can live in either (or both) of two
distinct, independent features — the freeform "Panels" grid further down
the About tab, and a short curated "social links" list Twitch renders right
beside the bio text (icon + platform name, added via Twitch's own "add
social link" flow, distinct from a Panel). Neither is in Helix — not the
API, not the raw page HTML, both are filled in client-side. But twitch.tv's
own frontend fetches both from an internal GraphQL API at gql.twitch.tv
using a public web client-id (the one twitch.tv itself sends, not a secret,
needs no registration) — verified directly against the live API by hand.
It's undocumented, so treat it the same as any other best-effort scraper:
it can break if Twitch changes their frontend, and any failure just
returns [].

Missing credentials, or any other failure (network, bad credentials, no
such user), returns None — never blocks adding the link, same contract as
every other scraper here.
"""

from __future__ import annotations

import os
import time

import httpx

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_USERS_URL = "https://api.twitch.tv/helix/users"
_FOLLOWERS_URL = "https://api.twitch.tv/helix/channels/followers"
_VIDEOS_URL = "https://api.twitch.tv/helix/videos"
_GQL_URL = "https://gql.twitch.tv/gql"
_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_token: str | None = None
_token_expires_at: float = 0.0


def _get_app_token() -> str | None:
    global _token, _token_expires_at
    if _token and time.time() < _token_expires_at:
        return _token
    client_id = os.environ.get("TWITCH_CLIENT_ID")
    client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    response = httpx.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    _token = data["access_token"]
    _token_expires_at = time.time() + data["expires_in"] - 60
    return _token


def scrape_channel(username: str) -> dict | None:
    try:
        token = _get_app_token()
        client_id = os.environ.get("TWITCH_CLIENT_ID")
        if not token or not client_id:
            return None
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        response = httpx.get(
            _USERS_URL, params={"login": username}, headers=headers, timeout=10
        )
        response.raise_for_status()
        users = response.json().get("data") or []
        if not users:
            return None
        user = users[0]

        follower_count = None
        try:
            followers_response = httpx.get(
                _FOLLOWERS_URL,
                params={"broadcaster_id": user["id"]},
                headers=headers,
                timeout=10,
            )
            followers_response.raise_for_status()
            follower_count = followers_response.json().get("total")
        except Exception:
            pass  # pfp/bio still worth returning even if this one call fails

        return {
            "pfp_url": user.get("profile_image_url"),
            "follower_count": follower_count,
            "bio": user.get("description"),
        }
    except Exception:
        return None


def list_vods(username: str, limit: int = 6) -> list[dict]:
    """Recent archived broadcasts (VODs), newest first — real Helix data
    (`type=archive`), not a scrape, so title/thumbnail/published_at are
    exact rather than best-effort-parsed."""
    try:
        token = _get_app_token()
        client_id = os.environ.get("TWITCH_CLIENT_ID")
        if not token or not client_id:
            return []
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        response = httpx.get(
            _USERS_URL, params={"login": username}, headers=headers, timeout=10
        )
        response.raise_for_status()
        users = response.json().get("data") or []
        if not users:
            return []

        response = httpx.get(
            _VIDEOS_URL,
            params={"user_id": users[0]["id"], "type": "archive", "first": limit},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        videos = response.json().get("data") or []
        results = []
        for video in videos[:limit]:
            thumbnail = video.get("thumbnail_url") or ""
            thumbnail = thumbnail.replace("%{width}", "320").replace("%{height}", "180")
            results.append({
                "kind": "vod",
                "embedId": video["id"],
                "url": video.get("url") or f"https://www.twitch.tv/videos/{video['id']}",
                "title": video.get("title"),
                "thumbnailUrl": thumbnail or None,
                "publishedAt": video.get("published_at"),
            })
        return results
    except Exception:
        return []


def scrape_panel_links(username: str) -> list[str]:
    """Raw linkURLs from the channel's About-tab Panels, in whatever order
    Twitch returns them. Callers match each against known platform domains
    themselves — this just fetches the URLs."""
    try:
        response = httpx.post(
            _GQL_URL,
            headers={"Client-Id": _GQL_CLIENT_ID, "Content-Type": "application/json"},
            json=[
                {
                    "operationName": "ChannelPanels",
                    "variables": {"channelLogin": username},
                    "query": (
                        "query ChannelPanels($channelLogin: String!) { "
                        "user(login: $channelLogin) { panels { "
                        "... on DefaultPanel { linkURL } } } }"
                    ),
                }
            ],
            timeout=10,
        )
        response.raise_for_status()
        data = (response.json()[0].get("data") or {}).get("user")
        if not data:
            return []
        return [p["linkURL"] for p in data.get("panels", []) if p.get("linkURL")]
    except Exception:
        return []


def scrape_social_medias(username: str) -> list[str]:
    """Raw urls from the channel's curated "social links" list (the icon
    row next to the bio text) — a different Twitch feature from Panels,
    fetched the same undocumented-GraphQL way."""
    try:
        response = httpx.post(
            _GQL_URL,
            headers={"Client-Id": _GQL_CLIENT_ID, "Content-Type": "application/json"},
            json=[
                {
                    "operationName": "ChannelSocials",
                    "variables": {"channelLogin": username},
                    "query": (
                        "query ChannelSocials($channelLogin: String!) { "
                        "user(login: $channelLogin) { channel { "
                        "socialMedias { url } } } }"
                    ),
                }
            ],
            timeout=10,
        )
        response.raise_for_status()
        user = (response.json()[0].get("data") or {}).get("user")
        if not user or not user.get("channel"):
            return []
        return [s["url"] for s in user["channel"].get("socialMedias", []) if s.get("url")]
    except Exception:
        return []


def _self_check() -> None:
    global _token, _token_expires_at

    # No credentials in this environment by default — the graceful-fallback
    # path is what's actually testable here without secrets.
    original_id = os.environ.pop("TWITCH_CLIENT_ID", None)
    original_secret = os.environ.pop("TWITCH_CLIENT_SECRET", None)
    _token, _token_expires_at = None, 0.0
    try:
        assert scrape_channel("twitch") is None, "no credentials -> None, not an exception"
    finally:
        if original_id is not None:
            os.environ["TWITCH_CLIENT_ID"] = original_id
        if original_secret is not None:
            os.environ["TWITCH_CLIENT_SECRET"] = original_secret
        _token, _token_expires_at = None, 0.0

    # With real credentials (TWITCH_CLIENT_ID/SECRET set in the environment),
    # this hits the real network — same tier as the other scrapers'
    # self-checks — and should resolve a real, stable channel.
    if os.environ.get("TWITCH_CLIENT_ID") and os.environ.get("TWITCH_CLIENT_SECRET"):
        result = scrape_channel("twitch")
        assert result is not None, "expected a successful scrape with real credentials"
        assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
        assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
        assert scrape_channel("this-should-not-exist-xyz123") is None

        # VOD availability varies by channel, so this only checks the shape,
        # not that any come back — a channel with no archived broadcasts is
        # a legitimate [], not a bug.
        vods = list_vods("r0ckyshield", limit=3)
        assert isinstance(vods, list) and len(vods) <= 3, vods
        for vod in vods:
            assert vod["embedId"], vod
            assert vod["url"].startswith("https://www.twitch.tv/"), vod
            assert vod["kind"] == "vod", vod
        assert list_vods("this-should-not-exist-xyz123-nope") == []
    else:
        assert list_vods("twitch") == [], "no credentials -> [], not an exception"

    # scrape_panel_links needs no credentials — the public web client-id
    # isn't ours to set. Real network, same tier as tiktok_scrape's check.
    links = scrape_panel_links("pokimane")
    assert links, "expected at least one panel link on a real, stable channel"
    assert all(url.startswith("http") for url in links), links
    assert scrape_panel_links("this-should-not-exist-xyz123-nope") == []

    social_links = scrape_social_medias("r0ckyshield")
    assert social_links, "expected at least one social link on a real, stable channel"
    assert all(url.startswith("http") for url in social_links), social_links
    assert scrape_social_medias("this-should-not-exist-xyz123-nope") == []

    print("twitch_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
