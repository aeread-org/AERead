# AERead Public Environment Interface and External Benchmark Adapter Specification

> **Status:** proposed design delta; authoring, planning, exact-version developer registry/discovery, and evidence foundations exist, while formal discovery and the executable kernel remain incomplete
>
> **Author:** Codex, for Zeyu Sun
>
> **Date:** 2026-08-24
>
> **Depends on:** [`shared_runner_design.md`](shared_runner_design.md); current PR #7 design
> source `155d8fc`, integrated locally at merge `b5239cd`

## 0. Executive decision

AERead should publish a versioned environment-authoring SDK, not only an internal shared runner. The public boundary must let first-party case owners, external benchmark adapters, and future third-party contributors enter the same runner without adding family-specific branches to the kernel.

The recommended architecture is:

```text
external repository / native case data
              |
              v
  BenchmarkSourceAdapter       source pin, license, materialization, parity
              |
              v
       CaseManifest + artifacts
              |
              v
       EnvironmentPlugin       economics, information, legal actions, transition
              |
              v
       Shared Runner Kernel    schedule, calls, attempts, evidence, replay, receipt
              |
              v
       VerifierPlugin          deterministic scoring over sealed evidence
              |
              v
       EvaluationReceipt       paper/training/export source of truth

AgentProfile -> AgentAdapter -> CanonicalResponse
ExecutionBackend supplies local/subprocess/container/remote execution when required.
```

This is a framework contract, not a universal game schema. State, action, phase graph, topology, utility, and termination remain family-owned. AERead standardizes identity, scheduling boundaries, evidence, versioning, provenance, measurement declarations, and receipts.

The work should proceed in two stages:

1. implement the public SDK and minimum shared-runner kernel, then prove Exchange compatibility and Housing native conformance;
2. implement three external adapter spikes: EconEvals Procurement, tau3 Retail, and AgenticPay.

External adapters cannot be meaningfully implemented before the minimum kernel exists. This document specifies the end-state contract; the implementation-status map in Section 11 distinguishes the landed foundation from the missing runtime.

---

## 1. What AERead is publishing

AERead is both:

- a benchmark framework for authoring, executing, measuring, and auditing heterogeneous economic-agent tasks; and
- a native benchmark suite containing AERead-owned families such as Exchange and Housing.

An external benchmark is not “converted into the AERead environment.” It retains its own identity and scientific claims. AERead supplies a pinned, declared adapter that lets the upstream benchmark execute through AERead's evidence and evaluation protocol.

The public product is therefore not one `Env` class. It is a versioned set of orthogonal contracts:

| Contract | Question answered | Owner |
|---|---|---|
| `BenchmarkSourceAdapter` | Where did cases/code come from, and how are they pinned and materialized? | external adapter author |
| `EnvironmentPlugin` | How does this economic world expose observations, accept legal actions, transition, and terminate? | family/adapter author |
| `VerifierPlugin` | What is measured, against which reference, and how is it scored from sealed evidence? | family/measurement owner |
| `AgentAdapter` | How is a resolved agent configuration invoked and normalized? | harness/provider integration owner |
| `ExecutionBackend` | Where does code run and how is its lifecycle isolated? | runtime integration owner |
| `RunnerKernel` | How are phases, attempts, evidence, replay, receipts, and coverage controlled? | AERead core |

A benchmark package composes these objects:

```text
BenchmarkPackage
  = source identity + task/case set
  + environment plugin
  + verifier specifications
  + suite sampling/assignment protocol
  + admissible agent/runtime capabilities
```

This distinction prevents three common errors:

- treating a GitHub repository as a ready-to-run benchmark without pinning its generator, driver, and scorer;
- treating an environment reward as the paper's estimand without declaring the comparison or aggregation protocol;
- forcing unrelated benchmarks into one state/action schema merely because one runner executes them.

---

## 2. Frozen principles and proposed design delta

All frozen decisions in `shared_runner_design.md` remain normative: full agent configuration is the unit under test; controlled counterparts are the primary block; the runner owns scheduling; retries are explicit; scoring is family-owned; receipts are canonical; and Exchange parity precedes external adapters.

This specification proposes one required amendment.

### 2.1 Replace seat-keyed actions with decision slots and channels

The current baseline sketches:

```python
eligible_actors(...) -> Sequence[str]
step(..., actions: Mapping[str, ActionEnvelope])
```

