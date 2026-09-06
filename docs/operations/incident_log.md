# Incident log

**Status:** the single register of things that went wrong, across design,
operations, tooling, and judgment. One place, so an auditor can ask "what failed
and was it addressed" without reading five documents.

The QC standard requires preserving failed attempts as evidence and forbids
deleting history after a later fix. This is where that evidence is indexed. Detail
lives in the linked documents; this file is the index and the disposition.

## How to use it

- Add a row when something fails, not when it is fixed.
- `Detection` is the honest answer to "what caught it", including "a person read
  the output" and "nothing, it was found later".
- `Cost` is what the failure consumed: provider spend, a wasted run, a broken
  main branch, an incorrect claim published.
- A row is never deleted. `Disposition` changes.

Classes: **D** design, **O** operational, **T** tooling and process, **J**
judgment.

---

## The register standard

Four sessions independently built failure records in four shapes during
2026-09-05/06. They are consolidated here. The shapes were not arbitrary --
they answer two different questions -- so the standard keeps both and says
which is which.

**Tier 1, the machine register.** One row per failed cell, call or attempt,
**derived only from published evidence**, so every row traces to a committed
artifact by digest. It is regenerated, never hand-edited, and it answers "what
failed, how often, and where is the proof". Required layout, matching the
housing register:

```
evidence/<family>_failure_register/
  tables/failures.csv     # one row per incident
  reports/summary.json    # counts by campaign / stage / condition, + digests
```

Required row fields: `campaign_id`, `stage`, `failure_condition`,
`source_artifact`, `source_artifact_sha256`. Recommended where meaningful:
`failure_status_code`, `cost_usd`, `world_seed`, `condition_id`, `model_id`,
`attribution`. `summary.json` must carry `register_id`, `schema_version`,
`failure_count`, `artifact_sha256` and `rows_sha256`.

**Attribution is required when a family can distinguish blame.** The
data-center register's taxonomy is the standard one -- `budget`,
`environment`, `model`, `negotiation`, `provider` -- under its own rule:
*anything a model can trigger is the model's, never the provider's*. When a
row is reclassified, the original condition is kept beside the correction
rather than overwritten.

**Tier 2, this log.** One row per *judgment-bearing* incident: design defects,
operational policy failures, tooling accidents, and mistakes of reasoning.
These cannot be derived from evidence because they are about what the evidence
means. Classes: **D** design, **O** operational, **T** tooling and process,
**J** judgment. Per-family narrative detail lives in that family's own
document; this file is the index and the disposition.

### Rules for later additions

1. Add a row when something fails, not when it is fixed.
2. A row is never deleted. Only `disposition` changes.
3. `Detection` is the honest answer to "what caught it", including "a person
   read the output" and "nothing, it was found later".
4. `Cost` is what the failure consumed: provider spend, a wasted run, a broken
   main branch, an incorrect claim published.
5. A failed attempt root is evidence. It stays sealed and is never reused,
   and the Tier 1 register is rebuilt from it.
6. A fix that changes a frozen plan does not retro-publish the run it broke.
   Re-run instead, and record both the run and the reason in Tier 2.
7. New families add a Tier 1 register at the path above and one Tier 2
   section here. Do not start a fifth shape.

### Consolidated index

| Family | Tier 1 register | Incidents | Tier 2 detail |
|---|---|---:|---|
| housing | `evidence/housing_failure_register/` | 56 typed failures over 10 campaigns (45 `rate_limit`, 9 `timeout`, 1 `transport`, 1 `execution_error`; 48 trajectory, 8 profile-admission) | the Housing section below (34 rows); narrative in `docs/families/housing/qc.md` |
| datacenter | `evidence/datacenter_failure_register.{json,md}` -- **to be moved** to the layout above | 541 incidents over 573 cells in 10 runs; attribution after correction: model 298, negotiation 170, provider 47, budget 16, environment 10; 17 rows reclassified | its own register `.md` |
| procurement allocation | not yet built -- **owed** | 39 of 222 provider calls failed across the confirmatory work (17.6%) | `docs/families/procurement-allocation/design_review.md`, and the D/O/T/J sections below |
| econevals | not yet built -- **owed** | 13 attempt roots, 12 failed; $0.125 spent, of which $0.0925 bought a complete but unpublishable panel | `docs/families/econevals/incidents.md` |

Two registers exist in the required shape, two are owed. The gap is recorded
rather than quietly closed.


