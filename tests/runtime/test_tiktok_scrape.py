import runtime.tiktok_scrape as tiktok_scrape_module
from runtime.tiktok_scrape import list_videos, resolve_handle, scrape_profile


def test_tiktok_scrape_self_check():
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_profile("https://www.tiktok.com/@tiktok")
    assert result is not None, "expected a successful scrape of a real, stable profile"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"
    assert "bio_link" in result, "bio_link key must always be present, even when unset (None)"

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


def test_resolve_handle_delegates_to_shared_resolver_with_tiktok_hint(monkeypatch):
    # The DuckDuckGo-search behavior itself (retries, fuzzy-match threshold)
    # is covered live-network-free in test_handle_resolve.py — this only
    # checks that tiktok_scrape.resolve_handle wires the "tiktok" platform
    # hint through to the shared resolver.
    calls = []

    def fake_resolve_handle(display_text, platform_hint):
        calls.append((display_text, platform_hint))
        return "thesamshow"

    monkeypatch.setattr(tiktok_scrape_module, "_resolve_handle", fake_resolve_handle)

    assert resolve_handle("sam") == "thesamshow"
    assert calls == [("sam", "tiktok")]
