"""Tests for the alympics.wac foundation stage: authored grid, case records.

Unlike ``tau3.retail`` (which imports an upstream task bank verbatim), this
family authors its own 7-cell parameter grid (no upstream corpus exists to
import -- see ``cases.py``'s module docstring). These tests verify the
importer's determinism, the R1 grammar, and the digest computation against
the kernel's own resolver helper -- never against a value this test suite
invents for itself.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from aeread.shared_runner.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.alympics_wac import cases as wac_cases


# ---------------------------------------------------------------------------
# Governing facts about the upstream persona table (spec "Governing facts").
# ---------------------------------------------------------------------------


def test_persona_table_matches_upstream_hardcoded_roster() -> None:
    assert wac_cases.SEAT_ORDER == ("alex", "bob", "cindy", "david", "eric")
    assert wac_cases.PERSONAS == {
        "alex": {"upstream_name": "Alex", "requirement": 8, "daily_salary": 70},
        "bob": {"upstream_name": "Bob", "requirement": 9, "daily_salary": 75},
        "cindy": {"upstream_name": "Cindy", "requirement": 10, "daily_salary": 100},
        "david": {"upstream_name": "David", "requirement": 11, "daily_salary": 120},
        "eric": {"upstream_name": "Eric", "requirement": 12, "daily_salary": 120},
    }


def test_starting_state_matches_upstream_myplayer_defaults() -> None:
    assert wac_cases.STARTING_BALANCE == 0
    assert wac_cases.STARTING_HP == 8
    assert wac_cases.STARTING_NO_DRINK == 1
    assert wac_cases.MAXIMUM_HEALTH == 10


# ---------------------------------------------------------------------------
# Supply-schedule generation.
# ---------------------------------------------------------------------------


def test_generate_supply_schedule_uniform_matches_a_fresh_random_state() -> None:
    regime = {"kind": "uniform", "lower": 10, "upper": 20, "supply_schedule_seed": 7}
    schedule = wac_cases.generate_supply_schedule(regime, rounds=5)
    expected = [
        int(value) for value in np.random.RandomState(7).randint(10, 20, size=5)
    ]
    assert schedule == expected
    assert all(10 <= value < 20 for value in schedule)


def test_generate_supply_schedule_is_reproducible_for_the_same_seed() -> None:
    regime = {"kind": "uniform", "lower": 3, "upper": 8, "supply_schedule_seed": 0}
    first = wac_cases.generate_supply_schedule(regime, rounds=10)
    second = wac_cases.generate_supply_schedule(regime, rounds=10)
    assert first == second


def test_generate_supply_schedule_constant_needs_no_seed() -> None:
    schedule = wac_cases.generate_supply_schedule({"kind": "constant", "value": 0}, rounds=20)
    assert schedule == [0] * 20


def test_generate_supply_schedule_rejects_unknown_kind() -> None:
    with pytest.raises(wac_cases.GridValidationError):
        wac_cases.generate_supply_schedule({"kind": "bogus"}, rounds=1)


# ---------------------------------------------------------------------------
# Grid / case records (spec section 1's 7-row table).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built() -> dict[str, dict]:
    return wac_cases.build_all_cases()


def test_grid_has_exactly_7_cells() -> None:
    assert len(wac_cases.GRID) == 7
    case_ids = [cell["case_id"] for cell in wac_cases.GRID]
    assert len(set(case_ids)) == 7


def test_grid_case_ids_match_the_spec_table(built) -> None:
    expected = {
        "alympics.wac.reference_baseline",
        "alympics.wac.generous_supply",
        "alympics.wac.scarce_supply",
        "alympics.wac.mixed_policies_a",
        "alympics.wac.mixed_policies_a_seed2",
        "alympics.wac.short_horizon",
        "alympics.wac.zero_supply_degenerate",
    }
    assert set(built) == expected


def test_case_ids_contain_no_colon(built) -> None:
    for case_id in built:
        assert ":" not in case_id


def test_reference_baseline_matches_upstream_reference_run_defaults(built) -> None:
    case = built["alympics.wac.reference_baseline"]
    grid_cell = case["payload"]["grid_cell"]
    assert grid_cell["rounds"] == 20
    assert grid_cell["supply_regime"] == {"kind": "uniform", "lower": 10, "upper": 20}
    assert set(grid_cell["policy_assignment"].values()) == {"proportional"}
    assert len(case["payload"]["supply_schedule"]) == 20


def test_zero_supply_degenerate_has_constant_zero_schedule_and_no_seed(built) -> None:
    case = built["alympics.wac.zero_supply_degenerate"]
    assert case["payload"]["supply_schedule"] == [0] * 20
    assert case["payload"]["grid_cell"]["supply_schedule_seed"] is None
    assert case["world_seed"] == 0  # sentinel: CaseManifest.world_seed requires an int


def test_mixed_policies_a_and_seed2_share_policy_assignment_but_disjoint_seeds(
    built,
) -> None:
    a = built["alympics.wac.mixed_policies_a"]
    b = built["alympics.wac.mixed_policies_a_seed2"]
    assert a["payload"]["grid_cell"]["policy_assignment"] == b["payload"]["grid_cell"][
        "policy_assignment"
    ]
    assert (
        a["payload"]["grid_cell"]["supply_schedule_seed"]
        != b["payload"]["grid_cell"]["supply_schedule_seed"]
    )
    assert a["content_sha256"] != b["content_sha256"]


def test_every_case_declares_the_shared_upstream_pin(built) -> None:
    for case in built.values():
        pin = case["payload"]["upstream_pin"]
        assert pin["repo"] == "microsoft/Alympics"
        assert pin["commit"] == "caed7c8c3b8f9de9ac8be1ba54407a51087affc5"
        assert pin["license"] == "MIT"


def test_every_case_declares_5_seats_with_the_shared_role(built) -> None:
    for case in built.values():
        seat_ids = {seat["id"] for seat in case["seats"]}
        seat_roles = {seat["role"] for seat in case["seats"]}
        assert seat_ids == {"alex", "bob", "cindy", "david", "eric"}
        assert seat_roles == {"player"}


def test_every_case_provenance_is_curated_not_upstream_pinned(built) -> None:
    # AERead authors this corpus itself (no upstream task bank exists to
    # import); "upstream_pinned" would misdescribe that (schemas.py:441-444
    # legal review_status values).
    for case in built.values():
        assert case["provenance"]["review_status"] == "curated"
        assert case["provenance"]["generator_id"] == "alympics_wac_importer"


def test_max_logical_actions_is_5_times_rounds(built) -> None:
    for case in built.values():
        rounds = case["payload"]["grid_cell"]["rounds"]
        assert case["episode"]["max_logical_actions"] == 5 * rounds


def test_termination_vocabulary_is_exactly_3_reasons(built) -> None:
    for case in built.values():
        assert tuple(case["episode"]["termination"]) == (
            "rounds_exhausted",
            "all_seats_eliminated",
            "malformed_action",
        )


def test_case_record_round_trips_through_the_strict_r1_grammar(built) -> None:
    for case in built.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]
        assert manifest.family_id == "alympics.wac"


def test_case_content_sha256_matches_the_kernel_resolver_computation(built) -> None:
    case = built["alympics.wac.reference_baseline"]
    assert case_content_sha256(case) == case["content_sha256"]

    mutated = copy.deepcopy(case)
    mutated["payload"]["supply_schedule"][0] += 1
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_case_id_grammar_rejects_a_naive_colon_joined_id() -> None:
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "alympics.wac:reference_baseline",
                "family_id": "alympics.wac",
                "family_version": "0.1.0",
                "split": "base",
                "world_seed": 0,
                "seats": [{"id": "alex", "role": "player"}],
                "episode": {"max_logical_actions": 1, "termination": ["error"]},
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


def test_undeclared_policy_id_is_rejected() -> None:
    bad_cell = dict(wac_cases.GRID[0])
    bad_cell = {
        **bad_cell,
        "policy_assignment": {**bad_cell["policy_assignment"], "alex": "omniscient"},
    }
    with pytest.raises(wac_cases.GridValidationError):
        wac_cases.build_case(bad_cell)


def test_policy_assignment_must_cover_every_seat() -> None:
    bad_cell = dict(wac_cases.GRID[0])
    incomplete = dict(bad_cell["policy_assignment"])
    del incomplete["eric"]
    bad_cell = {**bad_cell, "policy_assignment": incomplete}
    with pytest.raises(wac_cases.GridValidationError):
        wac_cases.build_case(bad_cell)


# ---------------------------------------------------------------------------
# Corpus manifest.
# ---------------------------------------------------------------------------


def test_build_corpus_manifest_covers_all_7_cases(built) -> None:
    manifest = wac_cases.build_corpus_manifest(built)
    assert manifest["family_id"] == "alympics.wac"
    assert manifest["split"] == "base"
    assert len(manifest["case_ids"]) == 7
    assert set(manifest["case_ids"]) == set(built)
    for case_id in manifest["case_ids"]:
        assert manifest["case_sha256_by_id"][case_id] == built[case_id]["content_sha256"]
    assert len(manifest["content_sha256"]) == 64
    int(manifest["content_sha256"], 16)


def test_corpus_manifest_hash_changes_if_a_case_digest_changes(built) -> None:
    manifest = wac_cases.build_corpus_manifest(built)
    mutated_cases = copy.deepcopy(built)
    ref_id = "alympics.wac.reference_baseline"
    mutated_cases[ref_id]["content_sha256"] = "1" * 64
    mutated_manifest = wac_cases.build_corpus_manifest(mutated_cases)
    assert mutated_manifest["content_sha256"] != manifest["content_sha256"]


def test_build_corpus_manifest_raises_on_missing_case() -> None:
    with pytest.raises(ValueError, match="not found"):
        wac_cases.build_corpus_manifest({})


# ---------------------------------------------------------------------------
# Import determinism: two importer runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_importer_is_byte_identical_across_two_runs(tmp_path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    wac_cases.run_import(out_a)
    wac_cases.run_import(out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    assert len(files_a) == 8  # 7 case files + corpus_manifest.json

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two importer runs"


def test_importer_writes_exactly_7_case_files_plus_corpus_manifest(tmp_path) -> None:
    out_dir = tmp_path / "run"
    wac_cases.run_import(out_dir)

    case_files = sorted(out_dir.glob("alympics.wac.*.json"))
    # corpus_manifest.json also matches "alympics.wac.*.json"? No -- it does
    # not start with the case prefix, so it is excluded by this glob.
    assert len(case_files) == 7

    manifest = json.loads((out_dir / "corpus_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["case_ids"]) == 7
