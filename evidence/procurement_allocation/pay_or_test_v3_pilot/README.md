# Pay or test v3 pilot: Opus 5.5 and Sol 6.1 on the version 3 pilot pack

Development evidence, no claim. Declared in `docs/families/procurement-allocation/pay_or_test_v3_plan.md` (committed in
`18cdb111` before any play) and read out by `tools/cli_subjects/pay_or_test_v3_pilot_report.py`, committed with it.
Pack `pay_or_test_v3_pilot` (12 worlds), brief `procurement_allocation_pay_or_test_v3_brief_v1`, two plays a world,
Opus 5.5 through Claude Code and Sol 6.1 through Codex at effort low, both isolated (no violation; neutral working
directories). 48 of 48 plays completed. Every play's margin was reproduced by replaying its public trace through the
version 3 environment, then priced action by action by the version 3 reference. $2.29 and $2.17 at list price on
subscription logins.

**Run tree.** The kernel does not yet trust the version 3 plugin on `main`. The pilot ran from
`codex/procurement-v3-pilot-trusted` at `2372256c`: this branch at `18cdb111` plus one row in
`registry.TRUSTED_BUILTIN_PLUGIN_KEYS`, which had not had the kernel-lane review it needs before `main`. Played on the
owner's answer "bypass" to that question (2026-10-19).

- `reports/pilot_claude_opus55.json`, `reports/pilot_codex_sol61.json`: the declared read-out, with every play's trace.
- `reports/runs.json`: per subject, the isolation probe's findings (no paths), the plan and summary digests, the 24
  receipt digests, and list cost. The sealed run roots stay in the run tree's `runs/`; the raw probes quote the
  operator's home path and account, which the publication scan refuses.
