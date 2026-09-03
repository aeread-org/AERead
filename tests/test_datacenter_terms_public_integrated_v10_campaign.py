from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development.objective_openrouter import (
    normalize_indicator_map_output,
)
from aeread_families.datacenter_development_terms.public_integrated_v10_campaign import (
    _cases_by_slug,
    _campaign_summary,
    _run_provider_queue,
    _run_live_cell,
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development_terms.public_integrated_expansion_v4_cases import (
    UNIT_INSTRUCTION,
)
from aeread_families.datacenter_development_terms.environment import (
    DataCenterTermsPlugin,
    response_contract,
)
from aeread_families.single_offer.runner import FixedResponseProvider


def test_integrated_v10_design_is_frozen_unit_explicit_60s_paced_panel() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 6
    assert design["planned_pair_count"] == 3
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.15)
    assert design["schema_mode"] == "complete_indicator_maps_v1"
    assert design["adapter_implementation_id"] == (
        "datacenter_objective_openrouter_indicator_map_v1"
    )
    assert all(
        cell["schema_mode"] == "complete_indicator_maps_v1"
        for cell in design["cells"]
    )
    assert {cell["inference_seed"] for cell in design["cells"]} == {422104}
    assert design["pack_sha256"] == (
        "a47eb3e63166a8b77b004745ccf0bdb81d3c36cf48714fbbde9c1069a2b438ad"
    )
    assert design["numeric_unit_correction"] == contract["numeric_unit_correction"]
    assert all("public_integrated_expansion_v4" in cell["case_id"] for cell in design["cells"])
    assert design["provider_schedule"] == (
        "deterministic_route_queues_parallel_across_providers"
    )
    assert design["provider_cooldown_seconds_after_attempt"] == {
        "DeepInfra": 60.0,
        "Google": 0.0,
    }
    assert set(contract["models"]) == {
        "mistral32_deepinfra",
        "qwen3_235b_google",
    }
    assert contract["alternate_route_qualification"]["provider"] == "Parasail"
    assert contract["alternate_route_qualification"]["decision"] == (
        "exclude_parasail_from_campaign"
    )


def test_integrated_v10_units_and_tydal_invoice_day_are_visible() -> None:
    cases = _cases_by_slug()
    assert all(
        case.payload["public_case"]["prompt"].endswith(UNIT_INSTRUCTION)
        for case in cases.values()
    )
    case = cases["tydal-open-book-epc-governance-and-risk"]
    e05 = next(
        item
        for item in case.payload["public_case"]["observations"]
        if item["evidence_id"] == "e05"
    )

    assert "22nd" in e05["content"]
    assert "seven days" in e05["content"]
    assert case.payload["oracle"]["gold"]["amounts"]["invoice_payment_day"] == 22.0


def test_integrated_v10_contract_rejects_route_schema_or_pacing_drift(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    candidates = (
        {**contract, "inference_seeds": [1, 2, 3]},
        {
            **contract,
            "execution": {**contract["execution"], "indicator_maps": False},
        },
        {
            **contract,
            "models": {
                **contract["models"],
                "qwen3_235b_google": {
                    **contract["models"]["qwen3_235b_google"],
                    "provider": "unsealed-provider",
                },
            },
        },
        {
            **contract,
            "execution": {
                **contract["execution"],
                "provider_cooldown_seconds_after_attempt": {
                    "DeepInfra": 0.0,
                    "Google": 0.0,
                },
            },
        },
    )
    for index, candidate in enumerate(candidates):
        path = tmp_path / f"contract-{index}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValueError):
            load_contract(path)


def test_integrated_v10_design_rejects_aggregate_cost_above_campaign_cap() -> None:
    contract = load_contract()
    over_budget = {
        **contract,
        "execution": {
            **contract["execution"],
            "campaign_max_cost_usd": 0.149,
        },
    }

    with pytest.raises(ValueError, match="exceed campaign maximum"):
        build_design(over_budget)


def test_integrated_v10_passes_provider_free_and_admission_gates(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        run_campaign(
            run_root=tmp_path / "integrated_v10",
            stop_after="profile_admission",
        )
    )
    assert result["status"] == "passed"
    assert len(result["admitted_cells"]) == 6
    gate = json.loads(
        (tmp_path / "integrated_v10/provider_free_validation/summary.json").read_text()
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


def test_integrated_v10_live_cell_executes_scores_and_replays(tmp_path: Path) -> None:
    contract = load_contract()
    cases = _cases_by_slug()
    cell = next(
        row
        for row in build_design(contract)["cells"]
        if row["case_slug"] == "tydal-open-book-epc-governance-and-risk"
        and row["model_id"] == "qwen3_235b_google"
        and row["inference_seed"] == 422104
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


def test_integrated_v10_pair_requires_both_routes() -> None:
    contract = load_contract()
    design = build_design(contract)
    rows = []
    for cell in design["cells"]:
        completed = cell["model_id"] == "qwen3_235b_google"
        rows.append(
            {
                **cell,
                "status": "completed" if completed else "operational_failure",
                "inclusion_status": "included" if completed else "excluded",
                "replay_verified": completed,
                "usage": {"reported_cost_usd": 0.001} if completed else None,
                "metrics": {
                    "score": 0.8,
                    "hard_gate_pass": True,
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
        )
    summary = _campaign_summary(contract, rows)
    assert summary["reportable_pair_count"] == 0
    assert all(
        not pair["pair_reportable"]
        for pair in summary["paired_case_seed_contrasts"]
    )


def test_integrated_v10_deepinfra_queue_is_ordered_and_cooled_down(
    tmp_path: Path,
) -> None:
    contract = load_contract()
    design = build_design(contract)
    cells = [
        cell
        for cell in design["cells"]
        if cell["model_id"] == "mistral32_deepinfra"
    ]
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
            cells,
            cases={},
            run_root=tmp_path,
            provider=object(),
            sleep=fake_sleep,
            run_cell=fake_run_cell,
        )
    )

    assert calls == [
        "helios-phased-capacity-revenue-and-draws",
        "lake-mariner-lease-commencement-prepaid-rent-and-land",
        "tydal-open-book-epc-governance-and-risk",
    ]
    assert sleeps == [60.0, 60.0]
    assert [row["cell_key"] for row in rows] == [cell["cell_key"] for cell in cells]
