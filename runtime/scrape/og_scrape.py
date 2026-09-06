"""Best-effort profile metadata via public OpenGraph meta tags — no API key,
no login. Used for Instagram and X, neither of which has a dedicated scraper
like TikTok's or YouTube's.

X's profile page still serves `og:image`/`og:description` to a plain HTTP
GET, so a plain `httpx` request works there. Instagram strips its og tags for
an unauthenticated *non-browser* request specifically — a real (even
logged-out) browser still gets them — so that branch goes through Scrapling's
`StealthyFetcher` (a real, fingerprint-evading browser engine) instead of
`httpx`.

Neither platform's og tags carry a dedicated follower-count field. X is a
partial exception: when it serves the generic logged-out description instead
of the account's real bio, that description itself starts with "N followers
· M following. Joined ..." — `_extract_follower_count` pulls the number out
of that specific shape. Instagram's og:description instead starts with
"N Followers, M Following, ... Posts" — a different shape, handled by
`_extract_instagram_counts`. Any other og:description (a real bio) simply
doesn't match either, so follower_count stays None there.

The scrape can fail for any reason (network, markup changes, blocking) and
must never block adding the link: every caller treats None as "no scrape
data available", the same as any other platform that never had a scraper.
"""

from __future__ import annotations

import html
import re

import httpx

from .handle_resolve import resolve_handle as _resolve_handle

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_X_FOLLOWER_RE = re.compile(r"^([\d,]+)\s+[Ff]ollowers?\b")
_INSTAGRAM_FOLLOWER_RE = re.compile(r"^([\d,.]+[KMB]?)\s+Followers?\b")
# The first "video_versions" entry in a reel page's inline JSON — a signed,
# directly-fetchable progressive .mp4, confirmed live (curl, no referer
# needed). `[^}]*?` stops at the entry's own closing brace so this can't
# run on and grab a "url" from a later, unrelated JSON object.
_VIDEO_VERSIONS_RE = re.compile(r'"video_versions"\s*:\s*\[\{[^}]*?"url"\s*:\s*"([^"]+)"')


def _meta(text: str, prop: str) -> str | None:
    match = re.search(rf'<meta property="{prop}" content="([^"]*)"', text)
    return html.unescape(match.group(1)) if match else None


def _extract_follower_count(bio: str | None) -> int | None:
    if not bio:
        return None
    match = _X_FOLLOWER_RE.match(bio)
    return int(match.group(1).replace(",", "")) if match else None


def _extract_instagram_follower_count(bio: str | None) -> int | None:
    """Instagram's og:description shape: "25M Followers, 20 Following,
    2,339 Posts - See Instagram photos and videos from ...". The count can
    carry a K/M/B suffix instead of being spelled out in full."""
    if not bio:
        return None
    match = _INSTAGRAM_FOLLOWER_RE.match(bio)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(raw[-1], None)
    if multiplier:
        return int(float(raw[:-1]) * multiplier)
    return int(float(raw))


def _scrape_instagram(url: str) -> dict | None:
    try:
        from scrapling.fetchers import StealthyFetcher

        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status != 200:
            return None
        # Scrapling returns its own TextHandler wrapper, not a plain str —
        # coerce so downstream regex/JSON handling gets an actual string.
        pfp_url = next(iter(page.css('meta[property="og:image"]::attr(content)')), None)
        bio = next(iter(page.css('meta[property="og:description"]::attr(content)')), None)
        pfp_url = str(pfp_url) if pfp_url else None
        bio = str(bio) if bio else None
        if not pfp_url and not bio:
            return None
        return {"pfp_url": pfp_url, "follower_count": _extract_instagram_follower_count(bio), "bio": bio}
    except Exception:
        return None


def resolve_instagram_handle(display_text: str) -> str | None:
    """Instagram bios can @-mention a display nickname that isn't the
    account's real @handle, same as TikTok's — the direct profile-URL guess
    404s. See `handle_resolve.resolve_handle` for how the real handle gets
    found."""
    return _resolve_handle(display_text, "instagram")


_POST_LINK_RE = re.compile(r"/(p|reel)/([A-Za-z0-9_-]+)/")


def list_instagram_posts(url: str, limit: int = 6) -> list[dict]:
    """Recent posts/reels, newest-first as Instagram's own profile grid
    orders them. Only reachable through a real browser (see _scrape_instagram
    above) — the post grid hydrates client-side and never appears in a plain
    httpx GET's HTML, unlike the og-tag profile metadata."""
    try:
        from scrapling.fetchers import StealthyFetcher

        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status != 200:
            return []
        anchors = page.css('a[href*="/p/"], a[href*="/reel/"]')
    except Exception:
        return []
    results: list[dict] = []
    seen: set[str] = set()
    for anchor in anchors:
        href = str(anchor.attrib.get("href") or "")
        match = _POST_LINK_RE.search(href)
        if not match or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        img = next(iter(anchor.css("img")), None)
        alt = img.attrib.get("alt") if img else None
        src = img.attrib.get("src") if img else None
        results.append({
            "kind": "video" if match.group(1) == "reel" else "image",
            "embedId": match.group(2),
            "url": f"https://www.instagram.com{href}",
            "title": str(alt) if alt else None,
            "thumbnailUrl": str(src) if src else None,
        })
        if len(results) >= limit:
            break
    return results


def scrape_instagram_post_media(url: str) -> dict | None:
    """The post's own actual media — the CDN file, not the page. This is
    what lets the fan player render a plain <video>/<img> instead of going
    through Instagram's embed.js widget, which has needed an app-level
    oEmbed access token since their Graph API changes and can silently
    render nothing (a blank white box) without one.

    A reel's og:video meta tag is missing more often than not (checked
    live), but the page's own inline JSON still carries a signed,
    directly-fetchable progressive .mp4 under "video_versions" — the exact
    file the page's own <video> tag would play, just not exposed as a tag
    a scraper can read declaratively. Tried first; og:video/og:image are the
    fallback for whatever that regex doesn't match if Instagram reshapes the
    page.

    Returns {"url": ..., "kind": "video" | "image"} — `kind` here is which
    source actually resolved, not a guess from the post's /reel/ vs /p/ URL
    shape: a caller that assumed "reel" always means "got a video" would
    hand a JPEG to a <video> tag on the (still possible) fallback path.

    Called once per post during the admin-triggered post refresh (see
    posts.py) — never live on a fan's page load, same contract as every
    other scrape in this module.
    """
    try:
        from scrapling.fetchers import StealthyFetcher

        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status != 200:
            return None
        html = str(page.html_content)
        progressive = _VIDEO_VERSIONS_RE.search(html)
        if progressive:
            return {"url": progressive.group(1).replace("\\/", "/"), "kind": "video"}
        video = next(iter(page.css('meta[property="og:video"]::attr(content)')), None)
        if video:
            return {"url": str(video), "kind": "video"}
        image = next(iter(page.css('meta[property="og:image"]::attr(content)')), None)
        return {"url": str(image), "kind": "image"} if image else None
    except Exception:
        return None


def scrape_profile(url: str) -> dict | None:
    if "instagram.com" in url:
        return _scrape_instagram(url)
    try:
        response = httpx.get(
            url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=10
        )
        response.raise_for_status()
        pfp_url = _meta(response.text, "og:image")
        bio = _meta(response.text, "og:description")
        if not pfp_url and not bio:
            return None
        return {"pfp_url": pfp_url, "follower_count": _extract_follower_count(bio), "bio": bio}
    except Exception:
        return None


