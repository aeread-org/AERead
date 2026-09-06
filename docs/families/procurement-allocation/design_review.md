# Procurement allocation v1: design review

**QC profile:** [qc.md](qc.md), which records these findings as gate statuses.

What the family measures well, what it does not measure at all, and the specific
defects behind each gap. Every claim below is backed by a number recomputed from
the tracked cases or the published evidence bundles; the command that produces it
is named so a reviewer can re-derive it.

The short version: the **feasibility** half of the design is measured and now
close to saturated. The **information and negotiation** half is largely
unmeasurable with the current worlds, and in three places the environment itself
makes it unmeasurable rather than the worlds being badly chosen.

---

## 1. Verbal claims are always true, so the provisional/binding distinction is procedural only

`ProcurementAllocationPlugin.step` answers an `inquire` by reading the supplier's
own `private_terms` and returning them verbatim under
`evidence_status: "verbal_claim"`. A verbal claim is therefore never *wrong*, only
*not award-eligible*.

The case README says listings and verbal claims are "provisional" and that only
formal offers and verified samples "can satisfy the award gate". Both are true of
the implementation, but a buyer that fully trusted every verbal reply would never
make an economic error. It would only be blocked by the gate. Nothing in the
family rewards verification, because there is nothing to catch.

This is the single largest gap. Real procurement risk is that the supplier's
claim is optimistic relative to what it will actually deliver, and that risk is
exactly what a sample is for.

**Fix.** Give `private_terms` an optional `verbal_bias` block: per-field offsets
applied only to `inquire` replies and to `listing`, leaving formal offers and
verified samples truthful. Default it to no bias so every existing case keeps its
digest. Then a world can make the cheap supplier claim a 0.99 yield and deliver
0.84, and sampling becomes worth its cost.

## 2. Information is too cheap to trade off

Inquiry costs $0.05, a quote $0.10, a counter $0.15, a sample about $0.40. Across
all 37 tracked cases, a buyer that bought *every* piece of information available
would spend a mean of **1.76%** of gross revenue (worst case 11.25%).

The regret decomposition over 101 feasible awards puts `information_cost_excess`
at **-1.5%** of total regret, and negative: models under-spend on information
relative to the oracle and it barely registers.

So the objective names information-acquisition cost, but the binding constraint is
the ten-action budget, not money. The family measures *action budgeting*, not
cost-benefit reasoning about information.

**Fix.** Either scale information costs to 10-25% of gross margin so the
trade-off binds, or drop the claim that the family measures information cost and
describe the action budget as the real scarce resource.

## 3. Price and MOQ negotiation have no headroom in almost every world

Per-supplier headroom across all 147 supplier records in the corpus:

| counterable term | mean headroom | suppliers with any headroom |
|---|---|---|
| unit price | 3.10% below base | 58 / 147 above 2% |
| payment terms | 12.7 days | 52 / 147 |
| refund window | 6.0 days | 52 / 147 |
| MOQ | **0.1 units** | **2 / 147** |
| return freight | n/a | by flag |

A typical price floor sits one or two cents under the quote, so a price counter on
a 20-unit line is worth about $0.40. The design advertises five negotiable terms;
in practice only payment terms ever carries real money, and only in the worlds
built for it.

The sharpest version of this: the *one* world with genuine price and MOQ headroom
is `negotiated_moq` (price 1.60 to 1.30, a 19% cut; MOQ 30 to 20), and it is the
only world **no treatment ever improved** — unchanged at about $12.66 per row
across V4, worksheet V1, worksheet V2, and the pre-award check. Where negotiation
would actually pay, no model has ever taken it.

**Fix.** Set floors as a policy across the generator (say 10-25% below base) rather
than per-world by hand, and give MOQ real headroom wherever a world claims to test
it.

## 4. A rejected counter teaches nothing

`_counter_is_accepted` returns a bool. On rejection the supplier replies
`"Counter rejected; <offer> remains available until day N."` — no indication of
which of the up-to-five proposed terms was out of bounds, or by how much.

This is why worksheet V1 packed all five fields into every one of its 82
proposals and had 50 rejected: with no feedback, a buyer cannot bisect the limits
within a ten-action episode. Worksheet V2's single-field rule was a workaround for
missing feedback, not a discovery about negotiation.

