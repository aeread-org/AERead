# Shared Runner Post-Sync Rebaseline Implementation Plan

> **Author:** Codex, for Zeyu Sun  
> **Date:** 2026-08-25  
> **Status:** Task 0.1a is independently P0/P1/P2 clean at `9f7255e`. The local PR #7
> integration merge is clean at `275a285`, and its design-contract fix/re-review is clean
> at `388e52b`; neither commit was pushed or merged to GitHub/main. The fresh rebaseline-
> plan review at `388e52b` is not clean. Do not dispatch Task 0.3+ until this correction is
> independently reviewed and `.superpowers/sdd/2026-08-25-shared-runner-post-sync-rebaseline/progress.md`
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
- Every AERead-initiated or adapter-declared observable atomic side effect has a durable
  start record and exactly one terminal `succeeded`, `failed`, or `outcome_unknown`
  record. An opaque upstream trial promises this only for its outer trial operation and
  explicitly declares its internal provider/tool operations unobserved.
- Valid zero or negative economics never become missing/corrupt evidence.
- Judge calls are recorded evaluator work; `VerifierPlugin.score()` stays deterministic.
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

**Dependency:** the progress ledger records a clean verdict for this corrected plan.

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
exports, schemas, and fixtures. Add `record_type: Literal["plan_cell"]` and an exact
`spec_version`, and bump the enclosing `RunPlan` schema. A compatibility alias may exist
only at the Python import surface; it must not introduce a second serialized identity or
hash basis. If retained, `EpisodeCell = PlanCell` is the only permitted compatibility
shape: instances created through either import serialize with `record_type="plan_cell"`
and the `PlanCell` schema/version. The retired name is forbidden in authoritative public
type signatures and serialized payloads.

**RED requirements:** `test_plan_cell_rejects_stale_episode_cell_payloads` rejects an
authoritative `record_type="episode_cell"`, the old enclosing `RunPlan` version, and a
payload lacking the discriminator/version;
`test_plan_cell_has_one_serialized_identity_even_through_alias` proves the optional Python
alias emits only the `PlanCell` schema and hash basis;
`test_plan_cell_digest_covers_every_scientific_input` mutation-tests every scientific
field; and `test_public_environment_spec_uses_plan_cell_only` rejects active public
`EpisodeCell`/`EpisodeCellT` signatures. Historical or explicitly negative migration prose
may name the retired type. No automatic legacy migration is provided on this feature
branch.

**Output:** one version-bumped `RunPlan` containing only canonical `PlanCell` records, one
public Python export (plus the optional import-only alias), and a design-contract guard
that prevents the retired serialized/public name from returning.

## Stage 1 — reconcile measurement before execution code

### Task 1.1: Refactor—not replace—the typed measurement leaf

**Files:**

- Modify `src/aeread/sdk/v1/records.py` and `src/aeread/sdk/v1/__init__.py`.
- Modify `src/aeread/runner/planning.py`.
- Modify `docs/shared_runner_design.md`, `docs/verifier_taxonomy.md`, and their design
  contract tests so this deliberate refinement of PR #7 is normative, not SDK-only.
- Modify `tests/shared_runner/fakes.py` and `tests/shared_runner/test_planning.py`.
- Create `tests/shared_runner/test_verifier_contracts.py`.

Current three buckets conflate canonical with rule verification and comparative with
judge assessment. Preserve and migrate all existing typed scientific invariants: source
orientation and source-to-canonical transformation, objective/reference scope matching,
bound-claim rules, feasibility/information/horizon/opponent conditions, and the existing
validators that make those fields mandatory. Do not replace them with an untyped
`JSONObject` escape hatch.

Each `MeasurementSpec` remains one scientific leaf: one `EstimandSpec`, exactly one of
the five semantic `VerifierSpec` families, one typed `EvaluationModeSpec`, and the typed
references authorized for that leaf. Hybrid/vector/gated/weighted/judge-augmented
composition belongs to suite analysis over multiple named leaves, never to a verifier
that silently emits a cross-family scalar.

