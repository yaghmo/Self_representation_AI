---
name: add
description: Ingest a conversation, transcript, or set of answers into the character bible. Extracts the creator's answers and observable reactions, redacts identifying details, appends them to data/sources.md as new S-### entries, and rewrites the affected sections of data/character.md with cites. Use whenever new source material arrives — pasted chat logs, answered questions, screenshots transcribed to text — or when the user types /add followed by the material.
---

# add — ingest source material into the character bible

Takes raw conversation and turns it into cited character data. This is the **only** sanctioned way to modify `data/sources.md`.

## Input

One of:
- Text pasted directly after `/add`
- A file path (e.g. `/add data/conversation-3.txt`)
- Nothing — then ask which material to ingest. Do not guess.

## The one rule everything serves

**The creator authors the character. You transcribe.**

Whatever they say about the character is canon — factual about their life, invented for the character, or any mix. That is their call and you take no position on it.

Your job is to add *nothing*. Not a plausible detail, not a reasonable inference, not a tidier phrasing. Every statement in `character.md` must trace to an entry in `sources.md`. An uncited sentence is a bug.

## What is and isn't recoverable

| File | If you get it wrong |
|---|---|
| `sources.md` | **Permanent.** Append-only, not in git, no backup. A bad entry stays. |
| `character.md` | Free to redo — it can be regenerated from sources at any time. |

So: **be slow and conservative when logging, relaxed when deriving.** When unsure whether to log something, don't — ask. When unsure how to phrase a trait, write your best guess; it costs nothing to fix.

---

# Decision tests

These replace judgment with checks. **Apply them literally.** When a test is ambiguous, take the listed default — the defaults are chosen so that being wrong is cheap.

### Test 1 — Is this an extractable item?

- **Can you quote the exact words that support it?** No → not an item. Do not log it.
- **Are you describing what they did, or why they did it?** Why → not an item.
  - `"Apologised quickly"` — observable. Log it.
  - `"Felt guilty"` — motive. Don't.
- **Default when unsure:** don't extract. A missed item can be picked up from the next batch; a fabricated one is permanent.

### Test 2 — Are two sources independent?

This is the highest-stakes test in the skill. It controls whether `(tentative)` gets dropped, which is the bot's confidence signal.

**Independent only if at least one is true:**
- They come from different conversations, or different days
- One is self-reported and the other is observed behaviour

**NOT independent:**
- Two sentences in the same message
- Two items extracted from the same batch about the same thing
- An answer and a restatement of that answer
- Your own two readings of one quote

**Default: NOT independent.** Keep the `(tentative)` marker. A trait that stays tentative one batch too long is harmless. A trait promoted on one source pretending to be two is a bot asserting something confidently on thin evidence.

### Test 3 — Conflict, or nuance?

**It is a conflict only if BOTH hold:**
1. Both statements are unqualified, and
2. They cannot both be true at once

**It is nuance if any hold:**
- They carry different qualifiers ("I don't judge anyone" / "I judge people who've done something bad" — both carry *unless harm*)
- They apply to different contexts or different objects (deflects a hyperbolic compliment, accepts a plain one)
- One is about behaviour and the other about self-image

**Default: nuance.** Write a `- **Note:**` explaining why it looks like a conflict and isn't. Never silently resolve a real conflict — flag it and ask.

### Test 4 — Redact, omit, or keep?

Ask **whose information is this**, before asking how precise it is:

| Whose | Action |
|---|---|
| Someone other than the creator | **Omit entirely.** Not fuzzed — omitted. Their health, age, job, problems, and name are not character data at any precision |
| The creator's, and precise (date, place, school, number, handle) | Fuzz per the policy table in `sources.md` |
| The creator's, and not identifying | Keep verbatim |

**Default when unsure: omit and tell the user what you left out.** They can always ask you to add it back. You cannot un-log something.

Never infer an age, a location, or a date that was not stated — including from indirect evidence like schooling, life stage, or someone else's age.

### Test 5 — Naming a trait

**Name the behaviour, not the virtue.**

- ✅ `Resists being treated as an imposition` — describes what she does; checkable against the quotes
- ❌ `Selfless` — a verdict; not checkable, and asserts more than the evidence

**Check:** could someone accept your quotes and still reject your label? If yes, the label is doing work the evidence doesn't support. Rename it closer to the behaviour.

---

# Procedure

### 1. Read state first

1. `CLAUDE.md` — project rules
2. `data/sources.md` — the **redaction policy table**, the `## Ingested material` table, the highest existing `S-###`
3. `data/character.md` — the current profile

