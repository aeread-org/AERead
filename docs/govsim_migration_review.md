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

## Second review pass (2026-09-06)

<!-- Provenance: independent review supplied to the migrating agent for a second pass over
this same migration; reproduced verbatim below. -->
<!-- Disposition, verification, and mutation-test results appended by the migrating agent,
2026-09-06. -->

--- BEGIN REVIEW ---
2. Should-fix, medium — witness fixtures assert nothing about what they witness

`_govsim_fixture_pair` in `tests/test_shared_runner_scoring_contract.py` supplies four
fixtures against one shared `family_case`: the original paired-history pair (`left`,
`right` — a symmetric per-seat swap of identical aggregate demand) plus two witnesses added
later so govsim's two trajectory-scoped leaves could satisfy ruling R9(b) — a collapse
witness (a 49+49 harvest schedule intended to drive the pool under the collapse threshold)
and a threshold-breach witness (an asymmetric schedule, 15 against a threshold of 10,
intended to make one seat breach while the episode still reaches the horizon). The reviewer
confirmed the fixtures are correctly ordered (the original pair first, which the
paired-history check requires) and share one `family_case` (which the witness requires).

The gap: `test_govsim_obeys_the_scoring_contract` hands all four fixtures to the generic
kernel helper and asserts nothing about what each witness fixture actually did. The helper
proves each trajectory leaf changed on SOME same-case pair — not that the fixture named
`collapse_witness` actually collapsed, or that `threshold_breach_witness` actually breached.
If a schedule drifts (an upstream threshold changes, a harvest is clamped, the pool
regenerates differently) the fixture could stop doing what its name says while the witness
is still satisfied accidentally by some other pair, and nothing fails. The fixtures' intent
would silently rot.

FINDINGS: 1
--- END REVIEW ---

### Finding 2 — CONFIRMED, fixed

Verified against the code before acting:

- `_govsim_fixture_pair` (`tests/test_shared_runner_scoring_contract.py`, around line 1291)
  returns exactly the four fixtures the finding describes, in the order `left, right,
  collapse_witness, threshold_breach_witness`, all built from one shared `family_case`.
- `test_govsim_obeys_the_scoring_contract` (around line 2198, pre-fix) called
  `_assert_family_obeys_the_scoring_contract(key, registration, fixtures)` and returned,
  asserting nothing else — confirmed by reading the function body directly; no reference to
  `collapse_witness` or `threshold_breach_witness` by name existed anywhere in the test.
- Read the real scores the family produces for each fixture directly (a throwaway script
  driving `_govsim_fixture_pair` + `replay_family_scoring_input` +
  `registration.plugin.build_scorer` against the real bridge, bypassing nothing): both
  witnesses genuinely do what their names claim today —
  - `collapse_witness`: `govsim_no_collapse_leaf` primary `0.0`, `metrics["collapse_round"]
    == 1.0`, `outcome["num_round"] == 1 < max_num_rounds (2)` — a genuine early collapse,
    not a fabricated one.
  - `threshold_breach_witness`: `govsim_threshold_adherence_leaf` primary `0.0`,
    `metrics["round_0_persona_0_within_threshold"] == 0.0`,
    `metrics["round_0_persona_1_within_threshold"] == 1.0`,
    `outcome["num_round"] == 2 == max_num_rounds` — a genuine asymmetric breach that still
    reaches the horizon, isolated from collapse.
  - `left`/`right`: both leaves' primary is `1.0` (no collapse, no breach) — the clean
    baseline the paired-history check compares.
  So neither witness fixture is currently satisfied by accident; this finding is about the
  test's own coverage of that fact, not about the fixtures themselves being wrong today.

**Fix**: added explicit postconditions to `test_govsim_obeys_the_scoring_contract`, beside
the existing `_assert_family_obeys_the_scoring_contract` call, reading the leaf scores off
`result.produced_by_case` (the four fixtures in their own `left, right, collapse_witness,
threshold_breach_witness` order) and asserting, with a message naming the fixture and its
intent:
- `collapse_witness`: `govsim_no_collapse_leaf.primary.value == 0.0`, a `collapse_round`
  metric is present and equals `1.0`, and `outcome["num_round"] < max_num_rounds` (genuinely
  terminated by collapse, not by reaching the horizon);
