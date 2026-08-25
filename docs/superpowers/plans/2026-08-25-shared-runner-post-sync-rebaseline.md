# Shared Runner Post-Sync Rebaseline Implementation Plan

> **Author:** Codex, for Zeyu Sun  
> **Date:** 2026-08-25  
> **Status:** scope approved for autonomous work; Task 0.1 is precisely blocked after its
> fifth fix/re-review round by one case-insensitive-filesystem P1; do not dispatch Task
> 0.2+ until that gate is explicitly reset, fixed, and independently cleared. Separately,
> five plan-review rounds are exhausted and the final transition-evidence finding is
> patched but not independently re-cleared.  
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

Task 0.1 is complete only after independent review is P0/P1/P2 clean. Current verdict at
`ab6c3b1`: **BLOCKED after round 5/5** because filesystem-equivalent case aliases bypass
the reserved-namespace check; literal lowercase collision tests and all earlier Task 5
invariants pass.

### Task 0.2: Integrate the latest approved PR #7 design

Dependency: Task 0.1 clean and clean worktree.

1. Merge `origin/feat/shared-runner-design` at `6bb07aa`.
2. Resolve the known `docs/shared_runner_design.md` conflict by retaining local
   `DecisionSlot` / channel / ordered `ActionBundle` semantics and adopting upstream
   `LogicalAction -> ActionAttempt -> ProviderCall* + ToolInvocation*` vocabulary.
3. Preserve the public environment/adapter spec and implementation plans.
4. Verify Section 13 of the taxonomy and the R0–R8 walkthrough are present.
5. Run the design contract suite and full suite before committing the merge.

### Task 0.3: Migrate the serialized planning identity to `PlanCell`

PR #7 freezes `PlanCell -> Episode -> EpisodeAttempt`. Rename the current public and
serialized `EpisodeCell` record to `PlanCell`, then update the resolver, hash basis,
exports, schemas, and fixtures. Add `record_type: Literal["plan_cell"]` and an exact
`spec_version`, and bump the enclosing `RunPlan` schema. A compatibility alias may exist
only at the Python import surface; it must not introduce a second serialized identity or
hash basis.

**RED requirements:** a stale payload lacking the discriminator/version fails; old and
new Python names cannot serialize to two valid identities; every scientific input still
changes the plan-cell digest. No automatic legacy migration is provided on this feature
branch.

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
class EstimandSpec(StrictModel):
    estimand_id: str
    estimand_version: str
    primary_metric_id: str | None
    input_scope: Literal["answer", "terminal_state", "trajectory", "distribution"]
    direction: Literal["maximize", "minimize", "none"]
    units: str
    conditions: JSONObject
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

Each verifier variant owns a discriminated typed reference union; reference *source* is
a second discriminated union (`case_payload`, `pinned_artifacts`, or approved
`pre_outcome_computation`). Common `EstimandSpec.conditions` can describe experimental
conditions, but it never substitutes for typed objective scope. In particular the
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

**RED requirements:** all five valid records and JSON-schema discriminators; incompatible
family fields rejected; objective references match full estimand scope; rater/judge
requires rubric, visibility, replicate, aggregation and provenance; every measurement
input changes the `PlanCell.measurement_sha256`; legacy three-bucket payloads fail
rather than silently coercing; composition rejects missing/cyclic blocks, invalid gate
families, and undeclared cross-family scalars; evaluator profiles are pinned but never
become economic seats.

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

Modify SDK records/protocols/exports and their focused tests. The only hierarchy is:

```text
LogicalAction
  -> ActionAttempt
       -> ProviderCall 0..n
       -> ToolInvocation 0..n
       -> CanonicalResponse/ActionEnvelope | typed failure

EvaluationWork
  -> RaterAttempt 1..n
       -> ProviderCall 0..n
       -> ToolInvocation 0..n
       -> RaterJudgment | typed failure

EnvironmentTransition
  -> TransitionStart
  -> TransitionCheckpoint 0..n
  -> TransitionSucceeded | TransitionFailed | TransitionOutcomeUnknown
```

