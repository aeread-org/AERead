# Appendices E–F: case details and quality control in detail (draft, AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. Material moved out of the main
[Case studies](paper_case_studies.md) and [Quality control](paper_qc_design.md) sections to keep
their length near the main-text budget of comparable environment papers.

---

## Appendix E. Case details

### E.1 Every reported check

**Table E.1. Every reported check in the four cases.**

| Case | Check | Kind | Output | Scope |
|---|---|---|---|---|
| Housing | tenant net per world against the reachable reference and the ceiling | value | dollars | outcome |
| Housing | holds signed that only a lemon's landlord would offer; ending on an uninspected listing | rule | count | path |
| Housing | model against model, paired by world | relative | dollars | outcome |
| Procurement | dollars given up against the best informed policy, action by action | value | dollars | path |
| Data center | joint value lost against the best of 600 agreements | value | dollars | outcome |
| Data center | each side's surplus, by counterpart | relative | dollars | outcome |
| Data center | signed below one's own walk-away point; disclosed a confidential item | rule | count | outcome; path |
| Refund | resolution (eligibility, remedy, amount, liability; workflow) against the reference | answer (declared as rule checks in the code) | share of fields matched | outcome |
| Refund | evidence complete before deciding; contract format; payment bound to the proposal (RF-D-05) | rule | pass or fail per leaf | path |

None of the four uses a rubric. Every score is computed from the sealed trajectory and replayed
without a model, which is the property we ask contributors to preserve where they can; a
rubric leaf is supported, but it is kept beside the computed ones and never folded into them.

### E.2 Pack construction

A pack is drawn from a generator and admitted by a rule. Where a case has a hidden draw, the
rule reads only what the deciding side could see, so admission cannot select on the draw.
Strata are named before any model plays, and held-out worlds come from a seed range disjoint
from development.

**Housing.** A seed is admitted when the tenant's favourite listing and a second listing are
worth more than their asks if sound. The seed keeps its own lemon draw, and the stratum
(favourite is a lemon, or sound) is read only after admission. Seeds are taken in order until
each quota is full: a main pack of 200 favourite-lemon and 60 favourite-sound worlds, and a
holdout of 30 and 10 from a disjoint range. The quotas oversample favourite-lemon worlds,
where the decision is hardest.

**Procurement.** Six kinds of world, four of each: paying is right on the money; paying is
right because a failed test would leave no time for the recorded supplier; a test is right
with the cheapest or with another newcomer, on a tight or a loose clock. A world is classified
from its listings with every newcomer assumed good, and the newcomers' types are drawn
afterwards on their own stream. The kinds are sampled evenly; drawn as they fall, a test of
the cheapest newcomer would be right in most worlds. A sibling pack of 18 worlds puts a
marketplace record on one component's listings, from which whom to verify can be read.

**Data center.** Eleven cells, each with its own outside-option situation and the playbooks it
allows, two worlds per cell and playbook: 58 worlds, 52 with a deal worth signing and 6 where no
agreement beats both outside options. The 58 development worlds come from the generator of the
case's predecessor; the declared test used 58 fresh worlds from the same generator, none equal
in content to a development world, and for its type-swap experiment wrote 29 of them twice,
identical except for the client's hidden risk charge. The admission rule implemented is the
predecessor's (a shortcut must lose by a margin on the playbook's menu); the agreement case's
own admission rules are designed but not built.

### E.3 What was run

**Table E.2. What was run.**

