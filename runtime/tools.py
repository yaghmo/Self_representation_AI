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

from .bible import PROFILE_PATH

SOURCES_PATH = PROFILE_PATH.parent / "sources.md"
ENTRY = re.compile(r"^### (S-\d+)", re.MULTILINE)
SEARCH_LIMIT = 5


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

    def apply(self) -> Path:
        backups = self.path.parent / ".backups"
        backups.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        if self.path.exists():
            shutil.copy2(self.path, backups / f"{self.path.name}.{stamp}")
        self.path.write_text(self.new_text, encoding="utf-8")
        return self.path


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
        path=path, new_text=new, summary=summary, diff=diff, before=before, after=after
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


def _find_section(text: str, heading: str) -> tuple[str, int, int]:
    wanted = heading.strip().lstrip("#").strip().lower()
    for name, start, end in _sections(text):
        if name.lower() == wanted or name.lower().startswith(wanted):
            return name, start, end
    known = ", ".join(name for name, _, _ in _sections(text))
    raise KeyError(f"no section {heading!r}. Sections are: {known}")


def read_profile_section(heading: str, path: Path | None = None) -> str:
    path = path or PROFILE_PATH
    text = path.read_text(encoding="utf-8")
    _, start, end = _find_section(text, heading)
    return text[start:end].rstrip() + "\n"


def next_source_id(text: str) -> str:
    numbers = [int(m.group(1).split("-")[1]) for m in ENTRY.finditer(text)]
    return f"S-{max(numbers) + 1:03d}" if numbers else "S-001"


def append_source(answer: str, feeds: list[str], path: Path | None = None) -> Proposal:
    """Append one entry. There is no tool that edits or deletes an existing one.

    The id comes from the file, never from the model: an id the model picks is
    an id it can collide, skip, or reuse, and every cite in the profile points
    at one.
    """
    path = path or SOURCES_PATH
    old = path.read_text(encoding="utf-8")
    entry_id = next_source_id(old)
    block = (
        f"\n### {entry_id}\n"
        f"**A:** {answer.strip()}\n"
        f"**Feeds:** {', '.join(feeds) if feeds else '—'}\n"
    )
    new = old.rstrip("\n") + "\n" + block
    return _propose(
        path, old, new, f"append {entry_id} to {path.name}", before="", after=block.strip()
    )


def replace_profile_section(heading: str, text: str, path: Path | None = None) -> Proposal:
    """Replace exactly one `## ` section. Nothing outside it can move."""
    path = path or PROFILE_PATH
    old = path.read_text(encoding="utf-8")
    name, start, end = _find_section(old, heading)
    body = text.strip()
    if not body.startswith("## "):
        body = f"## {name}\n{body}"
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
                "Propose appending a new entry to the sources file, verbatim. "
                "The entry id is assigned automatically. The creator must "
                "approve before anything is written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "feeds": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["answer", "feeds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_profile_section",
            "description": (
                "Propose replacing one profile section with new text. Read the "
                "section first. Every statement needs a cite. The creator must "
                "approve before anything is written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["heading", "text"],
            },
        },
    },
]

READ_TOOLS = {"search_sources": search_sources, "read_profile_section": read_profile_section}
WRITE_TOOLS = {"append_source": append_source, "replace_profile_section": replace_profile_section}


def run_tool(name: str, arguments: dict) -> str | Proposal:
    """Dispatch by name. Unknown names and bad arguments come back as text so
    the model can correct itself rather than the loop dying."""
    handler = READ_TOOLS.get(name) or WRITE_TOOLS.get(name)
    if handler is None:
        return f"no such tool {name!r}. Available: {', '.join([*READ_TOOLS, *WRITE_TOOLS])}"
    try:
        return handler(**arguments)
    except TypeError as exc:
        return f"bad arguments for {name}: {exc}"
    except KeyError as exc:
        return str(exc).strip('"')
    except OSError as exc:
        return f"{name} could not read the file: {exc}"


def _self_check() -> None:
    import tempfile
    from pathlib import Path

    corpus = (
        "# Sources\n\n"
        "### S-001\n**Q:** placeholder question one\n**A:** alpha answer\n\n"
        "### S-002\n**Q:** placeholder question two\n**A:** beta answer\n"
    )
    profile = (
        "# Placeholder\n## How this file works\nmeta\n"
        "# CHARACTER\n"
        "## 0. At a Glance\n- one\n\n"
        "## 6. Voice\n- old line\n\n"
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

        # Append allocates the next id itself.
        proposal = append_source("gamma answer", ["6. Voice"], path=sources)
        assert "S-003" in proposal.diff, proposal.diff
        assert proposal.before == "", "an appended entry has no before"
        assert "gamma answer" in proposal.after, proposal.after
        assert sources.read_text(encoding="utf-8") == corpus, "nothing writes before apply"

        proposal.apply()
        after = sources.read_text(encoding="utf-8")
        assert after.startswith(corpus), "existing entries must be byte-identical"
        assert "S-003" in after
        assert len(list((root / ".backups").iterdir())) == 1, "apply snapshots first"

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
        assert "## Changelog" in rewritten, "the changelog must survive"

        # An unknown section is refused rather than appended as a new one.
        try:
            replace_profile_section("99. Nope", "x", path=target)
        except KeyError:
            pass
        else:
            raise AssertionError("expected KeyError for an unknown section")

    print("tools self-check: ok")


if __name__ == "__main__":
    _self_check()
