# Admin API Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the admin write-capable operations that currently only run inside the Streamlit process (`run_tool`, snapshot list/restore, story routing/proposing, voice-sample save) as new FastAPI endpoints on `service/main.py`, gated to agent mode exactly the way `/ingest` already is.

**Architecture:** All new endpoints live in `service/main.py`. Proposals are stateless wire objects (a `Proposal` is already just strings) — the client gets one back as JSON and, to apply it, echoes it back whole; the server re-derives trust by validating `path` against a closed allowlist before reconstructing and calling `.apply()`. No server-side session/proposal store. The story index+embedder reuse the exact lazy-singleton `_get_recall()` already has, rather than a second cache.

**Tech Stack:** FastAPI, Pydantic (both already in use in this file). No new dependency.

## Global Constraints

- Every new route is gated the same way: `model = _require_loaded()` then `_require_agent(model)` (new shared helper, 403 if `not model.agent`) — same rule `/ingest` already enforces per-request, not a route-registration-time decision.
- `/admin/proposal/apply`'s `path` field is client-supplied and MUST be validated against a closed allowlist (`PROFILE_PATH`, `SOURCES_PATH`, a file directly under `STORIES_DIR` matching `STORY_NAME`, or `SAMPLE_PATH`) before `Proposal(**body)` is constructed — this is new, since `Proposal.path` has never before crossed a trust boundary. Do not skip this; it is a path-traversal-class defect if omitted.
- No server-side proposal store, no session concept, no new proposal id.
- Reuse `_get_recall()` for the story index+embedder in `/admin/story/route` — do not build a second singleton.
- This repo has no pytest. `service/main.py` already carries a `_self_check()` under `if __name__ == "__main__":` using `fastapi.testclient.TestClient` against a fake `_model`. New assertions extend that same function, in the same style (see the existing agent-mode toggling around `_model.agent = True` / `_model.agent = False`). Do not add a new test file or framework.
- Full design: `docs/superpowers/specs/2026-08-09-admin-api-routes-design.md`.

---

### Task 1: Shared plumbing, `/admin/tool`, `/admin/proposal/apply`

**Files:**
- Modify: `service/main.py` (imports near the top; new helpers and schemas in the `# ---- schemas ----` / `# ---- model ----` sections; two new endpoints after `/summarize`; new self-check assertions at the end of `_self_check()`)

**Interfaces:**
- Consumes: `runtime.tools.run_tool(name: str, arguments: dict) -> str | Proposal`, `runtime.tools.Proposal` (fields `path: Path, new_text: str, summary: str, diff: str, before: str = "", after: str = "", old: str = ""`, method `apply(self) -> Path` raising `StaleProposal`), `runtime.tools.STORY_NAME` (compiled regex), `runtime.tools.SOURCES_PATH: Path`, `runtime.bible.PROFILE_PATH: Path`, `runtime.stories.STORIES_DIR: Path`, `runtime.voice_sample.SAMPLE_PATH: Path` (only used for the allowlist here — Task 4 uses the rest of that module), `runtime.index.all_chunks()`.
- Produces (for later tasks): `_require_agent(model: Model) -> None` (raises `HTTPException(403, ...)` if `not model.agent`), `ToolResponse` pydantic model (`result: str | None`, `proposal: dict | None`), `_proposal_dict(proposal: Proposal) -> dict`.

- [ ] **Step 1: Add the new imports**

In `service/main.py`, add `from pathlib import Path` near the top (after `from contextlib import asynccontextmanager`), add `Request` to the fastapi import, and extend the `runtime.*` imports:

```python
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
```

Change the `runtime.bible` import block to add `PROFILE_PATH`:

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

Change `from runtime.index import Embedder, Index, load_index` to add `all_chunks`:

```python
from runtime.index import Embedder, Index, all_chunks, load_index
```

