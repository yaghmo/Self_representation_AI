# qwentts.cpp API — findings (live-verified)

**Status: LIVE-VERIFIED**, 2026-08-30, against `ghcr.io/serveurpersocom/qwentts.cpp:cuda12`
run via Docker (Docker Desktop + `--gpus all`, RTX 4070 Laptop GPU), for
both the base (cloning) and voicedesign talkers, using the real GGUF files
already downloaded into `models/qwen3-tts-gguf-{base,voicedesign}/`.

## /v1/audio/speech request field for the text to speak

**`input`** — confirmed. `docs/ARCHITECTURE.md`'s claim of `"text"` was
wrong; a `{"text": ...}` payload returns `400 {"error": {"message": "'input'
must be a non-empty string", ...}}`. `runtime/voice.py`'s `_synth_via_server()`
now sends `"input"`.

## Voice cloning registration

**Confirmed working end-to-end.** `POST /v1/audio/voices` with
`{"name", "ref_text", "wav_b64"}` (base64 of the raw reference WAV) returns
`{"name": "...", "status": "registered"}`. A subsequent
`POST /v1/audio/speech` with `{"input": ..., "voice": "<name>", ...}`
returns real, audible WAV. Verified with `data/voice/sample.wav` as the
reference clip.

As designed: registration lives in that `tts-server` process's memory
only — lost on restart — so `runtime/voice.py`'s `warm_bubbles()` calls
`_register_clone()` on every fresh `TTSServer.start()`, not once.

## VoiceDesign over HTTP

**Confirmed working.** `POST /v1/audio/speech` with `{"input": ...,
"instructions": "<description>", ...}` against the voicedesign talker
returns real WAV audio. The server actively validates this: the identical
request *without* `"instructions"` returns `400 {"error": {"message":
"voice_design models require --instruct", "type": "server_error"}}` —
strong confirmation this is the real, required field, not a silently
ignored one. `runtime/voice.py` already used `"instructions"`; no change
needed there.

## What this means for testing

The unit test suite still mocks `_register_clone`/`_synth_via_server`
directly (proving the lock/batching/caching logic), but the actual HTTP
payload shapes those two functions send are now confirmed correct against
a real server, not just documentation.

## Residual gaps

- `TTSServer.command()` spawns a local `tts-server` binary from
  `vendor/qwentts.cpp/build/`, which still doesn't exist on this machine —
  verification here used the Docker image directly (`docker run ... -p
  8091:8080 ...`), not `TTSServer.start()`'s own subprocess path. Building
  the actual binary (or switching `TTSServer` to run the Docker image
  instead of a bare subprocess) is still open.
- Not tested: behavior when `wav_b64` is large enough to matter for request
  size, or repeated re-registration across many `start()`/`stop()` cycles
  in quick succession.
