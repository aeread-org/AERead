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

Every failure -- a design defect, a sealed attempt, a broken tool, or a claim
that turned out to be wrong -- is indexed in the
[incident log](incident_log.md). Preserving failed attempts is already required;
the register is where they are findable. A row is added when something fails, not
when it is fixed, and rows are never deleted.

A required check is evidence only once it has been **observed to fail on a
counterexample**. Demonstrate this by mutation: revert the guard, confirm the
check dies for the intended reason, restore it, confirm the check passes, and
record that the kill was real. A check that has never failed may be asserting
something true by construction; three defects fixed on 2026-09-05 passed every
existing suite for exactly that reason. Where a mutation does not kill a check,
record that rather than glossing it.

This standard's task and outcome validity checks align with the
[Agentic Benchmark Checklist (Zhu et al., 2025)](https://arxiv.org/abs/2507.02825).
The mutation requirement above is AERead's concrete check that a claimed guard
can detect the defect it is meant to catch.

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

1. Before freezing a panel, run **the frozen control itself** across every
   candidate world, at one seed if budget is tight (one seed can discard a
   candidate; it cannot admit one, see the sampling plans below). A cheaper proxy policy is not
   a substitute unless that proxy is first shown to track the control on a panel
   of known difficulty.
2. Admit a world only after rejecting it on **three separate grounds**, each
   testable and each cheap. A world is *trivial* if a deterministic policy
   reading only public observations already succeeds, so the family's subject is
   not under test. It is *floored* if the control never succeeds. It is
   *saturated* if the control always succeeds. Publish the measured control rate
   and each baseline outcome per admitted world in the panel manifest.

   "The two policies disagree" is **not** a sufficient rule, and looks like one.
   It admits a saturated world whenever a baseline happens to lose there, which
   reintroduces the exact failure the two-sided screen was built to prevent.
   State the three conditions separately and test them separately.

3. Measure the control at **several seeds per world**, not one. One seed cannot
   distinguish a ceiling from a lucky draw, and both rejection grounds above are
   claims about a rate.

4. Report the **within-world variance** the screen observes, and treat zero as a
   finding rather than as precision. If every seed in a world returns the same
   outcome, seeds are repeats rather than replicates: the effective sample size
   is the number of worlds, and any interval computed across rows is narrower
   than the truth by construction. A panel-level rate near 50% is compatible with
   every individual world being deterministic, so it is not evidence of headroom
   on its own. Procurement's due-diligence sweep is the worked example: a 50%
   panel rate at budget 6 decomposes into three worlds at 3/3 and three at 0/3,
   with no fractional cell anywhere.

5. **Never catch an exception inside a screening loop.** A policy that cannot run
   and a policy that runs and loses must not produce the same value. Procurement's
   first two-sided screen called its baseline with a positional argument where the
   parameter is keyword-only, scored the resulting `TypeError` as a loss in every
   world, and reported a fabricated unanimous admission. A screen is evidence and
   is owed the scepticism owed to a run; a unanimous verdict is a reason to check
   the instrument.
6. **Screen on the quantity the family actually scores.** If the reported metric
   is continuous, admission is decided on dispersion in that metric, not on a
   binary derived from it. A threshold discards exactly the information the panel
   needs, and it does so silently: procurement's noisy panel was 100% feasible at
   every seed of every world with zero variance, and the same 23 rows carried
   regret from $8.04 to $64.82 varying within four of six worlds. Read one way it
   was uninformative, read the other it discriminated. For a continuous score the
   grounds become *degenerate*, meaning the control scores identically at every
   seed, which subsumes floored and saturated, and *trivial*, meaning a
   deterministic policy already matches the control's best.

7. A holdout must additionally preserve the difficulty of the panel it holds out
   from. Matching a panel's failure *themes* does not match its difficulty.

#### Sampling plans

The seeds per world and the two cut-offs are a sampling plan, and a plan errs
in known ways. State the plan and its miss rates in the panel manifest;
`aeread.design.screen_plan` computes both. For a control whose outcome on a
seed is success or failure:

| Seeds per world | Rejected when the control succeeds | Admits a world solved 95% of the time | Admits one solved 90% | Admits one solved 5% | Rejects one solved 50% |
|---:|---|---:|---:|---:|---:|
| 1 | never or always | 0% | 0% | 0% | 100% |
| 3 | never or always | 14% | 27% | 14% | 25% |
| 5 | never or always | 23% | 41% | 23% | 6% |
| 10 | never or always | 40% | 65% | 40% | 0% |
| 10 | 1 or fewer, or 9 or more | 9% | 26% | 9% | 2% |
| 20 | 2 or fewer, or 18 or more | 8% | 32% | 8% | 0% |

- **One seed cannot admit a world.** Never-or-always covers both outcomes of a
  single draw. One seed is enough to discard a candidate, not to admit one.
- **Under never-or-always, more seeds admit more near-saturated worlds.** One
  failure is enough to admit, so at 10 seeds a world the control solves nine
  times in ten is admitted 65% of the time. Saturated and floored are claims
  about a rate: reject on the rate (9 or more of 10), not on unanimity.
- **Choose the plan from the miss rate the campaign can carry.** At 3 seeds
  about one in seven of the candidates the control solves 95% of the time is
  admitted, and one informative world in four is refused. Add seeds, or
  tighten the cut-offs, until the declared rates give miss rates the design
  contract accepts.

For a continuous score the same statement is owed for the dispersion rule:
the seeds per world, the spread that counts as degenerate, and how often a
world with a declared true spread is refused. No shared calculation covers
that case yet.

If a family cannot produce worlds that pass all three grounds, the finding is
about the environment and not about the panel. Check whether the rule admitting a
world and the quantity making it hard are the same quantity; when they are, the
outcome is a step and no amount of re-tuning will find an interior. Procurement
defect 17 is that case written out.

Substituting a cheap proxy without validating it is its own trap. Procurement's
deterministic policy baselines solve **zero** worlds on the good development
panel, the known-bad holdout, and the confirmatory panel alike, so they cannot
distinguish a panel the model control saturates from one it fails; they beat the
model on the six `dev` worlds and lose everywhere else. A screen that returns the
same answer for a good and a bad panel is not a screen.

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
6. Name the counterparts a claim covers. When more than one counterpart type
   is run, report the gap per type and test whether it varies by type before
   pooling. A general advantage needs a positive gap against every declared
   type ([campaign SOP](experiment_campaign_sop.md), claim scope).
7. Run an A/A arm in the variance pilot: one profile in both arms, through
   execution, scoring, analysis and the claim rule. A claim rule that fires on
   it stops the campaign before the freeze.

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
   declared minimum meaningful effect, target power, and attrition rule. Use
   the shared calculation and seal its record with the freeze
   (`aeread.design.sizing_record`); a pack smaller than its own sizing record
   is not frozen.
3. Before confirmatory outcomes are inspected, hash the holdout tasks, seeds,
   profiles, prompts, harness, retry rules, execution order, analysis plan,
   missingness policy, stopping rule, implementation pins, and cost ceiling.
4. Average stochastic repeats within the declared independent cluster before
   treating clusters as independent evidence.
5. Preserve every planned cell as a verified receipt or typed missingness. Do
   not selectively rerun a losing condition or score operational failure as
   task-quality zero.
6. Report paired cluster-level intervals, predeclared slices, reliability,
   exclusions, and missingness alongside aggregates. Name the interval and the
   test, chosen by cluster count. Compare missingness between arms, and when
   cells are missing report the worst-case bounds beside the estimate
   ([campaign SOP](experiment_campaign_sop.md), reuse and reporting rules).
7. Prove every guarded metric is falsifiable. For each quantity a promotion rule
   guards, construct a synthetic arm that maximizes it through behavior the rule
   is meant to reject, and require the rule to reject that arm. A metric is a
   guardrail only when some behavior fails it. Terminal feasibility is the worked
   example: it counts an explicit deferral as a success, so a treatment that
   defers more can satisfy a feasibility guardrail while earning nothing, and the
   guarded quantity must instead be one that a deferral fails.
8. Publish canonical fact tables and a manifest whose rows trace to admitted
   profiles, plans, receipts, and evidence.

#### Reliability

Reliability is the share of a comparison that would recur: the expected
correlation between the model means of two independent runs of the same
design, each on its own draw of worlds and plays.

```text
reliability = var_model / (var_model + var_world_model / worlds + var_play / (worlds x plays))
```

- `var_model` is the variance between the models' true means: what the
  campaign is trying to see.
- `var_world_model` is how much a model's standing changes from world to
  world, and `var_play` is play-to-play noise inside a world. These two are
  the error. A counterpart or a seat that the design samples is error in the
  same way and enters with its own count; one that the design fixes as a
  control narrows the claim instead.
- A world's own level is not error. Every model meets the same worlds, so an
  easy world lifts all of them and cancels in the comparison.

Estimate the variances from the variance pilot
(`aeread.design.variance_components`, worlds by models by plays) and report
the reliability at the confirmatory size, with the number of worlds that
reaches the campaign's target (`aeread.design.worlds_for_reliability`). For a
single pair of models, also report the chance that two runs would put them in
the same order (`aeread.design.sign_agreement`). With two or three models the
model variance rests on two or three means, so the figure describes the
design and is not a test; report the sizing calculation beside it.

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
| Data-center development (six family ids) | [datacenter/qc.md](../families/datacenter/qc.md) | `failed`; task-distribution and construct gates `failed`, confirmatory `not_run` |

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
