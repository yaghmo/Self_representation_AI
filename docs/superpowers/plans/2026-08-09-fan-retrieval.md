# Fan Retrieval (recall) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the fan-facing chat a read-only `recall(query)` tool over the story corpus, run entirely server-side and invisible to the client — the model decides when it needs a specific personal story, the search happens inside `service/main.py`, and the HTTP contract (`ChatResponse`) never changes shape.

**Architecture:** A new pure module (`runtime/recall.py`) holds the tool schema and the search+hydrate function, tested the same `_self_check()` way as `index.py`. `service/main.py` loads the story index and embedder once, lazily, and runs a small bounded internal loop only for non-agent `/chat` requests: call the model with the one tool offered, execute any `recall` call it makes, feed the result back, repeat up to a cap, then return the final text. `chat_app.py` gets one small change — the fan surface stops offering the streaming checkbox, since `/chat/stream` has no loop and therefore no retrieval.

**Tech Stack:** Python stdlib + numpy (already a dependency via `index.py`). No new dependency.

## Global Constraints

- Search scope is **event chunks only** (`index.search(query, embed, limit=limit, kind="event")`). Chapter/summary chunks are for ingestion routing, not retrieval — see `2026-08-07-context-budgeting-design.md`'s "fan retrieval shape" note, already decided.
- Each hit is hydrated with its **own story's existing summary chunk** (`index.chunks` lookup by `key == f"{story_id}/summary"`), not a fresh lookup through `stories.py`.
- Ordering is **whatever `Index.search` already returns** (score, highest first) — `recall()` must not resort.
- **No pinning/stickiness machinery.** Native tool-calling judgment plus the existing `bible.plan_compaction` trim already give that behavior. Do not build a topic-shift detector.
- `recall()` **never raises** out to its caller — a search failure returns the string `"recall failed: {reason}"`, same shape as a no-hits result.
- `/chat/stream` is **not touched**. Fan mode simply stops using it.
- `_reject_tools()` in `service/main.py` is **not touched** — it only inspects client-supplied `request.messages`/`request.tools`; the internal loop's messages are server-generated and appended after that check already ran.
- If the embedder/index can't load (`EmbeddingNotConfigured`), the tool is **silently not offered** that session — no error to the fan, same degrade-gracefully stance `/story` already takes on the admin side.
- `character.md` / the persona is **unchanged** — always whole, never retrieved. `sources.md` retrieval and admin-side `recall` access are both explicitly out of scope.
- Tool-call parsing mirrors the exact idiom already used in `runtime/agent.py:211-230`: `call.get("function") or {}`, `function.get("name", "")`, `call.get("id", "")`, `function.get("arguments") or "{}"`, `json.loads(raw) if isinstance(raw, str) else raw`.

---

### Task 1: `runtime/recall.py` — schema + search/hydrate

**Files:**
- Create: `runtime/recall.py`
- Test: none separate — `_self_check()` inside the same file, run via `python -m runtime.recall`

**Interfaces:**
- Consumes: `runtime.index.Index`, `runtime.index.Embedder`, `runtime.index.build`, `runtime.index.chunks_of` (existing, unchanged).
- Produces (used by Task 2):
  - `RECALL_SCHEMA: dict` — an OpenAI-shaped tool schema, `function.name == "recall"`, one required string parameter `query`.
  - `RESULT_LIMIT: int = 3`
  - `recall(query: str, index: Index, embed: Embedder, limit: int = RESULT_LIMIT) -> str` — never raises.

- [ ] **Step 1: Write the self-check (it will fail — nothing exists yet)**

Create `runtime/recall.py` with just the module docstring, imports, and this `_self_check()`:

