# Context Budgeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `/story` failing on long input, and replace silent history-dropping with story-scoped context plus a summary.

**Architecture:** Four changes. The server sizes the ingestion reply from the input instead of a fixed 1024. `assemble()` gains a pinned `summary` parameter and a pure `plan_compaction()` companion. A new `/summarize` route holds the summarization prompt server-side. `chat_app` scopes what it *sends* to the current story while still *showing* everything.

**Tech Stack:** Python 3.10, FastAPI, Streamlit, numpy. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-07-context-budgeting-design.md`

## Global Constraints

- **No pytest, no `tests/` directory, no fixtures.** Tests are `_self_check()` functions in the module they test, `assert`-based, run with `python -m <module>`. Follow `runtime/bible.py` and `service/main.py`. This is a hard repo rule.
- **Run everything with the venv:** `.venv\Scripts\python.exe -m <module>` on Windows PowerShell.
- **Never write instance data into tracked files.** No real names, traits, quotes or dates in `runtime/`, `service/`, `templates/` or docs. Self-checks use invented placeholder content only.
- **The persona is never truncated.** `assemble()` raises rather than shortening it.
- **Persona stays first and byte-identical** in the assembled message list — the KV prefix cache depends on it.
- `REPLY_RATIO = 1.4` and `REPLY_FLOOR = 256` are the exact values. `COMPACT_TRIP = 0.80`, `COMPACT_KEEP = 0.40`.
- After the final task, run `graphify update .` to refresh the code graph.

---

### Task 1: `plan_compaction` and a pinned summary in `assemble()`

**Files:**
- Modify: `runtime/bible.py` — add constants near the top, add `plan_compaction()` above `assemble()` (currently line 183), change `assemble()`'s signature and return, extend `_self_check()` (currently line 257)

**Interfaces:**
- Consumes: `Message` from `runtime/backend`, `estimate_tokens` (already in `bible.py`)
- Produces:
  - `plan_compaction(history: list[Message], room: int, count: Callable[[str], int] = estimate_tokens) -> tuple[list[Message], list[Message]] | None`
  - `assemble(..., summary: str = "") -> list[Message]` — new keyword-only-in-practice trailing parameter
  - `SUMMARIZE_PROMPT: str`
  - `COMPACT_TRIP: float`, `COMPACT_KEEP: float`

- [ ] **Step 1: Write the failing self-check cases**

Add to the end of `_self_check()` in `runtime/bible.py`, before the final `print`:

```python
    # -- compaction ----------------------------------------------------------
    # Invented placeholder turns only; this file is tracked.
    turns = [Message("user", f"message number {n} " + "word " * 20) for n in range(10)]
    each = estimate_tokens(turns[0].content)

    assert plan_compaction(turns, room=each * 100) is None, "must not trip with room to spare"
    assert plan_compaction([], room=10) is None, "empty history has nothing to compact"

    planned = plan_compaction(turns, room=each * 5)
    assert planned is not None, "must trip when history overruns the room"
    older, newer = planned
    assert older and newer, "both halves must be non-empty"
    assert older + newer == turns, "compaction must partition, not drop"
    assert newer[-1] is turns[-1], "the newest turn is always kept verbatim"

    # A tool result must never start the kept half — its call would be gone.
    paired = [
        Message("user", "do the thing " + "word " * 20),
        Message("assistant", "", tool_calls=[{"id": "c1", "function": {"name": "t"}}]),
        Message("tool", "the result " + "word " * 20, tool_call_id="c1"),
        Message("user", "thanks " + "word " * 20),
    ]
    split = plan_compaction(paired, room=estimate_tokens(paired[0].content) * 2)
    if split is not None:
        assert split[1][0].role != "tool", "kept half must not open on an orphaned tool result"

    # The summary is pinned: it survives a budget that evicts ordinary history.
    note = "Earlier in this conversation: they described a trip."
    out = assemble(turns, context_tokens=1400, persona=persona, summary=note)
    assert out[0].role == "system", "persona stays first"
    assert out[0].content == persona, "persona stays byte-identical"
    assert out[1].role == "user" and out[1].content == note, "summary is pinned right after the persona"

    # Absent a summary, output is unchanged from before this feature.
    assert assemble(turns, context_tokens=1400, persona=persona) == [
        m for m in assemble(turns, context_tokens=1400, persona=persona, summary="")
    ], "empty summary must be a no-op"
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
.venv\Scripts\python.exe -m runtime.bible
```

Expected: `NameError: name 'plan_compaction' is not defined`.

- [ ] **Step 3: Add the constants and the summarization prompt**

Near the other module constants at the top of `runtime/bible.py`:

```python
# Compaction trips before the wall, not at it, so a long reply never lands
# mid-turn. KEEP is the newest share of history left verbatim.
COMPACT_TRIP = 0.80
COMPACT_KEEP = 0.40

