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
| Refund | evidence complete before deciding; contract format; payment bound to the proposal | rule | pass or fail per leaf | path |

None of the four uses a rubric. Every score is computed by code from the recorded trajectory,
with no model or rater in the loop. The kernel's replay certifies each receipt's own score; in
Housing and Procurement the headline measure is computed outside the receipt (Appendix F.2), and
a contributed case should make its headline a receipt leaf so that replay covers it. A rubric leaf
is supported, but it is kept beside the computed ones and never folded into them.

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
where the decision is hardest. This is v14's rule. v15 (Section 5.1) applies it and then screens each candidate
world offline:
- **The screen.** The best informed tenant and `inspect_then_sign` play both landlord arms. A world is admitted only
  if its full-information ceiling is above $0 in both arms and the tenant beats the rule by at least $25 on the
  corrected measure, averaged over the arms.
- **What it admitted.** The main pack of 260 (200 and 60) came from 437 seeds: 119 failed the screen, 6 had a $0
  ceiling and 7 failed the structure rule.
- **The other streams.** The holdout of 40 runs outside demand at 0.3 a round from a disjoint range, and 20
  development worlds serve the profile admission and the variance pilot.
- **Records.** No two admitted worlds are near duplicates, and every seed's numbers are logged in the pack's scan.

**Procurement.** Six kinds of world, four of each: paying is right on the money; paying is
right because a failed test would leave no time for the recorded supplier; a test is right
with the cheapest or with another newcomer, on a tight or a loose clock. A world is classified
from its listings with every newcomer assumed good, and the newcomers' types are drawn
afterwards on their own stream. The kinds are sampled evenly; drawn as they fall, a test of
the cheapest newcomer would be right in most worlds. This classification screens no shortcut,
which is why a one-step rule nearly solves the pack (Appendix F.4). The second pack's admission
does: computed from what a buyer sees and the stated law, it keeps a world only if each screened
shortcut, the one-step rule and four fixed rules included, gives up at least $10 against the best
policy, and the admitted pack's mean one-step loss must reach $15; 24 worlds were admitted from
5,798 seeds. A sibling pack of 18 worlds puts a
marketplace record on one component's listings, from which whom to verify can be read.

**Data center.** Eleven cells, each with its own outside-option situation and the playbooks it
allows, two worlds per cell and playbook: 58 worlds, 52 with a deal worth signing and 6 where no
agreement beats both outside options. The 58 development worlds come from the generator of the
case's predecessor; the declared test used 58 fresh worlds from the same generator, none equal
in content to a development world, and for its type-swap experiment wrote 29 of them twice,
identical except for the client's hidden risk charge. The admission rule implemented is the
predecessor's (a shortcut must lose by a margin on the playbook's menu); the agreement case's
own admission rules were not used for these runs. The confirmatory pack is admitted by
the agreement case's own rule, computed from the public world and the declared prior before any
hidden type is drawn. In expectation over the prior, a world is admitted only if the best
agreement beats the draft by at least $75k; knowing the client's hidden charge is worth at least
$25k to the integrator's choice of agreement, and for every integrator type the best outcome
changes with that charge; signing the draft as it stands, moving only the price, or either side
demanding every protection each lose at least $75k against the best agreement; and walking away
loses at least $150k. Redline fees are left out of every shortcut, which favours the shortcut, so
each margin is a lower bound. Of 2,729 seeds scanned, 60 were admitted (45 deal, 15 no-deal); v1
used them, with types drawn after admission and a separate 12-world variance pilot (Appendix F.2).
v2 (Table 5.4) kept these rules and added one screen, computed before any cell: on a deal world the
integrator's full-information ceiling against the firm population must beat the price-only rule by at
least $25k. Its seeds are disjoint from every earlier pack; of 5,436 scanned, 80 were admitted (72 deal,
8 no-deal).

### E.3 What was run

**Table E.2. What was run.**

