"""Best-effort TikTok profile metadata scraped from the public profile page
— no API key, no login. TikTok's public page embeds a
`__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON blob with everything needed;
yt-dlp's TikTok extractor only sees video listings, not this profile data.

The scrape can fail for any reason (network, markup changes, TikTok
blocking the request) and must never block adding the link: every caller
treats None as "no scrape data available", the same as any other platform
that never had a scraper in the first place.
"""

from __future__ import annotations

import json
import re

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_DATA_SCRIPT_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
    re.S,
)


def scrape_profile(url: str) -> dict | None:
    try:
        response = httpx.get(
            url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=10
        )
        response.raise_for_status()
        match = _DATA_SCRIPT_RE.search(response.text)
        if not match:
            return None
        data = json.loads(match.group(1))
        user_info = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
        user = user_info["user"]
        stats = user_info["stats"]
        return {
            "pfp_url": user.get("avatarLarger"),
            "follower_count": stats.get("followerCount"),
            "bio": user.get("signature"),
        }
    except Exception:
        return None


_OEMBED_URL = "https://www.tiktok.com/oembed"


def _oembed_thumbnail(video_url: str) -> str | None:
    """yt-dlp's flat extraction (list_videos below) never returns a
    thumbnail for TikTok, so this fills the gap with one small call to
    TikTok's own oEmbed endpoint per video — best-effort, None on failure,
    never raises."""
    try:
        response = httpx.get(_OEMBED_URL, params={"url": video_url}, timeout=10)
        response.raise_for_status()
        return response.json().get("thumbnail_url")
    except Exception:
        return None


def list_videos(url: str, limit: int = 6) -> list[dict]:
    """Recent videos, newest first — via yt-dlp, not the profile-page scrape
    above: yt-dlp's TikTok extractor handles video listings, the profile
    page's embedded JSON handles pfp/follower/bio, neither covers both."""
    try:
        import yt_dlp
    except ImportError:
        return []
    try:
        with yt_dlp.YoutubeDL(
            {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": limit}
        ) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return []
    results = []
    for entry in (info or {}).get("entries") or []:
        video_id = entry.get("id")
        if not video_id:
            continue
        video_url = entry.get("url") or entry.get("webpage_url") or f"{url.rstrip('/')}/video/{video_id}"
        results.append({
            "kind": "video",
            "embedId": video_id,
            "url": video_url,
            "title": entry.get("title"),
            "thumbnailUrl": entry.get("thumbnail") or _oembed_thumbnail(video_url),
        })
        if len(results) >= limit:
            break
    return results