- `threshold_breach_witness`: `govsim_threshold_adherence_leaf.primary.value == 0.0`,
  `metrics["round_0_persona_0_within_threshold"] == 0.0` (persona_0 identified as the
  breaching seat), `metrics["round_0_persona_1_within_threshold"] == 1.0` (persona_1
  compliant), and `outcome["num_round"] == max_num_rounds` (still reached the horizon, so
  the fixture isolates the breach from collapse);
- `left`/`right`: both `govsim_no_collapse_leaf.primary.value == 1.0` and
  `govsim_threshold_adherence_leaf.primary.value == 1.0` for each fixture (the clean
  baseline neither collapses nor breaches).

- **Test result (green)**: `tests/test_shared_runner_scoring_contract.py`,
  `tests/test_govsim_bridge_driver.py`, `tests/test_govsim_bridge_required_gate.py`,
  `tests/test_govsim_cases.py`, `tests/test_govsim_environment.py`,
  `tests/test_govsim_measurement.py`, `tests/test_govsim_parity.py`,
  `tests/test_govsim_replay.py`, `tests/test_govsim_replay_skip_behavior.py`, and
  `tests/test_shared_runner_smoke.py` together: 158 passed, 0 failed, 0 skipped, with
  `AEREAD_GOVSIM_BRIDGE_REQUIRED=1` and the real bridge exported.
- **Mutation check 1 (collapse_witness)**: changed `_GOVSIM_COLLAPSE_HARVEST_SCHEDULE` to a
  two-round, non-collapsing harvest (24+24, then 5+5 — well under the collapse threshold
  every round). In the full test, `collapse_witness` no longer being the sole source of
  `govsim_no_collapse` variation among the four fixtures means the PRE-EXISTING generic
  witness check (`_assert_trajectory_leaves_are_witnessed`, inside
  `_assert_family_obeys_the_scoring_contract`) fails first, before this test's own new
  assertions run — both checks correctly reject the mutation, but pytest only surfaces the
  first one. To confirm the new postconditions specifically, and independently of that
  ordering, a throwaway script called the two new assertions directly against the mutated
  fixture's real scores: both fired with their own messages —
  `"collapse_witness: govsim_no_collapse did not report the collapsed verdict (primary !=
  0.0) -- this fixture is named for a genuine early pool collapse"` and
  `"collapse_witness: the episode reached the horizon (num_round=2 == max_num_rounds=2)
  instead of terminating by collapse -- this fixture is named for a genuine early pool
  collapse, not for reaching the horizon"`. Restored from the `/tmp` backup (not
  `git checkout`, per project convention for mutating a file with uncommitted work) and
  reverified green.
- **Mutation check 2 (threshold_breach_witness)**: changed
  `_GOVSIM_ASYMMETRIC_THRESHOLD_BREACH_SCHEDULE`'s round-0 harvest from `{"persona_0": 15,
  "persona_1": 3}` to `{"persona_0": 8, "persona_1": 3}` (under the threshold of 10, so
  round 0 no longer breaches for either seat). Here `collapse_witness` remains a second,
  untouched source of `govsim_threshold_adherence` variation (it also breaches, at harvest
  49), so the pre-existing generic witness check still passes; the full test run reached
  this test's own new assertion and failed exactly there:
  `AssertionError: threshold_breach_witness: govsim_threshold_adherence did not report the
  breaching verdict (primary != 0.0) -- this fixture is named for a genuine per-agent
  threshold breach`. Restored from the `/tmp` backup and reverified green (single-test rerun
  of `test_govsim_obeys_the_scoring_contract`, then the full listed-file run above).

## Stated limits (second pass)

- The collapse-witness mutation above shows this fixture set has only one source of
  `govsim_no_collapse` variation (`collapse_witness` itself); a future fixture change that
  adds a second, independent collapsing fixture would let a `collapse_witness` regression
  hide behind the generic witness check the same way `threshold_breach_witness`'s regression
  did not (`collapse_witness` currently also happens to breach the threshold, which is why
  it backstops the threshold witness but nothing backstops it in turn). The new postconditions
  added here close that gap directly (they read `collapse_witness`'s own scores, not any
  other fixture's), independent of that ordering effect.
- As with the first pass, this closes a test-coverage gap, not a behavior change: both
  witness fixtures were already doing what their names claim (see the verification above);
  nothing in `src/aeread_families/govsim/` was touched.
