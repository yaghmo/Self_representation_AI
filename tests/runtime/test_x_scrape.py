from runtime.x_scrape import list_posts


def test_x_scrape_self_check():
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    posts = list_posts("https://x.com/X", limit=3)
    assert 0 < len(posts) <= 3, f"expected 1-3 posts, got {len(posts)}"
    for post in posts:
        assert post["embedId"].isdigit(), post
        assert post["url"] == f"https://x.com/X/status/{post['embedId']}", post
        assert post["kind"] == "post", post

    assert list_posts("https://x.com/this-should-not-exist-xyz123") == []
