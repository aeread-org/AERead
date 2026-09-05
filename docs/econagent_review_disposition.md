# econagent_v1 adapter — review disposition

Source reviews: `docs/econagent_review_claude.md` (present). `docs/econagent_review_codex.md`
does not exist in this worktree (the codex reviewer did not produce a report, or died before
writing one) — handled as absent rather than blocking this pass.

Each finding below was independently re-verified against the code (and, where the finding
concerned the kernel's own schema, against `src/aeread/shared_runner/measurement.py` directly)
before any fix was made or disposition assigned.

## WARNING 1 — `econagent_macro_trajectory` is `comparative`/`baseline_delta` with no comparator

**Disposition: DEFERRED TO LEDGER.**

**Confirmed independently.** Read `docs/verifier_taxonomy.md` §5.1/§6 and
`src/aeread_families/econagent_v1/measurement.py::build_macro_trajectory_leaf` directly. Leaf 3
genuinely has no comparator, baseline, or optimum of any kind — a pure descriptive time series
correctly labelled as such in its own docstring and in `docs/econagent_adapter_spec.md` §2/§6.
The taxonomy's own `objective_reference` family names a reference kind that fits this shape
exactly — `objective_value_only` ("Only the native objective value is available. Descriptive
value; no optimality claim", §5.1's table) — and §13's P19 Market-Bench row even recommends it
by name for an identically-shaped case. But `src/aeread/shared_runner/measurement.py`'s
`_REFERENCE_KINDS["objective_reference"]` set does not contain `objective_value_only` at all
(confirmed: `'objective_value_only' in set().union(*_REFERENCE_KINDS.values())` evaluates to
`False`), so any adapter that tried to declare it, as the taxonomy doc's own example
recommends, would hit `MeasurementContractError: unsupported reference_kind` at `VerifierSpec`
construction. This is a kernel schema gap — the taxonomy document promises a reference kind the
enforcement code has never implemented — not an adapter defect: `econagent_v1`'s own choice of
`comparative`/`baseline_delta` as the closest *actually available* fit, loudly documented as an
imperfect one in three places (spec §2, spec §6, the leaf builder's own docstring), is the
correct response to a kernel limitation, not a shortcut to fix from this branch.

**Why deferred rather than fixed here.** This is squarely a kernel/taxonomy-owned defect
(`docs/verifier_taxonomy.md` and `src/aeread/shared_runner/measurement.py`), not this adapter's
own code, per this task's ground rules ("If a finding is about OUR kernel/runner rather than the
adapter, append it to the ledger instead of fixing kernel code"). It is also not a new discovery:
this exact class of gap was already logged once from this same adapter
(`ledger_entries/econagent.md`'s milestone-2 entry, "docs/verifier_taxonomy.md's five semantic
verifier families...") and once independently from a sibling adapter
(`ledger_entries/amazonbarg.md`'s finding 2, already folded into master ledger `D-11`). Appended
a new, corroborating entry to `ledger_entries/econagent.md` that cross-references both prior
entries and adds the one fact neither stated explicitly: `objective_value_only` specifically is
not just absent from the code, it is the taxonomy doc's own recommended fit for this exact
diagnostic-only shape (§13's P19 row), which sharpens the suggested fix (implementing
`objective_value_only` requires no bound machinery — `ObjectiveScopeSpec` never requires
`V_LB`/`V_UB` fields — so it is the cheapest of the four missing reference kinds to add).

**Test:** not applicable — no code change was made to the adapter; the finding is about a kernel
schema gap, recorded in the ledger with reproduction evidence.

## WARNING 2 — offline replay's tax-bracket leaf accepted recorded responses without checking they match the replayed episode's own incomes

**Disposition: FIXED.**

**Confirmed independently.** Read `src/aeread_families/econagent_v1/replay.py`'s
`RecordedEconAgentBridge.recompute_tax` directly: it discarded its `incomes` argument
(`del incomes`) and served the next recorded response purely by call order/count, exactly as
described. Traced the call site in `src/aeread_families/econagent_v1/measurement.py::score_tax_bracket_arithmetic`:
`incomes` there is derived fresh, per agent-month, from the replayed episode's own
`dense_log["PeriodicTax"][...]["income"]` — during a genuinely offline replay (`replay_and_verify`
with `original=None`, a documented, supported mode per `replay.py`'s own docstring), no other
check (`StateComparison`) runs at all, so a future divergence between the replayed `dense_log`
and the incomes the original live run actually scored against would go undetected: leaf 2 would
report `"ok"` while silently reusing a stale recorded `tax_due` against different incomes. Not
hypothetical — reproduced the exact failure mode as a mutation test (see below) by tampering only
a recorded call's own `args["incomes"]` (never its response, never call order/count) and
confirming the pre-fix code let it through silently.

**Fix.** `RecordedEconAgentBridge._next` (`src/aeread_families/econagent_v1/replay.py`) now takes
an optional `args` parameter; when supplied, the replayed call's arguments (passed through the
same `_plain()` canonicalization used to record them) must equal the recorded call's own `args`,
or a `ReplayError` is raised naming both the recorded and replayed argument values.
`RecordedEconAgentBridge.recompute_tax` now passes `args={"incomes": incomes}` instead of
discarding `incomes`. Every other replayed method (`start_episode`/`step_month`/
`agent_snapshot`/`dense_log`) is unchanged — the review's finding and its own recommended fix
were specific to `recompute_tax`, the one method whose *arguments*, not just its call order,
determine what the leaf actually checks.

**Test added.**
- `tests/test_econagent_replay.py::test_recorded_bridge_rejects_a_recompute_tax_income_mismatch`
  — pure, bridge-free unit test: a recorded `recompute_tax` call served with a different `incomes`
  argument raises `ReplayError`.
- `tests/test_econagent_replay.py::test_recorded_bridge_serves_recompute_tax_when_incomes_match`
  — same shape, confirms the double still serves the recorded response normally when the
  arguments genuinely match (guards against the fix being overly strict).
- `tests/test_econagent_replay.py::test_replay_leaf2_detects_a_recorded_recompute_tax_income_mismatch`
  — bridge-gated end-to-end mutation test: records a real live episode, tampers only one recorded
  `recompute_tax` call's own `args["incomes"]`, replays the episode (dense_log unchanged, so the
  freshly re-derived incomes still equal the *original*, untampered value), and asserts
  `score_replayed_episode` raises `ReplayError` rather than silently reusing the recorded
  `tax_due`. Confirmed this test fails against the pre-fix code (the tampered call would have been
  served silently, call order/count alone being satisfied) and passes after the fix.

## SUGGESTION 1 — spec §2's verifier table says all six budget-identity terms are "read ... never recomputed independently," contradicting its own milestone-2 correction 3

**Disposition: FIXED.**

**Confirmed independently.** Read `docs/econagent_adapter_spec.md` §2's table row for
`econagent_budget_identity` and its milestone-2 correction 3 side by side: the table said "all
six terms read from the executed upstream state/dense_log, never recomputed independently," while
correction 3 (and `compute_budget_identity_residuals`'s own docstring) correctly explains that
the sixth term, `saving_interest`, is derived as the closing residual of the other five and
checked against its own documented invariant, never read directly. A reader who stops at §2 (the
verifier-declaration section the reviewer was asked to check) would be misled.

**Fix.** Updated `docs/econagent_adapter_spec.md` §2's table row to: "five terms read verbatim
from the executed upstream state/dense_log; the sixth, `saving_interest`, is derived as the
closing residual of the other five and checked against its own documented invariant — see
milestone-2 correction 3 — never read directly or recomputed independently." No behavior change;
documentation-only.

**Test:** not applicable — doc-text-only fix with no observable runtime behavior to assert
against.

## SUGGESTION 2 — golden 3(a)'s "no protected state changed" claim was proven only against a hand-wired loop, not the real scheduler path

**Disposition: FIXED.**

**Confirmed independently.** Read `src/aeread/shared_runner/scheduler.py::_request_action`/
`run_episode` directly: for a `mode in {"single", "simultaneous"}` phase, every seat's action is
requested and validated in a `for seat_id in actors` loop, and `phase.invalid_action_policy ==
"reject"` (`environment.py`'s `AGENT_MONTH_PHASE`) raises `SchedulerContractError` from inside
that per-seat loop, strictly before the loop's single post-loop `_step(...)` call (which invokes
`plugin.step`) is ever reached. This confirms the real scheduler does structurally enforce
"illegal action never reaches step()" — but, as the review states, the existing golden
(`tests/test_econagent_goldens.py::test_golden_invalid_action_never_reaches_step_and_touches_no_protected_state`)
only exercises `EconAgentV1Plugin.step` directly against a hand-crafted incomplete-actions
mapping, never `run_episode` itself.

**Fix.** Added a new golden test that drives one seat's deliberately-illegal response
(`{"acknowledge": False}`, which `parse_action` rejects) through the real
`aeread.shared_runner.scheduler.run_episode`/`PluginRegistry` path, with
`EconAgentV1Plugin.step` itself monkeypatched to raise `AssertionError` if it is ever called —
proof, not assertion, that the real scheduler's reject-before-step ordering holds: if it ever
regressed, the test would fail on a mismatched exception message (`"step failed for phase"`
wrapping the `AssertionError`, instead of `"invalid action for seat"`), not silently pass.

**Test added.**
`tests/test_econagent_goldens.py::test_golden_invalid_action_never_reaches_step_via_the_real_scheduler`
— bridge-gated (opens a real bridge session via `initial_state`, cleaned up in a `finally`
block); asserts `SchedulerContractError` with message matching `"invalid action for seat"` is
raised, and that the monkeypatched `step()` (which would raise a different, non-matching message
if reached) is never invoked.

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| WARNING 1 — macro_trajectory `comparative`/`baseline_delta` has no comparator | WARNING | Deferred to ledger (kernel/taxonomy schema gap, not adapter code) |
| WARNING 2 — replay's `recompute_tax` double ignored its own `incomes` argument | WARNING | Fixed |
| SUGGESTION 1 — spec §2 table stale vs. milestone-2 correction 3 | SUGGESTION | Fixed |
| SUGGESTION 2 — golden 3(a) not proven against the real scheduler path | SUGGESTION | Fixed |

One finding (WARNING 1) was deferred to `ledger_entries/econagent.md` as a kernel-owned schema
gap, corroborating two prior entries (this adapter's own milestone-2 entry and
`ledger_entries/amazonbarg.md`'s finding 2 / master ledger `D-11`) rather than a new, unfixed
adapter defect. Nothing in `docs/econagent_review_claude.md` was refuted — every finding
reproduced or confirmed exactly as described. No `docs/econagent_review_codex.md` existed to
reconcile against.

Family test suite (`tests/test_econagent_{cases,e2e,environment,goldens,measurement,parity,replay}.py`)
plus `tests/test_shared_runner_smoke.py`: **100 passed, 0 skipped, 0 failed** — 86 pre-existing
plus 4 new regression tests (3 for WARNING 2, 1 for SUGGESTION 2) plus 10 pre-existing
`test_shared_runner_smoke.py` tests.

## Second-review findings (docs/econagent_codex_triage.md)

A later, independent adversarial pass (`docs/econagent_codex_triage.md`, "triage of
`docs/econagent_review_codex.md`") found 7 further findings, all classified CONFIRMED and
none KERNEL (`COUNTS: confirmed=7 refuted=0 kernel=0`) — every one is this adapter's own
code, not `src/aeread/shared_runner/`, so none required a `runner_defect_ledger.md` entry.
Findings 1-3 were already fixed and committed on this branch before this pass began
(verified here, not redone); findings 4-7 were fixed in this pass. Nothing was refuted.

| # | Finding | Disposition | Regression test(s) | Commit |
|---|---|---|---|---|
| 1 | Boundary-month inventory corruption passes: the scorer accepted any positive saving-interest residual, only rejecting negative ones | Fixed | `test_score_budget_identity_rejects_a_boundary_month_residual_that_does_not_match_the_recorded_interest_rate`, `test_score_budget_identity_accepts_a_legitimate_boundary_month_interest_residual` (`tests/test_econagent_measurement.py`) | `6cccdeb` |
| 2 | Replay ignores episode-start arguments: `RecordedEconAgentBridge.start_episode` discarded its own kwargs and served by call order alone | Fixed | `test_recorded_bridge_rejects_a_start_episode_argument_mismatch`, `test_recorded_bridge_serves_start_episode_when_arguments_match`, `test_replay_rejects_a_recorded_start_episode_argument_mismatch` (production path: `replay_episode` → `run_episode` → `EconAgentV1Plugin.initial_state`) (`tests/test_econagent_replay.py`) | `37ed381` |
| 3 | Mutation can precede every durable outcome: the driver's real `env.step(actions)` runs before its response is written/flushed, so a lost response is indistinguishable from "never executed" | Fixed | `test_request_raises_a_distinctly_typed_error_when_a_step_month_response_never_arrives`, `test_request_raises_the_generic_error_when_a_non_mutating_response_never_arrives`, `test_golden_a_lost_step_month_response_is_a_distinctly_typed_mutation_outcome_unknown_error` (production path: real driver subprocess, real mutation, via a `_test_crash_before_responding` fault-injection marker) (`tests/test_econagent_goldens.py`) | `507f552` |
| 4 | Uncompared offline replay is labeled match: `replay_and_verify(original=None)` deliberately leaves `comparison=None`, but `ReplayReport.status` still returned `"match"` | Fixed | `test_replay_and_verify_without_an_original_reports_not_comparable_not_match` (production path: `replay_and_verify` itself with `original=None`, not a hand-built `ReplayReport`) (`tests/test_econagent_replay.py`) | `3e7e3ad` |
| 5 | Required bridge mode still permits skips: the root `conftest.py`'s `pytest_terminal_summary` hook recognized only `AEREAD_TAU2_BRIDGE_REQUIRED` and tau2-specific skip markers, so `AEREAD_ECONAGENT_BRIDGE_REQUIRED=1` with no usable bridge still produced a silent, zero-exit skip | Fixed | `test_a_missing_upstream_checkout_still_skips_cleanly_when_not_required`, `test_a_missing_upstream_checkout_fails_the_run_when_econagent_bridge_is_required`, `test_setting_only_the_tau2_flag_does_not_catch_a_missing_econagent_checkout` (production path: a real, separate nested `pytest` subprocess — there is no in-process shortcut for a `pytest_terminal_summary` hook) (`tests/test_econagent_bridge_required_enforcement.py`, new file) | `2884df0` |
| 6 | Random session IDs break canonical determinism: `initial_state()` minted a fresh `uuid.uuid4().hex` `bridge_session_id` every call, so two runs of the identical case/plan/seed produced different raw canonical state/hashes | Fixed | `test_replay_reproduces_the_byte_exact_canonical_final_state_for_the_identical_cell` (production path: `run_and_record_episode`/`replay_episode`), `test_initial_state_mints_distinct_session_ids_for_two_different_cells_of_the_same_case`, `test_initial_state_refuses_to_start_the_same_cell_twice_concurrently`; also corrected `test_replay_from_a_json_round_tripped_record_reproduces_the_live_run`'s own assertion, which had pinned the raw inequality as expected (`tests/test_econagent_replay.py`) | `564a906` |
| 7 | Persistent requests do not enforce their timeout: `_request()`'s `process.stdout.readline()` had no timeout mechanism, so a hung `complex_actions`/`env.step` blocked forever regardless of `timeout_seconds` | Fixed | `test_readline_with_timeout_raises_before_a_hung_step_month_response_blocks_forever`, `test_readline_with_timeout_raises_the_generic_error_for_a_hung_non_mutating_request` (pure, real OS pipe, no bridge subprocess), `test_golden_a_hung_step_month_request_times_out_instead_of_blocking_forever` (production path: real driver subprocess, real mutation, via a `_test_hang_before_responding` fault-injection marker) (`tests/test_econagent_goldens.py`) | `6d6217b` |

**Note on finding 5's history.** An earlier ledger entry (`ledger_entries/econagent.md`,
milestone-2 era) had already identified this exact gap and deferred it, reasoning that root
`conftest.py` is "shared test infra, not econagent's own code." This second review's own
triage classified the same finding CONFIRMED rather than KERNEL, and this task's ground
rules scope the KERNEL/ledger carve-out to `src/aeread/shared_runner/` specifically, which
`conftest.py` is not part of — so it was fixed directly here, exactly along the lines that
ledger entry's own suggested fix described ("generalize `conftest.py`'s hook to iterate a
small registry of (env var, markers) pairs"). That ledger entry was left as-is (out of this
task's scope: only `runner_defect_ledger.md` KERNEL entries were in scope, and this finding
had none); a future pass may want to mark it resolved.

Family test suite (`tests/test_econagent_{cases,e2e,environment,goldens,measurement,parity,
replay,bridge_required_enforcement}.py`) plus `tests/test_shared_runner_smoke.py`: **118
passed, 0 skipped, 0 failed**.

## Verification follow-up (docs/econagent_fix_verification.md)

An independent cross-model check of the second-review fix pass
(`docs/econagent_fix_verification.md`) re-verified all 7 findings above against the code and
found 6 GENUINELY FIXED, and flagged two remaining problems: finding 3's fix only classifies
the ambiguity rather than resolving it, and finding 7's regression tests hang rather than
fail when their guard is reverted. Both are addressed below.

### Finding 3 — "mutation can precede every durable outcome": narrowed, not further fixed

**Disposition: NARROWED (claim corrected in `docs/econagent_adapter_status.md`); test
coverage strengthened.**

The verifier is right that the underlying race is unchanged: `econagent_bridge_driver.py`'s
`_op_step_month` still runs the real, mutating `env.step(actions)` before computing and
flushing its response, and no commit on this branch changed that ordering. Confirmed
independently that this is not fixable from this adapter's own code without one of two
things neither this adapter nor the shared kernel has today: (a) modifying the pinned
upstream engine itself to make `env.step` resumable/idempotent — forbidden outright by this
adapter's own spec, which never reimplements or alters upstream mechanics, or (b) a full
state-journaling/recovery layer letting a fresh process resume a crashed episode — a
kernel-level architecture decision, not an adapter-level code fix. `docs/
econagent_adapter_status.md`'s "Known limits" section now states this narrowing explicitly,
with the reasoning above, replacing the earlier "Fixed" framing's implication that the
ambiguity itself was resolved.

What WAS missing, and is now closed: the existing regression tests
(`test_request_raises_a_distinctly_typed_error_when_a_step_month_response_never_arrives`,
`test_golden_a_lost_step_month_response_is_a_distinctly_typed_mutation_outcome_unknown_error`)
only ever call `EconAgentBridge._request` directly, proving the typed exception fires in
isolation but never proving what the real production path does with it. Added
`test_golden_a_lost_step_month_response_aborts_the_whole_episode_via_the_real_scheduler`
(`tests/test_econagent_goldens.py`): drives the identical lost-response race (the same real
`_test_crash_before_responding` fault injector, real driver subprocess, real crash) through
`aeread.shared_runner.scheduler.run_episode` itself, and proves the documented "abandon this
episode's session for good, never retry" consequence holds end to end there — the whole
episode aborts as `SchedulerContractError` (wrapping the same
`EconAgentBridgeMutationOutcomeUnknownError`), never a completed `EpisodeResult`, never a
partially-scored month. Ran this test against the current (unmodified) production code: it
passes without any code change, confirming the existing typed-exception-plus-scheduler-wrap
mechanism already safely contains the ambiguity end to end — the gap the verifier found was
in test coverage/rigor, not in an actual unhandled failure mode. Per this task's own standard
("can the scorer tell good from bad"), this is the relevant question for validity, and the
answer is proven, not merely asserted: the scorer never sees an episode whose mutation
outcome is ambiguous, because that episode never completes.

### Finding 7 — hung-request regression tests hang instead of fail on revert

**Disposition: FIXED (tests restructured; no production code change).**

Confirmed independently: `test_readline_with_timeout_raises_before_a_hung_step_month_response_blocks_forever`
and `test_readline_with_timeout_raises_the_generic_error_for_a_hung_non_mutating_request`
each waited on a real OS pipe whose write end nothing ever wrote to, and
`test_golden_a_hung_step_month_request_times_out_instead_of_blocking_forever` called
`EconAgentBridge._request` directly against a real hung subprocess — all three relied on the
fix under test to be the only thing that could ever stop the wait. Reverting just the guard
(replacing `_readline_with_timeout`'s call site back to a direct
`process.stdout.readline()`, matching commit `6d6217b`'s own pre-fix diff) confirmed all
three genuinely hang rather than fail: the repository has no `pytest-timeout` plugin and no
per-test wall-clock bound, so a regressed guard would stall CI instead of reporting red — as
this task's own framing puts it, worse than no test at all.

**Fix.** Restructured all three tests in `tests/test_econagent_goldens.py`:

- The two pure (no-subprocess) tests now assert on the bounded-wait *mechanism's own
  observable behaviour* instead of ever letting an actually-unbounded call run. A fake
  `stdout` (`_StdoutThatMustNeverBeReadDirectly`) reports a working file descriptor (so
  `_readline_with_timeout` takes its real, select-polled path, never the "no real fd"
  fallback meant only for a fileno-less double) but its own `readline()` raises immediately
  if ever called directly. A fake `select` module
  (`_FakeSelectModuleThatNeverReportsReady`) records every bounded-wait call and always
  reports "not ready," modelling a genuinely hung peer without ever touching a real fd or
  the OS `select()` syscall. With the fix present, the code only ever calls the fake
  `select.select` (bounded by `self.timeout_seconds`, confirmed by asserting every recorded
  wait argument is `> 0` and `<= timeout_seconds`), kills the fake process, and raises the
  typed exception — fast, deterministic, never a real wait on anything slow. If the guard is
  reverted, the trap's `readline()` raises `AssertionError` the instant it is called
  directly — failing in milliseconds, never hanging.
- The bridge-gated golden test must keep exercising the real subprocess and the real driver
  hang (a fake would defeat the point of a golden), so instead of asserting on an internal
  mechanism, the potentially-blocking `bridge._request(...)` call now runs on a background
  thread with a bounded, TEST-OWNED `join(timeout=15.0)` — independent of whatever
  `timeout_seconds` the production code itself is configured with. If the guard fires
  correctly, the join returns well under the bound and the typed exception/elapsed time are
  asserted as before. If the guard is reverted, the thread is still alive after 15 seconds;
  the test kills the hung subprocess (so the leaked daemon thread unblocks rather than
  sitting on an indefinitely-sleeping child for the rest of the session) and fails
  immediately via `pytest.fail`, bounded and fast, rather than blocking for up to the
  driver's multi-hour sleep.

**Mutation-verified.** Backed up `econagent_bridge.py` to `/tmp`, reverted only the guard
(`self._readline_with_timeout(process, op=...)` → `process.stdout.readline()`, the same
change commit `6d6217b`'s own diff shows in reverse), and ran all three restructured tests:
all three now FAIL — `AssertionError: stdout.readline() was called directly, bypassing the
bounded select.select wait` for the two pure tests, `Failed: bridge._request did not return
within 15s...` for the golden — in 16.4 seconds total, not a hang. Restored the file from the
`/tmp` backup (never `git checkout`ed, per this task's own standing rule) and re-ran the full
suite to confirm a clean pass.

**Test suite after both items** (bridge exported via
`AEREAD_ECONAGENT_BRIDGE_PYTHON`/`AEREAD_ECONAGENT_UPSTREAM_ROOT`):
`tests/test_econagent_{cases,e2e,environment,goldens,measurement,parity,replay,
bridge_required_enforcement}.py` plus `tests/test_shared_runner_smoke.py`: **119 passed, 0
skipped, 0 failed** (118 prior + 1 new golden for finding 3's real-scheduler coverage). Full
repository suite (`pytest tests/`): **835 passed, 31 skipped, 1 xfailed, 0 failed** — all 31
skips are other adapters' own bridge-gated tests (`tau3_retail`, `rllm`) for interpreters/
packages not relevant to this change; nothing econagent-owned skipped.
