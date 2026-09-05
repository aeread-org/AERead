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

#### Observed Qwen V2 result

V2 admitted its exact-request canary, completed all 18 scored trajectories, and
receipt-replayed every row with zero operational failures or retries. The canary cost
$0.000152064 and the scored panel cost $0.018937017, for $0.019089081 total with
exact accounting.

Qwen produced no feasible allocation in 18 attempts. Twelve submitted awards that
failed minimum service, including two unverified-sample violations. Six terminated
as malformed JSON. The raw sealed responses show that those six reached the
1,800-token completion limit while repeatedly inventing a large `fields` array that
was outside the strict action schema, then ended mid-JSON. This is retained as model
and pinned-route behavior, not converted into provider missingness or repaired after
the fact.

The paired comparison against the qualified GLM baseline passed every case, seed,
content, harness, upper-bound, route, replay, cost, and digest check. The seven GLM
feasible rows all transitioned pass-to-fail; the other eleven pairs were fail/fail.
After averaging seeds within each of the six economic worlds, Qwen-minus-GLM effects
were -0.3889 feasibility (six-world bootstrap interval [-0.7222, -0.1111]), -8.3333
completed kits ([-13.7222, -3.3889]), -$29.5818 contribution margin
([-56.9818, -6.1514]), and +$29.5818 regret ([6.1514, 56.9818]). These intervals
describe only the curated panel.

Operationally, Qwen's median trajectory time was 16.74 seconds versus 204.43 for the
historical GLM run, and its scored cost was $0.018937017 versus $0.0365370885. Route,
provider, and execution-time differences confound that speed comparison, so it is a
deployment diagnostic rather than a model-only causal effect. Because base
allocation feasibility was 0/18, this candidate does not progress to the 144-row
risk-gate factorial.

### Adaptive Qwen 235B follow-up

The next candidate tests whether greater model capacity clears the base allocation
gate before any further prompt-mechanism campaign. It pins the Apache-2.0 Qwen3
235B-A22B Instruct checkpoint to the AtlasCloud FP8 route while preserving the 30B
campaign's cases, seeds, unscaffolded prompt, Minimal Chat transport, action budget,
objective verifier, checkpointing, retry policy, and completeness gate. Candidate
selection occurred after inspecting the qualified 30B result, so this remains an
adaptive diagnostic rather than confirmatory model selection.

The frozen plan binds the 30B evidence manifest and has digest
`9b7b2fbea8200eb9900ee063bf34255c3162f9aa7e733a5d76adb7224507a78f`.
One unscored exact-request canary precedes three sequential six-row checkpoints.
The conservative total ceiling is $0.45912 and the hard ceiling is $0.57 including
the canary. Any operational failure seals the attempt, and no case outcome is
inspected until all 18 rows complete and receipt-replay.

#### Observed Qwen 235B AtlasCloud result

The canary and all 18 scored trajectories completed with exact accounting, no
operational failures, and no retries. The canary cost $0.0002727648 and the scored
panel cost $0.0047373876, for $0.0050101524 total. Every row receipt-replayed and
the median trajectory time was 2.69 seconds.

All 18 trajectories nevertheless stopped on their first action with
`unknown_procurement_action`. The returned JSON was semantically a supplier inquiry,
but placed `inquire` at the top level and omitted the required top-level
`"action": "inquire"` discriminator. This repeated envelope error produced 0/18
feasible allocations. Because the route did not enforce the declared strict schema,
the result identifies a route-level structured-output compatibility failure; it does
not isolate the checkpoint's procurement decision capacity and does not progress to
the risk-gate factorial.

### Adaptive Qwen 235B provider-route diagnostic

The next diagnostic holds the 235B checkpoint, exact six cases, three inference
seeds, prompt, Minimal Chat harness, action budget, objective verifier, retries, and
checkpoint policy fixed, while changing only the pinned route to Google. The live
endpoint catalog declares one Google endpoint at the pinned $0.22/M input and
$0.88/M output prices with `structured_outputs`, `response_format`, `seed`, and
`max_tokens` support; a second, more expensive endpoint is excluded by the price pin.