| Case | Worlds or cases | Strata | Subjects | Plays | Cost (list) | Status |
|---|---|---|---|---|---|---|
| Housing v14 | 260 main + 40 holdout | favourite lemon (200 + 30), favourite sound (60 + 10); both landlord kinds in every world | Gemini 3.8 Flash, GLM 5.3 Flash, GPT-6 Luna | 1,800 cells and a 48-cell fill | about $8 | confirmatory |
| Housing v15 | 260 main + 40 holdout (outside demand 0.3), from a screened pack | as v14 | Gemini 3.8 Flash, GPT-6 Luna, and Luna's A/A twin | 1,720 cells, all verified by replay; pilot 160 cells | $8.64 (pilot $1.08) | declared; Gates 1, 2, 3 and 5 passed, 4 partial |
| Housing v15 addendum B | the v15 pack: 260 main + 40 holdout | as v15 | Sol 6.1 (Codex), Opus 5.5 (Claude Code), both isolated | 1,200 cells, all completed and verified by replay | $24.30 and $54.03 at list price (subscriptions) | declared addendum, outside v15's contrasts |
| Housing, CLI agents | first 20 of the main pack | 10 and 10 | Opus 5.5, Sol 6.1 | 40 cells each | $4.72 | development |
| Procurement, pay or test | 24 | six kinds × four | Opus 5.5, Sol 6.1 | 96 cells over two briefs | $9.10 | development |
| Procurement, pay or test, flash models | 24 | six kinds × four | Gemini 3.8 Flash, GPT-6 Luna (GLM's route refused) | 24 cells each, second brief | $0.21 | development |
| Procurement, record pack | 18 | which listing the record favours | Opus 5.5, Sol 6.1 | one cell a world each | | development |
| Data center development and signalling | 58 development + 58 fresh | deal or no deal; outside-option kind; counterpart style | Opus 5.5, Sol 6.1 | 2,456 negotiations, 2,417 valid | $119.30 | development; one declared test |
| Procurement v2 gate and pilot | 12 pilot worlds, two plays per model; one gate each | shared-source information value | Gemini 3.8 Flash, GPT-6 Luna | 50 cells | $0.2193 charged | stopped at sizing; no confirmatory |
| Data center confirmatory v2 | 80 admitted + 12 pilot | 72 deal / 8 no-deal; both tools isolated | Opus 5.5, Sol 6.1 | 640 negotiations, all valid and replayed | $55.41 | declared; Gate 3 passed, the others partial |
| Data center confirmatory v1 | 60 admitted + 12 pilot | 45 deal / 15 no-deal in confirmatory | Opus 5.5, Sol 6.1 | 1,176 model negotiations, 1,175 valid; 120 additional scripted dry runs | $74.41 | declared primaries; eight departures |
| Refund V2.5 | 180 distinct cases (seed 301) | eleven cohorts × four seats | deterministic reference profiles only | 816 trajectories | none | developmental release |
| Refund V2.1 | 6 cases | one policy seat | DeepSeek V4 Flash, Gemini 2.5 Flash Lite, GPT-5.6 Luna, Grok 4.3 | 480 cells (20 repeats of each case) | | descriptive |

Opus 5.5 ran through Claude Code and Sol 6.1 through the Codex CLI, without tools, at low
reasoning effort, one subprocess per action; neither CLI exposes a seed or temperature, and
both are recorded as unavailable rather than assumed. In the v1 confirmatory they were not equally isolated
from the operator's machine (Table H.1); v2 isolated both and probed their context (Section 5.1). Refund V2.5 makes no paid model call: its
release qualifies the environment with deterministic profiles in every seat and replays every
trajectory, so it measures the environment's conformance, not a model; with every seat scripted, its 816
trajectories are 174 distinct action sequences (four payments cases share one reference
trajectory).

### E.4 Results beyond the main text

#### Housing

v15, the reported comparison, is in Section 5.1 and Table 5.2. Its bundle also records 0 invalid seat-0 actions
in either model, and realized nets of $244.0 (Gemini) and $194.2 (Luna) beside the corrected-measure values.
The rest of this subsection is v14, the earlier comparison of three models (Table E.13).

**Table E.13. Housing v14, main pack; dollars per world, 95% intervals over worlds. The corrected block is a post-run reanalysis, reproduced from sealed records on 16 October; the declared measure remains visible.**

| | Gemini 3.8 Flash | GLM 5.3 Flash | GPT-6 Luna |
|---|---:|---:|---:|
| Complete worlds: all (favourite lemon / sound) | 260 (200 / 60) | 260 (200 / 60) | 260 (200 / 60) |
| *Declared measure, as frozen* | | | |
| Tenant net | +211 [+189, +233] | +137 [+111, +162] | +130 [+104, +156] |
| Minus the reference, favourite is a lemon | −101 [−120, −82] | −179 [−203, −154] | −207 [−229, −186] |
| Minus the reference, favourite is sound | −14 [−18, −9] | −76 [−116, −36] | −9 [−16, −2] |
| Minus a rule that inspects when the odds make it pay, then signs | +66 [+50, +82] | −8 [−30, +14] | −15 [−32, +2] |
| *Corrected measure, reanalysis* | | | |
| Tenant net | +213 [+191, +235] | +149 [+124, +175] | +147 [+121, +174] |
| Minus the reference, favourite is a lemon | −98 [−117, −80] | −164 [−189, −139] | −185 [−208, −162] |
| Minus the reference, favourite is sound | −14 [−18, −9] | −70 [−108, −32] | −9 [−16, −2] |
| Minus a rule that inspects when the odds make it pay, then signs | +68 [+52, +84] | +5 [−17, +27] | +3 [−15, +20] |

Under the analysis declared before any cell (three pairs, Holm; $50 minimum) Gemini leads GLM by
+74 [+53, +95] and Luna by +81 [+63, +98], and GLM and Luna do not differ (+7 [−16, +29]); the
40-world holdout agrees. Under the corrected measure, a reanalysis not
declared in advance, the leads are +63 [+43, +84] and +65 [+49, +82] and GLM minus Luna is +2
[−20, +24]: no declared verdict changes, but both lower bounds fall below $50. None reaches the reference, and
almost the whole shortfall is in worlds where the favourite listing is a lemon. The rule in the
last row of each block, scored after the runs, earns $145 a world; under either measure Gemini
beats it and GLM and Luna are not distinguishable from it.

On all 260 main-pack worlds, Gemini's refused cells taken from the declared fill, the models fall short of the reachable reference by −81 [−96, −66]
(Gemini), −155 [−177, −134] (GLM) and −162 [−181, −142] (Luna) a world; they keep 60%, 27% and
22% of what the reference earns where the favourite is a lemon, against 97%, 83% and 98% where it
is sound. The 40-world holdout points the same way (Gemini−GLM +105 [+46, +164], Gemini−Luna +65
[+23, +106], GLM−Luna −40 [−106, +26]). The original 1,800 published receipt rows comprise 1,764 scored completions and 36
operational-failure exclusions. Replay reconstructs each completed receipt's score, which totals
all six tenants; failure rows are verified as exclusions, not rescored (Appendix H.3). The seat-0 measure of Table E.13 was re-derived from the sealed event logs by the
derived analyses.
Scripted tenants played offline on every cell give the floor: passing earns $0, never inspecting and signing any
hold the listing's value if sound would cover −$80 a world (it signs lemons), and inspecting when the stated odds make it
pay then signing $145; the models beat the first two by $130 to $292 a world. Sixteen GLM cells
contain invalid tenant actions, almost all offers on a listing already leased; the bundle did not
report them, and no number moves. Thirty-six Gemini cells were refused when the provider account ran out of credit; the declared
bundle keeps them as typed missingness, and the tables use a fill run under its own identity, whose
twelve reruns of completed cells reproduced their outcomes. On the declared bundle alone (240 Gemini
worlds) the leads are +70 [+48, +92] and +80 [+62, +99] under the declared measure and +60 [+39, +81]
and +67 [+49, +84] under the corrected one. Under
the corrected measure (a blind signing valued at the posterior given inspections and informative
replies) 21 (GLM), 33 (Luna) and 3 (Gemini) signings change value: Gemini leads by +63 [+43, +84]
and +65 [+49, +82] (Holm p < 10⁻⁸), GLM−Luna is +2 [−20, +24], and each model minus the reference
becomes −79, −142 and −144. The published bundle is not edited.

Two CLI agents played the first 20 worlds of the main pack (40 cells each). Sol 6.1 earns $313
[225, 402] and Opus 5.5 $291 [198, 383] against the reference's $331 on those worlds; the
difference, +23 [−19, +64], is not established. Both equal the reference where the favourite is
sound ($427) and fall short where it is a lemon ($200 and $155 against $235).

The reference is reachable, not best. An exact best informed tenant (Appendix C) earns $307 a
world on the main pack when it knows the two landlord kinds and how each prices; the v14 subjects
were not told that, so part of their gap to it is information rather than judgment. v15 states that rule
in its brief and uses this tenant as the reference of its admission screen and of its gap rows (Section 5.1).

#### Procurement

**The earlier pack (`pay_or_test_v1`).** Section 5.1 reports the case's harder pack. The earlier pack,
which all four subjects played, has 24 worlds in six kinds; its quotes always arrive, its recorded
supplier always charges a premium, and its newcomers never share a source (Appendix A.2).

**Table E.14. The earlier Procurement pack, 24 worlds per subject; the share of the best policy's value (it earns $451 a world) each subject gives up and keeps, with 95% intervals over worlds. Always paying the premium, which never tests a newcomer, already keeps 83.3% (it gives up $75.19 a world), so the last row reports the decision itself: the share of the gap between that rule and the best policy each subject closes. All 96 losses and these intervals were reproduced on 16 October by a source-pinned derivation from replay-audited sealed actions; decision loss is separate from the original receipt scores.**

| | Sol 6.1 (Codex) | Opus 5.5 (Claude Code) | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| Share of the best policy's value given up | 0.2% [0.0, 0.5] | 1.2% [0.3, 2.4] | 16.7% [10.8, 22.5] | 16.5% [10.4, 22.8] |
| Share kept (always paying the premium: 83.3%) | 99.8% | 98.8% | 83.3% | 83.5% |
| Share of the premium-to-best gap closed | 98.6% [97.2, 99.7] | 92.8% [85.9, 98.4] | 0.0% [−34.9, 35.2] | 1.1% [−36.6, 37.9] |

The frontier agents (through their CLIs) are at the ceiling; most of what they lost on a first run
came from two rules the brief left unsaid, that a quote is final and that the average is the
criterion. That ceiling shows less than it seems: on this pack a rule that looks one test ahead comes
within 0.01% of the best policy's value, so near-perfect play shows that the agents avoid the listed
mistakes, not that they plan further ahead than one test. A v2 gate and pilot (50 cells, $0.22) found
little newcomer testing and required 326 to 3,464 worlds against a 96-world cap, so no confirmatory run
followed (Appendix F.4); the harder pack of Section 5.1 followed instead. The flash models give up what
always paying the premium gives up: their loss is in the worlds where a newcomer was worth testing.

**Further runs on the harder pack (Table E.15).** Section 5.1 reports the 20 declared worlds. The runs below were a
development pilot and three diagnostics, each declared before its plays; none tests a claim.

**Table E.15. Procurement's harder pack: runs beyond Table 5.3. Shares are of the gap between paying the premium and the best policy, as means over worlds (each world the mean of its plays).**

| Run | Worlds and plays | Sol 6.1 | Opus 5.5 | Exact rules on the same worlds |
|---|---|---|---|---|
| Development pilot | 6 worlds, two plays each | 50% [27, 71] (bootstrap) | 0% in all 12 plays | one-newcomer rule 0%, shortcut 8%, two newcomers 84% |
| The declared worlds at the earlier pack's cohort odds (diagnostic) | 20 worlds, one play each | 59% [19, 100], median 83%; one play deferred and bought nothing | 0% in all 20 plays | one-newcomer rule 58%, shortcut 62%, two newcomers 90% |
| A brief corrected for four wording defects (diagnostic) | the 20 declared worlds, two plays each | no change shown: +7.8 points [−5.6, +21.2] | touched no newcomer in 40 plays | as Table 5.3 |
| How likely a newcomer is to be sound once another of its kind has passed or failed a sample, with and without a clean quote of its own first, asked with no play (diagnostic) | 3 worlds, 3 questions, asked twice | 18 of 18 within 0.05 of the exact value | 18 of 18 within 0.05; earlier attempts, whose schema asked for the model's working, were refused | |

A further diagnostic, declared before its plays, tried to certify Gate 1's measured headroom with a frozen control that
tests. GPT-6 Luna at high reasoning was chosen on the pilot worlds because it tested a newcomer in 5 of 12 plays (Gemini
3.8 Flash at high reasoning tested in none). On the declared worlds, three plays each, it tested in 26 of 60 plays but
closed −34% of the gap on average, worse than paying the premium. Against it 3 worlds score the same at every seed and 18
are matched by a screened rule (the kind-blind shortcut in 14, the one-step rule in 4), so only 2 of 20 pass: the
control is weaker than the shortcut, which says more about the control than about the worlds. Beside it, and not
declared, Sol's better play of each world beats every screened rule in 11 of 20.

The pilot's go rule sized a comparison of the two models past the 96-world cap, so the declared test was on Sol
alone. In the pilot worlds the kind-blind shortcut closes 8% against Sol's 50%; on the declared worlds it closes
33% against Sol's 35%. No comparison with it was declared.

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
before any call.

#### Data center

The following counterpart and probing results use the development packs. Which model sits in which seat changes the pair's total by +3 [−11, +18] ($ thousands a world);
Sol is ahead of Opus in 51 of 52 worlds in each seat head to head. Table E.3 gives every
counterpart; Appendix B gives each style's rule and parameters.

**Table E.3. Development results: Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

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
  earned 40. Price only tests whether the model fixes the clauses itself: as integrator, Opus reached
  the best clause set in 0 of 52 worlds and lost 15 deals; Sol reached it in 10.
- *A probing counterpart* (20 worlds, each model in each seat against the prober and against a
  silent script; 158 of 160 valid, $7.92). Both sides' briefs carried a planted confidential name
  and figure that change no payoff, and the prober's notes asked for the other side's costs and
  for the confidential item. Neither model disclosed a confidential item in any negotiation. Asked
  for its own costs, Sol as integrator stated its pre-staging cost in 18 of 19 negotiations, and
  Opus in none of 40; nothing in the brief says a side's own costs are confidential, and no model
  stated a false cost. Asking changed no one's earnings measurably (−15 [−86, +57], +4 [−18,
  +25], +1 [−25, +26], +3 [−15, +22]); the intervals are wide, so this does not show that
  disclosure is harmless. Unprompted, across 3,492 notes, no model stated its own
  private cost; in 114 negotiations a note called a price final or a floor, and in 112 of them the
  stated number was better for the speaker than its true limit.

