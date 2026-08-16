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
    except Exception:
        return None
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

    print("youtube_scrape: all checks passed")


if __name__ == "__main__":
    _self_check()
