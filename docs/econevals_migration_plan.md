# econevals migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, `git log --oneline origin/main..HEAD`,
`docs/govsim_migration_plan.md`), read in full before writing this plan; the
second reference (`.../AERead/.worktrees/collusion-migrate`) and
`migration_worked_example.md` were read for the R9/R10 trajectory-embedding
precondition and the four traps, respectively.

## Preconditions confirmed on this base (origin/main via `git fetch`)

- `git fetch origin` ran clean; `HEAD` (`e848c455`) already equals
  `origin/main` (`git diff --stat origin/main..HEAD` is empty) — branch
  `zeyu/econevals-contract-migration` is exactly at `origin/main`.
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` (plus `FinalizeTimeLeafPolicy`, `MeasurementDeclaration`
  with `leaves`/`primary_leaf_id`/`admission_leaf_ids`) exists in
  `src/aeread/shared_runner/schemas.py`.
- `('econevals', '0.1.0', 'econevals_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:64`), and
  `("econevals", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1054`). `environment.py`'s
  `register_plugin` already calls `registry.register_trusted(...)`, so this
  family is not exposed to the rebase-breaks-registration trap the worked
  example describes (trap 1) — it was already carried this way before this
  branch forked.
- **Trajectory-embedding precondition (rulings R9/R10, round 3).** Read
  `EconevalsPlugin.outcome()` (`environment.py`): it returns exactly
  `{termination_reason, period_count, num_attempts}` — three scalars, never
  the `attempts` list or any per-period record. `attempts` (the trajectory the
  two measurement leaves' `score_terminal_state` reads via
  `state["attempts"][-1]`) lives only on `terminal()`/`state`, which
  `FamilyScoringInput.phase_instances` reconstructs but `outcome` does not
  carry. So this family's outcome does **not** embed its trajectory, the R9/R10
  precondition ("if it does...") is false, and the milestone's own fallback
  check does not apply: `grep -c trajectory_outcome_paths
  src/aeread/shared_runner/schemas.py` **is 0 on this base**, but that is not a
  blocker here — it would only be one if outcome embedded the trajectory,
  and it confirmed does not. (This is the same situation the reference
  migration recorded for govsim, for the same reason: an outcome of final
  aggregates only.)
