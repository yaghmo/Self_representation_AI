"""Runs a GGUF through llama.cpp's own server binary.

Why a binary and not a Python binding: there is no prebuilt, GPU-capable,
Qwen3-capable `llama-cpp-python` wheel for Windows/cp310 — CUDA wheels stop at
0.3.4, which pre-dates Qwen3. Building from source needs MSVC and the CUDA
toolkit. The official release binaries need neither, and the server speaks the
OpenAI protocol, so local and hosted models share one client.

This is not ollama. There is no registry, no daemon, no model naming scheme —
one process, pointed at one file you already have on disk.

Placement is the interesting part. llama.cpp does not force a GPU-or-CPU
choice: `--n-gpu-layers N` puts N layers on the card and leaves the rest in
RAM. So a model that *almost* fits still runs mostly on the GPU instead of
falling all the way back to CPU.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import time
import weakref
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from cookbook.probe import Probe, run_probe
from cookbook.schema import GB, MB, ModelEntry, human_bytes
from service.logging_config import get_logger

logger = get_logger("runtime.llamacpp")

# Every server this process starts, so a crash or Ctrl-C does not leave a
# subprocess holding several GB of VRAM. That happened once already.
_running: "weakref.WeakSet[LlamaServer]" = weakref.WeakSet()


@atexit.register
def _stop_all_servers() -> None:
    for server in list(_running):
        try:
            server.stop()
        except Exception:
            pass

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "llama.cpp"
BIN_DIR = VENDOR_DIR / "bin"

# Room for the CUDA context, fragmentation, and the compute buffers llama.cpp
# allocates beyond the weights themselves.
VRAM_SAFETY = 700 * MB


@dataclass
class Placement:
    """The decision, with the arithmetic that produced it kept visible."""

    n_gpu_layers: int
    total_layers: int
    reason: str
    vram_needed: int
    vram_available: int

    @property
    def mode(self) -> str:
        if self.n_gpu_layers == 0:
            return "cpu"
        if self.n_gpu_layers >= self.total_layers:
            return "gpu"
        return "partial"

    def describe(self) -> str:
        if self.mode == "gpu":
            return f"all {self.total_layers} layers on GPU — {self.reason}"
        if self.mode == "cpu":
            return f"CPU only — {self.reason}"
        return (
            f"{self.n_gpu_layers} of {self.total_layers} layers on GPU, "
            f"the rest in RAM — {self.reason}"
        )


def find_server() -> Path | None:
    for name in ("llama-server.exe", "llama-server"):
        found = shutil.which(name)
        if found:
            return Path(found)
        candidate = BIN_DIR / name
        if candidate.exists():
            return candidate
    return None


def cuda_dll_dirs() -> list[Path]:
    """Where the CUDA runtime DLLs can be found.

    llama.cpp's Windows CUDA build needs cudart/cublas/cublasLt beside the exe,
    which is what the separate ~370MB `cudart-*` release zip is for. But torch's
    CUDA wheel already ships those same DLLs, and CUDA 12.x minor versions are
    binary compatible — so if torch is installed, that download is redundant.

    Found by *path*, never by importing torch. Importing it here would load the
    CUDA runtime into whatever process asked — including the Streamlit UI, which
    then crashed with a heap corruption in ntdll (0xc0000374) once NVML was also
    being cycled on reruns. The UI needs a directory name, not a CUDA context.
    """
    dirs = [BIN_DIR]
    for site_packages in map(Path, sys.path):
        torch_lib = site_packages / "torch" / "lib"
        if (torch_lib / "cudart64_12.dll").exists() or (torch_lib / "libcudart.so.12").exists():
            dirs.append(torch_lib)
            break
    return [d for d in dirs if d.exists()]


def extract_release() -> Path | None:
    """Unpack whatever release zips were downloaded into vendor/llama.cpp."""
    zips = [z for z in sorted(VENDOR_DIR.glob("*.zip")) if z.stat().st_size > 0]
    if not zips:
        return None
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    for archive in zips:
        if not zipfile.is_zipfile(archive):
            print(f"skipping {archive.name} — not a valid zip (interrupted download?)")
            continue
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                # Release zips are flat or one level deep; flatten either way so
                # the DLLs land beside the exe that needs them.
                target = BIN_DIR / Path(member).name
                if target.exists():
                    continue
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    return find_server()


def plan_placement(
    entry: ModelEntry,
    context_tokens: int,
    probe: Probe | None = None,
) -> Placement:
    """How many layers fit on the card, right now.

    Uses live free VRAM rather than the cookbook's planning budget: the cookbook
    answers "what should we choose", this answers "what can we load at this
    moment", and those differ whenever something else is using the GPU.
    """
    probe = probe or run_probe()
    total_layers = entry.kv.layers if entry.kv else 32

    if not probe.gpu.present:
        return Placement(0, total_layers, "no usable GPU", 0, 0)

    available = max(0, probe.gpu.free_bytes - VRAM_SAFETY)
    needed = entry.footprint(context_tokens)

    if needed <= available:
        return Placement(total_layers, total_layers, "whole model fits in VRAM", needed, available)

    # Per-layer cost: its share of the weights plus its share of the KV cache.
    kv_bytes = entry.kv.bytes_at(context_tokens) if entry.kv else 0
    per_layer = (entry.weights_bytes + kv_bytes) / total_layers
    # Non-layer overhead lands on the GPU as soon as any layer does.
    usable = available - entry.runtime_overhead_bytes

    if per_layer <= 0 or usable <= per_layer:
        return Placement(
            0, total_layers,
            f"needs {human_bytes(needed)}, only {human_bytes(available)} free",
            needed, available,
        )

    layers = min(total_layers, int(usable // per_layer))
    logger.info(
        "partial offload: %d/%d layers on GPU (needs %s, %s free)",
        layers, total_layers, human_bytes(needed), human_bytes(available),
    )
    return Placement(
        layers, total_layers,
        f"needs {human_bytes(needed)}, {human_bytes(available)} free",
        needed, available,
    )


# eq=False keeps identity hashing. The generated __eq__ would set __hash__ to
# None, and the atexit WeakSet above needs these to be hashable.
@dataclass(eq=False)
class LlamaServer:
    """A llama-server subprocess, owned and cleaned up by this object."""

    model_path: Path
    context_tokens: int = 8192
    n_gpu_layers: int = 0
    host: str = "127.0.0.1"
    port: int = 8080
    # --jinja uses the model's own chat template rather than a built-in guess.
    # Required for `chat_template_kwargs` (which is how thinking gets switched
    # off) and later for tool calling on the admin surface.
    extra_args: tuple[str, ...] = ("--jinja",)
    process: subprocess.Popen | None = None
    # True when start() attached to a server someone else launched, in which
    # case our n_gpu_layers is a plan that was never applied.
    reused: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"

    def command(self) -> list[str]:
        server = find_server()
        if server is None:
            raise RuntimeError(
                "llama-server not found. Run `python -m runtime.llamacpp --setup` "
                "after downloading the release zips into vendor/llama.cpp/"
            )
        return [
            str(server),
            "--model", str(self.model_path),
            "--ctx-size", str(self.context_tokens),
            "--n-gpu-layers", str(self.n_gpu_layers),
            "--host", self.host,
            "--port", str(self.port),
            *self.extra_args,
        ]

    def already_running(self) -> bool:
        try:
            with httpx.Client(timeout=2.0) as client:
                return client.get(f"http://{self.host}:{self.port}/health").status_code < 500
        except Exception:
            return False

    def start(self, wait_seconds: int = 180) -> "LlamaServer":
        if self.already_running():
            self.reused = True
            logger.warning(
                "port %d already serving — attaching to it. Its actual layer "
                "split is whatever that process was started with, NOT the %d "
                "layers planned here.",
                self.port, self.n_gpu_layers,
            )
            return self

        logger.info(
            "starting llama-server: %s, ctx=%d, n_gpu_layers=%d, port=%d",
            self.model_path.name, self.context_tokens, self.n_gpu_layers, self.port,
        )
        env = dict(os.environ)
        # llama-server loads its CUDA DLLs from PATH. Torch's copies count.
        prefix = os.pathsep.join(str(d) for d in cuda_dll_dirs())
        env["PATH"] = f"{prefix}{os.pathsep}{env.get('PATH', '')}"

        self.process = subprocess.Popen(
            self.command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            errors="replace",
        )

        # Everything past the spawn runs guarded: any failure here must not
        # leave a subprocess holding several GB of VRAM with nobody owning it.
        try:
            _running.add(self)
            started = time.time()
            deadline = started + wait_seconds
            while time.time() < deadline:
                if self.process.poll() is not None:
                    output = self.process.stdout.read() if self.process.stdout else ""
                    logger.error("llama-server exited with %s", self.process.returncode)
                    raise RuntimeError(
                        f"llama-server exited with {self.process.returncode}.\n"
                        f"{output[-2000:]}"
                    )
                if self.already_running():
                    logger.info("llama-server healthy after %.1fs", time.time() - started)
                    return self
                time.sleep(1.0)

            raise RuntimeError(f"llama-server did not become healthy within {wait_seconds}s")
        except Exception:
            logger.exception("llama-server failed to come up — cleaning up the process")
            self.stop()
            raise

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            logger.info("stopping llama-server pid %s", self.process.pid)
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logger.warning("llama-server ignored terminate, killing")
                self.process.kill()
        self.process = None
        _running.discard(self)

    def __enter__(self) -> "LlamaServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def _setup() -> int:
    server = find_server()
    if server:
        print(f"llama-server already available: {server}")
        return 0
    print(f"extracting release zips in {VENDOR_DIR}")
    server = extract_release()
    if not server:
        print(
            "no llama-server found. Download a release from "
            "https://github.com/ggml-org/llama.cpp/releases into vendor/llama.cpp/ first "
            "(both the bin-win-cuda zip and the matching cudart zip)."
        )
        return 1
    print(f"ready: {server}")
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="llama.cpp server helper")
    parser.add_argument("--setup", action="store_true", help="extract downloaded release zips")
    args = parser.parse_args()
    raise SystemExit(_setup() if args.setup else _setup())
