# Integrator and client: negotiating who carries the risk

Draft design, 2026-09-24. Proposed as the next data-center case in place of the
shared-feeder joint venture (draft PRs #214 and #216). Generator and reference:
`src/aeread_families/datacenter_development/risk_allocation.py`
(`python -m aeread_families.datacenter_development.risk_allocation --out pack.json`),
tests in `tests/test_datacenter_risk_allocation.py`. Not wired into the environment.

## What the negotiation half taught

| Finding ([QC profile](qc.md), [design findings](design_findings_2026-09.md)) | Rule for this case |
|---|---|
| In the 30 bundles audited on 2026-09-19, walking away beat the scripted reference, so nothing could show a model negotiating well (DC-D-01) | The reference is the best play on the client's information, and every world checks it against walking and five other constant policies |
| The six channels have one policy shape; the reference sits at a band edge; adopting the counter was the scored optimum (DC-D-03) | The counterparty has conduct: private costs, a pricing rule, a falling ask and a break-off hazard. Copying its counter gives up at least one step of the ask |
| Only 25% of confirmatory cells finished validly, and more channels meant more chances to break protocol | Two rounds; every proposal is one full package and a price, which is the shape that succeeded 9 of 10 times against 5 of 10 for acceptance by reference |
| The joint venture had one decision with two answers; the symmetric version was focal (8 of 8 fair share) | Four clauses and a price. Whether a clause is worth moving depends on the world and on the integrator's private costs, and six different contracts are efficient across the draft pack |
| Joint-venture probes: the answer must be a best response under a declared prior (DC-D-20, on the joint-venture branch); the observation must carry every number it uses; a generator must not filter out the worlds where a rule is wrong; a threshold heuristic passed 9 of 12 | The prior over the integrator's costs is stated; a test checks every number in the brief; each rule named as a loser must lose in its cell; twins share every public fact |
| One confirmatory, one route, no power analysis | Before any claim: at least two routes, and a pilot sized from the regret spread (below) |

## What is tested, and how it differs from supplier judgment

The case tests negotiating the allocation of risk and reward between two
businesses. The client has to work out:

- which risks to move;
- what to ask the other side to price;
- what a clause is worth to each side;
- how hard to push;
- when to walk.

It does not test judging the counterparty's quality, which is what the
procurement [supplier-judgment case](../procurement-allocation/hidden_information_case.md)
does.

| | Supplier judgment | Risk allocation |
|---|---|---|
| Hidden | whether a supplier is good or bad | what it costs the integrator to carry each risk |
| Learned from | a public record, samples, deliveries | the integrator's prices for alternative contracts |
| Decided | whom to buy from, whether to test | what contract to sign, at what price, how fast |
| Value comes from | avoiding a bad supplier | moving each risk to the side that carries it more cheaply, and keeping part of the saving |

The integrator's competence is public: every risk's probability is declared,
and both parties know it.

## The world

A client commissions an integrator to deliver a GPU cluster into the client's
own facility. Hardware costs $9.6M and is passed through at cost; the
integrator's own delivery cost is $0.6M. Money is in $ thousands.

| Risk (declared) | Probability | Cost when it happens |
|---|---|---|
| Compatibility defect | 25-35%, or 4-8% if the integrator pre-stages the cluster | fix $200-300k, and 3-5 weeks of delay |
| Client facility not ready | 20-30% | 2-4 weeks of delay, and $150-220k of integrator standby |
| Post-handover incident | 4-6% | $2.5-3.5M lost by the client |
| Each week of delay | | $90-130k of the client's revenue |

| Clause | Levels |
|---|---|
| warranty | none · fix (integrator pays the fix) · fix_and_delay (fix plus $100k per week of defect delay) |
| readiness | client pays standby · integrator does |
| consequential | excluded (client carries the incident) · included |
| deposit | half the hardware at signing, 13 weeks early · on delivery |

A clause changes the value of the contract to both sides together only through
three channels:

- **Control.** The integrator pre-stages the cluster, at a private cost of $40k,
  $120k or $200k, only if the contract makes testing pay for it. That means a
  warranty whose avoided defects outweigh the test's cost. In the other
  direction, the client's facility is outside the integrator's control, so the
  integrator adds 150% of expected standby if it has to carry readiness. The
  tests pin this: moving readiness to the integrator never helps in any world.
- **Risk charge.** Each side pays a charge on every dollar of expected loss it
  carries, from covenants and insurance:
  - the client's charge is declared (0.1 to 1.65 in the draft pack);
  - the integrator's is private, 0.3 or 1.2.

  A loss belongs with whichever side's charge is lower.
- **Capital.** A deposit saves the integrator 14% a year in financing. It costs
  the client its own rate plus the chance that the integrator fails before
  delivery.

Price moves money between the two sides and never changes their joint value
(tested). A clause can therefore create value, only move money (then its fair
price is what it costs the other side), or destroy value.

## The integrator's conduct (declared)

- **Pricing.** It signs any package at its expected cost of that package plus a
  $500k floor margin, plus an ask premium: $400k in its opening, $200k in
  round 1 and $0 in round 2.
- **Counters.** A proposal below its price is answered with the price at which
  it would sign that same package in that round. That counter is how the client
  learns the integrator's costs.
- **Break-off and delay.** After each refused proposal it breaks off with a
  declared probability (3-47% in the draft pack), and the client loses $25k per refused
  round.
- **The client's outside option** is a turnkey contract at a stated all-in cost.

Its opening is the defensive proposal: no warranty, the client carries readiness
and the incident, and the deposit is paid at signing. The opening's cost does not
depend on the integrator's private costs, so it reveals nothing (tested).
Haggling over the opening therefore learns nothing. Asking the integrator to
price the full-warranty alternative identifies all six private types in one
counter in 14 of the 16 draft worlds (tested on the base world). In the other
two, both keep_their_terms, it leaves three types, which do not change the
answer.

## Reference and grading

The reference is exact:

- **The dynamic programme.** It runs over which integrator types are still
  consistent with every price the client has seen. It only needs to consider
  proposing at a consistent type's ask, or below every ask (a request to price
  the package), since any other price is dominated.
