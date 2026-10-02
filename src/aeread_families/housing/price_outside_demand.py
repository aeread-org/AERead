"""Outside demand for the Housing price pilot: one deciding tenant, four landlords.

The six-tenant pilots measured mostly who won a contested listing. With six
sampled copies the opening round differed between the two landlord arms in 48
of 57 worlds before either landlord had replied; with scripted rivals the focal
seat was shut out of sound listings by a one-dollar overbid and a tie-break by
seat number it was never told about. Neither is the tenant's judgement.

This module keeps the pressure those rivals stood for, sign now or lose the
listing, and removes their behaviour. Seat 0 is the only tenant that decides.
Seats 1 to 4 are outside demand, one per listing; seat 5 is idle. At the end of
each round every open listing on which seat 0 made no offer is taken with a
declared probability, the same for a sound listing and a lemon.

How a take happens, using only the market's existing rules: the outside seat
for a wanted listing offers ``OPENING_OFFER``; the fixed landlord counters at
its own target; the seat signs. If seat 0 offered on that listing in the same
round, its offer is the higher one, the landlord answers seat 0, and the
outside seat is rejected, so the listing cannot be taken in a round in which
seat 0 bid on it, whether seat 0 then signs or walks.

Which listing is wanted in which round is a function of the world alone (the
rule id, the board's asks, the listing and the round), so both landlord arms,
every replicate and every model meet the same departures. Nothing here reads
quality, a tenant's value, or what seat 0 did.

Nothing in this module is hashed into a Housing plan: the market, the runner
and the prompt are the sealed ones. Seat 0 is told the rule by a notice the
seat router appends to its instructions; the kernel's ``provider_call_started``
event records the request as the plan built it, without the notice, so the
contract carries the notice text and its digest and ``seat_calls.jsonl`` records
the digest of the instructions each focal call actually sent.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Callable, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure

from .runner import _scripted_result

RULE_ID = "housing_outside_demand_v1"
PROVIDER = "housing_outside_demand"
MODEL = "housing_outside_demand_tenant_v1"
REVISION = "1.0.0"

#: Per round, per open listing seat 0 did not bid on. Rivals in the six-tenant
#: pilots took 35 to 70 percent of the still-open sound listings each round.
RATE = 0.5
#: The outside seat's opening offer. Zero is below any offer seat 0 can make,
#: and a tie at zero goes to the lower seat, so the landlord always answers
#: seat 0 first when both want the same listing.
OPENING_OFFER = 0.0

FOCAL_SEAT = 0
#: Seats 1..4 each stand for outside demand on one listing; seat 5 never acts.
OUTSIDE_SEATS = (1, 2, 3, 4, 5)

FOCAL_NOTICE = (
    "\nOther tenants are searching too. At the end of every round, each open listing on "
    "which you made no offer in that round is taken by another tenant with probability "
    f"{RATE}, independently, whether it is sound or a lemon, and is then no longer open. "
    "A listing on which you made an offer in a round is not taken in that round, whether "
    "you sign it or walk away."
)
FOCAL_NOTICE_SHA256 = hashlib.sha256(FOCAL_NOTICE.encode("utf-8")).hexdigest()


def listing_for_seat(tenant_id: int) -> int | None:
    """The one listing an outside seat stands for, or ``None`` for an idle seat."""
    listing_id = int(tenant_id) - 1
    return listing_id if 0 <= listing_id < 4 else None


def wanted(asks: list[float] | tuple[float, ...], listing_id: int, round_index: int,
           rate: float = RATE) -> bool:
    """Whether outside demand wants ``listing_id`` in ``round_index`` of this world.

    Keyed on the board's asks, which the world seed fixes and both landlord arms
    share, so a scripted seat can compute it from its own observation.
    """
    key = canonical_json_bytes({
        "rule": RULE_ID,
        "asks": [round(float(ask), 2) for ask in asks],
        "listing_id": int(listing_id),
        "round_index": int(round_index),
    })
    draw = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") / 2.0 ** 64
    return draw < rate


def schedule(asks: list[float] | tuple[float, ...], rounds: int, rate: float = RATE) -> list[list[bool]]:
    """``schedule[round][listing]``: the whole world's outside demand, for analysis."""
    return [[wanted(asks, listing, r, rate) for listing in range(len(asks))] for r in range(rounds)]


def outside_demand_action(observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
    """One outside seat's move: a function of its own observation and nothing else."""
    if phase_id == "inspect":
        return {"decision": "pass", "listing_id": None}
    if phase_id == "contact":
        listing_id = listing_for_seat(int(observation["tenant_id"]))
        board = sorted(observation["board"], key=lambda row: int(row["listing_id"]))
        row = next((r for r in board if int(r["listing_id"]) == listing_id), None)
        if row is None or row["status"] != "OPEN":
            return {"decision": "pass", "listing_id": None, "rent": None}
        asks = [float(r["rent_asked"]) for r in board]
        if not wanted(asks, listing_id, int(observation["round_index"])):
            return {"decision": "pass", "listing_id": None, "rent": None}
        return {"decision": "offer", "listing_id": listing_id, "rent": OPENING_OFFER}
    if phase_id == "commit":
        hold = observation.get("active_hold")
        if hold is None:
            return {"decision": "pass", "hold_id": None}
        hold_id = hold["hold_id"] if isinstance(hold, Mapping) else hold.hold_id
        return {"decision": "sign", "hold_id": hold_id}
    raise ValueError(f"unknown phase: {phase_id}")


class OutsideDemandProvider:
    """Answers the outside seats. Costs nothing and calls nobody."""

    async def complete(self, request: Any) -> Any:
        if request.provider != PROVIDER or request.model != MODEL or request.revision != REVISION:
            raise ProviderFailure("provider_contract", "wrong outside-demand provider", retryable=False)
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        if int(observation["tenant_id"]) not in OUTSIDE_SEATS:
            raise ProviderFailure("provider_contract", "outside demand asked to play the focal seat", retryable=False)
        return _scripted_result(request, outside_demand_action(observation, payload["phase_id"]))


def block() -> dict[str, Any]:
    """What a contract must declare about the outside seats and the notice."""
    return {
        "kind": "outside_demand", "rule_id": RULE_ID, "model": MODEL, "revision": REVISION,
        "seats": list(OUTSIDE_SEATS), "focal_seat": FOCAL_SEAT,
        "rate_per_round": RATE, "opening_offer_usd": OPENING_OFFER,
        "applies_to": "open listings the focal seat made no offer on in that round",
        "quality_dependence": "none",
        "schedule_key": "sha256(rule_id, board asks, listing_id, round_index)",
        "focal_notice": FOCAL_NOTICE, "focal_notice_sha256": FOCAL_NOTICE_SHA256,
        "focal_notice_delivery": "appended to the focal seat's instructions by the seat router; "
                                 "not in the kernel's provider_call_started request",
    }


def rival_rewrite(request: Any) -> Any:
    return dataclasses.replace(request, provider=PROVIDER, model=MODEL, revision=REVISION)


def focal_rewrite(request: Any) -> Any:
    return dataclasses.replace(request, instructions=request.instructions + FOCAL_NOTICE)


def instructions_sha256(request: Any) -> str:
    return hashlib.sha256(request.instructions.encode("utf-8")).hexdigest()


Rewrite = Callable[[Any], Any]
