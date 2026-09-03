"""Tests for the aucarena foundation stage: item pool pin, scenario authoring,
case records (spec section 1: QC Gate 1 -- pinned source, corpus
enumeration, content digest).

These tests exercise the real pinned upstream checkout on disk (read-only,
never executed -- only its ``data/pseudo_items.jsonl`` data file is ever
read) and, where a computed value is asserted, compare against the
governing facts in ``docs/aucarena_adapter_spec.md`` or against the
kernel's own resolver helpers -- never against a value this test suite
invents.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.aucarena import cases as ac_cases


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_AUCARENA_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-aucarena",
    )
    root = Path(candidate)
    marker = root / "data" / "pseudo_items.jsonl"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream auction-arena checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent. Without this flag pytest treats a
            # module-level skip as an error and the whole file fails to
            # collect. This collapses all 19 tests below into one silent
            # "1 skipped" line with zero further signal -- set
            # $AEREAD_AUCARENA_QC_GATE_REQUIRED=1 (conftest.py's
            # pytest_terminal_summary) to turn that into a failed run
            # instead (docs/aucarena_codex_triage.md Finding 8).
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()


# ---------------------------------------------------------------------------
# Governing facts about the upstream item pool (spec section 1).
# ---------------------------------------------------------------------------


def test_item_pool_file_matches_the_pinned_sha256_and_count() -> None:
    path = UPSTREAM_ROOT / "data" / "pseudo_items.jsonl"
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ac_cases.ITEM_POOL_SHA256
    lines = [line for line in data.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == ac_cases.ITEM_POOL_COUNT == 26


def test_load_item_pool_resolves_every_id_1_through_26() -> None:
    pool = ac_cases.load_item_pool(UPSTREAM_ROOT)
    assert set(pool) == set(range(1, 27))
    for item_id, item in pool.items():
        assert item["id"] == item_id
        assert isinstance(item["name"], str) and item["name"]
        assert isinstance(item["price"], int) and item["price"] > 0
        assert isinstance(item["true_value"], int) and item["true_value"] >= item["price"]


def test_item_5_is_equipment_e_price_5000_matching_golden_5() -> None:
    # Governing fact this adapter's golden 5 depends on (spec section 5).
    pool = ac_cases.load_item_pool(UPSTREAM_ROOT)
    assert pool[5]["name"] == "Equipment E"
    assert pool[5]["price"] == 5000


def test_items_1_through_4_are_the_shared_1000_2000_widgets() -> None:
    pool = ac_cases.load_item_pool(UPSTREAM_ROOT)
    for item_id, name in ((1, "Widget A"), (2, "Gadget B"), (3, "Thingamajig C"), (4, "Doodad D")):
        assert pool[item_id]["name"] == name
        assert pool[item_id]["price"] == 1000
        assert pool[item_id]["true_value"] == 2000


def test_load_item_pool_rejects_a_tampered_file(tmp_path: Path) -> None:
    tampered_root = tmp_path / "upstream"
    (tampered_root / "data").mkdir(parents=True)
    (tampered_root / "data" / "pseudo_items.jsonl").write_text(
        '{"name": "Fake", "price": 1, "desc": "x", "id": 1, "true_value": 1}\n',
        encoding="utf-8",
    )
    with pytest.raises(ac_cases.ItemPoolPinMismatchError, match="sha256"):
        ac_cases.load_item_pool(tampered_root)


# ---------------------------------------------------------------------------
# Scenario records (spec section 1 and section 5).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def imported() -> dict[str, dict]:
    return ac_cases.import_all_cases(UPSTREAM_ROOT)


def test_five_goldens_produce_five_uniquely_named_cases(imported) -> None:
    assert len(imported) == 5
    assert set(imported) == {
        "aucarena.pilot.successful_01",
        "aucarena.pilot.valid_but_poor_01",
        "aucarena.pilot.invalid_unauthorized_01",
        "aucarena.pilot.malformed_operational_01",
        "aucarena.pilot.degenerate_reference_01",
    }


def test_case_identity_fields_for_every_golden(imported) -> None:
    for case_id, case in imported.items():
        assert case["case_id"] == case_id
        assert case["family_id"] == "aucarena"
        assert case["family_version"] == "0.1.0"
        assert case["split"] == "pilot"
        assert case["upstream_task_id"] is None
        assert tuple(case["episode"]["termination"]) == ("auction_complete",)
        assert case["provenance"] == {
            "generator_id": "aucarena_importer",
            "generator_version": "0.1.0",
            "review_status": "curated",
        }


def test_shared_roster_goldens_have_the_three_seat_roster(imported) -> None:
    for case_id in (
        "aucarena.pilot.successful_01",
        "aucarena.pilot.valid_but_poor_01",
        "aucarena.pilot.invalid_unauthorized_01",
        "aucarena.pilot.malformed_operational_01",
    ):
        case = imported[case_id]
        seat_ids = {seat["id"] for seat in case["seats"]}
        assert seat_ids == {"agent", "field_low", "field_high"}
        roster_by_seat = {seat["seat_id"]: seat for seat in case["payload"]["roster"]}
        assert roster_by_seat["field_low"]["model_name"] == "rule"
        assert roster_by_seat["field_low"]["max_bid_cnt"] == 0
        assert roster_by_seat["field_high"]["model_name"] == "rule"
        assert roster_by_seat["field_high"]["budget"] == 9000
        assert roster_by_seat["agent"]["model_name"] == "scripted"
        assert case["payload"]["min_markup_pct"] == 0.1
        assert case["payload"]["enable_discount"] is False


def test_golden_1_and_2_reference_items_1_through_4(imported) -> None:
    for case_id in ("aucarena.pilot.successful_01", "aucarena.pilot.valid_but_poor_01"):
        assert imported[case_id]["payload"]["item_ids"] == [1, 2, 3, 4]


def test_golden_3_and_4_reference_item_1_only(imported) -> None:
    for case_id in (
        "aucarena.pilot.invalid_unauthorized_01",
        "aucarena.pilot.malformed_operational_01",
    ):
        assert imported[case_id]["payload"]["item_ids"] == [1]


def test_golden_5_is_a_single_seat_single_item_degenerate_scenario(imported) -> None:
    case = imported["aucarena.pilot.degenerate_reference_01"]
    assert [seat["id"] for seat in case["seats"]] == ["agent"]
    assert case["payload"]["item_ids"] == [5]
    assert case["payload"]["items"][0]["name"] == "Equipment E"


def test_every_referenced_item_id_resolves_against_the_pinned_pool(imported) -> None:
    pool = ac_cases.load_item_pool(UPSTREAM_ROOT)
    for case in imported.values():
        for item_id, item in zip(case["payload"]["item_ids"], case["payload"]["items"]):
            assert item == pool[item_id]


def test_case_record_round_trips_through_the_strict_r1_grammar(imported) -> None:
    for case in imported.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(imported) -> None:
    case = imported["aucarena.pilot.successful_01"]
    assert case_content_sha256(case) == case["content_sha256"]

    # Mutating any part of the payload must change the digest -- guards
    # against a resolver/importer canonicalization bug silently accepting a
    # stale hash.
    mutated = copy.deepcopy(case)
    mutated["payload"]["roster"][0]["budget"] += 1
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_build_case_rejects_an_item_id_outside_the_pinned_pool() -> None:
    pool = ac_cases.load_item_pool(UPSTREAM_ROOT)
    bogus = ac_cases.GoldenScenario(
        golden_name="bogus",
        item_ids=(9999,),
        roster=(ac_cases.RosterSeat(seat_id="agent", model_name="scripted", budget=100, max_bid_cnt=1),),
        world_seed=1,
    )
    with pytest.raises(ValueError, match="not in the pinned pool"):
        ac_cases.build_case(bogus, pool)


def test_case_id_grammar_rejects_a_naive_colon_joined_id() -> None:
    # A naive "family:golden_name" join is exactly what the kernel's
    # identifier grammar forbids (a colon once collapsed GRPO grouping
    # downstream); the importer must mint "aucarena.pilot.successful_01"
    # instead, never this.
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "aucarena:pilot:successful_01",
                "family_id": "aucarena",
                "family_version": "0.1.0",
                "split": "pilot",
                "world_seed": 1,
                "seats": [{"id": "agent", "role": "bidder"}],
                "episode": {"max_logical_actions": 1, "termination": ["auction_complete"]},
                "visibility_policy": "x",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "curated",
                },
                "content_sha256": "0" * 64,
            }
        )


# ---------------------------------------------------------------------------
# P1 -- import determinism: two importer runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    ac_cases.run_import(UPSTREAM_ROOT, out_a)
    ac_cases.run_import(UPSTREAM_ROOT, out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 5 case files + provenance.json
    assert len(files_a) == 6

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_5_case_files_plus_provenance(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    ac_cases.run_import(UPSTREAM_ROOT, out_dir)

    case_files = sorted(out_dir.glob("aucarena.pilot.*.json"))
    assert len(case_files) == 5

    provenance = json.loads((out_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["item_pool_sha256"] == ac_cases.ITEM_POOL_SHA256
    assert provenance["upstream_commit"] == ac_cases.UPSTREAM_COMMIT
    assert len(provenance["case_ids"]) == 5


def test_checked_in_case_files_match_a_fresh_import(tmp_path: Path) -> None:
    """The committed cases/aucarena/pilot/*.json must not drift from the
    importer -- a stale checked-in case file would silently diverge from
    what `cases.py` actually produces."""
    checked_in_dir = Path("cases/aucarena/pilot")
    fresh_dir = tmp_path / "fresh"
    ac_cases.run_import(UPSTREAM_ROOT, fresh_dir)

    checked_in_files = sorted(p.name for p in checked_in_dir.glob("*.json"))
    fresh_files = sorted(p.name for p in fresh_dir.glob("*.json"))
    assert checked_in_files == fresh_files
    for name in checked_in_files:
        assert (checked_in_dir / name).read_bytes() == (fresh_dir / name).read_bytes(), name