- **Break-off is the only chance event,** so any policy's expected cost is
  computed exactly, not simulated. The reference's value equals the solver's
  (tested).
- **Decision regret** is what an action gives up against the best action, in
  expected cost to the client, on the client's own information. It is summed
  over decisions, so a model that learns the type and then signs a poor
  contract is charged for the signing.
- **Diagnostics, not scores**, measured against the true type:
  - *allocation*: joint value lost against the efficient contract;
  - *price*: the amount paid above the floor for the contract signed;
  - *pace*: rounds and break-off exposure beyond the reference.

A worked world, `price_the_alternatives_2461001` and its twin. The two share
every public fact and the same $10,932k opening:

| | Integrator charge 1.2 | Twin, charge 0.3 |
|---|---|---|
| Round 1 (reference) | ask for the full-warranty price | the same |
| Counter, then floor | $10,825.7k, then $10,625.7k | $10,803.7k, then $10,603.7k |
| Types left | one | one |
| Round 2 (reference) | fix / client / excluded / at signing, at its floor $10,590.5k | fix_and_delay / client / included / at signing, at $10,785.7k |
| Why | the client's 0.75 charge is below 1.2, so keep the tail; the integrator tests under "fix" alone | 0.3 is below 0.75, so move the tail and the delay damages |
| Joint value over the opening | +$245k | +$323k |
| Price-only haggling loses | $226k | $297k |

## The pack (draft, 2 seeds per cell plus twins, 16 worlds)

A world is admitted only if its intended first move beats every other kind of
first move by at least $10k in expectation. Every rule named as a loser must
also give up at least $25k. Twins are added where the right contract depends on
the hidden type.

The six columns after "First move" are the rules that don't negotiate the
allocation: accept the opening, walk, take the first counter, haggle price only,
demand every protection, and sign the prior-best package now. Cells are regret
ranges across the cell's worlds, $k, expected over the prior on the
integrator's type.

| Cell | What it teaches | First move | Accept | Walk | Take counter | Price only | Demand all | Sign prior-best |
|---|---|---|---|---|---|---|---|---|
| keep_their_terms | the defensive proposal is already efficient: negotiate price, not terms | ask for a price | 319-345 | 449-483 | 180-188 | 0 | 257-279 | 119-145 |
| price_the_alternatives | which risks to move depends on the integrator's costs: ask it to price the alternative | price an alternative | 464-536 | 458-881 | 211-215 | 114-187 | 119-156 | 257-258 |
| shift_the_tail | the client carries loss dearer than any integrator: move the tail and the delay | price an alternative | 675-818 | 1003-1073 | 184-190 | 364-472 | 44-54 | 225-284 |
| better_contract_or_walk | on the opening terms turnkey wins; only a better allocation beats walking | price an alternative | 576-704 | 71-137 | 211-220 | 195-320 | 99-186 | 283-301 |
| walk_away | no allocation beats turnkey: walk before spending a round | walk | 926-1063 | 0 | 507-539 | 487-615 | 442-519 | 645-675 |
| close_now | high break-off and a large surplus: sign now | sign at a price | 468-639 | 1135-1498 | 412-644 | 551-856 | 318-554 | 0 |

- Each rule is right in at most one cell.
- Demanding every protection is never right, because readiness always belongs
  with the client.
- Copying the counter is never right: it loses at least $180k in every world.
- Six different contracts are efficient across the pack.

## Stated simplifications

- Expectations stand in for realised outcomes. A realised draw, with common
  random numbers across models, is for display only.
- The four risk events are independent, and there is one delay cost per week.
- Liquidated damages are uncapped.
- The integrator's pre-staging is its best response to the contract.
- The integrator prices honestly by a declared rule. Strategic misreporting is
  a later cell.
- The first-move kind "price an alternative" is often met by the same package
  (full warranty), so the first move alone separates little. The second move,
  which contract to sign once the counter is in, carries most of the regret.
- The source document that prompted the case is a real firm's proposal and is
  not in the repository. Nothing here is drawn from its figures.

## Before a live run (new pack and campaign identity)

1. **The integrator seat.** The same facts, with the model writing the proposal
   against a scripted client whose risk charge is private. The facts must stay
   identical across seats.
2. **Environment wiring:**
   - a plugin whose one action is a full package and a price, plus accept and
     walk;
   - the brief (`brief_text`) as the observation;
   - counters as replies;
   - `decision_regret` per move, with the allocation, price and pace
     diagnostics.
3. **Leak audits:** clause names carry no verdict; renaming the levels leaves
   the reference unchanged; the brief's numbers match the world.
4. **Checks before a campaign:** a manual trace of one world through the
   plugin, then a crossed pilot on at least two routes, sized from the spread
   of regret across the pack.
