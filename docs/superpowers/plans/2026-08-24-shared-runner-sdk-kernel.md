# Shared Runner Public SDK and Kernel Implementation Plan

> **Post-sync notice (2026-08-25):** Tasks 1–5 and their review history remain binding.
> Tasks 6–11 are superseded by
> [`2026-08-25-shared-runner-post-sync-rebaseline.md`](2026-08-25-shared-runner-post-sync-rebaseline.md)
> after the approved PR #7 taxonomy/roadmap added five semantic verifier families,
> `ActionAttempt -> ProviderCall* + ToolInvocation*`, and the 8/25 sync required
> benchmark-informed compatibility probes. Do not dispatch old Task 6 directly.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the versioned `aeread.sdk.v1` authoring API and minimum family-neutral runner kernel, then prove that the legacy Exchange path produces equivalent outcomes through it.

**Architecture:** Public Pydantic models and Protocols define environment, verifier, agent, runtime, and source boundaries. The private runner resolves immutable plans, schedules `DecisionSlot` objects, records attempts before side effects, applies atomic transitions, seals deterministic scores and receipts, and supports replay. Plugin entry points resolve trusted IDs without family branches.

**Tech Stack:** Python 3.10+, Pydantic 2, `asyncio`, `importlib.metadata`, SHA-256, JSONL, pytest.

**Spec:** [`docs/public_environment_and_external_adapter_spec.md`](../../public_environment_and_external_adapter_spec.md)

## Global Constraints

- `aeread.sdk.v1` exports only stable author-facing protocols, immutable models, errors, and test helpers.
- Unknown manifest fields are rejected.
- Every plugin declares `sdk_api = "aeread.sdk/v1"` and its own semantic version.
- Canonical bytes use UTF-8 JSON, sorted keys, compact separators, no NaN/Infinity, and algorithm ID `aeread.cjson/1` before SHA-256 hashing.
- The kernel must not import a concrete family or branch on `family_id`.
- The runner writes `harness_invocation_started` before invoking an external agent, and every observable provider call writes `call_attempt_started` before its side effect.
- `step()` is the only atomic environment mutation boundary and cannot call an agent/provider.
- A deterministic verifier scores only sealed evidence and cannot call the candidate/provider.
- Core import must not load tau3, AgenticPay, Gurobi, vLLM, SGLang, Docker, or Harbor.
- Exchange terminal allocation, `w_real`, denominator/tier, AER, failure class, evidence count, and replay must match the legacy path before migration.

## Execution workflow

At implementation start, create one active goal whose objective is the completion gate at the end of this plan. Treat each numbered task as a review gate and each checkbox as the smallest tracked action. Update the plan after every test/commit boundary; mark the goal complete only after the full completion gate passes.

Parallel work is allowed only for bounded subtasks without overlapping files or unsettled shared types. Good parallel candidates are fixture research, documentation examples, and independent parity-report readers. Keep `records -> protocols/registry -> planning -> evidence -> attempts -> kernel -> replay/finalize` serial because downstream signatures depend on upstream decisions. Before merging each parallel result, rerun its focused tests and inspect the diff against this spec.

---

## File structure

```text
src/aeread/sdk/v1/
  __init__.py          stable exports
  base.py              StrictModel, canonical bytes and hashes
  records.py           IDs, phases, slots, actions, events, scores, receipts
  protocols.py         Environment/Verifier/Agent/Runtime/Source Protocols
  errors.py            typed integration, environment, action and measurement failures

src/aeread/runner/
  __init__.py
  registry.py          trusted entry-point registry
  planning.py          manifest validation and immutable RunPlan resolution
  event_store.py       append-only hash-chained JSONL and artifact references
  attempts.py          explicit retry/timeout/canonical response execution
  kernel.py            declarative phase scheduler and atomic transition loop
  replay.py            event validation and deterministic state reconstruction
  finalize.py          sealed verifier call and EvaluationReceipt
  conformance.py       reusable provider-free plugin tests

src/aeread/families/exchange_v1_compat.py
tests/shared_runner/
  fakes.py
  test_records.py
  test_registry.py
  test_planning.py
  test_event_store.py
  test_attempts.py
  test_kernel.py
  test_replay_receipt.py
  test_conformance.py
  test_exchange_parity.py
```

