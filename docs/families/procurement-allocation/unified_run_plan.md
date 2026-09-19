# Unified continuous procurement execution plan

This replaces the unsupported arithmetic and claims in the supplied execution
plan. The objective remains six admitted economic worlds, a paired pilot, and a
single frozen 36-row comparison if every preceding gate passes. Source and
receipt identities from earlier campaigns remain unchanged.

## Measurement contract

The new campaign is `procurement_allocation_unified_regret_v1`. It binds
continuous regret, counter-based binomial sampling, offline continuous
admission, and the synthetic shortcut falsification tests together.
`runner.continuous_promotion_rule` requires a negative upper endpoint of the
paired world-bootstrap 95% interval for treatment-minus-control regret. It
also requires complete paired cells, replayed receipts, correct bound-minus-
margin accounting, and authorized treatment decisions. Binary award frequency
is reported as a diagnostic; it is not the economic promotion endpoint.

A sample establishes evidence eligibility and estimates quality. Sample counts
accumulate across requests; payout uses the hidden true quality. The environment
seed is recorded in each episode case and paired across arms. Inference seeds
are recorded separately. Merely changing an inference seed does not change the
sampling stream.

`counter_feedback=field_specific` identifies rejected price, MOQ, payment,
refund-window, and return-freight terms without revealing private limits.
Legacy cases retain their historical reply text. Lead time is not a counterable
field in the existing action contract. Promotional `verbal_bias` already affects
public listings; regression tests ensure it cannot alter binding quote terms.

## Production evidence and its limits

The [frozen grounding case](../../../cases/procurement_grounding_v1/dev/procurement_grounding_231_projects.json)
records 497 search-card SKU rows, 231 project BOMs, 341 named search-card
suppliers, **252 SKU outreach assignments**, 30 captured conversation threads,
and nine quote suppliers. Assignments are not 252 independently observed
messages. Quote records do not establish binding commercial agreements.
Exact-variant screening is not physical sample testing. The frozen reference
readiness decision is `defer_bulk_order`.

The new markets use component identities from that snapshot. Supplier prices,
quality rates, sample counts, budgets, and causal relationships are explicitly
synthetic. No simulation result certifies a real supplier or authorizes an order.

## Gated sequence

| Stage | Required evidence | Stop condition |
|---|---|---|
| 0: integration | PR #146 integrated with the continuous rule, shortcut falsification, field-specific feedback, and the full provider-free suite | Any regression, stale implementation pin, or failing falsification |
| 1: offline admission | Exactly six selected worlds; all candidate outcomes and rejections retained; at least three distinct environment seeds; no paid calls | Fewer than six admissions, duplicate economic worlds, a floored reference, trivial greedy policy, or spread below materiality |
| 2: route and paired pilot | Two unscored prompt-specific canaries; first full trajectory per arm; six worlds × two environment seeds × two arms = **24 pilot rows**; receipt replay and measured variance | Operational failure, incomplete pairing, no sampling dispersion, token/latency excess, or uncertain billing |
| 3: confirmatory freeze and execution | Frozen prompts, route/revision, source pins, selected cases, analysis, seeds, ordering, budget, and digest; six worlds × three new seeds × two arms = **36 rows** | Failed precision or projected-cost gate; any post-freeze change requires a new identity |
| Publication | Every row traced to sealed receipts and score replay; world-bootstrap interval, rates, missingness, and billing reported | Missing or unverifiable receipt; unsupported broader claim |

A trajectory consists of multiple provider calls. Neither 24 rows nor 36 rows
means that many API calls. Canaries add calls and are counted separately. The
first pair of pilot trajectories supplies the full-trajectory gate, avoiding an
extra scored pair. No retries or alternative provider substitutions are allowed.

The driver reserves a conservative cost allowance before each dispatch and
records actual returned charges. An ambiguous request keeps its reservation and
stops dispatch; it is never silently retried. The initial implementation applies
the supplied **$0.35 ceiling to all paid activity combined**. The original
$0.08/$0.25 amounts are unverified estimates, not measured bills or guarantees.
If the pilot projects a larger total, execution stops before confirmation.