This is a provider-route diagnostic, not a new model comparison. It binds the
published AtlasCloud evidence manifest, runs one unscored exact-request canary, then
three sequential six-row checkpoints. The frozen plan digest is
`7c90ba968b369ab0b03c080ea734f6aa71efdfb981d160d9ac795a2a56fff862`,
with a $0.47352 conservative ceiling and $0.57 hard ceiling including the canary. If
the Google route returns valid action envelopes, later outcome differences can be
interpreted as route-mediated behavior. If it repeats the same envelope defect, the
evidence shifts toward checkpoint or adapter incompatibility, but still does not
justify a broad model-quality claim.

#### Observed Qwen 235B Google result

The Google route admitted a valid `inquire` action and completed all 18 scored rows
with receipt replay, exact accounting, zero operational failures, and zero retries.
The canary cost $0.0003336696 and the scored panel cost $0.0620862858, for
$0.0624199554 total. Median trajectory time was 13.94 seconds.

Every matched first action changed from a missing discriminator on AtlasCloud to a
valid `inquire` action on Google. Eleven trajectories reached an award submission,
six ended with a malformed procurement action, and one exhausted the ten-action
interaction budget. Three allocations were feasible: one quality/refund replicate
and two variant-substitution replicates. The other 15 remained infeasible, including
systematic over-capacity awards in the MOQ/capacity world and minimum-service failures
in the deadline and service-defer worlds.

The digest-bound paired route comparison qualified all 18 pairs. Google-minus-
AtlasCloud effects, after averaging seeds within each of the six worlds, were +0.1667
feasibility (six-world bootstrap interval [0.0000, 0.3889]), +7.7778 completed kits
([2.3333, 13.5556]), +$12.0299 contribution margin ([-$1.0389, $31.1382]), and
-$12.0299 regret ([-$31.1382, $1.0389]). The route therefore fixes the action-envelope
failure and reveals some decision capacity, but uncertainty and remaining constraint
violations do not support a general provider ranking or progression to the 144-row
risk-gate factorial.

The next high-value test is a matched constraint-ledger treatment on this qualified
Google route. It should require the model to record demand, capacity, MOQ, deadline,
cash, sample, and minimum-service obligations before submitting an award, while
leaving the environment, objective verifier, action schema, cases, and seeds fixed.
This directly tests whether the dominant residual failures are recoverable planning
errors rather than spending another broad campaign on an unqualified base policy.

That adaptive treatment is frozen as
`procurement_allocation_qwen3_235b_google_constraint_ledger_v1`. It binds the
published Google control manifest and changes only the public buyer decision
procedure. The plan digest is
`af36b6088539cbece9967f066f9954d80e743e2350dfe17bf3b91a7b7380c36d`.
One unscored canary precedes three sequential six-row checkpoints; the conservative
total ceiling is $0.47352 and the hard ceiling is $0.57. Outcomes remain hidden until
all 18 rows complete and receipt-replay with exact cost accounting.

#### Observed constraint-ledger V1 result

V1 admitted a valid `request_quote` canary and completed and receipt-replayed all 18
rows with no operational failures or retries. The canary cost $0.00038115 and the
scored panel cost $0.0216552006, for $0.0220363506 total with exact accounting.
Median trajectory time fell from 13.94 seconds in control to 1.78 seconds in
treatment, largely because many treatment trajectories terminated early.

Treatment produced 5/18 feasible allocations versus 3/18 in control. All three
deadline/cost replicates changed fail-to-pass, two variant-substitution replicates
remained pass-to-pass, and one quality/refund replicate changed pass-to-fail. Across
the six worlds, treatment-minus-control effects were +0.1111 feasibility (six-world
bootstrap interval [-0.1667, 0.5000]), -2.5000 completed kits ([-11.4444, 7.1667]),
+$6.2385 contribution margin ([-$9.3673, $27.6077]), and -$6.2385 regret
([-$27.6077, $9.3673]). None of these panel intervals excludes zero.

