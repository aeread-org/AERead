"""The one-move counterpart and the counterparts that read a client's first offer."""

from __future__ import annotations

import pytest

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import agreement_reader as rd
from aeread_families.datacenter_development import risk_allocation_contracts as rc


def _worlds(pack="agreement_confirm_v1", n=10):
    _, raw = ap.load(pack)
    return [rc.world_from({k: c["payload"][k] for k in ("world", "integrator_type", "extras")}) for c in sorted(raw.values(), key=lambda c: c["case_id"])[:n]]


def test_the_confirmatory_worlds_are_none_of_the_development_worlds():
    _, dev = ap.load("agreement_dev_v1")
    _, fresh = ap.load("agreement_confirm_v1")
    content = lambda cases: {str(sorted((k, str(c["payload"][k])) for k in ("world", "integrator_type", "extras"))) for c in cases.values()}
    assert len(fresh) == 58 and not content(dev) & content(fresh)


def test_a_swap_pack_changes_one_private_number_and_nothing_else():
    for pack, seat in (("agreement_confirm_swap_client_v1", "client"), ("agreement_confirm_swap_integrator_v1", "integrator")):
        _, raw = ap.load(pack)
        by_world = {}
        for c in raw.values():
            by_world.setdefault(c["world_seed"], []).append(c)
        assert all(len(v) == 2 for v in by_world.values())
        for a, b in by_world.values():
            cwa, ita = rc.world_from({k: a["payload"][k] for k in ("world", "integrator_type", "extras")})
            cwb, itb = rc.world_from({k: b["payload"][k] for k in ("world", "integrator_type", "extras")})
            mine = [x for x, y in zip(ag.brief(cwa, seat, ita if seat == "integrator" else None).splitlines(), ag.brief(cwb, seat, itb if seat == "integrator" else None).splitlines()) if x != y]
            other = ag.other(seat)
            assert len(mine) == 1
            assert ag.brief(cwa, other, ita if other == "integrator" else None) == ag.brief(cwb, other, itb if other == "integrator" else None)
            assert ag.draft(cwa) == ag.draft(cwb)


def test_the_one_move_counterpart_opens_the_same_whichever_type_the_client_is_given():
    _, raw = ap.load("agreement_confirm_swap_client_v1")
    by_world = {}
    for c in raw.values():
        by_world.setdefault(c["world_seed"], []).append(rc.world_from({k: c["payload"][k] for k in ("world", "integrator_type", "extras")}))
    for (cwa, ita), (cwb, itb) in by_world.values():
        assert rd.first_move_only(ag.initial_state(cwa), cwa, ita) == rd.first_move_only(ag.initial_state(cwb), cwb, itb)


def test_the_one_move_counterpart_opens_as_the_firm_script_and_then_walks():
    for cw, it in _worlds():
        state = ag.initial_state(cw)
        first = rd.first_move_only(state, cw, it)
        assert first == an.negotiator_move(state, cw, it, rd.FIRST_MOVE_STYLE)
        if first["action"] != "redline":
            continue
        state = ag.apply(state, first, cw)
        assert rd.first_move_only(state, cw, it)["action"] == "walk"  # in the client's seat
        state = ag.apply(state, {"action": "redline", "clauses": {k: None for k in ag.TERMS}, "price": first["price"] - 100.0, "note": None}, cw)
        assert rd.first_move_only(state, cw, it)["action"] == "walk"


@pytest.mark.parametrize("model", sorted(rd.FITTED))
def test_a_reader_plays_the_firm_script_until_the_client_offers_and_then_leans_the_way_the_offer_points(model):
    cw, it = next((cw, it) for cw, it in _worlds(n=30) if an.negotiator_move(ag.initial_state(cw), cw, it, an.DRAWN)["action"] == "redline")
    state = ag.initial_state(cw)
    for channel in rd.CHANNELS:
        assert rd.reader_move(state, cw, it, channel, model) == an.negotiator_move(state, cw, it, an.DRAWN)
    opened = ag.apply(state, an.negotiator_move(state, cw, it, an.DRAWN), cw)
    charges = sorted(c for c, _ in cw.w.client_prior)
    most = {"warranty": "fix_and_delay", "damages": "200", "liability_cap": "uncapped", "readiness": "integrator", "consequential": "included", "burn_in": True}
    asks_all = ag.apply(opened, {"action": "redline", "clauses": {k: most.get(k) for k in ag.TERMS}, "price": opened["standing"]["price"], "note": None}, cw)
    reader = rd.Reader(cw, it, "clauses", model)
    belief = {o.charge: o.p for o in reader.belief(asks_all)}
    assert abs(sum(belief.values()) - 1.0) < 1e-9
    assert belief.get(charges[-1], 0.0) > belief.get(charges[0], 0.0)  # asking for every protection points at the highest charge
    high = ag.apply(opened, {"action": "redline", "clauses": {k: None for k in ag.TERMS}, "price": opened["standing"]["price"] - 5.0, "note": None}, cw)
    low = ag.apply(opened, {"action": "redline", "clauses": {k: None for k in ag.TERMS}, "price": opened["standing"]["price"] - 600.0, "note": None}, cw)
    price = rd.Reader(cw, it, "price", model)
    at = lambda s: {o.charge: o.p for o in price.belief(s)}.get(charges[-1], 0.0)
    assert at(high) >= at(low)  # a higher bid makes the charge that can pay most at least as likely


def test_a_reader_never_signs_below_its_walk_away_point():
    for cw, it in _worlds():
        for channel in rd.CHANNELS:
            state = ag.initial_state(cw)
            while not state["finished"]:
                act = rd.reader_move(state, cw, it, channel, "claude") if state["to_move"] == "integrator" else an.negotiator_move(state, cw, it, "soft")
                state = ag.apply(state, act, cw)
            assert not ag.grade(cw, it, state)["integrator_ir_violation"]
