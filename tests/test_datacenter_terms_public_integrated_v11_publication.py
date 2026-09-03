from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v11_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)


def test_integrated_v11_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_integrated_v11"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_integrated_v11_publication.py"
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
    assert summary["completed_cells"] == 5
    assert summary["operational_failure_cells"] == 1
    assert summary["reportable_pair_count"] == 2
    assert summary["reported_cost_usd"] == pytest.approx(0.00347697405)
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["operational_missingness_finding"] == {
        "model_id": "mistral32_deepinfra",
        "provider": "DeepInfra",
        "case_slug": "lake-mariner-lease-commencement-prepaid-rent-and-land",
        "provider_queue_position": 2,
        "observed_condition": "rate_limit",
        "affected_cells": 1,
        "model_output_available": False,
        "reported_usage_available": False,
    }
    order = summary["provider_order_finding"]
    assert order["ordered_outcomes"] == [
        {
            "position": 1,
            "case_slug": "tydal-open-book-epc-governance-and-risk",
            "status": "completed",
            "score": 1.0,
        },
        {
            "position": 2,
            "case_slug": "lake-mariner-lease-commencement-prepaid-rent-and-land",
            "status": "rate_limit",
            "score": None,
        },
        {
            "position": 3,
            "case_slug": "helios-phased-capacity-revenue-and-draws",
            "status": "completed",
            "score": 1.0,
        },
    ]
    assert order["tydal_specific_failure_supported"] is False
    assert order["deterministic_third_call_failure_supported"] is False
    assert order["causal_effect_allowed"] is False
    correction = summary["answerability_correction_verified"]
    assert set(correction["observed_values"].values()) == {22.0}
    assert set(correction["observed_scores"].values()) == {1.0}
    assert correction["replay_verified"] is True
    unit_observation = summary["numeric_unit_contract_observed"]
    assert unit_observation["observed_model_ids"] == ["qwen3_235b_google"]
    assert unit_observation["cross_route_current_run_verified"] is False
    assert "case_answerability_invalidation" not in summary
    assert summary["alternate_route_finding"]["provider"] == "Parasail"
    assert summary["alternate_route_finding"]["reported_cost_usd"] == 0.0
    assert summary["alternate_route_finding"]["substituted_into_campaign"] is False

    with (publication / "tables/cell_results.csv").open(newline="") as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 6
    mistral = [row for row in cells if row["model_id"] == "mistral32_deepinfra"]
    qwen = [row for row in cells if row["model_id"] == "qwen3_235b_google"]
    assert len([row for row in mistral if row["status"] == "completed"]) == 2
    failed_mistral = [row for row in mistral if row["status"] != "completed"]
    assert len(failed_mistral) == 1
    assert all(row["failure_condition"] == "rate_limit" for row in failed_mistral)
    assert all(row["inclusion_status"] == "excluded" for row in failed_mistral)
    assert failed_mistral[0]["case_slug"] == (
        "lake-mariner-lease-commencement-prepaid-rent-and-land"
    )
    assert all(row["route_verified"] == "True" for row in qwen)
    assert all(row["replay_verified"] == "True" for row in qwen)
    completed = [row for row in cells if row["status"] == "completed"]
    assert len(completed) == 5
    assert all(float(row["score"]) == 1.0 for row in completed)
    assert all(row["hard_gate_pass"] == "True" for row in completed)

    with (publication / "tables/paired_contrasts.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 3
    reportable = [row for row in pairs if row["pair_reportable"] == "True"]
    missing = [row for row in pairs if row["pair_reportable"] == "False"]
    assert len(reportable) == 2
    assert {row["case_slug"] for row in reportable} == {
        "helios-phased-capacity-revenue-and-draws",
        "tydal-open-book-epc-governance-and-risk",
    }
    assert all(float(row["qwen_minus_mistral"]) == 0.0 for row in reportable)
    assert len(missing) == 1
    assert missing[0]["case_slug"] == (
        "lake-mariner-lease-commencement-prepaid-rent-and-land"
    )
    assert all(row["qwen_minus_mistral"] == "" for row in missing)

    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    completed_trajectories = [
        row for row in trajectories if row["status"] == "completed"
    ]
    assert len(completed_trajectories) == 5
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


def test_integrated_v11_publication_is_idempotent() -> None:
    assert publish() == publish()
