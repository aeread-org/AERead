# Integrator and client: negotiating who carries the risk

Design and dev pack, 2026-09-24. This is the next data-center case, replacing
the shared-feeder joint venture (#214 and #216, closed unmerged on 2026-09-24;
their incident rows are carried in the log).

| Part | Where |
|---|---|
| Economics, reference, cells, briefs | `src/aeread_families/datacenter_development/risk_allocation.py` |
| Environment plugin and grading | `risk_allocation_environment.py` (same package) |
| Case writer | `risk_allocation_pack.py` (`python -m aeread_families.datacenter_development.risk_allocation_pack risk_allocation_dev_v1 --write`) |
| Cases | `cases/datacenter_risk_allocation_v1/risk_allocation_dev_v1/` (32 cases and `pack.json`) |
| Probe driver | `tools/run_risk_allocation_probe.py` |
| Tests | `tests/test_datacenter_risk_allocation.py`, `tests/test_datacenter_risk_allocation_environment.py` |

## What the negotiation half taught

| Finding ([QC profile](qc.md), [design findings](design_findings_2026-09.md)) | Rule for this case |
|---|---|
| In the 30 bundles audited on 2026-09-19, walking away beat the scripted reference, so nothing could show a model negotiating well (DC-D-01) | The reference is the best play on the model's own information, and every world checks it against walking and the other constant rules |
| The six channels have one policy shape; the reference sits at a band edge; adopting the counter was the scored optimum (DC-D-03) | The counterpart has conduct: private costs, a pricing rule, a falling ask and a break-off hazard. Copying its first counter loses at least $178k in every world |
| Only 25% of confirmatory cells finished validly, and more channels meant more chances to break protocol | Two rounds; every proposal is one full package and a price, which is the shape that succeeded 9 of 10 times against 5 of 10 for acceptance by reference |
| The joint venture had one decision with two answers; the symmetric version was focal (8 of 8 fair share) | Four clauses and a price. Six different contracts are efficient across the dev pack |
| Joint-venture probes: the answer must be a best response under a declared prior (DC-D-20); the observation must carry every number it uses (DC-D-22); a generator must not filter out the worlds where a rule is wrong; a threshold heuristic passed 9 of 12 | Priors are stated in the brief; a test checks every number in both briefs; each rule named as a loser must lose in its cell; twins share every public fact |
| One confirmatory, one route, no power analysis | The probe runs two routes; any claim waits for a pilot sized from the spread of regret |

## What is tested, and how it differs from supplier judgment

The case tests negotiating the allocation of risk and reward between two
businesses. The negotiator has to work out:

- which risks to move;
- what to ask the other side to price;
- what a clause is worth to each side;
- how hard to push;
- when to walk.

It does not test judging the counterpart's quality, which is what the
procurement [supplier-judgment case](../procurement-allocation/hidden_information_case.md)
does.

| | Supplier judgment | Risk allocation |
|---|---|---|
| Hidden | whether a supplier is good or bad | what it costs the other side to carry risk |
| Learned from | a public record, samples, deliveries | the other side's prices for alternative contracts |
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

- **Control.** The integrator pre-stages the cluster, at a cost of $40k, $120k
  or $200k, exactly when the contract makes that cheaper for it: a warranty
  whose avoided defects outweigh the test. In the other direction, the client's
  facility is outside the integrator's control, so the integrator adds 150% of
  expected standby if it has to carry readiness. Moving readiness to the
  integrator never helps in any world (tested).
- **Risk charge.** Each side pays a charge on every dollar of expected loss it
  carries, from covenants and insurance:
  - the client's is 0.15, 0.75 or 1.55;
  - the integrator's is 0.3 or 1.2.

  A loss belongs with whichever side's charge is lower.
- **Capital.** A deposit saves the integrator 14% a year in financing. It costs
  the client its own rate plus the chance that the integrator fails before
  delivery.

Price moves money between the two sides and never changes their joint value
(tested). A clause can therefore create value, only move money (then its fair
price is what it costs the other side), or destroy value.

## Two seats on the same facts

