"""Housing assignment market: world generator, assignment-game oracle, baselines.

Tenants compete for a smaller number of listings. Each tenant has a private
willingness to pay per listing and each landlord a private reservation cost, so a
match is worth ``v[t][l] - c[l]`` and the rent agreed splits that surplus without
creating it. What varies, and what is scored, is who ends up matched with whom.

The oracle is the transferable-utility assignment game: max-weight bipartite
matching on the surplus matrix gives the efficient matching, and the LP duals give
the core rent interval for every matched pair. Deferred acceptance is deliberately
NOT used. DA assumes non-transferable utility, and rent here is negotiable; it is
also strategyproof on the proposing side, which would leave nothing to measure.

Three mechanisms are implemented. ``resolve`` is a serial-dictatorship variant kept
for reference only: it is strategyproof, so truthful ranking is dominant and
realized-vs-optimal measures the mechanism's own inefficiency rather than agent
behaviour. ``resolve_bids`` is a one-shot sealed-bid market. ``HousingMarket`` is the
multi-round contact/respond/commit market, a step-wise state machine so a scripted
policy and an agent driver go through the identical interface.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
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
    costs = [float(l.rent_asked) for l in base.listings]
    ask = list(costs)
    values = [
        [round(costs[l] + base.surplus[t][l] * 10.0 + rng.uniform(-20, 20), 2)
         for l in range(num_listings)]
        for t in range(num_tenants)
    ]
    return BidWorld(listings=base.listings, values=values, costs=costs, ask=ask)


def resolve_bids(world: BidWorld, bids: Dict[int, Tuple[int, float]]) -> Assignment:
    """Each listing goes to its highest bidder at or above ask; ties by tenant id."""
    best: Dict[int, Tuple[float, int]] = {}
    for t in sorted(bids):
        entry = bids.get(t)
        if not entry:
            continue
        l, amount = entry
        if not (0 <= l < world.num_listings) or amount < world.ask[l]:
            continue
        cur = best.get(l)
        if cur is None or amount > cur[0]:
            best[l] = (float(amount), t)
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


class HousingMarket:
    def __init__(self, world: BidWorld, rounds: int = 4):
        self.world = world
        self.rounds = rounds
        self.round_index = 0
        self.pairs: List[Tuple[int, int]] = []
        self.signed_rent: Dict[int, float] = {}
        self._taken: set = set()
        self._matched: set = set()
        self._offers: Dict[int, List[Tuple[int, float]]] = {}
        self._holds: Dict[int, Tuple[int, float]] = {}   # tenant -> (listing, rent it may sign at)
        self.rejected: Dict[int, set] = {t: set() for t in range(world.num_tenants)}
        self.wasted_contacts = 0

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
                "status": "LEASED" if l.listing_id in self._taken else "OPEN",
            })
        return out

    # -- phases ------------------------------------------------------------
    def submit_offers(self, offers: Dict[int, Tuple[int, float]]) -> Dict[int, List[Tuple[int, float]]]:
        """contact: one offer per unmatched tenant. Returns each landlord's inbox."""
        inbox: Dict[int, List[Tuple[int, float]]] = {}
        for t in sorted(offers):
            if t in self._matched:
                continue
            entry = offers[t]
            if not entry:
                continue
            l, rent = entry
            if not (0 <= l < self.world.num_listings) or l in self._taken:
                self.wasted_contacts += 1
                continue
            inbox.setdefault(l, []).append((t, float(rent)))
        for l in inbox:
            inbox[l].sort(key=lambda x: (-x[1], x[0]))
        self._offers = inbox
        return inbox

    def submit_responses(
        self, responses: Dict[int, Dict[int, Tuple[str, Optional[float]]]]
    ) -> Dict[int, Tuple[int, float]]:
        """respond: at most one acceptance per landlord. Returns each tenant's hold."""
        holds: Dict[int, Tuple[int, float]] = {}
        for l, per_tenant in responses.items():
            accepted = [t for t, (d, _) in per_tenant.items() if d == "accept"]
            if len(accepted) > 1:
                raise ValueError(f"landlord {l} accepted {len(accepted)} offers in one round")
            offered = {t: rent for t, rent in self._offers.get(l, [])}
            for t, (decision, counter) in per_tenant.items():
                if decision == "accept":
                    holds[t] = (l, offered.get(t, self.world.ask[l]))
                elif decision == "counter":
                    holds[t] = (l, float(counter if counter is not None else self.world.ask[l]))
                else:
                    self.rejected[t].add(l)
                    self.wasted_contacts += 1
        self._holds = holds
        return holds

    def submit_commits(self, commits: Dict[int, Tuple]) -> None:
        """commit: sign (binding) or walk. Advances the round."""
        for t in sorted(commits):
            action = commits[t]
            if not action or action[0] != "sign":
                continue
            _, l, rent = action
            hold = self._holds.get(t)
            if hold is None or hold[0] != l or l in self._taken or t in self._matched:
                continue
            self._taken.add(l)
            self._matched.add(t)
            self.pairs.append((t, l))
            self.signed_rent[t] = float(rent)
        self.pairs.sort()
        self._offers = {}
        self._holds = {}
        self.round_index += 1

    def result(self) -> Assignment:
        total = round(sum(self.world.values[t][l] - self.world.costs[l] for t, l in self.pairs), 2)
        return Assignment(pairs=list(self.pairs), total=total,
                          unhoused=self.world.num_tenants - len(self.pairs))


def scripted_landlord_responses(
    market: HousingMarket, inbox: Dict[int, List[Tuple[int, float]]]
) -> Dict[int, Dict[int, Tuple[str, Optional[float]]]]:
    """Accept the highest offer at or above cost; counter a below-cost offer at the
    midpoint between it and the ask; never reject outright. Deterministic."""
    out: Dict[int, Dict[int, Tuple[str, Optional[float]]]] = {}
    for l, offers in inbox.items():
        per: Dict[int, Tuple[str, Optional[float]]] = {}
        cost = market.world.costs[l]
        viable = [(t, r) for t, r in offers if r >= cost]
        if viable:
            best_t = viable[0][0]
            for t, r in offers:
                per[t] = ("accept", None) if t == best_t else ("reject", None)
        else:
            for t, r in offers:
                per[t] = ("counter", round((r + market.world.ask[l]) / 2.0, 2))
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
        inbox = m.submit_offers(offers)
        holds = m.submit_responses(scripted_landlord_responses(m, inbox))
        commits: Dict[int, Tuple] = {}
        for t, (l, rent) in holds.items():
            commits[t] = ("sign", l, rent) if rent <= world.values[t][l] else ("walk",)
        for t in m.unmatched_tenants():
            if t not in holds and strategy == "adaptive":
                bump[t] += increment
        m.submit_commits(commits)
    return m.result()
