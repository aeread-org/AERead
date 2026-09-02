"""Tests for the collusion foundation stage: solver, corpus, case records.

There is no upstream code to exercise here (verified: no repository is cited
for arXiv 2404.00806v6, none exists at the listing) -- "parity" instead means
hand-verified closed-form arithmetic against the paper's own quoted Appendix
A.5 figures, per ``docs/collusion_adapter_spec.md`` sections 1 and 5. The
arithmetic-parity regression below must never silently skip: a skip here
means the adapter's whole economic-mechanism claim went unchecked, the same
failure mode already logged for this codebase's tau3 fidelity suite
(``docs/collusion_adapter_spec.md`` section 5).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest
from aeread_families.collusion import cases as collusion_cases
from aeread_families.collusion import economics

CASES_DIR = Path(__file__).resolve().parents[1] / "cases" / "collusion" / "duopoly_pilot"


# ---------------------------------------------------------------------------
# Arithmetic parity (substitute for an upstream-code parity gate, spec 5).
# ---------------------------------------------------------------------------


def test_symmetric_baseline_alpha1_matches_paper_appendix_a5_to_stated_precision() -> None:
    """The paper's own Appendix A.5 quotes 1.47/22.29/1.92/33.75 -- must never skip."""
    (nash_a, nash_b), _nash_trace = economics.solve_nash(
        (2.0, 2.0), 0.0, 0.25, 100.0, 1.0, (1.0, 1.0)
    )
    (mono_a, mono_b), _mono_trace = economics.solve_monopoly(
        (2.0, 2.0), 0.0, 0.25, 100.0, 1.0, (1.0, 1.0)
    )
    assert nash_a.price == nash_b.price
    assert mono_a.price == mono_b.price
    assert round(nash_a.price, 2) == 1.47
    assert round(nash_a.profit, 2) == 22.29
    assert round(mono_a.price, 2) == 1.92
    assert round(mono_a.profit, 2) == 33.75


def test_asymmetric_quality_direction_matches_paper_appendix_a2() -> None:
    """App. A.2 confirms only direction: Firm 2 (higher a) prices/profits exceed Firm 1's."""
    (nash_a, nash_b), _ = economics.solve_nash(
        (2.0, 2.75), 0.0, 0.25, 100.0, 1.0, (1.0, 1.0)
    )
    assert nash_b.price > nash_a.price
    assert nash_b.profit > nash_a.profit


def test_solver_scales_linearly_in_alpha_per_governing_facts() -> None:
    (nash_1, _), _ = economics.solve_nash((2.0, 2.0), 0.0, 0.25, 100.0, 1.0, (1.0, 1.0))
    (nash_10, _), _ = economics.solve_nash((2.0, 2.0), 0.0, 0.25, 100.0, 10.0, (1.0, 1.0))
    assert nash_10.price == pytest.approx(nash_1.price * 10, rel=1e-9)
    assert nash_10.profit == pytest.approx(nash_1.profit * 10, rel=1e-9)


# ---------------------------------------------------------------------------
# Gate 1: corpus enumeration and content digest.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_cases() -> dict[str, dict]:
    return collusion_cases.build_all_cases()


def test_pilot_grid_has_exactly_6_cells(built_cases: dict[str, dict]) -> None:
    assert len(built_cases) == 6


def test_case_ids_are_pairwise_distinct_and_colon_free(built_cases: dict[str, dict]) -> None:
    ids = list(built_cases)
    assert len(set(ids)) == len(ids)
    assert all(":" not in case_id for case_id in ids)


def test_expected_case_ids(built_cases: dict[str, dict]) -> None:
    assert set(built_cases) == {
        "collusion.duopoly.baseline-symmetric.alpha1.seed0",
        "collusion.duopoly.baseline-symmetric.alpha3p2.seed0",
        "collusion.duopoly.baseline-symmetric.alpha10.seed0",
        "collusion.duopoly.asymmetric-quality.alpha1.seed0",
        "collusion.duopoly.asymmetric-quality.alpha3p2.seed0",
        "collusion.duopoly.asymmetric-quality.alpha10.seed0",
    }


