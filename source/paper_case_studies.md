# Case studies (draft section of the AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-16. The main-text section; case
details are in [Appendix E](paper_appendix_details.md), formal specifications in
[Appendices A–D](paper_appendix_case_specs.md). Three reported analyses were declared before their runs: Housing v14, the data-center
signalling test and the data-center agreement confirmatory. Other results are development
probes; Procurement v2 stopped after its pilot. The companion section is [Quality control](paper_qc_design.md).

---

## 5. Case studies

We present four cases built by the maintainers (Table 5.1). They are worked examples of the
framework rather than a fixed benchmark: each is a starting point for questions about the decision
it models, and Section 7.2 lists the questions we consider open. The cases show how the counterpart changes measured value and how a shortfall
splits into typed action classes; Section 5.3 runs an external benchmark on the same runtime. Housing, Procurement and Data center are described here and specified in Appendices A–D;
Refund appears only in the cross-case comparison. Each case is a family rather than a fixed task
set: a generator of worlds, a case-specific reference (a policy that uses only what the deciding
side may know, or an explicitly labelled full-information upper bound), an admission rule that
keeps worlds where the decision matters (its form varies by case; Appendix E.2), and a set of verifiers. The references differ in
what a shortfall means: against a reachable policy it is value a feasible strategy would have
kept; against the best policy given the decider's information it is the whole cost of the
decisions; against a full-information bound it also includes the value of information no seat
had (Appendix C).

Cases are chosen by the economic value of the decision, not by occupation [AV]: an activity
qualifies when its value is decided rather than produced, a counterparty has its own interest and
private information, and the result can be scored inside a world against a computed reference.
The four examples sit in two of the five transaction classes introduced in §3
(business and household purchases); they were chosen to span the kinds of verifier and
counterpart, not sampled from a representative distribution.

**Table 5.1. The four cases. Each is scored in its own units against the reference in the last column.**

| Case | Real setting | What the agent decides | Who it faces | Scored against |
|---|---|---|---|---|
| Housing | informal rental listings | which listing to inspect, what to offer, and whether to sign when some listings are lemons | scripted landlords; other tenants take listings it leaves | a scripted tenant that uses only what the tenant knows |
| Procurement | wholesale sourcing | pay more for an established supplier, or test a cheaper newcomer, before a deadline | scripted suppliers | the best plan given what the buyer knows, solved exactly |
| Data center | AI-infrastructure contracting | which risk clauses to change, what price to name, and when to sign or walk away | the other side: a script, another model or the same model | the best agreement at both sides' true costs, which neither side knows |
| Refund | customer refund claims | what to ask, decide and pay on a claim under a written policy | the other parties to the claim, scripted | a hand-written correct resolution |

How much room each case leaves is reported in its own units: Tables 5.2 to 5.4 give each subject's gap to the reference, and Figure 5.1 splits it by action class. The cases use four of the kinds of check defined with the runner's measurement layer (§4): an
answer key, declared rules, the value of the best policy or a bound, and relative standing
against another agent; none uses a rubric. Every score is computed by code, with
no model in the loop; the kernel's replay recomputes each receipt's own score from its sealed
events, while the headline measures of Housing and Procurement are computed by case code outside
that certificate (Appendix F.2). Table E.1 lists every check.

### 5.1 Results

Each case's gate status (§6) bounds what its results can claim. The Data-center confirmatory is
partial at every gate, chiefly because the client seat has almost nothing to infer and the best
informed policy turn by turn is not built; Housing v14 is partial throughout; the Procurement pack
reported here fails Gates 1 and 3; and Refund V2.5 fails Gate 3. "Declared" below describes how a comparison
was run, with its analysis committed before any cell, not the case: the results compare the named
subjects on these worlds and are not qualified benchmark scores.

