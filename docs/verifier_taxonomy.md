# Verifier taxonomy and composition contract

**Status:** shared-runner measurement contract

**Decision:** classify verifiers by the claim their evidence can establish, while recording
stochastic estimation, admission checks, and composition as separate attributes

**Non-goal:** forcing heterogeneous cases into one universal score or one universal oracle

## 1. Why heterogeneous cases belong in one measurement layer

AERead cases do not need the same gold object. They belong under one runner because they
share a typed claim-to-evidence contract:

```text
case -> estimand -> semantic verifier -> reference/evidence -> typed result -> receipt
```

The domain says what happens in the environment. The estimand says what quantity or
property the study claims to measure. The verifier says how recorded evidence supports
that claim. A reference may be a point answer, an acceptable set, a property, a certified
bound, an executable comparator, or a rater protocol. The receipt makes that choice and
its provenance inspectable.

This common wrapper provides replay, validity, versioning, uncertainty, and honest claim
language. It does **not** imply that exact refund-state correctness, bounded housing
welfare, and a judged negotiation outcome are numerically interchangeable.

## 2. Two-axis classification

Every primary or diagnostic estimand declares one semantic verifier family and the
applicable modifiers.

For communication, this is a **seven-part operational verification framework**:
five semantic verifier families plus two cross-cutting layers, stochastic/statistical
estimation and integrity/admissibility. The seven parts should not be flattened into
one schema enum because they answer different questions: what claim is established,
how repeated evidence is estimated, and whether that evidence is admissible.

### 2.1 Semantic verifier families

| Family | Core question | Typical references |
|---|---|---|
| `canonical_reference` | Does the answer or outcome match an accepted target? | point, acceptable set, equivalence relation, distance function |
| `rule_constraint` | Does the answer, state, or trajectory satisfy declared rules? | predicate set, invariant, temporal formula, metamorphic relation |
| `objective_reference` | How good is the outcome under a declared objective? | exact optimum, certified bounds, support bounds, executable baseline |
| `comparative` | How does the policy perform relative to a named comparator or field? | baseline policy, paired system, opponent panel, human reference distribution |
| `rater_judge` | How does a declared rater protocol assess the artifact? | human rubric, LLM rubric, preference or ensemble protocol |

### 2.2 Orthogonal modifiers and layers

These do not replace the semantic family:

- **Evaluation mode:** deterministic calculation, `stochastic_estimator`, or
  judge-dependent assessment.
- **Match mode:** exact, tolerance-based, set membership, equivalence, or distance.
- **Input scope:** answer, terminal state, trajectory, or distribution over outcomes.
- **Integrity layer:** `measurement_validity` checks whether the evidence may enter the
  analysis.
- **Composition:** leaf result, deterministic gate, retained vector, or defended weighted
  composite.

A stochastic refund user simulation can still feed a canonical terminal-state verifier.
A deterministic transcript can still feed a judge-dependent rubric. Calling
"simulation" a verifier family would erase the substantive claim in both examples.

## 3. Canonical-reference verifiers

Canonical verification applies when acceptable correctness can be specified without
optimizing a policy objective.

| Reference kind | Contract | Appropriate result |
|---|---|---|
| `canonical_point` | Compare with one scalar or structured target after declared canonicalization. | exact/tolerance pass and error |
| `canonical_set` | Accept membership in a versioned set of valid answers or outcomes. | membership plus optional distance |
| `terminal_state_equivalence` | Compare a canonical terminal state or its equivalence class, independent of irrelevant ordering or representation. | pass plus field-level differences |
| `distance_to_canonical_set` | Compute the minimum declared distance from the observed object to any accepted object. | native-unit distance and threshold result |

For an interactive task, the canonical object should normally describe acceptable answers,
terminal outcomes, or equivalence classes—not **one canonical action sequence**. Multiple
legal tool trajectories can reach the same correct refund state. A trajectory becomes the
gold object only when the path itself is part of the estimand, such as consent before a
mutation or a prohibited disclosure.

Canonicalization, ignored fields, tolerances, equivalence relations, and reference hashes
are part of the verifier version. If the accepted set is incomplete, a failed membership
test is evidence about that reference set, not automatically proof that the policy is
economically wrong.

## 4. Rule, constraint, and temporal verifiers

These verifiers evaluate declared predicates rather than proximity to a single target.

