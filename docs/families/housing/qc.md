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

### Strata

Market difficulty and the opponent model are crossed with every world, so they
triple and double the cells, and neither changes the model contrast on the
30-world confirmatory. Difficulty separated DeepSeek and GLM as tenants
on the 8-world panels V23 and V26 and did not replicate on the 30-world
confirmatory (p = 0.27 tenants, 0.082 landlords); the within-case score cannot
move with difficulty, being scaled to each market's bound. The opponent reads
within noise on the pooled contrast while moving each market by about 0.08 in
either direction (D-27). Future packs assign one difficulty per world, balanced,
after the D-27 estimand decision, and report the opponent pooled. The sensitivity
panels with 1 to 4 worlds cannot test any split. See the
[strata audit](../../research/strata_audit_2026-09.md).

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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_v1/reports/qualification.json).

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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v2/reports/qualification.json).

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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v3/reports/qualification.json).

For review without publishing raw model reasoning, the repository also keeps a
digest-bound set of three V0 trajectory examples: the upper and lower observed
completed live-opponent cross-play cells and the shortest operational failure.
The export includes event-seal roots, receipt identities, action summaries,
outcomes, costs, and limitations, while the complete provider responses remain
under ignored local `runs/`. See
[`selected_2026-09-02.json`](../../../evidence/housing/housing_population_crossplay_v0/trajectories/selected_2026-09-02.json).

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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v4/reports/qualification.json).

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
See its tracked [`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v5/reports/qualification.json).

V6 made null or blank provider content a receipt-visible `empty_response` so
the application retry policy, rather than the adapter, owns retry decisions.
Admission then exposed a separate semantic hole in the V1 commit schema:
DeepSeek returned `decision=pass` with a non-null `hold_id`. Seventeen of 18
probes passed, and the failed gate blocked live execution. See its tracked
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v6/reports/qualification.json).

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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v7/reports/qualification.json)
records the gates and stop. The separate
[`selected.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v7/trajectories/selected.json)
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
[`requalification_2026-09-02.json`](../../../evidence/housing/housing_population_crossplay_v0/reports/requalification_2026-09-02.json).

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
  --publish-root evidence/housing/housing_qc_goldens_v1
```

All five valid receipts replay state and score exactly; the provider-failure
receipt has `replay_level=none`. The bundle made zero external calls and cost
`$0.00`. Review the digest-bound
[`qc_bundle.json`](../../../evidence/housing/housing_qc_goldens_v1/reports/qc_bundle.json)
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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v8/reports/qualification.json)
records every gate. The
[`attempted.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v8/trajectories/attempted.json)
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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v9/reports/qualification.json),
the explicit zero-attempt
[`attempted.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v9/trajectories/attempted.json),
and the canonical
[`fact_manifest.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_alt_v9/tables/fact_manifest.json).
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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_morph_v10/reports/qualification.json),
all-attempt
[`attempted.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_morph_v10/trajectories/attempted.json),
and the
[`canonical_fact_index.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_morph_v10/tables/canonical_fact_index.json).
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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_deepinfra_v11/reports/qualification.json),
the explicit zero-attempt
[`attempted.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_deepinfra_v11/trajectories/attempted.json),
and the reusable admission
[`fact_manifest.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_deepinfra_v11/tables/fact_manifest.json).

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
[`qualification.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_deepinfra_v12/reports/qualification.json),
the zero-attempt
[`attempted.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_deepinfra_v12/trajectories/attempted.json),
and the pacing-aware canonical
[`fact_manifest.json`](../../../evidence/housing/housing_model_sensitivity_openrouter_deepinfra_v12/tables/fact_manifest.json).

## 20. Lemons refusal pilot campaign

The first campaign identity on the lemons world (case contract §5c) is
[`housing_lemons_refusal_pilot_v1`](../../../configs/housing_lemons_refusal_pilot_v1.json),
driven by `aeread_families.housing.lemons_campaign`. It is descriptive and
single-route: one live tenant profile (Gemini 3.8 Flash via Google AI Studio)
on a frozen pack of gate-admitted worlds, with the three scripted tenant
policies run through the same runner on the same pack as controls. The
primary estimand is `tenant_net_payoff`; the contrast is live minus the
`inspect_then_sign` reference per world. It may claim no winner and no ranking.

