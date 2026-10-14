# Case studies (draft section of the AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. The main-text section; case
details are in [Appendix E](paper_appendix_details.md), formal specifications in
[Appendices A–D](paper_appendix_case_specs.md). One result is confirmatory (Housing v14), one is
a test declared before its runs (the data-center signalling test), and everything else is a
development probe. The companion section is [Quality control](paper_qc_design.md).

---

## 5. Case studies

AERead is meant to grow through cases contributed by a wider community. We present four cases
built by the maintainers as worked examples of what a contributed case can look like (Table
5.1). Housing, Procurement and Data center are described here and specified in Appendices A–D;
Refund appears only in the cross-case comparison. Each case is a family rather than a fixed task
set: a generator of worlds, a reference computed from what the deciding side may know, an
admission rule that keeps only worlds where the decision matters, and a set of verifiers.

Cases are chosen by the economic value of the decision, not by occupation [AV]: an activity
qualifies when its value is decided rather than produced, a counterparty has its own interest and
private information, and the result can be scored inside a world against a computed reference.
The four examples sit in two of the five classes of transaction that weight the suite's target
distribution (business and household purchases, 49% of the weight); they were chosen to span the
kinds of verifier and counterpart, not sampled from that distribution.

**Table 5.1. The four examples.**

| Case | Decision under test | Model's seat; counterpart | Reference | Verifiers | Status | Headroom (hardest stratum) |
|---|---|---|---|---|---|---|
| Housing | which listing to verify, what to offer, whether to sign when two of four listings are lemons | one tenant; scripted landlords of two kinds, outside demand | a reachable scripted tenant ($292 a world); a full-information ceiling ($370) | value; rule | confirmatory | shown: Gemini −102 [−122, −82] a world against the reference where the favourite is a lemon |
| Procurement | pay a premium for a recorded supplier, or test a cheaper newcomer, before a deadline | one buyer; scripted suppliers | the best informed policy, solved exactly ($451 a world) | value, priced per action | development | flash tier only: Luna gives up 74.4 [46.7, 102.7] a world, the frontier agents 1 to 5 |
| Data center | which of eight risk clauses to move, what price to name, when to sign or walk | client or integrator; the other model, itself, or a scripted negotiator | the best of 600 agreements at both sides' true costs | value; relative; rule | development, one declared test | shown: the pair loses 79 [70, 88] of about 410 a world head to head |
| Refund | what to ask, decide and pay on a claim under a written policy | one of four seats; the rest scripted | a hand-written reference resolution | answer; rule | developmental | suggested: the best model resolves 79% of cases as scored, against 100% (six cases) |

The Verifiers column uses the kinds of check defined with the runner's measurement layer (§4):
an answer key, declared rules, the value of the best policy or a bound, relative standing
against another agent, or a rubric. The four cases use the first four and no rubric, and every
score replays from the sealed trajectory without a model. Table E.1 lists every check.

### 5.1 Results

**Housing.** A tenant faces four landlords; two listings are lemons worth $1,000 less, an
inspection costs $25, and over three rounds each listing the tenant did not bid on is taken by
outside demand with probability ½. Every world is played against a landlord whose reply reveals
a lemon and one whose reply does not. Blind signings are scored at their expected value given
the reply, so the score follows the decision rather than the draw.

**Table 5.2. Housing v14, main pack (260 worlds); dollars per world, 95% intervals paired by world.**

| | Gemini 3.8 Flash | GLM 5.3 Flash | GPT-6 Luna |
|---|---:|---:|---:|
| Tenant net per world | +211 [+188, +233] | +137 [+111, +162] | +130 [+104, +156] |
| Minus the reference, favourite is a lemon (200) | −102 [−122, −82] | −179 [−203, −154] | −207 [−229, −186] |
| Minus the reference, favourite is sound (60) | −13 [−18, −8] | −76 [−116, −36] | −9 [−16, −2] |

Under an analysis declared before any cell (three pairs, Holm; $50 minimum), Gemini leads GLM by
+70 [+48, +92] and Luna by +80 [+62, +99]; GLM and Luna do not differ; the 40-world holdout
agrees. None reaches the reference, and almost the whole shortfall is in worlds where the
favourite listing is a lemon. A correction to the measure found while writing this paper
(HL-D-07) moves no declared verdict: Gemini's leads become +60 and +67.

