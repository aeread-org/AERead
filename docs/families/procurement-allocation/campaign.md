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

### Qwen matched case qualification

The next model candidate is the Apache-2.0 Qwen3 30B-A3B Instruct checkpoint on a
pinned CoreWeave BF16 route. It reuses the qualified GLM baseline's six cases, three
inference seeds, unscaffolded prompt, Minimal Chat transport, action budget, and
objective verifier. This supports a later matched model diagnostic without treating
the three seeds within one economic world as independent cases.

The campaign first sends one unscored exact-request canary. Any nonempty response
admits transport, including malformed JSON; output validity is not used to select a
candidate. Scored execution is sequential, advances six trajectories per invocation,
and stops permanently on the first typed operational failure. Only a failure-free
checkpoint may resume. All 18 rows must complete and receipt-replay before outcomes
are inspected or compared.

V1 froze plan digest
`fc7febffe7f3aa947a00c30821d7da87935c6ce12a7d39e275cf2155d3d57d02`,
then stopped at admission before any scored trajectory. The exact request received
HTTP 404 because the adapter serialized `reasoning: {}` despite the profile declaring
no reasoning control. With parameter matching required, OpenRouter removed the
otherwise eligible endpoint at its parameter-filter stage. The canary reported zero
cost but marked accounting unavailable, so V1 is sealed and ineligible.

V2 preserves V1's model, route, cases, seeds, prompt, harness, action budget,
checkpoint policy, retries, cost bounds, and eligibility rule. Its only operational
change omits the reasoning field when neither effort nor token budget is declared.
The V2 frozen plan digest is
`cef886b5f890c4a14c224a09ea4541ebfdbaacbbf872f633139827a7f42a08d5`.
The conservative total ceiling remains $0.1792 and the hard total ceiling $0.19,
including the canary. The claim remains a six-world curated-panel diagnostic, not a
population model ranking or evidence that an open-source license determines quality.

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
Execution is sequential and checkpoints after six completed rows by default. A
failure-free checkpoint may continue only the declared missing case/seed rows with
`--resume`; the sealed canary and completed rows are reused unchanged. The first
operational failure permanently disqualifies the attempt, remains typed missingness,
and is never resumed or included in the effect estimate.

The runner also exposes pinned GLM/Reka, GLM/Cloudflare, and GLM/Parasail routes as
`--candidate-id glm53_flash_reka` and
`--candidate-id glm53_flash_cloudflare`, and
`--candidate-id glm53_flash_parasail`. Each selection receives a distinct
campaign ID, panel IDs, provider metadata, and $0.5700 treatment ceiling. They do
not reuse the qualified Morph controls: a route change requires new labeled and
opaque unscaffolded controls on that same route before a scaffold effect is
eligible. This prevents provider implementation or quantization differences from
being misreported as a prompt-treatment effect.

The Parasail v4 route permits at most two runner-owned retries after the initial
provider call, only for typed rate-limit or provider-5xx failures. SDK retries are
disabled. Backoff is exponential with deterministic jitter and honors bounded
`Retry-After` guidance. Retry counts, triggering conditions, and total provider
calls are retained in the sanitized rows, and the paired comparison requires the
control and treatment retry policies to match. A recovered transient is therefore
observable rather than silently changing the campaign's effective sampling process.

The first v1 development attempt admitted its canary and completed one labeled
trajectory before a typed HTTP 429 stopped the queue. That row reached an award in
six actions instead of exhausting all ten, but it sampled and awarded formally late
suppliers, completing zero kits. The v2 prompt therefore imposes a hard deadline gate
before price ranking and sampling. V2 then completed 14 labeled rows before another
typed HTTP 429. All three deadline rows became feasible 19-kit awards, but all three
MOQ/capacity rows submitted quantities above the selected offers' capacities. V3
therefore adds an explicit second-supplier split rule whenever required raw units
exceed one offer's capacity. These adaptive changes are versioned explicitly; results
on these development worlds remain exploratory and require a held-out panel for
confirmation.

## Observed Parasail v4 strategy result

