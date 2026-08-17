# AERead Shared Runner and Case Format

> **Status:** concise design proposal for team review; not yet a frozen specification  
> **Owner:** Zeyu Sun  
> **Date:** 2026-08-16  
> **Current code baseline:** `zeyu/rllm-b0-hardening` at `3bf3460`

## Purpose

We need one runner that can evaluate heterogeneous economic case families—exchange, contracts, refunds, partner discovery, and housing—without forcing them into one game loop or one scoring formula.

The central design choice is:

> **Standardize the outer experiment contract, not the internal economics of each case family.**

Each family owns its environment, information structure, actions, transitions, termination, oracle, and scorer. The shared runner owns experiment resolution, agent execution, evidence, replay, failure accounting, receipts, and reporting.

---

## 1. Decisions the team needs to confirm

| Decision | Recommended default | Why it matters |
|---|---|---|
| **Canonical owner** | AERead native core defines benchmark truth; Prime, Harbor, and rLLM are adapters/export targets. | External framework semantics must not silently redefine the benchmark. |
| **Unit under test** | A fully resolved **agent configuration**: model, harness, prompt, sampling, runtime, tools/memory, limits, and retries. | A model name alone is not sufficient to reproduce an agentic result. |
| **Primary evaluation block** | Controlled evaluation against a scripted or version-pinned counterpart. Cross-play and self-play/hardness are separate blocks. | Live–live outcomes belong to the pair, not causally to one candidate. |
| **Shared boundary** | Family environment owns control flow; the runner exposes services through `EpisodeContext`. | Contract, refund, discovery, housing, and exchange have different topologies and termination rules. |
| **Shared formats** | Approve the roles of `FamilyManifest`, `CaseManifest`, `SuiteManifest`, `RunSpec`, generated `RunPlan`, `ScoreEnvelope`, and `EvaluationReceipt`. | Zeyu can implement the kernel once these responsibilities are stable. |
| **Case-owner contract** | Require the declaration and provider-free fixtures in Section 6 from every family. | The shared format can only be validated against genuinely different cases. |
| **Paper v1 harness** | Freeze `minimal_chat/1.0`: no harness-managed tools, persistent memory, or compaction, and at most one provider request per logical action. Episode history may still be rendered by the environment. | This keeps the first paper attributable and makes call accounting testable. |
| **Scoring policy** | Each family has its own scorer/oracle but returns a common `ScoreEnvelope`. Invalid measurements are never converted to zero. | The four tests do not share a meaningful raw metric, but they need common validation and reporting. |
| **Evidence and retry policy** | Record an attempt before any external side effect; record its terminal success/failure; no hidden provider retry in the fixed v1 harness. | Otherwise failed calls disappear and failure rate, cost, replay, and attribution become unreliable. |
| **Reference paths** | Wrap `exchange_v1` and prove parity; implement `contract_v1` as the first clean native family. | These two paths test the abstraction from opposite directions. |

Case owners do **not** need to agree on a universal state or action schema. They do need to agree that every family supplies the declaration and fixtures in Section 6.

---

## 2. Architecture

```text
L5  Interoperability
    rLLM trajectories | Harbor tasks / ATIF | Prime Verifiers adapters
    (consume native records; do not define benchmark truth)

L4  Research protocol and reporting
    SuiteManifest | aggregation | coverage | paper tables | ablations

L3  Shared runner kernel                                      Zeyu owns
    resolve + hash -> RunPlan | SuiteRunner | EpisodeRunner
    agent calls | evidence | replay | failure accounting | receipts

L2a Case-family plugins                 L2b Agent execution adapters
    env + action codec + scorer             harness + runtime + provider
    oracle + generator + baselines           Python / HTTP / CLI / container

L1  Shared authoring formats
    FamilyManifest | CaseManifest | SuiteManifest | RunSpec / AgentProfile
```

### Ownership boundary

| Shared runner owns | Case-family plugin owns |
|---|---|
| schema/version/hash validation | state and private types |
| immutable `RunPlan` resolution | actor schedule and interaction topology |
| seat-to-agent assignment | role-specific observations |
| budgets, timeouts, and retry ownership | legal actions, parsing, and legality |
| `AgentAdapter` dispatch and provider canonicalization | state transitions and natural termination |
| append-only evidence and artifacts | terminal outcome and economic consequences |
| receipt integrity, replay, and coverage | oracle, primary metric, diagnostics, rewards |
| declared aggregation and export | generators, difficulty knobs, and baselines |

The kernel must not import concrete families or contain `if family == ...` branches. A trusted registry resolves a `family_id` to a versioned plugin.

### Minimal interfaces

