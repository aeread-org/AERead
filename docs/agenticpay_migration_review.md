# agenticpay.bilateral migration — independent review and disposition

Reviewer: independent review of branch `zeyu/agenticpay-contract-migration`.
Author of this disposition: Zeyu, verified against the code before any fix was written.

## The review, verbatim

--- BEGIN REVIEW ---
1. `tests/test_shared_runner_scoring_contract.py:170-179`, `tests/test_agenticpay_bilateral_replay.py:78-92` — The shared protocol module imports the replay-test helpers, whose module initialization calls `_upstream_root()`. If the upstream checkout is absent, `pytest.skip(..., allow_module_level=True)` fires during import. This skips the entire shared scoring-contract test module—including every family’s protocol coverage—not merely AgenticPay.

2. `tests/test_agenticpay_bilateral_replay.py:94-105`, `tests/test_shared_runner_scoring_contract.py:2377-2404`, `tests/test_shared_runner_scoring_contract.py:2485-2500`, `tests/test_shared_runner_scoring_contract.py:2907-2910` — If the checkout exists but its bridge interpreter is unavailable, `_bridge()` skips AgenticPay’s behavioral protocol test. Nevertheless, the always-on closure test treats AgenticPay as enrolled through `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`. The suite can therefore pass without executing AgenticPay’s leaf-set, case-conditional, or trajectory-sensitivity checks.

FINDINGS: 2
--- END REVIEW ---

## Disposition

Both findings were independently re-verified against the code before any fix was written,
by driving a real pytest process (never a hand-called stand-in) under the exact
environment each finding describes.

### Finding 1 — module-level upstream-checkout skip cascades into the shared protocol module — **confirmed, fixed**

**Verification.** Ran `pytest tests/test_shared_runner_scoring_contract.py -rs -q` with
`AEREAD_AGENTICPAY_UPSTREAM_ROOT` pointed at a nonexistent path: the entire module
collapsed to `1 skipped` (`SKIPPED [1] tests/test_agenticpay_bilateral_replay.py:85: pinned
upstream AgenticPay checkout not found at ...`), with `--collect-only` reporting "no tests
collected". Targeting one specific, unrelated node id directly
(`tests/test_shared_runner_scoring_contract.py::test_every_registered_family_obeys_the_scoring_contract`)
under the same missing checkout produced `ERROR: found no collectors for ...` and exit code
4 — pytest could not even generate that test item, so whether housing's,
procurement_allocation's, procurement_grounding's, commercial_state_calibration's, and the
kernel-owned reference family's protocol coverage would have passed or failed was entirely
hidden behind AgenticPay's own missing checkout. Root cause confirmed exactly as named:
`tests/test_agenticpay_bilateral_replay.py:77-89`'s `_upstream_root()` called
`pytest.skip(..., allow_module_level=True)` at import time, and
`tests/test_shared_runner_scoring_contract.py:170-179` imports that module's helpers
(`UPSTREAM_ROOT`, `EvidenceRecordingAgenticpayHarness`, `_bridge`, `_case`, `_cell`,
`_script`) at module scope, so the `Skipped` exception raised during that import re-raised
during the importing module's own collection.

This is the exact failure mode this project has already fixed twice for other families
(`tests/test_govsim_replay_skip_behavior.py`, `tests/test_amazonbarg_upstream_skip_scope.py`)
— govsim's `tests/test_govsim_replay.py` is the direct precedent for the fix shape.

