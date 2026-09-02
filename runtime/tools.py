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

from pydantic import BaseModel, ValidationError

from .bible import PROFILE_END, PROFILE_PATH, PROFILE_START
from .stories import STORIES_DIR

SOURCES_PATH = PROFILE_PATH.parent / "sources.md"
ENTRY = re.compile(r"^### (S-\d+)", re.MULTILINE)
SEARCH_LIMIT = 5
SOURCE_LOG_HEADING = "source log"
BACKUP_DIR = ".backups"
# A profile section can run to 2,000 tokens. Two of those fill a small model's
# window before it has done anything, and the loop then dies of old age rather
# than of the task being hard. Truncation is visible, so the model can narrow
# rather than assume it saw everything.
MAX_RESULT_CHARS = 3000


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
        # The first story lands in a `data/stories/` that nothing has created
        # yet, and `snapshot()` writes into a subdirectory of it. The bible
        # files always have a parent, so this only ever fires on a new corpus.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        snapshot(self.path, summary=self.summary)
        self.path.write_text(self.new_text, encoding="utf-8")
        return self.path


def snapshot(path: Path, summary: str = "") -> Path | None:
    """Copy a file into its sibling `.backups/` before it is overwritten.

    `data/` is gitignored, so these snapshots are the only undo that exists.
    `summary`, if given, is the proposal that is about to overwrite `path` —
    written as a sidecar `<name>.summary` so the restore list can show what a
    snapshot is a state *before*, instead of a bare timestamp.
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
    if summary:
        summary_path(destination).write_text(summary, encoding="utf-8")
    return destination


def summary_path(backup: Path) -> Path:
    """The sidecar summary file a backup's own name implies."""
    return backup.with_name(backup.name + ".summary")


# Admits every id `next_story_id` can emit (3+ digits, `%03d` is a minimum
# width not a maximum) while excluding what it never emits. `[0-9]` not `\d`
# — `\d` is Unicode-aware and `int()` would happily parse a match like
# "ST-٣.md", letting a restore land attacker-chosen content as a story.
# `fullmatch` not `match` with `^…$` — `$` alone matches before a trailing
# newline, a legal filename byte on the Linux container this ships in.
STORY_NAME = re.compile(r"ST-[0-9]{3,}\.md")


def _corpus_roots(directory: Path | None) -> tuple[Path, Path]:
    """(bible_dir, stories_dir) — the exactly-two directories a snapshot may
    belong to. A story's snapshot lands beside the story file
    (`data/stories/.backups`), not beside the bible (`data/.backups`), so
    both have to be known rather than one being assumed.

    This is a closed, hardcoded pair — never a directory derived from a
    snapshot's own name in a general way. That is the one thing this whole
    module exists to prevent: a crafted name choosing where a restore
    writes.
    """
    bible_dir = directory or SOURCES_PATH.parent
    stories_dir = STORIES_DIR if directory is None else directory / "stories"
    return bible_dir, stories_dir


def list_backups(directory: Path | None = None) -> list[Path]:
    """Snapshots of the corpus files (bible + stories), newest first.

    Scans exactly the two known directories, and a name only counts in the
    directory that matches its own kind — a story-shaped name sitting in the
    bible's `.backups` is not offered, and vice versa. Anything else that
    ends up in either folder is not something to offer to write back.
    """
    bible_dir, stories_dir = _corpus_roots(directory)
    found: list[Path] = []

    bible_backups = bible_dir / BACKUP_DIR
    if bible_backups.is_dir():
        found += [
            p
            for p in bible_backups.iterdir()
            if p.is_file() and _restore_target_name(p) in {SOURCES_PATH.name, PROFILE_PATH.name}
        ]

    story_backups = stories_dir / BACKUP_DIR
    if story_backups.is_dir():
        found += [
            p
            for p in story_backups.iterdir()
            if p.is_file() and STORY_NAME.fullmatch(_restore_target_name(p))
        ]

    return sorted(found, key=lambda p: p.name, reverse=True)


def _restore_target_name(backup: Path) -> str:
    """`sources.md.20260801T203941` -> `sources.md`."""
    return backup.name.rsplit(".", 1)[0]


def restore_backup(backup: Path, directory: Path | None = None) -> Path:
    """Roll one file back to a snapshot, snapshotting the current text first
    (an undo that destroys what it replaced is not an undo).

    The destination is picked from the closed pair `_corpus_roots` returns,
    never derived from the snapshot's name in a general way — a bible name
    routes to the bible directory, a story name to the story directory, and
    the snapshot is then confirmed to actually live in that directory's own
    `.backups` (a name matching the pattern but sitting anywhere else, e.g.
    reached by climbing out with `..`, is refused).
    """
    bible_dir, stories_dir = _corpus_roots(directory)
    name = _restore_target_name(backup)

    if name in {SOURCES_PATH.name, PROFILE_PATH.name}:
        target_dir = bible_dir
    elif STORY_NAME.fullmatch(name):
        target_dir = stories_dir
    else:
        raise ValueError(f"{backup.name!r} is not a snapshot of a corpus file")

    if backup.resolve().parent != (target_dir / BACKUP_DIR).resolve():
        raise ValueError(f"{backup.name!r} is not in {target_dir / BACKUP_DIR}")

    target = target_dir / name
    snapshot(target, summary=f"before restoring {backup.name}")
    shutil.copy2(backup, target)
    return target