**A declared test.** Looking back over these runs suggested two signals: Opus's counter-offer
price seemed to follow its private value, and Sol's clause requests seemed to follow its risk
charge. The claims, measures, exclusions and six primary predictions were committed before any
run, on the fresh worlds of Appendix E.2. Sol asks for 1.82 [1.23, 2.40] more protective clauses of six
under the high charge (supported, Holm p < 0.001), 1.58 [0.95, 2.22] more than Opus does;
at the true charge, the clauses Sol chose for its type are worth about +120k [+83k, +156k] a world
more joint value than those it chose for the other type (a secondary measure; joint value is the
pair's surplus, not Sol's own earnings).
Opus's price pass-through is −0.07 [−0.18, +0.05], not supported; the earlier 0.52 came from
counter-offers only, compared across worlds, and was withdrawn. The fitted reading counterparts yielded +2k [−14k, +17k] and −8k [−42k, +26k], but their
rules came from the confounded look-back data. The Opus price reader used the
withdrawn 0.52 slope, so this tests a misspecified reader, not a well-fitted reader's ability
to exploit Opus. The within-world price result remains unsupported; reader-effect estimates
cannot establish that disclosure is harmless.

Of 2,456 negotiations, 2,417 are valid. Every failure is a CLI service error; the original
bundles keep them as missing, and 16 were played again under separate identities by an explicit, recorded
decision.

**The earlier declared comparison (v1).** Before v2, a comparison was declared on 60 admitted worlds (from 2,729
scanned), 45 with a mutually beneficial deal. It differs from v2 in three ways: the two command-line tools were not
equally isolated, the client's brief did not state its walk-away point, and worlds were not screened for the
integrator's room over a price-only rule. v1 and v2 are not pooled.

**Table E.16. Data center v1 (14 October): Sol 6.1 (Codex) and Opus 5.5 (Claude Code). Differences in a seat's earnings above its outside option, at true costs, on the 45 deal worlds, in percentage points of the value available in a deal ($322k a world); intervals are 95%, with Holm correction across the campaign's primaries. Eight documented departures and a partial Gate 5 verdict (Appendix F.5).**

| Primary contrast | Worlds | Estimate [95% interval] | Holm p |
|---|---:|---|---:|
| Head to head: Sol minus Opus earnings, seat-averaged | 45 deal | +59.1 [46.0, 72.1] | 3.2e-11 |
| Firm population: Sol minus Opus earnings, seat-averaged | 45 deal | +8.2 [3.3, 13.2] | 0.0017 |
| Client signs below its walk-away point: Opus / Sol | all 60 | 45% vs 5% (27 and 3 of 60) | 2.4e-7 |

Sol's lead against the firm population is detectable but smaller than the plan's minimum of 15.5 points ($50k;
the 98.3% interval is [2.1, 14.3]). Across v1's pilot and three arms, 1,175 of 1,176 negotiations are valid ($74.41
list price). The two tools were not equally isolated: Codex's context listed eight of the operator's own skills, two
described in benchmark and evaluation terms, and Claude Code's listed none (Table H.1). Every v1 Sol-versus-Opus
contrast carries that difference. With the walk-away point stated in v2, neither model signed below it as client.

Against the firm population, v1's joint loss was led by fees (69.9% of Sol's $103.4k a world and 40.3% of Opus's
$70.8k, all 60 worlds, seats averaged), and Opus's next largest part (29.5%) was harmful agreements: in the 15
worlds where no agreement beats both outside options, it signed anyway. Table E.17 gives v1's joint loss by
pairing, and Appendix E.9 its replay at other fees.

**Table E.17. Data center v1: joint loss by pairing ($ thousands per world, all 60 worlds).**

| Integrator / client | Inferior clauses | Harmful agreement | Missed deal | Redline fees | Total |
|---|---:|---:|---:|---:|---:|
| Opus / Sol | 9.3 | 1.2 | 3.7 | 63.3 | 77.5 |
| Sol / Opus | 22.6 | 34.8 | 25.2 | 44.2 | 126.8 |
| Opus / firm | 2.2 | 0.0 | 12.2 | 30.0 | 44.4 |
| Sol / firm | 1.1 | 0.0 | 29.1 | 60.8 | 91.0 |
| Firm / Opus | 15.5 | 41.8 | 12.9 | 27.1 | 97.2 |
| Firm / Sol | 14.3 | 4.0 | 13.8 | 83.8 | 115.8 |

### E.5 Failure classes: rules and full tables

**Table E.4. The shared classes.**

| Class | What happened |
|---|---|
| Information not acquired | acted without information worth acquiring: signed an uninspected listing whose quality nothing it knew had settled; paid the premium or awarded the recorded supplier where the best policy tested a newcomer; decided before a required fact |
| Acted contrary to information held | the trajectory contains information (an inspection result, a landlord's reply, a sample result, revealed facts) under which the reference acts differently, and the subject did not: signed a hold that, under the landlords' pricing rule, only a lemon's landlord offers, at a rent above a lemon's value; awarded a supplier its own test showed bad; stopped after one bad newcomer where another test was worth it; tested the wrong newcomer or in the wrong order; a decision the answer key contradicts after every required fact was revealed. The class records that the information was in the trajectory, not that the subject could interpret it |
| Worse terms | agreed to a worse deal than one available, with no protocol error: a verified listing worth less net of rent than the reference's; a worse award on a qualified supplier; a clause set worth less to the pair than the best one |
| Commitment error | signed what it should have refused or refused what it should have signed: no lease where the reference leased; deferred where an award or a test was worth more; no deal where one was available |
| Interaction cost | the charge for moves the case prices: redline fees after the opening; inquiries, counter-offers and checks; inspection spend above the reference's on a lease of the same value. Any gain such a move brings appears in another class (a better clause set is smaller worse-terms loss), so this class prices the moves and does not judge them |
| Procedure and format | an action the environment rejected or could not parse; a fact request the case rejects; a format the verifier rejects |
| Operational | a cell with no measurement; counted, never scored |

The priority order makes the decomposition an accounting identity, not a causal attribution.

**Rules per case.** *Housing:* the unit is the cell (one world, one landlord kind), the shortfall is
the reachable reference's net minus the tenant's at v15's primary measure (the reply-conditioned measure), and the rules apply in
the order procedure, contrary to information held, not acquired, commitment, worse terms,
interaction cost. A known lemon
signed at a rent its lemon value covers is judged on terms, as the reference does the same.
Revealed-lemon signings count as contrary to information held; v15's brief states how landlords
price, so the acceptance that reveals a lemon follows from a stated rule. The rules are v14's
(`housing_v15.py`, 5522d543); each reads seat 0's decisions from v15's seat-0 receipts, the reference is
`inspect_lowball` scored as v15's scorer scores it, and every cell's gap reproduces the published
v15 analysis. v14's classes (Gemini 78.9, GLM 142.3, Luna 144.3 $ a world) stay in the source package. *Procurement:*
the unit is the action, and each action's loss against the best policy (which sums to the decision
loss) goes to a class by what the action did; a request to the recorded supplier counts as not
acquired only when the episode never tests a newcomer, and as contrary to information held
otherwise. *Data center:* the
unit is each part of a negotiation's grade: no deal is a commitment error (labelled by the side that
walked); allocation loss in a world with positive available surplus is worse terms, while allocation loss in a world without positive available surplus is a harmful agreement (commitment error). Redline fees are interaction cost. Figure 5.2c separates harmful agreements from missed beneficial deals. Signing below one's own walk-away value is counted separately: the individual loss is not an additive joint-loss component, although the same agreement may also destroy joint value. *Refund:* the published gap decomposition's parts map onto the classes
(deciding before a required fact to not acquired, a wrong decision to contrary to information held, re-asked or unknown
facts and the null-method format to procedure).

**Interpreting negotiation costs.** A redline that improves the final agreement's joint value by
$100k while costing $25k reduces total shortfall by $75k: allocation loss falls by $100k and
interaction cost rises by $25k. The score therefore credits improvements net of their cost. The
full-information reference knows both private types and can propose the best agreement in the
free opening move. Its advantage includes negotiation costs that agents with limited information
may need to incur; the decomposition does not identify which costs were avoidable. It also does
not establish robustness to the chosen $25k fee per additional redline. Appendix E.9 tests
scoring sensitivity by replaying the same actions at alternative fees; measuring behavioral
adaptation would require new model runs under declared fee settings.