The target shape is:

```python
class ExperimentalConditionRef(StrictModel):
    condition_id: str
    condition_version: str
    resolved_value_sha256: SHA256

class EstimandSpec(StrictModel):
    estimand_id: str
    estimand_version: str
    primary_metric_id: str | None
    input_scope: Literal["answer", "terminal_state", "trajectory", "distribution"]
    direction: Literal["maximize", "minimize", "none"]
    units: str
    conditions: tuple[ExperimentalConditionRef, ...]
    cluster_mapping: str

VerifierSpec = Annotated[
    CanonicalReferenceVerifierSpec
    | RuleConstraintVerifierSpec
    | ObjectiveReferenceVerifierSpec
    | ComparativeVerifierSpec
    | RaterJudgeVerifierSpec,
    Field(discriminator="verifier_family"),
]

class MeasurementSpec(StrictModel):
    estimand: EstimandSpec
    verifier: VerifierSpec
    evaluation: EvaluationModeSpec
    composition: LeafCompositionSpec
```

The evaluation union and the design records it binds are concrete typed records, not a
`JSONObject`/free-form options field:

```python
class SamplingPopulationSpec(StrictModel):
    population_id: str
    population_version: str
    panel_mode: Literal["fixed_panel", "sampled_panel"]
    sampling_frame_sha256: SHA256
    selection_unit: str
    selection_rule_id: str
    selection_rule_version: str

class ClusterSpec(StrictModel):
    cluster_mapping_id: str
    cluster_level: str
    identity_fields: tuple[str, ...]
    parent_fields: tuple[str, ...]

class NestedReplicateSpec(StrictModel):
    replicate_level: Literal["episode", "episode_attempt", "rater_attempt"]
    replicate_id_fields: tuple[str, ...]
    nested_within_cluster_fields: tuple[str, ...]
    replacement_creates_new_cluster: Literal[False] = False

class PairingSpec(StrictModel):
    mode: Literal["unpaired", "paired", "blocked"]
    pair_id_fields: tuple[str, ...]
    seed_fields: tuple[str, ...]

class EstimatorSpec(StrictModel):
    estimator_id: str
    estimator_version: str
    target: Literal["mean", "difference", "probability", "quantile", "pass_k"]
    implementation: ImplementationRef

class IntervalSpec(StrictModel):
    method: Literal[
        "none", "cluster_bootstrap", "paired_randomization",
        "cluster_robust", "hierarchical",
    ]
    confidence: float | None
    resampling_unit: Literal["cluster"] | None

class EstimandTransformationSpec(StrictModel):
    transformation_id: str
    transformation_version: str
    input_units: str
    output_units: str
    implementation: ImplementationRef

class MissingDataPolicySpec(StrictModel):
    policy: Literal["invalidate_required", "predeclared_partial_estimator"]
    minimum_valid_units: int | None
    missing_is_zero: Literal[False] = False

class EvaluationDesignSpec(StrictModel):
    sampling_population: SamplingPopulationSpec
    independent_cluster: ClusterSpec
    nested_replicates: NestedReplicateSpec
    pairing: PairingSpec
    estimator: EstimatorSpec
    interval: IntervalSpec
    transformation: EstimandTransformationSpec
    missing_data: MissingDataPolicySpec

class DeterministicEvaluationModeSpec(StrictModel):
    evaluation_mode: Literal["deterministic"]
    design: EvaluationDesignSpec

class StochasticEstimatorEvaluationModeSpec(StrictModel):
    evaluation_mode: Literal["stochastic_estimator"]
    design: EvaluationDesignSpec
    stochastic_source: Literal[
        "environment", "counterpart", "candidate", "judge", "combined"
    ]

class RaterVisibilitySpec(StrictModel):
    projection: Literal["public", "evaluator", "named_seat"]
    seat_ids: tuple[str, ...]
    field_allowlist: tuple[str, ...]
    blind_fields: tuple[str, ...]
    randomized_order: bool

class RaterReplicateSpec(StrictModel):
    judgment_slot_ids: tuple[str, ...]
    required_judgments: int
    maximum_replacement_attempts: int
    replacement_creates_new_cluster: Literal[False] = False

class RaterAggregationSpec(StrictModel):
    method: Literal["mean", "median", "majority_vote", "unanimous", "pairwise_model"]
    tie_policy: Literal["retain", "half_credit", "invalidate"]
    implementation: ImplementationRef

class RaterMissingnessPolicySpec(StrictModel):
    policy: Literal["invalidate_required", "predeclared_partial_estimator"]
    minimum_valid_judgments: int | None
    missing_is_zero: Literal[False] = False

class RaterProtocolSpec(StrictModel):
    rubric_sha256: SHA256
    prompt_sha256: SHA256
    visibility: RaterVisibilitySpec
    replicates: RaterReplicateSpec
    aggregation: RaterAggregationSpec
    missingness: RaterMissingnessPolicySpec

class JudgeDependentEvaluationModeSpec(StrictModel):
    evaluation_mode: Literal["judge_dependent"]
    design: EvaluationDesignSpec
    rater: RaterProtocolSpec

EvaluationModeSpec = Annotated[
    DeterministicEvaluationModeSpec
    | StochasticEstimatorEvaluationModeSpec
    | JudgeDependentEvaluationModeSpec,
    Field(discriminator="evaluation_mode"),
]
```

