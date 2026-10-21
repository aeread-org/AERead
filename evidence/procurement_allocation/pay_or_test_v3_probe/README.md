# Pay or test v3 probe: frontier CLI subjects on worlds where the best first move is worth only its option value

Development evidence, no claim. Declared in `docs/families/procurement-allocation/pay_or_test_v3_design_note.md`
("Probe, 2026-10-19") before the run; read out by `tools/cli_subjects/pay_or_test_v3_probe_report.py` (committed
before the results). Pack `pay_or_test_v2_pilot` (12 worlds), prompt `procurement_allocation_pay_or_test_shared_source_v1`,
one play a world, Opus 5.5 through Claude Code and Sol 6.1 through Codex, effort low, both isolated (`reports/isolation.json`:
no violation; neutral working directories). 24 of 24 plays completed, every play's margin reproduced by replay through
v2's reference; $1.21 and $0.66 at list price on subscription logins.

| Worlds | Subject | First request to a newcomer | First move is a best move | Mean decision loss | One-step rule | Pay the premium |
|---|---|---:|---:|---:|---:|---:|
| 6 `myopic_pays` (Q*(probe) > Q*(default) > Q1) | Opus 5.5 | 0 of 6 | 0 of 6 | $23.61 | $23.61 | $23.61 |
| | Sol 6.1 | 0 of 6 | 0 of 6 | $23.61 | $23.61 | $23.61 |
| 6 `myopic_tests` (one test ahead suffices) | Opus 5.5 | 0 of 6 | 0 of 6 | $90.95 | $36.26 | $114.87 |
| | Sol 6.1 | 5 of 6 | 1 of 6 | $21.24 | $36.26 | $114.87 |

`reports/probe.json` holds every play's priced trace. The raw isolation probes stay in the run roots: they quote the
operator's home path and account email, which the publication scan refuses.
