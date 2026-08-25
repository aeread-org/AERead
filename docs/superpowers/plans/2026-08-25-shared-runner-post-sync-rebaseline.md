# Shared Runner Post-Sync Rebaseline Implementation Plan

> **Author:** Codex, for Zeyu Sun  
> **Date:** 2026-08-25  
> **Status:** Task 0.1a is independently P0/P1/P2 clean at `9f7255e`. The local PR #7
> integration merge is clean at `275a285`, and its design-contract fix/re-review is clean
> at `388e52b`; neither commit was pushed or merged to GitHub/main. Dual independent review
> of the first plan correction at `0ea339a` is not clean. Do not dispatch Task 0.3+ until
> this second correction is independently reviewed and
> `.superpowers/sdd/2026-08-25-shared-runner-post-sync-rebaseline/progress.md`
> records a clean verdict; editing this plan does not itself clear that gate.
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
- One `PlanCell` is one intended `Episode`; operational retries create
  `EpisodeAttempt`, not an independent statistical cluster.
- Planned `Episode` replicates and judgment slots are statistical identities;
  `EpisodeAttempt` and `RaterAttempt` are operational children and never add counts.
- Every AERead-initiated or adapter-declared observable atomic side effect has a durable
  start record and exactly one terminal `succeeded`, `failed`, or `outcome_unknown`
  record. An opaque upstream trial promises this only for its outer trial operation and
  explicitly declares its internal provider/tool operations unobserved.
- Valid zero or negative economics never become missing/corrupt evidence.
- Judge calls are recorded evaluator work; `VerifierPlugin.score()` stays deterministic.
- Transition/reconciliation policy and state materialization are resolved and hashed before
  execution; an unknown mutation never implies an authoritative state.
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

Complete locally. Merge commit `275a285` incorporates PR #7 commit `6bb07aa`; corrective
commit `388e52b` aligns the merged design, public executable boundary, roadmap taxonomy,
and design-contract tests. The scoped re-review is clean. No implementer should repeat this
merge, push it, or merge it to GitHub/main under this plan.

### Task 0.3: Migrate the serialized planning identity to `PlanCell`

**Dependency:** the progress ledger records a clean verdict for this corrected plan, and
the ignored
`.superpowers/sdd/2026-08-25-shared-runner-post-sync-rebaseline/task-0.3-brief.md`
is then regenerated from that exact clean plan before dispatch. The brief present at
`0ea339a` is stale and must not be dispatched or edited as part of this plan-fix commit.

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

### Task 1.1a: Freeze the reusable family measurement leaf and pure verifier boundary

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py` for strict records, Protocols, and stable exports.
- Modify `src/aeread/runner/registry.py`; create
  `src/aeread/runner/verifier_artifacts.py` for the read-only artifact port.
- Modify `docs/shared_runner_design.md`, `docs/verifier_taxonomy.md`,
  `docs/walkthroughs/shared_runner_architecture_roadmap.md`, and
  `docs/public_environment_and_external_adapter_spec.md` to freeze the same ownership and
  pure-scorer signature.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/test_registry.py`,
  `tests/shared_runner/fakes.py`, and `tests/test_shared_runner_design_contract.py`; create
  `tests/shared_runner/test_verifier_conformance.py` and
  `tests/shared_runner/test_verifier_artifacts.py`.

This slice owns only reusable family semantics. Define the strict replacement target
`MeasurementLeafSpec`: stable leaf ID/version, one
`EstimandSpec`, exactly one of the five semantic verifier/reference variants, one allowed
evaluation-mode class (`deterministic`, `stochastic_estimator`, or `judge_dependent`), a
pinned scorer implementation, and `composition_kind: Literal["leaf"]`. The family leaf
must not contain a panel, sample size, cluster mapping, pairing, planned repetitions,
judgment slots, concrete evaluator profile, estimator, interval, missingness rule, or
paper composition. Those are suite-owned in Task 1.1b.
Do not wire the new record into or version-bump `FamilyManifest` in this slice; Task 1.1c
is the sole manifest migration owner, so 1.1a can be reviewed without a half-migrated
serialized family identity.

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

Add a read-only `AuthorizedArtifactResolver`/`AuthorizedArtifactView`. It is constructed
from the exact `ArtifactRef` allowlist bound by the measurement contract, verifies digest,
media type, and byte length against the content-addressed store before returning bytes,
and rejects undeclared or mismatched references. It exposes no write, provider, runtime,
tool, or network method. Freeze the pure scoring boundary as an equivalent bind step:

```python
class ResolvedMeasurementContract(Protocol):
    measurement_sha256: SHA256
    leaf: MeasurementLeafSpec

class BoundVerifier(Protocol):
    measurement_sha256: SHA256

    def score(
        self,
        case: FamilyCase,
        outcome: FamilyOutcome,
        evidence: SealedEvidenceView,
        artifacts: AuthorizedArtifactView,
    ) -> ScoreEnvelope: ...

class VerifierPlugin(Protocol):
    implementation: ImplementationRef

    def bind(
        self,
        measurement: ResolvedMeasurementContract,
        artifacts: AuthorizedArtifactResolver,
    ) -> BoundVerifier: ...
```