def test_each_cell_solved_twice_in_process_is_bit_identical() -> None:
    for demand_tag in collusion_cases.DEMAND_PARAMS:
        for alpha in collusion_cases.ALPHA_VALUES:
            for seed in collusion_cases.SEED_VALUES:
                first = collusion_cases.build_case(demand_tag, alpha, seed)
                second = collusion_cases.build_case(demand_tag, alpha, seed)
                assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_nash_below_monopoly_and_ceiling_above_monopoly_per_cell(
    built_cases: dict[str, dict],
) -> None:
    for case in built_cases.values():
        gold = case["payload"]["gold_reference"]
        ceiling_k = case["payload"]["ceiling_k"]
        for seat in ("firm_a", "firm_b"):
            assert gold["p_nash"][seat] < gold["p_monopoly"][seat]
            assert ceiling_k * gold["p_monopoly"][seat] > gold["p_monopoly"][seat]


def test_case_records_round_trip_through_the_strict_r1_grammar(
    built_cases: dict[str, dict],
) -> None:
    for case in built_cases.values():
        manifest = CaseManifest.from_dict(case)
        assert manifest.case_id == case["case_id"]
        assert manifest.family_id == "collusion"
        assert manifest.family_version == "0.1.0"
        assert manifest.split == "duopoly_pilot"
        assert manifest.upstream_task_id is None
        seat_ids = {seat.id for seat in manifest.seats}
        seat_roles = {seat.role for seat in manifest.seats}
        assert seat_ids == {"firm_a", "firm_b"}
        assert seat_roles == {"pricing_agent"}
        assert manifest.episode.max_logical_actions == 600


def test_case_content_sha256_matches_the_kernel_resolver_computation(
    built_cases: dict[str, dict],
) -> None:
    case = built_cases["collusion.duopoly.baseline-symmetric.alpha1.seed0"]
    assert case_content_sha256(case) == case["content_sha256"]

    mutated = copy.deepcopy(case)
    mutated["payload"]["gold_reference"]["p_nash"]["firm_a"] += 0.01
    assert case_content_sha256(mutated) != case["content_sha256"]


def test_case_id_grammar_rejects_a_naive_colon_joined_id() -> None:
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "collusion:duopoly:baseline-symmetric",
                "family_id": "collusion",
                "family_version": "0.1.0",
                "split": "duopoly_pilot",
                "world_seed": 0,
                "seats": [
                    {"id": "firm_a", "role": "pricing_agent"},
                    {"id": "firm_b", "role": "pricing_agent"},
                ],
                "episode": {"max_logical_actions": 1, "termination": ["error"]},
                "visibility_policy": "public-prices-private-payoff",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "upstream_pinned",
                },
                "content_sha256": "0" * 64,
            }
        )


# ---------------------------------------------------------------------------
# Alpha/tag formatting helpers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alpha, expected",
    [(1.0, "1"), (3.2, "3p2"), (10.0, "10")],
)
def test_format_alpha(alpha: float, expected: str) -> None:
    assert collusion_cases._format_alpha(alpha) == expected


def test_ceiling_multiplier_is_deterministic_and_in_range() -> None:
    first = collusion_cases.ceiling_multiplier(0)
    second = collusion_cases.ceiling_multiplier(0)
    assert first == second
    assert collusion_cases.CEILING_UNIFORM_LOW <= first <= collusion_cases.CEILING_UNIFORM_HIGH


# ---------------------------------------------------------------------------
# P1 -- build determinism and on-disk corpus (spec section 1).
# ---------------------------------------------------------------------------


def test_write_cases_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    collusion_cases.run_import(out_a)
    collusion_cases.run_import(out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    assert len(files_a) == 6

    for rel in files_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes()


def test_committed_corpus_on_disk_matches_the_builder(built_cases: dict[str, dict]) -> None:
    on_disk = sorted(CASES_DIR.glob("collusion.duopoly.*.json"))
    assert len(on_disk) == 6
    for path in on_disk:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == built_cases[data["case_id"]]
