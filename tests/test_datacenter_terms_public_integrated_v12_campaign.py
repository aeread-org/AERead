from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development.objective_openrouter import (
    normalize_indicator_map_output,
)
from aeread_families.datacenter_development_terms.environment import (
    DataCenterTermsPlugin,
    response_contract,
)
from aeread_families.datacenter_development_terms.public_integrated_expansion_v4_cases import (
    UNIT_INSTRUCTION,
)
from aeread_families.datacenter_development_terms.public_integrated_v12_campaign import (
    _campaign_summary,
    _cases_by_slug,
    _ordered_provider_cells,
    _run_live_cell,
    _run_provider_queue,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_integrated_v12_design_is_frozen_qwen_gptoss_panel() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 6
    assert design["planned_pair_count"] == 3
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.15)
    assert design["schema_mode"] == "complete_indicator_maps_v1"
    assert design["adapter_implementation_id"] == (
        "datacenter_objective_openrouter_indicator_map_v1"
    )
    assert {cell["inference_seed"] for cell in design["cells"]} == {422106}
    assert all(
        cell["schema_mode"] == "complete_indicator_maps_v1"
        for cell in design["cells"]
    )
    assert all(
        "public_integrated_expansion_v4" in cell["case_id"]
        for cell in design["cells"]
    )
    assert set(contract["models"]) == {
        "gptoss120b_coreweave",
        "qwen3_235b_google",
    }
    assert contract["models"]["gptoss120b_coreweave"]["reasoning_effort"] == (
        "low"
    )
    assert design["gptoss_route_history"]["comparison_scope"] == (
        "route_qualification_history_only_different_case_pack"
    )
    assert design["provider_cooldown_seconds_after_attempt"] == {
        "CoreWeave": 0.0,
        "Google": 0.0,
    }


def test_integrated_v12_units_and_tydal_invoice_day_are_visible() -> None:
    cases = _cases_by_slug()
    assert all(
        case.payload["public_case"]["prompt"].endswith(UNIT_INSTRUCTION)
        for case in cases.values()
    )
    case = cases["tydal-open-book-epc-governance-and-risk"]
    evidence = next(
        item
        for item in case.payload["public_case"]["observations"]
        if item["evidence_id"] == "e05"
    )

    assert "22nd" in evidence["content"]
    assert case.payload["oracle"]["gold"]["amounts"]["invoice_payment_day"] == 22.0


def test_integrated_v12_contract_rejects_seed_route_schema_or_lineage_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {**contract, "inference_seeds": [1]},
        {
            **contract,
            "execution": {**contract["execution"], "indicator_maps": False},
        },
        {
            **contract,
            "models": {
                **contract["models"],
                "gptoss120b_coreweave": {
                    **contract["models"]["gptoss120b_coreweave"],
                    "provider": "unsealed-provider",
                },
            },
        },
        {
            **contract,
            "gptoss_route_history": {
                **contract["gptoss_route_history"],
                "completed_cells": 14,
            },
        },
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_integrated_v12_design_rejects_aggregate_cost_above_campaign_cap() -> None:
    contract = load_contract()
    over_budget = {
        **contract,
        "execution": {
            **contract["execution"],
            "campaign_max_cost_usd": 0.149,
        },
    }

    with pytest.raises(ValueError, match="exceed campaign max"):
        build_design(over_budget)


def test_integrated_v12_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "integrated_v12"
    result = asyncio.run(
        run_campaign(run_root=run_root, stop_after="profile_admission")
    )

    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 6
    gate = json.loads(
        (run_root / "provider_free_validation" / "summary.json").read_text()
    )
    assert gate["case_count"] == 3
    assert all(row["score"] == 1.0 for row in gate["cases"])


def _indicator_response(case) -> dict[str, object]:
    vocabulary = response_contract(
        DataCenterTermsPlugin().validate_payload(case.payload)
    )
    gold = case.payload["oracle"]["gold"]
    required_actions = set(gold["required_actions"])
    required_claims = set(gold["required_claims"])
    required_evidence = set(gold["required_evidence_ids"])
    return {
        "case_id": case.case_id,
        "states": gold["states"],
        "amounts": gold["amounts"],
        "actions": {
            label: label in required_actions
            for label in vocabulary["action_candidates"]
        },
        "claims": {
            label: label in required_claims
            for label in vocabulary["claim_candidates"]
        },
        "evidence_ids": {
            label: label in required_evidence
            for label in vocabulary["evidence_ids"]
        },
        "external_actions_attempted": {"any": False},
    }


