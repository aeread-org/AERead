# Walkthrough: Housing V1 environment architecture

**Entry point**: `src/aeread/shared_runner/housing_experiment.py:run_housing_reasoning_experiment()`
(line 1350)

**Trigger**: `python -m aeread.shared_runner.housing_experiment --mode full --output <path>`
for the paired experiment, or `python -m aeread.shared_runner.housing --output <path>`
for one smoke cell.

**Files involved**:

- `src/aeread/housing_env.py` — world generation and the mutable Housing market state machine.
- `src/aeread/shared_runner/housing.py` — Housing family plugin, manifests, providers, scoring,
  receipts, and replay.
- `src/aeread/shared_runner/scheduler.py` — provider-independent phase scheduler.
- `src/aeread/shared_runner/execution.py` — provider calls, retries, budgets, and evidence.
- `src/aeread/shared_runner/receipts.py` — immutable evaluation receipt contract.
- `src/aeread/shared_runner/housing_experiment.py` — paired plans, admission, resumable batches,
  and cluster analysis.

**What changes**: plan construction reads source files to pin their hashes. Execution may call
OpenRouter and writes a canonical RunPlan, event log, response artifacts, state-transition
evidence, result row, score, and receipt below the requested evidence root. `HousingMarket`
mutates only an in-memory reconstruction during execution; replay starts from the sealed case
and recomputes every transition without a provider call.

## Topology

```text
experiment controller
  -> two sealed RunPlans (reasoning none / low)
    -> interleaved resumable cell queue
      -> generic execute_plan_cell
        -> generic phase scheduler
          -> HousingV1Plugin hooks
            -> HousingMarket: contact -> respond -> commit
        -> evidence reconciliation
      -> Housing scorer -> EvaluationReceipt
      -> provider-free state-and-score replay
    -> world-cluster paired analysis
```

The central boundary is deliberate: the runner owns execution, identities, concurrency,
provider calls, evidence, retries, receipts, and reporting. The Housing plugin owns private
observations, action meaning, legal transitions, terminal economics, and its verifier.

---

## Step 1: lock the experiment before executing cells

`src/aeread/shared_runner/housing_experiment.py:L1350-L1373`

```python
async def run_housing_reasoning_experiment(
    *,
    mode: str,
    output_root: str | Path,
    concurrency: int = 2,
    spend_limit_usd: float | None = None,
    tenant_provider: Any | None = None,
    progress_callback: Any | None = None,
    openrouter_route: OpenRouterRoutePin = CONFIRMATORY_EXPERIMENT_ROUTE,
) -> dict[str, Any]:
    """Run the locked dry, admission, or 100x2x3 Housing experiment workflow."""

    if mode not in {"dry-run", "admission", "full"}:
        raise ValueError("mode must be dry-run, admission, or full")
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    panel = derive_world_seeds(master_seed=20260826, count=100)
    admission_panel = derive_world_seeds(master_seed=20260827, count=3)
    if set(panel) & set(admission_panel):
        raise ValueError("admission and confirmatory world panels must be disjoint")
    if spend_limit_usd is None:
        spend_limit_usd = {"dry-run": 1.0, "admission": 0.10, "full": 6.0}[mode]
    if mode == "full" and spend_limit_usd <= 0.10:
        raise ValueError("full mode requires more than $0.10 for admission plus batch")
```

The controller derives two disjoint seed panels before outcomes: three admission worlds and
100 analysis worlds. `full` mode cannot enter the sample directly. It first runs the
admission panel, validates the route and reasoning treatment, subtracts admission cost, and
only then releases the 600 sample cells.

**Calls** -> Step 2

**Data flow**: `{world seeds, conditions, replicates, route pin, budget}` become two condition-
specific sealed plans.

### DANGER ZONE A1: the controller is Housing-experiment-specific

The admission rules and 100-by-2-by-3 design live in `housing_experiment.py`; they are not a
generic shared-runner primitive. A refund or supply-chain experiment can reuse the execution,
evidence, and receipt layers, but needs its own design/admission wrapper or a future generic
experiment controller.

## Step 2: compile family semantics into sealed RunPlans

`src/aeread/shared_runner/housing.py:L1541-L1565`

```python
    family = FamilyManifest.from_dict(
        {
            "spec_version": "aeread.family/0.1",
            "family": {"id": "housing_v1", "version": "1.0.0", "plugin_id": "aeread.housing_v1"},
            "environment": {
                "topology": "market_with_private_preferences",
                "phase_specs": ["contact", "respond", "commit"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "tenant": {"testable": True, "scripted_policies": ["housing_scripted_tenant_v1"]},
                "landlord": {"testable": False, "scripted_policies": ["housing_scripted_landlord_v1"]},
            },
            "measurement": {
                "primary_estimand": "social_welfare",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "optimum_lower_bound": "housing_feasible_zero_v1",
                "comparison_baseline": "housing_naive_v1",
                "optimum_upper_bound": "housing_exact_assignment_v1",
                "optimum_upper_bound_kind": "full_information_relaxation",
                "bound_status": "bracketed",
                "outcome_support": "case_specific",
            },
```