```python
class CaseFamilyPlugin(Protocol):
    def validate_payload(self, payload: Mapping[str, Any]) -> FamilyCase: ...
    def build_environment(self, case: FamilyCase, run: EpisodeCell) -> FamilyEnvironment: ...
    def build_scorer(self, case: FamilyCase) -> FamilyScorer: ...
    def build_oracle(self, case: FamilyCase) -> Oracle | None: ...
    def generator(self) -> CaseGenerator | None: ...


class FamilyEnvironment(Protocol):
    async def run(self, ctx: EpisodeContext) -> TerminalState: ...


class EpisodeContext(Protocol):
    async def ask(
        self, *, seat: str, observation: Observation,
        action_schema: dict | None, phase: str
    ) -> AgentTurn: ...
    def emit_action(self, action: ActionEnvelope) -> None: ...
    def emit_transition(self, transition: StateTransition) -> None: ...


class AgentAdapter(Protocol):
    async def act(self, request: AgentRequest) -> CanonicalResponse: ...


class HarnessAdapter(Protocol):
    async def open_session(
        self, config: ResolvedAgentConfiguration,
        runtime: RuntimeAdapter, evidence: EvidenceSink
    ) -> AgentAdapter: ...


class FamilyScorer(Protocol):
    def score(self, case, terminal_state, evidence, oracle) -> ScoreEnvelope: ...
```

`AgentAdapter` is a capability boundary, not a required base class. A Python object, provider endpoint, HTTP service, CLI program, or containerized agent can be wrapped behind it.

---

## 3. Shared format

### 3.1 Records and responsibilities

| Record | Purpose | Authored by |
|---|---|---|
| `FamilyManifest` | Declares family roles, schemas, capabilities, scorer/oracle/generator, baselines, and limits. | Family owner; versioned with the trusted plugin. |
| `CaseManifest` | Defines one immutable world instance and its family-typed payload. It never selects a model or harness. | Generator or curator. |
| `SuiteManifest` | Defines the scientific protocol: cases, controlled/cross-play blocks, role pairing, repetitions, missingness, and aggregation. | Paper/evaluation owners. |
| `AgentProfile` | Human-authored model+harness+runtime configuration. | Experiment owner. |
| `RunSpec` | Assigns agent profiles to subject seats and sets execution budgets/mode. | Experiment owner. |
| `RunPlan` | Fully resolved, pinned, hashed execution cells. Written before any paid call. | Generated by the resolver. |
| `EpisodeEventLog` | Canonical append-only record of what happened. | Runner, environment, adapters, scorer. |
| `ScoreEnvelope` / `EvaluationReceipt` | Validated score and final inclusion/provenance/integrity record. | Scorer and runner finalizer. |

### 3.2 `FamilyManifest` sketch

```toml
spec_version = "aeread.family/0.1"

[family]
id = "contract_v1"
version = "1.0.0"
plugin_id = "aeread.contract_v1"   # trusted registry key, not an arbitrary import

[environment]
topology = "alternating_bilateral"
needs_tools = false
needs_sandbox = false

[roles.buyer]
testable = true
action_schema = "schemas/buyer_action_v1.json"

[roles.seller]
testable = true
action_schema = "schemas/seller_action_v1.json"
scripted_policies = ["reservation_seller_v1"]

[scoring]
scorer_id = "contract_surplus_v1"
oracle_id = "contract_frontier_v1"
primary_metric = "normalized_joint_surplus"

[generator]
generator_id = "contract_generator_v1"
difficulty_knobs = ["reservation_gap", "deadline_tension"]
```

### 3.3 `CaseManifest` sketch

```yaml
spec_version: aeread.case/0.1
case_id: contract_v1__dev__000001
family_id: contract_v1
family_version: 1.0.0
split: dev
seed: 41001

seats:
  - {id: buyer, role: buyer}
  - {id: seller, role: seller}

episode:
  max_decisions: 8
  invalid_action_limit: 2
  termination: [agreement, reject, walk_away, max_decisions, forfeit]

visibility_policy: contract_private_types_v1

payload:                         # validated only by contract_v1
  currency: USD
  public_context: "Time-sensitive procurement contract"
  issues:
    price: {type: integer, min: 70, max: 160}
    delivery_days: {type: integer, min: 1, max: 30}
  private_types:
    buyer: {value_model: contract_buyer_value_v1, params: {base_value: 170}}
    seller: {cost_model: contract_seller_cost_v1, params: {base_cost: 60}}

scoring:
  scorer_id: contract_surplus_v1
  scorer_version: 1.0.0
  oracle_id: contract_frontier_v1
  oracle_version: 1.0.0

provenance:
  generator_id: contract_generator_v1
  generator_version: 1.0.0
  review_status: curated

content_sha256: "0000000000000000000000000000000000000000000000000000000000000000"
```

