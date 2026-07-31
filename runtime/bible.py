"""Assembles the system prompt the audience-facing bot runs on.

The fan surface reads `data/character.md` and nothing else. `sources.md` is the
creator's unedited answers and stays admin-only — a retrieval hit there would
surface a whole entry to a stranger.

The profile body is small enough to go into context whole, so there is no
retrieval, no embedding model, and no chunking. When it eventually outgrows the
budget, see `assemble()` — it refuses loudly rather than truncating the persona,
because a prompt that loses the hard constraints is a bot that fabricates.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "data" / "character.md"


class ProfileMissing(FileNotFoundError):
    pass

PROFILE_START = "# CHARACTER"
PROFILE_END = "## Changelog"

# Cites come in several shapes: `S-004`, `[S-004]`, `[S-004, S-007]`, etc.
# Match backtick-wrapped citations with or without brackets, or bracketed
# citations with or without backticks. Other backtick spans must survive: the
# profile also backticks quoted speech, file references, and the bracketed
# markers that stand in for deliberately fuzzed details.
CITE = re.compile(r"[ \t]*`S-[^`]*`|[ \t]*`?\[S-[^\]]*\]`?")


def load_profile(path: Path | None = None) -> str:
    path = path or PROFILE_PATH
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProfileMissing(
            f"{path} does not exist — the fan surface has no character to be. "
            "Fill it in from templates/character.template.md, or run /add."
        ) from exc


def slice_profile(text: str) -> str:
    """Just the bot-facing span. Everything before `# CHARACTER` explains the
    file to the humans maintaining it, and the changelog is bookkeeping."""
    start = text.find(PROFILE_START)
    if start == -1:
        raise ValueError(f"{PROFILE_START!r} not found — is this a character profile?")
    end = text.find(PROFILE_END, start)
    body = text[start:end] if end != -1 else text[start:]
    return body.strip()


def strip_cites(text: str) -> str:
    """Citations are the audit trail, not something a fan should read. They stay
    in the file; they never reach a prompt."""
    return CITE.sub("", text)


def estimate_tokens(text: str) -> int:
    """Rough count for when no server is up to ask. Off by 10-20%, which is why
    it is never used to decide whether a prompt fits — only to display."""
    return len(text) // 4


def _self_check() -> None:
    # Invented placeholder content only. This file is tracked, and CLAUDE.md
    # forbids instance details in tracked files — no real name, trait, quote,
    # or redacted value from anyone's profile belongs in a fixture.
    sample = (
        "# Placeholder — Character Profile\n"
        "## How this file works\n"
        "Meta instructions the model must never see.\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n"
        "- **Three words:** alpha `[S-003, S-023, S-024]`, beta `[S-014]`\n"
        "- Something single-sourced (tentative) `[S-099]`\n"
        "- Bracket-less cite form `S-055` must also strip\n"
        "- Voice text `zzz` must survive, file ref `sources.md` must survive\n"
        "- Redaction marker `[~placeholder-date]` must survive\n"
        "## Changelog\n"
        "- v1 bookkeeping nobody should read\n"
    )

    sliced = slice_profile(sample)
    assert sliced.startswith("# CHARACTER"), sliced[:40]
    assert "How this file works" not in sliced
    assert "bookkeeping" not in sliced

    stripped = strip_cites(sliced)
    # Regression guards: no citation leaks
    assert "[S-" not in stripped, f"[S- citation leaked: {stripped}"
    assert "`S-" not in stripped, f"`S- citation leaked: {stripped}"
    # Legitimate spans must survive
    assert "(tentative)" in stripped, "tentative markers must survive"
    assert "alpha," in stripped, stripped
    assert "`zzz`" in stripped, "voice text must survive"
    assert "`sources.md`" in stripped, "file refs must survive"
    assert "`[~placeholder-date]`" in stripped, "redaction markers must survive"

    # Verify against real profile
    real_stripped = strip_cites(slice_profile(load_profile()))
    assert "[S-" not in real_stripped, f"Real profile: [S- citation leaked"
    assert "`S-" not in real_stripped, f"Real profile: `S- citation leaked"

    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens(sliced) > 0

    # Verify LocalBackend.count_tokens URL derivation logic
    base_url_v1 = "http://127.0.0.1:8080/v1"
    root = base_url_v1.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    assert root == "http://127.0.0.1:8080", f"Expected root URL without /v1, got {root}"
    assert f"{root}/tokenize" == "http://127.0.0.1:8080/tokenize"

    print("bible self-check: ok")


if __name__ == "__main__":
    _self_check()
