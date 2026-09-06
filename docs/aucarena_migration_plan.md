# aucarena migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, `git log --oneline zeyu/kernel-r9r10..HEAD`),
read in full before writing this plan, together with the second reference
(`.worktrees/collusion-migrate`) for the one shape govsim does not exercise
(a family whose primary leaf needs an artifact the current scorer cannot supply).

## Preconditions confirmed on this base

- `git fetch origin` ran clean; the worktree is on branch
  `zeyu/aucarena-contract-migration`, and `git merge-base --is-ancestor
  zeyu/kernel-r9r10 HEAD` succeeds -- this branch is built on top of
  `zeyu/kernel-r9r10` as expected.
- `FamilyScoringInput` exists at `src/aeread/shared_runner/task/evaluation.py:465`
  (plus `replay_family_scoring_input` at line 496); `LeafPolicyDeclaration`
  (plus `FinalizeTimeLeafPolicy`, `MeasurementDeclaration` with
  `leaves`/`primary_leaf_id`/`admission_leaf_ids`) exists in
  `src/aeread/shared_runner/schemas.py:341-459`.
- `('aucarena', '0.1.0', 'aucarena_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:71`), and
  `("aucarena", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1650-1670`).
  `environment.py`'s `register_plugin` already calls
  `registry.register_trusted(manifest, plugin)`, so this family is not exposed
  to the rebase-breaks-registration trap the worked example describes (trap 1)
  -- it was already carried this way before this branch forked.
- `trajectory_outcome_paths` (rulings R9/R10, round 3) exists on this base:
  `grep -c trajectory_outcome_paths src/aeread/shared_runner/schemas.py` → `11`
  (nonzero). Not a blocker either way -- see the constructibility finding
  below, which concludes this family does not need to use it.
- Family test suite, bridge exported
  (`AEREAD_AUCARENA_UPSTREAM_ROOT=/Users/sunzeyu/Documents/econ benchmark/upstream-aucarena`):
  `tests/test_aucarena_cases.py`, `test_aucarena_environment.py`,
  `test_aucarena_measurement.py`, `test_aucarena_parity.py`,
  `test_aucarena_qc_gate_visibility.py`, `test_aucarena_replay.py`,
  `test_aucarena_vendored_upstream.py` -- **109 passed, 0 failed, 0 skipped**
  in 2.34s. This is the green baseline this migration must not regress.

## Does `outcome()` embed the trajectory? (rulings R9/R10 precondition)

`AucArenaPlugin.outcome()` (`environment.py`, "Terminal / outcome" section)
returns exactly:

```python
{
    "termination_reason": terminal["reason"],
    "items": [dict(entry) for entry in terminal["sold_log"]],   # one entry PER ITEM
    "seats": {seat_id: {"profit", "budget", "items_won", "model_name"} for each seat},
}
```

