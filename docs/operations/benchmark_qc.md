# Benchmark quality-control standard

**Status:** normative standard for AERead case families and campaigns.

This document defines when an AERead benchmark is trustworthy as a measurement
instrument. It complements the [experiment campaign SOP](experiment_campaign_sop.md),
which controls when one particular harness, model, opponent, prompt, reasoning,
or budget experiment may advance.

The boundary is deliberate:

- **Benchmark QC** validates the task distribution, environment, verifier,
  construct, and attribution design.
- **Campaign gates** validate the profiles, executions, freeze, analysis, and
  publication for one declared experiment.

A green campaign cannot repair a bad oracle or an uninformative mechanism. A
valid case family does not make an underpowered or selectively missing campaign
reportable.

Each family must publish a case-specific QC profile that binds this standard to
its generator or cases, verifier, metrics, goldens, baselines, roles, and
attribution design. Mark a check `not_applicable` only with a versioned rationale.

## 1. QC result vocabulary

Each QC track ends in one of five typed states:

| Status | Meaning |
|---|---|
| `passed` | Every required check passed and the evidence references are sealed |
| `failed` | At least one required check failed; downstream promotion is blocked |
| `partial` | Some named checks have evidence, but the declared scope is incomplete; promotion is blocked |
| `not_run` | The gate has not been attempted for this family or campaign version |
| `not_applicable` | A versioned rationale proves that a named check does not apply |

Development qualification and normative family readiness are separate tracks.
For example, Housing may have
`development_case_qualification=passed` while
`normative_housing_profile=partial`; only the normative `passed` state permits
promotion. Preserve failed attempts after later fixes. A passing test suite is
supporting evidence, not a substitute for an explicit QC record.

QC evidence may be reused across campaigns only when every bound input still
matches by typed identifier and digest.

A required check is evidence only once it has been **observed to fail on a
counterexample**. Demonstrate this by mutation: revert the guard, confirm the
check dies for the intended reason, restore it, confirm the check passes, and
record that the kill was real. A check that has never failed may be asserting
something true by construction; three defects fixed on 2026-09-05 passed every
existing suite for exactly that reason. Where a mutation does not kill a check,
record that rather than glossing it.

Every machine-consumed evidence reference records the artifact type, path,
SHA-256 digest, family ID and version, profile ID, and explicit required and
observed coverage IDs. At admission, the path is resolved inside an explicitly
declared evidence root and the SHA-256 digest is recomputed from the file bytes.
A path or caller-supplied digest by itself is not QC evidence. A gate may pass
only when its canonical artifact type matches and its bound artifacts
collectively cover every required ID in that gate's scope.

## 2. Standard gates

### Gate 0: Profile admission

**Purpose:** establish that this family has somewhere to record a gate result.

This is the first reject gate and it is evaluated before every other gate. A
family without a published QC profile is `failed`, not `not_run`: the remaining
gates are not merely unevaluated, they are unevaluable, because no artifact
exists that can hold their status.

Require, before Gate 1 is considered:

1. a profile at `docs/families/<family>/qc.md` that references this standard;
2. a typed normative status for the family, and a typed status for each of
   Gates 1 through 5;
3. a stated blocker for every gate that is not `passed`.

**Rejecting on a missing profile is not bureaucracy; it is the gate that makes
the others load-bearing.** Procurement is the worked example. Its Gate 3 check
ran, found that a deterministic policy reading only the displayed price beat the
qualified subject by $28.50 per world, and published that as campaign evidence
in `evidence/procurement_allocation_public_policy_baselines_v1/`. Because no
profile existed, the failing result had nowhere to be recorded and was read as
an interesting campaign finding rather than a construct-validity failure. The
gate had been performed and its verdict was lost.

This gate is enforced by `tests/test_benchmark_qc_profiles.py`, which fails when
a trusted family has neither a profile nor a named entry in that file's dated
exemption list. The exemption list is the backlog for families that predate this
gate; its length is asserted, so adding a family to it is visible in review
rather than silent.

Stop when a family is registered, promoted, or described as measuring its
declared construct without a profile.

### Gate 1: Task-distribution admission

