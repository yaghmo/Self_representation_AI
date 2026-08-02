# Redaction policy

One policy, every corpus. `sources.md`, `stories/`, and anything added later
all obey this table. Change it here and the change applies everywhere.

**Reduce at ingestion, never as a later cleanup pass.** Every corpus is
reachable by the bot, so anything exact written into one can be surfaced to
the public. A bracketed value is always a fuzzed replacement, never an
original — never write the precise value anywhere in the repo, including in
ignored files.

Only the creator may loosen a row, and the approval is recorded here with a
date. Tightening needs no approval. Unset or unclear means the conservative
default. Where the policy is genuinely unclear for a specific detail, ask —
do not guess at how much to blur.

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
