# Case studies (draft section of the AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. Written from the current design
of each case, its one-page result sheet, the bundles or run roots those sheets cite, and a
reading of each case's code for the formal appendix
([Appendices A–D](paper_appendix_case_specs.md)). It supersedes the Housing and Procurement
case material in the 2026-09-06 working draft (`aeread_environment_paper_draft.md`, on branch
`codex/housing-v13-cooldown-full-trajectory`). One result below is confirmatory (Housing v14);
one is a test declared before its runs (the data-center signalling test); everything else is a
development probe and is labelled so. The companion section is
[Quality control](paper_qc_design.md).

---

## 5. Case studies

AERead is meant to grow through cases contributed by a wider community. This section
presents three cases built by the maintainers as worked examples of what a contributed case
can look like: renting under adverse selection (Housing), qualifying a supplier under a
deadline (Procurement), and negotiating a services agreement (Data center). Each case is a
family rather than a fixed task set: a generator of worlds, a reference computed from what the
deciding side is allowed to know, an admission rule that keeps only worlds where the decision
matters, and a set of verifiers. Together they cover three kinds of verifier, two kinds of
counterpart (scripted and model), and both one-seat and two-seat play.

Cases are chosen by the economic value of the decision, not by occupation [AV]. An activity
qualifies when its value is decided rather than produced, when a counterparty has its own
interest and private information, and when the result can be scored inside a world against a
computed reference. The target distribution weights cases by the flow each class of transaction
decides (§5.10). The three examples sit in two of its five classes: they were chosen to span the
kinds of verifier and counterpart, not drawn from that distribution.

**Table 5.1. The three examples, and what a contributor can reuse from each.**

| Case | Decision under test | Seats and counterparts | Verifiers used (§5.1) | Pattern to reuse | Status |
|---|---|---|---|---|---|
| Housing | which listing to verify, what to offer, whether to sign when two of four listings are lemons | one model tenant; scripted landlords of two kinds; outside demand | value (dollars against a reachable reference and a ceiling); rule (legal moves) | hidden quality with costly verification; two counterpart kinds played on every world; scoring at decision time rather than on the draw | confirmatory |
| Procurement | pay a premium for a supplier with a record, or test a cheaper newcomer, before a deadline | one model buyer; scripted suppliers | value (dollars each action gave up against an exact best policy) | buying information versus paying for certainty; an exact reference that prices every action | development |
| Data center | which risk clauses to move, what price to name, when to sign or walk | model or script in either seat; scripted negotiators in five styles, including adversarial ones | value (joint value lost against the best agreement); relative (each side's take, by counterpart); rule (signing below one's walk-away point) | two-sided negotiation with private types; the counterpart as part of the measurement | development, one declared test |

### 5.1 Kinds of verifier

A verifier compares what happened with something. We classify verifiers by what they compare
against, because that decides what a score can claim and how the verifier itself must be
checked (§6.2). Five kinds cover the design space; the three cases use three of them:

- **Answer.** The outcome is compared with an answer key: did the resolution match? A key must
  be shown correct.
- **Rule.** The outcome or the path is checked against declared rules: was a rule broken, and
  how often? Rules must be stated to the subject.
- **Value.** The outcome is priced in the case's own units against the best policy or a bound:
  how many dollars short? The reference must agree with the environment.
- **Relative.** The outcome is compared with another agent or a population of them: how much
  more did it keep than its counterpart? The claim covers only the counterparts named.
- **Rubric.** A rater scores the artifact against a rubric. The rater must be calibrated.

Two labels go on every check. Its **output** is pass or fail, a count, or an amount. Its
**scope** is the outcome or the path that led to it. The scope matters in practice: a Housing
tenant can end on a sound listing without having verified it, which the outcome alone would not
show, and Procurement prices every action rather than only the award (§5.7). These five
kinds are the repository's verifier taxonomy under plain names (canonical reference, rule and
constraint, objective reference, comparative, rater and judge).

