"""Shared display-nickname -> real-@handle resolver, used by any platform
whose bio can @-mention a display nickname that isn't the account's real
handle (e.g. TikTok's "@sam" for the account "@thesamshow").

Search-engine results title a profile page "name (@handle) | Platform", so
searching the nickname usually surfaces the real handle. Queries the
project's own SearXNG instance (docker-compose.yml's `searxng` service, a
self-hosted metasearch aggregator) over plain httpx rather than driving a
browser at one search engine's HTML directly — no browser-launch latency,
and one upstream engine (DuckDuckGo, Google, ...) rate-limiting itself
doesn't take the whole lookup down since SearXNG merges several.
"""

from __future__ import annotations

import os
import re
import time
from difflib import SequenceMatcher

import httpx

from cookbook.probe import _detect_container
from service.logging_config import get_logger

logger = get_logger("runtime.handle_resolve")

# Mirrors runtime/qwentts.py's DEFAULT_HOST pattern — the compose network's
# service-name DNS only resolves from inside a sibling container; a bare
# `uv run` on the host instead reaches the port docker-compose.yml publishes.
SEARXNG_URL = os.environ.get(
    "SEARXNG_URL",
    "http://searxng:8080" if _detect_container() else "http://localhost:8081",
)

_SEARCH_RESULT_RE = re.compile(r'([^<>(){}\n]{1,40})\(@([A-Za-z0-9_.]{1,24})\)')

# Below this, a match is more likely a same-platform stranger the creator
# tagged as a friend than the real account behind a displayed nickname.
_HANDLE_MATCH_THRESHOLD = 0.5

# A plain JSON API call to our own instance, not a browser fighting a bot
# gate — these are just a couple of retries for an ordinary transient
# network hiccup, not the many-second backoff a search engine's own
# rate-limiting used to need.
_RETRY_DELAYS_SECONDS = (0.5, 1.5)


# A result's title doesn't reliably read "Name (@handle) | Platform" any
# more (TikTok's own SERP titles often carry no handle at all) — the
# profile URL usually does, so it's checked too, not just the title.
_PROFILE_URL_PATTERNS = {
    "tiktok": re.compile(r"tiktok\.com/@([A-Za-z0-9_.]{1,24})"),
    "instagram": re.compile(
        r"instagram\.com/(?!p/|reel/|reels/|explore/|accounts/|stories/)"
        r"([A-Za-z0-9_.]{1,30})"
    ),
}


def _search(display_text: str, platform_hint: str) -> str | None:
    query = f"{display_text} {platform_hint}"
    try:
        response = httpx.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
    except Exception:
        logger.exception("handle search failed: %s", query)
        return None
    if not results:
        logger.warning("handle search returned no results: %s", query)
        return None

    needle = display_text.strip().lower()
    url_pattern = _PROFILE_URL_PATTERNS.get(platform_hint)
    best_handle, best_ratio = None, 0.0

    for result in results:
        title_match = _SEARCH_RESULT_RE.search(result.get("title") or "")
        if title_match:
            name, handle = title_match.groups()
            ratio = SequenceMatcher(None, needle, name.strip().lower()).ratio()
            if ratio > best_ratio:
                best_ratio, best_handle = ratio, handle
        if url_pattern:
            url_match = url_pattern.search(result.get("url") or "")
            if url_match:
                handle = url_match.group(1)
                ratio = SequenceMatcher(None, needle, handle.lower()).ratio()
                if ratio > best_ratio:
                    best_ratio, best_handle = ratio, handle

    if best_handle is None:
        logger.info("handle search: no match for %r on %r", display_text, platform_hint)
    else:
        logger.info(
            "handle search: %r -> %r (ratio %.2f)", display_text, best_handle, best_ratio
        )
    return best_handle if best_ratio >= _HANDLE_MATCH_THRESHOLD else None


def resolve_handle(display_text: str, platform_hint: str) -> str | None:
    """Only accepted if the matched display name is at least half similar to
    what was tagged, so an unrelated account someone mentioned as a friend
    (not an alt) doesn't get resolved and linked as if it were one. Retries
    a couple of times on an empty result — see _RETRY_DELAYS_SECONDS."""
    handle = _search(display_text, platform_hint)
    if handle:
        return handle
    for delay in _RETRY_DELAYS_SECONDS:
        time.sleep(delay)
        handle = _search(display_text, platform_hint)
        if handle:
            return handle
    return None