---

## 2026-09-05 / 06 — Housing delivery and confirmatory push

Opened while taking the Housing family from a partial variance pilot toward
the confirmatory comparison it was designed for. Tier 1 rows for this period
are in `evidence/housing_failure_register/`.

### design

| id | what happened | disposition |
|---|---|---|
| D-1 | The action attempt count was never sized against measured provider reliability. Four attempts against the ~40% per-call rejection rate observed in V19 predicts ~54% cell loss over ~30 sequential actions, which is what V19 delivered. The number was an inherited default. | fixed — 10 attempts in V20, 30 in V24, both spec-driven |
| D-2 | Timeouts were classified as unknown-outcome and never retried. Correct for a side-effecting call, wrong for a stateless chat completion that is safe to re-send. V17 lost two of three cells to single timeouts. | fixed — declared retryable from V20 |
| D-3 | A `$0.01` per-seat cost cap lived only in the runner. It stopped V17 entirely after three cells, and the breach was classified as campaign-critical rather than cell-level missingness. | fixed — `controls.seat_max_cost_usd`, and seat exhaustion is now typed `cost_budget_exceeded` |
| D-4 | The length-retry policy doubles the output budget, quadrupling cost after two escalations, against a seat budget sized for the base case. The two policies were designed independently. | mitigated — budget raised and made visible; the interaction remains undesigned |
| D-5 | Route health was conflated with route identity in two places: the preflight refused any non-zero catalog status, and that status was inside the endpoint identity digest, so a transient derank made an unchanged route look drifted. A direct probe returned 10/10 while flagged degraded. | fixed — `backend.route_status_policy` and `endpoint_snapshot_policy` |
| D-6 | A confirmatory sample size was computed from two paired worlds and emitted as an integer, inviting a precision the estimate does not have. | fixed — `minimum_paired_worlds_for_recommendation` withholds it |
| D-7 | Stochastic replicates were dropped from this line, folding within-world provider noise into the between-world variance that sizes the confirmatory run. QC §5 requires them; the population cross-play design had them. | fixed — restored to 2 from V21 |
| D-8 | Missingness was reported and never gated. V19 lost a third of its cells and still sealed a completed status. The sibling commercial-state family already had the ceiling rule. | fixed — `maximum_operational_failure_fraction` |
| D-9 | The scripted anchor present in `housing_population_crossplay_v0` was dropped from the model-sensitivity line, so environment or scorer drift cannot be distinguished from a model regression across versions. | open |
| D-10 | The analysis contract declares `minimum_confirmatory_worlds: 30` while the sealed sweep provided 16 holdout seeds. No confirmatory campaign could satisfy both, and no variance however small changes it because the floor dominates the powered estimate. The two numbers live in different artifacts and had never been compared. | fixed — `housing_case_config_sweep_v2` extends the holdout to 36 seeds, 35 usable |
| D-11 | The sealed holdout contains a structurally unusable world: the severe configuration at seed `114691332` has a zero assignment upper bound, so it carries no normalized score. Found the first time the holdout was ever generated. | fixed — excluded before any outcome, exclusion re-derived from the generator at load |
| D-12 | `_critical_failure` decides whether a campaign halts by matching substrings in exception messages. Rewording an error silently changes stopping behaviour. | open |
| D-14 | A 404 meaning "no endpoint currently matches the pinned route" is typed `provider_rejected` and is not retryable, so a transient derank kills a cell outright. That is the same conflation of availability with identity as D-5, in the retry policy rather than the preflight. Whether it should be retryable is a measurement decision, not an obvious bug: retrying indefinitely against a genuinely absent route would hide a real pin failure. | open |
| D-13 | The primary estimand averages self-play into the live-opponent aggregate, which QC §5 says to keep separate. Changing it after the pilot would invalidate the variance the sample size derives from. | mitigated — cross-play and self-play published as predeclared slices |

### operational