That is insufficient for a market in which one seat must produce several directed actions in one phase. For example, one AgenticPay buyer negotiates with multiple sellers in parallel and the official driver invokes the buyer separately for each buyer-seller edge. A mapping keyed only by buyer seat cannot preserve both actions or their distinct call evidence.

The public SDK should use:

```python
class ActionChannel(StrictModel):
    channel_id: str
    recipient_seat_ids: tuple[str, ...]
    action_schema_ref: str
    min_actions: int = 1
    max_actions: int | None = 1


class DecisionSlot(StrictModel):
    slot_id: str
    seat_id: str
    channels: tuple[ActionChannel, ...]
    observation_schema_ref: str
    response_schema_ref: str
    order_key: str


class ActionEnvelope(StrictModel):
    action_id: str
    slot_id: str
    channel_id: str
    actor_seat_id: str
    sequence_index: int
    payload: dict[str, object]


class ActionBundle(StrictModel):
    slot_id: str
    actions: tuple[ActionEnvelope, ...]
```

One `DecisionSlot` is one logical agent decision and therefore one `logical_action_id`. A seat may own several slots in the same phase when the upstream protocol makes independent calls, or one slot may contain several channels when one response is supposed to coordinate several directed actions. A channel declares action cardinality, so one response can contain an ordered tool-call sequence as well as a single offer. One successful canonical response parses into one atomic `ActionBundle`. The family adapter must choose the slot grouping that preserves the original decision opportunity; the runner does not merge or split calls for convenience.

For simultaneous phases, all slot observations are frozen from the same pre-phase state. No parsed peer action is revealed until every required bundle is closed or its declared failure consequence has been applied.

This amendment requires explicit design review because it changes the public action boundary. It does not change family ownership of action semantics.

---

## 3. Public SDK surface

### 3.1 Package and version policy

AERead already declares package version `0.1.0`, and `aeread.sdk.v1` is the current stable
authoring namespace. Shared-runner design work may add APIs, but it cannot retroactively
move the compatibility boundary to a future release. Preview manifests retain their
independent schema versions such as `aeread.case/0.1`, and each serialized record declares
its own version.

The existing `CallAttemptStart` and `CallAttemptToken` remain stable compatibility exports.
Task 2.1a may deprecate them but must not remove, repurpose, or change their v1 field and
validation semantics. The new kernel can add the more precise `ActionAttempt`,
`ProviderCall`, `ToolInvocation`, and `RaterAttempt` vocabulary alongside them and must not
use the legacy records for new evidence. Any breaking removal or incompatible serialized
change requires `aeread.sdk.v2`.

Rules:

- `aeread.sdk.v1` exports stable author-facing protocols, immutable models, errors, and test helpers;
- runner implementation details live under `aeread.runner` and are not part of the compatibility promise;
- unknown manifest fields are rejected;
- every plugin declares `sdk_api = "aeread.sdk/v1"` and its own semantic version;
- breaking API changes require `aeread.sdk.v2`; additive optional fields require a schema-version increment and compatibility tests;
- canonical bytes use UTF-8 JSON, sorted keys, compact separators, no NaN/Infinity, and an explicit `aeread.cjson/1` algorithm identifier before SHA-256 hashing.

The implementation should use Pydantic 2 (`pydantic>=2.8,<3`) for strict validation, immutable records, discriminated unions, and JSON schema export. This is one deliberate new core dependency and must be called out in the implementation PR.

### 3.2 Environment contract

```python
from typing import Mapping, Protocol, Sequence


class EnvironmentPlugin(Protocol):
    manifest: FamilyManifest

    def validate_case(self, payload: Mapping[str, object]) -> FamilyCase: ...

    def initial_state(
        self, case: FamilyCase, cell: PlanCell
    ) -> FamilyState: ...

    def phase_graph(self, case: FamilyCase) -> PhaseGraph: ...

    def decision_slots(
        self,
        case: FamilyCase,
        state: FamilyState,
        phase: PhaseSpec,
    ) -> Sequence[DecisionSlot]: ...

    def observe(
        self,
        case: FamilyCase,
        state: FamilyState,
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> ObservationEnvelope: ...

    def parse_action(
        self,
        case: FamilyCase,
        state: FamilyState,
        phase: PhaseSpec,
        slot: DecisionSlot,
        response: CanonicalResponse,
    ) -> ParseResult: ...

    def legal(
        self,
        case: FamilyCase,
        state: FamilyState,
        phase: PhaseSpec,
        bundle: ActionBundle,
    ) -> LegalityResult: ...

    def step(
        self,
        case: FamilyCase,
        state: FamilyState,
        phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle],  # keyed by slot_id
    ) -> TransitionResult: ...

    def terminal(
        self, case: FamilyCase, state: FamilyState
    ) -> TerminalResult | None: ...

    def outcome(
        self, case: FamilyCase, terminal: TerminalResult
    ) -> FamilyOutcome: ...
```