**Pack.** Six tenants, four listings, four rounds, share 0.5, loss 1000, fee 25,
the family admission rule. Seeds are walked from 100000: the first admitted
world is the full-trajectory world (100000), then each stratum fills to twelve
worlds in stream order. The strata are declared slices, `favourite_is_lemon`
and `favourite_is_sound`, where the favourite is the listing most tenants rank
first by value-if-sound gain. The stream was scanned to seed 100030, six worlds
excluded. The design gate re-derives the pack from the rule and refuses a
contract whose seed lists differ from what the rule yields.

**Gates.** The campaign SOP's first five, through the shared gate history:

```bash
python -m aeread_families.housing.lemons_campaign \
  --contract configs/housing_lemons_refusal_pilot_v1.json \
  --run-root runs/housing_lemons_refusal_pilot_v1 --through provider_free_validation
python -m aeread_families.housing.lemons_campaign \
  --contract configs/housing_lemons_refusal_pilot_v1.json \
  --run-root runs/housing_lemons_refusal_pilot_v1 --through full_trajectory
python -m aeread_families.housing.lemons_campaign \
  --contract configs/housing_lemons_refusal_pilot_v1.json \
  --run-root runs/housing_lemons_refusal_pilot_v1 --through variance_pilot
```

`design_contract` seals the pack facts, the plan and profile digests, and the
worst case in integer cents (49 cells x $0.30, with the stage ceilings of $0.50
and $6.00 binding first). `provider_free_validation` runs all 75 scripted cells
with receipt verification and replay and refuses a policy whose runner score
differs from the offline gate's. `profile_admission` probes the three lemons
action schemas three times each. `full_trajectory` is one live cell;
`variance_pilot` is 24 worlds x 2 inference seeds, executed world by world in
ascending seed order. Set `OPENROUTER_API_KEY` before the paid gates.

**Limits in the contract.** Per-profile cost ceiling $0.30 per cell, four action
attempts with the declared retryable conditions, 120 s per action, the two stage
ceilings, and `max_consecutive_operational_failures: 3`: after three failed
cells in a row the stage halts, seals the untouched cells as `not_attempted`
typed missingness, and fails its gate. A later attempt reuses the completed
cells of earlier attempts and re-executes only failed ones under a new evidence
root, so no cell is rerun in place and no completed cell is paid for twice.

**Analysis.** Five endpoints in declared order, overall and per stratum, each a
mean over worlds with a 95% percentile interval from a world-clustered bootstrap
of 10000 draws; one `random.Random(20260921)` stream serves every interval in
that order, so two analysts with the contract get the same numbers. Cells that
signed an uninspected lemon, that fell below sign-anything, and that beat the
reference are counted beside the intervals. Operational failures are reported
as missingness, never as zero scores.

**Result (2026-09-21, exploratory, no claim).** All five gates passed. The
pilot needed two attempts: the first lost its network after 19 completed cells
and the stop rule halted it (HL-O-03); the second reused those 19 and completed
the pack, 48 of 48 cells, $4.30 for the campaign including the failed cells,
costs exact. The sealed bundle is
[`evidence/housing/housing_lemons_refusal_pilot_v1/`](../../../evidence/housing/housing_lemons_refusal_pilot_v1/),
verified by recomputing every digest, re-driving all 49 live receipts through
the environment (0 score mismatches) and recomputing the analysis from the
published rows. Over 24 worlds, one Gemini 3.8 Flash tenant population:

| endpoint (mean over worlds, 95% world-clustered interval) | overall | favourite is lemon | favourite is sound |
|---|---|---|---|
| tenant net payoff | 328.5 (248.0 to 405.8) | 301.4 (170.5 to 423.9) | 355.7 (264.2 to 445.1) |
| within-case score (net / oracle) | 0.223 (0.171 to 0.271) | 0.188 (0.113 to 0.256) | 0.258 (0.194 to 0.318) |
| abstention correctness | 0.993 (0.979 to 1.000) | 0.986 (0.958 to 1.000) | 1.000 |
| cells signing an uninspected lemon | 2 of 48 | 2 of 24 | 0 of 24 |
| live minus inspect-then-sign reference | -25.6 (-95.4 to 23.1) | -28.1 (-156.2 to 54.4) | -23.2 (-72.7 to 3.5) |
| cells above the reference / below sign-anything | 34 / 0 | 14 / 0 | 20 / 0 |

Read descriptively: the live tenant sits within the scripted bracket on every
cell, never below sign-anything, above the inspect-then-sign reference on 34 of
48 cells, and the paired difference to the reference is indistinguishable from
zero at this size. Both uninspected lemon signings, and both negative cells, are
the two seeds of one world (100025) in the favourite-is-lemon stratum, the only
world where the pooled expectation of the popular listing exceeded the rent and
the listing was a lemon. The two inference seeds gave identical net payoffs on
16 of 24 worlds, so seed variance is small relative to world variance and a
powered design should spend its budget on worlds. None of this ranks a model or
supports a winner; a second route on the same pack would be a paired contrast,
not a ranking.

