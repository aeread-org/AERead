# Pay or test v3: confirmatory test (arm A) and odds diagnostic (arm B)

Declared in `docs/families/procurement-allocation/pay_or_test_v3_confirmatory_plan.md` (`e67df11d`, before any play)
and computed by `tools/cli_subjects/pay_or_test_v3_confirmatory_analysis.py`, committed with it. The read-out it
calls crashed on the diagnostic pack before printing anything and was fixed in `07988773`, which changes no
computation (incident row P-T-20). 100 of 100 plays completed. Every margin was reproduced by replaying its public
trace through the version 3 environment. Every isolation probe was clean. $8.18 at list price on subscription logins.

**Run tree.** As for the pilot: `codex/procurement-v3-pilot-trusted` (merged to `07988773`), which adds one row trusting
the version 3 plugin, still awaiting kernel-lane review.

- `reports/analysis.json`: both arms' declared outputs, per world.
- `reports/readout_*.json`: each run's priced plays.
- `reports/runs.json`: per run, the isolation findings (no paths), plan and summary digests, receipt digests and cost.