Each world is played twice. What is private depends on the seat:

| | Client seat | Integrator seat |
|---|---|---|
| The model | the client | the integrator, writing the proposal |
| Private to the counterpart | the integrator's pre-staging cost ($40k, $120k or $200k) and risk charge (0.3 or 1.2): six types | the client's risk charge (0.15, 0.75 or 1.55) |
| When the scripted counterpart signs | at a price of at least its cost of the package plus $500k, plus an ask premium ($400k in its opening, $200k in round 1, $0 in round 2) | at a price of at most its turnkey all-in less its expected cost of the package, less a demanded saving ($200k in round 1, $0 in round 2) |
| First standing offer | the integrator's defensive opening: no warranty, client carries readiness and the incident, deposit at signing | none: the client asks for a proposal |
| Model's outside option | the turnkey contract | $500k of other work |

In both seats:

- **A proposal is answered.** A proposal the counterpart will not sign gets the
  price at which it would sign that same package in that round, which becomes
  the standing offer. Proposing with no price asks for that price without
  committing.
- **Refusals cost.** After each refusal the counterpart breaks off with a
  declared probability (3-49% across the pack), and each refused proposal costs
  the model $25k.
- **Rounds.** There are two rounds. After the last answer the model may only
  accept or walk.

The client-seat opening's cost does not depend on the integrator's private
costs, so the opening reveals nothing, and haggling over it learns nothing. The
integrator's answer to "price the full warranty" identifies all six types in 14
of the 16 worlds. In the other two, both `keep_their_terms`, it leaves three,
which do not change the answer.

In the integrator seat, any asked price reveals the client's charge, so its
information step is a single question. That seat mainly tests the proposal:
which package, and pricing it to the client's final bid.

## Reference and grading

- **The reference.** The model's best play is a dynamic programme over which
  counterpart types are still consistent with every price seen. It considers
  proposing at a consistent type's threshold, or with no price; any other price
  is dominated.
- **Exact, not simulated.** Break-off is the only chance event, so every
  policy's expected cost is computed exactly. The reference's value equals the
  solver's (tested).
- **Decision regret is the score.** At each move it is what the action gives up
  against the best action, in expected cost to the model, on the model's own
  information, summed over the episode.
- **Break-off draws.** Each case stores one uniform draw per round, shared by
  both seats of a world and by its twin. Every model meets the same luck, and
  the score does not depend on it.
- **Diagnostics** (`grade`), measured against the true types:
  - *allocation gap*: joint value lost against the better of the efficient
    contract and no deal;
  - *price gap*: in the client seat, paid above the integrator's floor; in the
    integrator seat, left below the client's final bid;
  - *refused rounds*.
- **Invalid moves.** An invalid action ends the episode and is typed
  missingness. The decisions before it are still graded.

A worked world, `price_the_alternatives_2461000` and its twin (client seat).
The two share every public fact, the same $10,932k opening and the same brief,
byte for byte:

| | Integrator: pre-staging $200k, charge 1.2 | Twin: $40k, charge 0.3 |
|---|---|---|
| Round 1 (reference) | ask the price of full warranty, no consequential, deposit at signing | the same |
| Answer, and the floor it implies | $10,981.3k, floor $10,781.3k | $10,801.1k, floor $10,601.1k |
| Types left | one | one |
| Round 2 (reference) | fix_and_delay / client / excluded / on_delivery at its floor, $10,949.3k | fix_and_delay / client / included / on_delivery at $10,964.1k |
| Why | 1.2 is above the client's 0.75, so the client keeps the incident; the full warranty still makes this integrator pre-stage | 0.3 is below 0.75, so the incident moves too |
| Joint value over the opening | +$61k | +$309k |
| Price-only haggling loses | $58k | $290k |

## The dev pack: 16 worlds, 32 cases

Cells are defined on the client seat. A world is admitted only if its intended
first move beats every other kind of first move by at least $10k in
expectation, and every rule named as a loser gives up at least $25k. Twins are
added where the right contract depends on the hidden type.

