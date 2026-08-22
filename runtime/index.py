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

# Events per chapter. A summary is fixed-size, so it gets lossier as events
# pile up: ST-002's summary still described its first 3 events at 7, and a
# paste about the later ones scored 0.511 against it — under the 0.60 routing
# threshold, though the paragraph it belonged to sat at 0.804 — and got logged
# as a new story instead. Chapters keep the summary-to-content ratio constant.
#
# Counted in events, not tokens — index.py has no tokeniser and shouldn't grow
# one. 4 is small enough to bite before a real story's chapter gets too big.
#
# Chapter membership is derived from the event's own number, not its list
# position, so ids allocated from the max and never reused keep E-005 in
# chapter 2 for the story's life. Only the still-filling chapter re-embeds.
CHAPTER_SIZE = 4


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


def chapter_of(event_id: str) -> int:
    """Which chapter an event belongs to, from its number alone."""
    return (int(event_id.split("-")[1]) - 1) // CHAPTER_SIZE + 1


def _chapters(story: Story) -> list[Chunk]:
    """Coarse chunks for spans of a story one summary can no longer cover.

    Derived from the events' own `title. body` text — deterministic, no model
    call, can't drift from a regenerated summary. Two things measured on the
    misrouted paste that motivated this (needed to clear 0.60):

    - No story-title prefix — identical across chapters, so it flattened
      separation from 0.699/0.062 down to 0.509/0.495 and 0.008.
    - Not titles alone — too little text, scored 0.480, worse than the stale
      summary they were meant to rescue.

    Nothing below CHAPTER_SIZE gets chapters — one chapter over that few
    events would just duplicate the story summary.
    """
    if len(story.events) <= CHAPTER_SIZE:
        return []

    grouped: dict[int, list[Event]] = {}
    for event in story.events:
        grouped.setdefault(chapter_of(event.id), []).append(event)

    return [
        Chunk(
            key=f"{story.id}/C-{number:03d}",
            kind="summary",
            story_id=story.id,
            event_id="",
            text=" ".join(f"{e.title}. {e.text.strip()}" for e in members),
            keywords=list(story.keywords),
        )
        for number, members in sorted(grouped.items())
    ]


def chunks_of(story: Story) -> list[Chunk]:
    """One summary chunk, its chapters, then one chunk per event, in id order.

    Chapters are `kind="summary"` on purpose: they are the coarse layer, and
    `route()` reads `story_id` off whichever coarse chunk wins. So a chapter
    match resolves to its story exactly like a story match, and routing needs
    no idea that chapters exist.
    """
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
    return [summary, *_chapters(story), *events]


def all_chunks(directory: Path | None = None) -> list[Chunk]:
    return [chunk for story in load_all(directory) for chunk in chunks_of(story)]


def _lexical(query: str, chunk: Chunk) -> float:
    """Share of the query's words present in the chunk or its keywords.

    ponytail: token overlap, not BM25 — IDF weighting is noise at hundreds of
    chunks. Swap in BM25 if recall measurably disappoints on rare terms.
    """
    words = set(re.findall(r"\w+", query.lower()))
    if not words:
        return 0.0
    haystack = set(re.findall(r"\w+", (chunk.text + " " + " ".join(chunk.keywords)).lower()))
    return len(words & haystack) / len(words)


class Index:
    """Vectors plus their chunks. Not a database — a numpy array and a list.

    ponytail: linear scan — microseconds at a few hundred chunks. Move to a
    real vector store past five figures.
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
        # Corrupt or incomplete file. The index is derived and rebuildable,
        # so degrade to empty rather than crash.
        return Index([], np.zeros((0, 1), dtype=np.float32))


def in_id_order(hits: list[Hit]) -> list[Hit]:
    """Re-order a ranked result set by stable id, for the prompt.

    Ranking is what routing needs; stable order is what the prefix cache
    needs. Sorting by score would reshuffle identical content between turns
    and produce a cache miss on text that never changed.
    """
    return sorted(hits, key=lambda h: (h.chunk.story_id, h.chunk.event_id))
