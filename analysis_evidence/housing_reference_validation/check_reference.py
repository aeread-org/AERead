"""Independent bounded checks of Housing's approximate planning reference.

Run with Python 3.11+:
  python check_reference.py --source-root /path/to/housing-best-informed --output results.json

No model calls, campaign edits, or changes to the production solver. The oracle
uses exact rational arithmetic and explicit hidden-world partitions, without
calling the production belief, price, or Bellman helpers. Passing these fixtures
certifies neither every reachable campaign state nor the full offer distribution.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
import sys

TOL = 1e-9  # absolute dollars, only for comparison to production binary64


@dataclass(frozen=True)
class World:
    bad: tuple[bool, ...]
    rents: tuple[F, ...]
    weight: F = F(1)


class EnumeratedOracle:
    """An explicit finite hidden-world decision tree, independent of Tenant.

    A belief is a tuple of retained world indices; their original weights
    normalize within that subset. Inspection partitions by quality; a contact
    partitions by exact rent. Thus future actions condition on the observation,
    rather than maximizing after replacing observations by their mean.
    """
    def __init__(self, worlds, values, loss, fee, rate):
        self.worlds = tuple(worlds)
        self.values = tuple(F(str(v)) for v in values)
        self.loss, self.fee, self.rate = map(lambda v: F(str(v)), (loss, fee, rate))

    @lru_cache(None)
    def mass(self, belief):
        return sum((self.worlds[i].weight for i in belief), F(0))

    def partitions(self, belief, key):
        groups = {}
        for i in belief:
            groups.setdefault(key(self.worlds[i]), []).append(i)
        return tuple((observation, tuple(ids)) for observation, ids in groups.items())

    def average(self, belief, value):
        return sum((self.worlds[i].weight * value(self.worlds[i]) for i in belief), F(0)) / self.mass(belief)

    @lru_cache(None)
    def start(self, remaining, opened, belief):
        if remaining <= 0 or not opened:
            return F(0)
        return max(self.inspections(remaining, opened, belief).values())

    def inspections(self, remaining, opened, belief):
        choices = {None: self.contact(remaining, opened, belief)}
        for listing in opened:
            groups = self.partitions(belief, lambda w: w.bad[listing])
            if len(groups) > 1:
                choices[listing] = -self.fee + sum((self.mass(ids) / self.mass(belief)
                    * self.contact(remaining, opened, ids) for _, ids in groups), F(0))
        return choices

    @lru_cache(None)
    def contact(self, remaining, opened, belief):
        return max(self.contacts(remaining, opened, belief).values())

    def contacts(self, remaining, opened, belief):
        choices = {None: self.depart(remaining, opened, belief, None)}
        for listing in opened:
            groups = self.partitions(belief, lambda w: w.rents[listing])
            choices[listing] = sum((self.mass(ids) / self.mass(belief)
                * self.commit(remaining, opened, ids, listing) for _, ids in groups), F(0))
        return choices

    def commit(self, remaining, opened, belief, listing):
        sign = self.average(belief, lambda w: self.values[listing]
                            - self.loss * w.bad[listing] - w.rents[listing])
        return max(sign, self.depart(remaining, opened, belief, listing))

    @lru_cache(None)
    def depart(self, remaining, opened, belief, protected):
        if remaining <= 1:
            return F(0)
        risk = tuple(l for l in opened if l != protected)
        result = F(0)
        for flags in product((False, True), repeat=len(risk)):
            gone = {l for l, take in zip(risk, flags) if take}
            probability = self.rate ** len(gone) * (1-self.rate) ** (len(risk)-len(gone))
            if probability:
                result += probability * self.start(remaining-1, tuple(l for l in opened if l not in gone), belief)
        return result


def representative_worlds(asks, loss, lemon_count):
    """Independent statement of the two-category surrogate, in exact dollars."""
    worlds = []
    for leaky in (False, True):
        for bad_set in combinations(range(len(asks)), lemon_count):
            bad = tuple(i in bad_set for i in range(len(asks)))
            rents = tuple(min(F(a), max(F(0), F(a)-50-(loss if leaky and bad[i] else 0))+25)
                          for i, a in enumerate(asks))
            worlds.append(World(bad, rents))
    return worlds


def verify_production(best):
    rows = []
    profiles = [
        ((2000, 2100), (2200, 2280), 25),
        ((2000, 2100), (1975, 2090), 0),
        ((2000, 2100), (2500, 2400), 500),
        ((2000, 2100, 2200, 2300), (2300, 2150, 2500, 2280), 25),
    ]
    original_rate = best.RATE
    try:
        for asks, values, fee in profiles:
            n = len(asks)
            worlds = representative_worlds(asks, 1000, n//2)
            observations = [(tuple('?' for _ in asks), tuple('-' for _ in asks), {})]
            # Representative posterior states: inspected sound/lemon and heard low/ordinary.
            for wi in (0, len(worlds)-1):
                w = worlds[wi]
                for inspected, contacted in ((0, None), (None, 0), (0, 1)):
                    q = tuple(('L' if w.bad[i] else 'S') if i == inspected else '?' for i in range(n))
                    prices = {} if contacted is None else {contacted: float(w.rents[contacted])}
                    z = tuple(('L' if w.rents[i] < asks[i]-55 else 'N') if i == contacted else '-' for i in range(n))
                    observations.append((q, z, prices))
            for rate in (F(1,2), F(3,10)):
                best.RATE = float(rate)  # explicit controlled input, restored below
                oracle = EnumeratedOracle(worlds, values, 1000, fee, rate)
                for oi, (q, z, prices) in enumerate(observations):
                    belief = tuple(i for i,w in enumerate(worlds)
                        if all(label == '?' or (label == 'L') == w.bad[j] for j,label in enumerate(q))
                        and all(w.rents[j] == F(str(rent)) for j,rent in prices.items()))
                    assert belief
                    for remaining in (1,2,3):
                        opened = tuple(range(n)) if oi % 2 == 0 else tuple(range(n-1))
                        tenant = best.Tenant('pricing')
                        tenant.n, tenant.ask, tenant.value = n, list(asks), list(values)
                        tenant.loss, tenant.fee, tenant.lemon_count = 1000, fee, n//2
                        tenant.answers = dict(prices)
                        state = (3-remaining, tuple(i in opened for i in range(n)), q, z)
                        comparisons = [
                            ('inspect', dict(tenant._inspections(*state)), oracle.inspections(remaining, opened, belief)),
                            ('contact', dict(tenant._offers(*state)), oracle.contacts(remaining, opened, belief)),
                        ]
                        errors = []
                        for phase, got, expected in comparisons:
                            assert got.keys() == expected.keys(), (phase, got, expected)
                            for action in got:
                                error = abs(got[action]-float(expected[action]))
                                assert error <= TOL, (phase, action, got[action], expected[action])
                                errors.append(error)
                            chosen = max(got, key=lambda a: got[a])
                            assert float(max(expected.values())-expected[chosen]) <= TOL
                        rows.append({'listings':n, 'values':values, 'fee':fee, 'rate':str(rate),
                            'observation':oi, 'remaining_rounds':remaining, 'open':opened,
                            'action_values_compared':len(errors), 'max_abs_error_usd':max(errors),
                            'exact_start_value':str(oracle.start(remaining,opened,belief))})
        # Terminal condition, independent of the phase-level checks above.
        tenant = best.Tenant('pricing')
        assert tenant._start(3, (True,), ('?',), ('-',)) == 0
        assert tenant._start(0, (False,), ('?',), ('-',)) == 0
    finally:
        best.RATE = original_rate
    return rows


def verify_distribution(best, bargaining):
    # Exact cent bins induced by rounding a continuous Uniform[20,80] discount:
    # endpoint bins have half the width; all interior bins have width one cent.
    worlds = []
    for cents in range(2000, 8001):
        weight = F(1,12000) if cents in (2000,8000) else F(1,6000)
        cost = F(2000)-F(cents,100)
        rent = min(F(2000),cost+25)
        got = bargaining.landlord_action({'inbox':[{'rent':0.,'tenant_id':0,'offer_id':'probe'}],
            'private_cost':float(cost), 'reservation_cost':float(cost),
            'listing':{'rent_asked':2000.}})['counter_rent']
        assert F(str(got)) == rent
        worlds.append(World((False,), (rent,), weight))
    assert sum((w.weight for w in worlds), F(0)) == 1
    oracle = EnumeratedOracle(worlds, (1975,), 1000, 25, F(1,2))
    value = oracle.contacts(1,(0,),tuple(range(len(worlds))))[0]
    direct = sum((w.weight*max(F(1975)-w.rents[0],F(0)) for w in worlds),F(0))
    assert value == direct == F(15,2)
    tenant = best.Tenant('pricing')
    tenant.n,tenant.ask,tenant.value = 1,[2000],[1975]
    tenant.loss,tenant.fee,tenant.lemon_count = 1000,25,0
    approximate = dict(tenant._offers(2,(True,),('S',),('-',)))[0]
    assert approximate == 0
    # Known alternative worth $5: the exact policy contacts the uncertain
    # listing ($7.50), whereas mean-price planning chooses the alternative.
    two = [World((False,False),(w.rents[0],F(1975)),w.weight) for w in worlds]
    choice_oracle = EnumeratedOracle(two,(1975,1980),1000,25,F(1,2))
    choices = choice_oracle.contacts(1,(0,1),tuple(range(len(two))))
    assert choices[0] == F(15,2) and choices[1] == 5
    tenant.n,tenant.ask,tenant.value = 2,[2000,2000],[1975,1980]
    tenant.answers = {1:1975.}; tenant._belief.clear(); tenant._memo.clear()
    approximations = dict(tenant._offers(2,(True,True),('S','S'),('-','N')))
    assert max(approximations,key=approximations.get) == 1
    assert max(choices,key=choices.get) == 0
    # A two-round, one-listing policy can keep its first quote by bidding.
    # For a known sound listing and fixed rent, repeating contact adds no value.
    small = [World((False,),(F(1945),)),World((False,),(F(2000),))]
    two_round = EnumeratedOracle(small,(1975,),1000,25,F(1,2))
    assert two_round.start(2,(0,),(0,1)) == F(15)
    return {'scope':'synthetic states, not admitted evaluation worlds',
        'rounded_cost_bins':len(worlds), 'landlord_targets_checked':len(worlds),
        'distribution_mass': '1', 'exact_contact_usd':str(value),
        'approximate_contact_usd':approximate,
        'two_listing_exact_action':0,'two_listing_approximate_action':1,
        'two_listing_action_gap_usd':str(choices[0]-choices[1]),
        'two_round_persistent_quote_value_usd':'15'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=args.source_root.resolve()
    sys.path.insert(0,str(root/'src'))
    from aeread_families.housing import price_best_informed as best, price_bargaining as bargaining
    assert Path(best.__file__).resolve().is_relative_to(root)
    rows=verify_production(best)
    distribution=verify_distribution(best,bargaining)
    paths=[Path(__file__).resolve(),Path(best.__file__),Path(bargaining.__file__),
           root/'src/aeread_families/housing/environment.py',
           root/'src/aeread_families/housing/price_outside_demand.py']
    report={'schema':'housing_reference_bounded_checks/1','status':'passed',
        'scope':'Exact-rational representative-price fixtures plus synthetic full-price regressions; not campaign-wide optimality certification',
        'precision':{'oracle':'fractions.Fraction; exact rational arithmetic',
                     'production':'Python float (binary64)', 'absolute_tolerance_usd':TOL,
                     'rounding':'No rounding inside oracle; exact fraction strings retained; actual landlord target cents checked'},
        'source_root':str(root),
        'sha256':{str(p):sha256(p.read_bytes()).hexdigest() for p in paths},
        'surrogate_state_count':len(rows),
        'action_value_count':sum(r['action_values_compared'] for r in rows),
        'max_abs_error_usd':max(r['max_abs_error_usd'] for r in rows),
        'distribution_checks':distribution, 'surrogate_checks':rows}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('surrogate_checks','sha256')},indent=2))


if __name__ == '__main__':
    main()
