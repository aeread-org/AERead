# Procurement allocation campaign

## Purpose

`procurement_allocation_v1` tests whether a buyer can turn provisional marketplace
listings and natural-language supplier exchanges into a valid order decision. The
buyer must obtain formal offers and exact-variant sample evidence before awarding,
then balance service, landed cost, quality, refund recovery, and working capital.

This is an `objective_reference` family. The terminal contribution margin is compared
with a deterministic full-information upper bound that is charged for every quote,
sample, and negotiation action required to reach its award. Constraint-only refund
tests and claim-grounding tests remain separate verifier families.

## Grounding boundary

The six-case variance panel is anchored to the component-family priority matrix in
`cases/procurement_grounding_v1/dev/procurement_grounding_231_projects.json`. That
snapshot covers 231 projects and 1,156 BOM rows. It is used only to choose relevant
component families and preserve their observed project/BOM counts.

Supplier names, prices, MOQs, capacities, lead times, quality observations, return
terms, and negotiation limits in the allocation cases are synthetic experimental
variables. The grounding snapshot itself says displayed prices are not verified
quotes and project BOMs are not production truth. The allocation cases therefore do
not claim current supplier availability or commercial authority.

## Declared case variance

| Case | Component-family pair | Primary decision pressure |
|---|---|---|
| `deadline_cost` | ESP32-S3 + SSD1306 OLED | Cheap late supply versus costly on-time supply |
| `quality_refund` | SHT30 + BH1750 | Unit cost versus verified yield and refund recovery |
| `moq_capacity_split` | tactile switch + KY-040 | MOQ, capacity, and multi-supplier allocation within ten actions |
| `working_capital` | DS3231 + ESP32-S3 | Prepay discount versus longer payment terms |
| `variant_substitution` | protected TP4056 + MOSFET driver | Cheap near-match listings versus exact variants |
| `service_defer` | KY-023 + SSD1306 OLED | Thin service-feasible award versus the explicit defer option |

Each case has a distinct world seed and BOM signature. Three inference seeds per case
produce 18 declared trajectories. Replicates within one case measure stochastic
reliability; they are not counted as additional independent procurement cases.

## Blinded label/order invariance campaign

`cases/procurement_allocation_v1/blinded_v3/` is a paired mirror of the six-case
panel. It preserves each objective, policy, interaction budget, substantive listing
claim, private supplier term, world seed, and deterministic full-information upper
bound. The intervention replaces suggestive supplier identifiers and names with
deterministic opaque identifiers and deterministically changes listing order.

The v3 campaign uses the same three inference seeds, model route, and Minimal Chat
harness as the v2 baseline. Rows pair by case slug and inference seed. This tests
whether procurement behavior is sensitive to semantic hints such as `value`,
`express`, or `exact`, or to presentation order. It does not add six independent
economic worlds and is not a population estimate.

A result is eligible for publication when all 18 baseline and all 18 blinded rows
are present, completed, receipt-replayed, and paired; the model route and harness
match; and each observed upper bound is invariant. Model performance is not an
eligibility gate: a lower blinded score is a valid sensitivity finding. Operational
failure, missing pairs, changed economics, or digest mismatch blocks qualification
and must not be converted into a procurement score.

Before a live v3 attempt, an unscored admission canary sends the first case's real
structured request shape through the pinned route. Its sanitized record binds the
request digest, resolved model, usage, cost, and parsed action without retaining the
provider payload. A rejected canary prevents the panel from starting. If a provider
failure occurs after admission, the campaign stops after that sealed cell, reports
the remaining trajectories as unattempted, and requires a fresh attempt root rather
than selectively resuming around the failure.

## Observed v3 qualification

`qualification_attempt_004` completed all 18 blinded trajectories and replayed every
receipt with zero operational failures. The admission canary cost $0.000118998 and
the scored panel cost $0.0245407338. The paired integrity checks confirmed identical
model route, harness, inference seeds, pair identities, and upper bounds.

Feasibility fell from 7/18 in the labeled baseline to 2/18 after blinding. The paired
transitions were 11 fail/fail, 5 pass/fail, 2 pass/pass, and 0 fail/pass. Mean
completed kits changed by -4.8889, mean contribution margin by -$26.4214, and mean
regret by +$26.4214.

The loss is concentrated in two of the six independent worlds:
`variant_substitution` accounts for three pass/fail transitions and
`working_capital` for two. The other four worlds have no feasibility-count loss.
With only six curated economic worlds and a bundled identity/order intervention,
this is a shortcut-sensitivity diagnostic rather than a population estimate. The
next causal ablation should separate opaque labels from reordered listings while
holding these same worlds and seeds fixed.

## Artifact contract

