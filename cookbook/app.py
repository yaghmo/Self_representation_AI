"""Streamlit front end for the cookbook.

Run:  streamlit run cookbook/app.py

Two modes, both of which end at the same place — a stack.json you confirmed.
Auto ranks every legal combination. Manual lets you choose and tells you
plainly whether it fits or bricks, and by how much.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

if __package__ in (None, ""):  # streamlit runs this as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cookbook.config import build_config, config_path, read_config, write_config
from cookbook.fit import (
    CONTEXT_CANDIDATES,
    CONVERSATION_RESERVE_TOKENS,
    DEFAULT_WHOLE_BIBLE_BONUS,
    Budget,
    Placement,
    Selection,
    auto_fit,
    bible_tokens,
    evaluate,
    largest_shortfall,
)
from cookbook.probe import run_probe
from cookbook.schema import ROLES, human_bytes, load_catalogue

st.set_page_config(page_title="Cookbook — stack fitter", layout="wide")


@st.cache_resource(show_spinner="Probing machine…")
def _probe():
    return run_probe()


@st.cache_resource
def _catalogue():
    return load_catalogue()


def _refresh():
    _probe.clear()
    _catalogue.clear()


probe = _probe()
catalogue = _catalogue()

st.title("Cookbook")
st.caption(
    "Fits the whole stack at once — every enabled role is resident at the same "
    "time, so the constraint is their sum, not any one model."
)

# ---------------------------------------------------------------- machine ---

with st.sidebar:
    st.header("Machine")
    st.metric("RAM ceiling", human_bytes(probe.ram_ceiling_bytes))
    st.caption(probe.ram_ceiling_source)
    st.metric("RAM free now", human_bytes(probe.ram_available_bytes))

    if probe.gpu.present:
        st.metric("VRAM free", human_bytes(probe.gpu.free_bytes))
        st.caption(
            f"{probe.gpu.name} · {human_bytes(probe.gpu.used_bytes)} already in use"
        )
    else:
        st.metric("VRAM free", "none")
        st.warning(probe.gpu.diagnosis)

    st.metric("CPU cores", probe.cpu_count)
    st.metric("Disk free", human_bytes(probe.disk_free_bytes))
    st.write(
        f"Container: **{'yes' if probe.in_container else 'no'}** · "
        f"Internet: **{'yes' if probe.internet else 'no'}**"
    )
    if st.button("Re-probe", width="stretch"):
        _refresh()
        st.rerun()

    st.divider()
    st.header("Preference")
    whole_bible_bonus = st.slider(
        "Value of the whole bible in context",
        min_value=0.0,
        max_value=40.0,
        value=DEFAULT_WHOLE_BIBLE_BONUS,
        step=1.0,
        help=(
            "Scored against raw model quality. At 0 the fitter always takes the "
            "smartest model that fits and leans on retrieval. High values buy a "
            "context long enough to hold the whole bible, paid for with a "
            "smaller model. There is no correct answer — it is a taste call."
        ),
    )

for warning in probe.warnings:
    st.warning(warning)

if catalogue.estimated:
    st.warning(
        f"{len(catalogue.estimated)} of {len(catalogue.models)} entries still carry "
        "**estimated** figures. Run `python -m cookbook.refresh --apply` to replace "
        "them with real file sizes and real KV geometry from the hub."
    )
elif catalogue.unverified:
    st.info(
        f"Figures for all {len(catalogue.models)} entries come from the hub — real "
        "file sizes, real KV geometry. Still not **measured**: runtime overhead is "
        "a constant per role rather than an observed number, so a fit landing "
        "within a few hundred MB of the limit is a maybe, not a yes."
    )

# ----------------------------------------------------------------- choices ---

left, right = st.columns([1, 2])

with left:
    st.subheader("Surface")
    surface_label = st.radio(
        "Choosing a stack for",
        ["User — chat only", "Admin — agent with tools"],
        help=(
            "The user surface is fans talking to the character: retrieval, then "
            "one model call, no tools. The admin surface is you editing the "
            "bible through an agent loop, which needs a model that emits tool "
            "calls a runtime can parse."
        ),
    )
    surface = "admin" if surface_label.startswith("Admin") else "user"

    if surface == "admin":
        excluded = [
            m.id
            for m in catalogue.by_role("llm")
            if m.tool_calling != "native"
        ]
        if excluded:
            st.caption(
                f"Excluded, no native tool calling: {', '.join(excluded)}"
            )

    st.subheader("Roles")
    st.caption("Disabled roles cost nothing. Enabled ones enter the sum.")
    use_embedding = st.checkbox(
        "Embedding (RAG over the bible)", value=True, key=f"emb-{surface}"
    )
    # The admin agent edits text through tools. Nothing speaks, so loading a
    # voice model would just take VRAM from the model doing the thinking.
    use_tts = st.checkbox(
        "TTS with voice cloning",
        value=(surface == "user"),
        key=f"tts-{surface}",
        help=None if surface == "user" else "Off by default for admin — the agent has no voice.",
    )
    require_cloning = True
    if use_tts:
        require_cloning = st.checkbox(
            "Cloning required", value=True, key=f"clone-{surface}",
            help="Off allows fixed-voice models like Kokoro, which are far smaller.",
        )

    # Hosted-provider selection is removed for now — every stack is local.
    # `providers.json` and the fitter's API branch stay in place, dormant, for
    # when that comes back.
    provider_id = None

    roles = ["llm"]
    if use_embedding:
        roles.append("embedding")
    if use_tts:
        roles.append("tts")

    st.subheader("Budget")
    basis_label = st.radio(
        "Fit against",
        ["Whole machine", "What is free right now"],
        help=(
            "Whole machine assumes you close things before starting the "
            "container, and reserves memory for the OS. Free-right-now is "
            "truthful about this instant but makes the answer depend on what "
            "you had open when you probed."
        ),
    )
    basis = "whole-machine" if basis_label == "Whole machine" else "free-now"
    budget = Budget.from_probe(probe, basis=basis)

    st.write(
        f"VRAM **{human_bytes(budget.vram_bytes)}** of {human_bytes(budget.vram_raw)}"
    )
    st.write(
        f"RAM **{human_bytes(budget.ram_bytes)}** of {human_bytes(budget.ram_raw)}"
    )
    if basis == "whole-machine" and probe.gpu.present and probe.gpu.used_bytes > 512 * 1024**2:
        st.caption(
            f"{human_bytes(probe.gpu.used_bytes)} of VRAM is in use by something "
            "else right now. Close it before boot, or this fit will not hold."
        )

with right:
    mode = st.radio(
        "Mode", ["Auto — pick the best fit", "Manual — I choose, you check"],
        horizontal=True,
    )
    chosen_fit = None

    if mode.startswith("Auto"):
        results = auto_fit(
            catalogue,
            budget,
            roles=roles,
            llm_provider=provider_id,
            require_cloning=require_cloning,
            surface=surface,
            whole_bible_bonus=whole_bible_bonus,
        )
        if not results:
            st.error(largest_shortfall(catalogue, budget, roles, require_cloning, surface))
        else:
            rows = []
            for index, fit in enumerate(results):
                row = {"#": index + 1, "score": round(fit.score, 1)}
                for role in ROLES:
                    placement = fit.selection.placements.get(role)
                    if role == "llm" and fit.selection.llm_provider:
                        row["llm"] = f"API · {fit.selection.llm_provider}"
                    elif placement:
                        row[role] = f"{placement.model_id} ({placement.device})"
                    else:
                        row[role] = "—"
                row["context"] = f"{fit.selection.context_tokens:,}"
                row["bible"] = fit.strategy
                row["VRAM"] = human_bytes(fit.vram_used)
                row["RAM"] = human_bytes(fit.ram_used)
                rows.append(row)

            st.dataframe(rows, width="stretch", hide_index=True)
            pick = st.number_input(
                "Row to use", min_value=1, max_value=len(results), value=1, step=1
            )
            chosen_fit = results[int(pick) - 1]

    else:
        placements: dict[str, Placement] = {}
        for role in roles:
            if role == "llm" and provider_id:
                continue
            options = catalogue.for_surface(role, surface)
            if role == "tts" and require_cloning:
                options = [m for m in options if m.cloning]
            model_id = st.selectbox(
                f"{role} model",
                [m.id for m in options],
                key=f"pick-{role}",
            )
            model = catalogue.model(model_id)
            device = st.radio(
                f"{role} device",
                list(model.devices),
                horizontal=True,
                key=f"dev-{role}",
            )
            placements[role] = Placement(model_id, device)

        context = st.select_slider(
            "Context length",
            options=list(CONTEXT_CANDIDATES),
            value=32_768,
            format_func=lambda n: f"{n:,}",
            disabled=bool(provider_id),
        )
        needed = bible_tokens(surface)
        st.caption(
            f"The {surface} surface holds ~{needed:,} tokens of bible. It goes "
            f"in whole above {needed + CONVERSATION_RESERVE_TOKENS:,}; below "
            f"that, retrieval."
        )

        candidate = Selection(
            context_tokens=context,
            placements=placements,
            llm_provider=provider_id,
            surface=surface,
        )
        fit = evaluate(candidate, catalogue, budget, whole_bible_bonus)

        if fit.ok:
            st.success(f"Fits. VRAM {human_bytes(fit.vram_used)} · RAM {human_bytes(fit.ram_used)}")
            chosen_fit = fit
        else:
            st.error(fit.verdict())

        for reason in fit.reasons:
            st.caption(reason)

        if fit.per_model:
            st.write("Per-model footprint at this context:")
            st.dataframe(
                [
                    {"role": role, "bytes": human_bytes(cost)}
                    for role, cost in fit.per_model.items()
                ],
                width="stretch",
                hide_index=True,
            )

# ----------------------------------------------------------------- confirm ---

st.divider()

if chosen_fit is not None and chosen_fit.ok:
    st.subheader("Confirm")
    st.write(
        f"Surface: **{surface}** · bible strategy: **{chosen_fit.strategy}** · "
        f"context **{chosen_fit.selection.context_tokens:,}** tokens"
    )
    destination = config_path(surface)
    if st.button(f"Write {destination.as_posix()}", type="primary"):
        config = build_config(chosen_fit, catalogue, probe)
        path = write_config(config)
        st.success(f"Wrote {path}")
        st.json(config)
else:
    st.caption("Nothing confirmed yet — pick a fit above.")

for known in ("user", "admin"):
    existing = read_config(known)
    if existing:
        with st.expander(
            f"Current {config_path(known).as_posix()} "
            f"(written {existing.get('written_at', '?')})"
        ):
            st.json(existing)