## 21. Lemons v2: a pooled landlord, temperature 1.0, two routes on one pack

Two identities fix the v1 pilot's design defects and run a second model on the
same frozen pack: `housing_lemons_refusal_v2_gemini38_flash` and
`housing_lemons_refusal_v2_glm53_flash` (`lemons_campaign.IDENTITIES`). They
differ from v1 in two controls and from each other in the route alone:

- **Pooled landlord (HL-D-01).** `environment.lemon_landlord: "pooled"`: a
  lemon's scripted landlord accepts and counters on its sound-equivalent cost,
  so its reply no longer tells an offer below the ask apart by quality; the true
  cost enters only the accounting. v1 keeps `true_cost` and replays unchanged.
- **Temperature 1.0 (HL-D-02)**, carried to the profile by the runner (HL-T-02).
- **Routes.** Gemini 3.8 Flash (Google AI Studio) and GLM 5.3 Flash (Parasail
  fp8), each filling all six tenant seats, so a cell is a market of one model's
  tenants. Pack, strata, seeds, limits, analysis and stream are v1's.

**Execution (2026-09-25).** Both passed design, provider-free validation,
profile admission and the full-trajectory cell. Gemini's variance pilot lost
one cell to an unanswered call in attempt 1 (HL-O-04) and completed 48 of 48 in
attempt 2, $4.30 for the campaign. GLM's lost six cells the same way in attempt
1, then three, one, one and one: world 100021 seed 1 hung on every one of five
runs in the campaign root, at a different seat and phase each time, while
direct replays of its hung requests and two diagnostic copies of the run root
completed (HL-O-05 to HL-O-07). Re-execution stopped under a rule fixed before
the fifth attempt. Its gate stays failed at 47 of 48, and the owner decided to
publish it as an incomplete pack rather than re-run the cell: the driver's
`--publish-incomplete-pilot REASON` publishes the newest attempt as sealed,
records `pilot_gate_status: failed_incomplete_pack`, the reason and the missing
cell in the manifest and README, and refuses when a passed attempt exists or
the stage halted.

**Published** at
[`evidence/housing/housing_lemons_refusal_v2_gemini38_flash/`](../../../evidence/housing/housing_lemons_refusal_v2_gemini38_flash/)
and
[`evidence/housing/housing_lemons_refusal_v2_glm53_flash/`](../../../evidence/housing/housing_lemons_refusal_v2_glm53_flash/)
(incomplete pack), each verified by recomputing every digest and the manifest
seal, a clean prohibited-text scan, re-driving every completed live receipt
through the environment (49 and 48, 0 score mismatches) and recomputing the
analysis from the published rows.

| endpoint, mean over worlds (95% world-clustered interval) | Gemini v2 (48/48) | GLM v2 (47/48, incomplete pack) |
|---|---|---|
| tenant net payoff | 327.8 (248.8 to 405.4) | 134.0 (-0.4 to 271.3) |
| within-case score | 0.223 (0.172 to 0.269) | 0.079 (-0.013 to 0.165) |
| abstention correctness | 1.000 | 0.927 (0.888 to 0.962) |
| cells signing an uninspected lemon | 2 of 48 | 10 of 47 |
| live minus inspect-then-sign reference | -26.3 (-93.5 to 21.9) | -220.2 (-336.0 to -103.8) |
| cells above the reference / below sign-anything | 37 / 0 | 6 / 0 |

Paired over the 24 worlds, derived from the two bundles at
[`evidence/housing/housing_lemons_refusal_v2_comparison/`](../../../evidence/housing/housing_lemons_refusal_v2_comparison/)
(`python -m aeread_families.housing.lemons_comparison --check`), Gemini minus GLM in net payoff is +193.9
(66.9 to 321.7), Gemini ahead on 19 worlds and behind on 5. It does not rest
on the missing cell: without world 100021 it is +161.6 (40 to 273) over 23
worlds, and with GLM's missing seed set to the best payoff GLM reached anywhere
it is +157.8.

