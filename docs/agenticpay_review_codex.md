# Codex adversarial review — agenticpay adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **7**.

---

The review is complete, but the sandbox blocked writing `docs/agenticpay_review_codex.md`; the file remains absent and no worktree files changed. Full report follows.

## [CRITICAL] The case budget permits only half the upstream negotiation horizon

File: `src/aeread_families/agenticpay_bilateral/cases.py:588-590`; `src/aeread_families/agenticpay_bilateral/environment.py:298-320`; `src/aeread/shared_runner/scheduler.py:745-755`.

The importer copies upstream’s `max_rounds` directly into the case-wide logical-action budget, although every upstream round consumes two AERead actions. All checked-in cases therefore exhaust their budget after 10 of the declared 20 rounds.

Concrete failure scenario: repeatedly submit buyer `$80` and seller `$150`. After 10 completed rounds, the next buyer request raises `SchedulerContractError: case logical-action budget exceeded before termination`, so no timeout or scores are produced. A live pinned-bridge probe reproduced this.

Suggested fix direction: express the budget in seat-level actions and add a no-agreement test that reaches upstream’s actual timeout boundary.

## [HIGH] Out-of-range agreements publish values outside the declared support

File: `src/aeread_families/agenticpay_bilateral/measurement.py:419-437`; `src/aeread_families/agenticpay_bilateral/measurement.py:501-529`.

The basic scorer checks only that the ZOPA denominator is positive; it never verifies that the agreed price lies within the declared feasible interval. Upstream treats such agreements as invalid-range failures, while the adapter publishes unbounded shares with `status="ok"`.

Concrete failure scenario: for task 1 (`buyer_max=150`, `seller_min=80`), both parties submit `$200`. A focused probe returned buyer share `-0.7142857142857143` and seller share `1.7142857142857142`, despite declared reference bounds of 0 and 1.

Suggested fix direction: quarantine out-of-range agreements as invalid measurements before publishing normalized shares.

## [HIGH] Offline replay is unbound and labels incomparable results as matches

File: `src/aeread_families/agenticpay_bilateral/replay.py:109-137`; `src/aeread_families/agenticpay_bilateral/replay.py:219-231`; `src/aeread_families/agenticpay_bilateral/replay.py:367-406`; `tests/test_agenticpay_bilateral_replay.py:441-462`.

A recorded episode retains only `case_id` and decisions, omitting the case hash, family version, plan identity, and upstream pin. Moreover, when no original result exists, `comparison` is `None` but `status` returns `"match"`.

Concrete failure scenario: replay a task-1 record using a manifest with the same `case_id` but changed reservation prices and a valid new content hash. Replay accepts and scores the altered benchmark, then reports `"match"` despite performing no comparison.

Suggested fix direction: bind records to case and plan provenance, reject mismatches, and return `unverified` or `not_comparable` when no expected result exists.

## [MEDIUM] Repeating an unchanged legal contract is scored as illegal

File: `src/aeread_families/agenticpay_bilateral/measurement.py:325-364`; `src/aeread_families/agenticpay_bilateral/environment.py:140-153`.

Legality is inferred from whether the stored contract changed. Upstream accepts a valid repeated contract by assigning the same value, so state change is not equivalent to validation success.

Concrete failure scenario: in s01, the buyer submits valid contract C while the seller submits another legal but incompatible contract; next round the buyer repeats C and the seller submits C. Upstream agrees, but the adapter reports `round_2_buyer_contract_legal=0` and trajectory score `0.0`. A pinned-bridge probe reproduced this.

Suggested fix direction: return upstream’s explicit parse/validation result through the bridge instead of inferring it from state differences.

## [MEDIUM] Sealed evidence omits bridge results and scored outcomes

File: `src/aeread_families/agenticpay_bilateral/harness.py:58-79`; `src/aeread_families/agenticpay_bilateral/environment.py:420-446`; `tests/test_agenticpay_bilateral_replay.py:260-302`.

The harness seals only the phase, seat, and raw response before execution. Bridge results, pre/post state, terminal compatibility scores, and measurement outputs are not appended to that evidence store; tests reconcile only the served responses.

Concrete failure scenario: two bridge executions consume identical sealed messages, but one returns a corrupted `global_score`. Both evidence stores contain identical events and pass reconciliation, while their published results differ without any immutable record of which occurred.

Suggested fix direction: seal canonical bridge request/result records, state hashes, outcomes, and scores, then reconcile them against the episode result.

## [MEDIUM] Fidelity tests become successful skips unless an opt-in variable is set

File: `tests/test_agenticpay_bilateral_environment.py:41-70`; `tests/test_agenticpay_bilateral_measurement.py:287-316`; `tests/test_agenticpay_bilateral_replay.py:53-82`; `conftest.py:38-61`.

Bridge-backed tests skip when the checkout or interpreter is absent, while the hook converting those skips into failure is explicitly disabled by default. A normal test run can therefore succeed without exercising upstream fidelity.

Concrete failure scenario: run the agenticpay tests without a usable bridge and without `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1`. Fidelity tests skip, the summary hook returns at line 61, and pytest exits successfully even if delegation is broken.

Suggested fix direction: require the bridge in the adapter’s CI job and fail if zero fidelity tests execute.

## [LOW] Replay scoring expectations come from the scorer under test

File: `tests/test_agenticpay_bilateral_replay.py:346-370`.

The test computes both original and replayed scores using the same production scorer, then compares them. This proves repeatability but cannot detect a shared formula error.

Concrete failure scenario: change both basic surplus calculations to use the wrong denominator. Original and replayed scores change identically, so the assertions at lines 364-368 still pass.

Suggested fix direction: assert replayed values against independently hand-derived constants from the fixed trajectory.

## Summary

Critical: 1  
High: 2  
Medium: 3  
Low: 1

FINDINGS: 7