- Family test suite, bridge exported
  (`AEREAD_ECONEVALS_BRIDGE_PYTHON`, `AEREAD_ECONEVALS_UPSTREAM_ROOT`):
  `tests/test_econevals_cases.py`, `test_econevals_environment.py`,
  `test_econevals_measurement.py`, `test_econevals_replay.py`,
  `test_econevals_tools.py` — **97 passed, 0 failed, 0 skipped** in 144.05s.
  Matches `docs/econevals_adapter_status.md`'s own reported per-file
  breakdown (22 + 29 + 24 + 10 + 12 = 97; that doc's 107 total also includes
  `tests/test_shared_runner_smoke.py`, which is a kernel-level suite, not this
  family's own, and is not part of this baseline). This is the green baseline
  this migration must not regress.

## Today's declared leaves and their `input_scope`

Exactly **two** leaves are ever built for one case — `measurement.build_leaves(track,
gold_optimum)` returns `(gate_leaf, objective_leaf)` for that case's own `track` only;
a procurement case never builds scheduling's or pricing's leaf pair. Because the leaf
*id* string is parameterized by track today, there are six distinct
`MeasurementLeafSpec` declarations family-wide, two of which are live for any one case:

| Leaf id (today) | Estimand id | `input_scope` | Verifier family | Reference kind | Evaluation class |
|---|---|---|---|---|---|
| `econevals_procurement_gate_leaf` | `econevals_procurement_gate` | `answer` | `rule_constraint` | `constraint_satisfaction` | `deterministic` |
| `econevals_procurement_objective_leaf` | `econevals_procurement_utility` | `terminal_state` | `objective_reference` | `exact_optimum` | `deterministic` |
| `econevals_scheduling_gate_leaf` | `econevals_scheduling_gate` | `answer` | `rule_constraint` | `constraint_satisfaction` | `deterministic` |
| `econevals_scheduling_objective_leaf` | `econevals_scheduling_blocking_pairs` | `terminal_state` | `objective_reference` | `exact_optimum` | `deterministic` |
| `econevals_pricing_gate_leaf` | `econevals_pricing_gate` | `answer` | `rule_constraint` | `constraint_satisfaction` | `deterministic` |
| `econevals_pricing_objective_leaf` | `econevals_pricing_profit` | `terminal_state` | `objective_reference` | `exact_optimum` | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every scorer is
deterministic arithmetic or a deterministic bridge call over case-sealed and
episode-replayed data (see classification below).

**Shared shape, always a hybrid gate** (per `measurement.py`'s own module docstring
and `docs/research/verifier_taxonomy.md` section 10's `hybrid_gate`: "apply
deterministic prerequisites such as legality, then report the admitted outcome
vector"): every `score_procurement`/`score_scheduling`/`score_pricing` checks legality
first; only when the gate passes does it compute the objective. When the gate fails
outright (a genuinely illegal but well-formed submission), the gate leaf itself scores
`status="ok"`, `primary=0.0` — a real, scored domain fact, never `invalid_measurement`
(the module's own `_gate_fail` docstring is explicit about this) — and the objective
leaf is returned as `None`, not as its own envelope. Only a malformed/unparseable
submission (`attempt["error"] == "malformed_input"`) produces `status="invalid_measurement"`,
and today only on the gate leaf (`_invalid_measurement`'s own docstring calls this "the
measurement_validity (admission) failure path"). **Plumbing note for the next
milestone, not this one:** `FamilyScoreSet`/the finalizer's `_enforce_declared_leaf_policy`
requires the scorer to return *exactly* the declared leaf set on every case
(`set(produced_leaf_ids) == set(declared.leaf_ids)`), so a milestone-1 `__call__` must
turn that `None` into an explicit `invalid_measurement` envelope for the objective leaf
whenever the gate is malformed — a signature/plumbing widening, mirroring the worked
example's trap 3 (govsim's `float | None` baseline), never a change to the scoring
arithmetic itself.

## Reference-source classification

| Leaf role | What its scorer needs to produce `status="ok"` | Classification |
|---|---|---|
| gate (legality/feasibility) | This episode's own last recorded attempt (`state["attempts"][-1]`), checked against a deterministic rule: the pinned upstream legality primitive for procurement/scheduling (`evaluate_alloc`/`is_valid_matching`, via the bridge), or AERead's own declared non-negativity/key-match rule for pricing (no upstream primitive exists to delegate to there) | **replayed-episode** |
| objective (exact optimum) | (a) `family_case["gold_optimum"]` — computed exactly once at case-generation time (`cases.py`'s `_build_{procurement,scheduling,pricing}_candidate`) via a deterministic solver call sealed into the validated `family_case` (procurement: bridge ILP solve; scheduling: the Gale-Shapley existence theorem, an analytic claim requiring no per-instance solve at all; pricing: a bridge monopoly-price closed form) — never from running any policy/episode; (b) this episode's own last recorded attempt's achieved value (`utility` / `len(blocking_pairs)` / summed `profits`) | **closed-form-from-case** (the reference `v_star`) **+ replayed-episode** (the achieved value) |

Every `score_procurement`/`score_scheduling`/`score_pricing` function's own parameter
list confirms this exhaustively: each takes only `gold_optimum` (case-sealed,
closed-form) and `attempt` (this episode's own state) — never a second episode's
outcome, never a rater/judge verdict. **No leaf in this family is separate-run-artifact
or judge-artifact today**, so both are finalize-time-eligible by the milestone's own
rule (closed-form and replayed-episode leaves are finalize_time).

## Reference gap: the manifest's family-level `primary_estimand` is not a leaf

`family_manifest()` (`environment.py`) declares
`measurement.primary_estimand = "econevals_headroom_capture"`, annotated by its own
adjacent comment as "a coarse descriptor, not a literal stand-in for any one track's
units/direction" — the author already flags it as non-literal. Reading
`verifier_taxonomy.md` section 5.3, `headroom_capture = (V_agent - B) / (V_UB - B)`,
where `B` is a `comparison_baseline` reference — per section 6's `baseline_delta`
contract, "compare native outcomes with a named, versioned, executable policy under the
same design," i.e. **the output of a separate baseline-policy episode run under the
same case**, not anything derivable from the case alone. `measurement.py`'s own module
docstring confirms no such leaf is built: "this module deliberately never computes
`headroom_capture` itself ... and no `baseline_headroom` reference/leaf is declared
anywhere in spec section 2's table for this milestone."

So: **`econevals_headroom_capture` — the estimand named by the manifest's own
`primary_estimand` field — requires a `comparison_baseline` separate-run artifact (an
executable baseline policy's own episode under the same case) by its estimand
definition, and no leaf realizing it exists today.** No honest finalize_time leaf can
be named "the primary_estimand's own leaf" for this family as currently built. Per the
milestone's own rule, this is recorded as the reference gap, not fixed here: splitting
the estimand into an `_own` finalize_time metric (what the two existing leaves already
report — achieved value vs. the exact optimum, in native units) and a `_vs_baseline`
deferred metric (once a baseline-run artifact exists) is an owner decision outside this
migration's scope. This migration does not invent a `headroom_capture` leaf, deferred or
otherwise, and does not touch the manifest's `primary_estimand` string.

## Proposed primary (for the leaf-policy fields this migration will add): the objective leaf

Since no leaf realizes `econevals_headroom_capture`, the primary this migration
proposes is the leaf that already realizes the substantive economic headline the
family's own docs describe as the design's point: the **objective (`exact_optimum`)
leaf** — "the achieved value `V_agent` in the track's own native units... [compared to]
the case's own pinned exact optimum" (`measurement.py` module docstring;
`docs/econevals_adapter_spec.md`'s milestone-2 build note: "the objective leaf primary
is native-units, not `headroom_capture`"). This is not a same-named coincidence (per
ruling R8, the correspondence with `primary_estimand` is unenforced and, here,
genuinely absent by string) — it is the closest-in-meaning, already-implemented
substitute: `headroom_capture`'s own formula divides an achieved-value-vs-optimum
quantity by a baseline-relative denominator, and the achieved-value-vs-optimum half is
exactly what the objective leaf already reports, in native units, without the
baseline term this family cannot yet compute. The gate leaf is explicitly not
proposed as primary: it is a legality precondition (`hybrid_gate`'s "deterministic
prerequisite"), not the outcome being measured, and per the module docstring's own
framing, "regret... or any headroom-style ratio is left for a consumer to compute" from
the objective leaf's two typed values — the objective leaf is the "outcome" that
`hybrid_gate` says to report once admitted.

**Leaf-identity finding that follows from this (a decision, not yet code):**
`family_manifest()` takes no arguments and is called once per family/version, and
`_enforce_declared_leaf_policy` requires every case's produced `leaf_id` set to equal
the manifest's *one* static declared set exactly (`set(produced_leaf_ids) ==
set(declared.leaf_ids)`). Today's `leaf_id`s are track-parameterized
(`econevals_{track}_gate_leaf` / `econevals_{track}_objective_leaf`), so a procurement
case and a scheduling case produce disjoint `leaf_id` sets — incompatible with one
static manifest declaration. This plan's leaf-policy fields therefore use
track-*agnostic* `leaf_id`s: `econevals_gate_leaf` and `econevals_objective_leaf` (the
per-track distinctions — `estimand_id`, `units`, `direction`, `reference.source_sha256`
— all live one level down, inside each `MeasurementLeafSpec`, and are untouched by this
rename; `_enforce_declared_leaf_policy` never inspects them). Renaming these two
identifiers is milestone-1 code, mirroring the worked example's "signature change only,
never the scoring arithmetic" — recorded here so the choice is visible before it is
made.

- `primary_leaf_id = econevals_objective_leaf`
- `leaves = [(econevals_gate_leaf, finalize_time), (econevals_objective_leaf, finalize_time)]`

## Admission: `econevals_objective_leaf` alone

Per the spec: "Admission. Precisely the leaves whose `invalid_measurement` status
excludes the receipt... Diagnostic leaves are receipted but do not gate admission
unless declared." In this family's own vocabulary, `invalid_measurement` is
`_invalid_measurement`'s "measurement_validity (admission) failure path," triggered only
by a malformed/unparseable submission — never by a well-formed-but-illegal one (that is
`_gate_fail`'s `status="ok"`, `primary=0.0`, a real scored fact). Malformed input always
disables the objective (there is no legal attempt to score `V_agent` against), so the
objective leaf's own `invalid_measurement` status (once the plumbing note above gives it
one explicitly, rather than `None`) already covers exactly the case that should exclude
the receipt; a malformed submission's gate-leaf `invalid_measurement` is redundant with
it, not an independent gate. `admission_leaf_ids = (econevals_objective_leaf,)` is the
default the spec gives when none is declared beyond the primary
(`MeasurementDeclaration.__post_init__`: `admission_leaf_ids = self.admission_leaf_ids
or (self.primary_leaf_id,)`), and nothing here motivates widening it — mirroring
govsim's own minimal single-leaf admission set, for an analogous reason (its
rule/constraint leaves are diagnostics, not admission gates either, just for a
different reason: govsim's are normative-tradeoff diagnostics per
`verifier_taxonomy.md` section 4; econevals's gate is a legality precondition whose own
failure mode is never `invalid_measurement`).

## Deferred leaves: none

Both leaves are proposed `scope="finalize_time"`. Neither depends on a judge verdict,
external rater protocol, or a separate baseline-policy run — see the
reference-source classification above. There is no artifact for a `deferred_artifact`
field to name for either of the two implemented leaves. (The one leaf that *would* need
`deferred_artifact` — a `headroom_capture`/baseline-comparison leaf — does not exist in
this family's manifest or scorer today; see the reference gap above. This migration
does not create it.)

## Paired-history pair: constructible — yes

Confirmed directly against this base's `EconevalsPlugin.outcome()` (see the
trajectory-embedding precondition above): it returns only
`{termination_reason, period_count, num_attempts}` — final aggregates, never the
`attempts` list the two leaves' `score_terminal_state` reads. `attempts` lives only on
`terminal()`/`state`, which `FamilyScoringInput.phase_instances` reconstructs but
`outcome` does not carry — the same shape the R9/R10 preconditions text records for
govsim, confirmed here independently rather than assumed from that precedent.

Concretely buildable analogously to the reference migration's own pair (verified
against the real bridge there, not merely asserted): two bridge-backed episodes on the
*same* case whose final recorded attempt (period, termination reason, and — for
procurement/pricing — the aggregate feasibility/legality outcome) is identical, so
`termination_reason`/`period_count`/`num_attempts` land byte-identical, but whose
*earlier* periods' submitted attempts differ (e.g. two different infeasible/illegal
intermediate submissions before an identical final legal one, for procurement or
pricing; two different non-final matchings before an identical final one, for
scheduling) — same outcome, a genuinely different `attempts` trajectory. Because
neither of this family's two leaves has `input_scope="trajectory"` (both are `answer`
or `terminal_state`, scored from the *last* attempt only), this pair does not exercise a
trajectory-scoped leaf the way govsim's pair does — there is none to exercise — but it
still gives the mislabelling contrapositive (R7) a non-trivial pair to check both
terminal-scoped leaves against, and it is what "constructible" asks for here: an outcome
that is provably compatible with more than one distinct trajectory.

## Rulings that do not apply here

R9/R10 (trajectory embedded in outcome): not applicable — confirmed above, `outcome()`
carries no trajectory-bearing field, so no `trajectory_outcome_paths` declaration is
needed and none exists on this base to declare it with.
