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
| Refund | resolution (eligibility, remedy, amount, liability; workflow) against the reference | answer (implemented as rule checks in the code) | share of fields matched | outcome |
| Refund | evidence complete before deciding; contract format; payment bound to the proposal | rule | pass or fail per leaf | path |

None of the four cases uses a rubric. Code computes every score from the recorded trajectory,
with no model or human rater in the loop. The kernel's replay certifies the score recorded in each
receipt. In Housing and Procurement, however, the headline measure is computed outside the receipt
(Appendix F.2), so a contributed case should make its headline measure a receipt leaf that replay
covers. The runtime supports rubric leaves, but it keeps them beside the computed leaves and never
folds them into the computed score.

### E.2 Construction of the evaluation sets

Each evaluation set is drawn from a generator and filtered by an inclusion criterion. Where a case
has a hidden draw, the criterion reads only what the deciding side could observe, so inclusion
cannot select on the draw. We name the strata before any model plays, and we draw held-out worlds
from a seed range disjoint from the development set.

**Housing.** A seed is included when the tenant's favourite listing and a second listing would be
worth more than their asking rents if sound. Each seed keeps its own lemon draw, and we read the
stratum (the favourite is a lemon, or it is sound) only after inclusion. Seeds are taken in order
until each quota is full: a main evaluation set of 200 favourite-lemon and 60 favourite-sound worlds,
and a holdout of 30 and 10 worlds from a disjoint seed range. The quotas oversample favourite-lemon
worlds, where the decision is hardest. This is v14's criterion. v15 (Section 5.1) applies it and then
screens each candidate world offline:
- **The screen.** The best informed tenant and `inspect_then_sign` play both landlord arms. A world is included only
  if its full-information ceiling is above $0 in both arms and the best informed tenant beats the rule by at least
  $25 on the corrected measure, averaged over the two arms.
- **What it included.** The main evaluation set of 260 worlds (200 and 60) came from 437 seeds: 119 failed the
  screen, 6 had a $0 ceiling and 7 failed the structural criterion.
- **The other streams.** The holdout of 40 worlds runs with outside demand at 0.3 a round and comes from a disjoint
  seed range; a development set of 20 worlds serves the model-profile check and the variance pilot.
- **Records.** No two included worlds are near duplicates, and the evaluation set's scan logs every seed's numbers.

**Procurement.** The earlier evaluation set contains six kinds of world, four worlds of each. In two
kinds paying the premium is right, either on price alone or because a failed test would leave no
time to buy from the recorded supplier. In the other four a test is right, either of the cheapest
newcomer or of another newcomer, on a tight or a loose clock. We classify a world from its listings
with every newcomer assumed good, and draw the newcomers' types afterwards from a separate random
stream. The kinds are sampled evenly; if they were drawn as they fall, a test of the cheapest
newcomer would be right in most worlds. This classification screens no shortcut, which is why a
one-step rule nearly solves the evaluation set (Appendix F.4). The second evaluation set's inclusion
criterion does screen shortcuts. Computed from what a buyer observes and the stated law, it keeps a
world only if each screened shortcut, including the one-step rule and four fixed rules, gives up at
least $10 against the best policy, and it requires the included worlds' mean one-step loss to reach
$15; 24 worlds were included from 5,798 seeds. A sibling evaluation set of 18 worlds places a
marketplace record on one component's listings, from which an agent can read which supplier to
verify.

**Data center.** The development set has eleven strata, each with its own outside-option situation
and its own set of allowed playbooks, and two worlds per stratum and playbook: 58 worlds in all, 52
with a deal worth signing and 6 in which no agreement beats both outside options. The 58 development
worlds come from the generator of the case's predecessor. The pre-registered test used 58 fresh worlds
from the same generator, none identical in content to a development world, and for its type-swap
experiment it wrote 29 of them twice, identical except for the client's hidden risk charge. The
inclusion criterion implemented for these runs is the predecessor's (a shortcut must lose by a margin
on the playbook's menu); the agreement case's own criteria were not used. The confirmatory evaluation
set is filtered by the agreement case's own criterion, computed from the public world and the
pre-registered prior before any hidden type is drawn. In expectation over the prior, a world is
included only if four conditions hold. The best agreement beats the draft by at least $75k. Knowing
the client's hidden charge is worth at least $25k to the integrator's choice of agreement, and for
every integrator type the best outcome changes with that charge. Signing the draft as it stands,
moving only the price, and either side demanding every protection each lose at least $75k against
the best agreement. Walking away loses at least $150k. We leave redline fees out of every shortcut's
value, which favours the shortcut, so each margin is a lower bound. Of 2,729 seeds scanned, 60 were
included (45 with a deal and 15 without); v1 used them, with types drawn after inclusion and a
separate 12-world variance pilot (Appendix F.2). v2 (Table 5.4) kept these criteria and added one
screen, computed before any episode: in a world with a deal, the integrator's full-information
ceiling against the firm population must beat the price-only rule by at least $25k. Its seeds are
disjoint from those of every earlier evaluation set; of 5,436 seeds scanned, 80 were included (72
with a deal and 8 without).

### E.3 What was run

**Table E.2. What was run.**

| Case | Worlds or cases | Strata | Subjects | Plays | Cost (list) | Status |
|---|---|---|---|---|---|---|
| Housing v14 | 260 main + 40 holdout | favourite lemon (200 + 30), favourite sound (60 + 10); both landlord kinds in every world | Gemini 3.8 Flash, GLM 5.3 Flash, GPT-6 Luna | 1,800 episodes and a 48-episode fill | about $8 | confirmatory |
| Housing v15 | 260 main + 40 holdout (outside demand 0.3), from a screened evaluation set | as v14 | Gemini 3.8 Flash, GPT-6 Luna, and Luna's A/A twin | 1,720 episodes, all verified by replay; pilot 160 episodes | $8.64 (pilot $1.08) | pre-registered; Gates 1, 2, 3 and 5 passed, 4 partial |
| Housing v15 addendum B | the v15 evaluation set: 260 main + 40 holdout | as v15 | Sol 6.1 (Codex), Opus 5.5 (Claude Code), both isolated | 1,200 episodes, all completed and verified by replay | $24.30 and $54.03 at list price (subscriptions) | pre-registered addendum, outside v15's contrasts |
| Housing, CLI agents | first 20 of the main evaluation set | 10 and 10 | Opus 5.5, Sol 6.1 | 40 episodes each | $4.72 | development |
| Procurement, pay or test | 24 | six kinds × four | Opus 5.5, Sol 6.1 | 96 episodes over two task prompts | $9.10 | development |
| Procurement, pay or test, flash models | 24 | six kinds × four | Gemini 3.8 Flash, GPT-6 Luna (GLM's route refused) | 24 episodes each, second task prompt | $0.21 | development |
| Procurement, record evaluation set | 18 | which listing the record favours | Opus 5.5, Sol 6.1 | one episode a world each | | development |
| Data center development and signalling | 58 development + 58 fresh | deal or no deal; outside-option kind; counterpart style | Opus 5.5, Sol 6.1 | 2,456 negotiations, 2,417 valid | $119.30 | development; one pre-registered test |
| Procurement v2 gate and pilot | 12 pilot worlds, two plays per model; one gate each | shared-source information value | Gemini 3.8 Flash, GPT-6 Luna | 50 episodes | $0.2193 charged | stopped at sizing; no confirmatory run |
| Data center confirmatory v2 | 80 included + 12 pilot | 72 deal / 8 no-deal; both tools isolated | Opus 5.5, Sol 6.1 | 640 negotiations, all valid and replayed | $55.41 | pre-registered; Gate 3 passed, the others partial |
| Data center confirmatory v1 | 60 included + 12 pilot | 45 deal / 15 no-deal in the confirmatory run | Opus 5.5, Sol 6.1 | 1,176 model negotiations, 1,175 valid; 120 additional scripted dry runs | $74.41 | pre-registered primary contrasts; eight departures |
| Refund V2.5 release | 244 distinct cases, 268 placements (seed 301) | thirteen cohorts × four seats | deterministic reference profiles only | 1,072 trajectories | none | developmental release |
| Refund V2.5 calibration | 66 seat-specific pairs, 132 placements | four seats, two repeats | Gemini 2.5 Flash Lite, Gemini 2.5 Pro, GPT-6-sol | 792 episodes | not reported | exploratory calibration |
| Refund V2.1 | 6 cases | one policy seat | DeepSeek V4 Flash, Gemini 2.5 Flash Lite, GPT-5.6 Luna, Grok 4.3 | 480 episodes (20 repeats of each case) | | descriptive |

Opus 5.5 ran through Claude Code and Sol 6.1 through the Codex CLI, without tools, at low reasoning
effort, with one subprocess per action. Neither CLI exposes a seed or a temperature, so we record both
settings as unavailable rather than assume values for them. In the v1 confirmatory run the two CLIs
were not equally isolated from the operator's machine (Table H.1); for v2 we isolated both and probed
their context (Section 5.1). The Refund V2.5 release check makes no paid model call: its 1,072 scripted
trajectories measure the environment's conformance, not model performance. The earlier release audit's 816 scripted
trajectories reduce to 174 distinct action sequences (four payments cases share one reference trajectory). Both are
separate from the 792 model episodes of the calibration in Section 5.1, which do not certify performance on the
expanded release.

### E.4 Results beyond the main text

#### Housing

Section 5.1 and Table 5.2 report v15, the pre-registered comparison. Its inclusion screen rejected 119 of the 437
candidate main worlds. Relative to the best informed tenant's value, the full-information ceiling is 121% and
`inspect_then_sign` earns 49.5%. The A/A arm, in which Luna runs twice under two names with different seeds, differs by
−1.6 points [−6.1, +2.9]. Run-to-run noise between identical arms is therefore well inside the $50 band; the band
itself is our judgement of the smallest difference that matters, which the A/A arm cannot test. In the holdout, Gemini
leads Luna by 18.2 points [5.8, 30.6]. Across all 600 of each model's episodes (the main evaluation set and the holdout, both
landlord kinds and both strata), Luna signs without inspecting 230 times and Gemini 114 times. All 1,720 episodes completed and were verified by
replay ($8.64). The evidence bundle also records 0 invalid seat-0 actions for either model, and realized nets of
$244.0 (Gemini) and $194.2 (Luna) beside the corrected-measure values; the v15 results note in the repository gives
every row of Table 5.2 in dollars.

**The addenda.** GLM 5.3 Flash was excluded at the pre-run profile check, because its provider now serves a different
quantization from the one v14 pinned. A pre-registered addendum ran it on another provider serving v14's quantization
(600 of 600 episodes, verified by replay), and we report it beside v15 and outside its pre-registered contrasts. On
the main evaluation set GLM keeps 53.9% of the best informed tenant's value. It does not beat `inspect_then_sign` at
the pre-registered 98.3% level (+4.5 points [−4.4, +13.3]). Descriptively, it trails Luna by 8.9 points [1.6, 16.2]
and Gemini by 24.8 [19.0, 30.5]. A second pre-registered addendum ran Sol 6.1 and Opus 5.5 through their command-line
tools on the same 600 episodes each, all completed and verified by replay, likewise outside v15's contrasts. Sol keeps
90.4% of the best informed tenant's value and comes closest to `inspect_lowball` (5.0 points below it); Opus keeps
80.4%. Both beat `inspect_then_sign` at the 98.3% level. Sol leads Opus by 10.0 points [7.4, 12.6], and Opus cannot be
distinguished from Gemini (+1.6 [−0.3, +3.6]). As with the flash models, nearly all of each model's shortfall arises
in worlds whose favourite is a lemon.

**The earlier comparison (v14).** The rest of this subsection reports v14, the earlier comparison of three models
(Table E.13). v14's pre-registered measure conditioned on only one landlord kind.

**Table E.13. Housing v14, main evaluation set, in dollars per world with 95% intervals over worlds. The corrected block is a post-run reanalysis that we reproduced from sealed records on 16 October; the pre-registered measure remains visible.**

