"""Provider-free fixtures shared by shared-runner tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from aeread.sdk.v1 import (
    ActionBundle,
    ActionChannel,
    AgentContext,
    AgentExecutionConfig,
    AgentRequest,
    AttemptBudget,
    AttemptObserver,
    AgentProfile,
    CapabilityDeclaration,
    CaseManifest,
    CaseProvenance,
    ClusterSpec,
    CallAttemptStart,
    CallAttemptToken,
    CanonicalResponse,
    DecisionSlot,
    EvaluationBlock,
    FamilyManifest,
    FamilyOutcome,
    LegalityResult,
    MemoryPin,
    ModelPin,
    ObservationEnvelope,
    OptimizableOutcomeMeasurementSpec,
    OptimizationReferenceContract,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    PluginManifest,
    PinnedPluginRef,
    ProviderCallFailure,
    ProviderCallResult,
    ProviderPin,
    RetryPolicy,
    ResolutionInputs,
    RoleSpec,
    RunSpec,
    RuntimePin,
    SeatSpec,
    ScoreEnvelope,
    SealedEvidenceView,
    SamplingPin,
    SuiteManifest,
    TerminalResult,
    TransitionResult,
    ImplementationRef,
    content_sha256,
)


IDS = {
    "logical_action_id": "logical-action-1",
    "slot_id": "buyer-round-1",
    "seat_id": "buyer-1",
}

_SLOT = DecisionSlot(
    slot_id=IDS["slot_id"],
    seat_id=IDS["seat_id"],
    channels=(
        ActionChannel(
            channel_id="offers",
            recipient_seat_ids=("seller-1",),
            action_schema_ref="offer/1",
            min_actions=0,
            max_actions=1,
        ),
    ),
    observation_schema_ref="market-observation/1",
    response_schema_ref="market-response/1",
    order_key="0001",
)

_REQUEST_EXECUTION_CONFIG = AgentExecutionConfig(
    provider=ProviderPin(provider_id="fake", api_version="2026-08-01"),
    model=ModelPin(model_id="fake-model", revision="2026-08-01"),
    harness=ImplementationRef(
        implementation_id="fake-harness",
        version="1.0.0",
        content_sha256="1" * 64,
    ),
    runtime=RuntimePin(
        implementation=ImplementationRef(
            implementation_id="in_process",
            version="1.0.0",
            content_sha256="2" * 64,
        ),
        config={},
    ),
    prompt="You are a fake test agent.",
    prompt_sha256=content_sha256("You are a fake test agent."),
    sampling=SamplingPin(
        schema_id="generation_sampling",
        schema_version="1.0.0",
        content={"temperature": 0.0},
    ),
    tools=(),
    memory=MemoryPin(mode="none"),
    attempt_budget=AttemptBudget(timeout_seconds=1.0, output_token_limit=64),
    retry_policy=RetryPolicy(max_attempts=1),
)

REQUEST = AgentRequest(
    logical_action_id=IDS["logical_action_id"],
    phase_id="offers",
    slot=_SLOT,
    observation=ObservationEnvelope(
        schema_ref="market-observation/1",
        slot_id=IDS["slot_id"],
        visible_payload={},
        public_event_refs=(),
        private_event_refs=(),
    ),
    context=AgentContext(
        agent_profile_id="candidate",
        seat_id=IDS["seat_id"],
        provider="fake",
        model="fake-model",
        harness="fake-harness",
        runtime="in_process",
    ),
    agent_profile_sha256="0" * 64,
    execution_config_sha256=content_sha256(_REQUEST_EXECUTION_CONFIG),
    execution_config=_REQUEST_EXECUTION_CONFIG,
    budget=_REQUEST_EXECUTION_CONFIG.attempt_budget,
)

NO_RETRY = RetryPolicy(max_attempts=1)
LENGTH_RETRY_ONCE = RetryPolicy(
    max_attempts=2,
    retryable_conditions=("length",),
    length_retry_output_tokens=128,
)
EMPTY_LENGTH_RESPONSE = CanonicalResponse(content="", finish_reason="length")
VALID_RESPONSE = CanonicalResponse(content='{"offers": []}', finish_reason="stop")


@dataclass(frozen=True)
class FakeEnvironment:
    manifest: PluginManifest = PluginManifest(
        plugin_id="fake_market",
        plugin_version="1.0.0",
        sdk_api="aeread.sdk/v1",
    )

    def with_manifest(self, manifest: PluginManifest) -> "FakeEnvironment":
        return replace(self, manifest=manifest)

    def validate_case(self, payload: Mapping[str, object]) -> object:
        return dict(payload)

    def initial_state(self, case: object, cell: object) -> object:
        return {}

    def phase_graph(self, case: object) -> PhaseGraph:
        return PhaseGraph(
            initial_phase_id="offers",
            phases=(
                PhaseSpec(
                    phase_id="offers",
                    actor_selector="all",
                    mode="simultaneous",
                    observation_schema_by_role={},
                    action_schema_by_role={},
                    max_logical_actions=1,
                    invalid_action_policy="forfeit",
                    next_phases=(),
                ),
            ),
        )

    def decision_slots(
        self, case: object, state: object, phase: PhaseSpec
    ) -> Sequence[DecisionSlot]:
        return (_SLOT,)

    def observe(
        self,
        case: object,
        state: object,
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> ObservationEnvelope:
        return REQUEST.observation

    def parse_action(
        self,
        case: object,
        state: object,
        phase: PhaseSpec,
        slot: DecisionSlot,
        response: CanonicalResponse,
    ) -> ParseResult:
        return ParseResult(status="malformed", error_code="not_implemented")

    def legal(
        self,
        case: object,
        state: object,
        phase: PhaseSpec,
        bundle: ActionBundle,
    ) -> LegalityResult:
        return LegalityResult(status="legal")

    def step(
        self,
        case: object,
        state: object,
        phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle],
    ) -> TransitionResult:
        return TransitionResult(state={}, next_phase_id=None)

    def terminal(self, case: object, state: object) -> TerminalResult | None:
        return None

    def outcome(self, case: object, terminal: TerminalResult) -> FamilyOutcome:
        return FamilyOutcome(terminal_reason=terminal.reason, payload={})


@dataclass(frozen=True)
class FakeVerifier:
    manifest: PluginManifest = PluginManifest(
        plugin_id="fake_verifier",
        plugin_version="1.0.0",
        sdk_api="aeread.sdk/v1",
    )

    def score(
        self, case: object, outcome: FamilyOutcome, evidence: SealedEvidenceView
    ) -> ScoreEnvelope:
        raise NotImplementedError


@dataclass(frozen=True)
class FakeAgentAdapter:
    manifest: PluginManifest = PluginManifest(
        plugin_id="fake_agent",
        plugin_version="1.0.0",
        sdk_api="aeread.sdk/v1",
    )
    call_observability: str = "full"

    async def act(
        self, request: AgentRequest, *, attempts: AttemptObserver
    ) -> CanonicalResponse:
        return VALID_RESPONSE


@dataclass(frozen=True)
class FakeExecutionBackend:
    manifest: PluginManifest = PluginManifest(
        plugin_id="fake_backend",
        plugin_version="1.0.0",
        sdk_api="aeread.sdk/v1",
    )

    async def start(self, spec: object) -> object:
        return object()

    async def run(self, handle: object, request: object) -> object:
        return object()

    async def read(self, handle: object, path: str) -> bytes:
        return b""

    async def write(self, handle: object, path: str, data: bytes) -> None:
        return None

    async def stop(self, handle: object) -> None:
        return None


@dataclass(frozen=True)
class FakeBenchmarkSource:
    manifest: PluginManifest = PluginManifest(
        plugin_id="fake_source",
        plugin_version="1.0.0",
        sdk_api="aeread.sdk/v1",
    )

    def source_ref(self) -> object:
        return {"source": "fake"}

    def enumerate_cases(self, split: str) -> Sequence[object]:
        return ({"case": "one"},)

    def materialize_case(self, ref: object) -> object:
        return {"materialized": ref}

    def parity_fixtures(self) -> Sequence[object]:
        return ()


class FakeAttemptObserver:
    def call_started(self, start: CallAttemptStart) -> CallAttemptToken:
        return CallAttemptToken(call_attempt_id=start.call_attempt_id)

    def call_succeeded(
        self, token: CallAttemptToken, result: ProviderCallResult
    ) -> None:
        return None

    def call_failed(
        self, token: CallAttemptToken, failure: ProviderCallFailure
    ) -> None:
        return None


class MissingStepEnvironment:
    """Intentionally incomplete environment protocol implementation."""

    manifest = FakeEnvironment().manifest


def fake_implementation(
    implementation_id: str, version: str = "1.0.0", marker: str = "1"
) -> ImplementationRef:
    return ImplementationRef(
        implementation_id=implementation_id,
        version=version,
        content_sha256=marker * 64,
    )


def fake_pin(
    plugin_id: str, version: str = "1.0.0", marker: str = "1"
) -> PinnedPluginRef:
    return PinnedPluginRef(
        plugin={"plugin_id": plugin_id, "plugin_version": version},
        implementation=fake_implementation(plugin_id, version, marker),
    )


def fake_agent_profile(
    profile_id: str,
    *,
    adapter_id: str = "fake_agent",
    marker: str = "4",
) -> AgentProfile:
    return AgentProfile(
        profile_id=profile_id,
        profile_version="1.0.0",
        adapter=fake_pin(adapter_id, marker=marker),
        call_observability="full",
        execution_config=AgentExecutionConfig(
            provider=ProviderPin(provider_id="fake-provider", api_version="2026-08-01"),
            model=ModelPin(model_id=f"fake-model-{profile_id}", revision="2026-08-01"),
            harness=fake_implementation("minimal_chat", marker="7"),
            runtime=RuntimePin(
                implementation=fake_implementation("in_process", marker="8"),
                config={"isolation": "in_process"},
            ),
            prompt=f"You are the {profile_id} buyer.",
            prompt_sha256=content_sha256(f"You are the {profile_id} buyer."),
            sampling=SamplingPin(
                schema_id="generation_sampling",
                schema_version="1.0.0",
                content={"temperature": 0.0},
            ),
            tools=(),
            memory=MemoryPin(mode="none"),
            attempt_budget=AttemptBudget(
                timeout_seconds=1.0,
                output_token_limit=64,
            ),
            retry_policy=RetryPolicy(max_attempts=1),
        ),
    )


def fake_resolution_inputs() -> ResolutionInputs:
    family = FamilyManifest(
        family_id="fake_market",
        family_version="1.0.0",
        environment=fake_pin("fake_market", marker="1"),
        verifiers=(fake_pin("fake_verifier", marker="2"),),
        phase_graph=FakeEnvironment().phase_graph({}),
        roles=(
            RoleSpec(
                role_id="buyer",
                testable=True,
                trainable=True,
                controlled_profile_ids=(),
            ),
            RoleSpec(
                role_id="seller",
                testable=False,
                trainable=False,
                controlled_profile_ids=("counterpart",),
            ),
        ),
        measurements=(
            OptimizableOutcomeMeasurementSpec(
                estimand_id="buyer_utility",
                measurement_kind="optimizable_outcome",
                direction="maximize",
                primary_metric_id="buyer_utility",
                verifier_plugin_id="fake_verifier",
                verifier_semantics_id="realized_buyer_utility",
                verifier_semantics_version="1.0.0",
                objective_id="buyer_utility",
                objective_version="1.0.0",
                units="utility_points",
                feasible_set="offers permitted by fake_market/1.0.0",
                information_set="buyer-private observation",
                horizon="two offer rounds",
                opponent_condition="fixed counterpart/1.0.0",
                stochastic_expectation="expectation over declared rollout seeds",
                bound_status="lower_bound_only",
                reference_contracts={
                    "optimum_lower_bound": OptimizationReferenceContract(
                        kind="optimum_lower_bound",
                        objective_id="buyer_utility",
                        objective_version="1.0.0",
                        units="utility_points",
                        direction="maximize",
                        feasible_set="offers permitted by fake_market/1.0.0",
                        information_set="buyer-private observation",
                        horizon="two offer rounds",
                        opponent_condition="fixed counterpart/1.0.0",
                        proof_type="executable feasible witness",
                        implementation=fake_implementation(
                            "buyer_utility_lower_bound", marker="9"
                        ),
                        validity_domain="fake_market/1.0.0 dev split",
                    )
                },
            ),
        ),
        capabilities=CapabilityDeclaration(
            schedule_control="runner",
            observation_visibility="partial",
            call_observability="full",
            state_replay="deterministic",
            score_parity="component",
            privacy_enforcement="runner",
            trainability="per_seat",
        ),
        generator=fake_implementation("fake_generator", marker="a"),
        limits={"max_rounds": 2},
    )
    case = CaseManifest.from_content(
        case_id="case-b",
        family_id="fake_market",
        family_version="1.0.0",
        split="dev",
        world_seed=11,
        seats=(
            SeatSpec(seat_id="buyer-1", role_id="buyer"),
            SeatSpec(seat_id="seller-1", role_id="seller"),
        ),
        max_logical_actions=8,
        terminal_reasons=("deal", "deadline"),
        visibility_policy="private_offers/1.0",
        payload={"reserve": 3},
        provenance=CaseProvenance(
            source_kind="generated",
            generator_id="fake_generator",
            generator_version="1.0.0",
            review_status="curated",
        ),
    )
    suite = SuiteManifest(
        suite_id="fake_suite",
        suite_version="1.0.0",
        case_ids=("case-b",),
        blocks=(
            EvaluationBlock(
                block_id="candidate_vs_fixed",
                kind="fixed_counterpart",
                estimand_id="buyer_utility",
                subject_roles=("buyer",),
                controlled_profile_by_role={"seller": "counterpart"},
                repetitions=2,
                rollout_seeds=(7, 3),
            ),
        ),
        cluster_by_estimand={
            "buyer_utility": ClusterSpec(
                cluster_level="case_seed",
                identity_fields=("case_id", "world_seed"),
                paired_fields=("rollout_seed",),
                parent_field="generator_version",
                panel_mode="fixed_panel",
            )
        },
        missingness_policy="report_separately",
        aggregation_group_fields=("family_id", "subject_role"),
        cross_family_scalar="disabled",
    )
    candidate = fake_agent_profile("candidate")
    counterpart = fake_agent_profile("counterpart")
    run = RunSpec(
        run_id="paper-run",
        run_version="1.0.0",
        admission_profile="paper_primary",
        execution_backend=fake_pin("fake_backend", marker="3"),
        subject_profile_by_role={"buyer": "candidate"},
        execution_mode="local",
    )
    return ResolutionInputs(
        family=family,
        cases=(case,),
        suite=suite,
        agent_profiles=(candidate, counterpart),
        run_spec=run,
    )
