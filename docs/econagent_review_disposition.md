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