Each file has one owner boundary: SDK declarations never execute episodes; runner files never define economics; the Exchange compatibility module is the only place that imports the legacy Exchange engine.

---

### Task 1: Lock the decision-slot design delta

**Files:**
- Modify: `docs/shared_runner_design.md`
- Modify: `tests/test_shared_runner_design_contract.py`

**Interfaces:**
- Consumes: `DecisionSlot`, `ActionChannel`, and `ActionBundle` proposal in the spec.
- Produces: the normative statement that one logical action is keyed by `slot_id`, and one slot can atomically emit multiple channel actions.

- [ ] **Step 1: Write the failing documentation-contract test**

```python
def test_shared_runner_design_supports_multi_channel_decisions() -> None:
    text = DESIGN.read_text()
    for required in (
        "DecisionSlot",
        "ActionChannel",
        "ActionBundle",
        "keyed by slot_id",
        "one logical agent decision",
    ):
        assert required in text
```

- [ ] **Step 2: Run the test and verify the old baseline fails**

Run: `pytest tests/test_shared_runner_design_contract.py::test_shared_runner_design_supports_multi_channel_decisions -v`

Expected: FAIL because the current normative document keys actions only by seat.

- [ ] **Step 3: Amend the normative interface**

Replace `eligible_actors(...) -> Sequence[str]` with `decision_slots(...) -> Sequence[DecisionSlot]`; define `ActionChannel` and `ActionBundle`; change `step(..., actions: Mapping[str, ActionEnvelope])` to `step(..., bundles: Mapping[str, ActionBundle])` keyed by `slot_id`. State that simultaneous observations are frozen before any slot response and that all channel actions from one slot parse and close atomically.

- [ ] **Step 4: Run the documentation contract**

Run: `pytest tests/test_shared_runner_design_contract.py -v`

Expected: all design-contract tests PASS.

- [ ] **Step 5: Commit the reviewed design amendment**

```bash
git add docs/shared_runner_design.md tests/test_shared_runner_design_contract.py
git commit -m "docs: support multi-channel runner decisions"
```

---

### Task 2: Add strict public records and canonical hashing

**Files:**
- Modify: `pyproject.toml`
- Create: `src/aeread/sdk/__init__.py`
- Create: `src/aeread/sdk/v1/__init__.py`
- Create: `src/aeread/sdk/v1/base.py`
- Create: `src/aeread/sdk/v1/errors.py`
- Create: `src/aeread/sdk/v1/records.py`
- Create: `tests/shared_runner/__init__.py`
- Create: `tests/shared_runner/test_records.py`

**Interfaces:**
- Produces: `StrictModel`, `canonical_json_bytes(value) -> bytes`, `content_sha256(value) -> str`, `PhaseSpec`, `PhaseGraph`, `DecisionSlot`, `ActionChannel`, `ActionEnvelope`, `ActionBundle`, `ObservationEnvelope`, `CanonicalResponse`, `ScoreEnvelope`, `EvaluationReceipt`.

- [ ] **Step 1: Add failing validation and hash tests**

```python
def test_decision_slot_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DecisionSlot.model_validate({
            "slot_id": "buyer1-round0",
            "seat_id": "buyer1",
            "channels": [],
            "observation_schema_ref": "obs/1",
            "response_schema_ref": "reply/1",
            "order_key": "0001",
            "typo": True,
        })


def test_canonical_hash_is_key_order_independent() -> None:
    assert content_sha256({"b": 2, "a": 1}) == content_sha256({"a": 1, "b": 2})


def test_canonical_bytes_reject_non_finite_float() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes({"value": float("nan")})
```

