from runtime.backend import Message, tokenize_url
from runtime.bible import (
    FRAMING,
    MessageTooLarge,
    ProfileIncomplete,
    ProfileMissing,
    ProfileTooLarge,
    assemble,
    build_compact_persona_from,
    estimate_tokens,
    load_profile,
    plan_compaction,
    profile_section_chunks_from,
    section_index_from,
    slice_profile,
    strip_cites,
)


def test_bible_self_check():
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
        assert "[S-" not in real_stripped, "Real profile: [S- citation leaked"
        assert "`S-" not in real_stripped, "Real profile: `S- citation leaked"
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
    # carries the same framing prefix a real one would.
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
    # full history needs. Relative to persona_tokens rather than a fixed
    # constant, so this stays correct as FRAMING's own length changes.)
    trimmed = assemble(history, context_tokens=1024 + persona_tokens + 50, persona=persona)
    assert trimmed[0].role == "system"
    assert len(trimmed) < len(history) + 1
    assert trimmed[-1].content == history[-1].content, "newest turn must survive"

    # A tool result whose call was trimmed away must go with it. llama-server
    # rejects a result addressed to a call that is not in the conversation, so
    # an orphan here is a 400 on the next agent turn.
    call = {"id": "call_1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}
    agent_history = [
        Message("assistant", "x " * 400, tool_calls=[call]),
        Message("tool", "result text", tool_call_id="call_1"),
        Message("user", "and now?"),
    ]
    kept = assemble(agent_history, context_tokens=1024 + persona_tokens + 50, persona=persona)
    assert not any(m.role == "assistant" for m in kept), "the big call turn should be trimmed"
    assert not any(m.role == "tool" for m in kept), "an orphaned tool result must be dropped"

    # Whole pairs survive together when they fit.
    intact = assemble(agent_history[1:], context_tokens=4096, persona=persona)
    assert not any(m.role == "tool" for m in intact), "still orphaned, still dropped"
    paired = assemble(
        [Message("assistant", "short", tool_calls=[call]), *agent_history[1:]],
        context_tokens=4096,
        persona=persona,
    )
    assert [m.role for m in paired] == ["system", "assistant", "tool", "user"], paired

    # -- compaction ----------------------------------------------------------
    # Invented placeholder turns only; this file is tracked.
    turns = [Message("user", f"message number {n} " + "word " * 20) for n in range(10)]
    each = estimate_tokens(turns[0].content)

    assert plan_compaction(turns, room=each * 100) is None, "must not trip with room to spare"
    assert plan_compaction([], room=10) is None, "empty history has nothing to compact"

    planned = plan_compaction(turns, room=each * 5)
    assert planned is not None, "must trip when history overruns the room"
    older, newer = planned
    assert older and newer, "both halves must be non-empty"
    assert older + newer == turns, "compaction must partition, not drop"
    assert newer[-1] is turns[-1], "the newest turn is always kept verbatim"

    # A tool result must never start the kept half — its call would be gone.
    paired = [
        Message("user", "do the thing " + "word " * 20),
        Message("assistant", "", tool_calls=[{"id": "c1", "function": {"name": "t"}}]),
        Message("tool", "the result " + "word " * 20, tool_call_id="c1"),
        Message("user", "thanks " + "word " * 20),
    ]
    split = plan_compaction(paired, room=estimate_tokens(paired[0].content) * 2)
    if split is not None:
        assert split[1][0].role != "tool", "kept half must not open on an orphaned tool result"

    # Regression: history ending on a tool result must not be split into an
    # orphaned result. This is the normal mid-loop state when compaction is needed.
    tool_ending = [
        Message("user", "ask " + "word " * 20),
        Message("assistant", "", tool_calls=[{"id": "c2", "function": {"name": "t"}}]),
        Message("tool", "answer " + "word " * 20, tool_call_id="c2"),
    ]
    tool_split = plan_compaction(tool_ending, room=estimate_tokens(tool_ending[0].content))
    if tool_split is not None:
        assert tool_split[1][0].role != "tool", "must not split into orphaned result even at history end"

    # The summary is pinned: it survives a budget that evicts ordinary history.
    note = "Earlier in this conversation: they described a trip."
    out = assemble(turns, context_tokens=1400, persona=persona, summary=note)
    assert out[0].role == "system", "persona stays first"
    assert out[0].content == persona, "persona stays byte-identical"
    assert out[1].role == "user" and out[1].content == note, "summary is pinned right after the persona"

    # Absent a summary, output is unchanged from before this feature.
    assert assemble(turns, context_tokens=1400, persona=persona) == [
        m for m in assemble(turns, context_tokens=1400, persona=persona, summary="")
    ], "empty summary must be a no-op"

    # -- compact persona / profile-section chunks ----------------------------
    # Invented placeholder content only — same rule as the rest of this file.
    compact_sample = (
        "# Placeholder — Character Profile\n"
        "## How this file works\n"
        "Meta instructions the model must never see.\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n"
        "- placeholder glance line `[S-001]`\n"
        "## 1. Core Identity\n"
        "- placeholder identity line, retrievable only `[S-002]`\n"
        "## 6. Voice & Speech Patterns\n"
        "- placeholder voice line `[S-003]`\n"
        "## 10. Interaction Rules\n"
        "- placeholder hard constraint line, must never be dropped `[S-004]`\n"
        "## Changelog\n"
        "- v1 bookkeeping nobody should read\n"
    )

    compact = build_compact_persona_from(compact_sample)
    assert compact.startswith(FRAMING), "compact persona keeps the same framing prefix"
    assert "placeholder hard constraint line" in compact, (
        "hard constraints must survive into the compact persona"
    )
    assert "placeholder voice line" in compact, "voice register must survive into the compact persona"
    assert "placeholder glance line" in compact, "at-a-glance must survive into the compact persona"
    assert "placeholder identity line" not in compact, (
        "a retrievable-only section must not leak into the always-pinned compact persona"
    )
    assert "[S-" not in compact, "citations must not leak into the compact persona either"

    # A profile missing a required compact section must refuse loudly, not
    # silently ship a persona with no hard constraints in it.
    incomplete_sample = compact_sample.replace(
        "## 10. Interaction Rules", "## 10a. Renamed By Mistake"
    )
    try:
        build_compact_persona_from(incomplete_sample)
    except ProfileIncomplete as exc:
        assert "10. Interaction Rules" in str(exc), str(exc)
    else:
        raise AssertionError("expected ProfileIncomplete when a compact section is missing")

    chunks = profile_section_chunks_from(compact_sample)
    assert [c.key for c in chunks] == ["profile/1"], (
        "only the retrievable section present in the fixture should produce a chunk"
    )
    assert chunks[0].kind == "profile_section"
    assert chunks[0].story_id == "" and chunks[0].event_id == ""
    assert "placeholder identity line" in chunks[0].text
    assert "[S-" not in chunks[0].text, "citations must be stripped from retrievable chunks too"
    # A retrievable section simply absent from the profile is not an error —
    # unlike a missing *compact* section, it just means less to retrieve.
    assert "profile/5" not in [c.key for c in chunks]
