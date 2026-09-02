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
import os
import subprocess
import threading
import time
import weakref
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx

from cookbook.probe import _detect_container
from service.logging_config import get_logger

logger = get_logger("runtime.qwentts")

# The volume mount docker-compose.yml gives this container for model
# weights (see cookbook/download.py's MODELS_DIR — REPO_ROOT resolves to
# /app under the image's WORKDIR).
MODELS_MOUNT = Path("/app/models")


@lru_cache(maxsize=1)
def _host_models_root() -> str | None:
    """The models/ bind mount's real path on the Docker *host*.

    `docker run -v` below is a client command sent over the DooD socket —
    the *host* daemon resolves that -v source, not this container. Handing
    it a container-internal path like /app/models/<id> means nothing to
    the host, and it silently bind-mounts a fresh empty directory instead
    of erroring, so tts-server starts fine and then can't find its weights.
    Self-introspect our own container's mounts (Docker sets $HOSTNAME to
    the container id) to get the real host-side path, the same trick
    Docker-outside-of-Docker runners use generally."""
    if not _detect_container():
        return None
    container_id = os.environ.get("HOSTNAME")
    if not container_id:
        return None
    try:
        result = subprocess.run(
            [
                "docker", "inspect", "--format",
                '{{range .Mounts}}{{if eq .Destination "/app/models"}}'
                '{{.Source}}{{end}}{{end}}',
                container_id,
            ],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except Exception:
        logger.exception("could not resolve /app/models' host-side path")
        return None
    return result.stdout.strip() or None


def _host_path_for(container_path: Path) -> str:
    """Translate a path under MODELS_MOUNT into its host-visible form."""
    root = _host_models_root()
    if root is None:
        # Not containerized (e.g. `uv run` straight on the host) — the
        # path we were given is already a real, host-visible path.
        return container_path.as_posix()
    rel_parts = container_path.relative_to(MODELS_MOUNT).parts
    cls = PureWindowsPath if "\\" in root else PurePosixPath
    return str(cls(root, *rel_parts))

# `docker run -p PORT:8080` publishes the sibling container's port on the
# *host's* network — reachable as 127.0.0.1 only when this process is also
# running directly on the host. Inside a container (the normal deployed
# case — see docker-compose.yml's docker.sock mount), that same publish
# lands on the host's interface, one hop away from this container's own
# network namespace, and host.docker.internal is what reaches it.
DEFAULT_HOST = "host.docker.internal" if _detect_container() else "127.0.0.1"

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
CPU_IMAGE = "ghcr.io/serveurpersocom/qwentts.cpp:cpu"

# Single-tenant, one GPU: tts-server and llama-server are the only two VRAM
# consumers, and there is never a case where two tts-server instances should
# run at once. Every caller that needs the TTS GPU slot serializes on this.
LOCK = threading.Lock()


@dataclass(eq=False)
class TTSServer:
    """A qwentts.cpp tts-server container, owned and cleaned up by this object."""

    talker_path: Path
    codec_path: Path
    host: str = DEFAULT_HOST
    port: int = 8091
    device: str = "gpu"
    process: subprocess.Popen | None = None
    reused: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def container_name(self) -> str:
        return f"qwentts-{self.port}"

    @property
    def image(self) -> str:
        # Catalogue/config spell the GPU case "transient-gpu" (see
        # cookbook/fit.py), not "gpu" — only "cpu" picks the CPU image.
        return CPU_IMAGE if self.device == "cpu" else IMAGE

    def command(self) -> list[str]:
        # talker and codec always sit in the same catalogue-entry directory
        # (see runtime/voice.py's _talker_and_codec_paths) — mount that
        # whole directory once rather than the two files separately.
        model_dir = self.talker_path.parent
        command = [
            "docker", "run", "--rm",
            "--name", self.container_name,
        ]
        if self.device != "cpu":
            command += ["--gpus", "all"]
        command += [
            "-p", f"{self.port}:8080",
            "-v", f"{_host_path_for(model_dir)}:/models:ro",
            "-e", f"MODEL_PATH=/models/{self.talker_path.name}",
            "-e", f"CODEC_PATH=/models/{self.codec_path.name}",
            self.image,
        ]
        return command

    def already_running(self) -> bool:
        try:
            with httpx.Client(timeout=2.0) as client:
                return client.get(f"{self.base_url}/health").status_code < 500
        except Exception:
            return False

    def _ensure_image_pulled(self, timeout_seconds: int = 1800) -> None:
        # `docker run` would pull a missing image itself, but inline with
        # the health-check wait below — a multi-GB CUDA image's first pull
        # takes far longer than a container's boot ever should, so a short
        # wait_seconds there always timed out on a machine that had never
        # run this image before. Pull it here first, on its own generous
        # budget, so the health-check loop only ever waits on the fast part.
        inspect = subprocess.run(
            ["docker", "image", "inspect", self.image],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if inspect.returncode == 0:
            return
        logger.info("pulling %s (first use, may take a while)", self.image)
        subprocess.run(["docker", "pull", self.image], check=True, timeout=timeout_seconds)

    def start(self, wait_seconds: int = 60) -> "TTSServer":
        if self.already_running():
            self.reused = True
            logger.warning(
                "port %d already serving tts-server — attaching to it", self.port
            )
            return self

        self._ensure_image_pulled()

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
