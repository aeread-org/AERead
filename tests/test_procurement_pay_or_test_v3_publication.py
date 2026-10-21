"""Pay or test version 3's kernel bundles (``pay_or_test_v3_publication``) and their replay setup.

The bundles are what ``aeread verify-replay`` reads (qc.md 8.2, Gates 2, 3 and 5). CI has no run roots, so it checks
what a bundle alone can show: every file is sealed in its manifest and carries no prohibited text; each bundle's cells,
receipt projections and trajectory grain agree; every published receipt's run plan is rebuilt from current source by
``pay_or_test_v3_replay.setup_for_receipt``; and a baseline episode played here audits against the setup it returns.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "tools" / "cli_subjects"))

import pay_or_test_v3_replay as replay  # noqa: E402
from aeread.shared_runner.run.publication import (  # noqa: E402
    MANIFEST_FILENAME,
    assert_public_payload,
    bundle_artifact_digests,
)
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes, plan_with_recorded_pins  # noqa: E402
from aeread.shared_runner.task.evaluation import audit_family_receipt  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_v3_baselines as baselines  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_v3_case_matrix as pack_module  # noqa: E402

EVIDENCE = REPOSITORY / "evidence" / "procurement_allocation"
BUNDLES = sorted(p.parent.parent for p in EVIDENCE.glob("procurement_allocation_pay_or_test_v3_*/reports/campaign.json"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_published_campaigns_are_the_twelve_runs_the_profile_names() -> None:
    names = {bundle.name.removeprefix("procurement_allocation_pay_or_test_v3_") for bundle in BUNDLES}
    assert names == {
        "pilot_v3_codex_cli_sol61_v1", "pilot_v3_claude_code_opus55_v1",
        "confirm_v3_codex_cli_sol61_v1", "confirm_v3_claude_code_opus55_v1",
        "odds_diagnostic_v3_codex_cli_sol61_v1", "odds_diagnostic_v3_claude_code_opus55_v1",
        "confirm_v3_openrouter_gemini38_flash_v1", "confirm_v3_openrouter_gpt6_luna_v1",
        "pilot_v3_control_gpt6_luna_high_v1", "pilot_v3_control_gemini38_flash_high_v1",
        "confirm_v3_control_gpt6_luna_high_v1", "confirm_v3_scripted_baselines_v1",
    }


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name)
def test_each_bundle_is_sealed_public_and_consistent(bundle: Path) -> None:
    manifest = json.loads((bundle / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["artifacts"] == bundle_artifact_digests(bundle)
    body = {k: v for k, v in manifest.items() if k not in ("manifest_sha256", "publication_sha256")}
    import hashlib
    assert manifest["manifest_sha256"] == hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            assert_public_payload(path.name, path.read_bytes())
    campaign = json.loads((bundle / "reports" / "campaign.json").read_text(encoding="utf-8"))
    assert campaign["campaign_id"] == manifest["publication_id"] == bundle.name
    cells = _jsonl(bundle / "tables" / "cells.jsonl")
    projections = _jsonl(bundle / "receipts" / "projections.jsonl")
    assert len(cells) == len(projections) == campaign["planned_trajectory_count"]
    assert {c["receipt_sha256"] for c in cells} == {p["source_receipt_sha256"] for p in projections}
    grain = _jsonl(bundle / "trajectories" / "sanitized.jsonl")
    assert grain and {row["source_receipt_sha256"] for row in grain} <= {c["receipt_sha256"] for c in cells}


@pytest.mark.parametrize("bundle", BUNDLES, ids=lambda b: b.name)
def test_every_published_receipt_rebuilds_its_run_plan_from_current_source(bundle: Path) -> None:
    for cell in _jsonl(bundle / "tables" / "cells.jsonl")[:: max(1, 10)]:
        receipt = {key: cell[key] for key in ("case_id", "run_plan_sha256", "plan_implementation_pins")}
        setup = replay.setup_for_receipt(receipt)
        pins = tuple(ImplementationPin.from_dict(item) for item in cell["plan_implementation_pins"])
        plan, _drift = plan_with_recorded_pins(setup.plan, pins)
        assert plan.plan_sha256 == cell["run_plan_sha256"], cell["campaign_cell_key"]


def test_a_receipt_no_campaign_made_is_refused() -> None:
    cell = _jsonl(BUNDLES[0] / "tables" / "cells.jsonl")[0]
    with pytest.raises(ValueError, match="no published version 3 campaign"):
        replay.setup_for_receipt({**cell, "run_plan_sha256": "0" * 64})


def test_a_baseline_episode_played_here_audits_against_the_setup_the_replay_returns(tmp_path: Path) -> None:
    case_path = sorted(pack_module.case_paths(split=baselines.PACK))[0]
    row = asyncio.run(baselines._play(case_path, 0, None, tmp_path / "ev"))
    (receipt_path,) = (tmp_path / "ev").rglob("evaluation_receipt.json")
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["receipt_sha256"] == row["receipt_sha256"]
    audited = audit_family_receipt(setup=replay.setup_for_receipt(receipt), receipt_path=receipt_path)
    assert audited["scores"]