Validation makes every identifier/version/field tuple non-empty and unique; paired or
blocked modes require pair IDs and seeds; `interval.method="none"` is the only mode with
`confidence=None`/no resampling unit; all other interval methods require confidence
strictly between zero and one plus cluster resampling. `predeclared_partial_estimator`
requires a positive
`minimum_valid_units`; `invalidate_required` forbids one. `missing_is_zero` accepts only
`False`. `RaterReplicateSpec.required_judgments` is positive, its slot IDs are unique, and
replacement creates a new judgment/`RaterAttempt` identity nested in the existing
independent cluster. `named_seat` visibility requires explicit `seat_ids`; other
projections forbid them. `RaterMissingnessPolicySpec` applies the same fail-closed
validation using its explicit positive `minimum_valid_judgments`, which cannot exceed
`required_judgments`. Authoring ownership remains with
the suite's typed `SamplingPlan` and `AnalysisPlan`; `EvaluationDesignSpec` is their one
canonical resolved binding for the leaf, not a second independently editable declaration.
The resolver hashes and exact-compares the binding and rejects, rather than overrides, a
conflicting duplicate.

Each verifier variant owns a discriminated typed reference union; reference *source* is
a second discriminated union (`case_payload`, `pinned_artifacts`, or approved
`pre_outcome_computation`). Common typed `EstimandSpec.conditions` references can identify
experimental conditions, but they never substitute for typed objective scope. In
particular the
objective verifier retains `source_direction`, `source_to_canonical_rule`, units,
feasible set, information set, horizon, environment/opponent condition, stochastic
expectation, validity domain, typed claim, proof type, and exact scope matching for every
reference. Canonical, rule, comparative, and rater variants likewise keep their
family-specific reference and provenance constraints.

`deterministic`, `stochastic_estimator`, and `judge_dependent` remain evaluation modes,
not extra verifier families. `EvaluationBlock.estimand_id` stays singular; evaluator/
analysis roles are explicit. `measurement_sha256` hashes the complete leaf spec.

Bump `FamilyManifest`, `SuiteManifest`, and `RunPlan` spec versions rather than offering
an automatic legacy parser. Move hybrid gate/vector/weighted/judge-augmented composition
to typed `SuiteManifest.compositions` over `block_id`s. Weighted scalars require exact
rational weights, pinned transforms, a declared decision problem, and sensitivity
analysis; otherwise cross-family output remains a vector. Add evaluator assignments to
the evaluation block without turning evaluators into environment seats.