Add two new import lines (after the `runtime.story_tools` import, before `runtime.voice_sample` doesn't exist yet in this file):

```python
from runtime.stories import STORIES_DIR, load_story
from runtime.tools import (
    SOURCES_PATH,
    STORY_NAME,
    Proposal,
    StaleProposal,
    list_backups,
    restore_backup,
    run_tool,
)
from runtime.voice_sample import SAMPLE_PATH, sample_status, save_sample
```

(`list_backups`, `restore_backup` are unused until Task 2; `sample_status`, `save_sample` unused until Task 4 — imported together now since they're one line each and this is the one place imports get added. `STORIES_DIR`/`load_story` are unused until Task 3.)

- [ ] **Step 2: Add `_require_agent` next to `_require_loaded`**

In `service/main.py`, immediately after the existing `_require_loaded` function:

```python
def _require_agent(model: Model) -> None:
    """Shared gate for every /admin/* route — these write the corpus or
    execute a tool, so they are admin-side only, the same rule `/ingest`
    already enforces per-request rather than at route-registration time.
    """
    if not model.agent:
        raise HTTPException(
            status_code=403,
            detail=(
                "this route writes the corpus, so it is admin-side only and "
                "this deployment is not in agent mode."
            ),
        )
```

- [ ] **Step 3: Add the path allowlist helper**

Immediately after `_require_agent`:

```python
def _validate_proposal_path(raw_path: str) -> Path:
    """The closed set of files `/admin/proposal/apply` may ever write to.

    `Proposal.path` is only ever server-constructed everywhere else in this
    codebase — `add_profile_line`, `propose_addition`, etc. Here it arrives
    from the client, echoed back from an earlier response, so before it is
    trusted it must resolve (`.resolve()`, so `..` cannot escape it) to
    exactly one of the files this admin surface is allowed to write. Same
    closed-set discipline `_corpus_roots`/`restore_backup` already apply to
    snapshot restores, extended here to cover `apply()`'s destinations.
    """
    resolved = Path(raw_path).resolve()
    fixed = {PROFILE_PATH.resolve(), SOURCES_PATH.resolve(), SAMPLE_PATH.resolve()}
    if resolved in fixed:
        return resolved
    if resolved.parent == STORIES_DIR.resolve() and STORY_NAME.fullmatch(resolved.name):
        return resolved
    raise HTTPException(
        status_code=400,
        detail=f"{raw_path!r} is not a file this admin surface may write.",
    )
```

- [ ] **Step 4: Add the schemas**

In the `# ---- schemas ----` section, after `class LoadRequest(BaseModel): ...`:

```python
class ToolRequest(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)


class ToolResponse(BaseModel):
    result: str | None = None
    proposal: dict | None = None


class ProposalPayload(BaseModel):
    path: str
    new_text: str
    summary: str
    diff: str = ""
    before: str = ""
    after: str = ""
    old: str = ""


class ApplyResponse(BaseModel):
    path: str
```

- [ ] **Step 5: Add the `_proposal_dict` helper**

Near `_validate_proposal_path` (after it):

```python
def _proposal_dict(proposal: Proposal) -> dict:
    return {
        "path": str(proposal.path),
        "new_text": proposal.new_text,
        "summary": proposal.summary,
        "diff": proposal.diff,
        "before": proposal.before,
        "after": proposal.after,
        "old": proposal.old,
    }
```

- [ ] **Step 6: Add the two endpoints**

After the existing `/summarize` endpoint (end of the endpoints section, before `_self_check`):

```python
@app.post("/admin/tool", response_model=ToolResponse)
def admin_tool(request: ToolRequest) -> ToolResponse:
    """Execute one tool call — the exact dispatcher the agent loop already
    calls for every tool. Read tools return a string; write tools return a
    proposal for the client to render and, on confirm, echo back to
    /admin/proposal/apply. Nothing is written here.
    """
    model = _require_loaded()
    _require_agent(model)
    outcome = run_tool(request.name, request.arguments)
    if isinstance(outcome, Proposal):
        return ToolResponse(proposal=_proposal_dict(outcome))
    return ToolResponse(result=outcome)


@app.post("/admin/proposal/apply", response_model=ApplyResponse)
def admin_proposal_apply(request: ProposalPayload) -> ApplyResponse:
    """The confirm gate's Apply button, relocated from Streamlit. Decline
    needs no endpoint — the client already never calls anything on Decline
    today either.
    """
    model = _require_loaded()
    _require_agent(model)

    path = _validate_proposal_path(request.path)
    proposal = Proposal(
        path=path,
        new_text=request.new_text,
        summary=request.summary,
        diff=request.diff,
        before=request.before,
        after=request.after,
        old=request.old,
    )
    try:
        written = proposal.apply()
    except StaleProposal as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # A story landing under STORIES_DIR invalidates the cached index the same
    # way chat_app.py's confirm_dialog already refreshes it after an apply —
    # the index is derived from the files, so it follows the write.
    global _story_index
    if written.parent == STORIES_DIR and _story_index is not None:
        _story_index.refresh(all_chunks(), _story_embed)
        _story_index.save()

    return ApplyResponse(path=str(written))
```

- [ ] **Step 7: Add self-check assertions**

`_self_check()`'s current final line is:

```python
    print(f"service self-check: ok (persona ~{len(messages[0].content) // 4} tokens by estimate)")
```

Insert the block below immediately **before** that line (same indentation,
inside the function — not after it, and don't duplicate the print):

```python
    # -- /admin/tool + /admin/proposal/apply ----------------------------------
    import tempfile

    import runtime.tools as tools_module

    # Refused like every other /admin/* route when not in agent mode.
    # `_model.agent` is already False here — every prior block that set it
    # True reset it before returning control.
    response = client.post("/admin/tool", json={"name": "search_sources", "arguments": {}})
    assert response.status_code == 403, (response.status_code, response.text)
    _model.agent = True

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sources = root / "sources.md"
        profile = root / "character.md"
        sources.write_text(
            "# Sources\n\n## Source log\n\n"
            "### S-001\n- **Q:** placeholder\n- **A:** an answer about baking\n\n",
            encoding="utf-8",
        )
        profile.write_text("# Placeholder\n## 6. Voice\n- old line\n", encoding="utf-8")

        original_sources, original_profile = tools_module.SOURCES_PATH, tools_module.PROFILE_PATH
        tools_module.SOURCES_PATH = sources
        tools_module.PROFILE_PATH = profile
        try:
            # A read tool returns a string result, no proposal.
            response = client.post(
                "/admin/tool", json={"name": "search_sources", "arguments": {"query": "baking"}}
            )
            assert response.status_code == 200, (response.status_code, response.text)
            body = response.json()
            assert body["proposal"] is None, body
            assert "S-001" in body["result"], body

            # A write tool returns a proposal, and nothing is written yet.
            response = client.post(
                "/admin/tool",
                json={
                    "name": "add_profile_line",
                    "arguments": {"heading": "6. Voice", "line": "- a new line"},
                },
            )
            assert response.status_code == 200, (response.status_code, response.text)
            proposal = response.json()["proposal"]
            assert proposal is not None
            assert "a new line" in proposal["new_text"]
            assert profile.read_text(encoding="utf-8") == (
                "# Placeholder\n## 6. Voice\n- old line\n"
            ), "the tool call alone must not write anything"

            # A path outside the allowlist is refused before Proposal() is
            # even built — proves the guard fires on client-supplied paths,
            # not just on the ones this codebase happens to construct.
            forged = dict(proposal)
            forged["path"] = str(root / "not-a-corpus-file.txt")
            response = client.post("/admin/proposal/apply", json=forged)
            assert response.status_code == 400, (response.status_code, response.text)
            assert not (root / "not-a-corpus-file.txt").exists()

            # Applying the real proposal writes it.
            response = client.post("/admin/proposal/apply", json=proposal)
            assert response.status_code == 200, (response.status_code, response.text)
            assert "a new line" in profile.read_text(encoding="utf-8")

            # Re-applying the same (now stale) proposal is refused, not
            # silently merged or overwritten.
            response = client.post("/admin/proposal/apply", json=proposal)
            assert response.status_code == 409, (response.status_code, response.text)
        finally:
            tools_module.SOURCES_PATH = original_sources
            tools_module.PROFILE_PATH = original_profile

    _model.agent = False
```

- [ ] **Step 8: Run the self-check**

Run: `python -m service.main`
Expected: prints `service self-check: ok (persona ~N tokens by estimate)` for
some number N (or the earlier no-`data/character.md` skip message/return, if
this checkout has none — either is a pass; only an `AssertionError` or
traceback is a failure).

- [ ] **Step 9: Commit**

```bash
git add service/main.py
git commit -m "feat: add /admin/tool and /admin/proposal/apply routes"
```

---

### Task 2: `/admin/snapshots`, `/admin/snapshots/restore`

**Files:**
- Modify: `service/main.py` (two new endpoints after Task 1's; new self-check assertions)

**Interfaces:**
- Consumes: `_require_loaded`, `_require_agent` (Task 1), `runtime.tools.list_backups(directory: Path | None = None) -> list[Path]`, `runtime.tools.restore_backup(backup: Path, directory: Path | None = None) -> Path`.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the schema**

In the schemas section, after `ApplyResponse`:

```python
class RestoreRequest(BaseModel):
    name: str
```

- [ ] **Step 2: Add the two endpoints**

After `/admin/proposal/apply`:

```python
@app.get("/admin/snapshots")
def admin_snapshots() -> dict:
    model = _require_loaded()
    _require_agent(model)
    return {"snapshots": [p.name for p in list_backups()]}


@app.post("/admin/snapshots/restore")
def admin_snapshots_restore(request: RestoreRequest) -> dict:
    model = _require_loaded()
    _require_agent(model)
    # Resolved by name against list_backups()'s own output, not built from
    # the client's string directly — restore_backup() validates the closed
    # bible/story pair too, but there is no reason to hand it a path it has
    # to prove is safe when the safe set is already in hand.
    candidates = {p.name: p for p in list_backups()}
    backup = candidates.get(request.name)
    if backup is None:
        raise HTTPException(status_code=404, detail=f"no snapshot named {request.name!r}")
    try:
        restored = restore_backup(backup)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"restored": restored.name}
```

- [ ] **Step 3: Add self-check assertions**

Append inside `_self_check()`, after Task 1's block, still before the final return:

```python
    # -- /admin/snapshots ------------------------------------------------------
    _model.agent = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        profile = root / "character.md"
        profile.write_text("# Placeholder\n## 6. Voice\n- old line\n", encoding="utf-8")

        tools_module.PROFILE_PATH = profile
        try:
            # Nothing snapshotted yet in this fresh directory.
            response = client.get("/admin/snapshots")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["snapshots"] == []

            # snapshot() (called from inside Proposal.apply, exercised via
            # Task 1's flow) is what populates .backups/ — reproduce that
            # directly here rather than re-driving a whole tool call.
            from runtime.tools import snapshot

            snapshot(profile)
            profile.write_text("# Placeholder\n## 6. Voice\n- changed\n", encoding="utf-8")

            response = client.get("/admin/snapshots")
            assert response.status_code == 200, (response.status_code, response.text)
            names = response.json()["snapshots"]
            assert len(names) == 1, names

            response = client.post("/admin/snapshots/restore", json={"name": names[0]})
            assert response.status_code == 200, (response.status_code, response.text)
            assert "old line" in profile.read_text(encoding="utf-8")

            # An unknown name is refused, not treated as "nothing to restore".
            response = client.post("/admin/snapshots/restore", json={"name": "not-a-real-one"})
            assert response.status_code == 404, (response.status_code, response.text)
        finally:
            tools_module.PROFILE_PATH = original_profile
    _model.agent = False
```

- [ ] **Step 4: Run the self-check**

Run: `python -m service.main`
Expected: `service self-check: ok (persona ~N tokens by estimate)` for some
number N (or the earlier no-`data/character.md` skip message/return).

- [ ] **Step 5: Commit**

```bash
git add service/main.py
git commit -m "feat: add /admin/snapshots list and restore routes"
```

---

### Task 3: `/admin/story/route`, `/admin/story/propose`

**Files:**
- Modify: `service/main.py` (two new endpoints; new self-check assertions)

**Interfaces:**
- Consumes: `_require_loaded`, `_require_agent`, `_proposal_dict`, `ToolResponse` (Task 1); `runtime.stories.STORIES_DIR: Path`, `runtime.stories.load_story(path: Path) -> Story`; `runtime.story_tools.parse_story_command(raw: str) -> tuple[str, str, str]`, `runtime.story_tools.route(text: str, index: Index, embed: Embedder, directory: Path | None = None) -> Routing` (`Routing` has `branch: str`, `story: Story | None`, `event_id: str`, `runners_up: list[Hit]`; a `Hit` has `.chunk.story_id: str` and `.score: float`), `runtime.story_tools.propose_addition(story, events: list[tuple[str,str]], directory=None, keywords=None) -> Proposal`, `runtime.story_tools.propose_amendment(story, event_id, new_text, directory=None, additions=None, keywords=None) -> Proposal`, `runtime.story_tools.propose_new_story(summary, keywords, logged, events, directory=None) -> Proposal`, `runtime.story_tools.keep_logged(logged: str, source: str) -> str`; the existing `_get_recall() -> tuple[Index, Embedder] | None` and the module-level `_story_unavailable` string.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the schemas**

In the schemas section, after `RestoreRequest`:

```python
class StoryRouteRequest(BaseModel):
    text: str


class StoryEvent(BaseModel):
    title: str
    text: str


class StoryProposeRequest(BaseModel):
    branch: str  # "new" | "append" | "amend"
    story_id: str = ""
    event_id: str = ""
    # Original source text — only used on branch="new", as keep_logged's
    # fallback when the ingestion pass didn't extract a date.
    text: str = ""
    # branch="amend" only: True means events[1:] are NOT appended (a merge
    # asked for one paragraph rewritten, not the story grown).
    merge: bool = False
    summary: str = ""   # branch="new" only
    logged: str = ""    # branch="new" only
    keywords: list[str] = Field(default_factory=list)
    events: list[StoryEvent] = Field(default_factory=list)
```

Add `from runtime.story_tools import keep_logged, parse_story_command, propose_addition, propose_amendment, propose_new_story, route` — extend the existing `from runtime.story_tools import AMEND_PROMPT, INGEST_PROMPT, read_policy` line into:

```python
from runtime.story_tools import (
    AMEND_PROMPT,
    INGEST_PROMPT,
    keep_logged,
    parse_story_command,
    propose_addition,
    propose_amendment,
    propose_new_story,
    read_policy,
    route,
)
```

- [ ] **Step 2: Add `/admin/story/route`**

After `/admin/snapshots/restore`:

```python
@app.post("/admin/story/route")
def admin_story_route(request: StoryRouteRequest) -> dict:
    """Same decision `chat_app.py`'s `/story` handling makes today: an
    explicit `ST-###[/E-###]` prefix short-circuits routing; otherwise the
    story index decides.
    """
    model = _require_loaded()
    _require_agent(model)

    story_id, event_id, text = parse_story_command(request.text)
    if story_id:
        target = STORIES_DIR / f"{story_id}.md"
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"no story {story_id} in the corpus")
        story = load_story(target)
        if event_id:
            if not any(e.id == event_id for e in story.events):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"{story_id} has no {event_id}. Events present: "
                        + (", ".join(e.id for e in story.events) or "none")
                    ),
                )
            return {
                "branch": "amend",
                "story_id": story_id,
                "story_title": story.title,
                "event_id": event_id,
                "text": text,
                "runners_up": [],
            }
        return {
            "branch": "append",
            "story_id": story_id,
            "story_title": story.title,
            "event_id": "",
            "text": text,
            "runners_up": [],
        }

    pair = _get_recall()
    if pair is None:
        raise HTTPException(
            status_code=424, detail=_story_unavailable or "story retrieval unavailable"
        )
    index, embed = pair
    routing = route(text, index, embed)
    return {
        "branch": routing.branch,
        "story_id": routing.story.id if routing.story else "",
        "story_title": routing.story.title if routing.story else "",
        "event_id": routing.event_id,
        "text": text,
        "runners_up": [
            {"story_id": h.chunk.story_id, "score": h.score} for h in routing.runners_up
        ],
    }
```

- [ ] **Step 3: Add `/admin/story/propose`**

Immediately after:

```python
@app.post("/admin/story/propose", response_model=ToolResponse)
def admin_story_propose(request: StoryProposeRequest) -> ToolResponse:
    model = _require_loaded()
    _require_agent(model)

    pairs = [(e.title, e.text) for e in request.events]
    try:
        if request.branch == "amend":
            if not pairs:
                raise HTTPException(status_code=422, detail="amend needs at least one event")
            story = load_story(STORIES_DIR / f"{request.story_id}.md")
            proposal = propose_amendment(
                story,
                request.event_id,
                pairs[0][1],
                additions=[] if request.merge else pairs[1:],
                keywords=request.keywords,
            )
        elif request.branch == "append":
            story = load_story(STORIES_DIR / f"{request.story_id}.md")
            proposal = propose_addition(story, pairs, keywords=request.keywords)
        elif request.branch == "new":
            proposal = propose_new_story(
                summary=request.summary,
                keywords=request.keywords,
                logged=keep_logged(request.logged, request.text),
                events=pairs,
            )
        else:
            raise HTTPException(status_code=422, detail=f"unknown branch {request.branch!r}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ToolResponse(proposal=_proposal_dict(proposal))
```

- [ ] **Step 4: Add self-check assertions**

Append inside `_self_check()`, after Task 2's block:

```python
    # -- /admin/story/route + /admin/story/propose ----------------------------
    _model.agent = True
    # Force the "no embedder" state directly rather than relying on whatever
    # this machine happens to have configured — on a machine WITH bge-m3
    # set up, an unforced _get_recall() would hit the real data/index/*
    # corpus and make the 424 assertion below flaky (or outright wrong)
    # depending on what's actually indexed there. The point under test is
    # the endpoint's 424 wiring, not route()'s scoring — that's already
    # covered by story_tools.py's own self-check.
    global _story_index, _story_embed, _story_unavailable
    saved_index, saved_embed, saved_unavailable = _story_index, _story_embed, _story_unavailable
    _story_index, _story_embed, _story_unavailable = None, None, "no embedder configured"
    with tempfile.TemporaryDirectory() as tmp:
        stories_dir = Path(tmp) / "stories"
        stories_dir.mkdir()
        (stories_dir / "ST-001.md").write_text(
            "---\nid: ST-001\ntitle: A day at the beach\n"
            "summary: a day at the beach\nkeywords: []\nlogged: \n---\n\n"
            "## E-001 — arriving\nWe got there at noon.\n",
            encoding="utf-8",
        )

        import runtime.stories as stories_module

        original_stories_dir = stories_module.STORIES_DIR
        stories_module.STORIES_DIR = stories_dir
        # `service.main` imported STORIES_DIR by value, so the module-level
        # name here must be repointed too, not just the source module's.
        global STORIES_DIR
        original_main_stories_dir = STORIES_DIR
        STORIES_DIR = stories_dir
        try:
            # No embedder (forced above) — an unqualified route() call is
            # expected to come back 424, the same "unavailable, not an
            # error" contract _get_recall() already gives the fan path.
            response = client.post("/admin/story/route", json={"text": "something new happened"})
            assert response.status_code == 424, (response.status_code, response.text)

            # An explicit ST-### prefix bypasses the embedder entirely.
            response = client.post(
                "/admin/story/route", json={"text": "ST-001 and then we went home"}
            )
            assert response.status_code == 200, (response.status_code, response.text)
            body = response.json()
            assert body["branch"] == "append", body
            assert body["story_id"] == "ST-001", body
            assert body["text"] == "and then we went home", body

            # An explicit ST-###/E-### prefix names the paragraph directly.
            response = client.post(
                "/admin/story/route", json={"text": "ST-001/E-001 we actually got there at noon"}
            )
            assert response.status_code == 200, (response.status_code, response.text)
            body = response.json()
            assert body["branch"] == "amend", body
            assert body["event_id"] == "E-001", body

            # A story id that doesn't exist is a 404, not a silent new story.
            response = client.post("/admin/story/route", json={"text": "ST-099 nothing here"})
            assert response.status_code == 404, (response.status_code, response.text)

            # Proposing an addition to ST-001 returns a proposal, writes nothing.
            response = client.post(
                "/admin/story/propose",
                json={
                    "branch": "append",
                    "story_id": "ST-001",
                    "events": [{"title": "leaving", "text": "We left at four."}],
                },
            )
            assert response.status_code == 200, (response.status_code, response.text)
            proposal = response.json()["proposal"]
            assert proposal is not None
            assert "We left at four." in proposal["new_text"]
            assert "We left at four." not in (stories_dir / "ST-001.md").read_text(
                encoding="utf-8"
            ), "proposing must not write"

            # A brand new story needs no story_id.
            response = client.post(
                "/admin/story/propose",
                json={
                    "branch": "new",
                    "summary": "a trip to the mountains",
                    "events": [{"title": "arriving", "text": "We arrived at dusk."}],
                },
            )
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["proposal"]["path"].endswith("ST-002.md"), response.json()
        finally:
            stories_module.STORIES_DIR = original_stories_dir
            STORIES_DIR = original_main_stories_dir
    _story_index, _story_embed, _story_unavailable = saved_index, saved_embed, saved_unavailable
    _model.agent = False
```

- [ ] **Step 5: Run the self-check**

Run: `python -m service.main`
Expected: `service self-check: ok (persona ~N tokens by estimate)` for some
number N (or the earlier no-`data/character.md` skip message/return).

- [ ] **Step 6: Commit**

```bash
git add service/main.py
git commit -m "feat: add /admin/story/route and /admin/story/propose routes"
```

---

### Task 4: `/admin/voice/status`, `/admin/voice/sample`

**Files:**
- Modify: `service/main.py` (two new endpoints; new self-check assertions)

**Interfaces:**
- Consumes: `_require_loaded`, `_require_agent` (Task 1); `runtime.voice_sample.sample_status() -> str | None`, `runtime.voice_sample.save_sample(data: bytes) -> Path` (raises `ValueError` on non-WAV data).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the two endpoints**

After `/admin/story/propose`:

```python
@app.get("/admin/voice/status")
def admin_voice_status() -> dict:
    model = _require_loaded()
    _require_agent(model)
    return {"status": sample_status()}


@app.post("/admin/voice/sample")
async def admin_voice_sample(request: Request) -> dict:
    model = _require_loaded()
    _require_agent(model)
    data = await request.body()
    try:
        save_sample(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": sample_status()}
```

- [ ] **Step 2: Add self-check assertions**

Insert the block below into `_self_check()` immediately after Task 3's
block and still before the function's final line,
`print(f"service self-check: ok (persona ~{len(messages[0].content) // 4} tokens by estimate)")`
— do not add a second print statement, that line already exists:

```python
    # -- /admin/voice --------------------------------------------------------
    _model.agent = True
    with tempfile.TemporaryDirectory() as tmp:
        import runtime.voice_sample as voice_module

        original_voice_dir = voice_module.VOICE_DIR
        original_sample_path = voice_module.SAMPLE_PATH
        voice_module.VOICE_DIR = Path(tmp) / "voice"
        voice_module.SAMPLE_PATH = voice_module.VOICE_DIR / "sample.wav"
        try:
            response = client.get("/admin/voice/status")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["status"] is None

            # Non-WAV bytes are refused, not written.
            response = client.post(
                "/admin/voice/sample",
                content=b"not-a-wav",
                headers={"Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 400, (response.status_code, response.text)
            assert not voice_module.SAMPLE_PATH.exists()

            response = client.post(
                "/admin/voice/sample",
                content=b"RIFF" + b"fake-wav-bytes",
                headers={"Content-Type": "audio/wav"},
            )
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["status"] is not None

            response = client.get("/admin/voice/status")
            assert response.status_code == 200, (response.status_code, response.text)
            assert response.json()["status"] is not None
        finally:
            voice_module.VOICE_DIR = original_voice_dir
            voice_module.SAMPLE_PATH = original_sample_path
    _model.agent = False
```

Immediately after this block, the existing final line
(`print(f"service self-check: ok ...")`) still runs, unchanged.

- [ ] **Step 3: Run the self-check**

Run: `python -m service.main`
Expected: `service self-check: ok (persona ~N tokens by estimate)` for some
number N (or the earlier no-`data/character.md` skip message/return).

- [ ] **Step 4: Commit**

```bash
git add service/main.py
git commit -m "feat: add /admin/voice/status and /admin/voice/sample routes"
```
