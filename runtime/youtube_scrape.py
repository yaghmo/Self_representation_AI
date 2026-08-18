"""Best-effort YouTube channel metadata via yt-dlp — no API key, no OAuth.

The scrape can fail for any reason (network, yt-dlp internals, YouTube
changing its markup) and must never block adding the link: every caller
treats None as "no scrape data available", the same as any other platform
that never had a scraper in the first place.
"""

from __future__ import annotations


def scrape_channel(url: str) -> dict | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    try:
        with yt_dlp.YoutubeDL(
            {"quiet": True, "skip_download": True, "playlist_items": "0"}
        ) as ydl:
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
                {"quiet": True, "skip_download": True, "extract_flat": True, "playlistend": limit}
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


def _self_check() -> None:
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_channel("https://www.youtube.com/@YouTube")
    assert result is not None, "expected a successful scrape of a real, stable channel"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"

    # An unrecognized/garbage URL fails cleanly, not with an exception.
    assert scrape_channel("https://www.youtube.com/@this-channel-should-not-exist-xyz123") is None
    assert scrape_channel("not a url at all") is None

    videos = list_videos("https://www.youtube.com/@YouTube", limit=3)
    assert 0 < len(videos) <= 3, f"expected 1-3 videos, got {len(videos)}"
    for video in videos:
        assert video["embedId"], video
        assert video["url"].startswith("https://www.youtube.com/watch?v="), video
        assert video["thumbnailUrl"], video
        assert video["kind"] in ("video", "short"), video

    assert list_videos("https://www.youtube.com/@this-channel-should-not-exist-xyz123") == []

    print("youtube_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
