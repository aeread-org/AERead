"""Refund V2.5 lower controls and the declared beatability rule (QC Gate 3)."""
import pytest

from aeread_families.refund import v2_5_controls as controls


def _rows(seat, cohort, control, values):
    return [{"seat": seat, "cohort": cohort, "control": control, "case_id": f"case_{i}",
             "end_to_end": e2e, "policy_semantic": sem} for i, (e2e, sem) in enumerate(values)]


def test_rule_is_the_declared_identity():
    rule = controls.RULE
    assert rule.rule_id == "refund_v25_beatability/1"
    assert (rule.end_to_end_margin, rule.policy_semantic_margin, rule.max_reach_share) == (0.50, 0.25, 0.10)
    assert rule.policy_semantic_seats == ("policy",)
    assert set(controls.CONTROLS) == {"customer", "intake", "policy", "payments"}


def test_rule_passes_a_floor_control_and_fails_each_clause_separately():
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 20)
    floor = _rows("policy", "c", "floor", [(0.0, 0.0)] * 20)
    assert controls.evaluate_rule(reference + floor)["passes"]
    # B3 alone: 3 of 20 reached (15% > 10%), e2e gap 0.85, semantic gap 0.85.
    reach = _rows("policy", "c", "reach", [(1.0, 1.0)] * 3 + [(0.0, 0.0)] * 17)
    verdict = controls.evaluate_rule(reference + reach)
    clauses = verdict["verdicts"][0]["controls"][0]["clauses"]
    assert not verdict["passes"]
    assert [k for k, v in clauses.items() if not v["holds"]] == ["B3_reach_share"]
    assert clauses["B3_reach_share"]["reached_case_ids"] == ["case_0", "case_1", "case_2"]
    # B2 alone: no case reached, but the semantic content is mostly right.
    semantic = _rows("policy", "c", "semantic", [(0.0, 0.9)] * 20)
    clauses = controls.evaluate_rule(reference + semantic)["verdicts"][0]["controls"][0]["clauses"]
    assert [k for k, v in clauses.items() if not v["holds"]] == ["B2_policy_semantic_margin"]
    # B1 fails with B3 whenever more than half the strict trajectories pass.
    half = _rows("policy", "c", "half", [(1.0, 0.0)] * 11 + [(0.0, 0.0)] * 9)
    clauses = controls.evaluate_rule(reference + half)["verdicts"][0]["controls"][0]["clauses"]
    assert {k for k, v in clauses.items() if not v["holds"]} == {"B1_end_to_end_margin", "B3_reach_share"}


def test_rule_margins_are_inclusive_at_the_declared_threshold():
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 20)
    edge = _rows("policy", "c", "edge", [(1.0, 1.0)] * 2 + [(0.5, 0.75)] * 18)
    # e2e gap = 1 - (2 + 9) / 20 = 0.45 < 0.5, so B1 fails; reach 2/20 = 0.10 holds.
    clauses = controls.evaluate_rule(reference + edge)["verdicts"][0]["controls"][0]["clauses"]
    assert not clauses["B1_end_to_end_margin"]["holds"]
    assert clauses["B3_reach_share"]["holds"]
    exact = _rows("policy", "c", "exact", [(0.5, 0.75)] * 20)
    clauses = controls.evaluate_rule(reference + exact)["verdicts"][0]["controls"][0]["clauses"]
    assert clauses["B1_end_to_end_margin"]["holds"] and clauses["B2_policy_semantic_margin"]["holds"]


def test_small_cohort_allows_no_reached_case():
    reference = _rows("payments", "tiny", "reference", [(1.0, 1.0)] * 4)
    one = _rows("payments", "tiny", "one", [(1.0, 1.0)] + [(0.0, 1.0)] * 3)
    verdict = controls.evaluate_rule(reference + one)
    assert not verdict["passes"]
    assert verdict["failing_cohorts"] == [{"seat": "payments", "cohort": "tiny", "failing_controls": ["one"]}]
    # policy_semantic is the scripted counterpart's outside the policy seat: not a clause.
    assert "B2_policy_semantic_margin" not in verdict["verdicts"][0]["controls"][0]["clauses"]


def test_a_reference_failure_counts_as_reached():
    reference = _rows("policy", "c", "reference", [(0.0, 1.0)] + [(1.0, 1.0)] * 19)
    floor = _rows("policy", "c", "floor", [(0.0, 0.0)] * 20)
    clauses = controls.evaluate_rule(reference + floor)["verdicts"][0]["controls"][0]["clauses"]
    assert clauses["B3_reach_share"]["reached_case_ids"] == ["case_0"]


def test_mutation_a_control_that_copies_the_reference_fails_the_rule():
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 20)
    copy = [{**row, "control": "copy_reference"} for row in reference]
    verdict = controls.evaluate_rule(reference + copy)
    assert not verdict["passes"]
    assert all(not clause["holds"] for clause in verdict["verdicts"][0]["controls"][0]["clauses"].values())


@pytest.mark.parametrize("broken", ["no_reference", "no_control", "case_mismatch", "duplicate"])
def test_incomparable_screens_raise_instead_of_returning_a_verdict(broken):
    reference = _rows("policy", "c", "reference", [(1.0, 1.0)] * 3)
    floor = _rows("policy", "c", "floor", [(0.0, 0.0)] * 3)
    rows = {"no_reference": floor, "no_control": reference, "case_mismatch": reference + floor[:2],
            "duplicate": reference + floor + floor[:1]}[broken]
    with pytest.raises(ValueError):
        controls.evaluate_rule(rows)
