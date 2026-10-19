"""Outside demand at 0.3 a round: the v15 holdout's one changed mechanism.

The v15 plan (``docs/families/housing/price_confirmatory_v15_plan.md``, Section 2) holds its holdout out by
mechanism, not only by seed: outside demand takes an unbid open listing with probability 0.3 a round instead of
``price_outside_demand.RATE`` (0.5). Everything else is v14's. The draw is ``price_outside_demand.wanted`` with
``rate`` passed, so a listing wanted at 0.3 is wanted at 0.5 too and both landlord arms meet the same departures.
``price_outside_demand`` is not edited: editing ``RATE`` in place would change what v14 runs (plan, Correction).

This module plays the market offline at this rate (``run_world``, ``run_recorded``) for the pack's screen and
controls, and answers the outside seats in the kernel (``HoldoutOutsideDemandProvider``) under its own model id,
so a holdout contract names the rate it ran. Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from aeread.shared_runner.task.execution import ProviderFailure

from aeread_families.housing import environment as hz
from aeread_families.housing import price_bargaining, price_outside_demand, price_reference, price_reply_posterior
from aeread_families.housing.runner import _scripted_result

RATE = 0.3
PROVIDER = price_outside_demand.PROVIDER
MODEL = "housing_outside_demand_tenant_rate30_v1"
REVISION = "1.0.0"


def outside_demand_action(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """``price_outside_demand.outside_demand_action`` at this module's rate."""
    if phase_id != "contact":
        return price_outside_demand.outside_demand_action(observation, phase_id)
    listing_id = price_outside_demand.listing_for_seat(int(observation["tenant_id"]))
    board = sorted(observation["board"], key=lambda row: int(row["listing_id"]))
    row = next((r for r in board if int(r["listing_id"]) == listing_id), None)
    if row is None or row["status"] != "OPEN":
        return {"decision": "pass", "listing_id": None, "rent": None}
    asks = [float(r["rent_asked"]) for r in board]
    if not price_outside_demand.wanted(asks, listing_id, int(observation["round_index"]), rate=RATE):
        return {"decision": "pass", "listing_id": None, "rent": None}
    return {"decision": "offer", "listing_id": listing_id, "rent": price_outside_demand.OPENING_OFFER}


def block() -> dict[str, Any]:
    """What a holdout contract declares about its outside demand."""
    base = {k: v for k, v in price_outside_demand.block().items() if not k.startswith("focal_notice")}  # notice v5 declares it
    return {**base, "model": MODEL, "revision": REVISION, "rate_per_round": RATE,
            "draw": "price_outside_demand.wanted(asks, listing, round, rate=0.3)"}


def run_world(seed: int, arm: str, focal: price_reference.Policy, rounds: int = price_outside_demand.ROUNDS) -> hz.HousingMarket:
    """``price_reference.run_world`` with outside demand at this module's rate."""
    return run_with(seed, arm, focal, outside_demand_action, rounds)


def run_with(seed: int, arm: str, focal: price_reference.Policy, outside: price_reference.Policy,
             rounds: int = price_outside_demand.ROUNDS) -> hz.HousingMarket:
    """``price_reference.run_world``'s loop with the outside seats' policy passed in (a test holds the two equal)."""
    market = hz.HousingMarket(price_reference.make_world(seed, arm), rounds=rounds)

    def act(seat: int, observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
        return focal(observation, phase_id) if seat == price_reference.FOCAL_SEAT else outside(observation, phase_id)

    while not market.finished:
        inspections = {}
        for seat in market.unmatched_tenants():
            action = act(seat, market.tenant_observation(seat), "inspect")
            if action["decision"] == "inspect":
                inspections[seat] = action["listing_id"]
        market.submit_inspections(inspections)
        offers = {}
        for seat in market.unmatched_tenants():
            action = act(seat, market.tenant_observation(seat), "contact")
            if action["decision"] == "offer":
                offers[seat] = (action["listing_id"], action["rent"])
        contact = market.submit_offers(offers)
        responses, _ = price_bargaining.landlord_responses(market, contact.inbox)
        holds = market.submit_responses(responses).holds
        commits = {}
        for seat in holds:
            action = act(seat, market.tenant_observation(seat), "commit")
            if action["decision"] in {"sign", "walk"}:
                commits[seat] = (action["decision"], action["hold_id"])
        market.submit_commits(commits)
    return market


def run_recorded(seed: int, arm: str, policy: price_reference.Policy) -> tuple[hz.HousingMarket, price_reply_posterior.Trajectory]:
    """``price_reply_posterior.run_recorded`` at this module's rate."""
    recorder = price_reply_posterior._Recorder(policy)
    market = run_world(seed, arm, recorder)
    return market, recorder.trajectory


class HoldoutOutsideDemandProvider:
    """Answers the outside seats of a holdout cell at this module's rate. Costs nothing and calls nobody."""

    async def complete(self, request: Any) -> Any:
        if request.provider != PROVIDER or request.model != MODEL or request.revision != REVISION:
            raise ProviderFailure("provider_contract", "wrong holdout outside-demand provider", retryable=False)
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        if int(observation["tenant_id"]) not in price_outside_demand.OUTSIDE_SEATS:
            raise ProviderFailure("provider_contract", "outside demand asked to play the focal seat", retryable=False)
        return _scripted_result(request, outside_demand_action(observation, payload["phase_id"]))


__all__ = ["HoldoutOutsideDemandProvider", "MODEL", "PROVIDER", "RATE", "REVISION", "block", "outside_demand_action",
           "run_recorded", "run_with", "run_world"]
