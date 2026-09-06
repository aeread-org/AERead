# steer migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, commits `origin/main..HEAD`), read in full
before writing this plan; the collusion worktree
(`.../AERead/.worktrees/collusion-migrate`) was also read for the R9/R10
trajectory-embedding shape, which this family turns out not to need.

## Preconditions confirmed on this base (origin/main via `git fetch`)

- Branch `zeyu/steer-contract-migration` is exactly at `origin/main`
  (`git merge-base --is-ancestor origin/main HEAD` succeeds; `HEAD` and
  `origin/main` are the same commit).
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` (plus `FinalizeTimeLeafPolicy`, `MeasurementDeclaration`
  with `leaves`/`primary_leaf_id`/`admission_leaf_ids` and
  `finalize_time_leaf_policy()`) exists in `src/aeread/shared_runner/schemas.py`.
- `('steer', '0.1.0', 'steer_environment')` is in `TRUSTED_BUILTIN_PLUGIN_KEYS`
  (`src/aeread/shared_runner/registry.py:77`), and `("steer", "0.1.0")` is in
  `_NOT_YET_MIGRATED_TRUSTED_KEYS` (`tests/test_shared_runner_scoring_contract.py:1079`).
  `environment.py`'s `register_plugin` already calls `registry.register_trusted(...)`
  (`environment.py:145`), so this family is not exposed to the rebase-breaks-registration
  trap the worked example describes (trap 1) — it was already carried this way before
  this branch forked.
- `trajectory_outcome_paths` (rulings R9/R10, round 3, 2026-09-05) does not exist
  anywhere in `schemas.py`/`measurement.py` on this base
  (`grep -c trajectory_outcome_paths src/aeread/shared_runner/schemas.py` → `0`).
  Per this milestone's own instructions, that absence is only a blocker if this
  family's `outcome()` embeds its trajectory. It does not — see "Whole-outcome
  paired-history pair" below — so R9/R10 do not apply to this family and the
  STOP condition on a zero grep count is not triggered.
- Family test suite, bridge exported (`AEREAD_STEER_DATA_ROOT`,
  `AEREAD_STEER_UPSTREAM_ROOT`, `AEREAD_STEER_BRIDGE_PYTHON`), no
  `AEREAD_STEER_FIXTURES_REQUIRED` (this is the baseline check, not a certifying
  run): `tests/test_steer_measurement.py`, `test_steer_goldens.py`,
  `test_steer_replay.py`, `test_steer_cases.py`, `test_steer_e2e.py`,
  `test_steer_environment.py`, `test_steer_fixtures_required.py` —
  **154 passed, 0 failed, 0 skipped**, in 23.28s. This is the green baseline this
  migration must not regress.

## Does `outcome()` embed the trajectory?

No. `SteerPlugin.outcome()` (`environment.py:356-364`) returns exactly:

```python
{
    "termination_reason": terminal["reason"],
    "selected_option_id": terminal["selected_option_id"],
    "failure_code": terminal["failure_code"],
}
```

— a single terminal decision, never a history. The family's own module docstring
(`environment.py:1-9`) states the shape directly: "Mode A ... a single agent, one
phase, one logical action. There is no environment to mutate, no tool loop, and no
counterpart seat." `family_manifest().environment.phase_specs` declares exactly one
phase (`PHASE_ID = "answer_question"`). There is no `history`/`round_trace`/
`public_history`-shaped field anywhere in `outcome()` or the case payload for a
leaf to embed — unlike collusion's `{termination_reason, rounds_played, history}`
or `datacenter_development`'s baked-in `public_history`, which is exactly the shape
R9/R10 exist to handle.

## Today's declared leaf and its `input_scope`

One leaf, declared unconditionally for every one of the 8 pilot elements
(`measurement.py::build_answer_key_leaf`); only the scored *value* varies by case.

| Leaf id | Estimand id | `input_scope` | Verifier family | Evaluation class |
|---|---|---|---|---|
| `steer_answer_key` | `steer_answer_key` | `answer` | `canonical_reference` | `deterministic` |

`measurement.py`'s module docstring states this explicitly: "There is no second,
judge-dependent leaf: STEER's MCQA answer key is a deterministic equality check end
to end" — the pinned upstream commit itself deleted its own evaluation submodule
("Remove STEER evaluation submodule"), so there is no upstream scorer to delegate to
or achieve parity against, unlike `tau3_retail`.

## Reference-source classification

The leaf's scorer (`score_answer_key`, called via `SteerScorer.__call__` →
`SteerScorer.score`) needs exactly two values to produce a valid (`status="ok"`)
result, and both are available at finalize time:

| Value | Reference source | Where it actually comes from |
|---|---|---|
| `correct_option_id` (gold answer) | **closed-form-from-case** | Recovered by `SteerPlugin.build_scorer`/`_load_cached_row` from the cached, flattened corpus row keyed by `family_case["element"]`/`family_case["question_id"]`, and validated by recomputing `source_sha256` from the row's own fields (`_recomputed_source_sha256`) against `family_case["source_sha256"]` — derived from the validated `family_case` alone, never from an episode. |
| `selected_option_id`, `failure_code` (the submission and its legality) | **replayed-episode** | `scoring_input.outcome`, produced by `finalize_family_execution`'s verified deterministic re-execution (`replay_family_scoring_input` / `_replay_family_trajectory`) of *this* episode — never the live `EpisodeResult`, per ruling R2. |

No value the leaf needs comes from a **separate-run-artifact** (another episode's
run, e.g. a baseline policy under the same case) or a **judge-artifact** (a rater or
judge verdict sealed separately). This matches `measurement.py`'s own claim that
there is no second, judge-dependent component to label.

## Proposed primary: `steer_answer_key`

It is the only leaf this family declares, so there is exactly one candidate —
this is not "the one that was easiest to compute" chosen among alternatives
(spec section 5's forbidden reasoning); there are no alternatives. The
correspondence to the manifest is checked directly, not assumed from the id
matching by coincidence: `family_manifest()`'s
`measurement.primary_estimand = "steer_answer_key"` (`environment.py`) is exactly
`ANSWER_KEY_ESTIMAND_ID` (`measurement.py`), the estimand id of this same leaf —
and it agrees in meaning, not just spelling: the manifest's headline quantity
*is* "does the submitted answer match the gold answer key", and that is exactly
and only what `steer_answer_key` measures.

## Admission: `steer_answer_key` alone

Forced, not chosen: `MeasurementDeclaration.__post_init__` requires
`admission_leaf_ids` to include the primary, and with only one declared
`finalize_time` leaf, `admission_leaf_ids` defaults to `(primary_leaf_id,)`
(`schemas.py:440`) when left unset. There is no second, diagnostic leaf to
separately include or exclude from admission.

## Deferred leaves: none

The one leaf is `scope="finalize_time"` (`_LEAF_SCOPES = {"finalize_time",
"deferred"}`, `schemas.py:277`). Nothing about `steer_answer_key`'s own estimand —
"does the submitted `option_id` equal the gold `correct_option_id`" — depends on
an artifact that might not exist yet at finalization (a judge verdict, an external
rater protocol, another episode's run). Both values it needs (see the
reference-source table above) are available the moment this episode's evidence is
sealed. There is no `deferred_artifact` for a `deferred` leaf to name here, because
there is no deferred leaf.

## Reference gap: none

The primary (and only) leaf's estimand does not, by its own definition, require a
separate-run or judge artifact: it is a closed-form equality check against a gold
answer pinned in the case, scored against this episode's own terminal submission.
STEER's upstream evaluation submodule was deleted at the pinned commit, so there is
no upstream parity target to defer to either — the gold answer is recovered from
upstream's own `Answers` frame, already flattened into the cached row, not from a
live upstream scorer. No estimand split (an `X_own` finalize_time leaf plus an
`X_vs_baseline` deferred leaf, the shape ruling text elsewhere anticipates for
comparative families) is implied here, because there is no comparative or
judge-dependent component to split off in the first place.

## Whole-outcome paired-history pair: constructible — yes, and not exercised

Constructible in the same sense the milestone-0 instructions describe for
govsim: `outcome()` carries only a final decision, never a trajectory (see "Does
`outcome()` embed the trajectory?" above), so two episodes with identical
terminal decisions and different question/case content would still need
identical `outcome()` shape — the field set never varies, so the *shape*
half of the pairing is trivially satisfiable. Concretely, any two of the 8
declared elements' successful-golden episodes are already such a pair: two
byte-identical-shaped `outcome()` mappings (only the *values* inside
`selected_option_id`/`termination_reason`/`failure_code` differ per case), with
no `history`/`round_trace` field to differ or agree on at all.

This differs from govsim's actual need, though: govsim has two `trajectory`-scoped
leaves, so its pair must be built and exercised by the protocol test's
`if declared.trajectory_leaf_ids:` branch (spec section 6). `steer_answer_key`
is declared `input_scope="answer"`, not `"trajectory"` — this family has no
trajectory-scoped leaf at all, so `declared.trajectory_leaf_ids` will be empty for
it and that branch is never entered. The pair is recorded here because this
milestone asks for the determination directly (and because it resolves the
`trajectory_outcome_paths` STOP condition above), not because a later milestone
needs to actually build and ship such a fixture pair for this family.

## Rulings that do not apply here

- **R9/R10** (trajectory embedded in outcome): not applicable — confirmed above,
  `outcome()` carries no trajectory-bearing field, so no `trajectory_outcome_paths`
  declaration is needed and none exists on this base to declare it with.
- **R7**'s mislabelling contrapositive (every `terminal_state`-declared leaf must
  score identically across a paired-history pair): not applicable either — the one
  leaf is declared `input_scope="answer"`, not `"terminal_state"` or `"trajectory"`,
  so it is outside the scope R7 checks. (Spec section 7 independently names steer,
  alongside econevals and amazonbarg, as one of "the three terminal-only families"
  whose migration is deliberately deferred until after the eleven-family kernel
  work, precisely because its change is expected to be small.)
- **R8** (no forced correspondence to `primary_estimand`): satisfied trivially and
  checked by inspection, not assumed — see "Proposed primary" above.

## Ledger / prior-decision note

`docs/steer_adapter_status.md` already documents the single-leaf, no-judge design
("There is no second, judge-dependent leaf...") as a pre-existing, already-reviewed
decision from the adapter build itself. Nothing in this plan is a new design
decision; it restates that existing design against the new contract's vocabulary
(finalize_time/deferred scope, closed-form/replayed-episode/separate-run/judge
reference sources) so a reviewer can check the restatement rather than re-deriving
the design from scratch.
