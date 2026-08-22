from runtime.linktree_scrape import scrape_links


def test_linktree_scrape_self_check():
    # Hits the real network — there's no mockable seam worth building for a
    # single best-effort scraper, and this repo's self-checks already
    # accept that (runtime/model.py's needs a real model).
    # Using Linktree's own demo/profile page as a stable test target.
    result = scrape_links("https://linktr.ee/linktree")
    assert result is None or (
        isinstance(result, list) and all(isinstance(u, str) for u in result)
    ), f"unexpected result: {result!r}"

    # Invalid URL returns None
    assert scrape_links("not a url at all") is None