**Housing.** The structure follows informal rental markets on social platforms such as RedNote:
listings are posted with photos a tenant cannot check before viewing, a viewing costs time, and good
listings are often taken while the tenant decides. Rents, the lemon share and the inspection cost
are set by the authors, not drawn from platform data. A tenant chooses among four listings, two of
which are lemons. It knows its own value v_ℓ for each listing if sound, but not which two are
lemons; each of the six pairs is equally likely. In each of three rounds it may pay $25 to inspect
one listing, make one offer, and sign or walk from a lease it is offered, while each listing it
did not bid on is taken by outside demand with probability ½. Signing listing ℓ at rent x after k
inspections pays v_ℓ − 1,000·𝟙[ℓ is a lemon] − x − 25k; signing nothing pays −25k. The hard part
is information. A listing worth $400 more than its ask if sound is worth 400 − ½·1,000 = −$100 if
signed blind at the ask, but ½·400 − 25 = +$175 if inspected first and signed only when sound;
inspecting a second listing takes another round, in which each listing not bid on may be taken. A
landlord's reply can reveal a lemon at no cost: every world is played against one landlord kind
whose reply to a low offer reveals a lemon and one whose reply does not. A blind signing is scored at its expected value given what
the tenant knew, so the score follows the decision rather than the draw. The declared measure
conditions on the landlord's reply in only one case; a corrected measure, introduced in this paper,
conditions on every informative reply, and Table 5.2 shows both.

**Table 5.2. Housing v14, main pack; dollars per world, 95% intervals over worlds. The corrected block is a post-run reanalysis, reproduced from sealed records on 16 October; the declared measure remains visible.**

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

**Procurement.** The structure follows wholesale sourcing on B2B platforms such as Alibaba's 1688.
In our own sourcing of parts for 231 hardware projects, 1688 search results showed 341 suppliers;
236 requests went to 28 of them and 9 returned quotes, and an exact-variant screen of 51 listings
accepted 1, left 20 conditional and rejected 30. A displayed price is not a quote, and a listing's
quality is known only after it is checked. Two of the case's assumptions depart from that record by
design: its recorded supplier always charges a premium, whereas in the record a seller with a sales
history was dearer than one without in only about half of comparable parts; and its quotes always
arrive, whereas most requests went unanswered. The case's prices, failure rates and delays are set by
the authors, not calibrated to that record. A buyer owes 50 kits by a deadline and awards one
supplier: a recorded supplier with a long clean record, or one of three cheaper newcomers. Each newcomer is
good, late or poor, and the buyer knows only the odds, read from the record of its seller kind.
Among up to ten actions it may request a quote ($2 and a day, which exposes a late supplier),
request a sample ($30 to $80 and two or three days, which exposes a poor one), award, or defer. An award
that delivers k kits on time earns 37k − 12(50 − k) less the order's cost and the information
bought; one that delivers fewer than 40, as a late or poor supplier does, is worth −$600 less the
information bought (Appendix A.2). The hard part is whether information is worth its price and its
days. In one world the recorded supplier's award earns $418 and a newcomer 15% cheaper earns $628
if good, with odds of 0.45 good, 0.20 late and 0.35 poor; quoting it, then sampling it ($50) only
if the quote is clean, is worth $65.90 more than paying the premium, provided a failed test leaves
time to return to the recorded supplier. Every action is charged what it gave up against the
exact best informed policy at that point.

**Table 5.3. Procurement pay-or-test, 24 worlds per subject; dollars given up per world against the best policy, which earns $451 a world. All 96 losses and these intervals were reproduced on 16 October by a source-pinned derivation from replay-audited sealed actions; decision loss is separate from the original receipt scores.**

| | Sol 6.1 (Codex) | Opus 5.5 (Claude Code) | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| Given up per world | 1.0 [0.2, 2.1] | 5.4 [1.2, 10.6] | 75.2 [48.7, 101.4] | 74.4 [46.7, 102.7] |
| Share of the best policy's value | 99.8% | 98.8% | 83.3% | 83.5% |

The frontier agents (through their CLIs) are at the ceiling; most of what they lost on a first
run came from two rules the brief left unsaid, that a quote is final and that the average is the
criterion. That ceiling shows less than it seems: on this pack a rule that looks one test ahead
comes within $0.06 a world of the best policy, so near-perfect play shows that the agents avoid
the listed mistakes, not that they plan further ahead than one test. A v2 gate and pilot (50 cells, $0.22) found little newcomer testing and required 326 to 3,464 worlds against a 96-world cap, so no confirmatory run followed (Appendix F.4). The flash models give up what always paying the premium gives up: their loss is in
the worlds where a newcomer was worth testing.