Thirteen treatment rows ended with `malformed_procurement_action`. Their sealed
provider responses were schema-shaped, but the selected `request_quote` or
`request_sample` action carried a null `message`; that field is contractually required
to be non-empty because it contains the verbal confirmation request. Irrelevant null
superset fields are ignored, but selected-action nulls are not post-hoc normalized.
Thus V1 demonstrates a strong deadline-world gain alongside broad action-contract
regressions and does not progress to the risk-gate factorial.

The next bounded diagnostic should be an adaptive V2 that adds only an explicit
non-empty-message reminder to the frozen V1 decision procedure. Reusing the same
panel is suitable for diagnosing output-contract compliance, but any efficacy change
remains development evidence because V2 is selected after inspecting V1.

V2 is frozen as
`procurement_allocation_qwen3_235b_google_constraint_ledger_v2`, with plan digest
`b08c0d86956ce522b7bd401d617acf110fabea0f4637b077749e7722043ff308`.
It binds the V1 evidence manifest and appends only the selected-action field reminder.
One unscored canary precedes three sequential six-row checkpoints. The conservative
total ceiling remains $0.47352 and the hard ceiling $0.57; inspection remains blocked
until all 18 rows complete and receipt-replay with exact cost accounting.

#### Observed constraint-ledger V2 result

V2 admitted a valid `request_quote` canary and completed and receipt-replayed all 18
rows with zero operational failures or retries. The canary cost $0.0004068504 and the
scored panel cost $0.0571252374, for $0.0575320878 total with exact accounting.
All 13 V1 malformed-action failures disappeared; 13 V1 invalid trajectories reached
award submission in V2.

V2 produced 10/18 feasible allocations: 3/3 quality/refund, 3/3 working-capital,
2/3 variant-substitution, 1/3 deadline/cost, and 1/3 service-defer. MOQ/capacity
remained 0/3 because every award exceeded both selected offers' capacities, and one
variant-substitution row used an unknown supplier ID. Four submitted awards still
failed minimum service.

The primary adaptive V2-minus-V1 contract-recovery contrast increased feasibility by
0.2778, but its six-world interval [-0.1667, 0.7222] includes zero. The exploratory
V2-minus-unscaffolded-control contrast was +0.3889 feasibility ([0.1111, 0.6667]),
+7.0556 completed kits ([2.1111, 12.6667]), +$23.4162 contribution margin
([$3.4540, $49.4385]), and -$23.4162 regret ([-$49.4385, -$3.4540]). These are strong
development-panel effects, not confirmatory mechanism estimates, because V2 was
selected after inspecting V1 on the same worlds.

Further prompt edits on these six cases are saturated. The next high-value campaign
is a held-out confirmatory panel with new economic worlds, opaque/reordered supplier
IDs, and several cases where a feasible award requires splitting demand across
capacity-limited offers. It should freeze V2 unchanged and include the unscaffolded
control so transfer, supplier-ID robustness, and split-capacity execution can be
estimated without additional prompt tuning.

### Frozen targeted Qwen holdout

That next campaign is frozen as
`procurement_allocation_qwen3_235b_google_holdout_v1`. It contains six new opaque
economic worlds: two single-component splits, one dual-component split, one
multi-unit BOM split, one capacity-limited 18-kit minimum-service allocation, and
one budget-limited 18-kit allocation. All six have new economic-world digests
relative to the development, prior confirmatory, and risk-gate panels. Their exact
oracles are positive, use only public quote/sample/award actions, and require no more
than the declared ten actions.

The Qwen3 235B Google route, model revision, Minimal Chat harness, structured action
schema, verifier, retry policy, six opaque cases, and three inference seeds are held
fixed. The only paired intervention is the prompt: unscaffolded control versus the
unchanged constraint-ledger V2 prompt. Supplier identifiers and display names are
opaque in both arms, and listing order is deterministically shuffled before either
prompt sees a case.