**Table E.5. Housing and Procurement, every subject ($ per world; Housing v15 on the 260 main worlds of Table 5.2, GLM from its declared addendum; Procurement on the 20 declared worlds of Table 5.3, each world the mean of its two plays).**

| Class | Housing Gemini | Housing Luna | Housing GLM (addendum) | Proc. Sol | Proc. Opus | Proc. Gemini | Proc. Luna |
|---|---:|---:|---:|---:|---:|---:|---:|
| Information not acquired | −0.2 | 14.9 | 18.9 | 17.5 | 51.0 | 49.4 | 55.4 |
| Acted contrary to information held | 1.9 | 22.2 | 49.6 | 13.9 | 0 | 0 | 0 |
| Worse terms | 40.7 | 54.3 | 40.1 | 0 | 0 | 0 | 0.5 |
| Commitment error | 8.9 | 8.6 | 7.2 | 0 | 0 | 0 | 0 |
| Interaction cost | −0.3 | −0.1 | −0.2 | 1.1 | 0.2 | 1.9 | 2.2 |
| Procedure and format | 0 | 0 | 11.7 | 0 | 0 | 0 | 0 |
| Total | 51.1 | 99.9 | 127.3 | 32.5 | 51.2 | 51.2 | 58.1 |

Housing's totals reproduce the published v15 differences from `inspect_lowball` (51.13 and 99.92 $ a world; GLM's addendum row R3, 127.32), and every one of the 520 main cells per subject completed, so no world is excluded. Main-world means average both landlord arms within a world. Negative amounts are retained when the subject beats the reference. The inspection-cost row is a residual after earlier classes; inspection costs inside other classes are not counted again.

**Table E.6. Data center development ($k joint value lost per deal world) and Refund (points of cells unresolved).**

| Class | DC Sol int. × Opus | DC Opus int. × Sol | DC Sol × firm | DC Opus × firm | Refund DeepSeek | Refund Gemini 2.5 FL | Refund GPT-5.6 Luna | Refund Grok |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Information not acquired | — | — | — | — | 44.2 | 0 | 15.0 | 29.2 |
| Acted contrary to information held | — | — | — | — | 0 | 0 | 0 | 0.8 |
| Worse terms | 35.4 | 12.2 | 9.1 | 4.8 | 0 | 0 | 0 | 0 |
| Commitment error | 0 | 0 | 32.0 | 6.9 | — | — | — | — |
| Interaction cost | 46.2 | 66.3 | 80.2 | 29.8 | — | — | — | — |
| Procedure and format | 0 | 0 | 0 | 0 | 5.8 | 98.3 | 5.8 | 17.5 |
| Total | 81.5 | 78.6 | 121.3 | 41.5 | 50.0 | 98.3 | 20.8 | 47.5 |

In these development runs, 7 of Sol's 8 lost deals against the firm script were the script walking from Sol's last offer.
Signing below one's own walk-away point, not in the table: Opus as client 12 of 52 worlds against Sol
(it proposed the losing terms itself in 4) and 2 against the firm script; Sol as client 1 against the
firm script; neither as integrator.

### E.6 Two frontier agents across three cases

**Table E.7. Development comparisons of Opus 5.5 and Sol 6.1 on the three cases both played; Data-center confirmatory results are in Table 5.4 (v2) and Table E.16 (v1).**

| Case (worlds) | Measure | Opus 5.5 | Sol 6.1 | Sol relative to Opus | Reference |
|---|---|---:|---:|---:|---|
| Housing (20) | tenant net per world | 291 [198, 383] | 313 [225, 402] | +23 [−19, +64] | scripted reference 331 |
| Housing, favourite a lemon (10) | tenant net per world | 155 | 200 | not tested | scripted reference 235 |
| Procurement pay-or-test (24) | given up per world | 5.4 [1.2, 10.6] | 1.0 [0.2, 2.1] | 4.4 [0.6, 9.0] less given up | best policy gives up 0 |
| Procurement, record pack (18) | worlds solved | 18 | 16 | regret −20 [−48, +7] (Opus lower) | informed policy 18 |
| Data center development, firm population (52) | earns, integrator / client ($k) | 122 / 107 | 139 / 130 | +17 [−10, +44] / +23 [−2, +48] | first-offer stand-in 122 / 114 |
| Data center development, head to head (52) | earns, integrator / client ($k) | 60 / 25 | 308 / 276 | +248 / +251 | |

### E.7 Current shortfall panels: scope and uncertainty

Figure 5.2 is descriptive accounting after the runs, not an additional declared test. Its
Data-center panel uses all 80 admitted worlds of v2, including 8 with no positive available surplus;
Table 5.4's earnings contrasts use the 72 deal worlds. Both focal roles receive equal weight
within each world, the integrator's two plays against the firm client first averaged. Individual
below-walk-away signings are not added to joint loss: as integrator against the firm client, Opus
signed below its outside option in 2 of 160 plays and Sol in none; as client neither did in 80.
Table E.6 preserves the earlier development decomposition on its 52 deal worlds, and Table E.17
v1's by pairing.

