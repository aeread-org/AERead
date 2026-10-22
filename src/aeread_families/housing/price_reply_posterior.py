"""Housing price measure v2: a blind signing valued at its posterior given every informative reply (HL-D-07).

The v14 primary measure (``price_endpoint``, seat 0's ``net_expected_response_odds``, here *v1*)
conditions on the landlord's reply in one case only: a leaky-arm hold below the sound floor is a
certain lemon. The case contract describes the measure as pricing every blind signing at its
expected value given what the tenant saw. Two replies v1 does not read:

1. a leaky-arm **counter exactly at the sound floor** to an offer below it, which only a sound
   listing's landlord gives, so the listing is sound;
2. a reply that reveals one listing's quality also moves the odds on every other listing, because
   the world holds exactly ``lemon_count`` lemons.

v2 reads both. The evaluator knows the true landlord arm and, per listing, the lowest rent a sound
listing's landlord accepts (``price_endpoint.sound_floor``) and the target a lemon's landlord would
counter at (``lemon_target``). Under the price landlord's rule (``price_bargaining.landlord_action``):

* leaky arm (``true_cost``), an offer **below** the sound floor on a listing whose lemon target is
  below that floor: a reply below the floor (an acceptance or a counter) proves a lemon; a counter
  exactly at the floor proves sound; any other reply is impossible under the rule and stops the
  scorer (an instrument error is never scored);
* an offer at or above the floor is accepted by either quality and says nothing;
* the pooled arm's landlord reserves on the sound cost whatever the quality, so no reply says anything;
* knowledge accumulates inside the round order (inspect, contact, respond, commit): a decision in
  round ``r`` sees every inspection and informative reply of rounds up to and including ``r``.

A blind signing of listing ``l`` is valued at ``v_l - lemon_loss * P(lemon | known qualities)``,
with exactly ``lemon_count`` lemons exchangeable over the ``num_listings`` listings. An informed
signing is valued at its true value and a walk does not enter, as in v1. Seat 0's v2 primary is
the sum over its signings of value less rent, less its inspection spend. Where v2's posterior
equals the tenant's stated odds the environment's own recorded expected value is used, so a cell
v2 does not change carries exactly v1's number.

Declared 2026-10-13 for identities frozen after it. v14 was frozen under v1; its published
numbers stand, and its recomputation under v2 is a derived analysis
(``price_reply_conditioned``), not an edit.

Trajectory sources: a sealed cell's event log (``trajectory_from_events``) and an offline market
run with a recording seat 0 (``run_recorded``), so scripted controls are scored by the same code.

Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import collections
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import environment as hz
from . import lemons, price_endpoint, price_reference
from .price_bargaining import LANDLORD_MARGIN

MEASURE_ID = "housing_price_reply_conditioned_v2"
MEASURE: dict[str, Any] = {
    "measure_id": MEASURE_ID,
    "supersedes": "price_endpoint net_expected_response_odds (v1, the v14 primary measure)",
    "value_of_a_blind_signing": "value if sound minus lemon_loss times P(lemon | inspections and informative replies "
                                "up to the decision's round, given the true landlord arm); exactly lemon_count lemons, "
                                "exchangeable",
    "informative_reply": "leaky arm only, offer below the sound floor, lemon target below the floor: a hold below the "
                         "floor proves a lemon, a counter at the floor proves sound; an offer at or above the floor "
                         "and every pooled-arm reply are uninformative",
    "informed_signing": "true value, as in v1",
    "declared": "2026-10-13, for identities frozen after it (HL-D-07)",
}
TOLERANCE = 1e-6
LEAKY = "true_cost"
LEMON = lemons.QUALITY_LABEL[lemons.LEMON]
SOUND = lemons.QUALITY_LABEL[lemons.SOUND]


@dataclass(frozen=True)
class Reply:
    """One landlord reply to seat 0: the round, the listing, seat 0's offer and the binding rent."""

    round_index: int
    listing_id: int
    offer: float
    hold: float