| Case | Worlds or cases | Strata | Subjects | Plays | Cost (list) | Status |
|---|---|---|---|---|---|---|
| Housing | 260 main + 40 holdout | favourite lemon (200 + 30), favourite sound (60 + 10); both landlord kinds in every world | Gemini 3.8 Flash, GLM 5.3 Flash, GPT-6 Luna | 1,800 cells and a 48-cell fill | about $8 | confirmatory |
| Housing, CLI agents | first 20 of the main pack | 10 and 10 | Opus 5.5, Sol 6.1 | 40 cells each | $4.72 | development |
| Procurement, pay or test | 24 | six kinds × four | Opus 5.5, Sol 6.1 | 96 cells over two briefs | $9.10 | development |
| Procurement, pay or test, flash models | 24 | six kinds × four | Gemini 3.8 Flash, GPT-6 Luna (GLM's route refused, P-O-06) | 24 cells each, second brief | $0.21 | development |
| Procurement, record pack | 18 | which listing the record favours | Opus 5.5, Sol 6.1 | one cell a world each | | development |
| Data center | 58 development + 58 fresh | deal or no deal; outside-option kind; counterpart style | Opus 5.5, Sol 6.1 | 2,456 negotiations, 2,417 valid | $119.13 | development; one declared test |
| Refund V2.5 | 180 distinct cases (seed 301) | eleven cohorts × four seats | deterministic reference profiles only | 816 trajectories | none | developmental release |
| Refund V2.1 | 6 cases | one policy seat | DeepSeek V4 Flash, Gemini 2.5 Flash Lite, GPT-5.6 Luna, Grok 4.3 | 480 cells (20 repeats of each case) | | descriptive |

Opus 5.5 ran through Claude Code and Sol 6.1 through the Codex CLI, without tools, at low
reasoning effort, one subprocess per action; neither CLI exposes a seed or temperature, and
both are recorded as unavailable rather than assumed. Refund V2.5 makes no paid model call: its
release qualifies the environment with deterministic profiles in every seat and replays every
trajectory, so it measures the environment's conformance, not a model; with every seat scripted, its 816
trajectories are 174 distinct action sequences (four payments cases share one reference
trajectory).

### E.4 Results beyond the main text

#### Housing

Over all 260 main-pack worlds the models fall short of the reachable reference by −81 [−97, −65]
(Gemini), −155 [−177, −134] (GLM) and −162 [−181, −142] (Luna) a world; they keep 60%, 27% and
22% of what the reference earns where the favourite is a lemon, against 97%, 83% and 98% where it
is sound. The 40-world holdout points the same way (Gemini−GLM +106 [+44, +168], Gemini−Luna +55
[+12, +98], GLM−Luna −40 [−106, +26]). All 1,800 published receipts replay to the same score.
Scripted tenants played offline on every cell give the floor: passing earns $0, never inspecting and signing any
hold the listing's value if sound would cover −$80 a world (it signs lemons), and inspecting when the stated odds make it
pay then signing $145; the models beat the first two by $130 to $292 a world. Sixteen GLM cells
contain invalid tenant actions, almost all offers on a listing already leased; the bundle did not
report them (HL-D-08) and no number moves. Thirty-six Gemini cells were refused when the provider account ran out of credit; they stay
missing in the declared bundle, and a separately identified fill moves nothing (+74, +81). Under
the HL-D-07 correction (a blind signing valued at the posterior given inspections and informative
replies) 21 (GLM), 33 (Luna) and 3 (Gemini) signings change value: Gemini leads by +60 [+39, +81]
and +67 [+49, +84] (Holm p < 10⁻⁶), GLM−Luna is +2 [−20, +24], and each model minus the reference
becomes −79, −142 and −144. The published bundle is not edited.

Two CLI agents played the first 20 worlds of the main pack (40 cells each). Sol 6.1 earns $313
[225, 402] and Opus 5.5 $291 [198, 383] against the reference's $331 on those worlds; the
difference, +23 [−19, +64], is not established. Both equal the reference where the favourite is
sound ($427) and fall short where it is a lemon ($200 and $155 against $235).

The reference is reachable, not best. An exact best informed tenant (Appendix C) earns $307 a
world on the main pack when it knows the two landlord kinds and how each prices; the v14 subjects
were not told that, so part of their gap to it is information rather than judgment. This tenant is
development work on an unmerged branch.

#### Procurement

Fixed rules, scored exactly over the 24 worlds: comparing each untested newcomer with paying, one
test ahead and keeping the recorded supplier reachable, gives up $0.06 a world; testing the best
odds once $45.7; always paying $75.2; testing the cheapest once $81.4; working up the price list
until one qualifies $146.1. On a first brief that did not state that a quote is final or that the
average is the criterion, the CLI agents gave up $12.2 [4.3, 23.6] (Sol) and $19.4 [6.0, 38.2]
(Opus); stating the two rules cut the loss by $11.1 [3.6, 22.3] and $14.0 [0.4, 33.5]. Under the
second brief the agents give up nothing in 20, 17, 8 and 7 of 24 worlds (Sol, Opus, Gemini, Luna);
both CLI agents pay without a test in all eight worlds where paying is right, and the first
newcomer each tests is the right one in 15 and 14 of 16. The record pack is saturated the same
way: Opus solves 18 of 18 worlds and Sol 16. Of the flash models Gemini never tested a newcomer
and Luna tested in two worlds; the two are indistinguishable (+$0.8 [−3.7, +6.3]), their loss is
$112.8 and $111.0 a world where a test is the best plan against $0.0 and $1.0 where paying is, and
all 48 cells are valid and replayed ($0.21). GLM 5.3 Flash did not play: its route changed price
before any call (P-O-06).

#### Data center

Which model sits in which seat changes the pair's total by +3 [−11, +18] ($ thousands a world);
Sol is ahead of Opus in 51 of 52 worlds in each seat head to head. Table E.3 gives every
counterpart; Appendix B gives each style's rule and parameters.

**Table E.3. Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

| Counterpart | As integrator | As client |
|---|---:|---:|
| The other model | +248 [+206, +290] | +251 [+209, +293] |
| Firm population | +17 [−10, +44] | +23 [−2, +48] |
| Soft | +86 [+56, +116] | +95 [+74, +115] |
| Price only | +112 [+75, +149] | +54 [+36, +71] |
| Collapse | +88 [+51, +126] | +148 [+117, +179] |
| Overreach | +32 [+10, +53] | +108 [+72, +144] |

Against the firm population both models earn about what signing its first offer earns (a stand-in
that does so earns 122 as integrator and 114 as client), by opposite routes: Opus signs its first offer, Sol bargains to the last move and loses deals.
Two copies of Sol split the value evenly (integrator minus client −6 [−94, +81]).

**Adversarial counterparts.**

- *Hardball scripts* (overreach, collapse, price only; 684 of 696 negotiations valid, $33.41).
  Overreach tests whether the model refuses a deal worse than walking away: as client, Opus
  signed below its own walk-away point in 23 of 52 worlds and earned −8 a world on average;
  Sol signed none and earned 100. Collapse tests patience: as client, Sol earned 187 and Opus
  40. Price only tests whether the model fixes the clauses itself: as integrator, Opus reached
  the best clause set in 0 of 52 worlds and lost 15 deals; Sol reached it in 10.
- *A probing counterpart* (20 worlds, each model in each seat against the prober and against a
  silent script; 158 of 160 valid, $7.92). Both sides' briefs carried a planted confidential name
  and figure that change no payoff, and the prober's notes asked for the other side's costs and
  for the confidential item. Neither model disclosed a confidential item in any negotiation. Asked
  for its own costs, Sol as integrator stated its pre-staging cost in 18 of 19 negotiations, and
  Opus in none of 40; nothing in the brief says a side's own costs are confidential, and no model
  stated a false cost. Asking changed no one's earnings measurably (−15 [−86, +57], +4 [−18,
  +25], +1 [−25, +26], +3 [−15, +22]). Unprompted, across 3,492 notes, no model stated its own
  private cost; in 114 negotiations a note called a price final or a floor, and in 112 of them the
  stated number was better for the speaker than its true limit.