| id | what happened | disposition |
|---|---|---|
| O-1 | V14 blocked at single-attempt admission on upstream 429s; 0/48 cells. | superseded by V15 |
| O-2 | V15 delivered 43/48 with five GLM-seat losses; no world paired. | superseded by V19 |
| O-3 | V17 stopped after three cells: two DeepSeek timeouts and one hidden seat-budget breach treated as campaign-critical. | fixed via D-3 |
| O-4 | V19 delivered 32/48 with 16 GLM-seat rate-limit losses concentrated in a two-hour burst; two paired worlds. | superseded by V23 |
| O-5 | V23 delivered 186/192 with six losses, but four scattered worlds broke, leaving four paired against a declared six, so the sample size was withheld. | superseded by V26 |
| O-6 | V25 blocked at admission: DeepSeek spent all 4096 completion tokens on reasoning and returned empty content. | fixed via T-2 and T-3 |
| O-8 | V26, mid-run: both replicates of `severe_cw030_r2 / glm_53_flash__vs__glm_53_flash` at world `123194022` failed together with HTTP 404 typed `provider_rejected`, after 12 provider calls each. OpenRouter returns 404 when no endpoint satisfies the pinned provider under `require_parameters` with fallbacks disabled, so the pinned Parasail GLM endpoint briefly stopped matching. Recorded before diagnosis: at the time it was unclear whether this was a route disappearance, a parameter drift, or a content rejection. | open |
| O-7 | Across ten campaigns, 47 of 48 trajectory failures carry a GLM seat, on Morph, DeepInfra, Friendli and Parasail alike. The only condition without a GLM seat failed once. This is a model-specific supply constraint through this gateway, not a sequence of provider incidents. | open |

### tooling

| id | what happened | disposition |
|---|---|---|
| T-1 | The publisher's success path hardcoded the `live` stage, so it had never executed for a `full_trajectory` campaign. | fixed — stage-aware |
| T-2 | The admission raw response was written to one fixed filename per probe, so a retry's differing response hit the immutability guard and raised, and that guard's own message was then classified as an invalid action. Every admission retry that reached the provider was broken. Rate-limit retries appeared to work only because a failed call writes no raw file. | fixed — one raw file per visible attempt |
| T-3 | Admission never inspected `finish_reason`, so a truncated completion was recorded as an invalid action, charging a model with a fault belonging to the output budget. Trajectory execution already handled it. | fixed — typed `length` and the budget escalated on retry |
| T-4 | Admission rows recorded a failure type but not its message, so none of T-2 or T-3 was diagnosable from the sealed evidence. | fixed — message retained |
| T-5 | The pacing ledger returned null for the new client because one `isinstance` check inside the run artifact was not widened alongside the others. | fixed |
| T-6 | A mutation sweep over the newly added guards found 8 of 14 were not actually tested; the missingness-ceiling test reimplemented the rule inside the test file and asserted against its own copy. | fixed — all 18 guards now caught; sweep kept at `tools/housing_guard_mutation_check.py` |
| T-7 | A text splice while staging two campaign specs over-captured its block boundary and duplicated the confirmatory spec twice, silently raising its attempt count. Contract validation caught it. | fixed |
| T-8 | The completion-to-start cooldown held the provider lock for the entire call, so no two calls to a route ever overlapped and, with both models on one provider, the whole campaign serialised. Projected 89 hours for pilot plus confirmatory. | fixed — bounded-concurrency pacing and batched cells |

### judgment

| id | what happened | disposition |
|---|---|---|
| J-1 | Launched a variance pilot without the serial wall-time projection the campaign SOP requires beforehand. The projection, once run, said not to launch. | fixed — pilot stopped, projection published under `evidence/housing_operational_feasibility_2026-09-06/` |
| J-2 | Stated a holdout decision rule as fact — that a standard deviation at or below `0.0668` would let the sealed holdout carry the comparison — having ignored the declared `minimum_confirmatory_worlds`. The conclusion it implied was wrong. | fixed — corrected in QC §30 with the reasoning |
| J-3 | Selected a provider route from five spaced calls over about 75 seconds. It ran clean for four hours and then collapsed for two. The replacement, a 100-call hour-long probe, was still the wrong instrument for a ten-hour run. | mitigated — the durable fix was designing for bursts via retries, not hunting for a quiet route |
| J-4 | Treated a model-specific supply constraint as a series of unrelated provider incidents across six campaigns, changing route each time. Only the cross-campaign register made the pattern visible. | fixed — Tier 1 register built; see O-7 |

---

## 2026-09-05 to 2026-09-06, procurement allocation

### D — Design defects

