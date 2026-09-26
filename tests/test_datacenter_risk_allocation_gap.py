"""The risk-allocation gap analysis: every move re-graded and split into parts that sum to the published score."""

from __future__ import annotations

import collections
import json
import math

import pytest

from aeread.shared_runner.run.publication import assert_public_payload
from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_environment as env
from aeread_families.datacenter_development import risk_allocation_gap as gap
from aeread_families.datacenter_development import risk_allocation_pack as rp

PACKS = {pack: rp.load(pack) for pack in ("risk_allocation_dev_v1", "risk_allocation_two_prices_dev_v1")}


def _payload(slug: str, seat: str, pack: str = "risk_allocation_dev_v1") -> dict:
    manifest, cases = PACKS[pack]
    world = next(w for w in manifest["worlds"] if w["slug"] == slug)
    return cases[world["seats"][seat]["case_id"]]["payload"]


def _act(a: ra.Action) -> dict:
    if a.kind != "propose":
        return {"action": a.kind, "package": None if a.package is None else a.package.as_dict(), "price": None, "reason": ""}
    return {"action": "propose", "package": a.package.as_dict(), "price": None if a.price == ra.PRICE_IT else a.price,
            "alternate": None if a.alternate is None else a.alternate.as_dict(), "reason": ""}


def _reference(payload: dict) -> list[dict]:
    game, other = env.game_of(payload)
    policy, seen, out = ra.reference_policy(game), ra.start(game, other), []
    while True:
        a = policy(seen)
        out.append(_act(a))
        if a.kind != "propose":
            return out
        result, nxt, _ = ra.advance(game, seen, a, other)
        if result == "signed":
            return out
        seen = nxt


def _threshold(payload: dict, package: ra.Package, round_: int) -> float:
    game, other = env.game_of(payload)
    return game.threshold(package, other, round_)


def _propose(package: ra.Package, price: float | None = None) -> dict:
    return _act(ra.Action("propose", package, ra.PRICE_IT if price is None else price))


def _classes(move: dict) -> list[str]:
    return [c for c, *_ in move["classes"]]


FIRST = ra.Package("fix_and_delay", "client", "excluded", "at_signing")  # the reference's first request in the client seat
PTA = "price_the_alternatives_2461000"


# ---------------------------------------------------------------------------
# Parts and classes on synthetic moves over committed worlds.


@pytest.mark.parametrize("pack", sorted(PACKS))
def test_the_reference_gives_up_nothing_in_any_part(pack: str) -> None:
    manifest, cases = PACKS[pack]
    for world in manifest["worlds"]:
        for seat in ra.SEATS:
            payload = cases[world["seats"][seat]["case_id"]]["payload"]
            for move in gap.grade_moves(payload, _reference(payload)):
                assert move["regret"] == 0.0 and all(v == 0.0 for v in move["parts"].values()) and not move["classes"]


def test_asking_when_it_should_sign_now_is_the_opening_price() -> None:
    payload = _payload("close_now_2465000", "client")
    best = ra.Package("fix_and_delay", "client", "included", "on_delivery")  # the reference signs this at once
    (move,) = gap.grade_moves(payload, [_propose(best)])
    assert move["parts"]["opening_package"] == 0.0 and move["parts"]["opening_price"] == move["regret"] > 100
    assert _classes(move) == ["asked_when_it_should_have_offered"]


def test_asking_about_the_opening_learns_nothing_so_the_opening_package_is_charged() -> None:
    payload = _payload(PTA, "client")
    (move,) = gap.grade_moves(payload, [_propose(ra.OPENING)])
    assert move["parts"]["opening_package"] == move["regret"] > gap.FLOOR and move["parts"]["opening_price"] == 0.0
    assert _classes(move) == ["opened_with_another_package"]


