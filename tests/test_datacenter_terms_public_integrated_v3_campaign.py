from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v3_campaign import (
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_integrated_v3_is_two_route_paired_and_bounded() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["case_count"] == 3
    assert design["independent_cluster_count"] == 3
    assert design["planned_cells"] == 18
    assert design["planned_pair_count"] == 9
    assert design["worst_case_declared_cost_usd"] == 0.36
    assert {cell["model_id"] for cell in design["cells"]} == {
        "mistral32_deepinfra",
        "qwen3_235b_google",
    }
    assert {cell["inference_seed"] for cell in design["cells"]} == {
        320001,
        320002,
        320003,
    }
    assert contract["predecessor"]["gptoss_completion_count_across_v1_v2"] == 0
    assert contract["predecessor"]["gptoss_planned_cells_across_v1_v2"] == 18
    assert contract["models"]["qwen3_235b_google"]["provider"] == "Google"
    assert contract["models"]["qwen3_235b_google"]["quantization"] == "unknown"
    assert contract["execution"]["provider_fallbacks"] is False
    assert contract["analysis"]["winner_claim_allowed"] is False


def test_integrated_v3_rejects_route_lineage_and_budget_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {
            **contract,
            "models": {
                **contract["models"],
                "qwen3_235b_google": {
                    **contract["models"]["qwen3_235b_google"],
                    "max_prompt_price_per_million": "0.25",
                },
            },
        },
        {
            **contract,
            "predecessor": {
                **contract["predecessor"],
                "gptoss_completion_count_across_v1_v2": 1,
            },
        },
        {
            **contract,
            "execution": {
                **contract["execution"],
                "campaign_max_cost_usd": 0.35,
            },
        },
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_integrated_v3_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "integrated_v3",
            stop_after="profile_admission",
        )
    )
    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 18


def test_integrated_v3_live_cell_executes_scores_and_replays(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    cases = _cases_by_slug()
    cell = next(
        row
        for row in build_design(contract)["cells"]
        if row["case_slug"] == "horizon-tranche-acceptance-financing-guarantees"
        and row["model_id"] == "qwen3_235b_google"
        and row["inference_seed"] == 320001
    )
    case = cases[cell["case_slug"]]
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
            cases=cases,
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
    return [
        {
            **cell,
            "status": "completed",
            "inclusion_status": "included",
            "replay_verified": True,
            "elapsed_seconds": 1.0,
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
        for cell in build_design(contract)["cells"]
    ]


def test_integrated_v3_summary_preserves_pair_missingness() -> None:
    contract = load_contract()
    rows = copy.deepcopy(_completed_rows())
    target = next(
        row
        for row in rows
        if row["case_slug"] == "black-pearl-phased-rent-debt-and-overrun"
        and row["model_id"] == "qwen3_235b_google"
        and row["inference_seed"] == 320001
    )
    target.update(
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

    summary = _campaign_summary(contract, rows)
    missing = [
        row
        for row in summary["paired_case_seed_contrasts"]
        if not row["pair_reportable"]
    ]
    assert summary["planned_cells"] == 18
    assert summary["completed_cells"] == 17
    assert summary["reportable_pair_count"] == 8
    assert summary["cost_qualifier"] == "lower_bound"
    assert len(missing) == 1
    assert missing[0]["model_scores"] is None
    assert missing[0]["qwen_minus_mistral"] is None
