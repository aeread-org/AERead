# Independent verification of the second-review fix pass

Cross-model check of whether each CONFIRMED finding was genuinely fixed and
whether its regression test has teeth. Recovered from the run transcript: the
verifier is read-only and could not write this file itself.

---

## 1) Per-CONFIRMED finding

No tests were executed, per instruction; outcomes below are derived from the inspected code and test bodies.

| Finding | Addressing commit | Named test(s) | Genuinely fixed? | Justification |
|---|---|---|---|---|
| 1 — Production scorer is not callable | `93ddc73` | `test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt` | **Yes, narrowly** | `NegarenaScorer.__call__` now returns a typed invalid measurement (`src/aeread_families/negarena/measurement.py:437-479`, `93ddc73`), and the test reaches the real finalizer and asserts the resulting receipt/seal (`tests/test_negarena_kernel_finalizer.py:417-451`, `93ddc73`). Reverting `__call__` while retaining the test would raise `TypeError` before those assertions. The test is bridge-gated (`tests/test_negarena_kernel_finalizer.py:77-89`). |
| 2 — Replay record is not bound to execution inputs | `2ea753e` | `test_replay_rejects_a_case_with_the_same_case_id_but_different_content`; `test_replay_rejects_a_cell_with_a_different_opponent_profile` | **No — partially fixed** | Case and cell hashes are recorded and checked (`src/aeread_families/negarena/replay.py:117-213,273-297`, `2ea753e`), and the two tests exercise those checks (`tests/test_negarena_harness.py:347-428`, `2ea753e`). But `RecordedEpisode` still contains no run-plan or implementation/runtime pins; `PlanCell` itself has no pins, while they exist only on `RunPlan` (`src/aeread/shared_runner/resolver.py:157-185,210-228`, HEAD `046e293`). Moreover, `record_episode` checks `case_id` but never verifies `result.cell_id == cell.cell_id` (`replay.py:180-213`). Both named tests pass despite these omissions because they supply the original implementation and correct cell at recording time. |
| 3 — Harness seals an incomplete evidence lifecycle | `93ddc73` | `test_finalize_family_execution_seals_the_complete_evidence_lifecycle` | **No** | `ScriptedNegarenaHarness.__call__` still records only `negarena_decision_served` (`src/aeread_families/negarena/harness.py:73-95`, `93ddc73`). The new helper can append lifecycle events (`harness.py:102-193`), but repository-wide usage shows it is invoked only manually by the new test (`tests/test_negarena_kernel_finalizer.py:388-413`). Existing end-to-end harness tests still seal immediately and assert event count equals only logical-action count (`tests/test_negarena_harness.py:189-225,255-274`, HEAD `046e293`). The named test proves the optional helper works; it passes with the actual automatic harness/production wiring gap still present. |
| 4 — Unperformed comparison reported as match | `2ea753e` | `test_replay_and_verify_ties_replay_comparison_and_scoring_together`; `test_replay_report_status_is_not_compared_when_no_comparison_was_made` | **Yes** | `ReplayReport.status` now returns `not_compared` for `comparison is None` (`src/aeread_families/negarena/replay.py:455-479`, `2ea753e`). Both integration and bridge-free tests assert `not_compared` and explicitly reject `match` (`tests/test_negarena_harness.py:462-478,503-529`, `2ea753e`). Reverting the property to the old fall-through `"match"` makes those assertions fail. |
| 5 — Provisioning uses wrong default upstream path | `046e293` | `test_default_upstream_root_matches_the_documented_sibling_checkout`; `test_default_upstream_root_agrees_between_a_main_checkout_and_a_worktree` | **Yes, but inadequately protected** | The actual assignment now calls `default_upstream_root` (`tools/negarena_bridge/provision.sh:40-50,100-105`, `046e293`). However, both tests invoke only `--print-default-upstream-root` (`tests/test_negarena_provisioning.py:36-43,53-90`), which exits at `provision.sh:52-59` before reaching the real assignment at line 102. Step by step: retain helper/flag, revert only line 102 to the old fixed-depth expression, run either test—the flag prints the helper result and exits, so both still pass while normal provisioning is broken again. |

Explicitly, Findings **2 and 3 are claimed fixed but are not genuinely complete**. Finding 5 is fixed in current code, but its named tests would still pass if the real normal-provisioning use-site were reverted while the introspection helper remained.

## 2) Weakened, deleted, or loosened tests/assertions

None found in the three recent fix commits.

The only removed pre-existing assertion was corrected and strengthened in `2ea753e`: `assert report_no_original.status == "match"` became assertions for `"not_compared"` and `!= "match"` (`tests/test_negarena_harness.py:462-478`). `93ddc73` and `046e293` added new test files rather than deleting or loosening existing tests, as confirmed by their inspected per-file diffs.

## 3) Git state

`git log --oneline origin/main..HEAD`:

```text
046e293 fix(negarena): resolve the bridge provisioning default upstream path from any worktree depth
2ea753e fix(negarena): complete the offline-replay follow-up and record its review report
93ddc73 fix(negarena): make the production scorer callable and seal the full evidence lifecycle
8d77d9e docs: add negarena codex review triage
5f6c91b docs(negarena): add adversarial review report and fix-pass disposition
2a1e93e docs(negarena): fix dangling spec cross-reference and correct measurement_validity claim
fa79d27 fix(negarena): catch missing required tags and guard ultimatum blue endowment
dcea3e5 docs(negarena): add milestone-3 adapter status doc
d7341c6 feat(negarena): add scripted shared-runner harness and offline replay
6e62867 docs/negarena): update a stale milestone-1 comment in environment.py
4f26850 test(negarena): add golden-1 component parity test (spec section 5)
7dbf38c test(negarena): add the ten QC Gate-2 scoring goldens for measurement.py
93bcc40 feat(negarena): declare measurement leaves and wire settlement scoring
c99b7a7 feat(negarena): add family environment plugin (Mode B, bridge-delegated parsing)
66794b3 build(negarena): provision isolated bridge venv, correct spec governing facts
335e6f8 feat(negarena): author six-scenario case corpus with content digests
7f42bf1 docs/negarena): add adapter integration spec for buy_sell_game and ultimatum
```

`git status`:

```text
On branch zeyu/negarena-adapter
Your branch is up to date with 'origin/zeyu/negarena-adapter'.

nothing to commit, working tree clean
```

Verdict: the tree is clean and everything is committed.

VERDICT: PROBLEMS - Findings 2 and 3 remain incomplete, and Finding 5's tests do not protect its real provisioning use-site.