**Read the policy table; don't assume the defaults.** The creator may have loosened a row. Unset or unclear → conservative default.

### 2. Check what has already been logged

Duplicates are not harmless. `sources.md` is append-only, so removing them means hand-editing a file whose premise is that you don't — and they corrupt the confidence signal by making one source look like two.

**Exact string matching, not semantic comparison.** Two different answers that *mean* the same thing are two independent sources; semantic matching would collapse them and inflate confidence. You are catching identical text logged twice, which is a string problem.

**Source level:** check the `## Ingested material` table. Already processed → say so and stop, unless the user confirms it changed.

**Item level:** for each candidate, grep a distinctive 5–10 word snippet:

```
grep -F "distinctive snippet from the answer" data/sources.md
```

A hit means already logged — skip it. This is a search, not a context load; it stays cheap at any file size, which matters on a small-context model.

Partial overlap is normal, not an error. Ingest what's new, skip what's known, report both counts.

### 3. Separate the creator's material from everyone else's

Only the **creator's** side becomes entries. The other party's messages are context that makes her replies legible — they are not character data, and their personal details are never logged (Test 4).

### 4. Extract items

| Kind | `Type:` | What it is |
|---|---|---|
| Something she said about the character | `direct answer` | Her authorship. Strongest evidence. |
| Something visible in *how* she wrote | `observed event` | Your read of her behaviour. Weaker — inference about her, not authorship by her. |

Run **Test 1** on every candidate.

Observed material is the high-value part and the easiest to miss. Look for:

- **Register** — punctuation, emoji, capitalisation, typos, laughter, message length and shape
- **Reactions** — what produces excitement, discomfort, deflection, silence
- **Boundaries** — anything she declines, redirects, or asks not to happen
- **Hedges** — how she qualifies before committing to a statement
- **Behaviour under load** — tired, rushed, put on the spot
- **What she volunteers unprompted** — that's what she cares about

### 5. Redact on the way in

Apply **Test 4** to every detail, as you log. Never as a cleanup pass afterward.

**A bracketed value is always a fuzzed replacement, never an original.** Never write the precise value anywhere — not in an ignored file, not in a comment, not in your reply to the user.

### 6. Append entries — never edit existing ones

Continue numbering from the highest existing `S-###`. If something is corrected later, add a new entry and mark the old one `SUPERSEDED BY S-###`.

```
### S-0NN
- **Date:** [~fuzzed period]
- **Type:** direct answer | observed event | interview | public post | existing bio
- **Tags:** personality, voice
- **Q:** the question as asked, or "— (unprompted)" for observed material
- **A:** her answer, VERBATIM
- **Feeds:** §3 Core traits, §6 Voice
```

**Verbatim means verbatim.** Do not fix grammar, spelling, punctuation, or emoji. Do not tidy. The phrasing *is* the voice data, and a cleaned-up answer is a destroyed one. This is the single most common way to damage the file.

Add `- **Redacted:** ...` naming what you reduced or omitted, and `- **Note:** ...` for anything a future session needs.

### 7. Self-check before touching `character.md`

For each new entry, verify:

- [ ] The `A:` field is character-for-character what she wrote — no fixed typos, no normalised emoji
- [ ] Every fuzzed value is in brackets, and no precise original appears anywhere
- [ ] Nothing belonging to the other party is present at any precision
- [ ] No age, location, or date is stated that she did not state herself
- [ ] The ID is sequential and does not already exist

Fix anything failing this **before** deriving. After it's written, it's permanent.

### 8. Rewrite the affected sections of `character.md`

Only the sections named in each entry's `Feeds:` line.

- Add the fact with its cite: `Forgiving [S-008]`
- An event implying a trait becomes that trait **with the event as its cite** — never a floating adjective
- Apply **Test 5** to every trait name
- Apply **Test 2** before dropping any `(tentative)` marker
- Apply **Test 3** to anything that looks contradictory
- Reported second-hand ("my friends would say I'm kind") is weaker than self-report or observation — label it as reported

Leave unanswered fields as `_[unanswered]_`. **"Unknown" is a correct state.** Filling it with something plausible is the failure this whole system exists to prevent.

### 9. Tick the Open Questions

`- [x] What line would they never cross? → S-006`, `[~]` for partial with a note on what's missing. A question answered that wasn't in the bank gets added, marked as added.

### 10. Update the tables

`## Ingested material` row, both file headers (version, date, count), a changelog row in each.

---

# Worked examples

Worked extractions, with the reasoning. **These matter more than the prose above** — match their shape.

