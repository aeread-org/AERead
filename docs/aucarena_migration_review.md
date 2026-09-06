# aucarena migration review

Milestone 3 of 3 (`kernel_scoring_contract_spec.md`): enroll in the scoring-contract
protocol test and prove a receipt comes back. Unlike the govsim reference migration,
these findings were not supplied by an independent reviewer -- they were hit while
implementing the milestone, verified empirically before being fixed, and are recorded
here in the same disposition format the govsim precedent (`docs/govsim_migration_review.md`
on `zeyu/govsim-adapter`) established, so a later reader can check the reasoning rather
than trust it.

## Finding 1 — High: R9(b)'s sensitivity witness is structurally unsatisfiable for two
of this family's three trajectory-scoped leaves

- **What the code did**: `score_budget_invariant` returned `primary=1.0, metrics={}`
  whenever no seat's budget went negative; `score_hammer_rule` returned
  `primary=1.0, metrics={}` unconditionally on any successful (non-raising) replay. Both
  leaves are declared `input_scope="trajectory"`.
- **Why that is a problem**: `kernel_scoring_contract_spec.md` ruling R9(b) requires every
  declared `trajectory` leaf to be shown capable of changing across some same-case fixture
  pair the family supplies (`_assert_trajectory_leaves_are_witnessed`,
  `tests/test_shared_runner_scoring_contract.py`). `aucarena_budget_invariant`'s only
  violation path (`budget < 0`) is unreachable through this environment's own legality
  gate: `environment.py`'s `step()` never applies a bid that fails `bid_sanity_check`
  (`if not envelope.valid: continue`), so a winning bid's price was always ≤ the winner's
  budget at the time it was placed, and budget can never go negative on a legitimately-
  scripted episode. `aucarena_hammer_rule`'s only disagreement path raises
  `AucArenaMeasurementError` rather than returning a differing score, so a successful
  replay's envelope content is identical no matter how the auction played out.
- **Verified, not assumed**: built a hand-controlled, single-item/two-seat case and drove
  it through the real scheduler twice -- one round (agent bids the eventual hammer price
  directly) versus three rounds (both seats bid, then agent raises, then the field
  withdraws) to the identical winner and hammer price. Confirmed the terminal `outcome` is
  byte-identical and `phase_instances` genuinely differ, then confirmed
  `score_budget_invariant`/`score_hammer_rule` returned byte-identical `ScoreEnvelope`
  content for both trajectories on the *unmodified* scorer. This is the concrete
  before/after evidence for the fix below, not a comment asserting it.
- **Disposition: CONFIRMED, fixed.** Added `checked_transitions_count`/
  `replayed_rounds_count` diagnostics -- how many recorded states/rounds each leaf's
  independent check actually examined -- to their existing `metrics` dicts, mirroring
  `score_bid_legality`'s own `malformed_action_count` pattern already in this module. Pure
  bookkeeping: no violation-detection arithmetic, `primary` computation, or `status` logic
  changed. Re-ran the same hand-controlled pair against the *modified* scorer: both
  diagnostics now differ (1 vs. 3), witnessing both leaves.
- **Mutation check**: with the fix in place and all three of this milestone's fixtures
  wired into `_aucarena_fixtures`, dropped the fixture supplying the byte-identical,
  differing-round-count pair down to the single-round trajectory only (a `/tmp` backup +
  restore, never `git checkout`, on a file already fully committed at the time) --
  `test_every_registered_family_obeys_the_scoring_contract` failed on
  `aucarena_bid_legality_leaf`'s own witness (see Finding 2's mutation check below for the
  exact failure), confirming the paired fixture is load-bearing. Restored and reverified
  green before committing.
- **Stated limit**: this is a diagnostic, not a proof that either leaf reads the
  trajectory in a way that could ever catch a real violation on this environment; both
  leaves remain what `docs/aucarena_adapter_status.md` already calls them --
  "integrity/parity diagnostics on the environment's own rule application" -- and neither
  is primary or an admission leaf.

## Finding 2 — Medium: `aucarena_bid_legality`'s witness needs a genuinely illegal bid,
not just a longer trajectory

- **What the code did**: the same hand-controlled one-round/three-round pair above, both
  fully legal, produced byte-identical `score_bid_legality` content too (`metrics={}` on
  both -- no illegal bid, no malformed response).
