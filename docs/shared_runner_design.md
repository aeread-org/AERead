# AERead Shared Runner, Measurement, and Case Format

> **Status:** normative design target; authoring/planning/measurement records and the evidence foundation are landed; scheduler, executor, receipt finalization, replay, and adapters are not landed
>
> **Owner:** Zeyu Sun
>
> **Reviewed:** 2026-08-24
>
> **Compatibility baseline:** the current `exchange_v1_runner.py` path

## Purpose and scope

AERead needs one runner that can evaluate heterogeneous economic case families—exchange, contracts, refunds, partner discovery, and housing—without forcing them into one game loop, utility model, or universal score.

The design rule is:

> **Standardize experimental control, evidence, and measurement declarations; keep economic semantics inside versioned environment, verifier, reference, and generator plugins.**

The shared runner owns experiment resolution, phase scheduling, agent execution, explicit retry accounting, durable evidence, replay, receipts, and declared aggregation. The `EnvironmentPlugin` owns state, observations, actions, transitions, and terminal outcomes; family-owned verifier, reference-provider, and generator implementations own measurement and case semantics without becoming scheduler callbacks.

This document is the implementation contract that other branches may cite. It does **not** claim that the shared runner already exists.

---

## 1. Frozen decisions

| Decision | Baseline |
|---|---|
| **Canonical owner** | AERead native schemas and receipts define benchmark truth. Prime, Harbor, and rLLM are adapters/export targets. |
| **Unit under test** | A fully resolved **agent configuration**: model, harness, prompt, sampling, runtime, tools/memory, limits, and retry policy. |
| **Primary evaluation block** | Controlled evaluation against a scripted or version-pinned counterpart. Cross-play and self-play/hardness are separate blocks because they measure a joint system. |
| **Control flow** | The runner owns a declarative `PhaseSpec` schedule. The family supplies pure or auditable phase hooks; it does not receive an unrestricted callback with which to run its own hidden loop. |
| **Actions** | Observation, parser, action schema, legality rule, and invalid-action consequence are phase- and role-specific. There is no universal role-only action schema. |
| **Calls and retries** | One `LogicalAction` contains one or more explicit `ActionAttempt` records. An attempt may contain multiple atomic `ProviderCall` and `ToolInvocation` records; no provider/SDK retry or tool side effect may be hidden. |
| **Scoring** | Every estimand declares its measurement kind, direction, comparison reference, and typed bound evidence. Reserve `oracle` for an exact reference inside a declared validity domain; other references are typed separately. Social welfare, principal utility, and distributional capture remain separate quantities. |
| **Cross-family reporting** | There is no default universal score. Family metrics may be displayed together, but scalar pooling is disabled unless a paper supplies and defends a normalization and weighting rule. |
| **Clusters** | The suite declares the smallest independently sampled, randomized, or assigned unit before execution. Repeated rows inside that unit are not independent samples. |
| **Evidence** | Stable episode/action/attempt/event identities, write-before-side-effect records, typed visibility, deterministic ordering, and crash/resume semantics are required. |
| **Reference paths** | Wrap `exchange_v1` and prove parity; implement `housing_v1` as the first clean native family. |

Case owners do not need to agree on a universal state, action, welfare, or bargaining schema. They do need to implement the versioned hooks and declarations below.

The canonical object hierarchy, exact walkthrough of the current Exchange path,
compatibility map, and gated implementation sequence are frozen in
[`walkthroughs/shared_runner_architecture_roadmap.md`](walkthroughs/shared_runner_architecture_roadmap.md).

---

## 2. Architecture and ownership

```text
L5  Interoperability
    rLLM trajectories | Harbor tasks / ATIF | Prime Verifiers adapters
    (consume native records; do not define benchmark truth)

L4  Research protocol and analysis
    SuiteManifest | measurement declarations | cluster-aware aggregation

L3  Shared runner kernel                                      Zeyu owns
    resolve + hash -> RunPlan | phase scheduler | agent calls
    retries | evidence | replay/resume | receipts | coverage

L2a Environment + measurement plugins  L2b Agent execution adapters
    typed phase hooks + scorer              harness + runtime + provider
    references + generator + baselines      Python / HTTP / CLI / container

L1  Shared authoring formats
    FamilyManifest | CaseManifest | SuiteManifest | RunSpec / AgentProfile
```

| Shared runner owns | Environment and family-owned measurement plugins own |
|---|---|
| schema/version/hash validation | typed state and private types |
| immutable `RunPlan` resolution | declarative phase definitions |
| phase and actor scheduling | role- and phase-specific observations |
| seat-to-agent assignment | parsing, action schemas, and legality |
| budgets, timeouts, and retry ownership | transitions and economic consequences |
| `AgentAdapter` dispatch and canonicalization | natural termination and terminal outcome |
| append-only evidence and artifacts | primary outcome, diagnostics, and rewards |
| receipt integrity, replay/resume, and coverage | reference providers, generators, difficulty knobs, and baselines |
| declared cluster-aware aggregation and export | family interpretation of each measurement |

