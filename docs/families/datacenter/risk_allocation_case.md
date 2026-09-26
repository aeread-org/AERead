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
| Gap analysis of the dev campaign (every move re-graded, Gemini against GLM per seat) | `risk_allocation_gap.py` (`--check`), bundle `evidence/datacenter_development/datacenter_risk_allocation_gap/` |

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

## Probe v2: two arms, each changing one thing from v1

Written before either arm ran. Probe v1 left one question open. Is the
anchoring a limit of reasoning at low effort, or is it the task itself, where
seeing any other package's price means inferring the counterpart's costs from
one number?

| Arm | Changes from v1 | Keeps from v1 |
|---|---|---|
| `risk_allocation_probe_v2_default_reasoning` | no reasoning setting declared; output limit per route from a smoke | pack `risk_allocation_dev_v1`, prompts, schema, routes, temperature |
| `risk_allocation_probe_v2_two_prices` | pack `risk_allocation_two_prices_dev_v1`: a price request may name an alternate package, the answer prices both, and either can be accepted; output limit per route from a smoke | low reasoning effort, the same 16 worlds and break-off draws, routes, temperature |

- **v1 is untouched.** The two-prices protocol is opt-in per case
  (`packages_per_request: 2`), so every one-price case and prompt is
  unchanged. Replaying all 64 v1 episodes through the new code reproduced every
  prompt (125), every final state and every grade byte for byte.
- **The yardstick is unchanged.** A second price is worth exactly $0 to the
  reference in all 32 cases, because the reference infers every package's price
  from one answer. Any improvement a model shows in the two-prices arm is
  therefore inference it did not do in v1.
- **Output limits come from a smoke.** The limits were sized by a stated rule,
  because v1's fixed limit truncated 11 of GLM's episodes (DC-O-08). The rule is
  twice the longest reply in a smoke of first-round prompts (reasoning
  included), rounded up to 1,000 tokens, and at least 4,000.
- **What would read which way.** If allocation improves only with a second price, the
  models can use a price they are shown but do not infer one. If it improves
  with default reasoning, low effort was the limit. If neither moves it, the
  anchoring is the models' negotiating habit.

### Results (2026-09-25): diagnostic, not a claim

Arms run:

| Identity | Route | Plan | Cost |
|---|---|---|---|
| `risk_allocation_probe_v2_default_reasoning` | Gemini | `1ba56a81` | $1.49 |
| `risk_allocation_probe_v2_default_reasoning_glm` | GLM | `701b9810` | $1.14 |
| `risk_allocation_probe_v2b_two_prices` | both | `3e85fdac` | $0.34 |

- **GLM's own identity.** GLM runs in a separate default-reasoning identity
  because its first smoke was censored. A 131,072-token smoke then found replies
  of 13,530 to 46,228 tokens, taking up to 923 s, and set its limit at 93,000.
- **The two-prices arm was run twice.** `v2b` supersedes
  `risk_allocation_probe_v2_two_prices`, whose prompt had lost v1's "price is
  null on accept" (DC-D-24).
- **Driver defects found and fixed on the way:**
  - DC-T-11: a connection the provider dropped was uncaught.
  - DC-T-12, twice: a provider error, first as an HTTP 200 body and then as
    `finish_reason: "error"`, was typed as the model's move.
  - DC-O-09: GLM's low-effort limit was sized from too small a smoke.

| Arm | Route | Valid | Regret, client / integrator, $k | Signed a package other than its first | Signed the efficient package | Zero-regret episodes |
|---|---|---|---|---|---|---|
| v1: low effort, one price | Gemini | 32/32 | 115 / 144 | 0 of 24 | 4 of 24 | 1 |
| v1 | GLM | 21/32 (DC-O-08) | not compared | | | |
| Default reasoning | Gemini | 32/32 | 63 / 62 | 0 of 26 | 7 of 26 | 5 |
| Default reasoning | GLM | 28/32 (4 provider failures) | 69 / 68 | 12 of 21 | 13 of 21 | 16 |
| Two prices (v2b), low effort | Gemini | 32/32 | 136 / 169 | 4 of 26 | 3 of 26 | 1 |
| Two prices (v2b), low effort | GLM | 31/32 | 120 / 203 | 3 of 21 | 9 of 21 | 1 |

**The question probe v1 left open has one answer per model:**