**Data center.** The structure follows a real AI-infrastructure engagement in which a system
integrator bundles hardware, data-center space, staffing and software into a working system for a
client. Hardware can arrive late or defective and the site may not be ready, and the contract's
warranty, delay-damages, liability-cap, site-readiness, deposit and burn-in clauses decide who
bears each cost. Costs, probabilities and prices are set by the authors. Client and integrator
negotiate one agreement: a position on each of the eight clauses (600 distinct agreements) and an
all-in price p. Each side knows its own cost of carrying risk and only the odds of the other's: the
integrator's pre-staging cost and risk charge, the client's risk charge. Over six alternating
moves a side may redline any clauses and name a price, sign the standing version, or walk, and
each redline after the first move costs $25k. A signed agreement c pays the integrator
p − C_I(c) − 500 and the client O_C − p − C_C(c), in $ thousands and less redline fees, where 500
is the integrator's outside option, O_C the client's, and C_I and C_C each side's expected cost of
the risks the clauses leave with it, marked up by its risk charge; no deal pays only the fees. The
hard part is that price only divides the value while the clauses decide how much there is, and the
best clauses depend on what the other side hides. Burn-in, for example, costs the integrator $40k
and, in one world, the client a week's delay worth $110k, and halves the chance of a $3 million
incident the client carries; it lowers joint cost by $41k for a client with the highest risk
charge and raises it by $19k or $64k for the other two, and the integrator cannot tell which
client it faces. The comparison declared before its runs used 60 admitted worlds:
45 with a mutually beneficial deal and 15 without one. Table 5.4 reports its three primary
contrasts; development results remain in Tables E.3 and E.7.

**Table 5.4. Data-center agreement confirmatory: Sol 6.1 (Codex) and Opus 5.5 (Claude Code). Earnings are $ thousands above the seat's outside option, at true costs; intervals are 95%, with Holm correction across the three primaries. The campaign has eight documented departures and a partial Gate 5 verdict (Appendix F.5).**

| Primary contrast | Worlds | Estimate [95% interval] | Holm p |
|---|---:|---|---:|
| Head to head: Sol minus Opus earnings, seat-averaged | 45 deal | +190.1 [148.0, 232.1] | 3.2e-11 |
| Firm population: Sol minus Opus earnings, seat-averaged | 45 deal | +26.4 [10.5, 42.4] | 0.0017 |
| Client signs below its walk-away point: Opus / Sol | all 60 | 27/60 vs 3/60 (40 percentage points) | 2.4e-7 |

Sol's lead against the firm population is detectable but smaller than the plan's $50k minimum:
the 98.3% interval is [6.7, 46.1]. Head to head the opponent changes with the focal model;
the firm-population contrast holds the counterpart policy fixed. The distinction supports a
counterpart-specific reading of the larger head-to-head gap. All primary negotiations are valid.
Across the pilot and three arms, 1,175 of 1,176 negotiations are valid ($74.41 list price);
one secondary-arm CLI failure remains missing. The client seat still measures pricing and the
walk-away decision under nearly complete clause information, because the integrator's private
cost barely changes its best agreement.

The two CLIs were not equally isolated from the operator's machine: Codex's context listed eight of
the operator's own skills, two described in benchmark and evaluation terms, and Claude Code's listed
none (Table H.1). Every Sol-versus-Opus contrast in this paper carries that unmeasured difference; a
second confirmatory, declared with both subjects isolated and their context probed before it runs,
removes it.

### 5.2 Where the shortfall comes from

Figure 5.1 separates each case's shortfall into observed action classes. The components sum to
the total under a stated priority order; they describe what happened, not its cause. Each panel
uses its own reference and units. Appendix E.5 gives the rules and full subject tables; E.7 gives
the current Data-center breakdown and uncertainty. Table E.10 retains the exact panel values.

![Shortfall components across four cases, including all four Procurement subjects, with separate units and axes.](figures/shortfall_by_case.svg)

