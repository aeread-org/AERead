Provenance: independent review of branch `zeyu/collusion-contract-migration` at commit `5e593c8c` (worktree `collusion-migrate`), reproduced verbatim below for verification.
Not authored by this document's author; verified against the code and dispositioned in the sections that follow.

--- BEGIN REVIEW ---
1. `src/aeread_families/collusion/environment.py:219` and `src/aeread_families/collusion/measurement.py:872`

   The primary/admission `collusion_long_run_profit` leaf is declared `finalize_time`, but the production scorer always supplies `baseline_profit_by_seat=None`, guaranteeing `invalid_measurement` rather than computing that leaf.

   Failure scenario: any otherwise valid Collusion episode finalized through `finalize_family_execution` returns `baseline_profit_not_provided` for the primary leaf and excludes the receipt, as explicitly demonstrated at `tests/test_collusion_replay.py:1209-1217` and asserted at `tests/test_collusion_replay.py:1276-1280`.

FINDINGS: 1
--- END REVIEW ---

## Verification

Re-derived independently against the code at the cited commit, not merely re-read from
the review's prose:

- `environment.py:219-222` — `family_manifest()`'s `measurement` block declares
  `"primary_leaf_id": measurement.LONG_RUN_PROFIT_LEAF_ID` and
  `"admission_leaf_ids": [measurement.LONG_RUN_PROFIT_LEAF_ID]`, with the leaf itself
  listed `"scope": "finalize_time"` at line 219. Confirmed exactly as cited.
- `measurement.py:872-875` — `CollusionScorer.__call__`, the seam
  `task.evaluation.finalize_family_execution` actually invokes
  (`plugin.build_scorer(family_case)(scoring_input, evidence_refs=...)`), calls
  `self.score_all(replayed_outcome, baseline_profit_by_seat=None, evidence_refs=evidence_refs)`
  unconditionally — there is no branch, no case data, and no code path in this method
  that ever supplies a non-`None` baseline. Confirmed exactly as cited.
- `score_long_run_profit` (`measurement.py`): `if baseline_profit_by_seat is None: return
  _invalid_measurement(leaf, reasons=("baseline_profit_not_provided",), ...)` runs before
  any `outcome["history"]` access, so the `"ok"` branch is unreachable whenever `__call__`
  is the caller.
- `src/aeread/shared_runner/measurement.py`'s `FamilyScoreSet.__post_init__` raises
  `MeasurementContractError("primary_leaf_id must also be an admission leaf")` if the
  primary is not in `admission_leaf_ids` — a kernel-enforced invariant, not a
  per-family convention. Combined with the manifest above, `collusion_long_run_profit`
  can never be decoupled from admission while it remains primary.
- `tests/test_collusion_replay.py:1209-1217` and `:1276-1280` — both citations are exact.
  `test_finalize_wires_collusion_to_the_shared_family_finalizer`'s own docstring states
  plainly that this is "a documented, structural fact, not a fixture defect" and its
  final assertions (`long_run_profit.status == "invalid_measurement"`,
  `long_run_profit.validity.reasons == ("baseline_profit_not_provided",)`) pin exactly
  this behavior. `receipt.inclusion_status == "excluded"` is asserted earlier in the
  same test.

The finding's factual claim is **true without qualification**: every receipt this family
produces through the real finalizer is `status="invalid_measurement"` /
`inclusion_status="excluded"`, for every trajectory, including a clean, fully legal
300-round episode, because the sole admission leaf can never score `"ok"` in production.

## Disposition

### Finding 1 — Disposition: confirmed; not independently fixable by a migration/fix
agent — escalated (architectural decision required).

The defect is real and reproducible exactly as described. It is not, however, a
mechanical migration bug with an available in-scope fix. Three candidate fixes were
considered and each is blocked for a stated reason:

