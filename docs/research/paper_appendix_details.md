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

### E.4 Results in full

#### Housing

The three flash models were run under one analysis declared before any cell: three model pairs
corrected together (Holm), each model against the reference, a $50 minimum meaningful
difference, the holdout reported apart.

**Table E.3. Housing v14, main pack (260 worlds); dollars per world, 95% intervals paired by world.**

| | Gemini 3.8 Flash | GLM 5.3 Flash | GPT-6 Luna |
|---|---:|---:|---:|
| Tenant net per world | +211 [+188, +233] | +137 [+111, +162] | +130 [+104, +156] |
| Minus the reference, all worlds | −81 [−97, −65] | −155 [−177, −134] | −162 [−181, −142] |
| Minus the reference, favourite is a lemon (200) | −102 [−122, −82] | −179 [−203, −154] | −207 [−229, −186] |
| Minus the reference, favourite is sound (60) | −13 [−18, −8] | −76 [−116, −36] | −9 [−16, −2] |

Gemini leads GLM by +70 [+48, +92] and Luna by +80 [+62, +99] (Holm p < 10⁻⁸); GLM and Luna
differ by +7 [−16, +29], inside the $50 band. The 40-world holdout points the same way (+106
[+44, +168], +55 [+12, +98], −40 [−106, +26]). All 1,800 published receipts replay to the same
score. Thirty-six Gemini cells were refused when the provider account ran out of credit; they
stay missing in the declared bundle, and a separately identified fill run moves nothing (+74,
+81). A reading of the measure's code for this paper found that a blind signing of a listing the
leaky landlord's reply had proved sound is valued at the stated odds rather than as sound
(HL-D-07). Recomputed from the sealed run roots with every blind signing valued at the
posterior given inspections and informative replies, the correction moves 21 (GLM), 33 (Luna)
and 3 (Gemini) signings and no declared verdict: Gemini leads GLM by +60 [+38, +81] and Luna by
+67 [+49, +84] (Holm p < 10⁻⁶), still past the $50 band, though the lower bounds now fall below
it; GLM and Luna differ by +2 [−20, +24]; each model minus the reference becomes −79, −142 and
−144. The published bundle is not edited; an erratum is owed once the errata layer lands.

None of the three reaches the reference, and almost the whole shortfall sits in the
favourite-lemon stratum, where the models keep 60%, 27% and 22% of what the reference earns,
against 97%, 83% and 98% where the favourite is sound. A pooled score would report a gap of $81
to $162 and hide that, on the quarter of the pack where the favourite is sound, two of the
three models are within $13 of the reference.

Two CLI agents played the first 20 worlds of the main pack (40 cells each). Sol 6.1 earns $313
[225, 402] and Opus 5.5 $291 [198, 383] against the reference's $331 on those worlds; the
difference, +23 [−19, +64], is not established. Both equal the reference where the favourite is
sound ($427) and fall short where it is a lemon ($200 and $155 against $235).

The reference is reachable, not best. An exact best informed tenant (a belief over which
listings are lemons and which landlord kind it faces, solved by backward induction, Appendix C)
earns $307 a world on the main pack when it knows the two landlord kinds and how each prices.
The v14 subjects were not told that, so part of their gap to it is information rather than
judgment. This tenant is development work on an unmerged branch.

#### Procurement

**Table E.4. Procurement pay-or-test, 24 worlds, one play a world; dollars given up per world.**

| | Sol 6.1 (Codex CLI) | Opus 5.5 (Claude Code) | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| First brief | 12.2 [4.3, 23.6] | 19.4 [6.0, 38.2] | | |
| Brief stating that a quote is final and that the buyer is judged on its average | 1.0 [0.2, 2.1] | 5.4 [1.2, 10.6] | 75.2 [48.7, 101.4] | 74.4 [46.7, 102.7] |
| Share of the best policy's value (second brief) | 99.8% | 98.8% | 83.3% | 83.5% |
| Worlds with nothing given up (second brief) | 20 of 24 | 17 of 24 | 8 of 24 | 7 of 24 |

Fixed rules, scored exactly over the same 24 worlds: comparing each untested newcomer with
paying, one test ahead and keeping the recorded supplier reachable, gives up $0.06 a world;
testing the best odds once $45.7; always paying $75.2; testing the cheapest once $81.4; working
up the price list until one qualifies $146.1.

