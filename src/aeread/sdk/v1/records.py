"""Immutable public records shared by AERead environments and the runner."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, ValidationInfo, model_validator

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
    media_type: SDKStr
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
    payload: JSONObject
    prior_event_hash: SDKStr | None = None
    event_hash: SDKStr


class SealedEvidenceView(StrictModel):
    events: tuple[EpisodeEvent, ...]
    artifacts: tuple[ArtifactRef, ...]
    event_root_sha256: SDKStr
    artifact_root_sha256: SDKStr


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
    case_id: SDKStr
    family_id: SDKStr
    family_version: SDKStr
    split: SDKStr
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
    block_id: SDKStr
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
    suite_id: SDKStr
    suite_version: SDKStr
    case_ids: tuple[SDKStr, ...]
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
    run_id: SDKStr
    run_version: SDKStr
    admission_profile: Literal["paper_primary", "training", "interop_only"]
    execution_backend: PinnedPluginRef
    subject_profile_by_role: ImmutableMapping[SDKStr]
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


class EpisodeCell(StrictModel):
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


class RunPlan(StrictModel):
    spec_version: Literal["aeread.run_plan/0.1"] = "aeread.run_plan/0.1"
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
    cells: tuple[EpisodeCell, ...]

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
