"""``aeread verify-replay`` recomputes a bundle's scores from sealed evidence.

DC-T-01: published replay was a boolean copied from the run that produced
the row. The check here is the reviewer's: find each published receipt's
sealed attempt, re-drive it, recompute the score, compare.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from aeread.shared_runner.run import replay_verification
from aeread.shared_runner.run.publication import (
    KERNEL_MANIFEST_SCHEMA_VERSION,
    MANIFEST_FILENAME,
    _sealed_manifest,
    bundle_artifact_digests,
    rebuild_publication_manifest,
    seal_publication_manifest,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
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


def _expected_primary(receipt):
    (entry,) = [e for e in receipt["scores"] if e["leaf"]["leaf_id"] == receipt["primary_leaf_id"]]
    return entry["primary"]["value"]


def _bare(receipt, **changes):
    """A production-shaped row: identity and a primary score, no ``scores``."""

    row = _projection(receipt, **{"primary_leaf_id": receipt["primary_leaf_id"], **changes})
    del row["scores"]
    return row


def _verify_rows(published, tmp_path, rows):
    _bundle, run_root, _receipts, _ = published
    bundle = _bundle_without_grain(tmp_path, projections=rows)
    return verify_bundle_replay(bundle, run_root, setup_for=setup_for)


def test_a_projection_without_scores_but_a_wrong_cell_id_differs(published, tmp_path) -> None:
    sealed = _sealed_receipts(published[3])
    rows = [_bare(sealed[0]), _bare(sealed[1], cell_id="some_other_cell")]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert "cell_id" in differs["reason"] and "receipts/projections.jsonl" in differs["reason"]


def test_a_projection_without_scores_and_the_derived_primary_score_verifies(published, tmp_path) -> None:
    sealed = _sealed_receipts(published[3])
    rows = [_bare(r, primary_score=_expected_primary(r)) for r in sealed]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is True and report["verdict_reasons"] == []
    assert report["published_projections_checked"] == 2


def test_a_projection_with_a_wrong_primary_score_differs(published, tmp_path) -> None:
    sealed = _sealed_receipts(published[3])
    rows = [_bare(sealed[0], primary_score=999), _bare(sealed[1], primary_score=_expected_primary(sealed[1]))]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert "primary_score" in differs["reason"]


@pytest.mark.parametrize("field", ["case_id", "case_sha256", "run_plan_sha256"])
def test_a_projection_whose_case_or_plan_identity_changed_differs(published, tmp_path, field) -> None:
    sealed = _sealed_receipts(published[3])
    rows = [_projection(sealed[0], **{field: "altered"}), _projection(sealed[1])]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert field in differs["reason"]


def test_a_production_shaped_projection_verifies(published, tmp_path) -> None:
    sealed = _sealed_receipts(published[3])
    rows = [
        _projection(
            r,
            case_id=r["case_id"],
            case_sha256=r["case_sha256"],
            run_plan_sha256=r["run_plan_sha256"],
            primary_leaf_id=r["primary_leaf_id"],
        )
        for r in sealed
    ]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is True and report["published_projections_checked"] == 2


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


def _family_manifest(bundle, receipts=None, **changes):
    """A datacenter-style manifest: no per-file digests, a self-seal over the rest."""

    rest = {
        "schema_version": "aeread.example_family_publication/0.1",
        "publication_id": "housing_replay_fixture_v1",
    }
    if receipts is not None:
        rest["source_receipt_sha256s"] = list(receipts)
    rest.update(changes)
    sealed = {**rest, "artifact_sha256": hashlib.sha256(canonical_json_bytes(rest)).hexdigest()}
    (bundle / MANIFEST_FILENAME).write_text(json.dumps(sealed))
    return sealed


def _reseal(bundle, **changes):
    """Edit a kernel manifest and recompute its seal, as a forger who knows the format would."""

    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest.update(changes)
    manifest = {key: value for key, value in manifest.items() if value is not _DELETE}
    path.write_text(json.dumps(_sealed_manifest(manifest)))


_DELETE = object()


def test_a_family_layout_manifest_is_seal_only_and_verifies_on_its_declared_list(published) -> None:
    bundle, run_root, receipts, attempt_dirs = published
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "seal_only"
    assert report["manifest"]["seal_field"] == "artifact_sha256"
    assert report["verified"] is True and report["coverage"] == "declared_receipts"
    shutil.rmtree(attempt_dirs[1])
    missing = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert missing["manifest"]["status"] == "seal_only"
    assert missing["verified"] is False and missing["counts"][EVIDENCE_MISSING] == 1


def test_a_malformed_projection_digest_in_a_seal_only_bundle_is_reported(published) -> None:
    """Projection files of a seal_only bundle are read for comparison; a bad digest is not skipped."""

    bundle, run_root, receipts, attempt_dirs = published
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts])
    (bundle / "receipts").mkdir(exist_ok=True)
    row = _projection(_sealed_receipts(attempt_dirs)[0], source_receipt_sha256="not-a-digest")
    (bundle / "receipts" / "projections.jsonl").write_text(json.dumps(row) + "\n")
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "seal_only"
    assert report["verified"] is False
    assert any("not-a-digest" in entry for entry in report["malformed_declarations"])


def test_an_edited_family_seal_is_tampered(published) -> None:
    bundle, run_root, receipts, _ = published
    sealed = _family_manifest(bundle, [r.receipt_sha256 for r in receipts])
    sealed["source_receipt_sha256s"] = sealed["source_receipt_sha256s"][:1]
    (bundle / MANIFEST_FILENAME).write_text(json.dumps(sealed))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered" and report["verified"] is False


def test_a_family_manifest_without_a_receipt_list_does_not_read_unsealed_projections(published, tmp_path) -> None:
    """Family files are not sealed, so a projection file cannot stand in for the inventory."""

    _bundle, run_root, _receipts, attempt_dirs = published
    bundle = tmp_path / "family_nolist"
    (bundle / "receipts").mkdir(parents=True)
    rows = [_projection(r) for r in _sealed_receipts(attempt_dirs)]
    (bundle / "receipts" / "projections.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    _family_manifest(bundle)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "seal_only"
    assert report["verified"] is False and report["declared_receipts"] == 0
    assert report["coverage"] == "receipts_found_under_run_root"


def _files_map(bundle, **overrides):
    """The family ``files`` layout: path -> {sha256, bytes} for every bundle file."""

    files = {}
    for path in sorted(bundle.rglob("*")):
        relative = path.relative_to(bundle).as_posix()
        if path.is_file() and relative != MANIFEST_FILENAME:
            data = path.read_bytes()
            files[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    files.update(overrides)
    return files


def test_a_family_files_map_is_checked_file_by_file(published) -> None:
    """A family manifest that lists per-file digests under ``files`` is sealed, not seal_only.

    Before, only ``artifacts`` was read, so a sealed file deleted from such a
    bundle went unnoticed (EVID-O-03, #252).
    """

    bundle, run_root, receipts, _ = published
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=_files_map(bundle))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["manifest"]["seal_field"] == "artifact_sha256"
    assert report["manifest"]["altered_or_missing_artifacts"] == []
    assert report["verified"] is True


@pytest.mark.parametrize("change", ["deleted", "altered"])
def test_a_family_files_map_catches_a_deleted_or_altered_file(published, change) -> None:
    bundle, run_root, receipts, _ = published
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=_files_map(bundle))
    victim = sorted(path for path in _files_map(bundle))[0]
    if change == "deleted":
        (bundle / victim).unlink()
    else:
        (bundle / victim).write_bytes((bundle / victim).read_bytes() + b"x")
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["manifest"]["altered_or_missing_artifacts"] == [victim]
    assert report["verified"] is False


@pytest.mark.parametrize(
    "entry",
    [{"bytes": 1}, {"bytes": 1, "sha256": "not-a-digest"}, "d" * 64, None],
    ids=["no_digest", "bad_digest", "bare_string", "null"],
)
def test_a_malformed_files_entry_is_tampered(published, entry) -> None:
    bundle, run_root, receipts, _ = published
    files = _files_map(bundle)
    files[sorted(files)[0]] = entry
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=files)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert "files holds a malformed or duplicate entry" in report["manifest"]["reason"]


def test_a_files_map_that_is_not_an_object_is_tampered(published) -> None:
    bundle, run_root, receipts, _ = published
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=["README.md"])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert "files is a list" in report["manifest"]["reason"]


def test_artifacts_and_files_together_must_agree(published) -> None:
    """No bundle on main carries both; if one does, both lists are read and must agree."""

    bundle, run_root, receipts, _ = published
    files = _files_map(bundle)
    first, last = sorted(files)[0], sorted(files)[-1]
    digests = {path: entry["sha256"] for path, entry in files.items()}
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=files, artifacts=digests)
    assert verify_bundle_replay(bundle, run_root, setup_for=setup_for)["manifest"]["status"] == "sealed"
    # The two lists disagree about a file that is intact on disk.
    conflicting = {**files, first: {"bytes": 1, "sha256": "e" * 64}}
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=conflicting, artifacts=digests)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert "malformed or duplicate entry" in report["manifest"]["reason"]
    # A file sealed only under ``files`` is still checked when ``artifacts`` exists.
    only_artifacts = {path: digest for path, digest in digests.items() if path != last}
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts], files=files, artifacts=only_artifacts)
    (bundle / last).unlink()
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["manifest"]["altered_or_missing_artifacts"] == [last]


def _early_manifest(bundle, **changes):
    """The early kernel layout: artifacts as a list of objects, a publication_sha256 self-seal."""

    digests = bundle_artifact_digests(bundle)
    rest = {
        "schema_version": KERNEL_MANIFEST_SCHEMA_VERSION,
        "publication_id": "housing_replay_fixture_v1",
        "artifacts": [
            {"path": path, "sha256": digest, "size_bytes": (bundle / path).stat().st_size}
            for path, digest in digests.items()
        ],
    }
    rest.update(changes)
    sealed = {**rest, "publication_sha256": hashlib.sha256(canonical_json_bytes(rest)).hexdigest()}
    (bundle / MANIFEST_FILENAME).write_text(json.dumps(sealed))


def test_an_early_kernel_manifest_with_an_artifact_list_is_sealed_and_checked(published) -> None:
    bundle, run_root, _receipts, _ = published
    _early_manifest(bundle)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["manifest"]["seal_field"] == "publication_sha256"
    assert report["verified"] is True and report["coverage"] == "every_published_episode"
    (bundle / "reports" / "summary.json").write_text("{}")
    tampered = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert tampered["manifest"]["status"] == "tampered"
    assert tampered["manifest"]["altered_or_missing_artifacts"] == ["reports/summary.json"]
    assert tampered["verified"] is False


def test_a_manifest_with_no_recognised_seal_is_unchecked_and_not_verified(published) -> None:
    bundle, run_root, _receipts, _ = published
    (bundle / MANIFEST_FILENAME).write_text(json.dumps({"schema_version": "x/0.1", "publication_id": "p"}))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "unchecked" and report["verified"] is False
    assert "no recognised seal" in report["manifest"]["reason"]


def test_a_kernel_manifest_whose_schema_was_edited_is_tampered(published) -> None:
    bundle, run_root, _receipts, _ = published
    _rewrite_manifest(bundle, schema_version="aeread.family_publication/0.1")
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered" and report["verified"] is False


_MANIFEST_EDITS = {
    "schema": {"schema_version": "aeread.family_publication/0.1"},
    "artifacts_deleted": {"artifacts": _DELETE},
    "artifacts_as_list": {"artifacts": []},
}


@pytest.mark.parametrize("edit", sorted(_MANIFEST_EDITS))
def test_a_sealed_artifact_edit_cannot_be_hidden_by_changing_the_manifest(published, edit) -> None:
    """Edited without resealing, and edited then resealed: neither may verify."""

    bundle, run_root, _receipts, _ = published
    (bundle / "reports" / "summary.json").write_text(json.dumps({"receipts": ["edited"]}))
    changes = _MANIFEST_EDITS[edit]
    _reseal(bundle, **changes)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["verified"] is False


@pytest.mark.parametrize("edit", ["artifacts_deleted", "artifacts_as_list"])
def test_a_kernel_manifest_without_a_digest_map_is_tampered_even_when_unedited(published, edit) -> None:
    bundle, run_root, _receipts, _ = published
    _reseal(bundle, **_MANIFEST_EDITS[edit])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered" and report["verified"] is False


def test_an_empty_grain_and_reports_only_receipts_is_not_a_declared_inventory(published, tmp_path) -> None:
    """One attempt removed, grain empty, receipts only in reports/: nothing says what should exist."""

    _bundle, run_root, receipts, attempt_dirs = published
    bundle = tmp_path / "emptygrain"
    (bundle / "reports").mkdir(parents=True)
    (bundle / "reports" / "summary.json").write_text(
        json.dumps({"receipts": [r.receipt_sha256 for r in receipts]})
    )
    (bundle / "trajectories").mkdir()
    (bundle / GRAIN).write_text("")
    seal_publication_manifest(
        bundle,
        publication_id="housing_replay_fixture_v1",
        privacy_boundary={"included": "receipt digests", "excluded": "raw run evidence"},
    )
    shutil.rmtree(attempt_dirs[1])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert report["coverage"] == "receipts_found_under_run_root"
    assert any("no receipt inventory" in reason for reason in report["verdict_reasons"])


def test_a_projection_file_added_after_sealing_is_not_an_inventory(published, tmp_path) -> None:
    _bundle, run_root, _receipts, attempt_dirs = published
    bundle = _bundle_without_grain(tmp_path)
    (bundle / "receipts").mkdir()
    rows = [_projection(r) for r in _sealed_receipts(attempt_dirs)]
    (bundle / "receipts" / "projections.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False and report["declared_receipts"] == 0
    assert report["manifest"]["status"] == "sealed"
    assert report["manifest"]["unsealed_artifacts"] == ["receipts/projections.jsonl"]


def test_a_symlinked_projection_is_tampered_and_listed(published, tmp_path) -> None:
    _bundle, run_root, _receipts, attempt_dirs = published
    bundle = _bundle_without_grain(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("".join(json.dumps(_projection(r)) + "\n" for r in _sealed_receipts(attempt_dirs)))
    (bundle / "receipts").mkdir()
    (bundle / "receipts" / "projections.jsonl").symlink_to(outside)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["manifest"]["symlinks"] == ["receipts/projections.jsonl"]
    assert report["verified"] is False and report["declared_receipts"] == 0


def test_a_malformed_manifest_digest_is_reported_not_dropped(published, tmp_path) -> None:
    _bundle, run_root, receipts, _ = published
    bundle = _bundle_without_grain(tmp_path, declared=[r.receipt_sha256 for r in receipts] + ["not-a-digest"])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert any("not-a-digest" in item or "[2]" in item for item in report["malformed_declarations"])


def test_a_manifest_receipt_list_that_is_a_string_is_malformed(published, tmp_path) -> None:
    _bundle, run_root, receipts, _ = published
    bundle = _bundle_without_grain(
        tmp_path,
        declared=[r.receipt_sha256 for r in receipts],
        bindings={"receipt_sha256s": receipts[0].receipt_sha256},
    )
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert any("receipt_sha256s" in item for item in report["malformed_declarations"])


def test_a_projection_row_with_a_malformed_digest_is_reported(published, tmp_path) -> None:
    _bundle, run_root, _receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    rows = [_projection(r) for r in sealed] + [_projection(sealed[0], source_receipt_sha256="NOT-HEX")]
    bundle = _bundle_without_grain(tmp_path, projections=rows)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert any("receipts/projections.jsonl" in item for item in report["malformed_declarations"])


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


def test_a_projection_file_that_does_not_parse_is_reported_not_skipped(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    rows = [_projection(r) for r in _sealed_receipts(attempt_dirs)]
    bundle = _bundle_without_grain(
        tmp_path, declared=[r.receipt_sha256 for r in receipts], projections=rows
    )
    (bundle / "receipts" / "projections.jsonl").write_text("{not json\n")
    _reseal(bundle, artifacts=bundle_artifact_digests(bundle))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert report["manifest"]["status"] == "sealed"
    assert any("receipts/projections.jsonl" in item for item in report["malformed_declarations"])


def _seal_again(bundle, *, declared=()):
    """A correctly sealed bundle after a sealed file changed: drop the manifest and seal anew."""

    (bundle / MANIFEST_FILENAME).unlink()
    fields = {"source_receipt_sha256s": list(declared)} if declared else {}
    seal_publication_manifest(
        bundle,
        publication_id="housing_replay_fixture_v1",
        privacy_boundary={"included": "receipt digests", "excluded": "raw run evidence"},
        **fields,
    )


def _grain_rows(bundle):
    return [json.loads(line) for line in (bundle / GRAIN).read_text().splitlines() if line.strip()]


def _write_grain(bundle, rows):
    (bundle / GRAIN).write_text("".join(json.dumps(row) + "\n" for row in rows))


# R1: rows may not cite receipts the manifest does not declare.


@pytest.mark.parametrize("where", ["projections", "grain"])
def test_a_seal_only_bundle_whose_rows_cite_an_undeclared_receipt_does_not_verify(published, where) -> None:
    bundle, run_root, receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    if where == "projections":
        shutil.rmtree(bundle / "trajectories")
        (bundle / "receipts").mkdir()
        (bundle / "receipts" / "projections.jsonl").write_text(
            "".join(json.dumps(_projection(r)) + "\n" for r in sealed)
        )
    _family_manifest(bundle, [receipts[0].receipt_sha256])
    shutil.rmtree(attempt_dirs[1])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "seal_only"
    assert report["verified"] is False
    assert any("references receipts the bundle does not declare: 1" in reason for reason in report["verdict_reasons"])


# R2 + R8: every identity and admission field of a projection is compared.

_COMPARED_FIELDS = [
    "run_plan_id",
    "run_plan_sha256",
    "cell_id",
    "case_id",
    "case_sha256",
    "episode_id",
    "episode_attempt_id",
    "primary_leaf_id",
    "status",
    "inclusion_status",
    "replay_level",
]


@pytest.mark.parametrize("with_scores", [True, False], ids=["with_scores", "without_scores"])
@pytest.mark.parametrize("field", _COMPARED_FIELDS)
def test_every_identity_and_admission_field_of_a_projection_is_compared(published, tmp_path, field, with_scores) -> None:
    sealed = _sealed_receipts(published[3])
    build = _projection if with_scores else _bare
    rows = [build(sealed[0], **{field: "altered"}), build(sealed[1])]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert field in differs["reason"] and "receipts/projections.jsonl" in differs["reason"]


@pytest.mark.parametrize("with_scores", [True, False], ids=["with_scores", "without_scores"])
def test_a_projection_carrying_every_compared_field_unaltered_verifies(published, tmp_path, with_scores) -> None:
    sealed = _sealed_receipts(published[3])
    build = _projection if with_scores else _bare
    rows = [build(r, **{name: r[name] for name in _COMPARED_FIELDS}) for r in sealed]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is True and report["published_projections_checked"] == 2


def test_one_wrong_projection_among_correct_ones_for_the_same_digest_differs(published, tmp_path) -> None:
    sealed = _sealed_receipts(published[3])
    rows = [_projection(sealed[0]), _projection(sealed[0], cell_id="some_other_cell"), _projection(sealed[1])]
    report = _verify_rows(published, tmp_path, rows)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert differs["source_receipt_sha256"] == sealed[0]["receipt_sha256"] and "cell_id" in differs["reason"]


# R3: trajectory grain rows are compared against the audited receipt.


def test_a_clean_grain_is_compared_row_by_row(published) -> None:
    bundle, run_root, _receipts, _ = published
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is True
    assert report.get("trajectory_rows_checked") == len(_grain_rows(bundle)) > 0


def test_a_resealed_grain_with_a_rewritten_run_plan_id_differs(published) -> None:
    bundle, run_root, _receipts, _ = published
    rows = _grain_rows(bundle)
    for row in rows:
        row["run_plan_id"] = "some_other_plan"
    _write_grain(bundle, rows)
    _seal_again(bundle)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["verified"] is False
    assert report["counts"][DIFFERS] >= 1
    assert any("trajectories/sanitized.jsonl" in r["reason"] and "run_plan_id" in r["reason"] for r in report["rows"] if r["status"] == DIFFERS)


def test_only_the_last_grain_row_of_a_digest_is_altered_and_still_differs(published) -> None:
    bundle, run_root, receipts, _ = published
    rows = _grain_rows(bundle)
    mine = [row for row in rows if row["source_receipt_sha256"] == receipts[0].receipt_sha256]
    assert len(mine) > 1
    mine[-1]["episode_attempt_id"] = "altered"
    _write_grain(bundle, rows)
    _seal_again(bundle)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1


def test_a_seal_only_grain_is_read_for_comparison(published) -> None:
    bundle, run_root, receipts, _ = published
    rows = _grain_rows(bundle)
    for row in rows:
        row["cell_id"] = "some_other_cell"
    _write_grain(bundle, rows)
    _family_manifest(bundle, [r.receipt_sha256 for r in receipts])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "seal_only"
    assert report["verified"] is False and report["counts"][DIFFERS] == 2


# R4: nested files are discovered.


def test_a_nested_sealed_projection_file_is_compared(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    bundle = _bundle_without_grain(tmp_path, declared=[r.receipt_sha256 for r in receipts])
    (bundle / "receipts" / "nested").mkdir(parents=True)
    rows = [_projection(sealed[0]), _projection(sealed[1], cell_id="some_other_cell")]
    (bundle / "receipts" / "nested" / "projections.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    _seal_again(bundle, declared=[r.receipt_sha256 for r in receipts])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["published_projections_checked"] == 2
    assert report["verified"] is False and report["counts"][DIFFERS] == 1


# R5: every record must be a JSON object.


def test_non_object_records_in_a_sealed_projection_file_are_malformed(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    rows = [_projection(r) for r in _sealed_receipts(attempt_dirs)]
    bundle = _bundle_without_grain(tmp_path, declared=[r.receipt_sha256 for r in receipts], projections=rows)
    with (bundle / "receipts" / "projections.jsonl").open("a") as handle:
        handle.write("null\n17\n")
    _seal_again(bundle, declared=[r.receipt_sha256 for r in receipts])
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["verified"] is False
    assert "receipts/projections.jsonl: record 2 is not a JSON object" in report["malformed_declarations"]
    assert "receipts/projections.jsonl: record 3 is not a JSON object" in report["malformed_declarations"]


@pytest.mark.parametrize("document", ["17", '[{"a": 1}, 5]'])
def test_a_json_document_that_is_not_an_object_or_a_list_of_objects_is_malformed(published, tmp_path, document) -> None:
    _bundle, run_root, receipts, _ = published
    declared = [r.receipt_sha256 for r in receipts]
    bundle = _bundle_without_grain(tmp_path, declared=declared)
    (bundle / "receipts").mkdir()
    (bundle / "receipts" / "extra.json").write_text(document)
    _seal_again(bundle, declared=declared)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["verified"] is False
    assert any(item.startswith("receipts/extra.json: record") and "not a JSON object" in item for item in report["malformed_declarations"])


# R6: symlinks are detected everywhere.


def test_a_hidden_symlink_is_tampered_and_listed(published, tmp_path) -> None:
    bundle, run_root, _receipts, _ = published
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (bundle / "reports" / ".hidden.json").symlink_to(outside)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["symlinks"] == ["reports/.hidden.json"]
    assert report["manifest"]["status"] == "tampered" and report["verified"] is False


# R7: an unsealed note does not steer which receipts are audited.


def test_an_unsealed_note_naming_another_receipt_does_not_reject_a_valid_bundle(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    bundle = _bundle_without_grain(tmp_path, declared=[receipts[0].receipt_sha256])
    receipt_path = attempt_dirs[1] / "evaluation_receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["scores"][0]["value"] = (receipt["scores"][0].get("value") or 0) + 1
    receipt_path.write_text(json.dumps(receipt))
    (bundle / "reports" / "note.json").write_text(json.dumps({"see": receipts[1].receipt_sha256}))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "sealed"
    assert report["counts"] == {VERIFIED: 1, DIFFERS: 0, EVIDENCE_MISSING: 0}
    assert report["verified"] is True


# Round 4: every input the verdict relies on is checked.

from aeread.shared_runner.run.publication import receipt_projection  # noqa: E402


def _verify_no_crash(bundle, run_root):
    """Run the verb; an exception on a legitimate bundle is an assertion failure."""

    try:
        return verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    except UnicodeDecodeError as error:
        pytest.fail(f"verification crashed on an unreadable file: {error}")


def _production_projection(receipt):
    return receipt_projection(receipt, campaign_cell_key="campaign|cell|0")


def _sealed_projection_bundle(tmp_path, receipts, rows, name="prod"):
    declared = [r.receipt_sha256 for r in receipts]
    return _bundle_without_grain(tmp_path, declared=declared, projections=rows, name=name)


def test_a_projection_row_without_its_receipt_binding_is_malformed(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    rows = [_production_projection(r) for r in sealed]
    stray = _production_projection(sealed[0])
    del stray["source_receipt_sha256"]
    stray["cell_id"] = "some_other_cell"
    bundle = _sealed_projection_bundle(tmp_path, receipts, rows + [stray])
    report = _verify_no_crash(bundle, run_root)
    assert report["manifest"]["status"] == "sealed"
    assert report["verified"] is False
    assert "receipts/projections.jsonl: record 2 has no source_receipt_sha256" in report["malformed_declarations"]


def test_a_grain_row_without_its_receipt_binding_is_malformed(published) -> None:
    bundle, run_root, _receipts, _ = published
    rows = _grain_rows(bundle)
    assert len(rows) > 1
    del rows[1]["source_receipt_sha256"]
    _write_grain(bundle, rows)
    _seal_again(bundle)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False
    assert f"{GRAIN}: record 1 has no source_receipt_sha256" in report["malformed_declarations"]


def test_a_family_archive_without_any_binding_is_ignored(published, tmp_path) -> None:
    _bundle, run_root, receipts, _ = published
    bundle = _bundle_without_grain(tmp_path, declared=[r.receipt_sha256 for r in receipts])
    (bundle / "trajectories").mkdir()
    (bundle / "trajectories" / "archive.jsonl").write_text(
        json.dumps({"receipt_sha256": receipts[0].receipt_sha256, "step": 0}) + "\n"
    )
    _seal_again(bundle, declared=[r.receipt_sha256 for r in receipts])
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is True and report["malformed_declarations"] == []


def test_a_binding_nested_inside_a_record_is_not_a_binding(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    rows = [_production_projection(r) for r in sealed]
    rows.append({"note": {"source_receipt_sha256": sealed[0]["receipt_sha256"]}})
    bundle = _sealed_projection_bundle(tmp_path, receipts, rows)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False
    assert "receipts/projections.jsonl: record 2 has no source_receipt_sha256" in report["malformed_declarations"]


_COPIED = {
    "cluster_id": "altered",
    "cluster_level": "altered",
    "evidence": {"altered": True},
    "deferred_leaf_ids": ["altered"],
    "spec_version": "altered",
    "observability_limits": {"altered": True},
    "failure": {"condition": "altered", "failure_class": "altered"},
}


@pytest.mark.parametrize("field", sorted(_COPIED))
def test_a_copied_projection_field_that_differs_from_the_receipt_differs(published, tmp_path, field) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    first = _production_projection(sealed[0])
    first[field] = _COPIED[field]
    rows = [first, _production_projection(sealed[1])]
    bundle = _sealed_projection_bundle(tmp_path, receipts, rows)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert field in differs["reason"] and "receipts/projections.jsonl" in differs["reason"]


def test_a_correct_production_shaped_projection_verifies(published, tmp_path) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    rows = [_production_projection(r) for r in _sealed_receipts(attempt_dirs)]
    assert all("failure" in row and "campaign_cell_key" in row for row in rows)
    bundle = _sealed_projection_bundle(tmp_path, receipts, rows)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is True and report["verdict_reasons"] == []
    assert report["published_projections_checked"] == 2


#: The trajectory identity contract, written out here rather than read from the
#: module, so that dropping a field from the implementation fails a test.
TRAJECTORY_IDENTITY_FIELDS = (
    "run_plan_id",
    "run_plan_sha256",
    "cell_id",
    "case_id",
    "case_sha256",
    "episode_id",
    "episode_attempt_id",
)


@pytest.mark.parametrize("field", TRAJECTORY_IDENTITY_FIELDS)
def test_every_trajectory_identity_field_is_compared(published, field) -> None:
    bundle, run_root, receipts, _ = published
    rows = _grain_rows(bundle)
    for row in rows:
        if row["source_receipt_sha256"] == receipts[0].receipt_sha256:
            row[field] = "altered"
    _write_grain(bundle, rows)
    _seal_again(bundle)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1
    (differs,) = [row for row in report["rows"] if row["status"] == DIFFERS]
    assert field in differs["reason"]


def test_two_grain_rows_sharing_a_digest_one_wrong_differs(published) -> None:
    bundle, run_root, receipts, _ = published
    rows = _grain_rows(bundle)
    mine = [row for row in rows if row["source_receipt_sha256"] == receipts[0].receipt_sha256]
    assert len(mine) > 1
    mine[0]["cell_id"] = "some_other_cell"
    _write_grain(bundle, rows)
    _seal_again(bundle)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1


def test_an_unsealed_binary_note_does_not_reject_a_bundle_with_a_declared_inventory(published) -> None:
    bundle, run_root, _receipts, _ = published
    (bundle / "reports" / "note.json").write_bytes(b"\xff\xfe not text")
    report = _verify_no_crash(bundle, run_root)
    assert report["manifest"]["status"] == "sealed"
    assert report["verified"] is True


def test_an_unreadable_published_file_with_no_declared_inventory_is_malformed_not_an_exception(
    published, tmp_path
) -> None:
    _bundle, run_root, _receipts, _ = published
    bundle = _bundle_without_grain(tmp_path)
    (bundle / "reports" / "note.json").write_bytes(b"\xff\xfe not text")
    _seal_again(bundle)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False
    assert any("published receipt scan" in item for item in report["malformed_declarations"])


def test_an_unrelated_binary_receipt_file_under_the_run_root_is_ignored(published) -> None:
    bundle, run_root, _receipts, _ = published
    stray = run_root / "stray"
    stray.mkdir()
    (stray / "evaluation_receipt.json").write_bytes(b'{"a": "\xff"}')
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is True


def test_an_unreadable_declared_receipt_is_evidence_missing(published) -> None:
    bundle, run_root, receipts, attempt_dirs = published
    (attempt_dirs[1] / "evaluation_receipt.json").write_bytes(b'{"a": "\xff"}')
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False
    assert report["counts"] == {VERIFIED: 1, DIFFERS: 0, EVIDENCE_MISSING: 1}


@pytest.mark.parametrize("published_failure", ["provider_timeout", [{"condition": "x", "failure_class": "y"}], 0])
def test_a_non_mapping_published_failure_differs_from_a_receipt_without_one(published, tmp_path, published_failure) -> None:
    _bundle, run_root, receipts, attempt_dirs = published
    sealed = _sealed_receipts(attempt_dirs)
    assert not isinstance(sealed[0].get("failure"), dict)
    rows = [_production_projection(r) for r in sealed]
    assert rows[0]["failure"] is None
    rows[0]["failure"] = published_failure
    bundle = _sealed_projection_bundle(tmp_path, receipts, rows)
    report = _verify_no_crash(bundle, run_root)
    assert report["verified"] is False and report["counts"][DIFFERS] == 1


def test_an_unreadable_unsealed_addition_does_not_abort_a_valid_bundle(published) -> None:
    bundle, run_root, _receipts, _ = published
    note = bundle / "reports" / "unreadable_note.json"
    note.write_text("{}")
    note.chmod(0)
    try:
        report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    finally:
        note.chmod(0o644)
    assert report["verified"] is True
    assert "reports/unreadable_note.json" in report["manifest"]["unsealed_artifacts"]


@pytest.mark.parametrize("escape", ["../outside.json", "/etc/hosts", "reports/../../outside.json"])
def test_a_sealed_path_outside_the_bundle_is_tampered_and_never_read(published, escape) -> None:
    bundle, run_root, *_ = published
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest["artifacts"] = {**manifest["artifacts"], escape: "0" * 64}
    path.write_text(json.dumps(_sealed_manifest(manifest)))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    # Rejected as a malformed entry before any read, not as an altered file.
    assert "malformed" in report["manifest"]["reason"]
    assert report["manifest"]["altered_or_missing_artifacts"] == []
    assert report["verified"] is False


@pytest.mark.parametrize(
    "alias", ["./receipts/projections.jsonl", "receipts//projections.jsonl", "receipts/./projections.jsonl"]
)
def test_an_aliased_sealed_path_is_malformed(published, tmp_path, alias) -> None:
    """An alias would be hashed but never compared, letting a wrong projection pass."""

    _bundle, run_root, receipts, attempt_dirs = published
    rows = [_production_projection(r) for r in _sealed_receipts(attempt_dirs)]
    rows[0]["cell_id"] = "cell_wrong"
    bundle = _sealed_projection_bundle(tmp_path, receipts, rows)
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest["artifacts"][alias] = manifest["artifacts"].pop("receipts/projections.jsonl")
    path.write_text(json.dumps(_sealed_manifest(manifest)))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert "malformed" in report["manifest"]["reason"]
    assert report["verified"] is False


def test_a_sealed_path_through_a_symlinked_directory_is_never_read(published, tmp_path, monkeypatch) -> None:
    bundle, run_root, *_ = published
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "probe.json").write_text("{}")
    os.symlink(outside, bundle / "reports" / "link", target_is_directory=True)
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest["artifacts"]["reports/link/probe.json"] = hashlib.sha256(b"{}").hexdigest()
    path.write_text(json.dumps(_sealed_manifest(manifest)))
    read: list[Path] = []
    original = Path.read_bytes

    def recording(self):
        read.append(Path(self).resolve())
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", recording)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["verified"] is False
    assert not [p for p in read if outside.resolve() in p.parents]


def test_a_windows_drive_path_is_malformed(published) -> None:
    bundle, run_root, *_ = published
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest["artifacts"]["C:/outside.json"] = "0" * 64
    path.write_text(json.dumps(_sealed_manifest(manifest)))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert "malformed" in report["manifest"]["reason"]


def test_an_overlong_sealed_path_is_reported_not_raised(published) -> None:
    bundle, run_root, *_ = published
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest["artifacts"]["reports/" + "a" * 300 + ".json"] = "0" * 64
    path.write_text(json.dumps(_sealed_manifest(manifest)))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert report["verified"] is False


def test_a_symlinked_receipts_directory_is_never_read(published, tmp_path, monkeypatch) -> None:
    """A failed bundle is still not read through a symlink, by any reader."""

    bundle, run_root, receipts, attempt_dirs = published
    outside = tmp_path / "outside_receipts"
    outside.mkdir()
    row = _production_projection(_sealed_receipts(attempt_dirs)[0])
    (outside / "probe.jsonl").write_text(json.dumps(row) + "\n")
    os.symlink(outside, bundle / "receipts", target_is_directory=True)
    read: list[Path] = []
    original_bytes, original_text = Path.read_bytes, Path.read_text

    def recording_bytes(self):
        read.append(Path(self).resolve())
        return original_bytes(self)

    def recording_text(self, *args, **kwargs):
        read.append(Path(self).resolve())
        return original_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", recording_bytes)
    monkeypatch.setattr(Path, "read_text", recording_text)
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered" and report["verified"] is False
    assert not [p for p in read if outside.resolve() in p.parents]


def test_a_sealed_path_with_a_nul_character_is_malformed(published) -> None:
    bundle, run_root, *_ = published
    path = bundle / MANIFEST_FILENAME
    manifest = json.loads(path.read_bytes())
    manifest["artifacts"]["reports/bad\u0000.json"] = "0" * 64
    path.write_text(json.dumps(_sealed_manifest(manifest)))
    report = verify_bundle_replay(bundle, run_root, setup_for=setup_for)
    assert report["manifest"]["status"] == "tampered"
    assert "malformed" in report["manifest"]["reason"]
