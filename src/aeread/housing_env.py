"""Housing assignment market: world generator, assignment-game oracle, baselines.

Tenants compete for a smaller number of listings. Each tenant has a private
willingness to pay per listing and each landlord a private reservation cost, so a
match is worth ``v[t][l] - c[l]`` and the rent agreed splits that surplus without
creating it. What varies, and what is scored, is who ends up matched with whom.

The implemented oracle is max-weight bipartite matching on the surplus matrix.
Core-rent intervals are a possible future price diagnostic, not part of the current
implementation. Deferred acceptance is deliberately NOT used. DA assumes
non-transferable utility, and rent here is negotiable; it is also strategyproof on
the proposing side, which would leave nothing to measure.

Mechanisms. ``resolve`` is a serial-dictatorship variant kept for reference only:
it is strategyproof, so truthful ranking is dominant and realized-vs-optimal
measures the mechanism's own inefficiency rather than agent behaviour.
``resolve_bids`` is a one-shot sealed-bid market. ``HousingMarket`` is the
multi-round contact/respond/commit market, a step-wise state machine so a scripted
policy and an agent driver go through the identical interface.

Worlds. ``make_bid_world`` draws valuations abstractly. ``make_attr_world`` derives
them from listing attributes and a per-tenant weight vector, so the agent must
compute its own value rather than being handed one, and ``adherence`` measures
whether it applied its own weights.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Listing:
    listing_id: int
    rent_asked: int
    beds: int
    baths: int
    minutes_to_campus: int
    crime_index: float
    minutes_to_groceries: int
    orientation: str = "South"


@dataclass(frozen=True)
class HousingWorld:
    listings: List[Listing]
    surplus: List[List[float]]  # surplus[tenant][listing]

    @property
    def num_tenants(self) -> int:
        return len(self.surplus)

    @property
    def num_listings(self) -> int:
        return len(self.listings)


@dataclass(frozen=True)
class Assignment:
    pairs: List[Tuple[int, int]]  # (tenant, listing), sorted by tenant
    total: float
    unhoused: int


def make_housing_world(
    num_tenants: int,
    num_listings: int,
    seed: int,
    common_weight: float = 0.6,
) -> HousingWorld:
    """Seeded market.

    Tenant value has a common component (everybody agrees which listings are
    good, which is what creates congestion) and an idiosyncratic component
    (which is what makes the *correct* assignment differ from the popular one).
    Landlord reservation cost is subtracted, so a poor match has negative
    surplus and should not be leased at all.
    """
    rng = random.Random(seed)
    listings = [
        Listing(
            listing_id=l,
            rent_asked=int(rng.uniform(1500, 3200)),
            beds=rng.randint(1, 3),
            baths=rng.randint(1, 2),
            minutes_to_campus=rng.randint(5, 45),
            crime_index=round(rng.uniform(1.0, 10.0), 1),
            minutes_to_groceries=rng.randint(3, 25),
        )
        for l in range(num_listings)
    ]
    common = [rng.uniform(0.0, 1.0) for _ in range(num_listings)]
    surplus: List[List[float]] = []
    for _ in range(num_tenants):
        row = []
        for l in range(num_listings):
            idio = rng.uniform(0.0, 1.0)
            value = common_weight * common[l] + (1.0 - common_weight) * idio
            row.append(round(value * 100.0 - 30.0, 2))
        surplus.append(row)
    return HousingWorld(listings=listings, surplus=surplus)


def assignment_oracle(surplus: Sequence[Sequence[float]]) -> Assignment:
    """Max-weight bipartite matching; pairs with non-positive surplus are dropped."""
    n = len(surplus)
    m = len(surplus[0]) if n else 0
    size = max(n, m)
    padded = [[0.0] * size for _ in range(size)]
    for t in range(n):
        for l in range(m):
            padded[t][l] = max(0.0, float(surplus[t][l]))

    from scipy.optimize import linear_sum_assignment  # local: scipy is heavy

    rows, cols = linear_sum_assignment(padded, maximize=True)
    pairs = [
        (int(t), int(l))
        for t, l in zip(rows, cols)
        if t < n and l < m and float(surplus[t][l]) > 0.0
    ]
    pairs.sort()
    total = round(sum(float(surplus[t][l]) for t, l in pairs), 2)
    return Assignment(pairs=pairs, total=total, unhoused=n - len(pairs))


def selfish_rankings(world: HousingWorld) -> Dict[int, List[int]]:
    """Rank by own surplus, descending, omitting listings not worth leasing.

    No reasoning about what anyone else wants. This is the baseline a model must
    beat to have demonstrated any coordination at all.
    """
    return {
        t: [
            l
            for l in sorted(range(world.num_listings), key=lambda x: -world.surplus[t][x])
            if world.surplus[t][l] > 0.0
        ]
        for t in range(world.num_tenants)
    }


def random_rankings(world: HousingWorld, seed: int) -> Dict[int, List[int]]:
    rng = random.Random(seed)
    out: Dict[int, List[int]] = {}
    for t in range(world.num_tenants):
        order = list(range(world.num_listings))
        rng.shuffle(order)
        out[t] = order
    return out


def resolve(world: HousingWorld, rankings: Dict[int, List[int]]) -> Assignment:
    """Public priority rule: lower tenant id gets first refusal.

    Each tenant is assigned the first still-available listing on its stated
    ranking. The rule is public, so a high-id tenant that ranks the popular
    listing first has made a coordination error, not suffered bad luck.
    """
    taken: set = set()
    pairs: List[Tuple[int, int]] = []
    for t in range(world.num_tenants):
        for l in rankings.get(t, []):
            if l in taken or not (0 <= l < world.num_listings):
                continue
            taken.add(l)
            pairs.append((t, l))
            break
    total = round(sum(world.surplus[t][l] for t, l in pairs), 2)
    return Assignment(pairs=pairs, total=total, unhoused=world.num_tenants - len(pairs))


# ---------------------------------------------------------------------------
# Sealed-bid market
#
# The serial-dictatorship variant above is retained for reference but is NOT a
# strategic environment: truthful ranking is a dominant strategy there (verified
# exhaustively), so realized-vs-optimal measures mechanism inefficiency, not
# agent behaviour. Under unit-demand sealed bidding a tenant must choose which
# listing to contest and how much to bid, and losing a contest pays nothing.
# The returned total is allocation welfare, however, so it can measure whether
# bids route listings to high-surplus matches but not whether a tenant shaded its
# bid well or retained a positive private payoff.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BidWorld:
    listings: List[Listing]
    values: List[List[float]]   # values[tenant][listing]: willingness to pay
    costs: List[float]          # landlord reservation cost per listing
    ask: List[float]            # posted asking rent per listing

    @property
    def num_tenants(self) -> int:
        return len(self.values)

    @property
    def num_listings(self) -> int:
        return len(self.listings)

    @property
    def surplus(self) -> List[List[float]]:
        return [[v - self.costs[l] for l, v in enumerate(row)] for row in self.values]


def make_bid_world(num_tenants: int, num_listings: int, seed: int,
                   common_weight: float = 0.6) -> BidWorld:
    base = make_housing_world(num_tenants, num_listings, seed, common_weight)
    rng = random.Random(seed * 7919 + 13)
    ask = [float(l.rent_asked) for l in base.listings]
    # The ask is public and the reservation cost is private.  Drawing a stable
    # non-zero markup prevents the public board from revealing the private type.
    costs = [round(max(0.0, price - rng.uniform(20.0, 80.0)), 2) for price in ask]
    values = [
        [round(ask[l] + base.surplus[t][l] * 10.0 + rng.uniform(-20, 20), 2)
         for l in range(num_listings)]
        for t in range(num_tenants)
    ]
    return BidWorld(listings=base.listings, values=values, costs=costs, ask=ask)


def resolve_bids(world: BidWorld, bids: Dict[int, Tuple[int, float]]) -> Assignment:
    """Resolve well-formed bids and report allocation welfare, not tenant payoff.

    Each listing goes to its highest bidder at or above ask, with ties broken by
    tenant id. Malformed tenant ids, listing ids, bid containers, and non-finite
    amounts are ignored independently so they cannot win or block other bids.
    Because rent is a transfer, ``Assignment.total`` measures the welfare of the
    resulting matching; it does not evaluate bid shading or individual rationality.
    """
    best: Dict[int, Tuple[float, int]] = {}
    valid_tenants = sorted(
        t
        for t in bids
        if isinstance(t, int)
        and not isinstance(t, bool)
        and 0 <= t < world.num_tenants
    )
    for t in valid_tenants:
        entry = bids.get(t)
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        l, amount = entry
        if not (isinstance(l, int) and not isinstance(l, bool)
                and 0 <= l < world.num_listings):
            continue
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        try:
            amount = float(amount)
        except (OverflowError, TypeError, ValueError):
            continue
        if not math.isfinite(amount):
            continue
        if amount < world.ask[l]:
            continue
        cur = best.get(l)
        if cur is None or amount > cur[0]:
            best[l] = (amount, t)
    pairs = sorted((t, l) for l, (_, t) in best.items())
    total = round(sum(world.values[t][l] - world.costs[l] for t, l in pairs), 2)
    return Assignment(pairs=pairs, total=total, unhoused=world.num_tenants - len(pairs))


def naive_top_bids(world: BidWorld, margin: float = 1.0) -> Dict[int, Tuple[int, float]]:
    """Bid the minimum on your own favourite listing. No thought about rivals."""
    out: Dict[int, Tuple[int, float]] = {}
    for t in range(world.num_tenants):
        gains = [world.values[t][l] - world.ask[l] for l in range(world.num_listings)]
        l = max(range(world.num_listings), key=lambda x: gains[x])
        if gains[l] <= 0:
            continue
        out[t] = (l, world.ask[l] + margin)
    return out


def truthful_top_bids(world: BidWorld) -> Dict[int, Tuple[int, float]]:
    """Bid your full valuation on your favourite listing: wins often, captures nothing."""
    out: Dict[int, Tuple[int, float]] = {}
    for t in range(world.num_tenants):
        gains = [world.values[t][l] - world.ask[l] for l in range(world.num_listings)]
        l = max(range(world.num_listings), key=lambda x: gains[x])
        if gains[l] <= 0:
            continue
        out[t] = (l, world.values[t][l])
    return out


# ---------------------------------------------------------------------------
# Multi-round market: contact -> respond -> commit
#
# Step-wise so a scripted policy and an LLM driver drive it identically. Only the
# final allocation is scored, so the oracle is unchanged by the extra structure.
# A tenant sends ONE offer per round: that scarcity is what makes choosing which
# listing to contest a real decision.
# ---------------------------------------------------------------------------


class PhaseOrderError(ValueError):
    """The harness attempted to apply a market phase out of order."""


@dataclass(frozen=True)
class Offer:
    offer_id: str
    tenant_id: int
    listing_id: int
    rent: float
    round_index: int


@dataclass(frozen=True)
class Hold:
    hold_id: str
    tenant_id: int
    listing_id: int
    rent: float
    round_index: int


@dataclass(frozen=True)
class ActionVerdict:
    actor_id: int
    phase: str
    outcome: str
    reason: Optional[str] = None
    reference_id: Optional[str] = None


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    verdicts: Dict[int, ActionVerdict]
    inbox: Dict[int, Tuple[Offer, ...]] = field(default_factory=dict)
    holds: Dict[int, Hold] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalEconomics:
    assignment: Assignment
    signed_rents: Dict[int, float]
    tenant_payoffs: Dict[int, float]
    landlord_payoffs: Dict[int, float]
    social_welfare: float
    ir_violations: Tuple[str, ...]


class HousingMarket:
    def __init__(self, world: BidWorld, rounds: int = 4):
        if rounds < 0:
            raise ValueError("rounds must be non-negative")
        self.world = world
        self.rounds = rounds
        self.round_index = 0
        self.pairs: List[Tuple[int, int]] = []
        self.signed_rent: Dict[int, float] = {}
        self._taken: set = set()
        self._matched: set = set()
        self._offers: Dict[int, Tuple[Offer, ...]] = {}
        self._holds: Dict[int, Hold] = {}
        self.rejected: Dict[int, set] = {t: set() for t in range(world.num_tenants)}
        self.wasted_contacts = 0
        self.phase = "finished" if self.finished else "contact"

    # -- state -------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return (self.round_index >= self.rounds
                or not self.unmatched_tenants()
                or not self.open_listings())

    def open_listings(self) -> List[int]:
        return [l for l in range(self.world.num_listings) if l not in self._taken]

    def unmatched_tenants(self) -> List[int]:
        return [t for t in range(self.world.num_tenants) if t not in self._matched]

    def board(self) -> List[Dict[str, Any]]:
        out = []
        for l in self.world.listings:
            out.append({
                "listing_id": l.listing_id,
                "rent_asked": self.world.ask[l.listing_id],
                "beds": l.beds,
                "baths": l.baths,
                "minutes_to_campus": l.minutes_to_campus,
                "crime_index": l.crime_index,
                "minutes_to_groceries": l.minutes_to_groceries,
                "orientation": l.orientation,
                "status": "LEASED" if l.listing_id in self._taken else "OPEN",
            })
        return out

    def active_holds(self) -> Dict[int, Hold]:
        """Return a copy of the current tenant-to-hold index."""
        return dict(self._holds)

    def tenant_observation(self, tenant_id: int) -> Dict[str, Any]:
        """Information visible to one tenant; other private types are omitted."""
        if not self._valid_tenant(tenant_id):
            raise ValueError(f"unknown tenant {tenant_id!r}")
        out: Dict[str, Any] = {
            "role": "tenant",
            "tenant_id": tenant_id,
            "round_index": self.round_index,
            "phase": self.phase,
            "board": self.board(),
            "rejected_listing_ids": sorted(self.rejected[tenant_id]),
            "active_hold": self._holds.get(tenant_id),
        }
        if hasattr(self.world, "weights"):
            out["private_weights"] = list(self.world.weights[tenant_id])
            out["valuation_formula"] = {
                "attributes": ATTRIBUTES,
                "attribute_scores": (
                    "campus=10-minutes_to_campus/5; safety=10-crime_index; "
                    "groceries=10-minutes_to_groceries/3; "
                    "room=min(10,2.5*beds+2.5*baths); "
                    "orientation=South:10,East:8,West:6,North:4"
                ),
                "wtp": "1200 + 220 * weighted_attribute_score",
            }
        else:
            out["private_values"] = list(self.world.values[tenant_id])
        return out

    def landlord_observation(self, listing_id: int) -> Dict[str, Any]:
        """Information visible to one landlord, including only its own inbox."""
        if not self._valid_listing(listing_id):
            raise ValueError(f"unknown listing {listing_id!r}")
        listing = next(row for row in self.board() if row["listing_id"] == listing_id)
        return {
            "role": "landlord",
            "listing_id": listing_id,
            "round_index": self.round_index,
            "phase": self.phase,
            "listing": listing,
            "private_cost": self.world.costs[listing_id],
            "inbox": tuple(self._offers.get(listing_id, ())),
        }

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def _valid_tenant(self, tenant_id: Any) -> bool:
        return self._valid_id(tenant_id) and 0 <= tenant_id < self.world.num_tenants

    def _valid_listing(self, listing_id: Any) -> bool:
        return self._valid_id(listing_id) and 0 <= listing_id < self.world.num_listings

    @staticmethod
    def _valid_rent(rent: Any) -> bool:
        return (isinstance(rent, (int, float)) and not isinstance(rent, bool)
                and math.isfinite(float(rent)) and float(rent) >= 0.0)

    def _require_phase(self, expected: str) -> None:
        if self.phase != expected:
            raise PhaseOrderError(f"expected phase {expected!r}, current phase is {self.phase!r}")

    @staticmethod
    def _verdict(actor_id: int, phase: str, outcome: str,
                 reason: Optional[str] = None,
                 reference_id: Optional[str] = None) -> ActionVerdict:
        return ActionVerdict(actor_id, phase, outcome, reason, reference_id)

    # -- phases ------------------------------------------------------------
    def submit_offers(self, offers: Dict[int, Any]) -> PhaseResult:
        """Apply one frozen contact batch; invalid seat actions become passes."""
        self._require_phase("contact")
        inbox: Dict[int, List[Offer]] = {}
        verdicts: Dict[int, ActionVerdict] = {}
        actor_ids = set(self.unmatched_tenants()) | set(offers)
        for t in sorted(actor_ids, key=lambda value: (type(value).__name__, repr(value))):
            if not self._valid_tenant(t):
                verdicts[t] = self._verdict(t, "contact", "pass", "unknown_tenant")
                continue
            if t in self._matched:
                verdicts[t] = self._verdict(t, "contact", "pass", "unavailable_tenant")
                continue
            action = offers.get(t)
            if action is None:
                verdicts[t] = self._verdict(t, "contact", "pass", "missing_action")
                continue
            if not isinstance(action, (tuple, list)) or len(action) != 2:
                verdicts[t] = self._verdict(t, "contact", "pass", "invalid_contact")
                self.wasted_contacts += 1
                continue
            listing_id, rent = action
            if not self._valid_listing(listing_id):
                verdicts[t] = self._verdict(t, "contact", "pass", "unknown_listing")
                self.wasted_contacts += 1
                continue
            if listing_id in self._taken:
                verdicts[t] = self._verdict(t, "contact", "pass", "unavailable_listing")
                self.wasted_contacts += 1
                continue
            if not self._valid_rent(rent):
                verdicts[t] = self._verdict(t, "contact", "pass", "invalid_rent")
                self.wasted_contacts += 1
                continue
            offer = Offer(
                offer_id=f"offer:r{self.round_index}:t{t}:l{listing_id}",
                tenant_id=t,
                listing_id=listing_id,
                rent=float(rent),
                round_index=self.round_index,
            )
            inbox.setdefault(listing_id, []).append(offer)
            verdicts[t] = self._verdict(t, "contact", "applied", reference_id=offer.offer_id)
        for listing_id in inbox:
            inbox[listing_id].sort(key=lambda offer: (-offer.rent, offer.tenant_id))
        frozen_inbox = {listing_id: tuple(listing_offers)
                        for listing_id, listing_offers in inbox.items()}
        self._offers = frozen_inbox
        self.phase = "respond"
        return PhaseResult(phase="contact", verdicts=verdicts, inbox=dict(frozen_inbox))

    def submit_responses(
        self, responses: Dict[int, Any]
    ) -> PhaseResult:
        """Apply one landlord response batch and create at most one hold per listing."""
        self._require_phase("respond")
        holds: Dict[int, Hold] = {}
        verdicts: Dict[int, ActionVerdict] = {}
        actor_ids = set(self._offers) | set(responses)
        for listing_id in sorted(actor_ids, key=lambda value: (type(value).__name__, repr(value))):
            if not self._valid_listing(listing_id):
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "unknown_listing"
                )
                continue
            offered = {offer.tenant_id: offer for offer in self._offers.get(listing_id, [])}
            action = responses.get(listing_id)
            if action is None:
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "missing_action"
                )
                for tenant_id in offered:
                    self.rejected[tenant_id].add(listing_id)
                    self.wasted_contacts += 1
                continue
            if not isinstance(action, dict):
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "invalid_response"
                )
                continue
            if any(tenant_id not in offered for tenant_id in action):
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "unknown_offer"
                )
                continue

            parsed: Dict[int, Tuple[str, Optional[float]]] = {}
            invalid = False
            for tenant_id, decision_action in action.items():
                if (not isinstance(decision_action, (tuple, list))
                        or len(decision_action) != 2):
                    invalid = True
                    break
                decision, counter = decision_action
                if decision not in {"accept", "counter", "reject"}:
                    invalid = True
                    break
                if decision == "counter" and not self._valid_rent(counter):
                    invalid = True
                    break
                if decision != "counter" and counter is not None:
                    invalid = True
                    break
                parsed[tenant_id] = (decision, counter)
            if invalid:
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "invalid_response"
                )
                continue
            binding = [tenant_id for tenant_id, (decision, _) in parsed.items()
                       if decision in {"accept", "counter"}]
            if len(binding) > 1:
                verdicts[listing_id] = self._verdict(
                    listing_id, "respond", "pass", "hold_capacity_exceeded"
                )
                continue

            hold: Optional[Hold] = None
            if binding:
                tenant_id = binding[0]
                decision, counter = parsed[tenant_id]
                rent = offered[tenant_id].rent if decision == "accept" else float(counter)
                hold = Hold(
                    hold_id=f"hold:r{self.round_index}:t{tenant_id}:l{listing_id}",
                    tenant_id=tenant_id,
                    listing_id=listing_id,
                    rent=rent,
                    round_index=self.round_index,
                )
                holds[tenant_id] = hold
            for tenant_id in offered:
                if hold is None or tenant_id != hold.tenant_id:
                    self.rejected[tenant_id].add(listing_id)
                    self.wasted_contacts += 1
            verdicts[listing_id] = self._verdict(
                listing_id, "respond", "applied",
                reference_id=hold.hold_id if hold is not None else None,
            )
        self._holds = holds
        self.phase = "commit"
        return PhaseResult(phase="respond", verdicts=verdicts, holds=dict(holds))

    def submit_commits(self, commits: Dict[int, Any]) -> PhaseResult:
        """Sign or walk an immutable hold by id, then expire all remaining holds."""
        self._require_phase("commit")
        verdicts: Dict[int, ActionVerdict] = {}
        actor_ids = set(self._holds) | set(commits)
        for tenant_id in sorted(actor_ids, key=lambda value: (type(value).__name__, repr(value))):
            if not self._valid_tenant(tenant_id):
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "unknown_tenant"
                )
                continue
            hold = self._holds.get(tenant_id)
            action = commits.get(tenant_id)
            if action is None:
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "missing_action"
                )
                if hold is not None:
                    self.rejected[tenant_id].add(hold.listing_id)
                continue
            if not isinstance(action, (tuple, list)) or len(action) != 2:
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "invalid_commit"
                )
                if hold is not None:
                    self.rejected[tenant_id].add(hold.listing_id)
                continue
            decision, hold_id = action
            if decision not in {"sign", "walk"} or not isinstance(hold_id, str):
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "invalid_commit"
                )
                if hold is not None:
                    self.rejected[tenant_id].add(hold.listing_id)
                continue
            if hold is None or hold.hold_id != hold_id:
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "unknown_hold"
                )
                if hold is not None:
                    self.rejected[tenant_id].add(hold.listing_id)
                continue
            if (hold.round_index != self.round_index or hold.listing_id in self._taken
                    or tenant_id in self._matched):
                verdicts[tenant_id] = self._verdict(
                    tenant_id, "commit", "pass", "unavailable_hold"
                )
                continue
            if decision == "sign":
                self._taken.add(hold.listing_id)
                self._matched.add(tenant_id)
                self.pairs.append((tenant_id, hold.listing_id))
                self.signed_rent[tenant_id] = hold.rent
            else:
                self.rejected[tenant_id].add(hold.listing_id)
            verdicts[tenant_id] = self._verdict(
                tenant_id, "commit", "applied", reference_id=hold.hold_id
            )
        self.pairs.sort()
        self._offers = {}
        self._holds = {}
        self.round_index += 1
        self.phase = "finished" if self.finished else "contact"
        return PhaseResult(phase="commit", verdicts=verdicts)

    def result(self) -> Assignment:
        total = round(sum(self.world.values[t][l] - self.world.costs[l] for t, l in self.pairs), 2)
        return Assignment(pairs=list(self.pairs), total=total,
                          unhoused=self.world.num_tenants - len(self.pairs))

    def economics(self) -> TerminalEconomics:
        """Complete terminal allocation and transfer accounting for both sides."""
        tenant_payoffs = {t: 0.0 for t in range(self.world.num_tenants)}
        landlord_payoffs = {l: 0.0 for l in range(self.world.num_listings)}
        ir_violations: List[str] = []
        for tenant_id, listing_id in self.pairs:
            rent = self.signed_rent[tenant_id]
            tenant_payoffs[tenant_id] = round(self.world.values[tenant_id][listing_id] - rent, 2)
            landlord_payoffs[listing_id] = round(rent - self.world.costs[listing_id], 2)
            if tenant_payoffs[tenant_id] < 0:
                ir_violations.append(f"tenant:{tenant_id}")
            if landlord_payoffs[listing_id] < 0:
                ir_violations.append(f"landlord:{listing_id}")
        social_welfare = round(
            sum(tenant_payoffs.values()) + sum(landlord_payoffs.values()), 2
        )
        return TerminalEconomics(
            assignment=self.result(),
            signed_rents=dict(self.signed_rent),
            tenant_payoffs=tenant_payoffs,
            landlord_payoffs=landlord_payoffs,
            social_welfare=social_welfare,
            ir_violations=tuple(ir_violations),
        )


def scripted_landlord_responses(
    market: HousingMarket, inbox: Dict[int, Sequence[Offer]]
) -> Dict[int, Dict[int, Tuple[str, Optional[float]]]]:
    """Accept the highest offer at or above cost; counter a below-cost offer at the
    midpoint between it and the ask; never reject outright. Deterministic."""
    out: Dict[int, Dict[int, Tuple[str, Optional[float]]]] = {}
    for l, offers in inbox.items():
        per: Dict[int, Tuple[str, Optional[float]]] = {}
        cost = market.world.costs[l]
        viable = [offer for offer in offers if offer.rent >= cost]
        if viable:
            best_t = viable[0].tenant_id
            for offer in offers:
                per[offer.tenant_id] = (
                    ("accept", None) if offer.tenant_id == best_t else ("reject", None)
                )
        else:
            best = offers[0]
            per[best.tenant_id] = (
                "counter", round((best.rent + market.world.ask[l]) / 2.0, 2)
            )
            for offer in offers[1:]:
                per[offer.tenant_id] = ("reject", None)
        out[l] = per
    return out


def run_scripted_market(world: BidWorld, rounds: int = 4, strategy: str = "adaptive",
                        increment: float = 50.0) -> Assignment:
    """Scripted baseline over the full multi-round market."""
    m = HousingMarket(world, rounds=rounds)
    bump: Dict[int, float] = {t: 0.0 for t in range(world.num_tenants)}
    while not m.finished:
        offers: Dict[int, Tuple[int, float]] = {}
        for t in m.unmatched_tenants():
            cand = [l for l in m.open_listings()
                    if world.values[t][l] - world.ask[l] > 0
                    and (strategy != "adaptive" or l not in m.rejected[t])]
            if not cand:
                continue
            l = max(cand, key=lambda x: world.values[t][x] - world.ask[x])
            rent = world.ask[l] + (bump[t] if strategy == "adaptive" else 1.0)
            if rent > world.values[t][l]:
                continue
            offers[t] = (l, rent)
        contact = m.submit_offers(offers)
        response = m.submit_responses(scripted_landlord_responses(m, contact.inbox))
        commits: Dict[int, Tuple] = {}
        for t, hold in response.holds.items():
            commits[t] = (("sign", hold.hold_id)
                          if hold.rent <= world.values[t][hold.listing_id]
                          else ("walk", hold.hold_id))
        for t in m.unmatched_tenants():
            if t not in response.holds and strategy == "adaptive":
                bump[t] += increment
        m.submit_commits(commits)
    return m.result()


# ---------------------------------------------------------------------------
# Attribute-derived valuations
#
# The agent is given its own weight vector and the listing attributes and must
# compute what each listing is worth to it. Ground truth is exact, so adherence to
# its own preference function is measurable.
#
# Rent is deliberately NOT an attribute in the weight vector. Value here means
# willingness to pay, so rent is the price rather than a feature; including it
# would double-count. Landlord cost is a separate private type.
# ---------------------------------------------------------------------------

ATTRIBUTES = ("campus", "safety", "groceries", "room", "orientation")
_ORIENTATION_SCORE = {"South": 10.0, "East": 8.0, "West": 6.0, "North": 4.0}
_WTP_FLOOR = 1200.0     # willingness to pay at utility 0
_WTP_SPAN = 220.0       # dollars per utility point


def attribute_scores(listing: Listing) -> Dict[str, float]:
    """Each attribute on a 0-10 scale. Documented so an agent could reproduce them."""
    return {
        "campus": 10.0 - listing.minutes_to_campus / 5.0,
        "safety": 10.0 - listing.crime_index,
        "groceries": 10.0 - listing.minutes_to_groceries / 3.0,
        "room": min(10.0, 2.5 * listing.beds + 2.5 * listing.baths),
        "orientation": _ORIENTATION_SCORE.get(listing.orientation, 4.0),
    }


@dataclass(frozen=True)
class AttrWorld:
    listings: List[Listing]
    weights: List[List[float]]   # weights[tenant][attribute], sums to 1
    values: List[List[float]]    # derived, never shown to the agent
    costs: List[float]
    ask: List[float]

    @property
    def num_tenants(self) -> int:
        return len(self.weights)

    @property
    def num_listings(self) -> int:
        return len(self.listings)

    @property
    def surplus(self) -> List[List[float]]:
        return [[v - self.costs[l] for l, v in enumerate(row)] for row in self.values]


def valuation(world: "AttrWorld", weights: Sequence[float], listing_index: int) -> float:
    s = attribute_scores(world.listings[listing_index])
    u = sum(w * s[a] for w, a in zip(weights, ATTRIBUTES))
    return round(_WTP_FLOOR + _WTP_SPAN * u, 2)


def make_attr_world(num_tenants: int, num_listings: int, seed: int) -> AttrWorld:
    rng = random.Random(seed * 104729 + 7)
    listings = [
        Listing(
            listing_id=l,
            rent_asked=int(rng.uniform(1500, 3200)),
            beds=rng.randint(1, 3),
            baths=rng.randint(1, 2),
            minutes_to_campus=rng.randint(5, 45),
            crime_index=round(rng.uniform(1.0, 10.0), 1),
            minutes_to_groceries=rng.randint(3, 25),
            orientation=rng.choice(("South", "East", "West", "North")),
        )
        for l in range(num_listings)
    ]
    weights: List[List[float]] = []
    for _ in range(num_tenants):
        raw = [rng.random() + 0.05 for _ in ATTRIBUTES]
        tot = sum(raw)
        w = [round(x / tot, 6) for x in raw]
        w[-1] = round(1.0 - sum(w[:-1]), 6)   # absorb rounding so the vector sums to 1
        weights.append(w)
    ask = [float(l.rent_asked) for l in listings]
    costs = [round(max(0.0, price - rng.uniform(75.0, 250.0)), 2) for price in ask]
    world = AttrWorld(listings=listings, weights=weights, values=[], costs=costs, ask=ask)
    values = [[valuation(world, weights[t], l) for l in range(num_listings)]
              for t in range(num_tenants)]
    return AttrWorld(listings=listings, weights=weights, values=values,
                     costs=costs, ask=ask)


def adherence(world: "AttrWorld", tenant: int, reported: Dict[int, float]) -> Dict[str, float]:
    """Did the agent apply its OWN weights? Scored on the valuation, not the choice.

    rank_agreement is the share of listing pairs ordered the same way as ground
    truth, so getting the ordering right with the level wrong is a separate error
    from getting the ordering wrong.
    """
    ls = [l for l in range(world.num_listings) if l in reported]
    truth = {l: world.values[tenant][l] for l in ls}
    if len(ls) < 2:
        return {"rank_agreement": float("nan"), "mean_abs_error": float("nan"), "n": len(ls)}
    same = tot = 0
    for i in range(len(ls)):
        for j in range(i + 1, len(ls)):
            a, b = ls[i], ls[j]
            if truth[a] == truth[b]:
                continue
            tot += 1
            if (reported[a] - reported[b]) * (truth[a] - truth[b]) > 0:
                same += 1
    mae = sum(abs(reported[l] - truth[l]) for l in ls) / len(ls)
    return {"rank_agreement": (same / tot) if tot else float("nan"),
            "mean_abs_error": round(mae, 2), "n": len(ls)}
