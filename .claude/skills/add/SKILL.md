---
name: add
description: Ingest a conversation, transcript, or set of answers into the character bible. Extracts the creator's answers and observable reactions, redacts identifying details, appends them to data/sources.md as new S-### entries, and rewrites the affected sections of data/character.md with cites. Use whenever new source material arrives — pasted chat logs, answered questions, screenshots transcribed to text — or when the user types /add followed by the material.
---

# add — ingest source material into the character bible

Takes raw conversation and turns it into cited character data. This is the **only** sanctioned way to modify `data/sources.md` and `data/character.md`.

## Input

One of:
- Text pasted directly after `/add`
- A file path (e.g. `/add data/conversation-3.txt`)
- Nothing — then ask which material to ingest. Do not guess.

## The one rule everything serves

**The creator authors the character. You transcribe.**

Whatever they say about the character is canon — factual about their life, invented for the character, or any mix. That is their call and you take no position on it.

Your job is to add *nothing*. Not a plausible detail, not a reasonable inference, not a tidier phrasing. Every statement you write into `character.md` must trace to an entry in `sources.md`. An uncited sentence is a bug.

---

## Procedure

### 1. Read state first

Read, in this order:

1. `CLAUDE.md` — the project rules
2. `data/sources.md` — specifically: the **redaction policy table**, the highest existing `S-###`, and the existing entries (you need them to detect conflicts)
3. `data/character.md` — the current profile

**Read the policy table, don't assume the defaults.** The creator may have loosened a row. Unset or unclear → use the conservative default.

### 2. Separate the creator's material from everyone else's

In a two-person conversation, only the **creator's** side becomes entries. The other party's messages are context that makes the creator's replies legible — they are not character data, and their personal details never get logged.

### 3. Extract two kinds of item

| Kind | `Type:` | What it is |
|---|---|---|
| Something they said about the character | `direct answer` | Their authorship. Strongest evidence. |
| Something visible in *how* they wrote | `observed event` | Your read of their behaviour. Weaker — it's inference about them, not authorship by them. |

Observed material is the high-value part and easy to miss. Look for:

- **Register** — punctuation habits, emoji use, capitalisation, typos, laughter, filler words, sentence length
- **Reactions** — what produces excitement, discomfort, deflection, silence
- **Boundaries** — anything they decline, redirect, or explicitly ask not to happen
- **Self-corrections and hedges** — how they qualify before committing to a statement
- **Behaviour under load** — tired, rushed, overwhelmed, put on the spot
- **What they volunteer unprompted** — that's what they care about

Do not extract an item you can only state by guessing at motive. "Was polite" is observable. "Felt insecure" is not.

### 4. Redact on the way in

Reduce precision **as you log**, never as a cleanup pass afterward. Follow the policy table in `data/sources.md`.

Default reductions:

| Seen | Logged as |
|---|---|
| An exact date | `[~mid-July]`, `[~2023]` |
| An address, venue, neighbourhood | city level, or "home" / "a café near their place" |
| A school or employer name | "their university", "the studio they worked at" |
| A third party's full name | first name only, or "a friend" |
| Contact details, handles, booking or flight numbers | omit entirely |
| An exact age tied to a year | approximate |

**A bracketed value is always a fuzzed replacement, never an original.** Never write the precise value anywhere — not in an ignored file, not in a comment, not in your reply to the user.

Do **not** infer an age or location that was never stated. If a detail is load-bearing for the character but too precise to log safely, **ask** rather than guessing how much to blur.

### 5. Append entries — never edit existing ones

`sources.md` is append-only. Continue the numbering from the highest existing `S-###`. If something is corrected later, add a new entry and mark the old one `SUPERSEDED BY S-###`.

```
### S-0NN
- **Date:** [~fuzzed period]
- **Type:** direct answer | observed event | interview | public post | existing bio
- **Tags:** personality, voice
- **Q:** the question as asked, or "— (unprompted)" for observed material
- **A:** their answer, VERBATIM
- **Feeds:** §3 Core traits, §6 Voice
```

**Verbatim means verbatim.** Do not fix grammar, spelling, punctuation, or emoji. Do not tidy. The phrasing *is* the voice data, and a cleaned-up answer is a destroyed one. This is the single most common way to damage the file.

Add `- **Redacted:** ...` naming what you reduced, and `- **Note:** ...` for anything a future session needs to know.

### 6. Check for conflicts — flag, never resolve

Compare against existing entries. If a new entry contradicts an old one:

- Mark `⚠️ CONFLICT` in the affected `character.md` section
- Log both IDs in the **Conflicts** table in `sources.md`
- **Ask the user.** Never silently pick a winner — that's how a profile drifts away from the person

Before flagging, check it's a real contradiction. Two statements carrying the same qualifier are consistent, not conflicting.

### 7. Rewrite the affected sections of `character.md`

Only the sections named in each entry's `Feeds:` line.

- Add the fact with its cite: `Forgiving [S-008]`
- An event that implies a trait becomes that trait **with the event as its cite** — a story about helping someone yields `Helpful [S-014]`, never a floating adjective
- Single-sourced → mark `(tentative)`
- A second **independent** source → drop the `(tentative)` marker. Two answers in the same batch about the same thing are one source, not two
- Reported second-hand ("my friends would say I'm kind") is weaker than self-assessment or observation — label it as reported

Leave unanswered fields as `_[unanswered]_`. **"Unknown" is a correct state.** Filling it with something plausible is the failure this whole system exists to prevent.

### 8. Tick the Open Questions

Mark answered questions `[x]` with the entry ID: `- [x] What line would they never cross? → S-006`

Use `[~]` for partial answers, with a note on what's still missing. If the material answered a question not in the bank, add it as answered and mark it as added.

### 9. Bump both files

Version + `Last updated` + entry count in the headers, and a changelog row in each file describing what landed.

---

## Report back

State plainly:

1. **Entries added** — IDs and a one-line summary each
2. **Traits changed** — new traits, and any `(tentative)` promoted to established (say which second source did it)
3. **Redactions** — every detail you blurred, so the user can check you didn't over- or under-do it
4. **Conflicts** — flagged, with the question you need answered
5. **Still open** — which gaps the next batch should target

Be specific about redactions. The user is the only one who can tell whether you blurred something load-bearing into uselessness.

---

## Never

- Edit or delete an existing entry (append-only, always)
- Write a sentence into `character.md` without a cite
- Tidy, correct, or paraphrase a quoted answer
- Infer an age, a location, a date, or a third party's identity
- Resolve a contradiction yourself
- Log the other party's personal details
- Copy a template over an instance file in `data/` — it destroys logged sources and policy overrides, and `data/` is not in git, so it is unrecoverable
