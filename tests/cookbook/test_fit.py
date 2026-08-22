from pathlib import Path

from cookbook.fit import CONVERSATION_RESERVE_TOKENS, _measure, bible_tokens, strategy_for


def test_fit_self_check():
    # bible_tokens takes no surface: one stack serves both modes, and the
    # agent reads sources.md through tools rather than holding it in context.
    tokens = bible_tokens()
    assert isinstance(tokens, int) and tokens > 0, tokens

    # Whichever way it was measured, the strategy threshold is that number
    # plus the conversation reserve. Assert on the boundary, not a constant,
    # so this keeps testing the logic when the profile grows.
    threshold = tokens + CONVERSATION_RESERVE_TOKENS
    assert strategy_for(threshold) == "whole-bible"
    assert strategy_for(threshold - 1) == "retrieval"

    # The fallback path: no data/ on a fresh clone.
    assert _measure(Path("does-not-exist.md"), 4_242) == 4_242
