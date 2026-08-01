"""Tools the admin agent calls. Pure functions over data/, no HTTP, no model.

The API is deliberately narrow. A generic write_file would let a weak model
renumber the corpus or rewrite the profile wholesale, and the only thing
standing between that and the creator's ground truth would be how carefully
someone reads a diff at 1am. So the invariants live in the signatures:

    ids are allocated by code           the model cannot collide or skip one
    sources are append-only             there is no tool that edits an entry
    the profile edits one section       named up front, nothing else moves
    searches are capped                 sources.md is ~15k tokens

Writes do not write. They return a Proposal, and the creator applies it.
"""

from __future__ import annotations

import difflib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .bible import PROFILE_END, PROFILE_PATH, PROFILE_START

SOURCES_PATH = PROFILE_PATH.parent / "sources.md"
ENTRY = re.compile(r"^### (S-\d+)", re.MULTILINE)
SEARCH_LIMIT = 5
SOURCE_LOG_HEADING = "source log"
BACKUP_DIR = ".backups"


class StaleProposal(RuntimeError):
    """The file changed on disk since this proposal was built.

    Two proposals can be composed from the same snapshot in one turn — two
    `append_source` calls both computing the same next id, say. Applying the
    second on top of the first would silently erase the already-approved
    first write. Refuse instead: never merge, never overwrite.
    """


@dataclass
class Proposal:
    """A write that has not happened yet.

    The creator is the sole author of the character, so an agent may compose an
    edit but never land one. `apply()` is called by the UI after a human looks
    at `diff`, and it snapshots first because `data/` is gitignored — there is
    no other undo.
    """

    path: Path
    new_text: str
    summary: str
    diff: str
    # The changed span alone, so the UI can show before beside after rather
    # than making the creator read a unified diff to approve their own words.
    # Empty `before` means the span is new.
    before: str = ""
    after: str = ""
    # The full file text this proposal was built from. apply() re-reads and
    # compares before writing — see StaleProposal.
    old: str = ""

    def apply(self) -> Path:
        current = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        if current != self.old:
            raise StaleProposal(
                f"{self.path.name} changed since this proposal was built — "
                "read it again and re-propose rather than overwriting the "
                "newer content."
            )
        snapshot(self.path)
        self.path.write_text(self.new_text, encoding="utf-8")
        return self.path


def snapshot(path: Path) -> Path | None:
    """Copy a file into its sibling `.backups/` before it is overwritten.

    `data/` is gitignored, so these snapshots are the only undo that exists.
    """
    backups = path.parent / BACKUP_DIR
    backups.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    if not path.exists():
        return None
    # Two applies inside the same second would otherwise write the same name,
    # and the second would overwrite the snapshot the first just took — losing
    # exactly the state someone would want back.
    destination = backups / f"{path.name}.{stamp}"
    bump = 0
    while destination.exists():
        bump += 1
        destination = backups / f"{path.name}.{stamp}-{bump}"
    shutil.copy2(path, destination)
    return destination


def list_backups(directory: Path | None = None) -> list[Path]:
    """Snapshots of the two bible files, newest first.

    Restricted to those two names on purpose: this list feeds a restore
    button, and a restore is a whole-file overwrite. Anything else that ends
    up in the folder is not something to offer to write back.
    """
    directory = directory or SOURCES_PATH.parent
    backups = directory / BACKUP_DIR
    if not backups.is_dir():
        return []
    restorable = {SOURCES_PATH.name, PROFILE_PATH.name}
    found = [p for p in backups.iterdir() if p.is_file() and _restore_target_name(p) in restorable]
    return sorted(found, key=lambda p: p.name, reverse=True)


def _restore_target_name(backup: Path) -> str:
    """`sources.md.20260801T203941` -> `sources.md`."""
    return backup.name.rsplit(".", 1)[0]


def restore_backup(backup: Path, directory: Path | None = None) -> Path:
    """Roll one file back to a snapshot, snapshotting the current text first.

    An undo that destroys what it replaced is not an undo. The pre-restore
    snapshot is what makes this reversible in the other direction.

    The name is checked against the two bible files rather than trusted: this
    is the one path that overwrites a whole file, and a crafted name would
    otherwise choose the destination.
    """
    directory = directory or SOURCES_PATH.parent
    name = _restore_target_name(backup)
    if name not in {SOURCES_PATH.name, PROFILE_PATH.name}:
        raise ValueError(f"{backup.name!r} is not a snapshot of a bible file")
    if backup.resolve().parent != (directory / BACKUP_DIR).resolve():
        raise ValueError(f"{backup.name!r} is not in {directory / BACKUP_DIR}")
    target = directory / name
    snapshot(target)
    shutil.copy2(backup, target)
    return target


