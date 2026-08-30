# TTS: on-demand qwentts.cpp, load per turn, unload after

**Date:** 2026-08-30
**Status:** design, approved
**Touches:** `runtime/voice.py` (replaced), new `runtime/qwentts.py`,
`service/main.py` (`/chat` fan path, `/voice/speak`), `cookbook/fit.py`
(budget model), `cookbook/schema.py` (`Device` type), `cookbook/catalogue.json`.

## Why

Tonight's spike (see `tests/audio_samples/`) confirmed `qwentts.cpp`
(`ServeurpersoCom/qwentts.cpp`, a GGML port of Qwen3-TTS) produces audio
~9x faster than the current bf16 `qwen_tts`/`transformers` path, on the
same GPU, with no measurable quality loss and no loss of voice-cloning
capability. But it doesn't fit the VRAM budget as an always-resident
process: real measurements tonight put the LLM (qwen3-8b, 12288 ctx) at
~7.24 GB and `qwentts.cpp`'s own weight+KV accounting at ~3.2 GB, against
an 8.19 GB card — ~10.9 GB combined, even with the embedding role kept on
CPU (its GGUF form measured only 451 MB GPU, but the decision below keeps
it on CPU regardless, per the separate embedding conversation tonight).

So TTS moves to **on-demand**: load only while there's speech to
generate for the turn in progress, unload immediately after.

## Engine: spawn `tts-server` per turn

`qwentts.cpp` ships three tools; `tts-server` is the one this spec uses
— an OpenAI-compatible HTTP server (`POST /v1/audio/speech`), matching
this repo's existing pattern for the LLM (`runtime/llamacpp.py`'s
`LlamaServer`: spawn a `llama.cpp`-family binary, poll `/health`, talk
HTTP, terminate on `.stop()`) rather than the in-process C-ABI route
(`ctypes` bindings to `qt_init`/`qt_synthesize` — real new integration
work with no precedent in this repo, correctly rejected during
brainstorming in favor of reusing a proven shape).

`runtime/qwentts.py` gets a `TTSServer` dataclass, mirroring
`LlamaServer` field-for-field where it makes sense:

```python
@dataclass(eq=False)
class TTSServer:
    talker_path: Path       # qwen-talker-1.7b-{base,voicedesign}-Q8_0.gguf
    codec_path: Path        # qwen-tokenizer-12hz-Q8_0.gguf (shared, both modes)
    host: str = "127.0.0.1"
    port: int = 8091        # distinct from llama-server's 8080 and the
                             # embedding llama-server's own port
    process: subprocess.Popen | None = None

    def command(self) -> list[str]: ...   # tts-server --model <talker> --codec <codec> --port ...
    def already_running(self) -> bool: ... # GET /health, same shape as LlamaServer
    def start(self, wait_seconds: int = 60) -> "TTSServer": ...
    def stop(self) -> None: ...
    def __enter__(self) / __exit__(self): ...  # same context-manager convenience
```

Same `atexit`-registered `WeakSet` cleanup pattern as `LlamaServer` (a
crashed request must never leave a `tts-server` process holding VRAM
with nobody owning it). `wait_seconds=60` rather than `LlamaServer`'s 180
— `tts-server`'s model is far smaller (~2 GB vs the LLM's weights) and a
minute is already generous headway over tonight's measured ~5s cold
load.

Which talker GGUF to pass is decided the same way `voice.py` already
decides clone vs design today: `CLONE_PATH.exists()` → base talker,
`DESIGN_PATH.exists()` → voicedesign talker. That dispatch logic moves
into the new module unchanged in spirit.

## One global lock, one GPU slot