**A declared test.** Looking back over these runs suggested two signals: Opus's counter-offer
price seemed to follow its private value, and Sol's clause requests seemed to follow its risk
charge. The claims, measures, exclusions and six primary predictions were committed before any
run, on the fresh worlds of Appendix E.2. Sol asks for 1.82 [1.23, 2.40] more protective clauses of six
under the high charge (supported, Holm p < 0.001), 1.58 [0.95, 2.22] more than Opus does;
fitting its clauses to its type is worth about +120k [+83k, +156k] of joint value a world to it.
Opus's price pass-through is −0.07 [−0.18, +0.05], not supported; the earlier 0.52 came from
counter-offers only, compared across worlds, and was withdrawn. Counterparts that read the first
offer gained nothing measurable from either model (+2k [−14k, +17k]; −8k [−42k, +26k]).

Of 2,456 negotiations, 2,417 are valid. Every failure is a CLI service error; the original
bundles keep them as missing, and 16 were played again under separate identities by the owner's
ruling.

### E.5 Failure classes: rules and full tables

**Table E.4. The shared classes.**

| Class | What happened |
|---|---|
| Information not acquired | acted without information worth acquiring: signed an uninspected listing whose quality nothing it knew had settled; paid the premium or awarded the recorded supplier where the best policy tested a newcomer; decided before a required fact |
| Information misread | had the information, or was shown it, and acted against it: signed a hold only a lemon's landlord offers, at a rent above a lemon's value; awarded a supplier its own test showed bad; stopped after one bad newcomer where another test was worth it; tested the wrong newcomer or in the wrong order; a decision the answer key contradicts |
| Worse terms | agreed to a worse deal than one available, with no protocol error: a verified listing worth less net of rent than the reference's; a worse award on a qualified supplier; a clause set worth less to the pair than the best one |
| Commitment error | signed what it should have refused or refused what it should have signed: no lease where the reference leased; deferred where an award or a test was worth more; no deal where one was available |
| Bargaining cost | moves that cost and could not gain: redline fees after the opening; inquiries, counter-offers and checks that can change nothing; inspection spend above the reference's on a lease of the same value |
| Procedure and format | an action the environment rejected or could not parse; a fact request the case rejects; a format the verifier rejects |
| Operational | a cell with no measurement; counted, never scored |

