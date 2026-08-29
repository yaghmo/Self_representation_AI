"""Shared display-nickname -> real-@handle resolver, used by any platform
whose bio can @-mention a display nickname that isn't the account's real
handle (e.g. TikTok's "@sam" for the account "@thesamshow").

Search-engine results title a profile page "name (@handle) | Platform", so
searching the nickname usually surfaces the real handle. Uses DuckDuckGo's
plain HTML results endpoint through Scrapling's `StealthyFetcher`, not a
plain httpx request — a non-browser client gets rate-limited noticeably
fast (confirmed live: a 202 "please wait" shell instead of real results,
after this resolver's own moderate call volume during dev), same class of
bot-gate Instagram's og-tag scrape has (see og_scrape.py) that a real,
even automated, browser gets through.
"""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from urllib.parse import urlencode

from service.logging_config import get_logger

logger = get_logger("runtime.handle_resolve")

_SEARCH_RESULT_RE = re.compile(r'([^<>(){}\n]{1,40})\(@([A-Za-z0-9_.]{1,24})\)')

# Below this, a match is more likely a same-platform stranger the creator
# tagged as a friend than the real account behind a displayed nickname.
_HANDLE_MATCH_THRESHOLD = 0.5

# A miss isn't good evidence the account can't be found — DuckDuckGo's own
# bot-gate (see module docstring) clears itself after a few seconds, not
# after a fraction of one, so the backoff has to actually give it that long.
# A single 0.5s retry was too short to matter, hence the extra attempt.
_RETRY_DELAYS_SECONDS = (1.0, 3.0)


def _search(display_text: str, platform_hint: str) -> str | None:
    query = urlencode({"q": f"{display_text} {platform_hint}"})
    url = f"https://html.duckduckgo.com/html/?{query}"
    try:
        from scrapling.fetchers import StealthyFetcher

        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status != 200:
            logger.warning("handle search non-200: %s -> HTTP %d", url, page.status)
            return None
        titles = [str(t) for t in page.css("a.result__a::text")]
    except Exception:
        logger.exception("handle search failed: %s", url)
        return None
    if not titles:
        logger.warning("handle search returned no result titles: %s", url)
        return None
    best_handle, best_ratio = None, 0.0
    for title in titles:
        match = _SEARCH_RESULT_RE.search(title)
        if not match:
            continue
        name, handle = match.groups()
        ratio = SequenceMatcher(None, display_text.strip().lower(), name.strip().lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_handle = ratio, handle
    if best_handle is None:
        logger.info("handle search: no title matched %r for %r", display_text, platform_hint)
    else:
        logger.info(
            "handle search: %r -> %r (ratio %.2f)", display_text, best_handle, best_ratio
        )
    return best_handle if best_ratio >= _HANDLE_MATCH_THRESHOLD else None


def resolve_handle(display_text: str, platform_hint: str) -> str | None:
    """Only accepted if the matched display name is at least half similar to
    what was tagged, so an unrelated account someone mentioned as a friend
    (not an alt) doesn't get resolved and linked as if it were one. Retries
    on an empty result — see _RETRY_DELAYS_SECONDS for why the backoff is
    seconds, not fractions of one."""
    handle = _search(display_text, platform_hint)
    if handle:
        return handle
    for delay in _RETRY_DELAYS_SECONDS:
        time.sleep(delay)
        handle = _search(display_text, platform_hint)
        if handle:
            return handle
    return None
