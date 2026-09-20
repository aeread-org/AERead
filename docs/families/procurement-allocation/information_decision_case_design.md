# Procurement: decisions under costly, incomplete information

Status: **local design with twelve numerically checked decision points**. No new
model calls, full-episode world generator, registered adapter, frozen campaign or
model-performance result is included. These fixtures are calibration examples,
not twelve independent markets. Phase 2 evidence remains unchanged.

The target is choosing a profitable sequence of information purchases and orders
under uncertainty: which supplier to investigate, how much evidence to buy, when
to commit, how much to buy from whom, and when to stop. `defer` is one available
action. Observing a deferral is neither a pilot admission condition nor a success
metric by itself.

The detailed strategy guidance accepted by the user stays available to every model.
Difficulty must come from the economics and uncertain evidence after that guidance,
not from withholding instructions or making supplier identifiers harder to copy.

## What the new cases must establish

Phase 2 demonstrated replay and useful allocation behavior, but its two traps
advertised market-wide infeasibility and its two split worlds shared almost the
same economic structure. The completed run used GLM 5.3 Flash, not Gemini. The
[audited result](phase2_timeout_recovery_results.md) is retained on its original
contract; this design changes the measurement rather than reinterpreting it.

Every scored case family should have a matched variant where a changed economic
fact reverses the best decision. This prevents a policy such as "always defer",
"always sample twice", "always buy the cheapest", or "always split" from passing
the entire family. Matching is an authoring control, not independent replication.
Changing only names, catalogue order, revenue by a few cents, or sample seeds
does not count as adding an economically distinct market.

## Six case families and twelve checked examples

All amounts below are synthetic USD. Each example starts at a declared legal
decision point; quotes and samples already acquired are explicitly stated in the
fixture. Values are expected *incremental* contribution from that point. Sunk
research remains in full-episode accounts but cancels when ranking next actions.
The fixture file contains evaluator answer keys and must never be sent as a model
observation.

| Family | Concrete decision | Matched change and verified reversal |
|---|---|---|
| **1. Choose the next supplier** | Qualified incumbent earns $10. A's quote yields $80 with probability .2, otherwise -$20; B yields $22 with probability .7, otherwise -$6. Both prospects already have samples. Only one quote plus a final decision fits. | Contact costs A=$3, B=$1: quote A, expected value **$21**, versus B **$17.40**. Increase A's contact cost to $8: quote B; A is now worth **$16**. A's lower unconditional expected margin does not make it a worse information purchase. |
| **2. Buy another sample or commit** | Both options are qualified. Incumbent earns $12; candidate earns $40 in a good lot and -$20 in a bad lot. A further QC screen costs $2, with 80% sensitivity and specificity. | With posterior P(good)=.5, repeat the screen: **$18**, versus stopping at **$12**. With P(good)=.9, buy the candidate now: **$34**, versus screening **$32**. More testing is not always better. |
| **3. Search consumes the deadline** | Qualified incumbent earns $16. A sampled alternative needs a one-day quote costing $1; its margin is $36 with probability .4, otherwise -$8. Delivery takes one further day. | With one day left, award the incumbent: **$16**; the quote would expire both opportunities and leave **-$1**. With two days left, quote the alternative: **$23** expected value. |
| **4. Walk away after evidence, or continue** | Two investigated suppliers were unprofitable. A remaining sampled prospect needs a $4 quote. It could yield $30, otherwise -$10. No universal price or delivery floor proves impossibility. | If shared market conditions reduce its posterior chance of profit to .1, defer: **$0 additional value**, versus search **-$1**. If it is independent and retains probability .4, search: **$8** expected value. The same two bad observations do not justify the same action under different dependence structures. |
| **5. Split only when its total cost pays** | Need 20 usable units, revenue $5/kit. Qualified A: $2/unit, lots of 6, cap 12. B: $2.40/unit, lots of 4, cap 12. C: one lot of 20 at $2.80/unit. | B freight $0: A12+B8 costs $43.20, margin **$56.80**. B freight $20: C20 costs $56, margin **$44**; splitting A12+B8 would earn only **$36.80**. |
| **6. Balance a multi-component BOM** | Each kit needs one controller and one radio. Controllers: A lots of 10 at $1, cap 20; B one lot of 10 at $.80. Radios: C one lot of 10 at $1; D lots of 10 at $3, cap 20. Revenue $5/kit, target 20, minimum service 10. All are qualified. | Cash $60: A10+B10+C10+D10 costs $58, makes 20 kits, margin **$42**. Cash $50: B10+C10 costs $18, makes 10 kits, margin **$32**. Partial fulfillment is explicitly permitted; unused unmatched parts earn nothing. |

For family 4, the .1 posterior is derived, not assigned after seeing a model result:
prior favorable-market probability .5; each bad quote has likelihood .2 in a
favorable market and .6 in an unfavorable market; the two observations are
conditionally independent given the market. After both, the favorable probability
is `.5*.2^2 / (.5*.2^2 + .5*.6^2) = .1`. In the sibling case, earlier suppliers
are independent of the remaining prospect, so its .4 probability is unchanged.
The buyer must receive the dependence/prior information, not guess the evaluator's
assumptions. The old $2 of research expense remains spent in both cases.