`src/aeread/shared_runner/housing.py:L1798-L1838`

```python
    plugin = HousingV1Plugin()
    registry = PluginRegistry()
    registry.register(family, plugin)
    housing_source = Path(hz.__file__).read_bytes()
    bridge_source = Path(__file__).read_bytes()
    execution_source = Path(__file__).with_name("execution.py").read_bytes()
    housing_digest = hashlib.sha256(housing_source).hexdigest()
    bridge_digest = hashlib.sha256(bridge_source).hexdigest()
    combined_digest = hashlib.sha256(housing_source + bridge_source).hexdigest()
    execution_digest = hashlib.sha256(execution_source).hexdigest()
    pins = [
        _pin("aeread.housing_v1", "family_plugin", combined_digest),
        _pin("housing_outcome_v1", "scorer", combined_digest),
        _pin("housing_exact_assignment_v1", "reference", housing_digest),
        _pin("housing_feasible_zero_v1", "reference", bridge_digest),
        _pin("housing_naive_v1", "reference", housing_digest),
        _pin("housing_generator_v1", "generator", housing_digest),
        _pin("minimal_chat", "harness", execution_digest, version="1.0"),
        _pin("aeread.shared_runner.housing", "runtime", bridge_digest, version="0.1.0"),
    ]
    if tenant_provider == "openrouter":
        pins.append(
            _pin(
                "aeread.shared_runner.execution",
                "runtime",
                execution_digest,
                version="0.1.0",
            )
        )
    plan = resolve_run_plan(
        families=(family,),
        cases=tuple(cases),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(tenant_profile, landlord_profile),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
    )
```

Each case carries the world seed, seats, round/action budget, visibility policy, and generator
provenance. The sampling plan declares `world_seed` as the cluster and the replicate as a
nested episode attempt. Agent profiles bind prompts, action schemas, model/revision, reasoning
condition, route, pricing, retries, timeout, and output budget. Source digests bind the family,
scorer, oracle, generator, runtime, and harness to the plan.

**Calls** -> Step 3

**Data flow**: validated manifests plus implementation hashes become immutable `PlanCell`s.

### DANGER ZONE A2: source pinning is not environment packaging

The plan proves which local source bytes were used; it does not itself package dependencies or
reconstruct the Python environment. Portable execution still requires the declared runtime and
compatible dependencies to exist.

## Step 3: execute exactly one sealed cell

`src/aeread/shared_runner/execution.py:L2793-L2803`

```python
    """Execute one sealed R2 cell through the R3 scheduler and R4 adapter."""
    verify_run_plan(plan)
    plan_path = Path(evidence_root) / plan.run_plan_id / "run_plan.json"
    expected_plan_bytes = canonical_json_bytes(plan)
    if plan_path.exists():
        if plan_path.read_bytes() != expected_plan_bytes:
            raise EvidenceIntegrityError(
                f"existing RunPlan bytes differ from {plan.run_plan_id}: {plan_path}"
            )
    else:
        write_run_plan(plan, plan_path)
```

`src/aeread/shared_runner/execution.py:L2871-L2907`

```python
    destination = (
        Path(evidence_root)
        / plan.run_plan_id
        / cell.cell_id
        / episode_attempt_id
    )
    evidence = EvidenceStore(
        destination,
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_id=episode_id,
        episode_attempt_id=episode_attempt_id,
    )
    executor = MinimalChatExecutor(
        evidence=evidence,
        profiles=selected_profiles,
        prompt_sources=prompt_sources,
        providers=providers,
        pricing=pricing,
        request_seed_by_profile=request_seed_by_profile,
    )
    result = await run_episode(
        cell=cell,
        case=case,
        plugin=plugin,
        response_source=executor,
    )
    evidence.audit_reconciliation()
    return CellExecution(
        run_plan_id=plan.run_plan_id,
        cell_id=cell.cell_id,
        episode_attempt_id=episode_attempt_id,
        episode_result=result,
        evidence=evidence,
        action_executions=executor.executions(),
        total_cost_usd=executor.total_cost_usd,
    )
```

`execute_plan_cell` is the generic R4 boundary. It rejects changed plan bytes, resolves the
family plugin and profiles from the plan, derives stable episode/attempt identities, creates
an append-only evidence store, and hands provider ownership to `MinimalChatExecutor` while the
scheduler remains provider-independent.

**Calls** -> Step 4

**Data flow**: one `PlanCell` becomes `{EpisodeResult, evidence, action executions, cost}`.

## Step 4: reconstruct the Housing world and phase graph

`src/aeread/shared_runner/housing.py:L457-L495`