@dataclass
class Trajectory:
    """What seat 0 saw that v2 reads: the round each listing was inspected and every reply."""

    inspections: dict[int, int] = field(default_factory=dict)
    replies: list[Reply] = field(default_factory=list)
    invalid_actions: dict[str, int] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "inspections": [[listing, round_index] for listing, round_index in sorted(self.inspections.items())],
            "replies": [[r.round_index, r.listing_id, r.offer, r.hold] for r in self.replies],
            "invalid_actions": dict(sorted(self.invalid_actions.items())),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Trajectory":
        return cls(
            inspections={int(listing): int(r) for listing, r in row["inspections"]},
            replies=[Reply(int(r), int(l), float(o), float(h)) for r, l, o, h in row["replies"]],
            invalid_actions={str(k): int(v) for k, v in row.get("invalid_actions", {}).items()},
        )


def quality(world: lemons.LemonsWorld, listing_id: int) -> str:
    return lemons.QUALITY_LABEL[world.quality[listing_id]]


def lemon_target(world: lemons.LemonsWorld, listing_id: int, margin: float = LANDLORD_MARGIN) -> float:
    """The rent a leaky-arm lemon landlord would counter at on ``listing_id``, from the price rule."""
    cost = round(max(0.0, float(world.sound_costs[listing_id]) - float(world.lemon_loss)), 2)
    return round(max(cost, min(float(world.ask[listing_id]), cost + margin)), 2)


def reply_quality(world: lemons.LemonsWorld, reply: Reply, margin: float = LANDLORD_MARGIN) -> str | None:
    """What one reply proves about its listing's quality, given the world's true landlord arm."""
    if world.landlord_reservation != LEAKY:
        return None
    floor = price_endpoint.sound_floor(world, reply.listing_id, margin)
    if reply.offer >= floor - TOLERANCE:
        return None
    if lemon_target(world, reply.listing_id, margin) >= floor - TOLERANCE:
        return None  # the two landlords would answer alike: the reply cannot separate them
    if reply.hold < floor - TOLERANCE:
        return LEMON
    if abs(reply.hold - floor) <= TOLERANCE:
        return SOUND
    raise ValueError(f"reply {reply} is above the sound floor {floor} for an offer below it; "
                     "the price landlord's rule cannot give it")


def lemon_posterior(listing_id: int, known: Mapping[int, str], lemon_count: int, num_listings: int) -> float:
    """P(``listing_id`` is a lemon | ``known`` qualities), exactly ``lemon_count`` lemons, exchangeable."""
    if listing_id in known:
        return 1.0 if known[listing_id] == LEMON else 0.0
    unknown = num_listings - len(known)
    lemons_known = sum(q == LEMON for q in known.values())
    return min(1.0, max(0.0, (lemon_count - lemons_known) / unknown))


def knowledge(world: lemons.LemonsWorld, round_index: int, trajectory: Trajectory,
              margin: float = LANDLORD_MARGIN) -> tuple[dict[int, str], dict[int, str]]:
    """(inspected, reply-revealed) qualities seat 0 holds at the commit phase of ``round_index``."""
    inspected = {l: quality(world, l) for l, r in trajectory.inspections.items() if r <= round_index}
    revealed: dict[int, str] = {}
    for reply in trajectory.replies:
        if reply.round_index > round_index:
            continue
        found = reply_quality(world, reply, margin)
        if found is None:
            continue
        if found != quality(world, reply.listing_id):
            raise ValueError(f"reply {reply} proves {found} but the listing is {quality(world, reply.listing_id)}")
        revealed[reply.listing_id] = found
    return inspected, revealed


