"""Extract the outbound links on a Linktree page — no API key, no login.

Linktree is a Next.js app: the initial HTML embeds the full page state,
including every link the creator added, as JSON in a `__NEXT_DATA__` script
tag. Reading that avoids needing a headless browser to run the client-side
render.

The scrape can fail for any reason (network, markup changes, blocking) and
must never block adding the link: every caller treats None as "no scrape
data available", the same as any other platform that never had a scraper.

Linktree's edge WAF fingerprints the TLS handshake, not just headers — a
plain httpx/urllib3 request 403s even with a full browser header set, while
curl (and curl_cffi's Chrome impersonation) pass. curl_cffi is already an
installed transitive dependency, so no new package is needed.
"""

from __future__ import annotations

import json
import re

from curl_cffi import requests

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def scrape_links(url: str) -> list[str] | None:
    """Return the URLs a creator added to their Linktree page, or None."""
    try:
        response = requests.get(url, impersonate="chrome", timeout=10)
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

