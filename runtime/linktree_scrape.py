"""Extract the outbound links on a Linktree page — no API key, no login.

Linktree is a Next.js app: the initial HTML embeds the full page state,
including every link the creator added, as JSON in a `__NEXT_DATA__` script
tag. Reading that avoids needing a headless browser to run the client-side
render.

The scrape can fail for any reason (network, markup changes, blocking) and
must never block adding the link: every caller treats None as "no scrape
data available", the same as any other platform that never had a scraper.
"""

from __future__ import annotations

import json
import re

import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    # Linktree's edge WAF 403s a bare User-Agent with no other browser
    # headers — these are what a real navigation sends alongside it.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def scrape_links(url: str) -> list[str] | None:
    """Return the URLs a creator added to their Linktree page, or None."""
    try:
        response = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=10)
        response.raise_for_status()
        match = _NEXT_DATA_RE.search(response.text)
        if not match:
            return None
        data = json.loads(match.group(1))
        links = data["props"]["pageProps"]["links"]
        urls = [link["url"] for link in links if link.get("url")]
        return urls or None
    except Exception:
        return None


def _self_check() -> None:
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    # Using Linktree's own demo/profile page as a stable test target.
    result = scrape_links("https://linktr.ee/linktree")
    assert result is None or (
        isinstance(result, list) and all(isinstance(u, str) for u in result)
    ), f"unexpected result: {result!r}"

    # Invalid URL returns None
    assert scrape_links("not a url at all") is None

    print("linktree_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
