"""Runs qwen3-tts via qwentts.cpp's published tts-server Docker image, on
demand, one turn's synth batch at a time.

No local build of qwentts.cpp exists on this machine, and building one
needs a CUDA/MSVC toolchain or a working WSL distro this machine doesn't
have — verified live instead against
`ghcr.io/serveurpersocom/qwentts.cpp:cuda12` via Docker (GPU passthrough
confirmed working), see
docs/superpowers/specs/2026-08-30-tts-api-findings.md. Mirrors
runtime/llamacpp.py's LlamaServer shape (spawn, poll /health, HTTP, stop())
with the spawned process being `docker run` instead of a bare binary.
"""

from __future__ import annotations

import atexit
import subprocess
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path

import httpx

from service.logging_config import get_logger

logger = get_logger("runtime.qwentts")

# Mirrors llamacpp.py's own WeakSet — a crashed request must never leave a
# tts-server container holding VRAM with nobody owning it.
_running: "weakref.WeakSet[TTSServer]" = weakref.WeakSet()


@atexit.register
def _stop_all_servers() -> None:
    for server in list(_running):
        try:
            server.stop()
        except Exception:
            pass


IMAGE = "ghcr.io/serveurpersocom/qwentts.cpp:cuda12"

# Single-tenant, one GPU: tts-server and llama-server are the only two VRAM
# consumers, and there is never a case where two tts-server instances should
# run at once. Every caller that needs the TTS GPU slot serializes on this.
LOCK = threading.Lock()


@dataclass(eq=False)
class TTSServer:
    """A qwentts.cpp tts-server container, owned and cleaned up by this object."""

    talker_path: Path
    codec_path: Path
    host: str = "127.0.0.1"
    port: int = 8091
    process: subprocess.Popen | None = None
    reused: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def container_name(self) -> str:
        return f"qwentts-{self.port}"

    def command(self) -> list[str]:
        # talker and codec always sit in the same catalogue-entry directory
        # (see runtime/voice.py's _talker_and_codec_paths) — mount that
        # whole directory once rather than the two files separately.
        model_dir = self.talker_path.parent
        return [
            "docker", "run", "--rm",
            "--name", self.container_name,
            "--gpus", "all",
            "-p", f"{self.port}:8080",
            "-v", f"{model_dir.as_posix()}:/models:ro",
            "-e", f"MODEL_PATH=/models/{self.talker_path.name}",
            "-e", f"CODEC_PATH=/models/{self.codec_path.name}",
            IMAGE,
        ]

    def already_running(self) -> bool:
        try:
            with httpx.Client(timeout=2.0) as client:
                return client.get(f"{self.base_url}/health").status_code < 500
        except Exception:
            return False

    def start(self, wait_seconds: int = 60) -> "TTSServer":
        if self.already_running():
            self.reused = True
            logger.warning(
                "port %d already serving tts-server — attaching to it", self.port
            )
            return self

        # A crash on a previous run can leave a stopped container holding
        # this name, and `docker run --name` refuses to start over it.
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        logger.info(
            "starting tts-server container: talker=%s port=%d",
            self.talker_path.name, self.port,
        )
        self.process = subprocess.Popen(
            self.command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )

        try:
            _running.add(self)
            started = time.time()
            deadline = started + wait_seconds
            while time.time() < deadline:
                if self.process.poll() is not None:
                    output = self.process.stdout.read() if self.process.stdout else ""
                    logger.error("tts-server container exited with %s", self.process.returncode)
                    raise RuntimeError(
                        f"tts-server container exited with {self.process.returncode}.\n{output[-2000:]}"
                    )
                if self.already_running():
                    logger.info("tts-server healthy after %.1fs", time.time() - started)
                    return self
                time.sleep(0.5)

            raise RuntimeError(f"tts-server did not become healthy within {wait_seconds}s")
        except Exception:
            logger.exception("tts-server failed to come up — cleaning up the container")
            self.stop()
            raise

    def stop(self) -> None:
        # `docker run`'s client process doesn't reliably forward a stop
        # signal to the container on every platform — stop the container by
        # name explicitly rather than trusting the client process's exit.
        subprocess.run(
            ["docker", "stop", self.container_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if self.process and self.process.poll() is None:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        _running.discard(self)

    def __enter__(self) -> "TTSServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
