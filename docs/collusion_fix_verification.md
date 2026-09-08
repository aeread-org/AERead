# Independent verification of the second-review fix pass

Cross-model check of whether each CONFIRMED finding was genuinely fixed and
whether its regression test has teeth. Recovered from the run transcript: the
verifier is read-only and could not write this file itself.

---

Two confirmed findings are not fully fixed.

1. CONFIRMED findings and regression tests

- Finding 2 — incomplete. Commit `7a4a5a7` corrects the baseline used by one replay test, but does not fix the scorer/caller provenance gap described in the triage. Production still accepts caller-supplied bare baseline values without proving the opponent condition. `test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent` only proves the values differ; it would pass with production unchanged. The updated replay test guards its own fixture, not production behavior.
- Finding 3 — genuinely addressed by `7a4a5a7`. `RecordedEpisode.expected_final_outcome_sha256`, `ReplayReport.digest_verified`, and the status check detect altered decisions during offline replay. `test_offline_replay_of_a_tampered_recording_with_no_original_in_memory_reports_mismatch_not_a_fabricated_match` would fail without this logic.
- Finding 4 — only partially addressed by `7a4a5a7`. The recording is now bound to `case_content_sha256`, and `test_replay_case_content_mismatch_raises_a_typed_replay_error_even_with_a_matching_case_id` would fail without that check. However, the triage also identified missing run-cell identity. `RecordedEpisode` still contains no `cell_id`, and `replay_episode()` checks only case ID/content before accepting the supplied cell. No test exercises replay under a different compatible cell.
- Finding 5 — genuinely addressed by `4f6f4eb`. Raw signed per-round gaps are retained in `primary.metadata["per_round_gap"]`. Both `test_distance_leaf_retains_the_raw_signed_per_round_gap_not_just_the_averaged_primary` and `test_distance_leaf_gap_metadata_distinguishes_oscillating_from_midpoint_trajectories_sharing_one_primary_value` would fail without the metadata addition.

2. Test weakening

No pre-existing test or assertion was deleted, weakened, or loosened in the two fix commits. Existing assertions were retained; constructor calls and the incorrect baseline fixture were updated, and new assertions/tests were added.

3. Repository state

`git log --oneline origin/main..HEAD` showed 11 commits, including both fix commits and the final disposition commit. The tree is not clean: `git status` reports the untracked file `docs/collusion_review_codex.md`. Therefore, not everything in the worktree is committed.

Tests were not executed, as requested; test sensitivity above is based on the diffs and control flow.

VERDICT: PROBLEMS - Findings 2 and 4 remain incomplete, and the worktree contains an uncommitted untracked review file.