The frozen plan digest is
`5ae0b91427f07c024120de0e96698ceafe1343c55d95e07b867b5cc8c479efde`.
It declares 36 scored trajectories, two unscored prompt-specific canaries, a
$0.94704 conservative total ceiling, and a $1.14 hard ceiling. Execution is
sequential and checkpoints every six rows. No efficacy inspection or early stopping
is permitted; any operational failure seals the affected attempt.

The independent unit is the economic world. Three seeds are averaged within world,
then V2-minus-control effects are reported for feasibility, completed kits, margin,
and regret with a deterministic six-world cluster bootstrap. The preregistered
diagnostic support rule requires the regret interval upper bound below zero and the
feasibility interval lower bound at least -0.05. That rule affects interpretation,
not eligibility: any complete, digest-matched, receipt-replayed result with exact
cost accounting is published, including a null or adverse effect. Because the worlds
were targeted from prior failures, even a supported result is a residual-capability
transfer diagnostic rather than broad confirmatory evidence.

#### Observed targeted Qwen holdout result

Both canaries were admitted and all 36 scored rows completed and receipt-replayed
with zero operational failures and exact accounting. The control arm had one bounded
provider retry; V2 had none. Control scored cost was $0.0527916708, V2 scored cost
was $0.0590797746, and the two canaries cost $0.0006390252, for $0.1125104706 total.
Median trajectory time was 14.00 seconds for control and 10.84 seconds for V2.

The preregistered residual-capability support rule was not met. V2-minus-control
effects after averaging seeds within each world were +0.0556 terminal feasibility
(six-world interval [0.0000, 0.1667]), +2.7222 completed kits ([-1.8333, 10.0000]),
-$0.3611 contribution margin ([-$0.7861, $0.0167]), and +$0.3611 regret
([-$0.0167, $0.7861]). The regret interval upper bound is not below zero. The one
fail-to-pass transition was a defer, not a purchase: neither arm produced any
feasible award.

V2 did improve action-contract discipline. Control had five malformed procurement
actions; V2 had none. Both arms made zero supplier-targeting attempts with an
unknown opaque ID. V2 reached 17 award submissions versus 13 for control, but this
did not translate into constraint-aware allocation. Across the five worlds that
require a split, control submitted ten awards and V2 submitted fourteen; neither arm
submitted a single award that split one component across multiple offers. Control
recorded 14 over-capacity line violations and V2 recorded 15. Both arms exceeded the
cash budget in all three budget-limited replicates by ordering the 20-kit target
instead of the feasible 18-kit minimum-service quantity.

The most informative result is therefore a separation between procedural compliance
and economic decision competence. The frozen V2 procedure reliably eliminates the
earlier JSON/action-field failures and reaches terminal decisions, but the model does
not carry observed capacity, order-step, budget, and target-versus-minimum constraints
into final award quantities. Additional wording on the same procedure is unlikely to
be high value. A next test should change the decision representation or action
interface—for example, a typed allocation worksheet or verifier-visible pre-award
constraint check—rather than tune this prompt again.

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

## Regret decomposition over published GLM bundles

The buyer objective is additive, and every tracked evidence row carries its parsed
action trace. `regret_decomposition` re-drives each published GLM trajectory through
the deterministic environment with no provider calls, recovers the full award
evaluation, and splits each feasible award's regret exactly into term gaps against
the recomputed full-information plan: lost revenue, excess purchase, shipping, duty,
working-capital, information, return-freight, and refund-financing cost, lost refund
recovery, and shortfall penalty. The replay must reproduce the published
feasibility, margin, regret, and kit count within $0.000001; any mismatch is an
integrity failure. Infeasible, deferred, and failed rows are categorized, not
decomposed, because their regret is the whole bound.

