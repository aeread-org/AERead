# Housing V1 QC profile

**Standard:** [AERead benchmark QC](../../operations/benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](../../operations/experiment_campaign_sop.md)
**Status:** case-specific profile;
`development_case_qualification=passed` and
`environment_and_verifier_qc=passed`, while
`normative_housing_profile=partial`. The one-world model-to-model integration
slice is complete with typed missingness, but variance, freeze, and
confirmatory gates remain incomplete, so normative promotion is blocked.

This profile binds the shared QC gates to Housing V1. Requirements inherited
from the standard are not repeated unless Housing supplies a specific
implementation, threshold, role, policy, or artifact.

## 1. Task-distribution admission

The admitted confirmatory setting uses six tenants, four listings, four rounds,
private tenant values, private landlord reservation costs, and the exact
assignment upper bound. Development qualification may use smaller dimensions but
must be labeled as an operational slice.

Validate for every world:

- positive tenant, listing, and round counts;
- rectangular, finite value, cost, ask, and surplus arrays;
- tenant and listing identities matching the declared dimensions;
- deterministic regeneration from generator version, parameters, and seed;
- finite assignment upper bound `U >= 0`;
- unique seed and canonical world-content digest;
- market tightness, congestion, `common_weight`, oracle surplus, naive-baseline
  score, and baseline gap;
- disjoint development and confirmatory seed domains and declared held-out
  parameter combinations.

Worlds with `U = 0` receive `degenerate_upper_bound`, have no normalized score,
and remain visible outside normalized-score inference.

The exit artifact contains the ordered world manifest, content hashes,
difficulty facts, clusters, split labels, and typed admissions or exclusions.

## 2. Environment and verifier

Maintain Housing goldens for:

1. a legal trajectory realizing a known efficient allocation;
2. a legal but economically poor or negative-welfare allocation;
3. unknown listings, fabricated offers, excess holds, and tampered commits;
4. malformed phase output and a provider failure;
5. a world with `U = 0`.

Cross-check `assignment_oracle` against brute-force enumeration on small
rectangular worlds, ties, all-negative surplus, and unmatched seats.

Replay must rebuild `contact -> respond -> commit` from sealed parsed actions and
legality evidence, then recompute assignment, signed rents, per-seat payoffs,
social welfare, IR violations, wasted contacts, and `within_case_score`. Tenant
observations must omit other tenant values and landlord costs; landlord
observations expose only their own cost and inbox.

## 3. Construct validity and baselines

Run the following policies through the active multi-round interface:

| Policy | Housing interpretation |
|---|---|
| No-op | Every eligible seat passes; feasible lower-policy anchor |
| Random | Seeded legal target, price, response, and commit choices |
| Naive | Favourite available listing with no opponent adaptation |
| Adaptive | Uses rejection history, availability, holds, and round history |
| Oracle-informed | Evaluator-only diagnostic for the attainable mechanism ceiling |

Before model results, freeze the beatability threshold and run unilateral or
counterfactual deviations from the comparison baseline. Report allocation
efficiency, tenant and landlord payoff, IR violations, wasted contacts, action
validity, and answer rate separately.

Housing shortcut checks include lowest-listing-ID targeting, ask-only bids,
tenant-seat priority, narrow seed memorization, public-board leakage, and
policies that gain welfare only by accepting individually irrational matches.

## 4. Attribution and experimental controls

Keep these blocks separate:

| Block | Assignment | Valid claim |
|---|---|---|
| Focal tenant | One subject, five fixed background tenants, fixed landlord profile; rotate through all six tenant seats | Individual behavior and externality against that background |
| Tenant population | One profile fills all six tenant seats; other roles fixed | Homogeneous tenant-population policy performance |
| Cross-play | Every declared subject-by-landlord-profile pairing | Robustness over the frozen opponent panel |
| Same-model self-play | Same base model in tenant and landlord roles through distinct role profiles | Joint role-conditioned system behavior |

The opponent panel contains a deterministic landlord anchor and at least two
version-pinned live model families admitted through the common harness. Scripted,
cross-model, and same-model results remain separate.

Pair conditions on world, replicate, and focal-seat rotation. Rotate condition
order by world. Treat the world as the independent cluster; seats, opponents,
rotations, and replicates within it are correlated.

### Housing profile admission

Tenant and landlord profiles for the same base model are distinct. Each profile
seals model revision, route, quantization, harness, role prompt, schemas, tools,
memory, reasoning, sampling, budgets, retry policy, and pricing.

Run three probes per action schema:

- tenant: `contact` and `commit`;
- landlord: `respond`.

Admission requires valid structured actions, exact route verification, complete
usage and billing evidence, and no hidden retry or repair. A failed profile stays
visible and unranked. One full trajectory per admitted subject-opponent
condition is the next campaign gate.

Before paid cross-play, contract tests must prove that only the declared factor
varies, routes follow seat assignments, focal rotations preserve world and
background seats, role accounting reconciles, replay is exact, and incomplete
opponent panels cannot enter a rank.

## 5. Confirmatory reliability and publication

Use the world as the independent unit. Complete a predeclared paired variance
pilot, select confirmatory world count from paired world-level variance and a
declared minimum meaningful effect, then freeze cases, seeds, profiles, prompts,
retry rules, execution order, analysis, stopping, implementation pins, and cost
ceiling.

Average stochastic replicates within worlds. Preserve operational failures as
typed missingness and never selectively rerun one condition. Report paired
world-level intervals, the complete subject-by-opponent matrix,
opponent-weighted means, worst-opponent results, reliability, exclusions, and
missingness. Scripted anchors and self-play remain separate from live-opponent
aggregates.

Publish canonical profiles, model features, benchmark results, run/task/call
facts, trajectories, and a digest-bound manifest.

## 6. Current implementation coverage

| Gate | Current coverage | Main blocker to `passed` |
|---|---|---|
| Task-distribution admission | Frozen 18-configuration development sweep, canonical case/configuration facts, and disjoint held-out parameters and seeds | The confirmatory holdout remains sealed and must not be executed before confirmatory freeze |
| Environment and verifier | Oracle enumeration, zero-bound quarantine, replay, and the six-scenario `housing_qc_goldens_v1` receipt bundle passed | No blocker for development campaigns; re-run only when a bound environment, verifier, runner, or golden contract digest changes |
| Construct validity | Active no-op, seeded random, naive, adaptive, and oracle-informed audit implemented across the frozen development grid; eligibility and selection thresholds are frozen; V8 produced 11 valid live trajectories | A multi-world pilot must measure whether model policies reliably separate from the declared baselines across independent worlds |
| Attribution and controls | The V8 fixed-harness subject-by-opponent matrix attempted all 12 cells with exact route and replay evidence; one GLM self-play cell is typed timeout missingness | Focal-seat rotation remains a separate future block; no cross-play or self-play result is rankable before a complete multi-world design |
| Confirmatory reliability | Generic gate and analysis primitives only | No Housing variance pilot, power calculation, freeze artifact, or campaign gate history |

Housing may run development and qualification experiments, but it must not
present a confirmatory model leaderboard until every applicable gate has sealed
`passed` evidence.

## 7. Provider-free case-configuration sweep

[`housing_case_config_sweep_v1`](../../../configs/housing_case_config_sweep_v1.json)
qualifies the case distribution before comparing models. It crosses three
market-tightness strata, three `common_weight` values, and two round budgets over
16 paired development seeds. The harness is not a factor in this sweep: no model
or provider is invoked, and every policy drives the Housing state machine
directly.

The frozen rule first excludes configurations with duplicate or degenerate
worlds, generator or oracle failures, insufficient naive-policy beatability, or
an uninformative naive-score envelope. Among admitted configurations, it chooses
one per market-tightness stratum by distance to the declared baseline-difficulty
target. This is case admission, not a model leaderboard.

Run it with:

```bash
python -m aeread_families.housing.case_sweep \
  --contract configs/housing_case_config_sweep_v1.json \
  --run-root runs/housing_case_config_sweep_v1
```

The output contains:

- `housing_case_facts.csv`: one row per development configuration and world;
- `housing_config_summary.csv`: one reportable row per candidate configuration;
- `selected_development_configs.json`: the predeclared selection result;
- `fact_manifest.json`: source-contract identity, implementation pins, row counts,
  and artifact digests;