def test_committing_to_a_price_when_asking_was_better() -> None:
    payload = _payload(PTA, "client")
    game, _ = env.game_of(payload)
    solver = ra.Solver(game)
    types = ra.consistent_types(solver, ra.start(game, env.game_of(payload)[1]))
    price = max(game.threshold(FIRST, t, 1) for t in types)  # every consistent integrator signs
    (move,) = gap.grade_moves(payload, [_propose(FIRST, price)])
    assert move["parts"]["opening_package"] == 0.0 and move["parts"]["opening_price"] > gap.FLOOR
    assert _classes(move) == ["offered_when_it_should_have_asked"]


def test_keeping_the_first_package_after_the_answer_is_the_later_package() -> None:
    payload = _payload(PTA, "client")
    moves = gap.grade_moves(payload, [_propose(FIRST), _propose(FIRST, _threshold(payload, FIRST, 2))])
    later = moves[1]
    assert set(later["parts"]) == {"later_package", "later_price"}
    assert later["parts"]["later_package"] == later["regret"] > gap.FLOOR and later["parts"]["later_price"] == 0.0
    assert _classes(later) == ["kept_its_first_package"]


def test_switching_to_a_package_that_is_not_the_best_one() -> None:
    payload = _payload(PTA, "client")
    other = ra.Package("fix", "client", "excluded", "at_signing")
    moves = gap.grade_moves(payload, [_propose(FIRST), _propose(other, _threshold(payload, other, 2))])
    assert moves[1]["parts"]["later_package"] > gap.FLOOR and _classes(moves[1]) == ["switched_to_the_wrong_package"]


def test_paying_above_the_ask_is_the_later_price() -> None:
    payload = _payload(PTA, "client")
    best = ra.Package("fix_and_delay", "client", "excluded", "on_delivery")
    moves = gap.grade_moves(payload, [_propose(FIRST), _propose(best, _threshold(payload, best, 2) + 50.0)])
    assert moves[1]["parts"]["later_package"] == 0.0
    assert moves[1]["parts"]["later_price"] == pytest.approx(50.0, abs=1e-6)
    assert _classes(moves[1]) == ["offered_a_worse_signing_price"]


def test_taking_the_counter_and_walking_are_accept_or_walk() -> None:
    payload = _payload(PTA, "client")
    took = gap.grade_moves(payload, [_propose(FIRST), {"action": "accept", "package": None, "price": None, "reason": ""}])[1]
    assert set(took["parts"]) == {"accept_or_walk"} and took["parts"]["accept_or_walk"] == took["regret"] > 100
    assert _classes(took) == ["took_a_counter_when_proposing_was_better"]
    (walked,) = gap.grade_moves(payload, [{"action": "walk", "package": None, "price": None, "reason": ""}])
    assert walked["parts"]["accept_or_walk"] > gap.FLOOR and _classes(walked) == ["walked_when_a_deal_was_better"]
    (right,) = gap.grade_moves(_payload("walk_away_2464000", "client"), [{"action": "walk", "package": None, "price": None, "reason": ""}])
    assert right["regret"] == 0.0 and not right["classes"]


def test_proposing_or_accepting_when_walking_was_best() -> None:
    payload = _payload("walk_away_2464001", "client")
    accept = {"action": "accept", "package": None, "price": None, "reason": ""}
    moves = gap.grade_moves(payload, [_propose(FIRST), _propose(FIRST), accept])
    assert _classes(moves[0]) == ["proposed_when_walking_or_accepting_was_best"]
    assert moves[2]["final"] and _classes(moves[2]) == ["accepted_when_walking_was_better"]


def test_a_price_refused_within_the_stated_rounding_is_typed_as_the_defect() -> None:
    payload = _payload(PTA, "integrator")
    best = ra.Package("fix_and_delay", "client", "excluded", "on_delivery")
    ask = _propose(ra.OPENING)
    bid = _threshold(payload, best, 2)
    over = gap.grade_moves(payload, [ask, _propose(best, bid + 0.0005)])[1]
    assert over["parts"]["later_price"] > 25.0 and _classes(over) == ["refused_at_the_stated_price"]
    exact = gap.grade_moves(payload, [ask, _propose(best, bid)])[1]
    assert exact["regret"] == 0.0 and not exact["classes"]
    far = gap.grade_moves(payload, [ask, _propose(best, bid + 5.0)])[1]
    assert _classes(far) == ["asked_when_it_should_have_offered"]