**Figure 5.1. Shortfall to each case's reference.** Segments account for observed actions;
labels give mean totals (lower is better within a panel). Units and scales differ. Housing shows
all three models on 260 worlds; GLM's inspection cost of −0.2 a world is in Table E.10 and is not
drawn. Procurement shows all four subjects; full subject tables are in Appendix E.5. Data center reports joint loss
against the full-information bound with firm counterparts at $25k per paid redline; individual below-walk-away signings
are separate (Table 5.4). Intervals and exact values appear in Tables 5.3, E.9 and E.10.

Procurement's Gemini loss comes entirely from foregoing useful tests; Housing's Gemini loss is
mostly worse lease terms. Luna's largest Housing class is signing at a rent above a lemon's value
when the reply identifies a lemon under the landlord policy. The v14 brief omitted that pricing
rule, so the label does not establish that the tenant knew how to interpret the reply. In Refund,
Gemini 2.5 Flash Lite's loss is chiefly procedure or format.

In Data center, the $25k redline fee accounts for 69.9% of Sol's and 40.3% of Opus's joint loss
against the firm population across all 60 worlds. Fees can accompany valuable contract
improvements; their share alone does not establish inefficient negotiation. The full-information
reference can agree immediately, so the gap includes costs that agents with limited information
may need to incur. Opus also signs harmful agreements in worlds without positive available surplus.

Exploratory replay with actions fixed separates scoring sensitivity from behavioral adaptation
(Appendix E.9). On the 45 deal-feasible worlds, Opus retains lower joint loss at zero fees;
Sol's earnings lead rises from $26.4k to $54.8k and reverses near $48.3k per redline. Across
all 60 worlds, however, removing fees reverses the joint-loss ranking: Sol loses $31.1k versus
Opus's $42.3k. Fee robustness therefore depends on the measure and the worlds included.

**Across the cases.** Four things hold. The gap sits in a stratum the design fixes in advance, so every
case reports by stratum and pools last. The counterpart is part of the measurement, so a claim
names the counterparts it covers. What the brief states moves the score as much as the subject
does (stating two rules cut procurement loss by $11 to $14; stating a walk-away cost cut losing
signatures from 15 of 60 to 1 of 60), so the brief is a versioned part of the case. And a pattern
found by looking back is a hypothesis until a declared test confirms it.

Housing, Procurement and Data center take their decision structure from real settings (Section
5.1): informal rentals, wholesale sourcing and AI-infrastructure contracting. Their parameters are
set by the authors, not calibrated to field data. The experiments use controlled scenarios and a small set of agent configurations, with no human
policy baseline; they do not establish general model rankings.

### 5.3 An external benchmark on the same runtime

TERMS-Bench evaluates bilateral price negotiation against counterparts whose type is hidden [TB].
We reimplemented, from the paper's description, its alternating-offer environment, three of its
six counterpart families (Candid, Taciturn and Expressive) and four of its measures as one AERead
family. The counterpart runs as a scripted seat, and its random draws are sealed each turn, so
replay recomputes the counterpart's moves as well as the scores. Not implemented: the Oracle-Cue
reference and the gap measures built on it, the urgency regime, type-belief error and the other
three families; counterpart messages are templates. The corpus has 30 cases, 15 with a zone of
agreement and 15 without, each played once.

**Table 5.5. TERMS-Bench reimplementation: two of the paper's agents on the same 30 cases, scripted
counterpart and settings. Agreement and surplus are over the cases with a zone of agreement: 15 for
GPT-4o-mini and 12 for GLM-5.1, whose three malformed moves removed those episodes. Paper values:
surplus efficiency from its Table 16 (overlap regime, mean of the three families played here);
agreement and conditional surplus efficiency from its Table 2, which pools six families and three
regimes.**

| | GPT-4o-mini | GLM-5.1 | Paper: GPT-4o-mini | Paper: GLM-5.1 |
|---|---:|---:|---:|---:|
| Agreement rate where a deal exists (AGR+) | 0.80 | 1.00 | 0.522 | 0.951 |
| Surplus efficiency (SE+) | 0.035 | 0.458 | 0.196 | 0.668 |
| Conditional surplus efficiency (CSE+) | 0.044 | 0.458 | 0.363 | 0.721 |

