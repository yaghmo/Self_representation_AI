# TTS Voice Clone/Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `runtime/voice.py` (clone/design a voice once, cache it, synthesize from it) and wire it into `service/main.py` as admin build/confirm endpoints plus one fan-facing speak endpoint.

**Architecture:** One new module, `runtime/voice.py`, mirrors `runtime/model.py`'s shape but loads a `transformers`-family model in-process via the `qwen_tts` package (no `llama-server`, since llama.cpp has no confirmed TTS HTTP endpoint). Exactly one of two mutually-exclusive cached objects under `data/voice/` decides which of the two downloaded Qwen3-TTS-12Hz-1.7B checkpoints (Base=cloning, VoiceDesign=instruct-only) is ever loaded per process. `service/main.py` gets three new/extended admin routes and one public streaming route, following the file's existing patterns exactly (`_require_loaded`/`_require_agent` gate, `StreamingResponse`, the single big `_self_check()` using `TestClient`).

**Tech Stack:** `qwen-tts==0.1.1` (real, already verified installed and importable — `from qwen_tts import Qwen3TTSModel`), `soundfile==0.14.0`, `torch` (already a dependency), FastAPI (already the service framework).

**Spec:** `docs/superpowers/specs/2026-08-22-tts-voice-clone-design.md`

## Global Constraints

- Both checkpoints are already downloaded: `models/qwen3-tts-12hz-1.7b-base/`, `models/qwen3-tts-12hz-1.7b-voicedesign/`. Catalogue ids: `qwen3-tts-12hz-1.7b-base`, `qwen3-tts-12hz-1.7b-voicedesign`.
- `data/voice/` is git-ignored (biometric data) — never write test fixtures there directly; every test that touches these paths must swap the module's directory globals to a `tempfile.TemporaryDirectory()`, exactly like the existing `-- /admin/voice --` block in `service/main.py`'s `_self_check()` already does for `runtime.voice_sample`.
- Self-checks stay `if __name__ == "__main__"` assert blocks, not pytest, per this repo's standing rule while the feature is in flux — no new `test_*.py` files, no `conftest.py`.
- Confirmed real API (verified by inspecting the installed package, not docs):
  ```python
  # qwen_tts.inference.qwen3_tts_model.Qwen3TTSModel
  def create_voice_clone_prompt(self, ref_audio, ref_text=None, x_vector_only_mode=False) -> List[VoiceClonePromptItem]: ...
  def generate_voice_clone(self, text, language=None, ref_audio=None, ref_text=None, x_vector_only_mode=False, voice_clone_prompt=None, non_streaming_mode=False, **kwargs) -> Tuple[List[np.ndarray], int]: ...
  def generate_voice_design(self, text, instruct, language=None, non_streaming_mode=True, **kwargs) -> Tuple[List[np.ndarray], int]: ...

  @dataclass
  class VoiceClonePromptItem:
      ref_code: Optional[torch.Tensor]
      ref_spk_embedding: torch.Tensor
      x_vector_only_mode: bool
      icl_mode: bool
      ref_text: Optional[str] = None
  ```
  `VoiceClonePromptItem` is a plain `@dataclass` of tensors/primitives — stdlib `pickle` round-trips it fine, no need for `torch.save`.
