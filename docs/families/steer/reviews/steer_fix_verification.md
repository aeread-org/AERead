# Independent verification of the second-review fix pass

Cross-model check of whether each CONFIRMED finding was genuinely fixed and
whether its regression test has teeth. Recovered from the run transcript: the
verifier is read-only and could not write this file itself.

---

1. Confirmed-finding verification

This was static, read-only verification; pytest was not run because it may create cache/temp files.

- Finding 1 — production finalization calls scorer as callable: addressed by `9ee48dd`. `src/aeread_families/steer/measurement.py:279-286` adds `SteerScorer.__call__`, delegating to `.score()`. The specific regression test is `tests/test_steer_e2e.py:640-652`, `test_finalize_family_execution_scores_a_real_steer_episode_through_the_production_path`; without `__call__`, its real finalization call reaches the original `TypeError`.

- Finding 2 — false upstream pinning: addressed by `f2b93b4`. `src/aeread_families/steer/steer_bridge_driver.py:96-118` reads `git rev-parse HEAD` and rejects a mismatch. `tests/test_steer_cases.py:283-304` contains named wrong-commit and non-git-checkout tests; neither rejection existed before the fix.

- Finding 3 — unauthenticated replay labeled `match`: addressed by `d49526e`. `src/aeread_families/steer/replay.py:340-352` returns `not_compared` when `comparison is None`. `tests/test_steer_replay.py:420-461`, `test_replay_report_status_distinguishes_an_uncompared_replay_from_a_verified_match`, directly proves uncompared and verified reports cannot share `"match"`.

- Finding 4 — circular golden oracles: not fully fixed by `fdca586`. The new `tests/test_steer_cases.py:358-373`, `test_golden_1s_gold_option_is_independently_verified_against_the_raw_upstream_frame`, specifically checks Golden 1's first `transitivity` row through a separate raw-row path and would fail without that path or on disagreement. However, the triage finding covers Goldens 1/2, while Golden 2 still uses the independently unchecked first `plurality_voting` row at `tests/test_steer_goldens.py:146-166`. No named independent-ground-truth test exists for Golden 2.

- Finding 5 — silent module skips: not fully fixed by `a2b4f7f`. `conftest.py:82-90` activates failure only when `AEREAD_STEER_FIXTURES_REQUIRED` is externally set. Its own `test_a_missing_steer_cache_is_silently_green_by_default_in_a_multi_module_run` at `tests/test_steer_fixtures_required.py:54-60` explicitly requires the original default-silent behavior to remain. The specific opt-in regression test at lines 63-70 would fail without the hook, but no inspected fix commit configures CI to set the new variable.

- Finding 6 — missing exclusion records: not fixed for the committed corpus by `55bee6e`. The importer can now generate and hash a ledger (`src/aeread_families/steer/cases.py:198-232,311-345`), and the named tests at `tests/test_steer_cases.py:422-469` specifically exercise generation and temporary-file writing. But committed `cases/steer/pins.json:121-135` ends with `zero_correct_sample_by_element` and has no `excluded_question_ids_sha256_by_element`; the commit's own message states the corpus/pins were not regenerated. Thus the existing corpus still has no committed ledger binding.

- Finding 7 — vacuous Golden 5: addressed by `21f0555`. `tests/test_steer_cases.py:393-409`, `test_golden_5s_sample_is_independently_verified_to_have_zero_correct_options`, loads the raw upstream rows, requires the ID to exist, and independently asserts no option is correct. This specifically fails if the recorded sample is not genuinely zero-correct.

- Finding 8 — unsealed score evidence: addressed for the inspected harness-driven call sites by `40a81c3`. `src/aeread_families/steer/harness.py:75-99` adds `record_score`, linking the score to the submitted-answer event. `tests/test_steer_e2e.py:202-248`, `test_scripted_harness_seals_a_score_recorded_event_before_the_evidence_seal`, specifically requires two sealed events and the correct outcome-event linkage; before the commit it would fail because `record_score` did not exist. The API remains caller-driven, as documented at `harness.py:75-87`.

Claimed-fixed problems: Findings 4, 5, and 6 are incomplete. Every finding has a targeted named test for at least the implemented change, but Finding 4 lacks equivalent coverage for Golden 2, Finding 5 tests only an opt-in guard, and Finding 6 tests generated temporary output rather than the unchanged committed corpus.

2. Pre-existing test weakening/deletion

No weakened or deleted pre-existing test was observed in the eight fix commits.

- `d49526e`, `tests/test_steer_replay.py:408-417`: the old exact assertion `status == "match"` was replaced with the corrected exact assertion `status == "not_compared"` and supplemented with a distinct-state test; it was not loosened.
- `40a81c3`, `tests/test_steer_e2e.py:172-188`: exact assertions were strengthened from one event to two, adding event-type and serialized-score checks.
- `21f0555`, `tests/test_steer_goldens.py:266-281`: the existing non-empty-string assertion remains unchanged; only explanatory text and a separate stronger test were added.
- `9ee48dd`, `tests/test_steer_environment.py:182-265`: only the keyword was renamed from `cell=None` to `run=None`; assertions were unchanged.

3. Commit and working-tree state

`git log --oneline origin/main..HEAD` shows all eight alleged fixes as commits, from `9ee48dd` through `40a81c3`, above triage commit `44e5625`.

`git status` reported:

> On branch zeyu/steer-adapter; up to date with origin/zeyu/steer-adapter; nothing to commit, working tree clean.

`git status --porcelain=v1` and `git diff --stat` also produced no output. There are no uncommitted changes implementing a claimed fix. The missing parts of Findings 4–6 are absent from the committed implementation/artifacts, rather than present as local changes.

VERDICT: PROBLEMS - Findings 4, 5, and 6 remain incomplete despite targeted fix commits and a clean working tree.
