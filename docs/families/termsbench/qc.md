# TERMS-Bench: QC profile of the reproduction (`termsbench_repro_v1`)

Profile of the identity declared in [reproduction_plan.md](reproduction_plan.md), under the QC standard
(`docs/operations/benchmark_qc.md`, Gates 0 to 5). Written 2026-10-19 at the end of Stage 0, before any provider call
of this identity. The four published pilots keep their own records (`adapter_status.md`, the failure register).

**Status: Stage 0 stops at its gate.** The environment, the paper's interface and the generator are built and tested;
the fixed-concession check of Gate 1 fails on FC10 (TB-D-10), so by the plan no Stage 1 call is made.

| Gate | Status | What decides it |
|---|---|---|
| 0, profile | `passed` | this file, written before Stage 1 as the plan requires |
| 1, task distribution | `failed` (FC10) | geometry as stated (median ZOPA width 25.0 against the paper's 24.6); FC1 < FC10 < FC30; FC1 and FC30 within 0.03 of Table 16, FC10 0.041 above |
| 2, environment and verifier | `partial` | the plugin's paper rules are tested offline; `aeread verify-replay` has no v2 cell to check yet |
| 3, construct and baselines | `not_run` | needs Stage 1 and 3: GPT-4o-mini below every frontier agent in development |
| 4, attribution | `not_run` | routes, reasoning and temperature are sealed at Stage 2 |
| 5, confirmatory | `not_run` | the freeze and its addendum |

## Gate 1: the generator and the fixed-concession check

Generator v0.2.0 (`src/aeread_families/termsbench/cases_v2.py`) draws prices on [0, 100], an overlap width and a
no-deal gap U[10, 40], balances role and opener 2 x 2 within each family and regime, and regenerates byte for byte
(tested). Its blocks, the confirmatory corpus and the published pilot's seeds are disjoint (tested).

The plan's Stage 0 gate plays FC1, FC10 and FC30 through the reproduction's plugin and the family's own scorer
(`fc_baselines.py`). The FC rule is assumed (plan Section 6): open at the bound, concede the stated share of the
remaining distance to the reservation value, accept any offer within it.

| | FC1 | FC10 | FC30 |
|---|---:|---:|---:|
| Paper, Table 16, three-family overlap SE+ | 0.249 | 0.266 | 0.374 |
| 120 development worlds (the gate's run) | 0.248 | 0.325 | 0.392 |
| 1,200 check worlds | 0.258 | 0.307 | 0.397 |
| Within 0.03 on 1,200 worlds | yes | **no (+0.041)** | yes |

FC10 sits 0.04 above the paper in every role-by-opener cell (0.295 to 0.318), so the gap is not sampling. Five other
readings of the rule fit worse; that comparison is a diagnostic and was not used to choose a rule. The paper does not
define its FC policy, so the gate cannot tell whether the difference lies in the rule or in the environment. Per
TB-D-10 the gate is neither widened nor refitted; the FC definition is a question for the paper's author.

## Gate 2: what the reproduction's plugin does (tested offline)

`environment_v2.TermsBenchPluginV2` (family version 0.2.0) changes, against v0.1.0, only what the plan names: the
paper's five-key observation; decisions read case-insensitively; an Accept that carries a price executes at the
standing offer; an offer outside the bounds is clamped and recorded; an unparseable or illegal move is replaced by the
paper's fallback (accept the standing offer if it is weakly preferred to walking away, else offer the reservation
price), recorded as an invalid action and counted, and the episode continues. v0.1.0's plugin still ends such an
episode as before (tested). Harness 2.0 sends the observation alone and extracts the move by balanced-brace scanning.

## Known limits

- The agent prompts are read from the paper's v1 PDF (Appendix K, Fig. 20); the plan cites v2 for Table 16. The
  seller's prompt is the paper's stated mirror of the buyer's, written here.
- The paper names a `delta_max` constraint without a value; the observation leaves it out.
- **Registration.** The kernel trusts `('termsbench', '0.1.0', 'termsbench_environment')` only. A Stage 1 call needs
  either a one-line kernel-lane change adding version 0.2.0 (a non-author review) or a qualified contribution record.
