# Pay or test v3 under brief v3.1: a declared rerun and a comprehension check

**Status:** declared 2026-10-19, before any play or question below, at the owner's go ("yes rerun the fix") on the
proposal that followed the audit of version 3's brief (incident P-D-29). A diagnostic with no claim and no model
ranking. Version 3's brief, its pilot and confirmatory results, and every sealed v3 run stay as they are.

## 1. Why

The audit read the sealed requests of all 148 v3 plays. The buyer sees every quantity the exact reference uses (cohort
counts, the sharing chance and what sharing means, the answer rate, fees, days, deadline, lead times that equal the true
ones in all 80 confirmatory listings, the payoff). It also found four defects in the brief (P-D-29): a contradiction
with the empty `marketplace_record` every new listing carries, on exactly the two rules the case tests; order sizes
shown only in a quote, although the 60-unit cap is why a bad new seller cannot be rescued; an objective that names
"quality loss" and "return recovery" with no rule; and a `message` field that changes nothing. None of the four
explains Opus never testing: in its reasons a shared source appears in 4 of 126 turns, always as risk. This rerun
measures whether correcting them changes what either subject does, and the comprehension check asks whether each
subject can read the sharing rule when asked directly.

## 2. Brief v3.1

`src/aeread_families/procurement_allocation/pay_or_test_v31_prompt.py`, prompt id
`procurement_allocation_pay_or_test_v3_brief_v31`. Version 3's text with these changes and no others:

| Defect | Version 3 | Version 3.1 |
|---|---|---|
| 1 | "A listing with a marketplace_record always answers"; "a listing with a marketplace_record is not part of any" | "A listing with reported orders always answers"; "a listing with reported orders is not part of any"; a new listing is "a listing whose marketplace_record shows no orders" |
| 2 | order sizes only in a quote | "Every supplier in this marketplace sells 50 to 60 units an order, in steps of 5", as the generator sets them for every listing |
| 3 | "contribution margin ... after the price paid, quality loss, return recovery, information cost, and shortfall penalties" | the margin the environment computes: revenue per completed kit, less price paid, information and shortfall penalties, plus refunds; the refund rule in terms of `objective.defect_detection_days` and the quote's `return_policy` fields |
| 4 | nothing | "A message is kept in the conversation and changes no supplier's price or terms." |

Nothing new says whom to test, in what order, or when a lookup is worth it. `tests/test_procurement_pay_or_test_v31_brief.py`
checks every rule the brief states against the environment and the generator, and that the sealed v3 brief is
unchanged.

## 3. Worlds, subjects and plays

- **Pack:** `pay_or_test_v3_confirm`, the 20 option-value worlds of arm A, unchanged. Holding the worlds fixed lets each
  world be paired with the sealed v3 run. These worlds have been played, so nothing here is a confirmatory test.
- **Subjects:** Sol 6.1 through Codex and Opus 5.5 through Claude Code, two plays a world each, 80 plays. The v3
  comparison runs are `procurement_allocation_pay_or_test_v3_confirm_v3_codex_cli_sol61_v1` and
  `..._v3_claude_code_opus55_v1`.
- **Identities:** the brief is a changed frozen control, so each run is a new campaign:
  `procurement_allocation_pay_or_test_v3_confirm_v31_codex_cli_sol61_v1` and `..._v31_claude_code_opus55_v1`, stamped
  `development_diagnostic` with this plan's scope by `tools/cli_subjects/pay_or_test_v31_cli.py`, which imports the v3
  driver unchanged.
- **Controls:** v3's, unchanged: effort low; isolation probed before any world, the run refusing on any violation; one
  sealed attempt an action; a failed cell is typed missingness and never rerun; the pack's list-price ceiling of $10 a
  run on subscription logins (the v3 runs cost $2.32 and $3.80 for 40 plays). Runs play from a tree carrying the
  unreviewed registry row, as v3's pilot and confirmatory did.

## 4. Read-out, in this order

`tools/cli_subjects/pay_or_test_v31_analysis.py`, committed with this plan. Every play is replayed and priced by
`pay_or_test_v3_pilot_report.read`. Per subject, paired by world with the v3 run:

1. the share of the pay-to-best gap closed under each brief (each world the mean of its plays), and the paired change,
   v3.1 minus v3, with its 95% t interval over the 20 worlds;
2. plays touching a new listing, plays touching two or more new listings, plays with a lookup, plays settling whether
   a kind shares a source;
3. turns whose stated reason mentions a shared source, and how many of those read it as information about another
   listing (the analysis tool's two patterns, fixed here);
4. the kind-blind shortcut's share on the same worlds (0.334), beside each subject's.

**Reading rules, fixed now:**
- **Opus.** It touched a new listing in 0 of 40 v3 plays. If it touches one in at most 2 of 40 under v3.1, the brief's
  defects are not why it never tests. If in 10 or more, the corrected brief moved it, and the brief is named as a cause.
  Between 3 and 9, the result is reported without a reading.
- **Sol.** If the paired change's 95% interval excludes zero, the brief moved Sol's share; otherwise no change is shown.
- **Both.** One factor changed (the brief) on the same worlds, but the runs are hours apart, so a change in the served
  model cannot be excluded; the CLI runtime versions recorded in each plan are compared and reported.

## 5. The comprehension check

No play. Each subject receives brief v3.1 as its instructions, a world's opening observation, and one question, through
the run's own isolated client at effort low, with a schema asking for a probability and the working.

- **Worlds:** `myopic_pays__3` (the paper's worked example), then the first two other confirmatory worlds in slug order
  that have a kind with two or more new listings. In each, the target is that kind's cheapest new listing and the probe
  the cheapest sample among the rest of the kind.
- **Questions,** each asking the probability that the target is sound: (a) after a sound sample of the probe alone;
  (b) after the target's quote answers clean and then the probe's sample is sound; (c) after the probe's sample fails.
  The exact answers come from the version 3 reference (for `myopic_pays__3`: 0.553, 0.944, 0.010).
- **Plays:** each question twice per subject, 18 asks per subject. An answer is correct within 0.05 of the exact value.
- **Reading:** a subject reads the rule if 14 or more of its 18 answers are correct, and does not if 9 or fewer.
  A subject that reads the rule and still never tests fails at planning to use it, which is the case's construct; one
  that does not read it fails at the rule. Between 10 and 13, no reading.

The records are written by `pay_or_test_v31_cli.py --comprehension` with each request's hash, and summarised by the
analysis tool.

## 6. Stop rules and publication

A run stops on an isolation violation, at three consecutive failed cells, or at its ceiling. Results go to
`evidence/procurement_allocation/pay_or_test_v31_brief/` as v3's did (read-outs, analysis, run and isolation records)
with a results note beside this plan. Whatever the reading, v3's results and the paper's Table 5.3 are not changed by
this diagnostic.

## Amendment 1 (2026-10-19, after Opus's 40 plays and before any answer was read)

Opus's comprehension check aborted on its first refused ask: Claude Code returned "Opus 5.5's safeguards flagged this
message" for one question, and the driver kept no record (incident P-O-04). No answer was recorded or seen. From now:

- a provider refusal is typed missingness, recorded with its failure text, and the check goes on; every ask is written
  as it lands;
- the reading uses answered asks: a subject reads the rule if at least 14/18 of its answered asks are correct, and does
  not if at most 9/18 are, and there is no reading if fewer than 14 asks were answered; refused asks are reported per
  question;
- Opus's whole check runs once more from the start. Sol's check had not started and runs under this amendment.

The plays, their read-out and their reading rules are unchanged.
