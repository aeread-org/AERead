from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from aeread.shared_runner.analysis.errata import (
    Erratum,
    ErrataContractError,
    build_register,
    errata_for,
    load_errata,
    main,
    plans_sealed_under,
    publish_register,
    write_erratum,
)
from aeread.shared_runner.run.contract import read_sealed
from aeread.shared_runner.run.resolver import canonical_json_bytes

PLAN_A = "a" * 64
PLAN_B = "b" * 64
RECEIPT_1 = "1" * 64
PIN_OLD = "c" * 64
PIN_NEW = "d" * 64


def _erratum(**overrides) -> dict:
    base = {
        "errata_id": "ERR-2026-09-06-001",
        "opened_at": "2026-09-06",
        "category": "kernel",
        "effect": "cost_lower_bound",
        "title": "Multi-round turns were costed only on their final round",
        "description": "Every round before the reply was billed but never charged.",
        "selectors": {
            "campaign_ids": ["camp_v9"],
            "run_plan_sha256s": [PLAN_A],
            "receipt_sha256s": [],
            "implementation_pins": [
                {"component_id": "minimal_chat", "sha256s": [PIN_OLD]}
            ],
            "family_ids": [],
        },
        "fix_ref": "#101 (d89da44)",
        "disposition": "open",
        "superseded_by": None,
        "evidence_refs": ["https://github.com/aeread-org/AERead/pull/101"],
    }
    base.update(overrides)
    return base


# --- record contract ---


def test_erratum_round_trips_and_requires_a_selector() -> None:
    erratum = Erratum.from_dict(_erratum())
    assert Erratum.from_dict(erratum.to_dict()) == erratum
    assert erratum.selectors.implementation_pins[0].component_id == "minimal_chat"

    empty = _erratum(
        selectors={
            "campaign_ids": [],
            "run_plan_sha256s": [],
            "receipt_sha256s": [],
            "implementation_pins": [],
            "family_ids": [],
        }
    )
    with pytest.raises(ErrataContractError, match="at least one selector"):
        Erratum.from_dict(empty)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("errata_id", "ERR-1", "errata_id"),
        ("category", "vibes", "category"),
        ("effect", "bad", "effect"),
        ("disposition", "closed", "disposition"),
        ("opened_at", "yesterday", "opened_at"),
        ("title", "", "title"),
    ],
)
def test_erratum_rejects_malformed_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(ErrataContractError, match=message):
        Erratum.from_dict(_erratum(**{field: value}))


def test_superseded_erratum_must_name_its_successor() -> None:
    with pytest.raises(ErrataContractError, match="superseded_by"):
        Erratum.from_dict(_erratum(disposition="superseded"))
    Erratum.from_dict(
        _erratum(disposition="superseded", superseded_by="ERR-2026-09-07-001")
    )


# --- append-only storage ---


def test_write_erratum_seals_and_load_verifies_digests(tmp_path: Path) -> None:
    root = tmp_path / "errata"
    erratum = Erratum.from_dict(_erratum())
    path = write_erratum(root, erratum)
    assert path == root / "ERR-2026-09-06-001.json"
    stored = read_sealed(path)
    assert stored["errata_id"] == "ERR-2026-09-06-001"
    assert stored["schema_version"] == "aeread.erratum/0.1"

    # Identical rewrite is a no-op; a different record under the same id is refused.
    write_erratum(root, erratum)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        write_erratum(root, Erratum.from_dict(_erratum(title="edited")))

    (loaded,) = load_errata(root)
    assert loaded == erratum

    tampered = dict(stored)
    tampered["title"] = "tampered"
    path.write_bytes(canonical_json_bytes(tampered) + b"\n")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        load_errata(root)


def test_load_errata_rejects_duplicate_ids_and_misnamed_files(tmp_path: Path) -> None:
    root = tmp_path / "errata"
    write_erratum(root, Erratum.from_dict(_erratum()))
    misnamed = root / "ERR-2026-09-06-002.json"
    misnamed.write_bytes((root / "ERR-2026-09-06-001.json").read_bytes())
    with pytest.raises(ErrataContractError, match="file name"):
        load_errata(root)


def test_load_errata_on_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert load_errata(tmp_path / "nowhere") == ()


# --- matching ---


def test_errata_for_matches_any_selector_and_skips_superseded() -> None:
    open_one = Erratum.from_dict(_erratum())
    superseded = Erratum.from_dict(
        _erratum(
            errata_id="ERR-2026-09-06-002",
            disposition="superseded",
            superseded_by="ERR-2026-09-06-001",
            selectors={
                "campaign_ids": ["camp_v9"],
                "run_plan_sha256s": [],
                "receipt_sha256s": [],
                "implementation_pins": [],
                "family_ids": [],
            },
        )
    )
    errata = (open_one, superseded)
    assert errata_for(errata, campaign_id="camp_v9") == ("ERR-2026-09-06-001",)
    assert errata_for(errata, run_plan_sha256=PLAN_A) == ("ERR-2026-09-06-001",)
    assert errata_for(errata, run_plan_sha256=PLAN_B) == ()
    assert errata_for(errata, receipt_sha256=RECEIPT_1) == ()
    pins = ({"component_id": "minimal_chat", "kind": "harness", "version": "1.0", "sha256": PIN_OLD},)
    assert errata_for(errata, implementation_pins=pins) == ("ERR-2026-09-06-001",)
    new_pins = ({"component_id": "minimal_chat", "kind": "harness", "version": "1.0", "sha256": PIN_NEW},)
    assert errata_for(errata, implementation_pins=new_pins) == ()
    assert errata_for(errata, campaign_id="camp_v9", include_superseded=True) == (
        "ERR-2026-09-06-001",
        "ERR-2026-09-06-002",
    )