def test_integrated_v12_live_cell_executes_scores_and_replays(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    cases = _cases_by_slug()
    cell = next(
        row
        for row in build_design(contract)["cells"]
        if row["case_slug"] == "tydal-open-book-epc-governance-and-risk"
        and row["model_id"] == "gptoss120b_coreweave"
    )
    case = cases[cell["case_slug"]]
    normalized = normalize_indicator_map_output(
        canonical_json_bytes(_indicator_response(case)).decode("utf-8")
    )
    result = asyncio.run(
        _run_live_cell(
            contract,
            cell,
            cases=cases,
            run_root=tmp_path / "live",
            provider=FixedResponseProvider(normalized),
        )
    )

    assert result["status"] == "completed"
    assert result["metrics"]["score"] == 1.0
    assert result["replay_verified"] is True


def _synthetic_row(cell, *, score: float, completed: bool = True):
    return {
        **cell,
        "status": "completed" if completed else "operational_failure",
        "inclusion_status": "included" if completed else "excluded",
        "replay_verified": completed,
        "usage": {"reported_cost_usd": 0.001} if completed else None,
        "metrics": {
            "score": score,
            "hard_gate_pass": score > 0.0,
            "state_accuracy": 1.0,
            "amount_accuracy": 1.0,
            "required_action_recall": 1.0,
            "required_claim_recall": 1.0,
            "evidence_coverage": 1.0,
            "forbidden_actions": [],
            "forbidden_claims": [],
        }
        if completed
        else None,
        "failure": None
        if completed
        else {
            "failure_class": "retryable_infrastructure",
            "failure_condition": "provider_5xx",
        },
    }


def test_integrated_v12_summary_uses_qwen_minus_gptoss() -> None:
    contract = load_contract()
    design = build_design(contract)
    rows = [
        _synthetic_row(
            cell,
            score=0.9 if cell["model_id"] == "gptoss120b_coreweave" else 1.0,
        )
        for cell in design["cells"]
    ]

    summary = _campaign_summary(contract, rows)

    assert summary["reportable_pair_count"] == 3
    assert all(
        pair["qwen_minus_gptoss"] == pytest.approx(0.1)
        for pair in summary["paired_case_seed_contrasts"]
    )
    assert "qwen_minus_mistral" not in summary["paired_case_seed_contrasts"][0]


def test_integrated_v12_pair_requires_both_routes() -> None:
    contract = load_contract()
    design = build_design(contract)
    rows = [
        _synthetic_row(
            cell,
            score=1.0,
            completed=cell["model_id"] == "qwen3_235b_google",
        )
        for cell in design["cells"]
    ]

    summary = _campaign_summary(contract, rows)

    assert summary["reportable_pair_count"] == 0
    assert all(
        not pair["pair_reportable"]
        for pair in summary["paired_case_seed_contrasts"]
    )
    assert summary["cost_qualifier"] == "lower_bound"


def test_integrated_v12_provider_queues_are_deterministic_without_cooldown(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    design = build_design(contract)
    ordered = _ordered_provider_cells(contract, design["cells"])
    expected = [
        "helios-phased-capacity-revenue-and-draws",
        "lake-mariner-lease-commencement-prepaid-rent-and-land",
        "tydal-open-book-epc-governance-and-risk",
    ]
    assert [cell["case_slug"] for cell in ordered["CoreWeave"]] == expected
    assert [cell["case_slug"] for cell in ordered["Google"]] == expected

    calls: list[str] = []
    sleeps: list[float] = []

    async def fake_run_cell(
        _contract,
        cell,
        *,
        cases,
        run_root,
        provider,
    ):
        calls.append(cell["case_slug"])
        return {"cell_key": cell["cell_key"]}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    rows = asyncio.run(
        _run_provider_queue(
            contract,
            ordered["CoreWeave"],
            cases={},
            run_root=tmp_path,
            provider=object(),
            sleep=fake_sleep,
            run_cell=fake_run_cell,
        )
    )

    assert calls == expected
    assert sleeps == []
    assert [row["cell_key"] for row in rows] == [
        cell["cell_key"] for cell in ordered["CoreWeave"]
    ]