- `sweep_summary.json`: completion, provider-call, cost, and holdout status.

The frozen development result is published in
[`evidence/housing_case_config_sweep_v1`](../../../evidence/housing_case_config_sweep_v1/).
All 288 development worlds completed without a provider call; 14 of 18
configurations passed the declared admission rule. The selected panel is:

| Stratum | Configuration | Tenants / listings | Rounds | `common_weight` | Median naive score | Median oracle gap |
|---|---|---:|---:|---:|---:|---:|
| Mild | `mild_cw085_r2` | 6 / 5 | 2 | 0.85 | 0.7895 | 0.2105 |
| Moderate | `moderate_cw085_r2` | 6 / 4 | 2 | 0.85 | 0.8108 | 0.1892 |
| Severe | `severe_cw030_r2` | 6 / 3 | 2 | 0.30 | 0.7920 | 0.2080 |

The selected configurations are development cases, not confirmatory cases. The
four excluded settings remain visible in the configuration fact table with their
failed eligibility fields; they are not silently dropped from the record.

`world_sha256` identifies the generated private-value world.
`case_config_sha256` additionally binds the round budget, so the same paired world
may correctly appear in two distinct executable case configurations. The world
seed is the independent cluster; configuration is a paired within-world factor.

The confirmatory holdout declares disjoint seeds and unseen dimensions,
round counts, and preference-correlation values. This runner never materializes
them. Opening that holdout requires a new campaign identity after sample size,
models, prompts, retry rules, analysis, and stopping are frozen.

The testing sequence after this sweep is:

1. admit and pin the candidate model profiles;
2. run a small model sensitivity slice on the three selected development
   configurations using one fixed harness as infrastructure;
3. run the paired variance pilot and power the confirmatory sample;
4. freeze the complete model campaign;
5. execute the holdout exactly once.

The earlier population campaign below predates this sweep. Its results remain
valid as development evidence for its own fixed setting, but its `6 x 4`, four
round, `common_weight=0.6` case must not be silently relabeled as the selected V1
case panel. A model comparison over the selected configurations needs a new
campaign identity.

## 8. V1 fixed-harness model sensitivity

[`housing_model_sensitivity_v1`](../../../configs/housing_model_sensitivity_v1.json)
is the first model-to-model integration slice over the three selected
development configurations. It holds `minimal_chat/1.0`, prompts, tools,
memory, reasoning, sampling, retry policy, role budgets, provider route, and
inference seeds fixed. It crosses GLM 5.3 Flash and DeepSeek V4 Flash in all
four tenant-population-by-landlord-population pairings. There is no scripted
condition and no harness comparison in this campaign.

The driver pins tenant and landlord action-budget ceilings to the admitted V0
profile values. Those ceilings are profile controls, not the Housing episode
horizon; fixing them prevents case size from accidentally changing the model
profile identity while the selected environment configuration varies.

Run the free gates, then the paid integration gate:

```bash
python -m aeread_families.housing.model_sensitivity \
  --contract configs/housing_model_sensitivity_v1.json \
  --run-root runs/housing_model_sensitivity_v1 \
  --through provider_free

python -m aeread_families.housing.model_sensitivity \
  --contract configs/housing_model_sensitivity_v1.json \
  --run-root runs/housing_model_sensitivity_v1 \
  --through live
```

Set `OPENROUTER_API_KEY` locally for `live`. The live stage has a $0.05 hard
campaign ceiling, reserves $0.02 before starting each trajectory, seals each
attempt, retains typed operational missingness, and stops on route, provider
contract, replay, or cost-integrity failure. It does not selectively retry a
failed trajectory.

The 2026-09-02 execution passed design and provider-free validation, then
stopped during the mild configuration. Two cells exhausted their declared
action attempts on upstream GLM rate limits; the third returned a DeepSeek
choice without text and triggered the provider-contract stop. Zero trajectories
completed, nine were never started, and recorded cost was $0. This is a failed
integration/reliability gate, not evidence of Housing performance and not a
model ranking. The sanitized record is
[`qualification.json`](../../../evidence/housing_model_sensitivity_v1/reports/qualification.json).

Because only one world cluster was planned, even a complete run would remain a
descriptive integration slice with no estimable uncertainty. A variance pilot
can begin only after a complete live matrix passes under one frozen campaign
identity.

## 9. V2 alternate-backend qualification

[`housing_model_sensitivity_openrouter_alt_v2`](../../../configs/housing_model_sensitivity_openrouter_alt_v2.json)
tests whether changing only the pinned inference endpoints can clear the
reliability gate that blocked V1. It retains the V1 selected cases, prompts,
fixed `minimal_chat/1.0` harness, tools, memory, reasoning, sampling, action
budgets, condition matrix, and one-world development-only claim scope. It uses
new profile identities because endpoint provider and pricing are part of an
agent profile.

The 2026-09-02 route snapshot selected Novita FP8 for GLM 5.3 Flash and
OpenInference FP8 for DeepSeek V4 Flash. Both routes passed the free catalog
preflight for canonical model identity, parameter support, status, and frozen
prices. Profile admission then attempted all 18 declared probes without hidden
retry: GLM/Novita passed 0 of 9 and returned nine HTTP 404 failures;
DeepSeek/OpenInference passed 4 of 9, with four HTTP 429 failures and one
invalid admission action. Observed cost for successful calls was
`$0.0008403318`; failed-call billing was unavailable, so exact total cost is not
claimed.

The failed admission automatically blocked all 12 Housing trajectories. This
is backend qualification evidence, not a Housing score or model comparison.
See the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v2/reports/qualification.json).

The next attempt remains on OpenRouter and uses a new campaign identity, a fresh
catalog query, new route-bound profile hashes, and the same
admission-before-trajectory gate. Do not redirect V2 in place or retry only its
failed probes.

## 10. V3 OpenRouter-only route qualification

[`housing_model_sensitivity_openrouter_alt_v3`](../../../configs/housing_model_sensitivity_openrouter_alt_v3.json)
keeps OpenRouter as the gateway and tests a fresh route pair: Reka FP8 for GLM
5.3 Flash and Parasail FP8 for DeepSeek V4 Flash. V3 is a new campaign because
provider route, price, and profile identity are frozen controls. Its catalog
preflight also rejects endpoints whose completion limit is smaller than the
profile's frozen `max_output_tokens` value.

Run the gates with the local OpenRouter key:

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_alt_v3.json \
  --run-root runs/housing_model_sensitivity_openrouter_alt_v3 \
  --through provider_free

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_alt_v3.json \
  --run-root runs/housing_model_sensitivity_openrouter_alt_v3 \
  --through profile_admission

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_alt_v3.json \
  --run-root runs/housing_model_sensitivity_openrouter_alt_v3 \
  --through live
