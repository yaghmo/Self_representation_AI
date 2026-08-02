# Agent mode: one stack, one flag, a loop with a confirm gate

**Date:** 2026-08-01
**Status:** approved, not yet planned
**Supersedes:** the two-surface stack split (`config/stack.<surface>.json`), and the
per-surface bible sizing added 2026-07-31 in "fan-side prompt assembly" Task 6.

## Why

The user/admin split was built as *two different stacks*: the admin agent needs a
tool-calling model and holds `sources.md` in context, the fan bot needs neither.
That is not what the split is for. It exists for one reason — **a fan must not be
able to trigger the tools that write the bible.**

Everything else the split acquired along the way is incidental, and some of it is
wrong:

- Two stacks mean two configs that must not drift, with nothing enforcing it.
- Sizing the admin context to hold `sources.md` (~15k tokens) assumed the agent
  reads its corpus from context. An agent with tools does not — it searches and
  appends through tool calls, the way a developer works a repo they have not read.
- That assumption was pushing the fitter toward a 32k context, hence a large KV
  cache, hence a smaller model — to hold something the agent never needed in
  context in the first place.

So: one stack, and a boolean that decides whether tools exist.

## Decisions

| Decision | Chosen | Why |
|---|---|---|
| Surface in the fitter | **Deleted** | One stack serves both modes. `Surface` leaves `fit.py`, `schema.py`, `config.py`, `app.py`. |
| Model eligibility | **Always native tool-calling** | Any stack the cookbook writes can serve either mode, so the flag can be flipped without re-fitting or re-downloading. Cost: models without native tool calling leave the catalogue permanently, even for fan-only deployments. |
| The flag | `agent: true\|false` in `config/stack.json` | One source of truth, ships inside the container, set by a checkbox in the cookbook. No env var, no client input. |
| Bible in admin context | **No — tools instead** | `bible_tokens()` loses its surface parameter and returns the profile size for both modes. |
| Admin system prompt | **Assembled server-side** from `.claude/skills/add/SKILL.md` | The client supplies no system message in either mode, so the trust boundary closed in Task 4 stays closed with no exceptions. |
| Write safety | **Confirm before write** | The creator is the sole author of the character. An agent editing the profile unreviewed contradicts the premise of the repo, and `data/` is gitignored so there is no undo. |
| Loop location | **Client-side**, in the admin page | The service never executes a tool and holds no per-turn state. There is no code path from HTTP to `data/`. |
| Toolset shape | **Bible-shaped**, not generic file access | The tools encode the update loop's invariants, so a weak local model's mistakes are bounded by the API rather than by the reviewer's attention. |

## Architecture

```
cookbook  ──writes──>  config/stack.json   { "agent": true|false, ... }
                              │
                              ├──> service:    which system prompt; are tools legal
                              └──> admin page: run the loop or don't

service        passes tools through, returns tool calls, executes nothing
admin page     runs the loop, executes tools against data/, holds the confirm gate
```

A fan-facing deployment ships the service and the fan page. The tool code is never
reachable over HTTP, in any configuration, because the service has no tool
executor to reach.

Two facts about the existing code that this design leans on:

- `runtime/llamacpp.py` already passes `--jinja`, which is what llama-server needs
  to emit tool calls. No change to how the model is served.
- `runtime/backend.py` already carries per-call extras as attributes
  (`last_usage`, `last_reasoning`). Tool calls follow that idiom, so `complete()`
  keeps its signature and no existing caller changes.

## Components

### `cookbook/`

- `schema.py` — delete `for_surface()`. LLM candidates are always filtered to
  `tool_calling == "native"`.
- `fit.py` — `Surface` leaves `Selection` and `evaluate()`. `bible_tokens()` takes
  no argument and measures `data/character.md` only, falling back to
  `DEFAULT_PROFILE_TOKENS` when `data/` is absent. `DEFAULT_SOURCES_TOKENS` is
  deleted with the split that needed it.
- `config.py` — `config_path()` returns `config/stack.json`. `build_config()`
  writes `agent` from the checkbox instead of deriving it from a surface.
- `app.py` — the Surface radio becomes an **Agent mode** checkbox. Same page, one
  fit, one config, either mode.

### `runtime/bible.py`

Gains two functions. `build_persona()` is untouched.

```python
def section_index() -> str          # the "## " headings, ~60 tokens
def build_procedure() -> str        # SKILL.md + section index
```

The index is read live from the profile at assembly time, so it cannot drift from
the file, and it saves a `list_sections()` round trip on every single turn.

### `runtime/tools.py` — new

Pure functions over `data/`. No HTTP, no model, no Streamlit.

```python
search_sources(query, limit=5)        -> list[Entry]      # capped
read_profile_section(heading)         -> str              # one section
append_source(answer, feeds)          -> Proposal
replace_profile_section(heading, txt) -> Proposal
```

