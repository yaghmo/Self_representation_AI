# qwentts.cpp API — findings (unverified against a live build)

**Status: NOT live-verified.** This machine has no CUDA/MSVC toolchain to
build `qwentts.cpp` from source, no usable WSL distro, and Docker Desktop's
daemon isn't running — so Task 1's planned build+curl verification
(`docs/superpowers/plans/2026-08-30-tts-on-demand-implementation.md`, Task 1)
could not run. By explicit decision, the implementation proceeds on
documentation alone; the values below are best-available, not confirmed.

Sourced from `ServeurpersoCom/qwentts.cpp`'s own `docs/ARCHITECTURE.md`.

## /v1/audio/speech request field for the text to speak

Hypothesis: **`text`** (this is what `docs/ARCHITECTURE.md` states explicitly).
A separate, less authoritative README excerpt used `input` instead —
possibly conflating this server with the real OpenAI TTS API's field name.
**Not confirmed.**

## Voice cloning registration

Confirmed with reasonable confidence (consistent across multiple doc
excerpts): `POST /v1/audio/voices` with `{"name", "ref_text", "wav_b64"}`
triggers server-side embedding extraction from the raw reference clip.
Registration lives in that `tts-server` process's memory only — lost on
every restart, which is why `runtime/voice.py`'s `warm_bubbles()` calls
`_register_clone()` on every fresh `TTSServer.start()`, not once.

## VoiceDesign over HTTP

**Not confirmed.** The CLI tool `qwen-tts` documents a `--instruct` flag,
but that's a separate offline binary, not `tts-server`. `tts-server`'s own
CLI flags (`--model`, `--codec`, `--alias`, `--host`, `--port`, `--lang`,
`--no-fa`, `--clamp-fp16`) have no instruct-related flag. Whether
`/v1/audio/speech` accepts an instruction string at all — and under what
field name — is undocumented in what was fetched during planning.

`runtime/voice.py`'s `_synth_via_server()` ships with `"instructions"` as
its best-available guess for the design-mode branch (matching the real
OpenAI TTS API's own field name, which this server otherwise imitates).
**This is unverified and may not work.**

## What this means for testing

Every test in this implementation mocks `_register_clone`/`_synth_via_server`
directly rather than hitting a real `tts-server` — so the test suite proves
the lock/batching/caching logic is correct, but proves nothing about whether
the actual HTTP payloads are accepted by a real `tts-server` process.

## Required before this ships to a real fan

Before voice actually works end-to-end:
1. Get a real build of `qwentts.cpp` (CUDA toolchain, a working WSL
   Ubuntu distro, or a running Docker Desktop with GPU passthrough).
2. Re-run the verification steps in Task 1 of
   `docs/superpowers/plans/2026-08-30-tts-on-demand-implementation.md`
   against the real binary.
3. Fix `runtime/voice.py`'s `"text"`/`"instructions"` field names in
   `_synth_via_server()` if the real server disagrees.
4. If VoiceDesign turns out not to work over HTTP at all, `_synth_via_server`'s
   `design` branch needs to raise a clear error instead of silently sending
   a payload the server ignores.