class NoChange(ValueError):
    """The proposed text is what the file already holds.

    Every write in this repo goes through a confirm gate, and a gate that
    reports "applied" over an empty diff teaches the creator to trust a write
    that did not happen. Observed on the amend branch: the ingestion pass
    returned the target paragraph unchanged, the file round-tripped
    byte-identical, a backup was taken, and the story was reported as amended.

    Raised here rather than checked per caller — every proposal in the repo is
    built by `_propose`, so this is the one place all of them pass through.
    """


def _propose(
    path: Path,
    old: str,
    new: str,
    summary: str,
    before: str = "",
    after: str = "",
) -> Proposal:
    if new == old:
        raise NoChange(
            f"{path.name} already reads exactly this — nothing to write. "
            "Nothing was changed."
        )

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
    wanted = heading.strip().lstrip("#").lstrip("§").strip().lower()
    editable = [(n, s, e) for n, s, e in _sections(text) if edit_start <= s < edit_end]

    for name, start, end in editable:
        if name.lower() == wanted:
            return name, start, end

    # Sections are numbered, and every way of naming one carries the number:
    # "§5 Preferences" from an entry's Feeds line, "5. Preferences & Texture"
    # from the index, a bare "5" from a model being terse. The number is the
    # part that never drifts, and it identifies the section exactly — "1" is
    # `1.` and never `10.`.
    numbered = re.match(r"(\d+)", wanted)
    if numbered:
        prefix = f"{numbered.group(1)}."
        for name, start, end in editable:
            if name.startswith(prefix):
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

    The id comes from the file, never the model — a model-picked id can
    collide, skip, or reuse, and every cite in the profile points at one. An
    empty or `"unknown"` date falls back to today's date (when it's being
    logged is a fact the clock knows, not one to invent); a date the creator
    gives for the material itself still wins.
    """
    path = path or SOURCES_PATH
    old = path.read_text(encoding="utf-8")
    # The corpus is append-only, so a duplicate is permanent and doubles the
    # weight of whatever it says. A model that has just read an entry will
    # cheerfully log it back — three identical copies of one answer is a real
    # run, not a hypothetical.
    normalised = " ".join(answer.split()).strip().lower()
    for existing in _entries(old):
        for line in existing.splitlines():
            body = line.strip().lstrip("-").strip()
            if body.lower().startswith("**a:**"):
                if " ".join(body[6:].split()).strip().strip('"').lower() == normalised.strip('"'):
                    raise ValueError(
                        f"that answer is already logged as {entry_id_of(existing)} — "
                        "the corpus is append-only, so nothing needs re-logging. "
                        "Use the existing entry's id."
                    )
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


def line_key(line: str) -> str:
    """What a line is *about* — its field name, normalised.

    `| Age / birthdate | ... |` and `- **Age / birthdate:** ...` both key on
    "age / birthdate". A section holds one line per field, so this is what
    tells an addition from an edit of something already there.
    """
    stripped = line.strip()
    if stripped.startswith("|"):
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        return cells[0].lower() if cells else ""
    stripped = stripped.lstrip("-*").strip()
    if stripped.startswith("**"):
        label = stripped[2:].split("**", 1)[0]
        return label.rstrip(":").strip().lower()
    return ""


def line_value(line: str) -> str:
    """What a line *says*, with the label, cites and markup taken off.

    `- **Race:** elf [S-075]` and `- **Self-identification:** elf [S-075]` say
    the same thing under different labels. The field key cannot tell them
    apart; this can.
    """
    stripped = line.strip().lstrip("-*").strip()
    if stripped.startswith("|"):
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        stripped = cells[1] if len(cells) > 1 else ""
    elif stripped.startswith("**"):
        stripped = stripped.split("**", 2)[-1].lstrip(":").strip()
    without_cites = re.sub(r"[\[`]S-\d+[^\]`]*[\]`]", "", stripped)
    return re.sub(r"[^a-z0-9 ]", "", without_cites.lower()).strip()


def _dedupe_cites(line: str) -> str:
    """Collapse a cite repeated inside one line.

    Told to keep the cites a line carries and add its own, a model told to add
    `S-075` to a line already citing `S-075` writes it twice.
    """
    seen: set[str] = set()

    def once(match: re.Match) -> str:
        token = match.group(0)
        key = re.sub(r"\W", "", token)
        if key in seen:
            return ""
        seen.add(key)
        return token

    collapsed = re.sub(r"[\[`]S-\d+[^\]`]*[\]`]", once, line)
    return re.sub(r"\s*,\s*,", ",", collapsed).replace(" ,", "").rstrip(", ").rstrip()


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
    # A section holds one line per field. Handed a section and told to add,
    # a model will re-emit rows that are already there with the new cite
    # attached — including the very row it was meant to change. Adding a
    # second "Age" row does not answer the age; it just makes the profile
    # contradict itself twice.
    body = _dedupe_cites(body)
    key = line_key(body)
    if key:
        clash = next((existing for existing in lines if line_key(existing) == key), None)
        if clash is not None:
            raise ValueError(
                f"{name!r} already has a line for {key!r}:\n\n{clash.strip()}\n\n"
                "Use replace_profile_line to change it, keeping the cites it "
                "already carries and adding yours."
            )

    # The same fact under a different label is still the same fact. Left to
    # itself a model will file one answer as Race, then Self-identification,
    # then Ethnicity, and each passes the field check because each label is
    # new.
    value = line_value(body)
    if value:
        echo = next((existing for existing in lines if line_value(existing) == value), None)
        if echo is not None:
            raise ValueError(
                f"{name!r} already says this, under a different label:\n\n"
                f"{echo.strip()}\n\nOne fact, one line. Edit that line if it "
                "needs the new cite, or move on to the next section."
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
    body = _dedupe_cites(body)
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


def entry_id_of(entry: str) -> str:
    """The `S-###` an entry block declares, or "" if it has none."""
    found = ENTRY.search(entry)
    return found.group(1) if found else ""


def entry_feeds(entry: str) -> list[str]:
    """The sections an entry's `Feeds:` line names.

    The entry says where it belongs, so the follow-up work is fully specified
    by the entry alone — no chat history, no diff against a snapshot.
    """
    for line in entry.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped.lower().startswith("**feeds:**"):
            listed = stripped.split("**", 2)[-1].strip()
            return [part.strip() for part in listed.split(",") if part.strip() and part.strip() != "—"]
    return []


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
                            "'Where they're from'."
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

# The profile half of the procedure: two tools, both of which write a line.
#
# Everything else is absent for the same reason. `append_source` is gone
# because the entry is already logged and the system prompt opens by saying to
# log one. `read_profile_section` and `search_sources` are gone because the
# task already carries the entry and the sections it feeds — offered the tool,
# the model re-reads what it was just handed until it runs out of turns, and
# the instruction it is following there ("read the section first") is one we
# wrote. A prompt cannot outrank a prompt; a missing tool can.
FOLLOWUP_TOOL_NAMES = {"add_profile_line", "replace_profile_line"}
FOLLOWUP_SCHEMAS: list[dict] = [
    schema
    for schema in TOOL_SCHEMAS
    if schema["function"]["name"] in FOLLOWUP_TOOL_NAMES
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


class SearchSourcesArgs(BaseModel):
    query: str


class ReadProfileSectionArgs(BaseModel):
    heading: str


class AppendSourceArgs(BaseModel):
    answer: str
    question: str
    entry_type: str
    tags: list[str]
    date: str
    feeds: list[str]


class AddProfileLineArgs(BaseModel):
    heading: str
    line: str


class ReplaceProfileLineArgs(BaseModel):
    heading: str
    find: str
    line: str


# One model per TOOL_SCHEMAS entry, same field names and required-ness — the
# schema tells the model what's legal, this actually checks it. Without this,
# a wrong type on a present field (e.g. `tags` sent as a string instead of a
# list) reached the handler as-is: `", ".join(t for t in tags)` on a string
# silently iterates its characters instead of failing loudly.
TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "search_sources": SearchSourcesArgs,
    "read_profile_section": ReadProfileSectionArgs,
    "append_source": AppendSourceArgs,
    "add_profile_line": AddProfileLineArgs,
    "replace_profile_line": ReplaceProfileLineArgs,
}


def run_tool(name: str, arguments: dict) -> str | Proposal:
    """Dispatch by name.

    Arguments are filtered to the tool's declared schema before the handler
    ever sees them: `path` is intentionally undeclared everywhere, so a model
    that emits `{"path": "C:\\Windows\\win.ini"}` gets it silently dropped
    rather than routed to `Path.read_text`. What's left is then validated
    against that tool's pydantic model — a required field missing or the
    wrong type (a string where the schema says array, say) is refused here
    with a message the model can read and correct, rather than reaching the
    handler and either TypeError-ing on the more obvious shapes or silently
    misbehaving on the subtler ones. Unknown names, bad arguments, and any
    handler exception all come back as text — a handler must never kill the
    loop.
    """
    handler = READ_TOOLS.get(name) or WRITE_TOOLS.get(name)
    if handler is None:
        return f"no such tool {name!r}. Available: {', '.join([*READ_TOOLS, *WRITE_TOOLS])}"
    allowed = TOOL_PROPERTIES.get(name, set())
    dropped = sorted(k for k in arguments if k not in allowed)
    filtered = {k: v for k, v in arguments.items() if k in allowed}
    model = TOOL_ARG_MODELS.get(name)
    if model is not None:
        try:
            filtered = model.model_validate(filtered).model_dump()
        except ValidationError as exc:
            return f"bad arguments for {name}: {exc}"
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
    if isinstance(result, str) and len(result) > MAX_RESULT_CHARS:
        cut = len(result) - MAX_RESULT_CHARS
        result = (
            result[:MAX_RESULT_CHARS]
            + f"\n\n[truncated — {cut} more characters. Search for the specific "
            "line instead of reading the whole section.]"
        )
    return result