Task 1.1c's `ResolvedMeasurementDesign` satisfies
`ResolvedMeasurementContract`; binding must reject a leaf/hash/implementation mismatch.
Both bind and score are provider-free and side-effect-free. Registered verifier fakes and
conformance probes must raise if a scorer tries to resolve an undeclared artifact or
touches network/provider/write ports.

**RED requirements:** schema tests construct all five reference families and every
reference-kind discriminator above, and reject incompatible or incomplete fields. Each
objective reference fails on any full-scope mismatch. Rater schemas reject ambiguous
source, unpinned renderer/order/calibration/provenance, or an untyped visibility payload,
but accept a valid tie. Registry tests reject an implementation/hash mismatch. Artifact
tests reject traversal, non-allowlisted refs, digest/media-type/length mismatch, mutation,
and every write/network/provider surface; a bound fake scores the same sealed inputs and
authorized bytes byte-identically with zero external calls.

**Output:** one family-owned `MeasurementLeafSpec` with complete five-family typed
reference semantics, a registered pure `BoundVerifier` contract, and a read-only
content-addressed allowlisted artifact boundary—no suite statistical choices.

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
and panel/selection rule, `ClusterSpec`, `PairingSpec`, planned episode replicates,
evaluation-mode binding, method-specific estimator and interval, transformation,
missingness, evaluator/imported-evidence assignment where required, and an analysis block
ID. It contains no family scorer implementation and cannot redefine an estimand,
verifier, reference, or allowed evaluation class.
Do not wire this binding into or version-bump `SuiteManifest`, `PlanCell`, or `RunPlan` in
this slice; Task 1.1c owns that one atomic serialized migration.

Statistical identity is planned rather than inferred from operational rows:

- `PlannedEpisodeReplicate` is one intended `Episode` slot nested in its declared
  independently sampled cluster. `EpisodeAttempt` is an operational child of that slot;
  retries never add a replicate, planned episode, pair, or cluster count.
- `PlannedJudgmentSlot` is one intended rating for a leaf/episode/presentation position.
  `RaterAttempt` is an operational child serving that slot. Replacement attempts retain
  the same judgment-slot/cluster identity, and at most one accepted terminal judgment per
  slot contributes to aggregation.
- judgment-slot count and evaluator stochasticity exist only in a
  `JudgeDependentEvaluationBinding` carrying the typed rater protocol. The non-judge
  `StochasticEstimatorEvaluationBinding.stochastic_sources` is a non-empty set drawn only
  from `environment | counterpart | candidate`; it has neither `judge` nor `combined`.

Replace the bare estimator target enum with a discriminator union:

- `MeanEstimatorSpec` binds the metric and weighting rule;
- `DifferenceEstimatorSpec` binds subject/comparator arm IDs, the comparison direction,
  and the exact `PairingSpec`/pair keys it consumes;
- `ProbabilityEstimatorSpec` binds a typed, versioned success predicate and denominator;
- `QuantileEstimatorSpec` binds metric, `q` strictly in `(0, 1)`, and interpolation rule;
- `PassAllKEstimatorSpec` binds a positive `k`, success predicate, planned-replicate group
  keys, and means exactly `1` iff all and exactly the `k` planned episode slots in each
  complete group succeed; missing or extra slots follow the declared missingness rule and
  cannot silently change `k`.

V0 interval is a method-specific union only: `NoIntervalSpec(method="none")` has no
confidence or resampling fields; `ClusterBootstrapIntervalSpec` requires confidence,
draw count, seed, and the declared cluster ID as its resampling unit;
`PairedRandomizationIntervalSpec` requires confidence, exact-or-bounded permutation
count, seed, test statistic, and the pairing keys/assignment mechanism it randomizes.
Cluster-robust and hierarchical intervals are deferred. A validator never requires fake
cluster resampling fields for `none` or paired randomization.

Missingness is fail-closed and typed: `invalidate_required` forbids numeric output when a
required planned unit is missing/failed/unknown; a predeclared partial estimator names its
positive minimum valid planned units and denominator treatment; neither may drop rows or
impute economic zero. A rater binding additionally freezes aggregation, valid tie
treatment, minimum valid judgment slots, disagreement output, and concrete assignment.
`EvaluatorAgentAssignment` pins one evaluator profile per judgment slot and its authorized
projection; `ImportedHumanAssignment` pins the collection/provenance artifact and maps
records to planned slots. Neither becomes an environment seat.

