"""Typed, family-neutral measurement contracts for shared-runner adapters.

The runner owns these records and their validation.  A family adapter owns the
economic meaning and implementation of each estimand, reference, and scorer.
Keeping that boundary explicit lets Housing, refund, and supply-chain cases use
one receipt format without implying that their measurements are interchangeable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .schemas import is_exportable_id


_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INPUT_SCOPES = {"answer", "terminal_state", "trajectory", "distribution"}
_DIRECTIONS = {"maximize", "minimize", "none"}
_EVALUATION_CLASSES = {"deterministic", "stochastic_estimator", "judge_dependent"}
_REFERENCE_KINDS = {
    "canonical_reference": {
        "canonical_point",
        "canonical_set",
        "terminal_state_equivalence",
        "distance_to_canonical_set",
    },
    "rule_constraint": {
        "constraint_satisfaction",
        "state_invariant",
        "temporal_property",
        "axiom_relation",
        "metamorphic_relation",
    },
    "objective_reference": {
        "exact_optimum",
        "objective_lower_bound",
        "objective_upper_bound",
        "comparison_baseline",
        "outcome_support_min",
        "outcome_support_max",
    },
    "comparative": {
        "baseline_delta",
        "paired_comparison",
        "head_to_head",
        "human_reference_comparison",
        "field_rating",
    },
    "rater_judge": {"rubric_score", "pairwise_preference"},
}
_REFERENCE_SCOPE = {
    "terminal_state_equivalence": {"terminal_state"},
    "temporal_property": {"trajectory"},
    "state_invariant": {"terminal_state", "trajectory"},
    "metamorphic_relation": {"distribution"},
    "exact_optimum": {"terminal_state", "distribution"},
    "objective_lower_bound": {"terminal_state", "distribution"},
    "objective_upper_bound": {"terminal_state", "distribution"},
    "comparison_baseline": {"terminal_state", "distribution"},
    "outcome_support_min": {"terminal_state", "distribution"},
    "outcome_support_max": {"terminal_state", "distribution"},
}


class MeasurementContractError(ValueError):
    """A measurement record would support an ambiguous or invalid claim."""


def _require_id(value: object, label: str) -> str:
    if not is_exportable_id(value):
        raise MeasurementContractError(f"{label} must be an exportable identifier")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeasurementContractError(f"{label} must be a non-empty string")
    return value


def _require_semver(value: object, label: str) -> str:
    text = _require_text(value, label)
    if _SEMVER_RE.fullmatch(text) is None:
        raise MeasurementContractError(f"{label} must be an exact semantic version")
    return text


def _require_sha256(value: object, label: str) -> str:
    text = _require_text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise MeasurementContractError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _freeze_metric_mapping(
    value: Mapping[str, "MetricValue"], label: str
) -> Mapping[str, "MetricValue"]:
    if not isinstance(value, Mapping):
        raise MeasurementContractError(f"{label} must be a mapping")
    frozen: dict[str, MetricValue] = {}
    for key, metric in value.items():
        checked = _require_id(key, f"{label} key")
        if not isinstance(metric, MetricValue):
            raise MeasurementContractError(f"{label}.{checked} must be a MetricValue")
        frozen[checked] = metric
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class ImplementationRef:
    implementation_id: str
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.implementation_id, "implementation_id")
        _require_semver(self.version, "implementation version")
        _require_sha256(self.content_sha256, "implementation content_sha256")


@dataclass(frozen=True, slots=True)
class ValidityDomainSpec:
    domain_id: str
    domain_version: str
    schema_ref: str
    predicate: ImplementationRef

    def __post_init__(self) -> None:
        _require_id(self.domain_id, "domain_id")
        _require_semver(self.domain_version, "domain_version")
        _require_text(self.schema_ref, "schema_ref")
        if not isinstance(self.predicate, ImplementationRef):
            raise MeasurementContractError("predicate must be an ImplementationRef")


@dataclass(frozen=True, slots=True)
class EstimandSpec:
    estimand_id: str
    estimand_version: str
    input_scope: str
    direction: str
    units: str
    validity_domain: ValidityDomainSpec

    def __post_init__(self) -> None:
        _require_id(self.estimand_id, "estimand_id")
        _require_semver(self.estimand_version, "estimand_version")
        if self.input_scope not in _INPUT_SCOPES:
            raise MeasurementContractError(f"unsupported estimand input_scope: {self.input_scope!r}")
        if self.direction not in _DIRECTIONS:
            raise MeasurementContractError(f"unsupported estimand direction: {self.direction!r}")
        _require_text(self.units, "estimand units")
        if not isinstance(self.validity_domain, ValidityDomainSpec):
            raise MeasurementContractError("validity_domain must be a ValidityDomainSpec")


@dataclass(frozen=True, slots=True)
class ReferenceSpec:
    reference_id: str
    reference_version: str
    reference_kind: str
    input_scope: str
    units: str
    source_sha256: str
    implementation: ImplementationRef

    def __post_init__(self) -> None:
        _require_id(self.reference_id, "reference_id")
        _require_semver(self.reference_version, "reference_version")
        known_kinds = set().union(*_REFERENCE_KINDS.values())
        if self.reference_kind not in known_kinds:
            raise MeasurementContractError(f"unsupported reference_kind: {self.reference_kind!r}")
        if self.input_scope not in _INPUT_SCOPES:
            raise MeasurementContractError(f"unsupported reference input_scope: {self.input_scope!r}")
        permitted_scopes = _REFERENCE_SCOPE.get(self.reference_kind)
        if permitted_scopes is not None and self.input_scope not in permitted_scopes:
            raise MeasurementContractError(
                f"{self.reference_kind} does not accept input_scope {self.input_scope!r}"
            )
        _require_text(self.units, "reference units")
        _require_sha256(self.source_sha256, "reference source_sha256")
        if not isinstance(self.implementation, ImplementationRef):
            raise MeasurementContractError("reference implementation must be pinned")


@dataclass(frozen=True, slots=True)
class ObjectiveScopeSpec:
    objective_id: str
    objective_version: str
    direction: str
    units: str
    feasible_set: str
    information_set: str
    horizon: str
    environment_condition: str
    opponent_condition: str
    validity_domain: ValidityDomainSpec

    def __post_init__(self) -> None:
        _require_id(self.objective_id, "objective_id")
        _require_semver(self.objective_version, "objective_version")
        if self.direction not in {"maximize", "minimize"}:
            raise MeasurementContractError("an objective direction must be maximize or minimize")
        for label in (
            "units",
            "feasible_set",
            "information_set",
            "horizon",
            "environment_condition",
            "opponent_condition",
        ):
            _require_text(getattr(self, label), label)
        if not isinstance(self.validity_domain, ValidityDomainSpec):
            raise MeasurementContractError("objective validity_domain must be declared")


@dataclass(frozen=True, slots=True)
class VerifierSpec:
    verifier_family: str
    evaluation_class: str
    reference: ReferenceSpec
    objective_scope: ObjectiveScopeSpec | None = None

    def __post_init__(self) -> None:
        if self.verifier_family not in _REFERENCE_KINDS:
            raise MeasurementContractError(
                f"unsupported verifier_family: {self.verifier_family!r}"
            )
        if self.evaluation_class not in _EVALUATION_CLASSES:
            raise MeasurementContractError(
                f"unsupported evaluation_class: {self.evaluation_class!r}"
            )
        if not isinstance(self.reference, ReferenceSpec):
            raise MeasurementContractError("reference must be a ReferenceSpec")
        if self.reference.reference_kind not in _REFERENCE_KINDS[self.verifier_family]:
            raise MeasurementContractError(
                f"reference kind {self.reference.reference_kind!r} does not belong to "
                f"verifier family {self.verifier_family!r}"
            )
        if self.verifier_family == "objective_reference":
            if not isinstance(self.objective_scope, ObjectiveScopeSpec):
                raise MeasurementContractError(
                    "objective_reference verifier requires objective_scope"
                )
        elif self.objective_scope is not None:
            raise MeasurementContractError(
                "objective_scope is only valid for objective_reference verifiers"
            )
        if self.verifier_family == "rater_judge" and self.evaluation_class != "judge_dependent":
            raise MeasurementContractError("rater_judge verifier must be judge_dependent")


@dataclass(frozen=True, slots=True)
class MeasurementLeafSpec:
    leaf_id: str
    leaf_version: str
    estimand: EstimandSpec
    verifier: VerifierSpec
    scorer: ImplementationRef
    composition_kind: str = field(default="leaf", init=False)

    def __post_init__(self) -> None:
        _require_id(self.leaf_id, "leaf_id")
        _require_semver(self.leaf_version, "leaf_version")
        if not isinstance(self.estimand, EstimandSpec):
            raise MeasurementContractError("estimand must be an EstimandSpec")
        if not isinstance(self.verifier, VerifierSpec):
            raise MeasurementContractError("verifier must be a VerifierSpec")
        if not isinstance(self.scorer, ImplementationRef):
            raise MeasurementContractError("scorer must be an ImplementationRef")
        reference = self.verifier.reference
        if self.estimand.input_scope != reference.input_scope:
            raise MeasurementContractError("reference input_scope must match estimand input_scope")
        if self.estimand.units != reference.units:
            raise MeasurementContractError("reference units must match estimand units")
        scope = self.verifier.objective_scope
        if scope is not None:
            if (
                scope.objective_id != self.estimand.estimand_id
                or scope.objective_version != self.estimand.estimand_version
                or scope.direction != self.estimand.direction
                or scope.units != self.estimand.units
                or scope.validity_domain != self.estimand.validity_domain
            ):
                raise MeasurementContractError(
                    "objective_scope must match the estimand identity, direction, units, and domain"
                )


@dataclass(frozen=True, slots=True)
class MetricValue:
    value: float
    unit: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise MeasurementContractError("metric value must be a finite number")
        if not math.isfinite(float(self.value)):
            raise MeasurementContractError("metric value must be a finite number")
        _require_text(self.unit, "metric unit")
        if not isinstance(self.metadata, Mapping):
            raise MeasurementContractError("metric metadata must be a mapping")
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ValidityReport:
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"valid", "invalid"}:
            raise MeasurementContractError("validity status must be valid or invalid")
        for reason in self.reasons:
            _require_text(reason, "validity reason")
        if self.status == "invalid" and not self.reasons:
            raise MeasurementContractError("invalid validity report requires reasons")


@dataclass(frozen=True, slots=True)
class ScoreEnvelope:
    status: str
    leaf: MeasurementLeafSpec
    primary: MetricValue | None
    metrics: Mapping[str, MetricValue]
    reference_values: Mapping[str, MetricValue]
    validity: ValidityReport
    evidence_refs: tuple[str, ...]
    utility_by_seat: Mapping[str, MetricValue] = field(default_factory=dict)
    capture_by_seat: Mapping[str, MetricValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"ok", "invalid_measurement"}:
            raise MeasurementContractError("score status must be ok or invalid_measurement")
        if not isinstance(self.leaf, MeasurementLeafSpec):
            raise MeasurementContractError("leaf must be a MeasurementLeafSpec")
        if not isinstance(self.validity, ValidityReport):
            raise MeasurementContractError("validity must be a ValidityReport")
        if self.status == "ok":
            if not isinstance(self.primary, MetricValue) or self.validity.status != "valid":
                raise MeasurementContractError("ok score requires a valid primary measurement")
            if self.primary.unit != self.leaf.estimand.units:
                raise MeasurementContractError("primary metric unit must match the estimand")
        elif self.primary is not None or self.validity.status != "invalid":
            raise MeasurementContractError(
                "invalid_measurement score cannot contain a primary measurement"
            )
        for reference in self.evidence_refs:
            _require_id(reference, "evidence reference")
        object.__setattr__(self, "metrics", _freeze_metric_mapping(self.metrics, "metrics"))
        object.__setattr__(
            self,
            "reference_values",
            _freeze_metric_mapping(self.reference_values, "reference_values"),
        )
        object.__setattr__(
            self,
            "utility_by_seat",
            _freeze_metric_mapping(self.utility_by_seat, "utility_by_seat"),
        )
        object.__setattr__(
            self,
            "capture_by_seat",
            _freeze_metric_mapping(self.capture_by_seat, "capture_by_seat"),
        )


@dataclass(frozen=True, slots=True)
class FamilyScoreSet:
    """One family's independently typed score leaves and admission policy.

    ``EvaluationReceipt`` has always stored a tuple of score envelopes, but the
    generic family finalizer historically accepted only one. This record makes
    the multi-leaf boundary explicit without forcing existing one-leaf plugins
    to change: :func:`normalize_family_score_set` wraps a lone
    :class:`ScoreEnvelope` with that leaf as both primary and admission leaf.

    An invalid diagnostic may remain in an included receipt. An invalid
    admission leaf excludes the receipt as an invalid measurement; a measured
    constraint violation is still an ``ok`` envelope whose primary value is
    zero, not an invalid measurement.
    """

    primary_leaf_id: str
    scores: tuple[ScoreEnvelope, ...]
    admission_leaf_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        primary_leaf_id = _require_id(self.primary_leaf_id, "primary_leaf_id")
        if not isinstance(self.scores, tuple) or not self.scores:
            raise MeasurementContractError("family score set must contain scores")
        by_leaf: dict[str, ScoreEnvelope] = {}
        for score in self.scores:
            if not isinstance(score, ScoreEnvelope):
                raise MeasurementContractError(
                    "family score set must contain only ScoreEnvelope values"
                )
            leaf_id = score.leaf.leaf_id
            if leaf_id in by_leaf:
                raise MeasurementContractError(
                    "family score set contains a duplicate measurement leaf"
                )
            by_leaf[leaf_id] = score
        if primary_leaf_id not in by_leaf:
            raise MeasurementContractError(
                "family score set does not contain its primary measurement leaf"
            )

        raw_admission = self.admission_leaf_ids or (primary_leaf_id,)
        if not isinstance(raw_admission, tuple):
            raise MeasurementContractError("admission_leaf_ids must be a tuple")
        admission = tuple(
            _require_id(leaf_id, "admission leaf id") for leaf_id in raw_admission
        )
        if len(set(admission)) != len(admission):
            raise MeasurementContractError(
                "admission_leaf_ids must not contain duplicates"
            )
        missing = sorted(set(admission) - set(by_leaf))
        if missing:
            raise MeasurementContractError(
                "admission leaves are absent from the family score set: "
                + ", ".join(missing)
            )
        if primary_leaf_id not in admission:
            raise MeasurementContractError(
                "primary_leaf_id must also be an admission leaf"
            )

        canonical_scores = tuple(
            sorted(
                by_leaf.values(),
                key=lambda score: (
                    score.leaf.leaf_id != primary_leaf_id,
                    score.leaf.leaf_id,
                ),
            )
        )
        canonical_admission = tuple(
            sorted(
                admission,
                key=lambda leaf_id: (leaf_id != primary_leaf_id, leaf_id),
            )
        )
        object.__setattr__(self, "scores", canonical_scores)
        object.__setattr__(self, "admission_leaf_ids", canonical_admission)

    @property
    def invalid_admission_leaf_ids(self) -> tuple[str, ...]:
        admission = set(self.admission_leaf_ids)
        return tuple(
            score.leaf.leaf_id
            for score in self.scores
            if score.leaf.leaf_id in admission and score.status != "ok"
        )


def normalize_family_score_set(
    value: ScoreEnvelope | FamilyScoreSet | Sequence[ScoreEnvelope],
) -> FamilyScoreSet:
    """Normalize old and compact scorer returns to ``FamilyScoreSet``.

    A bare sequence uses its first score as the primary and sole admission
    leaf. Families with additional admission leaves must return an explicit
    ``FamilyScoreSet`` so the policy is never inferred from score order.
    """

    if isinstance(value, FamilyScoreSet):
        return value
    if isinstance(value, ScoreEnvelope):
        return FamilyScoreSet(
            primary_leaf_id=value.leaf.leaf_id,
            scores=(value,),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        scores = tuple(value)
        if not scores or not isinstance(scores[0], ScoreEnvelope):
            raise MeasurementContractError(
                "family scorer sequence must contain ScoreEnvelope values"
            )
        return FamilyScoreSet(
            primary_leaf_id=scores[0].leaf.leaf_id,
            scores=scores,
        )
    raise MeasurementContractError(
        "family scorer must return ScoreEnvelope, a score sequence, or FamilyScoreSet"
    )


__all__ = [
    "EstimandSpec",
    "FamilyScoreSet",
    "ImplementationRef",
    "MeasurementContractError",
    "MeasurementLeafSpec",
    "MetricValue",
    "ObjectiveScopeSpec",
    "ReferenceSpec",
    "ScoreEnvelope",
    "ValidityDomainSpec",
    "ValidityReport",
    "VerifierSpec",
    "normalize_family_score_set",
]
