"""The embedder the index actually runs on, loaded from the cookbook's config.

`runtime/index.py` takes its embedder as a parameter so it can be checked with
no weights on disk. This module is the other side of that: it holds the model
load, and nothing else depends on it except the entry points that need a real
one.

transformers rather than sentence-transformers, which is what this originally
used. sentence-transformers imports scikit-learn, and torch followed by sklearn
is an access violation on this machine — two copies of the OpenMP runtime in
one process. Since bge-m3's dense vector is just the CLS token normalised (its
own `1_Pooling/config.json` says so), the wrapper was buying a segfault and a
transitive dependency in exchange for four lines.

torch and transformers are imported inside the function, not at module scope:
the import is seconds and hundreds of megabytes, and anything that only wants
the exception type should not pay for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
STACK_PATH = REPO_ROOT / "config" / "stack.json"
MODELS_DIR = REPO_ROOT / "models"

# ponytail: fixed batch, no length-sorted bucketing. The corpus is hundreds of
# chunks embedded once at ingestion — bucketing would save seconds a day.
BATCH = 8


class EmbeddingNotConfigured(RuntimeError):
    """No embedding model in the stack config, or its weights are absent."""


def embedder_from_config(stack_path: Path | None = None):
    """Return an `Embedder` for whichever role is actually configured —
    `bge_embedder()` (local) or Gemini's api one (runtime/embed_api.py),
    picked the same way runtime/voice.py picks between qwentts and
    voice_api.py: by `roles.embedding.source` in config/stack.json.
    """
    stack_path = stack_path or STACK_PATH
    if not stack_path.exists():
        raise EmbeddingNotConfigured(
            f"{stack_path} is missing — run the cookbook to fit a stack first."
        )
    config = json.loads(stack_path.read_text(encoding="utf-8"))
    role = config.get("roles", {}).get("embedding")
    if not role:
        raise EmbeddingNotConfigured(
            "no embedding role in the stack config — run the cookbook and pick "
            "an embedding model before indexing stories."
        )
    if role.get("source") == "api":
        from . import embed_api

        model = role.get("model", embed_api.DEFAULT_MODEL)
        return lambda texts: embed_api.embed(texts, model=model)
    return bge_embedder(stack_path)


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
        # transformers' own lazy-import machinery pulls in pandas, which
        # carries the same OpenMP runtime as torch — import it first or
        # loading torch then transformers is an access violation, the same
        # class of crash the sentence-transformers/sklearn switch above was
        # written to dodge.
        import pandas  # noqa: F401
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise EmbeddingNotConfigured(
            "torch and transformers are not installed — run `uv sync --extra runtime`"
        ) from exc

    # The cookbook's vocabulary is "gpu"/"cpu"; torch's is "cuda"/"cpu". Passed
    # through unmapped, a role fitted onto the GPU dies in `.to("gpu")` with a
    # torch error naming every device except the one that was asked for.
    device = {"gpu": "cuda"}.get(role.get("device", "cpu"), role.get("device", "cpu"))
    tokenizer = AutoTokenizer.from_pretrained(str(weights))
    model = AutoModel.from_pretrained(str(weights)).to(device).eval()

    # The model's own config, not a constant here: bge-m3 takes 8192, and a
    # number copied into this file would silently truncate a longer one.
    config = weights / "sentence_bert_config.json"
    max_length = 512
    if config.exists():
        max_length = json.loads(config.read_text(encoding="utf-8")).get("max_seq_length", 512)

    def embed(texts: list[str]):
        vectors = []
        for start in range(0, len(texts), BATCH):
            batch = tokenizer(
                texts[start : start + BATCH],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            ).to(device)
            with torch.inference_mode():
                # CLS token, per the model's 1_Pooling/config.json. Normalised
                # because the index scores with a plain dot product.
                hidden = model(**batch).last_hidden_state[:, 0]
                vectors.append(
                    torch.nn.functional.normalize(hidden, p=2, dim=1).cpu().numpy()
                )
        if not vectors:
            return np.zeros((0, model.config.hidden_size), dtype=np.float32)
        return np.concatenate(vectors).astype(np.float32)

    return embed
