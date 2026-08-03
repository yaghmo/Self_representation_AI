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


def _self_check() -> None:
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)

        # Markdown and plain text pass through untouched. Running them through
        # a converter would reflow the creator's own line breaks, and phrasing
        # is the voice data this whole project exists to keep.
        source = directory / "note.md"
        source.write_text("# a day\n\nIt rained.\n", encoding="utf-8")
        assert to_markdown(source) == "# a day\n\nIt rained.\n"

        # A failed conversion stops. A partial document silently ingested is
        # a corpus with a hole in it that nothing will ever report.
        #
        # Two distinct failures, and only one of them is markitdown's to
        # report. Bytes that aren't the claimed format at all are the
        # dangerous case: markitdown sniffs them as plain text and hands back
        # the junk as a successful conversion, so MAGIC has to catch this one
        # before markitdown ever sees the file.
        broken = directory / "broken.docx"
        broken.write_bytes(b"not really a docx")
        try:
            to_markdown(broken)
        except ConversionFailed:
            pass
        else:
            raise AssertionError("a broken file was converted anyway")

        # A truncated document does get past MAGIC — the header is intact,
        # only the body is missing — and markitdown raises on it. Both halves
        # of the guard are load-bearing; neither covers the other's case.
        truncated = directory / "truncated.docx"
        with zipfile.ZipFile(directory / "whole.docx", "w") as archive:
            archive.writestr("word/document.xml", "<xml/>")
        truncated.write_bytes((directory / "whole.docx").read_bytes()[:40])
        try:
            to_markdown(truncated)
        except ConversionFailed:
            pass
        else:
            raise AssertionError("a truncated file was converted anyway")

        missing = directory / "nope.pdf"
        try:
            to_markdown(missing)
        except ConversionFailed:
            pass
        else:
            raise AssertionError("a missing file was converted anyway")

    print("convert: ok")


if __name__ == "__main__":
    _self_check()
