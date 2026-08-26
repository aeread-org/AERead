# Shared Runner Post-Sync Rebaseline Implementation Plan

> **Author:** Codex, for Zeyu Sun  
> **Date:** 2026-08-25  
> **Status:** Task 0.1a is independently P0/P1/P2 clean at `9f7255e`. Latest PR #7 source
> `155d8fc` is integrated locally by true merge `b5239cd`, with compatibility and
> executable-guard follow-ups through `c7aca60`; none was pushed or merged to GitHub/main.
> Task 0.3 is complete. Task 1.1a1 is independently clean through `ca173f4`; Task 1.1a2
> has candidate fixes through `a7ddbb2`, with independent review pending. The executable
> scheduler, attempt executor, receipt/replay kernel, and benchmark adapters remain
> unimplemented.
> **Supersedes:** Tasks 6–11 of `2026-08-24-shared-runner-sdk-kernel.md`; Tasks 1–5 and their review history remain valid

## Objective

Finish a family-neutral, audit-grade shared runner without assuming that every external
benchmark has the same state/action schema, Python API, runtime, or measurement. Stable
kernel work continues while five semantic-verifier fixtures and selected real upstream
source audits expose contract gaps early. Executable upstream adapters remain after
provider-free kernel conformance and Exchange/Housing native parity.

```text
scientific claim       EstimandSpec + semantic VerifierSpec + ReferenceSpec
experiment design      SamplingPlan + EvaluationBlock + AnalysisPlan
economic execution     EnvironmentPlugin + runner-owned phase scheduler
agent execution        AgentAdapter + episode-scoped AgentSession + runtime
side effects           ActionAttempt | RaterAttempt | LifecycleOperation
                         -> ProviderCall* + ToolInvocation* as allowed
evidence               append-only events + artifacts + durable seal
measurement            recorded evaluator work -> pure scorer -> ScoreEnvelope
publication            EvaluationReceipt + projections + aggregate analysis
```

## Non-negotiable gates

- No family-specific branch or import in the kernel.
- Unsupported versions, source pins, capabilities, runtime, or observability fail before
  external side effects.
- One `PlanCell` is the only planned `Episode`/replicate slot. Suite replication design
  expands to unique `PlanCell` records; operational retries create `EpisodeAttempt`, never
  a second planned unit or independent statistical cluster.
- Planned judgment slots are statistical identities; `RaterAttempt` records are
  operational children and never add judgments or denominator counts.
- Every `PlanCell` closes exactly once in a content-addressed `AttemptChainClosure`, and
  run close binds the exact expected closure set before post-receipt analysis.
- Every AERead-initiated or adapter-declared observable atomic side effect has a durable
  start record and exactly one terminal `succeeded`, `failed`, or `outcome_unknown`
  record. An opaque upstream trial promises this only for its outer trial operation and
  explicitly declares its internal provider/tool operations unobserved.
- Valid zero or negative economics never become missing/corrupt evidence.
- Judge calls are recorded evaluator work; their deterministic `RaterAggregate` is sealed
  before the measurement-bound `VerifierPlugin` scores it.
- Transition/reconciliation policy and state materialization are resolved and hashed before
  execution; an unknown mutation never implies an authoritative state.
- Predeclared reference, sealed scorer-input, and reconciliation-staging artifacts have
  separate typed authority; no consumer enumerates the whole artifact store.
- Harbor is optional runtime/source interop, not the multi-agent scheduler or core
  dependency.
- Provider-free conformance and independent review precede live-provider runs.
- No push or PR merge is authorized by this plan.

## Stage 0 — close the current foundation

### Task 0.1: Harden and independently re-review Task 5

Modify only the evidence records/store/tests/report/ledger. Required adversarial cases:
seal publication failure, cached corruption, reopened sealed readers, artifact writes
after seal, append partial-write/fsync poisoning, valid-tail and final-marker deletion,
empty identity, forged projection order/finality, public plaintext leakage, directory
fsync boundaries, hostile `model_copy()`, dangling/final/ancestor symlink side effects,
identity-preserving empty projections, artifact snapshot races, and single-episode
artifact-generation ownership, including no-follow descendant access, retained-inode
namespace semantics, same-identity split-log claims, and pre-log claim recovery. The
portable local threat model does not promise lexical containment after a same-user/admin
renames an already-open managed directory; it promises that writes remain on the retained
inode and never follow the replacement symlink target. Event-log admission must also
reserve the ArtifactStore namespace using filesystem identity, not only case-sensitive
path strings: on a case-insensitive filesystem, aliases such as `ARTIFACTS/**` must be
rejected before generation, lease, log, state, seal, or CAS mutation. A robust follow-up
compares the candidate reserved-prefix inode `(st_dev, st_ino)` against the retained
artifact anchor without lowercasing paths on case-sensitive filesystems.

```bash
PYTHONPATH=src pytest --confcutdir=. tests/shared_runner/test_event_store.py -q
PYTHONPATH=src pytest --confcutdir=. -q
git diff --check
```

Task 0.1a is complete at `9f7255e`: independent specification and quality reviews are
P0/P1/P2 clean. APFS dynamically exercised filesystem-equivalent alias rejection; the
case-sensitive allowance is encoded for Linux CI but was not dynamically exercised on the
local APFS volume.

### Task 0.2: Integrate the latest approved PR #7 design

Complete locally. Latest PR #7 source `155d8fc` is integrated by true merge `b5239cd`, with
crosswalk/status/stability/ABI-guard follow-ups through `c7aca60`. Task 1.1a1 is
independently clean through `ca173f4`; Task 1.1a2 has candidate fixes through `a7ddbb2`,
with independent review pending. Older `275a285`/`388e52b` commits remain
historical milestones only. No implementer should repeat either merge, push it, or merge it
to GitHub/main under this plan.

### Task 0.3: Migrate the serialized planning identity to `PlanCell`

**Dependency:** independently dispatchable under the controller ledger ruling and its
controller-issued Task 0.3 brief. Its authorization does not depend on the round-5 plan
review gate for Task 1.1a and later tasks. The Task 0.3 brief is controller-owned; do not
edit it or use this plan-correction commit to widen its scope.

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py` for the canonical record, `PlanCellT` protocol type, and
  stable export.
- Modify `src/aeread/runner/planning.py` for construction, digest basis, validation, and
  `RunPlan.cells` typing.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/test_registry.py`,
  `tests/shared_runner/test_planning.py`, and
  `tests/shared_runner/test_planning_adversarial.py`.
- Modify the authoritative executable example in
  `docs/public_environment_and_external_adapter_spec.md` and its guard in
  `tests/test_shared_runner_design_contract.py`.

PR #7 freezes `PlanCell -> Episode -> EpisodeAttempt`. Rename the current public and
serialized `EpisodeCell` record to `PlanCell`, then update the resolver, hash basis,
exports, schemas, and fixtures. Freeze
`record_type: Literal["plan_cell"]`,
`spec_version: Literal["aeread.plan_cell/0.1"]`, and the enclosing
`RunPlan.spec_version: Literal["aeread.run_plan/0.2"]`. A compatibility alias may exist
only at the Python import surface; it must not introduce a second serialized identity or
hash basis. If retained, `EpisodeCell = PlanCell` is the only permitted compatibility
shape: instances created through either import serialize with `record_type="plan_cell"`
and the `PlanCell` schema/version. The retired name is forbidden in authoritative public
type signatures and serialized payloads.

**RED requirements:** `test_plan_cell_rejects_stale_episode_cell_payloads` rejects an
authoritative `record_type="episode_cell"`, every enclosing `RunPlan` version other than
`aeread.run_plan/0.2`, every `PlanCell` version other than `aeread.plan_cell/0.1`, and a
payload lacking either discriminator/version;
`test_plan_cell_has_one_serialized_identity_even_through_alias` proves the optional Python
alias emits only the `PlanCell` schema and hash basis;
`test_plan_cell_digest_covers_every_scientific_input` mutation-tests every scientific
field; and `test_public_environment_spec_uses_plan_cell_only` rejects active public
`EpisodeCell`/`EpisodeCellT` signatures. Historical or explicitly negative migration prose
may name the retired type. No automatic legacy migration is provided on this feature
branch.

**Output:** one `aeread.run_plan/0.2` `RunPlan` containing only
`aeread.plan_cell/0.1` canonical `PlanCell` records, one public Python export (plus the
optional import-only alias), and a design-contract guard that prevents the retired
serialized/public name from returning.

## Stage 1 — reconcile measurement before execution code

### Task 1.1a: Freeze the reusable family measurement leaf and reference-artifact boundary

**Dependency:** Task 0.3 is independently complete and the progress ledger records this
round-5 plan correction P0/P1/P2 clean. Task 0.3 may proceed under its separate controller
authorization while this gate remains closed.

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py` for strict records, Protocols, and stable exports.
- Modify `src/aeread/runner/registry.py`; create
  `src/aeread/runner/verifier_artifacts.py` for the read-only artifact port.
- Modify `docs/shared_runner_design.md`, `docs/verifier_taxonomy.md`,
  `docs/walkthroughs/shared_runner_architecture_roadmap.md`, and
  `docs/public_environment_and_external_adapter_spec.md` to freeze the same ownership and
  family leaf/reference-artifact semantics.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/test_registry.py`,
  `tests/shared_runner/fakes.py`, and `tests/test_shared_runner_design_contract.py`; create
  `tests/shared_runner/test_verifier_conformance.py` and
  `tests/shared_runner/test_verifier_artifacts.py`.

This slice owns only reusable family semantics. Define the strict replacement target
`MeasurementLeafSpec`: stable leaf ID/version, one
`EstimandSpec`, exactly one of the five semantic verifier/reference variants, a non-empty
unique canonical tuple `allowed_evaluation_classes` drawn from `deterministic`,
`stochastic_estimator`, and `judge_dependent`, a
pinned scorer implementation, and `composition_kind: Literal["leaf"]`. The family leaf
must not contain a panel, sample size, cluster mapping, pairing, planned repetitions,
judgment slots, concrete evaluator profile, estimator, interval, missingness rule, or
paper composition. Those are suite-owned in Task 1.1b.
Evaluation class remains orthogonal to semantic family: a non-`rater_judge` leaf may allow
`deterministic`, `stochastic_estimator`, or both, but never `judge_dependent`; a
`rater_judge` leaf permits only `judge_dependent`. The family declares this allowed set;
the suite selects exactly one member in Task 1.1b.
Do not wire the new record into or version-bump `FamilyManifest` in this slice; Task 1.1c
is the sole manifest migration owner, so 1.1a can be reviewed without a half-migrated
serialized family identity. Preserve the current legacy three-variant `MeasurementSpec`
and `FamilyManifest` unchanged while incrementally adding the leaf/reference records,
pin-aware registry, and `ReferenceArtifactView`; Task 1.1a does not modify
`planning.py`, `PlanCell`, or `RunPlan`. Task 1.1c alone removes that legacy authoring path
and performs the atomic family/suite/plan migration.

Preserve and make discriminated the reference semantics implementers otherwise would have
to invent:

- canonical reference: `canonical_point`, `canonical_set`,
  `terminal_state_equivalence`, or `distance_to_canonical_set`, with typed schema/scope,
  canonicalizer or equivalence/distance implementation, units, exact/absolute/relative
  tolerance where applicable, accepted target `ArtifactRef` values, and provenance;
- rule reference: `constraint_satisfaction`, `state_invariant`, `temporal_property`,
  `axiom_relation`, or `metamorphic_relation`, with typed input/checkpoint scope,
  predicate or relation implementation, parameter/reference artifacts, pass vector and
  residual semantics, and provenance;
- objective reference: retain source direction and source-to-canonical transformation,
  units, feasible policy class, information set, horizon, environment/opponent condition,
  stochastic expectation, validity domain, typed exact/bound/baseline/support/value-only
  claim, proof type, and exact scope matching for every reference;
- comparative reference: `baseline_delta`, `paired_comparison`, `head_to_head`,
  `human_reference`, or `field_rating`, with typed comparator/reference implementation or
  artifact, population/role/matching preconditions, output units/direction, validity
  domain, and provenance; suite pairing and concrete panel membership remain Task 1.1b;
- rater reference: rubric and protocol/prompt `ArtifactRef` values, typed answer/outcome/
  trajectory input scope, authorized projection plus pinned renderer, an
  `evaluator_agent | imported_human` source union, blind-order algorithm with declared
  seed/counterbalance inputs, calibration/reference artifacts, provenance requirements,
  result/tie schema, and required disagreement report. An accepted tie is a typed rater
  result, never corrupt/missing evidence. Concrete evaluator or imported-evidence
  assignment remains Task 1.1b.

Reference source is a second strict union—case payload path with schema, allowlisted
content-addressed artifacts, or a pinned pre-outcome deterministic computation—not a
`JSONObject` or free-form options field. Every identifier, version, field tuple, and
artifact reference is non-empty and unique where appropriate.

This slice owns the predeclared artifact side only. A read-only `ReferenceArtifactView` is
constructed solely from the exact `ArtifactRef` values declared by the leaf/reference
records; it verifies digest, media type, and byte length before returning bytes and cannot
list the artifact store. Task 1.1c binds those refs into the final resolved measurement,
constructs the post-seal scorer-input artifact boundary, and owns the final
`ResolvedMeasurementContract`/`BoundVerifier`/`VerifierPlugin.bind` signatures after Task
1.1b has defined evaluator and aggregate-input schemas. Task 1.1a must not import,
forward-reference, or locally duplicate those later-owned types. The reference view
exposes no write, provider, runtime, tool, network, reconciliation, or whole-store method.

**RED requirements:** schema tests construct all five reference families and every
reference-kind discriminator above, and reject incompatible or incomplete fields. Each
objective reference fails on any full-scope mismatch. Rater schemas reject ambiguous
source, unpinned renderer/order/calibration/provenance, or an untyped visibility payload,
but accept a valid tie. Registry tests reject an implementation/hash mismatch. Artifact
tests reject traversal, non-predeclared reference refs, unreachable store objects,
digest/media-type/length mismatch, mutation, store enumeration, and every write/network/
provider surface. A dependency test rejects any Task 1.1a protocol or export that mentions
`ResolvedEvaluationBinding`, `RaterAggregateInput`, `ResolvedMeasurementContract`, or
`BoundVerifier`; those final-boundary names first become legal in Tasks 1.1b/1.1c. Mode
tests reject an empty/duplicate/noncanonical allowed set, `judge_dependent` on a non-rater
leaf, and any non-judge class on a `rater_judge` leaf, while accepting one non-rater leaf
that allows both deterministic and stochastic evaluation.

**Output:** one family-owned `MeasurementLeafSpec` with complete five-family typed
reference semantics and one read-only predeclared-reference artifact boundary—no suite
statistical choices or selected evaluation class, final scorer protocol, post-seal
aggregate type, or whole-store authority.

### Task 1.1b: Freeze suite-owned statistical and evaluator bindings

**Dependency:** Task 1.1a is independently clean.

**Files:**

- Modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py`.
- Modify `tests/shared_runner/test_records.py`; create
  `tests/shared_runner/test_measurement_design.py`.
- Modify `tests/shared_runner/fakes.py` only for strict suite-design fixtures; do not add
  resolver or evaluator execution.

This slice owns the concrete design under which a leaf is evaluated. Add a strict
`SuiteMeasurementBinding`: referenced `measurement_leaf_id`, typed sampling population
and panel/selection rule, `ClusterSpec`, `PairingSpec`, `EpisodeReplicationDesign`,
one discriminated evaluation-mode binding with exactly one `selected_evaluation_class`,
method-specific estimator and interval/test, transformation,
missingness, one `EpisodeAttemptInclusionPolicy`, evaluator/imported-evidence assignment
where required, and an analysis block ID. It contains no family scorer implementation and cannot redefine an estimand,
verifier, reference, or allowed evaluation-class set. Task 1.1c exact-matches the selected
class to the referenced leaf's allowed tuple.
Do not wire this binding into or version-bump `SuiteManifest`, `PlanCell`, or `RunPlan` in
this slice; Task 1.1c owns that one atomic serialized migration.

The analysis block ID resolves to one strict suite-owned `AnalysisBlockSpec` discriminator:
leaf estimator, arm/pair comparison, metamorphic check over declared base/transformed leaf
blocks, or field rating over a declared population/matching graph. Every block names exact
input block IDs and output schema; comparison binds direction/pairing and optional test;
metamorphic and field-rating blocks pin a pure `ImplementationRef` plus typed algorithm
parameters and a closed `AnalysisMethodIOSpec`: inputs and outputs are only typed canonical
integer rationals or categorical values, never host-language floats. An implementation
that cannot satisfy this portable contract is excluded from V0 `AnalysisRecord` numeric
output rather than being silently rounded by plugin code. Unknown/open parameter maps
fail. These declarations contain no receipt data or execution port; Task 3.12 alone
evaluates them after receipt validation.

Statistical identity is planned rather than inferred from operational rows:

- `EpisodeReplicationDesign` is suite-authored intent: a non-empty `replication_id`, a
  positive repetition count, an ordered tuple of rollout seeds of exactly that length,
  and the resolved replicate/pair/cluster-mapping identity fields. Task 1.1c zips each
  repetition index to the seed at that same index and expands those pairs into
  unique `PlanCell` records; there is no `PlannedEpisodeReplicate` record or second episode
  identity. `EpisodeAttempt` is an operational child of a `PlanCell`; retries never add a
  planned episode, pair, group, or cluster count.
- `PlannedJudgmentSlot` is one intended rating for a leaf/episode/presentation position.
  `RaterAttempt` is an operational child serving that slot. Replacement attempts retain
  the same judgment-slot/cluster identity, and at most one accepted terminal judgment per
  slot contributes to aggregation.
- judgment-slot count and evaluator stochasticity exist only in a
  `JudgeDependentEvaluationBinding` carrying the typed rater protocol. The non-judge
  `StochasticEstimatorEvaluationBinding.stochastic_sources` is a non-empty set drawn only
  from `environment | counterpart | candidate`; it has neither `judge` nor `combined`.

This slice also owns the strict `ResolvedEvaluationBinding` union and the typed
`RaterAggregateInput` record schema needed by the final verifier boundary. The aggregate
input carries the sealed aggregate record/artifact ref, its canonical hash, measurement/
assignment/planned-slot bindings, validity, and disagreement/tie disposition; it is never
an open payload, executor, or artifact resolver. Task 1.1c alone composes these schemas
with the family leaf into the final resolved contract and Protocol signatures.

Resolve an outcome-blind `EpisodeAttemptInclusionPolicy` before execution. It pins a
policy ID/version, `max_attempts_per_cell: PositiveInt`, the finite retry-failure classes
authorized to create a successor,
canonical attempt ordering `(attempt_ordinal, episode_attempt_id)`, and the V0 selection
rule `terminal_chain_tail_after_authorized_retries`. Attempts must form one gap-free
predecessor chain within the bound for the same `PlanCell`; a successor is eligible only
when its predecessor's typed terminal failure class is allowlisted, and no successor may
follow a non-retry terminal. The sole selected attempt is the integrity-complete chain tail
(including an exhausted/abandoned typed failure), never an earlier attempt whose outcome
looks better. `AttemptSelectionProof` records the ordered
attempt/event hashes, predecessor links and failure classes, eligibility decisions, and
the sole selected attempt ID or `None`. Policy resolution and proof verification may use
only identities, ordering, integrity/completeness, and typed retry-failure classes—never
measurement validity, score, utility, success-predicate value, action quality, or another
outcome value. Each receipt immutably binds the policy hash and only its local
`AttemptPolicyEvidence`—ordinal, predecessor attempt ID and terminal event ID/hash when
present, plus this attempt's terminal event ID/hash and typed retry class—so a later retry
never requires rewriting an
earlier receipt. After retry control ends, Task 3.11 binds those immutable local records
and any typed prepublication failures/exclusion into the one complete
`AttemptChainClosure`; Task 3.12 exact-matches that closure to the run-close manifest and
produces the canonical `AttemptSelectionProof` by recomputing the full chain before
accepting a selected attempt.

Every suite-authored V0 numeric parameter used by analysis is a strict reduced
`CanonicalRational(numerator: int, denominator: PositiveInt)` with positive denominator;
JSON floats or decimal strings are rejected for these fields. Replace the bare estimator
target enum with a discriminator union:

- `MeanEstimatorSpec` binds the metric and `weighting: Literal["uniform"]`;
- `DifferenceEstimatorSpec` binds subject/comparator arm IDs, comparison direction, and
  exactly one design: paired with its exact `PairingSpec`/pair keys, or unpaired with each
  arm's declared population and `weighting: Literal["uniform"]`;
- `ProbabilityEstimatorSpec` binds a typed, versioned Boolean success predicate and
  `denominator: Literal["planned", "valid"]`. `planned` is legal only with
  `invalidate_required` and produces a semantic probability only when every planned cell
  has one selected valid Boolean predicate value; any invalid/missing/failed/unknown cell
  invalidates the numeric result rather than becoming `false`. `valid` is legal only with
  a predeclared partial-missingness estimator; only selected valid Boolean values enter its
  denominator, and the result records planned, valid, invalid/missing, and success counts
  plus the exact invalid/missing cell identities. A probability whose predicate is
  operational completion or measurement availability must be a separately declared
  operational-availability `EstimandSpec`, never a semantic-success probability shortcut;
- `QuantileEstimatorSpec` binds metric, rational `q` strictly in `(0, 1)`, and the V0 R-7
  linear interpolation rule;
- `PassAllKEstimatorSpec` binds a positive `k`, success predicate, planned-cell group
  keys consumed as `PlanCell` keys after Task 1.1c expansion, and means exactly `1` iff all
  and exactly the `k` unique cells in each complete group succeed. Missing or extra cells
  follow the declared missingness rule and cannot silently change `k`; attempts never
  enter the denominator.

Non-uniform estimator weights are deferred from V0 and fail schema resolution. V0
interval is a method-specific union only: `NoIntervalSpec(method="none")` has no
confidence or resampling fields; `ClusterBootstrapIntervalSpec` requires confidence,
as a rational strictly in `(0, 1)`, draw count, seed, the percentile/R-7 method version,
and the resolved cluster-mapping/identity fields that define its resampling unit. Its
`resampling_block_mapping` equals that cluster mapping unless the suite declares a strict
`LargerAtomicResamplingBlockSpec` whose partition coarsens (never splits) clusters. Every
indivisible paired-comparison pair and every complete pass-all-k group must be wholly
nested in one effective resampling block; a cross-cluster pair/group is legal only when
that larger predeclared block contains all of it, and bootstrap samples those whole blocks.
`PairedRandomizationTestSpec` is a
separate hypothesis-test declaration with paired keys,
`assignment_mechanism: Literal["independent_uniform_within_pair"]`, typed assignment and
exchangeability provenance refs, two-sided absolute-mean-difference statistic, exhaustive
threshold, Monte Carlo draw count, and seed. Observational or otherwise non-uniform pairs
may publish the paired effect only and must reject a p-value/test declaration. Its interval
must be `NoIntervalSpec` because V0 publishes no randomization confidence interval.
Cluster-robust and hierarchical intervals are deferred. A validator never requires fake
resampling fields for `none` or
the paired test.

Missingness is fail-closed and typed: `invalidate_required` forbids numeric output when a
required planned unit is missing/failed/unknown; a predeclared partial estimator names its
positive minimum valid planned units and denominator treatment. A probability result
always reports `planned_count`, `valid_boolean_count`, `invalid_or_missing_count`, and
integer `success_count`. Under `denominator="planned"`, the counts must prove
`planned_count == valid_boolean_count` before division; otherwise the entire result is
`invalid_measurement` with no numerator, denominator, or numeric value. Under
`denominator="valid"`, only selected cells with a valid Boolean predicate enter the
denominator and the partial rule must authorize that treatment. Neither policy may
silently drop rows, coerce invalidity to Boolean failure, or impute economic zero. A rater
binding additionally freezes aggregation, valid tie treatment, minimum valid judgment
slots, disagreement output, and concrete assignment.
`EvaluatorAgentAssignment` pins one evaluator profile per judgment slot and its authorized
projection; `ImportedHumanAssignment` pins the collection/provenance artifact and maps
records to planned slots. Neither becomes an environment seat.

**RED requirements:** tests reject `PlannedEpisodeReplicate` and reject
`EpisodeAttempt`/`RaterAttempt` as replicate or judgment identity fields, reject seed/count
mismatches, reject a Cartesian repetition/seed expansion, reject replacement as a new
count, and reject more than one accepted judgment per planned slot. Each estimator variant
fails when its method-specific parameter is
absent or inconsistent; pass-all-k cases cover complete success, one failure, missing,
extra, and duplicate cell keys. Interval tests cover the two exact V0 variants; paired
randomization accepts only literal independent uniform within-pair assignment plus both
provenance refs and a separate test plus `none`; observational/non-uniform pairs reject
p-values, and cluster-robust/hierarchical or fake resampling fields fail. Numeric schema
tests reject non-reduced/zero-denominator rationals, JSON-float numeric parameters, and
every non-uniform estimator weight. Probability tests prove one invalid planned cell makes
`denominator="planned"` reject all numeric numerator/denominator/output, while the
predeclared `valid` design returns exact planned/valid/invalid/success counts and cell IDs;
the same fixture cannot relabel semantic failure as operational availability. Bootstrap
schema tests reject any pair or pass-all-k group split across effective resampling blocks,
accept only an explicit coarsening block that wholly contains it, and reject a block that
splits any resolved cluster. Analysis-method tests reject host-float IO and exclude an
incompatible custom method from V0 portable numeric output.
Judge variation without a rater protocol, ambiguous `combined`, unauthorized visibility,
incomplete evaluator/imported-human assignment, implicit drop, and zero imputation all
fail before evaluator/provider/runtime work. Inclusion-policy tests reject outcome fields,
unauthorized retry classes, attempt-bound overflow, broken/gapped predecessor chains, a
successor after a non-retry terminal, noncanonical ordering, two selected attempts, or a
selection proof that Task 3.12 cannot recompute byte-identically.

Evaluation-class schema tests require exactly one selected discriminator consistent with
its binding variant and reject suite redefinition of the family-owned allowed tuple; the
cross-record allowance/hash proof remains in Task 1.1c with the resolver.

**Output:** one suite-owned, strictly typed statistical/evaluation binding whose
replication design expands only to `PlanCell`, whose planned judgment slots are distinct
from operational attempts, whose attempt inclusion is plan-bound and outcome-blind, and
whose V0 interval/test declarations are unambiguous.

### Task 1.1c: Resolve one measurement design, minimal composition, and schema migrations

**Dependency:** Tasks 1.1a and 1.1b are independently clean.

**Files:**

- Modify `src/aeread/runner/planning.py` and `src/aeread/runner/registry.py`.
- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py` for the resolved records, final bound-verifier Protocols,
  composition declarations, and versioned manifest/plan fields; complete
  `src/aeread/runner/verifier_artifacts.py` for the post-seal scorer-input set.
- Modify `docs/shared_runner_design.md`, `docs/verifier_taxonomy.md`, and
  `docs/walkthroughs/shared_runner_architecture_roadmap.md`; guard the ownership,
  identity, composition, and hash rules in `tests/test_shared_runner_design_contract.py`.
- Modify `tests/shared_runner/test_planning.py` and
  `tests/shared_runner/test_planning_adversarial.py`; create
  `tests/shared_runner/test_measurement_resolution.py`.

For every evaluation block, resolve exactly one family `MeasurementLeafSpec` plus exactly
one compatible `SuiteMeasurementBinding` into one immutable
`ResolvedMeasurementDesign` stored directly in `PlanCell`. It contains the leaf ID/version/
hash, allowed evaluation-class tuple and selected evaluation class, exact reference and predeclared-reference
artifact set, sampling/panel, cluster, pair, replication design and judgment-slot
identities, estimator, interval/test, transformation, missingness, evaluator assignment,
scorer visibility, the resolved `EpisodeAttemptInclusionPolicy`, analysis-block ID, and two
composition-excluding hashes:
`suite_measurement_binding_sha256` over only the canonical resolved
`SuiteMeasurementBinding`, and `analysis_block_sha256` over only its resolved analysis
block. It must not contain or hash the full `SuiteManifest` or any composition declaration.
Its canonical `measurement_sha256` covers every listed field, and the `BoundVerifier`
carries that exact digest. Full `suite_manifest_sha256` and `composition_sha256` are
separate fields on `PlanCell`, `RunPlan`, and the eventual receipt.

The resolver first validates `repetition_count == len(rollout_seeds)`, then expands each
`EpisodeReplicationDesign` into exactly one `PlanCell` per declared case × evaluation
block × subject/seat assignment × `enumerate(rollout_seeds)`. Each repetition index is
zipped to the seed at that same index; repetition indices and seeds are never separate
Cartesian axes. It rejects duplicate keys and proves exact set equality between expected
and actual `PlanCell` keys—no missing or extra cell and no `EpisodeAttempt`/retry key may
satisfy coverage. In the atomic migration, `EvaluationBlock` references one
`episode_replication_design_id`; legacy inline repetition/rollout-seed fields are rejected
so the same intent cannot be authored twice. `PlannedJudgmentSlot` remains the only inner
rating identity.

`SuiteManifest/0.2` owns unique `episode_replication_designs` and `analysis_blocks`
collections. Every evaluation/binding reference resolves exactly once; unreferenced,
missing, duplicate, or cross-suite IDs fail rather than creating implicit defaults.

This slice owns the final pure scoring contract after the earlier schema slices exist:

```python
class ResolvedMeasurementContract(Protocol):
    measurement_sha256: SHA256
    suite_measurement_binding_sha256: SHA256
    analysis_block_sha256: SHA256
    leaf: MeasurementLeafSpec
    evaluation: ResolvedEvaluationBinding

class BoundVerifier(Protocol):
    measurement_sha256: SHA256

    def score(
        self,
        case: FamilyCase,
        outcome: FamilyOutcome,
        evidence: SealedEvidenceView,
        artifacts: ScorerInputArtifactView,
        rater_aggregate: RaterAggregateInput | None,
    ) -> ScoreEnvelope: ...

class VerifierPlugin(Protocol):
    implementation: ImplementationRef

    def bind(
        self,
        measurement: ResolvedMeasurementContract,
        references: ReferenceArtifactView,
    ) -> BoundVerifier: ...
```

`ResolvedMeasurementDesign` satisfies `ResolvedMeasurementContract`; bind rejects every
leaf/evaluation/hash/implementation mismatch. After terminal evidence and any typed
`RaterAggregateInput` are complete, the runner builds `ScorerInputArtifactSet` as the
sorted union of exact predeclared reference refs and typed `ArtifactRef` fields recursively
reachable through only the final visible terminal/evidence/aggregate records authorized by
`ScorerVisibilitySpec`. It follows only registered typed artifact-manifest media types,
rejects cycles and string-shaped/untyped refs, validates digest/media type/length, never
calls `ArtifactStore.list_refs()`, and binds the sorted refs plus
`artifact_set_sha256` into score, replay, and receipt. Bind and score are provider-free and
side-effect-free. Judge-dependent scoring requires exactly one sealed, valid,
measurement-bound aggregate; it never falls back to leaf-only scoring.

Validation is exact and rejects rather than overwrites: missing or duplicate leaf/binding,
estimand mismatch, selected evaluation class outside the leaf allowance, family/suite reference drift,
incompatible paired estimator, unresolved artifact/profile/implementation, or more than
one cluster mapping for a leaf/block. Changing a paper panel, repetition count, pairing,
interval/test, missingness rule, or evaluator assignment must leave the family leaf
bytes/hash unchanged while changing the suite manifest, resolved measurement, `PlanCell`,
and `RunPlan` bytes/hashes.