def score_seat(world: lemons.LemonsWorld, decisions: Sequence[Mapping[str, Any]], trajectory: Trajectory,
               inspection_spend: float, *, seat: int = price_reference.FOCAL_SEAT,
               margin: float = LANDLORD_MARGIN) -> dict[str, Any]:
    """Seat ``seat``'s realized net, its v1 primary and its v2 primary, with every blind signing priced."""
    mine = [d for d in decisions if int(d["tenant_id"]) == seat]
    v1_rows = price_endpoint.score_decisions(world, mine, margin)
    v1 = price_endpoint.seat_view(v1_rows, {f"tenant_{seat}": inspection_spend}, seat)
    loss, count, listings = float(world.lemon_loss), world.lemon_count, world.num_listings
    blind, primary = [], 0.0 - float(inspection_spend)
    replies_by_round = {r.round_index: r for r in trajectory.replies}
    for decision, v1_row in zip(mine, v1_rows):
        if decision["decision"] != "sign":
            continue
        rent, listing, round_index = float(decision["rent"]), int(decision["listing_id"]), int(decision["round_index"])
        if decision["informed"]:
            primary += float(world.values[seat][listing]) - rent
            continue
        inspected, revealed = knowledge(world, round_index, trajectory, margin)
        if listing in inspected:
            raise ValueError(f"decision {decision} is recorded blind but listing {listing} was inspected by then")
        sound_value = float(world.values_if_sound[seat][listing])
        stated = lemon_posterior(listing, inspected, count, listings)
        recorded = float(decision["expected_value"])
        if abs(round(sound_value - stated * loss, 2) - recorded) > 0.011:
            raise ValueError(f"stated odds {stated} do not reproduce the recorded expected value of {decision}")
        posterior = lemon_posterior(listing, {**inspected, **revealed}, count, listings)
        value = recorded if abs(posterior - stated) < 1e-12 else round(sound_value - posterior * loss, 2)
        primary += value - rent
        now = replies_by_round.get(round_index)
        blind.append({
            "round_index": round_index, "listing_id": listing, "rent": rent, "quality": decision["quality"],
            "p_stated": round(stated, 6), "p_v1": round((sound_value - v1_row["expected_value_response"]) / loss, 6),
            "p_v2": round(posterior, 6), "value_v1": v1_row["expected_value_response"], "value_v2": value,
            "reply_this_round": (reply_quality(world, now, margin)
                                 if now is not None and now.listing_id == listing else None),
            "revealed_elsewhere": sorted(q for l, q in revealed.items() if l != listing and l not in inspected),
        })
    changed = [b for b in blind if abs(b["value_v2"] - b["value_v1"]) > 0.005]
    return {
        "net_realized": v1["net_realized"],
        "primary_v1": v1["net_expected_response_odds"],
        "primary_v2": round(primary, 2) + 0.0,  # never -0.0
        "blind_signings": blind,
        "changed_signings": len(changed),
        "informative_replies": sum(reply_quality(world, r, margin) is not None for r in trajectory.replies),
    }


# --- trajectory sources -------------------------------------------------------------------------

_INSPECTION_REF = re.compile(r"inspection:r(\d+):t(\d+):l(\d+)")


