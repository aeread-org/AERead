"""The single-period procurement gap analysis: exact parts, steps that hold their decisions, typed failures."""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from aeread.shared_runner.run.publication import assert_public_payload
from aeread_families.procurement_allocation import regret_decomposition as rd
from aeread_families.procurement_allocation import single_period_gap as gap

PRIMARY = gap.OUT / "reports" / "gap_decomposition.json"
SECONDARY = gap.OUT / "reports" / "gap_decomposition_pre_award_check.json"


def _step(ordinal, action, supplier=None, days=0, cost=0.0):
    return {"ordinal": ordinal, "action": action, "supplier_id": supplier, "days": days, "days_added": 0, "cost_added": cost}


def _terms(**values):
    terms = {t: 0.0 for t in rd.REGRET_TERMS}
    terms.update(values)
    return terms


# --- parts --------------------------------------------------------------------------------------------------------

def test_a_rejected_award_and_a_missing_award_are_each_one_whole_part() -> None:
    parts = gap.split_endpoint("infeasible_award", -148.2, None)
    assert parts["infeasible_award"] == -148.2 and sum(parts.values()) == -148.2
    parts = gap.split_endpoint("no_award", -111.9, None)
    assert parts["no_award"] == -111.9 and sum(parts.values()) == -111.9


def test_a_feasible_award_splits_its_ten_terms_into_four_groups_with_the_endpoint_sign() -> None:
    terms = _terms(revenue_shortfall=14.0, shortfall_penalty_excess=6.0, purchase_cost_excess=3.0, shipping_cost_excess=-1.0,
                   duty_cost_excess=0.5, working_capital_cost_excess=0.25, recovery_shortfall=0.75,
                   return_freight_cost_excess=0.1, refund_financing_cost_excess=0.05, information_cost_excess=-0.2)
    parts = gap.split_endpoint("feasible_award", -sum(terms.values()), terms)
    assert parts["kits_short"] == pytest.approx(-20.0)
    assert parts["landed_cost"] == pytest.approx(-2.5)
    assert parts["terms_and_returns"] == pytest.approx(-1.15)
    assert parts["information_spend"] == pytest.approx(0.2)
    assert parts["infeasible_award"] == parts["no_award"] == 0.0
    assert sum(parts.values()) == pytest.approx(-sum(terms.values()))


def test_a_feasible_award_without_terms_is_refused() -> None:
    with pytest.raises(ValueError):
        gap.split_endpoint("feasible_award", -1.0, None)


# --- contribution rows --------------------------------------------------------------------------------------------

def _evaluation(kits, landed, wc, recovery, info):
    return {"completed_kits": kits, "purchase_cost_usd": landed, "shipping_cost_usd": 0.0, "duty_cost_usd": 0.0,
            "working_capital_cost_usd": wc, "return_freight_cost_usd": 0.0, "refund_financing_cost_usd": 0.0,
            "expected_recovery_usd": recovery, "information_cost_usd": info}


def test_feasible_award_rows_sit_at_the_award_and_at_every_paid_information_step() -> None:
    steps = [_step(1, "request_quote", "a", cost=0.1), _step(2, "request_sample", "a", cost=0.4),
             _step(3, "counter_offer", "a", cost=0.15), _step(4, "submit_award")]
    terms = _terms(revenue_shortfall=7.0, purchase_cost_excess=2.0, working_capital_cost_excess=0.3, information_cost_excess=0.15)
    parts = gap.split_endpoint("feasible_award", -9.45, terms)
    rows = gap.cell_contributions({"category": "feasible_award", "parts": parts, "steps": steps,
                                   "evaluation": _evaluation(19, 42.0, 0.5, 0.0, 0.65),
                                   "plan_evaluation": _evaluation(20, 40.0, 0.2, 0.0, 0.5)})
    sums = collections.Counter()
    for row in rows:
        sums[row["component"]] += row["amount"]
        assert row["note"]
    assert {k: sums[k] for k in gap.KEYS} == pytest.approx(parts)
    info = [(r["ordinal"], r["action"], round(r["amount"], 6)) for r in rows if r["component"] == "information_spend"]
    assert info == [(1, "request_quote", -0.1), (2, "request_sample", -0.4), (3, "counter_offer", -0.15), (4, "submit_award", 0.5)]
    assert {r["ordinal"] for r in rows if r["component"] != "information_spend"} == {4}


