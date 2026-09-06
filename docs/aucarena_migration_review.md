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
- **Stated limit**: `run/resolver.py:588,1009` always sets `PlanCell.world_seed =
  case.world_seed` and `task/scheduler.py:353` rejects any mismatch, so a per-replicate
  `world_seed` resample is unreachable under the current kernel; the risk is hypothetical
  until the kernel changes.

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

---

## Independent review received 2026-09-06
Appended verbatim below, unedited; verification and disposition follow in the section after it.

### 5. Scoring logic newly written during migration

**Budget score gains a synthetic trajectory-length metric**
`src/aeread_families/aucarena/measurement.py:423-459`

The migration adds `checked_transitions_count` to the returned score specifically because the pre-existing violation path is unreachable. For the same case and byte-identical terminal outcome, the one-round fixture returns `1` while the three-round fixture returns `3`. Thus the budget measurement changes despite both runs satisfying the invariant, violating section 5's requirement to compose pre-existing scoring methods without inventing new scoring behavior.

**Hammer score gains a synthetic trajectory-length metric**
`src/aeread_families/aucarena/measurement.py:630-640,650-717`

The migration similarly adds `replayed_rounds_count` because successful hammer-rule checks previously produced identical scores. The one-round and three-round paths at `tests/test_aucarena_replay.py:757-785` now emit different hammer-leaf metrics solely from episode length, even though both reach the same winner, price, and terminal outcome. This manufactures sensitivity by changing the score schema rather than composing the family's pre-existing hammer score.

FINDINGS: 2

## Disposition of the 2026-09-06 independent review

Both findings were re-verified directly against the code and the frozen spec (not
re-read from the review's own characterization) before reaching a disposition, per this
task's standing instruction that reviews on this project contain false positives.

### Finding — budget score's `checked_transitions_count` (section 5, "Budget score gains a synthetic trajectory-length metric")

**Disposition: refuted.**

The factual observation is correct and was already disclosed, in the same terms, by this
document's own Finding 1 above (written during the migration, before this review
arrived): the one-round/three-round pair does yield `checked_transitions_count == 1` vs.
`== 3` for a byte-identical outcome, and the field exists only because
`aucarena_budget_invariant`'s violation path (`budget < 0`) is structurally unreachable
through this environment's own legality gate.

What does not hold is the conclusion that this violates
`kernel_scoring_contract_spec.md` section 5. Re-read against the code:

- Section 5 step 3's "no new scoring logic is written" clause is scoped, in the spec's
  own text, to `__call__`: "where it does not [have `score_all()`], `__call__` composes
  the existing named `score_*` methods and no new scoring logic is written." Verified
  directly: `AucArenaScorer.__call__` (`measurement.py:843-872`) does exactly that --
  calls the four existing named `score_*` methods and assembles a `FamilyScoreSet`, no
  arithmetic of its own -- and commit `24f07c4c` (the commit the review is describing)
  touches only the bodies of `score_budget_invariant`/`score_hammer_rule` themselves
  (plus `__all__` exports and swapping the bare component-id string literals in
  `_validity_domain` and the four `build_*_leaf` declarations for the new named constants;
  no version was bumped -- `LEAF_VERSION` is "1.0.0" on both zeyu/kernel-r9r10 and HEAD);
  `git show --stat 24f07c4c` and a per-hunk read confirm `__call__`/`build_scorer` are
  untouched by that commit. The clause the review cites does not, by its own text, reach
  this edit.
- The addition never changes `primary`, `status`, or `validity` -- confirmed by reading
  both functions end to end (`measurement.py:411-468`, `601-721`): `checked_transitions_count`
  is computed in a side counter and written into `metrics` after `primary` is already
  determined from `violations`; `replayed_rounds_count` is written into `metrics`
  alongside an unconditional `primary=1.0` that was unconditional before this commit too.
  Nothing about what either leaf measures or what counts as a violation changed.
