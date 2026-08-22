from runtime.embed import EmbeddingNotConfigured, bge_embedder


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