Composition is declaration-only in V0. `SuiteManifest.compositions` may declare
`vector`, `hybrid_gate`, `weighted`, or `judge_augmented` over a non-empty unique tuple of
existing leaf `block_id` values. A component may not reference another composition, so
nesting and cycle traversal do not exist. Validate and hash declarations only; aggregate
execution and scalar publication belong only to post-receipt Task 3.12. Weighted
declarations still bind exact rational weights, pinned transforms, units, decision problem,
and sensitivity declaration, but V0 analysis publishes only the ordered component vector,
the declaration hash, and `weighted_scalar_status="deferred"`; it does not compute or
publish one official weighted scalar. A future version may enable scalar publication only
after a finite typed sensitivity grid and its complete execution/result semantics are
plan-bound and executed. Vector binds output order; hybrid gate binds its typed gate,
gated blocks, and fallback; V0 judge-augmented binds ordered component IDs, the one judge
block, typed dependency edges, required component statuses, and tie/missing disposition,
but has no numeric combiner, transforms, or scalar output. Any cross-component scalar must
use `weighted` and remains deferred in V0. Every executable gate predicate or weighted
transform is pinned; otherwise keep a vector.
Composition never changes leaf validity/inclusion, never claims
shared evidence without a separately resolved paired design, and never becomes an
execution/admission gate. `composition_sha256` is a separate SuiteManifest-owned digest
carried by `PlanCell` and `RunPlan`: changing composition changes only composition,
`SuiteManifest`, `PlanCell`, and `RunPlan` bytes/hashes, never
`suite_measurement_binding_sha256`, `analysis_block_sha256`,
`ResolvedMeasurementDesign.measurement_sha256`, or the bound leaf digest.

Make the breaking migration explicit with no automatic legacy parser:
`FamilyManifest` becomes `aeread.family/0.2`, `SuiteManifest` becomes
`aeread.suite/0.2`, `PlanCell` becomes `aeread.plan_cell/0.2`, and `RunPlan` becomes
`aeread.run_plan/0.3`. Legacy family-owned evaluation/composition payloads and the
Task 0.3 plan versions fail closed.

**RED requirements:** construct every allowed leaf/mode binding and mutation-test every
resolved field. `test_suite_design_change_does_not_change_family_identity` changes panel
and interval independently, proves identical family bytes/hash, and proves changed suite,
measurement, cell, and run-plan hashes. Resolution rejects every duplicate/conflict named
above; inclusion-policy mutation changes measurement/cell/run hashes but never the family
leaf hash. `test_plan_cell_expansion_is_an_exact_bijection` compares the complete expected and
actual key sets, rejects missing/extra/duplicate keys, and proves retries cannot satisfy a
missing cell. Its required `R=2` fixture with seeds `(s0, s1)` produces exactly the two
unique coordinates `(0, s0)` and `(1, s1)`, never four Cartesian cells; adding an
`EpisodeAttempt` changes neither expected nor actual coverage. Binding/hash tests mutate
the suite measurement binding and analysis block independently and require changed
`measurement_sha256`, while composition and unrelated full-suite-envelope changes preserve
`suite_measurement_binding_sha256`, `analysis_block_sha256`, and `measurement_sha256` but
change the appropriate full suite/composition/cell/run hashes. Composition accepts direct
leaf block IDs, rejects
missing/duplicate/non-leaf components and undeclared scalar semantics, has no executable
aggregation port in planning/resolution, and
`test_composition_change_preserves_measurement_digest` proves only the
composition/suite/cell/run hashes change. Post-seal artifact tests reject untyped or
unreachable refs, cycles, store enumeration, and aggregate-binding drift; bound-verifier
tests prove byte-identical provider-free scoring and fail closed for a required absent,
invalid, wrong-binding, or unsealed aggregate. Weighted composition RED requires the
ordered vector and declaration hash with `weighted_scalar_status="deferred"` and rejects
any V0 official weighted scalar. Judge-augmented RED freezes only component/dependency/
status structure and rejects a combiner, transform, weight, or scalar result. Evaluation-
class RED resolves one dual-allowed non-rater leaf under deterministic and stochastic
suite bindings, proving identical leaf bytes/hash and distinct suite, resolved-measurement,
cell, and run hashes; it rejects zero/multiple selections and every selection outside the
leaf allowance.
Migration tests assert all four exact versions and reject prior payloads. The unauthorized
rater preflight remains zero-side-effect evidence only; Tasks 3.5–3.7 own evaluator work.

**Output:** one hashed composition-free `ResolvedMeasurementDesign` per sole episode
identity `PlanCell`, exact expansion/coverage and family/suite ownership, separately
hashed declaration-only leaf composition, and explicit versioned migrations.

### Task 1.2: Add five provider-free measurement fixtures

**Dependency:** Task 1.1c is independently clean.

**Files:** create one valid and one neighboring invalid fixture for each family under
`tests/shared_runner/fixtures/verifier_families/`, and create
`tests/shared_runner/test_verifier_family_fixtures.py`.

Freeze five AERead-owned pressure cases, not copied benchmark tasks: a structured
canonical answer with typed absolute/relative tolerance; a two-seat trajectory whose
temporal/rule property detects ordering and actor mistakes; a tiny procurement instance
whose objective/reference is verified by pinned brute-force enumeration; a comparative
baseline evaluated on the same case and seed with exact pair identity; and canned blinded
rater judgments covering evaluator-agent/imported-human provenance, a valid tie,
disagreement, and missingness with zero provider calls. Each fixture must canonicalize,
resolve to a plan, bind its predeclared reference view, derive any scorer-input view only
from typed sealed refs, and fail its neighboring invalid input before filesystem mutation,
runtime start, evaluator work, or provider call.

**RED requirements:** each valid fixture selects its intended reference discriminator,
evaluation binding, cluster/pair/planned-slot identities, and hash; its invalid neighbor
fails only the targeted contract. Dependency fakes raise if any runtime/provider/network/
write port is touched. The rater case aggregates only canned accepted planned judgment
slots and proves a replacement attempt cannot add a judgment.

**Output:** five provider-free conformance fixtures proving contract expressibility—not
upstream parity, interval adequacy, or benchmark quality.

## Stage 2 — correct agent lifecycle and side-effect contracts

### Task 2.1a: Add precise action/call/tool evidence vocabulary

**Dependency:** Task 1.1c is independently clean.

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py`.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/test_registry.py`, and
  `tests/shared_runner/fakes.py`; create
  `tests/shared_runner/test_action_attempt_contracts.py`.
- Modify the authoritative `AttemptObserver` and executable action examples in
  `docs/public_environment_and_external_adapter_spec.md`, `docs/shared_runner_design.md`,
  and `docs/walkthroughs/shared_runner_architecture_roadmap.md`; guard them in
  `tests/test_shared_runner_design_contract.py`.

This task owns the public records, discriminated unions, Protocols, stable exports, schema
versions, and conformance fakes for action, provider, tool, and rater attempts only. It
does not version-bump `PlanCell`/`RunPlan` or own transition/recovery records. Task 2.1b
owns those; Tasks 3.1 and 3.3 own scheduler/attempt execution. The only action/mutation
path is:

```text
LogicalAction
  -> ActionAttempt
       -> ProviderCall 0..n
       -> ToolInvocation 0..n
       -> CanonicalResponse | typed failure

CanonicalResponse
  -> EnvironmentPlugin.parse_action()
       -> ParseResult containing one atomic ActionBundle
ActionBundle
  -> EnvironmentPlugin.legal()
       -> LegalityResult
legal ActionBundle
  -> TransitionStart
       -> EnvironmentPlugin.step()

EvaluationWork
  -> RaterAttempt 1..n
       -> ProviderCall 0..n
       -> ToolInvocation 0..n
       -> RaterJudgment | typed failure
```

The existing `CallAttemptStart` and `CallAttemptToken` remain stable compatibility exports.
They may be deprecated and excluded from the new kernel path, but their v1 fields,
validation, and import names cannot be removed or repurposed. Add distinct
`ProviderCallStart` and `ProviderCallToken` records alongside them, plus
`ActionAttemptStart` plus
`ActionAttemptSucceeded | ActionAttemptFailed | ActionAttemptOutcomeUnknown`, and the
analogous strict `succeeded | failed | outcome_unknown` terminal union for each provider
call, executed tool, and rater attempt. Add
`ToolInvocationStart` and its strict terminal union, with stable parent
IDs, canonical hashes, tool/version pins, idempotency/reconciliation capability,
typed `family_read_only | harness_internal | transactional_preview` execution scope, and
result/state-diff artifact refs.

The existing `AttemptObserver.call_started`, `call_succeeded`, and `call_failed` signatures
remain stable. The existing `AgentAdapter.act(..., attempts: AttemptObserver)` signature
remains stable. Task 2.1a implements a runner-owned compatibility observer that translates
those callbacks into the additive `ProviderCall*` evidence records and binds the current
action-attempt parent from runner context. It does not replace the stable methods. Any
future incompatible observer contract must be a separately named additive Protocol or v2.
Every child side effect uses a discriminated parent ref:
`action_attempt | rater_attempt | lifecycle_operation`. `EvaluationWork` is the frozen
plan/input unit; `RaterAttempt` is the only operational retry identity for evaluator
execution, so no redundant `EvaluatorAttempt` record is exported. It always serves one
preplanned judgment slot and never creates a statistical judgment, replicate, or cluster.
Retry creates a new `ActionAttempt`; provider transport retry creates another
`ProviderCall`. An actually executed, allowed `ToolInvocation` with unknown outcome is not
silently retried; requested family mutations are not executed as tool invocations at all.

An agent/model request to invoke a mutating family tool remains untrusted normalized
content inside `CanonicalResponse`. `AgentAdapter`, `AttemptObserver`, `ActionAttempt`, and
`ToolMediator` may neither construct an `ActionEnvelope`/`ActionBundle` from that request
nor execute the family mutation. Only `EnvironmentPlugin.parse_action()` can turn the
response into a successful `ParseResult` containing one atomic `ActionBundle`; only
`EnvironmentPlugin.legal()` can authorize it; only the scheduler may then open a
`TransitionStart` and call `EnvironmentPlugin.step()`. `ToolInvocation` rows cover only
operations actually executed inside an attempt: read-only operations, harness-internal
operations, or deterministic transactional previews. A requested family mutation never
produces `ToolInvocationSucceeded`, and a failed `step()` can never coexist with a
succeeded tool row claiming that economic mutation committed.

**RED requirements:** the new persisted evidence path must not serialize new rows with the
legacy `CallAttempt*` identities; compatibility tests require their imports, schemas,
`AttemptObserver` methods, and `AgentAdapter.act` signature to remain unchanged in v1.
Record
tests reject mismatched parent IDs, missing pins/hashes, and second terminal construction
in a conformance fake. The public design-contract RED asserts the exact response -> parse
-> legality -> transition path and rejects language allowing adapters/attempts/tools to
create an `ActionEnvelope` or execute a requested family mutation. Task 3.3 owns runtime
no-envelope/no-tool-success at the executor boundary. Task 3.1 owns runtime parsing,
legality, slot/bundle validation, and no-step-before-parse-and-legality RED.

**Output:** one versioned public evidence vocabulary rooted in `ActionAttempt`,
`ProviderCall`, actual `ToolInvocation`, and `RaterAttempt`, with the existing
`CallAttempt*` records retained only as compatibility exports and exactly one declared
parse/legality/mutation path.

### Task 2.1b: Freeze transition, reconciliation, and recovery contracts

**Dependency:** Tasks 1.1c and 2.1a are independently clean.

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py` for transition/reconciliation/recovery records only.
- Modify `src/aeread/runner/planning.py` for plan-time transition-policy resolution and
  hashing only; recovery execution remains Task 3.9.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/fakes.py`, and
  `tests/shared_runner/test_planning.py`; create
  `tests/shared_runner/test_transition_contracts.py`.
- Modify the environment materialization/recovery boundaries in
  `docs/public_environment_and_external_adapter_spec.md`, `docs/shared_runner_design.md`,
  and `docs/walkthroughs/shared_runner_architecture_roadmap.md`; guard them in
  `tests/test_shared_runner_design_contract.py`.

This slice owns the plan-bound transition policy, event records, staging contract,
deterministic materialization, and receipt-facing `RecoveryReport`. It does not execute
recovery; Task 3.9 does that against these exact contracts.

Before any execution, the resolver must select one strict `TransitionPolicySpec` for every
`PlanCell`, store it in that cell, and cover it in the `PlanCell`/`RunPlan` canonical hash.
The policy binds a stable policy ID/version, the pinned `TransitionReconciler`
`ImplementationRef`, idempotency semantics (`runner_copy_on_write` or
`external_idempotency_key`), reconciliation-query semantics
(`single_query` in V0), a positive maximum transition-attempt count, and exactly one
state-materialization strategy:
`CanonicalStateArtifactStrategy` with its state schema/version or
`TransitionResultArtifactStrategy` with its result schema/version. Admission exact-matches
the selected strategy and single-query/idempotency semantics to environment capabilities.
Unsupported external/database mutation fails preflight; a native environment uses a
pinned runner-owned reconciler rather than an implicit recovery path.

```python
class CanonicalStateArtifactStrategy(StrictModel):
    strategy: Literal["canonical_state_artifact"]
    state_schema_ref: str

class TransitionResultArtifactStrategy(StrictModel):
    strategy: Literal["transition_result_artifact"]
    result_schema_ref: str

StateMaterializationStrategy = Annotated[
    CanonicalStateArtifactStrategy | TransitionResultArtifactStrategy,
    Field(discriminator="strategy"),
]

class TransitionPolicySpec(StrictModel):
    policy_id: str
    policy_version: str
    reconciler: ImplementationRef
    idempotency_semantics: Literal[
        "runner_copy_on_write", "external_idempotency_key"
    ]
    query_semantics: Literal["single_query"]
    max_transition_attempts: PositiveInt
    state_materialization: StateMaterializationStrategy
```

This is a breaking plan migration in Task 2.1b: after Task 1.1c, `PlanCell` becomes
`aeread.plan_cell/0.3` and `RunPlan` becomes `aeread.run_plan/0.4`; no prior payload is
silently upgraded. The future `EvaluationReceipt` must bind the complete transition
policy and its canonical hash, not merely the reconciler name.

Add a first-class environment-transition evidence contract. `TransitionStart` durably
binds transition/phase IDs, ordered bundle hashes, prior state version/hash, idempotency
key, and the exact resolved transition-policy hash before `EnvironmentPlugin.step()`. The
strict terminal union is:

- `TransitionSucceeded`: next state version/hash and result/state-diff artifact refs;
- `TransitionFailed`: typed failure plus evidence that no commit occurred and the prior
  state remains authoritative;
- `TransitionOutcomeUnknown`: the adapter cannot prove whether mutation committed.

An optional checkpoint is progress evidence, never terminal. Unknown mutation is never
retried, resumed, or materialized until reconciled under the already-resolved policy.

Add an append-only reconciliation contract without changing the original transition
terminal:

