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

import os
import time

import httpx
import streamlit as st

from runtime.agent import resumed, run as run_agent
from runtime.backend import Message
from runtime.tools import StaleProposal, list_backups, restore_backup
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


def stream_reply(payload: dict):
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)) as client:
        with client.stream("POST", f"{SERVICE_URL}/chat/stream", json=payload) as response:
            response.raise_for_status()
            for piece in response.iter_text():
                if piece:
                    yield piece


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
        st.session_state["resume"] = True
        st.session_state["resume_note"] = note
        st.session_state["history"].append({"role": "user", "content": shown})
        st.rerun()

    left, right = st.columns(2)
    if left.button("Apply", type="primary", width="stretch"):
        try:
            path = proposal.apply()
        except StaleProposal as exc:
            # The file moved under the proposal. Never merge, never overwrite —
            # the creator re-asks and the agent re-reads.
            resolved(f"not applied — {exc}", f"[not applied: {exc}]")
        st.session_state["applied_note"] = f"Wrote {path} (snapshot in data/.backups/)"
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
    st.session_state["history"] = []

columns = st.columns([1, 1, 6])
if columns[0].button("Clear"):
    st.session_state["history"] = []
    st.rerun()
columns[1].caption(f"{len(st.session_state['history'])} turns")

for message in st.session_state["history"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

ready = bool(health.get("model_loaded"))
prompt = st.chat_input("Say something" if ready else "Load the model first")

# Applying or declining a proposal hands the turn back to the agent: the /add
# procedure does not end at the source entry, it ends with the profile sections
# that entry feeds. Without this the loop stops at the write and the creator has
# to prompt again to get the second half of a procedure already underway.
resume = bool(st.session_state.pop("resume", False))

if prompt or resume:
    if not ready:
        st.warning("Model is not loaded — press Load model in the sidebar.")
        st.stop()

    if prompt:
        # Typing instead of deciding abandons the paused turn — the proposal it
        # was waiting on is stale the moment the conversation moves on.
        st.session_state.pop("pending_step", None)
        st.session_state.pop("pending", None)
        st.session_state["history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

    messages = list(st.session_state["history"])
    if override_allowed and system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": thinking,
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
                },
            )
            response.raise_for_status()
            return response.json()

        paused = st.session_state.pop("pending_step", None) if resume else None
        if paused is not None:
            # Continue the paused turn: the model's own tool call is still in
            # that history, and this closes it with what the creator decided.
            history = resumed(paused, st.session_state.pop("resume_note", "applied"))
        else:
            history = [Message(m["role"], m["content"]) for m in st.session_state["history"]]
        reply = ""
        with st.chat_message("assistant"):
            try:
                for step in run_agent(post_turn, history):
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
            st.session_state["history"].append({"role": "assistant", "content": reply})
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

        st.session_state["history"].append({"role": "assistant", "content": reply})

if st.session_state.get("applied_note"):
    st.success(st.session_state.pop("applied_note"))

pending = st.session_state.get("pending")
if pending is not None:
    confirm_dialog(pending)