The kernel MUST NOT import a concrete family or contain `if family == ...` branches. The
formal target resolves `family_id` and version through a provenance-attested registry. The
current exact-version developer registry/discovery foundation is not yet trusted for paper
mode because it lacks pre-load allowlisting and resolved distribution/source provenance.

### 2.1 Declarative phase contract

`PhaseSpec` is runner-readable. It names the eligible decision slots, whether their actions are sequential or simultaneous, the observation and action contracts, budgets, invalid-action policy, and the possible next phases. A decision slot is the unit at which the runner requests one logical agent decision; it is not limited to one channel or one action field.

```python
class PhaseSpec:
    phase_id: str
    actor_selector: str
    mode: Literal["single", "sequential", "simultaneous"]
    observation_schema_by_role: dict[str, SchemaRef]
    action_schema_by_role: dict[str, SchemaRef]
    max_logical_actions: int
    invalid_action_policy: str
    next_phases: tuple[str, ...]


class ActionChannel(StrictModel):
    channel_id: str
    recipient_seat_ids: tuple[str, ...]
    action_schema_ref: str
    min_actions: int = 1
    max_actions: int | None = 1


class ActionEnvelope(StrictModel):
    action_id: str
    slot_id: str
    channel_id: str
    actor_seat_id: str
    sequence_index: int
    payload: dict[str, object]


class DecisionSlot(StrictModel):
    slot_id: str
    seat_id: str
    channels: tuple[ActionChannel, ...]
    observation_schema_ref: str
    response_schema_ref: str
    order_key: str


class ActionBundle(StrictModel):
    slot_id: str
    actions: tuple[ActionEnvelope, ...]


class EnvironmentPlugin(Protocol):
    manifest: FamilyManifest

    def validate_case(self, payload: Mapping[str, object]) -> FamilyCase: ...
    def initial_state(self, case: FamilyCase, cell: PlanCell) -> FamilyState: ...
    def phase_graph(self, case: FamilyCase) -> PhaseGraph: ...
    def decision_slots(
        self, case: FamilyCase, state: FamilyState, phase: PhaseSpec
    ) -> Sequence[DecisionSlot]: ...
    def observe(
        self, case: FamilyCase, state: FamilyState, phase: PhaseSpec,
        slot: DecisionSlot
    ) -> ObservationEnvelope: ...
    def parse_action(
        self, case: FamilyCase, state: FamilyState, phase: PhaseSpec,
        slot: DecisionSlot, response: CanonicalResponse
    ) -> ParseResult: ...
    def legal(
        self, case: FamilyCase, state: FamilyState, phase: PhaseSpec,
        bundle: ActionBundle
    ) -> LegalityResult: ...
    def step(
        self, case: FamilyCase, state: FamilyState, phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle]
    ) -> TransitionResult: ...
    def terminal(
        self, case: FamilyCase, state: FamilyState
    ) -> TerminalResult | None: ...
    def outcome(
        self, case: FamilyCase, terminal: TerminalResult
    ) -> FamilyOutcome: ...


class AttemptObserver(Protocol):
    """Stable v1 runner-owned write-ahead provider-call observer."""
    def call_started(self, start: CallAttemptStart) -> CallAttemptToken: ...
    def call_succeeded(
        self, token: CallAttemptToken, result: ProviderCallResult
    ) -> None: ...
    def call_failed(
        self, token: CallAttemptToken, failure: ProviderCallFailure
    ) -> None: ...


class AgentAdapter(Protocol):
    async def act(
        self, request: AgentRequest, *, attempts: AttemptObserver
    ) -> CanonicalResponse: ...
```

ProviderCall target vocabulary is not a frozen field contract. Task 2.1a must define the
complete typed records and a versioned discriminated parent for `action_attempt`,
`rater_attempt`, and `lifecycle_operation` ownership before serialization is frozen. The
existing `CallAttemptStart` and `CallAttemptToken` remain stable compatibility exports.
Task 2.1a may deprecate them but cannot remove or repurpose them in v1; it adds the precise
new evidence vocabulary alongside them. The sketch above preserves only the runner-owned
observer role and does not freeze the new target record classes or fields.

The existing `AttemptObserver.call_started`, `call_succeeded`, and `call_failed` signatures
remain stable. The existing `AgentAdapter.act(..., attempts: AttemptObserver)` signature
remains stable. The runner implementation translates those callbacks into the additive
`ProviderCall*` evidence records, using its current action-attempt context to supply the
new discriminated parent. Existing adapters therefore remain valid while new evidence uses
the precise vocabulary.