**Fix.** Name the violated field in the rejection, or return the nearest
admissible value. Either makes negotiation learnable inside one episode without
revealing the whole private limit set.

## 5. A deferral counts as feasible in the guarded metric

`ProcurementAllocationPlugin.outcome` sets `"feasible": terminal["reason"] == "deferred"`
for the non-award branch. So `outcome["feasible"]` is **True** for a deferral, and
every campaign's preregistered feasibility guardrail is computed on that field.

A treatment that makes the model defer more can therefore satisfy the guardrail
while earning nothing. The pre-award check produced 15 deferrals and still passed
its guardrail at +0.389. `feasible_award` exists as a separate diagnostic and is
the quantity the transfer campaign correctly used, but it is not what the
confirmation rules guard.

**Fix.** Guard `feasible_award`, and report terminal feasibility as a diagnostic.
This is a one-line change to the confirmation rule in each campaign, and it should
be made before any published claim leans on the guardrail.

## 6. The episode is decided early, and nothing gives feedback until the end

Analysis of all 15 deferrals in the pre-award-check run: in **every** case, no
feasible award was reachable from the terminal state's offers and samples, so the
deferral was the correct action. Yet in every case the oracle had a positive
feasible award, ranging from $103 to $156.

Stronger still: replaying every prefix of those 15 trajectories, there is **no
action index at any point** in any of them where a feasible award could have been
constructed from the offers and samples the buyer had obtained. The buyer never
assembled a qualifying supplier set at all, even though the oracle needs only
five to nine actions in these worlds.

So the deferral was correct at every step, and the buyer was never close. The
pre-award check reports the dead end accurately, but it evaluates award lines
against offers *already obtained*. It cannot say "the set you are buying
information about cannot produce a feasible award; quote someone else."

**Fix.** This is a design choice to make explicitly, not a bug. Either accept that
the family measures irreversible early commitment and say so in the case README,
or add a cheap early signal: let `check_award` accept listings as hypothetical
offers, so a buyer can ask "could this supplier set ever work" before spending
four actions finding out that it cannot. The second is the change that would make
the deferrals informative rather than merely correct.

## 7. The oracle solver is exponential, which silently constrains what worlds can exist

`solve_full_information_upper_bound` enumerates the full cartesian product of
(supplier x mode x admissible quantity). A world with four suppliers at
`moq=10, capacity=40, order_step=2` yields 16 quantities x 2 modes per supplier,
about 1.2M evaluations, and hangs for minutes. This was hit while authoring the
holdout panel in this branch and worked around by coarsening the order step.

The consequence is that fine-grained quantity worlds — exactly the ones that would
make the split and rounding dimensions interesting — cannot be authored, and the
limit is invisible: the generator simply appears to hang.

**Fix.** Solve per component independently (the objective is separable across BOM
components given the kit-completion floor), or branch and bound on landed cost.
Failing that, assert a budget on the enumeration size at generation time so an
author gets an error instead of a hang.

## 8. Labeled supplier identifiers leak their own private advantage

Identifiers such as `ds3231_at24c32_terms_flexible`, `switch_reliable`, and
`low_sticker` name the private property that makes them the right or wrong
choice. Worksheet V2 measured the size of this: on labeled worlds all three seeds
captured the payment-terms saving, and on the economically identical opaque
mirror only one of three did, because the buyer could no longer tell the
terms-flexible supplier from the terms-fixed one.

The blinded and opaque mirrors exist precisely for this reason, and they work. The
defect is that labeled results are still reported as a primary surface and
averaged with opaque ones.

**Fix.** Report opaque as primary and labeled as the name-leakage diagnostic, or
rename labeled suppliers to neutral trade names so the labeled surface tests
presentation order rather than embedded answers.

## 9. Headroom is exhausted on the panels that treatments target

Of the 53 feasible purchase awards in the pre-award-check run, **23 matched the
full-information bound exactly** (zero regret). On the targeted Qwen holdout, all
14 feasible GLM awards matched the bound exactly.

Once a model reaches a feasible award on these worlds, there is usually nothing
further to measure. That is the signature of a panel whose search problem has
collapsed, and it is why three prompt treatments in a row could only move
feasibility.

**Fix.** Worlds need a feasible frontier with several distinguishable points, not
one optimum plus a set of violations.

## 10. Operational: a transient 429 on an unscored canary seals an attempt root

