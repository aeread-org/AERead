# Case studies (draft section of the AERead environment paper)

**Status:** working draft, 2026-10-13. Written from the current design of each case, its
one-page result sheet and the bundles or run roots those sheets cite. It supersedes the
Housing and Procurement case material in the 2026-09-06 working draft
(`aeread_environment_paper_draft.md`, on branch `codex/housing-v13-cooldown-full-trajectory`),
which described designs that have since been replaced. One result below is confirmatory
(Housing v14); one is a test declared before its runs (the data-center signalling test);
everything else is a development probe and is labelled so. The companion section is
[Quality control](paper_qc_design.md).

---

## 5. Case studies

### 5.0 What a case is, and what three cases buy

Terminal-Bench 2.0 holds 89 tasks, selected from 229 candidates. Each has its own
environment, an oracle script that passes its tests, about three reviewer-hours of review,
and at least five runs per agent and model [TB2]. Its unit is a task instance with a
pass-or-fail verdict, and its breadth is the number of instances.

An AERead case is a different unit. It is a generator of worlds, a reference policy
computed exactly from what the deciding side is allowed to know, an admission screen that
keeps only worlds where the decision matters, and a measure in dollars. Each admitted world
is an item scored on a continuous scale against that reference, so a case supplies as many
items as the design needs to resolve a stated difference.

**Table 5.1. Items in adjacent environments and in the three AERead cases.**

| Environment | Domains or cases | Items | Verdict on an item |
|---|---|---|---|
| Terminal-Bench 2.0 [TB2] | 1 (terminal) | 89 tasks | pass or fail on tests |
| τ-bench [TAU] | 2 | 165 tasks (115 retail, 50 airline) | pass or fail on the final database state |
| τ²-bench [TAU2] | 3 | 278 tasks (50, 114, 114) | pass or fail |
| AppWorld [APPW] | 1 world of 9 apps | 750 tasks | pass or fail on state-based tests |
| **AERead (this section)** | **3** | **458 admitted worlds** (Housing 300, Procurement 42, Data center 116) | **dollars given up against an exact reference** |

The comparison flatters AERead in one way and is unfair to it in another. Worlds of one
case are draws of one decision, not 300 different tasks: they buy statistical resolution
on that decision and nothing on breadth. On the other hand a world carries a graded score
against a reference that is computed for that world, so one world says how far a subject
fell short and where, which a pass-or-fail item cannot.

Three cases is few. The reason is cost, and the cost is in the distribution rather than
in any one instance. Each case below reached its current design through several sealed
campaign identities, and the defects that forced each redesign were invisible world by
world: a seat-number tie-break deciding who got the good listing, an admission rule that
made the favourite's quality depend on its popularity, a prompt that pointed every subject
at the right supplier in half the worlds and at the wrong one in the other half, a
counterpart against which walking away was nearly optimal. Section 6 lists them. We therefore make claims about three decisions and
not about economic agency in general; §5.6 states what the three cover and how the suite
grows.

### 5.1 Shared anatomy

Every case reports the same rows, so that a reader can compare how they are built
even though their scores are not on one scale.

**Table 5.2. The three cases.**

