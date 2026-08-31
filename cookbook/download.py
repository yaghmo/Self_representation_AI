"""Fetch weights into the project, not into the user's Hugging Face cache.

Everything lands under `models/<model-id>/`, one directory per catalogue entry,
laid out as the serving runtime expects rather than as a blob store. Nothing is
written to `~/.cache/huggingface`.

Bandwidth is treated as expensive: every command prints exactly what it will
pull and what is already on disk, and refuses to start until told to.

    python -m cookbook.download --list
    python -m cookbook.download --models qwen3-8b-instruct-q4km,bge-m3
    python -m cookbook.download --role llm --dry-run
    python -m cookbook.download --from-config          # whatever stack.json selected
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"

# Must be set before huggingface_hub is imported, or it will resolve the user's
# home cache at import time and quietly use it for anything not covered by
# local_dir.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / ".hf"))
os.environ.setdefault("HF_HUB_CACHE", str(MODELS_DIR / ".hf" / "hub"))

# The Xet transfer backend stages chunks in a shared cache outside local_dir
# and only materializes the destination file on completion, so on_disk_bytes()
# below would read ~0 for the whole download then jump to 100% at the end.
# Disabling it falls back to plain HTTP, which writes (and resumes) directly
# into local_dir, matching what progress polling assumes.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from .config import read_config  # noqa: E402
from .schema import Catalogue, ModelEntry, human_bytes, load_catalogue  # noqa: E402


def target_dir(entry: ModelEntry) -> Path:
    return MODELS_DIR / entry.id


def on_disk_bytes(entry: ModelEntry) -> int:
    directory = target_dir(entry)
    if not directory.is_dir():
        return 0
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


def is_complete(entry: ModelEntry) -> bool:
    """Complete enough to skip. Compares against the size the hub reported, with
    a small tolerance — a few bytes of line-ending drift in a README should not
    trigger a 5GB re-download."""
    expected = entry.download.total_bytes if entry.download else None
    if not expected:
        return False
    actual = on_disk_bytes(entry)
    return actual >= expected * 0.99


def models_from_config(catalogue: Catalogue) -> list[ModelEntry]:
    config = read_config()
    if not config:
        raise SystemExit(
            "no config found — run the cookbook first, or name models explicitly"
        )
    ids = []
    for role_name, role in config["roles"].items():
        if role.get("source") != "local":
            continue
        if role_name == "tts":
            # stack.json only names the one tts checkpoint fit.py placed for
            # the steady-state VRAM budget, but voice.py's design->clone
            # chaining (see runtime/voice.py's CLONE_MODEL_ID/DESIGN_MODEL_ID)
            # needs both the cloning and VoiceDesign talkers on disk — they
            # load one at a time, on demand, never resident together.
            ids.extend(m.id for m in catalogue.by_role("tts"))
        else:
            ids.append(role["model_id"])
    if not ids:
        raise SystemExit("stack.json selects no local models — nothing to download")
    seen: set[str] = set()
    return [catalogue.model(i) for i in ids if not (i in seen or seen.add(i))]


def select(catalogue: Catalogue, args) -> list[ModelEntry]:
    if args.all:
        return list(catalogue.models)

    if args.from_config:
        return models_from_config(catalogue)

    chosen: list[ModelEntry] = []
    if args.models:
        for model_id in args.models.split(","):
            chosen.append(catalogue.model(model_id.strip()))
    if args.role:
        chosen.extend(catalogue.by_role(args.role))

    if not chosen:
        raise SystemExit("nothing selected — pass --models, --role, --from-config or --all")

    seen: set[str] = set()
    unique = []
    for entry in chosen:
        if entry.id not in seen:
            seen.add(entry.id)
            unique.append(entry)
    return unique


def fetch(entry: ModelEntry, token: str | None) -> Path:
    from huggingface_hub import hf_hub_download, snapshot_download

    download = entry.download
    if download is None:
        raise SystemExit(f"{entry.id} has no download block")

    destination = target_dir(entry)
    destination.mkdir(parents=True, exist_ok=True)

    if download.file:
        hf_hub_download(
            repo_id=download.repo,
            filename=download.file,
            local_dir=str(destination),
            token=token,
        )
    else:
        snapshot_download(
            repo_id=download.repo,
            local_dir=str(destination),
            allow_patterns=list(download.allow_patterns) or None,
            ignore_patterns=list(download.ignore_patterns) or None,
            token=token,
        )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show catalogue and disk state")
    parser.add_argument("--models", help="comma-separated model ids")
    parser.add_argument("--role", choices=["llm", "embedding", "tts"])
    parser.add_argument("--all", action="store_true", help="the entire catalogue")
    parser.add_argument(
        "--from-config",
        action="store_true",
        help="download whatever config/stack.json selected",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan, download nothing")
    parser.add_argument("--force", action="store_true", help="re-download even if complete")
    args = parser.parse_args()

    catalogue = load_catalogue()
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

    if args.list:
        print(f"weights directory: {MODELS_DIR}\n")
        for role in ("llm", "embedding", "tts"):
            print(f"[{role}]")
            for entry in catalogue.by_role(role):
                size = entry.download.total_bytes if entry.download else None
                state = "on disk" if is_complete(entry) else "not downloaded"
                gated = " GATED" if entry.download and entry.download.gated else ""
                print(f"  {entry.id:32} {human_bytes(size or 0):>10}  {state}{gated}")
            print()
        return 0

    chosen = select(catalogue, args)

    to_get = [e for e in chosen if args.force or not is_complete(e)]
    skipped = [e for e in chosen if e not in to_get]

    total = sum((e.download.total_bytes or 0) for e in to_get if e.download)
    free = shutil.disk_usage(REPO_ROOT).free

    print(f"weights directory: {MODELS_DIR}")
    for entry in skipped:
        print(f"  skip  {entry.id:32} already on disk")
    for entry in to_get:
        size = entry.download.total_bytes if entry.download else 0
        gated = "  GATED — needs an accepted licence and HF_TOKEN" if entry.download and entry.download.gated else ""
        print(f"  get   {entry.id:32} {human_bytes(size or 0):>10}{gated}")

    print(f"\nto download: {human_bytes(total)} across {len(to_get)} models")
    print(f"disk free:   {human_bytes(free)}")

    if total > free * 0.9:
        raise SystemExit("not enough disk headroom — free some space first")

    if args.dry_run:
        print("\ndry run — nothing downloaded")
        return 0

    if not to_get:
        print("\nnothing to do")
        return 0

    gated = [e for e in to_get if e.download and e.download.gated]
    if gated and not token:
        print(
            "\nHF_TOKEN is not set and these need one: "
            + ", ".join(e.id for e in gated)
        )

    for index, entry in enumerate(to_get, 1):
        size = entry.download.total_bytes if entry.download else 0
        print(f"\n[{index}/{len(to_get)}] {entry.id} — {human_bytes(size or 0)}")
        try:
            path = fetch(entry, token)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue
        print(f"  -> {path}  ({human_bytes(on_disk_bytes(entry))} on disk)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
