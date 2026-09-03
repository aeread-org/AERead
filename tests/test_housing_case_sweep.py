from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.housing.case_sweep import (
    build_sweep,
    load_contract,
    write_sweep,
)
from aeread_families.housing.qc import audit_bid_world
from aeread.shared_runner.run.resolver import canonical_json_bytes


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_case_config_sweep_v1.json"
)


@pytest.fixture(scope="module")
def completed_sweep(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    contract = load_contract(CONTRACT_PATH)
    output = tmp_path_factory.mktemp("housing_case_sweep")
    paths = write_sweep(contract=contract, output_dir=output)
    with paths["world_facts"].open(newline="", encoding="utf-8") as handle:
        world_rows = list(csv.DictReader(handle))
    with paths["config_summary"].open(newline="", encoding="utf-8") as handle:
        summaries = list(csv.DictReader(handle))
    selected = json.loads(paths["selected_configs"].read_bytes())
    manifest = json.loads(paths["fact_manifest"].read_bytes())
    sweep_summary = json.loads(paths["sweep_summary"].read_bytes())
    return {
        "contract": contract,
        "paths": paths,
        "world_rows": world_rows,
        "summaries": summaries,
        "selected": selected,
        "manifest": manifest,
        "sweep_summary": sweep_summary,
    }


def test_contract_freezes_paired_development_and_unopened_holdout() -> None:
    contract = load_contract(CONTRACT_PATH)

    assert contract["independent_cluster"] == "world_seed"
    assert len(contract["development"]["candidate_configs"]) == 18
    assert len(contract["development"]["world_seeds"]) == 16
    assert contract["confirmatory_holdout"]["status"] == "sealed_not_executed"
    assert set(contract["development"]["world_seeds"]).isdisjoint(
        contract["confirmatory_holdout"]["world_seeds"]
    )
    assert "harness" not in contract


def test_contract_rejects_development_holdout_overlap(tmp_path: Path) -> None:
    value = json.loads(CONTRACT_PATH.read_bytes())
    value["confirmatory_holdout"]["world_seeds"][0] = value["development"][
        "world_seeds"
    ][0]
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="seeds overlap"):
        load_contract(path)


def test_provider_free_world_facts_are_reproducible_and_bounded() -> None:
    arguments = {
        "tenants": 6,
        "listings": 4,
        "rounds": 2,
        "common_weight": 0.85,
        "world_seed": 1971418798,
    }

    first = audit_bid_world(**arguments)
    second = audit_bid_world(**arguments)

    assert first == second
    assert first["oracle_crosscheck_passed"] is True
    assert first["oracle_total"] == first["brute_force_oracle_total"]
    assert first["oracle_total"] == first["oracle_informed_total"]
    assert first["no_op_total"] == 0.0
    assert all(
        first[field] <= first["oracle_total"]
        for field in (
            "random_total",
            "naive_total",
            "adaptive_total",
        )
    )


def test_sweep_selects_one_eligible_config_per_difficulty_stratum(
    completed_sweep: dict[str, object],
) -> None:
    world_rows = completed_sweep["world_rows"]
    summaries = completed_sweep["summaries"]
    selected = completed_sweep["selected"]

    assert isinstance(world_rows, list) and len(world_rows) == 288
    assert isinstance(summaries, list) and len(summaries) == 18
    assert isinstance(selected, dict)
    assert selected["selected_config_count"] == 3
    assert [row["config_id"] for row in selected["selected_configs"]] == [
        "mild_cw085_r2",
        "moderate_cw085_r2",
        "severe_cw030_r2",
    ]
    assert {row["difficulty_stratum"] for row in selected["selected_configs"]} == {
        "mild_1p2",
        "moderate_1p5",
        "severe_2p0",
    }
    selected_ids = {row["config_id"] for row in selected["selected_configs"]}
    assert all(
        row["admission_status"] == "passed"
        for row in summaries
        if row["config_id"] in selected_ids
    )


def test_sweep_facts_do_not_materialize_confirmatory_holdout(
    completed_sweep: dict[str, object],
) -> None:
    contract = completed_sweep["contract"]
    world_rows = completed_sweep["world_rows"]
    holdout_seeds = {
        str(seed) for seed in contract["confirmatory_holdout"]["world_seeds"]
    }
    holdout_ids = {
        config["config_id"]
        for config in contract["confirmatory_holdout"]["parameter_combinations"]
    }

    assert {row["split"] for row in world_rows} == {"development"}
    assert {row["world_seed"] for row in world_rows}.isdisjoint(holdout_seeds)
    assert {row["config_id"] for row in world_rows}.isdisjoint(holdout_ids)
    assert all(row["case_config_sha256"] for row in world_rows)


def test_fact_manifest_binds_every_reportable_artifact(
    completed_sweep: dict[str, object],
) -> None:
    paths = completed_sweep["paths"]
    manifest = completed_sweep["manifest"]
    sweep_summary = completed_sweep["sweep_summary"]

    core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    assert (
        manifest["manifest_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    for name, record in manifest["artifacts"].items():
        assert hashlib.sha256(paths[name].read_bytes()).hexdigest() == record["sha256"]
    assert manifest["artifacts"]["world_facts"]["row_count"] == 288
    assert manifest["artifacts"]["config_summary"]["row_count"] == 18
    assert manifest["confirmatory_holdout_status"] == "sealed_not_executed"
    assert sweep_summary["provider_calls"] == 0
    assert sweep_summary["provider_cost_usd"] == 0.0
    assert sweep_summary["status"] == "completed"
    assert sweep_summary["qc_status"]["development"]["state"] == "passed"
    assert sweep_summary["qc_status"]["normative"]["state"] == "partial"
    assert sweep_summary["qc_status"]["promotion_eligible"] is False


def test_build_sweep_is_deterministic_for_the_frozen_contract() -> None:
    contract = load_contract(CONTRACT_PATH)
    first_rows, first_summaries, first_selection = build_sweep(contract)
    second_rows, second_summaries, second_selection = build_sweep(contract)

    assert canonical_json_bytes(first_rows) == canonical_json_bytes(second_rows)
    assert canonical_json_bytes(first_summaries) == canonical_json_bytes(
        second_summaries
    )
    assert canonical_json_bytes(first_selection) == canonical_json_bytes(
        second_selection
    )
