# T6: Case construct validity

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5 and is decided in [issue #321](https://github.com/aeread-org/AERead/issues/321); a ruling is recorded here with its date and source.

**Summary.** Several published cases score something other than what their claim says: GovSim served the intervention arm as baseline, Procurement's `check_award` reads the hidden yield, a Datacenter leaf rewards copying the counterpart, a Refund leaf scores 1.0 while money does not move. Each was found after the run, by reading a result, because no step when a case is written asks what each seat is shown against what is graded. Direction: `docs/operations/benchmark_qc.md` already requires a visibility audit (Gate 2) and construct controls (Gate 3) but leaves the evidence to hand-written prose; this theme turns that evidence into one construct checklist with a provider-free test per case, so the existing gate stop conditions have something to refuse on, and every redesign ships under a new identity. Ruling requested: does a missing or failing checklist stop the existing `design_contract` and `provider_free_validation` gates for new and redesigned cases, and who rules per case.

Evidence labels: [read] source at `1e2ae367`, [row] incident row or issue text not re-checked. Detail and ledger in the [ledger](ledgers/T6_ledger.md).

## 1. Problem and root cause

Root cause: facts that define the measured construct (what a seat sees, which units and signs the grader expects, what a leaf can tell apart, what reasoning a model actually does) live in separate places (prompt, schema, parser, grader, counterpart, tool) and no check ties them together. Cases are authored from convenient checkable quantities, so each defect is found one at a time after a run.

| Symptom | Where it shows | Evidence |
|---|---|---|
| Stated rules disagree with what is enforced | DC-D-08 (walk with a reason is malformed), DC-D-23 (sign/unit never stated), DC-D-25/26 (stated price refused), RF-D-03 (null denial method), P-D-29, P-D-19 (G05) | DC-D-08: `stack_environment.py:758-764` rejects it under interface 2, accepts under 3 [read]; others [row] |
| Observations or tools expose hidden state | P-D-17 `check_award`; P-D-10 ids and names; P-D-11, P-D-14 offers; #91.a GovSim threshold (G14) | `procurement_allocation/environment.py:1509-1534`, `:653-657` [read]; `govsim/environment.py:570-590` [read]; rest [row] |
| Score leaves cannot separate known bad strategies | DC-D-03, DC-D-04, #290.b/.c/.e, RF-D-05 (G13) | `adoption_measurement.py:93-110` copy is the required behavior [read]; Refund [row] |
| One score bit folds different failures; counts include actions that did not execute | RF-D-02 (skipped question, rejected request and format mismatch share one 0), P-T-11 (refused actions counted as the type attempted; branch only) | incident records (working note, unpublished) rows RF-D-02, P-T-11 [row] |
| Same declared effort is not the same reasoning | #91 (13 reasoning tokens under `reasoning_low_v1`), HL-O-17 (G18) | `govsim/live.py:453` [read]; token counts [row] |

What is already true: the same author-side guard exists once, for one family. Datacenter's opt-in `construct_controls` refuses a case whose reference does not dominate the outside option, and a test shows it kills the sealed case (`stack_environment.py:133-150`; `tests/test_datacenter_stack.py:630`) [read]. Its QC profile still reads `construct_validity=partial`: "one repaired case is not an admission screen" (`docs/families/datacenter/qc.md:140`) [read]. So the pattern works and is local.

Published consequence (from the rows): scored-malformed reasoned walks (DC-D-08, 6 of 21 and 6 of 12 cells), refused-at-stated-price moves (DC-D-25, 4 of 341), GovSim panels that measured the intervention arm and a non-deliberating model [row].

## 2. Direction

What exists today, so the gap is stated exactly: `docs/operations/benchmark_qc.md` Gate 0 is test-enforced (`tests/test_benchmark_qc_profiles.py`: a trusted family needs a profile or a dated exemption); Gate 2 requires a visibility audit and stops when hidden state leaks (`:293-300`); Gate 3 requires declared controls, a sensitivity rule fixed before results, and shortcut tests, and stops when stronger and weaker policies are indistinguishable (`:319-350`); the campaign gates `design_contract` and `provider_free_validation` consume Gate 3 (`:440-452`) [read]. What is missing is a per-case, machine-run form of that evidence: the audit and controls are prose in each family's QC profile, and the Datacenter profile still reads `construct_validity=partial` (`qc.md:140`). The checklist below is that evidence; the only new policy it adds is the ruling in section 5.

Replace case-by-case discovery with a construct checklist produced when a case is written or redesigned. Five parts; 1 to 4 are machine-checkable, 5 is a recorded statement.

1. **Information-flow table** in the case contract: for each seat and each arm, every field it is shown or can obtain, whether it is a function of hidden state, and the declared channel (always shown, arm-conditional disclosure, or costly action) and cost. Test (provider-free, family lane): with public state and randomness fixed, perturb hidden state and assert that observations and tool outputs change only through a declared channel for that arm and seat. A zero-cost disclosure is legal when the arm declares it: GovSim with `inject_universalization=True` shows the threshold by design (`govsim/environment.py:570-590`) [read]; the same field under the baseline arm is the defect. The test is run per arm, so it would have caught P-D-17, P-D-10 and #91.a without rejecting the intervention arm.
2. **Interface conformance test**: replay a literal copy of every figure the seat is shown and an exact stated price through parser, scorer and counterpart; expect accepted. One declared unit and sign per amount key. This is the check for DC-D-08/23/25/26 and RF-D-03.
3. **Known-bad-strategy table, by leaf purpose.** Each leaf declares its purpose, and the test follows it:
   - capability leaf (the claimed measure): lists at least one strategy it must separate from the reference (random legal, copy the counterpart, constant action, no-op) and a test that it loses. Datacenter's scored controls (#193) and the proposed Refund screens are the same idea.
   - integrity leaf (accounting identity, replay, legality): a mutation test that a deliberately corrupted record fails it; a weak but legal strategy must pass. econagent's budget identity is of this kind: a violation is an adapter defect, `direction="none"` (`econagent_v1/measurement.py:97-99,148`) [read].
   - diagnostic leaf: declares what it validates and carries no separation test; it is not a capability claim.
   A leaf with no declared purpose fails the checklist.
4. **Component separation and counting invariants**: a score bit that can fail for different causes (RF-D-02) is split into typed components or its causes are reported apart, with a test that each cause yields its own outcome; any action count is computed from executed status, with a test that a refused action does not count as the type attempted (P-T-11). These are not covered by "the bad strategy loses", since both defects survive that test.
5. **Reasoning condition**: the case records the declared reasoning condition and reports realized reasoning tokens next to the label, so a model gap is read as a gap in the measured quantity and not in effort.

Rule that goes with it: a case redesigned for any of these reasons ships under a new identity. Published bundles stay as defined and carry a construct-limits note, as incident-log practice already does [row]. This replaces fix-by-ticket on each family and the use of a post-run QC read as the first place a construct defect appears.

Alternatives not recommended:
- Prose gate only (today's Gate 2 and 3 text without a per-case test): the stop conditions exist but the evidence is hand-written, and the defects in section 1 passed it.
- A new separate admission policy beside `benchmark_qc.md`: it would duplicate Gates 2 and 3. The checklist attaches to them instead.
- A kernel-level construct gate: the checks need case-specific knowledge (which fields are hidden, which unit is expected). A kernel field can record the result later (T4 manifest); it cannot compute it.
- Retrofit all published cases: contradicts "published numbers stay as defined" and costs reruns for no new claim.

## 3. Scope

In scope: clusters G05, G13, G14, G18; rows listed in section 1; board items #290, #91, and the shared test helper.
Out of scope:
- G15, G16 (world informativeness, control ladders, headroom: DC-D-02/28/30/33/35/36/42, P-D-01/03/09/12/13/16/20/22/27, RF-D-01/04, #290.a/.d): T5.
- #116 (econagent declared primary is an accounting flag): clustered under G12, so T5. The board lists it under T6; to be confirmed by the owner.
- #303 (FC10 baseline does not reproduce the paper): a reproduction-fidelity gate; it concerns whether our baseline matches the paper's, not a case design. Kept with its family owner; placement to be confirmed.
- Call outcomes, billing, retries (T1); run controls and caps, including the larger declared cap for HL-O-17 (T2); identity granularity and pins (T3); manifest schema for recording gate results (T4).

## 4. Already decided

| Ruling | Label | Source |
|---|---|---|
| Refund V2.6 is Yuchen's design; V2.5 unchanged; if only part is taken, rows 1 and 5 first | [owner] hand-over | #290 body |
| #91 stays open until the deliberating arm runs | [owner] | #91 comment |
| Reasoning is a declared, versioned condition | [merged] | `docs/research/reasoning_condition_and_diagnostics.md:5` |
| Datacenter `construct_controls` and scored controls for new cases; sealed 001 unchanged | [merged] | `qc.md:128-140`; #193 |
| QC standard: visibility audit (Gate 2), construct controls and sensitivity rule (Gate 3), campaign gates consume Gate 3 | in main as `docs/operations/benchmark_qc.md:293-300,319-350,440-452` [read]; the ruling label was not checked | the file |
| GovSim threshold follows the declared arm; v4 is the baseline | [merged] | #159 (merged 2026-09-10); `govsim/campaign.py:90-100` |
| Published bundles are not edited; a changed rule is a new identity | [record] | incident log rows |

No owner ruling exists yet on a cross-family checklist.

## 5. Theme ruling requested

**Question: for every case written or redesigned from now on, does a missing or failing construct checklist stop the existing campaign gates `design_contract` and `provider_free_validation` (the gates that consume Gate 2 and 3)?**

Sub-questions:
- (a) Who rules a case's construct status: the family owner, or Chenyu.
- (b) Gate scope: new and redesigned identities only, or also a screen of cases already published.
- (c) Where the gate result is recorded: the family QC profile, or later a field in the T4 publication manifest.

| Option | Measured results | Frozen identities | Cost and work |
|---|---|---|---|
| A. Yes, all five parts stop those gates for new and redesigned cases | none change | none touched; each redesign gets a new identity | One shared test helper plus one table and tests per case; blocks new cases until written |
| B. Yes for parts 1-4 (machine-checkable); part 5 is reviewed by the case owner and recorded, not a stop | none change | none touched | Same helper; smaller gate, fewer false stops |
| C. No: the checklist is evidence offered to the existing gates, which stay prose | none change | none touched | Least work; defects keep being found after runs |
| D. A or B plus screen all published cases | published rows may be marked, reruns may follow | possible new identities for every family | Large; reruns need paid-call approval |

**Recommendation (not a ruling): B, applied to new and redesigned identities, with published cases marked in their construct-limits note and not rescreened.** Reason: parts 1-4 are what the incident rows show failing and each is a provider-free test; part 5 depends on provider behavior that no test can pin. For (a), the family owner rules and Chenyu rules only where owner and reviewer disagree or the case is contested. For (c), the family QC profile now; the manifest field when T4 lands. Consequence of choosing C instead: the open rows are fixed one by one and the next family repeats them.

## 6. Issue-level decisions that follow

| Question | Decider | Blocks | Issue |
|---|---|---|---|
| RF-D-03: is a null method a valid denial method | Yuchen, Chenyu if contested | Refund V2.6 verifier; 48 of 49 terms-mismatch cells [row] | row only, no issue |
| Which #290 rows enter V2.6; board shows "fix in PR #269" but #269 is the V2.5 publish PR (draft, dirty) | Yuchen | V2.6 start | #290 |
| #91 deliberating arm: authorize the paid run | Chenyu | closing #91; the GovSim claim "survival below 54%" | #91 |
| DC-D-23: state the sign and unit convention, or grade equivalents | Datacenter owner | next datacenter campaign identity | row only |
| DC-D-08: fixed on new identities and run: interface-3 pilot and second confirmatory (72 cells, 5 reasoned walks accepted) (`qc.md:436-474`) [read]; sealed interface-2 bundles keep their definition. Left: a regression check that a new case cannot select interface 2, and update the row status | Datacenter owner | nothing blocked; closes the row | row only |
| P-D-17 and P-D-10/11: opt-in `check_award` control and randomized supplier codes in a new environment identity (`environment.py` is hash-pinned [row]) | Procurement owner | next procurement pack | row only |
| P-D-29: rerun on confirmatory worlds under brief v3.1 as a new identity | Procurement owner | using v3.1 | row only |
| #116 and #303 theme placement | Chenyu | board and charter scope | #116, #303 |
| Board hygiene: #91 "Blocked by PR#159" is stale (merged) | Zeyu | board accuracy | #91 |

## 7. Delivery

1. Rule section 5 (Chenyu). Starts now.
2. Write the shared test helper: per-arm information-flow perturbation, literal-copy replay, per-purpose leaf runner (separation, integrity mutation), counting and component checks. Zeyu, family lane (tooling), depends on 1 for scope. Do not touch `src/aeread/shared_runner/**`; the kernel queue (#291, #292, #293, #248) is unaffected.
3. Pilot on Procurement `check_award` and one Datacenter case, where the defects and the existing `construct_controls` precedent are. Family owners; depends on 2.
4. Refund V2.6 checklist tables are written into the redesign Yuchen is already asked to make; depends on #290 and RF-D-03.
5. GovSim deliberating arm and realized-token report: Chenyu authorizes the run, Zeyu runs; depends on a paid-call approval.
6. Reference the checklist from `benchmark_qc.md` Gate 2 and 3 and the QC profile template, instead of a new document. Zeyu; after 2.

Can start now: step 2 design (no code until approved), RF-D-03 and #303 placement rulings.

## 8. Not verified

- Incident row numbers (cells, dollars, token counts) are taken from the rows; R-D-01 and HL-O-17 token counts were not re-run, and no provider was called.
- Rows DC-D-23/25/26, P-D-29, P-T-11, Refund V2.5 items sit on non-main branches or the draft PR #269; I confirmed only that they are absent from main, not their branch contents.
- The ruling status of `benchmark_qc.md` (owner approval) was not looked up; RF-D-02 and P-T-11 are taken from their rows, the latter on a branch only.
- P-D-10/11/14 were not re-read in source; P-D-17 was.
- Row owners are blank for Datacenter and Procurement; I did not look up which person owns each.
- Whether other families (collusion, govsim beyond the threshold, housing) have the same defect classes was not audited.
- The V2.6 note on `docs/refund-qc-profile` was read only to its header.
