"""Voice synthesis — clone or design, cached, one model warm at a time.

    clone.pt    pickle of {"prompt": create_voice_clone_prompt() output, "seed":
                int} — Base checkpoint. No documented seed param on
                generate_voice_clone either, so the seed is stored here and
                pinned before every call — otherwise timbre drifts call to
                call, audibly different tone from one synth() to the next.
                Stored once at build_clone() time so "hear yourself" and the
                fan-facing /voice/speak calls land on the identical seed.
    design.json {instruct, seed, language} — VoiceDesign checkpoint. No seed
                param on generate_voice_design, so reproducibility is done by
                pinning torch.manual_seed(seed) before each call.

If both exist, clone wins. Only one checkpoint loads per process, decided by
voice_status() at first use.

cache/<sha256>.wav  Generated clips, keyed by (checkpoint kind, checkpoint
                mtime, language, text) — a repeat of the same line skips the
                model entirely. The checkpoint mtime is part of the key so a
                rebuilt clone/design can never serve a stale-voice clip.

qwen-tts has no working streaming generation — synth() streams delivery of
the finished clip, not generation itself.
"""

from __future__ import annotations

import hashlib
import io
import json
import pickle
import re
import time
from pathlib import Path
from typing import Any, Iterator, Literal

import numpy as np
import soundfile as sf
import torch

from cookbook.download import target_dir
from cookbook.schema import load_catalogue

from service.logging_config import get_logger

from .bible import PROFILE_PATH
from .tools import snapshot

logger = get_logger("runtime.voice")

VOICE_DIR = PROFILE_PATH.parent / "voice"
CLONE_PATH = VOICE_DIR / "clone.pt"
DESIGN_PATH = VOICE_DIR / "design.json"
# Generated clips, cached to disk keyed by text — a fan re-asking (or the
# creator re-testing) the same question skips the GPU synth entirely.
# ponytail: no eviction/size cap — fine for the current single-tenant
# scale, revisit if this ever needs a real cache-size budget.
CACHE_DIR = VOICE_DIR / "cache"

CLONE_MODEL_ID = "qwen3-tts-12hz-1.7b-base"
DESIGN_MODEL_ID = "qwen3-tts-12hz-1.7b-voicedesign"

_MODEL_CACHE: dict[str, Any] = {}

# Qwen3-TTS raises on anything outside this set (e.g. Arabic, which
# voice_sample.py's LANGUAGES still offers for the read-aloud script since
# that's just text on screen, not a synth call).
QWEN_SUPPORTED_LANGUAGES = {
    "auto", "chinese", "english", "french", "german", "italian",
    "japanese", "korean", "portuguese", "russian", "spanish",
}

# Emoji/pictographs and curly punctuation confuse the model into babbling
# unrelated syllables rather than reading the text — strip/normalize before
# every synth call, whatever the caller.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "]+"
)
_PUNCT_TRANSLATION = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."}
)


def _clean_for_tts(text: str) -> str:
    text = text.translate(_PUNCT_TRANSLATION)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"([!?.,])\1+", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


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
    other = "design" if kind == "clone" else "clone"
    if other in _MODEL_CACHE:
        del _MODEL_CACHE[other]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("evicted %s voice model to load %s", other, kind)
    from qwen_tts import Qwen3TTSModel

    model_id = CLONE_MODEL_ID if kind == "clone" else DESIGN_MODEL_ID
    entry = load_catalogue().model(model_id)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    logger.info("loading %s voice model (%s) on %s", kind, model_id, device)
    t0 = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(
        str(target_dir(entry)), device_map=device, dtype=torch.bfloat16
    )
    logger.info("%s voice model loaded in %.1fs", kind, time.monotonic() - t0)
    _MODEL_CACHE[kind] = model
    return model


def build_clone(ref_audio: Path, ref_text: str, seed: int = 0) -> None:
    model = _load_model("clone")
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(ref_audio), ref_text=ref_text, x_vector_only_mode=False
    )
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if CLONE_PATH.exists():
        snapshot(CLONE_PATH)
    with open(CLONE_PATH, "wb") as f:
        pickle.dump({"prompt": prompt, "seed": seed}, f)
    logger.info("built voice clone from %s, seed=%d", ref_audio, seed)


def build_design(instruct: str, seed: int, language: str = "Auto") -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if DESIGN_PATH.exists():
        snapshot(DESIGN_PATH)
    DESIGN_PATH.write_text(
        json.dumps({"instruct": instruct, "seed": seed, "language": language}),
        encoding="utf-8",
    )
    logger.info("built voice design, seed=%d language=%s", seed, language)


def _wav_bytes(wav: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, wav, sample_rate, format="WAV")
    return buffer.getvalue()


def _chunk(data: bytes, size: int = 32_768) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def _cache_path(text: str, language: str, status: str) -> Path:
    # Keyed on the active checkpoint's mtime too — a rebuilt clone/design
    # must not serve a clip synthesized from the old voice.
    checkpoint = CLONE_PATH if status == "clone" else DESIGN_PATH
    fingerprint = checkpoint.stat().st_mtime_ns if checkpoint.exists() else 0
    key = hashlib.sha256(f"{status}|{fingerprint}|{language}|{text}".encode()).hexdigest()
    return CACHE_DIR / f"{key}.wav"


def synth(text: str, language: str = "Auto") -> Iterator[bytes]:
    text = _clean_for_tts(text)
    if language.lower() not in QWEN_SUPPORTED_LANGUAGES:
        language = "Auto"
    status = voice_status()
    if status == "none":
        logger.warning("synth called with no voice configured")
        raise NoVoiceConfigured("no clone or design voice is configured yet")
    cache_path = _cache_path(text, language, status)
    if cache_path.exists():
        logger.info("synth: kind=%s language=%s chars=%d (cache hit)", status, language, len(text))
        yield from _chunk(cache_path.read_bytes())
        return
    logger.info("synth: kind=%s language=%s chars=%d", status, language, len(text))
    t0 = time.monotonic()
    if status == "clone":
        model = _load_model("clone")
        with open(CLONE_PATH, "rb") as f:
            cached = pickle.load(f)
        torch.manual_seed(cached["seed"])
        wavs, sr = model.generate_voice_clone(
            text=text, language=language, voice_clone_prompt=cached["prompt"]
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
    audio = _wav_bytes(wavs[0], sr)
    logger.info(
        "synth done: kind=%s elapsed=%.2fs audio_s=%.2f",
        status, time.monotonic() - t0, len(wavs[0]) / sr,
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(audio)
    yield from _chunk(audio)
