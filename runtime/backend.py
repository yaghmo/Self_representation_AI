"""Talking to a served model.

Local only, on purpose. Hosted-provider adapters (Anthropic, NVIDIA, any
OpenAI-compatible endpoint) were removed for now and will come back as a second
implementation of this same interface — that is why the shape stays generic
rather than hardcoding llama.cpp everywhere.

The protocol spoken here is the OpenAI chat schema, because that is what
llama.cpp's server speaks. When the hosted paths return, they slot in without
touching the caller.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Iterator, Protocol

import httpx

from service.logging_config import get_logger

logger = get_logger("runtime.backend")

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Backend(Protocol):
    name: str

    def complete(self, messages: list[Message], **kwargs) -> str: ...

    def stream(self, messages: list[Message], **kwargs) -> Iterator[str]: ...

    def health(self) -> tuple[bool, str]: ...


@dataclass
class LocalBackend:
    """A llama.cpp server over HTTP."""

    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = ""
    name: str = "llama.cpp"
    temperature: float = 0.7
    max_tokens: int = 512
    # Qwen3 and friends emit a <think> block before answering. llama.cpp splits
    # it into `reasoning_content`, so a thinking model that runs out of tokens
    # mid-thought returns an EMPTY `content` and looks broken. For a persona bot
    # the reasoning is pure latency, so it is off unless asked for.
    thinking: bool = False
    last_usage: Usage = field(default_factory=Usage)
    last_reasoning: str = ""

    def _payload(self, messages: list[Message], stream: bool, **kwargs) -> dict:
        payload = {
            "messages": [m.as_dict() for m in messages],
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": stream,
        }
        if self.model:
            payload["model"] = self.model
        if not kwargs.get("thinking", self.thinking):
            # Honoured when llama-server runs with --jinja, which it does.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        for key in ("top_p", "top_k", "repeat_penalty", "stop", "seed"):
            if key in kwargs:
                payload[key] = kwargs[key]
        return payload

    def complete(self, messages: list[Message], **kwargs) -> str:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        started = time.monotonic()
        logger.debug("POST %s (%d messages, stream=False)", url, len(messages))

        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.post(url, json=self._payload(messages, False, **kwargs))
            response.raise_for_status()
            data = response.json()

        self._record_usage(data.get("usage"))
        message = data["choices"][0]["message"]
        self.last_reasoning = message.get("reasoning_content") or ""
        content = message.get("content") or ""
        elapsed = time.monotonic() - started

        logger.info(
            "completion: %d tokens in %.2fs (%.1f tok/s), prompt %d%s",
            self.last_usage.completion_tokens,
            elapsed,
            self.last_usage.completion_tokens / elapsed if elapsed else 0.0,
            self.last_usage.prompt_tokens,
            ", reasoning suppressed" if not content and self.last_reasoning else "",
        )

        if not content and self.last_reasoning:
            logger.warning(
                "model produced only reasoning (%d chars) and no answer — "
                "token budget exhausted mid-thought",
                len(self.last_reasoning),
            )
            return (
                "[no answer produced — the model spent the whole token budget "
                "reasoning. Raise max_tokens or turn thinking off.]"
            )
        return content

    def stream(self, messages: list[Message], **kwargs) -> Iterator[str]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        self.last_reasoning = ""
        started = time.monotonic()
        chunks = 0
        logger.debug("POST %s (%d messages, stream=True)", url, len(messages))

        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            with client.stream("POST", url, json=self._payload(messages, True, **kwargs)) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    body = line[len("data:") :].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except json.JSONDecodeError:
                        logger.debug("skipping unparseable SSE chunk: %.80s", body)
                        continue
                    if chunk.get("usage"):
                        self._record_usage(chunk["usage"])
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content"):
                            self.last_reasoning += delta["reasoning_content"]
                        piece = delta.get("content")
                        if piece:
                            chunks += 1
                            yield piece

        elapsed = time.monotonic() - started
        logger.info(
            "stream finished: %d chunks in %.2fs%s",
            chunks,
            elapsed,
            " (no content — reasoning only)" if chunks == 0 and self.last_reasoning else "",
        )

    def _record_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        self.last_usage = Usage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    def health(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url.rstrip('/')}/models")
            if response.status_code < 400:
                return True, "reachable"
            return False, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)


def from_role_config(role: dict) -> Backend:
    """Build a backend from the `roles.llm` block of a stack config."""
    if role.get("source") == "api":
        raise NotImplementedError(
            "hosted API backends were removed for now — reconfigure this stack "
            "with a local model, or restore the provider adapters"
        )
    return LocalBackend(
        base_url=role.get("base_url", "http://127.0.0.1:8080/v1"),
        model=role.get("model_id", ""),
    )
