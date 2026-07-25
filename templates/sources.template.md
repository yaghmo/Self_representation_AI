# [CHARACTER NAME] — Source Appendix

> **Version:** 0.1 · **Last updated:** YYYY-MM-DD · **Entries:** 0
> **Companion file:** `character.md` — the profile derived from this one.

---

## How this file works

This is the **ground truth** half of a two-file system. Everything asserted in `character.md` traces back to an entry here.

**Append-only.** Never edit a logged answer. If something is corrected later, add a new entry and mark the old one `SUPERSEDED BY S-###`. The history of what was believed and when is part of the record.

**Answer verbatim.** Do not clean up phrasing, fix grammar, or make it sound better. How someone phrases an answer is the best voice data in the whole project — a tidied answer is a destroyed one.

### Redaction — log the fact, not the fingerprint

Real answers carry details that identify or locate a real person. **Reduce precision as you log**, never as a later cleanup pass — this file is the retrieval corpus, so anything exact written here can be surfaced to the public by the bot.

**A bracketed value is always a fuzzed replacement, never an original** — `[~mid-July]` marks a detail deliberately reduced. Never write the precise value anywhere, including in ignored files; those still get pasted, backed up, and shared.

This bends the verbatim rule on purpose: **keep the phrasing, reduce the specifics.** Phrasing is voice data and stays untouched; a date is not voice data.

## Redaction policy — set per creator

The defaults below are deliberately conservative. **This is the creator's call, not the author's.** They may loosen any row — but only they can, and it has to be recorded here with a date. Never loosen a row by inference, by convenience, or because a detail seems harmless.

Unset, unclear, or mid-discussion → **use the default.** Fail safe.

| Category | Default | This instance | Approved by / when |
|---|---|---|---|
| Dates | fuzz to period — `[~mid-July]`, `[~2023]` | default | — |
| Locations | city level; no address, venue, or neighbourhood | default | — |
| School / employer names | generalised — "their university" | default | — |
| Third-party full names | first name only, or "a friend" | default | — |
| Contact details, handles, booking or flight numbers | omit entirely, always | default | — |
| Age | approximate, not tied to an exact year | default | — |
| Family details | generalised; no names | default | — |
| Health / medical | omit unless the creator explicitly opts in | default | — |

To loosen a row, replace `default` with what's allowed and fill in the approval column:

```
| Dates | fuzz to period | exact dates OK for public/professional events only | creator, 2026-03-04 |
```

Two things worth keeping in mind when a creator loosens something:

- **Precision compounds.** Individually harmless details — a city, a school, a birth month, a workplace — combine into an identification. A row loosened in isolation may be safe; three loosened rows may not be.
- **This is reversible only going forward.** Once precise data is logged, embedded, and answered with, it has been published. Removing it later doesn't unpublish it. When unsure, log conservatively — precision can always be added when the creator confirms, but it cannot be recalled.

If a detail matters to the character but is too precise to log safely, ask instead of guessing how much to blur.

At runtime this file is the retrieval corpus: entries get chunked and embedded, and the relevant ones are pulled in to answer a given question. `character.md` is what sits in the system prompt.

### Entry format

```
### S-001
- **Date:** YYYY-MM-DD
- **Type:** direct answer | interview | public post | observed event | existing bio
- **Tags:** personality, fears
- **Q:** the question as asked
- **A:** the answer, verbatim
- **Feeds:** §3 Core traits, §3 Fears
```

`Type` matters for trust: a direct answer from the person outranks an inference from an observed event. `Feeds` makes the link bidirectional — from a claim you can find its evidence, and from a source you know what to go rewrite.

---

## Source log

<!--
  EXAMPLE — delete this entry when you start. Fictional, for format only.

  ### S-001
  - **Date:** 2026-01-15
  - **Type:** direct answer
  - **Tags:** personality, coping, voice
  - **Q:** How do you act when you're angry?
  - **A:** "Honestly I just go quiet. Like, really quiet. My friends know
    something's wrong when I stop making jokes. I don't really yell, I
    just kind of shut the door and deal with it later."
  - **Feeds:** §3 Coping (Angry), §3 Core traits, §6 Humor
