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
from aeread.shared_runner.run.publication import (
    MANIFEST_FILENAME,
    rebuild_publication_manifest,
    seal_publication_manifest,
)
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


def _sealed_receipts(attempt_dirs):
    return [json.loads((d / "evaluation_receipt.json").read_bytes()) for d in attempt_dirs]


def _projection(receipt, **changes):
    row = {
        "source_receipt_sha256": receipt["receipt_sha256"],
        "run_plan_id": receipt["run_plan_id"],
        "cell_id": receipt["cell_id"],
        "episode_id": receipt["episode_id"],
        "episode_attempt_id": receipt["episode_attempt_id"],
        "scores": receipt["scores"],
    }
    row.update(changes)
    return row


def _bundle_without_grain(
    tmp_path, *, declared=(), projections=(), summary=("0" * 64,), bindings=None, name="nograin"
):
    """A correctly sealed bundle with no trajectory grain."""

    bundle = tmp_path / name
    (bundle / "reports").mkdir(parents=True)
    (bundle / "reports" / "summary.json").write_text(json.dumps({"receipts": list(summary)}))
    if projections:
        (bundle / "receipts").mkdir()
        (bundle / "receipts" / "projections.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in projections)
        )
    fields = {"source_receipt_sha256s": list(declared)} if declared else {}
    seal_publication_manifest(
        bundle,
        publication_id="housing_replay_fixture_v1",
        privacy_boundary={"included": "receipt digests", "excluded": "raw run evidence"},
        source_bindings=bindings,
        **fields,
    )
    return bundle


