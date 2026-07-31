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

from runtime.backend import Message
from runtime.model import Model, ModelNotDownloaded
from service.logging_config import setup_logging

logger = setup_logging("service")

# One model per process. Concurrency comes from llama-server, not from loading
# the weights twice.
_model: Model | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service starting (surface=%s)", os.environ.get("SURFACE", "user"))
    yield
    global _model
    if _model is not None:
        logger.info("shutting down — unloading model")
        _model.unload()
    logger.info("service stopped")


app = FastAPI(title="Character chat service", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------ schemas --


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = Field(default=512, ge=1, le=8192)
    thinking: bool = False


class ChatResponse(BaseModel):
    content: str
    reasoning: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LoadRequest(BaseModel):
    surface: str = Field(default="user", pattern="^(user|admin)$")
    port: int = Field(default=8080, ge=1024, le=65535)


# -------------------------------------------------------------------- model --


def _get_model(surface: str = "user", port: int = 8080) -> Model:
    global _model
    if _model is None or _model.surface != surface:
        logger.info("resolving model for surface=%s", surface)
        _model = Model.from_config(surface, port=port)
        logger.info("resolved %s", _model.name)
    return _model


def _require_loaded() -> Model:
    if _model is None or not _model.loaded:
        raise HTTPException(status_code=409, detail="no model loaded — POST /model/load first")
    return _model


# ---------------------------------------------------------------- endpoints --


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_loaded": _model.loaded if _model else False,
        "model": _model.name if _model else None,
    }


@app.get("/model")
def model_status(surface: str = "user") -> dict:
    try:
        return _get_model(surface).status()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("status failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/model/load")
def model_load(request: LoadRequest) -> dict:
    try:
        model = _get_model(request.surface, request.port)
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
    messages = [Message(m.role, m.content) for m in request.messages]
    try:
        content = model.chat(
            messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            thinking=request.thinking,
        )
    except Exception as exc:
        logger.exception("chat failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    backend = model._backend
    return ChatResponse(
        content=content,
        reasoning=getattr(backend, "last_reasoning", ""),
        prompt_tokens=getattr(backend, "last_usage", None).prompt_tokens if backend else 0,
        completion_tokens=getattr(backend, "last_usage", None).completion_tokens if backend else 0,
    )


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    model = _require_loaded()
    messages = [Message(m.role, m.content) for m in request.messages]

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
