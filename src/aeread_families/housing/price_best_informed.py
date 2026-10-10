"""The best informed tenant for the outside-demand price case, by backward induction over what it knows.

``price_reference.inspect_lowball`` is a strong scripted tenant, and the
full-information ceiling knows which listings are lemons. Neither says what a
tenant could earn by deciding as well as possible with what it is shown. This
module computes that. At every step it holds a belief over which two of the
four listings are lemons, and chooses the inspection, the offer and the
sign-or-walk that maximise its expected net over what an inspection could
show, what a landlord could answer, and which unbid listings other tenants
take (each with the declared probability) in the rounds that remain.

Two tenants, differing only in what they have been told.

``stated``: what the v14 prompt states and nothing else. It knows the lemon
count, the loss, the fee, the departure rule and the three rounds. It is not
told how landlords price, so an answer is a price to it and not evidence
about quality, and it plans as if an unseen answer will be the ask.

``pricing``: also told how landlords price, as the v13 notice told its
tenants: a sound landlord's lowest rent is within $55 of the ask, and there
are two kinds of landlord market, one where a lemon's landlord prices on its
own lower cost and one where it prices like a sound one, equally likely. To
this tenant an answer far below the ask proves a lemon, and an ordinary
answer is evidence the listing is sound.

Both always offer zero: the landlord answers any offer below its lowest rent
with that rent, so nothing is lost by asking and the answer is the price.

One approximation. Landlords' lowest rents differ by up to $60 from listing
to listing in a way no tenant can see before asking. The tenant plans with the
average for a listing it has not asked about and uses the true answer once it
has it. The plan is exact given that; the realised nets below are the
market's own.

Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from typing import Any, Mapping, Sequence

from aeread_families.housing import lemons, price_bargaining, price_outside_demand, price_reference

ROUNDS = price_outside_demand.ROUNDS
RATE = price_outside_demand.RATE
#: A sound landlord's lowest rent is its cost plus the margin, and its cost is $20 to $80 under the ask.
SOUND_DISCOUNT_MEAN = 50.0
LOW_BELOW_ASK = price_outside_demand.SOUND_FLOOR_MAX_BELOW_ASK
ARMS = ("true_cost", "pooled")
UNKNOWN, SOUND, LEMON = "?", "S", "L"
UNSEEN, ORDINARY, LOW = "-", "N", "L"
KNOWLEDGE = ("stated", "pricing")


class Tenant:
    """One tenant in one world. Call it as ``tenant(observation, phase_id)``."""

    def __init__(self, knowledge: str):
        if knowledge not in KNOWLEDGE:
            raise ValueError(f"knowledge must be one of {KNOWLEDGE}")
        self.reads_answers = knowledge == "pricing"
        self.answers: dict[int, float] = {}
        self.signed_blind = False
        self.plan_value: float | None = None
        self._memo: dict[Any, float] = {}
        self._belief: dict[Any, tuple[tuple[float, ...], tuple[float, ...]]] = {}

    # --- what the tenant is shown -------------------------------------------------

    def _read(self, observation: Mapping[str, Any]) -> None:
        board = sorted(observation["board"], key=lambda row: int(row["listing_id"]))
        self.n = len(board)
        self.ask = [float(row["rent_asked"]) for row in board]
        self.open = tuple(row["status"] == "OPEN" for row in board)
        self.value = [float(v) for v in observation["private_values_if_sound"]]
        self.loss = float(observation["lemon_loss"])
        self.fee = float(observation["inspection_cost"])
        self.lemon_count = int(observation["lemon_count"])
        self.round = int(observation["round_index"])
        seen = lemons._inspection_lookup(observation)
        label = {lemons.QUALITY_LABEL[lemons.SOUND]: SOUND, lemons.QUALITY_LABEL[lemons.LEMON]: LEMON}
        self.quality = tuple(label[seen[l]] if l in seen else UNKNOWN for l in range(self.n))
        hold = lemons._hold_view(observation)
        if hold:
            self.answers[int(hold["listing_id"])] = float(hold["rent"])
        self.answer = tuple(self._class(l, self.answers[l]) if l in self.answers else UNSEEN for l in range(self.n))
        table = tuple(sorted(self.answers.items()))
        if getattr(self, "_table", None) != table:  # a new true answer changes prices: plan again
            self._table, self._memo = table, {}

    def _class(self, listing: int, rent: float) -> str:
        return LOW if rent < self.ask[listing] - LOW_BELOW_ASK - 0.005 else ORDINARY

    def _price(self, listing: int, kind: str) -> float:
        if listing in self.answers and self._class(listing, self.answers[listing]) == kind:
            return self.answers[listing]
        if not self.reads_answers:
            return self.ask[listing]
        ordinary = self.ask[listing] - SOUND_DISCOUNT_MEAN + price_bargaining.LANDLORD_MARGIN
        if kind == ORDINARY:
            return min(self.ask[listing], ordinary)
        cost = max(0.0, self.ask[listing] - SOUND_DISCOUNT_MEAN - self.loss)
        return min(self.ask[listing], cost + price_bargaining.LANDLORD_MARGIN)

    # --- belief --------------------------------------------------------------------

    def _beliefs(self, quality: tuple[str, ...], answer: tuple[str, ...]) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """(chance each listing is a lemon, chance an unseen answer on each listing would be low)."""
        key = (quality, answer)
        if key not in self._belief:
            lemon = [0.0] * self.n
            low = [0.0] * self.n
            total = 0.0
            arms = ARMS if self.reads_answers else ("pooled",)
            for arm in arms:
                for subset in itertools.combinations(range(self.n), self.lemon_count):
                    bad = set(subset)
                    if any((q == LEMON) != (l in bad) for l, q in enumerate(quality) if q != UNKNOWN):
                        continue
                    if self.reads_answers and any(
                        a != UNSEEN and (a == LOW) != (arm == "true_cost" and l in bad) for l, a in enumerate(answer)
                    ):
                        continue
                    total += 1.0
                    for l in bad:
                        lemon[l] += 1.0
                        if arm == "true_cost":
                            low[l] += 1.0
            if total == 0.0:  # an answer the tenant's picture of the market cannot explain: keep the inspections only
                return self._beliefs(quality, tuple(UNSEEN for _ in answer))
            self._belief[key] = (tuple(x / total for x in lemon), tuple(x / total for x in low))
        return self._belief[key]

    # --- the plan --------------------------------------------------------------------

    def _start(self, r: int, open_: tuple[bool, ...], quality: tuple[str, ...], answer: tuple[str, ...]) -> float:
        """Expected net from the start of round ``r``, before fees already paid."""
        if r >= ROUNDS or not any(open_):
            return 0.0
        key = ("start", r, open_, quality, answer)
        if key not in self._memo:
            self._memo[key] = max(v for _, v in self._inspections(r, open_, quality, answer))
        return self._memo[key]

    def _inspections(self, r, open_, quality, answer):
        yield None, self._offer_stage(r, open_, quality, answer)
        lemon, _ = self._beliefs(quality, answer)
        for l in range(self.n):
            if open_[l] and quality[l] == UNKNOWN and 0.0 < lemon[l] < 1.0:
                after = lambda q: tuple(q if i == l else x for i, x in enumerate(quality))  # noqa: E731
                yield l, -self.fee + lemon[l] * self._offer_stage(r, open_, after(LEMON), answer) + (
                    1.0 - lemon[l]) * self._offer_stage(r, open_, after(SOUND), answer)

    def _offer_stage(self, r, open_, quality, answer) -> float:
        key = ("offer", r, open_, quality, answer)
        if key not in self._memo:
            self._memo[key] = max(v for _, v in self._offers(r, open_, quality, answer))
        return self._memo[key]

    def _offers(self, r, open_, quality, answer):
        yield None, self._end(r, open_, quality, answer, None)
        _, low = self._beliefs(quality, answer)
        for l in range(self.n):
            if not open_[l]:
                continue
            if answer[l] != UNSEEN:
                yield l, self._commit(r, open_, quality, answer, l)[1]
                continue
            seen = lambda a: tuple(a if i == l else x for i, x in enumerate(answer))  # noqa: E731
            p = low[l] if self.reads_answers else 0.0
            value = (1.0 - p) * self._commit(r, open_, quality, seen(ORDINARY), l)[1]
            if p > 0.0:
                value += p * self._commit(r, open_, quality, seen(LOW), l)[1]
            yield l, value

    def _commit(self, r, open_, quality, answer, listing) -> tuple[bool, float]:
        """(sign?, value) holding the landlord's answer on ``listing``."""
        lemon, _ = self._beliefs(quality, answer)
        sign = self.value[listing] - self.loss * lemon[listing] - self._price(listing, answer[listing])
        walk = self._end(r, open_, quality, answer, listing)
        return (sign >= walk, max(sign, walk))

    def _end(self, r, open_, quality, answer, bid) -> float:
        """The end of a round: each open listing the tenant did not bid on is taken with the declared probability."""
        if r + 1 >= ROUNDS:
            return 0.0
        key = ("end", r, open_, quality, answer, bid)
        if key not in self._memo:
            at_risk = [l for l in range(self.n) if open_[l] and l != bid]
            total = 0.0
            for taken in itertools.product((False, True), repeat=len(at_risk)):
                gone = {l for l, t in zip(at_risk, taken) if t}
                chance = RATE ** len(gone) * (1.0 - RATE) ** (len(at_risk) - len(gone))
                total += chance * self._start(r + 1, tuple(o and l not in gone for l, o in enumerate(open_)), quality, answer)
            self._memo[key] = total
        return self._memo[key]

    # --- acting --------------------------------------------------------------------

    def __call__(self, observation: Mapping[str, Any], phase_id: str) -> dict[str, Any]:
        self._read(observation)
        state = (self.round, self.open, self.quality, self.answer)
        if phase_id == "inspect":
            if self.plan_value is None:
                self.plan_value = self._start(*state)
            choice = max(self._inspections(*state), key=lambda cv: (cv[1], cv[0] is None))[0]
            return lemons._pass(phase_id) if choice is None else {"decision": "inspect", "listing_id": choice}
        if phase_id == "contact":
            choice = max(self._offers(*state), key=lambda cv: (cv[1], cv[0] is not None))[0]
            if choice is None:
                return lemons._pass(phase_id)
            return {"decision": "offer", "listing_id": choice, "rent": price_reference.LOWBALL_OFFER}
        if phase_id == "commit":
            hold = lemons._hold_view(observation)
            if not hold:
                return lemons._pass(phase_id)
            listing = int(hold["listing_id"])
            sign, _ = self._commit(self.round, self.open, self.quality, self.answer, listing)
            if sign and self.quality[listing] == UNKNOWN:
                self.signed_blind = True
            return {"decision": "sign" if sign else "walk", "hold_id": hold["hold_id"]}
        raise ValueError(f"unknown phase: {phase_id}")


