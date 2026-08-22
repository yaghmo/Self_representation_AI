# TTS voice — clone or design, cached, served to admin and fan

**Date:** 2026-08-22
**Status:** design, approved
**Touches:** new `runtime/voice.py`; `cookbook/catalogue.json` (already edited —
`qwen3-tts-12hz-1.7b-base`, `qwen3-tts-12hz-1.7b-voicedesign`); `service/main.py`
(new admin + fan endpoints); `runtime/voice_sample.py` (unchanged, reused as-is);
cookbook-web admin UI and `ChatWidget`/`PostGrid`-adjacent fan UI (later phase).

## Why

`runtime/voice_sample.py` already captures one reference clip
(`data/voice/sample.wav`). Nothing downstream of it exists — no TTS
inference wrapper, no endpoint, no stored "voice object." Every session
would otherwise re-run the reference-audio encode from scratch, and the
no-sample fallback (character.md description → a voice) had no path at
all. This spec builds that missing layer.

## Models (catalogue, already applied)

Two Qwen3-TTS-12Hz-1.7B checkpoints, both downloaded to `models/`:

- **`qwen3-tts-12hz-1.7b-base`** — `cloning: true`. `generate_voice_clone(text,
  language, ref_audio, ref_text)` clones timbre from a 3-second reference
  clip. No `instruct` param — cannot take an emotion/tone directive.
- **`qwen3-tts-12hz-1.7b-voicedesign`** — `cloning: false`. No reference
  audio, no preset speakers. `generate_voice_design(text, language,
  instruct)` builds a voice purely from a natural-language description.

A third variant, `CustomVoice` (9 fixed presets + emotion instruct, no
cloning, no free design), was evaluated and rejected — it fits neither the
clone path (no ref-audio input at all) nor the no-sample fallback (can't
build a voice from a description, only pick from its 9 presets). Not in
the catalogue.

Both checkpoints are large (1.7B, bf16) and mutually exclusive at runtime
— see "One model loaded at a time" below. A GGUF quantized swap
(`ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF`, Q8_0/Q4_K_M via `llama-tts`) was
raised as a possible latency/memory win but is explicitly **out of scope
here** — it needs a real bf16 baseline to A/B against first, and
`llama-server`'s HTTP API has no confirmed TTS endpoint (only the one-shot
`llama-tts` CLI does), which is a different serving story than the rest of
this repo's "model comes up as a server at boot" LLM path. Revisit once
`runtime/voice.py` exists and there's something to benchmark against.

## Storage — the two cacheable objects

Both live under `data/voice/` (already git-ignored, same bucket as
`sample.wav` — this is biometric/identifying data under this repo's
privacy rule, never tracked).

- **`data/voice/clone.pt`** — `torch.save()` of whatever
  `create_voice_clone_prompt(ref_audio, ref_text)` returns on the Base
  model. Built once per (re-)upload of `sample.wav`, reused on every
  subsequent `synth()` call without re-encoding the reference clip.
- **`data/voice/design.json`** — `{"instruct": str, "seed": int,
  "language": str}`. `instruct` is LLM-generated (see below), not
  character.md dumped raw. `seed` exists because `generate_voice_design`
  has **no documented seed parameter and no reusable prompt object** —
  reproducibility is done by pinning `torch.manual_seed(seed)` before every
  call and storing the seed that produced the approved test phrase. This is
  a workaround for an undocumented gap in the model's API, not confirmed
  model behavior, and gets verified empirically during implementation
  (same instruct + same seed, two calls, compare output) before being
  trusted.

At most one of the two files exists at a time — building one is expected
to remove or ignore the other (clone takes precedence if somehow both are
present, since it's the deliberate stronger signal: a real reference clip
beats a generated approximation).

## `runtime/voice.py` — one entrypoint, one model loaded at a time

Shaped like `runtime/model.py`'s `Model` class, but simpler — no
`llama-server` subprocess, since llama.cpp's TTS support has no confirmed
persistent HTTP mode. The Qwen3-TTS checkpoint loads in-process via
`transformers`, once, and stays warm — matches this repo's "nothing swaps
mid-session" rule.

```
synth(text: str, language: str = "Auto") -> Iterator[bytes]   # streamed PCM/wav chunks
build_clone(ref_audio: Path, ref_text: str) -> None            # writes clone.pt
build_design(instruct: str, seed: int, language: str) -> None  # writes design.json
voice_status() -> Literal["clone", "design", "none"]
```

**Which checkpoint loads is decided once, at first `synth()` call, by
`voice_status()`:**

- `"clone"` → load Base, dispatch `generate_voice_clone(text, language,
  voice_clone_prompt=<loaded clone.pt>)`.
