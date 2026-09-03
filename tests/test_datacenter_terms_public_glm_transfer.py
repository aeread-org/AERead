from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_glm_transfer_campaign import (
    MODEL_ID,
    _campaign_summary,
    _case,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_glm_transfer_publication import (
    PROHIBITED_PUBLIC_TEXT,
    publish,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_public_glm_transfer_contract_is_model_only_matched_and_bounded() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 3
    assert design["case_count"] == 1
    assert design["independent_cluster_count"] == 1
    assert design["worst_case_declared_cost_usd"] == 0.06
    assert {cell["inference_seed"] for cell in design["cells"]} == {
        316001,
        316002,
        316003,
    }
    assert {cell["case_sha256"] for cell in design["cells"]} == {
        "7fdc0e690dc69396941baa011a39a0b9523018519cd717030d0c4d5e2438bbd0"
    }
    assert contract["model"]["provider"] == "DeepInfra"
    assert contract["model"]["quantization"] == "fp8"
    assert contract["execution"]["sdk_retries"] == 0
    assert contract["execution"]["response_cache"] is False
    assert contract["execution"]["provider_fallbacks"] is False


def test_public_glm_transfer_contract_rejects_bridge_route_or_case_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {
            **contract,
            "bridge": {
                **contract["bridge"],
                "live_summary_sha256": "0" * 64,
            },
        },
        {**contract, "model": {**contract["model"], "provider": "Other"}},
        {**contract, "case": {**contract["case"], "case_sha256": "0" * 64}},
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_public_glm_transfer_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "glm_transfer",
            stop_after="profile_admission",
        )
    )
    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 3
    gate = json.loads(
        (
            tmp_path
            / "glm_transfer/provider_free_validation/summary.json"
        ).read_text()
    )
    assert gate["score"] == 1.0
    assert gate["replay_verified"] is True


def test_public_glm_transfer_live_cell_scores_and_replays(tmp_path: Path) -> None:
    contract = load_contract()
    cell = build_design(contract)["cells"][0]
    case = _case()
    gold = case.payload["oracle"]["gold"]
    response = {
        "case_id": case.case_id,
        "states": gold["states"],
        "amounts": gold["amounts"],
        "actions": gold["required_actions"],
        "claims": gold["required_claims"],
        "evidence_ids": gold["required_evidence_ids"],
        "external_actions_attempted": [],
    }
    result = asyncio.run(
        _run_live_cell(
            contract,
            cell,
            run_root=tmp_path / "live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )
    assert result["status"] == "completed"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def _completed_rows() -> list[dict[str, object]]:
    contract = load_contract()
    rows = []
    for cell in build_design(contract)["cells"]:
        rows.append(
            {
                **cell,
                "status": "completed",
                "inclusion_status": "included",
                "replay_verified": True,
                "usage": {"reported_cost_usd": 0.001},
                "metrics": {
                    "score": 0.8,
                    "hard_gate_pass": True,
                    "state_accuracy": 1.0,
                    "amount_accuracy": 1.0,
                    "required_action_recall": 0.5,
                    "required_claim_recall": 0.5,
                    "evidence_coverage": 1.0,
                    "forbidden_actions": [],
                    "forbidden_claims": [],
                },
                "failure": None,
            }
        )
    return rows


def test_public_glm_transfer_summary_applies_frozen_decision_rule() -> None:
    contract = load_contract()
    qualified = _campaign_summary(contract, _completed_rows())
    assert qualified["decision"] == "qualifies_for_five_cluster_replication"
    assert qualified["bridge_reportable_count"] == 3

    failed = copy.deepcopy(_completed_rows())
    for row in failed:
        row["metrics"]["score"] = 0.0
        row["metrics"]["hard_gate_pass"] = False
    broad_failure = _campaign_summary(contract, failed)
    assert broad_failure["decision"] == (
        "broad_model_family_failure_on_integrated_case"
    )

    missing = copy.deepcopy(_completed_rows())
    missing[0].update(
        {
            "status": "operational_failure",
            "inclusion_status": "excluded",
            "replay_verified": False,
            "usage": None,
            "metrics": None,
            "failure": {
                "failure_class": "retryable_infrastructure",
                "failure_condition": "rate_limit",
            },
        }
    )
    inconclusive = _campaign_summary(contract, missing)
    assert inconclusive["decision"] == "inconclusive_operational_missingness"
    assert inconclusive["bridge_reportable_count"] == 2
    assert inconclusive["cost_qualifier"] == "lower_bound"
    assert inconclusive["model_summary"]["hard_gate_pass_rate"] == 1.0
    assert inconclusive["winner_claim_allowed"] is False
    assert inconclusive["inferential_model_ranking_allowed"] is False
    assert MODEL_ID == "glm53_deepinfra"


def test_public_glm_transfer_publication_is_sealed_and_preserves_missingness() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_glm_transfer_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_glm_transfer_publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert manifest["source_summary_sha256"] == (
        "9bbe483028c41e9eab8103852c076efea0ffebbdeb05f3ef0daff751b6e72f70"
    )
    assert manifest["source_design_sha256"] == (
        "2a0de1742da6057c850384a680fead81f031fa00acebc4b44da8dd6d13ef6b76"
    )
    assert len(manifest["source_receipt_sha256s"]) == 3
    assert len(manifest["source_result_sha256s"]) == 3
    assert all(value is False for value in manifest["sanitization"].values())

    summary = json.loads((publication / "reports/summary.json").read_text())
    assert summary["completed_cells"] == 1
    assert summary["operational_failure_cells"] == 2
    assert summary["failure_conditions"] == ["rate_limit", "rate_limit"]
    assert summary["reported_cost_usd"] == pytest.approx(0.00018159075)
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["decision"] == "inconclusive_operational_missingness"
    assert summary["bridge_reportable_count"] == 1
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True

    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    assert len(trajectories) == 3
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["metrics"]["score"] == pytest.approx(
        0.9666666666666668
    )
    assert completed[0]["metrics"]["hard_gate_pass"] is True
    assert completed[0]["metrics"]["forbidden_actions"] == []
    assert completed[0]["metrics"]["forbidden_claims"] == []
    excluded = [row for row in trajectories if row["status"] != "completed"]
    assert len(excluded) == 2
    assert all(row["inclusion_status"] == "excluded" for row in excluded)
    assert all(row["metrics"] is None for row in excluded)

    with (publication / "tables/four_model_bridge.csv").open(newline="") as handle:
        bridge = list(csv.DictReader(handle))
    assert len(bridge) == 3
    reportable = [row for row in bridge if row["bridge_reportable"] == "True"]
    assert len(reportable) == 1
    assert reportable[0]["glm_hard_gate_pass"] == "True"
    assert reportable[0]["mistral_hard_gate_pass"] == "True"
    assert reportable[0]["qwen_hard_gate_pass"] == "False"
    assert reportable[0]["gptoss_hard_gate_pass"] == "False"

    payload = b"".join(
        path.read_bytes() for path in publication.rglob("*") if path.is_file()
    ).decode("utf-8").lower()
    assert all(token not in payload for token in PROHIBITED_PUBLIC_TEXT)


def test_public_glm_transfer_publication_is_idempotent() -> None:
    assert publish() == publish()