**Rules per case.** *Housing:* the unit is the cell (one world, one landlord kind), the shortfall is
the reachable reference's net minus the tenant's at the published measure, and the rules apply in
the order procedure, misread, not acquired, commitment, worse terms, bargaining. A known lemon
signed at a rent its lemon value covers is judged on terms, as the reference does the same.
Revealed-lemon signings count as misread although the v14 prompt did not state how landlords
price; counted as not acquired instead, GLM's not-acquired loss would be about $102. *Procurement:*
the unit is the action, and each action's loss against the best policy (which sums to the decision
loss) goes to a class by what the action did; a request to the recorded supplier counts as not
acquired only when the episode never tests a newcomer, and as misread otherwise. *Data center:* the
unit is each part of a negotiation's grade: no deal is a commitment error (labelled by the side that
walked), a worse clause set is worse terms, and redline fees are bargaining cost; signing below
one's own walk-away point is counted separately because it moves value between the sides and never
appears in joint value. *Refund:* the published gap decomposition's parts map onto the classes
(deciding before a required fact to not acquired, a wrong decision to misread, re-asked or unknown
facts and the null-method format to procedure).

**Table E.5. Housing and Procurement, every subject ($ per world; Housing with the HL-D-07 measure in brackets).**

| Class | Housing Gemini | Housing GLM | Housing Luna | Proc. Sol | Proc. Opus | Proc. Gemini | Proc. Luna |
|---|---:|---:|---:|---:|---:|---:|---:|
| Information not acquired | 6.6 (3.9) | 28.1 (9.2) | 32.4 (10.1) | 0 | 2.6 | 75.2 | 71.8 |
| Information misread | 11.2 | 73.6 | 86.4 | 1.0 | 2.8 | 0 | 1.9 |
| Worse terms | 54.6 (55.1) | 36.1 (42.2) | 39.1 (44.0) | 0 | 0 | 0 | 0.7 |
| Commitment error | 8.5 | 12.4 | 2.9 | 0 | 0 | 0 | 0 |
| Bargaining cost | 0.2 | −0.2 | 1.0 | 0 | 0 | 0 | 0 |
| Procedure and format | 0 | 5.1 | 0 | 0 | 0 | 0 | 0 |
| Total | 81.0 (78.9) | 155.1 (142.3) | 161.6 (144.3) | 1.0 | 5.4 | 75.2 | 74.4 |

Thirty Gemini cells of the main pack are operational missingness and are not scored.

**Table E.6. Data center ($k joint value lost per deal world) and Refund (points of cells unresolved).**

| Class | DC Sol int. × Opus | DC Opus int. × Sol | DC Sol × firm | DC Opus × firm | Refund DeepSeek | Refund Gemini 2.5 FL | Refund GPT-5.6 Luna | Refund Grok |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Information not acquired | — | — | — | — | 44.2 | 0 | 15.0 | 29.2 |
| Information misread | — | — | — | — | 0 | 0 | 0 | 0.8 |
| Worse terms | 35.4 | 12.2 | 9.1 | 4.8 | 0 | 0 | 0 | 0 |
| Commitment error | 0 | 0 | 32.0 | 6.9 | — | — | — | — |
| Bargaining cost | 46.2 | 66.3 | 80.2 | 29.8 | — | — | — | — |
| Procedure and format | 0 | 0 | 0 | 0 | 5.8 | 98.3 | 5.8 | 17.5 |
| Total | 81.5 | 78.6 | 121.3 | 41.5 | 50.0 | 98.3 | 20.8 | 47.5 |

Against the firm script, 7 of Sol's 8 lost deals were the script walking from Sol's last offer.
Signing below one's own walk-away point, not in the table: Opus as client 12 of 52 worlds against Sol
(it proposed the losing terms itself in 4) and 2 against the firm script; Sol as client 1 against the
firm script; neither as integrator.

### E.6 Two frontier agents across three cases

**Table E.7. Opus 5.5 and Sol 6.1 on the three cases both played.**

| Case (worlds) | Measure | Opus 5.5 | Sol 6.1 | Sol relative to Opus | Reference |
|---|---|---:|---:|---:|---|
| Housing (20) | tenant net per world | 291 [198, 383] | 313 [225, 402] | +23 [−19, +64] | scripted reference 331 |
| Housing, favourite a lemon (10) | tenant net per world | 155 | 200 | not tested | scripted reference 235 |
| Procurement pay-or-test (24) | given up per world | 5.4 [1.2, 10.6] | 1.0 [0.2, 2.1] | 4.4 [0.6, 9.0] less given up | best policy gives up 0 |
| Procurement, record pack (18) | worlds solved | 18 | 16 | regret −20 [−48, +7] (Opus lower) | informed policy 18 |
| Data center, firm population (52) | earns, integrator / client ($k) | 122 / 107 | 139 / 130 | +17 [−10, +44] / +23 [−2, +48] | first-offer stand-in 122 / 114 |
| Data center, head to head (52) | earns, integrator / client ($k) | 60 / 25 | 308 / 276 | +248 / +251 | |

## Appendix F. Quality control in detail

