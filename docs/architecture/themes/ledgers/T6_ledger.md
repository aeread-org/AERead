# T6 Case construct validity: evidence ledger

**Evidence ledger for [T6](../T6_case_construct_validity.md).** Line references are at main 1e2ae367 unless a row says otherwise.

Snapshot: `origin/main` 1e2ae367 , issues and PRs fetched 2026-10-21. Cluster ids (G01..G36) refer to the root-cause clustering summarised in the [themes README](../README.md). Labels: [read] source read; [run] reproduced; [row] taken from an incident row or issue text, not re-checked. No [run] claims: nothing here needed a probe.

## 1. Claim ledger

| # | Claim | Source | Label |
|---|---|---|---|
| 1 | GovSim `observe()` now serves `sustainability_threshold` only when the declared arm (`inject_universalization`) asks for it; before, it was served always. | `src/aeread_families/govsim/environment.py:570-590` | read |
| 2 | Every govsim corpus case declares `inject_universalization: False`; campaign v4 is the corrected baseline and v1/v3 measured the intervention arm. | `govsim/cases.py:98`, `govsim/campaign.py:90-100,163` | read |
| 3 | PR #159 (the fix) merged 2026-09-10. #91 stays open for the deliberating arm and Tier 1 register. Board "Blocked by: PR#159 merge" is stale. | `gh pr view 159`; #91 thread | read |
| 4 | The three published GovSim panels all show survival 12/12 x3 (saturated); paper reports survival below 54%. | #91 comment (Chenyu) | row |
| 5 | GovSim live runs declare `reasoning_low_v1` (effort low, no token budget). | `govsim/live.py:453` | read |
| 6 | One call per condition: reasoning cap or effort low gives 13 reasoning tokens, no reasoning block gives 259 (GLM 5.3 Flash). Not re-run. | `docs/operations/incident_log.md:509` (R-D-01) | row |
| 7 | Repo decision: reasoning is a declared, versioned condition; every cell binds a `reasoning_condition_id`. | `docs/research/reasoning_condition_and_diagnostics.md:5,17` | read |
| 8 | DeepSeek V4 Flash at declared low effort writes 2,600-12,000 reasoning tokens a call, 6 of 12 gate calls end `length`; GLM writes 35-530. | `incident_log.md:647` (HL-O-17) | row |
| 9 | DC-D-08: developer interface 2 rejects a walk that carries a message (`malformed_datacenter_stack_action`); interface 3 accepts it. Every sealed case is interface 2; interface 3 is opt-in via `construct_controls.developer_interface`. The interface-3 pilot (48 cells) and a second confirmatory (72 cells, 5 reasoned walks accepted as valid) have already run on new identities. | `datacenter_development/stack_environment.py:118-122,129-130,758-764,789`; `docs/families/datacenter/qc.md:436-474` | read |
| 10 | Datacenter already has an opt-in construct guard: `validate_payload` refuses a case with `construct_controls` unless the reference strictly dominates the outside option by a margin and prices are two-sided; a test shows it kills the sealed dominated case. | `stack_environment.py:133-150`; `docs/families/datacenter/qc.md:128-140`; `tests/test_datacenter_stack.py:630` | read |
| 11 | The Datacenter QC profile records `construct_validity=partial` (was `failed` at 2026-09-19 audit); "one repaired case is not an admission screen". | `qc.md:8-30,140` | read |
| 12 | DC-D-03: the adoption primary leaf's `required_behavior` is "copy each complete written counter package exactly and sign its accepted offer id". | `datacenter_development/adoption_measurement.py:93-110` | read |
| 13 | P-D-17: `check_award` (zero money, zero days, one action) calls `evaluate_award`, which reads `private_terms.quality.verified_yield_rate`, i.e. the hidden yield, not the evidence the buyer holds. | `procurement_allocation/environment.py:1509-1534`, `:581`, `:653-657` | read |
| 14 | Procurement prompts say `check_award` "projects only from your available evidence" (continuous) / "costs nothing and takes no days" (v3). | `continuous_execution.py:44`; `pay_or_test_v3_prompt.py:62` | read |
| 15 | P-D-10 (supplier ids and names name the hidden defect), P-D-11 (offers print true on_time_probability), P-D-14. Not re-read in this pass. | incident rows | row |
| 16 | P-D-29 brief v3.1 exists only on branch `codex/procurement-v3-brief-v31` (acd0c706), not on main. | `git ls-remote origin` | read |
| 17 | Refund V2.5 code (payment leaf, null-method verifier, RV25 leaves) is not on main: `src/aeread_families/refund` has only V1/V2.1 files; `payment_binding` has no hit in `src`. | directory listing; grep | read |
| 18 | PR #269 is the Refund V2.5 publish PR (draft, mergeStateStatus DIRTY), not a V2.6 fix. Board row for #290 says "Blocked by: fix in PR #269". | `gh pr view 269`; the board export (working note, unpublished) | read |
| 19 | #290 is a design hand-over from Chenyu to Yuchen: six rows (RV25-D-03/04/05/06, RF-D-05, RF-T-01); "if you take only part, 1 and 5 matter most"; no comments. V2.6 note as `v2_6_redesign_note.md` (under `docs/families/refund/`) on branch `docs/refund-qc-profile` (e6e6d1da). | #290 body; `git show` | read |
| 20 | DC-D-23/25/26 and P-T-11 sit on non-main branches (PR #258 draft, others). `Game.signs` has no hit on main. | `gh pr view 258`; grep; rows say "only on non-PR branch(es)" | read |
| 21 | DC-D-04 partial fix: two-sided bands in `full_stack_amendment_002`; walk-away and adopt-every-counter scored controls merged in #193. | `qc.md`; `gh issue view 193` | read |
| 22 | #116 (econagent primary is an accounting-integrity flag, `direction: none`) is board Theme T6, but the taxonomy puts it in G12, theme T5. | the board export (working note, unpublished); the clustering (working note, unpublished) G12 | read |
| 23 | #303 / TB-D-10: FC10 baseline 0.307 vs paper 0.266, Stage 0 gate fails, gate not widened, rule not refitted; the paper does not define the FC policy. Board: "new since taxonomy snapshot; confirm theme". | #303 body; `incident_log.md:822` | read |
| 24 | the theme assignment note (working note, unpublished) defines T6 as: case-writing lacks a construct checklist (information-flow table, each leaf must separate known bad strategies); each case redesigned itself and ships under a new identity; not a runner bug. | the theme assignment note (working note, unpublished), T6 row | read |
| 26 | `benchmark_qc.md` Gate 0 is test-enforced (`tests/test_benchmark_qc_profiles.py`); Gate 2 requires a visibility audit and stops on hidden-state leak; Gate 3 requires controls, a pre-declared sensitivity rule and shortcut tests; campaign gates `design_contract`/`provider_free_validation` consume Gate 3. | `docs/operations/benchmark_qc.md:76-108,293-300,319-350,440-452` | read |
| 27 | GovSim with `inject_universalization=True` serves the threshold by design; a hidden-state perturbation test must be arm-conditional. | `govsim/environment.py:570-590` | read |
| 28 | econagent budget-identity leaf has `direction="none"`; a violation is an adapter defect, not policy quality. | `econagent_v1/measurement.py:97-99,148` | read |
| 29 | RF-D-02: one compliance bit folds skipped question, rejected request and format mismatch. P-T-11: action counts built without reading status (branch only). | incident records (working note, unpublished) | row |
| 25 | Every fix named in G05/G13/G14 for a published case is "new identity; published bundles not edited". | the clustering (working note, unpublished), existing work | row |

## 2. Members

Clusters (priority from the clustering): G05 P1 (7), G13 P2 (8), G14 P2 (5), G18 P2 (2).

| Member | What | State | Owner | True at 1e2ae367? |
|---|---|---|---|---|
| DC-D-08 | walk with message parsed as malformed (interface 2) | row says ruled_awaiting_impl; fixed on interface 3 and run | datacenter (not named in row) | Sealed yes; interface-3 pilot and confirmatory already run (claim 9) |
| DC-D-23 | scorer grades sign/unit convention never stated | open | datacenter | Not on main (PR #258 branch) |
| DC-D-25 | counterpart states price it will not sign at | open | datacenter | Not on main |
| DC-D-26 | menu shows rounded prices, signs at unrounded | partly_fixed | datacenter | Fix in menu campaign, not on main |
| RF-D-03 | correct denial with method null fails | blocked_on_ruling | Refund (Yuchen) | V2.5 not on main (claim 17) |
| P-D-29 | v3 brief disagrees with observation | partly_fixed | procurement | Fix on branch only (claim 16) |
| P-D-19 | counters cannot succeed, prompt silent | open | procurement | Row says P-D-22 closes it; P-D-22 open; cross-ref wrong |
| DC-D-03 | adoption leaf rewards copying | open, "by design" | datacenter | Yes (claim 12) |
| DC-D-04 | careless bidder vs careful negotiator | partly_fixed | datacenter | Yes; sealed 001 keeps one-sided bands |
| #290.b/.c/.e, RF-D-05, RF-D-02 | Refund leaves that do not discriminate | ruled_awaiting_impl / open | Yuchen | V2.5 not on main |
| P-T-11 | action counts include refused actions | open | procurement | Not on main |
| P-D-10, P-D-11, P-D-14, P-D-17 | hidden state in ids, offers, check_award | open | procurement | P-D-17 yes (claim 13); others [row] |
| #91.a | GovSim threshold leaked | fixed_pending_close | Chenyu | Fixed (claims 1-3) |
| #91, HL-O-17 | reasoning condition not equivalent | partly_fixed / open | Chenyu (#91) | Yes (claims 5-8) |

Board items with Theme T6 (4): #303 (Triage; confirm theme), #290 (In review; blocked-by text wrong), #116 (Needs decision, Chenyu; taxonomy says T5), #91 (Backlog). Related, other themes: G15, G16 (rows DC-D-02/28/30/33/35/36/42, P-D-01/03/09/12/13/16/20/22/27, RF-D-01/04, #290.a/.d) are world informativeness and control ladders, T5. G26 (RF-D-06, #279) is T5/T4.

## 3. Rulings in force

- [owner] #290: Chenyu hands V2.6 to Yuchen as a design hand-over; V2.5 is not changed; pick which rows to take (#290 body). It is a hand-over, not a ruling on each row.
- [owner] #91: keep open until the deliberating arm runs (#91 comment).
- [merged] Reasoning is a declared, versioned condition (`reasoning_condition_and_diagnostics.md:5`).
- [merged] Datacenter `construct_controls` guard and scored controls (#193) for new cases; sealed 001 unchanged.
- [record] Incident-log rule: published bundles are not edited; a fix to a case's rules is a new identity.
- No [owner] ruling exists on a cross-family construct checklist or admission gate.

## 4. Open questions

1. Is a mandatory checklist with an admission gate adopted, and who rules per case (theme ruling).
2. RF-D-03: is null a valid denial method (Yuchen or Chenyu).
3. #290: which rows Yuchen takes into V2.6.
4. DC-D-23: state the sign/unit convention or grade equivalents (datacenter owner).
5. P-D-17: new environment identity for an opt-in check (procurement owner).
6. #91 deliberating arm: paid run needs Chenyu's authorization.
7. Theme placement of #116 (T5 or T6) and #303 (family reproduction fidelity or T6).

## 5. Conflicts between sources

- Board #290 "fix in PR #269" vs PR #269 being the V2.5 publish PR (claim 18).
- Board #91 "Blocked by PR#159 merge" vs #159 merged 2026-09-10 (claim 3).
- Board #116 Theme T6 vs taxonomy G12 / T5 (claim 22).
- Row P-D-19 says P-D-22 closes it; P-D-22 is open, and is a headroom row (G16).
- Row DC-D-08 status ruled_awaiting_impl is stale: interface 3 exists and the pilot and second confirmatory ran on it (claim 9); old interface-2 bundles keep their definition; what remains is a regression check and the row update.
- The v1 ledger said the repo had only guidance; `benchmark_qc.md` already has gates and one test-enforced entry (claim 26).
