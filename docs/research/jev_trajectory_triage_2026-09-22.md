# Can a decision model classify agency in trajectories? A Jev probe

**Date:** 2026-09-22
**Scope:** sealed trajectories of `procurement_allocation_unified_regret_recovery_v2`
(36 receipts, both arms), `housing_lemons_refusal_pilot_v1` (live episodes and
scripted reference tenants; bundle on PR #215), `datacenter_counteroffer_adoption_v3`
(18) and `datacenter_counteroffer_affordance_v1` (20)
**Model:** `typesafe/jev-1.13` on OpenRouter's decisions endpoint (typed choice
questions, calibrated probabilities)
**Status:** exploratory probe, not a campaign. Total spend about $0.15.
Scripts and saved answers: [`tools/examiner/jev/`](../../tools/examiner/jev/)

## Bottom line

The question was whether Jev can classify the actions that carry an agent's
own decision and alter the outcome, as distinct from inaction, copying and
procedure-following, better than rules alone. **It cannot.**

- *Did this action alter the outcome* is defined by the environment's own state
  transitions: award lines, accepted counters, holds that became leases, offer
  terms equal to the counter. A rule over those transitions is the definition.
  Jev approximates it at 96–99% on positive actions and never attributes an
  outcome to an omission (0 of 20 cases).
- *Was this a real decision or procedure* is the half rules cannot define, so it
  was Jev's only opening. Scripted reference tenants, which make no decisions,
  received the same agency labels as live models. The label follows the action
  type, not evidence of choice.

What Jev did add is reviewer value: it caught two defects in the rule labels
used to score it, applied one question set across three families with no
per-family code, and ranked trajectories in an order that tracked regret and
payoff without being told to look for either.

**Recommendation.** Measure agency as counterfactual sensitivity: at each
decision point the rules enumerate, replay the state under the family's scripted
reference action and take the outcome delta. A step carries agency when the
agent's action differed from the reference and the delta is material. Jev stays
optional as a cheap second reader over the rules.

## 1. Feasibility

| Question | Result |
|---|---|
| State sizes accepted | 2 KB action card, 7 KB trace with parsed actions and verdicts, 50 KB with observations; each 8/8 |
| Size limit | between 97 KB and 100 KB of state JSON, about 24k tokens |
| Known-answer facts (ending, sampled before award, feasibility) | 8/8 |
| Harder reading (awarded supplier, sample and quote counts) | 35–36 of 36, once the checker keyed award lines on `offer_id` |
| Cost and latency | about $0.00004 to $0.0006 per call, 0.3–1.3 s |

## 2. Trajectory-level triage (123 calls, $0.017)

Rules flag nothing in the procurement campaign: no invalid and no duplicate
actions, 35 awards and one deferral. Jev was asked for a primary issue, whether
a formal quote contradicted a verbal claim, and an attention level.

| Jev attention | receipts | mean regret to upper bound (USD) | mean actions |
|---|---:|---:|---:|
| low | 17 | 32.5 | 5.9 |
| medium | 17 | 28.5 | 7.7 |
| high | 2 | 66.2 | 7.5 |

Both high-attention receipts are control-arm, and no existing rule catches either:

- `ee8a2536b1` is the campaign's only deferral. The buyer quoted and sampled
  three suppliers, then deferred, stating that capacity and yields could not
  meet the service minimum. Margin −2.57 USD, regret 88.9, the campaign's worst.
  Its paired treatment run on the same case awarded feasibly (regret 45.4), as
  did all 35 other receipts.
- `7896d458d8` wrote after two sample rounds that the incumbent DS3231
  supplier's defect rate was too risky, requested a quote and sample from a
  third supplier, then awarded the incumbent anyway. Regret 43.4.

Jev labelled both "wasted actions", which is wrong for both. Its issue labels
are weak; its ranking is useful.

On the lemons live episodes (49) and the datacenter receipts (38):

| Question | Result |
|---|---|
| leases signed on lemon listings (zero, one, two or more) | 49/49 |
| which tenant signed a lemon it never inspected | 47/49; no false alarms, but only 1 of the 3 true signers found |
| confidence on correct vs missed answers to that question | 0.97 vs 0.58 |
| lemons attention vs live minus reference payoff (USD) | low +47.6 (5), medium −10.9 (19), high −78.8 (25) |
| datacenter: what the developer did after the counter; was anything executed | 38/38 once the rule was corrected (see §5) |

Both missed signers inspected one listing and signed a different one. A 0.7
confidence threshold routes exactly those two to a human.

## 3. Action-level agency (652 actions, $0.11)

