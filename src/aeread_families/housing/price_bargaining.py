"""Versioned, provider-free price negotiation probe for Housing lemons.

This is an exploratory price diagnostic, not the frozen refusal campaign. The
tenant uses only its observation; the landlord follows one fixed cost-plus rule.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
from typing import Any, Mapping

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons


LANDLORD_MODEL = "housing_scripted_landlord_price_v1"
TENANT_MODEL = "housing_scripted_tenant_price_v1"
LANDLORD_MARGIN = 25.0
TENANT_OPENING_DISCOUNT = 100.0


def _offer_view(offer: Any) -> Mapping[str, Any]:
    return dataclasses.asdict(offer) if dataclasses.is_dataclass(offer) else offer


def landlord_action(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Counter at cost plus $25, capped by ask; accept a better opening offer."""
    inbox = [_offer_view(offer) for offer in observation["inbox"]]
    if not inbox:
        return {"decision": "reject_all", "offer_id": None, "counter_rent": None}
    reservation = float(observation.get("reservation_cost", observation["private_cost"]))
    ask = float(observation["listing"]["rent_asked"])
    target = round(max(reservation, min(ask, reservation + LANDLORD_MARGIN)), 2)
    chosen = max(inbox, key=lambda offer: (float(offer["rent"]), -int(offer["tenant_id"])))
    if float(chosen["rent"]) >= target:
        return {"decision": "accept", "offer_id": chosen["offer_id"], "counter_rent": None}
    return {"decision": "counter", "offer_id": chosen["offer_id"], "counter_rent": target}


def landlord_responses(
    market: hz.HousingMarket, inbox: Mapping[int, Any]
) -> tuple[dict[int, dict[int, tuple[str, float | None]]], list[dict[str, Any]]]:
    """Translate the same fixed provider action into market responses and a trace."""
    responses: dict[int, dict[int, tuple[str, float | None]]] = {}
    negotiations: list[dict[str, Any]] = []
    for listing_id, listing_offers in inbox.items():
        action = landlord_action(market.landlord_observation(listing_id))
        chosen = next(offer for offer in listing_offers if offer.offer_id == action["offer_id"])
        negotiations.append({
            "round_index": market.round_index,
            "tenant_id": chosen.tenant_id,
            "listing_id": listing_id,
            "offer_rent": chosen.rent,
            "landlord_decision": action["decision"],
            "hold_rent": chosen.rent if action["decision"] == "accept" else action["counter_rent"],
        })
        responses[listing_id] = {
            offer.tenant_id: (
                ("accept", None) if action["decision"] == "accept" else ("counter", action["counter_rent"])
            ) if offer.tenant_id == chosen.tenant_id else ("reject", None)
            for offer in listing_offers
        }
    return responses, negotiations