**Purpose:** establish that sampled tasks are valid, distinct, informative
instances of the declared construct.

Required checks:

1. Re-resolve or regenerate every task from its pinned source, generator,
   parameters, versions, and seeds; require identical canonical content digests.
2. Validate required dimensions, types, identities, ranges, and finite numeric
   fields.
3. Validate every denominator, bound, reference value, or expected answer used
   for normalization. Degenerate tasks remain visible and are quarantined or
   reported under a predeclared rule rather than silently resampled.
4. Measure predeclared difficulty dimensions and reject or stratify a panel that
   falls outside its acceptance envelope.
5. Reject exact duplicates. Cluster near-duplicates, shared sources, parameter
   siblings, or other tasks that are not independent evidence.
6. Bind development and confirmatory splits to disjoint seed, source, or
   parameter domains. A new seed alone is not a held-out mechanism condition.

Exit evidence includes a source or generator manifest, task identifiers and
digests, validation results, denominator or reference checks, difficulty slices,
duplicate and cluster assignments, split membership, and typed exclusions.

Stop on invalid or non-finite inputs, resolution drift, an unverified bound,
duplicate leakage across independent clusters, or development/holdout overlap.

#### Measured headroom

A panel is *informative* only if the declared control leaves rows it can fail.
Establish this by measurement, not by inspecting world definitions:

1. Before freezing a panel, run the frozen control, or a cheaper declared
   baseline policy, across every candidate world.
2. Admit a world only when the control fails at least a declared minimum share of
   its rows, and publish the measured control rate per admitted world in the
   panel manifest.
3. A holdout must additionally preserve the difficulty of the panel it holds out
   from. Matching a panel's failure *themes* does not match its difficulty.

Skipping this produces a panel that passes every other Gate 1 check and still
cannot measure anything. Procurement's `confirmatory_v2` is the worked example:
twelve worlds with distinct seeds, distinct economic-world digests, and positive
reachable bounds, on which the control scored 97% against 56% on the panel it
replaced and won every completed row in seven of twelve worlds. A 144-row run was
spent discovering it.

### Gate 2: Environment and verifier

**Purpose:** prove that actions change the intended state and that scores are
deterministically reconstructed from evidence rather than trusted from an agent,
provider, or simulator declaration.

Every family maintains at least these goldens when applicable:

| Golden | Required behavior |
|---|---|
| Successful | Legal trajectory realizes a known successful outcome and exact accounting |
| Valid but poor | Legal low-quality outcome stays valid and preserves component diagnostics |
| Invalid or unauthorized | Invalid action changes no protected state and receives no positive credit |
| Malformed or operational failure | Malformed output and infrastructure failure become typed invalidity or missingness, never task-quality zero |
| Degenerate reference | Zero, missing, or undefined denominator follows the declared non-fabrication rule |

Additional requirements:

1. Cross-check deterministic oracles against an independent implementation,
   exhaustive enumeration on small instances, or hand-verifiable goldens.
2. Reconstruct transitions from sealed observations, parsed actions, legality
   results, tool results, and pre-state. Recompute terminal state and score.
3. Reconcile component accounting exactly and reject scores outside declared
   support or verified bounds.
4. Audit every agent-visible payload for evaluator-only state leakage.
5. Require offline replay to reproduce state and score with zero provider calls.

Exit evidence includes golden receipts, sealed event stores, independent oracle
checks, replay results, visibility audits, and scorer/accounting reports.

Stop when invalid activity mutates protected state, an oracle check disagrees,
hidden state leaks, a score cannot be reconstructed, or replay differs.

#### External-wrapper parity

An external benchmark wrapper must declare, before execution:

1. the exact external task or task set;
2. the treatment reproduced inside AERead;
3. the metric compared;
4. the original paper or benchmark conclusion; and
5. the numeric or exact tolerance used to decide parity.

Component and adapter parity still remain visible separately. Matching record
shapes is not evidence that AERead reproduced the original result unless the
declared external-result criterion also passes. The criterion includes a pinned
source reference, names one declared parity field, and uses exactly that
field's comparison mode and tolerance; the report records its result as
`criterion_matched`.

### Gate 3: Construct validity and baselines