```

The 2026-09-02 free gates passed, including active route, canonical model,
parameter, price, and completion-limit checks. Admission attempted all 18
declared probes with no hidden retry. Four probes failed: Reka/GLM returned
three HTTP 429 failures, and one Parasail/DeepSeek commit response used the
invalid decision `pass` instead of the allowed `sign` or `walk`. The 14 passed
probes plus the one billed invalid response reported `$0.0019847322`; the three
429 calls lacked billing, so exact total cost is not claimed.

The failed admission blocked all 12 Housing trajectories with zero additional
provider calls. This remains backend reliability evidence, not a Housing score
or model comparison. Do not selectively retry V3. See the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v3/reports/qualification.json).

For review without publishing raw model reasoning, the repository also keeps a
digest-bound set of three V0 trajectory examples: the upper and lower observed
completed live-opponent cross-play cells and the shortest operational failure.
The export includes event-seal roots, receipt identities, action summaries,
outcomes, costs, and limitations, while the complete provider responses remain
under ignored local `runs/`. See
[`selected_2026-09-02.json`](../../../evidence/housing_population_crossplay_v0/trajectories/selected_2026-09-02.json).

## 11. V4 strict-output OpenRouter qualification

[`housing_model_sensitivity_openrouter_alt_v4`](../../../configs/housing_model_sensitivity_openrouter_alt_v4.json)
keeps the selected cases and frozen minimal-chat controls while assigning fresh
route-bound profiles to Phala FP8 for GLM 5.3 Flash and Parasail FP8 for
DeepSeek V4 Flash. Both are pinned OpenRouter endpoints; the campaign neither
uses direct provider credentials nor permits automatic fallback. V4 also
strengthens catalog admission by requiring advertised `structured_outputs`
support because the runner sends a strict JSON schema.

The design, provider-free case, and live catalog gates passed on 2026-09-02.
Profile admission then completed all 18 predeclared probes with no hidden
retry. Parasail/DeepSeek passed 9 of 9. Phala/GLM passed 1 of 9: five responses
failed Housing action semantics by returning `action` where the frozen schemas
required `decision`, two calls failed the provider-response contract, and one
returned HTTP 429. The provider-reported cost was
`$0.0038987487`; three failed calls omitted billing, so exact total cost is not
claimed.

The failed joint admission blocked all 12 Housing trajectories with zero
additional provider calls. This is profile and backend qualification evidence,
not a Housing score or comparison. See the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v4/reports/qualification.json).

Do not selectively rerun V4 or interpret DeepSeek's admission success as a
Housing result. The next experiment should diagnose GLM's action-contract
failures provider-free before freezing another route-bound campaign.

## 12. V5-V7 action-contract and live qualification

V5 through V7 retain the same selected development cases, fixed
`minimal_chat/1.0` harness, and pinned NextBit/GLM plus Parasail/DeepSeek
OpenRouter routes. Each version has a new campaign identity because its frozen
action or retry contract changed.

V5 passed all 18 profile-admission probes for `$0.0025567542`. Its first live
GLM self-play trajectory completed with a descriptive within-case score of
`0.8879703073`. The next cross-play trajectory returned an OpenRouter choice
without text after eight provider calls. V5 classified that as a
`provider_contract` failure, stopped the matrix, and left ten cells unstarted.
See its tracked [`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v5/reports/qualification.json).

V6 made null or blank provider content a receipt-visible `empty_response` so
the application retry policy, rather than the adapter, owns retry decisions.
Admission then exposed a separate semantic hole in the V1 commit schema:
DeepSeek returned `decision=pass` with a non-null `hold_id`. Seventeen of 18
probes passed, and the failed gate blocked live execution. See its tracked
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v6/reports/qualification.json).

V7 binds conditional `oneOf` schemas that enforce decision-dependent fields
and explicitly wires timeout, output-token, attempt, and retry controls into
the live profiles. All 18 admission probes passed for `$0.0031975713`. Seven
of 12 live trajectories then completed with verified routes, complete provider
billing, and score replay; zero trajectories failed operationally. The gate
stopped at `$0.0361729071` because the frozen `$0.02` next-cell reserve would
breach the `$0.05` live ceiling. Four mild cells and three moderate cells are
present; the fourth moderate cell and all four severe cells remain unstarted.

