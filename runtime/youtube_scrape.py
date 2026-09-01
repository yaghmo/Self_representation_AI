"""Best-effort YouTube channel metadata via yt-dlp — no API key, no OAuth.

The scrape can fail for any reason (network, yt-dlp internals, YouTube
changing its markup) and must never block adding the link: every caller
treats None as "no scrape data available", the same as any other platform
that never had a scraper in the first place.
"""

from __future__ import annotations

# A guessed handle from an LLM-extracted mention 404s as often as it hits —
# yt-dlp's own defaults retry a failed fetch several times with backoff,
# which is the right call for a real download but turns "confirm this
# profile doesn't exist" into a multi-second stall for no benefit: a single
# fast failure is exactly as informative. No retries, short timeout.
_YDL_OPTS = {
    "quiet": True,
    "skip_download": True,
    "retries": 0,
    "extractor_retries": 0,
    "socket_timeout": 5,
}


def scrape_channel(url: str) -> dict | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS | {"playlist_items": "0"}) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return None
        pfp_url = info.get("thumbnail")
        if not pfp_url:
            for thumb in info.get("thumbnails") or []:
                if thumb.get("id") == "avatar_uncropped":
                    pfp_url = thumb.get("url")
                    break
        return {
            "pfp_url": pfp_url,
            "follower_count": info.get("channel_follower_count"),
            "bio": info.get("description"),
        }
    except Exception:
        return None


def list_videos(url: str, limit: int = 6) -> list[dict]:
    """Recent uploads, newest first — the /videos tab first, topped up from
    /shorts if that tab alone doesn't reach `limit` (skipped entirely, no
    extra network call, once /videos already fills the quota).
    """
    try:
        import yt_dlp
    except ImportError:
        return []
    results: list[dict] = []
    for tab, kind in (("videos", "video"), ("shorts", "short")):
        if len(results) >= limit:
            break
        try:
            with yt_dlp.YoutubeDL(
                _YDL_OPTS | {"extract_flat": True, "playlistend": limit}
            ) as ydl:
                info = ydl.extract_info(f"{url.rstrip('/')}/{tab}", download=False)
        except Exception:
            continue
        for entry in (info or {}).get("entries") or []:
            video_id = entry.get("id")
            if not video_id:
                continue
            results.append({
                "kind": kind,
                "embedId": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": entry.get("title"),
                "thumbnailUrl": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            })
            if len(results) >= limit:
                break
    return results