**Table 5.2. Every reported check in the three cases.**

| Case | Check | Kind | Output | Scope |
|---|---|---|---|---|
| Housing | tenant net per world against the reachable reference and the ceiling | value | dollars | outcome |
| Housing | holds signed that only a lemon's landlord would offer; ending on an uninspected listing | rule | count | path |
| Housing | model against model, paired by world | relative | dollars | outcome |
| Procurement | dollars given up against the best informed policy, action by action | value | dollars | path |
| Data center | joint value lost against the best of 600 agreements | value | dollars | outcome |
| Data center | each side's surplus, by counterpart | relative | dollars | outcome |
| Data center | signed below one's own walk-away point; disclosed a confidential item | rule | count | outcome; path |

None of the three uses an answer key or a rubric. Every score is computed from the sealed trajectory and replayed
without a model, which is the property we ask contributors to preserve where they can; a
rubric leaf is supported, but it is kept beside the computed ones and never folded into them.

### 5.2 Case formulation

A case fixes one decision, the seat the model plays, what that seat sees and what is hidden
from it, the actions it may take, and how long it has. The other seats are scripted, or are
another model; a script follows a stated rule on its own seat's information. Appendix A gives
each case formally, in the form of an environment, a protocol and fixed counterpart policies.

**Housing.** A tenant faces four landlords. Two of the four listings are lemons, worth $1,000
less; an inspection costs $25 and reveals one listing's quality to the tenant alone. Over three
rounds the tenant may inspect, offer, and sign or walk. Each listing it made no offer on in a
round is taken by outside demand at rate ½, by a draw the world fixes, so every subject and
both landlord kinds meet the same departures. Every world is played under two landlord kinds:
a *leaky* landlord prices a lemon on its own lower cost, so a reply far below the ask reveals
it; a *pooled* landlord prices a lemon like a sound listing. The tenant is told the lemon count,
the loss, the fee, the departure rule, the horizon, and that a landlord's counteroffer can carry
information about quality; it is not told how landlords price.

**Procurement.** A buyer owes 50 kits by a deadline. One supplier has a long clean record and
the highest price; three are 3% to 21% cheaper and new, each listing what share of new sellers
of its kind proved unreliable on delivery or failed inspection. A quote ($2, a day) shows
whether a supplier delivers on time; a sample shows its yield ($30 and two days for the
recorded supplier, $30 to $80 and three days for a newcomer); every award needs both.
Supplying nothing costs the $12 shortfall penalty on all 50 kits, on top of whatever was spent
finding out.

**Data center.** An integrator will deliver a GPU cluster into a client's facility, and its
standard draft is on the table. Moves alternate, three a side: redline (move any of eight
clauses between fixed positions and name an all-in price, with an optional note), sign what
the other side last put on the table, or walk to an outside option. The clauses decide who pays
when one of four things goes wrong (a compatibility defect, a late facility, an incident after
handover, the integrator failing while holding an unprotected deposit), and the integrator
pre-stages hardware and prepares the site exactly when the clauses make that cheaper for it, so
moving a risk to the side that can control it shrinks the total rather than only moving it.
Each redline after the opening costs its author $25k.

**Table 5.3. The three cases in brief.**

| | Housing | Procurement | Data center |
|---|---|---|---|
| **Model's seat** | one tenant | one buyer | client or integrator |
| **Hidden from the model** | which listings are lemons; landlord costs; how a landlord prices a lemon | each newcomer's delivery and yield type, drawn from stated odds | the client's risk charge; the integrator's pre-staging cost (its risk charge shows in its draft) |
| **Actions** | inspect, offer, sign, walk | quote, sample, inquire, counter, check an award, award, defer | redline with a price and a note, sign, walk |
| **Horizon** | three rounds | the deadline, in days | six moves |

### 5.3 Pack construction

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

