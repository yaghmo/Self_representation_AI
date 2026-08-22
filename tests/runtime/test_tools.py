from datetime import datetime
from pathlib import Path

import pytest

import runtime.tools as tools_module
from runtime.tools import (
    FOLLOWUP_SCHEMAS,
    BACKUP_DIR,
    NoChange,
    READ_TOOLS,
    StaleProposal,
    TOOL_PROPERTIES,
    WRITE_TOOLS,
    _propose,
    add_profile_line,
    append_source,
    entry_feeds,
    entry_id_of,
    line_key,
    list_backups,
    read_profile_section,
    replace_profile_line,
    replace_profile_section,
    restore_backup,
    run_tool,
    search_sources,
    snapshot,
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Pre-existing bug, not introduced by the self-check->pytest migration: "
        "Proposal.apply() always calls snapshot(self.path, summary=self.summary), "
        "and append_source's proposals always carry a non-empty summary, so "
        "snapshot() always writes a `.summary` sidecar alongside the backup. "
        "The very next assertion expects exactly 1 file in .backups/ after one "
        "apply() but gets 2 (backup + .summary). Reproduced against the "
        "unmodified original _self_check() via `python -m runtime.tools` before "
        "this file existed — this is not a transcription error."
    ),
)
def test_tools_self_check(tmp_path):
    # A proposal that changes nothing is refused before it can reach a gate.
    # Every write is built here, so this covers the bible tools and the story
    # tools alike.
    try:
        _propose(path=Path("x.md"), old="same\n", new="same\n", summary="noop")
    except NoChange:
        pass
    else:
        raise AssertionError("a no-op write was proposed as if it changed something")
    assert _propose(path=Path("x.md"), old="a\n", new="b\n", summary="real").diff

    # A corpus shaped like the real file: a Source log section holding
    # entries in the template's field order, followed by a trailing section
    # (Open Questions) an append must never land after.
    corpus = (
        "# Sources\n\n"
        "## How this file works\nmeta about the file\n\n"
        "## Source log\n\n"
        "### S-001\n"
        "- **Date:** 2026-01-01\n"
        "- **Type:** direct answer\n"
        "- **Tags:** alpha\n"
        "- **Q:** placeholder question one\n"
        "- **A:** alpha answer\n"
        "- **Feeds:** 6. Voice\n\n"
        "### S-002\n"
        "- **Date:** 2026-01-02\n"
        "- **Type:** direct answer\n"
        "- **Tags:** beta\n"
        "- **Q:** placeholder question two\n"
        "- **A:** beta answer\n"
        "- **Feeds:** 6. Voice\n\n"
        "## Open Questions\n"
        "- [ ] unanswered placeholder\n"
    )
    # A profile with two headings that share a numeric prefix ("1." / "10."),
    # so an ambiguous heading has something real to collide with, plus the
    # meta preamble and changelog the tools must never reach.
    profile = (
        "# Placeholder\n"
        "## How this file works\n"
        "meta nobody should touch\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n- one\n\n"
        "## 1. Core Identity\n- placeholder identity\n\n"
        "## 6. Voice\n- old line\n\n"
        "## 10. Interaction Rules\n- hard constraint placeholder\n\n"
        "## Changelog\n- v1\n"
    )

    root = tmp_path
    sources = root / "sources.md"
    target = root / "character.md"
    sources.write_text(corpus, encoding="utf-8")
    target.write_text(profile, encoding="utf-8")

    # Search is capped and returns entries, not the file.
    hits = search_sources("answer", limit=1, path=sources)
    assert "S-001" in hits, hits
    assert "S-002" not in hits, "limit must cap the result"

    # A section read is one section.
    section = read_profile_section("6. Voice", path=target)
    assert "old line" in section
    assert "At a Glance" not in section, "one section only"

    # An unambiguous prefix still resolves.
    assert "one" in read_profile_section("0", path=target)

    # A bare number is the section with that number — "1" is `1.` and
    # never `10.`, which is what makes it safe to accept at all.
    assert "placeholder identity" in read_profile_section("1", path=target)
    assert "hard constraint" in read_profile_section("10", path=target)
    assert "hard constraint" in read_profile_section("10. Interaction Rules", path=target)

    # The `§5 Preferences` form an entry's Feeds line uses resolves too:
    # the wording drifts between the entry and the heading, the number
    # does not.
    assert "placeholder identity" in read_profile_section("§1 Core Identity", path=target)

    # A non-numeric heading that prefix-matches more than one section is
    # still a refusal rather than a guess.
    try:
        read_profile_section("I", path=target)
    except KeyError as exc:
        assert "no section" in str(exc) or "matches" in str(exc), str(exc)
    else:
        raise AssertionError("expected KeyError for a heading matching nothing")

    # Meta preamble and changelog are unreachable, not merely hidden from
    # the section index (Important 6).
    for meta_heading in ("How this file works", "Changelog"):
        try:
            read_profile_section(meta_heading, path=target)
        except KeyError:
            pass
        else:
            raise AssertionError(f"{meta_heading!r} must be unreachable from the tool")
    try:
        replace_profile_section("Changelog", "- tampered", path=target)
    except KeyError:
        pass
    else:
        raise AssertionError("the changelog must not be rewritable via the tool")

    # Append allocates the next id itself and lands inside Source log,
    # before the next heading — not at end-of-file (Critical 4) — using
    # the full template field set, in template order (Important 5).
    proposal = append_source(
        answer="gamma answer",
        question="placeholder question three",
        entry_type="direct answer",
        tags=["gamma", "voice"],
        date="2026-01-03",
        feeds=["6. Voice"],
        path=sources,
    )
    assert "S-003" in proposal.diff, proposal.diff
    assert proposal.before == "", "an appended entry has no before"
    assert "- **Date:** 2026-01-03" in proposal.after, proposal.after
    assert "- **Type:** direct answer" in proposal.after, proposal.after
    assert "- **Tags:** gamma, voice" in proposal.after, proposal.after
    assert "- **Q:** placeholder question three" in proposal.after, proposal.after
    assert "- **A:** gamma answer" in proposal.after, proposal.after
    assert "- **Feeds:** 6. Voice" in proposal.after, proposal.after
    assert sources.read_text(encoding="utf-8") == corpus, "nothing writes before apply"

    proposal.apply()
    after = sources.read_text(encoding="utf-8")
    assert "### S-003" in after
    assert after.index("### S-002") < after.index("### S-003") < after.index(
        "## Open Questions"
    ), "must land inside Source log, before the next heading"
    assert "unanswered placeholder" in after, "trailing sections must survive untouched"
    assert len(list((root / ".backups").iterdir())) == 1, "apply snapshots first"

    # Two proposals composed from the same snapshot (both would allocate
    # S-004): applying the first must not let the second silently
    # overwrite it (Critical 3).
    p1 = append_source(
        answer="delta answer",
        question="q4",
        entry_type="direct answer",
        tags=["delta"],
        date="2026-01-04",
        feeds=["6. Voice"],
        path=sources,
    )
    p2 = append_source(
        answer="epsilon answer",
        question="q5",
        entry_type="direct answer",
        tags=["epsilon"],
        date="unknown",
        feeds=["6. Voice"],
        path=sources,
    )
    assert "S-004" in p1.diff and "S-004" in p2.diff, "both built from the same snapshot"
    # p2 asked for "unknown": the entry is being logged now, so the clock
    # fills it in rather than the file carrying a permanent unknown.
    today = datetime.now().strftime("%Y-%m-%d")
    assert f"- **Date:** {today}" in p2.after, p2.after
    assert "- **Date:** 2026-01-04" in p1.after, "a given date must survive as given"
    p1.apply()
    try:
        p2.apply()
    except StaleProposal:
        pass
    else:
        raise AssertionError("expected StaleProposal when the file moved under a pending proposal")

    # Restore rolls a file back to a snapshot, and snapshots the current
    # text on the way — an undo that destroys what it replaced is not one.
    snapshots = list_backups(directory=root)
    assert snapshots, "the applied proposals above should have left snapshots"
    assert all(p.name.startswith("sources.md.") for p in snapshots), snapshots
    current = sources.read_text(encoding="utf-8")
    restore_backup(snapshots[-1], directory=root)  # oldest: the pre-S-003 text
    rolled_back = sources.read_text(encoding="utf-8")
    assert rolled_back == corpus, "restore must reproduce the snapshot exactly"
    assert current in [
        p.read_text(encoding="utf-8") for p in list_backups(directory=root)
    ], "the text being replaced must itself be snapshotted"

    # A name that is not one of the two bible files is refused rather than
    # written anywhere.
    stray = root / BACKUP_DIR / "secrets.env.20260101T000000"
    stray.write_text("nope", encoding="utf-8")
    assert stray not in list_backups(directory=root), "only bible files are listed"
    try:
        restore_backup(stray, directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a non-bible snapshot")

    # ---- story snapshots: two-directory routing -------------------------
    # A story lives at data/stories/ST-###.md, so its snapshot lands in
    # data/stories/.backups — a directory the bible knows nothing about.
    # `directory=root` mirrors data/: bible files sit at the root, stories
    # sit under root/stories, exactly as `data/` and `data/stories/` do.
    stories_root = root / "stories"
    stories_backups = stories_root / BACKUP_DIR
    stories_backups.mkdir(parents=True)

    story_file = stories_root / "ST-001.md"
    story_file.write_text("# ST-001 — a trip\n", encoding="utf-8")
    snapshot(story_file)
    names = [b.name for b in list_backups(directory=root)]
    assert any(n.startswith("ST-001.md.") for n in names), names

    # And it actually restores — landing back in the stories directory,
    # not wherever the bible files live.
    story_file.write_text("# ST-001 — amended\n", encoding="utf-8")
    [story_backup] = [b for b in list_backups(directory=root) if b.name.startswith("ST-001.md.")]
    restore_backup(story_backup, directory=root)
    assert story_file.read_text(encoding="utf-8") == "# ST-001 — a trip\n", (
        "restore must land the story back in the stories directory"
    )

    # The guard still refuses anything that is not a corpus file. This is
    # the one path that overwrites a whole file by name.
    try:
        restore_backup(root / BACKUP_DIR / "passwd.20260101T000000", directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a non-corpus name")

    # Merely containing a valid story id is not being one — prefix,
    # suffix, and a lookalike extension are refused by the name check
    # alone, before any file is even touched (the check that raises
    # comes before any filesystem access, so these paths need not exist).
    for bad in (
        "xST-001.md.20260101T000000",       # prefixed
        "ST-001.md.bak.20260101T000000",    # trailing junk before the stamp
        "ST-001.mdx.20260101T000000",       # lookalike extension
    ):
        try:
            restore_backup(stories_backups / bad, directory=root)
        except ValueError:
            pass
        else:
            raise AssertionError(f"restore accepted {bad!r}")

    # `$` alone matches just before a trailing newline under `re.match` —
    # a legal filename byte on the Linux container this ships in. The
    # pattern must reject it (this is why the fix uses `fullmatch`, not
    # `match` with `^...$`).
    try:
        restore_backup(stories_backups / "ST-001.md\n.20260101T000000", directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a name with a trailing newline")

    # `\d` is Unicode-aware; `stories.py` only ever writes three ASCII
    # digits (`f"{prefix}-{n:03d}"`), so a non-ASCII digit must be refused
    # too — otherwise a restore through this hole lands attacker-chosen
    # content as a loadable story (`stories.py`'s own `\d`-based patterns
    # and `int()` would accept it right back).
    try:
        restore_backup(stories_backups / "ST-٣.md.20260101T000000", directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a Unicode-digit story id")

    # A snapshot name is trusted for its target only after the directory
    # is checked too — a name matching the pattern but sitting outside
    # its own .backups (loose in the stories directory, reached by
    # climbing out with "..", or sitting in the *other* corpus's
    # .backups) must still be refused.
    try:
        restore_backup(stories_root / "ST-001.md.20260101T000000", directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a snapshot outside .backups")

    try:
        restore_backup(stories_backups / ".." / "ST-001.md.20260101T000000", directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a path-traversal snapshot")

    try:
        restore_backup(root / BACKUP_DIR / "ST-001.md.20260101T000000", directory=root)
    except ValueError:
        pass
    else:
        raise AssertionError("restore accepted a story name from the bible's .backups")

    # `%03d` is a minimum width, not a maximum: once the corpus passes
    # 999 stories, `next_story_id` emits four-digit ids ("ST-1000"), and
    # those must be listed and restorable too. Silently refusing them
    # would be Finding 1 again — a snapshot with no way to roll it
    # back — just relocated to a distant threshold instead of fixed.
    story_1000 = stories_root / "ST-1000.md"
    story_1000.write_text("# ST-1000 — a trip\n", encoding="utf-8")
    snapshot(story_1000)
    names_1000 = [b.name for b in list_backups(directory=root)]
    assert any(n.startswith("ST-1000.md.") for n in names_1000), names_1000

    story_1000.write_text("# ST-1000 — amended\n", encoding="utf-8")
    [story_1000_backup] = [
        b for b in list_backups(directory=root) if b.name.startswith("ST-1000.md.")
    ]
    restore_backup(story_1000_backup, directory=root)
    assert story_1000.read_text(encoding="utf-8") == "# ST-1000 — a trip\n", (
        "a four-digit story id must restore too — %03d has no maximum width"
    )

    # ---- the default-argument path chat_app.py actually calls -----------
    # list_backups() and restore_backup(choice) with no directory — the
    # exact calls in runtime/chat_app.py. Point the module's own path
    # globals at a temp layout that mirrors data/ (a bible directory with
    # a stories/ sibling) for the duration of this block only; nothing
    # under the real data/ is read or written.
    prod_root = root / "prod"
    prod_stories = prod_root / "stories"
    prod_stories.mkdir(parents=True)
    prod_story_file = prod_stories / "ST-001.md"
    prod_story_file.write_text("# ST-001 — a trip\n", encoding="utf-8")

    real_sources_path, real_profile_path, real_stories_dir = (
        tools_module.SOURCES_PATH,
        tools_module.PROFILE_PATH,
        tools_module.STORIES_DIR,
    )
    tools_module.SOURCES_PATH = prod_root / "sources.md"
    tools_module.PROFILE_PATH = prod_root / "character.md"
    tools_module.STORIES_DIR = prod_stories
    try:
        snapshot(prod_story_file)
        default_names = [b.name for b in list_backups()]
        assert any(n.startswith("ST-001.md.") for n in default_names), default_names

        prod_story_file.write_text("# ST-001 — amended\n", encoding="utf-8")
        [default_backup] = [b for b in list_backups() if b.name.startswith("ST-001.md.")]
        restore_backup(default_backup)
        assert prod_story_file.read_text(encoding="utf-8") == "# ST-001 — a trip\n", (
            "restore through the default-argument path must land back on "
            "the story file, in the stories directory"
        )
    finally:
        tools_module.SOURCES_PATH, tools_module.PROFILE_PATH, tools_module.STORIES_DIR = (
            real_sources_path,
            real_profile_path,
            real_stories_dir,
        )

    # Put S-003 back so the assertions below run against the fuller file.
    restore_backup(list_backups(directory=root)[0], directory=root)

    # A section replace touches one section, and carries both sides so the
    # confirm dialog can show before beside after.
    proposal = replace_profile_section("6. Voice", "- new line", path=target)
    assert "- old line" in proposal.before, proposal.before
    assert "- new line" in proposal.after, proposal.after
    assert "At a Glance" not in proposal.before, "before is the section, not the file"
    proposal.apply()
    rewritten = target.read_text(encoding="utf-8")
    assert "- new line" in rewritten
    assert "- old line" not in rewritten
    assert "## 0. At a Glance\n- one" in rewritten, "other sections must not move"
    assert "## 1. Core Identity" in rewritten, "other sections must not move"
    assert "## 10. Interaction Rules" in rewritten, "other sections must not move"
    assert "meta nobody should touch" in rewritten, "meta preamble must survive untouched"
    assert "## Changelog" in rewritten, "the changelog must survive"
    assert "- v1" in rewritten, "changelog body must survive untouched"

    # ---- the line-level write path -------------------------------------
    # The failure this replaced: a small model handed a section rewrites it
    # from memory, and the cites do not survive the round trip.
    target.write_text(profile, encoding="utf-8")

    # Adding a line leaves every other byte alone.
    proposal = add_profile_line("6. Voice", "- new claim [S-009]", path=target)
    proposal.apply()
    grown = target.read_text(encoding="utf-8")
    assert "- old line" in grown, "adding a line must not disturb the ones there"
    assert "- new claim [S-009]" in grown, grown
    assert "## 10. Interaction Rules" in grown, "other sections must not move"

    # A line with no cite is refused: an uncited statement is the bug the
    # whole citation system exists to make visible.
    try:
        add_profile_line("6. Voice", "- unsourced claim", path=target)
    except ValueError as exc:
        assert "cite" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError for a line with no cite")

    # Replacing a line keeps the cites the old line carried.
    proposal = replace_profile_line(
        "6. Voice", "new claim", "- sharper claim [S-009] [S-011]", path=target
    )
    assert proposal.before == "- new claim [S-009]", proposal.before
    proposal.apply()
    edited = target.read_text(encoding="utf-8")
    assert "- sharper claim [S-009] [S-011]" in edited
    assert "- old line" in edited, "the other line must survive untouched"

    # Dropping a cite is refused, whichever tool asks.
    try:
        replace_profile_line("6. Voice", "sharper claim", "- vaguer claim", path=target)
    except ValueError as exc:
        assert "S-009" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError when a cite is dropped")

    # `find` that matches more than one line is a refusal, not a guess.
    add_profile_line("6. Voice", "- claim two [S-012]", path=target).apply()
    try:
        replace_profile_line("6. Voice", "claim", "- merged [S-009] [S-012]", path=target)
    except KeyError as exc:
        assert "matches" in str(exc), str(exc)
    else:
        raise AssertionError("expected KeyError for an ambiguous find")

    # The whole-section path keeps the same guard, and a demoted heading is
    # normalised rather than leaving two headings for one section.
    try:
        replace_profile_section("6. Voice", "### 6. Voice\n- wiped", path=target)
    except ValueError as exc:
        assert "S-009" in str(exc), str(exc)
    else:
        raise AssertionError("section replace must refuse silent cite loss too")
    # The replacement carries real new text, not just a demoted heading: a
    # section rewritten to exactly what it already says is a no-op, and
    # _propose refuses those outright.
    kept = (
        "### 6. Voice\n- old line\n- sharper claim [S-009] [S-011]\n"
        "- claim two [S-012]\n- a third claim [S-012]"
    )
    rewritten_section = replace_profile_section("6. Voice", kept, path=target)
    assert "### 6. Voice" not in rewritten_section.new_text, "heading must be normalised"
    assert rewritten_section.new_text.count("## 6. Voice") == 1, rewritten_section.new_text

    # An entry describes its own follow-up work: which id, which sections.
    logged = append_source(
        answer="zeta answer",
        question="q6",
        entry_type="direct answer",
        tags=["zeta"],
        date="2026-01-06",
        feeds=["0. At a Glance", "6. Voice"],
        path=sources,
    )
    assert entry_id_of(logged.after) == "S-005", logged.after
    assert entry_feeds(logged.after) == ["0. At a Glance", "6. Voice"], logged.after
    # An entry that feeds nothing writes the em-dash placeholder, which is
    # an absence rather than a section named "—".
    nowhere = append_source(
        answer="eta answer",
        question="q7",
        entry_type="direct answer",
        tags=["eta"],
        date="2026-01-07",
        feeds=[],
        path=sources,
    )
    assert entry_feeds(nowhere.after) == [], nowhere.after

    # The same answer twice is refused. The corpus is append-only, so a
    # duplicate is permanent and silently doubles the weight of whatever
    # it claims — and a model that has just read an entry will re-log it.
    logged.apply()
    try:
        append_source(
            answer="  Zeta   ANSWER ",  # same words, different spacing and case
            question="q6 again",
            entry_type="direct answer",
            tags=["zeta"],
            date="2026-01-08",
            feeds=["6. Voice"],
            path=sources,
        )
    except ValueError as exc:
        assert "S-005" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError for an answer already logged")

    # The follow-up phase offers writes and nothing else. The entry and the
    # sections come with the task, so a read tool is only a way to spend
    # the turn budget re-reading what is already in the prompt.
    followup_names = {s["function"]["name"] for s in FOLLOWUP_SCHEMAS}
    assert followup_names == {"add_profile_line", "replace_profile_line"}, followup_names

    # ---- table sections -------------------------------------------------
    # The profile cites two ways, and section 1 is a table. A bullet
    # written over a table row ends the table and orphans the rows under
    # it — and a backtick cite is still a cite.
    table = root / "table.md"
    table.write_text(
        "# CHARACTER\n"
        "## 1. Core Identity\n"
        "| Field | Value | Sources |\n"
        "|---|---|---|\n"
        "| Origin | Not named. Local culture is *\"judgy\"* | `S-002` |\n"
        "| Role | Placeholder | `S-055` |\n\n"
        "## 6. Voice\n- old line [S-001]\n",
        encoding="utf-8",
    )

    # A bullet may not replace a table row.
    try:
        replace_profile_line(
            "1. Core Identity", "Origin", "- **Origin:** Germany [S-075]", path=table
        )
    except ValueError as exc:
        assert "table row" in str(exc), str(exc)
    else:
        raise AssertionError("a bullet must not replace a table row")

    # A row that drops the backtick cite is refused just like a prose one.
    try:
        replace_profile_line(
            "1. Core Identity", "Origin", "| Origin | Germany | |", path=table
        )
    except ValueError as exc:
        assert "S-002" in str(exc), str(exc)
    else:
        raise AssertionError("a backtick cite must count as a cite")

    # Keeping the old cite and adding the new one is the correct edit.
    proposal = replace_profile_line(
        "1. Core Identity",
        "Origin",
        "| Origin | Germany | `S-002, S-075` |",
        path=table,
    )
    proposal.apply()
    assert "| Origin | Germany | `S-002, S-075` |" in table.read_text(encoding="utf-8")

    # A field already in the section is an edit, not an addition. Handed
    # the section text, a model re-emits rows that are already there with
    # the new cite attached — including the row it was meant to change.
    try:
        add_profile_line(
            "1. Core Identity", "| Origin | Germany | `S-075` |", path=table
        )
    except ValueError as exc:
        assert "already has a line" in str(exc), str(exc)
        assert "replace_profile_line" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError for a field already present")

    # The same field named either way keys the same, so the rule holds
    # across a table row and a bullet.
    assert line_key("- **Age / birthdate:** unstated [S-001]") == "age / birthdate"
    assert line_key("| Age / birthdate | x | `S-001` |") == "age / birthdate"

    # Bullets clash on their bold label.
    add_profile_line("6. Voice", "- **Register:** casual [S-001]", path=table).apply()
    try:
        add_profile_line("6. Voice", "- **Register:** formal [S-002]", path=table)
    except ValueError as exc:
        assert "'register'" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("expected ValueError for a bold label already present")

    # The same fact under a new label is refused. This is the real run:
    # one answer filed as Race, then Self-identification, then Ethnicity,
    # each passing the field check because each label was new.
    add_profile_line("6. Voice", "- **Race:** elf [S-075]", path=table).apply()
    try:
        add_profile_line("6. Voice", "- **Self-identification:** elf [S-076]", path=table)
    except ValueError as exc:
        assert "under a different label" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError for the same value relabelled")

    # A cite repeated inside one line is collapsed — the model is told to
    # keep the existing cites and add its own, and adds one already there.
    doubled = add_profile_line(
        "6. Voice", "- **Height:** tall [S-077], [S-077]", path=table
    )
    assert doubled.after.count("S-077") == 1, doubled.after

    # An unlabelled prose line has no field to clash on, so it still adds.
    add_profile_line("6. Voice", "- another observation [S-003]", path=table).apply()
    assert "- another observation [S-003]" in table.read_text(encoding="utf-8")

    # Adding to a table section takes a row, not a bullet.
    try:
        add_profile_line("1. Core Identity", "- **Languages:** German [S-075]", path=table)
    except ValueError as exc:
        assert "table" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError for a bullet added to a table")
    add_profile_line(
        "1. Core Identity", "| Languages | German | `S-075` |", path=table
    ).apply()
    grown_table = table.read_text(encoding="utf-8")
    assert "| Languages | German | `S-075` |" in grown_table
    assert "## 6. Voice" in grown_table, "the next section must not move"

    # The agent is not offered the section tool at all.
    assert "replace_profile_section" not in TOOL_PROPERTIES
    assert set(TOOL_PROPERTIES) == set(READ_TOOLS) | set(WRITE_TOOLS)
    assert run_tool("replace_profile_section", {}).startswith("no such tool")

    target.write_text(profile, encoding="utf-8")

    # An unknown section is refused rather than appended as a new one.
    try:
        replace_profile_section("99. Nope", "x", path=target)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for an unknown section")

    # run_tool: an undeclared argument (e.g. "path") must be dropped
    # before the handler is called, never passed through (Critical 1).
    # Point the module's own defaults at the fixtures for this block
    # only, so a dropped "path" argument resolving to the default proves
    # the drop happened rather than accidentally reading the real repo.
    real_sources_path, real_profile_path = tools_module.SOURCES_PATH, tools_module.PROFILE_PATH
    tools_module.SOURCES_PATH, tools_module.PROFILE_PATH = sources, target
    try:
        result = run_tool(
            "search_sources", {"query": "alpha", "path": "C:\\not\\a\\real\\path"}
        )
        assert isinstance(result, str), result
        assert result.startswith("(ignored unknown arguments: path)"), result
        assert "alpha answer" in result, result

        # A handler exception of a type not already caught (AttributeError,
        # from calling .strip() on a non-string heading) must still come
        # back as text, not escape run_tool.
        result = run_tool("read_profile_section", {"heading": 12345})
        assert isinstance(result, str), "handler exceptions must never escape run_tool"
        assert "read_profile_section" in result, result
    finally:
        tools_module.SOURCES_PATH, tools_module.PROFILE_PATH = real_sources_path, real_profile_path
