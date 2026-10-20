# Pay or test v3: Sol on the odds twins (diagnostic)

Declared in `docs/families/procurement-allocation/pay_or_test_v3_twins_sol_plan.md` (`2fb0140a`, before any play) and
read out by `tools/cli_subjects/pay_or_test_v3_twins_sol_analysis.py`, committed with it. Sol 6.1 through Codex, one play
on each of the 20 twins (`pay_or_test_v3_odds_diagnostic`). 20 of 20 plays completed, every one replayed from its trace
to the recorded margin; the isolation probe was clean; $1.95 at list price on a subscription login. Played from
`codex/procurement-v3-pilot-trusted` (34842926), which carries the registry row awaiting kernel-lane review.

- `reports/analysis.json`: the declared read-out, with per-world shares.
- `reports/readout.json`: every play, priced action by action.
- `reports/runs.json`: the isolation findings (no paths), plan and summary digests, receipt digests and cost.
