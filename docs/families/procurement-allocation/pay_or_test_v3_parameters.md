# Pay or test v3: parameter revision (specification)

**Status:** a specification written at the owner's ruling of 2026-10-19 ("procurement don't run, as we need to tweak
those param that does not vary"). Nothing here is declared, built or run. It sits beside the
[v3 design note](pay_or_test_v3_design_note.md), whose diagnosis of v2 still holds: the first test is the bottleneck
(P-D-27). A plan follows only after the checks in Section 3 pass offline and the owner approves.

## 1. Remove what no choice depends on

v2's values are from `pay_or_test_v2_case_matrix.py` (branch `codex/procurement-pay-or-test`).

| Term in v2 | Why it carries no decision | v3 |
|---|---|---|
| Cash budget, $3,000 | Never binds: v2 raised it from $2,500 so it could not, and the reference refuses a world where it could (`pay_or_test_reference.py`, "cash budget could bind") | Dropped from the brief and the payoff. The generator keeps the check as an invariant, not a stated rule |
| Shipping, $0.60 a unit | The same for every supplier | Folded into each listed unit price (a landed price) |
| Financing, 12% a year (15 days on the order, 10 on the recovery) | About 0.5% of the order value; scales every price alike | Dropped |
| Counter-offer, $1 and a day | Can only lose: every limit equals the quoted value, so quotes are final. Under the second brief it cost every subject $0 (paper Table E.5) | Removed from the action set. Bargaining is measured in Housing and Data center |
| Inquiry, $1 and a day | Can only lose: every seller claims on-time 0.97 and yield 0.97 whatever its type | Removed from the action set |

**Not removed:**
- *Recovery of defective units* (0.9 of the price on the share that fails inspection). It is the only yield-dependent
  term of a valid award.
- *The free award check.* It costs nothing and spends an action, and its use is part of the action-budget decision.

## 2. Add two features from the record

From the maintainers' own 1688 sourcing record (`~/analysis/aeread-paper/procurement_calibration/`, inputs hashed in
`INPUT_SHA256.txt`; paper Section 5.1):

| Feature | The record | v2 | v3 |
|---|---|---|---|
| **Quotes may go unanswered** | 236 requests went to 28 suppliers; 9 suppliers quoted (32%) | Every quote request is answered | Each newcomer quote request is answered with probability *a*, drawn independently per request. An unanswered request costs its fee and its day and reveals nothing. The recorded supplier always answers, because it has a relationship. The default is *a* = 1/3; see Section 4 |
| **Price gaps from the record** | Over 56 recorded-against-unrecorded pairs (cap 3), the newcomer was cheaper in 50%; its median discount off the recorded seller was −0.8% (IQR −35% to +46%). The cheapest-to-dearest gap had a median of 39% (IQR 23% to 57%), robust across caps 2 to 5 (49% to 51% cheaper) | Newcomers are always cheaper, by 2–8% or 24–40% | Each newcomer's price relative to the recorded supplier is drawn from the 56 recorded pairs. A newcomer is then dearer in about half of the candidate worlds; admission (Section 3) keeps a world only where testing pays for some newcomer |

The two additions put the difficulty where v2 was too easy at the top, where Sol and Opus gave up $1–5 of $451:
- unanswered quotes make days the scarce resource, so it matters whether to ask several suppliers at once or wait;
- two-sided price gaps mean a newcomer is not always worth testing.

## 3. Checks before any model plays

Each check is declared in the v3 plan before it runs, and each is scripted, with no provider call.

1. **The reference stays exact.** The best informed policy gains one supplier state, asked and not answered, so the
   status space grows from 5⁴ to 6⁴. Answers enter as chance nodes. A test holds the policy's value equal to a
   Monte Carlo average of the policy over the answer draws, within its standard error, on every admitted world.
2. **The case is not one-step arithmetic.** The one-step rule loses at least $10 on every admitted world, and at
   least $15 on average over the pack (v2's admission margins, `MARGIN_USD` and `MEAN_MARGIN_USD`).
3. **Testing is made more attractive, not less** (the other session's condition, 2026-10-19). Always paying the
   premium must lose more on the v3 pack than on v2's pilot pack ($69.24 a world). The share of admitted worlds
   where the best policy's first action is a newcomer test must also not fall below v2's.
4. **Brief and environment agree.** Every rule the brief states (answer odds, landed prices, the action set) is checked
   against the environment by a test, as in the data-center agreement case.
5. **Free baselines.** The pay-the-premium, one-step, two-test and cheapest-until-found rules run through the kernel on
   every admitted world, and their receipts replay.

If check 2 or 3 fails, the parameters are revised and the checks rerun before any plan is written. Whether
*subjects* then take the first test is the v2 failure (P-D-27), and no parameter can settle it offline. The design
note's route A decision rule applies to a small paid pilot after the owner's approval: each subject quotes or samples
a newcomer in at least 75% of the plays where the best policy tests, and the sized world count is at most 96.

## 4. Choices for the owner

1. **Answer probability:** a single 1/3, from the record (recommended), or a per-world draw from {0.2, 1/3, 0.5}. The
   draw adds a stratum and needs a larger pack.
2. **Does the recorded supplier always answer?** Recommended yes. A shared answer rate would make paying the premium
   uncertain too, which mixes "pay or test" with "who answers".
3. **Inquiry:** removed (recommended), or made a cheap noisy signal beside the exact quote and sample, which adds a
   third information source the reference must model.
4. **Price ratios:** drawn from the 56 recorded pairs (recommended), or from a fitted distribution. The fit smooths a
   small sample but adds a modelling choice.

## 5. What v3 keeps from v2

- The supplier types (good, late, poor) and the cohort record of each seller kind, with its same-source correlation.
- The kits owed, revenue and shortfall penalty.
- Order sizes and minimum order.
- The deadline clocks and the action budget of 10.
- Exact samples, and a quote that reveals the on-time rate.

The reported packs (v1, and v2's pilot) stay as published. v3 is a new identity.