-->

_[empty — first entry goes here]_

---

## Open Questions

Unanswered. Each one answered becomes a source entry above.
**Nothing here may be filled in by inference.**

### Personality — Core traits & self-image
- [ ] How would they describe themselves in one sentence?
- [ ] How would someone who dislikes them describe them?
- [ ] How would someone who loves them describe them?
- [ ] What do they think their best quality is?
- [ ] What do they think their worst flaw is?
- [ ] What's a trait they have but might not fully admit to themselves?

### Personality — Values & moral compass
- [ ] What line would they never cross?
- [ ] What do they judge other people for?
- [ ] What do they tend to forgive easily in others?
- [ ] Do they believe people can change?

### Personality — Fears
- [ ] What are they visibly afraid of?
- [ ] What's something they're afraid of but wouldn't say out loud?
- [ ] What do they do the moment they feel that fear rising?

### Personality — Coping & stress
- [ ] How do they act when angry — explode, go cold, get sarcastic, go quiet?
- [ ] How do they act when scared or anxious?
- [ ] How do they act when sad — isolate, seek company, mask it with humor?
- [ ] Under pressure: fight, flee, freeze, or fix?
- [ ] Do they ask for help easily, or avoid it?

### Personality — Contradictions
- [ ] What's something they want but feel conflicted about wanting?
- [ ] Where might their words and actions not fully match up?
- [ ] What's a belief they hold strongly, even if it's debatable?

### Personality — Attachment
- [ ] Do they open up quickly or slowly?
- [ ] Do they trust easily, or do people have to earn it?
- [ ] How do they handle betrayal or being let down?
- [ ] How do they show they care — words, actions, presence, humor?

### Background & history
- [ ] Where and when were they born? What was childhood like?
- [ ] Who raised them, and what was that relationship like?
- [ ] What's the defining turning point that shaped who they are?
- [ ] What was their education/training?
- [ ] What was life like before they were known publicly?
- [ ] What led them to what they do now?
- [ ] Who shaped them — mentors, rivals, early friends?
- [ ] What do they keep private about their past?
- [ ] A moment they're proud of? Ashamed of?

### Physical presence
- [ ] How would they describe their own appearance?
- [ ] Distinguishing traits, style choices, habits of dress?
- [ ] Body language — posture, gestures, how they carry themselves?
- [ ] How do they act differently in public vs. private?

### Preferences & texture
- [ ] Favorite food, music, media, colors, places?
- [ ] Things they dislike or avoid?
- [ ] Hobbies, how they spend free time?
- [ ] Habits or routines?
- [ ] What makes them laugh? What annoys them?
- [ ] Quirks, pet peeves, comfort objects?

### Voice & speech
- [ ] How do they typically talk — formal, casual, fast, slow?
- [ ] Recurring phrases, verbal tics, catchphrases?
- [ ] How does tone shift between professional, casual, and audience contexts?
- [ ] What topics do they avoid or deflect?
- [ ] Do they use humor, sarcasm, bluntness? How?
- [ ] How do they respond to compliments? To criticism?

### Relationships
- [ ] Who are the important people in their life now?
- [ ] How do they treat their audience specifically?
- [ ] How do they handle conflict or disagreement?
- [ ] Who do they trust most, and why?

### Skills & public role
- [ ] What are they known for / good at professionally?
- [ ] What do they struggle with?
- [ ] How do they talk about their own work?

### Goals & motivations
- [ ] What drives them / what are their stated goals?
- [ ] What do they want for their future?
- [ ] What matters most to them?

### Setup decisions (not character data)
- [ ] What topics are hard boundaries for the bot?
- [ ] How is the AI-representation disclosure worded?
- [ ] Who reviews the profile before it goes live?

---

## Conflicts

Contradictions between sources. Logged, not silently resolved.

| ID | Sources | Description | Status |
|---|---|---|---|
| — | — | _[none logged]_ | — |

---

## Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | YYYY-MM-DD | Created from template. No entries yet. |