**Why, and how much is luck (HL-J-01).** Both populations signed about as many
listings without inspecting them (Gemini 23, GLM 21); 2 of Gemini's were lemons
and 11 of GLM's, at the $1,000 lemon loss each, which is the realized gap. But a
blind signing is a bet at the tenant's own lemon probability. At signing, those
probabilities summed to 5.0 expected lemons for Gemini (8 of its 23 were on
listings it had deduced sound) and 7.2 for GLM: the draws favoured Gemini by
about 3 lemons and went against GLM by about 4. Charging every blind signing its
expected loss instead of the realized one, Gemini minus GLM is +41.1 (-69.3 to
143.3), Gemini ahead on 14 worlds and GLM on 10: not separated. The derived
comparison publishes this as `expected_net_payoff`, from the published expected
values and the worlds regenerated from their seeds. What separates
is smaller: GLM made 4 blind signings worth less than the rent in expectation
(about $17.5 a market), Gemini none, and GLM's risky signings carried a higher
mean lemon probability (0.45 against 0.33). GLM also inspected more (11.7
against 10.5 per market) and walked far more holds (138 against 5).

**Where the gap comes from.** The derived analysis
[`evidence/housing/housing_lemons_refusal_v2_gap/`](../../../evidence/housing/housing_lemons_refusal_v2_gap/)
(`python -m aeread_families.housing.lemons_gap --check`) splits every cell's payoff
exactly into leases signed after inspecting, blind signings worth it in expectation,
blind signings not worth it, the lemon draws on blind signings, and inspection fees.
Of the +193.9, the lemon draws are +152.8 (62.5 to 243.1); GLM's larger inspection
spend is +30.7 (13.0 to 48.4); its blind signings below expected value +17.5 (0.0
to 46.0); blind signings worth it +9.9 and leases signed after inspecting -17.1,
both crossing zero. The decision classes, judged at what each tenant knew, extend
the Housing failure taxonomy with group `L`: GLM signed 4 uninspected holds worth
less than their rent, signed blind 6 times after passing on an inspection worth its
fee, declined 16 holds worth more than their rent and signed 31 leases above the
ask; Gemini did none of these. Every instance names its cell, round and tenant.
`tables/contributions.jsonl` carries every part down to the decision behind it
(1,281 rows: 226 leases and draws at their commit step, 1,055 inspection fees at
their inspect step; per cell a part's rows sum to it exactly, and every row's
round, phase and seat lands on the matching action in the published trajectory),
so a part of the gap can be followed to the worlds, cells and steps that make it.

**Against the reference.** The same bundle splits each model's payoff against the
scripted inspect-then-sign reference on the same worlds (`baselines`; replaying the
policy reproduces all 24 published reference payoffs). The reference never signs
blind, so its luck part is zero and the pair gap is exactly the difference of the
two contrasts. Gemini is not separated from it, -26.3 (-94.5 to 22.2): it signs
fewer leases after inspecting (1.44 a market against 1.83; -139.2, -237.3 to
-53.1) and makes it up with blind signings worth it in expectation (+53.0, 25.1 to
85.4) and lucky draws (+62.5, crossing zero). GLM is below it, -220.2 (-339.6 to
-103.5), and not only by luck: it signs nearly as many inspected leases (1.77) but
gets 283.7 of surplus from each against the reference's 335.2 (-122.2, -186.7 to
-54.6), spends more on inspections (-33.3, -52.1 to -14.6), and its draws went
against it (-90.3, -173.6 to -13.9). The reference is a yardstick, not an optimum,
and the decision classes do not apply to it.

**By stratum (unregistered look, a hypothesis for the next identity).** Split by the
pack's declared strata, 12 worlds each, the two routes fall short of the reference
in opposite worlds. Where the favourite listing is a lemon, Gemini signs 1.12
inspected leases a market against the reference's 1.75 and 0.79 blind; with luck
removed it is -128.6 (-221.2 to -41.4) against the reference. Where the favourite is
sound, GLM pays above the ask on its inspected leases (+31.9 a lease; the reference
+1.0) and with luck removed is -194.8 (-272.0 to -125.4). The luck-removed pair gap
is +145.7 (4.8 to 261.7) in sound-favourite worlds and -63.5 (-220.2 to 79.0) in
lemon-favourite ones, a difference of +209.3 (8.4 to 404.5), resampling worlds
within strata. This was not declared, it is one of several cuts examined, and 12
worlds a stratum is thin: a v3 identity should declare the stratum contrast before
it runs rather than read it off this one. It is also confounded (HL-D-03): admission drops worlds where a
popular favourite is a lemon, so the pack's lemon-favourite worlds have less contested favourites (shared by 0.67
of tenants against 0.79), and the split compares contested with crowded markets as much as trap with control.