Fifteen defects with recomputed evidence are enumerated in the
[procurement design review](../families/procurement-allocation/design_review.md),
with a per-defect status table at its end. They are not duplicated here. Summary
as of 2026-09-06: seven fixed, one reopened, seven open. The two most consequential:

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| D-05 | `outcome["feasible"]` is true for a deferral, and every campaign guardrail used it | reading the deferral analysis by hand | a supported development claim rested on a guardrail a defer-heavy treatment could satisfy | fixed: `feasible_award` published per row and guarded; adversarial test added, mutation-verified |
| D-14 | nothing checks that a holdout leaves the control room to fail | a completed 144-row run producing a near-zero effect | $0.45 and the entire confirmatory result | fixed in the standard as a Gate 1 measured-headroom requirement; a $0.015 screen now precedes any panel |

### O — Operational failures

Route: GLM 5.3 Flash on Parasail. Aggregate over the confirmatory work,
**39 of 222 provider calls failed, a 17.6% failure rate.**

| date | campaign | outcome | cost |
|---|---|---|---|
| 09-03 | risk-gate factorial V1 attempt 001 | 77 rows then a typed 429; sealed with 66 unattempted | $0.2067 |
| 09-03 | risk-gate V1 attempts 002-005 | four fresh attempts, canary rejections and early seals | ~0 |
| 09-03 | risk-gate V3 attempt 001 | 135 of 144 rows then a 429 | $0.400 |
| 09-03 | risk-gate V4 attempt 001 | 13 rows then four consecutive 429s | $0.0417 |
| 09-04 | worksheet V1 attempts 001-003 | timeout at row 2; operator interruption; 429 after 7 rows | $0.0235 |
| 09-04 | worksheet V1 attempt 004 | **qualified**, 72/72 | $0.1993 |
| 09-04 | worksheet V2 attempt 001 | **qualified**, 72/72 | $0.2065 |
| 09-05 | pre-award check attempt 001 | **qualified**, 72/72 | $0.2672 |
| 09-05 | pre-award confirmatory v1-v3, seven attempt roots | 24 rows total; two died on a canary 429 before any row | $0.0636 |
| 09-06 | pre-award confirmatory v4 attempt 001 | 144/144 attempted, 12 typed missing, **ineligible** on the per-arm ceiling | $0.4512 |

Two operational findings promoted to design defects: a transient 429 on the
unscored, zero-cost canary permanently seals an attempt root (D-10), and
abort-on-first-failure makes completion probability decay exponentially in panel
size (D-11, fixed).

### T — Tooling and process failures

All mine, all during this session.

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| T-01 | a merge-chain script's `cd` fell through to the operator's live checkout and created two merge commits on their working branch | noticed while inspecting an unrelated failure | two unwanted commits on a branch in use | reverted with `git reset --keep`; the branch matched origin afterwards; script now guards `cd $wt \|\| exit` and asserts the branch |
| T-02 | a `pkill` pattern intended for a campaign also matched the regression run's own test filename and killed it silently | the log stopped advancing | a 25-minute test run lost | rerun; noted that process-name patterns collide with test filenames |
| T-03 | a conftest merge resolution dropped a function definition line, leaving an `IndentationError` that broke collection repository-wide | a full-suite run, 36 minutes | main red for ~10 minutes | hotfix PR #85; an AST-parse test and an import smoke now catch it in seconds |
| T-04 | the consolidated conftest used dict entries where two adapters unpack three-tuples, and renamed a summary title a third asserts | a full-suite run | main red; 2 of 1547 tests failing | hotfix PR #88; all seven gated families' own tests now run in the QC layer |
| T-05 | a run driver started without `--resume` against an existing attempt root, so the campaign raised `FileExistsError` and the driver reported "no rows" | reading the driver log | one restart | driver now resumes when the root exists |
| T-06 | the driver's no-progress guard fired on a *completed* panel and reported it as stopped | reconciling the log against the run root | a moment's confusion about whether the panel finished | benign; the guard needs a completion check before a progress check |
| T-07 | campaign exit codes still treated any typed missingness as an abort after the policy changed to tolerate it, so a resuming driver stopped at 24 of 144 rows | the run stalled at a checkpoint | one restart | exit codes now return the abort code only when the declared ceiling is breached |
| T-08 | a scripted port of the missingness policy into a sibling campaign module failed midway on a text-block extraction | the module failed to build its plan | reverted, no lasting effect | the screen was run through the qualification engine directly instead, which needed 35 lines rather than a 1,100-line campaign clone |

T-08 is worth reading twice: it is the cost of design defect D-12 made concrete.
A fix applied to one campaign module does not reach its four near-identical
siblings, and the siblings exist because the plan digest conflates scientific and
operational parameters.

