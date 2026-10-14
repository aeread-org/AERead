# Cross-case failure taxonomy: definitions

Every case prices a subject's shortfall against a reference in its own units. This taxonomy splits that
shortfall into seven shared classes named by what happened in the sealed trajectory, never by an inferred
cause or a judge. It follows `aeread.gap_decomposition/0.1`: each shortfall unit is assigned to exactly
one class by a declared priority order, so the classes sum exactly to the shortfall (asserted to 1e-9 on
unrounded numbers in every script). Units where the subject beat the reference keep their negative sign
and count toward their class. Nothing was re-run and no model or provider was called.

## The classes

| # | Class | What happened |
|---|---|---|
| 1 | Information not acquired | Acted without information worth acquiring: signed an uninspected listing whose quality nothing it knew had settled; paid the premium or awarded the recorded supplier where the best informed policy tested a newcomer; decided before a required fact. |
| 2 | Acted contrary to information held | Had the information, or was shown it, and acted against it: signed a hold only a lemon's landlord offers, at a rent above a lemon's value; awarded a supplier its own test showed bad; stopped after one bad newcomer where another test was worth it; tested the wrong newcomer, tested where the odds and clock made paying best, or secured the recorded supplier before the test that was best first; a decision the answer key contradicts. |
| 3 | Worse terms | Agreed to a worse deal than one available, with no protocol error: a settled (verified) listing whose value less rent differs from the reference's; a worse award (supplier or quantity) on a qualified supplier; a clause set worth less to the pair than the best one; a wrong refund amount or method. |
| 4 | Commitment error | Signed what it should have refused, or refused what it should have signed: ended with no lease where the reference leased; signed a listing known sound above its value; walked away (defer) where an award or test was worth more; no deal where one was available; signed where no deal beats both outside options. Side level, not in any joint total: signed below its own walk-away point. |
| 5 | Interaction cost | Moves that cost and could not gain: redline fees after the opening; inquiries, counter-offers and pre-award checks (none can change anything in the pay-or-test pack); a request that can show nothing new; inspection spend above the reference's on a lease of the same value. |
| 6 | Procedure and format | An action the environment rejected or could not parse; a fact request the case rejects; a correct denial written with `method: null` where the key says `"none"`; a transaction not executed exactly once. |
| 7 | Operational | A cell with no measurement (typed missingness). Counted, never scored, never re-run. |

"—" in `summary.md` marks a class whose rule cannot fire in that case.

## Housing v14 (lemons price, outside demand)

**Shortfall.** Per cell (one world, one landlord arm): reachable reference net (`price_reference.inspect_lowball`,
replayed per cell and checked against the published `reference_net`) minus seat 0's net at the measure. The
published measure is `net_expected_response_odds` (`price_endpoint.score_cell`); the corrected one is the
HL-D-07 posterior (`tools/paper/hl_d_07/hl_d_07.py`, `score_cell` → `primary_corrected`).
A world's amount is the mean of its two arms, as the primary is; worlds missing an arm are left out with
their completed arm (Operational). Main pack, 260 worlds; strata `favourite_is_lemon` / `favourite_is_sound`
reported separately in `taxonomy.json`.

**Unit.** The cell. Its whole shortfall goes to the first rule that fires:

1. **Procedure and format**: seat 0 sent an action the environment did not accept (`action_parsed.ok` false or
   `action_legality_checked.legal` false for `seat_id == tenant_0` in the sealed events: GLM's
   `unavailable_listing` offers and one `malformed_commit`).
2. **Acted contrary to information held**: the signed listing's lemon probability, given what the measure counts as known, is 1
   (published: inspected lemon, or a hold below a sound landlord's floor in the leaky arm, or elimination;
   corrected: the full HL-D-07 posterior), **and** the rent is above a lemon's value (surplus at the measure < 0).
   A known lemon signed at a rent its lemon value covers is not a failure: the reference does exactly that in the
   leaky arm, so it is judged on terms (rules 4 to 6).
3. **Information not acquired**: the signed listing's lemon probability at the measure is strictly between 0 and 1.
   (In every such cell an inspection was worth its $25 fee: p × (1000 − (value if sound − rent)) > 25.)
4. **Commitment error**: no lease while the reference leased (split by whether seat 0 walked from a hold worth its
   rent); or a listing known sound signed above its value.
5. **Worse terms**: a settled lease whose value less rent differs from the reference's lease (either sign:
   negative when seat 0's lease is better, or when it leased and the reference did not).
6. **Interaction cost**: the remainder, i.e. the same lease value as the reference (or neither leased), so the
   difference is inspection spend.