**Procurement.** A buyer owes 50 kits by a deadline. It may pay the most for a supplier with a
long record, or test a cheaper newcomer whose cohort record states how often its kind failed; a
quote shows delivery, a sample shows yield, and both take money and days. Every action is charged
what it gave up against the exact best informed policy at that point.

**Table 5.3. Procurement pay-or-test, 24 worlds; dollars given up per world against the best policy.**

| | Sol 6.1 | Opus 5.5 | Gemini 3.8 Flash | GPT-6 Luna |
|---|---:|---:|---:|---:|
| Given up per world | 1.0 [0.2, 2.1] | 5.4 [1.2, 10.6] | 75.2 [48.7, 101.4] | 74.4 [46.7, 102.7] |
| Share of the best policy's value | 99.8% | 98.8% | 83.3% | 83.5% |

The frontier agents (through their CLIs) are at the ceiling; most of what they lost on a first
run came from two rules the brief left unsaid, that a quote is final and that the average is the
criterion. The flash models give up what always paying the premium gives up: their loss is in
the worlds where a newcomer was worth testing.

**Data center.** Client and integrator redline one services agreement, eight risk clauses and a
price, over six moves; each knows only its own costs, and every amount is computed at both sides'
true costs.

**Table 5.4. Sol 6.1 minus Opus 5.5 in the same seat, by counterpart ($ thousands per world, 52 deal worlds).**

| Counterpart | As integrator | As client |
|---|---:|---:|
| The other model | +248 [+206, +290] | +251 [+209, +293] |
| Soft script | +86 [+56, +116] | +95 [+74, +115] |
| Collapse, price-only, overreach scripts | +32 to +112 | +54 to +148 |
| Firm population of scripts | +17 [−10, +44] | +23 [−2, +48] |

Head to head the pair recovers about 80% of the value available, against 14% for signing the
draft unchanged. Sol keeps far more than Opus against a model that gives way, but against a firm
counterpart the two are not distinguishable, so a result against one counterpart could be any
number in that range. Against an overreaching script Opus signs below its own walk-away point in
23 of 52 worlds and Sol in none; against a counterpart that asks for private information neither
model leaks a confidential item. A test declared before its runs supported one of two
looked-back signals and rejected the other.

### 5.2 Where the shortfall comes from

Each case's shortfall against its reference splits into a small set of shared classes, named by
what happened in the sealed trajectory rather than by an inferred cause, and computed rather than
judged. Each unit of shortfall (a cell, or in Procurement an action) is assigned to the first
thing that went wrong, by a declared priority, so the classes sum exactly to the shortfall.
Appendix E.5 gives the rules for each case and the full tables.

**Table 5.5. The shortfall to each case's reference, by class (per world, each case in its own units).**

| Class (what happened) | Housing $: Gemini / Luna | Procurement $: Opus / Gemini | Data center $k joint: Opus / Sol vs firm | Refund points: GPT-5.6 Luna / Gemini 2.5 FL |
|---|---|---|---|---|
| Information not acquired | 6.6 / 32.4 | 2.6 / 75.2 | — | 15.0 / 0 |
| Information misread | 11.2 / 86.4 | 2.8 / 0 | — | 0 / 0 |
| Worse terms | 54.6 / 39.1 | 0 / 0 | 4.8 / 9.1 | 0 / 0 |
| Commitment error | 8.5 / 2.9 | 0 / 0 | 6.9 / 32.0 | — |
| Bargaining cost | 0.2 / 1.0 | 0 / 0 | 29.8 / 80.2 | — |
| Procedure and format | 0 / 0 | 0 / 0 | 0 / 0 | 5.8 / 98.3 |
| **Total shortfall** | **81.0 / 161.6** | **5.4 / 75.2** | **41.5 / 121.3** | **20.8 / 98.3** |

The classes separate failures that one score would merge. The flash models in Procurement lose
almost everything by not acquiring information: they pay the premium where a test was worth it.
In Housing, GLM and Luna lose most by misreading what they were shown, signing holds only a lemon's
landlord would offer (about half of their shortfall), while Gemini's smaller loss is mostly worse
terms. In the agreement the joint loss is mostly bargaining cost; against the firm script Sol also
loses deals (commitment errors), though in 7 of its 8 the script walked away from Sol's last offer; Opus's characteristic error does not appear in joint value at all,
because signing below one's own walk-away point is a transfer: as client it did so in 12 of 52
worlds against Sol and 2 against the firm script. In Refund most models lose by deciding before a
required fact (information not acquired), while Gemini 2.5 Flash Lite loses almost everything to
procedure, asking again for facts it already had. A class records
what happened, not why; a cause stays a hypothesis until a probe holds the world fixed, as the
data-center signalling test did.