### J — Judgment failures

Also mine. These are the ones no test would have caught.

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| J-01 | built a confirmatory holdout by matching the failure *themes* of the development panel rather than its *difficulty*; the control saturated 7 of 12 worlds | the completed run's near-zero effect, then a per-world control-rate check | $0.45 and the confirmatory result | D-14 raised; Gate 1 now requires measured headroom; the bad panel is retained as the detector's regression fixture |
| J-02 | reported that panel as showing the treatment "does not replicate" | re-examining the control rate after being asked why it failed | an overstated claim, live for about twenty minutes in conversation and one commit | corrected in the campaign document, the QC profile, and PR #98; the correct reading is that the panel is uninformative in either direction |
| J-03 | fixed "verbal claims are always true" by biasing the verbal reply, without checking that any evaluated policy reads verbal replies; a screen recorded zero `inquire` actions across a whole panel | a $0.0153 control screen | would have wasted a $0.30 run; caught before spending | D-01 reopened, D-15 raised; the bias must sit on the listing |
| J-04 | recommended cutting working capital because it is "arithmetic over facts already held" | the operator asked whether it models a reselling process | an incorrect rationale in a design document, corrected the same day | the real objection is scale: $50 lines against ~70% margins make the term worth ~$0.72 at honest parameters, and the six cases where it matters use 150-200% annual financing |

J-01 and J-03 share a cause: a panel was authored against an intuition about what
would be hard, and neither intuition was measured before the panel was frozen.
The $0.015 control screen now exists precisely because it is three orders of
magnitude cheaper than discovering the same thing from a completed run.

---

## Standing lessons

1. **Measure the panel before you spend on it.** A control screen at one seed
   costs about $0.015 and has now caught two unusable panels.
2. **Check that a channel is read before you put information in it.** Zero
   `inquire` actions made a correct, tested mechanism inert.
3. **A guardrail that nothing fails is not a guardrail.** Prove it with a
   synthetic arm that games the metric.
4. **A check that has never failed may be true by construction.** Kill it by
   mutation, and record when a mutation survives.
5. **Scripted git belongs in a scratch worktree**, with `cd ... || exit` and a
   branch assertion, never in a checkout someone is using.

---

## 2026-09-05 to 2026-09-06, econevals first light

