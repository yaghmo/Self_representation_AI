"""Documents to markdown, so `/story` can take a file as well as a paste.

Documents only, never media. markitdown handles the office and PDF formats;
markdown and plain text are passed through rather than round-tripped, because
a converter would reflow line breaks that are part of the creator's phrasing.
"""

from __future__ import annotations

from pathlib import Path

PASSTHROUGH = {".md", ".markdown", ".txt"}

# markitdown sniffs content, not the extension, and silently falls back to
# plaintext when bytes don't parse — a .docx holding junk would come back as
# that junk and `/story` would ingest it as the creator's own words. So the
# first bytes have to match the claimed format before markitdown gets a shot.
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
            # A latin-1/cp1252 note is ordinary to receive — refuse by name
            # rather than crash, and say what to do. Guessing a codec here
            # would silently corrupt the creator's phrasing.
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