```python
    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("housing payload must be a mapping")
        expected = {
            "world_kind",
            "world_seed",
            "num_tenants",
            "num_listings",
            "rounds",
            "common_weight",
        }
        if set(payload) != expected:
            raise ValueError("housing payload fields are incomplete or unexpected")
        if payload["world_kind"] != "bid":
            raise ValueError("only the pinned bid world is supported")
        integers: dict[str, int] = {}
        for field, minimum in (
            ("world_seed", 0),
            ("num_tenants", 1),
            ("num_listings", 1),
            ("rounds", 1),
        ):
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")
            integers[field] = value
        common_weight = payload["common_weight"]
        if not _finite_number(common_weight) or not 0.0 <= float(common_weight) <= 1.0:
            raise ValueError("common_weight must be between zero and one")
        world = hz.make_bid_world(
            integers["num_tenants"],
            integers["num_listings"],
            seed=integers["world_seed"],
            common_weight=float(common_weight),
        )
        return {**integers, "common_weight": float(common_weight), "world": world}

    def initial_state(self, case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        return _snapshot_market(hz.HousingMarket(case["world"], rounds=case["rounds"]))
```

`src/aeread/shared_runner/housing.py:L497-L531`

```python
    def phases(self, case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        tenant_budget = case["num_tenants"] * case["rounds"]
        landlord_budget = case["num_listings"] * case["rounds"]
        return (
            PhaseSpec(
                phase_id="contact",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={"tenant": "housing_tenant_contact_observation_v1"},
                action_schema_by_role={"tenant": "housing_contact_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("respond",),
            ),
            PhaseSpec(
                phase_id="respond",
                actor_selector="open_landlords",
                mode="simultaneous",
                observation_schema_by_role={"landlord": "housing_landlord_respond_observation_v1"},
                action_schema_by_role={"landlord": "housing_respond_v1"},
                max_logical_actions=landlord_budget,
                invalid_action_policy="family_defined",
                next_phases=("commit",),
            ),
            PhaseSpec(
                phase_id="commit",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={"tenant": "housing_tenant_commit_observation_v1"},
                action_schema_by_role={"tenant": "housing_commit_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("contact",),
            ),
        )
```

The world is regenerated from the sealed seed. The mutable market is immediately serialized
to a plain snapshot so every hook receives a copy rather than a shared live object. All three
phases are simultaneous batches.

**Calls** -> Step 5

**Data flow**: case payload -> `BidWorld` -> serialized initial `HousingMarket` state plus a
validated cyclic phase graph.

## Step 5: enforce private information at observation construction

`src/aeread/housing_env.py:L373-L415`

```python
    def tenant_observation(self, tenant_id: int) -> Dict[str, Any]:
        """Information visible to one tenant; other private types are omitted."""
        if not self._valid_tenant(tenant_id):
            raise ValueError(f"unknown tenant {tenant_id!r}")
        out: Dict[str, Any] = {
            "role": "tenant",
            "tenant_id": tenant_id,
            "round_index": self.round_index,
            "phase": self.phase,
            "board": self.board(),
            "rejected_listing_ids": sorted(self.rejected[tenant_id]),
            "active_hold": self._holds.get(tenant_id),
        }
        if hasattr(self.world, "weights"):
            out["private_weights"] = list(self.world.weights[tenant_id])
            out["valuation_formula"] = {
                "attributes": ATTRIBUTES,
                "attribute_scores": (
                    "campus=10-minutes_to_campus/5; safety=10-crime_index; "
                    "groceries=10-minutes_to_groceries/3; "
                    "room=min(10,2.5*beds+2.5*baths); "
                    "orientation=South:10,East:8,West:6,North:4"
                ),
                "wtp": "1200 + 220 * weighted_attribute_score",
            }
        else:
            out["private_values"] = list(self.world.values[tenant_id])
        return out

    def landlord_observation(self, listing_id: int) -> Dict[str, Any]:
        """Information visible to one landlord, including only its own inbox."""
        if not self._valid_listing(listing_id):
            raise ValueError(f"unknown listing {listing_id!r}")
        listing = next(row for row in self.board() if row["listing_id"] == listing_id)
        return {
            "role": "landlord",
            "listing_id": listing_id,
            "round_index": self.round_index,
            "phase": self.phase,
            "listing": listing,
            "private_cost": self.world.costs[listing_id],
            "inbox": tuple(self._offers.get(listing_id, ())),
        }
```

Tenants see the public board and only their own values; landlords see only their listing,
private cost, and inbox. The public ask differs from private cost. The scheduler freezes every
observation before any peer request is dispatched.

**Calls** -> Step 6

**Data flow**: one pre-phase state -> one seat-specific immutable observation per eligible
actor.

### DANGER ZONE A3: privacy is application code, not an automatic information-flow proof

The runner preserves and labels seat-local observations, but Housing decides their contents.
Adding a field to `tenant_observation` or `landlord_observation` can leak private state unless
privacy tests and review are updated.

## Step 6: freeze a simultaneous phase and ask every actor

`src/aeread/shared_runner/scheduler.py:L733-L805`