**Same states, both models (diagnostic, 2026-09-25).** The cells are markets of one
model's six tenants, so the routes differ in history and competition as well as in
policy. `tools/run_lemons_state_probe.py` removes the history: it sent each model the
exact recorded decision states of both routes' published cells (123 blind
sign-or-walk holds, 31 inspections before a blind signing, 80 sampled offers), three
times each at the campaign's own sampling; plan frozen to `runs/` before the calls
(sha256 57768ec0), 1,402 of 1,404 calls answered (one 503, one unparseable), $1.45.
Differences are over states, bootstrapped by state:

| on the same states | Gemini | GLM | Gemini minus GLM |
|---|---|---|---|
| signs a blind hold worth it in expectation (38 states) | 0.965 | 0.526 | +0.44 (0.32 to 0.57) |
| signs a blind hold not worth it (85 states) | 0.039 | 0.125 | -0.09 (-0.15 to -0.03) |
| expected surplus per sign-or-walk decision | +26.4 | -1.7 | +28.1 (14.7 to 42.8) |
| inspects, in the round before a blind signing | 0.935 | 0.968 | |
| offers, when asked to contact | 0.25 | 0.52 | |
| mean offer minus ask | -2.4 | -228.5 | |

So the policy difference is at the sign-or-walk decision: in identical states GLM
declines half the uninspected holds worth signing and signs one in eight that are
not; Gemini tracks expected value almost exactly. GLM also offers twice as often and
haggles far below the ask; the two inspect alike. This is sharper than the
run-level contrast, where the lemon draws swamp it (the luck-removed gap +41.1
crosses zero), and it is what the next identity should measure directly.

**Replicates.** Gemini's two seeds gave the same net payoff on 18 of 24 worlds
at temperature 1.0 (16 at 0); GLM's on 0 of 23. Gemini's agreement is its own
consistency, not an artefact of temperature 0 (HL-D-02, corrected).

**What this supports.** The realized payoffs differ by more than the world
variance, but most of that is which blind bets happened to be lemons; on the
decisions themselves, judged at what each tenant knew, the two are not
separated at this size, with GLM taking somewhat riskier bets. It does not support a ranking
or a winner: the GLM side is an incomplete pack, 24 worlds, one pack, and both routes
fill all six seats, so each number describes a market of one model, not one
agent against fixed competitors. Future lemons identities run 3 rounds, not 4 (case contract §5c, ruling of
2026-09-25). A publishable pair needs a new identity that
declares how an unanswered call is handled (a retryable `timeout` or a longer
action timeout), run on both routes.

## 22. Lemons price with outside demand (v14 confirmatory)

The three v14 identities, `housing_lemons_price_confirmatory_v14_{glm53_flash_nextbit,gpt6_luna,gemini38_flash}`
(case contract §5c, "One deciding tenant and outside demand"), put one deciding tenant, seat 0, against scripted
outside demand and both scripted landlord kinds on a 300-world pack; bundle
[`evidence/housing/housing_lemons_price_confirmatory_v14/`](../../../evidence/housing/housing_lemons_price_confirmatory_v14/)
with the declared fill beside it. This section was written on 2026-10-13, after v14 ran and was published.
**Status:** `v14_confirmatory_profile=partial`. No gate is `failed`; Gates 1 to 5 each still have a blocker. The
same day, after this section was first written, the blockers that could be closed offline were closed: goldens for
the price market, a declared rule for the $0-ceiling cells, the scripted controls published, a versioned measure for
HL-D-07 with the v14 recomputation published beside the bundle, and a contract-diff test of the three identities.
None of them changes a published v14 number or a declared verdict, and no gate became `passed`: what remains is either
a sealed artifact that needs provider calls or a step that had to happen before the v14 freeze.

| Gate | First written | Now | What still blocks it |
|---|---|---|---|
| 0 | `passed` | `passed` | |
| 1 | `partial` | `partial` | no measured-headroom screen of the frozen control (one replicate); no near-duplicate clustering; the holdout is new seeds, not a held-out mechanism |
| 2 | `partial` | `partial` | the goldens are tests, not a sealed golden-receipt bundle; the bundle holds no receipts, so a kernel replay cannot run from `evidence/` |
| 3 | `partial` | `partial` | no beatability rule declared before v14's results; v14's frozen primary is v1 and the HL-D-07 erratum waits on #117; HL-D-09 open |
| 4 | `partial` | `partial` | no sealed probe-based profile-admission receipts for the v14 profiles |
| 5 | `partial` | `partial` | no sealed variance pilot or sizing record; no A/A arm; both had to precede the freeze |

