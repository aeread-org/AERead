"""The repeated-sourcing campaign: frozen plans, typed cells, pairing, publication.

Offline throughout. The publish test drives one cell through the kernel with
the fixture provider so the bundle it seals carries a real receipt, a real
evidence store and a real trajectory grain.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.procurement_allocation import (
    build_offline_setup,
    finalize_procurement_allocation_execution,
    run_fixture_script,
    solve_full_information_upper_bound,
)
from aeread_families.procurement_allocation import relationship_campaign as campaign
from aeread_families.procurement_allocation.relationship_case_matrix import CASE_PATHS

WORLD = CASE_PATHS[0]


def _plan(tmp_path: Path, *, seeds=(11, 12), case_paths=(WORLD,), route_id="gemini38_flash_aistudio"):
    return campaign.prepare(
        tmp_path / "run", campaign_id="test_campaign", seeds=seeds, route_id=route_id, case_paths=case_paths
    )


def _completed_row(cell: dict, *, regret: float, counters: int = 0, quoted=("a", "b")) -> dict:
    bound = 400.0
    return {
        "slug": cell["slug"],
        "seed": cell["seed"],
        "world_case_id": cell["world_case_id"],
        "case_id": cell["case_id"],
        "case_content_sha256": cell["content_sha256"],
        "status": "completed",
        "decision": "award",
        "termination_reason": "submitted",
        "feasible": True,
        "feasible_award": True,
        "periods": 4,
        "periods_awarded": 4,
        "period_decisions": ["award"] * 4,
        "period_margins": [100.0 - regret / 4] * 4,
        "switches": 0,
        "realized_on_time_rate": 1.0,
        "contribution_margin_usd": bound - regret,
        "upper_bound_usd": bound,
        "myopic_reference_usd": 380.0,
        "loyal_reference_usd": 380.0,
        "shopping_reference_usd": 378.0,
        "regret_to_upper_bound_usd": regret,
        "advantage_over_myopic_usd": bound - regret - 380.0,
        "violations": [],
        "information_cost_usd": 1.0,
        "action_count": 14,
        "action_counts": {"request_quote": 8, "submit_award": 4, "request_sample": 2},
        "counters": counters,
        "inquiries": 0,
        "suppliers_quoted": list(quoted),
        "suppliers_quoted_count": len(quoted),
        "provider_call_count": 14,
        "finish_reasons": {"stop": 14},
        "input_tokens": 1000,
        "cached_input_tokens": 0,
        "output_tokens": 100,
        "cost_usd": 0.01,
        "resolved_models": ["fake"],
        "receipt_sha256": "0" * 64,
        "receipt_status": "ok",
        "inclusion_status": "included",
        "elapsed_seconds": 1.0,
        "period_results": [],
        "action_trace": [{"ordinal": 1, "status": "completed", "failure_code": None, "action": "request_quote", "supplier_id": "a"}],
    }


# --------------------------------------------------------------------------
# episode cases and plans
# --------------------------------------------------------------------------


def test_episode_case_reseeds_delivery_and_keeps_the_economics() -> None:
    world = json.loads(WORLD.read_text(encoding="utf-8"))
    first = campaign.episode_case(world, 11)
    second = campaign.episode_case(world, 12)
    assert first["case_id"] != second["case_id"] != world["case_id"]
    assert first["content_sha256"] != second["content_sha256"]
    assert first["payload"]["interaction"]["periods"]["delivery_seed"] == 11
    assert (
        solve_full_information_upper_bound(first["payload"]).contribution_margin_usd
        == solve_full_information_upper_bound(second["payload"]).contribution_margin_usd
    )
    with pytest.raises(ValueError, match="positive integer"):
        campaign.episode_case(world, 0)


def test_episode_case_reseeds_sample_noise_when_the_world_declares_it() -> None:
    world = json.loads(WORLD.read_text(encoding="utf-8"))
    world["payload"]["interaction"]["sample_noise"] = {"model": "binomial", "seed": 1}
    derived = campaign.episode_case(world, 77)
    assert derived["payload"]["interaction"]["sample_noise"]["seed"] == 77


def test_prepare_freezes_a_plan_that_read_plan_verifies(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    assert len(plan["cells"]) == 2 and plan["route_id"] == "gemini38_flash_aistudio"
    assert set(campaign.FAMILY_SOURCES) <= set(plan["sources"])
    reread = campaign.read_plan(tmp_path / "run")
    assert reread["plan_sha256"] == plan["plan_sha256"]
    for cell in plan["cells"]:
        assert (tmp_path / "run" / cell["path"]).is_file()
    with pytest.raises(ValueError, match="never rewritten"):
        _plan(tmp_path)
    with pytest.raises(ValueError, match="unknown route"):
        campaign.prepare(tmp_path / "other", campaign_id="x", seeds=(1,), route_id="jev")
    with pytest.raises(ValueError, match="distinct"):
        campaign.prepare(tmp_path / "dup", campaign_id="x", seeds=(1, 1))


def test_read_plan_refuses_changed_family_sources_and_tolerates_tool_drift(
    tmp_path: Path, monkeypatch
) -> None:
    _plan(tmp_path)
    original = campaign.source_hashes()
    drifted_tool = {**original, campaign.TOOL_SOURCES[0]: "f" * 64}
    monkeypatch.setattr(campaign, "source_hashes", lambda: drifted_tool)
    campaign.read_plan(tmp_path / "run")  # noted, not refused
    drifted_family = {**original, campaign.FAMILY_SOURCES[0]: "f" * 64}
    monkeypatch.setattr(campaign, "source_hashes", lambda: drifted_family)
    with pytest.raises(ValueError, match="family sources changed"):
        campaign.read_plan(tmp_path / "run")


def test_route_record_round_trips() -> None:
    for route in campaign.ROUTES.values():
        rebuilt = campaign.route_from_record(campaign.route_record(route))
        assert rebuilt == route


# --------------------------------------------------------------------------
# execution: typed cells, no reruns, the stop rule
# --------------------------------------------------------------------------


def test_execute_records_every_cell_once_and_never_reruns(tmp_path: Path) -> None:
    plan = _plan(tmp_path, seeds=(1, 2, 3))
    calls: list[str] = []

    def runner(plan_, cell, root):
        calls.append(cell["case_id"])
        return _completed_row(cell, regret=10.0 + cell["seed"])

    summary = campaign.execute(tmp_path / "run", runner=runner, log=lambda _: None)
    assert summary["completed"] == 3 and summary["halted"] is None
    assert summary["mean_regret_usd"] == pytest.approx(12.0)
    assert summary["worlds_measured"] == 1
    assert summary["mean_regret_usd_95_world_bootstrap"] is None  # one world, no interval
    assert summary["worlds"][0]["within_world_regret_variance"] == pytest.approx(1.0)
    assert (tmp_path / "run" / "results.json").is_file()
    again = campaign.execute(tmp_path / "run", runner=runner, log=lambda _: None)
    assert len(calls) == 3  # recorded cells are read back, never rerun
    assert again["completed"] == 3
    assert "error" not in json.dumps(again["rows"])


def test_execute_halts_after_consecutive_failures_and_types_the_rest(tmp_path: Path) -> None:
    plan = _plan(tmp_path, seeds=(1, 2, 3, 4, 5))
    seen: list[int] = []

    def runner(plan_, cell, root):
        seen.append(cell["seed"])
        return {
            "slug": cell["slug"],
            "seed": cell["seed"],
            "case_id": cell["case_id"],
            "status": "failed",
            "error_type": "ProviderFailure",
            "error": "429 from the provider, user_id: secret",
            "failure_receipt_sha256": None,
            "elapsed_seconds": 0.1,
        }

    summary = campaign.execute(tmp_path / "run", runner=runner, log=lambda _: None)
    assert seen == [1, 2, 3]
    assert summary["failed"] == 3 and summary["not_attempted"] == 2
    assert "consecutive operational failures" in summary["halted"]
    assert all(row["status"] == "not_attempted" for row in summary["rows"][3:])
    assert "user_id" not in json.dumps(summary["rows"])  # error text never leaves the cell file


# --------------------------------------------------------------------------
# summary and pairing
# --------------------------------------------------------------------------


def test_bootstrap_interval_is_deterministic_and_brackets_the_mean() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    first = campaign.bootstrap_interval(values)
    second = campaign.bootstrap_interval(values)
    assert first == second
    assert first[0] < sum(values) / len(values) < first[1]
    assert campaign.bootstrap_interval([1.0]) is None


def test_compare_pairs_by_world_and_seed(tmp_path: Path) -> None:
    left_plan = _plan(tmp_path / "left", seeds=(1, 2))
    right_plan = campaign.prepare(
        tmp_path / "right" / "run", campaign_id="other", seeds=(1, 2), route_id="glm53_flash_parasail", case_paths=(WORLD,)
    )
    campaign.execute(
        tmp_path / "left" / "run",
        runner=lambda p, c, r: _completed_row(c, regret=20.0, counters=1),
        log=lambda _: None,
    )
    campaign.execute(
        tmp_path / "right" / "run",
        runner=lambda p, c, r: _completed_row(c, regret=30.0, quoted=("a", "b", "c")),
        log=lambda _: None,
    )
    report = campaign.compare(tmp_path / "left" / "run", tmp_path / "right" / "run")
    assert report["paired_cells"] == 2 and report["worlds"] == 1
    assert report["mean_regret_delta_usd"] == pytest.approx(-10.0)
    assert report["per_world"][WORLD.stem]["counters"] == pytest.approx(1.0)
    assert report["per_world"][WORLD.stem]["quoted"] == pytest.approx(-1.0)
    assert (tmp_path / "left" / "run" / "comparison_vs_other.json").is_file()

    mismatched = campaign.prepare(
        tmp_path / "third" / "run", campaign_id="third", seeds=(1, 3), case_paths=(WORLD,)
    )
    campaign.execute(
        tmp_path / "third" / "run", runner=lambda p, c, r: _completed_row(c, regret=1.0), log=lambda _: None
    )
    with pytest.raises(ValueError, match="different seeds"):
        campaign.compare(tmp_path / "left" / "run", tmp_path / "third" / "run")


# --------------------------------------------------------------------------
# publication, from a real kernel cell
# --------------------------------------------------------------------------


def _script() -> list[str]:
    actions: list[dict] = []
    versions = {"esp32_s3_n8r8_partner": 0, "ssd1306_oled_096_steady": 0}
    for period in range(1, 5):
        lines = []
        for supplier_id in versions:
            versions[supplier_id] += 1
            actions.append({"action": "request_quote", "supplier_id": supplier_id, "message": "quote"})
            if period == 1:
                actions.append({"action": "request_sample", "supplier_id": supplier_id, "message": "sample"})
            lines.append({"offer_id": f"offer_{supplier_id}_v{versions[supplier_id]}", "quantity": 20})
        actions.append({"action": "submit_award", "award_lines": lines})
    return [json.dumps(action, sort_keys=True) for action in actions]


def test_publish_seals_a_verifiable_bundle_from_a_kernel_cell(tmp_path: Path) -> None:
    plan = _plan(tmp_path, seeds=(5,))
    run_root = tmp_path / "run"
    cell = plan["cells"][0]
    evidence_root = campaign.cell_root(run_root, cell) / "evidence"

    def offline_builder(plan_, cell_, root_):
        return build_offline_setup(case_path=root_ / cell_["path"])

    setup, execution, provider = asyncio.run(
        run_fixture_script(_script(), evidence_root=evidence_root, case_path=run_root / cell["path"])
    )
    assert provider.exhausted
    receipt = finalize_procurement_allocation_execution(setup=setup, execution=execution)
    outcome = json.loads(canonical_json_bytes(execution.episode_result.outcome))
    row = _completed_row(cell, regret=outcome["regret_to_upper_bound_usd"])
    row.update(
        contribution_margin_usd=outcome["contribution_margin_usd"],
        upper_bound_usd=outcome["upper_bound_usd"],
        myopic_reference_usd=outcome["myopic_reference_usd"],
        loyal_reference_usd=outcome["loyal_reference_usd"],
        receipt_sha256=receipt.receipt_sha256,
        period_results=outcome["period_results"],
        action_trace=campaign.public_trace(execution),
    )
    campaign.execute(run_root, runner=lambda p, c, r: row, log=lambda _: None)

    bundle = tmp_path / "bundle"
    manifest = campaign.publish(run_root, publication_root=bundle, setup_builder=offline_builder)
    assert manifest["publication_id"] == "test_campaign"
    assert manifest["claim_status"] == "development_qualification"
    assert manifest["winner_claim_allowed"] is False
    assert manifest["source_bindings"]["source_receipt_sha256s"] == [receipt.receipt_sha256]
    for name in (
        "README.md",
        "reports/plan.json",
        "reports/summary.json",
        "reports/replay.json",
        "tables/cells.jsonl",
        "tables/periods.jsonl",
        "receipts/receipts.jsonl",
        "trajectories/sanitized.jsonl",
    ):
        assert name in manifest["artifacts"], name
    grain = (bundle / "trajectories" / "sanitized.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(grain) == 14
    periods = (bundle / "tables" / "periods.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(periods) == 4
    verdict = campaign.verify_bundle(bundle)
    assert verdict["problems"] == [] and verdict["receipts"] == 1
    with pytest.raises(ValueError, match="already sealed"):
        campaign.publish(run_root, publication_root=bundle, setup_builder=offline_builder)
    text = (bundle / "README.md").read_text(encoding="utf-8")
    assert "No winner" in text and "development_qualification" in text


def test_prepare_on_a_generated_pack_reseeds_the_sample_noise(tmp_path: Path) -> None:
    paths = campaign.pack_paths("relationship_holdout_v1")
    assert len(paths) == 12
    plan = campaign.prepare(tmp_path / "run", campaign_id="holdout_probe", seeds=(3, 4), case_paths=paths[:2])
    assert len(plan["cells"]) == 4
    for cell in plan["cells"]:
        case = json.loads((tmp_path / "run" / cell["path"]).read_text(encoding="utf-8"))
        assert case["payload"]["interaction"]["sample_noise"]["seed"] == cell["seed"]
        assert case["payload"]["interaction"]["periods"]["delivery_seed"] == cell["seed"]
    assert campaign.pack_paths("relationship_v1") == tuple(CASE_PATHS)
