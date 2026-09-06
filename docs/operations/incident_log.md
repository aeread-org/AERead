# Incident log

**Status:** the single register of things that went wrong, across design,
operations, tooling, and judgment. One place, so an auditor can ask "what failed
and was it addressed" without reading five documents.

The QC standard requires preserving failed attempts as evidence and forbids
deleting history after a later fix. This is where that evidence is indexed. Detail
lives in the linked documents; this file is the index and the disposition.

## Two tiers

| tier | artifact | written by | contains |
|---|---|---|---|
| 1 | `evidence/<family>_failure_register/` | a generator, from published evidence only | every executed row that failed or carried a violation, and every rejected canary |
| 2 | this file | a person | design, operational, tooling, and judgment failures, including those that leave no trace in evidence |

Tier 1 for procurement is
`aeread_families.procurement_allocation.failure_register`. It is regenerable and
digest-bound, so it cannot omit a failure by accident or by preference, and any
drift between it and this file is itself a finding. Tier 2 exists because the
failures that cost the most this session -- a panel authored against an
unmeasured intuition, a claim reported too strongly, a script that committed to
the wrong checkout -- leave no row anywhere.

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
| T-10 | CI went red on a commit that touched only two documentation files. The cause was already on the branch: environment fixes for defects 5 and 7 had moved ten frozen `plan_sha256` literals across seven campaign tests, and no commit since had run the full suite | a documentation-only push failing CI, which is the signal that the failure predates it | roughly 50 minutes of CI and local suite time spread over three pushes, since each new push restarted a 35-minute run | literals updated and labelled as current-source identity rather than as seals; a new test pins the published bundles' self-verifying digests, which are the actual seals and all five still verify. Recorded as design defect 19 |
| T-09 | cleaning up a rejected panel, `rm -f .../trap_*.json` also matched `trap_is_cheapest`, `trap_is_midpriced` and `trap_is_priciest`, three cases of the *retained* fixture that the rejected panel was never meant to touch | `git status` immediately after showed three deletions that should not have been there | none; restored from the index in the same minute | the near-miss is the point: a glob written for files created minutes earlier reached files created days earlier, in a directory that J-05 explicitly designates as evidence to preserve. Deletions in an evidence directory should name their files or be a `git clean` of untracked paths only |
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

| J-05 | built the due-diligence panel and admitted it on a control-only screen; only 1 of 6 worlds could express a difference, 2 saturated and 2 floored | the operator asked whether the zero-delta worlds were saturated or non-discriminatory, which I had not checked | $0.20 on a comparison that is effectively one world | D-16 raised; Gate 1 now requires two-sided headroom screened with two policies; the campaign write-up was corrected from "one-world artifact" to "one-world comparison" |
| J-06 | the two-sided screen built to fix J-05 called the baseline policy with a positional argument where the parameter is keyword-only, and its `except Exception: return None` reported the resulting `TypeError` as "the baseline lost". Every baseline in every world raised, so the screen printed `admitted 6/6` having never run its second policy | the uniformity was implausible, so the baselines were traced before the verdict was used | none: caught before the panel was frozen, and the corrected screen reached the same admission decision for real | exception handling removed from the screen's action loop, so a broken policy aborts instead of scoring; a screen whose baselines all reach no terminal now rejects rather than admits |
| J-07 | the same screen's admission rule was "the two policies disagree", which admits a world where the control already wins every seed -- the precise saturation of J-01 and D-14, re-created inside the fix for D-16 | re-reading the rule against the earlier per-world control rates | none: caught before spending | admission now tests three separable conditions -- trivial, floored, saturated -- and measures the control at four seeds, because one seed cannot distinguish a ceiling from a lucky draw |

J-01, J-03 and J-05 share a cause: a panel was authored against an intuition about what
would be hard, and neither intuition was measured before the panel was frozen.
The $0.015 control screen now exists precisely because it is three orders of
magnitude cheaper than discovering the same thing from a completed run.

J-06 and J-07 are the more uncomfortable pair, because both are defects *in the
instrument built to catch the previous defect*. J-06 is a swallowed exception
that made "could not run" indistinguishable from "ran and lost". J-07 is a
weakened admission rule that let ceiling-saturated worlds back in through the
door opened for floored ones. Neither would have been caught by the screen
itself; both were caught by distrusting a clean result. A screen is evidence and
is owed the same scepticism as a run, which is why the screen now prints its
per-policy outcomes rather than only its verdict.

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
   branch assertion, never in a checkout someone is using. Deletions inside an
   evidence directory name their files or restrict themselves to untracked
   paths; a wildcard there will eventually match something older (T-09).
6. **Never catch an exception in a measurement loop.** A policy that cannot run
   and a policy that runs and loses must not produce the same value; conflating
   them turns a broken instrument into a confident result (J-06).
7. **A unanimous result is a reason to check the instrument**, not to proceed.
   Both screen defects announced themselves as a suspiciously clean sweep.
8. **Distinguish a seal from a pin.** A digest inside a published bundle that
   verifies against its own content is a seal and must never be edited to make a
   run pass. A digest written into a test is a pin on current source and will
   move whenever anything upstream does. Conflating them makes every environment
   fix look like tampering, and makes real tampering look routine (T-10, D-19).
