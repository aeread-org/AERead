# EconAgent migration — independent review and disposition

Review received 2026-09-06 for the econagent_v1 scoring-contract migration; verified
against `src/aeread_families/econagent_v1/` and `tests/` at commit `945b3040` on
branch `zeyu/econagent-contract-migration` before any finding below was acted on.

--- BEGIN REVIEW ---
1. `src/aeread_families/econagent_v1/environment.py:689` — Replay identity relies on a destructive, in-order FIFO and is neither order-independent nor repeatable (`popleft()` at line 715). Scenario: cells A and B run the same case, B finalizes before A, and B's replay consumes A's session ID, causing the sealed pre-state hash check to fail; repeating an audit after the queue entry was consumed similarly falls back to a different case-derived ID.

2. `tests/test_shared_runner_scoring_contract.py:1927` — The trusted-catalog closure counts EconAgent as enrolled unconditionally at lines 2316–2319 even when its protocol test is skipped for an unavailable checkout or bridge (`tests/test_econagent_replay.py:97` and `tests/test_econagent_replay.py:116`). Scenario: CI lacks the pinned EconAgent checkout or bridge interpreter; `test_econagent_obeys_the_scoring_contract` skips, but the catalog-closure test remains green and reports the trusted family as accounted for without behavioral protocol coverage.

3. `tests/test_shared_runner_scoring_contract.py:2029` — EconAgent is exempted from the protocol's paired-fixture checks and supplies only one fixture at lines 2336–2370; its separate pair test invokes the scorer directly and checks only `status == "ok"` (`tests/test_econagent_replay.py:849`–`887`). Scenario: all three trajectory-scoped scorers regress to constant successful outputs that ignore `phase_instances`; the direct pair test still passes because it never requires a score difference, while the shared protocol never receives the second fixture needed to detect the regression through its paired-history checks.

FINDINGS: 3
--- END REVIEW ---

## Disposition

### Finding 1 — CONFIRMED, escalated (owner decision)

The FIFO queue in `EconAgentV1Plugin._mint_session_id`
(`src/aeread_families/econagent_v1/environment.py:645-716`) is exactly as described: a
live cell mints a deterministic, cell-derived session id and enqueues it; the no-cell
replay/audit path (`initial_state(family_case, run=None)`, which is how
`task.evaluation._replay_family_trajectory` always calls it) has no way to name which
live episode it is replaying and can only `popleft()` the oldest still-queued id for
that `family_case`'s digest. This is order-dependent, not merely by omission but by
construction: the class's own docstring (`environment.py:199-240`) and the method's own
docstring (`environment.py:645-701`) already state the exact assumption the review
challenges — "FIFO order matters... each replay consumes its OWN corresponding id...
in the same order the fixtures were minted" — and already name the specific residual
risk verbatim in their own "Stated limit" paragraph: a second, later re-replay of an
already-consumed episode falls through to a case-digest id that disagrees with that
episode's sealed evidence. The review's scenario (two live episodes of an identical
`family_case`, finalized out of mint order) is the same failure mode reached a different
way: whichever episode is replayed second, out of order, gets the wrong id and fails the
sealed pre-state hash check.

Verified this is not fixable inside the family package: `initial_state(family_case,
run)` is the only hook the kernel calls during replay, `run` is always `None` on that
path, and evidence-derived disambiguation is not available to the plugin at the point it
must choose a session id, because the kernel hashes and compares the plugin's returned
state against the sealed `pre_state_sha256` only *after* `initial_state` returns — the
plugin has nothing to check candidate ids against before committing to one. The family's
own docstring reaches the same conclusion: "A future need for repeatable, idempotent
re-replay of the same episode would need a kernel-level fix (e.g.
`_replay_family_trajectory` threading the sealed evidence's own `cell_id` through as
`run`) rather than this family-local one." That kernel-level change would touch
`task/evaluation.py`'s replay call sites shared by all twelve migrated families, which is
outside one family migration's authority.

Confirmed as a genuine, currently-reachable gap (two cells sharing one `family_case` —
e.g. the identical case evaluated in two different evaluation blocks — is an ordinary
production shape, not a contrived one) and escalated for an owner decision on the
kernel-level fix the family's own analysis already points to.

### Finding 2 — REFUTED