This appendix describes only checks that were built and applied to the four cases. Two caveats
apply throughout. The QC profiles of the four current designs and the reference-run tests were
written on 2026-10-13, after the runs they describe. And rules of the QC standard that were not
applied to these cases are not described here.

### F.1 Profiles and gates

The QC standard defines six gates and the rule that a changed bound input reopens them; a test on
the main branch rejects a registered family without a profile. Each of the four current designs
now has a section in its family's profile with a typed status and a blocker per gate (Table F.1),
and none passes Gates 1 to 5: Housing v14 is `partial` throughout; Procurement's pay-or-test pack
fails Gates 1 and 3; the data-center agreement fails Gate 1, because its packs were not admitted
by its own rules and its hidden type is tied to the pack cell; Refund fails Gate 3 for want of a
lower control. The identity rule was applied: Housing's 36 refused cells ran later under their own
identity, and Procurement's corrected schema ran under new identities.

**Table F.1. Benchmark QC gates.**

| Gate | Question | Stops when | In the four cases |
|---|---|---|---|
| 0. Profile | Is there a place to record each gate's verdict? | the family has no QC profile | an earlier Procurement design's construct check found a public-price rule beating the model by $28.50 a world; with no profile, the verdict was read as a campaign finding and lost. The four current profiles were written after their runs |
| 1. Task distribution | Are the worlds valid, distinct, split and informative? | an unverified bound, duplicates across clusters, development and holdout overlap, no measured headroom | Housing v14 admits a seed on the tenant's own structure and reads quality afterwards, with a holdout from a disjoint seed range; pay-or-test fails: a rule reading only public information solves 23 of 24 worlds |
| 2. Environment and verifier | Do actions change the intended state, and is every score rebuilt from sealed evidence? | invalid actions mutate state, an oracle disagrees, hidden state leaks, replay differs | 1,800 of 1,800 Housing v14 receipts replay from sealed events with no provider call |
| 3. Construct and baselines | Does a better-informed policy do better, and do shortcuts lose? | stronger and weaker policies indistinguishable, a shortcut drives the score | pay-or-test fails: Procurement's fixed rules give up $45.7 to $146.1 a world, but a one-step comparison reaches the best policy to within $0.06 |
| 4. Attribution and controls | Does the result support the attribution it claims? | an undeclared control changes, the matrix is incomplete, the block cannot carry the claim | the three v14 identities differ in model and route and also in reasoning tier, sampling and cost ceiling, a declared choice the contract did not state (HL-J-12); data-center claims name their counterparts |
| 5. Confirmatory reliability and publication | Was the comparison sized, frozen and executed without tuning on outcomes? | incomplete pilot, a frozen control changed, selective missingness, a guardrail no behaviour can fail | Housing v14's analysis was declared before any cell and 36 refused cells stayed missing, but no sizing record was sealed; no other case reached this gate |

### F.2 Checks applied to the four cases

**Table F.2. What each kind of verifier must be shown to do, and how the four cases show it.**

| Kind | Must be shown | How it is shown in the four cases |
|---|---|---|
| Answer | the key is correct and complete for every admitted case | Refund: admission requires the policy's public compiler to reproduce the hand-written reference resolution on every case |
| Rule | every rule is stated to the subject, and each check fails on a counterexample | Procurement tests most of the rules its brief states against the environment; the agreement case tests its stated walk-away cost; two checks (the agreement's oracle grade and Housing's ceiling) have mutation tests; a rule left unstated or a schema that disagrees with its parser is a defect (P-D-19, P-D-23, RF-D-03) |
| Value | the reference agrees with the environment, and a simple rule does not already match it | each reference is played on every world (below); Procurement computed its one-step rule before play, and that rule matches its best policy |
| Relative | the counterparts are named and the gap is reported per counterpart | the data-center counterpart table (Table E.3) |
| Rubric | the rater agrees with people and resists gaming | not used |

- **Regeneration.** In all four cases a test reproduces every committed pack byte for byte from
  its generator and seeds.
- **Reference run on every world.** Tests added after the runs play each reference through the
  real environment and verifier with no model: the Housing reference and a full-information tenant
  on all 600 v14 cells, reproducing the published per-cell values and reaching the ceiling in
  every cell (offline, against the same functions that wrote the bundle); Procurement's best policy
  equals the environment's average over the 27 type profiles in all 24 worlds; the data-center
  oracle pair loses nothing in all 116 worlds of both packs, against an optimum the test computes
  independently; Refund's release requires the reference to take full credit on every case.
- **Replay.** The 1,800 published Housing v14 receipts replay from their sealed events with no
  provider call; the agreement driver replayed every receipt before counting it; the procurement
  panels replay to their recorded margins; Refund's 816 provider-free trajectories replay, though
  they are unpublished and only 174 are distinct.