**Gate 0, profile admission: `passed`**, by this section: it references the standard and types each gate with its
blocker. v14 itself ran without one.

**Gate 1, task distribution: `partial`.** The pack regenerates from `lemons_design.confirmatory_pack()` and matches
`configs/housing_lemons_outside_demand_pack_v1.json` and its digest `39ddf59f…` (tested). Admission reads only seat
0's structure (a favourite and a second listing with positive gain if sound); the stratum is read afterwards from the
seed's own lemon draw, so admission cannot select on quality (the HL-D-03 fix). Quotas 200 favourite-lemon and 60
favourite-sound from seeds 300000-300441, holdout 30 and 10 from 400000-400063, disjoint from each other and from the
development worlds 100000-100059; no two of the 300 worlds give seat 0 the same view (tested). The holdout keeps the
main pack's difficulty: favourite-lemon share 75% against 77%, reference $280 against $292 a world, ceiling $353
against $370. Each world's deterministic baseline outcomes (no-op, weak control, baseline, reference, ceiling, both
arms) are published per world in
[`housing_lemons_price_v14_controls`](../../../evidence/housing/housing_lemons_price_v14_controls/).
**$0-ceiling cells, declared rule `housing_price_zero_ceiling_v1`** (`price_controls.ZERO_CEILING_RULE`, declared
2026-10-13, after v14 ran). Ten cells have a $0 ceiling, all pooled-arm favourite-lemon (seven main: 300002, 300055,
300073, 300308, 300346, 300357, 300409; three holdout: 400007, 400019, 400061): no listing is worth its landlord's
lowest acceptable rent to seat 0, so the best play is to do nothing. Such a cell stays in every net measure, per-world
mean and contrast; it is excluded from the numerator and the denominator of every share-of-ceiling ratio; and it is
counted and listed wherever a share is reported. Tested on world 300002 and against the bundle's ten cells
(`tests/test_housing_price_goldens.py`). No declared v14 verdict uses a share of the ceiling; under the rule the
models' realized shares on the main pack move from the bundle's 35.8%, 36.7%, 57.1% (GLM, Luna, Gemini) to 36.4%,
36.9%, 57.3%, the most on GLM's holdout (22.9% to 25.3%); the controls analysis reports both. Blockers: no
measured-headroom screen (the control was not run per world before the freeze, and with one replicate within-world
variance is unmeasured); no near-duplicate clustering; the holdout is new seeds of the same generator, not a held-out
mechanism.

**Gate 2, environment and verifier: `partial`.** `price_reference.run_world` drives the sealed market offline and
replayed the sealed scripted reference cell for cell (120 of 120 when written; four worlds pinned in
`tests/test_housing_price_reference.py`). `tests/test_housing_price_oracle_run.py` plays all 300 pack worlds under both
arms and reproduces the bundle's `reference_net` and `ceiling` in all 600 cells. In it a full-information tenant
(knows quality, never inspects, offers $0 in round 0 on its best listing at the target the landlord's own rule
returns, signs the counter) realizes `price_reference.ceiling` exactly in every cell; outside demand bid on its listing
in 295 of them and lost the declared $0 tie to seat 0. The check fails when it should: a landlord margin of $30 against
the ceiling's $25 moves 490 of 520 main-pack cells off it (tested). Every published receipt replays from its sealed
events (`aeread verify-replay`, 1,800 of 1,800; fill 48 of 48), and `your_history` carries no tenant id or quality
(tested). **Goldens for the price market** (`tests/test_housing_price_goldens.py`, closed 2026-10-13), on pack worlds,
every expected number computed in the test from the world's values, costs and asks:

- *successful*: the reference in 300000 and 300003 (leaky) signs at its landlord's rule target, a sound listing at its
  floor and a verified lemon at the lemon's own floor; seat 0's net is value less rent less the $25 fee, the landlord's
  payoff is $25, the ceiling is the same lease without the fee, and the endpoint's decomposition has no residual;
- *valid but poor*: `sign_anything` in 300002 (leaky) signs a lemon blind at $1 over the ask for -$695.61; the
  trajectory stays valid, the tenant's IR violation is recorded, and the stated-odds components (-$500 lemon draw,
  -$195.61 bet) are kept under v1 and v2;
- *invalid or unauthorized*: unknown, boolean and negative listing ids, negative, NaN and infinite rents, signing
  another seat's hold, inspecting a leased listing, a repeat inspection and a stale hold each get a typed verdict;
  the market's protected state ends identical to a seat that passed, with $0 credit;