```python
class TransitionReconciliationStart(StrictModel):
    reconciliation_attempt_id: str
    transition_id: str
    outcome_unknown_event_id: str
    transition_idempotency_key: str
    transition_policy_sha256: SHA256
    reconciler: ImplementationRef

class TransitionReconciliationRequest(StrictModel):
    reconciliation_attempt_id: str
    transition_id: str
    transition_idempotency_key: str
    transition_policy_sha256: SHA256
    transition_start_event_id: str
    transition_start_event_sha256: SHA256
    outcome_unknown_event_id: str
    outcome_unknown_event_sha256: SHA256
    prior_state_version: str
    prior_state_sha256: SHA256

StagedArtifactRole = Literal["proof", "canonical_state", "transition_result"]

class StagedArtifactRef(StrictModel):
    evidence_store_id: str
    transition_id: str
    reconciliation_attempt_id: str
    staging_key: str
    role: StagedArtifactRole
    sha256: SHA256
    media_type: str
    byte_length: NonNegativeInt

class TransitionReconciliationEventView(Protocol):
    transition_policy: TransitionPolicySpec
    transition_policy_sha256: SHA256
    transition_start_event_id: str
    transition_start_event_sha256: SHA256
    outcome_unknown_event_id: str
    outcome_unknown_event_sha256: SHA256

    def resolve_event_artifact(self, ref: ArtifactRef) -> bytes: ...

class ReconciliationArtifactStaging(Protocol):
    evidence_store_id: str
    transition_id: str
    reconciliation_attempt_id: str

    async def stage(
        self, *, role: StagedArtifactRole, canonical_bytes: bytes, media_type: str
    ) -> StagedArtifactRef: ...

class ReconciliationStagingJournal(Protocol):
    async def complete(self, entry: "ReconciliationStagingJournalEntry") -> None: ...
    async def load_completed(self) -> "ReconciliationStagingJournalEntry | None": ...

class StagedCanonicalStateMaterialization(StrictModel):
    materialization_kind: Literal["canonical_state_artifact"]
    artifact: StagedArtifactRef
    state_schema_ref: str

class StagedTransitionResultMaterialization(StrictModel):
    materialization_kind: Literal["transition_result_artifact"]
    artifact: StagedArtifactRef
    result_schema_ref: str

class ReconciliationCommittedFinding(StrictModel):
    status: Literal["committed"]
    proof: StagedArtifactRef
    state_materialization: Annotated[
        StagedCanonicalStateMaterialization | StagedTransitionResultMaterialization,
        Field(discriminator="materialization_kind"),
    ]
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

class ReconciliationNotCommittedFinding(StrictModel):
    status: Literal["not_committed"]
    proof: StagedArtifactRef
    authoritative_prior_state_version: str
    authoritative_prior_state_sha256: SHA256

class ReconciliationStillUnknownFinding(StrictModel):
    status: Literal["still_unknown"]
    proof: StagedArtifactRef | None
    reason_code: Literal["reconciler_failed", "proof_inconclusive"]

ReconciliationFinding = Annotated[
    ReconciliationCommittedFinding
    | ReconciliationNotCommittedFinding
    | ReconciliationStillUnknownFinding,
    Field(discriminator="status"),
]

class ReconciliationStagingJournalEntry(StrictModel):
    evidence_store_id: str
    transition_id: str
    reconciliation_attempt_id: str
    finding: ReconciliationFinding
    finding_sha256: SHA256

class CanonicalStateMaterialization(StrictModel):
    materialization_kind: Literal["canonical_state_artifact"]
    artifact_ref: ArtifactRef
    state_schema_ref: str

class TransitionResultMaterialization(StrictModel):
    materialization_kind: Literal["transition_result_artifact"]
    artifact_ref: ArtifactRef
    result_schema_ref: str

CommittedStateMaterialization = Annotated[
    CanonicalStateMaterialization | TransitionResultMaterialization,
    Field(discriminator="materialization_kind"),
]

class ReconciliationArtifactView(Protocol):
    reconciliation_terminal_event_id: str
    reconciliation_terminal_event_sha256: SHA256

    def resolve_terminal_artifact(
        self, ref: ArtifactRef, *, role: StagedArtifactRole
    ) -> bytes: ...

class TransitionReconciliationCommitted(StrictModel):
    status: Literal["committed"]
    reconciliation_attempt_id: str
    transition_id: str
    proof_artifact_ref: ArtifactRef
    state_materialization: CommittedStateMaterialization
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

class TransitionReconciliationNotCommitted(StrictModel):
    status: Literal["not_committed"]
    reconciliation_attempt_id: str
    transition_id: str
    proof_artifact_ref: ArtifactRef
    authoritative_prior_state_version: str
    authoritative_prior_state_sha256: SHA256

class TransitionReconciliationStillUnknown(StrictModel):
    status: Literal["still_unknown"]
    reconciliation_attempt_id: str
    transition_id: str
    proof_artifact_ref: ArtifactRef | None
    reason_code: Literal[
        "query_interrupted_no_result",
        "reconciler_failed",
        "proof_inconclusive",
    ]

TransitionReconciliationTerminal = Annotated[
    TransitionReconciliationCommitted
    | TransitionReconciliationNotCommitted
    | TransitionReconciliationStillUnknown,
    Field(discriminator="status"),
]

class TransitionReconciler(Protocol):
    implementation: ImplementationRef

    async def reconcile(
        self,
        request: TransitionReconciliationRequest,
        events: TransitionReconciliationEventView,
        staging: ReconciliationArtifactStaging,
    ) -> ReconciliationFinding: ...

class EnvironmentPlugin(Protocol):
    def materialize_reconciled_state(
        self,
        case: FamilyCase,
        prior_state: FamilyState,
        materialization: CommittedStateMaterialization,
        artifacts: ReconciliationArtifactView,
    ) -> FamilyState: ...

class HashedEventRef(StrictModel):
    event_id: str
    event_sha256: SHA256

class RecoveryChainLink(StrictModel):
    transition_id: str
    transition_start: HashedEventRef
    transition_terminal: HashedEventRef
    reconciliation_attempt_id: str | None
    reconciliation_start: HashedEventRef | None
    reconciliation_terminal: HashedEventRef | None

class RecoveryNotRequired(StrictModel):
    status: Literal["not_required"]
    chain: tuple[RecoveryChainLink, ...] = ()

class RecoveryReconciledCommitted(StrictModel):
    status: Literal["reconciled_committed"]
    chain: tuple[RecoveryChainLink, ...]
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

class RecoveryReconciledNotCommitted(StrictModel):
    status: Literal["reconciled_not_committed"]
    chain: tuple[RecoveryChainLink, ...]
    retry_transition_id: str
    final_attempt_disposition: Literal["succeeded", "failed"]
    final_transition_terminal: HashedEventRef

class RecoveryQuarantined(StrictModel):
    status: Literal["quarantined"]
    chain: tuple[RecoveryChainLink, ...]
    reason_code: Literal[
        "still_unknown",
        "materialization_mismatch",
        "reconciliation_failed",
        "attempt_bound_exhausted",
    ]
    detail_artifact_ref: ArtifactRef | None
    invalid_measurement: Literal[True] = True

RecoveryReport = Annotated[
    RecoveryNotRequired
    | RecoveryReconciledCommitted
    | RecoveryReconciledNotCommitted
    | RecoveryQuarantined,
    Field(discriminator="status"),
]
```

`TransitionReconciliationStart` references the original `TransitionOutcomeUnknown` by
both `transition_id` and event ID, repeats its exact idempotency key, pins the reconciler,
and is durably written immediately before the one and only V0 reconciliation query. That start is the
counted query invocation: each unknown transition has exactly one reconciliation start,
never a replay or second reconciliation-attempt ID. One start receives exactly one
terminal, and the original transition terminal is never overwritten. Neither a transition
nor reconciliation start may publish a second terminal.

The runner builds `TransitionReconciliationEventView` from only the exact hashed
transition start/outcome-unknown events, resolved policy, and typed `ArtifactRef` fields in
those events; its resolver rejects every other store object. It also creates a durable
staging journal scoped to `(evidence_store_id, transition_id,
reconciliation_attempt_id)`, but passes the reconciler only the narrowed stage-only
`ReconciliationArtifactStaging` port. Only this runner-owned port accepts canonical bytes,
writes them under a runner-chosen `staging_key`, and returns a fully serializable
`StagedArtifactRef`; the reconciler cannot choose an out-of-scope key, construct an
`ArtifactRef`, or call journal completion/resume methods. The journal durably stores the
canonical typed finding plus its `finding_sha256` and exact scope, and `load_completed()`
revalidates both before returning it. A staged ref is a serializable locator/integrity
claim, never a bearer capability or CAS ref. Its role is exact and immutable: every
finding proof is `proof`, a canonical-state materialization is `canonical_state`, and a
transition-result materialization is `transition_result`; one staged ref cannot be reused
under another role even when bytes/digest happen to match.

After the reconciler returns, the runner validates every staged-ref scope, records and
fsyncs the completed finding, then reopens each object through the runner-owned staging
area by exact `(evidence_store_id, transition_id, reconciliation_attempt_id, staging_key)`.
It verifies byte length, media type, and SHA-256 from the reopened bytes before
`ArtifactStore.put()`, validates the resulting CAS refs, and only then constructs the
terminal with `ArtifactRef` values. Recovery performs the identical reopen/verify/publish
path from journal bytes and the durable staging area; it requires no in-memory object,
token, handle, closure, or process-local cache. `ReconciliationArtifactView` is scoped to
the exact proof/materialization `ArtifactRef` values and roles published by one validated
terminal event. `resolve_terminal_artifact(ref, role=...)` exact-matches both before
returning verified bytes; the view has no listing, write, staging, reference, scorer,
provider, or whole-store method. Neither reconciliation view is a reference/scorer artifact
view or enumerates the store.

Recovery is deterministic at every crash boundary. Before the start, resume may append
the sole start and issue the query. After the start, a completed staged finding is resumed
through the same journal/CAS publication without another query; an absent completed
finding becomes `still_unknown(query_interrupted_no_result)` and quarantine. After CAS
publication but before terminal append, idempotent `put()`/validation resumes and appends
that terminal. After a terminal, normal recovery continues. `committed` and
`not_committed` always bind proof refs; only `still_unknown` may omit proof because an
interrupted query may have produced no bytes.

`committed` carries both the authoritative state version/hash and a restorable canonical
state or transition-result artifact. The runner event-scope-resolves its bytes, calls only
the pinned environment's deterministic `materialize_reconciled_state()` boundary, then
hashes the returned state and exact-matches the authoritative version/hash before resume;
it never reissues `step()`. `not_committed` carries the authoritative *prior* state
version/hash, which the chain validator must prove exactly equal to the original
`TransitionStart` prior version/hash before a new transition ID/start may be authorized
under the resolved retry bound. `still_unknown` carries an optional proof and reason
only—no authoritative state version/hash or materialization—and always
quarantines/invalidates the cell; ambiguity is never resolved by re-querying.

Also freeze the terminal receipt-facing recovery union in records. `RecoveryReport` is
one of `not_required`; `reconciled_committed` with a non-empty ordered transition/
reconciliation event-ID+hash chain and the restored authoritative state; or
`reconciled_not_committed` with that chain, the newly recorded transition ID, and its
final `succeeded | failed` disposition; or `quarantined` with the referenced chain,
typed reason, and `invalid_measurement=True`. A second unknown during the authorized retry
must reconcile again or end as `quarantined`, never masquerade as a final
`reconciled_not_committed` report. Task 3.9 constructs this terminal report; normal runs
construct `not_required`. No universally final `RecoveryDecision` is public or receipt-
bound.

Record validators require `RecoveryNotRequired.chain` to be empty and every other report
chain to be non-empty. Each `RecoveryChainLink` has either all three reconciliation fields
or none, event refs are unique and ordered by the sealed event sequence, and the terminal
event IDs/hashes must resolve to the named transition/reconciliation IDs.

**RED requirements:** record tests reject a policy missing any
reconciler/idempotency/single-query/materialization field, any
`max_reconciliation_attempts` or replay-safe query variant, a transition whose policy hash
differs from its cell, or a second terminal. `test_reconciliation_issues_exactly_one_query`
proves one unknown -> one durable start -> one reconciler invocation even across resume.
`test_reconciliation_resume_publishes_staged_result_without_query` crashes after completed
staging and after CAS publication, then proves same-journal publication and one invocation.
Its completed-staging case is a genuine new-process RED: process A writes/fsyncs staged
bytes and the canonical completed journal and exits; process B creates fresh coordinator,
staging, journal, and artifact-store objects with no inherited memory, reopens and verifies
the bytes by `StagedArtifactRef`, publishes the same CAS refs, and emits the terminal with
zero reconciler calls.
`test_reconciliation_crash_without_completed_finding_quarantines` proves no replay, an
optional-proof `still_unknown`, and invalid measurement. Fakes reject reconciler-created
`ArtifactRef`, foreign-policy/event refs, foreign-scope/forged staged refs, journal/finding
hash mismatch, absolute/traversal/symlink or substituted staging keys, byte-length/media-
type/digest mismatch, wrong or reused staged roles, a proof/materialization role swap, a
terminal-view ref not published by that exact terminal, any terminal-view list/write
surface, and reconciler access to journal completion/resume, store enumeration, or
terminal append before
`ArtifactStore.put()` returns validated refs. Reconciliation tests also reject
committed without restorable materialization or a matching authoritative state,
kind/schema drift, not-committed prior-state drift, and still-unknown with an authoritative
state. Recovery-report tests cover all four variants, non-empty/ordered chains, and the
final retry disposition. Exact version/hash tests cover the Task 1.1c-to-Task 2.1b
`PlanCell`/`RunPlan` migration.

**Output:** one plan-bound, single-query transition/reconciliation contract with
runner-owned durable serializable artifact staging and CAS publication, deterministic state
materialization, append-only recovery evidence, and a terminal `RecoveryReport`; no
receipt-facing `RecoveryDecision`, reconciliation retry count, or store-wide artifact
authority exists.

### Task 2.2: Add episode-scoped harness lifecycle

**Dependency:** Task 2.1a is independently clean.

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py`.
- Modify `tests/shared_runner/fakes.py`.
- Create `tests/shared_runner/test_agent_lifecycle_contract.py`.

This task owns lifecycle capability/policy/operation records, Protocols, stable exports,
and scripted conformance fakes only. It does **not** create or partially implement a
lifecycle coordinator; Task 3.2 is the sole owner of orchestration and cleanup execution.

`AgentAdapter` remains the stable act-only v1 Protocol. Task 2.2 must not add required
lifecycle methods to `AgentAdapter`; `LifecycleAgentAdapter` is a separately named additive
Protocol that may extend the act boundary with native lifecycle capabilities. A runner-owned
stateless compatibility wrapper presents every existing act-only v1 adapter as a trivial
session. The new Protocol and wrapper are additive; replacing the existing Protocol or
changing `AgentAdapter.act()` requires SDK v2.

Minimum lifecycle:

```text
ExecutionBackend.start
  -> LifecycleAgentAdapter.setup
    -> LifecycleAgentAdapter.open_session
      -> AgentSession.act*
      -> AgentSession.reset / close
    -> LifecycleAgentAdapter.cleanup
  -> ExecutionBackend.stop
```

Define three separate records: adapter-declared `AgentAdapterCapabilities`, runtime-
declared `ExecutionBackendCapabilities`, and request-side `SessionPolicy`. A runner-owned
coordinator implemented only in Task 3.2 will validate compatibility before
`ExecutionBackend.start()` and own backend start/stop, adapter setup/cleanup, session
open/close, and their write-ahead events. The Protocols require an action executor to
borrow an existing session; it never owns session close or adapter cleanup. The lifecycle
records make the `EpisodeAttempt` finalization choice explicit: exactly one terminal action
for each live session generation, `close` by default or `reset-consume` only when a next
attempt has already been authorized.

`ExecutionBackendCapabilities` is the sole owner of backend capability facts. Alongside
lifecycle start/stop/isolation/reset/cleanup, it strictly declares supported execution
kinds, process isolation, filesystem/network/terminal modes and exact host allowlists,
tool/version pins, container image digests, secret scopes, and minimum observability.
Task 2.3 consumes this record for admission and must not introduce a second backend-
capability model.

Backend/setup generations are scoped as explicitly as sessions. The conservative default
lease subject is a strict discriminator:

```python
class EconomicSeatLeaseSubject(StrictModel):
    subject_kind: Literal["economic_seat"]
    episode_attempt_id: str
    seat_id: str
    seat_kind: Literal["candidate", "counterpart"]

class EvaluatorLeaseSubject(StrictModel):
    subject_kind: Literal["evaluator"]
    episode_attempt_id: str
    evaluation_work_id: str
    evaluator_assignment_id: str
    planned_judgment_slot_id: str

LifecycleLeaseSubject = Annotated[
    EconomicSeatLeaseSubject | EvaluatorLeaseSubject,
    Field(discriminator="subject_kind"),
]

class EconomicSeatLeaseSubjectKey(StrictModel):
    subject_kind: Literal["economic_seat"]
    seat_id: str
    seat_kind: Literal["candidate", "counterpart"]

class EvaluatorLeaseSubjectKey(StrictModel):
    subject_kind: Literal["evaluator"]
    evaluator_assignment_id: str
    planned_judgment_slot_id: str