The analysis covers eight report files from four bundles: the development v2 and
blinded v3 Morph runs, both strategy-scaffold v4 surfaces, and all four confirmatory
v2 arms. All 216 rows replayed exactly and all 101 feasible awards decomposed with
zero residual. The pooled result is descriptive over 29 curated worlds with mixed
prompts, surfaces, and routes; the economic world remains the independent unit and
no inferential ranking is implied.

### Observed decomposition

Feasible awards carry $1,250.81 of regret, a mean of $12.38 per row; seventeen rows,
all under the V4 scaffold on confirmatory worlds, reached the bound exactly. Excess
working-capital cost accounts for 61.0% of feasible regret, lost revenue for 20.5%,
shortfall penalty for 10.9%, and lost refund recovery for 7.2%. Purchase price and
information cost are slightly negative contributors: the model often pays less per
unit and spends less on quotes and samples than the oracle, but loses more on
financing and completed kits.

The working-capital gap is a negotiation gap. The oracle award plan uses a
negotiated counter in 67 of the 101 feasible rows, almost always to extend payment
terms; the model submitted an award on a counter-improved offer in 7. Both
payment-terms-counter surfaces in the confirmatory panel show a mean feasible regret
of $48.63 with $48.27 from working capital alone, and the development and blinded
working-capital worlds show $32.48 with $34.28 from the same term. Unscaffolded
confirmatory control rows never used an accepted counter; the V4 scaffold rows used
one in six of 39.

The model matched the oracle supplier set in 75 of 101 feasible rows but matched
quantities in only 33, and on development worlds it matched quantities in none. The
remaining revenue and shortfall-penalty regret comes from under-ordering relative
to yield on the quality/refund worlds and from awarding to a slower supplier on the
service-defer worlds. The negotiated-MOQ confirmatory worlds lose $12.00 per row in
purchase cost from accepting the base MOQ price instead of countering.

This changes what the next procurement intervention should target. Prompt work so far
has addressed award feasibility, which is where most total regret still sits, but on
the feasible margin the dominant unexercised lever is the payment-terms counter that
the case was designed to test. The tracked bundle is
`evidence/procurement_allocation_glm_regret_decomposition_v1/`.

Reproduce it without provider calls:

```bash
python -m aeread_families.procurement_allocation.regret_decomposition

python -m aeread_families.procurement_allocation.regret_decomposition \
  --publish \
  --publication-root evidence/procurement_allocation_glm_regret_decomposition_v1
```

## Frozen negotiation-worksheet treatment

The decomposition selects the next adaptive treatment. It holds the GLM 5.3
Flash/Parasail route, Minimal Chat harness, structured action contract, verifier,
retry policy, twelve confirmatory worlds, both presentation surfaces, and the three
confirmatory inference seeds fixed. It changes only the buyer prompt by appending a
working-capital worksheet to the frozen V4 procedure: compute working-capital cost
per formal offer from the visible financing rate, horizon, and payment terms; rank the
five counterable terms by computed saving; counter on the single largest term with
every other proposal field null; request payment terms equal to the horizon first
and two-thirds of it once on rejection; and award only on each supplier's newest
offer id.

The paired control is the sealed confirmatory V2 treatment arm on each surface,
bound by file and artifact digest, so no control rows are re-run. Rows pair by exact
case id and inference seed. The campaign ID is
`procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v1`, the
worksheet prompt digest is
`29b5e6c336ad01d06e21fa48c723a6eed3c94e11e698f8fa7b481e0f0983d3d2`, and the plan
digest is `dddf5f52f00c9e3667af74da6448087c5d979474dc49f99b3cde8354d3be043a`. It
declares one unscored admission canary, 72 scored rows in six twelve-row checkpoints,
a $1.11 conservative total ceiling, and a $2.19 hard ceiling.

