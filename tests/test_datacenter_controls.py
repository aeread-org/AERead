"""Gate 3 controls for the V2 stack, scored through the real interface.

`walk_away` is the anchor a reference must strictly beat (DC-D-01);
`adopt_every_counter` is the transcription policy the score must be able to
tell from negotiation (DC-D-03, DC-D-04). Both run through the same scheduler
a live subject uses and seal the same receipts.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
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


#: The one column that follows the runner's bytes rather than the cases or the
#: family engine. A run plan pins the ``minimal_chat`` harness by the digest of
#: the kernel's execution module, so every kernel commit moves it (DC-T-20).
#: The committed value is the record of the commit that sealed the bundle.
SOURCE_BOUND_COLUMNS = ("run_plan_sha256",)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _source_independent_rows(table: Path) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(table.read_text(encoding="utf-8")))
    rows = list(reader)
    assert reader.fieldnames is not None
    for row in rows:
        for column in SOURCE_BOUND_COLUMNS:
            assert _SHA256.fullmatch(row.pop(column)), column
    return list(reader.fieldnames), rows


def assert_bundle_regenerates(fresh: Path, committed: Path) -> None:
    """A regenerated bundle equals the committed one in everything the cases
    and the family engine determine; the kernel-bound digests are compared in
    shape only, and the committed bundle must still seal its own bytes."""

    for relative in ("reports/summary.json", "README.md"):
        assert (fresh / relative).read_bytes() == (committed / relative).read_bytes(), relative
    assert _source_independent_rows(fresh / "tables" / "controls.csv") == _source_independent_rows(
        committed / "tables" / "controls.csv"
    )
    fresh_manifest = json.loads((fresh / "publication_manifest.json").read_text())
    sealed = json.loads((committed / "publication_manifest.json").read_text())
    assert set(fresh_manifest["artifacts"]) == set(sealed["artifacts"])
    for relative, digest in sealed["artifacts"].items():
        assert hashlib.sha256((committed / relative).read_bytes()).hexdigest() == digest, relative
        if relative != "tables/controls.csv":
            assert fresh_manifest["artifacts"][relative] == digest, relative
    assert fresh_manifest["source_bindings"] == sealed["source_bindings"]


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
    assert DEVELOPER_POLICIES == ("scripted", "walk_away", "adopt_every_counter")
    with pytest.raises(ValueError, match="developer_policy must be one of"):
        build_stack_setup("v2", case_path=CURATED, developer_policy="random")


def test_the_scored_controls_bundle_regenerates(tmp_path) -> None:
    """Derived only from committed cases and the engine: regenerating must
    reproduce the committed tables, summary and manifest artifact table, apart
    from the run-plan digest, which also follows the runner's bytes."""

    summary = write_bundle(tmp_path / "bundle")
    assert summary["case_count"] == 25 and summary["trajectory_count"] == 75
    assert summary["all_receipts_included"] and summary["all_replays_verified"]
    assert summary["reference_beats_walk_away_in"] == 25
    assert summary["reference_beats_adoption_in"] == 25
    # On the sealed pack the adopter walks at the amendment (DC-D-09), so the
    # only admitted adoption is the curated case's.
    assert summary["adoption_completes_the_stack_in"] == summary["adoption_admitted_in"] == 1
    assert_bundle_regenerates(tmp_path / "bundle", DEFAULT_BUNDLE_ROOT)


def test_a_runner_edit_moves_only_the_run_plan_digest(tmp_path, monkeypatch) -> None:
    """DC-T-20: the comparison must survive a kernel commit and still catch a
    change in anything the cases or the engine determine."""

    from aeread_families.datacenter_development import stack_runner

    real_pin = stack_runner._pin

    def drifted(component_id, kind, source_path, *, version="1.0.0"):
        pin = real_pin(component_id, kind, source_path, version=version)
        if kind != "harness":
            return pin
        return stack_runner.ImplementationPin.from_dict(
            {"component_id": component_id, "kind": kind, "version": version, "sha256": "0" * 64}
        )

    monkeypatch.setattr(stack_runner, "_pin", drifted)
    write_bundle(tmp_path / "bundle")
    fresh = tmp_path / "bundle" / "tables" / "controls.csv"
    assert fresh.read_bytes() != (DEFAULT_BUNDLE_ROOT / "tables" / "controls.csv").read_bytes()
    assert_bundle_regenerates(tmp_path / "bundle", DEFAULT_BUNDLE_ROOT)

    fresh.write_text(fresh.read_text().replace(",-72000,", ",-72001,", 1), encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_bundle_regenerates(tmp_path / "bundle", DEFAULT_BUNDLE_ROOT)
