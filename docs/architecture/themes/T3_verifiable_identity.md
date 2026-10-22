# T3: Verifiable identity

**Status: proposed.** Not yet reviewed by a maintainer. The theme ruling requested is in section 5 and is decided in [issue #318](https://github.com/aeread-org/AERead/issues/318); a ruling is recorded here with its date and source.

**Summary.** A receipt is only as verifiable as the identity it binds. Today each family author chooses what to pin, and chooses whole files: too coarse (one kernel or family edit moves every plan id and orphans old bundles) and too few (scorer, reference and seat roles that decide the headline are not declared, so replay certifies a number nobody reports). Verification itself is optional: nothing in publication requires `verify-replay`, and no test drives every trusted family through finalize, replay and audit. The direction is one identity contract: the manifest declares every component that decides the score, each is pinned by its own digest, replay is a publication gate that reports coverage, and one conformance test replaces the per-family exemptions. The theme ruling requested, for new identities only, is at what granularity plan pins bind code, what a kernel pin is, and from when publication requires full-coverage replay (section 5).

Evidence labels: `[read]` source read, `[run]` reproduced, `[row]` taken from an incident row or issue text. Source tree is `origin/main` 1e2ae367. Full ledger: [ledger](ledgers/T3_ledger.md), claim numbers C1-C37 below.

## 1. Problem and root cause

**Root cause.** Identity is a set of whole-file digests chosen family by family, not something derived from what decides the number. The kernel already separates kernel-owned pins (drift is allowed and reported) from family-owned pins (must match exactly), and audits receipts by their recorded pins. What it does not do is define what a manifest must declare, at what granularity a component is pinned, or require that anyone re-executes a bundle before it is published.

Two mismatches follow, and one omission:

- **Too coarse.** A family pin covers a whole source file, and some family pins embed kernel bytes. Any edit moves the plan id; family edits make old plans unbuildable.
- **Too few.** Components that decide the score (scorer, oracle, reference, predicate, seat map) are missing from the manifest or sit outside any pin.
- **Verification is optional.** Replay is computed by the producing run and copied; the independent command exists but is not a gate, and its coverage depends on whether a family shipped a setup callable.

| Symptom | Where it shows | Evidence |
|---|---|---|
| Every kernel commit touching `task/execution.py` gives every new Refund plan a new id; byte-regeneration of tables carrying `run_plan_sha256` fails | Refund pin; DC-T-20 | Whole-file digest of a 4,770-line file as `harness` and `runtime` pin, `refund/runner.py:1228-1245` [read] (C6); plan id hashes pins, `resolver.py:703-756` [read] (C1); DC-T-20 [row] |
| Old receipts still audit on a moved kernel, but only if the family's setup rebuilds the plan with recorded pins | Housing v15 (HL-T-11), pay-or-test v3 | `plan_with_recorded_pins`, `resolver.py:805-840`; `evaluation.py:1240, 1374` [read] (C3, C4); 0 of 3,520 v15 receipts verified before the family-side fix [row] (C12); fix 841c7584 [read] (C11) |
| A later family edit orphans earlier bundles; the bundle records `execution_source_sha256` but no source commit | TB-D-04 (3 occurrences in 2 days), #304 | family pins must match exactly, `resolver.py:826-834` [read]; TB-D-04 [row] (C9); #304 [read] (C20) |
| A family pin that embeds kernel bytes cannot be repaired by recorded-pin substitution; Housing v14 needed a rebuild from `git show 6aaf46bb` | HL-D-11 | `housing_feasible_zero_v1` = sha256(`runner.py` + kernel `task/evaluation.py`); commit 03b3fb63 [read] (C10) |
| One aggregate digest pins scorer and all references: any edit to any listed module moves all of them | Housing v15 | `price_seat0.py:44-49, 289-296` [read] (C14) |
| consent_ir leaves cite two implementations the manifest does not declare; they can be neither pinned nor omitted | #120 | resolver accepts `reference_provider_ids` (`resolver.py:381-388`) [read]; consent_ir declares none [read]; the two refusals [row] (C15, C16) |
| Procurement reference is not a declared component; decision loss (paper Table 5.3) is computed from an unpinned module | P-T-17, P-D-26 | no `reference_provider_ids` in `procurement_allocation/` [read]; 17 other families declare them (C17) |
| Headline outside the receipt (Housing v14) is fixed for v15 under a new scorer id; seat roles still live in a driver router and an unsealed `seat_calls.jsonl` | #289.a/.b, HL-D-09, HL-T-09 | `price_seat0.py` [read] (C18); `price_campaign.py:297, 824-832, 912` [read] (C19) |
| consent_ir returns `None` leaves and `invalid` validity for a well-formed input: silent exclusion, not a crash | #120, #144.b | Reproduced: both leaves `primary=None`, validity invalid, no exception [run] (C30); ratchet lists only consent_ir [read] (C31) |
| 18 trusted keys are exempt from the scoring-contract test with no owner or exit rule; #294 and #296 added two on 2026-10-21, #306 would add a third | #294, #296, #306 | `test_shared_runner_scoring_contract.py:3152-3190`, counted with `ast` [run] (C32, C33) |
| Certified replay passes `None` for the plan cell; EconAgent replay burns case-keyed session ids | #135.a, #156 | `evaluation.py:277` [read] (C26); mechanism [row] |
| R10 trajectory consistency is not enforced at replay; a deterministic mis-copy self-verifies | #122 | `evaluation.py:575-579`; `trajectory_outcome_paths` consumed only in `schemas.py` [read] (C27) |
| Nothing ties publication to `verify-replay`; datacenter bundles carry a producer-computed `replay_verified` flag; no datacenter or Refund setup callable | DC-T-01, #264.c, #289.d | `publication.py` and `publish_trajectories.py` do not import it [read] (C23); `adoption_campaign.py:488-499`, `adoption_publication.py:204` [read] (C24); setup callables only for TERMS-Bench, Housing, procurement v3 [read, by name] (C22) |
| A canary checkpoint written by hand passes the resume check | #171 | `adapter_campaign.py:168-192` [read] (C28) |

## 2. Direction

One identity contract, built once, replacing ticket-by-ticket repairs. Four parts. Each says what becomes declared, enforced or tested, and by which component.

**2.1 Declare every component that decides the score (manifest, kernel contract).**
A family manifest names, for each leaf, the scorer, oracle, reference providers, validity predicate, and (for multi-seat cases) the seat map. The resolver already requires pins for exactly the set named in `scoring` (`resolver.py:368-404`) and the receipt already requires a pin for each leaf's predicate, reference and scorer (`evaluation.py:68-90`) [read]. So the kernel change is small: families must declare what their leaves cite. Where a leaf cites an implementation the manifest omits, manifest validation refuses it at registration, not at first finalize. First adopters: consent_ir (#120), procurement pay-or-test (reference), Housing seat map.

**2.2 Pin each component by its own digest, and never pin kernel bytes inside a family pin (kernel contract plus family rule).**
- Family-owned components: one digest per declared component (its module closure), not one file per family and not one aggregate per case. The Housing v15 aggregate (`price_seat0.implementation_digest`) shows the pattern and its limit (C14).
- A family pin must not include kernel bytes (the HL-D-11 pattern). Kernel-owned pins stay as provenance with reported drift, which is what main already does.
- Source-commit recording already exists: `seal_publication_manifest(source_commit=...)` (`publication.py:452-475`), `source_commit_for_pins` (`provenance.py:96`) and `aeread source-commit` (`cli.py:30`) [read]; #161 closed 2026-10-01 [read, `gh issue view 161`]. What is missing is requiring it: every publisher must pass it, and the gate checks it against the recorded pins, so "replay this bundle" is one command.
- Existing sealed plans are not touched. A pin scheme marker lets the verifier read both.

**2.3 Verify-replay is a publication gate that reports coverage (kernel publication path, family setup factories).**
The bundle builder refuses to write a `replay_verified` claim unless `verify_bundle_replay` ran on that bundle and returned `verified` with coverage `every_published_episode`. Today `verified` is also true under coverage `receipts_found_under_run_root`, which is what a bundle without the trajectory grain gets: published receipts 2, found 1, `evidence_missing=0`, `verified=true` (`replay_verification.py:156-166`, `_published_episodes` empty) [read; the reviewer's in-memory probe agrees]. So a new bundle must carry a sealed episode inventory (the trajectory grain), and a run covering only part of it is reported as partial verification, never as `verified`. Every family ships a setup callable that rebuilds the plan from recorded pins. Reviewing #245 and landing #156 and #122 supply the sealed-input rule, the real plan cell and R10 at replay; #171 supplies the canary rule.

**2.4 One conformance test replaces the exemptions (kernel conftest gate).**
A parametrized test drives every trusted family through run (provider-free fixture), finalize, replay and audit. Each fixture declares its expected leaf statuses, primary and admission disposition, and the test fails on any difference, so an unexpected exclusion is caught while leaves the owner ruled unmeasured stay legal: GovSim comparatives without a baseline are `invalid_measurement` by the #141 ruling, and TermsBench value-axis leaves are `invalid_measurement` on a protocol violation while `protocol_compliance` stays the admission leaf [row, #141 owner comments 2026-09-10; GovSim policy comment at `test_shared_runner_scoring_contract.py:3194`]. It subsumes `KNOWN_UNMIGRATED_SCORERS` and `_NOT_YET_MIGRATED_TRUSTED_KEYS`. Until a family has its fixture, its exemption carries an owner, an issue and a date; adding a key without those fails the test.

**What identity does and does not do.** `plan_sha256` and `run_plan_id` hash the implementation pins (`resolver.py:703-756`); `design_plan_sha256` strips them (`resolver.py:725-747`) [read]. So a change to any pinned byte, kernel or family, moves the execution identity and never the design identity; this holds under every option. Option a2 narrows what is pinned (only declared components, no kernel bytes inside family pins), so an edit to code that decides nothing no longer moves a plan. A behaviour fix to a pinned component still creates a new execution identity by design, and old bundles stay replayable only through the recorded source commit and pins. It does not make fixes identity-neutral.

**Replaces.** The per-family hand-written recorded-pin setups (Housing v15 has two, pay-or-test v3 one); the aggregate digests; the exemption lists; the producer-computed `replay_verified` flag.

**Alternatives considered.**

| Alternative | Why not recommended |
|---|---|
| Keep whole-file pins; add tooling only (publisher commit, setup factories) | Fixes TB-D-04 and HL-T-11 operationally but leaves the headline outside any pin (#120, P-D-26) and unrelated edits still moving every plan id (aggregate and whole-file digests) |
| Replace file digests by a kernel contract version string | Cheaper identity, but a version is a claim and not a check; two different byte states can share a version. Kept as an option for kernel-owned pins only (sub-question b) |
| Re-pin old plans retroactively | Moves frozen identities and `evidence/**` must not be edited; rejected |
| Gate publication on the producer's own replay | That is the current state (C24); the producer's flag is not independent |

## 3. Scope

**In scope.** Clusters G02 (headline and seat roles inside the seal), G09 (replay and canary coverage), G10 (PlanCell, source commit), G11 (scorer calling convention, conformance). Issues and PRs: #120, #122, #141, #144, #171, #245, #289 (except .c), #304, #306, #156, #135.a, #39.a. Rows: TB-D-04, DC-T-20, DC-T-01, DC-T-22, HL-D-09, HL-T-09, HL-T-11, HL-D-11, HL-J-17, P-T-17, P-D-26.

**Out of scope.**

| Item | Destination |
|---|---|
| Call-outcome typing, retries inside an attempt, billing of provider calls, terminal writers (#248, #291, #135 D1 length state machine) | T1 |
| Paid gate-4 runs and the eleven external benchmarks without receipts (#39 title) | Owner decision on paid runs; not identity |
| Publication integrity of already published rows and QC display (cluster G24 and others) | T4 |
| One launch path for case drivers (#289 item 3) | T2 (G21) |
| Uniform recording of real subject clients (#289.c) | T1 (cluster G07; T1 design covers client recording and conformance) |
| Admission schemas (#289 items 5, 6) | T4 (G26) |
| Leaf validity (what a leaf measures) and comparators (G12, G13) | The themes that own G12 and G13 |
| Refund V2.5 compatibility audit (#264) | Yuchen |

## 4. Already decided

| Decision | Label | Link |
|---|---|---|
| Kernel landing order: #151, #149, #156, #150, then #135 D1, then #122 (tiered form: #151/#149/#117 parallel, then #156, then #150) | owner | #135 comments 5624145957, 5624791316 |
| Current kernel order: #246 (merged), #291, #292, #293; #248 after its part-1 repairs | owner | owner's order |
| Design identity excludes kernel implementation pins | merged | #149; `resolver.py:722-747` |
| Receipts audit by recorded kernel pins; family pins must match | merged | dfcd0c05 (2026-09-03); `resolver.py:805-840` |
| `scripted_seats` is inside design identity | owner | #135 comment 5624791316; #150 merged 2026-10-19 |
| Housing headline: focal-seat scorer in a new module under a new scorer id, `runner.py` untouched | merged | 716493d5, 0aad1313 |
| v14 rebuild by recomputing the bridge digest from the sealed kernel file | on behalf (written as "the coordinator's ruling"; no owner comment found) | 03b3fb63; incident log HL-D-11 |
| v15 replay by recorded pins on a moved kernel, family-side | merged (commit); no ruling needed | 841c7584 |
| #141: five-leaf GovSim policy with comparatives as `invalid_measurement`; TermsBench admission unconditional | owner | #141 thread; test comment at `test_shared_runner_scoring_contract.py:3194` |
| Exemptions are "deliberately named, not derived"; a new trusted key needs a fixture or an explicit widening | merged | `test_shared_runner_scoring_contract.py:3140-3151` |
| Receipt validation must not be weakened | record | #135.a |

## 5. Theme ruling requested

**Question.** For every identity frozen from now on, should plan identity bind implementation code per declared component, and should a published bundle count as verified only if `verify-replay` re-executed all of it? Every existing sealed identity stays as it is under every option below. The three sub-questions have independent answers, so each has its own options. Design identity is unaffected by all of them (see section 2, "What identity does and does not do").

**(a) Granularity of family-owned pins.**

| Option | Frozen identities | Measured results | Cost and work |
|---|---|---|---|
| a1. Whole-file pins; tooling only (publisher commit, setup factories, recorded-pin setups per family) | Unchanged | Unchanged; headline can still sit outside the pin set | Low kernel work. Each family hand-writes recorded-pin setups (Housing needed three commits). Any edit to a whole-file or aggregate pin moves the plan id (#304) |
| a2. Per-component pins for new identities, no kernel bytes inside a family pin, scheme marker so the verifier reads old and new (recommended) | Existing plans and bundles unchanged | No change to published numbers; future headlines are leaves inside pins | One kernel change (manifest declaration check, scheme marker); family adoption under new identities, one family at a time. A behaviour fix to a pinned component is still a new execution identity |
| a3. Re-pin existing plans to the new scheme | Moves every frozen id; `evidence/**` cannot be edited | Risks invalidating published receipts | Not viable |

**(b) Kernel-owned pins.**

| Option | Frozen identities | Measured results | Cost and work |
|---|---|---|---|
| b1. Keep the kernel file digest as provenance with reported drift, as today (recommended) | Unchanged | Unchanged | None; main already tolerates kernel drift (C3, C4) |
| b2. Name a kernel contract version in the plan instead | Existing plans unchanged | Unchanged | Needs a rule for what bumps the version. A version is a claim; weaker than a digest unless a test ties it to behaviour |

**(c) Publication gate.**

| Option | Frozen identities | Measured results | Cost and work |
|---|---|---|---|
| c1. No gate; `verify-replay` stays a command | Unchanged | Published `replay_verified` stays the producer's own flag | None. Keeps today's gap (C24) |
| c2. Gate from a date the owner sets: bundles published after it need `verify_bundle_replay` returning `verified` with `every_published_episode` coverage; legacy bundles shown as "not replayable, reason", never as verified (recommended) | Unchanged | None | Kernel publication-path change in the kernel lane after the owner's order; bundles need the sealed episode inventory; each family needs a setup callable before its next publication |
| c3. Gate all bundles including legacy | Unchanged ids, but many legacy bundles cannot be re-executed (no setup callables) | Would mark published results unverifiable | Not viable for legacy |

**Recommendation (a recommendation, not a ruling): a2, b1, c2** with the date for c2 set by the owner. Reason: main already tolerates kernel drift and refuses family drift (C3, C4), so the missing pieces are narrow and local: what a manifest must declare, how fine a family pin is, and whether publication needs a re-execution. This closes #120 (undeclared references) and the orphaning part of TB-D-04 as classes, and gives P-D-26 its reference declaration, without touching a frozen byte. It does not make a behaviour fix identity-neutral (#304 stays a new identity for the fixed component), and it does not by itself compute the decision-loss leaf (decision 9).

## 6. Issue-level decisions that follow

| # | Question | Decider | Blocks | Issue |
|---|---|---|---|---|
| 1 | Landing of #156 (draft, head b4ede44b): rebase on current main (after #150) and approve? | Chenyu (order); non-author approval needed | #122, EconAgent finalize (#135.a), the PlanCell part of the gate | Exists (#156) |
| 2 | #122: json_pointer module and R10 at replay; implementation after #156 (plan on `zeyu/issue-122-plan` @ 3b3d1a4f) | Zeyu implements; Chenyu orders | Replay of trajectory-scoped leaves | Exists (#122) |
| 3 | #245: two reproduced residuals; where does it sit in the order? | Chenyu | The coverage report of the gate | Exists (#245) |
| 4 | #171: is the run tree trusted, or must a canary be a re-probe or provider-reported evidence at publish? | Chenyu | Publication gate on canaries | Exists (#171) |
| 5 | #289: which of items 1, 2, 4 go to the kernel lane and which to the family lane; does Part A carry the "as it is" paragraph? | Zeyu (asked), Chenyu | Seat map in plan, headline leaf rule, mandatory setup | Exists (#289) |
| 6 | #120: migrate consent_ir scorer and declare the two references; drop the ratchet entry | Zeyu or family-lane implementer; no kernel change | First adopter of 2.1; shrinks the exemption list | Exists (#120) |
| 7 | Exit rule for `_NOT_YET_MIGRATED_TRUSTED_KEYS` (18 keys): owner, issue and date per key, or a policy that new registry rows need their fixture | Chenyu (policy), Zeyu | Whether #306 and later registry PRs may add keys | New; no issue yet |
| 8 | Mechanism exists (#161, closed). Which publishers must pass `source_commit` from now on, how the gate verifies it against the recorded pins, and how historic bundles find their source | Chenyu (policy) | Closing TB-D-04 as a class; replay by one command | New; no issue yet |
| 9 | Procurement: declare `pay_or_test_reference` as a reference provider and add a headline decision-loss leaf computed at finalize from verified replay inputs (today `pay_or_test_v3_environment.py:217-222` returns the contribution-margin scorer's result and decision loss is computed outside the receipt [read]); the paper reads that leaf. New scorer id and new identity | Chenyu (new identity), family lane | P-T-17, paper Table 5.3 coverage; the reference declaration alone does not close it | New; row P-D-26 |
| 10 | Housing seat map into the sealed plan under a new identity (HL-T-09); v15 still uses the router | Chenyu | Receipts naming a model for seats it never played | Covered by #289.b |
| 11 | #141 remainder. At `1e2ae367` GovSim declares its five leaves (`environment.py:240-292`), econevals 0.1.0 and govsim 0.1.0 are in `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` (`test_shared_runner_scoring_contract.py:3246-3256`), TermsBench 0.1.0 is enrolled directly, and only `termsbench` 0.2.0 remains in the 18-key set [read]. What is left is TermsBench 0.2.0's fixture and the per-fixture expected-status conformance (2.4); whether #141 can close is not re-read | Chenyu | One exemption (termsbench 0.2.0) | Exists (#141) |
| 12 | #144 fixtures for the datacenter scorers (migrated on #63's branch); #306 row | Chenyu, non-author reviewer | Seven or more datacenter exemptions | Exists (#144, #306) |
| 13 | Datacenter setup factory for `verify-replay`; agreement driver counts a sealed exclusion as failed (DC-T-22, needs a later driver identity) | Zeyu or datacenter owner | The main Gate 2 blocker (DC-T-01) | #264.c, DC-T-22 (rows); no new issue |
| 14 | #304: redo the scripted landlord cost floor in an unhashed module after v15 merges | Family lane | Closes #200 | Exists (#304) |
| 15 | EconAgent reverse and repeated replay (B13): after #156, replay one case in reverse and repeated order and check the case-keyed queue (`econagent_v1/environment.py:705-715` still keeps and pops it [read]); the result decides how much FIFO cleanup is needed | Zeyu (family lane) | G10 acceptance: #156 alone is not enough | New; no issue yet |

## 7. Delivery

| Step | What | Owner | Lane | Depends on | Can start now |
|---|---|---|---|---|---|
| 1 | #120: migrate consent_ir scorer, declare two references, red test through run, finalize, replay (including a non-optimal cycle), drop ratchet entry | Zeyu | Family | none | Yes |
| 2 | Write the pin-granularity design (options a2, b1, c2 in detail: manifest check, scheme marker, gate, exemption policy) | Zeyu | Design | Theme ruling | Yes (draft); ruling decides scope |
| 3 | Every publisher passes `source_commit`; the gate checks it against the recorded pins | Zeyu | Tooling (outside execution freeze) | Decision 8 | After the decision |
| 4 | #156 rebase and approval | Zeyu, Chenyu | Kernel | owner's order | Waits on the order |
| 5 | #245 residuals resolved | Zeyu | Kernel | Decision 3 | After the order |
| 6 | #122 json_pointer and R10 at replay | Zeyu | Kernel | #156, #135 D1 | No |
| 7 | #171 canary rule | Zeyu | Kernel | Decision 4 | No |
| 8 | Kernel change: manifest declaration check, pin scheme marker, publication gate | Zeyu | Kernel | Theme ruling, steps 4-5, owner's order after #291-#293 and #248 | No |
| 9 | Conformance test across trusted families; exemption owners and dates | Zeyu | Kernel conftest gate | Decision 7 | Design now; land with step 8 |
| 10 | Family adoption, one family per PR, new identities: procurement reference and decision-loss leaf, Housing seat map, datacenter setup, Refund setup, TermsBench 0.2.0 fixture, #144 fixtures | Zeyu, Yuchen (Refund) | Family | Step 8 | No |
| 11 | #304 cost floor redo | Family lane | Family | v15 on main (met) | Yes |
| 12 | EconAgent reverse and repeated replay check (decision 15), then FIFO cleanup if it fails | Zeyu | Family | #156 | After #156 |

Kernel steps (4-9) go in the lane order the owner set: #246 (merged), #291, #292, #293, #248 after part 1. This charter proposes no change to that order. Each family step is tested against the merged families, not only its branch.

## 8. Not verified

- Whether Refund can replay old receipts on a moved kernel: no Refund setup factory was found (searched by name) and nothing was run.
- The two "reproduced residuals" on #245: not present in the PR text I read.
- #156 at head b4ede44b was not rebuilt against current main (#150 merged after its last rebase).
- The EconAgent adapter's FIFO code was not read; #135.a rests on the record and `evaluation.py:277`.
- `docs/architecture/reviews/kernel_contract_gap_review.md` (ruling R6), incident rows RN-O-04, and `verifier_taxonomy.md` 5.1 were not opened.
- Per-family bodies of scoring-contract fixtures were not read; only the closed-world assertion and the exemption set.
- Secondary items B03, B12, B18, N4 were not examined; B11 is confirmed through #120; B13 is a delivery item (decision 15), not checked.
- Whether TermsBench 0.1.0 enrollment and the econevals, govsim, termsbench finalize tests pass was read by name, not run.
- Counts that come from incident rows (3,520 receipts, 29 of 72 bundles, 30 datacenter bundles) were not recounted.
- The HL-D-11 combination was written as a coordinator's ruling; no owner comment was found, so it is labelled on behalf.