| | Housing | Procurement | Data center |
|---|---|---|---|
| **Decision under test** | Which listing to verify, what to offer and whether to sign when two of four listings are lemons | Pay a premium for a supplier with a record, or test a cheaper newcomer of unknown quality, before a deadline | Which of eight risk clauses to move, what price to name, when to sign and when to walk |
| **The model's seat** | One tenant against four scripted landlords; listings it does not bid on leave with probability ½ a round; three rounds | One buyer; suppliers are scripted | Client or integrator; the other seat is the other model, a copy of itself, or a scripted negotiator in one of five styles |
| **Hidden from the model** | Which listings are lemons ($1,000 less); landlord costs; how the landlord prices a lemon | Each newcomer's delivery and yield type, drawn from stated odds | The client's risk charge and the integrator's pre-staging cost (the integrator's own risk charge shows in its draft) |
| **Reference** | A scripted tenant that inspects its favourite, offers $0 on the best verified listing and signs any counter its value covers: $292 a world, 79% of a $370 full-information ceiling | The best informed policy, solved exactly by backward induction over what quotes and samples could show: $451 a world, 92% of a $489 full-information bound | The best of 600 agreements at both sides' true costs; a stand-in that knows both sides and the script (a ceiling) |
| **Primary measure** | Tenant's net per world (value less rent less inspections); a blind signing counted at its expected value given the landlord's reply; mean of the two landlord kinds | Dollars each action gave up against the best informed policy at that point, summed over the play | Joint value lost against the best agreement, and each side's surplus over its outside option |
| **Pack** | 260 + 40 holdout worlds, admitted on the tenant's own structure; each world's lemon draw is read only after admission | 24 worlds, six kinds × four, admitted on what a buyer can see, types drawn afterwards; plus an 18-world sibling pack | 58 development worlds (52 with a deal worth signing) and 58 fresh worlds for a declared test |
| **Subjects** | Gemini 3.8 Flash, GLM 5.3 Flash, GPT-6 Luna (1,800 cells); Opus 5.5 and Sol 6.1 through their CLIs on 20 worlds | Opus 5.5 and Sol 6.1 through their CLIs | Opus 5.5 and Sol 6.1 through their CLIs |
| **Status** | Confirmatory, analysis declared before any cell | Development | Development probes and one declared test |

Opus 5.5 ran through Claude Code and Sol 6.1 through the Codex CLI, without tools, at low
reasoning effort, one subprocess per action; neither CLI exposes a seed or temperature, and
both are recorded as unavailable rather than assumed.

### 5.2 Housing: renting when the favourite may be a lemon

**The case.** A tenant faces four landlords. Two of the four listings are lemons, worth
$1,000 less; an inspection costs $25 and reveals one listing's quality to the tenant alone.
Over three rounds the tenant may inspect, offer, and sign or walk; each listing it did not
bid on is taken by outside demand with probability ½ at the end of a round, on a schedule
the world fixes so that every subject meets the same departures. Every world is played
under two landlord kinds: a *leaky* landlord prices a lemon on its own lower cost, so a
reply far below the ask reveals it; a *pooled* landlord prices a lemon like a sound
listing. The tenant is told the lemon count, the loss, the fee, the departure rule and the
horizon, and nothing about how landlords price.

**The measure.** Realized payoff on this case is dominated by which blind bet happened to
be a lemon, so the primary measure prices each blind signing at its expected value given
the landlord's reply. The score therefore moves with the tenant's decision and not with the
draw. Worlds are admitted on the tenant's own structure (its favourite and a second
listing are worth signing if sound) and the lemon draw is read after admission, so
admission cannot select on quality; the main pack holds the first 200 favourite-lemon and
60 favourite-sound worlds from one seed range, and the holdout 30 and 10 from a disjoint
one.

**Result.** The three flash models were run under one declared analysis: three model pairs
corrected together (Holm), each model against the reference, a $50 minimum meaningful
difference, the holdout reported apart.

**Table 5.3. Housing v14, main pack (260 worlds); dollars per world, 95% intervals paired by world.**

| | Gemini 3.8 Flash | GLM 5.3 Flash | GPT-6 Luna |
|---|---:|---:|---:|
| Tenant net per world | +211 [+188, +233] | +137 [+111, +162] | +130 [+104, +156] |
| Minus the reference, all worlds | −81 [−97, −65] | −155 [−177, −134] | −162 [−181, −142] |
| Minus the reference, favourite is a lemon (200) | −102 [−122, −82] | −179 [−203, −154] | −207 [−229, −186] |
| Minus the reference, favourite is sound (60) | −13 [−18, −8] | −76 [−116, −36] | −9 [−16, −2] |
| Signed a hold only a lemon's landlord would offer | 7 of 38 | 54 of 73 | 80 of 88 |

