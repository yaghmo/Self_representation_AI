"""Writes the one artifact the rest of the app consumes.

`config/stack.json` is the contract: container boot reads it, starts one
server per role, and hands the prompt-assembly layer its context budget and
bible strategy. It is written only on an explicit confirmation — the cookbook
never picks silently.

It holds no secrets. API keys live in the environment; this file records only
the *name* of the variable to read.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .fit import Fit
from .probe import Probe
from .schema import Catalogue

CONFIG_VERSION = 1
CONFIG_DIR = Path("config")


def config_path(surface: str = "user") -> Path:
    """One config per surface. They are genuinely different stacks — the admin
    agent needs a tool-calling model and the user bot does not — so a single
    stack.json would mean each choice silently destroying the other.
    """
    return CONFIG_DIR / f"stack.{surface}.json"


def build_config(fit: Fit, catalogue: Catalogue, probe: Probe) -> dict:
    selection = fit.selection
    roles: dict[str, dict] = {}

    for role, placement in selection.placements.items():
        if role == "llm" and selection.llm_provider:
            continue
        model = catalogue.model(placement.model_id)
        roles[role] = {
            "source": "local",
            "model_id": model.id,
            "repo": model.repo,
            "quant": model.quant,
            "device": placement.device,
            "estimated_bytes": fit.per_model.get(role, 0),
            "figures": model.figures,
        }
        if role == "llm":
            roles[role]["tool_calling"] = model.tool_calling

    if selection.llm_provider:
        provider = catalogue.provider(selection.llm_provider)
        roles["llm"] = {
            "source": "api",
            "provider": provider.id,
            "adapter": provider.adapter,
            "base_url": provider.base_url,
            "model": provider.default_model,
            "api_key_env": provider.api_key_env,
            "context_tokens": provider.context_tokens,
            "tool_calling": "native" if provider.tool_calling else "none",
        }

    return {
        "version": CONFIG_VERSION,
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "surface": selection.surface,
        "agent": selection.surface == "admin",
        "context_tokens": selection.context_tokens,
        "bible_strategy": fit.strategy,
        "roles": roles,
        "estimated_footprint": {
            "vram_bytes": fit.vram_used,
            "ram_bytes": fit.ram_used,
        },
        "probed_machine": {
            "in_container": probe.in_container,
            "gpu": probe.gpu.name or None,
            "gpu_free_bytes": probe.gpu.free_bytes,
            "ram_ceiling_bytes": probe.ram_ceiling_bytes,
            "ram_ceiling_source": probe.ram_ceiling_source,
        },
        "_warning": (
            "Estimated footprints, not measurements. If a server OOMs on boot, "
            "re-run the cookbook rather than editing this file by hand."
        ),
    }


def write_config(config: dict, path: Path | None = None) -> Path:
    path = path or config_path(config.get("surface", "user"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def read_config(surface: str = "user", path: Path | None = None) -> dict | None:
    path = path or config_path(surface)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
