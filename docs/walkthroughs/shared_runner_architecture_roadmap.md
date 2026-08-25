# Walkthrough: AERead current-to-shared runner architecture and build roadmap

**Entry point:** `src/aeread/cli.py:main()` (line 27), then
`src/aeread/exchange_v1_runner.py:run_v1()` (line 950)

**Trigger:** `aeread run`, or the existing evaluation, sweep, and submission drivers that
call `run_v1()` as a library function

**Source baseline:** `main` at `7aea2687804f8f458ac41061cc649c289ebfb3ef`

**Design baseline:** PR #7 at `fa81b6b8f17ab8ef2f05da0523652395f27794ac`

**Files involved:**

- `src/aeread/cli.py` — dispatches CLI verbs to Exchange-specific modules.
- `src/aeread/exchange_v1_runner.py` — resolves one Exchange run, selects policies,
  records calls and artifacts, delegates the protocol, and finalizes metadata.
- `src/aeread/exchange_economy.py` — owns the fixed Exchange round protocol and state
  mutations.
- `src/aeread/exchange_v1_pilot.py` — expands cases, agents, and seeds and handles
  whole-job recovery and aggregation.
- `src/aeread/exchange_v1_sweep.py` — executes a Cartesian grid and writes CSV results.
- `src/aeread/exchange_v1_submit.py` — evaluates a submitted agent against frozen
  panels and verifies replay.
- `src/aeread/exchange_v1_scoring.py` — converts an Exchange run directory into the
  current AER result.
- `docs/shared_runner_design.md` — normative planned architecture.
- `docs/verifier_taxonomy.md` — measurement/verifier taxonomy; it remains separate from
  the runner object taxonomy below.

**What changes:** the current path reads an Exchange config, makes provider calls, mutates
an `ExchangeWorld`, and writes a self-contained run directory. The planned architecture
retains those assets behind an `exchange_v1` compatibility plugin, but moves experiment
resolution, phase scheduling, agent execution, attempts, canonical evidence, receipts, and
analysis into a family-neutral kernel.

The complete one-run compatibility boundary traced below spans
`src/aeread/exchange_v1_runner.py:L950-L1234`; its concrete protocol boundary spans
`src/aeread/exchange_economy.py:L4919-L5078`.

---

## Part I. Current execution path

### Step 1: Dispatch a CLI verb

`src/aeread/cli.py:L27-L40`

```python
def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: aeread <verb> [options]   (verb --help for details)\n\nverbs:")
        for verb, (_, desc) in VERBS.items():
            print(f"  {verb:14s} {desc}")
        return 0
    verb = argv[0]
    if verb not in VERBS:
        print(f"aeread: unknown verb {verb!r} (try `aeread --help`)", file=sys.stderr)
        return 2
    module = VERBS[verb][0]
    sys.argv = [f"aeread {verb}"] + argv[1:]
    runpy.run_module(module, run_name="__main__")
```

The CLI is a dispatcher, not the shared runner. `run`, `eval`, `sweep`, and `submit` enter
different Exchange-specific orchestration modules.

**Calls →** Step 2 for one Exchange run, or a higher-level driver that eventually calls
Step 2 once per grid cell.

**Data flow:** command-line arguments become module-specific arguments; there is no common
`RunSpec` or resolved suite plan.

### Step 2: Enter the one-run compatibility spine

`src/aeread/exchange_v1_runner.py:L950-L973`

```python
def run_v1(
    config_path: Optional[str | Path] = None,
    *,
    mode: str = "offline",
    seed: Optional[int] = None,
    out_root: str | Path = "runs",
    options: Optional[InferenceOptions] = None,
    rounds_override: Optional[int] = None,
    controllers_override: Optional[list[int]] = None,
    replay_from: Optional[str | Path] = None,
    run_id: Optional[str] = None,
    quiet: bool = False,
    strict: bool = False,
    under_test_agent: Optional[Any] = None,
) -> RunOutcome:
    """Execute one run end-to-end and return its self-contained run directory.

    Library entry point used by the CLI, the sweep harness, and tests alike.
    In replay mode the config, seed, models and sampling params are taken from
    the source run's artifacts — a replay reproduces the original run, period.
    With strict=True a funnel-check mismatch raises (after all artifacts are
    written) instead of merely stamping status=manifest_incomplete: a call
    missing from the manifest means the run is not faithfully replayable.
    """
```

