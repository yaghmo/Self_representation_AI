"""HTTP front end for the cookbook.

The Next.js page in `web/` calls this instead of running Streamlit.
Same two modes as the old app — auto ranks every legal stack, manual checks a
choice — and nothing is written to `config/stack.json` until the confirm
endpoint is called, which re-evaluates the fit itself rather than trusting
the client.

Run:  uv run uvicorn cookbook.api:app --port 8001
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cookbook.config import build_config, read_config, write_config
from cookbook.download import fetch, is_complete, models_from_config, on_disk_bytes
from cookbook.fit import (
    Budget,
    Fit,
    Placement,
    Selection,
    auto_fit,
    bible_tokens,
    evaluate,
    largest_shortfall,
)
from cookbook.probe import Probe, run_probe
from cookbook.schema import Catalogue, ROLES, load_catalogue

app = FastAPI(title="Cookbook API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("COOKBOOK_UI_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# ------------------------------------------------------------- serialization --

def _probe_dict(probe: Probe) -> dict:
    gpu = probe.gpu
    return {
        "in_container": probe.in_container,
        "ram_total_bytes": probe.ram_total_bytes,
        "ram_available_bytes": probe.ram_available_bytes,
        "ram_ceiling_bytes": probe.ram_ceiling_bytes,
        "ram_ceiling_source": probe.ram_ceiling_source,
        "cpu_count": probe.cpu_count,
        "disk_free_bytes": probe.disk_free_bytes,
        "gpu": {
            "present": gpu.present,
            "name": gpu.name,
            "total_bytes": gpu.total_bytes,
            "free_bytes": gpu.free_bytes,
            "used_bytes": gpu.used_bytes,
            "driver": gpu.driver,
            "vendor": gpu.vendor,
            "diagnosis": gpu.diagnosis,
        },
        "internet": probe.internet,
        "installed_repos": sorted(probe.installed_repos),
        "warnings": probe.warnings,
    }


def _catalogue_dict(catalogue: Catalogue) -> dict:
    return {
        "bible_tokens": bible_tokens(),
        "models": [
            {
                "id": m.id,
                "role": m.role,
                "repo": m.repo,
                "weights_bytes": m.weights_bytes,
                "runtime_overhead_bytes": m.runtime_overhead_bytes,
                "devices": list(m.devices),
                "quality": m.quality,
                "quant": m.quant,
                "max_context": m.max_context,
                "kv": (
                    {
                        "layers": m.kv.layers,
                        "kv_heads": m.kv.kv_heads,
                        "head_dim": m.kv.head_dim,
                        "bytes_per_elem": m.kv.bytes_per_elem,
                    }
                    if m.kv
                    else None
                ),
                "cloning": m.cloning,
                "tool_calling": m.tool_calling,
                "figures": m.figures,
                "notes": m.notes,
            }
            for m in catalogue.models
        ],
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                "adapter": p.adapter,
                "api_key_env": p.api_key_env,
                "base_url": p.base_url,
                "default_model": p.default_model,
                "context_tokens": p.context_tokens,
                "free_tier": p.free_tier,
                "tool_calling": p.tool_calling,
                "notes": p.notes,
            }
            for p in catalogue.providers
        ],
    }


def _selection_dict(selection: Selection, catalogue: Catalogue) -> dict:
    """Placements keyed by role, resolving an API-backed LLM to its provider."""
    out: dict[str, dict] = {}
    for role in ROLES:
        placement = selection.placements.get(role)
        if role == "llm" and selection.llm_provider:
            out[role] = {
                "model": None,
                "device": None,
                "provider": catalogue.provider(selection.llm_provider).label,
            }
        elif role == "tts" and selection.tts_provider:
            out[role] = {
                "model": None,
                "device": None,
                "provider": catalogue.provider(selection.tts_provider).label,
            }
        elif role == "embedding" and selection.embedding_provider:
            out[role] = {
                "model": None,
                "device": None,
                "provider": catalogue.provider(selection.embedding_provider).label,
            }
        elif placement:
            out[role] = {"model": placement.model_id, "device": placement.device}
    return out


def _fit_dict(fit: Fit, catalogue: Catalogue) -> dict:
    return {
        "ok": fit.ok,
        "score": round(fit.score, 1),
        "strategy": fit.strategy,
        "context_tokens": fit.selection.context_tokens,
        "placements": _selection_dict(fit.selection, catalogue),
        "vram_used": fit.vram_used,
        "ram_used": fit.ram_used,
        "vram_over": fit.vram_over,
        "ram_over": fit.ram_over,
        "per_model": fit.per_model,
        "reasons": fit.reasons,
        "verdict": fit.verdict(),
    }


# -------------------------------------------------------------------- state --

_probe_cache: Probe | None = None


def _get_probe(fresh: bool = False) -> Probe:
    global _probe_cache
    if fresh or _probe_cache is None:
        _probe_cache = run_probe()
    return _probe_cache


# Download progress is polled straight off disk usage (on_disk_bytes vs the
# catalogue's expected total) rather than threaded through a callback, so the
# status endpoint stays correct even if the worker thread dies mid-file.
_download_models: list = []
_download_thread: threading.Thread | None = None
_download_errors: dict[str, str] = {}


def _download_worker(models: list) -> None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    for entry in models:
        if is_complete(entry):
            continue
        try:
            fetch(entry, token)
        except Exception as exc:  # noqa: BLE001 — surfaced via /api/download/status
            _download_errors[entry.id] = str(exc)


# ----------------------------------------------------------------- requests --


class SelectionIn(BaseModel):
    context_tokens: int
    placements: dict[str, dict]  # role -> {"model": id, "device": device}
    llm_provider: str | None = None  # set instead of placements["llm"] for an API-backed LLM
    tts_provider: str | None = None  # set instead of placements["tts"] for an API-backed TTS
    tts_voice_gender: str | None = None  # "male" | "female", api tts only
    embedding_provider: str | None = None  # set instead of placements["embedding"] for an API-backed embedder


class FitIn(BaseModel):
    selection: SelectionIn
    basis: str = "whole-machine"
    whole_bible_bonus: float = 12.0


class AutoIn(BaseModel):
    roles: list[str] = ["llm", "embedding", "tts"]
    require_cloning: bool = True
    whole_bible_bonus: float = 12.0
    basis: str = "whole-machine"


class ConfigIn(FitIn):
    agent: bool = False


def _selection_from(s: SelectionIn) -> Selection:
    placements = {
        role: Placement(p["model"], p["device"])
        for role, p in s.placements.items()
        if p.get("model")
    }
    return Selection(
        context_tokens=s.context_tokens,
        placements=placements,
        llm_provider=s.llm_provider,
        tts_provider=s.tts_provider,
        tts_voice_gender=s.tts_voice_gender,
        embedding_provider=s.embedding_provider,
    )


def _budget(basis: str, probe: Probe | None = None) -> Budget:
    probe = probe or _get_probe()
    return Budget.from_probe(probe, basis=basis)


# ----------------------------------------------------------------- endpooints --


@app.get("/api/probe")
def api_probe(fresh: bool = False) -> dict:
    return _probe_dict(_get_probe(fresh))


@app.get("/api/installed")
def api_installed() -> list[str]:
    """Model ids present in the local models/ directory."""
    model_dir = Path("models")
    if not model_dir.is_dir():
        return []
    return sorted(d.name for d in model_dir.iterdir() if d.is_dir() and not d.name.startswith("."))


@app.get("/api/catalogue")
def api_catalogue() -> dict:
    return _catalogue_dict(load_catalogue())


@app.post("/api/fit/auto")
def api_fit_auto(body: AutoIn) -> dict:
    catalogue = load_catalogue()
    budget = _budget(body.basis)
    fits = auto_fit(
        catalogue,
        budget,
        roles=body.roles,
        require_cloning=body.require_cloning,
        whole_bible_bonus=body.whole_bible_bonus,
    )
    if not fits:
        return {
            "fits": [],
            "shortfall": largest_shortfall(
                catalogue, budget, body.roles, body.require_cloning
            ),
        }
    return {"fits": [_fit_dict(f, catalogue) for f in fits], "shortfall": None}


@app.post("/api/fit/manual")
def api_fit_manual(body: FitIn) -> dict:
    catalogue = load_catalogue()
    fit = evaluate(
        _selection_from(body.selection),
        catalogue,
        _budget(body.basis),
        body.whole_bible_bonus,
    )
    return {**_fit_dict(fit, catalogue), "bible_tokens": bible_tokens()}


@app.get("/api/config")
def api_config_get() -> dict | None:
    return read_config()


@app.post("/api/config")
def api_config_write(body: ConfigIn) -> dict:
    catalogue = load_catalogue()
    probe = _get_probe()
    selection = _selection_from(body.selection)
    fit = evaluate(selection, catalogue, _budget(body.basis, probe), body.whole_bible_bonus)
    if not fit.ok:
        raise HTTPException(status_code=422, detail=fit.verdict())
    config = build_config(fit, catalogue, probe, agent=body.agent)
    path = write_config(config)
    config["_path"] = path.as_posix()
    return config


@app.post("/api/download/start")
def api_download_start() -> dict:
    global _download_models, _download_thread, _download_errors
    catalogue = load_catalogue()
    try:
        models = models_from_config(catalogue)
    except SystemExit:
        # An all-API-backed stack selects no local models — a no-op, not a
        # failure. SystemExit is BaseException, not Exception, so it would
        # otherwise skip Starlette's exception handling entirely and reach
        # the client as a CORS-header-less 500 ("Failed to fetch" in the browser).
        _download_models = []
        return api_download_status()
    if _download_thread is None or not _download_thread.is_alive():
        _download_models = models
        _download_errors = {}
        _download_thread = threading.Thread(
            target=_download_worker, args=(models,), daemon=True
        )
        _download_thread.start()
    return api_download_status()


class ProviderTestIn(BaseModel):
    provider_id: str
    api_key: str


def _write_env_key(env_var: str, value: str) -> None:
    """Upsert one KEY=value line into the repo-root .env, creating it from
    .env.example if it doesn't exist yet. .env is gitignored — this never
    touches a tracked file."""
    env_path = Path(".env")
    example_path = Path(".env.example")
    lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else example_path.read_text(encoding="utf-8").splitlines()
        if example_path.exists()
        else []
    )
    pattern = re.compile(rf"^{re.escape(env_var)}=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{env_var}={value}"
            break
    else:
        lines.append(f"{env_var}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _env_keys_present() -> dict[str, bool]:
    """Which provider env vars already have a non-empty value in .env.
    `_write_env_key` below only ever writes a key after `/api/provider/test`
    confirms it works, so presence here already means verified — no need to
    re-hit every provider's API just to render the cookbook page."""
    env_path = Path(".env")
    if not env_path.exists():
        return {}
    present: dict[str, bool] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        present[key.strip()] = bool(value.strip())
    return present


