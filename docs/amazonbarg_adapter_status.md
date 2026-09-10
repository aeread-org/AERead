# amazonbarg bilateral-bargaining adapter — status

Branch `zeyu/amazonbarg-contract-migration`. Last verified 2026-09-06, after
rebasing onto `zeyu/kernel-r9r10` + `zeyu/kernel-r12-seat-context` and
adopting ruling R12 (kernel_scoring_contract_spec.md, "seat context reaches
the scorer") — see "Leaf policy" below for the resolution this milestone's
own "Disclosed consequence"/"single most consequential finding" language
described, now superseded. That sits on the kernel-scoring-contract
migration's milestone 3 of 3 (protocol-test enrollment + first real
receipt; see "Enrollment in the scoring-contract protocol test" below),
which itself sits on milestone 2 of 3 (leaf policy + `__call__`; see the
"Leaf policy" section below), on top of the milestone-3 adapter build
(scripted harness, end-to-end, replay) and a post-review fix pass
(`docs/amazonbarg_review_disposition.md`).

## What the adapter claims

For the 45-session `home-kitchen` + `toys-games` pilot pair (44
mutual-interest sessions + `toys-games_22`, the pilot's one
conflicting-interest session), the adapter runs upstream's exact bilateral
buyer/seller bargaining protocol (`session.parseReply` +
`utils.Action.ActionParser`, delegated in-process, never reimplemented)
through the real kernel scheduler, and scores every episode by delegating to
upstream's own `eval.py:Metrics` — never a hand-written legality or
profit/ratio recomputation. Five leaves are published, `composition_kind
="leaf"` throughout, never blended into one number:

| Leaf | Verifier family | Owner | Claim |
|---|---|---|---|
| `amazonbarg_deal_authenticity` | `rule_constraint` | delegated (`wrongAction`) | matches a genuine prior offer and the buyer's declared need |
| `amazonbarg_zopa_membership` | `rule_constraint` | AERead-owned, over delegated `B`/`C`/`D` | deal price inside `[cost, budget]` |
| `amazonbarg_deal_lower_bound` | `objective_reference` | AERead-owned | deal price vs. `S_min = cost` |
| `amazonbarg_deal_upper_bound` | `objective_reference` | AERead-owned | deal price vs. `S_max = budget` |
| `amazonbarg_bargained_ratio` | `comparative` | AERead-owned scorer, delegated arithmetic | tested seat's ratio vs. the fixed scripted counterpart |

`amazonbarg_deal_authenticity` and `amazonbarg_zopa_membership` are
deliberately kept separate (spec section 2): golden 3 (Breville) is a real
case where upstream calls a below-cost deal legitimate and AERead's own
added check is the only thing that catches it — this golden proves
scoring-layer detection, not state-layer prevention; see golden 4 for the
latter (spec section 4, golden 3 entry). Milestone 3 adds the scripted
counterpart harness (`harness.py`), an end-to-end run of at least two full
episodes through the real shared-runner path with sealed evidence, and an
offline replayer (`replay.py`) that reproduces both state and score with
zero further model/network calls; a post-review fix pass then extended the
harness/replay path from 2 to all 5 QC Gate-2 goldens
(`docs/amazonbarg_review_disposition.md` finding W1).

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf
policy explicitly (spec section 3), and `AmazonbargScorer.__call__` takes a
`FamilyScoringInput` and returns a `FamilyScoreSet` carrying every one of
the five leaves below — the gap where `AmazonbargScorer` had no `__call__`
at all (ledger D-15, see "Kernel/runner defects" below) is closed.

| Leaf | Scope | Primary | Admission |
|---|---|---|---|
| `amazonbarg_deal_authenticity_leaf` | `finalize_time` | no | no |
| `amazonbarg_zopa_membership_leaf` | `finalize_time` | no | no |
| `amazonbarg_deal_lower_bound_leaf` | `finalize_time` | no | no |
| `amazonbarg_deal_upper_bound_leaf` | `finalize_time` | no | no |
| `amazonbarg_bargained_ratio_leaf` | `finalize_time` | **yes** | **yes** |

**Why `amazonbarg_bargained_ratio` is primary.** It is this family's own
already-declared `primary_estimand` (`family_manifest()`'s `measurement`
block, present since before this milestone) and its closest-to-headline
comparative claim: the tested seat's own bargained ratio against the fixed
scripted counterpart. It was not picked because it was easiest to compute —
`amazonbarg_deal_authenticity` (a single delegated boolean) is in fact the
simplest of the five and is not proposed as primary. See
`docs/amazonbarg_migration_plan.md`'s "Proposed primary" section for the
full reasoning recorded before any `__call__` code was written.

**Why it alone gates admission.** `amazonbarg_zopa_membership`,
`amazonbarg_deal_lower_bound`, and `amazonbarg_deal_upper_bound` all share
the exact same validity gate (`_measurement_gate`, called identically by
each of their scorers): they turn `invalid_measurement` together, for the
same reasons, whenever there is no recorded evidence, upstream flags
`wrongAction=1`, the case has no ZOPA, or no deal closed — exactly the same
cases `amazonbarg_bargained_ratio` is already invalid in, so naming any of
them as an additional admission leaf adds no discriminating power.
`amazonbarg_deal_authenticity` is even weaker: it is `invalid_measurement`
only in the zero-recorded-turns case, already the *first* check inside
`_measurement_gate`, so it is already implied whenever
`amazonbarg_bargained_ratio` is invalid too. See
`docs/amazonbarg_migration_plan.md`'s "Admission" section.