Single-tenant, one GPU, and `tts-server` and the LLM's own
`llama-server` are two separate resident-vs-transient VRAM consumers —
there's never a case where two `tts-server` instances should run at
once. A single process-wide lock (`threading.Lock`, since
`service/main.py`'s handlers are sync) serializes every path that needs
the TTS GPU slot:

- The per-turn background batch (below).
- `/voice/speak`'s cache-miss fallback (below).

Whichever caller acquires the lock owns starting `tts-server` (if not
already up from a caller currently ahead of it — reentrant only in the
sense that a second caller waiting on the lock will find the first
caller's synth already cached when its turn comes, not that two
callers ever touch `tts-server` concurrently) and stopping it once its
own batch of synths is done.

## Per-turn trigger, replacing today's simple pre-warm

Today (already built, unchanged in shape): after `/chat` returns a fan
reply, a `BackgroundTasks` job calls `voice.synth()` once per bubble.
This spec keeps that entry point and trigger — same gate (`not
request.tools`), same place in `chat()` — but the job body changes:

1. Split `response.content` into bubbles with the exact rule
   `ChatWidget.tsx`'s `splitIntoBubbles` already uses (`\n{2,}`) — server
   and client must agree on bubble boundaries, since the fan's play
   button is keyed by bubble text.
2. Acquire the TTS lock.
3. `TTSServer(...).start()` — talker path chosen by `voice_status()`.
4. For each bubble text: skip if already cache-hit (repeat line), else
   call `tts-server`'s `/v1/audio/speech` and write the response bytes
   to the same on-disk cache `runtime/voice.py` already maintains
   (`data/voice/cache/<hash>.wav`, same key derivation, same
   count-capped eviction from the `_evict_oldest` fix earlier tonight).
5. `.stop()`. Release the lock.

If `voice_status()` is `"none"`, the job no-ops immediately, exactly as
today.

## `/voice/speak` fallback

Unchanged endpoint contract. Internally: check cache first (unchanged).
On a miss — the fan clicked before the batch reached that bubble, or
after `tts-server` already shut down for that turn — acquire the same
lock, `TTSServer(...).start()` if not already running (a caller already
holding the lock mid-batch means this call simply queues on the lock
and finds a cache hit once it acquires it), synth just that one text,
and leave the *stop* decision to whichever caller's batch loop owns the
shutdown — a fallback-only invocation (batch already finished and
exited) starts and stops its own instance around the single call.

## Error handling

- `tts-server` fails to start (port conflict, transient GPU pressure
  from an LLM context spike): the background batch logs a warning and
  gives up — same silent-fail contract the existing pre-warm has today.
  Cache stays empty for that turn; the play button never lights up.
- `/voice/speak`'s fallback path is a direct client request, so a start
  failure there surfaces as a real error response, not a silent no-op.
- A `tts-server` crash mid-batch (dies after `start()` succeeded):
  caught the same way `LlamaServer.start()` already guards a subprocess
  that dies during its own health-poll loop — log, `.stop()` to clean
  up, stop the batch for that turn (remaining bubbles simply never get
  cached, same end state as a clean no-op).

## `cookbook/fit.py`: TTS becomes transient-gpu, not gpu-or-cpu

`cookbook/schema.py`'s `Device` gains a third value:
`Literal["gpu", "cpu", "transient-gpu"]`. Only the `tts` role can ever
be `transient-gpu` — `llm` and `embedding` stay resident, always `gpu`
or `cpu`.

In `cookbook/fit.py`'s `evaluate()`: a `transient-gpu` TTS placement is
excluded entirely from the steady-state `vram_used` sum the LLM and
embedding compete over — it doesn't hold VRAM at rest, so it shouldn't
shrink the budget those roles get fitted against. It's also excluded
from the existing `CPU_PENALTY_BASE`/`CPU_PENALTY_PER_GB` scoring
(`ROLE_WEIGHT["tts"]` stays as a quality-scoring input, but the
CPU-slowness penalty doesn't apply — it isn't running on CPU). The
`Fit` result still reports the TTS role's own weight size
(`per_model["tts"]`) for visibility in the UI, just not folded into
`vram_over`/`ram_over`.

`api_fit_auto`/`api_fit_manual` (`cookbook/api.py`) need no change —
they already pass whatever `Selection.placements` the caller (or
auto-search) chooses through to `evaluate()`; `transient-gpu` is just a
new valid value for the `tts` role's device there.

## `cookbook/catalogue.json`

- Remove: `xtts-v2`, `f5-tts-base`, `chatterbox`, `kokoro-82m` — none of
  them run on `qwentts.cpp`, and once TTS serving moves entirely to it,
  there is no runtime path left that could serve these.
- Replace `qwen3-tts-12hz-1.7b-base` / `-voicedesign` (currently `bf16`,
  loaded via `transformers`) with GGUF Q8_0 entries pointing at
  `qwen-talker-1.7b-{base,voicedesign}-Q8_0.gguf` (already downloaded
  tonight into `models/qwen3-tts-gguf-{base,voicedesign}/`), `device:
  "transient-gpu"`, `estimated_bytes` set from tonight's real
  measurement (~3.2 GB) rather than the file size, since that's what
  the fitter should show even though it no longer subtracts it from the
  steady budget.
- `embedding` entries unchanged (stays CPU/`transformers`, per tonight's
  separate decision — the bge-m3 GGUF path works and was benchmarked,
  but isn't being adopted here).

## Testing

- `runtime/qwentts.py`'s `TTSServer`: same test shape
  `tests/runtime/test_llamacpp.py` already uses for `LlamaServer`
  (subprocess mocked, `start()`/`stop()`/`already_running()` covered) —
  mirror that file's approach rather than inventing a new one.
- The lock: a focused test that fires two concurrent callers (threads)
  needing the TTS slot and asserts exactly one `TTSServer.start()` call
  happens, the second observing a cache hit instead of a second spawn.
- `cookbook/fit.py`: a case asserting a `transient-gpu` TTS placement is
  absent from `vram_used`/`vram_over`, alongside the existing
  gpu/cpu-placement cases already in `tests/cookbook/test_fit.py`.

## Explicitly out of scope

- Idle-timeout keep-warm (rejected during brainstorming — the batch
  already knows every bubble for a turn up front, so there's nothing an
  idle timer would buy beyond what the per-turn batch already does,
  at the cost of real added complexity: a watchdog timer and the
  shutdown-race-with-a-new-turn case).
- `/yuumii`'s mirror of `ChatWidget.tsx` needs zero changes — this
  entire spec is backend-only, the fan's `warm()`/`SpeakButton` flow is
  untouched.
- Multi-tenant TTS concurrency (more than one `tts-server` at a time) —
  this repo is single-tenant today; the single global lock is the
  correct choice for that, not a placeholder for future sharding.
