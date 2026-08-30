from pathlib import Path

from cookbook.fit import (
    CONVERSATION_RESERVE_TOKENS,
    Budget,
    Placement,
    Selection,
    _measure,
    bible_tokens,
    evaluate,
    strategy_for,
)
from cookbook.schema import GB, Catalogue, ModelEntry


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


def _tts_model(device: str) -> ModelEntry:
    return ModelEntry(
        id="test-tts",
        role="tts",
        repo="test/test",
        weights_bytes=3 * GB,
        runtime_overhead_bytes=0,
        devices=(device,),
        quality=88,
    )


def test_transient_gpu_tts_excluded_from_steady_state_budget():
    catalogue = Catalogue(models=[_tts_model("transient-gpu")])
    budget = Budget(
        vram_bytes=1 * GB, ram_bytes=8 * GB,
        vram_raw=1 * GB, ram_raw=8 * GB, has_gpu=True,
    )
    selection = Selection(
        context_tokens=4096,
        placements={"tts": Placement("test-tts", "transient-gpu")},
    )

    fit = evaluate(selection, catalogue, budget)

    assert fit.vram_used == 0
    assert fit.ram_used == 0
    assert fit.ok, fit.reasons
    # Still reported for the UI, just not folded into either budget sum.
    assert fit.per_model["tts"] == 3 * GB


def test_transient_gpu_tts_blocked_without_a_gpu():
    catalogue = Catalogue(models=[_tts_model("transient-gpu")])
    budget = Budget(
        vram_bytes=0, ram_bytes=8 * GB,
        vram_raw=0, ram_raw=8 * GB, has_gpu=False,
    )
    selection = Selection(
        context_tokens=4096,
        placements={"tts": Placement("test-tts", "transient-gpu")},
    )

    fit = evaluate(selection, catalogue, budget)

    assert not fit.ok
    assert "no usable GPU" in fit.verdict()