def test_a_declared_receipt_without_the_grain_and_without_evidence_is_missing(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    bundle = _bundle_without_grain(tmp_path, declared=[r.receipt_sha256 for r in receipts])
    shutil.rmtree(attempt_dirs[1])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["counts"] == {VERIFIED: 1, DIFFERS: 0, EVIDENCE_MISSING: 1}
    assert report["verified"] is False
    assert report["coverage"] == "declared_receipts" and report["declared_receipts"] == 2
    assert report["verdict_reasons"]


def test_a_source_binding_receipt_list_declares_receipts_too(published, tmp_path) -> None:
    """The refund bundles list their receipts as ``source_bindings.receipt_sha256s``."""

    _bundle, run_root, receipts, attempt_dirs = published
    bundle = _bundle_without_grain(
        tmp_path, bindings={"receipt_sha256s": [r.receipt_sha256 for r in receipts]}
    )
    shutil.rmtree(attempt_dirs[1])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["coverage"] == "declared_receipts" and report["declared_receipts"] == 2
    assert report["counts"] == {VERIFIED: 1, DIFFERS: 0, EVIDENCE_MISSING: 1}
    assert report["verified"] is False


def test_projection_rows_declare_receipts_and_are_compared(published, tmp_path) -> None:
    _bundle, run_root, _receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    bundle = _bundle_without_grain(tmp_path, projections=[_projection(r) for r in sealed])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is True and report["verdict_reasons"] == []
    assert report["coverage"] == "declared_receipts"
    assert report["published_projections_checked"] == 2
    assert report["counts"][VERIFIED] == 2


def test_a_projection_whose_scores_were_altered_differs(published, tmp_path) -> None:
    _bundle, run_root, _receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    altered = json.loads(json.dumps(sealed[0]["scores"]))
    altered[0]["value"] = (altered[0].get("value") or 0) + 1
    rows = [_projection(sealed[0], scores=altered), _projection(sealed[1])]
    bundle = _bundle_without_grain(tmp_path, projections=rows)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert differs["source_receipt_sha256"] == sealed[0]["receipt_sha256"]
    assert "receipts/projections.jsonl" in differs["reason"] and "scores" in differs["reason"]


def test_a_projection_whose_cell_id_changed_differs(published, tmp_path) -> None:
    _bundle, run_root, _receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    rows = [_projection(sealed[0]), _projection(sealed[1], cell_id="some_other_cell")]
    bundle = _bundle_without_grain(tmp_path, projections=rows)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert "cell_id" in differs["reason"]


def test_a_projection_row_the_grain_cannot_list_is_still_expected(published) -> None:
    """A zero-action episode has no grain row; its projection row still declares it."""

    bundle, run_root, _receipts, attempt_dirs = published
    ghost = "ab" * 32
    ghost_row = _projection(_sealed_receipts(attempt_dirs)[0], source_receipt_sha256=ghost)
    del ghost_row["scores"]
    (bundle / "receipts").mkdir()
    (bundle / "receipts" / "projections.jsonl").write_text(json.dumps(ghost_row) + "\n")
    rebuild_publication_manifest(bundle)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["coverage"] == "every_published_episode"
    assert report["verified"] is False and report["counts"][EVIDENCE_MISSING] == 1
    (missing,) = [row for row in report["rows"] if row["status"] == EVIDENCE_MISSING]
    assert missing["source_receipt_sha256"] == ghost


def test_without_the_grain_and_without_a_declared_inventory_nothing_verifies(published, tmp_path) -> None:
    """Missing evidence cannot be detected when nothing says what should exist."""

    _bundle, run_root, _receipts, _ = published
    summary = [r["receipt_sha256"] for r in _sealed_receipts(_attempts(run_root))]
    bundle = _bundle_without_grain(tmp_path, summary=summary)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["coverage"] == "receipts_found_under_run_root"
    assert report["counts"][VERIFIED] == 2 and report["declared_receipts"] == 0
    assert report["verified"] is False
    assert any("no receipt inventory" in reason for reason in report["verdict_reasons"])
    empty = tmp_path / "empty_runs"
    empty.mkdir()
    nothing = verify_bundle_replay(bundle, empty, setup_for=setup_for)
    assert nothing["verified"] is False and nothing["rows"] == []
    assert "no row was checked" in nothing["verdict_reasons"]


def _attempts(run_root):
    return sorted(path.parent for path in run_root.rglob("evaluation_receipt.json"))


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


def _rewrite_manifest(bundle, **changes):
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest.update(changes)
    path.write_text(json.dumps(manifest))


def test_editing_a_sealed_artifact_without_resealing_is_tampered(published) -> None:
    bundle, run_root, _receipts, _ = published
    (bundle / "reports" / "summary.json").write_text(json.dumps({"receipts": ["edited"]}))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["counts"] == {VERIFIED: 2, DIFFERS: 0, EVIDENCE_MISSING: 0}
    assert report["manifest"]["status"] == "tampered"
    assert report["manifest"]["altered_or_missing_artifacts"] == ["reports/summary.json"]
    assert report["verified"] is False
    assert any("manifest" in reason for reason in report["verdict_reasons"])


def test_deleting_a_sealed_artifact_without_resealing_is_tampered(published) -> None:
    bundle, run_root, _receipts, _ = published
    (bundle / "reports" / "summary.json").unlink()
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["manifest"]["altered_or_missing_artifacts"] == ["reports/summary.json"]
    assert report["verified"] is False


def test_an_unsealed_addition_is_reported_not_a_failure(published) -> None:
    bundle, run_root, _receipts, _ = published
    (bundle / "README.md").write_text("added after sealing\n")
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["manifest"]["unsealed_artifacts"] == ["README.md"]
    assert report["manifest"]["altered_or_missing_artifacts"] == []
    assert report["verified"] is True


def test_a_family_layout_manifest_is_unchecked_and_still_verifies(published) -> None:
    bundle, run_root, _receipts, _ = published
    _rewrite_manifest(bundle, schema_version="aeread.family_publication/0.1")
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "unchecked"
    assert "aeread.family_publication/0.1" in report["manifest"]["reason"]
    assert report["verified"] is True


def test_an_edited_manifest_seal_is_tampered(published) -> None:
    bundle, run_root, _receipts, _ = published
    _rewrite_manifest(bundle, manifest_sha256="0" * 64)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["verified"] is False


def test_the_verb_prints_the_manifest_status_and_fails_a_tampered_bundle(published, capsys) -> None:
    bundle, run_root, _receipts, _ = published
    arguments = [str(bundle), "--run-root", str(run_root), "--setup", f"{__name__}:setup_for"]
    assert replay_verification.main(arguments) == 0
    assert "manifest=sealed" in capsys.readouterr().out
    (bundle / "reports" / "summary.json").write_text("{}")
    assert replay_verification.main(arguments) == 1
    out = capsys.readouterr().out
    assert "manifest=tampered" in out
    assert "  not verified: " in out and "reports/summary.json" in out