```python
        if phase.mode in {"single", "simultaneous"}:
            # Freeze every view before dispatch. Even a response source with
            # synchronous side effects cannot change a peer's observation.
            for seat_id in actors:
                observations[seat_id] = _observe(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    seat_id=seat_id,
                    phase=phase,
                )
            envelopes: dict[str, ActionEnvelope] = {}
            action_specs: list[tuple[str, int]] = []
            for seat_id in actors:
                logical_action_count += 1
                phase_action_counts[phase.phase_id] = (
                    phase_action_counts.get(phase.phase_id, 0) + 1
                )
                if logical_action_count > cell.case_max_logical_actions:
                    raise SchedulerContractError(
                        "case logical-action budget exceeded before termination"
                    )
                if phase_action_counts[phase.phase_id] > phase.max_logical_actions:
                    raise SchedulerContractError(
                        f"phase logical-action budget exceeded for {phase.phase_id!r}"
                    )
                action_specs.append((seat_id, logical_action_count - 1))

            async def request(spec: tuple[str, int]) -> LogicalActionRecord:
                seat_id, action_ordinal = spec
                return await _request_action(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    cell=cell,
                    episode_id=episode_id,
                    phase=phase,
                    phase_instance_id=phase_instance_id,
                    seat_id=seat_id,
                    role=role_by_seat[seat_id],
                    observation=observations[seat_id],
                    action_ordinal=action_ordinal,
                    response_source=response_source,
                )

            if phase.mode == "simultaneous":
                requested = await asyncio.gather(
                    *(request(spec) for spec in action_specs),
                    return_exceptions=True,
                )
                first_error = next(
                    (item for item in requested if isinstance(item, BaseException)),
                    None,
                )
                if first_error is not None:
                    raise first_error
                records = requested
            else:
                records = [await request(spec) for spec in action_specs]
            for record in records:
                if not isinstance(record, LogicalActionRecord):
                    raise SchedulerContractError(
                        "simultaneous action did not return a logical-action record"
                    )
                action_records.append(record)
                envelopes[record.seat_id] = record.envelope
            transition = _step(
                plugin=plugin,
                family_case=family_case,
                state=state,
                phase=phase,
                actions=envelopes,
            )
```

The scheduler owns ordering, stable identities, phase/action budgets, observation freezing, and
concurrent dispatch. It applies exactly one Housing transition after all peer responses return.

**Calls** -> Step 7

**Data flow**: frozen observations -> provider responses -> parsed/legal `ActionEnvelope`s ->
one deterministic batch transition.

### DANGER ZONE A4: one actor infrastructure failure aborts the cell

`asyncio.gather` collects peer calls, but the first provider/harness exception aborts the
phase. That is recorded as operational missingness rather than converted to an agent pass.
Malformed or illegal *returned actions* are different: they become typed family-defined
passes and remain valid economic outcomes.

## Step 7: translate a decision into a provider call with evidence and retries

`src/aeread/shared_runner/execution.py:L1791-L1814`

```python
        return ProviderRequest(
            provider_call_id=provider_call_id,
            provider=profile.model.provider,
            base_url=profile.model.base_url,
            model=profile.model.model,
            revision=profile.model.revision,
            instructions=self._prompt_text[profile.profile_id],
            input_text=input_text,
            temperature=temperature,
            top_p=profile.sampling.top_p,
            max_output_tokens=max_output_tokens,
            reasoning_effort=profile.reasoning.effort,
            timeout_seconds=profile.budgets.timeout_seconds,
            request_sha256="",
            max_cost_usd=profile.budgets.max_cost_usd,
            output_schema=output_schema,
            provider_metadata=(
                profile.harness.config.get("provider_metadata")
                or profile.harness.config.get("provider_runtime")
            ),
            seed=self._request_seed_by_profile.get(
                profile.profile_id, profile.sampling.seed
            ),
        ).with_computed_hash()
```

`src/aeread/shared_runner/execution.py:L1898-L1942`

```python
            provider = self._providers[profile.model.provider]
            try:
                result = await asyncio.wait_for(
                    provider.complete(request), timeout=profile.budgets.timeout_seconds
                )
            except asyncio.TimeoutError as error:
                failure = ProviderFailure("timeout", str(error), retryable=True)
                should_retry = self._record_provider_failure(
                    decision,
                    profile,
                    request,
                    action_attempt_id,
                    ordinal,
                    retry_reason,
                    attempts,
                    failure,
                )
                if should_retry:
                    retry_reason = failure.condition
                    continue
                raise failure from error
            except ProviderFailure as failure:
                should_retry = self._record_provider_failure(
                    decision,
                    profile,
                    request,
                    action_attempt_id,
                    ordinal,
                    retry_reason,
                    attempts,
                    failure,
                )
                if should_retry:
                    retry_reason = failure.condition
                    if failure.condition == "length":
                        max_output_tokens *= 2
                    elif failure.condition in {"rate_limit", "provider_5xx"}:
                        await self._wait_before_provider_retry(
                            decision=decision,
                            request=request,
                            condition=failure.condition,
                            ordinal=ordinal,
                        )
                    continue
                raise
```

The executor hashes every request and records call start, success/failure, route/model, tokens,
cost, response, retry reason, and action-attempt lifecycle. Paired conditions get the same
provider seed for the same world and replicate. The experiment profiles start at 4,096 output
tokens, permit one length expansion to 8,192, use a 120-second deadline, and bound transient
provider retries.