1. **Substitute a case-derived closed-form baseline (e.g.
   `family_case["gold_reference"]["pi_nash"]`) inside `__call__`.** This was the
   author's own first instinct on reading the review, and it is wrong: `pi_nash` is the
   Nash-*vs*-Nash stage-game profit, and is only a valid stand-in for leaf 4's baseline
   when the real opponent condition is itself Nash. `tests/test_collusion_replay.py`'s
   own `shared_asymmetric_same_opponent_baseline_profit` fixture and
   `test_same_opponent_condition_baseline_differs_from_nash_vs_nash_pi_nash_for_an_asymmetric_opponent`
   prove the two values differ materially whenever the real opponent is not itself
   playing Nash (a previously triaged and fixed bug — `docs/collusion_codex_triage.md`
   "Finding 2: Profit baseline uses the wrong opponent condition"). The economically
   correct baseline is each seat playing the named Nash-play policy against the *same*
   real opponent *policy function* the live trajectory actually used — not that
   opponent's recorded price sequence replayed unchanged, since a reactive opponent
   (e.g. tit-for-tat, or an LLM-driven seat that reads the other seat's history) would
   have acted differently against a different counterfactual price each round. For a
   real, LLM-driven opponent that policy function is a live model, unreachable from
   `FamilyScoringInput` (`scoring_input.outcome`, `scoring_input.phase_instances`) by
   construction. Applying this "fix" would have silently reintroduced a previously-fixed,
   *worse* bug: a wrong `"ok"` score instead of an honest `invalid_measurement`.
2. **Fall back to re-simulating the baseline episode live at finalize time.** Forbidden
   by the frozen contract itself: `kernel_scoring_contract_spec.md` section 5 states
   agents decide none of "whether to fall back to live data when replay is incomplete
   (never — replay failure fails finalization)", and `replay_family_scoring_input`/
   `FamilyScorer.__call__(scoring_input, *, evidence_refs=...)` has no parameter through
   which a live policy or a second episode could be supplied.
3. **Remove `collusion_long_run_profit` from `admission_leaf_ids` while keeping it
   primary.** Blocked by a kernel-enforced invariant, not a style choice:
   `FamilyScoreSet.__post_init__` (`src/aeread/shared_runner/measurement.py`) raises
   `MeasurementContractError` unless the primary leaf is also an admission leaf. Spec
   section 3 states the same rule in prose ("The primary is always included"). Demoting
   `collusion_long_run_profit` from primary to make this leaf-4-specific admission
   change legal would mean picking a different headline metric, which is exactly the
   next option.
4. **Redefine the primary leaf's meaning to be self-contained** (own realized profit,
   not the delta against a baseline), mirroring govsim's `govsim_survival_months`
   shape, where the baseline is optional supplementary content rather than the value
   that gates `status`. Rejected for this milestone because it contradicts this
   family's own frozen spec: `docs/collusion_adapter_spec.md` section 4's golden table
   states golden 3's expected leaf-4 output as the delta itself ("Δπ≈+11.46/round"),
   not own profit. Changing that is a family-spec change, not a migration fix.

Every available fix is therefore either a violation of the frozen kernel contract, a
violation of this family's own frozen spec, or a reintroduction of a previously-fixed,
economically wrong measurement. Per this task's own boundary rule — an architectural
decision is not something a mechanical fix pass should guess at — this finding is
recorded as confirmed and escalated, not fixed. No production code was changed for this
finding. This matches, and independently re-confirms rather than merely repeats, the
disposition already on record for the same underlying defect in
`docs/collusion_adapter_status.md`'s "Receipt" section and in this repository's prior
`collusion_migration_review.md` review round (Findings 2/3, at commit `eeb59ecf`),
re-verified here directly against the code rather than taken on trust.

**No test was weakened, deleted, or loosened.** The existing
`tests/test_collusion_replay.py::test_finalize_wires_collusion_to_the_shared_family_finalizer`
already is the failing-test-first artifact for this exact defect: it drives a real,
fully legal episode through the real `finalize_family_execution` and pins the
`invalid_measurement`/`excluded` outcome as a documented, intentional assertion, not an
oversight. No new test was added for this finding, because no code changed for it to
guard.

**Open question for the spec/family owner** (not answerable by this pass): whether to
(a) extend the kernel contract's `deferred` scope to leaves blocked on a live
re-simulation artifact, not only a judge/rater verdict, (b) amend
`docs/collusion_adapter_spec.md`'s golden table to a self-contained primary (option 4
above), or (c) accept permanent exclusion pending a future live-baseline-recomputation
capability as the intended state. This is a decision, not a defect a code change can
resolve unilaterally.

## Summary

| Finding | Disposition |
|---|---|
| 1 | Confirmed — escalated, not fixed (architectural decision needed) |
