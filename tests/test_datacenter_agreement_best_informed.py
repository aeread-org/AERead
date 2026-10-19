"""The best informed policy turn by turn (``agreement_best_informed``), Gate 3's reference for the agreement case.

What has to hold for its loss by turn to mean what ``docs/families/datacenter/agreement_case.md`` says it means:

1. The cached script makes the original script's move on every state the search asks it about.
2. Restricted to ``agreement_own_information``'s class of moves, the search reproduces that module's values, and its
   own wider class never does worse.
3. The plan, played against the original script with each type the seat cannot rule out, earns what the search says.
4. The best informed policy loses nothing against itself, turn by turn.
5. A sealed confirmatory negotiation replays to the surplus its cell records, and a script move the script would not
   have made is refused.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_best_informed as bi
from aeread_families.datacenter_development import agreement_own_information as oi
from aeread_families.datacenter_development import risk_allocation_contracts as rc

ROOT = Path(__file__).resolve().parents[1]
WORLD = "0064cc63"  # three live types in each seat; the first world of the admitted pack


@pytest.fixture(scope="module")
def world():
    _, cases, _ = aap.load()
    payload = next(c["payload"] for c in cases.values() if c["case_id"].endswith(WORLD))
    return rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})


@pytest.fixture(scope="module")
def client_seat(world):
    seat = bi.Seat(*world, "client")
    return seat, bi.plan_values(seat)


def test_the_cached_script_moves_as_the_original(client_seat) -> None:
    seat, _ = client_seat
    assert bi.check_script(seat, every=1) == len(seat.visited) > 0


def test_restricted_to_its_moves_the_search_reproduces_own_information(world, monkeypatch) -> None:
    cw, it = world
    original, store = ag.costs, {}

    def fast_costs(cw, it, c):  # the same numbers, computed once per (world, type, agreement), so the test runs in seconds
        k = (id(cw), id(it), c)
        if k not in store:
            store[k] = original(cw, it, c)
        return store[k]

    scripts: dict = {}

    def fast_move(state, cw, it, style):  # the cached script, which the first test holds to the original's moves
        k = (id(cw), state["to_move"], id(it), style)
        if k not in scripts:
            scripts[k] = bi.FastNegotiator(cw, state["to_move"], it if state["to_move"] == "integrator" else None, style)
        return scripts[k].move(state)

    monkeypatch.setattr(ag, "costs", fast_costs)
    monkeypatch.setattr(oi.an, "negotiator_move", fast_move)
    theirs = oi.own_information(cw, it)
    assert (theirs["expected"], theirs["at_true"], theirs["full_information_grid"]) == (173.536, 381.982, 381.982)  # as the original script gives
    seat = bi.Seat(cw, it, "integrator")
    cw_by = {h.cw.w.client.risk_charge: h.cw for h in seat.hyps.values()}
    label = {f"charge={c:g}": c for c in cw_by}
    mine = bi.plan_values(seat, moves=lambda labels, state: oi.options(state, cw_by, it, [label[x] for x in labels]))
    assert mine["expected"] == pytest.approx(theirs["expected"], abs=1e-3)
    assert mine["at_true"] == pytest.approx(theirs["at_true"], abs=1e-3)
    assert mine["told_the_type"] == pytest.approx(theirs["full_information_grid"], abs=1e-3)
    wider = bi.plan_values(seat)
    assert wider["expected"] >= mine["expected"] - 1e-6


def test_the_plan_earns_its_values_against_the_original_script(client_seat) -> None:
    seat, plan = client_seat
    for label in seat.hyps:
        assert bi.replay(seat, label)[0] == pytest.approx(plan["by_type"][label], abs=1e-6)


def _policy_moves(seat: bi.Seat) -> list[dict]:
    """The best informed policy against the true type's script, every move in order."""
    solver = bi.Solver(seat)
    h = seat.hyps[seat.true_label]
    state, live, moves = ag.initial_state(h.cw), sorted(seat.hyps), []
    while not state["finished"]:
        if state["to_move"] == seat.seat:
            act = solver.solve(state, live)[1]
        else:
            act = seat.script_move(seat.true_label, state)
            live = [x for x in live if seat.script_move(x, state) == act]
        moves.append(act)
        state = ag.apply(state, act, h.cw)
    return moves


def test_the_best_informed_policy_loses_nothing_against_itself(client_seat) -> None:
    seat, plan = client_seat
    got = bi.loss_by_turn(seat, _policy_moves(seat))
    assert got["turns"] and all(t["loss"] == pytest.approx(0.0, abs=1e-6) for t in got["turns"])
    assert got["earned"] == pytest.approx(plan["at_true"], abs=1e-6)


def test_a_sealed_negotiation_replays_to_its_recorded_surplus(client_seat) -> None:
    seat, plan = client_seat
    sealed = bi.sealed_negotiations(ROOT)[(WORLD, "client")]
    assert len(sealed) == 2
    for n in sealed:
        got = bi.loss_by_turn(seat, n["moves"])
        assert got["earned"] == pytest.approx(n["recorded_surplus"], abs=1e-6)
        assert got["loss"] >= -1e-6 or any(t["loss"] < 0 for t in got["turns"])  # a move outside the class may beat it
    tampered = copy.deepcopy(sealed[0]["moves"])
    first_script = next(i for i, m in enumerate(tampered) if i % 2 == 0)  # the integrator script opens
    tampered[first_script]["price"] += 5.0
    with pytest.raises(AssertionError, match="not the script's"):
        bi.loss_by_turn(seat, tampered)


def test_the_one_step_agreement_is_never_better_than_the_best(world) -> None:
    for name in ag.SEATS:
        seat = bi.Seat(*world, name)
        for labels in (sorted(seat.hyps), [seat.true_label]):
            got = bi.one_step(seat, labels)
            assert got["best_value"] >= got["one_step_value"] - 1e-6
            assert got["best_value"] >= got["draft_value"] - 1e-6
            assert got["matches"] == (abs(got["best_value"] - got["one_step_value"]) <= 1e-6)
