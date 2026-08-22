import os
import time

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
            "scope": "user.info.basic,video.list",
        })
        assert tiktok_oauth_module.connection_status() == {
            "connected": True, "openId": "abc123", "scope": "user.info.basic,video.list"
        }
        tiktok_oauth_module.disconnect()
        assert tiktok_oauth_module.connection_status() == {"connected": False}
    finally:
        tiktok_oauth_module.TOKEN_PATH = original_token_path
        tiktok_oauth_module._pending_state = None
        if original_key is not None:
            os.environ["TIKTOK_CLIENT_KEY"] = original_key
        if original_secret is not None:
            os.environ["TIKTOK_CLIENT_SECRET"] = original_secret
