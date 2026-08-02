# `/story` Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the creator a `/story` command that ingests narrative material into a mutable story corpus, routes a later detail to the story it amends, and keeps a rebuildable embedding index over it.

**Architecture:** Three new modules under `runtime/`, following the shape the existing ones already use. `stories.py` is pure text — parse and render story files, allocate stable ids, nothing else. `index.py` embeds and searches, with the embedder injected as a callable so it runs in a self-check without model weights, exactly as `bible.assemble()` injects its tokeniser. `story_tools.py` composes the two into proposals, reusing the `Proposal` / `snapshot` machinery in `tools.py` so every story write lands behind the same confirm gate and the same undo as a bible write.

**Tech Stack:** Python 3.10, numpy, sentence-transformers (bge-m3) for the real embedder, markitdown for file conversion, Streamlit for the admin surface.

**Source spec:** `docs/superpowers/specs/2026-08-02-story-ingestion-design.md`

## Global Constraints

- Python is pinned `>=3.10,<3.11`. No syntax past 3.10.
- Every module carries `_self_check()` and ends with `if __name__ == "__main__": _self_check()`. This repo has no pytest suite and does not want one — that is the established test cycle and every runtime module follows it.
- Self-checks must run with **no model weights and no network**. Inject a fake embedder.
- `ST-###` and `E-###` ids are assigned once and **never reused or renumbered**. The fan-side prompt layout orders retrieved chunks by stable id so identical content serialises to identical bytes and the KV prefix cache survives; renumbering silently destroys that.
- Similarity is cosine on the dense vector. `DUPLICATE_THRESHOLD = 0.95`, `AMENDMENT_THRESHOLD = 0.60`, both defined once in `story_tools.py` and imported anywhere else they are needed.
- Every write goes through a `Proposal`. An agent may compose an edit, never land one.
- Every write is preceded by a snapshot into `data/.backups/`.
- Redaction happens **at ingestion, before the write**, never as a later cleanup pass.
- `data/` is gitignored wholesale (`.gitignore:43`), so `data/stories/` and `data/index/` need no new ignore rules. Do not add any.
- Never put creator material in a tracked file. Examples in code, comments, and docstrings are synthetic.
- `/story` never modifies `data/character.md`. That is `/add`'s job.

**Run the test cycle with:**

```bash
export PYTHONPATH=$(pwd) PYTHONIOENCODING=utf-8
./.venv/Scripts/python.exe -m runtime.<module>
```

Exit code 0 and no assertion error is a pass.

---

### Task 1: Story file format

Pure text in, pure text out. No embeddings, no filesystem beyond reading and writing one file.

**Files:**
- Create: `runtime/stories.py`
- Test: `runtime/stories.py::_self_check` (in-module, per repo convention)

**Interfaces:**
- Consumes: nothing. This is the base layer.
- Produces:
  - `STORIES_DIR: Path` — `data/stories`
  - `@dataclass Event(id: str, title: str, text: str)`
  - `@dataclass Story(id: str, title: str, summary: str, keywords: list[str], logged: str, events: list[Event])`
  - `parse_story(text: str) -> Story`
  - `render_story(story: Story) -> str`
  - `load_story(path: Path) -> Story`
  - `load_all(directory: Path | None = None) -> list[Story]`
  - `next_story_id(existing: list[str]) -> str`
  - `next_event_id(story: Story) -> str`
  - `MalformedStory(ValueError)`

- [ ] **Step 1: Write the failing self-check**

Create `runtime/stories.py` containing only the imports and this function, so the first run fails on the missing names:

```python
def _self_check() -> None:
    text = (
        "# ST-001 — a weekend hiking trip\n"
        "**Summary:** the guide at the trailhead, the storm, getting back after dark\n"
        "**Keywords:** hiking, mountains, weather\n"
        "**Logged:** [~early 2026]\n"
        "\n"
        "## E-001 — meeting the guide\n"
        "He was already waiting when we pulled in.\n"
        "\n"
        "## E-002 — the storm\n"
        "It came in fast on the second afternoon.\n"
    )

    story = parse_story(text)
    assert story.id == "ST-001", story.id
    assert story.title == "a weekend hiking trip", story.title
    assert story.keywords == ["hiking", "mountains", "weather"], story.keywords
    assert story.logged == "[~early 2026]", story.logged
    assert [e.id for e in story.events] == ["E-001", "E-002"]
    assert story.events[1].title == "the storm"
    assert story.events[0].text.strip() == "He was already waiting when we pulled in."

    # Round-trip is exact. The index is derived from these files, so a render
    # that reflows text would silently re-embed chunks that never changed.
    assert render_story(story) == text, "round-trip changed the file"

    # Amending an event edits its text and leaves every id alone. Renumbering
    # would break stable-id ordering, and with it the KV prefix cache.
    story.events[0].text = "He was already waiting, red jacket, when we pulled in.\n"
    amended = parse_story(render_story(story))
    assert [e.id for e in amended.events] == ["E-001", "E-002"], "ids moved"
    assert "red jacket" in amended.events[0].text

    # Ids are allocated from the maximum, never from the count — a deleted
    # event must not free its number for reuse.
    assert next_story_id(["ST-001", "ST-004"]) == "ST-005"
    assert next_story_id([]) == "ST-001"
    assert next_event_id(story) == "E-003"

    malformed = "no heading here\n"
    try:
        parse_story(malformed)
    except MalformedStory:
        pass
    else:
        raise AssertionError("malformed story was accepted")

    print("stories: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m runtime.stories`
