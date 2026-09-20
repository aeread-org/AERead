"""The interface-3 pilot pack, its scored controls, and the pilot contract.

`worlds_v3` is `worlds_v2` (same master seed, same 24 worlds, same knobs and
seeds) with every case opting into developer interface 3, so the pilot on it
is a within-world comparison against the interface-2 pilot with only the
interface changed. The controls bundle on it shows what the decline changes
for the adopter: it now completes every stack and the lender funds none.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development.scored_controls import (
    BUNDLES,
    bundle_root_for,
    write_bundle,
)
from aeread_families.datacenter_development.stack_worlds import (
    DEFAULT_OUTPUT_ROOT,
    MASTER_SEED,
    STRATA,
    check_pack,
    load_pack_manifest,
)
from aeread_families.datacenter_development.world_campaign import (
    CONTRACT_SCHEMA_VERSIONS,
    build_design,
    load_contract,
    pack_root_for,
    run_campaign,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORLDS_V3 = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "worlds_v3"
PACK_ID = "datacenter_development_v2_worlds_v3_interface3_v1"
BUNDLE_ID = "datacenter_v2_interface3_scored_controls_v1"
PILOT = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_interface3_pilot_v1.json"


def test_the_interface_three_pack_is_the_development_pack_at_interface_three() -> None:
    result = check_pack(WORLDS_V3, master_seed=MASTER_SEED, split="worlds_v3", pack_id=PACK_ID, developer_interface=3)
    assert result["reproducible"] is True and result["drift"] == []
    three = load_pack_manifest(WORLDS_V3)
    two = load_pack_manifest(DEFAULT_OUTPUT_ROOT)
    assert three["developer_interface"] == 3 and "developer_interface" not in two
    assert three["world_count"] == 24 and {w["stratum"] for w in three["worlds"]} == set(STRATA)
    assert [w["knobs"] for w in three["worlds"]] == [w["knobs"] for w in two["worlds"]]
    assert [w["world_seed"] for w in three["worlds"]] == [w["world_seed"] for w in two["worlds"]]
    assert {w["content_sha256"] for w in three["worlds"]}.isdisjoint({w["content_sha256"] for w in two["worlds"]})
    for entry in three["worlds"]:
        case = json.loads((WORLDS_V3 / entry["file"]).read_text())
        assert case["payload"]["construct_controls"]["developer_interface"] == 3
        assert case["case_id"] == f"datacenter_development_v1.worlds_v3.{entry['file'].removesuffix('.json')}"


def test_the_interface_three_controls_bundle_regenerates_and_the_adopter_is_never_funded(tmp_path) -> None:
    """With a decline available the adopter completes every stack; the lender
    funds none of them. That, and not a walk at the amendment, is the
    separation between transcription and negotiation (DC-D-09)."""

    assert BUNDLES[BUNDLE_ID]["worlds"] == WORLDS_V3
    committed = bundle_root_for(BUNDLE_ID)
    summary = write_bundle(tmp_path / "bundle", publication_id=BUNDLE_ID)
    assert summary["case_count"] == 25 and summary["trajectory_count"] == 75
    assert summary["all_receipts_included"] and summary["all_replays_verified"]
    assert summary["reference_beats_walk_away_in"] == 25
    assert summary["reference_beats_adoption_in"] == 25
    assert summary["adoption_completes_the_stack_in"] == 25
    assert summary["adoption_admitted_in"] == 1  # the curated case only
    assert summary["world_pack"]["adoption_terminations"] == ["agreement_stack_executed"]
    for relative in ("tables/controls.csv", "reports/summary.json", "README.md"):
        assert (tmp_path / "bundle" / relative).read_bytes() == (committed / relative).read_bytes(), relative
    fresh = json.loads((tmp_path / "bundle" / "publication_manifest.json").read_text())
    sealed = json.loads((committed / "publication_manifest.json").read_text())
    assert fresh["artifacts"] == sealed["artifacts"]
    assert fresh["source_bindings"] == sealed["source_bindings"]
    assert sealed["source_bindings"]["world_pack_sha256"] == load_pack_manifest(WORLDS_V3)["artifact_sha256"]


def test_the_interface_three_pilot_contract_pins_the_pack_and_sums_in_cents(tmp_path) -> None:
    contract = load_contract(PILOT)
    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSIONS[1]
    assert contract["campaign_id"] == "datacenter_development_v2_world_panel_interface3_pilot_v1"
    assert contract["pack_id"] == PACK_ID and contract["pack_split"] == "worlds_v3"
    assert contract["expected_pack_sha256"] == load_pack_manifest(WORLDS_V3)["artifact_sha256"]
    assert pack_root_for(contract) == WORLDS_V3
    assert contract["inference_seeds"] == [41211, 41212]
    assert list(contract["models"]) == ["gemini38_flash_aistudio"]
    design = build_design(contract, pack_root=WORLDS_V3)
    assert design["planned_cells"] == 48 and design["independent_cluster_count"] == 24
    assert design["worst_case_declared_cost_usd"] == 9.6  # exact: integer cents
    assert {cell["case_sha256"] for cell in design["cells"]} == {w["content_sha256"] for w in load_pack_manifest(WORLDS_V3)["worlds"]}


def test_the_interface_three_pilot_provider_free_gate_replays_every_world(tmp_path) -> None:
    summary = asyncio.run(
        run_campaign(contract_path=PILOT, run_root=tmp_path / "campaign", stop_after="provider_free")
    )
    assert summary["status"] == "passed"
    assert summary["world_count"] == 24
    assert all(row["replay_verified"] for row in summary["worlds"])
    assert all(row["logical_action_count"] == 18 for row in summary["worlds"])
