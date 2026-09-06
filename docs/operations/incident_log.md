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
| housing | `evidence/housing_failure_register/` | 56 typed failures over 10 campaigns (45 `rate_limit`, 9 `timeout`, 1 `transport`, 1 `execution_error`; 48 trajectory, 8 profile-admission) | `docs/operations/benchmark_qc.md` |
| datacenter | `evidence/datacenter_failure_register.{json,md}` -- **to be moved** to the layout above | 541 incidents over 573 cells in 10 runs; attribution after correction: model 298, negotiation 170, provider 47, budget 16, environment 10; 17 rows reclassified | its own register `.md` |
| procurement allocation | not yet built -- **owed** | 39 of 222 provider calls failed across the confirmatory work (17.6%) | `docs/families/procurement-allocation/design_review.md`, and the D/O/T/J sections below |
| econevals | not yet built -- **owed** | 13 attempt roots, 12 failed; $0.125 spent, of which $0.0925 bought a complete but unpublishable panel | `docs/families/econevals/incidents.md` |

Two registers exist in the required shape, two are owed. The gap is recorded
rather than quietly closed.


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
| 09-06 | 008 | case 00 scored `included`, then a spurious Parasail **404** | $0.0255 |
| 09-06 | 009 | two procurement cases scored, then an empty turn exhausted the harness's corrective rounds | $0.0228 |
| 09-06 | 010 | ten attempts against a 429 burst exhausted in two minutes: backoff is opt-in and none was declared | $0.00004 |
| 09-06 | 011 | **6/6 cases `ok/included`**, 100 periods each -- unpublishable, see E-D-02 | $0.0925 |
| 09-06 | 012 | spurious Parasail **404** again, on the first action | $0.00003 |
| 09-06 | 013 | two procurement cases scored, then a sustained 429 exhausted ten attempts **with** backoff (~3 min of spread) | $0.0689 |

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
| E-J-03 | reported per-attempt costs from checkpoints that omit a failed case's spend, understating what the failures consumed by 44% | the operator asked whether a 429 costs anything | an understated incident ledger, corrected the same day | failure checkpoints now recover sealed spend; ledger figures restated |

**E-J-03 is not econevals-only.** A survey of every family's failure path:

| family | failed-case spend recorded? |
|---|---|
| housing | yes -- `cost_usd` plus a `billing_status` field on the failure row |
| procurement allocation | yes -- `_sealed_failure_telemetry` recovers incurred usage from the sealed event ledger and flags `telemetry_complete` |
| econevals | **was no**, fixed here |
| tau3 retail (PR #97) | **no** -- the failure checkpoint records `failure_type` and `failure_condition` only, so a case killed after successful turns reports no spend |

econevals inherited the omission by copying tau3's checkpoint shape, which
is the same way it inherited tau3's retry and backoff policies (E-J-01).
Procurement's `_sealed_failure_telemetry` is the better pattern of the two
implementations -- it reads the event ledger rather than walking artifacts,
and it says when telemetry is incomplete rather than silently summing what
it found. Raised for tau3's owner rather than changed here.
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
