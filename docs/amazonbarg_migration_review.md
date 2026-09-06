# amazonbarg migration — independent review and disposition

Independent review supplied 2026-09-05 for branch `zeyu/amazonbarg-contract-migration`.
Verified against the code and disposed by the migration agent in the same session.

--- BEGIN REVIEW ---
- High — The two bound leaves are falsely declared `terminal_state`. [measurement.py:350](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:350) and [measurement.py:403](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:403) declare that scope, while [measurement.py:1130](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:1130) extracts history from `phase_instances` and passes the resulting trajectory-derived metrics to every leaf. The paired test at [test_shared_runner_scoring_contract.py:1329](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/tests/test_shared_runner_scoring_contract.py:1329) only demonstrates coincident outputs for two histories ending at the same price; it cannot make the forbidden read legal. Concrete failure: two byte-identical outcomes with different transcript-derived `wrongAction`/deal parsing could change or invalidate either bound despite its terminal-only declaration.

- High — Every successful production episode is deliberately excluded. [measurement.py:1115](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:1115) always calls scoring with `tested_seat=None`; [measurement.py:896](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:896) consequently invalidates the primary and sole admission leaf. The production-finalizer test enshrines the resulting excluded receipt at [test_amazonbarg_replay.py:1225](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/tests/test_amazonbarg_replay.py:1225). Concrete failure: the clean $135 golden deal can never yield an admissible benchmark measurement through the production finalizer, although direct callers supplying a seat can score it.

- Medium — Returned leaves violate required ordering. The manifest declares the primary as `amazonbarg_bargained_ratio_leaf` at [environment.py:152](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/environment.py:152), but `score_all()` inserts it last at [measurement.py:1074](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:1074), and [measurement.py:1141](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/src/aeread_families/amazonbarg/measurement.py:1141) preserves that order. Tests reduce scores to sets, e.g. [test_amazonbarg_measurement.py:469](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/tests/test_amazonbarg_measurement.py:469), so they miss it. Concrete failure: positional consumers receive a diagnostic first and the primary last, contrary to the primary-first, then-lexical contract.

- Medium — Trusted-catalog closure can pass without executing AmazonBarg's protocol test. The always-on closure counts the family through an unconditional set union at [test_shared_runner_scoring_contract.py:1365](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/tests/test_shared_runner_scoring_contract.py:1365), while the actual fixture calls `pytest.skip` when the external checkout is absent at [test_shared_runner_scoring_contract.py:1404](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/amazonbarg-migrate/tests/test_shared_runner_scoring_contract.py:1404). Concrete failure: on a normal environment without that checkout, catalog closure passes and the separate AmazonBarg test skips, leaving the trusted enrolled family with zero behavioral protocol coverage.

FINDINGS: 4
--- END REVIEW ---

## Disposition

### Finding 1 (High — two bound leaves falsely declared `terminal_state`): CONFIRMED, ESCALATED (owner decision)

Verified against the code: `build_deal_lower_bound_leaf`/`build_deal_upper_bound_leaf`
(`measurement.py`, `input_scope="terminal_state"`) declare a scope that their own
underlying data does not honor. `AmazonbargScorer.__call__` reads the full recorded
transcript off `scoring_input.phase_instances` (`_history_from_phase_instances`) and
delegates it to upstream's `eval.py:Metrics` for **every** leaf, including the two
bound leaves — their `primary` (the realized deal price `D`) is a transcript-derived
quantity, not a terminal-state fact. `AmazonbargPlugin.outcome()`
(`environment.py:622-631`) confirms this independently: it carries only
`termination_reason`, `terminating_actor`, `turns_completed`, `message_count` — never
the deal price — so the "terminal outcome" the paired-history test treats as
byte-identical cannot, by construction, pin the deal price at all. The review's
concrete failure is real: `wrongAction`, `closeADeal`, and `D` are all
transcript-derived and could legitimately vary across two fixtures sharing the same
four `outcome()` fields, which would flip `_measurement_gate`'s verdict for a bound
leaf despite an unchanged declared-terminal "outcome".