**Deferred leaves: none.** Every leaf's estimand is *replayed-episode*
(needs this episode's own recorded transcript, delegated to upstream's
`eval.py:Metrics`, never a separately-run baseline episode or a judge/rater
verdict — see the migration plan's "Reference-source classification"
table), hence all five are declared `scope="finalize_time"` per spec
section 4's rule ("closed-form and replayed-episode → finalize_time;
separate-run and judge → deferred"). There is no artifact for a
`deferred_artifact` field to name.

**`input_scope`: three leaves relabelled `trajectory`, two forced to stay
`terminal_state`.** The migration plan's Path A ("relabel all five to
`trajectory`") turned out not to be uniformly available: `measurement.py`'s
own `_REFERENCE_SCOPE` table restricts `reference_kind="outcome_support_min"`/
`"outcome_support_max"` (the two bound leaves) to
`{"terminal_state", "distribution"}` — `ReferenceSpec.__post_init__` rejects
`"trajectory"` for them outright. `amazonbarg_deal_authenticity`,
`amazonbarg_zopa_membership`, and `amazonbarg_bargained_ratio` have no such
restriction (`constraint_satisfaction`/`head_to_head` have no
`_REFERENCE_SCOPE` entry) and are genuinely trajectory-dependent — their
delegated `eval.py:Metrics` call needs the full recorded transcript, not a
terminal snapshot — so those three are relabelled `input_scope="trajectory"`.