### 5.4 References and measures

Every case scores a play against something computed, not judged. Appendix C gives each
reference policy as a recursion and Appendix D each measure.

- **Housing.** The reference is a scripted tenant that uses only what the prompt gives: it
  inspects its favourite, offers $0 on the best listing it has verified, and signs any counter
  its known value covers. It earns $292 a world on the main pack; a tenant that knew every
  listing's quality would earn $370 (the mean of $448 against the leaky landlord and $292
  against the pooled one). Realized payoff is dominated by which blind bet happened to be a
  lemon, so a blind signing is scored at its expected value under the stated odds, except that
  a hold the leaky landlord priced below that listing's sound floor is scored as a lemon. A
  counter that proves a listing sound is still scored at the stated odds; correcting that moves
  no declared verdict (HL-D-07, §5.6). The tenant's net per world is averaged over the two landlord kinds.
- **Procurement.** The best informed policy knows the stated odds and nothing else about a
  newcomer. It is solved exactly by working back from the deadline over everything a quote or a
  sample could show, and earns $451 a world in expectation, equal to the environment's average
  over all 27 ways the newcomers can turn out. Each action is charged the best policy's value at
  that point less the value of the action taken, given only what the buyer had learned; the
  charges sum to the play's shortfall, and their expectation is the policy's gap to the best.
- **Data center.** Every amount is computed at both sides' true costs. Joint value lost is the
  surplus the best of the 600 distinct agreements would create, less what the pair realized,
  redline costs included; each side's result is its surplus over its own outside option.
  Against a script, a stand-in that knows both sides' costs and the script's style gives a
  ceiling that is not a fair target. The design's per-turn loss against a best informed policy
  is not built.

### 5.5 Composition

**Table 5.4. What was run.**

| Case | Worlds or cases | Strata | Subjects | Plays | Cost (list) | Status |
|---|---|---|---|---|---|---|
| Housing | 260 main + 40 holdout | favourite lemon (200 + 30), favourite sound (60 + 10); both landlord kinds in every world | Gemini 3.8 Flash, GLM 5.3 Flash, GPT-6 Luna | 1,800 cells and a 48-cell fill | about $8 | confirmatory |
| Housing, CLI agents | first 20 of the main pack | 10 and 10 | Opus 5.5, Sol 6.1 | 40 cells each | $4.72 | development |
| Procurement, pay or test | 24 | six kinds × four | Opus 5.5, Sol 6.1 | 96 cells over two briefs | $9.10 | development |
| Procurement, pay or test, flash models | 24 | six kinds × four | Gemini 3.8 Flash, GPT-6 Luna (GLM's route refused, P-O-06) | 24 cells each, second brief | $0.21 | development |
| Procurement, record pack | 18 | which listing the record favours | Opus 5.5, Sol 6.1 | one cell a world each | | development |
| Data center | 58 development + 58 fresh | deal or no deal; outside-option kind; counterpart style | Opus 5.5, Sol 6.1 | 2,456 negotiations, 2,417 valid | $119.13 | development; one declared test |

Opus 5.5 ran through Claude Code and Sol 6.1 through the Codex CLI, without tools, at low
reasoning effort, one subprocess per action; neither CLI exposes a seed or temperature, and
both are recorded as unavailable rather than assumed.

### 5.6 Results

#### Housing

The three flash models were run under one analysis declared before any cell: three model pairs
corrected together (Holm), each model against the reference, a $50 minimum meaningful
difference, the holdout reported apart.

**Table 5.5. Housing v14, main pack (260 worlds); dollars per world, 95% intervals paired by world.**

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

**Table 5.6. Procurement pay-or-test, 24 worlds, one play a world; dollars given up per world.**

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
[3.6, 22.3] and $14.0 [0.4, 33.5] (§5.7). The record pack is saturated the same way: Opus solves
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

**Table 5.7. Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

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
so earns 122 as integrator and 114 as client), by the opposite routes described in §5.7. At equal
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
run, on the fresh worlds of §5.3. Sol asks for 1.82 [1.23, 2.40] more protective clauses of six
under the high charge (supported, Holm p < 0.001), 1.58 [0.95, 2.22] more than Opus does;
fitting its clauses to its type is worth about +120k [+83k, +156k] of joint value a world to it.
Opus's price pass-through is −0.07 [−0.18, +0.05], not supported; the earlier 0.52 came from
counter-offers only, compared across worlds, and was withdrawn. Counterparts that read the first
offer gained nothing measurable from either model (+2k [−14k, +17k]; −8k [−42k, +26k]).

