"""The scripted negotiator: what it may read, what it never does, and that the other side's moves change what it does."""

from __future__ import annotations

from dataclasses import replace

import pytest

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import agreement_negotiator_check as check
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import risk_allocation_contracts as rc


def _worlds(n: int = 12):
    _, raw = ap.load("agreement_dev_v1")
    out = []
    for c in sorted(raw.values(), key=lambda c: c["case_id"])[:n]:
        out.append(rc.world_from({k: c["payload"][k] for k in ("world", "integrator_type", "extras")}))
    return out


def _self_play(cw, it, style):
    state = ag.initial_state(cw)
    while not state["finished"]:
        state = ag.apply(state, an.negotiator_move(state, cw, it, style), cw)
    return state


def test_the_clients_script_is_not_given_the_integrators_type():
    cw, it = _worlds(1)[0]
    with pytest.raises(ValueError):
        an.Negotiator(cw, "client", it)
    with pytest.raises(ValueError):
        an.Negotiator(cw, "integrator", None)


def test_the_clients_script_plays_the_same_whichever_declared_type_it_faces():
    for cw, it in _worlds():
        if len(cw.types) < 2:
            continue
        opening = {"action": "redline", "clauses": {k: None for k in ag.TERMS}, "price": cw.best_outside[1] - 200.0, "note": None}
        state = ag.apply(ag.initial_state(cw), opening, cw)
        assert state["to_move"] == "client"
        moves = {str(an.negotiator_move(state, cw, t, an.DRAWN)) for t in cw.types}
        assert len(moves) == 1


@pytest.mark.parametrize("style", [*an.STYLES, an.DRAWN])
def test_it_never_signs_below_its_outside_option_and_walks_when_there_is_no_deal(style):
    for cw, it in _worlds():
        g = ag.grade(cw, it, _self_play(cw, it, style))
        assert not g["client_ir_violation"] and not g["integrator_ir_violation"]
        if g["available_surplus"] <= 1e-6:
            assert g["termination"] == "walked"


def test_the_drawn_style_depends_on_the_world_and_seat_only_and_stays_in_the_population():
    seen = set()
    for cw, _ in _worlds():
        for seat in ag.SEATS:
            st = an.drawn_style(cw, seat)
            assert st == an.drawn_style(cw, seat)
            lo, hi = an.POPULATION["opening"]
            assert lo <= st.opening <= hi and an.POPULATION["final_at_least"] <= st.final <= st.opening
            assert an.POPULATION["least"][0] <= st.least <= an.POPULATION["least"][1] and st.reciprocity in an.POPULATION["reciprocity"]
            seen.add(st)
    assert len(seen) > 12


def _ask_after(cw, it, style, client_shares):
    """The integrator script's asks when the client answers each of its offers with these shares of the true surplus for itself."""
    me = check.Informed(cw, it, "client")
    script = an.Negotiator(cw, "integrator", it, style)
    state, asks = ag.initial_state(cw), []
    for share in [*client_shares, None]:
        asks.append(script._ask(state, script.belief(state)))
        act = script.move(state)
        if act["action"] != "redline" or share is None:
            break
        state = ag.apply(state, act, cw)
        state = ag.apply(state, me.ask(state, share), cw)
    return asks


def test_a_side_that_does_not_move_gets_nothing_for_waiting_and_one_that_moves_is_met():
    cw, it = next((cw, it) for cw, it in _worlds() if check.Informed(cw, it, "client").available > 100)
    style = an.Style(opening=0.9, final=0.5, least=0.1, reciprocity=1.0)
    still = _ask_after(cw, it, style, [0.6, 0.6])
    moving = _ask_after(cw, it, style, [0.6, 0.4])
    clock = _ask_after(cw, it, replace(style, reciprocity=0.0), [0.6, 0.6])
    assert len(still) == len(moving) == len(clock) == 3
    assert still[2] == pytest.approx(still[1])  # the client repeated itself: no further step
    assert moving[2] < still[2] - 0.05  # the client came toward it: it comes down
    assert clock[2] < clock[1] < clock[0]  # at reciprocity 0 it comes down on the clock
    assert min(still + moving + clock) >= style.final - 1e-9


def test_it_refuses_a_last_move_ultimatum_below_its_least_share_and_signs_above_it():
    cw, it = next((cw, it) for cw, it in _worlds() if check.Informed(cw, it, "integrator").available > 100)
    me = check.Informed(cw, it, "integrator")
    for share, action in ((0.97, "walk"), (0.5, "sign")):
        state = ag.initial_state(cw)
        for _ in range(2):  # the integrator holds, the client's script answers, twice
            state = ag.apply(state, me.ask(state, 0.97), cw)
            state = ag.apply(state, {"action": "redline", "clauses": {k: None for k in ag.TERMS}, "price": state["standing"]["price"] - 1.0, "note": None}, cw)
        state = ag.apply(state, me.ask(state, share), cw)
        assert ag.is_final(state)
        assert an.Negotiator(cw, "client", None, an.Style(opening=0.6, final=0.5, least=0.3)).move(state)["action"] == action


def test_the_other_sides_plan_changes_what_it_earns_and_holding_out_is_not_the_best_plan():
    cw, it = next((cw, it) for cw, it in _worlds() if check.Informed(cw, it, "client").available > 100)
    earned = {plan: check.surplus(cw, it, check.play(cw, it, "client", an.DRAWN, plan), "client") for plan in check.PLANS}
    best, path, _ = check.best_plan(cw, it, "client", an.DRAWN)
    assert len({round(v, 3) for v in earned.values()}) >= 3
    assert best >= max(earned.values()) - 1e-6
    assert best > earned["never comes down"] + 1.0


def _first_deal_world(seat):
    return next((cw, it) for cw, it in _worlds() if check.Informed(cw, it, seat).available > 100)


def test_overreach_opens_with_an_offer_no_declared_type_could_sign_and_ends_with_one_that_can_be():
    cw, it = _first_deal_world("client")
    script = an.Negotiator(cw, "integrator", it, "overreach")
    state = ag.initial_state(cw)
    first = script.move(state)
    state = ag.apply(state, first, cw)
    me = an.Negotiator(cw, "client", None, "even")
    assert all(me.surplus(rc.Contract(**state["terms"]), first["price"], o)[0] < 0 for o in me.prior)
    for _ in range(2):  # the client holds at an even split; the script comes down on the clock
        state = ag.apply(state, check.Informed(cw, it, "client").ask(state, 0.5), cw)
        act = script.move(state)
        if act["action"] != "redline":
            break
        state = ag.apply(state, act, cw)
    assert act["action"] == "sign" or check.Informed(cw, it, "client").worth(state) > 0


def test_price_only_never_touches_a_clause_and_prices_the_clauses_the_other_side_sets():
    for seat in ag.SEATS:
        cw, it = _first_deal_world(ag.other(seat))
        state = ag.initial_state(cw)
        if seat == "client":
            state = ag.apply(state, check.Informed(cw, it, "integrator").ask(state, 0.9), cw)
        act = an.negotiator_move(state, cw, it, "price_only")
        assert act["action"] == "redline" and all(v is None for v in act["clauses"].values())


def test_collapse_holds_its_ask_then_drops_it_on_its_last_proposal():
    cw, it = _first_deal_world("client")
    asks = _ask_after(cw, it, "collapse", [0.9, 0.9])
    assert asks == [0.9, 0.9, 0.3]
