"""Typed quality-control states and content-bound evidence references."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .schemas import is_exportable_id


_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
QC_STATES = frozenset({"passed", "failed", "partial", "not_run", "not_applicable"})


class QCContractError(ValueError):
    """A QC status or evidence binding is incomplete or internally inconsistent."""


def _require_id(value: object, label: str) -> str:
    if not is_exportable_id(value):
        raise QCContractError(f"{label} must be an exportable identifier")
    return value


def _require_semver(value: object, label: str) -> str:
    if not isinstance(value, str) or _SEMVER_RE.fullmatch(value) is None:
        raise QCContractError(f"{label} must be an exact semantic version")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise QCContractError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return value


def _require_id_tuple(
    values: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(values, tuple) or (not values and not allow_empty):
        qualifier = "a tuple" if allow_empty else "a non-empty tuple"
        raise QCContractError(f"{label} must be {qualifier}")
    for value in values:
        _require_id(value, f"{label} item")
    if len(values) != len(set(values)):
        raise QCContractError(f"{label} must not contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class QCCoverage:
    """The exact expected and observed units represented by one artifact."""

    coverage_id: str
    required_ids: tuple[str, ...]
    observed_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_id(self.coverage_id, "coverage_id")
        required = _require_id_tuple(self.required_ids, "required_ids")
        observed = _require_id_tuple(
            self.observed_ids, "observed_ids", allow_empty=True
        )
        unexpected = sorted(set(observed) - set(required))
        if unexpected:
            raise QCContractError(
                f"observed_ids contains values outside required_ids: {unexpected}"
            )

    @property
    def complete(self) -> bool:
        return set(self.observed_ids) == set(self.required_ids)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QCCoverage":
        if not isinstance(value, Mapping):
            raise QCContractError("coverage must be an object")
        expected = {"coverage_id", "required_ids", "observed_ids"}
        if set(value) != expected:
            raise QCContractError("coverage fields are incomplete or unexpected")
        return cls(
            coverage_id=value["coverage_id"],
            required_ids=tuple(value["required_ids"]),
            observed_ids=tuple(value["observed_ids"]),
        )


@dataclass(frozen=True, slots=True)
class QCEvidenceRef:
    """A content-addressed artifact bound to identity and declared coverage."""

    artifact_type: str
    path: str
    sha256: str
    family_id: str
    family_version: str
    profile_id: str
    coverage: tuple[QCCoverage, ...]

    def __post_init__(self) -> None:
        _require_id(self.artifact_type, "artifact_type")
        if not isinstance(self.path, str) or not self.path.strip():
            raise QCContractError("path must be a non-empty string")
        _require_sha256(self.sha256, "sha256")
        _require_id(self.family_id, "family_id")
        _require_semver(self.family_version, "family_version")
        _require_id(self.profile_id, "profile_id")
        if not isinstance(self.coverage, tuple) or not self.coverage:
            raise QCContractError("coverage must be a non-empty tuple")
        if any(not isinstance(item, QCCoverage) for item in self.coverage):
            raise QCContractError("coverage must contain only QCCoverage records")
        coverage_ids = tuple(item.coverage_id for item in self.coverage)
        if len(coverage_ids) != len(set(coverage_ids)):
            raise QCContractError("coverage IDs must be unique within an artifact")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "QCEvidenceRef":
        if not isinstance(value, Mapping):
            raise QCContractError("evidence reference must be an object")
        expected = {
            "artifact_type",
            "path",
            "sha256",
            "family_id",
            "family_version",
            "profile_id",
            "coverage",
        }
        if set(value) != expected:
            raise QCContractError(
                "evidence reference fields are incomplete or unexpected"
            )
        return cls(
            artifact_type=value["artifact_type"],
            path=value["path"],
            sha256=value["sha256"],
            family_id=value["family_id"],
            family_version=value["family_version"],
            profile_id=value["profile_id"],
            coverage=tuple(QCCoverage.from_dict(item) for item in value["coverage"]),
        )


def evidence_coverage_complete(
    evidence_refs: tuple[QCEvidenceRef, ...], coverage_id: str
) -> bool:
    """Return whether bound artifacts collectively cover one declared scope."""

    _require_id(coverage_id, "coverage_id")
    matching = [
        coverage
        for evidence in evidence_refs
        for coverage in evidence.coverage
        if coverage.coverage_id == coverage_id
    ]
    if not matching:
        return False
    required_sets = {frozenset(coverage.required_ids) for coverage in matching}
    if len(required_sets) != 1:
        raise QCContractError(
            f"coverage {coverage_id!r} declares inconsistent required IDs"
        )
    required = set(next(iter(required_sets)))
    observed = {
        item for coverage in matching for item in coverage.observed_ids
    }
    return observed == required


def verify_qc_evidence_files(
    evidence_refs: tuple[QCEvidenceRef, ...],
    evidence_root: Path,
    *,
    expected_artifact_types: tuple[str, ...],
) -> tuple[Path, ...]:
    """Resolve and hash every evidence artifact inside one trusted root.

    ``QCEvidenceRef`` is the portable record.  This function is the material
    admission boundary: callers cannot turn a path and a plausible-looking
    digest into passed evidence without the referenced bytes being present.
    """

    if not isinstance(evidence_root, Path):
        raise QCContractError("evidence_root must be a Path")
    try:
        root = evidence_root.resolve(strict=True)
    except OSError as error:
        raise QCContractError("evidence_root must exist") from error
    if not root.is_dir():
        raise QCContractError("evidence_root must be a directory")
    allowed = _require_id_tuple(
        expected_artifact_types, "expected_artifact_types"
    )
    allowed_set = set(allowed)
    resolved: list[Path] = []
    for evidence in evidence_refs:
        if not isinstance(evidence, QCEvidenceRef):
            raise QCContractError(
                "evidence_refs must contain only QCEvidenceRef records"
            )
        if evidence.artifact_type not in allowed_set:
            raise QCContractError(
                f"artifact_type {evidence.artifact_type!r} is not permitted; "
                f"expected one of {sorted(allowed_set)}"
            )
        relative = Path(evidence.path)
        if relative.is_absolute():
            raise QCContractError("evidence path must be relative to evidence_root")
        try:
            artifact = (root / relative).resolve(strict=True)
            artifact.relative_to(root)
        except (OSError, ValueError) as error:
            raise QCContractError(
                f"evidence path does not resolve inside evidence_root: {evidence.path}"
            ) from error
        if not artifact.is_file():
            raise QCContractError(f"evidence artifact is not a file: {evidence.path}")
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != evidence.sha256:
            raise QCContractError(
                f"evidence artifact digest mismatch: {evidence.path}"
            )
        resolved.append(artifact)
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class QCTrackStatus:
    """One explicitly named development or normative QC track."""

    scope_id: str
    state: str
    rationale: str

    def __post_init__(self) -> None:
        _require_id(self.scope_id, "scope_id")
        if self.state not in QC_STATES:
            raise QCContractError(f"state must be one of {sorted(QC_STATES)}")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise QCContractError("rationale must be a non-empty string")


@dataclass(frozen=True, slots=True)
class BenchmarkQCStatus:
    """Separate development evidence from normative family readiness."""

    family_id: str
    family_version: str
    development: QCTrackStatus
    normative: QCTrackStatus

    def __post_init__(self) -> None:
        _require_id(self.family_id, "family_id")
        _require_semver(self.family_version, "family_version")
        if not isinstance(self.development, QCTrackStatus):
            raise QCContractError("development must be a QCTrackStatus")
        if not isinstance(self.normative, QCTrackStatus):
            raise QCContractError("normative must be a QCTrackStatus")
        if self.development.scope_id == self.normative.scope_id:
            raise QCContractError("development and normative scopes must be distinct")

    @property
    def promotion_eligible(self) -> bool:
        return self.normative.state == "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "aeread.benchmark_qc_status/0.1",
            "family_id": self.family_id,
            "family_version": self.family_version,
            "development": {
                "scope_id": self.development.scope_id,
                "state": self.development.state,
                "rationale": self.development.rationale,
            },
            "normative": {
                "scope_id": self.normative.scope_id,
                "state": self.normative.state,
                "rationale": self.normative.rationale,
            },
            "promotion_eligible": self.promotion_eligible,
        }


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Finite execution ceilings required before a contributed family can run."""

    max_wall_seconds: float
    max_logical_actions: int
    max_provider_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_wall_seconds, bool)
            or not isinstance(self.max_wall_seconds, (int, float))
            or not math.isfinite(float(self.max_wall_seconds))
            or self.max_wall_seconds <= 0
        ):
            raise QCContractError("max_wall_seconds must be finite and positive")
        for name in (
            "max_logical_actions",
            "max_provider_calls",
            "max_input_tokens",
            "max_output_tokens",
        ):
            value = getattr(self, name)
            minimum = 1 if name == "max_logical_actions" else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise QCContractError(f"{name} must be an integer at least {minimum}")
        if (
            isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or not math.isfinite(float(self.max_cost_usd))
            or self.max_cost_usd < 0
        ):
            raise QCContractError("max_cost_usd must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class HumanQCApproval:
    """A human decision bound to the exact contributed-family contract."""

    reviewer_id: str
    decision: str
    contribution_sha256: str
    evidence: QCEvidenceRef

    def __post_init__(self) -> None:
        _require_id(self.reviewer_id, "reviewer_id")
        if self.decision != "approved":
            raise QCContractError("human QC decision must be approved")
        _require_sha256(self.contribution_sha256, "contribution_sha256")
        if not isinstance(self.evidence, QCEvidenceRef):
            raise QCContractError("human QC evidence must be a QCEvidenceRef")
        if self.evidence.artifact_type != "human_qc_approval":
            raise QCContractError(
                "human QC evidence artifact_type must be human_qc_approval"
            )


@dataclass(frozen=True, slots=True)
class FamilyContribution:
    """Admission material required for a new, non-built-in family plugin."""

    family_id: str
    family_version: str
    plugin_id: str
    registry_namespace: str
    action_schema: Mapping[str, Any]
    observation_schema: Mapping[str, Any]
    provider_free_evidence: QCEvidenceRef
    resource_limits: ResourceLimits
    human_qc_approval: HumanQCApproval

    def __post_init__(self) -> None:
        _require_id(self.family_id, "family_id")
        _require_semver(self.family_version, "family_version")
        _require_id(self.plugin_id, "plugin_id")
        _require_id(self.registry_namespace, "registry_namespace")
        if not isinstance(self.action_schema, Mapping):
            raise QCContractError("action_schema must be an object")
        if not isinstance(self.observation_schema, Mapping):
            raise QCContractError("observation_schema must be an object")
        if not isinstance(self.provider_free_evidence, QCEvidenceRef):
            raise QCContractError(
                "provider_free_evidence must be a QCEvidenceRef"
            )
        if not isinstance(self.resource_limits, ResourceLimits):
            raise QCContractError("resource_limits must be a ResourceLimits")
        if not isinstance(self.human_qc_approval, HumanQCApproval):
            raise QCContractError(
                "human_qc_approval must be a HumanQCApproval"
            )


__all__ = [
    "BenchmarkQCStatus",
    "FamilyContribution",
    "HumanQCApproval",
    "QCCoverage",
    "QCContractError",
    "QCEvidenceRef",
    "QCTrackStatus",
    "QC_STATES",
    "ResourceLimits",
    "evidence_coverage_complete",
    "verify_qc_evidence_files",
]