- **Visibility.** Named hidden fields are tested absent from the observations in Housing,
  Procurement and Refund; the agreement case has no such test.
- **Paired plans.** A Housing test rebuilds the six v14 plans that ran, matches their ids, and
  asserts that they differ only in model and route, reasoning tier, sampling and cost ceiling,
  the differences HL-J-12 recorded; Refund tests that a plan has a single subject seat; the
  agreement case tests its packs.
- **Golden plays.** For Housing, tests added after the runs play five kinds of tenant on v14
  worlds through the real market: a good lease with its accounting checked by hand, a poor blind
  lemon signing, invalid and unauthorised actions (the market ends exactly as if the tenant had
  passed), malformed output through the kernel (typed as an error and scored as a pass, never as
  $0), and a world whose ceiling is $0; each has a counterexample that makes it fail.

### F.3 Reading trajectories

Housing v14 (60 of its 1,800 attempts step by step) and the agreement's development runs open in
the Examiner, a trajectory viewer that shows each step as the seat saw it beside the state it
could not see, with a QC checklist per run; on 2026-10-13 that checklist flagged 670 lines across
144 bundles, of which 58 needed a reviewer. Walking a single case by hand found RF-D-05 in Refund;
an earlier data-center design was traced the same way on 2026-09-14.

### F.4 Adversarial checks applied

- **Trivial agents** are reported beside the subjects: signing the draft unchanged recovers 14% of
  the value available in the agreement case; always paying the premium gives up $75.2 a world in
  Procurement; in Housing, scored after the runs, passing earns $0, signing without
  inspecting −$80 and an inspect-then-sign rule $145 a world, a rule two of the three models do not
  beat (Table 5.2).
- **Fixed rules** are scored exactly against Procurement's best policy; the one-step rule's $0.06
  is the finding that fails Gates 1 and 3.
- **Brief audits** found instructions that decided outcomes in Procurement (P-D-15, P-D-19, P-D-21)
  and a schema that contradicts its verifier in Refund (RF-D-03).
- **A placebo outcome** was run after the agreement's look-back price signal: the same regression
  on the opening price of a scripted integrator that is never told the hidden type gave 0.38 [0.23,
  0.52] where the answer must be 0, which exposed DC-D-33; a random relabelling of types had not
  caught it.

### F.5 Statistical practice applied

The world is the unit of uncertainty, paired across conditions. On the agreement runs, treating
plays as independent made intervals 1.47 to 1.65 times too narrow, and more worlds beat more
repeats: a $50k gap needs 83 to 91 negotiations an arm at one play a world against 159 to 162 at
three. Counterparts are named and reported per type: in the agreement case the counterpart
accounts for 25% to 33% of the spread in what a model earns. Two analyses were declared before
their runs: Housing v14's, and the agreement's signalling test. A harness setting was tested
rather than assumed: asking the CLIs for reasoning summaries changed nothing detectable in Housing
(Opus +17 [−28, +62], Sol +3.5 [−46, +53]; five selected worlds, 120 episodes, the summary-off
plays always run first).

### F.6 Failure records and review

Every failure is written into the incident log when it happens, in four categories (design,
operational, tooling, judgment), and rows are never deleted (Table F.3). Evidence
review by verification (digests, replay, prohibited-text scan) was done for the Housing v14
bundle. The agreement family's registry change has had no review by anyone other than its author,
and eight earlier kernel fixes merged without one under a one-time waiver (RN-O-01).

**Table F.3. Judgment-log rows about each case and its predecessors, by category (all branches, 2026-10-13).**

| Case (row prefix) | Design | Operational | Tooling | Judgment | Total |
|---|---:|---:|---:|---:|---:|
| Housing lemons and price line (HL) | 9 | 21 | 8 | 12 | 50 |
| Procurement (P) | 23 | 6 | 10 | 4 | 43 |
| Data center (DC) | 33 | 21 | 20 | 8 | 82 |
| Refund (RF, RV25) | 8 | 0 | 7 | 1 | 16 |

### F.7 What quality control found

**Table F.4. Defects found by quality control in these cases and their predecessors, with the level at which each was visible.**

