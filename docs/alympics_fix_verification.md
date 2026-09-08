# Independent verification of the second-review fix pass

Cross-model check of whether each CONFIRMED finding was genuinely fixed and
whether its regression test has teeth. Recovered from the run transcript:
the verifier is read-only and could not write this file itself.

---

## 1. CONFIRMED findings: fixes and regression tests

Runtime note: focused pytest could not start because the read-only sandbox had no usable temporary directory. The test conclusions below are based on observed diffs and assertions, not a fresh passing run.

1. **Finding 1 — `f1f4397`: partially addressed.** Post-salary balance is fixed, and winner history is added. However, the implementation explicitly remains a narrower proxy containing only `round_id`, `supply`, and `winners`; bids and upstream's fuller status history remain absent (`environment.py:546-578`, `docs/alympics_adapter_spec.md:123`).
   Test: `test_observe_shows_post_salary_balance_and_prior_round_public_winners_history` (`tests/test_alympics_wac_environment.py:249`). It would fail before the implemented salary/winner-history changes, but does not test the still-omitted history.

2. **Finding 2 — `80e3072`: not fully addressed despite being claimed fixed.** The commit binds a caller-supplied `baseline_policy_id` to the leaf and rejects mismatched labels, but never verifies that the supplied state was actually produced by that policy. The scorer calls it the caller's declaration (`measurement.py:640-667`), and the test proves an arbitrary `dummy_players` mapping is accepted when accompanied by the matching string (`tests/test_alympics_wac_measurement.py:241-265`).
   Tests: `test_declared_baseline_policy_id_is_part_of_the_leaf_1_2_reference_identity`, `test_scorer_leaves_for_focal_seat_threads_the_declared_baseline_policy_id_through`, `test_score_terminal_wealth_rejects_baseline_evidence_declared_under_a_mismatched_policy`, and `test_score_survival_rejects_baseline_evidence_declared_under_a_mismatched_policy` (`:176`, `:211`, `:229`, `:268`). These fail without the label-binding change, but **no test covers fabricated/unverified baseline data carrying the expected label**.

3. **Finding 3 — `80e3072`: addressed.** Missing legality evidence is distinguished from rounds the seat never played and invalidates legality, wealth, and survival scoring.
   Tests: `test_score_bid_legality_flags_a_round_with_no_legality_evidence_at_all`, `test_score_terminal_wealth_and_survival_reject_missing_legality_evidence`, and `test_score_bid_legality_still_skips_rounds_the_seat_never_played` (`tests/test_alympics_wac_measurement.py:655`, `:683`, `:723`). The first two would fail before the fix.

4. **Finding 4 — `80e3072`: addressed according to the triage's stated caveat.** Terminal wealth now reports actual and baseline alive-at-terminal metrics (`measurement.py:687-700`).
   Test: `test_score_terminal_wealth_flags_a_dead_focal_seats_frozen_balance_as_not_alive` (`tests/test_alympics_wac_measurement.py:414`), plus assertions in the golden at `:369-375`. These would fail before the metrics were added.

5. **Finding 5 — `80e3072`: addressed.** `comparison is None` now returns `not_compared` (`replay.py:423-440`).
   Test: `test_replay_and_verify_with_no_original_in_memory_never_fabricates_a_match` (`tests/test_alympics_wac_replay.py:435`). It would fail before the fix.

6. **Finding 6 — `f1f4397`: addressed.** `_load_upstream` compares the imported module's resolved `__file__` to the pinned checkout path (`environment.py:210-230`).
   Test: `test_load_upstream_rejects_a_waterallocation_module_already_bound_elsewhere` (`tests/test_alympics_wac_environment.py:712`). It would fail before the fix.

7. **Finding 7 — `80e3072`: partially addressed despite being claimed fixed.** The existing golden was strengthened to assert the actual elimination pattern (`tests/test_alympics_wac_measurement.py:336-351`), but its name still says "full survival," and the specification still falsely claims every focal seat survives 20 rounds with "full survival" (`docs/alympics_adapter_spec.md:101`).
   Test: the strengthened `test_golden_1_successful_reports_positive_wealth_and_full_survival`. There is no separate regression test that fails against the pre-fix production code; this was a test/documentation defect, and only the assertions were corrected.

8. **Finding 8 — `e77ea97`: addressed as documentation-only/no action.** The commit explicitly documents that malformed-action coverage is reachable only through the test-only hook (`docs/alympics_adapter_spec.md:124`).
   Relevant failing test: **none**, consistent with the triage's conclusion that this was disclosure rather than a production-code fix.

9. **Finding 9 — `9ec0827`: not fully addressed despite being claimed fixed.** The new gate works only when `AEREAD_ALYMPICS_UPSTREAM_REQUIRED` is explicitly set (`conftest.py:46-63`, `:81-83`). Default CI still runs plain `pytest tests/ -q` without provisioning the checkout or setting that variable (`.github/workflows/ci.yml:19-22`). Thus the original green-CI-with-five-skipped-modules scenario remains possible.
   Test: `test_alympics_upstream_skip_fails_the_run_when_required` (`tests/test_alympics_wac_upstream_required_gate.py:82`) would fail before the hook. Conversely, `test_alympics_upstream_skip_stays_silent_without_the_required_env_var` (`:69`) explicitly preserves the unresolved default behavior.

Claimed fixed but not fully fixed: **Findings 1, 2, 7, and 9**.

## 2. Weakened, deleted, or loosened tests

None found in the fix-pass commits.

The only replaced pre-existing assertion was in `f1f4397`, where the observation-leakage test changed its positive check from the obsolete pre-salary balance to the new post-salary balance and added negative checks for both other seats' raw and post-salary values (`tests/test_alympics_wac_environment.py:620-634`). That is a semantic update plus strengthening, not loosening. `80e3072` only added assertions/tests, and `9ec0827` added a new test module.

## 3. Repository state

`git log --oneline origin/main..HEAD`:

```text
0b436b3 docs(alympics_wac): record Codex-review findings disposition (fix pass)
9ec0827 fix(alympics_wac): silent upstream-checkout skip can now be required to fail CI
80e3072 fix(alympics_wac): enforce baseline provenance, missing-legality evidence, dead-seat wealth flag, replay not_compared status
f1f4397 fix(alympics_wac): credit this round's salary + public history in observe(), guard sys.modules provenance
436dcce docs(alympics_wac): triage second (codex) adversarial review
14e0710 fix(alympics_wac): reject near-duplicate grid cells (N2) + review disposition
e77ea97 fix(alympics_wac): address review M1/M2/N1/N3 findings
a180fa5 docs(alympics_wac): add milestone 3 adapter status (harness + replay evidence)
1aba4ed feat(alympics_wac): add scripted harness and offline replay (milestone 3)
de6c908 feat(alympics_wac): implement measurement leaves and QC Gate-2 goldens
5b65872 feat(alympics_wac): implement the environment plugin (Gate 2 trajectories)
3d65b5d feat(alympics_wac): author the 7-cell WAC parameter grid (Gate 1)
7e74aee docs: add alympics.wac adapter integration spec
```

`git status`:

```text
On branch zeyu/alympics-adapter
Your branch is up to date with 'origin/zeyu/alympics-adapter'.

nothing to commit, working tree clean
```

The tree is clean, and every present fix-pass change is committed. That repository state does not cure the four substantive partial fixes above.

VERDICT: PROBLEMS - Findings 1, 2, 7, and 9 remain only partially addressed, although the tree is clean and no tests were weakened.