This function is the valuable compatibility spine. Its public parameters combine concerns
that the planned system splits among `CaseManifest`, `AgentProfile`, `RunSpec`, and
`RunPlan`.

**Calls →** config resolution and artifact initialization.

**Data flow:** Exchange JSON plus runtime overrides becomes one resolved Exchange config.

### Step 3: Resolve the Exchange config and claim a run directory

`src/aeread/exchange_v1_runner.py:L999-L1041`

```python
    options = options or InferenceOptions()
    config_path = Path(config_path)
    if not config_path.is_file():
        raise RunnerError(f"config not found: {config_path}")
    config_bytes = config_path.read_bytes()
    config = resolve_config(
        config_path,
        seed=seed,
        rounds_override=rounds_override,
        controllers_override=controllers_override,
    )
    resolved_dict = dataclasses.asdict(config)

    # D9: a `roles` block in the config JSON selects the per-seat composite path.
    # The engine's config loader ignores unknown keys, so we read it from the raw
    # bytes; embedding it in the snapshot makes replay re-derive the seat table.
    raw_config = json.loads(config_bytes.decode("utf-8"))
    roles_block = raw_config.get("roles") if isinstance(raw_config, dict) else None
    role_table: Optional[RoleTable] = None
    if roles_block is not None:
        resolved_dict["roles"] = roles_block
        if mode != "offline":  # offline scripts every seat; roles kept for provenance only
            try:
                role_table = parse_role_table(roles_block, config.num_agents)
            except RoleConfigError as err:
                raise RunnerError(f"invalid roles block in {config_path}: {err}") from err

    if mode == "offline":
        model_label = "offline"
    elif role_table is not None:
        under_test_policy = role_table.group_for("under_test").policy
        model_label = under_test_policy.get("model") or under_test_policy["kind"]
    else:
        model_label = options.model
    run_id = run_id or make_run_id(
        config.name,
        f"{model_label}-replay" if mode == "replay" else model_label,
        config.seed,
    )
    run_dir = Path(out_root) / run_id
    if run_dir.exists():
        raise RunnerError(f"run dir already exists: {run_dir}")
    run_dir.mkdir(parents=True)
```

The current runner does resolve and hash important inputs, but it does not expand and seal
all suite cells before execution. Its `roles` block is also embedded in an Exchange config
rather than resolved through a family-neutral seat assignment.

**Mutation:** creates the run directory.

**Danger zone:** a recovery path must choose a new attempt directory or resume the existing
one; blindly repeating the same `run_id` hits `run directory already exists`.

**Calls →** metadata writing and engine execution.

### Step 4: Build the world and delegate control to the Exchange engine

`src/aeread/exchange_v1_runner.py:L1109-L1147`

```python
    try:
        world = ex.make_world_from_config(config)
        policy = build_policy(
            mode, config, options, role_table=role_table, under_test_agent=under_test_agent
        )
        if mode != "offline":
            from aeread import llm_agent

            if not quiet:
                print(
                    f"[{mode}] {config.name} seed={config.seed} rounds={config.rounds} "
                    f"model={model_label} -> {run_dir}",
                    flush=True,
                )
            recorder = ManifestRecorder(
                run_dir,
                total_rounds=config.rounds,
                label=mode,
                verbose=not quiet,
            )
            # composite: every recording-capable seat shares the run's recorder
            for sub_policy in getattr(policy, "sub_policies", (policy,)):
                if hasattr(sub_policy, "v1_recorder"):
                    sub_policy.v1_recorder = recorder
            previous_observer = llm_agent.set_call_observer(
                lambda record: observed_calls.__setitem__(0, observed_calls[0] + 1)
            )
            previous_replay_dir = llm_agent.set_replay_dir(
                replay_source / "llm_cache" if mode == "replay" else None
            )
            hooks_installed = True
        result = ex.run_exchange_transcript(
            world,
            rounds=config.rounds,
            controllers=config.controllers,
            policy=policy,
            protocol=config.protocol,
            trace_jsonl_path=run_dir / "trace.jsonl",
        )
```

This is the central architectural boundary: the wrapper installs observation/replay hooks,
then the concrete family engine owns scheduling. The planned architecture inverts that
ownership: the generic runner owns scheduling and invokes an `EnvironmentPlugin` one phase at a
time.

