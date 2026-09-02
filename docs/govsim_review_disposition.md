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