- [ ] **Step 2: Run the tests and verify imports fail**

Run: `pytest tests/shared_runner/test_records.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'aeread.sdk'`.

- [ ] **Step 3: Add Pydantic and implement the strict base**

Add `"pydantic>=2.8,<3"` to `[project].dependencies`, then implement:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_json_bytes(value: object) -> bytes:
    normalized = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    try:
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(str(exc)) from exc


def content_sha256(value: object) -> str:
    return hashlib.sha256(b"aeread.cjson/1\0" + canonical_json_bytes(value)).hexdigest()
```

- [ ] **Step 4: Implement immutable record models**

Define the spec fields exactly. Use discriminated status values for `ParseResult`, `LegalityResult`, `TerminalResult`, `ScoreEnvelope`, and `EvaluationReceipt`; use tuples instead of mutable lists at the public boundary; validate unique channel declarations within a slot, unique action IDs and sequence indices within a bundle, declared channel membership, per-channel `min_actions`/`max_actions`, and matching `slot_id`/`actor_seat_id` across an `ActionBundle`.

- [ ] **Step 5: Export the stable API**

`src/aeread/sdk/v1/__init__.py` imports only the public models/errors and declares an explicit `__all__`. `import aeread.sdk.v1` must not import `aeread.exchange_economy` or any integration package.

- [ ] **Step 6: Run the record tests**

Run: `pytest tests/shared_runner/test_records.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/aeread/sdk tests/shared_runner/test_records.py
git commit -m "feat: add shared runner sdk records"
```

---

### Task 3: Define protocols and trusted plugin registry

**Files:**
- Create: `src/aeread/sdk/v1/protocols.py`
- Modify: `src/aeread/sdk/v1/__init__.py`
- Create: `src/aeread/runner/__init__.py`
- Create: `src/aeread/runner/registry.py`
- Create: `tests/shared_runner/fakes.py`
- Create: `tests/shared_runner/test_registry.py`

**Interfaces:**
- Consumes: Task 2 record types.
- Produces: `EnvironmentPlugin`, `VerifierPlugin`, `AgentAdapter`, `AttemptObserver`, `ExecutionBackend`, `BenchmarkSourceAdapter`, `OfficialVerifierBridge`, and `PluginRegistry.resolve_environment(plugin_id, plugin_version)`.

- [ ] **Step 1: Write registry rejection and resolution tests**

```python
def test_registry_resolves_exact_environment_version(fake_environment) -> None:
    registry = PluginRegistry.from_objects(environments=[fake_environment])
    assert registry.resolve_environment("fake_market", "1.0.0") is fake_environment


def test_registry_rejects_manifest_import_path() -> None:
    with pytest.raises(UntrustedPluginReference):
        PluginRef(plugin_id="os:system", plugin_version="1.0.0")


def test_registry_rejects_sdk_major_mismatch(fake_environment) -> None:
    incompatible = fake_environment.with_manifest(
        fake_environment.manifest.model_copy(update={"sdk_api": "aeread.sdk/v2"})
    )
    with pytest.raises(IncompatiblePlugin):
        PluginRegistry.from_objects(environments=[incompatible])
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_registry.py -v`

Expected: FAIL because protocols and registry do not exist.

- [ ] **Step 3: Add Protocol definitions with exact signatures**

Copy the method signatures from the spec. Mark all protocols `@runtime_checkable`; keep source, verifier, agent, environment, and runtime interfaces separate. `AgentAdapter.act()` accepts the runner-owned `AttemptObserver`; `VerifierPlugin.score()` accepts `SealedEvidenceView`, never a mutable `EventStore`. In `tests/shared_runner/fakes.py`, define reusable immutable `CELL`, `REQUEST`, `IDS`, `NO_RETRY`, `LENGTH_RETRY_ONCE`, `EMPTY_LENGTH_RESPONSE`, and `VALID_RESPONSE` fixtures used by later tasks.

- [ ] **Step 4: Implement registry resolution**

Use `importlib.metadata.entry_points(group=...)`; load only the five declared `aeread.*` entry-point groups; validate `plugin_id`, exact version, and `sdk_api`; reject duplicates. `PluginRegistry.from_objects()` is the provider-free test seam.

- [ ] **Step 5: Run registry and import-isolation tests**

Run: `pytest tests/shared_runner/test_registry.py -v`

Expected: PASS, including a subprocess assertion that `import aeread.sdk.v1` does not populate external adapter modules in `sys.modules`.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/sdk/v1 src/aeread/runner tests/shared_runner/fakes.py tests/shared_runner/test_registry.py
git commit -m "feat: add shared runner plugin contracts"
```