**RED requirements:** tests reject `EpisodeAttempt`/`RaterAttempt` as replicate or
judgment identity fields, reject replacement as a new count, and reject more than one
accepted judgment per planned slot. Each estimator variant fails when its method-specific
parameter is absent or inconsistent; pass-all-k cases cover complete success, one
failure, missing, and extra planned slots. Interval tests cover the three exact V0
variants and reject cluster-robust/hierarchical payloads or fake resampling fields.
Judge variation without a rater protocol, ambiguous `combined`, unauthorized visibility,
incomplete evaluator/imported-human assignment, implicit drop, and zero imputation all
fail before evaluator/provider/runtime work.

**Output:** one suite-owned, strictly typed statistical/evaluation binding whose planned
episode and judgment slots are distinct from operational attempt identities.

### Task 1.1c: Resolve one measurement design, minimal composition, and schema migrations

**Dependency:** Tasks 1.1a and 1.1b are independently clean.

**Files:**

- Modify `src/aeread/runner/planning.py` and `src/aeread/runner/registry.py`.
- Modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py` only for the
  resolved records, composition declarations, and versioned manifest/plan fields.
- Modify `docs/shared_runner_design.md`, `docs/verifier_taxonomy.md`, and
  `docs/walkthroughs/shared_runner_architecture_roadmap.md`; guard the ownership,
  identity, composition, and hash rules in `tests/test_shared_runner_design_contract.py`.
- Modify `tests/shared_runner/test_planning.py` and
  `tests/shared_runner/test_planning_adversarial.py`; create
  `tests/shared_runner/test_measurement_resolution.py`.

For every evaluation block, resolve exactly one family `MeasurementLeafSpec` plus exactly
one compatible `SuiteMeasurementBinding` into one immutable
`ResolvedMeasurementDesign` stored directly in `PlanCell`. It contains the leaf and suite
IDs/versions/hashes; allowed and selected evaluation classes; exact reference and
authorized-artifact set; sampling/panel, cluster, pair, planned episode and judgment-slot
identities; estimator, interval, transformation, missingness, evaluator assignment, and
analysis-block ID. Its canonical `measurement_sha256` covers every field, and the
`BoundVerifier` carries that exact digest.

Validation is exact and rejects rather than overwrites: missing or duplicate leaf/binding,
estimand mismatch, selected mode outside the leaf allowance, family/suite reference drift,
incompatible paired estimator, unresolved artifact/profile/implementation, or more than
one cluster mapping for a leaf/block. Changing a paper panel, replicate count, pairing,
interval, missingness rule, evaluator assignment, or composition must leave the family
leaf bytes/hash unchanged while changing the suite manifest, resolved measurement,
`PlanCell`, and `RunPlan` bytes/hashes.

Composition is declaration-only in V0. `SuiteManifest.compositions` may declare
`vector`, `hybrid_gate`, `weighted`, or `judge_augmented` over a non-empty unique tuple of
existing leaf `block_id` values. A component may not reference another composition, so
nesting and cycle traversal do not exist. Validate and hash declarations only; aggregate
execution and scalar publication are deferred. Weighted declarations still bind exact
rational weights, pinned transforms, units, decision problem, and sensitivity declaration;
otherwise keep a vector. Composition never changes leaf validity/inclusion, never claims
shared evidence without a separately resolved paired design, and never becomes an
execution/admission gate.

Make the breaking migration explicit with no automatic legacy parser:
`FamilyManifest` becomes `aeread.family/0.2`, `SuiteManifest` becomes
`aeread.suite/0.2`, `PlanCell` becomes `aeread.plan_cell/0.2`, and `RunPlan` becomes
`aeread.run_plan/0.3`. Legacy family-owned evaluation/composition payloads and the
Task 0.3 plan versions fail closed.

**RED requirements:** construct every allowed leaf/mode binding and mutation-test every
resolved field. `test_suite_design_change_does_not_change_family_identity` changes panel
and interval independently, proves identical family bytes/hash, and proves changed suite,
measurement, cell, and run-plan hashes. Resolution rejects every duplicate/conflict named
above. Composition accepts direct leaf block IDs, rejects missing/duplicate/non-leaf
components and undeclared scalar semantics, and has no executable aggregation port.
Migration tests assert all four exact versions and reject prior payloads. The unauthorized
rater preflight remains zero-side-effect evidence only; Tasks 3.5–3.7 own evaluator work.

**Output:** one hashed `ResolvedMeasurementDesign` per `PlanCell`, exact family/suite
ownership, declaration-only leaf composition, and explicit versioned migrations.

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
resolve to a plan, bind the authorized artifacts, and fail its neighboring invalid input
before filesystem mutation, runtime start, evaluator work, or provider call.

**RED requirements:** each valid fixture selects its intended reference discriminator,
evaluation binding, cluster/pair/planned-slot identities, and hash; its invalid neighbor
fails only the targeted contract. Dependency fakes raise if any runtime/provider/network/
write port is touched. The rater case aggregates only canned accepted planned judgment
slots and proves a replacement attempt cannot add a judgment.

**Output:** five provider-free conformance fixtures proving contract expressibility—not
upstream parity, interval adequacy, or benchmark quality.

## Stage 2 — correct agent lifecycle and side-effect contracts

### Task 2.1: Replace retired call-attempt vocabulary and freeze transition recovery policy

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py`.
- Modify `src/aeread/runner/planning.py` for plan-time transition-policy resolution and
  hashing only; recovery execution remains Task 3.9.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/test_registry.py`, and
  `tests/shared_runner/fakes.py`; modify `tests/shared_runner/test_planning.py` and create
  `tests/shared_runner/test_transition_contracts.py`.
- Modify the authoritative `AttemptObserver`, environment materialization boundary, and
  executable action/recovery examples in
  `docs/public_environment_and_external_adapter_spec.md`, `docs/shared_runner_design.md`,
  and `docs/walkthroughs/shared_runner_architecture_roadmap.md`; guard them in
  `tests/test_shared_runner_design_contract.py`.

This task owns the public records, discriminated unions, Protocols, stable exports, schema
versions, and conformance fakes only. Tasks 3.1, 3.3, and 3.9 own scheduler, attempt, and
transition/reconciliation execution. The only action/mutation path is:

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

EnvironmentTransition
  -> TransitionStart
  -> TransitionCheckpoint 0..n
  -> TransitionSucceeded | TransitionFailed | TransitionOutcomeUnknown

TransitionOutcomeUnknown
  -> TransitionReconciliationStart
  -> TransitionReconciliationCommitted
     | TransitionReconciliationNotCommitted
     | TransitionReconciliationStillUnknown
```

