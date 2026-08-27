# The housing assignment case

A two-sided market where tenants compete for a smaller number of listings. It asks
whether an agent can reason about **competition for a scarce resource**, not merely
optimize its own valuation.

Status: the P0 environment contract, allocation oracle, scripted multi-round baselines,
and native shared-runner path through typed measurement, receipts, and deterministic
state-and-score replay are implemented and tested. The standalone CLI and batch runner
both finalize successful trajectories and reconciled failures through the same receipt
contract. The earlier fixed OpenRouter/DeepSeek smoke cell is historical R4 admission
evidence and predates the new receipt layer; it is not a current paper result.

The finalized receipt path is documented in
[`walkthroughs/shared_runner_housing_receipts.md`](walkthroughs/shared_runner_housing_receipts.md).

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

The implemented upper bound `U` is max-weight bipartite matching on the
transferable-utility surplus matrix. Non-positive matches are dropped. The always
feasible no-trade policy proves the optimum lower bound `L = 0`; it is not a lower
bound on every realized agent outcome. For worlds with `U > 0`, normalized
efficiency is therefore `(R - L) / (U - L) = R / U`; worlds with `U = 0` must be
reported separately rather than divided by zero.

The comparison baseline `B` is a declared executable policy, not another bound. For
the current multi-round direct-value world, `B` is the deterministic naive scripted
policy described below. Keeping `L`, `U`, and `B` separate prevents a weak baseline
from being misreported as a feasibility floor or an optimum.

Core-rent intervals are not implemented. They remain a possible price diagnostic,
but the present oracle is an allocation/welfare oracle only. The repository must not
claim a core-price result until an explicit price oracle and contract tests exist.

Deferred acceptance is deliberately not used, for two independent reasons. It assumes
non-transferable utility, and rent here is negotiable. And it is strategyproof on the
proposing side, so truthful ranking would be a dominant strategy and there would be
nothing for an agent to get right or wrong.

## 3. Reference policies

All references are computable without provider calls, so the scale exists before an
agent is scored. The receipt comparison baseline `B` is the four-round naive scripted
policy in Section 5. The adaptive scripted policy is retained as a diagnostic, and the
max-weight allocation supplies `U`; the current pinned-panel values are reported in
Section 5a.

The one-shot `naive_top_bids`, `truthful_top_bids`, and `resolve_bids` helpers remain
useful for unit tests and mechanism probes, but they are not the current multi-round
receipt comparator. Their historical averages must not be mixed with the P0
`contact -> respond -> commit` results.

## 4. Why this mechanism and not a simpler one

An earlier version used serial dictatorship: tenants submit ranked lists and a public
priority order resolves collisions. **That mechanism cannot measure strategic
coordination in this interface**, and the reason generalizes to any benchmark.

Serial dictatorship is strategyproof, so ranking by own value is a dominant strategy.
The gap between realized and optimal surplus therefore measures the mechanism's own
inefficiency, which agent behavior cannot close; matching the truthful baseline is
optimal play rather than evidence of a coordination failure.

Sealed bidding restores live choices over target and price. The earlier profitable-
deviation count predates the P0 world revision and is withdrawn until its search
artifact is committed and rerun.

`resolve` (serial dictatorship) is kept in the module for reference, and is not the
scoring path.

**The general rule, worth applying to any case in this repo:** before measuring an
agent against a baseline, verify the baseline is beatable by searching unilateral
deviations and counting how many pay. A near-zero rate means the mechanism is a
formality, and no sample size rescues the experiment.

## 5. The multi-round market

`HousingMarket` runs `contact -> respond -> commit` over four rounds as a step-wise
interface.

1. **contact.** Each unmatched tenant sends one offer to one listing:
   `{"listing_id": 2, "rent": 2350}`. One offer per tenant per round is the scarcity
   that makes choosing which listing to contest a real decision.
2. **respond.** Each landlord sees only real offers addressed to its listing and may
   accept or counter at most one. Either action creates one immutable, capacity-
   reserving `Hold(hold_id, tenant_id, listing_id, rent, round_index)`. A fabricated
   tenant/offer reference creates no hold. Accepting below private cost remains legal
   so a loss is measured rather than silently censored.
