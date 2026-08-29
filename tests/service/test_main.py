"""Runs service.main's self-check under pytest.

Stays defined in service/main.py, not relocated here — it reassigns ~18 of
that module's own top-level names via `global`, which only rebinds correctly
in the module it's defined in. This is just the pytest-discoverable wrapper.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import runtime.social as social_module
import service.main as main_module
from service.main import _self_check, app


def test_main_self_check():
    _self_check()


def test_extract_mentions_strips_newlines_and_accepts_bare_type():
    """Regression for a real bio ('@samtoo \\nmore stuff vv') that came back
    with zero mentions: the local model's JSON extraction breaks on a literal
    newline in the bio text, and separately sometimes echoes the prompt's own
    "bare handle" wording back as `"type": "bare"` instead of `"platform"`."""
    seen_content = {}

    def fake_chat(messages, **kwargs):
        seen_content["bio"] = messages[0].content.split("\n\n")[-1]
        assert "\n" not in seen_content["bio"], "newline must be collapsed before reaching the model"
        return '[{"type": "bare", "platform": null, "value": "samtoo"}]'

    model = SimpleNamespace(chat=fake_chat)
    mentions = main_module._extract_mentions(model, "@samtoo \nmore stuff vv", "tiktok")
    assert seen_content["bio"] == "@samtoo more stuff vv"
    assert len(mentions) == 1
    assert mentions[0].type == "platform"
    assert mentions[0].platform == "tiktok"
    assert mentions[0].value == "samtoo"


def test_mentions_from_urls_resolves_known_shortener(monkeypatch):
    """X serves its 'website' profile field as og:description verbatim — a
    t.co shortlink, not the real destination — so a mention behind one is
    invisible unless the redirect gets resolved first."""

    class FakeResponse:
        url = "https://linktr.ee/creator"

    def fake_head(url, follow_redirects=True, timeout=5):
        assert url == "https://t.co/abc123"
        return FakeResponse()

    monkeypatch.setattr(main_module.httpx, "head", fake_head)
    mentions = main_module._mentions_from_urls(["https://t.co/abc123"], exclude_platform="x")
    assert len(mentions) == 1
    assert mentions[0].platform == "linktree"
    assert mentions[0].value == "creator"

    # A non-shortener domain must never trigger a network call.
    def unexpected_head(*a, **k):
        raise AssertionError("should not resolve a non-shortener domain")

    monkeypatch.setattr(main_module.httpx, "head", unexpected_head)
    assert main_module._mentions_from_urls(["https://example.com/x"], exclude_platform="x") == []


def test_social_preview_expands_bio_url_and_linktree_mention(tmp_path, monkeypatch):
    """A bio containing a bare @handle (same-platform alt) *and* a raw
    Linktree URL should surface the alt account plus everything the
    Linktree page links to, deduped across sources — not just the handle,
    and not the same account twice when both the bio and the Linktree page
    name it."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    def fake_chat(messages, **kwargs):
        return '[{"type": "platform", "platform": "tiktok", "value": "alt"}]'

    monkeypatch.setattr(
        main_module,
        "_model",
        SimpleNamespace(loaded=True, agent=True, chat=fake_chat),
    )

    def fake_tiktok(url):
        if url.endswith("@creator"):
            return {
                "pfp_url": "https://img/creator.jpg",
                "follower_count": 100,
                "bio": "backup: @alt more links: linktr.ee/mylinks",
            }
        return {"pfp_url": "https://img/alt.jpg", "follower_count": 5, "bio": None}

    def fake_linktree(url):
        assert url == "https://linktr.ee/mylinks"
        # Same alt TikTok the bio already names, plus a new Instagram —
        # the alt must not come back twice.
        return ["https://tiktok.com/@alt", "https://instagram.com/creator2"]

    def fake_og(url):
        return {"pfp_url": "https://img/ig.jpg", "follower_count": 3, "bio": None}

    monkeypatch.setattr(main_module, "scrape_tiktok_profile", fake_tiktok)
    monkeypatch.setattr(main_module, "scrape_linktree_links", fake_linktree)
    monkeypatch.setattr(main_module, "scrape_og_profile", fake_og)
    # The tiktok branch now always cross-checks a search resolution too —
    # nothing to resolve here, so it must be a no-op back to the guess.
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: None)

    client = TestClient(app)
    response = client.post(
        "/admin/social/preview", json={"url": "https://tiktok.com/@creator"}
    )
    assert response.status_code == 200, response.text
    mentions = response.json()["mentions"]
    seen = {(m["platform"], m["value"]) for m in mentions}
    assert seen == {("tiktok", "alt"), ("instagram", "creator2")}, mentions
    by_platform = {m["platform"]: m["confidence"] for m in mentions}
    # Both are scrape-verifiable and neither (fake) bio names the primary
    # account back, so both are merely confirmed-to-exist, not "confirmed".
    assert by_platform == {"tiktok": "likely", "instagram": "likely"}, mentions