Of 2,456 negotiations, 2,417 are valid. Every failure is a CLI service error; the original
bundles keep them as missing, and 16 were played again under separate identities by the owner's
ruling.

### 5.7 Error analysis

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

**Table 5.8. Opus 5.5 and Sol 6.1 on the three cases.**

| Case (worlds) | Measure | Opus 5.5 | Sol 6.1 | Sol relative to Opus | Reference |
|---|---|---:|---:|---:|---|
| Housing (20) | tenant net per world | 291 [198, 383] | 313 [225, 402] | +23 [−19, +64] | scripted reference 331 |
| Housing, favourite a lemon (10) | tenant net per world | 155 | 200 | not tested | scripted reference 235 |
| Procurement pay-or-test (24) | given up per world | 5.4 [1.2, 10.6] | 1.0 [0.2, 2.1] | 4.4 [0.6, 9.0] less given up | best policy gives up 0 |
| Procurement, record pack (18) | worlds solved | 18 | 16 | regret −20 [−48, +7] (Opus lower) | informed policy 18 |
| Data center, firm population (52) | earns, integrator / client ($k) | 122 / 107 | 139 / 130 | +17 [−10, +44] / +23 [−2, +48] | first-offer stand-in 122 / 114 |
| Data center, head to head (52) | earns, integrator / client ($k) | 60 / 25 | 308 / 276 | +248 / +251 | |

Five observations hold across the cases.

1. **The gap sits in a stratum the design fixes in advance.** Housing's shortfall is in
   favourite-lemon worlds; procurement's residual loss is in test worlds; the data-center losing
   signatures are all in self-manage worlds. Every case reports by declared stratum and pools
   last.
2. **The counterpart is part of the measurement.** The same two agents are equal against one
   counterpart and 250 apart against another (Table 5.7). A claim names the counterparts it
   covers.
3. **What the brief states moves the score as much as the subject does.** Stating that a quote
   is final and that the average is the criterion cut procurement loss by $11 to $14, more than
   twice the gap between the two agents; stating a walk-away cost cut the data-center losing
   signatures from 15 of 60 to 1 of 60. The brief and the action schema are controlled,
   versioned parts of the case.
4. **Outcome and path diverge.** Housing models often sign the right kind of listing without
   having verified it, and the flash models in Procurement reach a feasible award while giving
   up the value of a test. A case should say which it scores, and report both where both
   matter.
5. **Patterns found by looking back are not results until tested.** One of the two data-center
   signals failed its declared test. Only declared tests enter the results above.

### 5.8 Headroom

A case is useful only while it is not saturated, and unsaturation has to be shown rather than
assumed. We count a case as having headroom when the best subject falls short of a reference it
could have reached, in a stratum declared before the runs, by an interval that excludes zero.
Table 5.9 states the evidence case by case.

**Table 5.9. Evidence of headroom in each case's hardest declared stratum.**

