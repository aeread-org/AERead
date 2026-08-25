"""Immutable public records shared by AERead environments and the runner."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from .base import ImmutableMapping, JSONObject, StrictModel
from .errors import BundleValidationError


class PluginManifest(StrictModel):
    plugin_id: str
    plugin_version: str
    sdk_api: str


class PhaseSpec(StrictModel):
    phase_id: str
    actor_selector: str
    mode: Literal["single", "sequential", "simultaneous"]
    observation_schema_by_role: ImmutableMapping[str]
    action_schema_by_role: ImmutableMapping[str]
    max_logical_actions: int = Field(ge=1)
    invalid_action_policy: str
    next_phases: tuple[str, ...]


class PhaseGraph(StrictModel):
    initial_phase_id: str
    phases: tuple[PhaseSpec, ...]

    @model_validator(mode="after")
    def validate_graph(self) -> "PhaseGraph":
        phase_ids = [phase.phase_id for phase in self.phases]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("phase_id values must be unique")
        declared = set(phase_ids)
        if self.initial_phase_id not in declared:
            raise ValueError("initial_phase_id must name a declared phase")
        for phase in self.phases:
            undeclared = set(phase.next_phases) - declared
            if undeclared:
                raise ValueError(
                    f"phase {phase.phase_id!r} has undeclared next phases: "
                    f"{sorted(undeclared)!r}"
                )
        return self


class ActionChannel(StrictModel):
    channel_id: str
    recipient_seat_ids: tuple[str, ...]
    action_schema_ref: str
    min_actions: int = Field(default=1, ge=0)
    max_actions: int | None = Field(default=1, ge=0)

    @model_validator(mode="after")
    def validate_cardinality(self) -> "ActionChannel":
        if self.max_actions is not None and self.max_actions < self.min_actions:
            raise ValueError("max_actions must be greater than or equal to min_actions")
        if len(self.recipient_seat_ids) != len(set(self.recipient_seat_ids)):
            raise ValueError("recipient_seat_ids must be unique")
        return self


class DecisionSlot(StrictModel):
    slot_id: str
    seat_id: str
    channels: tuple[ActionChannel, ...]
    observation_schema_ref: str
    response_schema_ref: str
    order_key: str

    @model_validator(mode="after")
    def validate_channel_ids(self) -> "DecisionSlot":
        channel_ids = [channel.channel_id for channel in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("channel_id declarations must be unique within a slot")
        return self


class ActionEnvelope(StrictModel):
    action_id: str
    slot_id: str
    channel_id: str
    actor_seat_id: str
    sequence_index: int = Field(ge=0)
    payload: JSONObject


class ActionBundle(StrictModel):
    slot_id: str
    actions: tuple[ActionEnvelope, ...]

    @model_validator(mode="after")
    def validate_intrinsic_identity(self) -> "ActionBundle":
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action_id values must be unique within a bundle")

        sequence_indices = [action.sequence_index for action in self.actions]
        if len(sequence_indices) != len(set(sequence_indices)):
            raise ValueError("sequence_index values must be unique within a bundle")
        if any(
            current >= following
            for current, following in zip(sequence_indices, sequence_indices[1:])
        ):
            raise ValueError("sequence_index values must be strictly increasing")

        if any(action.slot_id != self.slot_id for action in self.actions):
            raise ValueError("every action slot_id must match the bundle slot_id")
        actor_ids = {action.actor_seat_id for action in self.actions}
        if len(actor_ids) > 1:
            raise ValueError("actor_seat_id must be consistent within a bundle")
        return self

    def validate_against(self, slot: DecisionSlot) -> "ActionBundle":
        """Validate slot identity, actor, channel membership, and cardinality."""

        if self.slot_id != slot.slot_id:
            raise BundleValidationError(
                f"bundle slot_id {self.slot_id!r} does not match {slot.slot_id!r}"
            )

        declared = {channel.channel_id: channel for channel in slot.channels}
        counts = {channel_id: 0 for channel_id in declared}
        for action in self.actions:
            if action.actor_seat_id != slot.seat_id:
                raise BundleValidationError(
                    f"action actor_seat_id {action.actor_seat_id!r} does not match "
                    f"slot seat_id {slot.seat_id!r}"
                )
            if action.channel_id not in declared:
                raise BundleValidationError(
                    f"action uses undeclared channel {action.channel_id!r}"
                )
            counts[action.channel_id] += 1

        for channel_id, channel in declared.items():
            count = counts[channel_id]
            if count < channel.min_actions:
                raise BundleValidationError(
                    f"channel {channel_id!r} requires at least "
                    f"{channel.min_actions} actions; got {count}"
                )
            if channel.max_actions is not None and count > channel.max_actions:
                raise BundleValidationError(
                    f"channel {channel_id!r} allows at most "
                    f"{channel.max_actions} actions; got {count}"
                )
        return self


def validate_action_bundle(
    bundle: ActionBundle, slot: DecisionSlot
) -> ActionBundle:
    """Validate an action bundle against the slot that authorized it."""

    return bundle.validate_against(slot)


class ObservationEnvelope(StrictModel):
    schema_ref: str
    slot_id: str
    visible_payload: JSONObject
    public_event_refs: tuple[str, ...]
    private_event_refs: tuple[str, ...]


class ArtifactRef(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str
    size_bytes: int = Field(ge=0)


class CanonicalResponse(StrictModel):
    content: str | None = None
    tool_calls: tuple[JSONObject, ...] = ()
    finish_reason: str | None = None
    usage: ImmutableMapping[int] = Field(default_factory=dict)
    raw_artifact_ref: ArtifactRef | None = None
    harness_trace_ref: ArtifactRef | None = None


class EventIdentity(StrictModel):
    run_plan_id: str
    cell_id: str
    episode_id: str
    episode_attempt_id: str


class EpisodeEvent(StrictModel):
    event_id: str
    sequence: int = Field(ge=0)
    event_type: str
    occurred_at: str
    identity: EventIdentity
    visibility: str
    payload: JSONObject
    prior_event_hash: str | None = None
    event_hash: str


class SealedEvidenceView(StrictModel):
    events: tuple[EpisodeEvent, ...]
    artifacts: tuple[ArtifactRef, ...]
    event_root_sha256: str
    artifact_root_sha256: str


class AgentContext(StrictModel):
    agent_profile_id: str
    seat_id: str
    provider: str
    model: str
    harness: str
    runtime: str
    metadata: JSONObject = Field(default_factory=dict)


class AttemptBudget(StrictModel):
    timeout_seconds: FiniteFloat = Field(gt=0)
    input_token_limit: int | None = Field(default=None, ge=1)
    output_token_limit: int = Field(ge=1)


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=1, ge=1)
    retryable_conditions: tuple[str, ...] = ()
    length_retry_output_tokens: int | None = Field(default=None, ge=1)


class AgentRequest(StrictModel):
    logical_action_id: str
    phase_id: str
    slot: DecisionSlot
    observation: ObservationEnvelope
    context: AgentContext
    budget: AttemptBudget


class CallAttemptStart(StrictModel):
    call_attempt_id: str
    logical_action_id: str
    ordinal: int = Field(ge=1)
    retry_reason: str | None = None
    request_sha256: str
    provider: str
    model: str
    timeout_seconds: FiniteFloat = Field(gt=0)
    input_token_limit: int | None = Field(default=None, ge=1)
    output_token_limit: int = Field(ge=1)


class CallAttemptToken(StrictModel):
    call_attempt_id: str


class ProviderCallResult(StrictModel):
    provider_request_id: str | None = None
    finish_reason: str | None = None
    empty: bool = False
    truncated: bool = False
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: FiniteFloat | None = Field(default=None, ge=0)
    cost_usd: FiniteFloat | None = Field(default=None, ge=0)
    raw_artifact_ref: ArtifactRef | None = None


class ProviderCallFailure(StrictModel):
    error_class: str
    message: str
    retryable: bool
    transport_status: int | None = None
    raw_artifact_ref: ArtifactRef | None = None


class ParseResult(StrictModel):
    status: Literal["ok", "malformed"]
    bundle: ActionBundle | None = None
    error_code: str | None = None
    message: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ParseResult":
        if self.status == "ok" and self.bundle is None:
            raise ValueError("an ok parse result requires a bundle")
        if self.status == "malformed" and self.bundle is not None:
            raise ValueError("a malformed parse result cannot contain a bundle")
        return self


class LegalityResult(StrictModel):
    status: Literal["legal", "illegal"]
    reasons: tuple[str, ...] = ()


class TransitionResult(StrictModel):
    state: JSONObject
    next_phase_id: str | None
    evidence: JSONObject = Field(default_factory=dict)


class TerminalResult(StrictModel):
    status: Literal["terminal"]
    reason: str
    final_state: JSONObject


class FamilyOutcome(StrictModel):
    terminal_reason: str
    payload: JSONObject
    utility_by_seat: ImmutableMapping[FiniteFloat] = Field(default_factory=dict)


class MetricValue(StrictModel):
    value: FiniteFloat
    unit: str | None = None
    metadata: JSONObject = Field(default_factory=dict)


class ImplementationRef(StrictModel):
    implementation_id: str
    version: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OptimizationBoundReference(StrictModel):
    kind: Literal["optimum_lower_bound", "optimum_upper_bound"]
    value: FiniteFloat
    objective_id: str
    objective_version: str
    units: str
    direction: Literal["maximize", "minimize"]
    feasible_set: str
    information_set: str
    horizon: str
    opponent_condition: str
    proof_type: str
    implementation: ImplementationRef
    validity_domain: str


class ComparisonBaselineReference(StrictModel):
    kind: Literal["comparison_baseline"]
    value: FiniteFloat
    comparison_id: str
    comparison_version: str
    units: str
    direction: Literal["maximize", "minimize"]
    provenance: JSONObject
    applicability: str
    implementation: ImplementationRef


class OutcomeSupportReference(StrictModel):
    kind: Literal["outcome_support_min", "outcome_support_max"]
    value: FiniteFloat
    objective_id: str
    objective_version: str
    units: str
    direction: Literal["maximize", "minimize"]
    proof_type: str
    applicability: str


ReferenceValue = Annotated[
    OptimizationBoundReference
    | ComparisonBaselineReference
    | OutcomeSupportReference,
    Field(discriminator="kind"),
]


class ValidityReport(StrictModel):
    status: Literal["valid", "invalid"]
    reasons: tuple[str, ...] = ()


class ScoreEnvelope(StrictModel):
    status: Literal["ok", "invalid_measurement"]
    measurement_kind: str
    direction: str
    bound_status: str | None
    primary: MetricValue | None
    metrics: ImmutableMapping[MetricValue]
    utility_by_seat: ImmutableMapping[FiniteFloat]
    capture_by_seat: ImmutableMapping[FiniteFloat]
    references: ImmutableMapping[ReferenceValue]
    outcome: JSONObject
    validity: ValidityReport
    scorer: ImplementationRef
    oracle: ImplementationRef | None
    evidence_refs: tuple[str, ...]


class EpisodeExecutionResult(StrictModel):
    status: Literal["ok", "invalid_measurement"]
    terminal: TerminalResult | None
    outcome: FamilyOutcome | None
    evidence: SealedEvidenceView
    failure_class: str | None = None
    failure_message: str | None = None


class EvaluationReceipt(StrictModel):
    status: Literal["ok", "invalid_measurement"]
    run_plan_id: str
    cell_id: str
    episode_id: str
    episode_attempt_id: str
    cluster_id: str
    run_plan_sha256: str
    case_sha256: str
    agent_config_sha256: str
    implementations: tuple[ImplementationRef, ...]
    evidence: SealedEvidenceView
    score: ScoreEnvelope | None
    failure_class: str | None = None
    failure_message: str | None = None
    inclusion_status: Literal["included", "excluded"]
    observability_limits: tuple[str, ...] = ()
    replay_level: Literal["deterministic", "score_only", "none"]
    trajectory_refs: ImmutableMapping[ArtifactRef] = Field(default_factory=dict)
    receipt_sha256: str | None = None
