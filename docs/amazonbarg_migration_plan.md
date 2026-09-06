# amazonbarg migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, commits `04aa901a..46a32b1c`, especially
`docs/govsim_migration_plan.md`), read in full before writing this plan, plus the
collusion migration (`.../AERead/.worktrees/collusion-migrate`) for the rulings
R9/R10 shape, which does not apply here (see below).

## Preconditions confirmed on this base (`origin/main` via `git fetch`)

- Branch `zeyu/amazonbarg-contract-migration` is exactly at `origin/main`
  (`git rev-parse HEAD` == `git rev-parse origin/main`, both `e848c455`).
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` (plus `FinalizeTimeLeafPolicy`, `MeasurementDeclaration`
  with `leaves`/`primary_leaf_id`/`admission_leaf_ids`) exists in
  `src/aeread/shared_runner/schemas.py`.
- `('amazonbarg.bilateral', '0.1.0', 'amazonbarg_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:70`), and
  `("amazonbarg.bilateral", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1072`). `environment.py`'s
  `register_plugin` already calls `registry.register_trusted(...)`, so this family
  is not exposed to the rebase-breaks-registration trap the worked example
  describes (trap 1) — it was already carried this way before this branch forked.
- `trajectory_outcome_paths` (rulings R9/R10, round 3) does not exist anywhere in
  `schemas.py`/`measurement.py` on this base (`grep -c` is `0`). Per the task
  framing this is only a blocker if amazonbarg's `outcome()` embeds its
  trajectory. It does not (confirmed below), so R9/R10 do not apply to this
  family and this absence is not a blocker. **Not a STOP condition.**
- Family test suite, bridge exported
  (`AEREAD_AMAZONBARG_UPSTREAM_ROOT="/Users/sunzeyu/Documents/econ benchmark/upstream-amazonbarg"`):
  `tests/test_amazonbarg_cases.py`, `test_amazonbarg_environment.py`,
  `test_amazonbarg_harness.py`, `test_amazonbarg_measurement.py`,
  `test_amazonbarg_replay.py`, `test_amazonbarg_shim.py`,
  `test_amazonbarg_upstream_skip_scope.py` — **117 passed, 0 failed, 0 skipped**
  in 7.92s. This is the green baseline this migration must not regress.

## Today's declared leaves and their `input_scope`

All five leaves are declared unconditionally for every case
(`measurement.py::build_leaves` takes `family_case` but ignores it); only the
scored *values* vary by scenario.

| Leaf id | Estimand id | `input_scope` | Verifier family | Evaluation class |
|---|---|---|---|---|
| `amazonbarg_deal_authenticity_leaf` | `amazonbarg_deal_authenticity` | `terminal_state` | `rule_constraint` | `deterministic` |
| `amazonbarg_zopa_membership_leaf` | `amazonbarg_zopa_membership` | `terminal_state` | `rule_constraint` | `deterministic` |
| `amazonbarg_deal_lower_bound_leaf` | `amazonbarg_deal_lower_bound` | `terminal_state` | `objective_reference` | `deterministic` |
| `amazonbarg_deal_upper_bound_leaf` | `amazonbarg_deal_upper_bound` | `terminal_state` | `objective_reference` | `deterministic` |
| `amazonbarg_bargained_ratio_leaf` | `amazonbarg_bargained_ratio` | `terminal_state` | `comparative` | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every scorer
is deterministic arithmetic, delegated to upstream's pinned `eval.py:Metrics`
(never reimplemented — adapter rule 2), over one episode's own recorded
transcript (`build_metrics_line(..., history=...)`).

**Flag for the implementation milestone (not resolved here — no code changes in
Milestone 0):** all five scorers need `metrics_output = compute_upstream_metrics(
history=..., ...)`, i.e. the full turn-by-turn `history` list. `outcome()`
(`environment.py`) deliberately does not carry `history` — it returns only
`{termination_reason, terminating_actor, turns_completed, message_count}` — while
`terminal()` does. Under the new contract, "terminal-only scorers read
`scoring_input.outcome` explicitly" (spec section 1); none of these five leaves
can compute anything from `outcome` alone as declared. This mirrors govsim's
`govsim_no_collapse_leaf`/`govsim_threshold_adherence_leaf`, which read
`round_trace` (also stripped from `outcome()`, present only via `terminal()`/
`phase_instances`) and are therefore correctly declared `input_scope="trajectory"`,
not `"terminal_state"`. Two consistent implementation paths exist and neither is
chosen here:

- **(A) Relabel all five leaves' `EstimandSpec.input_scope` from `terminal_state`
  to `trajectory`**, and have `__call__` reconstruct `history` from
  `scoring_input.phase_instances` (walk `buyer_turn`/`seller_turn` instances in
  `ordinal` order, rebuilding the `[buyer_record]` / `[buyer_record,
  seller_record]` pairs `step()` already assembles). No change to `outcome()`.
  Mirrors govsim's precedent exactly; R9/R10 stay inapplicable.
- **(B) Embed `history` into `outcome()`** (mirroring collusion's shape),
  declare `trajectory_outcome_paths=("/history",)` per R9, and keep the leaves
  labelled `terminal_state`. This invokes R9/R10's projection-based
  paired-history check instead of the whole-outcome one.

Path (A) is the smaller, more reversible change and matches the one precedent
this project already has for this exact situation (govsim), so it is the
recommended default — but it is a leaf-declaration correction to be made (and
justified) in the implementation milestone, not a decision this plan finalizes.

## Reference-source classification

| Leaf | Reference source | Reasoning |
|---|---|---|
| `amazonbarg_deal_authenticity` | replayed-episode | Upstream's `wrongAction` verdict is computed by `eval.py:Metrics` from this episode's own recorded transcript alone. Not derivable from `family_case` (no deal has been proposed yet at case-validation time); not another episode's output; not a rater verdict. |
| `amazonbarg_zopa_membership` | replayed-episode | Needs the realized deal price `D`, delegated from `Metrics` over this episode's own transcript, compared against `family_case.derived.cost`/`.budget` (closed-form). The closed-form half alone cannot produce a claim — no deal, no `D`, no membership verdict — so the leaf as a whole is replayed-episode, not closed-form. |
| `amazonbarg_deal_lower_bound` | replayed-episode | Same shape as zopa_membership: `primary` is the realized deal price `D` (replayed-episode); the single bound in `reference_values` is closed-form (`derived.cost`). |
| `amazonbarg_deal_upper_bound` | replayed-episode | Same shape, bound is `derived.budget` (closed-form); primary is `D` (replayed-episode). |
| `amazonbarg_bargained_ratio` | replayed-episode | Needs `buyer_bargained_ratio`/`seller_bargained_ratio` from `Metrics`, computed over the same episode's transcript. The "fixed scripted counterpart" is the OTHER seat in the SAME episode, not a separately-run baseline episode: the manifest declares both `buyer` and `seller` as `"testable": true` with `"scripted_policies": ["scripted"]`, and `ScriptedAmazonbargHarness` serves both seats' turns inside one script driven through one `run_episode` call. There is no join against another episode's artifact, so this is replayed-episode, not separate-run-artifact, despite the `comparative`/`head_to_head` verifier family and reference_kind. |

No leaf's estimand, by definition, needs an artifact from a DIFFERENT episode
(a separately-run baseline policy) or a judge/rater verdict. All five are
**replayed-episode**, hence all five are **finalize_time** per the rule in
section 4 of the spec (closed-form and replayed-episode → finalize_time;
separate-run and judge → deferred).

## Proposed primary: `amazonbarg_bargained_ratio_leaf`

`family_manifest()` (`environment.py`) already declares
`measurement.primary_estimand = "amazonbarg_bargained_ratio"`. That estimand id
is exactly `BARGAINED_RATIO_ESTIMAND_ID`, the estimand of
`amazonbarg_bargained_ratio_leaf` — the leaf proposed as primary is the one the
manifest's existing family-level field already names, not a same-named
coincidence chosen for convenience. Per ruling R8 the kernel does not enforce
this correspondence mechanically; I checked it by reading both declarations.

Substantively, the manifest's own comment calls this "the one comparative leaf
closest to a headline claim" and records `measurement_kind:
"comparative_or_human_judged"`, `direction: "maximize"`, `outcome_support:
"ratio"` — all of which match `amazonbarg_bargained_ratio_leaf`'s own
`direction="maximize"`/`units="ratio"` exactly (the two bound leaves also claim
`direction="maximize"` but only as a documented structural placeholder — see
`measurement.py`'s module docstring — never a normative claim, so they are not
candidates). It is also not "the one that was easiest to compute" (the spec's
forbidden reasoning): `amazonbarg_deal_authenticity` is in fact the simplest of
the five (a single upstream boolean) and is not proposed as primary.

## Admission: `amazonbarg_bargained_ratio_leaf` alone

`amazonbarg_zopa_membership`, `amazonbarg_deal_lower_bound`,
`amazonbarg_deal_upper_bound`, and `amazonbarg_bargained_ratio` all share the
exact same validity gate (`_measurement_gate`, called identically by
`score_zopa_membership`, `_score_bound`, and `score_bargained_ratio`): they turn
`invalid_measurement` together, for the same reasons, whenever there is no
recorded evidence, upstream flags `wrongAction=1`, the case has no ZOPA, or no
deal closed. Because these four leaves' validity always co-varies, naming any of
the other three as an additional admission leaf would exclude a receipt in
exactly the same cases the primary already excludes it in — no extra
discriminating power. `amazonbarg_deal_authenticity` is even weaker: it is
`invalid_measurement` only in the zero-recorded-turns case (`REASON_NO_EVIDENCE`),
which is already the *first* check inside `_measurement_gate` and therefore
already implies `amazonbarg_bargained_ratio` is also invalid there. So gating
admission on it adds nothing either.

`admission_leaf_ids = (amazonbarg_bargained_ratio_leaf,)`, and the primary is
(trivially) inside admission, satisfying `MeasurementDeclaration.__post_init__`.
The other four leaves are receipted as diagnostics (never dropped from the
returned `FamilyScoreSet` — spec section 3's "declared leaf set" rule — just not
admission-gating).

## Deferred leaves: none

All five leaves are `scope="finalize_time"` (see the reference-source table
above). None depends on a judge verdict or an external rater protocol, and none
depends on a separately-run baseline episode. There is no artifact for a
`deferred_artifact` field to name.

## Reference gap: none

The manifest's `primary_estimand` (`amazonbarg_bargained_ratio`) and the one
admission leaf both resolve to `amazonbarg_bargained_ratio_leaf`, which is
replayed-episode, not separate-run-artifact or judge-artifact, by its own
estimand definition (the "fixed scripted counterpart" is the other seat inside
the same episode, not a joined artifact from elsewhere — see the classification
table). An honest finalize_time primary exists today; no estimand split
(`X_own` finalize_time / `X_vs_baseline` deferred) is needed, and none is
proposed.

## Paired-history pair: constructible — yes

`AmazonbargPlugin.outcome()` (`environment.py`) returns only
`termination_reason, terminating_actor, turns_completed, message_count` — final
aggregates, never `history`. `history` (the per-round transcript the five
leaves' delegated `Metrics` calls need) lives only on `terminal()`, which
`FamilyScoringInput.phase_instances` reconstructs but `outcome` does not carry.
This is the R9/R10 preconditions text's own worked case for a family whose
outcome carries only final aggregates (mirrors govsim, not collusion/
datacenter_development, whose `outcome()` embeds `history`/`public_history`
directly) — confirmed directly against this base's `outcome()`, not assumed.

Concretely buildable the same way: two bridge-backed episodes that reach the
same `termination_reason`/`terminating_actor`/`turns_completed`/`message_count`
but whose actual buyer/seller dialogue — and therefore realized deal price,
`wrongAction` verdict, and bargained ratios — differ. Two of the five QC Gate-2
goldens already land on the same shape: golden 1 (`home-kitchen_2`) and golden 3
(`home-kitchen_5`), per `tests/test_amazonbarg_harness.py`, both terminate
`reason="deal"`, `terminating_actor="seller"`, after 4 served decisions/messages
— but golden 1 deals at `$135` on a different product than golden 3's `$480`
deal, so the underlying `history`, deal price, and (for golden 3, an
authenticated below-cost deal per `docs/amazonbarg_adapter_status.md`) the
zopa/bound/ratio leaves' scored values differ while `turns_completed`/
`message_count` match. This pair is a candidate to source the paired-history
fixture; the exact fixture (confirming `outcome()`'s four fields truly land
byte-identical, not just the two fields checked by the existing harness test)
is the implementation milestone's job, not this plan's.

## Rulings that do not apply here

R9/R10 (trajectory embedded in outcome): not applicable — confirmed above,
`outcome()` carries no trajectory-bearing field, so no
`trajectory_outcome_paths` declaration is needed and none exists on this base
to declare it with.

## Open item carried into the implementation milestone

The `terminal_state` vs `trajectory` `input_scope` mismatch described above
(all five leaves declared `terminal_state` today but needing data `outcome()`
does not carry) is not resolved in this milestone. It does not change any
conclusion above (finalize_time/deferred classification, primary, admission,
and paired-history constructibility are all unaffected by which of paths A/B
is eventually chosen), but a reviewer should confirm the choice before
`__call__` is implemented.
