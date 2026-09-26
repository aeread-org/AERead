"""The repeated-sourcing gap analysis: an exact split against the bound's plan, typed decisions, real steps."""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from aeread_families.procurement_allocation import relationship_gap as gap

WORLD = gap.ROOT / "cases" / "procurement_allocation_v1" / "relationship_holdout_v1" / "loyalty_investment_2430000.json"
PARTNER, STEADY = "esp32_s3_n8r8_partner", "ssd1306_oled_096_steady"


def _step(i: int, action: dict | None) -> dict:
    valid = action is not None
    return {"step_index": i, "_round_index": i, "phase_id": "buyer_procurement_turn", "seat_id": "buyer",
            "phase_instance_id": f"phase_{i}", "action": action,
            "outcome": {"valid": valid, "failure_code": None if valid else "malformed_procurement_action"},
            "parse": {"ok": valid, "error_code": None if valid else "malformed_procurement_action"}}


def _trajectory() -> list[dict]:
    """Period 1 qualifies and awards both; period 2 re-quotes, one counter refused and one accepted at the floor;
    period 3 ends on an unparseable action, so period 4 is never played."""
    quote = lambda s: {"action": "request_quote", "supplier_id": s, "message": "m"}
    sample = lambda s: {"action": "request_sample", "supplier_id": s, "message": "m"}
    counter = lambda s, offer, price: {"action": "counter_offer", "supplier_id": s, "offer_id": offer,
                                       "proposal": {"unit_price_usd": price}, "message": "m"}
    award = lambda a, b: {"action": "submit_award", "award_lines": [{"offer_id": a, "quantity": 20}, {"offer_id": b, "quantity": 20}]}
    actions = [
        {"action": "inquire", "supplier_id": PARTNER, "fields": ["lead_time"], "message": "m"},
        quote(PARTNER), sample(PARTNER), quote(STEADY), sample(STEADY),
        award(f"offer_{PARTNER}_v1", f"offer_{STEADY}_v1"),
        quote(PARTNER), quote(STEADY),
        counter(PARTNER, f"offer_{PARTNER}_v2", 2.5),         # below the floor: refused
        counter(STEADY, f"offer_{STEADY}_v2", 1.091622),      # at the floor: accepted as v3
        award(f"offer_{PARTNER}_v2", f"offer_{STEADY}_v3"),
        None,
    ]
    return [_step(i, a) for i, a in enumerate(actions)]


def _bound(margins=(90.0, 95.0, 100.0, 105.0)) -> list[dict]:
    """A synthetic bound: every period the same terms, information 1.3, margin as given."""
    out = []
    for period, margin in enumerate(margins, start=1):
        terms = {"service": 187.0, "list_price": -89.0, "relationship_price": 0.0, "negotiated_price": 0.0, "logistics": 0.0}
        terms["logistics"] = margin + 1.3 - sum(terms.values())
        out.append({"period": period, "margin": margin, "information": 1.3, "terms": terms, "outside": 0.0, "plan": []})
    return out


@pytest.fixture(scope="module")
def replayed() -> list[dict]:
    world = json.loads(WORLD.read_text())
    return gap.replay_cell(world["payload"], _trajectory())


def test_the_replay_scores_each_period_and_forfeits_the_rest(replayed) -> None:
    assert [r["status"] for r in replayed] == ["award", "award", "failed", "unplayed"]
    assert [r["close_step"]["step_index"] for r in replayed] == [5, 10, 11, 11]
    assert replayed[0]["information"] == pytest.approx(0.05 + 0.1 + 0.4 + 0.1 + 0.4)
    assert replayed[1]["information"] == pytest.approx(0.1 + 0.1 + 0.15 + 0.15)
    assert replayed[2]["margin"] == replayed[3]["margin"] == 0.0  # defer value 0, nothing bought in period 3
    assert [c["accepted"] for c in replayed[1]["counters"]] == [False, True]


