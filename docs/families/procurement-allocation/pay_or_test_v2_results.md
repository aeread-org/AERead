# Pay or test v2: results

**Status:** stopped at sizing, 2026-10-14. The campaign followed
[`pay_or_test_v2_confirmatory_plan.md`](pay_or_test_v2_confirmatory_plan.md)
through step 4 of its order of work. The pilot's sizing needs 326 to 3,464
worlds against the plan's cap of 96, so by the plan's own rule no confirmatory
run was frozen or played, and the declared contrasts have no confirmatory
result. Everything below is development evidence.

## Outcome

| | Gemini 3.8 Flash | GPT-6 Luna |
|---|---|---|
| Pilot plays completed | 24 of 24 | 24 of 24 |
| Receipts replayed offline | 24 of 24, `state_and_score` | 24 of 24, `state_and_score` |
| Decision loss a world, mean (SD over 12 worlds) | $69.24 ($56.03) | $112.71 ($178.10) |
| Share of the best policy's value kept | 84.3% | 74.4% |
| Plays that quoted or sampled a newcomer | 0 of 24 | 1 of 24 |
| Worlds with the plan's probe | 0 of 12 | 0 of 12 |
| Loss less always paying the premium ($69.24 here) | $0.00 | +$43.47 |
| Loss less the one-step rule ($29.93 here) | +$39.31 | +$82.78 |
| Loss less the two-test lookahead ($5.16 here) | +$64.08 | +$107.55 |

Gemini played the pay-the-premium rule on every world, to within half a cent
of that rule's exact expected loss. Luna went only to the recorded supplier in
23 of 24 plays and matched the pay-the-premium rule on 10 of 12 worlds; $39.47
of its $43.47 a world beyond that rule is one voided award (below), and $4.00
the one play that tested a newcomer. Neither
subject took the first test the pack is built around, so the plan's question,
whether a subject plans past one test, is not reached by these two subjects:
the P1 contrast would measure whether a subject tests at all (P-D-27).

## Pilot contrasts (development, not tested for a claim)

The plan's three contrasts computed on the pilot worlds as the confirmatory
run would have computed them: paired t on world values (each the mean of two
plays), two-sided, Holm across the three. No world was missing.

| Contrast | Worlds | Mean | 95% interval | Holm level | Interval at that level | p | Holm p |
|---|---:|---:|---|---:|---|---:|---:|
| P1, Gemini 3.8 Flash less `one_step_value` | 12 | +$39.31 | [4.93, 73.68] | 0.0167 | [-4.74, 83.35] | 0.029 | 0.086 |
| P1, GPT-6 Luna less `one_step_value` | 12 | +$82.78 | [-29.80, 195.35] | 0.025 | [-49.85, 215.41] | 0.134 | 0.268 |
| P2, Gemini 3.8 Flash less GPT-6 Luna | 12 | -$43.47 | [-129.99, 43.04] | 0.05 | [-129.99, 43.04] | 0.292 | 0.292 |

## Variance and sizing (step 4)

World-to-world and play-to-play variance of each contrast's per-play
difference, and the SD of a world's difference at the planned two plays
(`aeread.design.sd_of_differences`, from a copy of `codex/methods-design`
159cba3c). Worlds needed at the plan's settings: $10 effect, power 0.8,
alpha 0.05/3, attrition 5% (`aeread.design.worlds_needed`); the smallest
effect a given number of worlds detects at power 0.8 and alpha 0.05/3
(`smallest_detectable_effect`).

| Contrast | Var, world | Var, play | SD at two plays | Worlds needed | Detectable at 96 worlds | at 24 |
|---|---:|---:|---:|---:|---:|---:|
| P1, Gemini | 2,926.9 | 0.0 | $54.10 | 326 | $18.1 | $37.8 |
| P1, Luna | 13,250.4 | 36,284.4 | $177.18 | 3,464 | $59.3 | $123.8 |
| P2 | 399.4 | 36,284.4 | $136.17 | 2,047 | $45.6 | $95.2 |

