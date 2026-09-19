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
    """Gemini only: 24 worlds x 2 seeds x 1 route. The rotation over one
    route is the identity, and the paired model comparisons are empty."""

    contract = load_contract()
    design = build_design(contract)

    assert design["independent_cluster_count"] == 24
    assert design["paired_seed_count"] == 2
    assert design["model_ids"] == ["gemini38_flash_aistudio"]
    assert design["planned_cells"] == 24 * 2 * 1 == 48
    assert design["worst_case_declared_cost_usd"] == pytest.approx(9.6)
    assert design["campaign_max_cost_usd"] == pytest.approx(10.0)
    assert design["worst_case_declared_cost_usd"] <= design["campaign_max_cost_usd"]
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert all(cell["evaluation_block_kind"] == "controlled" for cell in design["cells"])

    pairs: dict[tuple[str, int], set[str]] = {}
    for cell in design["cells"]:
        pairs.setdefault((cell["case_id"], cell["inference_seed"]), set()).add(cell["model_id"])
    assert len(pairs) == 48
    assert all(models == {"gemini38_flash_aistudio"} for models in pairs.values())
    assert all(cell["execution_order_in_world"] == 0 for cell in design["cells"])

    assert len({cell["run_plan_id"] for cell in design["cells"]}) == 48
    assert Counter(cell["stratum"] for cell in design["cells"]) == {
        stratum: 8 for stratum in (
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
    over_budget["models"]["gemini38_flash_aistudio"]["max_cost_usd_per_live_profile"] = 0.30
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

    assert design["planned_cells"] == 48
    assert (tmp_path / "campaign" / "design.json").is_file()


def test_world_panel_provider_free_gate_replays_every_world(tmp_path) -> None:
    summary = asyncio.run(
        run_campaign(run_root=tmp_path / "campaign", stop_after="provider_free")
    )

    assert summary["status"] == "passed"
    assert summary["world_count"] == 24
    assert len(summary["strata_replayed"]) == 6
    assert all(row["replay_verified"] for row in summary["worlds"])
    # Six agreements x (offer, response, commit); main has no sequencing action.
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
    """One route: admitted, no-agreement and operational cells are counted
    apart, nothing is ranked against anything, and no winner is claimed."""

    contract = load_contract()
    design = build_design(contract)
    rows = []
    for cell in design["cells"]:
        outside = cell["outside_option_developer_equity_npv_cents"]
        baseline = cell["scripted_baseline_developer_equity_npv_cents"]
        if cell["world_index"] == 0 and cell["inference_seed"] == 41211:
            rows.append(_row(cell, status="operational_failure"))
        elif cell["stratum"] == "covenant_cliff":
            rows.append(_row(cell, constraints=False, npv=baseline))
        elif cell["world_index"] % 2:
            rows.append(_row(cell, reason="developer_walk", completed=False, npv=outside))
        else:
            rows.append(_row(cell, npv=baseline))
    summary = summarize(contract, design, rows)
    by_model = {item["model_id"]: item for item in summary["model_summaries"]}

    gemini = by_model["gemini38_flash_aistudio"]
    assert gemini["operational_failure_cells"] == 1
    assert gemini["excluded_cells"] == 8
    assert gemini["by_stratum"]["covenant_cliff"]["excluded_cells"] == 8
    # 12 odd-indexed worlds x 2 seeds, less the 2 odd covenant-cliff worlds
    # that took the excluded branch first.
    assert gemini["no_agreement_reasons"] == {"developer_walk": 20}
    assert gemini["rankable"] is False
    assert summary["paired_comparisons"] == []
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["failure_conditions"] == {"rate_limit": 1}
    assert summary["winner_claim_allowed"] is False

    text = render_leaderboard(summary)
    assert "gemini38_flash_aistudio" in text
    assert "No winner claim" in text

def test_a_retry_may_reuse_a_cell_directory_but_not_overwrite_a_live_one(tmp_path) -> None:
    """Archived attempts must not look like a half-finished cell.

    The guard exists so a run that died mid-cell is never silently overwritten.
    A declared re-execution leaves archived results and evidence behind, and
    those must not trip it.
    """
    import json as _json

    from aeread_families.datacenter_development.world_campaign import (
        _sealed,
        archive_failed_attempt,
    )

    cell = tmp_path / "cell"
    (cell / "evidence").mkdir(parents=True)
    failed = _sealed({"status": "operational_failure", "failure": {"failure_condition": "rate_limit"}})
    (cell / "result.json").write_text(_json.dumps(failed, indent=2, sort_keys=True) + "\n")

    ordinal = archive_failed_attempt(cell)
    assert ordinal == 1
    assert (cell / "result.attempt1.json").is_file()
    assert (cell / "evidence.attempt1").is_dir()
    # The live slots are clear, so a re-execution may proceed.
    assert not (cell / "result.json").exists()
    assert not (cell / "evidence").exists()

    # A completed cell is never archived.
    done = _sealed({"status": "completed", "failure": None})
    (cell / "result.json").write_text(_json.dumps(done, indent=2, sort_keys=True) + "\n")
    assert archive_failed_attempt(cell) == 0
    assert (cell / "result.json").is_file()


def test_every_completed_episode_is_scored() -> None:
    """The mean must not be an average over a route's self-selected successes.

    Dropping excluded cells made the headline incomparable between routes with
    different failure profiles: a route that signed something unbuildable in
    most cells was averaged over the few it finished well, and it led the table
    on a figure computed from 7 of its 48 cells.
    """
    from aeread_families.datacenter_development.world_campaign import (
        _economic_value,
        build_design,
        load_contract,
        summarize,
    )

    contract = load_contract()
    design = build_design(contract)
    rows = []
    for index, cell in enumerate(design["cells"]):
        if cell["model_id"] == "gemini38_flash_aistudio":
            rows.append(
                _row(cell, npv=cell["scripted_baseline_developer_equity_npv_cents"])
                if index == 0
                else _row(cell, constraints=False, npv=10**12)
            )
        else:
            rows.append(
                _row(
                    cell,
                    reason="developer_walk",
                    completed=False,
                    npv=cell["outside_option_developer_equity_npv_cents"],
                )
            )

    # A failed stack scores the walk-away it declined, not its fictional NPV.
    failed = next(
        r
        for r in rows
        if r["model_id"] == "gemini38_flash_aistudio"
        and not r["outcome"]["project_constraints_satisfied"]
    )
    assert _economic_value(failed) == float(
        failed["outside_option_developer_equity_npv_cents"]
    )

    summary = summarize(contract, design, rows)
    for item in summary["model_summaries"]:
        assert item["scored_cells"] == item["completed_cells"], item["model_id"]

    by_model = {item["model_id"]: item for item in summary["model_summaries"]}
    reckless = by_model["gemini38_flash_aistudio"]["mean_developer_equity_npv_cents"]
    assert reckless is not None and reckless < 10**11


def test_publish_refuses_a_run_whose_summary_and_design_disagree(tmp_path) -> None:
    """A published bundle must be faithful to the run it claims to publish.

    The summary records the design it was computed against. Where that is not
    the design sitting beside it, the two came from different versions of the
    campaign driver, and the bundle can be faithful to the run or internally
    consistent but never both. The committed world-panel bundle had silently
    drifted to the latter, recording a driver hash two revisions old, and
    nothing noticed because publish() rewrote it every time.
    """
    from aeread_families.datacenter_development.world_campaign import publish

    root = tmp_path / "run"
    (root / "live").mkdir(parents=True)
    (root / "design.json").write_text(
        json.dumps(
            {
                "artifact_sha256": "a" * 64,
                "campaign_driver_sha256": "b" * 64,
                "pack_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    (root / "live" / "summary.json").write_text(
        json.dumps({"artifact_sha256": "d" * 64, "design_sha256": "e" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="internally inconsistent|digest mismatch"):
        publish(run_root=root, publication_root=tmp_path / "publication")