| Reference kind | Input scope | Example |
|---|---|---|
| `constraint_satisfaction` | answer, state, or action | allocation feasibility, policy eligibility, tool legality |
| `state_invariant` | each state or selected checkpoints | budget never negative, protected field never changes |
| `temporal_property` | ordered event trajectory | obtain consent before mutation, refund only after eligibility check |
| `axiom_relation` | answer or outcome set | individual rationality, no blocking pair, equilibrium residual |
| `metamorphic_relation` | related cases or reruns | relabeling agents preserves an allocation property |

The verifier returns the predicate vector, failures, and any native residuals. A single pass
rate may summarize predicates only when the aggregation rule is declared. A hard gate is
justified for logical prerequisites such as legality; it should not silently convert a
normative tradeoff into invalidity.

## 5. Objective, optimum, and bound verifiers

An objective verifier requires a declared feasible policy class, objective, direction,
information set, horizon, environment/opponent condition, and units. For maximization:

`V_LB <= V* <= V_UB`

### 5.1 Reference kinds and claim patterns

The settable `reference_kind` values for the `objective_reference` family are exactly
`exact_optimum`, `objective_lower_bound`, `objective_upper_bound`,
`comparison_baseline`, `outcome_support_min`, and `outcome_support_max`. Every
`VerifierSpec.reference` carries one `ReferenceSpec`, so a claim resting on two
references (a lower and an upper bound, say) is declared as two measurement leaves,
one per reference kind — the per-bound pattern the housing family pins with its
single `objective_upper_bound` leaf.

The table below names the common claim patterns and what each is built from. The
pattern names in the left column are conceptual labels for derived quantities; they
are never literal `reference_kind` values.

| Claim pattern | Built from | Permitted claim |
|---|---|---|
| exact optimum | one `exact_optimum` leaf | exact regret or optimality ratio within its validity domain |
| bound certificate | one `objective_lower_bound` leaf plus one `objective_upper_bound` leaf | certified regret interval and bound status |
| baseline headroom | one `comparison_baseline` leaf plus one `objective_upper_bound` leaf | fraction of that declared headroom captured (derived, section 5.3) |
| support-normalized outcome | one `outcome_support_min` leaf plus one `outcome_support_max` leaf | bounded support position (derived, section 5.3) |
| objective value only | no `objective_reference` leaf is constructible | descriptive value; no optimality claim |

**A feasible policy is not an outcome floor.** Its value witnesses a lower bound on the
unknown optimum; another policy may do worse. Likewise, an objective's nominal maximum is
not a problem-specific upper bound unless every admissible outcome is proven to satisfy it.

### 5.2 Certified regret

For a feasible evaluated policy with value `V_agent` under the exact same objective and
conditions, a valid bound certificate implies:

`max(0, V_LB - V_agent) <= regret <= V_UB - V_agent`

where `regret = V* - V_agent`. Equality of the bounds yields exact regret. With sampling
error, estimated values and bounds require a joint uncertainty procedure before this is
called a certificate. Apparent violations such as `V_agent > V_UB` invalidate the claimed
common domain until reconciled; they are not clipped away.

### 5.3 Baseline headroom versus support normalization

If `V_UB > B`, the fraction of declared baseline-to-upper-bound headroom captured is:

`headroom_capture = (V_agent - B) / (V_UB - B)`

This is a comparative statistic, not automatically a score in `[0, 1]`. It may be negative
when the agent loses to the baseline. It may exceed one when the references, stochastic
estimates, or validity domains disagree. Record and investigate those cases rather than
clipping them. `B` remains a comparison baseline even when its value also witnesses
`V_LB`. Both `headroom_capture` and the support-normalized position are derived
statistics computed from the per-bound leaves of section 5.1; "baseline headroom" and
"support-normalized outcome" are claim-pattern names, never `reference_kind` values.

If `S_min` and `S_max` are true support bounds applying to every admissible realized
outcome, then:

`support_score = (V - S_min) / (S_max - S_min)`

Only this second construction is bounded by outcome support. It does not express distance
to the optimum. An exact ratio such as `V_agent / V*` is allowed only when zero has a
substantive meaning, the scale is ratio-valued, the denominator is nonzero with a known
sign, and the direction/domain match. Minimization problems must reverse the inequalities
or first transform to a declared higher-is-better objective.

## 6. Comparative verifiers

Comparative verification is appropriate when there is a scientifically meaningful
reference but no defensible optimum.

| Reference kind | Contract |
|---|---|
| `baseline_delta` | Compare native outcomes with a named, versioned, executable policy under the same design. |
| `paired_comparison` | Evaluate systems on identical independently sampled clusters/seeds and report paired effects. |
| `head_to_head` | Evaluate against a declared opponent, field, or matchup distribution. |
| `human_reference_comparison` | Compare with a specified human sample and collection protocol. |
| `field_rating` | Estimate a rating under a fixed population, pairing rule, and statistical model. |

