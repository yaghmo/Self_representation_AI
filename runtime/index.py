"""Embeddings over the story corpus, and search across them.

Two levels, because a story and a moment inside it answer different queries.
The summary chunk matches "tell me about the hiking trip"; the event chunks
match "what was the guide wearing". Coarse layer finds the story, fine layer
finds the paragraph — which is also how an amendment finds the line it edits.

The embedder is a parameter rather than an import. `bible.assemble()` already
takes its tokeniser this way, and the reason is the same: it keeps this module
a pure function of its inputs, so the self-check runs with no weights on disk.

The index is derived. `data/stories/*.md` are the truth, and this file can be
deleted and rebuilt at any time. Nothing may live only here.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from runtime.stories import Event, Story, load_all

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = REPO_ROOT / "data" / "index" / "stories.npz"

Embedder = Callable[[list[str]], np.ndarray]


@dataclass
class Chunk:
    key: str
    kind: str  # "summary" | "event"
    story_id: str
    event_id: str
    text: str
    keywords: list[str]

    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Hit:
    chunk: Chunk
    score: float


def chunks_of(story: Story) -> list[Chunk]:
    """One summary chunk, then one chunk per event, in id order."""
    summary = Chunk(
        key=f"{story.id}/summary",
        kind="summary",
        story_id=story.id,
        event_id="",
        text=f"{story.title}. {story.summary}",
        keywords=list(story.keywords),
    )
    events = [
        Chunk(
            key=f"{story.id}/{event.id}",
            kind="event",
            story_id=story.id,
            event_id=event.id,
            text=f"{event.title}. {event.text.strip()}",
            keywords=list(story.keywords),
        )
        for event in story.events
    ]
    return [summary, *events]


def all_chunks(directory: Path | None = None) -> list[Chunk]:
    return [chunk for story in load_all(directory) for chunk in chunks_of(story)]


def _lexical(query: str, chunk: Chunk) -> float:
    """Share of the query's words present in the chunk or its keywords.

    ponytail: token overlap, not BM25. The corpus is hundreds of chunks, where
    IDF weighting is below the noise floor. Swap in BM25 if recall measurably
    disappoints on rare terms.
    """
    words = set(re.findall(r"\w+", query.lower()))
    if not words:
        return 0.0
    haystack = set(re.findall(r"\w+", (chunk.text + " " + " ".join(chunk.keywords)).lower()))
    return len(words & haystack) / len(words)


class Index:
    """Vectors plus their chunks. Not a database — a numpy array and a list.

    ponytail: linear scan. At a few hundred chunks it is microseconds and an
    approximate-nearest-neighbour structure is infrastructure without a
    problem. Move to a real vector store when the corpus reaches five figures.
    """

    def __init__(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        self.chunks = chunks
        self.vectors = vectors

    def search(
        self,
        query: str,
        embed: Embedder,
        limit: int = 5,
        kind: str | None = None,
    ) -> list[Hit]:
        if not self.chunks:
            return []
        wanted = [i for i, c in enumerate(self.chunks) if kind is None or c.kind == kind]
        if not wanted:
            return []
        vector = embed([query])[0]
        dense = self.vectors[wanted] @ vector
        hits = [
            Hit(self.chunks[position], 0.85 * float(dense[row]) + 0.15 * _lexical(query, self.chunks[position]))
            for row, position in enumerate(wanted)
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def refresh(self, chunks: list[Chunk], embed: Embedder) -> int:
        """Re-embed only chunks whose text changed. Returns how many."""
        known = {c.key: (c.digest(), row) for row, c in enumerate(self.chunks)}
        stale = [c for c in chunks if known.get(c.key, ("", -1))[0] != c.digest()]
        if stale:
            fresh = embed([c.text for c in stale])
        else:
            fresh = np.zeros((0, self.vectors.shape[1]), dtype=np.float32)

        # An empty index carries a placeholder width of 1. Taking the width
        # from it would allocate the wrong shape for the first real refresh,
        # so the incoming vectors decide it whenever there are any.
        width = fresh.shape[1] if fresh.size else self.vectors.shape[1]

        by_key = {c.key: row for row, c in enumerate(stale)}
        vectors = np.zeros((len(chunks), width), dtype=np.float32)
        for row, chunk in enumerate(chunks):
            if chunk.key in by_key:
                vectors[row] = fresh[by_key[chunk.key]]
            else:
                vectors[row] = self.vectors[known[chunk.key][1]]

        self.chunks, self.vectors = chunks, vectors
        return len(stale)

    def save(self, path: Path | None = None) -> Path:
        path = path or INDEX_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = json.dumps([c.__dict__ for c in self.chunks])
        np.savez(path, vectors=self.vectors, meta=np.array(meta))
        return path


def build(chunks: list[Chunk], embed: Embedder) -> Index:
    if not chunks:
        return Index([], np.zeros((0, 1), dtype=np.float32))
    return Index(chunks, embed([c.text for c in chunks]))


def load_index(path: Path | None = None) -> Index:
    path = path or INDEX_PATH
    if not path.exists():
        return Index([], np.zeros((0, 1), dtype=np.float32))
    try:
        loaded = np.load(path, allow_pickle=False)
        chunks = [Chunk(**record) for record in json.loads(str(loaded["meta"]))]
        return Index(chunks, loaded["vectors"])
    except (ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile, EOFError):
        # Index file is corrupt or incomplete. Since the index is derived
        # and can be rebuilt, degrade to empty rather than crash. Catches:
        # - zipfile.BadZipFile: truncated writes (most common corruption)
        # - EOFError: empty files
        # - ValueError/KeyError/JSONDecodeError: malformed content
        return Index([], np.zeros((0, 1), dtype=np.float32))


def in_id_order(hits: list[Hit]) -> list[Hit]:
    """Re-order a ranked result set by stable id, for the prompt.

    Ranking is what routing needs; stable order is what the prefix cache
    needs. Sorting by score would reshuffle identical content between turns
    and produce a cache miss on text that never changed.
    """
    return sorted(hits, key=lambda h: (h.chunk.story_id, h.chunk.event_id))


def _self_check() -> None:
    import tempfile

    # A deterministic stand-in for bge-m3: hash each word into a fixed number
    # of buckets. Shares the only properties the index depends on — same text
    # gives the same vector, shared words give a higher cosine — and needs no
    # weights, so this check runs anywhere.
    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, hash(word) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    story = Story(
        id="ST-001",
        title="a weekend hiking trip",
        summary="the guide at the trailhead, the storm, getting back after dark",
        keywords=["hiking", "mountains", "weather"],
        logged="[~early 2026]",
        events=[
            Event("E-001", "meeting the guide", "He was already waiting when we pulled in.\n"),
            Event("E-002", "the storm", "It came in fast on the second afternoon.\n"),
        ],
    )

    chunks = chunks_of(story)
    assert [c.key for c in chunks] == ["ST-001/summary", "ST-001/E-001", "ST-001/E-002"]
    assert chunks[0].kind == "summary" and chunks[1].kind == "event"
    assert chunks[1].event_id == "E-001"

    index = build(chunks, fake_embed)

    # Coarse layer finds the story; fine layer finds the event inside it.
    summaries = index.search("hiking trip storm", fake_embed, kind="summary")
    assert summaries[0].chunk.story_id == "ST-001", summaries[0].chunk.key
    events = index.search("waiting when we pulled in", fake_embed, kind="event")
    assert events[0].chunk.event_id == "E-001", events[0].chunk.key

    # Identical text scores 1.0 (convex blend: 0.85 * dense + 0.15 * lexical, ceiling 1.0).
    # The chunk text for E-002 is "the storm. It came in fast on the second afternoon."
    identical_query = "the storm. It came in fast on the second afternoon."
    same = index.search(identical_query, fake_embed)
    assert same[0].chunk.event_id == "E-002", f"matched wrong chunk: {same[0].chunk.key}"
    assert same[0].score >= 0.99, f"identical text scored {same[0].score}, expected >= 0.99"
    assert same[0].score <= 1.0, f"score {same[0].score} exceeds 1.0"

    # A near-miss: shares most words but is not identical text must score below 0.95.
    # "the storm. It came in fast on the second morning" differs by one word.
    near_miss = index.search("the storm. It came in fast on the second morning.", fake_embed)
    assert near_miss[0].score < 0.95, f"near-miss scored {near_miss[0].score}, expected < 0.95"

    # All scores from search must stay within [0, 1.0].
    all_scores = index.search("hiking", fake_embed, limit=None)
    for hit in all_scores:
        assert 0 <= hit.score <= 1.0, f"score {hit.score} out of bounds"

    # Ranked by score for routing, but re-ordered by stable id for the prompt.
    # Both orderings are needed and they are not the same list.
    shuffled = [Hit(chunks[2], 0.9), Hit(chunks[0], 0.8), Hit(chunks[1], 0.7)]
    assert [h.chunk.key for h in in_id_order(shuffled)] == [
        "ST-001/summary", "ST-001/E-001", "ST-001/E-002"
    ]

    # An amendment re-embeds only what changed. A one-line edit that rebuilt
    # the corpus would make every amendment cost a full pass.
    story.events[0].text = "He was already waiting, red jacket, when we pulled in.\n"
    changed = index.refresh(chunks_of(story), fake_embed)
    assert changed == 1, f"re-embedded {changed} chunks, expected 1"
    assert index.refresh(chunks_of(story), fake_embed) == 0, "re-embedded an unchanged corpus"

    # Refreshing an empty index must take its width from the incoming vectors,
    # not from the placeholder an empty index carries.
    grown = build([], fake_embed)
    assert grown.refresh(chunks_of(story), fake_embed) == 3
    assert grown.vectors.shape == (3, 64), grown.vectors.shape

    with tempfile.TemporaryDirectory() as directory:
        path = index.save(Path(directory) / "stories.npz")
        reloaded = load_index(path)
        assert [c.key for c in reloaded.chunks] == [c.key for c in index.chunks]
        assert np.allclose(reloaded.vectors, index.vectors)

        # A corrupt index file (garbage bytes) must not crash; degrade to empty.
        corrupt_path = Path(directory) / "corrupt.npz"
        corrupt_path.write_bytes(b"not a valid npz file\x00\xff\xfe")
        corrupt = load_index(corrupt_path)
        assert len(corrupt.chunks) == 0, "corrupt index should return empty"
        assert corrupt.vectors.shape == (0, 1), "corrupt index should have empty vector shape"

        # A truncated file (interrupted write mid-save) must not crash; degrade to empty.
        # This is the most common real-world corruption mode.
        truncated_path = Path(directory) / "truncated.npz"
        full_data = path.read_bytes()
        truncated_path.write_bytes(full_data[:len(full_data) // 2])
        truncated = load_index(truncated_path)
        assert len(truncated.chunks) == 0, "truncated index should return empty"
        assert truncated.vectors.shape == (0, 1), "truncated index should have empty vector shape"

    print("index: ok")


if __name__ == "__main__":
    _self_check()
