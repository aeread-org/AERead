"""Gate 3 controls for the V2 stack, scored through the real interface.

`walk_away` is the anchor a reference must strictly beat (DC-D-01);
`adopt_every_counter` is the transcription policy the score must be able to
tell from negotiation (DC-D-03, DC-D-04). Both run through the same scheduler
a live subject uses and seal the same receipts.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development.scored_controls import (
    DEFAULT_BUNDLE_ROOT,
    POLICIES,
    write_bundle,
)
from aeread_families.datacenter_development.stack_runner import (
    DEVELOPER_POLICIES,
    build_stack_setup,
    finalize_stack_execution,
    replay_stack_receipt,
    run_stack_offline,
)
from aeread_families.datacenter_development.stack_worlds import DEFAULT_OUTPUT_ROOT as WORLDS_ROOT

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CURATED = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v2" / "full_stack_amendment_002.json"
WORLD = WORLDS_ROOT / "covenant_cliff_001.json"


def _run(tmp_path: Path, case: Path, policy: str):
    root = tmp_path / policy
    setup, execution = asyncio.run(
        run_stack_offline("v2", evidence_root=root, case_path=case, developer_policy=policy)
    )
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    assert receipt.status == "ok" and receipt.inclusion_status == "included"
    assert replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=root) == receipt
    return setup, execution.episode_result.outcome, execution.episode_result.logical_action_count


def test_the_three_policies_bracket_the_repaired_case(tmp_path) -> None:
    """Reference −72,000 > walk −100,000 > adoption −155,000: the case can tell
    a negotiator from a quitter from a transcriber, and each is sealed."""

    scripted, walk, adopt = (_run(tmp_path, CURATED, policy) for policy in POLICIES)
    assert scripted[1]["termination_reason"] == "agreement_stack_executed"
    assert scripted[1]["developer_equity_npv_cents"] == -72_000 and scripted[2] == 18
    assert walk[1]["termination_reason"] == "developer_walk"
    assert walk[1]["developer_equity_npv_cents"] == -100_000 and walk[2] == 1
    assert adopt[1]["termination_reason"] == "agreement_stack_executed"
    assert adopt[1]["developer_equity_npv_cents"] == -155_000 and adopt[2] == 30
    assert adopt[1]["project_completed"] is True
    profiles = {setup.plan.cells[0].profile_by_seat["developer"] for setup, _, _ in (scripted, walk, adopt)}
    assert profiles == {
        "datacenter_v2_scripted_developer_v1",
        "datacenter_v2_walk_away_developer_v1",
        "datacenter_v2_adopt_every_counter_developer_v1",
    }


def test_adoption_strands_on_a_world_and_the_reference_does_not(tmp_path) -> None:
    """On the pack the landowner's amendment counter is the executed land
    agreement, so a blind adopter has no amendment to adopt: it declines,
    walks, and scores the outside option; the reference completes."""

    scripted, walk, adopt = (_run(tmp_path, WORLD, policy) for policy in POLICIES)
    outside = json.loads(WORLD.read_text())["payload"]["outside_option"]["developer_equity_npv_cents"]
    assert scripted[1]["project_completed"] is True
    assert scripted[1]["developer_equity_npv_cents"] > outside
    assert walk[1]["termination_reason"] == "developer_walk"
    assert walk[1]["developer_equity_npv_cents"] == outside
    assert adopt[1]["termination_reason"] == "developer_walk"
    assert adopt[1]["project_completed"] is False
    assert adopt[1]["developer_equity_npv_cents"] == outside
    assert not adopt[1]["temporal_violations"]  # a decline, not an invalid action


def test_an_unknown_developer_policy_is_refused() -> None:
    assert DEVELOPER_POLICIES == ("scripted", "walk_away", "adopt_every_counter", "free_rider", "fair_share")
    assert POLICIES == ("scripted", "walk_away", "adopt_every_counter")  # the V2 bundles' three
    with pytest.raises(ValueError, match="developer_policy must be one of"):
        build_stack_setup("v2", case_path=CURATED, developer_policy="random")


def test_the_scored_controls_bundle_regenerates_byte_for_byte(tmp_path) -> None:
    """Derived only from committed cases and the engine: regenerating must
    reproduce the committed tables, summary and manifest artifact table."""

    summary = write_bundle(tmp_path / "bundle")
    assert summary["case_count"] == 25 and summary["trajectory_count"] == 75
    assert summary["all_receipts_included"] and summary["all_replays_verified"]
    assert summary["reference_beats_walk_away_in"] == 25
    assert summary["reference_beats_adoption_in"] == 25
    # On the sealed pack the adopter walks at the amendment (DC-D-09), so the
    # only admitted adoption is the curated case's.
    assert summary["adoption_completes_the_stack_in"] == summary["adoption_admitted_in"] == 1
    for relative in ("tables/controls.csv", "reports/summary.json", "README.md"):
        assert (tmp_path / "bundle" / relative).read_bytes() == (DEFAULT_BUNDLE_ROOT / relative).read_bytes(), relative
    fresh = json.loads((tmp_path / "bundle" / "publication_manifest.json").read_text())
    committed = json.loads((DEFAULT_BUNDLE_ROOT / "publication_manifest.json").read_text())
    assert fresh["artifacts"] == committed["artifacts"]
    assert fresh["source_bindings"] == committed["source_bindings"]