Contract rules:

- hooks receive serializable, versioned values and return typed results;
- the runner invokes hooks; a plugin never receives an unrestricted `run(ctx)` callback;
- `PhaseGraph` declares all legal next phases, while `TransitionResult.next_phase_id` selects one declared edge;
- `decision_slots()` may depend on current state but must return deterministic ordering and stable slot identities under replay;
- `observe()` returns only the projection authorized for that slot; evaluator-only data never enters `AgentRequest`;
- `parse_action()` classifies malformed responses without mutating state;
- `legal()` classifies well-formed but impermissible actions without mutating state;
- `step()` is the single atomic mutation boundary and cannot call an agent/provider;
- `terminal()` and `outcome()` are deterministic and cannot call an agent/provider;
- family randomness is drawn from runner-supplied recorded RNG streams, never ambient global randomness.

### 3.3 Observation and canonical response boundary

> **Target vocabulary only; field-level Python contract is not frozen:** provider-call
> write-ahead evidence will use `ProviderCallStart` / `ProviderCallToken` vocabulary,
> but Task 2.1a must freeze the complete typed records and serialization.

```python
class ObservationEnvelope(StrictModel):
    schema_ref: str
    slot_id: str
    visible_payload: dict[str, object]
    public_event_refs: tuple[str, ...]
    private_event_refs: tuple[str, ...]


class AgentRequest(StrictModel):
    logical_action_id: str
    phase_id: str
    slot: DecisionSlot
    observation: ObservationEnvelope
    context: AgentContext
    budget: AttemptBudget


class AttemptObserver(Protocol):
    """Runner-owned observer role; exact typed methods are frozen in Task 2.1a."""
    ...


class AgentAdapter(Protocol):
    async def act(
        self, request: AgentRequest, *, attempts: AttemptObserver
    ) -> CanonicalResponse: ...
```

Task 2.1a will freeze a versioned discriminated parent linking every provider-call record
to exactly one of `action_attempt`, `rater_attempt`, or `lifecycle_operation`, together
with the complete identity, request, budget, terminal, and provenance fields. This section
therefore declares vocabulary and ownership only; it does not define partial record classes.

The existing `CallAttemptStart` and `CallAttemptToken` remain stable compatibility exports,
but new adapter contracts should use the more precise vocabulary once Task 2.1a adds it.
Task 2.1a may deprecate the legacy surface and owns the additive versioned records; it may
not remove or repurpose the v1 exports.

The adapter owns provider/harness-specific wire formats. OpenAI Responses, Chat Completions, Anthropic Messages, a CLI agent, or an rLLM gateway may return different native objects; each adapter normalizes them into `CanonicalResponse` before the family parser or scorer consumes them. `CanonicalResponse` includes normalized content/tool calls, finish reason, usage, raw artifact reference, and an optional harness-trace reference.

Canonicalization records, rather than erases, meaningful distinctions. It does not force every harness into a shared Python class or provider API internally; an HTTP service, CLI process, rLLM flow, or in-process object may sit behind the adapter.

The runner writes `logical_action_started` and `harness_invocation_started` before invoking `act()`. A direct-model adapter reports provider-call start immediately before each provider request and reports exactly one terminal result through the observer boundary. An instrumented multi-turn harness reports every internal provider attempt through the same boundary; an interception layer may do this on its behalf. The adapter never writes the event store directly. Task 2.1a freezes the observer method names together with the record contract.

If invocation throws, the harness invocation and any started provider attempts still exist. If a harness cannot expose internal calls, it declares `call_observability = "logical_only"`; the runner records the outer invocation but does not fabricate provider rows, and the adapter cannot satisfy `paper_primary`. Recording only after `act()` returns loses evidence for exactly the calls most important to benchmark validity.

### 3.4 Verifier contract

```python
class VerifierPlugin(Protocol):
    manifest: VerifierManifest

    def score(
        self,
        case: FamilyCase,
        outcome: FamilyOutcome,
        evidence: SealedEvidenceView,
    ) -> ScoreEnvelope: ...
```

A verifier is deterministic over sealed artifacts. It may execute a pinned solver or compare terminal database state, but it may not call the candidate agent/provider. LLM judges, if a study needs them, are separate evaluator agents with their own configuration, trace, uncertainty, and failure accounting; they are never silently embedded in a deterministic scorer.