def test_purchase_splits_into_list_relationship_and_counter(replayed) -> None:
    world = json.loads(WORLD.read_text())
    listed = {s["supplier_id"]: s["private_terms"]["base_unit_price_usd"] for s in world["payload"]["suppliers"]}
    second = replayed[1]
    lines = {l["supplier_id"]: l for l in second["lines"]}
    # one consecutive award: the partner's schedule takes 6.65% off its list price; the steady supplier has none
    assert lines[PARTNER]["quoted"] == pytest.approx(listed[PARTNER] * (1 - 0.0665), abs=1e-6)
    assert lines[PARTNER]["loyalty_discount"] == pytest.approx(0.0665)
    assert lines[STEADY]["paid"] == pytest.approx(1.091622) and lines[STEADY]["quoted"] == pytest.approx(listed[STEADY])
    terms = second["terms"]
    assert terms["list_price"] == pytest.approx(-20 * (listed[PARTNER] + listed[STEADY]))
    assert terms["relationship_price"] == pytest.approx(20 * listed[PARTNER] * 0.0665, abs=1e-4)
    assert terms["negotiated_price"] == pytest.approx(20 * (listed[STEADY] - 1.091622))
    assert sum(terms.values()) - second["information"] == pytest.approx(second["margin"])


def test_period_parts_put_a_lost_period_in_one_part() -> None:
    bound = _bound()[0]
    lost = {"period": 1, "margin": -0.6, "information": 0.6, "terms": None, "outside": 0.0}
    parts = gap.period_parts(lost, bound)
    assert parts["periods_lost"] == pytest.approx(-(bound["margin"] + bound["information"]))
    assert parts["information"] == pytest.approx(-(0.6 - 1.3))
    assert all(parts[k] == 0.0 for k in gap.ECONOMIC)
    assert sum(parts.values()) == pytest.approx(lost["margin"] - bound["margin"])
    kept = {"period": 1, "margin": 80.0, "information": 1.0,
            "terms": {"service": 187.0, "list_price": -95.0, "relationship_price": 0.0, "negotiated_price": 0.0, "logistics": -11.0},
            "outside": 0.0}
    parts = gap.period_parts(kept, bound)
    assert parts["periods_lost"] == 0.0 and parts["list_price"] == pytest.approx(-6.0)
    assert sum(parts.values()) == pytest.approx(80.0 - bound["margin"])


def test_cell_parts_rows_and_classes_add_up(replayed) -> None:
    bound = _bound()
    result = gap.analyse_cell(replayed, bound)
    assert sum(result["parts"].values()) == pytest.approx(sum(r["margin"] for r in replayed) - sum(b["margin"] for b in bound))
    sums = collections.Counter()
    for row in result["contributions"]:
        sums[row["component"]] += row["amount"]
        assert row["note"] and row["phase_id"] == "buyer_procurement_turn" and row["seat_id"] == "buyer"
        if row["component"] in gap.ECONOMIC:
            assert row["action"] == "submit_award"
        if row["component"] == "periods_lost":
            assert row["action"] in {"submit_award", "unparseable"}
    assert {k: sums[k] for k in gap.KEYS} == pytest.approx(result["parts"])
    # periods 3 and 4 are lost whole: the bound's pre-information margin in each
    assert result["parts"]["periods_lost"] == pytest.approx(-(100.0 + 1.3) - (105.0 + 1.3))
    classes = collections.Counter(i["class"] for i in result["instances"])
    assert classes == {"inquiry": 1, "counter_rejected": 1, "awarded_above_floor": 2, "loyalty_discount": 1,
                       "malformed_action": 1, "unplayed_period": 1}
    malformed = next(i for i in result["instances"] if i["class"] == "malformed_action")
    assert malformed["step_index"] == 11 and malformed["action"] == "unparseable"
    assert malformed["amount"] == pytest.approx(result["parts"]["periods_lost"])


def test_a_late_rejected_award_is_classed_by_every_cause() -> None:
    bound = _bound()[:1]
    step = _step(3, {"action": "submit_award", "award_lines": []})
    record = {"period": 1, "margin": -0.3, "information": 0.3, "terms": None, "outside": 0.0, "lines": [], "status": "rejected",
              "violations": ["x.sample_not_verified", "minimum_service_not_met"], "late_lines": ["x"], "elapsed_days": 9,
              "completed_kits": 0, "close_step": step, "buying": [], "counters": []}
    classes = {i["class"]: i["amount"] for i in gap.analyse_cell([record], bound)["instances"]}
    assert set(classes) == {"below_minimum_service", "unverified_sample", "late_award"}
    assert all(v == pytest.approx(-(90.0 + 1.3)) for v in classes.values())
    record["violations"] = ["x.wrong_variant"]
    with pytest.raises(ValueError):
        gap.analyse_cell([record], bound)