SUMMARIZE_PROMPT = """Summarise the conversation below so it can stand in for
those turns in a later prompt.

Record only what was actually said. Do not add detail, motive, or conclusion
that is not in the turns you were handed — an invented fact here becomes a
memory the assistant asserts later, with nothing marking it as derived.

Keep any correction the speaker made. A summary that drops "no, I meant —"
leaves the version they retracted standing as fact.

Write one short paragraph, third person, no preamble.
"""
```

- [ ] **Step 4: Add `plan_compaction()` above `assemble()`**

```python
def plan_compaction(
    history: list[Message],
    room: int,
    count: Callable[[str], int] = estimate_tokens,
) -> tuple[list[Message], list[Message]] | None:
    """Split history into (to_summarize, to_keep), or None if it still fits.

    Pure: no model call, no state. The caller decides what to do with the
    halves, which is what keeps the summary sticky — recomputing it every turn
    would rewrite the prompt prefix every turn and defeat the KV cache.
    """
    if not history:
        return None

    total = sum(count(m.content) for m in history)
    if total <= room * COMPACT_TRIP:
        return None

    # Walk newest-first, keeping turns until the verbatim share is spent.
    keep_budget = total * COMPACT_KEEP
    kept = 0
    split = len(history)
    for position in range(len(history) - 1, -1, -1):
        cost = count(history[position].content)
        if kept + cost > keep_budget:
            break
        kept += cost
        split = position

    # Never open the kept half on a tool result: its call sits in the half
    # being summarized, and llama-server rejects a result with no call.
    while split < len(history) and history[split].role == "tool":
        split += 1

    # The newest turn is the question this reply is for — always verbatim.
    split = min(split, len(history) - 1)
    if split <= 0:
        return None
    return history[:split], history[split:]
```

- [ ] **Step 5: Add the `summary` parameter to `assemble()`**

Change the signature (line 183) to add a trailing parameter:

```python
def assemble(
    history: list[Message],
    context_tokens: int,
    count: Callable[[str], int] = estimate_tokens,
    reserve_tokens: int = 1024,
    persona: str | None = None,
    summary: str = "",
) -> list[Message]:
```

Then, immediately after `remaining = budget - persona_tokens` (currently line 210), insert:

```python
    # Pinned outside the trimming loop. As the first entry of `history` it
    # would be the first thing evicted — the compaction undone by the next
    # turn that needed room. Its cost comes off the budget before the loop.
    pinned: list[Message] = []
    if summary:
        summary_cost = count(summary)
        if summary_cost < remaining:
            pinned = [Message("user", summary)]
            remaining -= summary_cost
```

And change the return (currently line 233) to:

```python
    return [Message("system", persona), *pinned, *_whole_tool_pairs(kept)]