Per focal action, Jev answered: agency (deliberate choice, procedural default,
copy or repeat, null or inaction), the action's effect on the outcome
(decisive, enabling, informational and unused, none), and whether replacing it
with the safest default would change the outcome. Rule labels came from award
lines and accepted counters, lemons holds, signings and walks, and datacenter
offer terms compared with the counter and with the developer's own previous
offer.

| Family | actions | Jev effect label agrees with the rule |
|---|---:|---:|
| procurement | 246 | 244 (99%) |
| housing lemons, 6 episodes | 318 | 306 (96%) |

- **Inaction and copying are separated cleanly.** All 201 passes were labelled
  inaction. All 30 datacenter offers that copied the counter or repeated the
  developer's own previous offer were labelled copy. The 35 opening offers,
  which copy the supplied starter terms as instructed, were labelled procedural.
- **Positive actions are linked to the outcome.** Every one of the 145 quotes
  and samples for later-awarded suppliers was labelled enabling, and 32 of the
  34 for suppliers not awarded were labelled unused. Most of the lemons
  disagreements are Jev being more causal than the rule: it called an
  inspection of a lemon followed by a switch to another listing enabling.
- **Omissions are invisible.** The 20 datacenter offers that resubmitted the
  developer's own terms instead of the counter were labelled copy, "no effect"
  and counterfactual "no", 20 of 20. None of those 20 receipts executed an
  agreement, while each of the 10 offers that copied the counter was followed
  by a signing.
- **The counterfactual is inconsistent on prerequisites.** Skipping a quote
  changes the outcome in 82 of 87 answers, skipping a sample in 15 of 92,
  although an award requires both.
- **Only 55 of 652 actions were both deliberate and outcome-moving.** In
  procurement these are 10 counters, 9 award decisions, 7 quote or sample
  choices and the deferral.

The labels do describe the treatment arm's mechanism. All 13 counters are
treatment-arm, all accepted, all decisive. The treatment award step became a
copy of its own `check_award` lines (9 copy and 8 procedural, plus 1
deliberate award that skipped the check), while control awards were 8
deliberate and 9 procedural. The worksheet moves the decision
from the award into the check and the counter.

## 4. The test that decides it: scripted tenants (97 actions, $0.02)

The same questions over the scripted `inspect_then_sign` and `sign_anything`
tenants in three worlds, beside the live model:

| Action | scripted policy | live model |
|---|---|---|
| inspect | deliberate 36/36 | deliberate 63/63 |
| offer | deliberate 27/43 | deliberate 27/37 |
| sign | procedural 18/18 | procedural 15/15 |

A policy that makes no decision gets the same labels as a model that does.
Across the 36 procurement receipts, the share of actions labelled deliberate
correlates with regret at 0.10, and the arms move in opposite directions.

## 5. Defects found in the rule labels

Jev's disagreements exposed two errors in the labels written to score it; both
are corrected in the scripts and the saved results and recorded in the
incident log (EX-J-01):

- Three datacenter receipts ended on an invalid first developer action, before
  any counter existed, and were scored "ignored the counter". Jev's "no counter
  seen" was right.
- Lemons holds were aligned one round late, because a commit phase's
  `post_state.round_index` already carries the next round. Seven ordinary
  passes were read as refusals of a held offer, and those seven states sent to
  Jev carried the tenant's hold from the following round. Jev labelled all
  seven inaction regardless.

## 6. Data observation

In the run-plan cells of `procurement_allocation_unified_regret_recovery_v2`
both arms carry the same buyer profile id. Per receipt, the arm is recoverable
only from the buyer's instructions digest (`3c8810960987` is the treatment
worksheet, `ab02902deb62` the control prompt). The bundle's result tables do
carry the arm.

## 7. Not yet tested

The deciding test in §4 ran on lemons, whose actions carry no text: a tenant
returns a decision and a listing id, and the lens holds no raw response. If
deliberateness is visible anywhere it is in the model's own words. Procurement
actions do carry the buyer's messages and stated reasons, and the family has a
scripted-policy campaign (`procurement_allocation_public_policy_baselines_v1`),
so repeating §4 there is the fair last check before dropping Jev from the
agency role entirely. How informative it is depends on whether the scripted
buyers write messages of their own.

## Reproduce

```bash
tools/examiner/rebuild.sh <AERead checkout> /tmp/examiner      # lemons needs the PR #215 run root
python3 tools/examiner/jev/jev_score.py /tmp/examiner           # §2 scores, no model calls
python3 tools/examiner/jev/jev_actions.py /tmp/examiner --truth-only   # rule labels, no model calls
python3 tools/examiner/jev/jev_actions_score.py /tmp/examiner   # §3 scores
```

Re-asking Jev needs `OPENROUTER_API_KEY` in the environment and gives
different samples; the saved answers in `tools/examiner/jev/results/` are the
ones reported here.