# --------------------------------------------------------------------------
# The published bundle
# --------------------------------------------------------------------------


def _report(suffix: str) -> dict:
    return json.loads((gap.OUT / "reports" / f"gap_decomposition_{suffix}.json").read_text())


def _published_steps(bundle: str) -> dict:
    steps = collections.defaultdict(dict)
    for row in gap._steps(bundle).values():
        for s in row:
            action = s["action"]["action"] if isinstance(s["action"], dict) else "unparseable"
            steps[s["source_receipt_sha256"]][s["step_index"]] = (s["phase_id"], s["seat_id"], s["_round_index"], action)
    return steps


@pytest.mark.parametrize("comparison", gap.COMPARISONS, ids=lambda c: c.suffix)
def test_published_parts_sum_to_the_published_endpoint(comparison) -> None:
    report = _report(comparison.suffix)
    cells = {c["receipt_sha256"]: c for bundle in (comparison.left, comparison.right) for c in gap._cells(bundle)
             if c.get("status") == "completed"}
    for row in report["cell_parts"]:
        cell = cells[row["receipt_sha256"]]
        endpoint = float(cell["contribution_margin_usd"]) - float(cell["upper_bound_usd"])
        assert endpoint == pytest.approx(-float(cell["regret_to_upper_bound_usd"]), abs=1e-6)
        assert sum(row["parts"].values()) == pytest.approx(endpoint, abs=1e-4)
    published = json.loads((gap.EVIDENCE / comparison.left / "reports" / f"comparison_vs_{comparison.right}.json").read_text())
    assert report["realized"]["difference"] == pytest.approx(-published["mean_regret_delta_usd"], abs=1e-5)
    assert report["cells"]["left"] == report["cells"]["right"] == published["paired_cells"]
    assert sum(c["difference"] for c in report["components"]) == pytest.approx(report["realized"]["difference"], abs=1e-5)
    counts = collections.Counter((i["class"], i["side"]) for i in report["instances"])
    for c in report["classes"]:
        assert (c["left_count"], c["right_count"]) == (counts[(c["key"], "left")], counts[(c["key"], "right")])


@pytest.mark.parametrize("comparison", gap.COMPARISONS, ids=lambda c: c.suffix)
def test_published_rows_and_instances_name_real_steps(comparison) -> None:
    report = _report(comparison.suffix)
    steps = {**_published_steps(comparison.left), **_published_steps(comparison.right)}
    rows = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
    assert len(rows) == report["contributions"]["rows"]
    closing = {"submit_award", "unparseable"}
    sums = collections.Counter()
    for row in rows + report["instances"]:
        phase, seat, round_index, action = steps[row["receipt_sha256"]][row["step_index"]]
        assert (row["phase_id"], row["seat_id"], row["round_index"], row["action"]) == (phase, seat, round_index, action)
    for row in rows:
        sums[(row["receipt_sha256"], row["component"])] += row["amount"]
        if row["component"] in gap.ECONOMIC:
            assert row["action"] == "submit_award"
        elif row["component"] == "periods_lost":
            assert row["action"] in closing
        else:
            assert row["action"] in gap.INFORMATION_ACTIONS | closing
            assert row["action"] in closing or row["amount"] < 0
    for cell in report["cell_parts"]:
        for key, value in cell["parts"].items():
            assert sums[(cell["receipt_sha256"], key)] == pytest.approx(value, abs=1e-4)


def test_one_world_regenerates_from_the_published_trajectories() -> None:
    """A slice of --check: the world with a malformed action and a lost period, rebuilt from its sources."""
    comparison = gap.COMPARISONS[0]
    world = "procurement_allocation_v1.relationship_holdout_v1.loyalty_investment_2430006"
    keep = {(world, seed) for seed in (76001, 76002, 76003, 76004, 76005)}
    published = {c["receipt_sha256"]: c["parts"] for c in _report(comparison.suffix)["cell_parts"]}
    rebuilt = 0
    for side, bundle in (("left", comparison.left), ("right", comparison.right)):
        for cell in gap._side(side, bundle, keep)["cells"]:
            assert {k: round(v, 6) for k, v in cell["parts"].items()} == published[cell["receipt_sha256"]]
            rebuilt += 1
    assert rebuilt == 10