- `"design"` → load VoiceDesign, `torch.manual_seed(seed)`, dispatch
  `generate_voice_design(text, language, instruct=<loaded instruct>)`.
- `"none"` → raise. Caller (both admin and fan endpoints) turns this into
  "no voice configured yet" rather than a 500.

**Streaming.** Qwen3-TTS's architecture documents native streaming
generation ("Dual-Track hybrid streaming... a single model supports both
streaming and non-streaming generation"), confirmed at the repo level but
without a documented call signature. `synth()` returns an iterator of
audio chunks; the exact method used to get chunked output from the
installed package (a `stream=True` kwarg, a separate `*_stream` method, or
manual chunking of codec tokens) is an implementation-time detail resolved
against the actual installed library, not fixed by this spec.

## Admin flow

Two entry points, both ending at the same "hear a test phrase, confirm"
gate before anything is treated as final — nothing here writes
`character.md` or `sources.md`, so it sits on the admin surface but
doesn't need the bible write-confirm gate; it needs its own listen-and-
confirm instead.

**With a sample** (`data/voice/sample.wav` already recorded via the
existing `voice_sample.py` flow):
1. Endpoint calls `build_clone(sample.wav, ref_text)` → writes `clone.pt`.
2. Synthesizes one test phrase **in the same language code the sample was
   recorded in** (`voice_sample.LANGUAGES`/`PHRASES` — reuse the language
   picked during recording, not `"Auto"`), so the confirm step actually
   exercises the clone in a language it has ground truth for.
3. Admin listens. Re-recording the sample (already supported, snapshots
   the old take) and re-running step 1 is the correction path — no
   separate "retry" mechanism needed.

**Without a sample:**
1. One prompted call to the already-configured chat LLM (the admin
   surface's existing agentic model, not a new dependency), fed a
   condensed read of `character.md`, asking for a short natural-language
   vocal description — tone, pitch, pace, energy — in the style of the
   model's own instruct examples ("warm, unhurried female voice, low
   pitch, dry humor in the delivery"), not a life-summary paragraph.
2. Pick a seed, call `build_design(instruct, seed, language)` → writes
   `design.json`. `language` defaults to `"Auto"` here — there's no
   recorded-language signal to reuse, unlike the clone path.
3. Synthesize a test phrase, admin listens, same confirm gate.

`ref_text` (the transcript `generate_voice_clone` wants alongside
`ref_audio`) is exactly the fixed phrase already shown to the admin during
recording (`voice_sample.PHRASES[language]`) — no new transcription step
needed, it's already known verbatim.

## Fan flow

A tiny play button under every chat bubble. On click, `POST` that
bubble's text to a new streaming endpoint; the fan surface plays audio as
chunks arrive rather than waiting for the full clip — matters more here
than in admin, since fan replies can run long and a multi-second silent
wait before the first sound defeats the point of a low-friction play
button. No pre-generation, no per-message audio cache in this pass — audio
regenerates on every click, accepted for v1 given "tiny play button"
scope.

The endpoint takes text in, streams audio out, touches neither
`character.md` nor `sources.md` — it reads `voice_status()` and the cached
object, nothing else. Fits the fan-surface no-writes rule without needing
to be a tool at all; it's a plain HTTP endpoint alongside `/chat`, not
something the model calls.

If `voice_status()` is `"none"`, the endpoint returns a clear "no voice
configured" response and the frontend hides or disables the play button —
exact UI treatment is a later, separate frontend pass (this spec covers
the backend contract only).

## Testing

Per this repo's standing rule: while the feature is still being built out,
`runtime/voice.py` keeps a `__main__` assert-based self-check, not pytest
— pytest conversion happens later, in a batch sweep, once this (and other
in-flight pieces) are done. The self-check covers `build_clone` /
`build_design` / `voice_status()` dispatch logic and the save/load
round-trip for both cache files, against a stubbed model backend — it does
not run real GPU inference. Real verification is the human "listen to the
test phrase" step already built into the admin flow above; that's the
actual correctness check for audio quality, and no automated check
replaces it.

## Explicitly out of scope here

- GGUF/`llama-tts` swap-in benchmark (needs this spec's baseline to exist
  first).
- Fan-side UX beyond "a play button exists" — placement, styling,
  per-message caching, whether it also mirrors into `/yuumii` — later,
  separate pass, but note for whenever that pass happens: this repo's
  standing rule is that functional additions to `/fan` get mirrored into
  `/yuumii` too.
- Multi-tenant / multiple stored voices — this repo is single-tenant
  today; one `clone.pt` or `design.json`, not one per user.
