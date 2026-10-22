# T5 Statistical design: evidence ledger

**Evidence ledger for [T5](../T5_statistical_design.md).** Line references are at main 1e2ae367 unless a row says otherwise.

Snapshot: origin/main `1e2ae367` (verified with `git rev-parse origin/main`), threads fetched 2026-10-21/22. Source tree `S` = the repository at `origin/main` `1e2ae367`. PR #288 diff saved read-only at head `159cba3c`. Cluster ids (G01..G36) refer to the root-cause clustering summarised in the [themes README](../README.md). Labels: [read] source read; [run] reproduced; [row] taken from issue/incident text.

## 1. Evidence ledger

| # | Claim | Source | Label |
|---|---|---|---|
| E1 | PR #288 is OPEN, draft, mergeable=CONFLICTING, head `159cba3c`, 12 files +1044/-16, CI green on that head (test 3.10/3.12, kernel-review, fidelity jobs), no review, no comments | `gh pr view 288` | [read] |
| E2 | #288 body: draft because the author has 6 ready PRs against a limit of 3; family lane, touches nothing under `shared_runner/`, `cli.py`, `conftest.py` | PR #288 body | [read] |
| E3 | #288 adds package `src/aeread/design/` with `worlds_needed`, `sizing_record`, `verify_sizing_record`, `detection_rate`, `sd_of_differences`, `smallest_detectable_effect`, `variance_components`, `reliability`, `worlds_for_reliability`, `sign_agreement`, `admit_probability`, `screen_plan`, `aa_check` | `pr288.diff` lines 332-856 (`design/__init__.py`) | [read] |
| E4 | `aeread.design` does not exist on main | `ls S/src/aeread/` shows `exchange_v1 inference integrations shared_runner`; `ls S/src/aeread/design` fails | [run] |
| E5 | #288 adds SOP and QC text: QC Gate 1 "Sampling plans" table, Gate 4 items 6-7 (counterpart scope, A/A arm), Gate 5 item 2 (seal sizing record; "a pack smaller than its own sizing record is not frozen"), Gate 5 item 6 (interval and missingness rules), a "Reliability" definition; SOP sections on strata sizing, A/A before freeze, exploratory factorial, interleaving | `pr288.diff` lines 1-331 | [read] |
| E6 | #288 states what it leaves open per issue: no family writes the sizing record at `confirmatory_freeze`; panel manifests recording the plan (new panels only); live A/A arm on one family; sign-flip test in kernel `paired.py`; contracts recording each split's minimum effect and counterpart types; contract schema accepting the exploratory type; balance preflight (kernel lane) and spending-limit field for #286; Housing v14 and other analyses calling the missingness bounds | PR #288 body table; author comments on #273, #285, #282, #271, #272, #274, #277 | [read] |
| E7 | #288 does not touch the kernel and adds no contract field, so it cannot make the freeze reject a missing sizing record. The gate sequence `design_contract ... confirmatory_freeze ...` is a list of typed history records; `campaign.py` checks status and sequence, and `grep` finds no `sizing` in `shared_runner/run/*.py` | `src/aeread/shared_runner/run/campaign.py:32-41, 325-365`; grep over `src/aeread/shared_runner/run` | [read] + [run] |
| E8 | The author's own rule for first adoption is a freeze test: "The first campaign that freezes after the PR merges should call `verify_sizing_record(record, frozen_worlds=...)` in its freeze test" | #273 comment by LEE-CHENYU 2026-10-14 | [read] |
| E9 | Main already holds a byte copy of #288's sizing module: `tools/housing/sizing_159cba3c.py`, sha256 `6a3f0794...a41f`, loaded by `tools/housing/price_v15_sizing.py` (digest checked) to write `docs/families/housing/price_v15_sizing_record.json` (worlds_needed 20, cap 260, effect 50, power 0.8, alpha 0.05, attrition 0.05). So one family has adopted the calculation by vendoring an unmerged PR file. | `tools/housing/price_v15_sizing.py:1-30`; `shasum -a 256 S/tools/housing/sizing_159cba3c.py`; `docs/families/housing/price_v15_sizing_record.json` | [run] |
| E10 | `git branch -r --contains 159cba3c` lists only `origin/codex/methods-design` and `pr/288`: the vendored file's origin is unmerged | git | [run] |
| E11 | Kernel paired analysis already returns `cluster_bootstrap_95` (percentile), `paired_t_95` and `missingness_difference_bounds`; no sign-flip test exists in `src` | `src/aeread/shared_runner/analysis/paired.py:175-216`; `grep sign_flip` over src and docs finds only a prose mention at `docs/families/housing/case.md:701` | [read] + [run] |
| E12 | Percentile world bootstrap covers 89/93/94% at 10/20/50 worlds with no true gap; paired t covers 95% at all three (author's corrected figures, test in PR) | PR #288 body; #271 author comment (issue text quoted 91/92/95, corrected) | [row] (test not re-run) |
| E13 | Housing v14 used 260 worlds where ~50 suffice for one pair and ~6,000 would be needed for another; only two older Housing analyses call missingness bounds | #273 body; #274 body | [row] |
| E14 | Procurement has a headroom/policy-separation screen (it is not the only one; see E32): `classify_world_by_policy_separation` requires two structurally different policies to differ in expectation | `src/aeread_families/procurement_allocation/headroom_screen.py:152-165`; imported at `continuous_campaign.py:21` | [read] |
| E15 | Screen miss rates: under a never-or-always rule one seed cannot admit a world; at 10 seeds a world solved 9 in 10 is admitted 65% | PR #288 QC table (`pr288.diff` "Sampling plans"); #285 comment | [row] (asserted equal to `screen_plan` by a PR test, not re-run) |
| E16 | Collusion primary returns `invalid_measurement` with reason `baseline_profit_not_provided` when the baseline dict is None; baseline is "run under the identical cell/horizon/opponent condition" as a separate episode, and provenance is trusted from the caller | `src/aeread_families/collusion/measurement.py:639-667` | [read] |
| E17 | Leaf scope is `finalize_time` or `deferred`; a deferred leaf must name `deferred_artifact`; "a leaf may not be marked deferred merely because computing it is inconvenient" | `src/aeread/shared_runner/schemas.py:337, 350-356, 389-416` | [read] |
| E18 | A family score set holds one primary and the admission leaves; primary must also be an admission leaf. The #71 contract (quoted in #100) forbids a deferred leaf as primary or admission | `src/aeread/shared_runner/measurement.py:405-447`; #100 body | [read] + [row] |
| E19 | AucArena degenerate case: comparator is a frozen rule-bidder field seat; empty roster gives `invalid` with "empty comparator population". Comparison is between seats inside one episode | `src/aeread_families/aucarena/measurement.py:750-768` | [read] |
| E20 | NegArena maps the opponent profile to a frozen policy through `OPPONENT_PROFILE_TO_POLICY_ID`; unmapped gives an invalid envelope | `src/aeread_families/negarena/measurement.py:585-598` | [read] |
| E21 | EconAgent declares `primary_estimand "econagent_budget_identity"`, `direction "none"`, a conformance check | `src/aeread_families/econagent_v1/environment.py:118-130` | [read] |
| E22 | Decision on #135.c, stated as an owner decision in Zeyu's own comment of 2026-09-08 ("Approved repair program"); Chenyu's comments of 2026-09-10 and 2026-09-19 do not mention AucArena, so this is a record, not a verified owner ruling: preserve `aucarena.pilot.degenerate_reference_01` byte-for-byte as QC-only, remove it from the live panel, add a separately identified frozen-field case | #135 thread (owner ruling block, item 3) | [read] |
| E23 | #100 proposes `X_own` (finalize_time, primary) and `X_vs_baseline` (deferred) for every family; collusion first, econevals second instance; no owner ruling in the thread (last comment 2026-09-06) | #100 body and comment | [row] |
| E24 | Repository analysis rules: distributions, run-to-run variance, confidence intervals "the case is the resampling unit, cases that share their facts are one cluster, and conditions run on the same cases are compared as paired differences", judge agreement | `CLAUDE.md:67-80` | [read] |
| E25 | Refund 120-cell panel is six cases (20 seeds repeat one prompt); procurement seeds are repeats; data-center counteroffer cases pin one world (15 of 15) | records RF-D-01, P-D-01, DC-D-02 | [row] |
| E26 | Control ladder gaps: Refund V2.5 naive_full_refund passes 38/180, naive_no_mutation reaches reference 17-100% (#290 is Chenyu's design hand-over to Yuchen with "Change proposed" rows, not a ruling; board status `ruled_awaiting_impl` is not supported by the issue text); Refund has no lower controls rule (RF-D-04); procurement pay_or_test gives up $1.0 (Codex) and $5.4 (Opus) per world vs best (P-D-22); two data-center lower controls coincide in 36 of 58 worlds (DC-D-28); micro-GRPO case has zero reward variance (#4.e) | records #290.a, #290.d, RF-D-04, P-D-22, DC-D-28, #4.e | [row] |
| E27 | New since taxonomy: #301 (data-center agreement v3 pack needs an exact reference and a shortcut screen in every world) and #302 (Housing next pack must screen against `inspect_lowball` and use partial pass-through; v15 passes Gate 1 on the exact-reference route but `inspect_lowball` is within $25 of best-informed in 229 of 260 worlds) | #301, #302 bodies; Chenyu comment on #302 2026-10-22 | [row] |
| E28 | Scripted-vs-live: data-center Codex-minus-Opus gap is 248k head-to-head and 17k [-10,44] against the firm script; `drawn_style` hashes the whole world including the client's hidden charge (DC-D-32) | records #275, #283, DC-D-32 | [row] |
| E29 | #292 (kernel, draft) adds declared campaign admission and launch gates for spend and operational halts; it says "Scoring-contract changes: none" and is not a design-gate vehicle | `gh pr view 292` body | [read] |
| E30 | Kernel landing order set by owner: #246 (merged), #291, #292, #293; #248 after part-1 repairs | [rulings register](rulings_register.md) D-11 | [read] |
| E32 | Housing's pack screen already admits by structure, ceiling and headroom: `screen()` returns status structure, zero_ceiling, headroom or passed, with `HEADROOM_MIN` | `src/aeread_families/housing/price_pack_v2.py:165-180` | [read] |
| E33 | QC Gate 3 already lists controls (no-op or lower anchor, random or weak, simple baseline, informed policy, oracle diagnostic "normally") and requires a beatability rule predeclared before model results; #288 does not change Gate 3 | `docs/operations/benchmark_qc.md:324-345`; #288 diff touches Gates 1, 4, 5 only | [read] |
| E34 | Housing v15 results already report an A/A: Luna minus its twin (seed 88001) -5.0 [-18.8, 8.9], twin 520 cells; it is part of the confirmatory run, after the freeze. #282 asks for a pre-freeze A/A in `variance_pilot`; Chenyu notes published bundles hold action-level trajectories, so per-world replicate scores need family-specific parsing | `docs/families/housing/price_confirmatory_v15_results.md:17,31-37`; #282 comment | [read] |
| E35 | `missingness_difference_bounds` is a returned field of `analyze_paired_results()`, not a function; bounds are `None` with status `unavailable_without_declared_outcome_support` unless `score_support_by_world` supplies per-world lowest and highest scores | `src/aeread/shared_runner/analysis/paired.py:131-216` | [read] |
| E36 | #288 already carries the reporting rule: compare missingness between arms; bounds that include zero or reverse a claimed gap read "inconclusive" | #274 comment; `pr288.diff` Gate 5 item 6 | [read] |
| E37 | `verify_sizing_record` checks schema, that the record recomputes from its inputs, and that frozen_worlds >= the record's worlds; it does not look at any screen plan | `aeread/design/sizing.py` at `159cba3c` (`git show FETCH_HEAD:src/aeread/design/sizing.py`) | [read] |
| E38 | #94 (pre-award holdout run, waiting on Chenyu review) and #281 (reference panel, Backlog) have no delivery step in #288 | issue bodies; board items | [read] |
| E31 | PR #256 (Housing v14 analysis, named in #274) is not in the open PR list at 2026-10-22; #288 is one of many draft PRs by LEE-CHENYU | `gh pr list -R aeread-org/AERead --state open` | [run] |

## 2. Members

Cluster G19 (14): the shared design layer. Cluster G15 (13): world admission. Cluster G16 (9): controls and headroom. Cluster G12 (5, split). Cluster G20 (5): counterpart validity. Board T5 items (20): #94, #100, #4, #270, #271, #272, #273, #274, #275, #276, #277, #278, #281, #282, #283, #284, #285, #288, #301, #302 (#279, #280 are not in this theme).

| Member | What | State (2026-10-22) | Owner | Still true at 1e2ae367 |
|---|---|---|---|---|
| #270 | Rehearse sealed analysis on simulated data before spend | open research; no PR covers it (`aa_check` is the nearest, provider-free half) | Chenyu | yes: no rehearsal tool on main [run] |
| #271 | Name interval/test by cluster count | rule in #288; sign-flip in kernel open | Chenyu | partly: paired.py has bootstrap and t, no sign-flip [read] |
| #272 | Size a split for its own effect | rule in #288; contract field open | Chenyu | yes until #288 merges |
| #273 | Shared sizing calculation, sealed record | function in #288; no family writes record at freeze (Housing v15 wrote one via vendored copy, E9) | Chenyu | partly: record exists for Housing v15 only |
| #274 | Missingness by arm, worst-case bounds | rule in #288; kernel computes bounds; analyses do not call them | Chenyu | yes |
| #275 | Claim scope per counterpart | rule in #288; contract fields open | Chenyu | yes |
| #276 | Define reliability for Gate 5 | fully in #288; close on merge | Chenyu | yes until #288 merges |
| #277 | Exploratory factorial design type | SOP text in #288; schema open | Chenyu | yes |
| #278 | Separate random streams per source | research, no audit; Housing lemons already separate (HL-D-03) | Chenyu | not checked beyond record |
| #281 | Reference panel and control chart | research; not in #288 | Chenyu | yes |
| #282 | A/A through full pipeline | rule and `aa_check` in #288; live arm open | Chenyu | yes |
| #283 | Scripted vs live counterparts | open defect | Chenyu | yes |
| #284 | Invariance test | research | Chenyu | yes |
| #285 | Screen plans and miss rates | table and `screen_plan` in #288; manifest field open | Chenyu | yes |
| #286.b | Interleave arms sharing an account | rule in #288; close on merge | Chenyu | yes |
| #94 | Pre-award confirmatory holdout + control arm run | research run, waiting on Chenyu | Chenyu | not checked |
| #4 / #4.e | Micro-GRPO zero gradient; per-case base-rate first | open; #4.e is the reason for a control ladder | Chenyu | record only |
| #100 / #100.a, #100.b | Collusion and econevals baseline-relative primary; own/vs_baseline split | blocked on Chenyu ruling; no comment since 2026-09-06 | Chenyu | yes: E16 |
| #116 | EconAgent primary is a conformance check | blocked on Chenyu | Chenyu | yes: E21 |
| #135.c | AucArena degenerate reference | ruled (E22), awaiting successor panel | Zeyu | yes: E19 |
| #135.e | NegArena frozen opponent comparison policy | blocked on Chenyu | Chenyu | yes: E20 |
| DC-D-29, HL-J-02 | Seed-noise gap not a separation; "luck removed" label erratum | open | none assigned | row only |
| P-D-01, P-D-03, RF-D-01, DC-D-02 | seeds that are repeats; declared noise not reaching score | open (DC-D-02 partly fixed) | none assigned | row only |
| DC-D-30, -33, -34, -35, -36, -42, P-D-09, -12, -13 | world informativeness defects | open; DC-D-36 waits on owner | none assigned | row only |
| RF-D-04, #290.a, #290.d, DC-D-28, P-D-16, -20 (superseded), -22, -27 | control ladder and headroom | #290.a/d ruled awaiting implementation (Yuchen) | mixed | row only |
| #275, #283, #284, #278, DC-D-32 | G20 counterpart/world validity | see above; DC-D-32 fix changes every drawn style (new style identity) | Chenyu / none | row only |
| #301, #302 | Next data-center and Housing packs must screen against shortcuts | open, triage, new | Chenyu | yes |
| PR #288 | the vehicle | draft, conflicting, CI green | Chenyu | E1 |

## 3. Rulings in force

| Ruling | Label | Source |
|---|---|---|
| Kernel landing order #246, #291, #292, #293; #248 after part-1 repairs | [owner] | rulings register D-11 |
| AucArena: keep legacy degenerate case QC-only, add a new frozen-field case id | [record] (Zeyu's 2026-09-08 comment calls it an owner decision; no Chenyu comment found restating it) | #135 thread |
| Scoring contract #71: leaves are finalize_time or deferred; primary and admission leaves must be finalize_time | [merged] | schemas.py:350-356, measurement.py:405-447 |
| SOP: confirmatory size comes from paired cluster-level variance, declared minimum effect, power and attrition (existing text, before #288) | [merged] | `docs/operations/experiment_campaign_sop.md:90-95`, QC Gate 5 item 2 |
| Strata: five independent units per stratum is a floor | [merged] | SOP strata section (quoted in #272) |
| Reported analysis rules (distributions, variance, CI with case as resampling unit, judge agreement) | [merged] | `CLAUDE.md:67-80` |
| #290.a, #290.d: not a ruling; proposal in Chenyu's #290 hand-over to Yuchen (may be adopted in part) | owner proposal, not in the label set | #290 body |
| #288's new SOP/QC wording | [record] until merged | PR #288 |

## 4. Open questions

1. Is #288 ready to be undrafted, and does the owner want the design package to be the only home of these calculations (Housing v15 already vendors a copy)?
2. Who enforces the sizing record at `confirmatory_freeze`: a family freeze test (as #273 comment says) or a kernel contract field? The second needs the landing order; #292 is not that vehicle (E29).
3. #100/#116/#135.e: the four families' primary estimands need four separate rulings; #100 asks for one family-wide rule (X_own/X_vs_baseline).
4. Does the design contract (gate `design_contract`) get fields for sizing, split minimum effect, counterpart types, screen plan? Not defined anywhere.
5. Who owns the unowned incident rows (G15/G16 world defects) after the pack redesigns (#301, #302)?
6. HL-J-02: whether the "luck removed" label needs an erratum (Chenyu, Housing paper).

## 5. Conflicts between sources

- #271 issue text and the taxonomy cluster quote bootstrap coverage 91/92/95 (and the cluster record 89/93/94); the author corrected to 89/93/94 in his comment. Use 89/93/94.
- Cluster G19 says "contracts do not record the arithmetic and families do not call it". Partly outdated: Housing v15 on main records a sizing record through a vendored copy (E9). The statement "no family writes the record at freeze" in #273's comment predates or ignores that.
- Cluster G12 statement "contract has no declared baseline-artifact input": the deferred leaf with `deferred_artifact` exists (E17); what is missing is a family using it and a ruling (E23), not a new kernel input. Landing a kernel field is not needed to adopt the X_own split. [read]
- Cluster G15/G16 claims of absent screens and control ladders: partly outdated; Housing's screen (E32) and Gate 3 (E33) exist. What is missing is per-case recording and uptake.
- Board status `ruled_awaiting_impl` for #290.a-e versus the #290 text (proposal): the text governs.
- Cluster G15 existing_work says "aeread.design.screen_plan (PR#288)": true only on the PR (E4).
- Board lists #286.b? No: board has no #286 item; cluster G19 includes #286.b. Recorded here, not resolved.
- Board `Lane` for PR #288 is "family"; E7 confirms the PR touches no kernel.

## 6. Not verified

#288 test results (46 tests, simulated coverage figures) not re-run; the PR is not on main and its tests need its branch. No provider calls. Incident rows on non-PR branches are lower confidence. PR #256 state not read.