**Mutation:** constructs and later mutates an `ExchangeWorld`; installs execution hooks;
may make provider calls; writes call artifacts and trace rows.

**Calls →** Step 5, the fixed Exchange protocol.

### Step 5: Execute the fixed Exchange round protocol

`src/aeread/exchange_economy.py:L4919-L5018`

The source sequence is:

```python
    _ensure_information_reveal_protocol(world, protocol, history, controller_id=controller_id)
    communication_ids = _communication_agent_ids_for(protocol, world, controller_id)
    if hasattr(policy, "communication_texts"):
        communication_texts = policy.communication_texts(world, communication_ids, t, history)
    else:
        communication_texts = {
            aid: policy.communication_text(world, aid, t, history)
            for aid in communication_ids
        }
    proposal_text = policy.propose_text(world, controller_id, t, history, communication_texts)
    responders = response_agent_ids or _response_agent_ids_for(
        protocol,
        world,
        controller_id,
        proposal_text=proposal_text,
        communication_texts=communication_texts,
    )
    blank = RoundTranscript(t, controller_id, proposal_text, {}, "", communication_texts)
    responder_ids = []
    for aid in responders:
        _idx(aid, world.num_agents, "responder")
        if aid == controller_id:
            continue
        responder_ids.append(aid)
    coordination_cost = apply_institutional_costs(
        world,
        world.institution_pressure,
        t,
        contacted_agent_count=len(responder_ids),
    )
    if hasattr(policy, "response_texts"):
        response_texts = policy.response_texts(world, responder_ids, blank, history)
    else:
        response_texts = {
            aid: policy.respond_text(world, aid, blank, history)
            for aid in responder_ids
        }
    draft = RoundTranscript(t, controller_id, proposal_text, response_texts, "", communication_texts)
    if protocol.atomic_commit:
        final_text = _atomic_commit_final_text(proposal_text)
    else:
        final_text = policy.finalize_text(world, controller_id, draft, history)
    transcript = RoundTranscript(t, controller_id, proposal_text, response_texts, final_text, communication_texts)
    compiled = policy.compile_transcript(world, transcript)
    verified_before_private_acceptance = policy.verify_compilation(world, transcript, compiled)
    verified = verified_before_private_acceptance
    private_acceptance_audits: list[PrivateAcceptanceAudit] = []
    if protocol.private_acceptance_check and not protocol.atomic_commit and verified.transfers:
        debited_agents = _debited_agent_ids(verified)
        if protocol.private_acceptance_mode == "deterministic_oracle":
            acceptance_texts = {}
        elif hasattr(policy, "private_acceptance_texts"):
            acceptance_texts = policy.private_acceptance_texts(
                world,
                debited_agents,
                transcript,
                verified,
                history,
            )
        else:
            acceptance_texts = {}
        verified, private_acceptance_audits = enforce_private_acceptance(
            verified,
            acceptance_texts,
            world=world,
            mode=protocol.private_acceptance_mode,
        )
    event = apply_compiled_mechanism(
        world, verified, round_index=t, controller_id=controller_id,
        ir_enforce=protocol.ir_enforce,
    )
    event.private_acceptance_audits = private_acceptance_audits
    event.coordination_cost = coordination_cost
    _append_trace_jsonl(
        trace_jsonl_path,
        transcript=transcript,
        compiled=compiled,
        verified_before_private_acceptance=verified_before_private_acceptance,
        executed=verified,
        event=event,
    )
    return event, float(coordination_cost.get("net_coordination_cost") or 0.0)
```

Communication, proposal, response, finalization, compilation, verification, private
acceptance, and mutation are encoded as Exchange functions rather than data-driven phase
instances. The compatibility adapter must map each boundary to a `PhaseInstance` and
canonical events without changing allocation or score semantics.

**Data flow:** current world plus history → policy text → compiled mechanism → verified
mechanism → mutated world plus one `RoundEvent`.

**Calls →** Step 6 until the fixed round budget is exhausted.

### Step 6: Repeat rounds and construct an Exchange result

`src/aeread/exchange_economy.py:L5021-L5078`

