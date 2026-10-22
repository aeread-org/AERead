# T5: Statistical design

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5; a ruling is recorded here with its date and source.

**Summary.** Campaigns size, screen and interpret themselves: sizing, interval method, missingness bounds, A/A runs, screen sampling plans and control ladders are left to each campaign, so published intervals under-cover, splits are undersized, and admitted worlds can be repeats or saturated. PR #288 (owner: Chenyu) is the vehicle: it adds the shared `aeread.design` calculations and the SOP and QC rules that use them, in the family lane. This charter proposes to keep #288 as that vehicle, finish what it leaves open in three steps (merge, family adoption at the freeze, then contract fields), and keep the four G12 comparator problems as separate per-family rulings. The theme ruling asks Chenyu to confirm scope, vehicle and admission gates.

## 1. Problem and root cause

Root cause: statistical design is a convention in prose, not a declared and checked part of a campaign. The SOP says the confirmatory size comes from paired variance and a minimum effect, but nothing computes it, records it or rejects a freeze without it. Worlds are a parallel case: QC Gate 3 already requires controls and a beatability rule (`docs/operations/benchmark_qc.md:324-345` [read]) and Housing's pack screen already tests ceiling and headroom (`housing/price_pack_v2.py:165-180` [read]), but the requirement is not recorded per world or per case in the manifest, and Refund, procurement and data-center packs still shipped repeats, saturated or shortcut-solvable worlds.

| Symptom | Where it shows | Evidence |
|---|---|---|
| No shared sizing, no sealed record: Housing v14 ran 260 worlds where about 50 suffice for one pair and about 6,000 for another | #273, #272 | #273 body [row]; `aeread.design` absent on main `ls src/aeread` [run] |
| Calculation exists only on an unmerged PR, yet main already vendors it byte for byte (sha256 `6a3f0794...`) for the Housing v15 sizing record | #288, `tools/housing/` | `tools/housing/price_v15_sizing.py:1-30`, `sizing_159cba3c.py` [run] |
| Freeze cannot reject a missing record: gates are typed history records with status and order checks only | `confirmatory_freeze` | `shared_runner/run/campaign.py:32-41, 325-365`; no `sizing` in `run/*.py` [read][run] |
| Percentile world bootstrap covers 89/93/94% at 10/20/50 worlds; paired t covers 95% | #271 | #288 test per author comment [row]; `analysis/paired.py:175-216` returns bootstrap and t, no sign-flip [read] |
| Worst-case missingness bounds exist in the kernel but few analyses call them | #274 | `paired.py:191-216` [read]; #274 body [row] |
| Screens state no sampling plan: one seed cannot admit a world; at 10 seeds a 9-in-10 world is admitted 65% | #285 | #288 QC table [row] |
| Worlds that are repeats or carry no hidden-information value, although Gate 3 and some screens exist: Refund 120 cells are six cases, procurement seeds repeat, data-center client seat gains at most 19.4 | G15: RF-D-01, P-D-01, DC-D-02, DC-D-35 | incident records [row] |
| Controls listed by Gate 3 are not applied or recorded per case: Refund naive policy passes 38/180, pay_or_test within 1 to 5 dollars of best, micro-GRPO case has zero reward variance | G16: #290.a, P-D-22, #4.e | Gate 3 text [read]; records [row] |
| Scripted counterparts untested against live play: 248k head-to-head gap vs 17k against the firm script | G20: #275, #283 | records [row] |
| Four families' primary estimands need a comparator that one episode cannot carry, each for a different reason | G12: #100, #135.c, #135.e, #116 | `collusion/measurement.py:639-667`, `aucarena/measurement.py:750-768`, `negarena/measurement.py:585-598`, `econagent_v1/environment.py:118-130` [read] |

## 2. Direction

One design layer, in three tiers, so that sizing, screening and interval choice become declared and checked rather than recited.

