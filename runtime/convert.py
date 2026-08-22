"""Documents to markdown, so `/story` can take a file as well as a paste.

Documents only, never media. markitdown handles the office and PDF formats;
markdown and plain text are passed through rather than round-tripped, because
a converter would reflow line breaks that are part of the creator's phrasing.
"""

from __future__ import annotations

from pathlib import Path

PASSTHROUGH = {".md", ".markdown", ".txt"}

# markitdown sniffs content rather than trusting the extension, and when a
# document's bytes don't parse it falls back to its plaintext converter without
# saying so: a .docx holding junk comes back as that junk, and `/story` would
# ingest it as the creator's own words. The extension claims a format, so the
# first bytes have to agree before markitdown is allowed to guess.
#
# ponytail: magic bytes for the formats a creator actually attaches. Anything
# outside this table still gets markitdown's sniffing — widen the table if a
# format starts arriving, don't reach for a mime-detection dependency.
MAGIC = {
    ".docx": b"PK\x03\x04",
    ".pptx": b"PK\x03\x04",
    ".xlsx": b"PK\x03\x04",
    ".odt": b"PK\x03\x04",
    ".epub": b"PK\x03\x04",
    ".pdf": b"%PDF",
}


class ConversionFailed(RuntimeError):
    """The file could not be converted. Never ingest a partial conversion."""


def to_markdown(path: Path) -> str:
    if not path.is_file():
        raise ConversionFailed(f"{path.name} does not exist")
    if path.suffix.lower() in PASSTHROUGH:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConversionFailed(f"{path.name} could not be read: {exc}") from exc
        except UnicodeDecodeError as exc:
            # A note saved as latin-1 or cp1252 is an ordinary thing to be
            # handed. Refuse it by name rather than crashing the page, and say
            # what to do — re-saving as UTF-8 keeps the creator's phrasing,
            # while guessing a codec here would silently corrupt it.
            raise ConversionFailed(
                f"{path.name} is not UTF-8 text ({exc.reason} at byte {exc.start}). "
                "Re-save it as UTF-8 and attach it again."
            ) from exc

    magic = MAGIC.get(path.suffix.lower())
    if magic:
        try:
            with path.open("rb") as handle:
                head = handle.read(len(magic))
        except OSError as exc:
            raise ConversionFailed(f"{path.name} could not be read: {exc}") from exc
        if head != magic:
            raise ConversionFailed(
                f"{path.name} is not really a {path.suffix.lower().lstrip('.')} file"
            )

    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise ConversionFailed(
            "markitdown is not installed — run `uv sync --extra runtime`"
        ) from exc

    try:
        result = MarkItDown().convert(str(path))
    except Exception as exc:  # markitdown raises per-format exceptions
        raise ConversionFailed(f"{path.name} could not be converted: {exc}") from exc

    text = getattr(result, "text_content", "") or ""
    if not text.strip():
        raise ConversionFailed(f"{path.name} converted to nothing — is it a document?")
    return text
