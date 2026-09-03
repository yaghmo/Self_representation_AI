"""Fish Audio text-to-speech, called directly (not through OpenRouter) — the
"api" alternative to the local qwentts.cpp stack in runtime/voice.py.

No design mode here: Fish Audio has no text-instruction voice synthesis, only
a fixed voice (a named `reference_id`, or the provider default when none is
given) and stateless reference-audio cloning (the whole clip re-sent on every
call — there is no persisted clone id the way qwentts's clone.json pins one).

The request body is MessagePack, not JSON — Fish Audio's own API, unlike
OpenRouter's OpenAI-compatible passthrough, takes reference audio as raw
bytes inside a msgpack-encoded body rather than a base64 data URI in JSON.
`format: "wav"` gets a ready-made WAV byte stream back directly, so unlike
the OpenRouter path this needs no PCM->WAV wrapping.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import msgpack

BASE_URL = "https://api.fish.audio"
MODEL_HEADER = "s2.1-pro-free"
API_KEY_ENV = "FISH_API_KEY"

# Two curated public voices from Fish Audio's own voice library — see
# https://fish.audio/discovery for browsing more. Chosen for clean audio and
# a neutral, general-purpose tone (not a character voice, not a real
# person's likeness). Native Fish Audio model ids, so they work as
# `reference_id` here exactly as they did as OpenRouter's `voice` field.
VOICE_MALE = "802e3bc2b27e49c2995d23ef70e6ac89"  # "Energetic Male"
VOICE_FEMALE = "da3e7f40f72041eab8d986603b94d63b"  # "UGC Female"


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set — api tts needs a Fish Audio key")
    return key


def api_synth(
    text: str,
    *,
    voice: str | None = None,
    ref_audio: bytes | None = None,
    ref_text: str | None = None,
    timeout: float = 60.0,
) -> bytes:
    """One synth call to Fish Audio. Returns WAV bytes.

    `ref_audio` set -> stateless voice cloning for this call only (`voice` is
    ignored — `references` takes over voice selection entirely). No
    `ref_audio` and no `voice` -> the provider's own default voice.
    """
    payload: dict[str, Any] = {"text": text, "format": "wav", "sample_rate": 24000}
    if ref_audio is not None:
        payload["references"] = [{"audio": ref_audio, "text": ref_text or ""}]
    elif voice:
        payload["reference_id"] = voice

    body = msgpack.packb(payload, use_bin_type=True)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            f"{BASE_URL}/v1/tts",
            content=body,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/msgpack",
                "model": MODEL_HEADER,
            },
        )
        resp.raise_for_status()
        return resp.content
