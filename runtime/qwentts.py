"""Runs qwen3-tts through qwentts.cpp's own `tts-server` binary, on demand.

Mirrors runtime/llamacpp.py's LlamaServer shape: spawn a subprocess, poll
/health, talk HTTP, terminate on stop(). Unlike LlamaServer, this process is
started and stopped around every batch of synths rather than held resident —
see docs/superpowers/specs/2026-08-30-tts-on-demand-gguf-design.md.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path

import httpx

from runtime.llamacpp import cuda_dll_dirs
from service.logging_config import get_logger

logger = get_logger("runtime.qwentts")

# Mirrors llamacpp.py's own WeakSet — a crashed request must never leave a
# tts-server process holding VRAM with nobody owning it.
_running: "weakref.WeakSet[TTSServer]" = weakref.WeakSet()


@atexit.register
def _stop_all_servers() -> None:
    for server in list(_running):
        try:
            server.stop()
        except Exception:
            pass


REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "qwentts.cpp"
BIN_DIR = VENDOR_DIR / "build"

# Single-tenant, one GPU: tts-server and llama-server are the only two VRAM
# consumers, and there is never a case where two tts-server instances should
# run at once. Every caller that needs the TTS GPU slot serializes on this.
LOCK = threading.Lock()


def find_tts_server() -> Path | None:
    names = ("tts-server.exe", "tts-server") if os.name == "nt" else ("tts-server", "tts-server.exe")
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
        candidate = BIN_DIR / name
        if candidate.exists():
            return candidate
    return None


@dataclass(eq=False)
class TTSServer:
    """A tts-server subprocess, owned and cleaned up by this object."""

    talker_path: Path
    codec_path: Path
    alias: str = "qwen3-tts"
    host: str = "127.0.0.1"
    port: int = 8091
    process: subprocess.Popen | None = None
    reused: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def command(self) -> list[str]:
        server = find_tts_server()
        if server is None:
            raise RuntimeError(
                "tts-server not found. Build qwentts.cpp into vendor/qwentts.cpp/ "
                "(see docs/superpowers/specs/2026-08-30-tts-on-demand-gguf-design.md)."
            )
        return [
            str(server),
            "--model", str(self.talker_path),
            "--codec", str(self.codec_path),
            "--alias", self.alias,
            "--host", self.host,
            "--port", str(self.port),
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

        logger.info(
            "starting tts-server: talker=%s port=%d", self.talker_path.name, self.port
        )
        env = dict(os.environ)
        prefix = os.pathsep.join(str(d) for d in cuda_dll_dirs())
        env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"
        env["LD_LIBRARY_PATH"] = f"{prefix}{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"

        self.process = subprocess.Popen(
            self.command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
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
                    logger.error("tts-server exited with %s", self.process.returncode)
                    raise RuntimeError(
                        f"tts-server exited with {self.process.returncode}.\n{output[-2000:]}"
                    )
                if self.already_running():
                    logger.info("tts-server healthy after %.1fs", time.time() - started)
                    return self
                time.sleep(0.5)

            raise RuntimeError(f"tts-server did not become healthy within {wait_seconds}s")
        except Exception:
            logger.exception("tts-server failed to come up — cleaning up the process")
            self.stop()
            raise

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            logger.info("stopping tts-server pid %s", self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logger.warning("tts-server ignored terminate, killing")
                self.process.kill()
        self.process = None
        _running.discard(self)

    def __enter__(self) -> "TTSServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