The observed V7 scores range from `0.7917117782` to `0.9926657320`, but this is
not a leaderboard: the condition-by-configuration matrix is incomplete and has
only one world cluster. The digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v7/reports/qualification.json)
records the gates and stop. The separate
[`selected.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v7/trajectories/selected.json)
publishes parsed action counts, assignments, rents, welfare, latency, cost,
retry counts, and receipt/event digests for all seven completed trajectories;
raw provider responses and hidden reasoning remain under ignored local
`runs/`.

All four qualification records include a path-relocation amendment. The runs
executed before tracked evidence moved from `docs/evidence/` into standardized
top-level campaign bundles. Current configs point to `reports/` and `tables/`,
while the records preserve both the executed and current contract digests. The
provider-free sweep was deterministically republished under the new paths; its
world-fact table is byte-identical, while projection and manifest digests
changed to bind the new layout.

The next complete integration attempt requires a new campaign identity and a
cost ceiling sized from V7's observed per-cell costs. Do not carry V7's seven
cells into a new matrix or selectively execute only its five missing cells.

## 13. Frozen V0 population campaign

The first executable population campaign is
[`housing_population_crossplay_v0`](../../../configs/housing_population_crossplay_v0.json).
It compares GLM 5.3 Flash and DeepSeek V4 Flash as homogeneous tenant
populations against a scripted anchor and both live landlord profiles. The
scripted cells are controlled anchors, diagonal cells are self-play, and
off-diagonal cells are cross-play. Only the equal-weight mean over the two live
opponents enters the primary contrast.

Run gates in order; the driver resumes verified rows and records failed attempts:

```bash
python -m aeread_families.housing.population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --run-root runs/housing_population_crossplay_v0 \
  --through provider_free_validation

python -m aeread_families.housing.population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --run-root runs/housing_population_crossplay_v0 \
  --through full_trajectory

python -m aeread_families.housing.population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --run-root runs/housing_population_crossplay_v0 \
  --through variance_pilot
```

Set `OPENROUTER_API_KEY` locally before the paid gates. `full_trajectory` is an
integration gate, and `variance_pilot` is exploratory. Neither may be reported
as a model winner. A leaderboard becomes confirmatory only after the powered
sample, holdout, complete frozen matrix, and analysis are sealed at
`confirmatory_freeze`.

The application-level retry policy includes `empty_response` alongside length,
rate-limit, and provider-5xx failures. Each retry is a new sealed action attempt;
SDK retries remain disabled. This makes transient blank completions visible in
the receipt instead of either hiding them or failing an otherwise valid matrix.

Local V0 evidence created under campaign-history schema 0.1 must be migrated
explicitly. The migration keeps the exact source bytes as
`gate_history.v0.1.json`, rebuilds typed content-bound evidence references, and
then appends the required pre-freeze retry-policy invalidation before paid work:

```bash
PYTHONPATH=src .venv/bin/python -m aeread_families.housing.population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --run-root runs/housing_population_crossplay_v0 \
  --through full_trajectory \
  --migrate-legacy-history \
  --invalidate-from profile_admission \
  --changed-control retry_policy \
  --invalidation-reason "Add explicit receipt-visible empty-response retries"
```

Do not use the migration flag to erase or renumber failed attempts. If the
backup exists with different bytes, migration fails closed.

The 2026-09-02 requalification migrated the legacy history and appended that
invalidation, but the pinned DeepInfra GLM route then exhausted all four visible
attempts on the first tenant-contact admission probe. No Housing trajectory was
started, and the variance pilot remains blocked. The sanitized, digest-bound
record is
[`requalification_2026-09-02.json`](../../../evidence/housing_population_crossplay_v0/reports/requalification_2026-09-02.json).

Apply the campaign SOP's backend-escalation instruction before the variance
pilot. OpenRouter remains the backend; any provider-route change requires a new
campaign identity and fresh admission rather than an in-place backend swap.

## 14. Provider-free environment and verifier goldens

[`housing_qc_goldens_v1`](../../../configs/housing_qc_goldens_v1.json) closes
the development environment-and-verifier QC bundle with six deterministic
shared-runner scenarios: efficient, valid-but-poor, unauthorized, malformed,
provider failure, and zero upper bound. The invalid-action fixture emits valid
JSON and fails legality only; malformed output fails parsing; provider failure
is excluded as operational missingness rather than converted to a zero score.

Run and publish it without a provider key:

```bash
PYTHONPATH=src python -m aeread_families.housing.qc_bundle \
  --contract configs/housing_qc_goldens_v1.json \
  --run-root runs/housing_qc_goldens_v1 \
  --publish-root evidence/housing_qc_goldens_v1
```

All five valid receipts replay state and score exactly; the provider-failure
receipt has `replay_level=none`. The bundle made zero external calls and cost
`$0.00`. Review the digest-bound
[`qc_bundle.json`](../../../evidence/housing_qc_goldens_v1/reports/qc_bundle.json)
and its six sanitized receipt projections.

## 15. V8 complete-attempt model-to-model integration slice

[`housing_model_sensitivity_openrouter_alt_v8`](../../../configs/housing_model_sensitivity_openrouter_alt_v8.json)
keeps V7's three selected development configurations, one world seed, fixed
`minimal_chat/1.0` harness, role prompts, conditional schemas, retry policy,
and NextBit/GLM plus Parasail/DeepSeek routes. It raises only the predeclared
live ceiling and next-cell reserve, under a new campaign identity, using V7's
observed costs.

V8 passed the provider-free and catalog gates, then passed all 18 profile
probes with no operational failures or hidden retries for `$0.0029879091`.
It attempted all 12 frozen live cells. Eleven completed with exact replay and
complete provider billing; the mild GLM self-play cell timed out after 12
provider calls and is retained as excluded typed missingness. Live execution
cost `$0.0472764897`; combined provider-reported cost was `$0.0502643988`.

This is acceptable integration evidence, not a leaderboard. Only one world
cluster was attempted, uncertainty is not estimable, and the matrix has one
missing score. The next gate is a newly frozen multi-world variance pilot; do
not selectively rerun or impute the V8 timeout.

The digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v8/reports/qualification.json)
records every gate. The
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v8/trajectories/attempted.json)
projection retains all 12 attempts in frozen order, including parsed action
counts, outcomes, assignments, rents, role usage, costs, latency, failure
usage, and receipt/event digests. Raw provider responses and reasoning remain
only under ignored local `runs/`.

## 16. V9 multi-world variance-pilot admission result

[`housing_model_sensitivity_openrouter_alt_v9`](../../../configs/housing_model_sensitivity_openrouter_alt_v9.json)
froze the next four unused development world seeds across the same three case
configurations and four model-to-model conditions. This defines 48 planned
trajectories and four independent world clusters. Its primary estimand is the
paired world-level GLM-minus-DeepSeek contrast after equal weighting across
the three configurations and two opponent models. The design is exploratory
and cannot produce a leaderboard claim.

The design, provider-free, and catalog gates passed. Provider-free QC matched
all 12 case-world records to the canonical case-fact table and did not open the
confirmatory holdout. Profile admission passed 17 of 18 single-attempt probes;
the NextBit GLM landlord `housing_respond_v1` probe at probe index 1 returned a
typed HTTP 429 rate-limit failure. The gate recorded `$0.0031521699` in
provider-reported cost, with billing unavailable for the failed request.

Under the frozen no-selective-retry policy, that failure blocked all 48 live
trajectories. V9 therefore contains no Housing scores and no variance
estimate. It is publishable provider-reliability and gate evidence, not
integration or performance evidence. Continue only under a new campaign
identity after reviewing the route failure; do not rerun or impute the failed
V9 probe.

Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v9/reports/qualification.json),
the explicit zero-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v9/trajectories/attempted.json),
and the canonical
[`fact_manifest.json`](../../../evidence/housing_model_sensitivity_openrouter_alt_v9/tables/fact_manifest.json).
The fact manifest binds two reusable tables: frozen model/profile features and
all 18 sanitized admission outcomes. Raw provider responses remain only in the
ignored local run directory.

## 17. V10 Morph-route execution and protocol finding

[`housing_model_sensitivity_openrouter_morph_v10`](../../../configs/housing_model_sensitivity_openrouter_morph_v10.json)
kept V9's three configurations, four development worlds, four model-to-model
conditions, harness, prompts, schemas, sampling, action budgets, and analysis.
Only the GLM route changed from NextBit to Morph; DeepSeek remained on Parasail.
The frozen maximum exposure was `$0.41`, below the user-authorized `$5` budget.

Design, provider-free, catalog, and all 18 single-attempt profile-admission
checks passed. V10 then attempted all 48 frozen cells for a combined
provider-reported cost of `$0.15123042`. Thirty-one trajectories completed with
exact replay, route verification, and complete provider billing. The remaining
17 are retained as typed operational missingness: 11 rate limits, five
timeouts, and one transport failure. Every failed condition contained a Morph
GLM seat. These counts are route/session reliability evidence, not model-score
evidence.

No development world has all six GLM-subject and six DeepSeek-subject cells.
The paired-world count is therefore zero, variance is not estimable, and no
confirmatory sample size or leaderboard result can be produced. V10 also
revealed a campaign-control defect: after changing the GLM route, execution
proceeded from profile admission directly to the multi-world pilot instead of
recording the SOP-required full-trajectory gate. The publication marks this
explicitly as a protocol deviation rather than treating the 48 attempted cells
as a valid variance pilot.

Do not selectively rerun or impute V10. The next campaign must use a new
identity and, before any multi-world spend, complete one trajectory for each of
the four subject-opponent conditions on the selected routes. Only that gate may
promote the design to a newly frozen variance pilot.

Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_morph_v10/reports/qualification.json),
all-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_morph_v10/trajectories/attempted.json),
and the
[`canonical_fact_index.json`](../../../evidence/housing_model_sensitivity_openrouter_morph_v10/tables/canonical_fact_index.json).
The index binds 12 run-level `profiles.csv`, `model_features.csv`, and
`benchmark_results.csv` projections plus an explicit four-row paired-world
table. Raw provider payloads and reasoning remain only under ignored local
`runs/`.

## 18. V11 explicit full-trajectory promotion gate

[`housing_model_sensitivity_openrouter_deepinfra_v11`](../../../configs/housing_model_sensitivity_openrouter_deepinfra_v11.json)
implements the gate that V10 skipped. It freezes one selected development
configuration (`moderate_cw085_r2`), one previously unused non-holdout world
(`227922569`), and the four subject-opponent conditions. The runner writes this
stage under `full_trajectory/`, and promotion requires one completed trajectory
per condition. The claim scope is gate qualification only; no score comparison
or ranking is allowed.

V11 changed the GLM route to DeepInfra FP8 under a new campaign identity and
retained Parasail FP8 for DeepSeek. At catalog preflight, both routes were
active and matched the frozen model, parameters, completion limit, and price.
Design and provider-free validation passed, with the confirmatory holdout still
sealed.

Profile admission attempted all 18 single-attempt probes without SDK retries
or hidden repair. Parasail/DeepSeek passed 9 of 9. DeepInfra/GLM passed the
first six probes, then all three probe-index-2 schemas—tenant contact, tenant
commit, and landlord respond—returned typed HTTP 429 rate limits. The
provider-reported billed calls cost `$0.00200370555`; the three failed calls did
not expose billing, so this is not an exact total-charge claim.

Admission therefore blocked all four full trajectories with zero trajectory
provider calls. Do not rerun only the three failed probes or add pacing inside
V11. Any admission-pacing or route change requires a new campaign identity and
fresh profile hashes. Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_deepinfra_v11/reports/qualification.json),
the explicit zero-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_deepinfra_v11/trajectories/attempted.json),
and the reusable admission
[`fact_manifest.json`](../../../evidence/housing_model_sensitivity_openrouter_deepinfra_v11/tables/fact_manifest.json).

## 19. V12 preregistered paced full-trajectory gate

[`housing_model_sensitivity_openrouter_deepinfra_v12`](../../../configs/housing_model_sensitivity_openrouter_deepinfra_v12.json)
is a new campaign identity created in response to V11's admission-rate-limit
result. It does not retry or amend V11. V12 keeps the same selected
configuration, development world, four subject-opponent conditions, DeepInfra
and Parasail routes, schemas, prompts, sampling, retry ownership, and cost
ceilings.

The sole execution treatment added by V12 is a frozen provider-call scheduler.
Each route receives a 15-second minimum start-to-start interval, including a
15-second first-call delay. One scheduler instance is shared across profile
admission and the full-trajectory stage, so passing admission under a gentle
cadence cannot be followed by an unpaced trajectory burst. The scheduler
delegates exactly one call for each shared-runner request and owns no retry
policy. Its implementation file is digest-pinned in the campaign contract, and
each admission probe and trajectory records observed provider-call and pacing
wait counts.

V12 remains a one-world promotion gate. It may establish only whether every
frozen model pairing completes one replay-verified trajectory under the paced
execution condition. It cannot support a winner, model ranking, variance
estimate, or confirmatory claim. If any admission probe fails, all four
trajectories remain blocked; if any trajectory fails, the missing cell remains
typed missingness and is not selectively rerun.

The executed gate attempted all 18 admission probes. Parasail/DeepSeek passed
9 of 9 and DeepInfra/GLM passed 8 of 9. The first DeepInfra call passed after
147.14 seconds including the 15-second initial wait. Because the frozen policy
measured starts rather than completions, the next DeepInfra call received zero
additional wait and returned HTTP 429; the following call waited 14.68 seconds
and passed. The other 15 probes passed. Provider-reported billing was
`$0.001947033`; billing is incomplete because the failed call exposed no cost.

This result rejects the V12 pacing treatment for promotion. It also exposes a
separate admission-control defect: the 147.14-second row exceeded the declared
120-second call timeout because profile admission invokes the provider adapter
without the shared runner's timeout wrapper. All four trajectories were
therefore blocked with zero trajectory provider calls. Do not amend or retry
V12. A new campaign must freeze a completion-to-next-start cooldown and enforce
the same wall-time timeout semantics in admission and trajectory execution.
Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_deepinfra_v12/reports/qualification.json),
the zero-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_deepinfra_v12/trajectories/attempted.json),
and the pacing-aware canonical
[`fact_manifest.json`](../../../evidence/housing_model_sensitivity_openrouter_deepinfra_v12/tables/fact_manifest.json).

## 20. V13 preregistered cooldown and admission-timeout gate

[`housing_model_sensitivity_openrouter_friendli_v13`](../../../configs/housing_model_sensitivity_openrouter_friendli_v13.json)
is a new campaign identity created in response to the V12 result. It does not
retry or amend V12. V13 keeps the same selected configuration, development
world, four subject-opponent conditions, schemas, prompts, sampling, retry
ownership, and the `$0.14` maximum exposure (`$0.06` admission plus `$0.08`
full trajectory).

V13 changes three frozen things:

1. **GLM route.** DeepInfra blocked V11 and V12 with upstream HTTP 429s. V13
   pins GLM 5.3 Flash to Friendli, whose catalog record reports every required
   parameter, an active status, and the same `$0.15/$0.50` per-million pricing
   as the other full-featured GLM routes. Friendli reports its quantization as
   `unknown`; the pin records that literally instead of asserting FP8. DeepSeek
   V4 Flash stays on Parasail FP8 with the same endpoint snapshot digest as
   V12. Before freezing, five spaced strict-client probes per route returned
   five valid actions on Friendli, Parasail, and Sail Research; only Friendli
   held catalog status `0` across three samples, so the other two are not
   admissible pins.
2. **Completion-to-next-start cooldown.** The V12 scheduler measured
   start-to-start, so a 147-second call was followed immediately by another
   call. V13 replaces it with a per-route cooldown of 10 seconds measured from
   the previous call's completion, success or failure, with no first-call
   delay. Calls to one route are serialised. One scheduler instance is shared
   across profile admission and the full-trajectory stage. The implementation
   file is digest-pinned in the contract; the V12 module is untouched.
3. **Admission timeout enforcement.** V12 showed profile admission invoking
   the adapter without a wall-time budget. V13 wraps every admission call in
   the same `asyncio.wait_for` budget the shared-runner attempt loop applies,
   using the frozen 120-second `timeout_seconds`, and records an over-budget
   call as a typed `timeout` failure.

V13 remains a one-world promotion gate. It may establish only whether every
frozen model pairing completes one replay-verified trajectory under the
cooldown condition. It cannot support a winner, model ranking, variance
estimate, or confirmatory claim. If any admission probe fails, all four
trajectories remain blocked; if any trajectory fails, the missing cell remains
typed missingness and is not selectively rerun.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_friendli_v13.json \
  --run-root runs/housing_model_sensitivity_openrouter_friendli_v13 \
  --through provider_free

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_friendli_v13.json \
  --run-root runs/housing_model_sensitivity_openrouter_friendli_v13 \
  --through full_trajectory
```

The executed gate passed. All 18 admission probes passed on the first attempt
for `$0.003589443` with complete provider billing: Friendli/GLM 9 of 9 and
Parasail/DeepSeek 9 of 9. All four full trajectories then completed with
verified routes, complete billing, and exact score replay for
`$0.0223814646`; zero trajectories failed operationally and none were
retried. The combined provider-reported cost was `$0.0259709076` against the
`$0.14` ceiling. The shared scheduler delivered 132 trajectory provider calls
(65 Friendli, 67 Parasail) with 115 paced waits totalling about 1147 seconds;
no admission call exceeded the 120-second budget.

The descriptive within-case scores range from `0.8331363374` to
`0.9330865186`, but this is a one-world promotion gate, not a leaderboard. It
establishes only that the frozen model pairings complete under the cooldown
condition. The next campaign must freeze a new identity for a multi-world
variance pilot that carries the V13 routes, cooldown, and admission-timeout
controls forward unchanged; V13's single world must not be pooled into it.
Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v13/reports/qualification.json),
the four-trajectory
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v13/trajectories/attempted.json),
and the
[`canonical_fact_index.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v13/tables/canonical_fact_index.json).
Raw provider payloads and reasoning remain only under ignored local `runs/`.

## 21. V14 preregistered four-world variance pilot on the V13 routes

[`housing_model_sensitivity_openrouter_friendli_v14`](../../../configs/housing_model_sensitivity_openrouter_friendli_v14.json)
is the multi-world variance pilot that V13's full-trajectory gate promotes. It
carries V13's Friendli and Parasail routes, endpoint snapshot digests,
completion-to-next-start cooldown, and admission-timeout enforcement forward
unchanged, under a new campaign identity and fresh profile digests. Its design
is the V9/V10 pilot design: the three selected development configurations,
four world clusters, and the four subject-opponent conditions, executed in the
rotate-by-world-and-configuration order, for 48 frozen cells. The primary
estimand is the paired world-level GLM-minus-DeepSeek contrast after equal
weighting across configurations and opponents within a world.

The four worlds are the next unused development seeds (`264284765`,
`722524881`, `1535604354`, `366965770`). They are disjoint from V9/V10's four
worlds, from V11 to V13's single world, and from the sealed confirmatory
holdout. V13's world is not pooled in.

The execution ceiling is `$0.45`, sized from V13's observed per-trajectory
range (`$0.0022` to `$0.0084`) times 48 cells with a `$0.01` next-cell
reserve; admission keeps its `$0.06` ceiling, for `$0.51` maximum exposure.
Every cell is one attempt; typed operational failures are retained and never
selectively rerun. The pilot is exploratory: it may estimate the paired-world
variance and a confirmatory sample size, but it cannot support a winner, a
ranking, or a confirmatory claim.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_friendli_v14.json \
  --run-root runs/housing_model_sensitivity_openrouter_friendli_v14 \
  --through provider_free

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_friendli_v14.json \
  --run-root runs/housing_model_sensitivity_openrouter_friendli_v14 \
  --through live
```

The executed pilot blocked at profile admission. Both routes were active at
catalog preflight with V13's endpoint snapshots. Admission attempted all 18
single-attempt probes under the shared cooldown: Parasail/DeepSeek passed 9 of
9, and Friendli/GLM passed 6 of 9. The three failures (tenant commit probes 0
and 2, landlord respond probe 0) were typed HTTP 429 rate limits returned
about 6.5 seconds after each call started, each after the full 10-second
cooldown had been delivered. Provider-reported billing for the 15 passed
probes was `$0.0022604868`; the failed calls exposed no cost. All 48
trajectories remain not started with zero trajectory provider calls.

V13 passed 9 of 9 on the same Friendli route four hours earlier, and the
route's catalog uptime stayed above 99 percent through the failure window.
The cooldown therefore does not by itself protect a single-attempt admission
probe from OpenRouter's upstream shared-pool rate limiting, which has now
blocked DeepInfra (V11, V12), Reka, Parasail, and Friendli at different times.
Do not rerun or amend V14. Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v14/reports/qualification.json),
the zero-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v14/trajectories/attempted.json),
and the admission
[`fact_manifest.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v14/tables/fact_manifest.json).

## 22. V15 preregistered pilot with receipt-visible admission attempts

[`housing_model_sensitivity_openrouter_friendli_v15`](../../../configs/housing_model_sensitivity_openrouter_friendli_v15.json)
repeats the V14 pilot design unchanged: the same Friendli and Parasail routes
and endpoint snapshots, cooldown, admission-timeout enforcement, three
configurations, the same four fresh development worlds, four conditions, 48
cells, and the `$0.51` maximum exposure. It changes one frozen thing.

Profile admission may now make up to four receipt-visible attempts per probe,
the same attempt limit and retryable-condition set (`length`, `rate_limit`,
`provider_5xx`, `empty_response`) that trajectory execution has used since
V1. SDK retries stay at zero and hidden repair stays disallowed. Each attempt
re-sends the identical sealed request after a recorded delay of 2, 4, or 8
seconds on top of the shared cooldown; every attempt's outcome, status code,
elapsed time, and billing status is sealed in the probe row, and the summary
still counts zero hidden retries. A probe that passes after a failed attempt
carries a `provider_reported_with_unbilled_failed_attempts` billing status,
so the admission cost is a lower bound whenever a failed call exposed no cost.
Non-retryable failures, including semantically invalid actions, still end the
probe on the first attempt.

This closes the asymmetry that V14 exposed: single-attempt admission was
stricter than the trajectory policy it gates, so shared-pool rate limiting
could block a pilot whose trajectories would have tolerated the same event.
The population cross-play driver has used four visible admission attempts
since V0. V15 is still an exploratory pilot and supports no ranking.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_friendli_v15.json \
  --run-root runs/housing_model_sensitivity_openrouter_friendli_v15 \
  --through provider_free

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_friendli_v15.json \
  --run-root runs/housing_model_sensitivity_openrouter_friendli_v15 \
  --through live
```

The executed pilot attempted all 48 frozen cells. Both routes were active at
catalog preflight with V13's endpoint snapshots. All 18 admission probes
passed on their first attempt for `$0.0029824542`; the four-attempt policy was
available but unused. Execution then completed 43 of 48 trajectories with
verified routes, complete billing, and exact score replay for
`$0.2280142062`, a combined `$0.2309966604` against the `$0.51` ceiling. The
shared cooldown delivered 1248 trajectory provider calls (625 Friendli, 623
Parasail) with 1128 paced waits totalling about 10992 seconds.

Five trajectories are retained as typed operational missingness: four Friendli
rate-limit exhaustions (all four visible attempts on one GLM action returned
HTTP 429) and one Friendli timeout. Every failed cell contains a GLM seat;
Parasail/DeepSeek produced no operational failure in 623 calls. The failures
fall one or two per world, so no world has a complete GLM-subject block and the
paired-world count is zero. Variance, the confirmatory sample size, and any
contrast are therefore not estimable, exactly as in V10, though the completion
rate rose from 31 of 48 to 43 of 48.

The pilot is protocol-conformant: the V13 full-trajectory gate passed on the
same routes and endpoint snapshots under its own identity, and the publisher
verifies that gate's committed digest before recording conformance. Do not
rerun or impute the five missing cells. The descriptive within-case scores
span `0.1940733781` to `1.0` and support no ranking. Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v15/reports/qualification.json),
the all-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v15/trajectories/attempted.json),
and the
[`canonical_fact_index.json`](../../../evidence/housing_model_sensitivity_openrouter_friendli_v15/tables/canonical_fact_index.json).