@pytest.mark.parametrize("reason,last,expect", [
    ("deferred", "defer", "deferred instead of awarding"),
    ("interaction_budget_exhausted", "counter_offer", "spent the last of 10 actions"),
    ("invalid_action", "unparseable", "could not be parsed (malformed_json)"),
])
def test_a_cell_with_no_award_is_one_row_at_its_last_step(reason, last, expect) -> None:
    steps = [_step(1, "request_quote", "a", cost=0.1), _step(2, last, "a")]
    parts = gap.split_endpoint("no_award", -110.3, None)
    rows = gap.cell_contributions({"category": "no_award", "parts": parts, "steps": steps, "termination_reason": reason,
                                   "failure_code": "malformed_json", "max_actions": 10})
    assert [(r["ordinal"], r["action"], r["component"], r["amount"]) for r in rows] == [(2, last, "no_award", -110.3)]
    assert expect in rows[0]["note"]


def test_a_rejected_award_is_one_row_at_the_award() -> None:
    steps = [_step(1, "request_sample", "a", cost=0.4), _step(2, "submit_award")]
    rows = gap.cell_contributions({"category": "infeasible_award", "parts": gap.split_endpoint("infeasible_award", -99.0, None),
                                   "steps": steps, "violation_keys": ["the cash budget"]})
    assert [(r["ordinal"], r["component"], r["amount"]) for r in rows] == [(2, "infeasible_award", -99.0)]
    assert "the cash budget" in rows[0]["note"]


# --- classes ------------------------------------------------------------------------------------------------------

def _line(supplier, component, quantity=20, late=False, verified=True, deciding=None, lead=5):
    return {"supplier_id": supplier, "component": component, "quantity": quantity, "moq": 10, "order_step": 10, "capacity": 60,
            "lead_time_days": lead, "late": late, "deciding_ordinal": deciding, "verified": verified}


def _facts(violations, lines, steps=None, **extra):
    steps = steps or [_step(1, "request_sample", "a", days=3), _step(2, "submit_award", days=3)]
    base = {"category": "infeasible_award", "termination_reason": "submitted", "failure_code": None, "violations": violations,
            "steps": steps, "last_ordinal": steps[-1]["ordinal"], "last_action": steps[-1]["action"], "last_supplier": None,
            "max_actions": 10, "bom": ["x", "y"], "deadline_days": 14, "elapsed_days": steps[-1]["days"], "completed_kits": 0,
            "minimum_service_kits": 18, "cash_spend": 50.0, "cash_budget": 100.0, "award_ordinal": steps[-1]["ordinal"],
            "lines": lines}
    base.update(extra)
    return base


def _kinds(found):
    return {f["class"]: f for f in found}


def test_a_missing_component_is_its_own_cause_of_minimum_service() -> None:
    found = _kinds(gap.classify(_facts(["minimum_service_not_met"], [_line("a", "x")])))
    assert set(found) == {"minimum_service_not_met", "component_not_awarded"}
    assert "buys no y" in found["component_not_awarded"]["note"] and found["component_not_awarded"]["ordinal"] == 2


def test_a_late_line_is_located_at_the_step_that_used_up_its_slack() -> None:
    steps = [_step(1, "request_quote", "a", days=1), _step(2, "request_sample", "b", days=10),
             _step(3, "request_sample", "a", days=12), _step(4, "submit_award", days=12)]
    lines = [_line("a", "x", late=True, deciding=2, lead=5), _line("b", "y")]
    found = _kinds(gap.classify(_facts(["minimum_service_not_met"], lines, steps=steps)))
    assert set(found) == {"minimum_service_not_met", "arrives_after_deadline"}
    assert found["arrives_after_deadline"]["ordinal"] == 2
    assert "a sample from b took the clock to day 10" in found["arrives_after_deadline"]["note"]


def test_too_few_units_is_the_cause_only_when_nothing_else_explains_it() -> None:
    lines = [_line("a", "x", quantity=10), _line("b", "y", quantity=10)]
    found = _kinds(gap.classify(_facts(["minimum_service_not_met"], lines, completed_kits=8)))
    assert set(found) == {"minimum_service_not_met", "quantity_short"}
    unverified = [_line("a", "x"), _line("b", "y", verified=False)]
    found = _kinds(gap.classify(_facts(["b.sample_not_verified", "minimum_service_not_met"], unverified)))
    assert set(found) == {"sample_not_verified", "minimum_service_not_met"}
    assert "20 units from b without a verified sample" in found["sample_not_verified"]["note"]


