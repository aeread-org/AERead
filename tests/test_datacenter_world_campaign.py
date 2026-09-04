from __future__ import annotations

import asyncio
import copy
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from aeread_families.datacenter_development.world_campaign import (
    DEFAULT_PACK_ROOT,
    build_design,
    load_contract,
    load_pack,
    render_leaderboard,
    run_campaign,
    summarize,
)


def test_world_panel_design_is_paired_rotated_and_budget_bounded() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["independent_cluster_count"] == 24
    assert design["paired_seed_count"] == 2
    assert design["planned_cells"] == 24 * 2 * 3 == 144
    assert design["worst_case_declared_cost_usd"] == pytest.approx(4.32)
    assert design["campaign_max_cost_usd"] == pytest.approx(5.0)
    assert design["worst_case_declared_cost_usd"] <= design["campaign_max_cost_usd"]
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert all(cell["evaluation_block_kind"] == "controlled" for cell in design["cells"])

    # Every (world, seed) pair sees every model exactly once.
    pairs: dict[tuple[str, int], set[str]] = {}
    for cell in design["cells"]:
        pairs.setdefault((cell["case_id"], cell["inference_seed"]), set()).add(cell["model_id"])
    assert len(pairs) == 48
    assert all(models == set(design["model_ids"]) for models in pairs.values())

    # Model execution order rotates with the world index.
    first_by_world: dict[int, str] = {}
    for cell in design["cells"]:
        if cell["execution_order_in_world"] == 0:
            first_by_world.setdefault(cell["world_index"], cell["model_id"])
    assert Counter(first_by_world.values()) == {model: 8 for model in design["model_ids"]}

    # Cells are distinct run plans, one per world x seed x model.
    assert len({cell["run_plan_id"] for cell in design["cells"]}) == 144
    assert Counter(cell["stratum"] for cell in design["cells"]) == {
        stratum: 24 for stratum in (
            "revenue_without_bankability",
            "delayed_revenue",
            "restrictive_draws",
            "covenant_cliff",
            "liability_transfer",
            "verbal_written_divergence",
        )
    }


def test_world_panel_contract_pins_the_generated_pack() -> None:
    contract = load_contract()
    manifest = load_pack(contract, DEFAULT_PACK_ROOT)

    assert manifest["artifact_sha256"] == contract["expected_pack_sha256"]
    assert manifest["world_count"] == contract["analysis"]["independent_cluster_count"]


def test_world_panel_rejects_budget_overflow_and_drifted_pack(tmp_path) -> None:
    contract = load_contract()
    over_budget = copy.deepcopy(contract)
    over_budget["execution"]["max_cost_usd_per_live_profile"] = 0.04
    path = tmp_path / "over_budget.json"
    path.write_text(json.dumps(over_budget), encoding="utf-8")
    with pytest.raises(ValueError, match="cost ceiling"):
        build_design(load_contract(path))

    drifted = copy.deepcopy(contract)
    drifted["expected_pack_sha256"] = "0" * 64
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(ValueError, match="pack hash"):
        build_design(load_contract(path))