**Across the cases.** Four things hold. The gap sits in a stratum the design fixes in advance, so every
case reports by stratum and pools last. The counterpart is part of the measurement, so a claim
names the counterparts it covers. What the brief states moves the score as much as the subject
does (stating two rules cut procurement loss by $11 to $14; stating a walk-away cost cut losing
signatures from 15 of 60 to 1 of 60), so the brief is a versioned part of the case. And a pattern
found by looking back is a hypothesis until a declared test confirms it.

These cases do not rank models in general: two frontier agents at one reasoning setting and a few
flash-tier models played them. No practitioner has set or reviewed the prices, fees and odds, and
no human has played them.

### References

- [AV] Li, C. *Activities, not occupations.* AERead blog, 8 October 2026. https://aeread.org/blog/activities-not-occupations.html

### Sources for the numbers in this section

| Table or claim | Source | Status |
|---|---|---|
| Housing v14 (Tables 5.2, E.3) | `evidence/housing/housing_lemons_price_confirmatory_v14` and `..._v14_gemini_fill` (branch `codex/housing-lemons-outside-demand`, draft PR #256); the case contract's v14 section on that branch; one-pager `housing_lemons_confirmatory_v14_with_claude_codex.pdf` | confirmatory |
| HL-D-07 recomputation | the sealed v14 run roots; script and results `~/analysis/housing/hl_d_07/` (outside the repository) | derived |
| Housing pack, ceiling by arm, outside-demand share | the case contract's "confirmatory pack" paragraph; the code reading for Appendix A (`lemons_design.py`, `price_outside_demand.py`, `price_reference.py`) | |
| Housing CLI rows | run roots `housing_lemons_price_cli_v1_{claude_code_opus55,codex_cli_sol61}_outside_w20`; page 2 of the same one-pager | development, unadjusted |
| Best informed tenant ($307) | branch `codex/housing-best-informed`, `price_best_informed.py`; recomputed 2026-10-13 from its 600 cells per knowledge level | development |
| Pay-or-test (Tables 5.3, E.4) | run roots `pay_or_test_v1_{accounting,finalquotes}_*` (branch `codex/procurement-pay-or-test`); recomputed 2026-10-13 with `pay_or_test_report.py`; one-pager `procurement_pay_or_test_first_result.pdf`; incident rows P-D-19 to P-D-22, P-J-05 | development |
| Procurement flash panels | run roots `procurement_allocation_pay_or_test_v1_finalquotes_openrouter_{gemini38_flash,gpt6_luna}_v2` in the pay-or-test worktree; driver `tools/cli_subjects/pay_or_test_openrouter.py` (d91fbde8), report fix eecdaffe; incident rows P-D-23, P-O-05, P-O-06, P-T-14, P-T-15 | development |
| Record pack (18 worlds) | branch `codex/procurement-inference-v2`, draft PR #263; incident row P-D-16 | development |
| Data center (Tables 5.4, E.3), adversarial counterparts, declared test | `agreement_results_2026-10.md` and `agreement_signalling_plan_2026-10.md` on branch `codex/datacenter-agreement`; bundles `evidence/datacenter_development/datacenter_agreement_cli_*` (incl. `scripted_tactics_v1`, `elicitation_probe_v1`); one-pagers `datacenter_agreement_first_result.pdf`, `..._scripted_result.pdf`, `..._signalling_test.pdf`; incident rows DC-D-32, DC-D-33, DC-J-07 | development; the signalling test was declared |
| Refund V2.5 cohorts, verifiers and qualification | `refund_v2_5_release.md` and the code on branch `codex/refund-v25-shared-runner` (draft PR #269); a provider-free rerun of the release, 816 of 816; incident rows RF-D-05, RF-D-06 | developmental release |
| Refund rows of Tables 5.1 and 5.5 | `evidence/refund/refund_v2_1_gap` (branch `codex/refund-gap-analysis`, draft PR #222); incident rows RF-D-01 to RF-D-04 | descriptive |
| Failure classes (Table 5.5, Appendix E.5) | scripts and results in `~/analysis/paper/failure_taxonomy/` (outside the repository), built from the bundles and run roots above; each case's classes sum to its published shortfall (checked to 1e-9) | derived |
| Housing CLI cost ($4.72) | list prices of the two CLI runs, $1.78 (Sol) and $2.94 (Opus), from the CLI probe's run reports | development |
