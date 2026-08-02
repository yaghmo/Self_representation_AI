# Fan-Side Prompt Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the audience-facing bot actually read the character profile, server-side, with a token budget that fails loudly instead of silently truncating the persona.

**Architecture:** One new module `runtime/bible.py` loads `data/character.md`, slices out the human-facing meta sections, strips citation markers, and assembles a system prompt. `service/main.py` prepends that persona itself and stops accepting a client-supplied system message. Token counting uses `llama-server`'s `/tokenize` endpoint with a chars/4 fallback. No retrieval, no embedding model — the profile fits in context whole.

**Tech Stack:** Python 3.10, FastAPI, httpx, Streamlit, llama.cpp server. No new dependencies.

## Global Constraints

- **No new dependencies.** Everything here uses stdlib plus `httpx`, already in use.
- **No test framework.** This repo has zero tests and no pytest dependency. Checks follow the existing repo habit: an `if __name__ == "__main__":` block with plain `assert`s, matching `cookbook/probe.py`, `cookbook/download.py`, `runtime/model.py`, `runtime/llamacpp.py`.
- **Never edit `data/character.md` or `data/sources.md`.** They are the creator's files. Citation stripping happens in memory at assembly time. `data/` is gitignored and must stay that way.
- **Fixtures use invented placeholder content only.** No real name, trait, quote, or redacted value from the profile may appear in code, comments, docs, or commit messages — CLAUDE.md forbids instance details in tracked files, and a test fixture is a tracked file. The bible and the source log are the only places that content lives. When a check needs the real profile, call `load_profile()` and assert on a property (no `[S-` survives) rather than pasting an excerpt.
- **Never commit creator data.** `git add` exact paths only — never `git add -A`, never `git add data/`.
- **The module adds framing, never policy.** Behavioural rules live in `character.md` §10 and arrive with the profile. Inventing rules in code is the transcriber authoring the character, which CLAUDE.md forbids.
- **Python is pinned `>=3.10,<3.11`.** No `match` statements beyond 3.10, no 3.11+ stdlib.
- Run commands from the repo root: `C:\Users\yaghm\Desktop\projects\self_presentation_AI`.

---

## File Structure

| File | Responsibility |
|---|---|
| `runtime/bible.py` (create) | Load, slice, strip, frame, count, budget, assemble. The only new file. |
| `runtime/backend.py` (modify) | Add `count_tokens()` to `LocalBackend` via `/tokenize`. |
| `runtime/__init__.py` (modify) | Export the new public names. |
| `service/main.py` (modify) | Prepend persona server-side; reject client system messages unless the override flag is set. |
| `runtime/chat_app.py` (modify) | Stop sending a system prompt; show the debug box only under the flag. |
| `cookbook/fit.py` (modify) | Replace the hardcoded `BIBLE_TOKENS` with a per-surface measurement. |

---

### Task 1: Load, slice, strip

**Files:**
- Create: `runtime/bible.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PROFILE_PATH: Path` — `REPO_ROOT / "data" / "character.md"`
  - `class ProfileMissing(FileNotFoundError)`
  - `def load_profile(path: Path | None = None) -> str`
  - `def slice_profile(text: str) -> str`
  - `def strip_cites(text: str) -> str`

**Context the implementer needs:**

`data/character.md` is 332 lines. Line 42 is `# CHARACTER` — everything before it ("How this file works", canon rules, the update loop) is instructions to the humans maintaining the file. Line 318 is `## Changelog` — bookkeeping. Only the span between them is bot-facing.

