"""Voice synthesis — clone or design, cached, one model warm at a time.

Two mutually-exclusive cached objects under data/voice/, built once by the
admin flow and reused on every synth() call after:

    clone.pt    pickle of create_voice_clone_prompt() — Base checkpoint.
    design.json {"instruct": str, "seed": int, "language": str} — VoiceDesign
                checkpoint. No seed param is documented on generate_voice_design,
                so reproducibility is done by pinning torch.manual_seed(seed)
                before every call — confirmed no such param exists on the
                installed qwen-tts==0.1.1 generate_voice_design signature.

If both exist, clone wins — a real reference clip beats a generated
approximation. Only one Qwen3-TTS checkpoint is ever loaded per process,
decided by voice_status() at first use — matches this repo's "nothing swaps
mid-session" rule.

qwen-tts's own generate methods have no working streaming generation in this
version (checked the installed source directly) — synth() streams the
*delivery* of the finished clip in chunks, not the generation itself.
"""

from __future__ import annotations

import io
import json
import pickle
from pathlib import Path
from typing import Any, Iterator, Literal

import numpy as np
import soundfile as sf
import torch

from cookbook.download import target_dir
from cookbook.schema import load_catalogue

from .bible import PROFILE_PATH
from .tools import snapshot

VOICE_DIR = PROFILE_PATH.parent / "voice"
CLONE_PATH = VOICE_DIR / "clone.pt"
DESIGN_PATH = VOICE_DIR / "design.json"

CLONE_MODEL_ID = "qwen3-tts-12hz-1.7b-base"
DESIGN_MODEL_ID = "qwen3-tts-12hz-1.7b-voicedesign"

_MODEL_CACHE: dict[str, Any] = {}


class NoVoiceConfigured(RuntimeError):
    pass


def voice_status() -> Literal["clone", "design", "none"]:
    if CLONE_PATH.exists():
        return "clone"
    if DESIGN_PATH.exists():
        return "design"
    return "none"


def _load_model(kind: Literal["clone", "design"]):
    if kind in _MODEL_CACHE:
        return _MODEL_CACHE[kind]
    from qwen_tts import Qwen3TTSModel

    model_id = CLONE_MODEL_ID if kind == "clone" else DESIGN_MODEL_ID
    entry = load_catalogue().model(model_id)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = Qwen3TTSModel.from_pretrained(
        str(target_dir(entry)), device_map=device, dtype=torch.bfloat16
    )
    _MODEL_CACHE[kind] = model
    return model


def build_clone(ref_audio: Path, ref_text: str) -> None:
    model = _load_model("clone")
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(ref_audio), ref_text=ref_text, x_vector_only_mode=False
    )
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if CLONE_PATH.exists():
        snapshot(CLONE_PATH)
    with open(CLONE_PATH, "wb") as f:
        pickle.dump(prompt, f)


def build_design(instruct: str, seed: int, language: str = "Auto") -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if DESIGN_PATH.exists():
        snapshot(DESIGN_PATH)
    DESIGN_PATH.write_text(
        json.dumps({"instruct": instruct, "seed": seed, "language": language}),
        encoding="utf-8",
    )


def _wav_bytes(wav: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    return buffer.getvalue()


def _chunk(data: bytes, size: int = 32_768) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def synth(text: str, language: str = "Auto") -> Iterator[bytes]:
    status = voice_status()
    if status == "clone":
        model = _load_model("clone")
        with open(CLONE_PATH, "rb") as f:
            prompt = pickle.load(f)
        wavs, sr = model.generate_voice_clone(
            text=text, language=language, voice_clone_prompt=prompt
        )
    elif status == "design":
        model = _load_model("design")
        cached = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        torch.manual_seed(cached["seed"])
        wavs, sr = model.generate_voice_design(
            text=text,
            language=cached.get("language", "Auto"),
            instruct=cached["instruct"],
        )
    else:
        raise NoVoiceConfigured("no clone or design voice is configured yet")
    yield from _chunk(_wav_bytes(wavs[0], sr))


def _self_check() -> None:
    import tempfile

    global VOICE_DIR, CLONE_PATH, DESIGN_PATH

    original = (VOICE_DIR, CLONE_PATH, DESIGN_PATH)
    calls: dict = {}

    class FakeModel:
        def create_voice_clone_prompt(self, ref_audio, ref_text, x_vector_only_mode):
            calls["clone_prompt"] = (ref_audio, ref_text, x_vector_only_mode)
            return [{"speaker": "fake-embedding"}]

        def generate_voice_clone(self, text, language, voice_clone_prompt):
            calls["clone_generate"] = (text, language, voice_clone_prompt)
            return [np.zeros(2400, dtype=np.float32)], 24000

        def generate_voice_design(self, text, language, instruct):
            calls["design_generate"] = (text, language, instruct)
            return [np.zeros(2400, dtype=np.float32)], 24000

    try:
        with tempfile.TemporaryDirectory() as tmp:
            VOICE_DIR = Path(tmp) / "voice"
            CLONE_PATH = VOICE_DIR / "clone.pt"
            DESIGN_PATH = VOICE_DIR / "design.json"
            _MODEL_CACHE["clone"] = FakeModel()
            _MODEL_CACHE["design"] = _MODEL_CACHE["clone"]

            assert voice_status() == "none"

            build_clone(Path("ref.wav"), "the quick brown fox")
            assert voice_status() == "clone"
            assert calls["clone_prompt"] == ("ref.wav", "the quick brown fox", False)

            audio = b"".join(synth("hello there", language="en"))
            assert audio.startswith(b"RIFF"), "not a WAV container"
            assert calls["clone_generate"][1] == "en"

            build_design("a warm low voice", seed=7, language="Auto")
            # clone.pt still exists, so clone must still win over design.
            assert voice_status() == "clone"

            CLONE_PATH.unlink()
            assert voice_status() == "design"
            audio = b"".join(synth("hello there"))
            assert audio.startswith(b"RIFF")
            assert calls["design_generate"][2] == "a warm low voice"
    finally:
        VOICE_DIR, CLONE_PATH, DESIGN_PATH = original
        _MODEL_CACHE.clear()

    print("voice: all checks passed")


if __name__ == "__main__":
    _self_check()
