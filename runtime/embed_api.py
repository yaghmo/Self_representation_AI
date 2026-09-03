"""Gemini text embeddings — the "api" alternative to runtime/embed.py's local
bge_embedder, called directly against Google's Generative Language API.

Two models are available on a free key, each with its own separate daily
quota (confirmed empirically, not just documented): gemini-embedding-001 and
gemini-embedding-2. Only one is wired in as the active default for now — the
model id is a parameter, not hardcoded, so switching to the other (or later,
using both for their separate quotas — one per index, never mixed within one
index's vector space) is a one-line change, not a rewrite.

Batched via batchEmbedContents — one HTTP request embeds many texts, which
matters against the per-model daily request cap. output dimensionality is
truncated (Matryoshka) rather than left at the full 3072, both models support
it identically.
"""

from __future__ import annotations

import os

import httpx
import numpy as np

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-embedding-2"
OUTPUT_DIMENSIONALITY = 768
API_KEY_ENV = "GOOGLE_API_KEY"

# Google's own request-size limit per batchEmbedContents call.
BATCH = 100


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set — api embedding needs a Gemini key")
    return key


def embed(texts: list[str], *, model: str = DEFAULT_MODEL, timeout: float = 60.0) -> np.ndarray:
    """Texts in, L2-normalised float32 vectors out — same contract as
    embed.py's bge_embedder, so the two are drop-in interchangeable behind
    runtime/index.py's Embedder type (which scores with a plain dot product,
    so this only produces a valid cosine similarity if every vector is unit
    length).

    Normalised here explicitly, not trusted from the API: at a truncated
    outputDimensionality, gemini-embedding-2 comes back already unit-length
    but gemini-embedding-001 does not (checked empirically, not documented
    anywhere obvious) — relying on "the API already did it" would silently
    break scoring the moment the model changes.
    """
    if not texts:
        return np.zeros((0, OUTPUT_DIMENSIONALITY), dtype=np.float32)

    vectors: list[list[float]] = []
    with httpx.Client(timeout=timeout) as client:
        for start in range(0, len(texts), BATCH):
            chunk = texts[start : start + BATCH]
            payload = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": text}]},
                        "outputDimensionality": OUTPUT_DIMENSIONALITY,
                    }
                    for text in chunk
                ]
            }
            resp = client.post(
                f"{BASE_URL}/models/{model}:batchEmbedContents",
                params={"key": _api_key()},
                json=payload,
            )
            resp.raise_for_status()
            vectors.extend(e["values"] for e in resp.json()["embeddings"])

    array = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.where(norms == 0, 1, norms)
