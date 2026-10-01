"""``aeread verify-replay`` recomputes a bundle's scores from sealed evidence.

DC-T-01: published replay was a boolean copied from the run that produced
the row. The check here is the reviewer's: find each published receipt's
sealed attempt, re-drive it, recompute the score, compare.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from aeread.shared_runner.run import replay_verification
from aeread.shared_runner.run.publication import seal_publication_manifest
from aeread.shared_runner.run.publish_trajectories import GRAIN, publish_trajectory_grain
from aeread.shared_runner.run.replay_verification import (
    DIFFERS,
    EVIDENCE_MISSING,
    VERIFIED,
    verify_bundle_replay,
)
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
    finalize_housing_execution,
)

WORLD_SEEDS = (41001, 41002)
_SETUPS: dict[str, object] = {}


def _setup(world_seed: int):
    return build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
        world_seed=world_seed,
    )


def setup_for(receipt):
    """The family's part of the check: the sealed plan a receipt belongs to."""

    return _SETUPS[receipt["run_plan_id"]]


@pytest.fixture
def published(tmp_path: Path):
    """Two scripted housing worlds, run, sealed and published with the grain."""

    run_root = tmp_path / "runs"
    receipts, attempt_dirs = [], []
    _SETUPS.clear()
    for world_seed in WORLD_SEEDS:
        setup = _setup(world_seed)
        execution = asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=run_root,
                prompt_sources=setup.prompt_sources,
                providers={
                    "housing_scripted_tenant": HousingScriptedTenantProvider(),
                    "housing_scripted_landlord": HousingScriptedLandlordProvider(),
                },
                pricing=setup.pricing,
                episode_attempt_ordinal=0,
            )
        )
        receipts.append(finalize_housing_execution(setup=setup, execution=execution))
        attempt_dirs.append(execution.evidence.root)
        execution.evidence.close()
        _SETUPS[setup.plan.run_plan_id] = setup
    bundle = tmp_path / "bundle"
    (bundle / "reports").mkdir(parents=True)
    (bundle / "reports" / "summary.json").write_text(
        json.dumps({"receipts": [receipt.receipt_sha256 for receipt in receipts]})
    )
    seal_publication_manifest(
        bundle,
        publication_id="housing_replay_fixture_v1",
        privacy_boundary={"included": "receipt digests", "excluded": "raw run evidence"},
    )
    publish_trajectory_grain(bundle, attempt_dirs)
    yield bundle, run_root, receipts, attempt_dirs
    _SETUPS.clear()


def test_every_published_row_is_re_driven_and_its_score_recomputed(published) -> None:
    bundle, run_root, receipts, _ = published
    before = sorted(path.read_bytes() for path in bundle.rglob("*") if path.is_file())
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is True
    assert report["coverage"] == "every_published_episode"
    assert report["counts"] == {VERIFIED: 2, DIFFERS: 0, EVIDENCE_MISSING: 0}
    assert report["scored_rows_verified"] == 2
    assert report["publication_id"] == "housing_replay_fixture_v1"
    assert {row["source_receipt_sha256"] for row in report["rows"]} == {
        receipt.receipt_sha256 for receipt in receipts
    }
    assert len({row["episode_key"] for row in report["rows"]}) == 2
    # The check reads; it writes nothing into the bundle.
    assert sorted(path.read_bytes() for path in bundle.rglob("*") if path.is_file()) == before


def test_a_published_episode_whose_evidence_is_gone_is_missing_not_verified(published) -> None:
    """Run roots do not last (EX-T-06); a row nobody can re-drive is not verified."""

    bundle, run_root, receipts, attempt_dirs = published
    shutil.rmtree(attempt_dirs[1])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert report["counts"] == {VERIFIED: 1, DIFFERS: 0, EVIDENCE_MISSING: 1}
    (missing,) = [row for row in report["rows"] if row["status"] == EVIDENCE_MISSING]
    assert missing["source_receipt_sha256"] == receipts[1].receipt_sha256
    assert missing["episode_key"] is not None


