# `/story` — story ingestion design

**Date:** 2026-08-02
**Status:** approved, not yet planned
**Scope:** the story corpus, its ingestion command, and its index.

> Every example in this document is synthetic. No creator material appears here.

## Why this exists

`sources.md` holds answers to questions. It is append-only, verbatim, and every
line of `character.md` cites it. That format is right for Q&A and wrong for
narrative: a creator who wants to write down a whole day, or a story about the
character, has nowhere to put it that does not distort the source log.

Stories are a third corpus. They are not ground truth to be cited and not a
derived profile — they are material the fan-facing bot draws on at chat time
through retrieval.

## Decisions

| Question | Decision |
|---|---|
| Story text mutable or append-only? | **Mutable.** Amendments edit the story in place. |
| How is an edit made safe? | Snapshot to `data/.backups/` before every write, reusing the existing helpers. |
| New story vs amendment? | **Always retrieve, always propose.** The confirm gate names which it chose. No flag for the creator to forget. |
| Redaction | One policy for every corpus, hoisted out of `sources.md` into its own file. |
| Retrievable unit | **Two levels** — a story summary for coarse matching, event chunks for the payload. |
| Does `/story` touch `character.md`? | **No.** That stays `/add`'s job. |

### On mutability

This is a deliberate departure from the append-only rule that governs
`sources.md`, made by the creator with the consequence stated: a model edits
the creator's own phrasing, and `data/` is not in git, so a bad edit has no
version history behind it.

The mitigation is the snapshot, not a policy. `runtime/tools.py` already has
`snapshot`, `list_backups()` and `restore_backup()` writing to
`data/.backups/`. Story writes go through the same path, so every edit is one
restore away from undone. No new machinery.

`sources.md` remains append-only and is not affected by this decision.

## Storage

```
data/
  redaction-policy.md      one policy, every corpus
  character.md             unchanged
  sources.md               unchanged, append-only
  stories/
    ST-001.md              one file per story, mutable
    ST-002.md
  index/
    stories.npz            embeddings + metadata — derived, rebuildable
```

### Story file format

```markdown
# ST-001 — a weekend hiking trip
**Summary:** the guide who met us at the trailhead, the storm on the second
day, getting back down after dark
**Keywords:** hiking, mountains, weather
**Logged:** [~early 2026]

## E-001 — meeting the guide
Free text, the creator's own phrasing.

## E-002 — the storm
...
```

`ST-###` and `E-###` are **stable ids**, assigned once and never reused or
renumbered. This is load-bearing. The fan-side prompt layout orders retrieved
chunks by stable id rather than by relevance score, so that identical content
serialises to identical bytes and the KV prefix cache survives between turns.
Renumbering events would silently destroy that property.

The `Logged:` value follows the redaction policy like any other date.

### Why the index is derived

`stories/*.md` are the truth. `index/stories.npz` is a cache of embeddings and
metadata that can be deleted and rebuilt at any time. Nothing may live only in
the index.

## Redaction

The policy table currently lives inside `data/sources.md`. It moves to
`data/redaction-policy.md` and governs every corpus — sources, stories, and
anything added later. One file, one place for a creator to change it.

This supersedes the line in `CLAUDE.md` pointing at the `## Redaction policy`
section of `data/sources.md`; both `CLAUDE.md` and the `/add` skill need
updating to the new location as part of implementation.

Rules carried over unchanged:

- Reduce at ingestion, never as a later cleanup pass. Anything written to a
  corpus can be surfaced to the public by the bot.
- A bracketed value is always a fuzzed replacement, never an original.
- Only the creator may loosen a row, recorded in the table with a date.
- Where the policy is genuinely unclear for a specific detail, **ask**. Do not
  guess at how much to blur. This is for ambiguity in the policy, not for
  negotiating narrative texture — stories get no looser treatment than any
  other corpus.

## Ingestion flow

```
/story  <pasted text | attached file>

 1. read data/redaction-policy.md
 2. if a file: markitdown -> markdown
 3. embed input; retrieve against summaries AND event chunks
 4. route:
      >= 0.95 similar to existing content  -> REFUSE, name the duplicate
      >= 0.60 story match                  -> propose AMENDMENT
      below that                           -> propose NEW STORY
 5. redact on the way in
 6. confirm gate — names the choice and the target story
 7. on approve: snapshot -> write -> re-embed changed chunks only
```