| Case | Hardest declared stratum | Best subject | Reference | Best subject minus reference | Headroom |
|---|---|---|---|---|---|
| Housing v14 | favourite is a lemon (200 worlds) | Gemini 3.8 Flash | the reachable scripted tenant | −102 [−122, −82] per world; −99 [−119, −80] with HL-D-07 corrected | shown, in a confirmatory panel |
| Housing, CLI agents | favourite is a lemon (10 worlds) | Sol 6.1, $200 | the same, $235 | −35, no interval at 10 worlds | suggested, not tested |
| Data center | every deal world, head to head (52) | the pair with Opus as integrator | the best of 600 agreements, computed exactly | joint value lost 79 [70, 88] of about 410 available; best agreement signed in 19 of 52 worlds | shown |
| Data center | overreaching counterpart, client seat (52) | Sol 6.1 | refusing every deal below the walk-away point | Sol signs none; Opus signs 23 | shown for Opus only |
| Procurement, frontier agents | every world (24) | Sol 6.1 | the best informed policy, exact | 1.0 [0.2, 2.1] per world given up | not shown: at the ceiling for both frontier agents |
| Procurement, flash models | every world (24) | GPT-6 Luna | the same | 74.4 [46.7, 102.7] per world given up | shown for the flash tier |

Headroom is shown in Housing and Data center, and in Procurement for the flash tier only. In
Procurement the frontier agents are at the ceiling while both flash
models give up about $75 a world, so the pack separates the tiers and cannot separate frontier
agents; its harder variants (odds left for the buyer to infer, noisy tests that may need a
second batch) are designed, not run. The data-center stand-in that knows
both sides' costs earns 72k to 128k more than either model against the firm population, but it
is a ceiling rather than a reachable reference, so it is not used as evidence here.

### 5.9 Limitations, and what a contributed case adds

These cases do not rank models in general. Two frontier agents at one reasoning setting played
all three; flash-tier models played Housing and Procurement's pay-or-test pack; no human
played any; the
prices, fees and odds are the designers' assumptions, not calibrated by a practitioner; and only
Housing ran a declared confirmatory campaign. Headroom is shown in all three cases, in
Procurement for the flash tier only (§5.8).

The three cases measure three decisions: whether to pay to verify when quality is hidden and
adversely selected; whether to pay a premium for a known supplier or buy information about a
cheaper one under a deadline; and how to trade risk clauses and price with a counterpart whose
costs are private. A contributed case can extend this in four ways, at very different costs:

- **A new pack within a case.** A generator setting and an admission rule; the reference,
  verifiers and runner are reused.
- **A new counterpart style.** A scripted rule with stated parameters (Appendix B), reported as
  its own stratum.
- **Frozen turns.** The data-center design admits a written mid-negotiation state as an item: one
  decision, scored against the best informed policy played forward. Designed, not built.
- **A new case.** A decision, a generator, a reference, an admission rule and verifiers of the
  kinds in §5.1, qualified through the checklist in Section 6. Eleven published economic
  benchmarks are already wrapped as families of the same runner and show the minimum shape of
  such a contribution, though without exact references.

### 5.10 Task distribution: choosing cases by economic value

The target distribution follows the argument of [AV]: the value of a dealing activity lies in
the flow it decides, not in the hours spent on it, so cases are weighted by that flow. An
activity qualifies when three things hold. Its value is decided rather than produced, so the
flow it governs is large against what it costs to perform. A counterparty has its own interest
and private information, so readiness means bargaining, matching, commitment, protection and
refusal rather than the quality of a deliverable. And the result can be scored inside a world at
the end of the episode against a computable reference. What passes decides about $47.6 trillion
of US flows a year; contracting, risk transfer, brokerage and advice enter as stages and seats
inside the transactions, as the data-center clauses do.

Each transaction is counted once and its two seats share the weight; a 10% floor keeps every
class readable, and results are reported per class, never as one undecomposed score.

**Table 5.10. The target distribution, and where the three examples sit.**