```python
    for t in range(1, rounds + 1):
        controller_id = controllers[(t - 1) % len(controllers)]
        event, net_cost = run_one_round(
            world, t, controller_id, history, policy, protocol,
            response_agent_ids=response_agent_ids, trace_jsonl_path=trace_jsonl_path,
        )
        coordination_cost_total += net_cost
        history.append(event)

    final_welfare = total_welfare(world)
    return RunResult(
        initial_allocation=initial_allocation,
        final_allocation=world.copy_allocation(),
        history=history,
        initial_welfare=initial_welfare,
        final_welfare=final_welfare,
        optimum_welfare=optimum_welfare,
        initial_welfare_ratio=0.0,
        final_welfare_ratio=(
            1.0 if optimum_welfare <= initial_welfare + 1e-12
            else max(0.0, min(1.0, (final_welfare - initial_welfare) / (optimum_welfare - initial_welfare)))
        ),
        initial_gini=initial_gini,
        final_gini=gini(utility_vector(world)),
        final_institutions=active_institutions(world, rounds + 1),
        coordination_cost_total=coordination_cost_total,
        final_net_welfare=final_welfare - coordination_cost_total,
    )
```

The engine returns an Exchange-specific `RunResult`. The planned `EnvironmentPlugin.outcome()`
retains this family object, while the scorer exposes selected estimands through a typed
`ScoreEnvelope`.

**Calls →** runner finalization and separate AER scoring.

### Step 7: Observe provider calls after they return

`src/aeread/exchange_v1_runner.py:L673-L692`

```python
        def _call(self, role, system, prompt, model, max_tokens, agent_id=None, round_index=None):
            response = super()._call(
                role, system, prompt, model, max_tokens,
                agent_id=agent_id, round_index=round_index,
            )
            if self.v1_recorder is not None:
                temperature, sample = self._role_sampling(role)
                self.v1_recorder.record(
                    role=role,
                    agent_id=agent_id,
                    round_index=round_index if round_index is not None else self._v1_round_hint,
                    system=system,
                    prompt=prompt,
                    response=response,
                    model=model,
                    params={"max_tokens": max_tokens, "temperature": temperature, "sample": sample},
                    batched=False,
                    seat=getattr(self, "v1_seat", "env"),
                )
            return response
```

This records useful prompts, responses, usage, costs, model pins, and replay snapshots. It
does so after the external call returns, so it cannot prove that a started call with an
ambiguous outcome existed after a crash. The new kernel requires
**write-before-side-effect** start events and exactly one terminal event.

**Data flow:** provider response → manifest row and response snapshot.

### Step 8: Finalize summary and run status

`src/aeread/exchange_v1_runner.py:L1185-L1211`

```python
    summary = ex.build_run_summary_payload(
        result,
        config=config,
        usage=usage,
        model=model_label,
    )
    summary["run_id"] = run_id
    summary["mode"] = mode
    summary["cost_line"] = _cost_line(usage)
    summary["manifest_totals"] = recorder.totals() if recorder is not None else None
    _write_json(run_dir / "summary.json", summary)

    # a funnel mismatch means a call is missing from the manifest, i.e. the run
    # is NOT faithfully replayable — never label that "complete"; a violated
    # panel pin outranks both (the exam itself changed under the candidate)
    meta["status"] = (
        "complete" if funnel_check is None or funnel_check["ok"] else "manifest_incomplete"
    )
    if pin_check is not None and not pin_check["ok"]:
        meta["status"] = "panel_drift"
    meta["completed_utc"] = _utc_now_iso()
    meta["duration_seconds"] = round(time.monotonic() - started, 3)
    meta["usage"] = usage
    meta["funnel_check"] = funnel_check
    meta["pin_check"] = pin_check
    meta["manifest_totals"] = recorder.totals() if recorder is not None else None
    _write_json(run_dir / "run_meta.json", meta)
```

Current truth is spread across `run_meta.json`, `trace.jsonl`,
`inference_manifest.jsonl`, `llm_cache/`, `summary.json`, and optional submission reports.
The planned `EvaluationReceipt` binds the canonical roots and inclusion decision without
replacing those family/compatibility projections.

---

## Part II. Canonical runner taxonomy

The object model is divided by responsibility. Measurement-verifier families remain in
`verifier_taxonomy.md`; they are not execution objects.

```text
1. Definition   what can be evaluated
2. Experiment   what evaluation is requested and resolved
3. Execution    what actually happens
4. Evidence     what is durably recorded
5. Measurement  what claim the evidence supports
6. Analysis     what population/fixed-panel result is reported
7. Interop      what derived external format is emitted
```

### 1. Definition objects

