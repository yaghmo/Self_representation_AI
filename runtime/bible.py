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
from typing import Callable

from .backend import Message, tokenize_url

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = REPO_ROOT / "data" / "character.md"


class ProfileMissing(FileNotFoundError):
    pass

PROFILE_START = "# CHARACTER"
PROFILE_END = "## Changelog"

# Cites come in several shapes: `S-778`, `[S-778]`, `[S-778, S-779]`, `S-997`/`S-998`, etc.
# Match backtick-wrapped citations with or without brackets, or bracketed
# citations with or without backticks. Slash-separated multiples like `S-997`/`S-998`
# are consumed as a unit. Other backtick spans must survive: the profile also
# backticks quoted speech, file references, and the bracketed markers for fuzzed details.
CITE = re.compile(
    r"[ \t]*`S-[^`]*`([ \t]*/[ \t]*`S-[^`]*`)*"  # bracket-less, with slash separation
    r"|[ \t]*`?\[S-[^\]]*\]`?"  # bracketed with optional backticks
)


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


class ProfileTooLarge(RuntimeError):
    pass


class MessageTooLarge(RuntimeError):
    """The newest turn alone doesn't fit in what's left after the persona.

    Distinct from `ProfileTooLarge` on purpose: this failure is about the
    user's message, not the profile, and the message should say so rather
    than pointing someone at /rebuild for a problem that isn't there.
    """

    pass


# Framing only. The behavioural rules are the creator's and live in the profile
# itself (§10 Interaction Rules, and Hard constraints). The honesty line is
# CLAUDE.md's fixed bot rule, not something invented here.
FRAMING = (
    "You are the person described in the profile below. Answer as her, in her "
    "voice, using her phrasing.\n"
    "If you are asked something the profile does not cover, say so plainly, in "
    "voice. Never invent a memory, an opinion, an event, or a relationship to "
    "fill a gap.\n\n"
)


def build_persona(path: Path | None = None) -> str:
    return FRAMING + strip_cites(slice_profile(load_profile(path)))


PROCEDURE_PATH = REPO_ROOT / ".claude" / "skills" / "add" / "SKILL.md"


class ProcedureMissing(FileNotFoundError):
    pass


def section_index_from(text: str) -> str:
    """The profile's `## ` headings, one per line.

    Split from `section_index()` so it can be tested against a fixture without
    touching `data/`. Everything before `# CHARACTER` explains the file to
    humans and the changelog is bookkeeping — neither is a section the agent
    should be editing, and `slice_profile` has already removed both.
    """
    body = slice_profile(text)
    return "\n".join(line for line in body.splitlines() if line.startswith("## "))


def section_index(path: Path | None = None) -> str:
    return section_index_from(load_profile(path))


def build_procedure(path: Path | None = None) -> str:
    """The admin system prompt: the /add procedure, plus what sections exist.

    Read live rather than baked into a constant, so the index cannot drift from
    the file — and so the agent spends no tool call asking what it could have
    been told for sixty tokens.
    """
    try:
        procedure = PROCEDURE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProcedureMissing(
            f"{PROCEDURE_PATH} does not exist — agent mode has no procedure to "
            "follow. Restore the /add skill, or turn agent mode off."
        ) from exc
    return (
        procedure
        + "\n\n## Sections in the profile you are editing\n\n"
        + section_index(path)
        + "\n"
    )


