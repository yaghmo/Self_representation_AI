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


def _self_check() -> None:
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_profile("https://www.tiktok.com/@tiktok")
    assert result is not None, "expected a successful scrape of a real, stable profile"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"

    # TikTok returns 200 with a client-side-rendered shell for a
    # nonexistent/banned profile — no userInfo in the embedded JSON, not an
    # HTTP error, so this exercises the KeyError path rather than a status
    # code.
    assert scrape_profile("https://www.tiktok.com/@this-should-not-exist-xyz123") is None
    assert scrape_profile("not a url at all") is None

    videos = list_videos("https://www.tiktok.com/@tiktok", limit=3)
    assert 0 < len(videos) <= 3, f"expected 1-3 videos, got {len(videos)}"
    for video in videos:
        assert video["embedId"], video
        assert video["url"], video
        assert video["kind"] == "video", video
        assert video["thumbnailUrl"], f"expected an oEmbed-derived thumbnail, got {video!r}"

    assert list_videos("https://www.tiktok.com/@this-should-not-exist-xyz123") == []

    print("tiktok_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