`ScoreEnvelope` retains measurement kind, direction, typed references, primary metric, component metrics, per-seat utility/capture where defined, validity, scorer/oracle versions, and evidence references. Per-seat reward is required only for seats included in a training or role-comparison estimand; a controlled mechanism seat can have utility recorded without being a trainable target.

### 3.5 Source and official-parity contract

External benchmark ingestion is split so source handling cannot quietly control runtime semantics:

```python
class BenchmarkSourceAdapter(Protocol):
    manifest: BenchmarkAdapterManifest

    def source_ref(self) -> UpstreamSourceRef: ...
    def enumerate_cases(self, split: str) -> Sequence[UpstreamCaseRef]: ...
    def materialize_case(self, ref: UpstreamCaseRef) -> MaterializedCase: ...
    def parity_fixtures(self) -> Sequence[ParityFixture]: ...


class OfficialVerifierBridge(Protocol):
    def evaluate_official(self, fixture: ParityFixture) -> OfficialResult: ...
    def evaluate_aeread(self, fixture: ParityFixture) -> ScoreEnvelope: ...
    def compare(self, official: OfficialResult, aeread: ScoreEnvelope) -> ParityReport: ...
```

`materialize_case()` produces immutable local artifacts; it does not make provider calls. When the upstream generator is not deterministic, the adapter stores the fully generated instance and hashes it rather than claiming seed-only reproducibility.

Official parity is an admission test, not an excuse to execute opaque upstream orchestration in the paper path. If only score parity is possible, the capability declaration says so and AERead must not claim state replay or full call observability.

### 3.6 Execution backend

```python
class ExecutionBackend(Protocol):
    async def start(self, spec: RuntimeSpec) -> RuntimeHandle: ...
    async def run(self, handle: RuntimeHandle, request: ProgramRequest) -> ProgramResult: ...
    async def read(self, handle: RuntimeHandle, path: str) -> bytes: ...
    async def write(self, handle: RuntimeHandle, path: str, data: bytes) -> None: ...
    async def stop(self, handle: RuntimeHandle) -> None: ...
```

The initial backend is in-process/local subprocess. Docker, a remote sandbox, or Harbor can be added when an adapter truly needs filesystem/terminal isolation. AERead should not require Harbor merely to run economic environments that have no sandbox workload. Runtime location is orthogonal to multi-agent scheduling.

---

## 4. Plugin discovery and trust

Third-party packages register plugins through Python entry points:

```toml
[project.entry-points."aeread.environments"]
my_market_v1 = "my_package.environment:plugin"

[project.entry-points."aeread.benchmark_sources"]
my_benchmark_v1 = "my_package.source:adapter"

[project.entry-points."aeread.verifiers"]
my_market_score_v1 = "my_package.verifier:plugin"

[project.entry-points."aeread.agent_adapters"]
my_harness_v1 = "my_package.agent:adapter"

[project.entry-points."aeread.execution_backends"]
my_runtime_v1 = "my_package.runtime:backend"
```

The **proposed formal-mode resolver** resolves `(plugin_id, plugin_version, sdk_api)` only
after attesting the distribution and entry-point provenance. The current implementation
provides exact-version developer registration/discovery, but it loads an entry point before
validating the returned plugin object; it is therefore not a trusted paper-mode discovery
path. A case manifest may reference a registered ID but may not contain an arbitrary import
path or executable code. That restriction prevents case data itself from naming an import,
but it does not attest the installed distribution.

Core imports must stay lightweight. tau3, AgenticPay, Gurobi, vLLM, SGLang, Docker, and Harbor dependencies belong in adapter extras or isolated adapter distributions. Importing `aeread.sdk.v1` must not import any of them.

---

## 5. Standard manifests and provenance

### 5.1 `BenchmarkAdapterManifest`

```yaml
spec_version: aeread.benchmark_adapter/0.1
adapter_id: agenticpay_text_v1
adapter_version: 0.1.0
sdk_api: aeread.sdk/v1

upstream:
  repo_url: https://github.com/SafeRL-Lab/AgenticPay
  commit: 1ff4e1a2686eac6a07ff559df6d50329c6fd9f69
  release: null
  license_spdx: MIT
  source_paths: [agenticpay/envs, agenticpay/metrics]
  patchset_sha256: null

plugins:
  environment_id: aeread.agenticpay_text_v1
  verifier_ids: [aeread.agenticpay_compatibility_v1]

capabilities:
  schedule_control: runner
  observation_visibility: partial
  call_observability: full
  state_replay: deterministic
  score_parity: component
  privacy_enforcement: runner
  trainability: per_seat
```

