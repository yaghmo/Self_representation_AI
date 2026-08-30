"""Migrated from runtime/voice.py's own __main__ self-check.

Invented placeholder content only — this file is tracked, and CLAUDE.md
forbids instance details in tracked files.
"""

import json
import os
import threading
import time
from pathlib import Path

import runtime.voice as voice_module
from runtime.voice import _evict_oldest, build_clone, build_design, synth, voice_status, warm_bubbles


def test_evict_oldest_keeps_newest_n(tmp_path):
    for i in range(5):
        clip = tmp_path / f"clip{i}.wav"
        clip.write_bytes(b"x")
        os.utime(clip, (i, i))

    _evict_oldest(tmp_path, keep=3)

    remaining = {p.name for p in tmp_path.glob("*.wav")}
    assert remaining == {"clip2.wav", "clip3.wav", "clip4.wav"}


def test_evict_oldest_noop_under_cap(tmp_path):
    clip = tmp_path / "clip0.wav"
    clip.write_bytes(b"x")

    _evict_oldest(tmp_path, keep=3)

    assert clip.exists()


class FakeTTSServer:
    start_calls = 0
    instances: list["FakeTTSServer"] = []

    def __init__(self, talker_path, codec_path, **kwargs):
        self.talker_path = talker_path
        self.codec_path = codec_path
        self.stopped = False
        FakeTTSServer.instances.append(self)

    def start(self, wait_seconds: int = 60):
        FakeTTSServer.start_calls += 1
        return self

    def stop(self):
        self.stopped = True


def _reset_fake_server():
    FakeTTSServer.start_calls = 0
    FakeTTSServer.instances.clear()


def _patch_voice_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(voice_module, "VOICE_DIR", tmp_path / "voice")
    monkeypatch.setattr(voice_module, "CLONE_META_PATH", voice_module.VOICE_DIR / "clone.json")
    monkeypatch.setattr(voice_module, "CLONE_REF_PATH", voice_module.VOICE_DIR / "clone_ref.wav")
    monkeypatch.setattr(voice_module, "DESIGN_PATH", voice_module.VOICE_DIR / "design.json")
    monkeypatch.setattr(voice_module, "CACHE_DIR", voice_module.VOICE_DIR / "cache")


def _patch_server(monkeypatch, lock=None):
    fake_module = type("FakeQwenttsModule", (), {
        "TTSServer": FakeTTSServer,
        "LOCK": lock or threading.Lock(),
    })
    monkeypatch.setattr(voice_module, "qwentts", fake_module)
    monkeypatch.setattr(
        voice_module, "_talker_and_codec_paths",
        lambda kind: (Path(f"{kind}-talker.gguf"), Path("codec.gguf")),
    )


def test_voice_lifecycle(tmp_path, monkeypatch):
    _patch_voice_dirs(monkeypatch, tmp_path)
    _reset_fake_server()
    _patch_server(monkeypatch)

    calls: dict = {}

    def fake_register_clone(server):
        calls["registered"] = True

    def fake_synth_via_server(server, text, language, status):
        calls.setdefault("synth_calls", []).append((text, language, status))
        return b"RIFFfake-audio-" + text.encode()

    monkeypatch.setattr(voice_module, "_register_clone", fake_register_clone)
    monkeypatch.setattr(voice_module, "_synth_via_server", fake_synth_via_server)

    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"RIFFref")

    assert voice_status() == "none"

    build_clone(ref_audio, "the quick brown fox", seed=42)
    assert voice_status() == "clone"
    assert voice_module.CLONE_REF_PATH.read_bytes() == b"RIFFref"
    assert json.loads(voice_module.CLONE_META_PATH.read_text())["seed"] == 42

    audio = b"".join(synth("hello there", language="english"))
    assert audio == b"RIFFfake-audio-hello there"
    assert calls["registered"] is True
    assert calls["synth_calls"] == [("hello there", "english", "clone")]

    # Same text + language again -> cache hit, no second synth call, no
    # second TTSServer spawn.
    cached_audio = b"".join(synth("hello there", language="english"))
    assert cached_audio == audio
    assert len(calls["synth_calls"]) == 1
    assert FakeTTSServer.start_calls == 1

    build_design("a warm low voice", seed=7, language="Auto")
    assert voice_status() == "clone", "clone.json still exists, so clone must still win"

    voice_module.CLONE_META_PATH.unlink()
    assert voice_status() == "design"
    b"".join(synth("a new line"))
    assert calls["synth_calls"][-1] == ("a new line", "Auto", "design")


def test_warm_bubbles_no_voice_configured_is_a_noop(tmp_path, monkeypatch):
    _patch_voice_dirs(monkeypatch, tmp_path)
    _reset_fake_server()
    _patch_server(monkeypatch)

    warm_bubbles(["never gets here"])

    assert FakeTTSServer.start_calls == 0


def test_warm_bubbles_two_concurrent_callers_start_server_once(tmp_path, monkeypatch):
    _patch_voice_dirs(monkeypatch, tmp_path)
    _reset_fake_server()
    lock = threading.Lock()
    _patch_server(monkeypatch, lock=lock)
    monkeypatch.setattr(voice_module, "_register_clone", lambda server: None)

    lock_acquired = threading.Event()
    release_gate = threading.Event()

    def slow_synth(server, text, language, status):
        lock_acquired.set()
        release_gate.wait(timeout=2)
        return b"RIFFaudio"

    monkeypatch.setattr(voice_module, "_synth_via_server", slow_synth)

    voice_module.VOICE_DIR.mkdir(parents=True)
    voice_module.CLONE_REF_PATH.write_bytes(b"ref")
    voice_module.CLONE_META_PATH.write_text(json.dumps({"ref_text": "x", "seed": 0}))

    thread_a = threading.Thread(target=warm_bubbles, args=(["shared bubble"],))
    thread_a.start()
    assert lock_acquired.wait(timeout=2), "thread A should have reached the synth call"

    thread_b = threading.Thread(target=warm_bubbles, args=(["shared bubble"],))
    thread_b.start()
    time.sleep(0.1)  # give B a chance to block on LOCK.acquire()

    release_gate.set()
    thread_a.join(timeout=2)
    thread_b.join(timeout=2)

    assert FakeTTSServer.start_calls == 1