The reimplementation orders the two agents as the paper does on all three measures, but absolute
levels are lower for both, and for a third model. A review of the port after these runs traced the
shift to four departures from the paper's protocol, not to the agent, whose interface in the paper
is also one stateless call per round. Our prompt does not state the agent's payoff or the rule
against accepting above its reservation value; its observation differs from the paper's; a malformed
move removes the episode where the paper applies a fallback, under which GLM-5.1's surplus efficiency
would be 0.520 over all 15 cases; and our price range and zone widths are wider than the paper's. A
declared reproduction will follow those fixes. The paper reports critical violations by GLM-5.1 in
5% of cases without a zone of agreement for these three families; at that rate 15 such cases would
show none about half the time, and ours showed none. The port also exposed a harness effect. On one provider route, any declared
reasoning budget suppressed deliberation, and GLM 5.3 Flash breached its own reservation value in
13 of 30 cases against the paper's band of 0 to 2.06%. With no reasoning declaration it breached in
2 of 30 and its surplus efficiency rose from 0.40 to 0.53; the comparison above uses that setting.
This is why the reasoning condition is part of each run's declared configuration. The runtime
support for a scripted seat that this family uses is still in development.

### References

- [AV] Li, C. *Activities, not occupations.* AERead blog, 8 October 2026. https://aeread.org/blog/activities-not-occupations.html
- [TB] Zhang, E. et al. *TERMS-Bench: Diagnosing LLM Negotiation Agents Beyond Deal Rate.* arXiv:2605.13909, 2026.

### Sources for the numbers in this section