def test_gate_violations_name_their_supplier_and_terms() -> None:
    lines = [_line("a", "x", quantity=19), _line("b", "y", quantity=5)]
    found = _kinds(gap.classify(_facts(["cash_budget_exceeded", "a.invalid_order_step", "b.below_moq"], lines, cash_spend=154.5)))
    assert set(found) == {"cash_budget_exceeded", "invalid_order_step", "below_moq"}
    assert "$154.50 exceeds the $100.00 budget" in found["cash_budget_exceeded"]["note"]
    assert "19 from a, which sells 10 and up in steps of 10" in found["invalid_order_step"]["note"]
    assert "5 from b, below its minimum order of 10" in found["below_moq"]["note"]


def test_the_remaining_gate_violations_are_typed_by_supplier() -> None:
    lines = [_line("a", "x", quantity=70), _line("b", "y"), _line("c", "y")]
    found = _kinds(gap.classify(_facts(["a.over_capacity", "b.wrong_variant", "c.expired_offer"], lines)))
    assert set(found) == {"over_capacity", "wrong_variant", "expired_offer"}
    assert "70 from a, above its capacity of 60" in found["over_capacity"]["note"]
    assert "b's offer (wrong variant)" in found["wrong_variant"]["note"]
    assert all(f["ordinal"] == 2 for f in found.values())


@pytest.mark.parametrize("reason,violations,expect", [
    ("interaction_budget_exhausted", ["interaction_budget_exhausted"], "interaction_budget_exhausted"),
    ("invalid_action", ["malformed_json"], "unparseable_action"),
    ("deferred", [], "deferred"),
])
def test_endings_without_an_award_are_typed_at_the_last_step(reason, violations, expect) -> None:
    steps = [_step(1, "request_quote", "a"), _step(2, "counter_offer", "a")]
    facts = _facts(violations, [], steps=steps, category="no_award", termination_reason=reason, failure_code="malformed_json",
                   award_ordinal=None)
    found = gap.classify(facts)
    assert [(f["class"], f["ordinal"]) for f in found] == [(expect, 2)]


def test_an_unknown_violation_is_refused_rather_than_dropped() -> None:
    with pytest.raises(ValueError):
        gap.classify(_facts(["a.duplicate_supplier"], [_line("a", "x")]))


# --- the published bundle -----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def reports() -> dict:
    return {"primary": json.loads(PRIMARY.read_text()), "secondary": json.loads(SECONDARY.read_text())}


def _published_rows() -> dict[str, dict]:
    rows = {}
    for arm in ("labeled_control", "labeled_treatment", "opaque_control", "opaque_treatment"):
        report, _ = rd.verified_bundle_report(gap.EVIDENCE / gap.CONFIRMATORY / "reports" / f"{arm}.json")
        rows.update({r["receipt_sha256"]: r for r in report["rows"]})
    recovery = json.loads((gap.EVIDENCE / gap.RECOVERY / "reports" / "confirmatory.json").read_text())
    rows.update({r["receipt_sha256"]: r for r in recovery["rows"]})
    return rows


def test_published_parts_sum_to_each_cells_published_endpoint(reports) -> None:
    published = _published_rows()
    for key, cells in (("primary", 144), ("secondary", 36)):
        report = reports[key]
        assert len(report["cell_parts"]) == cells
        for cell in report["cell_parts"]:
            assert sum(cell["parts"].values()) == pytest.approx(-published[cell["receipt_sha256"]]["regret_to_upper_bound_usd"], abs=1e-6)
        assert sum(c["difference"] for c in report["components"]) == pytest.approx(report["realized"]["difference"])
        assert sum(t["contribution"] for t in report["transitions"]["rows"]) == pytest.approx(report["realized"]["difference"])


def test_the_realized_gaps_reproduce_the_published_effects(reports) -> None:
    effects = json.loads((gap.EVIDENCE / gap.CONFIRMATORY / "reports" / "confirmatory_effects.json").read_text())["effects"]
    assert reports["primary"]["realized"]["difference"] == pytest.approx(
        effects["overall_treatment_minus_control"]["contribution_margin_usd"]["world_cluster_mean"], abs=1e-9)
    recovery = json.loads((gap.EVIDENCE / gap.RECOVERY / "reports" / "confirmatory.json").read_text())["summary"]
    assert reports["secondary"]["realized"]["difference"] == pytest.approx(-recovery["mean_regret_delta_usd"], abs=1e-9)
    assert reports["primary"]["bootstrap"] is None and reports["primary"]["intervals"].startswith("none:")
    assert reports["secondary"]["bootstrap"]["unit"] == "world"