def test_filter_mentions_confirms_mutual_backreference(tmp_path, monkeypatch):
    """The tree-check: a candidate alt account whose own (already-scraped,
    no extra request) bio tags the primary account back is a 100%-confirmed
    match, not just a verified-to-exist guess."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    def fake_tiktok(url):
        assert url == "https://tiktok.com/@alt"
        return {"pfp_url": "https://img/alt.jpg", "follower_count": 5, "bio": "main: @creator"}

    monkeypatch.setattr(main_module, "scrape_tiktok_profile", fake_tiktok)
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: None)

    mention = main_module.SocialMention(type="platform", platform="tiktok", value="alt")
    kept = main_module._filter_mentions([mention], "tiktok", "creator")
    assert len(kept) == 1
    assert kept[0].confidence == "confirmed"
    assert kept[0].pfpUrl == "https://img/alt.jpg"
    assert kept[0].followerCount == 5


def test_filter_mentions_confirms_shared_bio_link(tmp_path, monkeypatch):
    """A resolved-via-search candidate whose bio doesn't @-tag the primary
    back can still be confirmed if its bio lists the same link (Linktree,
    website, ...) the primary's own bio does — the mutual-backreference
    check alone would miss this."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    def fake_tiktok(url):
        assert url == "https://tiktok.com/@alt"
        return {
            "pfp_url": "https://img/alt.jpg",
            "follower_count": 5,
            "bio": "shop: linktr.ee/creatorname",
        }

    monkeypatch.setattr(main_module, "scrape_tiktok_profile", fake_tiktok)
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: None)

    mention = main_module.SocialMention(type="platform", platform="tiktok", value="alt")
    kept = main_module._filter_mentions(
        [mention], "tiktok", "creator", "main account — shop: linktr.ee/creatorname"
    )
    assert len(kept) == 1
    assert kept[0].confidence == "confirmed"

    # No shared link -> falls back to merely "likely", same as before.
    mention2 = main_module.SocialMention(type="platform", platform="tiktok", value="alt")
    kept2 = main_module._filter_mentions(
        [mention2], "tiktok", "creator", "main account — no links here"
    )
    assert kept2[0].confidence == "likely"


def test_filter_mentions_drops_weak_connection(tmp_path, monkeypatch):
    """A verifiable-platform mention that fails every check available to
    it — guessed profile 404s, search resolution finds nothing similar
    enough — is noise, not a real lead, and gets dropped outright. (Used
    to be kept-but-flagged before search resolution existed; now that a
    full resolve pass runs first, whatever's still unverified after that
    really is a dead end.)"""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(main_module, "scrape_tiktok_profile", lambda url: None)
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: None)

    mention = main_module.SocialMention(type="platform", platform="tiktok", value="ABC")
    kept = main_module._filter_mentions([mention], "tiktok", "creator")
    assert kept == []


def test_filter_mentions_keeps_unscrapeable_platform(tmp_path, monkeypatch):
    """A platform with no verification scrape at all (telegram, throne, ...)
    can never be checked either way, so unlike a failed-verification drop
    above, it stays kept-but-flagged — dropping it would lose a real
    mention the creator could still find manually."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    mention = main_module.SocialMention(type="platform", platform="telegram", value="somebody")
    kept = main_module._filter_mentions([mention], "tiktok", "creator")
    assert len(kept) == 1
    assert kept[0].confidence == "unverified"
    assert kept[0].pfpUrl is None
    assert kept[0].followerCount is None


def test_filter_mentions_tiktok_search_overrides_wrong_literal_match(tmp_path, monkeypatch):
    """A guessed handle can 200 — TikTok lets a display nickname collide
    with a *different, real* account's actual @handle — so a successful
    guess isn't proof it's the right one. Search resolution disagreeing
    with the guess must win over just trusting whatever the literal text
    happened to resolve to."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    def fake_tiktok(url):
        if url == "https://tiktok.com/@sam":
            # A real, unrelated account that just happens to be named
            # literally "@sam" — not the creator's alt.
            return {"pfp_url": "https://img/wrong.jpg", "follower_count": 2, "bio": None}
        assert url == "https://tiktok.com/@thesamshow"
        return {"pfp_url": "https://img/right.jpg", "follower_count": 500, "bio": None}

    monkeypatch.setattr(main_module, "scrape_tiktok_profile", fake_tiktok)
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: "thesamshow")

    mention = main_module.SocialMention(type="platform", platform="tiktok", value="sam")
    kept = main_module._filter_mentions([mention], "tiktok", "creator")
    assert len(kept) == 1
    assert kept[0].value == "thesamshow"
    assert kept[0].pfpUrl == "https://img/right.jpg"
    assert kept[0].followerCount == 500


