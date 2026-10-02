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

**Round budget (ruling, 2026-09-25): new lemons identities use 3 rounds.** The first
two identities kept the bid world's pinned 4, which was never chosen for this world.
Over seeds 0-299 the scripted bracket is the same at 3, 4 and 6 rounds (admitted
75%, 76%, 76%; ordering holds on 85%, 86%, 86%; median `R / U` 0.179 at each), and
every world of the v2 pack is admitted at 3 with the same `R / U` and `B / U` as at 4.
In the v2 runs the fourth round held about 20% of the model calls (Gemini 692 of
3,261, GLM 638 of 3,137) and 1 and 5 of the 92 and 104 leases. Two rounds is not
the default: admission falls to 68% and ordering to 78%, two v2 pack worlds fail,
and a tenant can inspect at most two of four listings, so the world would test
deciding under a deadline rather than refusing a lemon; that is a separate arm if
it is wanted. The round count is a frozen control, so a 3-round run is a new
identity, compared within itself and not against v2.

**Reproduce.** `pytest tests/test_housing_lemons.py -q` covers the world, the market,
the policies, the gate, the plugin and the plan-to-receipt-to-replay path;
`python -m aeread_families.housing.runner --world-kind lemons --tenant-policy
inspect_then_sign --run-root runs/lemons_smoke` runs one scripted cell. A live tenant
takes `--provider openrouter --route google_gemini_38_flash` or `--route xai_grok_47`.

### Exploratory price negotiation probe

`housing_lemons_price_probe_v1` is a separate, provider-free experiment over the
same `HousingMarket` inspection, offer, response, and commit transitions. It does
not alter the frozen refusal campaigns or their scores. Each tenant inspects one
open listing per round, offers $100 below the quality-adjusted ask for a known
listing, and signs a counteroffer only when its inspected value covers that rent.
The fixed landlord accepts an opening offer at or above its target; otherwise it
counters at its reservation cost plus $25, capped at ask. A tenant can sign or
walk that hold, but cannot continue negotiating the same listing after walking.

The probe runs the same seeded mixed-quality worlds twice. In the `true_cost` arm,
lemon landlords reserve against their lower true cost. In the `pooled` arm, both
qualities use the sound-equivalent reservation; a counteroffer then does not
mechanically reveal quality. The target rule is fixed in both arms, and the
tenant receives only its own observation. This is a mechanics and information
design comparison, not a test of model bargaining ability.

Run `PYTHONPATH=src python -m aeread_families.housing.price_bargaining --seeds 30`
for seeds 100000–100029, six tenants, four listings, three rounds, 50% lemons,
and a $1,000 quality loss. The output retains listings, signings, counteroffers,
signed rents, and signed rent relative to the listing's posted ask by quality.
For this fixed 30-world development panel:

| Landlord reservation | Quality | Signed / listings | Mean signed rent | Mean signed rent − ask | Signed after counter |
|---|---|---:|---:|---:|---:|
| true cost | sound | 56 / 60 | $2,251.95 | −$27.19 | 56 |
| true cost | lemon | 59 / 60 | $1,407.52 | −$1,028.00 | 59 |
| pooled | sound | 58 / 60 | $2,242.63 | −$27.18 | 58 |
| pooled | lemon | 0 / 60 | undefined | undefined | 0 |

The true-cost signed discount gap is $1,000.81 (sound minus lemon rent-minus-ask).
Raw mean rents mix different posted asks, and signed prices condition on a lease;
therefore the sign rates and eligible-listing denominators belong beside every
price comparison. The near-$1,000 gap is mostly a consequence of the declared
$1,000 cost shift and this fixed concession rule. No model tenant was run and no
statistical population claim is made from this selected panel. A future scored
model-tenant campaign needs its own identity and reference outcomes recomputed
under this landlord; reusing the refusal campaign's reference would mis-score it.