Three pilots on three GLM routes have now produced the same shape: the
DeepSeek arm completes, and shared-pool rate limiting on the GLM arm leaves
every world one cell short. The next campaign must change the GLM delivery
treatment explicitly under a new identity, for example a route with a
dedicated provider key or a batch backend under the SOP's escalation rule,
rather than repeat this design on another shared-pool route.

## 23. GLM route probe and the V16 Parasail full-trajectory gate

Three pilots on three shared-pool GLM routes had produced the same one-cell-
per-world loss, and each route had been chosen from five spaced calls over
about a minute. That window cannot detect a route that bursts HTTP 429 for a
few seconds every twenty minutes. Before spending again, a one-hour route
probe ran every GLM endpoint that advertises the strict client's required
parameters: 12 routes, 100 calls each, 36 seconds apart, through the V15
admission request builder with the 120-second wall-time cap, no retries, and
V2 schema validation. The sanitized per-call record and digest-bound summary
are published under
[`evidence/housing_glm_route_probe_2026-09-05/`](../../../evidence/housing_glm_route_probe_2026-09-05/reports/summary.json).

| Route | Valid | 429 | Other failures |
|---|---|---|---|
| Parasail FP8 | 100 / 100 | 0 | 0 |
| Cloudflare | 99 / 100 | 1 | 0 |
| Morph FP8 | 95 / 100 | 5 | 0 |
| Reka FP8 | 92 / 99 | 0 | 7 HTTP 502 |
| Friendli | 90 / 100 | 10 | 0 |
| Sail Research, Makora, NextBit | 82 to 84 / 100 | 16 to 17 | 0 |
| Wafer, CoreWeave, DeepInfra | 31 to 55 / 100 | 19 to 69 | 3 timeouts |
| Phala FP8 | 20 / 82 | 1 | 61 invalid actions |

