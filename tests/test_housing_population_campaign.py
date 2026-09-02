from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from aeread.shared_runner.housing import DEEPINFRA_GLM_53_FLASH_ROUTE
from aeread.shared_runner.housing_population_campaign import (
    _live_stage_root,
    audit_world_panel,
    build_condition_setups,
    design_contract_artifact,
    execute_campaign,
    load_contract,
)
from aeread.shared_runner.resolver import canonical_json_bytes


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "housing_population_crossplay_v0.json"
)


def test_contract_resolves_the_complete_frozen_crossplay_matrix() -> None:
    contract = load_contract(CONTRACT_PATH)
    setups = build_condition_setups(
        contract,
        world_seeds=contract["full_trajectory"]["world_seeds"],
        replicates=1,
    )

    assert len(setups) == 6
    for condition in contract["conditions"]:
        setup = setups[condition["condition_id"]]
        block = setup.plan.evaluation_blocks[0]
        assert block.kind == condition["evaluation_kind"]
        assert len(setup.plan.cells[0].profile_by_seat) == 10
        if block.kind == "controlled":
            assert len(block.subject_seats) == 6
            assert len(block.controlled_profiles) == 4
        elif block.kind == "self_play":
            assert len(block.subject_seats) == 10
            assert dict(block.controlled_profiles) == {}
        else:
            assert len(block.subject_seats) == 6
            assert dict(block.controlled_profiles) == {}


def test_design_and_provider_free_qc_are_evidence_backed() -> None:
    contract = load_contract(CONTRACT_PATH)

    design = design_contract_artifact(contract)
    qc = audit_world_panel(contract)

    assert design["status"] == "passed"
    assert design["complete_matrix"] is True
    assert design["scripted_anchor_ranked"] is False
    assert qc["status"] == "passed"
    assert qc["world_count"] == 17
    assert qc["duplicate_world_count"] == 0
    assert qc["beatability_passed"] is True
    assert all(
        row["oracle_total"] == row["oracle_informed_total"]
        and row["oracle_total"] > row["naive_total"]
        for row in qc["worlds"]
    )


def test_glm_route_uses_distinct_cached_input_price() -> None:
    pricing = DEEPINFRA_GLM_53_FLASH_ROUTE.token_pricing()

    assert pricing.input_per_million == 0.075
    assert pricing.cached_input_per_million == 0.015
    assert pricing.output_per_million == 0.25


def test_live_gate_retries_use_whole_matrix_attempt_directories(
    tmp_path: Path,
) -> None:
    assert _live_stage_root(tmp_path, "full_trajectory", 1) == (
        tmp_path / "full_trajectory"
    )
    assert _live_stage_root(tmp_path, "full_trajectory", 2) == (
        tmp_path / "full_trajectory" / "attempt_2"
    )


def test_contract_rejects_route_drift(tmp_path: Path) -> None:
    value = json.loads(CONTRACT_PATH.read_bytes())
    value["models"]["glm_53_flash"]["canonical_model"] = "drifted"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="model route drifted"):
        load_contract(path)


def test_campaign_executes_through_provider_free_gate_without_paid_calls(
    tmp_path: Path,
) -> None:
    result = asyncio.run(
        execute_campaign(
            contract_path=CONTRACT_PATH,
            output_root=tmp_path / "campaign",
            through="provider_free_validation",
        )
    )

    assert result["gate_summaries"]["design_contract"]["status"] == "passed"
    assert result["gate_summaries"]["provider_free_validation"]["status"] == "passed"
    history = json.loads((tmp_path / "campaign" / "gate_history.json").read_bytes())
    assert [record["gate_id"] for record in history["records"]] == [
        "design_contract",
        "provider_free_validation",
    ]
    summary = json.loads(
        (
            tmp_path / "campaign" / "provider_free_validation" / "summary.json"
        ).read_bytes()
    )
    assert summary["provider_cost_usd"] == 0.0
    assert summary["replay_verified"] is True


def test_published_trajectory_examples_are_digest_bound_and_unranked() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "docs"
        / "evidence"
        / "housing_population_crossplay_v0_trajectory_examples_2026-09-02.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["ranking_allowed"] is False
    assert value["raw_provider_responses_included"] is False
    assert value["model_reasoning_included"] is False
    assert {example["example_class"] for example in value["examples"]} == {
        "completed_upper_observed_crossplay",
        "completed_lower_observed_crossplay",
        "shortest_operational_failure",
    }


def test_published_population_qualification_is_digest_bound() -> None:
    path = (
        CONTRACT_PATH.parents[1]
        / "docs"
        / "evidence"
        / "housing_population_crossplay_v0_qualification_2026-09-01.json"
    )
    value = json.loads(path.read_bytes())
    core = {key: item for key, item in value.items() if key != "artifact_sha256"}

    assert (
        value["artifact_sha256"]
        == hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    )
    assert value["winner_claim_allowed"] is False
    assert value["local_evidence"]["committed"] is False