def test_two_prices_a_request_naming_an_alternate_is_a_way_of_proposing_the_package() -> None:
    payload = _payload(PTA, "integrator", "risk_allocation_two_prices_dev_v1")
    moves = gap.grade_moves(payload, [_propose(ra.OPENING), _propose(ra.OPENING)])
    assert moves[1]["best_same"].alternate is not None
    assert moves[1]["parts"]["later_price"] > gap.FLOOR and "asked_the_less_useful_question" in _classes(moves[1])
    both = _act(ra.Action("propose", ra.OPENING, ra.PRICE_IT, ra.Package("fix_and_delay", "client", "excluded", "on_delivery")))
    assert gap.grade_moves(payload, [_propose(ra.OPENING), both])[1]["parts"]["later_price"] == 0.0


def test_round_index_counts_starts_of_the_first_phase() -> None:
    steps = [{"step_index": 0, "phase_id": "negotiate", "phase_instance_id": "a"},
             {"step_index": 1, "phase_id": "negotiate", "phase_instance_id": "b"},
             {"step_index": 2, "phase_id": "negotiate", "phase_instance_id": "c"}]
    assert gap._round_indices(steps) == {0: 0, 1: 1, 2: 2}


def test_a_cell_whose_published_score_does_not_replay_is_refused() -> None:
    data = gap.load()
    row = next(r for r in data["cells"] if r["valid"] is True and r["decision_regret"] > 1.0)
    payload = data["cases"][row["case_id"]]["payload"]
    good = gap.analyse_cell(payload, data["steps"][row["receipt_sha256"]], row)
    assert math.fsum(good["parts"].values()) == pytest.approx(-row["decision_regret"], abs=1e-6)
    with pytest.raises(ValueError):
        gap.analyse_cell(payload, data["steps"][row["receipt_sha256"]], {**row, "decision_regret": row["decision_regret"] + 1.0})


# ---------------------------------------------------------------------------
# The published bundle.


def _reports() -> dict[str, dict]:
    return {p.stem[len("gap_decomposition_"):]: json.loads(p.read_text()) for p in sorted((gap.OUT / "reports").glob("gap_decomposition_*.json"))}


def _cells() -> dict[str, dict]:
    return {r["receipt_sha256"]: r for r in gap._jsonl(gap.EVIDENCE / gap.SOURCE / "tables" / "cells.jsonl")}


def _trajectory() -> dict[str, dict[int, dict]]:
    by: dict[str, dict[int, dict]] = collections.defaultdict(dict)
    for s in gap._jsonl(gap.EVIDENCE / gap.SOURCE / "trajectories" / "sanitized.jsonl"):
        by[s["source_receipt_sha256"]][s["step_index"]] = s
    return by


def test_the_bundle_regenerates_byte_for_byte() -> None:
    assert gap.check()


def test_one_report_per_arm_and_seat_with_enough_pairs_and_the_primary_arm_has_the_most() -> None:
    reports = _reports()
    cells = list(_cells().values())
    by = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in cells:
        by[(r["arm"], r["seat"])][r["world"]][r["route_id"]] = r
    pairs = {k: sum(all(d.get(m, {}).get("valid") for _, m in gap.ROUTES) for d in v.values()) for k, v in by.items()}
    assert set(reports) == {f"{a}_{s}" for (a, s), n in pairs.items() if n >= gap.MIN_PAIRS}
    assert {r["comparison"]["arm"] for r in reports.values() if r["comparison"]["primary"]} == {"one_price_low"}
    assert all(r["paired_worlds"] == pairs[(r["comparison"]["arm"], r["comparison"]["seat"])] for r in reports.values())
    assert all((r["bootstrap"] is None) == (r["clusters"] < gap.MIN_CLUSTERS_FOR_INTERVAL) for r in reports.values())


