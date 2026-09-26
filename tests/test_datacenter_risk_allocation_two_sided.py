"""The two-sided risk-allocation case: both seats players, graded on the exact outcome.

The grader is checked against a full-information oracle that must lose nothing on
every world; the protocol (alternation, legality, round costs, break-off) on hand-built
move sequences; the kernel path on scripted pairings, whose receipts must seal and replay.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_two_sided as ts
from aeread_families.datacenter_development import risk_allocation_two_sided_campaign as tc
from aeread_families.datacenter_development import risk_allocation_two_sided_pack as tp
from aeread_families.datacenter_development.risk_allocation_two_sided_environment import TwoSidedPlugin, parse_move, world_and_type


def _worlds():
    _, cases = tp.load(tc.PACK)
    return [c["payload"] for c in sorted(cases.values(), key=lambda c: c["case_id"])]


def _play(payload, policy):
    w, it = world_and_type(payload)
    st = ts.initial_state(w)
    while not st["finished"]:
        st = ts.apply(st, parse_move(ts.POLICIES[policy](st, w, it)).action, w, payload["breakoff_draws"])
    return w, it, st


def test_the_oracle_loses_nothing_on_every_world_and_the_loss_splits_exactly() -> None:
    for payload in _worlds():
        w, it, st = _play(payload, "oracle")
        g = ts.grade_two_sided(w, it, st)
        assert g["joint_value_lost"] == 0.0 and not g["client_ir_violation"] and not g["integrator_ir_violation"]
        assert (g["signed_package"] is not None) == (g["available_surplus"] > 0)
        _, _, rule = _play(payload, "rule")
        r = ts.grade_two_sided(w, it, rule)
        assert r["joint_value_lost"] == pytest.approx(r["allocation_loss"] + r["no_deal_loss"] + r["delay_loss"], abs=1e-6)
        assert r["joint_value_lost"] >= -1e-9


def _world():
    payload = _worlds()[0]
    w, it = world_and_type(payload)
    return payload, w, it


def _propose(pkg, price):
    return {"action": "propose", "package": pkg.as_dict(), "price": price, "reason": ""}


def test_moves_alternate_and_a_refused_proposal_costs_its_proposer_a_round() -> None:
    payload, w, it = _world()
    draws = [0.99] * ts.max_moves(w)  # no break-off
    st = ts.initial_state(w)
    assert st["to_move"] == "integrator"
    st = ts.apply(st, _propose(ra.OPENING, 11000.0), w, draws)
    assert st["to_move"] == "client" and st["standing"]["by"] == "integrator"
    st = ts.apply(st, _propose(ra.EVERY_PROTECTION, None), w, draws)  # a price request, refusing the opening
    assert st["round_costs"] == {"client": 0.0, "integrator": w.terms.round_cost}
    assert st["standing"] is None and st["request"]["package"] == ra.EVERY_PROTECTION.as_dict()
    st = ts.apply(st, _propose(ra.EVERY_PROTECTION, 12000.0), w, draws)
    assert st["round_costs"]["client"] == w.terms.round_cost
    st = ts.apply(st, {"action": "accept", "package": None, "price": None, "reason": ""}, w, draws)
    assert st["termination"] == "signed" and st["signed"]["price"] == 12000.0 and st["signed"]["offered_by"] == "integrator"
    g = ts.grade_two_sided(w, it, st)
    assert g["delay_loss"] == pytest.approx(2 * w.terms.round_cost)


def test_a_breakoff_draw_below_the_worlds_probability_ends_the_negotiation() -> None:
    payload, w, it = _world()
    draws = [0.99, 0.0] + [0.99] * (ts.max_moves(w) - 2)
    st = ts.apply(ts.initial_state(w), _propose(ra.OPENING, 11000.0), w, draws)
    st = ts.apply(st, _propose(ra.OPENING, 10500.0), w, draws)
    assert st["termination"] == "broke_off" and st["signed"] is None


def test_legality_accept_needs_a_standing_offer_the_final_move_cannot_propose_and_only_the_mover_moves() -> None:
    payload, w, _ = _world()
    plugin = TwoSidedPlugin()
    st = plugin.initial_state(payload, None)
    accept = {"action": "accept", "package": None, "price": None, "reason": ""}
    assert plugin.legal(payload, st, "integrator", None, accept).reason == "nothing_to_accept"
    assert plugin.legal(payload, st, "client", None, _propose(ra.OPENING, 1.0)).reason == "not_your_move"
    final = {**st, "move": st["moves"], "to_move": "client"}
    assert plugin.legal(payload, final, "client", None, _propose(ra.OPENING, 1.0)).reason == "final_answer_only"


def test_each_brief_shows_the_other_side_only_as_the_prior() -> None:
    payload, w, it = _world()
    other_type = next(t for t, _ in w.prior if t != it)
    assert ts.brief(w, "client") == ts.brief(w, "client")  # the client's brief takes no integrator type at all
    other_charge = next(c for c, _ in w.client_prior if c != w.client.risk_charge)
    w2 = replace(w, client=replace(w.client, risk_charge=other_charge))
    assert ts.brief(w, "integrator", it) == ts.brief(w2, "integrator", it)
    assert ts.brief(w, "integrator", it) != ts.brief(w, "integrator", other_type)
    obs = TwoSidedPlugin().observe(payload, TwoSidedPlugin().initial_state(payload, None), "client", None)
    assert not {"world", "integrator_type", "breakoff_draws"} & set(obs)


@pytest.mark.parametrize("pairing", ["oracle_client_oracle_integrator", "rule_client_rule_integrator"])
def test_scripted_pairings_seal_verified_replayable_receipts(tmp_path: Path, pairing: str) -> None:
    setup = tc.build_setup(pairing, tc._cases()[:2])
    entry = {"pairing": pairing, "client_route": tc.PAIRINGS[pairing][0], "integrator_route": tc.PAIRINGS[pairing][1]}
    for cell in setup.plan.cells:
        record = asyncio.run(tc._run_cell(tmp_path, entry, setup, cell, tc.oc.Spend(1.0), asyncio.Semaphore(1)))
        assert record["status"] == "ok" and record["grade"]["valid"], record
        if pairing.startswith("oracle"):
            assert record["grade"]["joint_value_lost"] == 0.0


def test_model_pairings_resolve_with_both_seats_and_shared_request_seeds() -> None:
    setup = tc.build_setup("gemini_client_glm_integrator", tc._cases()[:2])
    profiles = {p.profile_id: p for p in setup.plan.agent_profiles}
    assert len(profiles) == 2 and {p.model.model for p in profiles.values()} == {"google/gemini-3.8-flash", "z-ai/glm-5.3-flash"}
    for p in profiles.values():
        assert p.harness.config["request_seed_source"] == "paired_cell_v1" and p.retry_policy.max_action_attempts == 4
    assert sorted(c.replicate_index for c in setup.plan.cells) == [0, 0, 1, 1]
    assert {c.profile_by_seat["client"] for c in setup.plan.cells} != {c.profile_by_seat["integrator"] for c in setup.plan.cells}


def test_the_pack_pairs_with_the_one_sided_eval_pack() -> None:
    manifest, cases = tp.load(tc.PACK)
    assert len(cases) == 32
    for world in manifest["worlds"]:
        case = cases[world["case_id"]]
        assert case["payload"]["breakoff_draws"][:2] == json.loads(
            (Path(tp.REPOSITORY_ROOT) / "cases" / "datacenter_risk_allocation_v1" / "risk_allocation_eval_v1"
             / f"{world['one_sided_case_ids']['client']['case_id'].rsplit('.', 1)[-1]}.json").read_text())["payload"]["breakoff_draws"]