This is a deliberate refinement of PR #7: leaf verifiers always declare
`composition_kind="leaf"`; a separate typed `MeasurementCompositionSpec` combines named
block outputs only after leaf scoring. A composition never changes a leaf's validity or
inclusion. A deterministic legality/admission gate that can prevent execution belongs to
the case/rule contract; a suite `hybrid_gate` controls only post-hoc reporting. It cannot
claim that separately executed leaves share a trajectory. Any same-trajectory joint
claim requires an explicit paired/shared-evidence design and is outside V0.

**RED requirements:** all five valid verifier records plus all three evaluation-mode JSON
schema discriminators; incompatible family/mode fields rejected; objective references
match full estimand scope. `test_unauthorized_rater_visibility_makes_zero_evaluator_calls`
fails preflight before an `EvaluationWork`/`RaterAttempt` or provider call is opened.
`test_required_judgment_missing_failed_or_unknown_is_invalid_measurement` covers missing,
failed, and `outcome_unknown` required judgments; the only admitted partial result uses a
predeclared partial estimator whose `minimum_valid_judgments` is satisfied.
`test_missingness_never_drops_or_imputes_zero` rejects `missing_is_zero=True`, implicit row
dropping, and zero imputation. `test_rerun_and_replacement_preserve_independent_cluster`
requires new replicate/episode-attempt/rater-attempt IDs while keeping the original
`cluster_id`. Hash-mutation tests cover sampling population, exact cluster mapping,
nesting, pairing fields and seeds, estimator, interval method/confidence, transformation,
rater visibility/replicates/aggregation, and missingness; every change updates
`PlanCell.measurement_sha256`, and every estimand declared by the suite has exactly one
cluster mapping. Legacy three-bucket payloads fail rather than silently coercing;
composition rejects missing/cyclic blocks, invalid gate families, and undeclared
cross-family scalars; evaluator profiles are pinned but never become economic seats.

**Output:** version-bumped family/suite/run-plan schemas containing five leaf verifier
variants, three evaluation-mode variants, one canonical typed sampling/cluster/analysis
design per leaf, and typed suite-level compositions over leaf `block_id` outputs.

### Task 1.2: Add five provider-free measurement fixtures

Create one valid and one neighboring invalid fixture for each family under
`tests/shared_runner/fixtures/verifier_families/`, plus
`tests/shared_runner/test_verifier_family_fixtures.py`. Fixtures are AERead-owned
microcases, not copied benchmark tasks. Each must canonicalize, resolve to a plan, and
fail invalid input before filesystem mutations, runtime starts, or provider side
effects. This proves expressibility, not
upstream parity.

## Stage 2 — correct agent lifecycle and side-effect contracts

### Task 2.1: Replace retired call-attempt vocabulary

**Files:**

- Modify `src/aeread/sdk/v1/records.py`, `src/aeread/sdk/v1/protocols.py`, and
  `src/aeread/sdk/v1/__init__.py`.
- Modify `tests/shared_runner/test_records.py`, `tests/shared_runner/test_registry.py`, and
  `tests/shared_runner/fakes.py`.
- Modify the authoritative `AttemptObserver` and executable action-boundary examples in
  `docs/public_environment_and_external_adapter_spec.md` and guard them in
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
plan/input unit; `RaterAttempt` is the only retry/identity unit for evaluator execution,
so no redundant `EvaluatorAttempt` record is exported.
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

Add a first-class environment-transition evidence contract. `TransitionStart` durably
binds transition/phase IDs, ordered bundle hashes, prior state version/hash, idempotency
key, and declared reconciliation capability before `EnvironmentPlugin.step()`. The strict
terminal union is:

- `TransitionSucceeded`: next state version/hash and result/state-diff artifact refs;
- `TransitionFailed`: typed failure plus evidence that no commit occurred and the prior
  state remains authoritative;
- `TransitionOutcomeUnknown`: the adapter cannot prove whether mutation committed.