def test_plans_sealed_under_resolves_pins_from_local_receipts(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    for name, plan, sha in (("old", PLAN_A, PIN_OLD), ("new", PLAN_B, PIN_NEW)):
        receipt = runs / name / "tasks" / "cell" / "attempts" / "a0" / "evaluation_receipt.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(
            json.dumps(
                {
                    "run_plan_sha256": plan,
                    "plan_implementation_pins": [
                        {"component_id": "minimal_chat", "kind": "harness", "version": "1.0", "sha256": sha},
                        {"component_id": "scorer", "kind": "scorer", "version": "1.0.0", "sha256": "e" * 64},
                    ],
                }
            )
        )
    assert plans_sealed_under(runs, "minimal_chat", (PIN_OLD,)) == (PLAN_A,)
    assert plans_sealed_under(runs, "minimal_chat", (PIN_OLD, PIN_NEW)) == (PLAN_A, PLAN_B)
    assert plans_sealed_under(runs, "scorer", (PIN_OLD,)) == ()


# --- derived register over published evidence ---


def _bundle(evidence: Path, campaign_id: str, *, plan: str | None, receipts: tuple[str, ...] = ()) -> Path:
    root = evidence / campaign_id
    root.mkdir(parents=True)
    manifest = {"campaign_id": campaign_id, "schema_version": "x/0.1"}
    if plan is not None:
        manifest["plan_sha256"] = plan
    (root / "publication_manifest.json").write_text(json.dumps(manifest))
    (root / "README.md").write_text(f"# {campaign_id}\n")
    if receipts:
        (root / "receipts").mkdir()
        lines = [
            json.dumps({"run_plan_sha256": plan or PLAN_B, "source_receipt_sha256": sha})
            for sha in receipts
        ]
        (root / "receipts" / "projections.jsonl").write_text("\n".join(lines) + "\n")
    return root


def test_register_lists_affected_bundles_by_selector_and_is_reproducible(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _bundle(evidence, "camp_v9", plan=PLAN_A, receipts=(RECEIPT_1,))
    _bundle(evidence, "camp_v10", plan=PLAN_B, receipts=("2" * 64,))
    _bundle(evidence, "other_family_v1", plan=None)
    errata = (
        Erratum.from_dict(_erratum()),
        Erratum.from_dict(
            _erratum(
                errata_id="ERR-2026-09-06-002",
                effect="route_unverified",
                selectors={
                    "campaign_ids": [],
                    "run_plan_sha256s": [],
                    "receipt_sha256s": ["2" * 64],
                    "implementation_pins": [],
                    "family_ids": [],
                },
            )
        ),
    )

    first_csv, first_summary = build_register(evidence, errata)
    second_csv, second_summary = build_register(evidence, errata)
    assert first_csv == second_csv and first_summary == second_summary

    rows = list(csv.DictReader(io.StringIO(first_csv.decode("utf-8"))))
    assert [(r["errata_id"], r["campaign_id"], r["matched_by"]) for r in rows] == [
        ("ERR-2026-09-06-001", "camp_v9", "campaign_id,run_plan_sha256"),
        ("ERR-2026-09-06-002", "camp_v10", "receipt_sha256"),
    ]
    assert rows[0]["effect"] == "cost_lower_bound" and rows[0]["disposition"] == "open"
    assert first_summary["affected_bundle_count"] == 2
    assert first_summary["errata_count"] == 2
    assert first_summary["by_effect"] == {"cost_lower_bound": 1, "route_unverified": 1}
    assert first_summary["rows_sha256"] == hashlib.sha256(first_csv).hexdigest()
    assert first_summary["schema_version"] == "aeread.errata_register/0.1"
    assert first_summary["source_truth"] == ["evidence/errata", "publication_manifest.json", "receipts/projections.jsonl"]


def test_publish_register_writes_tables_summary_and_sidecar_notes(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    affected = _bundle(evidence, "camp_v9", plan=PLAN_A)
    clean = _bundle(evidence, "camp_v10", plan=PLAN_B)
    errata_root = evidence / "errata"
    write_erratum(errata_root, Erratum.from_dict(_erratum()))

    summary = publish_register(evidence, errata_root=errata_root, register_root=evidence / "errata_register", write_notes=True)
    register = evidence / "errata_register"
    assert (register / "tables" / "affected.csv").is_file()
    assert read_sealed(register / "reports" / "summary.json")["affected_bundle_count"] == 1
    assert summary["affected_bundle_count"] == 1

    note = (affected / "ERRATA.md").read_text()
    assert "ERR-2026-09-06-001" in note and "cost_lower_bound" in note and "#101" in note
    assert "publication_manifest.json" not in note.split("\n")[0]
    assert not (clean / "ERRATA.md").exists()
    # The sealed manifest is untouched by the sidecar.
    assert json.loads((affected / "publication_manifest.json").read_text())["campaign_id"] == "camp_v9"

    again = publish_register(evidence, errata_root=errata_root, register_root=register, write_notes=True)
    assert again == summary
    assert (affected / "ERRATA.md").read_text() == note


def test_cli_publishes_register_and_reports_counts(tmp_path: Path, capsys) -> None:
    evidence = tmp_path / "evidence"
    _bundle(evidence, "camp_v9", plan=PLAN_A)
    write_erratum(evidence / "errata", Erratum.from_dict(_erratum()))
    code = main(
        [
            "--evidence-root", str(evidence),
            "--errata-root", str(evidence / "errata"),
            "--register-root", str(evidence / "errata_register"),
            "--write-notes",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["affected_bundle_count"] == 1 and out["errata_count"] == 1
