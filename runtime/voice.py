"""Voice synthesis — clone or design, cached, driven by an on-demand
qwentts.cpp tts-server rather than a resident in-process model.

    clone.json      {ref_text, seed, source} — the reference clip's
                    transcript, the seed pinned for reproducibility, and
                    whether the clip was "recorded" (a mic sample) or
                    "generated" (a VoiceDesign clip chained through
                    build_clone() for a consistent voice — see
                    synth_design_once()). Stored once at build_clone() time.
    clone_ref.wav   The reference clip itself, copied verbatim. qwentts.cpp's
                    tts-server extracts the voice embedding server-side from
                    this on every registration — see _register_clone().
    design.json     {instruct, seed, language} — VoiceDesign parameters.
                    Only ever the bootstrap default now that generation
                    chains into clone.json — see _ensure_voice_configured().
    disabled        Bare marker file. Presence = the fan-facing voice
                    feature is turned off; absence (the default) = on. Only
                    gates /voice/speak and the chat pre-warm — admin testing
                    stays available either way.

If both clone.json and design.json exist, clone wins. Only one loads per
synth batch, decided by voice_status(). voice_status() == "none" only ever
happens before the very first synth attempt — _ensure_voice_configured()
lazily builds a design.json default at that point, so nothing downstream
has to handle "none" as a real case.

cache/<sha256>.wav  Generated clips, keyed by (checkpoint kind, checkpoint
                    mtime, language, text) — a repeat of the same line skips
                    tts-server entirely. The checkpoint mtime is part of the
                    key so a rebuilt clone/design can never serve a
                    stale-voice clip.

tts-server keeps a registered voice in that process's own memory — lost
every time it's stopped. Since this module starts and stops it around every
batch of synths (see docs/superpowers/specs/2026-08-30-tts-on-demand-gguf-design.md),
a clone voice is re-registered on every fresh start(), not just once.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Iterator, Literal

import httpx

from cookbook.download import target_dir
from cookbook.schema import load_catalogue

from service.logging_config import get_logger

from . import qwentts
from .bible import PROFILE_PATH, voice_design_instruct
from .tools import snapshot

logger = get_logger("runtime.voice")

VOICE_DIR = PROFILE_PATH.parent / "voice"
CLONE_META_PATH = VOICE_DIR / "clone.json"
CLONE_REF_PATH = VOICE_DIR / "clone_ref.wav"
DESIGN_PATH = VOICE_DIR / "design.json"
DISABLED_PATH = VOICE_DIR / "disabled"
CACHE_DIR = VOICE_DIR / "cache"
CACHE_MAX_FILES = 300

CLONE_MODEL_ID = "qwen3-tts-gguf-base"
DESIGN_MODEL_ID = "qwen3-tts-gguf-voicedesign"
CODEC_FILENAME = "qwen-tokenizer-12hz-Q8_0.gguf"
CLONE_VOICE_NAME = "clone"

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

# Chat abbreviations Qwen3-TTS sounds out letter-by-letter ("idk" -> "eye dee
# kay") instead of reading as words — spelled out before every synth call.
# Deliberately small: only the ones that actually mis-pronounce, not every
# bit of chat shorthand (e.g. "gonna"/"wanna" already read fine as-is).
_ABBREVIATIONS = {
    "idk": "i don't know",
    "btw": "by the way",
    "omg": "oh my god",
    "tbh": "to be honest",
    "imo": "in my opinion",
    "imho": "in my honest opinion",
    "ngl": "not gonna lie",
    "irl": "in real life",
    "afaik": "as far as i know",
    "lol": "laughing out loud",
    "lmao": "laughing my ass off",
    "brb": "be right back",
    "fyi": "for your information",
}
_ABBREVIATION_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\b",
    re.IGNORECASE,
)


def _expand_abbreviations(text: str) -> str:
    return _ABBREVIATION_RE.sub(lambda m: _ABBREVIATIONS[m.group(0).lower()], text)


def _clean_for_tts(text: str) -> str:
    text = text.translate(_PUNCT_TRANSLATION)
    text = _EMOJI_RE.sub("", text)
    text = _expand_abbreviations(text)
    text = re.sub(r"([!?.,])\1+", r"\1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def voice_status() -> Literal["clone", "design", "none"]:
    if CLONE_META_PATH.exists():
        return "clone"
    if DESIGN_PATH.exists():
        return "design"
    return "none"


def clone_source() -> Literal["recorded", "generated"] | None:
    """None when there's no clone at all. Older clone.json files predate the
    "source" field — treated as "recorded" since that's the only way a clone
    could have been built before generation started chaining into one."""
    if not CLONE_META_PATH.exists():
        return None
    cached = json.loads(CLONE_META_PATH.read_text(encoding="utf-8"))
    return cached.get("source", "recorded")


def voice_enabled() -> bool:
    return not DISABLED_PATH.exists()


def set_voice_enabled(enabled: bool) -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if enabled:
        DISABLED_PATH.unlink(missing_ok=True)
    else:
        DISABLED_PATH.touch()


def _talker_and_codec_paths(kind: Literal["clone", "design"]) -> tuple[Path, Path]:
    model_id = CLONE_MODEL_ID if kind == "clone" else DESIGN_MODEL_ID
    entry = load_catalogue().model(model_id)
    directory = target_dir(entry)
    talkers = sorted(directory.glob("qwen-talker-*.gguf"))
    if not talkers:
        # A bare next() here used to raise StopIteration straight out of
        # synth()'s generator frame — PEP 479 turns that into an opaque
        # "generator raised StopIteration" RuntimeError instead of this
        # message. Most likely cause: only one of the two tts role entries
        # was downloaded — see cookbook/download.py's models_from_config().
        raise RuntimeError(
            f"{model_id} has no qwen-talker-*.gguf under {directory} — "
            f"download it first: python -m cookbook.download --models {model_id}"
        )
    codec = directory / CODEC_FILENAME
    return talkers[0], codec


def build_clone(
    ref_audio: Path, ref_text: str, seed: int = 0, source: Literal["recorded", "generated"] = "recorded"
) -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if CLONE_META_PATH.exists():
        snapshot(CLONE_META_PATH)
    shutil.copyfile(ref_audio, CLONE_REF_PATH)
    CLONE_META_PATH.write_text(
        json.dumps({"ref_text": ref_text, "seed": seed, "source": source}), encoding="utf-8"
    )
    logger.info("built voice clone reference (%s) from %s, seed=%d", source, ref_audio, seed)


def build_design(instruct: str, seed: int, language: str = "Auto") -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if DESIGN_PATH.exists():
        snapshot(DESIGN_PATH)
    DESIGN_PATH.write_text(
        json.dumps({"instruct": instruct, "seed": seed, "language": language}),
        encoding="utf-8",
    )
    logger.info("built voice design, seed=%d language=%s", seed, language)


def _ensure_voice_configured() -> Literal["clone", "design"]:
    """voice_status() can only ever be "none" before the very first synth
    attempt — lazily build the design.json bootstrap default right then, so
    every caller past this point can treat "clone" and "design" as the only
    two real states. Cheap: just a JSON write, no tts-server involved."""
    status = voice_status()
    if status == "none":
        build_design(voice_design_instruct(), seed=0, language="Auto")
        return "design"
    return status


def synth_design_once(text: str, language: str = "Auto") -> bytes:
    """One-off VoiceDesign synth, ignoring voice_status() — used right after
    build_design() to generate a reference clip for build_clone() to lock
    in. VoiceDesign's raw output isn't guaranteed identical call to call the
    way a fixed clone embedding is; chaining through build_clone() makes the
    voice actually consistent, and this is what generates that one clip."""
    text = _clean_for_tts(text)
    if language.lower() not in QWEN_SUPPORTED_LANGUAGES:
        language = "Auto"
    talker, codec = _talker_and_codec_paths("design")
    with qwentts.LOCK:
        server = qwentts.TTSServer(talker_path=talker, codec_path=codec)
        server.start()
        try:
            return _synth_via_server(server, text, language, "design")
        finally:
            server.stop()


def _chunk(data: bytes, size: int = 32_768) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def _evict_oldest(cache_dir: Path, keep: int) -> None:
    clips = sorted(cache_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    for clip in clips[: len(clips) - keep]:
        clip.unlink()


def _cache_path(text: str, language: str, status: str) -> Path:
    checkpoint = CLONE_META_PATH if status == "clone" else DESIGN_PATH
    fingerprint = checkpoint.stat().st_mtime_ns if checkpoint.exists() else 0
    key = hashlib.sha256(f"{status}|{fingerprint}|{language}|{text}".encode()).hexdigest()
    return CACHE_DIR / f"{key}.wav"


def _register_clone(server: "qwentts.TTSServer") -> None:
    cached = json.loads(CLONE_META_PATH.read_text(encoding="utf-8"))
    wav_b64 = base64.b64encode(CLONE_REF_PATH.read_bytes()).decode("ascii")
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{server.base_url}/v1/audio/voices",
            json={
                "name": CLONE_VOICE_NAME,
                "ref_text": cached["ref_text"],
                "wav_b64": wav_b64,
            },
        )
        resp.raise_for_status()


def _synth_via_server(server: "qwentts.TTSServer", text: str, language: str, status: str) -> bytes:
    # Field names verified against a real tts-server (CUDA Docker image) —
    # see docs/superpowers/specs/2026-08-30-tts-api-findings.md.
    payload: dict[str, Any] = {"input": text, "response_format": "wav"}
    if status == "clone":
        cached = json.loads(CLONE_META_PATH.read_text(encoding="utf-8"))
        payload["voice"] = CLONE_VOICE_NAME
        payload["seed"] = cached["seed"]
    elif status == "design":
        cached = json.loads(DESIGN_PATH.read_text(encoding="utf-8"))
        payload["instructions"] = cached["instruct"]
        payload["seed"] = cached["seed"]
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(f"{server.base_url}/v1/audio/speech", json=payload)
        resp.raise_for_status()
        return resp.content


def warm_bubbles(texts: list[str], language: str = "Auto") -> None:
    """Synthesize every cache-miss in `texts` under one tts-server load.

    The shared entry point for both the per-turn background pre-warm
    (service/main.py's /chat) and /voice/speak's cache-miss fallback — the
    only difference between those two callers is how many texts they pass.
    """
    status = _ensure_voice_configured()
    if language.lower() not in QWEN_SUPPORTED_LANGUAGES:
        language = "Auto"

    cleaned = [_clean_for_tts(t) for t in texts]
    misses = [t for t in cleaned if not _cache_path(t, language, status).exists()]
    if not misses:
        return

    with qwentts.LOCK:
        # A caller ahead of us in line may have already synthesized some or
        # all of these while we were waiting on the lock.
        misses = [t for t in misses if not _cache_path(t, language, status).exists()]
        if not misses:
            return

        talker, codec = _talker_and_codec_paths(status)
        server = qwentts.TTSServer(talker_path=talker, codec_path=codec)
        server.start()
        try:
            if status == "clone":
                _register_clone(server)
            for text in misses:
                try:
                    audio = _synth_via_server(server, text, language, status)
                except Exception:
                    logger.exception("tts-server synth failed mid-batch, stopping this batch")
                    break
                cache_path = _cache_path(text, language, status)
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(audio)
                _evict_oldest(CACHE_DIR, CACHE_MAX_FILES)
        finally:
            server.stop()


def synth(text: str, language: str = "Auto") -> Iterator[bytes]:
    text = _clean_for_tts(text)
    if language.lower() not in QWEN_SUPPORTED_LANGUAGES:
        language = "Auto"
    status = _ensure_voice_configured()

    cache_path = _cache_path(text, language, status)
    if cache_path.exists():
        logger.info("synth: kind=%s language=%s chars=%d (cache hit)", status, language, len(text))
        yield from _chunk(cache_path.read_bytes())
        return

    logger.info("synth: kind=%s language=%s chars=%d", status, language, len(text))
    t0 = time.monotonic()
    warm_bubbles([text], language)
    if not cache_path.exists():
        raise RuntimeError("tts-server failed to produce audio for this text")
    logger.info("synth done: kind=%s elapsed=%.2fs", status, time.monotonic() - t0)
    yield from _chunk(cache_path.read_bytes())