```

- [ ] **Step 6: Run the self-check**

```powershell
.venv\Scripts\python.exe -m runtime.bible
```

Expected: `bible self-check: ok`.

- [ ] **Step 7: Commit**

```bash
git add runtime/bible.py
git commit -m "feat: compaction planning, and a summary the trimmer cannot evict"
```

---

### Task 2: Size the ingestion reply from the input

**Files:**
- Modify: `service/main.py` — `IngestRequest` (line 94), `ingest()` (line 345), `_self_check()` (line ~500)

**Interfaces:**
- Consumes: `INGEST_PROMPT`, `read_policy` from `runtime.story_tools` (already imported line 43)
- Produces: `REPLY_RATIO`, `REPLY_FLOOR`, `ingest_cap(context_tokens, persona_tokens) -> int`

- [ ] **Step 1: Write the failing self-check cases**

Add to `_self_check()` in `service/main.py`, after the existing `/ingest` gate assertion:

```python
    # The cap is derived from the reply budget, not chosen separately.
    assert ingest_cap(8192, 1075) == int((8192 - 1075 - REPLY_FLOOR) / (1 + REPLY_RATIO))
    assert ingest_cap(8192, 1075) > 2000, "a normal story must fit"
    # A persona that fills the window leaves no room for any story.
    assert ingest_cap(2048, 4096) <= 0, "an over-large persona must not yield a positive cap"
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
.venv\Scripts\python.exe -m service.main
```

Expected: `NameError: name 'ingest_cap' is not defined`.

- [ ] **Step 3: Add the constants and the cap helper**

Near the other module constants in `service/main.py`:

```python
# The ingestion reply echoes the creator's text back redacted — policy
# preserves phrasing, so it barely shrinks — plus a summary, keywords, event
# titles and JSON syntax.
#
# ponytail: 1.4 is a guess, deliberately generous. Wrong low truncates the
# reply; wrong high refuses slightly early. Measure the realised ratio once a
# real corpus exists and replace it.
REPLY_RATIO = 1.4
REPLY_FLOOR = 256


def ingest_cap(context_tokens: int, persona_tokens: int) -> int:
    """Largest story that leaves room for its own redacted reply.

    From persona + input + (input * RATIO + FLOOR) <= context.
    """
    return int((context_tokens - persona_tokens - REPLY_FLOOR) / (1 + REPLY_RATIO))
```

- [ ] **Step 4: Make `max_tokens` optional**

Change `IngestRequest` (line 94):

```python
class IngestRequest(BaseModel):
    text: str
    # On the amend branch, the paragraph being edited, so the pass rewrites it
    # rather than inventing a replacement for text it never saw.
    existing: str = ""
    # None means auto: sized from the input, because the reply restates it.
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
```

- [ ] **Step 5: Size the reply and enforce the cap in `ingest()`**

In `ingest()`, replace the block that builds `messages`. After `text` is assembled (after the `if request.existing:` block) and before the `assemble()` call, insert:

```python
    persona = INGEST_PROMPT.format(policy=policy)
    persona_tokens = model.count_tokens(persona)
    input_tokens = model.count_tokens(text)
    cap = ingest_cap(model.context_tokens, persona_tokens)

    if input_tokens > cap:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This story is about {input_tokens:,} tokens. The ingestion cap "
                f"is {cap:,} tokens (roughly {cap * 4:,} characters) at the "
                "current context size, because the reply has to restate the "
                "whole story redacted. Split it at a scene break and send the "
                "halves as two /story calls — they route independently, and the "
                "second will offer to amend the first if they overlap."
            ),
        )

    max_tokens = request.max_tokens or int(input_tokens * REPLY_RATIO) + REPLY_FLOOR
```

Then change the `assemble()` call to use the local `persona`, and the `model.chat()` call to use the local `max_tokens`:

```python
        messages = assemble(
            [Message("user", text)],
            context_tokens=model.context_tokens,
            count=model.count_tokens,
            reserve_tokens=max(1024, max_tokens),
            persona=persona,
        )