An optional checkpoint is progress evidence, never terminal. Pure/copy-on-write native
environments may provide runner-owned rollback; external/database environments must
declare idempotency/reconciliation or fail admission for resumable execution. Unknown
mutation is never retried or resumed until reconciled.

Add an append-only reconciliation contract without changing the original transition
terminal:

```python
class TransitionReconciliationStart(StrictModel):
    reconciliation_attempt_id: str
    transition_id: str
    transition_idempotency_key: str
    reconciler: ImplementationRef

class TransitionReconciliationRequest(StrictModel):
    reconciliation_attempt_id: str
    transition_id: str
    transition_idempotency_key: str
    outcome_unknown_event_id: str
    prior_state_version: str
    prior_state_sha256: SHA256

class TransitionReconciliationResult(StrictModel):
    status: Literal["committed", "not_committed", "still_unknown"]
    proof_artifact_ref: ArtifactRef
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

class TransitionReconciliationCommitted(StrictModel):
    status: Literal["committed"]
    reconciliation_attempt_id: str
    transition_id: str
    proof_artifact_ref: ArtifactRef
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

class TransitionReconciliationNotCommitted(StrictModel):
    status: Literal["not_committed"]
    reconciliation_attempt_id: str
    transition_id: str
    proof_artifact_ref: ArtifactRef
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

class TransitionReconciliationStillUnknown(StrictModel):
    status: Literal["still_unknown"]
    reconciliation_attempt_id: str
    transition_id: str
    proof_artifact_ref: ArtifactRef
    authoritative_state_version: str
    authoritative_state_sha256: SHA256

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
    ) -> TransitionReconciliationResult: ...
```

`TransitionReconciliationStart` references the original `TransitionOutcomeUnknown` by
`transition_id`, repeats its exact idempotency key, pins the reconciler, and is durably
written before any reconciliation query/side effect. One start receives exactly one
terminal; every terminal binds a content-addressed proof artifact and the authoritative
state version/hash observed by the pinned reconciler. The original transition terminal is
never overwritten, and neither a transition attempt nor a reconciliation attempt may
publish a second terminal. `committed` means resume from the authoritative committed state
without reissuing `step()`. `not_committed` means a retry is possible only as a new
recorded transition ID/start and only under the predeclared retry/idempotency policy.
`still_unknown` quarantines the runtime/cell and yields `invalid_measurement`; neither
resume nor retry is permitted. Task 3.9 implements these rules.

**RED requirements:** retired active executable imports, exports, schema discriminators,
and authoritative public-spec signatures using `CallAttemptStart`/`CallAttemptToken` fail;
explicitly labeled historical/negative migration prose may retain the strings. Record tests
reject mismatched parent IDs, missing pins/hashes, second terminal construction in a
conformance fake, and reconciliation terminals without proof plus authoritative state.
The public design-contract RED asserts the exact response -> parse -> legality ->
transition path and rejects language allowing adapters/attempts/tools to create an
`ActionEnvelope` or execute a requested family mutation. Runtime no-envelope/no-tool-
success/no-step-before-parse-and-legality RED belongs to Tasks 3.1 and 3.3.

**Output:** one versioned public evidence vocabulary rooted in `ActionAttempt`,
`ProviderCall`, actual `ToolInvocation`, `RaterAttempt`, lifecycle operations, environment
transitions, and append-only transition reconciliation, with no active serialized
`CallAttempt*` identity.

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

**RED requirements:** one seat can emit multiple ordered channels in one slot; stable
`slot_id`, `channel_id`, and `sequence_index` survive LogicalAction, ActionAttempt, parse,
and ActionBundle; collection is keyed by slot, never reduced to `dict[seat_id, action]`;
all simultaneous bundles enter exactly one atomic `step()` call. Named tests cover every
channel's `min_actions`/`max_actions`, globally unique `action_id` values and unique ordered
`sequence_index` values within a bundle, rejection of an action whose `slot_id` differs
from its bundle/current slot, and atomic rejection of the entire bundle when any required
channel/action is missing, extra, malformed, cross-slot, or illegal. No valid sibling from
a rejected partial bundle reaches `step()`.

