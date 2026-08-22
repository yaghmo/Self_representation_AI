import zipfile

from runtime.convert import ConversionFailed, to_markdown


def test_convert_self_check(tmp_path):
    directory = tmp_path

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

    # Text that isn't UTF-8 is refused by name, not by traceback — the
    # passthrough branch never sees markitdown, so nothing else catches it.
    latin = directory / "note.txt"
    latin.write_bytes("caf\xe9 in the morning".encode("latin-1"))
    try:
        to_markdown(latin)
    except ConversionFailed as exc:
        assert "UTF-8" in str(exc), str(exc)
    else:
        raise AssertionError("non-UTF-8 text was read anyway")

    missing = directory / "nope.pdf"
    try:
        to_markdown(missing)
    except ConversionFailed:
        pass
    else:
        raise AssertionError("a missing file was converted anyway")