**Purpose:** show that the active interface distinguishes the intended
capability from weaker behavior, shortcuts, and mechanism artifacts.

Each case profile declares applicable controls, normally including:

- a no-op or feasible lower-policy anchor;
- a seeded random or weak behavioral control;
- a simple comparison baseline;
- an informed or adaptive policy using permitted observations;
- an evaluator-only oracle-informed diagnostic or attainable ceiling when one
  can be defined without leaking hidden state.

Predeclare a beatability or sensitivity rule before inspecting model results.
Require a deliberately better-informed policy, admissible counterfactual, or
controlled perturbation to improve the intended outcome on a declared
nontrivial slice. If behavior cannot change the measured outcome, reject or
narrow the construct claim rather than increasing sample size.

Report primary outcomes, important components, validity, compliance,
reliability, action or answer rate, and efficiency separately. Test shortcuts
specific to the generator, source, seat order, prompt surface, tools, and
verifier.

Exit evidence includes pinned policy definitions, paired per-task baseline
facts, uncertainty, beatability or counterfactual results, shortcut tests, and
difficulty slices.

Stop when stronger and weaker policies are indistinguishable under the declared
rule, performance is driven by a shortcut, or the metric hides a critical
validity or component failure.

### Gate 4: Attribution and experimental controls

**Purpose:** ensure that each result supports its claimed level of attribution.

Each case profile declares its valid blocks. Examples include:

- one focal subject with fixed background participants;
- one subject profile filling a population of equivalent seats;
- full subject-by-opponent cross-play;
- same-model role-conditioned self-play;
- one agent against a scripted user, supplier, judge, database, or policy;
- a single-agent task with no adaptive counterparty.

Required controls:

1. Declare one primary treatment factor. Bind every other knob as a control,
   predeclared robustness arm, or diagnostic.
2. Pair conditions on the same admitted task and environment randomness. Rotate
   order or seats when order or identity may confound the treatment.
3. Pin prompts, schemas, tools, memory, harness, model revision, provider route,
   reasoning and sampling settings, budgets, retries, and seed derivation.
4. Prove with plan-level contract tests that only the declared treatment or
   rotation changes between paired plans.
5. Declare the independent cluster. Treat repeats, seats, calls, turns, and
   opponents inside that cluster as correlated observations.

#### Profile admission

Profile admission asks whether one exact model-role execution contract is
eligible for comparison. It does not measure task quality.

For every action schema or tool boundary used by a profile, run the number and
kind of probes declared by the case profile. Admission requires valid structured
actions, exact route or runtime verification, complete usage and billing
evidence when applicable, and no hidden retries or silent repairs. Failed
profiles remain visible and unranked.

One complete trajectory per admitted condition is the subsequent campaign
`full_trajectory` gate, not part of schema admission.

Exit evidence includes sealed profiles, prompt and implementation digests,
admission receipts, the complete treatment matrix, paired-plan invariant audits,
and route, usage, billing, retry, and tool reconciliation.

Stop when a profile changes interface behavior, a route drifts, a matrix is
incomplete, a rotation changes undeclared controls, or the assignment block does
not support the attribution claim.

### Gate 5: Confirmatory reliability and publication

**Purpose:** convert a qualified design into a reportable comparison without
post-outcome tuning.

Required sequence:

1. Complete the full paired design on a predeclared variance-pilot panel. Do not
   infer or publish a winner from the pilot.
2. Choose confirmatory cluster count from paired cluster-level variance, a
   declared minimum meaningful effect, target power, and attrition rule.
3. Before confirmatory outcomes are inspected, hash the holdout tasks, seeds,
   profiles, prompts, harness, retry rules, execution order, analysis plan,
   missingness policy, stopping rule, implementation pins, and cost ceiling.
4. Average stochastic repeats within the declared independent cluster before
   treating clusters as independent evidence.
5. Preserve every planned cell as a verified receipt or typed missingness. Do
   not selectively rerun a losing condition or score operational failure as
   task-quality zero.
6. Report paired cluster-level intervals, predeclared slices, reliability,
   exclusions, and missingness alongside aggregates.