def tenant_action(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """Inspect, bid below the quality-adjusted ask, and sign affordable holds."""
    board = [row for row in observation["board"] if row["status"] == "OPEN"]
    inspected = {int(row["listing_id"]): row["quality"] for row in observation["inspections"]}
    values = observation["private_values_if_sound"]
    loss = float(observation["lemon_loss"])
    if phase_id == "inspect":
        unknown = [row for row in board if row["listing_id"] not in inspected]
        if not unknown:
            return {"decision": "pass", "listing_id": None}
        chosen = max(unknown, key=lambda row: (float(values[row["listing_id"]]) - float(row["rent_asked"]), -row["listing_id"]))
        return {"decision": "inspect", "listing_id": chosen["listing_id"]}
    if phase_id == "contact":
        candidates = []
        for row in board:
            listing_id = row["listing_id"]
            if listing_id not in inspected or listing_id in observation["rejected_listing_ids"]:
                continue
            quality_loss = loss if inspected[listing_id] == "lemon" else 0.0
            value = float(values[listing_id]) - quality_loss
            quality_ask = float(row["rent_asked"]) - quality_loss
            if value >= max(0.0, quality_ask):
                candidates.append((value - quality_ask, -listing_id, row, quality_ask, value))
        if not candidates:
            return {"decision": "pass", "listing_id": None, "rent": None}
        _, _, row, quality_ask, value = max(candidates)
        rent = round(max(0.0, min(value, quality_ask - TENANT_OPENING_DISCOUNT)), 2)
        return {"decision": "offer", "listing_id": row["listing_id"], "rent": rent}
    if phase_id == "commit":
        hold = observation["active_hold"]
        if hold is None:
            return {"decision": "pass", "hold_id": None}
        hold = _offer_view(hold)
        listing_id = int(hold["listing_id"])
        quality_loss = loss if inspected.get(listing_id) == "lemon" else 0.0
        value = float(values[listing_id]) - quality_loss
        return {
            "decision": "sign" if listing_id in inspected and value >= float(hold["rent"]) else "walk",
            "hold_id": hold["hold_id"],
        }
    raise ValueError(f"unknown phase: {phase_id}")


def run_world(seed: int, *, landlord_reservation: str = "true_cost", rounds: int = 3) -> list[dict[str, Any]]:
    """Run one mixed-quality world through the real HousingMarket transitions."""
    world = lemons.make_lemons_world(
        6, 4, seed, 0.6, lemon_share=0.5, lemon_loss=1000.0,
        inspection_cost=25.0, landlord_reservation=landlord_reservation,
    )
    market = hz.HousingMarket(world, rounds=rounds)
    negotiations: list[dict[str, Any]] = []
    while not market.finished:
        inspections = {}
        for tenant_id in market.unmatched_tenants():
            action = tenant_action(market.tenant_observation(tenant_id), "inspect")
            if action["decision"] == "inspect":
                inspections[tenant_id] = action["listing_id"]
        market.submit_inspections(inspections)
        offers = {}
        for tenant_id in market.unmatched_tenants():
            action = tenant_action(market.tenant_observation(tenant_id), "contact")
            if action["decision"] == "offer":
                offers[tenant_id] = (action["listing_id"], action["rent"])
        contact = market.submit_offers(offers)
        responses, round_negotiations = landlord_responses(market, contact.inbox)
        negotiations.extend(round_negotiations)
        response = market.submit_responses(responses)
        commits = {}
        for tenant_id in response.holds:
            action = tenant_action(market.tenant_observation(tenant_id), "commit")
            commits[tenant_id] = (action["decision"], action["hold_id"])
        market.submit_commits(commits)
    leased = {listing_id: tenant_id for tenant_id, listing_id in market.pairs}
    signed_negotiations = {
        (row["tenant_id"], row["listing_id"]): row
        for row in negotiations if (row["tenant_id"], row["listing_id"]) in market.pairs
    }
    return [
        {
            "world_seed": seed,
            "listing_id": listing_id,
            "quality": hz.QUALITY_LABEL[world.quality[listing_id]],
            "ask": world.ask[listing_id],
            "tenant_id": leased.get(listing_id),
            "signed_rent": market.signed_rent[leased[listing_id]] if listing_id in leased else None,
            "signed_via_counter": (
                signed_negotiations[(leased[listing_id], listing_id)]["landlord_decision"] == "counter"
                if listing_id in leased else None
            ),
            "counteroffers": sum(
                row["landlord_decision"] == "counter" for row in negotiations
                if row["listing_id"] == listing_id
            ),
            "landlord_reservation": landlord_reservation,
        }
        for listing_id in range(world.num_listings)
    ]


def run_reference(world: lemons.LemonsWorld, rounds: int, policy_id: str) -> hz.HousingMarket:
    """Recompute a lemons scripted reference against the price landlord."""
    policy = lemons.TENANT_POLICIES[policy_id]
    market = hz.HousingMarket(world, rounds=rounds)
    while not market.finished:
        inspections = {}
        for tenant_id in market.unmatched_tenants():
            action = policy(market.tenant_observation(tenant_id), "inspect")
            if action["decision"] == "inspect":
                inspections[tenant_id] = action["listing_id"]
        market.submit_inspections(inspections)
        offers = {}
        for tenant_id in market.unmatched_tenants():
            action = policy(market.tenant_observation(tenant_id), "contact")
            if action["decision"] == "offer":
                offers[tenant_id] = (action["listing_id"], action["rent"])
        contact = market.submit_offers(offers)
        responses, _ = landlord_responses(market, contact.inbox)
        holds = market.submit_responses(responses).holds
        commits = {}
        for tenant_id in holds:
            action = policy(market.tenant_observation(tenant_id), "commit")
            if action["decision"] in {"sign", "walk"}:
                commits[tenant_id] = (action["decision"], action["hold_id"])
        market.submit_commits(commits)
    return market


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep trade selection beside conditional signed-price statistics."""
    result: dict[str, Any] = {}
    for quality in ("sound", "lemon"):
        eligible = [row for row in rows if row["quality"] == quality]
        signed = [row for row in eligible if row["signed_rent"] is not None]
        discounts = [round(row["signed_rent"] - row["ask"], 2) for row in signed]
        result[quality] = {
            "listings": len(eligible),
            "signed": len(signed),
            "signed_via_counter": sum(row["signed_via_counter"] for row in signed),
            "counteroffers": sum(row["counteroffers"] for row in eligible),
            "sign_rate": round(len(signed) / len(eligible), 4) if eligible else None,
            "mean_ask": round(statistics.mean(row["ask"] for row in eligible), 2) if eligible else None,
            "mean_signed_rent": round(statistics.mean(row["signed_rent"] for row in signed), 2) if signed else None,
            "mean_signed_minus_ask": round(statistics.mean(discounts), 2) if discounts else None,
            "median_signed_minus_ask": round(statistics.median(discounts), 2) if discounts else None,
        }
    sound = result["sound"]["mean_signed_minus_ask"]
    lemon = result["lemon"]["mean_signed_minus_ask"]
    result["sound_minus_lemon_discount_gap"] = round(sound - lemon, 2) if sound is not None and lemon is not None else None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--start-seed", type=int, default=100000)
    parser.add_argument("--reservation", choices=("true_cost", "pooled", "both"), default="both")
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    reservations = ("true_cost", "pooled") if args.reservation == "both" else (args.reservation,)
    arms = {
        reservation: summarize([
            row for seed in range(args.start_seed, args.start_seed + args.seeds)
            for row in run_world(seed, landlord_reservation=reservation)
        ])
        for reservation in reservations
    }
    print(json.dumps({"experiment": "housing_lemons_price_probe_v1", "worlds": args.seeds, "start_seed": args.start_seed, "arms": arms}, sort_keys=True))


if __name__ == "__main__":
    main()