---

### Task 4: Resolve immutable manifests into a RunPlan

**Files:**
- Modify: `src/aeread/sdk/v1/records.py`
- Create: `src/aeread/runner/planning.py`
- Create: `tests/shared_runner/test_planning.py`

**Interfaces:**
- Consumes: `PluginRegistry`, `FamilyManifest`, `CaseManifest`, `SuiteManifest`, `AgentProfile`, `RunSpec`.
- Produces: `resolve_run_plan(inputs: ResolutionInputs, registry: PluginRegistry) -> RunPlan` and deterministic `cell_id`/`cluster_id` values.

- [ ] **Step 1: Write failing resolution tests**

```python
def test_resolver_pins_every_cell_before_execution(fake_inputs, fake_registry) -> None:
    plan = resolve_run_plan(fake_inputs, fake_registry)
    assert plan.cells
    assert all(cell.cell_id and cell.case_hash and cell.agent_config_hash for cell in plan.cells)
    assert all(cell.cluster_id and cell.environment_ref.version for cell in plan.cells)


def test_resolver_rejects_training_profile_without_per_seat_trace(fake_inputs, fake_registry) -> None:
    inputs = fake_inputs.model_copy(update={
        "run_spec": fake_inputs.run_spec.model_copy(update={"admission_profile": "training"}),
        "family": fake_inputs.family.model_copy(update={
            "capabilities": fake_inputs.family.capabilities.model_copy(
                update={"trainability": "joint_only"}
            )
        }),
    })
    with pytest.raises(CapabilityMismatch):
        resolve_run_plan(inputs, fake_registry)
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_planning.py -v`

Expected: FAIL because no resolver exists.

- [ ] **Step 3: Implement strict manifest records**

Add `UpstreamSourceRef`, `CapabilityDeclaration`, `FamilyManifest`, `CaseManifest`, `SuiteManifest`, `AgentProfile`, `RunSpec`, `PluginRef`, `EpisodeCell`, and `RunPlan`. Encode the seven capability axes and the exact requirements for `paper_primary`, `training`, and `interop_only` in `ADMISSION_REQUIREMENTS`.

- [ ] **Step 4: Implement deterministic resolution**

Resolve defaults and plugin versions first; canonicalize and hash inputs; expand case × block × subject role × repetition × seed in sorted order; derive IDs from content hashes rather than wall time; reject unresolved models, plugins, retries, scorer references, cluster fields, and incompatible capabilities.

- [ ] **Step 5: Run planning tests**

Run: `pytest tests/shared_runner/test_planning.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/sdk/v1/records.py src/aeread/runner/planning.py tests/shared_runner/test_planning.py
git commit -m "feat: resolve immutable shared run plans"
```

---

### Task 5: Add append-only event and artifact stores

**Files:**
- Create: `src/aeread/runner/event_store.py`
- Create: `tests/shared_runner/test_event_store.py`

**Interfaces:**
- Consumes: `EpisodeEvent`, `ArtifactRef`, canonical hashing.
- Produces: `EventStore.append(event_type, identity, visibility, payload) -> EpisodeEvent`, `EventStore.seal() -> SealedEvidenceView`, `ArtifactStore.put(bytes, media_type) -> ArtifactRef`.

