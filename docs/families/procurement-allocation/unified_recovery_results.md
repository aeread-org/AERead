# Approved recovery: complete 36-row confirmation

The separately approved `procurement_allocation_unified_regret_recovery_v2`
completed all 36 fresh confirmation cells with 100% receipt replay, no
operational failures, no retries, and no measured violations. The guarded
comparison is **supported on the declared six curated synthetic worlds**:
treatment-minus-control regret is **−$5.02259**, with a 50,000-resample paired
world-bootstrap 95% interval of **[−$9.76878, −$0.86160]**.

| Observed result | Control | Treatment |
|---|---:|---:|
| Completed and replayed rows | 18/18 | 18/18 |
| Mean regret to certified bound | $34.97190 | $29.94931 |
| Eligible awards | 17/18 | 18/18 |
| Measured violations | 0 | 0 |

The independent unit is the economic world (six), after averaging the three
paired seeds within each world. The environment and inference seeds were
49001, 49002, and 49003. Both arms retained the same prompts, noisy sampling,
economic bounds, and pinned GLM/Parasail route as the original campaign.

The [original attempt](unified_run_results.md) remains ineligible and immutable.
Its 24-row pilot was re-audited and linked only as calibration. Its partial
confirmation was not pooled, replaced, or reclassified. The user approved the
separate recovery after the original no-retry run stopped on HTTP 429. The
recovery's one-retry policy was verified with synthetic shared-runner receipts;
no live retry was needed in this run.

## Costs and coverage

| Billing component | USD |
|---|---:|
| Original attempt: recorded charges | 0.1320779295 |
| Gemini coding review: two requests | 0.0138647025 |
| Recovery: two canaries plus 36 trajectories, 248 requests | 0.1224105795 |
| Combined recorded charges | **0.2683532115** |
| Original unresolved request reservation | 0.0023634000 |
| Combined accounted cost | **0.2707166115** |
| Remaining below the $0.35 ceiling | **0.0792833885** |

All recovery requests have recorded billing. The original unknown request is
still unknown and retains its reservation; it was not assigned a zero charge.
The user-requested Gemini 3.8 Flash calls assisted coding review only. They are
included in the cap and excluded from benchmark observations. The first review
was truncated; the focused follow-up was assessed against the declared contract.

## Verification and reproducibility

Before paid execution, the full provider-free suite passed **3,734 tests**, with
265 skipped and two expected failures. Unavailable upstream fixtures remain
explicitly skipped. The source snapshot taken before that test run matched the
source pins used for execution. The test command was `PYTHONPATH=src python -m
pytest -q -n 8`.

The recovery plan was frozen before confirmation with digest
`be70f3feeb5ef37166a9683a4b0e48cf0220261bf7ae9449b0b67f312e2bf783`.
The implementation was committed at `2f6592b1` before paid execution. All seven
shared campaign gates passed. The exporter independently replayed every sealed
receipt; the public review script then recomputed all 36 economic outcomes,
the guarded comparison and interval, and all six artifact hashes. The scan for
credentials, account metadata, full prompts, and raw provider payload fields
was clean.

From the repository root, reproduce the public review without credentials:

```sh
PYTHONPATH=src python evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2/qc/replay_review.py
```

Review targets:

1. [Confirmation rows and comparison](../../../evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2/reports/confirmatory.json): verify the six paired world means and guarded interval.
2. [Frozen plan](../../../evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2/tables/frozen_plan.json) and [execution contract](../../../evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2/tables/execution_contract.json): fresh seeds, prompt hashes, retry boundary and original calibration link.
3. [Execution status and combined billing](../../../evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2/reports/execution_status.json): 248 recovery requests, zero unresolved recovery requests, original reservation retained.
4. [Independent audit](../../../evidence/procurement_allocation/procurement_allocation_unified_regret_recovery_v2/qc/execution_audit.json) and [V3 failure register](../../../evidence/procurement_allocation/procurement_allocation_failure_register/reports/failure_register_2026-09-19_v3.json): 20 bundles, 68 reports, 721 planned rows / 701 executed, with the original 20 unattempted cells and two historical operational failures preserved.

## Limits of the result

These are curated synthetic markets, not a representative supplier sample or
a population model ranking. The panel's public lead-time signal is unbalanced
(five worlds in one direction, one in the other). Pilot variance combines
sampling and model-inference variability. The planning power calculation remains
conditional on its stated distribution assumptions.

The observed $5.02 improvement is smaller than the $11.66 effect used in the
planning sensitivity. The declared promotion rule requires a negative interval
upper bound; it does not require a realized 15% improvement. The 15% threshold
was an offline scenario-admission condition. No real supplier qualification or
bulk-order decision follows from this experiment.
