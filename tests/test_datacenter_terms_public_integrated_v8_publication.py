from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v8_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)


def test_integrated_v8_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_integrated_v8"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_integrated_v8_publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert len(manifest["source_receipt_sha256s"]) == 6
    assert len(manifest["source_result_sha256s"]) == 6
    assert all(value is False for value in manifest["sanitization"].values())

    summary = json.loads((publication / "reports/summary.json").read_text())
    assert summary["completed_cells"] == 6
    assert summary["operational_failure_cells"] == 0
    assert summary["reportable_pair_count"] == 3
    assert summary["raw_reportable_pair_count"] == 3
    assert summary["interpretable_pair_count"] == 2
    assert summary["reported_cost_usd"] == pytest.approx(0.00385881705)
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["provider_pacing_finding"] == {
        "model_id": "mistral32_deepinfra",
        "provider": "DeepInfra",
        "v7_completed_cells": 1,
        "v7_planned_cells": 3,
        "v8_completed_cells": 3,
        "v8_planned_cells": 3,
        "cooldown_seconds_after_attempt": 30.0,
        "causal_effect_allowed": False,
        "disposition": "operationally_promising_requires_replication",
    }
    correction = summary["answerability_correction_verified"]
    assert correction["case_slug"] == "tydal-open-book-epc-governance-and-risk"
    assert correction["oracle_field"] == "amounts.invoice_payment_day"
    assert correction["visible_value_restored"] == 22.0
    assert set(correction["observed_values"].values()) == {22.0}
    assert set(correction["observed_scores"].values()) == {1.0}
    assert correction["replay_verified"] is True
    assert "case_answerability_invalidation" not in summary
    invalidation = summary["amount_unit_answerability_invalidation"]
    assert invalidation["ambiguous_fields"] == [
        "amounts.prepaid_rent_received",
        "amounts.current_deferred_rent",
        "amounts.noncurrent_deferred_rent",
        "amounts.remaining_deferred_rent",
    ]
    assert invalidation["schema_unit"] == "unspecified_number"
    assert invalidation["raw_case_score_interpretable"] is False
    assert invalidation["raw_pair_delta_interpretable"] is False
    assert invalidation["separate_unambiguous_error"] == {
        "field": "amounts.conditional_power_access_gross_mw",
        "visible_and_oracle_value": 750.0,
        "model_value": 250.0,
    }
    assert summary["alternate_route_finding"]["provider"] == "Parasail"
    assert summary["alternate_route_finding"]["reported_cost_usd"] == 0.0
    assert summary["alternate_route_finding"]["substituted_into_campaign"] is False

    with (publication / "tables/cell_results.csv").open(newline="") as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 6
    mistral = [row for row in cells if row["model_id"] == "mistral32_deepinfra"]
    qwen = [row for row in cells if row["model_id"] == "qwen3_235b_google"]
    assert len(mistral) == 3
    assert len(qwen) == 3
    completed = [row for row in cells if row["status"] == "completed"]
    assert len(completed) == 6
    assert all(row["route_verified"] == "True" for row in completed)
    assert all(row["replay_verified"] == "True" for row in completed)
    assert all(row["hard_gate_pass"] == "True" for row in completed)
    lake_mistral = next(
        row
        for row in cells
        if row["model_id"] == "mistral32_deepinfra"
        and row["case_slug"]
        == "lake-mariner-lease-commencement-prepaid-rent-and-land"
    )
    assert float(lake_mistral["score"]) == pytest.approx(0.9444444444444444)

    with (publication / "tables/paired_contrasts.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 3
    reportable = [row for row in pairs if row["pair_reportable"] == "True"]
    interpretable = [
        row for row in pairs if row["interpretation_reportable"] == "True"
    ]
    invalidated = [
        row for row in pairs if row["interpretation_reportable"] == "False"
    ]
    assert len(reportable) == 3
    assert {row["case_slug"] for row in interpretable} == {
        "helios-phased-capacity-revenue-and-draws",
        "tydal-open-book-epc-governance-and-risk",
    }
    assert all(float(row["qwen_minus_mistral"]) == 0.0 for row in interpretable)
    assert len(invalidated) == 1
    assert invalidated[0]["case_slug"] == (
        "lake-mariner-lease-commencement-prepaid-rent-and-land"
    )
    assert invalidated[0]["interpretation_exclusion_reason"] == (
        "ambiguous_currency_unit_contract"
    )
    assert float(invalidated[0]["qwen_minus_mistral"]) == pytest.approx(
        0.05555555555555558
    )

    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    completed_trajectories = [
        row for row in trajectories if row["status"] == "completed"
    ]
    assert len(completed_trajectories) == 6
    for row in completed_trajectories:
        for field in (
            "actions",
            "claims",
            "evidence_ids",
            "external_actions_attempted",
        ):
            values = row["parsed_output"][field]
            assert len(values) == len(set(values))

    payload = b"".join(
        path.read_bytes() for path in publication.rglob("*") if path.is_file()
    ).decode("utf-8").lower()
    assert all(token not in payload for token in PROHIBITED_PUBLIC_TEXT)


@pytest.mark.local_run("datacenter_development_terms_public_integrated_v8")
def test_integrated_v8_publication_is_idempotent() -> None:
    assert publish() == publish()
