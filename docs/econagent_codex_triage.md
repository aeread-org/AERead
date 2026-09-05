# Triage of docs/econagent_review_codex.md

Recovered from the triage author's returned text: its sandbox did not permit direct file writes, so this document is being saved on its behalf.

## Finding 1: Boundary-month inventory corruption passes

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/econagent_v1/measurement.py:418-428`, `src/aeread_families/econagent_v1/measurement.py:473-520`
- **Evidence**: Closing inventory determines the residual. On boundary months, the scorer rejects only negative residuals; every positive residual is accepted as interest. `all_pass` therefore remains true and produces `primary=1.0`. An in-memory probe adding 1,000,000 Coin to a boundary-month closing inventory returned `status="ok"`, `primary=1.0`, zero violations, and `max_abs_residual=1000000.0`. Thus corrupted inventory → unexplained positive residual → passing score.

## Finding 2: Replay ignores episode-start arguments

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/econagent_v1/replay.py:210-234`, `src/aeread_families/econagent_v1/replay.py:245-258`, `tests/test_econagent_replay.py:176-186`
- **Evidence**: `_next()` can compare arguments, but `start_episode()` deletes `kwargs` and calls `_next()` without them. The test records empty arguments, supplies live episode parameters, and expects success. An in-memory probe replayed a four-agent/seed-zero record using `n_agents=99, world_seed=999`; the recorded response was accepted. The income-recomputation portion of the old report has been fixed — `recompute_tax()` now passes incomes for comparison — but episode-start mismatch remains sufficient to confirm the finding.

## Finding 3: Mutation can precede every durable outcome

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/econagent_v1/econagent_bridge_driver.py:229-250`, `src/aeread_families/econagent_v1/econagent_bridge_driver.py:388-405`, `src/aeread_families/econagent_v1/replay.py:162-173`, `src/aeread_families/econagent_v1/environment.py:426-434`
- **Evidence**: The driver calls the mutating `env.step(actions)` before writing and flushing its response. The recorder appends a call only after `_inner.step_month()` returns, while the plugin updates its canonical state only after `bridge.step_month()` returns. If `env.step()` completes and the process or pipe fails before the response reaches the caller, upstream has executed the month but neither the replay log nor scheduler state records that fact. A retry cannot distinguish "not executed" from "executed, response lost."

## Finding 4: Uncompared offline replay is labeled match

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/econagent_v1/replay.py:605-618`, `src/aeread_families/econagent_v1/replay.py:621-645`
- **Evidence**: `replay_and_verify(original=None)` deliberately sets `comparison=None` and documents the result as not comparable. Nevertheless, `ReplayReport.status` returns `"match"` unless a non-`None` comparison explicitly mismatches. An in-memory `ReplayReport(comparison=None)` probe returned `"match"`. No comparison → unjustified match label.

## Finding 5: Required bridge mode still permits skips

- **Classification**: CONFIRMED
- **Location**: `tests/test_econagent_parity.py:27-55`, `conftest.py:11-19`, `conftest.py:38-68`, `docs/econagent_adapter_spec.md:417-421`
- **Evidence**: Bridge discovery converts unavailability into `BRIDGE_PYTHON=None`, and `_require_bridge()` unconditionally calls `pytest.skip`; neither reads `AEREAD_ECONAGENT_BRIDGE_REQUIRED`. The root pytest hook recognizes only `AEREAD_TAU2_BRIDGE_REQUIRED` and tau2-specific skip markers. Therefore setting the econagent requirement flag while providing no usable interpreter still yields skipped fidelity tests rather than the requested failure, allowing a zero-exit test run when nothing else fails.

## Finding 6: Random session IDs break canonical determinism

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/econagent_v1/environment.py:283-305`, `src/aeread_families/econagent_v1/replay.py:401-417`, `src/aeread_families/econagent_v1/replay.py:438-472`, `tests/test_econagent_replay.py:322-331`
- **Evidence**: Every `initial_state()` creates a fresh `uuid.uuid4().hex` and embeds it as `bridge_session_id`. The replay code explicitly acknowledges that this changes scheduler pre/post hashes and frozen final state, while `StateComparison.matches` omits both raw hash agreement and raw final-state agreement. Consequently, two executions with identical case, plan, and seeds produce different canonical states and hashes, yet the semantic comparison can still report a match. The test explicitly requires raw final-state inequality.

## Finding 7: Persistent requests do not enforce their timeout

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/econagent_v1/econagent_bridge.py:130-140`, `src/aeread_families/econagent_v1/econagent_bridge.py:301-350`
- **Evidence**: `timeout_seconds` is stored and used by `process.wait()` during shutdown, but `_request()` writes the request and then calls blocking `process.stdout.readline()` without any timeout mechanism. If `complex_actions` or `env.step` hangs while keeping stdout open, even a bridge configured with a one-second timeout remains blocked indefinitely instead of returning a typed timeout failure.

COUNTS: confirmed=7 refuted=0 kernel=0
