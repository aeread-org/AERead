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
| datacenter | **not on `main`** -- the register in the standard layout exists only on the unmerged branch `codex/datacenter-world-panel-v1` (`evidence/datacenter_development_failure_register/`, 766 incidents, 19 defects, 1 open); the earlier flat `evidence/datacenter_failure_register.{json,md}` this row used to name is absent from `main` (DC-T-03) | 541 incidents over 573 cells in 10 runs as last indexed; attribution after correction: model 298, negotiation 170, provider 47, budget 16, environment 10; 17 rows reclassified | [the data-center QC profile](../families/datacenter/qc.md) and the 2026-09-19 section below (DC-D-01..03, DC-T-01..03) |
| procurement allocation | not yet built -- **owed** | 39 of 222 provider calls failed across the confirmatory work (17.6%) | `docs/families/procurement-allocation/design_review.md`, and the D/O/T/J sections below |
| econevals | `evidence/econevals/econevals_failure_register/` | 19 typed failures over 13 attempt roots (10 `rate_limit`, 3 `malformed_structured_output`, 2 `provider_rejected`, 2 `provider_contract`, 2 `invalid_measurement`); 176 retried provider-call failures beneath them; attribution provider 12, model 5, environment 2 | `docs/families/econevals/incidents.md` |
| termsbench | `evidence/termsbench_failure_register/` | 1 typed failure over 2 attempt roots (v1 aborted at 8/30 on `malformed_structured_output`, a decoding degeneration; v2 30/30 with no typed failure); 13 of 30 v2 episodes carry a measured individual-rationality violation, which is a score, not a failure row | the TERMS-Bench section below (TB-D-01..03, TB-O-01); `docs/families/termsbench/campaign_scoping.md` |
| govsim | not yet built -- **owed** | 3 live campaigns (`first_light_v1`, `dialogue_v2`, `dialogue_v3`) with 0 typed execution failures; the family's incidents are judgment-bearing (a fabricated-utterance near miss, an identity collision, a pre-fix source pin, an arm mismatch) rather than machine-derivable | [the govsim ledger](../families/govsim/incidents.md) (G-D-01..03, G-J-01..02) |
| tau3 retail | not yet built -- **owed** (PR #97) | 5 campaign identities in one day (v14-v18); v18 excluded 3 cases on the per-case cap and 1 on a malformed response | PR #97; no Tier 2 section yet |

Four registers exist in the required shape (housing, econevals, termsbench,
and the data-center one pending its move to the standard layout); procurement
still owes one, and tau3 and the seven #132 adapter families owe theirs. The gap is
recorded rather than quietly closed.

A note the econevals register makes concrete: a checkpoint records
`execution_failure` whenever the exception carries no `condition`, which is
true of every `SchedulerContractError`, so a register built from checkpoints
alone cannot tell a 429 from a 404 from a contract error. The typed
conditions must be recovered from the sealed event ledger. Any family
building a Tier 1 register should do the same rather than trusting the
checkpoint's label.


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
| T-09 | cleaning up a rejected panel, `rm -f .../trap_*.json` also matched three cases of the *retained* fixture the rejected panel was never meant to touch | `git status` immediately after showed three deletions that should not have been there | none; restored from the index in the same minute | a glob written for files created minutes earlier reached files created days earlier, in a directory J-05 designates as evidence to preserve. Deletions in an evidence directory name their files or restrict themselves to untracked paths |
| T-10 | CI went red on a commit that touched only documentation. The cause was already on the branch: environment fixes had moved ten frozen `plan_sha256` literals across seven campaign tests, and no commit since had run the full suite | a documentation-only push failing CI, which is the signal that the failure predates it | roughly 50 minutes of CI and local suite time over three pushes, since each push restarted a 35-minute run | literals updated and labelled as current-source identity rather than as seals; a new test pins the published bundles' self-verifying digests. Recorded as design defect 19 |
| T-11 | the session scratchpad under `/private/tmp` was garbage-collected while in use. It emptied per-seed result directories, deleted scratch generator scripts, removed kernel source files from a git worktree and severed that worktree's `.git` link | an import failing on a module present an hour earlier, then `git status` reporting the worktree was not a repository | the worktree was unusable; the branch on origin was unaffected because every change had been pushed | worktree recreated from origin. Anything that must survive belongs in a commit, and `runs/` is gitignored so it never qualifies |
| T-12 | removed the damaged worktree with `rm -rf` to recreate it, destroying the only copy of 84 model trajectories: two arms of GLM 5.3 Flash and two of Gemini 3.8 Flash, about $0.60 of provider spend and the evidence behind design defects 24 and 25 | searching for the files immediately afterwards in order to analyse them | 84 trajectories unrecoverable; the findings survive only as numbers already written into the design review | the six worlds had been reconstructed and digest-verified against the run plan minutes earlier, which is the only reason those numbers remain checkable. A run root that has produced evidence is copied out of the scratchpad before anything is deleted |

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
| J-05 | built the due-diligence panel and admitted it on a control-only screen; only 1 of 6 worlds could express a difference, 2 saturated and 2 floored | the operator asked whether the zero-delta worlds were saturated or non-discriminatory, which I had not checked | $0.20 on a comparison that is effectively one world | D-16 raised; Gate 1 now requires two-sided headroom screened with two policies; the campaign write-up was corrected from "one-world artifact" to "one-world comparison" |
| J-06 | the two-sided screen built to fix J-05 called the baseline policy with a positional argument where the parameter is keyword-only, and its `except Exception: return None` reported the resulting `TypeError` as "the baseline lost". Every baseline in every world raised, so the screen printed `admitted 6/6` having never run its second policy | the uniformity was implausible, so the baselines were traced before the verdict was used | none: caught before the panel was frozen, and the corrected screen reached the same admission decision for real | exception handling removed from the screen's action loop, so a broken policy aborts instead of scoring; a screen whose baselines all reach no terminal now rejects rather than admits |
| J-07 | the same screen's admission rule was "the two policies disagree", which admits a world where the control already wins every seed -- the precise saturation of J-01 and D-14, re-created inside the fix for D-16 | re-reading the rule against the earlier per-world control rates | none: caught before spending | admission now tests three separable conditions -- trivial, floored, saturated -- and measures the control at four seeds, because one seed cannot distinguish a ceiling from a lucky draw |
| J-08 | wrote a test asserting that an award is scored on the supplier's true yield rather than the buyer's noisy estimate, then mutated the scorer to read the estimate. **The mutation survived.** The test awarded one component of a two-component bill, so the award completed zero kits whatever the yields were and never reached the yield arithmetic | running the mutation, which the QC standard requires for every new guard | none; the guard was unverified for about ten minutes and was never published in that state | the test now awards a qualifying supplier for every component and asserts a positive completed-kit count before comparing margins. Re-run, the mutation fails the test and nothing else |
| J-09 | the paired-world independence check was mutated to report "clean" unconditionally, and **the mutation survived**: all 24 tests still passed. The check runs against an environment that is genuinely independent, so it had never returned a negative and nothing proved it could | running the mutation, one day after J-08 taught the same lesson | none; caught before the module was pushed | the check now takes an injectable replay, and two tests drive it from both sides: an order-dependent replay must be reported as contaminated, and a pure one must not |
| J-10 | admitted an eight-world panel, promoted it to a committed generator with tests, and wrote its cases into `cases/`. It was screened only against the declared baselines, which lose those worlds without ever awarding, because their stopping rule requires covering the full target and they defer once they cannot qualify another supplier | writing a test that asserted the cash budget forbade the hedge; the arithmetic said $46 against a $55 budget, so the stated mechanism was false, and tracing a baseline showed it deferring rather than being priced out | none published; the panel, its generator and its tests were removed in the same session | a stronger screening reference was added, which solved 8 of 8 at better regret than the subject. Recorded as design defect 22 |
| J-11 | a test asserting that screening draws come from a stream separate from sampling called the draw helper directly with a literal `"inquiry:"` prefix, so it tested the helper and not the wiring; pointing the environment at the shared stream left it passing. The third surviving mutation in two days | running the mutation, routine after J-08 and J-09 | none; caught before push | the test now drives the environment and compares a reading against a sample for every supplier at equal batch size |
| J-12 | analysed why two models fail by comparing each awarded supplier against its **hidden** yield, concluding they routinely awarded suppliers they had already seen were worse: 17 of 17 failing GLM rows and 5 of 7 for Gemini | re-deriving the same numbers from what the buyer actually saw, reconstructed from the declared noise seed, before reporting any of it | none; caught before the claim left the session | the strict figures are 10 of 57 and 0 of 20. Judging a decision against information the decider did not hold turned a thin-evidence problem into an apparent reasoning failure |
| J-13 | reported J-08 through J-12 as recorded when none of them reached the file. Each edit anchored on text that commit `c1069921` had already removed, so `str.replace` matched nothing, rewrote the file unchanged, and printed its success message anyway | reviewing the branch diff before writing PR notes and noticing the incident log was absent from it | eight judgment records missing across two branches for two days, and five separate claims to the operator that they were recorded | rows restored from `c1069921^` and from the commit messages that did land; anchored edits now assert the anchor exists before replacing |
| J-14 | asserted that the branch had deleted a kernel source file, on the strength of a `git cat-file` check that zsh had silently mangled: the `<rev>:<path>` argument was parsed as a `:s/old/new/` substitution modifier and the path was rewritten | running `git ls-tree` on the same path, which listed the file present | none published; checked before the claim left the session | the branch deletes nothing. Quote every `<rev>:<path>` argument, and prefer `ls-tree` to an exit-code check whose failure mode is indistinguishable from absence |

J-01, J-03, J-05 and J-10 share a cause: a panel was authored against an
intuition about what would be hard, and the intuition was not measured before the
panel was frozen. J-06 through J-09 and J-11 are a different family: defects in
the instrument built to catch the previous defect, each found by distrusting a
clean result rather than by the instrument itself.

J-13 is the one to read twice. Eight of these rows did not exist until they were
reconstructed, because a consolidation removed the text later edits anchored on,
and those edits then failed silently while reporting success. A register that can
be edited by a no-op is not a register.
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

---

## 2026-09-07, trajectory grain backfill

Publishing the kernel trajectory grain (#136, #138) into the already-published
procurement bundles (#139).

### T — Tooling and process failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-T-04 | the local full-suite gate was `pytest ... \| tail -4` and the exit code read was `tail`'s; the first push of #139 was described as "full suite green locally" while five confirmatory tests were red | CI failed 20 tests on the same tree | one CI cycle; a wrong claim on a PR | suite commands now `set -o pipefail` and read pytest's summary line; #136–#138 had been independently green on CI |
| P-T-05 | the P-T-02 zsh trap recurred: `for p in $PINNED` did not split, so seven paths became one, and `mv`/`git checkout` failed on a too-long filename | the commands' own errors | none; nothing was moved | redone in Python; shell loops over lists stay in bash arrays or Python |

### J — Judgment failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| P-J-02 | ten bundles were re-sealed with the grain as a "mechanical correction" without checking whether anything froze their manifests; seven are pinned as parent controls (`PARENT_EVIDENCE_FILE_SHA256`) by later campaign modules, and a changed frozen control requires a new campaign identity | CI: `parent ... evidence manifest changed` | one CI cycle | parents restored byte-for-byte; their rows published as a derived bundle bound to the parents' digests; the leaf-only rule and the pin check are now in `reviewing_trajectories.md` §5 |

## 2026-09-08 — judgment: a frozen control edited in place under a published campaign

`#98` added `feasible_award` to the `primary_outcomes` list in
`procurement_allocation/model_campaign.py`. That list is frozen into every
plan `planned_model_qualification` builds, and one of those plans --
`procurement_allocation_glm53_flash_parasail_qwen_holdout_transfer_v1`,
published in #62 -- had already been sealed under the old list. After #98,
rebuilding that plan from source no longer reproduced its sealed digest
(`3fbba58a…` became `8dc6d893…`), and #62 went red on a test that exists
precisely to notice this.

Campaign discipline says a changed frozen control takes a new identity. #98
changed it in place. The consequence was contained -- the sealed bundle is
untouched and correct, and no published evidence carried the parent digest --
but "the test was wrong" would have been the easy reading, and updating the
recorded digest would have deleted the only record that a frozen plan had
stopped matching its source.

Disposition: `primary_outcomes` is now a parameter threaded from each
campaign's spec, defaulting to today's list; the sealed campaign declares the
list it sealed with. Its digest reproduces again, and no other campaign's
digest moved (42 procurement digest tests). The rule that should have caught
this at review time, not test time, is the one #143 adds.
## 2026-09-08 — tooling: main went red on a test neither PR had seen fail

#125 added a two-way coverage ratchet over `TRUSTED_BUILTIN_PLUGIN_KEYS`.
#147 enrolled seven datacenter keys as trusted, merging at 05:15Z -- after
#125's last CI run and before its merge at 17:26Z. Each PR was green on its
own; `main` at `b728736d` fails
`test_every_trusted_key_is_checked_or_named_as_uncovered`, and #107's CI hit
the same wall first.

Not a defect in either PR. It is the gap branch protection leaves open: a
required check is evaluated on the PR head against the base *at trigger
time*, not at merge time, so two green PRs can compose into a red main.
Disposition: the keys are named in the allowlist with their reason (campaign-
registered, not a package hook), and the ratchet will demand their removal
the day they resolve. Worth a rule: re-run a PR's checks if `main` has moved
under it since they last ran, before merging.

## 2026-09-08, TERMS-Bench first live pilot (#92)

The first live path for a family whose counterpart is not a model. The
kernel gained a scripted-seat capability for it (#150,
`docs/kernel_scripted_seats_design.md`); the family's live setup, campaign
and publisher were built against it offline, every corpus case run through
the real kernel with a fake route, before any provider call.

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| TB-D-01 | a receipt with a scripted seat could be sealed and replayed but not read back: the research layer's `_deserialize_receipt` did not know `scripted_seats`, rebuilt the receipt with the empty default, and `verify_evaluation_receipt` rejected the digest; the same gap sat in `_deserialize_run_plan` for cells, and the research report's permitted-seat check named only model seats | the family publisher's test, on the first genuine receipt it projected -- offline, before any spend | none; found before the canary | fixed in #150 (`fe8cdd6d`): the research layer reads `scripted_seats` on receipts and cells, defaulting when absent so older receipts read unchanged; `receipt_projection` publishes which seats were not models; round-trip test added |
| TB-D-02 | the live harness typed a model answer that was not a JSON object as a non-retryable `malformed_structured_output` route fault, which the kernel wraps as `SchedulerContractError` and the campaign as an operational abort. The kernel's OpenRouter client deliberately keeps a completed, billable non-JSON answer on the normal response path "so the family parser can classify malformed model output as agent behavior", and this family defines a malformed move as a measured `agreement_violation` (`malformed_action_schema`, receipt `invalid_measurement`, spec golden 4). The harness pre-empted both -- the same mistake its own docstring warned against, one level up | attempt_001 of the v1 pilot aborting at case 8/30 | $0.0052 on the case, 22 cases never run, a campaign identity | fixed in v2 (`live.py` harness 1.1): the text reaches the family unchanged; `campaign.py` seals a failed cell as a typed exclusion (`finalize_family_failure`) and continues, aborting only outside a cell |
| TB-D-03 | the kernel's two chat clients type a truncated structured response differently: the Arena client raises `length` (retryable, budget growth) when `finish_reason == "length"` and the JSON does not parse; the OpenRouter client returns the truncated text as a completed answer, and `ModelTurn` carries no `finish_reason`, so a harness cannot tell truncation from a finished malformed answer. On this route the difference decides whether a degenerate answer is retried or measured | reading the sealed provider result of TB-O-01 (`finish_reason: length`, 4000 output tokens) | none beyond TB-O-01 | open; filed as #152 rather than changed under the scripted-seat PR (one concern per kernel PR) |

### O — Operational failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| TB-O-01 | `termsbench_glm53_flash_parasail_pilot_v1`, attempt_001: canary admitted (358 in / 29 out, $0.00007), cases 0–6 complete and replayed (1.1–8.4 s each, ≤ $0.0005), then case 7 (`termsbench.candid.nodeal.1010055`, buyer r=56.66 against a seller opening at 151.65) aborted the campaign: on its fifth agent turn GLM 5.3 Flash at temperature 0 wrote `{"decision": "offer", "price": 56.5993352745860345659335…` and repeated the digits of the price until the 4,000-token output ceiling (`finish_reason: length`, 26 reasoning tokens, $0.0021 for the call); the harness typed it `malformed_structured_output` (TB-D-02). First hypothesis on reading the checkpoint -- "the route returned prose" -- was wrong: it was a decoding degeneration inside a number. The checkpoint records `execution_failure`, as every `SchedulerContractError` does; the typed condition is in the sealed ledger | the campaign's own abort; the cause from the sealed provider result | $0.0074 total across the attempt; 22 of 30 cases never run; the v1 identity | the attempt root stays sealed as evidence (Tier 1 row 1); v2 identity with the TB-D-02 fix ran 30/30 complete, $0.029, 5.6 min, and on the same case at temperature 0 the degeneration did not recur (`counterpart_walk_away`, 5 rounds) -- the route is not deterministic at temperature 0, so a v1 rerun would have been evidence of nothing; the model's degeneration is a measured outcome in v2's design, not an abort |

### T — Tooling and process failures

| id | what happened | detection | cost | disposition |
|---|---|---|---|---|
| TB-T-01 | #150 pushed as ready with "full suite green locally" (2,477 passed) and CI failed at collection on Python 3.10: `mutable default <class 'mappingproxy'> for field scripted_seats is not allowed: use default_factory`. The local venv is 3.13, where `mappingproxy` is hashable and `dataclasses` accepts it as a plain default; on 3.10/3.11 it is unhashable and rejected. The plain default was chosen deliberately, because the omit-if-default rule compared against `field.default` and a factory field has none. First reading of the red check -- "kernel-review, no approval yet" -- was right for one job and hid the other | CI (`agenticpay-fidelity`, then `test (3.10)`) | two red checks on a PR just marked ready; one CI cycle | factory defaults on `RunSpec`, `PlanCell` and `EvaluationReceipt`, and a `field_default` helper the omit rule (both digest paths) looks through; reproduced and re-run under a 3.10 venv before the next push. Rule: a local gate on one interpreter is not the CI matrix; run the touched tests under 3.10 too when a dataclass default changes |
| TB-T-02 | `gh pr edit 150 --body-file … && gh pr ready 150` exited non-zero on a GraphQL warning (`Projects (classic) is being deprecated … projectCards`) after applying only the title, so the chained `gh pr ready` never ran and the reviewer request failed the same way; the PR sat as a draft with the stale "implementation is not written yet" body while the push comment said it was ready. Noticed only because the follow-up `gh pr view` was read | a person read `gh pr view` output | none beyond confusion on the PR | `gh api -X PATCH repos/…/pulls/N` and `gh api … /requested_reviewers` for edits; never chain state changes behind a `gh pr edit` without checking its exit |
| TB-T-03 | in zsh, `git show $B:src/aeread_families/tau3_retail/campaign.py` expanded `$B:s…` as a history modifier and produced `origin/codex/tau3-first-live-campaignetail/campaign.py` -- twice in one session, the second time on `$T:src/…` after the first was diagnosed | the commands' own errors | two wasted reads | `"${B}:path"` always; the P-T-02/P-T-05 zsh rows now have a third sibling |
| TB-T-04 | the Tier 1 register built from the family worktree emitted `source_artifact` as absolute paths (the sealed runs live under the live checkout, not the worktree), and the prohibited-text scan refused the table on `/users/` | `assert_public_payload` at publish | one failed build | `failure_register.py --repository-root`; the scan doing its job is why this row exists rather than an absolute path in a committed register |
| TB-T-05 | merging `main` (#109, #112) into #150: `git checkout --theirs` on the two conflicting kernel files, then re-applying this branch's hunks by script, silently dropped three statement-level hunks (the research report's permitted-seat union, the cell deserializer's `scripted_seats`, and the receipt's `__post_init__` validation of scripted seats) while a weaker re-typed `__post_init__` took the original's place. The bound-names superset check passed on both files -- it sees module-level names, not statements -- and 471 tests passed, because no test covered the permitted-seat union | reading every removed line of `git diff <parent>` for each parent before committing the merge | none; caught before the merge commit | the three hunks restored from the pre-merge head byte-for-byte; the rule gains a step: after the bound-names check, read the removed lines of the resolved file against *each* parent, and treat any removed non-comment line the other parent did not remove as a dropped hunk |

## 2026-09-09 — tooling: a rebase raced a merge by two minutes

#132 rebased onto `main` at 04:21Z and reported "rebased onto the current
main after its kernel contract updates"; #112 had merged at 04:19Z as
`2318d748`. The rebase base was `b37c3d0d`, one commit behind, so the
branch carried #112's R13 code as it stood on #112's branch, not as merged:
`git merge-tree` against `main` shows a single-line conflict in
`task/evaluation.py` (`_reject_undeclared_inapplicable_ids(registration.manifest, …)`
on `main`, the pre-merge `(family, …)` on the branch) and the usual union
in `tests/test_shared_runner_scoring_contract.py`. GitHub runs no workflow on
a conflicting PR, so the Python 3.12 fix pushed in the same rebase has not
been exercised by CI either.

Not a design defect in either PR, and a kernel-file conflict is a stop rather
than a hand-resolve, so it was reported on #132 with the target commit. It is
the same gap the 2026-09-08 row above names from the other side: a check, or
a rebase, is evaluated against `main` *at that moment*. Rule to add to the
one there: read `main`'s head from `git ls-remote` immediately before the
rebase, and put that commit in the rebase comment, so "current main" is a
digest and not a claim.

## 2026-09-10 — design: two declared reasoning conditions that both turn reasoning off

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| R-D-01 | every live panel this repository has published on GLM 5.3 Flash/Parasail declared a reasoning condition that suppresses reasoning, and none of them says so. One call per condition on the same prompt (2026-09-10): `reasoning.max_tokens: 1500` → 13 reasoning tokens; `reasoning.max_tokens: 8000` → 13; `reasoning.effort: "low"` → 13; **no reasoning block at all → 259**. The cap is a switch, not a budget, and the two settings we use (`reasoning_capped_1500_v1` for econevals and TERMS-Bench, `reasoning_low_v1` for govsim) are the same behaviour under different names. `docs/research/reasoning_condition_and_diagnostics.md` already requires the condition to be declared and versioned; what it could not require is that the declared name describe what the route does with it | asking why TERMS-Bench pilot v2's 43% critical-violation rate sat twenty times above the paper's 0–2.06% band for thirteen deliberating agents | no run invalidated -- every panel measured a real, declared configuration -- but `econevals_glm53_flash_parasail_panel_v10`, `govsim_glm53_flash_parasail_first_light_v1` and `govsim_glm53_flash_parasail_dialogue_v3` all measure a **non-deliberating** GLM 5.3 Flash and must be read that way, and no published number of ours is a like-for-like against a paper table until the deliberating arm is run | `termsbench/live.py` names both measured conditions (`reasoning_capped_1500_v1`, `reasoning_unconstrained_v1`) and puts the condition in the profile id, so a panel cannot silently change which agent it measured; TERMS-Bench pilot v3 runs the deliberating arm as its own identity. The same arm is owed for econevals and govsim. Open |

## 2026-09-10 — design: receipt compatibility accepted altered JSON and unreadable writes (#151)

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| PR151-D-01 | the transitional digest candidate coerced five falsy JSON values to `[]`; the idempotent writer accepted pretty-printed bytes that its reader rejected | independent review, then seven failing regression cases before the production fix | no provider spend; digest verification accepted altered field bytes and publication could report success over unreadable receipts | exact absent-or-empty-list compatibility and shared read-back validation implemented; 188 focused checks pass |

## 2026-09-11 — tooling: review checks and registration merges did not converge automatically

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| INF-T-01 | approval left older failed/cancelled `kernel-review` instances on the same head; partial workflow reruns could preserve the block | #176 operator report and workflow inspection | manual full reruns and delayed merges | automatic full-workflow repair implemented with current-head approval checks and a three-attempt limit; deployment pending |
| INF-T-02 | merge-time registration checks were prose and duplicate-binding checks omitted imports | #178; AST inventory found redundant imports in the scoring-contract and receipt tests | repeated manual scripts and risk of silently dropping enrollment | shared structural checker and import-aware regression guard implemented; focused validation passes |
| INF-T-03 | the new return checker initially treated a bridge's `pytest.skip` exception path as a missing return | running the checker against the existing scoring-contract file | one false-positive local check; no source or evidence loss | known non-returning pytest calls recognized and covered by a regression |

## 2026-09-12 — operational: the evidence index still described the pre-move layout

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| EVID-O-01 | after 59 campaign directories moved under benchmark families, the evidence README still listed the old flat paths and the layout guide still prescribed them; the 17 frozen-path exceptions had no grouped index | compared the live working branch with `main@13935585`, then checked tracked paths and frozen references | misleading navigation and uncertainty about which paths could move | benchmark index covers all 76 directories and labels all 17 preserved paths; canonical layout and documentation entry point updated; 91 links and anchors checked, all 35 existing campaign descriptions retained, all 540 published files byte-identical, and 7 layout tests pass |

## 2026-09-19 — data-center Gate 0: the profile the family never had, and what writing it found

Writing `docs/families/datacenter/qc.md` was the detection method for every row
below. All six data-center family ids had sat on the Gate 0 exemption list since
2026-09-08, so 30 published campaigns ran with no artifact that could hold a
gate verdict. The family never over-claimed — all 33 contracts in `configs/`
declare a diagnostic, exploratory or reliability-only `claim_status` and every
README denies a winner or a causal effect — which is exactly how a failed
construct gate stayed invisible.

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| DC-D-01 | the declared comparison baseline is dominated by the outside option. `cases/datacenter_development_v1/v2/full_stack_amendment_001.json` carries `baseline.developer_equity_npv_cents = -155000` against `outside_option.developer_equity_npv_cents = -100000`, so refusing to negotiate beats the scripted-developer reference by 55,000 cents. `validate_payload` re-simulates the baseline and accepts it (`environment.py:292-304`, `stack_environment.py:365-373`); the strict-dominance precondition exists only in the 2.1.0 objective scorer (`objective_measurement.py:198-199`), and the 1.0.0/1.1.0/2.0.0 identities are scored by `DataCenterDevelopmentScorer` (`measurement.py:131`), which has none | writing the Gate 3 section of the new profile, then reading the case payloads against the interaction campaign's group means | `datacenter_development_v2_interaction_v1` is affected: all four model-by-condition groups scored exactly `-100000.0` with `project_completion_rate 0.0`, which was read as a completion floor when it is also the reference failing. No published number is wrong; the interpretation that a subject negotiated well is unavailable, and was never claimed | partially closed 2026-09-19: an opt-in `construct_controls` guard in `stack_environment.validate_payload` (strict dominance by a declared margin, two-sided price bands), mutation-verified against the sealed `001` payload, and a repaired case `full_stack_amendment_002` whose floor-negotiating reference scores -72,000 against -100,000; the sealed case is unchanged. The scored walk-away and adopt-every-counter controls landed 2026-09-20 (`datacenter_v2_scored_controls_v1`, #193): the reference beats both on the curated case and on all 24 worlds. Still open: the guard on the 1.0.0/1.1.0 identities, and the sealed `001` case, which keeps its dominated reference |
| DC-D-02 | no informativeness admission exists for any data-center world: no trivial/floored/saturated classification, no measured control rate, no within-world variance report — the counterpart to procurement's `headroom_screen.classify_world` was never built. Fifteen of fifteen counteroffer cases pin the same world (`world_seed 312101`, `base_case_sha256 3e487d62…5139`), and integrated V5 recorded all six model-by-project groups repeating exactly across seeds, so seeds are repeats and the effective sample size is the cluster count | the Gate 1 audit for the profile | 19 of 30 published bundles have an independent-cluster count of 1 and none exceeds 5; no published bundle supports a cluster-level interval | open; `task_distribution_admission=failed` until 2026-09-19, `partial` since the world packs (#192, #197): every world is refused at generation unless a naive strategy fails it, and the holdout is split from the pilot pack by seed domain. Still owed: near-duplicate clustering across strata and a measured control rate per world |
| DC-D-03 | for the adoption, salience, affordance and action-schema ids the scored optimum *is* copying the counterparty: the primary leaf's `required_behavior` is to copy each complete written counter package exactly (`adoption_measurement.py:93-110`). Defensible as a contract-compliance instrument, but no test asserts that adopting the counter is suboptimal, so the instrument cannot separate negotiation quality from transcription | the Gate 3 audit | none directly; it bounds what four of the six ids can measure | open, by design for now; recorded in the profile's construct limits so it is not mistaken for a negotiation measurement |
| DC-D-04 | the score cannot tell a careless bidder from a careful negotiator. Live probes on the sealed V2 case, 2026-09-19: Gemini 3.8 Flash (3 seeds, $0.17) opened every agreement bidding against itself — 300,000 / 100,000 / 200,000 for land quoted at 20,000, interconnection 50,000 against 20,000, demand charge 100-150 against 5 — was countered only because an unrelated field breached a ceiling, copied the counter verbatim and scored exactly the reference, -155,000; GPT-6 Astra (3 seeds, $0.93) bid 700,000-800,000 for the same land, made the only downward price probe of either model (interconnection 10,000) but bundled it with out-of-band fields, demanded 300-350 c/kW-mo from a customer capped at 100, never conceded, stranded the project and scored the outside option, -100,000. Re-simulation: the land policy has a floor and no ceiling, so a 300,000 bid with the other fields in band is accepted and scores -435,000 | reading the sealed event ledgers action by action against the counterparty quotes | $1.10; no published number affected. The finding is a model one and the case exposed it, but nothing in the score records it | open as a measurement gap; the two-sided bands in `full_stack_amendment_002` close the overpay and lowball holes, and the scored walk-away / adopt-every-counter controls that make self-bidding visible landed 2026-09-20 (#193); what remains is that the sealed `001` case and every bundle read against it keep the one-sided bands |
| DC-D-05 | a live land amendment was stamped with the *scripted* developer's `amended_fields` instead of the fields it actually changed (`stack_environment._make_offer`), so an amendment that changed a different set of fields — including one that changed nothing — passed the landowner and crashed at commit (`apply_executed_amendment`: "amended_fields must exactly match the changed structured terms"), booked as `family_execution_failure` / `environment_failure` and excluded. Same defect the world-panel branch fixed on 2026-09-05 ("live amendments crashed at commit unless they changed exactly the scripted land_amendment_fields") and never merged | the Gemini 3.8 Flash probe on `full_stack_amendment_002`, seed 31212: it re-proposed the executed land terms with expiry unchanged at 3 as its amendment; 1 of 3 cells | one excluded cell whose provider spend is unreported (the failure branch records `usage: None`), and a model's mistake booked as environment missingness, against the register's own rule that anything a model can trigger is the model's | fixed 2026-09-19 with the case repair: amended fields are derived from the diff against the executed land agreement, and a re-proposal that changes nothing is the developer's typed invalid action (`amendment_changes_nothing`) rather than a crash; the scripted path's amendment is unchanged so sealed receipts do not move. Two tests, one of which drives the no-op through `step` to the outside option |
| DC-D-06 | `cashflow.py` counted the maturity balloon in debt-service coverage, so every realistic bullet facility breached its DSCR covenant in its final month purely because principal came due; on the toy curated cases the bullet was the only service month, which is why the goldens read a coverage of 9,000 bps where none is measurable. Found on the world-panel branch 2026-09-05 (a 24-world pack could not draw a single feasible world with the balloon counted) and never merged | porting the world generator: with main's `cashflow.py` no `revenue_without_bankability` variant is feasible; with the branch's, all 24 are | no published number affected (every sealed case's baseline re-simulates unchanged); the family's calibrated worlds were unauthorable on main | fixed with the world pack: coverage is measured on scheduled service only, the bullet is refinancing risk tested by `maturity_nonpayment`; goldens corrected and a regression added (`test_a_bullet_repayment_at_maturity_is_not_a_coverage_breach`) |
| DC-D-07 | the closed developer output schema said `integer` where the contract parser says `>= 1`, so a model could emit a value the environment would refuse; nothing told it months are numbered from 1. In the first Gemini variance pilot on the world pack, 5 of the first 10 cells died at their first action on `site_control_start_month: 0`, scored at the outside option for $0.0015 each, measuring the indexing convention rather than negotiation | reading the first pilot cell's raw output and re-parsing it locally (`ContractValidationError: site_control_start_month must be an integer >= 1`) | five cells of a 48-cell pilot spent on a schema gap; typed as the model's error under the register's rule, which is correct and still a harness defect | fixed 2026-09-19 for cases that opt into `construct_controls`: every parser minimum is carried into the strict schema (`TERM_MINIMUMS`, non-negative otherwise) and a v2 developer prompt says months start at 1; sealed cases keep their v1 schema and prompt byte for byte. The pilot ran to completion on the v1 contract and is reported as run; the confirmatory uses a new campaign identity |
| DC-D-08 | the developer offer schema allows `{"decision": "walk", "message": <string>, "terms": null}`, but the parser accepts a walk only when `message` is null, so a walk that states its reason is typed `malformed_datacenter_stack_action` and scored as an invalid action. Six of the pilot's 21 "malformed" cells and the first two of the confirmatory's were walks with a reason — one of them Gemini reading that the lender's required credit support (7.4 billion cents) exceeded the executed service agreement's (6.29 billion) and calling the project unbankable, which is exactly the cross-agreement read the family exists to measure, thrown away as a format error | re-parsing the raw model output of every malformed cell in both runs while the confirmatory was running | 8 cells across two runs booked as the model's format error when the model's decision was legal and, in at least one case, right; the confirmatory's admission rate is biased down by every such cell | open: recorded under the frozen confirmatory, which runs and is reported as run. The parser change (a walk may carry a message; the reason enters the public history) is a harness change and lands in the next campaign identity, not under this one. Same class as DC-D-07: the schema the model sees and the rule the environment enforces disagreed. Read from the run root 2026-09-20: 6 of the 12 are declines of the amendment phrased as a walk (DC-D-10), and 6 are reasoned refusals at the loan, five because the lender's minimum customer credit support (its floor, equal to its counter) exceeds the credit support the model had already signed with the customer, one because the written 30% advance rate cannot fund the project. Those six score the outside option under either typing; their mistake was upstream, signing the customer's counter on credit support without the lender's floor in view, and the typing hides that read as a format error. Fixed for cases that opt into `construct_controls.developer_interface: 3` (stack_environment.parse_action): a walk may carry its reason and the reason enters the public history; interface-2 cases keep refusing it, so no sealed receipt moves |
| DC-O-01 | first variance pilot on the world pack (`datacenter_development_v2_world_panel_v1`, Gemini 3.8 Flash, 24 worlds x 2 seeds): 47 of 48 cells completed, 1 `timeout`; of the 47, 7 admitted, 40 excluded — 21 `malformed_datacenter_stack_action` and 2 `malformed_json` (the DC-D-07 schema gap, 48% of the panel), 7 `amendment_changes_nothing`, 8 `unfinanced` and 2 `funding_shortfall` (completed stacks the lender will not fund: the trap working). Two strata admitted nothing (liability_transfer 0/8, verbal_written_divergence 0/8). Admitted cells land at the scripted reference (median −0.03B on ~50B references; 3 of 7 above it). Only 4 of 24 worlds completed on both seeds; where both did, the seed difference was 2.6B median, 3.8B max | the campaign's own summary and a per-world read of the sealed results | $2.52 lower bound; the pilot measures the schema gap more than negotiation, which is what a pilot is for | recorded as run and published unchanged; the confirmatory uses a new campaign identity with the bounded schema and v2 prompt (#195), sized on 24 worlds |
| DC-O-02 | the first confirmatory on the held-out pack (`datacenter_development_v2_world_panel_confirmatory_v1`, Gemini 3.8 Flash, 24 worlds x 3 seeds, bounded schema and v2 prompt, frozen before any outcome): 72 of 72 cells completed, 0 operational failures, $5.34 exact. Admitted 18 of 72; world-level admission 0.25 (95% world-clustered bootstrap 0.15-0.35); 14 of 24 worlds admitted on at least one seed, none on all three. Excluded: 21 completed stacks the lender would not fund, 16 no-op amendments, 12 walks with a stated reason typed malformed (DC-D-08), 5 non-JSON outputs. Admitted cells sit 2.2 billion cents below the scripted reference on average (95% -2.9 to -1.5 billion), 3 of 18 above it. Verbal/written divergence admitted 0 of 12, revenue-without-bankability 1 of 12 | the sealed summary and a per-world read of every result | $5.34; the admission rate is biased down by the 12 DC-D-08 cells and the 16 no-op amendments, both harness gaps the next identity closes | published as run with the predeclared analysis sealed into the bundle; Gate 5 `passed` for this campaign track, family normative status still `partial` (one route, descriptive, no random control, near-duplicate clustering still owed) |

### T — Tooling and process failures

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| DC-T-01 | published replay is a copied boolean, not a recomputation. Campaigns compute `replay_verified` at run time and publishers copy it into the sealed bundle (`adoption_publication.py:204`, `public_publication.py:145`, and siblings); the publication tests assert the flag. Across 30 bundles and 531 sealed rows nothing re-drives a published row through the environment and recomputes its score, which procurement's regret decomposition does to $0.000001 | the Gate 2 audit | the family's replay claim over 531 rows rests on a flag written by the same run that produced the row | open. Named as the main Gate 2 blocker |
| DC-T-02 | `datacenter_development_terms_public_integrated_v12` has no committed bundle under `evidence/`, and both of its publication tests are gated on a gitignored `runs/` directory by the `local_run` marker (`tests/conftest.py:31-50`), so on a clean checkout that campaign's publication is verified by nothing. The other 14 `local_run`-gated data-center tests each guard a bundle a second ungated test also checks | running the data-center suite from a clean worktree at `main@9aa11a2d` (616 passed, 47 skipped) and mapping every skip to its required run root | one campaign's publisher is unverified in CI | open. Either commit the bundle or delete the campaign's publisher and tests |
| DC-T-03 | the consolidated index claimed a Tier 1 register at `evidence/datacenter_failure_register.{json,md}`, marked *to be moved*. That path is not on `main`; the register in the standard layout exists only on the unmerged branch `codex/datacenter-world-panel-v1`, and its counts (766 incidents, 19 defects) differ from the indexed 541 | checking the index row while writing the profile's register section | an auditor following the index found nothing | index row corrected to state that no data-center Tier 1 register is on `main`; the register still lands with that branch |
| DC-T-04 | in the kernel trajectory grain of the world-panel pilot, the two seed cells of each world share `cell_id`, `episode_id` and `episode_attempt_id` (24 distinct each for 48 receipts) while `run_plan_id` is distinct (48): the inference seed lives in the run plan, not in the cell or episode identity, so a downstream join on `episode_id` alone silently merges two seeds of one world | counting distinct identities in `trajectories/sanitized.jsonl` while verifying the bundle for review | none yet; the rows carry `run_plan_id` and `source_receipt_sha256`, so the unique key is `(run_plan_id, cell_id, episode_attempt_id)` | open. Whether the kernel should fold the seed into the episode identity is a kernel ruling; until then every grain consumer keys on the run plan |
| DC-T-05 | the world-panel design digest depends on the interpreter: `worst_case_declared_cost_usd` is a plain float `sum()` of the per-cell caps, and Python 3.12 changed `sum()` to compensated summation, so 72 x 0.20 is 14.39999999999998 on 3.10 and 14.4 on 3.13 and the sealed `artifact_sha256` differs by that one float. Every run-plan digest and every implementation pin is identical across interpreters | CI's 3.10 job failed the freeze test that the 3.13 local suite passed; reproduced by building the design under both | the frozen design's digest cannot be re-derived on CI; no cell, receipt or number is affected | recorded; the freeze record now pins the 72 run-plan digests explicitly and names the interpreter that sealed the design. Fixed for contracts at schema `aeread.datacenter_world_campaign_contract/0.2`: the design's worst-case cost is summed in integer cents (`_declared_maximum`); 0.1 contracts keep the float sum so their sealed designs still reproduce |

### J — Judgment failures

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| DC-J-01 | the first GPT-6 Astra probe sealed `canonical_model` as the bare slug `openai/gpt-6-astra`; the OpenRouter route pin compares the selected endpoint against the sealed revision and rejected all three cells (`provider_contract`, "selected endpoint model does not match the sealed revision") | the harness, before any billable call; three receipts sealed as typed missingness | $0; six seconds per cell | corrected by sealing OpenRouter's dated `canonical_slug` (`openai/gpt-6-astra-20260903`, as `google/gemini-3.8-flash-20260902` had been) under a new probe identity; the rejected run root is kept. Lesson recorded: the pin wants the dated slug, never the alias |
| DC-D-09 | the adopt-every-counter control cannot reach the loan for a reason that has nothing to do with transcription: it opens the land amendment with no conditions precedent, the scripted landowner refuses with a message and no counter-terms ("We cannot sign this. We need conditions precedent covering zoning_approval."), and the control, with nothing to copy, walks. Re-run offline on 2026-09-20 it walks at `land_amendment_developer_offer` on 24 of 24 holdout worlds, and the sealed `worlds_v2` terminations are all `developer_walk`. `datacenter_v2_scored_controls_v1` therefore shows that this control fails admission, not that transcribing priced counters fails it; in the confirmatory the 18 admitted cells signed the counterparty's counter verbatim on 18/18 land, 18/18 service, 11/18 power and 11/18 EPC agreements, so admission was reached mostly by transcription plus one coherent amendment | re-reading the control's trajectory while interpreting the confirmatory | the profile's sentence "every guarded quantity has its failing counterexample" over-read the control and is withdrawn in this row's PR. What separates transcription from negotiation on this pack is cross-agreement consistency: copying the utility's 40 MW counter fails `power_capacity_covers_lease` in the 14 worlds where the utility counters short (15 of the 21 unfinanced stacks carry 40 MW against a 50 MW lease), and copying the lender's written 30% advance rate fails funding in the 4 verbal-written-divergence worlds (8 of 12 cells) | corrected on re-reading the trace: the landowner's amendment counter is not bare, it is the executed land agreement itself (`counter_terms` volunteer no extension), so what the adopter lacks is not terms but a way to say no — the same gap as DC-D-10. Under `developer_interface: 3` the control declines the amendment instead of walking and goes on to copy the lender's counter (`StackScriptedDeveloperProvider`); on the 24 interface-3 worlds it executes every stack and is funded on none (`datacenter_v2_interface3_scored_controls_v1`), against the prediction in this row's first disposition that it would pass on the 6 worlds without a capacity or verbal-written trap: on every world the declined amendment leaves site control expiring before operations (`site_control_holds_through_operations` fails 24 of 24, because the landowner's counter volunteers no extension and the amendment is the lever that buys one), 15 also carry the 40 MW power counter and 4 a funding shortfall. The separation between transcription and negotiation is therefore admission, on every world, and a decline is not free: it costs the extension the reference negotiates. `datacenter_v2_scored_controls_v1` is regenerated under the edited engine (only `run_plan_sha256` moved, every NPV identical); the interface-3 controls bundle lands with the interface-3 packs |
| DC-D-10 | the land-amendment phase has no way to decline: the developer must propose an amendment, a proposal identical to the executed terms is the typed invalid action `amendment_changes_nothing` (DC-D-05), and a walk ends the project. In the confirmatory 22 of 72 cells died there after signing all four agreements: 16 re-proposals whose messages all read "reaffirming executed land terms", and 6 walks whose stated reason was "no amendment needed" (typed malformed under DC-D-08). Against the lender's own counter-terms 12 of the 22 stacks pass every static cross-agreement check, so admission is biased down by up to 12 of 72: measured 0.25, upper bound 0.42 | reading the 22 messages from the local run root while interpreting the confirmatory | the confirmatory's "biased down by DC-D-08" attributes the bias to the wrong row: the 6 DC-D-08 walks at the loan are reasoned refusals that score the outside option under either typing, and the bias is this row. The sealed README and analysis keep that sentence until an erratum can be sealed (#117) | fixed for cases that opt into `construct_controls.developer_interface: 3`: `{"decision": "decline", "message": <reason or null>, "terms": null}` in the land-amendment phase keeps the executed land agreement as signed and proceeds to the loan (the phase graph declares the successor, the outcome scores the land as signed, `declined_agreements` names it), the v3 prompt says so, and the strict schema lists it for that phase only. Interface-2 cases keep the no-op as their typed invalid action. Measured by the next identity (DC-O-04): with a decline available the developer declines in 66 of 72 cells and site control then expires before commercial operation in 46 of 49 unfunded stacks; admission 0.208 against the first confirmatory's 0.25 (different packs, descriptive). The 0.42 was an upper bound on stacks whose site control covered COD, which the developer does not secure |
| DC-T-06 | the confirmatory freeze test compared the frozen run-plan digests and driver digest to a design rebuilt from the current source (`test_confirmatory_contract_freezes_on_the_holdout`), and a run plan pins the family implementation by digest, so the first family edit after the run failed the test: the freeze had been made to forbid any change to the family after a confirmatory, which is not what a freeze is for | the interface-3 PR, on its first test run | none beyond the rerun | fixed: the freeze is compared to the published design inside the sealed bundle (the record of execution), and the fresh design only to what does not depend on the source — pack, contract, cell count, cost within a cent |
| DC-T-07 | the first confirmatory's freeze record and its sealed analysis (`reports/confirmatory_analysis.json`) were written by session heredocs that never reached the repository; the analysis was even sealed twice within a minute by two scripts whose bootstraps differed (a fresh stream for the delta interval, then one stream shared with the admission interval), and only the second is what was published. Nothing in the tree could regenerate either | porting the scripts for the second confirmatory | none to the numbers: `confirmatory.py` reproduces the sealed analysis byte for byte (given the run root for the one v1-only split of parser rejections into walks-with-reason) and the freeze's pins from the published design; the shared-stream bootstrap is now the declared procedure | fixed: `aeread_families.datacenter_development.confirmatory` (`freeze_record`, `write_freeze`, `analyze`, `seal_analysis`) with tests against the sealed v1 artifacts; every later freeze and analysis runs through it |
| DC-O-03 | the interface-3 pilot (`datacenter_development_v2_world_panel_interface3_pilot_v1`, 24 worlds x 2 seeds, Gemini 3.8 Flash) lost its network mid-run: world 16 seed 41212 timed out after 198 s, and every cell from world 17 to 23 — 14 cells, the last seven worlds — then failed in 0 s as `transport`, one after another, while the driver kept walking the design. 33 of 48 cells completed on the first pass ($2.19), 15 operational failures, 31% of planned cells: over the 10% ceiling a confirmatory would have carried. The wrong hypothesis while it ran: nothing, the run was unattended overnight | reading the design summary after the process exited at 07:44Z | 14 cells re-executed as further attempts (`--retry-failed`, prior attempts archived on the record), about $0.75; no cell was rerun in place | the pilot is published with every attempt visible; the confirmatory that follows runs attended, and the driver gains a stop rule (DC-T-08) |
| DC-T-08 | the world-panel driver has no stop rule for consecutive operational failures: after the network dropped it executed 14 cells in a row that each failed in 0 s as `transport`, exhausting the design instead of halting. Every limit that can terminate a run is meant to live in the contract, and this one lives nowhere | the same outage | 14 wasted cells and an unattended run that reported 31% missingness as if it were the model's | open: the next contract schema adds `max_consecutive_operational_failures` to the execution block and the driver halts, records the halt as typed missingness for the untouched cells, and exits non-zero |
| DC-O-04 | the second confirmatory (`datacenter_development_v2_world_panel_interface3_confirmatory_v1`, 24 fresh held-out worlds x 3 seeds, Gemini 3.8 Flash, developer interface 3, frozen before any cell ran): 72 of 72 completed, 0 operational failures, $5.26 exact, run attended with an external guard for consecutive transport failures (DC-T-08). Harness check passed: 0 amendment-phase exclusions. Admitted 15 of 72; world-level admission 0.208 (95% world-clustered bootstrap 0.111-0.306); 11 of 24 worlds on at least one seed, none on all three. 66 of 72 cells declined the amendment; of the 49 unfunded stacks, site control expired before commercial operation in 46, 17 carried the 40 MW power counter, 10 a funding shortfall. Five walks stated a reason, four refusing a written 20-30% advance rate the lender's message had disavowed. Admitted cells sit 0.61 billion cents below the scripted reference on average (95% -1.44 to +0.06), 8 of 15 above it, 12 of the 15 admitted after a decline that happened to leave site control long enough | the sealed analysis, `confirmatory.analyze` | none: published as run | published with the predeclared analysis sealed in; Gate 5 `passed` for this track as for the first; family normative status still `partial`. Descriptive against the first confirmatory (0.25 on another pack under interface 2): the interface gap is closed and admission did not rise, because the developer declines the amendment that would carry site control through operation |
| DC-J-02 | the confirmatory was frozen with the amendment gap in place because the pilot's signal was misread: 7 of the pilot's 48 cells (15%) ended in `amendment_changes_nothing`, and that was recorded as model behaviour (a no-op re-proposal typed as the developer's invalid action, DC-D-05) rather than as a missing affordance in the phase. The confirmatory then lost 22 of 72 cells to the same gap. The wrong hypothesis at the time: "the model re-proposes because it does not understand amendments"; the messages say it understood exactly and had no way to say so | reading the 16 no-op messages after the confirmatory | one paid confirmatory ($5.34) whose primary endpoint has a 17-point harness ceiling gap (measured 0.25, bound 0.42), published as run and not withdrawn | recorded; the rule it adds to the profile: when a pilot's exclusion category is a typed *developer* invalid action that a scripted policy never triggers, read the messages before freezing, because the category may be an affordance the interface lacks |

## 2026-09-22 — tooling: the evidence examiner and a Jev agency probe

`tools/examiner/` reads every published bundle and the sealed logs behind
them; `docs/research/jev_trajectory_triage_2026-09-22.md` reports the probe.
Both were built in one agent session. The examiner was published as a private
artifact before this entry, so its defects reached a reader.

### D — Design defects

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| EX-D-01 | every model comparison the examiner showed was one number per case, pooled over the strata the design fixes before a model acts (world type, seat, reasoning arm, the model on the other side, market difficulty), and only four pairs had a comparison panel while the catalogue holds 46 comparison sets in which two or more models played the same worlds. A reader could not see whether a direction held inside each stratum, and in one case it does not: in risk allocation v2 GLM has more regret than Gemini in three seat-by-arm strata and less in the fourth (integrator, default reasoning) | the owner, 2026-09-26, reading the lemons and procurement panels: "right now I just see results on the aggregate level" | no published number was wrong; the pooled panels answered a coarser question than the cases were built to ask, and a tally across cases could only be assembled by hand | fixed in 93c82048: `build_model_comparisons.py` and the page's "model comparisons" view (artifact v63) compute every multi-model case by stratum (matched seeds, equal weight per world, cluster bootstrap from 5 clusters up), name each stratum, and list the cases that cannot be compared with the reason. It reproduces the published procurement O1/O2 and lemons figures and risk allocation v2's complete arms exactly. Where GLM has missing cells its per-world weighting differs from the family's per-pair mean: risk allocation v2 integrator-default reads GLM − Gemini −27.1 [−63.1, −1.0] there against the published −26.9 [−70.4, +0.1], so that one stratum's verdict depends on the weighting |
| EX-D-02 | the results page (a run's "Open charts") grouped each published table by default by the first text column with 2 to 12 values when no design column was present, and in 67 of 698 tables (48 runs) that column was an outcome the run produced (`decision`, `status`, `feasible`, `passed`, `complete_pair`, `inclusion_status`). The procurement holdout opened as "award n=58 / failed n=2" on contribution margin: a split by what happened, which each model controls, drawn like a comparison | the owner, 2026-09-26, from a phone screenshot of that chart, minutes after I had told them no chart on the page compared award cells with failed cells; that claim was wrong and is corrected here | a reader could take the award/failed gap for a finding; the same selection problem O2 has (the owner questioned it the same hour), shown by default and without a caption | fixed in a31ef32f: outcome and identity columns are never the default grouping (the default is a design column or none), stay selectable labelled "an outcome, not a stratum", and carry a banner saying what such a grouping shows; artifact v64 |
| EX-D-03 | the gap breakdown ("Why they differ") drew every gap report pooled over the strata its cells carry, and counted its decision classes the same way: the procurement holdout's 33.2 gap was one waterfall over six world types whose own gaps run from 12.5 (retaliation trap) to 56.4 (demand ramp), and its "periods lost" part is 0 in retaliation trap and 31 to 33 in three others. EX-D-01 fixed the model comparison and left this view pooled, and I pointed the owner to this breakdown as the right tool without saying it pools | the owner, 2026-09-26, from a screenshot of the holdout's Why they differ tab: "is this still comparing aggregated across diff strata" | the per-stratum structure of every gap report with strata (procurement, lemons, refund, datacenter risk allocation and world panel) was invisible outside the per-world click-through | fixed in a3cbae6e: a parts-by-stratum table under the waterfall, a selector that redraws the waterfall for one stratum, and the click-through and class counts follow it; artifact v68 |
| EX-D-04 | the by-stratum model comparison split every declared dimension into rows, the reasoning arm included, so all 29 rows of the full-terms v2 comparison (`datacenter_risk_allocation_contracts_dev_campaign_v2`) opened with "Arm: low reasoning effort", the only arm both models ran, and the arm GLM did not run (default reasoning, not seated: DC-O-14) appeared only in a "Not compared" banner. An arm is a condition the campaign sets on the model, not a stratum of worlds; the other three risk-allocation cases that declare one (one-sided v1 and v2, menu v1) split the same way | the owner, 2026-09-26, from a screenshot of the full-terms v2 Model comparison tab: "should put reasoning control as a drawdown, most of them are the same now" | one repeated line on every row of four cases, and the one-sided v1 table three times as long as its strata | fixed in d3b73de2: an `arm` dimension (or any a build marks `pick`) is a menu at the head of the split row; arms both models ran are choices, an arm only one ran is listed greyed with who ran it, and "all N run by both, pooled" is offered where two or more are shared; the rows, pooled row, chart title and the run page's key chart follow it; artifact v76 |
| EX-D-05 | strata and baselines appeared on every page as bare labels ("favourite lemon", `close_now`, `covenant_cliff`, "denial due", "scripted inspect-then-sign reference", "oracle") with nothing on the page saying what world, case or policy each one is; the definitions lived in generator docstrings, case docs and gap-analysis modules on eight branches. No table could be sorted. While building the fix I read the full-terms pack's world types off a listing that stopped at eight values and missed three (`sign_now`, `take_the_cap`, `walk_away`); the first lookup then fell back to the one-seat pack's `walk_away`, a different world, for the full-terms runs, caught by a used-by count (5 runs where its siblings had 3) before anything was published | the owner, 2026-09-26, from a screenshot of the lemons case table: "all tables should be sortable; also i think we need a place we can easily check what's each strata and baselines those are just a label now" | a reader could not check what a stratum or a reference is without opening the repository; a same-named world type in another pack would have been misdefined silently | fixed: `tools/examiner/definitions.json` holds 126 definitions (91 strata, 35 baselines) of every stratum value and baseline label the visible runs use (290 lookups, none missing; model names excepted), each with a verbatim quote that `build_definitions.py` finds at the branch's pushed commit or stops; entries carry the runs they apply to and a pack scope, and a scoped entry never answers for another run. The page underlines defined labels (hover, click for the quote), lists each run's strata and baselines under its key charts and all of them under "strata & baselines"; every table sorts by any column |
| EX-D-06 | every sealed risk-allocation cell (60 per bundle across the six risk-allocation bundles) fell back to the generic case card: part 3 said "No reference is published for this case" and the score line "not in the sealed log", though each cell's outcome carries the grader's full grade (every move with its regret, the best contract, the realised cost and cost over best attainable), and nothing on the examiner let a reader check a full-terms cell against the solver that graded it | the owner, 2026-09-26, from a screenshot of full-terms cell `02998b5f`: "also need case card for this", and of the contract builder artifact: "can you put this to data center case for checking" | a reader could not see why a cell scored what it scored, or tell a grading defect from a model's | fixed in 15d64ccd: a `risk_allocation` card adapter (the grade's moves are the rubric, outcome rows diagnose, the score line separates decision regret from cost over best attainable; two-sided cells show joint value lost), and the contract builder inside the examiner (`build_contract_builder.py`, rebuild step 6f; a "Contract builder" tab on the full-terms runs, linked from each card) that recomputes a cell's realised cost, cost over best attainable and its split beside the grader's: at build time all 696 graded cells of full-terms v2 and all 482 of v1 reproduce; artifact v78 |
| EX-D-07 | the model comparison drew each stratum's paired difference with each world's seeds averaged away, so the reason full-terms v2 cannot separate GLM from Gemini at low effort appeared nowhere on the page: one model's two seeds on the same world differ by a median 124.7 (GLM) and 38.8 (Gemini), seed-to-seed correlation 0.18 and 0.37 (DC-D-29) | the owner, 2026-09-26, after being told the gap is mostly seed noise: "so we need intra strata diff seed result distribution charts, drop down to select strata/effort/model" | a null read as "the models are alike" when it is "each model is noisy" | fixed in a2af5687: "Seed to seed, within a stratum" under every case's stratum chart: every world of the chosen stratum as a row with a dot per seed for the chosen effort and model (menus for each declared stratum, the arm and the model), and each series' median gap between two seeds and seed-to-seed correlation beside the models' gap on the same worlds; artifact v78 |
| EX-D-08 | The noise line under every split (ae77b0ae, v79) said it tests whether "the world-level differences between strata" exceed shuffled labels, without saying differences of what or that it is an average. It asks one thing: whether the gap the table compares shifts between strata on average over the worlds. A stratum that moves both sides' scores, or moves the gap one way in some worlds and the other way in others, reads "within noise". The Housing confirmatory shows it: the opponent's tests read within noise (gap p = 0.21 and 0.22, level p = 0.13 and 0.43, tenant and landlord views, unchanged with difficulty held fixed per case), while the Housing estimand diagnostic (D-27) finds the opponent explains 56.4% of within-case variance at p = 0.003. Both are right: per case the opponent moves the within-case score by 0.08 on average, with the sign split 51 to 39 over the 90 cases, so the average shift is +0.034 | checking the trim audit's opponent verdict against the estimand diagnostic before stating it; I had drafted "the opponent has no effect anywhere" | none published; a reader of v79 could take "within noise" for "does not matter" | fixed in the commit that adds this row (artifact v80): the box says the test asks whether the gap changes between strata on average, and that a stratum moving the scores, or the gap in opposite directions, reads within noise |

### T — Tooling and process failures

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| EX-T-01 | the examiner's construct-validity checklist counted only incident rows that name a bundle's identity, so `datacenter_development_v2_world_panel_interface3_confirmatory_v1` (run 17 of 17 in its family) showed no open issue while the family's open rows applied to it (DC-D-02, which caps what the confirmatory may claim, and DC-T-04) | a person compared the checklist with the incident panel on the same page and asked why the gate found nothing | an incorrect "no issue" shown on a published (private) examiner page | fixed before commit: open family-level rows appear on every bundle of the family as red checklist lines |
| EX-T-02 | the lens builder grouped sealed receipts by `(cell_id, episode_attempt_id)`, which the world panels share across their three inference seeds (the shape DC-T-04 records), so one case stood for three receipts | a person asked, on a screenshot, whether the listed cases were different worlds | world-panel case lists showed one case per world instead of one per receipt | fixed before commit: one case per receipt, routed by receipt digest, with world-seed and inference-seed columns |
| EX-T-03 | the checklist states a verdict without showing what it rests on, and its rules read only a fixed set of top-level report keys, so a bundle that states a fact under another name reads "not stated": `housing_confirmatory_parasail_v2` shows "not stated" for cell accounting and cost while its `reports/qualification.json` carries `acceptance.all_frozen_cells_attempted = true`, `acceptance.typed_missingness_preserved = true` and a `cost_note`; the same bundle's "no" on the claim boundary reads the freeze's top-level `winner_claim_allowed = true` and not its `execution.winner_claim_allowed = false` | an analysis reader said the checklist lacked support; reading the bundle's reports against the screenshot found the unread keys | checklist states on a published (private) examiner page that a reader could not check; across the 120 bundles, 182 of the 279 "not stated" lines (in 104 bundles) sit beside statements on the same subject under keys the rule does not read (cost 59, cell accounting 52, replay 45), so some of them understate the bundle; how many needs a reading per line | open: each checklist line now opens a page with the rule branch that decided it, the values it read with file digests, the QC standard's passage, and every related statement the rule does not read, and a "not stated" line with related statements says so; no state was changed; whether the rules should read these keys is a decision for the owner |
| EX-T-04 | the QC-profile check split the profile into sentences without removing fenced code or subheadings, so a shell block (or a `###` heading) was glued to the sentence after it and quoted as the profile's gate outcome: `housing_model_sensitivity_openrouter_friendli_v13` showed its "yes" as a `python -m ... backend_campaign` command line; the sentence that carries the verdict ("The executed gate passed.") was right, the quote was not | building the checklist detail page, which quotes the sentence in full | a shell command shown as QC support on a published (private) examiner page; no state was wrong in this case | fixed before commit: fenced code and heading lines are removed before sentences are split |
| EX-T-05 | the StarCraft import (`tools/examiner/build_starcraft.py`, 123f6443) called every step a "strategist decision", but tactical missions are chosen by Jev (`tactical_chooser`), not by the Codex or Claude strategist; and with no declared graph the page drew the phase graph from the time order of both seats' decisions, which reads as the control loop and is not it (the prototype's `CombinedRunner` runs, per seat, concession review → engagement posture → one macro lane's goal step on each strategic snapshot, with Jev's tactical and worker loop beside it) | the owner asked, on a screenshot of the graph, whether it was the agentic loop in use; reading `action_combined_runner.py` showed it was not, and showed the tactical chooser is Jev | a wrong attribution and a misleading graph on a published (private) examiner page, artifact v47, for about an hour | fixed before the next publish: tactical missions are attributed to Jev, the family carries a declared graph of the controller's loop with who decides each stage, and the summary no longer says "strategist decisions" |
| EX-T-06 | the rebuild of 2026-09-25 (to add the lemons v2 bundles) crashed in the lens step with `FileNotFoundError` on an `events.jsonl` under another session's scratch worktree (`/private/tmp/claude-501/.../scratchpad/v3-wt/runs/datacenter_development_v2_world_panel_interface3_pilot_v1/...`). The attempt directory still held its receipt and artifacts; its event log and seal were gone, removed at 00:00 by macOS's daily temporary-file cleaner, which deletes old files under /tmp. The damage was wider than the crash showed. The interface-3 pilot's run root keeps 15 of the 48 sealed attempts the published lens was built from, and the Datacenter world-panel confirmatory v1 keeps none of its 60: whole attempt directories, receipts included, are gone, so the receipt index no longer knew them and a rebuild quietly turned that bundle's lens from 60 sealed attempts into 60 published-only rows. Two unpublished Jev housing receipts (`/private/tmp/aeread-jev-housing-20260920`) lost their logs too. The first fix, keeping the old lens only when an indexed receipt had lost its log, missed the confirmatory for exactly that reason, and it also left the kept bundle's campaign file unthinned (1.3 MB instead of 0.18 MB); both were caught by diffing the rebuild's decoded content against the published build before publishing | the rebuild's traceback; then a decoded-content diff of the new build against the published one | none published; about 40 minutes. Sealed logs under /tmp are not durable: any run root kept only in a session's /tmp worktree loses its logs within days | fixed: attempts are replayed only from directories whose log exists, and a rebuild that can read fewer sealed attempts for a bundle than the previous build did keeps that build's lens, campaign file (thinned as before) and catalog step grain (`rebuild.sh` saves the previous catalog before step 3); the lens index entry states how many sealed attempts this machine still holds. Moving run roots out of /tmp is the owners' call |
| EX-T-07 | the examiner links an incident row to a run when the row's text contains any one token of the run's identity, so a common word hung rows on unrelated runs: `action` put the open row DC-O-12 (a GLM timeout in the risk-allocation campaign) on both `datacenter_counteroffer_action_schema` runs as "Open incident still applies to this design", `open` put HL-D-03 on `housing_open_harness_2026-08-31`, and `risk` put DC-D-06 (refinancing risk) on the risk-allocation campaign | 2026-09-25, diffing a rebuild's catalog against the live artifact before publishing: 8 older runs changed status with no change of their own | red checklist lines on runs the rows do not concern, published once (DC-D-06 on v52, closed, so background only) | partly fixed (the second commit after 0f170c3a): `action` and `open` no longer link from row text (`PROSE_WORDS`); section headings and rows naming the identity link as before. Open: a share-of-rows rule (drop any token used by one row in ten) was tried first and withdrawn before publishing, because it also removed dozens of links the owner may rely on (`world` alone linked 10 to 17 rows to each world-panel run, some of them open design rows); which of those are true is a ruling for the examiner's owner. `risk` still hangs the closed DC-D-06 on the risk-allocation runs |
| EX-T-08 | EX-T-07's open half recurred with the full-terms menu's incident rows: a single ordinary word in a new row linked it to older runs whose identity contains that word, 15 links in all. `world` hung DC-D-27 and DC-J-04 on the four world-panel runs, `schema` hung DC-T-19 on both counteroffer action-schema runs, `controls` hung DC-O-15 and DC-T-16 on both scored-controls runs (their open-row counts went 3 to 5), and `menu`/`contracts` hung DC-O-15, DC-T-18, DC-T-19 and the old DC-T-05 on the new risk-allocation runs they do not concern. Two narrower rules were measured on the 130-bundle catalog before publishing and neither is safe to adopt unasked: requiring two identity tokens when a run has two or more drops 289 links from 95 rows, and suppressing token links for any row that names some identity drops 65 links from 17 rows, both including links that look true | 2026-09-26, diffing the rebuild's catalog against the live v61 before publishing the menu and full-terms bundles | the 15 links publish with v62, each showing its reason ("its text contains `world`"); readers of those older runs see rows that are not about them | open: the rule is a ruling for the examiner's owner (EX-T-07). Until then a new row that concerns one run should name that run's identity, which links it by name |
| EX-T-09 | on a gap card, clicking a part of a model's breakdown against a scripted reference looked the reference up by the world's unit, but procurement relationship cells are keyed by world name (`demand_ramp_2430002`) and the published `reference_parts` by seed (`2430002`), so on every procurement gap report the click-through matched no world and said none contributed | found 2026-09-26 while splitting those charts by stratum, when the per-stratum reference tables came out empty ("all 0 strata") | a reader clicking a procurement reference part saw an empty list, which reads as "no world moves this part"; lemons and the other reports key both by seed and were unaffected | fixed in 15b842af: the lookup falls back to the world's seed; the pooled reference figures recomputed from cells now reproduce the published ones on procurement and lemons |
| EX-T-10 | the results page's interval-estimates chart grouped a bundle's published estimates by the last segment of their path, so estimates in different units shared one axis: the procurement holdout's pre-registered O1 breach-rate difference (0.133, 95% world-bootstrap 0.05 to 0.233) was drawn on the dollar axis of O2 (14.2, 9.0 to 19.2) as a dot at zero with no visible interval | the owner, 2026-09-26, from a screenshot: "what's the confidence interval here" | a pre-registered result whose interval excludes zero read as zero on the page; any bundle publishing several role-named estimates in different units was affected the same way | fixed in 4762017e: role-named estimates group under their outcome, one axis each, and difference axes include zero; artifact v70 |
| EX-T-11 | the results tab titled a published table only by its file and its JSON path, so a run with scripted controls showed five charts that differed by one path segment in the middle of a line (`...scripted_controls/scripted_accept_the_base.exploratory_by_playbook (keyed)` against `...scripted_cheapest_listed_price...`); two of them also carried the same bars, because in managed and coordination worlds the cheapest listed offer is the base or costs the same (DC-D-28), and nothing on the card said which strategy each was | 2026-09-26, the owner on the full-terms v2 results tab: "what's the diff, without title hard to tell" | every results tab with keyed tables since the tab existed; no number was wrong | fixed: each table card leads with a title read off its path (the arm and model or the scripted control, then what it breaks down, then the metric), whole-bundle tables named for what they hold; the file and path stay under it as the source |
| EX-T-12 | the results tab headed the published intervals "4 point estimates with a published interval" and labelled each by one path segment, so a reader took four contrasts, each pooled over dozens of worlds, for four data points; the build dropped the pairs and worlds the bundle states beside each interval, so nothing on the page said what an estimate pools. The same tab drew one chart per arm and per scripted control for each breakdown, nine near-identical charts in a row | 2026-09-26, the owner: "if pooled why call 4 point estimates or 3 point estimates", and asking for a dropdown to select between the look-alike charts | every results tab with published intervals since the tab existed; no number was wrong | fixed: the header says each is one number pooled over every world it covers; `build_results.py` carries the stated pairs, worlds and cells as `pooled` and each row shows them ("115 pairs, 58 worlds"); tables of one file whose paths differ in one segment are one chart with a picker for that segment, and bars keyed by an arm or control carry its readable name |

### J — Judgment failures

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| EX-J-01 | the rule labels written to score Jev were wrong twice: three datacenter receipts that ended on an invalid first developer action were scored "ignored the counter" though no counter existed; and lemons holds were aligned one round late, because a commit phase's `post_state.round_index` already carries the next round, so seven ordinary passes were read as refusals of a held offer and those seven states sent to Jev carried the following round's hold | Jev disagreed, and reading those trajectories showed the rule was wrong both times | none published; caught before any figure was reported | closed: both corrected in `tools/examiner/jev/`, and `jev_actions.py --truth-only` rebuilds the saved rule labels exactly (652 of 652) |
| EX-J-02 | EX-D-03 presented the procurement holdout gap by world type (12.5 in retaliation trap to 56.4 in demand ramp) as structure the pooled waterfall hid, and I pointed the owner to the by-stratum views as the way to read cases, without testing whether any stratum differs from another by more than world-to-world noise. With two worlds per type it does not: a permutation test of the stratum labels across worlds gives p = 0.64 for the holdout and 0.45 for dev2 (Gemini minus GLM regret); the curated packs, the six single-order worlds and the refund scenarios have one world per stratum, where stratum and world cannot be told apart at all. Across all 67 stratum splits on the model comparisons, 36 cannot be tested (one world per stratum or fewer than 5 clusters); of the 31 that can, 7 have p < 0.05 against 1.6 expected by chance and 4 survive Benjamini-Hochberg at q = 0.10: risk-allocation v2 by arm (Gemini ahead by 94.1 at low effort, 10.9 and not separated at default) and by world type (-155.8 in close now to +53.0 in shift the tail), the two-sided client by world type (pooled +1.4 over -216.4 to +81.3), and housing sensitivity v26 tenants by difficulty (DeepSeek minus GLM -0.09 moderate, +0.14 severe; v23 shows the same sign pattern at p = 0.031) | the owner, 2026-09-26: "do you think the diff strata yield useful info so far or it just diverged resources" | a reader of a by-stratum table or gap breakdown cannot tell a stratum difference from noise; the procurement and lemons splits, where most of the stratified reading happened, carry none detectable | fixed in ae77b0ae (artifact v79, 2026-09-26): every split on the page carries the test, and `tools/examiner/strata_noise.py` is its offline twin (page and script agree on 67 of 67 comparison splits). The committed test moves whole clusters across strata and also covers the gap reports: 81 splits, 42 testable, 12 at p < 0.05 against 2.1 expected. With it the Benjamini-Hochberg set at q = 0.10 differs from the session figures above: risk-allocation v2 by world type falls to q = 0.13; the menu and v1 world types (q = 0.049, 0.076) and three datacenter gap splits (world panel interfaces 2 and 3, risk allocation one price low as client; each q = 0.076) enter; the v2 arm (0.031), the two-sided client (0.076) and v26 difficulty (0.021) stay. The test reads a consistent shift in the gap only (EX-D-08) |
| EX-J-03 | I wrote the risk-allocation case card (v78) and the contract builder's cell panel saying each move is graded against a player who knows the integrator's type, without reading how the solver defines its reference. Every risk-allocation reference plays on the seat's own information: the counterpart's declared pricing policy and the prior over its type, learning the type only from the prices it is shown (`risk_allocation_contracts.py`: 'it knows the policy and the prior over the integrator's type, not the type'). In the full-terms pack the posted list reveals the type in most worlds, which made the error hard to see in any number | found by me the same day, reading the solver to design the tender case | the published page misdescribed what decision regret measures for a few hours | fixed in e2ca4eff; artifact v81 (2026-09-26). Rule applied since: read the definition in the code before describing a measure on a page |