Shared fields are strict (`extra=forbid`). `payload` is a typed extension validated by the registered family. The zero digest above is illustrative; the real digest is computed over canonical bytes with `content_sha256` removed.

Agent/model/harness configuration does not belong in a case. The case says **what world this is**; the suite/run says **who plays and how the result may be interpreted**.

### 3.4 Suite and run separation

The suite owns research choices such as:

```yaml
evaluation_blocks:
  - id: controlled_fixed_counterpart
    kind: controlled
    orientations:
      - subject_seats: [buyer]
        controlled_profiles: {seller: contract_scripted_seller_v1}
      - subject_seats: [seller]
        controlled_profiles: {buyer: contract_scripted_buyer_v1}
    pair_orientations: true
    repetitions: 3
    seed_policy: paired

aggregation:
  group_by: [family_id, primary_metric, subject_role, difficulty_bin]
  missingness: report_separately
  cross_family_scalar: disabled
```

The run supplies the candidate profile, execution mode (`offline`, `live_frozen`, or `replay`), and budgets. The resolver expands case × evaluation block × role × repetition × seed, resolves every agent/harness/runtime/provider/scorer version, and writes an immutable `RunPlan` before execution.

---

## 4. End-to-end runner flow

```text
1. Load Family/Case/Suite/Run/AgentProfile inputs.
2. Strictly validate schemas and trusted plugin availability.
3. Resolve defaults, seats, agent configurations, implementation pins, and hashes.
4. Expand all experiment cells and write the immutable RunPlan.
5. Preflight every cell before the first paid or external call.
6. Start an episode attempt and open its append-only event log.
7. Call FamilyEnvironment.run(ctx); the environment selects actors and builds observations.
8. ctx.ask() records an action attempt, dispatches the AgentAdapter, canonicalizes the response,
   and returns it to the family ActionCodec for parsing and legality checks.
9. The environment applies transitions, emits evidence, and declares termination.
10. Seal terminal state and evidence; compute the family oracle and ScoreEnvelope.
11. Finalize an EvaluationReceipt and close sessions/runtimes in finally.
12. Validate receipts, reconcile planned/attempted/valid counts, aggregate declared cohorts,
    and optionally export to rLLM, Harbor/ATIF, or Prime Verifiers.
```

### The decision/call relationship

```text
environment decision request
  └── outer agent action attempt             always visible to the runner
      └── harness segment(s), 0..N
          └── provider/model call(s), 0..N   visible when the adapter supports it
```

For the paper's fixed `minimal_chat/1.0` harness, one logical action should produce at most one provider request. Future agentic harnesses may use multiple internal calls; an opaque adapter must report `observes_model_calls=false`, not fabricate zero calls.

### Response and action pipeline

```text
raw provider/process output
  -> content-addressed raw artifact
  -> provider-neutral CanonicalResponse
  -> family ActionCodec.parse()
  -> parsed ActionEnvelope
  -> environment legality check
  -> StateTransition
```

Canonicalization occurs before family parsing so a contract/refund/housing parser does not need to understand every provider dialect. Raw evidence remains available even when canonicalization or parsing fails.

---

## 5. Evidence, scoring, and research invariants

1. **One canonical log.** `events.jsonl` is the source of truth. Call ledgers, per-agent trajectories, and the joint environment timeline are derived projections.
2. **Write before side effects.** Append and flush `agent_action_attempt_started` and every observable `call_attempt_started` before invoking a provider, process, or external agent. Then append a terminal success/failure event.
3. **Separate transport, action, and economics.** A valid response may contain a malformed action; a parsed action may be illegal; a legal action may still be economically poor.
4. **Missing is not zero.** Provider, harness, runtime, environment, oracle, or scorer failure yields `invalid_measurement`. Valid zero or negative economic outcomes remain numeric.
5. **Keep joint and per-agent views.** Each seat has a trajectory; the episode also has a joint state/action/transition timeline. Neither replaces the other.
6. **Protect private information structurally.** Evidence is labeled `public`, `seat:<id>`, or `evaluator_only`. Agents receive role-specific observations, never the entire private world object.
7. **Score sealed evidence.** A family scorer is deterministic over terminal state and sealed evidence; it does not call the candidate or provider. An LLM judge, if used, is a named secondary metric with its own recorded configuration.
8. **Do not average incomparable metrics.** Report family-level primary metrics, role/difficulty slices, coverage, failure rates, and cost. Cross-family pooling is disabled unless each normalization and weight is scientifically justified in the suite.

Minimal score contract:

```python
class ScoreEnvelope:
    status: Literal["ok", "invalid_measurement"]
    primary: MetricValue | None
    metrics: dict[str, MetricValue]
    rewards_by_seat: dict[str, float]
    outcome: dict
    validity: ValidityReport
    scorer: ImplementationRef
    oracle: ImplementationRef | None
    evidence_refs: list[str]
```

