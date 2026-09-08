# Codex adversarial review — collusion adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **6**.

---

The review found 6 issues, including three HIGH-severity defects: malformed output incorrectly exhausts ten retries immediately; profit deltas use Nash-vs-Nash instead of the required same-opponent baseline; and unverified offline replays are labeled `match`. Three additional MEDIUM findings cover insufficient replay identity binding, undocumented distance aggregation, and incorrect parsing of scientific notation.

The sandbox rejected the sole authorized write because this session is read-only, so `docs/collusion_review_codex.md` was not created. The complete findings are preserved below:

## [HIGH] One malformed response is falsely reported as ten exhausted retries

File: `src/aeread_families/collusion/environment.py:438-450`; `tests/test_collusion_environment.py:277-295`; `tests/test_collusion_measurement.py:466-480`

Any parse failure immediately becomes `retry_exhausted`, while the paper permits ten attempts. If period 75 first returns malformed prose and then a valid price, the paper continues but this adapter terminates and invalidates every leaf.

Category: 1. Scoring/fidelity bugs; 2. Cheating tests.

## [HIGH] Profit delta uses the wrong opponent condition

File: `src/aeread_families/collusion/measurement.py:103-115`; `src/aeread_families/collusion/measurement.py:536-578`; `tests/test_collusion_measurement.py:287-297`; `tests/test_collusion_measurement.py:344-351`

The contract requires baseline profit under the same opponent condition, but the implementation subtracts Nash-vs-Nash profit. For monopoly play against tit-for-tat, it publishes the wrong delta whenever Nash play against that tit-for-tat opponent earns something other than Nash-vs-Nash profit.

Category: 1. Scoring/fidelity bugs; 2. Cheating tests; 5. Evidence gaps.

## [HIGH] Unverified offline replay is labeled `match`

File: `src/aeread_families/collusion/replay.py:99-127`; `src/aeread_families/collusion/replay.py:338-352`; `src/aeread_families/collusion/replay.py:355-383`; `tests/test_collusion_replay.py:265-298`

Recordings have no seal or expected trajectory digest. Editing a saved price and replaying with `original=None` produces `comparison=None` but still reports `status == "match"`.

Category: 5. Evidence gaps; 3. Silent skips or unreachable assertions.

## [MEDIUM] Replay is bound only to case ID

File: `src/aeread_families/collusion/replay.py:99-110`; `src/aeread_families/collusion/replay.py:130-150`; `src/aeread_families/collusion/replay.py:190-214`

The record omits the case digest and run-cell identity. Old decisions can therefore be replayed under changed economic parameters sharing the same case ID, producing different scores without rejection.

Category: 4. Identifier/determinism hazards; 5. Evidence gaps.

## [MEDIUM] Distance leaves discard the specified per-round gaps

File: `src/aeread_families/collusion/measurement.py:445-499`

The scorer publishes an undocumented whole-trajectory mean instead of raw per-round gaps. A half-Nash/half-monopoly trajectory can receive the same primary distance as constant midpoint pricing despite materially different dynamics.

Category: 1. Scoring/fidelity bugs; 5. Evidence gaps.

## [MEDIUM] Scientific notation is parsed as a different price

File: `src/aeread_families/collusion/environment.py:54-61`; `src/aeread_families/collusion/environment.py:138-146`; `src/aeread_families/collusion/environment.py:365-393`

`"My final price is 1e0"` is tokenized as `1` and `0`, after which the parser selects `0`. The run silently computes and scores price `0.0` instead of `1.0`.

Category: 1. Scoring/fidelity bugs.

FINDINGS: 6