Every 429 carried OpenRouter's `upstream_provider_shared_pool` limit source;
the account is paid-tier with no request limit, so the bursts are provider
saturation, not client throttling. Parasail was the only route with zero
operational failures and zero invalid actions across the window.

[`housing_model_sensitivity_openrouter_parasail_v16`](../../../configs/housing_model_sensitivity_openrouter_parasail_v16.json)
is the SOP-required full-trajectory gate for the changed GLM route. It pins
both models to Parasail FP8, keeps V13's world, configuration, four
conditions, `$0.14` exposure, cooldown module, admission-timeout
enforcement, and V15's four receipt-visible admission attempts, and binds the
route probe's summary digest in its campaign spec. Because both models share
one provider, the 10-second cooldown now serialises every provider call in a
trajectory, so wall time roughly doubles relative to V13. Promotion requires
one completed trajectory per condition; a passing gate is the declared
prerequisite for a 48-cell pilot under a further identity.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v16.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v16 \
  --through provider_free

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v16.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v16 \
  --through full_trajectory
```

The executed gate passed. All 18 admission probes passed on their first
attempt for `$0.0026201538` with complete billing. All four trajectories
completed with verified routes, complete billing, and exact score replay for
`$0.021948696`, a combined `$0.0245688498`. Zero operational failures, zero
hidden retries. The shared Parasail cooldown delivered 132 trajectory calls
with 131 paced waits totalling about 1307 seconds. Descriptive within-case
scores span `0.8856512098` to `0.9201434`, and support no ranking. Review the
digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v16/reports/qualification.json),
the four-trajectory
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v16/trajectories/attempted.json),
and the
[`canonical_fact_index.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v16/tables/canonical_fact_index.json).

## 24. V17 preregistered four-world variance pilot on the Parasail routes

[`housing_model_sensitivity_openrouter_parasail_v17`](../../../configs/housing_model_sensitivity_openrouter_parasail_v17.json)
is the multi-world variance pilot that the V16 gate promotes. It carries V16's
Parasail FP8 routes and endpoint snapshots, cooldown, admission-timeout
enforcement, and four receipt-visible admission attempts forward unchanged,
under a new identity and fresh profile digests, on the V9/V10 pilot design:
three selected configurations, four world clusters, four conditions, 48
cells, rotate-by-world ordering, `$0.51` maximum exposure. Its campaign spec
binds both the V16 qualification digest as the verified prerequisite gate and
the route-probe summary digest as the route-selection record.

The four worlds are the next unused development seeds (`1063943031`,
`647986875`, `1758927083`, `237549679`), disjoint from every earlier campaign
and from the sealed holdout. V15's worlds are deliberately not reused, so no
cell from a different route can be mistaken for a rerun.

Because both models share one provider, the cooldown serialises every call;
expect roughly twice V15's wall time. The pilot is exploratory: it may
estimate the paired-world variance and a confirmatory sample size, but it
cannot support a winner, a ranking, or a confirmatory claim.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v17.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v17 \
  --through provider_free

python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v17.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v17 \
  --through live
