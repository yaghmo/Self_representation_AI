import os
import time

import httpx

import runtime.tiktok_oauth as tiktok_oauth_module
from runtime.tiktok_oauth import InvalidState


def test_tiktok_oauth_self_check(tmp_path):
    original_token_path = tiktok_oauth_module.TOKEN_PATH
    original_key = os.environ.pop("TIKTOK_CLIENT_KEY", None)
    original_secret = os.environ.pop("TIKTOK_CLIENT_SECRET", None)
    try:
        tiktok_oauth_module.TOKEN_PATH = tmp_path / "tiktok_token.json"

        assert tiktok_oauth_module.connection_status() == {"connected": False}
        assert tiktok_oauth_module.list_videos() == [], "no connected account -> [], not an exception"

        try:
            tiktok_oauth_module.authorize_url("https://example.com/callback")
        except ValueError:
            pass
        else:
            raise AssertionError("authorize_url accepted a missing client key")

        os.environ["TIKTOK_CLIENT_KEY"] = "test-key"
        url = tiktok_oauth_module.authorize_url("https://example.com/callback")
        assert url.startswith(tiktok_oauth_module._AUTHORIZE_URL)
        assert "client_key=test-key" in url
        assert tiktok_oauth_module._pending_state is not None

        try:
            tiktok_oauth_module.handle_callback("code", "wrong-state", "https://example.com/callback")
        except InvalidState:
            pass
        else:
            raise AssertionError("handle_callback accepted a mismatched state")

        tiktok_oauth_module._save_token({
            "access_token": "tok",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "obtained_at": int(time.time()),
            "open_id": "abc123",
            "username": "thesamshow",
            "scope": "user.info.basic,user.info.profile,video.list",
        })
        assert tiktok_oauth_module.connection_status() == {
            "connected": True,
            "openId": "abc123",
            "username": "thesamshow",
            "scope": "user.info.basic,user.info.profile,video.list",
        }
        assert tiktok_oauth_module.is_connected_to("thesamshow") is True
        assert tiktok_oauth_module.is_connected_to("@thesamshow") is True, "leading @ ignored"
        assert tiktok_oauth_module.is_connected_to("TheSamShow") is True, "case-insensitive"
        assert tiktok_oauth_module.is_connected_to("someone-else") is False
        tiktok_oauth_module.disconnect()
        assert tiktok_oauth_module.connection_status() == {"connected": False}
        assert tiktok_oauth_module.is_connected_to("thesamshow") is False, "nothing connected"
    finally:
        tiktok_oauth_module.TOKEN_PATH = original_token_path
        tiktok_oauth_module._pending_state = None
        if original_key is not None:
            os.environ["TIKTOK_CLIENT_KEY"] = original_key
        if original_secret is not None:
            os.environ["TIKTOK_CLIENT_SECRET"] = original_secret


def test_backfills_username_on_a_token_saved_without_one(tmp_path, monkeypatch):
    """A token saved before this field existed (or left unset by a
    _fetch_username failure at connect time) must not stay permanently
    unmatchable — the next status/match check should pick it up."""
    monkeypatch.setattr(tiktok_oauth_module, "TOKEN_PATH", tmp_path / "tiktok_token.json")
    tiktok_oauth_module._save_token({
        "access_token": "tok",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "obtained_at": int(time.time()),
        "open_id": "abc123",
        "scope": "user.info.basic,user.info.profile,video.list",
    })

    def fake_get(url, params=None, headers=None, timeout=None):
        assert headers == {"Authorization": "Bearer tok"}
        return httpx.Response(
            200,
            json={"data": {"user": {"username": "thesamshow"}}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(tiktok_oauth_module.httpx, "get", fake_get)

    assert tiktok_oauth_module.is_connected_to("thesamshow") is True
    # persisted, not just returned in-memory — a second call shouldn't need another fetch
    assert tiktok_oauth_module._load_token()["username"] == "thesamshow"


def test_fetch_username_failure_leaves_match_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(tiktok_oauth_module, "TOKEN_PATH", tmp_path / "tiktok_token.json")
    tiktok_oauth_module._save_token({
        "access_token": "tok",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "obtained_at": int(time.time()),
        "open_id": "abc123",
        "scope": "user.info.basic,user.info.profile,video.list",
    })

    def fake_get(*args, **kwargs):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(tiktok_oauth_module.httpx, "get", fake_get)

    assert tiktok_oauth_module.is_connected_to("thesamshow") is False, (
        "an unresolved connected account must never be assumed to match"
    )
