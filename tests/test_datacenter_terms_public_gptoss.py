from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_gptoss_campaign import (
    MODEL_ID,
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_gptoss_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_public_gptoss_addon_is_hash_bridged_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 15
    assert design["case_count"] == 5
    assert design["independent_cluster_count"] == 5
    assert design["worst_case_declared_cost_usd"] == 0.3
    assert design["bridge"] == contract["bridge"]
    assert all(cell["model_id"] == MODEL_ID for cell in design["cells"])
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert contract["model"]["requested_model"] == "openai/gpt-oss-120b"
    assert contract["model"]["provider"] == "CoreWeave"
    assert contract["model"]["quantization"] == "fp4"
    assert contract["model"]["license_id"] == "Apache-2.0"
    assert contract["execution"]["sdk_retries"] == 0
    assert contract["execution"]["response_cache"] is False
    assert contract["execution"]["provider_fallbacks"] is False
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["project_generalization_allowed"] is False


def test_public_gptoss_contract_rejects_bridge_or_route_drift(tmp_path: Path) -> None:
    contract = load_contract()
    for field, value in (
        ("bridge", {**contract["bridge"], "live_summary_sha256": "0" * 64}),
        ("model", {**contract["model"], "provider": "unsealed-provider"}),
    ):
        candidate = {**contract, field: value}
        path = tmp_path / f"{field}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_public_gptoss_passes_reexecuted_gate_and_admission(tmp_path: Path) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "gptoss_campaign",
            stop_after="profile_admission",
        )
    )

    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 15
    gate = json.loads(
        (
            tmp_path
            / "gptoss_campaign/provider_free_validation/summary.json"
        ).read_text()
    )
    assert gate["mode"] == "reexecuted_same_pack_environment_scorer_and_cases"
    assert gate["case_count"] == 5


def test_public_gptoss_live_cell_executes_scores_and_replays(tmp_path: Path) -> None:
    contract = load_contract()
    design = build_design(contract)
    cell = next(
        row
        for row in design["cells"]
        if row["case_slug"] == "ground-lease-commencement-boundary"
        and row["inference_seed"] == 314001
    )
    case = _cases_by_slug()[cell["case_slug"]]
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
            run_root=tmp_path / "gptoss_live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )

    assert result["status"] == "completed"
    assert result["inclusion_status"] == "included"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def test_public_gptoss_summary_keeps_failure_as_missingness() -> None:
    contract = load_contract()
    rows = []
    for cell in build_design(contract)["cells"]:
        excluded = cell["cell_key"] == (
            "ground-lease-commencement-boundary__"
            f"{MODEL_ID}__seed_314001"
        )
        rows.append(
            {
                **cell,
                "status": "operational_failure" if excluded else "completed",
                "inclusion_status": "excluded" if excluded else "included",
                "replay_verified": not excluded,
                "usage": (
                    None
                    if excluded
                    else {
                        "reported_cost_usd": 0.001,
                        "input_tokens": 1,
                        "cached_input_tokens": 0,
                        "output_tokens": 1,
                    }
                ),
                "metrics": (
                    None
                    if excluded
                    else {
                        "score": 0.8,
                        "hard_gate_pass": True,
                        "state_accuracy": 1.0,
                        "amount_accuracy": 1.0,
                        "required_action_recall": 0.5,
                        "required_claim_recall": 0.5,
                        "evidence_coverage": 1.0,
                    }
                ),
                "failure": (
                    {
                        "failure_class": "retryable_infrastructure",
                        "failure_condition": "rate_limit",
                    }
                    if excluded
                    else None
                ),
            }
        )

    summary = _campaign_summary(contract, rows)

    assert summary["planned_cells"] == 15
    assert summary["completed_cells"] == 14
    assert summary["operational_failure_cells"] == 1
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["model_summary"]["completion_rate"] == 14 / 15
    missing = [
        row
        for row in summary["bridge_rows"]
        if row["pair_key"] == "ground-lease-commencement-boundary__seed_314001"
    ]
    assert missing == [
        {
            "pair_key": "ground-lease-commencement-boundary__seed_314001",
            "case_slug": "ground-lease-commencement-boundary",
            "source_cluster_id": "sec_fermi_ground_lease_2025",
            "inference_seed": 314001,
            "bridge_reportable": False,
            "scores": None,
            "hard_gate_pass": None,
        }
    ]


