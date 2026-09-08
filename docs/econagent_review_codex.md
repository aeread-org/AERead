# Codex adversarial review — econagent adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **7**.

---

The review found 3 high- and 4 medium-severity defects. The requested file could not be created because the read-only sandbox rejected the authorized write; verification confirmed it remains absent. Complete findings follow.

## Boundary-month inventory corruption passes the budget identity

Severity: high

file:line: `src/aeread_families/econagent_v1/measurement.py:473-523`; `tests/test_econagent_measurement.py:269-319`

Concrete failure scenario: Increase an agent’s closing inventory by any positive amount on a saving-boundary month without changing income, tax, redistribution, consumption, or independently recorded interest. The unexplained increase becomes `saving_interest`, and the scorer checks only that it is non-negative. A direct probe adding 1,000,000 Coin returned `primary=1.0`, zero violations, and `max_abs_residual=1000000.0`. The tests cover off-cycle corruption and negative boundary residuals, but never positive boundary corruption.

## Replay accepts recorded responses for different inputs

Severity: high

file:line: `src/aeread_families/econagent_v1/replay.py:210-239`; `tests/test_econagent_replay.py:176-186`

Concrete failure scenario: Record `start_episode(n_agents=4, world_seed=0)` or one set of tax-recomputation incomes, then replay with different parameters. The replay bridge discards current arguments and validates only method order. A direct probe accepted `n_agents=99, world_seed=999` against the four-agent/seed-zero record. The unit test itself supplies live arguments against a record with empty arguments, codifying the incomplete contract.

## A bridge mutation can occur without a recorded outcome

Severity: high

file:line: `src/aeread_families/econagent_v1/econagent_bridge_driver.py:229-249`; `src/aeread_families/econagent_v1/replay.py:162-173`; `src/aeread_families/econagent_v1/environment.py:426-434`

Concrete failure scenario: The driver completes `env.step(actions)` but the process or pipe fails before returning JSON. The recorder appends only after the inner call returns, while canonical plugin state is also updated only after that return. Upstream state was mutated, but there is no dispatch/outcome record or corresponding sealed scheduler state. Retry cannot distinguish “not executed” from “executed, response lost.”

## Offline replay without an original is labeled `match`

Severity: medium

file:line: `src/aeread_families/econagent_v1/replay.py:586-625`

Concrete failure scenario: Invoke `replay_and_verify(..., original=None)`. Although `comparison` becomes `None` and the docstring calls this “not comparable,” `ReplayReport.status` returns `"match"`. A direct probe confirmed `comparison=None` produces `match`.

## Required bridge mode silently skips fidelity checks

Severity: medium

file:line: `tests/test_econagent_parity.py:43-55`; `docs/econagent_adapter_spec.md:417-421`

Concrete failure scenario: CI sets `AEREAD_ECONAGENT_BRIDGE_REQUIRED=1`, but the interpreter is missing. The tests never inspect the requirement flag and call `pytest.skip`. With the flag enabled and the bridge path deliberately invalid, the parity command exited 0 with three tests skipped.

## Random session IDs poison canonical state determinism

Severity: medium

file:line: `src/aeread_families/econagent_v1/environment.py:283-305`; `src/aeread_families/econagent_v1/replay.py:419-453`; `tests/test_econagent_replay.py:288-298`

Concrete failure scenario: Run the same case and plan cell twice with identical seeds. A fresh UUID enters every initial state and therefore changes scheduler pre/post hashes and frozen final state. The comparator excludes these raw hashes from its overall match result, and the test explicitly requires raw final-state inequality.

## Persistent bridge requests have no effective timeout

Severity: medium

file:line: `src/aeread_families/econagent_v1/econagent_bridge.py:322-350`

Concrete failure scenario: The driver hangs during `complex_actions` or `env.step` without closing stdout. `_request()` blocks indefinitely in `readline()`; `timeout_seconds` is not applied to persistent requests. No typed failure, terminal record, or sealed measurement is reached.

FINDINGS: 7