- **`language` must be a full name** ("english", "chinese", ...), not an ISO code — confirmed the hard way during Task 3 (see Implementation Notes). `voice_sample.LANGUAGES` keys on ISO codes ("en"); map through `dict(LANGUAGES)[code]` to get the label Qwen3-TTS actually validates against.
- No real streaming generation exists in `qwen-tts==0.1.1` — confirmed by reading `qwen_tts/inference/qwen3_tts_model.py` directly: `non_streaming_mode`'s own docstring says it "currently only simulates streaming text input... rather than enabling true streaming input or streaming generation." Both generate methods are `@torch.no_grad()` and return the full waveform synchronously. The fan endpoint streams the *HTTP delivery* of the finished clip (chunked `StreamingResponse`), not the generation itself. Do not attempt to call a streaming generation API — it does not exist in this version.
- Importing `qwen_tts` prints harmless stderr noise on this machine (missing `SoX` binary, missing `flash-attn`) — expected, not a failure signal. Don't chase it.
- `runtime/bible.py` already exports `build_compact_persona()` — reuse it for the condensed character.md read; do not write a new condensation function.
- `service/main.py` already imports `from runtime.voice_sample import LANGUAGES, PHRASES, SAMPLE_PATH, sample_status, save_sample` and `from runtime.bible import ... build_compact_persona ...` — reuse both, do not re-import differently.
- **A `from X import Y` binding does not track later reassignment of `X.Y`.** Both `service.main`'s own imported names (`build_clone`, `build_design`, `voice_synth`, `SAMPLE_PATH`) and any self-check monkeypatching of them must go through this rule — see Implementation Notes below, this bit the first draft of Task 3's self-check twice.

---

### Task 1: Add TTS inference dependencies — DONE

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `qwen_tts` and `soundfile` importable in the project's own environment (Tasks 2+ depend on this).

- [x] **Step 1: Add the two dependencies to the `runtime` extra**
- [x] **Step 2: Sync the environment** (`uv sync --extra runtime`)
- [x] **Step 3: Verify the import works** — `uv run python -c "from qwen_tts import Qwen3TTSModel; ...; print('ok')"` → `ok`.
- [x] **Step 4: Commit** — `uv.lock` is git-ignored in this repo, only `pyproject.toml` staged.

---

### Task 2: `runtime/voice.py` — core module — DONE

**Files:**
- Create: `runtime/voice.py`

**Interfaces:**
- Consumes: `runtime.bible.PROFILE_PATH`, `runtime.tools.snapshot(path)`, `cookbook.schema.load_catalogue()` + `.model(id)`, `cookbook.download.target_dir(entry)`.
- Produces (used by Task 3):
  - `voice_status() -> Literal["clone", "design", "none"]`
  - `build_clone(ref_audio: Path, ref_text: str) -> None`
  - `build_design(instruct: str, seed: int, language: str = "Auto") -> None`
  - `synth(text: str, language: str = "Auto") -> Iterator[bytes]`
  - `class NoVoiceConfigured(RuntimeError)`
  - Module constants: `VOICE_DIR`, `CLONE_PATH`, `DESIGN_PATH`

- [x] **Step 1: Write the module with self-check, real functions stubbed to raise**
- [x] **Step 2: Run it, confirm it fails on the stubs** — `NotImplementedError` from `build_clone`, as expected.
- [x] **Step 3: Implement the real functions**
- [x] **Step 4: Run the self-check again, confirm it passes** — `voice: all checks passed`.
- [x] **Step 5: Commit**

Implemented exactly as originally planned — no deviations in this file.

---

### Task 3: Wire `service/main.py` — admin build/confirm + fan speak — DONE

**Files:**
- Modify: `service/main.py`

**Interfaces:**
- Consumes: `runtime.voice.voice_status`, `build_clone`, `build_design`, `synth`; `runtime.voice_sample.SAMPLE_PATH`/`LANGUAGES`/`PHRASES`/`sample_status` (already imported, plus a new `import runtime.voice_sample as voice_sample_module` for the live-path lookup — see notes); `runtime.bible.build_compact_persona`; `runtime.backend.Message`; `model.chat(...)`.
- Produces: `GET /admin/voice/status` (extended), `POST /admin/voice/clone`, `POST /admin/voice/design`, `POST /voice/speak`.

- [x] **Step 1: Add the self-check assertions first**
- [x] **Step 2: Run, confirm the new assertions fail** — failed on missing `synthStatus` key, as expected.
- [x] **Step 3: Add the imports and request models**
- [x] **Step 4: Extend `GET /admin/voice/status` and add the two admin build routes**
- [x] **Step 5: Add the fan-facing speak endpoint**
- [x] **Step 6: Run the self-check, confirm it now passes** — `service self-check: ok`, after three real bugs surfaced and got fixed (below).
- [x] **Step 7: Commit**