The plan sizes on the largest SD, P1 for Luna: 3,464 worlds, past the 96-world
cap, so "no confirmatory run; the plan is revised and states the smallest
effect 96 worlds can detect". Every contrast is past the cap, the smallest
(Gemini's P1) by more than three times, so the decision does not rest on the
outlier below.

Gemini at temperature 0 played each world identically under both seeds, so
all of its variance is between worlds. 99% of Luna's play-to-play variance is
one world, `myopic_tests__loose__1`: at seed 87001 it awarded 54 units, which
is off the order step; the environment voided the award (`invalid_order_step`,
margin -$632, worse than walking away) and the score priced it as the award
terms it chose; at seed 87002 it awarded 50 and lost $194.6.

The sealed sizing record (`aeread.design.sizing_record`), as the pilot report
wrote it:

```json
{"artifact_sha256": "233f58a8eee8073761b7c0a4ccc3e4adc399d86709a216eec3dada5cede8a434",
 "inputs": {"alpha": 0.016666666666666666, "attrition": 0.05, "minimum_effect": 10.0,
            "pilot_source": "pay_or_test_v2_shared_source_openrouter_gemini38_flash_pilot_v1, pay_or_test_v2_shared_source_openrouter_gpt6_luna_pilot_v1",
            "pilot_worlds": 12, "power": 0.8, "sd_of_differences": 177.1797},
 "method": "paired t on per-world differences: the smallest n with n >= ((t(n-1, 1-alpha/2) + z(power)) * sd / effect)^2, then n / (1 - attrition) rounded up",
 "schema_version": "aeread.design.sizing/1", "worlds": 3464, "worlds_before_attrition": 3290}
```

## Gate (step 3)

One world per subject, the pilot pack's first in its own order
(`myopic_pays__tight__1`), request seed 87001.

| Subject | Status | Actions | Decision loss | Cost | Offline replay |
|---|---|---:|---:|---:|---|
| Gemini 3.8 Flash | completed | 3 | $16.3 | $0.0120 | verified, `state_and_score` |
| GPT-6 Luna | completed | 3 | $16.3 | $0.0009 | verified, `state_and_score` |

Both quoted and sampled the recorded supplier and awarded it, which is what
the one-step rule does in this cell (its exact expected loss there is $16.28).

## Spend

| Identity | Plays | Charged |
|---|---:|---:|
| `pay_or_test_v2_shared_source_openrouter_gemini38_flash_gate_v1` | 1 | $0.0120 |
| `pay_or_test_v2_shared_source_openrouter_gpt6_luna_gate_v1` | 1 | $0.0009 |
| `pay_or_test_v2_shared_source_openrouter_gemini38_flash_pilot_v1` | 24 | $0.1845 |
| `pay_or_test_v2_shared_source_openrouter_gpt6_luna_pilot_v1` | 24 | $0.0219 |
| Total | 50 | $0.2193 |

Every cell's cost is `exact` (no outcome-unknown call). OpenRouter credit was
$24.43 before the gate.

## Where everything is

| What | Where |
|---|---|
| Driver | `tools/cli_subjects/pay_or_test_v2_openrouter.py` (9f5adc81) |
| Report | `tools/cli_subjects/pay_or_test_v2_report.py` (9f5adc81) |
| Pilot pack | `cases/procurement_allocation_v1/pay_or_test_v2_pilot/` (9f5adc81), 12 worlds from seed 9,100,000, mean one-step loss $29.93 |
| Tests | `tests/test_pay_or_test_v2_openrouter.py`, and the pilot byte-for-byte checks in `tests/test_procurement_pay_or_test_v2.py` |
| Run roots | `runs/procurement_allocation/pay_or_test_v2_shared_source_openrouter_{gemini38_flash,gpt6_luna}_{gate,pilot}_v1` in this worktree (ignored by git, not published) |
| Pilot report | `runs/procurement_allocation/pay_or_test_v2_pilot_report.json` (sha256 `eed608fe...87d5`), rebuilt by `pay_or_test_v2_report.py runs/procurement_allocation --panel pilot --design-src <copy of src/aeread/design at 159cba3c>` |
| Incident rows | P-T-18, P-D-26, P-D-27 |

## Departures from the plan

1. **Steps 5 and 6 were not run.** The pilot's sizing passed the 96-world
   cap, and the plan says no confirmatory run follows. No freeze was written
   and no confirmatory identity exists.
2. **The decision-loss reference is sealed by digest, not as a kernel pin.**
   The model plans record the digests of both drivers, both references and
   both prompt modules, and `verify` refuses a run root once any changes. A
   kernel implementation pin was tried and refused by the resolver (P-D-26).
   This adds a seal; it changes no control.
3. **The gate world** is the pilot pack's first world; the plan did not name
   one. The gate plays no confirmatory world.
4. **Ceilings.** The plan leaves each identity its own ceiling. The driver
   declares $0.30 for each gate, $1.50 (Gemini) and $1.00 (Luna) for the
   pilot, and $1.80 and $1.00 for the confirmatory run that did not happen,
   each about twice the plan's estimate plus room for one wave.
5. **Interpreter.** The pilot pack was generated, and the pack tests run, on
   Python 3.13, the interpreter that built the committed pack, because the
   committed pack does not rebuild on 3.10 (P-T-18). The pilot pack itself
   rebuilds byte for byte on both.
6. **`aeread.design`** was loaded from a copy of 159cba3c, which the plan
   allows while that branch is unmerged.