Step 4's routing decision is a proposal, never a silent action. The gate states
in words which of the two branches it took and against which story, so a
misroute is visible before anything is written.

Step 7 re-embeds only chunks whose text changed. A one-line amendment must not
trigger a full corpus rebuild.

### Proposing a new story

The agent proposes the id, the summary, the keyword list, and the event
segmentation. The creator sees all four at the gate and can reject or adjust
before anything is written. Event segmentation is a model judgment made once at
ingestion, on the admin surface, where judgment is affordable.

### Thresholds

Similarity is cosine on the dense bge-m3 vector.

Input that is ≥0.95 similar to content already in the corpus is refused rather
than ingested, and the refusal names what it duplicates. This catches the
common case of the same story being pasted twice.

The 0.60 amendment threshold is a **starting value to be tuned against the real
corpus**, not a derived constant. It can be wrong in either direction without
causing damage, because the gate names the branch it took before anything is
written — a misroute costs one rejection, not a corrupted story. Both
thresholds live in one place in code so tuning them is a single edit.

Below that threshold, near-duplicate content is a matter for the gate, not for
an automatic rule — a creator retelling the same event with new detail is
producing an amendment, which is exactly what branch two handles.

## Amendment resolution

The case this design was built around: a detail arrives with no marker, naming
its target only by allusion.

```
"oh btw the guide from that hiking trip had a red jacket"

  summary match     ST-001  0.81   <- hiking trip
                    ST-014  0.44   <- a different trip
  event match       E-001   0.77   <- "meeting the guide"

  PROPOSE  amend ST-001 / E-001
    - the guide met us at the trailhead and
    + the guide, red jacket, met us at the trailhead and

  [confirm]  [reject]  [redirect -> ST-014]
```

Two-level retrieval performs the resolution: the summary layer finds the story,
the event layer finds the paragraph. The runner-up stories are shown alongside,
so a wrong hit costs one click rather than a corrupted story.

The model never picks the edit target silently. With mutable story text that is
the failure mode that matters most.

## Retrieval

Hybrid, using bge-m3 — one encoder producing both dense and sparse lexical
weights, so hybrid costs one model rather than two systems plus a fusion layer.
bge-m3 is already in the cookbook catalogue and already fitted.

Storage is a numpy array until it measurably stops being enough. At the corpus
sizes in play — order hundreds of chunks — a vector database is infrastructure
without a problem to solve. Swapping to one later is a contained change because
the index is derived.

Metadata per chunk: `kind`, `story_id`, `event_id`, `keywords`, `cites`.

`recall(query)` returns event chunks plus the parent story summary for context,
ordered by stable id, and the returned block is pinned while the conversation
stays on topic.

## Error handling

| Case | Behaviour |
|---|---|
| Input matches nothing but reads like an amendment | Propose a new story. The gate catches it; the creator redirects. |
| Two stories match closely | Gate shows both, ranked. Creator picks. |
| Index disagrees with `stories/` | Rebuild the index. The files win, always. |
| Story file changed since the proposal was built | Reuse `StaleProposal` from `runtime/tools.py`. Proposal is refused, not applied blind. |
| Write fails midway | Snapshot precedes every write, so `restore_backup()` recovers. |
| markitdown fails on a file | Report the failure and stop. Never ingest a partial conversion. |

## Testing

Each new module carries a `_self_check()` runnable as `python -m <module>`,
matching every other module under `runtime/`. The checks that matter:

- Stable ids survive an amendment — no renumbering.
- Chunks serialise in stable-id order regardless of retrieval score.
- A ≥0.95 duplicate is refused.
- An amendment re-embeds only the chunks whose text changed.
- Every write is preceded by a snapshot.
- Redaction runs before the write, not after.

## Out of scope

Deliberately excluded, to keep this one project:

- The fan-side `recall` tool and the append-only prompt layout it feeds.
  Decided already, recorded in `CLAUDE.md`, built separately.
- Indexing `sources.md`. Same infrastructure, different corpus, own decisions.
- The turn budget for chunked file ingestion. Related, separately scoped.

The story index and the fan-side retrieval consumer share infrastructure. This
spec builds the corpus and the index; the consumer follows.