## Admission and selection

The reference is `replay_best_qualified`, a public-observation policy, **not the
certified optimizer**. The certified full-information bound is computed by the
separate enumerator. The reference ranks public displayed prices, uses only
acquired evidence, and awards its qualified suppliers. The comparison baseline
is `displayed_price_greedy`.

The materiality scale is explicitly the certified full-information contribution
margin, rather than the magnitude of observed regret. Admission requires both
material continuous dispersion and a mean policy gap of at least 15% of this
scale. The reference must form a feasible award on at least one screened seed.
Policy rates in an offline manifest are labeled as such; they are not live-model
control rates.

The fixed V2 candidate generator produces 96 distinct markets before any live
model outcome is observed. It varies BOMs, private yields, sample prices and
precision, commercial terms, cash, and penalties. The direction of the public
quality signal varies by market. Candidate order is fixed; select the first six
passing worlds. Twelve environment seeds screen each candidate. Every rejected
world is retained, rather than adjusting the admission threshold to fill a panel.
These are curated, admission-selected worlds: inference is scoped to the fixed
panel, not the population of procurement markets.

Earlier offline attempts are retained under the ignored operational run root:
24 existing worlds admitted three; expanding to 44 still admitted three; a
48-world prototype admitted five and was superseded because its public signal
had one direction. These were provider-free authoring diagnostics, not model
experiments or confirmatory evidence.

## Sample size and power

Six worlds are six clusters, not 36 independent observations. Average the three
paired seed differences within each world before resampling worlds. Three seeds
reduce the contribution of independent within-world noise under the stated
variance model; they do not by themselves establish diminishing returns or power.

The supplied claim “80% power at d ≥ 1.15” has no supporting calculation.
As a sensitivity check, a two-sided paired t-test with six pairs has approximately
**61.94% power at d=1.15** and needs **d≈1.4345 for 80% power**, assuming normal
paired world effects. These numbers are not bootstrap power, and the historical
$28.50/$54.92 gaps are not standardized effect sizes without their variances.

The executable pilot instead declares a meaningful effect of 15% of the mean
certified margin, estimates paired world dispersion, and simulates the
percentile-bootstrap decision under independent normal world effects at that
estimated dispersion. It records 1,000 simulations, 2,000 bootstrap resamples per
simulation, the RNG seed, and a Wilson lower bound for simulation uncertainty.
Freeze requires that lower bound to reach 80%. This is a **conditional planning
sensitivity**, with uncertain pilot variance and distribution assumptions; it
is not proof of unconditional population power. The final comparison uses
50,000 paired world-bootstrap resamples. A failed precision gate is a result to
report, not a reason to retune the six-world panel after observing model outcomes.

## Reproduction

From the repository root, using an environment with the project dependencies:

```sh
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m aeread_families.procurement_allocation.continuous_campaign \
  --generated-pool \
  --output runs/procurement_allocation/unified_regret_v1/screen_final.json \
  --selected-case-output cases/procurement_allocation_v1/continuous_candidates_v2/opaque
PYTHONPATH=src python -m aeread_families.procurement_allocation.continuous_execution \
  --screen runs/procurement_allocation/unified_regret_v1/screen_final.json \
  --cases cases/procurement_allocation_v1/continuous_candidates_v2/opaque \
  --validation runs/procurement_allocation/unified_regret_v1/validation.json \
  --run-root runs/procurement_allocation/unified_regret_v1/attempt_001 \
  --stage pilot
```

The validation JSON binds the successful full-suite log path and SHA-256, exit
code, passed-test count, current implementation pins, and successful synthetic
falsification. `--stage confirmatory` uses the same root and consumes the sealed
pilot; it cannot bypass the precision or cost gate. No live command should be
run with a fabricated validation record. An orphaned execution lock or uncertain
billing requires an audit before any further dispatch.

The original [failure register](../../../evidence/procurement_allocation/procurement_allocation_failure_register/)
is retained. The 2026-09-19 report and its QC manifest include nested evidence
bundles that the old scanner missed. All source-report hashes are recorded;
the register excludes its own derived output so regeneration is stable.
