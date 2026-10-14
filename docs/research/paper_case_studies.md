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
admission rule that keeps only worlds where the decision matters, and a set of verifiers. Cases
are chosen by the economic value of the decision, not by occupation [AV] (§5.3).

**Table 5.1. The four examples.**

| Case | Decision under test | Model's seat; counterpart | Reference | Verifiers | Status |
|---|---|---|---|---|---|
| Housing | which listing to verify, what to offer, whether to sign when two of four listings are lemons | one tenant; scripted landlords of two kinds, outside demand | a reachable scripted tenant ($292 a world); a full-information ceiling ($370) | value; rule | confirmatory |
| Procurement | pay a premium for a recorded supplier, or test a cheaper newcomer, before a deadline | one buyer; scripted suppliers | the best informed policy, solved exactly ($451 a world) | value, priced per action | development |
| Data center | which of eight risk clauses to move, what price to name, when to sign or walk | client or integrator; the other model, itself, or a scripted negotiator | the best of 600 agreements at both sides' true costs | value; relative; rule | development, one declared test |
| Refund | what to ask, decide and pay on a claim under a written policy | one of four seats; the rest scripted | a hand-written reference resolution | answer; rule | developmental |

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

### 5.2 Headroom, and what holds across cases

A case is useful only while it is unsaturated, so headroom is shown, not assumed: the best
subject must fall short of a reference it could reach, in a stratum declared before the runs.

**Table 5.5. Headroom in each case's hardest declared stratum.**

| Case | Stratum | Best subject minus reference | Headroom |
|---|---|---|---|
| Housing | favourite is a lemon | Gemini −102 [−122, −82] a world | shown |
| Data center | deal worlds, head to head | the pair loses 79 [70, 88] of about 410 | shown |
| Procurement | all worlds | frontier: Sol gives up 1.0 [0.2, 2.1]; flash: Luna 74.4 [46.7, 102.7] | shown for the flash tier only |
| Refund | six cases, one seat | best model resolves 79% as scored against 100% | suggested; no interval |

Four things hold across the cases. The gap sits in a stratum the design fixes in advance, so every
case reports by stratum and pools last. The counterpart is part of the measurement, so a claim
names the counterparts it covers. What the brief states moves the score as much as the subject
does (stating two rules cut procurement loss by $11 to $14; stating a walk-away cost cut losing
signatures from 15 of 60 to 1 of 60), so the brief is a versioned part of the case. And a pattern
found by looking back is a hypothesis until a declared test confirms it.

### 5.3 Coverage and task distribution

Cases are weighted by the flow a class of transaction decides, not by the hours spent on it [AV]:
an activity qualifies when its value is decided rather than produced, a counterparty has its own
interest and private information, and the result can be scored in a world against a computed
reference. Each transaction is counted once, its two seats share the weight, and a 10% floor keeps
every class readable.

**Table 5.6. The target distribution, and where the four examples sit.**

| Class | Flow decided (US, 2025) | Weight | Examples |
|---|---|---:|---|
| Business purchases | $20.0T of inputs | 39% | Procurement; Data center |
| Labour contracts | $15.7T of compensation | 30% | none |
| Capital and corporate transactions | $5.6T of investment | 11% | none |
| Household purchases, the dealt part | $3.2T | 10% | Housing; Refund |
| Public purchases | $3.1T | 10% | none |

The examples cover two classes, 49% of the weight, by design: they were chosen to span kinds of
verifier and counterpart, and the distribution is what contributed cases fill. They do not rank
models in general: two frontier agents at one reasoning setting and a few flash-tier models
played, no human did, the numbers are the designers' assumptions, and only Housing ran a declared
confirmatory campaign.

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
| Refund V2.5 cohorts, verifiers and qualification | `refund_v2_5_release.md` and the code on branch `codex/refund-v25-shared-runner` (draft PR #269); a provider-free rerun of the release, 816 of 816; incident rows RF-D-05, RF-D-06 | developmental release |
| Refund V2.1 rows of Tables 5.4 and 5.9, and §5.1 | `evidence/refund/refund_v2_1_gap` (branch `codex/refund-gap-analysis`, draft PR #222); incident rows RF-D-01 to RF-D-04 | descriptive |
| Task distribution (Table 5.10) | [AV], from the BEA national accounts (2025) and BLS wage statistics (May 2023) | |
| Housing CLI cost ($4.72) | list prices of the two CLI runs, $1.78 (Sol) and $2.94 (Opus), from the CLI probe's run reports | development |
