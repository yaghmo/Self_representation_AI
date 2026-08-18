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
from pathlib import Path

from .bible import PROFILE_PATH
from .social import list_socials
from .tiktok_oauth import connection_status as tiktok_oauth_status
from .tiktok_oauth import list_videos as list_tiktok_oauth_videos
from .tiktok_scrape import list_videos as list_tiktok_videos
from .twitch_scrape import list_vods as list_twitch_vods
from .youtube_scrape import list_videos as list_youtube_videos

_LOCK = threading.Lock()

POSTS_PATH = PROFILE_PATH.parent / "posts.json"

POSTS_PER_PLATFORM = 6

_SCRAPERS = {"youtube", "twitch", "tiktok"}


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
        # The OAuth Display API once the creator has connected their
        # account — real metadata (title/thumbnail/id), no yt-dlp/oEmbed
        # fragility. Playback still goes through TikTok's embed widget
        # either way; this only makes the *listing* reliable.
        raw = (
            list_tiktok_oauth_videos(POSTS_PER_PLATFORM)
            if tiktok_oauth_status()["connected"]
            else list_tiktok_videos(social["url"], POSTS_PER_PLATFORM)
        )
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


def _self_check() -> None:
    import tempfile

    import runtime.social as social_module
    import runtime.tiktok_oauth as tiktok_oauth_module
    from .social import add_social

    global POSTS_PATH, list_youtube_videos, list_twitch_vods, list_tiktok_videos

    original_posts_path = POSTS_PATH
    original_profile_json = social_module.PROFILE_JSON_PATH
    original_tiktok_token_path = tiktok_oauth_module.TOKEN_PATH
    original_yt = list_youtube_videos
    original_tw = list_twitch_vods
    original_tk = list_tiktok_videos

    list_youtube_videos = lambda url, limit: [
        {"kind": "video", "embedId": "yt1", "url": "https://y", "title": "t", "thumbnailUrl": "th"}
    ]
    list_twitch_vods = lambda username, limit: [
        {"kind": "vod", "embedId": "tw1", "url": "https://t", "title": "t", "thumbnailUrl": None,
         "publishedAt": "2026-01-01T00:00:00Z"}
    ]
    list_tiktok_videos = lambda url, limit: []

    try:
        with tempfile.TemporaryDirectory() as tmp:
            POSTS_PATH = Path(tmp) / "posts.json"
            social_module.PROFILE_JSON_PATH = Path(tmp) / "profile.json"
            # Deterministic "not connected" regardless of whatever the real
            # TikTok OAuth state on this machine happens to be — otherwise
            # a genuinely connected account would make this self-check hit
            # the real API instead of the stubbed scraper below.
            tiktok_oauth_module.TOKEN_PATH = Path(tmp) / "tiktok_token.json"

            assert list_posts() == [], "no cache file yet -> empty list"
            assert refresh_posts() == [], "no linked socials yet -> nothing to scrape"

            add_social({"platform": "youtube", "username": "h", "url": "https://youtube.com/@h"})
            add_social({"platform": "twitch", "username": "h2", "url": "https://twitch.tv/h2"})
            add_social({"platform": "instagram", "username": "h3", "url": "https://instagram.com/h3"})

            posts = refresh_posts()
            assert len(posts) == 2, "instagram has no scraper -> skipped, not an error"
            assert {p["platform"] for p in posts} == {"youtube", "twitch"}
            for post in posts:
                assert post["id"] == f"{post['platform']}-{post['embedId']}"
                assert post["socialId"]
            assert list_posts() == posts, "refresh must persist to the cache file"
    finally:
        POSTS_PATH = original_posts_path
        social_module.PROFILE_JSON_PATH = original_profile_json
        tiktok_oauth_module.TOKEN_PATH = original_tiktok_token_path
        list_youtube_videos = original_yt
        list_twitch_vods = original_tw
        list_tiktok_videos = original_tk

    print("posts: all checks passed")


if __name__ == "__main__":
    _self_check()