`AgentAdapter` remains the stable act-only v1 Protocol. Task 2.2 must not add required
lifecycle methods to `AgentAdapter`; `LifecycleAgentAdapter` is a separately named additive
Protocol for native setup/session/reset/cleanup support. A runner-owned stateless
compatibility wrapper maps an existing act-only adapter to a trivial session without
changing its v1 conformance.

The public executable names and call boundaries are defined by [`public_environment_and_external_adapter_spec.md`](public_environment_and_external_adapter_spec.md): the runner invokes an `EnvironmentPlugin`, and an `AgentAdapter` reports provider activity through the runner-owned `AttemptObserver` rather than writing evidence directly. The hooks may be methods or registered functions, but their inputs, outputs, versions, and evidence must be explicit. The runner—not an environment-owned coroutine—advances the schedule, enforces budgets, and records every boundary. Every logical action is keyed by `slot_id`; one seat may own multiple decision slots in one phase, and one slot may own multiple channels. A slot may atomically emit multiple ordered channel actions in one `ActionBundle`. The adapter MUST preserve upstream call grouping, and the runner MUST NOT merge or split those calls across slots or bundles. Bundle validation uses the slot's declared `ActionChannel` membership and each channel's `min_actions`/`max_actions`: every channel count is within its declared bounds, every action has a declared channel, action IDs are unique, and sequence indices are unique and ordered within the bundle. `parse_action()` returns one atomic `ParseResult` for the whole slot response; on success it contains one `ActionBundle`. `legal()` returns one `LegalityResult` for that whole bundle. No partial bundle is applied.

`DecisionSlot` → `ActionChannel` → ordered atomic `ActionBundle` describes the
environment decision topology. It does not replace the execution/evidence lifecycle:
requesting one slot creates one `LogicalAction`; executing or retrying that request creates
an `ActionAttempt`; and each attempt records every atomic `ProviderCall` and
`ToolInvocation`. A successfully parsed logical action closes as exactly one slot-keyed
`ActionBundle`, which may contain multiple `ActionEnvelope` records.

For a simultaneous phase, the runner freezes every participant's observation from the same pre-phase state **before any slot response**, dispatches in a deterministic recorded order, hides peer actions until each bundle closes, and passes the complete slot_id-keyed bundle mapping to one deterministic `step`. Logical-action accounting is per decision slot, not per channel: one slot response creates one logical action and one or more channel actions within that bundle. Dynamic protocols express conditional transitions through declared `next_phases` plus family hook results.

---

## 3. Shared records

| Record | Purpose | Authored by |
|---|---|---|
| `FamilyManifest` | Roles, `PhaseSpec` references, capabilities, measurement declarations, baselines, scorer/reference-provider/generator implementations, and limits. | Family owner; versioned with plugin. |
| `CaseManifest` | One immutable world and family-typed payload. It never selects a model or harness. | Generator or curator. |
| `SuiteManifest` | Cases plus references to its sampling, evaluation, and analysis declarations. | Evaluation owner. |
| `SamplingPlan` | Target population or fixed panel, selection, seeds, pairing, nesting, and replicates. | Evaluation owner. |
| `EvaluationBlock` | Controlled, cross-play, self-play, or reference comparison with subject and controlled seats. | Evaluation owner. |
| `AnalysisPlan` | Estimands, inclusion/missingness, aggregation, uncertainty, and sensitivity rules. | Analysis owner. |
| `AgentProfile` | Model+harness+runtime configuration, including explicit retry policy. | Experiment owner. |
| `RunSpec` | Agent assignments, execution mode, and budgets. | Experiment owner. |
| `RunPlan` | Fully resolved, pinned, hashed cells and analysis identities, written before external calls. | Resolver. |
| `PlanCell` | One planned case × block × seat assignment × seed × replicate execution unit. | Resolver. |
| `EpisodeEventLog` | Canonical append-only record of attempts, actions, transitions, and scoring. | Runner and registered hooks. |
| `ScoreEnvelope` | Family measurement vector, reference values, validity, and provenance. | Family scorer. |
| `EvaluationReceipt` | Final inclusion, cluster, implementation, artifact, replay, and integrity record. | Runner finalizer. |

Shared fields use strict validation (`extra=forbid`). Family payloads are typed extensions validated by their registered plugin. A case says **what world this is**; the suite and run say **who plays, under what controls, and how observations may be analyzed**.

Reasoning configuration is part of the resolved agent and experiment condition, not an
unreported provider default. Actions and family outcomes remain primary; reasoning telemetry
and failure-mechanism labels are secondary diagnostics. The required fields, paired design,
budget-starvation treatment, and `objective_selection` / `strategic_modeling` /
`constraint_tracking` / `execution` taxonomy are defined in
[`reasoning_condition_and_diagnostics.md`](reasoning_condition_and_diagnostics.md).

