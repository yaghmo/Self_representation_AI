"""Cached feed of recent posts pulled from the creator's linked youtube/
twitch/tiktok accounts. Refreshed by an explicit admin action, never
scraped live on a fan's page load — same contract as pfp/banner/bio in
`social.py`: scrape once, serve the cache.
"""

from __future__ import annotations

import json
import threading
import time
from itertools import zip_longest

from .bible import PROFILE_PATH
from .og_scrape import list_instagram_posts
from .social import list_socials
from .tiktok_scrape import list_videos as list_tiktok_videos
from .twitch_scrape import list_vods as list_twitch_vods
from .x_scrape import list_posts as list_x_posts
from .youtube_scrape import list_videos as list_youtube_videos

_LOCK = threading.Lock()

POSTS_PATH = PROFILE_PATH.parent / "posts.json"

POSTS_PER_PLATFORM = 6

_SCRAPERS = {"youtube", "twitch", "tiktok", "instagram", "x"}


def list_posts() -> list[dict]:
    if not POSTS_PATH.exists():
        return []
    return json.loads(POSTS_PATH.read_text(encoding="utf-8")).get("posts", [])


def _scrape_social(social: dict) -> list[dict]:
    platform = social["platform"].lower()
    if platform == "youtube":
        raw = list_youtube_videos(social["url"], POSTS_PER_PLATFORM)
    elif platform == "twitch":
        raw = list_twitch_vods(social["username"], POSTS_PER_PLATFORM)
    elif platform == "tiktok":
        raw = list_tiktok_videos(social["url"], POSTS_PER_PLATFORM)
    elif platform == "instagram":
        raw = list_instagram_posts(social["url"], POSTS_PER_PLATFORM)
    elif platform == "x":
        raw = list_x_posts(social["url"], POSTS_PER_PLATFORM)
    else:
        return []
    return [
        {
            "id": f"{platform}-{item['embedId']}",
            "platform": platform,
            "socialId": social["id"],
            "publishedAt": None,
            **item,
        }
        for item in raw
    ]


def _interleave(lists: list[list[dict]]) -> list[dict]:
    """Round-robins each platform's own newest-first order rather than
    sorting on publishedAt directly — YouTube/TikTok listings don't reliably
    carry a timestamp, so a global chronological merge isn't possible across
    all three platforms; this still reads as one mixed feed."""
    result = []
    for row in zip_longest(*lists):
        result.extend(item for item in row if item is not None)
    return result


def refresh_posts() -> list[dict]:
    with _LOCK:
        by_platform: dict[str, list[dict]] = {}
        for social in list_socials():
            platform = social["platform"].lower()
            if platform not in _SCRAPERS:
                continue
            by_platform.setdefault(platform, []).extend(_scrape_social(social))

        posts = _interleave(list(by_platform.values()))
        POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        POSTS_PATH.write_text(
            json.dumps({"version": 1, "refreshedAt": int(time.time()), "posts": posts}, indent=2),
            encoding="utf-8",
        )
        return posts


