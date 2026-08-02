"""The embedder the index actually runs on, loaded from the cookbook's config.

`runtime/index.py` takes its embedder as a parameter so it can be checked with
no weights on disk. This module is the other side of that: it holds the import
of sentence-transformers and the model load, and nothing else depends on it
except the entry points that need a real one.

sentence-transformers is imported inside the function rather than at module
scope. The import pulls torch, which is seconds and hundreds of megabytes, and
anything that only wants the exception type should not pay for it.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STACK_PATH = REPO_ROOT / "config" / "stack.json"
MODELS_DIR = REPO_ROOT / "models"


class EmbeddingNotConfigured(RuntimeError):
    """No embedding model in the stack config, or its weights are absent."""


def bge_embedder(stack_path: Path | None = None):
    """Return an `Embedder`: texts in, L2-normalised float32 vectors out."""
    stack_path = stack_path or STACK_PATH
    if not stack_path.exists():
        raise EmbeddingNotConfigured(
            f"{stack_path} is missing — run the cookbook to fit a stack first."
        )

    config = json.loads(stack_path.read_text(encoding="utf-8"))
    role = config.get("roles", {}).get("embedding")
    if not role or not role.get("model_id"):
        raise EmbeddingNotConfigured(
            "no embedding role in the stack config — run the cookbook and pick "
            "an embedding model before indexing stories."
        )

    weights = MODELS_DIR / role["model_id"]
    if not weights.is_dir():
        raise EmbeddingNotConfigured(
            f"{role['model_id']} is configured but not downloaded. Run: "
            "uv run python -m cookbook.download --from-config"
        )

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingNotConfigured(
            "sentence-transformers is not installed — run `uv sync --extra runtime`"
        ) from exc

    model = SentenceTransformer(str(weights), device=role.get("device", "cpu"))

    def embed(texts: list[str]):
        return model.encode(
            texts,
            normalize_embeddings=True,  # the index scores with a plain dot product
            convert_to_numpy=True,
        ).astype("float32")

    return embed


def _self_check() -> None:
    import tempfile

    # No embedding role configured is the state a fresh machine is in, and it
    # must say so rather than failing somewhere inside a model loader.
    with tempfile.TemporaryDirectory() as raw:
        empty = Path(raw) / "stack.json"
        empty.write_text('{"version": 1, "roles": {}}', encoding="utf-8")
        try:
            bge_embedder(empty)
        except EmbeddingNotConfigured as exc:
            assert "cookbook" in str(exc).lower(), str(exc)
        else:
            raise AssertionError("a missing embedding role was accepted")

        missing = Path(raw) / "nope.json"
        try:
            bge_embedder(missing)
        except EmbeddingNotConfigured:
            pass
        else:
            raise AssertionError("a missing stack.json was accepted")

        # Role configured but weights not on disk — the likeliest failure a user hits.
        # A bogus model_id is guaranteed absent under MODELS_DIR.
        missing_weights = Path(raw) / "with_weights.json"
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

    print("embed: ok")


if __name__ == "__main__":
    _self_check()
