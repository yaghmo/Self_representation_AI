# Compact persona + profile-section retrieval — making `bible_strategy` real

**Date:** 2026-08-19
**Status:** design, approved
**Touches:** `runtime/bible.py`, `runtime/recall.py`, `service/main.py`.
`runtime/index.py` ends up unmodified (see the amendment below — the
two-index design needs no change to `Index.search`). No schema change to
`config/stack.json` — `bible_strategy` already exists there and is already
threaded onto `Model` (`runtime/model.py:50,80`); this spec is the first
thing that reads it.

`2026-08-08-fan-retrieval-design.md` built `recall(query)` over the story
corpus and explicitly scoped `bible_strategy` out: *"That config field
exists on `Model`... but nothing in `bible.py` currently branches on it...
It's a separate, still-open question about the persona, not the story
corpus."* This spec is that follow-up.

## Why now

Surfaced by a concrete failure, not speculation: turning `thinking: true` on
for the fan chat produced a 507 on the very first message.
`bible.assemble()`'s reserve math is `max(1024, max_tokens * 2) + (1024 if
thinking)`; with `max_tokens=120` that's 2048, leaving a 6144-token budget
against an 8192-token context — and the full `character.md` persona alone is
already 6601 tokens. It doesn't fit, full stop, not even on turn one.

`character.md` is 6601 tokens today, comfortably under 8192 without
`thinking`. It will not stay that size — the creator adds sourced material
over time (`/add`) and `/rebuild` periodically regenerates the profile from
a growing `sources.md`. The 8192-token context itself is fixed by what fits
on this GPU (RTX 4070 Laptop, ~8GB VRAM, most of it already spent on the
8B Q4 model). When the profile crosses the budget, today's `assemble()`
refuses loudly (`ProfileTooLarge`) rather than truncate the persona — correct
behavior, but it means the fan surface goes down, not degrades. This spec
gives it somewhere to go instead.

## Why fold into `recall()`, not a second tool

CLAUDE.md is explicit and was written deliberately: *"The fan surface may
hold exactly one server-supplied read-only tool, `recall(query)`, for
retrieval. Everything else stays out of its schema."* That bound is what
keeps `_reject_tools()` trivial to audit — a forged client request can never
name a write tool because the fan schema never contains one, and there is
exactly one name to check for. A second tool (e.g. a section-enum lookup
reusing the admin's `read_profile_section(heading)`) was considered and
rejected for this reason, even though it would have sidestepped needing the
embedder at all. One tool, broadened scope, no rule change.

## What's always pinned vs. retrieved

The **compact persona** = `§0 At a Glance` + `§6 Voice & Speech Patterns` +
`§10 Interaction Rules` — roughly 1600 of today's 6601 tokens. This is not
a token-savings choice first; it's a safety choice: `§10`'s **Hard
constraints** subsection (*never invent an age, a location, an event, a
person...*) is the one thing that must never be a retrieval miss away from
disappearing. `§6` Voice stays pinned too, because voice fidelity has to
hold on every single reply, not just the ones where retrieval happens to
fire.

**Retrieved on demand**, one whole section at a time, not further chunked:
`§1 Core Identity`, `§2 Physical Presence`, `§3 Personality & Psychology`,
`§4 Background & History`, `§5 Preferences & Texture`, `§7 Relationships`,
`§8 Skills & Public Role`, `§9 Goals & Motivations`.

`bible.py` gains:

```python
COMPACT_SECTIONS = ("0. At a Glance", "6. Voice & Speech Patterns", "10. Interaction Rules")
RETRIEVABLE_SECTIONS = (
    "1. Core Identity", "2. Physical Presence", "3. Personality & Psychology",
    "4. Background & History", "5. Preferences & Texture", "7. Relationships",
    "8. Skills & Public Role", "9. Goals & Motivations",
)

def build_compact_persona(path: Path | None = None) -> str:
    """FRAMING + only the pinned sections, still cite-stripped. Same
    ProfileMissing behavior as build_persona()."""

def profile_section_chunks(path: Path | None = None) -> list[Chunk]:
    """One Chunk per entry in RETRIEVABLE_SECTIONS, whole section text
    (heading included)."""
```

Both reuse `slice_profile()` / `strip_cites()`, and a small `_split_sections()`
helper that walks the sliced body the same line-anchored `## ` way
`section_index_from()` already does, rather than re-deriving section
boundaries a third way. **Not** `tools.py`'s `read_profile_section()` /
`_find_section()` — those already import `PROFILE_START`/`PROFILE_END` *from*
`bible.py`, so `bible.py` importing back from `tools.py` would be circular.
`tools.py`'s version also solves a different, harder problem (a model naming
a section ambiguously at edit time, ties refused rather than guessed) that
this one doesn't need — chunk-building just splits the whole document once.

## Data note (already fixed)