| | Gemini 3.8 Flash | GLM 5.3 Flash | GPT-6 Luna |
|---|---:|---:|---:|
| Complete worlds: all (favourite lemon / sound) | 260 (200 / 60) | 260 (200 / 60) | 260 (200 / 60) |
| *Pre-registered measure, as frozen* | | | |
| Tenant net | +211 [+189, +233] | +137 [+111, +162] | +130 [+104, +156] |
| Minus the reference, favourite is a lemon | −101 [−120, −82] | −179 [−203, −154] | −207 [−229, −186] |
| Minus the reference, favourite is sound | −14 [−18, −9] | −76 [−116, −36] | −9 [−16, −2] |
| Minus a rule that inspects when the odds make it pay, then signs | +66 [+50, +82] | −8 [−30, +14] | −15 [−32, +2] |
| *Corrected measure, reanalysis* | | | |
| Tenant net | +213 [+191, +235] | +149 [+124, +175] | +147 [+121, +174] |
| Minus the reference, favourite is a lemon | −98 [−117, −80] | −164 [−189, −139] | −185 [−208, −162] |
| Minus the reference, favourite is sound | −14 [−18, −9] | −70 [−108, −32] | −9 [−16, −2] |
| Minus a rule that inspects when the odds make it pay, then signs | +68 [+52, +84] | +5 [−17, +27] | +3 [−15, +20] |

Under the analysis pre-registered before any episode, which compares three pairs with Holm adjustment and
treats $50 as the smallest meaningful difference, Gemini leads GLM by +74 [+53, +95] dollars a world and Luna by
+81 [+63, +98], and GLM and Luna do not differ (+7 [−16, +29]); the 40-world holdout agrees. Under the corrected
measure, a reanalysis that was not pre-registered, the leads are +63 [+43, +84] and +65 [+49, +82], and GLM minus
Luna is +2 [−20, +24]. No pre-registered verdict changes, but both lower bounds fall below $50. No model reaches
the reference, and almost the entire shortfall arises in worlds where the favourite listing is a lemon. The rule
in the last row of each block, which we scored after the runs, earns $145 a world; under either measure Gemini
beats it, and GLM and Luna cannot be distinguished from it.

On all 260 worlds of the main evaluation set, with Gemini's refused episodes taken from the pre-registered fill,
the models fall short of the reachable reference by −81 [−96, −66] (Gemini), −155 [−177, −134] (GLM) and −162
[−181, −142] (Luna) dollars a world. They keep 60%, 27% and 22% of what the reference earns where the favourite is
a lemon, against 97%, 83% and 98% where it is sound. The 40-world holdout points the same way (Gemini−GLM +105
[+46, +164], Gemini−Luna +65 [+23, +106], GLM−Luna −40 [−106, +26]). The original 1,800 published receipt rows
comprise 1,764 scored completions and 36 exclusions for operational failure. Replay reconstructs each completed
receipt's score, which totals all six tenants; failure rows are verified as exclusions rather than rescored
(Appendix H.3). The derived analyses re-derive the seat-0 measure of Table E.13 from the sealed event logs.

Scripted tenants, played offline on every episode, give the floor. Passing earns $0. Never inspecting, and signing
any hold that the listing's value would cover if it were sound, earns −$80 a world, because this rule signs lemons.
Inspecting when the stated odds make it pay and then signing earns $145. The models beat the first two rules by
$130 to $292 a world. Sixteen GLM episodes contain invalid tenant actions, almost all of them offers on a listing
that was already leased; the bundle did not report them, and no number changes. Thirty-six Gemini episodes were
refused when the provider account ran out of credit. The pre-registered bundle keeps them as typed missingness,
and the tables use a fill run under its own frozen configuration, whose twelve reruns of completed episodes
reproduced their outcomes. On the pre-registered bundle alone (240 Gemini worlds) the leads are +70 [+48, +92]
and +80 [+62, +99] under the pre-registered measure and +60 [+39, +81] and +67 [+49, +84] under the corrected one.
The corrected measure values a blind signing at the posterior given the inspections and the informative replies.
Under it, 21 (GLM), 33 (Luna) and 3 (Gemini) signings change value; Gemini leads by +63 [+43, +84] and +65 [+49,
+82] (Holm p < 10⁻⁸), GLM−Luna is +2 [−20, +24], and each model's difference from the reference becomes −79, −142
and −144. We do not edit the published bundle.

Two CLI agents played the first 20 worlds of the main evaluation set (40 episodes each). Sol 6.1 earns $313
[225, 402] and Opus 5.5 earns $291 [198, 383] a world, against the reference's $331 on those worlds; their
difference, +23 [−19, +64], is not statistically established. Both equal the reference where the favourite is
sound ($427) and fall short where it is a lemon ($200 and $155 against $235).

This reference is reachable but not optimal. An exact best informed tenant (Appendix C) earns $307 a world on the
main evaluation set when it knows the two landlord kinds and how each prices. The v14 models were not told how
landlords price, so part of their gap to this tenant reflects missing information rather than poor judgment. v15
states the pricing rule in its task prompt and uses this tenant as the reference for its inclusion screen and for
its gap rows (Section 5.1).

#### Procurement

**The earlier evaluation set.** Section 5.1 reports the case's harder evaluation set. The earlier set, which all
four models played, has 24 worlds of six kinds. In it, quotes always arrive, the recorded supplier always charges a
premium, and newcomers never share a source (Appendix A.2). For a model m with decision loss L_m against the best
policy, we report the share of the premium-to-best gap that it closes,

[[eq E.1]] G_m = (L_pay − L_m) / L_pay,

where L_pay is the loss of always paying the premium. G_m equals zero for that rule and one for the best policy, and it
is negative for play worse than paying the premium.

**Table E.14. The earlier Procurement evaluation set, 24 worlds per model: the share of the best policy's value (it earns $451 a world) that each model gives up and keeps, with 95% intervals over worlds. Always paying the premium, which never tests a newcomer, already keeps 83.3% (it gives up $75.19 a world), so the last row reports the decision itself: the share of the gap between that rule and the best policy that each model closes. On 16 October we reproduced all 96 losses and these intervals with a source-pinned derivation from replay-audited sealed actions; decision loss is separate from the original receipt scores.**

| | Sol 6.1 (Codex) | Opus 5.5 (Claude Code) | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| Share of the best policy's value given up | 0.2% [0.0, 0.5] | 1.2% [0.3, 2.4] | 16.7% [10.8, 22.5] | 16.5% [10.4, 22.8] |
| Share kept (always paying the premium: 83.3%) | 99.8% | 98.8% | 83.3% | 83.5% |
| Share of the premium-to-best gap closed | 98.6% [97.2, 99.7] | 92.8% [85.9, 98.4] | 0.0% [−34.9, 35.2] | 1.1% [−36.6, 37.9] |

The frontier agents, run through their CLIs, are at the ceiling. Most of what they lost on a first run came from
two rules that the task prompt left unstated: that a quote is final, and that the average is the criterion. This
ceiling shows less than it appears to. On this evaluation set a rule that looks one test ahead comes within 0.01%
of the best policy's value, so near-perfect play shows that the agents avoid the listed mistakes, not that they
plan further ahead than one test. A v2 gate check and pilot (50 episodes, $0.22) found little newcomer testing and
required 326 to 3,464 worlds against a cap of 96, so no confirmatory run followed (Appendix F.4); the harder
evaluation set of Section 5.1 followed instead. The flash models give up as much as always paying the premium does:
their loss arises in the worlds where a newcomer was worth testing.

**Further runs on the harder evaluation set (Table E.15).** Section 5.1 reports the 20 pre-registered worlds. On
them, Sol opens with the kind-blind shortcut's move in 2 of 40 plays, tests a second newcomer in 7 of 40 and looks up
a source in 4, so the moves the case is built around are rare in its play. The runs below are a development pilot
and three diagnostics, each pre-registered before its plays; none of them tests a claim. These runs, like the
pre-registered test, used the case's environment from a development branch, which is now on the main branch with its
registration, and every published receipt replays through the runtime's command line (Appendix F.1).

**Table E.15. Procurement's harder evaluation set: runs beyond Table 5.3. Shares are of the gap between paying the premium and the best policy, as means over worlds (each world the mean of its plays).**

| Run | Worlds and plays | Sol 6.1 | Opus 5.5 | Exact rules on the same worlds |
|---|---|---|---|---|
| Development pilot | 6 worlds, two plays each | 50% [27, 71] (bootstrap) | 0% in all 12 plays | one-newcomer rule 0%, shortcut 8%, two newcomers 84% |
| The pre-registered worlds at the earlier set's cohort odds (diagnostic) | 20 worlds, one play each | 59% [19, 100], median 83%; one play deferred and bought nothing | 0% in all 20 plays | one-newcomer rule 58%, shortcut 62%, two newcomers 90% |
| A task prompt corrected for four wording defects (diagnostic) | the 20 pre-registered worlds, two plays each | no change shown: +7.8 points [−5.6, +21.2] | touched no newcomer in 40 plays | as Table 5.3 |
| How likely a newcomer is to be sound once another of its kind has passed or failed a sample, with and without a clean quote of its own first, asked with no play (diagnostic) | 3 worlds, 3 questions, asked twice | 18 of 18 within 0.05 of the exact value | 18 of 18 within 0.05; earlier attempts, whose schema asked for the model's working, were refused | |

A further diagnostic, pre-registered before its plays, tried to certify Gate 1's measured headroom with a frozen
control that tests, as the standard then required. We chose GPT-6 Luna at high reasoning effort on the pilot worlds
because it tested a newcomer in 5 of 12 plays (Gemini 3.8 Flash at high reasoning effort tested in none). On the
pre-registered worlds, with three plays each, it tested in 26 of 60 plays but closed −34% of the gap on average,
which is worse than paying the premium. Against this control, 3 worlds score the same at every seed and 18 are
matched by a screened rule (the kind-blind shortcut in 14, the one-step rule in 4), so only 2 of 20 pass. The
control is weaker than the shortcut, which says more about the control than about the worlds. In a comparison that
was not pre-registered, Sol's better play of each world beats every screened rule in 11 of 20 worlds, and if its two
plays were read as a control, Sol would pass the check in only 9 of 20 worlds. A world that a model fails to exploit
is not a world without headroom: every shortcut loses at least $10 to the exact reference in every pre-registered
world. The standard therefore now accepts this exact screen where a case has an exact reference, and the evaluation
set passes Gate 1 on it (Appendix F.1); the control's result remains reported as a diagnostic.

The pilot's go rule sized a comparison of the two models beyond the cap of 96 worlds, so the pre-registered test
concerned Sol alone. On the pilot worlds the kind-blind shortcut closes 8% of the gap against Sol's 50%; on the
pre-registered worlds it closes 33% against Sol's 35%. No comparison with the shortcut was pre-registered.

We score the fixed rules exactly over the 24 worlds. A rule that compares each untested newcomer with paying,
looking one test ahead and keeping the recorded supplier reachable, gives up $0.06 a world. Testing the best odds
once gives up $45.7, always paying $75.2, testing the cheapest newcomer once $81.4, and working up the price list
until one listing qualifies $146.1. Under a first task prompt that did not state that a quote is final or that the
average is the criterion, the CLI agents gave up $12.2 [4.3, 23.6] (Sol) and $19.4 [6.0, 38.2] (Opus) a world;
stating the two rules reduced the loss by $11.1 [3.6, 22.3] and $14.0 [0.4, 33.5]. Under the second task prompt the
agents give up nothing in 20, 17, 8 and 7 of the 24 worlds (Sol, Opus, Gemini and Luna respectively). Both CLI agents
pay without a test in all eight worlds where paying is right, and the first newcomer each tests is the right one in
15 and 14 of 16 worlds. The record evaluation set is saturated in the same way: Opus solves 18 of 18 worlds and Sol
16. Of the flash models, Gemini never tested a newcomer and Luna tested in two worlds. The two cannot be
distinguished (+$0.8 [−3.7, +6.3]); their loss is $112.8 and $111.0 a world where a test is the best plan, against
$0.0 and $1.0 where paying is, and all 48 episodes are valid and replayed ($0.21). GLM 5.3 Flash did not play,
because its provider route changed price before any call.

#### Data center