Gemini leads GLM by +70 [+48, +92] and Luna by +80 [+62, +99] (Holm p < 10⁻⁸); GLM and
Luna differ by +7 [−16, +29], inside the $50 band. The 40-world holdout points the same way
(+106 [+44, +168], +55 [+12, +98], −40 [−106, +26]). All 1,800 published receipts replay to
the same score. Thirty-six Gemini cells were refused when the provider account ran out of
credit; they stay missing in the declared bundle, and a separately identified fill run
moves nothing (+74, +81).

**What the case shows.** Gemini's lead is established and repeats on the holdout; none of
the three reaches a scripted tenant that inspects before it offers; and almost the whole
shortfall sits in the favourite-lemon stratum, where the models keep 60%, 27% and 22% of
what the reference earns, against 97%, 83% and 98% where the favourite is sound. A pooled
score would report a gap of $81 to $162 and hide that, on the quarter of the pack where the
favourite is sound, two of the three models are within $13 of the reference. With the
rules in the sealed prompt, GLM and Luna still sign most holds that only a lemon's landlord
would offer, although reading a reply that way takes an inference about how landlords
price that the prompt does not state.

Two frontier agents played the first 20 worlds of the main pack through their CLIs (40 cells
each). Sol 6.1 earns $313 [225, 402] and Opus 5.5 $291 [198, 383] against the reference's
$331 on those worlds; the difference, +23 [−19, +64], is not established. Both equal the
reference where the favourite is sound ($427) and fall short where it is a lemon ($200 and
$155 against $235), and both still sign four uninspected holds whose rent reveals a lemon.

The reference is reachable, not best. An exact best informed tenant (a belief over which
listings are lemons and which landlord kind it faces, solved by backward induction) earns
$307 a world on the main pack when told how landlords price, against $292 for the scripted
reference and $370 for the ceiling. The v14 subjects were not told how landlords price, so
part of their gap to that tenant is information rather than judgment; told nothing about
pricing, the same solver earns $267, below the scripted rule, which is why it is not used as
the reference here. This tenant is development work on an unmerged branch.

### 5.3 Procurement: pay the premium or test a newcomer

**The case.** A buyer owes 50 kits by a deadline. One supplier has a long clean record and
the highest price. Three are 3% to 21% cheaper and new, each listing what share of new
sellers of its kind proved unreliable on delivery or failed inspection. A quote ($2, a day)
shows whether a supplier delivers on time, a sample ($30 to $80, three days) shows its
yield, and every award needs both; supplying nothing costs the shortfall penalty on all 50
kits. The pack has six kinds of world, four of each: paying is right on the money; paying is
right because a failed test would leave no time for the recorded supplier; a test is right
with the cheapest or with another newcomer, on a tight or a loose clock.

**The reference and the measure.** The best informed policy knows the stated odds and
nothing else about a newcomer. It is solved exactly by working back from the deadline over
everything a quote or a sample could show, and its value equals the environment's average
over all 27 ways the newcomers can turn out. Each action is charged what it gave up against
that policy at the point it was taken, so the measure does not move with how a tested
supplier happened to turn out. Fixed rules are scored the same way, exactly: comparing each
untested newcomer with paying, one test ahead, gives up $0.1 a world; testing the best odds
once $45.7; always paying $75.2; testing the cheapest once $81.4; working up the price list
until one qualifies $146.1.

**Table 5.4. Procurement pay-or-test, 24 worlds, one play a world; dollars given up per world.**

| | Sol 6.1 (Codex CLI) | Opus 5.5 (Claude Code) |
|---|---:|---:|
| First prompt | 12.2 [4.3, 23.6] | 19.4 [6.0, 38.2] |
| Prompt stating that a quote is final and that the buyer is judged on its average | 1.0 [0.2, 2.1] | 5.4 [1.2, 10.6] |
| The same, the 16 worlds where a test is the best plan | 1.5 [0.3, 3.1] | 8.1 [1.9, 15.6] |
| Worlds with nothing given up (second prompt) | 20 of 24 | 17 of 24 |

