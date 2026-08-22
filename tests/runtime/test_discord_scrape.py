from runtime.discord_scrape import scrape_invite


def test_discord_scrape_self_check():
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    result = scrape_invite("discord-developers")
    assert result is not None, "expected a successful resolve of a real, stable invite"
    assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
    assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
    assert result["bio"] is not None, "expected a bio (may be empty string, not None)"

    assert scrape_invite("this-should-not-exist-xyz123-nope") is None
    assert scrape_invite("not a valid code at all !!") is None