3. **commit.** A tenant may submit only `("sign", hold_id)` or
   `("walk", hold_id)`. Listing and rent are taken from the frozen hold and cannot be
   resubmitted. All unsigned and invalidly referenced holds expire at the end of the
   commit phase; only then does the round advance.

Each method applies one deterministic batch against the same pre-phase state and
returns a typed `PhaseResult`. Every submitted seat action receives an
`ActionVerdict` with outcome `applied` or `pass` plus a reason. Missing or malformed
actions are native passes after runner retry policy is exhausted: an invalid contact
creates no offer, an invalid response creates no hold, and an invalid commit expires
the hold. Calling phases out of order raises `PhaseOrderError`, because that is a
harness integration defect rather than an agent decision.

```python
market = hz.HousingMarket(world, rounds=4)
contact = market.submit_offers({0: (2, 2350.0)})
response = market.submit_responses({2: {0: ("accept", None)}})
hold = response.holds[0]
commit = market.submit_commits({0: ("sign", hold.hold_id)})
```

The public board includes ask, attributes (including orientation), and lease status,
but never reservation cost. A direct-value tenant sees only its own WTP vector; an
attribute-world tenant sees only its own weights and the published valuation formula,
not derived WTP. A landlord sees only its own listing, private cost, and inbox. Public
ask and private cost are independently represented and differ in generated worlds.

`HousingMarket` itself does not choose landlord actions. `run_scripted_market`
explicitly injects the deterministic policy for the controlled comparison block; a
runner may instead fill the same response batch from live landlord seats. Scripted and
live-counterparty results must be reported as separate experimental conditions.

Tenants see the board each round with a `status` column marking listings already
leased. That column is what makes the market adaptive: without it a later round
carries no more information than the first.

There is **no per-round penalty**. An unmatched tenant already scores zero, so a
bounded round budget supplies the pressure, and a penalty entering the objective
would move the optimum and therefore the oracle. Four rounds is the pinned P0
configuration. The prior saturation claim predates binding one-hold capacity and must
be rerun before a round-budget ceiling is claimed.

### Current baselines and model-result status

Regenerated over 300 seeds under the binding-hold P0 semantics:

| policy | mean efficiency | standard deviation | mean leases |
|---|---:|---:|---:|
| naive scripted (`B`) | 0.852 | 0.096 | 3.820 |
| adaptive scripted diagnostic | 0.849 | 0.100 | 3.640 |
| max-weight upper bound (`U`) | 1.000 | - | - |

The ordering is a useful correction: the old claim that adaptive beats naive depended
on permissive multi-hold behavior. The policies are retained as distinct diagnostics,
but naive is the current comparison baseline because it is marginally stronger on the
pinned panel.

The previous live-model tables are withdrawn from current evidence. They were produced
before the binding-hold, phase, privacy, and terminal-accounting corrections, and the
driver, prompts, raw responses, retry records, and trajectories were not committed.
They are neither reproducible from this repository nor comparable to the current
environment.

The admitted R4 smoke cell is documented separately in
[`walkthroughs/shared_runner_housing_r4.md`](walkthroughs/shared_runner_housing_r4.md).
Its single fixed world reached `R = B = U = 389.54`, with no IR violations, one wasted
contact, and `$0.0002722896` charged cost. That is integration evidence only: one
cluster cannot estimate uncertainty, robustness, coverage, ranking, or saturation.

For the next run, reasoning mode must be a declared experimental condition and stored
in the receipt. Actions and outcomes remain primary evidence; reasoning text is only a
secondary diagnostic surface. Failure coding should distinguish objective selection,
strategic modeling, constraint tracking, and execution rather than report only
"reasoning on/off."

## 5b. Attribute-derived valuations

By default the agent is handed its willingness to pay. `make_attr_world` instead
derives it: each listing has attributes, each tenant a private weight vector, and the
agent must compute its own value.

