Procurement mechanism study (paper Section 5.1, Appendix E.4, Table E.20). Copied 2026-11-02 from
notebooks/procurement_v3/mechanism_study/ in the live checkout, which git does not track.

confirm/   held-out run: protocol.json (frozen, its own sha256 field f35aece8...), screen.json, episodes.csv, report.json
pilot/     development pilot, same files
recompute.py                  recomputes every Table E.20 figure from confirm/episodes.csv and writes CHECKS.json
CHECKS.json                   build.py asserts the paper's text against it
table_5_3_worlds_screen.py    applies this study's screen to the 20 worlds of Table 5.3; 0 of 20 pass (computed 2026-11-02, no model called)
P0_RESULTS.md, PROTOCOL.md, CODEX_COMPARISON_RESULTS.md   the study's own write-ups

report.json counts failed episodes in its `n` (99, 99, 99, 100). Mean losses use completed episodes only (99, 98, 98, 98),
and Table E.20 states those denominators. Its elicited-plan count 66/99 is right: the plan precedes the failure.
Raw requests, responses and results are not copied here. They are in the notebooks folder above and backed up at
~/aeread-run-backups/procurement_mechanism_p0_2026-10-27/.

Intervals in the paper are the sealed analysis's (confirm/report.json). recompute.py draws its own bootstrap, so CHECKS.json's intervals differ by Monte Carlo noise of at most 0.4; its means and counts match exactly.
