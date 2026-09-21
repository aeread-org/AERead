"""The confirmatory freeze and analysis are code, not session scripts (DC-T-07).

The first confirmatory was frozen and analysed by heredocs that never reached
the repository. This module reproduces the sealed v1 analysis from the sealed
bundle (byte for byte when the run root is present for one v1-only split) and
the v1 freeze's binding pins from the published design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.datacenter_development.confirmatory import (
    ANALYSIS_SCHEMA,
    FREEZE_SCHEMA,
    analyze,
    classify,
    freeze_record,
)
from aeread_families.datacenter_development.stack_runner import DEVELOPER_PROMPT, MONTH_INDEXING_NOTE
from aeread_families.datacenter_development.world_campaign import load_contract, publication_root_for

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_confirmatory_v1.json"
FREEZE = CONTRACT.with_suffix(".freeze.json")
RUN_ROOT = REPOSITORY_ROOT / "runs" / "datacenter_development_v2_world_panel_confirmatory_v1"


def _sealed():
    contract = load_contract(CONTRACT)
    bundle = publication_root_for(contract)
    return contract, json.loads(FREEZE.read_text()), bundle, json.loads((bundle / "reports" / "confirmatory_analysis.json").read_text())


def test_the_analysis_reproduces_the_sealed_v1_numbers_from_the_bundle() -> None:
    contract, freeze, bundle, sealed = _sealed()
    fresh = analyze(bundle, contract, freeze, reading=sealed["reading"])
    assert fresh["schema_version"] == ANALYSIS_SCHEMA == sealed["schema_version"]
    for key in sealed:
        if key == "exclusions":
            continue
        assert fresh[key] == sealed[key], key
    # v1 typed a walk that stated its reason as a parser rejection; without the
    # raw text the bundle cannot split those from non-JSON outputs.
    assert fresh["exclusions"] == {
        "amendment_changes_nothing": 16,
        "completed_but_unfinanced": 21,
        "malformed_datacenter_stack_action": 12,
        "malformed_json": 5,
    }
    assert sealed["exclusions"] == {
        "amendment_changes_nothing": 16,
        "completed_but_unfinanced": 21,
        "walk_with_reason": 12,
        "malformed_json": 5,
    }


@pytest.mark.skipif(not (RUN_ROOT / "live").is_dir(), reason="the v1 run root is gitignored; only its author's machine has it")
def test_with_the_run_root_the_analysis_is_byte_identical() -> None:
    contract, freeze, bundle, sealed = _sealed()
    fresh = analyze(bundle, contract, freeze, reading=sealed["reading"], run_root=RUN_ROOT)
    assert canonical_json_bytes(fresh) == canonical_json_bytes(sealed)


def test_the_freeze_record_reproduces_the_v1_pins_from_the_published_design() -> None:
    contract = load_contract(CONTRACT)
    sealed = json.loads(FREEZE.read_text())
    design = json.loads((publication_root_for(contract) / "reports" / "design.json").read_text())
    text = {key: sealed[key] for key in ("primary_endpoint", "secondary_endpoint", "predeclared_slices", "seed_handling", "stopping_rule", "claims_allowed", "execution_order")}
    fresh = freeze_record(
        CONTRACT,
        design,
        prompt_id=sealed["developer_prompt_id"],
        prompt_text=DEVELOPER_PROMPT + MONTH_INDEXING_NOTE,
        holdout=sealed["holdout"],
        sample_size_rationale=sealed["sample_size_rationale"],
        missingness_policy=sealed["missingness_policy"],
        text=text,
        design_digest_note=sealed["design_digest_note"],
        frozen_at=sealed["frozen_at"],
    )
    assert fresh["schema_version"] == FREEZE_SCHEMA
    assert fresh == sealed


def test_classify_names_walks_failures_and_missingness() -> None:
    base = {"case_id": "w", "stratum": "s", "inference_seed": 1, "status": "completed", "inclusion_status": "included",
            "cell_key": "k", "scripted_baseline_developer_equity_npv_cents": 100}
    admitted = classify({**base, "outcome": {"project_completed": True, "project_constraints_satisfied": True, "temporal_violations": [], "developer_equity_npv_cents": 130, "termination_reason": "agreement_stack_executed"}})
    assert admitted["admitted"] is True and admitted["delta"] == 30 and admitted["exclusion"] is None
    walk = classify({**base, "outcome": {"project_completed": False, "project_constraints_satisfied": False, "temporal_violations": [], "developer_equity_npv_cents": -5, "termination_reason": "developer_walk"}})
    assert walk["admitted"] is False and walk["exclusion"] == "developer_walk"  # a valid walk, interface 3
    unfunded = classify({**base, "outcome": {"project_completed": True, "project_constraints_satisfied": False, "temporal_violations": [], "developer_equity_npv_cents": 90, "termination_reason": "agreement_stack_executed"}})
    assert unfunded["exclusion"] == "completed_but_unfinanced"
    invalid = classify({**base, "outcome": {"project_completed": False, "project_constraints_satisfied": False, "temporal_violations": ["amendment_changes_nothing"], "developer_equity_npv_cents": -5, "termination_reason": "invalid_action"}})
    assert invalid["exclusion"] == "amendment_changes_nothing"
    missing = classify({**base, "status": "operational_failure", "inclusion_status": "excluded", "outcome": None})
    assert missing["missing"] is True and missing["admitted"] is False


def test_two_routes_get_per_route_endpoints_and_a_paired_world_contrast(tmp_path) -> None:
    """Synthetic cells for two routes on four worlds: the contrast is the mean
    per-world difference in admission, second minus first, over worlds where
    both routes have every seed, with a world-clustered interval."""

    from aeread_families.datacenter_development.confirmatory import analyze_two_routes

    def cell(model, world, seed, admitted, missing=False):
        outcome = None if missing else {"project_completed": admitted, "project_constraints_satisfied": admitted, "temporal_violations": [], "developer_equity_npv_cents": 130 if admitted else -5, "termination_reason": "agreement_stack_executed" if admitted else "developer_walk"}
        return {"case_id": world, "stratum": "s", "inference_seed": seed, "model_id": model, "status": "operational_failure" if missing else "completed", "inclusion_status": "excluded" if missing else "included", "cell_key": f"{world}_{model}_{seed}", "scripted_baseline_developer_equity_npv_cents": 100, "outcome": outcome}
    rows = []
    for world in ("w1", "w2", "w3", "w4"):
        for seed in (1, 2):
            rows.append(cell("a", world, seed, admitted=(world in ("w1",))))
            rows.append(cell("b", world, seed, admitted=(world in ("w1", "w2", "w3")), missing=(world == "w4" and seed == 2)))
    (tmp_path / "tables").mkdir(); (tmp_path / "tables" / "cells.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    contract = {"campaign_id": "t", "models": {"a": {}, "b": {}}, "inference_seeds": [1, 2], "analysis": {"bootstrap_draws": 200, "bootstrap_seed": 7}}
    freeze = {"contract_sha256": "x", "primary_endpoint": "p", "secondary_endpoint": "s", "seed_handling": "h", "missingness_policy": "m", "paired_contrast": "c"}
    out = analyze_two_routes(tmp_path, contract, freeze, reading="r")
    assert out["routes"] == ["a", "b"] and out["cells"] == 16 and out["operational_failures"] == 1
    assert out["by_route"]["a"]["primary_admission_rate"]["point"] == 0.25
    assert out["by_route"]["b"]["primary_admission_rate"]["point"] == pytest.approx(0.75)  # 3 of 4 worlds, w4 has one seed
    contrast = out["paired_admission_contrast"]
    assert contrast["second_minus_first"] == ["b", "a"] and contrast["worlds_paired"] == 3  # w4 lacks a seed for b
    assert contrast["point"] == pytest.approx(2 / 3) and contrast["worlds_second_higher"] == 2 and contrast["worlds_tied"] == 1
    assert contrast["ci95"][0] <= contrast["point"] <= contrast["ci95"][1]
    assert out["winner_claim_allowed"] is False