- [ ] **Step 1: Write crash-evidence and hash-chain tests**

```python
def test_append_flushes_started_event_before_side_effect(tmp_path) -> None:
    store = EventStore.open(tmp_path / "events.jsonl")
    event = store.append("call_attempt_started", IDS, "evaluator_only", {"ordinal": 1})
    rows = (tmp_path / "events.jsonl").read_text().splitlines()
    assert json.loads(rows[-1])["event_id"] == event.event_id


def test_hash_chain_detects_tampering(tmp_path) -> None:
    store = build_two_event_store(tmp_path)
    replace_second_payload_without_rehash(store.path)
    with pytest.raises(EventIntegrityError):
        EventStore.verify(store.path)
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_event_store.py -v`

Expected: FAIL because stores do not exist.

- [ ] **Step 3: Implement content-addressed artifacts and durable append**

Write artifacts under `artifacts/sha256/<digest>` using exclusive creation. Append one canonical JSON event per line, flush, and `os.fsync()` before returning. Compute `event_hash` over `prior_event_hash` plus canonical event content. Visibility is exactly `public`, `seat:<id>`, or `evaluator_only`.

- [ ] **Step 4: Implement sealing and projections**

`seal()` verifies the chain, closes writes, and returns an immutable view with event/artifact roots. Projection retains event IDs/hashes while removing unauthorized payload refs.

- [ ] **Step 5: Run event-store tests**

Run: `pytest tests/shared_runner/test_event_store.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/runner/event_store.py tests/shared_runner/test_event_store.py
git commit -m "feat: add durable runner evidence store"
```

---

### Task 6: Execute explicit call attempts

**Files:**
- Create: `src/aeread/runner/attempts.py`
- Create: `tests/shared_runner/test_attempts.py`

**Interfaces:**
- Consumes: `AgentAdapter.act(AgentRequest, attempts=AttemptObserver)`, `RetryPolicy`, `EventStore`.
- Produces: `execute_logical_action(request, adapter, retry_policy, events) -> LogicalActionResult` with one or more explicit `CallAttempt` records.

- [ ] **Step 1: Write failure-before-return and retry tests**

```python
@pytest.mark.asyncio
async def test_exception_keeps_started_attempt(tmp_path) -> None:
    adapter = RaisingAgent(TimeoutError("provider timed out"))
    result = await execute_logical_action(REQUEST, adapter, NO_RETRY, event_store(tmp_path))
    assert result.status == "retryable_infrastructure_exhausted"
    assert event_types(tmp_path) == [
        "logical_action_started",
        "harness_invocation_started",
        "harness_invocation_failed",
        "logical_action_failed",
    ]


@pytest.mark.asyncio
async def test_length_retry_preserves_both_attempts(tmp_path) -> None:
    adapter = SequenceAgent([EMPTY_LENGTH_RESPONSE, VALID_RESPONSE])
    result = await execute_logical_action(REQUEST, adapter, LENGTH_RETRY_ONCE, event_store(tmp_path))
    assert [a.ordinal for a in result.attempts] == [1, 2]
    assert result.attempts[1].retry_reason == "empty_length"
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_attempts.py -v`

Expected: FAIL because the executor does not exist.

- [ ] **Step 3: Implement the attempt state machine**

For every logical retry: allocate deterministic IDs; append `harness_invocation_started`; invoke `adapter.act(..., attempts=observer)` under `asyncio.timeout`; store raw artifact and canonical response; append exactly one invocation success, failure, or `outcome_unknown`. `AttemptObserver.call_started()` durably appends `call_attempt_started` before a direct or instrumented harness makes a provider request, and closes it exactly once. Apply only declared retry predicates and limits. Disable nested unobservable SDK retries in first-party adapters.

- [ ] **Step 4: Map failures without producing economic zero**

Transport timeout/rate-limit/provider 5xx exhaustion returns `invalid_measurement`; successful malformed/empty responses return an agent-action result for family policy; integration/configuration errors fail preflight; ambiguous interrupted side effects become `outcome_unknown` and require a new `episode_attempt_id`.

