"""Housing lemons world: refusal under adverse selection.

A declared number of listings are lemons that post the same ask as sound units.
A tenant's value depends on true quality, which only the landlord knows until
the tenant pays to inspect. Signing an uninspected unit at the pooled ask is
adverse selection; refusing an uninspected lemon is correct.

Welfare cannot score refusal. A lemon's landlord cost is lower by the same
defect that lowers the tenant's value, so a lemon signed at the ask still adds
``value - cost`` to welfare while the tenant seat loses. The primary endpoint
for this world is therefore the principal's outcome: the tenants' net payoff
after inspection spend, bracketed by three scripted tenant policies that share
the code of the runner's scripted providers:

- ``sign_anything`` never inspects, offers the ask on its favourite listing by
  value-if-sound, and signs any hold at or below that value;
- ``pass`` never inspects and never offers, so it books exactly zero;
- ``inspect_then_sign`` inspects its best uninspected candidate each round,
  offers only on listings it knows are sound, and signs only a hold whose rent
  is covered by the value it has verified.

A world is admitted only when the inverted ordering holds on it:
``sign_anything < pass < inspect_then_sign`` with ``sign_anything`` strictly
negative, by declared margins normalized by the full-information oracle.

Every policy here is a function of the tenant observation alone, so what the
gate computes offline is what the scripted provider does in a run.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import random
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from aeread_families.housing import environment as hz


SOUND = hz.SOUND
LEMON = hz.LEMON
QUALITY_LABEL = hz.QUALITY_LABEL

TENANT_POLICY_IDS = ("sign_anything", "inspect_then_sign", "pass")

DEFAULT_LEMON_SHARE = 0.5
DEFAULT_LEMON_LOSS = 1000.0
DEFAULT_INSPECTION_COST = 25.0

# The inverted admission rule. Normalized quantities divide by the oracle total,
# so the margins are shares of the full-information surplus.
DEFAULT_ADMISSION_RULE: Dict[str, float] = {
    "lemon_count_min": 1,
    "sound_count_min": 1,
    "oracle_total_min": 1e-9,
    "sign_anything_normalized_max": -0.05,
    "inspect_then_sign_normalized_min": 0.05,
    "reference_minus_sign_anything_normalized_min": 0.25,
}


@dataclass(frozen=True)
class LemonsWorld:
    listings: List[hz.Listing]
    values: List[List[float]]            # true willingness to pay; never shown
    values_if_sound: List[List[float]]   # what the tenant is shown
    costs: List[float]                   # landlord reservation cost; private
    ask: List[float]
    quality: Tuple[int, ...]             # SOUND (1) or LEMON (0) per listing
    lemon_share: float
    lemon_loss: float
    inspection_cost: float
    # How a lemon's landlord decides (HL-D-01). "true_cost": on its own cost,
    # which is lemon_loss lower, so its accept-or-counter reply reveals quality.
    # "pooled": on the cost a sound listing at that address would have, as a
    # lemon seller mimicking a sound one would; the true cost stays in the
    # accounting only. sound_costs holds that sound-equivalent cost per listing.
    landlord_reservation: str = "true_cost"
    sound_costs: Tuple[float, ...] = ()

    def reservation_cost(self, listing_id: int) -> float:
        """The cost the landlord of ``listing_id`` accepts and counters against."""
        if self.landlord_reservation == "pooled":
            return float(self.sound_costs[listing_id])
        return float(self.costs[listing_id])

    @property
    def num_tenants(self) -> int:
        return len(self.values)

    @property
    def num_listings(self) -> int:
        return len(self.listings)

    @property
    def surplus(self) -> List[List[float]]:
        """True surplus, so the oracle prices quality in."""
        return [[v - self.costs[l] for l, v in enumerate(row)] for row in self.values]

    @property
    def lemon_ids(self) -> Tuple[int, ...]:
        return tuple(l for l, q in enumerate(self.quality) if q == LEMON)

    @property
    def sound_ids(self) -> Tuple[int, ...]:
        return tuple(l for l, q in enumerate(self.quality) if q == SOUND)

    @property
    def lemon_count(self) -> int:
        return len(self.lemon_ids)


#: How a lemon's landlord reserves; see LemonsWorld.landlord_reservation.
LANDLORD_RESERVATIONS = frozenset({"true_cost", "pooled"})


def _finite_nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def lemon_count_for(num_listings: int, lemon_share: float) -> int:
    """The declared share rounds half up to an exact count, so every world has it
    and one listing at share 0.5 is a lemon rather than Python's round-to-even zero."""
    return int(math.floor(float(lemon_share) * num_listings + 0.5))


