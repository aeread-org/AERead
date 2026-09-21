# The housing assignment case

A two-sided market where tenants compete for a smaller number of listings. It asks
whether an agent can reason about **competition for a scarce resource**, not merely
optimize its own valuation.

Status: the P0 environment contract, allocation oracle, scripted multi-round
baselines, shared-runner adapter, typed receipts, and offline state-and-score
replay are implemented and tested. Live-model artifacts remain development
evidence: Housing has not completed the separate
[quality-control contract](qc.md) or a confirmatory campaign freeze, so
no live-model table is a current paper result.

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
from aeread_families.housing import environment as hz

world = hz.make_bid_world(num_tenants=6, num_listings=4, seed=0)
optimum = hz.assignment_oracle(world.surplus)       # max-weight matching benchmark

bids = hz.naive_top_bids(world)                     # {tenant: (listing, rent)}
result = hz.resolve_bids(world, bids)
efficiency = result.total / optimum.total           # what a submitted agent is scored on
```

## 2. Oracle

The implemented upper bound `U` is max-weight bipartite matching on the
transferable-utility surplus matrix. Non-positive matches are dropped. The always
feasible no-trade outcome is the floor `L = 0`. For worlds with `U > 0`, normalized
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

## 3. Baselines

All computable with no API calls, so the scale exists before any agent is scored.

| baseline | efficiency vs optimum |
|---|---|
| naive: minimum bid on your own favourite | 0.619 |
| truthful: full valuation on your own favourite | 0.700 |
| max-weight optimum | 1.000 |

These numbers were regenerated after the P0 privacy correction over 300 seeds at 6
tenants and 4 listings. The naive baseline standard deviation is 0.173. They describe
only the pinned generator and policy; they are not evidence of saturation of housing
reasoning in general.

## 4. Why this mechanism and not a simpler one

An earlier version used serial dictatorship: tenants submit ranked lists and a public
priority order resolves collisions. **That mechanism cannot measure strategic
coordination in this interface**, and the reason generalizes to any benchmark.

Serial dictatorship is strategyproof, so ranking by own value is a dominant strategy.
The gap between realized and optimal surplus therefore measures the mechanism's own
inefficiency, which agent behavior cannot close; matching the truthful baseline is
optimal play rather than evidence of a coordination failure.

Sealed bidding restores live choices over target and price, but the headline welfare
score measures only the resulting allocation. Because rent is a transfer, an extreme
overbid can leave a tenant with negative payoff without lowering joint surplus. Welfare
therefore supports claims about allocation efficiency and congestion management, not
bid shading, tenant payoff, or individually rational bidding. Those require the signed
rent, per-seat payoff, and `ir_violations` diagnostics below. The earlier profitable-
deviation count predates the P0 world revision and is withdrawn until its search artifact
is committed and rerun.

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
revision and is withdrawn pending a committed rerun. Current four-round results over
the 299 of 300 generated seeds with `U > 0` are: naive 0.847 (sd 0.122) and adaptive
0.835 (sd 0.127). These establish executable within-case comparisons, not universal
scores or evidence that the suite is saturated.

## 5c. Refusal under adverse selection: the lemons world

`make_lemons_world` (`lemons.py`) is the pinned bid world plus quality. A declared
`lemon_share` of the listings, rounded half up to an exact `lemon_count`, are lemons
that post the same ask as sound units. A lemon is worth `lemon_loss` less to every
tenant and costs its landlord `lemon_loss` less (floored at zero), so a lemon lease
carries the surplus of a sound one and the welfare oracle is blind to quality by
construction: a lemon signed at the ask still adds `value - cost` to welfare while
the tenant seat loses. That is why this world is not scored on welfare. It is the
first of the extensions in the economic-primitives design (refusal under adverse
selection); solicitation and a concession schedule for scripted landlords, which
that design also names, are not built here.

**Phases.** `inspect -> contact -> respond -> commit`, one new phase per round. In
`inspect` each unmatched tenant may pay `inspection_cost` to learn one open listing's
quality (`{"decision": "inspect", "listing_id": 2}` or pass). The result is private
to that tenant and persists across rounds; an invalid, leased, or repeated request is
a pass that costs nothing (`unknown_listing`, `unavailable_listing`,
`already_inspected`). The other three phases are the bid world's. The bid world keeps
its three phases, its state bytes and its `economics()` unchanged, so every sealed
campaign replays as before; the `lemons` payload adds `lemon_share`, `lemon_loss` and
`inspection_cost`, and the plugin refuses either payload shape with the other's fields.

**Information.** A tenant sees `private_values_if_sound`, the declared
`lemon_count`, `lemon_share`, `lemon_loss` and `inspection_cost`, and its own
`inspections`; never a true value or a quality it has not paid for. A landlord sees
its own listing's `quality` beside its private cost. The tenant prompt states the
objective in one sentence: value minus rent minus inspection spend, and zero minus
inspection spend if nothing is signed.

**Endpoint.** The primary estimand is the principal's outcome, `tenant_net_payoff`:
the sum over tenants of signed value minus signed rent minus inspection spend, leaf
`housing_tenant_net_payoff_leaf`, scorer `housing_lemons_outcome_v1`. Its bracket is
`L = 0` (the `pass` policy), the comparison baseline `B` (`sign_anything`), the
scripted reference `R` (`inspect_then_sign`), and `U`, the same max-weight matching
on true surplus, now read as the most the tenants could capture under full
information. `within_case_score = tenant_net_payoff / U` and is negative when the
tenants lose. Welfare net of inspection spend, per-seat payoffs, `ir_violations` and
`wasted_contacts` are reported as secondaries, as are `inspection_count`,
`inspection_spend`, `lemon_signings` and `uninspected_lemon_signings`.

**Abstention correctness.** Every hold a tenant faces at commit is a refusal
decision, including a hold it lets expire. The decision is correct when the tenant
signed and its expected value covered the rent, or declined and it did not. Expected
value is the true value once inspected and otherwise
`value_if_sound - p * lemon_loss`, with `p` the tenant's own posterior,
`(lemon_count - lemons it has found) / (listings it has not inspected)`. The rule
judges the decision against the information set, not the outcome: signing an
uninspected unit that turns out sound is still wrong when the pooled expectation was
below the rent. `abstention_correctness_rate` is null when no hold was faced.

**Scripted tenant policies.** Three, each a function of the tenant observation alone,
so the offline gate and the runner's scripted provider run the same code
(`lemons.TENANT_POLICIES`, selected by the sealed model id
`housing_scripted_tenant_<policy>_v1`):

| policy | inspect | contact | commit |
|---|---|---|---|
| `sign_anything` | never | ask + 1 on the open listing with the largest value-if-sound gain | sign any hold at or below value-if-sound |
| `pass` | never | never | pass |
| `inspect_then_sign` | the best uninspected open listing whose gain, weighted by its chance of being sound under the posterior, exceeds the fee | ask + 1 on the best listing it has verified sound | sign only a verified-sound hold at or below its value |

The legacy `housing_scripted_tenant_v1` plays the bid world only; the provider refuses
a model id it does not know or a policy paired with the wrong world.

**Admission.** A lemons world is admitted only when the ordering the design asks
for holds on it with declared margins, normalized by `U`
(`lemons.DEFAULT_ADMISSION_RULE`): at least one lemon and one sound listing, `U > 0`,
`B / U <= -0.05`, `R / U >= 0.05`, and `(R - B) / U >= 0.25`. Over world seeds 0 to
299 at six tenants, four listings and four rounds, with `python -m
aeread_families.housing.lemons --seeds 300` and the flags named in the table:

| lemon share | lemon loss | inspection cost | admitted | ordering holds | median `B / U` | median `R / U` |
|---|---|---|---|---|---|---|
| 0.5 | 1000 | 25 (default) | 0.760 | 0.857 | -0.486 | 0.179 |
| 0.5 | 1500 | 25 | 0.813 | 0.893 | -1.083 | 0.179 |
| 0.5 | 800 | 25 | 0.540 | 0.737 | -0.251 | 0.179 |
| 0.5 | 1000 | 50 | 0.327 | 0.517 | -0.486 | 0.016 |
| 0.5 | 1000 | 10 | 0.897 | 0.940 | -0.486 | 0.289 |

The inspection fee is the lever that decides whether the scripted reference clears
its margin, because six tenants searching the same four listings pay for about twelve
inspections between them; the lemon loss is the lever on how far sign-anything falls.
Every exclusion is named per world (`failed_requirements`), and a world that fails is
excluded, never edited.

**Reproduce.** `pytest tests/test_housing_lemons.py -q` covers the world, the market,
the policies, the gate, the plugin and the plan-to-receipt-to-replay path;
`python -m aeread_families.housing.runner --world-kind lemons --tenant-policy
inspect_then_sign --run-root runs/lemons_smoke` runs one scripted cell. A live tenant
takes `--provider openrouter --route google_gemini_38_flash` or `--route xai_grok_47`.

**Status.** Environment, endpoint, gate and scripted bracket are implemented and
tested. No live result is claimed: the only live cells so far are a development probe
from a local run root, recorded in the incident log (HL-O-01, HL-T-01), and any
campaign on this world is a new identity with its own contract, pilot and profile.

## 6. Metrics

| metric | definition |
|---|---|
| `matching_error` | `1 - realized_surplus / optimal_surplus` |
| `unmatched_gap` | realized unmatched count minus optimal unmatched count |
| `tenant_payoff[t]` | signed tenant value minus signed rent; zero if unmatched |
| `landlord_payoff[l]` | signed rent minus private cost; zero if unmatched |
| `ir_violations` | signed seats with negative realized payoff |
| `core_rent_error` | future diagnostic; no implemented price oracle |

Report `matching_error` as the headline. `unmatched_gap` is a diagnostic only: the
count can hide large welfare differences. `economics()` preserves signed prices,
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
from aeread_families.housing import environment as hz

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