LifecycleLeaseSubjectKey = Annotated[
    EconomicSeatLeaseSubjectKey | EvaluatorLeaseSubjectKey,
    Field(discriminator="subject_kind"),
]
```

`LifecycleLeaseSubjectKey` is the sole plan-time projection of a runtime subject: it drops
only operational `episode_attempt_id`/`evaluation_work_id` fields and preserves the exact
economic seat or evaluator assignment/judgment-slot discriminator. Task 2.3 reuses this
type for plan-bound admission; it must not create a competing subject union. The default
backend/setup/session lease key is the complete runtime subject tuple. An evaluator is
never synthesized as a `SeatSpec`, given economic utility, or admitted under candidate/
counterpart semantics. Reuse across subjects/cells/attempts requires declared
state-containment plus reset/cleanup capability, capability preflight, and a receipt-
visible treatment declaration covering filesystem, process, cache, memory, and tool
state. Session isolation alone never proves runtime isolation.

Default session scope is the exact `LifecycleLeaseSubject`. Across subjects or
EpisodeAttempts the default is close plus a fresh open. An optional
`reset(old_session, next_spec) -> new_session_generation` consumes the old handle and
replaces close/open; every generation is finalized exactly once by either close or a
successful reset-consume. A failed, timed-out, or outcome-unknown reset never yields a
reusable generation; the runtime is closed/quarantined through the typed failure path.
`SessionPolicy` binds
within-episode continuation, retry behavior (`restart_from_pre_action`, `continue`, or
`forbid`), reset/isolation scope, cleanup timeout, memory scope, tool allowlist, and
required minimum observability. Actual provider/tool observability comes only from
adapter capabilities and is copied into the resolved plan/receipt. Cross-cell state
leakage is forbidden unless persistent
memory is an explicit treatment with analysis implications.

`restart_from_pre_action` is coordinator-owned: close/quarantine the affected generation,
open a fresh generation, then restore an adapter-declared checkpoint or deterministically
replay only the canonical pre-action message prefix. Economic/tool side effects are never
replayed. Capability preflight must prove checkpoint/restore or safe prefix replay before
this policy is admitted. `continue` is admitted only when the adapter can certify the
session mutation as reconciled and usable; unknown session mutation forbids continuation.

Lifecycle/setup/runtime operations are evidence-visible but are not mislabeled as
economic tool calls. Partial setup/open failures clean up every acquired resource;
unsupported reset falls back to close/open only when policy permits. Cleanup is
idempotent, runs in `finally`, and quarantines a runtime whose cleanup fails. Existing
stateless HTTP adapters enter through the runner-owned compatibility wrapper and use a
trivial session; persistent CLI/API adapters may implement the additive lifecycle Protocol
directly.

Define a runner-owned `ToolMediator` port and pass it to `AgentSession.act()`. It validates
lease-subject/work/phase tool allowlists for operations that may execute inside an attempt,
writes durable starts before those side effects, and reconciles terminal outcome.
`ExecutionBackend` owns process/file/network/runtime operations only. Harness-internal
tools never mutate economic state. Only read-only, harness-internal, or deterministic
transactional preview tools may execute and return a result before provider execution
continues inside the same attempt. A model-emitted request for a mutating family tool is
not executed by `ToolMediator`; it remains untrusted normalized `CanonicalResponse`
content and the attempt returns. The scheduler then invokes family `parse_action()` and
`legal()` before it can open `TransitionStart` and call the single state-versioned atomic
`step()`. Any provider continuation after a committed transition is a new
`LogicalAction`/`ActionAttempt` in the same authorized session.
During simultaneous collection, immediate tools are read-only/preview against the frozen
snapshot; mutating actions are staged and committed together only after all slots arrive.
Thus tools cannot create a second untracked environment-mutation path.

**RED requirements for this contract task:** schema/protocol tests reject conflated
adapter/backend/request capabilities, an unscoped/incomplete lease subject, evaluator
work encoded as a seat, evaluator utility/seat-kind fields, reuse without containment and
reset/cleanup capability, an unobservable continuation policy, or more than one terminal
choice for a session generation. Scripted fakes expose backend-start, partial-setup,
open-session, reset, close, cleanup, backend-stop, timeout, failure, and
`outcome_unknown` outcomes without orchestrating them. The `ToolMediator` fake rejects a
requested family mutation and can execute only read-only, harness-internal, or
transactional-preview operations. Task 3.2 consumes these fakes for the runtime failure
matrix. A pre-Task-2.2 conformance fake that implements only the stable
`AgentAdapter.act()` Protocol must still pass admission and execute through the stateless
wrapper after this task lands.

**Output:** versioned lifecycle/capability/session/tool-mediation contracts with distinct
economic-seat and evaluator-assignment subjects plus reusable scripted fakes, with no
coordinator implementation in this task.

### Task 2.3: Freeze whole-trial admission semantics without implementing a protocol

**Dependency:** Tasks 2.1a, 2.1b, and 2.2 are independently clean.

**Files:**

- Modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py` for strict
  runtime-requirement and admission records only; move/re-export the existing sole
  `AdmissionProfile` alias there for record use and make planning import it rather than
  declaring a second alias; consume Task 2.2's sole `ExecutionBackendCapabilities` record
  unchanged.
- Modify `src/aeread/runner/planning.py` to add the pure
  `resolve_execution_admission(...)` function; do not add an upstream adapter Protocol.
- Modify `tests/shared_runner/test_records.py` and
  `tests/shared_runner/test_planning.py`; create
  `tests/shared_runner/test_execution_surface_admission.py`.
- Modify the execution-surface ownership tables in `docs/shared_runner_design.md` and
  `docs/public_environment_and_external_adapter_spec.md`; guard them in
  `tests/test_shared_runner_design_contract.py`.

Add strict `RuntimeRequirementSpec` fields corresponding exactly to Task 2.2's
`ExecutionBackendCapabilities` for every execution dimension: `execution_kind`
(`in_process | local_subprocess | container |
remote_sandbox | upstream_managed`); process isolation; filesystem (`none | read_only |
read_write`); network (`none | allowlisted | upstream_managed`) plus an exact non-empty
allowlist when selected; terminal (`none | noninteractive | interactive`); sorted unique
required tool IDs/version pins; container image digest when `container`; declared secret
scope (`none | named_scopes | upstream_managed`) without secret values; and minimum
provider/tool/runtime observability. The existing backend capabilities declare the exact
supported sets and maxima for the same fields, not an open options map. Unknown enum values,
missing conditional fields, wildcard tools/hosts/secrets, or an unpinned container fail.

Freeze this provider-free API and its canonical input/report hashes:

```python
def resolve_execution_admission(
    *,
    requested_profile: AdmissionProfile,
    subject: LifecycleLeaseSubjectKey,
    capabilities: CapabilityDeclaration,
    runtime_requirements: RuntimeRequirementSpec,
    backend_capabilities: ExecutionBackendCapabilities,
) -> SubjectExecutionAdmission: ...
```

The resolver exact-checks schedule control, execution kind, isolation, filesystem,
network/host allowlist, terminal mode, every tool/version, image digest, secret scope, and
observability before any backend, file, network, provider, or tool call. Reuse the existing
`AdmissionProfile = paper_primary | training | interop_only`; do not introduce
`ExecutionProfile`. The immutable `SubjectExecutionAdmission` has
`spec_version="aeread.subject_execution_admission/0.1"`, one exact
`LifecycleLeaseSubjectKey`, requested/resolved admission profile and schedule control,
canonical requirement/capability hashes, effective bounds, admission class/reason, and
`admission_sha256` over every field except itself. A rejection produces only a typed
zero-side-effect admission failure.

Planning resolves the complete expected subject-key set for each cell: every economic
seat plus every evaluator-agent assignment/planned-judgment-slot pair that can open a
lifecycle; imported-human assignments create no runtime subject or synthetic admission.
`PlanCell.subject_admissions` is the canonical subject-key-sorted tuple of their immutable
accepted admissions; missing,
duplicate, extra, cell-foreign, or rejected entries fail resolution. This task is the sole
owner of the resulting breaking migration after Task 2.1b:
`PlanCell.spec_version="aeread.plan_cell/0.4"` and
`RunPlan.spec_version="aeread.run_plan/0.5"`, with no automatic prior-version parser.
Execution evidence records the full runtime `LifecycleLeaseSubject` plus the exact matching
planned subject key/admission version/hash. Task 3.11 binds the sorted set actually used,
never a cell-global admission shortcut.

Reuse the existing `CapabilityDeclaration.schedule_control` discriminator; do not create
a duplicate `execution_surface` enum or export an unconformed `UpstreamTrialAdapter` in
SDK v1. Freeze admission semantics only, and copy resolved capabilities into receipts:

| schedule control | execution surface | default admission |
|---|---|---|
| `runner` | native `EnvironmentPlugin` phase/observe/step | may apply for paper/training |
| `upstream` | stepwise upstream `advance()` | parity/interop until stronger checks |
| `opaque` | one opaque upstream trial operation (no SDK Protocol) | `interop_only` |

An opaque trial maps to one AERead `EpisodeAttempt`; its logs/trajectory are imported
artifacts/projections, never fabricated native events. Only the outer
`upstream_trial_started -> succeeded|failed|outcome_unknown` operation is native evidence.
Upstream retries must be disabled, exposed one-by-one, or declared opaque; hidden multiple
trials cannot be presented as one clean attempt. No fake child provider/tool rows.

**RED requirements:** `test_execution_admission_rejects_each_capability_mismatch_without_side_effects`
mutates each dimension above one at a time and asserts zero backend/file/network/provider/
tool calls. Named neighboring tests reject missing allowlist/tool version/container digest/
secret scope, wildcard or unknown capability values, schedule-control/profile mismatch,
and opaque execution claimed as paper/training eligible. Subject tests require distinct
economic-seat and evaluator assignment/judgment-slot admissions, reject subject-key drift
or a cell-global admission, reject an imported-human synthetic admission, and prove the
canonical sorted set and every admission hash are
covered by the `PlanCell`/`RunPlan` digests. Exact migration tests accept only PlanCell
0.4/RunPlan 0.5 after this task and reject all prior versions. The valid runner, upstream,
and opaque cases assert exact report hashes and table outcomes. An import/export RED proves no
`UpstreamTrialAdapter` exists, and opaque evidence accepts only one outer operation with
no fabricated child rows.

**Output:** one strict hashed runtime-requirement record, exact matching against Task 2.2's
sole backend-capability record, and one pure subject-keyed admission resolver/report set
bound into PlanCell 0.4/RunPlan 0.5 that fails before side effects, preserves schedule
control, and adds no whole-trial Protocol.

## Stage 3 — implement execution on the corrected contract

### Task 3.1: Provider-free phase scheduler against an executor port

**Dependency:** Tasks 2.1a and 2.1b are independently clean.

Create `src/aeread/runner/kernel.py` and `tests/shared_runner/test_kernel.py`. First define
a small family-neutral `LogicalActionExecutor` port and scripted fake; do not depend on a
real provider/session executor. Its output is
`CanonicalResponse | ActionAttemptFailed | ActionAttemptOutcomeUnknown`, never
`ActionEnvelope` or `ActionBundle`. Freeze simultaneous observations, handle
sequential, simultaneous, and multi-slot decisions, then enforce this single path:
`ActionAttempt -> CanonicalResponse -> parse_action() -> ParseResult(ActionBundle) ->
legal() -> LegalityResult -> TransitionStart -> step()`. Apply family-declared missing/
invalid consequences, perform one atomic transition, validate phase edges/termination,
and record all boundaries.

**RED requirements:** before parse, `LogicalAction` carries only logical-action/phase/
`slot_id` plus the frozen request identity/hash, and `ActionAttempt` adds only its attempt
ID, parent logical-action ID, and request identity/hash. Neither record may claim a
`channel_id`, `action_id`, or `sequence_index`, and raw normalized tool-call identifiers
are not canonical economic action IDs. Only a successful family `parse_action()` creates
canonical `channel_id`, globally unique `action_id`, and ordered `sequence_index` values
inside one `ActionBundle`; its `slot_id` must exact-match the request/current slot.
Collection is keyed by slot, never reduced to `dict[seat_id, action]`, and all simultaneous
bundles enter exactly one atomic `step()` call.

Named tests reject pre-parse channel/action/sequence fields, prove request/slot identity
survives into the parse call, and then cover every parsed channel's
`min_actions`/`max_actions`, globally unique `action_id` values, unique ordered
`sequence_index` values within the bundle, and rejection of an action whose `slot_id`
differs from its bundle/current slot. The entire bundle is rejected when any required
channel/action is missing, extra, malformed, cross-slot, or illegal; no valid sibling from
a rejected partial bundle reaches `step()`.

`test_mutating_tool_request_is_untrusted_until_parse_and_legality` asserts that a model-
requested family mutation creates no `ActionEnvelope`, no `ToolInvocationSucceeded`, and
no `step()` call before successful parse and legality. Neighboring malformed-parse and
illegal-bundle cases assert zero transition starts and zero steps; only the fully legal
bundle writes one durable `TransitionStart` and then calls `step()` once.

**Transition RED requirements:** durable start precedes `step()`; exception before any
commit produces `failed` with unchanged prior hash; exception after an unreconciled
possible commit produces `outcome_unknown`; successful commit binds the exact next
version/hash. Every transition start exact-matches the `PlanCell` transition-policy hash;
Task 3.4 separately owns subject-admission composition. Replay/resume rejects a missing,
duplicate, or contradictory terminal row and
Task 3.9 alone may reconcile an unknown transition.

### Task 3.2: Episode/session lifecycle coordinator

**Dependency:** Tasks 2.2 and 2.3 are independently clean.

**Files:**

- Create `src/aeread/runner/lifecycle.py`.
- Modify `src/aeread/runner/__init__.py` only to export the completed coordinator surface.
- Create `tests/shared_runner/test_lifecycle.py`.

**Consumes:** Task 2.2's lifecycle capability/policy/operation records, Protocols and
scripted fakes, plus Task 2.3's exact plan-bound `SubjectExecutionAdmission` for each
subject. **Produces:** `EpisodeLifecycleCoordinator.preflight(subject,
admission, ...) -> LifecycleLeasePlan`, `start_attempt(subject: LifecycleLeaseSubject, ...) ->
EpisodeLifecycle`, `borrow_session(subject) -> AgentSessionLease`, and
`finalize_attempt(subject, ...) -> LifecycleFinalization`. `preflight` also receives the
same full runtime subject and rejects unless its `LifecycleLeaseSubjectKey` projection,
admission version/hash, and PlanCell entry exact-match. This is the only task that
implements lifecycle orchestration for both economic-seat and evaluator-assignment leases.

Implement fail-closed preflight and cleanup ownership with scripted adapters/backends.
Default isolation closes each session at episode-attempt scope and opens fresh on the next
attempt. Optional reset consumes the old session generation and returns a new generation;
it is never an implicit `ActionAttempt` retry. Action-attempt restart instead uses
coordinator-owned fresh generation plus safe checkpoint/restore or side-effect-free
canonical prefix replay.

**RED requirements:** absent, wrong-version/hash, cell-foreign, or wrong-subject admission
and every capability mismatch cause zero backend/provider/tool calls; both
economic-seat and evaluator subjects traverse the same preflight/start/borrow/finalize
implementation, while incomplete/economic-seat-shaped evaluator subjects fail before
start. Evaluator leases never create seats, utilities, observations, or actions;
backend-start, partial-setup, open-session, reset, close, cleanup, and backend-stop
failure/timeout/`outcome_unknown` paths each close exactly one started lifecycle operation.
A failed or unknown reset never reuses the old generation. Exactly one finalizer owns each
live generation; the action executor cannot close/reset/cleanup it. Default lease keys
prevent backend/setup/session/process/filesystem/cache/memory/tool state from crossing
subject/cell/attempt boundaries. Native session IDs and secrets never enter public evidence
or receipts, and action-attempt restart never replays economic/tool side effects.

**Output:** a runner-owned, episode-attempt and lease-subject-scoped coordinator for
economic seats and evaluator assignments, with typed preflight, leases, generation
consumption, quarantine, and idempotent `finally` cleanup.

### Task 3.3: Action-attempt executor

**Dependency:** Tasks 2.1a and 3.2 are independently clean.

Create `src/aeread/runner/attempts.py` and
`tests/shared_runner/test_attempts.py`. Test exception-after-provider-start,
provider→tool→provider, length retry, hidden retry rejection, child reconciliation,
timeout/cancellation, and ToolMediator ownership. It borrows the coordinator's live
session and never closes it. Its successful return is a `CanonicalResponse`; it never
constructs `ActionEnvelope`/`ActionBundle` or calls `EnvironmentPlugin.step()`. A normalized
mutating-family tool request ends the attempt as response content with zero executed
family-mutation tool rows; only read-only/harness-internal/transactional-preview operations
can produce `ToolInvocationSucceeded`. Add RED for these negative boundaries as well as a
failed/unknown child side effect. Failure never manufactures an economic zero.