Required upstream provenance includes repository URL, immutable commit, tag/release when relevant, SPDX license, source paths, any AERead patchset hash, materialized artifact hashes, adapter distribution/version, upstream scorer reference, and parity report hash.

### 5.2 Capability declaration

Capabilities are independent axes, not one vague quality tier:

| Field | Allowed values | Meaning |
|---|---|---|
| `schedule_control` | `runner`, `upstream`, `opaque` | who decides turns/phases/calls |
| `observation_visibility` | `full`, `partial`, `opaque` | whether AERead can audit seat projections |
| `call_observability` | `full`, `logical_only`, `opaque` | whether every external attempt is visible |
| `state_replay` | `deterministic`, `score_only`, `none` | strongest supported replay claim |
| `score_parity` | `exact`, `component`, `statistical`, `none` | relation to official evaluation |
| `privacy_enforcement` | `runner`, `upstream`, `unverified` | who prevents cross-seat leakage |
| `trainability` | `per_seat`, `joint_only`, `none` | available credit-assignment granularity |

Admission profiles derive from these fields:

- `paper_primary`: runner-controlled schedule, auditable observations/actions, full attempts, deterministic replay, and exact or predeclared component parity;
- `training`: `paper_primary` evidence plus per-seat logical-action, token, outcome, and reward linkage for every trainable seat;
- `interop_only`: may preserve only upstream execution or score parity, must disclose limitations, and cannot support AERead's core auditability claims.

An adapter is admitted to a profile only by a generated `AdmissionReport`. Missing capability is not converted to `false` evidence or a score of zero.

---

## 6. Contributor experience

AERead should support three contribution paths with increasing responsibility:

| Contribution | Contributor supplies | AERead supplies |
|---|---|---|
| data-only case for an existing family | strict `CaseManifest` payload and provenance | environment, verifier, conformance |
| new native family | environment + verifier plugins, manifests, fixtures | kernel, attempts, events, receipts, CLI |
| external benchmark | source adapter + family/verifier bridge + official parity fixtures | pinning schema, plugin registry, admission and reporting |

Recommended CLI:

```text
aeread env init <plugin-id>                 scaffold package and fixtures
aeread env validate <plugin-id>             validate manifests and phase graph
aeread env test <plugin-id>                 provider-free conformance suite
aeread benchmark inspect <adapter-id>       show source pin/license/capabilities
aeread benchmark materialize <adapter-id>   create immutable CaseManifests
aeread benchmark parity <adapter-id>        compare official and AERead results
aeread suite resolve <suite.yaml>            write immutable RunPlan
aeread suite run <run-plan-id>              execute/resume planned cells
aeread receipt verify <receipt.json>        validate hashes, replay, and inclusion
```

`aeread env init` generates one successful fixture, one malformed action, one parseable-but-illegal action, one terminal no-deal case where applicable, one privacy fixture, and one score fixture. The contributor edits economics rather than reconstructing runner plumbing.

The conformance kit must test:

- strict schema/version rejection and canonical hashes;
- deterministic initial state and phase graph;
- stable slot/channel/action identities;
- sequential and simultaneous scheduling;
- frozen simultaneous observations and private noninterference;
- malformed, illegal, missing, timed-out, and extra channel actions;
- atomic transition and deterministic ordering;
- natural terminal versus budget/forfeit terminal;
- scorer determinism and zero-versus-invalid measurement;
- write-ahead attempts, raw/canonical evidence, interrupted resume, and hash-chain integrity;
- per-seat and public trajectory projections;
- official parity at the capability level claimed by the adapter.

---

## 7. End-to-end execution contract

