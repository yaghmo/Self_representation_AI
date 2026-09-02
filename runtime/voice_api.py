"""Fish Audio text-to-speech through OpenRouter's /audio/speech endpoint —
the "api" alternative to the local qwentts.cpp stack in runtime/voice.py.

No design mode here: Fish Audio has no text-instruction voice synthesis, only
a fixed voice (its own id, or the provider default when none is given) and
stateless reference-audio cloning (the whole clip re-sent on every call —
there is no persisted clone id the way qwentts's clone.json pins one).

Response format is always "pcm" and wrapped into a WAV container here rather
than requested as "mp3" — every downstream consumer (service/main.py's
`media_type="audio/wav"`, voice.py's `*.wav` cache) expects a wav byte
stream, and PCM->WAV is a few lines of stdlib `wave` with no new dependency.
The sample rate isn't fixed — it's read off the response's own
`Content-Type: audio/pcm;rate=<n>;channels=<m>` header on every call.
"""

from __future__ import annotations

import base64
import io
import os
import wave
from typing import Any

import httpx

MODEL_ID = "fish-audio/s2.1-pro-free:free"
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_ENV = "OPENROUTER_API_KEY"

# Two curated public voices from Fish Audio's own voice library — there is no
# documented enum, no "male"/"female" keyword the API accepts, and no other
# way to discover ids short of browsing fish.audio/discovery by hand. Chosen
# for clean audio and a neutral, general-purpose tone (not a character voice,
# not a real person's likeness).
VOICE_MALE = "802e3bc2b27e49c2995d23ef70e6ac89"  # "Energetic Male"
VOICE_FEMALE = "da3e7f40f72041eab8d986603b94d63b"  # "UGC Female"

_RATE_RE_DEFAULT = 44100


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set — api tts needs an OpenRouter key")
    return key


def _pcm_to_wav(pcm: bytes, content_type: str) -> bytes:
    rate = _RATE_RE_DEFAULT
    channels = 1
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("rate="):
            rate = int(part[len("rate=") :])
        elif part.startswith("channels="):
            channels = int(part[len("channels=") :])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)  # 16-bit little-endian, per the schema's own doc
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def api_synth(
    text: str,
    *,
    voice: str | None = None,
    ref_audio: bytes | None = None,
    ref_text: str | None = None,
    timeout: float = 60.0,
) -> bytes:
    """One synth call to Fish Audio via OpenRouter. Returns WAV bytes.

    `ref_audio` set -> stateless voice cloning for this call only (`voice` is
    ignored — input_references takes over voice selection entirely). No
    `ref_audio` and no `voice` -> the provider's own default voice.
    """
    payload: dict[str, Any] = {
        "model": MODEL_ID,
        "input": text,
        "response_format": "pcm",
    }
    if ref_audio is not None:
        parts: list[dict[str, Any]] = [
            {
                "type": "input_audio",
                "input_audio": {
                    "data": "data:audio/wav;base64," + base64.b64encode(ref_audio).decode("ascii")
                },
            }
        ]
        if ref_text:
            parts.append({"type": "text", "text": ref_text})
        payload["input_references"] = parts
    elif voice:
        payload["voice"] = voice

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            f"{BASE_URL}/audio/speech",
            headers={"Authorization": f"Bearer {_api_key()}"},
            json=payload,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        return _pcm_to_wav(resp.content, content_type)