### 3.1 Family and case sketch

```toml
spec_version = "aeread.family/0.1"

[family]
id = "housing_v1"
version = "1.0.0"
plugin_id = "aeread.housing_v1"

[environment]
topology = "market_with_private_preferences"
phase_specs = ["search_v1", "application_v1", "allocation_v1"]
needs_tools = false
needs_sandbox = false

[roles.applicant]
testable = true

[roles.housing_provider]
testable = false
scripted_policies = ["fixed_listing_provider_v1"]

[measurement]
primary_estimand = "applicant_realized_utility"
measurement_kind = "optimizable_outcome"
direction = "maximize"
optimum_lower_bound = "housing_scripted_search_v1"
comparison_baseline = "housing_scripted_search_v1"
optimum_upper_bound = "housing_exact_assignment_v1"
optimum_upper_bound_kind = "full_information_relaxation"
bound_status = "bracketed"
outcome_support = "undeclared"

[scoring]
scorer_id = "housing_outcome_v1"

[references]
bound_provider_id = "housing_exact_assignment_v1"

[generator]
generator_id = "housing_generator_v1"
difficulty_knobs = ["market_tightness", "information_friction"]
```

```yaml
spec_version: aeread.case/0.1
case_id: housing_v1__dev__000001
family_id: housing_v1
family_version: 1.0.0
split: dev
world_seed: 41001

seats:
  - {id: applicant, role: applicant}
  - {id: provider, role: housing_provider}

episode:
  max_logical_actions: 8
  termination: [allocation, withdrawal, deadline, forfeit]

visibility_policy: housing_private_preferences_v1
payload: {}                    # validated only by housing_v1

provenance:
  generator_id: housing_generator_v1
  generator_version: 1.0.0
  review_status: curated

content_sha256: "0000000000000000000000000000000000000000000000000000000000000000"
```

The zero digest is illustrative; the real digest is computed from canonical bytes with `content_sha256` removed.

### 3.2 Suite, pairing, and clustering sketch

```yaml
evaluation_blocks:
  - id: controlled_fixed_counterpart
    kind: controlled
    subject_seats: [applicant]
    controlled_profiles: {provider: fixed_listing_provider_v1}
    repetitions: 5
    seed_policy: paired

sampling:
  estimand: generated_housing_case_population
  cluster_level: world_seed
  cluster_id_fields: [generator_version, world_seed]
  paired_fields: [world_seed, subject_profile]
  replicate_level: episode_attempt
  panel_mode: sampled_panel       # or fixed_panel

aggregation:
  group_by: [family_id, primary_metric, subject_role, difficulty_bin]
  missingness: report_separately
  resampling_unit: cluster_id
  cross_family_scalar: disabled
```

The resolver expands case × evaluation block × role × repetition × seed, then records `cluster_id`, `cluster_level`, `observations_per_cluster`, pair/block membership, and resolved implementation hashes in every cell. These identities are fixed before outcomes are observed.

---

## 4. End-to-end execution

```text
1. Load Family/Case/Suite/Run/AgentProfile inputs.
2. Strictly validate schemas, phase graph, measurement declarations, and plugins.
3. Resolve all defaults, seats, retries, implementations, analysis IDs, and hashes.
4. Expand cells and durably write the immutable RunPlan.
5. Preflight every cell before the first paid or external call.
6. Create the one Episode for each PlanCell, then create episode_id and episode_attempt_id; open the append-only event log.
7. Runner selects the current PhaseSpec, creates a PhaseInstance, and resolves decision slots.
8. Runner freezes role-specific observations for every slot before any slot response and creates per-slot logical_action_id values.
9. Runner executes explicit ActionAttempt records under the resolved retry policy; the adapter records each ProviderCall and ToolInvocation.
10. Family parse_action and legal hooks classify the CanonicalResponse into one ordered atomic ActionBundle of ActionEnvelope records.
11. Runner applies the declared invalid-action policy or calls one family step.
12. Runner records the transition and selects the declared next phase.
13. On termination, seal state/evidence and compute the family ScoreEnvelope.
14. Finalize an EvaluationReceipt and close sessions/runtimes in finally.
15. Reconcile planned/attempted/valid counts and run cluster-aware aggregation.
16. Optionally derive rLLM, Harbor/ATIF, or Prime Verifiers exports.
```

### 4.1 Logical actions, action attempts, and side effects