- **Disposition**: not a defect to fix in `measurement.py` -- `score_bid_legality`
  already has a genuine violation path (an illegal bid is recorded and independently
  re-checked, contributing a `metrics` entry when it fails `bid_sanity_check`; golden 3's
  own `invalid_unauthorized` scenario already exercises this). The fix is a *third*
  same-case fixture (`illegal_bid_answer`): same case as the byte-identical pair, one
  seat's bid rejected as illegal, uncontested win for the other seat. `_assert_trajectory_
  leaves_are_witnessed` considers every same-case pair among all supplied fixtures, not
  only the two used for the paired-history/R7 check, so this third fixture does not need
  a matching outcome.
- **Mutation check**: dropping this third fixture (again via `/tmp` backup + restore, not
  `git checkout`) reproduced exactly the predicted failure --
  `aucarena_bid_legality_leaf never changed across any of the 1 same-case pair(s)
  examined among the 2 supplied fixtures` -- confirming the fixture is necessary, not
  decorative. Restored and reverified green before committing.

## Finding 3 — High: this family could never produce a receipt at all

- **What the code did**: `initial_state`'s second parameter was named `cell` and
  dereferenced (`cell.world_seed`). `task.evaluation._replay_family_trajectory` --
  `replay_family_scoring_input`'s own implementation, called internally by
  `finalize_family_execution` -- calls `plugin.initial_state(family_case, run=None)` by
  keyword. Every other already-migrated family in this codebase names that parameter
  `run`; this one still named and used `cell`.
- **Verified, not assumed**: drove a real episode through a hand-built `RunPlan` and
  `finalize_family_execution` before making any change. It raised
  `AttributeError: 'NoneType' object has no attribute 'world_seed'` inside
  `_replay_family_trajectory`'s very first call to `initial_state` -- this family had, in
  fact, never produced an `EvaluationReceipt`.
- **Disposition: CONFIRMED, fixed.** Renamed the parameter to `run` (matching every other
  migrated family) and, since replay supplies `None` there and `world_seed` must be
  reachable from `family_case` alone for `score_hammer_rule`'s RNG tie-break replay to
  reproduce the live episode's stream exactly, duplicated `world_seed` (already present at
  the outer `CaseManifest` level) into `payload.world_seed`. `cases.py`'s `build_case` was
  updated to write the same duplicate for every future import, and the five checked-in
  pilot goldens were regenerated through the real import CLI (not hand-edited) so their
  `content_sha256` stays internally consistent with `case_content_sha256`.
- **A second, related gap found while fixing this**: `resolve_run_plan` rejected the
  first hand-built `RunPlan` with `unreferenced implementation pins` for every one of this
  family's nine leaf-level implementation ids (the domain predicate plus each of the four
  leaves' distinct verifier-reference and scorer components), because `family_manifest()`
  named only `scoring.scorer_id`, never `scoring.reference_provider_ids`. Fixed by
  exporting those nine component ids (previously bare string literals inline in each
  `build_*_leaf`) as named constants (`measurement.REFERENCE_PROVIDER_IDS`) and declaring
  them on the manifest, mirroring govsim's identical field.
- **Verified end to end**: after both fixes, the same hand-built `RunPlan` drove a real
  episode through `finalize_family_execution` and returned `status="ok"`,
  `inclusion_status="included"`, all four declared leaf ids, and
  `primary_leaf_id="aucarena_profit_vs_field_leaf"` -- see
  `tests/test_aucarena_replay.py::test_finalize_wires_aucarena_to_the_shared_family_finalizer`.
- **Stated limit**: `world_seed` is now pinned to the case's own declared value rather
  than reachable from any per-replicate resampling a `RunPlan`'s sampling plan might
  otherwise vary through `PlanCell.world_seed`. This mirrors the tradeoff every other
  already-migrated family in this codebase that ignores its `initial_state`'s `run`/`cell`
  parameter entirely has already made (negarena, steer, tau3_retail, procurement_*,
  commercial_state_calibration, datacenter_development, consent_ir); it is not a new risk
  introduced by this family specifically, but it is worth a reviewer's attention if this
  family's sampling plan is ever changed to resample `world_seed` per replicate.

## Paired-history pair: constructible — yes, confirmed against real code

`docs/aucarena_migration_plan.md`'s milestone-0 finding ("a seat jumping straight to a
hammer price in round 0 instead of via intermediate rounds is still legal") is not merely
argued from reading `bid_sanity_check`/`check_hammer` -- it was built and run: a single-
item, two-seat case reaches the identical winner and hammer price (`1300`) in one round
(`short_path_answer`) and in three rounds (`long_path_answer`), with a byte-identical
terminal `outcome` and genuinely differing `phase_instances`, confirmed both by a
standalone probe against the live scheduler and by
`test_every_registered_family_obeys_the_scoring_contract`'s own R7 paired-history
assertion.

## Does a receipt now come back?

Yes. `test_finalize_wires_aucarena_to_the_shared_family_finalizer`
(`tests/test_aucarena_replay.py`) drives one real, provider-free episode through
`task.evaluation.finalize_family_execution` and asserts `status == "ok"`,
`inclusion_status == "included"`, exactly the four declared finalize-time leaf ids, and
`primary_leaf_id == aucarena_profit_vs_field_leaf` -- this family had never produced one
before this milestone (Finding 3).
