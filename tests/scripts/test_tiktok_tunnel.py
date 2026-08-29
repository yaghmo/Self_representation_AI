from scripts.tiktok_tunnel import _extract_url, update_redirect_uri


def test_extract_url_finds_trycloudflare_hostname():
    line = "|  https://random-words-here.trycloudflare.com                |"
    assert _extract_url(line) == "https://random-words-here.trycloudflare.com"


def test_extract_url_none_on_unrelated_line():
    assert _extract_url("some other cloudflared log line") is None


def test_update_redirect_uri_writes_callback_path(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER_VAR=keep-me\n", encoding="utf-8")

    result = update_redirect_uri("https://abc123.trycloudflare.com", env_path)

    assert result == "https://abc123.trycloudflare.com/admin/tiktok/callback"
    content = env_path.read_text(encoding="utf-8")
    assert "TIKTOK_REDIRECT_URI=https://abc123.trycloudflare.com/admin/tiktok/callback" in content
    assert "OTHER_VAR=keep-me" in content


def test_update_redirect_uri_overwrites_previous_value(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TIKTOK_REDIRECT_URI=https://old-url.trycloudflare.com/admin/tiktok/callback\n",
        encoding="utf-8",
    )

    update_redirect_uri("https://new-url.trycloudflare.com", env_path)

    content = env_path.read_text(encoding="utf-8")
    assert "old-url" not in content
    assert "new-url" in content