The preregistered primary estimand is worksheet-minus-V4 regret averaged equally over
surfaces within each world, with a twelve-world cluster bootstrap. Support requires
the regret interval upper bound below zero and the feasibility interval lower bound
at least -0.05. Secondary outcomes are the working-capital term from the regret
decomposition on feasible awards in each arm, accepted-counter counts, feasible
awards placed on counter-improved offers, and the single-field proposal share. Because
the treatment was chosen after inspecting the decomposition on these same worlds, a
supported result is development evidence, not a holdout confirmation.

```bash
python -m aeread_families.procurement_allocation.negotiation_worksheet_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v1/qualification_attempt_001
```

Add `--execute --max-spend-usd 2.19` after loading `OPENROUTER_API_KEY`, continue
each failure-free checkpoint with `--resume`, and publish with `--publish-only` to
`evidence/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v1/`.

### Worksheet operational audit

Attempt 001 admitted the canary, completed one row, and sealed on a typed provider
`timeout` on the first call of row two with $0.0033577335 spent. Attempt 002 was
interrupted by the operator before any scored row and is set aside. Attempt 003
completed seven rows and sealed on three consecutive HTTP 429 responses inside 17
seconds, exhausting the confirmatory three-attempt bound, at $0.0201324915. Attempt
004, under the identical frozen plan in a later window, admitted the canary and
completed all 72 rows in six failure-free checkpoints with zero operational failures.
No partial efficacy result was inspected before attempt 004 qualified.

### Observed worksheet result

Attempt 004 cost $0.199348479 including the canary, with exact accounting and every
row receipt-replayed. The preregistered support rule was not met. Worksheet-minus-V4
regret averaged over surfaces was -$3.82 per world with twelve-world bootstrap
interval [-$12.69, $4.48]; the interval includes zero. The feasibility guardrail
held at +0.0556 ([-0.0278, 0.1667]). Completed kits moved -0.29 ([-1.40, 0.82]).
Feasibility transitions were 4 fail-to-pass and 2 pass-to-fail on each surface.

The mechanism did what it was built to do. All 58 worksheet counters proposed a
single field, against zero of V4's 27; 22 were accepted against 12. On the
payment-terms-counter world the worksheet cut regret from $48.63 to $10.68 in five of
six rows by requesting 180-day terms, taking the rejection, and settling at 120 days,
leaving $9.81 of working capital on the table against the private 150-day limit. Mean
working-capital excess on feasible awards fell from $7.25 to $1.48 on labeled worlds
and from $7.63 to $3.39 on opaque worlds. Multi-unit BOM, split-capacity rounding,
and landed-cost worlds also improved by $29.24, $17.09, and $10.62 per world.

The offsetting harm is concentrated and legible. On quality-refund-tail, negotiated
MOQ, and refund-counter worlds the worksheet lost $20.77, $16.32, and $5.63 per
world. In three of those rows the buyer countered and then submitted an award
without the exact-variant sample, converting a feasible V4 outcome into a
`sample_not_verified` failure worth the whole bound. In two refund-counter rows the
buyer awarded to a worse supplier after a single-term counter on price. The
worksheet's action-budget clause, which allows a counter only with three actions
remaining, is not sufficient to protect the sample step once two counters per
supplier are in play.

The result is therefore a partial transfer: the payment-terms lever is now used, and
the decomposition target it was built for fell, but a counter budget of two per
supplier competes with sampling inside the ten-action limit and the preregistered
overall rule does not clear. A follow-up should make the sample step a hard
precondition of any award before allowing counters, or cap counters at one per
supplier. The tracked bundle is
`evidence/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v1/`.

### Frozen negotiation-worksheet V2

V2 keeps V1's route, harness, contract, verifier, retry policy, twelve confirmatory
worlds, surfaces, seeds, paired sealed V4 control, support rule, and ceilings. It
changes only the worksheet ordering after V1 showed counters displacing the sample
step: a supplier must have a verified exact-variant sample before any counter against
its offer and before any award line, and one action is reserved for the award before
any counter is allowed. The campaign ID is
`procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v2`, the prompt
digest is `5ad918b8595e38a91c0784b842abebe6b8ce4215f29fb4a33416f82f5f2d5fb0`, and the
plan digest is `e7d002cd6a89607d56d2accc6149cd817f8e877840a1213efec2ae5d5beb37a2`. The
plan binds the V1 evidence manifest by file digest. V2 is selected after inspecting
V1 on the same worlds and remains development evidence.