def test_a_sealed_receipt_whose_score_was_altered_differs(published) -> None:
    bundle, run_root, receipts, attempt_dirs = published
    receipt_path = attempt_dirs[0] / "evaluation_receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["scores"][0]["value"] = (receipt["scores"][0].get("value") or 0) + 1
    receipt_path.write_text(json.dumps(receipt))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert differs["source_receipt_sha256"] == receipts[0].receipt_sha256 and differs["reason"]


def test_altered_evidence_under_an_intact_receipt_differs(published) -> None:
    """The copied flag could not see this: the receipt is untouched and the
    events it was scored from are not the events on disk."""

    bundle, run_root, _receipts, attempt_dirs = published
    events = attempt_dirs[0] / "events.jsonl"
    lines = events.read_text().splitlines()
    events.chmod(0o644)
    events.write_text("\n".join(lines[:-1]) + "\n")
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1


def test_a_setup_built_from_other_source_does_not_verify(published) -> None:
    """The family moved on: a plan resolved from different source no longer
    owns the receipt, and the row is reported, not assumed."""

    bundle, run_root, _receipts, _ = published
    other = _setup(49999)
    report = verify_bundle_replay(bundle, run_root, setup_for=lambda receipt: other)
    assert report["verified"] is False
    assert report["counts"] == {VERIFIED: 0, DIFFERS: 2, EVIDENCE_MISSING: 0}


def test_without_the_grain_only_the_receipts_found_can_be_checked_and_the_report_says_so(published, tmp_path) -> None:
    bundle, run_root, _receipts, _ = published
    (bundle / GRAIN).unlink()
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["coverage"] == "receipts_found_under_run_root"
    assert report["verified"] is True and report["counts"][VERIFIED] == 2
    empty = tmp_path / "empty_runs"
    empty.mkdir()
    nothing = verify_bundle_replay(bundle, empty, setup_for=setup_for)
    assert nothing["verified"] is False and nothing["rows"] == []


def test_a_copy_of_the_same_run_root_is_not_counted_twice(published) -> None:
    bundle, run_root, _receipts, _ = published
    shutil.copytree(run_root, run_root.parent / "runs_backup")
    report = verify_bundle_replay(bundle, run_root.parent, setup_for=setup_for)
    assert report["counts"][VERIFIED] == 2 and report["duplicate_receipt_copies_ignored"] == 2


def test_the_verb_prints_a_line_to_paste_and_exits_by_the_verdict(published, tmp_path, capsys) -> None:
    from aeread.cli import VERBS

    assert VERBS["verify-replay"][0] == "aeread.shared_runner.run.replay_verification"
    bundle, run_root, _receipts, attempt_dirs = published
    out = tmp_path / "report.json"
    arguments = [str(bundle), "--run-root", str(run_root), "--setup", f"{__name__}:setup_for", "--json", str(out)]
    assert replay_verification.main(arguments) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("housing_replay_fixture_v1: 2 verified (2 scored), 0 differ, 0 evidence missing")
    assert json.loads(out.read_text())["verified"] is True

    shutil.rmtree(attempt_dirs[0])
    assert replay_verification.main(arguments[:-2]) == 1
    assert "evidence_missing:" in capsys.readouterr().out
    with pytest.raises(SystemExit) as raised:
        replay_verification.main([str(bundle), "--run-root", str(run_root), "--setup", "not_a_reference"])
    assert raised.value.code == 2


def test_the_dispatcher_returns_the_verdict_as_the_exit_status(published, monkeypatch, capsys) -> None:
    """`aeread verify-replay` must fail a shell pipeline when a row does not verify."""

    import sys

    from aeread import cli

    bundle, run_root, _receipts, attempt_dirs = published
    arguments = ["aeread", "verify-replay", str(bundle), "--run-root", str(run_root), "--setup", f"{__name__}:setup_for"]
    monkeypatch.setattr(sys, "argv", arguments)
    assert cli.main() == 0
    shutil.rmtree(attempt_dirs[0])
    assert cli.main() == 1
    assert "1 evidence missing" in capsys.readouterr().out