- *malformed or operational failure*: malformed market actions become typed passes; through the kernel with a v14
  contract, a plain-text commit and GLM's own v14 commit `{"decision": "walk", "hold_id": null}` are sealed as
  `malformed_json` and `malformed_commit`, the cell completes, the hold lapses as a walk would, and seat 0 nets minus
  its fees, neither the lease nor $0; a failed cell is published with its typed condition and no primary, its world
  leaves the paired measure, and the failure is counted;
- *degenerate reference*: the $0-ceiling world 300002 pooled under the rule above.

Each kind has a counterexample that fails it: a landlord countering $1 over its rule, a market without its rent guard,
a share that keeps the $0 cell. Blockers: the goldens are tests over the real market and kernel, not a sealed
golden-receipt bundle as §14 publishes for the bid world; the bundle binds receipts by digest but holds neither
receipts nor trajectories (145 MB), so a kernel replay cannot be rerun from `evidence/`. Narrowed: seat 0's trajectory
facts for all 1,812 completed cells (v14 and the fill), each bound to its verified receipt and sealed event root, are
now in `evidence/housing/housing_lemons_price_v14_reply_conditioned/tables/seat0_trajectories.jsonl`, so the primary
measure (v1 and v2) is recomputed from `evidence/` alone.

**Gate 3, construct and baselines: `partial`.** The scripted controls are published
([`housing_lemons_price_v14_controls`](../../../evidence/housing/housing_lemons_price_v14_controls/),
`python -m aeread_families.housing.price_controls --check`; closed 2026-10-13). Main pack, per world, realized and
primary (v1):

| Seat 0 | Realized | Primary | Favourite lemon, realized | Favourite sound, realized |
|---|---|---|---|---|
| `pass` (no-op) | $0 | $0 | $0 | $0 |
| `sign_anything` (weak) | -$349 | -$80 | -$577 | +$410 |
| `inspect_then_sign` (baseline) | +$145 | +$145 | +$72 | +$385 |
| `inspect_lowball` (reachable reference) | +$292 | +$292 | +$255 | +$414 |
| GLM, Luna, Gemini (published) | +$132, +$136, +$211 | +$137, +$130, +$211 | +$69, +$55, +$153 | +$345, +$405, +$397 |
| full-information ceiling | +$370 | | +$349 | +$440 |

