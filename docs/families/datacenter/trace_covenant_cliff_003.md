# A manual trace: one cell from observation to sealed score

One cell, walked by hand from the JSON the developer seat receives, through the
text the model emitted, through parse, legality and state transition, to the
five sealed measurement leaves. Everything below is read out of sealed evidence,
not reconstructed.

| | |
|---|---|
| Cell | `covenant_cliff_003__gemini38_flash_aistudio__seed_41211` |
| Case | `datacenter_development_v1.worlds_v2.covenant_cliff_003`, pinned at `2f2eeef4…` |
| Receipt | `2730cad736374f62…`, status `completed` |
| Logical actions | 27 (17 billed developer calls, 10 free scripted counterparty turns) |
| Tokens | 76,274 in / 5,985 out |
| Cell cost | $0.0789 |

A caveat that matters for reading any number here: this cell ran against world
pack `a5bb0ccc`. The pack has been regenerated twice since, most recently by the
repricing this trace prompted, and is now `a9cf905a`. See the last section.

---

## Step 0: the plan

**Input.** The developer seat gets one observation with nine keys. The
`project_facts` block is the frozen world: a 36-month horizon, 50,000 kW of
energized capacity reaching full output in month 22 and built capacity in month
24, energy at 7 cents per kWh, operating cost 4,400 cents per kW-month, a
1,200 basis point developer discount rate, a $300M equity budget and a $1.3B
appraised value. The negotiation block names six agreements to open, three rounds each,
`land_amendment` optional, and one ordering prerequisite: the amendment cannot
precede the lease it amends.

The action schema for this phase is `datacenter_sequence_plan_v1`. The phase
declares six possible successors, one per agreement, because the developer is
about to choose which it opens first.

**Response.** 1,457 input tokens in, 21 out, $0.0012:

```json
{"order": ["land", "power", "epc", "service", "land_amendment", "loan"]}
```

**Parse.** `parse_action` returns
`{"decision": "sequence", "order": [...], "ok": true}`. It supplies the
`decision` key; the model only has to name an order.

**Legality.** Checked against three rules: the order is a permutation of the six
agreements, no prerequisite is violated, and every optional agreement that is
omitted is one the world declared optional. All pass.

**Transition.** State advances from `b97f3a56…` to `cbb28ff1…`, and
`next_phase_id` becomes `land_developer_offer`. The chosen order is written into
state, so the rest of the episode is driven by the model's own choice rather
than by the listing order.

This is the planning half of the family in one action. The order decides what
the developer knows when it commits. Opening financing last means signing the
lease before learning the lender's private bankability minimums.

---

## Steps 1 to 5: the land agreement, and the move that decided the episode

The developer opened at a $20M purchase price with site control through month
36. The landowner countered, and the counter carried a message:

> We cannot sign this. We need purchase_price_cents of at least 4250000000;
> site_control_expiry_month of no more than 30.

On price the package matched the bound exactly. On site control it did not: the
package attached to that counter offered **month 22**, eight months worse for
the developer than the month 30 the prose had just named.

The developer's next offer took the price it was told to take and the *bound*
rather than the package:

> Accepting landowner counter-terms with purchase price 4,250,000,000 cents and
> site control through month 30.

The landowner accepted, the developer signed, and land closed in three rounds.

**Why this is the whole episode.** Construction completes in month 24. Re-run
the sealed stack with the only change being site control at month 22, the value
the counter package actually proposed:

| | site control to month 30 | had it copied the package: month 22 |
|---|---|---|
| Developer equity NPV | $465.6M | $465.6M |
| Site control holds through operations | yes | **no** |
| Admitted | yes | **no** |

The primary measure does not move at all. The difference is invisible in NPV
and decisive in the constraint vector. That is the reason
`project_constraint_satisfaction` is an admission leaf rather than a component
of the headline: a stack that cannot be built is not a cheaper stack, it is not
a stack.

---

## Steps 6 to 10: the power agreement, traced in full

**Input.** Same observation shape, now with `agreement_key: "power"`,
`latest_offer: null`, and an `executed_agreements` block containing the signed
land deal. The public history carries all six prior moves verbatim, including
the landowner's counter message. Nothing about the utility's private policy is
visible.

**Response (step 6).** 2,337 in / 249 out, $0.0027. The model proposed 50,000 kW
contracted capacity, energization in month 22, a 1,000 cents per kW-month demand
charge, $25M interconnection cost, $10M developer security, and conditions
precedent of site control and zoning approval.

**Counterparty (step 7).** The scripted utility is not a model. It runs
`terms_acceptable` against its private policy: hard bounds first, then a linear
valuation. The offer fails the bounds, so it counters with a fixed package from
its policy and a message saying what is short:

> We cannot sign this. We need monthly_demand_charge_cents_per_kw of at least
> 1190; developer_security_cents of no more than 20000000;
> interconnection_cost_cents of no more than 2000000000; conditions precedent
> covering power_commitment.

Note what the counter package quoted for contracted capacity: 50,000 kW, the
full amount. That is luck, not logic. The package is fixed per world, and in
this world it happened to quote full capacity. In 15 of the 24 worlds in the
current pack it quotes 40,000 kW against a tenant that will need 50,000, and
copying it strands the project. A developer that treats the counter as
authoritative is not reading a counterparty that only asks for what it needs.

**Response (step 8).** 3,297 in / 548 out, $0.0045. The model adopted the
counter package verbatim, including a demand charge of 1,400 against a stated
floor of 1,190.

