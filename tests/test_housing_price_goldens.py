"""Goldens for the v14 price market (Gate 2 of the QC standard): the five kinds, on the real market.

Every golden drives the sealed offline market (``price_reference.run_world``, or the
``HousingMarket`` phases it calls, with the price landlord and the outside-demand seats) or, for
the malformed golden, the full kernel path (``price_campaign.run`` on a v14 contract with a
stand-in for the paid client). Worlds are v14 pack worlds; every expected number is derived in
the test from the world's own values, costs and asks, not copied from a run.

1. successful: a legal trajectory realizes a known outcome with exact accounting;
2. valid but poor: a legal blind lemon signing stays valid and keeps its components;
3. invalid or unauthorized: actions the market must refuse change no protected state and earn
   nothing;
4. malformed or operational failure: malformed output becomes typed invalidity applied as a pass,
   and an infrastructure failure becomes typed missingness, never a zero;
5. degenerate reference: a $0-ceiling cell under ``price_controls.ZERO_CEILING_RULE``.

Each golden has a counterexample that shows the check can fail.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons, price_bargaining, price_campaign, price_controls, price_endpoint
from aeread_families.housing import price_publication as pp
from aeread_families.housing import price_reference as pr
from aeread_families.housing import price_reply_posterior as post

ROOT = Path(__file__).resolve().parents[1]
GLM = "housing_lemons_price_confirmatory_v14_glm53_flash_nextbit"
SEAT = pr.FOCAL_SEAT


def _protected(market: hz.HousingMarket) -> tuple[Any, ...]:
    """The state an invalid seat-0 action must not move."""
    return (sorted(market.pairs), dict(market.signed_rent), dict(market.inspection_spend),
            {t: dict(v) for t, v in market.inspected.items()}, market.open_listings(),
            json.dumps(market.commit_decisions, sort_keys=True), pr.seat_net(market))


def _target(world: lemons.LemonsWorld, listing: int) -> float:
    """The price landlord's counter target, by its rule, from the reservation it uses."""
    reservation = world.reservation_cost(listing)
    return round(max(reservation, min(float(world.ask[listing]), reservation + price_bargaining.LANDLORD_MARGIN)), 2)


# --- 1. successful ----------------------------------------------------------------------------

@pytest.mark.parametrize("seed, listing", [(300000, 1), (300003, 3)])
def test_successful_reference_trajectory_has_exact_accounting(seed: int, listing: int) -> None:
    # 300000: the reference inspects listing 1 (sound) in round 0, offers $0, is countered at the
    # sound floor and signs. 300003: it inspects listing 3, a lemon, and signs it at the leaky
    # landlord's own floor (lemon cost plus $25), which leaves it the same surplus.
    market = pr.run_world(seed, "true_cost", pr.inspect_lowball_action)
    world = market.world
    target = _target(world, listing)
    assert dict(market.pairs)[SEAT] == listing and market.signed_rent[SEAT] == target
    assert market.inspected[SEAT] == {listing: world.quality[listing]}
    expected = round(float(world.values[SEAT][listing]) - target - world.inspection_cost, 2)
    assert pr.seat_net(market) == expected
    # The full-information ceiling is the same lease without the fee.
    assert pr.ceiling(seed, "true_cost") == round(expected + world.inspection_cost, 2)
    economics = market.economics()
    assert economics.tenant_payoffs[SEAT] == round(float(world.values[SEAT][listing]) - target, 2)
    assert economics.landlord_payoffs[listing] == round(target - float(world.costs[listing]), 2) == 25.0
    accounting = market.lemons_accounting()
    assert accounting["tenant_net_payoffs"][SEAT] == expected
    # The endpoint's decomposition sums to the realized total with no residual.
    scored = price_endpoint.score_cell({k: accounting[k] for k in price_endpoint.OUTCOME_FACTS},
                                       world_seed=seed, arm="true_cost")
    assert scored["residual"] == 0.0
    assert scored["by_seat"][SEAT]["net_realized"] == scored["by_seat"][SEAT]["net_expected_response_odds"] == expected
    # Outside seats never inspect, so seat 0's lease is the market's only informed one.
    assert scored["parts"]["informed_leases"] == round(expected + world.inspection_cost, 2)