def _propose(
    path: Path,
    old: str,
    new: str,
    summary: str,
    before: str = "",
    after: str = "",
) -> Proposal:
    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=path.name,
            tofile=f"{path.name} (proposed)",
            n=2,
        )
    )
    return Proposal(
        path=path, new_text=new, summary=summary, diff=diff, before=before, after=after, old=old
    )


def _entries(text: str) -> list[str]:
    """Split a sources file into whole `### S-###` blocks."""
    starts = [m.start() for m in ENTRY.finditer(text)]
    return [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]


def search_sources(query: str, limit: int = SEARCH_LIMIT, path: Path | None = None) -> str:
    """Entries whose text contains every word of the query, case-insensitively.

    Substring matching, not embeddings: this runs against one local file of a
    few dozen entries, and a retrieval stack would be a lot of machinery to
    answer a question `in` already answers.
    """
    path = path or SOURCES_PATH
    words = [w.lower() for w in query.split() if w]
    hits = [
        entry
        for entry in _entries(path.read_text(encoding="utf-8"))
        if all(w in entry.lower() for w in words)
    ]
    if not hits:
        return f"no entries match {query!r}"
    capped = hits[:limit]
    out = "\n".join(e.strip() for e in capped)
    if len(hits) > limit:
        out += f"\n\n[{len(hits) - limit} more matches not shown — narrow the query]"
    return out