The comparator, opponent population, matching rule, and cluster structure are part of the
estimand. A win rate against one opponent is not a universal capability score, and beating
a baseline does not establish closeness to optimality. Comparative effects stay in native
units or use a predeclared interpretable transformation.

## 7. Rater and judge verifiers

Use `human_rubric`, `llm_rubric`, pairwise preference, or an ensemble only when the target
cannot be fully reduced to deterministic state, rule, or objective checks. The result is
judge-dependent and records:

- rubric and prompt/version hashes;
- rater identity class, model snapshot, decoding settings, and blind/randomized order;
- replicate count, aggregation, disagreement, and missingness;
- calibration examples and reliability evidence where available; and
- the exact artifact visible to each judge.

Deterministic components remain separate. For example, a refund database match should not
be hidden inside an LLM's holistic score. A judged explanation also cannot override an
illegal action or incorrect terminal state unless the declared estimand explicitly asks
about explanation quality.

## 8. Stochastic and statistical estimation

`stochastic_estimator` is an evaluation mode applied to a semantic verifier when users,
opponents, environments, policies, or judges vary. Common outputs include expected value,
success probability, risk/quantiles, and robust pass-all-runs measures such as `pass^k`.

The estimator declares the sampling population, independent cluster, nested replicates,
pairing, seeds, missing-data rule, interval procedure, and estimand transformation. More
reruns of one task reduce conditional Monte Carlo error but do not create more independent
task clusters. A deterministic verifier applied after each stochastic run does not make
the suite deterministic; it makes correctness per realized run deterministic.

## 9. Measurement validity and admission

`measurement_validity` is an integrity layer, not a capability score. It checks that the
claimed verifier received admissible evidence, including as applicable:

- schema and action legality;
- required observation exposure and context delivery;
- tool-call and state-transition completeness;
- retry, truncation, reasoning-budget, and provider-attempt accounting;
- task, policy, model, simulator, scorer, oracle, and artifact hashes; and
- event-chain integrity, deterministic replay, and scorer reproducibility.

An invalid or missing observation must not be scored as an economic zero, a failed refund,
or a dominated policy. The receipt reports `invalid_measurement`, the failed admission
checks, and whether a fresh episode attempt is allowed.

## 10. Hybrid composition

Many cases legitimately use more than one leaf verifier. Preserve the typed vector first.

- `hybrid_gate`: apply deterministic prerequisites such as legality, then report the
  admitted outcome vector.
- `vector`: report co-primary or diagnostic components without scalar collapse.
- `weighted`: allowed only with declared normative weights, units/transformation,
  sensitivity analysis, and an explanation of the decision problem the weights represent.
- `judge_augmented`: retain deterministic components and the judge-dependent component;
  the aggregate remains judge-dependent.

A gate should express logical admissibility, not hide a welfare/distribution tradeoff. A
weighted composite is not universal merely because every case emits a number.

## 11. Minimum `VerifierSpec`

Each leaf verifier is resolved into the run plan and receipt:

```yaml
verifier_id: tau3_terminal_db_v1
version: 1
measurement_kind: property_or_answer
verifier_family: canonical_reference
input_scope: terminal_state
reference_kind: terminal_state_equivalence
reference_hashes: [sha256:...]
direction: higher_is_better
units: pass
match_mode: equivalence
determinism: deterministic
composition: leaf
validity_domain:
  suite: tau3-retail-v1.0.1
  split: base
implementation:
  package: aeread_tau3_adapter
  commit: ...
cluster_mapping: task_instance
```

At minimum, `VerifierSpec` binds `verifier_id`, version, `measurement_kind`, semantic
`verifier_family`, `input_scope`, `reference_kind`, direction/units, determinism,
composition, validity domain, implementation provenance, evidence/reference hashes, and
the estimand's cluster mapping. Objective verifiers additionally bind the feasible set,
information set, horizon, bound proof types, and baseline. Judge and stochastic modes add
their protocols and sampling fields.

## 12. Current case mappings

| Case/estimand | Semantic verifier | Modifiers and claim boundary |
|---|---|---|
| tau3 refund terminal database | `terminal_state_equivalence` | deterministic leaf per run; stochastic user runs are nested replicates |
| refund eligibility, amount, or method | `canonical_set` or `constraint_satisfaction` | depends on whether alternatives are enumerated or rule-derived |
| consent before refund mutation | `temporal_property` | trajectory-scoped deterministic predicate |
| housing social welfare | `bound_certificate` | report native value and certified regret interval; no universal scalar |
| exactly solvable allocation/procurement | `exact_optimum` | only inside the solver's declared validity domain |
| fixed-opponent negotiation | `paired_comparison` or `head_to_head` | identifies performance against that opponent/panel, not global optimality |
| qualitative service quality | `human_rubric` or `llm_rubric` | judge-dependent; deterministic state checks remain separate |
| replay, hashes, and reasoning starvation | `measurement_validity` | admission evidence, never economic utility |