| Table or claim | Source | Status |
|---|---|---|
| Housing v14 (Tables 5.2, E.3) | `evidence/housing/housing_lemons_price_confirmatory_v14` and `..._v14_gemini_fill` (branch `codex/housing-lemons-outside-demand`, draft PR #256); the case contract's v14 section on that branch; one-pager `housing_lemons_confirmatory_v14_with_claude_codex.pdf` | confirmatory |
| HL-D-07 recomputation | the sealed v14 run roots; script and results `tools/paper/hl_d_07/` on this branch | derived |
| Housing pack, ceiling by arm, outside-demand share | the case contract's "confirmatory pack" paragraph; the code reading for Appendix A (`lemons_design.py`, `price_outside_demand.py`, `price_reference.py`) | |
| Housing CLI rows | run roots `housing_lemons_price_cli_v1_{claude_code_opus55,codex_cli_sol61}_outside_w20`; page 2 of the same one-pager | development, unadjusted |
| Best informed tenant ($307) | branch `codex/housing-best-informed`, `price_best_informed.py`; recomputed 2026-10-13 from its 600 cells per knowledge level | development |
| Pay-or-test (Tables 5.3, E.4) | run roots `pay_or_test_v1_{accounting,finalquotes}_*` (branch `codex/procurement-pay-or-test`); recomputed 2026-10-13 with `pay_or_test_report.py`; one-pager `procurement_pay_or_test_first_result.pdf`; incident rows P-D-19 to P-D-22, P-J-05 | development |
| Procurement flash panels | run roots `procurement_allocation_pay_or_test_v1_finalquotes_openrouter_{gemini38_flash,gpt6_luna}_v2` in the pay-or-test worktree; driver `tools/cli_subjects/pay_or_test_openrouter.py` (d91fbde8), report fix eecdaffe; incident rows P-D-23, P-O-05, P-O-06, P-T-14, P-T-15 | development |
| Record pack (18 worlds) | branch `codex/procurement-inference-v2`, draft PR #263; incident row P-D-16 | development |
| Data center development (Tables E.3, E.6, E.7), adversarial counterparts, signalling test | `agreement_results_2026-10.md` and `agreement_signalling_plan_2026-10.md` on branch `codex/datacenter-agreement`; bundles `evidence/datacenter_development/datacenter_agreement_cli_*` (incl. `scripted_tactics_v1`, `elicitation_probe_v1`); one-pagers `datacenter_agreement_first_result.pdf`, `..._scripted_result.pdf`, `..._signalling_test.pdf`; incident rows DC-D-32, DC-D-33, DC-J-07 | development; the signalling test was declared |
| Data center confirmatory (Tables 5.4, E.8; Figure 5.1c) | `agreement_confirmatory_results_2026-10.md` at `12516caf`; plan `ca9d5cac`; `agreement_confirmatory_analysis/reports/analysis.json` and five `datacenter_agreement_confirm_*_v1` bundles on `codex/datacenter-agreement` | declared primaries; eight departures; Gate 5 partial in the 16 October review |
| Procurement v2 gate and pilot | `pay_or_test_v2_results.md`, `pay_or_test_v2_confirmatory_plan.md`, the four retained gate/pilot roots on `codex/procurement-pay-or-test` (`29c00d83`); incident P-D-27 | development; stopped at sizing, no confirmatory run |
| Refund V2.5 cohorts, verifiers and qualification | `refund_v2_5_release.md` and the code on branch `codex/refund-v25-shared-runner` (draft PR #269); a provider-free rerun of the release, 816 of 816; incident rows RF-D-05, RF-D-06 | developmental release |
| Refund rows of Table 5.1 and Figure 5.1d | `evidence/refund/refund_v2_1_gap` (branch `codex/refund-gap-analysis`, draft PR #222); incident rows RF-D-01 to RF-D-04 | descriptive |
| Failure classes (Figure 5.1, Table E.10, Appendix E.5) | `tools/paper/failure_taxonomy/` on this branch, built from the bundles and run roots above; `analysis_evidence/shortfall_panels/derive_panels.py` matches Housing's corrected cell changes, Procurement's sealed reanalysis, Data-center confirmatory bundle grades and Refund's cell decomposition; components sum to the corresponding total | derived |
| Data-center fee sensitivity (Appendix E.9, Tables E.11-E.12) | `analysis_evidence/datacenter_fee_sensitivity/`: supplied `analyze.py` replayed against all 240 firm-population negotiations; `results.json`, `rows.json`, `edits.json`, source hashes and cohort checks | exploratory after the runs; fixed actions, six fee levels; no new model calls |
| Housing corrected measure and control contrasts (Table 5.2) | derived analyses `evidence/housing/housing_lemons_price_v14_reply_conditioned/` (765e99a7) and `..._v14_controls/` (55ce9d84) on branch `codex/housing-lemons-outside-demand`; `tools/paper/housing_controls_v14.py` on this branch | derived after the runs |
| Housing scripted controls (Table 5.2, last row) | derived analysis `evidence/housing/housing_lemons_price_v14_controls/` on branch `codex/housing-lemons-outside-demand` (55ce9d84), `reports/controls.json`, block `beatability_main_pack_primary_v1` | derived after the runs |
| TERMS-Bench reimplementation (§5.3, Table 5.5) | bundles `evidence/termsbench_gpt4o_mini_pilot_v1`, `termsbench_glm51_pilot_v1`, `termsbench_glm53_flash_parasail_pilot_v2` and `..._v3`, `reports/summary.json` (overlap aggregates); `docs/families/termsbench/campaign_scoping.md` (violation counts, reasoning probe); branch `codex/termsbench-scripted-counterpart` at `8f820c5b`, draft PR #153 on kernel PR #150; paper values from TERMS-Bench Table 2 (arXiv 2605.13909v2) | development; one play per case |
| Procurement grounding (§5.1) | frozen sourcing workbook `cases/procurement_grounding_v1/dev/procurement_grounding_231_projects.json` (as of 2026-08-31): `oracle.source_counts` (231 projects, 341 search-card suppliers, 236 sent requests to 28 suppliers, 9 quote suppliers) and `visible_evidence.priority_matrix` (51 original listings: 1 accepted, 20 conditional, 30 rejected) | record of the authors' own sourcing |
| TERMS-Bench review (§5.3) | incident rows TB-J-01, TB-D-06 to TB-D-09 (port review, 2026-10-18); TERMS-Bench Table 16 Panels A and C | review after the runs |
| Procurement against the 1688 record (§5.1) | `~/analysis/aeread-paper/procurement_calibration/` (script, inputs hashed, results at four mismatch cut-offs): a listing with a sales count was dearer than one without in 50% of 56 comparable parts (48–51% across cut-offs); 9 of 28 suppliers quoted | analysis of the authors' own record, 2026-10-18 |
| Housing CLI cost ($4.72) | list prices of the two CLI runs, $1.78 (Sol) and $2.94 (Opus), from the CLI probe's run reports | development |