- This is not a novel pattern for this module: `score_bid_legality`'s
  `malformed_action_count` (`measurement.py`, present since `0da9d811`, which predates
  every commit in this migration's own range `zeyu/kernel-r9r10..HEAD`) is the same shape
  -- a bookkeeping count of how much the check examined, alongside its violations, never
  folded into `primary`.
- Most directly: `kernel_scoring_contract_spec.md` ruling R9(b), together with its
  fourth-pass refinement (`docs/kernel_r9r10_review.md`, "W1", lines 546-654, commit
  `330765c1`, dated one day before this migration's own fix commit), is a *kernel-level*,
  already-ratified decision that the sensitivity witness is deliberately weak: "a sanity
  check... not a proof of trajectory-dependence" that is satisfied by *any* same-case pair
  on which the leaf's measurement content differs, including — the ruling's own worked
  counterexample, govsim's `no_collapse` — a leaf whose witnessing difference comes from
  an outcome field, never the trajectory at all, "and that is accepted rather than guarded
  against." A diagnostic that counts genuinely-read trajectory content
  (`phase_instances`/`transitions`, not an outcome field) satisfies that already-accepted
  bar by a comfortably wider margin than the counterexample the kernel authors
  themselves designed the rule around.

No code change made. This document's own pre-existing "Stated limit" note under Finding 1
already says plainly that the diagnostic is not a proof either leaf could catch a real
violation on this environment — the same substantive point the independent review makes —
so nothing here is newly disclosed; only the "spec violation" characterization is rejected.

### Finding — hammer score's `replayed_rounds_count` (section 5, "Hammer score gains a synthetic trajectory-length metric")

**Disposition: refuted**, for the same reasons as the budget finding above, verified
independently against `score_hammer_rule` (`measurement.py:601-721`) rather than assumed
to follow from the budget finding's disposition: `replayed_rounds_count` is written into
`metrics` only, `primary` remains the unconditional `MetricValue(1.0, "pass")` it was
before commit `24f07c4c`, and the modification lives in the pre-existing named
`score_hammer_rule` method, not in `AucArenaScorer.__call__`. The same kernel-level R9(b)/W1
ruling governs both leaves identically, since both are declared `input_scope="trajectory"`
leaves facing the same sensitivity-witness requirement.

No code change made.

---

## Second independent review (2026-09-06)

A second, later independent review of the same `24f07c4c` diagnostic-metric change raised two
new findings, distinct from the ones dispositioned immediately above (those argued the metrics
violated a spec clause; these accept the leaf scoping and the "no new scoring logic" reading and
instead attack the *quality* of the R9(b) witness itself, plus a test regression in the same
commit). Recorded verbatim below, then disposition, test names, and mutation results.

### Finding 1 (should-fix, medium) — verbatim

> the witness is satisfied only by trajectory CARDINALITY, which hollows out its signal.
> `checked_transitions_count` counts transitions and `replayed_rounds_count` counts phase
> instances; neither reflects budgets, violations or state content (measurement.py around lines
> 438, 456, 650, 661). The family's fixture pair differs only in round count (1 round vs 3
> rounds). The reviewer's concrete failure scenario: delete the budget inspection
> (measurement.py ~443-455) or the hammer recomputation/comparison (~661-706), keep the
> counters, and R9(b) still passes even though the leaf no longer checks anything.

The finding's requested fix, in order of preference: (a) follow `collusion`'s precedent and make
each leaf's own `status`/`primary` vary on a same-`family_case` fixture, sealed adversarially or
malformed if necessary; (b) if a genuine violation cannot be sealed for a leaf, do not fabricate
one — keep the counter, and write the limit down precisely (which leaf, why its verdict cannot
vary on any sealable trajectory, that R9(b) is satisfied by check-extent rather than verdict
variation, and the failure scenario above as a stated limit), stated plainly, not softened.

**Disposition for `aucarena_budget_invariant`: (b) — a genuine violation cannot be sealed.**
Verified by reading, not assumed: `envelope.valid` (the only gate through which a bid can ever
reach `step()`'s state mutation) is computed by the *shared kernel scheduler itself*
(`src/aeread/shared_runner/task/scheduler.py`: `valid = parsed.ok and legality is not None and
legality.legal`), never by this family's own code, and `AucArenaPlugin.legal()`
(`environment.py`) calls the same `vendored.bid_sanity_check` that already rejects `bid_price >
budget`; `step()` never folds an invalid action into `round_bids`
(`if not envelope.valid: continue`). Chasing this through `win_bid`
(`_vendored_upstream.py`: `new_budget = budget - bid`) by induction over every item a seat bids
on — each win only ever subtracts an already-legal, budget-bounded amount from that seat's
*current* budget (already reduced by any prior win) — shows no sequence of raw scripted
responses driven through the real scheduler can ever produce a negative recorded budget,
regardless of how adversarial or malformed the responses are. The `illegal_bid_answer` fixture
already checked into this repo (`tests/test_aucarena_replay.py`, used by
`tests/test_shared_runner_scoring_contract.py`'s `_aucarena_fixtures` to witness
`aucarena_bid_legality`) is exactly this family's version of collusion's malformed-round
precedent — a scripted response that is illegal (`"500"`, below the item's starting price) — and
it does *not* move `aucarena_budget_invariant`'s verdict, because the illegal bid is rejected by
`legal()` before it can ever reach `step()`'s budget mutation; that is concrete evidence a
fixture was tried, not merely argued to be impossible. The only way to force a negative recorded
budget would be to fabricate `TransitionResult.state` directly instead of deriving it from a
live episode — not a sealed fixture in the sense this family's other witnesses are — so no
fixture was added. Limit written down in `docs/aucarena_adapter_status.md`'s "Known limits"
section (new bullet), stated plainly rather than softened, including the reviewer's own failure
scenario verbatim.

**Disposition for `aucarena_hammer_rule`: (b) — a differing verdict is unreachable by
construction.** `score_hammer_rule`'s only disagreement path (`measurement.py`, the
`if recorded != recomputed: raise AucArenaMeasurementError(...)` branch) raises immediately
rather than returning a differing `ScoreEnvelope`; a disagreement, if one were ever reachable,
aborts finalization instead of scoring differently — so `status`/`primary` are unconditionally
`("ok", 1.0)` on every successful (non-raising) replay, and no fixture, sealed or otherwise,
could ever witness a varying verdict for this leaf. Same disclosure location and treatment as
`aucarena_budget_invariant` above.

Both leaves resolve as (b), so no fixture was added and this finding's commit is a docs-only
commit (`docs(aucarena): state the witness limit for structurally-constant rule leaves`), per
this task's own standing instruction for that case.

### Finding 2 (should-fix, low) — verbatim

> commit `24f07c4c` WEAKENED an existing assertion. `tests/test_aucarena_measurement.py` around
> lines 213-225: a golden that previously asserted exact metric equality now checks only the
> metrics' KEY SET, and the hammer golden does not inspect its new metric at all. The reviewer's
> failure scenario: return arbitrary differing negative counts with unit `"usd"` and both the
> golden and the R9 inequality still pass.

**Disposition: CONFIRMED, fixed.** Verified against the actual diff
(`git show 24f07c4c -- tests/test_aucarena_measurement.py`): the pre-`24f07c4c` assertion was
`assert budget_score.metrics == {}` (exact); the commit replaced it with
`assert set(budget_score.metrics) == {"checked_transitions_count"}` (key-set only, no value, no
unit) and added no assertion at all against `hammer_score`'s new `replayed_rounds_count`.

Fixed in `tests/test_aucarena_measurement.py::test_golden_1_all_rule_constraint_leaves_pass`:
restored exact-equality assertions for both leaves' `metrics` dicts —
`assert budget_score.metrics == {"checked_transitions_count": MetricValue(32.0, "count")}` and
`assert hammer_score.metrics == {"replayed_rounds_count": MetricValue(32.0, "count")}` — pinning
both the numeric value and the unit, not just the key. The expected value (`32.0` for both, on
golden 1, `cases/aucarena/pilot/aucarena.pilot.successful_01.json`) is derived from the fixture's
own known shape, not read off a run and copied blind: golden 1 auctions four items under
`_min_markup_policy` (agent bids the legal minimum every round it can afford; `field_low` never
bids, `max_bid_cnt=0`; `field_high` raises by the same 10% minimum markup). Driving the real
scheduler and reading the recorded `phase_instances`/`consequences` in order gives item 1 sold in
9 rounds (bid_round 0-8, agent wins at $1700), item 2 in 8 rounds (0-7, `field_high` wins at
$1600), item 3 in 8 rounds (0-7, `field_high` wins at $1600), item 4 in 7 rounds (0-6,
`field_high` wins at $1500) — one recorded `TransitionResult`/round per phase instance, so
`checked_transitions_count == replayed_rounds_count == 9 + 8 + 8 + 7 == 32`. The arithmetic is
spelled out in a comment at each assertion site, not only here.

**Mutation check.** Backed up `src/aeread_families/aucarena/measurement.py` to `/tmp` (never
`git checkout` on a file with committed-but-not-yet-pushed history), then, one change at a time,
restoring from the `/tmp` copy between each:
- changed `checked_transitions_count`'s unit from `"count"` to `"usd"` (value held at `32.0`) —
  `test_golden_1_all_rule_constraint_leaves_pass` failed on the budget assertion, exactly as the
  reviewer's failure scenario predicts;
- changed `checked_transitions_count`'s value to `33.0` (unit held at `"count"`) — failed on the
  same assertion;
- changed `replayed_rounds_count`'s unit from `"count"` to `"usd"` (value held at `32.0`) —
  failed on the hammer assertion;
- changed `replayed_rounds_count`'s value to `27.0` (unit held at `"count"`) — failed on the same
  assertion.

All four mutations independently reproduced a failure; restored the file from the `/tmp` backup
and reverified `git diff --stat` reports no change and the full
`tests/test_aucarena_measurement.py` suite (20 tests) passes before committing.