The taxonomy therefore tells readers what kind of evidence closes each claim. It allows
case-by-case verification while making results reproducible and preventing a property
check, a bound, a baseline comparison, and a judge score from masquerading as the same
kind of measurement.

A compact one-real-world-example and one-benchmark-per-class crosswalk is maintained in
[`verifier_case_mapping.md`](verifier_case_mapping.md). The exhaustive paper-by-paper
reference audit remains in [`problem_bound_case_audit.md`](problem_bound_case_audit.md).

## 13. Deployment-oriented mappings from the 23-paper audit

The examples below prioritize operationally recognizable workflows. They are proposed
AERead integration routes, not claims that every source paper already implements the
exact `VerifierSpec`. In particular, a paper may expose the state needed for a
deterministic verifier while publishing a human-adjudicated or comparative score.

| Operational part | Representative paper and deployable workflow | AERead verifier route | Published-evidence saturation status |
|---|---|---|---|
| **canonical/reference** | **P11 FinanceBench**: answer a structured numerical question from a real financial filing | Canonicalize value, currency, unit, period, and evidence reference, then apply exact/tolerance matching. The published full evaluation was manually adjudicated, so this deterministic route is limited to a separately declared structured subset. | `not_demonstrated`: a fixed canonical suite has a correctness ceiling, but the paper does not establish robust ceiling exhaustion for this deterministic subset. |
| **rule/constraint/temporal** | **P21 AucArena**: execute bids in a procurement-style auction | Replay the trajectory and verify budgets, bid increments, action legality, and declared acquisition goals. Environment enforcement and independent verification remain distinct. | `not_demonstrated`: the published results do not show robust pass-all-runs compliance with cluster-level coverage on a fixed predicate suite. |
| **objective/optimum/bound** | **P19 Market-Bench**: manage procurement, pricing, inventory, cash, and balance-sheet outcomes | Preserve native profit/net-worth as `objective_value_only`, plus named policy comparisons under the same market condition. | `saturation_undecidable`: no certified policy upper bound is supplied. |
| **comparative** | **P07 TERMS-Bench**: negotiate a buyer-supplier price against a version-pinned counterpart | Pair agents on identical cases, roles, simulator types, and seeds; report utility, agreement, and failure deltas. Retain the extra-information dynamic program as a separately typed upper bound. | `not_demonstrated`: the published evidence does not certify a predeclared epsilon-small bound gap with cluster-level uncertainty. |
| **rater/judge** | **P12 GDPval**: produce an analyst report, spreadsheet, presentation, or other professional deliverable | Use blinded expert rubric or pairwise preference records with ties, disagreement, rater provenance, and uncertainty. | `not_applicable` to universal capability saturation: the result is relative to a replaceable expert/reference system and rubric. |
| **simulation/statistical** | **P23 Vending-Bench**: operate an inventory-and-pricing business under simulated customer demand | Apply the objective verifier per run, then estimate expected net worth, failure risk, and quantiles across declared task clusters and nested seeds. | `saturation_undecidable`: repetition estimates the outcome distribution but does not create the missing policy upper bound. |
| **integrity/admissibility** | **P02 AERead**: admit an economic-agent episode before any capability score enters analysis | Verify schemas, observation delivery, provider attempts, retries, state transitions, hashes, deterministic replay, and scorer reproducibility. | `not_applicable`: measurement validity is an admission layer, not a capability scale. AERead welfare saturation must be assessed separately against its typed bound. |

The status labels have deliberately narrow meanings:

- `not_demonstrated`: the fixed estimand admits a meaningful ceiling test, but the
  published evidence does not meet the predeclared gap, independent-cluster uncertainty,
  coverage, and validity requirements.
- `saturation_undecidable`: the evidence lacks a defensible upper bound for the declared
  policy problem, so compression or strong comparative performance cannot establish
  remaining headroom.
- `not_applicable`: the row is a moving comparison, judge protocol, or integrity layer
  rather than a fixed capability ceiling.

None of these seven representative mappings is currently certified as `ceiling_exhausted`.
This does not mean every case is difficult. It means the available evidence does not
support the stronger, typed saturation claim.
