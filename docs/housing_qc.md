# Housing V1 QC profile

**Standard:** [AERead benchmark QC](benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](experiment_campaign_sop.md)
**Status:** case-specific profile;
`development_case_qualification=passed` and
`normative_housing_profile=partial`. Confirmatory and live-model gates remain
incomplete, so normative promotion is blocked.

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
| Environment and verifier | Oracle enumeration, zero-bound quarantine, sealed scripted execution, and replay implemented | Complete targeted efficient, poor, invalid, malformed, and provider-failure golden receipts remain to be published as one QC bundle |
| Construct validity | Active no-op, seeded random, naive, adaptive, and oracle-informed audit implemented across the frozen development grid; eligibility and selection thresholds are frozen | The V1 model-sensitivity live gate stopped on typed provider failures before producing a valid trajectory; provider reliability must pass before freezing the confirmatory difficulty envelope |
| Attribution and controls | Complete population cross-play driver and plan-level block checks implemented; the V1 fixed-harness, four-condition model matrix passed design and provider-free validation | Focal-seat rotation remains a separate future block; the live V1 matrix must complete without route or provider-contract drift |
| Confirmatory reliability | Generic gate and analysis primitives only | No Housing variance pilot, power calculation, freeze artifact, or campaign gate history |

Housing may run development and qualification experiments, but it must not
present a confirmatory model leaderboard until every applicable gate has sealed
`passed` evidence.

## 7. Provider-free case-configuration sweep

[`housing_case_config_sweep_v1`](../configs/housing_case_config_sweep_v1.json)
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
python -m aeread.shared_runner.housing_case_sweep \
  --contract configs/housing_case_config_sweep_v1.json \
  --output runs/housing_case_config_sweep_v1
```

The output contains:

- `housing_case_facts.csv`: one row per development configuration and world;
- `housing_config_summary.csv`: one reportable row per candidate configuration;
- `selected_development_configs.json`: the predeclared selection result;
- `fact_manifest.json`: source-contract identity, implementation pins, row counts,
  and artifact digests;
- `sweep_summary.json`: completion, provider-call, cost, and holdout status.

The frozen development result is published in
[`docs/evidence/housing_case_config_sweep_v1`](evidence/housing_case_config_sweep_v1/).
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

[`housing_model_sensitivity_v1`](../configs/housing_model_sensitivity_v1.json)
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
python -m aeread.shared_runner.housing_model_sensitivity \
  --contract configs/housing_model_sensitivity_v1.json \
  --output runs/housing_model_sensitivity_v1 \
  --through provider_free

python -m aeread.shared_runner.housing_model_sensitivity \
  --contract configs/housing_model_sensitivity_v1.json \
  --output runs/housing_model_sensitivity_v1 \
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
[`housing_model_sensitivity_v1_qualification_2026-09-02.json`](evidence/housing_model_sensitivity_v1_qualification_2026-09-02.json).

Because only one world cluster was planned, even a complete run would remain a
descriptive integration slice with no estimable uncertainty. A variance pilot
can begin only after a complete live matrix passes under one frozen campaign
identity.

## 9. V2 alternate-backend qualification

[`housing_model_sensitivity_openrouter_alt_v2`](../configs/housing_model_sensitivity_openrouter_alt_v2.json)
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
[`housing_model_sensitivity_openrouter_alt_v2_qualification_2026-09-02.json`](evidence/housing_model_sensitivity_openrouter_alt_v2_qualification_2026-09-02.json).

The next attempt remains on OpenRouter and uses a new campaign identity, a fresh
catalog query, new route-bound profile hashes, and the same
admission-before-trajectory gate. Do not redirect V2 in place or retry only its
failed probes.

## 10. V3 OpenRouter-only route qualification

[`housing_model_sensitivity_openrouter_alt_v3`](../configs/housing_model_sensitivity_openrouter_alt_v3.json)
keeps OpenRouter as the gateway and tests a fresh route pair: Reka FP8 for GLM
5.3 Flash and Parasail FP8 for DeepSeek V4 Flash. V3 is a new campaign because
provider route, price, and profile identity are frozen controls. Its catalog
preflight also rejects endpoints whose completion limit is smaller than the
profile's frozen `max_output_tokens` value.

Run the gates with the local OpenRouter key:

```bash
python -m aeread.shared_runner.housing_backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_alt_v3.json \
  --output runs/housing_model_sensitivity_openrouter_alt_v3 \
  --through provider_free

python -m aeread.shared_runner.housing_backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_alt_v3.json \
  --output runs/housing_model_sensitivity_openrouter_alt_v3 \
  --through profile_admission

python -m aeread.shared_runner.housing_backend_campaign \
  --contract configs/housing_model_sensitivity_openrouter_alt_v3.json \
  --output runs/housing_model_sensitivity_openrouter_alt_v3 \
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
[`housing_model_sensitivity_openrouter_alt_v3_qualification_2026-09-02.json`](evidence/housing_model_sensitivity_openrouter_alt_v3_qualification_2026-09-02.json).

For review without publishing raw model reasoning, the repository also keeps a
digest-bound set of three V0 trajectory examples: the upper and lower observed
completed live-opponent cross-play cells and the shortest operational failure.
The export includes event-seal roots, receipt identities, action summaries,
outcomes, costs, and limitations, while the complete provider responses remain
under ignored local `runs/`. See
[`housing_population_crossplay_v0_trajectory_examples_2026-09-02.json`](evidence/housing_population_crossplay_v0_trajectory_examples_2026-09-02.json).

## 11. Frozen V0 population campaign

The first executable population campaign is
[`housing_population_crossplay_v0`](../configs/housing_population_crossplay_v0.json).
It compares GLM 5.3 Flash and DeepSeek V4 Flash as homogeneous tenant
populations against a scripted anchor and both live landlord profiles. The
scripted cells are controlled anchors, diagonal cells are self-play, and
off-diagonal cells are cross-play. Only the equal-weight mean over the two live
opponents enters the primary contrast.

Run gates in order; the driver resumes verified rows and records failed attempts:

```bash
python -m aeread.shared_runner.housing_population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --output runs/housing_population_crossplay_v0 \
  --through provider_free_validation

python -m aeread.shared_runner.housing_population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --output runs/housing_population_crossplay_v0 \
  --through full_trajectory

python -m aeread.shared_runner.housing_population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --output runs/housing_population_crossplay_v0 \
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
PYTHONPATH=src .venv/bin/python -m aeread.shared_runner.housing_population_campaign \
  --contract configs/housing_population_crossplay_v0.json \
  --output runs/housing_population_crossplay_v0 \
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
[`housing_population_crossplay_v0_requalification_2026-09-02.json`](evidence/housing_population_crossplay_v0_requalification_2026-09-02.json).

Apply the campaign SOP's backend-escalation instruction before the variance
pilot. OpenRouter remains the backend; any provider-route change requires a new
campaign identity and fresh admission rather than an in-place backend swap.