def test_public_gptoss_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_gptoss_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_gptoss_publication.py"
        ).read_bytes()
    ).hexdigest()
    helper_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/publication.py"
        ).read_bytes()
    ).hexdigest()

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert manifest["publisher_helper_sha256"] == helper_hash
    assert len(manifest["source_receipt_sha256s"]) == 15
    assert len(set(manifest["source_receipt_sha256s"])) == 15
    assert len(manifest["source_result_sha256s"]) == 15
    assert len(set(manifest["source_result_sha256s"])) == 15
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_public_gptoss_publication_preserves_safety_and_bridge_results() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_public_gptoss_v1"
    )
    summary = json.loads((publication / "reports/summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    receipts = (publication / "receipts/projections.jsonl").read_text().splitlines()
    with (publication / "tables/three_model_bridge.csv").open(newline="") as handle:
        bridge = list(csv.DictReader(handle))

    assert summary["planned_cells"] == 15
    assert summary["completed_cells"] == 15
    assert summary["included_cells"] == 15
    assert summary["operational_failure_cells"] == 0
    assert summary["reported_cost_usd"] == 0.0018843759
    assert summary["cost_qualifier"] == "exact"
    assert summary["model_summary"]["completion_rate"] == 1.0
    assert summary["model_summary"]["hard_gate_pass_rate"] == 0.8
    assert summary["model_summary"]["mean_score"] == 0.5163333333333333
    assert summary["bridge_reportable_count"] == 12
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["all_completed_receipts_replayed"] is True
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["project_generalization_allowed"] is False

    assert len(trajectories) == 15
    assert len(receipts) == 15
    assert all(row["status"] == "completed" for row in trajectories)
    assert all(row["inclusion_status"] == "included" for row in trajectories)
    assert all(row["route_verified"] is True for row in trajectories)
    assert all(row["replay_verified"] is True for row in trajectories)
    failures = [row for row in trajectories if not row["metrics"]["hard_gate_pass"]]
    assert {row["cell_key"] for row in failures} == {
        "linked-land-power-construction-underwriting__"
        f"{MODEL_ID}__seed_314001",
        "linked-land-power-construction-underwriting__"
        f"{MODEL_ID}__seed_314002",
        "linked-land-power-construction-underwriting__"
        f"{MODEL_ID}__seed_314003",
    }
    assert all(row["metrics"]["score"] == 0.0 for row in failures)
    assert all(
        "underwrite_as_fixed_price_epc" in row["metrics"]["forbidden_actions"]
        for row in failures
    )
    assert all(
        row["metrics"]["forbidden_claims"]
        == ["ground_lease_survives_power_termination"]
        for row in failures
    )
    assert sorted(row["metrics"]["component_mean"] for row in failures) == [
        0.8333333333333334,
        0.9666666666666668,
        1.0,
    ]

    assert len(bridge) == 15
    reportable = [row for row in bridge if row["bridge_reportable"] == "True"]
    assert len(reportable) == 12
    assert all(
        float(row["gptoss_score"])
        <= max(float(row["mistral_score"]), float(row["qwen_score"]))
        for row in reportable
    )
    profiles = [
        row
        for row in csv.DictReader(
            (publication / "tables/profiles.csv").open(newline="")
        )
    ]
    assert len(profiles) == 15
    assert {row["provider"] for row in profiles} == {"CoreWeave"}
    assert {row["quantization"] for row in profiles} == {"fp4"}