These decision points isolate mechanisms. They are not a replacement for fresh
full episodes: the full generator must produce reachable histories and verify
which occur under its reference policy. An author-supplied difficult history is
not evidence that an end-to-end agent would reach it.

## Full-episode world design

Use a new family/campaign identity. Begin with tractable finite scenarios, then
expand only where reference quality can be certified.

- Give each market several competitive suppliers with differing MOQ, capacity,
  order increments, freight, lead time, inspection cost and prior quality. Use
  two-component BOMs where appropriate. Eight listings alone is not a difficulty
  requirement; the number of economically plausible choices matters.
- Supply a documented prior distribution and observation likelihoods. A small
  finite market regime can correlate supplier prices, lead times or quality.
  The realized regime, supplier condition and future sample outcomes stay hidden.
  These are calibrated synthetic beliefs; robustness to misspecified priors is a
  separately declared later slice, not a silent change to the oracle.
- Formal quotes reveal binding price, MOQ, capacity, shipping and delivery terms.
  Listings can provide overlapping uncertain estimates. Samples reveal noisy QC
  evidence; they establish variant/sample eligibility, not perfect knowledge of
  the future production yield. Full sample-count likelihoods should replace the
  binary QC simplification in the authoring example where appropriate.
- Remove action-revealing global infeasibility certificates from the scored
  search cases. Keep obvious impossibility checks in a separate sanity suite.
  Include hidden all-bad draws and profitable draws from the same declared prior;
  do not give the model a trap label or enforce a known "two traps per panel" rule.
- Make research costs, time and remaining actions bind in meaningful branches.
  Include cases where another sample helps, where it changes no decision, where
  a second-step information plan pays despite a useless first-step-only plan,
  and where further research destroys an existing offer.
- Generate economically distinct market parents with varied spreads, dependence,
  fixed costs, capacity ratios and bottleneck components. Supplier aliases and
  catalogue order are independently permuted and cannot identify a family or
  profitable option. Cosmetic variants stay in their parent's statistical cluster.

The accepted strategy paragraph remains shared across models. The common task
description must truthfully explain the new information and payoff contract;
there is no claim that the entire old Phase 2 prompt can remain byte-identical
after its certified-floor assumptions and observation schema change. Freeze the
new complete prompt once and use exactly that prompt for a model comparison.

## Reference policy and score

The reference sees the same public history and calibrated prior as the buyer.
It does not receive the sampled hidden state. Maintain a posterior belief `b`,
available formal offers, verified samples, cash, time and actions remaining.
For a research action `a`, use the finite-horizon decision value:

```
Q*(b, a) = -research_cost(a) + sum_o P(o | b, a) V*(updated_state(b, a, o))
V*(b)    = max(expected value of each legal award, defer value, research Q* values)
```

Time, cash, qualification and future opportunities must update on each branch.
An immediate negative expected purchase can still be worth investigating because
the buyer may reject it after an unfavorable result. Research is charged even on
that rejection branch. Full-information profit remains a diagnostic upper bound;
it is not the primary standard for judging costly discovery.

For the small finite probes the calculator enumerates all allowed continuations
with exact rational arithmetic. A test verifies a two-screen example where one
screen is worth $9.90, stopping $10, but a two-screen contingent plan $10.25.
For a larger full market, use exact dynamic programming only when tractable. If
an approximation is necessary, report verified lower/upper bounds and the gap;
do not label an unbounded heuristic an optimum or use it to certify tiny losses.

Report these components separately:

| Measurement | Definition and limit |
|---|---|
| **Primary economic performance** | Mean realized net contribution across paired draws: fulfilled-kit revenue minus purchased inventory, freight, all research and the explicit service/late penalties, plus any declared salvage. Report the paired mean gap to the information-limited reference. A single lucky realization can exceed the reference's expected value; a per-row realized gap need not be nonnegative. |
| **Decision quality diagnostic** | At each legal decision point, `V*(b) - Q*(b, chosen_action)`, under the frozen belief/utility model. This evaluates whether a test, award or defer was worthwhile with available information. Do not silently substitute it for realized business value. |
| **Constraint reliability** | Quote/sample/variant eligibility, MOQ, capacity, order increment, known delivery terms and available cash. Include all model failures in episode denominators; report violations by type. A stochastic quality loss after a legal purchase is an economic outcome, not automatically an illegal action. |
| **Service and efficiency** | Completed kits, on-time fulfillment, research expenditure/actions and premature-stop/over-search loss. Always include the costs paid before a defer. |
| **Operational coverage** | Attempted, replayed, malformed, timed-out and unattempted rows separately. Provider missingness remains null, not a zero-dollar successful defer. |

No experiment-wide "zero model mistakes" condition erases an otherwise measured
economic comparison. Reliability can have a separately preregistered acceptance
threshold for deployment claims. Invalid actions have explicit settlement semantics
(for example, rejected order and retained research cost), not an invented flat
penalty. An always-defer policy earns its outside option, but loses the opportunity
to profit in the rest of the distribution; it does not pass merely by abstaining.