### Task 3.4: Scheduler × real executor integration

**Dependency:** Tasks 2.3 and 3.1–3.3 are independently clean.

**Files:**

- Create `src/aeread/runner/execution.py`.
- Modify `src/aeread/runner/__init__.py` only to export the completed native runner.
- Create `tests/shared_runner/test_execution.py`.

**Consumes:** the exact subject-keyed Task 2.3 admissions from
`PlanCell.subject_admissions`, Task 3.1 `PhaseScheduler`, Task 3.2
`EpisodeLifecycleCoordinator`, and Task 3.3 `ActionAttemptExecutor`. **Produces:**
`build_native_episode_runner(...) -> NativeEpisodeRunner` and
`NativeEpisodeRunner.run_episode_attempt(cell, case, environment) -> OpenEpisodeHandoff`.
The handoff is a runner-internal discriminated result carrying the PlanCell/attempt
identity, the still-open evidence-generation handle, sorted economic-seat admissions and
lifecycle finalizations, and exactly one of terminal `FamilyOutcome` or a typed execution
failure. It is neither a sealed-evidence view nor a receipt.

The factory wires the scheduler to one lifecycle-backed `LogicalActionExecutor`; it does
not expose a second adapter/session path. `run_episode_attempt` exact-validates the
complete economic-seat subject-key/admission set and its cell hashes and completes
execution/lifecycle preflight before starting the episode, creates economic-seat lease
subjects, starts their authorized lifecycles, lets
the attempt executor borrow (never own) sessions, runs the family-neutral scheduler, and
finalizes each acquired subject exactly once in `finally`. Single-agent, controlled
counterpart, population, and live-live differ only in resolved `PlanCell`/seat inputs and
use this same function—no family/type branch or direct adapter call. It finalizes economic
lifecycles but deliberately leaves the evidence generation open. Every returned handoff,
including its execution-failure variant, transfers exactly once to Task 3.7. On the
terminal branch it carries the open generation and `FamilyOutcome` to that composition
root, which invokes Task 3.5 evaluator planning through a narrowed borrow-scoped port;
Task 3.7 is the sole later owner of the final evidence seal, and Task 3.11 alone finalizes
the receipt.
Task 3.4 never closes/seals the generation, scores, or creates a receipt.

**RED requirements:** `test_native_runner_capability_mismatch_has_zero_side_effects`
asserts zero lifecycle/backend/provider/tool/environment calls. Named tests cover all four
deployment modes through the same factory/executor/scheduler call trace; reject cell/
admission drift, missing/extra economic-seat admissions, a direct adapter/session
invocation, a bypass of parse/legality, or a
family-specific import/branch; and prove scheduler/attempt failure or cancellation still
finalizes every started lifecycle once without manufacturing an outcome/score. A handoff
test proves the terminal outcome and open generation reach Task 3.7, Task 3.4
does not call close/seal/score/receipt finalization, and a failed handoff remains open for
the single later seal owner's typed invalid-measurement path.

**Output:** one dispatchable native economic-execution root with exact admission,
lifecycle-borrow, scheduler, attempt, open-evidence handoff, and `finally` ownership; no
second execution path and no premature evidence seal.

### Task 3.5: Judge plan, authorized input, and evaluator hierarchy

**Dependency:** Tasks 1.1c, 2.1a, and 2.1b are independently clean.

**Files:**

- Create `src/aeread/runner/evaluation.py` and
  `tests/shared_runner/test_evaluation.py`.
- Modify the verifier/evaluator-authorized-input prose and Protocol example in
  `docs/public_environment_and_external_adapter_spec.md`; modify
  `tests/test_shared_runner_design_contract.py` to guard it. Task 3.7 separately owns the
  executable final-seal ordering in that document.

Add `EvaluationWork` plus `RaterAttempt`; rater provider calls belong to measurement/
evaluator work, not candidate `LogicalAction`s. Define the strict typed result
`EvaluationPlanResult = EvaluationPlanReady | EvaluationPlanNotRequired |
EvaluationPlanFailed`. The borrow-scoped API
`build_evaluation_plan(outcome, measurement, planning_port) -> EvaluationPlanResult`
accepts the terminal `FamilyOutcome`, resolved measurement, and a narrow
`EvaluationPlanningPort` owned and supplied by Task 3.7. The port may append only the
authorized planning/render/store events and artifacts for this episode; it cannot seal,
close, retain the generation, enumerate artifacts, or expose provider/runtime/session
authority. Task 3.5 never accepts, owns, retains, or returns an `OpenEpisodeHandoff` or an
open evidence-generation handle.

The result union is closed: `EvaluationPlanReady` carries the canonical work plan/hash;
`EvaluationPlanNotRequired` carries only `reason="non_judge"`; and
`EvaluationPlanFailed` carries a strict stage
`authorization | render | artifact_store`, one stage-compatible failure code
(`assignment_mismatch | visibility_violation | capability_mismatch`,
`renderer_failed | rendered_input_invalid`, or
`artifact_store_failed | artifact_ref_mismatch`), and its hashed failure-event ref. The
`EvaluationPlanningPort` exposes only
`record_planning_event(event: EvaluationPlanningEvent) -> HashedEventRef` and
`store_authorized_input(input: RenderedEvaluatorInput) -> ArtifactRef`; both arguments are
strict typed records. It has no generic payload/options method.

Planning validates the resolved judge source, concrete assignment, capability, and
visibility; renders the exact authorized projection; stores/hashes that artifact through
the narrow port; and returns ready work, a typed non-judge result, or a typed planning/
render/store failure. Task 3.7 alone calls this API while its handoff remains open and owns
the enclosing seal finalizer.
Every work item references one planned judgment slot, resolved measurement hash,
rubric/protocol, renderer, blind-order seed/counterbalance, and authorized-input artifact.

**RED requirements:** the authoritative spec and static guard reject Task 3.5 ownership or
receipt of `OpenEpisodeHandoff`, a generation handle, or seal authority. Pre-terminal
evaluator planning, unauthorized fields, assignment/slot drift, or artifact-hash drift
returns the exact typed failure before any `EvaluationWork`, `RaterAttempt`, provider, or
tool call. Evaluators never become economic seats, a request may not widen the resolved
projection, and a closed planning port fails without creating evaluator work. Named tests
freeze ready, not-required, planning, render, and store result variants and prove no Task
3.5 branch seals or closes evidence.

**Output:** a typed, provider-free evaluator work plan over frozen authorized inputs plus
its typed not-required/failure alternatives and narrow runner-owned artifact/event port;
no open-handoff ownership, evaluator execution, or seal in this task.

### Task 3.6: Pure recorded-rater aggregation

**Dependency:** Task 3.5 is independently clean.

**Files:** modify `src/aeread/runner/evaluation.py` and
`tests/shared_runner/test_evaluation.py` only.

**Consumes:** the resolved `JudgeDependentEvaluationBinding` and canned accepted/failed/
unknown records keyed by planned judgment slot. **Produces:**
`aggregate_recorded_judgments(...) -> RaterAggregate`. Aggregate human/LLM/imported
rater records by planned judgment slot, provenance, ties, missingness, and disagreement
without provider calls.
Missing, failed, and `outcome_unknown` required judgments return `invalid_measurement`
unless the predeclared partial estimator reaches `minimum_valid_judgments`; there is no
implicit drop or zero imputation. Deterministic score components stay separate from
judge-dependent components. At most one accepted judgment per planned slot contributes;
replacement `RaterAttempt` identities never increase the planned denominator. A valid tie
follows the typed tie rule and is not classified as corrupt/missing. This is the first
executable judge-verifier gate.

**RED requirements:** zero provider/runtime/tool calls; duplicate accepted judgments for
one slot, assignment/provenance drift, undeclared slots, or an implicit denominator change
fails. Named cases cover retained/half-credit/invalidate tie rules without conflating a
valid tie with missingness, required missing/failed/unknown judgments, a satisfied and an
unsatisfied partial threshold, and byte-identical repeated aggregation.

**Output:** one deterministic `RaterAggregate` over planned slots, or a typed
`invalid_measurement`, with no operational attempt counted as a new judgment.

### Task 3.7: Live evaluator execution

**Dependency:** Tasks 3.2, 3.4, 3.5, and 3.6 are independently clean.

**Files:**

- Modify `src/aeread/runner/evaluation.py` and
  `tests/shared_runner/test_evaluation.py`.
- Modify the end-to-end execution section of
  `docs/public_environment_and_external_adapter_spec.md` and its exact ordering guard in
  `tests/test_shared_runner_design_contract.py`; this task owns that final-seal ordering,
  while Task 3.5 owns evaluator-plan authorization.

Implement evaluator execution entirely with scripted/fake providers. The sole public
flow is:

```text
Task 3.7 consumes OpenEpisodeHandoff
  -> if terminal outcome: call Task 3.5 build_evaluation_plan through a narrow planning port
  -> if ready judge plan: authorized EvaluationWork/RaterAttempt execution under
       evaluator lifecycle leases -> append every judgment terminal -> close work
       -> aggregate_recorded_judgments() -> append typed RaterAggregate while log is open
  -> if not-required/non-judge: no evaluator work or aggregate
  -> if execution/planning/render/store failure or cancellation: append typed disposition
  -> finally: invoke the sole final evidence seal exactly once
  -> if valid terminal outcome plus completed/not-required evaluation:
       build ScorerInputArtifactSet from typed final visible refs
       -> measurement-bound BoundVerifier.score(
            case, outcome, sealed evidence, scorer artifact view, typed rater aggregate)
  -> otherwise: sealed invalid-measurement result with zero scorer calls
  -> completed function branches: replay/projections -> EvaluationReceipt
  -> cancellation branch: re-raise after seal; Task 3.11 binds typed prepublication failure
```

`complete_open_episode(handoff, measurement) -> SealedEpisodeEvaluation` is the one
composition API and Task 3.7 is the sole owner of the handoff, planning call, evaluator
execution, and evidence seal. Inside one `try/finally`, it constructs the narrow Task 3.5
planning port from the owned generation, calls `build_evaluation_plan(...)`, and handles
every typed result. A ready judge plan follows the full flow above; not-required seals and
continues to bound scoring with no rater aggregate; a typed execution/planning/render/store
failure appends its typed invalid-measurement disposition and seals with zero later work.
Cancellation is recorded when the log is writable, the sole seal finalizer is shielded to
completion, and cancellation is re-raised only after seal. `seal_once` is invoked exactly
once on success, no-judge, each declared failure, unexpected exception, and cancellation;
a seal-publication failure is its own terminal evidence failure and never triggers a
second seal. A seal never
precedes required evaluator work, and a sealed store never reopens for judge output. Each
evaluator-agent work item constructs the exact `EvaluatorLeaseSubject` from
its episode/evaluation-work/assignment/planned-slot IDs, calls the Task 3.2 coordinator's
preflight with the exact evaluator subject-keyed `SubjectExecutionAdmission` from the
PlanCell and then start/borrow APIs, executes provider/tool work with the same full
write-ahead contract as candidate attempts, and finalizes that subject exactly once in
`finally`.
Evaluator work never borrows an economic-seat lease or receives seat/utility semantics;
imported-human evidence creates no synthetic session. The aggregate is validated against
`ResolvedMeasurementContract.evaluation`, recorded, and included in the final seal before
its typed ref/view is passed to scoring. A missing, failed, unsealed, wrong-binding, or
invalid aggregate yields `invalid_measurement` and no numeric score. No live-provider
smoke is authorized by this task.

**RED requirements:** the authoritative public example and static guard require the exact
order above and reject seal-before-judge, judge-after-seal, provider calls from the bound
verifier, scoring without the sealed aggregate/scorer artifact-set hash, and receipt-
before-score. `test_evaluator_uses_assignment_lifecycle_lease` proves the coordinator
preflight/start/borrow/finalize trace, exact evaluator admission version/hash/subject key,
and full provider/tool write-ahead; neighboring tests reject missing/wrong/cell-global
admission or an economic-seat lease before side effects and prove `finally` cleanup.
Execution tests cover failed/missing/`outcome_unknown` judgment attempts, replacement
under a new `RaterAttempt` identity for
the same planned judgment slot, at most one accepted contribution per slot, exact
authorized-input artifact hash, blind ordering, evaluator/imported-human provenance,
disagreement, valid tie handling, and the partial-estimator threshold.
Exact branch tests prove success, no-judge, planning failure, render failure, store failure,
execution-failure handoff, unexpected exception, and cancellation each transfer the
handoff once and invoke exactly one Task 3.7 seal; cancellation cannot interrupt the seal
and is re-raised afterward for Task 3.11's typed prepublication-failure/closure path.
Failure branches make no unauthorized evaluator/scorer call,
Task 3.5/3.4/3.11 never seal, and double-seal or an unsealed
`SealedEpisodeEvaluation` fails.

**Output:** one provider-free composition root that always consumes the open handoff,
plans/executes evaluator work under assignment-scoped lifecycle leases, includes the typed
aggregate in the sole final seal, and only then derives the scorer-input artifact set for
pure scoring, with every success/failure/cancellation seal branch guarded statically.

### Task 3.8: Deterministic replay validation

**Dependency:** Tasks 1.1c, 2.1b, and 3.7 are independently clean.

**Files:**

- Create `src/aeread/runner/replay.py`.
- Create `tests/shared_runner/test_replay.py`.

**Consumes:** `PlanCell`, including its resolved transition policy and measurement design,
the full `SealedEvidenceView`, the exact validated `ScorerInputArtifactSet`/view and sealed
typed `RaterAggregateInput` when required, the pinned `EnvironmentPlugin`, and the pure
`ScoreEnvelope`. It never receives a whole-store resolver. **Produces:**
`validate_replay(...) -> ReplayReport`, where the immutable typed report records
`status`, requested/achieved replay level, transition/event coverage counts, terminal
state version/hash, `artifact_set_sha256`, score hash, and an optional typed first
divergence. Its canonical
bytes/hash are staged for Task 3.11; replay never mutates the sealed evidence/artifact
roots.

Replay reconstructs state and verifies score inputs from sealed evidence and artifacts
with zero provider, tool, evaluator, session, backend, or runtime calls.

**RED requirements:** dependency fakes raise if any external execution port is touched;
unsealed evidence, a missing/duplicate/contradictory transition terminal, a policy-hash or
bundle/order/state-hash mismatch, an unreconciled transition, invalid reconciliation
materialization/equality, or a score-input/measurement/artifact hash mismatch yields a
typed failed `ReplayReport`, never partial success. Exact state-and-score replay reports
complete coverage, while a declared `score_only` adapter can report only that weaker
achieved level. Valid zero and negative economic values round-trip numerically. Repeating
replay over the same sealed inputs produces byte-identical report/hash and no new events.

**Output:** a canonical `ReplayReport` and hash suitable for receipt binding, with fresh
tests proving replay is deterministic and side-effect-free.

### Task 3.9: Interrupted-run recovery/resume

**Dependency:** Tasks 2.1b, 3.1, and 3.2 are independently clean.

**Files:**

- Create `src/aeread/runner/recovery.py`.
- Create `tests/shared_runner/test_recovery.py`.

**Consumes:** Task 2.1b transition/reconciliation records, exact plan-resolved
`TransitionPolicySpec`, pinned `TransitionReconciler`, validated open event chain,
`TransitionReconciliationEventView`, runner-owned `ReconciliationArtifactStaging`/
`ReconciliationStagingJournal`, event-scoped `ReconciliationArtifactView`,
environment materialization hook, and Task 3.2 quarantine/lifecycle hooks. **Produces:**
`reconcile_transition(...) -> TransitionReconciliationTerminal`, an internal runner-only
`ResumeInstruction` used immediately by the coordinator, and
`finalize_recovery(...) -> RecoveryReport`. Normal paths use
`not_required_recovery(...) -> RecoveryReport(status="not_required")`. The internal
instruction is not an SDK export, serialized public identity, or receipt input.

