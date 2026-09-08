# Independent verification of the second-review fix pass

Cross-model check of whether each CONFIRMED finding was genuinely fixed and
whether its regression test has teeth. Recovered from the run transcript: the
verifier is read-only and could not write this file itself.

---

1. CONFIRMED findings

Finding 1 — runtime upstream pin -> FIXED (`142aee8`; `environment.py` hunk `@@ -168,6 +169,39 @@` adds `git rev-parse HEAD` and `git status --porcelain`, now [environment.py:180](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/environment.py:180); tests `tests/test_amazonbarg_environment.py::test_validate_payload_rejects_an_upstream_checkout_edited_in_place` and `::test_validate_payload_rejects_an_upstream_checkout_at_the_wrong_revision`, [line 252](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_environment.py:252)).

Finding 2 — false ZOPA passes -> FIXED (`142aee8`; `measurement.py` hunk `@@ -665,25 +669,50 @@` changes bounds from delegated `C/B` to `derived.cost/budget`, now [measurement.py:698](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/measurement.py:698); test `tests/test_amazonbarg_measurement.py::test_narrow_bargaining_room_does_not_let_a_deal_above_the_real_budget_pass_zopa`, [line 533](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_measurement.py:533)).

Finding 3 — replay never reads sealed evidence -> FIXED (`142aee8`; `replay.py` hunk `@@ -155,6 +157,45 @@` adds `record_episode_from_evidence`, including chain/seal verification and payload reads at [replay.py:160](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/replay.py:160); tests `tests/test_amazonbarg_replay.py::test_record_episode_from_evidence_reads_the_sealed_disk_store_not_memory` and `::test_record_episode_from_evidence_detects_tampering_on_disk`, [line 288](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_replay.py:288)).

Finding 4 — unverified replay reports match -> FIXED (`142aee8`; `replay.py` hunk `@@ -387,9 +428,23 @@` adds `comparison is None -> "not_comparable"`, now [replay.py:429](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/replay.py:429); test `tests/test_amazonbarg_replay.py::test_replay_and_verify_reports_not_comparable_rather_than_a_fabricated_match`, [line 574](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_replay.py:574)).

Finding 5 — production execution does not produce/seal scores -> NOT FIXED (no fix commit and no regression test; it was deferred as kernel-owned. `finalize_family_execution` still calls the scorer as a single callable at [family_evaluation.py:245](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread/shared_runner/family_evaluation.py:245), while `AmazonbargScorer` still has no `__call__` and returns five leaves through `score_all`, [measurement.py:850](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/measurement.py:850)).

Finding 6 — tests silently skip wholesale -> FIXED (`6760399`; `conftest.py` hunk `@@ -10,0 +13,67 @@` introduces per-item skipping at [conftest.py:64](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/conftest.py:64), while six `@@ -…,8 +… @@` hunks remove module-level `pytest.skip`; test `tests/test_amazonbarg_upstream_skip_scope.py::test_a_pure_measurement_leaf_test_still_passes_without_the_upstream_checkout`, [line 68](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_upstream_skip_scope.py:68)).

Finding 7 — component parity compares implementation with itself -> NOT FIXED (`8f5a044` claims a documentation fix, but hunk `@@ -303,0 +304,17 @@` adds only a docstring; the two identical `compute_upstream_metrics` calls and self-equality assertion remain at [test_amazonbarg_measurement.py:324](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_measurement.py:324). The cited finding-2 test does not fail if this documentation-only change is removed, so no finding-7 regression test exists).

Finding 8 — sanitization collision -> FIXED (`8f5a044`; `cases.py` hunk `@@ -126,14 +144,29 @@` escapes marker-shaped raw underscores, now [cases.py:156](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/cases.py:156); test `tests/test_amazonbarg_cases.py::test_sanitize_does_not_collide_a_real_colon_with_a_literal_escape_marker`, [line 182](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_cases.py:182)).

Finding 9 — insertion-order-dependent pilot digest -> FIXED (`8f5a044`; `cases.py` hunk `@@ -465,8 +503,21 @@` adds `normalized["case_ids"] = sorted(...)`, now [cases.py:505](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/cases.py:505); test `tests/test_amazonbarg_cases.py::test_pilot_manifest_digest_is_independent_of_insertion_order`, [line 404](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_cases.py:404)).

Finding 10 — concurrency-unsafe import shim -> FIXED (`8f5a044`; hunks `@@ -96,6 +97,22 @@`, `@@ -309,16 +326,24 @@`, and `@@ -330,17 +355,22 @@` add `_IMPORT_LOCK` and wrap both critical sections, now [upstream_shim.py:114](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/src/aeread_families/amazonbarg/upstream_shim.py:114); test `tests/test_amazonbarg_shim.py::test_direct_import_calls_are_serialized_across_threads`, [line 225](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/tests/test_amazonbarg_shim.py:225)).

2. Pre-existing test weakening

None observed. `142aee8` and `8f5a044` only add test code/assertions. In `6760399`, the only removed test-file logic is the six module-level `pytest.skip(..., allow_module_level=True)` blocks; no pre-existing test function, assertion, tolerance, or expected value was removed or loosened. Their replacement is the per-test hook at [conftest.py:64](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg/conftest.py:64). `37ce660` changes documentation only.

3. Git outputs and commit state

`git log --oneline origin/main..HEAD`:

```text
37ce660 docs(amazonbarg): record codex-review fix-pass disposition
8f5a044 fix(amazonbarg): make sanitize injective, digest pilot membership, serialize the shim import lock
6760399 test(amazonbarg): skip only upstream-dependent tests, not whole modules
142aee8 fix(amazonbarg): enforce runtime upstream pin and close ZOPA/replay evidence gaps
9f79e9b docs(amazonbarg): triage second-reviewer (codex) findings
35eea52 docs(amazonbarg): record adversarial review and fix-pass disposition
18a6510 test(amazonbarg): cover goldens 2-4 through sealed evidence and replay
14b9681 docs(amazonbarg): record milestone 3 status and scope decision
748945e feat(amazonbarg): add offline replay reproducing state and score
96e95b0 feat(amazonbarg): add scripted harness with sealed evidence
dae983f feat(amazonbarg): add measurement leaves and QC Gate-2 goldens
94f33cb refactor(amazonbarg): drop leading underscore from cross-module helper
2c9fc05 feat(amazonbarg): add environment phase graph and plugin registration
739d912 feat(amazonbarg): add case importer, pins, and 45-session pilot corpus
43610a9 feat(amazonbarg): add in-process upstream delegation shim
74aca3e docs: draft amazonbarg bilateral-bargaining adapter spec
```

`git status`:

```text
On branch zeyu/amazonbarg-adapter
Your branch is up to date with 'origin/zeyu/amazonbarg-adapter'.

nothing to commit, working tree clean
```

The working tree is clean. All changes constituting the claimed fix pass are committed; none are merely staged or untracked. The remaining problems are substantive omissions in committed code, not uncommitted work.

VERDICT: PROBLEMS - Findings 5 and 7 do not meet the claimed fix-and-regression-test bar.