def test_successful_counterexample_a_wrong_rent_breaks_the_accounting(monkeypatch) -> None:
    # Counterexample: a landlord that counters $1 above its rule moves the realized net off the
    # hand-computed one, so the check above is not true by construction.
    original = price_bargaining.landlord_action

    def greedy(observation):
        action = original(observation)
        return {**action, "counter_rent": action["counter_rent"] + 1.0} if action["decision"] == "counter" else action

    monkeypatch.setattr(price_bargaining, "landlord_action", greedy)
    market = pr.run_world(300000, "true_cost", pr.inspect_lowball_action)
    world = market.world
    assert pr.seat_net(market) != round(float(world.values[SEAT][1]) - _target(world, 1) - world.inspection_cost, 2)


# --- 2. valid but poor ------------------------------------------------------------------------

def test_valid_but_poor_blind_lemon_signing_keeps_its_components() -> None:
    # 300002 leaky arm: sign_anything never inspects, offers $1 over the ask on its favourite
    # (listing 1, a lemon) and signs. The offer is at the sound floor or above, so the reply says
    # nothing; the stated odds are 2 of 4.
    seed, arm, listing = 300002, "true_cost", 1
    market, trajectory = post.run_recorded(seed, arm, lemons.sign_anything_action)
    world = market.world
    assert world.quality[listing] == lemons.LEMON and dict(market.pairs)[SEAT] == listing
    rent = market.signed_rent[SEAT]
    assert rent == world.ask[listing] + 1.0 >= price_endpoint.sound_floor(world, listing)
    assert market.inspection_spend[SEAT] == 0.0 and trajectory.inspections == {}
    realized = round(float(world.values[SEAT][listing]) - rent, 2)
    assert realized < 0 and pr.seat_net(market) == realized
    assert "tenant:0" in market.economics().ir_violations
    decision = next(d for d in market.commit_decisions if d["tenant_id"] == SEAT)
    expected_value = round(float(world.values_if_sound[SEAT][listing]) - 0.5 * world.lemon_loss, 2)
    assert (decision["informed"], decision["quality"], decision["expected_value"]) == (False, "lemon", expected_value)
    accounting = market.lemons_accounting()
    scored = price_endpoint.score_cell({k: accounting[k] for k in price_endpoint.OUTCOME_FACTS}, world_seed=seed, arm=arm)
    seat = scored["by_seat"][SEAT]
    assert seat["net_realized"] == realized
    assert seat["net_expected_stated_odds"] == seat["net_expected_response_odds"] == round(expected_value - rent, 2)
    assert seat["reply_leak_expected_loss"] == 0.0 and seat["signed_blind"] == 1
    # v2 agrees: an acceptance at or above the floor is uninformative.
    assert post.score_market(market, trajectory)["primary_v2"] == seat["net_expected_response_odds"]


# --- 3. invalid or unauthorized ---------------------------------------------------------------

