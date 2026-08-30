import subprocess
import sys

from runtime.embed import EmbeddingNotConfigured, bge_embedder


def test_embed_import_order_does_not_segfault():
    # torch, then transformers (which lazily pulls in pandas) crashes with an
    # access violation on this machine — two copies of the OpenMP runtime in
    # one process, the same class of bug the sentence-transformers/sklearn
    # switch was written to dodge. bge_embedder() must import pandas first.
    # Run in a subprocess against the real configured model: a real segfault
    # here would take the test runner down with it if it happened in-process,
    # and only actually calling bge_embedder() exercises its internal import
    # order — importing torch/transformers directly in this script wouldn't.
    result = subprocess.run(
        [sys.executable, "-c", "from runtime.embed import bge_embedder; bge_embedder()(['hi'])"],
        capture_output=True,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)


def test_embed_self_check(tmp_path):
    # No embedding role configured is the state a fresh machine is in, and it
    # must say so rather than failing somewhere inside a model loader.
    empty = tmp_path / "stack.json"
    empty.write_text('{"version": 1, "roles": {}}', encoding="utf-8")
    try:
        bge_embedder(empty)
    except EmbeddingNotConfigured as exc:
        assert "cookbook" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("a missing embedding role was accepted")

    missing = tmp_path / "nope.json"
    try:
        bge_embedder(missing)
    except EmbeddingNotConfigured:
        pass
    else:
        raise AssertionError("a missing stack.json was accepted")

    # Role configured but weights not on disk — the likeliest failure a user hits.
    # A bogus model_id is guaranteed absent under MODELS_DIR.
    missing_weights = tmp_path / "with_weights.json"
    missing_weights.write_text(
        '{"version": 1, "roles": {"embedding": {"model_id": "nonexistent-model-12345"}}}',
        encoding="utf-8",
    )
    try:
        bge_embedder(missing_weights)
    except EmbeddingNotConfigured as exc:
        assert "cookbook.download" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("a missing weights directory was accepted")
