# negarena migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, commits `6dbe0c7..98f3b55`, and its own
`docs/govsim_migration_plan.md`), read in full before writing this plan. The
second reference (`.../AERead/.worktrees/collusion-migrate`) is read for the
R9/R10 (trajectory-embedded-in-outcome) case, which does not apply here (see
below).

## Preconditions confirmed on this base (`git fetch origin`, then checked directly)

- Branch `zeyu/negarena-contract-migration` is exactly at `zeyu/kernel-r9r10`
  (0 commits ahead, `git merge-base --is-ancestor zeyu/kernel-r9r10 HEAD`
  succeeds; `git log --oneline zeyu/kernel-r9r10..HEAD` is empty before this
  milestone's commit).
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`
  (line 465); `LeafPolicyDeclaration` exists in
  `src/aeread/shared_runner/schemas.py` (line 341), alongside
  `FinalizeTimeLeafPolicy` (409) and `MeasurementDeclaration` (433) with
  `leaves`/`primary_leaf_id`/`admission_leaf_ids`/`trajectory_outcome_paths`
  fields.
- `('negarena', '0.1.0', 'negarena_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:76`),
  and `("negarena", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1674`).
  `environment.py::register_plugin` already calls
  `registry.register_trusted(family_manifest(), plugin)`, so this family is
  not exposed to the worked example's trap 1 (registration silently breaking
  after rebase) — it was already carried this way before this branch forked.
- `grep -c trajectory_outcome_paths src/aeread/shared_runner/schemas.py` is
  **11** (nonzero) — the field exists on this base. As shown below, negarena's
  own `outcome()` does not embed the trajectory, so this field is not needed
  for this family's declaration, but its existence on this base is confirmed
  per the milestone's precondition check regardless.
- `NegarenaPlugin.outcome()` (`environment.py:494-503`) returns only
  `{termination_reason, iteration_count, last_answer, last_trade}` — a
  terminal summary, never `state["history"]`. Rulings R9/R10 (a family whose
  outcome embeds its trajectory) therefore do not apply to this family; see
  "Rulings that do not apply here" below.