| Object | Canonical meaning | Must not mean |
|---|---|---|
| `FamilyManifest` | Serialized identity, roles, phases, capabilities, measurements, and implementation references for one protocol family/version. | Executable plugin code. |
| `EnvironmentPlugin` | Registered executable implementation of family state, observation, action, transition, and outcome hooks. | Experiment scheduler, provider client, scorer, reference provider, or generator. |
| `VerifierPlugin` | Registered deterministic scorer over a family outcome and sealed evidence. | Environment scheduler or candidate/provider caller. |
| `ReferenceProvider` | Typed reference implementation role; not a separate public Protocol or entry-point group in `0.1`. It may be supplied through a family/verifier implementation with a declared validity domain. | A generic oracle label for every reference. |
| `CaseGenerator` | Typed generation implementation role; not a separate public Protocol or entry-point group in `0.1`. It may be supplied through family or source-adapter materialization. | Environment scheduler or analysis plan. |
| `CaseManifest` | One immutable world instance, seats, family-typed payload, split, seed, provenance, and hash. | Agent/model assignment. |
| upstream task | External benchmark's identifier mapped to one AERead case and retained as `upstream_task_id`. | A second native object parallel to `CaseManifest`. |

A family is a protocol type such as `exchange_v1` or `housing_v1`; a case is one fixed
world. A manifest is data, while a plugin is code.

### 2. Experiment objects

| Object | Canonical meaning |
|---|---|
| `SuiteManifest` | Versioned selection of cases plus references to sampling, evaluation, and analysis declarations. |
| `SamplingPlan` | Target population or fixed panel, selection procedure, seeds, pairing, nesting, and replicate counts. |
| `EvaluationBlock` | Controlled, cross-play, self-play, or human/reference comparison with declared subject and controlled seats. |
| `AgentProfile` | Fully specified model, harness, prompt, runtime, tools/memory, reasoning condition, sampling, budgets, and retry policy. |
| `RunSpec` | Unresolved evaluation request: suite, blocks, profiles, assignments, modes, and overrides. |
| `RunPlan` | Fully resolved, pinned, canonicalized, and hashed plan written before external calls. |
| `PlanCell` | One planned case × block × seat assignment × seed × replicate execution unit. |

`RunSpec` is user intent; `RunPlan` is benchmark truth. A `SuiteManifest` references a
`SamplingPlan` and `AnalysisPlan` rather than becoming an untyped container for statistical
choices.

### 3. Execution objects

```text
PlanCell
└── Episode
    └── EpisodeAttempt
        └── PhaseInstance
            ├── DecisionSlot 1..n
            │   ├── ActionChannel 1..n
            │   └── LogicalAction (exactly one per DecisionSlot)
            │       ├── ActionAttempt 1..n
            │       │   ├── ProviderCall*
            │       │   ├── ToolInvocation*
            │       │   └── CanonicalResponse 0..1
            │       ├── ParseResult
            │       ├── LegalityResult
            │       └── ActionBundle 0..1
            │           └── ActionEnvelope 0..n (ordered)
            └── TransitionResult
```

| Object | Canonical meaning |
|---|---|
| `Episode` | Intended economic trajectory for a `PlanCell`. In `0.1`, enforce **one `PlanCell` = one `Episode`**. |
| `EpisodeAttempt` | One operational attempt to realize the episode. Retrying infrastructure does not create a new independent case. |
| `PhaseSpec` | Reusable declarative phase definition. |
| `PhaseInstance` | One occurrence of a phase, such as `round_3/contact`. |
| `DecisionSlot` | One runner-requested economic decision opportunity with a stable slot identity. |
| `ActionChannel` | One typed directed action lane within a decision slot, including minimum and maximum action cardinality. |
| `LogicalAction` | The evidence identity for the one economic decision requested by one `DecisionSlot`. |
| `ActionAttempt` | One declared attempt to produce the logical action; a retry creates a new attempt. |
| `ProviderCall` | One atomic model-provider request, including request/response evidence and provider status. |
| `ToolInvocation` | One atomic tool side effect or result. Repeated tools are separate invocations. |
| `AttemptObserver` | Runner-owned interface through which an `AgentAdapter` records each provider call before and after the side effect. |
| `CanonicalResponse` | Agent-adapter output presented to the family parser. |
| `ActionBundle` | One slot-keyed atomic parse result containing ordered channel actions; partial bundles are never applied. |
| `ActionEnvelope` | One ordered action inside the slot's atomic `ActionBundle`, plus evidence references. |
| `TransitionResult` | New family state, typed consequences, next-phase choice, and/or termination signal. |