```

```python
        content = model.chat(
            messages, temperature=0.2, max_tokens=max_tokens, thinking=False
        )
```

Note `reserve_tokens` is now `max(1024, max_tokens)` rather than `max_tokens * 2` — the doubling existed to guess at the reply, and `max_tokens` is now the real figure.

- [ ] **Step 6: Run the self-check**

```powershell
.venv\Scripts\python.exe -m service.main
```

Expected: `service self-check: ok (persona ~N tokens by estimate)`.

- [ ] **Step 7: Commit**

```bash
git add service/main.py
git commit -m "fix: /ingest capped the reply at 1024 while allowing 5k of story"
```

---

### Task 3: `POST /summarize`

**Files:**
- Modify: `service/main.py` — add `SummarizeRequest` beside `IngestRequest`, add the route after `ingest()`, extend `_self_check()`

**Interfaces:**
- Consumes: `SUMMARIZE_PROMPT`, `assemble` from `runtime.bible`
- Produces: `POST /summarize {"messages": [...], "max_tokens": int} -> {"content": str}`

Unlike `/ingest` this is **not** agent-gated: the fan surface compacts too. It is still safe, because the prompt is a server-held constant — a client chooses the turns to summarize, never the instruction applied to them.

- [ ] **Step 1: Write the failing self-check case**

Add to `_self_check()` in `service/main.py`:

```python
    # Summarisation is available on a fan deployment — compaction is not a
    # write, and the prompt is server-held, so no client can choose it.
    response = client.post(
        "/summarize",
        json={"messages": [{"role": "user", "content": "a thing that happened"}]},
    )
    assert response.status_code == 200, (response.status_code, response.text)
    assert "content" in response.json(), response.text
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
.venv\Scripts\python.exe -m service.main
```

Expected: assertion failure with status `404`.

- [ ] **Step 3: Add the request model**

Beside `IngestRequest` in `service/main.py`:

```python
class SummarizeRequest(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int = Field(default=256, ge=1, le=2048)
```

- [ ] **Step 4: Add the route**

After `ingest()`, and add `SUMMARIZE_PROMPT` to the existing `from runtime.bible import (...)` block:

```python
@app.post("/summarize")
def summarize(request: SummarizeRequest) -> dict:
    """Compact older turns into one paragraph.

    Not agent-gated: the fan surface fills its window too, and summarising is
    not a write. The prompt is a server-held constant for the same reason
    `/chat` refuses a client system message — a client picks which turns are
    summarised, never the instruction applied to them.

    Deliberately unlogged, like `/ingest`: the turns are conversation content
    and `log_payload` would write them to disk.
    """
    model = _require_loaded()

    transcript = "\n\n".join(f"{m.role}: {m.content}" for m in request.messages)
    try:
        messages = assemble(
            [Message("user", transcript)],
            context_tokens=model.context_tokens,
            count=model.count_tokens,
            reserve_tokens=max(1024, request.max_tokens),
            persona=SUMMARIZE_PROMPT,
        )
    except (ProfileTooLarge, MessageTooLarge) as exc:
        # Too much to summarise in one pass. The caller keeps its history
        # rather than losing it to a failed compaction.
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    content = model.chat(
        messages, temperature=0.2, max_tokens=request.max_tokens, thinking=False
    )
    return {"content": content}
```

- [ ] **Step 5: Run the self-check**

```powershell
.venv\Scripts\python.exe -m service.main
```

Expected: `service self-check: ok`.

- [ ] **Step 6: Commit**

```bash
git add service/main.py
git commit -m "feat: /summarize, with the prompt held server-side"
```

---

### Task 4: Parse an explicit story id from `/story`

**Files:**
- Modify: `runtime/story_tools.py` — add `parse_story_command()` near `route()` (line 143), extend `_self_check()`

**Interfaces:**
- Consumes: `STORY_NAME` pattern already in `runtime/stories.py`
- Produces: `parse_story_command(raw: str) -> tuple[str, str]` returning `(story_id, remaining_text)`; `story_id` is `""` when no id was given

- [ ] **Step 1: Write the failing self-check cases**

Add to `_self_check()` in `runtime/story_tools.py`:

```python
    # -- explicit story id ---------------------------------------------------
    assert parse_story_command("ST-001 we drove to the lake") == (
        "ST-001",
        "we drove to the lake",
    ), "a leading id targets that story and leaves the narrative behind"
    assert parse_story_command("st-001 we drove") == ("ST-001", "we drove"), "case insensitive"
    assert parse_story_command("we drove to the lake") == (
        "",
        "we drove to the lake",
    ), "no id means route() decides"
    # A bare id with no narrative is not a story.
    assert parse_story_command("ST-001") == ("ST-001", "")
    # Must not eat text that merely starts with something id-shaped.
    assert parse_story_command("STORY about a lake") == ("", "STORY about a lake")
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
.venv\Scripts\python.exe -m runtime.story_tools
```

Expected: `NameError: name 'parse_story_command' is not defined`.

- [ ] **Step 3: Implement it**

Add near `route()` in `runtime/story_tools.py`:

```python
# A leading story id, and only at the very start. Anchored so prose beginning
# with an id-shaped word is left alone.
LEADING_ID = re.compile(r"^\s*(ST-\d{3,})\b[:,]?\s*", re.IGNORECASE)


def parse_story_command(raw: str) -> tuple[str, str]:
    """Split a leading `ST-###` off the narrative.

    The manual override for a mis-route. Returns ("", raw) when no id leads,
    so the caller falls through to `route()` unchanged.
    """
    found = LEADING_ID.match(raw)
    if not found:
        return "", raw
    return found.group(1).upper(), raw[found.end():].strip()
```

- [ ] **Step 4: Run the self-check**

```powershell
.venv\Scripts\python.exe -m runtime.story_tools
```

Expected: `story_tools: ok`.

- [ ] **Step 5: Commit**

```bash
git add runtime/story_tools.py
git commit -m "feat: a leading story id on /story overrides routing"
```

---

### Task 5: Wire compaction and the explicit id into `chat_app`

**Files:**
- Modify: `runtime/chat_app.py` — imports (line 27-42), the `/story` text handling (line 374), the payload build (line 494)

**Interfaces:**
- Consumes: `plan_compaction`, `parse_story_command`, `POST /summarize`
- Produces: session keys `summary` (str), used by Task 6

- [ ] **Step 1: Add the imports**

```python
from runtime.bible import plan_compaction
from runtime.backend import Message
from runtime.story_tools import keep_logged, parse_story_command, propose_amendment, propose_new_story, route
from runtime.stories import STORIES_DIR, load_story
```

(`Message` and `STORIES_DIR` may already be imported — check before adding.)

- [ ] **Step 2: Use the explicit id in the `/story` path**

Replace line 374 (`text = (prompt or "").removeprefix("/story").strip()`) with:

```python
    text = (prompt or "").removeprefix("/story").strip()
    wanted_id, text = parse_story_command(text)
```

Then replace the routing block (line 402-408) with:

```python
    routing = None
    if wanted_id:
        target_path = STORIES_DIR / f"{wanted_id}.md"
        if not target_path.exists():
            # A typo must not silently become a new story.
            st.error(f"No story {wanted_id} in the corpus. Drop the id to log a new story.")
            st.stop()
        story = load_story(target_path)
        # The creator named the story; the index still picks the paragraph.
        hits = [
            h for h in st.session_state["story_index"].search(text, _embed, limit=None, kind="event")
            if h.chunk.story_id == wanted_id
        ]
        routing = Routing(
            branch="amend",
            story=story,
            event_id=hits[0].chunk.event_id if hits else "",
        )
        st.caption(f"Targeting {wanted_id} — routing skipped.")
    else:
        try:
            routing = route(text, st.session_state["story_index"], _embed)
        except Exception as exc:
            st.error(f"Routing failed — {type(exc).__name__}: {exc}")
    if routing is None:
        st.stop()
```

Add `Routing` to the `runtime.story_tools` import.

- [ ] **Step 3: Compact before sending**

Replace line 494 (`messages = list(st.session_state["history"])`) with:

```python
    floor = st.session_state.get("prompt_floor", 0)
    scoped = list(st.session_state["history"][floor:])

    # Compact before the wall. `room` is the context minus the persona and the
    # reply reserve; the service holds the real persona, so this is the client
    # estimating its own share conservatively.
    room = max(512, int(status.get("context_tokens", 8192)) - 5500 - max_tokens)
    turns = [Message(m["role"], m["content"]) for m in scoped]
    planned = plan_compaction(turns, room=room)
    if planned is not None:
        older, newer = planned
        with st.spinner("Compacting older turns"):
            response = post(
                "/summarize",
                {"messages": [m.as_dict() for m in older], "max_tokens": 256},
            )
        if response.status_code == 200:
            fresh = response.json()["content"].strip()
            previous = st.session_state.get("summary", "")
            # Fold, don't nest: the old summary is material for the new one.
            st.session_state["summary"] = (
                f"{previous} {fresh}".strip() if previous else fresh
            )
            # Those turns are now represented by the summary. Drop them from
            # what is *sent*; `history` keeps them for the visible transcript.
            st.session_state["prompt_floor"] = floor + len(older)
            scoped = [{"role": m.role, "content": m.content} for m in newer]
        else:
            # A failed compaction must not lose history. Keep sending it all
            # and let `assemble()` trim as it did before.
            st.caption("Compaction failed — older turns will be trimmed instead.")

    messages = scoped
```

- [ ] **Step 4: Send the summary with the payload**

Both `payload` (line 498) and the `post_turn` body (line 512) gain a `summary` field:

```python
    summary_note = st.session_state.get("summary", "")
```

Add `"summary": summary_note,` to both dicts.

- [ ] **Step 5: Accept and pin it server-side**

In `service/main.py`, add to `ChatRequest`:

```python
    # A compaction summary, pinned after the persona. User-role by design: a
    # client can already write user turns, so this grants no authority it did
    # not have — and it must never be a system message, which is exactly what
    # _reject_client_system exists to prevent.
    summary: str = ""
```

Pass it through in `_prompt_for()`:

```python
        return assemble(
            ...,
            summary=request.summary,
        )
```

- [ ] **Step 6: Verify everything still passes**

```powershell
.venv\Scripts\python.exe -m runtime.bible ; .venv\Scripts\python.exe -m service.main ; .venv\Scripts\python.exe -m runtime.story_tools
```

Expected: three `ok` lines.

- [ ] **Step 7: Commit**

```bash
git add runtime/chat_app.py service/main.py
git commit -m "feat: compact older turns instead of dropping them silently"
```

---

### Task 6: Story-scoped context on the admin surface

**Files:**
- Modify: `runtime/chat_app.py` — the Apply handler (line 129-131), the payload build

**Interfaces:**
- Consumes: `prompt_floor`, `summary` session keys from Task 5
- Produces: session keys `current_story` (str), `logged_stories` (list[str])

- [ ] **Step 1: Detect the switch on Apply**

In the Apply handler, after `path = proposal.apply()` (line 131):

```python
            # A story landing somewhere new scopes the context to it. Only on
            # Apply: the creator saw the gate and ratified the routing, so an
            # uncalibrated threshold can propose a wrong landing but never act
            # on one unobserved.
            if path.parent == STORIES_DIR:
                landed = path.stem
                if landed != st.session_state.get("current_story"):
                    st.session_state["current_story"] = landed
                    # The previous story is on disk, parsed and indexed. Keeping
                    # its turns in the prompt duplicates a file route() reaches
                    # in one call, so they stop being sent — and stay on screen.
                    st.session_state["prompt_floor"] = len(st.session_state["history"])
                    st.session_state.pop("summary", None)
                    logged = st.session_state.setdefault("logged_stories", [])
                    if landed not in logged:
                        logged.append(landed)
```

- [ ] **Step 2: Pin the one-line note**

In Task 5's Step 4, replace the `summary_note` line with:

```python
    logged = st.session_state.get("logged_stories", [])
    parts = []
    if logged:
        parts.append("Earlier this session you logged: " + ", ".join(logged) + ".")
    if st.session_state.get("summary"):
        parts.append(st.session_state["summary"])
    summary_note = "\n\n".join(parts)
```

- [ ] **Step 3: Keep Clear honest**

The Clear button (line 324) must reset the new keys too, or a cleared session keeps a floor pointing past the end:

```python
if columns[0].button("Clear"):
    st.session_state["history"] = []
    for key in ("prompt_floor", "summary", "current_story", "logged_stories"):
        st.session_state.pop(key, None)
    st.rerun()
```

- [ ] **Step 4: Show the scope**

Beside the turn count (line 327):

```python
columns[1].caption(
    f"{len(st.session_state['history'])} turns"
    + (f" · sending {len(st.session_state['history']) - st.session_state.get('prompt_floor', 0)}"
       if st.session_state.get("prompt_floor") else "")
)
```

- [ ] **Step 5: Verify the module still loads**

```powershell
.venv\Scripts\python.exe -m py_compile runtime\chat_app.py
```

Expected: no output.

- [ ] **Step 6: Manual check — the one thing self-checks cannot cover**

Streamlit session state has no offline harness, so this needs the real app:

```powershell
.venv\Scripts\python.exe -m uvicorn service.main:app --port 8000
.venv\Scripts\python.exe -m streamlit run runtime/chat_app.py
```

1. Load the model. Send `/story` with a short narrative. Apply.
2. Chat two or three turns.
3. Send a second, unrelated `/story`. Apply.
4. Confirm the caption shows fewer sent than total, and the earlier turns are **still visible** on screen.
5. Ask "what have we done so far" — the reply should name both story ids and not claim the session just began.

- [ ] **Step 7: Commit and refresh the graph**

```bash
git add runtime/chat_app.py
git commit -m "feat: scope admin context to the story being worked on"
```

```powershell
graphify update .
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| Part 1 — ingestion reply budget | Task 2 |
| Part 1 — client surfaces the 413 | already works (`chat_app.py:441-443`); no task needed |
| Part 2 — `plan_compaction`, pinned summary | Task 1 |
| Part 2 — summarizer with the anti-extrapolation rule | Task 1 (prompt), Task 3 (route) |
| Part 2 — user-role, not system | Task 5 Step 5 |
| Part 2 — stickiness and folding | Task 5 Step 3 |
| Part 3 — switch on applied landing | Task 6 Step 1 |
| Part 3 — display history ≠ prompt history | Task 5 Step 3, Task 6 Step 4 |
| Part 3 — pinned line naming logged stories | Task 6 Step 2 |
| Part 4 — explicit id, unknown id refused | Task 4, Task 5 Step 2 |

**Known gap:** the spec's test list includes "a switch is detected only when an *applied* landing differs" as a `story_tools` self-check. It is not testable there — the logic lives in Streamlit session state, which has no offline harness. Task 6 Step 6 covers it manually instead. Called out rather than faked with a test that asserts nothing.

**Risk to watch during execution:** Task 5 Step 3 estimates the persona at a hardcoded 5500 tokens client-side, because the client does not hold the persona. If `/rebuild` shortens the profile this over-compacts. The honest fix is the service returning its persona size from `/status`; deferred rather than smuggled in.
