"""The second confirmatory: interface 3 on a fresh held-out pack, frozen.

`worlds_v3_holdout` comes from master seed 20280920 and shares nothing with
the three packs a live model has seen. The contract keeps the first
confirmatory's design (24 worlds x 3 seeds, one route, $15) so the two
admission rates are read on the same footing; the freeze pins the run plans
and predeclares a harness check ahead of the endpoints.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development.confirmatory import FREEZE_SCHEMA
from aeread_families.datacenter_development.stack_runner import AMENDMENT_DECLINE_NOTE, DEVELOPER_PROMPT, MONTH_INDEXING_NOTE
from aeread_families.datacenter_development.stack_worlds import DEFAULT_OUTPUT_ROOT, STRATA, check_pack, load_pack_manifest
from aeread_families.datacenter_development.world_campaign import (
    CONTRACT_SCHEMA_VERSIONS,
    build_design,
    load_contract,
    pack_root_for,
    publication_root_for,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASES = REPOSITORY_ROOT / "cases" / "datacenter_development_v1"
HOLDOUT = CASES / "worlds_v3_holdout"
HOLDOUT_SEED = 20280920
HOLDOUT_PACK_ID = "datacenter_development_v2_worlds_v3_holdout_v1"
CONTRACT = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_interface3_confirmatory_v1.json"
FREEZE = CONTRACT.with_suffix(".freeze.json")


def _knobs(manifest):
    return {json.dumps(w["knobs"], sort_keys=True) for w in manifest["worlds"]}


def test_the_second_holdout_is_reproducible_and_shares_nothing_with_any_seen_pack() -> None:
    result = check_pack(HOLDOUT, master_seed=HOLDOUT_SEED, split="worlds_v3_holdout", pack_id=HOLDOUT_PACK_ID, developer_interface=3)
    assert result["reproducible"] is True and result["drift"] == []
    hold = load_pack_manifest(HOLDOUT)
    assert hold["developer_interface"] == 3 and hold["world_count"] == 24
    assert {w["stratum"] for w in hold["worlds"]} == set(STRATA)
    for seen in (DEFAULT_OUTPUT_ROOT, CASES / "worlds_v3", CASES / "worlds_v2_holdout"):
        other = load_pack_manifest(seen)
        assert _knobs(hold).isdisjoint(_knobs(other)), seen.name
        assert {w["world_seed"] for w in hold["worlds"]}.isdisjoint({w["world_seed"] for w in other["worlds"]}), seen.name
        assert {w["content_sha256"] for w in hold["worlds"]}.isdisjoint({w["content_sha256"] for w in other["worlds"]}), seen.name


def test_the_second_confirmatory_contract_keeps_the_first_design_on_the_new_pack() -> None:
    contract = load_contract(CONTRACT)
    first = load_contract(REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_confirmatory_v1.json")
    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSIONS[1]
    assert contract["campaign_id"] == "datacenter_development_v2_world_panel_interface3_confirmatory_v1"
    assert contract["pack_id"] == HOLDOUT_PACK_ID and contract["pack_split"] == "worlds_v3_holdout"
    assert contract["expected_pack_sha256"] == load_pack_manifest(HOLDOUT)["artifact_sha256"]
    assert pack_root_for(contract) == HOLDOUT
    assert contract["inference_seeds"] == first["inference_seeds"] == [51211, 51212, 51213]
    assert contract["execution"] == first["execution"]
    assert list(contract["models"]) == list(first["models"]) == ["gemini38_flash_aistudio"]
    route, first_route = contract["models"]["gemini38_flash_aistudio"], first["models"]["gemini38_flash_aistudio"]
    assert {k: v for k, v in route.items() if k not in ("profile_id", "pricing")} == {k: v for k, v in first_route.items() if k not in ("profile_id", "pricing")}
    design = build_design(contract, pack_root=HOLDOUT)
    assert design["planned_cells"] == 72 and design["independent_cluster_count"] == 24
    assert design["worst_case_declared_cost_usd"] == 14.4  # exact: integer cents


def test_the_freeze_pins_the_run_plans_and_predeclares_the_harness_check() -> None:
    contract = load_contract(CONTRACT)
    freeze = json.loads(FREEZE.read_text())
    assert freeze["schema_version"] == FREEZE_SCHEMA
    assert freeze["campaign_id"] == contract["campaign_id"]
    assert freeze["contract_sha256"] == hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    assert freeze["pack_sha256"] == contract["expected_pack_sha256"]
    assert freeze["developer_prompt_id"] == "datacenter_v2_developer_prompt_v3"
    assert freeze["developer_prompt_sha256"] == hashlib.sha256((DEVELOPER_PROMPT + MONTH_INDEXING_NOTE + AMENDMENT_DECLINE_NOTE).encode()).hexdigest()
    assert freeze["planned_cells"] == 72 and freeze["paired_seed_count"] == 3 and freeze["independent_cluster_count"] == 24
    assert len(freeze["frozen_run_plan_sha256s"]) == 72 == len(set(freeze["frozen_run_plan_sha256s"]))
    assert "must be 0 of 72" in freeze["harness_check"]
    assert freeze["claims_allowed"]["winner"] is False and freeze["claims_allowed"]["causal_condition_effect"] is False
    # Until the run is published the freeze is held to the design the current
    # source resolves; once published, to the design as run (DC-T-06).
    published = publication_root_for(contract) / "reports" / "design.json"
    if published.is_file():
        design = json.loads(published.read_text())
        assert freeze["design_artifact_sha256"] == design["artifact_sha256"]
    else:
        design = build_design(contract, pack_root=HOLDOUT)
    assert freeze["frozen_run_plan_sha256s"] == [cell["run_plan_sha256"] for cell in design["cells"]]
    assert freeze["campaign_driver_sha256"] == design["campaign_driver_sha256"]