For the reading only (not classes), each signed cell's gap is also split into listing choice at the landlord's
floor, rent above that floor, and inspection spend above the reference's (`reading_pieces_per_world`).

## Procurement pay-or-test (pay_or_test_v1, prompt v2 "finalquotes")

**Shortfall.** Decision loss: for every action, the best informed policy's value at that point
(`pay_or_test_reference.Reference`, backward induction over what the buyer has learned) less the value of the
action taken, summed over the episode; per world is the mean over 24 worlds. Each action is replayed through the
worktree environment and checked against `pay_or_test_report.score_trace` / `score_actions`.

**Unit.** The action. Zero-loss actions carry no class. An action with loss goes to the first rule that fires:

1. **Procedure and format**: the environment rejected it (priced as walking away).
2. **Commitment error**: a valid `defer`.
3. **Interaction cost**: `inquire`, `counter_offer`, `check_award`; or a quote/sample that can show nothing new.
4. A **quote or sample** that was not a best action:
   - on the recorded supplier where a best action tested a newcomer: **Information not acquired** if the episode
     never tests a newcomer (paid the premium); otherwise **Acted contrary to information held** (went to the recorded supplier
     after a bad newcomer, or secured it before the test that was best first);
   - on a newcomer where no best action tested a newcomer (paying was best), on the worse newcomer, or in a worse
     order: **Acted contrary to information held**.
5. An **award**, split by `score_actions`' own parts. If its timing part is positive (a further request was worth
   more): awarded before the awarded supplier's own required quote or sample, or the recorded supplier with no
   newcomer ever tested → **Information not acquired**; after a bad newcomer where another test was worth it →
   **Acted contrary to information held**. Otherwise its terms part: a supplier shown bad → **Acted contrary to information held**; one not yet
   qualified → **Information not acquired**; a qualified supplier at a worse choice or quantity → **Worse terms**.
   An award with both parts positive goes whole to its timing class (3 Luna actions; their terms part,
   $1.76 a world, would otherwise be Worse terms).
6. **Operational**: a failed cell (none: 24 of 24 for every subject).

The report's five parts map as: `requests` → 1/2 (by rule 4), `strays` → 5, `walk_away` → 4 or 6,
`award_timing` → 1/2, `award_terms` → 1/2/3.

## Data-center agreement (agreement case, development pack)

**Shortfall.** Joint value lost from `agreement.grade` ($k): the surplus the best of the 600 agreements makes
available for both true types, less the surplus realised, redline fees included. It splits exactly into
allocation + no deal + delay, checked per negotiation.

**Unit.** One part of one negotiation (allocation, no deal, delay), each to one class:

1. a negotiation that ended on an invalid move: its whole loss to **Procedure and format** (none occurred);
2. `no_deal_loss > 0`: **Commitment error**, labelled by the seat that walked (against the firm population this is
   usually the script walking from the model's last offer);
3. allocation loss in a world where no agreement beats both outside options: **Commitment error** (none occurred);
   otherwise **Worse terms**;
4. delay: **Interaction cost**, split by the seat that paid each redline fee (the integrator's opening redline is
   free);
5. `status != "ok"`: **Operational**.

Information classes cannot fire: the grade has no information step to read. Pairings: head to head on all 58
worlds (bundles `pair_dev`, `pair_reverse`, `pair_spread`, `pair_rest`), and each model against the drawn firm
population in each seat (`scripted_canary`, `scripted_rest`; the selective re-run `scripted_fill1` is not used).
Per world is the mean over a pairing's measured negotiations; "× firm" averages the model's two seatings per
world over worlds where both were measured. The published headline basis is the 52 deal worlds; all 58 are
also in `taxonomy.json`. **Side level:** `client_ir_violation` / `integrator_ir_violation` (a side's deal below
its own outside option) counted per model and seat, with who put the terms on the table. These are transfers
and never appear in joint value lost.

## Refund V2.1

**Shortfall.** Percentage points of cells unresolved against the answer key, mean per case then over the six
cases, from `evidence/refund/refund_v2_1_gap` on `origin/codex/refund-gap-analysis` (read with `git show`). The
bundle already assigns each unresolved cell to one part by the first thing that went wrong; the classes are a
mapping of those parts, recomputed from `cell_parts`.

| Published part | Class |
|---|---|
| `decided_before_required_facts` | Information not acquired |
| `wrong_decision` | Acted contrary to information held |
| `wrong_amount_or_method` | Worse terms |
| `re_requested_known_fact`, `requested_unknown_fact` | Procedure and format |
| `denial_method_null` | Procedure and format |
| `transaction_error` | Procedure and format |

Commitment error and Interaction cost cannot fire: one decision, no counterpart. Operational: no excluded cell
(120 of 120 per model).
