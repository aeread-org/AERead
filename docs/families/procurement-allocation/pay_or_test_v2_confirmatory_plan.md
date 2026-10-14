# Pay or test v2: confirmatory campaign plan

**Status:** plan only, 2026-10-14. Nothing here has been run, frozen or paid
for. No provider was called to write it. The pack it plays is
[`cases/procurement_allocation_v1/pay_or_test_v2/`](../../../cases/procurement_allocation_v1/pay_or_test_v2/),
whose gates are in the [QC profile, section 8.1](qc.md). The campaign rules are
the [experiment campaign SOP](../../operations/experiment_campaign_sop.md); this
document declares what that SOP asks to be declared before a run.

## Question

Does a subject plan past one test? On every world of the pack the best informed
policy beats the rule that looks one test ahead by at least $10 (by $30.09 on
average), because a cheap sample on one listing says whether a dear sample on
another listing of the same kind is worth taking. A subject that does no better
than the one-step rule is doing the arithmetic version 1 already rewarded; one
that does better is using what one test tells about another listing.

## Subjects

| Subject | Route | Status |
|---|---|---|
| Gemini 3.8 Flash | OpenRouter, Google AI Studio, reasoning minimal, temperature 0, top_p 1; the pin of `tools/cli_subjects/pay_or_test_openrouter.py` | required |
| GPT-6 Luna | OpenRouter, OpenAI, reasoning low, no temperature or top_p; the same driver's pin | required |
| GLM 5.3 Flash | none chosen: the Housing v14 route is gone (P-O-05) and the Morph route was refused at today's prices (P-O-06) | only if a route is pinned under its own identity before the pilot; it then joins every contrast below |
| Claude Opus 5.5, Codex Sol 6.1 | Claude Code and Codex CLIs, tool-less, as in the version 1 panels (`procurement_cli.py`) | optional; reported separately, because model and harness are confounded against the OpenRouter subjects (QC section 8, Gate 4) |

The OpenRouter subjects run on a new driver, `tools/cli_subjects/pay_or_test_v2_openrouter.py`,
written from `pay_or_test_openrouter.py` with the pack, the prompt
(`pay_or_test_v2_prompt.PAY_OR_TEST_V2_PROMPT`, id
`procurement_allocation_pay_or_test_shared_source_v1`), the panel names, the
inference seeds and the cost ceilings changed, and every other control kept:
route pins, the action schema v2 the family parser agrees with (P-D-23), the
credit and catalog checks before any run root, Housing v14's retry policy, the
halt rule, $0.30 a cell. The version 1 driver's bytes are in sealed plans and
are not edited. Scoring needs a version 2 report,
`tools/cli_subjects/pay_or_test_v2_report.py`, that prices actions with
`pay_or_test_v2_reference.score_actions`; the version 1 report reads the version
1 pack and reference.

## Measure

**Primary:** decision loss per world, in dollars: for every action the subject
took, the best informed policy's value at that point less the value of the
action, summed over the episode (`score_actions`). It does not move with how a
tested supplier turned out. A world's value is the mean over its plays. A
rejected or malformed action is priced as walking away at that point, as in
version 1.

**Secondary, reported, not tested:** loss by part (requests, award timing,
award terms, strays, walking away); share of the best policy's value; the
probe rate (worlds where the subject's first sample is on a newcomer other than
the one it awards, in a group with a dearer sample); loss by cell
(`myopic_pays`, `myopic_tests`) and by clock; the subject against always paying
and against the two-test lookahead.

## Contrasts, declared before any play

| Id | Contrast | Per-world difference | Reading |
|---|---|---|---|
| P1-s | each OpenRouter subject s against the one-step rule | subject's loss less `one_step_value`'s exact loss on that world | below zero: the subject plans past one test |
| P2 | Gemini 3.8 Flash against GPT-6 Luna (and each pair with GLM if it runs) | loss of one less loss of the other, paired by world | a model contrast: harness, schema, seed and limits are shared |

Two-sided, alpha 0.05, Holm across the family (P1 for each OpenRouter subject,
and P2). The CLI subjects get P1 as a description with its interval, outside
the family.

**Minimum meaningful effect: $10 a world** for every contrast. It is the
admission margin: every world was admitted because the one-step rule falls at
least $10 short of the best policy there, so a difference smaller than that is
inside the gap the pack was built to show. It is also about twice what Opus 5.5
gave up on version 1 under brief v2 ($5.4) and ten times Codex Sol 6.1 ($1.0).

## Variance pilot, then sizing

No variance has been measured on version 2, and version 1's numbers do not
transfer: in version 1 a third of the worlds were pay worlds where every
sensible subject loses nothing, and version 2 has none. The pilot comes first.

