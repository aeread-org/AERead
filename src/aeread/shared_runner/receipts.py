"""Immutable, content-addressed evaluation receipts for the shared runner.

A receipt binds plan/case identity, design metadata, resolved implementations,
sealed evidence, typed measurements, replay capability, and the admission
decision.  It deliberately references rather than duplicates the event log and
artifacts sealed by :class:`EvidenceStore`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .execution import EvidenceSeal
from .measurement import (
    ImplementationRef,
    MeasurementContractError,
    ScoreEnvelope,
)
from .resolver import ImplementationPin, canonical_json_bytes
from .schemas import is_exportable_id


_SHA256_LENGTH = 64
_FAILURE_CLASSES = {
    "retryable_infrastructure",
    "agent_action_failure",
    "integration_or_configuration",
    "environment_failure",
    "oracle_or_scorer_failure",
}
_REPLAY_LEVELS = {"none", "score_only", "state_and_score"}
_PANEL_MODES = {"sampled_panel", "fixed_panel"}


def _require_id(value: object, label: str) -> str:
    if not is_exportable_id(value):
        raise MeasurementContractError(f"{label} must be an exportable identifier")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeasurementContractError(f"{label} must be a non-empty string")
    return value


def _require_sha256(value: object, label: str) -> str:
    text = _require_text(value, label)
    if len(text) != _SHA256_LENGTH or any(character not in "0123456789abcdef" for character in text):
        raise MeasurementContractError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _freeze_json(value: Any, label: str) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise MeasurementContractError(f"{label} keys must be strings")
            frozen[key] = _freeze_json(item, f"{label}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        )
    if value is None or isinstance(value, (str, bool, int, float)):
        try:
            canonical_json_bytes(value)
        except (TypeError, ValueError) as error:
            raise MeasurementContractError(
                f"{label} must contain only canonical JSON values"
            ) from error
        return value
    raise MeasurementContractError(f"{label} must contain only canonical JSON values")


def _freeze_digest_mapping(value: Mapping[str, str], label: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise MeasurementContractError(f"{label} must be a non-empty mapping")
    frozen: dict[str, str] = {}
    for key, digest in sorted(value.items()):
        frozen[_require_id(key, f"{label} key")] = _require_sha256(
            digest, f"{label}.{key}"
        )
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class EvaluationFailure:
    """Typed reason why a receipt cannot support its primary measurement."""

    failure_class: str
    condition: str
    message: str

    def __post_init__(self) -> None:
        if self.failure_class not in _FAILURE_CLASSES:
            raise MeasurementContractError(
                f"unsupported evaluation failure_class: {self.failure_class!r}"
            )
        _require_id(self.condition, "failure condition")
        _require_text(self.message, "failure message")


@dataclass(frozen=True, slots=True)
class EvaluationReceipt:
    """Final immutable admission record for one planned episode attempt."""

    spec_version: str
    receipt_sha256: str | None
    status: str
    inclusion_status: str
    run_plan_id: str
    run_plan_sha256: str
    cell_id: str
    case_id: str
    case_sha256: str
    suite_id: str
    suite_version: str
    block_id: str
    sampling_plan_id: str
    analysis_plan_id: str
    episode_id: str
    episode_attempt_id: str
    cluster_id: str
    cluster_level: str
    observations_per_cluster: int
    parent_cluster_id: str | None
    pair_id: str | None
    paired_fields: Mapping[str, Any]
    replicate_index: int
    panel_mode: str
    agent_profile_sha256_by_seat: Mapping[str, str]
    implementation_refs: tuple[ImplementationRef, ...]
    plan_implementation_pins: tuple[ImplementationPin, ...]
    evidence: EvidenceSeal
    primary_leaf_id: str
    scores: tuple[ScoreEnvelope, ...]
    failure: EvaluationFailure | None
    observability_limits: tuple[str, ...] = field(default_factory=tuple)
    replay_level: str = "none"

    SPEC_VERSION = "aeread.receipt/0.1"

    def __post_init__(self) -> None:
        if self.spec_version != self.SPEC_VERSION:
            raise MeasurementContractError(
                f"spec_version must be {self.SPEC_VERSION!r}"
            )
        if self.receipt_sha256 is not None:
            _require_sha256(self.receipt_sha256, "receipt_sha256")
        if self.status not in {"ok", "invalid_measurement"}:
            raise MeasurementContractError("receipt status must be ok or invalid_measurement")
        if self.inclusion_status not in {"included", "excluded"}:
            raise MeasurementContractError(
                "receipt inclusion_status must be included or excluded"
            )

        for name in (
            "run_plan_id",
            "cell_id",
            "case_id",
            "suite_id",
            "block_id",
            "sampling_plan_id",
            "analysis_plan_id",
            "episode_id",
            "episode_attempt_id",
            "cluster_id",
            "cluster_level",
            "primary_leaf_id",
        ):
            _require_id(getattr(self, name), name)
        if self.parent_cluster_id is not None:
            _require_id(self.parent_cluster_id, "parent_cluster_id")
        if self.pair_id is not None:
            _require_id(self.pair_id, "pair_id")
        _require_text(self.suite_version, "suite_version")
        _require_sha256(self.run_plan_sha256, "run_plan_sha256")
        _require_sha256(self.case_sha256, "case_sha256")

        if isinstance(self.observations_per_cluster, bool) or not isinstance(
            self.observations_per_cluster, int
        ) or self.observations_per_cluster < 1:
            raise MeasurementContractError("observations_per_cluster must be at least one")
        if isinstance(self.replicate_index, bool) or not isinstance(self.replicate_index, int) or self.replicate_index < 0:
            raise MeasurementContractError("replicate_index must be a non-negative integer")
        if self.panel_mode not in _PANEL_MODES:
            raise MeasurementContractError(
                f"panel_mode must be one of {sorted(_PANEL_MODES)}"
            )
        if self.replay_level not in _REPLAY_LEVELS:
            raise MeasurementContractError(
                f"replay_level must be one of {sorted(_REPLAY_LEVELS)}"
            )

        object.__setattr__(self, "paired_fields", _freeze_json(self.paired_fields, "paired_fields"))
        object.__setattr__(
            self,
            "agent_profile_sha256_by_seat",
            _freeze_digest_mapping(
                self.agent_profile_sha256_by_seat,
                "agent_profile_sha256_by_seat",
            ),
        )
        self._validate_and_freeze_implementations()
        self._validate_and_freeze_plan_pins()
        self._validate_and_freeze_scores()
        self._validate_evidence()

        limits = tuple(self.observability_limits)
        for limit in limits:
            _require_text(limit, "observability limit")
        object.__setattr__(self, "observability_limits", limits)

        if self.failure is not None and not isinstance(self.failure, EvaluationFailure):
            raise MeasurementContractError("failure must be an EvaluationFailure")
        primary = next(
            (score for score in self.scores if score.leaf.leaf_id == self.primary_leaf_id),
            None,
        )
        if self.status == "ok":
            if self.inclusion_status != "included":
                raise MeasurementContractError("ok receipt must be included")
            if primary is None or primary.status != "ok":
                raise MeasurementContractError(
                    "ok receipt cannot contain an invalid primary measurement"
                )
            if self.failure is not None:
                raise MeasurementContractError("ok receipt cannot contain a failure")
            if self.replay_level == "none":
                raise MeasurementContractError("included receipt must support score replay")
        else:
            if self.inclusion_status != "excluded":
                raise MeasurementContractError(
                    "invalid_measurement receipt must be excluded"
                )
            if primary is not None and primary.status != "invalid_measurement":
                raise MeasurementContractError(
                    "excluded receipt cannot contain a valid primary measurement"
                )
            if self.failure is None:
                raise MeasurementContractError(
                    "invalid_measurement receipt requires a typed failure"
                )

    def _validate_and_freeze_implementations(self) -> None:
        if not isinstance(self.implementation_refs, tuple):
            raise MeasurementContractError("implementation_refs must be a tuple")
        resolved: dict[tuple[str, str], ImplementationRef] = {}
        for implementation in self.implementation_refs:
            if not isinstance(implementation, ImplementationRef):
                raise MeasurementContractError(
                    "implementation_refs must contain only ImplementationRef values"
                )
            key = (implementation.implementation_id, implementation.version)
            existing = resolved.get(key)
            if existing is not None and existing != implementation:
                raise MeasurementContractError(
                    "implementation_refs contain conflicting content hashes"
                )
            resolved[key] = implementation
        canonical = tuple(
            sorted(
                resolved.values(),
                key=lambda item: (
                    item.implementation_id,
                    item.version,
                    item.content_sha256,
                ),
            )
        )
        object.__setattr__(self, "implementation_refs", canonical)

    def _validate_and_freeze_scores(self) -> None:
        if not isinstance(self.scores, tuple):
            raise MeasurementContractError("scores must be a tuple")
        by_leaf: dict[str, ScoreEnvelope] = {}
        for score in self.scores:
            if not isinstance(score, ScoreEnvelope):
                raise MeasurementContractError("scores must contain only ScoreEnvelope values")
            leaf_id = score.leaf.leaf_id
            if leaf_id in by_leaf:
                raise MeasurementContractError("scores contain a duplicate measurement leaf")
            by_leaf[leaf_id] = score
        canonical = tuple(
            sorted(
                by_leaf.values(),
                key=lambda score: (
                    score.leaf.leaf_id != self.primary_leaf_id,
                    score.leaf.leaf_id,
                ),
            )
        )
        object.__setattr__(self, "scores", canonical)

        available = set(self.implementation_refs)
        required: set[ImplementationRef] = set()
        for score in canonical:
            required.update(
                {
                    score.leaf.estimand.validity_domain.predicate,
                    score.leaf.verifier.reference.implementation,
                    score.leaf.scorer,
                }
            )
        if not required.issubset(available):
            raise MeasurementContractError(
                "implementation_refs must pin every score predicate, reference, and scorer"
            )

    def _validate_and_freeze_plan_pins(self) -> None:
        if not isinstance(self.plan_implementation_pins, tuple) or not self.plan_implementation_pins:
            raise MeasurementContractError(
                "plan_implementation_pins must be a non-empty tuple"
            )
        resolved: dict[str, ImplementationPin] = {}
        for pin in self.plan_implementation_pins:
            if not isinstance(pin, ImplementationPin):
                raise MeasurementContractError(
                    "plan_implementation_pins must contain only ImplementationPin values"
                )
            try:
                checked = ImplementationPin.from_dict(dataclasses.asdict(pin))
            except Exception as error:
                raise MeasurementContractError(
                    "plan_implementation_pins contain an invalid pin"
                ) from error
            if checked.component_id in resolved:
                raise MeasurementContractError(
                    "plan_implementation_pins contain duplicate component identities"
                )
            resolved[checked.component_id] = checked
        canonical = tuple(resolved[key] for key in sorted(resolved))
        object.__setattr__(self, "plan_implementation_pins", canonical)

        available = {
            (pin.component_id, pin.version, pin.sha256) for pin in canonical
        }
        missing = sorted(
            implementation.implementation_id
            for implementation in self.implementation_refs
            if (
                implementation.implementation_id,
                implementation.version,
                implementation.content_sha256,
            )
            not in available
        )
        if missing:
            raise MeasurementContractError(
                "plan_implementation_pins do not match measurement implementations: "
                + ", ".join(missing)
            )

    def _validate_evidence(self) -> None:
        if not isinstance(self.evidence, EvidenceSeal):
            raise MeasurementContractError("evidence must be an EvidenceSeal")
        expected = (
            self.run_plan_id,
            self.cell_id,
            self.episode_id,
            self.episode_attempt_id,
        )
        observed = (
            self.evidence.run_plan_id,
            self.evidence.cell_id,
            self.evidence.episode_id,
            self.evidence.episode_attempt_id,
        )
        if observed != expected:
            raise MeasurementContractError("receipt and evidence identity do not match")
        if (
            isinstance(self.evidence.event_count, bool)
            or not isinstance(self.evidence.event_count, int)
            or self.evidence.event_count < 0
            or isinstance(self.evidence.artifact_count, bool)
            or not isinstance(self.evidence.artifact_count, int)
            or self.evidence.artifact_count < 0
        ):
            raise MeasurementContractError("evidence counts must be non-negative integers")
        _require_sha256(self.evidence.event_root_sha256, "event_root_sha256")
        _require_sha256(self.evidence.artifact_root_sha256, "artifact_root_sha256")


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


def write_evaluation_receipt(
    receipt: EvaluationReceipt, destination: str | Path
) -> Path:
    """Durably publish canonical receipt bytes without overwriting other content."""

    verify_evaluation_receipt(receipt)
    path = Path(destination)
    payload = canonical_json_bytes(receipt) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise MeasurementContractError("receipt destination must not be a symlink")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != payload:
            raise MeasurementContractError(
                "refusing to overwrite a different evaluation receipt"
            )
        return path
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while persisting evaluation receipt")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path


__all__ = [
    "EvaluationFailure",
    "EvaluationReceipt",
    "seal_evaluation_receipt",
    "verify_evaluation_receipt",
    "write_evaluation_receipt",
]