The canary is write-once. A rate limit on the zero-cost admission probe therefore
permanently disqualifies the attempt root and forces a fresh one, which is correct
for scored rows and disproportionate for a probe that costs nothing and produced
no measurement. This happened twice while running the confirmatory holdout in this
branch, and the same pattern sealed risk-gate attempts V1 and V4.

**Fix.** Let a canary rejected with a typed transient condition be re-probed
within the same attempt, recording every probe, while keeping any *scored* row's
transient failure sealing as it is today.

---

## What is measured, honestly

| design dimension | status |
|---|---|
| Award feasibility under MOQ, capacity, order step, deadline, cash, service minimum | measured, near-saturated |
| Provisional vs binding authority | measured as procedure only; no economic content (defect 1) |
| Sampling and yield | measured |
| Working-capital / payment-terms negotiation | measured for one lever, and only on labeled surfaces (defects 3, 8) |
| Price, MOQ, refund, freight negotiation | not measured (defects 3, 4) |
| Information-acquisition trade-off | not measurable (defect 2) |
| Deferral as a priced outside option | partly; `defer_value_usd` is 0 in most worlds and the metric miscounts it (defect 5) |
| Cross-model generalization | GLM and Qwen 235B only |

Defects 1, 2, 3, and 4 are the ones that block the family from measuring the
objective it declares. Defects 5 and 7 are correctness issues that should be fixed
regardless. Defects 6, 8, 9 are scoping decisions that should be stated in the
case README rather than left implicit.

## 11. Abort-on-first-failure makes completion probability decay exponentially in panel size

Every campaign in this family sets `abort_on_operational_failure=True`, so one
typed operational failure ends the whole attempt and every remaining row becomes
unattempted. The kernel's default is `False`, and the family's own doctrine says
operational failures "remain typed missingness"; the campaign policy converts a
single missing row into 143 unattempted ones.

The cost of that choice is a function of panel size. A row seals only when four
consecutive attempts on one action fail, so at the 17.6% per-call failure rate
measured on GLM Parasail on 2026-09-05, with about seven calls per row:

| panel | probability an attempt completes |
|---|---|
| 18 rows | 88.6% |
| 36 rows | 78.5% |
| 72 rows | 61.6% |
| 96 rows | 52.5% |
| 144 rows | 38.0% |

The 72-row development campaigns completed because they are small. The 144-row
confirmatory panel and the 144-row risk-gate factorial are the two largest in the
family and are precisely the two that have never completed — the risk-gate
factorial across V1 to V4, and the pre-award confirmatory across seven attempt
roots on one evening.

The scientific goal is real: transient availability must not silently choose which
rows survive. But that goal is met by *recording* a typed missing row and requiring
the analysis to treat it as missing, which the publication path already does. It
does not require discarding the other 143.

**Fix.** Let an attempt continue past a typed operational failure, sealing that row
as typed missingness, and make eligibility depend on a declared missingness ceiling
rather than on zero failures. Keep the current abort for untyped or contract
failures, where continuing really would be unsound. Without this, panel size is
capped by route reliability rather than by statistical need.

---

## Status of the fixes

| defect | state |
|---|---|
| 1 verbal claims always true | **fixed** — `verbal_bias`; `information_v1` proves it bites |
| 2 information too cheap | **addressed in worlds** — `information_v1` prices it at 15-48% of gross |
| 3 no negotiation headroom | **addressed in worlds** — floors 15-30% below quote, real MOQ headroom |
| 4 rejected counter teaches nothing | open; needs an environment change to the counter reply |
| 5 defer counts as feasible | **fixed** — `feasible_award` published per row and guarded in the new confirmatory rule |
| 6 episode decided early | open by design; the fix is a hypothetical-offer check, recorded not implemented |
| 7 exponential oracle | **fixed** — bounded with a named error |
| 8 labeled ids leak the answer | open; opaque mirrors exist and should become the primary surface |
| 9 headroom exhausted | **addressed in worlds** — `information_v1` and `confirmatory_v2` |
| 10 canary sealed by a transient 429 | open; hit repeatedly while running the holdout on 2026-09-05 |
| 11 abort-on-first-failure caps panel size | open; the two 144-row panels are the two that have never completed |

Defects 4, 6, 8, 10, and 11 are the remaining work. None of them blocks the panels
above; each is a bounded change with the fix already described in its section.