The final `EvaluationReceipt` binds the suite/case hashes, resolved agent configurations by seat, environment/parser/scorer/oracle implementations, event and artifact hashes, score or typed failure, observability limits, and verified replay levels. Paper tables consume validated receipts rather than ad hoc logs.

For the ICLR paper, controlled results should use a deterministic/scripted or version-pinned counterpart. Live–live, cross-play, and self-play/hardness results are valuable, but they measure a joint system and should be reported separately. The paper should call the subject an **agent configuration** unless harness, prompt, runtime, tools/memory, sampling, and retry policy are all fixed across models.

---

## 6. What each case-family owner must provide

Please comment on whether the following declaration is sufficient for your family:

| Required declaration | Questions to answer |
|---|---|
| **Identity** | Family ID/version, owner, research question, and whether the family composes another protocol. |
| **Roles and topology** | Roles/seats, which roles are testable or controlled, communication graph, turn order, sequential vs simultaneous behavior. |
| **Observation and privacy** | What each role sees; public, seat-private, and evaluator-only fields; expected context size. |
| **Actions** | Structured action types/schema, parser, legality rules, and consequence of malformed or illegal actions. |
| **State and termination** | Initial state, randomness/seed, transition semantics, natural termination, maximum decisions, timeout/forfeit behavior. |
| **Outcome and scoring** | Terminal outcome schema, primary metric, diagnostics, per-seat rewards, oracle/reference, and aggregation rule. |
| **Generation and difficulty** | Generator parameters, difficulty knobs, benchmark/train split isolation, external data and privacy constraints. |
| **Baselines and conformance** | Scripted/no-op/random/greedy/oracle baselines, admission rule, and required replay/observability capabilities. |

Each family must also provide provider-free fixtures:

- one deterministic successful trajectory;
- one valid no-deal/no-match/denial outcome where applicable;
- one malformed action and one parseable-but-illegal action;
- one scorer/oracle fixture with exact expected values;
- one private-information noninterference check;
- one deterministic state/score replay fixture;
- a small admission pilot that separates format failures from bad decisions.

Family owners define economic semantics. The shared-runner owner should not invent their utilities, oracle, or legal actions. Conversely, family plugins should not implement their own provider logging, retry system, receipt format, or paper aggregation.

---

## 7. Migration and validation

The current `exchange_v1_runner.py`, `exchange_v1_roles.py`, and `exchange_v1_scoring.py` already provide valuable assets: self-contained run directories, offline/live-frozen/replay modes, response snapshots, hashes, resolved-model pins, call-funnel checks, invalid-measurement handling, and AER semantics. These should be preserved.

### Two reference implementations

1. **`exchange_v1` compatibility wrapper**
   - Keep the existing ten-stage engine internally.
   - Map its current config into a family payload.
   - Project its trace/manifest into canonical events.
   - Bridge its scorer into `ScoreEnvelope`.
   - Prove parity for terminal allocation, `w_real`, denominator/tier, AER, failure class, and replay before removing the old path.

2. **`contract_v1` clean plugin**
   - Two roles with private values/costs.
   - Alternating structured offers over price and one additional term.
   - Exact offer-reference acceptance, early termination, and deterministic oracle.
   - Scripted counterpart for controlled evaluation; frozen/live counterpart only as a separate block.

The design is credible when both families run through the same kernel, event log, score envelope, receipt, and replay machinery without family-specific branches in `EpisodeRunner`.

### Minimum paper-ready gates

- all selected families pass one provider-free conformance suite;
- every planned episode reconciles to a valid receipt or a typed exclusion/failure;
- failed external calls remain durably observable;
- private-information boundaries are tested;
- valid zero/negative outcomes remain distinct from missing measurements;
- exchange old/new parity is demonstrated;
- controlled counterpart, role, order, seed, harness, prompt, sampling, and model provenance are complete;
- paper tables can be regenerated from validated receipts;
- Prime/Harbor/rLLM claims are supported by parity or round-trip evidence, or labeled future work.

---

## Design lineage

This proposal adopts Prime's useful separation of **taskset (what)**, **harness (how)**, and **runtime (where)**, plus the PRIME-RL multi-agent pattern in which the environment owns role scheduling and an episode contains per-agent traces. AERead adds a first-class joint economic timeline, family-owned deterministic scoring/oracles, explicit invalid-measurement handling, and native receipts suitable for paper aggregation and replay.

The interfaces and schemas above are proposals, not claims that the shared runner already exists. The current AERead path remains exchange-specific; the purpose of this review is to freeze the smallest correct contract before implementation.