```text
1. Registry resolves trusted source/environment/verifier/agent/runtime plugins.
2. Source adapter verifies upstream pin/license and materializes immutable cases.
3. Resolver validates Case/Suite/Agent/Run specs and capability compatibility.
4. Resolver expands cells and writes the immutable RunPlan before external calls.
5. Runner opens episode attempt and append-only event log.
6. Runner selects a declared phase and obtains deterministic DecisionSlots.
7. Runner freezes each slot's ObservationEnvelope from the pre-phase state.
8. For each slot, runner writes logical_action_started and harness_invocation_started.
9. AgentAdapter reports observable provider attempts through AttemptObserver and returns a CanonicalResponse, or a typed invocation/attempt failure is recorded.
10. Environment parses response into ActionBundle and validates legality.
11. Runner closes missing/invalid bundles under the declared phase policy.
12. Environment applies all closed bundles in one atomic step.
13. Runner records transition, next phase, termination, and visibility projections.
14. On terminal state, runner seals evidence and environment emits FamilyOutcome.
15. Verifier computes ScoreEnvelope from sealed evidence without provider calls.
16. Runner seals EvaluationReceipt and reconciles planned/attempted/valid counts.
17. Analysis consumes validated receipts at the declared cluster/resampling unit.
18. Optional rLLM, Prime, Harbor/ATIF, or other exports derive from native records.
```

One complete economic episode is one runner cell. Internal seat trajectories are linked projections, not separate independent benchmark samples. For training, each trainable trajectory references the joint episode, role, seat, logical actions, and reward attribution rule.

---

## 8. Research-validity requirements for adaptation

An adapter is scientifically valid only if it states what is preserved and what is changed. The admission report must answer:

1. **Construct preservation:** Is the same economic capability and information set being measured?
2. **Intervention preservation:** Are prompts, tools, action opportunities, budgets, and counterpart policies equivalent or intentionally changed?
3. **Outcome preservation:** Does terminal state and score match the official implementation for fixed fixtures?
4. **Population preservation:** Are case sampling, difficulty, seeds, and exclusions equivalent?
5. **Unit preservation:** Is the reported row a candidate configuration, joint system, role, episode, or cluster?
6. **Failure preservation:** Are upstream retries, invalid actions, timeouts, and missing measurements visible rather than silently repaired?
7. **Version preservation:** Can every result resolve exact code, data, adapter, model, harness, scorer, and oracle versions?

AERead should report adapter results in separate blocks unless the paper predeclares a defensible common estimand and aggregation. “Runs under one runner” is not evidence that scores are comparable.

---

## 9. Three representative external adapters

### 9.1 EconEvals Procurement: single candidate, tool loop, exact optimization

- **Official source:** `sara-fish/econ-evals-paper`
- **Pin:** `e1f2a40fec96f0d27f5414873c4310f2b5c51935`
- **Role in the spike:** tests repeated tool actions, exact feasibility/optimization scoring, and materialized synthetic instances.
- **Required adaptation:** lift provider calls and retries out of upstream orchestration; represent procurement tools as phase/role schemas; store the full generated instance; preserve official allocation evaluation; treat the exact optimum as a pinned oracle artifact.
- **Known admission risks:** hidden Tenacity retries, proprietary Gurobi dependency, and an upstream generator path that mixes a seeded RNG with global NumPy randomness.
- **Parity gate:** for fixed materialized instances and scripted tool actions, AERead and upstream produce identical feasibility, allocation value, optimum reference, normalized components, and terminal classification.

This is the best first external adapter because it stresses tools and optimization without requiring live multi-agent scheduling.

### 9.2 tau3 Retail: frozen user simulation plus tools

