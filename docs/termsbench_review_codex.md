# Codex adversarial review — termsbench adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **6**.

---

Review completed: 0 Critical, 2 High, 2 Medium, 2 Low findings. No files were skipped, and no skipped/xfail tests or colon-bearing corpus identifiers were found.

The requested artifact could not be written because the enforced read-only sandbox rejected the only authorized write. `docs/termsbench_review_codex.md` remains absent.

Findings:

1. High — Terminal-round walk-away probability is discarded
   `src/aeread_families/termsbench/kernel.py:690-702`
   At round `K`, failed acceptance immediately becomes Timeout before the positive walk-away hazard is sampled, changing terminal-outcome frequencies.

2. High — Scoreable episodes can run without sealed evidence
   `src/aeread_families/termsbench/harness.py:98-105,121-129,168-175`; `tests/test_termsbench_harness.py:264-280`
   Omitting `EvidenceStore` silently suppresses action/draw records while still allowing scoring, making published results unauditable.

3. Medium — Uncompared offline replay is falsely labelled `match`
   `src/aeread_families/termsbench/replay.py:395-408,422-427`
   When `original=None`, `comparison` is absent but `ReplayReport.status` still returns `"match"`.

4. Medium — Timeout reports `K+1` rounds and its test locks in the defect
   `src/aeread_families/termsbench/environment.py:494-508,518-530`; `tests/test_termsbench_environment.py:172-183`
   A timeout occurring at round 10 is serialized as `rounds_used=11`.

5. Low — Difficulty-purity test asserts source spelling, not behavior
   `tests/test_termsbench_cases.py:106-115`
   Substring inspection of `generate_payload` can miss outcome dependence hidden behind helpers and can fail on irrelevant variable names.

6. Low — Replay scoring test compares the scorer with itself
   `tests/test_termsbench_replay.py:272-290`; `src/aeread_families/termsbench/replay.py:355-386`
   A shared scoring regression changes both sides identically, leaving the test green.

No tests were executed because the user's safety boundary permitted only reads and `git log/diff/show`.

FINDINGS: 6