`sold_log` has one entry per **item** (`{item_id, sold, winner, hammer_price}`) --
the item's final disposition, not a per-round bid log. There is no field
anywhere in `outcome()` recording individual bid amounts, bid rounds, parse
results, legality determinations, or tie-break draws -- exactly the data the
three trajectory-scoped leaves below actually read, and exactly the data
`collusion`'s `history` / `datacenter_development`'s `public_history` embed
verbatim (the R9/R10 preamble's own motivating cases). This is `govsim`'s
shape ("outcome carries only final aggregates"), not `collusion`'s.

**Concretely constructible, not merely argued by shape.** Two trajectories can
land on the same final item disposition and the same final per-seat tallies by
a different bidding path -- e.g. a single-item, two-seat case where trajectory
A takes several rounds of escalating bids ending at hammer price `P` won by
seat `X`, and trajectory B reaches the identical winner `X` and identical
hammer price `P` in a different number of rounds (a seat jumping straight to
`P` in round 0 instead of via intermediate rounds is still legal:
`bid_sanity_check` only requires the new bid clear `highest_bid +
min_markup_pct * price`, not a fixed increment, so nothing forces a unique
path to a given hammer price). Same `sold_log` entry, same seat
profit/budget/items_won, different `phase_instances` (different round counts,
different recorded actions) -- exactly the pair the protocol test's
paired-history assertion (`kernel_scoring_contract_spec.md` section 6) needs
to build for this family's three `trajectory` leaves.

**Conclusion: `outcome()` does not embed the trajectory. The whole-outcome
paired-history pair is constructible. Rulings R9/R10 (`trajectory_outcome_paths`)
do not apply to this family** -- consistent with `govsim`'s own Milestone-0
finding for the same reason, and distinct from `collusion`'s, whose `outcome()`
carries `history` verbatim and therefore needed the R9/R10 projection.

## Today's declared leaves and their `input_scope`

All four leaves are declared unconditionally for every case
(`measurement.py::build_leaves`); only the scored *values* (and, for leaf 4,
the `status`) vary by scenario.

| Leaf id | Estimand id | `input_scope` | Verifier family | Reference kind | Evaluation class |
|---|---|---|---|---|---|
| `aucarena_budget_invariant_leaf` | `aucarena_budget_invariant` | `trajectory` | `rule_constraint` | `state_invariant` | `deterministic` |
| `aucarena_bid_legality_leaf` | `aucarena_bid_legality` | `trajectory` | `rule_constraint` | `constraint_satisfaction` | `deterministic` |
| `aucarena_hammer_rule_leaf` | `aucarena_hammer_rule` | `trajectory` | `rule_constraint` | `temporal_property` | `deterministic` |
| `aucarena_profit_vs_field_leaf` | `aucarena_profit_vs_field` | `terminal_state` | `comparative` | `head_to_head` | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every
scorer is deterministic arithmetic or a vendored-rule replay over recorded
state (`measurement.py`'s own module docstring: "provider-free and
judge-free... all four are `deterministic`").

## Reference-source classification

The rule from this milestone's brief: closed-form-from-case and
replayed-episode leaves are `finalize_time`; separate-run and judge leaves are
`deferred`.

| Leaf | Classification | Why |
|---|---|---|
| `aucarena_budget_invariant` | replayed-episode | Reads every recorded `TransitionResult.state` in this same episode's `phase_instances` (`score_budget_invariant`: `for phase_instance in result.phase_instances: for transition in phase_instance.transitions: ...`). Depends on the realized bidding trajectory, not derivable from `family_case` alone. |
| `aucarena_bid_legality` | replayed-episode | Recomputes `bid_sanity_check` from each recorded action's own frozen pre-round observation (`_all_action_records(result.phase_instances)`), independent of `environment.py`'s own recorded legality verdict but still sourced from this episode's own recorded actions. |
| `aucarena_hammer_rule` | replayed-episode | Independently replays `record_bid`/`check_hammer` from `PhaseInstance.actions` and `result.final_state["world_seed"]`/`["enable_discount"]`, both of which are static fields copied unchanged into every recorded transition's `state` and therefore reachable from `phase_instances` alone (no `EpisodeResult.final_state` needed at the interface). |
| `aucarena_profit_vs_field` | replayed-episode | `score_profit_vs_field` reads `result.outcome["seats"]` for **both** the tested seat and every field seat. The field seats are other seats on the *same* `family_case["roster"]`, playing in the *same* auction episode (`build_scorer`: `field_seats = tuple(seat for seat in family_case["roster"] if seat["seat_id"] != tested_seat_id)`) -- this is not a second, separately-run episode or a baseline policy run under the same condition; it is this episode's own terminal outcome. Unlike `collusion`'s `collusion_long_run_profit` (which needs a counterfactual Nash-play rerun against the *same opponent policy function*, an artifact no `FamilyScoringInput` can supply), aucarena's comparator is already fully inside this episode's `outcome`. |

No leaf in this family is closed-form-from-case (all four depend on how the
episode actually played out, not on `family_case` alone), separate-run-artifact,
or judge-artifact. **All four leaves are `scope="finalize_time"`.**

## Proposed primary: `aucarena_profit_vs_field_leaf`

`family_manifest()` (`environment.py`) already declares
`measurement.primary_estimand = "aucarena_profit_vs_field"`. That estimand id
is exactly `PROFIT_VS_FIELD_ESTIMAND_ID`, the estimand of
`aucarena_profit_vs_field_leaf` -- the leaf proposed as primary is the one the
manifest's existing family-level field already names, not a same-named
coincidence chosen for convenience. Per ruling R8 the kernel does not enforce
this correspondence mechanically, which is exactly why a human has to check
it: here the two independently-authored fields agree in meaning, checked by
reading both declarations rather than assumed from the names.

Substantively this also matches the adapter's own stated design (spec section
2, restated in `measurement.py`'s module docstring and
`docs/aucarena_adapter_status.md`): no `objective_reference` leaf is declared
at all because profit/TrueSkill do not solve the auction policy game (P21 row,
`verifier_taxonomy.md` section 13); "the estimand of primary interest is the
comparative one" is the manifest's own comment on this exact field. The three
`rule_constraint` leaves are integrity/parity checks on the environment's own
rule application (`docs/aucarena_adapter_status.md`: "the component parity
check the spec's test plan calls for"), not competing candidates for headline
result -- and none of them is "the one that was easiest to compute" chosen for
convenience (spec section 3's forbidden reasoning); they are declared for a
different reason (protocol conformance), not proposed as primary.

## Admission: `aucarena_profit_vs_field_leaf` alone

- The three `rule_constraint` leaves never produce `invalid_measurement` in
  their current scorers: each always returns `status="ok"` (a violation is
  recorded as a `0.0`-valued metric under an otherwise-valid envelope, e.g.
  `score_budget_invariant`'s `primary=MetricValue(0.0 if violations else 1.0,
  "pass")`); a genuine disagreement between the environment's own recorded
  state/legality/consequences and this module's independent recompute is
  treated as an adapter defect and raises `AucArenaMeasurementError` directly
  (module docstring: "not an ordinary scoring outcome"), which aborts
  finalization before admission gating is ever reached. There is no
  `invalid_measurement` path on these three leaves to gate on.
- `aucarena_profit_vs_field` is the only leaf whose estimand definition
  requires something that is not always present (a non-empty field, golden 5)
  and therefore the only one with a real `invalid_measurement` path
  (`score_profit_vs_field`'s empty-`field_seats` branch) -- the leaf whose
  exclusion behavior actually matters is the one gating admission.

So `admission_leaf_ids = (aucarena_profit_vs_field_leaf,)`, and the primary is
(trivially) inside admission, satisfying `MeasurementDeclaration`'s invariant.
This mirrors `govsim`'s own admission choice (primary alone; its two
`rule_constraint` diagnostics are declared but do not gate) for the same
underlying reason: a rule/protocol-conformance check is a diagnostic here, not
a normative admission gate.

## Deferred leaves: none

All four leaves are `scope="finalize_time"`, per the reference-source table
above. None depends on a judge verdict or an external/separate-run artifact.
There is no `deferred_artifact` to name.

## Reference gap: none

Unlike `collusion`'s `collusion_long_run_profit` (which, by its own spec's
estimand definition, needs a *separate* counterfactual episode -- one seat
forced to Nash-play against the same opponent policy function -- an artifact
no `FamilyScoringInput` can supply), `aucarena_profit_vs_field`'s comparator
(the frozen rule-bidder field) is, by its own estimand definition
(`docs/aucarena_adapter_spec.md` section 2: "the comparator and pairing are
part of the estimand"), a set of seats that play in the *same* episode as the
tested seat. The primary is fully computable today from
`FamilyScoringInput.outcome` alone, with no separate-run or judge artifact
required by the estimand's own definition. No estimand-design change is
needed for this migration, and none is proposed.

## Paired-history pair: constructible -- yes

See "Does `outcome()` embed the trajectory?" above. `outcome()` carries no
trajectory-bearing field (only per-item final dispositions and per-seat final
tallies), so the whole-outcome pair -- byte-identical `outcome`, differing
`phase_instances` -- is constructible without any `trajectory_outcome_paths`
projection, the same shape as `govsim` and unlike `collusion`/
`datacenter_development`.

## Rulings that do not apply here

R9/R10 (trajectory embedded in outcome): not applicable -- confirmed above,
`outcome()` carries no trajectory-bearing field, so no
`trajectory_outcome_paths` declaration is needed for this family.
