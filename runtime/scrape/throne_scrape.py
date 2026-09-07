"""Best-effort Throne wishlist profile metadata via OpenGraph meta tags.

Throne (throne.com) sits behind Vercel's bot-protection checkpoint — a JS
challenge that 429s a plain httpx/curl_cffi request outright (a "Vercel
Security Checkpoint" interstitial), not just a header or TLS-fingerprint
check like linktree_scrape.py's case. Only a real, JS-executing browser gets
past it, so this goes through Scrapling's `StealthyFetcher`, same as
og_scrape.py's Instagram branch.

Throne's og:description is a fixed "Send X gifts via Throne..." template,
not a stat, so there's no follower-count field to parse out — follower_count
always stays None here, same contract as any other platform whose
og:description doesn't carry a parseable count.

A nonexistent handle doesn't 404 — Throne 307-redirects it to their own
`/landing` marketing page, which serves a real 200 with a genuine (but
generic, not-this-account) og:image/description. Following redirects and
stopping at 200 alone would read every made-up handle as a verified real
account, so the final URL is checked against `/landing` explicitly.

The scrape can fail for any reason (network, markup changes, blocking) and
must never block adding the link: every caller treats None as "no scrape
data available", the same as any other platform that never had a scraper.
"""

from __future__ import annotations

from urllib.parse import urlparse


def scrape_profile(url: str) -> dict | None:
    """Return {"pfp_url", "follower_count", "bio"} for a Throne profile URL,
    or None if the account doesn't exist or the scrape failed."""
    try:
        from scrapling.fetchers import StealthyFetcher

        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status != 200:
            return None
        if urlparse(page.url).path.strip("/") == "landing":
            return None
        pfp_url = next(iter(page.css('meta[property="og:image"]::attr(content)')), None)
        bio = next(iter(page.css('meta[property="og:description"]::attr(content)')), None)
        pfp_url = str(pfp_url) if pfp_url else None
        bio = str(bio) if bio else None
        if not pfp_url and not bio:
            return None
        return {"pfp_url": pfp_url, "follower_count": None, "bio": bio}
    except Exception:
        return None