def test_parts_sum_to_the_published_decision_regret_per_cell_and_to_the_gap() -> None:
    cells = _cells()
    for report in _reports().values():
        assert report["schema_version"] == "aeread.gap_decomposition/0.1" and report["direction"] == "higher"
        for cell in report["cell_parts"]:
            assert math.fsum(cell["parts"].values()) == pytest.approx(-cells[cell["receipt_sha256"]]["decision_regret"], abs=1e-5)
        for side in ("left", "right"):
            published = [cells[c["receipt_sha256"]]["decision_regret"] for c in report["cell_parts"] if c["side"] == side]
            assert report["realized"][side] == pytest.approx(-math.fsum(published) / len(published), abs=1e-6)
        assert math.fsum(c["difference"] for c in report["components"]) == pytest.approx(report["realized"]["difference"], abs=1e-5)
        assert report["accounting_check"]["max_abs_residual_per_cell"] < 1e-6
        graded = sum(1 for c in cells.values() if c["valid"] is not None)  # every episode that ended on a move
        assert report["replay_check"] == {**report["replay_check"], "cells": graded, "mismatches": 0}


def test_the_primary_means_are_the_campaign_s_published_means() -> None:
    summary = json.loads((gap.EVIDENCE / gap.SOURCE / "reports" / "summary.json").read_text())["groups"]
    for seat in ra.SEATS:
        report = _reports()[f"one_price_low_{seat}"]
        for side, route in gap.ROUTES:
            assert -report["realized"][side] == pytest.approx(summary[f"one_price_low/{route}/{seat}"]["mean_decision_regret"], abs=5e-4)


def test_contribution_rows_add_up_and_land_on_the_move_they_describe() -> None:
    trajectory = _trajectory()
    for suffix, report in _reports().items():
        rows = gap._jsonl(gap.OUT / report["contributions"]["table"])
        assert len(rows) == report["contributions"]["rows"]
        sums: collections.Counter = collections.Counter()
        for row in rows:
            sums[(row["receipt_sha256"], row["component"])] += row["amount"]
            steps = trajectory[row["receipt_sha256"]]
            step = steps[row["step_index"]]
            assert (step["phase_id"], step["seat_id"]) == (row["phase_id"], row["seat_id"])
            assert row["round_index"] == gap._round_indices([steps[i] for i in sorted(steps)])[row["step_index"]]
            assert step["outcome"]["valid"] is True
            action = env._action(step["action"])
            assert gap.move_label(action) == row["move"]
            first = min(i for i, s in steps.items() if s["outcome"]["valid"] is True)
            if row["component"] == "accept_or_walk":
                assert action.kind in ("accept", "walk")
            else:
                assert action.kind == "propose" and (row["step_index"] == first) == row["component"].startswith("opening_")
        for cell in report["cell_parts"]:
            for key, value in cell["parts"].items():
                assert sums[(cell["receipt_sha256"], key)] == pytest.approx(value, abs=1e-5)


def test_every_instance_names_a_real_step_and_the_stated_price_defect_is_counted_once() -> None:
    trajectory = _trajectory()
    stated = 0
    for report in _reports().values():
        keys = {c["key"] for c in report["classes"]}
        for inst in report["instances"]:
            assert inst["class"] in keys and inst["note"]
            step = trajectory[inst["receipt_sha256"]][inst["step_index"]]
            assert (step["phase_id"], step["seat_id"]) == (inst["phase_id"], inst["seat_id"])
            stated += inst["class"] == "refused_at_the_stated_price"
        for cls in report["classes"]:
            assert cls["left_count"] == sum(1 for i in report["instances"] if i["class"] == cls["key"] and i["side"] == "left")
    assert stated == 4  # DC-D-25: 4 of the campaign's 341 accepted moves, all in paired integrator cells


def test_every_published_file_passes_the_prohibited_text_scan() -> None:
    for path in sorted(gap.OUT.rglob("*")):
        if path.is_file():
            assert_public_payload(str(path.relative_to(gap.OUT)), path.read_bytes())