```

The executed pilot stopped after three cells. Admission passed 18 of 18 on
the first attempt for `$0.003019401`. The first two trajectories then failed
on single 120-second timeouts of DeepSeek seats on Parasail, one of them
after a `length` escalation had doubled that seat's output cap from 4096 to
8192 tokens; a timeout is deliberately not retryable because the provider may
already have executed the call. The third trajectory failed when its DeepSeek
tenant seat exceeded a hardcoded `$0.01` per-seat cost budget after the same
length escalation, and the driver classified that `EvidenceIntegrityError`
as a critical campaign failure, stopping the pilot with 45 cells never
attempted for `$0.0222467553` of spend. Parasail delivered every one of the
74 provider calls; no route or rate-limit failure occurred.

This is a driver defect, not a route result. A seat exhausting its own
budget is cell-level typed missingness and should not stop the campaign; the
`$0.01` seat budget was never contract-visible; and the 120-second wall-time
cap cannot accommodate the length policy's own 8192-token retry at Parasail's
observed DeepSeek throughput. V17 is not rerun or amended. The publisher now
records stopped pilots, marking `all_frozen_cells_attempted` false and the
never-attempted count. Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v17/reports/qualification.json)
and the three-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v17/trajectories/attempted.json).

## 25. V18 preregistered gate with contract-visible seat budget and wall time

[`housing_model_sensitivity_openrouter_parasail_v18`](../../../configs/housing_model_sensitivity_openrouter_parasail_v18.json)
is a new full-trajectory gate identity created in response to V17. It keeps
V16's Parasail FP8 routes and endpoint snapshots, world, configuration, four
conditions, cooldown, admission-timeout enforcement, and four receipt-visible
admission attempts, and changes three frozen controls:

1. `timeout_seconds` rises from 120 to 300 so that the frozen length policy's
   8192-token retry can complete at observed throughput.
2. `seat_max_cost_usd` freezes each seat's per-trajectory cost budget at
   `$0.03` in the contract, replacing the hidden `$0.01` runner default. The
   per-trajectory reserve rises to `$0.06` (two seats) and the gate's
   execution ceiling to `$0.30`, for `$0.36` maximum exposure.
3. A seat budget exhaustion is typed `cost_budget_exceeded` cell-level
   missingness and no longer stops the campaign; route drift, replay failure,
   provider-contract failure, and the campaign cost ceiling remain critical.

Executed campaigns V13 to V17 keep their original implementation digests via
the historical pin table, so their sealed designs still reproduce. V18 is a
one-world promotion gate and supports no ranking.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v18.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v18 \
  --through full_trajectory
```

The executed gate passed. All 18 admission probes passed on their first
attempt for `$0.002637261`. All four trajectories completed with verified
routes, complete billing, and exact score replay for `$0.0277184754`, a
combined `$0.0303557364` against the `$0.36` ceiling; zero operational
failures, zero hidden retries, 135 Parasail calls with 134 paced waits. One
cross-play cell cost `$0.0117`, above the hidden `$0.01` seat budget that
stopped V17, and completed under the frozen `$0.03`. Descriptive scores span
`0.5751824247` to `0.9167928417` and support no ranking. Review the
digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v18/reports/qualification.json),
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v18/trajectories/attempted.json),
and
[`canonical_fact_index.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v18/tables/canonical_fact_index.json).

## 26. V19 preregistered four-world variance pilot on the V18 controls

[`housing_model_sensitivity_openrouter_parasail_v19`](../../../configs/housing_model_sensitivity_openrouter_parasail_v19.json)
is the multi-world variance pilot that the V18 gate promotes. It carries
V18's Parasail FP8 routes and snapshots, 300-second wall time, `$0.03` seat
budget, cooldown, admission-timeout enforcement, and four receipt-visible
admission attempts forward unchanged, under a new identity and fresh profile
digests, on the V9/V10 pilot design: three configurations, four worlds, four
conditions, 48 cells, rotate-by-world ordering. Its spec binds the V18
qualification digest as the verified prerequisite gate and the route-probe
summary digest as the route-selection record.

The four worlds are V17's three never-attempted worlds (`647986875`,
`1758927083`, `237549679`) plus the next unused development seed
(`1515521562`). V17 executed cells only on `1063943031`, which is excluded,
so no V19 cell repeats an executed cell. The per-trajectory reserve is
`$0.06` (two seats at `$0.03`) and the execution ceiling `$1.00`, sized so
the reserve rule cannot stop the pilot before its 48th cell at the V18
observed cost of `$0.002` to `$0.012` per cell; `$1.06` maximum exposure.
The pilot is exploratory and supports no winner, ranking, or confirmatory
claim.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v19.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v19 \
  --through live
```

The executed pilot attempted all 48 cells. Admission passed 18 of 18 on the
first attempt for `$0.0031506552`. Thirty-two trajectories completed with
verified routes, complete billing, and exact score replay for
`$0.2003244111`; the shared Parasail cooldown delivered 1048 provider calls.
Sixteen trajectories are typed operational missingness, every one a Parasail
GLM seat exhausting its four visible attempts on HTTP 429. The failures are
not spread evenly: worlds `647986875` and `1758927083` completed all 24 of
their cells with zero failures, then a rate-limit burst that began during
world `237549679` and persisted through world `1515521562` cost 16 of the
remaining 24 cells. No timeout and no seat-budget exhaustion occurred under
the V18 controls.

Two worlds therefore have a complete subject pair, the first paired worlds in
this family. The paired world-level GLM-minus-DeepSeek contrast is
`-0.1412` and `-0.0098`, mean `-0.0755` with sample standard deviation
`0.0930`, which the frozen analysis converts to 28 raw and 32
attrition-adjusted confirmatory worlds, inside the declared maximum of 100.
Two paired worlds cannot support that sample-size claim with any confidence,
and the estimate remains exploratory: no winner, ranking, or confirmatory
claim is supported, and `paired_worlds_complete` is false.

The reliability finding is now precise. Parasail GLM sustained 24 clean
cells over roughly four hours and then lost 16 of 24 in a burst that the
one-hour selection probe could not have predicted. Shared-pool rate limiting
on OpenRouter is time-varying at the scale of hours, so no route selection
procedure on a shared key can make a 48-cell serial pilot reliable. The next
delivery treatment must remove the shared pool: a dedicated GLM provider key
attached to the OpenRouter account, or a batch backend under the SOP's
escalation rule, each under a new campaign identity with a fresh gate. Do
not rerun or impute the 16 missing cells. Review the digest-bound
[`qualification.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v19/reports/qualification.json),
the all-attempt
[`attempted.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v19/trajectories/attempted.json),
the
[`canonical_fact_index.json`](../../../evidence/housing_model_sensitivity_openrouter_parasail_v19/tables/canonical_fact_index.json),
and the paired-world table.

## 27. V20 preregistered gate with ten receipt-visible attempts per action

V19's losses were not short bursts. From 10:10 to 12:15 UTC on 2026-09-05,
about 40 percent of the calls in every ten-minute window returned HTTP 429
from the Parasail shared pool while the remaining calls succeeded normally;
464 calls failed in that window. Under four attempts per action, a sustained
40 percent per-call failure rate loses roughly half of all cells, which is
what happened. Under ten attempts the per-action loss falls below 0.1
percent. The attempt count is a declared retry control, so
[`housing_model_sensitivity_openrouter_parasail_v20`](../../../configs/housing_model_sensitivity_openrouter_parasail_v20.json)
freezes it under a new gate identity rather than changing the route or
requesting a private provider key.

V20 keeps V18's Parasail FP8 routes and endpoint snapshots, world,
configuration, conditions, 300-second wall time, `$0.03` seat budget,
cooldown, and admission-timeout enforcement, and changes two controls:
`max_action_attempts` rises from 4 to 10 for every seat, and the seat harness
gains the runner's `exponential_jitter_v1` backoff (base 5 seconds, doubling
to the 30-second cap, honouring `Retry-After` up to 60 seconds). Profile
admission uses the same ten-attempt limit and base delay. SDK retries stay at
zero, every attempt is sealed in the receipt, and a timeout still ends an
action because the provider may have executed the call. V20 is a one-world
promotion gate; a pass promotes a 48-cell pilot under a further identity.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v20.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v20 \
  --through full_trajectory