The v4 Parasail campaign qualified all 36 treatment trajectories and replayed every
receipt with zero operational failures. Its labeled panel was feasible in 16/18 rows
and its opaque/reordered panel in 18/18. The corresponding same-route controls were
feasible in 11/18 and 9/18 rows. Treatment execution cost $0.092382147, plus one
unscored $0.0002539845 admission canary; the two control panels cost $0.087848244.

After averaging the three seeds within each of the six economic worlds, the labeled
treatment-minus-control effect was +0.2778 feasibility, +2.1111 completed kits,
+$17.3712 contribution margin, and -$17.3712 regret. Its six-world bootstrap intervals
cross zero, so the labeled result is directional rather than confirmatory. The opaque
effect was +0.5000 feasibility (95% interval [0.2222, 0.7778]), +7.0000 completed kits
([3.2222, 11.5000]), +$24.6111 margin ([$5.8546, $50.3578]), and -$24.6111 regret
([-50.3578, -5.8546]). All paired route, retry-policy, seed, prompt-binding, replay,
case-content, pair-identity, and upper-bound integrity checks passed.

The opaque result is the most robust signal in this adaptive panel: the scaffold
removed all nine control failures and reduced the absolute surface gap in feasibility
by 0.1111 on average. The labeled treatment also introduced two pass-to-fail
transitions, including a sample-verification failure in the quality/refund world.
That regression should define a held-out diagnostic, not an in-place v4 prompt edit.
Because v1-v4 were developed against these same six worlds, this evidence supports a
mechanism hypothesis and a qualified implementation artifact, not a population-level
claim. The next confirmatory campaign should freeze v4 and use new economic worlds.

## Frozen confirmatory campaign

The confirmatory campaign freezes the exact V4 treatment prompt and its unscaffolded
control by SHA-256, the GLM/Parasail revision and route, Minimal Chat transport,
runner-owned retry policy, twelve new paired economic worlds, three new inference
seeds, sequential execution, and 12-row checkpoints. It binds the adaptive evidence
manifest that motivated the test. Any drift in these inputs requires a new campaign
identity.

The four arms run in this order: labeled control, opaque control, labeled treatment,
and opaque treatment. All 144 rows must complete and receipt-replay. Controls run
before treatments, no outcome-based early stopping is allowed, and an operational
failure seals the attempt as missingness. The conservative scored ceiling is $2.16;
two prompt-specific unscored admission canaries raise the total ceiling to $2.22.

The independent unit is the economic world. Within each of the twelve worlds, the
three inference seeds are averaged within each surface, then the labeled and opaque
treatment-minus-control deltas are averaged equally. The preregistered primary
estimand is regret-to-upper-bound delta. Confirmation requires its deterministic
50,000-resample world-cluster bootstrap upper bound to be strictly below zero and
the overall feasibility-delta lower bound to be at least -0.05. Surface-specific
feasibility, kits, margin, regret, violations, latency, tokens, retries, and cost are
secondary diagnostics.

Evidence eligibility does not depend on a favorable result. A fully complete,
replayed, digest-valid campaign is publishable as either `supported` or
`not_supported`. The claim remains bounded to twelve curated synthetic worlds and is
not a population-level model ranking.

## Confirmatory v1 operational audit

The first confirmatory attempt sealed after 46 completed rows and one typed
`empty_response` failure in opaque control, leaving 97 trajectories unattempted.
No efficacy outcomes were inspected. The completed rows and two canaries reported
$0.113711994, but the failed trajectory had already incurred $0.002703789 across
seven successful provider calls. V1 therefore cost at least $0.116415783; the final
empty call's usage was not retained by that implementation, so its exact total is
unknown. V1 is permanently ineligible and is never resumed or scored.

V2 preserves V1's cases, prompts, route, three inference seeds, arm order, estimands,
bootstrap, and decision thresholds. Its only changes are operational: a billed empty
completion remains a successful provider call in usage accounting, failed-trajectory
cost is recovered from the sealed event ledger, and `empty_response` can retry within
the existing three-attempt action bound. The V2 frozen plan digest is
`cd8cff2fbedc8c208195982bcf3f692ba290f1e37f7b58b5e8c72ddfd957b4dd`.

## Observed confirmatory v2 result