Verified the closure test's mechanics match the review's description exactly:
`test_every_registered_family_obeys_the_scoring_contract`
(`tests/test_shared_runner_scoring_contract.py:2296-2323`) treats
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` as a static, unconditional enrollment set
(line 2318), independent of whether `test_econagent_obeys_the_scoring_contract` actually
ran or skipped that same test session. In isolation, the review's claim about that one
test's behavior is accurate.

It is refuted as a coverage-hiding defect because a second, already-built, already-tested
mechanism exists specifically for this and is not bypassed by it. The root `conftest.py`'s
`pytest_terminal_summary` hook (`conftest.py:126-192`) carries a dedicated
`AEREAD_ECONAGENT_BRIDGE_REQUIRED` entry (`conftest.py:93-105, 118`) whose skip-reason
markers ("pinned upstream EconAgent checkout not found",
"pinned upstream EconAgent Python interpreter") match, by direct inspection, both skip
paths the review cites: the module-level skip in `_upstream_root()`
(`tests/test_econagent_replay.py:97-101`) and `_require_bridge()`'s skip
(`tests/test_econagent_replay.py:116-118`, via `discover_bridge_python`'s error text at
`econagent_bridge.py:141-142`). When `AEREAD_ECONAGENT_BRIDGE_REQUIRED=1` is set (the
project's own documented convention for a certifying run) and either skip fires — from
*any* test file, including this one — the hook sets `session.exitstatus = 1`, failing the
whole run regardless of any individual test's own pass/skip status. This exact path is
already proven end-to-end by a real nested-`pytest` subprocess in
`tests/test_econagent_bridge_required_enforcement.py`
(`test_a_missing_upstream_checkout_fails_the_run_when_econagent_bridge_is_required`).
Reproduced directly for this review (see Verification below): with the flag set and the
bridge deliberately made unreachable, the overall run exits non-zero even though the
catalog-closure test itself still reports green.

For a run that does *not* set the flag, the skip-is-accepted behavior is the same,
uniform, pre-existing convention this project already applies to every other bridge-gated
family (tau2-bench, econ-evals, STEER, AgenticPay, Alympics) — not a defect specific to
this migration's enrollment wiring, and explicitly the intended behavior for the
deliberately-without-bridge run this task's own setup instructs never to certify with.

### Finding 3 — CONFIRMED, fixed

Verified both halves of the gap directly. `_SINGLE_FIXTURE_EXEMPT_FAMILIES`
(`tests/test_shared_runner_scoring_contract.py:2029-2049`) keeps `econagent_v1` out of
`_assert_family_obeys_the_scoring_contract`'s multi-fixture path entirely, so
`_assert_trajectory_leaves_are_witnessed` (ruling R9(b)) never runs for it. Read
`test_paired_history_pair_has_a_byte_identical_outcome_and_a_differing_trajectory`
(`tests/test_econagent_replay.py:782-887` before this fix) end to end: its final loop
(lines 875-887) asserts only `left_score.status == "ok"` and `right_score.status ==
"ok"` for each of the three leaves — no metric or content comparison at all. Empirically
confirmed (via a throwaway probe using the real bridge) that this specific pair's
`econagent_budget_identity`/`econagent_tax_bracket_arithmetic` metrics are also
*coincidentally* identical between its two fixtures (both report zero economic activity
by the pair's own deliberate construction), so even adding a content comparison to that
exact pair would not have witnessed those two leaves.

A true R9(b) same-case witness is independently confirmed to be structurally unavailable
for this family (`world_seed`/`beta`/`gamma`/`h` fully and deterministically determine the
whole trajectory — reproduced directly: two same-`family_case` fixtures produce
byte-identical `phase_instances`), matching this test module's own existing comment on
`_SINGLE_FIXTURE_EXEMPT_FAMILIES`'s `econagent_v1` entry.

Fixed with a new test,
`test_call_output_is_sensitive_to_phase_instances_for_every_declared_leaf`
(`tests/test_econagent_replay.py`), that witnesses non-constancy a different way: two
fixtures with the same `world_seed` but different `episode_length` (1 vs. 2 months)
produce, by construction, a different number of agent-months in their dense logs, so
`econagent_budget_identity`'s and `econagent_tax_bracket_arithmetic`'s own
`checked_agent_months` metric, and `econagent_macro_trajectory`'s own per-month metric
count, must differ if `__call__` reads its own call's `phase_instances`, and cannot differ
if it reads a cached, hardcoded, or otherwise constant trajectory instead. This proves
non-constancy, not genuine economic trajectory-dependence, which is the same class of
claim ruling R9(b) itself makes for its own (unavailable, for this family) same-case
witness.

**Test:** `tests/test_econagent_replay.py::test_call_output_is_sensitive_to_phase_instances_for_every_declared_leaf`

**Mutation result:** introduced the exact regression the review describes — cached
`EconAgentV1Scorer.__call__`'s first call's trajectory fields in a module-level variable
and reused them for every subsequent call, ignoring that call's own
`scoring_input.phase_instances` (a temporary, uncommitted edit to
`src/aeread_families/econagent_v1/measurement.py`, reverted immediately after). The new
test failed exactly as expected:

```
AssertionError: econagent_budget_identity_leaf: checked_agent_months is identical
across two fixtures with a different episode_length -- __call__ is not reading this
call's own phase_instances
assert 2.0 != 2.0
```

Reverted the mutation (`git diff --stat` on `measurement.py` confirmed byte-identical to
before the mutation) and re-ran the new test: passes.

## Verification of finding 2's refutation

```
$ AEREAD_ECONAGENT_BRIDGE_REQUIRED=1 AEREAD_ECONAGENT_BRIDGE_PYTHON=/nonexistent \
    AEREAD_ECONAGENT_UPSTREAM_ROOT=/nonexistent \
    .venv/bin/python -m pytest tests/test_econagent_replay.py \
    tests/test_shared_runner_scoring_contract.py::test_every_registered_family_obeys_the_scoring_contract \
    -q
```

confirms: pytest reports `1 passed, 1 skipped` —
`test_every_registered_family_obeys_the_scoring_contract` itself still passes (no
fixture in it depends on the EconAgent bridge) — and the module-level skip fires for
`tests/test_econagent_replay.py` with the exact reason the hook matches on
("pinned upstream EconAgent checkout not found at /nonexistent"). The process exit code
is `1`, not `0`: the overall run fails because of the `AEREAD_ECONAGENT_BRIDGE_REQUIRED`
terminal-summary hook, despite the one test that ran reporting green. "The closure test
is green" therefore never means "the run passed" once the certifying flag is set, which
is the guarantee the review's scenario needs and does not get to assume away.