**v2 (Table 5.4).** All freeze and run probes were clean, and all 640 negotiations are valid and replayed ($55.41 at
list price). With the walk-away point stated, neither model signs below it as client (0 of 80 for either), and the
client seat separates nothing (+0.8 points [−3.2, 4.9]). On v2's deal worlds the best informed turn-by-turn policy
gives the integrator 63.5% of the value available at the true client type, whereas Sol earned 33.8%, Opus 26.3% and
the price-only rule 26.5%. Sol therefore captures about 20% of the room between the rule and that policy. Neither
model contrast is shown to reach its pre-registered minimum: the lower ends of the intervals fall below 32.4 and 12.9
points ($100k and $40k). Halving the head-to-head contrast, so that a transfer between the two agents counts once,
halves its minimum to 16.2 points, below which the halved interval also starts (15.7). The halved comparison in
Section 5.1 was made after the runs; its paired p-value is 0.0003. Matching seats as well, by averaging the
integrator and client contrasts against the script (4.1 points [0.1, 8.2]), widens the paired difference to 16.7
points [10.5, 22.9]. The earlier
comparison (v1) is reported at the end of this subsection (Tables E.16 and E.17), and development results are in
Tables E.3 and E.7.

**Development sets.** The counterpart and probing results below use the development sets. Which model sits in which seat changes the
pair's total by +3 [−11, +18] thousand dollars a world, and in head-to-head play Sol is ahead of Opus in 51 of 52
worlds in each seat. Table E.3 reports every counterpart, and Appendix B gives each counterpart style's rule and
parameters.

**Table E.3. Development results: Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

| Counterpart | As integrator | As client |
|---|---:|---:|
| The other model | +248 [+206, +290] | +251 [+209, +293] |
| Firm population | +17 [−10, +44] | +23 [−2, +48] |
| Soft | +86 [+56, +116] | +95 [+74, +115] |
| Price only | +112 [+75, +149] | +54 [+36, +71] |
| Collapse | +88 [+51, +126] | +148 [+117, +179] |
| Overreach | +32 [+10, +53] | +108 [+72, +144] |

Against the firm population, both models earn about what signing the counterpart's first offer earns (a scripted
stand-in that does so earns $122k a world as integrator and $114k as client), but by opposite routes: Opus signs the
first offer, whereas Sol bargains until the last move and loses deals. Two copies of Sol split the value evenly
(integrator minus client −6 [−94, +81] thousand dollars a world).

**Adversarial counterparts.**

- *Hardball scripts* (overreach, collapse and price only; 684 of 696 negotiations valid; $33.41).
  The overreach script tests whether a model refuses a deal worse than walking away. As client, Opus
  signed below its own walk-away point in 23 of 52 worlds and earned −8 thousand dollars a world on average,
  whereas Sol signed none and earned $100k. The collapse script holds a high ask until its final proposal and
  then concedes, so it rewards a model that does not settle early: as client, Sol earned $187k a world
  and Opus $40k. The price-only script tests whether a model sets the clauses itself. As integrator,
  Opus reached the best clause set in 0 of 52 worlds and lost 15 deals, whereas Sol reached it in 10.
- *A probing counterpart* (20 worlds, with each model in each seat against the prober and against a
  silent script; 158 of 160 negotiations valid; $7.92). Both sides' task prompts carried a planted
  confidential name and figure that change no payoff, and the prober's notes asked for the other side's
  costs and for the confidential item. Neither model disclosed a confidential item in any negotiation.
  When asked for its own costs, Sol as integrator stated its pre-staging cost in 18 of 19 negotiations,
  and Opus in none of 40. Nothing in the task prompt says that a side's own costs are confidential, and
  no model stated a false cost. Asking changed no model's earnings measurably (−15 [−86, +57], +4 [−18,
  +25], +1 [−25, +26] and +3 [−15, +22] thousand dollars a world); the intervals are wide, so this does
  not show that disclosure is harmless. Unprompted, across 3,492 notes, no model stated its own private
  cost. In 114 negotiations a note called a price final or a floor, and in 112 of them the stated number
  was better for the speaker than its true limit.

**A pre-registered test.** A look back over these runs suggested two signals: Opus's counter-offer price seemed
to follow its private value, and Sol's clause requests seemed to follow its risk charge. We committed the claims,
measures, exclusions and six primary predictions before any run, on the fresh worlds of Appendix E.2. Sol asks for
1.82 [1.23, 2.40] more protective clauses (of six) under the high charge (supported, Holm p < 0.001), which is 1.58
[0.95, 2.22] more than Opus does. At the true charge, the clauses Sol chose for its own type are worth about +120k
[+83k, +156k] dollars a world more in joint value than those it chose for the other type (a secondary measure;
joint value is the pair's surplus, not Sol's own earnings). Opus's price pass-through is −0.07 [−0.18, +0.05], so
that prediction is not supported; the earlier estimate of 0.52 came from counter-offers alone, compared across
worlds, and we withdrew it. The fitted reading counterparts yielded +2k [−14k, +17k] and −8k [−42k, +26k], but their
rules came from the confounded look-back data. The counterpart that reads Opus's price used the withdrawn slope of
0.52, so this run tests a misspecified reader rather than a well-fitted reader's ability to exploit Opus. The
within-world price result remains unsupported, and the reader-effect estimates cannot establish that disclosure is
harmless.

Of the 2,456 negotiations, 2,417 are valid. Every failure is a CLI service error. The original bundles keep the
failures as missing, and we re-ran 16 of them under separate frozen configurations by an explicit, recorded
decision.

**The earlier pre-registered comparison (v1).** Before v2, we pre-registered a comparison on 60 included worlds
(from 2,729 scanned), 45 of them with a mutually beneficial deal. It differs from v2 in three ways: the two
command-line tools were not equally isolated, the client's task prompt did not state its walk-away point, and the
worlds were not screened for the integrator's headroom over a price-only rule. We do not pool v1 and v2.

**Table E.16. Data center v1 (14 October): Sol 6.1 (Codex) and Opus 5.5 (Claude Code). Differences in a seat's earnings above its outside option, at true costs, on the 45 deal worlds, in percentage points of the value available in a deal ($322k a world); intervals are 95%, with Holm correction across the campaign's primary contrasts. The campaign has eight documented departures from its plan and a partial Gate 5 verdict (Appendix F.5).**

| Primary contrast | Worlds | Estimate [95% interval] | Holm p |
|---|---:|---|---:|
| Head to head: Sol minus Opus earnings, seat-averaged | 45 deal | +59.1 [46.0, 72.1] | 3.2e-11 |
| Firm population: Sol minus Opus earnings, seat-averaged | 45 deal | +8.2 [3.3, 13.2] | 0.0017 |
| Client signs below its walk-away point: Opus / Sol | all 60 | 45% vs 5% (27 and 3 of 60) | 2.4e-7 |

Sol's lead against the firm population is detectable but smaller than the plan's smallest meaningful difference
of 15.5 points ($50k; the 98.3% interval is [2.1, 14.3]). Across v1's pilot and three arms, 1,175 of 1,176
negotiations are valid ($74.41 at list price). The two tools were not equally isolated: Codex's context listed eight
of the operator's own skills, two of them described in benchmark and evaluation terms, whereas Claude Code's context
listed none (Table H.1). Every v1 contrast between Sol and Opus carries that difference. Once v2 stated the
walk-away point, neither model signed below it as client.

Against the firm population, redline fees were the largest part of v1's joint loss (69.9% of Sol's $103.4k a world
and 40.3% of Opus's $70.8k, over all 60 worlds with seats averaged). Opus's next largest part (29.5%) was harmful
agreements: in the 15 worlds where no agreement beats both outside options, it signed anyway. Table E.17 gives v1's
joint loss by pairing, and Appendix E.9 replays it at other fee levels.

**Table E.17. Data center v1: joint loss by pairing ($ thousands per world, all 60 worlds).**

| Integrator / client | Inferior clauses | Harmful agreement | Missed deal | Redline fees | Total |
|---|---:|---:|---:|---:|---:|
| Opus / Sol | 9.3 | 1.2 | 3.7 | 63.3 | 77.5 |
| Sol / Opus | 22.6 | 34.8 | 25.2 | 44.2 | 126.8 |
| Opus / firm | 2.2 | 0.0 | 12.2 | 30.0 | 44.4 |
| Sol / firm | 1.1 | 0.0 | 29.1 | 60.8 | 91.0 |
| Firm / Opus | 15.5 | 41.8 | 12.9 | 27.1 | 97.2 |
| Firm / Sol | 14.3 | 4.0 | 13.8 | 83.8 | 115.8 |

#### Refund

**The four-seat calibration (Section 5.1).** This comparison is distinct from the historical V2.1 results retained in
Tables E.6 and E.9, and from the later provider-free release. It uses version 5.1 of the payment-unit contract and the
second version of the branching policy panel. The frozen selection has 132 seat–case placements, and each model played
each placement twice. The 66 pairs are seat-specific templates, not 66 independent economic mechanisms, because seats
can reuse a base policy. The policy seat has six pair templates in each of its core, stress and frontier strata; its
world seed is 201, and the customer, intake and payments seats use seed 301. We ran no held-out model test, and later
incomplete customer and intake collections are not pooled into this balanced panel.

**Measurement and uncertainty.** The primary measure is the frozen seat-specific strict trajectory score. Within a
stratum, a template's two variants and two repetitions are averaged before the templates receive equal weight, and
the strata are then weighted:

[[eq E.3]] S = Σ_s w_s · (1/|T_s|) · Σ_{t ∈ T_s} p̄_t,

where p̄_t is the share of template t's four episodes that pass, T_s holds the templates of stratum s, and w_s is one
third for each policy stratum and 0.4 and 0.6 for the baseline and difficult strata of the other seats. Conditional
diagnostics keep their weighted coverage: a leaf that is never visited is neither an observed success nor an observed
model error. Policy meaning is the mean of four field checks (eligibility, remedy, amount and liability), not the
share of wholly correct resolutions. Workflow, payment, evidence, contract and operational status remain separate.
The collaboration checks cover requested disclosure, intake quality, confirmation of the current proposal and payment
binding; the payment-binding diagnostic includes allocation and method consistency, not only the proposal identifier.
When the policy seat is evaluated, a passing payment leaf means that the scripted payments seat followed its
obligation; it does not show that the model's proposal was right. The frozen intervals use 20,000 stratified paired
template-bootstrap draws that carry the two variants, the repeats and the model pairing together. Two-sided template
sign-flip tests give the p-values, with Holm correction across all eight comparisons. Shared mechanisms can make
templates dependent, and a single world per seat, sequential model collection and developmental amendments further
limit inference. These are exploratory intervals on this panel, not population rankings or the confirmation of an
original primary hypothesis, and more seeds or repeats would not substitute for new independent templates.

**Table E.19. Refund V2.5 calibration: the eight frozen paired contrasts, in percentage points of weighted strict compliance, with 95% template-bootstrap intervals.**

| Seat | Contrast | Difference [95% interval] | Holm p |
|---|---|---|---|
| Customer | Pro minus Lite | 0.0 [0.0, 0.0] | 1.000 |
| Customer | GPT minus Pro | 0.0 [0.0, 0.0] | 1.000 |
| Intake | Pro minus Lite | 60.8 [44.2, 78.3] | 0.00586 |
| Intake | GPT minus Pro | 0.8 [0.0, 2.5] | 1.000 |
| Policy | Pro minus Lite | 65.3 [54.2, 76.4] | 0.0000610 |
| Policy | GPT minus Pro | 1.4 [0.0, 4.2] | 1.000 |
| Payments | Pro minus Lite | 63.3 [60.0, 67.8] | 0.00342 |
| Payments | GPT minus Pro | 0.0 [−3.3, 3.3] | 1.000 |

The customer, intake, policy and payments seats have 52, 64, 72 and 76 episodes per model, and all 792 included
episodes have replay-audited receipts; the denominator is valid episodes, not every provider attempt. Unweighted
strict pass counts are 52, 32, 24 and 32 for Flash Lite, 52, 63, 71 and 75 for Pro, and 52, 64, 72 and 75 for
GPT-6-sol; these counts do not replace the frozen weights of Figure 5.3. Requiring both variants of a pair to pass
within a repetition gives 100.0%, 31.3%, 0.0% and 36.8% for Flash Lite, 100.0%, 96.9%, 97.2% and 97.4% for Pro, and
100.0%, 100.0%, 100.0% and 97.4% for GPT-6-sol. The zero-width interval in the customer seat reflects a saturated
template pool, not certainty of equal performance on unseen worlds. In the intake seat, the scripted downstream checks
pass whenever they are reached, but Flash Lite reaches them in only 38.3% of weighted trajectories, so that
conditional full score does not measure its policy ability. Because the counterparts are scripted, a full downstream
score in Figure 5.3 does not show a capability of the evaluated model; the figure's operational row covers the 792
included episodes, not every provider attempt.

