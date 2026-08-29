import runtime.handle_resolve as handle_resolve_module
from runtime.handle_resolve import resolve_handle


def test_resolve_handle_retries_on_empty_result(monkeypatch):
    """DuckDuckGo's result set for the exact same query genuinely varies
    call to call — a bare miss on the first attempt must not be taken as
    final, now that a miss here means the caller drops the mention outright."""
    calls = []

    def fake_search(display_text, platform_hint):
        calls.append((display_text, platform_hint))
        return None if len(calls) < 3 else "thesamshow"

    monkeypatch.setattr(handle_resolve_module, "_search", fake_search)
    monkeypatch.setattr(handle_resolve_module.time, "sleep", lambda seconds: None)

    assert resolve_handle("sam", "tiktok") == "thesamshow"
    assert len(calls) == 3, "must keep retrying through both backoff delays"


def test_resolve_handle_stops_retrying_once_delays_exhausted(monkeypatch):
    calls = []

    def fake_search(display_text, platform_hint):
        calls.append((display_text, platform_hint))
        return None

    monkeypatch.setattr(handle_resolve_module, "_search", fake_search)
    monkeypatch.setattr(handle_resolve_module.time, "sleep", lambda seconds: None)

    assert resolve_handle("sam", "tiktok") is None
    assert len(calls) == 1 + len(handle_resolve_module._RETRY_DELAYS_SECONDS)


def test_resolve_handle_no_retry_when_first_call_hits(monkeypatch):
    calls = []

    def fake_search(display_text, platform_hint):
        calls.append((display_text, platform_hint))
        return "thesamshow"

    monkeypatch.setattr(handle_resolve_module, "_search", fake_search)

    assert resolve_handle("sam", "tiktok") == "thesamshow"
    assert len(calls) == 1, "a first-call hit must not trigger a wasted retry"


def test_resolve_handle_none_when_both_attempts_miss(monkeypatch):
    monkeypatch.setattr(handle_resolve_module, "_search", lambda text, hint: None)
    monkeypatch.setattr(handle_resolve_module.time, "sleep", lambda seconds: None)

    assert resolve_handle("nonexistent nonsense", "tiktok") is None