```python
"""recall(query) — the one read-only tool the fan surface may call.

Searches the story corpus at chat time. Flat over event chunks only:
chapter and summary chunks exist for *ingestion routing* (which story a new
paste belongs to), and are the wrong signal here — see
2026-08-07-context-budgeting-design.md's "fan retrieval shape" note. Two
near-identical story summaries make the coarse layer the least
discriminative signal for two stories that differ only in one event.

No pinning, no stickiness bookkeeping. Native tool-calling judgement (the
model only calls this when it decides a question needs it) plus the
existing bible.plan_compaction (old turns age out of the prompt over a long
conversation) already give "stays on topic -> doesn't re-search; a stale
fact eventually falls out of context" for free.
"""

from __future__ import annotations

from .index import Embedder, Index

RECALL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "recall",
        "description": (
            "Search the creator's logged personal stories for one that "
            "answers the question. Use this when something asks about a "
            "specific event, memory, or experience the character profile "
            "does not cover. Returns the closest matching moments, or says "
            "none were found."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

RESULT_LIMIT = 3


def _self_check() -> None:
    import re
    import zlib

    import numpy as np

    from .index import build, chunks_of
    from .stories import Event, Story

    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, zlib.crc32(word.encode("utf-8")) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    story = Story(
        id="ST-001",
        title="a weekend hiking trip",
        summary="the guide at the trailhead, the storm, getting back after dark",
        keywords=["hiking"],
        logged="",
        events=[
            Event("E-001", "meeting the guide", "He was already waiting when we pulled in.\n"),
            Event("E-002", "the storm", "It came in fast on the second afternoon.\n"),
        ],
    )
    chunks = chunks_of(story)
    index = build(chunks, fake_embed)

    # An event hit is hydrated with its story's summary chunk as a header.
    # kind="event" means the hit itself is never a summary/chapter chunk.
    result = recall("waiting when we pulled in", index, fake_embed)
    header, _, body = result.partition("\n\n")
    assert header == f"{story.title}. {story.summary}", header
    assert "He was already waiting" in body, body
    assert "meeting the guide" in body, body

    # No match returns the "no matching stories" shape, not an exception or "".
    empty_index = build([], fake_embed)
    none_result = recall("anything", empty_index, fake_embed)
    assert "no matching stories" in none_result, none_result

    # A search failure is caught and degrades to the same non-raising shape.
    class Explodes:
        def search(self, *args, **kwargs):
            raise RuntimeError("index corrupt")

    boom = recall("anything", Explodes(), fake_embed)
    assert boom.startswith("recall failed:"), boom

    # Multiple hits stay ordered by score, highest first — recall() must not
    # reshuffle what Index.search already returned.
    other_story = Story(
        id="ST-002", title="a quiet week", summary="not much happened",
        keywords=[], logged="",
        events=[Event("E-001", "the coffee machine broke", "It died on Tuesday.\n")],
    )
    combined = build(chunks_of(story) + chunks_of(other_story), fake_embed)
    multi = recall("coffee machine broke Tuesday", combined, fake_embed, limit=2)
    first_block = multi.split("\n\n---\n\n")[0]
    assert "coffee machine" in first_block, (multi,)

    print("recall: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m runtime.recall`
Expected: `NameError: name 'recall' is not defined`

- [ ] **Step 3: Implement `recall()`**

Insert above `_self_check()`:

```python
def recall(query: str, index: Index, embed: Embedder, limit: int = RESULT_LIMIT) -> str:
    """Event-level hits, each hydrated with its story's own summary chunk.

    Never raises: a search failure degrades to the same shape as a "no
    hits" result, so one bad call costs the model a turn, not the whole
    request — matching tools.run_tool's "a handler must never kill the
    loop" stance already established for the admin side.
    """
    try:
        hits = index.search(query, embed, limit=limit, kind="event")
    except Exception as exc:
        return f"recall failed: {exc}"

    if not hits:
        return f"no matching stories for {query!r}"

    by_key = {c.key: c for c in index.chunks}
    parts = []
    for hit in hits:
        summary = by_key.get(f"{hit.chunk.story_id}/summary")
        header = summary.text if summary is not None else hit.chunk.story_id
        parts.append(f"{header}\n\n{hit.chunk.text}")
    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python -m runtime.recall`