def test_filter_mentions_second_hop_discovers_new_account(tmp_path, monkeypatch):
    """A verified candidate's own bio can carry a link the primary's bio
    never mentioned — that gets mined too (one hop past the first-hop
    candidate, not recursively past the newly found one) and the
    discovered account gets scraped and offered like any other suggestion."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: None)

    def fake_tiktok(url):
        if url == "https://tiktok.com/@alt":
            return {
                "pfp_url": "https://img/alt.jpg",
                "follower_count": 5,
                "bio": "also on IG @sidequest",
            }
        return None

    def fake_og(url):
        assert url == "https://instagram.com/sidequest"
        return {"pfp_url": "https://img/sidequest.jpg", "follower_count": 9, "bio": None}

    def fake_chat(messages, **kwargs):
        bio = messages[0].content.split("\n\n")[-1]
        if "sidequest" in bio:
            return '[{"type": "platform", "platform": "instagram", "value": "sidequest"}]'
        return "[]"

    monkeypatch.setattr(main_module, "scrape_tiktok_profile", fake_tiktok)
    monkeypatch.setattr(main_module, "scrape_og_profile", fake_og)
    model = SimpleNamespace(chat=fake_chat)

    mention = main_module.SocialMention(type="platform", platform="tiktok", value="alt")
    kept = main_module._filter_mentions([mention], "tiktok", "creator", None, model)
    seen = {(m.platform, m.value) for m in kept}
    assert seen == {("tiktok", "alt"), ("instagram", "sidequest")}, kept


def test_filter_mentions_resolves_nickname_via_search(tmp_path, monkeypatch):
    """A bio tagging "@sam" when the real account is "@thesamshow": the
    direct guess 404s, search-based resolution finds the real handle, and
    the mention's value gets updated to point at the real profile."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    def fake_tiktok(url):
        if url == "https://tiktok.com/@sam":
            return None  # nickname, not the real handle — 404s
        assert url == "https://tiktok.com/@thesamshow"
        return {"pfp_url": "https://img/sam.jpg", "follower_count": 500, "bio": None}

    monkeypatch.setattr(main_module, "scrape_tiktok_profile", fake_tiktok)
    monkeypatch.setattr(main_module, "resolve_tiktok_handle", lambda text: "thesamshow")

    mention = main_module.SocialMention(type="platform", platform="tiktok", value="sam")
    kept = main_module._filter_mentions([mention], "tiktok", "creator")
    assert len(kept) == 1
    assert kept[0].value == "thesamshow"
    assert kept[0].confidence == "likely"
    assert kept[0].pfpUrl == "https://img/sam.jpg"
    assert kept[0].followerCount == 500


def test_filter_mentions_resolves_instagram_nickname_via_search(tmp_path, monkeypatch):
    """Same nickname-vs-real-handle gap as TikTok's, now that Instagram is
    scrape-verifiable (Scrapling gets past its og-tag gate)."""
    monkeypatch.setattr(social_module, "PROFILE_JSON_PATH", tmp_path / "profile.json")

    def fake_og(url):
        if url == "https://instagram.com/sam":
            return None  # nickname, not the real handle — no og tags
        assert url == "https://instagram.com/thesamshow"
        return {"pfp_url": "https://img/sam.jpg", "follower_count": 500, "bio": None}

    monkeypatch.setattr(main_module, "scrape_og_profile", fake_og)
    monkeypatch.setattr(main_module, "resolve_instagram_handle", lambda text: "thesamshow")

    mention = main_module.SocialMention(type="platform", platform="instagram", value="sam")
    kept = main_module._filter_mentions([mention], "instagram", "creator")
    assert len(kept) == 1
    assert kept[0].value == "thesamshow"
    assert kept[0].confidence == "likely"
    assert kept[0].pfpUrl == "https://img/sam.jpg"
    assert kept[0].followerCount == 500
