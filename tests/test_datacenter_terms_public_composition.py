from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_composition_campaign import (
    CONDITION_ORDER,
    MODEL_ORDER,
    _campaign_summary,
    _cases_by_condition,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_composition_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_public_composition_design_is_matched_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 18
    assert design["planned_wording_pair_count"] == 9
    assert design["planned_composition_bundle_count"] == 18
    assert design["integrated_case_count"] == 2
    assert design["mechanism_count"] == 3
    assert design["independent_cluster_count"] == 1
    assert design["worst_case_declared_cost_usd"] == 0.36
    assert {cell["wording_condition"] for cell in design["cells"]} == set(
        CONDITION_ORDER
    )
    assert {cell["model_id"] for cell in design["cells"]} == set(MODEL_ORDER)
    assert {cell["inference_seed"] for cell in design["cells"]} == {
        315001,
        315002,
        315003,
    }
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert contract["execution"]["max_output_tokens"] == 900
    assert contract["execution"]["sdk_retries"] == 0
    assert contract["execution"]["response_cache"] is False
    assert contract["execution"]["provider_fallbacks"] is False
    assert contract["analysis"]["score_difference_allowed"] is False
    assert contract["analysis"]["composition_causal_effect_allowed"] is False


def test_public_composition_contract_rejects_bridge_case_or_route_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {
            **contract,
            "mechanism_bridge": {
                **contract["mechanism_bridge"],
                "trajectory_sha256": "0" * 64,
            },
        },
        {
            **contract,
            "integrated_cases": {
                **contract["integrated_cases"],
                "affirm_only": {
                    **contract["integrated_cases"]["affirm_only"],
                    "expected_case_sha256": "0" * 64,
                },
            },
        },
        {
            **contract,
            "models": {
                **contract["models"],
                "mistral32_deepinfra": {
                    **contract["models"]["mistral32_deepinfra"],
                    "provider": "unsealed-provider",
                },
            },
        },
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_public_composition_passes_gate_and_matched_admission(tmp_path: Path) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "composition_campaign",
            stop_after="profile_admission",
        )
    )

    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 18
    gate = json.loads(
        (
            tmp_path
            / "composition_campaign/provider_free_validation/summary.json"
        ).read_text()
    )
    assert gate["mode"] == "reexecuted_integrated_cases_environment_scorer_and_oracles"
    assert gate["case_count"] == 2
    assert all(row["score"] == 1.0 for row in gate["cases"])


def test_public_composition_live_cell_executes_scores_and_replays(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    design = build_design(contract)
    cell = next(
        row
        for row in design["cells"]
        if row["wording_condition"] == "affirm_only"
        and row["model_id"] == "gptoss120b_coreweave"
        and row["inference_seed"] == 315001
    )
    case = _cases_by_condition()["affirm_only"]
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
            cases=_cases_by_condition(),
            run_root=tmp_path / "composition_live",
            provider=FixedResponseProvider(
                canonical_json_bytes(response).decode("utf-8")
            ),
        )
    )

    assert result["status"] == "completed"
    assert result["inclusion_status"] == "included"
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
                "usage": {
                    "reported_cost_usd": 0.001,
                    "input_tokens": 1,
                    "cached_input_tokens": 0,
                    "output_tokens": 1,
                },
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


def test_public_composition_summary_preserves_bundle_missingness_and_gaps() -> None:
    contract = load_contract()
    rows = _completed_rows()
    summary = _campaign_summary(contract, rows)

    assert summary["planned_cells"] == 18
    assert summary["completed_cells"] == 18
    assert summary["reportable_wording_pair_count"] == 9
    assert summary["planned_composition_bundle_count"] == 18
    assert summary["reportable_composition_bundle_count"] == 17
    assert summary["composition_gap_count"] == 0
    assert summary["component_only_gap_count"] == 3
    assert summary["score_difference_reported_across_granularity"] is False
    missing = [
        row for row in summary["composition_bundles"] if not row["bundle_reportable"]
    ]
    assert [row["composition_key"] for row in missing] == [
        "affirm_only__mistral32_deepinfra__seed_315002"
    ]

    qwen_failures = copy.deepcopy(rows)
    for row in qwen_failures:
        if (
            row["wording_condition"] == "affirm_only"
            and row["model_id"] == "qwen3_235b_novita"
        ):
            row["metrics"]["score"] = 0.0
            row["metrics"]["hard_gate_pass"] = False
            row["metrics"]["forbidden_actions"] = [
                "treat_executed_assignment_as_effective"
            ]
    with_gaps = _campaign_summary(contract, qwen_failures)

    assert with_gaps["composition_gap_count"] == 3
    qwen = next(
        row
        for row in with_gaps["model_composition_summaries"]
        if row["model_id"] == "qwen3_235b_novita"
    )
    assert qwen["planned_bundles"] == 6
    assert qwen["reportable_bundles"] == 6
    assert qwen["composition_gaps"] == 3
    assert qwen["component_only_gaps"] == 1