@app.get("/api/provider/keys")
def api_provider_keys() -> dict[str, bool]:
    catalogue = load_catalogue()
    env_present = _env_keys_present()
    return {p.id: env_present.get(p.api_key_env, False) for p in catalogue.providers}


@app.post("/api/provider/test")
def api_provider_test(body: ProviderTestIn) -> dict:
    """Verifies a key against the provider's own API before it's saved —
    the cookbook must never write a key to .env that doesn't actually work."""
    catalogue = load_catalogue()
    try:
        provider = catalogue.provider(body.provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # fish-audio and google speak their own APIs, not the OpenAI chat schema
    # their `adapter: "openai"` value nominally claims (that field only
    # matters to runtime/backend.py's LLM adapters, which the TTS/embedding
    # roles never reach) — each needs its own lightweight probe rather than
    # the generic /models check every real OpenAI-compatible LLM provider
    # gets. google in particular auths via a `?key=` query param, not a
    # Bearer header, so the generic path would send a valid key the wrong
    # way and always report it as bad.
    base_url = (provider.base_url or "").rstrip("/")
    if provider.id == "fish-audio":
        test_url = f"{base_url}/wallet/self/api-credit"
        params, headers = {}, {"Authorization": f"Bearer {body.api_key}"}
    elif provider.id == "google":
        test_url = f"{base_url}/models"
        params, headers = {"key": body.api_key}, {}
    elif provider.adapter != "openai":
        raise HTTPException(
            status_code=400,
            detail=f"no test support for the {provider.adapter!r} adapter yet",
        )
    else:
        test_url = f"{base_url}/models"
        params, headers = {}, {"Authorization": f"Bearer {body.api_key}"}
    try:
        resp = httpx.get(
            test_url,
            params=params,
            headers=headers,
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": str(exc)}
    if resp.status_code >= 400:
        return {"ok": False, "detail": f"HTTP {resp.status_code}"}
    _write_env_key(provider.api_key_env, body.api_key)
    return {"ok": True, "detail": f"HTTP {resp.status_code}"}


@app.get("/api/download/status")
def api_download_status() -> dict:
    models = [
        {
            "id": entry.id,
            "role": entry.role,
            "total_bytes": entry.download.total_bytes if entry.download else 0,
            "downloaded_bytes": on_disk_bytes(entry),
            "done": is_complete(entry),
            "error": _download_errors.get(entry.id),
        }
        for entry in _download_models
    ]
    return {
        "models": models,
        "active": _download_thread is not None and _download_thread.is_alive(),
    }