7. Prove every guarded metric is falsifiable. For each quantity a promotion rule
   guards, construct a synthetic arm that maximizes it through behavior the rule
   is meant to reject, and require the rule to reject that arm. A metric is a
   guardrail only when some behavior fails it. Terminal feasibility is the worked
   example: it counts an explicit deferral as a success, so a treatment that
   defers more can satisfy a feasibility guardrail while earning nothing, and the
   guarded quantity must instead be one that a deferral fails.
8. Publish canonical fact tables and a manifest whose rows trace to admitted
   profiles, plans, receipts, and evidence.

This gate is enforced through `variance_pilot`, `confirmatory_freeze`,
`confirmatory_execution`, and `publication` in the
[campaign SOP](experiment_campaign_sop.md).

Stop when the pilot design is incomplete, the powered sample exceeds the
declared budget, a frozen control changes, missingness is selective, a guarded
metric has no failing counterexample, or published aggregates cannot be
reconstructed from canonical facts.

## 3. Mapping QC to campaign promotion

| Benchmark QC evidence | Campaign gates that consume it |
|---|---|
| Profile admission | every gate; a missing profile rejects before evaluation |
| Task-distribution admission | `design_contract`, `confirmatory_freeze` |
| Environment and verifier | `provider_free_validation`, `publication` |
| Construct validity and baselines | `design_contract`, `provider_free_validation` |
| Attribution, controls, and profile eligibility | `design_contract`, `profile_admission`, `full_trajectory` |
| Confirmatory reliability and publication | `variance_pilot`, `confirmatory_freeze`, `confirmatory_execution`, `publication` |

Campaign records reference QC artifacts rather than duplicating them. If a
referenced QC digest changes, the consuming campaign gate must be retried.

## 4. Change invalidation

Re-run at least the listed gates after a bound input changes:

| Change | Gates invalidated |
|---|---|
| Task source, generator, parameters, or split rules | 1 through 5 |
| Environment phases, visibility, tools, or action legality | 2 through 5 |
| Oracle, verifier, scorer, normalization, or terminal accounting | 2 through 5 |
| Baseline or construct claim | 3 through 5 |
| Subject, opponent, simulator, judge, or seat assignment | 4 and 5 |
| Model route, prompt, harness, schema, budget, or retry policy | Profile admission onward for the affected campaign |
| Analysis, stopping rule, seeds, or sample size after freeze | New campaign identity |

A mechanical correction preserves campaign identity only when the scientific
contract is unchanged and both original and corrected artifacts remain
traceable.

## 5. Case-specific profiles

Each profile must state current implementation coverage and must not translate
`partial` into `passed`. A missing profile is rejected at
[Gate 0](#gate-0-profile-admission) before any other gate is evaluated.

Published profiles:

| Family | Profile | Normative status |
|---|---|---|
| Housing V1 | [housing/qc.md](../families/housing/qc.md) | `partial` |
| Procurement allocation V1 | [procurement-allocation/qc.md](../families/procurement-allocation/qc.md) | `partial`, construct gate `failed` |

A family may run development campaigns while carrying a dated Gate 0 exemption,
but no family may publish a result described as measuring its declared construct
until its profile exists and records that gate.

## 6. New-family contribution admission

A contributed family cannot enter the normal plugin registry until one
version-bound contribution record proves all of the following:

- a unique registry namespace bound to the exact family ID, family version, and
  plugin ID;
- closed action and observation schemas: every object declares all properties
  as required and sets `additionalProperties=false`;
- a content-addressed provider-free conformance report with complete declared
  coverage;
- finite ceilings for wall time, logical actions, provider calls, input and
  output tokens, and cost; and
- human QC approval whose evidence and approval digest bind the exact
  contribution contract.

In-tree families that predate this contract use the explicitly named trusted
registration path. New contributions use the qualified path and cannot replace
an existing family/version key or reuse another contribution's namespace.
Admission verifies both provider-free and human-QC evidence files against an
explicit evidence root and retains the contributed resource limits in the
registry record. Trusted conformance execution, runtime limit enforcement, and
reviewer authentication remain promotion blockers in
[QC/SOP open items](qc_sop_open_items.md).