The content below is **invented** — no creator's material appears in this file, per the privacy rule in `CLAUDE.md`. What is not invented is the *shape*: the messiness, the artifacts, and the judgment calls are exactly what real material looks like, and they are what you must reproduce.

### Example A — a direct answer

Raw: `"2. hmm thats a hard one 😅 i guess im pretty stubborn?? like once ive decided smth im NOT changing my mind lol, which is good and bad tbh, ive definitely dug my heels in when i shouldve just listened"`

```
### S-0NN
- **Date:** [~period]
- **Type:** direct answer
- **Tags:** core traits, flaws
- **Q:** What might be your best quality? And worst flaw?
- **A:** "2. hmm thats a hard one 😅 i guess im pretty stubborn?? like once ive decided smth im NOT changing my mind lol, which is good and bad tbh, ive definitely dug my heels in when i shouldve just listened"
- **Feeds:** §3 Core traits, §3 Flaws
```

Note what survived: the `"2. "` numbering artifact, the `😅`, the `??`, the lowercase `i`, `smth`, `tbh`, `shouldve`. The hedge *"hmm thats a hard one"* is kept — it is voice data, not filler. A tidied version of this answer would be a destroyed one.

Note also what was **not** done: one answer naming a quality and a flaw stays one entry. It is not split into two, and "stubborn" is not upgraded to "strong-willed".

### Example B — an observed item, with the other party's data omitted

Raw context: the other person disclosed a bereavement, and separately that they had lost their job; the creator's character responded.

```
### S-0NN
- **Date:** [~period]
- **Type:** observed event
- **Tags:** relationships, values, coping
- **Q:** — (the other person disclosed a bereavement, and separately a setback of their own)
- **A:** To the bereavement: *"oh no im so sorry 😞"*. To the setback: *"WAIT WHAT"* / *"thats so unfair"*, then *"if u need anything im around ok"*
- **Feeds:** §3 Core traits, §7 Relationships
- **Redacted:** the other person's loss and their employment situation are theirs, not hers, and are not logged. Only her response is.
```

**Test 4 applied:** the other party's circumstances are omitted **entirely, not fuzzed** — this is the distinction to get right. A fuzzed version ("a family matter `[~recent]`") would still be logging their life into her record. The trigger is described generically, and only generically enough that her reaction stays legible.

### Example C — nuance that looks like a conflict

One entry has her brushing off a compliment (*"nahhh stop it 😭"*). Another has her taking one warmly (*"AAA thank u sm!!"*).

**Test 3:** both are qualified by *what kind of compliment* — hyperbolic versus plain. They can both be true. → **nuance**, not conflict. Logged as:

```
- **Note:** Contrast with `S-0NN`, where she deflected. The difference tracks the kind of compliment: a plain one she takes warmly, a hyperbolic or parasocial one she waves off. **Nuance, not a conflict.**
```

And the trait is **renamed** rather than split — `Self-deprecating about praise` becomes `Takes plain compliments, deflects inflated ones`, which is what the evidence actually shows. Splitting would imply two traits where the evidence shows one with a condition.

### Example D — something correctly NOT extracted

Raw: she mentions her exams starting, and elsewhere the other party's age comes up.

- **The exams** → logged as a fact with its cite, flagged **not an age**. No age is derived from it (Test 4, last line).
- **The other party's age** → omitted entirely (Test 4, row 1).
- **Her age** → stays `_[unanswered]_`. It *feels* derivable from schooling plus context, which is exactly why the rule forbids deriving it.

---

# Report back

1. **Entries added** — IDs, one line each. And how many were skipped as already logged.
2. **Traits changed** — new traits, and any `(tentative)` promoted, naming the second source and which limb of Test 2 made it independent.
3. **Redactions** — every detail fuzzed *or omitted*. Be specific: the user is the only one who can tell whether you blurred something load-bearing into uselessness.
4. **Conflicts** — flagged, with the question you need answered. Say if something looked like a conflict and you ruled it nuance, and why.
5. **Still open** — which gaps the next batch should target.

---

# Never

- Edit or delete an existing entry (append-only, always)
- Write a sentence into `character.md` without a cite
- Tidy, correct, or paraphrase a quoted answer
- Infer an age, a location, a date, or a third party's identity — including from indirect evidence
- Log anything belonging to someone other than the creator, at any precision
- Resolve a contradiction yourself
- Drop a `(tentative)` marker without passing Test 2
- Copy a template over an instance file in `data/` — it destroys logged sources and policy overrides, and `data/` is not in git, so it is unrecoverable
