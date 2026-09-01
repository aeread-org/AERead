from __future__ import annotations

import pytest

from aeread.shared_runner import (
    CAMPAIGN_GATE_SEQUENCE,
    CampaignGateError,
    CampaignGateRecord,
    append_campaign_gate,
    campaign_gate_record_sha256,
    campaign_promotion_decision,
)


def _gate(
    gate_id: str,
    *,
    attempt_index: int = 1,
    status: str = "passed",
) -> CampaignGateRecord:
    return CampaignGateRecord(
        campaign_id="housing_harness_campaign_001",
        gate_id=gate_id,
        attempt_index=attempt_index,
        status=status,
        evidence_refs=(f"evidence/{gate_id}/{attempt_index}",),
        failure_reasons=() if status == "passed" else ("declared check failed",),
    )


def test_campaign_gates_require_every_predecessor_in_order() -> None:
    records: tuple[CampaignGateRecord, ...] = ()
    blocked = campaign_promotion_decision(
        "housing_harness_campaign_001", "full_trajectory", records
    )
    assert blocked.eligible is False
    assert blocked.blockers == (
        "design_contract:missing",
        "provider_free_validation:missing",
        "profile_admission:missing",
    )

    for gate_id in CAMPAIGN_GATE_SEQUENCE:
        record = _gate(gate_id)
        records = append_campaign_gate(records, record)
        assert campaign_gate_record_sha256(record) == campaign_gate_record_sha256(
            record
        )
    assert len(records) == len(CAMPAIGN_GATE_SEQUENCE)


def test_failed_gate_can_retry_but_blocks_downstream_work() -> None:
    records = append_campaign_gate((), _gate("design_contract", status="failed"))
    blocked = campaign_promotion_decision(
        "housing_harness_campaign_001", "provider_free_validation", records
    )
    assert blocked.eligible is False
    assert blocked.blockers == ("design_contract:failed",)

    with pytest.raises(CampaignGateError, match="blocked"):
        append_campaign_gate(records, _gate("provider_free_validation"))

    retry = campaign_promotion_decision(
        "housing_harness_campaign_001", "design_contract", records
    )
    assert retry.eligible is True
    assert retry.next_attempt_index == 2
    records = append_campaign_gate(
        records, _gate("design_contract", attempt_index=2)
    )
    records = append_campaign_gate(records, _gate("provider_free_validation"))
    assert records[-1].gate_id == "provider_free_validation"


def test_campaign_gate_record_requires_evidence() -> None:
    with pytest.raises(CampaignGateError, match="evidence_refs"):
        CampaignGateRecord(
            campaign_id="campaign_001",
            gate_id="design_contract",
            attempt_index=1,
            status="passed",
            evidence_refs=(),
        )