**Fix.** `tests/test_agenticpay_bilateral_replay.py`: renamed `_upstream_root()` to
`_find_upstream_root()`, returning `Path | None` instead of skipping; `UPSTREAM_ROOT` is now
`Path | None`; `BRIDGE_PYTHON`/`_BRIDGE_SKIP_REASON` computation is guarded on
`UPSTREAM_ROOT is not None`; `_bridge()` now skips per-test on
`UPSTREAM_ROOT is None or BRIDGE_PYTHON is None`. Every call site that dereferences
`UPSTREAM_ROOT` (`_run_live`, the three `bridge = _bridge()`-gated test bodies, and
`tests/test_shared_runner_scoring_contract.py`'s `_agenticpay_registration_and_pairs`) is
reached only after `_bridge()` has already skipped when the root is absent, so none of them
observes `None`. This mirrors `tests/test_govsim_replay.py`'s identical
`_find_upstream_root() -> Path | None` / guarded `_bridge()` shape exactly.

**Test:** `tests/test_agenticpay_bilateral_replay_skip_scope.py`
(`test_a_missing_upstream_checkout_skips_only_the_bridge_gated_replay_test`,
`test_a_missing_agenticpay_upstream_checkout_does_not_skip_the_shared_protocol_module`).
Both spawn a real, separate `pytest` subprocess (collection-time behavior cannot be observed
by importing an already-collected module in-process, mirroring the govsim/amazonbarg
precedent). Confirmed both fail against the pre-fix code (`found no collectors` in the
output for both a bridge-independent replay test run alongside a bridge-gated one, and for
the shared protocol module's always-on test run alone) and pass after the fix
(`2 passed`).

**Mutation check.** Reverted `tests/test_agenticpay_bilateral_replay.py` to the pre-fix
module-level-skip shape via a `/tmp` copy (never `git checkout` over uncommitted work) and
re-ran `tests/test_agenticpay_bilateral_replay_skip_scope.py`: both tests failed again with
the same `found no collectors` evidence, then restored the fixed file from the `/tmp` copy
and re-confirmed `2 passed`.

### Finding 2 — the always-on protocol test treats AgenticPay as enrolled without running its scorer, and CI never certifies the test that does — **confirmed, fixed**

**Verification.** Confirmed the structural claim by reading the code:
`tests/test_shared_runner_scoring_contract.py`'s `_build_protocol_test_registry_and_fixtures`
(used by the always-on `test_every_registered_family_obeys_the_scoring_contract`) registers
only housing, procurement_allocation, procurement_grounding, commercial_state_calibration,
and the kernel reference family — AgenticPay is never registered into that local registry.
AgenticPay's only real behavioral coverage is `test_agenticpay_obeys_the_scoring_contract`,
which calls `_agenticpay_registration_and_pairs` → `_agenticpay_bridge()` (`_bridge()` from
`tests/test_agenticpay_bilateral_replay.py`) as its first line — a per-test skip, independent
of the always-on test. `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` is consulted only by
`_assert_trusted_catalog_is_closed`'s closure check (ruling R6), which asserts every trusted
key is *accounted for*, not that its scorer ran.

Reproduced the claimed observable behavior directly: with a valid upstream checkout but
`AEREAD_AGENTICPAY_BRIDGE_PYTHON` unset and no colocated bridge venv,
`pytest tests/test_shared_runner_smoke.py tests/test_shared_runner_scoring_contract.py -q`
reported `68 passed, 1 skipped`, exit code 0 — a fully green run in which AgenticPay's
scoring contract never executed.

Then checked whether any existing enforcement already closes this gap and found it does
not, for a reason distinct from the mechanism itself: `conftest.py`'s
`pytest_terminal_summary` hook (the generic `AEREAD_<FAMILY>_BRIDGE_REQUIRED` skip-to-failure
mechanism) *does* work correctly for a skip raised inside
`tests/test_shared_runner_scoring_contract.py` — empirically confirmed by re-running the
same command with `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1`, which correctly printed the
"upstream bridge required: AgenticPay" banner and returned exit code 1. The actual gap is in
`.github/workflows/ci.yml`: the `agenticpay-fidelity` job is the only CI step that sets
`AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1`, and its `pytest` invocation named only
`test_agenticpay_bilateral_{cases,environment,measurement,replay}.py` — never
`tests/test_shared_runner_scoring_contract.py`. The `test` job's own `pytest tests/ -q` never
sets any bridge-required flag (by design, so a bridge/provisioning failure never blocks
every other family's PR). So `test_agenticpay_obeys_the_scoring_contract` ran, in CI, only
under the job that never enforces its skip — confirming the review's claim precisely, and
narrowing the fix to CI wiring rather than the enforcement mechanism itself.

**Fix.** Added `tests/test_shared_runner_scoring_contract.py` to the `agenticpay-fidelity`
job's `pytest` invocation in `.github/workflows/ci.yml`, alongside the four files already
there, with a comment explaining why. Extended
`tests/test_agenticpay_bilateral_ci_bridge_requirement.py`'s `_FIDELITY_TEST_FILES` tuple
(and its docstring) to include that file, so this wiring is itself enforced the same way the
original four files already were, and cannot silently regress.

**Test:** `tests/test_agenticpay_bilateral_ci_bridge_requirement.py::
test_ci_actually_runs_every_agenticpay_fidelity_test_file_under_the_bridge_gate` (existing
test, extended fixture list). Confirmed it fails against the pre-fix `ci.yml` (`no CI job
invokes tests/test_shared_runner_scoring_contract.py`) and passes after the fix.

**Mutation check.** Reverted `.github/workflows/ci.yml`'s added line via a `/tmp` copy
(never `git checkout` over uncommitted work) and re-ran the same test: it failed with the
identical assertion, then restored the fixed file from the `/tmp` copy and re-confirmed
`2 passed`.

**End-to-end confirmation of the certifying configuration.** Ran the exact file set and
environment the fixed `agenticpay-fidelity` job now runs
(`AEREAD_AGENTICPAY_BRIDGE_PYTHON`/`AEREAD_AGENTICPAY_UPSTREAM_ROOT` pointed at the real
provisioned bridge and pinned checkout, `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1`) against all
five files: `135 passed`, exit code 0 — AgenticPay's scoring-contract behavior (leaf set,
ruling R13's `contract_legality` case-conditional hook, and the trajectory-sensitivity
witnesses) now genuinely executes under the job whose whole purpose is to certify that it
does.

## Summary

| Finding | Disposition |
|---|---|
| 1 | Confirmed, fixed |
| 2 | Confirmed, fixed |

Neither fix touches the leaf set, the primary leaf, admission membership, or any estimand
definition — both are test-collection-scope and CI-wiring fixes. Neither was escalated.
