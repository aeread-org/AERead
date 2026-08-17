# The housing assignment case

A two-sided market where tenants compete for a smaller number of listings. It asks
whether an agent can reason about **competition for a scarce resource**, not merely
optimize its own valuation.

Status: the environment, oracle, and baselines are implemented and tested offline.
The multi-round negotiation workflow described in §5 is designed but not yet built;
what ships today is the one-shot sealed-bid market.

## 1. The market

| seat | count | knows privately |
|---|---|---|
| tenant | 6 | own willingness to pay `v[t][l]` for every listing |
| landlord | 4 | own reservation cost `c[l]` for its listing |

A match is worth `v[t][l] - c[l]`. Rent splits that surplus and never creates it, so
efficiency depends only on **who is matched with whom**. Tenant valuations have a
common component, so everyone agrees roughly which listings are good, and an
idiosyncratic component, so the efficient assignment differs from the popular one.
With six tenants and four listings, at least two tenants end up unhoused by
construction.

```python
from aeread import housing_env as hz

world = hz.make_bid_world(num_tenants=6, num_listings=4, seed=0)
optimum = hz.assignment_oracle(world.surplus)       # max-weight matching benchmark

bids = hz.naive_top_bids(world)                     # {tenant: (listing, rent)}
result = hz.resolve_bids(world, bids)
efficiency = result.total / optimum.total           # what a submitted agent is scored on
```

## 2. Oracle

The transferable-utility **assignment game**. Max-weight bipartite matching on the
surplus matrix gives the efficient matching; the LP duals give the core rent interval
for each matched pair. One linear program yields both a matching benchmark and a
price benchmark.

Deferred acceptance is deliberately not used, for two independent reasons. It assumes
non-transferable utility, and rent here is negotiable. And it is strategyproof on the
proposing side, so truthful ranking would be a dominant strategy and there would be
nothing for an agent to get right or wrong.

## 3. Baselines

All computable with no API calls, so the scale exists before any agent is scored.

| baseline | efficiency vs optimum |
|---|---|
| random: random listing, minimum bid | 0.351 |
| naive: minimum bid on your own favourite | 0.637 |
| truthful: full valuation on your own favourite | 0.729 |
| max-weight optimum | 1.000 |

All measured over 300 seeds at 6 tenants and 4 listings. The naive baseline has
standard deviation 0.175 across seeds, which is the number to size a run from:
`n = 2*((1.96+0.84)*sd/delta)^2`, so 30 episodes powers detection of a 0.13
difference.

## 4. Why this mechanism and not a simpler one

An earlier version used serial dictatorship: tenants submit ranked lists and a public
priority order resolves collisions. **That mechanism cannot measure anything**, and
the reason generalizes to any benchmark.

Serial dictatorship is strategyproof, so ranking by own value is a dominant strategy.
An exhaustive search over every permutation of every subset of listings, for every
tenant across 40 worlds, found **0 profitable deviations out of 240**. Three models
scored exactly at that baseline, one of them emitting the identical ranking on 180 of
180 calls. That was optimal play, not failure to coordinate, and the gap between
realized and optimal surplus measured the mechanism's own inefficiency, which no
agent behaviour could have closed.

Sealed bidding restores the strategic content: **222 of 360 tenants (61.7%) have a
profitable unilateral deviation** from the naive strategy.

`resolve` (serial dictatorship) is kept in the module for reference, and is not the
scoring path.

**The general rule, worth applying to any case in this repo:** before measuring an
agent against a baseline, verify the baseline is beatable by searching unilateral
deviations and counting how many pay. A near-zero rate means the mechanism is a
formality, and no sample size rescues the experiment.

## 5. Designed, not yet built: the multi-round workflow

The shipped market is one-shot. The full case runs `contact -> respond -> commit` over
four rounds:

1. **contact.** Each unmatched tenant sends one offer to one landlord:
   `{"listing_id": 2, "rent": 2350, "term_months": 12}`. One offer per tenant per
   round is the scarcity that makes choice strategic.
2. **respond.** Each landlord sees only the offers addressed to it and answers each
   with accept, counter, or reject, accepting at most one per round. Accepting below
   its own cost is permitted and scored as an error rather than blocked, so a landlord
   that leases at a loss is measurable.
3. **commit.** A tenant holding an acceptance or counter signs or walks. Signing is
   binding and ends that tenant's episode.

Tenants see a board of listings each round including a `status` column marking those
already leased. That column is what makes the market adaptive: without it a later
round carries no more information than the first.

There is **no per-round penalty**. An unmatched tenant already scores zero, so a
bounded round budget supplies the pressure, and a penalty entering the objective would
move the optimum and therefore the oracle. Four rounds is measured as sufficient: the
scripted adaptive baseline saturates at three rounds and gains nothing at six or eight.

## 6. Metrics

| metric | definition |
|---|---|
| `matching_error` | `1 - realized_surplus / optimal_surplus` |
| `core_rent_error` | share of signed leases priced outside the core interval |
| `unmatched_gap` | realized unmatched count minus optimal unmatched count |

Report `matching_error` as the headline. `unmatched_gap` is a diagnostic only: the
optimum leaves 2.12 tenants unhoused and the naive baseline 2.19, so it separates
almost nothing. `core_rent_error` requires landlords to be live agent seats rather
than a highest-bid rule, and is not measurable in the one-shot market.

Any reported metric should carry the answer rate beside it. A seat that returns an
empty response cannot bid, and a tenant that cannot bid cannot win, so a change in
answer rate is indistinguishable from a treatment effect unless both are shown. A
seat that returns empty with `finish_reason=length` should be retried at a higher
token cap before its silence is recorded as a decision: starvation and refusal are
different events.

## 7. Reproducing the baselines

```bash
pytest tests/test_housing_assignment.py tests/test_housing_bids.py -q
```

```python
import statistics as st
from aeread import housing_env as hz

ratios = []
for seed in range(300):
    w = hz.make_bid_world(6, 4, seed=seed)
    opt = hz.assignment_oracle(w.surplus)
    if opt.total <= 0:
        continue
    ratios.append(hz.resolve_bids(w, hz.naive_top_bids(w)).total / opt.total)
print(round(st.mean(ratios), 3), round(st.stdev(ratios), 3))
```