```text
LogicalAction                           stable logical_action_id
  └── ActionAttempt 1                   always recorded
      ├── ProviderCall 0..n             atomic model-provider requests
      ├── ToolInvocation 0..n           atomic tool side effects/results
      └── CanonicalResponse 0..1        adapter result for family parsing
  └── ActionAttempt 2                   only if the declared retry policy allows
      └── its own calls/tools/response and explicit retry reason
```

`minimal_chat/1.0` disables harness-managed tools, persistent memory, and compaction. Under
that profile, one `ActionAttempt` normally contains exactly one `ProviderCall`. This is a
profile restriction, not the universal architecture: a tool-using attempt can contain
multiple provider calls and tool invocations without being a retry. A `LogicalAction` has
additional `ActionAttempt` records only when the `AgentProfile` declares the condition,
limit, session/restart semantics, and changed budget.

An `ActionAttempt` may contain zero `ProviderCall` records when an output is scripted or a
typed setup/pre-call failure occurs before any provider request. The attempt still receives
terminal evidence; a failed attempt does not fabricate a provider call or canonical response.

Every `ActionAttempt` records at least:

- `action_attempt_id`, parent `logical_action_id`, ordinal, retry reason, and whether the
  harness session is continued or restarted;
- resolved harness/profile version, total budget, start/terminal events, final
  `CanonicalResponse` reference, and typed failure;
- child `provider_call_id` and `tool_invocation_id` identities in canonical order.

Every `ProviderCall` records request hash, provider/model pins, timeout, input/output token
budgets, start and terminal events, canonical `finish_reason`, empty/truncated flags, token
usage, latency, cost, transport/provider status, raw artifact reference, and error class.
Every `ToolInvocation` records the tool/version, canonical input hash, idempotency support,
start and terminal events, result/error artifact, and any declared state-diff reference.
`retried_for_length` and the prior/new output-token limit live on the retrying action attempt
and the affected provider-call records.

If a successful final provider response is empty and `finish_reason == "length"`, the
default paper policy may create one new `ActionAttempt` with a declared higher output limit.
The first attempt and every child side effect remain in evidence. Provider transport retries
within an action attempt are separate `ProviderCall` records. SDK-level automatic retries
MUST be disabled where possible; otherwise the adapter must expose every request or declare
the observability limitation. A tool side effect with an ambiguous outcome is never silently
reissued.

### 4.2 Failure taxonomy

Failures are classified at the layer that owns them:

| Class | Examples | Measurement consequence |
|---|---|---|
| `retryable_infrastructure` | timeout, rate limit, transient transport/provider 5xx | Retry only under the declared policy. Exhaustion is `invalid_measurement`. |
| `agent_action_failure` | missing, malformed, or illegal action after a successful response | Apply the family-declared no-op, penalty, or forfeit. The economic episode can remain valid. |
| `integration_or_configuration` | missing plugin, incompatible schema, unpinned implementation, failed preflight | Invalid cell; normally reject before paid calls. |
| `environment_failure` | hook exception or inconsistent transition | `invalid_measurement`; never turn into economic zero. |
| `oracle_or_scorer_failure` | scorer exception, missing required reference, non-deterministic replay | `invalid_measurement` for affected metrics/receipt. |

A legal action that produces zero or negative utility is a valid economic observation. A missing or corrupted observation is not zero.

---

## 5. Evidence, identity, and resume

`events.jsonl` is the source of truth. Per-seat trajectories, public transcripts, call ledgers, and the joint environment timeline are deterministic projections.

Every event contains:

```text
event_id | sequence | event_type | occurred_at
run_plan_id | cell_id | episode_id | episode_attempt_id
phase_spec_id | phase_instance_id? | logical_action_id? | action_attempt_id?
provider_call_id? | tool_invocation_id?
visibility | payload_ref/hash | prior_event_hash | event_hash
```

Identities are stable within a resolved plan. `sequence` supplies a total append order; phase-local actor order is separately recorded. Events carry one of `public`, `seat:<id>`, or `evaluator_only`. A projection may omit payloads but must retain event identities and hashes so reviewers can reconcile views without exposing private information.

### Durability rules

1. Append and flush `episode_attempt_started`, `logical_action_started`,
   `action_attempt_started`, `provider_call_started`, and `tool_invocation_started` before
   the relevant work or side effect.
2. Append exactly one terminal success, failure, or `outcome_unknown` event for each
   started `ActionAttempt`, `ProviderCall`, and `ToolInvocation`.
3. Record action parsing, legality, transition, termination, scoring, and receipt sealing as separate boundaries.
4. Score only sealed evidence. A scorer is deterministic and never calls the candidate/provider.
5. Preserve raw artifacts content-addressably even when canonicalization or parsing fails.

### Crash/resume rules

