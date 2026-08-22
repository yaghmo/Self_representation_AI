from runtime.og_scrape import _extract_follower_count, scrape_profile


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

    # Instagram strips og tags for unauthenticated requests — this scraper
    # returns None there, same as any blocked/unsupported platform.
    assert scrape_profile("https://www.instagram.com/instagram/") is None

    assert scrape_profile("not a url at all") is None
