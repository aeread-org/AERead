# govsim live campaigns: incident ledger

Tier 2 of the register standard (`docs/operations/incident_log.md`): the
judgment-bearing incidents from building and running this family's live
path. Per-attempt operational detail is in the campaign documents.

## Attempts

| Campaign | Attempt | Outcome | Cost (USD) | Disposition |
|---|---|---|---:|---|
| `first_light_v1` | 001 | 3/3 included, published | 0.0161 | stands, as the **communication-removed** panel |
| `dialogue_v2` | 002 | killed mid-run by the operator | 0.0065 | discarded: the dialogue was fake, see G-J-01 |
| `dialogue_v2` | 003 | 3/3 included, publish refused | 0.0407 | sealed; superseded by the v2 identity, see G-D-01 |
| `dialogue_v2` | 001 | running | -- | -- |

## D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| G-D-01 | the dialogue panel reused `first_light_v1`'s campaign id, so its bundle collided with an already-published one measuring a *different* experiment | the write-once publication guard refused the overwrite | one completed panel (0.0407) re-run under the right identity | v2 is its own campaign; v1 and v2 publish side by side and read as the comparison they are |
| G-D-02 | `discuss` and `reflect` accepted `{}`, so a live panel measured the common-pool dilemma with **communication removed** -- upstream's central mechanism | reading upstream (`cognition/converse.py`, utterances plotted in `analysis/details.py`) rather than the adapter's own docs | v1's survival numbers are not comparable to the paper's | content-carrying actions, a public transcript, per-agent reflections |

## J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| G-J-01 | shipped a harness fallback that **invented an utterance** when the model returned none, so attempt 002's transcript was ten identical strings the model never wrote -- fed into the public transcript and every agent's observation as if real | reading the sealed utterances from a live run; the status line said "included" and the offline dry run said 126/132 observations carried an utterance | one killed run, and a published panel narrowly avoided | fallback deleted: an empty utterance now raises. Inventing dialogue is fabricating evidence |
| G-J-02 | reported the dialogue fix as "verified" on the strength of a dry run whose **stub returned the field being tested** | the live run's identical strings | an incorrect claim to the operator, corrected the same session | a dry run validates plumbing, not content; check that outputs are *distinct*, not merely present |

G-J-01 and G-J-02 share a cause worth naming: every check was on shape, and
none on content. `count == 12` was true of both the fabricated transcript and
the real one; only `distinct == 12` told them apart. A first light should
read what the model actually said, not just whether the fields were filled.
