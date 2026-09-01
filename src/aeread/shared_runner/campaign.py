"""Sequential experiment-campaign gates.

The runner owns episode execution; this module owns the promotion decision that
must happen before a campaign advances to a more expensive or more reportable
stage. Gate records are evidence pointers, not replacements for RunPlans,
receipts, or sealed evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from .resolver import canonical_json_bytes
from .schemas import is_exportable_id


class CampaignGateError(ValueError):
    """Campaign gate history is invalid or an attempted promotion is blocked."""


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


def _require_id(value: object, label: str) -> str:
    if not is_exportable_id(value):
        raise CampaignGateError(f"{label} must be an exportable identifier")
    return value


def _require_text_tuple(values: object, label: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise CampaignGateError(f"{label} must be a non-empty tuple")
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise CampaignGateError(f"{label} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise CampaignGateError(f"{label} must not contain duplicates")
    return values


@dataclass(frozen=True, slots=True)
class CampaignGateRecord:
    """One evidence-backed attempt at a campaign gate.

    Failed gates remain in the history. A later attempt may pass the same gate,
    but no downstream gate can be appended until the latest attempt has passed.
    """

    campaign_id: str
    gate_id: str
    attempt_index: int
    status: str
    evidence_refs: tuple[str, ...]
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.campaign_id, "campaign_id")
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
        _require_text_tuple(self.evidence_refs, "evidence_refs")
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


@dataclass(frozen=True, slots=True)
class CampaignPromotionDecision:
    campaign_id: str
    target_gate_id: str
    eligible: bool
    next_attempt_index: int
    blockers: tuple[str, ...]


def campaign_gate_record_sha256(record: CampaignGateRecord) -> str:
    if not isinstance(record, CampaignGateRecord):
        raise CampaignGateError("record must be a CampaignGateRecord")
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _latest_gate_records(
    campaign_id: str,
    records: Sequence[CampaignGateRecord],
) -> dict[str, CampaignGateRecord]:
    _require_id(campaign_id, "campaign_id")
    latest: dict[str, CampaignGateRecord] = {}
    attempts: dict[str, set[int]] = {}
    seen_digests: set[str] = set()
    for record in records:
        if not isinstance(record, CampaignGateRecord):
            raise CampaignGateError(
                "gate history must contain only CampaignGateRecord values"
            )
        if record.campaign_id != campaign_id:
            raise CampaignGateError("gate history mixes campaign identities")
        digest = campaign_gate_record_sha256(record)
        if digest in seen_digests:
            raise CampaignGateError("gate history contains a duplicate record")
        seen_digests.add(digest)
        attempts.setdefault(record.gate_id, set()).add(record.attempt_index)
        previous = latest.get(record.gate_id)
        if previous is None or record.attempt_index > previous.attempt_index:
            latest[record.gate_id] = record
    for gate_id, observed in attempts.items():
        expected = set(range(1, max(observed) + 1))
        if observed != expected:
            raise CampaignGateError(
                f"gate {gate_id!r} attempt indexes must be contiguous from one"
            )
    return latest


def campaign_promotion_decision(
    campaign_id: str,
    target_gate_id: str,
    records: Sequence[CampaignGateRecord],
) -> CampaignPromotionDecision:
    """Return whether the next attempt at ``target_gate_id`` may start."""

    if target_gate_id not in CAMPAIGN_GATE_SEQUENCE:
        raise CampaignGateError(f"unknown campaign gate: {target_gate_id!r}")
    latest = _latest_gate_records(campaign_id, records)
    target_index = CAMPAIGN_GATE_SEQUENCE.index(target_gate_id)
    blockers: list[str] = []
    for prior_gate in CAMPAIGN_GATE_SEQUENCE[:target_index]:
        prior = latest.get(prior_gate)
        if prior is None:
            blockers.append(f"{prior_gate}:missing")
        elif prior.status != "passed":
            blockers.append(f"{prior_gate}:failed")

    later_records = [
        gate_id
        for gate_id in CAMPAIGN_GATE_SEQUENCE[target_index + 1 :]
        if gate_id in latest
    ]
    if later_records:
        raise CampaignGateError(
            f"cannot revisit {target_gate_id!r} after downstream gates: "
            f"{later_records}"
        )

    target = latest.get(target_gate_id)
    if target is not None and target.status == "passed":
        blockers.append(f"{target_gate_id}:already_passed")
    next_attempt_index = 1 if target is None else target.attempt_index + 1
    return CampaignPromotionDecision(
        campaign_id=campaign_id,
        target_gate_id=target_gate_id,
        eligible=not blockers,
        next_attempt_index=next_attempt_index,
        blockers=tuple(blockers),
    )


def append_campaign_gate(
    records: Sequence[CampaignGateRecord],
    record: CampaignGateRecord,
) -> tuple[CampaignGateRecord, ...]:
    """Append one gate attempt only when all predecessor gates have passed."""

    if not isinstance(record, CampaignGateRecord):
        raise CampaignGateError("record must be a CampaignGateRecord")
    decision = campaign_promotion_decision(
        record.campaign_id, record.gate_id, records
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
    return (*records, record)


__all__ = [
    "CAMPAIGN_GATE_SEQUENCE",
    "CampaignGateError",
    "CampaignGateRecord",
    "CampaignPromotionDecision",
    "append_campaign_gate",
    "campaign_gate_record_sha256",
    "campaign_promotion_decision",
]