**Calls** -> Step 8

**Data flow**: `DecisionRequest` plus pinned profile -> `ProviderRequest` ->
`CanonicalResponse`, cost record, and evidence events.

### DANGER ZONE A5: timeout outcome and billing are unknown

A timeout does not prove the provider did no work. The adapter records it as outcome-unknown;
the failed cell receives no economic score, and the externally billed cost can exceed recorded
cost.

## Step 8: parse syntax, then check state-dependent legality

`src/aeread/shared_runner/scheduler.py:L526-L579`

```python
        parsed = plugin.parse_action(
            family_case,
            _copy_for_hook(state, "parse state"),
            seat_id,
            phase,
            _copy_for_hook(raw_response, "canonical response"),
        )
```

```python
    if parsed.ok:
        try:
            legality = plugin.legal(
                family_case,
                _copy_for_hook(state, "legality state"),
                seat_id,
                phase,
                _copy_for_hook(parsed.action, "parsed action"),
            )
```

```python
    valid = parsed.ok and legality is not None and legality.legal
    failure_code = parsed.error_code if not parsed.ok else legality.reason
    envelope = ActionEnvelope(
        seat_id=seat_id,
        valid=valid,
        action=parsed.action if valid else None,
        parse=parsed,
        legality=legality,
    )
```

Housing parsing enforces the exact phase schema. Legality then verifies current availability,
non-negative finite rent, real offer IDs, and an active immutable `hold_id`. Parser or legality
failures are evidence, not scheduler crashes; because Housing declares `family_defined`, an
invalid action reaches the transition as an invalid envelope and becomes a typed pass.

**Calls** -> Step 9

**Data flow**: canonical response -> `ParseResult` -> `LegalityResult` -> `ActionEnvelope`.

## Step 9: apply `contact -> respond -> commit`

### 9a. Contact creates real, addressed offers

`src/aeread/housing_env.py:L477-L492`

```python
            offer = Offer(
                offer_id=f"offer:r{self.round_index}:t{t}:l{listing_id}",
                tenant_id=t,
                listing_id=listing_id,
                rent=float(rent),
                round_index=self.round_index,
            )
            inbox.setdefault(listing_id, []).append(offer)
            verdicts[t] = self._verdict(t, "contact", "applied", reference_id=offer.offer_id)
        for listing_id in inbox:
            inbox[listing_id].sort(key=lambda offer: (-offer.rent, offer.tenant_id))
        frozen_inbox = {listing_id: tuple(listing_offers)
                        for listing_id, listing_offers in inbox.items()}
        self._offers = frozen_inbox
        self.phase = "respond"
        return PhaseResult(phase="contact", verdicts=verdicts, inbox=dict(frozen_inbox))
```

Each unmatched tenant can create one offer. The environment produces the identity; agents
cannot fabricate it. Inbox order is deterministic.

### 9b. Respond creates at most one immutable hold per listing

`src/aeread/housing_env.py:L552-L583`

```python
            binding = [tenant_id for tenant_id, (decision, _) in parsed.items()
                       if decision in {"accept", "counter"}]
            if len(binding) > 1:
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "hold_capacity_exceeded"
                )
                continue

            hold: Optional[Hold] = None
            if binding:
                tenant_id = binding[0]
                decision, counter = parsed[tenant_id]
                rent = offered[tenant_id].rent if decision == "accept" else float(counter)
                hold = Hold(
                    hold_id=f"hold:r{self.round_index}:t{tenant_id}:l{listing_id}",
                    tenant_id=tenant_id,
                    listing_id=listing_id,
                    rent=rent,
                    round_index=self.round_index,
                )
                holds[tenant_id] = hold
            for tenant_id in offered:
                if hold is None or tenant_id != hold.tenant_id:
                    self.rejected[tenant_id].add(listing_id)
                    self.wasted_contacts += 1
            verdicts[listing_id] = self._verdict(
                listing_id, "respond", "applied",
                reference_id=hold.hold_id if hold is not None else None,
            )
        self._holds = holds
        self.phase = "commit"
        return PhaseResult(phase="respond", verdicts=verdicts, holds=dict(holds))
```

In the confirmatory block, landlords are controlled by a deterministic local policy. The
domain still uses the same landlord observation/action/transition path that a live landlord
would use.

### 9c. Commit signs only the frozen hold

`src/aeread/housing_env.py:L620-L648`

```python
            if hold is None or hold.hold_id != hold_id:
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "unknown_hold"
                )
                if hold is not None:
                    self.rejected[tenant_id].add(hold.listing_id)
                continue
            if (hold.round_index != self.round_index or hold.listing_id in self._taken
                    or tenant_id in self._matched):
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "unavailable_hold"
                )
                continue
            if decision == "sign":
                self._taken.add(hold.listing_id)
                self._matched.add(tenant_id)
                self.pairs.append((tenant_id, hold.listing_id))
                self.signed_rent[tenant_id] = hold.rent
            else:
                self.rejected[tenant_id].add(hold.listing_id)
            verdicts[tenant_id] = self._verdict(
                tenant_id, "commit", "applied", reference_id=hold.hold_id
            )
        self.pairs.sort()
        self._offers = {}
        self._holds = {}
        self.round_index += 1
        self.phase = "finished" if self.finished else "contact"
        return PhaseResult(phase="commit", verdicts=verdicts)
```

