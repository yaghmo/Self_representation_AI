"""FastAPI backend. Owns the model; everything else is a client.

    uvicorn service.main:app --port 8000

This process is the only one that touches CUDA, NVML, or a llama-server
subprocess. That separation is not decoration: running the model inside the
Streamlit process crashed it with a heap corruption in ntdll (0xc0000374),
because a UI that reruns its whole script on every keystroke has no business
holding a CUDA context.

Endpoints are deliberately few:

    GET  /health         is the service up, is a model loaded
    GET  /model          status and placement, without loading anything
    POST /model/load     start llama-server (slow, idempotent)
    POST /model/unload   stop it and free the VRAM
    POST /chat           one completion
    POST /chat/stream    the same, as a token stream
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cookbook.config import read_config
from runtime.backend import Message
from runtime.bible import (
    MessageTooLarge,
    ProcedureMissing,
    ProfileMissing,
    ProfileTooLarge,
    assemble,
    build_persona,
    build_procedure,
)
from runtime.model import Model, ModelNotDownloaded
from service.logging_config import setup_logging

logger = setup_logging("service")

# One model per process. Concurrency comes from llama-server, not from loading
# the weights twice.
_model: Model | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = read_config() or {}
    logger.info("service starting (agent=%s)", config.get("agent", False))
    yield
    global _model
    if _model is not None:
        logger.info("shutting down — unloading model")
        _model.unload()
    logger.info("service stopped")


app = FastAPI(title="Character chat service", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------ schemas --


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


class LoadRequest(BaseModel):
    port: int = Field(default=8080, ge=1024, le=65535)


# -------------------------------------------------------------------- model --


def _get_model(port: int = 8080) -> Model:
    global _model
    if _model is None:
        logger.info("resolving model")
        _model = Model.from_config(port=port)
        logger.info("resolved %s", _model.name)
    return _model


def _require_loaded() -> Model:
    if _model is None or not _model.loaded:
        raise HTTPException(status_code=409, detail="no model loaded — POST /model/load first")
    return _model


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


# ---------------------------------------------------------------- endpoints --


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_loaded": _model.loaded if _model else False,
        "model": _model.name if _model else None,
    }


@app.get("/model")
def model_status() -> dict:
    try:
        return _get_model().status()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("status failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/model/load")
def model_load(request: LoadRequest) -> dict:
    try:
        model = _get_model(request.port)
        if model.loaded:
            logger.info("load requested but %s is already loaded", model.name)
            return {"status": "already-loaded", **model.status()}

        logger.info("loading %s ...", model.name)
        model.load(wait_seconds=300)
        logger.info("loaded %s", model.name)
        return {"status": "loaded", **model.status()}

    except ModelNotDownloaded as exc:
        logger.error("weights missing: %s", exc)
        raise HTTPException(status_code=424, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("load failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/model/unload")
def model_unload() -> dict:
    global _model
    if _model is None or not _model.loaded:
        return {"status": "not-loaded"}
    name = _model.name
    _model.unload()
    logger.info("unloaded %s", name)
    return {"status": "unloaded", "model": name}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    model = _require_loaded()
    messages = _prompt_for(model, request)
    try:
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
    return ChatResponse(
        content=content,
        reasoning=getattr(backend, "last_reasoning", ""),
        tool_calls=getattr(backend, "last_tool_calls", []) or [],
        prompt_tokens=getattr(backend, "last_usage", None).prompt_tokens if backend else 0,
        completion_tokens=getattr(backend, "last_usage", None).completion_tokens if backend else 0,
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    model = _require_loaded()
    if request.tools:
        raise HTTPException(
            status_code=400,
            detail="tool calls are not streamed — use POST /chat in agent mode",
        )
    messages = _prompt_for(model, request)

    def generate():
        try:
            for piece in model.stream(
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                thinking=request.thinking,
            ):
                yield piece
        except Exception as exc:
            logger.exception("stream failed")
            # The response has already begun, so the error has to travel inline.
            yield f"\n\n[stream error: {exc}]"

    # Plain text rather than SSE: the only consumer is our own UI, and SSE
    # framing would be two layers of encoding for no benefit.
    return StreamingResponse(generate(), media_type="text/plain")


def _self_check() -> None:
    """The trust boundary, without weights.

    A fake model stands in for the real one — persona assembly only needs
    `context_tokens` and `count_tokens`, and `chat()` is never reached on the
    rejection cases. Run it with `python -m service.main`.
    """
    global _model
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    seen: dict = {}

    def record(messages, **kwargs) -> str:
        seen["messages"] = messages
        return "ok"

    _model = SimpleNamespace(
        loaded=True,
        agent=False,
        context_tokens=32768,
        count_tokens=lambda text: len(text) // 4,
        chat=record,
        _backend=None,
    )
    client = TestClient(app)
    pirate = [
        {"role": "system", "content": "you are a pirate"},
        {"role": "user", "content": "hi"},
    ]

    # A client-supplied system message is refused, not quietly dropped.
    response = client.post("/chat", json={"messages": pirate})
    assert response.status_code == 400, (response.status_code, response.text)
    assert "assembled server-side" in response.json()["detail"], response.text

    # ...unless the deployment opted in. Default-closed means unset rejects.
    os.environ["ALLOW_SYSTEM_PROMPT_OVERRIDE"] = "1"
    try:
        response = client.post("/chat", json={"messages": pirate})
    finally:
        del os.environ["ALLOW_SYSTEM_PROMPT_OVERRIDE"]
    assert response.status_code == 200, (response.status_code, response.text)
    assert seen["messages"][0].content == "you are a pirate", seen["messages"][0]

    # An ordinary turn gets the file-derived persona prepended, cites stripped.
    # Skipped on a clone with no data/ — the 424 is the correct answer there.
    seen.clear()
    response = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    if response.status_code == 424:
        print("service self-check: ok (no data/character.md — persona checks skipped)")
        return
    assert response.status_code == 200, (response.status_code, response.text)
    messages = seen["messages"]
    assert messages[0].role == "system", messages[0]
    assert messages[0].content.startswith("You are the person described"), messages[0].content[:60]
    assert "[S-" not in messages[0].content, "citation leaked into the prompt"
    assert "`S-" not in messages[0].content, "citation leaked into the prompt"
    assert messages[-1].content == "hi", messages[-1]

    # Too long to answer is the caller's problem, and says so as 413 rather
    # than surfacing as an unhandled 500.
    response = client.post("/chat", json={"messages": [{"role": "user", "content": "x" * 200_000}]})
    assert response.status_code == 413, (response.status_code, response.text)

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

    print(f"service self-check: ok (persona ~{len(messages[0].content) // 4} tokens by estimate)")


if __name__ == "__main__":
    _self_check()