Expected: `recall: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/recall.py
git commit -m "feat: recall(query) over the story corpus, event-level with summary hydration"
```

---

### Task 2: `service/main.py` — the internal recall loop

**Files:**
- Modify: `service/main.py` — imports, two new module-level globals + a loader function, one new loop function, the `/chat` handler, `_self_check()`.

**Interfaces:**
- Consumes: `runtime.recall.RECALL_SCHEMA`, `runtime.recall.recall` (Task 1); `runtime.embed.bge_embedder`, `runtime.embed.EmbeddingNotConfigured` (existing); `runtime.index.Index`, `runtime.index.load_index` (existing).
- Produces: nothing consumed by Task 3 — `chat_app.py` needs no new interface, only a UI change (see Task 3's Global Constraints).

- [ ] **Step 1: Add the imports**

In `service/main.py`, add to the import block near line 30:

```python
import json
```

and near the other `runtime.*` imports (around line 44):

```python
from runtime.embed import EmbeddingNotConfigured, bge_embedder
from runtime.index import Embedder, Index, load_index
from runtime.recall import RECALL_SCHEMA, recall
```

- [ ] **Step 2: Add the recall loader and the loop, module-level (near `_model`/`REPLY_RATIO`, around line 52-62)**

```python
# Independent of `_model` — the embedder and story index have nothing to do
# with the LLM's load state, so they are never unloaded together.
_story_index: Index | None = None
_story_embed = None
_story_unavailable: str = ""

MAX_RECALL_ITERATIONS = 3


def _get_recall() -> tuple[Index, Embedder] | None:
    """Lazily load the story index + embedder once. None means unavailable —
    the tool is then simply never offered, never an error surfaced to a fan.
    """
    global _story_index, _story_embed, _story_unavailable
    if _story_unavailable:
        return None
    if _story_index is None or _story_embed is None:
        try:
            _story_embed = bge_embedder()
            _story_index = load_index()
        except EmbeddingNotConfigured as exc:
            _story_unavailable = str(exc)
            logger.warning("fan retrieval unavailable: %s", exc)
            return None
    return _story_index, _story_embed


def _run_recall_loop(
    model: Model,
    messages: list[Message],
    temperature: float,
    max_tokens: int,
    thinking: bool,
    index: Index,
    embed: Embedder,
) -> str:
    """Let the model call `recall` a bounded number of times before
    returning a final answer. Entirely internal to one /chat request — the
    tool exchange is appended to `messages` in place and never reaches the
    client; only the returned string does.

    ponytail: the loop does not re-check the token budget between rounds.
    `assemble()` already sized `messages` for one reply; a very chatty
    exchange (several recall rounds, each a `RESULT_LIMIT`-chunk result)
    could in principle overrun the model's context. Caught the same way any
    other overrun is today — the caller's `except Exception` turns it into
    a 502 — not silently corrupted. Revisit if a real corpus makes this
    common; nothing to tune it against yet (corpus is empty).
    """
    for _ in range(MAX_RECALL_ITERATIONS):
        content = model.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=thinking,
            tools=[RECALL_SCHEMA],
        )
        calls = getattr(model._backend, "last_tool_calls", []) or []
        if not calls:
            return content

        messages.append(Message("assistant", content, tool_calls=calls))
        for call in calls:
            function = call.get("function") or {}
            call_id = call.get("id", "")
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
                query = arguments.get("query", "") if isinstance(arguments, dict) else ""
                result = recall(query, index, embed)
            except Exception as exc:
                result = f"recall failed: {exc}"
            messages.append(Message("tool", result, tool_call_id=call_id))

    # Cap hit and still calling tools — force a real answer, no tools offered
    # this time, so the model cannot loop again.
    return model.chat(
        messages, temperature=temperature, max_tokens=max_tokens, thinking=thinking
    )
```

- [ ] **Step 3: Wire the loop into `/chat`**

Locate the `chat()` function (around line 308-351). Replace the single `model.chat(...)` call and the `tool_calls` line in the response with a branch on `model.agent`:

```python
@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    model = _require_loaded()
    log_payload(
        logger,
        "POST /chat <<",
        {
            "messages": [m.model_dump() for m in request.messages],
            "tools": [t.get("function", {}).get("name") for t in (request.tools or [])],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "thinking": request.thinking,
        },
    )
    messages = _prompt_for(model, request)
    recall_ctx = None if model.agent else _get_recall()
    try:
        if recall_ctx is not None:
            index, embed = recall_ctx
            content = _run_recall_loop(
                model, messages, request.temperature, request.max_tokens,
                request.thinking, index, embed,
            )
        else:
            content = model.chat(
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                thinking=request.thinking,
                tools=request.tools,
            )
    except Exception as exc:
        logger.exception("chat failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    backend = model._backend
    # The internal recall loop's own tool exchange never reaches the client
    # — only agent mode's tool_calls are real callbacks the client must act
    # on and render.
    tool_calls = (getattr(backend, "last_tool_calls", []) or []) if model.agent else []
    log_payload(
        logger,
        "POST /chat >>",
        {
            "content": content,
            "reasoning": getattr(backend, "last_reasoning", ""),
            "tool_calls": tool_calls,
        },
    )
    return ChatResponse(
        content=content,
        reasoning=getattr(backend, "last_reasoning", ""),
        tool_calls=tool_calls,
        prompt_tokens=getattr(backend, "last_usage", None).prompt_tokens if backend else 0,
        completion_tokens=getattr(backend, "last_usage", None).completion_tokens if backend else 0,
    )
```

- [ ] **Step 4: Add self-check coverage for the internal loop**

In `service/main.py`'s `_self_check()`, after the existing tool-rejection tests and before the final `print(...)` line, add:

```python
    # -- the internal recall loop (non-agent /chat only) ---------------------
    import re
    import zlib

    import numpy as np

    from runtime.index import Chunk, build as build_index

    def fake_embed(texts: list[str]) -> "np.ndarray":
        width = 64
        out = np.zeros((len(texts), width), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                out[row, zlib.crc32(word.encode("utf-8")) % width] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)

    fixture_chunks = [
        Chunk(key="ST-009/summary", kind="summary", story_id="ST-009", event_id="",
              text="a fixture story. nothing eventful", keywords=[]),
        Chunk(key="ST-009/E-001", kind="event", story_id="ST-009", event_id="E-001",
              text="the fixture event. it happened on a Tuesday", keywords=[]),
    ]
    fixture_index = build_index(fixture_chunks, fake_embed)

    global _story_index, _story_embed, _story_unavailable
    real_story_index, real_story_embed, real_story_unavailable = (
        _story_index, _story_embed, _story_unavailable,
    )
    _story_index, _story_embed, _story_unavailable = fixture_index, fake_embed, ""

    class FakeBackend:
        def __init__(self):
            self.last_tool_calls: list = []
            self.last_reasoning = ""
            self.last_usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)

    fake_backend = FakeBackend()

    try:
        # A non-agent turn where the model answers immediately: recall must
        # never be invoked, and behaviour matches today exactly.
        def answers_immediately(messages, **kwargs):
            fake_backend.last_tool_calls = []
            return "no search needed"

        _model.chat = answers_immediately
        _model._backend = fake_backend
        _model.agent = False
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        if response.status_code == 424:
            pass  # no data/character.md on this clone — persona checks already skipped above
        else:
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["content"] == "no search needed", response.text
            assert response.json()["tool_calls"] == [], "recall exchange must never reach the client"

        # A non-agent turn where the model calls recall once, then answers.
        recall_call = [{
            "id": "call_1", "type": "function",
            "function": {"name": "recall", "arguments": json.dumps({"query": "Tuesday"})},
        }]
        script = iter([("", recall_call), ("it happened on a Tuesday, per what I found.", [])])

        def calls_recall_once(messages, **kwargs):
            content, calls = next(script)
            fake_backend.last_tool_calls = calls
            return content

        _model.chat = calls_recall_once
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "what happened Tuesday?"}]})
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            body = response.json()
            assert body["content"] == "it happened on a Tuesday, per what I found.", body
            assert body["tool_calls"] == [], "the tool exchange must not leak into the response"

        # The iteration cap: a model that keeps calling recall forever still
        # gets bounded to MAX_RECALL_ITERATIONS searches, then one final call
        # with no `tools` offered at all — forcing an answer rather than
        # looping forever. call_log proves the exact shape, not just that
        # the request eventually returned.
        call_log: list[bool] = []

        def always_calls_recall(messages, **kwargs):
            call_log.append("tools" in kwargs)
            fake_backend.last_tool_calls = recall_call
            return "fallback answer"

        _model.chat = always_calls_recall
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "keep searching"}]})
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            assert call_log == [True] * MAX_RECALL_ITERATIONS + [False], call_log
            assert response.json()["content"] == "fallback answer", response.text

        # Agent-mode requests are unaffected: recall is never in their tool
        # list, and the loop is not entered.
        def agent_reply(messages, **kwargs):
            fake_backend.last_tool_calls = []
            return "agent answer"

        _model.chat = agent_reply
        _model.agent = True
        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "tools": schema},
        )
        _model.agent = False
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["content"] == "agent answer", response.text
    finally:
        _model.chat = record
        _model._backend = None
        _story_index, _story_embed, _story_unavailable = (
            real_story_index, real_story_embed, real_story_unavailable,
        )
```

- [ ] **Step 5: Run the self-check**

Run: `python -m service.main`
Expected: `service self-check: ok (...)` — no assertion errors, no traceback.

- [ ] **Step 6: Commit**

```bash
git add service/main.py
git commit -m "feat: run recall internally for non-agent /chat, invisible to the client"
```

---

### Task 3: `chat_app.py` — fan surface stops streaming

**Files:**
- Modify: `runtime/chat_app.py:239` (inside the sidebar's Generation section)

**Interfaces:**
- Consumes: `status` (already fetched at `chat_app.py:216`, a plain dict with an `"agent"` key — no new field needed).
- Produces: nothing consumed elsewhere.

No automated test — `chat_app.py` has no test harness (repo convention, same as Task 3 of the chat-persistence plan). Verified by hand.

- [ ] **Step 1: Replace the unconditional checkbox**

Find (around line 239):

```python
    use_stream = st.checkbox("Stream", value=True)
```

Replace with:

```python
    if status.get("agent"):
        use_stream = st.checkbox("Stream", value=True)
    else:
        use_stream = False
        st.caption(
            "Streaming is off on the fan surface — recall needs the model's "
            "full turn (including any searches) before there's anything to show."
        )
```

- [ ] **Step 2: Verify by hand**

Start the backend and the app:

```bash
uvicorn service.main:app --port 8000
streamlit run runtime/chat_app.py
```

1. With `config/stack.json`'s `"agent"` set to `false` (fan mode): confirm the Stream checkbox is gone from the sidebar and the caption about streaming being off appears instead. Send a message; confirm a reply still comes back (non-streamed).
2. With `"agent": true` (admin mode): confirm the Stream checkbox still appears and still works exactly as before.
3. Ask the fan-mode bot something a logged story would answer (once the corpus has real entries — the corpus is currently empty per CLAUDE.md status, so this specific check may have nothing to verify against yet; if so, note that in your report rather than skipping the rest).

- [ ] **Step 3: Commit**

```bash
git add runtime/chat_app.py
git commit -m "fix: fan surface stops streaming, since recall has no streaming path"
```
