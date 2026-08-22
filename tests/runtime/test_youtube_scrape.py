from runtime.youtube_scrape import list_videos, scrape_channel


def test_youtube_scrape_self_check():
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
