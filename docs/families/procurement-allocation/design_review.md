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

## 12. One digest for two kinds of parameter turns every operational change into a new campaign

The SOP explicitly permits an operational change to keep its campaign identity:
"a purely mechanical correction may be published only when both the original and
corrected artifacts remain traceable and the scientific contract is unchanged."
The implementation does not allow it.

`plan_sha256` hashes the scientific and operational parameters together. The
frozen plan contains `world_pairs`, `inference_seeds`, `prompts`, the route, and
the analysis rule, and in the same object it contains
`abort_on_operational_failure`, `batch_size`, `max_parallel_cells`, and
`retry_policy`. Change a retry delay and the digest moves; the comparison then
raises "recorded campaign plan differs from frozen plan"; the only way forward is
a new campaign identity.

The cost is measurable. Confirming one hypothesis on 2026-09-05 took four
campaign identities in about an hour. Exactly one change was scientific, the
guarded metric moving from terminal feasibility to `feasible_award`. The other
three were retry pacing, process exit codes, and missingness tolerance, all of
which the SOP would have allowed under one identity. The same pressure explains
the shape of the tree: the family carries 11,439 lines of campaign and analysis
code around a 1,480-line environment, and the four newest campaign modules are
1,027, 1,011, 1,215, and 1,164 lines of near-identical code, because a fork is
the cheapest way to obtain a new digest.

**Fix.** Compute two digests. `scientific_contract_sha256` covers cases, seeds,
prompts, route identity, the analysis rule, and the guarded metric.
`operational_sha256` covers retries, batching, parallelism, ceilings, and the
missingness policy. Comparison verifies the scientific digest and reports
operational drift as a recorded field rather than an invalidation. A campaign
identity changes only when the scientific digest changes.

**Migration note, and why this was not done on 2026-09-06.** `plan_sha256` is
verified by recomputing the hash of the plan with that one key removed, so
*adding any key* to the plan changes the recomputed value and fails every frozen
plan check, including the confirmatory run in flight at the time. The split
therefore cannot be applied additively. It needs a versioned plan schema in which
old plans keep validating on `plan_sha256` alone and new plans carry both
digests, which is a kernel change rather than a family change and belongs with
the shared-runner contract work.

## 13. Eligibility cannot be checked without seeing the effect

`build_confirmatory_comparison` returns one object holding the integrity checks,
the eligibility verdict, and the effect estimates. There is no way to ask whether
a run is eligible without receiving its efficacy in the same value. Gate 5
forbids early efficacy inspection and the campaign plan declares
`no_early_efficacy_stopping`, yet the only available API makes the two
inseparable.

This was hit on 2026-09-06. The confirmatory holdout was checked for eligibility,
failed on the per-arm missingness ceiling, and the effect estimates were visible
in the same output. Nothing was changed as a result, and the plan is frozen, so
no harm followed; but the protection was procedural rather than structural, and
a procedure that depends on a reader ignoring a value already in front of them
is not a control.

**Fix.** Split the call. `assess_eligibility(run_root)` returns integrity checks,
missingness, and the verdict, and nothing derived from outcomes. `build_comparison`
takes an eligibility result and refuses to compute effects unless it passed.
Publication already refuses an unqualified run; the same discipline belongs one
step earlier, where a human looks.

## 14. Nothing checks that a holdout leaves the control room to fail

Gate 1 admits a world on validity, distinctness, a positive reachable bound, and
digest disjointness. None of those detects a world the control already solves.

The confirmatory holdout authored in this branch is the demonstration. Its twelve
worlds targeted exactly the failure modes the pre-award check removes, and every
Gate 1 check passed: distinct seeds, distinct economic-world digests, positive
bounds reachable inside the action budget, paired surfaces. The V4 control then
scored 97% feasible awards on the labeled surface against 56% on the development
panel, and won every completed row in 7 of 12 worlds. The panel is uninformative
by construction and cost a full 144-row run to discover.