Self-review on this spec caught `§8 Skills & Public Role` and `§9 Goals &
Motivations` missing a newline before their heading in `data/character.md`
— jammed onto the end of the preceding bullet, so `grep "^## "` (and
`section_index_from()`'s `line.startswith("## ")` splitting, which this
spec's chunk extraction reuses) silently skipped both. Fixed directly in
`data/character.md` (whitespace only, no content or cite touched, doesn't
need `/add`) before this spec was written up — `bible._self_check()`
re-run clean afterward. Noted here so the reason two sections' worth of
extra newlines shows up in the next `data/character.md` diff isn't a
mystery later.

## Chunk shape and where profile chunks live

`index.py`'s `Chunk` is `key, kind, story_id, event_id, text, keywords`,
built around story/event identity. Profile sections don't have a story —
`story_id` and `event_id` are set to `""` for this kind, unused, exactly the
way `kind="summary"` chapter chunks already leave `event_id=""` unused today.
Nothing new to learn if you already know the story chunk shapes:

```python
Chunk(
    key=f"profile/{n}",       # "profile/1" .. "profile/9" (section numbers, gaps allowed)
    kind="profile_section",
    story_id="",
    event_id="",
    text=section_text,         # includes its own "## N. Title" heading
    keywords=[],
)
```

These chunks are built from `character.md`, not `data/stories/*.md`, so they
load and refresh on a different trigger than the story index (an `/add` or
`/rebuild` run, not a `/story` ingest).

**Amendment, found during planning:** originally this spec called for
folding profile chunks into the *same* `Index` object and on-disk file the
story chunks use. `Index.refresh(chunks, embed)` doesn't merge — it replaces
`self.chunks` wholesale with whatever list is passed in, reusing vectors
only for keys that didn't change. Calling it with just the 8 profile chunks
would silently drop every story chunk; calling it with the story index's
own chunks *plus* profile chunks, then letting the admin `/story` ingest
path later `save()` that same in-memory index, would leak profile-section
data into `stories.npz` — a file whose own doc comment says it "can be
deleted and rebuilt at any time" from `data/stories/*.md` alone, which
would no longer be true. **Fix: two separate `Index` objects**, a
`_profile_index` alongside the existing `_story_index`, sharing the same
embedder but never sharing a chunk list or a save path. `recall()` searches
both and merges the hit lists by score before formatting — see below. The
on-disk story index is untouched by this spec; the profile index is never
persisted, rebuilt from `character.md` each time a process lazily loads it
(cheap: 8 chunks).

## `recall()`: two indices, two result shapes, one function

Story hits keep today's hydration (event text plus its story's summary as a
header). Profile-section hits need no hydration — the chunk's own text
already stands alone, heading included. `recall()` takes the profile index
as an additional optional argument rather than requiring `Index.search` to
understand more than one kind at a time:

```python
def recall(query, index, embed, limit=3, include_profile=False, profile_index=None) -> str:
    hits = index.search(query, embed, limit=limit, kind="event")
    if include_profile and profile_index is not None:
        hits = hits + profile_index.search(query, embed, limit=limit, kind="profile_section")
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:limit]
    if not hits:
        return f"no matching stories for {query!r}"
    parts = []
    for hit in hits:
        if hit.chunk.kind == "profile_section":
            parts.append(hit.chunk.text)
        else:
            summary = by_key.get(f"{hit.chunk.story_id}/summary")
            header = summary.text if summary is not None else hit.chunk.story_id
            parts.append(f"{header}\n\n{hit.chunk.text}")
    return "\n\n---\n\n".join(parts)
```

`include_profile` defaults `False` so **whole-persona mode's story search
stays byte-identical to today** — broadened scope only applies when compact
mode is actually active, and `Index.search` itself needs no changes at all
(still one `kind` string per call, as today). Ordering stays score-order,
not stable-id order, for the same reason the original spec gave: nothing
here is pinned and re-shown across turns, so there's no KV-prefix stability
to protect.

## Tool schema text must change with the mode

`RECALL_SCHEMA`'s current description says to use it for something "the
character profile does not cover" — accurate today, wrong once the tool
also answers questions the profile *does* cover but the compact persona
doesn't currently show. Left unchanged, the model would never think to call
it for an ordinary personality/background/preferences question in compact
mode. `RECALL_SCHEMA` (module-level constant) becomes `recall_schema(include_profile: bool) -> dict`
(function), worded per mode — whole-persona mode keeps today's exact text
unchanged; compact mode's description explicitly says the tool also reaches
profile detail not already shown.

## `service/main.py`: choosing the strategy, with automatic fallback

`_get_recall()` already lazily loads and caches `_story_index` +
`_story_embed` as module globals the first time a non-agent `/chat` request
needs them. It gains a sibling `_profile_index` global, built the same lazy
way from `bible.profile_section_chunks()` on first use (same embedder, no
separate config flag — if the embedder loads at all, both indices build).
Its return type changes from `tuple[Index, Embedder] | None` to
`tuple[Index, Index, Embedder] | None` — `(story_index, profile_index, embed)`
— its only caller (`chat()`) is updated to match.

```python
recall_ctx = None if request.tools else _get_recall()
use_compact = (
    not request.tools
    and model.bible_strategy == "retrieval"
    and recall_ctx is not None   # the fallback: no embedder, no compact mode
)
persona = (
    build_procedure() if request.tools
    else build_compact_persona() if use_compact
    else build_persona()          # unchanged path — today's behavior, exactly
)
```