The names `CallAttemptStart` and `CallAttemptToken` below are **retired migration names**,
not compatibility exports: rename their serialized/public executable forms to
`ProviderCallStart` and `ProviderCallToken`. Add
`ActionAttemptStart` plus
`ActionAttemptSucceeded | ActionAttemptFailed | ActionAttemptOutcomeUnknown`, and the
analogous strict `succeeded | failed | outcome_unknown` terminal union for each provider
call, tool, evaluator, and runtime operation. Add
`ToolInvocationStart` and its strict terminal union, with stable parent
IDs, canonical hashes, tool/version pins, idempotency/reconciliation capability,
typed `family_read_only | harness_internal | transactional_preview` execution scope, and
result/state-diff artifact refs.
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

Before any execution, the resolver must select one strict `TransitionPolicySpec` for every
`PlanCell`, store it in that cell, and cover it in the `PlanCell`/`RunPlan` canonical hash.
The policy binds a stable policy ID/version, the pinned `TransitionReconciler`
`ImplementationRef`, idempotency semantics (`runner_copy_on_write` or
`external_idempotency_key`), reconciliation-query semantics
(`deterministic_local_replay`, `same_key_read_only_replay_safe`, or
`single_query_no_replay`), positive maximum transition and reconciliation attempts, and
exactly one state-materialization strategy:
`CanonicalStateArtifactStrategy` with its state schema/version or
`TransitionResultArtifactStrategy` with its result schema/version. Admission exact-matches
the selected strategy and query/idempotency semantics to environment capabilities.
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
    query_semantics: Literal[
        "deterministic_local_replay",
        "same_key_read_only_replay_safe",
        "single_query_no_replay",
    ]
    max_transition_attempts: PositiveInt
    max_reconciliation_attempts: PositiveInt
    state_materialization: StateMaterializationStrategy