def _invalid_policy(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """Every phase, an action the market must refuse."""
    round_index = int(observation["round_index"])
    if phase_id == "inspect":
        return {"decision": "inspect", "listing_id": (99, True, -1)[round_index % 3]}
    if phase_id == "contact":
        return {"decision": "offer", "listing_id": 1, "rent": (-5.0, math.nan, math.inf)[round_index % 3]}
    return lemons._pass(phase_id)


def test_invalid_actions_change_no_protected_state_and_earn_nothing() -> None:
    for seed in (300000, 300002, 300003):
        for arm in pp.ARMS:
            refused = pr.run_world(seed, arm, _invalid_policy)
            passed = pr.run_world(seed, arm, lemons.pass_action)
            assert _protected(refused) == _protected(passed), (seed, arm)
            assert pr.seat_net(refused) == 0.0 and refused.inspection_spend[SEAT] == 0.0


def test_each_refused_action_is_typed_and_unauthorized_commits_take_nothing() -> None:
    market = hz.HousingMarket(pr.make_world(300000, "true_cost"), rounds=4)
    # Round 0: an unknown listing, a negative rent, then seat 0 signs seat 2's hold.
    assert market.submit_inspections({SEAT: 99}).verdicts[SEAT].reason == "unknown_listing"
    assert market.inspection_spend[SEAT] == 0.0
    assert market.submit_offers({SEAT: (0, -5.0), 2: (1, 0.0)}).verdicts[SEAT].reason == "invalid_rent"
    responses, _ = price_bargaining.landlord_responses(market, market._offers)
    holds = market.submit_responses(responses).holds
    assert SEAT not in holds and 2 in holds
    commits = market.submit_commits({SEAT: ("sign", holds[2].hold_id), 2: ("sign", holds[2].hold_id)}).verdicts
    assert commits[SEAT].reason == "unknown_hold" and commits[2].outcome == "applied"
    assert market.pairs == [(2, 1)] and SEAT not in market.signed_rent
    # Round 1: inspecting a leased listing is refused; a real hold is walked.
    assert market.submit_inspections({SEAT: 1}).verdicts[SEAT].reason == "unavailable_listing"
    market.submit_offers({SEAT: (0, 0.0)})
    responses, _ = price_bargaining.landlord_responses(market, market._offers)
    stale = market.submit_responses(responses).holds[SEAT]
    market.submit_commits({SEAT: ("walk", stale.hold_id)})
    # Round 2: one paid inspection. Round 3: inspecting it again costs nothing, and signing the
    # round-1 hold signs nothing.
    assert market.submit_inspections({SEAT: 0}).verdicts[SEAT].outcome == "applied"
    market.submit_offers({})
    market.submit_responses({})
    market.submit_commits({})
    assert market.submit_inspections({SEAT: 0}).verdicts[SEAT].reason == "already_inspected"
    market.submit_offers({})
    market.submit_responses({})
    assert market.submit_commits({SEAT: ("sign", stale.hold_id)}).verdicts[SEAT].reason == "unknown_hold"
    assert market.finished and SEAT not in dict(market.pairs)
    assert market.inspection_spend[SEAT] == 25.0 and pr.seat_net(market) == -25.0


def test_invalid_counterexample_a_market_that_accepts_a_negative_rent_moves_state(monkeypatch) -> None:
    # Counterexample: drop the rent guard and the same refused policy now changes the market.
    monkeypatch.setattr(hz.HousingMarket, "_valid_rent", staticmethod(lambda rent: isinstance(rent, float)))
    moved = [(seed, arm) for seed in (300000, 300002, 300003) for arm in pp.ARMS
             if _protected(pr.run_world(seed, arm, _invalid_policy)) != _protected(pr.run_world(seed, arm, lemons.pass_action))]
    assert moved


# --- 4. malformed or operational failure ------------------------------------------------------

MALFORMED_SHAPES = [
    ("contact", "not a pair", "invalid_contact"), ("contact", (True, 10.0), "unknown_listing"),
    ("contact", ("1", 10.0), "unknown_listing"), ("contact", (1, "10"), "invalid_rent"),
    ("contact", (1, math.nan), "invalid_rent"),
]


@pytest.mark.parametrize("phase, action, reason", MALFORMED_SHAPES)
def test_malformed_market_actions_become_typed_passes(phase: str, action: Any, reason: str) -> None:
    market = hz.HousingMarket(pr.make_world(300000, "pooled"), rounds=3)
    market.submit_inspections({})
    before = _protected(market)
    verdicts = market.submit_offers({SEAT: action}).verdicts
    assert (verdicts[SEAT].outcome, verdicts[SEAT].reason) == ("pass", reason)
    assert _protected(market) == before and SEAT not in {o.tenant_id for v in market._offers.values() for o in v}


class _MalformedCommit:
    """Stands in for the paid client: the scripted tenant, except that every commit facing a hold is malformed.

    Round 0's commit is plain text; a later one is the exact shape GLM sent once in v14,
    ``{"decision": "walk", "hold_id": null}``.
    """

    async def complete(self, request):
        from aeread_families.housing.runner import HousingScriptedTenantProvider

        result = await HousingScriptedTenantProvider().complete(dataclasses.replace(
            request, provider="housing_scripted_tenant",
            model="housing_scripted_tenant_inspect_then_sign_v1", revision="1.0.0"))
        payload = json.loads(request.input_text)
        if payload["phase_id"] != "commit" or payload["observation"].get("active_hold") is None:
            return result
        text = "I will sign the hold." if payload["observation"]["round_index"] == 0 else '{"decision":"walk","hold_id":null}'
        return dataclasses.replace(result, output_text=text)


def test_malformed_output_is_typed_invalidity_applied_as_a_pass_never_a_zero(tmp_path) -> None:
    # The kernel path: a v14 contract on pack world 300000, where the scripted tenant inspects
    # listing 1, is countered and signs (net $275.93 in either arm). Here every commit it sends is
    # malformed. Each cell completes, every parse failure is sealed with its typed code, each hold
    # lapses as a walk would, and seat 0 nets minus its fees: neither the lease it meant nor $0.
    contract = dict(price_campaign.load_contract(ROOT / f"configs/{GLM}.json"), world_seeds=[300000])
    summary = asyncio.run(price_campaign.run(contract, tmp_path, live=True, provider=_MalformedCommit()))
    assert summary["completed_cells"] == 2 and summary["operational_failures"] == 0
    rows = {r["arm"]: r for r in pp.cell_rows(contract, tmp_path)}
    codes = set()
    for arm in pp.ARMS:
        assert pr.seat_net(pr.run_world(300000, arm, lemons.inspect_then_sign_action)) == 275.93
        events = next((tmp_path / "live").glob(f"world_300000__{arm}_evidence/runplan_*/tasks/*/attempts/*/events.jsonl"))
        trajectory, outcome = post.trajectory_from_events(events)
        mine = [d for d in outcome["commit_decisions"] if d["tenant_id"] == SEAT]
        assert mine and all(d["decision"] == "walk" for d in mine)
        assert sum(trajectory.invalid_actions.values()) == len(mine) == len(trajectory.replies)
        codes |= set(trajectory.invalid_actions)
        spend = float(outcome["tenant_inspection_spend"][f"tenant_{SEAT}"])
        assert spend > 0 and rows[arm]["status"] == "completed" and rows[arm]["signed"] is False
        assert rows[arm]["net_realized"] == rows[arm][pp.PRIMARY] == -spend
    assert codes == {"malformed_json", "malformed_commit"}


def test_operational_failure_is_typed_missingness_never_a_zero(tmp_path) -> None:
    # The publication path: a failed cell is published with its typed condition and no primary,
    # its world drops out of the model's paired measure, and the failure is counted.
    live = tmp_path / "live"
    live.mkdir()
    for seed in (300000, 300001):
        for arm in pp.ARMS:
            if (seed, arm) == (300000, "true_cost"):
                row = {"world_seed": seed, "arm": arm, "status": "operational_failure",
                       "failure_condition": "SchedulerContractError", "cost_usd": 0.001, "receipt_sha256": None}
            else:
                market = pr.run_world(seed, arm, lemons.inspect_then_sign_action)
                accounting = market.lemons_accounting()
                row = {"world_seed": seed, "arm": arm, "status": "completed", "cost_usd": 0.0,
                       "outcome_facts": {k: accounting[k] for k in price_endpoint.OUTCOME_FACTS}}
            (live / f"world_{seed}__{arm}.json").write_text(json.dumps(row))
    contract = {"campaign_id": GLM, "world_seeds": [300000, 300001], "arms": list(pp.ARMS)}
    rows = pp.cell_rows(contract, tmp_path)
    failed = next(r for r in rows if (r["world_seed"], r["arm"]) == (300000, "true_cost"))
    assert failed["status"] == "operational_failure" and failed["failure_condition"] == "SchedulerContractError"
    assert pp.PRIMARY not in failed and "net_realized" not in failed
    report = pp.analysis({GLM: rows})
    main = report["models"][GLM]["by_scope"]["main"]
    assert report["models"][GLM]["operational_failures"] == 1
    assert main["worlds_with_both_arms"] == 1 and main["primary"]["n"] == 1
    kept = statistics.fmean(r[pp.PRIMARY] for r in rows if r["world_seed"] == 300001)
    assert main["primary"]["mean"] == round(kept, 2)


# --- 5. degenerate reference ------------------------------------------------------------------

def test_zero_ceiling_world_follows_the_declared_rule() -> None:
    # 300002 pooled: the pooled landlord counters every listing at the sound floor, and no listing's
    # true value to seat 0 covers it, so the ceiling is $0 and the best play is to do nothing.
    seed, arm = 300002, "pooled"
    world = pr.make_world(seed, arm)
    surplus = [round(float(world.values[SEAT][l]) - _target(world, l), 2) for l in range(world.num_listings)]
    assert max(surplus) <= 0 and pr.ceiling(seed, arm) == 0.0
    assert pr.seat_net(pr.run_world(seed, arm, lemons.pass_action)) == 0.0
    reference = pr.seat_net(pr.run_world(seed, arm, pr.inspect_lowball_action))
    assert reference == -25.0
    cell = {"world_seed": seed, "arm": arm, "ceiling": 0.0, "net_realized": reference}
    other = {"world_seed": seed, "arm": "true_cost", "ceiling": pr.ceiling(seed, "true_cost"),
             "net_realized": pr.seat_net(pr.run_world(seed, "true_cost", pr.inspect_lowball_action))}
    share = price_controls.share_of_ceiling([cell, other], "net_realized")
    assert share == {"share": round(other["net_realized"] / other["ceiling"], 4), "cells": 1, "zero_ceiling_cells_excluded": 1}
    assert price_controls.share_of_ceiling([cell], "net_realized") == {"share": None, "cells": 0, "zero_ceiling_cells_excluded": 1}
    # It stays in the net measure: the world's value is the mean of both arms, the $0 arm included.
    row = lambda c: {**c, "status": "completed", "population": "main", "stratum": "favourite_is_lemon",  # noqa: E731
                     pp.PRIMARY: c["net_realized"]}
    assert pp.per_world([row(cell), row(other)], pp.PRIMARY) == {seed: (cell["net_realized"] + other["net_realized"]) / 2}
    with pytest.raises(ValueError, match="oracle error"):
        price_controls.share_of_ceiling([{**cell, "ceiling": -1.0}], "net_realized")


def test_zero_ceiling_cells_of_the_pack_are_the_ten_the_bundle_publishes() -> None:
    published = {(r["world_seed"], r["arm"]) for r in map(json.loads, (
        ROOT / "evidence/housing/housing_lemons_price_confirmatory_v14/tables/cells.jsonl").read_text().splitlines())
        if r["ceiling"] == 0.0}
    found = {(seed, arm) for seed in price_campaign.PACK_WORLD_SEEDS for arm in pp.ARMS if pr.ceiling(seed, arm) == 0.0}
    assert found == published and len(found) == 10 and {arm for _, arm in found} == {"pooled"}
    holdout = set(price_campaign.PACK["holdout"]["world_seeds"])
    assert sum(seed in holdout for seed, _ in found) == 3


def test_zero_ceiling_counterexample_keeping_the_cell_changes_the_share() -> None:
    # Counterexample: a ratio that keeps the $0 cell (the bundle's ``realized_share_of_ceiling``)
    # is not the rule's, so the rule is a real choice and the test above can tell them apart.
    cells = [{"ceiling": 0.0, "net_realized": -25.0}, {"ceiling": 200.0, "net_realized": 150.0}]
    kept = sum(c["net_realized"] for c in cells) / sum(c["ceiling"] for c in cells)
    assert price_controls.share_of_ceiling(cells, "net_realized")["share"] != round(kept, 4)