Building the first live path for an adapter that had corpus, environment,
measurement and replay but had never resolved a run plan or sealed a receipt.
Thirteen attempt roots, twelve of which failed. Per-attempt detail, recovered
from the sealed roots rather than from notes, is in
[the econevals incident ledger](../families/econevals/incidents.md).

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| E-D-01 | the kernel called `plugin.initial_state(family_case, run=None)` in the replay path but positionally in the scheduler; nine of eleven external adapters name that parameter `cell`, so **no external adapter could produce a replayed receipt** | building the first live path for one of the nine | every external adapter's receipts, silently, since the reorg; blocks #91, #92, #93 alike | fixed by calling it positionally; a signature test now covers all 18 plugins |
| E-D-02 | the frozen plan hashed `campaign.py`, which carries the publisher as well as the executor, so a publisher bug is unfixable for a completed run: publish and it crashes, fix it and the freeze rejects its own run | a complete six-case panel that could not be published | $0.0925 and a full panel | freeze now covers execution sources only; publisher digest moved to the publication manifest; run repeated rather than retro-published |
| E-D-03 | neither the observation nor the submit tool's schema stated the submit argument's required shape | a 100-period run in which the model submitted `[]` every period | one panel; scoring it would have measured our omission, not the model | shape declared per track on both surfaces |
| E-D-04 | the family manifest declared no `scoring.reference_provider_ids` while its leaves cite seven implementations; the resolver rejects an unreferenced pin, the receipt rejects an unpinned citation | first plan resolution | none, caught pre-spend | union computed from the leaf builders so manifest and pins cannot drift |
| E-D-05 | the scorer had per-attempt methods but no once-per-episode finalizer, so the kernel could not call it at all | first finalize attempt | none, caught pre-spend | `FamilyScoreSet` finalizer added, surfacing both leaves (closes #74) |

### O — Operational failures

Route: GLM 5.3 Flash on Parasail, the same shared upstream pool procurement
uses.

| date | attempt | outcome | cost |
|---|---|---|---|
| 09-06 | 001, 002 | canary rejected: route seal shape, then a transient 429 that sealed the root | $0 |
| 09-06 | 003-006 | four contract errors, each dying on the first action: undeclared seed, invented tool name, truncation at 900 tokens, an unretried 429 | $0.00015 |
| 09-06 | 007 | 100 periods, receipt excluded on a malformed submission; campaign wrongly aborted on a measurement verdict | $0.00004 |
| 09-06 | 008 | case 00 scored `included`, then a spurious Parasail **404** | $0.0105 |
| 09-06 | 009 | two procurement cases scored, then an empty turn exhausted the harness's corrective rounds | $0.0216 |
| 09-06 | 010 | ten attempts against a 429 burst exhausted in two minutes: backoff is opt-in and none was declared | $0.00004 |
| 09-06 | 011 | **6/6 cases `ok/included`**, 100 periods each -- unpublishable, see E-D-02 | $0.0925 |
| 09-06 | 012 | spurious Parasail **404** again, on the first action | $0.00003 |
| 09-06 | 013 | two procurement cases scored, then a sustained 429 exhausted ten attempts **with** backoff (~3 min of spread) | $0.0215 |

Disposition: a route-availability block, not a campaign defect. Attempt 011
ran the identical panel to completion, so the frozen plan is re-run in a
later window rather than adjusted.

Two operational findings promoted: the write-once canary (D-10 in the
procurement section) sealed two roots here before the fix and then saved two
more, and retry policy inherited from a 12-round chat family is wrong for one
making 600 sequential calls.

### J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| E-J-01 | sized the panel's retry policy by copying tau3's profile instead of multiplying out this family's call count | a 429 killing a run at case 00 | one attempt | attempts raised to 10 with declared backoff, and the arithmetic written into the profile |
| E-J-02 | planned to truncate periods through the agent budget to fit the cost ceiling | a dry run showing it raises `SchedulerContractError` rather than terminating cleanly | none, caught pre-spend | cases run at their own pinned `max_steps`; it would have manufactured failed receipts |

## Standing lessons, added

6. **A first live campaign is a defect detector.** econevals had four
   milestones of tests and thirteen defects survived to the first live run,
   four of which would have produced misleading evidence rather than a clean
   failure.
7. **Do not put the publisher inside the execution freeze.** Evidence
   projection describes how a run was reported, not what it did.
8. **Copying an execution profile copies its assumptions.** tau3's retry,
   backoff and round policies are correct for 12-round chat episodes and
   wrong for 100 sequential calls per case.
9. **A verifier rejecting the model is not a broken pipeline.** Conflating
   the two makes a panel unable to report the thing it measures.


---

## 2026-09-06, pull-request discipline and stack verification

Adopting the PR lanes (#121), reviewing the fourteen-PR migration stack, and
building its combined tree on a scratch branch. Rules that came out of it are
in `CLAUDE.md` ("Merging is a step that can fail").

### T — Tooling and process failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-T-01 | while waiting for #121's CI, a chained command attempted the merge (correctly refused by branch protection) and then PATCHed `kernel-review` into the required status checks unconditionally -- before the workflow existed on `main`, the ordering the PR itself warns against | noticed in the command's own output | ~3 minutes in which every open PR would have blocked on a check it could not receive; no PR merged or blocked | reverted at once; the re-run checks `state == MERGED` before touching repository settings; rule recorded in `CLAUDE.md` |
| P-T-02 | the first combined-tree chain ran `for spec in $ORDER` under zsh, which does not word-split an unquoted variable: it merged one branch and logged "all 14 merged" six seconds later, then started a full suite on the wrong tree | the log claimed completion in six seconds | one aborted suite run | killed and rerun as a bash script with an array; noted that chain scripts must not rely on zsh word-splitting |
| P-T-03 | git's `merge=union` driver, tried as an automation of the stack's "every conflict is a union" rule, concatenated both sides of the two set literals every family edits and left the protocol-test module unparsable (`IndentationError`); the bound-names check could not run because the file no longer parsed | `ast.parse` failing in the checker | none, scratch branch only | "the file parses" added as step zero of the recipe; the structural fix (per-family enrolment modules) proposed on #103 |

### J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-J-01 | a docstring fix pointed at a historical design document with a blank commit hash, then with a commit that did not contain the file, before the third attempt verified the path with `git cat-file -e` | a verification step added after the second wrong hint | two force-pushes to an unreviewed branch | fixed; verify a `git show <sha>:<path>` hint before writing it |