```

## 28. V21 preregistered eight-world pilot and the holdout capacity question

V19 produced two paired worlds, which is too few to size a confirmatory run.
[`housing_model_sensitivity_openrouter_parasail_v21`](../../../configs/housing_model_sensitivity_openrouter_parasail_v21.json)
is the corrected pilot that V20 promotes. It carries V20's Parasail FP8
routes, ten receipt-visible attempts per action, five-second exponential
backoff, retryable timeouts, 300-second wall time, `$0.03` seat budget,
cooldown, and admission-timeout enforcement, and changes the panel.

The pilot moves from four worlds to eight, chosen by a declared rule rather
than by outcome: the first eight development seeds in frozen sweep order,
excluding the world used by the full-trajectory gates. V19's worlds are not
reused, so no world can be suspected of selection on its result.

It also restores stochastic replicates. Section 5 of this profile requires
repeats to be averaged within a world before worlds are treated as
independent evidence, and the whole model-sensitivity line ran a single
replicate per cell, which folds provider noise into the between-world term
and inflates both the variance and the world count derived from it. The
replicate index is hashed into the request seed, so a second replicate is a
genuine repeat draw rather than a duplicate call. The panel is eight worlds,
three configurations, four conditions and two replicates, for 192 cells at an
execution ceiling of `$2.00`. The confirmatory campaign uses the same
replicate count, because a variance measured at one replicate count cannot
size a run at another. The analysis declares
`minimum_paired_worlds_for_recommendation` of six, so a confirmatory sample
size is emitted only if at least six of the eight worlds complete both
subject blocks; below that the variance and mean contrast are still published
and the recommendation is withheld.

### The holdout capacity question

The campaign analysis contract declares a minimum of 30 confirmatory worlds
and the frozen case sweep seals 16 holdout seeds. No confirmatory campaign
can satisfy both, and this contradiction predates the current work. It does
not need to be resolved yet, because whether it binds depends on a quantity
the corrected pilot has not measured.

With 16 holdout worlds and the declared 10 percent attrition allowance, the
powered design fits inside the existing holdout precisely when the paired
world-level standard deviation is at most `0.0668` at the declared minimum
meaningful effect of `0.05`. V19 reported `0.0930`, but that figure is
inflated twice over: it comes from two worlds, and with one replicate per
cell it folds within-world provider noise into the between-world term. A
properly estimated standard deviation may fall below the threshold.

The decision rule is therefore fixed in advance, before any holdout outcome
is inspected. If V21 reports a paired standard deviation at or below
`0.0668`, the sealed 16-world holdout is sufficient and the confirmatory
freeze proceeds against it unchanged. If V21 reports more, the holdout must
be extended under a new case-sweep identity with additional seeds drawn
disjointly from the development split. Extending it remains legitimate at
that point only because the holdout is still sealed and unexecuted; once any
holdout outcome is seen, neither the seed list nor the minimum meaningful
effect may change. Lowering the declared effect to fit the existing holdout
is not an option, because the pilot effect size has already been observed and
choosing the detectable effect around it would be post-outcome tuning.

```bash
python -m aeread_families.housing.backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_parasail_v21.json \
  --run-root runs/housing_model_sensitivity_openrouter_parasail_v21 \
  --through live
```

## 29. Confirmatory gates, the sealed holdout, and its degenerate world

The kernel has always named `confirmatory_freeze` and
`confirmatory_execution`, but nothing implemented them for Housing, so the
family could not reach the comparison it was designed for. Both gates now
exist, together with a confirmatory campaign over the sealed holdout:
[`housing_confirmatory_parasail_v1`](../../../configs/housing_confirmatory_parasail_v1.json).

### The holdout panel is verified, not trusted

The confirmatory contract inlines the holdout configurations and world seeds
so the freeze can hash them, and every inlined value is checked against the
frozen case sweep at load. The sweep contract is digest-checked, the holdout
must still be sealed with its declared access rule, the inlined
configurations and seeds must match it exactly, and the panel must not
intersect the development split. A confirmatory campaign therefore cannot
widen or reshape its own evaluation set.

### One holdout world is structurally unusable

Auditing the holdout for the first time exposed a defect that had never
surfaced, because the holdout was sealed and had never been generated. The
severe holdout configuration at world seed `114691332` produces an assignment
upper bound of zero. Section 1 of this profile already rules that such a
world receives `degenerate_upper_bound`, carries no normalized score, and
stays outside normalized-score inference, so it cannot contribute a paired
contrast.

That world is excluded before any outcome exists, and the exclusion is
re-derived from the generator whenever the contract loads, so no world can be
dropped for a reason the environment does not force. Usable holdout capacity
is 15 worlds rather than 16, and the standard deviation the powered design
must meet tightens from `0.0668` to `0.0643`. The confirmatory panel is
therefore 15 worlds, three configurations and four conditions, for 180 cells.

The provider-free gate cannot cross-check these worlds against the
development facts table, because the holdout was deliberately never swept. It
audits every sealed world directly instead, including the excluded one, and
records the content digests that the freeze seals.

### What the freeze seals, and when

`confirmatory_freeze` is its own stopping point so that it can be committed
before a single holdout call is made. It seals the holdout seeds and
configurations, the profiles, controls, conditions, analysis plan,
missingness policy, stopping rule, execution block, prior gate digests and
cost ceiling, and it binds the variance pilot whose paired standard deviation
justified the world count. It refuses a pilot whose variance was not
estimable or whose recommendation was withheld, and it refuses a panel
smaller than the recommended world count, so an underpowered confirmatory run
cannot start by accident.

### What the confirmatory analysis reports

The primary estimand stays the one the variance pilot measured, because the
world count was derived from that estimand's variance; changing it here would
invalidate the sample size. Cross-play and self-play are reported as
predeclared secondary slices rather than folded into the headline, as section
5 requires. A world that lost any expected cell contributes no contrast, so
partial delivery cannot tilt the estimate. A ranking, a winner claim and
leaderboard eligibility are all withheld unless the declared paired minimum
is met and every planned cell was attempted, and the publisher refuses to
publish a confirmatory result whose contract digest changed after the freeze
was sealed.

## 30. V23 pilot result and a correction to the holdout decision rule

V23 executed all 192 cells for `$0.9095553819` with six operational
failures, a 3.1 percent cell loss well inside the declared 10 percent
ceiling. Delivery improved sharply against V19, which lost a third of its
cells on the same route: ten receipt-visible attempts with backoff, retryable
timeouts and bounded-concurrency pacing absorbed a continuous stream of
upstream rate limits, several hundred retried attempts spread across every
minute of the run.

The measured variance is much tighter than V19's exploratory figure.

| Quantity | V19 | V23 |
|---|---|---|
| Paired worlds | 2 | 4 |
| Mean paired contrast | -0.0755 | 0.0059 |
| Paired standard deviation | 0.0930 | 0.0385 |

The contrast is close to zero, which is a substantive result in itself, but
four paired worlds is below the declared minimum of six, so the analysis
withheld the confirmatory world count exactly as designed. The recommendation
is suppressed and the freeze will refuse to size a run from this pilot.

### Why six of eight worlds failed to pair from six lost cells

All six failures fell in one condition, GLM as tenant against DeepSeek as
landlord, spread across four separate worlds and four hours. Each one
exhausted all ten attempts on a single action. The retry ledger shows the
blocks lasted between 304 and 762 seconds, while ten attempts under a
five-second base capped at thirty seconds cover only about 245 seconds. The
policy gives up before the block clears. These are sustained upstream blocks,
not unlucky individual calls, and the retry window is simply too short for
them.

The arithmetic then amplifies. A world needs all 24 of its cells, so at a 3.1
percent cell loss a world survives with probability `0.969` to the 24th,
about 47 percent. Four of eight paired is exactly what that predicts. To
reach six of eight the cell loss must fall to roughly 1.2 percent.

### Correction: the declared minimum binds, not the variance

Section 28 stated that a paired standard deviation at or below `0.0668` would
let the sealed holdout carry the confirmatory comparison. That rule was
incomplete and the conclusion it implied was wrong.

The recommended world count is the larger of the powered estimate and the
contract's declared `minimum_confirmatory_worlds`, which is 30. V23's
standard deviation implies only five raw worlds and six after attrition, but
the floor of 30 dominates. The holdout admits 15 usable worlds. No standard
deviation, however small, can make 15 satisfy a declared minimum of 30.

The holdout capacity conflict is therefore unconditional rather than
contingent on the pilot, and better data cannot resolve it. The remaining
options are unchanged in kind: extend the holdout under a new case-sweep
identity while it is still sealed and unexecuted, which stays legitimate
precisely because no holdout outcome has been observed, or change the
declared minimum, which after seeing pilot outcomes would be post-outcome
tuning and is excluded.

