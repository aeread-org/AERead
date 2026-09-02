# Housing V1 QC profile

**Standard:** [AERead benchmark QC](benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](experiment_campaign_sop.md)
**Status:** case-specific profile; current executable coverage is partial.

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
| Task-distribution admission | Development-panel audit implemented | Held-out parameter combinations and a confirmatory admission artifact are not frozen |
| Environment and verifier | Oracle enumeration, zero-bound quarantine, sealed scripted execution, and replay implemented | Complete targeted efficient, poor, invalid, malformed, and provider-failure golden receipts remain to be published as one QC bundle |
| Construct validity | Active no-op, seeded random, naive, adaptive, and oracle-informed audit implemented | Freeze a confirmatory difficulty envelope and beatability threshold beyond the current development panel |
| Attribution and controls | Complete population cross-play driver and plan-level block checks implemented | Focal-seat rotation remains a separate future block; live profiles and the full matrix must pass their gates |
| Confirmatory reliability | Generic gate and analysis primitives only | No Housing variance pilot, power calculation, freeze artifact, or campaign gate history |

Housing may run development and qualification experiments, but it must not
present a confirmatory model leaderboard until every applicable gate has sealed
`passed` evidence.

## 7. Frozen V0 population campaign

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

Apply the campaign SOP's backend-escalation instruction before the variance
pilot. The direct OpenRouter route remains the V0 backend; adopting an Arena API
requires a new campaign identity and fresh admission rather than an in-place
backend swap.
