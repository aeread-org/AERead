"""Tests for the negarena case-authoring stage: pins, scenario grid, records.

Negarena ships no upstream task bank (governing fact in
``docs/negarena_adapter_spec.md``); AERead authors the scenario grid, so
these tests exercise the authoring module directly rather than a pinned
upstream checkout on disk (contrast with
``tests/test_tau3_retail_cases.py``).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.negarena import cases as negarena_cases

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = REPO_ROOT / "cases" / "negarena"


# ---------------------------------------------------------------------------
# The authored scenario grid (spec section 1).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def authored() -> tuple[dict, dict[str, dict]]:
    return negarena_cases.author_all_cases()


def test_pins_identify_the_pinned_upstream_repository() -> None:
    pins = negarena_cases.build_pins()
    assert pins == {
        "upstream_repo": "vinid/NegotiationArena",
        "upstream_commit": "c447fafd439a20b84cdedeb2f8a85c4fad764745",
        "upstream_license": "MIT",
    }


def test_authors_exactly_six_scenarios_three_per_split(authored) -> None:
    _pins, cases = authored
    assert len(cases) == 6
    by_split: dict[str, int] = {}
    for case in cases.values():
        by_split[case["split"]] = by_split.get(case["split"], 0) + 1
    assert by_split == {"buy_sell": 3, "ultimatum": 3}


def test_case_ids_are_dot_separated_lower_case_no_colons(authored) -> None:
    _pins, cases = authored
    expected_ids = {
        "negarena.buy_sell.0",
        "negarena.buy_sell.1",
        "negarena.buy_sell.2",
        "negarena.ultimatum.0",
        "negarena.ultimatum.1",
        "negarena.ultimatum.2",
    }
    assert set(cases) == expected_ids
    for case_id in cases:
        assert ":" not in case_id
        assert case_id == case_id.lower()


def test_reference_buy_sell_scenario_matches_upstreams_own_shipped_transcript(
    authored,
) -> None:
    # runner/buysell_main.py + example_logs/buysell/1707347676639/: RED cost
    # 40, BLUE willingness-to-pay 60, X:1 / ZUP:1000, iterations=10. This is
    # also the parity anchor (spec section 4, golden 1).
    _pins, cases = authored
    case = cases["negarena.buy_sell.0"]
    scenario = case["payload"]["scenario"]
    assert scenario["game_kind"] == "buy_sell"
    assert scenario["iterations"] == 10
    assert scenario["seats"]["red"]["starting_resources"] == {"X": 1}
    assert scenario["seats"]["red"]["valuation"] == {"X": 40}
    assert scenario["seats"]["red"]["goal_kind"] == "seller"
    assert scenario["seats"]["blue"]["starting_resources"] == {"ZUP": 1000}
    assert scenario["seats"]["blue"]["valuation"] == {"X": 60}
    assert scenario["seats"]["blue"]["goal_kind"] == "buyer"
    assert case["episode"]["max_logical_actions"] == 10


def test_thin_and_no_zopa_buy_sell_variants_only_change_red_cost(authored) -> None:
    _pins, cases = authored
    thin = cases["negarena.buy_sell.1"]["payload"]["scenario"]
    no_zopa = cases["negarena.buy_sell.2"]["payload"]["scenario"]
    assert thin["seats"]["red"]["valuation"] == {"X": 55}
    assert thin["seats"]["blue"]["valuation"] == {"X": 60}
    assert no_zopa["seats"]["red"]["valuation"] == {"X": 65}
    assert no_zopa["seats"]["blue"]["valuation"] == {"X": 60}


def test_reference_ultimatum_scenario_matches_upstreams_own_runner_script(
    authored,
) -> None:
    # runner/ultimatum_main.py: proposer RED holds Dollars:100, responder
    # BLUE holds Dollars:0, iterations=6.
    _pins, cases = authored
    case = cases["negarena.ultimatum.0"]
    scenario = case["payload"]["scenario"]
    assert scenario["game_kind"] == "ultimatum"
    assert scenario["iterations"] == 6
    assert scenario["seats"]["red"]["starting_resources"] == {"Dollars": 100}
    assert scenario["seats"]["blue"]["starting_resources"] == {"Dollars": 0}


def test_low_iteration_cap_ultimatum_variant_only_changes_iterations(authored) -> None:
    _pins, cases = authored
    case = cases["negarena.ultimatum.1"]
    scenario = case["payload"]["scenario"]
    assert scenario["iterations"] == 2
    assert scenario["seats"]["red"]["starting_resources"] == {"Dollars": 100}
    assert scenario["seats"]["blue"]["starting_resources"] == {"Dollars": 0}


def test_degenerate_ultimatum_endowment_is_zero_for_both_seats(authored) -> None:
    _pins, cases = authored
    case = cases["negarena.ultimatum.2"]
    scenario = case["payload"]["scenario"]
    assert scenario["seats"]["red"]["starting_resources"] == {"Dollars": 0}
    assert scenario["seats"]["blue"]["starting_resources"] == {"Dollars": 0}


def test_buy_sell_termination_reasons_have_no_early_reject(authored) -> None:
    # AlternatingGameEndsOnTag.game_over only checks for ACCEPT or the
    # iteration cap; unlike ultimatum there is no early-REJECT branch.
    _pins, cases = authored
    for case_id in ("negarena.buy_sell.0", "negarena.buy_sell.1", "negarena.buy_sell.2"):
        assert set(cases[case_id]["episode"]["termination"]) == {
            "accepted",
            "iteration_cap",
            "malformed_action",
            "invalid_measurement",
        }


def test_ultimatum_termination_reasons_include_early_reject(authored) -> None:
    _pins, cases = authored
    for case_id in (
        "negarena.ultimatum.0",
        "negarena.ultimatum.1",
        "negarena.ultimatum.2",
    ):
        assert set(cases[case_id]["episode"]["termination"]) == {
            "accepted",
            "rejected",
            "iteration_cap",
            "malformed_action",
            "invalid_measurement",
        }


def test_every_case_declares_red_and_blue_seats(authored) -> None:
    _pins, cases = authored
    for case in cases.values():
        seat_ids = {seat["id"] for seat in case["seats"]}
        seat_roles = {seat["role"] for seat in case["seats"]}
        assert seat_ids == {"red", "blue"}
        assert seat_roles == {"red", "blue"}


def test_every_case_pins_the_same_upstream_commit(authored) -> None:
    _pins, cases = authored
    for case in cases.values():
        pins = case["payload"]["pins"]
        assert pins["upstream_repo"] == "vinid/NegotiationArena"
        assert pins["upstream_commit"] == "c447fafd439a20b84cdedeb2f8a85c4fad764745"


def test_every_case_is_curated_not_upstream_pinned(authored) -> None:
    # AERead authors the scenario grid; there is no upstream corpus to pin
    # a case's provenance to (the inverse of tau3.retail).
    _pins, cases = authored
    for case in cases.values():
        assert case["provenance"]["review_status"] == "curated"
        assert case["provenance"]["generator_id"] == "negarena_case_authoring"


# ---------------------------------------------------------------------------
# Strict R1 grammar / content digest (QC Gate 1).
# ---------------------------------------------------------------------------


def test_case_record_round_trips_through_the_strict_r1_grammar(authored) -> None:
    _pins, cases = authored
    for case in cases.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]


def test_case_content_sha256_matches_the_kernel_resolver_computation(authored) -> None:
    _pins, cases = authored
    case = cases["negarena.buy_sell.0"]
    assert case_content_sha256(case) == case["content_sha256"]

    mutated = copy.deepcopy(case)
    mutated["payload"]["scenario"]["seats"]["red"]["valuation"]["X"] = 41
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_case_id_grammar_rejects_a_naive_colon_joined_id() -> None:
    # A naive "family:split:n" join is exactly what the kernel's identifier
    # grammar forbids (colons collapse GRPO groupings downstream); the
    # authoring module must mint "negarena.buy_sell.0" instead, never this.
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "negarena:buy_sell:0",
                "family_id": "negarena",
                "family_version": "0.1.0",
                "split": "buy_sell",
                "world_seed": 0,
                "seats": [{"id": "red", "role": "red"}],
                "episode": {"max_logical_actions": 1, "termination": ["accepted"]},
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


def test_build_corpus_manifest_raises_on_missing_case_ids() -> None:
    with pytest.raises(ValueError, match="not found"):
        negarena_cases.build_corpus_manifest({})


def test_corpus_manifest_hash_changes_if_the_id_list_changes(authored) -> None:
    _pins, cases = authored
    manifest = negarena_cases.build_corpus_manifest(cases)
    mutated = dict(manifest)
    mutated["case_ids"] = list(manifest["case_ids"][:-1])
    mutated_digest = negarena_cases._corpus_content_sha256(mutated)
    assert mutated_digest != manifest["content_sha256"]


# ---------------------------------------------------------------------------
# P1 -- authoring determinism: two authoring runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_authoring_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    negarena_cases.run_author(out_a)
    negarena_cases.run_author(out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 6 case files + pins.json + corpus_manifest.json
    assert len(files_a) == 8

    for rel in files_a:
        bytes_a = (out_a / rel).read_bytes()
        bytes_b = (out_b / rel).read_bytes()
        assert bytes_a == bytes_b, f"{rel} differs across two authoring runs"


# ---------------------------------------------------------------------------
# Checked-in case files under cases/negarena/ stay in sync with the authoring
# module (catches "edited the module but forgot to regenerate the fixtures").
# ---------------------------------------------------------------------------


def test_checked_in_case_files_match_the_authoring_module(authored) -> None:
    _pins, cases = authored
    for case_id, case in cases.items():
        path = CASES_DIR / case["split"] / f"{case_id}.json"
        assert path.is_file(), f"missing checked-in case file: {path}"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == case


def test_checked_in_corpus_manifest_matches_the_authoring_module(authored) -> None:
    _pins, cases = authored
    manifest = negarena_cases.build_corpus_manifest(cases)
    on_disk = json.loads((CASES_DIR / "corpus_manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest


def test_checked_in_pins_match_the_authoring_module() -> None:
    pins = negarena_cases.build_pins()
    on_disk = json.loads((CASES_DIR / "pins.json").read_text(encoding="utf-8"))
    assert on_disk == pins