A holdout must preserve the *difficulty* of the panel it holds out from, not only
its themes. Difficulty is a property of the control's performance, so it cannot
be established by inspecting the world definition; it has to be measured.

**Fix.** Add a Gate 1 admission criterion: before a panel is frozen, run the
frozen control -- or, more cheaply, the deterministic policy baselines that
already exist -- across the candidate worlds, and admit a world only when the
control fails a declared minimum share of its rows. Publish the measured control
rate per admitted world as part of the panel manifest, so a reader can see the
headroom the panel offers before any treatment is run. The same measurement
answers design-review defect 9, since a panel whose control saturates and a panel
whose subject reaches the bound exactly are the same failure seen from the two
ends.

## 15. The biased channel is one no policy reads, and financing cannot be material at this scale

Two findings from a $0.0153 control screen on 2026-09-06, both of which say a
dimension was added without checking that the toy can carry it.

**The `verbal_bias` fix is unreachable.** The screen recorded **zero `inquire`
actions** across a whole panel: the frozen procedures instruct the buyer to
request a formal quote directly rather than inquire first, and formal quotes and
verified samples are truthful by construction. A supplier that overstates only
when asked verbally is lying into a channel nothing listens to. Defect 1 is
therefore **reopened**: the mechanism is correct and tested, and it is inert. The
bias must sit on the **listing**, which every policy reads, with truth available
only through a quote or a sample.

**Even reachable, the budget defeats it.** Four suppliers and ten actions means
quoting all four, sampling the two chosen, and awarding costs seven actions. A
buyer can afford to verify everything, so it never has to trust a claim.
Information cost cannot bind while full verification fits inside the action
budget, and pricing actions in dollars does not change that, because dollars are
not the scarce resource. Panels must have more suppliers than the budget can
verify.

**Working capital cannot be material at this scale.** The term models a real cash
conversion cycle and `payment_terms_days` is genuinely private, so it could be an
information dimension. But cost scales with order value times rate times days,
and this family has $50 lines against roughly 70% gross margins. At the realistic
45-day, 12% setting the term is worth about $0.72 against margins of $100 to
$180; 89 of 95 cases sit there. The six cases where it matters reach 150% and
200% annual financing, which is not a business. Either the toy's orders grow and
its margins thin, or the term goes.

**Fix.** Before adding an economic dimension, check that the toy's own scale makes
it material at plausible parameters, and that the channel carrying its
information is one an evaluated policy actually reads. Both checks are cheap and
neither was performed.

## 16. A control-only headroom screen admits floored worlds

Defect 14 established that a panel must be admitted against a measured control
rate. The screen built for it measures one policy, so it detects saturation and
nothing else, and a world that no policy can solve passes it *because* the
control fails there.

The due-diligence panel is the demonstration. Its screen found the control
failing 3 of 6 worlds and admitted the panel. Running both arms showed 2 worlds
saturated, 2 floored where both arms score zero, 1 where both arms land on the
same rate, and **1 world able to express a difference**. All three worlds the
screen credited as headroom were floored or non-discriminating.

A world is informative only if some policy can succeed and some policy can fail.
That is a property of at least two policies, and no single-policy measurement can
establish it.

**Fix.** Screen two policies with different failure modes -- the frozen control
and the deterministic greedy baseline are already available and cost nothing
extra -- and admit a world only when they separate. Publish both rates per
admitted world. This costs one additional screening pass, against the two panels
and roughly $1 of runs that single-sided screening has now failed to protect.

---

## 17. Validity and difficulty are the same knob, so the interior is nearly empty

The recalibration of the due-diligence panel on 2026-09-06 was meant to fix
defect 16 by putting one trap per component instead of two, so that a single
recovery fits the action budget and a second does not. It did exactly that, and
the panel still failed admission -- for the opposite reason.

Measured at four seeds per world, with three deterministic public-observation
baselines replayed offline:

