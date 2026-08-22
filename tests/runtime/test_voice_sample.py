import runtime.voice_sample as voice_sample_module
from runtime.voice_sample import LANGUAGES, PHRASES, save_sample, sample_status


def test_voice_sample_self_check(tmp_path):
    original_dir, original_sample = voice_sample_module.VOICE_DIR, voice_sample_module.SAMPLE_PATH
    try:
        voice_sample_module.VOICE_DIR = tmp_path / "voice"
        voice_sample_module.SAMPLE_PATH = voice_sample_module.VOICE_DIR / "sample.wav"

        assert sample_status() is None, "a fresh directory has no sample"

        first = save_sample(b"RIFF" + b"first-take")
        assert first == voice_sample_module.SAMPLE_PATH
        assert voice_sample_module.SAMPLE_PATH.read_bytes() == b"RIFF" + b"first-take"
        assert sample_status() is not None
        assert not (voice_sample_module.VOICE_DIR / ".backups").exists(), (
            "the first write has nothing to snapshot"
        )

        save_sample(b"RIFF" + b"second-take")
        assert voice_sample_module.SAMPLE_PATH.read_bytes() == b"RIFF" + b"second-take"
        backups = list((voice_sample_module.VOICE_DIR / ".backups").iterdir())
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
        voice_sample_module.VOICE_DIR, voice_sample_module.SAMPLE_PATH = original_dir, original_sample