Expected: `NameError: name 'parse_story' is not defined`

- [ ] **Step 3: Implement the module**

Insert above `_self_check`:

```python
"""The story corpus: parse, render, and allocate ids.

A story is narrative material the creator writes down whole — a day, an
event, a story about the character. It is a third corpus, neither the
append-only source log nor the cited profile derived from it.

Story text is mutable by design: an amendment edits the story in place rather
than appending a note beside it, so that a retrieved chunk reads as one
coherent paragraph. What is never mutable is an id. `ST-###` and `E-###` are
assigned once and survive every edit, because retrieved chunks are ordered by
id so that unchanged content serialises to identical bytes and the model
server's prefix cache survives between turns.

This module is pure text. Embeddings live in `runtime/index.py` and writes go
through `runtime/story_tools.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STORIES_DIR = REPO_ROOT / "data" / "stories"

TITLE = re.compile(r"^# (ST-\d+) — (.+)$", re.MULTILINE)
EVENT = re.compile(r"^## (E-\d+) — (.+)$", re.MULTILINE)
FIELD = re.compile(r"^\*\*(Summary|Keywords|Logged):\*\* (.*)$", re.MULTILINE)


class MalformedStory(ValueError):
    """The file is not a story. Reported rather than guessed at."""


@dataclass
class Event:
    id: str
    title: str
    text: str


@dataclass
class Story:
    id: str
    title: str
    summary: str
    keywords: list[str] = field(default_factory=list)
    logged: str = ""
    events: list[Event] = field(default_factory=list)


def parse_story(text: str) -> Story:
    heading = TITLE.search(text)
    if heading is None:
        raise MalformedStory("no '# ST-### — title' heading found")

    fields = {name: value.strip() for name, value in FIELD.findall(text)}
    keywords = [k.strip() for k in fields.get("Keywords", "").split(",") if k.strip()]

    events: list[Event] = []
    marks = list(EVENT.finditer(text))
    for position, mark in enumerate(marks):
        end = marks[position + 1].start() if position + 1 < len(marks) else len(text)
        events.append(Event(id=mark.group(1), title=mark.group(2).strip(),
                            text=text[mark.end():end].lstrip("\n")))

    return Story(
        id=heading.group(1),
        title=heading.group(2).strip(),
        summary=fields.get("Summary", ""),
        keywords=keywords,
        logged=fields.get("Logged", ""),
        events=events,
    )


def render_story(story: Story) -> str:
    parts = [
        f"# {story.id} — {story.title}\n",
        f"**Summary:** {story.summary}\n",
        f"**Keywords:** {', '.join(story.keywords)}\n",
        f"**Logged:** {story.logged}\n",
    ]
    for event in story.events:
        parts.append(f"\n## {event.id} — {event.title}\n")
        parts.append(event.text if event.text.endswith("\n") else event.text + "\n")
    return "".join(parts)


def load_story(path: Path) -> Story:
    return parse_story(path.read_text(encoding="utf-8"))


def load_all(directory: Path | None = None) -> list[Story]:
    directory = directory or STORIES_DIR
    if not directory.is_dir():
        return []
    return [load_story(p) for p in sorted(directory.glob("ST-*.md"))]


def _next(ids: list[str], prefix: str) -> str:
    # From the maximum, never the count: a deleted id must not be handed out
    # again to different content the index may still hold a vector for.
    numbers = [int(i.split("-")[1]) for i in ids if i.startswith(f"{prefix}-")]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def next_story_id(existing: list[str]) -> str:
    return _next(existing, "ST")


def next_event_id(story: Story) -> str:
    return _next([e.id for e in story.events], "E")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m runtime.stories`
Expected: `stories: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/stories.py
git commit -m "feat: the story file format, with ids that never move"
```

---

### Task 2: Hoist the redaction policy

Documentation and template work. No code. Do this before Task 5, which reads the policy file by path.

**Files:**
- Create: `templates/redaction-policy.template.md`
- Create: `data/redaction-policy.md` (hand-copied from the live table — **not** generated from the template)
- Modify: `data/sources.md` — replace the `## Redaction policy` table with a pointer
- Modify: `templates/sources.template.md` — same change, so new instances get the new shape
- Modify: `CLAUDE.md:` the `### The table above is only the default` section
- Modify: `.claude/skills/add/SKILL.md` — step 5 and Test 4 reference the policy location

