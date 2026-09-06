# govsim migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration
(worktree `.../AERead/.worktrees/govsim`, commits `6dbe0c7..98f3b55`), read in
full before writing this plan.

## Preconditions confirmed on this base (origin/main via `git fetch`)

- Branch `zeyu/govsim-contract-migration` is exactly at `origin/main`
  (`git merge-base --is-ancestor origin/main HEAD` succeeds).
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` (plus `FinalizeTimeLeafPolicy`, `MeasurementDeclaration`
  with `leaves`/`primary_leaf_id`/`admission_leaf_ids`) exists in
  `src/aeread/shared_runner/schemas.py`.
- `('govsim', '0.1.0', 'govsim_environment')` is in `TRUSTED_BUILTIN_PLUGIN_KEYS`
  (`src/aeread/shared_runner/registry.py:64`), and `("govsim", "0.1.0")` is in
  `_NOT_YET_MIGRATED_TRUSTED_KEYS` (`tests/test_shared_runner_scoring_contract.py:1077`).
  `environment.py`'s `register_plugin` already calls `registry.register_trusted(...)`,
  so this family is not exposed to the rebase-breaks-registration trap the worked
  example describes (trap 1) — it was already carried this way before this branch
  forked.
- `trajectory_outcome_paths` (rulings R9/R10, round 3) does not exist anywhere in
  `schemas.py`/`measurement.py` on this base. Consistent with the task framing:
  govsim's `outcome()` does not embed the trajectory (confirmed below), so R9/R10
  do not apply to this family and this absence is not a blocker.
- Family test suite, bridge exported
  (`AEREAD_GOVSIM_BRIDGE_PYTHON`, `AEREAD_GOVSIM_UPSTREAM_ROOT`):
  `tests/test_govsim_measurement.py`, `test_govsim_replay_skip_behavior.py`,
  `test_govsim_replay.py`, `test_govsim_bridge_driver.py`, `test_govsim_cases.py`,
  `test_govsim_environment.py`, `test_govsim_parity.py` — **108 passed, 0 failed,
  0 skipped**, 1 warning, in 288.93s. This is the green baseline this migration
  must not regress. (Lower than the reference migration's post-migration count of
  119 because the leaf-policy and finalizer-wiring tests it adds do not exist yet
  on this base.)

## Today's declared leaves and their `input_scope`

All five leaves are declared unconditionally for every case
(`measurement.py::build_leaves`); only the scored *values* vary by scenario/policy.

| Leaf id | Estimand id | `input_scope` | Verifier family | Evaluation class |
|---|---|---|---|---|
| `govsim_no_collapse_leaf` | `govsim_no_collapse` | `trajectory` | `rule_constraint` | `deterministic` |
| `govsim_threshold_adherence_leaf` | `govsim_threshold_adherence` | `trajectory` | `rule_constraint` | `deterministic` |
| `govsim_survival_months_leaf` | `govsim_survival_months` | `terminal_state` | `comparative` | `deterministic` |
| `govsim_total_harvest_leaf` | `govsim_total_harvest` | `terminal_state` | `comparative` | `deterministic` |
| `govsim_equality_gini_leaf` | `govsim_equality_gini` | `terminal_state` | `comparative` | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every scorer
is deterministic arithmetic over replayed/recorded state.

## Proposed primary: `govsim_survival_months_leaf`

`family_manifest()` (`environment.py`) already declares
`measurement.primary_estimand = "govsim_survival_months"`. That estimand id is
exactly `SURVIVAL_MONTHS_ESTIMAND_ID`, the estimand of `govsim_survival_months_leaf`
— so the leaf I am proposing as primary is the one the manifest's existing
family-level field already names, not a same-named coincidence chosen for
convenience. Per ruling R8 the kernel does not enforce this correspondence
mechanically (`primary_estimand` and leaf ids are parallel, unenforced
namespaces for other families), which is exactly why a human has to check it:
here the two independently-authored fields agree in meaning, and I checked that
by reading both declarations rather than assuming it from the names.

Substantively, `govsim_survival_months` is also the adapter's own headline
quantity per `docs/govsim_adapter_status.md` and the family docstring in
`measurement.py`: how long the commons survives is the one number the other four
leaves qualify (whether it collapsed *cleanly* per the rules, how much was
harvested along the way, how equally). It is not "the one that was easiest to
compute" (spec section 3's forbidden reasoning) — `govsim_no_collapse` is in fact
the simplest of the five (a single boolean flag read off `round_trace`) and is
explicitly not proposed as primary.

## Admission: `govsim_survival_months_leaf` alone

Matches the family's own pre-existing, already-committed classification in
`measurement.py`'s module docstring (not invented for this migration):

- The two rule/constraint leaves (`govsim_no_collapse`, `govsim_threshold_adherence`)
  are diagnostics per `docs/verifier_taxonomy.md` section 4 — "a hard gate ...
  should not silently convert a normative tradeoff into invalidity" — harvesting
  in a commons dilemma is a genuine tradeoff, not a violation to gate admission on.
- `govsim_total_harvest` and `govsim_equality_gini` are comparative diagnostics
  against an AERead-authored baseline policy (`govsim_sustainable_v1`), not a
  certified bound (`docs/problem_bound_case_audit.md` row P06), so they report
  but do not gate.

So `admission_leaf_ids = (govsim_survival_months_leaf,)`, and the primary is
(trivially) inside admission, satisfying `MeasurementDeclaration.__post_init__`.

## Deferred leaves: none

All five leaves are `scope="finalize_time"`. None depends on a judge verdict or
external rater protocol that might not exist at finalization — every scorer in
`measurement.py` is closed-form arithmetic over replayed state
(`round_trace`, `terminal["num_round"]`, `terminal["resource_in_pool"]`,
`terminal["collected_resource"]`) or the vendored `gini()`. There is no artifact
for a `deferred_artifact` field to name.

## Paired-history pair: constructible — yes

`GovsimPlugin.outcome()` (`environment.py`) returns only
`termination_reason, outcome_status, num_round, resource_in_pool,
collected_resource, [operational_failure]` — final aggregates, never
`round_trace`. `round_trace` (the per-round history the two `trajectory`-scoped
leaves read) lives only on `terminal()`, which `FamilyScoringInput.phase_instances`
reconstructs but `outcome` does not carry. This is the R9/R10 preconditions text's
own worked case: "govsim ... had a constructible paired-history pair because its
outcome carries only final aggregates" — confirmed directly against this base's
`outcome()`, not assumed from that text.

Concretely buildable the same way the reference migration did it (verified
against the real bridge there, not merely asserted): two bridge-backed episodes
whose per-round *aggregate* demand is identical (so the shared pool/regeneration
trajectory, and therefore `num_round`/`resource_in_pool`/summed
`collected_resource`, land byte-identical) but whose per-agent *split* of that
demand is swapped between two personas each round — same terminal outcome, a
genuinely different `round_trace` per agent-round. This exercises both
trajectory leaves for real rather than degenerately (their per-agent-round
predicates would actually see different values across the pair), and gives the
mislabelling contrapositive (R7) a non-trivial pair to check the three
terminal-scoped leaves against.

## Ledger item this migration resolves

`docs/govsim_adapter_status.md`'s known-limit entry (ledger **D-16**,
`runner_defect_ledger.md`): `GovsimScorer.__call__` today surfaces only
`govsim_survival_months` through the finalizer seam and silently drops the other
four leaves. `FamilyScoringInput`/`FamilyScoreSet` is the kernel-level resolution
D-16 was waiting on; this migration's `__call__` returns the full five-leaf
`FamilyScoreSet` via the existing `score_all` and closes that entry.

## Rulings that do not apply here

R9/R10 (trajectory embedded in outcome): not applicable — confirmed above,
`outcome()` carries no trajectory-bearing field, so no
`trajectory_outcome_paths` declaration is needed and none exists on this base to
declare it with.