def play(seed: int, arm: str, knowledge: str) -> dict[str, Any]:
    """One world through the real market with the best informed tenant at seat 0."""
    tenant = Tenant(knowledge)
    market = price_reference.run_world(seed, arm, tenant)
    seat = price_reference.FOCAL_SEAT
    leased = dict(market.pairs)
    return {
        "world_seed": int(seed), "arm": arm, "knowledge": knowledge,
        "net": price_reference.seat_net(market),
        "plan_value": round(float(tenant.plan_value or 0.0), 2),
        "signed": seat in leased,
        "signed_lemon": seat in leased and market.world.quality[leased[seat]] == lemons.LEMON,
        "signed_blind": tenant.signed_blind,
        "inspections": round(market.inspection_spend[seat] / market.world.inspection_cost),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--first-seed", type=int, default=300000)
    parser.add_argument("--worlds", type=int, default=20)
    args = parser.parse_args(argv)
    out = {}
    for knowledge in KNOWLEDGE:
        cells = [play(seed, arm, knowledge) for seed in range(args.first_seed, args.first_seed + args.worlds) for arm in ARMS]
        out[knowledge] = {"net_mean": round(statistics.fmean(c["net"] for c in cells), 2),
                          "plan_value_mean": round(statistics.fmean(c["plan_value"] for c in cells), 2)}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