On resume, the runner validates the plan and event hash chain, then reconstructs state by deterministic replay. It never silently reissues an external side effect whose completion is ambiguous. If the provider supports a recorded idempotency key, the adapter may reconcile it; otherwise the attempt becomes `outcome_unknown`, that episode attempt is invalid, and a new `episode_attempt_id` is required. Resume decisions themselves are events.

The `EvaluationReceipt` binds suite/case/plan hashes, cluster identities, resolved agent configurations, parser/environment/scorer/reference-provider versions, event and artifact roots, observability limits, replay level, score or typed failure, and inclusion status. Paper tables consume validated receipts rather than ad hoc logs.

---

## 6. Measurement contract

### 6.1 Route each estimand before selecting references

The routing unit is an estimand, not a domain label. One case can have exact social-welfare bounds while private capture remains comparative.

1. `property_or_answer`: validate a known answer, feasibility condition, axiom, or equilibrium property. Report pass/error or distance; do not invent a policy optimum.
2. `optimizable_outcome`: define an objective over a feasible policy class, then declare direction, information set, horizon, opponent/control condition, and stochastic expectation before recording bounds.
3. `comparative_or_human_judged`: name the compared policy, system, human, or rater protocol. Make no optimality claim unless a separate model supplies one.

Minimization metrics are converted to a canonical higher-is-better orientation or carry reversed inequalities explicitly. This prevents metrics such as violation counts from entering a higher-is-better saturation screen backwards.

`measurement_kind` states the kind of claim. The semantic verifier, reference object,
stochastic estimation mode, integrity gate, and any hybrid composition are declared
separately in a versioned `VerifierSpec`. The general families, valid ratio constructions,
and composition rules are defined in [`verifier_taxonomy.md`](verifier_taxonomy.md). A
compact real-world case and benchmark crosswalk is frozen in
[`verifier_case_mapping.md`](verifier_case_mapping.md), with the exhaustive corpus audit
kept separately in [`problem_bound_case_audit.md`](problem_bound_case_audit.md).

### 6.2 Typed optimization bounds and comparison references

For a maximization estimand, the contract is:

`V_LB <= V* <= V_UB`

| Field | Meaning | Requirement |
|---|---|---|
| `optimum_lower_bound` (`V_LB`) | Value of a witnessed feasible policy or best-known feasible result. | Required for an optimality-gap claim; implementation, information scope, and result provenance required. |
| `optimum_upper_bound` (`V_UB`) | Certified relaxation, exact optimization result, or proof that no feasible policy in the declared problem can do better. It may use more information or looser constraints, which must be recorded. | Required for saturation or certified regret claims. |
| `comparison_baseline` (`B`) | Named executable policy, system, human, or reference used by the scientific comparison. It may also witness `V_LB`, but it is a distinct semantic field. | Required for every comparative claim. |
| `outcome_support_min`, `outcome_support_max` | Optional bounds applying to every admissible realized outcome. | Both required before claiming a normalization is bounded by its support. |

**A feasible policy is not an outcome floor.** It lower-bounds the unknown optimum; another policy or model can realize a worse outcome. Likewise, a metric maximum is not automatically a problem-specific upper bound. Every bound records objective/version, units, direction, feasible set, information set, horizon, opponent condition, proof type, implementation, and validity domain.

The strongest valid status is stored per estimand:

- `exact_solved`: lower and upper bounds coincide;
- `epsilon_solved`: their certified gap is at most a predeclared epsilon;
- `bracketed`: both exist with a material gap;
- `lower_bound_only`: a feasible witness exists without a certified upper bound;
- `baseline_only`: only a scientific comparison is justified;
- `descriptive_only`: no valid comparative reference exists.

A best observed result is a feasible witness, not an oracle. A support-normalized score `(M - support_min) / (support_max - support_min)` is permitted only when both support bounds are valid. Bound gaps and baseline improvements otherwise remain in native units. Equal numeric values across families still do not have equal scientific meaning, so `cross_family_scalar: disabled` remains the default. The survey-wide application is documented in [`problem_bound_case_audit.md`](problem_bound_case_audit.md).

### 6.3 Saturation and the Tier-0 screen

Tier 0 is a cheap, measure-aware frontier/headroom screen. It may use the case's primary outcome, score spread, failure/coverage, and improvement over `B` without requiring a case oracle.

- `headroom_visible`: credible systems or conditions still separate on the case measure.
- `compressed_undecidable`: scores are compressed, but no defensible `optimum_upper_bound` exists.
- `ceiling_exhausted`: `V_UB - M_best` is within a predeclared epsilon for the same estimand, with adequate cluster-level uncertainty and coverage.

Only `ceiling_exhausted` supports a saturation claim. A relaxation can certify saturation when its upper-bound gap is already small; it need not itself be attainable. Compression without a valid `optimum_upper_bound` is `compressed_undecidable`.

### 6.4 Welfare, private gain, and distribution are distinct