This is not a fix a migration agent may make. The label is **forced** by the kernel:
`ReferenceSpec.__post_init__`'s `_REFERENCE_SCOPE` table
(`src/aeread/shared_runner/measurement.py:67-68`) restricts
`reference_kind="outcome_support_min"`/`"outcome_support_max"` to
`{"terminal_state", "distribution"}` and rejects `"trajectory"` outright — verified by
reading that table directly. Making the label honest requires either (a) a kernel
change to `_REFERENCE_SCOPE`, or (b) changing which `reference_kind` these two leaves
use, or (c) exposing the deal price through `AmazonbargPlugin.outcome()` so a
genuinely terminal-state read becomes possible. All three change an estimand's
declared `input_scope`/`reference_kind` shape — explicitly out of a migration agent's
authority per `kernel_scoring_contract_spec.md` section 5 ("Agents decide none of: ...
an estimand definition"). This gap was already disclosed, independently of this
review, in `docs/amazonbarg_adapter_status.md`'s "Leaf policy" section ("not something
this adapter can resolve without either a kernel schema change or exposing the deal
price via `outcome()`, neither of which is this milestone's job"). No code change
made. Recorded here as confirmed and escalated for an owner decision among the three
options above.

### Finding 2 (High — every successful production episode excluded): CONFIRMED, ESCALATED (owner decision)

Verified against the code: `AmazonbargScorer.__call__` (`measurement.py`, inside the
`score_all(... tested_seat=None ...)` call) always passes `tested_seat=None` to
`score_bargained_ratio`, which (`measurement.py:896-902`) appends
`REASON_TESTED_SEAT_UNKNOWN` and seals the whole envelope
`invalid_measurement` whenever `tested_seat` is `None`. Because
`amazonbarg_bargained_ratio_leaf` is both the declared primary and the sole
admission leaf (`environment.py:152-153`), `_score_admission`
(`src/aeread/shared_runner/task/evaluation.py:106-127`) marks every such receipt
`status="invalid_measurement"`/`inclusion_status="excluded"`. Confirmed exactly as
described (the cited line numbers in the raw review drift by roughly twenty lines
from the current file — the `tested_seat=None` call site is at `measurement.py:1138`,
inside `__call__`, not 1115 — but the substance is unchanged and independently
verified).

This is not a fix a migration agent may make. `tested_seat` (which seat a `RunPlan` is
testing, `PlanCell.profile_by_seat`) is a policy-binding fact that is reachable from
neither `FamilyScoringInput` (`outcome`/`phase_instances`/`evidence_refs` only, spec
section 1 — frozen) nor `family_case`. There is no way to derive it from the sealed
trajectory: both seats produce ordinary bargaining turns whether one is a scripted
counterpart or the tested policy, so nothing in the replay distinguishes them. The
only two ways to resolve this are (a) a kernel-level channel to thread `tested_seat`
into or alongside `FamilyScoringInput`, or (b) moving the primary/admission leaf away
from `amazonbarg_bargained_ratio_leaf` to one of the four leaves that does not need a
seat — and (b) is explicitly forbidden to a migration agent (changes the primary and
admission membership, per spec section 5's "Agents decide none of: ... the primary,
admission membership"). This is already disclosed at length in
`docs/amazonbarg_adapter_status.md`'s "Disclosed consequence" section, including the
identical demonstration via the golden-1 production receipt
(`test_finalize_wires_amazonbarg_to_the_shared_family_finalizer`). No code change
made. Recorded here as confirmed and escalated for an owner decision between the two
options above.

### Finding 3 (Medium — ordering violates primary-first-then-lexical): REFUTED

Verified against the code and refuted. The review is correct that
`AmazonbargScorer.score_all()` builds its `dict` in declaration order with
`amazonbarg_bargained_ratio_leaf` (the primary) inserted **last**, and that
`__call__` passes `tuple(scored.values())` straight into `FamilyScoreSet(...)`
without reordering it. But the kernel's own `FamilyScoreSet.__post_init__`
(`src/aeread/shared_runner/measurement.py:447-463`) unconditionally re-sorts
`scores` (and `admission_leaf_ids`) by the key
`(leaf_id != primary_leaf_id, leaf_id)` on construction — i.e. primary first, then
lexical — **regardless of the order the family scorer supplied**. Since
`AmazonbargScorer.__call__` returns a `FamilyScoreSet` directly (not a bare sequence),
this canonicalization always runs.

Verified empirically, not just by reading: driving golden 1 (a real replayed episode)
through `AmazonbargScorer.__call__` and inspecting `score_set.scores` in order
produces exactly
`[amazonbarg_bargained_ratio_leaf, amazonbarg_deal_authenticity_leaf,
amazonbarg_deal_lower_bound_leaf, amazonbarg_deal_upper_bound_leaf,
amazonbarg_zopa_membership_leaf]` — primary first, then the remaining four leaf ids in
plain lexical order — even though `score_all()`'s own dict has the primary last. The
review's "concrete failure" (a positional consumer receiving the primary last) cannot
occur: the kernel makes this structurally impossible for any `FamilyScoreSet`, not
just this family's.

Added a regression test pinning this fact for amazonbarg specifically, since reading
only this family's own source (without also reading the kernel's
`FamilyScoreSet.__post_init__`) would lead a reviewer to the same wrong conclusion the
raw review reached:

- Test: `test_amazonbarg_scorer_call_orders_primary_first_then_lexical_leaf_id`
  (`tests/test_amazonbarg_measurement.py`). Asserts the exact literal order above.
- No mutation check performed for this one — there is nothing to mutate on the family
  side that would change the outcome: `FamilyScoreSet`'s canonicalization runs
  unconditionally on construction, so no family-level code path can produce a
  non-canonical order without also violating a different, already-tested invariant
  (e.g. duplicating or omitting a leaf, which is already caught elsewhere). This test
  passed immediately upon being written, for the reason stated above, not because of
  any code change made here.

### Finding 4 (Medium — trusted-catalog closure can pass without executing AmazonBarg's protocol test): CONFIRMED, FIXED

Verified against the code and confirmed, with a sharper concrete mechanism than the
one named in the review. `_assert_trusted_catalog_is_closed`'s closure check does
treat amazonbarg as enrolled unconditionally via
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS`
(`test_shared_runner_scoring_contract.py:1365-1368`), and
`test_amazonbarg_obeys_the_scoring_contract` does skip (not fail) when the pinned
upstream checkout is absent — both exactly as the review states, and both are the
same, deliberate, documented pattern every other bridge-gated family in this repo
uses (`conftest.py`'s `_BRIDGE_FAMILIES`/`pytest_terminal_summary`), not a defect
unique to this migration. The mitigation for that general pattern already exists and
already covers amazonbarg: setting `AEREAD_AMAZONBARG_BRIDGE_REQUIRED=1` turns the
skip into a hard failure (`conftest.py:106-113`, already added in this branch's
`fix(amazonbarg): fail certifying runs when the bridge-gated contract test skips`).

The actual gap is one level up: **nothing in this project's CI ever sets that
variable for amazonbarg.** Reading `.github/workflows/ci.yml` as checked in before
this fix: the `test` job runs a bare `pytest tests/ -q` with no bridge variables set
for any family, and the only dedicated bridge-required job is `agenticpay-fidelity` —
there was no `amazonbarg-fidelity` job at all. This means every real CI run on this
project, as configured, always skips `test_amazonbarg_obeys_the_scoring_contract` and
always reports the whole suite green, permanently — not merely "on a normal
environment" as a hypothetical, but as the actual, current, wired behavior. This
directly undermines ruling R6's stated purpose ("a family must be added to
`TRUSTED_BUILTIN_PLUGIN_KEYS` to be trusted at all, and that same act enrolls it in
the conformance test. You cannot obtain one without the other.") for this family
specifically: trust and conformance-checking are decoupled by default in CI as it
stood.

Fixed by adding an `amazonbarg-fidelity` job to `.github/workflows/ci.yml`, mirroring
the existing `agenticpay-fidelity` job: it checks out the pinned upstream
`TianXiaSJTU/AmazonPriceHistory` repository at the pinned commit, sets
`AEREAD_AMAZONBARG_UPSTREAM_ROOT` and `AEREAD_AMAZONBARG_BRIDGE_REQUIRED: "1"`, and
runs every amazonbarg family test file plus
`tests/test_shared_runner_scoring_contract.py` (where
`test_amazonbarg_obeys_the_scoring_contract` lives) under that gate. Unlike
agenticpay, no separate bridge-interpreter provisioning step is needed —
`upstream_shim.py`'s own module docstring establishes that amazonbarg's delegated
import runs in-process, under this project's own venv.

- Test: `tests/test_amazonbarg_bilateral_ci_bridge_requirement.py` (new; mirrors
  `tests/test_agenticpay_bilateral_ci_bridge_requirement.py`), three assertions:
  the workflow sets `AEREAD_AMAZONBARG_BRIDGE_REQUIRED: "1"`; the workflow sets
  `AEREAD_AMAZONBARG_UPSTREAM_ROOT` and checks out
  `TianXiaSJTU/AmazonPriceHistory`; the workflow actually invokes every amazonbarg
  fidelity test file (plus `test_shared_runner_scoring_contract.py`) under that job.
  Confirmed failing (all three assertions) before the CI job was added.
- Mutation result: with the new job's `AEREAD_AMAZONBARG_BRIDGE_REQUIRED: "1"` line
  removed (file copied to `/tmp`, mutated, tested, restored from the `/tmp` copy —
  never via `git checkout`), `test_ci_sets_the_amazonbarg_bridge_required_switch`
  failed as expected (the other two assertions, which check different lines,
  continued to pass); restoring the line made all three pass again.

## Summary

- Fixed: 1 (finding 4)
- Refuted: 1 (finding 3)
- Escalated (confirmed, owner decision required): 2 (findings 1 and 2)