def _sections(text: str) -> list[tuple[str, int, int]]:
    """(heading, start, end) for every `## ` block, in file order."""
    marks = [(m.group(1), m.start()) for m in re.finditer(r"^## (.+)$", text, re.MULTILINE)]
    spans = []
    for i, (heading, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        spans.append((heading.strip(), start, end))
    return spans


def _editable_span(text: str) -> tuple[int, int]:
    """Absolute offsets of the bot-facing span — the same boundary
    `bible.slice_profile` uses, but unstripped, so section offsets stay
    correct against the whole file (which is what actually gets rewritten).
    """
    start = text.find(PROFILE_START)
    if start == -1:
        raise ValueError(f"{PROFILE_START!r} not found — is this a character profile?")
    end = text.find(PROFILE_END, start)
    return start, end if end != -1 else len(text)


def _find_section(text: str, heading: str) -> tuple[str, int, int]:
    """Locate one `## ` section within the bot-facing span only. The meta
    preamble (`## How this file works`) and the changelog are structurally
    unreachable here, not merely absent from the section index in the prompt.

    Exact match wins outright. A heading typed short (`"1"`) can prefix-match
    more than one real heading (`"1. Core Identity"` and `"10. Interaction
    Rules"`) — silently resolving to whichever is found first would risk
    rewriting the wrong section, one of which may hold the hard constraints.
    More than one prefix match is a refusal, not a guess.
    """
    edit_start, edit_end = _editable_span(text)
    wanted = heading.strip().lstrip("#").strip().lower()
    editable = [(n, s, e) for n, s, e in _sections(text) if edit_start <= s < edit_end]

    for name, start, end in editable:
        if name.lower() == wanted:
            return name, start, end

    prefix_matches = [(n, s, e) for n, s, e in editable if n.lower().startswith(wanted)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        candidates = ", ".join(n for n, _, _ in prefix_matches)
        raise KeyError(f"{heading!r} matches more than one section: {candidates}. Be exact.")

    known = ", ".join(n for n, _, _ in editable)
    raise KeyError(f"no section {heading!r}. Sections are: {known}")


def read_profile_section(heading: str, path: Path | None = None) -> str:
    path = path or PROFILE_PATH
    text = path.read_text(encoding="utf-8")
    _, start, end = _find_section(text, heading)
    return text[start:end].rstrip() + "\n"


def next_source_id(text: str) -> str:
    numbers = [int(m.group(1).split("-")[1]) for m in ENTRY.finditer(text)]
    return f"S-{max(numbers) + 1:03d}" if numbers else "S-001"


def _source_log_end(text: str) -> int:
    """End offset of the `## Source log` section — immediately before the
    next `## ` heading, or end of file if it's the last section (or absent
    entirely, so the tool still works on a fresh corpus that hasn't grown
    the heading yet)."""
    for name, _, end in _sections(text):
        if name.strip().lower() == SOURCE_LOG_HEADING:
            return end
    return len(text)


def append_source(
    answer: str,
    question: str,
    entry_type: str,
    tags: list[str],
    date: str,
    feeds: list[str],
    path: Path | None = None,
) -> Proposal:
    """Append one entry inside the `## Source log` section, in the field
    order `templates/sources.template.md` defines. There is no tool that
    edits or deletes an existing one.

    The id comes from the file, never from the model: an id the model picks is
    an id it can collide, skip, or reuse, and every cite in the profile points
    at one. An empty or `"unknown"` date falls back to today's date: the
    field records when the answer was logged, and it is being logged now —
    that is a fact the clock knows, not one the model invented. A date the
    creator gives for the material itself still wins over the fallback.
    """
    path = path or SOURCES_PATH
    old = path.read_text(encoding="utf-8")
    entry_id = next_source_id(old)
    given = date.strip()
    stamped = datetime.now().strftime("%Y-%m-%d") if given.lower() in ("", "unknown") else given
    tag_str = ", ".join(t.strip() for t in tags if t.strip()) or "unknown"
    feed_str = ", ".join(f.strip() for f in feeds if f.strip()) or "—"
    block = (
        f"\n### {entry_id}\n"
        f"- **Date:** {stamped}\n"
        f"- **Type:** {entry_type.strip()}\n"
        f"- **Tags:** {tag_str}\n"
        f"- **Q:** {question.strip()}\n"
        f"- **A:** {answer.strip()}\n"
        f"- **Feeds:** {feed_str}\n"
    )
    insert_at = _source_log_end(old)
    new = old[:insert_at].rstrip("\n") + "\n" + block + old[insert_at:]
    return _propose(
        path, old, new, f"append {entry_id} to {path.name}", before="", after=block.strip()
    )


# The profile cites two ways: `[S-004]` in prose, `` `S-002` `` in the table
# cells. Matching only the bracketed form let a table row be rewritten with its
# cite silently dropped, which is the exact loss the guard exists to stop.
CITE = re.compile(r"S-\d+")


def _guard_cites(old_text: str, new_text: str) -> None:
    """Refuse a write that silently drops a cite.

    Every statement in the profile carries the entry it came from, and that
    link is the only thing making the profile checkable against the record.
    A model rewriting prose drops cites without noticing — this turns that
    into a refusal it can read and correct, rather than a diff someone has to
    catch by eye at 1am.
    """
    lost = sorted(set(CITE.findall(old_text)) - set(CITE.findall(new_text)))
    if lost:
        missing = ", ".join(lost)
        raise ValueError(
            f"this edit drops {missing} — every statement keeps the cite it came "
            "from. Reproduce the cites, or edit a different line."
        )


def _is_table(lines: list[str]) -> bool:
    """Two or more `|` rows means the section is a table, not a bullet list."""
    return sum(1 for line in lines if line.lstrip().startswith("|")) >= 2


def _section_lines(text: str, heading: str) -> tuple[str, int, int, list[str]]:
    name, start, end = _find_section(text, heading)
    return name, start, end, text[start:end].splitlines()


def add_profile_line(heading: str, line: str, path: Path | None = None) -> Proposal:
    """Add one bullet to one section. Everything else stays byte-identical.

    The whole write path is one line wide on purpose. A tool that takes a
    section makes the model reproduce a document it can only half remember,
    and what comes back is fluent, plausible, and missing the cites. A tool
    that takes a line cannot lose what it never asked for.
    """
    path = path or PROFILE_PATH
    old = path.read_text(encoding="utf-8")
    body = line.strip()
    if "\n" in body:
        raise ValueError("one line per call — call this again for the next line")
    if not CITE.search(body):
        raise ValueError(
            "every line in the profile carries a cite like [S-042]. Add the "
            "entry this comes from, or log the answer with append_source first."
        )
    name, start, end, lines = _section_lines(old, heading)
    if _is_table(lines) and not body.startswith("|"):
        raise ValueError(
            f"{name!r} is a table — add a row, not a bullet: "
            "| Field | value | `S-###` |"
        )
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append(body)
    new_section = "\n".join(lines) + "\n\n"
    new = old[:start] + new_section + old[end:]
    return _propose(
        path, old, new, f"add a line to {name!r}", before="", after=body
    )


def replace_profile_line(
    heading: str, find: str, line: str, path: Path | None = None
) -> Proposal:
    """Replace the one line in a section containing `find`.

    Matching more than one line is a refusal, not a guess: the lines in a
    section are statements about a person, and rewriting the wrong one is
    indistinguishable from inventing a fact.
    """
    path = path or PROFILE_PATH
    old = path.read_text(encoding="utf-8")
    body = line.strip()
    if "\n" in body:
        raise ValueError("one line per call — call this again for the next line")
    name, start, end, lines = _section_lines(old, heading)
    needle = find.strip().lower()
    if not needle:
        raise ValueError("`find` must name the line to replace")
    hits = [i for i, existing in enumerate(lines) if needle in existing.lower()]
    if not hits:
        raise KeyError(f"no line in {name!r} contains {find!r}")
    if len(hits) > 1:
        matched = " | ".join(lines[i].strip()[:60] for i in hits)
        raise KeyError(f"{find!r} matches {len(hits)} lines in {name!r}: {matched}. Be exact.")
    index = hits[0]
    previous = lines[index]
    # A table row rewritten as a bullet ends the table and orphans every row
    # under it. Keep the shape the line already had.
    if previous.lstrip().startswith("|") != body.startswith("|"):
        wanted = "a table row (| … | … |)" if previous.lstrip().startswith("|") else "a bullet"
        raise ValueError(f"that line is {wanted} — the replacement has to be one too")
    _guard_cites(previous, body)
    lines[index] = body
    new = old[:start] + "\n".join(lines) + old[end:]
    return _propose(
        path, old, new, f"rewrite one line in {name!r}", before=previous.strip(), after=body
    )


def replace_profile_section(heading: str, text: str, path: Path | None = None) -> Proposal:
    """Replace exactly one `## ` section. Nothing outside it can move.

    Not offered to the agent — see `TOOL_SCHEMAS`. It stays for a rebuild,
    where a human or a long-context pass is authoring the whole section and
    the cite guard is a backstop rather than the only line of defence.
    """
    path = path or PROFILE_PATH
    old = path.read_text(encoding="utf-8")
    name, start, end = _find_section(old, heading)
    body = text.strip()
    # A demoted heading (`### 4. Foo`) would otherwise get a second `## `
    # prepended, leaving the file with two headings for one section.
    first, _, rest = body.partition("\n")
    if first.lstrip("#").strip().lower() == name.lower():
        body = f"## {name}\n{rest.lstrip()}"
    elif not body.startswith("## "):
        body = f"## {name}\n{body}"
    _guard_cites(old[start:end], body)
    new = old[:start] + body.rstrip() + "\n\n" + old[end:]
    return _propose(
        path,
        old,
        new,
        f"rewrite section {name!r}",
        before=old[start:end].rstrip(),
        after=body.rstrip(),
    )


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_sources",
            "description": (
                "Search the creator's logged answers. Returns whole entries "
                "whose text contains every word of the query. Capped — narrow "
                "the query rather than asking for more."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_profile_section",
            "description": (
                "Read one section of the character profile. Use the heading "
                "exactly as listed in the system prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {"heading": {"type": "string"}},
                "required": ["heading"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_source",
            "description": (
                "Propose appending a new entry to the sources file, verbatim, "
                "inside the Source log section. The entry id is assigned "
                "automatically. The creator must approve before anything is "
                "written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "The creator's answer, verbatim — do not tidy the phrasing.",
                    },
                    "question": {
                        "type": "string",
                        "description": "The question as asked, verbatim.",
                    },
                    "entry_type": {
                        "type": "string",
                        "description": (
                            "One of: direct answer | interview | public post | "
                            "observed event | existing bio."
                        ),
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Short topic tags, e.g. personality, fears.",
                    },
                    "date": {
                        "type": "string",
                        "description": (
                            "YYYY-MM-DD the answer was given, fuzzed per the "
                            "redaction policy if needed. Use the literal string "
                            "'unknown' if the date is not known — today's date "
                            "is filled in for you. Never guess a date."
                        ),
                    },
                    "feeds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Profile sections this entry should feed, e.g. '6. Voice'.",
                    },
                },
                "required": ["answer", "question", "entry_type", "tags", "date", "feeds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_profile_line",
            "description": (
                "Propose adding ONE line to a profile section. Read the section "
                "first so you do not repeat something already there. The line "
                "must carry the cite of the entry it comes from, e.g. "
                "'- **Lives in:** Berlin [S-075]'. Everything else in the file "
                "stays exactly as it is. The creator must approve."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "heading": {
                        "type": "string",
                        "description": "Section heading, exactly as listed in the system prompt.",
                    },
                    "line": {
                        "type": "string",
                        "description": (
                            "The single line to add, including its [S-###] cite. "
                            "Match the bullet style already used in that section."
                        ),
                    },
                },
                "required": ["heading", "line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_profile_line",
            "description": (
                "Propose rewriting ONE existing line in a profile section. Read "
                "the section first. `find` must identify exactly one line — if "
                "it matches several the call is refused. Keep every [S-###] cite "
                "the old line carried; add the new one alongside. The creator "
                "must approve."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "heading": {
                        "type": "string",
                        "description": "Section heading, exactly as listed in the system prompt.",
                    },
                    "find": {
                        "type": "string",
                        "description": (
                            "Distinctive text from the line to replace, e.g. "
                            "'Where she's from'."
                        ),
                    },
                    "line": {
                        "type": "string",
                        "description": "The full replacement line, cites included.",
                    },
                },
                "required": ["heading", "find", "line"],
            },
        },
    },
]

READ_TOOLS = {"search_sources": search_sources, "read_profile_section": read_profile_section}
# `replace_profile_section` is deliberately absent: the agent writes one line at
# a time. A section-shaped tool asks the model to reproduce a document, and what
# comes back is fluent, plausible, and stripped of its cites.
WRITE_TOOLS = {
    "append_source": append_source,
    "add_profile_line": add_profile_line,
    "replace_profile_line": replace_profile_line,
}

# name -> declared argument names, from TOOL_SCHEMAS. `path` is deliberately
# absent from every schema even though every handler accepts it — see
# run_tool.
TOOL_PROPERTIES = {
    schema["function"]["name"]: set(schema["function"]["parameters"]["properties"])
    for schema in TOOL_SCHEMAS
}


def run_tool(name: str, arguments: dict) -> str | Proposal:
    """Dispatch by name.

    Arguments are filtered to the tool's declared schema before the handler
    ever sees them: `path` is intentionally undeclared everywhere, so a model
    that emits `{"path": "C:\\Windows\\win.ini"}` gets it silently dropped
    rather than routed to `Path.read_text`. Unknown names, bad arguments, and
    any handler exception all come back as text — a handler must never kill
    the loop.
    """
    handler = READ_TOOLS.get(name) or WRITE_TOOLS.get(name)
    if handler is None:
        return f"no such tool {name!r}. Available: {', '.join([*READ_TOOLS, *WRITE_TOOLS])}"
    allowed = TOOL_PROPERTIES.get(name, set())
    dropped = sorted(k for k in arguments if k not in allowed)
    filtered = {k: v for k, v in arguments.items() if k in allowed}
    try:
        result = handler(**filtered)
    except TypeError as exc:
        return f"bad arguments for {name}: {exc}"
    except KeyError as exc:
        return str(exc).strip('"')
    except ValueError as exc:
        # A refused write. The message is written to be read by the model, so
        # it comes back unwrapped — it is an instruction, not an error report.
        return str(exc)
    except OSError as exc:
        return f"{name} could not read the file: {exc}"
    except Exception as exc:  # a handler must never kill the loop
        return f"{name} failed: {exc}"
    if dropped and isinstance(result, str):
        result = f"(ignored unknown arguments: {', '.join(dropped)})\n{result}"
    return result


def _self_check() -> None:
    import tempfile
    from pathlib import Path

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

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
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

        # A bare-number heading that prefix-matches more than one real
        # section (Critical 2: "1" matches both "1. Core Identity" and
        # "10. Interaction Rules") must refuse, not silently pick one.
        try:
            read_profile_section("1", path=target)
        except KeyError as exc:
            assert "Core Identity" in str(exc), str(exc)
            assert "Interaction Rules" in str(exc), str(exc)
        else:
            raise AssertionError("expected KeyError for an ambiguous prefix")
        # The full heading for either candidate is unambiguous and works.
        assert "hard constraint" in read_profile_section("10. Interaction Rules", path=target)

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
        kept = "### 6. Voice\n- old line\n- sharper claim [S-009] [S-011]\n- claim two [S-012]"
        rewritten_section = replace_profile_section("6. Voice", kept, path=target)
        assert "### 6. Voice" not in rewritten_section.new_text, "heading must be normalised"
        assert rewritten_section.new_text.count("## 6. Voice") == 1, rewritten_section.new_text

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
        global SOURCES_PATH, PROFILE_PATH
        real_sources_path, real_profile_path = SOURCES_PATH, PROFILE_PATH
        SOURCES_PATH, PROFILE_PATH = sources, target
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
            SOURCES_PATH, PROFILE_PATH = real_sources_path, real_profile_path

    print("tools self-check: ok")


if __name__ == "__main__":
    _self_check()
