"""Correct the catalogue against the hub. Run when you choose, not automatically.

This is the sane version of the scraper the README argues against. It does not
discover models — the list stays hand-curated — it only replaces estimates with
facts for models already in it:

  * real file sizes, so `weights_bytes` stops being a guess
  * real KV geometry from config.json, which is most of the memory at long context
  * whether the download target exists and whether it is gated

Prints proposed changes and stops. Pass --apply to write them.

    python -m cookbook.refresh
    python -m cookbook.refresh --apply
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .schema import human_bytes

HUB = "https://huggingface.co"
CATALOGUE = Path(__file__).parent / "catalogue.json"


def _get_json(url: str, timeout: int = 30) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "cookbook-refresh"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def repo_tree(repo: str) -> list[dict]:
    """Every file in the repo with its real size."""
    out: list[dict] = []
    cursor = f"{HUB}/api/models/{repo}/tree/main?recursive=true"
    seen = 0
    while cursor and seen < 5000:
        batch = _get_json(cursor)
        if not isinstance(batch, list):
            break
        out.extend(batch)
        seen += len(batch)
        cursor = None  # the API paginates by Link header; one page is plenty here
    return out


def repo_info(repo: str) -> dict:
    return _get_json(f"{HUB}/api/models/{repo}")


def model_config(repo: str) -> dict | None:
    try:
        return _get_json(f"{HUB}/{repo}/raw/main/config.json")
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError:
        return None


def kv_from_config(config: dict) -> dict | None:
    """Pull KV-cache geometry out of a transformers config.

    Falls back the way the runtimes do: models without grouped-query attention
    have no num_key_value_heads and use one KV head per attention head.
    """
    text = config.get("text_config", config)  # multimodal configs nest it

    layers = text.get("num_hidden_layers")
    heads = text.get("num_attention_heads")
    kv_heads = text.get("num_key_value_heads", heads)
    hidden = text.get("hidden_size")
    head_dim = text.get("head_dim") or (hidden // heads if hidden and heads else None)

    if not all((layers, kv_heads, head_dim)):
        return None
    return {"layers": int(layers), "kv_heads": int(kv_heads), "head_dim": int(head_dim)}


def _match(patterns: tuple[str, ...], name: str) -> bool:
    from fnmatch import fnmatch

    return any(fnmatch(name, p) for p in patterns)


def inspect(entry: dict) -> tuple[dict, list[str]]:
    """Returns (updates, notes) for one catalogue entry."""
    updates: dict = {}
    notes: list[str] = []
    download = entry.get("download")

    if not download:
        return {}, ["no download block — cannot check"]

    repo = download["repo"]
    try:
        info = repo_info(repo)
    except Exception as exc:
        return {}, [f"FAILED to reach {repo}: {exc}"]

    gated = info.get("gated")
    if gated:
        updates.setdefault("download", {})["gated"] = True
        notes.append(f"gated ({gated}) — needs an accepted licence and HF_TOKEN")

    try:
        tree = repo_tree(repo)
    except Exception as exc:
        return updates, notes + [f"FAILED to list {repo}: {exc}"]

    files = {f["path"]: f.get("size", 0) for f in tree if f.get("type") == "file"}

    if download.get("file"):
        wanted = download["file"]
        if wanted not in files:
            near = [p for p in files if p.lower().endswith(".gguf")][:6]
            return updates, notes + [
                f"MISSING {wanted} in {repo}. Present: {', '.join(near) or 'no gguf files'}"
            ]
        total = files[wanted]
    else:
        patterns = tuple(download.get("allow_patterns", ()))
        ignored = tuple(download.get("ignore_patterns", ()))
        selected = {
            p: s
            for p, s in files.items()
            if (not patterns or _match(patterns, p)) and not _match(ignored, p)
        }
        if not selected:
            return updates, notes + [f"no files in {repo} matched {patterns}"]
        total = sum(selected.values())
        notes.append(f"{len(selected)} of {len(files)} files matched")

    updates.setdefault("download", {})["total_bytes"] = total

    old = entry["weights_bytes"]
    if total != old:
        drift = (total - old) / old * 100 if old else 0
        updates["weights_bytes"] = total
        notes.append(
            f"weights {human_bytes(old)} -> {human_bytes(total)} ({drift:+.0f}%)"
        )

    if entry["role"] == "llm":
        # GGUF repos have no config.json; the home repo does.
        config = model_config(entry["repo"]) or model_config(repo)
        if config:
            kv = kv_from_config(config)
            if kv and kv != entry.get("kv"):
                updates["kv"] = kv
                notes.append(f"kv {entry.get('kv')} -> {kv}")
            elif kv:
                notes.append("kv confirmed")
            ctx = (config.get("text_config", config)).get("max_position_embeddings")
            if ctx:
                notes.append(f"native max context {ctx:,}")
        else:
            notes.append(f"no config.json reachable for {entry['repo']} — kv left as is")

    if updates:
        updates["figures"] = "hub"
    return updates, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--only", help="limit to one model id")
    args = parser.parse_args()

    raw = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    changed = 0
    grand_total = 0

    for entry in raw["models"]:
        if args.only and entry["id"] != args.only:
            continue
        updates, notes = inspect(entry)
        head = f"{entry['id']:32}"
        if not updates and not notes:
            print(f"{head} unchanged")
            continue

        print(f"{head} {'; '.join(notes) if notes else ''}")

        if updates.get("download", {}).get("total_bytes"):
            grand_total += updates["download"]["total_bytes"]

        if args.apply and updates:
            for key, value in updates.items():
                if key == "download":
                    entry["download"].update(value)
                else:
                    entry[key] = value
            changed += 1

    print(f"\ntotal download size of the whole catalogue: {human_bytes(grand_total)}")

    if args.apply and changed:
        CATALOGUE.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {CATALOGUE} — {changed} entries updated")
    elif not args.apply:
        print("dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
