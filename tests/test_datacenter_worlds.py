from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.stack_environment import (
    DataCenterStackPlugin,
)
from aeread_families.datacenter_development.stack_runner import (
    finalize_stack_execution,
    replay_stack_receipt,
    run_stack_offline,
)
from aeread_families.datacenter_development.stack_worlds import (
    DEFAULT_OUTPUT_ROOT,
    MASTER_SEED,
    STRATA,
    VARIANTS_PER_STRATUM,
    check_pack,
    evaluate_stack,
    generate_pack,
    load_pack_manifest,
)


def test_world_pack_on_disk_is_reproducible_from_the_pinned_seed() -> None:
    result = check_pack(DEFAULT_OUTPUT_ROOT)

    assert result["reproducible"] is True, result["drift"]


def test_world_pack_covers_six_strata_with_four_distinct_variants() -> None:
    manifest = load_pack_manifest()

    assert manifest["master_seed"] == MASTER_SEED
    assert manifest["world_count"] == len(STRATA) * VARIANTS_PER_STRATUM == 24
    by_stratum: dict[str, list[dict]] = {}
    for world in manifest["worlds"]:
        by_stratum.setdefault(world["stratum"], []).append(world)
    assert set(by_stratum) == set(STRATA)
    for stratum, worlds in by_stratum.items():
        assert [world["variant"] for world in worlds] == [1, 2, 3, 4], stratum
        knobs = {json.dumps(world["knobs"], sort_keys=True) for world in worlds}
        assert len(knobs) == 4, stratum
    seeds = [world["world_seed"] for world in manifest["worlds"]]
    assert len(set(seeds)) == 24


def test_every_world_has_feasible_trap_and_walk_away_paths() -> None:
    manifest = load_pack_manifest()

    for world in manifest["worlds"]:
        mechanism = world["mechanism"]
        feasible = mechanism["feasible_path"]
        trap = mechanism["attractive_path"]
        walk = mechanism["walk_away"]
        assert feasible["constraints_satisfied"] is True, world["case_id"]
        assert feasible["financing_succeeded"] is True, world["case_id"]
        assert feasible["developer_equity_npv_cents"] > walk["developer_equity_npv_cents"]
        assert trap["constraints_satisfied"] is False, world["case_id"]
        expected = mechanism["expected_failure"]
        if expected == "loan_never_funds":
            assert trap["loan_conditions_satisfied_month"] is None
        else:
            assert expected in trap["default_reasons"], world["case_id"]


def test_world_case_files_validate_and_match_manifest_hashes() -> None:
    manifest = load_pack_manifest()
    plugin = DataCenterStackPlugin("v2")

    for world in manifest["worlds"]:
        document = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())
        assert document["case_id"] == world["case_id"]
        assert document["content_sha256"] == world["content_sha256"]
        assert case_content_sha256(document) == document["content_sha256"]
        payload = plugin.validate_payload(document["payload"])
        baseline = world["mechanism"]["feasible_path"]
        assert payload["baseline"]["developer_equity_npv_cents"] == (
            baseline["developer_equity_npv_cents"]
        )
        assert payload["outside_option"] == world["mechanism"]["walk_away"]
        # Mechanism annotations never enter the payload the agent can observe.
        assert "mechanism" not in document["payload"]
        assert "explanation" not in document["payload"]


def test_trap_paths_are_accepted_by_every_counterparty_but_fail_admission() -> None:
    pack = generate_pack(MASTER_SEED)
    manifest = pack["manifest"]

    for document, world in zip(pack["cases"], manifest["worlds"]):
        payload = document["payload"]
        recomputed = evaluate_stack(
            payload["project_facts"],
            {key: payload["scripted_developer"][f"{key}_terms"] for key in (
                "land", "power", "epc", "service", "land_amendment", "loan"
            )},
        )
        assert recomputed == world["mechanism"]["feasible_path"]


def test_verbal_written_divergence_counter_message_contradicts_terms() -> None:
    manifest = load_pack_manifest()
    worlds = [w for w in manifest["worlds"] if w["stratum"] == "verbal_written_divergence"]

    for world in worlds:
        document = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())
        loan_policy = document["payload"]["policies"]["loan"]
        scripted = document["payload"]["scripted_developer"]["loan_terms"]
        assert "advance rate" in loan_policy["counter_message"]
        assert loan_policy["counter_terms"]["advance_rate_bps"] < scripted["advance_rate_bps"]


@pytest.mark.parametrize(
    "file_name",
    ("revenue_without_bankability_001.json", "covenant_cliff_003.json"),
)
def test_two_worlds_from_different_strata_replay_exactly(tmp_path, file_name: str) -> None:
    setup, execution = asyncio.run(
        run_stack_offline(
            "v2",
            evidence_root=tmp_path,
            case_path=DEFAULT_OUTPUT_ROOT / file_name,
        )
    )
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path)
    outcome = execution.episode_result.outcome

    assert execution.episode_result.logical_action_count == 18
    assert receipt.inclusion_status == "included"
    assert outcome["project_completed"] is True
    assert outcome["project_constraints_satisfied"] is True
    assert replayed == receipt


def test_world_generator_cli_checks_the_pack(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread_families.datacenter_development.stack_worlds",
            "--check",
            "--output",
            str(DEFAULT_OUTPUT_ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout)["reproducible"] is True