Client seat. Each rule column is that rule's regret, $k, expected over the
prior, as a range across the cell's worlds:

| Cell | What it teaches | First move | Accept opening | Walk | Take first counter | Price only | Demand every protection | Sign prior-best now |
|---|---|---|---|---|---|---|---|---|
| keep_their_terms | the defensive proposal is already efficient: negotiate price, not terms | ask for a price | 301-333 | 312-637 | 178-180 | 0 | 263-276 | 101-133 |
| price_the_alternatives | which risks to move depends on the integrator's costs: ask it to price the alternative | price an alternative | 525-531 | 461-980 | 221-222 | 176-193 | 97 | 247-271 |
| shift_the_tail | the client carries loss dearer than any integrator: move the tail and the delay | price an alternative | 713-775 | 683-908 | 184 | 386-425 | 29-63 | 240-277 |
| better_contract_or_walk | on the opening terms turnkey wins; only a better allocation beats walking | price an alternative | 542-612 | 75-78 | 234-236 | 165-233 | 90-166 | 316-325 |
| walk_away | no allocation beats turnkey: walk before spending a round | walk | 865-889 | 0 | 404-448 | 453-485 | 341-359 | 501-557 |
| close_now | high break-off and a large surplus: sign now | sign at a price | 480-548 | 1306-1481 | 500-668 | 644-826 | 433-584 | 0 |

Integrator seat, same worlds:

| Cell | First move | Decline to bid | Take first counter | Defend the opening terms | Concede every protection | Sign prior-best now |
|---|---|---|---|---|---|---|
| keep_their_terms | ask for a price | 216-514 | 189-190 | 109-127 | 76-112 | 249-253 |
| price_the_alternatives | ask for a price | 367-1098 | 205-230 | 115-344 | 59-176 | 246-396 |
| shift_the_tail | ask for a price | 855-991 | 191-197 | 170-269 | 76-100 | 199-203 |
| better_contract_or_walk | ask for a price | 110-193 | 203-243 | 227-387 | 43-261 | 239-482 |
| walk_away | decline | 0 | 252-452 | 489-521 | 181-318 | 342-582 |
| close_now | sign at a price | 1466-1561 | 573-709 | 597-708 | 588-689 | 69-91 |

- Each client rule is right in at most one cell.
- Only declining to bid is ever right in the integrator seat, in `walk_away`.
- Copying the first counter never is.
- Six different contracts are efficient across the pack.

## Leak checks and the trace through the environment

Tested in `tests/test_datacenter_risk_allocation_environment.py`:

- **Twins look identical.** Twins with different hidden integrator types get
  byte-identical first observations.
- **The integrator seat's client is hidden.** Its observation is identical
  whatever the client's charge is.
- **No labels leak.** No case id or observation contains a cell name or the
  words lesson, hidden, efficient, reference or twin; case ids are hashes.
- **The briefs are complete.** Every number the reference uses is in each seat's
  brief, and the client's own charge is not in the integrator's.
- **The reference plays clean.** Played through the plugin, it grades zero
  regret in all 32 cases.
- **Rules are charged where the pack says they lose.** Price-only haggling costs
  $0 in `keep_their_terms` and more than $25k where the allocation matters.
  Walking costs $0 in `walk_away` and loses the whole surplus elsewhere.
- **Failures are typed.** Malformed JSON, a bad package, terms on a walk, and
  accepting when there is nothing to accept each end the episode as
  `invalid_action`.
- **The pack regenerates exactly.** The committed cases and `pack.json`
  regenerate byte for byte on Python 3.10 and 3.13. The first build did not,
  from a float `sum()`; that is DC-T-09, fixed with `math.fsum`.

Reading the rendered prompts by hand before any live call found two wordings a
model could misread, both fixed before any run:

- a counter "would sign at X" did not say which side of X;
- "pre-stages only if" read as a promise the integrator could make.

## Probe v1 (2026-09-24): diagnostic, not a claim

`tools/run_risk_allocation_probe.py`, plan `runs/risk_allocation_probe_v1/`
(ignored, digest `6a1ddb17`):

