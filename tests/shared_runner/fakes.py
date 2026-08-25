"""Provider-free fixtures shared by shared-runner tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from aeread.sdk.v1 import (
    ActionBundle,
    ActionChannel,
    AgentContext,
    AgentRequest,
    AttemptBudget,
    CallAttemptStart,
    CallAttemptToken,
    CanonicalResponse,
    DecisionSlot,
    FamilyOutcome,
    LegalityResult,
    ObservationEnvelope,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    PluginManifest,
    ProviderCallFailure,
    ProviderCallResult,
    RetryPolicy,
    ScoreEnvelope,
    SealedEvidenceView,
    TerminalResult,
    TransitionResult,
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
    budget=AttemptBudget(timeout_seconds=1.0, output_token_limit=64),
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

    def outcome(
        self, case: object, terminal: TerminalResult
    ) -> FamilyOutcome:
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
        self, request: AgentRequest, *, attempts: object
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

    async def write(
        self, handle: object, path: str, data: bytes
    ) -> None:
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
