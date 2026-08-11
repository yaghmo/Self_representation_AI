"""Catalogue types and the footprint math.

One rule holds the whole module together: a model's memory cost is not a
constant. Weights are, but the KV cache grows linearly with context length,
and for a chat model at long context it is routinely larger than the gap
between two model sizes. So context length is an *input* to fitting, never
an afterthought.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

GB = 1024**3
MB = 1024**2

Role = Literal["llm", "embedding", "tts"]
Device = Literal["gpu", "cpu"]

# How a model does tool calling.
#   native   — trained for it, with a chat template that emits structured calls
#   prompted — only by asking for JSON in the prompt; parses until it doesn't
#   none     — no meaningful support
ToolCalling = Literal["native", "prompted", "none"]

ROLES: tuple[Role, ...] = ("llm", "embedding", "tts")


@dataclass(frozen=True)
class KVGeometry:
    """Shape of one model's KV cache. Grouped-query models have fewer
    kv_heads than attention heads — that difference is most of why a modern
    8B is cheaper at long context than an older 7B."""

    layers: int
    kv_heads: int
    head_dim: int
    bytes_per_elem: int = 2  # fp16 cache

    def bytes_at(self, context_tokens: int) -> int:
        # 2 = one K tensor and one V tensor per layer.
        return (
            2
            * self.layers
            * self.kv_heads
            * self.head_dim
            * context_tokens
            * self.bytes_per_elem
        )


@dataclass(frozen=True)
class Voice:
    """One selectable voice for a TTS model.

    The mechanism differs by model class:
      cloning models (xtts, f5, qwen3-base) — there is no male/female flag at
        inference, the reference clip *is* the voice. `src` points at the
        creator's recorded clip (data/voice/*.wav).
      fixed-voice models (kokoro) — the model ships named speakers and `src`
        is that speaker id (e.g. "af_bella").
    """

    id: str
    label: str
    gender: Literal["female", "male"]
    src: str = ""


@dataclass(frozen=True)
class Download:
    """Where the weights actually come from.

    Not the same thing as the model's home repo, and conflating the two is a
    good way to pull 16GB of fp16 safetensors when the fitter budgeted 5GB of
    Q4_K_M. A quantised LLM lives in a different repo from the model it was
    quantised from.
    """

    repo: str
    file: str | None = None  # single-file download, e.g. one .gguf
    allow_patterns: tuple[str, ...] = ()  # otherwise, which files of the repo
    # Patterns are fnmatch, where `*` crosses directory separators — so
    # `*.json` happily matches `onnx/config.json`. These exclusions are what
    # stops a repo's alternative format being pulled alongside the one wanted.
    ignore_patterns: tuple[str, ...] = ()
    gated: bool = False  # needs an accepted licence and a token
    total_bytes: int | None = None  # real size, filled in by refresh.py


@dataclass(frozen=True)
class ModelEntry:
    id: str
    role: Role
    repo: str
    weights_bytes: int
    runtime_overhead_bytes: int
    devices: tuple[Device, ...]
    quality: int  # 0-100, judgment call, relative within a role only
    quant: str | None = None
    max_context: int | None = None
    kv: KVGeometry | None = None
    cloning: bool | None = None  # tts only: can it clone a voice
    voices: tuple[Voice, ...] = ()  # tts only: selectable voices (see Voice)
    tool_calling: ToolCalling = "none"  # llm only: gates the admin surface
    download: Download | None = None
    # estimated — derived from parameter counts and quant ratios
    # hub       — real file sizes and real config.json geometry from the hub
    # measured  — loaded on this machine, read off nvidia-smi
    figures: str = "estimated"
    notes: str = ""

    @property
    def verified(self) -> bool:
        return self.figures == "measured"

    def footprint(self, context_tokens: int = 0) -> int:
        total = self.weights_bytes + self.runtime_overhead_bytes
        if self.kv is not None and context_tokens:
            total += self.kv.bytes_at(context_tokens)
        return total

    def supports(self, device: Device) -> bool:
        return device in self.devices

    def fits_context(self, context_tokens: int) -> bool:
        return self.max_context is None or context_tokens <= self.max_context


@dataclass(frozen=True)
class Provider:
    """An API-backed LLM. Two adapters exist in code — `openai` and
    `anthropic`. Every other provider is data riding the generic one, so
    adding one is a JSON edit rather than a code change."""

    id: str
    label: str
    adapter: Literal["openai", "anthropic"]
    api_key_env: str
    base_url: str | None = None
    default_model: str = ""
    context_tokens: int = 128_000
    free_tier: str = ""
    tool_calling: bool = True  # every hosted frontier model does this well
    notes: str = ""


@dataclass
class Catalogue:
    models: list[ModelEntry] = field(default_factory=list)
    providers: list[Provider] = field(default_factory=list)

    def by_role(self, role: Role) -> list[ModelEntry]:
        """Candidates for a role.

        The LLM list is always narrowed to native tool calling. One stack has
        to be able to serve agent mode, since the mode is a flag that flips
        without re-fitting — and a model that cannot emit a parseable tool call
        is not an agent, it is a chatbot describing what it would have done.
        `"prompted"` models can be coaxed into JSON but have no tool tokens in
        their chat template, which is fine for chat and not for an agent whose
        failure mode is corrupting `sources.md`.
        """
        out = [m for m in self.models if m.role == role]
        if role == "llm":
            return [m for m in out if m.tool_calling == "native"]
        return out

    def model(self, model_id: str) -> ModelEntry:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(f"no model {model_id!r} in catalogue")

    def provider(self, provider_id: str) -> Provider:
        for p in self.providers:
            if p.id == provider_id:
                return p
        raise KeyError(f"no provider {provider_id!r} in catalogue")

    @property
    def unverified(self) -> list[ModelEntry]:
        return [m for m in self.models if not m.verified]

    @property
    def estimated(self) -> list[ModelEntry]:
        """Entries whose figures are still guesses — refresh.py has not seen them."""
        return [m for m in self.models if m.figures == "estimated"]


def _model_from_dict(d: dict) -> ModelEntry:
    kv = KVGeometry(**d["kv"]) if d.get("kv") else None
    download = None
    if d.get("download"):
        raw = dict(d["download"])
        raw["allow_patterns"] = tuple(raw.get("allow_patterns", ()))
        raw["ignore_patterns"] = tuple(raw.get("ignore_patterns", ()))
        download = Download(**raw)
    voices = tuple(Voice(**v) for v in d.get("voices", ()))
    return ModelEntry(
        id=d["id"],
        role=d["role"],
        repo=d["repo"],
        weights_bytes=int(d["weights_bytes"]),
        runtime_overhead_bytes=int(d["runtime_overhead_bytes"]),
        devices=tuple(d["devices"]),
        quality=int(d["quality"]),
        quant=d.get("quant"),
        max_context=d.get("max_context"),
        kv=kv,
        cloning=d.get("cloning"),
        voices=voices,
        tool_calling=d.get("tool_calling", "none"),
        download=download,
        figures=d.get("figures", "estimated"),
        notes=d.get("notes", ""),
    )


def load_catalogue(
    catalogue_path: Path | None = None,
    providers_path: Path | None = None,
) -> Catalogue:
    here = Path(__file__).parent
    catalogue_path = catalogue_path or here / "catalogue.json"
    providers_path = providers_path or here / "providers.json"

    raw = json.loads(catalogue_path.read_text(encoding="utf-8"))
    models = [_model_from_dict(d) for d in raw["models"]]

    raw_p = json.loads(providers_path.read_text(encoding="utf-8"))
    providers = [Provider(**d) for d in raw_p["providers"]]

    seen: set[str] = set()
    for m in models:
        if m.id in seen:
            raise ValueError(f"duplicate model id {m.id!r} in catalogue")
        seen.add(m.id)

    return Catalogue(models=models, providers=providers)


def human_bytes(n: float) -> str:
    if n < 0:
        return "-" + human_bytes(-n)
    for unit, size in (("GB", GB), ("MB", MB)):
        if n >= size:
            return f"{n / size:.2f} {unit}"
    return f"{int(n)} B"
