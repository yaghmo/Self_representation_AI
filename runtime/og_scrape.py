"""Best-effort profile metadata via public OpenGraph meta tags — no API key,
no login. Used for Instagram and X, neither of which has a dedicated scraper
like TikTok's or YouTube's: X's profile page still serves `og:image`/
`og:description` to a plain HTTP GET, so this works there. Instagram strips
its og tags for unauthenticated requests, so this returns None there in
practice — kept anyway since that's a platform decision, not a parsing gap,
and could change.

Neither platform's og tags carry a dedicated follower-count field. X is a
partial exception: when it serves the generic logged-out description instead
of the account's real bio, that description itself starts with "N followers
· M following. Joined ..." — `_extract_follower_count` pulls the number out
of that specific shape. Any other og:description (a real bio, Instagram's
stripped-tag None) simply doesn't match, so follower_count stays None there,
same as before.

The scrape can fail for any reason (network, markup changes, blocking) and
must never block adding the link: every caller treats None as "no scrape
data available", the same as any other platform that never had a scraper.
"""

from __future__ import annotations

import html
import re

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_X_FOLLOWER_RE = re.compile(r"^([\d,]+)\s+[Ff]ollowers?\b")


def _meta(text: str, prop: str) -> str | None:
    match = re.search(rf'<meta property="{prop}" content="([^"]*)"', text)
    return html.unescape(match.group(1)) if match else None


def _extract_follower_count(bio: str | None) -> int | None:
    if not bio:
        return None
    match = _X_FOLLOWER_RE.match(bio)
    return int(match.group(1).replace(",", "")) if match else None


def scrape_profile(url: str) -> dict | None:
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