The tenant cannot resubmit listing or rent. Signing consumes both unit-demand capacities;
walking or invalid commitment expires the hold. After four rounds—or when no unmatched tenant
or open listing remains—the market terminates.

**Calls** -> Step 10

**Data flow**: valid and invalid envelopes -> deterministic `PhaseResult` plus serialized next
state -> repeated phase cycle or terminal state.

## Step 10: compute terminal economics, references, and score

`src/aeread/housing_env.py:L655-L678`

```python
    def economics(self) -> TerminalEconomics:
        """Complete terminal allocation and transfer accounting for both sides."""
        tenant_payoffs = {t: 0.0 for t in range(self.world.num_tenants)}
        landlord_payoffs = {l: 0.0 for l in range(self.world.num_listings)}
        ir_violations: List[str] = []
        for tenant_id, listing_id in self.pairs:
            rent = self.signed_rent[tenant_id]
            tenant_payoffs[tenant_id] = round(self.world.values[tenant_id][listing_id] - rent, 2)
            landlord_payoffs[listing_id] = round(rent - self.world.costs[listing_id], 2)
            if tenant_payoffs[tenant_id] < 0:
                ir_violations.append(f"tenant:{tenant_id}")
            if landlord_payoffs[listing_id] < 0:
                ir_violations.append(f"landlord:{listing_id}")
        social_welfare = round(
            sum(tenant_payoffs.values()) + sum(landlord_payoffs.values()), 2
        )
        return TerminalEconomics(
            assignment=self.result(),
            signed_rents=dict(self.signed_rent),
            tenant_payoffs=tenant_payoffs,
            landlord_payoffs=landlord_payoffs,
            social_welfare=social_welfare,
            ir_violations=tuple(ir_violations),
        )
```

`src/aeread/shared_runner/housing.py:L707-L744`

```python
    def terminal(self, case, state) -> dict[str, Any] | None:
        market = _restore_market(case, state)
        if not market.finished:
            return None
        economics = market.economics()
        oracle = hz.assignment_oracle(market.world.surplus)
        baseline = hz.run_scripted_market(
            market.world,
            rounds=case["rounds"],
            strategy="naive",
        )
        score = (
            economics.social_welfare / oracle.total if oracle.total > 0 else None
        )
        return {
            "reason": "deadline" if market.round_index >= market.rounds else "allocation",
            "assignment_pairs": [list(pair) for pair in economics.assignment.pairs],
            "signed_rents": [
                {"tenant_id": tenant_id, "rent": rent}
                for tenant_id, rent in sorted(economics.signed_rents.items())
            ],
            "tenant_payoffs": {
                f"tenant_{tenant_id}": payoff
                for tenant_id, payoff in sorted(economics.tenant_payoffs.items())
            },
            "landlord_payoffs": {
                f"landlord_{listing_id}": payoff
                for listing_id, payoff in sorted(economics.landlord_payoffs.items())
            },
            "social_welfare": economics.social_welfare,
            "feasible_floor": 0.0,
            "baseline_total": baseline.total,
            "oracle_total": oracle.total,
            "within_case_score": score,
            "ir_violations": list(economics.ir_violations),
            "wasted_contacts": market.wasted_contacts,
            "bound_semantics": "full_information_allocation_relaxation",
        }
```

Rent cancels in social welfare but remains visible in side-specific capture. `L=0` is the
feasible no-trade lower bound on the optimum; `B` is the same-world naive scripted policy; `U`
is exact maximum-weight one-to-one matching with full private information. The within-case
score is `R/U`, can be negative for a legal value-destroying match, and cannot exceed one.

The scorer independently checks finite fields, bound semantics and order, `B <= U`, `R <= U`,
seat-payoff reconciliation, IR/contact types, and the exact ratio. It never clamps a negative
outcome to zero.

**Calls** -> Step 11

**Data flow**: terminal state -> native welfare/payoffs plus `L/B/U` -> validated
`ScoreEnvelope`.

### DANGER ZONE A6: the oracle is an allocation relaxation

`U` has all private information and ignores the interactive information/round constraints. It
is a valid welfare ceiling, not a claim that an interactive policy can attain it. No price/core
oracle exists, so distributional capture is descriptive rather than normatively optimal.

## Step 11: replay first, then seal the evaluation receipt

`src/aeread/shared_runner/housing.py:L1088-L1113`