One `DecisionSlot` creates one `LogicalAction`, and one successful logical action closes as one ordered atomic `ActionBundle`.
`DecisionSlot` and `ActionChannel` define environment decision topology; `LogicalAction`,
`ActionAttempt`, `ProviderCall`, `ToolInvocation`, and `AttemptObserver` define execution and
evidence. A scripted output or pre-call failure can therefore produce an `ActionAttempt`
with zero `ProviderCall` records without losing the slot or logical-action identity.

The earlier `CallAttempt` term is scheduled for retirement before the final `0.1`
serialized contract. It conflates an attempt to produce an economic action with an atomic
provider request. A tool-using action can contain multiple `ProviderCall` and
`ToolInvocation` records without being a retry. Under `minimal_chat/1.0`, one
`ActionAttempt` happens to contain one `ProviderCall`; that is a profile constraint, not a
universal invariant.

The normative ProviderCall target is not yet the current import surface. The current SDK
still exposes `CallAttemptStart` / `CallAttemptToken` with `call_attempt_id` as compatibility
names. Task 2.1 performs the serialized migration to `ProviderCallStart` /
`ProviderCallToken` and `provider_call_id`; this roadmap does not claim those target names
are already importable.

### 4. Evidence objects

| Object | Canonical meaning |
|---|---|
| `Event` | Immutable fact in the canonical timeline with stable IDs, type, visibility, payload reference, and hash-chain fields. |
| `Artifact` | Content-addressed bytes such as a prompt, raw response, state snapshot, judge record, or upstream task. |
| `Projection` | Deterministically derived view: public transcript, per-seat trajectory, provider ledger, legacy trace, or external export. |
| `EvaluationReceipt` | Final seal connecting plan, events, artifacts, implementations, measurement, validity, replay level, and inclusion. |

An event is not its payload. An artifact is not automatically publishable. A projection is
never the source of truth. A receipt is not another event log.

### 5. Measurement objects

| Object | Canonical meaning |
|---|---|
| `EstimandSpec` | Claimed quantity/property, direction, units, conditions, and cluster mapping. |
| `VerifierSpec` | Semantic verifier family, input scope, reference kind, determinism, composition, implementation, and validity domain. |
| `ReferenceSpec` | Canonical target, rule, exact optimum, bound, executable baseline, comparison field, human reference, or judge protocol. |
| `MetricValue` | One typed numeric/categorical result with units and provenance. |
| `ScoreEnvelope` | Family measurement vector, reference values, outcome fields, validity, scorer, and evidence references. |
| `ValidityReport` | Whether evidence is admissible and why; it is not economic utility. |

Reserve `oracle` for an exact, proven reference inside a declared validity domain. A
full-information relaxation is a `BoundProvider`, a scripted policy is a
`BaselineProvider`, and a gold refund state is a `CanonicalReference`. These are typed
implementation roles, not promised standalone public Protocols or entry-point groups in
`0.1`; the measurement surface should preserve them rather than forcing every reference
through `build_oracle()`.

Verifier, scorer, and validity remain distinct: a verifier establishes a declared property
against a reference; a scorer constructs the typed metric vector; validity decides whether
the evidence may enter analysis.

### 6. Analysis objects

| Object | Canonical meaning |
|---|---|
| `ClusterSpec` | Independently sampled/assigned unit, pairing/block map, and nested-replicate structure for one estimand. |
| `AnalysisPlan` | Estimand, inclusion/missingness, aggregation, uncertainty, multiplicity, and sensitivity rules. |
| `AggregateResult` | Population or fixed-panel result derived only from validated receipts. |

A cluster is not a task category, folder, or post-hoc similarity group. It is declared per
estimand before outcomes are observed.

### 7. Interoperability objects

`rLLM`, Harbor/ATIF, Prime Verifiers, and upstream benchmark artifacts are adapters or
`Projection` formats. They consume AERead native plans, events, artifacts, scores, and
receipts; they do not define benchmark truth.

---

## Part III. Current-to-planned architecture

### Current

