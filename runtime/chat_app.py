"""Test harness for the chat side. A thin client over the FastAPI service.

    uvicorn service.main:app --port 8000        # backend, owns the model
    streamlit run runtime/chat_app.py           # this

Nothing here imports torch, touches NVML, or spawns a subprocess. That is the
point: when this page owned the model it crashed with a heap corruption in
ntdll, because a script that reruns on every keystroke should not be holding a
CUDA context. All of that now lives behind HTTP.

Deliberately not the product. It exists to answer one question — does she sound
right — so it exposes the knobs that change the answer and shows what the
placement decision was, rather than hiding them behind a pretty surface.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import httpx
import streamlit as st

from runtime.agent import followup, resumed, run as run_agent
from runtime.backend import Message
from runtime.bible import plan_compaction
from runtime import chat_log
from runtime.convert import ConversionFailed, to_markdown
from runtime.embed import EmbeddingNotConfigured, bge_embedder
from runtime.index import all_chunks, build, load_index
from runtime.stories import STORIES_DIR, load_story
from runtime.story_tools import (
    Routing,
    keep_logged,
    parse_story_command,
    propose_addition,
    propose_amendment,
    propose_new_story,
    route,
)
from runtime.tools import (
    FOLLOWUP_SCHEMAS,
    SOURCES_PATH,
    TOOL_SCHEMAS,
    NoChange,
    StaleProposal,
    entry_id_of,
    list_backups,
    restore_backup,
)
from service.logging_config import setup_logging

SERVICE_URL = os.environ.get("SERVICE_URL", "http://127.0.0.1:8000")

# The loop runs in this process, so the tool calls and their results land in
# logs/chat.log while the model's own traffic lands in logs/service.log.
logger = setup_logging("chat")

st.set_page_config(page_title="Chat test", layout="wide")

def get(path: str, **params):
    with httpx.Client(timeout=15.0) as client:
        return client.get(f"{SERVICE_URL}{path}", params=params)


def post(path: str, payload: dict, timeout: float = 330.0):
    with httpx.Client(timeout=timeout) as client:
        return client.post(f"{SERVICE_URL}{path}", json=payload)


def json_block(raw: str) -> dict | None:
    """The ingestion reply as an object, tolerating a ``` fence around it.

    Fence-stripping only. The object still has to parse whole — a reply that
    isn't valid JSON returns None and stops the ingestion, because a story that
    silently lost half its events looks successful and reports nothing.
    """
    for candidate in (raw, raw[raw.find("{") : raw.rfind("}") + 1]):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def stream_reply(payload: dict):
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)) as client:
        with client.stream("POST", f"{SERVICE_URL}/chat/stream", json=payload) as response:
            response.raise_for_status()
            for piece in response.iter_text():
                if piece:
                    yield piece


def add_turn(role: str, content: str) -> None:
    """Append to the live session and the on-disk log in one call.

    Five call sites need this; one place keeps the two from drifting apart.
    """
    st.session_state["history"].append({"role": role, "content": content})
    chat_log.append_turn(st.session_state["chat_log_path"], role, content)


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

    def resolved(note: str, shown: str) -> None:
        """Close the paused tool call with `note`, and show `shown` in the chat.

        `note` goes back as the tool result, so the model reads the outcome of
        the call it actually made — a write that reports itself as a fresh
        user turn is one the model cannot tell apart from a request to write
        again, and that is how one answer becomes two entries.
        """
        st.session_state["pending"] = None
        # Only a tool call has a turn waiting on the answer. A `/story`
        # proposal is composed by this page, not by the model, so there is
        # nothing paused to close — resuming would run the loop over a
        # conversation that never asked it anything.
        st.session_state["resume"] = st.session_state.get("pending_step") is not None
        st.session_state["resume_note"] = note
        add_turn("user", shown)
        st.rerun()

    left, right = st.columns(2)
    if left.button("Apply", type="primary", width="stretch"):
        try:
            path = proposal.apply()
        except StaleProposal as exc:
            # The file moved under the proposal. Never merge, never overwrite —
            # the creator re-asks and the agent re-reads.
            resolved(f"not applied — {exc}", f"[not applied: {exc}]")
        else:
            # Everything below reads `path`, so it belongs to the branch where
            # `path` was bound. `resolved()` does halt — it ends in st.rerun() —
            # but that makes the whole block's safety turn on the last line of
            # a function two screens up. `else` is the same guarantee stated
            # where it can be checked.

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

            # A story's snapshot lands beside the story, not beside the bible, so
            # the note points at the directory that actually holds it.
            st.session_state["applied_note"] = (
                f"Wrote {path} (snapshot in {path.parent}/.backups/)"
            )

            # The index is derived from the files, so it follows the write rather
            # than being written alongside it. `refresh` re-embeds only what
            # changed, which for one approved story is one story.
            if path.parent == STORIES_DIR and st.session_state.get("story_index") is not None:
                index = st.session_state["story_index"]
                index.refresh(all_chunks(), st.session_state["story_embed"])
                index.save()

            # A logged entry is only half the procedure. The entry itself names the
            # sections it feeds, so the second half needs the entry — not the
            # conversation that produced it.
            if path.name == SOURCES_PATH.name and entry_id_of(proposal.after):
                st.session_state["followup_entry"] = proposal.after
            resolved(
                f"applied — {proposal.summary}. This write is done; do not repeat it.",
                f"[applied: {proposal.summary}]",
            )
    if right.button("Decline", width="stretch"):
        resolved(
            f"declined by the creator — {proposal.summary}. Do not retry it.",
            f"[declined: {proposal.summary}]",
        )


# ---------------------------------------------------------------- sidebar ---

with st.sidebar:
    st.header("Service")
    st.caption(SERVICE_URL)

    try:
        health = get("/health").json()
    except Exception as exc:
        st.error(f"Backend unreachable: {exc}")
        st.code("uvicorn service.main:app --port 8000")
        st.stop()

    st.success("Backend up")

    try:
        status = get("/model").json()
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    # Set unconditionally, every rerun, before anything below (the sidebar's
    # own Restore button included) reads it. It used to live inside the
    # `"history" not in st.session_state` guard further down, textually after
    # this read — safe only by accident of today's control flow.
    st.session_state["chat_log_path"] = chat_log.log_path(bool(status.get("agent")))

    if "detail" in status and "name" in status:
        st.write(f"**{status['name']}**")
        st.caption(
            f"{'agent' if status.get('agent') else 'chat'} · {status['source']} · "
            f"context {status['context_tokens']:,} · bible: {status['bible_strategy']}"
        )
        icon = {"gpu": "🟢", "partial": "🟡", "cpu": "🔴"}.get(status.get("mode"), "")
        st.info(f"{icon} {status['detail']}")
        st.caption(f"needs {status.get('vram_needed')} · {status.get('vram_available')} free")
    elif status.get("detail"):
        st.error(status["detail"])
    else:
        st.warning(status.get("placement_error", "no model configured"))

    st.divider()
    st.header("Generation")
    temperature = st.slider("Temperature", 0.0, 1.5, 0.7, 0.05)
    max_tokens = st.slider("Max tokens", 64, 2048, 512, 64)
    use_stream = st.checkbox("Stream", value=True)
    thinking = st.checkbox(
        "Reasoning",
        value=False,
        help=(
            "Qwen3 thinks in a <think> block before answering. Useful for hard "
            "questions, pure latency for a persona chat — and if the budget runs "
            "out mid-thought the answer comes back empty."
        ),
    )

    st.divider()
    if health.get("model_loaded"):
        st.success(f"Loaded: {health.get('model')}")
        if st.button("Unload", width="stretch"):
            post("/model/unload", {})
            st.rerun()
    else:
        if st.button("Load model", type="primary", width="stretch"):
            with st.spinner("Starting llama-server — first load reads several GB from disk"):
                started = time.time()
                response = post("/model/load", {}, timeout=330.0)
            if response.status_code >= 400:
                st.error(response.json().get("detail", response.text))
            else:
                st.session_state["load_seconds"] = time.time() - started
                st.rerun()

    if st.session_state.get("load_seconds"):
        st.caption(f"loaded in {st.session_state['load_seconds']:.1f}s")

    # Undo lives here, not in the tool list. Sources are append-only, so the
    # agent has no way to remove an entry and should not be given one — asked
    # to retract, the right move is a superseding entry or this button.
    if status.get("agent"):
        st.divider()
        st.header("Snapshots")
        snapshots = list_backups()
        if not snapshots:
            st.caption("No snapshots yet — one is taken before every write.")
        else:
            choice = st.selectbox(
                "Roll a file back",
                snapshots,
                format_func=lambda p: p.name,
                help=(
                    "Restores that snapshot over the live file. The text being "
                    "replaced is snapshotted first, so this is reversible too."
                ),
            )
            if st.button("Restore", width="stretch"):
                restored = restore_backup(choice)
                chat_log.clear(st.session_state["chat_log_path"])
                st.session_state["history"] = []
                st.session_state["applied_note"] = (
                    f"Restored {restored} from {choice.name} — chat cleared, since "
                    "the history described a file that no longer says that."
                )
                st.rerun()

# ------------------------------------------------------------------- main ---

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

if "history" not in st.session_state:
    path = st.session_state["chat_log_path"]
    window = int(status.get("history_window", 20))
    turns, summary = chat_log.load_recent(path, window)
    st.session_state["history"] = turns
    if summary:
        st.session_state["summary"] = summary

# `/story` is a write path onto the corpus, so it is loaded only in agent mode
# — the fan surface never reaches an embedder, an index, or a proposal.
#
# This does put sentence-transformers, and therefore torch, in the Streamlit
# process, which the module docstring above deliberately kept out of it. The
# crash that rule came from was a CUDA context in a script that reruns on every
# keystroke; the embedding role is CPU unless the creator configured otherwise,
# and the model is loaded once per session rather than per rerun. If it ever
# does bite, the embedder moves behind the service like the LLM did.
_embed = None
if status.get("agent"):
    if "story_embed" not in st.session_state:
        try:
            st.session_state["story_embed"] = bge_embedder()
        except EmbeddingNotConfigured as exc:
            st.session_state["story_embed"] = None
            st.session_state["story_error"] = str(exc)
        except Exception as exc:  # a torch or weights failure, not a config one
            st.session_state["story_embed"] = None
            st.session_state["story_error"] = f"{type(exc).__name__}: {exc}"
    _embed = st.session_state["story_embed"]

    # The index is derived and small, so a missing file is rebuilt rather than
    # reported: `data/stories/*.md` are the truth and the index follows them.
    # A missing embedder is reported instead of worked around — indexing with a
    # stand-in writes vectors no real query can match, and the corpus would
    # look indexed while retrieving nothing.
    if _embed is not None and "story_index" not in st.session_state:
        story_index = load_index()
        if not story_index.chunks:
            story_index = build(all_chunks(), _embed)
        st.session_state["story_index"] = story_index

columns = st.columns([1, 1, 6])
if columns[0].button("Clear"):
    chat_log.clear(st.session_state["chat_log_path"])
    st.session_state["history"] = []
    for key in ("prompt_floor", "summary", "current_story", "logged_stories"):
        st.session_state.pop(key, None)
    st.rerun()
columns[1].caption(
    f"{len(st.session_state['history'])} turns"
    + (f" · sending {len(st.session_state['history']) - st.session_state.get('prompt_floor', 0)}"
       if st.session_state.get("prompt_floor") else "")
)

for message in st.session_state["history"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

ready = bool(health.get("model_loaded"))
agent_mode = bool(status.get("agent"))

entered = st.chat_input(
    ("Say something, or /story to log one" if agent_mode else "Say something")
    if ready
    else "Load the model first",
    accept_file=agent_mode,
    file_type=["md", "markdown", "txt", "docx", "pdf"],
)
# `accept_file` changes the return type: a bare string without it, a value
# carrying `.text` and `.files` with it.
prompt = getattr(entered, "text", entered) if entered is not None else None
attachments = list(getattr(entered, "files", None) or [])

if st.session_state.get("story_error"):
    st.caption(f"`/story` is unavailable — {st.session_state['story_error']}")

# Applying or declining a proposal hands the turn back to the agent: the /add
# procedure does not end at the source entry, it ends with the profile sections
# that entry feeds. Without this the loop stops at the write and the creator has
# to prompt again to get the second half of a procedure already underway.
resume = bool(st.session_state.pop("resume", False))

# A file has no other consumer on this page, so attaching one means `/story`
# whether or not the command was typed.
story_command = agent_mode and (bool(attachments) or bool(prompt and prompt.startswith("/story")))

if story_command:
    if not ready:
        st.warning("Model is not loaded — press Load model in the sidebar.")
        st.stop()
    if _embed is None:
        st.error(st.session_state.get("story_error", "no embedder — /story is unavailable"))
        st.stop()

    # Same as typing an ordinary message: the paused proposal is stale the
    # moment the conversation moves on.
    for key in ("pending_step", "pending", "followup_active", "seen_calls"):
        st.session_state.pop(key, None)

    text = (prompt or "").removeprefix("/story").strip()
    wanted_id, wanted_event, text = parse_story_command(text)
    for upload in attachments:
        # `to_markdown` reads the file's own bytes, so the upload — a buffer in
        # memory — needs a real path carrying its real suffix.
        handle = tempfile.NamedTemporaryFile(suffix=Path(upload.name).suffix, delete=False)
        failure = ""
        try:
            handle.write(upload.getvalue())
            handle.close()
            text += ("\n\n" if text else "") + to_markdown(Path(handle.name))
        except ConversionFailed as exc:
            failure = str(exc)
        finally:
            handle.close()
            os.unlink(handle.name)
        if failure:
            st.error(failure)
            st.stop()

    if not text.strip():
        st.warning("`/story` needs the narrative — type it after the command, or attach a file.")
        st.stop()

    with st.chat_message("user"):
        st.markdown(f"**/story** — {len(text):,} characters in")

    # The raw text never enters `history`. It is pre-redaction by definition,
    # and history is replayed to the model on every later turn.
    routing = None
    if wanted_id:
        target_path = STORIES_DIR / f"{wanted_id}.md"
        if not target_path.exists():
            # A typo must not silently become a new story.
            st.error(f"No story {wanted_id} in the corpus. Drop the id to log a new story.")
            st.stop()
        story = load_story(target_path)
        if wanted_event:
            # The creator named the paragraph. Nothing is picked by similarity
            # on this path — an event id that does not exist is a typo, and
            # falling back to the nearest match would rewrite a paragraph they
            # did not name.
            if not any(e.id == wanted_event for e in story.events):
                st.error(
                    f"{wanted_id} has no {wanted_event}. Events present: "
                    + (", ".join(e.id for e in story.events) or "none")
                )
                st.stop()
            routing = Routing(branch="amend", story=story, event_id=wanted_event)
            st.caption(f"Rewriting {wanted_id}/{wanted_event} — routing skipped.")
        else:
            # A bare story id is new material for that story. Appending never
            # overwrites the creator's words, so it is what an unqualified id
            # means; `ST-###/E-###` is how they ask for the destructive one.
            routing = Routing(branch="append", story=story)
            st.caption(f"Adding to {wanted_id} — routing skipped.")
    else:
        try:
            routing = route(text, st.session_state["story_index"], _embed)
        except Exception as exc:
            st.error(f"Routing failed — {type(exc).__name__}: {exc}")
    if routing is None:
        st.stop()

    if routing.branch == "duplicate":
        top = routing.runners_up[0]
        st.warning(
            f"Already logged — {top.score:.0%} similar to {top.chunk.key}. Nothing ingested."
        )
        add_turn("user", f"[/story refused as a duplicate of {top.chunk.key}]")
        st.stop()

    existing = ""
    if routing.branch == "amend":
        if not routing.event_id:
            st.error(
                f"{routing.story.id} matched, but no paragraph inside it did — there "
                f"is nothing to amend. Name the paragraph (`/story {routing.story.id}"
                f"/E-001 …`), add it to the story (`/story {routing.story.id} …`), or "
                "let it be its own story by dropping the id."
            )
            st.stop()
        target = next((e for e in routing.story.events if e.id == routing.event_id), None)
        existing = target.text if target else ""
        st.info(f"Amending {routing.story.id}/{routing.event_id} — {routing.story.title}")
        if routing.runners_up:
            st.caption(
                "Other candidates: "
                + ", ".join(f"{h.chunk.story_id} ({h.score:.2f})" for h in routing.runners_up)
            )
    elif routing.branch == "append":
        # No `existing`: nothing in the story is being rewritten, so the
        # ingestion pass has no paragraph to work against.
        st.info(f"Adding to {routing.story.id} — {routing.story.title}")
    else:
        st.info("New story — nothing in the corpus matches this closely.")

    # The creator naming the paragraph is what makes this a merge. A routed
    # amend keeps the segmentation prompt: nothing said the paste is a fragment,
    # and it is often a whole expanded story whose later segments get appended.
    merge = bool(wanted_event)
    with st.spinner("Merging into the paragraph" if merge else "Redacting and segmenting"):
        response = post(
            "/ingest", {"text": text, "existing": existing, "merge": merge}
        )
    if response.status_code >= 400:
        st.error(response.json().get("detail", response.text))
        st.stop()

    raw = response.json()["content"]
    parsed = json_block(raw)
    if parsed is None:
        st.error("The ingestion pass did not return JSON. Nothing ingested.")
        st.code(raw)
        st.stop()

    proposal = None
    try:
        if routing.branch == "amend":
            # `events[0]` is the amended paragraph, redacted, in the creator's
            # phrasing. On a routed amend anything after it is new material in
            # the same paste — appended to the same story rather than dropped,
            # which is what made an amendment look applied while changing
            # nothing. A merge asked for one paragraph and gets no additions:
            # the creator named a paragraph, not a place to grow the story.
            extra = parsed["events"][1:]
            if merge and extra:
                st.caption(
                    f"The pass returned {len(extra)} extra segment(s); a named "
                    "paragraph is rewritten in place, so they were not added."
                )
            proposal = propose_amendment(
                routing.story,
                routing.event_id,
                parsed["events"][0]["text"],
                additions=[] if merge else [(e["title"], e["text"]) for e in extra],
                keywords=parsed.get("keywords", []),
            )
        elif routing.branch == "append":
            # Every segment is new material — none of it replaces anything, so
            # there is no first-segment special case here.
            proposal = propose_addition(
                routing.story,
                [(e["title"], e["text"]) for e in parsed["events"]],
                keywords=parsed.get("keywords", []),
            )
        else:
            proposal = propose_new_story(
                summary=parsed["summary"],
                keywords=parsed.get("keywords", []),
                # Dropped unless the creator's own text said when — the
                # ingestion pass invents periods. See keep_logged.
                logged=keep_logged(parsed.get("logged", ""), text),
                events=[(e["title"], e["text"]) for e in parsed["events"]],
            )
    except NoChange:
        # The ingestion pass handed back the paragraph it was given. Nothing to
        # confirm, and a gate over an empty diff would report a write that never
        # happened.
        where = f"{routing.story.id}/{routing.event_id}" if routing.event_id else routing.story.id
        st.warning(
            f"The redacted text is identical to {where} as it already stands — "
            "nothing ingested. Re-send with the new detail spelled out, or log "
            "it as its own story."
        )
    except Exception as exc:
        st.error(f"The reply parsed but does not fit a story — {type(exc).__name__}: {exc}")
        st.code(raw)
    if proposal is None:
        st.stop()

    # Same gate the bible writes go through. There is no second confirm path.
    st.session_state["pending"] = proposal

