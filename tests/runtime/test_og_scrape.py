from runtime.og_scrape import (
    _extract_follower_count,
    _extract_instagram_follower_count,
    list_instagram_posts,
    scrape_profile,
)


def test_og_scrape_self_check():
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_profile("https://x.com/X")
    assert result is not None, "expected a successful scrape of a real, stable profile"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"
    # @X's og:description is its real bio ("what's happening?!"), not the
    # generic follower-count fallback — this account happening not to match
    # is incidental to X's own behavior, not something this scraper controls.
    assert result["follower_count"] is None, "this account's bio carries no count to extract"

    # Deterministic, independent of whatever X happens to serve live: the
    # generic fallback description's exact shape parses; an ordinary bio
    # (even one that starts with a number) does not.
    assert _extract_follower_count("9 followers · 4 following. Joined Mar 2026.") == 9
    assert _extract_follower_count("1,234 Followers · 56 Following.") == 1234
    assert _extract_follower_count("what's happening?!") is None
    assert _extract_follower_count(None) is None

    # Instagram strips og tags for a plain non-browser request, but not for
    # a real (even logged-out) browser — Scrapling's StealthyFetcher gets
    # through where the httpx path above can't.
    ig_result = scrape_profile("https://www.instagram.com/instagram/")
    assert ig_result is not None, "expected a successful Scrapling-backed scrape"
    assert ig_result["pfp_url"], f"expected a pfp_url, got {ig_result['pfp_url']!r}"
    assert ig_result["bio"], f"expected a bio, got {ig_result['bio']!r}"
    assert ig_result["follower_count"], (
        f"expected a follower_count parsed from the bio, got {ig_result['follower_count']!r}"
    )

    assert _extract_instagram_follower_count("686M Followers, 276 Following, 8,562 Posts") == 686_000_000
    assert _extract_instagram_follower_count("9,876 Followers, 1 Following, 3 Posts") == 9876
    assert _extract_instagram_follower_count("just a bio, no counts here") is None
    assert _extract_instagram_follower_count(None) is None

    assert scrape_profile("not a url at all") is None

    posts = list_instagram_posts("https://www.instagram.com/instagram/", limit=3)
    assert 0 < len(posts) <= 3, f"expected 1-3 posts, got {len(posts)}"
    for post in posts:
        assert post["embedId"], post
        assert post["url"].startswith("https://www.instagram.com/"), post
        assert post["kind"] in ("image", "video"), post
        assert post["thumbnailUrl"], f"expected a thumbnail, got {post!r}"

    assert list_instagram_posts("https://www.instagram.com/this-should-not-exist-xyz123/") == []