`test_mutating_tool_request_is_untrusted_until_parse_and_legality` asserts that a model-
requested family mutation creates no `ActionEnvelope`, no `ToolInvocationSucceeded`, and
no `step()` call before successful parse and legality. Neighboring malformed-parse and
illegal-bundle cases assert zero transition starts and zero steps; only the fully legal
bundle writes one durable `TransitionStart` and then calls `step()` once.

**Transition RED requirements:** durable start precedes `step()`; exception before any
commit produces `failed` with unchanged prior hash; exception after an unreconciled
possible commit produces `outcome_unknown`; successful commit binds the exact next
version/hash; replay/resume rejects a missing, duplicate, or contradictory terminal row.

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

Create `src/aeread/runner/evaluation.py` and
`tests/shared_runner/test_evaluation.py`. Add `EvaluationWork` plus `RaterAttempt`; rater
provider calls belong to measurement/evaluator work, not candidate `LogicalAction`s.
Validate judge capability/visibility, freeze the authorized evaluation-input artifact
hash, and produce `build_evaluation_plan(...) -> EvaluationWorkPlan` while the event store
remains open. Repeat the Task 1.1 unauthorized-visibility RED at the execution boundary:
preflight failure creates zero `EvaluationWork`, `RaterAttempt`, provider, and tool calls.

### Task 3.6: Pure recorded-rater aggregation

In `src/aeread/runner/evaluation.py` and `tests/shared_runner/test_evaluation.py`, add
`aggregate_recorded_judgments(...) -> RaterAggregate`. Aggregate canned human/LLM/imported
rater records, provenance, ties, missingness, and disagreement without provider calls.
Missing, failed, and `outcome_unknown` required judgments return `invalid_measurement`
unless the predeclared partial estimator reaches `minimum_valid_judgments`; there is no
implicit drop or zero imputation. Deterministic score components stay separate from
judge-dependent components. This is the first executable judge-verifier gate.

### Task 3.7: Live evaluator execution

Implement evaluator execution entirely with scripted/fake providers: while the event log
is open, execute the validated plan and record rater attempts and provider calls. Then
finalize and seal evidence. Only after that does pure `VerifierPlugin.score()` read a
`SealedEvidenceView`. A sealed store never reopens for judge output. No live-provider
smoke is authorized by this task. RED covers failed/missing/`outcome_unknown` judgment
attempts, replacement under a new `RaterAttempt` identity in the same independent cluster,
and exact enforcement of the authorized input artifact hash and partial-estimator
threshold.

### Task 3.8: Deterministic replay validation

**Files:**

- Create `src/aeread/runner/replay.py`.
- Create `tests/shared_runner/test_replay.py`.

**Consumes:** `PlanCell`, the full `SealedEvidenceView`, content-addressed artifacts, the
pinned `EnvironmentPlugin`, and the pure `ScoreEnvelope`. **Produces:**
`validate_replay(...) -> ReplayReport`, where the immutable typed report records
`status`, requested/achieved replay level, transition/event coverage counts, terminal
state version/hash, score hash, and an optional typed first divergence. Its canonical
bytes/hash are staged for Task 3.11; replay never mutates the sealed evidence/artifact
roots.

Replay reconstructs state and verifies score inputs from sealed evidence and artifacts
with zero provider, tool, evaluator, session, backend, or runtime calls.

**RED requirements:** dependency fakes raise if any external execution port is touched;
unsealed evidence, a missing/duplicate/contradictory transition terminal, a bundle/order/
state-hash mismatch, an unreconciled transition, or a score-input/hash mismatch yields a
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

**Consumes:** Task 2.1 transition/reconciliation records and `TransitionReconciler`, the
validated open event chain, pinned plan/idempotency policy, and Task 3.2 quarantine/
lifecycle hooks. **Produces:** `RecoveryCoordinator.recover(...) -> RecoveryDecision` and
`reconcile_transition(...) -> TransitionReconciliationTerminal`; the decision is one of
`resume_committed_state`, `new_transition_attempt_allowed`, or
`quarantine_invalid_measurement` and binds the authoritative state version/hash.