elif prompt or resume:
    if not ready:
        st.warning("Model is not loaded — press Load model in the sidebar.")
        st.stop()

    if prompt:
        # Typing instead of deciding abandons the paused turn — the proposal it
        # was waiting on is stale the moment the conversation moves on.
        st.session_state.pop("pending_step", None)
        st.session_state.pop("pending", None)
        st.session_state.pop("followup_active", None)
        st.session_state.pop("seen_calls", None)
        add_turn("user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)

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
            chat_log.append_summary(st.session_state["chat_log_path"], st.session_state["summary"])
            # Those turns are now represented by the summary. Drop them from
            # what is *sent*; `history` keeps them for the visible transcript.
            st.session_state["prompt_floor"] = floor + len(older)
            scoped = [{"role": m.role, "content": m.content} for m in newer]
        else:
            # A failed compaction must not lose history. Keep sending it all
            # and let `assemble()` trim as it did before.
            st.caption("Compaction failed — older turns will be trimmed instead.")

    messages = scoped
    if override_allowed and system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    logged = st.session_state.get("logged_stories", [])
    parts = []
    if logged:
        parts.append("Earlier this session you logged: " + ", ".join(logged) + ".")
    if st.session_state.get("summary"):
        parts.append(st.session_state["summary"])
    summary_note = "\n\n".join(parts)

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": thinking,
        "summary": summary_note,
    }

    if bool(status.get("agent")):
        def post_turn(turn_messages, tools):
            logger.info(
                "turn: %s", " | ".join(f"{m.role}:{len(m.content)}c" for m in turn_messages)
            )
            response = post(
                "/chat",
                {
                    "messages": [m.as_dict() for m in turn_messages],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "thinking": thinking,
                    "tools": tools,
                    "summary": summary_note,
                },
            )
            response.raise_for_status()
            return response.json()

        entry = st.session_state.pop("followup_entry", None) if resume else None
        paused = st.session_state.pop("pending_step", None) if resume else None
        tools = TOOL_SCHEMAS
        if entry:
            # Start clean. The entry carries its own id and the sections it
            # feeds, so the follow-up needs none of the chat that produced it —
            # and stays the same size however long that chat was.
            st.session_state.pop("resume_note", None)
            history = followup(entry)
            # No append_source in this phase: the entry is logged, and the
            # system prompt opens by telling the model to log one.
            tools = FOLLOWUP_SCHEMAS
            st.session_state["followup_active"] = True
            st.session_state["seen_calls"] = {}
            st.caption(f"Updating the profile from {entry_id_of(entry)}")
        elif paused is not None:
            # Continue the paused turn: the model's own tool call is still in
            # that history, and this closes it with what the creator decided.
            history = resumed(paused, st.session_state.pop("resume_note", "applied"))
            # Applying one line of a follow-up resumes the follow-up — the
            # phase, and its tool set, have not changed.
            if st.session_state.get("followup_active"):
                tools = FOLLOWUP_SCHEMAS
        else:
            history = [Message(m["role"], m["content"]) for m in st.session_state["history"]]
        reply = ""
        with st.chat_message("assistant"):
            try:
                # Carried across Applies: each one resumes through a fresh run,
                # and the repeat worth catching is the same write proposed
                # again one click later.
                for step in run_agent(
                    post_turn,
                    history,
                    tools=tools,
                    seen=st.session_state.setdefault("seen_calls", {}),
                ):
                    if step.kind == "tool_call":
                        st.caption(f"{step.name}({step.text})")
                    elif step.kind == "tool_result":
                        with st.expander(f"{step.name} result"):
                            st.code(step.text)
                    elif step.kind == "proposal":
                        st.warning(step.text)
                        st.code(step.proposal.diff, language="diff")
                        st.session_state["pending"] = step.proposal
                        st.session_state["pending_step"] = step
                    elif step.kind == "answer":
                        reply = step.text
                        st.markdown(reply)
                    elif step.kind == "stopped":
                        reply = step.text
                        st.error(reply)
            except Exception as exc:
                st.error(f"{type(exc).__name__}: {exc}")
                st.stop()
        if reply:
            add_turn("assistant", reply)
    else:
        with st.chat_message("assistant"):
            started = time.time()
            try:
                if use_stream:
                    reply = st.write_stream(stream_reply(payload))
                    stats = None
                else:
                    with st.spinner("generating"):
                        response = post("/chat", payload)
                    response.raise_for_status()
                    stats = response.json()
                    reply = stats["content"]
                    st.markdown(reply)
                    if stats.get("reasoning"):
                        with st.expander("reasoning"):
                            st.markdown(stats["reasoning"])
            except Exception as exc:
                st.error(f"{type(exc).__name__}: {exc}")
                st.stop()

            elapsed = time.time() - started
            if stats and stats.get("completion_tokens"):
                rate = stats["completion_tokens"] / elapsed if elapsed else 0
                st.caption(
                    f"{stats['completion_tokens']} tokens in {elapsed:.1f}s "
                    f"({rate:.1f} tok/s) · prompt {stats['prompt_tokens']}"
                )
            else:
                st.caption(f"{elapsed:.1f}s")

        add_turn("assistant", reply)

if st.session_state.get("applied_note"):
    st.success(st.session_state.pop("applied_note"))

pending = st.session_state.get("pending")
if pending is not None:
    confirm_dialog(pending)
