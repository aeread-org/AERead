# govsim migration review

<!-- Provenance: independent review supplied to the migrating agent for the govsim FamilyScoringInput migration; reproduced verbatim below. -->
<!-- Disposition (fixed/refuted), verification, and mutation-test results appended by the migrating agent, 2026-09-05. -->

--- BEGIN REVIEW ---
1. High — behavioral enrollment can silently skip

- file:line: `tests/test_shared_runner_scoring_contract.py:1183-1185`, `tests/test_shared_runner_scoring_contract.py:1452-1455`, `tests/test_shared_runner_scoring_contract.py:1462-1485`, `tests/test_govsim_replay.py:135-137`
- What the code does: The always-on catalog test counts govsim as enrolled through `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`. Its actual behavioral protocol test separately calls `_govsim_fixture_pair()`, whose imported `_bridge()` executes `pytest.skip(...)` whenever the upstream checkout or bridge interpreter is unavailable.
- Concrete failure scenario: On CI without the govsim checkout or bridge Python, `test_govsim_obeys_the_scoring_contract` skips. The catalog closure still passes because `("govsim", "0.1.0")` is counted as enrolled, leaving a green suite that never checks govsim's returned leaf set, provenance, determinism, or terminal-state scope.
- Violated requirement: The trusted family must be covered by the protocol test; a skippable test combined with unconditional enrollment accounting does not provide that coverage.

FINDINGS: 1
--- END REVIEW ---

## Disposition

### Finding 1 — CONFIRMED, fixed

Verified against the code before acting:

- `tests/test_shared_runner_scoring_contract.py`'s `_govsim_fixture_pair` (defined at
  line 994) calls `_govsim_bridge()`, which is `_bridge` imported from
  `tests/test_govsim_replay.py` (`from tests.test_govsim_replay import ... _bridge as
  _govsim_bridge`, line 141-143). `test_govsim_replay.py`'s `_bridge()` (lines 135-137)
  calls `pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")` whenever the
  pinned upstream checkout or bridge interpreter is unavailable.
- `test_govsim_obeys_the_scoring_contract` (around line 1462) is the only test that
  invokes `_govsim_fixture_pair`, so it skips under the same condition.
- `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS = frozenset({("govsim", "0.1.0")})` (around
  line 1180) is folded unconditionally into
  `test_every_registered_family_obeys_the_scoring_contract`'s
  `enrolled_family_versions` set (`set(fixtures) | _BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`,
  around line 1455), independent of whether `test_govsim_obeys_the_scoring_contract`
  actually ran to completion.
- Reproduced directly: with no `AEREAD_GOVSIM_BRIDGE_PYTHON`/`AEREAD_GOVSIM_UPSTREAM_ROOT`
  provisioned, `pytest tests/test_shared_runner_scoring_contract.py -q` reports
  `test_govsim_obeys_the_scoring_contract` as `SKIPPED` while
  `test_every_registered_family_obeys_the_scoring_contract` reports `PASSED`, and the
  overall run exits 0 — a green run that never exercised govsim's leaf set, primary,
  admission set, provenance, determinism, or terminal-state scope. Finding confirmed.

This is the same class of problem the project has already solved, repeatedly, for other
families whose fidelity claim depends on an out-of-repo bridge/checkout: tau2-bench,
econ-evals, STEER, auction-arena, AgenticPay, Alympics, and EconAgent each register an
`AEREAD_<FAMILY>_BRIDGE_REQUIRED`-style environment variable with the root `conftest.py`'s
`pytest_terminal_summary` hook, which turns a matching skip into a hard failure (exit
status 1) when the variable is set, and leaves local runs untouched (silent skip) when it
is not. govsim had no such entry, so there was no way to certify a run and have a missing
bridge be caught rather than silently accepted — exactly the gap the finding names.

**Fix**: added an `AEREAD_GOVSIM_BRIDGE_REQUIRED` entry to `conftest.py`'s
`_BRIDGE_FAMILIES` (matching both of govsim's own skip-reason shapes — missing checkout,
from `tests/test_govsim_replay.py`'s `_find_upstream_root()`, and missing bridge
interpreter, from `discover_bridge_python`'s `GovsimBridgeUnavailableError`) and
`_BRIDGE_FAMILY_DISPLAY`. Setting `AEREAD_GOVSIM_BRIDGE_REQUIRED=1` now converts a skip of
`test_govsim_obeys_the_scoring_contract` (or any other govsim bridge-gated test reusing
the same skip-reason text) into a failed run instead of a silent pass, while a plain local
run without the flag is unaffected. This does not change
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`'s or the closed-world catalog-closure test's own
semantics (both stay exactly as documented in their own comments), and it does not touch
`test_shared_runner_scoring_contract.py` or `test_govsim_replay.py` at all — no existing
test was weakened, loosened, or deleted.

- **Test written first (red)**: `tests/test_govsim_bridge_required_gate.py`, six cases
  mirroring the established `tests/test_alympics_wac_upstream_required_gate.py` pattern
  (calls the real `conftest.pytest_terminal_summary` against hand-built fake
  `terminalreporter`/`config` objects, never a reimplementation of the hook). Run against
  the pre-fix `conftest.py`, 3 of 6 failed:
  `test_govsim_checkout_skip_fails_the_run_when_required`,
  `test_govsim_missing_interpreter_skip_fails_the_run_when_required`,
  `test_tau2_gate_never_disturbs_the_govsim_gate` — each expecting `exitstatus == 1` and
  observing `0`, because no `_BRIDGE_FAMILIES` entry matched the govsim skip-reason text.
- **Fix applied**: the two `conftest.py` edits above.
- **Test result (green)**: all 6 cases in `tests/test_govsim_bridge_required_gate.py`
  pass.
- **Mutation check**: with the fix in place, the added `_BRIDGE_FAMILIES` tuple entry for
  `AEREAD_GOVSIM_BRIDGE_REQUIRED` was removed (via a `/tmp` backup + restore, not
  `git checkout`, per project convention for mutating a file with uncommitted work) and
  the same 3 of 6 cases failed again (`test_govsim_checkout_skip_fails_the_run_when_
  required`, `test_govsim_missing_interpreter_skip_fails_the_run_when_required`,
  `test_tau2_gate_never_disturbs_the_govsim_gate`), confirming the test suite actually
  detects the regression the finding describes. The fix was then restored from the
  backup and reverified green.

## Stated limits

- This closes the enrollment-accounting gap for any run that opts in via
  `AEREAD_GOVSIM_BRIDGE_REQUIRED=1`. It does not, by itself, force any particular CI job to
  set that variable — no such job existed for govsim before this change (govsim had no
  bridge-gated CI job at all, unlike agenticpay's dedicated `agenticpay-fidelity` job in
  `.github/workflows/ci.yml`), and wiring one (checkout + bridge provisioning in GitHub
  Actions) is a separate, larger piece of work than this migration's scope. This mirrors
  the already-accepted state of the identical mechanism for Alympics, auction-arena, and
  STEER, which also have no dedicated CI job today; the mechanism is a necessary condition
  for a certifying run to catch the skip, not a guarantee that GitHub Actions performs
  such a run.
- The mechanism keys off skip-reason text substrings, the same design already used by
  every other family's entry in `_BRIDGE_FAMILIES`; a future change to govsim's skip
  message wording would silently stop matching unless the corresponding test
  (`tests/test_govsim_bridge_required_gate.py`) is also updated and re-run.
