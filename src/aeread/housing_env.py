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

Two market mechanisms are implemented. ``resolve`` is a serial-dictatorship variant
retained for reference only: it is strategyproof, so truthful ranking is a dominant
strategy and realized-vs-optimal measures the mechanism's own inefficiency rather
than agent behaviour. ``resolve_bids`` is the sealed-bid market used for scoring,
where a tenant must choose which listing to contest and how much to offer, and
losing a contest pays nothing.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


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