**Interfaces:**
- Consumes: nothing.
- Produces: `data/redaction-policy.md` exists and holds the live policy table. Task 5 reads it from `REPO_ROOT / "data" / "redaction-policy.md"`.

- [ ] **Step 1: Write the template**

Create `templates/redaction-policy.template.md`:

```markdown
# Redaction policy

One policy, every corpus. `sources.md`, `stories/`, and anything added later
all obey this table. Change it here and the change applies everywhere.

**Reduce at ingestion, never as a later cleanup pass.** Every corpus is
reachable by the bot, so anything exact written into one can be surfaced to
the public. A bracketed value is always a fuzzed replacement, never an
original — never write the precise value anywhere in the repo, including in
ignored files.

Only the creator may loosen a row, and the approval is recorded here with a
date. Tightening needs no approval. Unset or unclear means the conservative
default. Where the policy is genuinely unclear for a specific detail, ask —
do not guess at how much to blur.

| Category | Default | This instance | Approved by / when |
|---|---|---|---|
| Dates | fuzz to period — `[~mid-July]`, `[~2023]` | default | — |
| Locations | city level; no address, venue, or neighbourhood | default | — |
| School / employer names | generalised — "their university" | default | — |
| Third-party full names | first name only, or "a friend" | default | — |
| Contact details, handles, booking or flight numbers | omit entirely, always | default | — |
| Age | approximate, not tied to an exact year | default | — |
| Family details | generalised; no names | default | — |
| Health / medical | omit unless the creator explicitly opts in | default | — |
```

- [ ] **Step 2: Create the live policy file by hand**

Copy `data/sources.md`'s existing `## Redaction policy` table — **including any
rows the creator has already loosened and their approval dates** — into
`data/redaction-policy.md`, under the template's preamble.

CLAUDE.md forbids regenerating `data/` from templates: the creator's overrides
are unrecoverable, since `data/` is not in git. Read the live table first and
carry every row across verbatim.

- [ ] **Step 3: Point the old locations at the new file**

In `data/sources.md` and `templates/sources.template.md`, replace the policy
table with:

```markdown
## Redaction policy

Moved to `data/redaction-policy.md`. One policy governs every corpus — this
file, the story corpus, and anything added later.
```

- [ ] **Step 4: Update CLAUDE.md and the /add skill**

In `CLAUDE.md`, the `### The table above is only the default` section currently
says the live policy lives in the `## Redaction policy` table in
`data/sources.md`. Change that to `data/redaction-policy.md`, and note that it
governs every corpus.

