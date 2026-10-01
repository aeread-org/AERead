# Independent verification of the second-review fix pass

Cross-model check of whether each CONFIRMED finding was genuinely fixed and
whether its regression test has teeth. Recovered from the run transcript: the
verifier is read-only and could not write this file itself.

---

## Section 1: CONFIRMED findings

| Finding | Commit | Named regression test(s) | Verdict | Reason |
|---|---|---|---|---|
| 1. Boundary-month inventory corruption passes | `6cccdeb` | `test_score_budget_identity_rejects_a_boundary_month_residual_that_does_not_match_the_recorded_interest_rate` | GENUINELY FIXED | The scorer now compares residual against recorded rate × pre-interest balance (measurement.py:445, measurement.py:528); reverting that check makes the +1,000,000 test at test_econagent_measurement.py:374 pass incorrectly and fail its assertions. |
| 2. Replay ignores episode-start arguments | `37ed381` | `test_recorded_bridge_rejects_a_start_episode_argument_mismatch`; `test_replay_rejects_a_recorded_start_episode_argument_mismatch` | GENUINELY FIXED | `start_episode()` now supplies its arguments to `_next()` for equality checking (replay.py:222, replay.py:232); both direct and production-path mismatch tests require the resulting exception. |
| 3. Mutation can precede every durable outcome | `507f552` | `test_request_raises_a_distinctly_typed_error_when_a_step_month_response_never_arrives`; `test_golden_a_lost_step_month_response_is_a_distinctly_typed_mutation_outcome_unknown_error` | NOT FIXED | The commit only classifies the ambiguity: `env.step(actions)` still occurs at econagent_bridge_driver.py:266, before response write/flush at econagent_bridge_driver.py:484. The golden explicitly reproduces and accepts that condition, asserting only a new exception type (test_econagent_goldens.py:590). |
| 4. Uncompared offline replay labeled match | `3e7e3ad` | `test_replay_and_verify_without_an_original_reports_not_comparable_not_match` | GENUINELY FIXED | `comparison is None` now returns `not_comparable` (replay.py:633); reverting to the former fall-through `"match"` fails the assertions at test_econagent_replay.py:633. |
| 5. Required bridge mode permits skips | `2884df0` | `test_a_missing_upstream_checkout_fails_the_run_when_econagent_bridge_is_required` | GENUINELY FIXED | The EconAgent flag and skip markers are registered at conftest.py:50, and matching required skips set a failing exit status at conftest.py:84; the nested-pytest test requires nonzero exit at test_econagent_bridge_required_enforcement.py:67. |
| 6. Random session IDs break canonical determinism | `564a906` | `test_replay_reproduces_the_byte_exact_canonical_final_state_for_the_identical_cell` | GENUINELY FIXED | Scheduler-backed sessions now derive their ID from `cell.cell_id` (environment.py:541); reverting to UUID generation makes the byte-exact and session-ID equality assertions at test_econagent_replay.py:378 fail. |
| 7. Persistent requests ignore timeout | `6d6217b` | `test_readline_with_timeout_raises_before_a_hung_step_month_response_blocks_forever`; `test_golden_a_hung_step_month_request_times_out_instead_of_blocking_forever` | TEST WOULD NOT CATCH REVERT | Production now polls the pipe until a deadline and kills/raises on timeout (econagent_bridge.py:394), so the code fix is genuine. However, after reverting it, both tests block synchronously inside `_request()` before reaching their elapsed-time assertions (test_econagent_goldens.py:667, test_econagent_goldens.py:741); repository configuration contains no pytest timeout, so the named tests hang rather than fail autonomously. |

This was static inspection only; tests were not run, as requested.

## Section 2: weakened/deleted/loosened tests

None found in commits `6cccdeb`, `37ed381`, `507f552`, `3e7e3ad`, `564a906`, `6d6217b`, or `2884df0`.

Commit `564a906` replaced two pre-existing inequality assertions with stronger byte-exact equality assertions at test_econagent_replay.py:360; it did not remove the checks. No tolerance was widened, test skipped, or assertion weakened in the inspected diffs.

## Section 3: repository state

`git log --oneline origin/main..HEAD`:

```
a80cb5e docs(econagent): record second-review disposition for codex triage findings
2884df0 fix(econagent): enforce AEREAD_ECONAGENT_BRIDGE_REQUIRED in the root conftest
6d6217b fix(econagent): enforce the bridge's own read timeout on persistent requests
564a906 fix(econagent): derive bridge_session_id from the plan cell, not at random
3e7e3ad fix(econagent): label a genuinely uncompared offline replay not_comparable
507f552 fix(econagent): give a lost step_month response its own typed error
37ed381 fix(econagent): check start_episode arguments during replay
6cccdeb fix(econagent): check boundary-month interest against the recorded rate
afce2fa docs(econagent): triage codex review findings as confirmed
6db8ea8 docs(econagent): record codex adversarial review findings
7055e3d fix(econagent): verify replayed recompute_tax args and prove golden 3(a) via the real scheduler
610bf37 docs(econagent): record milestone-3 corrections and adapter status
84b00b6 feat(econagent): add offline replay with the bridge subprocess disabled
370894e fix(econagent): count one logical-action budget per seat, add scripted e2e harness
e36795b docs(econagent): record milestone-2 corrections against the adapter spec
7935c38 test(econagent): add independent oracle-vs-adapter parity harness
2e21a9d fix(econagent): source consumption_spend from month_actions, not the stale state field
7664965 test(econagent): add measurement leaf and scoring coverage
ec83d46 feat(econagent): add measurement leaves and bridge protocol for scoring
a339e67 test(econagent): add case-admission and environment import-level tests
e32aa54 feat(econagent): import the three pinned pilot scenarios plus the declared-not-run full config
334bcbb feat(econagent): add econagent_v1 family package (cases importer, bridge, environment plugin)
7106bd5 chore(econagent): add bridge venv provisioning for the pinned EconAgent checkout
7b2c6e9 docs(econagent): correct spec against pinned upstream (complex_actions location, cwd-relative reads, persistent bridge, seed floor)
13e37f0 docs(econagent): add adapter integration spec for EconAgent (ACL 2024)
```

`git status`:

```
On branch zeyu/econagent-adapter
Your branch is up to date with 'origin/zeyu/econagent-adapter'.

nothing to commit, working tree clean
```

The worktree is clean, all changes are committed, and the branch matches its configured remote-tracking branch.

VERDICT: PROBLEMS - Finding 3 remains structurally unfixed, and finding 7 lacks a regression test that fails rather than hangs when the timeout fix is reverted.