The first versioned model-tenant development pilot is declared in
`configs/housing_lemons_price_pilot_v1.json` and run by
`aeread_families.housing.price_campaign`. It pairs four worlds across the
true-cost and pooled arms (eight cells, one inference seed, three rounds), pins
Gemini 3.8 Flash on Google AI Studio, and assigns a $0.30 tenant ceiling per
cell and a $3 total stop ceiling. `--run-root <path>` performs the provider-free
eight-cell preflight; adding `--live` uses the pinned paid route. The driver
writes one result per cell, verifies the receipt and state-and-score replay,
halts on its first operational failure, and leaves untouched cells unattempted.
The price table conditions on completed cells and retains the eligible-listing
denominator. This small panel supports a diagnostic only; there is no model
ranking or population interval.

Two further identities, `housing_lemons_price_pilot_v2_glm53_flash_deepinfra` and
`housing_lemons_price_pilot_v2_gpt56_luna`, put the same four worlds and both arms
in front of GLM 5.3 Flash (DeepInfra, fp4) and GPT-5.6 Luna (OpenAI), so the models
see identical lemon draws. Luna accepts no temperature or top_p; its profile
declares `sampling_controls.temperature = "unavailable"` and sends neither, and a
test asserts exactly what each identity puts on the wire. Their route pins live in
`price_campaign.py` and not in `runner.py`, because a plan's implementation digests
hash `runner.py`, `environment.py`, `lemons.py` and `price_bargaining.py`, and
editing any of them moves the run-plan id of every sealed Housing identity (HL-T-04;
`test_sealed_v1_plan_identity_survives_edits_to_this_module` pins the sealed ids).
The DeepInfra identity ran once and failed (HL-O-08): its fp4 endpoint returns the
answer in `reasoning` with `content` null on most calls, so a cell of about 57 calls
cannot complete under this client. The same model on Parasail
(`housing_lemons_price_pilot_v2_glm53_flash_parasail`, same controls) and Luna each
completed all eight cells live ($0.051 and $0.105, no operational failure), as
unpublished development pilots in local run roots. On the same four worlds all three
models signed blind lowballs that the landlord's reply had already marked as lemons
(2, 2 and 4 signings; expected loss $833, $1,333 and $1,833 over the four `true_cost`
worlds for Gemini, GLM and Luna), while the realized `true_cost` minus `pooled`
contrast changes sign by model and by world (per-world spreads of 160 to 420), so the
arm effect is not established; the reply leak is the consistent finding.

K=2 identities on the same four worlds (`housing_lemons_price_pilot_v3_glm53_flash_parasail_k2`
and `..._v3_gpt56_luna_k2`, 16 cells each, $0.101 and $0.214, no operational failure)
measure the replicate noise the K=1 runs could not. Pooling each model's K=1 and K=2
cells as three replicates is an exploratory analysis across identities
(`price_endpoint --pool`, `status: exploratory_pool`), not part of either identity's
evidence. Within one world, arm and model, net payoff moves by a standard deviation of
about $266 (GLM) and $200 (Luna) between runs. GLM's arm contrast is dominated by
replicate noise (realized +72, replicate SD 402 against a world SD of 187, so no
world-level signal is detectable); Luna's is dominated by the world (realized -110,
world means +493, -319, -561, -52, a strong world-by-arm interaction). Neither is
distinguishable from zero over four worlds (SE 94 and 226). The consistent finding is
the reply leak: Luna signed a blind lemon the reply had already marked in 10 of 12
`true_cost` cells ($569 expected loss per cell), GLM in 4 of 12 ($250).

The 60-world panels (`housing_lemons_price_pilot_v4_glm53_flash_parasail_w60` and
`..._v4_gpt56_luna_w60`, seeds 100000-100059, K=1, 118 and 114 completed cells,
$0.81 and about $1.9) were sized to detect a $150 arm contrast. Four cells ended in
rate-limit or timeout failures caused by the session's parallel workers (HL-O-09,
HL-O-10) and stay missing, so GLM has 59 complete world pairs and Luna 57. With worlds
as the resampling unit, `true_cost` minus `pooled`: GLM realized -49 [-148, +53],
Luna realized -176 [-269, -80]; at the stated odds +208 [112, 308] and +266 [181, 349];
at the reply-conditioned odds -150 [-244, -55] and -278 [-371, -182]. A blind signing the
landlord's reply had already marked as a lemon occurred in 59% of GLM's and 82% of Luna's
`true_cost` worlds (never under `pooled`), $359 and $544 expected loss per cell; Luna
did it alone in 18 worlds against 6 for GLM (sign test p = 0.023). The stated-odds
measure ranks `true_cost` above `pooled` and the realized and reply-conditioned measures
rank it below, because a lowball the landlord accepts looks worth its price at the prior
and is a certain lemon once the reply is read. The favourite's quality (the covariate,
about 50/50 by chance) does not separate the contrasts. The four-world K=3 estimates
(GLM +72, Luna -110) were inside their noise; GLM's had the wrong sign.

