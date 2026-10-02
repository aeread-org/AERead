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


# --- notice v2: the horizon, and what the landlords already answered -------------------------
#
# The v10 panels left two things out of what the tenant could know (case.md, "What this panel
# does not control"). It was never told the market lasts three rounds, so it could not weigh
# signing now against inspecting first; and after it walked from a hold its observation kept
# only ``rejected_listing_ids``, not the rent the landlord had named, so nothing it learned
# from a reply survived the round. Notice v2 states the horizon and appends the tenant's own
# earlier offers, the landlords' binding rents and its decisions. The history holds only what
# the tenant itself did or was shown; nothing about quality, costs or the departure schedule.

ROUNDS = 3
FOCAL_NOTICE_V2 = FOCAL_NOTICE + (
    f"\nThe market lasts {ROUNDS} rounds, round_index 0 to {ROUNDS - 1}; nothing can be signed "
    "after the last round. Walking away from a hold does not close the listing to you: while it "
    "is still open you may offer on it again in a later round."
)
FOCAL_NOTICE_V2_SHA256 = hashlib.sha256(FOCAL_NOTICE_V2.encode("utf-8")).hexdigest()
HISTORY_HEADER = "\nYour earlier offers in this market and the landlords' answers:"


def block_v2() -> dict[str, Any]:
    """The outside-demand block of a contract that uses notice v2."""
    return {
        **block(), "notice_version": 2, "rounds_stated": ROUNDS,
        "focal_notice": FOCAL_NOTICE_V2, "focal_notice_sha256": FOCAL_NOTICE_V2_SHA256,
        "focal_history": "own offers, landlords' binding rents and own commit decisions of this "
                         "cell, appended after the notice; each call's text is in seat_calls.jsonl",
    }


def _history_line(round_index: int, entry: Mapping[str, Any], *, current: bool) -> str | None:
    offer, hold, commit = entry.get("offer"), entry.get("hold"), entry.get("commit")
    when = f"round_index {round_index}" + (" (this round)" if current else "")
    if offer is None and hold is None:
        return None if current else f"- {when}: you made no offer."
    parts = [f"- {when}:"]
    if offer is not None:
        parts.append(f"you offered {offer[1]} on listing {offer[0]};")
    if hold is None:
        if current:
            return None
        parts.append("you got no hold.")
        return " ".join(parts)
    if offer is not None and hold[0] == offer[0] and abs(float(hold[1]) - float(offer[1])) < 0.005:
        parts.append(f"the landlord accepted, a binding rent of {hold[1]};")
    else:
        parts.append(f"the landlord's binding rent for listing {hold[0]} was {hold[1]};")
    if current:
        parts.append("you now sign or walk.")
    elif commit == "sign":
        parts.append("you signed.")
    elif commit == "walk":
        parts.append("you walked away.")
    else:
        parts.append("the hold expired unsigned.")
    return " ".join(parts)


class FocalNoticeV2:
    """Appends notice v2 and the cell's reply history to the focal seat's instructions.

    One instance serves one process, which runs its cells one after another; a request for
    round 0's inspection starts a new cell. Entries are keyed by round, so a call the kernel
    retries rewrites the same entry.
    """

    def __init__(self) -> None:
        self._rounds: dict[int, dict[str, Any]] = {}
        self._last_history = ""

    def history(self, round_index: int, phase_id: str) -> str:
        lines = []
        for r in sorted(self._rounds):
            if r > round_index:
                continue
            current = r == round_index
            if current and phase_id != "commit":
                continue
            line = _history_line(r, self._rounds[r], current=current)
            if line:
                lines.append(line)
        return (HISTORY_HEADER + "\n" + "\n".join(lines)) if lines else ""

    def rewrite(self, request: Any) -> Any:
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        round_index, phase_id = int(observation["round_index"]), payload["phase_id"]
        if round_index == 0 and phase_id == "inspect":
            self._rounds = {}
        entry = self._rounds.setdefault(round_index, {})
        if phase_id == "commit":
            hold = observation.get("active_hold")
            entry["hold"] = (int(hold["listing_id"]), float(hold["rent"])) if hold else None
        self._last_history = self.history(round_index, phase_id)
        return dataclasses.replace(
            request, instructions=request.instructions + FOCAL_NOTICE_V2 + self._last_history
        )

    def after(self, request: Any, sent: Any, result: Any) -> dict[str, Any]:
        """Record what the tenant just did; returns the fields the seat log keeps."""
        payload = json.loads(request.input_text)
        round_index, phase_id = int(payload["observation"]["round_index"]), payload["phase_id"]
        entry = self._rounds.setdefault(round_index, {})
        try:
            action = json.loads(result.output_text)
        except (TypeError, ValueError):
            action = {}
        if not isinstance(action, Mapping):
            action = {}
        if phase_id == "contact":
            valid = action.get("decision") == "offer" and isinstance(action.get("rent"), (int, float)) \
                and isinstance(action.get("listing_id"), int)
            entry["offer"] = (int(action["listing_id"]), float(action["rent"])) if valid else None
        elif phase_id == "commit":
            entry["commit"] = action.get("decision") if action.get("decision") in ("sign", "walk") else None
        return {"instructions_sha256": instructions_sha256(sent), "history": self._last_history}


def rival_rewrite(request: Any) -> Any:
    return dataclasses.replace(request, provider=PROVIDER, model=MODEL, revision=REVISION)


def focal_rewrite(request: Any) -> Any:
    return dataclasses.replace(request, instructions=request.instructions + FOCAL_NOTICE)


def instructions_sha256(request: Any) -> str:
    return hashlib.sha256(request.instructions.encode("utf-8")).hexdigest()


Rewrite = Callable[[Any], Any]