Rename serialized `CallAttemptStart/Token` to `ProviderCallStart/Token`. Add
`ActionAttemptStart` plus a strict terminal union for each action, provider call, tool,
evaluator, and runtime operation: `succeeded | failed | outcome_unknown`. Add
`ToolInvocationStart` and its strict terminal union, with stable parent
IDs, canonical hashes, tool/version pins, idempotency/reconciliation capability,
`environment` versus `harness_internal` scope, and result/state-diff artifact refs.
Every child side effect uses a discriminated parent ref:
`action_attempt | rater_attempt | lifecycle_operation`. `EvaluationWork` is the frozen
plan/input unit; `RaterAttempt` is the only retry/identity unit for evaluator execution,
so no redundant `EvaluatorAttempt` record is exported.
Retry creates a new `ActionAttempt`; provider transport retry creates another
`ProviderCall`. A mutating tool with unknown outcome is not silently retried.

A model request to invoke a mutating family tool is a `CanonicalResponse`/
`ActionEnvelope`, not a completed `ToolInvocation`: it terminates the attempt and becomes
an action in the scheduler's bundle. The environment transition owns mutation start and
terminal evidence. `ToolInvocation` terminal rows cover operations actually executed
inside an attempt (read-only, harness-internal, or transactional preview). A failed
`step()` can never coexist with a succeeded tool-invocation row claiming that economic
mutation committed.

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

### Task 2.2: Add episode-scoped harness lifecycle

**Files:** SDK records/protocols, registry, fakes, and a new
`tests/shared_runner/test_agent_lifecycle_contract.py`.

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
lifecycle coordinator validates compatibility before `ExecutionBackend.start()` and
owns backend start/stop, adapter setup/cleanup, session open/close, and their write-ahead
events. An action executor borrows an existing session; it never owns session close or
adapter cleanup. At the `EpisodeAttempt` boundary, one runner-owned finalizer chooses
exactly one action for each live session generation: `close` by default, or
`reset-consume` only when a next attempt has already been authorized.

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
seat/phase tool allowlists, writes durable starts before tool side effects, executes, and
reconciles terminal outcome. `ExecutionBackend` owns process/file/network/runtime
operations only. Harness-internal tools never mutate economic state. A mutating family
tool call terminates the current `LogicalAction`/`ActionAttempt` with a typed tool action;
the scheduler then commits its bundle through the family's single state-versioned atomic
`step()`. Any provider continuation is a new LogicalAction/ActionAttempt in the same
authorized session. Only read-only, harness-internal, or deterministic transactional
preview tools may return a result and resume provider execution inside one attempt.
During simultaneous collection, immediate tools are read-only/preview against the frozen
snapshot; mutating actions are staged and committed together only after all slots arrive.
Thus tools cannot create a second untracked environment-mutation path.

**RED requirements:** capability mismatch causes zero backend/provider/tool calls;
backend-start, partial-setup, open-session, close, cleanup, and backend-stop failures all
reconcile; reset failure/timeout/outcome-unknown never reuses the old generation; native
session IDs and secrets never enter public evidence/receipts; action retry restores a
fresh/checkpointed pre-action session without replaying side effects; backend/setup state
cannot leak between default lease keys; failed `step()` cannot leave a succeeded
ToolInvocation claim for its economic mutation.

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
real provider/session executor. Freeze simultaneous observations, handle sequential,
simultaneous, and multi-slot decisions, parse and validate complete bundles, apply
family-declared missing/invalid consequences, perform one atomic transition, validate
phase edges/termination, and record all boundaries.

**RED requirements:** one seat can emit multiple ordered channels in one slot; stable
`slot_id`, `channel_id`, and `sequence_index` survive LogicalAction, ActionAttempt, parse,
and ActionBundle; collection is keyed by slot, never reduced to `dict[seat_id, action]`;
all simultaneous bundles enter exactly one atomic `step()` call.

**Transition RED requirements:** durable start precedes `step()`; exception before any
commit produces `failed` with unchanged prior hash; exception after an unreconciled
possible commit produces `outcome_unknown`; successful commit binds the exact next
version/hash; replay/resume rejects a missing, duplicate, or contradictory terminal row.

### Task 3.2: Episode/session lifecycle coordinator

Create the coordinator described in Task 2.2 and prove fail-closed preflight plus cleanup
ownership with scripted adapters/backends. Default isolation closes each session at
episode-attempt scope and opens fresh on the next attempt. Optional reset consumes the
old session generation and returns a new generation; it is never an implicit
`ActionAttempt` retry. Action-attempt restart instead uses coordinator-owned fresh
generation plus safe checkpoint/restore or side-effect-free canonical prefix replay.

### Task 3.3: Action-attempt executor

