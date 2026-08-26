"""Immutable public records shared by AERead environments and the runner."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import gcd
import re
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationInfo,
    model_validator,
)

from .base import (
    ImmutableMapping,
    JSONObject,
    SDKBool,
    SDKFloat,
    SDKInt,
    SDKStr,
    StrictModel,
    content_sha256,
)
from .errors import BundleValidationError, UntrustedPluginReference


_PLUGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
SHA256 = Annotated[SDKStr, Field(pattern=r"^[0-9a-f]{64}$")]

#: Identifiers that leave this repository — case, suite, block, and profile ids
#: end up in file names, dataset rows, and export formats. They are lower-case
#: `[a-z0-9_.-]`, use `__` to separate levels, and **must not contain a colon**.
#: rLLM composes an episode id as ``f"{task_id}:{rollout_idx}"`` and recovers the
#: task with ``id.split(":")[0]``, so a colon in a row id silently collapses
#: every training group into one; that is not a hypothetical, it happened.
_EXPORTABLE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_.-]*[a-z0-9])?$")

ExportableId = Annotated[SDKStr, Field(pattern=_EXPORTABLE_ID_PATTERN.pattern)]


def is_exportable_id(value: str) -> bool:
    """Whether an identifier is safe to put in a file name, row, or export."""

    return bool(_EXPORTABLE_ID_PATTERN.fullmatch(value))
RetryCondition = Literal["timeout", "rate_limit", "provider_5xx", "transport", "length"]
CallObservability = Literal["full", "logical_only", "opaque"]
ReferenceKind = Literal[
    "optimum_lower_bound",
    "optimum_upper_bound",
    "comparison_baseline",
    "outcome_support_min",
    "outcome_support_max",
]
BoundStatus = Literal[
    "exact_solved",
    "epsilon_solved",
    "bracketed",
    "lower_bound_only",
    "baseline_only",
    "descriptive_only",
]
_MUTABLE_VERSION_ALIASES = {"latest", "current", "default", "stable"}


def _require_exact_pin(label: str, value: str) -> None:
    if not value.strip() or value.strip().lower() in _MUTABLE_VERSION_ALIASES:
        raise ValueError(f"{label} must be an exact immutable pin")


class PluginManifest(StrictModel):
    plugin_id: SDKStr
    plugin_version: SDKStr
    sdk_api: Literal["aeread.sdk/v1"]


class PluginRef(StrictModel):
    """A non-executable, exact plugin registry reference."""

    plugin_id: SDKStr
    plugin_version: SDKStr

    @model_validator(mode="before")
    @classmethod
    def validate_trusted_reference(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise UntrustedPluginReference("plugin reference must be an object")
        plugin_id = value.get("plugin_id")
        plugin_version = value.get("plugin_version")
        if type(plugin_id) is not str or not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise UntrustedPluginReference(
                "plugin_id must be a stable non-executable registry ID"
            )
        if type(plugin_version) is not str or not _SEMVER_PATTERN.fullmatch(
            plugin_version
        ):
            raise UntrustedPluginReference(
                "plugin_version must be an exact semantic version"
            )
        return value


class PhaseSpec(StrictModel):
    phase_id: SDKStr
    actor_selector: SDKStr
    mode: Literal["single", "sequential", "simultaneous"]
    observation_schema_by_role: ImmutableMapping[SDKStr]
    action_schema_by_role: ImmutableMapping[SDKStr]
    max_logical_actions: SDKInt = Field(ge=1)
    invalid_action_policy: SDKStr
    next_phases: tuple[SDKStr, ...]


class PhaseGraph(StrictModel):
    initial_phase_id: SDKStr
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
    channel_id: SDKStr
    recipient_seat_ids: tuple[SDKStr, ...]
    action_schema_ref: SDKStr
    min_actions: SDKInt = Field(default=1, ge=0)
    max_actions: SDKInt | None = Field(default=1, ge=0)

    @model_validator(mode="after")
    def validate_cardinality(self) -> "ActionChannel":
        if self.max_actions is not None and self.max_actions < self.min_actions:
            raise ValueError("max_actions must be greater than or equal to min_actions")
        if len(self.recipient_seat_ids) != len(set(self.recipient_seat_ids)):
            raise ValueError("recipient_seat_ids must be unique")
        return self


class DecisionSlot(StrictModel):
    slot_id: SDKStr
    seat_id: SDKStr
    channels: tuple[ActionChannel, ...]
    observation_schema_ref: SDKStr
    response_schema_ref: SDKStr
    order_key: SDKStr

    @model_validator(mode="after")
    def validate_channel_ids(self) -> "DecisionSlot":
        channel_ids = [channel.channel_id for channel in self.channels]
        if len(channel_ids) != len(set(channel_ids)):
            raise ValueError("channel_id declarations must be unique within a slot")
        return self


class ActionEnvelope(StrictModel):
    action_id: SDKStr
    slot_id: SDKStr
    channel_id: SDKStr
    actor_seat_id: SDKStr
    sequence_index: SDKInt = Field(ge=0)
    payload: JSONObject


class ActionBundle(StrictModel):
    slot_id: SDKStr
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


def validate_action_bundle(bundle: ActionBundle, slot: DecisionSlot) -> ActionBundle:
    """Validate an action bundle against the slot that authorized it."""

    return bundle.validate_against(slot)


class ObservationEnvelope(StrictModel):
    schema_ref: SDKStr
    slot_id: SDKStr
    visible_payload: JSONObject
    public_event_refs: tuple[SDKStr, ...]
    private_event_refs: tuple[SDKStr, ...]


class ArtifactRef(StrictModel):
    sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: SDKStr = Field(min_length=1)
    size_bytes: SDKInt = Field(ge=0)


class CanonicalResponse(StrictModel):
    content: SDKStr | None = None
    tool_calls: tuple[JSONObject, ...] = ()
    finish_reason: SDKStr | None = None
    usage: ImmutableMapping[SDKInt] = Field(default_factory=dict)
    raw_artifact_ref: ArtifactRef | None = None
    harness_trace_ref: ArtifactRef | None = None


class EventIdentity(StrictModel):
    run_plan_id: SDKStr
    cell_id: SDKStr
    episode_id: SDKStr
    episode_attempt_id: SDKStr


class EpisodeEvent(StrictModel):
    event_id: SDKStr
    sequence: SDKInt = Field(ge=0)
    event_type: SDKStr
    occurred_at: SDKStr
    identity: EventIdentity
    visibility: SDKStr
    payload: JSONObject | None
    payload_visible: SDKBool = True
    payload_sha256: SHA256
    prior_event_hash: SHA256 | None = None
    event_hash: SHA256

    @model_validator(mode="after")
    def validate_event_projection(self) -> "EpisodeEvent":
        if self.visibility not in {"public", "evaluator_only"} and not re.fullmatch(
            r"seat:[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?",
            self.visibility,
        ):
            raise ValueError("visibility must be public, evaluator_only, or seat:<id>")
        try:
            parsed = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("occurred_at must be an RFC3339 timestamp") from exc
        if not self.occurred_at.endswith("Z") or parsed.utcoffset() is None:
            raise ValueError("occurred_at must be an RFC3339 UTC timestamp ending in Z")
        if self.payload_visible and self.payload is None:
            raise ValueError("a visible event must contain its payload")
        if not self.payload_visible and self.payload is not None:
            raise ValueError("a redacted event must not contain plaintext payload")
        if self.payload_visible and content_sha256(self.payload) != self.payload_sha256:
            raise ValueError("payload_sha256 does not match the visible payload")
        return self


class SealedEvidenceView(StrictModel):
    identity: EventIdentity
    evidence_store_id: SDKStr
    audience: SDKStr = "full"
    events: tuple[EpisodeEvent, ...]
    artifacts: tuple[ArtifactRef, ...]
    event_root_sha256: SHA256
    artifact_root_sha256: SHA256
    is_final: SDKBool = True

    @model_validator(mode="after")
    def validate_audience(self) -> "SealedEvidenceView":
        if not re.fullmatch(r"[0-9a-f]{32}", self.evidence_store_id):
            raise ValueError("evidence_store_id must be 32 lower-case hex")
        if self.audience not in {"full", "evaluator", "public"} and not re.fullmatch(
            r"seat:[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?",
            self.audience,
        ):
            raise ValueError("invalid evidence audience")
        artifact_keys = [
            (ref.sha256, ref.media_type, ref.size_bytes) for ref in self.artifacts
        ]
        if artifact_keys != sorted(set(artifact_keys)):
            raise ValueError(
                "evidence artifacts must be unique and canonically ordered"
            )
        for event in self.events:
            if event.identity != self.identity:
                raise ValueError("every evidence event must match the view identity")
            allowed = (
                self.audience in {"full", "evaluator"}
                or event.visibility == "public"
                or event.visibility == self.audience
            )
            if event.payload_visible != allowed:
                raise ValueError(
                    "event payload visibility does not match the evidence audience"
                )
        return self


class AgentContext(StrictModel):
    agent_profile_id: SDKStr
    seat_id: SDKStr
    provider: SDKStr
    model: SDKStr
    harness: SDKStr
    runtime: SDKStr
    metadata: JSONObject = Field(default_factory=dict)


class AttemptBudget(StrictModel):
    timeout_seconds: SDKFloat = Field(gt=0)
    input_token_limit: SDKInt | None = Field(default=None, ge=1)
    output_token_limit: SDKInt = Field(ge=1)


class RetryPolicy(StrictModel):
    max_attempts: SDKInt = Field(default=1, ge=1)
    retryable_conditions: tuple[RetryCondition, ...] = ()
    length_retry_output_tokens: SDKInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_retry_policy(self) -> "RetryPolicy":
        conditions = self.retryable_conditions
        if len(conditions) != len(set(conditions)):
            raise ValueError("retryable_conditions must be unique")
        if "length" not in conditions and self.length_retry_output_tokens is not None:
            raise ValueError("length retry budget requires the length condition")
        if self.max_attempts > 1 and not conditions:
            raise ValueError("multiple attempts require retryable_conditions")
        if conditions and self.max_attempts < 2:
            label = "length retry" if "length" in conditions else "retryable_conditions"
            raise ValueError(f"{label} requires max_attempts >= 2")
        if "length" in conditions and self.length_retry_output_tokens is None:
            raise ValueError("length retry requires length_retry_output_tokens")
        return self


class CallAttemptStart(StrictModel):
    call_attempt_id: SDKStr
    logical_action_id: SDKStr
    ordinal: SDKInt = Field(ge=1)
    retry_reason: SDKStr | None = None
    request_sha256: SDKStr
    provider: SDKStr
    model: SDKStr
    timeout_seconds: SDKFloat = Field(gt=0)
    input_token_limit: SDKInt | None = Field(default=None, ge=1)
    output_token_limit: SDKInt = Field(ge=1)


class CallAttemptToken(StrictModel):
    call_attempt_id: SDKStr


class ProviderCallResult(StrictModel):
    provider_request_id: SDKStr | None = None
    finish_reason: SDKStr | None = None
    empty: SDKBool = False
    truncated: SDKBool = False
    input_tokens: SDKInt | None = Field(default=None, ge=0)
    output_tokens: SDKInt | None = Field(default=None, ge=0)
    latency_ms: SDKFloat | None = Field(default=None, ge=0)
    cost_usd: SDKFloat | None = Field(default=None, ge=0)
    raw_artifact_ref: ArtifactRef | None = None


class ProviderCallFailure(StrictModel):
    error_class: SDKStr
    message: SDKStr
    retryable: SDKBool
    transport_status: SDKInt | None = None
    raw_artifact_ref: ArtifactRef | None = None


class ToolInvocationStart(StrictModel):
    """One atomic tool call, declared before it is executed.

    Repeated calls to the same tool are separate invocations, and several
    invocations inside one action attempt are not a retry: an agent that reads
    an order, then refunds it, made two invocations of one decision.

    ``effect`` is required because a read and a mutation are different events
    for a state-comparing verifier: replaying a trajectory must reproduce which
    calls could have changed the world.
    """

    invocation_id: SDKStr
    logical_action_id: SDKStr
    ordinal: SDKInt = Field(ge=1)
    tool_id: SDKStr
    tool_version: SDKStr | None = None
    effect: Literal["read_only", "mutating"]
    arguments_sha256: SHA256
    timeout_seconds: SDKFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_invocation_start(self) -> "ToolInvocationStart":
        if not self.invocation_id.strip() or not self.tool_id.strip():
            raise ValueError("invocation_id and tool_id must be non-empty")
        if not self.logical_action_id.strip():
            raise ValueError("a tool invocation must name its logical action")
        return self


class ToolInvocationToken(StrictModel):
    invocation_id: SDKStr


class ToolInvocationResult(StrictModel):
    result_sha256: SHA256 | None = None
    state_changed: SDKBool | None = None
    latency_ms: SDKFloat | None = Field(default=None, ge=0)
    raw_artifact_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_invocation_result(self) -> "ToolInvocationResult":
        if self.state_changed and self.result_sha256 is None:
            raise ValueError(
                "an invocation that changed state must record its result digest"
            )
        return self


class ToolInvocationFailure(StrictModel):
    """A tool that refused, or failed after it had already changed something.

    The partial mutation is the case that matters: a refund that times out
    after the debit posted is the canonical customer-service failure, and a
    verifier comparing final state has to be able to tell it from a refusal
    that changed nothing. So a failure that admits a state change carries the
    same evidence a success would.
    """

    error_class: SDKStr
    message: SDKStr
    retryable: SDKBool
    state_changed: SDKBool | None = None
    result_sha256: SHA256 | None = None
    raw_artifact_ref: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_invocation_failure(self) -> "ToolInvocationFailure":
        if not self.error_class.strip():
            raise ValueError("error_class must be non-empty")
        if self.state_changed and self.result_sha256 is None:
            raise ValueError(
                "a failure that changed state must record its result digest"
            )
        return self


class ParseResult(StrictModel):
    status: Literal["ok", "malformed"]
    bundle: ActionBundle | None = None
    error_code: SDKStr | None = None
    message: SDKStr | None = None
    diagnostics: JSONObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ParseResult":
        if self.status == "ok" and self.bundle is None:
            raise ValueError("an ok parse result requires a bundle")
        if self.status == "malformed" and self.bundle is not None:
            raise ValueError("a malformed parse result cannot contain a bundle")
        return self


class LegalityResult(StrictModel):
    status: Literal["legal", "illegal"]
    reasons: tuple[SDKStr, ...] = ()


class TransitionResult(StrictModel):
    state: JSONObject
    next_phase_id: SDKStr | None
    evidence: JSONObject = Field(default_factory=dict)


class TerminalResult(StrictModel):
    status: Literal["terminal"]
    reason: SDKStr
    final_state: JSONObject


class FamilyOutcome(StrictModel):
    terminal_reason: SDKStr
    payload: JSONObject
    utility_by_seat: ImmutableMapping[SDKFloat] = Field(default_factory=dict)


class MetricValue(StrictModel):
    value: SDKFloat
    unit: SDKStr | None = None
    metadata: JSONObject = Field(default_factory=dict)


class ImplementationRef(StrictModel):
    implementation_id: SDKStr
    version: SDKStr
    content_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")


def _validate_implementation_pin(implementation: ImplementationRef, label: str) -> None:
    if not implementation.implementation_id.strip():
        raise ValueError(f"{label} implementation_id must be non-empty")
    _require_exact_pin(f"{label} version", implementation.version)


# Incremental family-owned measurement leaf records. These are intentionally not wired
# into FamilyManifest until the atomic manifest migration.

EvaluationClass = Literal["deterministic", "stochastic_estimator", "judge_dependent"]
EstimandInputScope = Literal["answer", "terminal_state", "trajectory", "distribution"]


def _require_non_empty(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")


def _require_semver(label: str, value: str) -> None:
    if not _SEMVER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be an exact semantic version")


def _artifact_identity(reference: ArtifactRef) -> tuple[str, str, int]:
    return reference.sha256, reference.media_type, reference.size_bytes


def _validate_complete_artifact(reference: ArtifactRef, label: str) -> None:
    if not reference.media_type.strip():
        raise ValueError(f"{label} media_type must be non-empty")


def _validate_artifact_tuple(
    values: tuple[ArtifactRef, ...], label: str, *, required: bool
) -> None:
    if required and not values:
        raise ValueError(f"{label} must be non-empty")
    for index, value in enumerate(values):
        _validate_complete_artifact(value, f"{label}[{index}]")
    digests = [value.sha256 for value in values]
    if len(digests) != len(set(digests)):
        raise ValueError(f"{label} sha256 values must be unique")
    identities = [_artifact_identity(value) for value in values]
    if identities != sorted(identities):
        raise ValueError(f"{label} must be canonically ordered")


def _validate_direct_record_values(record: StrictModel, label: str) -> None:
    for field_name in type(record).model_fields:
        value = getattr(record, field_name)
        if type(value) is str:
            _require_non_empty(f"{label} {field_name}", value)
        elif isinstance(value, ImplementationRef):
            _validate_implementation_pin(value, f"{label} {field_name}")


def _validate_canonical_string_tuple(
    values: tuple[str, ...], label: str, *, required: bool
) -> None:
    if required and not values:
        raise ValueError(f"{label} must be non-empty")
    for index, value in enumerate(values):
        _require_non_empty(f"{label}[{index}]", value)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")
    if values != tuple(sorted(values)):
        raise ValueError(f"{label} must be canonically ordered")


class _PlannedIdentityRecord(StrictModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="wrap")
    @classmethod
    def reject_subclass_instances(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler["_PlannedIdentityRecord"],
    ) -> "_PlannedIdentityRecord":
        if isinstance(value, _PlannedIdentityRecord) and type(value) is not cls:
            raise ValueError(
                "planned identity records must use their exact concrete type"
            )
        return handler(value)


def _validate_planned_artifact(reference: ArtifactRef, label: str) -> None:
    if type(reference) is not ArtifactRef:
        raise ValueError(f"{label} must use the exact ArtifactRef type")
    _validate_complete_artifact(reference, label)


def _validate_planned_implementation(
    implementation: ImplementationRef, label: str
) -> None:
    if type(implementation) is not ImplementationRef:
        raise ValueError(f"{label} must use the exact ImplementationRef type")
    _validate_implementation_pin(implementation, label)


class SamplingPopulationSpec(_PlannedIdentityRecord):
    population_id: SDKStr
    population_version: SDKStr
    population_kind: Literal["finite_declared_frame"]
    unit_schema_ref: SDKStr
    unit_ids: tuple[SDKStr, ...]
    provenance_refs: tuple[ArtifactRef, ...] = ()
    frame_artifact_ref: ArtifactRef

    @model_validator(mode="after")
    def validate_population(self) -> "SamplingPopulationSpec":
        _require_non_empty("population_id", self.population_id)
        _require_semver("population_version", self.population_version)
        _require_non_empty("unit_schema_ref", self.unit_schema_ref)
        _validate_canonical_string_tuple(self.unit_ids, "unit_ids", required=True)
        for index, reference in enumerate(self.provenance_refs):
            _validate_planned_artifact(reference, f"provenance_refs[{index}]")
        _validate_artifact_tuple(
            self.provenance_refs, "provenance_refs", required=False
        )
        _validate_planned_artifact(self.frame_artifact_ref, "frame_artifact_ref")
        return self


class FixedPanelDesignSpec(_PlannedIdentityRecord):
    panel_kind: Literal["fixed_panel"]
    panel_design_id: SDKStr
    panel_design_version: SDKStr
    selected_unit_ids: tuple[SDKStr, ...]
    inference_scope: Literal["conditional_on_selected_panel"]

    @model_validator(mode="after")
    def validate_fixed_panel(self) -> "FixedPanelDesignSpec":
        _require_non_empty("panel_design_id", self.panel_design_id)
        _require_semver("panel_design_version", self.panel_design_version)
        _validate_canonical_string_tuple(
            self.selected_unit_ids, "selected_unit_ids", required=True
        )
        return self


class SampledPanelDesignSpec(_PlannedIdentityRecord):
    panel_kind: Literal["sampled_panel"]
    panel_design_id: SDKStr
    panel_design_version: SDKStr
    selection_algorithm: ImplementationRef
    sampling_method: Literal["simple_random_without_replacement"]
    selection_protocol_ref: ArtifactRef
    selection_seed: SDKInt = Field(ge=0)
    sample_size: SDKInt = Field(gt=0)
    replacement: Literal["without_replacement"]
    target_inference_scope: Literal[
        "declared_finite_population_under_probability_sampling"
    ]

    @model_validator(mode="after")
    def validate_sampled_panel(self) -> "SampledPanelDesignSpec":
        _require_non_empty("panel_design_id", self.panel_design_id)
        _require_semver("panel_design_version", self.panel_design_version)
        _validate_planned_implementation(
            self.selection_algorithm, "selection_algorithm"
        )
        _validate_planned_artifact(
            self.selection_protocol_ref, "selection_protocol_ref"
        )
        return self


PanelDesignSpec = Annotated[
    FixedPanelDesignSpec | SampledPanelDesignSpec,
    Field(discriminator="panel_kind"),
]


class ClusterMembershipSpec(_PlannedIdentityRecord):
    cluster_id: SDKStr
    population_unit_ids: tuple[SDKStr, ...]

    @model_validator(mode="after")
    def validate_membership(self) -> "ClusterMembershipSpec":
        _require_non_empty("cluster_id", self.cluster_id)
        _validate_canonical_string_tuple(
            self.population_unit_ids, "population_unit_ids", required=True
        )
        return self


class ClusterDesignSpec(_PlannedIdentityRecord):
    cluster_design_id: SDKStr
    cluster_design_version: SDKStr
    cluster_level: SDKStr
    memberships: tuple[ClusterMembershipSpec, ...]

    @model_validator(mode="after")
    def validate_cluster_design(self) -> "ClusterDesignSpec":
        _require_non_empty("cluster_design_id", self.cluster_design_id)
        _require_semver("cluster_design_version", self.cluster_design_version)
        _require_non_empty("cluster_level", self.cluster_level)
        if not self.memberships:
            raise ValueError("memberships must be non-empty")
        cluster_ids = tuple(item.cluster_id for item in self.memberships)
        _validate_canonical_string_tuple(cluster_ids, "cluster_ids", required=True)
        all_unit_ids = tuple(
            unit_id
            for membership in self.memberships
            for unit_id in membership.population_unit_ids
        )
        if len(all_unit_ids) != len(set(all_unit_ids)):
            raise ValueError("population units cannot belong to multiple clusters")
        return self


PlannedCoordinateField = Literal[
    "population_unit_id",
    "case_id",
    "repetition_index",
    "rollout_seed",
    "world_seed",
]


class PairingSpec(_PlannedIdentityRecord):
    pairing_id: SDKStr
    pairing_version: SDKStr
    pairing_kind: Literal["paired", "unpaired"]
    subject_block_id: SDKStr
    comparator_block_id: SDKStr
    pair_key_fields: tuple[PlannedCoordinateField, ...] = ()

    @model_validator(mode="after")
    def validate_pairing(self) -> "PairingSpec":
        _require_non_empty("pairing_id", self.pairing_id)
        _require_semver("pairing_version", self.pairing_version)
        _require_non_empty("subject_block_id", self.subject_block_id)
        _require_non_empty("comparator_block_id", self.comparator_block_id)
        if self.subject_block_id == self.comparator_block_id:
            raise ValueError("pairing block IDs must be distinct")
        _validate_canonical_string_tuple(
            self.pair_key_fields,
            "pair_key_fields",
            required=self.pairing_kind == "paired",
        )
        if self.pairing_kind == "unpaired" and self.pair_key_fields:
            raise ValueError("unpaired designs cannot declare pair_key_fields")
        return self


class SeededEpisodeReplicationDesign(_PlannedIdentityRecord):
    replication_mode: Literal["seeded"]
    replication_id: SDKStr
    replication_version: SDKStr
    repetition_count: SDKInt = Field(gt=0)
    rollout_seeds: tuple[Annotated[SDKInt, Field(ge=0)], ...]
    replicate_identity: Literal["repetition_index_and_rollout_seed"]
    replay_seed_guarantee: Literal["declared_seed_control"]

    @model_validator(mode="after")
    def validate_seeded_replication(self) -> "SeededEpisodeReplicationDesign":
        _require_non_empty("replication_id", self.replication_id)
        _require_semver("replication_version", self.replication_version)
        if len(self.rollout_seeds) != self.repetition_count:
            raise ValueError("rollout_seeds length must equal repetition_count")
        return self


class UnseededEpisodeReplicationDesign(_PlannedIdentityRecord):
    replication_mode: Literal["upstream_unseeded"]
    replication_id: SDKStr
    replication_version: SDKStr
    repetition_count: SDKInt = Field(gt=0)
    replicate_identity: Literal["repetition_index"]
    replay_seed_guarantee: Literal["none"]

    @model_validator(mode="after")
    def validate_unseeded_replication(self) -> "UnseededEpisodeReplicationDesign":
        _require_non_empty("replication_id", self.replication_id)
        _require_semver("replication_version", self.replication_version)
        return self


EpisodeReplicationDesign = Annotated[
    SeededEpisodeReplicationDesign | UnseededEpisodeReplicationDesign,
    Field(discriminator="replication_mode"),
]


class NoJudgeEvaluationInstrumentSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.evaluation_instrument/0.1"]
    record_type: Literal["evaluation_instrument"]
    instrument_kind: Literal["not_required"]


class JudgeEvaluationInstrumentSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.evaluation_instrument/0.1"]
    record_type: Literal["evaluation_instrument"]
    instrument_kind: Literal["judge_score"]
    instrument_id: SDKStr
    instrument_version: SDKStr
    aggregation: ImplementationRef
    aggregation_input: Literal["one_accepted_terminal_result_per_planned_judgment_slot"]
    slot_coverage_rule: Literal["exact_planned_terminal_slots"]
    minimum_valid_slots: SDKInt = Field(ge=1)
    missing_slot_rule: Literal["invalid_measurement"]
    duplicate_slot_rule: Literal["reject"]
    invalid_result_rule: Literal["invalid_measurement"]
    tie_rule: Literal["preserve_valid_categorical_tie"]
    disagreement_preservation_rule: Literal[
        "preserve_all_planned_slot_terminal_result_refs_and_dispositions"
    ]
    aggregate_result_schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_judge_instrument(self) -> "JudgeEvaluationInstrumentSpec":
        _require_non_empty("instrument_id", self.instrument_id)
        _require_semver("instrument_version", self.instrument_version)
        _validate_planned_implementation(self.aggregation, "aggregation")
        _require_non_empty(
            "aggregate_result_schema_ref", self.aggregate_result_schema_ref
        )
        return self


EvaluationInstrumentSpec = Annotated[
    NoJudgeEvaluationInstrumentSpec | JudgeEvaluationInstrumentSpec,
    Field(discriminator="instrument_kind"),
]


class MeasurementSelectionSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.measurement_selection/0.1"]
    record_type: Literal["measurement_selection"]
    selection_id: SDKStr
    selection_version: SDKStr
    leaf_id: SDKStr
    leaf_version: SDKStr
    leaf_sha256: SHA256
    selected_evaluation_class: EvaluationClass
    evaluation_instrument: EvaluationInstrumentSpec

    @model_validator(mode="after")
    def validate_selection(self) -> "MeasurementSelectionSpec":
        _require_non_empty("selection_id", self.selection_id)
        _require_semver("selection_version", self.selection_version)
        _require_non_empty("leaf_id", self.leaf_id)
        _require_semver("leaf_version", self.leaf_version)
        instrument = self.evaluation_instrument
        expected_type = (
            JudgeEvaluationInstrumentSpec
            if self.selected_evaluation_class == "judge_dependent"
            else NoJudgeEvaluationInstrumentSpec
        )
        if type(instrument) is not expected_type:
            raise ValueError(
                "selected evaluation class requires its exact evaluation instrument"
            )
        return self


class ExecutionRecordRef(_PlannedIdentityRecord):
    spec_version: Literal["aeread.execution_record_ref/0.1"]
    record_type: Literal["execution_record_ref"]
    ref_kind: Literal[
        "sampling_population",
        "panel_design",
        "episode_replication_design",
        "measurement_selection",
        "agent_profile",
    ]
    record_id: SDKStr
    record_version: SDKStr
    content_sha256: SHA256

    @model_validator(mode="after")
    def validate_execution_record_ref(self) -> "ExecutionRecordRef":
        _require_non_empty("record_id", self.record_id)
        _require_semver("record_version", self.record_version)
        return self


def _validate_execution_record_ref(
    reference: ExecutionRecordRef, label: str, expected_kind: str
) -> None:
    if type(reference) is not ExecutionRecordRef:
        raise ValueError(f"{label} must use the exact ExecutionRecordRef type")
    if reference.ref_kind != expected_kind:
        raise ValueError(f"{label} must have ref_kind {expected_kind!r}")


class FixedPanelResolutionTemplateSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.panel_resolution_template/0.1"]
    record_type: Literal["panel_resolution_template"]
    resolution_kind: Literal["fixed_panel"]
    panel_ref: ExecutionRecordRef
    realization_key: SDKStr
    realization_coupling: Literal["fixed_exact"]
    resolution_source: Literal["selected_unit_ids_from_pinned_fixed_panel"]
    resolution_timing: Literal["before_first_episode_side_effect"]
    failure_rule: Literal["admission_failure_no_retry"]

    @model_validator(mode="after")
    def validate_fixed_panel_resolution(
        self,
    ) -> "FixedPanelResolutionTemplateSpec":
        _validate_execution_record_ref(self.panel_ref, "panel_ref", "panel_design")
        _require_non_empty("realization_key", self.realization_key)
        return self


class SampledPanelResolutionTemplateSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.panel_resolution_template/0.1"]
    record_type: Literal["panel_resolution_template"]
    resolution_kind: Literal["sampled_panel"]
    panel_ref: ExecutionRecordRef
    realization_key: SDKStr
    realization_coupling: Literal["shared_exact_key", "independent_rng_domain"]
    rng_domain: SDKStr | None
    rng_domain_rule: Literal["not_applicable", "sha256_uint64_be_v1"]
    realization_source: Literal[
        "execute_pinned_design", "import_predeclared_realization_artifact"
    ]
    imported_realization_ref: ArtifactRef | None
    imported_realization_schema: Literal["aeread.sampled_panel_realization/0.1"] | None
    import_validator: ImplementationRef | None
    resolution_timing: Literal["before_first_episode_side_effect"]
    failure_rule: Literal["admission_failure_no_retry"]
    realization_binding_rule: Literal[
        "bind_frame_design_algorithm_protocol_selected_ids_and_provenance"
    ]
    publication_rule: Literal["atomic_idempotent_same_key_same_bytes"]

    @model_validator(mode="after")
    def validate_sampled_panel_resolution(
        self,
    ) -> "SampledPanelResolutionTemplateSpec":
        _validate_execution_record_ref(self.panel_ref, "panel_ref", "panel_design")
        _require_non_empty("realization_key", self.realization_key)
        if self.realization_coupling == "shared_exact_key":
            if self.rng_domain is not None or self.rng_domain_rule != "not_applicable":
                raise ValueError(
                    "shared_exact_key coupling requires rng_domain=None and "
                    "rng_domain_rule='not_applicable'"
                )
        else:
            if self.rng_domain is None:
                raise ValueError(
                    "independent_rng_domain coupling requires a nonblank rng_domain"
                )
            _require_non_empty("rng_domain", self.rng_domain)
            if self.rng_domain_rule != "sha256_uint64_be_v1":
                raise ValueError(
                    "independent_rng_domain coupling requires "
                    "rng_domain_rule='sha256_uint64_be_v1'"
                )

        imported_realization_ref = self.imported_realization_ref
        import_validator = self.import_validator
        import_fields = (
            imported_realization_ref,
            self.imported_realization_schema,
            import_validator,
        )
        if self.realization_source == "execute_pinned_design":
            if any(value is not None for value in import_fields):
                raise ValueError(
                    "execute_pinned_design requires all import fields to be None"
                )
        else:
            if (
                imported_realization_ref is None
                or self.imported_realization_schema is None
                or import_validator is None
            ):
                raise ValueError(
                    "import_predeclared_realization_artifact requires all import fields"
                )
            _validate_planned_artifact(
                imported_realization_ref, "imported_realization_ref"
            )
            _validate_planned_implementation(import_validator, "import_validator")
        return self


PanelResolutionTemplateSpec = Annotated[
    FixedPanelResolutionTemplateSpec | SampledPanelResolutionTemplateSpec,
    Field(discriminator="resolution_kind"),
]


class ExecutionBlockSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.execution_block/0.1"]
    record_type: Literal["execution_block"]
    block_id: SDKStr
    block_version: SDKStr
    measurement_selection_ref: ExecutionRecordRef
    role_ids: tuple[SDKStr, ...]
    subject_roles: tuple[SDKStr, ...]
    profile_ref_by_role: ImmutableMapping[ExecutionRecordRef]
    planned_coordinate_fields: tuple[PlannedCoordinateField, ...]
    judgment_template_id: SDKStr | None

    @model_validator(mode="after")
    def validate_execution_block(self) -> "ExecutionBlockSpec":
        _require_non_empty("block_id", self.block_id)
        _require_semver("block_version", self.block_version)
        _validate_execution_record_ref(
            self.measurement_selection_ref,
            "measurement_selection_ref",
            "measurement_selection",
        )
        _validate_canonical_string_tuple(self.role_ids, "role_ids", required=True)
        _validate_canonical_string_tuple(
            self.subject_roles, "subject_roles", required=True
        )
        if not set(self.subject_roles) <= set(self.role_ids):
            raise ValueError("subject_roles must be a subset of role_ids")
        if set(self.profile_ref_by_role) != set(self.role_ids):
            raise ValueError("profile_ref_by_role keys must exactly equal role_ids")
        for role_id, reference in self.profile_ref_by_role.items():
            _validate_execution_record_ref(
                reference, f"profile_ref_by_role[{role_id!r}]", "agent_profile"
            )
        unseeded = (
            "population_unit_id",
            "case_id",
            "repetition_index",
            "world_seed",
        )
        seeded = (
            "population_unit_id",
            "case_id",
            "repetition_index",
            "rollout_seed",
            "world_seed",
        )
        if self.planned_coordinate_fields not in (unseeded, seeded):
            raise ValueError(
                "planned_coordinate_fields must equal one exact declared coordinate tuple"
            )
        if self.judgment_template_id is not None:
            _require_non_empty("judgment_template_id", self.judgment_template_id)
        return self


def _validate_judgment_template_identity(
    template_id: str, template_version: str, local_slot_keys: tuple[str, ...]
) -> None:
    _require_non_empty("template_id", template_id)
    _require_semver("template_version", template_version)
    _validate_canonical_string_tuple(local_slot_keys, "local_slot_keys", required=True)


class EvaluatorAgentJudgmentTemplateSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.judgment_work_template/0.1"]
    record_type: Literal["judgment_work_template"]
    judgment_source_kind: Literal["evaluator_agent"]
    template_id: SDKStr
    template_version: SDKStr
    local_slot_keys: tuple[SDKStr, ...]
    primary_profile_ref_by_slot: ImmutableMapping[ExecutionRecordRef]
    replacement_rule: Literal["none", "predeclared_outcome_blind_successor_profiles"]
    replacement_profile_refs_by_slot: ImmutableMapping[tuple[ExecutionRecordRef, ...]]
    replacement_eligibility: ImplementationRef | None
    replacement_eligibility_input_rule: Literal[
        "not_applicable",
        "typed_operational_failure_without_accepted_terminal_result_only",
    ]
    assignment_rule: Literal["exact_predeclared_profile_per_local_slot"]
    lease_subject_template: Literal[
        "run_plan_cell_measurement_judgment_slot_and_profile"
    ]
    materialization_timing: Literal[
        "after_economic_outcome_before_final_episode_evidence_seal"
    ]

    @model_validator(mode="after")
    def validate_evaluator_agent_template(
        self,
    ) -> "EvaluatorAgentJudgmentTemplateSpec":
        _validate_judgment_template_identity(
            self.template_id, self.template_version, self.local_slot_keys
        )
        expected_slots = set(self.local_slot_keys)
        if set(self.primary_profile_ref_by_slot) != expected_slots:
            raise ValueError(
                "primary_profile_ref_by_slot keys must exactly equal local_slot_keys"
            )
        if set(self.replacement_profile_refs_by_slot) != expected_slots:
            raise ValueError(
                "replacement_profile_refs_by_slot keys must exactly equal "
                "local_slot_keys"
            )
        has_successor = False
        for slot_key in self.local_slot_keys:
            primary = self.primary_profile_ref_by_slot[slot_key]
            _validate_execution_record_ref(
                primary,
                f"primary_profile_ref_by_slot[{slot_key!r}]",
                "agent_profile",
            )
            successors = self.replacement_profile_refs_by_slot[slot_key]
            identities: list[str] = []
            for index, successor in enumerate(successors):
                _validate_execution_record_ref(
                    successor,
                    f"replacement_profile_refs_by_slot[{slot_key!r}][{index}]",
                    "agent_profile",
                )
                if successor == primary:
                    raise ValueError(
                        "replacement chain cannot contain its primary profile"
                    )
                identities.append(successor.model_dump_json())
            if len(identities) != len(set(identities)):
                raise ValueError("replacement chain cannot contain duplicate profiles")
            has_successor = has_successor or bool(successors)

        if self.replacement_rule == "none":
            if has_successor:
                raise ValueError("replacement_rule='none' requires empty chains")
            if self.replacement_eligibility is not None:
                raise ValueError(
                    "replacement_eligibility must be None when replacement is disabled"
                )
            if self.replacement_eligibility_input_rule != "not_applicable":
                raise ValueError(
                    "replacement_eligibility_input_rule must be 'not_applicable' "
                    "when replacement is disabled"
                )
        else:
            if not has_successor:
                raise ValueError(
                    "predeclared replacement requires at least one replacement profile"
                )
            if self.replacement_eligibility is None:
                raise ValueError(
                    "predeclared replacement requires replacement_eligibility"
                )
            _validate_planned_implementation(
                self.replacement_eligibility, "replacement_eligibility"
            )
            if (
                self.replacement_eligibility_input_rule
                != "typed_operational_failure_without_accepted_terminal_result_only"
            ):
                raise ValueError(
                    "predeclared replacement requires the typed operational failure "
                    "replacement_eligibility_input_rule"
                )
        return self


class ImportedHumanJudgmentTemplateSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.judgment_work_template/0.1"]
    record_type: Literal["judgment_work_template"]
    judgment_source_kind: Literal["imported_human"]
    template_id: SDKStr
    template_version: SDKStr
    local_slot_keys: tuple[SDKStr, ...]
    source_binding_rule: Literal[
        "exact_resolved_rater_source_in_canonical_local_slot_order"
    ]
    assignment_rule: Literal["predeclared_import_slot_order"]
    lease_subject_template: Literal["none"]
    materialization_timing: Literal[
        "after_economic_outcome_before_final_episode_evidence_seal"
    ]

    @model_validator(mode="after")
    def validate_imported_human_template(
        self,
    ) -> "ImportedHumanJudgmentTemplateSpec":
        _validate_judgment_template_identity(
            self.template_id, self.template_version, self.local_slot_keys
        )
        return self


JudgmentWorkTemplateSpec = Annotated[
    EvaluatorAgentJudgmentTemplateSpec | ImportedHumanJudgmentTemplateSpec,
    Field(discriminator="judgment_source_kind"),
]


class EpisodeTerminalDispositionRule(_PlannedIdentityRecord):
    spec_version: Literal["aeread.episode_terminal_disposition_rule/0.1"]
    record_type: Literal["episode_terminal_disposition_rule"]
    terminal_class: Literal[
        "preflight_rejected",
        "predeclared_population_ineligible",
        "execution_not_started",
        "isolated_cow_failed_no_publish",
        "idempotent_same_operation_proven_not_committed",
        "transition_outcome_unknown",
        "committed_valid_economic_outcome",
        "committed_outcome_measurement_failed",
        "run_cancelled_proven_no_commit",
        "run_cancelled_commit_unknown",
    ]
    disposition: Literal[
        "close_run_control_failure",
        "typed_zero_attempt_exclusion",
        "successor_if_policy_allows",
        "successor_same_operation_if_policy_allows",
        "quarantine",
        "close_valid",
        "close_invalid_without_economic_rerun",
        "close_invalid",
    ]

    @model_validator(mode="after")
    def validate_terminal_disposition(self) -> "EpisodeTerminalDispositionRule":
        expected = dict(_EPISODE_TERMINAL_DISPOSITION_TABLE)[self.terminal_class]
        if self.disposition != expected:
            raise ValueError(
                f"terminal_class {self.terminal_class!r} requires disposition "
                f"{expected!r}"
            )
        return self


_EPISODE_TERMINAL_DISPOSITION_TABLE = (
    ("preflight_rejected", "close_run_control_failure"),
    ("predeclared_population_ineligible", "typed_zero_attempt_exclusion"),
    ("execution_not_started", "successor_if_policy_allows"),
    ("isolated_cow_failed_no_publish", "successor_if_policy_allows"),
    (
        "idempotent_same_operation_proven_not_committed",
        "successor_same_operation_if_policy_allows",
    ),
    ("transition_outcome_unknown", "quarantine"),
    ("committed_valid_economic_outcome", "close_valid"),
    (
        "committed_outcome_measurement_failed",
        "close_invalid_without_economic_rerun",
    ),
    ("run_cancelled_proven_no_commit", "close_invalid"),
    ("run_cancelled_commit_unknown", "quarantine"),
)


class EpisodeAttemptPolicySpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.episode_attempt_policy/0.1"]
    record_type: Literal["episode_attempt_policy"]
    policy_id: SDKStr
    policy_version: SDKStr
    max_episode_attempts: SDKInt = Field(ge=1)
    terminal_rules: tuple[EpisodeTerminalDispositionRule, ...]
    successor_eligibility: ImplementationRef
    population_eligibility: ImplementationRef
    successor_eligibility_input_rule: Literal[
        "preoutcome_plan_and_typed_terminal_evidence_only"
    ]
    population_eligibility_input_rule: Literal[
        "preoutcome_population_frame_and_unit_only"
    ]
    unknown_transition_rule: Literal["quarantine_without_successor"]
    economic_outcome_rerun_rule: Literal["never_rerun_committed_economic_outcome"]
    cancellation_proof_rule: Literal[
        "typed_proven_no_commit_or_typed_commit_unknown_only"
    ]
    first_attempt_estimand_rule: Literal["preserve_first_attempt_separately"]
    policy_assisted_estimand_rule: Literal[
        "report_policy_assisted_final_without_overwriting_first_attempt"
    ]

    @model_validator(mode="after")
    def validate_episode_attempt_policy(self) -> "EpisodeAttemptPolicySpec":
        _require_non_empty("policy_id", self.policy_id)
        _require_semver("policy_version", self.policy_version)
        actual_table = tuple(
            (rule.terminal_class, rule.disposition) for rule in self.terminal_rules
        )
        if actual_table != _EPISODE_TERMINAL_DISPOSITION_TABLE:
            raise ValueError(
                "terminal_rules must contain the exact canonical ten-row table"
            )
        _validate_planned_implementation(
            self.successor_eligibility, "successor_eligibility"
        )
        _validate_planned_implementation(
            self.population_eligibility, "population_eligibility"
        )
        return self


class ExecutionDesignSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.execution_design/0.1"]
    record_type: Literal["execution_design"]
    execution_design_id: SDKStr
    execution_design_version: SDKStr
    population_ref: ExecutionRecordRef
    panel_resolution: PanelResolutionTemplateSpec
    replication_ref: ExecutionRecordRef
    blocks: tuple[ExecutionBlockSpec, ...]
    judgment_templates: tuple[JudgmentWorkTemplateSpec, ...]
    episode_attempt_policy: EpisodeAttemptPolicySpec
    cell_expansion_rule: Literal[
        "resolve_exact_population_panel_replication_block_seat_coordinate_product"
    ]
    execution_hash_domain: Literal["aeread.execution_design/1"]

    @model_validator(mode="after")
    def validate_execution_design(self) -> "ExecutionDesignSpec":
        _require_non_empty("execution_design_id", self.execution_design_id)
        _require_semver("execution_design_version", self.execution_design_version)
        _validate_execution_record_ref(
            self.population_ref, "population_ref", "sampling_population"
        )
        _validate_execution_record_ref(
            self.replication_ref,
            "replication_ref",
            "episode_replication_design",
        )
        if not self.blocks:
            raise ValueError("blocks must be non-empty")
        block_ids = tuple(block.block_id for block in self.blocks)
        _validate_canonical_string_tuple(block_ids, "blocks", required=True)
        template_ids = tuple(
            template.template_id for template in self.judgment_templates
        )
        _validate_canonical_string_tuple(
            template_ids, "judgment_templates", required=False
        )
        referenced_template_ids = {
            block.judgment_template_id
            for block in self.blocks
            if block.judgment_template_id is not None
        }
        if referenced_template_ids != set(template_ids):
            raise ValueError(
                "judgment_template references must exactly cover declared templates"
            )
        return self


class AssignmentAuthoringRecordRef(_PlannedIdentityRecord):
    spec_version: Literal["aeread.assignment_authoring_record_ref/0.1"]
    record_type: Literal["assignment_authoring_record_ref"]
    ref_kind: Literal["execution_design", "pairing_design", "exchangeability_domain"]
    record_id: SDKStr
    record_version: SDKStr
    content_sha256: SHA256

    @model_validator(mode="after")
    def validate_assignment_authoring_record_ref(
        self,
    ) -> "AssignmentAuthoringRecordRef":
        _require_non_empty("record_id", self.record_id)
        _require_semver("record_version", self.record_version)
        return self


def _validate_assignment_artifact(reference: ArtifactRef, label: str) -> None:
    if type(reference) is not ArtifactRef:
        raise ValueError(f"{label} must use the exact ArtifactRef type")
    ArtifactRef.model_validate(reference.model_dump(mode="python"))
    _validate_complete_artifact(reference, label)


def _validate_assignment_implementation(
    implementation: ImplementationRef, label: str
) -> None:
    if type(implementation) is not ImplementationRef:
        raise ValueError(f"{label} must use the exact ImplementationRef type")
    ImplementationRef.model_validate(implementation.model_dump(mode="python"))
    _validate_implementation_pin(implementation, label)


def _validate_distinct_content_sha256(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must use distinct content SHA-256 values")


def _validate_assignment_record_ref(
    reference: AssignmentAuthoringRecordRef,
    label: str,
    expected_kind: str,
) -> None:
    if type(reference) is not AssignmentAuthoringRecordRef:
        raise ValueError(
            f"{label} must use the exact AssignmentAuthoringRecordRef type"
        )
    AssignmentAuthoringRecordRef.model_validate(reference.model_dump(mode="python"))
    if reference.ref_kind != expected_kind:
        raise ValueError(f"{label} must have ref_kind {expected_kind!r}")


class ExchangeabilityDomainSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.exchangeability_domain/0.1"]
    record_type: Literal["exchangeability_domain"]
    domain_id: SDKStr
    domain_version: SDKStr
    domain_artifact_ref: ArtifactRef
    canonical_schema_ref: ArtifactRef
    validator: ImplementationRef
    allocation_unit: Literal["preassignment_pair"]
    eligible_pair_key_rule: Literal["exact_preassignment_pair_set_keys"]
    arm_binding_rule: Literal["exact_declared_subject_and_comparator_execution_blocks"]
    exclusion_rule: Literal["predeclared_only_no_post_assignment_or_outcome_exclusion"]
    supported_null: Literal[
        "sharp_no_unit_level_effect_under_declared_within_pair_allocation"
    ]
    assumption_status: Literal[
        "preregistered_scientific_assumption_not_empirically_proven_by_schema"
    ]

    @model_validator(mode="after")
    def validate_exchangeability_domain(self) -> "ExchangeabilityDomainSpec":
        _require_non_empty("domain_id", self.domain_id)
        _require_semver("domain_version", self.domain_version)
        _validate_assignment_artifact(self.domain_artifact_ref, "domain_artifact_ref")
        _validate_assignment_artifact(self.canonical_schema_ref, "canonical_schema_ref")
        _validate_assignment_implementation(self.validator, "validator")
        _validate_distinct_content_sha256(
            (
                self.domain_artifact_ref.sha256,
                self.canonical_schema_ref.sha256,
                self.validator.content_sha256,
            ),
            "exchangeability domain pins",
        )
        return self


class ExecuteUniformWithinPairAssignmentSourceSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.execution_assignment_source/0.1"]
    record_type: Literal["execution_assignment_source"]
    source_kind: Literal["execute_pinned"]
    algorithm: ImplementationRef
    protocol_ref: ArtifactRef
    selection_seed: SDKInt = Field(ge=0)
    seed_provenance_ref: ArtifactRef
    seed_provenance_schema_ref: ArtifactRef
    seed_provenance_validator: ImplementationRef
    seed_generation_rule: Literal[
        "uniform_integer_over_exact_n_pair_assignment_vectors_committed_preassignment"
    ]
    rng_domain: Literal["aeread.independent_uniform_within_pair_assignment/0.1"]
    bit_rule: Literal["n_low_order_seed_bits_in_canonical_pair_order"]
    determinism_rule: Literal[
        "same_claimed_inputs_reproduce_identical_canonical_realization_bytes"
    ]

    @model_validator(mode="after")
    def validate_execute_assignment_source(
        self,
    ) -> "ExecuteUniformWithinPairAssignmentSourceSpec":
        _validate_assignment_implementation(self.algorithm, "algorithm")
        _validate_assignment_artifact(self.protocol_ref, "protocol_ref")
        _validate_assignment_artifact(self.seed_provenance_ref, "seed_provenance_ref")
        _validate_assignment_artifact(
            self.seed_provenance_schema_ref, "seed_provenance_schema_ref"
        )
        _validate_assignment_implementation(
            self.seed_provenance_validator, "seed_provenance_validator"
        )
        _validate_distinct_content_sha256(
            (
                self.protocol_ref.sha256,
                self.seed_provenance_ref.sha256,
                self.seed_provenance_schema_ref.sha256,
            ),
            "execute assignment artifact pins",
        )
        return self


class ImportedUniformWithinPairAssignmentSourceSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.execution_assignment_source/0.1"]
    record_type: Literal["execution_assignment_source"]
    source_kind: Literal["import_predeclared"]
    realization_artifact_ref: ArtifactRef
    canonical_schema_ref: ArtifactRef
    validator: ImplementationRef
    generation_protocol_ref: ArtifactRef
    randomization_provenance_ref: ArtifactRef
    randomization_provenance_schema_ref: ArtifactRef
    randomization_provenance_validator: ImplementationRef
    assignment_law: Literal[
        "independent_uniform_one_half_allocation_for_each_exact_preassignment_pair"
    ]
    registration_rule: Literal[
        "content_pinned_before_plan_cell_publication_and_first_side_effect"
    ]

    @model_validator(mode="after")
    def validate_imported_assignment_source(
        self,
    ) -> "ImportedUniformWithinPairAssignmentSourceSpec":
        artifacts = (
            (self.realization_artifact_ref, "realization_artifact_ref"),
            (self.canonical_schema_ref, "canonical_schema_ref"),
            (self.generation_protocol_ref, "generation_protocol_ref"),
            (self.randomization_provenance_ref, "randomization_provenance_ref"),
            (
                self.randomization_provenance_schema_ref,
                "randomization_provenance_schema_ref",
            ),
        )
        for reference, label in artifacts:
            _validate_assignment_artifact(reference, label)
        _validate_assignment_implementation(self.validator, "validator")
        _validate_assignment_implementation(
            self.randomization_provenance_validator,
            "randomization_provenance_validator",
        )
        _validate_distinct_content_sha256(
            tuple(reference.sha256 for reference, _ in artifacts),
            "imported assignment artifact pins",
        )
        return self


ExecutionAssignmentSourceSpec = Annotated[
    ExecuteUniformWithinPairAssignmentSourceSpec
    | ImportedUniformWithinPairAssignmentSourceSpec,
    Field(discriminator="source_kind"),
]


class IndependentUniformWithinPairExecutionAssignmentSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.execution_assignment_design/0.1"]
    record_type: Literal["execution_assignment_design"]
    assignment_design_id: SDKStr
    assignment_design_version: SDKStr
    base_execution_design_ref: AssignmentAuthoringRecordRef
    pairing_ref: AssignmentAuthoringRecordRef
    exchangeability_domain_ref: AssignmentAuthoringRecordRef
    subject_execution_block_id: SDKStr
    comparator_execution_block_id: SDKStr
    assignment_unit: Literal["pair_key"]
    assignment_mechanism: Literal["independent_uniform_within_pair"]
    allocation_probability_rule: Literal["one_half_each_arm_per_pair"]
    source: ExecutionAssignmentSourceSpec
    realization_timing: Literal[
        "before_plan_cell_publication_and_first_execution_side_effect"
    ]
    pair_coverage_rule: Literal[
        "exact_cover_of_task_1_1c_preassignment_pair_set_no_subset"
    ]
    reroll_rule: Literal[
        "one_scope_one_claim_one_realization_new_draw_requires_new_suite_version"
    ]
    scope_derivation_rule: Literal[
        "task_1_1c_derived_not_caller_supplied_excludes_seed_source_design_provenance_and_realization_bytes"
    ]
    realization_key_rule: Literal[
        "task_1_1c_derived_from_scope_and_scope_claim_not_caller_supplied"
    ]
    execution_binding_rule: Literal[
        "resolved_assignment_changes_execution_design_plan_cell_and_receipt_identity"
    ]

    @model_validator(mode="after")
    def validate_execution_assignment(
        self,
    ) -> "IndependentUniformWithinPairExecutionAssignmentSpec":
        _require_non_empty("assignment_design_id", self.assignment_design_id)
        _require_semver("assignment_design_version", self.assignment_design_version)
        _validate_assignment_record_ref(
            self.base_execution_design_ref,
            "base_execution_design_ref",
            "execution_design",
        )
        _validate_assignment_record_ref(
            self.pairing_ref, "pairing_ref", "pairing_design"
        )
        _validate_assignment_record_ref(
            self.exchangeability_domain_ref,
            "exchangeability_domain_ref",
            "exchangeability_domain",
        )
        _require_non_empty(
            "subject_execution_block_id", self.subject_execution_block_id
        )
        _require_non_empty(
            "comparator_execution_block_id", self.comparator_execution_block_id
        )
        if self.subject_execution_block_id == self.comparator_execution_block_id:
            raise ValueError("subject and comparator execution blocks must be distinct")
        source_types = (
            ExecuteUniformWithinPairAssignmentSourceSpec,
            ImportedUniformWithinPairAssignmentSourceSpec,
        )
        if type(self.source) not in source_types:
            raise ValueError(
                "source must use an exact execution assignment source type"
            )
        type(self.source).model_validate(self.source.model_dump(mode="python"))
        return self


class _StrictValueModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )

    @model_validator(mode="wrap")
    @classmethod
    def reject_subclass_instances(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler["_StrictValueModel"],
    ) -> "_StrictValueModel":
        if isinstance(value, _StrictValueModel) and type(value) is not cls:
            raise ValueError("strict value records must use their exact concrete type")
        return handler(value)


class CanonicalRational(_StrictValueModel):
    numerator: SDKInt
    denominator: SDKInt = Field(gt=0)

    @model_validator(mode="after")
    def validate_canonical_rational(self) -> "CanonicalRational":
        if gcd(abs(self.numerator), self.denominator) != 1:
            raise ValueError("canonical rational must be reduced")
        if self.numerator == 0 and self.denominator != 1:
            raise ValueError("canonical rational zero must be 0/1")
        return self


class BooleanSuccessPredicateSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.boolean_success_predicate/0.1"]
    record_type: Literal["boolean_success_predicate"]
    predicate_id: SDKStr
    predicate_version: SDKStr
    input_metric_id: SDKStr
    input_schema_ref: SDKStr
    implementation: ImplementationRef
    output_kind: Literal["boolean"]
    semantic_scope: Literal["measurement_success_not_operational_availability"]

    @model_validator(mode="after")
    def validate_boolean_success_predicate(self) -> "BooleanSuccessPredicateSpec":
        _require_non_empty("predicate_id", self.predicate_id)
        _require_semver("predicate_version", self.predicate_version)
        _require_non_empty("input_metric_id", self.input_metric_id)
        _require_non_empty("input_schema_ref", self.input_schema_ref)
        _validate_planned_implementation(self.implementation, "implementation")
        return self


def _validate_estimator_identity(
    estimator_id: str,
    estimator_version: str,
    output_metric_id: str,
) -> None:
    _require_non_empty("estimator_id", estimator_id)
    _require_semver("estimator_version", estimator_version)
    _require_non_empty("output_metric_id", output_metric_id)


def _validate_analysis_unit_weighting(
    analysis_unit: str,
    weighting: str,
    within_cluster_reduction: str | None,
    *,
    allow_pair: bool,
) -> None:
    allowed = {
        "planned_cell": ("row_uniform", None),
        "population_cluster": ("cluster_uniform", "mean"),
    }
    if allow_pair:
        allowed["pair"] = ("pair_uniform", None)
    if allowed.get(analysis_unit) != (weighting, within_cluster_reduction):
        raise ValueError(
            "analysis_unit requires its exact weighting and within-cluster reduction"
        )


class MeanEstimatorSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.estimator/0.1"]
    record_type: Literal["estimator"]
    estimator_kind: Literal["mean"]
    estimator_id: SDKStr
    estimator_version: SDKStr
    output_metric_id: SDKStr
    input_numeric_policy: Literal["aeread.exact_rational_binary64/0.1"]
    output_rounding_policy: Literal["aeread.binary64_rne/0.1"]
    rounding_stage: Literal["typed_output_only_never_internal"]
    input_metric_id: SDKStr
    analysis_unit: Literal["planned_cell", "population_cluster"]
    weighting: Literal["row_uniform", "cluster_uniform"]
    within_cluster_reduction: Literal["mean"] | None

    @model_validator(mode="after")
    def validate_mean_estimator(self) -> "MeanEstimatorSpec":
        _validate_estimator_identity(
            self.estimator_id, self.estimator_version, self.output_metric_id
        )
        _require_non_empty("input_metric_id", self.input_metric_id)
        _validate_analysis_unit_weighting(
            self.analysis_unit,
            self.weighting,
            self.within_cluster_reduction,
            allow_pair=False,
        )
        return self


class DifferenceEstimatorSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.estimator/0.1"]
    record_type: Literal["estimator"]
    estimator_kind: Literal["difference"]
    estimator_id: SDKStr
    estimator_version: SDKStr
    output_metric_id: SDKStr
    input_numeric_policy: Literal["aeread.exact_rational_binary64/0.1"]
    output_rounding_policy: Literal["aeread.binary64_rne/0.1"]
    rounding_stage: Literal["typed_output_only_never_internal"]
    input_metric_id: SDKStr
    input_arity: SDKInt
    operand_order: Literal["subject_minus_comparator"]
    analysis_unit: Literal["planned_cell", "population_cluster", "pair"]
    weighting: Literal["row_uniform", "cluster_uniform", "pair_uniform"]
    within_cluster_reduction: Literal["mean"] | None

    @model_validator(mode="after")
    def validate_difference_estimator(self) -> "DifferenceEstimatorSpec":
        _validate_estimator_identity(
            self.estimator_id, self.estimator_version, self.output_metric_id
        )
        _require_non_empty("input_metric_id", self.input_metric_id)
        if self.input_arity != 2:
            raise ValueError("difference input_arity must equal 2")
        _validate_analysis_unit_weighting(
            self.analysis_unit,
            self.weighting,
            self.within_cluster_reduction,
            allow_pair=True,
        )
        return self


class ProbabilityEstimatorSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.estimator/0.1"]
    record_type: Literal["estimator"]
    estimator_kind: Literal["probability"]
    estimator_id: SDKStr
    estimator_version: SDKStr
    output_metric_id: SDKStr
    input_numeric_policy: Literal["aeread.exact_rational_binary64/0.1"]
    output_rounding_policy: Literal["aeread.binary64_rne/0.1"]
    rounding_stage: Literal["typed_output_only_never_internal"]
    predicate: BooleanSuccessPredicateSpec
    analysis_unit: Literal["planned_cell"]
    weighting: Literal["row_uniform"]
    denominator_source: Literal["episode_missingness_policy"]

    @model_validator(mode="after")
    def validate_probability_estimator(self) -> "ProbabilityEstimatorSpec":
        _validate_estimator_identity(
            self.estimator_id, self.estimator_version, self.output_metric_id
        )
        return self


class QuantileEstimatorSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.estimator/0.1"]
    record_type: Literal["estimator"]
    estimator_kind: Literal["quantile"]
    estimator_id: SDKStr
    estimator_version: SDKStr
    output_metric_id: SDKStr
    input_numeric_policy: Literal["aeread.exact_rational_binary64/0.1"]
    output_rounding_policy: Literal["aeread.binary64_rne/0.1"]
    rounding_stage: Literal["typed_output_only_never_internal"]
    input_metric_id: SDKStr
    analysis_unit: Literal["planned_cell"]
    weighting: Literal["row_uniform"]
    q: CanonicalRational
    interpolation: Literal["r7_linear"]

    @model_validator(mode="after")
    def validate_quantile_estimator(self) -> "QuantileEstimatorSpec":
        _validate_estimator_identity(
            self.estimator_id, self.estimator_version, self.output_metric_id
        )
        _require_non_empty("input_metric_id", self.input_metric_id)
        if not 0 < self.q.numerator < self.q.denominator:
            raise ValueError("quantile q must be strictly between zero and one")
        return self


class PassAllKEstimatorSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.estimator/0.1"]
    record_type: Literal["estimator"]
    estimator_kind: Literal["pass_all_k"]
    estimator_id: SDKStr
    estimator_version: SDKStr
    output_metric_id: SDKStr
    input_numeric_policy: Literal["aeread.exact_rational_binary64/0.1"]
    output_rounding_policy: Literal["aeread.binary64_rne/0.1"]
    rounding_stage: Literal["typed_output_only_never_internal"]
    predicate: BooleanSuccessPredicateSpec
    k: SDKInt = Field(gt=0)
    analysis_unit: Literal["planned_cell_group"]
    weighting: Literal["group_uniform"]
    group_key_fields: tuple[PlannedCoordinateField, ...]
    group_semantics: Literal["exactly_k_unique_plan_cells"]
    incomplete_group_rule: Literal["typed_missing_not_false"]

    @model_validator(mode="after")
    def validate_pass_all_k_estimator(self) -> "PassAllKEstimatorSpec":
        _validate_estimator_identity(
            self.estimator_id, self.estimator_version, self.output_metric_id
        )
        if not self.group_key_fields:
            raise ValueError("group_key_fields must be non-empty")
        if len(self.group_key_fields) != len(set(self.group_key_fields)):
            raise ValueError("group_key_fields must be unique")
        coordinate_order = {
            field: index
            for index, field in enumerate(
                (
                    "population_unit_id",
                    "case_id",
                    "repetition_index",
                    "rollout_seed",
                    "world_seed",
                )
            )
        }
        if tuple(sorted(self.group_key_fields, key=coordinate_order.__getitem__)) != (
            self.group_key_fields
        ):
            raise ValueError("group_key_fields must use planned-coordinate order")
        return self


EstimatorSpec = Annotated[
    MeanEstimatorSpec
    | DifferenceEstimatorSpec
    | ProbabilityEstimatorSpec
    | QuantileEstimatorSpec
    | PassAllKEstimatorSpec,
    Field(discriminator="estimator_kind"),
]


class IdentityTransformationSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.transformation/0.1"]
    record_type: Literal["transformation"]
    transformation_kind: Literal["identity"]
    input_units: SDKStr
    output_units: SDKStr
    unit_rule: Literal["input_and_output_units_must_match"]

    @model_validator(mode="after")
    def validate_identity_transformation(self) -> "IdentityTransformationSpec":
        _require_non_empty("input_units", self.input_units)
        _require_non_empty("output_units", self.output_units)
        if self.input_units != self.output_units:
            raise ValueError("identity transformation units must match exactly")
        return self


def _validate_missingness_identity(policy_id: str, policy_version: str) -> None:
    _require_non_empty("policy_id", policy_id)
    _require_semver("policy_version", policy_version)


class PlannedPopulationInvalidateMissingnessSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.episode_missingness/0.1"]
    record_type: Literal["episode_missingness"]
    missingness_kind: Literal["planned_population_invalidate"]
    policy_id: SDKStr
    policy_version: SDKStr
    coverage_unit: Literal["planned_cell"]
    count_reporting_rule: Literal["planned_valid_missing_invalid_counts_separate"]
    silent_drop_rule: Literal["forbidden"]
    zero_attempt_rule: Literal["run_coverage_not_observation"]
    valid_tie_rule: Literal["valid_measurement_not_missing"]
    scientific_target: Literal["planned_population_primary"]
    denominator_treatment: Literal["planned"]
    ignorability_assumption: Literal["none"]
    missing_or_invalid_rule: Literal["typed_invalid_primary_analysis"]
    conditional_secondary_rule: Literal["separate_preregistered_block_only"]

    @model_validator(mode="after")
    def validate_planned_population_missingness(
        self,
    ) -> "PlannedPopulationInvalidateMissingnessSpec":
        _validate_missingness_identity(self.policy_id, self.policy_version)
        return self


class CompleteCaseConditionalMissingnessSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.episode_missingness/0.1"]
    record_type: Literal["episode_missingness"]
    missingness_kind: Literal["complete_case_conditional"]
    policy_id: SDKStr
    policy_version: SDKStr
    coverage_unit: Literal["planned_cell"]
    count_reporting_rule: Literal["planned_valid_missing_invalid_counts_separate"]
    silent_drop_rule: Literal["forbidden"]
    zero_attempt_rule: Literal["run_coverage_not_observation"]
    valid_tie_rule: Literal["valid_measurement_not_missing"]
    scientific_target: Literal["complete_case_conditional"]
    denominator_treatment: Literal["valid_only"]
    minimum_valid_planned_cells: SDKInt = Field(gt=0)
    ignorability_assumption: Literal["none_claimed"]
    missing_or_invalid_rule: Literal["exclude_with_typed_disposition_and_report"]
    population_primary_claim: Literal["forbidden"]

    @model_validator(mode="after")
    def validate_complete_case_missingness(
        self,
    ) -> "CompleteCaseConditionalMissingnessSpec":
        _validate_missingness_identity(self.policy_id, self.policy_version)
        return self


class BoundsOrSensitivityMissingnessSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.episode_missingness/0.1"]
    record_type: Literal["episode_missingness"]
    missingness_kind: Literal["bounds_or_sensitivity"]
    policy_id: SDKStr
    policy_version: SDKStr
    coverage_unit: Literal["planned_cell"]
    count_reporting_rule: Literal["planned_valid_missing_invalid_counts_separate"]
    silent_drop_rule: Literal["forbidden"]
    zero_attempt_rule: Literal["run_coverage_not_observation"]
    valid_tie_rule: Literal["valid_measurement_not_missing"]
    scientific_target: Literal["bounds_or_sensitivity"]
    denominator_treatment: Literal["planned_with_typed_unobserved_units"]
    method: ImplementationRef
    method_input_schema_ref: SDKStr
    assumption_artifact_ref: ArtifactRef
    point_estimate_rule: Literal["no_unbounded_complete_case_primary"]

    @model_validator(mode="after")
    def validate_bounds_missingness(self) -> "BoundsOrSensitivityMissingnessSpec":
        _validate_missingness_identity(self.policy_id, self.policy_version)
        _validate_planned_implementation(self.method, "method")
        _require_non_empty("method_input_schema_ref", self.method_input_schema_ref)
        _validate_planned_artifact(
            self.assumption_artifact_ref, "assumption_artifact_ref"
        )
        return self


EpisodeMissingnessSpec = Annotated[
    PlannedPopulationInvalidateMissingnessSpec
    | CompleteCaseConditionalMissingnessSpec
    | BoundsOrSensitivityMissingnessSpec,
    Field(discriminator="missingness_kind"),
]


class RaterCoverageSummarySpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.rater_summary/0.1"]
    record_type: Literal["rater_summary"]
    summary_kind: Literal["coverage"]
    summary_id: SDKStr
    summary_version: SDKStr
    denominator: Literal["planned_judgment_slots"]
    reported_counts: tuple[
        Literal["planned_slots"],
        Literal["valid_slots"],
        Literal["missing_slots"],
        Literal["invalid_slots"],
    ]
    missing_judgment_score_rule: Literal["never_coerce_to_score_zero"]
    score_effect: Literal["none_descriptive_only"]

    @model_validator(mode="after")
    def validate_rater_coverage_summary(self) -> "RaterCoverageSummarySpec":
        _require_non_empty("summary_id", self.summary_id)
        _require_semver("summary_version", self.summary_version)
        return self


class RaterDisagreementSummarySpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.rater_summary/0.1"]
    record_type: Literal["rater_summary"]
    summary_kind: Literal["categorical_pairwise_disagreement"]
    summary_id: SDKStr
    summary_version: SDKStr
    input_rule: Literal["accepted_terminal_categorical_judgments_only"]
    denominator: Literal["unordered_valid_rater_pairs"]
    metric: Literal["pairwise_disagreement_probability"]
    fewer_than_two_rule: Literal["typed_unavailable_not_zero"]
    tie_rule: Literal["preserve_valid_categorical_tie"]
    score_effect: Literal["none_descriptive_only"]

    @model_validator(mode="after")
    def validate_rater_disagreement_summary(
        self,
    ) -> "RaterDisagreementSummarySpec":
        _require_non_empty("summary_id", self.summary_id)
        _require_semver("summary_version", self.summary_version)
        return self


RaterSummarySpec = Annotated[
    RaterCoverageSummarySpec | RaterDisagreementSummarySpec,
    Field(discriminator="summary_kind"),
]


class AnalysisSourceRef(_PlannedIdentityRecord):
    spec_version: Literal["aeread.analysis_source_ref/0.1"]
    record_type: Literal["analysis_source_ref"]
    source_kind: Literal[
        "cluster_design", "pairing_design", "execution_assignment_design"
    ]
    record_id: SDKStr
    record_version: SDKStr
    content_sha256: SHA256

    @model_validator(mode="after")
    def validate_analysis_source_ref(self) -> "AnalysisSourceRef":
        _require_non_empty("record_id", self.record_id)
        _require_semver("record_version", self.record_version)
        return self


def _validate_analysis_source_ref(
    reference: AnalysisSourceRef, label: str, expected_kind: str
) -> None:
    if type(reference) is not AnalysisSourceRef:
        raise ValueError(f"{label} must use the exact AnalysisSourceRef type")
    AnalysisSourceRef.model_validate(reference.model_dump(mode="python"))
    if reference.source_kind != expected_kind:
        raise ValueError(f"{label} must have source_kind {expected_kind!r}")


class EffectiveResamplingBlockSpec(_StrictValueModel):
    effective_block_id: SDKStr
    population_cluster_ids: tuple[SDKStr, ...]

    @model_validator(mode="after")
    def validate_effective_resampling_block(self) -> "EffectiveResamplingBlockSpec":
        _require_non_empty("effective_block_id", self.effective_block_id)
        _validate_canonical_string_tuple(
            self.population_cluster_ids, "population_cluster_ids", required=True
        )
        return self


class PopulationClusterProjectionSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.cluster_projection/0.1"]
    record_type: Literal["cluster_projection"]
    projection_id: SDKStr
    projection_version: SDKStr
    cluster_design_ref: AnalysisSourceRef
    population_key_field: Literal["population_unit_id"]
    replicate_nesting_rule: Literal["all_plan_cells_for_unit_share_population_cluster"]
    coverage_rule: Literal["exactly_one_population_cluster_per_planned_cell"]
    effective_block_kind: Literal["population_cluster", "strict_coarsening"]
    effective_blocks: tuple[EffectiveResamplingBlockSpec, ...]
    group_integrity_rule: Literal["pair_and_pass_all_k_groups_wholly_nested"]
    ordering_rule: Literal["effective_block_id_then_canonical_row_identity"]

    @model_validator(mode="after")
    def validate_population_cluster_projection(
        self,
    ) -> "PopulationClusterProjectionSpec":
        _require_non_empty("projection_id", self.projection_id)
        _require_semver("projection_version", self.projection_version)
        _validate_analysis_source_ref(
            self.cluster_design_ref, "cluster_design_ref", "cluster_design"
        )
        if self.effective_block_kind == "population_cluster":
            if self.effective_blocks:
                raise ValueError("population_cluster requires no effective blocks")
        else:
            if not self.effective_blocks:
                raise ValueError("strict_coarsening requires effective blocks")
            block_ids = tuple(
                block.effective_block_id for block in self.effective_blocks
            )
            _validate_canonical_string_tuple(
                block_ids, "effective block IDs", required=True
            )
            clusters = tuple(
                cluster
                for block in self.effective_blocks
                for cluster in block.population_cluster_ids
            )
            if len(clusters) != len(set(clusters)):
                raise ValueError("effective blocks cannot repeat population clusters")
        return self


class PairProjectionSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.pair_projection/0.1"]
    record_type: Literal["pair_projection"]
    projection_id: SDKStr
    projection_version: SDKStr
    pairing_ref: AnalysisSourceRef
    pairing_kind: Literal["paired", "unpaired"]
    coordinate_source: Literal["resolved_plan_cell_coordinates"]
    direction: Literal["subject_minus_comparator"]
    formation_rule: Literal[
        "one_to_one_equal_pair_keys", "independent_subject_and_comparator_arms"
    ]
    duplicate_rule: Literal["reject"]
    missing_pair_rule: Literal["typed_missing_not_drop"]
    ordering_rule: Literal[
        "pair_key_then_subject_then_comparator",
        "subject_then_comparator_canonical_row_identity",
    ]
    projection_scope: Literal["analysis_relation_only"]

    @model_validator(mode="after")
    def validate_pair_projection(self) -> "PairProjectionSpec":
        _require_non_empty("projection_id", self.projection_id)
        _require_semver("projection_version", self.projection_version)
        _validate_analysis_source_ref(self.pairing_ref, "pairing_ref", "pairing_design")
        expected = (
            ("one_to_one_equal_pair_keys", "pair_key_then_subject_then_comparator")
            if self.pairing_kind == "paired"
            else (
                "independent_subject_and_comparator_arms",
                "subject_then_comparator_canonical_row_identity",
            )
        )
        if (self.formation_rule, self.ordering_rule) != expected:
            raise ValueError(
                "pairing kind requires its exact formation and ordering rules"
            )
        return self


class NoIntervalSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.interval/0.1"]
    record_type: Literal["interval"]
    interval_kind: Literal["none"]
    reason: Literal[
        "not_requested",
        "paired_randomization_test_has_no_interval",
        "finite_population_interval_not_supported_v0",
    ]
    method: Literal["none"]


class ClusterBootstrapStabilityIntervalSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.interval/0.1"]
    record_type: Literal["interval"]
    interval_kind: Literal["cluster_bootstrap_stability"]
    interval_id: SDKStr
    interval_version: SDKStr
    method: Literal["percentile_cluster_bootstrap_stability"]
    coverage_claim: Literal["none_descriptive_only"]
    target: Literal["conditional_on_observed_effective_blocks"]
    central_mass: CanonicalRational
    endpoint_definition: Literal["equal_tailed_percentile_endpoints"]
    resample_count: SDKInt = Field(ge=2)
    resampling_seed: SDKInt = Field(ge=0)
    resampling_unit: Literal["whole_effective_row_block"]
    effective_block_source: Literal["population_cluster_projection"]
    group_integrity_rule: Literal["pair_and_pass_all_k_groups_wholly_nested"]
    estimator_recompute_rule: Literal[
        "complete_declared_estimator_over_all_rows_with_block_multiplicity"
    ]
    sampler_policy: Literal["aeread.sha256_rejection_uint256_mod_c/0.1"]
    endpoint_quantile_policy: Literal["r7_linear_exact_rational"]
    minimum_effective_blocks: Literal[2]
    claim_boundary: Literal["no_finite_population_or_superpopulation_coverage_claim"]

    @model_validator(mode="after")
    def validate_cluster_bootstrap_stability_interval(
        self,
    ) -> "ClusterBootstrapStabilityIntervalSpec":
        _require_non_empty("interval_id", self.interval_id)
        _require_semver("interval_version", self.interval_version)
        if type(self.central_mass) is not CanonicalRational:
            raise ValueError("central_mass must use the exact CanonicalRational type")
        CanonicalRational.model_validate(self.central_mass.model_dump(mode="python"))
        if not 0 < self.central_mass.numerator < self.central_mass.denominator:
            raise ValueError("central_mass must be strictly between zero and one")
        return self


IntervalSpec = Annotated[
    NoIntervalSpec | ClusterBootstrapStabilityIntervalSpec,
    Field(discriminator="interval_kind"),
]


class NoHypothesisTestSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.hypothesis_test/0.1"]
    record_type: Literal["hypothesis_test"]
    test_kind: Literal["none"]
    reason: Literal[
        "not_requested",
        "observational_pairing",
        "unpaired_contrast",
        "descriptive_stability_only",
    ]
    method: Literal["none"]


class PairedRandomizationTestSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.hypothesis_test/0.1"]
    record_type: Literal["hypothesis_test"]
    test_kind: Literal["paired_randomization"]
    test_id: SDKStr
    test_version: SDKStr
    method: Literal["paired_sign_flip_randomization"]
    execution_assignment_design_ref: AnalysisSourceRef
    subject_role: Literal["subject"]
    comparator_role: Literal["comparator"]
    role_binding_rule: Literal[
        "match_referenced_design_subject_and_comparator_execution_blocks"
    ]
    statistic: Literal["absolute_mean_subject_minus_comparator"]
    alternative: Literal["two_sided"]
    extreme_tie_rule: Literal["greater_than_or_equal"]
    pair_eligibility_rule: Literal[
        "every_preregistered_pair_has_exactly_two_valid_arm_outcomes"
    ]
    missing_pair_rule: Literal[
        "typed_ineligible_no_p_value_no_deletion_replacement_or_reassignment"
    ]
    exhaustive_assignment_vector_threshold: SDKInt = Field(ge=2)
    monte_carlo_resample_count: SDKInt = Field(ge=1)
    monte_carlo_seed: SDKInt = Field(ge=0)
    exhaustive_order: Literal["mask_ascending_pair_key_order_bit0_negative"]
    monte_carlo_policy: Literal["aeread.paired_randomization_sha256_bit/0.1"]
    monte_carlo_correction: Literal["plus_one_numerator_and_denominator"]
    numeric_policy: Literal["aeread.exact_rational_binary64/0.1"]
    interval_requirement: Literal["none"]

    @model_validator(mode="after")
    def validate_paired_randomization_test(self) -> "PairedRandomizationTestSpec":
        _require_non_empty("test_id", self.test_id)
        _require_semver("test_version", self.test_version)
        _validate_analysis_source_ref(
            self.execution_assignment_design_ref,
            "execution_assignment_design_ref",
            "execution_assignment_design",
        )
        return self


HypothesisTestSpec = Annotated[
    NoHypothesisTestSpec | PairedRandomizationTestSpec, Field(discriminator="test_kind")
]


class NoMultiplicityAdjustmentSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.multiplicity/0.1"]
    record_type: Literal["multiplicity"]
    multiplicity_kind: Literal["none"]
    reason: Literal["single_confirmatory_test", "descriptive_only", "not_requested"]
    method: Literal["none"]


class HolmMultiplicityAdjustmentSpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.multiplicity/0.1"]
    record_type: Literal["multiplicity"]
    multiplicity_kind: Literal["holm_familywise"]
    family_id: SDKStr
    family_version: SDKStr
    alpha: CanonicalRational
    family_membership_source: Literal["task_1_1b5_immutable_preregistered_test_nodes"]
    minimum_family_size: Literal[2]
    family_cardinality_rule: Literal["at_least_two_distinct_preregistered_test_nodes"]
    family_ordering_rule: Literal[
        "eligible_raw_p_value_then_test_id_followed_by_ineligible_test_id"
    ]
    method: Literal["holm_step_down_familywise"]
    threshold_rule: Literal[
        "alpha_over_original_preregistered_family_size_minus_eligible_rank_plus_one"
    ]
    stop_rule: Literal["stop_rejecting_after_first_nonrejection"]
    adjusted_p_rule: Literal["running_max_rank_scaled_clipped_one"]
    ineligible_test_rule: Literal[
        "retain_in_preregistered_family_cardinality_no_adjusted_p_no_rejection"
    ]
    numeric_policy: Literal["exact_rational"]

    @model_validator(mode="after")
    def validate_holm_multiplicity_adjustment(
        self,
    ) -> "HolmMultiplicityAdjustmentSpec":
        _require_non_empty("family_id", self.family_id)
        _require_semver("family_version", self.family_version)
        if type(self.alpha) is not CanonicalRational:
            raise ValueError("alpha must use the exact CanonicalRational type")
        CanonicalRational.model_validate(self.alpha.model_dump(mode="python"))
        if not 0 < self.alpha.numerator < self.alpha.denominator:
            raise ValueError("alpha must be strictly between zero and one")
        return self


MultiplicityAdjustmentSpec = Annotated[
    NoMultiplicityAdjustmentSpec | HolmMultiplicityAdjustmentSpec,
    Field(discriminator="multiplicity_kind"),
]


class InferenceCompatibilitySpec(_PlannedIdentityRecord):
    spec_version: Literal["aeread.inference_compatibility/0.1"]
    record_type: Literal["inference_compatibility"]
    compatibility_id: SDKStr
    compatibility_version: SDKStr
    inference_target: Literal[
        "planned_panel_descriptive",
        "finite_population_probability_sample",
        "cluster_bootstrap_descriptive_stability",
        "paired_observational_effect",
        "unpaired_observational_difference",
        "paired_randomized_effect",
    ]
    panel_basis: Literal["fixed_panel", "sampled_srswor"]
    estimator_analysis_unit: Literal["planned_cell", "population_cluster", "pair"]
    missingness_kind: Literal[
        "planned_population_invalidate",
        "complete_case_conditional",
        "bounds_or_sensitivity",
    ]
    cluster_projection: PopulationClusterProjectionSpec | None
    pair_projection: PairProjectionSpec | None
    interval: IntervalSpec
    hypothesis_test: HypothesisTestSpec
    multiplicity: MultiplicityAdjustmentSpec
    compatibility_matrix_version: Literal["aeread.inference_compatibility_matrix/0.2"]

    @model_validator(mode="after")
    def validate_inference_compatibility(self) -> "InferenceCompatibilitySpec":
        _require_non_empty("compatibility_id", self.compatibility_id)
        _require_semver("compatibility_version", self.compatibility_version)
        if self.cluster_projection is not None:
            if type(self.cluster_projection) is not PopulationClusterProjectionSpec:
                raise ValueError("cluster_projection must use its exact concrete type")
            PopulationClusterProjectionSpec.model_validate(
                self.cluster_projection.model_dump(mode="python")
            )
        if self.pair_projection is not None:
            if type(self.pair_projection) is not PairProjectionSpec:
                raise ValueError("pair_projection must use its exact concrete type")
            PairProjectionSpec.model_validate(
                self.pair_projection.model_dump(mode="python")
            )
        interval_types = (NoIntervalSpec, ClusterBootstrapStabilityIntervalSpec)
        test_types = (NoHypothesisTestSpec, PairedRandomizationTestSpec)
        multiplicity_types = (
            NoMultiplicityAdjustmentSpec,
            HolmMultiplicityAdjustmentSpec,
        )
        if type(self.interval) not in interval_types:
            raise ValueError("interval must use an exact concrete type")
        if type(self.hypothesis_test) not in test_types:
            raise ValueError("hypothesis_test must use an exact concrete type")
        if type(self.multiplicity) not in multiplicity_types:
            raise ValueError("multiplicity must use an exact concrete type")
        target = self.inference_target
        no_interval = type(self.interval) is NoIntervalSpec
        no_test = type(self.hypothesis_test) is NoHypothesisTestSpec
        no_multiplicity = type(self.multiplicity) is NoMultiplicityAdjustmentSpec
        if target == "planned_panel_descriptive":
            valid = (
                self.panel_basis == "fixed_panel"
                and self.estimator_analysis_unit == "planned_cell"
                and self.cluster_projection is None
                and self.pair_projection is None
                and no_interval
                and no_test
                and no_multiplicity
            )
        elif target == "finite_population_probability_sample":
            valid = (
                self.panel_basis == "sampled_srswor"
                and self.estimator_analysis_unit == "planned_cell"
                and self.cluster_projection is None
                and self.pair_projection is None
                and type(self.interval) is NoIntervalSpec
                and self.interval.reason
                == "finite_population_interval_not_supported_v0"
                and no_test
                and no_multiplicity
                and self.missingness_kind != "complete_case_conditional"
            )
        elif target == "cluster_bootstrap_descriptive_stability":
            valid = (
                self.estimator_analysis_unit in ("planned_cell", "population_cluster")
                and self.cluster_projection is not None
                and self.pair_projection is None
                and type(self.interval) is ClusterBootstrapStabilityIntervalSpec
                and no_test
                and no_multiplicity
            )
        elif target == "paired_observational_effect":
            valid = (
                self.estimator_analysis_unit == "pair"
                and self.cluster_projection is None
                and self.pair_projection is not None
                and self.pair_projection.pairing_kind == "paired"
                and no_interval
                and no_test
                and self.hypothesis_test.reason == "observational_pairing"
                and no_multiplicity
            )
        elif target == "unpaired_observational_difference":
            valid = (
                self.estimator_analysis_unit == "planned_cell"
                and self.cluster_projection is None
                and self.pair_projection is not None
                and self.pair_projection.pairing_kind == "unpaired"
                and no_interval
                and no_test
                and self.hypothesis_test.reason == "unpaired_contrast"
                and no_multiplicity
            )
        else:
            valid = (
                self.estimator_analysis_unit == "pair"
                and self.cluster_projection is None
                and self.pair_projection is not None
                and self.pair_projection.pairing_kind == "paired"
                and self.missingness_kind == "planned_population_invalidate"
                and type(self.interval) is NoIntervalSpec
                and self.interval.reason == "paired_randomization_test_has_no_interval"
                and type(self.hypothesis_test) is PairedRandomizationTestSpec
            )
        if not valid:
            raise ValueError(
                "inference target requires its exact local compatibility matrix"
            )
        return self


class ValidityDomainSpec(StrictModel):
    domain_id: SDKStr
    domain_version: SDKStr
    schema_ref: SDKStr
    predicate: ImplementationRef
    parameters: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_domain(self) -> "ValidityDomainSpec":
        _validate_direct_record_values(self, "validity domain")
        _require_semver("domain_version", self.domain_version)
        _validate_artifact_tuple(self.parameters, "domain parameters", required=False)
        return self


class EstimandSpec(StrictModel):
    estimand_id: SDKStr
    estimand_version: SDKStr
    input_scope: EstimandInputScope
    direction: Literal["maximize", "minimize", "none"]
    units: SDKStr
    quantity_schema_ref: SDKStr
    validity_domain: ValidityDomainSpec

    @model_validator(mode="after")
    def validate_estimand(self) -> "EstimandSpec":
        _validate_direct_record_values(self, "estimand")
        _require_semver("estimand_version", self.estimand_version)
        return self


class CasePayloadReferenceSource(StrictModel):
    source_kind: Literal["case_payload"]
    path: SDKStr
    schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_case_payload_path(self) -> "CasePayloadReferenceSource":
        _validate_direct_record_values(self, "case-payload source")
        segments = self.path.split("/")
        if (
            self.path.startswith("/")
            or "\\" in self.path
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValueError(
                "case-payload path must be a non-empty relative path without "
                "empty, dot, or traversal segments"
            )
        return self


class ArtifactReferenceSource(StrictModel):
    source_kind: Literal["artifacts"]
    artifacts: tuple[ArtifactRef, ...]

    @model_validator(mode="after")
    def validate_artifacts(self) -> "ArtifactReferenceSource":
        _validate_artifact_tuple(self.artifacts, "reference artifacts", required=True)
        return self


PreOutcomeInput = Literal[
    "case_manifest", "case_payload", "world_seed", "reference_artifacts"
]


class PreOutcomeComputationSource(StrictModel):
    source_kind: Literal["pre_outcome_computation"]
    determinism: Literal["pure_deterministic"]
    implementation: ImplementationRef
    allowed_inputs: tuple[PreOutcomeInput, ...]
    output_schema_ref: SDKStr
    input_artifacts: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_computation(self) -> "PreOutcomeComputationSource":
        _validate_direct_record_values(self, "pre-outcome computation")
        canonical_order = (
            "case_manifest",
            "case_payload",
            "world_seed",
            "reference_artifacts",
        )
        if not self.allowed_inputs:
            raise ValueError("allowed_inputs must be non-empty")
        indices = [canonical_order.index(value) for value in self.allowed_inputs]
        if indices != sorted(set(indices)):
            raise ValueError("allowed_inputs must be unique and canonically ordered")
        _validate_artifact_tuple(
            self.input_artifacts, "computation input_artifacts", required=False
        )
        if self.input_artifacts and "reference_artifacts" not in self.allowed_inputs:
            raise ValueError(
                "input_artifacts require reference_artifacts in allowed_inputs"
            )
        return self


ReferenceSource = Annotated[
    CasePayloadReferenceSource | ArtifactReferenceSource | PreOutcomeComputationSource,
    Field(discriminator="source_kind"),
]


class _VersionedReference(StrictModel):
    reference_id: SDKStr
    reference_version: SDKStr
    source: ReferenceSource

    @model_validator(mode="after")
    def validate_reference_identity(self) -> "_VersionedReference":
        _validate_direct_record_values(self, "reference")
        _require_semver("reference_version", self.reference_version)
        return self


class AbsoluteToleranceSpec(StrictModel):
    tolerance_kind: Literal["absolute"]
    value: SDKFloat = Field(ge=0)
    units: SDKStr

    @model_validator(mode="after")
    def validate_units(self) -> "AbsoluteToleranceSpec":
        _validate_direct_record_values(self, "absolute tolerance")
        return self


class RelativeToleranceSpec(StrictModel):
    tolerance_kind: Literal["relative"]
    value: SDKFloat = Field(ge=0)


ToleranceSpec = Annotated[
    AbsoluteToleranceSpec | RelativeToleranceSpec,
    Field(discriminator="tolerance_kind"),
]


class ExactPointMatchSpec(StrictModel):
    match_kind: Literal["exact"]


class TolerancePointMatchSpec(StrictModel):
    match_kind: Literal["tolerance"]
    tolerance: ToleranceSpec


PointMatchSpec = Annotated[
    ExactPointMatchSpec | TolerancePointMatchSpec,
    Field(discriminator="match_kind"),
]


class CanonicalPointReference(_VersionedReference):
    reference_kind: Literal["canonical_point"]
    input_scope: Literal["answer", "terminal_state"]
    input_schema_ref: SDKStr
    units: SDKStr
    canonicalizer: ImplementationRef
    match: PointMatchSpec

    @model_validator(mode="after")
    def validate_point_match(self) -> "CanonicalPointReference":
        if (
            isinstance(self.match, TolerancePointMatchSpec)
            and isinstance(self.match.tolerance, AbsoluteToleranceSpec)
            and self.match.tolerance.units != self.units
        ):
            raise ValueError("absolute tolerance units must match point units")
        return self


class CanonicalSetReference(_VersionedReference):
    reference_kind: Literal["canonical_set"]
    input_scope: Literal["answer", "terminal_state"]
    input_schema_ref: SDKStr
    units: SDKStr
    canonicalizer: ImplementationRef
    membership: ImplementationRef
    match_kind: Literal["exact"]


class TerminalStateEquivalenceReference(_VersionedReference):
    reference_kind: Literal["terminal_state_equivalence"]
    input_scope: Literal["terminal_state"]
    input_schema_ref: SDKStr
    units: SDKStr
    equivalence: ImplementationRef


class DistanceToCanonicalSetReference(_VersionedReference):
    reference_kind: Literal["distance_to_canonical_set"]
    input_scope: Literal["answer", "terminal_state"]
    input_schema_ref: SDKStr
    units: SDKStr
    canonicalizer: ImplementationRef
    distance: ImplementationRef
    tolerance: ToleranceSpec

    @model_validator(mode="after")
    def validate_distance_units(self) -> "DistanceToCanonicalSetReference":
        if (
            isinstance(self.tolerance, AbsoluteToleranceSpec)
            and self.tolerance.units != self.units
        ):
            raise ValueError("absolute tolerance units must match distance units")
        return self


CanonicalReference = Annotated[
    CanonicalPointReference
    | CanonicalSetReference
    | TerminalStateEquivalenceReference
    | DistanceToCanonicalSetReference,
    Field(discriminator="reference_kind"),
]


class CanonicalReferenceVerifier(StrictModel):
    verifier_family: Literal["canonical_reference"]
    verifier_id: SDKStr
    verifier_version: SDKStr
    reference: CanonicalReference

    @model_validator(mode="after")
    def validate_verifier(self) -> "CanonicalReferenceVerifier":
        _validate_direct_record_values(self, "canonical verifier")
        _require_semver("verifier_version", self.verifier_version)
        return self


RuleInputScope = Literal["answer", "terminal_state", "trajectory", "distribution"]
RuleCheckpointScope = Literal[
    "answer",
    "final_state",
    "every_state",
    "every_transition",
    "whole_trajectory",
    "related_cases",
]
RuleResultSemantics = Literal[
    "boolean", "pass_vector", "residual", "pass_vector_and_residual"
]


class _RuleReferenceBase(_VersionedReference):
    input_scope: RuleInputScope
    checkpoint_scope: RuleCheckpointScope
    result_schema_ref: SDKStr
    result_semantics: RuleResultSemantics
    residual_schema_ref: SDKStr | None = None

    @model_validator(mode="after")
    def validate_result_semantics(self) -> "_RuleReferenceBase":
        needs_residual = self.result_semantics in {
            "residual",
            "pass_vector_and_residual",
        }
        if needs_residual and self.residual_schema_ref is None:
            raise ValueError("residual result semantics require residual_schema_ref")
        if not needs_residual and self.residual_schema_ref is not None:
            raise ValueError(
                "residual_schema_ref is only legal for residual result semantics"
            )
        return self


class ConstraintSatisfactionReference(_RuleReferenceBase):
    reference_kind: Literal["constraint_satisfaction"]
    predicate: ImplementationRef

    @model_validator(mode="after")
    def validate_scope_pair(self) -> "ConstraintSatisfactionReference":
        expected = {
            "answer": "answer",
            "terminal_state": "final_state",
            "trajectory": "every_transition",
        }
        if (
            self.input_scope not in expected
            or self.checkpoint_scope != expected[self.input_scope]
        ):
            raise ValueError(
                "constraint scope/checkpoint must be answer/answer, "
                "terminal_state/final_state, or trajectory/every_transition"
            )
        return self


class StateInvariantReference(_RuleReferenceBase):
    reference_kind: Literal["state_invariant"]
    input_scope: Literal["terminal_state", "trajectory"]
    checkpoint_scope: Literal["final_state", "every_state"]
    predicate: ImplementationRef

    @model_validator(mode="after")
    def validate_scope_pair(self) -> "StateInvariantReference":
        expected = {
            "terminal_state": "final_state",
            "trajectory": "every_state",
        }
        if self.checkpoint_scope != expected[self.input_scope]:
            raise ValueError("state invariant scope/checkpoint are incompatible")
        return self


class TemporalPropertyReference(_RuleReferenceBase):
    reference_kind: Literal["temporal_property"]
    input_scope: Literal["trajectory"]
    checkpoint_scope: Literal["whole_trajectory"]
    ordering: Literal["event_sequence"]
    predicate: ImplementationRef

    @model_validator(mode="after")
    def validate_ordered_trajectory(self) -> "TemporalPropertyReference":
        if (
            self.input_scope != "trajectory"
            or self.checkpoint_scope != "whole_trajectory"
            or self.ordering != "event_sequence"
        ):
            raise ValueError("temporal property requires ordered trajectory evidence")
        return self


class AxiomRelationReference(_RuleReferenceBase):
    reference_kind: Literal["axiom_relation"]
    input_scope: Literal["answer", "terminal_state"]
    checkpoint_scope: Literal["answer", "final_state"]
    relation: ImplementationRef

    @model_validator(mode="after")
    def validate_scope_pair(self) -> "AxiomRelationReference":
        expected = {"answer": "answer", "terminal_state": "final_state"}
        if self.checkpoint_scope != expected[self.input_scope]:
            raise ValueError("axiom relation scope/checkpoint are incompatible")
        return self


class MetamorphicRelationReference(_RuleReferenceBase):
    reference_kind: Literal["metamorphic_relation"]
    input_scope: Literal["distribution"]
    checkpoint_scope: Literal["related_cases"]
    relation_scope: Literal["related_cases_or_reruns"]
    relation: ImplementationRef


RuleReference = Annotated[
    ConstraintSatisfactionReference
    | StateInvariantReference
    | TemporalPropertyReference
    | AxiomRelationReference
    | MetamorphicRelationReference,
    Field(discriminator="reference_kind"),
]


class RuleConstraintVerifier(StrictModel):
    verifier_family: Literal["rule_constraint"]
    verifier_id: SDKStr
    verifier_version: SDKStr
    reference: RuleReference

    @model_validator(mode="after")
    def validate_verifier(self) -> "RuleConstraintVerifier":
        _validate_direct_record_values(self, "rule verifier")
        _require_semver("verifier_version", self.verifier_version)
        return self


class ObjectiveScopeSpec(StrictModel):
    objective_id: SDKStr
    objective_version: SDKStr
    direction: Literal["maximize"]
    source_direction: Literal["maximize", "minimize"]
    source_to_canonical_rule: Literal["identity", "negate"]
    units: SDKStr
    feasible_set: SDKStr
    information_set: SDKStr
    horizon: SDKStr
    environment_condition: SDKStr
    opponent_condition: SDKStr
    stochastic_expectation: SDKStr
    validity_domain: ValidityDomainSpec

    @model_validator(mode="after")
    def validate_scope(self) -> "ObjectiveScopeSpec":
        _validate_direct_record_values(self, "objective scope")
        _require_semver("objective_version", self.objective_version)
        expected = "identity" if self.source_direction == "maximize" else "negate"
        if self.source_to_canonical_rule != expected:
            raise ValueError(
                "source_to_canonical_rule must be identity for native maximize and "
                "negate for native minimize under canonical maximize"
            )
        return self


class _ObjectiveReferenceBase(_VersionedReference):
    scope: ObjectiveScopeSpec
    proof_type: SDKStr


class ObjectiveExactReference(_ObjectiveReferenceBase):
    reference_kind: Literal["exact_value"]


class ObjectiveLowerBoundReference(_ObjectiveReferenceBase):
    reference_kind: Literal["lower_bound"]


class ObjectiveUpperBoundReference(_ObjectiveReferenceBase):
    reference_kind: Literal["upper_bound"]


class ObjectiveBaselineReference(_ObjectiveReferenceBase):
    reference_kind: Literal["comparison_baseline"]
    comparison_id: SDKStr
    comparison_version: SDKStr

    @model_validator(mode="after")
    def validate_baseline(self) -> "ObjectiveBaselineReference":
        _require_non_empty("comparison_id", self.comparison_id)
        _require_semver("comparison_version", self.comparison_version)
        return self


class ObjectiveSupportMinReference(_ObjectiveReferenceBase):
    reference_kind: Literal["support_min"]


class ObjectiveSupportMaxReference(_ObjectiveReferenceBase):
    reference_kind: Literal["support_max"]


class ObjectiveValueReference(_ObjectiveReferenceBase):
    reference_kind: Literal["value_only"]


class ObjectiveExactClaim(StrictModel):
    claim_kind: Literal["exact"]
    certification_rule: Literal["exact_reference_match"]
    exact: ObjectiveExactReference


class ObjectiveBoundClaim(StrictModel):
    claim_kind: Literal["bound"]
    bound_status: Literal[
        "exact_solved", "epsilon_solved", "bracketed", "lower_bound_only"
    ]
    certification_rule: Literal[
        "computed_bound_gap_eq_zero",
        "computed_bound_gap_lte_epsilon",
        "certified_lower_le_optimum_le_upper",
        "feasible_witness_lower_bounds_optimum",
    ]
    lower_bound: ObjectiveLowerBoundReference
    upper_bound: ObjectiveUpperBoundReference | None = None
    epsilon: SDKFloat | None = Field(default=None, gt=0)
    epsilon_units: SDKStr | None = None

    @model_validator(mode="after")
    def validate_bound_claim(self) -> "ObjectiveBoundClaim":
        expected_rule = {
            "exact_solved": "computed_bound_gap_eq_zero",
            "epsilon_solved": "computed_bound_gap_lte_epsilon",
            "bracketed": "certified_lower_le_optimum_le_upper",
            "lower_bound_only": "feasible_witness_lower_bounds_optimum",
        }[self.bound_status]
        if self.certification_rule != expected_rule:
            raise ValueError("certification_rule must match bound_status")
        needs_upper = self.bound_status in {
            "exact_solved",
            "epsilon_solved",
            "bracketed",
        }
        if needs_upper and self.upper_bound is None:
            raise ValueError(f"{self.bound_status} requires an upper bound")
        if self.bound_status == "lower_bound_only" and self.upper_bound is not None:
            raise ValueError("lower_bound_only cannot declare an upper bound")
        if self.bound_status == "epsilon_solved":
            if self.epsilon is None or self.epsilon_units is None:
                raise ValueError("epsilon_solved requires epsilon and epsilon_units")
            _require_non_empty("epsilon_units", self.epsilon_units)
            if self.epsilon_units != self.lower_bound.scope.units:
                raise ValueError("epsilon_units must match objective scope units")
        elif self.epsilon is not None or self.epsilon_units is not None:
            raise ValueError("epsilon fields are only legal for epsilon_solved")
        return self


class ObjectiveBaselineClaim(StrictModel):
    claim_kind: Literal["baseline"]
    certification_rule: Literal["comparison_against_pinned_baseline"]
    baseline: ObjectiveBaselineReference


class ObjectiveSupportClaim(StrictModel):
    claim_kind: Literal["support"]
    certification_rule: Literal["support_min_lte_outcome_lte_support_max"]
    support_min: ObjectiveSupportMinReference
    support_max: ObjectiveSupportMaxReference


class ObjectiveValueOnlyClaim(StrictModel):
    claim_kind: Literal["value_only"]
    certification_rule: Literal["no_optimality_or_comparison_claim"]
    value: ObjectiveValueReference


ObjectiveClaim = Annotated[
    ObjectiveExactClaim
    | ObjectiveBoundClaim
    | ObjectiveBaselineClaim
    | ObjectiveSupportClaim
    | ObjectiveValueOnlyClaim,
    Field(discriminator="claim_kind"),
]


class ObjectiveReferenceVerifier(StrictModel):
    verifier_family: Literal["objective_reference"]
    verifier_id: SDKStr
    verifier_version: SDKStr
    scope: ObjectiveScopeSpec
    claim: ObjectiveClaim

    @model_validator(mode="after")
    def validate_verifier(self) -> "ObjectiveReferenceVerifier":
        _validate_direct_record_values(self, "objective verifier")
        _require_semver("verifier_version", self.verifier_version)
        if isinstance(self.claim, ObjectiveExactClaim):
            references: tuple[_ObjectiveReferenceBase, ...] = (self.claim.exact,)
        elif isinstance(self.claim, ObjectiveBoundClaim):
            references = (self.claim.lower_bound,) + (
                (self.claim.upper_bound,) if self.claim.upper_bound is not None else ()
            )
        elif isinstance(self.claim, ObjectiveBaselineClaim):
            references = (self.claim.baseline,)
        elif isinstance(self.claim, ObjectiveSupportClaim):
            references = (self.claim.support_min, self.claim.support_max)
        else:
            references = (self.claim.value,)
        identities = [
            (reference.reference_id, reference.reference_version)
            for reference in references
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("objective reference identities must be unique")
        if any(reference.scope != self.scope for reference in references):
            raise ValueError("every objective reference scope must match exactly")
        return self


class _ComparativeReferenceBase(_VersionedReference):
    input_scope: EstimandInputScope
    comparator: ImplementationRef
    population_schema_ref: SDKStr
    role_precondition: SDKStr
    matching_precondition: SDKStr
    units: SDKStr
    direction: Literal["maximize", "minimize"]
    validity_domain: ValidityDomainSpec
    provenance_schema_ref: SDKStr


class BaselineDeltaReference(_ComparativeReferenceBase):
    reference_kind: Literal["baseline_delta"]


class PairedComparisonReference(_ComparativeReferenceBase):
    reference_kind: Literal["paired_comparison"]


class HeadToHeadReference(_ComparativeReferenceBase):
    reference_kind: Literal["head_to_head"]


class HumanReferenceComparison(_ComparativeReferenceBase):
    reference_kind: Literal["human_reference"]


class FieldRatingReference(_ComparativeReferenceBase):
    reference_kind: Literal["field_rating"]


ComparativeReference = Annotated[
    BaselineDeltaReference
    | PairedComparisonReference
    | HeadToHeadReference
    | HumanReferenceComparison
    | FieldRatingReference,
    Field(discriminator="reference_kind"),
]


class ComparativeReferenceVerifier(StrictModel):
    verifier_family: Literal["comparative"]
    verifier_id: SDKStr
    verifier_version: SDKStr
    reference: ComparativeReference

    @model_validator(mode="after")
    def validate_verifier(self) -> "ComparativeReferenceVerifier":
        _validate_direct_record_values(self, "comparative verifier")
        _require_semver("verifier_version", self.verifier_version)
        return self


class RaterInputSpec(StrictModel):
    input_scope: Literal["answer", "outcome", "trajectory"]
    visibility: Literal["public", "evaluator_authorized"]
    projection: ImplementationRef
    renderer: ImplementationRef
    rendered_schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_input(self) -> "RaterInputSpec":
        _validate_direct_record_values(self, "rater input")
        return self


class EvaluatorAgentRaterSource(StrictModel):
    source_kind: Literal["evaluator_agent"]
    evaluator_protocol_id: SDKStr
    evaluator_protocol_version: SDKStr
    adapter_contract: ImplementationRef

    @model_validator(mode="after")
    def validate_source(self) -> "EvaluatorAgentRaterSource":
        _validate_direct_record_values(self, "evaluator-agent source")
        _require_semver("evaluator_protocol_version", self.evaluator_protocol_version)
        return self


class ImportedHumanRaterSource(StrictModel):
    source_kind: Literal["imported_human"]
    evidence_source: ReferenceSource
    import_validator: ImplementationRef
    evidence_schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_source(self) -> "ImportedHumanRaterSource":
        _validate_direct_record_values(self, "imported-human source")
        return self


RaterSource = Annotated[
    EvaluatorAgentRaterSource | ImportedHumanRaterSource,
    Field(discriminator="source_kind"),
]


class BlindOrderSpec(StrictModel):
    algorithm: ImplementationRef
    seed_input: Literal["evaluation_seed"]
    counterbalance_input: Literal["counterbalance_label"]
    position_schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_order(self) -> "BlindOrderSpec":
        _validate_direct_record_values(self, "blind order")
        return self


class RaterJudgeVerifier(StrictModel):
    verifier_family: Literal["rater_judge"]
    verifier_id: SDKStr
    verifier_version: SDKStr
    protocol_id: SDKStr
    protocol_version: SDKStr
    rubric_ref: ArtifactRef
    prompt_ref: ArtifactRef
    input: RaterInputSpec
    rater_source: RaterSource
    blind_order: BlindOrderSpec
    calibration_refs: tuple[ArtifactRef, ...]
    provenance_refs: tuple[ArtifactRef, ...]
    result_schema_ref: SDKStr
    valid_tie_schema_ref: SDKStr
    disagreement_schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_verifier(self) -> "RaterJudgeVerifier":
        _validate_direct_record_values(self, "rater verifier")
        _require_semver("verifier_version", self.verifier_version)
        _require_semver("protocol_version", self.protocol_version)
        _validate_complete_artifact(self.rubric_ref, "rubric_ref")
        _validate_complete_artifact(self.prompt_ref, "prompt_ref")
        _validate_artifact_tuple(
            self.calibration_refs, "calibration_refs", required=True
        )
        _validate_artifact_tuple(self.provenance_refs, "provenance_refs", required=True)
        return self


class RaterScoreResult(StrictModel):
    result_kind: Literal["score"]
    value: SDKFloat
    schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_result(self) -> "RaterScoreResult":
        _validate_direct_record_values(self, "rater score result")
        return self


class RaterTieResult(StrictModel):
    result_kind: Literal["valid_tie"]
    schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_result(self) -> "RaterTieResult":
        _validate_direct_record_values(self, "rater tie result")
        return self


RaterResult = Annotated[
    RaterScoreResult | RaterTieResult,
    Field(discriminator="result_kind"),
]


VerifierSpec = Annotated[
    CanonicalReferenceVerifier
    | RuleConstraintVerifier
    | ObjectiveReferenceVerifier
    | ComparativeReferenceVerifier
    | RaterJudgeVerifier,
    Field(discriminator="verifier_family"),
]


class MeasurementLeafSpec(StrictModel):
    leaf_id: SDKStr
    leaf_version: SDKStr
    composition_kind: Literal["leaf"]
    estimand: EstimandSpec
    verifier: VerifierSpec
    allowed_evaluation_classes: tuple[EvaluationClass, ...]
    scorer: ImplementationRef

    @model_validator(mode="after")
    def validate_leaf(self) -> "MeasurementLeafSpec":
        _validate_direct_record_values(self, "measurement leaf")
        _require_semver("leaf_version", self.leaf_version)
        classes = self.allowed_evaluation_classes
        canonical_order = (
            "deterministic",
            "stochastic_estimator",
            "judge_dependent",
        )
        if not classes:
            raise ValueError("allowed_evaluation_classes must be non-empty")
        indices = [canonical_order.index(value) for value in classes]
        if indices != sorted(set(indices)):
            raise ValueError(
                "allowed_evaluation_classes must be unique and canonically ordered"
            )
        if self.verifier.verifier_family == "rater_judge":
            if classes != ("judge_dependent",):
                raise ValueError(
                    "rater_judge allows exactly judge_dependent evaluation"
                )
        elif "judge_dependent" in classes:
            raise ValueError(
                "non-rater measurement leaves cannot allow judge_dependent"
            )
        estimand = self.estimand
        verifier = self.verifier
        if isinstance(verifier, CanonicalReferenceVerifier):
            if (
                estimand.input_scope != verifier.reference.input_scope
                or estimand.units != verifier.reference.units
            ):
                raise ValueError(
                    "canonical verifier scope and units must match the estimand"
                )
        elif isinstance(verifier, RuleConstraintVerifier):
            if estimand.input_scope != verifier.reference.input_scope:
                raise ValueError("rule verifier scope must match the estimand")
        elif isinstance(verifier, ObjectiveReferenceVerifier):
            if (
                estimand.direction != verifier.scope.direction
                or estimand.units != verifier.scope.units
                or estimand.validity_domain != verifier.scope.validity_domain
            ):
                raise ValueError(
                    "objective direction, units, and validity domain must match "
                    "the estimand"
                )
        elif isinstance(verifier, ComparativeReferenceVerifier):
            reference = verifier.reference
            if (
                estimand.input_scope != reference.input_scope
                or estimand.direction != reference.direction
                or estimand.units != reference.units
                or estimand.validity_domain != reference.validity_domain
            ):
                raise ValueError(
                    "comparative scope, direction, units, and validity domain "
                    "must match the estimand"
                )
        else:
            rater_scope = (
                "terminal_state"
                if verifier.input.input_scope == "outcome"
                else verifier.input.input_scope
            )
            if estimand.input_scope != rater_scope:
                raise ValueError("rater input scope must match the estimand scope")
        return self


class OptimizationBoundReference(StrictModel):
    kind: Literal["optimum_lower_bound", "optimum_upper_bound"]
    value: SDKFloat
    objective_id: SDKStr
    objective_version: SDKStr
    units: SDKStr
    direction: Literal["maximize", "minimize"]
    feasible_set: SDKStr
    information_set: SDKStr
    horizon: SDKStr
    opponent_condition: SDKStr
    proof_type: SDKStr
    implementation: ImplementationRef
    validity_domain: SDKStr


class ComparisonBaselineReference(StrictModel):
    kind: Literal["comparison_baseline"]
    value: SDKFloat
    comparison_id: SDKStr
    comparison_version: SDKStr
    units: SDKStr
    direction: Literal["maximize", "minimize"]
    provenance: JSONObject
    applicability: SDKStr
    implementation: ImplementationRef


class OutcomeSupportReference(StrictModel):
    kind: Literal["outcome_support_min", "outcome_support_max"]
    value: SDKFloat
    objective_id: SDKStr
    objective_version: SDKStr
    units: SDKStr
    direction: Literal["maximize", "minimize"]
    feasible_set: SDKStr
    information_set: SDKStr
    horizon: SDKStr
    opponent_condition: SDKStr
    proof_type: SDKStr
    implementation: ImplementationRef
    validity_domain: SDKStr
    applicability: SDKStr


ReferenceValue = Annotated[
    OptimizationBoundReference | ComparisonBaselineReference | OutcomeSupportReference,
    Field(discriminator="kind"),
]


class ValidityReport(StrictModel):
    status: Literal["valid", "invalid"]
    reasons: tuple[SDKStr, ...] = ()


class ScoreEnvelope(StrictModel):
    status: Literal["ok", "invalid_measurement"]
    measurement_kind: SDKStr
    direction: SDKStr
    bound_status: SDKStr | None
    primary: MetricValue | None
    metrics: ImmutableMapping[MetricValue]
    utility_by_seat: ImmutableMapping[SDKFloat]
    capture_by_seat: ImmutableMapping[SDKFloat]
    references: ImmutableMapping[ReferenceValue]
    outcome: JSONObject
    validity: ValidityReport
    scorer: ImplementationRef
    oracle: ImplementationRef | None
    evidence_refs: tuple[SDKStr, ...]


class EpisodeExecutionResult(StrictModel):
    status: Literal["ok", "invalid_measurement"]
    terminal: TerminalResult | None
    outcome: FamilyOutcome | None
    evidence: SealedEvidenceView
    failure_class: SDKStr | None = None
    failure_message: SDKStr | None = None


class EvaluationReceipt(StrictModel):
    status: Literal["ok", "invalid_measurement"]
    run_plan_id: SDKStr
    cell_id: SDKStr
    episode_id: SDKStr
    episode_attempt_id: SDKStr
    cluster_id: SDKStr
    run_plan_sha256: SDKStr
    case_sha256: SDKStr
    agent_config_sha256: SDKStr
    implementations: tuple[ImplementationRef, ...]
    evidence: SealedEvidenceView
    score: ScoreEnvelope | None
    failure_class: SDKStr | None = None
    failure_message: SDKStr | None = None
    inclusion_status: Literal["included", "excluded"]
    observability_limits: tuple[SDKStr, ...] = ()
    replay_level: Literal["deterministic", "score_only", "none"]
    trajectory_refs: ImmutableMapping[ArtifactRef] = Field(default_factory=dict)
    receipt_sha256: SDKStr | None = None


class PinnedPluginRef(StrictModel):
    """Exact registry reference plus a caller-supplied content pin."""

    plugin: PluginRef
    implementation: ImplementationRef

    @model_validator(mode="after")
    def validate_matching_identity(self) -> "PinnedPluginRef":
        if (
            self.implementation.implementation_id != self.plugin.plugin_id
            or self.implementation.version != self.plugin.plugin_version
        ):
            raise ValueError(
                "implementation ID/version must match the plugin reference"
            )
        return self


class UpstreamSourceRef(StrictModel):
    repository_url: SDKStr
    commit: SDKStr = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    release: SDKStr | None = None
    license_spdx: SDKStr
    source_paths: tuple[SDKStr, ...]
    patchset_sha256: SDKStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    materialized_artifact_hashes: ImmutableMapping[SHA256] = Field(default_factory=dict)
    upstream_scorer_ref: SDKStr | None = None
    parity_report_sha256: SDKStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_source(self) -> "UpstreamSourceRef":
        parsed_url = urlparse(self.repository_url)
        if (
            parsed_url.scheme not in {"http", "https", "ssh", "git"}
            or not parsed_url.netloc
        ):
            raise ValueError("repository_url must be an absolute repository URL")
        if not self.license_spdx.strip():
            raise ValueError("repository_url and license_spdx must be non-empty")
        if not self.source_paths or any(not path.strip() for path in self.source_paths):
            raise ValueError("source_paths must contain non-empty paths")
        if len(self.source_paths) != len(set(self.source_paths)):
            raise ValueError("source_paths must be unique")
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in self.materialized_artifact_hashes.values()
        ):
            raise ValueError("materialized artifact hashes must be SHA-256 values")
        return self


class CapabilityDeclaration(StrictModel):
    schedule_control: Literal["runner", "upstream", "opaque"]
    observation_visibility: Literal["full", "partial", "opaque"]
    call_observability: Literal["full", "logical_only", "opaque"]
    state_replay: Literal["deterministic", "score_only", "none"]
    score_parity: Literal["exact", "component", "statistical", "none"]
    privacy_enforcement: Literal["runner", "upstream", "unverified"]
    trainability: Literal["per_seat", "joint_only", "none"]


class RoleSpec(StrictModel):
    role_id: SDKStr
    testable: SDKBool
    trainable: SDKBool
    controlled_profile_ids: tuple[SDKStr, ...] = ()

    @model_validator(mode="after")
    def validate_role(self) -> "RoleSpec":
        if not self.role_id.strip():
            raise ValueError("role_id must be non-empty")
        if len(self.controlled_profile_ids) != len(set(self.controlled_profile_ids)):
            raise ValueError("controlled_profile_ids must be unique")
        if any(not value.strip() for value in self.controlled_profile_ids):
            raise ValueError("controlled_profile_ids must be non-empty")
        return self


class _ScopedReferenceContract(StrictModel):
    objective_id: SDKStr
    objective_version: SDKStr
    units: SDKStr
    direction: Literal["maximize", "minimize"]
    feasible_set: SDKStr
    information_set: SDKStr
    horizon: SDKStr
    opponent_condition: SDKStr
    stochastic_expectation: SDKStr
    proof_type: SDKStr
    implementation: ImplementationRef
    validity_domain: SDKStr
    applicability: SDKStr

    @model_validator(mode="after")
    def validate_scope(self) -> "_ScopedReferenceContract":
        for label, value in (
            ("objective_id", self.objective_id),
            ("units", self.units),
            ("feasible_set", self.feasible_set),
            ("information_set", self.information_set),
            ("horizon", self.horizon),
            ("opponent_condition", self.opponent_condition),
            ("stochastic_expectation", self.stochastic_expectation),
            ("proof_type", self.proof_type),
            ("validity_domain", self.validity_domain),
            ("applicability", self.applicability),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-empty")
        _require_exact_pin("objective_version", self.objective_version)
        _validate_implementation_pin(self.implementation, "reference")
        return self


class OptimizationReferenceContract(_ScopedReferenceContract):
    """Pre-outcome optimum witness/certificate contract; never an observed value."""

    kind: Literal["optimum_lower_bound", "optimum_upper_bound"]


class ComparisonBaselineContract(_ScopedReferenceContract):
    """Pre-outcome executable scientific comparison contract."""

    kind: Literal["comparison_baseline"]
    comparison_id: SDKStr
    comparison_version: SDKStr
    provenance: JSONObject

    @model_validator(mode="after")
    def validate_comparison(self) -> "ComparisonBaselineContract":
        if not self.comparison_id.strip():
            raise ValueError("comparison identity must be non-empty")
        _require_exact_pin("comparison_version", self.comparison_version)
        return self


class OutcomeSupportContract(_ScopedReferenceContract):
    """Pre-outcome support claim applying to every admissible realized outcome."""

    kind: Literal["outcome_support_min", "outcome_support_max"]


PreOutcomeReferenceContract = Annotated[
    OptimizationReferenceContract | ComparisonBaselineContract | OutcomeSupportContract,
    Field(discriminator="kind"),
]


class _MeasurementBase(StrictModel):
    estimand_id: SDKStr
    direction: Literal["maximize", "minimize"]
    primary_metric_id: SDKStr
    verifier_plugin_id: SDKStr
    verifier_semantics_id: SDKStr
    verifier_semantics_version: SDKStr
    oracle: ImplementationRef | None = None

    @model_validator(mode="after")
    def validate_common_measurement(self) -> "_MeasurementBase":
        for label, value in (
            ("estimand_id", self.estimand_id),
            ("primary_metric_id", self.primary_metric_id),
            ("verifier_plugin_id", self.verifier_plugin_id),
            ("verifier_semantics_id", self.verifier_semantics_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-empty")
        _require_exact_pin(
            "verifier_semantics_version", self.verifier_semantics_version
        )
        if self.oracle is not None:
            _validate_implementation_pin(self.oracle, "oracle")
        return self


class PropertyAnswerMeasurementSpec(_MeasurementBase):
    measurement_kind: Literal["property_or_answer"]
    property_definition_id: SDKStr
    property_definition_version: SDKStr
    answer_schema_ref: SDKStr

    @model_validator(mode="after")
    def validate_property_contract(self) -> "PropertyAnswerMeasurementSpec":
        if (
            not self.property_definition_id.strip()
            or not self.answer_schema_ref.strip()
        ):
            raise ValueError("property definition and answer schema must be non-empty")
        _require_exact_pin(
            "property_definition_version", self.property_definition_version
        )
        return self


class ExactSolvedRule(StrictModel):
    bound_status: Literal["exact_solved"] = "exact_solved"
    certification_rule: Literal["computed_bound_gap_eq_zero"]


class EpsilonSolvedRule(StrictModel):
    bound_status: Literal["epsilon_solved"] = "epsilon_solved"
    certification_rule: Literal["computed_bound_gap_lte_epsilon"]
    epsilon: SDKFloat = Field(gt=0)
    epsilon_units: SDKStr

    @model_validator(mode="after")
    def validate_epsilon_units(self) -> "EpsilonSolvedRule":
        if not self.epsilon_units.strip():
            raise ValueError("epsilon_units must be non-empty")
        return self


class BracketedRule(StrictModel):
    bound_status: Literal["bracketed"] = "bracketed"
    certification_rule: Literal["certified_lower_le_optimum_le_upper"]


class LowerBoundOnlyRule(StrictModel):
    bound_status: Literal["lower_bound_only"] = "lower_bound_only"
    certification_rule: Literal["feasible_witness_lower_bounds_optimum"]


class BaselineOnlyRule(StrictModel):
    bound_status: Literal["baseline_only"] = "baseline_only"
    certification_rule: Literal["comparison_against_pinned_baseline"]


class DescriptiveOnlyRule(StrictModel):
    bound_status: Literal["descriptive_only"] = "descriptive_only"
    certification_rule: Literal["no_optimality_or_comparison_claim"]


BoundClaimRule = Annotated[
    ExactSolvedRule
    | EpsilonSolvedRule
    | BracketedRule
    | LowerBoundOnlyRule
    | BaselineOnlyRule
    | DescriptiveOnlyRule,
    Field(discriminator="bound_status"),
]


class OptimizableOutcomeMeasurementSpec(_MeasurementBase):
    measurement_kind: Literal["optimizable_outcome"]
    direction: Literal["maximize"]
    source_direction: Literal["maximize", "minimize"]
    source_to_canonical_rule: Literal["identity", "negate"]
    objective_id: SDKStr
    objective_version: SDKStr
    units: SDKStr
    feasible_set: SDKStr
    information_set: SDKStr
    horizon: SDKStr
    opponent_condition: SDKStr
    stochastic_expectation: SDKStr
    validity_domain: SDKStr
    reference_applicability: SDKStr
    claim_rule: BoundClaimRule
    reference_contracts: ImmutableMapping[PreOutcomeReferenceContract] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_optimization_contract(self) -> "OptimizableOutcomeMeasurementSpec":
        expected_orientation_rule = (
            "identity" if self.source_direction == "maximize" else "negate"
        )
        if self.source_to_canonical_rule != expected_orientation_rule:
            raise ValueError(
                "source direction and source-to-canonical rule must be "
                "maximize/identity or minimize/negate"
            )
        for label, value in (
            ("objective_id", self.objective_id),
            ("units", self.units),
            ("feasible_set", self.feasible_set),
            ("information_set", self.information_set),
            ("horizon", self.horizon),
            ("opponent_condition", self.opponent_condition),
            ("stochastic_expectation", self.stochastic_expectation),
            ("validity_domain", self.validity_domain),
            ("reference_applicability", self.reference_applicability),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-empty")
        _require_exact_pin("objective_version", self.objective_version)
        for kind, contract in self.reference_contracts.items():
            if kind != contract.kind:
                raise ValueError("reference mapping key must match contract kind")
            expected_scope = (
                self.objective_id,
                self.objective_version,
                self.units,
                self.direction,
                self.feasible_set,
                self.information_set,
                self.horizon,
                self.opponent_condition,
                self.stochastic_expectation,
                self.validity_domain,
                self.reference_applicability,
            )
            actual_scope = (
                contract.objective_id,
                contract.objective_version,
                contract.units,
                contract.direction,
                contract.feasible_set,
                contract.information_set,
                contract.horizon,
                contract.opponent_condition,
                contract.stochastic_expectation,
                contract.validity_domain,
                contract.applicability,
            )
            if actual_scope != expected_scope:
                raise ValueError("reference scope must match the estimand contract")

        kinds = set(self.reference_contracts)
        bound_status = self.claim_rule.bound_status
        lower_upper = {"optimum_lower_bound", "optimum_upper_bound"}
        if bound_status in {"exact_solved", "epsilon_solved", "bracketed"}:
            if not lower_upper.issubset(kinds):
                raise ValueError(
                    "exact_solved, epsilon_solved, and bracketed require lower and upper bounds"
                )
        if bound_status == "lower_bound_only" and "optimum_lower_bound" not in kinds:
            raise ValueError("lower_bound_only requires optimum_lower_bound")
        if bound_status == "lower_bound_only" and "optimum_upper_bound" in kinds:
            raise ValueError("lower_bound_only cannot declare optimum_upper_bound")
        if bound_status == "baseline_only" and "comparison_baseline" not in kinds:
            raise ValueError("baseline_only requires comparison_baseline")
        if bound_status == "baseline_only" and kinds & lower_upper:
            raise ValueError("baseline_only cannot make optimality claims")
        if bound_status == "descriptive_only" and kinds & {
            "optimum_lower_bound",
            "optimum_upper_bound",
            "comparison_baseline",
        }:
            raise ValueError(
                "descriptive_only cannot make optimality/comparison claims"
            )
        support_kinds = {"outcome_support_min", "outcome_support_max"}
        if kinds & support_kinds and not support_kinds.issubset(kinds):
            raise ValueError("outcome support min/max must be declared as a pair")
        if isinstance(self.claim_rule, EpsilonSolvedRule) and (
            self.claim_rule.epsilon_units != self.units
        ):
            raise ValueError("epsilon units must match the estimand's native units")
        return self


class ComparativeMeasurementSpec(_MeasurementBase):
    measurement_kind: Literal["comparative_or_human_judged"]
    comparison_target_id: SDKStr
    comparison_protocol_id: SDKStr
    comparison_protocol_version: SDKStr
    rater_semantics_id: SDKStr
    rater_semantics_version: SDKStr
    comparison_baseline: ComparisonBaselineContract
    support_contracts: ImmutableMapping[OutcomeSupportContract] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_comparative_contract(self) -> "ComparativeMeasurementSpec":
        for label, value in (
            ("comparison_target_id", self.comparison_target_id),
            ("comparison_protocol_id", self.comparison_protocol_id),
            ("rater_semantics_id", self.rater_semantics_id),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-empty")
        _require_exact_pin(
            "comparison_protocol_version", self.comparison_protocol_version
        )
        _require_exact_pin("rater_semantics_version", self.rater_semantics_version)
        for kind, contract in self.support_contracts.items():
            if kind != contract.kind:
                raise ValueError("support mapping key must match contract kind")
        support_kinds = set(self.support_contracts)
        expected = {"outcome_support_min", "outcome_support_max"}
        if support_kinds and support_kinds != expected:
            raise ValueError("outcome support min/max must be declared as a pair")
        return self


MeasurementSpec = Annotated[
    PropertyAnswerMeasurementSpec
    | OptimizableOutcomeMeasurementSpec
    | ComparativeMeasurementSpec,
    Field(discriminator="measurement_kind"),
]


class FamilyManifest(StrictModel):
    spec_version: Literal["aeread.family/0.1"] = "aeread.family/0.1"
    family_id: SDKStr
    family_version: SDKStr
    environment: PinnedPluginRef
    verifiers: tuple[PinnedPluginRef, ...]
    phase_graph: PhaseGraph
    roles: tuple[RoleSpec, ...]
    measurements: tuple[MeasurementSpec, ...]
    capabilities: CapabilityDeclaration
    generator: ImplementationRef | None = None
    upstream_source: UpstreamSourceRef | None = None
    limits: JSONObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_family(self) -> "FamilyManifest":
        if not self.family_id.strip() or not _SEMVER_PATTERN.fullmatch(
            self.family_version
        ):
            raise ValueError("family identity must be non-empty and exact-versioned")
        if not self.verifiers:
            raise ValueError("family must pin at least one verifier")
        if not self.roles or not self.measurements:
            raise ValueError("family must declare roles and measurements")
        for values, label in (
            ([item.plugin.plugin_id for item in self.verifiers], "verifier"),
            ([item.role_id for item in self.roles], "role"),
            ([item.estimand_id for item in self.measurements], "estimand"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} identifiers must be unique")
        if self.generator is not None:
            _validate_implementation_pin(self.generator, "generator")
        return self


class SeatSpec(StrictModel):
    seat_id: SDKStr
    role_id: SDKStr

    @model_validator(mode="after")
    def validate_seat(self) -> "SeatSpec":
        if not self.seat_id.strip() or not self.role_id.strip():
            raise ValueError("seat_id and role_id must be non-empty")
        return self


class CaseProvenance(StrictModel):
    source_kind: Literal["generated", "curated"]
    generator_id: SDKStr | None = None
    generator_version: SDKStr | None = None
    review_status: SDKStr
    curator_id: SDKStr | None = None
    curator_version: SDKStr | None = None
    parent_sha256: SDKStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    materialization_sha256: SDKStr | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def validate_provenance(self) -> "CaseProvenance":
        if not self.review_status.strip():
            raise ValueError("review_status is required")
        if (self.curator_id is None) != (self.curator_version is None):
            raise ValueError("curator_id and curator_version must be declared together")
        if self.source_kind == "generated":
            if self.generator_id is None or self.generator_version is None:
                raise ValueError("generated provenance requires generator ID/version")
            if not self.generator_id.strip() or not _SEMVER_PATTERN.fullmatch(
                self.generator_version
            ):
                raise ValueError("generator_id/generator_version must be exact")
        elif self.generator_id is not None or self.generator_version is not None:
            raise ValueError("curated provenance cannot claim a generator")
        if self.source_kind == "curated" and self.curator_id is None:
            raise ValueError("curated provenance requires curator identity/version")
        if self.curator_version is not None and not _SEMVER_PATTERN.fullmatch(
            self.curator_version
        ):
            raise ValueError("curator_version must be an exact semantic version")
        return self


def _case_content_basis(value: "CaseManifest") -> dict[str, object]:
    basis = value.model_dump(mode="python", exclude={"content_sha256"})
    basis["seats"] = sorted(basis["seats"], key=lambda seat: seat["seat_id"])
    basis["terminal_reasons"] = sorted(basis["terminal_reasons"])
    return basis


def case_content_sha256(value: "CaseManifest") -> str:
    """Compute a case digest over semantic content, excluding its digest field."""

    from .base import content_sha256

    return content_sha256(_case_content_basis(value))


class CaseManifest(StrictModel):
    spec_version: Literal["aeread.case/0.1"] = "aeread.case/0.1"
    # These three name the case wherever it goes: a run directory, a dataset
    # row, an export. See ExportableId for why a colon is not allowed.
    case_id: ExportableId
    family_id: ExportableId
    family_version: SDKStr
    split: ExportableId
    world_seed: SDKInt = Field(ge=0)
    seats: tuple[SeatSpec, ...]
    max_logical_actions: SDKInt = Field(ge=1)
    terminal_reasons: tuple[SDKStr, ...]
    visibility_policy: SDKStr
    payload: JSONObject
    provenance: CaseProvenance
    content_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_case(self, info: ValidationInfo) -> "CaseManifest":
        if any(
            not value.strip()
            for value in (
                self.case_id,
                self.family_id,
                self.split,
                self.visibility_policy,
            )
        ) or not _SEMVER_PATTERN.fullmatch(self.family_version):
            raise ValueError(
                "case identity, split, policy, and family version are required"
            )
        if not self.seats or not self.terminal_reasons:
            raise ValueError("case must declare seats and terminal reasons")
        seat_ids = [seat.seat_id for seat in self.seats]
        if len(seat_ids) != len(set(seat_ids)):
            raise ValueError("seat_id values must be unique")
        if len(self.terminal_reasons) != len(set(self.terminal_reasons)):
            raise ValueError("terminal_reasons must be unique")
        if any(not reason.strip() for reason in self.terminal_reasons):
            raise ValueError("terminal_reasons must contain non-empty identifiers")
        if info.context and info.context.get("skip_case_hash_validation"):
            return self
        if self.content_sha256 != case_content_sha256(self):
            raise ValueError("content_sha256 does not match canonical case content")
        return self

    @classmethod
    def from_content(cls, **data: object) -> "CaseManifest":
        """Validate case content and add its required canonical digest."""

        if "content_sha256" in data:
            raise ValueError("from_content computes content_sha256")
        candidate = cls.model_validate(
            {**data, "content_sha256": "0" * 64},
            context={"skip_case_hash_validation": True},
        )
        complete = candidate.model_dump(mode="python")
        complete["content_sha256"] = case_content_sha256(candidate)
        return cls.model_validate(complete)


class EvaluationBlock(StrictModel):
    block_id: ExportableId
    #: Left a free string on purpose: three sources propose three different
    #: vocabularies for this field, so locking one is a contract decision
    #: rather than a kernel decision. See docs/pr7_contract_decision_request.md.
    kind: SDKStr
    estimand_id: SDKStr
    subject_roles: tuple[SDKStr, ...]
    controlled_profile_by_role: ImmutableMapping[SDKStr]
    repetitions: SDKInt = Field(ge=1)
    rollout_seeds: tuple[Annotated[SDKInt, Field(ge=0)], ...]

    @model_validator(mode="after")
    def validate_block(self) -> "EvaluationBlock":
        if (
            not self.block_id.strip()
            or not self.kind.strip()
            or not self.estimand_id.strip()
        ):
            raise ValueError("block_id, kind, and estimand_id must be non-empty")
        if not self.subject_roles or not self.rollout_seeds:
            raise ValueError("blocks require subject roles and rollout seeds")
        if len(self.subject_roles) != len(set(self.subject_roles)):
            raise ValueError("subject_roles must be unique")
        if len(self.rollout_seeds) != len(set(self.rollout_seeds)):
            raise ValueError("rollout_seeds must be unique")
        if any(not role.strip() for role in self.subject_roles) or any(
            not role.strip() or not profile.strip()
            for role, profile in self.controlled_profile_by_role.items()
        ):
            raise ValueError("block role and profile identifiers must be non-empty")
        return self


class ClusterSpec(StrictModel):
    cluster_level: SDKStr
    identity_fields: tuple[SDKStr, ...]
    paired_fields: tuple[SDKStr, ...] = ()
    parent_field: SDKStr | None = None
    panel_mode: Literal["fixed_panel", "sampled_panel"]

    @model_validator(mode="after")
    def validate_cluster(self) -> "ClusterSpec":
        if not self.cluster_level.strip() or not self.identity_fields:
            raise ValueError("cluster level and identity fields are required")
        if len(self.identity_fields) != len(set(self.identity_fields)):
            raise ValueError("cluster identity_fields must be unique")
        if len(self.paired_fields) != len(set(self.paired_fields)):
            raise ValueError("cluster paired_fields must be unique")
        if any(not field.strip() for field in self.identity_fields) or any(
            not field.strip() for field in self.paired_fields
        ):
            raise ValueError("cluster fields must be non-empty")
        if self.parent_field is not None and not self.parent_field.strip():
            raise ValueError("cluster parent_field must be non-empty")
        return self


class SuiteManifest(StrictModel):
    spec_version: Literal["aeread.suite/0.1"] = "aeread.suite/0.1"
    suite_id: ExportableId
    suite_version: SDKStr
    case_ids: tuple[ExportableId, ...]
    blocks: tuple[EvaluationBlock, ...]
    cluster_by_estimand: ImmutableMapping[ClusterSpec]
    missingness_policy: SDKStr
    aggregation_group_fields: tuple[SDKStr, ...]
    cross_family_scalar: Literal["disabled"] = "disabled"

    @model_validator(mode="after")
    def validate_suite(self) -> "SuiteManifest":
        if (
            not self.suite_id.strip()
            or not _SEMVER_PATTERN.fullmatch(self.suite_version)
            or not self.missingness_policy.strip()
        ):
            raise ValueError("suite identity/version/missingness policy are required")
        if not self.case_ids or not self.blocks:
            raise ValueError("suite requires cases and evaluation blocks")
        if not self.cluster_by_estimand or any(
            not estimand_id.strip() for estimand_id in self.cluster_by_estimand
        ):
            raise ValueError("suite requires estimand-keyed cluster declarations")
        for values, label in (
            (self.case_ids, "case_id"),
            (tuple(block.block_id for block in self.blocks), "block_id"),
            (self.aggregation_group_fields, "aggregation_group_fields"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} values must be unique")
            if any(not value.strip() for value in values):
                raise ValueError(f"{label} values must be non-empty")
        return self


class ProviderPin(StrictModel):
    provider_id: SDKStr
    api_version: SDKStr

    @model_validator(mode="after")
    def validate_provider(self) -> "ProviderPin":
        if not self.provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        _require_exact_pin("api_version", self.api_version)
        return self


class ModelPin(StrictModel):
    model_id: SDKStr
    revision: SDKStr

    @model_validator(mode="after")
    def validate_model_pin(self) -> "ModelPin":
        if not self.model_id.strip():
            raise ValueError("model_id must be non-empty")
        _require_exact_pin("revision", self.revision)
        return self


class RuntimePin(StrictModel):
    implementation: ImplementationRef
    config: JSONObject = Field(default_factory=dict)


class SamplingPin(StrictModel):
    schema_id: SDKStr
    schema_version: SDKStr
    content: JSONObject

    @model_validator(mode="after")
    def validate_sampling(self) -> "SamplingPin":
        if not self.schema_id.strip():
            raise ValueError("sampling schema_id must be non-empty")
        _require_exact_pin("sampling schema_version", self.schema_version)
        return self


class MemoryPin(StrictModel):
    mode: Literal["none", "ephemeral", "persistent"]
    policy: ImplementationRef | None = None
    config: JSONObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_memory(self) -> "MemoryPin":
        if self.mode == "none":
            if self.policy is not None or self.config:
                raise ValueError("memory mode none cannot declare policy/config")
        elif self.policy is None:
            raise ValueError("enabled memory requires a pinned memory policy")
        return self


class ReasoningCondition(StrictModel):
    """A versioned reasoning setting, treated as an experimental condition.

    "Reasoning model" is not a stable description of a run: the same model can
    be served on provider defaults, at a named effort, under a token budget, or
    with no exposed control at all, and those change the policy, the cost, and
    what is comparable with what. Every evaluated cell therefore binds one of
    these, and reports compare complete agent configurations rather than a bare
    model name.

    Two distinctions the record refuses to blur: `provider_default` is not
    "off", and a provider exposing no disable switch is `unsupported_control`
    rather than a control arm. Private chain-of-thought is never required or
    retained; a provider summary or a task-visible decision record is an
    observed output that must be declared to be kept.
    """

    reasoning_condition_id: SDKStr
    mode: Literal["provider_default", "enabled", "disabled", "unsupported_control"]
    reasoning_effort: (
        Literal["low", "medium", "high", "provider_specific"] | None
    ) = None
    reasoning_token_budget: SDKInt | None = Field(default=None, ge=0)
    output_token_budget: SDKInt = Field(ge=1)
    total_completion_budget: SDKInt | None = Field(default=None, ge=1)
    provider_parameters: JSONObject = Field(default_factory=dict)
    rationale_visibility: Literal[
        "none", "provider_summary", "task_visible_decision_record"
    ] = "none"
    rationale_protocol_id: SDKStr | None = None
    reasoning_content_retained: Literal[False] = False

    @model_validator(mode="after")
    def validate_reasoning_condition(self) -> "ReasoningCondition":
        if not self.reasoning_condition_id.strip():
            raise ValueError("reasoning_condition_id must be non-empty")
        if self.mode != "enabled":
            # Only `enabled` means "we set this deliberately". A default is not
            # a setting, and a provider with no switch cannot have been tuned;
            # letting either carry an effort or a budget would describe a
            # configuration that was never requested.
            if self.reasoning_effort is not None:
                raise ValueError(
                    f"mode {self.mode!r} cannot also declare a reasoning effort"
                )
            if self.reasoning_token_budget:
                raise ValueError(
                    f"mode {self.mode!r} cannot also declare a reasoning budget"
                )
        # W10: the same setting must not arrive through the side channel.
        if self.mode in {"disabled", "unsupported_control"}:
            smuggled = sorted(
                key
                for key in self.provider_parameters
                if "reasoning" in key.lower() or "thinking" in key.lower()
            )
            if smuggled:
                raise ValueError(
                    f"mode {self.mode!r} declares no reasoning, but "
                    f"provider_parameters carries {smuggled}"
                )
        if self.total_completion_budget is not None:
            declared = self.output_token_budget + (self.reasoning_token_budget or 0)
            if self.total_completion_budget < declared:
                raise ValueError(
                    "total_completion_budget is smaller than the output and "
                    "reasoning budgets it is meant to contain"
                )
        visible = self.rationale_visibility != "none"
        if visible != (self.rationale_protocol_id is not None):
            raise ValueError(
                "a visible rationale needs a declared protocol, and a declared "
                "protocol needs a visibility other than 'none'"
            )
        return self


class AgentExecutionConfig(StrictModel):
    """Fully materialized provider/harness configuration delivered to an adapter."""

    provider: ProviderPin
    model: ModelPin
    harness: ImplementationRef
    runtime: RuntimePin
    prompt: SDKStr
    prompt_sha256: SHA256
    sampling: SamplingPin
    tools: tuple[ImplementationRef, ...]
    memory: MemoryPin
    attempt_budget: AttemptBudget
    retry_policy: RetryPolicy
    reasoning: ReasoningCondition

    @model_validator(mode="after")
    def validate_execution_config(self) -> "AgentExecutionConfig":
        if not self.prompt:
            raise ValueError("prompt content must be non-empty")
        if self.prompt_sha256 != content_sha256(self.prompt):
            raise ValueError("prompt hash must match canonical prompt content")
        tool_ids = [(tool.implementation_id, tool.version) for tool in self.tools]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("tool implementation identities must be unique")
        component_refs = (self.harness, self.runtime.implementation, *self.tools)
        if self.memory.policy is not None:
            component_refs = (*component_refs, self.memory.policy)
        for implementation in component_refs:
            _validate_implementation_pin(implementation, "agent component")
        length_limit = self.retry_policy.length_retry_output_tokens
        if "length" in self.retry_policy.retryable_conditions and (
            length_limit is None
            or length_limit <= self.attempt_budget.output_token_limit
        ):
            raise ValueError("length retry requires a larger output-token limit")
        return self


class AgentProfile(StrictModel):
    spec_version: Literal["aeread.agent_profile/0.1"] = "aeread.agent_profile/0.1"
    profile_id: SDKStr
    profile_version: SDKStr
    adapter: PinnedPluginRef
    call_observability: CallObservability
    execution_config: AgentExecutionConfig

    @model_validator(mode="after")
    def validate_agent_profile(self) -> "AgentProfile":
        required = (self.profile_id,)
        if any(
            not value.strip() for value in required
        ) or not _SEMVER_PATTERN.fullmatch(self.profile_version):
            raise ValueError("agent identity and configuration pins must be non-empty")
        return self


class AgentRequest(StrictModel):
    logical_action_id: SDKStr
    phase_id: SDKStr
    slot: DecisionSlot
    observation: ObservationEnvelope
    context: AgentContext
    profile: AgentProfile
    agent_profile_sha256: SHA256
    execution_config_sha256: SHA256
    budget: AttemptBudget

    @property
    def execution_config(self) -> AgentExecutionConfig:
        return self.profile.execution_config

    @model_validator(mode="after")
    def validate_resolved_configuration(self) -> "AgentRequest":
        config = self.profile.execution_config
        if self.agent_profile_sha256 != content_sha256(self.profile):
            raise ValueError("agent profile hash does not match its content")
        if self.execution_config_sha256 != content_sha256(config):
            raise ValueError("execution config hash does not match its content")
        if self.budget != config.attempt_budget:
            raise ValueError("request budget must match the resolved execution config")
        expected_context = (
            config.provider.provider_id,
            config.model.model_id,
            config.harness.implementation_id,
            config.runtime.implementation.implementation_id,
        )
        actual_context = (
            self.context.provider,
            self.context.model,
            self.context.harness,
            self.context.runtime,
        )
        if actual_context != expected_context:
            raise ValueError("agent context must match the resolved execution config")
        if self.context.agent_profile_id != self.profile.profile_id:
            raise ValueError("agent context profile ID must match the resolved profile")
        if self.context.seat_id != self.slot.seat_id:
            raise ValueError("agent context seat must match the decision slot")
        if self.observation.slot_id != self.slot.slot_id:
            raise ValueError("observation slot must match the decision slot")
        return self

    @classmethod
    def from_profile(
        cls,
        *,
        logical_action_id: str,
        phase_id: str,
        slot: DecisionSlot,
        observation: ObservationEnvelope,
        profile: AgentProfile,
        expected_profile_sha256: str,
        metadata: Mapping[str, object] | None = None,
    ) -> "AgentRequest":
        """Build the only profile-bound request form accepted by runner execution."""

        actual_profile_sha256 = content_sha256(profile)
        if actual_profile_sha256 != expected_profile_sha256:
            raise ValueError("profile hash does not match the resolved run plan")
        config = profile.execution_config
        return cls(
            logical_action_id=logical_action_id,
            phase_id=phase_id,
            slot=slot,
            observation=observation,
            context=AgentContext(
                agent_profile_id=profile.profile_id,
                seat_id=slot.seat_id,
                provider=config.provider.provider_id,
                model=config.model.model_id,
                harness=config.harness.implementation_id,
                runtime=config.runtime.implementation.implementation_id,
                metadata={} if metadata is None else metadata,
            ),
            profile=profile,
            agent_profile_sha256=actual_profile_sha256,
            execution_config_sha256=content_sha256(config),
            budget=config.attempt_budget,
        )


class RunSpec(StrictModel):
    spec_version: Literal["aeread.run/0.1"] = "aeread.run/0.1"
    run_id: ExportableId
    run_version: SDKStr
    admission_profile: Literal["paper_primary", "training", "interop_only"]
    execution_backend: PinnedPluginRef
    subject_profile_by_role: ImmutableMapping[SDKStr]
    #: Ambiguous today: fixtures set "local", which reads as placement, while
    #: the existing runner's three modes are offline / live_frozen / replay and
    #: placement is already pinned by execution_backend. Left free until the
    #: field's meaning is settled — see docs/pr7_contract_decision_request.md.
    execution_mode: SDKStr

    @model_validator(mode="after")
    def validate_run(self) -> "RunSpec":
        if (
            not self.run_id.strip()
            or not _SEMVER_PATTERN.fullmatch(self.run_version)
            or not self.execution_mode.strip()
            or not self.subject_profile_by_role
        ):
            raise ValueError("run identity, mode, and subject assignments are required")
        if any(not value.strip() for value in self.subject_profile_by_role.values()):
            raise ValueError("subject profile IDs must be non-empty")
        return self


class ResolutionInputs(StrictModel):
    family: FamilyManifest
    cases: tuple[CaseManifest, ...]
    suite: SuiteManifest
    agent_profiles: tuple[AgentProfile, ...]
    run_spec: RunSpec


class AdmissionCheck(StrictModel):
    axis: SDKStr
    actual_value: SDKStr
    allowed_values: tuple[SDKStr, ...]
    passed: SDKBool
    profile_id: SDKStr | None = None


class AdmissionReport(StrictModel):
    requested_profile: Literal["paper_primary", "training", "interop_only"]
    status: Literal["admitted", "rejected"]
    checks: tuple[AdmissionCheck, ...]


class PlanCell(StrictModel):
    spec_version: Literal["aeread.plan_cell/0.1"]
    record_type: Literal["plan_cell"]
    cell_id: SDKStr
    case_id: SDKStr
    family_id: SDKStr
    family_version: SDKStr
    block_id: SDKStr
    estimand_id: SDKStr
    measurement_sha256: SHA256
    subject_role: SDKStr
    subject_seat_id: SDKStr
    repetition_index: SDKInt = Field(ge=0)
    rollout_seed: SDKInt = Field(ge=0)
    world_seed: SDKInt = Field(ge=0)
    cluster_id: SDKStr
    cluster_level: SDKStr
    observations_per_cluster: SDKInt = Field(ge=1)
    cluster_parent_value: SDKStr | SDKInt | None = None
    pairing_values: JSONObject
    panel_mode: Literal["fixed_panel", "sampled_panel"]
    case_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    family_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    suite_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    run_spec_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_agent_config_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    seat_profile_id_by_seat: ImmutableMapping[SDKStr]
    seat_profile_sha256_by_seat: ImmutableMapping[SHA256]
    environment_ref: ImplementationRef
    verifier_ref: ImplementationRef
    reference_refs: ImmutableMapping[ImplementationRef]
    oracle_ref: ImplementationRef | None = None
    adapter_refs_by_seat: ImmutableMapping[ImplementationRef]
    execution_backend_ref: ImplementationRef
    admission_profile: Literal["paper_primary", "training", "interop_only"]


# Import-only compatibility alias. It cannot create a second model, schema, or payload.
EpisodeCell = PlanCell


class RunPlan(StrictModel):
    spec_version: Literal["aeread.run_plan/0.2"]
    run_plan_id: SDKStr
    run_plan_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    family_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    case_sha256_by_id: ImmutableMapping[SHA256]
    suite_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    run_spec_sha256: SDKStr = Field(pattern=r"^[0-9a-f]{64}$")
    agent_profile_sha256_by_id: ImmutableMapping[SHA256]
    family: FamilyManifest
    cases: tuple[CaseManifest, ...]
    suite: SuiteManifest
    agent_profiles: tuple[AgentProfile, ...]
    run_spec: RunSpec
    adapter_call_observability_by_profile: ImmutableMapping[CallObservability]
    admission_report: AdmissionReport
    cells: tuple[PlanCell, ...]

    @model_validator(mode="after")
    def validate_plan(self) -> "RunPlan":
        if not self.cells:
            raise ValueError("run plan must contain cells")
        if self.admission_report.status != "admitted":
            raise ValueError("run plan requires successful admission")
        cell_ids = [cell.cell_id for cell in self.cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("cell_id values must be unique")
        return self