**Table E.8. Data-center joint loss by pairing in v2 ($ thousands per world, all 80 worlds; the integrator's two plays against the firm client averaged within each world).**

| Integrator / client | Inferior clauses | Harmful agreement | Missed deal | Redline fees | Total |
|---|---:|---:|---:|---:|---:|
| Opus / Sol | 12.6 | 0.0 | 24.3 | 74.4 | 111.4 |
| Sol / Opus | 22.4 | 0.0 | 26.1 | 68.1 | 116.7 |
| Opus / firm | 2.2 | 0.0 | 9.1 | 40.0 | 51.3 |
| Sol / firm | 1.7 | 0.0 | 45.9 | 73.9 | 121.6 |
| Firm / Opus | 17.0 | 0.0 | 48.3 | 50.6 | 115.9 |
| Firm / Sol | 12.4 | 0.0 | 53.6 | 92.8 | 158.8 |

**Table E.9. Distribution of total shortfall for the subjects in Figure 5.2 (each case's own units).**

| Case / subject | Units (n) | Mean [95% interval] | Median [Q1, Q3] | Zero / negative units |
|---|---:|---|---|---|
| Housing: Gemini 3.8 Flash | 260 | 51.1 [38.3, 63.9] | 29.9 [0.0, 98.3] | 60 / 45 |
| Housing: GPT-6 Luna | 260 | 99.9 [83.8, 116.0] | 72.1 [0.0, 167.6] | 46 / 32 |
| Housing: GLM 5.3 Flash (addendum) | 260 | 127.3 [105.2, 149.4] | 79.9 [0.0, 212.8] | 36 / 39 |
| Procurement: Sol 6.1 | 20 | 32.5 [23.8, 41.3] | 33.3 [21.5, 48.7] | 0 / 0 |
| Procurement: GPT-6 Luna | 20 | 58.1 [52.3, 63.9] | 57.2 [50.4, 67.1] | 0 / 0 |
| Data center: Opus 5.5 | 80 | 83.6 [68.8, 98.4] | 57.2 [27.8, 137.3] | 0 / 0 |
| Data center: Sol 6.1 | 80 | 140.2 [120.6, 159.7] | 117.3 [87.5, 189.8] | 4 / 0 |
| Refund: GPT-5.6 Luna | 6 | 20.8 [-1.0, 42.7] | 20.0 [3.8, 28.8] | 2 / 0 |
| Refund: Gemini 2.5 Flash Lite | 6 | 98.3 [94.0, 102.6] | 100.0 [100.0, 100.0] | 0 / 0 |

Intervals here are Student t intervals over independent worlds (Housing after averaging arms;
Data center after averaging focal roles), or over the six fixed Refund cases after averaging
20 cells per case. They describe variation in these panels and do not establish a model ranking
or field-population coverage. They are newly derived descriptive intervals, not replacements
for the campaigns' declared analyses. A Refund interval can exceed the score's 0–100 bounds;
it is left untruncated to expose the weakness of an approximation with six fixed cases.
Housing, Procurement and Data center have one retained run per world and condition, so
run-to-run variance is unmeasured. Refund has repeated cells within fixed cases; its per-case
outcome distributions are retained in the derived evidence. The source package includes
component-level intervals, distributions, per-world amounts and input digests in
`analysis_evidence/shortfall_panels/panels.json`, with a provider-free reproduction script.

### E.8 Exact values for Figure 5.2

The figure uses the same estimates below. Components retain each case's native units and
classification rules; the figure adds no new analysis or cross-case aggregate.

**Table E.10. Shortfall by case. Housing uses v15 (Table 5.2) under its primary measure; Data center uses v2, the comparison of Table 5.4; Procurement uses the 20 declared worlds of Table 5.3. Refund retains its development panel.**

**(a) Housing**

$ per main world below the reachable scripted reference (`inspect_lowball`); v15, measure v2.

| Component | Gemini 3.8 Flash | GPT-6 Luna | GLM 5.3 Flash (addendum A) |
|---|---:|---:|---:|
| Information not acquired | −0.2 | 14.9 | 18.9 |
| Contrary to held information | 1.9 | 22.2 | 49.6 |
| Worse lease terms | 40.7 | 54.3 | 40.1 |
| Lease commitment error | 8.9 | 8.6 | 7.2 |
| Procedure or format | 0.0 | 0.0 | 11.7 |
| Inspection cost | −0.3 | −0.1 | −0.2 |
| **Total shortfall** | **51.1** | **99.9** | **127.3** |

Two landlord arms averaged within each of the 260 main worlds; no cell is missing. GLM played in a declared addendum outside v15's contrasts. Its procedure losses are actions the environment refused, chiefly malformed commits ($5.7 a world, 14 cells) and offers on listings already taken ($2.1, 5 cells). Negative amounts mean the subject did better than the reference in that class and are not drawn in Figure 5.2.

**(b) Procurement**

$ per world below the best policy given available information; the 20 declared worlds of Table 5.3, two plays each.

| Component | Sol 6.1 | Opus 5.5 | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| Information not acquired | 17.5 | 51.0 | 49.4 | 55.4 |
| Contrary to held information | 13.9 | 0.0 | 0.0 | 0.0 |
| Worse terms | 0.0 | 0.0 | 0.0 | 0.5 |
| Award checks | 1.1 | 0.2 | 1.9 | 2.2 |
| **Total shortfall** | **32.5** | **51.2** | **51.2** | **58.1** |

All four subjects, each world the mean of its two plays. Sol uses Codex; Opus uses Claude Code; Gemini and Luna use OpenRouter. Decision loss re-derived from every play's replayed trace, and every world matched against the read-outs. The declared rules file an award's whole loss under information not acquired when the award came before a worthwhile newcomer test, including the part from a worse quantity. For Luna, which ordered 50 units where 55 was best in 15 of 40 plays, that is $6.33 a world; split into its timing and terms parts, Luna's worse terms would be $6.85, its whole loss beyond paying the premium. The other three subjects have no such awards.

**(c) Data center**

$ thousands of joint value lost to the full-information bound; v2, against the firm counterparts.

| Component | Opus 5.5 | Sol 6.1 |
|---|---:|---:|
| Inferior contract clauses | 9.6 | 7.1 |
| Harmful agreement | 0.0 | 0.0 |
| Missed beneficial deal | 28.7 | 49.7 |
| Redline fees | 45.3 | 83.4 |
| **Total shortfall** | **83.6** | **140.2** |

All 80 worlds; both focal roles averaged within world. Joint outcomes include both parties' actions.

**(d) Refund**

Percentage points below full resolution under the verifier; V2.1.

| Component | GPT-5.6 Luna | Gemini 2.5 Flash Lite |
|---|---:|---:|
| Required facts skipped | 15.0 | 0.0 |
| Procedure or format | 5.8 | 98.3 |
| **Total shortfall** | **20.8** | **98.3** |

120 cells per model, averaged within each of six fixed cases and then across cases.

Rows that are zero for every displayed subject are omitted; rounded components may not add to
rounded totals. Below-walk-away signings are a separate individual outcome: in v2 neither model
signed below its walk-away value as client, against the firm integrator or head to head (0 of 80
each), and as integrator against the firm client Opus signed below its outside option in 2 of 160
plays and Sol in none. v1's counts are in Table E.16.

### E.9 Negotiation fees in v1: fixed-action sensitivity

We replayed all 240 valid firm-population negotiations of v1 (Table E.16; 60 worlds, two models, two focal
seats) at six fees per paid redline: $0, $5k, $12.5k, $25k, $50k and $100k. All original final
states and six score leaves matched the saved states and receipts. The 1,440 fee-specific
trajectories used the native transition and scoring functions, holding offers, clauses, notes,
signatures and walks fixed. This is exploratory analysis after the runs, not another declared
test or a model rerun. The free opening move remains free. v2 declared a smaller replay of the same kind
(Section 5.2).

The samples answer different questions. v1's joint loss covers all 60 worlds; its declared
earnings contrast (Table E.16) uses the 45 worlds with positive available joint surplus.
"Deal-feasible" describes those worlds, including negotiations that ended without agreement;
it does not select only signed contracts. Means first average both focal seats within a world,
then worlds. The independent unit is the world, not each correlated seat observation.

**Table E.11. Fee sensitivity on the 45 deal-feasible worlds ($ thousands per world; fixed actions). Sol earnings lead is Sol minus Opus against the firm population. Lower joint loss is better; a positive earnings lead favors Sol.**

| Fee per redline | Sol joint loss | Opus joint loss | Sol earnings lead |
|---|---:|---:|---:|
| 0 | 38.9 | 28.5 | +54.8 |
| 5 | 56.0 | 35.6 | +49.1 |
| 12.5 | 81.7 | 46.2 | +40.6 |
| 25 | 124.4 | 63.8 | +26.4 |
| 50 | 210.0 | 99.1 | -1.9 |
| 100 | 381.1 | 169.6 | -58.6 |

For these 45 worlds, fees amplify Sol's joint-loss disadvantage but do not create it: Opus
retains lower loss at zero fees. Sol's own earnings lead instead grows when fees are removed.
With behavior fixed, earnings depend linearly on the fee and are equal at approximately $48.3k
per redline. This threshold describes the recorded actions, not an optimal fee or how either
agent would respond to a changed fee.

**Table E.12. Joint-loss sensitivity across all 60 worlds ($ thousands per world; fixed actions). This is v1's full population, including 15 worlds without positive available joint surplus.**

| Fee per redline | Sol joint loss | Opus joint loss |
|---|---:|---:|
| 0 | 31.1 | 42.3 |
| 5 | 45.6 | 48.0 |
| 12.5 | 67.3 | 56.6 |
| 25 | 103.4 | 70.8 |
| 50 | 175.7 | 99.4 |
| 100 | 320.3 | 156.5 |

Across all 60 worlds, fees contribute 69.9% of Sol's and 40.3% of Opus's total joint loss
at $25k. Here the joint-loss ranking reverses without fees, with equality near $6.4k per
redline. The 45-world result therefore cannot establish a fee-independent ranking for the
full pack. On the 45-world subset, the corresponding fee shares are 68.8% and 55.3%.

**Useful changes and limits.** Among model-authored paid redlines in the 45 deal-feasible
worlds, 23 of Sol's 150 and 5 of Opus's 48 increased immediate full-information clause value
by more than the $25k fee. One Sol redline improved clause value by $87.5k for a $62.5k net
improvement. These are local comparisons: edits may later be undone, and negotiations may
remain unsigned. Price concessions and the information value of negotiation are not captured
by this clause-value count. Fee shares include both parties' fees, whereas these counts include
only the focal model's edits. The full-information reference advantage remains, and this
analysis neither validates the fee's empirical calibration nor measures adaptation to it.

The source package retains the supplied analysis, its reproduced outputs, input hashes and
the concrete move in `analysis_evidence/datacenter_fee_sensitivity/`. The reproduction uses
the retained campaign logs; the compact package does not include those complete raw logs.

## Appendix F. Quality control in detail

This appendix describes only checks that were built and applied to the four cases. Two caveats
apply throughout. The initial QC profiles and reference-run tests followed development; the
agreement confirmatory followed its profile and provider-free dry run. And rules of the QC standard that were not
applied to these cases are not described here.

### F.1 Profiles and gates

The QC standard defines six gates and the rule that a changed bound input reopens them; a repository
test rejects a registered family without a profile. Each of the four current designs
now has a section in its family's profile with a typed status and a blocker per gate (Table F.1),
and none passes Gates 1 to 5: Housing v14 is `partial` throughout (v15, below, passes four); Procurement's harder pack,
used in Table 5.3, passes Gates 0, 2, 3 and 5 and is `partial` at Gates 1 and 4 (profile section 8.2). Its environment
and its registration with the runtime reached the main branch on 20 October, the registration on the owner's override
without a non-author review. Its 12 published bundles replay through the runtime's command line, 432 of 432 receipts,
among them 100 from five scripted baselines played on the declared worlds with no model, each scoring as the reference
scores its moves. Gate 4 stays `partial` because the command-line subjects take no seed. Gate 1's measured headroom was then tried with a frozen control that tests,
declared before its plays: it tested but lost to the kind-blind shortcut, so only 2 of the 20 declared worlds pass
that check and the gate stays `partial` (Appendix E.4). The earlier pay-or-test v1 pack (Table E.14) fails Gates 1 and 3; v2 passes
the scripted Gate 3 checks but remains `partial` at Gate 1 after its pilot stopped at sizing (Appendix F.4). The agreement's development
packs fail Gate 1 because admission and type assignment were confounded. Its first confirmatory (v1) used
the admitted pack, still `partial` at Gate 1 because of the client-seat construct limit and
incomplete measured-headroom qualification (Appendix F.2); Refund V2.5 fails Gate 3 on its
lower controls (Appendix F.4).

Housing v15 was declared and run after these profiles were first written. It passes Gates 1, 2, 3 and 5 and is
`partial` at Gate 4:
- **Gate 1.** Its pack is screened for headroom, and its holdout changes a mechanism.
- **Gate 2.** A golden-receipt bundle was sealed through its builder, and all 1,720 cells replay.
- **Gate 3.** Its beatability rule was declared before results, both models pass it, and its receipts score the
  deciding tenant.
- **Gate 5.** Its sizing record and A/A arm preceded the freeze.
- **Gate 4, partial.** The declared one-call profile probe ran only after the freeze. It found structured output
  working and both reasoning tiers in effect: every sealed call's raw response carries the provider's reasoning
  count, which the kernel's OpenRouter client does not copy into its own field.

The agreement's v2 confirmatory (Table 5.4) passes Gate 3 for its integrator seat: the price-only rule leaves room
in every deal world by construction, the best informed integrator earns far more than either model, and the pack
separates the subjects. It is partial at Gates 0, 1, 2, 4 and 5. Its registry row awaits a non-author review and its
code is not on the main branch, so replay through the runtime's command line has not run; no frozen control has
screened its worlds; and the client seat keeps its construct limit. Through the environment's hooks the
full-information pair loses nothing in all 80 of its worlds.

The identity rule was applied: Housing's 36 refused cells ran later under their own
identity, and Procurement's corrected schema ran under new identities.

**Table F.1. Benchmark QC gates.**

| Gate | Question | Stops when | In the four cases |
|---|---|---|---|
| 0. Profile | Is there a place to record each gate's verdict? | the family has no QC profile | an earlier Procurement design's construct check found a public-price rule beating the model by $28.50 a world; with no profile, the verdict was read as a campaign finding and lost. The profiles followed initial development; the agreement confirmatory followed its profile |
| 1. Task distribution | Are the worlds valid, distinct, split and informative? | an unverified bound, duplicates across clusters, development and holdout overlap, no measured headroom | Housing v14 admits a seed on the tenant's own structure and reads quality afterwards, with a holdout from a disjoint seed range; pay-or-test v1 fails: a rule reading only public information solves 23 of 24 worlds; v2 remains `partial`: scripted headroom is shown, but a 50-cell gate/pilot found almost no newcomer testing and stopped at sizing |
| 2. Environment and verifier | Do actions change the intended state, and is every score rebuilt from sealed evidence? | invalid actions mutate state, an oracle disagrees, hidden state leaks, replay differs | Housing v14 has 1,764 scored completions and 36 failure exclusions: completed receipt scores replay from sealed events, and failure rows are verified as exclusions; the headline measure is computed outside the receipts. Procurement's harder pack passes: its 12 published bundles replay through the runtime's command line, 432 of 432 receipts |
| 3. Construct and baselines | Does a better-informed policy do better, and do shortcuts lose? | stronger and weaker policies indistinguishable, a shortcut drives the score | pay-or-test v1 fails: Procurement's fixed rules give up $45.7 to $146.1 a world, but a one-step comparison reaches the best policy to within $0.06; v2, built after the runs, passes for scripted policies: every screened rule, the one-step rule included, gives up at least $10 in every world; Refund V2.5 fails: under a rule committed before its controls ran, naive controls come too close to the reference in three of four seats |
| 4. Attribution and controls | Does the result support the attribution it claims? | an undeclared control changes, the matrix is incomplete, the block cannot carry the claim | the three v14 identities differ in model and route and also in reasoning tier, sampling and cost ceiling, a declared choice the contract did not state; data-center claims name their counterparts |
| 5. Confirmatory reliability and publication | Was the comparison sized, frozen and executed without tuning on outcomes? | incomplete pilot, a frozen control changed, selective missingness, a guardrail no behaviour can fail | Housing v14 has no sealed sizing record. The agreement confirmatory completed pilot, sizing, freeze and execution; its status is `partial` pending closure of analysis-digest and exclusion-verification discrepancies (F.5). Procurement's declared test passes: its plan preceded every play, it ran as declared, and its bundles are published and replay |

### F.2 Checks applied to the four cases

**Table F.2. What each kind of verifier must be shown to do, and how the four cases show it.**

| Kind | Must be shown | How it is shown in the four cases |
|---|---|---|
| Answer | the key is correct and complete for every admitted case | Refund: admission requires the policy's public compiler to reproduce the hand-written reference resolution on every case |
| Rule | every rule is stated to the subject, and each check fails on a counterexample | Procurement tests most of the rules its brief states against the environment; the agreement case tests its stated walk-away cost; two checks (the agreement's oracle grade and Housing's ceiling) have mutation tests; a rule left unstated or a schema that disagrees with its parser is a defect |
| Value | the reference agrees with the environment, and a simple rule does not already match it | each reference is played on every world (below); Procurement computed its one-step rule before play, and that rule matches its best policy |
| Relative | the counterparts are named and the gap is reported per counterpart | the data-center counterpart table (Table E.3) |
| Rubric | the rater agrees with people and resists gaming | not used |

- **Regeneration.** In all four cases a test reproduces every committed pack byte for byte from
  its generator and seeds.
- **Reference run on every world.** Tests following initial development play each reference through the
  real environment and verifier with no model: the Housing reference and a full-information tenant
  on all 600 v14 cells, reproducing the published per-cell values and reaching the ceiling in
  every cell (offline, against the same functions that wrote the bundle); Procurement's best policy
  equals the environment's average over the 27 type profiles in all 24 worlds; the data-center
  oracle pair loses nothing in all 116 worlds of both development packs, against an optimum the test computes
  independently; a 120-negotiation scripted dry run covered all 60 admitted agreement worlds
  before the confirmatory; Refund V2.5's release requires the reference to take full credit on every case.
- **Replay.** The kernel's replay recomputes each receipt's own score from its sealed events with
  no provider call: the 1,764 completed Housing v14 receipts (the other 36 rows are verified
  operational-failure exclusions); development agreement receipts replayed in-line;
  all 1,295 scored receipts from the agreement dry run, pilot and three confirmatory arms
  replayed offline. One failure receipt was checked separately for digest and seal because
  the pinned driver cannot classify exclusions. The
  procurement panels' receipts, in-line; and Refund V2.5's 816 provider-free trajectories
  (unpublished; 174 are distinct). The certificate does not cover two headline measures.
  Housing's seat-0 measure is case code over each cell's outcome, the receipts' own score totals
  all six tenants, and the measure was re-derived from the sealed event logs by the
  derived analyses of Table 5.2, re-extracted and regenerated exactly on 16 October.
  Procurement's original report read an unsealed action list through an unpinned reference.
  The 16 October reanalysis audits all 144 receipts (96 final-brief and 48 earlier-brief), reads
  parsed actions from their sealed logs, and pins the extraction, reference, report and case inputs.
  Every per-world loss and the Table E.14 intervals reproduce. This is a separately verified
  derivation; decision loss has not been inserted into the original receipts. The Housing
  receipts also name the model for the five tenant seats a script played; the true seat map is in
  an unsealed log.
- **Admission before types.** After development and before the confirmatory, the data-center agreement gained a pack admitted by
  its own rules: 60 worlds from 2,729 scanned, each admitted on its public parameters and the type
  prior while its hidden charge does not yet exist, then given types drawn independently of its
  cell (χ² p 0.46; the same test rejects the development packs' pattern). Tests play every
  shortcut through the environment for every type pair and confirm the loss admission assigned,
  and the oracle pair loses nothing in all 60 worlds. A separate 12-world pilot and the
  60-world confirmatory (v1) have run; the pilot supplied the sealed sizing record. v2's pack
  applies the same rules to fresh seeds and adds a headroom screen against one control, the
  price-only rule (80 worlds admitted of 5,436 scanned). This is evidence of play and variance,
  not a completed headroom verdict across all controls. The client seat still fails the
  dependence-on-counterpart-type rule.
- **Visibility.** Named hidden fields are tested absent from the observations in Housing,
  Procurement and Refund; the agreement case has no such test.
- **Paired plans.** A Housing test rebuilds the six v14 plans that ran, matches their ids, and
  asserts that they differ only in model and route, reasoning tier, sampling and cost ceiling,
  the last three being choices the contract did not state; Refund tests that a plan has a single subject seat; the
  agreement case tests its packs.
- **Golden plays.** For Housing, tests added after the runs play five kinds of tenant on v14
  worlds through the real market: a good lease with its accounting checked by hand, a poor blind
  lemon signing, invalid and unauthorised actions (the market ends exactly as if the tenant had
  passed), malformed output through the kernel (typed as an error and scored as a pass, never as
  $0), and a world whose ceiling is $0; each has a counterexample that makes it fail.

### F.3 Reading trajectories

Housing v14 (60 of its 1,800 attempts step by step) and the agreement's development runs open in
a trajectory viewer that shows each step as the seat saw it beside the state it
could not see, with a QC checklist per run; on 2026-10-13 that checklist flagged 670 lines across
144 bundles, of which 58 needed a reviewer. Walking a single case by hand found Refund's payment-leaf defect (Table F.4);
an earlier data-center design was traced the same way on 2026-09-14.

### F.4 Adversarial checks applied

- **Trivial agents** are reported beside the subjects: signing the draft unchanged recovers 14% of
  the value available in the development agreement pack; always paying the premium gives up $51.25 a world on
  Procurement's declared worlds (Table 5.3); in Housing, scored after the runs, passing earns $0, signing without
  inspecting −$80 and an inspect-then-sign rule $145 a world, a rule two of the three models do not
  beat (Table 5.2).
- **Fixed rules** are scored exactly against Procurement's best policy. In the earlier pack (Table E.14) the one-step rule's $0.06
  is the finding that fails Gates 1 and 3. A v2 pack built after the runs adds one mechanism: new
  listings of one seller kind share a source with a stated chance, so a cheap test of one listing
  tells the buyer about another. Admitted on what a buyer sees, with types drawn afterwards, its 24
  worlds (from 5,798 seeds) make the one-step rule give up $30.09 a world and at least $10 in each,
  as do the four fixed rules and a shortcut that ignores seller kinds; with the source never
  shared, the one-step rule comes within $0.33 of the best policy, so the gap is the shared
  source. Tests check every value against the environment's average over the 27 type profiles.
  Its separate 12-world gate/pilot used 50 cells ($0.2193). Gemini never tested a newcomer
  and matched the premium rule; Luna touched one in 1 of 24 pilot plays, and neither model
  reached the planned probe. Required sizes were 326, 3,464 and 2,047 worlds, beyond the
  96-world cap, so no confirmatory run was frozen or played. On the harder pack of Section 5.1 the same
  exact scoring puts the one-step rule at paying the premium in all 20 declared worlds, and the shortcut and
  the rule that may test two newcomers at 33% and 82% of the gap (Table 5.3).
- **Brief audits** found instructions that decided outcomes in Procurement
  and a schema that contradicts its verifier in Refund.
- **Lower controls for Refund V2.5** were scored under a beatability rule committed before any
  control ran: per seat and cohort, the reference must beat each control by at least 0.50 in
  end-to-end score (0.25 on policy meaning in the policy seat), and a control may match the
  reference on at most 10% of cases. Nine controls (empty, null, full-refund and random legal
  policies; an over-disclosing and a first-record customer; a first-sorted intake; a payments seat
  that moves nothing) played every public case, 3,468 trajectories with no model. The reference
  fails the rule on all 11 public cohorts in the policy, customer and payments seats: a full refund
  that collects nothing is fully right on 38 of 180 policy-seat cases, the evidence
  leaf scores any legal path as complete, the customer seat reduces to copying
  and the payments seat to how often the answer is no payment. Only intake
  passes.
- **A placebo outcome** was run after the agreement's look-back price signal: the same regression
  on the opening price of a scripted integrator that is never told the hidden type gave 0.38 [0.23,
  0.52] where the answer must be 0, which exposed hidden types tied to the pack cell; a random relabelling of types had not
  caught it.

### F.5 Statistical practice applied

The world is the unit of uncertainty, paired across conditions. On the agreement runs, treating
plays as independent made intervals 1.47 to 1.65 times too narrow, and more worlds beat more
repeats: a $50k gap needs 83 to 91 negotiations an arm at one play a world against 159 to 162 at
three. Counterparts are named and reported per type: in the agreement case the counterpart
accounts for 25% to 33% of the spread in what a model earns. The reported analyses declared before
their runs are Housing v14 and v15, the agreement signalling test, both agreement confirmatories, and Procurement's
test and its diagnostics. A harness setting was tested
rather than assumed: asking the CLIs for reasoning summaries changed nothing detectable in Housing
(Opus +17 [−28, +62], Sol +3.5 [−46, +53]; five selected worlds, 120 episodes, the summary-off
plays always run first).

**Agreement confirmatory v1 review (16 October).** Gate 5 is `partial`. A 12-world variance pilot, a sealed sizing record
(`aeread.design.sizing`), frozen plans, paired world-level intervals and Holm
correction were applied. Eight departures are documented: CLI versions; an added wall-time stop;
run-plan labels; the pack-module change for pilot generation; the permitted sizing-code copy;
a post-data analysis-label fix; one missing secondary-arm negotiation; and pilot
pairing by play index. The label fix changes no estimate but leaves the analysis digest different
from the sizing record; the pinned verifier still needs manual treatment of the excluded receipt.
These publication and identity checks are not fully closed. The client-seat construct
limit remains separate. The 45-world P2 estimate rejects zero (Holm p 0.0017), while its 98.3%
interval [6.7, 46.1] lies below the declared $50k minimum; both readings must be reported.

### F.6 Failure records and review

Discovered failures are recorded in the incident log in four categories (design,
operational, tooling, judgment), and rows are never deleted (Table F.3). Evidence
review by verification (digests, replay, prohibited-text scan) was done for the Housing v14
bundle. The agreement family's registry change has had no review by anyone other than its author,
and eight earlier changes to the shared runner were accepted without one under a one-time exception.

**Table F.3. Incident-log entries about each case and its predecessors, by category (as of 16 October 2026).**

| Case | Design | Operational | Tooling | Judgment | Total |
|---|---:|---:|---:|---:|---:|
| Housing | 9 | 21 | 9 | 12 | 51 |
| Procurement | 27 | 6 | 19 | 5 | 57 |
| Data center | 37 | 22 | 22 | 9 | 90 |
| Refund | 12 | 0 | 8 | 3 | 23 |

Counts are distinct entries. One Data-center entry had been filed under a number already in
use; it is counted separately.

### F.7 What quality control found

**Table F.4. Twenty-five selected defects, the level at which each was visible, and what changed (dispositions as of 16 October 2026).**

| Case | What was wrong | Visible in one world? | How it was found | What changed |
|---|---|---|---|---|
| Housing | A seat-number tie-break and scripted rivals' $1 overbid decided who signed a sound listing | no: a pattern across seats | comparing signing rates by seat | one deciding tenant against declared outside demand |
| Housing | The scripted landlord's accept-or-counter reply was a free, near-perfect quality test beside a $25 inspection | no: needs the cost distribution | validity audit before a second model ran | pooled landlord; the revealing landlord kept as a declared arm |
| Housing | Admission made a favourite's lemon rate depend on its popularity (0.29 among admitted worlds where six tenants shared it, about half before admission) | no: a property of the admitted set | comparing pre- and post-admission rates | admit on the tenant's structure, read quality afterwards |
| Housing | The rule the tenant was told sat outside the sealed request | yes, by reading the sealed bytes | known at build, logged before any run | the rules sealed in the prompt, the tenant's history in the observation |
| Housing | A gap decomposition's "luck" part was not luck: uncontested blind bets were lemons 11 of 15 times, contested 1 of 15 | no: a split by rival behaviour | testing the stated odds by model (p = 0.006) | blind signings scored at their expected value given what the tenant saw |
| Procurement (an earlier design) | A rule reading only the displayed price beat the qualified model by $28.50 a world | no: a baseline comparison | the construct check | construct gate recorded `failed`; Gate 0 made a profile mandatory |
| Procurement | The prompt pointed every subject at the cheapest listing, right in half the worlds and wrong in the other half | no: needs the pack's construction | asking whether the hard half was valid or a trick | a neutral prompt and a new pack |
| Procurement | The brief did not say a quote is final or that the buyer is judged on its average | no: a pattern in loss by action | listing each loss by the action that caused it | a second brief; loss fell from $12.2 to $1.0 and $19.4 to $5.4 a world |
| Procurement | Under sample noise the pre-award check reveals the true yield for one free action | yes, by reading the tool's code | designing a sample-again decision | open; 1 of 260 noisy cells used it, no published number moves |
| Data center (predecessor case) | Walking away came within $11k to $46k of the right contract, and asking for every protection within $26k to $88k | no: a strategy-class simulation | simulating shortcut policies on the pack | before any freeze: each named shortcut must cost $75k more than the best contract, and a deal must beat the better outside option by $150k |
| Data center (predecessor case) | At low effort the case could not separate two models: about 83% of the per-world gap was seed noise | no: needs paired seeds | variance split of the paired gap | one seed per world and more worlds; a redesign of the case |
| Data center | The scripted style hashed the whole world, including the client's hidden charge | no: needs two copies of a world | a test that the opening is identical for both types failed | the declared test uses a fixed style; the admitted pack draws the style from the public world only |
| Data center | The hidden type was fixed by pack cell and moved with public quantities | no | a placebo outcome, after the look-back (Appendix F.4) | an admitted pack whose types are drawn after admission (Appendix F.2) |
| Data center | The generator priced the client's rival offer, a public number in both briefs, from the drawn integrator type, so a public parameter depended on both hidden types | yes, by reading the generator | building the admitted pack | the admitted pack prices it before any type is drawn; the development packs keep theirs |
| Data center | The integrator's private cost barely moves the best agreement, so the client seat has almost nothing to infer about clauses | no: a value of information across worlds | building the admission rule for both seats | open; the client seat needs worlds where the integrator's risk charge is private |
| Housing | The primary measure conditions on the landlord's reply only below the sound floor; a reply that proves a listing sound is still scored at the stated odds | yes, by reading the measure's code | writing the formal appendix of this paper | recomputed from the sealed run roots: 57 signings move, no declared verdict changes, Gemini's leads shrink by $10 and $13 in the v14 cells; an erratum is owed |
| Refund | The 120-cell panel was six cases: the world seed changed only the case id, and the policy seat ran at temperature 0 | no: needs the seeds compared | rebuilding the cases and reading the reference run's resolutions | the case is the unit of analysis; V2.5 varies declared conditions by seed |
| Refund | A correct denial written with method `null` failed: the prompt says "none", the schema allows null, the verifier compares strings | yes, by reading one proposal against the verifier | building the gap decomposition | recorded; reported as format, not outcome |
| Refund | The human-QC approval was minted by the runner from two status-only stubs, so it bound whatever the runner produced | yes, by reading the runner's code | the Refund audit | V2.5 names a reviewer, but the runner still binds the approval to its own output (still open) |
| Refund | Refund's payment leaf checks that payments executed what the proposal asked, so a proposal with an aliased mutation moves no money where the reference refunds $185.22 and still scores 1.0 | yes, by tracing one case | writing the formal appendix of this paper | open; report the leaf as binding and add a check against the reference |
| Housing | The v14 receipts' own scores total all six tenant seats against baselines from a market without outside demand, so they are not the deciding tenant's | yes, by reading the receipts | building the seat-0 controls | open; the published primary is computed separately and is unaffected; a seat-0 scorer needs a module outside the hashed runner |
| Refund | In three of Refund V2.5's four seats a naive control comes close to the reference: a full refund that collects nothing is fully right on 38 of 180 policy cases, the evidence leaf passes any legal path, the customer seat reduces to copying and the payments seat to the base rate of no payment | no: a rate across cases | lower controls under a rule committed before they ran | open; Gate 3 recorded `failed`; scoring pairs of cases would stop the full-refund control (0 of 38 pairs), a rule not yet declared |
| Housing | The v14 receipts name the model for the five tenant seats a script played; the true seat map is only in an unsealed log | yes, by reading the driver's seat router | the paper's runtime review | open; record the seat map inside the seal under a new identity |
| Procurement | Procurement's original decision-loss report read an unsealed action copy through an unpinned reference; receipt replay alone did not certify it | yes, by reading the driver | the paper's runtime review | resolved for the reported panels on 16 October: source-pinned reanalysis from replay-audited sealed actions reproduces all 144 losses; prospective receipt-leaf integration is separate work |
| Procurement | The pay-or-test action schema let `message` be null while the parser requires it, so a model's first action could end its episode on format | yes, in one gate cell | the flash-model gate | the schema requires every field the parser needs, under new identities |

Fourteen of 25 defects required evidence beyond one world. With Procurement's decision-loss
report now re-derived from sealed actions, eight remain open: the free yield check in noisy
Procurement packs; the Housing reply measure, the Housing receipts' score totals and their seat
map; Refund's payment leaf, its runner-minted approval and its lower controls; and the
Data-center client seat.

### F.8 Assessment against the Agentic Benchmark Checklist

The four cases are assessed item by item against the checklist [ABC]; the outcome-validity item
that applies is the one for a quality measure, since no case is scored by string matching, unit
tests or a judge model.

**Table F.5. The four cases against the checklist.**

| Item | Status | Evidence |
|---|---|---|
| T.1 Tool versions specified | partly | routes, prompts, schemas and implementation digests are sealed in each plan; the two CLI agents expose no seed or temperature |
| T.2 Required APIs accessible | partly | provider outages lost cells (36 Housing cells to an empty account, 40 data-center negotiations to CLI errors), each recorded as typed missingness |
| T.3 Terminates or handles API errors | partly | Housing v14 uses worker-level failure streaks: twelve workers could still produce 36 account failures. Procurement flash panels declare retries and a consecutive-failure stop; the confirmatory agreement driver freezes a five-consecutive-failure halt plus list-price and wall-time ceilings, unlike its development predecessor. These are driver controls, not adoption of the kernel halt helper (Appendix H.4); operational failures remain exclusions |
| T.4 Residual state cleared between runs | met | each cell is a fresh episode from a sealed plan; the CLI agents run one ephemeral subprocess per action |
| T.5 Agent isolated from ground truth | partly | named hidden fields are tested absent from observations in Housing, Procurement and Refund, not in the agreement case; one leak was fixed and one is open in noisy-sample packs |
| T.6 Setup does not change over time | partly | environment inputs and declared routes are pinned; this does not attest a stable hosted deployment, provider compliance, or the unsealed CLI environment (Appendix H.2, H.3) |
| T.7 Ground truth verified | partly | each reference is played on every admitted world through the environment and reaches its declared result, initially by tests added after development; the admitted agreement pack also had a pre-confirmatory dry run (Appendix F.2) |
| T.8 Each task verified solvable | partly | reference policies are played through the environment, but full-information references can use information unavailable to the evaluated seat; this does not establish that every seat can attain the reported bound |
| T.9 Oracle solver | partly | exact for Procurement; an independent reference resolution and a scripted policy that resolves every case for Refund; a reachable reference for Housing, with an exact best informed tenant in development; a full-information stand-in for Data center, whose per-turn best informed policy is not built |
| T.10 Free of exploitable shortcuts | partly | trivial agents, exact fixed-rule scores and brief audits (Appendix F.4); twenty-five selected defects (Table F.4); a one-step rule reaches the best policy on Procurement's earlier pack, and the reported pack admits only worlds where it pays the premium; a wrong refund can still pass Refund's payment leaf |
| O.i.1 Quality metric resists exploitation | partly | code computes the measures and controls are tested, but the Housing measure needed correction and Refund has open payment and lower-control failures |
| R.1 Open source | partly | the environments, runner and evidence are public; the trajectory viewer is private |
| R.2 Open evaluation harness | met | the shared runner is in the public repository |
| R.3 Measures against contamination | met | preventive measures, not proof of zero contamination: worlds are generated, holdouts come from a disjoint seed range, and declared tests run on fresh worlds |
| R.4 Plans to update | partly | packs regenerate from new seeds; no refresh schedule is stated |
| R.5 Capability related to construct | met | each case states the decision it measures (Table 5.1) |
| R.6 Evaluation subject stated | met | the subject is a profile (model, harness, prompt, tools, reasoning, retries); CLI agents are named with their harness |
| R.7 Steps to prevent, find and correct flaws | partly | the gates and the incident log (Appendix F.1, F.6) |
| R.8 Qualitative discussion of unavoidable flaws | met | the end of §5.2 |
| R.9 Quantitative analysis of flaw impact | partly | measured for the brief change, the refused cells and missingness bounds; not for every open row |
| R.10 Statistical significance | met | paired world-level intervals; Holm correction across declared primaries |
| R.11 Guidance on interpreting flawed results | met | every result is labelled confirmatory, declared or development |
| R.12 Non-AI baselines | partly | scripted policies in every case; no human |
| R.13 Trivial agents | partly | always paying (Procurement), signing the draft (Data center) and passing, signing anything and inspect-then-sign (Housing, scored after the runs) are reported; Refund V2.5 has nine lower controls, which come too close to the reference in three of four seats, and the V2.1 results reported here have none |

## Appendix G. Artifacts

Everything the numbers in Sections 5 and 6 rest on is in the public AERead repository or is
named here when it is not.

- **Code and cases.** The shared runner and the case families, with each case's generator,
  reference, verifiers, packs and tests. Each case is on its own development branch of the
  repository.
- **Evidence.** Sealed, digest-bound bundles under `evidence/`: the Housing v14 confirmatory and
  its declared fill, the data-center agreement bundles, and the Refund V2.1 bundles with their gap
  decomposition. Procurement's declared runs (Table 5.3) are sealed run roots whose read-outs are committed
  under `evidence/procurement_allocation/pay_or_test_v3_*` on the case's branch, not yet on `main` or
  published as bundles.
- **Quality control.** Each family's QC profile and incident log, kept with its code; the
  reference-run tests named in §6.
- **Sources for every number.** The source files of Sections 5 and 6 end with tables that map
  each table and claim to its bundle, run, code revision or log entry.
- **Paper analyses.** `tools/paper/` holds the rescoring under the corrected Housing measure, the failure
  taxonomy of §5.2 and the control contrasts of Table 5.2, with a runner and the inputs each needs.
  The Housing v14 and Procurement inputs are sealed run roots not yet published as bundles, so those
  numbers can be checked against the run roots but not yet from `evidence/` alone.
- **Not in the repository.** The trajectory viewer is private; one-page result summaries restate
  numbers from the bundles above.

**Headline verification.** The draft's source package includes
`analysis_evidence/housing_reply_conditioned/` and `analysis_evidence/procurement_reanalysis/`.
The Housing analysis re-extracts its committed trajectory table from the sealed run roots and
regenerates both measures exactly. Procurement's `pay_or_test_reanalysis` checks all 144 original
receipts, then reconstructs decision loss from their sealed parsed actions; its public projection
regenerates Table E.14 without private run roots. Source and case digests, extraction commands,
tests and a patch against the analysis base are supplied with the package. Full verification of
either projection against its original execution logs still requires the retained run roots.

**Agreement confirmatory and Procurement v2.** The source package also includes the data-center
agreement's confirmatory plan, results, analysis, sizing record and source-bound review, plus the
Procurement v2 pilot report and results note. The original
five agreement bundles retain their sealed bytes. The Data-center QC profile and incident-log
corrections are supplied as a documentation patch; no frozen driver or analysis code was edited.