- **GLM, deliberating at length, does what the reference does.** With no
  reasoning setting it spends 13,000 to 46,000 tokens a move, and it does this:
  1. asks the price of one informative package;
  2. works out the integrator's costs from the answer;
  3. signs a different package at exactly its floor.

  Examples: it asked about fix_and_delay and signed "fix" at $10,602.8; it asked
  about the full package and signed the opening terms at $10,532.0. Both carry
  zero regret. It played 16 of 28 episodes without losing anything.
  - *Where it lost:* it signed readiness onto the integrator 4 times, and all 3
    of its valid `close_now` episodes broke off ($208k to $592k).
- **Gemini never revises, at any reasoning setting here.** Default reasoning
  (2,000 to 13,000 tokens a move) halves its regret through better opening
  terms and pace:
  - 6 different opening packages against 4 in v1;
  - its `close_now` losses fall from $477k to $156k.

  It still signed the package it opened with in 26 of 26 signings.
- **A shown second price is no substitute for the inference.**
  - *Gemini* used the alternate in all 32 episodes. It varied the warranty level
    28 times and the consequential clause 3 times. Where the alternate was the
    better quote (8 times) it signed the alternate twice, and its regret rose.
  - *GLM at low effort* with two prices switched package in 3 of 21 signings,
    against 12 of 21 when it deliberated with one price.

**Reading.** The anchoring measured in v1 is the behaviour of a model that does
not deliberate far enough to price the alternatives itself. Handing it the
prices does not fix that; long deliberation does, in the one model that
deliberates that long. That makes the case discriminating in the way it was
built for: the same worlds separate a price-haggler (Gemini at any setting
tried, GLM at low effort) from a negotiator that reallocates risk (GLM at
default reasoning), and fixed rules sit on the haggler's side.

Limits:

- 16 worlds and one run; twins are not independent.
- Counts behind the per-behaviour figures are 4 to 26.
- The two models differ in more than deliberation length, so "long deliberation
  causes revision" is a reading of one model, not a tested cause.
- GLM's default-reasoning arm takes hours of wall time: 13,000 to 51,000 tokens
  and up to 15 minutes a move.

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

## Dev campaign through the shared runner

`datacenter_risk_allocation_dev_campaign_v1` reruns the three probe arms as
sealed shared-runner receipts: 192 cells, $2.11, published at
`evidence/datacenter_development/datacenter_risk_allocation_dev_campaign_v1/`.
The trusted-plugin row is in draft PR #219 (kernel lane); the campaign ran from
this branch with that row applied. 169 episodes are valid; 21 are provider
exclusions (12 rate limits, 3 interrupted streams, 3 connection errors, 3
`finish_reason: error`, DC-O-10) and 2 replies were cut off by the output
limit. The exclusions concentrate in GLM at default reasoning, where only 18 of
32 cells are valid, so its integrator row rests on 5 worlds.

Paired against the low-effort arm on the same worlds, mean change in decision
regret ($ thousands), 95% interval from a world-clustered bootstrap (twins
clustered with their base world):

| Arm | Route | Seat | Worlds | Change | 95% interval |
|---|---|---|---|---|---|
| default reasoning | Gemini | client | 16 | −52 | −141 to −0 |
| default reasoning | Gemini | integrator | 16 | −105 | −208 to −33 |
| default reasoning | GLM | client | 13 | −112 | −164 to −52 |
| default reasoning | GLM | integrator | 5 | −186 | −233 to −136 |
| two prices | Gemini | client | 16 | +3 | −28 to +40 |
| two prices | Gemini | integrator | 14 | −33 | −114 to +32 |
| two prices | GLM | client | 10 | +56 | −18 to +117 |
| two prices | GLM | integrator | 15 | +27 | −38 to +89 |

Default reasoning lowers regret in every route and seat. A second price in
each round makes no detectable difference. The GLM integrator row is 5 worlds
and the Gemini client interval touches zero. This is a diagnostic dev
campaign: one run, 16 worlds per seat, no model ranking.

## Before a claim

1. **Kernel lane.** PR #219 merged after a non-author review.
2. **Retries.** GLM at default reasoning needs declared retries for rate limits
   and server errors, under a new campaign identity, before its missingness is
   small enough to read.
3. **Pilot.** A frozen pilot on held-out worlds, sized from this campaign's
   spread of regret.