- **Official source:** `sierra-research/tau2-bench`
- **Pin:** dereferenced `v1.0.1` commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`
- **Role in the spike:** tests half-duplex assistant/user turns, a controlled counterparty, tool-mediated state, and terminal database verification.
- **Required adaptation:** candidate assistant seat plus version-pinned frozen user policy; preserve task policy and tool semantics; use terminal database/state checks as the primary deterministic measurement; retain upstream judge-dependent reward as a separate compatibility metric.
- **Known admission risks:** user simulator and judge configuration can change the unit under test; aggregate upstream reward may mix deterministic and judge-dependent components.
- **Parity gate:** on the predeclared 18-task retail/base pilot, match component-level terminal state and deterministic reward exactly; report judge agreement statistically and separately.

Harbor's tau3 support is useful interoperability evidence, but AERead should not define its benchmark truth through Harbor or inherit a different source pin silently.

### 9.3 AgenticPay: multi-agent, multi-channel contract negotiation

- **Official source:** `SafeRL-Lab/AgenticPay`
- **Pin:** `1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`
- **Role in the spike:** tests bilateral multidimensional contracts and a parallel 2-buyer × 2-seller topology.
- **Initial scope:** text-only 1v1 multidimensional contract plus one 2×2 parallel task; multimodal and large topologies remain outside the first admission profile.
- **Required adaptation:** explicit buyer/seller seats, separate edge-level slots matching the upstream driver's calls, frozen buyer observations, seller projections augmented with the relevant pending buyer messages, deterministic action ordering, one upstream round transition after both subphases, and component-level mapping of GlobalScore/BuyerScore/SellerScore.
- **Known admission risks:** the upstream global observation can contain all negotiation histories while example drivers manually slice them; core imports pull a large vLLM/SGLang/Torch stack; compatibility scores are weighted components rather than a certified optimum.
- **Parity gate:** for identical scripted action bundles, match selected pair, contract/price, buyer and seller utilities, compatibility score components, round count, and terminal reason; privacy fixtures must prove that an unaddressed seat's private history cannot alter another seat's observation.

AgenticPay is the reason the public action boundary needs `DecisionSlot` and `ActionChannel`: the same seat owns several edge-level decisions that cannot be keyed by seat alone. The related paper “Do Matching Mechanisms Work with LLM Agents?” (arXiv:2606.03030) is relevant research context but has no verified executable source in this adapter set and is not treated as an implementation target.

---

## 10. Relationship to Prime Verifiers, PRIME-RL, and Harbor

AERead should explicitly reuse the following ideas from Prime Verifiers v1:

- task/taskset (what), harness (how), and runtime (where) are separate;
- provider dialects normalize into canonical response types;
- typed trace is the source of truth;
- harnesses may be complex and should not be assumed to share one provider API;
- agent and environment are first-class composable objects.

AERead intentionally differs in one important place. Prime's multi-agent `Env.run(task, agents)` permits an environment to program arbitrary control flow. That is appropriate for a general RL framework, but AERead's paper auditability requires the shared runner to own a declared phase schedule and write-ahead evidence. AERead therefore adopts Prime's separation and composability without delegating an opaque episode loop to each family.

Harbor is a third-party task/dataset and sandbox execution format, not AERead's multi-agent semantic model. Prime uses Harbor as one supported taskset source; its multi-agent abstraction is implemented in Verifiers/PRIME-RL itself. AERead should add a Harbor source/runtime adapter only when it unlocks a real benchmark with terminal/container requirements. It should not be a core dependency or the required contribution format.

---

## 11. Mapping to the current repository

| Current path | Current behavior | Required change |
|---|---|---|
| `src/aeread/exchange_v1_runner.py` | directly invokes the fixed ten-stage Exchange engine and records Exchange-specific manifests | retain as legacy path; add a compatibility plugin and prove parity through the new kernel |
| `src/aeread/llm_agent.py` | owns provider calls and internal retry loops | move retry ownership to explicit runner attempts for shared-runner paths; legacy behavior remains until parity migration |
| `src/aeread/cli.py` | hardcodes Exchange verbs in a dispatch dictionary | add namespaced `env`, `benchmark`, `suite`, and `receipt` commands backed by registries |
| `src/aeread/integrations/rllm_*` | maps Exchange episodes directly into rLLM flow/reward | derive rLLM records from canonical receipts and per-seat trajectory references |
| `src/aeread/sdk/v1` | implements strict authoring/planning/measurement records plus the proposed environment, agent, verifier, source, and backend protocol skeletons | retain the reviewed public boundary; do not infer that protocol records imply an executable scheduler |
| `src/aeread/runner/planning.py`, `registry.py`, and `event_store.py` | implement deterministic plan resolution, an exact-version developer registry/discovery foundation, and append-only event/artifact foundations | add formal pre-load provenance admission, then complete execution, recovery, receipt finalization, and replay |
| `docs/shared_runner_design.md` | normative baseline aligned to the implemented SDK foundation and proposed slot/channel action boundary | keep exact public signatures marked proposed until the team accepts the design delta |
| `tests/test_shared_runner_design_contract.py` | asserts terminology exists in documents | keep as documentation guard; add executable SDK/kernel/conformance tests |

RunPlan resolution, exact-version developer registry/discovery, the event store, and the artifact store exist in the current branch, together with strict SDK records and protocol skeletons. Formal/paper plugin discovery is not implemented: it still needs an allowlist before `entry_point.load()`, distribution name/version and entry-point identity, a source/code pin, and binding of the resolved provenance into PlanCell and receipt provenance. The scheduler, attempt executor, receipt finalization, replay/resume, and benchmark adapters do not yet exist as executable shared-runner paths. An `EvaluationReceipt` schema is therefore not evidence that receipts can already be finalized, and the current Exchange path still does not run through the proposed kernel.

---

## 12. Implementation and review gates

The implementation order is normative:

1. review and accept the slot/channel and attempt-observer design amendments;
2. land `aeread.sdk.v1` records, protocols, strict serialization, and exact-version developer registry/discovery;
3. add formal pre-load plugin allowlisting and distribution/source provenance before any paper-mode third-party discovery;
4. land the minimum kernel: RunPlan, phase scheduler, explicit attempts, event store, sealed score/receipt, replay/resume;
5. pass provider-free conformance fixtures;
6. prove legacy Exchange parity;
7. pass Housing as the first clean native family;
8. implement EconEvals Procurement;
9. implement tau3 Retail;
10. implement AgenticPay 1v1 and 2×2;
11. only then claim a public third-party contribution path is demonstrated.

The first implementation PR should not include external benchmark dependencies. The public contracts should be exercised by tiny provider-free fake plugins before any upstream adapter is added.

### Review questions for Chenyu/team

The specification recommends defaults rather than leaving these undefined. Review should explicitly accept or reject:

1. `DecisionSlot` with multi-channel `ActionBundle` replaces seat-keyed action maps.
2. `AgentAdapter` receives a runner-owned `AttemptObserver`; opaque harnesses declare `logical_only` rather than fabricating provider attempts.
3. `aeread.sdk.v1` is already the stable authoring namespace; Task 2.1a adds the new attempt lifecycle while retaining the existing `CallAttempt*` compatibility exports, and any breaking removal requires v2. Pydantic 2 is the only new core dependency.
4. developer plugins use registered entry points; formal mode additionally requires pre-load distribution allowlisting and provenance, while manifests cannot import code.
5. admission uses independent capability fields plus `paper_primary`, `training`, and `interop_only` profiles.
6. Exchange parity and Housing conformance remain prerequisites for external adapters.
7. the three spikes and pins above are the first external coverage set.

Agreement on these seven points is enough to start the SDK/kernel implementation plan. Case-specific economic rules still require the relevant case owner; the runner owner should not invent them.

---

## 13. Self-review result

This design was checked against the current remote baseline and repository implementation.

- **No hidden universal schema:** family states, utilities, actions, topology, and termination remain plugin-owned.
- **No family branch in kernel:** resolution occurs through exact-version plugin IDs;
  formal paper claims additionally require attested distribution provenance.
- **No seat-key collision:** one seat can emit multiple directed channel actions atomically.
- **No harness assumption:** provider/CLI/framework outputs canonicalize at `AgentAdapter`.
- **No runtime lock-in:** Harbor/sandbox execution remains optional and orthogonal.
- **No opaque scientific import:** upstream source, changes, parity, and capability limitations are receipt-visible.
- **No premature adapter claim:** kernel, Exchange parity, and Housing conformance precede external integration.
- **No score conflation:** environment outcome, deterministic verifier, judge result, and training reward remain distinct.
- **No evidence gap on exceptions:** attempts are written before side effects.
- **No unscoped contribution promise:** the public path includes templates, strict validation, provider-free conformance, and admission profiles.

The largest remaining architectural risk is not the registry or manifest format. It is preserving upstream interaction semantics while moving schedule control into AERead. The three spikes are intentionally selected to test progressively harder forms: tool loop, frozen user simulation, and multi-seat multi-channel negotiation.

---

## References

- AERead, [`shared_runner_design.md`](shared_runner_design.md), current PR #7 source
  `155d8fc`, integrated locally at `b5239cd` with reviewed follow-ups.
- Prime Intellect, [“verifiers v1: Decomposing Tasksets and Harnesses for Agentic RL & Evaluations”](https://www.primeintellect.ai/blog/verifiers-v1), 2026-07-10.
- Prime Intellect, [“Multi-Agent Systems in PRIME-RL”](https://www.primeintellect.ai/blog/multi-agent-systems), 2026-08-07.
- Fish et al., [EconEvals official repository](https://github.com/sara-fish/econ-evals-paper), pinned at `e1f2a40fec96f0d27f5414873c4310f2b5c51935`.
- Sierra Research, [tau2/tau3 official repository](https://github.com/sierra-research/tau2-bench), pinned at dereferenced `v1.0.1` commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`.
- SafeRL Lab, [AgenticPay official repository](https://github.com/SafeRL-Lab/AgenticPay), pinned at `1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`.
- Liu, Gu, and Song, [“AgenticPay: A Multi-Agent LLM Negotiation System for Buyer–Seller Transactions”](https://arxiv.org/abs/2602.06008), 2026.
- [“Do Matching Mechanisms Work with LLM Agents?”](https://arxiv.org/abs/2606.03030), related work only.