- **Worlds:** a pilot split of 12 worlds, three per cell, from the same
  generator, admission rule and brief on its own seed range (from 9,100,000,
  disjoint from the 24 confirmatory worlds and from version 1), under its own
  pack id `pay_or_test_v2_pilot`. The generator needs a split option for this;
  adding it must leave the committed pack byte for byte (its test says so).
- **Plays:** every subject plays every pilot world twice, request seeds 87001
  and 87002, so world-to-world and play-to-play variance separate.
- **Output:** the SD of each contrast's per-world difference, and its world and
  play components, with `aeread.design.variance_components` and
  `aeread.design.sd_of_differences` (draft PR #288, branch
  `codex/methods-design`; if it has not merged, the same arithmetic by hand).
  The pilot is development evidence: nothing in it is a result.

**Sizing:** `aeread.design.worlds_needed(sd, 10, power=0.8, alpha=0.05/3,
attrition=0.05)`, or by hand the smallest n with
n >= ((t(n-1, 1-alpha/2) + z(0.8)) * sd / 10)^2, then n / 0.95 rounded up;
the result is sealed with `aeread.design.sizing_record` at the freeze.

| If the pilot's largest contrast SD gives | Then |
|---|---|
| 24 worlds or fewer | the confirmatory run plays the committed 24, twice each |
| 25 to 96 | a confirmatory pack of that many worlds, rounded up to a multiple of four with the cells balanced, is generated from the same generator and admission on a fresh seed range before the run, and the committed 24 become development worlds |
| more than 96 | no confirmatory run; the plan is revised and states the smallest effect 96 worlds can detect |

What version 1 and the pack's own rules suggest, for orientation only, with
the Holm level of the first test (alpha 0.05/3): Gemini less Luna had a paired
SD of $13.0 on version 1, which needs 23 worlds; a subject that plays like the
two-test lookahead would differ from the one-step rule with an SD of $17.5,
which needs 37; a subject that always pays would differ with an SD of $54.2,
but by $34.3 on average, an effect 24 worlds detect only at about $38.

## Exclusions and missingness

- A world is excluded only if its case fails validation or its digest differs
  from `pack.json`. Never on an outcome.
- A failed cell (provider error after the declared retries, timeout, cost cap,
  a refused route) is typed missingness. It is never rerun; a changed control
  is a new identity.
- A malformed or rejected action is not missing: it ends the episode and is
  scored as walking away, as the brief and the version 1 report do.
- A world enters a paired contrast only if both sides have at least one
  completed play. If more than 5% of the worlds of any contrast are lost to
  missingness, that contrast is reported as not confirmatory, with the missing
  worlds named.
- The driver's halt rule stands: three consecutive failed cells stop the run,
  and no wave launches past the ceiling.

## Cost and wall time

From the version 1 flash panels under brief v2 (24 worlds, one play each):
Gemini 3.8 Flash charged $0.176 and took 10.1 s a world, GPT-6 Luna $0.029 and
12.7 s. The version 2 brief is seven lines longer and a probe adds one or two
actions, so the estimates below take half as much again and round up.

| Stage | Plays | Gemini 3.8 Flash | GPT-6 Luna | Wall time, 3 cells in parallel |
|---|---:|---:|---:|---|
| Gate, one world | 1 a subject | $0.02 | under $0.01 | under a minute |
| Pilot, 12 worlds twice | 24 a subject | $0.27 | $0.05 | about 3 minutes a subject |
| Confirmatory, 24 worlds twice | 48 a subject | $0.53 | $0.09 | about 5 minutes a subject |
| Confirmatory at the 96-world cap, twice | 192 a subject | $2.11 | $0.35 | about 20 minutes a subject |

Each identity declares its own ceiling (the version 1 driver used $3.00 a
panel). The CLI subjects, if run, cost about $4 to $5 at list for both of them
over 48 world-plays on version 1 (P-D-20, P-D-22), so about $2.50 each for 24
worlds once. Generating a larger confirmatory pack costs CPU only: the
24-world scan took six minutes, about 15 seconds a world.

## Order of work

1. The version 2 driver and report, with their tests (schema agrees with the
   parser; report re-drives a scripted trace to its recorded margin).
2. The pilot split, generated and committed.
3. Gate: one world per subject, offline replay of the receipt.
4. Pilot; variance components; sizing record.
5. Freeze: pack digests, prompt digest, driver digest, sizing record, this
   plan's contrasts, under a new confirmatory identity per subject.
6. Run; verify every receipt offline; report the declared contrasts first.
