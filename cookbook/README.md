# Cookbook

Probes the machine, works out which set of models will actually run on it, and
writes the config the rest of the app boots from.

```bash
uv sync                      # cookbook only
uv sync --extra runtime      # plus torch/transformers, CUDA build
uv run streamlit run cookbook/app.py
```

Python is pinned to 3.10 and torch comes from PyTorch's cu126 index — the PyPI
wheel for Windows is CPU-only, which would make every GPU placement the fitter
recommends a lie.

## What makes this different from a model picker

The unit being fitted is **the whole stack**, not one model. LLM, embedding and
TTS are all resident at the same time — they come up as servers at container
boot and nothing swaps mid-session — so the question is whether their *sum*
fits, in two separate pools:

- **VRAM**, what the GPU has free right now
- **RAM**, capped by the cgroup limit rather than whatever the host reports

Placement is part of the search. The embedding model is small enough to live on
the CPU permanently, and letting it compete for VRAM against the LLM costs a
quant tier for nothing.

## Why context length is an input, not a detail

A model's cost is `weights + runtime overhead + KV cache`, and only the first
two are constants. The cache grows linearly with context:

| Qwen3-8B Q4_K_M | total | of which KV |
|---|---|---|
| 4k context | 5.84 GB | 0.56 GB |
| 16k | 7.52 GB | 2.25 GB |
| 32k | 9.77 GB | 4.50 GB |
| 64k | 14.27 GB | 9.00 GB |

The same model swings 8 GB across that range — more than the gap between two
model sizes. Any fitter that treats a model as one number is wrong before it
starts.

This matters here specifically because the bible is **~23k tokens**. Holding it
whole means a 32k context, which means a large KV cache, which may mean a
smaller model. That tradeoff is exposed as a slider rather than decided for you.

## Two surfaces

A stack is chosen *for a surface*, and the two are not interchangeable.

**User** — fans talking to the character. Retrieval, then one model call. No
tools, no loop. Any model in the catalogue is eligible.

**Admin** — the creator editing the bible through an agent loop. The model must
emit tool calls a runtime can actually parse, so only entries marked
`tool_calling: "native"` qualify. `"prompted"` means the model can be coaxed
into JSON but has no tool tokens in its chat template — fine for chat, not for
an agent whose failure mode is silently corrupting `sources.md`. TTS defaults
off here: the agent edits text and has no voice.

Each surface writes its own config — `config/stack.user.json` and
`config/stack.admin.json` — because a single file would mean each choice
destroying the other.

## Two modes

**Auto** ranks every legal combination — models × device placement × context —
and shows the best. A few thousand candidates, brute-forced, instant. One row
per distinct stack.

**Manual** takes your choices and tells you whether they fit or brick, and by
how much. No silent substitution.

Either way, nothing is written until you confirm.

## The Docker trap this is built around

Inside a container `psutil` reports the **host's** RAM. Fit against that and the
stack gets OOM-killed on load. So the probe reads `/sys/fs/cgroup/memory.max`
and treats it as the ceiling.

The GPU has the same trap in a different shape. "No GPU found" inside a
container almost always means it was started without passthrough, not that the
machine has no card — so the probe checks for driver files and NVML separately,
and reports those two cases differently, because the fixes are nothing alike.

## API path

The LLM can be served by API instead, in which case it has no local footprint
and only embedding and TTS get checked — and the whole bible fits in context.

Two adapters exist in code: `openai` (anything speaking the OpenAI schema) and
`anthropic`. Every other provider is an entry in `providers.json`. NVIDIA NIM is
listed because its free Developer Program tier is genuinely free — about 1000
credits, no card, ~40 RPM — and it is OpenAI-compatible, so it costs no extra
code.

**Keys are read from the environment only.** `stack.json` records the *name* of
the variable, never the value. Copy `.env.example` to `.env` at the repo root.

## Weights

Everything lands in `models/<model-id>/`, inside the project. Nothing goes to
`~/.cache/huggingface` — `download.py` sets `HF_HOME` before importing the hub
client, so even incidental writes stay local. `models/` is gitignored.

```bash
uv run python -m cookbook.download --list          # catalogue + what's on disk
uv run python -m cookbook.download --models bge-m3 --dry-run
uv run python -m cookbook.download --from-config   # whatever stack.json chose
```

Every command prints the exact byte count before pulling anything, checks disk
headroom, and skips what is already complete. Bandwidth is treated as expensive.

**A model's home repo is not where its weights come from.** `Qwen/Qwen3-8B` is
16 GB of fp16 safetensors; the Q4_K_M the fitter budgeted 4.68 GB for lives in
`Qwen/Qwen3-8B-GGUF`. Each entry therefore carries a `download` block naming the
real source, and for multi-format repos, patterns narrowing it to one format.
Getting those patterns wrong is not a small error: matching `*.json` against
BGE-M3 pulled the ONNX copy alongside the PyTorch one, and matching
`*.safetensors` against Chatterbox pulled all four alternative checkpoints —
12.9 GB instead of 2.97 GB.

## Keeping the catalogue honest

```bash
uv run python -m cookbook.refresh            # dry run
uv run python -m cookbook.refresh --apply
```

Replaces estimates with facts for models already in the list: real file sizes,
and real KV geometry read from `config.json`. It does not discover models — the
list stays curated. Run it when you feel like it, not automatically.

## Files

| File | What it is |
|---|---|
| `probe.py` | Machine probe — cgroup ceiling, NVML, disk, installed weights |
| `schema.py` | Catalogue types and the footprint math |
| `catalogue.json` | The curated model list |
| `providers.json` | API provider presets — data, not code |
| `fit.py` | Budget, scoring, the search |
| `config.py` | Writes `config/stack.json` |
| `download.py` | Fetches weights into `models/` |
| `refresh.py` | Corrects catalogue figures against the hub |
| `app.py` | Streamlit front end |

## Known limitation — read this before trusting a fit

Figures now come from the hub, not from arithmetic: `weights_bytes` is the real
file size and `kv` is read from each model's `config.json`. The original
estimates were within ±7% for the LLMs, which is reassuring but was luck as much
as judgment — one entry was out by 55% because the quant it assumed does not
exist in that repo.

What is still *not* measured: `runtime_overhead_bytes` is a constant per role,
not an observed number, and real usage depends on the serving runtime. So a fit
landing within a few hundred MB of the limit is a maybe, not a yes.

To finish the job on an entry: load it, read actual usage off `nvidia-smi`,
correct the number, set `"figures": "measured"`.

Also not handled: multi-GPU (the fitter reasons about one pool and picks the
card with most free VRAM), and AMD/ROCm. The probe returns device records, so
adding a vendor is a new probe function with no change to the fitter.