V2 qualified all 144 planned rows across twelve independent worlds and replayed every
receipt with zero operational failures. The scored rows cost $0.345487329 and the two
unscored canaries cost $0.000472725, for $0.345960054 total. All usage and cost fields
are exact. Three rate-limit retries recovered in opaque treatment; no empty-response
retry was needed.

The preregistered hypothesis is supported. Averaged within world across the labeled
and opaque surfaces, treatment reduced regret by $26.0384 (95% deterministic
world-cluster bootstrap interval [-$46.1031, -$7.4144]) and improved feasibility by
0.2500 ([0.0694, 0.4444]). It also increased completed kits by 5.8056 ([3.3194,
8.0694]) and contribution margin by $26.0384 ([$7.1926, $46.1468]). There were 22
fail-to-pass and four pass-to-fail seed-level feasibility transitions across the two
surfaces.

The result survives removal of supplier-name cues and listing-order changes. Labeled
regret improved by $16.8383, but its interval [-$37.3019, $2.4585] crosses zero.
Opaque regret improved by $35.2385 with an interval [-$60.2523, -$12.1409]. The
opaque-minus-labeled interaction is -$18.4002, but its interval [-$39.5617, $1.3595]
also crosses zero, so the evidence does not establish that the scaffold works better
on opaque cases.

The treatment used 435 provider calls and cost $0.1683252945 versus 465 calls and
$0.1771620345 for control. Quality therefore improved without greater inference
spend. The effect is not uniform: eight worlds reduce regret, while sample lead time
and landed-cost/freight worsen it by $26.3044 and $10.8050 respectively; cash-budget
and on-time-reliability regress slightly. These failures motivate focused held-out
tests of sample timing and landed-cost gates rather than an in-place change to this
confirmed V4 intervention.

## Adaptive held-out risk-gate factorial

The next campaign holds the qualified GLM revision, provider route, action schema,
objective verifier, and frozen V4 prompt fixed while testing two explicit decision
gates. The temporal gate requires verbal confirmation of sample logistics and a
serial critical-path calculation. The cash gate requires quote-level landed-cash
arithmetic after MOQ, order-step, capacity, and BOM rounding. A 2x2 design runs V4,
temporal only, cash only, and both gates on both labeled and opaque surfaces.

The six economic worlds in `cases/procurement_allocation_v1/risk_gates_v1/` were
created after the V2 result audit. Three test sample timing and three test cash
failures driven by freight, duty, or MOQ. The presentation mirrors are economically
identical and use deterministic opaque IDs and reordered listings. The new three
inference seeds are also disjoint from prior campaigns.

Each invocation advances one complete economic-world block: three seeds in all
eight surface-condition arms. Six failure-free checkpoints complete 144 scored
rows. Four prompt-specific canaries are unscored. The conservative total ceiling is
$2.24 and the absolute per-trajectory/canary ceiling is $2.96. Retries are limited to
four attempts for typed rate limits, provider 5xx responses, or empty completions;
all attempts and billed usage remain visible.

The adaptive analysis reports temporal, cash, joint, factorial-main, and interaction
contrasts after equal aggregation across surfaces and seeds within each world.
Promotion of the joint gate requires lower mean regret overall, non-worse regret in
each stratum, and no loss in feasibility, completed kits, or defer rate overall or by
stratum. The six-world bootstrap intervals are exploratory. Eligibility depends only
on complete replayed rows, exact cost accounting, and bound identities—not a
favorable result.

Print the no-spend frozen plan:

```bash
python -m aeread_families.procurement_allocation.risk_gate_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm53_flash_parasail_risk_gate_factorial_v4/qualification_attempt_001
```

After provider-free verification and loading `OPENROUTER_API_KEY`, add
`--execute --max-spend-usd 2.96`. Continue each failure-free world checkpoint with
`--resume`. Raw state remains under ignored `runs/`; publication is a separate
`--publish-only` call to the matching direct `evidence/` bundle.

### Risk-gate V1 operational audit

V1 attempt 001 completed and replayed 77 scored rows before a typed HTTP 429 on the
78th row exhausted its three action attempts. The upstream response supplied no
`Retry-After`; the runner waited only 2.221 and 4.363 seconds. The failed row retained
$0.000311355 of earlier successful-call cost exactly. Attempt 001 cost $0.2066673015
including its four canaries, and remains sealed with 66 unattempted trajectories.

