from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development_terms.public_integrated_v4_campaign import (
    _campaign_summary,
    _cases_by_slug,
    _run_live_cell,
    _setup,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_integrated_v4_is_unique_array_paired_and_bounded() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["schema_mode"] == "unique_array_items_v1"
    assert design["planned_cells"] == 18
    assert design["planned_pair_count"] == 9
    assert design["worst_case_declared_cost_usd"] == 0.36
    assert {cell["inference_seed"] for cell in design["cells"]} == {
        321001,
        321002,
        321003,
    }
    assert all(cell["schema_mode"] == "unique_array_items_v1" for cell in design["cells"])
    cases = _cases_by_slug()
    setup = _setup(contract, design["cells"][0], cases)
    schema = setup.plan.agent_profiles[0].harness.config["output_schema"]
    for field in (
        "actions",
        "claims",
        "evidence_ids",
        "external_actions_attempted",
    ):
        assert schema["properties"][field]["uniqueItems"] is True
    assert contract["analysis"]["winner_claim_allowed"] is False


def test_integrated_v4_rejects_schema_lineage_and_route_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {
            **contract,
            "execution": {**contract["execution"], "unique_array_items": False},
        },
        {
            **contract,
            "predecessor": {
                **contract["predecessor"],
                "status": "valid",
            },
        },
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
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_integrated_v4_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "integrated_v4",
            stop_after="profile_admission",
        )
    )
    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 18


def test_integrated_v4_live_cell_executes_scores_and_replays(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    cases = _cases_by_slug()
    cell = next(
        row
        for row in build_design(contract)["cells"]
        if row["case_slug"] == "horizon-tranche-acceptance-financing-guarantees"
        and row["model_id"] == "qwen3_235b_google"
        and row["inference_seed"] == 321001
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


def test_integrated_v4_summary_preserves_pair_missingness() -> None:
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
    rows = copy.deepcopy(rows)
    target = next(
        row
        for row in rows
        if row["case_slug"] == "black-pearl-phased-rent-debt-and-overrun"
        and row["model_id"] == "qwen3_235b_google"
        and row["inference_seed"] == 321001
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
    assert summary["reportable_pair_count"] == 8
    assert summary["cost_qualifier"] == "lower_bound"
    missing = [
        row
        for row in summary["paired_case_seed_contrasts"]
        if not row["pair_reportable"]
    ]
    assert len(missing) == 1
    assert missing[0]["model_scores"] is None
