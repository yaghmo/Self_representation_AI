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

SERVICE_URL = os.environ.get("SERVICE_URL", "http://127.0.0.1:8000")

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

    # The service pins its surface from SURFACE in its own environment, so the
    # page asks for one only when the service is willing to be told.
    surface = (
        st.radio("Surface", ["user", "admin"], horizontal=True)
        if os.environ.get("ALLOW_SURFACE_OVERRIDE")
        else None
    )
    surface_param = {"surface": surface} if surface else {}

    try:
        status = get("/model", **surface_param).json()
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    if "detail" in status and "name" in status:
        st.write(f"**{status['name']}**")
        st.caption(
            f"{status['surface']} surface · {status['source']} · "
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
                response = post("/model/load", surface_param, timeout=330.0)
            if response.status_code >= 400:
                st.error(response.json().get("detail", response.text))
            else:
                st.session_state["load_seconds"] = time.time() - started
                st.rerun()

    if st.session_state.get("load_seconds"):
        st.caption(f"loaded in {st.session_state['load_seconds']:.1f}s")

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

if prompt:
    if not ready:
        st.warning("Model is not loaded — press Load model in the sidebar.")
        st.stop()

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
