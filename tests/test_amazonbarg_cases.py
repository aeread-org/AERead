"""Tests for the amazonbarg foundation stage: pins, importer, case records.

These tests exercise the real pinned upstream checkout on disk (read-only)
and, where a computed value is asserted, compare against upstream's own
governing facts (docs/amazonbarg_adapter_spec.md) or the kernel's own
resolver helpers -- never a value this test suite invents.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.amazonbarg import cases as amazonbarg_cases


def _upstream_root() -> Path:
    """The pinned upstream checkout path -- may not exist on disk.

    Unlike this function's pre-fix form, this never skips at import time
    (codex-review finding 6): a missing checkout is caught per-test by
    ``conftest.py``'s ``pytest_collection_modifyitems`` hook instead, which
    skips only the tests that actually need it -- tests marked
    ``@pytest.mark.no_upstream_checkout_required`` (verified independently to
    touch no upstream bytes) still run and pass even when this path does not
    exist.
    """
    candidate = os.environ.get(
        "AEREAD_AMAZONBARG_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg",
    )
    return Path(candidate)


UPSTREAM_ROOT = _upstream_root()

CASES_DIR = Path("cases/amazonbarg/pilot")


# ---------------------------------------------------------------------------
# Governing facts about the upstream corpus (spec "Governing facts").
# ---------------------------------------------------------------------------


def test_upstream_corpus_has_18_category_files_matching_the_pinned_list() -> None:
    corpus_dir = UPSTREAM_ROOT / "data" / "AmazonHistoryPrice"
    actual = sorted(p.name for p in corpus_dir.iterdir() if p.suffix == ".json")
    assert actual == list(amazonbarg_cases.CATEGORY_FILES)


def test_every_record_category_field_matches_its_own_filename_stem() -> None:
    for filename in amazonbarg_cases.CATEGORY_FILES:
        records = amazonbarg_cases.load_raw_category_records(UPSTREAM_ROOT, filename)
        stem = filename.removesuffix(".json")
        assert all(record.get("category") == stem for record in records)


def test_delegated_derivation_totals_930_sessions_886_mi_44_ci() -> None:
    products = amazonbarg_cases.load_all_derived_products(UPSTREAM_ROOT)
    assert len(products) == 930
    mutual = sum(1 for product in products if product.cost <= product.budget)
    conflicting = len(products) - mutual
    assert mutual == 886
    assert conflicting == 44


def test_pilot_pair_has_45_sessions_44_mi_1_ci_the_dji_drone() -> None:
    products = amazonbarg_cases.load_all_derived_products(UPSTREAM_ROOT)
    pilot_categories = {
        f.removesuffix(".json") for f in amazonbarg_cases.PILOT_CATEGORY_FILES
    }
    pilot_products = [p for p in products if p.category in pilot_categories]
    assert len(pilot_products) == 45
    conflicting = [p for p in pilot_products if p.cost > p.budget]
    assert [p.codename for p in conflicting] == ["toys-games_22"]
    (drone,) = conflicting
    assert drone.cost == pytest.approx(959.0)
    assert drone.budget == pytest.approx(864.928)


def test_max_turns_pin_matches_run_session_py_default_never_overridden() -> None:
    # Read, never executed: run_session.py:main's own `max_turns=6` default,
    # and neither run_2stages.sh nor run_3stages.sh overrides it.
    run_session = (UPSTREAM_ROOT / "run_session.py").read_text(encoding="utf-8")
    assert "max_turns=6" in run_session
    for script_name in ("run_2stages.sh", "run_3stages.sh"):
        script = (UPSTREAM_ROOT / script_name).read_text(encoding="utf-8")
        assert "max_turns" not in script
    assert amazonbarg_cases.MAX_TURNS == 6


# ---------------------------------------------------------------------------
# Sanitization round-trip (test plan P6).
# ---------------------------------------------------------------------------


def test_sanitize_is_the_identity_on_every_one_of_the_930_real_codenames() -> None:
    enumerated = amazonbarg_cases.enumerate_all_codenames(UPSTREAM_ROOT)
    assert len(enumerated) == 930
    mismatches = [
        entry["codename"]
        for entry in enumerated
        if amazonbarg_cases.sanitize(entry["codename"]) != entry["codename"]
    ]
    assert mismatches == []


@pytest.mark.no_upstream_checkout_required
@pytest.mark.parametrize(
    "raw",
    ["café_1", "a:b", "ABC_1", "home-kitchen_2", "toys-games_22", "已经_9"],
)
def test_sanitize_desanitize_round_trips_synthetic_counter_examples(raw: str) -> None:
    sanitized = amazonbarg_cases.sanitize(raw)
    assert amazonbarg_cases.desanitize(sanitized) == raw


@pytest.mark.no_upstream_checkout_required
def test_sanitize_escapes_a_colon_so_the_case_id_never_contains_one() -> None:
    sanitized = amazonbarg_cases.sanitize("a:b")
    assert ":" not in sanitized
    case_id = amazonbarg_cases.case_id_for_codename("a:b")
    assert ":" not in case_id
    # Round-trips through the strict identifier grammar cleanly.
    CaseManifest.from_dict(
        {
            "spec_version": CaseManifest.SPEC_VERSION,
            "case_id": case_id,
            "family_id": amazonbarg_cases.FAMILY_ID,
            "family_version": amazonbarg_cases.FAMILY_VERSION,
            "split": amazonbarg_cases.SPLIT,
            "world_seed": 0,
            "seats": [{"id": "buyer", "role": "buyer"}, {"id": "seller", "role": "seller"}],
            "episode": {"max_logical_actions": 1, "termination": ["deal"]},
            "visibility_policy": "x",
            "payload": {},
            "provenance": {
                "generator_id": "g",
                "generator_version": "0.1.0",
                "review_status": "upstream_pinned",
            },
            "content_sha256": "0" * 64,
        }
    )


@pytest.mark.no_upstream_checkout_required
def test_case_id_grammar_rejects_a_naive_colon_joined_codename() -> None:
    # A naive "family:codename" join (the obvious way to key a case by
    # upstream codename) is exactly what the kernel's identifier grammar
    # forbids (colons collapse GRPO groupings downstream); the importer
    # must mint a sanitized id instead, never this.
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": CaseManifest.SPEC_VERSION,
                "case_id": "amazonbarg.bilateral:home-kitchen_2",
                "family_id": amazonbarg_cases.FAMILY_ID,
                "family_version": amazonbarg_cases.FAMILY_VERSION,
                "split": amazonbarg_cases.SPLIT,
                "world_seed": 0,
                "seats": [{"id": "buyer", "role": "buyer"}, {"id": "seller", "role": "seller"}],
                "episode": {"max_logical_actions": 1, "termination": ["deal"]},
                "visibility_policy": "x",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "upstream_pinned",
                },
                "content_sha256": "0" * 64,
            }
        )


@pytest.mark.no_upstream_checkout_required
def test_sanitize_does_not_collide_a_real_colon_with_a_literal_escape_marker() -> None:
    """Codex-review finding 8: ``sanitize`` must be injective, not merely the
    identity on today's fixed 930-codename corpus.

    ``sanitize`` passes every character in ``[a-z0-9_.-]`` through unchanged
    and escapes everything else as ``_x{ord:04x}_`` -- but the literal
    characters ``_``, ``x``, and hex digits are themselves inside that
    passthrough set, so a codename that already happens to *contain* the
    literal marker text (e.g. ``"a_x003a_b"``) was previously left
    untouched and became indistinguishable from the escaped form of
    ``"a:b"`` (both produced ``"a_x003a_b"``) -- a real ``case_id``
    collision between two distinct real codenames, exactly the property
    ``sanitize``'s own docstring claims ("produce a safe, unique id") but
    did not meet."""
    colon_form = "a:b"
    lookalike_form = "a_x003a_b"  # already looks like the escaped form of colon_form
    assert colon_form != lookalike_form

    sanitized_colon = amazonbarg_cases.sanitize(colon_form)
    sanitized_lookalike = amazonbarg_cases.sanitize(lookalike_form)

    assert sanitized_colon != sanitized_lookalike
    assert amazonbarg_cases.desanitize(sanitized_colon) == colon_form
    assert amazonbarg_cases.desanitize(sanitized_lookalike) == lookalike_form
    assert (
        amazonbarg_cases.case_id_for_codename(colon_form)
        != amazonbarg_cases.case_id_for_codename(lookalike_form)
    )


# ---------------------------------------------------------------------------
# pins.json
# ---------------------------------------------------------------------------


def test_build_pins_facts() -> None:
    pins = amazonbarg_cases.build_pins(UPSTREAM_ROOT)

    assert pins["upstream_repo"] == "TianXiaSJTU/AmazonPriceHistory"
    assert pins["upstream_commit"] == "834ad9066d0627f0332504d5fa6d236706f2402b"
    assert pins["license"] == "Apache-2.0"
    assert pins["budget_ratio"] == 0.8
    assert pins["max_turns"] == 6
    assert pins["total_records"] == 930
    assert pins["total_mutual_interest"] == 886
    assert pins["total_conflicting_interest"] == 44
    assert pins["pilot_category_files"] == ["home-kitchen.json", "toys-games.json"]
    assert len(pins["category_files"]) == 18
    assert [entry["file"] for entry in pins["category_files"]] == list(
        amazonbarg_cases.CATEGORY_FILES
    )
    for entry in pins["category_files"]:
        assert isinstance(entry["sha256"], str) and len(entry["sha256"]) == 64
        int(entry["sha256"], 16)
        assert entry["bytes"] > 0
        assert entry["record_count"] > 0
        assert entry["category"] == entry["file"].removesuffix(".json")

    home_kitchen = next(e for e in pins["category_files"] if e["category"] == "home-kitchen")
    assert home_kitchen["record_count"] == 23
    toys_games = next(e for e in pins["category_files"] if e["category"] == "toys-games")
    assert toys_games["record_count"] == 22


def test_build_pins_file_hashes_match_a_direct_read() -> None:
    import hashlib

    pins = amazonbarg_cases.build_pins(UPSTREAM_ROOT)
    corpus_dir = UPSTREAM_ROOT / "data" / "AmazonHistoryPrice"
    for entry in pins["category_files"]:
        data = (corpus_dir / entry["file"]).read_bytes()
        assert entry["bytes"] == len(data)
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Case records (spec sections 1.2, 3).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pilot_cases() -> dict[str, dict]:
    return amazonbarg_cases.import_pilot_cases(UPSTREAM_ROOT)


def test_import_pilot_cases_materializes_exactly_45_sessions(pilot_cases) -> None:
    assert len(pilot_cases) == 45
    categories = {case["payload"]["derived"]["category"] for case in pilot_cases.values()}
    assert categories == {"home-kitchen", "toys-games"}


def test_case_identity_fields_for_the_five_golden_sessions(pilot_cases) -> None:
    golden_codenames = (
        "home-kitchen_2",
        "home-kitchen_3",
        "home-kitchen_4",
        "home-kitchen_5",
        "toys-games_22",
    )
    for codename in golden_codenames:
        case_id = amazonbarg_cases.case_id_for_codename(codename)
        case = pilot_cases[case_id]
        assert case["case_id"] == case_id
        assert case["family_id"] == "amazonbarg.bilateral"
        assert case["family_version"] == "0.1.0"
        assert case["split"] == "pilot"
        assert case["upstream_task_id"] == codename
        assert case["payload"]["derived"]["codename"] == codename
        assert case["provenance"] == {
            "generator_id": "amazonbarg_importer",
            "generator_version": "0.1.0",
            "review_status": "upstream_pinned",
        }
        seat_ids = {seat["id"] for seat in case["seats"]}
        assert seat_ids == {"buyer", "seller"}
        assert case["episode"]["max_logical_actions"] == 12
        assert set(case["episode"]["termination"]) == {
            "deal",
            "quit",
            "action_error",
            "turn_limit",
        }


def test_golden_1_shark_vacuum_cost_and_budget(pilot_cases) -> None:
    case = pilot_cases[amazonbarg_cases.case_id_for_codename("home-kitchen_2")]
    derived = case["payload"]["derived"]
    assert derived["cost"] == pytest.approx(95.00)
    assert derived["budget"] == pytest.approx(173.44)
    assert derived["interest"] == "mutual"


def test_golden_2_calphalon_cost_and_budget(pilot_cases) -> None:
    case = pilot_cases[amazonbarg_cases.case_id_for_codename("home-kitchen_3")]
    derived = case["payload"]["derived"]
    assert derived["cost"] == pytest.approx(60.99)
    assert derived["budget"] == pytest.approx(103.99, abs=0.01)
    assert derived["interest"] == "mutual"


def test_golden_3_breville_cost_and_budget(pilot_cases) -> None:
    case = pilot_cases[amazonbarg_cases.case_id_for_codename("home-kitchen_5")]
    derived = case["payload"]["derived"]
    assert derived["cost"] == pytest.approx(524.97)
    assert derived["budget"] == pytest.approx(599.96)
    assert derived["interest"] == "mutual"


def test_golden_5_dji_drone_is_the_pilots_one_conflicting_interest_session(pilot_cases) -> None:
    case = pilot_cases[amazonbarg_cases.case_id_for_codename("toys-games_22")]
    derived = case["payload"]["derived"]
    assert derived["cost"] == pytest.approx(959.00)
    assert derived["budget"] == pytest.approx(864.93, abs=0.01)
    assert derived["interest"] == "conflicting"
    assert "drone" in derived["title"].lower() or "dji" in derived["title"].lower()


def test_payload_product_is_the_verbatim_pinned_category_file_record(pilot_cases) -> None:
    case = pilot_cases[amazonbarg_cases.case_id_for_codename("home-kitchen_2")]
    raw_records = amazonbarg_cases.load_raw_category_records(UPSTREAM_ROOT, "home-kitchen.json")
    assert case["payload"]["product"] == raw_records[1]


def test_case_record_round_trips_through_the_strict_r1_grammar(pilot_cases) -> None:
    for case in pilot_cases.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(pilot_cases) -> None:
    case = pilot_cases[amazonbarg_cases.case_id_for_codename("home-kitchen_2")]
    assert case_content_sha256(case) == case["content_sha256"]

    mutated = copy.deepcopy(case)
    mutated["payload"]["derived"]["title"] = "mutated"
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_world_seeds_are_unique_and_reflect_full_corpus_position(pilot_cases) -> None:
    seeds = [case["world_seed"] for case in pilot_cases.values()]
    assert len(seeds) == len(set(seeds))
    assert all(0 <= seed < 930 for seed in seeds)


# ---------------------------------------------------------------------------
# Pilot manifest.
# ---------------------------------------------------------------------------


def test_build_pilot_manifest_has_45_ids_in_corpus_order(pilot_cases) -> None:
    manifest = amazonbarg_cases.build_pilot_manifest(pilot_cases)

    assert manifest["pilot_id"] == "amazonbarg_pilot_v1"
    assert manifest["family_id"] == "amazonbarg.bilateral"
    assert manifest["split"] == "pilot"
    assert len(manifest["case_ids"]) == 45
    assert len(set(manifest["case_ids"])) == 45
    assert manifest["case_ids"][0] == amazonbarg_cases.case_id_for_codename("home-kitchen_1")
    assert manifest["case_ids"][22] == amazonbarg_cases.case_id_for_codename("home-kitchen_23")
    assert manifest["case_ids"][23] == amazonbarg_cases.case_id_for_codename("toys-games_1")
    assert manifest["case_ids"][-1] == amazonbarg_cases.case_id_for_codename("toys-games_22")
    assert len(manifest["content_sha256"]) == 64
    int(manifest["content_sha256"], 16)


def test_pilot_manifest_hash_changes_if_the_id_list_changes(pilot_cases) -> None:
    manifest = amazonbarg_cases.build_pilot_manifest(pilot_cases)
    mutated = dict(manifest)
    mutated["case_ids"] = list(manifest["case_ids"][:-1]) + [
        amazonbarg_cases.case_id_for_codename("home-kitchen_1")
    ]
    mutated_digest = amazonbarg_cases._pilot_content_sha256(mutated)
    assert mutated_digest != manifest["content_sha256"]


@pytest.mark.no_upstream_checkout_required
def test_build_pilot_manifest_raises_when_case_count_is_not_45() -> None:
    with pytest.raises(ValueError, match="expected 45 cases"):
        amazonbarg_cases.build_pilot_manifest({})


@pytest.mark.no_upstream_checkout_required
def test_pilot_manifest_digest_is_independent_of_insertion_order() -> None:
    """Codex-review finding 9: the digest represents pilot *membership* (a
    set of 45 case_ids), so two callers assembling the identical set in a
    different sequence must get the identical digest for what is the same
    content -- ``case_ids`` (an incidental total order) must not leak into
    ``content_sha256`` even though the manifest's own ``case_ids`` field
    keeps reporting whichever order its caller actually built."""
    case_ids = [amazonbarg_cases.case_id_for_codename(f"home-kitchen_{i}") for i in range(1, 24)]
    case_ids += [amazonbarg_cases.case_id_for_codename(f"toys-games_{i}") for i in range(1, 23)]
    assert len(case_ids) == 45

    forward_cases = {case_id: {} for case_id in case_ids}
    reversed_cases = {case_id: {} for case_id in reversed(case_ids)}
    assert list(forward_cases) != list(reversed_cases)  # same set, different order

    forward_manifest = amazonbarg_cases.build_pilot_manifest(forward_cases)
    reversed_manifest = amazonbarg_cases.build_pilot_manifest(reversed_cases)

    assert set(forward_manifest["case_ids"]) == set(reversed_manifest["case_ids"])
    assert forward_manifest["content_sha256"] == reversed_manifest["content_sha256"]
    # The manifest's own case_ids field is untouched -- still whichever
    # order its caller actually built, never silently re-sorted.
    assert forward_manifest["case_ids"] == case_ids
    assert reversed_manifest["case_ids"] == list(reversed(case_ids))


# ---------------------------------------------------------------------------
# P1 -- import/digest determinism: two importer runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    amazonbarg_cases.run_import(UPSTREAM_ROOT, out_a)
    amazonbarg_cases.run_import(UPSTREAM_ROOT, out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 45 case files + pins.json + pilot_manifest.json
    assert len(files_a) == 47

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_45_case_files_plus_pins_and_pilot(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    amazonbarg_cases.run_import(UPSTREAM_ROOT, out_dir)

    case_files = sorted(out_dir.glob("amazonbarg.bilateral.*.json"))
    # Excludes pilot_manifest.json (does not match the case_id prefix glob
    # since it lacks the trailing per-codename segment... guard explicitly.)
    case_files = [p for p in case_files if p.name != "pilot_manifest.json"]
    assert len(case_files) == 45

    pins = json.loads((out_dir / "pins.json").read_text(encoding="utf-8"))
    assert pins["total_records"] == 930

    pilot = json.loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert len(pilot["case_ids"]) == 45


# ---------------------------------------------------------------------------
# The checked-in cases/amazonbarg/pilot/ directory matches a fresh import.
# ---------------------------------------------------------------------------


def test_checked_in_case_directory_matches_a_fresh_import(tmp_path: Path) -> None:
    if not (CASES_DIR / "pins.json").is_file():
        pytest.skip(f"checked-in case directory not found at {CASES_DIR}")

    fresh_dir = tmp_path / "fresh"
    amazonbarg_cases.run_import(UPSTREAM_ROOT, fresh_dir)

    checked_in_files = sorted(p.name for p in CASES_DIR.glob("*.json"))
    fresh_files = sorted(p.name for p in fresh_dir.glob("*.json"))
    assert checked_in_files == fresh_files

    for name in checked_in_files:
        checked_in_bytes = (CASES_DIR / name).read_bytes()
        fresh_bytes = (fresh_dir / name).read_bytes()
        assert checked_in_bytes == fresh_bytes, f"{name} differs from a fresh import"