def test_public_composition_publication_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_development_terms_public_composition_v1"
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development_terms/"
            "public_composition_publication.py"
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
    assert len(manifest["source_receipt_sha256s"]) == 18
    assert len(set(manifest["source_receipt_sha256s"])) == 18
    assert len(manifest["source_result_sha256s"]) == 18
    assert len(set(manifest["source_result_sha256s"])) == 18
    assert all(value is False for value in manifest["sanitization"].values())
    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_public_composition_publication_preserves_observed_result() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_development_terms_public_composition_v1"
    )
    summary = json.loads((publication / "reports/summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    receipts = (publication / "receipts/projections.jsonl").read_text().splitlines()
    with (publication / "tables/integrated_wording_contrasts.csv").open(
        newline=""
    ) as handle:
        wording = list(csv.DictReader(handle))
    with (publication / "tables/composition_bundles.csv").open(
        newline=""
    ) as handle:
        composition = list(csv.DictReader(handle))

    assert summary["planned_cells"] == 18
    assert summary["completed_cells"] == 16
    assert summary["included_cells"] == 16
    assert summary["operational_failure_cells"] == 2
    assert summary["failure_conditions"] == ["rate_limit", "rate_limit"]
    assert summary["reported_cost_usd"] == 0.003231954
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["reportable_wording_pair_count"] == 7
    assert summary["reportable_composition_bundle_count"] == 15
    assert summary["composition_gap_count"] == 6
    assert summary["component_only_gap_count"] == 1
    assert summary["independent_cluster_count"] == 1
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["all_completed_receipts_replayed"] is True
    assert summary["score_difference_reported_across_granularity"] is False
    assert summary["composition_causal_effect_allowed"] is False
    assert summary["winner_claim_allowed"] is False

    assert len(trajectories) == 18
    assert len(receipts) == 18
    excluded = [row for row in trajectories if row["status"] != "completed"]
    assert {row["cell_key"] for row in excluded} == {
        "integrated-baseline__gptoss120b_coreweave__seed_315001",
        "integrated-baseline__gptoss120b_coreweave__seed_315003",
    }
    assert all(row["inclusion_status"] == "excluded" for row in excluded)
    assert all(
        row["failure"]
        == {
            "failure_class": "retryable_infrastructure",
            "failure_condition": "rate_limit",
        }
        for row in excluded
    )
    completed = [row for row in trajectories if row["status"] == "completed"]
    assert all(row["route_verified"] is True for row in completed)
    assert all(row["replay_verified"] is True for row in completed)

    assert len(wording) == 9
    reportable_wording = [row for row in wording if row["pair_reportable"] == "True"]
    assert len(reportable_wording) == 7
    assert {
        row["pair_key"]
        for row in reportable_wording
        if row["hard_gate_rescue"] == "True"
    } == {"integrated__gptoss120b_coreweave__seed_315002"}
    assert {
        row["pair_key"]
        for row in reportable_wording
        if row["hard_gate_regression"] == "True"
    } == {"integrated__qwen3_235b_novita__seed_315003"}

    assert len(composition) == 18
    reportable_composition = [
        row for row in composition if row["bundle_reportable"] == "True"
    ]
    assert len(reportable_composition) == 15
    assert all(row["score_difference_reported"] == "False" for row in composition)
    assert {
        row["composition_key"]
        for row in reportable_composition
        if row["composition_gap"] == "True"
    } == {
        "affirm_only__qwen3_235b_novita__seed_315001",
        "affirm_only__qwen3_235b_novita__seed_315002",
        "affirm_only__qwen3_235b_novita__seed_315003",
        "baseline__gptoss120b_coreweave__seed_315002",
        "baseline__qwen3_235b_novita__seed_315001",
        "baseline__qwen3_235b_novita__seed_315002",
    }
    assert {
        row["composition_key"]
        for row in reportable_composition
        if row["component_only_gap"] == "True"
    } == {"baseline__qwen3_235b_novita__seed_315003"}