def make_lemons_world(
    num_tenants: int,
    num_listings: int,
    seed: int,
    common_weight: float = 0.6,
    *,
    lemon_share: float = DEFAULT_LEMON_SHARE,
    lemon_loss: float = DEFAULT_LEMON_LOSS,
    inspection_cost: float = DEFAULT_INSPECTION_COST,
    landlord_reservation: str = "true_cost",
) -> LemonsWorld:
    """The pinned bid world plus quality.

    Values-if-sound, asks, and sound landlord costs are exactly the bid world's.
    A lemon is worth ``lemon_loss`` less to every tenant and costs its landlord
    ``lemon_loss`` less (floored at zero), so a lemon lease carries the same
    surplus as a sound one and welfare cannot see quality.
    """
    share = _finite_nonnegative(lemon_share, "lemon_share")
    if share > 1.0:
        raise ValueError("lemon_share must be between zero and one")
    loss = _finite_nonnegative(lemon_loss, "lemon_loss")
    cost = _finite_nonnegative(inspection_cost, "inspection_cost")
    if landlord_reservation not in LANDLORD_RESERVATIONS:
        raise ValueError(f"landlord_reservation must be one of {sorted(LANDLORD_RESERVATIONS)}")
    base = hz.make_bid_world(num_tenants, num_listings, seed, common_weight)
    rng = random.Random(seed * 15485863 + 101)
    lemons = set(rng.sample(range(num_listings), lemon_count_for(num_listings, share)))
    quality = tuple(LEMON if l in lemons else SOUND for l in range(num_listings))
    values = [
        [round(v - loss, 2) if quality[l] == LEMON else v for l, v in enumerate(row)]
        for row in base.values
    ]
    costs = [
        round(max(0.0, c - loss), 2) if quality[l] == LEMON else c
        for l, c in enumerate(base.costs)
    ]
    return LemonsWorld(
        listings=base.listings,
        values=values,
        values_if_sound=[list(row) for row in base.values],
        costs=costs,
        ask=list(base.ask),
        quality=quality,
        lemon_share=share,
        lemon_loss=loss,
        inspection_cost=cost,
        landlord_reservation=landlord_reservation,
        sound_costs=tuple(float(c) for c in base.costs),
    )


# ---------------------------------------------------------------------------
# Scripted tenant policies over the observation
# ---------------------------------------------------------------------------