```

This is a breaking plan migration: after Task 1.1c, `PlanCell` becomes
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
    transition_idempotency_key: str
    transition_policy_sha256: SHA256
    reconciler: ImplementationRef

class TransitionReconciliationRequest(StrictModel):
    reconciliation_attempt_id: str
    transition_id: str
    transition_idempotency_key: str
    transition_policy_sha256: SHA256
    outcome_unknown_event_id: str
    prior_state_version: str
    prior_state_sha256: SHA256

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
    proof_artifact_ref: ArtifactRef
    reason_code: Literal[
        "query_not_replay_safe",
        "reconciler_failed",
        "proof_inconclusive",
        "attempt_bound_exhausted",
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
        self, request: TransitionReconciliationRequest
    ) -> TransitionReconciliationTerminal: ...

class EnvironmentPlugin(Protocol):
    def materialize_reconciled_state(
        self,
        case: FamilyCase,
        prior_state: FamilyState,
        materialization: CommittedStateMaterialization,
        artifacts: AuthorizedArtifactView,
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
`transition_id`, repeats its exact idempotency key, pins the reconciler, and is durably
written before any reconciliation query/side effect. One start receives exactly one
terminal, every terminal binds a content-addressed proof artifact, and the original
transition terminal is never overwritten. Neither a transition attempt nor a
reconciliation attempt may publish a second terminal.

`committed` carries both the authoritative state version/hash and a restorable canonical
state or transition-result artifact. The runner allowlist-resolves its bytes, calls only
the pinned environment's deterministic `materialize_reconciled_state()` boundary, then
hashes the returned state and exact-matches the authoritative version/hash before resume;
it never reissues `step()`. `not_committed` carries the authoritative *prior* state
version/hash, which the chain validator must prove exactly equal to the original
`TransitionStart` prior version/hash before a new transition ID/start may be authorized
under the resolved retry bound. `still_unknown` carries proof and reason only—no
authoritative state version/hash or materialization—and quarantines/invalidates the cell.
A query crash may be
replayed under the same reconciliation-attempt ID only when the plan says the exact query
is replay-safe; otherwise it becomes `still_unknown`.

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

**RED requirements:** retired active executable imports, exports, schema discriminators,
and authoritative public-spec signatures using `CallAttemptStart`/`CallAttemptToken` fail;
explicitly labeled historical/negative migration prose may retain the strings. Record tests
reject mismatched parent IDs, missing pins/hashes, second terminal construction in a
conformance fake, a policy missing any reconciler/idempotency/query/retry/materialization
field, or a transition whose policy hash differs from its cell. Reconciliation tests
reject committed without restorable materialization or a matching authoritative state,
committed materialization whose kind/schema differs from the resolved strategy,
not-committed whose prior state differs from the original start, and still-unknown with
any authoritative-state field. Recovery-report tests cover all four terminal variants,
reject an empty referenced chain where recovery occurred, and reject a not-committed retry
without one final recorded disposition. Exact schema-version and hash-mutation tests cover
the Task 1.1c-to-Task 2.1 `PlanCell`/`RunPlan` migration.
The public design-contract RED asserts the exact response -> parse -> legality ->
transition path and rejects language allowing adapters/attempts/tools to create an
`ActionEnvelope` or execute a requested family mutation. Runtime no-envelope/no-tool-
success/no-step-before-parse-and-legality RED belongs to Tasks 3.1 and 3.3.

**Output:** one versioned public evidence vocabulary rooted in `ActionAttempt`,
`ProviderCall`, actual `ToolInvocation`, `RaterAttempt`, lifecycle operations, environment
transitions, append-only reconciliation, a plan-bound transition policy, deterministic
state materialization, and a terminal `RecoveryReport`, with no active serialized
`CallAttempt*` or receipt-facing `RecoveryDecision` identity.

### Task 2.2: Add episode-scoped harness lifecycle

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py`.
- Modify `tests/shared_runner/fakes.py`.
- Create `tests/shared_runner/test_agent_lifecycle_contract.py`.

This task owns lifecycle capability/policy/operation records, Protocols, stable exports,
and scripted conformance fakes only. It does **not** create or partially implement a
lifecycle coordinator; Task 3.2 is the sole owner of orchestration and cleanup execution.

Minimum lifecycle:

```text
ExecutionBackend.start
  -> AgentAdapter.setup
    -> AgentAdapter.open_session
      -> AgentSession.act*
      -> AgentSession.reset / close
    -> AgentAdapter.cleanup
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

Backend/setup generations are scoped as explicitly as sessions. The conservative default
lease key is `(episode_attempt_id, seat_id)` for backend, adapter setup, and session. Reuse
across seats/cells/attempts requires declared state-containment plus reset/cleanup
capability, capability preflight, and a receipt-visible treatment declaration covering
filesystem, process, cache, memory, and tool state. Session isolation alone never proves
runtime isolation.

Default session scope is `(episode_attempt_id, seat_id)`. Across EpisodeAttempts the
default is close plus a fresh open. An optional
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
idempotent, runs in `finally`, and quarantines a runtime whose cleanup fails. Stateless
HTTP adapters use a trivial session; persistent CLI/API adapters use the same boundary.

Define a runner-owned `ToolMediator` port and pass it to `AgentSession.act()`. It validates
seat/phase tool allowlists for operations that may actually execute inside an attempt,
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
adapter/backend/request capabilities, an unscoped lease key, reuse without containment and
reset/cleanup capability, an unobservable continuation policy, or more than one terminal
choice for a session generation. Scripted fakes expose backend-start, partial-setup,
open-session, reset, close, cleanup, backend-stop, timeout, failure, and
`outcome_unknown` outcomes without orchestrating them. The `ToolMediator` fake rejects a
requested family mutation and can execute only read-only, harness-internal, or
transactional-preview operations. Task 3.2 consumes these fakes for the runtime failure
matrix.

**Output:** versioned lifecycle/capability/session/tool-mediation contracts and reusable
scripted fakes, with no coordinator implementation in this task.

### Task 2.3: Freeze whole-trial admission semantics without implementing a protocol

Reuse the existing `CapabilityDeclaration.schedule_control` discriminator; do not create
a duplicate `execution_surface` enum or export an unconformed `UpstreamTrialAdapter` in
SDK v1. Freeze admission semantics only, and copy resolved capabilities into receipts:

| schedule control | execution surface | default admission |
|---|---|---|
| `runner` | native `EnvironmentPlugin` phase/observe/step | may apply for paper/training |
| `upstream` | stepwise upstream `advance()` | parity/interop until stronger checks |
| `opaque` | `UpstreamTrialAdapter.run_trial()` | `interop_only` |

An opaque trial maps to one AERead `EpisodeAttempt`; its logs/trajectory are imported
artifacts/projections, never fabricated native events. Only the outer
`upstream_trial_started -> succeeded|failed|outcome_unknown` operation is native evidence.
Upstream retries must be disabled, exposed one-by-one, or declared opaque; hidden multiple
trials cannot be presented as one clean attempt. No fake child provider/tool rows.

## Stage 3 — implement execution on the corrected contract

### Task 3.1: Provider-free phase scheduler against an executor port

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
version/hash. Admission and every transition start exact-match the `PlanCell` transition-
policy hash; replay/resume rejects a missing, duplicate, or contradictory terminal row and
Task 3.9 alone may reconcile an unknown transition.

### Task 3.2: Episode/session lifecycle coordinator

**Files:**

- Create `src/aeread/runner/lifecycle.py`.
- Modify `src/aeread/runner/__init__.py` only to export the completed coordinator surface.
- Create `tests/shared_runner/test_lifecycle.py`.

**Consumes:** Task 2.2's lifecycle capability/policy/operation records, Protocols, and
scripted fakes. **Produces:** `EpisodeLifecycleCoordinator.preflight(...) ->
LifecycleLeasePlan`, `start_attempt(...) -> EpisodeLifecycle`,
`borrow_session(seat_id) -> AgentSessionLease`, and `finalize_attempt(...) ->
LifecycleFinalization`. This is the only task that implements lifecycle orchestration.

Implement fail-closed preflight and cleanup ownership with scripted adapters/backends.
Default isolation closes each session at episode-attempt scope and opens fresh on the next
attempt. Optional reset consumes the old session generation and returns a new generation;
it is never an implicit `ActionAttempt` retry. Action-attempt restart instead uses
coordinator-owned fresh generation plus safe checkpoint/restore or side-effect-free
canonical prefix replay.

**RED requirements:** capability mismatch causes zero backend/provider/tool calls;
backend-start, partial-setup, open-session, reset, close, cleanup, and backend-stop
failure/timeout/`outcome_unknown` paths each close exactly one started lifecycle operation.
A failed or unknown reset never reuses the old generation. Exactly one finalizer owns each
live generation; the action executor cannot close/reset/cleanup it. Default lease keys
prevent backend/setup/session/process/filesystem/cache/memory/tool state from crossing
seat/cell/attempt boundaries. Native session IDs and secrets never enter public evidence
or receipts, and action-attempt restart never replays economic/tool side effects.

**Output:** a runner-owned, episode-attempt-scoped coordinator with typed preflight,
leases, generation consumption, quarantine, and idempotent `finally` cleanup.

### Task 3.3: Action-attempt executor

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

Integrate Task 3.1's scheduler with Tasks 3.2–3.3 without adding family branches.
Single-agent, controlled counterpart, population, and live-live use the same kernel.

### Task 3.5: Judge plan, authorized input, and evaluator hierarchy

**Files:**

- Create `src/aeread/runner/evaluation.py` and
  `tests/shared_runner/test_evaluation.py`.
- Modify the verifier/evaluator-authorized-input prose and Protocol example in
  `docs/public_environment_and_external_adapter_spec.md`; modify
  `tests/test_shared_runner_design_contract.py` to guard it. Task 3.7 separately owns the
  executable final-seal ordering in that document.

Add `EvaluationWork` plus `RaterAttempt`; rater provider calls belong to measurement/
evaluator work, not candidate `LogicalAction`s. Only after `EnvironmentPlugin.terminal()`
and `outcome()` produce the terminal `FamilyOutcome`, validate the resolved judge source,
concrete assignment, capability, and visibility; render the exact authorized projection;
store/hash that artifact; and produce
`build_evaluation_plan(...) -> EvaluationWorkPlan` while the event store remains open.
Every work item references one planned judgment slot, resolved measurement hash,
rubric/protocol, renderer, blind-order seed/counterbalance, and authorized-input artifact.

**RED requirements:** the authoritative spec and static guard reject the old
terminal-outcome -> immediate-seal path and require terminal outcome -> authorized
evaluator planning/work while the log is open. Pre-terminal evaluator planning,
unauthorized fields, assignment/slot drift, or artifact-hash drift fails before any
`EvaluationWork`, `RaterAttempt`, provider, or tool call. Evaluators never become economic
seats, and a request may not widen the resolved projection.

**Output:** a typed, provider-free evaluator work plan over frozen authorized inputs plus
its runner-owned artifact/event evidence and public pre-seal placement contract; no
evaluator execution in this task.

### Task 3.6: Pure recorded-rater aggregation

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
terminal FamilyOutcome
  -> authorized EvaluationWork/RaterAttempt execution while event log is open
  -> append every judgment terminal and close evaluator work
  -> final evidence seal
  -> measurement-bound BoundVerifier.score(case, outcome, sealed evidence, authorized artifacts)
  -> replay/projections -> EvaluationReceipt
```

