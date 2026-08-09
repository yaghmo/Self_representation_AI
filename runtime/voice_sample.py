"""Reference-audio capture for TTS voice cloning.

Zero-shot cloning models (XTTS-v2, F5-TTS, Qwen3-TTS-CustomVoice) clone
timbre from one reference clip and can synthesize in any language the model
supports from it — the reference's own language doesn't have to match the
output language. So there is exactly one file, not one per language. The
language picker in the UI only decides which phrase is shown to read aloud,
never which file gets written.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .bible import PROFILE_PATH
from .tools import snapshot

VOICE_DIR = PROFILE_PATH.parent / "voice"
SAMPLE_PATH = VOICE_DIR / "sample.wav"

LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("fr", "French"),
    ("de", "German"),
    ("ru", "Russian"),
    ("es", "Spanish"),
    ("pt", "Portuguese"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ar", "Arabic"),
]

# Static reference scripts, not character content — CLAUDE.md's cite/
# authorship rule doesn't apply here. Chosen for verifiable correctness
# (well-known public texts) over invented-per-language sentences: classic
# pangrams for the Latin/Cyrillic-script languages, and for the two
# languages without a Western-style pangram tradition, the text each
# language actually uses for phonetic-coverage purposes — Li Bai's 静夜思
# for Chinese, いろは (Iroha) for Japanese.
PHRASES: dict[str, str] = {
    "en": (
        "The quick brown fox jumps over the lazy dog. Pack my box with five "
        "dozen liquor jugs. How vexingly quick daft zebras jump!"
    ),
    "fr": (
        "Portez ce vieux whisky au juge blond qui fume. Voix ambiguë d'un "
        "cœur qui au zéphyr préfère les jattes de kiwis."
    ),
    "de": "Zwölf Boxkämpfer jagen Viktor quer über den großen Sylter Deich.",
    "ru": "Съешь же ещё этих мягких французских булок, да выпей чаю.",
    "es": (
        "El veloz murciélago hindú comía feliz cardillo y kiwi. La cigüeña "
        "tocaba el saxofón detrás del palenque de paja."
    ),
    "pt": "Um pequeno jabuti xereta viu dez cegonhas felizes.",
    "zh": "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
    "ja": (
        "いろはにほへと ちりぬるを わかよたれそ つねならむ "
        "うゐのおくやま けふこえて あさきゆめみし ゑひもせす（ん）"
    ),
    "ar": "نص حكيم له سر قاطع وذو شأن عظيم مكتوب على ثوب أخضر ومغلف بجلد أزرق",
}


def save_sample(data: bytes) -> Path:
    """Snapshot the existing clip (if any), then write `data` over it."""
    if not data.startswith(b"RIFF"):
        raise ValueError(f"not a WAV container — starts with {data[:4]!r}")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    if SAMPLE_PATH.exists():
        snapshot(SAMPLE_PATH)
    SAMPLE_PATH.write_bytes(data)
    return SAMPLE_PATH


def sample_status() -> str | None:
    """'recorded <UTC date>', or None if nothing has been captured yet."""
    if not SAMPLE_PATH.exists():
        return None
    stamp = datetime.fromtimestamp(SAMPLE_PATH.stat().st_mtime, tz=timezone.utc)
    return f"recorded {stamp:%Y-%m-%d}"


def _self_check() -> None:
    import tempfile

    global VOICE_DIR, SAMPLE_PATH
    original_dir, original_sample = VOICE_DIR, SAMPLE_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            VOICE_DIR = Path(tmp) / "voice"
            SAMPLE_PATH = VOICE_DIR / "sample.wav"

            assert sample_status() is None, "a fresh directory has no sample"

            first = save_sample(b"RIFF" + b"first-take")
            assert first == SAMPLE_PATH
            assert SAMPLE_PATH.read_bytes() == b"RIFF" + b"first-take"
            assert sample_status() is not None
            assert not (VOICE_DIR / ".backups").exists(), (
                "the first write has nothing to snapshot"
            )

            save_sample(b"RIFF" + b"second-take")
            assert SAMPLE_PATH.read_bytes() == b"RIFF" + b"second-take"
            backups = list((VOICE_DIR / ".backups").iterdir())
            assert len(backups) == 1, "the second write must snapshot the first take"
            assert backups[0].read_bytes() == b"RIFF" + b"first-take"

            assert set(PHRASES) == {code for code, _ in LANGUAGES}, (
                "every language in the picker needs a phrase, and vice versa"
            )
            assert all(text.strip() for text in PHRASES.values())

            try:
                save_sample(b"not-a-wav")
            except ValueError:
                pass
            else:
                raise AssertionError("save_sample accepted non-WAV bytes")
    finally:
        VOICE_DIR, SAMPLE_PATH = original_dir, original_sample

    print("voice_sample: all checks passed")


if __name__ == "__main__":
    _self_check()
