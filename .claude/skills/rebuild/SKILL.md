---
name: rebuild
description: Regenerate data/character.md from scratch out of the entries in data/sources.md. Discards the existing profile and derives a fresh one, so every claim is re-checked against its evidence. Use when the profile has drifted, when a weaker model produced it, when traits look overstated, after correcting or superseding entries, or when the user types /rebuild.
---

# rebuild — regenerate the profile from the sources

Throws away `data/character.md` and derives it again from `data/sources.md`.

## Why this exists

The two files carry very different risk:

| File | Risk |
|---|---|
| `sources.md` | **Permanent.** Append-only, not in git. A bad entry is forever. |
| `character.md` | **Disposable.** Every claim traces to an entry, so it can always be rebuilt. |

That asymmetry is deliberate. It means derivation quality doesn't have to be guarded — a small or unfamiliar model can produce a mediocre profile and you just rebuild it. Only ingestion (`/add`) needs care.

Run this whenever you doubt the profile: after a batch ingested by a different model, when a trait reads stronger than its evidence, or after superseding entries.

## Before you start

**Never touch `sources.md`.** This skill reads it and writes only `character.md`. If you find something wrong in a source entry, report it — do not fix it. Corrections happen through a new entry marked `SUPERSEDED BY`, via `/add`.

## Procedure

### 1. Read

- `CLAUDE.md` — project rules
- `data/sources.md` — **every entry**, plus the Conflicts table and the redaction policy
- `templates/character.template.md` — the section structure to fill

Do **not** read the existing `data/character.md` first. Reading it anchors you to its wording and its mistakes — the point of a rebuild is deriving fresh. Read it only at step 5, to diff.

### 2. Index the evidence

For each entry, note: ID, type (`direct answer` outranks `observed event`), date/occasion, and which sections its `Feeds:` line names.

Group by target section. Each `character.md` section is then written from its own evidence pile.

### 3. Derive, section by section

For every claim you write:

- **Cite it.** No `[S-###]`, no sentence. This is absolute.
- **Count independent sources** — different occasions, or one self-reported and one observed. Same message or same batch = one source. One source → mark `(tentative)`.
- **Name behaviours, not verdicts.** `Resists being treated as an imposition`, not `Selfless`. Test: could someone accept the quotes and reject your label? Then it overreaches.
- **Label second-hand evidence.** "My friends would say I'm kind" is weaker than self-report or observation.
- **Leave gaps as gaps.** `_[unanswered]_` is correct. Filling it plausibly is the failure the whole system exists to prevent.
- **Preserve every `⚠️ CONFLICT`** in the Conflicts table. Never resolve one during a rebuild.

Quote directly where a quote carries voice — §6 especially. Paraphrase loses the thing that makes the bot sound like her.

### 4. Preserve what isn't derived

These are **not** derived from sources and must survive the rebuild — carry them across verbatim:

- The header block, canon rules, and update loop
- §10 rules that came from the creator's own instruction rather than from a trait (hard boundaries, disclosure)
- The full changelog — append a rebuild row, never truncate it

### 5. Diff against the old profile

Now read the version you replaced, and report:

- **Claims that disappeared** — each one is either an overreach you correctly dropped, or something you missed. Say which, per claim.
- **Confidence changes** — any `(tentative)` that appeared or vanished, and why.
- **Renamed traits** — old name, new name, why the new one fits the evidence better.

A rebuild that silently drops claims is worse than no rebuild. The diff is the deliverable.

### 6. Bump

Version, date, source count, and a changelog row saying what changed and why the rebuild was run.

## Report back

1. Sections rewritten, and entries used
2. The step-5 diff — dropped, promoted, demoted, renamed
3. Anything in `sources.md` that looked wrong (**reported, not fixed**)
4. Gaps the next batch should target

## Never

- Modify `data/sources.md` in any way
- Write an uncited claim
- Resolve a conflict
- Drop a `(tentative)` without two genuinely independent sources
- Truncate the changelog
- Read the old profile before deriving