**Failure checks.** Pro has three strict failures: an intake request that names three relevant facts despite a batch
capacity of two, a one-cent allocation error in a refund whose total is nevertheless correct, and the liability error
in the policy seat described in Section 5.2. GPT-6-sol has one: it selects the correct fallback instrument but writes
it into the ticket's immutable logical refund-method field, so the error is not evidence that funds went to the wrong
destination. All four failures occur in the second repetition, and each first repetition of the same case passes.
Replaying the four recorded actions reproduces their outcomes, and replacing only the erroneous action by a
correction derived from the public rules yields four full-score trajectories. Twelve scripted positive controls pass
and fifteen injected errors are detected. These checks support the local attributions; they do not show that the
verifier has no other defects.

**Figure accounting.** Figure 5.2(d) uses the policy seat only. Its priority order, fixed after the runs, assigns
each failed episode once: first a decision attempted before the required facts, then an invalid request or no
scoreable final resolution, then an observed policy, workflow or payment mismatch, and last a remaining contract-only
error. Overlapping taxonomy tags are not added. For Flash Lite this assigns 26, 4, 18 and 0 of 72 episodes, a total
shortfall of 66.7 points; Pro has one mismatch in 72 (1.4 points), and GPT-6-sol has none. The resolution-mismatch
segment includes policy, workflow and prescribed-payment meaning, not only the four-field policy score. Some premature
candidates also have wrong fields but are counted once, under the first class. The accounting describes the first
applicable failure, not its causal effect.

**Release scope.** The figure data record the digests of the frozen configuration, the merged 792 episodes, the
analysis and the offline audit, and this paper does not change the analysis. The model outcomes remain bound to their
original versioned runner and adapter. The public release adds customer and intake panels, giving 13 public cohorts,
268 placements and 244 distinct case identifiers per seed; the 24 core cases overlap the 76-case policy panel. Its
1,072 provider-free reference trajectories (every cohort under each of the four controlled seats) complete with full
scores, independent replay and audit, and no operational exclusions. They are not 1,072 distinct worlds or additional
model observations. The earlier lower-control results on 11 cohorts (Appendix F.4) remain historical quality-control
evidence, and the expanded release has not been promoted to full publication qualification.

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
| Operational | an episode with no measurement; counted, never scored |

For a unit u (an episode, an action or a part of a grade, depending on the case), the shortfall is the reference's
value minus the agent's, and the rules assign it to the classes in priority order:

[[eq E.2]] S(u) = V_ref(u) − V(u) = Σ over classes c of S_c(u),

where c ranges over the six scored classes and each part of the loss goes to the first class whose rule it meets. The
priority order makes the decomposition an accounting identity, not a causal attribution.

**Rules per case.** *Housing.* The unit is the episode (one world under one landlord kind). The shortfall is the
reachable reference's net minus the tenant's net under v15's primary measure (the reply-conditioned measure), and the
rules apply in the order procedure, contrary to information held, information not acquired, commitment error, worse
terms and interaction cost. A known lemon signed at a rent that its lemon value covers is judged on terms, because the
reference does the same. Signing a revealed lemon counts as acting contrary to information held: v15's task prompt
states how landlords price, so the acceptance that reveals a lemon follows from a stated rule. The rules are v14's.
They read seat 0's decisions from v15's seat-0 receipts, the reference is `inspect_lowball` scored as v15's scorer
scores it, and every episode's gap reproduces the published v15 analysis. v14's class totals (Gemini $78.9, GLM $142.3
and Luna $144.3 a world) remain in the source package. *Procurement.* The unit is the action. Each action's loss
against the best policy (these losses sum to the decision loss) goes to a class according to what the action did. A
request to the recorded supplier counts as information not acquired only when the episode never tests a newcomer, and
as acting contrary to information held otherwise. *Data center.* The unit is each part of a negotiation's grade. No
deal is a commitment error, labelled by the side that walked away. Allocation loss in a world with positive available
surplus counts as worse terms, while allocation loss in a world without positive available surplus is a harmful
agreement, which is a commitment error. Redline fees are interaction cost. Figure 5.2c separates harmful agreements
from missed beneficial deals. We count signing below one's own walk-away value separately: that individual loss is
not an additive component of joint loss, although the same agreement may also destroy joint value. *Refund V2.1 (historical).* The
parts of the published gap decomposition map onto the classes: deciding before a required fact maps to information
not acquired, a wrong decision to acting contrary to information held, and re-asked or unknown facts and the null
refund method to procedure and format. The V2.5 panel instead counts each failed episode once, under the first
applicable class (Appendix E.4).

**Interpreting negotiation costs.** A redline that improves the final agreement's joint value by
$100k while costing $25k reduces total shortfall by $75k: allocation loss falls by $100k and
interaction cost rises by $25k. The score therefore credits improvements net of their cost. The
full-information reference knows both private types and can propose the best agreement in the
free opening move. Its advantage includes negotiation costs that agents with limited information
may need to incur; the decomposition does not identify which costs were avoidable. It also does
not establish robustness to the chosen $25k fee per additional redline. Appendix E.9 tests
scoring sensitivity by replaying the same actions at alternative fees; measuring behavioural
adaptation would require new model runs under pre-registered fee settings.

**Table E.5. Housing and Procurement, every subject ($ per world; Housing v15 on the 260 main worlds of Table 5.2, GLM, Sol and Opus from their pre-registered addenda; Procurement on the 20 pre-registered worlds of Table 5.3, each world the mean of its two plays).**

| Class | Housing Gemini | Housing Luna | Housing Sol (addendum B) | Housing Opus (addendum B) | Housing GLM (addendum A) | Proc. Sol | Proc. Opus | Proc. Gemini | Proc. Luna |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Information not acquired | −0.2 | 14.9 | 0 | 1.4 | 18.9 | 17.5 | 51.0 | 49.4 | 55.4 |
| Acted contrary to information held | 1.9 | 22.2 | 0 | 0 | 49.6 | 13.9 | 0 | 0 | 0 |
| Worse terms | 40.7 | 54.3 | 15.7 | 38.8 | 40.1 | 0 | 0 | 0 | 0.5 |
| Commitment error | 8.9 | 8.6 | −0.0 | 6.3 | 7.2 | 0 | 0 | 0 | 0 |
| Interaction cost | −0.3 | −0.1 | −0.4 | −0.4 | −0.2 | 1.1 | 0.2 | 1.9 | 2.2 |
| Procedure and format | 0 | 0 | 0 | 0 | 11.7 | 0 | 0 | 0 | 0 |
| Total | 51.1 | 99.9 | 15.3 | 46.1 | 127.3 | 32.5 | 51.2 | 51.2 | 58.1 |

Housing's totals reproduce the published v15 differences from `inspect_lowball` (51.13 and 99.92 $ a world; GLM's addendum row R3, 127.32; Sol's and Opus's addendum row R, 15.34 and 46.07), and every one of the 520 main episodes per model completed, so no world is excluded. Main-world means average both landlord arms within a world. We retain negative amounts where the model beats the reference. The inspection-cost row is a residual after the earlier classes, so inspection costs already inside other classes are not counted again.

**Table E.6. Data center development ($k joint value lost per deal world) and historical Refund V2.1 (points of episodes unresolved).**

| Class | DC Sol int. × Opus | DC Opus int. × Sol | DC Sol × firm | DC Opus × firm | Refund DeepSeek | Refund Gemini 2.5 FL | Refund GPT-5.6 Luna | Refund Grok |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Information not acquired | — | — | — | — | 44.2 | 0 | 15.0 | 29.2 |
| Acted contrary to information held | — | — | — | — | 0 | 0 | 0 | 0.8 |
| Worse terms | 35.4 | 12.2 | 9.1 | 4.8 | 0 | 0 | 0 | 0 |
| Commitment error | 0 | 0 | 32.0 | 6.9 | — | — | — | — |
| Interaction cost | 46.2 | 66.3 | 80.2 | 29.8 | — | — | — | — |
| Procedure and format | 0 | 0 | 0 | 0 | 5.8 | 98.3 | 5.8 | 17.5 |
| Total | 81.5 | 78.6 | 121.3 | 41.5 | 50.0 | 98.3 | 20.8 | 47.5 |

In these development runs, 7 of Sol's 8 lost deals against the firm script occurred when the script walked away from
Sol's last offer. Signing below one's own walk-away point, which the table does not include, occurred for Opus as
client in 12 of 52 worlds against Sol (in 4 of them Opus proposed the losing terms itself) and in 2 against the firm
script, and for Sol as client in 1 against the firm script; neither model did so as integrator.

### E.6 Two frontier agents across three cases

**Table E.7. Development comparisons of Opus 5.5 and Sol 6.1 on the three cases both played; Data-center confirmatory results are in Table 5.4 (v2) and Table E.16 (v1).**

| Case (worlds) | Measure | Opus 5.5 | Sol 6.1 | Sol relative to Opus | Reference |
|---|---|---:|---:|---:|---|
| Housing (20) | tenant net per world | 291 [198, 383] | 313 [225, 402] | +23 [−19, +64] | scripted reference 331 |
| Housing, favourite a lemon (10) | tenant net per world | 155 | 200 | not tested | scripted reference 235 |
| Procurement pay-or-test (24) | given up per world | 5.4 [1.2, 10.6] | 1.0 [0.2, 2.1] | 4.4 [0.6, 9.0] less given up | best policy gives up 0 |
| Procurement, record evaluation set (18) | worlds solved | 18 | 16 | regret −20 [−48, +7] (Opus lower) | informed policy 18 |
| Data center development, firm population (52) | earns, integrator / client ($k) | 122 / 107 | 139 / 130 | +17 [−10, +44] / +23 [−2, +48] | first-offer stand-in 122 / 114 |
| Data center development, head to head (52) | earns, integrator / client ($k) | 60 / 25 | 308 / 276 | +248 / +251 | |

### E.7 Current shortfall panels: scope and uncertainty

Figure 5.2 is descriptive accounting computed after the runs, not an additional pre-registered test. Its Data-center
panel uses all 80 included worlds of v2, including 8 with no positive available surplus, whereas Table 5.4's earnings
contrasts use the 72 worlds with a deal. Both focal roles receive equal weight within each world, after the
integrator's two plays against the firm client are averaged. We do not add individual signings below the walk-away
point to joint loss: as integrator against the firm client, Opus signed below its outside option in 2 of 160 plays and
Sol in none, and as client neither model did so in 80. Table E.6 preserves the earlier development decomposition on
its 52 deal worlds, and Table E.17 gives v1's decomposition by pairing.