- **Routes and sampling:** 32 cases × 2 routes, Gemini 3.8 Flash (Google AI
  Studio) and GLM 5.3 Flash (Parasail), temperature 1.0, reasoning effort low,
  at most 4,000 output tokens, one run.
- **Cost:** $0.29.
- **Dry run:** the reference, played through the same path, grades 0 regret in
  all 32 episodes.
- **GLM losses:** 11 of GLM's 32 episodes are typed missingness from the output
  cap (DC-O-08: 4,000 tokens of hidden reasoning, empty reply), so GLM's numbers
  are on survivors and are not compared with Gemini's.
- **Grader fix:** grading first crashed on a truncated reply (DC-T-10, fixed;
  the scoring sources are unchanged since the plan).

| | Gemini, client | Gemini, integrator | GLM, client | GLM, integrator |
|---|---|---|---|---|
| Valid episodes | 16/16 | 16/16 | 8/16 | 13/16 |
| Mean decision regret, $k | 115 | 144 | 189 | 316 |
| Best constant rule on the same worlds, $k | 203 (demand every protection) | 197 (concede every protection) | 215 | 192 |
| Signed the package it proposed first | 11 of 11 | 13 of 13 | 5 of 6 | 8 of 9 |
| Signed the efficient package | 1 of 11 | 3 of 13 | 1 of 6 | 0 of 9 |
| Price gap on signed contracts, $k | 18 above floor | 75 below bid | 87 above floor | 211 below bid |

What it shows: **both models negotiate the price, not the allocation.**

- **Gemini never changes the package.** In 32 of 32 episodes, it never
  proposed more than one package.
- **It starts the right way.** As the client, its first move gave up nothing
  in 12 of 16 episodes, usually by asking the price of the full warranty as the
  reference does. It then priced within $18k of the integrator's floor on
  average, reading the ask premium correctly.
- **It doesn't use what the answer revealed.** The answer identifies the
  integrator's type, which settles whether the incident and the deposit should
  move. Gemini signed the package it had asked about in every case, and it was
  the efficient contract once.
- **Where it lost most:** in `close_now` it opened with a price request in one
  world and an offer below the ask in the other, when the integrator was likely
  to break off, and lost both deals ($388k and $566k).

On these worlds it still beats every constant rule in aggregate in both seats,
because the rules either give up the price or never ask.

What it does not show: any ranking (16 worlds, one run, twins not
independent, GLM truncated), or whether the anchoring is a limit of reasoning
at low effort or of the task's arithmetic. Inferring the integrator's type from
one price means matching it against six candidate floors, and a model that does
not do that has priced exactly one package. Two follow-ups would separate
these, each a new probe identity:

- the same pack with reasoning left to the provider and an output cap sized
  from a smoke of reply length;
- a variant in which one round may ask the price of two packages, so the
  alternative's price is seen rather than inferred.

## Stated simplifications

- **Outcomes.** Expectations stand in for realised outcomes. The four risk
  events are independent, there is one delay cost per week, and liquidated
  damages are uncapped.
- **Pre-staging** is the integrator's best response to the contract, and the
  scripted client knows it.
- **Counterparts price honestly** by a declared rule. Strategic misreporting is
  a later cell.
- **The first move carries little.** In the client seat, "price an alternative"
  is usually best met by the full warranty. The second move, which contract to
  sign once the answer is in, carries most of the regret.
- **The source document** that prompted the case is a real firm's proposal and
  is not in the repository. Nothing here is drawn from its figures.

## Before a campaign

1. **Kernel lane.** A trusted-plugin row for
   `datacenter_risk_allocation_v1` / `datacenter_risk_allocation_environment_v1`
   in `src/aeread/shared_runner/registry.py`, reviewed by someone other than
   the author. The probe drives the plugin directly and does not need it.
2. **Scorer.** A shared-runner scorer over `grade`, with typed missingness for
   invalid episodes.
3. **Pilot.** A pilot on at least two routes, frozen as its own identity and
   sized from the probe's spread of regret.