Resume only from reconciled durable boundaries. For `committed`, event-scope-resolve the
declared state/result artifact, invoke `materialize_reconciled_state()` with the original
prior state, exact-match the returned canonical version/hash, and continue without
reissuing `EnvironmentPlugin.step()`. For `not_committed`, first prove its authoritative
prior version/hash equals the original `TransitionStart`; then allow a retry only by
allocating a new `transition_id`, durably writing a new policy-hash-bound
`TransitionStart`, and staying within `max_transition_attempts`. For `still_unknown`,
quarantine and invalidate the cell; it has no authoritative
state to resume, and no retry/new operational attempt may claim the mutation is safe. The
original `TransitionOutcomeUnknown` remains in the append-only log.

**RED requirements:** parameterize all three findings/terminals and crash points: before
start; after durable start but without a completed staged finding; after completed staging
but before CAS publication; after CAS but before terminal; and after terminal before
control-flow continuation. V0 always issues exactly one reconciler call per unknown: a
start without a completed finding closes once as optional-proof
`still_unknown(query_interrupted_no_result)` and quarantines; a completed finding resumes
the same staging journal and idempotent CAS publication without calling the reconciler.
Tests reject query replay, a second reconciliation start used to evade an unfinished one,
a reconciler-created `ArtifactRef`, foreign/forged staged refs, journal/finding-hash or
reopened-byte integrity mismatch, terminal-before-CAS, a
second or contradictory transition/reconciliation terminal, terminal overwrite, missing
proof on committed/not-committed, changed idempotency key/reconciler/policy pin, committed
materialization whose bytes or returned state do not match, not-committed prior-state
inequality, still-unknown with an authoritative state, exhausted transition bounds, and
any `step()` on committed/still-unknown paths. The not-committed path proves the old
transition is not reused, the new attempt is recorded before its one allowed `step()`, and
its final succeeded or failed terminal is referenced by the report. If that new transition
becomes unknown, it receives its own sole reconciliation query or yields quarantine.
The completed-staging case must restart in a genuinely new process with fresh coordinator/
store instances and no inherited process-local token or cache, reopen by the serialized
`StagedArtifactRef`, verify scope/media type/length/digest, and publish without re-querying.

**Output:** append-only, crash-safe recovery that closes each transition and sole-query
reconciliation exactly once, resumes only staged bytes/result publication, and emits one
terminal `RecoveryReport` binding the complete chain, including `not_required` normally.

### Task 3.10: Public/private projections

**Dependency:** Tasks 1.1c and 3.7 are independently clean.

**Files:**

- Create `src/aeread/runner/projections.py`.
- Create `tests/shared_runner/test_projections.py`.

**Consumes:** a full `SealedEvidenceView`, resolved visibility policy, declared seat IDs,
and a receipt-staging artifact sink separate from the sealed canonical evidence store.
**Produces:** `build_projections(...) -> ProjectionSet` containing one public projection
reference, deterministic per-seat trajectory references, and their canonical hashes.

Derive default-deny public and seat projections without changing the canonical evidence
or artifact roots. Redacted rows retain event identity/order/hash and an explicit redaction
marker; they never expose payload refs the audience is not authorized to resolve.

**RED requirements:** evaluator-only payloads, other-seat private observations, raw
provider artifacts, credentials, native session IDs, and secret-bearing tool/runtime
fields never appear in public or unauthorized seat bytes. Cross-seat noninterference
mutation tests leave the other seat/public projection byte-identical. Unknown visibility,
missing policy coverage, forged artifact refs, or an audience widening request fail closed.
Repeated derivation is byte-identical, projection hashes verify, and the pre/post canonical
evidence roots are identical.

**Output:** a typed, privacy-checked `ProjectionSet` staged for receipt finalization, with
public and per-seat artifacts that remain reconcilable to canonical event identities.

### Task 3.11: Receipt finalization

**Dependency:** Tasks 2.3 and 3.7–3.10 are independently clean.

**Files:**

- Create `src/aeread/runner/finalize.py`.
- Modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py` only for the
  version-bumped final `EvaluationReceipt`, `AttemptChainClosure`, and
  `RunAttemptCoverageManifest` schemas/exports.
- Create `tests/shared_runner/test_receipt.py` and
  `tests/shared_runner/test_attempt_closure.py`.

**Consumes:** sealed evidence, the exact `ScorerInputArtifactSet`/hash and sealed typed
`RaterAggregateInput` when required, pure score/typed measurement failure, Task 3.8
`ReplayReport`, Task 3.9 terminal `RecoveryReport`, Task 3.10 `ProjectionSet`, Task 2.3
subject-keyed `SubjectExecutionAdmission` values and their runtime-subject evidence, and
the resolved `RunPlan`/`PlanCell`. **Produces:**
`finalize_episode(...) -> EvaluationReceipt` and an atomic canonical receipt file whose
`receipt_sha256` excludes only its own digest field; then, only after retry control for a
cell has ended, `close_attempt_chain(...) -> AttemptChainClosure`; and, only after every
planned cell is closed, `close_run_attempt_coverage(...) -> RunAttemptCoverageManifest`.
Task 3.11 is the sole attempt-chain and run-close owner.

Only after seal/pure score, replay validation, final recovery state, and projections,
create the immutable receipt. It binds plan/case, candidate, counterpart and judge
configurations, runtime/tools, environment/parser/verifier/reference pins, the complete
resolved measurement, `suite_manifest_sha256`, and transition-policy hashes, evidence
roots, replay result/coverage/
report hash, the terminal recovery status and referenced transition/reconciliation chain,
the sorted subject-admission version/capability hashes and observability,
`composition_sha256`, the exact sole
planned `PlanCell` key plus cluster/pair/judgment-slot identity (never attempt counts),
the outcome-blind `EpisodeAttemptInclusionPolicy` hash and this receipt's immutable local
`AttemptPolicyEvidence`,
sorted scorer-input refs and `artifact_set_sha256`, typed rater-aggregate ref/status,
projection and per-seat trajectory refs, and score or typed failure. Final selected/
excluded disposition is derived only in Task 3.12 and never retroactively written here.
Secret/native session identifiers are excluded, and finalization never enumerates the
artifact store.

**RED requirements:** finalization rejects unsealed evidence, an unfinished transition or
reconciliation, a missing/nonterminal `RecoveryReport`, absent/mismatched replay/
projection/measurement/transition-policy hashes, cluster or plan identity drift,
scorer-artifact-set/rater-aggregate/admission/composition drift, an invalid score paired
with numeric output, and any secret/native session identifier in
the public receipt. A scorer/judge/recovery failure produces `invalid_measurement` with no
numeric zero imputation. Receipt publication is atomic/idempotent for identical canonical
bytes and refuses a different second receipt for the same episode attempt. Hash mutation
tests cover every candidate/counterpart/judge/runtime/tool/plugin/reference/evidence/
replay/recovery-chain/transition-policy/cluster/planned-slot/projection/score/attempt-policy/
local-predecessor-evidence
field plus the sole PlanCell and artifact-set hashes. The four recovery statuses are
receipt-distinct; `quarantined` always has
`invalid_measurement` and no numeric score, while a valid `not_required` report is
mandatory for an uninterrupted run.

The receipt admission field is the canonical sort by full runtime subject tuple of every
admission actually used. Each entry binds the runtime subject, its exact planned
`LifecycleLeaseSubjectKey`, `aeread.subject_execution_admission/0.1` version, and
`admission_sha256`; the set must exactly cover all started economic-seat and evaluator
subjects and each entry must match `PlanCell.subject_admissions`. A single cell-global hash,
missing evaluator admission, duplicate subject, or unsorted set fails finalization.

Add immutable content-addressed closure records. One
`aeread.attempt_chain_closure/0.1` `AttemptChainClosure` exists for every exact `PlanCell`
key/hash after no further `EpisodeAttempt` can be authorized. It binds the resolved
inclusion-policy hash; the complete canonical ordinal/predecessor chain; every attempt ID
and terminal event ID/hash; and, for each attempt, exactly one immutable
`EvaluationReceipt` ID/hash or strict `ReceiptPrepublicationFailure` carrying its terminal
canonical typed failure-event record/hash and one of `input_contract_incomplete |
canonicalization_failed | atomic_publication_failed | run_cancelled_before_receipt`. A
zero-attempt cell instead binds exactly one
`TypedPlanCellExclusion` with its canonical durable run-control event record/hash and reason
`preflight_rejected | run_cancelled_before_attempt`; it cannot also carry attempt entries.
The closure records the final chain-tail attempt ID or `None` and exactly one outcome-blind
stop reason: `non_retry_terminal | retry_bound_exhausted |
run_cancelled_after_attempt | no_attempt_preflight_rejected |
no_attempt_run_cancelled`. Its `closure_sha256` covers every field except itself. Receipt
bytes remain immutable local attempt evidence; neither a later attempt nor closure rewrites
them.

One `aeread.run_attempt_coverage/0.1` `RunAttemptCoverageManifest` binds the `RunPlan` ID/
hash, its exact canonical ordered `PlanCell` key set, the one-to-one ordered closure ID/hash
set, and `closure_set_sha256` over that canonical pairing. Construction exact-matches the
plan: a missing, extra, duplicate, reordered, wrong-cell, or wrong-hash closure fails and
the run remains open. Typed exclusions and prepublication failures must resolve to their
embedded canonical events by recomputed hash and exact allowed phase/reason; an
operator-supplied reason or a bare string cannot satisfy coverage.

**Closure RED requirements:** close rejects a gapped/noncanonical predecessor chain,
attempt without exactly one terminal, receipt/failure double binding, receipt hash or
terminal mismatch, closure before retry control ends, outcome-derived stop reason, forged
prepublication failure, forged zero-attempt exclusion, a tail inconsistent with the
resolved policy, and a second different closure for one PlanCell. Run close rejects every
missing/extra/duplicate/reordered closure and any PlanCell/hash substitution; the exact
same canonical set is idempotent. A receipt finalized before a later authorized retry
remains byte-identical after closure.

**Output:** one immutable, hash-verifiable `EvaluationReceipt` per finalized episode
attempt, or a typed pre-publication failure if the finalization contract is incomplete or
run cancellation prevents receipt publication; then exactly one content-addressed
`AttemptChainClosure` per PlanCell and one exact-set `RunAttemptCoverageManifest` per
closed run.

### Task 3.12: Pure post-receipt analysis and composition

**Dependency:** Tasks 1.1c and 3.11, including its attempt-chain/run-close ownership, are
independently clean.

**Files:**

- Create `src/aeread/runner/analysis.py`.
- Modify `src/aeread/runner/__init__.py` only to export the completed analysis surface;
  modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py` only for the
  versioned `AnalysisRecord`/typed result records.
- Create `tests/shared_runner/test_analysis.py` and golden input/record pairs under
  `tests/shared_runner/fixtures/analysis_v0/`.
- Modify the post-receipt analysis ownership sections in `docs/verifier_taxonomy.md` and
  `docs/walkthroughs/shared_runner_architecture_roadmap.md`; guard the pure boundary in
  `tests/test_shared_runner_design_contract.py`.

**Consumes:** an immutable `RunPlan`, its resolved suite analysis/composition declarations,
its canonical-hash-validated `RunAttemptCoverageManifest` and exact ordered
`AttemptChainClosure` values, and canonical-hash-validated `EvaluationReceipt` values.
**Produces:**
`AnalysisEngine.analyze(run_plan, run_coverage, attempt_closures, receipts) ->
AnalysisRecord`. The engine and every
registered `AnalysisMethod` are synchronous, deterministic, provider/runtime/network/
filesystem/write-free functions. Metamorphic and field-rating declarations resolve their
exact pinned `ImplementationRef` through a pure registry and receive only typed declared
canonical-rational or categorical leaf/receipt values and may return only the same closed
value union. The engine alone applies `aeread.binary64_rne/0.1` to a final rational output;
a host-float method input/output, unknown implementation, pin drift, open options, or an
attempted port access fails. A method that cannot implement this contract is absent from
V0 portable numeric output rather than labeled portable. The engine returns canonical
bytes with `schema_version="aeread.analysis/0.1"` and `analysis_sha256` computed over every
field except itself; only its caller may publish those returned bytes with
`ArtifactStore.put()`.

Validate analysis inputs before arithmetic. Verify the run-coverage hash and require its
ordered PlanCell keys to equal the `RunPlan` set exactly; require the supplied ordered
closure ID/hash set to equal its manifest exactly; then verify every closure hash, cell/
policy binding, attempt chain, terminal event hash, receipt/prepublication-failure union,
tail, typed exclusion, and outcome-blind stop reason. Every supplied receipt must appear
exactly once in its cell closure, every closure receipt ref must be supplied, and every
typed failure/exclusion must exact-resolve to its durable event and allowed reason. A
missing, added, duplicate, reordered, substituted, or forged manifest/closure/receipt/
failure/exclusion fails before arithmetic.

Then verify each receipt's canonical hash and exact run/suite/cell/measurement/composition/
artifact-set bindings and independently recompute the resolved
`EpisodeAttemptInclusionPolicy` over each closure's complete predecessor chain without
reading any score, utility, success predicate, action-quality, or other outcome value.
Every receipt's policy hash and local `AttemptPolicyEvidence` must validate; the engine
emits the canonical `AttemptSelectionProof` from the closure and receipt evidence. For each
planned key, exactly zero or one integrity-complete receipt may be selected to provide that
cell's measurement disposition, and exactly zero or one valid numeric contribution may
enter arithmetic. Excluded operational-attempt receipts remain traceable inputs but never
count. An unauthorized retry, tail/stop mismatch, or two selected receipts for one key
fails. A key with a typed closure exclusion or no selected valid numeric measurement is
named in coverage and follows only the resolved missingness rule; analysis never chooses a
later attempt because its score is available or favorable.
No `EpisodeAttempt`, `RaterAttempt`, excluded
receipt, or retry row can fill a missing cell or change a denominator. Each analysis block
consumes only its declared leaf, arm, pair, group, population, or metamorphic inputs and
records `planned_count`, `valid_boolean_count`, `invalid_or_missing_count`, and
`success_count` wherever a probability or success rate is published.

Freeze V0 arithmetic and ordering rather than inheriting library defaults. The pure
numeric policy is `aeread.exact_rational_binary64/0.1`: lift every validated finite input
binary64 from its exact IEEE sign/exponent/significand bits into an integer rational, keep
declared probabilities/quantiles/confidence levels as canonical integer rationals, and do
all estimator, resampling, comparison, and interval arithmetic exactly. At each typed
numeric output boundary, `aeread.binary64_rne/0.1` rounds the exact rational directly to
IEEE-754 binary64, round-to-nearest ties-to-even, using integer quotient/remainder and
without an intermediate host float/decimal; overflow/non-finite fails and negative zero is
canonicalized to positive zero before project canonical JSON. The engine completes the
exact-rational dependency graph before rounding any recorded copy; a rounded output never
feeds a downstream statistic. Thus:

- uniform mean is the exact rational sum divided by `n`; probability reports integer
  `success_count`, `planned_count`, `valid_boolean_count`, and
  `invalid_or_missing_count`. A `planned` denominator produces a number only when
  `planned_count == valid_boolean_count`; otherwise the probability is
  `invalid_measurement` with no numeric fields. A predeclared `valid` denominator divides
  only by `valid_boolean_count`. Invalidity is never Boolean `false`, and operational
  availability is computed only under its separate declared estimand; R-7
  quantile sorts exact lifted values and uses exact `h=(n-1)q`, `j=floor(h)`, and
  `x[j] + (h-j)*(x[j+1]-x[j])` (the sole value for `n=1`);
- a paired difference applies the declared direction within each exact pair and divides
  the exact sum by `n_pairs`; an unpaired difference is the difference of the two exact
  uniform arm means in declared direction;
- pass-all-k groups by declared `PlanCell` group key, requires exactly `k` unique cells,
  assigns group value `1` iff every resolved success predicate is true and `0` otherwise,
  then reports integer passed-group numerator, declared valid-group denominator, and
  their mean. Missing/extra/duplicate cells invoke missingness and never silently alter k;