Four later fresh admission attempts confirmed intermittent route throttling. Two
stopped on their first zero-cost canary; two admitted some prompt shapes before a
later canary failed. No scored rows ran in those roots. Across all V1 attempts, exact
incurred cost was $0.2079232155. No partial efficacy contrast was inspected, and V1
is permanently ineligible.

V2 preserves all cases, economic pairing, prompt text and hashes, inference seeds,
model revision, route, cost bounds, estimands, bootstrap, and progression thresholds.
Its operational-only changes set the missing-`Retry-After` backoff base to 15 seconds
(then 30), apply the same bounded retry policy to canaries, and space new canaries by
10 seconds. V2 therefore receives a new campaign identity while retaining V1's
scientific contract.

### Risk-gate V2 operational audit and V3 correction

V2 admitted all four prompt shapes and completed 93 scored rows. It recovered one
provider-5xx response and two rate-limit responses under the preregistered pacing,
then stopped on row 94: opaque joint, `landed_cash_freight`, seed `279557369`. The
route returned nonempty structured-output text that was not valid JSON. The adapter
misclassified that observed model response as a zero-cost `provider_contract`
failure before the family parser could score it as `malformed_json`.

V2 remains sealed and ineligible with 50 rows unattempted. Its ledgers retain
$0.285769539 of exact known cost including canaries, but the terminal call's usage
and cost are unavailable because the old exception path discarded the returned
response metadata. No partial V2 efficacy contrasts were inspected.

V3 preserves V2's cases, economics, prompts, hashes, seeds, model route, arm order,
retry pacing, cost bounds, estimands, bootstrap, and progression thresholds. The
adapter now retains nonempty malformed content as a successful billable provider
response; procurement then terminates and scores it as an invalid model action.
Admission canaries gate only transport readiness and record, but do not select on,
model-output validity. These are measurement corrections, not changes to the
scientific treatment.

### Risk-gate V3 operational audit and V4 retry bound

V3 completed and replayed 135 rows before stopping on row 136: opaque temporal,
`landed_cash_moq`, seed `279557369`. Five calls in that trajectory succeeded, then
one logical action received three consecutive HTTP 429 responses. With no
`Retry-After` header, the runner waited 15.371 and 30.444 seconds before exhausting
the three-attempt bound. Eight planned rows remain unattempted.

Across completed V3 rows, six other rate limits and one provider-5xx response
recovered under the declared policy. The sealed attempt cost $0.40121235 exactly,
including canaries and the failed row's earlier successful calls. No partial V3
efficacy contrast was inspected, and V3 is permanently ineligible.

V4 preserves all scientific inputs and analysis rules from V3. Its only operational
change raises the per-action attempt bound from three to four while retaining the
15-second first backoff and 30-second cap. A fully throttled action therefore gets a
final fourth request at approximately 75 seconds. V4 has a new campaign identity
and must rerun all 144 rows from a fresh root.

### Risk-gate V4 operational audit and next gate

V4 attempt 001 admitted all four prompt shapes, then completed and replayed 13
scored rows before stopping on row 14: opaque V4,
`sample_schedule_symmetric`, seed `2094119875`. The first four logical actions in
that trajectory succeeded; the third and fourth each recovered from one rate limit.
The fifth action then received four consecutive HTTP 429 responses. With no
`Retry-After` header, the runner waited 15.486, 30.649, and 30.717 seconds before
exhausting the four-attempt bound. The endpoint catalog in every failure reported
only one available route for the pinned model revision.

The sealed attempt has one typed operational failure and 130 unattempted rows. It
cost $0.0417325095 exactly, including all canaries and the failed row's successful
calls. No partial V4 efficacy contrast was inspected. V4 attempt 001 is permanently
ineligible and must not be resumed or scored.

This audit does not justify a V5 with still more within-action retries: four failures
already span roughly 77 seconds, so increasing the bound would mainly expose the
campaign to a persistently unavailable shared route. The next GLM test is a fresh V4
attempt under the identical frozen plan in a later availability window. A different
model or provider belongs to a separately named campaign and cannot be pooled with
V4; it should first pass an exact-request canary and a small complete case panel.
