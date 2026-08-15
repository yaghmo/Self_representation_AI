"""Machine probe. Runs inside the container, on purpose.

The number that matters is not what the host has, it is what this process is
allowed to take. Inside a container `psutil` cheerfully reports the *host's*
RAM, which is how you approve a stack that then gets OOM-killed on load. So
the cgroup limit wins whenever one is set.

The GPU has the same trap in a different shape: "no GPU found" inside a
container usually means the container was started without passthrough, not
that the machine lacks a card. Those two get told apart and reported
differently, because the fixes are nothing alike.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .schema import GB, human_bytes

try:
    import psutil
except ImportError:  # pragma: no cover - dependency is declared, not optional
    psutil = None  # type: ignore[assignment]


@dataclass
class GPUInfo:
    present: bool
    name: str = ""
    total_bytes: int = 0
    free_bytes: int = 0
    driver: str = ""
    vendor: str = "nvidia"
    diagnosis: str = ""

    @property
    def used_bytes(self) -> int:
        return max(0, self.total_bytes - self.free_bytes)


@dataclass
class Probe:
    in_container: bool
    ram_total_bytes: int
    ram_available_bytes: int
    ram_ceiling_bytes: int
    ram_ceiling_source: str
    cpu_count: int
    disk_free_bytes: int
    gpu: GPUInfo
    internet: bool
    installed_repos: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"container: {'yes' if self.in_container else 'no'}",
            f"RAM ceiling: {human_bytes(self.ram_ceiling_bytes)} ({self.ram_ceiling_source})",
            f"RAM available now: {human_bytes(self.ram_available_bytes)}",
            f"CPU cores: {self.cpu_count}",
            f"disk free: {human_bytes(self.disk_free_bytes)}",
        ]
        if self.gpu.present:
            lines.append(
                f"GPU: {self.gpu.name} — {human_bytes(self.gpu.free_bytes)} free "
                f"of {human_bytes(self.gpu.total_bytes)}"
            )
        else:
            lines.append(f"GPU: none usable — {self.gpu.diagnosis}")
        lines.append(f"internet: {'reachable' if self.internet else 'unreachable'}")
        return "\n".join(lines)


def _detect_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if text in ("max", ""):
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    # cgroup v1 writes a sentinel near 2**63 to mean "unlimited".
    return None if value <= 0 or value > (1 << 62) else value


def _cgroup_limit() -> tuple[int | None, str]:
    v2 = _read_int(Path("/sys/fs/cgroup/memory.max"))
    if v2 is not None:
        return v2, "cgroup v2 memory.max"
    v1 = _read_int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
    if v1 is not None:
        return v1, "cgroup v1 memory.limit_in_bytes"
    return None, ""


def _nvidia_driver_visible() -> bool:
    """Is there any sign of an NVIDIA stack, even a broken one?"""
    if shutil.which("nvidia-smi"):
        return True
    if any(Path("/dev").glob("nvidia*")):
        return True
    return Path("/proc/driver/nvidia/version").exists()


def probe_gpu() -> GPUInfo:
    try:
        import pynvml
    except ImportError:
        return GPUInfo(
            present=False,
            diagnosis=(
                "pynvml not installed, so VRAM cannot be measured. "
                "Install nvidia-ml-py, or accept a CPU-only fit."
            ),
        )

    try:
        pynvml.nvmlInit()
    except Exception as exc:  # NVML raises its own error type
        if _nvidia_driver_visible():
            return GPUInfo(
                present=False,
                diagnosis=(
                    "NVIDIA driver files are visible but NVML would not "
                    f"initialise ({exc}). Inside a container this normally means "
                    "the GPU was not passed through — start it with "
                    "`--gpus all` and the NVIDIA Container Toolkit installed."
                ),
            )
        return GPUInfo(
            present=False,
            diagnosis="no NVIDIA driver and no NVML — treating this as a CPU-only machine.",
        )

    try:
        count = pynvml.nvmlDeviceGetCount()
        if count == 0:
            return GPUInfo(
                present=False,
                diagnosis=(
                    "NVML initialised but reports zero devices — usually a "
                    "container started without `--gpus`, or NVIDIA_VISIBLE_DEVICES "
                    f"set to exclude everything (currently "
                    f"{os.environ.get('NVIDIA_VISIBLE_DEVICES', 'unset')!r})."
                ),
            )

        # Multi-GPU is out of scope: the fitter reasons about one pool. Take
        # the card with the most free VRAM and say so.
        best = None
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            if best is None or mem.free > best[1].free:
                best = (name, mem)

        assert best is not None
        name, mem = best
        try:
            driver = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(driver, bytes):
                driver = driver.decode()
        except Exception:
            driver = ""

        note = f"{count} GPUs found; fitting against the one with most free VRAM" if count > 1 else ""
        return GPUInfo(
            present=True,
            name=name,
            total_bytes=int(mem.total),
            free_bytes=int(mem.free),
            driver=driver,
            diagnosis=note,
        )
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _internet_reachable(timeout: float = 1.5) -> bool:
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _hf_cache_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def scan_installed_repos() -> set[str]:
    """Repo ids already on disk, so the report can mark a model as a zero-byte
    download instead of telling you to fetch 5GB you already have."""
    cache = _hf_cache_dir()
    if not cache.is_dir():
        return set()
    found: set[str] = set()
    for entry in cache.iterdir():
        # huggingface_hub stores "models--org--name"
        if entry.is_dir() and entry.name.startswith("models--"):
            found.add(entry.name[len("models--") :].replace("--", "/"))
    return found


def run_probe(model_dir: Path | None = None) -> Probe:
    warnings: list[str] = []

    if psutil is None:
        raise RuntimeError("psutil is required — uv sync")

    in_container = _detect_container()
    vm = psutil.virtual_memory()
    ram_total = int(vm.total)
    ram_available = int(vm.available)

    limit, source = _cgroup_limit()
    if limit is not None and limit < ram_total:
        ram_ceiling, ceiling_source = limit, source
    else:
        ram_ceiling, ceiling_source = ram_total, "host RAM (no cgroup limit set)"
        if in_container:
            warnings.append(
                "Running in a container with no memory limit, so these figures "
                "are the host's. On Docker Desktop the real ceiling is the WSL2 "
                "VM's allowance — check `memory=` in .wslconfig before trusting a fit."
            )

    if in_container and limit is not None:
        current = _read_int(Path("/sys/fs/cgroup/memory.current"))
        if current is not None:
            ram_available = min(ram_available, max(0, limit - current))

    target = model_dir or _hf_cache_dir()
    probe_target = target if target.exists() else Path.cwd()
    disk_free = int(shutil.disk_usage(probe_target).free)

    gpu = probe_gpu()
    if not gpu.present and in_container:
        warnings.append(
            "No usable GPU inside the container. Confirm this is real before "
            "settling for a CPU fit — the host may well have a card that was "
            "simply not passed through."
        )

    return Probe(
        in_container=in_container,
        ram_total_bytes=ram_total,
        ram_available_bytes=ram_available,
        ram_ceiling_bytes=ram_ceiling,
        ram_ceiling_source=ceiling_source,
        cpu_count=psutil.cpu_count(logical=True) or 1,
        disk_free_bytes=disk_free,
        gpu=gpu,
        internet=_internet_reachable(),
        installed_repos=scan_installed_repos(),
        warnings=warnings,
    )


if __name__ == "__main__":
    p = run_probe()
    print(p.summary())
    for w in p.warnings:
        print(f"\n! {w}")
    if p.installed_repos:
        print(f"\nalready on disk: {len(p.installed_repos)} repos")