## Offline admission and shortcuts

Before any paid pilot, freeze the generator, parameters, sampling distribution,
reference tolerance, prompt, model routes and analysis. Check:

1. **Correct reversal:** each matched pair has distinct preferred actions with a
   certified value gap. Retain near-ties as near-ties; never demand a unique answer
   when several actions are economically equivalent.
2. **No simple universal winner:** compare always-defer, fixed listing rank,
   cheapest-first, exactly-one-sample, exactly-two-samples, exhaust-budget and
   myopic value-of-information policies with the reference. Preserve all outcomes.
   Report economic gaps by family rather than selecting worlds on a model's loss.
3. **Information integrity:** serialize only the buyer observation. Fixture answer
   keys, regime labels, realized latent values, future sample streams and reference
   action values remain evaluator-only. Errors must not become a hidden-quality
   oracle. Identical observable histories induce identical reference decisions.
4. **Feasibility and accounting:** independently enumerate the integer allocation
   on small cases. Test cost-before-defer, expiry after research, cash after fees,
   noisy but legal bad outcomes, invalid purchases and action-budget exhaustion.
5. **Variation rather than renaming:** hold out combinations of economically
   meaningful parameters. Share environment streams across models by supplier,
   action type and draw index, not by the global order in which calls happened.
6. **Coverage without outcome gates:** operational admission requires valid
   schemas, functioning tools, replay and bounded resource use. It must not require
   that a model defer, buy, split or beat another model in the pilot.

## Model comparison and sample design

Use the same detailed prompt, public cases, budgets and environment streams for
all compared models. Name the exact model IDs and provider routes before running;
fail on an unexpected model substitution. A Gemini/GLM comparison is a new
prospective experiment; the previous GLM rows are neither Gemini observations nor
held-out results for this new generator.

Independently generated market parents are the comparison units. Repeated sample
seeds and the two halves of a matched pair stay within the parent cluster. Report
family effects and repeat variability before a declared weighted overall mean.
More seeds cannot substitute for more market structures. Choose the final market
count and repeat count from a bounded pilot and a declared economically meaningful
effect, not the old unsupported eight-cluster power claim. A pilot used to tune
the generator is exploratory and excluded from frozen confirmation.

The present twelve examples establish neither difficulty for models nor statistical
power. No live sample count, provider budget or model winner is claimed here.
The first cross-model check should determine whether value loss remains in several
families, instead of merely reproducing a supplier-ID or one-pattern bottleneck.

## Reproduction and inspection

```
python tools/check_procurement_information_design.py \
  --output runs/procurement_information_design_v1/decision_values.json
PYTHONPATH=src python -m pytest tests/test_procurement_information_design.py -q
```

Observed validation: **12/12 intended decisions and values match; all six pairs
reverse their preferred action; 20 tests pass; zero provider calls.** Tests include
an independently computed noisy-screen value, two-step information value, expiry,
qualification requirements, correlated evidence, allocation costs, malformed
likelihood rejection and hidden-state index permutation. The fixtures simplify
several lot outcomes to stated conditional dollar payoffs; the production adapter
must derive these from its actual procurement cashflows rather than copying them
as answer labels.

The combined check passes **27 tests** including seven source-layout checks.
Two runs produce byte-identical decision reports, local documentation links resolve,
and all 92 executed Phase 2 source/test pins remain unchanged. The twelve preferred
actions comprise six awards, five research actions and one defer; this is authoring
coverage, not a measured model success rate.

Inspect in this order:

1. [Case fixtures](../../../tests/fixtures/procurement_information_design_v1.json): compare each pair's economics and explicit starting history. The numerical reversals are checked; full-episode reachability and realism remain unvalidated.
2. [Reference calculator](../../../tools/check_procurement_information_design.py): `action_values` conditions on observations and retains research cost/expiry; `allocation_choices` enumerates BOM-feasible purchases. This is an authoring calculator, not the shared-runner scorer.
3. [Tests](../../../tests/test_procurement_information_design.py): inspect the $18 noisy-information example versus the $26 clairvoyant value, and the $10.25 two-step plan versus stopping at $10. No model response is involved in either result.

The next implementation slice is one fully replayable end-to-end family with
actual quote/sample actions and a checked reference, followed by offline baselines
and a provider-free fixture campaign. Full-world adapter, observation-boundary
tests, shared-runner admission, external domain review and live discrimination
testing remain outstanding. This document and its calculator complete the case
design slice, not those later execution stages.

Method basis: belief-state sequential planning follows
[Kaelbling, Littman and Cassandra (1998)](https://www.cassandra.org/arc/papers/aij98.pdf).
The decision to spend resources on obtaining useful information is related to
[Russell and Wefald (1991)](https://doi.org/10.1016/0004-3702(91)90015-C).
The synthetic procurement parameters and admission rules here are new design
choices, not empirical claims from those papers.
