from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v4_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)


def test_integrated_v4_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_integrated_v4"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_integrated_v4_publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert len(manifest["source_receipt_sha256s"]) == 18
    assert len(manifest["source_result_sha256s"]) == 18
    assert all(value is False for value in manifest["sanitization"].values())

    summary = json.loads((publication / "reports/summary.json").read_text())
    assert summary["completed_cells"] == 9
    assert summary["operational_failure_cells"] == 9
    assert summary["reportable_pair_count"] == 0
    assert summary["reported_cost_usd"] == pytest.approx(0.0066202488)
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["completed_outputs_with_duplicate_array_labels"] == 0
    assert summary["provider_capability_finding"] == {
        "model_id": "mistral32_deepinfra",
        "provider": "DeepInfra",
        "observed_condition": "schema_keyword_unsupported",
        "schema_keyword": "uniqueItems",
        "affected_cells": 9,
    }

    with (publication / "tables/cell_results.csv").open(newline="") as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 18
    mistral = [row for row in cells if row["model_id"] == "mistral32_deepinfra"]
    qwen = [row for row in cells if row["model_id"] == "qwen3_235b_google"]
    assert all(row["failure_condition"] == "provider_5xx" for row in mistral)
    assert all(row["inclusion_status"] == "excluded" for row in mistral)
    assert all(row["route_verified"] == "True" for row in qwen)
    assert all(row["replay_verified"] == "True" for row in qwen)

    with (publication / "tables/paired_contrasts.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))
    assert len(pairs) == 9
    assert all(row["pair_reportable"] == "False" for row in pairs)
    assert all(row["qwen_minus_mistral"] == "" for row in pairs)

    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert len(completed) == 9
    for row in completed:
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


def test_integrated_v4_publication_is_idempotent() -> None:
    assert publish() == publish()