**Same-state disclosure probe** (`price_disclosure_probe.py`; a diagnostic, not evidence).
The commit-phase states the 60-world panels recorded are replayed unchanged with the
original instructions, a qualitative hint, and an explicit statement that a sound listing's
landlord never concedes more than $250 below the ask. For blind `true_cost` holds more than
$250 below ask, signing falls from 72% to 7% (GLM) and from 91% to 13% (Luna); holds within
$250, informed holds and `pooled`-arm holds do not move. Both models therefore discount for
adverse selection when told how, and the panels' exposure is a disclosure gap, not a
reasoning one. Turning the disclosure into an identity needs a tenant prompt with its own id,
which lives in `runner.py`; editing that file moves every sealed Housing plan id (HL-T-04).

**The price pilot's ex-ante endpoint** (`price_endpoint.py`). Realized net payoff
mixes the tenant's decisions with the lemon draw, and the `true_cost` landlord adds a
third thing: it reserves on a lemon's own cost, so a hold below the lowest rent a sound
listing's landlord would take proves the listing a lemon, while the tenant's stated
odds do not move. Each commit decision is scored at the stated odds (the
`lemons_gap` decomposition: informed leases, blind good and bad bets, lemon draws,
inspection spend, which sums exactly to the realized net) and at the
response-conditioned odds, where such a hold is a certain lemon; the difference is the
reply leak. On the Gemini pilot the `true_cost` arm looks better than `pooled` by
+$129 per world at the stated odds and worse by $79 realized, because in two worlds a
blind lowball was accepted and the acceptance had already said lemon ($500 and $333 in
expectation). The "lemon draw" in that arm is therefore selection by the landlord's
reply, not luck, and a luck-removed score at stated odds is biased there. The
response-conditioned score is an evaluator's benchmark: the floor uses the sound cost,
which no tenant sees.

**Quality-blind admission and a declared stratum** (`lemons_design.py`, HL-D-03). The
favourite's quality is a declared stratum; a seed is admitted only if the sealed rule
passes under both strata, so every admitted world appears in both and the stratum
contrast is paired within the world. Built and tested, wired to no contract: a new
identity must declare it, and must declare that blind admission shifts the pack toward
less contested favourites (41% of seeds with a five-or-six-tenant favourite survive,
against 69% for three or four).

**Status.** Environment, endpoint, gate and scripted bracket are implemented and
tested. No live result is claimed: the only live cells so far are a development probe
from a local run root, recorded in the incident log (HL-O-01, HL-T-01). The first
campaign identity on this world, the descriptive single-route pilot
`housing_lemons_refusal_pilot_v1`, is specified in the [QC profile](qc.md) §20.

### One deciding tenant and outside demand

The six-tenant price panels measured mostly who won a contested listing (HL-D-04): a
tie-break by seat number, the scripted rivals' one-dollar overbid, and, with six sampled
copies, an opening round that already differed between the two landlord arms. The
outside-demand pilot (`price_outside_demand.py`) keeps one deciding tenant, seat 0, and
replaces the rivals with a declared rule: at the end of every round each open listing the
tenant made no offer on is taken with probability 0.5, sound or lemon alike, on a
schedule the world fixes, so both landlord arms and every model meet the same departures.
A listing the tenant bid on cannot be taken in that round. The tenant is told the rule.
The worlds are the 60 of the earlier panels (seeds 100000-100059), so the asks, the
lemons and seat 0's values are unchanged.