Opus gives up $4.4 [0.6, 9.0] more than Sol under the second brief. Both pay without a test in
all eight worlds where paying is right, on both briefs, and the first newcomer each tests is the
right one in 15 (Sol) and 14 (Opus) of 16 worlds. All 96 cells completed and replay to their
recorded margins. The case is at its ceiling for these two subjects: its best policy is a
one-step comparison, and both make it. Stating two rules in the brief cut the loss by $11.1
[3.6, 22.3] and $14.0 [0.4, 33.5] (Appendix E.5). The record pack is saturated the same way: Opus solves
18 worlds and Sol 16.

Two flash-tier models played the same 24 worlds under the second brief, through the same
environment and an OpenRouter route (all 48 cells valid and replayed, $0.21 in all). They give up
about $75 a world: Gemini $75.2 [48.7, 101.4], exactly what always paying the premium gives up,
because it never tested a newcomer; Luna $74.4 [46.7, 102.7], having tested in two worlds. The two
are indistinguishable (+$0.8 [−3.7, +6.3]). Almost the whole loss is in the 16 worlds where a test
is the best plan ($112.8 and $111.0 a world there, against $0.0 and $1.0 where paying is). GLM 5.3
Flash did not play: its route changed price before any call (P-O-06). So the case separates the
flash tier from the frontier but not frontier agents from each other. Because the reference is
exact per action, both statements are dollars given up rather than pass rates.

#### Data center