**Table E.8. Data-center joint loss by pairing in v2 ($ thousands per world, all 80 worlds; the integrator's two plays against the firm client averaged within each world).**

| Integrator / client | Inferior clauses | Harmful agreement | Missed deal | Redline fees | Total |
|---|---:|---:|---:|---:|---:|
| Opus / Sol | 12.6 | 0.0 | 24.3 | 74.4 | 111.4 |
| Sol / Opus | 22.4 | 0.0 | 26.1 | 68.1 | 116.7 |
| Opus / firm | 2.2 | 0.0 | 9.1 | 40.0 | 51.3 |
| Sol / firm | 1.7 | 0.0 | 45.9 | 73.9 | 121.6 |
| Firm / Opus | 17.0 | 0.0 | 48.3 | 50.6 | 115.9 |
| Firm / Sol | 12.4 | 0.0 | 53.6 | 92.8 | 158.8 |

**Table E.9. Distribution of total shortfall (each case's own units). The Refund rows are the historical V2.1 panel; the V2.5 results are in Table E.19.**

| Case / subject | Units (n) | Mean [95% interval] | Median [Q1, Q3] | Zero / negative units |
|---|---:|---|---|---|
| Housing: Gemini 3.8 Flash | 260 | 51.1 [38.3, 63.9] | 29.9 [0.0, 98.3] | 60 / 45 |
| Housing: GPT-6 Luna | 260 | 99.9 [83.8, 116.0] | 72.1 [0.0, 167.6] | 46 / 32 |
| Housing: Sol 6.1 (addendum B) | 260 | 15.3 [6.2, 24.5] | 0.0 [0.0, 53.7] | 78 / 59 |
| Housing: Opus 5.5 (addendum B) | 260 | 46.1 [33.9, 58.2] | 27.8 [0.0, 96.0] | 61 / 47 |
| Housing: GLM 5.3 Flash (addendum A) | 260 | 127.3 [105.2, 149.4] | 79.9 [0.0, 212.8] | 36 / 39 |
| Procurement: Sol 6.1 | 20 | 32.5 [23.8, 41.3] | 33.3 [21.5, 48.7] | 0 / 0 |
| Procurement: Opus 5.5 | 20 | 51.2 [46.3, 56.2] | 50.2 [45.1, 57.7] | 0 / 0 |
| Procurement: Gemini 3.8 Flash | 20 | 51.2 [46.3, 56.2] | 50.2 [45.1, 57.7] | 0 / 0 |
| Procurement: GPT-6 Luna | 20 | 58.1 [52.3, 63.9] | 57.2 [50.4, 67.1] | 0 / 0 |
| Data center: Opus 5.5 | 80 | 83.6 [68.8, 98.4] | 57.2 [27.8, 137.3] | 0 / 0 |
| Data center: Sol 6.1 | 80 | 140.2 [120.6, 159.7] | 117.3 [87.5, 189.8] | 4 / 0 |
| Refund V2.1: GPT-5.6 Luna | 6 | 20.8 [-1.0, 42.7] | 20.0 [3.8, 28.8] | 2 / 0 |
| Refund V2.1: Gemini 2.5 Flash Lite | 6 | 98.3 [94.0, 102.6] | 100.0 [100.0, 100.0] | 0 / 0 |

Opus and Gemini bought from the recorded supplier in every play, so their Procurement rows coincide. The intervals
are Student t intervals over independent worlds (for Housing after averaging the arms, and for Data center after
averaging the focal roles), or over the six fixed Refund V2.1 cases after averaging 20 episodes per case. They describe
variation in these panels; they do not establish a model ranking or coverage of a field population. They are
descriptive intervals that we derived afterwards, not replacements for the campaigns' pre-registered analyses. A
Refund interval can exceed the score's 0–100 bounds; we leave it untruncated to expose the weakness of an
approximation with six fixed cases. Housing has one retained run per world and landlord arm, so its run-to-run variance is unmeasured. Procurement and
Data center have two plays per world: the two plays of a world scored identically in 7 to 20 of the 20 Procurement
worlds, depending on the model, and ended identically in 47 (Opus) and 28 (Codex) of the 80 Data center worlds
(Appendix F.1). Refund V2.1 has repeated episodes within fixed cases, and the derived
evidence retains its per-case outcome distributions. The source package includes component-level intervals,
distributions, per-world amounts and input digests, together with a reproduction script that makes no provider
call.

### E.8 Exact values for Figure 5.2

The figure draws the estimates below. Each component keeps its case's native units and classification rules, and
the figure adds no new analysis or cross-case aggregate.

**Table E.10. Shortfall by case. Housing uses v15 (Table 5.2) under its primary measure; Data center uses v2, the comparison of Table 5.4; Procurement uses the 20 pre-registered worlds of Table 5.3. Refund uses the policy seat of the V2.5 calibration.**

**(a) Housing**

Dollars per main world below the reachable scripted reference (`inspect_lowball`), under v15's measure v2.

| Component | Gemini 3.8 Flash | GPT-6 Luna | Sol 6.1 (Codex, addendum B) | Opus 5.5 (Claude Code, addendum B) | GLM 5.3 Flash (addendum A) |
|---|---:|---:|---:|---:|---:|
| Information not acquired | −0.2 | 14.9 | 0.0 | 1.4 | 18.9 |
| Contrary to held information | 1.9 | 22.2 | 0.0 | 0.0 | 49.6 |
| Worse lease terms | 40.7 | 54.3 | 15.7 | 38.8 | 40.1 |
| Lease commitment error | 8.9 | 8.6 | −0.0 | 6.3 | 7.2 |
| Procedure or format | 0.0 | 0.0 | 0.0 | 0.0 | 11.7 |
| Inspection cost | −0.3 | −0.1 | −0.4 | −0.4 | −0.2 |
| **Total shortfall** | **51.1** | **99.9** | **15.3** | **46.1** | **127.3** |

The two landlord arms are averaged within each of the 260 main worlds, and no episode is missing. GLM (addendum A) and the two command-line agents (addendum B) played in pre-registered addenda outside v15's contrasts. GLM's procedure losses are actions the environment refused, chiefly malformed commits ($5.7 a world, 14 episodes) and offers on listings already taken ($2.1, 5 episodes). Negative amounts mean that the model did better than the reference in that class; they are not drawn in Figure 5.2.

**(b) Procurement**

Dollars per world below the best policy given the available information, on the 20 pre-registered worlds of Table 5.3 with two plays each.

| Component | Sol 6.1 | Opus 5.5 | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| Information not acquired | 17.5 | 51.0 | 49.4 | 55.4 |
| Contrary to held information | 13.9 | 0.0 | 0.0 | 0.0 |
| Worse terms | 0.0 | 0.0 | 0.0 | 0.5 |
| Award checks | 1.1 | 0.2 | 1.9 | 2.2 |
| **Total shortfall** | **32.5** | **51.2** | **51.2** | **58.1** |

The panel shows all four models, with each world the mean of its two plays. Sol runs through Codex, Opus through Claude Code, and Gemini and Luna through OpenRouter. We re-derived the decision loss from every play's replayed trace and matched every world against the read-outs. The pre-registered rules file an award's whole loss under information not acquired when the award came before a worthwhile newcomer test, including the part caused by a worse quantity. For Luna, which ordered 50 units where 55 was best in 15 of 40 plays, that part is $6.33 a world; if the loss were split into its timing and terms parts, Luna's worse-terms loss would be $6.85, its whole loss beyond paying the premium. The other three models made no such awards.

**(c) Data center**

Thousands of dollars of joint value lost relative to the full-information bound, in v2 against the firm counterparts.

| Component | Opus 5.5 | Sol 6.1 |
|---|---:|---:|
| Inferior contract clauses | 9.6 | 7.1 |
| Harmful agreement | 0.0 | 0.0 |
| Missed beneficial deal | 28.7 | 49.7 |
| Redline fees | 45.3 | 83.4 |
| **Total shortfall** | **83.6** | **140.2** |

All 80 worlds, with both focal roles averaged within each world. Joint outcomes reflect both parties' actions.

**(d) Refund**

Percentage points below strict trajectory compliance in the policy seat of the V2.5 calibration.

| Component | Gemini 2.5 Flash Lite | Gemini 2.5 Pro | GPT-6-sol |
|---|---:|---:|---:|
| Required facts skipped | 36.1 | 0.0 | 0.0 |
| Procedure or format | 5.6 | 0.0 | 0.0 |
| Resolution mismatch | 25.0 | 1.4 | 0.0 |
| **Total shortfall** | **66.7** | **1.4** | **0.0** |

72 episodes per model; each failed episode is counted once, under the first applicable class (Appendix E.4). The
historical V2.1 panel (GPT-5.6 Luna 20.8, Gemini 2.5 Flash Lite 98.3 points) is in Tables E.6 and E.9. In it, Flash
Lite asked again for a fact it had already been given in 81% of its episodes, which ended the case with no decision
(80.8 of its 98.3 points), and in most of the rest wrote the refund method as null where the format requires "none"
(16.7 points); it reached the answer key's outcome in 18% of episodes and a wrong outcome in none.

We omit rows that are zero for every displayed model, and rounded components may not add up to rounded totals.
Signing below one's walk-away value is a separate, individual outcome. In v2 neither model signed below its walk-away
value as client, whether against the firm integrator or head to head (0 of 80 each); as integrator against the firm
client, Opus signed below its outside option in 2 of 160 plays and Sol in none. Table E.16 gives v1's counts.

### E.9 Negotiation fees in v1: fixed-action sensitivity

We replayed all 240 valid firm-population negotiations of v1 (Table E.16; 60 worlds, two models and two focal seats)
at six fees per paid redline: $0, $5k, $12.5k, $25k, $50k and $100k. All original final states and six score leaves
matched the saved states and receipts. The 1,440 fee-specific trajectories used the environment's own transition and
scoring functions and held offers, clauses, notes, signatures and walk-aways fixed. This is an exploratory analysis
performed after the runs, not another pre-registered test or a model rerun. The opening move remains free of fees. v2
pre-registered a smaller replay of the same kind (Section 5.2).

The two samples answer different questions. v1's joint loss covers all 60 worlds, whereas its pre-registered earnings
contrast (Table E.16) uses the 45 worlds with positive available joint surplus. "Deal-feasible" describes those worlds,
including negotiations in them that ended without agreement; it does not select only signed contracts. Means first
average both focal seats within a world and then average across worlds, so the independent unit is the world, not each
correlated seat observation.

**Table E.11. Fee sensitivity on the 45 deal-feasible worlds ($ thousands per world; fixed actions). Sol earnings lead is Sol minus Opus against the firm population. Lower joint loss is better; a positive earnings lead favors Sol.**

| Fee per redline | Sol joint loss | Opus joint loss | Sol earnings lead |
|---|---:|---:|---:|
| 0 | 38.9 | 28.5 | +54.8 |
| 5 | 56.0 | 35.6 | +49.1 |
| 12.5 | 81.7 | 46.2 | +40.6 |
| 25 | 124.4 | 63.8 | +26.4 |
| 50 | 210.0 | 99.1 | -1.9 |
| 100 | 381.1 | 169.6 | -58.6 |

On these 45 worlds, fees amplify Sol's disadvantage in joint loss but do not create it: Opus retains the lower loss at
zero fees. Sol's own earnings lead, by contrast, grows when fees are removed. Because behaviour is held fixed, each
model's earnings are a linear function of the fee, and the two models' earnings are equal at approximately $48.3k per
redline. This threshold describes the recorded actions; it is neither an optimal fee nor a prediction of how either
agent would respond to a different fee.

**Table E.12. Joint-loss sensitivity across all 60 worlds ($ thousands per world; fixed actions). This is v1's full population, including 15 worlds without positive available joint surplus.**

| Fee per redline | Sol joint loss | Opus joint loss |
|---|---:|---:|
| 0 | 31.1 | 42.3 |
| 5 | 45.6 | 48.0 |
| 12.5 | 67.3 | 56.6 |
| 25 | 103.4 | 70.8 |
| 50 | 175.7 | 99.4 |
| 100 | 320.3 | 156.5 |

Across all 60 worlds, fees contribute 69.9% of Sol's and 40.3% of Opus's total joint loss at $25k per redline. On this
population the joint-loss ranking reverses without fees, with equality near $6.4k per redline, so the 45-world result
cannot establish a fee-independent ranking for the full evaluation set. On the 45-world subset, the corresponding fee
shares are 68.8% and 55.3%.

**Useful changes and limits.** Among the paid redlines that the models authored in the 45 deal-feasible worlds, 23 of
Sol's 150 and 5 of Opus's 48 increased the immediate full-information clause value by more than the $25k fee. One Sol
redline improved clause value by $87.5k, a net improvement of $62.5k. These are local comparisons: an edit may later be
undone, and a negotiation may remain unsigned. This count of clause value does not capture price concessions or the
information value of negotiating. The fee shares include both parties' fees, whereas these counts include only the
focal model's edits. The full-information reference keeps its advantage, and this analysis neither validates the fee's
empirical calibration nor measures adaptation to it.

The source package retains the supplied analysis, its reproduced outputs, its input hashes and the specific redline
discussed above. The reproduction uses the retained campaign logs, which the compact package does not include in
full.

### E.10 TERMS-Bench reimplementation: a reproduction in progress

This is a negative result in progress, not evidence for the four cases. It shows that an external benchmark's
environment and counterparts can run as a family on AERead's runtime, and what a faithful port requires.

TERMS-Bench evaluates bilateral price negotiation against counterparts whose type is hidden [TB]. We reimplemented,
from the paper's description, its alternating-offer environment, three of its six counterpart families (Candid,
Taciturn and Expressive) and four of its measures as one AERead family. The counterpart runs as a scripted seat, and
its random draws are sealed each turn, so replay recomputes the counterpart's moves as well as the scores. We did not
implement the Oracle-Cue reference or the gap measures built on it, the urgency regime, type-belief error or the other
three families, and counterpart messages are templates. The corpus has 30 cases, 15 with a zone of agreement and 15
without, each played once.

**Table E.18. TERMS-Bench reimplementation: two of the paper's agents on the same 30 cases against scripted
counterparts, beside the paper's values. Agreement and surplus are computed over the cases with a zone of agreement
(15 for GPT-4o-mini, 12 for GLM-5.1).**

| | GPT-4o-mini | GLM-5.1 | Paper: GPT-4o-mini | Paper: GLM-5.1 |
|---|---:|---:|---:|---:|
| Agreement rate where a deal exists (AGR+) | 0.80 | 1.00 | 0.522 | 0.951 |
| Surplus efficiency (SE+) | 0.035 | 0.458 | 0.196 | 0.668 |
| Conditional surplus efficiency (CSE+) | 0.044 | 0.458 | 0.363 | 0.721 |

The paper's surplus efficiency comes from its Table 16 (overlap regime, mean of the three families played here); its
agreement and conditional surplus efficiency come from its Table 2, which pools six families and three regimes, so
those two comparisons are looser. GLM-5.1 has 12 cases because its three malformed moves removed those episodes.

The reimplementation orders the two agents as the paper does on all three measures, but absolute levels are lower for
both, and for a third model. A review of the port after these runs traced the shift to four departures from the
paper's protocol rather than to the agent, whose interface in the paper is also one stateless call per round. First,
our prompt does not state the agent's payoff or the rule against accepting above its reservation value. Second, its
observation differs from the paper's. Third, a malformed move removes the episode where the paper applies a fallback;
under that fallback, GLM-5.1's surplus efficiency would be 0.520 over all 15 cases. Fourth, our price range and zone
widths are wider than the paper's.

**The reproduction.** We have built a pre-registered reproduction with those fixes, and it stopped at its first check: one of the paper's fixed-concession baselines (FC10) scores 0.307 here against the paper's 0.266, while
the other two match. The paper states how much the baselines concede (1%, 10% or 30% of the remaining distance per
offer) but not how they open or accept. No agent has played the reproduction. The paper reports critical violations
by GLM-5.1 in 5% of cases without a zone of agreement for these three families; at that rate, 15 such cases would show
none about half the time, and ours showed none. The port also exposed a harness effect. On one provider route, any
specified reasoning budget suppressed deliberation, and GLM 5.3 Flash breached its own reservation value in 13 of
30 cases, against the paper's band of 0 to 2.06%. With no reasoning setting specified, it breached in 2 of 30 and its
surplus efficiency rose from 0.40 to 0.53; the comparison above uses that setting. This is why the reasoning condition
is part of each run's frozen configuration. The runtime's support for the scripted seat that this family uses is now
on the main branch.

## Appendix F. Quality control in detail

This appendix describes only the checks that we built and applied to the four cases, with two caveats that apply
throughout. First, the initial quality-control profiles and reference-run tests were written after development; only
the agreement's confirmatory run followed its profile and a dry run that made no provider call. Second, we do not
describe rules of the quality-control standard that were not applied to these cases.

### F.1 Profiles and gates

The quality-control standard defines six quality-control gates, together with the rule that a change to any bound
input reopens them, and a repository test rejects a registered family that has no profile. Each of the four current
designs now has a section in its family's profile with a typed status and a blocker for each gate (Table F.1), and
none passes Gates 1 to 5. Housing v14 is `partial` throughout (v15, discussed below, passes four of the five).
Procurement's harder evaluation set, used in Table 5.3, passes Gates 0, 1, 2, 3 and 5 and is `partial` at Gate 4
(profile section 8.2). Its environment and its registration with the runtime reached the main branch on 20 October,
the registration by the owner's override without a review by someone other than its author. Its 12 published bundles
replay through the runtime's command line, 432 of 432 receipts, among them 100 from five scripted baselines that
played the pre-registered worlds with no model, each scoring exactly as the reference scores its moves. Gate 4 stays
`partial` because the command-line agents take no seed. Gate 1 passes on the exact-reference route that the standard
added on 21 October: the reference is exact, and the six shortcuts that the profile names (paying the premium, three
fixed testing rules, the one-step rule and the kind-blind shortcut, the last two found in earlier versions) each lose
at least $10 in every pre-registered world. Rules that do make the decision come closer: looking two newcomers ahead
loses $8.38 a world, and as little as $0.09 in one world. Before the route existed, we tried to establish measured
headroom with a frozen control that tests, pre-registered before its plays. The control tested but lost to the
kind-blind shortcut, so by that route only 2 of the 20 pre-registered worlds passed (Appendix E.4). A control weaker
than the shortcuts measures itself rather than the worlds, which is why the standard now uses the exact reference
where a case has one. The models' two plays of a world scored identically in all 20 worlds for Opus and Gemini and in 7
for Sol, so the effective sample is the 20 worlds, as the world-mean intervals assume. The earlier pay-or-test v1
evaluation set (Table E.14) fails Gates 1 and 3. v2 passes the scripted Gate 3 checks and its screen meets the
exact-reference route, but its pilot stopped at sizing and the case moved to v3 (Appendix F.4). The agreement's
development sets fail Gate 1 because inclusion and type assignment were confounded. Its first confirmatory run (v1)
used the included evaluation set, which is still `partial` at Gate 1 because of the client seat's construct limit and
incomplete measured-headroom qualification (Appendix F.2). Refund V2.5 fails Gate 3 on its lower controls (Appendix
F.4) and is `partial` at Gates 1, 2 and 4: a constant full refund solves 38 of its 180 policy cases, its schema accepts
a null refund method that its verifier then fails, and no adapter admits a model profile. Its developmental
calibration with three models (Section 5.1) is exploratory rather than pre-registered, so Gate 5 has not run, and the
expanded public release is qualified only for environment conformance.

We pre-registered and ran Housing v15 after these profiles were first written. It passes Gates 1, 2, 3 and 5 and is
`partial` at Gate 4:
- **Gate 1.** Its evaluation set is screened for headroom against `inspect_then_sign`, and its holdout changes a
  mechanism. Scored per world afterwards, every rule that skips the decision loses at least $25 to the best informed
  tenant in every world (the smallest losses are $28.06 for never trading, $92.37 for signing anything, and $25.69 for
  inspecting and then signing at the asking rent). `inspect_lowball`, which inspects the favourite, offers $0 and signs
  the counter-offer when the inspected value covers it, comes within $25 of the reference in 229 of 260 worlds and
  equals it in all 60 worlds with a sound favourite. The headroom this evaluation set leaves therefore lies in carrying
  out a simple procedure, and every model falls short of that rule on average (Table 5.2).
- **Gate 2.** We sealed a bundle of golden receipts through its builder, and all 1,720 episodes replay.
- **Gate 3.** Its beatability rule was pre-registered before any result, both models pass it, and its receipts score
  the tenant who decides.
- **Gate 5.** Its sizing record and its A/A arm preceded the freeze of the configuration.
- **Gate 4, partial.** The pre-registered one-call probe of each model profile ran only after the freeze. It found
  structured output working and both reasoning tiers in effect: every sealed call's raw response carries the
  provider's count of reasoning tokens, which the kernel's OpenRouter client does not copy into its own field.

The agreement's v2 confirmatory run (Table 5.4) passes Gate 3 for its integrator seat: the price-only rule leaves
headroom in every deal world by construction, the best informed integrator earns far more than either model, and the
evaluation set separates the models. It is `partial` at Gates 0, 1, 2, 4 and 5. Its registry entry awaits a review by
someone other than its author and its code is not yet on the main branch, so replay through the runtime's command line
has not run. Its grid reference is a lower bound, so the exact-reference route does not apply, and a frozen control played on the
already frozen evaluation set could only count the worlds that pass. Gate 1 can therefore pass only on a new
evaluation set with an exact reference and a shortcut screen in every world; the client seat also retains its
construct limit. Scoring every scripted integrator rule against the grid reference shows what a new set must remove: a shortcut comes within $25k of it in 12 of the 80 worlds, namely all 8 in which no deal is possible (walking
away earns the reference, and every scripted rule walks away) and 4 of the 72 deal worlds, three of which have a total
ceiling below $25k. The shortcuts still lose $104.8k to $205.2k per deal world on average, so the evaluation set
separates the models in aggregate. A model's two plays of a world ended identically in 47 of 80 worlds for Opus and 28
for Codex, and some fixed negotiating style comes within $25k of the reference in 27 of the 72 deal worlds. Through the
environment's hooks, the full-information pair loses nothing in any of its 80 worlds.

We applied the rule that a changed control requires a new frozen configuration: Housing's 36 refused episodes ran
later under their own configuration, and Procurement's corrected schema ran under new configurations.

**Table F.1. Benchmark QC gates.**

| Gate | Question | Stops when | In the four cases |
|---|---|---|---|
| 0. Profile | Is there a place to record each gate's verdict? | the family has no QC profile | an earlier Procurement design's construct check found a public-price rule beating the model by $28.50 a world; with no profile, the verdict was read as a campaign finding and lost. The profiles followed initial development; the agreement's confirmatory run followed its profile |
| 1. Task distribution | Are the worlds valid, distinct, split and informative? | an unverified bound, duplicates across clusters, development and holdout overlap, no measured headroom | Housing v14 includes a seed on the tenant's own structure and reads quality afterwards, with a holdout from a disjoint seed range; pay-or-test v1 fails: a rule reading only public information solves 23 of 24 worlds; v2's screen meets the exact-reference route, but its 50-episode pilot found almost no newcomer testing and stopped at sizing; the pre-registered v3 evaluation set passes on that route, every named shortcut losing at least $10 in every world |
| 2. Environment and verifier | Do actions change the intended state, and is every score rebuilt from sealed evidence? | invalid actions mutate state, an oracle disagrees, hidden state leaks, replay differs | Housing v14 has 1,764 scored completions and 36 failure exclusions: completed receipt scores replay from sealed events, and failure rows are verified as exclusions; the headline measure is computed outside the receipts. Procurement's harder evaluation set passes: its 12 published bundles replay through the runtime's command line, 432 of 432 receipts |
| 3. Construct and baselines | Does a better-informed policy do better, and do shortcuts lose? | stronger and weaker policies indistinguishable, a shortcut drives the score | pay-or-test v1 fails: Procurement's fixed rules give up $45.7 to $146.1 a world, but a one-step comparison reaches the best policy to within $0.06; v2, built after the runs, passes for scripted policies: every screened rule, the one-step rule included, gives up at least $10 in every world; Refund V2.5 fails: under a rule committed before its controls ran, naive controls come too close to the reference in three of four seats |
| 4. Attribution and controls | Does the result support the attribution it claims? | a control that was not pre-registered changes, the matrix is incomplete, the block cannot carry the claim | the three v14 frozen configurations differ in model and route and also in reasoning tier, sampling and cost ceiling, a choice recorded in the configurations but not stated in the contract; data-center claims name their counterparts |
| 5. Confirmatory reliability and publication | Was the comparison sized, frozen and executed without tuning on outcomes? | incomplete pilot, a frozen control changed, selective missingness, a guardrail no behaviour can fail | Housing v14 has no sealed sizing record. The agreement's confirmatory run completed pilot, sizing, freeze and execution; its status is `partial` pending closure of analysis-digest and exclusion-verification discrepancies (F.5). Procurement's pre-registered test passes: its plan preceded every play, it ran as pre-registered, and its bundles are published and replay |

### F.2 Checks applied to the four cases

**Table F.2. What each kind of verifier must be shown to do, and how the four cases show it.**

| Kind | Must be shown | How it is shown in the four cases |
|---|---|---|
| Answer | the key is correct and complete for every included case | Refund: inclusion requires the policy's public compiler to reproduce the hand-written reference resolution on every case |
| Rule | every rule is stated to the agent, and each check fails on a counterexample | Procurement tests most of the rules its task prompt states against the environment; the agreement case tests its stated walk-away cost; two checks (the agreement's oracle grade and Housing's ceiling) have mutation tests; a rule left unstated or a schema that disagrees with its parser is a defect |
| Value | the reference agrees with the environment, and a simple rule does not already match it | each reference is played on every world (below); Procurement computed its one-step rule before play, and that rule matches its best policy |
| Relative | the counterparts are named and the gap is reported per counterpart | the data-center counterpart table (Table E.3) |
| Rubric | the rater agrees with people and resists gaming | not used |

- **Regeneration.** In all four cases a test reproduces every committed evaluation set byte for byte from its
  generator and seeds.
- **Reference run on every world.** Tests written after initial development play each reference through the real
  environment and verifier with no model. The Housing reference and a full-information tenant play all 600 v14
  episodes, reproducing the published per-episode values and reaching the ceiling in every episode (offline, against
  the same functions that wrote the bundle). Procurement's best policy equals the environment's average over the 27
  type profiles in all 24 worlds of the earlier evaluation set. On the harder evaluation set, the best policy and the
  one-step rule equal their averages over 400 plays through the environment, within four standard errors, on all 12
  pilot worlds and all 20 worlds of the pre-registered test; we checked those 20 worlds on 20 October, after the runs.
  The Housing full-information tenant reaches the ceiling on all 320 v15 worlds. The data-center oracle pair loses
  nothing in all 116 worlds of both development sets, against an optimum that the test computes independently, in
  all 60 worlds of v1's evaluation set and in all 80 of v2's; we checked v2's worlds on 20 October, after its runs. A
  scripted dry run of 120 negotiations covered all 60 included agreement worlds before the confirmatory run. Refund
  V2.5's release requires the reference to receive full credit on every case. The initial tests were written after
  development.
- **Replay.** The kernel's replay recomputes each receipt's own score from its sealed events without any provider
  call. It covers the 1,764 completed Housing v14 receipts (the other 36 rows are verified exclusions for operational
  failure), the development agreement receipts, which were replayed in-line, and all 1,295 scored receipts from the
  agreement's dry run, pilot and three confirmatory arms, which were replayed offline. We checked one failure receipt
  separately for its digest and seal, because the pinned driver cannot classify exclusions. Replay also covers the
  procurement panels' receipts, replayed in-line, the historical Refund V2.5 audit's 816
  provider-free trajectories (174 of them distinct), and the later release's 1,072 scripted trajectories. The 792
  model episodes of the Refund calibration were audited for seals, routes and offline replay on their own versioned
  runner. The replay certificate does not cover two headline measures.
  Housing's seat-0 measure is computed by case code over each episode's outcome, whereas the receipts' own scores
  total all six tenants; the derived analyses of Table 5.2 re-derived the measure from the sealed event logs, and we
  re-extracted and regenerated it exactly on 16 October. Procurement's original report read an unsealed action list
  through an unpinned reference. The reanalysis of 16 October audits all 144 receipts (96 under the final task prompt
  and 48 under the earlier one), reads the parsed actions from their sealed logs, and pins the extraction, the
  reference, the report and the case inputs. Every per-world loss and the intervals of Table E.14 reproduce. This is a
  separately verified derivation; we have not inserted decision loss into the original receipts. The Housing receipts
  also name the model for the five tenant seats that a script played; the true seat map is in an unsealed log.
- **Inclusion before types.** After development and before the confirmatory run, the data-center agreement gained an
  evaluation set filtered by its own inclusion criteria: 60 worlds from 2,729 scanned, each included on its public
  parameters and the type prior before its hidden charge exists, and then given types drawn independently of its
  design cell (χ² p 0.46; the same test rejects the pattern of the development sets). Tests play every shortcut
  through the environment for every pair of types and confirm the loss that the inclusion screen assigned, and the
  oracle pair loses nothing in all 60 worlds. A separate 12-world pilot and the 60-world confirmatory run (v1) have
  been completed; the pilot supplied the sealed sizing record. v2's evaluation set applies the same criteria to fresh
  seeds and adds a headroom screen against one control, the price-only rule (80 worlds included of 5,436 scanned).
  This is evidence of play and variance, not a completed headroom verdict across all controls. The client seat still
  fails the dependence-on-counterpart-type rule.
- **Visibility.** In Housing, Procurement and Refund, tests check that named hidden fields are absent from the
  observations; the agreement case has no such test.
- **Paired plans.** A Housing test rebuilds the six v14 plans that ran, matches their identifiers, and asserts that
  they differ only in model and route, reasoning tier, sampling and cost ceiling, the last three being choices that the
  contract did not state. Refund tests that a plan has a single agent seat, and the agreement case tests its
  evaluation sets.
- **Golden plays.** For Housing, tests added after the runs play five kinds of tenant on v14 worlds through the real
  market: a good lease whose accounting we checked by hand, a poor blind signing of a lemon, invalid and unauthorised
  actions (the market ends exactly as if the tenant had passed), malformed output through the kernel (typed as an
  error and scored as a pass, never as $0), and a world whose ceiling is $0. Each test has a counterexample that makes
  it fail.

### F.3 Reading trajectories

Housing v14 (60 of its 1,800 attempts, step by step) and the agreement's development runs open in a trajectory viewer
that shows each step as the seat saw it, beside the state it could not see, with a quality-control checklist for each
run. On 2026-10-13 that checklist flagged 670 lines across 144 bundles, of which 58 needed a human reviewer. Tracing a
single case by hand found Refund's defect in its payment leaf (Table F.4), and we traced an earlier data-center design
the same way on 2026-09-14.

### F.4 Adversarial checks applied

- **Trivial agents** are reported beside the models. Signing the draft unchanged recovers 14% of the value available
  in the agreement case's development set. Always paying the premium gives up $51.25 a world on Procurement's
  pre-registered worlds (Table 5.3). In Housing, scored after the runs, passing earns $0, signing without inspecting
  −$80 and an inspect-then-sign rule $145 a world, a rule that two of the three models do not beat (Table 5.2).
- **Fixed rules** are scored exactly against Procurement's best policy. In the earlier evaluation set (Table E.14) the
  one-step rule's loss of $0.06 is the finding that fails Gates 1 and 3. A v2 evaluation set built after the runs adds
  one mechanism: new listings of one seller kind share a source with a stated probability, so a cheap test of one
  listing informs the buyer about another. Included on what a buyer observes, with types drawn afterwards, its 24
  worlds (from 5,798 seeds) make the one-step rule give up $30.09 a world on average and at least $10 in each world, as
  do the four fixed rules and a shortcut that ignores seller kinds. With the source never shared, the one-step rule
  comes within $0.33 of the best policy, so the gap is due to the shared source. Tests check every value against the
  environment's average over the 27 type profiles. Its separate 12-world gate check and pilot used 50 episodes
  ($0.2193). Gemini never tested a newcomer and matched the premium rule; Luna contacted a newcomer in 1 of 24 pilot
  plays, and neither model reached the planned probe. The required sizes were 326, 3,464 and 2,047 worlds, beyond the
  cap of 96, so no confirmatory run was frozen or played. On the harder evaluation set of Section 5.1, the same exact
  scoring places the one-step rule at the value of paying the premium in all 20 pre-registered worlds, and the shortcut
  and the rule that may test two newcomers at 33% and 82% of the gap (Table 5.3).
- **Audits of the task prompts** found instructions that decided outcomes in Procurement and a schema that contradicts
  its verifier in Refund.
- **Lower controls for Refund V2.5** were scored under a beatability rule committed before any control ran. For each
  seat and cohort, the reference must beat each control by at least 0.50 in end-to-end score (0.25 on policy meaning in
  the policy seat), and a control may match the reference on at most 10% of cases. Nine controls played every public
  case, producing 3,468 trajectories with no model: empty, null, full-refund and random legal policies; an
  over-disclosing customer and a first-record customer; a first-sorted intake seat; and a payments seat that moves no
  money. The reference fails the rule on all 11 public cohorts in the policy, customer and payments seats. A full refund
  that collects nothing is fully right on 38 of 180 policy-seat cases, the evidence leaf scores any legal path as
  complete, the customer seat reduces to copying, and the payments seat reduces to how often the answer is no payment.
  Only the intake seat passes.
  These are the original audit's counts. They are not a new lower-control test of the expanded thirteen-cohort
  release or a reanalysis of the model calibration, and neither expansion establishes full quality control.
- **A placebo outcome** was run after the agreement's look-back price signal. The same regression on the opening price
  of a scripted integrator that is never told the hidden type gave 0.38 [0.23, 0.52] where the true value must be 0,
  which exposed hidden types tied to the evaluation set's design cell; a random relabelling of types had not caught
  this.

### F.5 Statistical practice applied

The world is the unit of uncertainty, and comparisons are paired across conditions within worlds. On the agreement
runs, treating plays as independent made the intervals 1.47 to 1.65 times too narrow, and adding worlds is more
efficient than adding repeats: detecting a $50k gap needs 83 to 91 negotiations per arm at one play a world, against 159
to 162 at three plays a world. We name the counterparts and report results per counterpart type; in the agreement case
the counterpart accounts for 25% to 33% of the spread in what a model earns. The reported analyses that were
pre-registered before their runs are Housing v14 and v15, the agreement signalling test, both agreement confirmatory
runs, and Procurement's test and its diagnostics. We tested a harness setting rather than assuming its effect: asking
the CLIs for reasoning summaries changed nothing detectable in Housing (Opus +17 [−28, +62], Sol +3.5 [−46, +53]; five
selected worlds and 120 episodes, with the summary-off plays always run first).

**Review of the agreement's v1 confirmatory run (16 October).** Gate 5 is `partial`. The run applied a 12-world
variance pilot, a sealed sizing record, frozen plans, paired world-level intervals and Holm correction. Eight
departures from the plan are documented: the CLI versions; an added wall-time stop; the run-plan labels; a change to
the evaluation-set module for pilot generation; the permitted copy of the sizing code; a correction of an analysis
label after the data were in; one missing negotiation in a secondary arm; and pilot pairing by play index. The label
correction changes no estimate but leaves the analysis digest different from the sizing record, and the pinned
verifier still needs manual treatment of the excluded receipt. These publication and configuration checks are
therefore not fully closed. The client seat's construct limit is a separate issue. The 45-world estimate for the
second primary contrast (P2) rejects zero (Holm p 0.0017), while its 98.3% interval [6.7, 46.1] lies below the
pre-registered smallest meaningful difference of $50k; both readings must be reported.

### F.6 Failure records and review

We record discovered failures in the incident log in four categories (design, operational, tooling and judgment),
and we never delete rows (Table F.3). Evidence review by verification (digests, replay and a scan for prohibited text)
was done for the Housing v14 bundle. The agreement family's registry change has had no review by anyone other than its
author, and eight earlier changes to the shared runner were accepted without such a review under a one-time
exception.

**Table F.3. Incident-log entries about each case and its predecessors, by category (as of 16 October 2026).**

| Case | Design | Operational | Tooling | Judgment | Total |
|---|---:|---:|---:|---:|---:|
| Housing | 9 | 21 | 9 | 12 | 51 |
| Procurement | 27 | 6 | 19 | 5 | 57 |
| Data center | 37 | 22 | 22 | 9 | 90 |
| Refund | 12 | 0 | 8 | 3 | 23 |

Counts are of distinct entries. One Data-center entry had been filed under an identifier already in use; we count it
separately.

### F.7 What quality control found

**Table F.4. Twenty-five selected defects, the level at which each was visible, and what changed (dispositions as of 16 October 2026).**

| Case | What was wrong | Visible in one world? | How it was found | What changed |
|---|---|---|---|---|
| Housing | A seat-number tie-break and scripted rivals' $1 overbid decided who signed a sound listing | no: a pattern across seats | comparing signing rates by seat | one deciding tenant against pre-registered outside demand |
| Housing | The scripted landlord's accept-or-counter reply was a free, near-perfect quality test beside a $25 inspection | no: needs the cost distribution | validity audit before a second model ran | pooled landlord; the revealing landlord kept as a pre-registered arm |
| Housing | Inclusion made a favourite's lemon rate depend on its popularity (0.29 among included worlds where six tenants shared it, about half before inclusion) | no: a property of the included set | comparing rates before and after inclusion | include on the tenant's structure, read quality afterwards |
| Housing | The rule the tenant was told sat outside the sealed request | yes, by reading the sealed bytes | known at build, logged before any run | the rules sealed in the prompt, the tenant's history in the observation |
| Housing | A gap decomposition's "luck" part was not luck: uncontested blind bets were lemons 11 of 15 times, contested 1 of 15 | no: a split by rival behaviour | testing the stated odds by model (p = 0.006) | blind signings scored at their expected value given what the tenant saw |
| Procurement (an earlier design) | A rule reading only the displayed price beat the qualified model by $28.50 a world | no: a baseline comparison | the construct check | construct gate recorded `failed`; Gate 0 made a profile mandatory |
| Procurement | The prompt pointed every subject at the cheapest listing, right in half the worlds and wrong in the other half | no: needs the evaluation set's construction | asking whether the hard half was valid or a trick | a neutral prompt and a new evaluation set |
| Procurement | The task prompt did not say a quote is final or that the buyer is judged on its average | no: a pattern in loss by action | listing each loss by the action that caused it | a second task prompt; loss fell from $12.2 to $1.0 and $19.4 to $5.4 a world |
| Procurement | Under sample noise the pre-award check reveals the true yield for one free action | yes, by reading the tool's code | designing a sample-again decision | open; 1 of 260 noisy episodes used it, no published number moves |
| Data center (predecessor case) | Walking away came within $11k to $46k of the right contract, and asking for every protection within $26k to $88k | no: a strategy-class simulation | simulating shortcut policies on the evaluation set | before any freeze: each named shortcut must cost $75k more than the best contract, and a deal must beat the better outside option by $150k |
| Data center (predecessor case) | At low effort the case could not separate two models: about 83% of the per-world gap was seed noise | no: needs paired seeds | variance split of the paired gap | one seed per world and more worlds; a redesign of the case |
| Data center | The scripted style hashed the whole world, including the client's hidden charge | no: needs two copies of a world | a test that the opening is identical for both types failed | the pre-registered test uses a fixed style; the included evaluation set draws the style from the public world only |
| Data center | The hidden type was fixed by design cell and moved with public quantities | no | a placebo outcome, after the look-back (Appendix F.4) | an included evaluation set whose types are drawn after inclusion (Appendix F.2) |
| Data center | The generator priced the client's rival offer, a public number in both task prompts, from the drawn integrator type, so a public parameter depended on both hidden types | yes, by reading the generator | building the included evaluation set | the included evaluation set prices it before any type is drawn; the development sets keep theirs |
| Data center | The integrator's private cost barely moves the best agreement, so the client seat has almost nothing to infer about clauses | no: a value of information across worlds | building the inclusion criterion for both seats | open; the client seat needs worlds where the integrator's risk charge is private |
| Housing | The primary measure conditions on the landlord's reply only below the sound floor; a reply that proves a listing sound under the leaky kind is still scored at the stated odds | yes, by reading the measure's code | writing the formal appendix of this paper | recomputed from the sealed run roots: 57 signings move, no pre-registered verdict changes, Gemini's leads shrink by $10 and $13 in the v14 episodes; an erratum is owed |
| Refund | The 120-episode panel was six cases: the world seed changed only the case id, and the policy seat ran at temperature 0 | no: needs the seeds compared | rebuilding the cases and reading the reference run's resolutions | the case is the unit of analysis; V2.5 varies pre-registered conditions by seed |
| Refund | A correct denial written with method `null` failed: the prompt says "none", the schema allows null, the verifier compares strings | yes, by reading one proposal against the verifier | building the gap decomposition | recorded; reported as format, not outcome |
| Refund | The human-QC approval was minted by the runner from two status-only stubs, so it bound whatever the runner produced | yes, by reading the runner's code | the Refund audit | V2.5 names a reviewer, but the runner still binds the approval to its own output (still open) |
| Refund | Refund's payment leaf checks that payments executed what the proposal asked, so a proposal with an aliased mutation moves no money where the reference refunds $185.22 and still scores 1.0 | yes, by tracing one case | writing the formal appendix of this paper | open; report the leaf as binding and add a check against the reference |
| Housing | The v14 receipts' own scores total all six tenant seats against baselines from a market without outside demand, so they are not the deciding tenant's | yes, by reading the receipts | building the seat-0 controls | open; the published primary is computed separately and is unaffected; a seat-0 scorer needs a module outside the hashed runner |
| Refund | In three of Refund V2.5's four seats a naive control comes close to the reference: a full refund that collects nothing is fully right on 38 of 180 policy cases, the evidence leaf passes any legal path, the customer seat reduces to copying and the payments seat to the base rate of no payment | no: a rate across cases | lower controls under a rule committed before they ran | open; Gate 3 recorded `failed`; scoring pairs of cases would stop the full-refund control (0 of 38 pairs), a rule not yet pre-registered |
| Housing | The v14 receipts name the model for the five tenant seats a script played; the true seat map is only in an unsealed log | yes, by reading the driver's seat router | the paper's runtime review | open; record the seat map inside the seal under a new frozen configuration |
| Procurement | Procurement's original decision-loss report read an unsealed action copy through an unpinned reference; receipt replay alone did not certify it | yes, by reading the driver | the paper's runtime review | resolved for the reported panels on 16 October: source-pinned reanalysis from replay-audited sealed actions reproduces all 144 losses; prospective receipt-leaf integration is separate work |
| Procurement | The pay-or-test action schema let `message` be null while the parser requires it, so a model's first action could end its episode on format | yes, in one episode of the gate check | the flash-model gate | the schema requires every field the parser needs, under new frozen configurations |

Fourteen of the 25 defects required evidence beyond a single world. Now that Procurement's decision-loss report has
been re-derived from sealed actions, eight remain open: the free yield check in noisy Procurement evaluation sets; the
Housing reply measure, the Housing receipts' score totals and their seat map; Refund's payment leaf, its runner-minted
approval and its lower controls; and the Data-center client seat.

### F.8 Assessment against the Agentic Benchmark Checklist

We assess the four cases item by item against the checklist [ABC]. The outcome-validity item that applies is the one
for a quality measure, since no case is scored by string matching, unit tests or a judge model.

**Table F.5. The four cases against the checklist.**

| Item | Status | Evidence |
|---|---|---|
| T.1 Tool versions specified | partly | routes, prompts, schemas and implementation digests are sealed in each plan; the two CLI agents expose no seed or temperature |
| T.2 Required APIs accessible | partly | provider outages lost episodes (36 Housing episodes to an empty account, 40 data-center negotiations to CLI errors), each recorded as typed missingness |
| T.3 Terminates or handles API errors | partly | Housing v14 uses worker-level failure streaks: twelve workers could still produce 36 account failures. Procurement flash panels declare retries and a consecutive-failure stop; the confirmatory agreement driver freezes a five-consecutive-failure halt plus list-price and wall-time ceilings, unlike its development predecessor. These are driver controls, not adoption of the kernel halt helper (Appendix H.4); operational failures remain exclusions |
| T.4 Residual state cleared between runs | met | each episode starts fresh from a sealed plan; the CLI agents run one ephemeral subprocess per action |
| T.5 Agent isolated from ground truth | partly | named hidden fields are tested absent from observations in Housing, Procurement and Refund, not in the agreement case; one leak was fixed and one is open in noisy-sample evaluation sets |
| T.6 Setup does not change over time | partly | environment inputs and pre-registered routes are pinned; this does not attest a stable hosted deployment, provider compliance, or the unsealed CLI environment (Appendix H.2, H.3) |
| T.7 Ground truth verified | partly | each reference is played on every included world through the environment and reaches its stated result, initially by tests added after development; the included agreement evaluation set also had a dry run before the confirmatory run (Appendix F.2) |
| T.8 Each task verified solvable | partly | reference policies are played through the environment, but full-information references can use information unavailable to the evaluated seat; this does not establish that every seat can attain the reported bound |
| T.9 Oracle solver | partly | exact for Procurement; an independent reference resolution and a scripted policy that resolves every case for Refund; a reachable reference for Housing, with an exact best informed tenant in development; a full-information stand-in for Data center, whose per-turn best informed policy is not built |
| T.10 Free of exploitable shortcuts | partly | trivial agents, exact fixed-rule scores and task-prompt audits (Appendix F.4); twenty-five selected defects (Table F.4); a one-step rule reaches the best policy on Procurement's earlier evaluation set, and the reported evaluation set includes only worlds where that rule pays the premium; a wrong refund can still pass Refund's payment leaf |
| O.i.1 Quality metric resists exploitation | partly | code computes the measures and controls are tested, but the Housing measure needed correction and Refund has open payment and lower-control failures |
| R.1 Open source | partly | the environments, runner and evidence are public; the trajectory viewer is private |
| R.2 Open evaluation harness | met | the shared runner is in the public repository |
| R.3 Measures against contamination | met | preventive measures, not proof of zero contamination: worlds are generated, holdouts come from a disjoint seed range, and pre-registered tests run on fresh worlds |
| R.4 Plans to update | partly | evaluation sets regenerate from new seeds; no refresh schedule is stated |
| R.5 Capability related to construct | met | each case states the decision it measures (Table 5.1) |
| R.6 Evaluation subject stated | met | the subject is a profile (model, harness, prompt, tools, reasoning, retries); CLI agents are named with their harness |
| R.7 Steps to prevent, find and correct flaws | partly | the gates and the incident log (Appendix F.1, F.6) |
| R.8 Qualitative discussion of unavoidable flaws | met | the end of §5.2 |
| R.9 Quantitative analysis of flaw impact | partly | measured for the task-prompt change, the refused episodes and missingness bounds; not for every open row |
| R.10 Statistical significance | met | paired world-level intervals; Holm correction across pre-registered primary contrasts |
| R.11 Guidance on interpreting flawed results | met | every result is labelled confirmatory, pre-registered or development |
| R.12 Non-AI baselines | partly | scripted policies in every case; no human |
| R.13 Trivial agents | partly | always paying (Procurement), signing the draft (Data center) and passing, signing anything and inspect-then-sign (Housing, scored after the runs) are reported; Refund V2.5 has nine lower controls, which come too close to the reference in three of four seats, and the V2.1 results reported here have none |

## Appendix G. Artifacts

Everything on which the numbers in Sections 5 and 6 rest is in the public AERead repository
(https://github.com/aeread-org/AERead), or is named here when it is not.

- **Code and cases.** The shared runner and the case families, with each case's generator, reference, verifiers,
  evaluation sets and tests. Each case is developed on its own branch of the repository.
- **Evidence.** Sealed, digest-bound evidence bundles: the Housing v14 confirmatory run and its pre-registered fill,
  the data-center agreement bundles, and the Refund V2.1 bundles with their gap decomposition, all on case branches.
  Procurement's pre-registered runs (Table 5.3) are on the main branch as twelve bundles, and all 432 of their receipts
  replay through the runtime's command line.
- **Quality control.** Each family's quality-control profile and incident log, kept with its code, and the
  reference-run tests named in §6.
- **Sources for every number.** The source files of Sections 5 and 6 end with tables that map each table and claim to
  its bundle, run, code revision or log entry.
- **Paper analyses.** A directory of paper analyses holds the rescoring under the corrected Housing measure, the
  failure taxonomy of §5.2 and the control contrasts of Table 5.2, with a runner and the inputs each analysis needs.
  The Housing v14 and Procurement inputs are sealed run roots not yet published as bundles, so those numbers can be
  checked against the run roots but not yet from the published evidence alone.
- **Not in the repository.** The trajectory viewer is private; one-page result summaries restate numbers from the
  bundles above.

**Headline verification.** The draft's source package includes the Housing reply-conditioned analysis and the
Procurement reanalysis. The Housing analysis re-extracts its committed trajectory table from the sealed run roots and
regenerates both measures exactly. The Procurement reanalysis checks all 144 original receipts and then reconstructs
decision loss from their sealed parsed actions; its public projection regenerates Table E.14 without private run
roots. The package supplies source and case digests, extraction commands, tests and a patch against the analysis base.
Full verification of either projection against its original execution logs still requires the retained run roots.

**Agreement confirmatory run and Procurement v2.** The source package also includes the data-center agreement's
confirmatory plan, results, analysis, sizing record and source-bound review, together with the Procurement v2 pilot
report and results note. The original five agreement bundles retain their sealed bytes. We supply the corrections to
the Data-center quality-control profile and incident log as a documentation patch; no frozen driver or analysis code
was edited.