Opus gives up $4.4 [0.6, 9.0] more than Sol under the second prompt. Both pay without a test
in all eight worlds where paying is right, on both prompts, and the first newcomer each
tests is the right one in 15 (Sol) and 14 (Opus) of 16 worlds. All 96 cells completed and
replay to their recorded margins.

**What the case shows.** It is at its ceiling for these two subjects: its best policy is a
one-step comparison and both make it, keeping 99.8% and 98.8% of the best policy's value.
Most of what they lost on the first run was the brief's doing. Sol made 43 counter-offers,
which cannot succeed in this pack, at $7.3 of its $12.2; Opus made cautious moves (paying
without a test, stopping after one bad newcomer) that are defensible for a buyer who weighs a
bad outcome above the average, which the first brief never said was the criterion. Stating the
two rules cut the loss by $11.1 [3.6, 22.3] and $14.0 [0.4, 33.5]. A sibling pack, in which
whom to verify can be read off a marketplace record (18 worlds), is saturated in the same
way: Opus solves 18 and Sol 16. No flash-tier model has played either pack, and every price,
fee and odds figure is the designers' assumption rather than an expert's.

The case contributes a negative result about difficulty, and the instrument that makes it
precise: because the reference is exact per action, saturation is stated as about a dollar
a world given up, not inferred from a high pass rate.

### 5.4 Data center: negotiating a services agreement

**The case.** An integrator will deliver a GPU cluster into a client's facility. Its
standard draft is on the table. Moves alternate, three a side: redline (move any of eight
clauses between fixed positions and name an all-in price, with an optional note), sign what
the other side last put on the table, or walk to an outside option. The clauses decide who
pays when one of four things goes wrong (a compatibility defect, a late facility, an
incident after handover, the integrator failing while holding an unprotected deposit), and
the integrator pre-stages hardware and prepares the site exactly when the clauses make that
cheaper for it, so moving a risk to the side that can control it shrinks the total rather
than only moving it. Each side knows its own costs and only the odds of the other's. Each
redline after the opening costs its author $25k. Every amount is computed at both sides'
true costs; nothing is judged.

**Result: the ranking depends on the counterpart.** Head to head, the pair recovers about
80% of the value available, against 14% for signing the draft unchanged, and which model
sits in which seat changes the total by +3 [−11, +18] ($ thousands a world). Who keeps it
differs sharply: Sol earns about 250 more than Opus in the same seat and is ahead in 51 of
52 worlds in each seat. Each model was then played in each seat against scripted negotiators that
follow one rule on their own seat's information.

**Table 5.5. Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

| Counterpart | What it does | As integrator | As client |
|---|---|---:|---:|
| The other model | | +248 [+206, +290] | +251 [+209, +293] |
| Collapse | holds a high ask, then gives most of it up on its last proposal | +88 [+51, +126] | +148 [+117, +179] |
| Soft | concedes on a clock, signs anything better than walking away | +86 [+56, +116] | +95 [+74, +115] |
| Price only | never changes a clause, haggles the price | +112 [+75, +149] | +54 [+36, +71] |
| Overreach | opens below the model's walk-away point, then comes down | +32 [+10, +53] | +108 [+72, +144] |
| Firm | concedes only as far as the model does, refuses a lopsided last offer | +17 [−10, +44] | +23 [−2, +48] |

The direction is the same against every counterpart; the size runs from not distinguishable
to 250, so a benchmark with one counterpart would have reported any number in that range.
Against the firm script both models earn about what signing its first offer earns (a
stand-in that does so earns 122 as integrator and 114 as client) by opposite routes: Opus
signs the first offer in 36 of 52 worlds as client, while Sol bargains to the last move, pays
for redlines and loses seven deals to the script's floor.

