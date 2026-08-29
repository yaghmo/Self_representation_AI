# TTS auto-synth on reply, play button pops when ready

**Date:** 2026-08-29
**Status:** design, approved
**Touches:** `service/main.py` (`/chat` fan path, new `/voice/ready`
endpoint); `runtime/voice.py` (cache eviction); fan `ChatWidget` and its
`/yuumii` mirror.

## Why

The 2026-08-22 TTS spec deliberately shipped v1 as click-to-generate: a fan
clicks play, the clip synthesizes on demand, nothing pre-warms. That's a
multi-second silent wait on every first play. This spec closes that gap:
synthesis starts the moment the bot's text reply is ready, so by the time a
fan notices the play button it's often already warm.

This is *not* new infrastructure. `runtime/voice.py`'s `synth()` already
writes a content-addressed cache at `data/voice/cache/<sha256(status |
checkpoint_mtime | language | text)>.wav` — a repeat of the same line is
already a cache hit. This spec's whole job is: call that function earlier
(right after the reply text exists, not on click), and give the frontend a
cheap way to ask "is it warm yet" without pulling the audio bytes just to
check.

## Trigger: FastAPI `BackgroundTasks` in `/chat`

`/chat` is fan-facing (agent mode's own chat testing is explicitly
out of scope — see below). After the reply's `content` is produced and
before the response returns, schedule a `BackgroundTasks` task:

```python
background_tasks.add_task(_prewarm_voice, response.content, language)
```

`_prewarm_voice` calls `voice.voice_status()` first — if `"none"`, no-op,
matches today's "no voice configured" behavior exactly. Otherwise it drains
`voice.synth(text, language)` (a generator; drain with a `for _ in ...:
pass` or `deque(..., maxlen=0)`) so the cache file gets written, and
discards the bytes — nothing about `/chat`'s response shape changes, this
is fire-and-forget.

`language` comes from the same source `/voice/speak` already uses (whatever
`VoiceSpeakRequest` — or its fan-chat equivalent — passes today); no new
language-detection logic here.

Failure handling: wrap the drain in try/except, log at `warning` on any
exception (model load failure, OOM, whatever), and otherwise do nothing —
`/voice/ready` simply stays false forever for that line, and the fan's play
button never enables. No error surfaces to the client; there is no existing
mechanism on this path to carry one, and the fallback (button never lights
up) is silently correct even if unpolished. `/chat`'s own success/failure
is entirely unaffected — the background task runs after the response is
already being returned.

`/chat/stream` is unchanged. Streaming replies build their text
incrementally client-side; wiring pre-warm there is future work, not this
pass.

## Ready-check: `POST /voice/ready`

```python
class VoiceReadyRequest(BaseModel):
    text: str
    language: str = "Auto"

@app.post("/voice/ready")
def voice_ready(request: VoiceReadyRequest) -> dict:
    if voice_status() == "none":
        return {"ready": False}
    return {"ready": voice_cache_path(request.text, request.language).exists()}
```

`voice_cache_path` is `runtime/voice.py`'s existing `_cache_path` helper,
exported (drop the leading underscore, or add a thin public wrapper) so
`service/main.py` can reuse the exact same key derivation instead of
re-implementing it — the hash must be byte-for-byte identical to what
`synth()` computes or the check is meaningless.

This endpoint never touches the model, never blocks on GPU/CPU inference —
it's a stat() call. Safe to poll frequently.

## Cache eviction

`runtime/voice.py` already carries:

```python
# ponytail: no eviction/size cap — fine for the current single-tenant
# scale, revisit if this ever needs a real cache-size budget.
CACHE_DIR = VOICE_DIR / "cache"
```

Auto-synth on every fan reply makes that budget real — traffic no longer
depends on a fan choosing to click play, so cache growth is now driven by
conversation volume, not deliberate action. `synth()` gains one call after
`cache_path.write_bytes(audio)`:

```python
_evict_oldest(CACHE_DIR, keep=300)
```

`_evict_oldest` lists `*.wav` in `CACHE_DIR`, and if count > `keep`, deletes
the oldest by `st_mtime` until back at the cap. Runs inline in `synth()`,
not a separate timer/cron — this repo has no scheduled-job infra today and
this doesn't need to be the first thing that adds one. `keep=300` is a
constant, not a config knob — this is a cheap-to-change number if it turns
out wrong, not a decision worth exposing before there's a reason to.

## Frontend: fan `ChatWidget` + `/yuumii` mirror

After a bot reply renders:

1. If `voice_status()` is `"none"` (surfaced via whatever field the fan
   chat response/health check already exposes today, or a fresh cheap
   check — implementation detail, not fixed here), the play button stays
   hidden, exactly as today. No polling starts.
2. Otherwise, poll `POST /voice/ready` with that reply's exact text every
   ~2s. Play button renders disabled/loading until `ready: true`, then
   enables.
3. Clicking play still calls the existing `/voice/speak` (unchanged) — by
   now it's virtually always a cache hit, so playback starts immediately
   instead of after a multi-second synth.
4. Polling stops once `ready` is true, or after a sane upper bound (e.g.
   30s / 15 polls) to avoid polling forever if the background synth
   silently failed — at that point the button simply stays disabled,
   same end state as "never configured."

Per this repo's standing rule, this exact behavior (poll-then-enable,
same endpoints) gets mirrored into `/yuumii`'s isolated copy of the chat
widget — not shared code, a parallel edit.

## Explicitly out of scope

- Admin's own chat testing view — no play button, no pre-warm. Voice
  QA on the admin side stays the existing dedicated
  build-clone/build-design "listen to a test phrase" flow from the
  2026-08-22 spec, unrelated to per-message chat replies.
- `/chat/stream` pre-warm.
- Time-based (TTL) cache expiry — count-based eviction only.
- Any change to `/voice/speak` itself, or to how `synth()` picks
  clone vs design.
- A configurable eviction cap — `keep=300` is a constant.

## Testing

Per this repo's standing rule (pytest from the start, no `__main__`
self-checks): `tests/service/test_voice_ready.py` covers `/voice/ready`
against a stubbed cache dir (hit and miss), and `tests/runtime/test_voice.py`
gains a case for `_evict_oldest` (write N+few files with staggered mtimes,
assert the oldest are gone and count settles at the cap). The background
`_prewarm_voice` trigger itself is covered by asserting `BackgroundTasks.add_task`
was called with the right args on a successful `/chat` fan response — not by
running real GPU/CPU inference in a test.