Create `src/aeread/runner/attempts.py` and
`tests/shared_runner/test_attempts.py`. Test exception-after-provider-start,
provider→tool→provider, length retry, hidden retry rejection, child reconciliation,
timeout/cancellation, and ToolMediator ownership. It borrows the coordinator's live
session and never closes it. Failure never manufactures an economic zero.

### Task 3.4: Scheduler × real executor integration

Integrate Task 3.1's scheduler with Tasks 3.2–3.3 without adding family branches.
Single-agent, controlled counterpart, population, and live-live use the same kernel.

### Task 3.5: Judge plan, authorized input, and evaluator hierarchy

Create `src/aeread/runner/evaluation.py` and
`tests/shared_runner/test_evaluation.py`. Add `EvaluationWork` plus `RaterAttempt`; rater
provider calls belong to measurement/evaluator work, not candidate `LogicalAction`s.
Validate judge capability/visibility, freeze the authorized evaluation-input artifact
hash, and produce a provider-free execution plan while the event store remains open.

### Task 3.6: Pure recorded-rater aggregation

Aggregate canned human/LLM/imported rater records, provenance, ties, missingness, and
disagreement without provider calls. Deterministic score components stay separate from
judge-dependent components. This is the first executable judge-verifier gate.

### Task 3.7: Live evaluator execution

Implement evaluator execution entirely with scripted/fake providers: while the event log
is open, execute the validated plan and record rater attempts and provider calls. Then
finalize and seal evidence. Only after that does pure `VerifierPlugin.score()` read a
`SealedEvidenceView`. A sealed store never reopens for judge output. No live-provider
smoke is authorized by this task.

### Task 3.8: Deterministic replay validation

Replay from sealed evidence and artifacts performs no provider, tool, or runtime calls.
Persist the achieved replay level/coverage for later receipt finalization.

### Task 3.9: Interrupted-run recovery/resume

Resume only from reconciled durable boundaries and creates a new operational attempt when
required; it never silently continues a poisoned or outcome-unknown mutation.

### Task 3.10: Public/private projections

Derive privacy-checked public projections and per-seat trajectory references without
changing the canonical evidence root or exposing secrets/private observations.

### Task 3.11: Receipt finalization

Only after seal/pure score, replay validation, final recovery state, and projections,
create the immutable receipt. It binds plan/case, candidate, counterpart and judge
configurations, runtime/tools, environment/parser/verifier/reference pins, evidence
roots, replay result/coverage, admission/observability, cluster identity, projection and
per-seat trajectory refs, score or typed failure, and inclusion. Secret/native session
identifiers are excluded.

## Stage 4 — provider-free conformance

### Task 4.1: Conformance library

Publish importable provider-free conformance fixtures for strict manifests; all five
verifier leaves; sequential/simultaneous/multi-channel scheduling; privacy; malformed/
illegal/missing/timeout actions; tool evidence; session cleanup; judge visibility;
replay; and receipt integrity.

### Task 4.2: Conformance CLI

Expose deterministic selection, machine-readable results, and non-zero failure exit.

### Task 4.3: Import-isolation gate

SDK/core imports must not load tau, Harbor, Docker, Gurobi, provider SDKs, or concrete
case families.

### Task 4.4: First live evaluator smoke

Explicit dependency: Tasks 4.1–4.3 are independently clean. Run one bounded live rater
smoke with pinned evaluator profile and no economic mutation; validate receipt/privacy/
cost evidence. It is infrastructure evidence, not a benchmark-quality result.

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
- Mutating family tool: terminates its action attempt, commits through one scheduler
  `step()`, and any provider continuation is a new logical action/attempt.
- Retry matrix: restart/continue/forbid exactly follows `SessionPolicy`.
- tau3 scripted half-duplex: assistant/user sessions, mutating tool, terminal DB.
- Harbor/tau whole trial: outer envelope only and `interop_only` admission.
- Harbor runtime backend: same scripted AERead episode has native outcome/score parity.
- Crash matrix: backend start, partial setup, open session, provider, tool, close,
  environment transition, cleanup, and backend stop failures reconcile to a strict
  terminal/unknown state.
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

## Overnight completion criterion

The whole runner need not finish tonight. The session succeeds if Task 5 is independently
clean or precisely blocked; the latest PR #7 design is integrated or has an exact conflict
resolution; the five-verifier/source matrix and corrected plan exist; and any additional
code was added only after its prerequisite gates with exact test and review evidence.