```python
    execution.evidence.audit_reconciliation()
    recorded_outcome, outcome_event = _replay_housing_state_from_evidence(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
    )
    if canonical_json_bytes(recorded_outcome) != canonical_json_bytes(
        execution.episode_result.outcome
    ):
        raise ValueError("execution outcome does not match the event log")

    score = plugin.build_scorer(family_case)(
        recorded_outcome,
        evidence_refs=(outcome_event.event_id,),
    )
    execution.evidence.append_event(
        "score_recorded",
        {
            "primary_leaf_id": score.leaf.leaf_id,
            "outcome_event_id": outcome_event.event_id,
            "score": score,
        },
    )
    execution.evidence.audit_reconciliation()
    evidence_seal = execution.evidence.seal()
```

`src/aeread/shared_runner/receipts.py:L394-L423`

```python
def _receipt_content_sha256(receipt: EvaluationReceipt) -> str:
    payload = {
        item.name: getattr(receipt, item.name)
        for item in dataclasses.fields(receipt)
        if item.name != "receipt_sha256"
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def seal_evaluation_receipt(receipt: EvaluationReceipt) -> EvaluationReceipt:
    """Return the receipt with a digest over every field except the digest itself."""

    if not isinstance(receipt, EvaluationReceipt):
        raise MeasurementContractError("receipt must be an EvaluationReceipt")
    if receipt.receipt_sha256 is not None:
        raise MeasurementContractError("receipt is already sealed")
    return dataclasses.replace(receipt, receipt_sha256=_receipt_content_sha256(receipt))


def verify_evaluation_receipt(receipt: EvaluationReceipt) -> EvaluationReceipt:
    """Reject an unsealed or mutated receipt and return a verified receipt."""

    if not isinstance(receipt, EvaluationReceipt):
        raise MeasurementContractError("receipt must be an EvaluationReceipt")
    if receipt.receipt_sha256 is None:
        raise MeasurementContractError("receipt_sha256 is missing")
    expected = _receipt_content_sha256(receipt)
    if receipt.receipt_sha256 != expected:
        raise MeasurementContractError("receipt_sha256 does not match receipt content")
    return receipt
```

Replay reconstructs the initial state, eligible actors, action envelopes, and every transition
from the event log, then recomputes terminal outcome and score. A successful receipt binds
plan/case/profile/implementation hashes, cluster/pair/replicate identity, evidence seal, score,
observability limits, and `replay_level="state_and_score"`. An operational failure instead gets
an excluded `invalid_measurement` receipt with no economic score.

**Calls** -> Step 12

**Data flow**: reconciled evidence -> provider-free replay -> score -> immutable included or
excluded `EvaluationReceipt`.

### DANGER ZONE A7: local evidence durability is not remote durability

Content addressing detects mutation but does not prevent disk loss. The current confirmatory
raw archive is preserved locally and referenced by hash; it still needs an addressable remote
evidence store for independent long-term reproduction.

## Step 12: resume without replacing cells and analyze at the world level

`src/aeread/shared_runner/housing_experiment.py:L839-L884`

```python
    conditions, identities = _validate_paired_setups(setups)
    output = Path(output_root)
    existing_by_condition: dict[str, dict[str, dict[str, Any]]] = {}
    all_existing_rows: list[dict[str, Any]] = []
    for condition in conditions:
        _recover_orphan_attempts(
            setup=setups[condition],
            condition_id=condition,
            output_root=output,
        )
        rows = read_condition_results(
            output, condition_id=condition, verify_evidence=True
        )
        valid_cell_ids = {cell.cell_id for cell in setups[condition].plan.cells}
        by_cell: dict[str, dict[str, Any]] = {}
        for row in rows:
            cell_id = row.get("cell_id")
            if (
                cell_id not in valid_cell_ids
                or row.get("run_plan_id") != setups[condition].plan.run_plan_id
            ):
                raise ValueError("existing result does not belong to the sealed RunPlan")
            if cell_id in by_cell:
                raise ValueError(f"duplicate existing cell result: {cell_id}")
            by_cell[cell_id] = row
        existing_by_condition[condition] = by_cell
        all_existing_rows.extend(rows)

    cells_by_condition = {
        condition: {
            (cell.world_seed, cell.replicate_index): cell
            for cell in setups[condition].plan.cells
        }
        for condition in conditions
    }
    tasks: list[tuple[str, Any]] = []
    for world_seed, replicate_index in identities:
        order = list(conditions)
        if _derived_nonnegative_int(
            "housing_condition_order_v1", world_seed, replicate_index
        ) % 2:
            order.reverse()
        for condition in order:
            cell = cells_by_condition[condition][(world_seed, replicate_index)]
            if cell.cell_id not in existing_by_condition[condition]:
                tasks.append((condition, cell))
```

`src/aeread/shared_runner/housing_experiment.py:L1165-L1189`