def assemble(
    history: list[Message],
    context_tokens: int,
    count: Callable[[str], int] = estimate_tokens,
    reserve_tokens: int = 1024,
    persona: str | None = None,
) -> list[Message]:
    """The system prompt plus as much recent conversation as fits.

    `count` is injected so this stays a pure function: the service passes the
    backend's exact tokeniser, the self-check passes the estimator.
    """
    persona = build_persona() if persona is None else persona
    budget = context_tokens - reserve_tokens
    persona_tokens = count(persona)

    if persona_tokens >= budget:
        raise ProfileTooLarge(
            f"the profile is {persona_tokens} tokens and the budget is {budget} "
            f"({context_tokens} context minus {reserve_tokens} reserved for the "
            "reply). Raise the context in the stack config, or shorten the "
            "profile with /rebuild. The persona is never truncated — a prompt "
            "that loses the hard constraints is a bot that fabricates."
        )

    # Newest first, keeping turns until the budget is spent, then put them back
    # in order. Oldest context is the cheapest thing to lose.
    remaining = budget - persona_tokens

    # The newest turn is the one question this reply is actually for. If it
    # doesn't fit, dropping it would send the persona into the void and get
    # an answer to no question — silently. Refuse instead.
    if history:
        newest_cost = count(history[-1].content)
        if newest_cost > remaining:
            raise MessageTooLarge(
                f"the latest message is {newest_cost} tokens and only {remaining} "
                "remain after the persona. The message is too long to answer, not "
                "the profile — shorten it and retry."
            )

    kept: list[Message] = []
    for message in reversed(history):
        cost = count(message.content)
        if cost > remaining:
            break
        remaining -= cost
        kept.append(message)
    kept.reverse()

    return [Message("system", persona), *kept]


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
        "- **Three words:** alpha `[S-777, S-778, S-779]`, beta `[S-780]`\n"
        "- Something single-sourced (tentative) `[S-781]`\n"
        "- Bracket-less cite form `S-888` must also strip\n"
        "- Slash-separated cites `S-997`/`S-998` must strip together\n"
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
    assert "must strip together" in stripped, "slash-separated cites must be removed entirely"
    assert "`zzz`" in stripped, "voice text must survive"
    assert "`sources.md`" in stripped, "file refs must survive"
    assert "`[~placeholder-date]`" in stripped, "redaction markers must survive"

    # The section index is the headings and nothing else — it goes in the
    # admin prompt so the model knows what sections exist without spending a
    # tool call to ask.
    index = section_index_from(sample)
    assert "## 0. At a Glance" in index, index
    assert "## Changelog" not in index, "bookkeeping is not a section to edit"
    assert "How this file works" not in index, "meta instructions are not either"
    assert "alpha" not in index, "the index is headings only, never bodies"

    # Verify against real profile — gracefully skip if file doesn't exist
    try:
        real_stripped = strip_cites(slice_profile(load_profile()))
        assert "[S-" not in real_stripped, f"Real profile: [S- citation leaked"
        assert "`S-" not in real_stripped, f"Real profile: `S- citation leaked"
    except ProfileMissing:
        # File not yet created on fresh clone or before first /add.
        # Fixture assertions above are the actual regression tests.
        pass

    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens(sliced) > 0

    # Verify LocalBackend.count_tokens URL derivation logic by exercising
    # the real helper it uses
    assert tokenize_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/tokenize"
    assert tokenize_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080/tokenize"

    # A caller-supplied persona stands in for build_persona()'s output, so it
    # carries the same framing prefix a real one would (~117 tokens by the
    # estimator).
    persona = FRAMING + "PERSONA " + "x " * 100
    persona_tokens = estimate_tokens(persona)
    history = [Message("user", "q " * 50), Message("assistant", "a " * 50)] * 6

    # Fits: system prompt first, every turn kept.
    out = assemble(history, context_tokens=4096, persona=persona)
    assert out[0].role == "system"
    assert out[0].content.startswith("You are")
    assert "PERSONA" in out[0].content
    assert len(out) == len(history) + 1

    # Too small for the persona alone: refuse, do not truncate. The budget
    # must be positive-but-insufficient, not negative — a negative budget
    # would pass the `persona_tokens >= budget` check for the wrong reason,
    # since any token count is >= a negative number regardless of the logic
    # being tested. Assert on the actual numbers the exception reports, not
    # a substring that would match by coincidence.
    small_budget = 50
    try:
        assemble(history, context_tokens=1024 + small_budget, persona=persona)
    except ProfileTooLarge as exc:
        assert str(persona_tokens) in str(exc), str(exc)
        assert str(small_budget) in str(exc), str(exc)
    else:
        raise AssertionError("expected ProfileTooLarge")

    # Newest turn alone does not fit after the persona: refuse loudly rather
    # than silently drop it and send the persona into the void with no
    # question attached.
    lonely = [Message("user", "q " * 50)]
    newest_tokens = estimate_tokens(lonely[0].content)
    short_remaining = newest_tokens - 1  # one token short, on purpose
    try:
        assemble(
            lonely,
            context_tokens=1024 + persona_tokens + short_remaining,
            persona=persona,
        )
    except MessageTooLarge as exc:
        assert str(newest_tokens) in str(exc), str(exc)
        assert str(short_remaining) in str(exc), str(exc)
    else:
        raise AssertionError("expected MessageTooLarge")

    # Persona fits but history does not: oldest turns dropped, system survives.
    # (reserve_tokens defaults to 1024, so context_tokens must clear that
    # before the persona has room to spare, with less left over than the
    # full 300-token history needs.)
    trimmed = assemble(history, context_tokens=1300, persona=persona)
    assert trimmed[0].role == "system"
    assert len(trimmed) < len(history) + 1
    assert trimmed[-1].content == history[-1].content, "newest turn must survive"

    print("bible self-check: ok")


if __name__ == "__main__":
    _self_check()