| Row | What was wrong | Visible in one world? | How it was found | What changed |
|---|---|---|---|---|
| HL-D-04 | A seat-number tie-break and scripted rivals' $1 overbid decided who signed a sound listing | no: a pattern across seats | comparing signing rates by seat | one deciding tenant against declared outside demand |
| HL-D-01 | The scripted landlord's accept-or-counter reply was a free, near-perfect quality test beside a $25 inspection | no: needs the cost distribution | validity audit before a second model ran | pooled landlord; the revealing landlord kept as a declared arm |
| HL-D-03 | Admission made a favourite's lemon rate depend on its popularity (0.29 among admitted worlds where six tenants shared it, about half before admission) | no: a property of the admitted set | comparing pre- and post-admission rates | admit on the tenant's structure, read quality afterwards |
| HL-D-05 | The rule the tenant was told sat outside the sealed request | yes, by reading the sealed bytes | known at build, logged before any run | the rules sealed in the prompt, the tenant's history in the observation |
| HL-J-02 | A gap decomposition's "luck" part was not luck: uncontested blind bets were lemons 11 of 15 times, contested 1 of 15 | no: a split by rival behaviour | testing the stated odds by model (p = 0.006) | blind signings scored at their expected value given what the tenant saw |
| P (Gate 0, an earlier design) | A rule reading only the displayed price beat the qualified model by $28.50 a world | no: a baseline comparison | the construct check | construct gate recorded `failed`; Gate 0 made a profile mandatory |
| P-D-15 | The prompt pointed every subject at the cheapest listing, right in half the worlds and wrong in the other half | no: needs the pack's construction | asking whether the hard half was valid or a trick | a neutral prompt and a new pack |
| P-D-19, P-D-21 | The brief did not say a quote is final or that the buyer is judged on its average | no: a pattern in loss by action | listing each loss by the action that caused it | a second brief; loss fell from $12.2 to $1.0 and $19.4 to $5.4 a world |
| P-D-17 | Under sample noise the pre-award check reveals the true yield for one free action | yes, by reading the tool's code | designing a sample-again decision | open; 1 of 260 noisy cells used it, no published number moves |
| DC-D-27 (predecessor case) | Walking away came within $11k to $46k of the right contract, and asking for every protection within $26k to $88k | no: a strategy-class simulation | simulating shortcut policies on the pack | before any freeze: each named shortcut must cost $75k more than the best contract, and a deal must beat the better outside option by $150k |
| DC-D-29 (predecessor case) | At low effort the case could not separate two models: about 83% of the per-world gap was seed noise | no: needs paired seeds | variance split of the paired gap | one seed per world and more worlds; a redesign of the case |
| DC-D-32 | The scripted style hashed the whole world, including the client's hidden charge | no: needs two copies of a world | a test that the opening is identical for both types failed | the declared test uses a fixed style |
| DC-D-33 | The hidden type was fixed by pack cell and moved with public quantities | no | a placebo outcome, after the look-back (Appendix F.4) | packs that play each world under each type |
| HL-D-07 | The primary measure conditions on the landlord's reply only below the sound floor; a reply that proves a listing sound is still scored at the stated odds | yes, by reading the measure's code | writing the formal appendix of this paper | recomputed from the sealed run roots: 57 signings move, no declared verdict changes, Gemini's leads shrink by $10 and $13 in the v14 cells; an erratum is owed |
| RF-D-01 | The 120-cell panel was six cases: the world seed changed only the case id, and the policy seat ran at temperature 0 | no: needs the seeds compared | rebuilding the cases and reading the reference run's resolutions | the case is the unit of analysis; V2.5 varies declared conditions by seed |
| RF-D-03 | A correct denial written with method `null` failed: the prompt says "none", the schema allows null, the verifier compares strings | yes, by reading one proposal against the verifier | building the gap decomposition | recorded; reported as format, not outcome |
| RF-T-01 | The human-QC approval was minted by the runner from two status-only stubs, so it bound whatever the runner produced | yes, by reading the runner's code | the Refund audit | V2.5 names a reviewer, but the runner still binds the approval to its own output (RF-D-06, open) |
| RF-D-05 | Refund's payment leaf checks that payments executed what the proposal asked, so a proposal with an aliased mutation moves no money where the reference refunds $185.22 and still scores 1.0 | yes, by tracing one case | writing the formal appendix of this paper | open; report the leaf as binding and add a check against the reference |
| HL-D-09 | The v14 receipts' own scores total all six tenant seats against baselines from a market without outside demand, so they are not the deciding tenant's | yes, by reading the receipts | building the seat-0 controls | open; the published primary is computed separately and is unaffected; a seat-0 scorer needs a module outside the hashed runner |
| P-D-23 | The pay-or-test action schema let `message` be null while the parser requires it, so a model's first action could end its episode on format | yes, in one gate cell | the flash-model gate | the schema requires every field the parser needs, under new identities |

Twelve of the twenty were invisible in any single world; the eight visible ones were found by
reading code or sealed bytes, by tracing a case, or in a single gate cell. Five are still open
(P-D-17, HL-D-07, HL-D-09, RF-D-05, RF-T-01).

### F.8 Assessment against the Agentic Benchmark Checklist

The four cases are assessed item by item against the checklist [ABC]; the outcome-validity item
that applies is the one for a quality measure, since no case is scored by string matching, unit
tests or a judge model.

**Table F.5. The four cases against the checklist.**

