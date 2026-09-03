# govsim adapter — review disposition

Two review reports were expected (`docs/govsim_review_codex.md`,
`docs/govsim_review_claude.md`); only the Claude report exists in this
checkout (`git status` shows no `govsim_review_codex.md` on disk or in
history) — the other reviewer produced nothing to process. Every finding
below is from `docs/govsim_review_claude.md`, each independently
re-verified against the code before any fix, per this pass's own ground
rules (reviews can contain false positives; nothing here was fixed on the
review's word alone).

## CRITICAL

None reported by the reviewer, and none found independently.

## WARNING

### W1 — sheep/pollution scenarios had zero live-bridge test coverage

**Verified:** confirmed independently. `grep -n '"sheep"\|"pollution"'
tests/test_govsim_measurement.py tests/test_govsim_replay.py
tests/test_govsim_environment.py` returned zero hits before this pass — every
QC Gate-2 golden and both live-scheduler episodes hard-coded `"fishing"`,
even though `cases.SCENARIOS` declares three scenarios and the committed
corpus has 3 cases each for `sheep`/`pollution`.

**Disposition: fixed.** Added
`test_sheep_and_pollution_match_fishings_terminal_state_exactly_for_the_same_seed_and_policy`
(`tests/test_govsim_measurement.py`, parametrized over
`[s for s in govsim_cases.SCENARIOS if s != "fishing"]`), which drives both
`sheep` and `pollution` through the REAL bridge for both `sustainable_v1`
and `greedy_v1` and asserts the resulting terminal state is byte-for-byte
identical to the equivalent `fishing` episode — closing exactly the
regression-protection hole the reviewer described (a future
`_SCENARIO_ENV_CLASSES`/`POOL_LOCATION_BY_SCENARIO`/scenario-`env.py`
regression affecting only `sheep`/`pollution` would now diverge this
assertion instead of staying invisible). Verified green with the bridge
provisioned (`bridges/govsim-venv`).

### W2 — the invalid-unauthorized golden never drives the real scheduler; its comment overclaims what is checked

**Verified:** confirmed independently, with one correction to the finding's
implicit framing. Reading `scheduler.py`'s `run_episode` shows `actors =
_eligible_actors(...)` is passed straight from `plugin.eligible_actors()`
and the scheduler only ever requests an action from a seat in that set — so
"submit an action from a seat that is not the phase's eligible actor" (spec
section 4's literal description of this golden) is not a path the real
scheduler can ever take for this family; it is not merely undertested, it
is structurally unreachable through `run_episode` as written. The
reviewer's second complaint — that the existing test's comment
("No protected state changed and no credit earned... legal() never touches
the bridge at all") asserts more than the single `call_count` assertion
actually checks — is accurate as written.

**Disposition: fixed**, on the reachable half of the concern.
1. Tightened the comment on
   `test_golden_invalid_unauthorized_rejected_before_any_bridge_call_no_credit`
   (`tests/test_govsim_measurement.py`) to state precisely what the
   assertion supports, and to explain why this specific scenario cannot be
   reproduced end-to-end through `run_episode`.
2. Added
   `test_a_malformed_first_harvest_response_aborts_the_real_scheduler_with_a_reject_policy`
   (`tests/test_govsim_replay.py`), which drives `run_episode` for real and
   proves the actually-reachable form of the same contract: a
   legitimately-requested seat answering with a value `parse_action`
   rejects aborts the whole episode via `SchedulerContractError`, because
   `HARVEST_PHASE`'s `invalid_action_policy="reject"`. This is the
   govsim-specific, scheduler-driven proof the reviewer asked for; the
   "wrong seat" framing itself is not something a test can exercise through
   `run_episode` without bypassing the kernel's own request/eligibility
   contract, which would test a hypothetical, not the real path.

## SUGGESTION

### S1 — `measurement_kind: "comparative_or_human_judged"` mislabels a fully deterministic family

**Verified:** confirmed independently. `schemas.py`'s
`MeasurementDeclaration.from_dict` enum is exactly
`{"property_or_answer", "optimizable_outcome", "comparative_or_human_judged"}`
— no bare "comparative" value — and every leaf in `measurement.py` declares
`evaluation_class="deterministic"` with no rater/judge field anywhere.

**Disposition: fixed (adapter-side) + deferred to ledger (kernel-side).**
Added a comment at the `measurement_kind` declaration site
(`src/aeread_families/govsim/environment.py`'s `family_manifest()`)
clarifying the enum's imprecision and warning a downstream consumer to
branch on each leaf's own `evaluation_class`, never on this field. The
underlying cause — the kernel schema itself has no bare "comparative"
enum value — is a kernel limitation, not something fixable in this
adapter; recorded as ledger entry #6 in `ledger_entries/govsim.md` per this
pass's ground rules (never fix kernel code from this branch).

### S2 — `survival_months`/`total_harvest` lack `equality_gini`'s byte-for-byte upstream parity check

**Verified:** confirmed independently. `measurement.py`'s docstring argues
by code inspection (not a runtime check) that `terminal["num_round"]`
matches upstream's own `compute_survival_months_stats`; there is no
bridge call analogous to `GovsimBridge.call_upstream_gini` for these two
estimands.

**Disposition: deferred.** This is spec section 5's own disclosed P1–P3
backlog (`docs/govsim_adapter_status.md`'s "Known limits": "P1...P2...P3
...remain open follow-up work"), not a hidden gap — the reviewer says so
explicitly. Building a `survival_months`/`total_harvest` parity bridge op
against upstream's real multi-run analysis code
(`simulation/analysis/plots.py`'s `compute_survival_months_stats`, which
takes a dataframe of multiple runs, not one episode's terminal state) is a
new feature, not a fix to a defect in this milestone's own code, and is
already tracked as open follow-up work; left as-is rather than expanding
this fix pass's scope.

## Not defects (reviewer's own "checked and cleared" section)

The review's "Not defects (checked and cleared)" section (Gate-1 corpus
admission, replay honesty, "are all five goldens real", verifier-declaration
correctness, the `html_interactions` indexing workaround, and
`self.terminations` initialization) reports the reviewer's own independent
checks that turned up nothing to fix, not open findings. Spot-verified
during this pass (`legal()`'s `del action`/`eligible_actors()`'s `del
state`, `is_exportable_id` on every case id, `build_corpus()`'s duplicate
guard) and no discrepancy was found; no further action taken on this
section.

## Summary

| Finding | Severity | Disposition |
|---|---|---|
| W1 | warning | fixed |
| W2 | warning | fixed |
| S1 | suggestion | fixed (adapter) + deferred (kernel, ledger #6) |
| S2 | suggestion | deferred (already tracked as spec P1–P3) |

## Second-review findings

A second, cross-model adversarial pass (`docs/govsim_review_codex.md`,
triaged in `docs/govsim_codex_triage.md`) reported 7 findings, all
classified CONFIRMED by triage (0 refuted, 0 kernel). Each is disposed
below with the test(s) that close it; every fix runs against this family's
real production seam (the kernel scheduler, `family_evaluation.py`'s
finalizer call, or `validate_payload`/`_op_run_actions` themselves), never
a shortcut around it, per this pass's own ground rule.

### Finding 1 — Production scorer is not callable (CRITICAL)

**Disposition: fixed.** `GovsimScorer` gained `__call__`
(`src/aeread_families/govsim/measurement.py`), delegating to
`score_survival_months` (this family's declared `primary_estimand`) and
accepting `baseline_survival_months=None` so the comparative delta/reference
is honestly omitted, never fabricated, when no baseline is reachable from a
recorded outcome alone.

- `tests/test_govsim_measurement.py::test_govsim_scorer_is_callable_and_used_exactly_as_the_production_finalizer_calls_it`
  — pure unit test on the callable itself, on both the `ok` and
  `invalid_measurement` paths (`test_govsim_scorer_call_reports_invalid_measurement_for_an_operational_failure_outcome`).
- `tests/test_govsim_replay.py::test_govsim_scorer_is_callable_through_the_real_finalizer_seam_on_a_live_outcome`
  — closes the finding's own complaint that existing tests bypass the seam:
  drives a real episode through `run_episode` (the real kernel scheduler),
  takes `GovsimPlugin.outcome()`'s own real output, and calls
  `build_scorer(...)(outcome, evidence_refs=...)` exactly as
  `family_evaluation.py`'s `finalize_family_execution` does — never a named
  method, never a synthetic dict.

### Finding 2 — Replay reports match without comparing an original (HIGH)

**Disposition: fixed.** `ReplayReport.status`
(`src/aeread_families/govsim/replay.py`) now returns `"not_comparable"`
when `comparison is None`, distinct from both `"match"` and `"mismatch"`,
so a caller can no longer mistake an uncompared replay for a verified one.

- `tests/test_govsim_replay.py::test_replay_and_verify_reports_not_comparable_when_no_original_is_supplied`
  — calls the real `replay_and_verify()` production entry point with
  `original` omitted and asserts `status == "not_comparable"` and
  `status != "match"`. Confirmed fails-first: reverting the property to its
  pre-fix form reproduces `AssertionError: assert 'match' == 'not_comparable'`.

### Finding 3 — All upstream step exceptions become operational failures (HIGH)

**Disposition: fixed.** `govsim_bridge_driver.py`'s `_op_run_actions` now
catches only `AssertionError` (upstream's own malformed-action validation)
around `env.step()`; every other exception type propagates uncaught and is
reported by `main()`'s outer handler as an infrastructure failure
(`failed_action_index: null`), never downgraded to
`operational_failure`/`invalid_measurement`.

- `tests/test_govsim_bridge_driver.py::test_op_run_actions_still_downgrades_upstreams_own_malformed_action_assertion`
  — proves the one intended path still works.
- `tests/test_govsim_bridge_driver.py::test_op_run_actions_never_downgrades_a_non_assertion_exception_to_an_action_failure[exception0-2]`
  (parametrized over `KeyError`/`AttributeError`/`TypeError`) — proves each
  now propagates instead of being silently reframed as a malformed action.

### Finding 4 — Recorded source and dependency pins are not enforced (HIGH)

**Disposition: fixed.** Added `_verify_source_and_dependency_pins`
(`src/aeread_families/govsim/environment.py`), called from
`validate_payload` after the existing git checks: hashes
`concurrent_env.py`, each scenario's `env.py`, and `persona/common.py`
against `pins.json`, and, when a bridge is configured, compares
`bridge.runtime_info()` against `pins.json`'s recorded `bridge_versions`.
Reports every mismatch found, not just the first.

- `tests/test_govsim_environment.py::test_verify_source_and_dependency_pins_rejects_tampered_source_bytes`
  — a fabricated tree with no git repo at all, proving `git status`/
  `git rev-parse` alone cannot catch this.
- `tests/test_govsim_environment.py::test_verify_source_and_dependency_pins_accepts_the_real_pinned_checkout`
  — must not raise against the real, unmodified checkout.
- `tests/test_govsim_environment.py::test_verify_source_and_dependency_pins_rejects_a_runtime_dependency_mismatch`
  — a fake bridge reporting a mismatched `python_version`.

### Finding 5 — Replay is self-consistency, not required upstream parity (MEDIUM)

**Disposition: fixed.** Added `tests/test_govsim_parity.py`, the spec
section 5 file that did not previously exist:

- `test_p2_adapter_translation_matches_an_independently_constructed_raw_action_sequence`
  — reconstructs upstream's raw `harvesting`/`chat`/`home` action sequence
  independently from the harvest quantities a live kernel-scheduler episode
  actually chose (never by calling `GovsimPlugin.step()`), submits it
  directly to `GovsimBridge.run_actions` with no `GovsimPlugin`/scheduler
  involved, and asserts identical `resource_in_pool`/`collected_resource`/
  `num_round` — genuine adapter-vs-raw-upstream parity, not adapter-vs-adapter
  self-consistency.
- `test_p3_recorded_regeneration_and_collapse_match_the_documented_formula_independently`
  — independently recomputes the regeneration/collapse formula per round
  from a fresh bridge query and diffs against what the adapter recorded.

### Finding 6 — `num_agents` is omitted from case identity (MEDIUM)

**Disposition: fixed.** `case_id`
(`src/aeread_families/govsim/cases.py`) now appends `.n{num_agents}`
whenever `num_agents` differs from `DEFAULT_NUM_AGENTS` (5); the committed
9-cell corpus, which always uses the default, keeps its existing
unsuffixed `case_id` grammar exactly as before.

- `tests/test_govsim_cases.py::test_case_id_differs_for_different_num_agents_same_scenario_policy_seed`
  — proves the previously-colliding 1-agent/5-agent cases now produce
  different `case_id`s and different content hashes.
- `tests/test_govsim_cases.py::test_default_num_agents_case_id_is_unsuffixed_matching_the_committed_corpus`
  — proves the committed corpus's case IDs are unaffected.

### Finding 7 — Module-level skip suppresses bridge-independent tests (LOW)

**Disposition: fixed.** `tests/test_govsim_replay.py` no longer calls
`pytest.skip(..., allow_module_level=True)` at import time; the pinned
upstream checkout is looked up once (`_find_upstream_root`) and every
bridge-gated test skips individually through `_bridge()`, mirroring
`tests/test_govsim_measurement.py`'s existing per-test-skip convention.
Bridge-independent tests (JSON round-tripping, recorded-response ordering,
mismatch reporting, harness behavior) now always run and can fail on their
own.

- `tests/test_govsim_replay_skip_behavior.py::test_a_missing_upstream_checkout_skips_only_the_bridge_gated_test`
  — a subprocess-level test (collection-time behavior cannot be observed
  in-process) that points `$AEREAD_GOVSIM_UPSTREAM_ROOT` at a nonexistent
  path and asserts a bridge-independent test still collects and passes
  while only the bridge-gated test is skipped, and that "found no
  collectors" never appears.

### Second-review summary

| Finding | Severity | Disposition |
|---|---|---|
| 1 | critical | fixed |
| 2 | high | fixed |
| 3 | high | fixed |
| 4 | high | fixed |
| 5 | medium | fixed |
| 6 | medium | fixed |
| 7 | low | fixed |

No findings in this pass were refuted or deferred to the kernel ledger (the
triage itself reports `refuted=0 kernel=0`); `runner_defect_ledger.md` was
not touched.

## Verification follow-up

An independent cross-model verification pass (`docs/govsim_fix_verification.md`)
re-checked every "GENUINELY FIXED"/"fixed" disposition above against its own
named test and verdict: **PROBLEMS — Finding 5 remains incomplete, and
Finding 4 lacks a regression test for its production wiring.** Findings 1,
2, 3, 6, and 7 were independently confirmed genuinely fixed and were not
touched again in this follow-up. This section disposes of the two flagged
gaps, plus one narrowing the verification pass asked for explicitly.

### Finding 5 — P2/P3 checked only terminal aggregates, not every round

**Verified: confirmed.** `tests/test_govsim_parity.py`'s P2 test
(`test_p2_adapter_translation_matches_an_independently_constructed_raw_
action_sequence`) checked three terminal aggregate values only; P3
(`test_p3_recorded_regeneration_and_collapse_match_the_documented_formula_
independently`) checked per-round regenerated pool and collapse flags but
never per-round `collected_resource` — exactly spec section 5's own
worry, "a transient per-round collection/trace mismatch that later
converges to the same terminal aggregates" could pass both.

**Disposition: fixed.**

- P2 now loops over every round (reusing the existing per-round
  checkpoints `_independent_raw_action_sequence` already computes, one
  round further than P3's own pre-regen checkpoint — i.e. immediately
  after that round's `reflect`/`home` actions, the point at which raw
  upstream has already regenerated the pool and recomputed
  `terminations` for the round) and asserts, at every round: raw-upstream
  `resource_in_pool` against the adapter's own recorded
  `resource_in_pool_after_regen`; raw-upstream `collected_resource`
  against the cumulative sum of every prior round's recorded
  `wanted_resource` (upstream's own `collected_resource[agent] += res`
  and `wanted_resource[agent] = res` in the same call, so the two are
  identical by construction, not merely assumed to agree); and
  raw-upstream's own `terminations` dict against the adapter's recorded
  `collapsed_or_horizon` flag. The terminal-aggregate assertions remain,
  now reusing the final round's already-fetched projection rather than
  re-querying the bridge a second time for the same action sequence.
- P3 gained the one comparison its own docstring named but never
  asserted: per-round `collected_resource`, cross-checked at the same
  checkpoint/bridge call the test already makes (no new bridge calls),
  against the same cumulative-`wanted_resource` reconstruction P2 uses.

**Mutation-verified.** `src/aeread_families/govsim/environment.py` was
copied to `/tmp`, then `round_trace`'s recorded `"wanted_resource"` was
replaced with all zeros for every persona (a bug confined entirely to
per-round record-keeping). Result:
- `result.terminal["collected_resource"]` (read fresh from upstream's live
  projection, independent of `round_trace`) stayed correct —
  `{"persona_0": 120, ..., "persona_4": 120}` — confirming the OLD
  terminal-only checks would have stayed green against this exact bug.
- Both `test_p2_...` and `test_p3_...` failed immediately at round 0 with
  `AssertionError: round 0: ... collected_resource {'persona_0': 10, ...}
  != the cumulative sum of every round's recorded wanted_resource
  {'persona_0': 0, ...}`.

The file was restored from the `/tmp` copy (`git status --porcelain` on it
is clean) and the full suite re-run green afterward (see below).

### Finding 4 — no regression test drives the actual production call site

**Verified: confirmed.** Both existing tests
(`test_verify_source_and_dependency_pins_rejects_tampered_source_bytes`,
`test_verify_source_and_dependency_pins_rejects_a_runtime_dependency_
mismatch`) call the private `_verify_source_and_dependency_pins` helper
directly; the sole `validate_payload` test that exercises the real,
pinned checkout configures no bridge and never triggers the
dependency-mismatch branch at all. Deleting only the production call site
(`environment.py`'s `_verify_source_and_dependency_pins(self.upstream_
root, self.bridge)`, immediately before `validate_payload` returns) would
leave every one of those tests passing.

**Disposition: fixed.** Added
`test_validate_payload_rejects_a_dependency_mismatch_through_the_actual_
production_call_site` (`tests/test_govsim_environment.py`), which drives
the real, public `validate_payload` entry point end to end: a
`GovsimPlugin` constructed against the real pinned checkout (so every
git/schema check ahead of the pins check still passes) with a fake bridge
reporting a mismatched `python_version`, wired onto the plugin exactly as
a real caller would configure it — never the private helper called by
hand.

**Mutation-verified.** The production call site line was replaced with
`pass` in a `/tmp` copy of `environment.py`. Result: the three pre-existing
pins tests (tampered-source, accepts-real-checkout, runtime-mismatch, all
calling the private helper or configuring no bridge) all still passed;
the new test failed with `Failed: DID NOT RAISE ValueError`, reproducing
the reviewer's described gap exactly. The file was restored from the
`/tmp` copy afterward.

### Narrowing: Finding 1's "fixed" scorer claim

**Not reopened — narrowed instead, per this follow-up's own instructions.**
Finding 1's disposition above ("`GovsimScorer` gained `__call__`... GENUINELY
FIXED") is accurate for exactly what it tested: the callable no longer
raises `TypeError` and is exercised through the real finalizer seam. It
does not state that this `__call__` surfaces only ONE of this family's
five declared leaves (`govsim_survival_months`) and silently omits the
other four (`govsim_no_collapse`, `govsim_threshold_adherence`,
`govsim_total_harvest`, `govsim_equality_gini`) whenever invoked through
that seam. No test in this family was weakened, and no production code
changed here — `docs/govsim_adapter_status.md`'s "Known limits" section
gained a new bullet stating this explicitly and pointing at
`runner_defect_ledger.md`'s **D-16**, which records this as an open,
kernel-owner architectural decision (leaf-vector sealing vs. a declared
single kernel-facing leaf per family), not something this adapter can
settle unilaterally. `finalize_family_execution`'s only current call site
is `housing.py:940`, so this family is not actually reached through that
seam in production today — the gap is latent, not live, and is stated as
such rather than presented as a solved production path.

### Final test counts

`tests/test_govsim_cases.py`, `tests/test_govsim_environment.py`,
`tests/test_govsim_measurement.py`, `tests/test_govsim_replay.py`,
`tests/test_govsim_replay_skip_behavior.py`,
`tests/test_govsim_bridge_driver.py`, `tests/test_govsim_parity.py`, and
`tests/test_shared_runner_smoke.py`, run together with
`$AEREAD_GOVSIM_BRIDGE_PYTHON`/`$AEREAD_GOVSIM_UPSTREAM_ROOT` exported:
**118 passed, 0 failed, 0 skipped**, in 251.18s (one pre-existing
`RuntimeWarning` from `test_vendored_gini_matches_upstream_on_an_all_
zero_array_nan_case`'s deliberate zero-array NaN case, not introduced by
this follow-up).