#### Observed worksheet V2 result

Attempt 001 admitted the canary and completed all 72 rows in six failure-free
checkpoints for $0.2065382055 with exact accounting and full receipt replay. The
preregistered rule was not met on either check. Worksheet-minus-V4 regret averaged
over surfaces was -$0.28 per world ([-$7.37, $7.23]) and feasibility was -0.0139
([-0.0833, 0.0417]), so the guardrail's lower bound fell below -0.05. Completed kits
moved +0.99 ([-0.17, 2.49]). Labeled regret was -$2.23 ([-$9.42, $2.52]); opaque
regret was +$1.67 ([-$8.88, $15.50]).

The V1 harm mechanism is gone. Every one of V2's seven `sample_not_verified`
failures is a four-supplier split in the multi-unit-BOM and split-capacity worlds
where the buyer quoted four suppliers, sampled three, and awarded all four inside the
ten-action budget; none follows a counter, and the V4 control fails those same rows
the same way. All 45 counters were single-field and 24 were accepted, up from 12.
On the labeled payment-terms world all three seeds again reached $10.68 from
$48.63, and mean working-capital excess on labeled feasible awards stayed at $1.48.

The opaque surface exposes the next limit. On opaque payment-terms rows only one of
three seeds captured the saving, because with opaque supplier ids the buyer could not
tell the terms-flexible supplier from the terms-fixed one, spent its two counters on
the fixed supplier, and stopped; the labeled result therefore depends on the
supplier name leaking which supplier will accept longer terms. On the opaque
negotiated-MOQ world two seeds countered MOQ downward after sampling and then awarded
a quantity below minimum service, converting two feasible V4 rows into
`minimum_service_not_met` failures worth $111 each; that world alone moved +$32.72.
Two labeled refund-counter seeds chose the cheaper, lower-yield supplier without any
counter and lost $24 of revenue each.

Taken together, V1 and V2 show that the payment-terms lever is reliably usable once
the buyer knows which offer to counter, that sample-first ordering is compatible
with it, and that the remaining losses are quantity reasoning after a counter changes
MOQ and supplier selection under opaque labels. Further prompt wording on the same
procedure is unlikely to clear the preregistered rule; the next test should change
the decision interface, for example a verifier-visible pre-award quantity check or a
typed allocation worksheet, or should accept the presentation-surface dependence as a
measured property of this route. The tracked bundle is
`evidence/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v2/`.

## Verifier-visible pre-award check

Worksheet V1 and V2 established that the payment-terms lever transfers once the
buyer knows which offer to counter, and that the remaining losses are quantity
errors after a counter changes MOQ, four-supplier splits with one unsampled line,
and supplier selection under opaque labels. Both were prompt changes on the same
action interface. The next treatment changes the interface.

The environment now exposes `check_award`. It takes the exact `award_lines` the buyer
intends to submit and returns, without ending the episode, whether that award would
be feasible, the violations it would raise, and the completed kits, contribution
margin, and cash spend it would produce. It runs the same `evaluate_award` the
terminal score uses on the current formal offers and verified samples, so the
projection is exact. It consumes one action and no money or calendar time. Checks
are recorded in the observation and in the terminal state, and the public action
trace carries their lines. Existing cases, prompts, and sealed evidence are
unchanged: the control prompt never names the action, sealed rows never emitted it,
and replay of every published row is byte-identical.

### Frozen pre-award-check treatment

