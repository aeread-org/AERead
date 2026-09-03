# steer adapter review — disposition

Reviewer inputs: `docs/steer_review_claude.md` (present). `docs/steer_review_codex.md`
does not exist in this worktree -- the second reviewer produced no report (handled
gracefully: no codex findings exist to process, nothing else changes).

Each finding below was independently re-verified against the code/data before any fix
was written (per this task's own instructions: reviews contain false positives).

---

## CRITICAL

### C1 — `source_sha256` runtime "integrity check" only compared two stored copies of the same label

**Disposition: FIXED.**

Reproduced independently: `SteerPlugin.initial_state`/`build_scorer` compared
`row["source_sha256"]` (a value written once by the importer and never touched again)
against `family_case["source_sha256"]` -- a tampered cache row (question_text/options/
correct_option_id changed, `source_sha256` field left byte-identical) went undetected.

Fix: `src/aeread_families/steer/environment.py` now recomputes the digest from the
row's own `question_text`/`options`/`correct_option_id` (`_recomputed_source_sha256`,
mirroring `steer_bridge_driver._op_flatten`'s construction exactly) and compares that
recomputed value against `family_case["source_sha256"]`, at both `initial_state` and
`build_scorer`.

Test added: `tests/test_steer_environment.py::test_initial_state_and_build_scorer_reject_a_tampered_row_whose_own_source_sha256_field_agrees`
-- builds a tampered cache row whose own `source_sha256` field is left unchanged and
asserts both hooks now raise. Confirmed the old code would not have raised (the old
comparison is a bare field-equality check against a value that was left unchanged by
construction in the test).

---

## MAJOR

### M1 — `_op_flatten`'s `.astype(bool)` on `Answers.correct` reads `NaN` as `True`

**Disposition: FIXED.**

Reproduced independently under the pinned bridge venv (pandas 3.0.5) against the real
`pure_nash/answers.pkl`: the `correct` column mixes real `bool` values with 60,000 `NaN`
placeholders; `.astype(bool)` on that object-dtype column reads every `NaN` as `True`
(66,047 total vs. 6,047 real). Cross-checked all 8 declared elements' `correct`/
`correct_answer` columns: `pure_nash` is the only one with `NaN`. Independently confirmed
the reviewer's own finding that the *admitted* (`exactly_one_correct`) question set and
gold answers are bit-identical whether `NaN` counts as truthy or not for this pinned
snapshot -- only the `zero_correct`/`multi_correct` exclusion-reason labels for the
already-excluded 12,550 questions were wrong (previously reported as 550/12,000, corrected
to 12,550/0).

Fix: `src/aeread_families/steer/steer_bridge_driver.py`'s `_op_flatten` now does
`.fillna(False).astype(bool)` before building `correct_rows`.

Consequence: `cases/steer/pins.json` and every one of the 1,595 committed case files embed
the shared `pins` record (including `counts_by_element`) inside `payload.pins`, so the
corpus was regenerated from the pinned upstream checkout with the fixed driver
(`python -m aeread_families.steer.cases ...`). Verified before committing: only
`pins.counts_by_element.pure_nash` and the resulting `content_sha256` changed per case;
every case's own `element`/`question_id`/`options_count`/`source_sha256` is byte-identical
to before, `corpus_manifest.json` is untouched (case_ids don't depend on counts), and the
corpus still admits exactly 1,595 cases.

Tests: updated `EXPECTED_COUNTS["pure_nash"]` in `tests/test_steer_cases.py` to the
corrected values (this alone is a regression guard -- it would fail against the unfixed
driver) and added a dedicated
`test_pure_nash_nan_correct_values_are_not_counted_as_truthy` that names the bug directly
rather than relying only on the full-table comparison.

Docs updated to match: `docs/steer_adapter_spec.md`'s Governing Facts table and narrative,
and the "`canonical_set` future work" bullet in both `steer_adapter_spec.md` and
`steer_adapter_status.md` (it previously attributed multi-correct exclusions to
`pure_nash`; that reading was itself the coercion-bug artifact -- the real, still-open
multi-correct case is `dsic_mechanism`'s 5 genuine multi-correct questions).

---

## MINOR

### N1 — `ledger_entries/steer.md` cited by `steer_adapter_spec.md`/`steer_adapter_status.md` but "does not exist anywhere in this repository or its git history"

**Disposition: REFUTED.**

The reviewer's reproduction (`git log --all` / `find .`, both run inside the AERead git
repo) is accurate as far as it checked, but the ledger directory is deliberately kept
OUTSIDE the AERead git repo -- the same convention as `bridges/steer-data/` and
`upstream-steer/`, and the same convention this very fix-pass's own instructions use
(`/Users/sunzeyu/Documents/econ benchmark/ledger_entries/steer.md`). That file exists,
is current (last updated 2026-09-02), and already carries an entry for exactly the
schema-drift finding both docs cite. Confirmed this is an established, repo-wide pattern,
not a steer-specific improvisation: `govsim`'s own spec/status docs cite
`ledger_entries/govsim.md` the identical way, and that file also exists at the same
out-of-repo path. No doc or code change made.

### N2 — `cases/steer/README.md` says "Scoring is not implemented yet" and describes the cache as "keyed by `source_sha256`"

**Disposition: FIXED.**

Both claims reproduced by inspection: `measurement.py`/`build_scorer`/the five QC Gate-2
goldens do implement and exercise scoring; `write_cache`/`_load_cached_row` key the cache
by `<element>/cases.jsonl` scanned linearly for a matching `question_id`, not by
`source_sha256`. `cases/steer/README.md` corrected on both points.

---

## SUGGESTIONS

### S1 — `_correct_column`'s fixed `correct`-before-`correct_answer` priority is a hard-coded tie-break for `pure_nash`, undocumented as a semantic choice beyond "reproduces last session's numbers"

**Disposition: DEFERRED** (not required by the review itself; no reproducible defect
against the current 8 declared elements -- verified `correct` is in fact the column that
reproduces the corrected Governing Facts table, `correct_answer` alone does not). Left
unchanged: this is a future-proofing suggestion for a hypothetical ninth declared element
that also carries both columns, out of this fix pass's scope (adding a
per-element-declared expected-column mapping would be a small design change, not a
one-line fix, and no current element is at risk).

### S2 — Golden 3's "no protected state changed" claim was verified only through the narrow `outcome()` projection, not the full `final_state`

**Disposition: FIXED.** Cheap and directly strengthens the golden the review's own focus
area (QC Gate-2 state-protection proof) names. `tests/test_steer_goldens.py`'s golden 3
now also asserts `result.final_state["question_text"]`/`["options"]` are byte-identical
(via `canonical_json_bytes`) to the cached row's own values, not just that
`selected_option_id` stayed `None`.

### S3 — Hard-coded personal absolute path (`/Users/sunzeyu/...`) as the default upstream/cache root in `cases.py`

**Disposition: DEFERRED** (explicitly "not required by review," fully overridable via
`AEREAD_STEER_UPSTREAM_ROOT`/`AEREAD_STEER_DATA_ROOT`, and not a functional bug). Left
unchanged in this fix pass: no template precedent in `tau3_retail.cases` for a more
actionable fallback error, and changing default-path behavior is a design change beyond
this pass's fix-confirmed-findings scope.

---

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| C1 | Critical | Fixed |
| M1 | Major | Fixed |
| N1 | Minor | Refuted |
| N2 | Minor | Fixed |
| S1 | Suggestion | Deferred |
| S2 | Suggestion | Fixed |
| S3 | Suggestion | Deferred |

No finding in this review was about the shared kernel/runner (`aeread.shared_runner`) --
every confirmed finding was in the `steer` adapter's own code or docs, so nothing was
appended to `ledger_entries/steer.md` from this pass.

---

## Codex-review findings

Source: `docs/steer_codex_triage.md` (triage of the recovered Codex adversarial review;
8 findings, all classified CONFIRMED there). Each is fixed here with a test that failed
first for the right reason, then passed once the fix landed. None concerns the shared
kernel/runner itself (finding 1's defect is a contract mismatch *exposed by* a
shared-kernel caller, but the fix is local to this family), so nothing was appended to
`ledger_entries/steer.md` from this section either.

| # | Finding | Disposition | Regression test |
|---|---|---|---|
| 1 | Production finalization calls the scorer as a callable; `SteerScorer` only had `.score()` | Fixed | `tests/test_steer_e2e.py::test_finalize_family_execution_scores_a_real_steer_episode_through_the_production_path` |
| 2 | False upstream pinning (commit never verified against a real checkout) | Fixed | `tests/test_steer_cases.py::test_bridge_refuses_to_flatten_against_an_upstream_checkout_at_the_wrong_commit`, `tests/test_steer_cases.py::test_bridge_refuses_an_upstream_root_that_is_not_a_git_checkout` |
| 3 | Unauthenticated replay labeled `match` | Fixed | `tests/test_steer_replay.py::test_replay_report_status_distinguishes_an_uncompared_replay_from_a_verified_match` |
| 4 | Circular golden oracles (goldens 1-4 only ever checked self-agreement with the cache) | Fixed | `tests/test_steer_cases.py::test_golden_1s_gold_option_is_independently_verified_against_the_raw_upstream_frame` |
| 5 | Silent module-level test skips hide "steer's tests never ran" behind a green, exit-0 multi-module run | Fixed | `tests/test_steer_fixtures_required.py::test_a_missing_steer_cache_is_silently_green_by_default_in_a_multi_module_run`, `tests/test_steer_fixtures_required.py::test_a_missing_steer_cache_fails_the_run_when_fixtures_are_required` |
| 6 | Missing per-question exclusion records (aggregate counts only) | Fixed | `tests/test_steer_cases.py::test_flatten_response_includes_a_per_question_exclusion_ledger_not_just_counts`, `tests/test_steer_cases.py::test_write_excluded_writes_the_full_ledger_matching_the_pins_content_hash` |
| 7 | Vacuous Golden 5 (tautological by construction, never checks the classifier itself) | Fixed | `tests/test_steer_cases.py::test_golden_5s_sample_is_independently_verified_to_have_zero_correct_options` |
| 8 | Unsealed score evidence (`ScriptedSteerHarness` sealed only the raw served text, never the score) | Fixed | `tests/test_steer_e2e.py::test_scripted_harness_seals_a_score_recorded_event_before_the_evidence_seal` (also: the three pre-existing harness-driven e2e tests now call the new `record_score` and assert on the sealed `score_recorded` event) |

**Fix for #8** (this pass): `ScriptedSteerHarness` (`src/aeread_families/steer/harness.py`)
gains `submission_events` bookkeeping and a `record_score(score)` method that appends a
`score_recorded` event -- `primary_leaf_id`/`outcome_event_id`/`score`, mirroring
`aeread.shared_runner.family_evaluation.finalize_family_execution`'s own
score-before-seal convention exactly -- so a harness-driven episode's evidence seal
certifies "this outcome was scored as X," not merely "this raw text was served." The new
test fails with `AttributeError: 'ScriptedSteerHarness' object has no attribute
'submission_events'` against the pre-fix code. `tests/test_steer_e2e.py`'s three existing
harness-driven tests (`test_scripted_harness_runs_one_full_episode_per_declared_element`,
`test_scripted_harness_seals_evidence_for_an_illegal_submission`,
`test_scripted_harness_seals_evidence_for_a_malformed_submission`) were strengthened, not
weakened, to call `record_score` and assert `seal.event_count == 2` (previously 1) with
the second event's payload checked against the computed `ScoreEnvelope`.

**Summary: 8 fixed, 0 refuted, 0 deferred to the ledger.**