**This is the load-bearing decision of the whole spec.** `bible_strategy:
"retrieval"` in config does not, by itself, put the fan chat into compact
mode — it only *permits* it. If the embedder can't load (as it can't right
now on this machine — `fan retrieval unavailable: torch and transformers
are not installed`, straight from the existing logs), `use_compact` is
`False` and every fan request gets the full profile, exactly as today. Zero
behavior change until the embedder dependency is actually installed;
nothing to toggle, nothing to remember to flip back. The moment it becomes
available, compact mode activates on the next request with no restart-time
decision required.

`_run_recall_loop` passes `include_profile=use_compact` (and `profile_index`)
through to every `recall()` call for that request, and offers
`recall_schema(use_compact)` — worded per mode — instead of the old
`RECALL_SCHEMA` constant. A whole-persona request with the embedder
available still only searches stories — matching today's behavior for that
combination exactly.

## What doesn't change

- `chat_app.py`'s fan branch: zero changes, same as the original recall spec
  — one `/chat` post, one reply, no client-visible difference.
- `/chat/stream`: still refuses tool calls; compact mode is not offered on
  the streaming path, same restriction `request.tools` already implies.
- `_reject_tools()`: unaffected — still only inspects client-supplied
  `request.messages`, the compact-vs-whole choice is entirely server-side.
- Admin surface: `bible_strategy` only changes what the **fan** persona
  looks like. `build_procedure()` (admin) is untouched.
- `sources.md`: still never retrieved, still admin-only. Not touched by this
  spec, same exclusion the original recall spec already established.

## Out of scope

- **Cookbook fit-time logic for choosing `bible_strategy` automatically.**
  This spec makes the *existing* value in `config/stack.json` real. Deciding
  *when the cookbook should write `"retrieval"` instead of `"whole"`* at
  probe time is a separate, later change to `cookbook/fit.py` — CLAUDE.md's
  "never choose silently" rule already requires that be a presented choice,
  not an automatic threshold, and this spec doesn't touch the cookbook at
  all.
- **Retrieval quality tuning** for profile sections specifically (does "what
  games does she play" reliably retrieve `§5 Preferences` over `§3
  Personality`?) — nothing to measure against without real fan traffic; same
  stance the original recall spec took on the story corpus.
- **Sub-section chunking.** Whole-section retrieval was chosen explicitly
  over finer chunks; revisiting that is a separate decision if a section
  itself grows too large to retrieve as one unit.
- **Making the embedder actually load on this machine** (installing
  `torch`/`transformers`, checking the ~2.7GB bge-m3 footprint against
  ~3GB free RAM). Orthogonal to this spec — compact mode falls back safely
  either way, so this can be solved separately, whenever, without blocking
  the code here.

## Testing

`runtime/index.py` is unmodified by this spec (the two-index amendment
above means `Index.search` never needs to filter by more than one kind at
once) — no new `index.py` test cases needed.

`runtime/recall.py`'s `_self_check()`: extend with a second fixture index
built from profile-section-shaped chunks (`kind="profile_section"`, same
fake deterministic embedder the existing fixture already uses) —

- `include_profile=False` (default), `profile_index` passed or not: a
  profile-section chunk is never returned even if it would have scored
  highest — whole-persona mode's story search must stay byte-identical to
  today regardless of whether a profile index happens to be available
- `include_profile=True` with only a profile-section hit matching: returned
  as its raw chunk text, no summary-header hydration attempted, no
  `"no matching stories"` string
- `include_profile=True` with both a story hit and a profile-section hit
  scoring close together: both appear in the result, in score order, each
  formatted correctly for its own kind in the same call
- `include_profile=True` but `profile_index=None`: behaves exactly like
  `include_profile=False` — a caller can't accidentally search profile
  content by flipping one flag without also holding the index

`runtime/bible.py`'s `_self_check()`: extend with —

- `build_compact_persona()` on the placeholder fixture contains the Hard
  Constraints text and the Voice section, and does **not** contain text
  unique to a retrievable-only section — the actual safety invariant this
  whole spec exists to protect, asserted directly rather than trusted
- cites are stripped from the compact persona the same way they are from
  the full one (reusing `strip_cites`, not a second implementation)

`service/main.py`'s existing `_self_check()` (TestClient-based): extend with
scripted-backend cases for —

- `bible_strategy="retrieval"` + embedder available → compact persona sent,
  `recall` offered with `include_profile=True`
- `bible_strategy="retrieval"` + embedder **unavailable** → falls back to
  `build_persona()` (whole), matching today's behavior exactly — this is
  the fallback path and needs its own explicit regression case, not just
  inference from the other cases
- `bible_strategy` anything else (`"whole"`, missing, unrecognized) →
  `build_persona()` regardless of embedder availability
- a whole-persona request with the embedder available still only searches
  stories (`include_profile=False`) — confirms the two knobs
  (`bible_strategy`, embedder availability) don't leak into each other