def test_contribution_rows_add_up_to_each_cells_parts(reports) -> None:
    for report in reports.values():
        rows = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
        assert len(rows) == report["contributions"]["rows"]
        sums = collections.Counter()
        for r in rows:
            sums[(r["receipt_sha256"], r["component"])] += r["amount"]
        for cell in report["cell_parts"]:
            for key, value in cell["parts"].items():
                assert sums[(cell["receipt_sha256"], key)] == pytest.approx(value, abs=1e-4)


def test_every_primary_locator_lands_on_the_published_step_that_holds_its_decision(reports) -> None:
    grain = collections.defaultdict(dict)
    path = gap.EVIDENCE / gap.GRAINS / "trajectories" / f"{gap.CONFIRMATORY}.jsonl"
    for line in path.read_text().splitlines():
        s = json.loads(line)
        action = s["action"] if isinstance(s["action"], dict) else {"action": "unparseable"}
        grain[s["source_receipt_sha256"]][s["step_index"]] = (s["phase_id"], s["seat_id"], action["action"],
                                                              action.get("supplier_id"), s["phase_instance_id"])
    report = reports["primary"]
    rows = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
    for r in rows + report["instances"]:
        phase, seat, action, supplier, _ = grain[r["receipt_sha256"]][r["step_index"]]
        assert (phase, seat, action, supplier) == (r["phase_id"], r["seat_id"], r["action"], r["supplier_id"])
        first_phase_starts = len({grain[r["receipt_sha256"]][i][4] for i in range(r["step_index"] + 1)})
        assert r["round_index"] == first_phase_starts - 1
    assert {r["action"] for r in rows if r["component"] in ("infeasible_award", "kits_short", "landed_cost", "terms_and_returns")} == {"submit_award"}
    per_decision = collections.Counter((r["receipt_sha256"], r["step_index"], r["component"], r["amount"] > 0) for r in rows)
    assert max(per_decision.values()) == 1  # one row per decision per part (the plan's information credit is the one positive row)


def test_secondary_rows_have_no_step_fields_and_name_their_published_action(reports) -> None:
    published = _published_rows()
    report = reports["secondary"]
    rows = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
    for r in rows + report["instances"]:
        assert r["step_index"] is None and r["round_index"] is None and r["phase_id"] is None and r["seat_id"] is None
        entry = published[r["receipt_sha256"]]["action_trace"][r["action_ordinal"] - 1]
        supplier = entry.get("supplier_id") if entry["action"] in gap._ADDRESSED else None
        assert (entry["action"], supplier) == (r["action"], r["supplier_id"])


def test_the_seed_repeat_check_is_what_sets_the_unit(reports) -> None:
    published = _published_rows()
    digests = collections.defaultdict(set)
    for cell in reports["primary"]["cell_parts"]:
        digests[(cell["unit"], cell["stratum"])].add(published[cell["receipt_sha256"]]["case_content_sha256"])
    assert len(digests) == 24 and all(len(d) == 1 for d in digests.values())
    digests.clear()
    for cell in reports["secondary"]["cell_parts"]:
        digests[cell["unit"]].add(published[cell["receipt_sha256"]]["case_content_sha256"])
    assert len(digests) == 6 and all(len(d) == 3 for d in digests.values())


def test_replay_steps_agrees_with_the_published_replay() -> None:
    report, _ = rd.verified_bundle_report(gap.EVIDENCE / gap.CONFIRMATORY / "reports" / "labeled_control.json")
    for row in report["rows"][:6]:
        case = json.loads(rd.case_path_for_id(row["case_id"]).read_text())["payload"]
        ours, theirs = gap.replay_steps(case, row["action_trace"]), rd.replay_action_trace(case, row["action_trace"])
        assert ours["outcome"] == theirs["outcome"] and len(ours["steps"]) == row["action_count"]
        assert sum(s["cost_added"] for s in ours["steps"]) == pytest.approx(ours["outcome"]["information_cost_usd"])


def test_the_bundle_regenerates_and_carries_no_prohibited_text() -> None:
    assert gap.check()
    files = [p for p in gap.OUT.rglob("*") if p.is_file()]
    files += [Path(gap.__file__), Path(__file__)]
    for path in files:
        assert_public_payload(str(path.name), path.read_bytes())