- Executable inputs live under `cases/procurement_allocation_v1/`.
- Raw plans, model events, receipts, replay state, and resumable results live under
  ignored `runs/`.
- Sanitized review projections live under `evidence/<publication_id>/` and retain
  source and implementation digests.
- This document explains design and interpretation; it is not benchmark evidence.

The campaign holds Minimal Chat fixed as transport and tests the model, not one
harness against another. Completed trajectories must replay exactly. Provider errors
remain typed operational missingness and never become zero-margin procurement scores.

## Paired open-source model follow-up

The next independent model test holds the original six cases, three inference seeds,
Minimal Chat harness, action budget, and objective verifier fixed, then replaces the
GLM/Morph route with the pinned Mistral Small 4/Mistral route. This route was selected
because it completed all measured calls in the prior procurement-grounding open-source
bake-off; that one-case classifier result is only an admission signal, not evidence of
allocation quality.

The campaign reports Mistral-minus-GLM paired changes in feasibility, completed kits,
contribution margin, and regret. It requires identical case content digests and upper
bounds, completed receipt replay for all 18 Mistral trajectories, and exact seed and
harness parity. The six economic worlds are the inference clusters. Provider failures
block the comparison and are never imputed as model outcomes.

The first two fresh attempts did not pass that gate. Both exact-request canaries
were admitted, but the first scored call in each attempt returned an empty response.
Each attempt therefore has zero completed trajectories, one typed operational
failure, and 17 unattempted trajectories. The repeated failure rejects this route
for the declared allocation campaign. It does not support a Mistral procurement
score or a Mistral-versus-GLM ranking.

## Public-observation policy controls

The deterministic policy campaign supplies non-model floors and a negative control
for the bundled supplier-label/order intervention. Each policy operates through the
same Minimal Chat request boundary and can parse only the public observation. The
environment still controls formal offers, samples, time, cost, feasibility, and the
objective score.

Immediate defer, displayed-price greedy, listing-claim fit, and semantic-hint
policies run once on each of the six labeled and six opaque/reordered worlds. The
economic world is the independent unit. The paired report requires 48 completed
rows, exact receipt replay, invariant solver upper bounds, and zero provider cost.
It reports policy outcomes separately and never treats a scripted policy as a model
replicate or as the full-information oracle.

## Observed policy-baseline result

All 48 declared policy trajectories completed and receipt-replayed with invariant
upper bounds and zero provider cost. Displayed-price greedy and listing-claim fit
were feasible in all six worlds under both surfaces. Each averaged 19.6667 completed
kits, $58.0359 contribution margin, and $15.5681 regret. Their paired
blinded-minus-labeled outcome deltas were zero.

The semantic-hint policy remained feasible in all worlds but changed outcomes in
three. Its opaque/reordered condition improved mean completed kits by 3.3333 and
margin by $4.0138. Thus, merely following favorable-looking supplier names does not
explain GLM's large labeled-to-blinded decline; in this policy control, removing the
names helped on average.

The primary displayed-price policy was also paired with the qualified GLM results by
economic world after averaging GLM's three inference seeds within each world. The
policy-minus-GLM mean margin was +$28.4986 on labeled/original cases with a six-world
bootstrap interval of [$2.3216, $55.9134], and +$54.9200 on opaque/reordered cases
with an interval of [$36.6918, $73.7546]. Feasibility differences were +0.6111 and
+0.8889 respectively, with intervals excluding zero. These results show substantial
headroom on the curated panel; they do not establish population-level superiority of
the deterministic policy.

## Strategy-scaffold campaign

The public-policy floor motivates a model-side intervention rather than another
harness comparison. `strategy_scaffold` appends a compact decision procedure to the
existing buyer prompt while holding the model revision, provider, structured-action
schema, Minimal Chat transport, case economics, seeds, action budget, scorer, and
receipt replay fixed.

The treatment runs 18 labeled/original and 18 opaque/reordered trajectories. Each
panel is paired to its already-qualified unscaffolded GLM control by economic-world
slug and inference seed. Primary effects are computed after averaging the three
inference seeds within each of the six worlds, with exact six-cluster percentile
bootstrap intervals. A difference-in-differences report then tests whether the
scaffold changes the opaque-minus-labeled sensitivity.

The treatment prompt ID, treatment ID, and content digest are bound into each model
plan; full prompt text remains only in source and raw execution context. Publication
requires both 18-row panels to complete and replay, exact seed and route parity with
their controls, complete pair identities, invariant objective upper bounds, and
verified artifact/row digests. A score improvement is never an eligibility gate.

The conservative total ceiling is $0.5088 including one unscored admission canary.
Execution is sequential by default and aborts on the first operational failure. A
failed attempt remains typed missingness and is never resumed or included in the
effect estimate.
