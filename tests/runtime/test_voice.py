"""Migrated from runtime/voice.py's own __main__ self-check.

Invented placeholder content only — this file is tracked, and CLAUDE.md
forbids instance details in tracked files.
"""

import pickle
import tempfile
from pathlib import Path

import numpy as np
import torch

import runtime.voice as voice_module
from runtime.voice import build_clone, build_design, synth, voice_status


def test_voice_self_check():
    original = (
        voice_module.VOICE_DIR,
        voice_module.CLONE_PATH,
        voice_module.DESIGN_PATH,
        voice_module.CACHE_DIR,
    )
    calls: dict = {}

    class FakeModel:
        def create_voice_clone_prompt(self, ref_audio, ref_text, x_vector_only_mode):
            calls["clone_prompt"] = (ref_audio, ref_text, x_vector_only_mode)
            return [{"speaker": "fake-embedding"}]

        def generate_voice_clone(self, text, language, voice_clone_prompt):
            calls["clone_generate"] = (text, language, voice_clone_prompt)
            calls["clone_generate_count"] = calls.get("clone_generate_count", 0) + 1
            calls.setdefault("clone_seeds", []).append(torch.initial_seed())
            return [np.zeros(2400, dtype=np.float32)], 24000

        def generate_voice_design(self, text, language, instruct):
            calls["design_generate"] = (text, language, instruct)
            return [np.zeros(2400, dtype=np.float32)], 24000

    try:
        with tempfile.TemporaryDirectory() as tmp:
            voice_module.VOICE_DIR = Path(tmp) / "voice"
            voice_module.CLONE_PATH = voice_module.VOICE_DIR / "clone.pt"
            voice_module.DESIGN_PATH = voice_module.VOICE_DIR / "design.json"
            voice_module.CACHE_DIR = voice_module.VOICE_DIR / "cache"
            voice_module._MODEL_CACHE["clone"] = FakeModel()
            voice_module._MODEL_CACHE["design"] = voice_module._MODEL_CACHE["clone"]

            assert voice_status() == "none"

            build_clone(Path("ref.wav"), "the quick brown fox", seed=42)
            assert voice_status() == "clone"
            assert calls["clone_prompt"] == ("ref.wav", "the quick brown fox", False)
            with open(voice_module.CLONE_PATH, "rb") as f:
                assert pickle.load(f)["seed"] == 42, "seed must be stored alongside the prompt"

            # A valid QWEN_SUPPORTED_LANGUAGES entry, not an ISO code ("en"
            # isn't in that set and silently falls back to "Auto" — that
            # fallback is real behavior, just not what this assertion means
            # to exercise).
            audio = b"".join(synth("hello there", language="english"))
            assert audio.startswith(b"RIFF"), "not a WAV container"
            assert calls["clone_generate"][1] == "english"

            # Same stored seed pinned on every call — this is what keeps "hear
            # yourself" and the fan-facing synth() sounding like the same voice.
            b"".join(synth("a second bubble", language="english"))
            assert calls["clone_seeds"] == [42, 42], "every clone synth must pin the stored seed"

            # Same text + language again -> served from the on-disk cache,
            # no second call into the model at all.
            cached_audio = b"".join(synth("hello there", language="english"))
            assert cached_audio == audio, "cache hit must return byte-identical audio"
            assert calls["clone_generate_count"] == 2, "cache hit must not re-invoke the model"

            build_design("a warm low voice", seed=7, language="Auto")
            # clone.pt still exists, so clone must still win over design.
            assert voice_status() == "clone"

            voice_module.CLONE_PATH.unlink()
            assert voice_status() == "design"
            audio = b"".join(synth("hello there"))
            assert audio.startswith(b"RIFF")
            assert calls["design_generate"][2] == "a warm low voice"
    finally:
        (
            voice_module.VOICE_DIR,
            voice_module.CLONE_PATH,
            voice_module.DESIGN_PATH,
            voice_module.CACHE_DIR,
        ) = original
        voice_module._MODEL_CACHE.clear()