**Where Opus loses.** As client Opus signed below its own walk-away point in 12 of 52 worlds
against Sol, 23 of 52 against the overreaching script, and, against a copy of itself, made
the losing offer unprompted in 5 of 20. Every case is a world where the client's better
outside option is managing the deployment itself, which the brief gave as ingredients rather
than as a number; one added line stating that number cut such signatures from 15 of 60
plays to 1 of 60. At equal skill the seat is worth nothing: two copies of Sol split the value
evenly (integrator minus client −6 [−94, +81]).

**A declared test.** Looking back over these runs suggested two signals: Opus's counter-offer
price seemed to follow its private value, and Sol's clause requests seemed to follow its
risk charge. The claims, measures, exclusions and six primary predictions were committed
before any run, on fresh worlds no model had played: 29 written twice with only the client's
hidden charge changed, and all 58 against counterparts that read the first offer. Sol asks for 1.82 [1.23, 2.40] more protective clauses of six under the high charge
(supported, Holm p < 0.001), 1.58 [0.95, 2.22] more than Opus does; fitting its clauses to
its type is worth about +120k [+83k, +156k] of joint value a world to it. Opus's price
pass-through is −0.07 [−0.18, +0.05], not supported; the earlier 0.52 came from counter-offers
only, compared across worlds, and was withdrawn. Counterparts that read the first offer
gained nothing measurable from either model (+2k [−14k, +17k]; −8k [−42k, +26k]).

**What was built and what was not.** The design calls for a scripted counterpart as the
measured case, a loss per turn against a best informed policy, an admitted pack and frozen
mid-negotiation turns. What has run uses the 58 development worlds, a full-information
stand-in as the ceiling (it knows both sides' costs and the script's style, so it is not a
fair target), and no per-turn reference. 2,417 of 2,456 negotiations are valid, at $119 list
price. Every failure is a CLI service error; the original bundles keep them as missing,
and 16 were played again under separate identities by the owner's ruling.

### 5.5 Across the three cases

The two CLI agents played all three cases, which allows one cross-case reading.

**Table 5.6. Opus 5.5 and Sol 6.1 on the three cases.**

| Case (worlds) | Measure | Opus 5.5 | Sol 6.1 | Sol relative to Opus | Reference |
|---|---|---:|---:|---:|---|
| Housing (20) | tenant net per world | 291 [198, 383] | 313 [225, 402] | +23 [−19, +64] | scripted reference 331 |
| Housing, favourite a lemon (10) | tenant net per world | 155 | 200 | not tested | scripted reference 235 |
| Procurement pay-or-test (24) | given up per world | 5.4 [1.2, 10.6] | 1.0 [0.2, 2.1] | 4.4 [0.6, 9.0] less given up | best policy gives up 0 |
| Procurement, record pack (18) | worlds solved | 18 | 16 | regret −20 [−48, +7] (Opus lower) | informed policy 18 |
| Data center, firm script (52) | earns, integrator / client ($k) | 122 / 107 | 139 / 130 | +17 [−10, +44] / +23 [−2, +48] | first-offer stand-in 122 / 114 |
| Data center, head to head (52) | earns, integrator / client ($k) | 60 / 25 | 308 / 276 | +248 / +251 | |

Five observations hold across the cases, each from the tables above.

1. **The gap sits in a stratum the design fixes in advance.** Housing's shortfall is in
   favourite-lemon worlds; procurement's residual loss is in test worlds; the data-center
   losing signatures are all in self-manage worlds. Every case reports by declared stratum
   and pools last.
2. **The counterpart is part of the measurement.** The same two agents are equal against one
   counterpart and 250 apart against another (Table 5.5). A claim names the counterparts it
   covers.
3. **What the brief states moves the score as much as the subject does.** Stating that a
   quote is final and that the average is the criterion cut procurement loss by $11 to $14,
   more than twice the gap between the two agents; stating a walk-away cost cut the data-center
   losing signatures from 15 of 60 to 1 of 60. The brief is a controlled, versioned part of
   the case, and what it states is declared.
4. **Frontier agents saturate part of each case.** Procurement is at its ceiling for both;
   Housing's favourite-sound half is at the reference for both; the hard halves (favourite
   lemon, the data-center agreement against a firm counterpart, 72k to 128k below the best
   plan) still leave room.