```text
aeread CLI
  -> pilot / sweep / submit (optional grid orchestration)
  -> exchange_v1_runner.run_v1
  -> Exchange config + RoleTable
  -> build ExchangeWorld and policy
  -> exchange_economy.run_exchange_transcript
  -> fixed Exchange round loop
  -> trace + inference manifest + response cache + summary
  -> Exchange scoring / replay byte comparison / driver aggregation
```

### Planned

```text
FamilyManifest + CaseManifest + SuiteManifest + AgentProfile + RunSpec
  -> resolver / registry / strict validation / canonical hashing
  -> immutable RunPlan
  -> generic runner-owned PhaseSpec scheduler
       -> EnvironmentPlugin: state / observe / parse / legal / step / terminal / outcome
       -> runner ActionAttempt
            -> AgentAdapter(request, attempts=runner AttemptObserver)
                 -> ProviderCall* / ToolInvocation* / CanonicalResponse
  -> canonical Event log + content-addressed Artifact store
  -> VerifierSpec + ScoreEnvelope + ValidityReport
  -> EvaluationReceipt
  -> AnalysisPlan / ClusterSpec / AggregateResult
  -> optional interoperability Projections
```

The architectural inversion is deliberate: today the concrete Exchange engine runs the
experiment and the wrapper observes it; planned, the shared kernel runs the experiment and
an environment plugin supplies economic hooks.

### Compatibility mapping

| Current asset | Planned home | Migration rule |
|---|---|---|
| resolved Exchange config and roles | `CaseManifest`, `AgentProfile`, `RunSpec`, `RunPlan` | Split world, agent, and experiment concerns; prove the resolved legacy snapshot maps losslessly. |
| `run_v1()` | `exchange_v1` compatibility adapter plus generic kernel | Keep the public compatibility entry point during migration. |
| `run_one_round()` stages | `PhaseSpec` and `EnvironmentPlugin` hooks | Map boundaries without rewriting economic semantics first. |
| `ManifestRecorder` rows | `ProviderCall` projections | Retain legacy schema as a deterministic projection of canonical events/artifacts. |
| `trace.jsonl` | Exchange public/evaluator projection | Preserve byte parity where possible; canonical events become source of truth. |
| `llm_cache/` | content-addressed raw response artifacts | Preserve replay keys and response hashes. |
| `run_meta.json` + `summary.json` | `EvaluationReceipt` plus compatibility projections | Receipt binds roots and validity rather than copying all payloads. |
| `exchange_v1_scoring.score_run()` | Exchange scorer producing `ScoreEnvelope` | Preserve `w_real`, denominator tier, raw AER, and failure semantics. |
| pilot/sweep/submission grids | `SuiteManifest`, `SamplingPlan`, `EvaluationBlock`, `AnalysisPlan` | Replace ad hoc expansion only after output parity is demonstrated. |

---

## Part IV. Gated build roadmap

Do not implement all layers in one branch. Each stage begins only when its dependency gates
pass and produces a reviewable artifact.

| Stage | Dependency | Deliverable | Exit gate |
|---|---|---|---|
| R0 | approved design | Freeze this taxonomy, ownership boundary, identifier hierarchy, compatibility map, and serialization naming. | Contract test green; no unresolved overloaded term. |
| R1 | R0 | Strict `0.1` authoring schemas and registry: `FamilyManifest`, `CaseManifest`, `SuiteManifest`, `SamplingPlan`, `EvaluationBlock`, `AnalysisPlan`, `AgentProfile`, and `RunSpec`. | Invalid fixtures fail before side effects; unknown fields are rejected. |
| R2 | R1 | Deterministic resolver producing canonical, hashed `RunPlan` and `PlanCell` records. | Same inputs produce identical bytes/hash; all defaults and implementation pins are explicit. |
| R3 | R2 | Provider-free generic phase scheduler with a minimal fixture `EnvironmentPlugin`, simultaneous frozen observations, parsing, legality, transitions, and termination. | Phase graph and simultaneous/noninterference conformance tests pass without provider calls. |
| R4 | R3 | Agent adapter and evidence kernel: `LogicalAction`, `ActionAttempt`, `ProviderCall`, `ToolInvocation`, canonical events, artifacts, typed failures, budgets, and retries. | Every started side effect reconciles to one terminal/unknown event; no hidden retry. |
| R5 | R4 | `EvaluationReceipt`, deterministic replay, interrupted resume, projections, and coverage reconciliation. | Crash-point tests recover or mark `outcome_unknown`; every planned cell has a receipt or typed exclusion. |
| R6 | R5 | `exchange_v1` compatibility `EnvironmentPlugin` and `VerifierPlugin` bridge. | **exchange_v1 parity** for allocation, `w_real`, denominator/tier, AER, failure class, evidence counts, and replay on provider-free and frozen fixtures. |
| R7 | R6 plus Housing P0 fixes | Native `housing_v1` `EnvironmentPlugin`, bounded-welfare references, controlled counterpart block, and paired cluster plan. | Same kernel/conformance suite passes; no family branch exists in the kernel. |
| R8 | R7 | Pinned tau3 retail adapter, 18-task component-parity pilot, then full suite and receipt-driven paper tables. | State/tool/scorer parity, replay, provenance, cluster intervals, and fixed-suite claim language pass. |

