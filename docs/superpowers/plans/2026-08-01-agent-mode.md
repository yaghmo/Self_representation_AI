# Agent Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the two-stack surface split into one `config/stack.json` carrying an `agent` boolean, gate tool access on it server-side, and build a client-side agent loop with bible-shaped tools and a confirm-before-write gate.

**Architecture:** The cookbook writes one config for one stack that can serve either mode; `agent` decides whether tools are legal and which system prompt the service assembles. The loop runs in the Streamlit admin page, not the service — the service passes tools through and returns tool calls but never executes one, so there is no code path from HTTP to `data/`. Writes return a proposal with a diff and touch disk only after the creator presses Apply.

**Tech Stack:** Python 3.10, FastAPI, Streamlit, httpx, llama.cpp server (already run with `--jinja`, which is what lets it emit tool calls). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-01-agent-mode-design.md`

## Global Constraints

- **No new dependencies.** Everything here is stdlib, or already in `pyproject.toml`.
- **No pytest in this repo.** Tests are `_self_check()` functions in the module they test, `assert`-based, run with `python -m <module>`, following `runtime/bible.py` and `service/main.py`. Do not add a test framework, a `tests/` directory, or fixtures.
- **Run everything through `uv run`.** Bare `python` has no dependencies installed.
- **Never put creator data in a tracked file.** `cookbook/`, `runtime/`, and `service/` are tracked. No real name, trait, quote, cite ID, or redacted value from `data/` may appear in code, comments, fixtures, or commit messages. Invent placeholder content for every fixture.
- **`data/` and `config/` are gitignored.** They must never appear in `git status` as staged. If they do, unstage before committing.
- **`cookbook/` must not import from `runtime/`.** The dependency runs the other way — `runtime/model.py` imports `cookbook.config`, and the cookbook ships as a standalone install. Duplicating a two-line helper is correct; importing across the layer creates a cycle.
- **The creator is the sole author.** No tool may write to `data/` without an explicit confirmation from the UI.

---

### Task 1: One config, no surface

Collapses `Surface` out of the fitter and the config path, and updates every consumer in the same task — `config_path()` changing shape breaks `runtime` and `service` immediately, so they move together.

**Files:**
- Modify: `cookbook/schema.py` — delete `for_surface()` (lines 146-156)
- Modify: `cookbook/fit.py` — `bible_tokens()`, `Selection`, `strategy_for()`, `evaluate()`, `_candidates()`, `auto_fit()`, `largest_shortfall()`
- Modify: `cookbook/config.py` — `config_path()`, `build_config()`, `read_config()`
- Modify: `cookbook/app.py` — surface radio (lines 127-150), role checkboxes (152-170), calls at 223/227/257/281-292, confirm block (320-343)
- Modify: `runtime/model.py` — `from_config()`, the `surface` field
- Modify: `service/main.py` — delete `_surface()` and the `SURFACE` env var, `_get_model()`

**Interfaces:**
- Produces: `cookbook.fit.bible_tokens() -> int` (no parameter), `cookbook.fit.strategy_for(context_tokens: int) -> Strategy`, `cookbook.config.config_path() -> Path` (no parameter), `cookbook.config.build_config(fit, catalogue, probe, agent: bool) -> dict`, `cookbook.config.read_config() -> dict | None`, `runtime.model.Model.from_config(port: int = 8080) -> Model` with a `Model.agent: bool` field.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing self-check in `cookbook/fit.py`**

Add at the bottom of `cookbook/fit.py`, before any existing `__main__` block:

```python
def _self_check() -> None:
    # bible_tokens takes no surface: one stack serves both modes, and the
    # agent reads sources.md through tools rather than holding it in context.
    tokens = bible_tokens()
    assert isinstance(tokens, int) and tokens > 0, tokens

    # Whichever way it was measured, the strategy threshold is that number
    # plus the conversation reserve. Assert on the boundary, not a constant,
    # so this keeps testing the logic when the profile grows.
    threshold = tokens + CONVERSATION_RESERVE_TOKENS
    assert strategy_for(threshold) == "whole-bible"
    assert strategy_for(threshold - 1) == "retrieval"

    # The fallback path: no data/ on a fresh clone.
    assert _measure(Path("does-not-exist.md"), 4_242) == 4_242

    print("fit self-check: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m cookbook.fit`
Expected: PASS. `bible_tokens()` still takes a defaulted `surface`, so calling it with no argument works today — this check does not fail yet, and that is the point of the next command.

Run: `uv run python -c "from cookbook.fit import bible_tokens; print(bible_tokens('admin'))"`
Expected: a number in the twenty-thousands. That call is what Step 3 must make impossible; it is re-run in Step 10 and must raise `TypeError` there.

- [ ] **Step 3: Drop the surface from `cookbook/fit.py`**

Replace `bible_tokens` and `strategy_for`:

```python
def bible_tokens() -> int:
    """Tokens of profile the model must hold.

    One number for both modes. The agent reads `sources.md` through tools —
    searching and appending, never holding the corpus in context — so there is
    no surface that needs it resident.
    """
    return _measure(DATA_DIR / "character.md", DEFAULT_PROFILE_TOKENS)


def strategy_for(context_tokens: int) -> Strategy:
    needed = bible_tokens() + CONVERSATION_RESERVE_TOKENS
    return "whole-bible" if context_tokens >= needed else "retrieval"
```

Delete `DEFAULT_SOURCES_TOKENS` — nothing reads it once the split is gone.

In the same file: remove `surface: Surface = "user"` from `Selection`; change `strategy = strategy_for(context_tokens, selection.surface)` in `evaluate()` back to `strategy_for(context_tokens)`; remove the `surface` parameter from `_candidates()`, `auto_fit()`, and `largest_shortfall()`, replacing `catalogue.for_surface(role, surface)` with `catalogue.by_role(role)` — the tool-calling filter moves into the catalogue in Step 4. Remove `Surface` from the `.schema` import line if nothing else in the file uses it.

- [ ] **Step 4: Make tool calling a permanent catalogue filter in `cookbook/schema.py`**

Delete `for_surface()` (lines 146-156) and replace it with a narrowed `by_role`:

```python
    def by_role(self, role: Role) -> list[ModelEntry]:
        """Candidates for a role.

        The LLM list is always narrowed to native tool calling. One stack has
        to be able to serve agent mode, since the mode is a flag that flips
        without re-fitting — and a model that cannot emit a parseable tool call
        is not an agent, it is a chatbot describing what it would have done.
        `"prompted"` models can be coaxed into JSON but have no tool tokens in
        their chat template, which is fine for chat and not for an agent whose
        failure mode is corrupting `sources.md`.
        """
        out = [m for m in self.models if m.role == role]
        if role == "llm":
            return [m for m in out if m.tool_calling == "native"]
        return out
```

Leave the `Surface` type alias in place for now; Step 6 removes it once no module imports it.

- [ ] **Step 5: One config path in `cookbook/config.py`**

```python
def config_path() -> Path:
    """One config for one stack.

    The user/admin split used to mean two stacks. It does not any more: the
    same models serve both, and `agent` decides whether tools exist.
    """
    return CONFIG_DIR / "stack.json"
```

In `build_config`, take the flag as a parameter and drop the surface keys:

```python
def build_config(fit: Fit, catalogue: Catalogue, probe: Probe, agent: bool) -> dict:
```

Replace the `"surface": selection.surface,` and `"agent": selection.surface == "admin",` lines in the returned dict with a single `"agent": agent,`.

Then simplify the two accessors:

```python
def write_config(config: dict, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def read_config(path: Path | None = None) -> dict | None:
    path = path or config_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 6: Replace the radio with a checkbox in `cookbook/app.py`**

Replace lines 127-150 (`with left:` through the `excluded` caption) with:

```python
with left:
    st.subheader("Mode")
    agent = st.checkbox(
        "Agent mode — tools enabled",
        value=False,
        help=(
            "Off is the fan bot: persona, one model call, no tools. On is you "
            "editing the bible through an agent loop. Same stack either way — "
            "the flag flips without re-fitting, so every LLM in the list emits "
            "native tool calls."
        ),
    )
```

Then, in the same file:

- Line 155/162/168 — the `key=f"emb-{surface}"` style keys lose their suffix: `key="emb"`, `key="tts"`, `key="clone"`. TTS `value=True` unconditionally, and drop the admin-specific `help`.
- Lines 223, 227, 292 — remove the `surface=surface` argument from `auto_fit`, `largest_shortfall`, and `Selection`.
- Line 257 — `catalogue.for_surface(role, surface)` becomes `catalogue.by_role(role)`.
- Lines 281-284 — `bible_tokens(surface)` becomes `bible_tokens()`, and the caption text drops the surface word:

```python
        needed = bible_tokens()
        st.caption(
            f"The profile is ~{needed:,} tokens. It goes in whole above "
            f"{needed + CONVERSATION_RESERVE_TOKENS:,}; below that, retrieval."
        )
```

- Lines 320-343 — the confirm block:

```python
if chosen_fit is not None and chosen_fit.ok:
    st.subheader("Confirm")
    st.write(
        f"Mode: **{'agent' if agent else 'chat'}** · bible strategy: "
        f"**{chosen_fit.strategy}** · context "
        f"**{chosen_fit.selection.context_tokens:,}** tokens"
    )
    destination = config_path()
    if st.button(f"Write {destination.as_posix()}", type="primary"):
        config = build_config(chosen_fit, catalogue, probe, agent)
        path = write_config(config)
        st.success(f"Wrote {path}")
        st.json(config)
else:
    st.caption("Nothing confirmed yet — pick a fit above.")

existing = read_config()
if existing:
    with st.expander(
        f"Current {config_path().as_posix()} "
        f"(written {existing.get('written_at', '?')})"
    ):
        st.json(existing)
```

Finally, delete `Surface` from `cookbook/schema.py` and any now-unused `Surface` imports across the cookbook.

- [ ] **Step 7: Update `runtime/model.py`**

`from_config` loses its surface parameter and gains the flag:

```python
    @classmethod
    def from_config(
        cls,
        catalogue: Catalogue | None = None,
        port: int = 8080,
    ) -> "Model":
        config = read_config()
        if not config:
            raise FileNotFoundError(
                f"{config_path()} does not exist — run the cookbook and confirm a stack"
            )
        catalogue = catalogue or load_catalogue()
        role = config["roles"]["llm"]
        entry = None if role.get("source") == "api" else catalogue.model(role["model_id"])
        return cls(
            entry=entry,
            role_config=role,
            context_tokens=config.get("context_tokens", 8192),
            agent=config.get("agent", False),
            bible_strategy=config.get("bible_strategy", "retrieval"),
            port=port,
        )
```

In the dataclass body, replace `surface: str = "user"` with `agent: bool = False`. In `status()`, replace `"surface": self.surface,` with `"agent": self.agent,`. Update the `__main__` block at the bottom: `Model.from_config()`.

- [ ] **Step 8: Update `service/main.py`**

Delete `_surface()` entirely, and the `SURFACE` reference in `lifespan` becomes the config's flag:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    config = read_config() or {}
    logger.info("service starting (agent=%s)", config.get("agent", False))
    yield
```

Add `from cookbook.config import read_config` to the imports. Then:

- `_get_model(surface: str = "user", port: int = 8080)` becomes `_get_model(port: int = 8080)`, dropping the `_model.surface != surface` check from its staleness test — with one config there is nothing to switch between:

```python
def _get_model(port: int = 8080) -> Model:
    global _model
    if _model is None:
        logger.info("resolving model")
        _model = Model.from_config(port=port)
        logger.info("resolved %s", _model.name)
    return _model
```

- `LoadRequest` loses its `surface` field entirely.
- `model_status(surface: str | None = None)` becomes `model_status()`, calling `_get_model()`.
- `model_load` drops `wanted = _surface(request.surface)` and calls `_get_model(request.port)`.
- In `_self_check`, delete the two surface-rejection cases added earlier today (the `/model/load` and `/model` 400 assertions) and the `surface="user"` key in the fake model's `SimpleNamespace`, replacing it with `agent=False`.

- [ ] **Step 9: Update `runtime/chat_app.py`**

Delete the `surface` radio block and `surface_param` added earlier today (the `ALLOW_SURFACE_OVERRIDE` block). `get("/model")` and `post("/model/load", {})` take no surface. The status caption line becomes:

```python
        st.caption(
            f"{'agent' if status.get('agent') else 'chat'} · {status['source']} · "
            f"context {status['context_tokens']:,} · bible: {status['bible_strategy']}"
        )
```

- [ ] **Step 10: Run both self-checks**

Run: `uv run python -m cookbook.fit`
Expected: `fit self-check: ok`

Run: `uv run python -m service.main`
Expected: `service self-check: ok (persona ~N tokens by estimate)`

Run: `uv run python -c "from cookbook.fit import bible_tokens; bible_tokens('admin')"`
Expected: `TypeError: bible_tokens() takes 0 positional arguments but 1 was given`

Run: `uv run python -c "import cookbook.app"`
Expected: only Streamlit bare-mode warnings, no `ImportError` or `NameError`.

- [ ] **Step 11: Re-cut the config**

The old `config/stack.user.json` is not read any more. Run `uv run streamlit run cookbook/app.py`, leave Agent mode unchecked, pick a fit, and press write — it lands at `config/stack.json`. Then delete the stale file:

```bash
rm config/stack.user.json
```

Verify: `uv run python -c "import json; c=json.load(open('config/stack.json')); print(c['agent'], c['context_tokens'])"`
Expected: `False <some context>` — and no `surface` key in the file.

- [ ] **Step 12: Commit**

```bash
git add cookbook/schema.py cookbook/fit.py cookbook/config.py cookbook/app.py runtime/model.py runtime/chat_app.py service/main.py
git status --short   # config/ and data/ must NOT appear
git commit -m "refactor: one stack, one config, an agent flag instead of a surface"
```

---

### Task 2: The admin system prompt

**Files:**
- Modify: `runtime/bible.py` — add `section_index()` and `build_procedure()`, extend `_self_check()`

**Interfaces:**
- Consumes: `load_profile()`, `PROFILE_PATH`, `ProfileMissing` — already in this module.
- Produces: `runtime.bible.section_index(path: Path | None = None) -> str`, `runtime.bible.build_procedure(path: Path | None = None) -> str`, `runtime.bible.PROCEDURE_PATH: Path`.

- [ ] **Step 1: Write the failing self-check**

Add to `_self_check()` in `runtime/bible.py`, after the existing `strip_cites` assertions (the `sample` fixture is already defined above them):

```python
    # The section index is the headings and nothing else — it goes in the
    # admin prompt so the model knows what sections exist without spending a
    # tool call to ask.
    index = section_index_from(sample)
    assert "## 0. At a Glance" in index, index
    assert "## Changelog" not in index, "bookkeeping is not a section to edit"
    assert "How this file works" not in index, "meta instructions are not either"
    assert "alpha" not in index, "the index is headings only, never bodies"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m runtime.bible`
Expected: `NameError: name 'section_index_from' is not defined`

- [ ] **Step 3: Implement both functions**

Add to `runtime/bible.py`, after `build_persona()`:

```python
PROCEDURE_PATH = REPO_ROOT / ".claude" / "skills" / "add" / "SKILL.md"


class ProcedureMissing(FileNotFoundError):
    pass


def section_index_from(text: str) -> str:
    """The profile's `## ` headings, one per line.

    Split from `section_index()` so it can be tested against a fixture without
    touching `data/`. Everything before `# CHARACTER` explains the file to
    humans and the changelog is bookkeeping — neither is a section the agent
    should be editing, and `slice_profile` has already removed both.
    """
    body = slice_profile(text)
    return "\n".join(line for line in body.splitlines() if line.startswith("## "))


def section_index(path: Path | None = None) -> str:
    return section_index_from(load_profile(path))


def build_procedure(path: Path | None = None) -> str:
    """The admin system prompt: the /add procedure, plus what sections exist.

    Read live rather than baked into a constant, so the index cannot drift from
    the file — and so the agent spends no tool call asking what it could have
    been told for sixty tokens.
    """
    try:
        procedure = PROCEDURE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProcedureMissing(
            f"{PROCEDURE_PATH} does not exist — agent mode has no procedure to "
            "follow. Restore the /add skill, or turn agent mode off."
        ) from exc
    return (
        procedure
        + "\n\n## Sections in the profile you are editing\n\n"
        + section_index(path)
        + "\n"
    )
```

- [ ] **Step 4: Run the self-check**

Run: `uv run python -m runtime.bible`
Expected: `bible self-check: ok`

- [ ] **Step 5: Verify against the real files**

Run:

```bash
uv run python -c "
from runtime.bible import build_procedure, section_index, estimate_tokens
print(section_index())
print('procedure tokens:', estimate_tokens(build_procedure()))
"
```

Expected: the profile's `##` headings, then a token count in the low thousands. If it prints nothing, `slice_profile` found no `# CHARACTER` marker — stop and report rather than working around it.

- [ ] **Step 6: Commit**

```bash
git add runtime/bible.py
git commit -m "feat: assemble the admin procedure prompt from the /add skill"
```

---

### Task 3: Tool calls through the backend

**Files:**
- Modify: `runtime/backend.py` — `Message`, `LocalBackend._payload()`, `LocalBackend.complete()`
- Modify: `runtime/__init__.py` — export nothing new unless it already exports `Message`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `Message(role, content, tool_calls: list[dict] | None = None, tool_call_id: str | None = None)`, `LocalBackend.last_tool_calls: list[dict]`, and `complete(messages, tools=[...])` passing tools through.

- [ ] **Step 1: Write the failing self-check**

`runtime/backend.py` has no `_self_check` yet. Add one at the bottom:

```python
def _self_check() -> None:
    # A plain message serialises as it always did — no null keys, because
    # llama-server rejects a tool_calls: null on a user turn.
    plain = Message("user", "hi")
    assert plain.as_dict() == {"role": "user", "content": "hi"}, plain.as_dict()

    # An assistant turn that called a tool carries the calls back verbatim:
    # the model must see its own call in the history or the tool result is
    # an answer to a question it never asked.
    call = {"id": "call_1", "type": "function",
            "function": {"name": "search_sources", "arguments": "{}"}}
    assistant = Message("assistant", "", tool_calls=[call])
    assert assistant.as_dict()["tool_calls"] == [call]

    # A tool result is addressed to the call it answers.
    result = Message("tool", "2 entries", tool_call_id="call_1")
    assert result.as_dict() == {
        "role": "tool", "content": "2 entries", "tool_call_id": "call_1"
    }

    # Tools reach the payload only when supplied.
    backend = LocalBackend()
    schema = [{"type": "function", "function": {"name": "noop", "parameters": {}}}]
    assert "tools" not in backend._payload([plain], False)
    assert backend._payload([plain], False, tools=schema)["tools"] == schema

    print("backend self-check: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m runtime.backend`
Expected: `TypeError: Message.__init__() got an unexpected keyword argument 'tool_calls'`

- [ ] **Step 3: Extend `Message`**

```python
@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str
    # Set on an assistant turn that called tools, and on the tool result that
    # answers one. Optional because every fan-side message has neither, and a
    # null key on a plain turn is rejected by llama-server.
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None

    def as_dict(self) -> dict:
        out: dict = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        return out
```

- [ ] **Step 4: Pass tools through and record what comes back**

In `LocalBackend`, add the field beside `last_reasoning`:

```python
    last_tool_calls: list[dict] = field(default_factory=list)
```

In `_payload()`, before the `return payload` line:

```python
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")
```

In `complete()`, after `self.last_reasoning = message.get("reasoning_content") or ""`:

```python
        self.last_tool_calls = message.get("tool_calls") or []
```

And guard the existing "reasoning only, no answer" branch so a tool call is not mistaken for an empty reply:

```python
        if not content and not self.last_tool_calls and self.last_reasoning:
```

- [ ] **Step 5: Run the self-check**

Run: `uv run python -m runtime.backend`
Expected: `backend self-check: ok`

- [ ] **Step 6: Commit**

```bash
git add runtime/backend.py
git commit -m "feat: carry tool calls through the backend"
```

---

### Task 4: Gate tools on the config flag

**Files:**
- Modify: `service/main.py` — `ChatMessage`, `ChatRequest`, `ChatResponse`, `_prompt_for()`, `chat()`, `_self_check()`

**Interfaces:**
- Consumes: `runtime.bible.build_procedure`, `ProcedureMissing` (Task 2); `Message.tool_calls` (Task 3); `Model.agent` (Task 1).
- Produces: `POST /chat` accepting `tools` and returning `tool_calls`.

- [ ] **Step 1: Write the failing self-check**

Add to `_self_check()` in `service/main.py`, after the existing persona assertions:

```python
    # Tools are illegal unless the deployment is in agent mode. Refused, not
    # ignored: a client that thinks it has tools and silently doesn't is a
    # loop that never terminates.
    schema = [{"type": "function", "function": {"name": "noop", "parameters": {}}}]
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "tools": schema},
    )
    assert response.status_code == 400, (response.status_code, response.text)
    assert "agent mode" in response.json()["detail"], response.text

    # In agent mode the system prompt is the procedure, not the persona.
    _model.agent = True
    seen.clear()
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "tools": schema},
    )
    _model.agent = False
    assert response.status_code == 200, (response.status_code, response.text)
    system = seen["messages"][0].content
    assert "You are the person described" not in system, "persona leaked into agent mode"
    assert "S-" in system, "the procedure should describe the S-### entry format"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m service.main`
Expected: `AssertionError: (200, ...)` — `tools` is currently ignored by pydantic, so the request succeeds instead of being refused.

- [ ] **Step 3: Widen the schemas**

```python
class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant|tool)$")
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = Field(default=512, ge=1, le=8192)
    thinking: bool = False
    tools: list[dict] | None = None


class ChatResponse(BaseModel):
    content: str
    reasoning: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
```

- [ ] **Step 4: Gate the tools and pick the prompt**

Add the import: `from runtime.bible import (MessageTooLarge, ProcedureMissing, ProfileMissing, ProfileTooLarge, assemble, build_persona, build_procedure)`.

Add above `_prompt_for`:

```python
def _reject_tools(model: Model, request: ChatRequest) -> None:
    """Tools exist only in agent mode.

    The split is not about model size or context — it is that a fan must not be
    able to reach the tools that write the bible. The flag comes from the
    config the cookbook wrote, so a request cannot move it.
    """
    if request.tools and not model.agent:
        raise HTTPException(
            status_code=400,
            detail=(
                "tools were supplied but this deployment is not in agent mode. "
                "Re-run the cookbook with Agent mode checked to enable them."
            ),
        )
```

In `_prompt_for`, call it first and choose the system prompt:

```python
def _prompt_for(model: Model, request: ChatRequest) -> list[Message]:
    _reject_client_system(request.messages)
    _reject_tools(model, request)
    override = [m for m in request.messages if m.role == "system"]
    history = [
        Message(m.role, m.content, tool_calls=m.tool_calls, tool_call_id=m.tool_call_id)
        for m in request.messages
        if m.role != "system"
    ]
    if override:
        persona = override[0].content
    else:
        persona = build_procedure() if model.agent else build_persona()
    try:
        return assemble(
            history,
            context_tokens=model.context_tokens,
            count=model.count_tokens,
            reserve_tokens=max(1024, request.max_tokens * 2),
            persona=persona,
        )
    except ProfileMissing as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except ProcedureMissing as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except ProfileTooLarge as exc:
        logger.error("prompt does not fit: %s", exc)
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    except MessageTooLarge as exc:
        # The caller's turn, not the profile — theirs to shorten, so 413.
        raise HTTPException(status_code=413, detail=str(exc)) from exc
```

`assemble(persona=...)` is now always given a value, so `build_persona()` is no longer called inside `bible.assemble`. Leave `assemble`'s own default in place — the self-check there relies on it.

- [ ] **Step 5: Return the tool calls**

In `chat()`, pass the tools and read the calls back:

```python
        content = model.chat(
            messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            thinking=request.thinking,
            tools=request.tools,
        )
```

and in the returned `ChatResponse`, add:

```python
        tool_calls=getattr(backend, "last_tool_calls", []) or [],
```

In `chat_stream()`, reject tools outright — a streamed tool call has no consumer:

```python
    if request.tools:
        raise HTTPException(
            status_code=400,
            detail="tool calls are not streamed — use POST /chat in agent mode",
        )
```

Place that immediately after `model = _require_loaded()`, before `_prompt_for`.

- [ ] **Step 6: Run the self-check**

Run: `uv run python -m service.main`
Expected: `service self-check: ok (persona ~N tokens by estimate)`

- [ ] **Step 7: Commit**

```bash
git add service/main.py
git commit -m "feat: accept tools only in agent mode, and prompt accordingly"
```

---

### Task 5: The bible tools

**Files:**
- Create: `runtime/tools.py`

**Interfaces:**
- Consumes: `runtime.bible.PROFILE_PATH`, `slice_profile` (Task 2 left both in place).
- Produces: `runtime.tools.Proposal`, `search_sources(query, limit=5) -> str`, `read_profile_section(heading) -> str`, `append_source(answer, feeds) -> Proposal`, `replace_profile_section(heading, text) -> Proposal`, `TOOL_SCHEMAS: list[dict]`, `run_tool(name, arguments) -> str | Proposal`.

- [ ] **Step 1: Write the failing self-check**

Create `runtime/tools.py` containing only this, so the first run fails honestly:

```python
"""Tools the admin agent calls. Pure functions over data/, no HTTP, no model.

The API is deliberately narrow. A generic write_file would let a weak model
renumber the corpus or rewrite the profile wholesale, and the only thing
standing between that and the creator's ground truth would be how carefully
someone reads a diff at 1am. So the invariants live in the signatures:

    ids are allocated by code           the model cannot collide or skip one
    sources are append-only             there is no tool that edits an entry
    the profile edits one section       named up front, nothing else moves
    searches are capped                 sources.md is ~15k tokens

Writes do not write. They return a Proposal, and the creator applies it.
"""

from __future__ import annotations


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    corpus = (
        "# Sources\n\n"
        "### S-001\n**Q:** placeholder question one\n**A:** alpha answer\n\n"
        "### S-002\n**Q:** placeholder question two\n**A:** beta answer\n"
    )
    profile = (
        "# Placeholder\n## How this file works\nmeta\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n- one\n\n"
        "## 6. Voice\n- old line\n\n"
        "## Changelog\n- v1\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sources = root / "sources.md"
        target = root / "character.md"
        sources.write_text(corpus, encoding="utf-8")
        target.write_text(profile, encoding="utf-8")

        # Search is capped and returns entries, not the file.
        hits = search_sources("answer", limit=1, path=sources)
        assert "S-001" in hits, hits
        assert "S-002" not in hits, "limit must cap the result"

        # A section read is one section.
        section = read_profile_section("6. Voice", path=target)
        assert "old line" in section
        assert "At a Glance" not in section, "one section only"

        # Append allocates the next id itself.
        proposal = append_source("gamma answer", ["6. Voice"], path=sources)
        assert "S-003" in proposal.diff, proposal.diff
        assert proposal.before == "", "an appended entry has no before"
        assert "gamma answer" in proposal.after, proposal.after
        assert sources.read_text(encoding="utf-8") == corpus, "nothing writes before apply"

        proposal.apply()
        after = sources.read_text(encoding="utf-8")
        assert after.startswith(corpus), "existing entries must be byte-identical"
        assert "S-003" in after
        assert len(list((root / ".backups").iterdir())) == 1, "apply snapshots first"

        # A section replace touches one section, and carries both sides so the
        # confirm dialog can show before beside after.
        proposal = replace_profile_section("6. Voice", "- new line", path=target)
        assert "- old line" in proposal.before, proposal.before
        assert "- new line" in proposal.after, proposal.after
        assert "At a Glance" not in proposal.before, "before is the section, not the file"
        proposal.apply()
        rewritten = target.read_text(encoding="utf-8")
        assert "- new line" in rewritten
        assert "- old line" not in rewritten
        assert "## 0. At a Glance\n- one" in rewritten, "other sections must not move"
        assert "## Changelog" in rewritten, "the changelog must survive"

        # An unknown section is refused rather than appended as a new one.
        try:
            replace_profile_section("99. Nope", "x", path=target)
        except KeyError:
            pass
        else:
            raise AssertionError("expected KeyError for an unknown section")

    print("tools self-check: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m runtime.tools`
Expected: `NameError: name 'search_sources' is not defined`

- [ ] **Step 3: Implement the module**

Insert above `_self_check()`:

```python
import difflib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .bible import PROFILE_PATH

SOURCES_PATH = PROFILE_PATH.parent / "sources.md"
ENTRY = re.compile(r"^### (S-\d+)", re.MULTILINE)
SEARCH_LIMIT = 5


@dataclass
class Proposal:
    """A write that has not happened yet.

    The creator is the sole author of the character, so an agent may compose an
    edit but never land one. `apply()` is called by the UI after a human looks
    at `diff`, and it snapshots first because `data/` is gitignored — there is
    no other undo.
    """

    path: Path
    new_text: str
    summary: str
    diff: str
    # The changed span alone, so the UI can show before beside after rather
    # than making the creator read a unified diff to approve their own words.
    # Empty `before` means the span is new.
    before: str = ""
    after: str = ""

    def apply(self) -> Path:
        backups = self.path.parent / ".backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        if self.path.exists():
            shutil.copy2(self.path, backups / f"{self.path.name}.{stamp}")
        self.path.write_text(self.new_text, encoding="utf-8")
        return self.path


def _propose(
    path: Path,
    old: str,
    new: str,
    summary: str,
    before: str = "",
    after: str = "",
) -> Proposal:
    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=path.name,
            tofile=f"{path.name} (proposed)",
            n=2,
        )
    )
    return Proposal(
        path=path, new_text=new, summary=summary, diff=diff, before=before, after=after
    )


def _entries(text: str) -> list[str]:
    """Split a sources file into whole `### S-###` blocks."""
    starts = [m.start() for m in ENTRY.finditer(text)]
    return [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]


def search_sources(query: str, limit: int = SEARCH_LIMIT, path: Path | None = None) -> str:
    """Entries whose text contains every word of the query, case-insensitively.

    Substring matching, not embeddings: this runs against one local file of a
    few dozen entries, and a retrieval stack would be a lot of machinery to
    answer a question `in` already answers.
    """
    path = path or SOURCES_PATH
    words = [w.lower() for w in query.split() if w]
    hits = [
        entry
        for entry in _entries(path.read_text(encoding="utf-8"))
        if all(w in entry.lower() for w in words)
    ]
    if not hits:
        return f"no entries match {query!r}"
    capped = hits[:limit]
    out = "\n".join(e.strip() for e in capped)
    if len(hits) > limit:
        out += f"\n\n[{len(hits) - limit} more matches not shown — narrow the query]"
    return out


def _sections(text: str) -> list[tuple[str, int, int]]:
    """(heading, start, end) for every `## ` block, in file order."""
    marks = [(m.group(1), m.start()) for m in re.finditer(r"^## (.+)$", text, re.MULTILINE)]
    spans = []
    for i, (heading, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        spans.append((heading.strip(), start, end))
    return spans


def _find_section(text: str, heading: str) -> tuple[str, int, int]:
    wanted = heading.strip().lstrip("#").strip().lower()
    for name, start, end in _sections(text):
        if name.lower() == wanted or name.lower().startswith(wanted):
            return name, start, end
    known = ", ".join(name for name, _, _ in _sections(text))
    raise KeyError(f"no section {heading!r}. Sections are: {known}")


def read_profile_section(heading: str, path: Path | None = None) -> str:
    path = path or PROFILE_PATH
    text = path.read_text(encoding="utf-8")
    _, start, end = _find_section(text, heading)
    return text[start:end].rstrip() + "\n"


def next_source_id(text: str) -> str:
    numbers = [int(m.group(1).split("-")[1]) for m in ENTRY.finditer(text)]
    return f"S-{max(numbers) + 1:03d}" if numbers else "S-001"


def append_source(answer: str, feeds: list[str], path: Path | None = None) -> Proposal:
    """Append one entry. There is no tool that edits or deletes an existing one.

    The id comes from the file, never from the model: an id the model picks is
    an id it can collide, skip, or reuse, and every cite in the profile points
    at one.
    """
    path = path or SOURCES_PATH
    old = path.read_text(encoding="utf-8")
    entry_id = next_source_id(old)
    block = (
        f"\n### {entry_id}\n"
        f"**A:** {answer.strip()}\n"
        f"**Feeds:** {', '.join(feeds) if feeds else '—'}\n"
    )
    new = old.rstrip("\n") + "\n" + block
    return _propose(
        path, old, new, f"append {entry_id} to {path.name}", before="", after=block.strip()
    )


def replace_profile_section(heading: str, text: str, path: Path | None = None) -> Proposal:
    """Replace exactly one `## ` section. Nothing outside it can move."""
    path = path or PROFILE_PATH
    old = path.read_text(encoding="utf-8")
    name, start, end = _find_section(old, heading)
    body = text.strip()
    if not body.startswith("## "):
        body = f"## {name}\n{body}"
    new = old[:start] + body.rstrip() + "\n\n" + old[end:]
    return _propose(
        path,
        old,
        new,
        f"rewrite section {name!r}",
        before=old[start:end].rstrip(),
        after=body.rstrip(),
    )


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_sources",
            "description": (
                "Search the creator's logged answers. Returns whole entries "
                "whose text contains every word of the query. Capped — narrow "
                "the query rather than asking for more."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_profile_section",
            "description": (
                "Read one section of the character profile. Use the heading "
                "exactly as listed in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {"heading": {"type": "string"}},
                "required": ["heading"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_source",
            "description": (
                "Propose appending a new entry to the sources file, verbatim. "
                "The entry id is assigned automatically. The creator must "
                "approve before anything is written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "feeds": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["answer", "feeds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_profile_section",
            "description": (
                "Propose replacing one profile section with new text. Read the "
                "section first. Every statement needs a cite. The creator must "
                "approve before anything is written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["heading", "text"],
            },
        },
    },
]

READ_TOOLS = {"search_sources": search_sources, "read_profile_section": read_profile_section}
WRITE_TOOLS = {"append_source": append_source, "replace_profile_section": replace_profile_section}


def run_tool(name: str, arguments: dict) -> str | Proposal:
    """Dispatch by name. Unknown names and bad arguments come back as text so
    the model can correct itself rather than the loop dying."""
    handler = READ_TOOLS.get(name) or WRITE_TOOLS.get(name)
    if handler is None:
        return f"no such tool {name!r}. Available: {', '.join([*READ_TOOLS, *WRITE_TOOLS])}"
    try:
        return handler(**arguments)
    except TypeError as exc:
        return f"bad arguments for {name}: {exc}"
    except KeyError as exc:
        return str(exc).strip('"')
    except OSError as exc:
        return f"{name} could not read the file: {exc}"
```

- [ ] **Step 4: Run the self-check**

Run: `uv run python -m runtime.tools`
Expected: `tools self-check: ok`

- [ ] **Step 5: Verify against the real corpus, read-only**

Run:

```bash
uv run python -c "
from runtime.tools import search_sources, next_source_id, SOURCES_PATH
print(next_source_id(SOURCES_PATH.read_text(encoding='utf-8')))
print(search_sources('the', limit=1)[:200])
"
```

Expected: the next unused id, and one entry. Nothing is written — no proposal is applied here.

- [ ] **Step 6: Commit**

```bash
git add runtime/tools.py
git commit -m "feat: bible-shaped tools that propose writes instead of making them"
```

---

### Task 6: The loop

**Files:**
- Create: `runtime/agent.py`

**Interfaces:**
- Consumes: `runtime.tools.run_tool`, `TOOL_SCHEMAS`, `Proposal` (Task 5).
- Produces: `runtime.agent.Step`, `runtime.agent.run(post, messages, max_iterations=8) -> Iterator[Step]`.

- [ ] **Step 1: Write the failing self-check**

Create `runtime/agent.py` with only the docstring and this check:

```python
"""The agent loop. Written here, not imported.

An agent is a loop: the model emits a tool call, code runs it, the result goes
back in, repeat until it stops. Wrapping that in a framework puts abstraction
exactly where local models break — malformed calls, runaway repetition, a tool
result the model ignores — which is where you most need to see what happened.

The loop runs client-side. The service passes tools through and returns tool
calls but never executes one, so no deployment can reach `data/` over HTTP.

`post` is injected: the caller supplies something that speaks POST /chat, and
the self-check supplies a script. That is the whole reason this is testable
without a model.
"""

from __future__ import annotations


def _self_check() -> None:
    calls: list[dict] = []

    def scripted(messages, tools):
        calls.append({"n": len(messages)})
        if len(calls) == 1:
            return {"content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "search_sources",
                             "arguments": '{"query": "nothing matches this"}'},
            }]}
        return {"content": "done", "tool_calls": []}

    steps = list(run(scripted, [Message("user", "hi")]))
    assert [s.kind for s in steps] == ["tool_call", "tool_result", "answer"], steps
    assert steps[-1].text == "done"
    assert len(calls) == 2, "the tool result must go back for a second turn"

    # An unknown tool comes back as a result, not an exception: the model gets
    # a chance to correct itself.
    def bad_tool(messages, tools):
        if len(messages) < 3:
            return {"content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "nope", "arguments": "{}"},
            }]}
        return {"content": "recovered", "tool_calls": []}

    steps = list(run(bad_tool, [Message("user", "hi")]))
    assert "no such tool" in steps[1].text, steps[1]
    assert steps[-1].text == "recovered"

    # Malformed JSON arguments are a result too, not a crash.
    def bad_json(messages, tools):
        if len(messages) < 3:
            return {"content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "search_sources", "arguments": "{not json"},
            }]}
        return {"content": "ok", "tool_calls": []}

    steps = list(run(bad_json, [Message("user", "hi")]))
    assert "could not parse" in steps[1].text, steps[1]

    # A model that never answers is stopped rather than left to spin.
    def never_stops(messages, tools):
        return {"content": "", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "search_sources", "arguments": '{"query": "x"}'},
        }]}

    steps = list(run(never_stops, [Message("user", "hi")], max_iterations=3))
    assert steps[-1].kind == "stopped", steps[-1]
    assert "3" in steps[-1].text, steps[-1].text

    # A write pauses: the proposal is yielded and nothing continues until the
    # caller decides.
    def wants_to_write(messages, tools):
        return {"content": "", "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "append_source",
                         "arguments": '{"answer": "placeholder", "feeds": []}'},
        }]}

    loop = run(wants_to_write, [Message("user", "hi")])
    first = next(loop)
    assert first.kind == "tool_call"
    pause = next(loop)
    assert pause.kind == "proposal", pause
    assert pause.proposal is not None and pause.proposal.diff

    print("agent self-check: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m runtime.agent`
Expected: `NameError: name 'run' is not defined`

- [ ] **Step 3: Implement the loop**

Insert above `_self_check()`:

```python
import json
from dataclasses import dataclass
from typing import Callable, Iterator

from .backend import Message
from .tools import TOOL_SCHEMAS, Proposal, run_tool

MAX_ITERATIONS = 8


@dataclass
class Step:
    """One observable thing the loop did. The UI renders these in order."""

    kind: str  # tool_call | tool_result | proposal | answer | stopped
    text: str = ""
    name: str = ""
    proposal: Proposal | None = None


def _result_message(call_id: str, text: str) -> Message:
    return Message("tool", text, tool_call_id=call_id)


def run(
    post: Callable[[list[Message], list[dict]], dict],
    messages: list[Message],
    max_iterations: int = MAX_ITERATIONS,
) -> Iterator[Step]:
    """Drive the model until it answers, proposes a write, or runs out of turns.

    Yields a Step per event so the caller can render as it goes. A write tool
    yields a `proposal` and the generator stops there: applying it is the
    creator's decision, and resuming is the caller's business — it calls `run`
    again with the tool result appended. Suspending inside a generator would
    hide that decision inside the loop, which is exactly the thing that has to
    be visible.
    """
    history = list(messages)

    for iteration in range(max_iterations):
        reply = post(history, TOOL_SCHEMAS)
        tool_calls = reply.get("tool_calls") or []

        if not tool_calls:
            yield Step("answer", text=reply.get("content", ""))
            return

        history.append(Message("assistant", reply.get("content", ""), tool_calls=tool_calls))

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            call_id = call.get("id", "")
            yield Step("tool_call", text=function.get("arguments", ""), name=name)

            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                text = f"could not parse the arguments to {name}: {exc}"
                history.append(_result_message(call_id, text))
                yield Step("tool_result", text=text, name=name)
                continue

            outcome = run_tool(name, arguments)

            if isinstance(outcome, Proposal):
                # Stop here. The creator applies or rejects, then the caller
                # resumes by calling run() again with the result appended.
                yield Step("proposal", name=name, proposal=outcome, text=outcome.summary)
                return

            history.append(_result_message(call_id, outcome))
            yield Step("tool_result", text=outcome, name=name)

    yield Step(
        "stopped",
        text=(
            f"stopped after {max_iterations} turns without an answer — the "
            "model kept calling tools. Say what you want in fewer steps, or "
            "check the tool results above for one it is misreading."
        ),
    )
```

The read/write distinction is not a name list here — it is the return type. A tool that returns a `Proposal` pauses the loop; a tool that returns text does not. Adding a write tool later means returning a `Proposal` from it and nothing else changes.

- [ ] **Step 4: Run the self-check**

Run: `uv run python -m runtime.agent`
Expected: `agent self-check: ok`

- [ ] **Step 5: Commit**

```bash
git add runtime/agent.py
git commit -m "feat: the agent loop, with a confirm gate on every write"
```

---

### Task 7: The admin page

**Files:**
- Modify: `runtime/chat_app.py` — the main chat block

**Interfaces:**
- Consumes: `runtime.agent.run`, `Step` (Task 6); `runtime.tools.Proposal` (Task 5); `runtime.backend.Message` (Task 3); the `agent` field on `GET /model` (Task 1).

- [ ] **Step 1: Add the agent branch**

In `runtime/chat_app.py`, add to the imports:

```python
from runtime.agent import run as run_agent
from runtime.backend import Message
```

After the existing `if prompt:` block's history append and before the assistant `st.chat_message` block, branch on the mode. Replace the whole `with st.chat_message("assistant"):` block with:

```python
    agent_mode = bool(status.get("agent"))

    if agent_mode:
        def post_turn(messages, tools):
            response = post(
                "/chat",
                {
                    "messages": [m.as_dict() for m in messages],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "thinking": thinking,
                    "tools": tools,
                },
            )
            response.raise_for_status()
            return response.json()

        history = [Message(m["role"], m["content"]) for m in st.session_state["history"]]
        reply = ""
        with st.chat_message("assistant"):
            for step in run_agent(post_turn, history):
                if step.kind == "tool_call":
                    st.caption(f"→ {step.name}({step.text})")
                elif step.kind == "tool_result":
                    with st.expander(f"{step.name} result"):
                        st.code(step.text)
                elif step.kind == "proposal":
                    st.warning(step.text)
                    st.code(step.proposal.diff, language="diff")
                    st.session_state["pending"] = step.proposal
                elif step.kind == "answer":
                    reply = step.text
                    st.markdown(reply)
                elif step.kind == "stopped":
                    reply = step.text
                    st.error(reply)
        if reply:
            st.session_state["history"].append({"role": "assistant", "content": reply})
    else:
        # The existing chat-mode block, moved under this else and indented one
        # level. Do not rewrite it: it is the `with st.chat_message("assistant"):`
        # block that builds `payload`, calls `stream_reply` or `post("/chat")`,
        # renders `reply`, prints the tokens-per-second caption, and appends the
        # assistant turn to history. Nothing inside it changes.
```

Indentation is the only edit to the chat-mode path. Verify it by diffing the block against `git show HEAD:runtime/chat_app.py` — the only differences should be leading whitespace.

- [ ] **Step 2: Add the confirm dialog**

A modal, not an inline block: an edit to the creator's own record should
interrupt, and a dialog cannot be scrolled past by accident. `st.dialog` needs
Streamlit ≥ 1.37 and `pyproject.toml` already floors at 1.40, so no dependency
changes.

Before/after side by side rather than a unified diff — the creator is approving
their own words, and reading `+`/`-` markers to do it is the wrong ask. The diff
stays available underneath for anything the two panes make ambiguous.

Add near the top of the file, after the `stream_reply` helper:

```python
@st.dialog("Confirm this change", width="large")
def confirm_dialog(proposal) -> None:
    """Nothing reaches disk until this returns through Apply.

    `data/` is gitignored — there is no undo but the snapshot `apply()` takes,
    and no author but the creator. So the write pauses here.
    """
    st.caption(f"{proposal.summary} — nothing has been written yet.")

    before, after = st.columns(2)
    with before:
        st.markdown("**Before**")
        if proposal.before:
            st.code(proposal.before, language="markdown")
        else:
            st.caption("_new — nothing is being replaced_")
    with after:
        st.markdown("**After**")
        st.code(proposal.after, language="markdown")

    with st.expander("Unified diff"):
        st.code(proposal.diff, language="diff")

    left, right = st.columns(2)
    if left.button("Apply", type="primary", width="stretch"):
        path = proposal.apply()
        st.session_state["pending"] = None
        st.session_state["history"].append(
            {"role": "user", "content": f"[applied: {proposal.summary}]"}
        )
        st.session_state["applied_note"] = f"Wrote {path} (snapshot in data/.backups/)"
        st.rerun()
    if right.button("Decline", width="stretch"):
        st.session_state["pending"] = None
        st.session_state["history"].append(
            {
                "role": "user",
                "content": f"[declined: {proposal.summary} — do not retry it]",
            }
        )
        st.rerun()
```

Then, immediately after the agent/chat branch, open it when something is
pending:

```python
if st.session_state.get("applied_note"):
    st.success(st.session_state.pop("applied_note"))

pending = st.session_state.get("pending")
if pending is not None:
    confirm_dialog(pending)
```

The Apply and Decline paths both append a turn to the history saying which
happened, so the next model turn knows the outcome and does not re-propose an
edit the creator just declined.

- [ ] **Step 3: Verify the page parses**

Run: `uv run python -c "import ast,pathlib; ast.parse(pathlib.Path('runtime/chat_app.py').read_text(encoding='utf-8')); print('parse ok')"`
Expected: `parse ok`

- [ ] **Step 4: End-to-end, chat mode**

Re-cut the config with Agent mode **unchecked** if it is currently on. Then:

```bash
uv run uvicorn service.main:app --port 8000
uv run streamlit run runtime/chat_app.py
```

Load the model, ask a question the profile answers. Expected: an in-character reply, no tool captions, and `prompt_tokens` in the thousands with Stream off.

- [ ] **Step 5: End-to-end, agent mode**

Re-run the cookbook with **Agent mode checked**, write the config, restart the service. Then in the page, give it a new answer to log. Expected: tool captions appear, a diff shows up, and **nothing changes on disk until you press Apply**. Verify that last part before pressing anything:

```bash
git status --short data/ 2>/dev/null; ls data/.backups 2>/dev/null || echo "no backups yet — correct"
```

Then press Apply and check the entry landed and a snapshot exists:

```bash
tail -6 data/sources.md
ls data/.backups
```

- [ ] **Step 6: Commit**

```bash
git add runtime/chat_app.py
git status --short   # data/ and config/ must NOT appear
git commit -m "feat: run the agent loop in the admin page, behind a confirm gate"
```

---

## Notes for whoever executes this

- Tasks 1-6 need no model running. Task 7 needs the service up and a model loaded.
- Task 1 leaves the repo unable to load a model until Step 11 re-cuts the config. That is expected — the old `config/stack.user.json` is not read by the new `config_path()`.
- If `git status` ever shows `data/` or `config/` staged, stop and unstage. They are gitignored and hold the creator's material.
- The `_self_check` idiom is the test framework here. Do not add pytest.