- Family test suite, bridge exported (`AEREAD_NEGARENA_UPSTREAM_ROOT`,
  `AEREAD_NEGARENA_BRIDGE_PYTHON`): `tests/test_negarena_environment.py`,
  `tests/test_negarena_cases.py`, `tests/test_negarena_harness.py`,
  `tests/test_negarena_parity.py`, `tests/test_negarena_measurement.py`,
  `tests/test_negarena_kernel_finalizer.py`,
  `tests/test_negarena_provisioning.py`, `tests/test_shared_runner_smoke.py`
  — **86 passed, 3 failed**, 0 skipped, in 231.82s.

  **The baseline is not clean, and the 3 failures are pre-existing, not
  introduced by this milestone (no code was changed to produce them).** All
  three are in `tests/test_negarena_kernel_finalizer.py`
  (`test_finalize_family_execution_does_not_crash_and_seals_a_typed_receipt`,
  `test_finalize_family_execution_seals_the_complete_evidence_lifecycle`,
  `test_run_scripted_negarena_episode_seals_the_complete_lifecycle_automatically`),
  and all three fail identically:
  `FileNotFoundError: ... src/aeread/shared_runner/execution.py`. That helper
  (`_build_negarena_run_plan`, lines 268-270) hashes
  `Path(__file__).parents[1] / "src" / "aeread" / "shared_runner" /
  "execution.py"` to build an `ImplementationPin.sha256` for the harness/
  runtime pins — a path that predates the kernel reorg this branch's base
  (`zeyu/kernel-r9r10`) already carries (`execution.py` -> `task/execution.py`,
  spec section 5 item 1: "`execution`/`scheduler`/`receipts`/`tools` ->
  `task.*`"). The test file's *imports* were already updated to
  `aeread.shared_runner.task.execution` (line 40); only this one
  hash-computation literal was missed. `docs/negarena_adapter_status.md`'s
  "89 of 89" claim is stale relative to this base for exactly this reason —
  it predates the rebase onto `zeyu/kernel-r9r10` (status doc says "Last
  verified 2026-09-02"; this branch's base moved after that).

  This is a one-line, mechanical leftover of exactly the kind spec section 5
  item 1 ("import migration to the reorganized kernel") exists to clean up,
  not a measurement/contract design question — it belongs to the next
  milestone's import-migration step, not to this milestone, which changes no
  code. Recorded here rather than fixed here so the next milestone starts
  from an accurate, not an assumed, baseline.

## Today's declared leaves and their `input_scope`

Both leaves are declared unconditionally for every case
(`measurement.py::build_leaves`); the manifest itself (`environment.py`'s
`family_manifest()`) does not yet declare `leaves`/`primary_leaf_id`/
`admission_leaf_ids` at all on this base — that is exactly what the next
milestone adds.

| Leaf id | Estimand id | `input_scope` (estimand / reference) | Verifier family | Evaluation class |
|---|---|---|---|---|
| `negarena_seat_outcome_leaf` | `negarena_seat_outcome` | `trajectory` / `trajectory` | `comparative` (`head_to_head`) | `deterministic` |
| `negarena_agreement_reached_leaf` | `negarena_agreement_reached` | `terminal_state` / `terminal_state` | `rule_constraint` (`constraint_satisfaction`) | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every
scorer is deterministic — either bridge-delegated settlement arithmetic
(leaf 1) or a pure predicate over `terminal["reason"]` (leaf 2).

## Reference-source classification

| Leaf | What the scorer needs for a `status="ok"` value | Classification | Why |
|---|---|---|---|
| `negarena_seat_outcome_leaf` | This episode's `state["history"][-2]` (the pre-accept proposed trade) and `terminal["reason"/"iteration_count"/"last_answer"]`, plus the validated `family_case.scenario` (starting resources/valuation/goal_kind) — all fed through `NegarenaBridge.settle()` to reproduce upstream's own `after_game_ends()`. The "opponent" in `HEAD_TO_HEAD_REFERENCE_ID`'s `reference_kind="head_to_head"` is the *other seat in this same episode* (`result["player_outcome"][opponent_index]`, read off the same `bridge.settle()` call) — never a second, separately-run episode. | **replayed-episode** | Everything the scorer touches — history, terminal, family_case — comes from this one episode's own re-executed trajectory/outcome (`FamilyScoringInput.phase_instances`/`outcome`). No artifact from another run, and no rater/judge verdict, is needed by the estimand's own definition ("this seat's own realized value, against the specific opponent it was paired with," `measurement.py`'s module docstring) — only by the plumbing, see below. |
| `negarena_agreement_reached_leaf` | Only `terminal["reason"]` (this episode's own termination reason) — no bridge call, no settlement. | **replayed-episode** | A pure predicate over this episode's own terminal state; not derivable from `family_case` alone (the actual termination reason depends on how play unfolded, not on the static case), and needs no separate-run or judge artifact. |

Both leaves classify as **replayed-episode**, so both stay `scope="finalize_time"`
per the spec's rule ("closed-form and replayed-episode leaves are
finalize_time"). Neither leaf's estimand, by its own definition, requires a
separate-run baseline or a judge verdict — **reference gap: none**.

### A real gap exists, but it is plumbing, not a reference gap — flagged, not resolved here

`NegarenaScorer.__call__` (`measurement.py:437-479`) does not compute a real
score today: it always returns `negarena_seat_outcome_leaf` as
`invalid_measurement` with reason
`"negarena_kernel_finalizer_lacks_seat_pairing_context"`, and never returns
`negarena_agreement_reached_leaf` at all. The reason, per its own docstring
and `runner_defect_ledger.md` D-15: the leaf is inherently **per seat** (one
`ScoreEnvelope` for RED, a separate one for BLUE — `measurement.py`'s module
docstring), but the finalizer's call site gives the scorer no way to know
*which* seat is the tested subject. Checked directly against this base's
contract, not assumed: `FamilyScoringInput` (`task/evaluation.py:465`) carries
only `outcome, phase_instances, evidence_refs` — no seat/subject/opponent
context — and `finalize_family_execution` (`task/evaluation.py:621-669`) does
not thread `cell.profile_by_seat`/`EvaluationBlock.subject_seats` through to
`plugin.build_scorer(family_case)(scoring_input, evidence_refs=...)` even
though `cell` is in scope there. Separately,
`FamilyScoreSet.__post_init__` (`measurement.py:405-420`) explicitly rejects
two `ScoreEnvelope`s sharing one `leaf_id` ("family score set contains a
duplicate measurement leaf") — so even if seat identity were threaded through,
today's contract has no way to carry *both* seats' envelopes for the *same*
declared leaf in one `FamilyScoreSet`. `replay.py::score_replayed_episode`
already computes both seats' envelopes side by side for test purposes
(`red_outcome`/`blue_outcome`, both under the one
`SEAT_OUTCOME_LEAF_ID`), which is exactly what the finalize-time contract as
it stands cannot accept.

This is **not** the estimand-definition reference gap the milestone is
watching for (the clarifying test is explicit: "not merely by the current
scorer's plumbing," and that is exactly what this is — a call-site/contract
plumbing gap, not a missing artifact the estimand needs). It is also a
narrower, more specific case than D-15's general census (which the new
`FamilyScoreSet` vector already resolves for *distinct*-leaf families like
govsim): negarena needs *one* leaf to carry *two* values for the same
episode, which `FamilyScoreSet`'s one-envelope-per-`leaf_id` invariant
forbids outright. No ledger entry names this narrower case yet.

**Not decided here, and flagged rather than guessed at**, per D-15's own
framing ("the real decision belongs to the kernel owner"): whether the next
milestone's `__call__` picks a fixed subject-seat convention (e.g. always
score the RunPlan cell's declared subject seat, when the contract is extended
to carry one), whether the kernel needs a seat-context extension to
`FamilyScoringInput`/the `FamilyScorer` protocol, or something else. Until
that is resolved, the honest `__call__` for this migration keeps reporting
`negarena_seat_outcome_leaf` as `invalid_measurement` with today's named
reason (the existing, already-documented posture in
`docs/negarena_adapter_status.md`) rather than fabricating a per-seat answer
the call site cannot support — this is exactly the spec's own instruction for
this situation: "the leaf stays finalize_time and reports
`invalid_measurement` with a named reason, the receipt is excluded, and every
doc says so."

## Proposed primary: `negarena_seat_outcome_leaf`

`family_manifest()` (`environment.py:115`) already declares
`measurement.primary_estimand = "negarena_seat_outcome"` — exactly
`SEAT_OUTCOME_ESTIMAND_ID`, the estimand of `negarena_seat_outcome_leaf`. Per
ruling R8 the kernel does not enforce this correspondence mechanically, which
is exactly why a human has to check it: here the two independently-authored
fields agree in meaning (both name "what this seat realized"), not merely by
name coincidence — I read both declarations directly rather than assuming it.

Substantively this leaf is also the adapter's own stated headline number:
`docs/negarena_adapter_status.md` labels it "primary" in its leaf table and
`measurement.py`'s module docstring opens with it as leaf 1; leaf 2
(`negarena_agreement_reached`) is explicitly labelled "diagnostic" in both
places. It is not "the one that was easiest to compute" (spec section 3's
forbidden reasoning) — leaf 2 is in fact the simpler of the two (a pure
predicate over `terminal["reason"]`, no bridge call) and is not proposed as
primary.

## Admission: `negarena_seat_outcome_leaf` alone

Matches the family's own pre-existing, already-committed classification, not
one invented for this migration: `measurement.py`'s module docstring calls
leaf 2 "diagnostic" and states its reason for existing separately — "so a
degenerate no-agreement episode is never silently averaged into the payoff
leaderboard as a 'loss'" (`docs/verifier_taxonomy.md` section 9) — i.e. leaf 2
is designed to be informative even when leaf 1's answer is uninteresting or
invalid, not to gate whether the receipt is admitted. Per the spec
("Diagnostic leaves are receipted but do not gate admission unless
declared"), leaf 2 stays out of `admission_leaf_ids`.

So `admission_leaf_ids = (negarena_seat_outcome_leaf,)`, and the primary is
(trivially) inside admission, satisfying `MeasurementDeclaration.__post_init__`.

Note both leaves already share the identical invalid-termination check
(`INVALID_TERMINATION_REASONS`) in today's scorers — a `malformed_action`/
`invalid_measurement` terminal reason makes *both* leaves invalid together —
but that is a coincidence of the current termination taxonomy, not a reason
to make leaf 2 an admission gate: the two leaves measure different things
(realized value vs. whether a resolution was reached) and diagnostic status
is a property of what the leaf is *for*, not of when it happens to agree with
the primary.

## Deferred leaves: none

Both leaves are `scope="finalize_time"` (see the reference-source
classification above: both are replayed-episode, neither needs a judge
verdict or a separate-run artifact by its estimand's own definition). There
is no artifact for a `deferred_artifact` field to name. The open plumbing
question above (D-15's per-seat case) is a blocker to `__call__` returning a
real `ok` value for leaf 1 today, not a reason to mark it `deferred` — a leaf
may not be marked `deferred` merely because computing it is currently
inconvenient (spec section 4), and this is squarely that: the estimand needs
no artifact that "may not exist yet," it needs a plumbing decision that has
not been made yet.

## Paired-history pair: constructible — yes

`NegarenaPlugin.outcome()` (`environment.py:494-503`) returns only
`{termination_reason, iteration_count, last_answer, last_trade}` — never
`state["history"]`. This is confirmed directly against this base's code, not
assumed from the R9/R10 text's own worked description of govsim ("its outcome
carries only final aggregates"): negarena's `outcome()` is the same shape.

Crucially, on the most common termination path this is even more collapsed
than it first looks: when `reason == "accepted"`, `last_trade` is the
*accepting* turn's own trade tag, which upstream's parser always reduces to
the fixed sentinel dict `{"kind": "none"}` regardless of what was negotiated
earlier (`environment.py`'s `terminal()` docstring; confirmed in
`negarena_bridge_driver.py:305-314`, and used exactly this way by every
golden transcript in `parity.py`, e.g. line 95's
`_scripted_buy_sell_response("NONE", answer="ACCEPT", ...)`). So for any two
episodes that both end in `"accepted"` at the same `iteration_count`, the
`outcome()` dict is byte-identical (`{"termination_reason": "accepted",
"iteration_count": N, "last_answer": "ACCEPT", "last_trade": {"kind":
"none"}}`) **regardless of what the intermediate rounds proposed** — the real
negotiated trade lives only in `state["history"][-2]`, which
`FamilyScoringInput.phase_instances` carries but `outcome()` never does.

Concretely buildable from the existing golden-1 buy_sell transcript
(`parity.py::build_buy_sell_golden_one`, offers `50->30->45->35->42->38->40`
then `ACCEPT`, 8 turns): a second fixture over the same case
(`negarena.buy_sell.0`) using a different intermediate offer sequence of the
same length (e.g. `45->35->50->25->42->38->40`) ending in the identical final
`ACCEPT` turn produces a byte-identical `outcome()` (`iteration_count=8`,
`termination_reason="accepted"`, `last_answer="ACCEPT"`,
`last_trade={"kind":"none"}`) with a genuinely different `phase_instances`
history (different `newly proposed trade`/`message` content in six of the
eight logical actions). This exercises the trajectory-scoped leaf
(`negarena_seat_outcome_leaf`, which reads `state["history"][-2]` — the
*second-to-last* turn, so varying only the earlier offers while keeping the
final two turns fixed keeps the settlement value itself identical too, unless
the pair is built to vary the second-to-last offer specifically, which the
next milestone's fixture author should do deliberately to get a genuine
sensitivity witness per ruling R9's "the pair must show the leaf CAN change"
requirement) and gives the mislabelling contrapositive (R7) a non-trivial
pair to check `negarena_agreement_reached_leaf` against.

No `trajectory_outcome_paths` declaration is needed, and none exists on this
base to declare it with — the whole outcome is checked directly, exactly as
before ruling R9/R10, matching govsim's case rather than collusion's.

## Rulings that do not apply here

R9/R10 (trajectory embedded in outcome): not applicable — confirmed above,
`outcome()` carries no trajectory-bearing field, so no
`trajectory_outcome_paths` declaration is needed.

R11 (no-upstream-code formula conformance): not applicable — negarena has a
real pinned upstream checkout (`vinid/NegotiationArena` at
`c447fafd439a20b84cdedeb2f8a85c4fad764745`) and never reimplements its
settlement math; `parity.py` already establishes byte-identical-`player_outcome`
parity against `NegarenaBridge.replay_transcript`, the genuine article R11
asks for when upstream code exists.
