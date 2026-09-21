"""The interface-4 packs, controls and the two-route comparison contracts.

`worlds_v4` is the development pack at interface 4 and `worlds_v4_holdout` a
fresh pack from master seed 20300920 that shares nothing with any pack a live
model has seen. The GLM 5.3 pilot runs on the first (Kimi K3 was tried and
set aside on cost, DC-O-06); the two-route confirmatory (Gemini 3.8 Flash
and GLM 5.3, paired by world and seed) is
declared on the second under schema 0.3 with the consecutive-failure stop
rule (DC-T-08) and is frozen only after the pilot.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development.scored_controls import BUNDLES, bundle_root_for, write_bundle
from aeread_families.datacenter_development.stack_worlds import DEFAULT_OUTPUT_ROOT, MASTER_SEED, STRATA, check_pack, load_pack_manifest
from aeread_families.datacenter_development.world_campaign import (
    CONTRACT_SCHEMA_VERSIONS,
    build_design,
    load_contract,
    pack_root_for,
    run_campaign,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASES = REPOSITORY_ROOT / "cases" / "datacenter_development_v1"
WORLDS_V4 = CASES / "worlds_v4"
HOLDOUT_V4 = CASES / "worlds_v4_holdout"
BUNDLE_ID = "datacenter_v2_interface4_scored_controls_v1"
PILOT = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_interface4_glm_pilot_v1.json"
TWO_ROUTE = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_interface4_two_route_confirmatory_v1.json"


def _knobs(manifest):
    return {json.dumps(w["knobs"], sort_keys=True) for w in manifest["worlds"]}


def test_the_interface_four_packs_are_reproducible_and_the_holdout_is_unseen() -> None:
    dev = check_pack(WORLDS_V4, master_seed=MASTER_SEED, split="worlds_v4", pack_id="datacenter_development_v2_worlds_v4_interface4_v1", developer_interface=4)
    hold = check_pack(HOLDOUT_V4, master_seed=20300920, split="worlds_v4_holdout", pack_id="datacenter_development_v2_worlds_v4_holdout_v1", developer_interface=4)
    assert dev["reproducible"] and hold["reproducible"]
    v4, h4 = load_pack_manifest(WORLDS_V4), load_pack_manifest(HOLDOUT_V4)
    assert v4["developer_interface"] == h4["developer_interface"] == 4
    assert _knobs(v4) == _knobs(load_pack_manifest(DEFAULT_OUTPUT_ROOT))  # the development worlds, restated
    for seen in (DEFAULT_OUTPUT_ROOT, CASES / "worlds_v2_holdout", CASES / "worlds_v3_holdout", WORLDS_V4):
        other = load_pack_manifest(seen)
        assert _knobs(h4).isdisjoint(_knobs(other)), seen.name
        assert {w["world_seed"] for w in h4["worlds"]}.isdisjoint({w["world_seed"] for w in other["worlds"]}), seen.name
    assert {w["stratum"] for w in h4["worlds"]} == set(STRATA)
    for entry in v4["worlds"] + h4["worlds"]:
        root = WORLDS_V4 if entry in v4["worlds"] else HOLDOUT_V4
        assert json.loads((root / entry["file"]).read_text())["payload"]["construct_controls"]["developer_interface"] == 4


def test_the_interface_four_controls_bundle_regenerates(tmp_path) -> None:
    assert BUNDLES[BUNDLE_ID]["worlds"] == WORLDS_V4
    summary = write_bundle(tmp_path / "bundle", publication_id=BUNDLE_ID)
    assert summary["case_count"] == 25 and summary["trajectory_count"] == 75
    assert summary["reference_beats_walk_away_in"] == summary["reference_beats_adoption_in"] == 25
    assert summary["adoption_completes_the_stack_in"] == 25 and summary["adoption_admitted_in"] == 1
    committed = bundle_root_for(BUNDLE_ID)
    for relative in ("tables/controls.csv", "reports/summary.json", "README.md"):
        assert (tmp_path / "bundle" / relative).read_bytes() == (committed / relative).read_bytes(), relative
    sealed = json.loads((committed / "publication_manifest.json").read_text())
    assert sealed["source_bindings"]["world_pack_sha256"] == load_pack_manifest(WORLDS_V4)["artifact_sha256"]


def test_the_glm_pilot_contract_pins_the_pack_and_carries_the_stop_rule() -> None:
    contract = load_contract(PILOT)
    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSIONS[2]
    assert contract["pack_split"] == "worlds_v4" and contract["expected_pack_sha256"] == load_pack_manifest(WORLDS_V4)["artifact_sha256"]
    assert pack_root_for(contract) == WORLDS_V4
    assert list(contract["models"]) == ["glm53_phala"]
    route = contract["models"]["glm53_phala"]
    assert route["canonical_model"] == "z-ai/glm-5.3-20260816" and route["provider"] == "Phala"
    assert contract["execution"]["max_consecutive_operational_failures"] == 6
    design = build_design(contract, pack_root=WORLDS_V4)
    assert design["planned_cells"] == 48 and design["worst_case_declared_cost_usd"] == 9.6


def test_the_two_route_contract_pairs_both_routes_on_the_fresh_holdout() -> None:
    contract = load_contract(TWO_ROUTE)
    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSIONS[2]
    assert contract["pack_split"] == "worlds_v4_holdout" and contract["expected_pack_sha256"] == load_pack_manifest(HOLDOUT_V4)["artifact_sha256"]
    assert sorted(contract["models"]) == ["gemini38_flash_aistudio", "glm53_phala"]
    assert contract["inference_seeds"] == [51211, 51212, 51213]
    assert contract["execution"]["max_consecutive_operational_failures"] == 6 and contract["execution"]["concurrency"] == 2
    assert contract["analysis"]["paired_by"] == ["case_id", "inference_seed"]
    assert contract["analysis"]["winner_claim_allowed"] is False and contract["analysis"]["inferential_model_ranking_allowed"] is False
    design = build_design(contract, pack_root=HOLDOUT_V4)
    assert design["planned_cells"] == 144 and design["worst_case_declared_cost_usd"] == 28.8
    by_model = {}
    for cell in design["cells"]:
        by_model.setdefault(cell["model_id"], set()).add((cell["case_id"], cell["inference_seed"]))
    assert by_model["gemini38_flash_aistudio"] == by_model["glm53_phala"] and len(by_model["glm53_phala"]) == 72


def test_the_glm_pilot_provider_free_gate_replays_every_world(tmp_path) -> None:
    summary = asyncio.run(run_campaign(contract_path=PILOT, run_root=tmp_path / "campaign", stop_after="provider_free"))
    assert summary["status"] == "passed" and summary["world_count"] == 24
    assert all(row["replay_verified"] for row in summary["worlds"])