```
campus      = 10 - (minutes to campus) / 5
safety      = 10 - (crime index)
groceries   = 10 - (minutes to groceries) / 3
room        = min(10, 2.5*bedrooms + 2.5*bathrooms)
orientation = South 10, East 8, West 6, North 4

utility            = weighted sum using the tenant's own weights
willingness to pay = 1200 + 220 * utility
```

**The formulas are published to the agent.** Hiding them would make the task guessing
the designer's functional form rather than applying stated preferences, so a failure to
adhere would not mean what it appears to mean.

**Rent is not in the weight vector.** Value here means willingness to pay, so rent is
the price rather than a feature; including it double-counts.

`adherence(world, tenant, reported)` scores the agent's reported valuations against
ground truth on two separate axes: `rank_agreement`, the share of listing pairs ordered
as its own weights imply, and `mean_abs_error` on the levels. A constant offset scores
perfect ranking and poor error, because ordering and calibration are different failures.

**Adherence is scored on the valuation, never on the choice.** An agent that values a
listing correctly and then bids elsewhere to avoid competition is playing well, not
miscomputing, and conflating the two would penalise exactly the behaviour the case
exists to reward.

The earlier profitable-deviation count predates the private-cost and binding-hold P0
revision and is withdrawn pending a committed rerun. The current four-round results
are the pinned 300-seed panel in Section 5a. They establish executable within-case
comparisons, not universal scores or evidence that the suite is saturated.

## 6. Metrics

| metric | definition |
|---|---|
| `social_welfare` | realized tenant plus landlord payoff in native utility units; receipt primary |
| `within_case_score` | `realized_surplus / optimal_surplus` when `U > 0`; within-case diagnostic |
| `matching_error` | `1 - realized_surplus / optimal_surplus` |
| `unmatched_gap` | realized unmatched count minus optimal unmatched count |
| `tenant_payoff[t]` | signed tenant value minus signed rent; zero if unmatched |
| `landlord_payoff[l]` | signed rent minus private cost; zero if unmatched |
| `ir_violations` | signed seats with negative realized payoff |
| `core_rent_error` | future diagnostic; no implemented price oracle |

The receipt headline is native-unit `social_welfare`; a predeclared paired analysis may
use `within_case_score` to compare conditions on identical worlds, but it is not a
universal cross-family score. `unmatched_gap` is a diagnostic only: the count can hide
large welfare differences. `economics()` preserves signed prices,
per-seat payoffs, total welfare, and IR violations. Negative-payoff agreements are
legal outcomes and must be recorded rather than filtered. `core_rent_error` is not yet
measurable because this repository does not implement or test a price/core oracle;
making landlords live is necessary for distributional experiments but does not by
itself supply that oracle.

Any reported metric should carry the answer rate beside it. A seat that returns an
empty response cannot bid, and a tenant that cannot bid cannot win, so a change in
answer rate is indistinguishable from a treatment effect unless both are shown. A
seat that returns empty with `finish_reason=length` should be retried at a higher
token cap before its silence is recorded as a decision: starvation and refusal are
different events.

## 7. Reproducing the baselines

```bash
pytest tests/test_housing_assignment.py tests/test_housing_bids.py \
  tests/test_housing_market.py tests/test_housing_attributes.py -q
```

```python
import statistics as st
from aeread import housing_env as hz

naive, adaptive = [], []
for seed in range(300):
    w = hz.make_bid_world(6, 4, seed=seed)
    opt = hz.assignment_oracle(w.surplus)
    if opt.total <= 0:
        continue
    naive.append(hz.run_scripted_market(w, 4, "naive").total / opt.total)
    adaptive.append(hz.run_scripted_market(w, 4, "adaptive").total / opt.total)
for name, ratios in (("naive", naive), ("adaptive", adaptive)):
    print(name, round(st.mean(ratios), 3), round(st.stdev(ratios), 3))
```

This reproduces scripted baselines only. A reproducible live-agent result additionally
requires the shared runner to store the task/policy/database hashes, model and exact
prompt, reasoning setting, seed, tool/action records, state diffs, retries, scorer
version, raw responses, and replay result. Until those artifacts are committed or
addressably archived, a model table must remain preliminary and outside paper claims.
