# Compact Persona + Profile-Section Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the currently-dead `bible_strategy` config field real, so the fan chat can run on a small always-pinned persona (hard constraints + voice, never retrieval-droppable) plus `recall()` extended to also fetch whole `character.md` sections on demand — while falling back to today's whole-persona behavior automatically whenever the embedder isn't available, so this ships with zero behavior change until that dependency exists.

**Architecture:** `runtime/bible.py` gains a compact-persona builder and a profile-section chunk builder, both pure functions of profile text (mirroring the existing `slice_profile`/`section_index_from` split between path-based and text-based variants). `runtime/recall.py`'s `recall()` gains an optional second `Index` (profile sections) and merges its hits with the story index's, by score, only when asked. `service/main.py` decides per-request whether to use the compact persona, based on `bible_strategy` **and** whether the embedder actually loaded — the fallback is the load-bearing behavior of the whole feature.

**Tech Stack:** Python 3.10/3.11, FastAPI, numpy (already a transitive dependency of `runtime/index.py`, which `service/main.py` already imports unconditionally). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-compact-persona-retrieval-design.md`

## Global Constraints

- The fan chat may hold **exactly one** server-supplied read-only tool, `recall` — this plan broadens its scope, never adds a second tool (CLAUDE.md, and the spec's "Why fold into `recall()`" section).
- The compact persona must **always** contain `§0 At a Glance`, `§6 Voice & Speech Patterns`, and `§10 Interaction Rules` (the hard constraints live in `§10`) — missing any of them is a refuse-loudly error, never a silently-incomplete persona.
- `include_profile` (and the profile index) default to off/`None` everywhere — **whole-persona mode's story-only search must stay byte-identical to today's behavior** in every test that doesn't explicitly opt into compact mode.
- The story index (`data/index/stories.npz`) and the profile-section index are **two separate `Index` objects, sharing an embedder, never a chunk list or a save path** — `Index.refresh()` replaces its chunk list wholesale, so merging them would either drop story chunks or leak profile chunks into the story file on the next admin save.
- `bible_strategy: "retrieval"` in config **permits** compact mode; it does not force it. Compact mode additionally requires the embedder to have actually loaded this process. Every other combination (strategy not `"retrieval"`, or the embedder unavailable) must produce **exactly today's** whole-persona behavior — this is the fallback and it needs its own explicit test, not inference from the others.
- No changes to `/chat/stream`, `_reject_tools()`, `chat_app.py`, or the admin surface (`build_procedure()`) — out of scope per the spec.
- All citations (`` `[S-###]` ``-shaped) must be stripped before any profile text — compact or retrieved — reaches a prompt. Reuse `strip_cites()`; don't reimplement it.

---

### Task 1: `runtime/bible.py` — compact persona and profile-section chunks

**Files:**
- Modify: `runtime/bible.py`

**Interfaces:**
- Consumes: `runtime.index.Chunk` (dataclass: `key, kind, story_id, event_id, text, keywords` — all `str` except `keywords: list[str]`), already defined in `runtime/index.py`. `runtime.bible`'s existing `slice_profile(text) -> str`, `strip_cites(text) -> str`, `load_profile(path=None) -> str`, `FRAMING` (str constant), `ProfileMissing`.
- Produces (for Task 3, and indirectly Task 2's tests):
  - `COMPACT_SECTIONS: tuple[str, ...]`
  - `RETRIEVABLE_SECTIONS: tuple[str, ...]`
  - `class ProfileIncomplete(RuntimeError)`
  - `build_compact_persona_from(text: str) -> str` (pure) and `build_compact_persona(path: Path | None = None) -> str` (wrapper)
  - `profile_section_chunks_from(text: str) -> list[Chunk]` (pure) and `profile_section_chunks(path: Path | None = None) -> list[Chunk]` (wrapper)

`runtime/index.py` imports only `runtime.stories` and `numpy` — no risk of a circular import bringing `Chunk` into `bible.py`. `bible.py` is already imported eagerly by `runtime/__init__.py`, which is already imported by `service/main.py` (which already imports `runtime.recall`, which already imports `runtime.index`, which already imports `numpy` at module level) — so this adds no new dependency to anything that doesn't already have it.

- [ ] **Step 1: Add the failing self-check assertions**

Open `runtime/bible.py`. Find `_self_check()` (starts around line 347). Insert this new block immediately before the final `print("bible self-check: ok")` line:

```python
    # -- compact persona / profile-section chunks ----------------------------
    # Invented placeholder content only — same rule as the rest of this file.
    compact_sample = (
        "# Placeholder — Character Profile\n"
        "## How this file works\n"
        "Meta instructions the model must never see.\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n"
        "- placeholder glance line `[S-001]`\n"
        "## 1. Core Identity\n"
        "- placeholder identity line, retrievable only `[S-002]`\n"
        "## 6. Voice & Speech Patterns\n"
        "- placeholder voice line `[S-003]`\n"
        "## 10. Interaction Rules\n"
        "- placeholder hard constraint line, must never be dropped `[S-004]`\n"
        "## Changelog\n"
        "- v1 bookkeeping nobody should read\n"
    )

    compact = build_compact_persona_from(compact_sample)
    assert compact.startswith(FRAMING), "compact persona keeps the same framing prefix"
    assert "placeholder hard constraint line" in compact, (
        "hard constraints must survive into the compact persona"
    )
    assert "placeholder voice line" in compact, "voice register must survive into the compact persona"
    assert "placeholder glance line" in compact, "at-a-glance must survive into the compact persona"
    assert "placeholder identity line" not in compact, (
        "a retrievable-only section must not leak into the always-pinned compact persona"
    )
    assert "[S-" not in compact, "citations must not leak into the compact persona either"

    # A profile missing a required compact section must refuse loudly, not
    # silently ship a persona with no hard constraints in it.
    incomplete_sample = compact_sample.replace(
        "## 10. Interaction Rules", "## 10a. Renamed By Mistake"
    )
    try:
        build_compact_persona_from(incomplete_sample)
    except ProfileIncomplete as exc:
        assert "10. Interaction Rules" in str(exc), str(exc)
    else:
        raise AssertionError("expected ProfileIncomplete when a compact section is missing")

    chunks = profile_section_chunks_from(compact_sample)
    assert [c.key for c in chunks] == ["profile/1"], (
        "only the retrievable section present in the fixture should produce a chunk"
    )
    assert chunks[0].kind == "profile_section"
    assert chunks[0].story_id == "" and chunks[0].event_id == ""
    assert "placeholder identity line" in chunks[0].text
    assert "[S-" not in chunks[0].text, "citations must be stripped from retrievable chunks too"
    # A retrievable section simply absent from the profile is not an error —
    # unlike a missing *compact* section, it just means less to retrieve.
    assert "profile/5" not in [c.key for c in chunks]
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m runtime.bible`
Expected: `NameError: name 'build_compact_persona_from' is not defined` (or similar — the new names don't exist yet).

- [ ] **Step 3: Add the `Chunk` import and `ProfileIncomplete` exception**

In `runtime/bible.py`, change the import block near the top:

```python
from .backend import Message, tokenize_url
from .index import Chunk
```

Then, right after the existing `class ProfileMissing(FileNotFoundError): pass` (around line 43-44), add:

```python
class ProfileIncomplete(RuntimeError):
    """A required always-pinned section (see COMPACT_SECTIONS) is missing.

    Distinct from ProfileMissing (the file itself is absent) and
    ProfileTooLarge (it exists but doesn't fit) — this means the file
    exists, fits, but is structurally missing the hard constraints or
    voice register. Refuse rather than ship a compact persona with a gap
    in exactly the part that's supposed to never have one.
    """
    pass
```

- [ ] **Step 4: Add the section constants and splitter**

Immediately after the existing `FRAMING = (...)` constant and its closing `)` (around line 130), add:

```python
# The compact persona — always in the prompt, never a retrieval miss away
# from disappearing. §10 carries the Hard constraints subsection; §6 is
# voice fidelity, which has to hold on every reply, not just the ones
# retrieval happens to fire on.
COMPACT_SECTIONS = (
    "0. At a Glance",
    "6. Voice & Speech Patterns",
    "10. Interaction Rules",
)

# Everything else — fetched a whole section at a time by recall(), never
# further chunked. Order here doesn't matter; profile_section_chunks_from
# walks the profile's own document order, not this tuple's.
RETRIEVABLE_SECTIONS = (
    "1. Core Identity",
    "2. Physical Presence",
    "3. Personality & Psychology",
    "4. Background & History",
    "5. Preferences & Texture",
    "7. Relationships",
    "8. Skills & Public Role",
    "9. Goals & Motivations",
)


def _split_sections(body: str) -> dict[str, str]:
    """Map each '## ' heading's text (without the '## ' prefix) to its own
    section — heading line included, up to the next '## ' heading or the
    end of `body`. Same line-anchored boundary `section_index_from()` uses,
    so a body neither function has seen still produces the same headings.
    Anything before the first '## ' heading (the '# CHARACTER' line itself)
    has nowhere to go and is dropped, same as section_index_from() ignores it.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[len("## "):].strip()
            sections[current] = [line]
        elif current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() + "\n" for heading, lines in sections.items()}
```

- [ ] **Step 5: Add the compact-persona and chunk builders**

Immediately after `def build_persona(...)` and its closing line (around line 134), add:

```python
def build_compact_persona_from(text: str) -> str:
    """Pure function of profile text, so the self-check can run it against a
    fixture — build_compact_persona() is the path-based wrapper below."""
    body = slice_profile(text)
    sections = _split_sections(body)
    missing = [h for h in COMPACT_SECTIONS if h not in sections]
    if missing:
        raise ProfileIncomplete(
            f"the profile is missing required section(s) {missing} — the "
            "compact persona must always include the hard constraints and "
            "voice register. Check data/character.md's headings against "
            "bible.COMPACT_SECTIONS."
        )
    compact = "\n\n".join(sections[heading] for heading in COMPACT_SECTIONS)
    return FRAMING + strip_cites(compact)


def build_compact_persona(path: Path | None = None) -> str:
    return build_compact_persona_from(load_profile(path))


def profile_section_chunks_from(text: str) -> list[Chunk]:
    """Pure function of profile text — one Chunk per RETRIEVABLE_SECTIONS
    entry actually present in `text`. A section missing from the profile is
    just missing from the result, not an error (unlike a missing compact
    section) — the bot says it doesn't know, which is the correct, honest
    answer for a gap that was never sourced."""
    body = slice_profile(text)
    sections = _split_sections(body)
    chunks: list[Chunk] = []
    for heading in RETRIEVABLE_SECTIONS:
        section_text = sections.get(heading)
        if section_text is None:
            continue
        number = heading.split(".", 1)[0].strip()
        chunks.append(
            Chunk(
                key=f"profile/{number}",
                kind="profile_section",
                story_id="",
                event_id="",
                text=strip_cites(section_text),
                keywords=[],
            )
        )
    return chunks


def profile_section_chunks(path: Path | None = None) -> list[Chunk]:
    return profile_section_chunks_from(load_profile(path))
```

- [ ] **Step 6: Run the self-check again**

Run: `python -m runtime.bible`
Expected: `bible self-check: ok`

- [ ] **Step 7: Commit**

```bash
git add runtime/bible.py
git commit -m "feat(bible): add compact persona and profile-section chunk builders"
```

---

### Task 2: `runtime/recall.py` — search profile sections alongside stories

**Files:**
- Modify: `runtime/recall.py`

**Interfaces:**
- Consumes: `runtime.index.Index` (has `.search(query, embed, limit=5, kind=None) -> list[Hit]`, unchanged by this task), `runtime.index.Hit` (`.chunk: Chunk`, `.score: float`), `Chunk.kind` (now includes `"profile_section"` as a real value produced by Task 1, but this task doesn't import `bible.py` — it only needs to recognize the string).
- Produces (for Task 3):
  - `recall(query: str, index: Index, embed: Embedder, limit: int = 3, include_profile: bool = False, profile_index: Index | None = None) -> str`
  - `recall_schema(include_profile: bool) -> dict` (replaces the module-level `RECALL_SCHEMA` constant)

- [ ] **Step 1: Add the failing self-check assertions**

Open `runtime/recall.py`. Find `_self_check()`. Immediately before its closing `print("recall: ok")`, add:

```python
    # -- profile-section retrieval, folded into the same tool ----------------
    from .index import Chunk as _Chunk

    profile_chunks = [
        _Chunk(
            key="profile/5", kind="profile_section", story_id="", event_id="",
            text="## 5. Preferences & Texture\n\n- loves hiking, apparently",
            keywords=[],
        ),
    ]
    profile_index = build(profile_chunks, fake_embed)

    # Default (include_profile=False): a profile-section chunk is never
    # returned, even if it would have scored highest, and even if a
    # profile_index was passed — whole-persona mode's story search must stay
    # byte-identical to today regardless of what's available.
    default_result = recall("hiking", index, fake_embed, profile_index=profile_index)
    assert "loves hiking" not in default_result, (
        "include_profile=False must never surface a profile-section chunk"
    )

    # include_profile=True but no profile_index supplied: same as the
    # default — a caller can't accidentally search profile content by
    # flipping one flag without also holding the index.
    no_index_result = recall("hiking", index, fake_embed, include_profile=True)
    assert "loves hiking" not in no_index_result, (
        "include_profile=True with profile_index=None must not search profile content"
    )

    # include_profile=True, profile_index supplied, only a profile hit
    # matches: returned as raw chunk text, no summary-header hydration
    # attempted (there is no story summary for a profile chunk).
    only_profile = recall(
        "hiking", build([], fake_embed), fake_embed,
        include_profile=True, profile_index=profile_index,
    )
    assert "loves hiking" in only_profile, only_profile
    assert "no matching stories" not in only_profile, only_profile

    # Both a story hit and a profile-section hit, close enough to both
    # score: both appear, each formatted correctly for its own kind, in one
    # call.
    mixed = recall(
        "waiting when we pulled in, loves hiking", index, fake_embed,
        include_profile=True, profile_index=profile_index,
    )
    assert "He was already waiting" in mixed, mixed
    assert "meeting the guide" in mixed, "story hit must still be hydrated with its summary"
    assert "loves hiking" in mixed, "profile-section hit must also appear"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m runtime.recall`
Expected: `TypeError: recall() got an unexpected keyword argument 'profile_index'`

- [ ] **Step 3: Implement `include_profile` / `profile_index` and `recall_schema()`**

Replace the module-level `RECALL_SCHEMA = { ... }` block with:

```python
def recall_schema(include_profile: bool) -> dict:
    """The fan surface's one tool. Wording changes with the mode: in
    whole-persona mode the model already has every profile fact in context,
    so the tool is purely for stories the profile doesn't cover — in
    compact mode it also has to reach the profile's own retrievable
    sections, and the description has to say so or the model will never
    think to call it for an ordinary personality/background question.
    """
    if include_profile:
        description = (
            "Look up something about her — a personal story, or a profile "
            "detail (background, preferences, personality, relationships, "
            "skills, goals) not already in what you've been given. Use this "
            "whenever a question needs more than what's in front of you. "
            "Returns the closest matching material, or says none were found."
        )
    else:
        description = (
            "Search the creator's logged personal stories for one that "
            "answers the question. Use this when something asks about a "
            "specific event, memory, or experience the character profile "
            "does not cover. Returns the closest matching moments, or says "
            "none were found."
        )
    return {
        "type": "function",
        "function": {
            "name": "recall",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
```

Then replace the `recall()` function body:

```python
def recall(
    query: str,
    index: Index,
    embed: Embedder,
    limit: int = RESULT_LIMIT,
    include_profile: bool = False,
    profile_index: Index | None = None,
) -> str:
    """Event-level story hits, each hydrated with its story's own summary
    chunk. When include_profile is set and a profile_index is supplied,
    also searches whole profile sections and merges them in by score — a
    profile-section hit needs no hydration, its own text already stands
    alone.

    Never raises: a search failure degrades to the same shape as a "no
    hits" result, so one bad call costs the model a turn, not the whole
    request — matching tools.run_tool's "a handler must never kill the
    loop" stance already established for the admin side.
    """
    try:
        hits = index.search(query, embed, limit=limit, kind="event")
        if include_profile and profile_index is not None:
            hits = hits + profile_index.search(query, embed, limit=limit, kind="profile_section")
            hits.sort(key=lambda h: h.score, reverse=True)
            hits = hits[:limit]
    except Exception as exc:
        return f"recall failed: {exc}"

    if not hits:
        return f"no matching stories for {query!r}"

    by_key = {c.key: c for c in index.chunks}
    parts = []
    for hit in hits:
        if hit.chunk.kind == "profile_section":
            parts.append(hit.chunk.text)
        else:
            summary = by_key.get(f"{hit.chunk.story_id}/summary")
            header = summary.text if summary is not None else hit.chunk.story_id
            parts.append(f"{header}\n\n{hit.chunk.text}")
    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run the self-check again**

Run: `python -m runtime.recall`
Expected: `recall: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/recall.py
git commit -m "feat(recall): fold profile-section retrieval into the existing tool"
```

---

### Task 3: `service/main.py` — wire the strategy decision, with fallback

**Files:**
- Modify: `service/main.py`

**Interfaces:**
- Consumes: `runtime.bible.build_compact_persona`, `runtime.bible.profile_section_chunks`, `runtime.bible.ProfileIncomplete` (Task 1); `runtime.recall.recall`, `runtime.recall.recall_schema` (Task 2); existing `runtime.index.Index`, `build as build_index`, `Embedder`; existing `model.bible_strategy: str` (already on `Model`, `runtime/model.py:50`).
- Produces: nothing new for other tasks — this is the top of the call chain for this feature.

- [ ] **Step 1: Add the failing self-check assertions**

Open `service/main.py`. `chat()` will shortly read `model.bible_strategy`
unconditionally (Step 6 below) — the fake `_model` this self-check builds
needs that attribute from the start, or every *existing* test case runs
into an `AttributeError` before reaching any of the new ones. Find, near
the top of `_self_check()`:

```python
    _model = SimpleNamespace(
        loaded=True,
        agent=False,
        context_tokens=32768,
        count_tokens=lambda text: len(text) // 4,
        chat=record,
        _backend=None,
    )
```

Change to (`"whole"` keeps every existing test case's behavior identical —
`use_compact` only ever becomes `True` when `bible_strategy == "retrieval"`):

```python
    _model = SimpleNamespace(
        loaded=True,
        agent=False,
        context_tokens=32768,
        count_tokens=lambda text: len(text) // 4,
        chat=record,
        _backend=None,
        bible_strategy="whole",
    )
```

Now find the `-- the internal recall loop (non-agent /chat only) --` block inside `_self_check()` (around line 1737, right after the `/summarize` check and before `-- /admin/tool + /admin/proposal/apply --`). The existing block builds `fixture_index` and monkeypatches `_story_index`/`_story_embed`/`_story_unavailable`. Extend the monkeypatch to also cover the new profile-index global, and extend the fixture:

Change:

```python
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
```

to:

```python
    fixture_chunks = [
        Chunk(key="ST-009/summary", kind="summary", story_id="ST-009", event_id="",
              text="a fixture story. nothing eventful", keywords=[]),
        Chunk(key="ST-009/E-001", kind="event", story_id="ST-009", event_id="E-001",
              text="the fixture event. it happened on a Tuesday", keywords=[]),
    ]
    fixture_index = build_index(fixture_chunks, fake_embed)

    fixture_profile_chunks = [
        Chunk(key="profile/5", kind="profile_section", story_id="", event_id="",
              text="## 5. Preferences & Texture\n\n- a fixture preference, retrieved on demand",
              keywords=[]),
    ]
    fixture_profile_index = build_index(fixture_profile_chunks, fake_embed)

    global _story_index, _story_embed, _story_unavailable, _profile_index
    real_story_index, real_story_embed, real_story_unavailable, real_profile_index = (
        _story_index, _story_embed, _story_unavailable, _profile_index,
    )
    _story_index, _story_embed, _story_unavailable = fixture_index, fake_embed, ""
    _profile_index = fixture_profile_index
```

And change the matching `finally` block:

```python
    finally:
        _model.chat = record
        _model._backend = None
        _story_index, _story_embed, _story_unavailable = (
            real_story_index, real_story_embed, real_story_unavailable,
        )
```

to:

```python
    finally:
        _model.chat = record
        _model._backend = None
        _story_index, _story_embed, _story_unavailable = (
            real_story_index, real_story_embed, real_story_unavailable,
        )
        _profile_index = real_profile_index
```

Then, still inside the same `try:` block (after the existing "Agent-mode requests are unaffected" case and before the `finally:`), add:

```python
        # -- bible_strategy: compact persona + profile retrieval -------------
        # bible_strategy="retrieval" + embedder available: compact persona
        # sent, recall offered with the compact-mode wording, and a
        # profile-section hit is reachable through it.
        def compact_mode_reply(messages, **kwargs):
            fake_backend.last_tool_calls = []
            seen["messages"] = messages
            seen["tools"] = kwargs.get("tools")
            return "compact reply"

        _model.chat = compact_mode_reply
        _model.bible_strategy = "retrieval"
        seen.clear()
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            system = seen["messages"][0].content
            assert len(system) < len(build_persona()), (
                "compact persona must be shorter than the whole profile — "
                f"got {len(system)} chars vs {len(build_persona())} for the whole one"
            )
            assert seen["tools"] is not None and seen["tools"][0]["function"]["name"] == "recall"
            assert "profile detail" in seen["tools"][0]["function"]["description"], (
                "compact mode must offer the compact-mode wording of the recall schema"
            )

        # bible_strategy="retrieval" + embedder UNAVAILABLE: falls back to
        # today's whole-persona behavior exactly. This is the load-bearing
        # fallback and needs its own explicit case, not inference from the
        # cases above.
        real_unavailable = _story_unavailable
        _story_unavailable = "embedder not installed (simulated)"
        seen.clear()
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        _story_unavailable = real_unavailable
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            system = seen["messages"][0].content
            assert system.startswith("You are the person described"), (
                "no embedder available must fall back to the full whole-persona build, "
                "identical to bible_strategy='whole' or unset"
            )
            # recall_ctx is None here, so chat() takes the plain model.chat(...,
            # tools=request.tools) branch entirely — _run_recall_loop and
            # recall_schema() are never reached, and the fan request itself
            # carries no "tools" key, so this must be exactly None.
            assert seen["tools"] is None, (
                "with no embedder, the recall tool must not be offered at all"
            )

        # bible_strategy anything else: whole persona, regardless of embedder
        # availability.
        _model.bible_strategy = "whole"
        seen.clear()
        response = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            assert seen["messages"][0].content.startswith("You are the person described")

        # A whole-persona request with the embedder available still only
        # searches stories — the two knobs (bible_strategy, embedder
        # availability) must not leak into each other.
        _model.bible_strategy = "whole"
        recall_only_story = [{
            "id": "call_2", "type": "function",
            "function": {"name": "recall", "arguments": json.dumps({"query": "preference"})},
        }]
        script2 = iter([("", recall_only_story), ("no profile reach here.", [])])
        seen_tool_messages: list = []

        def calls_recall_whole_mode(messages, **kwargs):
            content, calls = next(script2)
            if not calls:
                seen_tool_messages.extend(messages)
            fake_backend.last_tool_calls = calls
            return content

        _model.chat = calls_recall_whole_mode
        response = client.post(
            "/chat", json={"messages": [{"role": "user", "content": "what do you prefer?"}]}
        )
        if response.status_code != 424:
            assert response.status_code == 200, (response.status_code, response.text)
            tool_messages = [m for m in seen_tool_messages if m.role == "tool"]
            assert tool_messages, "no tool-result message was appended"
            assert "fixture preference" not in tool_messages[-1].content, (
                "whole-persona mode must never search profile-section chunks, "
                "even when a profile index and embedder are both available"
            )
```

(`_model.bible_strategy` needs no restore — `_model` is a fresh `SimpleNamespace` local to this one `_self_check()` call, not a module global; nothing outside this function ever reads it.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m service.main`
Expected: `AttributeError` — `_profile_index` doesn't exist yet, and `_model.bible_strategy` isn't read by anything yet.

- [ ] **Step 3: Add the `_profile_index` global and extend `_get_recall()`**

Find the module globals near the top (around line 125):

```python
_story_index: Index | None = None
_story_embed = None
_story_unavailable: str = ""
```

Change to:

```python
_story_index: Index | None = None
_profile_index: Index | None = None
_story_embed = None
_story_unavailable: str = ""
```

Find `_get_recall()` and replace it:

```python
def _get_recall() -> tuple[Index, Index, Embedder] | None:
    """Lazily load the story index, the profile-section index, and the
    embedder once. None means unavailable — every tool built on top of this
    (both indices) is then simply never offered, never an error surfaced to
    a fan. Both indices share the one embedder; there's no separate
    availability check for the profile side because there's no separate
    dependency for it.
    """
    global _story_index, _profile_index, _story_embed, _story_unavailable
    if _story_unavailable:
        return None
    if _story_index is None or _profile_index is None or _story_embed is None:
        try:
            _story_embed = bge_embedder()
            _story_index = load_index()
            _profile_index = build_index(profile_section_chunks(), _story_embed)
        except EmbeddingNotConfigured as exc:
            _story_unavailable = str(exc)
            logger.warning("fan retrieval unavailable: %s", exc)
            return None
        except Exception as exc:  # a torch or weights failure, not a config one
            _story_unavailable = f"{type(exc).__name__}: {exc}"
            logger.warning("fan retrieval unavailable: %s", exc)
            return None
    return _story_index, _profile_index, _story_embed
```

- [ ] **Step 4: Update imports**

Four exact, separate edits to the top-of-file import block (lines 45-60 today):

Change (lines 45-55):

```python
from runtime.bible import (
    MessageTooLarge,
    PROFILE_PATH,
    ProcedureMissing,
    ProfileMissing,
    ProfileTooLarge,
    SUMMARIZE_PROMPT,
    assemble,
    build_persona,
    build_procedure,
)
```

to:

```python
from runtime.bible import (
    MessageTooLarge,
    PROFILE_PATH,
    ProcedureMissing,
    ProfileMissing,
    ProfileTooLarge,
    SUMMARIZE_PROMPT,
    assemble,
    build_compact_persona,
    build_persona,
    build_procedure,
    profile_section_chunks,
)
```

Change (line 57):

```python
from runtime.index import Embedder, Index, all_chunks, load_index
```

to (`build_index` needs to be available to `_get_recall()` at module scope now, not just inside `_self_check()`):

```python
from runtime.index import Embedder, Index, all_chunks, build as build_index, load_index
```

Change (line 60):

```python
from runtime.recall import RECALL_SCHEMA, recall
```

to:

```python
from runtime.recall import recall, recall_schema
```

Inside `_self_check()` (around line 1743), change:

```python
    from runtime.index import Chunk, build as build_index
```

to (drop the now-redundant `build as build_index` — it's a module-level import as of the change above; `Chunk` is still only needed inside the self-check, for constructing fixtures):

```python
    from runtime.index import Chunk
```

- [ ] **Step 5: Wire `use_compact` into `_prompt_for()`**

Find `_prompt_for()` (around line 690). It currently computes `persona` via:

```python
            persona = build_procedure() if request.tools else build_persona()
```

This line is inside a branch keyed on `override` (client-supplied system message) — it's the `else` branch, i.e. no client override. `_prompt_for()` doesn't currently have access to `recall_ctx` (that's computed in `chat()`, the caller) — the compact/whole decision needs `recall_ctx is not None`, so it has to move up into `chat()`, or `_prompt_for()` needs the decision passed in. Simplest: compute `use_compact` in `chat()` (where `recall_ctx` already lives) and pass it into `_prompt_for()` as a new parameter.

Change `_prompt_for()`'s signature and that branch:

```python
def _prompt_for(model: Model, request: ChatRequest, use_compact: bool = False) -> list[Message]:
```

```python
            persona = (
                build_procedure() if request.tools
                else build_compact_persona() if use_compact
                else build_persona()
            )
```

- [ ] **Step 6: Compute `use_compact` in `chat()` and thread it through**

Find `chat()` (around line 859). It currently reads exactly:

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
    # Same per-request signal as the persona choice above, and for the same
    # reason: `model.agent` alone would also silently withhold recall() from
    # the fan whenever agent mode happens to be on for the admin surface
    # sharing this model.
    recall_ctx = None if request.tools else _get_recall()
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
```

Replace it with:

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
    # Same per-request signal the persona choice below now also depends on:
    # `model.agent` alone would silently withhold recall() from the fan
    # whenever agent mode happens to be on for the admin surface sharing
    # this model.
    recall_ctx = None if request.tools else _get_recall()
    # bible_strategy="retrieval" only *permits* the compact persona — it
    # still needs a working embedder (recall_ctx is not None) to actually
    # use it. No embedder, no compact mode: falls back to today's whole
    # persona automatically, every request, no restart required once the
    # embedder becomes available.
    use_compact = (
        not request.tools
        and model.bible_strategy == "retrieval"
        and recall_ctx is not None
    )
    messages = _prompt_for(model, request, use_compact=use_compact)
    try:
        if recall_ctx is not None:
            story_index, profile_index, embed = recall_ctx
            content = _run_recall_loop(
                model, messages, request.temperature, request.max_tokens,
                request.thinking, story_index, embed,
                include_profile=use_compact, profile_index=profile_index,
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
```

- [ ] **Step 7: Update `_run_recall_loop()`'s signature and tool offering**

Find `_run_recall_loop()` (around line 159). Change its signature:

```python
def _run_recall_loop(
    model: Model,
    messages: list[Message],
    temperature: float,
    max_tokens: int,
    thinking: bool,
    index: Index,
    embed: Embedder,
    include_profile: bool = False,
    profile_index: Index | None = None,
) -> str:
```

Inside the loop body, change:

```python
    for _ in range(MAX_RECALL_ITERATIONS):
        content = model.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=thinking,
            tools=[RECALL_SCHEMA],
        )
```

to:

```python
    for _ in range(MAX_RECALL_ITERATIONS):
        content = model.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking=thinking,
            tools=[recall_schema(include_profile)],
        )
```

And change the `recall(query, index, embed)` call inside the tool-handling loop to:

```python
                result = recall(
                    query, index, embed,
                    include_profile=include_profile, profile_index=profile_index,
                )
```

- [ ] **Step 8: Run the self-check again**

Run: `python -m service.main`
Expected: `service self-check: ok`

- [ ] **Step 9: Run the other two modules' self-checks too, as a regression guard**

Run: `python -m runtime.bible && python -m runtime.recall && python -m runtime.backend`
Expected: all three print their `: ok` line — confirms Task 1/2's changes still hold after Task 3 wired them together.

- [ ] **Step 10: Commit**

```bash
git add service/main.py
git commit -m "feat(service): wire bible_strategy to a real compact-persona + retrieval path"
```

---

## Manual verification (not automated — do this after Task 3)

The self-checks use a fake model and fake embedder throughout, so none of them prove the feature works against the real 8B model or the real (currently-uninstalled) bge-m3 embedder. After all three tasks are committed:

1. Set `"bible_strategy": "retrieval"` in `config/stack.json` (it's very likely already set to this — check first).
2. Restart the backend (`uv run uvicorn service.main:app --port 8000`) and send a few fan-chat messages.
3. Check `logs/service.log` for `POST /chat <<` entries: with the embedder still uninstalled on this machine, the system prompt should be the **full** profile (today's behavior) — confirms the fallback actually fires in a real request, not just the scripted test.
4. Once `torch`/`transformers` are installed (separate, already out-of-scope work — see the spec's "Out of scope" section) and the embedder loads successfully, repeat: the system prompt should now be much shorter (the compact persona), and a question about something in a retrievable section (e.g. "what games do you play?") should produce a `recall` tool call visible in the log, with a `profile_section`-shaped result.