1. **Library and rules (tier 1, #288, family lane).** `aeread.design` holds the calculations: sizing, reliability, screen plans, A/A check. The SOP and QC text defines when each is owed. Nothing under `shared_runner/` changes.
2. **Family adoption at the freeze (tier 2, family lane).** Each new freezing campaign writes the sizing record with `sizing_record` and calls `verify_sizing_record(record, frozen_worlds=...)` in its freeze test, as the #273 comment already asks. New panels record their screen plan in the manifest. Analyses call `analyze_paired_results()` (`paired.py`) with `score_support_by_world`, the per-world lowest and highest score declared before the freeze; without it the bounds are `None` and status is `unavailable_without_declared_outcome_support` (`paired.py:185-216` [read]). `missingness_difference_bounds` is a returned field, not a function. #288 already writes the reporting rule: compare missingness between arms, and bounds that include zero or reverse a claimed gap read "inconclusive" (#274 comment, `pr288.diff` Gate 5 item 6 [read]). Analyses also name the interval used. Housing v15 already holds a record built from a vendored copy; adoption replaces the copy by an import of `aeread.design` and keeps the record, with the digest check preserved, so no frozen identity changes.
3. **Contract fields (tier 3, kernel lane, later).** Once sizing, split minimum effect, counterpart types and screen plan have a settled shape, `design_contract` and `confirmatory_freeze` reject a campaign without them. This is schema and enforcement work and follows the owner's kernel landing order.

What it replaces: per-campaign scripts that restate the arithmetic, and the five-world floor for splits.

World admission and controls (G15, G16) are mostly adoption, coverage and verification of rules that exist, not new rules. Gate 3 already names the ladder (no-op or lower anchor, random, simple, informed, oracle diagnostic) and requires a beatability rule declared before model results; Housing's screen already admits worlds by ceiling and headroom. The difference this charter asks for, relative to current Gate 3, is only that the manifest records per case which controls ran, the per-world admission numbers and the headroom against current subjects, so a freeze can be checked against them. Whether to make that a mandatory record is an owner choice (section 6). #301 and #302 are the first two applications.

G12 is not one contract. Collusion needs an external baseline, AucArena compares seats inside one episode, NegArena needs a frozen opponent mapping, EconAgent's declared primary is a conformance check. The kernel already has `deferred` leaves with a named `deferred_artifact` (`schemas.py:350-356`), so no new kernel input is needed to adopt the #100 split; each family needs its own ruling.

Alternatives considered:
- A kernel-first design (contract fields before anything else): blocks sizing on the kernel landing order; not recommended as the first step.
- One family-wide estimand contract covering all G12 families: contradicted by the four mechanisms above; not recommended.
- Leave design to each campaign with the SOP as the only enforcement: this is the current state and produced the symptoms in section 1.

## 3. Scope

In scope: clusters G19 (14 members), G15 (13), G16 (9), G20 (5), and G12 (5, as four separate family decisions). Board items #94, #100, #4, #270-#278, #281-#285, #288, #301, #302. Members and states are listed in the [ledger](ledgers/T5_ledger.md) section 2.

Out of scope:
- Call-outcome typing, billing, retries inside an attempt, terminal writers: T1.
- Replay identity and frozen-identity hashing of scripted styles (DC-D-32 is a style identity change): T3 for the identity mechanism; the invariance test stays here.
- Campaign launch, spend limits and balance preflight (#286.a, #292, #293): kernel owner and T2.
- Judge and rater verdict artifacts: not in this theme.
- Paper wording for specific results (HL-J-02 erratum): Housing paper owner.

## 4. Already decided

| Decision | Label | Source |
|---|---|---|
| Kernel landing order #246, #291, #292, #293; #248 after part-1 repairs | [owner] | [rulings register](ledgers/rulings_register.md) D-11 |
| Scoring leaves are `finalize_time` or `deferred`; primary and admission leaves finalize-time | [merged] | `schemas.py:337, 350-356`; `measurement.py:405-447` |
| Confirmatory size from paired cluster variance, declared minimum effect, power, attrition; five units per stratum is a floor | [merged] | `docs/operations/experiment_campaign_sop.md`, QC Gate 5 |
| Reporting rules: distributions, run-to-run variance, intervals with the case as resampling unit, judge agreement | [merged] | `CLAUDE.md:67-80` |
| AucArena: legacy degenerate case stays QC-only; add a new frozen-field case id | [record] | Zeyu's "approved repair program" comment of 2026-09-08 in #135 states it as an owner decision; no Chenyu comment in the thread restates it (his 2026-09-10 comments rule only the landing order and #152) [read] |
| #288 SOP and QC wording | [record] until merged | PR #288 |

Not rulings: #290 (Refund V2.6) is Chenyu's design hand-over to Yuchen with "Change proposed" rows and permits taking only part; the board marks it `ruled_awaiting_impl`, which the issue text does not support [read]. It is an owner proposal, listed here only so it is not read as settled.

## 5. Theme ruling requested

**Question.** Confirm that statistical design is one shared layer with PR #288 as its vehicle, and decide where admission is enforced. Three independent sub-questions follow.

Sub-questions, each with its own options because the answers are independent:

**(a) Scope.**

| Option | Consequence |
|---|---|
| A1. G19, G15, G16, G20 under one layer; G12 as four per-family rulings | One owner review; G12 rulings proceed on their own timing |
| A2. A1 plus one family-wide estimand contract for G12 | One ruling, but contradicted by the four different mechanisms (section 2); risks a wrong contract for three families |
| A3. G19 only now; G15, G16, G20 stay per-family | Smallest review; admission and control gaps keep recurring ticket by ticket |

Recommendation: A1.

**(b) Vehicle.**

| Option | Consequence |
|---|---|
| B1. #288 as one PR: library plus SOP and QC text | Fewest steps; Housing's vendored copy can be replaced once; review covers both |
| B2. Split into library and rules | Two reviews; the library can land and be imported before the wording is settled; costs a rebase of a conflicting PR |

Recommendation: B1; both stay family lane, so neither depends on the kernel order. After merge, Housing replaces its vendored copy by an import and keeps the digest check.

**(c) Admission gate.** What does the freeze reject?

| Option | What happens | Measured results | Frozen identities | Cost and work |
|---|---|---|---|---|
| C1. Library and rules only (#288 as is) | No enforcement beyond SOP text | Under-sized and undeclared designs can still freeze | None change | Lowest; leaves the symptoms to discipline |
| C2. C1 plus family freeze tests (tier 2) | Each new freezing campaign calls `verify_sizing_record(record, frozen_worlds=...)`, which recomputes the record from its inputs and rejects a pack smaller than it needs; it does not look at screens (`design/sizing.py` `verify_sizing_record` [read]). Screen plan is a manifest declaration; the family test must also reject a manifest without one and bind the recorded screen result to the frozen pack and the declared acceptance rule | New campaigns are sized; screens are declared and checked by the family test, not by the library | None change; sealed manifests are not edited | Family lane, one test per campaign; the screen binding check is new test code per family; can start after #288 merges |
| C3. C2 plus kernel contract fields (tier 3) | `confirmatory_freeze` rejects missing design fields | Same as C2, now uniform | Changes the contract schema and the digest of future manifests; existing frozen packs need a declared version | Kernel lane; must follow #291, #292, #293 and needs non-author approval |

**Recommendation (recommendation, not a ruling): C2 now, C3 later.** C2 fixes the next campaign without touching the kernel, and the owner's own #273 comment already names the freeze test for sizing. Without the screen binding check, C2 promises sizing verification and screen declaration only, not screen enforcement. Decide C3 after one campaign has used the record, so the contract field is shaped by a real freeze.

## 6. Issue-level decisions that follow

| Question | Decider | Blocks | Issue exists |
|---|---|---|---|
| Mark #288 ready and resolve its conflict; confirm module path `aeread.design` | Chenyu | #273, #276, #285, #282, #271, #272, #274, #275, #277, #286.b close-out | #288 |
| Kernel sign-flip test beside the interval in `paired.py`; analysis report names the method used | Chenyu (kernel lane) | #271 | #271 |
| Contract fields: sizing record, split minimum effect, counterpart types, screen plan, exploratory type | Chenyu | tier 3; #272, #275, #277, #285 | partly (blocked-by notes on #272, #275, #277) |
| Pre-freeze live A/A arm in a `variance_pilot` on one family. Housing v15 already reports a post-freeze A/A (Luna vs its twin, -5.0 [-18.8, 8.9], 520 twin cells, `price_confirmatory_v15_results.md:17,31-34` [read]); reuse its analysis shape, but it ran after the freeze and cannot show the pipeline passes before spend | Chenyu | #282 | #282 |
| Collusion and econevals: adopt `X_own` primary and `X_vs_baseline` deferred leaf, or another form | Chenyu | #100.a, #100.b; every collusion receipt is excluded until ruled | #100 |
| NegArena: which frozen opponent policy each live profile is compared to | Chenyu | #135.e | #135 |
| EconAgent: conformance-only, add a capability leaf, or keep (reporter leans conformance-only) | Chenyu | #116 | #116 |
| AucArena: confirm the QC-only disposition and the successor frozen-field panel (currently a [record]) | Chenyu to confirm; Zeyu implements | #135.c | #135 |
| Make the Gate 3 control record mandatory per case in the manifest, with a headroom check against current subjects, including the cheap tier (Gate 3 already lists the controls). Refund V2.6 changes in #290 are a proposal to Yuchen, not a ruling | Chenyu | G16; #4.e quoting rule; #290 | none for the shared rule; #290 for Refund |
| Next data-center and Housing packs: exact reference and shortcut screens, partial pass-through | Chenyu | #301, #302 | #301, #302 |
| Reference panel and control chart cadence (deferred research item; see section 7) | Chenyu | #281 | #281 |
| Scripted-vs-live audit on data-center; invariance and stream tests | Chenyu | #283, #284, #278 | those issues |
| World-level admission defects without issues (G15 rows) | Chenyu to assign | pack redesigns | rows only, no issue |
| HL-J-02 erratum for the "luck removed" label | Chenyu | Housing paper | row only |

## 7. Delivery

| Step | Owner | Lane | Depends on | Can start now |
|---|---|---|---|---|
| 1. Resolve #288 conflict, undraft when the author's open-PR limit allows, review, merge | Chenyu, with Zeyu reviewing | family | none | yes |
| 2. Replace Housing's vendored copy by an import; keep the digest check | Housing owner | family | 1 | after 1 |
| 3. Next freezing campaign writes the sizing record and calls `verify_sizing_record` in its freeze test | campaign owner | family | 1 | after 1 |
| 4. New panel manifests record the screen plan; screen against shortcuts in #301 and #302 packs | pack owners | family | 1 | after 1 |
| 5. Analyses call `analyze_paired_results()` with pre-declared `score_support_by_world`, report missingness per arm and name the interval; sign-flip test in `paired.py`. Done when an analysis output carries non-null `missingness_difference_bounds` | Chenyu (kernel lane for sign-flip) | family; kernel | 1, landing order for kernel part | family part after 1 |
| 6. Pre-freeze A/A arm in a variance pilot on one family, reusing the Housing v15 A/A analysis shape; rehearsal of sealed analysis (#270, #282). Done when a pilot reports the gap, interval and whether the claim rule fires before `confirmatory_freeze` | Chenyu | family | 1 | after 1 |
| 7. Per-family G12 rulings (#100, #116, #135.e) and adoption | Chenyu rules; Zeyu implements | family | rulings | rulings can be given now |
| 8. Reference panel and control chart (#281): choose per-family panel and control, SOP rule, chart with stated false-alarm rate. Pre-award holdout run (#94): a research run waiting on Chenyu's review, deferred in this round because it needs no design layer; listed so it is not lost | Chenyu | SOP; family | none for #94; 1 for #281 | #94 yes, after Chenyu's review; #281 deferred |
| 9. Contract fields in `design_contract` and `confirmatory_freeze` | Chenyu / Zeyu | kernel | 3 or 4 done once; #291, #292, #293 landed | no |

## 8. Not verified

- #288's tests and simulated figures (46 tests, 0.80 detection, 89/93/94% coverage) were read, not run; they need the PR branch.
- Sizing record of Housing v15 was read and its module digest checked, but not recomputed from receipts.
- The owner ruling on AucArena was read from the #135 thread, not matched to a comment id.
- G15, G16 and G20 incident rows are taken from the records; several come from non-PR branches and are lower confidence.
- PR #256 (Housing v14 analysis) was not read.
- Live #288 draft, conflict, CI and review state was last read 2026-10-22 and may have moved.
- Whether the Housing v15 A/A analysis can be generalised to other families was not checked.
- No paid or provider calls were made.