- [ ] **Step 5: Run attempt tests**

Run: `pytest tests/shared_runner/test_attempts.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/runner/attempts.py tests/shared_runner/test_attempts.py
git commit -m "feat: record explicit agent call attempts"
```

---

### Task 7: Implement declarative phase scheduling

**Files:**
- Create: `src/aeread/runner/kernel.py`
- Create: `tests/shared_runner/test_kernel.py`

**Interfaces:**
- Consumes: `RunPlan` cell, `EnvironmentPlugin`, seat-bound `AgentAdapter` objects, attempt executor, event store.
- Produces: `async run_episode(cell, environment, agents, verifier, run_dir) -> EvaluationReceipt`.

- [ ] **Step 1: Write sequential, simultaneous, and multi-channel tests**

```python
@pytest.mark.asyncio
async def test_simultaneous_slots_observe_same_pre_phase_state(fake_market, agents, tmp_path) -> None:
    receipt = await run_episode(CELL, fake_market, agents, fake_market.verifier, tmp_path)
    observations = load_observations(receipt, phase_id="offer")
    assert {o.payload["state_version"] for o in observations} == {0}


@pytest.mark.asyncio
async def test_one_slot_can_emit_two_directed_actions(fake_two_by_two_market, agents, tmp_path) -> None:
    receipt = await run_episode(CELL, fake_two_by_two_market, agents, fake_two_by_two_market.verifier, tmp_path)
    bundle = load_bundle(receipt, slot_id="buyer1-round0")
    assert {a.channel_id for a in bundle.actions} == {"buyer1-seller1", "buyer1-seller2"}
    assert fake_two_by_two_market.step_calls == 1
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_kernel.py -v`

Expected: FAIL because the kernel does not exist.

- [ ] **Step 3: Implement the episode state machine**

Validate the phase graph once; initialize state; select current phase; obtain deterministically sorted slots; freeze all observations; execute slots according to `single`, `sequential`, or `simultaneous` mode; parse and validate bundles; apply the declared invalid/missing action policy; call one atomic `step()`; validate `next_phase_id`; check terminal and budgets.

- [ ] **Step 4: Enforce invariants at every boundary**

Reject duplicate slot/channel/action IDs, undeclared next phases, mutation during `observe`/`parse_action`/`legal`, missing required channel actions, unexpected extra actions, and a `step()` result that cannot serialize. Record parse, legality, transition, and termination as distinct events.

- [ ] **Step 5: Run kernel tests**

Run: `pytest tests/shared_runner/test_kernel.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/runner/kernel.py tests/shared_runner/test_kernel.py
git commit -m "feat: schedule family-neutral economic episodes"
```

---

### Task 8: Seal scores, receipts, and deterministic replay

**Files:**
- Create: `src/aeread/runner/finalize.py`
- Create: `src/aeread/runner/replay.py`
- Create: `tests/shared_runner/test_replay_receipt.py`

**Interfaces:**
- Consumes: terminal state, `FamilyOutcome`, `VerifierPlugin`, sealed evidence, RunPlan identities.
- Produces: `finalize_episode(...) -> EvaluationReceipt`, `replay_episode(receipt, environment, events) -> ReplayReport`.

- [ ] **Step 1: Write invalid-measurement and replay tests**

```python
def test_scorer_exception_is_not_zero_score(sealed_episode) -> None:
    receipt = finalize_episode(sealed_episode, RaisingVerifier())
    assert receipt.status == "invalid_measurement"
    assert receipt.score is None


def test_replay_reconstructs_state_and_score(valid_receipt, environment) -> None:
    report = replay_episode(valid_receipt, environment)
    assert report.state_hash_match is True
    assert report.score_hash_match is True
    assert report.external_calls == 0
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_replay_receipt.py -v`

Expected: FAIL because finalization/replay do not exist.