> Accepting utility counter terms with monthly demand charge of 1400 cents/kW
> and interconnection cost of 2,000,000,000 cents.

The same model that used the stated bound in the land agreement copied the
package in the power agreement, four actions later, in the same episode.

**Steps 9 and 10.** The utility accepts; the developer signs
`offer_c89ef10c…`; the phase advances to `epc_developer_offer`.

**What copying cost.** Re-pricing the sealed stack across the acceptable region:

| Power package | Utility would accept | Developer equity NPV |
|---|---|---|
| As executed: 1,400, energization month 22 | yes | $465.6M |
| Price floor alone: 1,190, month 22 | **no** | — |
| Trade: 1,190 with month 23 | yes | $467.2M |
| Trade: 1,190 with month 24 | yes | $467.7M |

Moving to the stated floor on its own is refused. The valuation, not the bound,
is what binds once the bounds are met, and the environment says so on the next
round: *the commercial terms are inside what we can sign, but the package as a
whole is not worth enough to us.* The trade exists and the model did not take
it, which is exactly what the family is built to detect. It is worth $2.1M.

---

## Termination, outcome, score

The episode ended after 27 actions with `termination_reason:
agreement_stack_executed`. Five agreements signed, `land_amendment` declined.

`outcome()` runs the executed terms through the cashflow engine and reports the
constraint vector rather than its conjunction, so partial failure is visible:

| Check | Result |
|---|---|
| Site control holds through operations | pass |
| Contracted power covers the lease | pass |
| EPC capacity covers the lease | pass |
| Power conditions precedent met | pass |
| EPC conditions precedent met | pass |
| Financing funded | pass |
| No default | pass |

Diagnostics recorded alongside: the developer chose its own order, the executed
lease met the lender minimums, the loan was *not* opened before the lease, and
`integrative_trade.power` recorded `accepted_the_opening_package: true`,
`trade_captured: false`, with no terms improved and none conceded.

The scorer then seals five leaves. Four are admission gates; one is primary.

| Leaf | Value | Reference | Delta |
|---|---|---|---|
| Developer equity NPV (primary) | $465.63M | scripted baseline $466.52M | **−$0.89M** |
| Total project NPV | $482.10M | scripted baseline $479.25M | +$2.85M |
| Binding contract integrity | 1 | required 1 | — |
| Negotiation temporal compliance | 1 | required 1 | — |
| Project constraint satisfaction | 1 | required 1 | — |

All five carry `status: ok` and `validity: valid`. The cell is admitted, and it
finishes $0.89M behind the scripted reference on the measure that ranks routes.

That is the honest summary of this trajectory: the model got the site-control
term right, which is what made the project buildable at all, and left roughly
$2.1M on the table in the power agreement by copying a counter instead of
reading its own stated floor.

The two figures are not the same quantity. The $0.89M is the gap to the
scripted reference across the whole stack; the $2.1M is what the power
agreement alone was worth. The model was ahead of the reference elsewhere and
behind it here, and the single measure that ranks routes shows only the net.
That is an argument for reading the per-agreement diagnostics, not only the
leaf.

---

## What the trace surfaced

### 1. The integrative trade cost the developer nothing, and is now repriced

Priced across all 24 worlds of the pack as it stood, the best acceptable power
package beat copying the counter in 21 of 24, by a median of $1.43M and at most
$2.06M, against developer NPVs of $400M to $700M. Under half a percent of the
primary measure.

The reason was worse than the size. The optimal move was identical in every
world: push contractual energisation to the policy ceiling and take the price
cut. It cost the developer nothing, because the utility's ceiling was set to the
guaranteed construction completion month, and until construction finishes those
months are already being withheld. The generator said so in its own comment:
deferral was tradeable *because* it was free.

But a concession nobody pays for is not a concession. "Capture the trade"
collapsed into "take the ceiling the counter message already names", which is
the same distributive move as pushing price to the floor, and the
`trade_captured` diagnostic recorded a concession where none was made.

**Fixed.** Deferral is now valued so the utility's cash floors become affordable
at exactly the month that maximises developer NPV, and the ceiling sits two
months past it. Where that month falls is set by the construction schedule,
which lives in the EPC agreement, while the ceiling is handed to the developer
in the counter message. So the decision is two-sided for the first time:

| | median cost to the developer |
|---|---|
| Copying the counter package | $5.04M |
| Conceding all the way to the ceiling | $10.08M |

Both penalties hold in 24 of 24 worlds. Two generation gates now enforce it:
a world whose declared concession costs nothing is never emitted, and the
scripted answer must sit strictly inside the admissible range.

### 2. The panel's evidence is pinned to a pack that no longer exists

The 192-cell panel ran against world pack `a5bb0ccc`; closing the last three
defects replaced it with `eecda1d7`, and the repricing above has replaced that
with `a9cf905a`. The drift
guard works correctly and the config and manifest moved together each time, so
nothing is silently wrong. But every yield figure in the failure analysis,
including the 61 substantive deal failures and 9 admitted cells, describes
worlds that have since been regenerated twice.

The replacement was not cosmetic. In this world alone, the landowner's minimum
price moved from $42.5M to $34M, and the power counter's contracted capacity
moved from 50,000 kW to 40,000 kW. That second change is the per-world
`undersized_quote` draw, now true in 15 of 24 worlds: copying the power counter
breaks the capacity chain in most of the current pack, where in the pack this
cell ran on it did not. Copying is punished far more often now than the panel
data shows, and more again after the repricing.

This is the one finding left open. No panel has been run against the current
pack, so the family's yield figures are stale by construction until one is.