| Class | Seats | Flow decided (US, 2025) | Weight | Examples in this section |
|---|---|---|---:|---|
| Business purchases | buyer and seller | $20.0T of inputs bought by businesses | 39% | Procurement (buyer); Data center (client and integrator) |
| Labour contracts | employer and worker | $15.7T of compensation | 30% | none |
| Capital and corporate transactions | lender and borrower, acquirer and target | $5.6T of investment | 11% | none |
| Household purchases, the part a household deals over | household and firm | $3.2T of $20.9T | 10% | Housing (a lease) |
| Public purchases | state and bidder | $3.1T of public procurement | 10% | none |

By flow alone the weights would be 42%, 33%, 12%, 6.7% and 6.5%. The three examples cover two
classes carrying 49% of the target weight, and none of labour contracts, capital transactions or
public purchases. That is by design for a set of worked examples, chosen to span the kinds of
verifier and counterpart in §5.1; the distribution is what contributed cases fill. A contributed
case states its class and seat, and the suite reports each class on its own.

### References

- [AV] Li, C. *Activities, not occupations.* AERead blog, 8 October 2026. https://aeread.org/blog/activities-not-occupations.html

### Sources for the numbers in this section

| Table or claim | Source | Status |
|---|---|---|
| Table 5.5, Housing v14 | `evidence/housing/housing_lemons_price_confirmatory_v14` and `..._v14_gemini_fill` (branch `codex/housing-lemons-outside-demand`, draft PR #256); the case contract's v14 section on that branch; one-pager `housing_lemons_confirmatory_v14_with_claude_codex.pdf` | confirmatory |
| HL-D-07 recomputation | the sealed v14 run roots; script and results `~/analysis/housing/hl_d_07/` (outside the repository) | derived |
| Housing pack, ceiling by arm, outside-demand share | the case contract's "confirmatory pack" paragraph; the code reading for Appendix A (`lemons_design.py`, `price_outside_demand.py`, `price_reference.py`) | |
| Housing CLI rows | run roots `housing_lemons_price_cli_v1_{claude_code_opus55,codex_cli_sol61}_outside_w20`; page 2 of the same one-pager | development, unadjusted |
| Best informed tenant ($307) | branch `codex/housing-best-informed`, `price_best_informed.py`; recomputed 2026-10-13 from its 600 cells per knowledge level | development |
| Table 5.6, pay-or-test | run roots `pay_or_test_v1_{accounting,finalquotes}_*` (branch `codex/procurement-pay-or-test`); recomputed 2026-10-13 with `pay_or_test_report.py`; one-pager `procurement_pay_or_test_first_result.pdf`; incident rows P-D-19 to P-D-22, P-J-05 | development |
| Procurement flash panels | run roots `procurement_allocation_pay_or_test_v1_finalquotes_openrouter_{gemini38_flash,gpt6_luna}_v2` in the pay-or-test worktree; driver `tools/cli_subjects/pay_or_test_openrouter.py` (d91fbde8), report fix eecdaffe; incident rows P-D-23, P-O-05, P-O-06, P-T-14, P-T-15 | development |
| Record pack (18 worlds) | branch `codex/procurement-inference-v2`, draft PR #263; incident row P-D-16 | development |
| Table 5.7, adversarial counterparts, declared test, §5.7 data-center counts | `agreement_results_2026-10.md` and `agreement_signalling_plan_2026-10.md` on branch `codex/datacenter-agreement`; bundles `evidence/datacenter_development/datacenter_agreement_cli_*` (incl. `scripted_tactics_v1`, `elicitation_probe_v1`); one-pagers `datacenter_agreement_first_result.pdf`, `..._scripted_result.pdf`, `..._signalling_test.pdf`; incident rows DC-D-32, DC-D-33, DC-J-07 | development; the signalling test was declared |
| Task distribution (Table 5.10) | [AV], from the BEA national accounts (2025) and BLS wage statistics (May 2023) | |
| Housing CLI cost ($4.72) | list prices of the two CLI runs, $1.78 (Sol) and $2.94 (Opus), from the CLI probe's run reports | development |