Reads return data. **Writes return a `Proposal`** — the diff, plus the write it
*would* perform. Nothing touches disk until `.apply()`, which snapshots the file
to `data/.backups/<name>.<timestamp>` before writing.

Invariants the API enforces, so the model cannot violate them:

- `S-###` is allocated by code from the file. The model never picks an ID, so it
  cannot collide, skip, or reuse one.
- `append_source` appends. There is no tool that edits or deletes an existing
  entry — `sources.md` is structurally append-only.
- `replace_profile_section` can touch exactly one `##` section.
- `search_sources` is capped. `sources.md` is ~15k tokens and dumping it defeats
  the reason it is not in context.

### `runtime/agent.py` — new

The loop, written here, not imported. Takes a `post` callable so it is testable
without a running service.

```
model turn ─> tool calls?
              ├─ read tool  -> run it, result goes back as a `tool` message
              └─ write tool -> yield the Proposal, pause for confirmation
           ─> no tool calls -> that is the answer, stop
```

Terminates on a text answer or an iteration cap.

### `runtime/backend.py`

- `Message` gains optional `tool_calls` and `tool_call_id`.
- `_payload()` passes `tools` when the caller supplies them.
- `LocalBackend.last_tool_calls`, following `last_reasoning`.

### `service/main.py`

- Reads `agent` from the config at startup.
- `_prompt_for()` returns the persona when false, the procedure when true.
- `ChatRequest.tools` is accepted only when `agent` is true; 400 otherwise, the
  same shape as the system-prompt guard.
- `ChatMessage.role` accepts `tool`.
- `ChatResponse.tool_calls`.
- **Deleted:** `_surface()` and the `SURFACE` environment variable. The config key
  replaces them.

### `runtime/chat_app.py`

When `agent` is true, render the loop: tool calls as they happen, and a modal
confirm dialog for every proposed write — the section before beside the section
after, with the unified diff available underneath, and Apply / Decline. A modal
rather than an inline block because an edit to the creator's own record should
interrupt rather than be scrollable past. `Proposal` therefore carries `before`
and `after` — the changed span alone — not only a diff.

## Data flow — one admin turn

```
you    <a new answer from the creator, touching §6>
page   POST /chat  { messages, tools }
svc    system = procedure + section index   -> model
model  tool_calls: search_sources(<topic of the answer>)
page   runs it locally -> 2 entries -> POST /chat with a tool message
model  tool_calls: read_profile_section("6. Voice & Speech Patterns")
page   ~850 tokens back -> POST /chat
model  tool_calls: append_source(...) + replace_profile_section("6", ...)
page   SHOWS DIFF, WAITS
you    Apply
page   snapshot -> write -> tool result -> POST /chat
model  "Logged as S-###, §6 updated."
```

Cost of that turn: the procedure (~4.2k tokens), a capped search result, and one
profile section (~850 tokens) — against ~8.4k for the profile whole and ~15k for
the sources corpus, neither of which is ever loaded.

## Error handling

| Case | Behaviour |
|---|---|
| Malformed or unknown tool call | The error is returned as the tool result, so the model can correct itself |
| Model loops without answering | Iteration cap (8), then stop and return what it has |
| Creator presses Reject | Tool result says the creator declined, so the model does not retry the same edit |
| `tools` sent when `agent` is false | 400, same shape as the system-prompt guard |
| Any write | Snapshot to `data/.backups/` before the file is touched |
| `SKILL.md` missing | 424, same as `ProfileMissing` |
| Profile or message too large | Unchanged — `ProfileTooLarge` 507, `MessageTooLarge` 413 |

## Testing

Self-checks in the module idiom already used by `bible.py` and `service/main.py` —
`assert`-based, runnable with `python -m <module>`, no framework.

- **`tools.py`** on a temporary corpus: `append_source` allocates the next ID and
  leaves every existing entry byte-identical; `replace_profile_section` changes
  one section and no other; `search_sources` respects its cap; `.apply()` writes a
  snapshot first.
- **`agent.py`** with a scripted fake `post`: a tool call followed by a final
  answer. Asserts termination, tool-result shape, the iteration cap, and the
  rejection path.
- **`service/main.py`** — two cases added to the existing `_self_check`: `tools`
  refused when `agent` is false, procedure selected when true.

## Known risk, accepted

The largest profile section is ~7.8k characters. `replace_profile_section` means
the model regenerates ~1,950 tokens of existing cited prose to change one line,
and the creator reviews that diff. If it drifts in practice, the fix is splitting
the section in the profile *format*, not adding a finer-grained tool.

## Out of scope

Deliberately not in this spec. Each is its own design:

- **A. Compact persona + retrieval** — the always-on persona block plus retrieval
  for the rest of the profile. This spec removes the pressure that made it urgent
  but does not build it.
- **B. Summarize on overflow** — today `assemble()` drops the oldest turns
  silently. Unchanged here.
- **C. Conversation persistence and session resume** — depends on B's summarizer.
- **`/rebuild` as an agent tool** — `/add` only for now.
