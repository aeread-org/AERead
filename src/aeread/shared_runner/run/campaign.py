"""Sequential, evidence-bound run-campaign promotion gates.

Gate and invalidation records are append-only. A pre-freeze control change can
invalidate one gate and every downstream gate without erasing their historical
records; promotion then resumes from the affected boundary with monotonically
increasing attempt indexes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeAlias

from ..quality import (
    QCContractError,
    QCEvidenceRef,
    evidence_coverage_complete,
    verify_qc_evidence_files,
)
from .resolver import canonical_json_bytes
from ..schemas import is_exportable_id


class CampaignGateError(ValueError):
    """Campaign history is invalid or an attempted promotion is blocked."""


CAMPAIGN_GATE_SEQUENCE = (
    "design_contract",
    "provider_free_validation",
    "profile_admission",
    "full_trajectory",
    "variance_pilot",
    "confirmatory_freeze",
    "confirmatory_execution",
    "publication",
)


def campaign_gate_artifact_type(gate_id: str, status: str) -> str:
    """Return the one canonical evidence type for a gate attempt."""

    if gate_id not in CAMPAIGN_GATE_SEQUENCE:
        raise CampaignGateError(f"unknown campaign gate: {gate_id!r}")
    if status not in {"passed", "failed"}:
        raise CampaignGateError("gate status must be passed or failed")
    return f"campaign_{gate_id}_{status}"


_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$"
)


def _require_id(value: object, label: str) -> str:
    if not is_exportable_id(value):
        raise CampaignGateError(f"{label} must be an exportable identifier")
    return value


def _require_semver(value: object, label: str) -> str:
    if not isinstance(value, str) or _SEMVER_RE.fullmatch(value) is None:
        raise CampaignGateError(f"{label} must be an exact semantic version")
    return value


def _require_text_tuple(
    values: object, label: str, *, identifiers: bool = False
) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise CampaignGateError(f"{label} must be a non-empty tuple")
    for value in values:
        if identifiers:
            _require_id(value, f"{label} item")
        elif not isinstance(value, str) or not value.strip():
            raise CampaignGateError(f"{label} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise CampaignGateError(f"{label} must not contain duplicates")
    return values


def _require_evidence(
    values: object,
    *,
    family_id: str,
    family_version: str,
    profile_id: str,
) -> tuple[QCEvidenceRef, ...]:
    if not isinstance(values, tuple) or not values:
        raise CampaignGateError("evidence_refs must be a non-empty tuple")
    if any(not isinstance(value, QCEvidenceRef) for value in values):
        raise CampaignGateError(
            "evidence_refs must contain only typed QCEvidenceRef records"
        )
    identities = {
        (value.family_id, value.family_version, value.profile_id) for value in values
    }
    if identities != {(family_id, family_version, profile_id)}:
        raise CampaignGateError(
            "evidence_refs must match the gate family, version, and profile"
        )
    content_keys = tuple((value.path, value.sha256) for value in values)
    if len(content_keys) != len(set(content_keys)):
        raise CampaignGateError("evidence_refs must not duplicate artifact content")
    return values


@dataclass(frozen=True, slots=True)
class CampaignGateRecord:
    """One typed, content-bound attempt at a campaign gate."""

    campaign_id: str
    family_id: str
    family_version: str
    profile_id: str
    gate_id: str
    attempt_index: int
    status: str
    evidence_refs: tuple[QCEvidenceRef, ...]
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.campaign_id, "campaign_id")
        _require_id(self.family_id, "family_id")
        _require_semver(self.family_version, "family_version")
        _require_id(self.profile_id, "profile_id")
        if self.gate_id not in CAMPAIGN_GATE_SEQUENCE:
            raise CampaignGateError(f"unknown campaign gate: {self.gate_id!r}")
        if (
            isinstance(self.attempt_index, bool)
            or not isinstance(self.attempt_index, int)
            or self.attempt_index < 1
        ):
            raise CampaignGateError("attempt_index must be a positive integer")
        if self.status not in {"passed", "failed"}:
            raise CampaignGateError("gate status must be passed or failed")
        evidence = _require_evidence(
            self.evidence_refs,
            family_id=self.family_id,
            family_version=self.family_version,
            profile_id=self.profile_id,
        )
        if not isinstance(self.failure_reasons, tuple):
            raise CampaignGateError("failure_reasons must be a tuple")
        for reason in self.failure_reasons:
            if not isinstance(reason, str) or not reason.strip():
                raise CampaignGateError(
                    "failure_reasons must contain non-empty strings"
                )
        if self.status == "passed" and self.failure_reasons:
            raise CampaignGateError("a passed gate cannot contain failure reasons")
        if self.status == "failed" and not self.failure_reasons:
            raise CampaignGateError("a failed gate requires failure reasons")
        expected_type = campaign_gate_artifact_type(self.gate_id, self.status)
        unexpected_types = sorted(
            {
                evidence_ref.artifact_type
                for evidence_ref in evidence
                if evidence_ref.artifact_type != expected_type
            }
        )
        if unexpected_types:
            raise CampaignGateError(
                f"gate {self.gate_id!r} evidence artifact_type must be "
                f"{expected_type!r}, got {unexpected_types}"
            )
        if self.status == "passed":
            try:
                complete = evidence_coverage_complete(evidence, self.gate_id)
            except QCContractError as error:
                raise CampaignGateError(str(error)) from error
            if not complete:
                raise CampaignGateError(
                    f"passed gate requires complete {self.gate_id!r} coverage"
                )


@dataclass(frozen=True, slots=True)
class CampaignInvalidationRecord:
    """One audited control change that clears an active gate suffix."""

    campaign_id: str
    family_id: str
    family_version: str
    profile_id: str
    invalidation_index: int
    from_gate_id: str
    changed_controls: tuple[str, ...]
    reason: str
    evidence_refs: tuple[QCEvidenceRef, ...]

    def __post_init__(self) -> None:
        _require_id(self.campaign_id, "campaign_id")
        _require_id(self.family_id, "family_id")
        _require_semver(self.family_version, "family_version")
        _require_id(self.profile_id, "profile_id")
        if (
            isinstance(self.invalidation_index, bool)
            or not isinstance(self.invalidation_index, int)
            or self.invalidation_index < 1
        ):
            raise CampaignGateError("invalidation_index must be a positive integer")
        if self.from_gate_id not in CAMPAIGN_GATE_SEQUENCE:
            raise CampaignGateError(
                f"unknown campaign gate: {self.from_gate_id!r}"
            )
        _require_text_tuple(
            self.changed_controls, "changed_controls", identifiers=True
        )
        if (
            "retry_policy" in self.changed_controls
            and self.from_gate_id != "profile_admission"
        ):
            raise CampaignGateError(
                "retry_policy changes must invalidate from profile_admission"
            )
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise CampaignGateError("invalidation reason must be a non-empty string")
        evidence = _require_evidence(
            self.evidence_refs,
            family_id=self.family_id,
            family_version=self.family_version,
            profile_id=self.profile_id,
        )
        unexpected_types = sorted(
            {
                evidence_ref.artifact_type
                for evidence_ref in evidence
                if evidence_ref.artifact_type != "campaign_invalidation"
            }
        )
        if unexpected_types:
            raise CampaignGateError(
                "invalidation evidence artifact_type must be "
                f"'campaign_invalidation', got {unexpected_types}"
            )
        try:
            complete = evidence_coverage_complete(evidence, "invalidation")
        except QCContractError as error:
            raise CampaignGateError(str(error)) from error
        if not complete:
            raise CampaignGateError(
                "invalidation record requires complete 'invalidation' coverage"
            )


CampaignHistoryRecord: TypeAlias = CampaignGateRecord | CampaignInvalidationRecord


@dataclass(frozen=True, slots=True)
class CampaignPromotionDecision:
    campaign_id: str
    target_gate_id: str
    eligible: bool
    next_attempt_index: int
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _HistoryState:
    active: Mapping[str, CampaignGateRecord]
    attempt_counts: Mapping[str, int]
    invalidation_count: int


def campaign_history_record_sha256(record: CampaignHistoryRecord) -> str:
    if not isinstance(record, (CampaignGateRecord, CampaignInvalidationRecord)):
        raise CampaignGateError("record must be a campaign history record")
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def campaign_gate_record_sha256(record: CampaignGateRecord) -> str:
    if not isinstance(record, CampaignGateRecord):
        raise CampaignGateError("record must be a CampaignGateRecord")
    return campaign_history_record_sha256(record)


def _history_state(
    campaign_id: str,
    records: Sequence[CampaignHistoryRecord],
    *,
    evidence_root: Path,
) -> _HistoryState:
    _require_id(campaign_id, "campaign_id")
    active: dict[str, CampaignGateRecord] = {}
    attempt_counts: dict[str, int] = {}
    invalidation_count = 0
    seen_digests: set[str] = set()
    identity: tuple[str, str, str] | None = None

    for record in records:
        if not isinstance(record, (CampaignGateRecord, CampaignInvalidationRecord)):
            raise CampaignGateError(
                "campaign history must contain only gate or invalidation records"
            )
        if record.campaign_id != campaign_id:
            raise CampaignGateError("campaign history mixes campaign identities")
        expected_types = (
            ("campaign_invalidation",)
            if isinstance(record, CampaignInvalidationRecord)
            else (campaign_gate_artifact_type(record.gate_id, record.status),)
        )
        try:
            verify_qc_evidence_files(
                record.evidence_refs,
                evidence_root,
                expected_artifact_types=expected_types,
            )
        except QCContractError as error:
            raise CampaignGateError(str(error)) from error
        record_identity = (
            record.family_id,
            record.family_version,
            record.profile_id,
        )
        if identity is None:
            identity = record_identity
        elif record_identity != identity:
            raise CampaignGateError(
                "campaign history mixes family, version, or profile identities"
            )
        digest = campaign_history_record_sha256(record)
        if digest in seen_digests:
            raise CampaignGateError("campaign history contains a duplicate record")
        seen_digests.add(digest)

        if isinstance(record, CampaignInvalidationRecord):
            invalidation_count += 1
            if record.invalidation_index != invalidation_count:
                raise CampaignGateError(
                    "invalidation indexes must be contiguous from one"
                )
            freeze = active.get("confirmatory_freeze")
            if freeze is not None and freeze.status == "passed":
                raise CampaignGateError(
                    "a passed confirmatory freeze requires a new campaign identity"
                )
            boundary = CAMPAIGN_GATE_SEQUENCE.index(record.from_gate_id)
            affected = [
                gate_id
                for gate_id in CAMPAIGN_GATE_SEQUENCE[boundary:]
                if gate_id in active
            ]
            if not affected:
                raise CampaignGateError(
                    "invalidation does not affect any active gate record"
                )
            for gate_id in CAMPAIGN_GATE_SEQUENCE[boundary:]:
                active.pop(gate_id, None)
            continue

        expected_attempt = attempt_counts.get(record.gate_id, 0) + 1
        if record.attempt_index != expected_attempt:
            raise CampaignGateError(
                f"gate {record.gate_id!r} requires attempt_index {expected_attempt}"
            )
        target_index = CAMPAIGN_GATE_SEQUENCE.index(record.gate_id)
        missing_or_failed = [
            gate_id
            for gate_id in CAMPAIGN_GATE_SEQUENCE[:target_index]
            if gate_id not in active or active[gate_id].status != "passed"
        ]
        if missing_or_failed:
            raise CampaignGateError(
                f"gate {record.gate_id!r} was appended before passed predecessors: "
                f"{missing_or_failed}"
            )
        later = [
            gate_id
            for gate_id in CAMPAIGN_GATE_SEQUENCE[target_index + 1 :]
            if gate_id in active
        ]
        if later:
            raise CampaignGateError(
                f"cannot revisit {record.gate_id!r} after downstream gates: {later}"
            )
        current = active.get(record.gate_id)
        if current is not None and current.status == "passed":
            raise CampaignGateError(
                f"cannot retry already-passed gate {record.gate_id!r} "
                "without an invalidation record"
            )
        active[record.gate_id] = record
        attempt_counts[record.gate_id] = record.attempt_index

    return _HistoryState(
        active=dict(active),
        attempt_counts=dict(attempt_counts),
        invalidation_count=invalidation_count,
    )


def campaign_active_gate_records(
    campaign_id: str,
    records: Sequence[CampaignHistoryRecord],
    *,
    evidence_root: Path,
) -> tuple[CampaignGateRecord, ...]:
    state = _history_state(campaign_id, records, evidence_root=evidence_root)
    return tuple(
        state.active[gate_id]
        for gate_id in CAMPAIGN_GATE_SEQUENCE
        if gate_id in state.active
    )


def campaign_promotion_decision(
    campaign_id: str,
    target_gate_id: str,
    records: Sequence[CampaignHistoryRecord],
    *,
    evidence_root: Path,
) -> CampaignPromotionDecision:
    """Return whether the next active attempt at target_gate_id may start."""

    if target_gate_id not in CAMPAIGN_GATE_SEQUENCE:
        raise CampaignGateError(f"unknown campaign gate: {target_gate_id!r}")
    state = _history_state(campaign_id, records, evidence_root=evidence_root)
    target_index = CAMPAIGN_GATE_SEQUENCE.index(target_gate_id)
    blockers: list[str] = []
    for prior_gate in CAMPAIGN_GATE_SEQUENCE[:target_index]:
        prior = state.active.get(prior_gate)
        if prior is None:
            blockers.append(f"{prior_gate}:missing")
        elif prior.status != "passed":
            blockers.append(f"{prior_gate}:failed")

    later_records = [
        gate_id
        for gate_id in CAMPAIGN_GATE_SEQUENCE[target_index + 1 :]
        if gate_id in state.active
    ]
    if later_records:
        raise CampaignGateError(
            f"cannot revisit {target_gate_id!r} after downstream gates: "
            f"{later_records}; append an invalidation record first"
        )

    target = state.active.get(target_gate_id)
    if target is not None and target.status == "passed":
        blockers.append(f"{target_gate_id}:already_passed")
    return CampaignPromotionDecision(
        campaign_id=campaign_id,
        target_gate_id=target_gate_id,
        eligible=not blockers,
        next_attempt_index=state.attempt_counts.get(target_gate_id, 0) + 1,
        blockers=tuple(blockers),
    )


def append_campaign_gate(
    records: Sequence[CampaignHistoryRecord],
    record: CampaignGateRecord,
    *,
    evidence_root: Path,
) -> tuple[CampaignHistoryRecord, ...]:
    """Append one gate attempt only when all active predecessors have passed."""

    if not isinstance(record, CampaignGateRecord):
        raise CampaignGateError("record must be a CampaignGateRecord")
    decision = campaign_promotion_decision(
        record.campaign_id,
        record.gate_id,
        records,
        evidence_root=evidence_root,
    )
    if not decision.eligible:
        raise CampaignGateError(
            f"campaign gate {record.gate_id!r} is blocked: {decision.blockers}"
        )
    if record.attempt_index != decision.next_attempt_index:
        raise CampaignGateError(
            f"gate {record.gate_id!r} requires attempt_index "
            f"{decision.next_attempt_index}"
        )
    combined = (*records, record)
    _history_state(record.campaign_id, combined, evidence_root=evidence_root)
    return combined


def append_campaign_invalidation(
    records: Sequence[CampaignHistoryRecord],
    record: CampaignInvalidationRecord,
    *,
    evidence_root: Path,
) -> tuple[CampaignHistoryRecord, ...]:
    """Append an audited pre-freeze invalidation without deleting old evidence."""

    if not isinstance(record, CampaignInvalidationRecord):
        raise CampaignGateError("record must be a CampaignInvalidationRecord")
    combined = (*records, record)
    _history_state(record.campaign_id, combined, evidence_root=evidence_root)
    return combined


def campaign_history_record_to_dict(record: CampaignHistoryRecord) -> dict[str, Any]:
    if isinstance(record, CampaignGateRecord):
        return {"record_type": "gate", **dataclasses.asdict(record)}
    if isinstance(record, CampaignInvalidationRecord):
        return {"record_type": "invalidation", **dataclasses.asdict(record)}
    raise CampaignGateError("record must be a campaign history record")


def campaign_history_record_from_dict(value: Mapping[str, Any]) -> CampaignHistoryRecord:
    if not isinstance(value, Mapping):
        raise CampaignGateError("campaign history record must be an object")
    record_type = value.get("record_type")
    evidence_value = value.get("evidence_refs")
    if not isinstance(evidence_value, (list, tuple)):
        raise CampaignGateError("campaign history evidence_refs must be an array")
    evidence = tuple(QCEvidenceRef.from_dict(item) for item in evidence_value)
    common = {
        "campaign_id": value.get("campaign_id"),
        "family_id": value.get("family_id"),
        "family_version": value.get("family_version"),
        "profile_id": value.get("profile_id"),
        "evidence_refs": evidence,
    }
    if record_type == "gate":
        expected = {
            "record_type",
            "campaign_id",
            "family_id",
            "family_version",
            "profile_id",
            "gate_id",
            "attempt_index",
            "status",
            "evidence_refs",
            "failure_reasons",
        }
        if set(value) != expected:
            raise CampaignGateError("gate record fields are incomplete or unexpected")
        return CampaignGateRecord(
            **common,
            gate_id=value["gate_id"],
            attempt_index=value["attempt_index"],
            status=value["status"],
            failure_reasons=tuple(value["failure_reasons"]),
        )
    if record_type == "invalidation":
        expected = {
            "record_type",
            "campaign_id",
            "family_id",
            "family_version",
            "profile_id",
            "invalidation_index",
            "from_gate_id",
            "changed_controls",
            "reason",
            "evidence_refs",
        }
        if set(value) != expected:
            raise CampaignGateError(
                "invalidation record fields are incomplete or unexpected"
            )
        return CampaignInvalidationRecord(
            **common,
            invalidation_index=value["invalidation_index"],
            from_gate_id=value["from_gate_id"],
            changed_controls=tuple(value["changed_controls"]),
            reason=value["reason"],
        )
    raise CampaignGateError(f"unknown campaign history record_type: {record_type!r}")


__all__ = [
    "CAMPAIGN_GATE_SEQUENCE",
    "CampaignGateError",
    "CampaignGateRecord",
    "CampaignHistoryRecord",
    "CampaignInvalidationRecord",
    "CampaignPromotionDecision",
    "append_campaign_gate",
    "append_campaign_invalidation",
    "campaign_active_gate_records",
    "campaign_gate_artifact_type",
    "campaign_gate_record_sha256",
    "campaign_history_record_from_dict",
    "campaign_history_record_sha256",
    "campaign_history_record_to_dict",
    "campaign_promotion_decision",
]
