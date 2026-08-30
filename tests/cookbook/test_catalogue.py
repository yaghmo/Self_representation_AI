from cookbook.schema import load_catalogue


def test_tts_entries_are_gguf_transient_gpu():
    catalogue = load_catalogue()

    removed = {"xtts-v2", "f5-tts-base", "chatterbox", "kokoro-82m"}
    present_ids = {m.id for m in catalogue.models}
    assert not (removed & present_ids), removed & present_ids

    base = catalogue.model("qwen3-tts-gguf-base")
    assert base.devices == ("transient-gpu",)
    assert base.cloning is True

    design = catalogue.model("qwen3-tts-gguf-voicedesign")
    assert design.devices == ("transient-gpu",)
    assert design.cloning is False
