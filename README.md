# self_presentation_AI

A portfolio page for a content creator — links, socials, media — with a chatbot that answers audience questions as an AI representation of the creator, grounded in a character profile they write themselves.

The design goal is **one author**. The creator defines the character — factual about themselves, invented, or any mix; that's their call. Everything downstream only transcribes. The bot answers from the documented source record or it says it doesn't know; it does not improvise a personality or fill gaps with plausible-sounding fiction, because invention there is authorship it doesn't have.

## Status

Character-authoring format is defined. No application code yet — stack and features are undecided.

## How the character system works

Two files per creator, and the dependency only runs one way.

| File | Role |
|---|---|
| `sources.md` | Raw Q&A, append-only, verbatim. The only truth. |
| `character.md` | Readable profile derived from `sources.md`. Every statement cited. |

Both are plain markdown with no dependency on how inference is run — the format is deliberately runtime-agnostic.

Every claim in `character.md` carries a cite (`[S-004]`) pointing at the source entry behind it. A statement with no cite is a bug. That's what makes the "no invented life" rule enforceable rather than aspirational — and it's why an unanswered question stays visibly unanswered instead of quietly becoming a guess.

Traits are derived, never asserted directly: an event about helping someone becomes a `helpful` trait *with that event as its cite*. Single-sourced claims are marked `(tentative)` until a second source backs them, which later tells the bot how firmly to assert something. Contradictions between sources get flagged, never silently resolved.

## Setup

```bash
mkdir -p data
cp templates/character.template.md data/character.md
cp templates/sources.template.md data/sources.md
```

Then work through the Open Questions list in `data/sources.md`. Answer as the creator, in their own words. Log each answer as the next `S-###`, then update the sections of `character.md` it feeds.

Answer verbatim — don't tidy the phrasing. How someone phrases an answer is the best voice data in the project; a cleaned-up answer is a destroyed one.

## Privacy

**`data/` is never committed.** `.gitignore` denies by default: everything is ignored unless explicitly allowed, so a new file is untracked until someone opts it in. Only `templates/`, `README.md`, and `.gitignore` are tracked.

Adding source directories later means adding a whitelist line (`!src/**`). That's deliberate — the cost is one line per directory, and the benefit is that forgetting to update `.gitignore` can never leak a creator's personal information.

## Disclosure

Any deployment must make clear to visitors that they are talking to an AI representation, not the person. The creator's actual answers are the only source material, and the creator should review the profile before it goes live.