The standard outcome vector keeps these quantities separate:

```python
class EconomicOutcome:
    primary_metric: MetricValue
    social_welfare: MetricValue | None
    principal_utility: MetricValue | None
    utility_by_seat: dict[str, MetricValue]
    capture_by_seat: dict[str, MetricValue]
    reference_residual: dict[str, MetricValue]
```

- `social_welfare` asks whether the allocation or agreement creates aggregate value.
- `principal_utility` asks how much the evaluated seat/client obtains.
- `capture_by_seat` starts from observed gain `g_i = u_i(outcome) - d_i`, where each disagreement utility `d_i` is declared. It may additionally report shares only when the family defines a valid common surplus denominator.
- `reference_residual` reports gaps to baselines or typed optimum bounds.

No runner-defined weighted composite resolves a conflict among them. A suite names one primary estimand and reports the others as co-primary or diagnostic outcomes. This prevents high total welfare from hiding extraction from a principal, and prevents high private capture from being mistaken for social efficiency.

### 6.5 Bargaining references

Observed private gain and a normative bargaining reference are different objects. `symmetric_nash_par` is permitted only for a fixed realized transferable-utility bargain with a declared status quo/disagreement point, equal bargaining weights, and two symmetric claimants. Under those assumptions it is the equal-gains special case of Nash bargaining; it is not a universal definition of fair capture.

For other structures, the family may declare a method only when its prerequisites are available:

| Method | Use when | Required object |
|---|---|---|
| weighted Nash bargaining | bargaining weights are substantively specified | feasible utility set and disagreement point |
| generalized n-party Nash | one joint bargain has more than two parties | feasible utility set, disagreement vector, weights |
| Shapley value | coalition contributions are the intended concept | coalition value function for all required coalitions |
| core / least-core | coalition stability is the intended concept | transferable-utility coalition game |
| nucleolus | lexicographic minimization of coalition excess is justified | complete coalition game and solver |

These are family-owned, versioned metrics with provenance—not fallback calculations invented by the runner. If the necessary feasible set, disagreement utilities, weights, or coalition values are unavailable, report observed `capture_by_seat` without a normative bargaining score.

### 6.6 Minimal score record

```python
class ScoreEnvelope:
    status: Literal["ok", "invalid_measurement"]
    measurement_kind: str
    direction: str
    bound_status: str | None
    primary: MetricValue | None
    metrics: dict[str, MetricValue]
    utility_by_seat: dict[str, float]
    capture_by_seat: dict[str, float]
    references: dict[str, ReferenceValue]
    outcome: dict
    validity: ValidityReport
    scorer: ImplementationRef
    oracle: ImplementationRef | None
    evidence_refs: list[str]
```

---

## 7. Cluster contract and uncertainty

A **cluster** is the smallest unit that was independently sampled, randomized, or assigned for the estimand. It is a property of the experiment design, not a visual grouping discovered after results arrive.

Default rules:

- All calls, decisions, turns, and agent seats within one episode share an episode cluster unless a larger sampled unit links them.
- When multiple arms or agent configurations reuse the same `world_seed`, they form a paired seed block and share the analysis `cluster_id` for population uncertainty.
- Cases generated from the same latent market, household, graph, or source document share the parent cluster if that parent was the independently sampled unit.
- Stochastic reruns are replicates nested inside their case/seed cluster; increasing reruns does not increase the number of independent case draws.
- Under `fixed_panel`, uncertainty is conditional on that fixed case panel. It must not be described as generalization to a population of cases.

Every `RunPlan` cell and receipt records `cluster_id`, `cluster_level`, `observations_per_cluster`, parent/block IDs, pairing fields, replicate index, and panel mode. If a suite targets more than one estimand, it declares a cluster mapping for each estimand.

Analysis must aggregate to one observation per cluster or use a method that respects dependence, such as a cluster bootstrap, paired/block randomization inference, cluster-robust standard errors with enough clusters, or an explicitly validated hierarchical model. It must **resample clusters**, not treat decision rows such as turns, calls, or offers as independent samples.

Reports include the number of clusters, cluster-size distribution, number of nested replicates, missing clusters/cells, and—when relevant—the design effect and effective sample size. A 3–5 episode run is an instrumentation/admission pilot, not evidence of a tight population interval.

---

## 8. Family-owner conformance package

Each family owner supplies:

