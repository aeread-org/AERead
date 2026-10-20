# Pay or test v3 under brief v3.1: rerun and comprehension check (diagnostic)

Declared in `docs/families/procurement-allocation/pay_or_test_v31_brief_plan.md` (`e7b94f91`, before any play; amendments
1 and 2 before any answer was seen) and computed by `tools/cli_subjects/pay_or_test_v31_analysis.py` (reason source fixed
in `8e7b4b36`, P-T-21). 80 of 80 plays completed; every margin was reproduced by replaying its public trace through the
version 3 environment. Every isolation probe was clean. Plays $2.47 (Sol) and $3.75 (Opus), comprehension $0.46, at list
price on subscription logins. Results: `docs/families/procurement-allocation/pay_or_test_v31_brief_results.md`.

**Run tree.** `codex/procurement-v3-brief-v31` with the row trusting the version 3 plugin (`2372256c`, still awaiting
kernel-lane review) cherry-picked on top, local only, as v3's runs were.

- `reports/analysis.json`: the declared read-out, both subjects paired by world with the sealed v3 confirmatory runs.
- `reports/readout_*.json`: each v3.1 run's priced plays.
- `reports/runs.json`: per run, the isolation findings (no paths), plan, prompt and summary digests, receipt digests, cost.
- `reports/comprehension_*.json`: each subject's 18 asks with request digests and exact answers;
  `comprehension_opus55_amendment1_all_refused.json` is the attempt whose 18 asks Opus 5.5's safeguards refused (P-O-04).