| world | control award rate | any baseline wins | margin | bound | regret |
|---|---:|---|---:|---:|---:|
| trap_high_a | 100% | no | 167.54 | 167.54 | 0.00 |
| trap_low_a | 100% | no | 147.90 | 148.40 | 0.50 |
| trap_low_b | 100% | no | 139.98 | 140.48 | 0.50 |
| trap_mid_a | 100% | no | 150.26 | 150.26 | 0.00 |
| trap_mid_b | 100% | no | 167.76 | 167.76 | 0.00 |
| trap_split_components | 100% | no | 148.95 | 149.45 | 0.50 |

Every world is saturated, and none is trivial: the baselines lose everywhere, so
verification is genuinely required and the control genuinely performs it. The
panel is not badly built. It is as well built as this parameterisation allows.

The reason is structural. `validate_payload` rejects a case whose
full-information optimum does not beat deferring, and that optimum is computed
under the action budget. Below a threshold budget the world is illegal; at or
above it the world is legal *and* a fixed procedure of quote, sample, award
attains the bound. For every world in this panel the threshold is five actions:

| budget | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|
| legal in all six worlds | no | no | yes | yes | yes |

So the same quantity that decides whether a world may exist also decides whether
it is hard. A budget sweep over the legal interior, three seeds per cell, says
precisely how sharply:

| world | budget 5 | budget 6 | budget 7 |
|---|---|---|---|
| trap_high_a | 3/3 | 3/3 | 3/3 |
| trap_low_a | 0/3 | 0/3 | 3/3 |
| trap_low_b | 0/3 | 0/3 | 3/3 |
| trap_mid_a | 3/3 | 3/3 | 3/3 |
| trap_mid_b | 3/3 | 3/3 | 3/3 |
| trap_split_components | 0/3 | 0/3 | 2/2 |
| **panel award rate** | **50%** | **50%** | **100%** |
| **mean regret** | $73.47 | $73.56 | $0.73 |

Read carefully, because the panel row is misleading on its own. A 50% award rate
at budget 5 looks like healthy headroom. It is not headroom; it is a mixture of
three worlds that always succeed and three that always fail. **No world takes a
fractional value at any budget.** Every cell is 0/3 or 3/3.

That distinction decides what a panel can measure. Headroom within a world means
a treatment can raise the probability of success there. A mixture across
deterministic worlds means a treatment can only move a world bodily across its
own step, and when it does, every seed in that world moves together. The
quantity a treatment must shift is therefore the number of worlds flipped, out
of six -- not the number of rows, whatever the row count suggests.

Two further readings from the same table. Budgets 5 and 6 are identical in every
cell, so the extra action bought nothing at all and the step for the hard worlds
sits between 6 and 7. And mean regret moves a hundredfold across that step,
because a world that fails forfeits its entire margin rather than part of it,
which is what makes the metric a step rather than a slope.

So the earlier claim that there is no interior band needs narrowing, and the
narrower version is worse rather than better. A panel-level interior does exist
and is easy to hit: budget 6 gives a 50% rate. A *within-world* interior does
not exist anywhere that was measured. Panels tuned on the panel-level number
will look well calibrated and still carry an effective sample size of six.
Defects 14 and 16 are both instances of this, and it explains why they kept
recurring under tuning: each new panel was landing on one side of a step that
the legality rule makes sharp.

The fix is not another panel. It is to break the coupling, by making the optimum
depend on something the budget does not buy -- noisy samples, so that evidence
accumulates instead of resolving in one draw, and a stopping decision exists.
The [positioning note](positioning.md) already lists noisy sampling as required
to make its questions 1 and 2 real. This measurement upgrades that from a
desirable addition to a precondition: until sampling is stochastic, award
feasibility is a deterministic function of the world and the budget, and no
prompt treatment can move it within a world.

## 18. The trajectories carry no seed variance, so replication is not measuring what it appears to