#### Implementation Notes — three real bugs the original plan text got wrong

The plan's original Step 1 self-check patched `voice_synth_module.build_clone = fake_build_clone` (etc.) and the original Step 4 handler read the bare imported `SAMPLE_PATH` directly. Both are wrong, for the same underlying reason, plus one unrelated sequencing bug:

1. **Monkeypatch target.** `service/main.py` imports with `from runtime.voice import build_clone, build_design, synth as voice_synth, voice_status`. That copies the function *objects* into `service.main`'s own namespace at import time — reassigning `runtime.voice.build_clone` afterward does not change what `service.main.admin_voice_clone()` calls, since it looks up the bare name `build_clone` in its own module globals. The self-check's fakes were silently never applied, and the first run of the self-check actually invoked the **real 1.7B model** (visible in the log: real weight loading, ~20s runtime, real `qwen_tts` internal log lines). Fix: `global build_clone, build_design, voice_synth` at the top of `_self_check()`, then reassign those bare names directly, restoring them in the matching `finally`.

2. **Same bug, `SAMPLE_PATH`.** `admin_voice_clone` originally checked `SAMPLE_PATH.exists()` using the bare name imported once at module load — which stayed pointed at the *real* `data/voice/sample.wav` (which genuinely exists in this environment) no matter what the self-check swapped `voice_sample.SAMPLE_PATH` to. Fix: dropped the bare `SAMPLE_PATH` import, added `import runtime.voice_sample as voice_sample_module`, and the handler now uses `sample_status()` (a function, which *does* correctly resolve `SAMPLE_PATH` dynamically against its own module's globals) for the existence check, and `voice_sample_module.SAMPLE_PATH` (live attribute access) for the actual path passed to `build_clone`.

3. **Real bug, not a test artifact.** Because of bug #1, the self-check's first run actually called the real `generate_voice_clone(language="en")` — and it failed for a genuine reason: Qwen3-TTS's `_validate_languages` only accepts full names (`'chinese', 'english', 'french', 'german', 'italian', 'japanese', 'korean', 'portuguese', 'russian', 'spanish', 'auto'`), not the ISO codes `voice_sample.LANGUAGES` keys on. `admin_voice_clone` now maps through `dict(LANGUAGES)[request.language]` to get the label before calling `voice_synth`. Note the model's supported-language list has no Arabic (which `voice_sample.LANGUAGES` includes) and does have Italian (which `voice_sample.LANGUAGES` doesn't) — a pre-existing mismatch between the two modules' language lists, not fixed here; picking Arabic during cloning will surface as a clear 502 with the model's own error text, which is accepted as correct-if-unpolished behavior rather than something this task needed to paper over.

4. **Unrelated sequencing bug in the self-check itself.** The pre-existing `-- /admin/voice --` block writes a real file at `Path(tmp)/"voice"/"sample.wav"` and only restores the module *attribute pointer* in its `finally` — it never deletes that file. The new "no sample recorded → 422" sub-test originally reused that same `Path(tmp) / "voice"` path, so by the time it ran, a file was already sitting there from the earlier sub-test, and the check was accidentally green (well, accidentally wrong — it hit the fake 200 path instead of the intended 422). Fixed by using a distinct `Path(tmp) / "voice-clone-test"` subdirectory for this sub-test.

None of these bugs affect Task 2 (`runtime/voice.py`), which needed no changes.

---

### Task 4: Live smoke test against the real downloaded weights

This is the one task automated checks cannot cover — Task 2/3's self-checks stub the model entirely. This task runs the real 1.7B checkpoints once each and hands the resulting audio to the user to listen to, per the spec's "no automated check replaces the listen step."

**Files:** none (verification only, no code changes).

- [x] **Step 1: Run the clone path against the real recorded sample** — ran clean, `clone_test.wav` (733,484 bytes).

`data/character.md` and `data/voice/sample.wav` both already exist in this environment (junctioned into the worktree from the main checkout). Run:

```bash
uv run python -c "
from pathlib import Path
from runtime.voice import build_clone, synth
from runtime.voice_sample import SAMPLE_PATH, PHRASES, LANGUAGES

build_clone(SAMPLE_PATH, PHRASES['en'])
audio = b''.join(synth(PHRASES['en'], language=dict(LANGUAGES)['en']))
Path('clone_test.wav').write_bytes(audio)
print('wrote clone_test.wav', len(audio), 'bytes')
"
```

Note the `language=dict(LANGUAGES)['en']` fix (full name "English", not "en") carried over from the Task 3 bugfix.

Expected: no exception, `clone_test.wav` written with a nonzero byte count. GPU/VRAM note: this loads one 1.7B bf16 model (~3.5GB) — if a separate `llama-server` LLM process is already resident, watch for CUDA OOM; if it happens, unload the LLM first (`POST /model/unload`) and retry.

- [x] **Step 2: Send the clip to the user for a real listen** — sent, awaiting confirmation.

Use `SendUserFile` on `clone_test.wav` with a caption asking the user to confirm it sounds like the recorded reference. This is the actual confirm gate — do not mark the clone path done until the user responds.

- [ ] **Step 3: Run the design path against the real character.md** — BLOCKED: `config/stack.json` does not exist anywhere in this checkout (not git-ignored-but-present, genuinely absent) — no LLM stack has ever been selected on this machine via the cookbook's probe/fit/confirm flow. `Model.from_config()` raises `FileNotFoundError` before `build_design` is even reached. This is an environment gap outside this plan's scope (CLAUDE.md: stack selection is a deliberate, user-confirmed cookbook step, never automatic) — not a bug in `runtime/voice.py` or `service/main.py`.

Requires the LLM loaded (`POST /model/load`, or `Model.from_config().load()` directly). Run:

```bash
uv run python -c "
from pathlib import Path
from runtime.model import Model
from runtime.bible import build_compact_persona
from runtime.backend import Message
from runtime.voice import build_design, synth

model = Model.from_config().load()
persona = build_compact_persona()
prompt = (
    \"Read this character profile and write ONE short sentence describing how \"
    \"this person's speaking voice would sound — tone, pitch, pace, energy. \"
    \"Write it as a vivid style description for a text-to-speech system, not a \"
    \"biography. Example style: 'Warm, unhurried female voice, low pitch, dry \"
    \"humor in the delivery.' Output only that one sentence, nothing else.\"
)
instruct = model.chat([Message('user', f'{prompt}\n\n{persona}')], temperature=0.4, max_tokens=100, thinking=False).strip()
print('instruct:', instruct)
build_design(instruct, seed=0, language='Auto')
audio = b''.join(synth('Hello, this is a preview of my voice.', language='Auto'))
Path('design_test.wav').write_bytes(audio)
print('wrote design_test.wav', len(audio), 'bytes')
"
```

Expected: prints a one-sentence `instruct` that reads as a voice description (not a biography paragraph), writes `design_test.wav`. If the LLM stack isn't loadable in this environment (e.g. `ModelNotDownloaded`), note that explicitly and skip to Step 5 rather than failing the whole task — mirrors this repo's existing "skipped — no data/character.md" self-check pattern for missing prerequisites.

- [ ] **Step 4: Verify seed reproducibility** — SKIPPED, depends on Step 3.

Run the same script's last two lines twice more (reuse the already-written `design.json`, don't rebuild it) and confirm both `synth()` calls succeed without error and both produce audio starting with the same WAV header — this checks the seed-pinning workaround doesn't crash, not byte-for-byte identical prosody (accepted per spec, only voice *identity* needs to hold, not exact output).

- [ ] **Step 5: Send the design clip to the user, report findings**

`SendUserFile` on `design_test.wav`. Report to the user: whether both paths ran cleanly, the generated `instruct` sentence for their review, and explicitly ask them to confirm the design-path voice actually sounds appropriate — this is a judgment call (does the LLM-written description produce a good voice) that the plan cannot verify for them.
