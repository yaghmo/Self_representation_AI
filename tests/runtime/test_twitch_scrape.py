import os

import runtime.twitch_scrape as twitch_scrape_module
from runtime.twitch_scrape import list_vods, scrape_channel, scrape_panel_links, scrape_social_medias


def test_twitch_scrape_self_check():
    # No credentials in this environment by default — the graceful-fallback
    # path is what's actually testable here without secrets.
    original_id = os.environ.pop("TWITCH_CLIENT_ID", None)
    original_secret = os.environ.pop("TWITCH_CLIENT_SECRET", None)
    twitch_scrape_module._token, twitch_scrape_module._token_expires_at = None, 0.0
    try:
        assert scrape_channel("twitch") is None, "no credentials -> None, not an exception"
    finally:
        if original_id is not None:
            os.environ["TWITCH_CLIENT_ID"] = original_id
        if original_secret is not None:
            os.environ["TWITCH_CLIENT_SECRET"] = original_secret
        twitch_scrape_module._token, twitch_scrape_module._token_expires_at = None, 0.0

    # With real credentials (TWITCH_CLIENT_ID/SECRET set in the environment),
    # this hits the real network — same tier as the other scrapers'
    # self-checks — and should resolve a real, stable channel.
    if os.environ.get("TWITCH_CLIENT_ID") and os.environ.get("TWITCH_CLIENT_SECRET"):
        result = scrape_channel("twitch")
        assert result is not None, "expected a successful scrape with real credentials"
        assert result["pfp_url"], f"expected a pfp_url, got {result['pfp_url']!r}"
        assert result["follower_count"], f"expected a follower_count, got {result['follower_count']!r}"
        assert scrape_channel("this-should-not-exist-xyz123") is None

        # VOD availability varies by channel, so this only checks the shape,
        # not that any come back — a channel with no archived broadcasts is
        # a legitimate [], not a bug.
        vods = list_vods("r0ckyshield", limit=3)
        assert isinstance(vods, list) and len(vods) <= 3, vods
        for vod in vods:
            assert vod["embedId"], vod
            assert vod["url"].startswith("https://www.twitch.tv/"), vod
            assert vod["kind"] == "vod", vod
        assert list_vods("this-should-not-exist-xyz123-nope") == []
    else:
        assert list_vods("twitch") == [], "no credentials -> [], not an exception"

    # scrape_panel_links needs no credentials — the public web client-id
    # isn't ours to set. Real network, same tier as tiktok_scrape's check.
    links = scrape_panel_links("pokimane")
    assert links, "expected at least one panel link on a real, stable channel"
    assert all(url.startswith("http") for url in links), links
    assert scrape_panel_links("this-should-not-exist-xyz123-nope") == []

    social_links = scrape_social_medias("r0ckyshield")
    assert social_links, "expected at least one social link on a real, stable channel"
    assert all(url.startswith("http") for url in social_links), social_links
    assert scrape_social_medias("this-should-not-exist-xyz123-nope") == []