In `.claude/skills/add/SKILL.md`, update the references in step 5 ("Redact on
the way in") and Test 4 to the new path.

- [ ] **Step 5: Verify nothing still points at the old location**

Run: `grep -rn "Redaction policy" --include="*.md" . | grep -v graphify-out`
Expected: hits only in `redaction-policy.md`, the two pointer stubs, `CLAUDE.md`, and the `/add` skill — none claiming the table lives in `sources.md`.

- [ ] **Step 6: Commit**

```bash
git add templates/redaction-policy.template.md templates/sources.template.md CLAUDE.md .claude/skills/add/SKILL.md
git commit -m "docs: one redaction policy, in its own file, for every corpus"
```

`data/` is gitignored — `data/redaction-policy.md` and the edit to
`data/sources.md` are correctly left out of this commit.

---

### Task 3: The index

Embeddings and search. The embedder is a parameter, never imported, so this
runs in a self-check with no weights on disk.

**Files:**
- Create: `runtime/index.py`
- Modify: `pyproject.toml:18-22` — add `numpy>=1.24` to the `runtime` extra
- Test: `runtime/index.py::_self_check`

**Interfaces:**
- Consumes: `runtime.stories.Story`, `runtime.stories.Event`, `runtime.stories.load_all`
- Produces:
  - `INDEX_PATH: Path` — `data/index/stories.npz`
  - `Embedder = Callable[[list[str]], "np.ndarray"]` returning `(n, d)` float32, L2-normalised
  - `@dataclass Chunk(key: str, kind: str, story_id: str, event_id: str, text: str, keywords: list[str])`
  - `@dataclass Hit(chunk: Chunk, score: float)`
  - `chunks_of(story: Story) -> list[Chunk]`
  - `build(chunks: list[Chunk], embed: Embedder) -> Index`
  - `Index.search(query: str, embed: Embedder, limit: int = 5, kind: str | None = None) -> list[Hit]`
  - `Index.refresh(chunks: list[Chunk], embed: Embedder) -> int` — returns how many were re-embedded
  - `Index.save(path: Path | None = None) -> Path` / `load_index(path: Path | None = None) -> Index`
  - `in_id_order(hits: list[Hit]) -> list[Hit]`

- [ ] **Step 1: Add numpy to the runtime extra**

In `pyproject.toml`, the `runtime` optional-dependency group becomes:

```toml
runtime = [
    "torch>=2.5",
    "transformers>=4.45",
    "sentence-transformers>=3.2",
    "numpy>=1.24",
]
```

numpy already arrives transitively through torch. Naming it is one line, and
it stops a future dependency change from removing it silently.

- [ ] **Step 2: Write the failing self-check**

Create `runtime/index.py` with imports and this function only:

```python
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

    # Identical text scores ~1.0. This is what the duplicate threshold reads.
    same = index.search("It came in fast on the second afternoon.", fake_embed)
    assert same[0].score > 0.95, same[0].score

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

    print("index: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 3: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m runtime.index`
Expected: `NameError: name 'chunks_of' is not defined`

- [ ] **Step 4: Implement the module**

Insert above `_self_check`:

```python
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
            Hit(self.chunks[position], float(dense[row]) + 0.15 * _lexical(query, self.chunks[position]))
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
    loaded = np.load(path, allow_pickle=False)
    chunks = [Chunk(**record) for record in json.loads(str(loaded["meta"]))]
    return Index(chunks, loaded["vectors"])


def in_id_order(hits: list[Hit]) -> list[Hit]:
    """Re-order a ranked result set by stable id, for the prompt.

    Ranking is what routing needs; stable order is what the prefix cache
    needs. Sorting by score would reshuffle identical content between turns
    and produce a cache miss on text that never changed.
    """
    return sorted(hits, key=lambda h: (h.chunk.story_id, h.chunk.event_id))
```

- [ ] **Step 5: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m runtime.index`
Expected: `index: ok`

- [ ] **Step 6: Commit**

```bash
git add runtime/index.py pyproject.toml
git commit -m "feat: a two-level index over the story corpus, embedder injected"
```

---

### Task 3b: The real embedder

Task 3 takes its embedder as a parameter, which is what makes it testable. This
is the one that carries weights, and the only reason it is a separate file is
that it cannot run in a self-check without them.

**Files:**
- Create: `runtime/embed.py`
- Test: `runtime/embed.py::_self_check`

**Interfaces:**
- Consumes: `config/stack.json` — `roles.embedding.model_id`, written by the cookbook.
- Produces: `bge_embedder() -> Embedder`, `EmbeddingNotConfigured(RuntimeError)`. `bge_embedder()` returns the callable Task 3 and Task 5 take as `embed`, and is what Task 7 imports as `_embed`.

- [ ] **Step 1: Write the failing self-check**

```python
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

    print("embed: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m runtime.embed`
Expected: `NameError: name 'bge_embedder' is not defined`

- [ ] **Step 3: Implement the module**

```python
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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m runtime.embed`
Expected: `embed: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/embed.py
git commit -m "feat: the bge-m3 embedder, loaded from the stack the cookbook wrote"
```

> **Note for Task 7:** `config/stack.json` currently has `"roles": {}`. Until
> the cookbook is re-run with an embedding model selected, `bge_embedder()`
> raises `EmbeddingNotConfigured` with the exact command to fix it. That is the
> correct behaviour, not a bug to work around — do not fall back to a fake
> embedder in the app.

---

### Task 4: Let stories be restored

`list_backups()` and `restore_backup()` currently hard-restrict to the two
bible filenames. That restriction is a security guard, not an oversight — the
restore path is the one place a whole file is overwritten, so the destination
is checked rather than trusted. Stories need the same guard widened, not
removed.

**Files:**
- Modify: `runtime/tools.py:107-147`
- Test: `runtime/tools.py::_self_check`

**Interfaces:**
- Consumes: `runtime.stories.STORIES_DIR`
- Produces: `list_backups()` and `restore_backup()` accept `ST-###.md` names alongside the two bible files.

- [ ] **Step 1: Add the failing assertions**

Append to `runtime/tools.py::_self_check`, inside the existing
`tempfile.TemporaryDirectory()` block:

```python
    # Story snapshots are restorable too. Without this, /story writes get a
    # snapshot taken and no way to roll it back — an undo that cannot be run.
    story_file = Path(directory) / "ST-001.md"
    story_file.write_text("# ST-001 — a trip\n", encoding="utf-8")
    snapshot(story_file)
    names = [b.name for b in list_backups(Path(directory))]
    assert any(n.startswith("ST-001.md.") for n in names), names

    # The guard still refuses anything that is not a corpus file. This is the
    # one path that overwrites a whole file by name.
    stray = Path(directory) / BACKUP_DIR / "passwd.20260101T000000"
    stray.write_text("x", encoding="utf-8")
    try:
        restore_backup(stray, Path(directory))
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a non-corpus name")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m runtime.tools`
Expected: `AssertionError` on the `ST-001.md.` assertion — `list_backups` filtered it out.

- [ ] **Step 3: Widen the guard**

Replace the `restorable` line in `list_backups` (currently `runtime/tools.py:118`) and the name check in `restore_backup` (currently `:140-141`) with a shared predicate. Add above `list_backups`:

```python
STORY_NAME = re.compile(r"^ST-\d+\.md$")


def _is_corpus_file(name: str) -> bool:
    """Names a restore is allowed to write to.

    Restore overwrites a whole file, so the destination is checked rather than
    trusted — a crafted snapshot name would otherwise choose where it lands.
    """
    return name in {SOURCES_PATH.name, PROFILE_PATH.name} or bool(STORY_NAME.match(name))
```

In `list_backups`, replace the `restorable` set and its use with:

```python
    found = [p for p in backups.iterdir() if p.is_file() and _is_corpus_file(_restore_target_name(p))]
```

In `restore_backup`, replace the membership test with:

```python
    if not _is_corpus_file(name):
        raise ValueError(f"{backup.name!r} is not a snapshot of a corpus file")
```

- [ ] **Step 4: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m runtime.tools`
Expected: the existing `tools: ok` line, with no assertion error.

- [ ] **Step 5: Commit**

```bash
git add runtime/tools.py
git commit -m "fix: stories get the same restore path the bible files have"
```

---

### Task 5: Routing and proposals

Where `/story` decides between amending and creating, and turns either into a
`Proposal` the confirm gate can show.

**Files:**
- Create: `runtime/story_tools.py`
- Test: `runtime/story_tools.py::_self_check`

**Interfaces:**
- Consumes: `runtime.stories` (all of Task 1), `runtime.index` (all of Task 3), `runtime.tools._propose`, `runtime.tools.Proposal`
- Produces:
  - `DUPLICATE_THRESHOLD = 0.95`, `AMENDMENT_THRESHOLD = 0.60`
  - `POLICY_PATH: Path` — `data/redaction-policy.md`
  - `@dataclass Routing(branch: str, story: Story | None, event_id: str, runners_up: list[Hit])` where `branch` is `"duplicate" | "amend" | "new"`
  - `route(text: str, index: Index, embed: Embedder, directory: Path | None = None) -> Routing`
  - `propose_new_story(summary, keywords, logged, events, directory=None) -> Proposal`
  - `propose_amendment(story, event_id, new_text, directory=None) -> Proposal`
  - `read_policy(path: Path | None = None) -> str`

- [ ] **Step 1: Write the failing self-check**

Create `runtime/story_tools.py` with imports and this function only:

```python
def _self_check() -> None:
    import tempfile

    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, hash(word) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        existing = Story(
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
        (directory / "ST-001.md").write_text(render_story(existing), encoding="utf-8")
        index = build(all_chunks(directory), fake_embed)

        # A detail naming its target only by allusion routes to the story it
        # belongs to, and to the event inside it. This is the case the whole
        # design exists for.
        routing = route(
            "the guide at the trailhead was wearing a red jacket",
            index, fake_embed, directory,
        )
        assert routing.branch == "amend", routing.branch
        assert routing.story is not None and routing.story.id == "ST-001"
        assert routing.event_id == "E-001", routing.event_id

        # Unrelated material is a new story, not a forced amendment.
        fresh = route(
            "a quiet afternoon rearranging every shelf in the kitchen",
            index, fake_embed, directory,
        )
        assert fresh.branch == "new", fresh.branch
        assert fresh.story is None

        # The same text pasted twice is refused, and the refusal names what it
        # duplicates so the creator can tell it apart from a rejection.
        again = route("It came in fast on the second afternoon.", index, fake_embed, directory)
        assert again.branch == "duplicate", again.branch
        assert again.runners_up and again.runners_up[0].chunk.story_id == "ST-001"

        # Amending composes a Proposal, never a write. Nothing lands until the
        # creator approves it at the gate.
        proposal = propose_amendment(
            existing, "E-001",
            "He was already waiting, red jacket, when we pulled in.\n",
            directory,
        )
        assert "red jacket" in proposal.new_text
        assert "ST-001" in proposal.summary
        on_disk = (directory / "ST-001.md").read_text(encoding="utf-8")
        assert "red jacket" not in on_disk, "proposal wrote to disk before approval"

        proposal.apply()
        after = parse_story((directory / "ST-001.md").read_text(encoding="utf-8"))
        assert "red jacket" in after.events[0].text
        assert [e.id for e in after.events] == ["E-001", "E-002"], "ids moved on amend"
        assert (directory / ".backups").is_dir(), "no snapshot taken before the write"

        # A new story takes the next free id and lands as its own file.
        created = propose_new_story(
            summary="rearranging every shelf in the kitchen",
            keywords=["home", "cleaning"],
            logged="[~early 2026]",
            events=[("an afternoon of it", "It took longer than it should have.\n")],
            directory=directory,
        )
        assert created.path.name == "ST-002.md", created.path.name
        created.apply()
        made = parse_story((directory / "ST-002.md").read_text(encoding="utf-8"))
        assert made.id == "ST-002" and made.events[0].id == "E-001"

    print("story_tools: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m runtime.story_tools`
Expected: `NameError: name 'route' is not defined`

- [ ] **Step 3: Implement the module**

Insert above `_self_check`:

```python
"""`/story`: route incoming narrative, and compose the write it implies.

Three branches, decided by retrieval rather than by a flag the creator has to
remember. Material that matches nothing becomes a new story; material that
matches an existing one becomes an amendment to it; material that matches
almost exactly is refused as a duplicate.

Every branch produces a `Proposal`, never a write. The confirm gate names the
branch it took and the story it picked, with the runners-up beside it, so a
misroute costs one rejection. That matters more here than in the bible tools:
story text is mutable, so a wrong edit target overwrites the creator's own
words rather than adding a line beside them.

Thresholds are starting values to be tuned against a real corpus. Both can be
wrong without causing damage, because nothing is written until a human looks
at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from runtime.index import Embedder, Hit, Index, all_chunks, build
from runtime.stories import (
    STORIES_DIR,
    Event,
    Story,
    load_all,
    load_story,
    next_event_id,
    next_story_id,
    parse_story,
    render_story,
)
from runtime.tools import Proposal, _propose

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO_ROOT / "data" / "redaction-policy.md"

DUPLICATE_THRESHOLD = 0.95
AMENDMENT_THRESHOLD = 0.60


@dataclass
class Routing:
    branch: str  # "duplicate" | "amend" | "new"
    story: Story | None = None
    event_id: str = ""
    runners_up: list[Hit] = field(default_factory=list)


def read_policy(path: Path | None = None) -> str:
    """The redaction policy, read before anything is written.

    One policy governs every corpus. Reduction happens on the way in: this
    corpus is reachable by the fan-facing bot, so anything exact written here
    can be surfaced to the public, and deleting it later does not unpublish it.
    """
    path = path or POLICY_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. The redaction policy governs every corpus and "
            "is read before any ingestion — restore it before logging anything."
        )
    return path.read_text(encoding="utf-8")


def route(
    text: str,
    index: Index,
    embed: Embedder,
    directory: Path | None = None,
) -> Routing:
    directory = directory or STORIES_DIR
    everything = index.search(text, embed, limit=5)
    if not everything:
        return Routing(branch="new")

    if everything[0].score >= DUPLICATE_THRESHOLD:
        return Routing(branch="duplicate", runners_up=everything)

    summaries = index.search(text, embed, limit=3, kind="summary")
    if not summaries or summaries[0].score < AMENDMENT_THRESHOLD:
        return Routing(branch="new", runners_up=summaries)

    target = summaries[0].chunk.story_id
    story = load_story(directory / f"{target}.md")

    # Coarse layer picked the story; fine layer picks the paragraph inside it.
    events = [h for h in index.search(text, embed, limit=8, kind="event")
              if h.chunk.story_id == target]
    event_id = events[0].chunk.event_id if events else (
        story.events[-1].id if story.events else ""
    )
    return Routing(branch="amend", story=story, event_id=event_id, runners_up=summaries[1:])


def propose_amendment(
    story: Story,
    event_id: str,
    new_text: str,
    directory: Path | None = None,
) -> Proposal:
    directory = directory or STORIES_DIR
    path = directory / f"{story.id}.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""

    target = next((e for e in story.events if e.id == event_id), None)
    if target is None:
        raise ValueError(
            f"{story.id} has no {event_id}. Events present: "
            f"{', '.join(e.id for e in story.events) or 'none'}"
        )

    before = target.text
    amended = parse_story(old) if old else story
    for event in amended.events:
        if event.id == event_id:
            event.text = new_text if new_text.endswith("\n") else new_text + "\n"

    return _propose(
        path=path,
        old=old,
        new=render_story(amended),
        summary=f"amend {story.id}/{event_id} — {target.title}",
        before=before,
        after=new_text,
    )


def propose_new_story(
    summary: str,
    keywords: list[str],
    logged: str,
    events: list[tuple[str, str]],
    directory: Path | None = None,
) -> Proposal:
    """`events` is a list of (title, body) pairs, already segmented and redacted."""
    directory = directory or STORIES_DIR
    story_id = next_story_id([s.id for s in load_all(directory)])
    story = Story(
        id=story_id,
        title=summary.split(",")[0].strip() or "an untitled story",
        summary=summary,
        keywords=list(keywords),
        logged=logged,
        events=[],
    )
    for title, body in events:
        story.events.append(Event(id=next_event_id(story), title=title, text=body))

    path = directory / f"{story_id}.md"
    return _propose(
        path=path,
        old="",
        new=render_story(story),
        summary=f"new story {story_id} — {story.title} ({len(story.events)} events)",
        before="",
        after=render_story(story),
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m runtime.story_tools`
Expected: `story_tools: ok`

- [ ] **Step 5: Run every other self-check, to confirm nothing regressed**

Run:

```bash
for m in runtime.bible runtime.tools runtime.agent runtime.backend runtime.model \
         runtime.llamacpp runtime.stories runtime.index runtime.embed runtime.story_tools; do
  printf "%-22s " "$m"; ./.venv/Scripts/python.exe -m $m >/dev/null 2>&1 && echo OK || echo FAIL
done
```

Expected: ten `OK` lines.

- [ ] **Step 6: Commit**

```bash
git add runtime/story_tools.py
git commit -m "feat: route a story to new, amend, or duplicate — the gate decides"
```

---

### Task 6: File conversion

`/story` accepts an attached document, not only pasted text.

**Files:**
- Create: `runtime/convert.py`
- Modify: `pyproject.toml:18-23` — add `markitdown>=0.0.1` to the `runtime` extra
- Test: `runtime/convert.py::_self_check`

**Interfaces:**
- Consumes: nothing.
- Produces: `to_markdown(path: Path) -> str`, `ConversionFailed(RuntimeError)`

- [ ] **Step 1: Write the failing self-check**

Create `runtime/convert.py` with imports and:

```python
def _self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)

        # Markdown and plain text pass through untouched. Running them through
        # a converter would reflow the creator's own line breaks, and phrasing
        # is the voice data this whole project exists to keep.
        source = directory / "note.md"
        source.write_text("# a day\n\nIt rained.\n", encoding="utf-8")
        assert to_markdown(source) == "# a day\n\nIt rained.\n"

        # A failed conversion stops. A partial document silently ingested is
        # a corpus with a hole in it that nothing will ever report.
        broken = directory / "broken.docx"
        broken.write_bytes(b"not really a docx")
        try:
            to_markdown(broken)
        except ConversionFailed:
            pass
        else:
            raise AssertionError("a broken file was converted anyway")

        missing = directory / "nope.pdf"
        try:
            to_markdown(missing)
        except ConversionFailed:
            pass
        else:
            raise AssertionError("a missing file was converted anyway")

    print("convert: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/Scripts/python.exe -m runtime.convert`
Expected: `NameError: name 'to_markdown' is not defined`

- [ ] **Step 3: Implement the module**

```python
"""Documents to markdown, so `/story` can take a file as well as a paste.

Documents only, never media. markitdown handles the office and PDF formats;
markdown and plain text are passed through rather than round-tripped, because
a converter would reflow line breaks that are part of the creator's phrasing.
"""

from __future__ import annotations

from pathlib import Path

PASSTHROUGH = {".md", ".markdown", ".txt"}


class ConversionFailed(RuntimeError):
    """The file could not be converted. Never ingest a partial conversion."""


def to_markdown(path: Path) -> str:
    if not path.is_file():
        raise ConversionFailed(f"{path.name} does not exist")
    if path.suffix.lower() in PASSTHROUGH:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConversionFailed(f"{path.name} could not be read: {exc}") from exc

    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise ConversionFailed(
            "markitdown is not installed — run `uv sync --extra runtime`"
        ) from exc

    try:
        result = MarkItDown().convert(str(path))
    except Exception as exc:  # markitdown raises per-format exceptions
        raise ConversionFailed(f"{path.name} could not be converted: {exc}") from exc

    text = getattr(result, "text_content", "") or ""
    if not text.strip():
        raise ConversionFailed(f"{path.name} converted to nothing — is it a document?")
    return text
```

- [ ] **Step 4: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m runtime.convert`
Expected: `convert: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/convert.py pyproject.toml
git commit -m "feat: documents in, markdown out, and a hard stop on partials"
```

---

### Task 7: Wire `/story` into the admin page

The creator-facing half. Everything before this is callable; nothing is
reachable.

**Files:**
- Modify: `runtime/chat_app.py` — imports at `:24-35`, the input handling near `:269-290`, and the confirm dialog at `:65`
- Test: manual, in the running app

**Interfaces:**
- Consumes: `runtime.story_tools.route`, `propose_new_story`, `propose_amendment`, `read_policy`; `runtime.index.load_index`, `build`, `all_chunks`, `in_id_order`; `runtime.embed.bge_embedder`, `EmbeddingNotConfigured`; `runtime.convert.to_markdown`
- Produces: nothing further consumes this.

- [ ] **Step 1: Load the embedder and the index once per session**

The index is derived and small. Rebuild it if the file is missing rather than
failing — `data/stories/*.md` are the truth and the index follows them.

A missing embedding role is reported, not worked around. Indexing with a
stand-in would write vectors that no real query can ever match, and the corpus
would look indexed while retrieving nothing.

```python
if "story_embed" not in st.session_state:
    try:
        st.session_state["story_embed"] = bge_embedder()
    except EmbeddingNotConfigured as exc:
        st.session_state["story_embed"] = None
        st.session_state["story_error"] = str(exc)

_embed = st.session_state["story_embed"]

if _embed is not None and "story_index" not in st.session_state:
    index = load_index()
    if not index.chunks:
        index = build(all_chunks(), _embed)
    st.session_state["story_index"] = index
```

`/story` is disabled with `st.session_state["story_error"]` shown when `_embed`
is `None`. The rest of the admin page is unaffected — the bible tools do not
use embeddings.

- [ ] **Step 2: Route the input and show the branch**

The gate must state the branch in words, with the runners-up beside it. A
misroute the creator cannot see is a misroute they cannot reject.

```python
routing = route(story_text, st.session_state["story_index"], _embed)

if routing.branch == "duplicate":
    st.warning(
        f"Already logged — this is {routing.runners_up[0].score:.0%} similar to "
        f"{routing.runners_up[0].chunk.key}. Nothing ingested."
    )
elif routing.branch == "amend":
    st.info(f"Amending {routing.story.id}/{routing.event_id} — {routing.story.title}")
    if routing.runners_up:
        st.caption(
            "Other candidates: "
            + ", ".join(f"{h.chunk.story_id} ({h.score:.2f})" for h in routing.runners_up)
        )
else:
    st.info("New story — nothing in the corpus matches this closely.")
```

- [ ] **Step 3: The redaction and segmentation pass**

Nothing so far produces the summary, keywords, and event split that
`propose_new_story` takes, and nothing has applied the redaction policy. Both
are one bounded model call — not the agent loop, which exists for open-ended
tool use and would spend turns on a fixed transform. It runs after routing,
because the branch decides the shape of what comes back.

The policy is read fresh on every ingestion rather than cached at startup, so
a creator who loosens a row sees it take effect on the next story rather than
after the next restart.

```python
INGEST_PROMPT = """You are preparing the creator's story for their own corpus.

Apply this redaction policy to every detail before you write anything:

{policy}

Reduce on the way in. This corpus is reachable by the public-facing bot, so
anything exact you write here can be surfaced, and removing it later does not
unpublish it. A bracketed value is always a fuzzed replacement — never write
the precise value you were given.

Keep the creator's phrasing. Reduce specifics, never rewrite voice. Do not add
events, details, names, or feelings that are not in the text you were handed.

Return JSON only:
{{"summary": "one sentence", "keywords": ["..."], "logged": "[~period]",
  "events": [{{"title": "short", "text": "the creator's words, redacted"}}]}}
"""

reply = model.chat([
    Message("system", INGEST_PROMPT.format(policy=read_policy())),
    Message("user", story_text),
])
parsed = json.loads(reply)
```

New-story branch: pass `parsed` straight to `propose_new_story`.

Amend branch: run the same call with the target event's current text appended
to the user message, and use only `events[0]["text"]` — the amended paragraph,
redacted, in the creator's phrasing — as `new_text` for `propose_amendment`.

If `json.loads` raises, show the raw reply and stop. Never ingest a partial
parse: a story that silently lost half its events looks successful and reports
nothing.

- [ ] **Step 4: Route the proposal through the existing gate**

`/story` proposals are `Proposal` objects, the same type the bible tools
produce, so they go through `confirm_dialog()` at `runtime/chat_app.py:65`
unchanged. Do not add a second confirm path.

- [ ] **Step 5: Refresh the index after an approved write**

```python
st.session_state["story_index"].refresh(all_chunks(), _embed)
st.session_state["story_index"].save()
```

Called after `proposal.apply()`, in the same branch that already sets
`applied_note`. `refresh` re-embeds only what changed.

- [ ] **Step 6: Verify in the running app**

Run:

```bash
export PYTHONPATH=$(pwd)
./.venv/Scripts/streamlit.exe run runtime/chat_app.py --server.headless true --server.port 8502
```

Walk all four paths and confirm each:

1. `/story` with fresh narrative → gate says **New story**, writes `ST-001.md`.
2. `/story` with a detail about that story → gate says **Amending ST-001/E-00N**, diff shows the single changed line, runners-up listed.
3. `/story` with the same text a second time → **refused as a duplicate**, naming what it matched. Nothing written.
4. Reject at the gate → nothing written, `data/stories/` unchanged.

Then confirm the undo path: after an approved amendment, a snapshot exists in
`data/.backups/` and appears in the restore list in the sidebar.

- [ ] **Step 7: Commit**

```bash
git add runtime/chat_app.py
git commit -m "feat: /story in the admin page, behind the gate the bible writes use"
```

---

## Done when

- Eleven module self-checks pass (`bible`, `tools`, `agent`, `backend`, `model`, `llamacpp`, `stories`, `index`, `embed`, `story_tools`, `convert`).
- All four gate paths behave as described in Task 7 Step 6.
- A story ingested end to end comes out redacted per `data/redaction-policy.md` — spot-check one story containing a date, a place, and a third-party name.
- `data/stories/` and `data/index/` exist, hold real content, and are absent from `git status`.
- `grep -rn "Redaction policy" --include="*.md" .` shows nothing still claiming the table lives in `sources.md`.

## Deliberately not in this plan

- The fan-side `recall` tool and the append-only prompt layout it feeds. Decided and recorded in `CLAUDE.md`; separate build.
- Indexing `sources.md`. Same machinery, different corpus, its own decisions.
- The turn budget for chunked file ingestion. Related, separately scoped.
- Replacing the linear scan or the token-overlap lexical score. Both carry `ponytail:` comments naming their ceiling and upgrade path.