def test_world_panel_module_invokes_cli_design(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread_families.datacenter_development.world_campaign",
            "--run-root",
            str(tmp_path / "campaign"),
            "--stop-after",
            "design",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    design = json.loads(completed.stdout)

    assert design["planned_cells"] == 144
    assert (tmp_path / "campaign" / "design.json").is_file()


def test_world_panel_provider_free_gate_replays_every_world(tmp_path) -> None:
    summary = asyncio.run(
        run_campaign(run_root=tmp_path / "campaign", stop_after="provider_free")
    )

    assert summary["status"] == "passed"
    assert summary["world_count"] == 24
    assert len(summary["strata_replayed"]) == 6
    assert all(row["replay_verified"] for row in summary["worlds"])
    assert all(row["logical_action_count"] == 18 for row in summary["worlds"])


def _row(design_cell: dict, *, status: str = "completed", reason: str = "agreement_stack_executed",
         completed: bool = True, constraints: bool = True, npv: int = 500_000,
         temporal: list | None = None, cost: float = 0.001) -> dict:
    if status != "completed":
        return {
            **design_cell,
            "status": "operational_failure",
            "inclusion_status": "excluded",
            "receipt_sha256": "f" * 64,
            "elapsed_seconds": 1.0,
            "usage": None,
            "route_verified": False,
            "verified_openrouter_call_count": 0,
            "outcome": None,
            "scores": None,
            "failure": {"failure_class": "operational", "failure_condition": "rate_limit"},
        }
    return {
        **design_cell,
        "status": "completed",
        "inclusion_status": "included",
        "receipt_sha256": "a" * 64,
        "elapsed_seconds": 10.0,
        "usage": {
            "provider_calls_started": 6,
            "provider_calls_succeeded": 6,
            "input_tokens": 1000,
            "cached_input_tokens": 0,
            "output_tokens": 200,
            "reported_cost_usd": cost,
            "resolved_models": [],
        },
        "route_verified": True,
        "verified_openrouter_call_count": 6,
        "outcome": {
            "project_completed": completed,
            "termination_reason": reason,
            "binding_contract_integrity": completed,
            "project_constraints_satisfied": constraints and completed,
            "amendment_precedence_valid": True,
            "temporal_violations": temporal or [],
            "developer_equity_npv_cents": npv,
            "lender_npv_cents": 0,
            "customer_npv_cents": 0,
            "total_project_npv_cents": npv,
            "default_reasons": [] if constraints else ["funding_shortfall"],
            "decisions": [],
            "counter_rounds": 0,
        },
        "scores": {},
        "failure": None,
    }


def test_world_panel_summary_separates_admission_no_agreement_and_failures() -> None:
    contract = load_contract()
    design = build_design(contract)
    rows = []
    for cell in design["cells"]:
        outside = cell["outside_option_developer_equity_npv_cents"]
        baseline = cell["scripted_baseline_developer_equity_npv_cents"]
        if cell["model_id"] == "glm53_parasail":
            rows.append(_row(cell, npv=baseline))
        elif cell["model_id"] == "qwen3_235b_google":
            if cell["stratum"] == "covenant_cliff":
                rows.append(_row(cell, constraints=False, npv=baseline))
            else:
                rows.append(_row(cell, reason="land_negotiation_rounds_exhausted", completed=False, npv=outside))
        else:
            if cell["world_index"] == 0 and cell["inference_seed"] == 41211:
                rows.append(_row(cell, status="operational_failure"))
            else:
                rows.append(_row(cell, reason="developer_walk", completed=False, npv=outside))
    summary = summarize(contract, design, rows)
    by_model = {item["model_id"]: item for item in summary["model_summaries"]}

    glm = by_model["glm53_parasail"]
    assert glm["admission_rate"] == 1.0
    assert glm["mean_delta_from_baseline_cents"] == 0.0
    assert glm["rankable"] is True

    mistral = by_model["qwen3_235b_google"]
    assert mistral["excluded_cells"] == 8
    assert mistral["no_agreement_cells"] == 40
    assert mistral["no_agreement_reasons"] == {"land_negotiation_rounds_exhausted": 40}
    assert "constraint_failure:funding_shortfall" in mistral["exclusion_reasons"]
    assert mistral["by_stratum"]["covenant_cliff"]["excluded_cells"] == 8

    gptoss = by_model["gptoss120b_coreweave"]
    assert gptoss["operational_failure_cells"] == 1
    assert gptoss["rankable"] is False
    assert summary["unranked_model_ids"] == ["gptoss120b_coreweave"]
    assert [row["model_id"] for row in summary["leaderboard"]] == ["glm53_parasail", "qwen3_235b_google"]
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["failure_conditions"] == {"rate_limit": 1}
    assert summary["winner_claim_allowed"] is False

    comparisons = {(c["treatment"], c["control"]): c for c in summary["paired_comparisons"]}
    pair = comparisons[("glm53_parasail", "qwen3_235b_google")]
    assert pair["admission_rate_difference"]["worlds"] == 24
    assert pair["admission_rate_difference"]["mean"] == pytest.approx(1.0)
    assert pair["developer_equity_npv_difference_cents"]["worlds"] == 20
    assert pair["developer_equity_npv_difference_cents"]["mean"] > 0

    text = render_leaderboard(summary)
    assert "| 1 | glm53_parasail |" in text
    assert "Unranked" in text and "gptoss120b_coreweave" in text
    assert "No winner claim" in text