The controls are ordered by what they know, and the measure separates them: each model beats `pass` and
`sign_anything` on the primary, paired by world (GLM +$137 [+111, +162] and +$216 [+188, +244]; Luna +$130 and +$210;
Gemini +$211 and +$292). GLM and Luna do not separate from the simple baseline `inspect_then_sign` (-$8 [-30, +14] and
-$15 [-32, +2]); Gemini is above it (+$64 [+48, +80]); all three are below the reference. The gap between the
reference and the ceiling sits where the design puts the difficulty: under the $0-ceiling rule the reference reaches 73%
of the ceiling in favourite-lemon worlds (94% leaky, 35% pooled) and 94% in favourite-sound ones. The weak control's
realized -$349 against its primary -$80 is the stratification: seat 0's favourite is a lemon in 77% of main-pack worlds,
while its stated odds, and the measure, price every unverified listing at 2 in 4.
**HL-D-07, the versioned measure** (closed for later identities 2026-10-13): `price_reply_posterior`
(`housing_price_reply_conditioned_v2`) values a blind signing at its lemon probability given every inspection and every
informative reply up to its round, with the evaluator's knowledge of the true arm (leaky arm, offer below the sound
floor: a reply below the floor proves a lemon, a counter at the floor proves sound; an acceptance at or above the floor
and every pooled reply say nothing); hand-built cases, a property test of the landlord rule on every pack world and a
counterexample are in `tests/test_housing_price_reply_posterior.py`. The recomputation is the derived analysis
[`housing_lemons_price_v14_reply_conditioned`](../../../evidence/housing/housing_lemons_price_v14_reply_conditioned/)
(`python -m aeread_families.housing.price_reply_conditioned --check`, `--from-runs` to re-extract from the run
roots). Its v1 reproduces every published cell, `analysis.json` and the fill's `sensitivity.json` exactly; under v2,
main pack: Gemini +$212.81 [190.28, 235.35], GLM +$149.40 [123.77, 175.03], Luna +$147.34 [121.15, 173.54];
Gemini−GLM +$59.64 [38.52, 80.75], Gemini−Luna +$66.54 [49.37, 83.70], GLM−Luna +$2.06 [−20.03, 24.14] (HL-D-07's row
rounds the first lower bound to +38). 21, 33 and 3 blind signings are repriced (GLM, Luna, Gemini), all of sound
listings and all by a counter on the signed listing itself, so gap (2) changes nothing in v14; no declared verdict
changes. The same analysis counts seat 0's invalid actions: 16 GLM cells (15 on a leased listing, one malformed commit),
none for Luna or Gemini (HL-D-08). Blockers: no beatability or sensitivity rule was declared before v14's results,
which cannot be added after them; v14's frozen primary is v1, and the HL-D-07 erratum waits on the errata layer
(#117); the best-informed tenant (`price_best_informed`) is on branch `codex/housing-best-informed`, not here, so it is
not among the published controls; HL-D-09 (the receipts' scores are six-seat figures, not seat 0's) is open.

**Gate 4, attribution and controls: `partial`.** One focal subject against fixed scripted counterparts. Counterpart
scope: two landlord kinds, leaky (`true_cost`) and pooled, both played in every world and paired by world; outside
demand at 0.5 a round on a schedule fixed by the world and blind to quality (tested). The world is the independent
unit. Notice v4, retry policy v2, the limits and the pack are common to the three (`price_campaign._V14`, tested per
identity). The treatment is the model profile, not the model (HL-J-12). **Contract diff, tested**
(`tests/test_housing_price_v14_contract_diff.py`, closed 2026-10-13): it loads the three contracts and builds the six
plans that ran (each run-plan id equals the bundle's), and the fields that differ are exactly, in the contracts, the
identity, the route (eight fields), the reasoning tier (GLM and Luna `low`, Gemini `minimal`), `temperature` and
`top_p` (Luna sends neither) and the run's cost ceiling ($1.50, $1.50, $7.00); in the plans, the tenant profile's model
and revision, route pricing and provider metadata, reasoning effort, `top_p` and Luna's `temperature: unavailable`,
plus only the identifiers derived from them (run-plan id, plan digest, input digests, cell ids, admission id). An
undeclared difference fails it (tested). Blockers: no sealed probe-based profile-admission receipts for the v14
profiles (the plans' capability admissions are not probes, and the full-trajectory gate is each run's first world);
the result is conditional on scripted counterparts and says nothing about adaptive landlords.

**Gate 5, confirmatory reliability and publication: `partial`.** The analysis (`price_campaign.CONFIRMATORY_ANALYSIS`:
the primary measure, Holm over the three pairs, a $50 band, the main pack with the holdout reported apart, strata
beside) is in each v14 contract (commit `9441abca`, 2026-10-06 08:26 UTC) and is the bundle's `declared` block
(tested); the bundle has no cell timestamps, so "before any cell" rests on the case contract. Every planned cell is a
receipt digest or typed missingness: 1,764 completed, 36 Gemini cells refused for credits (HL-O-21). The fill ran
those 36 under its own identity as a declared exception, published beside v14 with v14 unchanged; its 12 overlapping
cells repeated v14's outcome. Blockers, none fixable for v14 because each had to be sealed before the freeze: no
sealed variance pilot or sizing record (the world count is the declared quotas within the $10 budget); no A/A arm, so
the $50 band is not calibrated against run-to-run noise; the HL-D-07 erratum waits on the errata layer (#117).

**What a v15 identity would need** (not run): a new identity per model profile, frozen only after

1. a sealed variance pilot on its own pilot pack (not the confirmatory worlds), every profile at two or more
   replicates per world, giving the paired world-level variance of each contrast and the within-world replicate
   variance, and the frozen control's per-world outcomes for the Gate 1 headroom screen;
2. a sealed sizing record: minimum meaningful difference ($50 a world), target power, Holm over the pairs, attrition
   from the pilot's failure rate, and the world count it implies within the declared budget;
3. an A/A arm: one profile run twice under two identities that differ only in the inference seed base, on the same
   worlds, to calibrate the band against run-to-run noise;
4. in the contract: measure v2 (`housing_price_reply_conditioned_v2`) as the primary, the $0-ceiling rule, a
   beatability rule (each model against `pass`, `sign_anything` and `inspect_then_sign`, paired by world), and the
   count of invalid actions in the publication;
5. sealed probe-based profile admission for every profile, and the account balance and key limit checked against the
   projected cost (HL-O-21);
6. a seat-0 scorer under a new scorer id in a new module (HL-D-09), and a holdout that changes a mechanism (the outside
   demand rate or the landlord margin) rather than only the seeds.