def _payload(base: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads((base / event["payload_ref"]).read_text())


def trajectory_from_events(events_path: Path, seat: int = price_reference.FOCAL_SEAT) -> tuple[Trajectory, dict[str, Any]]:
    """Seat ``seat``'s trajectory and the family outcome, from one sealed attempt's event log.

    Inspections come from the inspect transitions' applied verdicts, offers and replies from the
    sealed state's history, and invalid actions from the kernel's parse and legality records (the
    family applies an invalid action as a pass; this counts it by its typed code).
    """
    base = events_path.parent
    seat_id = f"tenant_{seat}"
    trajectory = Trajectory()
    seats: dict[str, str] = {}
    invalid: collections.Counter[str] = collections.Counter()
    state = outcome = None
    for line in events_path.read_text().splitlines():
        event = json.loads(line)
        kind = event["event_type"]
        if kind == "logical_action_started":
            seats[event["logical_action_id"]] = _payload(base, event)["request"]["seat_id"]
        elif kind == "action_parsed" and seats.get(event["logical_action_id"]) == seat_id:
            parsed = _payload(base, event)["parse_result"]
            if not parsed["ok"]:
                invalid[str(parsed["error_code"])] += 1
        elif kind == "action_legality_checked" and seats.get(event["logical_action_id"]) == seat_id:
            legality = _payload(base, event)["legality_result"]
            if not legality["legal"]:
                invalid[str(legality["reason"])] += 1
        elif kind == "transition_applied":
            payload = _payload(base, event)
            if payload["phase_id"] == "inspect":
                for verdict in payload["transition"]["consequences"]["verdicts"]:
                    if verdict["actor_id"] == seat and verdict["outcome"] == "applied":
                        r, tenant, listing = map(int, _INSPECTION_REF.fullmatch(verdict["reference_id"]).groups())
                        if tenant != seat or listing in trajectory.inspections:
                            raise ValueError(f"inspection record {verdict} is not seat {seat}'s first of that listing")
                        trajectory.inspections[listing] = r
            state = payload["transition"]["state"]
        elif kind == "family_outcome_recorded":
            outcome = _payload(base, event)["outcome"]
    if state is None or outcome is None:
        raise ValueError(f"no transition or no family outcome in {events_path}")
    offers: dict[int, tuple[int, float]] = {}
    for item in state["history"]:
        if item.get("tenant_id") != seat:
            continue
        if item["event"] == "offer":
            if item["round_index"] in offers:
                raise ValueError(f"two offers in round {item['round_index']}")
            offers[item["round_index"]] = (int(item["listing_id"]), float(item["rent"]))
        elif item["event"] == "hold":
            listing, offer = offers[item["round_index"]]
            if listing != int(item["listing_id"]):
                raise ValueError(f"hold {item} answers no offer of seat {seat}")
            hold = float(item["binding_rent"])
            if (item["landlord"] == "accepted your offer") != (abs(hold - offer) < 0.005):
                raise ValueError(f"hold {item} says {item['landlord']!r} but binds {hold} against an offer of {offer}")
            trajectory.replies.append(Reply(int(item["round_index"]), listing, offer, hold))
    sealed = {int(i["listing_id"]) for x in state["inspected"] if x["tenant_id"] == seat for i in x["items"]}
    if sealed != set(trajectory.inspections):
        raise ValueError("the sealed state's inspections disagree with the applied inspection verdicts")
    trajectory.invalid_actions = dict(sorted(invalid.items()))
    return trajectory, outcome


class _Recorder:
    """Wraps a seat-0 policy and records what v2 reads from the observations it is given."""

    def __init__(self, policy: price_reference.Policy):
        self.policy = policy
        self.trajectory = Trajectory()
        self._offers: dict[int, tuple[int, float]] = {}

    def __call__(self, observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
        round_index = int(observation["round_index"])
        if phase_id == "contact":
            for row in observation["inspections"]:
                self.trajectory.inspections.setdefault(int(row["listing_id"]), round_index)
        action = self.policy(observation, phase_id)
        if phase_id == "contact" and action["decision"] == "offer":
            self._offers[round_index] = (int(action["listing_id"]), float(action["rent"]))
        if phase_id == "commit":
            hold = lemons._hold_view(observation)
            if hold:
                listing, offer = self._offers[round_index]
                if int(hold["listing_id"]) != listing:
                    raise ValueError(f"hold {hold} answers no offer of seat 0")
                self.trajectory.replies.append(Reply(round_index, listing, offer, float(hold["rent"])))
        return action


def run_recorded(seed: int, arm: str, policy: price_reference.Policy) -> tuple[hz.HousingMarket, Trajectory]:
    """``price_reference.run_world`` with a recording seat 0: the market and what seat 0 saw."""
    recorder = _Recorder(policy)
    market = price_reference.run_world(seed, arm, recorder)
    return market, recorder.trajectory


def score_market(market: hz.HousingMarket, trajectory: Trajectory, seat: int = price_reference.FOCAL_SEAT) -> dict[str, Any]:
    """Score an offline market's seat under v1 and v2."""
    return score_seat(market.world, market.commit_decisions, trajectory, market.inspection_spend[seat], seat=seat)