### Stage ownership

- Shared-runner owner: R1–R6 kernel, schemas, evidence, receipts, and Exchange compatibility.
- Family owners: family semantics and fixtures used by R6–R8.
- Measurement owner: `EstimandSpec`, `VerifierSpec`, reference validity, cluster mapping,
  aggregation, and paper-language gates.
- Interoperability owners: derived adapters after native receipt parity exists.

### Pull-request boundaries

Prefer one PR per stage, with R4 optionally split into agent execution and evidence storage
if the review surface becomes large. Do not combine Housing semantic repairs with the
generic scheduler, and do not begin tau3 integration before Exchange and Housing exercise
the same kernel.

---

## Danger zones

| # | Location | Risk | Planned mitigation |
|---|---|---|---|
| 1 | `exchange_v1_runner.py:L673-L692` | Provider evidence is written only after the call returns; a crash can leave an ambiguous unrecorded side effect. | R4 write-before-side-effect start and terminal/unknown events. |
| 2 | `exchange_v1_runner.py:L1038-L1041`; `exchange_v1_pilot.py:L161-L182` | The mute retry recursively reuses the same derived run ID after the first attempt created its directory, so real recovery can hit `run directory already exists`; the current test mocks away the filesystem interaction. | `EpisodeAttempt` identity and explicit retry/resume destination; add an end-to-end filesystem regression test before migration. |
| 3 | `exchange_v1_runner.py:L1109-L1158` | Observer/replay hooks span the engine call and must always be restored; leakage can contaminate later cells. | Adapter-scoped lifecycle and receipt coverage checks in `finally`. |
| 4 | `exchange_economy.py:L4919-L5018` | Scheduling, observations, provider calls, compilation, verification, and mutation are interleaved in one family function. | R3 runner-owned phase boundaries and pure/auditable family hooks. |
| 5 | current replay path | Replay reruns a completed episode from cached responses but cannot safely continue a partially completed one. | R5 event-chain reconstruction, idempotency reconciliation, and `outcome_unknown`. |
| 6 | current driver/scorer modules | Failure, missingness, aggregation, and scoring rules are spread across runner, pilot, sweep, submit, and scoring modules. | Typed receipts plus `AnalysisPlan`; invalid measurement never becomes economic zero. |
| 7 | reference naming | Calling a full-information upper bound an oracle overstates attainable knowledge. | Exact `oracle` reservation plus typed canonical, baseline, bound, comparison, and judge reference providers. |

## Invariants

- The shared kernel never imports a concrete family or branches on `family_id`.
- Economic state and action semantics remain family-owned.
- `RunPlan` bytes and IDs are fixed before external calls.
- In `0.1`, one `PlanCell` = one `Episode`; operational reruns create new
  `EpisodeAttempt` identities, not new independent clusters.
- One `LogicalAction` may have multiple `ActionAttempt` records only under the declared
  retry policy.
- One `ActionAttempt` may contain multiple `ProviderCall` and `ToolInvocation` records;
  this is not itself evidence of a retry.
- Every external side effect has a durable start event before execution and one terminal
  success, failure, or `outcome_unknown` event.
- Simultaneous actors observe one frozen pre-phase state, and deterministic application
  order does not create an economic first-mover advantage.
- Valid zero or negative outcomes remain valid; missing/corrupt evidence is not zero.
- A scorer is deterministic and never calls the candidate/provider.
- Every reported number traces through `AggregateResult` → validated receipts → score and
  evidence roots → one immutable `RunPlan`.
- No cross-family scalar exists unless a paper separately declares and defends its
  transformations and weights.