| Item | Status | Evidence |
|---|---|---|
| T.1 Tool versions specified | partly | routes, prompts, schemas and implementation digests are sealed in each plan; the two CLI agents expose no seed or temperature |
| T.2 Required APIs accessible | partly | provider outages lost cells (36 Housing cells to an empty account, 39 data-center negotiations to CLI errors), each recorded as typed missingness |
| T.3 Terminates or handles API errors | partly | Housing v14 and the procurement flash panels declare retries and stop after three consecutive failed cells; the agreement driver has no such halt; a failure is never scored as zero |
| T.4 Residual state cleared between runs | met | each cell is a fresh episode from a sealed plan; the CLI agents run one ephemeral subprocess per action |
| T.5 Agent isolated from ground truth | partly | named hidden fields are tested absent from observations in Housing, Procurement and Refund, not in the agreement case; one leak was fixed (HL-D-01) and one is open in noisy-sample packs (P-D-17) |
| T.6 Setup does not change over time | met | the environments are deterministic and sealed; hosted model routes are pinned and snapshotted |
| T.7 Ground truth verified | partly | each reference is played on every admitted world through the environment and reaches its declared result, by tests added after the runs (Appendix F.2) |
| T.8 Each task verified solvable | met | the reference plays every admitted world, and admission requires that the decision matters |
| T.9 Oracle solver | partly | exact for Procurement; an independent reference resolution and a scripted policy that resolves every case for Refund; a reachable reference for Housing, with an exact best informed tenant in development; a full-information stand-in for Data center, whose per-turn best informed policy is not built |
| T.10 Free of exploitable shortcuts | partly | trivial agents, exact fixed-rule scores and brief audits (Appendix F.4); twenty defects found (Table F.4); a one-step rule reaches Procurement's best policy; a wrong refund can still pass Refund's payment leaf (RF-D-05) |
| O.i.1 Quality metric resists exploitation | met | dollars against an exact or reachable reference; blind bets priced at expected value; guarded metrics must be falsifiable |
| R.1 Open source | partly | the environments, runner and evidence are public; the trajectory viewer is private |
| R.2 Open evaluation harness | met | the shared runner is in the public repository |
| R.3 Contamination prevented | met | generated worlds; holdouts from a disjoint seed range; fresh worlds for declared tests |
| R.4 Plans to update | partly | packs regenerate from new seeds; no refresh schedule is stated |
| R.5 Capability related to construct | met | each case states the decision it measures (Table 5.1) |
| R.6 Evaluation subject stated | met | the subject is a profile (model, harness, prompt, tools, reasoning, retries); CLI agents are named with their harness |
| R.7 Steps to prevent, find and correct flaws | partly | the gates and the incident log (Appendix F.1, F.6) |
| R.8 Qualitative discussion of unavoidable flaws | met | the end of §5.2 |
| R.9 Quantitative analysis of flaw impact | partly | measured for the brief change, the refused cells and missingness bounds; not for every open row |
| R.10 Statistical significance | met | paired world-level intervals; Holm correction across declared primaries |
| R.11 Guidance on interpreting flawed results | met | every result is labelled confirmatory, declared or development |
| R.12 Non-AI baselines | partly | scripted policies in every case; no human |
| R.13 Trivial agents | partly | always paying (Procurement), signing the draft (Data center) and passing, signing anything and inspect-then-sign (Housing, scored after the runs) are reported; Refund V2.1 has no lower anchor (RF-D-04) |

## Appendix G. Artifacts

Everything the numbers in Sections 5 and 6 rest on is in the public AERead repository or is
named here when it is not.

- **Code and cases.** The shared runner and the case families, with each case's generator,
  reference, verifiers, packs and tests, on the branches `codex/housing-lemons-outside-demand`
  (Housing), `codex/procurement-pay-or-test` (Procurement), `codex/datacenter-agreement` (Data
  center) and `codex/refund-v25-shared-runner` (Refund).
- **Evidence.** Sealed, digest-bound bundles under `evidence/`: the Housing v14 confirmatory and
  its declared fill, the data-center agreement bundles, and the Refund V2.1 bundles with their gap
  decomposition. The Procurement pay-or-test panels are development runs kept as sealed run roots
  and are not yet published as bundles.
- **Quality control.** Each family's QC profile (`docs/families/<family>/qc.md`) and the incident
  log (`docs/operations/incident_log.md`) on the branches above; the reference-run tests named in
  §6.
- **Sources for every number.** The tables at the end of the two section files
  (`docs/research/paper_case_studies.md`, `docs/research/paper_qc_design.md`) map each table and
  claim to its bundle, run root, commit or incident row.
- **Not in the repository.** The trajectory viewer (Examiner) is private; the one-page result
  sheets and the HL-D-07 recomputation script are kept with the authors and available on request.
