# Kernel ruling R12 — seat context reaches the scorer

**Provenance.** Branch `zeyu/kernel-r12-seat-context`, forked from
`zeyu/kernel-r9r10` (PR #103) at `78614540`. Implements ruling R12 of
`kernel_scoring_contract_spec.md` ("Seat context reaches the scorer;
per-seat primaries are declared, not guessed"), found by the negarena
migration on 2026-09-06.

## The problem

Some families' primary leaf is inherently per seat: "what did *this* seat
realize under its own valuation" (negarena's `seat_outcome`; tau3_retail
documents the same convention). One value exists for each seat, and a summed
or blended two-seat number is not the estimand. The kernel already knows
which seats are the tested subjects (`EvaluationBlock.subject_seats`) and
which profile sits in each seat (`cell.profile_by_seat`), and the receipt
already records per-seat `agent_profile_digests` — but none of it reached
the scorer, so such a family could only report `invalid_measurement` and
every one of its receipts was excluded. A migration agent must not invent a
seat convention; the kernel must carry the fact it already has.

Families whose case itself names the tested seat (aucarena's roster,
alympics' focal seat) are unaffected: their primary is cell-scoped and they
ignore seat context.

## What changed

### 1. `SeatContext` and `FamilyScoringInput.seat_context`

`src/aeread/shared_runner/task/evaluation.py` gains:

- `SeatContext` — a frozen dataclass with `subject_seats: tuple[str, ...]`
  and `profile_by_seat: Mapping[str, str]` (the mapping is frozen via
  `MappingProxyType` in `__post_init__`, the same minimal pattern
  `analysis/research.py` and `run/resolver.py` already use for
  `profile_by_seat`, since its values are already-validated plain strings —
  not the richer `_freeze_metric_mapping` validation `ScoreEnvelope` needs
  for `utility_by_seat`, whose values are typed `MetricValue`).
- `_seat_context_for_cell(plan, cell)` — builds the `SeatContext` for one
  resolved cell by matching `plan.evaluation_blocks` on `cell.block_id` and
  reading `cell.profile_by_seat` directly. Never touches the live episode
  (ruling R2 still holds: this is plan/receipt data).
- `FamilyScoringInput.seat_context: SeatContext = SeatContext((), {})` — the
  field defaults to an explicit empty `SeatContext` so a test that
  constructs `FamilyScoringInput` directly (without naming `SeatContext`)
  keeps working. Every production finalize/replay/audit path supplies the
  real one.
- `replay_family_scoring_input(*, plugin, family_case, evidence, seat_context)`
  — `seat_context` is a required keyword with **no default**. A caller
  cannot silently omit it the way a default would allow.

`finalize_family_execution`, `replay_family_receipt`, and
`audit_family_receipt` each compute `seat_context = _seat_context_for_cell(setup.plan, cell)`
and pass it to `replay_family_scoring_input` and (see §3 below)
`_enforce_declared_leaf_policy`.

### 2. `_check_seat_context_seat_set` — replay/audit reject a mismatched seat set

`replay_family_receipt` and `audit_family_receipt` each additionally call
`_check_seat_context_seat_set(seat_context, recorded_agent_profile_digests)`,
which raises a named `ValueError` ("seat context does not match the
receipt: seat_context names seats [...], receipt agent_profile_digests
names seats [...]") when `seat_context.profile_by_seat`'s keys disagree
with the receipt's recorded `agent_profile_sha256_by_seat` keys.

**Reachability note**, discovered while mutation-testing this check:
`PlanCell.profile_by_seat` is itself part of what makes `RunPlan.plan_sha256`,
so a receipt whose recorded seats genuinely disagree with the current
plan's cell is normally caught first, transitively, by the earlier
run_plan_id/plan_sha256 identity check every caller performs — and
`audit_family_receipt` additionally already re-derives and compares the
full `agent_profile_sha256_by_seat` digest mapping generically (any
disagreement, not only a key-set one, was already caught there). Disabling
this check and re-running its dedicated tests proved this asymmetrically:

- For `audit_family_receipt`, disabling it changes only the reported
  message (from this check's own to the pre-existing generic "receipt
  agent_profile_sha256_by_seat does not match the sealed plan") — the
  disagreement was already caught, just less specifically.
- For `replay_family_receipt`, disabling it means the disagreement is
  **not caught at all** — `replay_family_receipt` never compared
  `agent_profile_sha256_by_seat` against anything before this change. This
  check is the only guard there against a durable evidence directory whose
  on-disk receipt was corrupted directly (bypassing the write-once API) to
  a self-consistent but wrong `agent_profile_sha256_by_seat`.

Both tests construct exactly that scenario: finalize a real receipt, build
a freshly-resealed copy whose `agent_profile_sha256_by_seat` names an extra
seat absent from the plan, write those tampered bytes directly onto the
evidence directory's `evaluation_receipt.json` (bypassing
`write_evaluation_receipt`'s idempotent-overwrite guard, which refuses to
overwrite existing different content — exactly what a corrupted evidence
directory would look like), and confirm the named error fires.

### 3. `LeafPolicyDeclaration.seat_scope` / `subject_reduction`

`src/aeread/shared_runner/schemas.py`'s `LeafPolicyDeclaration` gains:

- `seat_scope: str = "cell"` — allowed values `{"cell", "subject_seat"}`.
- `subject_reduction: str | None = None` — only valid when
  `seat_scope == "subject_seat"`; a family-interpreted identifier (e.g.
  `"mean"`) the kernel never inspects for meaning.

Both fields are added to `LeafPolicyDeclaration._CANONICAL_OMIT_IF_DEFAULT`
(a `ClassVar` the class did not carry before this change), following the
exact pattern `MeasurementDeclaration` already uses for `leaves`/
`primary_leaf_id`/`admission_leaf_ids`/`trajectory_outcome_paths` (rulings
R1 and R9). `run/resolver.py`'s `_canonical_value` already recurses
generically into nested dataclasses (`LeafPolicyDeclaration` instances live
inside `MeasurementDeclaration.leaves`, itself inside `FamilyManifest`) and
reads `_CANONICAL_OMIT_IF_DEFAULT` off `type(value)` for whichever
dataclass it is currently canonicalizing — no change to
`_canonical_value` itself was needed.
`test_leaf_policy_declaration_without_seat_scope_is_digest_neutral` pins
this: a leaf that does not use `seat_scope`/`subject_reduction` hashes
byte-for-byte as it did before this change.

Both invariants are validated in `LeafPolicyDeclaration.from_dict` and in
`__post_init__` (so `dataclasses.replace` cannot smuggle an inconsistent
declaration past parsing), following the existing `scope`/
`deferred_artifact` pattern exactly.

### 4. Enforcement — `_enforce_subject_seat_primaries`

`task/evaluation.py`'s `_enforce_declared_leaf_policy` now also calls
`_enforce_subject_seat_primaries(score_set, manifest, seat_context)`, which
applies the following rules to every returned envelope whose declared leaf
has `seat_scope == "subject_seat"` **and** `status == "ok"` (nothing is
applied to `seat_scope == "cell"` leaves, and nothing is applied to a
`status == "invalid_measurement"` envelope — that is the scorer's own
domain):

- **Exactly one subject seat `S`.** `S` must be a key of
  `score.utility_by_seat`, and `score.primary` must equal
  `score.utility_by_seat[S]` (value **and** unit). The two conditions are
  checked — and raise — separately, so the message names which one failed:
  - `"leaf {leaf_id!r} scored ok for subject seat {subject!r} but its
    utility_by_seat does not carry that seat"`
  - `"leaf {leaf_id!r} scored ok for subject seat {subject!r} but its
    primary does not equal utility_by_seat[subject]"`
- **Zero subject seats.** An `ok` envelope is itself a violation:
  `"leaf {leaf_id!r} is declared seat_scope=subject_seat and scored ok with
  no subject seat"`.
- **Two or more subject seats (self-play).** An `ok` envelope is a
  violation unless the leaf declares `subject_reduction`:
  `"leaf {leaf_id!r} scored ok over {N} subject seats without a declared
  subject_reduction"`. The kernel never interprets what the declared
  identifier (e.g. `"mean"`) means — it only requires that a family
  declared *some* reduction before claiming a scalar over more than one
  subject seat.

These are **contract violations the kernel raises on**, not
`invalid_measurement` — reporting `invalid_measurement` for the same three
cases (reasons `no_subject_seat` / `ambiguous_subject_seat`) is the
scorer's own job. This check exists to catch a scorer that claims a scalar
it may not claim, regardless of whatever the scorer itself believed (a
scorer may compute a perfectly reasonable mean and still be rejected, if
the manifest never declared that reduction).

### 5. Protocol test — `FamilyScoringFixture` and the synthetic per-seat family

`tests/test_shared_runner_scoring_contract.py`'s `FamilyScoringFixture`
gains `subject_seats: tuple[str, ...] = ()` and
`profile_by_seat: Mapping[str, str] = dataclasses.field(default_factory=lambda: MappingProxyType({}))`
(a `MappingProxyType` cannot be a *plain* dataclass default under this
repository's Python — it is unhashable — hence the `default_factory`).
Seat-insensitive fixtures (housing, procurement_allocation,
procurement_grounding, commercial_state_calibration, the label-tally
reference family) pass nothing and are unaffected; their scorers see the
same empty `SeatContext` they always have.
`_assert_family_obeys_the_scoring_contract` now builds
`SeatContext(subject_seats=case.subject_seats, profile_by_seat=case.profile_by_seat)`
per fixture and threads it into `replay_family_scoring_input`.

A new synthetic, kernel-owned family exercises rule 2 end to end:

- `_SeatScopedPlugin` — a `_ReferencePlugin` subclass (same style as
  `_TrajectoryEmbeddingPlugin`) with two **real** seats, `"x"` and `"y"`
  (not the single `"participant_0"` seat the label-tally family reuses):
  seat `"x"` acts in `round_one`, seat `"y"` in `round_two`, so the
  terminal outcome (`{"label_by_seat": {"x": ..., "y": ...}}`) carries one
  label per seat.
- `_SeatScopedScorer` — publishes `utility_by_seat` for both seats (1.0 if
  the seat's label is `"x"`, else 0.0) and a `primary` that follows rule
  2's reduction. `mode` selects between the well-behaved default and three
  adversarial behaviours, each named for the exact violation it exercises:
  `"wrong_primary"`, `"missing_utility_seat"`, and
  `"ok_despite_zero_seats"`. In the default mode, for two or more subject
  seats the scorer always attempts a mean reduction — whether that `ok`
  envelope is actually *permitted* then depends solely on whether the
  manifest declares `subject_reduction`, which is the kernel's decision to
  make, not the scorer's.
- `_seat_scoped_case()` / `_seat_scoped_family_manifest(subject_reduction=...)`
  — reuse `_reference_case`/`_reference_family_manifest`'s generalized
  parameters (added by this change: `seat_ids`, `case`, `family_manifest`,
  `subject_seats`, `extra_pins` on `_reference_case`/
  `_build_reference_setup`/`_run_reference_episode`). The manifest also
  declares `scoring.reference_provider_ids` for the leaf's two
  `_reference_leaf`-minted implementation components, because
  `resolve_run_plan`'s pin-completeness check
  (`run/resolver.py`'s `_required_pin_kinds`) has no way to know, at
  plan-resolution time, which implementation refs a leaf's `ScoreEnvelope`
  will carry at finalize time — declaring them is what makes the extra
  pins `_run_seat_scoped_episode` supplies required (and therefore
  accepted) rather than "unreferenced".

**Enrollment note.** This family reuses the already-trusted key
`("kernel_contract_reference_v1", "1.0.0", "kernel_contract_reference_plugin")`
for `register_trusted` (as every other `_ReferencePlugin` subclass in this
file does, each in its own standalone `PluginRegistry`), but the singleton
protocol-path test passes a **fictional** key,
`("kernel_contract_seat_scoped_v1", "1.0.0")`, to
`_assert_family_obeys_the_scoring_contract` purely for messaging and the
`_SINGLE_FIXTURE_EXEMPT_FAMILIES` lookup (that function's `key` parameter
is never checked against the registration's actual manifest identity).
That fictional key is added to `_SINGLE_FIXTURE_EXEMPT_FAMILIES` because
seat `"x"` always acts in `round_one` and seat `"y"` always in
`round_two` — there is no order-swap analogous to the label-tally family's
`(x, y)`/`(y, x)` permutation trick that could produce a second,
outcome-identical, trajectory-differing fixture for two seats with fixed
roles. `registry.py`'s `TRUSTED_BUILTIN_PLUGIN_KEYS` was not touched.

## Stated limits (from the ruling, verbatim in substance)

- A family whose case names the tested seat is **not cross-checked**
  against the block's subject seat; a plan that puts the model in the
  other seat is an authoring error this ruling does not detect.
- Self-play aggregation semantics (what `"mean"` or any other
  `subject_reduction` identifier actually computes) are the family's, not
  the kernel's. The kernel only requires the identifier was declared
  before a scalar over multiple subject seats is claimed.
- Opponent identity is `profile_by_seat[opponent_seat]`. An agent profile
  id is not automatically an upstream policy id: a family that needs the
  latter (negarena's `opponent_policy_id`) maps profile id → policy id
  deterministically and pins that mapping; an unknown profile id is
  `invalid_measurement`, never a guessed policy. (This kernel change does
  not implement any such mapping — that is per-family migration work,
  outside its scope, exactly as ruling R12 item 3 describes.)

## Deviation from the file list originally scoped for this change

Two test files outside the change's originally-scoped file list —
`tests/test_shared_runner_family_scoring_input.py` and
`tests/test_shared_runner_family_scoring_input_sequential.py` — call
`replay_family_scoring_input` directly and were broken by the new required
`seat_context` keyword. Both were fixed mechanically (add
`seat_context=SeatContext((), {})` at each call site; extend the
signature-shape assertion in
`test_replay_family_scoring_input_has_no_episode_result_parameter` to
include the new parameter name) in commit
`fix(tests): thread the required SeatContext into direct
replay_family_scoring_input callers`. No behavioral change to either file.
This was necessary for the full suite to pass zero-failed, which this
change's own verification step requires.

## Commits

1. `feat(evaluation): carry SeatContext on FamilyScoringInput from the plan block and cell`
   — ruling items 1, 5, and 6.
2. `feat(schemas): declare per-seat primaries with LeafPolicyDeclaration.seat_scope`
   — ruling item 2 (declaration only; no enforcement yet).
3. `feat(evaluation): enforce the subject-seat primary rule at finalize`
   — ruling item 3.
4. `test(scoring-contract): exercise a per-seat family through the protocol path`
   — ruling item 4.
5. `fix(tests): thread the required SeatContext into direct replay_family_scoring_input callers`
   — mechanical fix for two test files outside the original scope (see above).
6. `docs: record ruling R12 seat-context design and tests` — this document.

## Every test added or extended for this ruling

`tests/test_shared_runner_schemas.py`:

- `test_leaf_policy_declaration_without_seat_scope_defaults_to_cell`
- `test_leaf_policy_declaration_without_seat_scope_is_digest_neutral`
- `test_leaf_policy_declaration_accepts_a_subject_seat_leaf_with_a_reduction`
- `test_leaf_policy_declaration_accepts_a_subject_seat_leaf_without_a_reduction`
- `test_leaf_policy_declaration_rejects_an_unknown_seat_scope`
- `test_leaf_policy_declaration_rejects_subject_reduction_on_a_cell_scoped_leaf`
- `test_leaf_policy_declaration_post_init_rejects_subject_reduction_bypassing_from_dict`

`tests/test_shared_runner_family_evaluation.py` (the finalizer test file —
located via `grep -l finalize_family_execution tests/`; this repository's
actual name for it is `test_shared_runner_family_evaluation.py`, not
`test_shared_runner_execution.py`/`test_shared_runner_evaluation*.py`):

- `test_finalizer_threads_seat_context_from_the_plan_block_and_cell`
- `test_replay_rejects_a_receipt_whose_agent_profile_seats_disagree_with_the_plan`
- `test_audit_rejects_a_receipt_whose_agent_profile_seats_disagree_with_the_plan`

`tests/test_shared_runner_scoring_contract.py`:

- `test_seat_scoped_singleton_subject_seat_primary_passes_the_protocol_path`
- `test_seat_scoped_singleton_primary_mismatch_is_rejected_at_finalize`
- `test_seat_scoped_singleton_missing_utility_seat_is_rejected_at_finalize`
- `test_seat_scoped_zero_subject_seats_ok_is_rejected_at_finalize`
- `test_seat_scoped_two_subject_seats_without_reduction_is_rejected_at_finalize`
- `test_seat_scoped_two_subject_seats_with_declared_reduction_is_accepted_at_finalize`

(unchanged behaviour, mechanical signature fix only)
`tests/test_shared_runner_family_scoring_input.py` and
`tests/test_shared_runner_family_scoring_input_sequential.py`.

## Per-rule enforcement, test, and mutation coverage

| Rule | Enforced by | Positive test | Negative test | Mutation-verified |
|---|---|---|---|---|
| Singleton: `S ∈ utility_by_seat` | `_enforce_subject_seat_primaries` | `test_seat_scoped_singleton_subject_seat_primary_passes_the_protocol_path` | `test_seat_scoped_singleton_missing_utility_seat_is_rejected_at_finalize` | yes — disabling the `subject not in score.utility_by_seat` guard changes the raised exception from a named `ValueError` to a raw `KeyError` |
| Singleton: `primary == utility_by_seat[S]` | `_enforce_subject_seat_primaries` | `test_seat_scoped_singleton_subject_seat_primary_passes_the_protocol_path` | `test_seat_scoped_singleton_primary_mismatch_is_rejected_at_finalize` | yes — disabling the equality guard makes the wrong-primary receipt seal successfully (test fails with "DID NOT RAISE") |
| Zero subject seats | `_enforce_subject_seat_primaries` | (see reduction-accepted test for the same helper's other paths) | `test_seat_scoped_zero_subject_seats_ok_is_rejected_at_finalize` | yes — disabling the `len(subject_seats) == 0` guard falls through to the ambiguous-reduction branch, changing the raised message (test fails on the specific-message assertion) |
| Two-plus seats without declared reduction | `_enforce_subject_seat_primaries` | `test_seat_scoped_two_subject_seats_with_declared_reduction_is_accepted_at_finalize` | `test_seat_scoped_two_subject_seats_without_reduction_is_rejected_at_finalize` | yes — disabling the `subject_reduction is None` guard makes the ambiguous receipt seal successfully (test fails with "DID NOT RAISE") |
| Seat-set consistency (replay) | `_check_seat_context_seat_set` | (implicit — every passing finalize/replay test) | `test_replay_rejects_a_receipt_whose_agent_profile_seats_disagree_with_the_plan` | yes — disabling the check lets a tampered receipt replay silently (no exception at all, not just a different one) |
| Seat-set consistency (audit) | `_check_seat_context_seat_set` | (implicit — every passing finalize/audit test) | `test_audit_rejects_a_receipt_whose_agent_profile_seats_disagree_with_the_plan` | yes — disabling the check falls through to the pre-existing generic `agent_profile_sha256_by_seat` mismatch check, changing the message (test fails on the specific-message assertion) |
| `LeafPolicyDeclaration.seat_scope`/`subject_reduction` cross-field invariant | `LeafPolicyDeclaration.__post_init__` | `test_leaf_policy_declaration_accepts_a_subject_seat_leaf_with_a_reduction` | `test_leaf_policy_declaration_rejects_subject_reduction_on_a_cell_scoped_leaf`, `test_leaf_policy_declaration_post_init_rejects_subject_reduction_bypassing_from_dict` | yes — disabling the `__post_init__` guard makes the `dataclasses.replace` bypass test fail with "DID NOT RAISE" |
| Digest neutrality of the two new fields | `_CANONICAL_OMIT_IF_DEFAULT` | `test_leaf_policy_declaration_without_seat_scope_is_digest_neutral` | (same test; asserts both the neutral and non-neutral case) | verified directly by the test's own byte-equality assertions, not a separate mutation |

## Verification

Targeted (`tests/test_shared_runner_schemas.py
tests/test_shared_runner_scoring_contract.py tests/test_shared_runner_smoke.py
tests/test_shared_runner_family_evaluation.py`): **149 passed, 0 failed.**

Full suite (`pytest -q`, no bridges exported): **2271 passed, 125 skipped,
1 xfailed (pre-existing, unrelated to this change), 0 failed.**