- [ ] **Step 3: Implement sealed verification and receipt creation**

Seal the event log before `VerifierPlugin.score()`. Record scorer implementation hash, reference versions, score evidence refs, inclusion status, observability limits, cluster IDs, plan/case/agent hashes, event/artifact roots, and per-seat trajectory refs. A scorer exception produces typed `oracle_or_scorer_failure`, never numeric zero.

- [ ] **Step 4: Implement replay**

Verify hashes; rebuild initial state; apply recorded legal `ActionBundle` objects through environment `step()` with no agent calls; compare every transition state hash, terminal outcome hash, and score hash. Refuse replay if the receipt declares `state_replay != deterministic`.

- [ ] **Step 5: Run replay/receipt tests**

Run: `pytest tests/shared_runner/test_replay_receipt.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/runner/finalize.py src/aeread/runner/replay.py tests/shared_runner/test_replay_receipt.py
git commit -m "feat: seal runner receipts and replay"
```

---

### Task 9: Publish the provider-free conformance kit and CLI

**Files:**
- Create: `src/aeread/runner/conformance.py`
- Modify: `src/aeread/cli.py`
- Create: `tests/shared_runner/test_conformance.py`

**Interfaces:**
- Consumes: registered environment/verifier plugins and fixture descriptors.
- Produces: `run_conformance(plugin_id, fixture_dir) -> AdmissionReport` and CLI commands `aeread env validate`, `aeread env test`, `aeread receipt verify`.

- [ ] **Step 1: Write CLI and conformance failure tests**

```python
def test_conformance_rejects_private_information_leak(leaky_plugin, tmp_path) -> None:
    report = run_conformance(leaky_plugin, fixture_dir(tmp_path))
    assert report.status == "rejected"
    assert "private_noninterference" in report.failed_checks


def test_cli_env_test_returns_nonzero_for_rejected_plugin(monkeypatch) -> None:
    assert cli.main(["env", "test", "leaky_market"]) == 1
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_conformance.py -v`

Expected: FAIL because conformance/CLI commands do not exist.

- [ ] **Step 3: Implement the conformance matrix**

Run deterministic success, no-deal, malformed, illegal, missing, timeout, simultaneous snapshot, privacy, scorer, replay, interrupted-resume, and zero-versus-invalid fixtures. Emit machine-readable `AdmissionReport` with check IDs, evidence refs, claimed capabilities, and admitted profiles.

- [ ] **Step 4: Refactor CLI dispatch without breaking Exchange verbs**

Change `main()` to accept optional `argv`; retain existing `run/eval/sweep/submit/validate-case/baselines`; add nested handlers for `env` and `receipt`; test both old and new help/exit behavior.

- [ ] **Step 5: Run CLI/conformance tests**

Run: `pytest tests/shared_runner/test_conformance.py tests/test_exchange_v1_runner.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/runner/conformance.py src/aeread/cli.py tests/shared_runner/test_conformance.py
git commit -m "feat: publish environment conformance commands"
```

---

### Task 10: Add the Exchange V1 compatibility plugin and parity gate

**Files:**
- Create: `src/aeread/families/__init__.py`
- Create: `src/aeread/families/exchange_v1_compat.py`
- Create: `tests/shared_runner/test_exchange_parity.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: current `exchange_economy.run_exchange_transcript`, `exchange_v1_scoring`, runner SDK/kernel.
- Produces: entry-point plugin `aeread.exchange_v1_compat` and `compare_exchange_runs(legacy_dir, shared_dir) -> ParityReport`.

- [ ] **Step 1: Write provider-free parity tests**

```python
@pytest.mark.parametrize("case_name", [
    "case01_visible_bilateral_ir",
    "case02_multiparty_clearing",
    "case03_hidden_discovery",
    "case04_consent_under_hidden_info",
])
def test_exchange_legacy_and_shared_runner_match(case_name, tmp_path) -> None:
    legacy = run_legacy_offline(case_name, seed=7, out=tmp_path / "legacy")
    shared = run_shared_offline(case_name, seed=7, out=tmp_path / "shared")
    report = compare_exchange_runs(legacy.run_dir, shared.run_dir)
    assert report.mismatches == ()