The two bound leaves stay declared `"terminal_state"`, forced by the kernel
schema, even though their own delegated computation (the realized deal
price `D`) also needs the full transcript — `AmazonbargPlugin.outcome()`
never carries it. `AmazonbargScorer.__call__` reads the same
phase-instances-derived transcript for all five leaves regardless of each
one's declared label. This is not a novel workaround invented for this
family: `tau3_retail`'s already-migrated `db_state` leaf
(`reference_kind="terminal_state_equivalence"`, scoped to exactly
`{"terminal_state"}`, even more restrictive) has the identical shape — its
`__call__` reads `scoring_input.phase_instances` for `messages` because
`outcome()` doesn't carry them either. A reviewer comparing this against a
strict reading of ruling R7 ("for every leaf declared `terminal_state`, its
score must be identical across two fixtures with byte-identical outcomes
but differing trajectories") should note that both bound leaves' scores
*would* vary in exactly that test, by construction — a known, disclosed gap
in the kernel's `_REFERENCE_SCOPE` table for a family whose
`objective_reference`/`outcome_support_*` estimand is genuinely
trajectory-dependent, not something this adapter can resolve without either
a kernel schema change or exposing the deal price via `outcome()` (neither
of which is this milestone's job). Not filed as a new numbered ledger entry
in this pass; recorded here for a reviewer to weigh against the same
question for `tau3_retail`.

**Resolved by ruling R12 (kernel_scoring_contract_spec.md, 2026-09-06):
`amazonbarg_bargained_ratio` is no longer always `invalid_measurement`
through this seam.** This section previously disclosed a real gap: which
seat (`buyer` or `seller`) a `RunPlan` is testing is a policy-binding fact
(`PlanCell.profile_by_seat`), and before ruling R12 nothing in
`FamilyScoringInput` (outcome/phase_instances/evidence_refs only, spec
section 1) or `family_case` let `__call__` recover it, so it always sealed
`REASON_TESTED_SEAT_UNKNOWN` and every receipt scored through this exact
seam was non-admitted. Ruling R12 adds `FamilyScoringInput.seat_context`
(`subject_seats`/`profile_by_seat`, populated by the finalizer from the
plan's evaluation block and the resolved cell — never the live episode,
so ruling R2 still holds) and lets a leaf declare
`seat_scope="subject_seat"` in its `LeafPolicyDeclaration`.
`amazonbarg_bargained_ratio_leaf` now declares exactly that (no
`subject_reduction` — this section's own claim above, "the tested seat's
own ratio ... against the fixed scripted counterpart", is one side's,
never blended), and `AmazonbargScorer.__call__` resolves `tested_seat`
from `scoring_input.seat_context.subject_seats` via the new
`score_bargained_ratio_for_subject_seats`, which defers to
`score_bargained_ratio` alone for the arithmetic (never reimplemented):

- Exactly one subject seat that is `"buyer"`/`"seller"` → scored normally,
  `status="ok"`, with `primary == utility_by_seat[tested_seat]` (the
  kernel itself enforces this identity at finalize for every
  `subject_seat` leaf, `task/evaluation.py`'s
  `_enforce_subject_seat_primaries`; asserted directly too, in
  `test_score_bargained_ratio_for_subject_seats_delegates_arithmetic_for_one_valid_seat`
  and `test_finalize_wires_amazonbarg_to_the_shared_family_finalizer`).
- Zero subject seats → `invalid_measurement` with the named
  `REASON_NO_SUBJECT_SEAT` (`test_score_bargained_ratio_for_subject_seats_reports_no_subject_seat_when_empty`).
- Two or more subject seats (this leaf declares no `subject_reduction`) →
  `invalid_measurement` with `REASON_AMBIGUOUS_SUBJECT_SEAT`, and the
  kernel does not raise for it (`_enforce_subject_seat_primaries` only
  applies to a `status="ok"` `subject_seat` leaf) —
  `test_score_bargained_ratio_for_subject_seats_reports_ambiguous_when_two_seats`
  and `test_finalize_reports_ambiguous_subject_seat_honestly_and_does_not_raise`.
- A subject seat that is not one of this family's own seat ids →
  `invalid_measurement` with `REASON_UNKNOWN_SUBJECT_SEAT`
  (`test_score_bargained_ratio_for_subject_seats_reports_unknown_seat_id`).

The pre-R12 `REASON_TESTED_SEAT_UNKNOWN` and `score_bargained_ratio`'s
widened `tested_seat: str | None` are retired along with the gap they
existed to disclose: `tested_seat` is a required `str` again, since no
caller needs `None` any more (`__call__` resolves a concrete seat, or
reports one of the three reasons above, before ever calling it; every
named caller that already knew which seat it tested -- every direct test
in this suite, `replay.py`'s `score_replayed_episode` -- is unaffected, as
before). See `test_finalize_wires_amazonbarg_to_the_shared_family_finalizer`
below for the first genuinely `status="ok"`/`inclusion_status="included"`
receipt this family has ever produced through the production finalizer
seam.

## Enrollment in the scoring-contract protocol test (migration milestone 3 of 3)

This family is enrolled in `tests/test_shared_runner_scoring_contract.py`'s
registry-driven protocol test (spec section 6): removed from
`_NOT_YET_MIGRATED_TRUSTED_KEYS` and added to
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` instead, mirroring the govsim
reference migration exactly, because this family's fixtures need the real,
pinned upstream AmazonPriceHistory checkout rather than being provider-free
in-process. `test_amazonbarg_obeys_the_scoring_contract` runs the identical
per-family check (`_assert_family_obeys_the_scoring_contract` — the
kernel's own canonical protocol-check function; this family's test called
it through a family-local copy, `_assert_family_scoring_contract`, until
the ruling-R12 rebase deleted that copy in favour of calling the kernel's
canonical one directly, so this family's fixtures are checked against
every rule the kernel's own protocol test enforces, including rulings
added after this milestone originally wrote its own copy) that every other
enrolled family runs, skipping (never failing) when the checkout is
missing; `conftest.py`'s new `AEREAD_AMAZONBARG_BRIDGE_REQUIRED` entry lets
a certifying run turn that skip into a failure instead — closing not only
this new test's own gap but a pre-existing one (before this milestone,
every `test_amazonbarg_*.py` skip on a missing checkout was already
unguarded by any `_BRIDGE_FAMILIES` entry).

**Paired-history fixture: constructible, and now built.** The migration
plan's "Paired-history pair: constructible — yes" finding is realized as
`GOLDEN_1_SCRIPT` (the existing golden 1 home-kitchen_2 $135 deal) paired
against a new `GOLDEN_1_PAIRED_HISTORY_SCRIPT` for the *same* case that
closes at the *same* $135 price through genuinely different intermediate
offers and dialogue. The byte-identity claim is asserted in the test itself
(`_assert_family_obeys_the_scoring_contract`'s own projection comparison —
`canonical_json_bytes(left_projection) == canonical_json_bytes(right_projection)`,
byte-for-byte the pre-ruling-R9 whole-outcome comparison this family's own
retired local copy ran, since this family declares no
`trajectory_outcome_paths` — and
`left_input.phase_instances != right_input.phase_instances`), not merely
claimed in a comment, and was independently verified against the real
pinned upstream checkout before being wired in. Post-rebase, a third
fixture (`GOLDEN_1_WRONG_ACTION_WITNESS_SCRIPT`, a genuinely different,
no-deal outcome for the same case) was added alongside this pair to
witness ruling R9(b)'s sensitivity requirement for this family's
trajectory-scoped leaves — see the dedicated `fix(amazonbarg):` commit;
the pair described here is unaffected and remains exactly
`produced_by_case[:2]`. Because the pair shares one
realized deal price `D`, the two leaves forced to stay declared
`input_scope="terminal_state"` (`amazonbarg_deal_lower_bound`,
`amazonbarg_deal_upper_bound` — see "Leaf policy" above) score identically
across it, satisfying ruling R7's contrapositive; mutation-verified by
temporarily changing the paired fixture's deal price to $140, which fails
the contrapositive assertion with a precise diff naming the mislabelled
leaf, then reverted.

**First real receipt: `test_finalize_wires_amazonbarg_to_the_shared_family_finalizer`
(`tests/test_amazonbarg_replay.py`).** This family had never produced an
`EvaluationReceipt` before this milestone — `ScriptedAmazonbargHarness`
writes only its own convenience event, never the generic evidence
vocabulary `task.evaluation.replay_family_scoring_input` needs to replay.
`EvidenceRecordingAmazonbargHarness` (new, mirrors govsim's identically
-purposed class field-for-field) and `build_amazonbarg_setup` (a real,
`resolve_run_plan`-resolved, provider-free `RunPlan`) close that gap. Two
defects surfaced only once this family was actually driven through
`finalize_family_execution` for the first time — exactly the govsim
reference migration's own experience, "neither defect was reachable before
this family was ever driven through finalize_family_execution":

- `AmazonbargPlugin.initial_state`'s second parameter was named `cell`;
  `task.evaluation._replay_family_trajectory` calls it by keyword
  (`run=None`), matching every other family's own hook. Renamed to `run`
  (the live scheduler still passes it positionally, so this is a pure
  signature rename, not a behavior change); the three call sites in
  `tests/test_amazonbarg_environment.py` that called it by keyword were
  updated to match.
- `measurement.py` declares each of its five leaves' scorer implementation
  (and the shared upstream-metrics-bridge reference and shared base-domain
  predicate) under its own distinct component id, never reusing the
  family-level `scorer_id` — `family_manifest()`'s `"scoring"` block now
  declares all seven as `reference_provider_ids`, or
  `resolve_run_plan`/`EvaluationReceipt._validate_and_freeze_plan_pins`
  reject the plan/receipt as missing implementations. This is an additive,
  amazonbarg-scoped manifest field with no existing frozen digest to
  perturb (ruling R1 is not implicated: this family has no published
  campaign evidence yet).

**Post-R12: the receipt now confirms the gap above is resolved, not merely
disclosed.** Driving golden 1 — a clean, successful $135 deal, nothing
malformed — through the real finalizer with `build_amazonbarg_setup`'s
default single subject seat (`subject_seats=("buyer",)`) produces a
receipt carrying every one of the five declared leaves `status="ok"`,
including the primary and sole admission leaf
(`amazonbarg_bargained_ratio_leaf`, `primary == utility_by_seat["buyer"]`),
with the receipt's own top-level `status="ok"` and
`inclusion_status="included"` — this family's first genuinely admitted
receipt through the production finalizer seam
(`test_finalize_wires_amazonbarg_to_the_shared_family_finalizer`). Driving
the identical golden with two subject seats instead
(`subject_seats=("buyer", "seller")`) reports the primary leaf honestly
`invalid_measurement`/`REASON_AMBIGUOUS_SUBJECT_SEAT`, receipt
`status="invalid_measurement"`/`inclusion_status="excluded"`, and does not
raise (`test_finalize_reports_ambiguous_subject_seat_honestly_and_does_not_raise`)
— ruling R12 rule 2's ambiguous-seat path, not a regression.

**Suite, with the bridge exported:** the full family test-file set —
now `test_amazonbarg_cases.py`, `test_amazonbarg_environment.py`,
`test_amazonbarg_harness.py`, `test_amazonbarg_measurement.py`,
`test_amazonbarg_replay.py`, `test_amazonbarg_shim.py`,
`test_amazonbarg_upstream_skip_scope.py`, and
`test_amazonbarg_bilateral_ci_bridge_requirement.py` (new, added by the
independent-review fix pass above) — plus `test_shared_runner_scoring_contract.py`
and `test_shared_runner_smoke.py` — **144 passed, 0 failed, 0 skipped**
(re-verified 2026-09-06, gate follow-up pass; up from 142 by the 2 tests the
gate follow-up added — `test_the_checkout_less_child_never_inherits_a_bridge_
required_flag` in `test_amazonbarg_upstream_skip_scope.py`, and
`test_every_amazonbarg_test_file_is_covered_by_some_ci_job` in
`test_amazonbarg_bilateral_ci_bridge_requirement.py`; the prior 142 count was
itself up from 138 by the 4 tests the independent-review fix pass added: the
ordering regression above and the three original
`test_amazonbarg_bilateral_ci_bridge_requirement.py` tests). Without the
bridge (upstream root pointed at a nonexistent path): **57 passed, 87
skipped** (up from 53/89 by the gate follow-up's fix (b): the three original
`test_amazonbarg_bilateral_ci_bridge_requirement.py` tests, plus its new
guard test, are now marked `no_upstream_checkout_required` — they read only
the checked-in workflow YAML, need no real upstream bytes, and previously
skipped anyway because `conftest.py`'s `pytest_collection_modifyitems` gates
on any `test_amazonbarg_` filename prefix, not on whether a given test
actually touches the checkout, so all four now run and pass instead of
skipping; the one offsetting new skip is
`test_the_checkout_less_child_never_inherits_a_bridge_required_flag`, left
unmarked like its sibling tests in that file since it drives a real
checkout-less child subprocess), every skip carrying the same named reason
as before, including both of the prior milestone's new tests
(`test_finalize_wires_amazonbarg_to_the_shared_family_finalizer`,
`test_amazonbarg_obeys_the_scoring_contract`) — verified individually, not
merely counted.

**Post-R12 count update (2026-09-06):** re-verified after rebasing this
branch onto `zeyu/kernel-r9r10` + `zeyu/kernel-r12-seat-context` and
adopting ruling R12 (see "Leaf policy" above). Same file list, bridge
exported: **181 passed, 0 failed, 0 skipped** (up from 144). Without the
bridge: **93 passed, 88 skipped** (up from 57/87). The great majority of
this increase is `test_shared_runner_scoring_contract.py` itself growing
by dozens of tests across rulings R7/R9/R10/R12 on the kernel side (a
shared, not per-family, file this family's own fixtures already ran
against before this rebase, on a much smaller version of it) — not new
tests this migration authored. This migration's own net contribution to
the counts above: `test_score_bargained_ratio_reports_tested_seat_unknown
_when_missing_never_fabricating_a_side` retired in favour of
`test_score_bargained_ratio_rejects_a_missing_tested_seat` (net 0, a
deliberate replacement, not a weakening — see "Leaf policy" above), plus
four new `score_bargained_ratio_for_subject_seats` unit tests and
`test_finalize_reports_ambiguous_subject_seat_honestly_and_does_not_raise`
(net +5) in this family's own test files, and one additional fixture
(`GOLDEN_1_WRONG_ACTION_WITNESS_SCRIPT`, witnessing ruling R9(b)'s
sensitivity requirement for this family's three trajectory-scoped leaves —
a gap the rebase surfaced, not one ruling R12 itself created; see the
dedicated `fix(amazonbarg):` commit for the full account) driven through
the already-existing `test_amazonbarg_obeys_the_scoring_contract`, adding
no new test function there.

**Gate follow-up (2026-09-06):** a final gate found two CI-wiring defects in
the finding-4 fix below. See "Gate follow-up" under finding 4 in
`docs/amazonbarg_migration_review.md` for the full reproduction and fix
detail; summarized here for the count reconciliation above.

**Independent review supplied and disposed
(`docs/amazonbarg_migration_review.md`, 2026-09-05).** Four findings, verified
against the code and disposed by the migration agent in the same session
(commits `44b31dda`, `d44e9a50`, `44ff2156`):

- Two were **CONFIRMED, ESCALATED (owner decision)** at review time — the
  two bound leaves' forced `terminal_state` declaration over a
  trajectory-derived deal price (still open, unaffected by ruling R12), and
  every `__call__`-produced receipt being non-admitted via
  `REASON_TESTED_SEAT_UNKNOWN` — matching, not adding to, what "Leaf policy"
  above and "Kernel/runner defects" below already disclosed before the
  review ran; no code change was made or was available to a migration
  agent for either at the time (spec section 5 forbade changing an
  estimand's declared `input_scope`/`reference_kind`, or moving the
  primary/admission leaf away from `amazonbarg_bargained_ratio_leaf`).
  **Post-R12 (2026-09-06): the `REASON_TESTED_SEAT_UNKNOWN` finding is
  resolved**, not by either of the two options the escalation named
  (neither was exercised), but by the kernel itself gaining a third option
  this review could not have anticipated — ruling R12's `seat_context` —
  see "Leaf policy" above and `docs/amazonbarg_migration_review.md`'s
  dated "Post-R12 note" for the full account. The bound-leaves escalation
  remains open.
- One is **REFUTED**: the claim that `score_all()` inserting the primary
  leaf last means a positional consumer sees it out of order.
  `FamilyScoreSet.__post_init__` (`src/aeread/shared_runner/measurement.py`)
  unconditionally re-sorts `scores`/`admission_leaf_ids`
  primary-first-then-lexical on construction regardless of the order a
  family scorer supplies — verified against a real replayed golden-1
  episode, then pinned by a new regression test,
  `test_amazonbarg_scorer_call_orders_primary_first_then_lexical_leaf_id`
  (`tests/test_amazonbarg_measurement.py`, commit `44b31dda`).
- One is **CONFIRMED, FIXED**: the scoring-contract protocol test's
  trusted-catalog closure counts amazonbarg as covered via
  `_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` regardless of whether
  `test_amazonbarg_obeys_the_scoring_contract` actually ran, and — the
  sharper mechanism the disposition adds — **nothing in this project's CI
  ever set `AEREAD_AMAZONBARG_BRIDGE_REQUIRED`**, so a real CI run always
  skipped that test (and every other amazonbarg fidelity test) and always
  reported green. Fixed by commit `d44e9a50`, completed by the gate
  follow-up commits `25d46831` (child pytest strips
  AEREAD_*_BRIDGE_REQUIRED) and `0a5dafb9` (no_upstream_checkout_required
  markers + coverage guard), docs in `15ab68f3`: a new `amazonbarg-fidelity`
  job in `.github/workflows/ci.yml` (mirroring `agenticpay-fidelity`)
  checks out the pinned upstream `TianXiaSJTU/AmazonPriceHistory` repository
  and runs every amazonbarg fidelity test file plus
  `test_shared_runner_scoring_contract.py` with
  `AEREAD_AMAZONBARG_BRIDGE_REQUIRED: "1"` set;
  `tests/test_amazonbarg_bilateral_ci_bridge_requirement.py` (new, mirrors
  `test_agenticpay_bilateral_ci_bridge_requirement.py`) regression-pins that
  the job stays wired that way, rather than merely asserting it once.

## Evidence

**All five QC Gate-2 goldens run end to end through the real scheduler,
sealed as durable evidence, then replayed by a second, independent plugin
instance with zero provider calls, reproducing state byte-identically for
all five goldens and score byte-identically for goldens 1, 4, and 5.**

- All five goldens — golden 1 (`home-kitchen_2`, Shark vacuum, closes
  `[DEAL] $135`), golden 2 (`home-kitchen_3`, Calphalon, an authenticated
  but comparatively poor deal), golden 3 (`home-kitchen_5`, Breville, an
  authenticated below-cost deal), golden 4 (`home-kitchen_4`, Bean Bag, the
  malformed-action case), and golden 5 (`toys-games_22`, the pilot's one CI
  session, correctly quits with no ZOPA) — are each driven through
  `ScriptedAmazonbargHarness` and the genuine
  `run_episode`/`AmazonbargPlugin`/`PluginRegistry` path — not a hand-wired
  shortcut. Every served decision is appended as a hash-chained
  `EvidenceStore` event and the store is sealed from the scheduler's own
  `episode_completed` lifecycle callback once the episode terminates.
  `tests/test_amazonbarg_harness.py` verifies the chain
  (`EvidenceStore.verify_chain()`/`verify_seal()`) and that every event
  payload round-trips exactly — including golden 4's single served decision
  and the proof that no seller-phase turn ever ran and no phantom deal was
  ever recorded.
- Each recorded episode is extracted (`record_episode`), round-tripped
  through plain JSON text (`RecordedEpisode.to_json()`/`from_json()`), and
  replayed (`replay_episode`) by a **second**, independently constructed
  `AmazonbargPlugin` — never the one that produced the original run.
  `tests/test_amazonbarg_replay.py` asserts:
  - `compare_episode_results(...).matches is True` for all five goldens,
    and, unlike `tau3_retail` (whose replay only ever matches *content*,
    because `step()` re-stamps a fresh wall-clock timestamp on every
    message — documented on that adapter's own
    `replay._strip_message_timestamps`), **the raw, byte-exact final state
    matches too** (`final_state_matches is True`,
    `canonical_json_bytes(replayed.final_state) ==
    canonical_json_bytes(original.final_state)`) — `AmazonbargPlugin.step()`
    stamps nothing, so this is a strictly stronger guarantee, verified
    directly rather than assumed.
  - Every measurement leaf (deal-authenticity/zopa/bounds and the
    comparative ratio, both seats) recomputed from the replayed episode's
    own recorded history via `score_replayed_episode` is `==`
    (dataclass-equal, i.e. byte-identical) to the same leaf computed from
    the original run's history, for golden 1, golden 4, and golden 5 —
    including golden 4's and golden 5's degenerate `invalid_measurement`
    envelopes, which reproduce with the same typed reason codes, not merely
    the same top-level status.
  - `replay_and_verify` end-to-end returns `status="match"` and the exact
    expected `amazonbarg_bargained_ratio` primary (`~=0.49` for the buyer
    seat on golden 1).
  - A tampered recorded decision (the DEAL's price text changed, its action
    *type* left alone so the episode still terminates after the same
    number of decisions) diverges — `matches is False`,
    `final_state_matches is False`, the two runs' final actions differ —
    **without raising**. This is an honest, documented difference from
    `tau3_retail` (whose `Tau3RetailPlugin.step()` independently
    re-executes and cross-checks every tool call against a live bridge and
    raises `SchedulerContractError` on a tamper): amazonbarg has no tool
    calls to cross-check, so a tampered reply is simply re-parsed into a
    genuinely different trajectory, never caught internally by `step()`
    itself. The replay guarantee here rests entirely on
    `compare_episode_results`/`assert_replay_matches` being run and checked
    by the caller.

Milestone-2 snapshot, superseded by the 144 / 57+87 counts under
"Enrollment" above (those files are now 24, 19, and 5 tests):
**Suite: 131/131 passed**, bridge exported, for the full amazonbarg
family test-file set (`test_amazonbarg_cases.py` 34,
`test_amazonbarg_environment.py` 21, `test_amazonbarg_measurement.py` 23,
`test_amazonbarg_shim.py` 13, `test_amazonbarg_harness.py` 8,
`test_amazonbarg_replay.py` 18, `test_amazonbarg_upstream_skip_scope.py` 4)
plus `test_shared_runner_smoke.py` (10) — zero failed, zero skipped (the
pinned upstream checkout is present at
`/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg`, so every test
that needs it actually ran, never silently skipped). Re-run with
`AEREAD_AMAZONBARG_UPSTREAM_ROOT` pointed at a nonexistent path: 48 passed,
83 skipped, every skip carrying the identical, named reason ("pinned
upstream AmazonPriceHistory checkout not found at ... (set
AEREAD_AMAZONBARG_UPSTREAM_ROOT)") — no silent pass, and (per the worked
example's own trap 2) no skip hiding an old calling convention: the four
new tests this milestone adds
(`test_family_manifest_declares_all_five_leaves_with_bargained_ratio_primary`,
`test_score_bargained_ratio_reports_tested_seat_unknown_when_missing_never_fabricating_a_side`,
`test_amazonbarg_scorer_call_raises_when_upstream_root_is_missing`, all
`no_upstream_checkout_required` and verified to actually run without the
bridge; `test_amazonbarg_scorer_call_returns_every_declared_leaf_never_just_
the_primary`, correctly bridge-gated since it delegates to
`eval.py:Metrics`) were each individually confirmed to run in the correct
one of the two modes, not merely counted. Mutation-verified: temporarily
deleting `amazonbarg_deal_authenticity_leaf` from `__call__`'s returned
dict fails `test_amazonbarg_scorer_call_returns_every_declared_leaf_never_
just_the_primary` with a set-difference assertion naming exactly the
dropped leaf; reverted after confirming.

Earlier milestones' own count (114/114, before this migration) is carried
forward from that history rather than restated leaf-by-leaf here; the
8-test increase from milestone 3's original 106/106 to 114/114 was the
post-review fix pass: 3 new harness goldens (2, 3, 4), 4 new replay
goldens (2, 3, 4 state-reproduction plus a golden-4 score-recompute), and 1
new measurement regression test (`docs/amazonbarg_review_disposition.md`
findings W1/W2).

**No regression: full repo suite re-run 2026-09-06 under the plain CI
environment (no bridge/upstream variables): 2230 passed, 125 skipped, 1
xfailed, 0 failed (docs/amazonbarg_migration_review.md, "Gate follow-up");
the earlier milestone-3 count with bridges was 830/31/1.** The 31 skips
under that earlier count are pre-existing, unrelated external-bridge
dependencies for other adapter families (confirmed none is
amazonbarg-related by grepping the skip report for `amazonbarg` — zero
hits). This migration milestone's own verification scope was the family
test-file set plus `test_shared_runner_smoke.py` (above), not a fresh
full-repo run.

**Provider-free, network-free throughout.** Every test in this milestone
runs entirely in-process, through `upstream_shim`'s delegation mechanism —
no subprocess bridge, no API key, no network call. `test_amazonbarg_shim.py`
already pins the stub miss-counter at `0` across the whole suite; this
milestone adds nothing that could raise it (the harness/replay modules
never call `upstream_shim` directly — only `measurement.py`'s
`compute_upstream_metrics`, already covered).

## What's still declared-but-not-executed

Only the 45-session pilot pair actually runs end to end tonight; the other
885 of the full 930-session corpus are digested at the file level (Gate 1)
and get no `CaseManifest`, scripted trajectory, harness run, or replay.
Milestone 3 originally only drove 2 of the 45 pilot sessions (goldens 1 and
5) through the harness/replay path, per the milestone's own acceptance bar
("at least 2 full episodes"); a post-review fix pass
(`docs/amazonbarg_review_disposition.md` finding W1) extended this to **all
5 QC Gate-2 goldens** — the remaining 40 pilot sessions (outside the five
goldens) and their measurement coverage are still exercised only by
`test_amazonbarg_measurement.py`'s existing scored-transcript tests, not yet
by a harness-run + sealed-evidence + replay cycle each. Extending the
harness/replay pair to the full 45-session pilot (and, separately, deciding
whether to materialize and score any of the other 885 sessions) remains
future work, not part of this milestone's scope.

## Known limits, stated rather than implied

- **The scripted counterpart is one fixed policy, not a distribution of
  opponents.** `amazonbarg_bargained_ratio`'s claim (and this milestone's
  own harness scripts) is relative to that one AERead-authored fixture,
  never a general capability score (spec section 6).
- **No stochastic estimation.** Every leaf's `evaluation_class` stays
  `"deterministic"` — scripted trajectories only; a real model policy in
  either seat is out of scope here.
- **Replay's guarantee is external, not internal.** Unlike
  `Tau3RetailPlugin.step()` (which owns its own tool-replay cross-check and
  raises on divergence), `AmazonbargPlugin.step()` has no tool calls to
  cross-check, so `replay.py`'s comparison functions must actually be
  called and their result actually checked — a caller that replays and
  never calls `assert_replay_matches`/inspects `StateComparison.matches`
  would not be told about a divergence. See the tamper test above for the
  concrete, verified shape of that gap.
- **`amazonbarg_zopa_membership` and the bound leaves are AERead
  additions** upstream never computes or validates — still true as of this
  milestone, restated from the milestone-2 status (never report them as
  "the paper's own headline metric").
- **`budget_ratio=0.8` and `max_turns=6` remain the only pins explored.**
  No sensitivity analysis over either value is part of this or any prior
  milestone.
- **"Component parity" (the double-delegated-call check every QC Gate-2
  golden test runs) proves wiring, never the correctness of the delegated
  arithmetic itself, for the two leaves that are purely delegated
  (`amazonbarg_deal_authenticity`'s `wrongAction`, `amazonbarg_bargained
  _ratio`'s profit arithmetic).** Both calls in `_score_and_check_parity`
  run the identical pinned upstream code on the identical input and will
  agree on whatever that code computes, bug or not (codex-review finding
  7) — demonstrated concretely by finding 2's own room-widening bug, which
  reproduced byte-identically across both calls and passed every parity
  assertion. Rule 2 ("never reimplement upstream") forbids building an
  independent oracle to close this for the two purely-delegated leaves, so
  it is not fixable inside this adapter; the one manually-verified,
  non-parity oracle case that exists
  (`test_narrow_bargaining_room_does_not_let_a_deal_above_the_real_budget
  _pass_zopa`) covers only the AERead-owned `amazonbarg_zopa_membership`
  leaf (whose fix let it stop trusting delegated `B`/`C` at all), not the
  two purely-delegated leaves parity can never independently check — and,
  since it does not call `_score_and_check_parity`, it does not regression
  -guard finding 7's own fix commit (a documentation-only docstring
  addition; no runtime behavior is gated on it, so no test can fail if it
  is reverted). This is a permanent, disclosed limitation, not a closed
  finding — see `docs/amazonbarg_review_disposition.md`'s "Verification
  follow-up" section for the correction to that file's earlier "closed by
  finding 2's test" summary-table wording, which overstated the
  relationship.

## Kernel/runner defects or limitations found this milestone

**D-15 (previously HIGH, open, cross-family) is resolved for this family by
this migration milestone, not closed at the kernel-ledger level.** The
original finding: the shared runner's production call site for family
scoring required `plugin.build_scorer(family_case)` to return something
directly callable that yields exactly one `ScoreEnvelope`, while
`AmazonbargScorer` (this adapter's declared five-leaf model, spec section
2, "never blended into one number") had no `__call__` and could not
satisfy that shape without inventing an arbitrary "primary" leaf and
silently discarding the other four. `kernel_scoring_contract_spec.md`
(the kernel-side change referenced throughout this section) replaced that
single-`ScoreEnvelope` contract with `FamilyScoringInput` /
`FamilyScoreSet`, and this milestone gives `AmazonbargScorer` a `__call__`
that satisfies it, returning every declared leaf (see "Leaf policy"
above) — the "arbitrary primary, silently discarding the other four"
failure mode D-15 named no longer applies to this family. Whether
`runner_defect_ledger.md`'s own D-15 entry should be marked resolved
project-wide is not this adapter's call to make (the entry is
cross-family, `Tau3RetailScorer` and others were the other named
instances, and `tau3_retail` already migrated too per
kernel_scoring_contract_spec.md ruling R4) — flagged here for whoever owns
that ledger, not edited directly by this branch.

**One remaining disclosed limitation from milestone 3, recorded in full
under "Leaf policy" above rather than repeated here:** the two bound
leaves' `input_scope="terminal_state"` declaration is forced by
`measurement.py`'s `_REFERENCE_SCOPE` table even though their own
delegated computation is genuinely trajectory-dependent, an
already-precedented shape (`tau3_retail`'s `db_state` leaf) rather than a
novel gap, but one a reviewer should weigh against ruling R7 for both
families. This remains open, independently confirmed and escalated for an
owner decision in `docs/amazonbarg_migration_review.md` (finding 1,
2026-09-05 review; no code change was available to a migration agent).

**Resolved (see "Leaf policy" above and `docs/amazonbarg_migration_review.md`'s
dated "Post-R12 note"): `amazonbarg_bargained_ratio` — this family's
primary and sole admission leaf — was always sealed `invalid_measurement`
through the `__call__` production seam specifically, because no
`tested_seat` signal was reachable from a `FamilyScoringInput`, making
every receipt scored through that seam non-admitted.** This was milestone
3's single most consequential finding, independently confirmed and
escalated in `docs/amazonbarg_migration_review.md` (finding 2, 2026-09-05
review). Ruling R12 (kernel_scoring_contract_spec.md, adopted 2026-09-06)
resolves it at the kernel level — `FamilyScoringInput.seat_context` — not
by either of the two options the escalation named. This family's first
genuinely admitted receipt through the production finalizer seam is now
demonstrated, not merely disclosed as impossible; see "Leaf policy" above
for the full account and the ambiguous-seat path that remains honestly
`invalid_measurement`.

The three kernel-contract limitations already on file from milestones 1-2
(`ledger_entries/amazonbarg.md`: the two-value `ScoreEnvelope.status` enum
having no distinct "degenerate" state; the lack of a directionless
`ObjectiveScopeSpec.direction` option; and the `verifier_taxonomy.md` §5.1
vs. real `_REFERENCE_KINDS` drift) are unchanged — this milestone's
harness/replay work exercises all three code paths again (goldens 1 and 5)
without surfacing anything new about them. The `sys.modules` shim technique
(spec section 3.1, also logged there as a deliberate departure from the
task's two named fallback patterns) is unchanged by this milestone:
`harness.py`/`replay.py` never call `upstream_shim` directly, only
`measurement.py`'s already-shimmed `compute_upstream_metrics`.