5. **Patterns found by looking back are not results until tested.** One of the two
   data-center signals failed its declared test. Only declared tests enter the results above; looked-back
   patterns are reported as hypotheses with the test that would decide them.

These cases do not rank models in general. Two frontier agents at one reasoning setting
played all three; flash-tier models played only Housing; no human played any; and the
prices, fees and odds are the designers' assumptions, not calibrated by a practitioner.

### 5.6 Coverage, and how the suite grows

The three cases measure three decisions: whether to pay to verify before committing when
quality is hidden and adversely selected; whether to pay a premium for a known supplier or
buy information about a cheaper one under a deadline; and how to trade risk clauses and price
with a counterpart whose costs are private. They do not cover hiring, financing or auctions
with many bidders, and their numbers have not been set by practitioners.

Breadth can grow along four lines, at very different costs.

- **New packs within a case.** A pack is a generator setting and an admission rule; the
  reference, verifier and runner are reused. Housing's leaky and pooled landlords and
  procurement's two packs are of this kind.
- **Frozen turns.** The data-center design admits a written mid-negotiation state (a draft,
  the redlines so far, the standing price) as an item: one decision, scored against the best
  informed policy played forward. Frozen turns are the closest AERead analogue to a
  Terminal-Bench task, and they can be authored in bulk once that policy exists. They are
  designed, not built.
- **Wrapped external benchmarks.** Eleven published economic benchmarks are wrapped as
  families of the same runner, each with an implementation status and a review trail, and
  some have been checked against their papers' published results. They add breadth without
  exact references.
- **New cases.** A new decision costs what each of these three cost: a generator, an exact
  reference, an admission screen and the qualification in Section 6.

### References

- [TB2] *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces.* arXiv:2601.11868, 2026. §2.2–2.3, Appendix B, §3.
- [TAU] Yao et al. *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains.* arXiv:2406.12045, 2024.
- [TAU2] Barres et al. *τ²-bench: Evaluating Conversational Agents in a Dual-Control Environment.* arXiv:2506.07982, 2025.
- [APPW] Trivedi et al. *AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents.* 2024.

### Sources for the numbers in this section

| Table or claim | Source | Status |
|---|---|---|
| Table 5.3, Housing v14 | `evidence/housing/housing_lemons_price_confirmatory_v14` and `..._v14_gemini_fill` (branch `codex/housing-lemons-outside-demand`, draft PR #256); the case contract's v14 section on that branch; one-pager `housing_lemons_confirmatory_v14_with_claude_codex.pdf` | confirmatory |
| Housing CLI rows | run roots `housing_lemons_price_cli_v1_{claude_code_opus55,codex_cli_sol61}_outside_w20`; page 2 of the same one-pager | development, unadjusted |
| Best informed tenant ($307, $267) | branch `codex/housing-best-informed`, `price_best_informed.py`; recomputed 2026-10-13 from its 600 cells per knowledge level | development |
| Table 5.4, pay-or-test | run roots `pay_or_test_v1_{accounting,finalquotes}_*` (branch `codex/procurement-pay-or-test`); recomputed 2026-10-13 with `pay_or_test_report.py`; one-pager `procurement_pay_or_test_first_result.pdf`; incident rows P-D-19 to P-D-22 | development |
| Record pack (18 worlds) | branch `codex/procurement-inference-v2`, draft PR #263; incident row P-D-16 | development |
| Table 5.5 and the data-center paragraphs | `agreement_results_2026-10.md` and `agreement_signalling_plan_2026-10.md` on branch `codex/datacenter-agreement`; bundles `evidence/datacenter_development/datacenter_agreement_cli_*`; one-pagers `datacenter_agreement_first_result.pdf`, `..._scripted_result.pdf`, `..._signalling_test.pdf`; incident rows DC-J-07, DC-D-33 | development; the signalling test was declared |
| Terminal-Bench 2.0 facts | [TB2] | external |
