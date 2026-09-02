"""The fitter.

Fits the whole stack at once, which is the part off-the-shelf tools don't do.
Every enabled role is resident simultaneously — models come up as servers at
container boot and nothing swaps mid-session — so the constraint is a plain
sum over enabled roles, checked against two separate pools: VRAM and RAM.

Placement is part of the search, not an afterthought. The embedding model is
small enough to sit on the CPU for free, and letting it compete for VRAM
against the LLM is how you end up one quant tier lower for no reason.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from .probe import Probe
from .schema import GB, MB, Catalogue, Device, ModelEntry, Role, human_bytes

# What the stack has to hold in context.
#
# Measured from the real file when it exists; the repo ships templates and
# `data/` may be absent. Deliberately not imported from `runtime` — the cookbook
# installs standalone and `runtime` already depends on it.
DEFAULT_PROFILE_TOKENS = 8_000

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def bible_tokens() -> int:
    """Tokens of profile the model must hold.

    One number for both modes. The agent reads `sources.md` through tools —
    searching and appending, never holding the corpus in context — so there is
    no surface that needs it resident.
    """
    return _measure(DATA_DIR / "character.md", DEFAULT_PROFILE_TOKENS)


def _measure(path: Path, fallback: int) -> int:
    try:
        return len(path.read_text(encoding="utf-8")) // 4
    except OSError:
        return fallback


# Room left for the conversation and the model's reply once the bible is in.
CONVERSATION_RESERVE_TOKENS = 4_000

CONTEXT_CANDIDATES: tuple[int, ...] = (4_096, 8_192, 16_384, 32_768, 65_536)

ROLE_WEIGHT: dict[Role, float] = {"llm": 0.60, "embedding": 0.15, "tts": 0.25}

# Cost of putting a role on the CPU. Not a flat number: CPU generation slows
# roughly with model size, so an 8B on CPU is far worse than a 1.7B on CPU,
# and a flat penalty would rank them as equally bad. Embedding is free there —
# it runs once per query on short text.
CPU_PENALTY_BASE: dict[Role, float] = {"llm": 15.0, "embedding": 0.0, "tts": 10.0}
CPU_PENALTY_PER_GB: dict[Role, float] = {"llm": 4.0, "embedding": 0.0, "tts": 1.0}

# How much a whole-bible context is worth against raw model quality. High
# values buy fidelity to the character at the cost of a smaller model. This is
# a taste setting and the UI exposes it.
DEFAULT_WHOLE_BIBLE_BONUS = 12.0


def cpu_penalty(role: Role, model: ModelEntry) -> float:
    weights_gb = model.weights_bytes / GB
    return CPU_PENALTY_BASE[role] + CPU_PENALTY_PER_GB[role] * weights_gb

Strategy = Literal["whole-bible", "retrieval"]


Basis = Literal["free-now", "whole-machine"]


@dataclass(frozen=True)
class Budget:
    vram_bytes: int
    ram_bytes: int
    vram_raw: int
    ram_raw: int
    has_gpu: bool
    basis: Basis = "whole-machine"

    @classmethod
    def from_probe(
        cls,
        probe: Probe,
        basis: Basis = "whole-machine",
        vram_headroom_frac: float = 0.10,
        vram_headroom_fixed: int = 384 * MB,
        ram_headroom_frac: float = 0.05,
    ) -> "Budget":
        """Two honest answers to "how much memory is there", and they differ by
        gigabytes on a working desktop.

        `free-now` fits against what is unused at this instant. Truthful, but it
        makes the recommendation depend on whether a browser happened to be open
        when you clicked probe.

        `whole-machine` fits against total capacity minus a reserve for the OS,
        which is the right basis for a container you start deliberately after
        closing things. Default, because the alternative silently punishes you
        for probing at the wrong moment.
        """
        if basis == "free-now":
            vram_raw = probe.gpu.free_bytes if probe.gpu.present else 0
            # Ceiling, not host total: in a container the cgroup limit is what
            # the process actually gets, whatever psutil reports.
            ram_raw = min(probe.ram_ceiling_bytes, probe.ram_available_bytes)
            ram_reserve = 1 * GB
        else:
            vram_raw = probe.gpu.total_bytes if probe.gpu.present else 0
            ram_raw = probe.ram_ceiling_bytes
            # Bigger reserve: the OS and whatever else survives the cleanup
            # still need room once the stack is resident.
            ram_reserve = 3 * GB

        vram = max(0, int(vram_raw * (1 - vram_headroom_frac)) - vram_headroom_fixed)
        ram = max(0, int(ram_raw * (1 - ram_headroom_frac)) - ram_reserve)

        return cls(
            vram_bytes=vram,
            ram_bytes=ram,
            vram_raw=vram_raw,
            ram_raw=ram_raw,
            has_gpu=probe.gpu.present,
            basis=basis,
        )


@dataclass(frozen=True)
class Placement:
    model_id: str
    device: Device


@dataclass(frozen=True)
class Selection:
    """What to run. `llm_provider` set means the LLM is API-backed, so it has
    no local footprint at all and only the other roles get checked."""

    context_tokens: int
    placements: dict[Role, Placement] = field(default_factory=dict)
    llm_provider: str | None = None
    tts_provider: str | None = None
    tts_voice_gender: str | None = None


@dataclass
class Fit:
    selection: Selection
    ok: bool
    vram_used: int
    ram_used: int
    vram_over: int
    ram_over: int
    strategy: Strategy
    score: float
    per_model: dict[Role, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def over_by(self) -> int:
        return max(self.vram_over, self.ram_over)

    def verdict(self) -> str:
        if self.ok:
            return "fits"
        parts = []
        if self.vram_over > 0:
            parts.append(f"{human_bytes(self.vram_over)} over VRAM")
        if self.ram_over > 0:
            parts.append(f"{human_bytes(self.ram_over)} over RAM")
        if not parts:
            # Not a memory problem — an illegal combination.
            return "invalid — " + "; ".join(self.reasons)
        return "bricks — " + ", ".join(parts)


def strategy_for(context_tokens: int) -> Strategy:
    needed = bible_tokens() + CONVERSATION_RESERVE_TOKENS
    return "whole-bible" if context_tokens >= needed else "retrieval"


def evaluate(
    selection: Selection,
    catalogue: Catalogue,
    budget: Budget,
    whole_bible_bonus: float = DEFAULT_WHOLE_BIBLE_BONUS,
) -> Fit:
    vram_used = 0
    ram_used = 0
    per_model: dict[Role, int] = {}
    reasons: list[str] = []
    blockers: list[str] = []
    quality = 0.0
    weight_total = 0.0

    api_backed = selection.llm_provider is not None
    tts_api_backed = selection.tts_provider is not None

    for role, placement in selection.placements.items():
        if role == "llm" and api_backed:
            continue
        if role == "tts" and tts_api_backed:
            continue
        model = catalogue.model(placement.model_id)
        context = selection.context_tokens if model.kv else 0
        cost = model.footprint(context)
        per_model[role] = cost

        if placement.device == "gpu":
            vram_used += cost
        elif placement.device == "cpu":
            ram_used += cost
        # transient-gpu: loaded only for the duration of one synth batch,
        # never resident — excluded from both steady-state pools entirely.

        if not model.supports(placement.device):
            blockers.append(f"{model.id} cannot run on {placement.device}")
        if not model.fits_context(selection.context_tokens):
            blockers.append(
                f"{model.id} maxes out at {model.max_context} tokens, "
                f"{selection.context_tokens} requested"
            )

        weight = ROLE_WEIGHT[role]
        penalty = cpu_penalty(role, model) if placement.device == "cpu" else 0.0
        quality += (model.quality - penalty) * weight
        weight_total += weight

    if api_backed:
        provider = catalogue.provider(selection.llm_provider or "")
        weight = ROLE_WEIGHT["llm"]
        # An API model is assumed to beat anything that fits locally on a
        # consumer card. It is the ceiling, not a compromise.
        quality += 95.0 * weight
        weight_total += weight
        reasons.append(
            f"LLM served by {provider.label} — no local footprint, "
            f"{provider.context_tokens:,} token context"
        )

    if tts_api_backed:
        tts_provider = catalogue.provider(selection.tts_provider or "")
        weight = ROLE_WEIGHT["tts"]
        # Same reasoning as the LLM api_backed branch: a hosted TTS model is
        # the ceiling here too, not a compromise against a local one.
        quality += 95.0 * weight
        weight_total += weight
        reasons.append(f"TTS served by {tts_provider.label} — no local footprint")

    if not budget.has_gpu and any(
        p.device in ("gpu", "transient-gpu") for p in selection.placements.values()
    ):
        blockers.append("no usable GPU, yet something was placed on one")

    vram_over = max(0, vram_used - budget.vram_bytes)
    ram_over = max(0, ram_used - budget.ram_bytes)

    context_tokens = (
        catalogue.provider(selection.llm_provider).context_tokens
        if api_backed
        else selection.context_tokens
    )
    strategy = strategy_for(context_tokens)

    score = (quality / weight_total if weight_total else 0.0)
    if strategy == "whole-bible":
        score += whole_bible_bonus

    ok = vram_over == 0 and ram_over == 0 and not blockers

    return Fit(
        selection=selection,
        ok=ok,
        vram_used=vram_used,
        ram_used=ram_used,
        vram_over=vram_over,
        ram_over=ram_over,
        strategy=strategy,
        score=score,
        per_model=per_model,
        reasons=blockers + reasons,
    )


def _candidates(
    catalogue: Catalogue,
    role: Role,
    budget: Budget,
    require_cloning: bool,
) -> list[Placement]:
    out: list[Placement] = []
    for model in catalogue.by_role(role):
        if role == "tts" and model.cloning is not require_cloning:
            continue
        for device in model.devices:
            if device in ("gpu", "transient-gpu") and not budget.has_gpu:
                continue
            out.append(Placement(model.id, device))
    return out


def auto_fit(
    catalogue: Catalogue,
    budget: Budget,
    roles: Iterable[Role] = ("llm", "embedding", "tts"),
    llm_provider: str | None = None,
    require_cloning: bool = True,
    context_candidates: Iterable[int] = CONTEXT_CANDIDATES,
    whole_bible_bonus: float = DEFAULT_WHOLE_BIBLE_BONUS,
    limit: int = 15,
) -> list[Fit]:
    """Every legal combination, scored, best first. A few thousand candidates
    at most — brute force is correct here, and a solver would only add a
    dependency and a way to be subtly wrong.

    One row per distinct set of models: a stack that scores the same at 4k and
    8k context is one option, not two, and showing both just buries the
    genuinely different stacks further down."""

    roles = tuple(roles)
    per_role: dict[Role, list[Placement]] = {}
    for role in roles:
        if role == "llm" and llm_provider:
            continue
        options = _candidates(catalogue, role, budget, require_cloning)
        if not options:
            return []
        per_role[role] = options

    searchable = list(per_role.keys())
    contexts = (
        [max(context_candidates)] if llm_provider else list(context_candidates)
    )

    best_per_stack: dict[tuple, Fit] = {}
    for combo in itertools.product(*(per_role[r] for r in searchable)):
        placements = dict(zip(searchable, combo))
        key = tuple(sorted((r, p.model_id, p.device) for r, p in placements.items()))
        for context in contexts:
            selection = Selection(
                context_tokens=context,
                placements=placements,
                llm_provider=llm_provider,
            )
            fit = evaluate(selection, catalogue, budget, whole_bible_bonus)
            if not fit.ok:
                continue
            incumbent = best_per_stack.get(key)
            # Same stack, different context: keep the better score, and on a
            # tie keep the longer context — free headroom for conversation.
            if (
                incumbent is None
                or fit.score > incumbent.score
                or (
                    fit.score == incumbent.score
                    and context > incumbent.selection.context_tokens
                )
            ):
                best_per_stack[key] = fit

    fits = list(best_per_stack.values())
    # Best score wins; ties break toward the smaller stack, since spare
    # memory is worth more than a rounding difference in a quality guess.
    fits.sort(key=lambda f: (-round(f.score, 2), f.vram_used + f.ram_used))
    return fits[:limit]


def largest_shortfall(
    catalogue: Catalogue,
    budget: Budget,
    roles: Iterable[Role],
    require_cloning: bool = True,
) -> str:
    """When nothing fits, say something more useful than 'nothing fits'."""
    cheapest = 0
    for role in roles:
        options = [
            m
            for m in catalogue.by_role(role)
            if not (role == "tts" and m.cloning is not require_cloning)
        ]
        if not options and role == "llm":
            return (
                "No model in the catalogue has native tool calling, so no LLM "
                "stack is possible. Use an API for the LLM, or add one."
            )
        if options:
            cheapest += min(m.footprint(4096) for m in options)
    total_budget = budget.vram_bytes + budget.ram_bytes
    if cheapest > total_budget:
        return (
            f"Even the smallest stack needs {human_bytes(cheapest)} and only "
            f"{human_bytes(total_budget)} is available. Drop a role, or use an "
            f"API for the LLM."
        )
    return (
        "No combination fits within a single pool. Try moving the embedding "
        "model to the CPU, lowering the context length, or serving the LLM by API."
    )