def _hold_view(observation: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The active hold as a mapping, whether the observation came through JSON
    (the provider) or straight from the market (the offline gate)."""
    hold = observation.get("active_hold")
    if hold is None:
        return None
    if dataclasses.is_dataclass(hold):
        return dataclasses.asdict(hold)
    return dict(hold)


def _inspection_lookup(observation: Mapping[str, Any]) -> Dict[int, str]:
    return {
        int(row["listing_id"]): str(row["quality"])
        for row in observation.get("inspections", ())
    }


def _open_candidates(observation: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rejected = set(observation.get("rejected_listing_ids", ()))
    return [
        row
        for row in observation["board"]
        if row["status"] == "OPEN" and row["listing_id"] not in rejected
    ]


def _gain_if_sound(observation: Mapping[str, Any], row: Mapping[str, Any]) -> float:
    return float(observation["private_values_if_sound"][row["listing_id"]]) - float(
        row["rent_asked"]
    )


def _offer(observation: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
    listing_id = row["listing_id"]
    value = float(observation["private_values_if_sound"][listing_id])
    return {
        "decision": "offer",
        "listing_id": listing_id,
        "rent": min(value, float(row["rent_asked"]) + 1.0),
    }


def _pass(phase_id: str) -> Dict[str, Any]:
    if phase_id == "inspect":
        return {"decision": "pass", "listing_id": None}
    if phase_id == "contact":
        return {"decision": "pass", "listing_id": None, "rent": None}
    if phase_id == "commit":
        return {"decision": "pass", "hold_id": None}
    raise ValueError(f"unknown lemons tenant phase: {phase_id!r}")


def sign_anything_action(observation: Mapping[str, Any], phase_id: str) -> Dict[str, Any]:
    """Never inspects; trusts the ask; signs any hold its sound value covers."""
    if phase_id == "inspect":
        return _pass(phase_id)
    if phase_id == "contact":
        viable = [row for row in _open_candidates(observation) if _gain_if_sound(observation, row) > 0]
        if not viable:
            return _pass(phase_id)
        return _offer(observation, max(viable, key=lambda row: _gain_if_sound(observation, row)))
    if phase_id == "commit":
        hold = _hold_view(observation)
        if not hold:
            return _pass(phase_id)
        value = float(observation["private_values_if_sound"][hold["listing_id"]])
        return {"decision": "sign" if hold["rent"] <= value else "walk", "hold_id": hold["hold_id"]}
    raise ValueError(f"unknown lemons tenant phase: {phase_id!r}")


def _posterior_from_observation(observation: Mapping[str, Any]) -> float:
    known = _inspection_lookup(observation)
    return hz.posterior_lemon_probability(
        int(observation["lemon_count"]),
        len(observation["board"]),
        [LEMON if quality == QUALITY_LABEL[LEMON] else SOUND for quality in known.values()],
    )


def inspect_then_sign_action(observation: Mapping[str, Any], phase_id: str) -> Dict[str, Any]:
    """Inspects before it contests; offers and signs only what it has verified.

    An inspection is worth paying for only when the gain it can unlock, weighted
    by the chance the listing is sound under the tenant's own posterior, exceeds
    the fee: ``(1 - p) * (value_if_sound - ask) > inspection_cost``.
    """
    known = _inspection_lookup(observation)
    if phase_id == "inspect":
        sound_probability = 1.0 - _posterior_from_observation(observation)
        fee = float(observation["inspection_cost"])
        candidates = [
            row
            for row in _open_candidates(observation)
            if row["listing_id"] not in known
            and sound_probability * _gain_if_sound(observation, row) > fee
        ]
        if not candidates:
            return _pass(phase_id)
        chosen = max(candidates, key=lambda row: _gain_if_sound(observation, row))
        return {"decision": "inspect", "listing_id": chosen["listing_id"]}
    if phase_id == "contact":
        candidates = [
            row
            for row in _open_candidates(observation)
            if known.get(row["listing_id"]) == QUALITY_LABEL[SOUND]
            and _gain_if_sound(observation, row) > 0
        ]
        if not candidates:
            return _pass(phase_id)
        return _offer(observation, max(candidates, key=lambda row: _gain_if_sound(observation, row)))
    if phase_id == "commit":
        hold = _hold_view(observation)
        if not hold:
            return _pass(phase_id)
        listing_id = hold["listing_id"]
        value = float(observation["private_values_if_sound"][listing_id])
        sign = known.get(listing_id) == QUALITY_LABEL[SOUND] and hold["rent"] <= value
        return {"decision": "sign" if sign else "walk", "hold_id": hold["hold_id"]}
    raise ValueError(f"unknown lemons tenant phase: {phase_id!r}")


def pass_action(observation: Mapping[str, Any], phase_id: str) -> Dict[str, Any]:
    """Never trades. The feasible floor, as a policy."""
    return _pass(phase_id)


TENANT_POLICIES: Dict[str, Callable[[Mapping[str, Any], str], Dict[str, Any]]] = {
    "sign_anything": sign_anything_action,
    "inspect_then_sign": inspect_then_sign_action,
    "pass": pass_action,
}


# ---------------------------------------------------------------------------
# Offline execution and world facts
# ---------------------------------------------------------------------------


def _apply_contact(action: Mapping[str, Any]) -> Optional[Tuple[int, float]]:
    if action["decision"] != "offer":
        return None
    return (int(action["listing_id"]), float(action["rent"]))


def run_lemons_policy(
    world: LemonsWorld, rounds: int, policy_id: str
) -> hz.HousingMarket:
    """Drive the market with one scripted tenant policy and the scripted landlord."""
    if policy_id not in TENANT_POLICIES:
        raise ValueError(f"unknown lemons tenant policy: {policy_id!r}")
    policy = TENANT_POLICIES[policy_id]
    market = hz.HousingMarket(world, rounds=rounds)
    while not market.finished:
        requests: Dict[int, int] = {}
        for t in market.unmatched_tenants():
            action = policy(market.tenant_observation(t), "inspect")
            if action["decision"] == "inspect":
                requests[t] = int(action["listing_id"])
        market.submit_inspections(requests)
        offers: Dict[int, Tuple[int, float]] = {}
        for t in market.unmatched_tenants():
            offer = _apply_contact(policy(market.tenant_observation(t), "contact"))
            if offer is not None:
                offers[t] = offer
        contact = market.submit_offers(offers)
        response = market.submit_responses(
            hz.scripted_landlord_responses(market, contact.inbox)
        )
        commits: Dict[int, Tuple[str, str]] = {}
        for t in response.holds:
            action = policy(market.tenant_observation(t), "commit")
            if action["decision"] in {"sign", "walk"}:
                commits[t] = (action["decision"], action["hold_id"])
        market.submit_commits(commits)
    return market


def _normalized(value: float, oracle_total: float) -> Optional[float]:
    if oracle_total <= 0.0:
        return None
    return round(value / oracle_total, 12)


def lemons_world_facts(world: LemonsWorld, rounds: int) -> Dict[str, Any]:
    """The bracket for one world: oracle, the three scripted policies, and ordering."""
    oracle = hz.assignment_oracle(world.surplus)
    markets = {policy_id: run_lemons_policy(world, rounds, policy_id) for policy_id in TENANT_POLICY_IDS}
    accounting = {policy_id: market.lemons_accounting() for policy_id, market in markets.items()}
    totals = {policy_id: accounting[policy_id]["tenant_net_total"] for policy_id in TENANT_POLICY_IDS}
    sign_anything = totals["sign_anything"]
    reference = totals["inspect_then_sign"]
    upper = oracle.total
    sign_economics = markets["sign_anything"].economics()
    return {
        "num_tenants": world.num_tenants,
        "num_listings": world.num_listings,
        "rounds": rounds,
        "lemon_count": world.lemon_count,
        "sound_count": world.num_listings - world.lemon_count,
        "lemon_share": world.lemon_share,
        "lemon_loss": world.lemon_loss,
        "inspection_cost": world.inspection_cost,
        "oracle_total": upper,
        "sign_anything_total": sign_anything,
        "pass_total": totals["pass"],
        "inspect_then_sign_total": reference,
        "sign_anything_normalized": _normalized(sign_anything, upper),
        "inspect_then_sign_normalized": _normalized(reference, upper),
        "reference_minus_sign_anything_normalized": _normalized(reference - sign_anything, upper),
        "sign_anything_leases": len(sign_economics.assignment.pairs),
        "sign_anything_lemon_signings": accounting["sign_anything"]["lemon_signings"],
        "sign_anything_tenant_ir_violations": sum(
            1 for item in sign_economics.ir_violations if item.startswith("tenant:")
        ),
        "inspect_then_sign_leases": len(markets["inspect_then_sign"].economics().assignment.pairs),
        "inspect_then_sign_inspections": accounting["inspect_then_sign"]["inspection_count"],
        "inspect_then_sign_abstention_correctness_rate": accounting["inspect_then_sign"][
            "abstention_correctness_rate"
        ],
        "inverted_ordering_holds": sign_anything < 0.0 < reference,
    }


def admission_failures(
    facts: Mapping[str, Any], rule: Mapping[str, float] = DEFAULT_ADMISSION_RULE
) -> List[str]:
    """Names of the requirements the world fails; empty means admitted."""
    if set(rule) != set(DEFAULT_ADMISSION_RULE):
        raise ValueError("lemons admission rule fields are incomplete or unexpected")
    failures: List[str] = []
    if int(facts["lemon_count"]) < rule["lemon_count_min"]:
        failures.append("lemon_count_min")
    if int(facts["sound_count"]) < rule["sound_count_min"]:
        failures.append("sound_count_min")
    if float(facts["oracle_total"]) < rule["oracle_total_min"] or (
        facts["sign_anything_normalized"] is None
    ):
        # A zero oracle has no normalized bracket, whatever threshold a custom
        # rule declares for it.
        failures.append("oracle_total_min")
        return failures
    if float(facts["sign_anything_normalized"]) > rule["sign_anything_normalized_max"]:
        failures.append("sign_anything_normalized_max")
    if float(facts["inspect_then_sign_normalized"]) < rule["inspect_then_sign_normalized_min"]:
        failures.append("inspect_then_sign_normalized_min")
    if (
        float(facts["reference_minus_sign_anything_normalized"])
        < rule["reference_minus_sign_anything_normalized_min"]
    ):
        failures.append("reference_minus_sign_anything_normalized_min")
    return failures


def sweep_facts(
    seeds: Sequence[int],
    *,
    num_tenants: int = 6,
    num_listings: int = 4,
    rounds: int = 4,
    common_weight: float = 0.6,
    lemon_share: float = DEFAULT_LEMON_SHARE,
    lemon_loss: float = DEFAULT_LEMON_LOSS,
    inspection_cost: float = DEFAULT_INSPECTION_COST,
    rule: Mapping[str, float] = DEFAULT_ADMISSION_RULE,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        world = make_lemons_world(
            num_tenants,
            num_listings,
            seed,
            common_weight,
            lemon_share=lemon_share,
            lemon_loss=lemon_loss,
            inspection_cost=inspection_cost,
        )
        facts = lemons_world_facts(world, rounds)
        failures = admission_failures(facts, rule)
        rows.append({"world_seed": seed, **facts, "admitted": not failures, "failed_requirements": failures})
    return rows


def summarize_sweep(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not rows:
        raise ValueError("no worlds to summarize")
    admitted = [row for row in rows if row["admitted"]]
    scored = [row for row in rows if row["sign_anything_normalized"] is not None]
    failures: Dict[str, int] = {}
    for row in rows:
        for name in row["failed_requirements"]:
            failures[name] = failures.get(name, 0) + 1

    def median(field: str) -> Optional[float]:
        values = [float(row[field]) for row in scored]
        return round(statistics.median(values), 6) if values else None

    return {
        "world_count": len(rows),
        "admitted_world_count": len(admitted),
        "admission_rate": round(len(admitted) / len(rows), 6),
        "inverted_ordering_rate": round(
            sum(bool(row["inverted_ordering_holds"]) for row in rows) / len(rows), 6
        ),
        "median_sign_anything_normalized": median("sign_anything_normalized"),
        "median_inspect_then_sign_normalized": median("inspect_then_sign_normalized"),
        "median_reference_minus_sign_anything_normalized": median(
            "reference_minus_sign_anything_normalized"
        ),
        "failed_requirement_counts": dict(sorted(failures.items())),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provider-free lemons world facts: the inverted bracket over seeds."
    )
    parser.add_argument("--seeds", type=int, default=300, help="world seeds 0..N-1")
    parser.add_argument("--tenants", type=int, default=6)
    parser.add_argument("--listings", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--common-weight", type=float, default=0.6)
    parser.add_argument("--lemon-share", type=float, default=DEFAULT_LEMON_SHARE)
    parser.add_argument("--lemon-loss", type=float, default=DEFAULT_LEMON_LOSS)
    parser.add_argument("--inspection-cost", type=float, default=DEFAULT_INSPECTION_COST)
    parser.add_argument("--rows", action="store_true", help="print every world's facts")
    arguments = parser.parse_args(argv)
    rows = sweep_facts(
        range(arguments.seeds),
        num_tenants=arguments.tenants,
        num_listings=arguments.listings,
        rounds=arguments.rounds,
        common_weight=arguments.common_weight,
        lemon_share=arguments.lemon_share,
        lemon_loss=arguments.lemon_loss,
        inspection_cost=arguments.inspection_cost,
    )
    summary = {
        "config": {
            "num_tenants": arguments.tenants,
            "num_listings": arguments.listings,
            "rounds": arguments.rounds,
            "common_weight": arguments.common_weight,
            "lemon_share": arguments.lemon_share,
            "lemon_loss": arguments.lemon_loss,
            "inspection_cost": arguments.inspection_cost,
        },
        "admission_rule": dict(DEFAULT_ADMISSION_RULE),
        **summarize_sweep(rows),
    }
    if arguments.rows:
        summary["rows"] = rows
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