A seal never precedes required evaluator work, and a sealed store never reopens for judge
output. No live-provider smoke is authorized by this task.

**RED requirements:** the authoritative public example and static guard require the exact
order above and reject seal-before-judge, judge-after-seal, provider calls from the bound
verifier, and receipt-before-score. Execution tests cover failed/missing/
`outcome_unknown` judgment attempts, replacement under a new `RaterAttempt` identity for
the same planned judgment slot, at most one accepted contribution per slot, exact
authorized-input artifact hash, blind ordering, evaluator/imported-human provenance,
disagreement, valid tie handling, and the partial-estimator threshold.

**Output:** provider-free scripted evaluator execution whose complete evidence is sealed
once before pure scoring, with the authoritative public flow guarded statically.

### Task 3.8: Deterministic replay validation

**Files:**

- Create `src/aeread/runner/replay.py`.
- Create `tests/shared_runner/test_replay.py`.

**Consumes:** `PlanCell`, including its resolved transition policy and measurement design,
the full `SealedEvidenceView`, content-addressed artifacts, the pinned
`EnvironmentPlugin`, and the pure `ScoreEnvelope`. **Produces:**
`validate_replay(...) -> ReplayReport`, where the immutable typed report records
`status`, requested/achieved replay level, transition/event coverage counts, terminal
state version/hash, score hash, and an optional typed first divergence. Its canonical
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

**Files:**

- Create `src/aeread/runner/recovery.py`.
- Create `tests/shared_runner/test_recovery.py`.

**Consumes:** Task 2.1 transition/reconciliation records, exact plan-resolved
`TransitionPolicySpec`, pinned `TransitionReconciler`, validated open event chain,
read-only authorized artifact resolver, environment materialization hook, and Task 3.2
quarantine/lifecycle hooks. **Produces:**
`reconcile_transition(...) -> TransitionReconciliationTerminal`, an internal runner-only
`ResumeInstruction` used immediately by the coordinator, and
`finalize_recovery(...) -> RecoveryReport`. Normal paths use
`not_required_recovery(...) -> RecoveryReport(status="not_required")`. The internal
instruction is not an SDK export, serialized public identity, or receipt input.

Resume only from reconciled durable boundaries. For `committed`, allowlist-resolve the
declared state/result artifact, invoke `materialize_reconciled_state()` with the original
prior state, exact-match the returned canonical version/hash, and continue without
reissuing `EnvironmentPlugin.step()`. For `not_committed`, first prove its authoritative
prior version/hash equals the original `TransitionStart`; then allow a retry only by
allocating a new `transition_id`, durably writing a new policy-hash-bound
`TransitionStart`, and staying within the resolved transition/reconciliation attempt
bounds. For `still_unknown`, quarantine and invalidate the cell; it has no authoritative
state to resume, and no retry/new operational attempt may claim the mutation is safe. The
original `TransitionOutcomeUnknown` remains in the append-only log.

**RED requirements:** parameterize all three terminal outcomes and crash points (before
reconciliation start; after durable start but before the reconciler call; during/after the
call but before terminal append; and after terminal append but before control-flow
continuation). A start without terminal is resumed under the same reconciliation-attempt
ID only when the *resolved policy* declares the exact same-key query replay-safe;
otherwise it closes once as `still_unknown` and quarantines. Tests reject retry or resume
before reconciliation, a second reconciliation start used to evade an unfinished one, a second
or contradictory transition/reconciliation terminal, terminal overwrite, missing proof,
changed idempotency key/reconciler/policy pin, committed materialization whose bytes or
returned state do not match, not-committed prior-state inequality, still-unknown with an
authoritative state, exhausted bounds, and any `step()` call on the `committed` or
`still_unknown` paths. The `not_committed` path proves the old transition is not reused,
the new attempt is recorded before its one allowed `step()`, and its final succeeded or
failed terminal is referenced by the report. A retry that becomes unknown must complete a
new allowed reconciliation or yield a quarantined report.

**Output:** append-only, crash-safe recovery that closes each transition and
reconciliation attempt exactly once and emits one terminal `RecoveryReport` binding the
complete referenced chain, including `not_required` for normal runs.

### Task 3.10: Public/private projections

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

**Files:**