`housing_lemons_price_pilot_v10_glm53_flash_parasail_outside_w60` and
`..._v10_deepseek_v4_flash_parasail_outside_w60`, K=1, 120 of 120 cells each, $0.09 and
$0.58. The owner asked for DeepInfra; its shared pool was overloaded and the v8 and v9
identities on that route have only failed gate cells (HL-O-15, HL-O-16). These are
development pilots: the notice that tells the tenant the rule is appended by the seat
router and is not in the kernel's sealed request (HL-D-05).

| Seat 0 | GLM 5.3 Flash | DeepSeek V4 Flash 0731 |
|---|---|---|
| Signs a sound listing, lemon-landlord / pooled arm | 77% / 80% | 77% / 85% |
| Signs a lemon, lemon-landlord / pooled arm | 17% / 2% | 15% / 3% |
| Signs nothing, lemon-landlord / pooled arm | 7% / 18% | 8% / 12% |
| Signs an uninspected listing after a revealing reply (lemon-landlord arm) | 15% of cells | 10% of cells |
| Mean net payoff, lemon-landlord / pooled arm | $204 / $247 | $251 / $289 |
| `true_cost` minus `pooled`, realized | -43 [-117, +31] | -38 [-86, +11] |
| `true_cost` minus `pooled`, at the stated odds | +57 [0, +114] | +40 [-4, +85] |
| `true_cost` minus `pooled`, at the reply-conditioned odds | -43 [-102, +16] | -26 [-78, +25] |

Intervals are 95% t-intervals over 60 paired worlds. No arm contrast is distinguishable
from zero on the realized or the reply-conditioned measure for either model; the sign
pattern of the six-tenant panels survives (the lemon landlord looks better at the stated
odds and worse once the reply is read). The sizes are not comparable with those panels'
published contrasts, which summed six seats. DeepSeek minus
GLM on the same worlds, both arms averaged: realized +45 [+1, +88], stated odds
+6 [-34, +46], reply-conditioned +23 [-24, +69]; the two ex-ante measures do not separate
the models. The two share a declared reasoning effort and not a reasoning condition:
DeepSeek writes 2,600 to 12,000 reasoning tokens a call and GLM 35 to 530 (HL-O-17).

What the redesign bought. Seat 0 reaches a sound listing in 77 to 85% of cells, against
38% with six copies of GLM and 22% against either scripted rival. In worlds where seat 0
held no lemon in either arm, where the landlord arm cannot matter, the contrast has a
standard deviation of $126 for GLM (6 of 40 worlds beyond $100) and $81 for DeepSeek
(4 of 45); in the six-copy GLM panel it was $259 (16 of 34). What is left is the
tenant's own sampling: its round-0 offer is the same listing at the same rent in both
arms in only 8 (GLM) and 12 (DeepSeek) of 60 worlds. The arm's effect sits in the worlds
where seat 0 held a lemon: 20 for GLM (mean -121, sd 451) and 15 for DeepSeek
(mean -87, sd 339), too few to size from one replicate.

Gemini 3.8 Flash on the same panel (`..._v10_gemini38_flash_outside_w60`, 120 of 120
cells, $0.80) signs a sound listing in 87% and 88% of cells and a lemon in 8% and 3%.
Its `true_cost` minus `pooled` contrast is +3 [-2, +8]: it plays the same opening
inspection and offer in both arms in all 60 worlds, so 56 world pairs are identical and
the tenant's own sampling noise, which dominates the GLM and DeepSeek pairs, is absent.
Mean net payoff per world over both arms, and the scripted inspect-then-sign rule run
through the same market provider-free:

| Seat 0 | Realized | At the stated odds | At the reply-conditioned odds |
|---|---|---|---|
| Scripted inspect-then-sign | $241 | $241 | $241 |
| GLM 5.3 Flash | $225 | $253 | $203 |
| DeepSeek V4 Flash 0731 | $270 | $259 | $225 |
| Gemini 3.8 Flash | $275 | $258 | $253 |