```python
        control_bounds = bounds[control_condition]
        treatment_bounds = bounds[treatment_condition]
        if control_bounds is not None and treatment_bounds is not None:
            control_lower, control_upper = control_bounds
            treatment_lower, treatment_upper = treatment_bounds
            lower_differences.append(treatment_lower - control_upper)
            upper_differences.append(treatment_upper - control_lower)
        if complete:
            control_mean = condition_world_means[control_condition][world_seed]
            treatment_mean = condition_world_means[treatment_condition][world_seed]
            complete_control.append(control_mean)
            complete_treatment.append(treatment_mean)
            complete_differences.append(treatment_mean - control_mean)
        else:
            incomplete_worlds.append(world_seed)

    if not complete_differences:
        raise ValueError("paired analysis has no complete world clusters")
    difference_array = np.asarray(complete_differences, dtype=float)
    rng = np.random.default_rng(bootstrap_seed)
    draws = rng.choice(
        difference_array,
        size=(bootstrap_draws, len(difference_array)),
        replace=True,
    ).mean(axis=1)
```

Existing results are admitted only after receipt/evidence verification, and their cells are
never rerun or replaced. Condition order is deterministically balanced within paired world-
replicates. The primary analysis averages three replicates within each condition/world, takes
the paired difference, and resamples worlds—not trajectories. Missing cells receive exact
world-specific legal score support only for the sensitivity bounds; observed scores remain
unchanged.

**Data flow**: verified cell receipts -> condition result rows -> within-world replicate means
-> paired world differences -> cluster bootstrap and missingness sensitivity bounds.

### DANGER ZONE A8: experiment rows are a derived index, not primary evidence

The JSON result rows make resume and analysis efficient, but the receipt plus sealed event and
artifact roots are authoritative. Analysis readers revalidate that chain before accepting a
row.

---

## Failure paths

| failure | classification | resulting evidence |
|---|---|---|
| malformed or state-illegal returned action | valid family-defined pass | included trajectory; failure code and consequences recorded |
| changed plan, profile, implementation pin, event, artifact, or receipt | integrity failure | cell rejected; no economic score |
| provider length/rate-limit/5xx within policy | bounded retry | every attempt and backoff recorded |
| timeout or transport interruption | outcome unknown | excluded operational receipt; billing may be unknown |
| retry exhaustion or per-profile cost breach | operational failure | excluded `invalid_measurement` receipt |
| interrupted durable attempt | reconciled on resume | completed evidence finalized, otherwise excluded; never silently rerun |
| no complete paired world | analysis deferred | coverage/status reported; no estimate emitted |

## Danger zones

| # | Location | Risk | Mitigation |
|---|---|---|---|
| A1 | `housing_experiment.py:1350` | design wrapper is Housing-specific | reuse generic execution/receipt layers; author family-specific design until controller is generalized |
| A2 | `housing.py:1798` | code hashes do not package dependencies | retain runtime/version pins and build a portable execution environment |
| A3 | `housing_env.py:373` | observation field can leak private types | explicit seat-local builders plus privacy contract tests |
| A4 | `scheduler.py:778` | one infrastructure error aborts a simultaneous phase | classify as operational missingness; never convert to economic zero |
| A5 | `execution.py:1900` | timeout work/cost may be unknowable | outcome-unknown evidence and separate billing caveat |
| A6 | `housing.py:712` | full-information allocation oracle can be overinterpreted | label it a relaxation; keep price/fairness oracle absent |
| A7 | `housing.py:1112` | content-addressed local data can still be lost | copy raw archive to an addressable remote evidence store |
| A8 | `housing_experiment.py:849` | derived result row can drift from evidence | verify receipt, seal, plan, and replay chain on every read |

## Invariants

1. A plan cell resolves exactly one case, family plugin, profile per seat, cluster, pair, and
   replicate identity, all bound by canonical hashes.
2. The control and treatment use identical world seeds, replicate indices, provider seeds,
   prompts, schemas, limits, landlord policy, model revision, and route; only reasoning effort
   changes.
3. Every simultaneous actor observes the same pre-phase state before any response is applied.
4. Tenants see only their own values; landlords see only their own cost and inbox.
5. A hold references a real offer, consumes at most one listing capacity, and freezes tenant,
   listing, rent, and round until sign/walk/expiry.
6. Malformed or illegal returned actions are typed passes; provider/harness failures are
   operational exclusions, never economic zeros.
7. Social welfare equals the sum of every tenant and landlord payoff; rent changes capture but
   not total surplus.
8. `L=0` bounds the optimum, not realized outcomes; `B` is a comparator; `U` is the exact
   full-information allocation relaxation.
9. An included receipt must replay state and score from sealed evidence without a provider
   call. An excluded receipt contains no economic score.
10. Existing cell evidence is verified and resumed, never overwritten or outcome-selected for
    replacement.
11. World seed is the independent analysis unit; three replicates, seats, calls, actions, and
    phases remain nested.

## Current architectural boundary

Housing now exercises the complete path from sealed design through live execution, native
measurement, receipt admission, deterministic replay, resumable batching, and cluster-level
analysis. What is reusable for refund and supply-chain families is the plan resolver, plugin
registry, scheduler, provider/evidence executor, receipt contract, replay-level declaration,
and batch/result integrity pattern. What remains family-specific is the world/state schema,
private observations, phase graph, action parser and legality, transition function, oracle and
scorer, exact outcome support, and experiment admission/design policy.