- vector and hybrid-gate outputs preserve direct leaf block IDs and never mutate a leaf
  result or `measurement_sha256`. Judge-augmented output is only its ordered component IDs,
  dependency edges, component statuses, judge block, and tie/missing disposition; it has no
  numeric combiner or scalar. A V0 weighted declaration preserves only
  the ordered component vector, `composition_sha256`, exact rational declaration, and
  `weighted_scalar_status="deferred"`; AnalysisEngine neither applies its transforms/
  weights nor publishes an official weighted scalar until a future version binds and
  executes a finite typed sensitivity grid.

`ClusterBootstrapIntervalSpec` uses percentile cluster bootstrap exactly. First validate
that each indivisible pair and pass-all-k group is wholly nested in one effective
resampling block. The effective mapping is the resolved cluster mapping unless the suite's
strict larger-block partition coarsens clusters and contains each cross-cluster group;
cross-block partial groups fail. Group rows into one ordered row-block per resolved sorted
effective identity, preserving every validated row, pair/group field, original cluster
identity, and unequal block size; require at least two valid effective blocks. For each of
B draws, sample C whole row-blocks with replacement and recompute the complete declared
uniform-weight estimator over all rows with block multiplicity. V0 has no cluster-level
contribution reduction or weighting shortcut.
Sampling uses SHA-256 counter blocks over
the canonical domain `(aeread.cluster_bootstrap/0.1, run_plan_sha256, analysis_block_id,
seed, draw_index, position, retry_counter)`: interpret the digest as an unsigned 256-bit
integer, reject values at or above `2^256 - (2^256 mod C)`, and take `value mod C`.
Sort the B finite statistics and compute endpoints at `(1-confidence)/2` and
`1-(1-confidence)/2` with the same exact-rational R-7 rule and sole output rounding.
Record confidence, B, seed, C, sampler/
quantile version, endpoint values, original cluster identities, effective block mapping,
and effective block identities in `AnalysisRecord`.

`PairedRandomizationTestSpec` publishes a test, never a confidence interval. From the
sorted exact pairs, first exact-validate literal
`assignment_mechanism="independent_uniform_within_pair"` plus the plan-bound assignment
and exchangeability provenance; observational or other pair formation may publish the
paired effect but must produce no p-value. Compute observed absolute exact-rational mean
difference. If `2^n` is no larger
than the declared exhaustive threshold, enumerate sign masks from `0` through `2^n-1`
in sorted pair order, with bit `0 -> -1` and bit `1 -> +1`, and report the exact rational
`count(T >= T_obs)/2^n`. Otherwise, for every `(draw_index, pair_position)` take bit zero
of the digest over canonical `(aeread.paired_randomization/0.1, run_plan_sha256,
analysis_block_id, seed, draw_index, pair_position)` with the same sign mapping, then
report exact rational `(1 + count(T >= T_obs))/(B + 1)`. Ties use `>=`; the record
names exhaustive vs Monte Carlo, pair count/order, B/seed when applicable, statistic, and
p-value, provenance refs, numeric-policy version, and `NoIntervalSpec(method="none")`.

`AnalysisRecord` binds analysis/run/suite/composition hashes, the run-coverage manifest ID/
hash and ordered exact closure ID/hash set, all sorted receipt ID/hash/cell/inclusion-policy/
selection-proof refs, exact expected/selected/valid/missing coverage and planned/valid-
Boolean/invalid-or-missing/success counts, per-block estimator/comparison/metamorphic/
field-rating results, intervals/tests, composition outputs, every analysis implementation
pin, numeric/sampler versions, and its own digest. The golden fixture freezes complete
canonical JSON and digest for mean, probability, R-7 quantile, paired/unpaired difference,
pass-all-k, bootstrap, randomization test, one canonical-rational metamorphic method, one
categorical field-rating method, and each executable composition variant; judge-augmented
freezes only its structural component/status result, while the weighted fixture freezes
its vector, deferred-scalar status, declaration hash, canonical JSON, and digest.

**RED requirements:** `test_analysis_v0_record_matches_golden_bytes_and_hash` covers the
complete fixture. Named neighboring tests mutate each run-coverage/closure/receipt/ref/pin/
PlanCell/group/pair/effective-block/cluster/composition field; reject a missing, added,
duplicate, reordered, wrong-cell, or wrong-hash closure and a forged typed exclusion or
prepublication failure; reject duplicate selected/extra cells and enforce declared
missingness for zero-valid cells; prove excluded operational retries do not change
coverage, probability denominators, or pass-all-k; reject outcome-dependent selection and
prove the engine recomputes each attempt chain/proof from the exact closure. One invalid
planned probability cell rejects all numeric planned-denominator fields; the corresponding
predeclared valid-denominator fixture freezes exact counts/identities, and operational
availability remains a separate estimand. Freeze exact-rational input lifting,
the final binary64 bits and canonical JSON for `1/3`; the exact midpoint between bit
patterns `0x3ff0000000000000` and `0x3ff0000000000001` rounding to the even lower value;
and the midpoint between `0x3ff0000000000001` and `0x3ff0000000000002` rounding to the
even upper value. Also freeze
bootstrap draw indices/endpoints and exhaustive/Monte Carlo randomization p-values; and
prove paired randomization has no CI fields, rejects observational/non-uniform assignment,
and requires both provenance refs. Bootstrap tests reject partial pair/pass-all-k groups
across effective blocks, accept the exact declared coarsening, and sample each whole block
with multiplicity. Custom-method tests reject a host-float argument or return and prove
only canonical rational/categorical values enter portable V0 output. Weighted-composition
tests reject any V0 official scalar or unexecuted-sensitivity claim; judge-augmented tests
reject any combiner or scalar. Dependency fakes raise on artifact-store
enumeration, write, file, network, provider, evaluator, lifecycle, tool, runtime, or
environment access. Reordered input receipts produce byte-identical output; repeated
analysis produces identical bytes/hash and no side effect.

**Output:** one pure content-addressed `AnalysisRecord` over validated receipts with exact
coverage, V0 numeric/bootstrap/test goldens, declared higher-order methods, and post-leaf
composition; no analysis mutates receipts or leaf measurement identity.

## Stage 4 — provider-free conformance

### Task 4.1: Conformance library

**Dependency:** Tasks 3.1–3.12 are independently clean.

**Files:**

- Create `src/aeread/runner/conformance.py`.
- Create `tests/shared_runner/test_conformance.py`.

**Consumes:** stable SDK/kernel interfaces and scripted fixtures only. **Produces:**
`run_conformance(subject, selection) -> ConformanceReport`, an importable deterministic
library API with named case results and no provider credentials/network dependency.

The provider-free matrix covers strict manifests; all five verifier leaves and three
evaluation modes, including one leaf allowed under two suite-selected non-judge modes;
separate read-only reference/scorer/reconciliation artifact boundaries, strict staged
artifact roles, terminal-ref-only reconciliation resolution, and scorer-set hash; exact
cluster/effective-resampling-block/pair/sole-`PlanCell`/planned-judgment mapping with
operational attempts excluded; sequential/simultaneous/multi-channel scheduling; channel
cardinality and atomic bundles; privacy; malformed/illegal/
missing/timeout actions; the no-mutation-before-parse/legal boundary; actual tool evidence;
economic-seat/evaluator-subject lifecycle cleanup/isolation; judge visibility, pre-seal
evaluator planning/work under Task 3.7 handoff ownership, sealed typed aggregation,
exactly-once final-seal success/failure/cancellation ordering, and fail-closed missingness/
probability denominators; structural-only judge augmentation and canonical-rational/
categorical custom analysis methods;
all transition-policy, sole-query/staging/materialization/reconciliation, and terminal
recovery-report outcomes; deterministic replay; receipt integrity; exact one-per-PlanCell
attempt closures and run-close coverage; pure golden
post-receipt analysis; and valid zero/negative economics.

**RED requirements:** an intentionally broken fixture for each named invariant fails only
its expected case with a stable failure code; a conforming minimal fixture passes the full
matrix with zero network/provider calls. Selection cannot omit prerequisite integrity
cases while claiming the stronger profile, and provider-free success is labeled
conformance rather than upstream parity, live readiness, or benchmark quality.

**Output:** an importable provider-free conformance library plus a typed, deterministic
`ConformanceReport` consumed unchanged by Task 4.2.

### Task 4.2: Conformance CLI

**Files:**

- Create `src/aeread/conformance_cli.py`.
- Modify `src/aeread/cli.py` to route `aeread env test` to that module without changing
  existing Exchange verbs.
- Create `tests/shared_runner/test_conformance_cli.py`.

**Consumes:** Task 4.1 only; the CLI adds no conformance semantics. **Produces:**
`aeread env test <plugin-id> [--case <case-id>] [--json <path>]`, stable sorted JSON using
the `ConformanceReport` schema, and exit code `0` for all selected cases passing, `1` for a
conformance failure, or `2` for usage/resolution/preflight failure.

**RED requirements:** repeated runs have identical case order/JSON apart from explicitly
excluded timing fields; unknown plugin/case IDs make zero subject calls and exit `2`; one
failing case exits `1` and names its stable failure code; stdout and `--json` serialize the
same report; no credential/network option exists.

**Output:** a deterministic machine-readable provider-free CLI wrapper around Task 4.1.

### Task 4.3: Import-isolation gate

**Files:**

- Create `tests/shared_runner/test_import_isolation.py`.

**Consumes:** clean subprocesses plus installed core dependencies. **Produces:** a CI gate
and a stable forbidden-import diagnostic for `aeread.sdk.v1`, `aeread.runner`, and
`aeread.runner.conformance`.

**RED requirements:** a subprocess/meta-path sentinel fails if core import attempts any
tau/tau3, Harbor, Docker, Gurobi, OpenAI/Anthropic/other provider SDK, or concrete AERead
family module; it also proves the public SDK/core/conformance surfaces import successfully
when those optional packages are absent. The test does not infer runtime or adapter parity
from import success.

**Output:** a focused import-isolation test gate; no production import-guard layer or
family allowlist is added to the kernel.

### Task 4.4: First live evaluator smoke

**Dependency:** Tasks 4.1–4.3 are independently clean, and the experiment owner supplies
one exact provider API/model revision plus credential through the normal secret channel.
Absence of either is a typed blocked preflight, never permission to use an unpinned alias.

**Files:**

- Create `src/aeread/live_evaluator_smoke.py`.
- Create `configs/shared_runner/live_evaluator_smoke_v1.json` containing the exact
  non-secret evaluator/profile/rubric/prompt pins and budgets used for the run.
- Create `tests/shared_runner/test_live_evaluator_smoke.py` for the driver and guardrails.

**Consumes:** Tasks 3.5–3.12, an evaluator-only fixture with no economic mutation path,
and the pinned profile/config. **Produces:** one ignored run directory containing the
canonical events/artifacts, `ReplayReport`, projections, `EvaluationReceipt`, cost record,
`AttemptChainClosure`, `RunAttemptCoverageManifest`, `AnalysisRecord`, and a
machine-readable smoke summary.

The live envelope is exactly one `RaterAttempt`, at most one provider call, 60 seconds,
256 output tokens, and USD 0.25; exceeding any bound fails the smoke. The driver has no
candidate/economic tool allowlist and performs zero `EnvironmentPlugin.step()` calls.

**RED requirements:** provider-free driver tests reject missing/alias pins, missing rubric/
prompt hashes, absent credential, extra provider calls, economic/tool mutation capability,
budget/cost overflow, unauthorized evaluator visibility, receipt/projection leakage, and a
failed/missing/unknown judgment presented as numeric zero. The actual live command runs
only after these tests and records the exact resolved model/provider response identifiers.

**Output:** one bounded live evaluator infrastructure smoke with receipt/privacy/cost
evidence. It is not provider-free conformance, upstream parity, latency characterization,
or a benchmark-quality/model-quality result.

## Stage 5 — native parity and external compatibility laboratory

### Task 5.1: Exchange parity

Preserve the R6 gate for allocation, `w_real`, denominator/tier, raw AER, failure class,
evidence counts, and replay on provider-free and frozen-response fixtures.

### Task 5.2: `housing_v1` native plugin

Preconditions: observation contract completed by native code or adapter state wrapper;
the false `L=0` outcome-floor wording corrected; landlord response-pass consequences
intentionally defined. Map contact/respond/commit to phases and keep controlled tenant
results separate from population/live-live blocks.

### Task 5.3: Source-only upstream admission audits

Audit pins, materialization, license, official scorer/reference availability, interaction
topology, runtime needs, and execution surface for the five provisional sources. These
audits may run before native parity but make no execution-compatibility claim. Produce
five independently reviewable audit artifacts/commit gates—FinanceBench, AucArena,
Market-Bench, TERMS-Bench, and GDPval—then derive one summary matrix; a blocked source
does not obscure the status of the other four.

### Task 5.4: tau retail adapter spike

Explicit dependency: Tasks 5.1 and 5.2 are independently clean through the same kernel.
Then adapt tau2/tau3 retail pinned to dereferenced `v1.0.1` commit
`fc0055dc4e0a316c3f83133267fbd6faaa770992`: first 1–3 scripted half-duplex tasks, then
the declared 18-task component-parity pilot. Full-duplex is interop/future.

### Task 5.5: Exact objective/tool-loop adapter spike

Explicit dependency: Tasks 5.1 and 5.2 are independently clean through the same kernel.
Then prefer EconEvals Procurement at
`e1f2a40fec96f0d27f5414873c4310f2b5c51935` unless Chenyu supplies a more executable
final representative. FinanceBench, AucArena, Market-Bench, TERMS-Bench, and GDPval stay
source-admission-only until their missing code/license/scorer/judge prerequisites close.

## Mandatory conformance spikes

- Stateless direct API: noop lifecycle + one provider call.
- Persistent API chat: two acts retain context within the episode; the default closes
  then opens fresh between `EpisodeAttempt`s, while optional reset consumes and replaces
  the old session generation.
- Installed CLI subprocess: setup, session, timeout, and finally cleanup.
- Provider→read-only/preview tool→provider: two provider calls plus one tool in one
  action attempt.
- Mutating family action request: remains untrusted `CanonicalResponse` content, creates no
  successful tool row, passes `parse_action()` and `legal()`, then commits only after a
  durable `TransitionStart` through one scheduler `step()`; any provider continuation is a
  new logical action/attempt.
- Retry matrix: restart/continue/forbid exactly follows `SessionPolicy`.
- tau3 scripted half-duplex: assistant/user sessions, normalized family-mutation request
  through parse/legality/transition evidence, terminal DB.
- Harbor/tau whole trial: outer envelope only and `interop_only` admission.
- Harbor runtime backend: same scripted AERead episode has native outcome/score parity.
- Crash matrix: backend start, partial setup, open session, provider, tool, close,
  environment transition, every sole-query reconciliation staging/CAS/materialization
  crash point, cleanup, and backend stop failures reconcile to one strict terminal
  recovery report without re-query, overwrite, or invented authoritative state.
- Capability mismatch: zero backend/runtime/provider/tool calls.
- Privacy: native session IDs and secrets never enter public receipts or projections.
- Isolation matrix: no session, memory, filesystem, process, cache, tool, or private-state
  leakage across default backend/setup/session lease subjects for economic seats,
  evaluator assignments, cells, or attempts.

## Review workflow

For every implementation task: write a meaningful failing test first; implement only the
owning layer; run focused and full suites plus formatting/diff checks; commit one scoped
change; append report/ledger; request independent review; run at most five fix/re-review
rounds before declaring a blocker. No dependent stage advances while P0/P1/P2 findings
remain. This correction is round 5 of 5: any unresolved architecture or P0/P1/P2 finding
is a blocker, not authority for a sixth plan-fix round or hidden implementer discretion.

## Current dispatch gate

Latest PR #7 source `155d8fc` is integrated locally by true merge `b5239cd`, with
compatibility and executable-guard follow-ups through `c7aca60`; the whole runner is not
implemented. Task 1.1a1 is independently clean through `ca173f4`; Task 1.1a2 has candidate
fixes through `a7ddbb2`, with independent review pending. Later tasks advance only through
their declared dependency, RED/GREEN, scoped commit, and independent-review gates.
Provider-free/static evidence is never reported as live runtime, upstream parity, or
benchmark-quality evidence.
