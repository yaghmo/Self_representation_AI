"""Best-effort X (Twitter) post listing via a real browser. X serves its
timeline HTML to a real, even logged-out browser, but blocks/JS-challenges a
plain non-browser request — same gate Instagram has (see og_scrape.py) — so
this goes through Scrapling's `StealthyFetcher` too, not httpx.

The scrape can fail for any reason (network, markup changes, blocking) and
must never block the rest of the feed: any failure returns an empty list,
same as any other platform's scraper.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_STATUS_RE = re.compile(r"^/([^/]+)/status/(\d+)$")


def list_posts(url: str, limit: int = 6) -> list[dict]:
    """Recent posts, newest-first as X's own profile timeline orders them.
    Skips reposts of someone else's tweet (its status link points at the
    original author, not this profile) but keeps the creator's own replies
    and quote-tweets — same "is this the profile owner's own status link"
    check either way."""
    username = urlparse(url).path.strip("/").split("/")[0]
    if not username:
        return []
    try:
        from scrapling.fetchers import StealthyFetcher

        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status != 200:
            return []
        articles = page.css("article")
    except Exception:
        return []
    results: list[dict] = []
    seen: set[str] = set()
    for article in articles:
        own_match = next(
            (
                m
                for href in article.css('a[href*="/status/"]::attr(href)')
                if (m := _STATUS_RE.match(str(href))) and m.group(1).lower() == username.lower()
            ),
            None,
        )
        if not own_match or own_match.group(2) in seen:
            continue
        seen.add(own_match.group(2))
        thumb = next(
            (str(s) for s in article.css('img[src*="pbs.twimg.com/media"]::attr(src)')), None
        )
        results.append({
            "kind": "post",
            "embedId": own_match.group(2),
            "url": f"https://x.com/{username}/status/{own_match.group(2)}",
            "title": None,
            "thumbnailUrl": thumb,
        })
        if len(results) >= limit:
            break
    return results