At the stated odds the three models are within $6 of each other and none is
distinguishable from the scripted rule (Gemini +18 [-10, +45]). Gemini minus GLM is
+50 [+7, +93] at the reply-conditioned odds and +50 [+10, +90] realized; Gemini minus
DeepSeek is +27 [-3, +57] and +5 [-22, +32]. The gap to GLM has two sources that are not
the same capability: Gemini signs an uninspected listing after a revealing reply in 2% of
lemon-landlord cells against GLM's 15%, and GLM lost 21 actions in 12 cells to malformed
or unavailable-listing outputs where DeepSeek and Gemini lost none.

What this panel does not control, and so what a model gap here may be instead of
capability: the declared reasoning effort is the same and the reasoning is not (GLM 35 to
530 tokens a call, Gemini a median of 196, DeepSeek 2,600 to 12,000); one route returns
the same answer for the same seed and the other two do not; the tenant is not told that
there are three rounds; after walking from a hold it no longer sees the counteroffer it
was given; and the landlord's rule leaves a median of $30 between a sound listing's ask
and its lowest acceptable rent, against $449 between the tenant's best- and
worst-looking listing, so the score is listing choice and inspection, not bargaining.

#### The retry with those factors controlled (v11 and v12)

Same 60 worlds and market. Changed: the tenant is told the market lasts three rounds and
that it may offer again on a listing it walked from, and it is shown its own earlier
offers, the landlords' binding rents and its decisions (notice v2); temperature 0 for
every model; both open-weight models on one provider at fp8 (NextBit). Lost actions are
counted apart from decisions. Not changed: the market still rewards choosing and
inspecting far more than bargaining, and Gemini's serving stack cannot be matched.

Reasoning could not be made equal. GLM and Gemini refuse effort "none"; GLM writes about
the same at any declared effort; DeepSeek writes nothing at "none" and thousands of tokens
at anything else, ignoring a token budget. The light tier is the closest available set:

| Seat 0, 120 of 120 cells each | Scripted rule | GLM 5.3 Flash, "low" | DeepSeek V4 Flash, "none" | Gemini 3.8 Flash, "minimal" |
|---|---|---|---|---|
| Reasoning tokens per call, median (max) | 0 | 32 (310) | 0 (0) | 240 (1,591) |
| Signs sound / lemon / nothing | 70 / 0 / 30% | 81 / 14 / 5% | 49 / 2 / 49% | 91 / 3 / 6% |
| Lost actions (cells) | 0 | 3 (3) | 6 (6) | 0 |
| Same opening move in both arms | 60 of 60 | 22 of 60 | 28 of 60 | 58 of 60 |
| Mean net, realized | $241 | $186 | $104 | $301 |
| Mean net, at the stated odds | $241 | $257 | $113 | $296 |
| Mean net, at the reply-conditioned odds | $241 | $192 | $113 | $285 |
| Cost | $0 | $0.08 | $0.29 | $1.01 |

Against the scripted rule, paired by world: Gemini +61 [+23, +99] realized, +55 [+22, +88]
at the stated odds and +44 [+6, +82] at the reply-conditioned odds, the first model in
this market to beat it. GLM is -54 [-120, +11], +17 [-28, +61] and -49 [-104, +6].
DeepSeek without reasoning is -136 [-190, -83], below the rule on every measure: it ends
with no lease in half its cells. Gemini minus GLM is +115 [+53, +177] realized and
+93 [+41, +145] reply-conditioned (+92 [+38, +145] on the 58 worlds where neither lost an
action), and +39 [-3, +81] at the stated odds: the two choose listings about equally
well and differ in what they do with the landlord's reply. GLM signs an uninspected
listing after a revealing reply in 20% of lemon-landlord cells, Gemini in 3%, DeepSeek in
none; GLM's `true_cost` minus `pooled` contrast at the reply-conditioned odds is
-71 [-131, -10], Gemini's -20 [-50, +11].

Temperature 0 did not make the open-weight route repeat itself: the opening move is the
same in both arms in 22 (GLM) and 28 (DeepSeek) of 60 worlds, up from 8 and 12 at
temperature 1, against 58 for Gemini. Their pairs still carry the tenant's own noise.

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