Resume only from reconciled durable boundaries. For `committed`, restore the reconciler's
authoritative committed state and continue without reissuing `EnvironmentPlugin.step()`.
For `not_committed`, allow a retry only by allocating a new `transition_id`, durably
writing a new `TransitionStart`, and satisfying the declared retry/idempotency policy. For
`still_unknown`, quarantine and invalidate the cell; no resume, retry, or new operational
attempt may claim the mutation is safe. The original `TransitionOutcomeUnknown` remains
in the append-only log.

**RED requirements:** parameterize all three terminal outcomes and crash points (before
reconciliation start; after durable start but before the reconciler call; during/after the
call but before terminal append; and after terminal append but before control-flow
continuation). A start without terminal is resumed under the same reconciliation-attempt
ID only when the pinned reconciler declares the same-key query replay-safe; otherwise it
closes once as `still_unknown` and quarantines. Tests reject retry or resume before
reconciliation, a second reconciliation start used to evade an unfinished one, a second
or contradictory transition/reconciliation terminal, terminal overwrite, missing proof,
changed idempotency key/reconciler pin, and any `step()` call on the `committed` or
`still_unknown` paths. The `not_committed` path proves the old transition is not reused
and the new attempt is recorded before its one allowed `step()`.

**Output:** append-only, crash-safe recovery that closes each transition and reconciliation
attempt exactly once and makes every resume/retry/quarantine decision explicit.

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
`ReplayReport`, Task 3.9 final `RecoveryDecision`, Task 3.10 `ProjectionSet`, and the
resolved `RunPlan`/`PlanCell`. **Produces:** `finalize_episode(...) -> EvaluationReceipt`
and an atomic canonical receipt file whose `receipt_sha256` excludes only its own digest
field.

Only after seal/pure score, replay validation, final recovery state, and projections,
create the immutable receipt. It binds plan/case, candidate, counterpart and judge
configurations, runtime/tools, environment/parser/verifier/reference pins, evidence roots,
replay result/coverage/report hash, reconciliation/recovery disposition, admission/
observability, exact cluster/pair/replicate identity, projection and per-seat trajectory
refs, score or typed failure, and inclusion. Secret/native session identifiers are
excluded.

**RED requirements:** finalization rejects unsealed evidence, an unfinished transition or
reconciliation, absent/mismatched replay/projection hashes, cluster or plan identity drift,
an invalid score paired with numeric output, and any secret/native session identifier in
the public receipt. A scorer/judge/recovery failure produces `invalid_measurement` with no
numeric zero imputation. Receipt publication is atomic/idempotent for identical canonical
bytes and refuses a different second receipt for the same episode attempt. Hash mutation
tests cover every candidate/counterpart/judge/runtime/tool/plugin/reference/evidence/
replay/recovery/cluster/projection/score/inclusion field.

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
evaluation modes; exact cluster/pair/replicate mapping; sequential/simultaneous/multi-
channel scheduling; channel cardinality and atomic bundles; privacy; malformed/illegal/
missing/timeout actions; the no-mutation-before-parse/legal boundary; actual tool evidence;
session cleanup/isolation; judge visibility and fail-closed missingness; all transition-
reconciliation outcomes; deterministic replay; receipt integrity; and valid zero/negative
economics.

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
  environment transition, every transition-reconciliation crash point, cleanup, and
  backend stop failures reconcile to one strict terminal/unknown state without overwrite.
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
is not implemented. Task 0.3+ remains blocked until an independent review finds this
corrected plan P0/P1/P2 clean and the progress ledger records that verdict. Thereafter each
task advances only through its declared RED/GREEN, scoped commit, and independent-review
gate; provider-free/static evidence is never reported as live runtime, upstream parity, or
benchmark-quality evidence.