Head to head, the pair recovers about 80% of the value available, against 14% for signing the
draft unchanged, and which model sits in which seat changes the total by +3 [−11, +18] ($
thousands a world). Who keeps it differs sharply: Sol earns about 250 more than Opus in the same
seat and is ahead in 51 of 52 worlds in each seat. Each model was then played in each seat
against scripted negotiators (Appendix B gives the rule and every style's parameters).

**Table E.5. Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

| Counterpart | What it does | As integrator | As client |
|---|---|---:|---:|
| The other model | | +248 [+206, +290] | +251 [+209, +293] |
| Firm population | each world and seat draws an opening ask (60% to 90% of the deal's value), a final ask, a least acceptable share (10% to 35%) and how closely it matches concessions | +17 [−10, +44] | +23 [−2, +48] |
| Soft | concedes on a clock from 55% to 25% of the deal's value, whatever the model does | +86 [+56, +116] | +95 [+74, +115] |
| Price only | never changes a clause, haggles the price | +112 [+75, +149] | +54 [+36, +71] |
| Collapse | holds a 90% ask until its last proposal, then asks 30% | +88 [+51, +126] | +148 [+117, +179] |
| Overreach | opens with offers worse than walking away for every type of the model's side, then comes down | +32 [+10, +53] | +108 [+72, +144] |

The direction is the same against every counterpart; the size runs from not distinguishable to
250, so a result against one counterpart could have been any number in that range. Against the
firm population both models earn about what signing its first offer earns (a stand-in that does
so earns 122 as integrator and 114 as client), by the opposite routes described in Appendix E.5. At equal
skill the seat is worth nothing: two copies of Sol split the value evenly (integrator minus
client −6 [−94, +81]).

**Adversarial counterparts.** Two kinds of counterpart try to exploit the model rather than
trade with it.

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

### E.5 Error analysis

The losses concentrate in a few behaviours, each counted from the sealed trajectories.

**Housing: signing what the reply has revealed, and ending unverified.** GLM and Luna sign most
holds that only a lemon's landlord would offer (54 of 73 and 80 of 88; Gemini 7 of 38). The
prompt says a counteroffer can carry information about quality but not how landlords price, so
reading a reply that way takes an inference. The models end on a listing they inspected in 75%
(Gemini), 66% (GLM) and 56% (Luna) of the cells where they sign. Each CLI agent still signs four
uninspected holds whose rent reveals a lemon.

**Procurement: moves the brief did not rule out.** On the first brief Sol made 43 counter-offers,
which cannot succeed in this pack, at $7.3 of its $12.2 a world. Opus made cautious moves, paying
without a test and stopping after one bad newcomer where another test paid, which are defensible
for a buyer who weighs a bad outcome above the average; the first brief never said the average
was the criterion. Under the second brief neither countered, and Opus still paid without a test
in 2 test worlds and stopped early in 2. The flash models' loss is a different behaviour: they
pay the premium almost everywhere, Gemini in every world, so they give up the value of the test
in every world where a newcomer was worth testing.

**Data center: signing below the walk-away point, and pressing past the deal.** As client Opus
signed below its own walk-away point in 12 of 52 worlds against Sol, 23 of 52 against the
overreaching script, and, against a copy of itself, made the losing offer unprompted in 5 of 20.
Every case is a world where the client's better outside option is managing the deployment
itself, which the brief gave as ingredients rather than as a number; one added line stating that
number cut such signatures from 15 of 60 plays to 1 of 60. Against the firm population Opus signs
the first offer in 36 of 52 worlds as client, while Sol bargains to the last move, pays for
redlines and loses seven deals to the script's floor.

**Table E.6. Opus 5.5 and Sol 6.1 on the three cases both played.**

| Case (worlds) | Measure | Opus 5.5 | Sol 6.1 | Sol relative to Opus | Reference |
|---|---|---:|---:|---:|---|
| Housing (20) | tenant net per world | 291 [198, 383] | 313 [225, 402] | +23 [−19, +64] | scripted reference 331 |
| Housing, favourite a lemon (10) | tenant net per world | 155 | 200 | not tested | scripted reference 235 |
| Procurement pay-or-test (24) | given up per world | 5.4 [1.2, 10.6] | 1.0 [0.2, 2.1] | 4.4 [0.6, 9.0] less given up | best policy gives up 0 |
| Procurement, record pack (18) | worlds solved | 18 | 16 | regret −20 [−48, +7] (Opus lower) | informed policy 18 |
| Data center, firm population (52) | earns, integrator / client ($k) | 122 / 107 | 139 / 130 | +17 [−10, +44] / +23 [−2, +48] | first-offer stand-in 122 / 114 |
| Data center, head to head (52) | earns, integrator / client ($k) | 60 / 25 | 308 / 276 | +248 / +251 | |

## Appendix F. Quality control in detail

### F.1 The case author's checklist

Quality control runs on two tracks with a deliberate boundary. **Benchmark QC** qualifies the
instrument: the world distribution, the environment and verifier, the construct and the
attribution design, in six gates recorded per family in a QC profile. **Campaign gates**
qualify one experiment on that instrument: `design_contract`, `provider_free_validation`,
`profile_admission`, `full_trajectory`, `variance_pilot`, `confirmatory_freeze`,
`confirmatory_execution` and `publication`, in that order. A green campaign cannot repair a
bad reference, and a qualified family does not make an underpowered or selectively missing
campaign reportable. Each gate ends in one of five typed states (`passed`, `failed`,
`partial`, `not_run`, `not_applicable`), and only `passed` promotes.

**Table F.1. Benchmark QC gates.**

| Gate | Question | Stops when | In the four cases |
|---|---|---|---|
| 0. Profile | Is there a place to record each gate's verdict? | the family has no QC profile | Procurement's construct check ran and found a public-price rule beating the model by $28.50 a world; with no profile, the verdict was read as a campaign finding and lost |
| 1. Task distribution | Are the worlds valid, distinct, split and informative? | an unverified bound, duplicates across clusters, development and holdout overlap, no measured headroom | Housing v14 admits a seed on the tenant's own structure and reads quality afterwards, with a holdout from a disjoint seed range; pay-or-test admits on what a buyer can see and draws types afterwards |
| 2. Environment and verifier | Do actions change the intended state, and is every score rebuilt from sealed evidence? | invalid actions mutate state, an oracle disagrees, hidden state leaks, replay differs | 1,800 of 1,800 Housing v14 receipts replay with no provider call; P-D-17 (open): under sample noise a pre-award check computes kits from true yield, so one free action reveals the hidden quality |
| 3. Construct and baselines | Does a better-informed policy do better, and do shortcuts lose? | stronger and weaker policies indistinguishable, a shortcut drives the score | Procurement's shortcut rules give up $45.7 to $146.1 a world against an exact policy that a one-step comparison matches; an earlier data-center baseline was worse than walking away, by $550 (DC profile audit) |
| 4. Attribution and controls | Does the result support the attribution it claims? | an undeclared control changes, the matrix is incomplete, the block cannot carry the claim | the three v14 identities differ in model and route and also in reasoning tier, sampling and cost ceiling, a declared choice the contract did not state (HL-J-12); data-center claims name their counterparts |
| 5. Confirmatory reliability and publication | Was the comparison sized, frozen and executed without tuning on outcomes? | incomplete pilot, a frozen control changed, selective missingness, a guardrail no behaviour can fail | v14's analysis was declared before any cell; 36 refused cells stayed missing and a fill ran under its own identity |

Changing any bound input reopens the gates downstream of it: a generator change reopens Gates
1 to 5, a scorer change 2 to 5, a new counterpart 4 and 5, and a change to the analysis, seeds
or sample size after a freeze requires a new campaign identity.

**A contributed case enters through its own admission path.** Before it joins the registry a
contributed family must bind, in one version-bound record: a unique namespace; closed action and
observation schemas (every property required, nothing extra allowed); a provider-free conformance
report covering everything it declares; finite ceilings on wall time, actions, provider calls,
tokens and cost; and a human QC approval whose digest binds that exact contribution. The
approval must come from outside the contribution. Refund V2.1 showed why: its runner hashed two
status-only QC stubs and set the approval's digest to the contribution it had just built, so the
approval bound whatever the runner produced (RF-T-01). Refund V2.5's record names a reviewer and a
date and rejects V2.1's, but its runner still binds the approval to the contribution it has just
built (RF-D-06).

Three checks are owed before any model plays a new case. The reference plays every admitted
world and agrees with the environment (Appendix F.2). Every rule the brief states is checked against
the environment by a test, and the brief states what the side is judged on and whether a
price is final. And the simplest one-step rule is run first: if it matches the best policy,
the case is arithmetic and is not run. Procurement's pay-or-test pack is where this last check
was learned; a one-step comparison matches its best policy to within $0.06 a world, and both
frontier agents found that comparison (Appendix E.4).

### F.2 Check tools

Each kind of verifier (§4) owes a different proof that it measures what it claims.

**Table F.2. What each kind of verifier must be shown to do, and how the four cases show it.**

| Kind | Must be shown | How it is shown in the four cases |
|---|---|---|
| Answer | the key is correct and complete for every admitted case | Refund's reference resolution is written by hand per template, and admission requires the policy's public compiler to reproduce it on every case, with a unique path through the policy's precedence |
| Rule | every rule is stated to the subject, and each check fails on a counterexample | briefs are checked against the environment by tests; checks are mutation-verified (below); a rule left unstated is a defect of the case (P-D-19, RF-D-03) |
| Value | the reference agrees with the environment, and a simple rule does not already match it | Procurement's policy equals the environment's average over 27 type profiles; Housing's offline reference replays the sealed scripted cells to the cent; the one-step rule is run first |
| Relative | the counterparts are named, the gap is reported per counterpart, and the analysis does not fire on identical arms | the data-center counterpart table (Table E.5); an A/A arm (Appendix F.5) |
| Rubric | the rater agrees with people and resists gaming | not used in the four cases |

The checks below run without calling a model.

- **Regeneration.** Every world is re-resolved from its generator, parameters and seed, and its
  canonical content digest must match. Denominators, bounds and reference values are
  validated, and degenerate worlds stay visible under a declared rule rather than being
  silently resampled.
- **The reference against the environment.** Procurement's best informed policy is tested
  against the environment's average over all 27 ways the newcomers can turn out. Housing's
  offline reference first replays the sealed scripted reference cell for cell on the
  development worlds, 120 of 120 to the cent. In the data-center case a pair of reference
  players loses nothing on all 58 worlds, and a pair that signs the draft loses $318k a world
  over the same 58.
- **Reference run on every admitted world.** Before a pack is frozen, its reference is played
  on every admitted world through the real environment and verifier, with no model, and must
  reach its declared result; a test on the committed pack enforces it. In the four cases: the
  Housing reference and a full-information tenant play all 600 v14 cells and reproduce the
  published per-cell values, the tenant reaching the ceiling in every cell; Procurement's best
  policy equals the environment's average over the 27 type profiles in all 24 worlds; the
  data-center oracle pair loses nothing in all 116 worlds of both packs, checked against an
  optimum the test computes on its own; Refund's release requires full credit on every case.
  Mutation tests show each check fails when the reference or the grade is wrong.
- **Replay.** Every published receipt is rebuilt from its sealed events with no provider call
  and must reproduce its state and score; for Housing v14 that is 1,800 of 1,800. Refund V2.5
  qualifies its whole public release this way, with deterministic profiles in every seat: 816 of
  816 trajectories, every leaf covered, each receipt replayed independently.
- **Visibility.** Every payload a seat receives is audited for evaluator-only state.
- **Plan-level contract tests.** Paired plans are tested to differ only in the declared
  treatment or rotation.
- **Headroom screen.** The declared control is run on every candidate world, and a world is
  rejected on three grounds tested separately: *trivial* (a deterministic policy reading only
  public observations already succeeds), *floored* (the control never succeeds) and *saturated*
  (it always does). "The two policies disagree" is not a substitute; it admits a saturated
  world whenever a baseline happens to lose there. For a continuous score the grounds become
  *degenerate* (the control scores the same at every seed) and *trivial*.

Saturated and floored are claims about a rate, so the number of seeds per world is a sampling
plan with known errors, and the panel manifest states them.

**Table F.3. How often a screen admits or refuses a world, by seeds per world (control outcome is success or failure).**

| Seeds per world | Rejected when the control succeeds | Admits a world solved 95% of the time | Rejects one solved 50% of the time |
|---:|---|---:|---:|
| 1 | never or always | 0% | 100% |
| 3 | never or always | 14% | 25% |
| 10 | never or always | 40% | 0% |
| 10 | 1 or fewer, or 9 or more | 9% | 2% |

One seed can discard a world but cannot admit one, and under a never-or-always rule more seeds
admit more near-saturated worlds. A shared calculation (`aeread.design.screen_plan`) produces
these rates for any plan; no shared calculation yet covers the dispersion rule for continuous
scores.

**A check counts only once it has been seen to fail.** A required check is evidence only after
it has failed on a counterexample: revert the guard, confirm the check dies for the intended
reason, restore it, confirm it passes, and record the kill. Three defects fixed on 2026-09-05
had passed every existing suite because the suites asserted something true by construction.
For the same reason a screening loop never catches an exception: procurement's first two-sided
screen called a policy with a positional argument where the parameter was keyword-only, scored
the resulting error as a loss in every world, and printed a unanimous "admitted 6/6". A
unanimous verdict from an instrument is a reason to check the instrument.

### F.3 Trace and debug tools

**The Examiner.** Every published run opens in a trajectory viewer that shows each step as the
seat saw it, beside the state the seat could not see, with the parsed action, the transition
and the sealed score, and a QC checklist per run. On 2026-10-13 that checklist flagged 670
lines across 144 bundles; once every design row was read against its run, 58 needed a
reviewer, and each run opens with the lines that do.

**A hand trace.** Once per family, and again after any change of mechanism, one admitted cell
is walked by hand: the observation the seat received, the text the model returned, the parse,
the legality check, the transition and the sealed score, read from the real bytes. An admitted
cell is chosen rather than a failure, because it shows what the case rewarded. On an earlier
data-center design this found two design defects in about an hour at no cost, where live
panels found defects at $2 to $4 and an hour each.

### F.4 Adversarial checks

AERead has no model-driven exploit agent. Its adversarial checks are policies and audits that
try to score well without making the decision the case is about.

- **Shortcut policies must lose a declared margin.** In the data-center case walking away once
  came within $11k to $46k of the right contract and asking for every protection within $26k
  to $88k (DC-D-27); since then each named shortcut (sign the draft, haggle only the price, ask
  for every protection, walk) must cost $75k more than the best contract before a world is
  admitted. Procurement's fixed rules are scored exactly against the best policy (Appendix E.4).
- **Trivial agents are reported.** Signing the draft unchanged (14% of the value available) and
  always paying the premium ($75.2 a world given up) are reported beside the subjects; Housing
  v14 reports no do-nothing tenant.
- **The brief is audited for instructions that decide the outcome.** Procurement's earlier
  prompt pointed every subject at the cheapest listing (P-D-15), and its first pay-or-test brief
  left unsaid that a quote is final and that the average is the criterion (P-D-19, P-D-21).
- **Look-back analyses run a placebo outcome first.** A pattern found by looking back through
  runs is tested on an outcome that cannot depend on the attribute in question. The data-center
  look-back regression of Opus's price on its hidden type gave 0.52; the same regression on the
  opening price of a scripted integrator that is never told the type gave 0.38 [0.23, 0.52],
  where the answer must be 0 (DC-D-33). A random relabelling of types did not catch it (0 of
  3,000 shuffles reached the observed value), because a permutation null tests association and
  a confound is an association.
- **Guarded metrics must be falsifiable.** For each quantity a promotion rule guards, a
  synthetic arm that maximises it through the behaviour the rule should reject must be
  rejected. Terminal feasibility failed this test, because an explicit deferral counted as
  feasible.

### F.5 Statistical controls

**The unit is the world.** Repeats, seats, turns and calls inside a world are correlated;
uncertainty is computed over worlds, paired across conditions on the same worlds. On the
data-center runs, treating plays as independent made intervals about 1.5 times too narrow, and
more worlds beat more repeats: a $50k gap needs 83 to 91 negotiations an arm at one play a
world against about 160 at three.

**Claims name their counterparts.** When more than one counterpart type is run, the gap is
reported per type and tested for variation before pooling, and a general advantage needs a
positive gap against every declared type. In the data-center case the counterpart accounts for
25% to 33% of the spread in what a model earns (shuffled labels give 2% or less), and the gap
between the same two agents runs from not distinguishable to $251k (Table E.5).

**An A/A arm runs through the whole pipeline.** One profile in both arms, through execution,
scoring, analysis and the claim rule; a rule that fires stops the campaign before its freeze.
On the data-center repeat plays, 0 of 48 same-condition comparisons were flagged, and two runs
of one condition on 20 worlds differed by $16k to $25k typically.

**Sizing and reliability are computed and sealed.** The confirmatory number of worlds comes
from the variance pilot's paired world-level spread, a declared minimum meaningful effect, a
target power and an attrition rule, and the calculation is sealed with the freeze. A comparison
also reports its reliability, the expected correlation between the model means of two
independent runs of the same design:

```text
reliability = var_model / (var_model + var_world_model / worlds + var_play / (worlds x plays))
```

A world's own level is not error, because every model meets the same worlds; a counterpart or
seat that the design samples is error, and one it fixes narrows the claim instead.

**Declared tests.** A pattern found by looking back is a hypothesis. To become a result it is
written down first: the claims, measures, exclusions and primary predictions are committed
before the runs, the analysis code before the runs finish, on worlds no model has played, with
the world held fixed and one thing changed, and the primary predictions corrected together. Of
the two patterns the data-center signalling test declared, one was supported and one was not,
and the unsupported one had already been reported on a result sheet (DC-J-07).

**Harness settings are tested, not assumed.** Whether a CLI is asked for reasoning summaries
changed nothing detectable in Housing (Opus +17 [−28, +62], Sol +3.5 [−46, +53] on five
selected worlds, 120 episodes, randomised order), a small check whose limits are stated on its
sheet: the worlds were chosen after an earlier result and three plays cannot exclude a small
effect.

### F.6 Failure records and evidence review

Every failure is written down at the moment it occurs, including the wrong first hypothesis,
in two registers that are not interchangeable.

- **Tier 1, the machine register,** one per family, derived only from published evidence so
  every row traces to a committed artifact by digest; it is regenerated, never edited, and
  regenerating it must reproduce the committed bytes.
- **Tier 2, the judgment log,** for what a machine cannot derive, in four categories: design
  (D), operational (O), tooling (T) and judgment (J), the last including errors by whoever
  writes the entry. Rows are never deleted; only their disposition changes, and `open` is a
  normal resting state.

**Table F.4. Judgment-log rows by case and category (all branches, 2026-10-13).**

| Case (row prefix) | Design | Operational | Tooling | Judgment | Total |
|---|---:|---:|---:|---:|---:|
| Housing lemons and price line (HL) | 7 | 21 | 8 | 12 | 48 |
| Procurement (P) | 23 | 6 | 15 | 5 | 49 |
| Data center (DC) | 33 | 21 | 20 | 8 | 82 |
| Refund (RF, RV25) | 6 | 0 | 2 | 1 | 9 |

The counts cover each family's earlier designs as well as the current one. Operational rows are
where a measurement was lost and not rerun (a provider account out of credit, a CLI outage, an
overloaded route); judgment rows are where a reading was wrong, including two withdrawn claims
of our own (HL-J-08, DC-J-07) and a ratio misstated on a result sheet (P-J-05). A finding that reaches already-published numbers also gets a
sealed erratum selecting the affected evidence by identity; published bundles are never edited.
The errata tooling is in review (PR #117).

**Evidence is reviewed by verification.** A sealed run root is published as a bundle with a
manifest of content digests. Reviewing an evidence bundle means recomputing its digests,
replaying every receipt from its sealed events with no provider call, scanning for prohibited
text, and pasting the output as the review; nobody is asked to read a 100,000-line bundle.
Changes to the shared runner need an approving review from someone other than the author.

### F.7 What quality control found in the four cases

**Table F.5. Defects found by quality control, with the level at which each was visible.**

| Row | What was wrong | Visible in one world? | How it was found | What changed |
|---|---|---|---|---|
| HL-D-04 | A seat-number tie-break and scripted rivals' $1 overbid decided who signed a sound listing | no: a pattern across seats | comparing signing rates by seat | one deciding tenant against declared outside demand |
| HL-D-01 | The scripted landlord's accept-or-counter reply was a free, near-perfect quality test beside a $25 inspection | no: needs the cost distribution | validity audit before a second model ran | pooled landlord; the revealing landlord kept as a declared arm |
| HL-D-03 | Admission made a favourite's lemon rate depend on its popularity (0.29 when six tenants shared it, 0.53 before admission) | no: a property of the admitted set | comparing pre- and post-admission rates | admit on the tenant's structure, read quality afterwards |
| HL-D-05 | The rule the tenant was told sat outside the sealed request | yes, by reading the sealed bytes | known at build, logged before any run | the rules sealed in the prompt, the tenant's history in the observation |
| HL-J-02 | A gap decomposition's "luck" part was not luck: uncontested blind bets were lemons 11 of 15 times, contested 1 of 15 | no: a split by rival behaviour | testing the stated odds by model (p = 0.006) | blind signings scored at their expected value given what the tenant saw |
| P (Gate 0) | A rule reading only the displayed price beat the qualified model by $28.50 a world | no: a baseline comparison | the construct check | construct gate recorded `failed`; Gate 0 made a profile mandatory |
| P-D-15 | The prompt pointed every subject at the cheapest listing, right in half the worlds and wrong in the other half | no: needs the pack's construction | asking whether the hard half was valid or a trick | a neutral prompt and a new pack |
| P-D-19, P-D-21 | The brief did not say a quote is final or that the buyer is judged on its average | no: a pattern in loss by action | listing each loss by the action that caused it | a second brief; loss fell from $12.2 to $1.0 and $19.4 to $5.4 a world |
| P-D-17 | Under sample noise the pre-award check reveals the true yield for one free action | yes, by reading the tool's code | designing a sample-again decision | open; 1 of 260 noisy cells used it, no published number moves |
| DC-D-27 | Walking away came within $11k to $46k of the right contract, and asking for every protection within $26k to $88k | no: a strategy-class simulation | simulating shortcut policies on the pack | before any freeze: each named shortcut must cost $75k more than the best contract, and a deal must beat the better outside option by $150k |
| DC-D-29 | At low effort the case could not separate two models: about 83% of the per-world gap was seed noise | no: needs paired seeds | variance split of the paired gap | one seed per world and more worlds; a redesign of the case |
| DC-D-32 | The scripted style hashed the whole world, including the client's hidden charge | no: needs two copies of a world | a test that the opening is identical for both types failed | the declared test uses a fixed style |
| DC-D-33 | The hidden type was fixed by pack cell and moved with public quantities | no | a placebo outcome (Appendix F.4) | packs that play each world under each type |
| HL-D-07 | The primary measure conditions on the landlord's reply only below the sound floor; a reply that proves a listing sound is still scored at the stated odds | yes, by reading the measure's code | writing the formal appendix of this paper | recomputed from the sealed run roots: 57 signings move, no declared verdict changes, Gemini's leads shrink by $10 to $15; an erratum is owed |
| RF-D-01 | The 120-cell panel was six cases: the world seed changed only the case id, and the policy seat ran at temperature 0 | no: needs the seeds compared | rebuilding the cases and reading the reference run's resolutions | the case is the unit of analysis; V2.5 varies declared conditions by seed |
| RF-D-03 | A correct denial written with method `null` failed: the prompt says "none", the schema allows null, the verifier compares strings | yes, by reading one proposal against the verifier | building the gap decomposition | recorded; reported as format, not outcome |
| RF-T-01 | The human-QC approval was minted by the runner from two status-only stubs, so it bound whatever the runner produced | yes, by reading the runner's code | the Refund audit | V2.5 names a reviewer, but the runner still binds the approval to its own output (RF-D-06, open) |
| RF-D-05 | Refund's payment leaf checks that payments executed what the proposal asked, so a proposal with an aliased mutation moves no money where the reference refunds $185.22 and still scores 1.0 | yes, by tracing one case | writing the formal appendix of this paper | open; report the leaf as binding and add a check against the reference |
| P-D-23 | The pay-or-test action schema let `message` be null while the parser requires it, so a model's first action could end its episode on format | yes, in one gate cell | the flash-model gate | the schema requires every field the parser needs, under new identities |

Twelve of the nineteen were invisible in any single world, and the seven that were visible were
found by reading code or sealed bytes, or by tracing one case, not by playing a panel. That is the main reason quality control
is organised around populations of worlds, declared analyses, code reading and recorded
failures rather than around reviewing instances.

### F.8 Assessment against the Agentic Benchmark Checklist

The QC standard aligns its task and outcome validity checks with the Agentic Benchmark
Checklist [ABC]. Table F.6 assesses the four cases as they stand, item by item; the
outcome-validity items that apply are those for a quality measure, since no case is scored by
string matching, unit tests or a judge model.

**Table F.6. The four cases against the checklist.**

| Item | Status | Evidence |
|---|---|---|
| T.1 Tool versions specified | partly | routes, prompts, schemas and implementation digests are sealed in each plan; the two CLI agents expose no seed or temperature |
| T.2 Required APIs accessible | partly | provider outages lost cells (36 Housing cells to an empty account, 39 data-center negotiations to CLI errors), each recorded as typed missingness |
| T.3 Terminates or handles API errors | met | a sealed retry policy; three consecutive failed cells stop a run; a failure is never scored as zero |
| T.4 Residual state cleared between runs | met | each cell is a fresh episode from a sealed plan; the CLI agents run one ephemeral subprocess per action |
| T.5 Agent isolated from ground truth | partly | observations are audited for evaluator-only state; one leak was fixed (HL-D-01) and one is open in noisy-sample packs (P-D-17) |
| T.6 Setup does not change over time | met | the environments are deterministic and sealed; hosted model routes are pinned and snapshotted |
| T.7 Ground truth verified | met | each reference is played on every admitted world through the environment and reaches its declared result, enforced by a test (Appendix F.2) |
| T.8 Each task verified solvable | met | the reference plays every admitted world, and admission requires that the decision matters |
| T.9 Oracle solver | partly | exact for Procurement; an independent reference resolution and a scripted policy that resolves every case for Refund; a reachable reference for Housing, with an exact best informed tenant in development; a full-information stand-in for Data center, whose per-turn best informed policy is not built |
| T.10 Free of exploitable shortcuts | partly | shortcut policies, trivial-world screens and brief audits (Appendix F.4); nineteen defects found (Table F.5); a wrong refund can still pass Refund's payment leaf (RF-D-05); a model-driven exploit agent is designed, not built |
| O.i.1 Quality metric resists exploitation | met | dollars against an exact or reachable reference; blind bets priced at expected value; guarded metrics must be falsifiable |
| R.1 Open source | partly | the environments, runner and evidence are public; the trajectory viewer is private |
| R.2 Open evaluation harness | met | the shared runner is in the public repository |
| R.3 Contamination prevented | met | generated worlds; holdouts from a disjoint seed range; fresh worlds for declared tests |
| R.4 Plans to update | partly | packs regenerate from new seeds; no refresh schedule is stated |
| R.5 Capability related to construct | met | each case states the decision it measures (Table 5.1) |
| R.6 Evaluation subject stated | met | the subject is a profile (model, harness, prompt, tools, reasoning, retries); CLI agents are named with their harness |
| R.7 Steps to prevent, find and correct flaws | met | the gates, the incident log and errata (Appendix F.1, Appendix F.6) |
| R.8 Qualitative discussion of unavoidable flaws | met | the end of §5.1 |
| R.9 Quantitative analysis of flaw impact | partly | measured for the brief change, the refused cells and missingness bounds; not for every open row |
| R.10 Statistical significance | met | paired world-level intervals; Holm correction across declared primaries |
| R.11 Guidance on interpreting flawed results | met | every result is labelled confirmatory, declared or development |
| R.12 Non-AI baselines | partly | scripted policies in every case; no human |
| R.13 Trivial agents | partly | always paying (Procurement) and signing the draft (Data center) are reported; Housing v14 reports no do-nothing tenant, and Refund V2.1 has no lower anchor (RF-D-04) |
