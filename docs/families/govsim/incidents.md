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
| `dialogue_v2` | 001 | 3/3 included, sealed | 0.0397 | not publishable: its plan pins the pre-fix `environment.py`, see G-D-02 |
| `dialogue_v3` | 001 | 3/3 included, published | 0.0408 | stands, as the **dialogue** panel: v1 and v3 read side by side |
| `baseline_v4` | 001 | 3/3 included, published | 0.0392 | stands, as the **baseline** arm: the paper-comparable panel |
| `baseline_deliberating_v5` | 001 | killed by the host mid-case, then could not resume | 0.1657 | sealed; re-attempted as 002 after the supersede fix, see G-O-01 |

## D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| G-D-01 | the dialogue panel reused `first_light_v1`'s campaign id, so its bundle collided with an already-published one measuring a *different* experiment | the write-once publication guard refused the overwrite | one completed panel (0.0407) re-run under the right identity | v2 is its own campaign; v1 and v2 publish side by side and read as the comparison they are |
| G-D-03 | `observe()` served `sustainability_threshold` on every harvest observation. Upstream gives the agent that number only under `inject_universalization` -- its `get_universalization_prompt`, "if everyone fishes more than N every month, the lake will eventually be empty" -- which is the paper's moral-reasoning **intervention**, the arm it reports as significantly more sustainable. The paper's headline ("highest survival rate below 54%") is the baseline arm. Every case in this corpus already declares `env_cfg.inject_universalization: false`, so both published panels ran the intervention while their own contract said baseline, and `test_observe_harvest_exposes_pool_and_threshold` asserted the defect as expected behaviour | reading upstream's own experiment configs while asking why our 12/12 survival did not resemble the paper's <54% | two published panels (`first_light_v1`, `dialogue_v3`, $0.057 total) measure a different arm than they say; no claim was published outside the repo | the observation now follows the declared arm; the scripted reference policy is a control and still sees the threshold; prompts and profile ids are per-arm, so a receipt names its arm. `baseline_v4` measures what the corpus declares. v1/v3 stay sealed and are re-labelled as the universalization arm; an erratum is owed once #117 lands |
| G-D-02 | `dialogue_v2` attempt 001 ran to 3/3 on a branch whose `environment.py` still subscripted the discuss message (`action["message"]`); the `.get("message", "")` fix landed on `main` (#127) after the run. The campaign plan pins every family source file by digest, so `_verify_plan` on `main` rebuilds a different plan and the publisher refuses the bundle -- correctly: a changed frozen control is a new campaign identity, and a bundle whose pinned source is on no pushed branch would be unreproducible | `git diff` of the run worktree against `main`, while checking whether the sealed run could be published | one completed panel ($0.0397) re-run as v3 | v3 identity from `main`'s source; v2's attempt root stays sealed |
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

### O — Operational failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| G-O-01 | `baseline_deliberating_v5` attempt 001 was killed mid-case by the host's memory pressure (an unrelated 2.2 GB application), and the resume then failed with `EvidenceIntegrityError: refusing to append to an existing event log without resume=True`. The kernel is right to refuse. What was missing is on this side: econevals and termsbench both rename an existing execution root to `<case_id>.superseded_<timestamp>` before re-running, and this family never did, so an interrupted case could not be re-run at all -- the campaign could only ever go forward from a clean tree | the resume's own error | $0.1657, recovered from the sealed tree by `_sealed_spend`, and one attempt of the identity | the supersede is added here, matching its siblings; the partial tree is kept rather than deleted, because partial evidence of a paid attempt is still evidence. Attempt 002 runs the same identity. Worth noting for the family's cost model: that one partial case cost 13x a complete v4 case, which is the deliberating condition showing up in the bill |