Citations look like `` `[S-055]` `` — backtick-wrapped, and they come in five shapes: single, comma-separated pairs, triples, one five-cite group, and two with a mangled separator. 222 total. Stripping the brackets without the backticks leaves orphan `` ` `` characters in the prompt.

`(tentative)` markers stay. CLAUDE.md: *"(tentative) = single-sourced... This later tells the bot how firmly to assert something."* They carry meaning the bot should honour — do not strip them.

- [ ] **Step 1: Write the failing self-check**

Create `runtime/bible.py` with only the self-check block:

```python
"""Assembles the system prompt the audience-facing bot runs on.

The fan surface reads `data/character.md` and nothing else. `sources.md` is the
creator's unedited answers and stays admin-only — a retrieval hit there would
surface a whole entry to a stranger.

The profile body is ~7.8k tokens, so it goes into context whole. No retrieval,
no embedding model, no chunking. When it eventually outgrows the budget, see
`assemble()` — it refuses loudly rather than truncating the persona, because a
prompt that loses §10 is a bot that fabricates.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "data" / "character.md"


class ProfileMissing(FileNotFoundError):
    pass


def _self_check() -> None:
    sample = (
        "# Placeholder — Character Profile\n"
        "## How this file works\n"
        "Meta instructions the model must never see.\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n"
        "- **Three words:** kind `[S-003, S-023, S-024]`, expressive `[S-014]`\n"
        "- Something single-sourced (tentative) `[S-099]`\n"
        "## Changelog\n"
        "- v1 bookkeeping nobody should read\n"
    )

    sliced = slice_profile(sample)
    assert sliced.startswith("# CHARACTER"), sliced[:40]
    assert "How this file works" not in sliced
    assert "bookkeeping" not in sliced

    stripped = strip_cites(sliced)
    assert "[S-" not in stripped, stripped
    assert "`" not in stripped, "orphan backticks left behind: " + stripped
    assert "(tentative)" in stripped, "tentative markers must survive"
    assert "kind," in stripped, stripped

    print("bible self-check: ok")


if __name__ == "__main__":
    _self_check()
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m runtime.bible
```

Expected: `NameError: name 'slice_profile' is not defined`.

- [ ] **Step 3: Write the minimal implementation**

Insert above `_self_check`:

```python
import re

PROFILE_START = "# CHARACTER"
PROFILE_END = "## Changelog"

# Cites are backtick-wrapped and come in several shapes — `[S-004]`,
# `[S-004, S-007]`, and two with a mangled separator. Match anything between
# the brackets, and take the backticks with it or the prompt keeps the quotes
# with nothing inside them.
CITE = re.compile(r"[ \t]*`?\[S-[^\]]*\]`?")


def load_profile(path: Path | None = None) -> str:
    path = path or PROFILE_PATH
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProfileMissing(
            f"{path} does not exist — the fan surface has no character to be. "
            "Fill it in from templates/character.template.md, or run /add."
        ) from exc


def slice_profile(text: str) -> str:
    """Just the bot-facing span. Everything before `# CHARACTER` explains the
    file to the humans maintaining it, and the changelog is bookkeeping."""
    start = text.find(PROFILE_START)
    if start == -1:
        raise ValueError(f"{PROFILE_START!r} not found — is this a character profile?")
    end = text.find(PROFILE_END, start)
    body = text[start:end] if end != -1 else text[start:]
    return body.strip()


def strip_cites(text: str) -> str:
    """Citations are the audit trail, not something a fan should read. They stay
    in the file; they never reach a prompt."""
    return CITE.sub("", text)
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m runtime.bible
```

Expected: `bible self-check: ok`

- [ ] **Step 5: Verify against the real profile**

```bash
python -c "from runtime.bible import *; t=strip_cites(slice_profile(load_profile())); print(len(t),'chars ~',len(t)//4,'tokens'); assert '[S-' not in t; print(t[:300])"
```

Expected: roughly 30,000 chars / ~7,500 tokens, no `[S-` anywhere, output starting at `# CHARACTER`.

- [ ] **Step 6: Commit**

```bash
git add runtime/bible.py
git commit -m "feat: load and clean the character profile for prompting"
```

---

### Task 2: Token counting

**Files:**
- Modify: `runtime/backend.py` (add a method to `LocalBackend`, near `health()` at line 177)
- Modify: `runtime/bible.py` (add the estimator)

**Interfaces:**
- Consumes: `LocalBackend` — existing code, `runtime/backend.py:59`.
- Produces:
  - `def estimate_tokens(text: str) -> int` in `runtime/bible.py`
  - `LocalBackend.count_tokens(self, text: str) -> int`

**Context the implementer needs:**

`llama-server` exposes `POST /tokenize` taking `{"content": "..."}` and returning `{"tokens": [...]}`. It is served at the **server root**, not under `/v1`. `LocalBackend.base_url` is `http://127.0.0.1:8080/v1`, so the `/v1` suffix has to come off.

Exactness matters here because the number decides whether a prompt is sent or refused. chars/4 is off by 10–20%, which near the boundary is the difference between a working bot and a silently truncated persona. So `/tokenize` is the real path and the estimate is only for when no server is up (status display before load).

- [ ] **Step 1: Write the failing self-check**

Add to `_self_check()` in `runtime/bible.py`, before the `print`:

```python
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens(sliced) > 0
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m runtime.bible
```

Expected: `NameError: name 'estimate_tokens' is not defined`.

- [ ] **Step 3: Implement the estimator**

Add to `runtime/bible.py` after `strip_cites`:

```python
def estimate_tokens(text: str) -> int:
    """Rough count for when no server is up to ask. Off by 10-20%, which is why
    it is never used to decide whether a prompt fits — only to display."""
    return len(text) // 4
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m runtime.bible
```

Expected: `bible self-check: ok`

- [ ] **Step 5: Implement the exact counter**

Add to `LocalBackend` in `runtime/backend.py`, after `health()`:

```python
    def count_tokens(self, text: str) -> int:
        """Exact count from the server that will run the prompt.

        /tokenize lives at the server root, not under /v1, so the suffix comes
        off. Raises rather than guessing: a caller deciding whether a prompt
        fits must not silently fall back to a chars/4 estimate.
        """
        root = self.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{root}/tokenize", json={"content": text})
            response.raise_for_status()
        return len(response.json().get("tokens", []))
```

- [ ] **Step 6: Verify against a running server**

Start the service and load the model, then:

```bash
python -c "
from runtime.backend import LocalBackend
from runtime.bible import strip_cites, slice_profile, load_profile, estimate_tokens
t = strip_cites(slice_profile(load_profile()))
b = LocalBackend()
exact = b.count_tokens(t)
print('exact', exact, 'estimate', estimate_tokens(t), 'error', f'{abs(exact-estimate_tokens(t))/exact:.1%}')
"
```

Expected: an exact count in the 7,000–8,500 range, and an estimate within ~20% of it. If this raises `ConnectError`, the llama-server is not up — start it via the service first.

- [ ] **Step 7: Commit**

```bash
git add runtime/bible.py runtime/backend.py
git commit -m "feat: count prompt tokens exactly via llama-server /tokenize"
```

---

### Task 3: Assembly and the budget

**Files:**
- Modify: `runtime/bible.py`
- Modify: `runtime/__init__.py`

**Interfaces:**
- Consumes: `load_profile`, `slice_profile`, `strip_cites`, `estimate_tokens` (Tasks 1–2); `Message` from `runtime.backend`.
- Produces:
  - `class ProfileTooLarge(RuntimeError)`
  - `def build_persona(path: Path | None = None) -> str`
  - `def assemble(history, context_tokens, count=estimate_tokens, reserve_tokens=1024, persona=None) -> list[Message]`

**Context the implementer needs:**

Three outcomes, from the spec:

| Case | Behaviour |
|---|---|
| Persona + reserve fits | Send whole. |
| Persona alone exceeds budget | Raise `ProfileTooLarge`, naming both numbers. Never truncate. |
| Persona fits, history has outgrown budget | Drop oldest turns until it fits. Keep the system prompt. |

The third is not hypothetical — `chat_app.py` sends unbounded history, so a 16k context with a 7.8k persona breaks at roughly 30 turns.

`reserve_tokens` covers the model's reply. `ChatRequest.max_tokens` defaults to 512 and is capped at 8192; 1024 gives the default case slack. Callers that raise `max_tokens` should raise the reserve to match.

The framing line tells the model it *is* this character. It does **not** state behavioural rules — §10 "Interaction Rules" and "Hard constraints" are already in the profile and arrive with it. The one honesty line included is quoted from CLAUDE.md's fixed bot rule, not invented here.

- [ ] **Step 1: Write the failing self-check**

Add to `_self_check()` before the `print`:

```python
    from .backend import Message

    persona = "PERSONA " + "x " * 100          # ~200 tokens by the estimator
    history = [Message("user", "q " * 50), Message("assistant", "a " * 50)] * 6

    # Fits: system prompt first, every turn kept.
    out = assemble(history, context_tokens=4096, persona=persona)
    assert out[0].role == "system"
    assert out[0].content.startswith("You are")
    assert "PERSONA" in out[0].content
    assert len(out) == len(history) + 1

    # Too small for the persona alone: refuse, do not truncate.
    try:
        assemble(history, context_tokens=100, persona=persona)
    except ProfileTooLarge as exc:
        assert "100" in str(exc), str(exc)
    else:
        raise AssertionError("expected ProfileTooLarge")

    # Persona fits but history does not: oldest turns dropped, system survives.
    trimmed = assemble(history, context_tokens=700, persona=persona)
    assert trimmed[0].role == "system"
    assert len(trimmed) < len(history) + 1
    assert trimmed[-1].content == history[-1].content, "newest turn must survive"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m runtime.bible
```

Expected: `NameError: name 'assemble' is not defined`.

- [ ] **Step 3: Implement**

Add to `runtime/bible.py`. Put the imports at the top of the file with the others:

```python
from typing import Callable

from .backend import Message
```

```python
class ProfileTooLarge(RuntimeError):
    pass


# Framing only. The behavioural rules are the creator's and live in the profile
# itself (§10 Interaction Rules, and Hard constraints). The honesty line is
# CLAUDE.md's fixed bot rule, not something invented here.
FRAMING = (
    "You are the person described in the profile below. Answer as her, in her "
    "voice, using her phrasing.\n"
    "If you are asked something the profile does not cover, say so plainly, in "
    "voice. Never invent a memory, an opinion, an event, or a relationship to "
    "fill a gap.\n\n"
)


def build_persona(path: Path | None = None) -> str:
    return FRAMING + strip_cites(slice_profile(load_profile(path)))


def assemble(
    history: list[Message],
    context_tokens: int,
    count: Callable[[str], int] = estimate_tokens,
    reserve_tokens: int = 1024,
    persona: str | None = None,
) -> list[Message]:
    """The system prompt plus as much recent conversation as fits.

    `count` is injected so this stays a pure function: the service passes the
    backend's exact tokeniser, the self-check passes the estimator.
    """
    persona = build_persona() if persona is None else persona
    budget = context_tokens - reserve_tokens
    persona_tokens = count(persona)

    if persona_tokens >= budget:
        raise ProfileTooLarge(
            f"the profile is {persona_tokens} tokens and the budget is {budget} "
            f"({context_tokens} context minus {reserve_tokens} reserved for the "
            "reply). Raise the context in the stack config, or shorten the "
            "profile with /rebuild. The persona is never truncated — a prompt "
            "that loses the hard constraints is a bot that fabricates."
        )

    # Newest first, keeping turns until the budget is spent, then put them back
    # in order. Oldest context is the cheapest thing to lose.
    remaining = budget - persona_tokens
    kept: list[Message] = []
    for message in reversed(history):
        cost = count(message.content)
        if cost > remaining:
            break
        remaining -= cost
        kept.append(message)
    kept.reverse()

    return [Message("system", persona), *kept]
```

- [ ] **Step 4: Run it to verify it passes**

```bash
python -m runtime.bible
```

Expected: `bible self-check: ok`

- [ ] **Step 5: Export the public names**

In `runtime/__init__.py`, add the import and the `__all__` entries, keeping the list alphabetical as it already is:

```python
from .bible import ProfileMissing, ProfileTooLarge, assemble, build_persona
```

```python
    "ProfileMissing",
    "ProfileTooLarge",
    "assemble",
    "build_persona",
```

- [ ] **Step 6: Verify the package still imports**

```bash
python -c "import runtime; print(sorted(runtime.__all__))"
```

Expected: the list including `ProfileMissing`, `ProfileTooLarge`, `assemble`, `build_persona`. No `ImportError`.

- [ ] **Step 7: Commit**

```bash
git add runtime/bible.py runtime/__init__.py
git commit -m "feat: assemble the system prompt within a hard token budget"
```

---

### Task 4: Wire it into the service, and close the trust boundary

**Files:**
- Modify: `service/main.py` — `ChatRequest` (line 63), `chat()` (line 157), `chat_stream()` (line 181)

**Interfaces:**
- Consumes: `assemble`, `ProfileTooLarge`, `ProfileMissing` from `runtime.bible`.
- Produces: `/chat` and `/chat/stream` that build their own system prompt.

**Context the implementer needs:**

This is the security-relevant task. Today `chat_app.py:164` sends `{"role": "system", "content": system_prompt}` from a text box and `service/main.py:160` forwards whatever arrives. On a deployed fan-facing surface that means any client can replace the persona — including the §10 hard constraints — with one HTTP request.

After this task the persona comes from the file, server-side. A client-supplied system message is **rejected**, not silently dropped, so a misconfigured client is visible rather than quietly unpersonated.

The override is `ALLOW_SYSTEM_PROMPT_OVERRIDE`, default-closed: unset means reject. A deployment that configures nothing is safe.

The model's context budget is `model.context_tokens`, already on the `Model` object from the stack config. The exact counter is `model._backend.count_tokens` — but that private access is one of the audit's findings, so add a small public passthrough on `Model` rather than deepening it.

- [ ] **Step 1: Add the token-counter passthrough to Model**

In `runtime/model.py`, after `stream()` (line 179):

```python
    def count_tokens(self, text: str) -> int:
        """Exact count from the loaded backend, estimate when nothing is loaded."""
        if self._backend is not None and hasattr(self._backend, "count_tokens"):
            return self._backend.count_tokens(text)
        from .bible import estimate_tokens

        return estimate_tokens(text)
```

- [ ] **Step 2: Reject client system messages**

In `service/main.py`, add near the top with the other imports:

```python
from runtime.bible import ProfileMissing, ProfileTooLarge, assemble
```

Add after the `_require_loaded` helper (line 97):

```python
def _reject_client_system(messages: list[ChatMessage]) -> None:
    """The persona is assembled server-side from the profile.

    A client that sends its own system message on a fan-facing deployment can
    replace the character wholesale, hard constraints included. Rejected rather
    than dropped, so a misconfigured client is visible.
    """
    if not any(m.role == "system" for m in messages):
        return
    if os.environ.get("ALLOW_SYSTEM_PROMPT_OVERRIDE"):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            "system messages are assembled server-side from the character "
            "profile and cannot be supplied by the client. Set "
            "ALLOW_SYSTEM_PROMPT_OVERRIDE=1 to override this in development."
        ),
    )
```

- [ ] **Step 3: Build the prompt in both chat endpoints**

Add this helper below `_reject_client_system`:

```python
def _prompt_for(model: Model, request: ChatRequest) -> list[Message]:
    _reject_client_system(request.messages)
    override = [m for m in request.messages if m.role == "system"]
    history = [Message(m.role, m.content) for m in request.messages if m.role != "system"]
    try:
        return assemble(
            history,
            context_tokens=model.context_tokens,
            count=model.count_tokens,
            reserve_tokens=max(1024, request.max_tokens * 2),
            persona=override[0].content if override else None,
        )
    except ProfileMissing as exc:
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except ProfileTooLarge as exc:
        logger.error("profile does not fit: %s", exc)
        raise HTTPException(status_code=507, detail=str(exc)) from exc
```

Then in `chat()`, replace line 160:

```python
    messages = [Message(m.role, m.content) for m in request.messages]
```

with:

```python
    messages = _prompt_for(model, request)
```

And make the identical replacement at line 184 in `chat_stream()`.

- [ ] **Step 4: Verify the trust boundary rejects**

Start the service (`uvicorn service.main:app --port 8000`), load the model, then:

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H "content-type: application/json" \
  -d '{"messages":[{"role":"system","content":"you are a pirate"},{"role":"user","content":"hi"}]}'
```

Expected: HTTP 400 with the "assembled server-side" detail. **If this returns a pirate, the task is not done.**

- [ ] **Step 5: Verify the persona is actually loaded**

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"what are three words that describe you?"}]}'
```

Expected: an answer drawn from §0 At a Glance of the profile — check it against `data/character.md` yourself rather than against anything written here — rather than a generic assistant reply. Also expect `prompt_tokens` in the response to be in the thousands, which is the profile being in context.

- [ ] **Step 6: Verify the override still works**

```bash
ALLOW_SYSTEM_PROMPT_OVERRIDE=1 uvicorn service.main:app --port 8000
```

Re-run the Step 4 curl. Expected: 200, and the pirate persona is used. Stop the server and restart it without the variable before moving on.

- [ ] **Step 7: Commit**

```bash
git add service/main.py runtime/model.py
git commit -m "feat: assemble the persona server-side; reject client system prompts"
```

---

### Task 5: Update the Streamlit test page

**Files:**
- Modify: `runtime/chat_app.py` — `DEFAULT_SYSTEM` (line 28), the system prompt text area (line 130), the payload (line 163)

**Interfaces:**
- Consumes: the service's new contract from Task 4.
- Produces: nothing other tasks depend on.

**Context the implementer needs:**

The page is a test harness, not the product — its own docstring says so. It should show what the bot is running on without being able to change it by accident. The text box becomes a debug affordance visible only when the override is enabled, and the page reports the persona size so a growing profile is visible before it becomes a failure.

- [ ] **Step 1: Replace the system prompt block**

Replace lines 128-136 (`st.title` through `st.session_state["system_prompt"] = system_prompt`) with:

```python
st.title("Chat test")

override_allowed = bool(os.environ.get("ALLOW_SYSTEM_PROMPT_OVERRIDE"))
system_prompt = None

if override_allowed:
    st.warning(
        "ALLOW_SYSTEM_PROMPT_OVERRIDE is set — this page can replace the "
        "character. Unset it to test what a deployment actually serves."
    )
    system_prompt = st.text_area(
        "System prompt override (debug)",
        value=st.session_state.get("system_prompt", ""),
        height=110,
        help="Leave empty to use the assembled profile.",
    )
    st.session_state["system_prompt"] = system_prompt
else:
    st.caption(
        "Persona is assembled server-side from data/character.md. "
        "The service rejects client-supplied system prompts."
    )
```

- [ ] **Step 2: Delete the now-unused default**

Remove the `DEFAULT_SYSTEM` constant at lines 28-32. Nothing else references it after Step 1.

- [ ] **Step 3: Update the payload**

Replace the `payload` assignment (line 163):

```python
    payload = {
        "messages": [{"role": "system", "content": system_prompt}, *st.session_state["history"]],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": thinking,
    }
```

with:

```python
    messages = list(st.session_state["history"])
    if override_allowed and system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": thinking,
    }
```

- [ ] **Step 4: Verify the page**

```bash
streamlit run runtime/chat_app.py
```

Expected: no system prompt box, a caption saying the persona is server-side, and a working conversation where she answers in character. Ask "what are three words that describe you?" and check the answer matches §0.

- [ ] **Step 5: Commit**

```bash
git add runtime/chat_app.py
git commit -m "feat: drop the client system prompt from the test page"
```

---

### Task 6: Correct the fitter's bible constant and re-cut the config

**Files:**
- Modify: `cookbook/fit.py` — `BIBLE_TOKENS` (line 22-23), `strategy_for` (line 158)
- Regenerate: `config/stack.user.json` (via the cookbook UI, not by hand)

**Interfaces:**
- Consumes: nothing from earlier tasks. Deliberately — see the note on layering below.
- Produces: `def bible_tokens(surface: Surface = "user") -> int`, `def _measure(path: Path, fallback: int) -> int`, and a `strategy_for` that now takes a surface.

**Context the implementer needs:**

`fit.py:23` hardcodes `BIBLE_TOKENS = 23_000`, the size of both files together. With fans on profile-only that is wrong for the user surface, and it has been making the fitter buy a 32k context — and therefore a smaller model — to hold something the fan side never loads.

**`cookbook/` must not import from `runtime/`.** The dependency runs the other way: `runtime/model.py` imports `cookbook.config`, and the cookbook ships as a standalone install (`pyproject.toml` packages `cookbook` only). Duplicating a two-line `len(text) // 4` is correct here; importing across the layer would create a cycle.

The repo ships templates and `data/` may be absent, so measurement falls back to the current constants when the files are not there.

- [ ] **Step 1: Replace the constant**

In `cookbook/fit.py`, replace lines 22-23:

```python
# The bible as it stands: character.md ~8.4k + sources.md ~15k.
BIBLE_TOKENS = 23_000
```

with:

```python
# What each surface has to hold in context.
#
# The fan surface reads the profile only — `sources.md` is the creator's
# unedited answers and stays admin-side. That halves the context the user stack
# has to buy, and context is paid for in KV cache, which is paid for in model
# size.
#
# Measured from the real files when they exist; the repo ships templates and
# `data/` may be absent. Deliberately not imported from `runtime` — the cookbook
# installs standalone and `runtime` already depends on it.
DEFAULT_PROFILE_TOKENS = 8_000
DEFAULT_SOURCES_TOKENS = 15_000

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def bible_tokens(surface: Surface = "user") -> int:
    """Tokens of bible the given surface must hold."""
    profile = _measure(DATA_DIR / "character.md", DEFAULT_PROFILE_TOKENS)
    if surface != "admin":
        return profile
    return profile + _measure(DATA_DIR / "sources.md", DEFAULT_SOURCES_TOKENS)


def _measure(path: Path, fallback: int) -> int:
    try:
        return len(path.read_text(encoding="utf-8")) // 4
    except OSError:
        return fallback
```

Add `from pathlib import Path` to the imports at the top of the file.

- [ ] **Step 2: Make `strategy_for` surface-aware**

Replace `strategy_for` (lines 158-160):

```python
def strategy_for(context_tokens: int) -> Strategy:
    needed = BIBLE_TOKENS + CONVERSATION_RESERVE_TOKENS
    return "whole-bible" if context_tokens >= needed else "retrieval"
```

with:

```python
def strategy_for(context_tokens: int, surface: Surface = "user") -> Strategy:
    needed = bible_tokens(surface) + CONVERSATION_RESERVE_TOKENS
    return "whole-bible" if context_tokens >= needed else "retrieval"
```

Then update its one caller, `evaluate()` at line 233:

```python
    strategy = strategy_for(context_tokens, selection.surface)
```

- [ ] **Step 3: Fix the import in the Streamlit app**

`cookbook/app.py:22` imports `BIBLE_TOKENS`, which no longer exists. Change the import to `bible_tokens`, and replace its use at lines 281-284:

```python
        st.caption(
            f"The bible is ~{BIBLE_TOKENS:,} tokens. It goes in whole above "
            f"{BIBLE_TOKENS + CONVERSATION_RESERVE_TOKENS:,}; below that, retrieval."
        )
```

with:

```python
        needed = bible_tokens(surface)
        st.caption(
            f"The {surface} surface holds ~{needed:,} tokens of bible. It goes "
            f"in whole above {needed + CONVERSATION_RESERVE_TOKENS:,}; below "
            f"that, retrieval."
        )
```

- [ ] **Step 4: Verify the numbers changed the way you expect**

```bash
python -c "
from cookbook.fit import bible_tokens, strategy_for
print('user ', bible_tokens('user'))
print('admin', bible_tokens('admin'))
print('user at 8192 :', strategy_for(8192, 'user'))
print('user at 16384:', strategy_for(16384, 'user'))
print('admin at 16384:', strategy_for(16384, 'admin'))
"
```

Expected: user ~8,400; admin ~23,400; user at 8192 `retrieval`; user at 16384 `whole-bible`; admin at 16384 `retrieval`.

- [ ] **Step 5: Re-cut the user config**

```bash
streamlit run cookbook/app.py
```

Choose the **User** surface, Auto mode, and confirm a row with **16,384 context**. Press the write button. Do not hand-edit `config/stack.user.json` — its own `_warning` says to re-run rather than edit, and a hand edit desyncs it from the fit that produced it.

Verify:

```bash
python -c "
import json; c=json.load(open('config/stack.user.json'))
print(c['context_tokens'], c['bible_strategy'], c['roles']['llm']['model_id'])
assert c['context_tokens'] >= 16384
assert c['bible_strategy'] == 'whole-bible'
print('ok')
"
```

- [ ] **Step 6: Delete the stale pre-surface config**

`config/stack.json` predates the surface split (written 20:05; `stack.user.json` at 21:48) and nothing reads it — `config_path()` only ever builds `stack.<surface>.json`. Confirm, then remove:

```bash
grep -rn "stack.json" cookbook runtime service --include=*.py
rm config/stack.json
```

Expected from the grep: only the `**/stack.json` line in `.gitignore` and comments. If any code reads it, stop and report instead of deleting.

- [ ] **Step 7: End-to-end**

Restart the service so it picks up the new context, load the model, and confirm in the Streamlit chat page that she answers in character and `prompt_tokens` lands around 7,500–8,500.

- [ ] **Step 8: Commit**

```bash
git add cookbook/fit.py cookbook/app.py
git commit -m "fix: measure bible size per surface instead of assuming both files"
```

---

## Two places this plan deviates from the spec

Both were decided while writing the tasks. Flagged rather than buried.

**1. `/tokenize` unreachable raises instead of estimating.** The spec said fall back to a chars/4 estimate and label it. But the count decides whether a prompt is sent or refused, and chars/4 is off by 10–20% — near the boundary that is exactly the difference between a working bot and a silently truncated persona, which is the failure this whole design exists to prevent. So `LocalBackend.count_tokens` raises, and the estimate is used only where nothing is being decided: `Model.count_tokens` when no backend is loaded at all, and the self-check. Say the word if you want the spec's version.

**2. `CORE_SECTIONS` is not built.** The spec had `bible.py` expose §0/§6/§10 now for the growth branch to use later. Nothing consumes it, and an unused constant that encodes a guess about a retriever that does not exist is the kind of thing that rots. The section boundaries are in the file itself, so building it when the branch is built costs nothing extra.

## Notes for whoever executes this

- `config/`, `data/`, and `models/` are gitignored. No task commits them. If `git status` shows any of them staged, something is wrong — unstage before committing.
- `service/` is not in `.gitignore`'s whitelist, so `git add service/main.py` in Task 4 will silently add nothing. Check `git status` after staging; if `service/main.py` does not appear, add `!service/**` to the "Application code" block in `.gitignore` alongside `!cookbook/**` and `!runtime/**` — it holds no creator data. Raise it rather than working around it.
- Tasks 1–3 need no model running. Tasks 4–6 need the service up and a model loaded.