| Required declaration | Questions to answer |
|---|---|
| **Identity** | Family ID/version, owner, research question, and composition with other protocols. |
| **Roles and phases** | Seats, testable/controlled roles, `PhaseSpec` graph, simultaneous boundaries, and actor rules. |
| **Observation and privacy** | What each role sees; public, seat-private, evaluator-only fields; expected context size. |
| **Actions** | Phase/role schema, parser, legality, and consequence of malformed or illegal actions. |
| **State and termination** | Initial state, randomness, transitions, natural terminal states, budgets, and forfeits. |
| **Measurement** | Primary estimand and kind, direction, `comparison_baseline`, typed optimum/support bounds, welfare/private/capture fields, scorer, and oracle validity domain. |
| **Sampling** | Independent sampling/assignment unit, pairing, linked cases, replicate nesting, and fixed-vs-sampled panel. |
| **Generation** | Generator, difficulty knobs, split isolation, external data, and privacy constraints. |
| **Baselines and admission** | Executable baselines, provider-free fixtures, admission rule, replay, and observability requirements. |

Provider-free fixtures include:

- one deterministic successful trajectory;
- one valid no-deal/no-match/denial outcome where applicable;
- malformed and parseable-but-illegal actions for each relevant phase;
- scorer/reference fixtures with exact expected values;
- a simultaneous-observation fixture where applicable;
- a private-information noninterference check;
- deterministic state/score replay and interrupted-resume fixtures;
- a small admission pilot separating format failures from bad decisions.

Family owners define economic semantics. The shared-runner owner must not invent their utilities, oracle, coalition game, or legal actions. Environment and measurement plugins must not implement private provider logging, retry systems, receipt formats, or paper aggregation.

---

## 9. Migration and validation

The existing `exchange_v1_runner.py`, roles, validity, and scoring paths contain assets worth preserving: self-contained run directories, offline/live-frozen/replay modes, snapshots, hashes, model pins, call-funnel checks, invalid-measurement handling, and AER semantics.

### Reference implementations

1. **`exchange_v1` compatibility wrapper**
   - Keep the existing ten-stage engine internally during migration.
   - Map each stage to declarative phases and canonical events.
   - Bridge current scoring into `ScoreEnvelope`.
   - Prove parity for terminal allocation, `w_real`, denominator/tier, AER, failure class, evidence counts, and replay before removing the old path.

2. **`housing_v1` clean native plugin**
   - Implement directly against `PhaseSpec` and typed hooks.
   - Include private applicant preferences, structured search/application/allocation actions, and a controlled provider/market policy.
   - Supply an executable `comparison_baseline` and feasible witness; provide `optimum_upper_bound` only where its objective, information scope, constraints, and proof are defensible.
   - Declare world/case clustering and paired seeds in the suite.

The abstraction is credible only when both paths run through the same scheduler, explicit attempts, event log, receipt, cluster metadata, and score envelope without family branches in the kernel.

### First external measurement-validation adapter

After the `exchange_v1` compatibility path and `housing_v1` native path pass the shared
conformance suite, the first external adapter is the pinned tau3 retail refund/return
surface. Its role is to prove that the same runner can preserve deterministic
`property_or_answer` state validation alongside housing's bounded
`optimizable_outcome`, while retaining the upstream judge-dependent reward as a separate
compatibility result. The pin, pilot task IDs, component-level parity gate, receipts,
cluster semantics, saturation language, STATE-Bench follow-on, and native `refund_v1`
admission rule are specified in
[`refund_external_benchmark_integration.md`](refund_external_benchmark_integration.md).

### Minimum gates before calling the runner paper-ready

- phase graph, scheduling, simultaneous observations, and invalid-action policies pass conformance tests;
- every logical action reconciles to explicit `ActionAttempt`, `ProviderCall`, and
  `ToolInvocation` records with no hidden retries or side effects;
- stable IDs, append order, visibility projections, interrupted resume, and artifact hashes validate;
- every planned cell reconciles to a valid receipt or typed failure/exclusion;
- zero/negative outcomes remain distinct from missing measurements;
- every comparative claim has a valid `comparison_baseline`; certified regret or saturation claims additionally have a valid `optimum_upper_bound`, while bounded normalization additionally requires valid outcome-support bounds;
- welfare, principal utility, and capture are reported separately where applicable;
- cluster-aware analysis matches declared sampling, pairing, and panel semantics;
- exchange old/new parity is demonstrated and the native housing fixtures pass;
- paper tables regenerate from validated receipts;
- interoperability claims have parity/round-trip evidence or are labeled future work.

## Design lineage

The proposal retains the useful taskset (what), harness (how), and runtime (where) separation used by adjacent evaluation frameworks, but AERead defines its own benchmark truth. The runner owns auditable scheduling and execution; families provide declarative economic hooks. AERead additionally requires a joint economic timeline, explicit attempt/failure accounting, typed information projections, within-case measurement references, cluster-aware receipts, and deterministic replay/resume. The typed measurement route was checked against 22 external papers, the AERead paper, and all five native pilot cases in [`problem_bound_case_audit.md`](problem_bound_case_audit.md).
