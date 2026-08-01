"""The Model class: takes a stack config, gives you something you can talk to.

Deliberately thinner than it might be, because the sizing work already happened.
The cookbook resolved real weights, real KV geometry, a memory budget that
respects cgroup limits, and wrote the answer to `config/stack.<surface>.json`.
Re-deriving any of that at load time would mean two sources of truth that
disagree the first time one of them changes.

So this class does four things:

    resolve   — find the weights on disk for the configured model
    place     — decide GPU / partial / CPU against *live* free memory
    serve     — bring up llama-server, or point at an API
    talk      — chat() and stream(), same signature either way
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from cookbook.config import config_path, read_config
from cookbook.download import target_dir
from cookbook.probe import Probe, run_probe
from cookbook.schema import Catalogue, ModelEntry, human_bytes, load_catalogue

from service.logging_config import get_logger

from .backend import Backend, Message, from_role_config
from .llamacpp import LlamaServer, Placement, plan_placement

logger = get_logger("runtime.model")

REPO_ROOT = Path(__file__).resolve().parent.parent


class ModelNotDownloaded(RuntimeError):
    pass


@dataclass
class Model:
    """One configured LLM, local or hosted."""

    entry: ModelEntry | None            # None when the LLM is API-backed
    role_config: dict
    context_tokens: int
    surface: str = "user"
    bible_strategy: str = "retrieval"
    port: int = 8080

    _backend: Backend | None = field(default=None, init=False, repr=False)
    _server: LlamaServer | None = field(default=None, init=False, repr=False)
    _placement: Placement | None = field(default=None, init=False, repr=False)
    _probe: Probe | None = field(default=None, init=False, repr=False)

    # ---------------------------------------------------------------- build --

    @classmethod
    def from_config(
        cls,
        surface: str = "user",
        catalogue: Catalogue | None = None,
        port: int = 8080,
    ) -> "Model":
        config = read_config(surface)
        if not config:
            raise FileNotFoundError(
                f"{config_path(surface)} does not exist — run the cookbook and confirm a stack"
            )
        catalogue = catalogue or load_catalogue()
        role = config["roles"]["llm"]
        entry = None if role.get("source") == "api" else catalogue.model(role["model_id"])
        return cls(
            entry=entry,
            role_config=role,
            context_tokens=config.get("context_tokens", 8192),
            surface=config.get("surface", surface),
            bible_strategy=config.get("bible_strategy", "retrieval"),
            port=port,
        )

    # -------------------------------------------------------------- resolve --

    @property
    def is_api(self) -> bool:
        return self.role_config.get("source") == "api"

    @property
    def name(self) -> str:
        if self.is_api:
            return f"{self.role_config.get('provider', 'api')}:{self.role_config.get('model', '')}"
        return self.entry.id if self.entry else "unknown"

    def weights_path(self) -> Path:
        """The single file or directory llama.cpp should be pointed at."""
        if self.entry is None:
            raise RuntimeError("API-backed model has no local weights")
        directory = target_dir(self.entry)
        if not directory.is_dir():
            raise ModelNotDownloaded(
                f"{self.entry.id} is not downloaded — "
                f"python -m cookbook.download --models {self.entry.id}"
            )
        wanted = self.entry.download.file if self.entry.download else None
        if wanted:
            candidate = directory / wanted
            if candidate.exists():
                return candidate
        ggufs = sorted(directory.rglob("*.gguf"))
        if ggufs:
            return ggufs[0]
        raise ModelNotDownloaded(f"no .gguf found under {directory}")

    # ---------------------------------------------------------------- place --

    def placement(self, refresh: bool = False) -> Placement:
        """GPU, partial, or CPU — decided against memory free *now*.

        This is the fallback the whole class exists for. The cookbook says what
        should fit on an idle machine; this says what actually loads today, with
        a browser open and something else holding VRAM.
        """
        if self.is_api:
            raise RuntimeError("API-backed model is not placed locally")
        if self._placement is None or refresh:
            self._probe = run_probe()
            self._placement = plan_placement(self.entry, self.context_tokens, self._probe)
        return self._placement

    # ---------------------------------------------------------------- serve --

    def load(self, wait_seconds: int = 180) -> "Model":
        if self._backend is not None:
            return self

        if self.is_api:
            self._backend = from_role_config(self.role_config)
            return self

        placement = self.placement()
        logger.info("loading %s — %s", self.name, placement.describe())
        self._server = LlamaServer(
            model_path=self.weights_path(),
            context_tokens=self.context_tokens,
            n_gpu_layers=placement.n_gpu_layers,
            port=self.port,
        ).start(wait_seconds=wait_seconds)

        self._backend = from_role_config(
            {**self.role_config, "base_url": self._server.base_url}
        )
        return self

    def unload(self) -> None:
        if self._server:
            logger.info("unloading %s", self.name)
            self._server.stop()
        self._server = None
        self._backend = None

    @property
    def loaded(self) -> bool:
        return self._backend is not None

    # ----------------------------------------------------------------- talk --

    def chat(self, messages: list[Message], **kwargs) -> str:
        if not self.loaded:
            self.load()
        assert self._backend is not None
        return self._backend.complete(messages, **kwargs)

    def stream(self, messages: list[Message], **kwargs) -> Iterator[str]:
        if not self.loaded:
            self.load()
        assert self._backend is not None
        yield from self._backend.stream(messages, **kwargs)

    def count_tokens(self, text: str) -> int:
        """Exact count from the loaded backend, estimate when nothing is loaded."""
        if self._backend is not None and hasattr(self._backend, "count_tokens"):
            return self._backend.count_tokens(text)
        from .bible import estimate_tokens

        return estimate_tokens(text)

    # ---------------------------------------------------------------- state --

    def status(self) -> dict:
        state: dict = {
            "name": self.name,
            "surface": self.surface,
            "source": "api" if self.is_api else "local",
            "context_tokens": self.context_tokens,
            "bible_strategy": self.bible_strategy,
            "loaded": self.loaded,
        }
        if self.is_api:
            state["endpoint"] = self.role_config.get("base_url")
            return state

        state["weights"] = str(self.weights_path()) if self.entry else None
        if self._server is not None and self._server.reused:
            state["reused_server"] = True
        try:
            placement = self.placement()
            state.update(
                mode=placement.mode,
                detail=(
                    "attached to a server that was already running — its layer "
                    "split is not the one planned here"
                    if state.get("reused_server")
                    else placement.describe()
                ),
                n_gpu_layers=placement.n_gpu_layers,
                total_layers=placement.total_layers,
                vram_needed=human_bytes(placement.vram_needed),
                vram_available=human_bytes(placement.vram_available),
            )
        except Exception as exc:
            state["placement_error"] = str(exc)
        return state

    def __enter__(self) -> "Model":
        return self.load()

    def __exit__(self, *exc) -> None:
        self.unload()


if __name__ == "__main__":
    import json

    model = Model.from_config("user")
    print(json.dumps(model.status(), indent=2))