The campaign holds the GLM 5.3 Flash/Parasail route, Minimal Chat harness, structured
action contract, verifier, retry policy, twelve confirmatory worlds, both surfaces,
and the confirmatory inference seeds fixed. The prompt is the frozen worksheet V2
procedure plus one step: reserve one check and one award, never submit an award that
has not passed a check with no violations, and fix the lines and re-check when the
check reports violations. The paired control remains the sealed confirmatory V2 V4
arm, bound by file and artifact digest, with rows paired by case id and seed.

The campaign ID is
`procurement_allocation_glm53_flash_parasail_pre_award_check_v1`, the prompt digest
is `600828117b31f363232085cfcf088bfa20ba0207adeed05e83255c55f5f7a871`, and the plan
digest is `70bef7fca393f73d9b8134a6f944b4e43d4a9b0faf3c15d5e616081f9e145c6d`. It binds
the worksheet V2 evidence manifest, declares one unscored canary and 72 scored rows
in six checkpoints, and keeps the $1.11 conservative and $2.19 hard ceilings. The
preregistered support rule is unchanged: treatment-minus-V4 regret interval upper
bound below zero and feasibility interval lower bound at least -0.05. Secondary
diagnostics add the number of checks per row and the number of awards submitted
after a clean check on identical lines.

The control rows ran on an environment without `check_award`. Because the control
never emitted it, the difference is inert for those rows, but the estimated effect
bundles the new action with the instruction to use it. This remains adaptive
development evidence on worlds the treatment was selected on.

```bash
python -m aeread_families.procurement_allocation.pre_award_check_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm53_flash_parasail_pre_award_check_v1/qualification_attempt_001
```

#### Observed pre-award-check result

Attempt 001 admitted the canary and completed all 72 rows in six failure-free
checkpoints for $0.2672071875 with exact accounting and full receipt replay. The
preregistered rule is met. Treatment-minus-V4 regret averaged over surfaces was
-$28.15 per world with twelve-world bootstrap interval [-$56.02, -$4.58], and
terminal feasibility rose +0.389 ([0.167, 0.611]). Labeled regret was -$29.24
([-$56.79, -$5.92]) and opaque regret -$27.06 ([-$55.72, -$2.40]); there was no
pass-to-fail transition on either surface, against 13 and 15 fail-to-pass.
Completed kits moved -0.86 ([-4.31, 2.06]).

The check was used in every one of the 72 rows, 83 times in total, and 51 of the 53
submitted awards followed a clean check on identical lines. Feasible purchase
awards rose from 39 to 53. The gains sit exactly where the decomposition and the
worksheet campaigns located the losses: on-time-reliability worlds went from three
infeasible awards per surface to feasible awards at or near the bound (-$122.46 per
world), multi-unit BOM from -$117.73, and split-capacity rounding from -$68.77, in
each case because the first check reported the unsampled line, the order-step
violation, or the late supplier and the buyer fixed the lines before submitting.
The payment-terms saving held (-$31.61) and the working-capital term on feasible
awards fell to $1.10 labeled and $2.61 opaque.

Two limits are visible. Fifteen rows ended in an explicit defer after a single
failing check rather than a repaired award: all six cash-budget-counter rows, four
sample-lead-time rows, and one each on three other worlds. A feasible defer counts
as feasible under the preregistered rule but earns no margin, so these rows carry
the whole bound in regret; they are the same worlds V4 also failed, which is why
completed kits did not improve. The negotiated-MOQ world is unchanged at $12.66
per row: a check reports feasibility, not price, so it cannot surface the MOQ
counter the oracle uses.

Support here is a development result. The treatment bundles a new action with the
instruction to use it, the control never had the action, and the worlds are the
ones on which the intervention was selected. What it establishes is that a
verifier-visible pre-award check removes the quantity, sample, and service
failures that three prompt treatments could not, at a cost of one action per row,
and that the remaining regret is deferral under budget pressure and price
negotiation. A confirmatory claim needs held-out worlds and, ideally, a control
arm re-run on the same environment. The tracked bundle is
`evidence/procurement_allocation_glm53_flash_parasail_pre_award_check_v1/`.