- Create `src/aeread/runner/finalize.py`.
- Modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py` only for the
  version-bumped final `EvaluationReceipt` schema/export.
- Create `tests/shared_runner/test_receipt.py`.

**Consumes:** sealed evidence, pure score/typed measurement failure, Task 3.8
`ReplayReport`, Task 3.9 terminal `RecoveryReport`, Task 3.10 `ProjectionSet`, and the
resolved `RunPlan`/`PlanCell`. **Produces:** `finalize_episode(...) -> EvaluationReceipt`
and an atomic canonical receipt file whose `receipt_sha256` excludes only its own digest
field.

Only after seal/pure score, replay validation, final recovery state, and projections,
create the immutable receipt. It binds plan/case, candidate, counterpart and judge
configurations, runtime/tools, environment/parser/verifier/reference pins, the complete
resolved measurement and transition-policy hashes, evidence roots, replay result/coverage/
report hash, the terminal recovery status and referenced transition/reconciliation chain,
admission/observability, exact planned cluster/pair/episode-replicate/judgment-slot
identity (never attempt counts), projection and per-seat trajectory refs, score or typed
failure, and inclusion. Secret/native session identifiers are excluded.

**RED requirements:** finalization rejects unsealed evidence, an unfinished transition or
reconciliation, a missing/nonterminal `RecoveryReport`, absent/mismatched replay/
projection/measurement/transition-policy hashes, cluster or plan identity drift,
an invalid score paired with numeric output, and any secret/native session identifier in
the public receipt. A scorer/judge/recovery failure produces `invalid_measurement` with no
numeric zero imputation. Receipt publication is atomic/idempotent for identical canonical
bytes and refuses a different second receipt for the same episode attempt. Hash mutation
tests cover every candidate/counterpart/judge/runtime/tool/plugin/reference/evidence/
replay/recovery-chain/transition-policy/cluster/planned-slot/projection/score/inclusion
field. The four recovery statuses are receipt-distinct; `quarantined` always has
`invalid_measurement` and no numeric score, while a valid `not_required` report is
mandatory for an uninterrupted run.

**Output:** one immutable, hash-verifiable `EvaluationReceipt` per finalized episode
attempt, or a typed pre-publication failure if the finalization contract is incomplete.

## Stage 4 — provider-free conformance

### Task 4.1: Conformance library

**Files:**

- Create `src/aeread/runner/conformance.py`.
- Create `tests/shared_runner/test_conformance.py`.

**Consumes:** stable SDK/kernel interfaces and scripted fixtures only. **Produces:**
`run_conformance(subject, selection) -> ConformanceReport`, an importable deterministic
library API with named case results and no provider credentials/network dependency.

The provider-free matrix covers strict manifests; all five verifier leaves and three
evaluation modes; the read-only authorized-artifact scorer boundary; exact cluster/pair/
planned-episode/planned-judgment mapping with operational attempts excluded; sequential/
simultaneous/multi-channel scheduling; channel cardinality and atomic bundles; privacy; malformed/illegal/
missing/timeout actions; the no-mutation-before-parse/legal boundary; actual tool evidence;
session cleanup/isolation; judge visibility, pre-seal evaluator work, final-seal ordering,
and fail-closed missingness; all transition-policy, materialization, reconciliation, and
terminal recovery-report outcomes; deterministic replay; receipt integrity; and valid
zero/negative economics.

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

**Consumes:** Tasks 3.5–3.11, an evaluator-only fixture with no economic mutation path,
and the pinned profile/config. **Produces:** one ignored run directory containing the
canonical events/artifacts, `ReplayReport`, projections, `EvaluationReceipt`, cost record,
and a machine-readable smoke summary.

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
  environment transition, every transition-reconciliation/materialization crash point,
  cleanup, and backend stop failures reconcile to one strict terminal recovery report
  without overwrite or invented authoritative state.
- Capability mismatch: zero backend/runtime/provider/tool calls.
- Privacy: native session IDs and secrets never enter public receipts or projections.
- Isolation matrix: no session, memory, filesystem, process, cache, tool, or private-state
  leakage across default backend/setup/session lease keys for seats/cells/attempts.

## Review workflow

For every implementation task: write a meaningful failing test first; implement only the
owning layer; run focused and full suites plus formatting/diff checks; commit one scoped
change; append report/ledger; request independent review; run at most five fix/re-review
rounds before declaring a blocker. No dependent stage advances while P0/P1/P2 findings
remain.

## Current dispatch gate

The foundation and local PR #7 integration are clean through `388e52b`; the whole runner
is not implemented, and dual review found `0ea339a` non-dispatchable. Task 0.3+ remains
blocked until an independent review finds this second correction P0/P1/P2 clean and the
progress ledger records that verdict. Only then may the ignored stale Task 0.3 brief be
regenerated from the clean plan and dispatched. Thereafter each task advances only through
its declared RED/GREEN, scoped commit, and independent-review gate; provider-free/static
evidence is never reported as live runtime, upstream parity, or benchmark-quality
evidence.