```

- [ ] **Step 2: Run one parity test and verify failure**

Run: `pytest tests/shared_runner/test_exchange_parity.py -k case01 -v`

Expected: FAIL because the compatibility plugin does not exist.

- [ ] **Step 3: Implement the compatibility plugin**

Map the legacy ten stages to declared phases and canonical events. During migration, reuse legacy state transition/scoring functions instead of rewriting economics. Convert legacy response records into explicit attempts only when their provenance is observable; mark legacy hidden-retry limitations in the receipt rather than fabricating attempt rows.

- [ ] **Step 4: Implement exact parity comparison**

Compare terminal allocation hash, `w_real`, denominator, denominator tier, AER, validity/failure class, logical action count, observable provider call count, and replay terminal hash. Numeric comparisons use the existing scorer's precision, not a new tolerance.

- [ ] **Step 5: Register the plugin**

```toml
[project.entry-points."aeread.environments"]
exchange_v1_compat = "aeread.families.exchange_v1_compat:plugin"
```

- [ ] **Step 6: Run the complete parity matrix**

Run: `pytest tests/shared_runner/test_exchange_parity.py -v`

Expected: PASS for all listed cases and seeds.

- [ ] **Step 7: Commit**

```bash
git add src/aeread/families pyproject.toml tests/shared_runner/test_exchange_parity.py
git commit -m "feat: run exchange through shared kernel"
```

---

### Task 11: Document the public SDK and run release gates

**Files:**
- Modify: `CONTRIBUTING.md`
- Modify: `README.md`
- Create: `docs/environment_authoring.md`
- Create: `examples/environment_plugin_minimal.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: one documented data-only case path, one plugin authoring path, and one executable provider-free example.

- [ ] **Step 1: Add a docs example test**

Create a pytest that imports `examples/environment_plugin_minimal.py`, registers its fake market, runs its fixture, and asserts a valid replayable receipt.

- [ ] **Step 2: Run the example test and verify failure**

Run: `pytest tests/shared_runner/test_conformance.py -k documented_example -v`

Expected: FAIL until the example exists.

- [ ] **Step 3: Write the authoring guide and example**

Document package layout, entry points, manifests, slot/channel semantics, privacy, invalid actions, scorer separation, fixture requirements, versioning, and admission profiles. The example has two seats, one simultaneous offer phase, one deterministic transition, and no provider dependency.

- [ ] **Step 4: Run focused and full verification**

Run: `pytest tests/shared_runner tests/test_shared_runner_design_contract.py tests/test_exchange_v1_runner.py -q`

Expected: PASS.

Run: `pytest -q`

Expected: all tests PASS; the existing three optional integration skips and one documented xfail may remain only if their reasons are unchanged.

- [ ] **Step 5: Verify the built wheel imports cleanly**

Run: `python -m build && python -c 'import aeread.sdk.v1; print("ok")'`

Expected: wheel builds and prints `ok` without importing external adapter packages.

- [ ] **Step 6: Commit**

```bash
git add CONTRIBUTING.md README.md docs/environment_authoring.md examples/environment_plugin_minimal.py tests/shared_runner
git commit -m "docs: publish environment authoring sdk"
```

---

## Completion gate

This plan is complete only when:

- `aeread.sdk.v1` is importable and schema JSON can be generated;
- a fake provider-free family passes every conformance check;
- a raised provider exception leaves a complete started/failed attempt chain;
- a simultaneous multi-channel fixture freezes observations and applies one atomic transition;
- replay uses zero external calls and reproduces state and score hashes;
- every planned cell ends in a valid receipt or typed invalid measurement;
- the Exchange parity matrix is green;
- the full existing suite remains green;
- Housing and external adapters can depend only on the published SDK, not runner internals.
