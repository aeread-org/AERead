# Pay or test v3: a frozen control that tests (Gate 1, measured headroom)

**Status:** declared 2026-10-20, before any play below, at the owner's go ("run one frozen control model that does
test. let's have a try"). A diagnostic for the family's QC profile. It makes no claim about any model, and it changes
neither the declared test's worlds nor its sealed result.

## 1. Why

The Gate 1 row of [qc.md](qc.md) §8.2 is `partial` on the measured-headroom ground: no frozen control's scores were
used to screen out degenerate worlds. The subjects cannot serve. Opus 5.5, and Gemini 3.8 Flash and GPT-6 Luna at the
efforts they played, touched no newcomer in any play, so each scores the pay-the-premium rule in every world, which
is degenerate by construction. `docs/operations/benchmark_qc.md` (Gate 1, "Measured headroom") asks for the frozen
control itself, at several seeds per world, and for a continuous score names two grounds: a world is *degenerate* if
the control scores identically at every seed, and *trivial* if a deterministic policy already matches the control's
best.

## 2. Phase A: choosing the control, on development worlds

- **Candidates, in this order:** GPT-6 Luna and Gemini 3.8 Flash, each at reasoning effort `high`, on the pinned
  OpenRouter routes of the flash run (`pay_or_test_v3_flash_plan.md`, f3daae61). Only the profile id and the effort
  differ. GLM 5.3 Flash is not a candidate: the catalog check of 2026-10-20 refused its route, whose price rose above
  the pin.
- **Worlds:** the 12 worlds of the pilot pack (`pay_or_test_v3_pilot`), which are development worlds, one play each at
  request seed 87101, under the v3 brief every v3 subject played.
- **Rule:** a candidate qualifies if it touches a newcomer (a quote, sample or lookup to a new listing) in at least 4
  of its 12 plays, with at most one failed cell. The control is the qualifying candidate with more such plays, and a
  tie goes to the first in order. If neither qualifies, Phase B does not run, the gate stays `partial`, and that is
  reported.
- **Ceiling:** $1.50 a candidate.

## 3. Phase B: the control on the declared worlds

- The control plays the 20 worlds of the declared test (`pay_or_test_v3_confirm`) three times, at request seeds 87201,
  87202 and 87203, under the v3 brief. Identity `procurement_allocation_pay_or_test_v3_confirm_v3_control_<name>_v1`.
- **Ceiling:** $4.00. One sealed attempt an action; a failed cell is typed missingness and is never rerun.
- Every other control is version 1's, imported unchanged through `pay_or_test_v3_openrouter.py`: the route pins, the
  credit floor ($10) and catalog check before any run root exists, the retry policy, $0.30 a cell, the halt rule. Runs
  play from the tree carrying the unreviewed registry row, as every v3 run did.

The driver is `tools/cli_subjects/pay_or_test_v3_control.py`. It imports `pay_or_test_v3_openrouter.py`, whose bytes
the flash plans recorded, and changes only what this plan names: the candidates, the pack and seeds of each phase,
the ceilings, the identities and the plan's scope.

## 4. Read-out, fixed now

`tools/cli_subjects/pay_or_test_v3_control_analysis.py`, committed with this plan. Every play is replayed and priced
by `pay_or_test_v3_pilot_report.read`.

**Phase A:** per candidate, plays, failed cells and plays touching a newcomer; the control the rule selects.

**Phase B,** per declared world: the control's share of the pay-to-best gap closed at each seed, and

- *degenerate:* the control's decision loss is within $0.01 at all three seeds (this subsumes floored and saturated);
- *trivial:* the best of the screened deterministic rules (the one-step rule, the four fixed rules and the kind-blind
  shortcut, the set admission screened) is worth at least the control's best play, within $0.01;
- the within-world standard deviation of the control's share.

Reported beside the grounds, not as grounds: the same-kind habit and the rule that may test two newcomers against the
control's best play, and Sol 6.1's per-world share from the declared test.

**Reading.** The measured-headroom ground is met for a world that is neither degenerate nor trivial. The Gate 1 row
moves to `passed` only if all 20 worlds meet it; otherwise it stays `partial`, with the counts and the failing worlds
named. No world leaves the declared test, whose result stands as sealed.

## 5. Cost

At low effort the flash run cost $0.39 (Gemini) and $0.04 (Luna) for 40 plays. High effort runs longer: the ceilings
above bound the whole diagnostic at $7.00, against $38.05 of credit at the time of writing.