Across the same 24 rows, `contribution_margin_usd`, `regret_to_upper_bound_usd`,
`completed_kits`, and `action_count` are **constant within every world at all four
seeds**. Only token counts and wall-clock time vary. The model emits the same
action sequence every time. The budget sweep reproduced this independently at
three different seeds and three budgets: all 53 cells are 0/3 or 3/3, with no
fractional value anywhere.

This matters beyond tidiness. Variance estimates, the pilot that sizes them, and
the cluster bootstrap over economic worlds all assume seeds are draws from a
distribution. Here the within-world variance is exactly zero, so a seed is a
repeat, not a replicate, and any confidence interval computed across seeds is
narrower than the truth by construction. The effective sample size of a panel is
its number of worlds, not its number of rows.

Two consequences, both cheap. Seed count should not be used to buy precision on
this family until sampling is stochastic. And the variance pilot should report
the within-world variance it actually observes, and refuse to proceed when it is
zero, since a zero there means the design is deterministic rather than that the
measurement is precise.

## Status of the fixes

| defect | state |
|---|---|
| 1 verbal claims always true | **reopened** — `verbal_bias` works but is unreachable; no policy inquires, so the bias must move to the listing (defect 15) |
| 2 information too cheap | **addressed in worlds** — `information_v1` prices it at 15-48% of gross |
| 3 no negotiation headroom | **addressed in worlds** — floors 15-30% below quote, real MOQ headroom |
| 4 rejected counter teaches nothing | open; needs an environment change to the counter reply |
| 5 defer counts as feasible | **fixed** — `feasible_award` published per row and guarded in the new confirmatory rule |
| 6 episode decided early | open by design; the fix is a hypothetical-offer check, recorded not implemented |
| 7 exponential oracle | **fixed** — bounded with a named error |
| 8 labeled ids leak the answer | open; opaque mirrors exist and should become the primary surface |
| 9 headroom exhausted | **addressed in worlds** — `information_v1` and `confirmatory_v2` |
| 10 canary sealed by a transient 429 | open; hit repeatedly while running the holdout on 2026-09-05 |
| 11 abort-on-first-failure caps panel size | **fixed** — typed missingness with a declared ceiling; took the run from 24 rows across seven attempts to a single completing attempt |
| 12 one digest for scientific and operational parameters | open; needs a versioned plan schema, so it is kernel work, not a family change |
| 13 eligibility and effect returned together | open; split into `assess_eligibility` and a comparison that requires it |
| 14 no check that a holdout leaves the control room to fail | open; cost a full 144-row run to discover, and is the reason the confirmatory holdout is uninformative |
| 16 control-only screen admits floored worlds | open; the due-diligence panel had 1 of 6 worlds able to express a difference |
| 15 biased channel unread, and financing immaterial at this scale | open; found by a $0.0153 screen that also saturated the information panel 7 of 7 |
| 17 validity and difficulty are the same knob | open, and it subsumes 14 and 16; a budget sweep found every world at 0/3 or 3/3, so the panel-level 50% at budget 6 is a mixture and not headroom |
| 18 no seed variance within a world | open; margin, regret and action count are identical at every seed across two independent runs, so seeds are repeats and not replicates |

Defects 4, 6, 8, 10, and 12 through 14 are the remaining work, and defects 17
and 18 reorder it. Defect 17 is now the most urgent, because it explains why 14
and 16 kept recurring: panels were being tuned across a step that the
environment's own legality rule makes sharp, so each new panel landed on one
side or the other. Tuning cannot fix that, and two panels and roughly $0.30 of
screening were spent establishing it.

The unblocking change is noisy sampling. It converts a one-draw settlement into
an accumulation, which creates the interior band defect 17 says is missing and
the within-world variance defect 18 says is absent, and it makes the stopping
question in the positioning note real rather than nominal. Until it lands, no
result from this family should be reported as a treatment effect on award
feasibility, and the existing evidence keeps its narrower label: award
feasibility under declared constraints.

