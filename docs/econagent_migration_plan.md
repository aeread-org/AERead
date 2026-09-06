# econagent_v1 migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, `git log --oneline origin/main..HEAD`,
commit `35e59b0e` "feat(govsim): migrate to the FamilyScoringInput scoring
contract"), read in full before writing this plan.

## Preconditions confirmed on this base (`zeyu/kernel-r12-seat-context` via `git fetch`)

- Branch `zeyu/econagent-contract-migration` is exactly at
  `zeyu/kernel-r12-seat-context` (`git merge-base --is-ancestor` succeeds; the
  branch range `zeyu/kernel-r12-seat-context..HEAD` is currently empty).
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` (plus `FinalizeTimeLeafPolicy`, `MeasurementDeclaration`
  with `leaves`/`primary_leaf_id`/`admission_leaf_ids`) exists in
  `src/aeread/shared_runner/schemas.py`.
- `('econagent_v1', '0.1.0', 'econagent_v1_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:73`), and
  `("econagent_v1", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1903`).
  `environment.py::register_plugin` already calls
  `registry.register_trusted(manifest, plugin)`, so this family is not exposed
  to the rebase-breaks-registration trap the worked example describes (trap 1)
  — it was already carried this way before this branch forked.
- `trajectory_outcome_paths` (rulings R9/R10) exists in `schemas.py`
  (`grep -c` → 11). `seat_context` (ruling R12) exists in
  `task/evaluation.py` (`grep -c` → 30). Both preconditions are satisfied on
  this base; see the R9/R10 and R12 applicability sections below for why
  neither actually needs to be invoked for this family.
- Family test suite, bridge exported
  (`AEREAD_ECONAGENT_BRIDGE_PYTHON`, `AEREAD_ECONAGENT_UPSTREAM_ROOT`):
  `tests/test_econagent_bridge_required_enforcement.py`,
  `test_econagent_e2e.py`, `test_econagent_parity.py`,
  `test_econagent_environment.py`, `test_econagent_goldens.py`,
  `test_econagent_cases.py`, `test_econagent_measurement.py`,
  `test_econagent_replay.py` — **109 passed, 0 failed, 0 skipped**, in 216.00s.
  This is the green baseline this migration must not regress.

## Today's declared leaves and their `input_scope`

All three leaves are declared unconditionally for every case
(`measurement.py::build_leaves`); nothing about the leaf *set* is
case-dependent (unlike `tau3_retail`'s conditionally-absent second leaf).

| Leaf id | Estimand id | `input_scope` | Verifier family | Reference kind | Evaluation class |
|---|---|---|---|---|---|
| `econagent_budget_identity_leaf` | `econagent_budget_identity` | `trajectory` | `rule_constraint` | `state_invariant` | `deterministic` |
| `econagent_tax_bracket_arithmetic_leaf` | `econagent_tax_bracket_arithmetic` | `trajectory` | `rule_constraint` | `constraint_satisfaction` | `deterministic` |
| `econagent_macro_trajectory_leaf` | `econagent_macro_trajectory` | `trajectory` | `comparative` | `baseline_delta` (mode: descriptive/baseline-only) | `deterministic` |

All three are genuinely `trajectory`-scoped, not mislabelled: budget-identity
and tax-bracket-arithmetic are per-agent-**per-month** invariants checked
across every month of the episode, and macro-trajectory is by definition a
per-month time series. Unlike govsim (2 trajectory + 3 terminal_state), this
family has **zero `terminal_state` leaves** — every leaf reads across the
whole episode, none reads only the final aggregate. This means the protocol
test's R7 mislabelling-contrapositive check (which fires on `terminal_state`
leaves) has nothing to check for this family; all three leaves instead need
R9's "sensitivity witness" (each must be shown to differ on *some* fixture
pair) when the family is enrolled in milestone 2/3.

No leaf has a judge/rater/rubric field anywhere in `measurement.py`; every
scorer is deterministic arithmetic over replayed state, or a fresh, stateless
re-invocation of upstream's own bracket-tax code (never a reimplemented
formula, per this adapter's own rule 2).

## Reference-source classification

| Leaf | Reference source | Why |
|---|---|---|
| `econagent_budget_identity_leaf` | replayed-episode | Every term (`inventory_coin[t±1]`, `labor_income`, `tax_paid`, `lump_sum`, `consumption_spend`) is read from *this episode's own* `dense_log`/`month_actions`/`world_interest_rate_by_month` — all three live only on `terminal()` today, reconstructible from `scoring_input.phase_instances[-1].transitions[-1].state` (the cumulative state after the last month), the same pattern govsim's migrated `_round_trace_from_phase_instances` uses (`phase_instances[-1].transitions[-1].state`, `govsim/measurement.py:792`). No other episode, no judge. |
| `econagent_tax_bracket_arithmetic_leaf` | replayed-episode | The per-agent-per-month `income` figures it checks are read from this episode's own `dense_log["PeriodicTax"]` (via `phase_instances`, same as above). The bracket schedule itself is re-invoked live through a fresh, stateless `EconAgentBridge.recompute_tax` call — a closed-form, case-derived computation (deterministic given the pinned `config.yaml`/bracket schedule) used only as the verification *mechanism*, not a second episode or a judge verdict. |
| `econagent_macro_trajectory_leaf` | replayed-episode | GDP-proxy/price/unemployment series are read verbatim from this episode's own `dense_log`/`month_actions` (via `phase_instances`), with no comparator, no baseline episode, no optimum — the leaf is descriptive-only over this one episode's own trajectory. |

All three are **replayed-episode → `scope="finalize_time"`**. None needs a
separate-run artifact (a baseline-policy comparison episode) or a
judge/rater verdict *by its estimand definition*. `econagent_macro_trajectory`
looks superficially like it could invite a baseline comparison (it is
declared `verifier_family="comparative"`/`reference_kind="baseline_delta"`),
but the estimand itself, as authored, is explicitly `mode:
descriptive/baseline_only` with "no comparator, no optimum, no pass/fail
meaning" (`measurement.py`'s own module docstring, echoing
`docs/econagent_adapter_status.md`'s claim table) — it does not need a
baseline episode to produce an `ok` value today; it produces one from this
episode alone. There is therefore **no reference gap** for this family.

## Proposed primary: `econagent_budget_identity_leaf`

`family_manifest()` (`environment.py`) already declares
`measurement.primary_estimand = "econagent_budget_identity"`. That estimand id
is exactly `BUDGET_IDENTITY_ESTIMAND_ID`, the estimand of
`econagent_budget_identity_leaf` — the leaf I am proposing as primary is the
one the manifest's existing family-level field already names, not a
same-named coincidence chosen for convenience. Per ruling R8 the kernel does
not enforce this correspondence mechanically, which is exactly why a human has
to check it: here the two independently-authored fields agree in meaning, and
I checked that by reading both declarations rather than assuming it from the
names.

Substantively, `econagent_budget_identity` is also the adapter's own
foundational correctness claim: `measurement.py`'s module docstring and
`docs/econagent_adapter_status.md`'s claim table both open with it as "Leaf
1", the six-term accounting identity that every agent's inventory must satisfy
every month, sourced entirely from upstream's own executed state. It is not
"the one that was easiest to compute" (spec section 3's forbidden reasoning):
`econagent_tax_bracket_arithmetic` (a single `tax_paid <= tax_due` inequality
per agent-month) is materially simpler to check than the six-term identity,
and `econagent_macro_trajectory` is explicitly disqualified from primary
status by its own declared estimand (descriptive-only, "no pass/fail
meaning" — it cannot be a `primary_estimand`, which requires an
`outcome_support` interpretation; the manifest's `outcome_support:
"pass_fail"` matches only the two rule_constraint leaves, not this one).

## Admission: `econagent_budget_identity_leaf` and `econagent_tax_bracket_arithmetic_leaf`

`docs/econagent_adapter_status.md`'s "Known limits" section already
classifies these two leaves as a pair, calling them "the two `rule_constraint`
leaves" throughout and noting they are "declared `hybrid_gate`-eligible" as a
group — distinct from `econagent_macro_trajectory`, which the same document
and `measurement.py`'s own docstring repeatedly call out as "Diagnostic only:
no comparator, no optimum, no pass/fail meaning." I am following that
pre-existing, already-committed classification rather than inventing one:

- Both rule_constraint leaves check whether the recorded episode is
  *internally consistent* with upstream's own executed accounting.
  `measurement.py` states directly that a violation here "is an adapter/bridge
  bug, never a policy-quality slack" — i.e. an `ok`-but-failing measurement on
  either of these leaves signals a genuine defect in this adapter's own
  bridge/replay path, not a legitimate policy outcome to merely report (this
  is the opposite of govsim's rule_constraint leaves, whose violations are
  legitimate policy behavior in a commons dilemma and were therefore
  deliberately kept *out* of govsim's admission set — I checked that
  distinction directly rather than copying govsim's admission shape by
  default).
- `econagent_macro_trajectory` is comparative/diagnostic by its own estimand
  (no pass/fail meaning, no optimum, no bound) — per spec section 3,
  "Diagnostic leaves are receipted but do not gate admission unless declared,"
  and I am not declaring it.

So `admission_leaf_ids = (econagent_budget_identity_leaf,
econagent_tax_bracket_arithmetic_leaf)`, and the primary
(`econagent_budget_identity_leaf`) is included, satisfying
`MeasurementDeclaration.__post_init__`.

**Note for a reviewer, stated rather than hidden**: `invalid_measurement` on
either of these two leaves is not "the identity failed to hold" (that is a
valid, informative `ok` result with `primary=0.0`/`false`-equivalent) — it is
"the measurement itself could not be produced" (missing/malformed
`dense_log`). In today's implementation both leaves share the same
`_require_dense_log` precondition, so in practice they go `invalid_measurement`
together whenever the episode's dense log is unusable; the one scenario where
they could diverge is `econagent_tax_bracket_arithmetic_leaf`'s live,
stateless re-invocation of `EconAgentBridge.recompute_tax` failing
independently of `dense_log` validity (e.g. a fresh bridge subprocess failing
at scoring time even though the episode's own recorded `dense_log` is fine).
Including both leaves in admission means that failure also excludes the
receipt, which I judge correct given both are declared bridge/adapter-bug
detectors, not diagnostics — but it is a judgment call, not a mechanical
consequence of anything checked above, exactly as spec section 3/R8 says no
identifier validation can catch a wrongly-scoped admission set. [Milestone-3
gate correction: as implemented, a `recompute_tax` failure raises out of the
scorer and yields no receipt; see the status doc's Leaf policy section.]

## Deferred leaves: none

All three leaves are proposed `scope="finalize_time"`. None depends on a
judge verdict, an external rater protocol, or another episode's run that
might not exist at finalization — every scorer in `measurement.py` is
deterministic arithmetic over replayed state (`dense_log`, `month_actions`,
`world_interest_rate_by_month`) or a fresh, stateless call into the pinned
upstream engine's own bracket-tax code. There is no artifact for a
`deferred_artifact` field to name, and no leaf's estimand definition requires
one (see the reference-source classification above).

## Reference gap: none

No leaf's estimand, as authored, requires a separate-run artifact (a baseline
policy episode under the same condition) or a judge verdict to produce a
valid `ok` value. `econagent_macro_trajectory` is the leaf that would most
plausibly need one (it is declared `comparative`/`baseline_delta`), but its
estimand is explicitly scoped `mode: descriptive/baseline_only` with no
comparator — it is honestly scoreable from this episode alone today. This
matches `docs/econagent_adapter_status.md`'s own claim table, which states
"no comparator, no optimum" for this leaf as a deliberate scope decision, not
a gap this migration is choosing to paper over.

## Ruling applicability

**R9/R10 (trajectory embedded in outcome): not applicable.**
`EconAgentV1Plugin.outcome()` (`environment.py`) returns exactly
`{termination_reason, timestep, n_agents, final_inventory_coin}` — final
aggregates only. `month_actions`, `world_interest_rate_by_month`, and
`dense_log` (the fields the three `trajectory`-scoped leaves actually read)
live only on `terminal()`, which `FamilyScoringInput.phase_instances`
reconstructs but `outcome` does not carry. Confirmed directly against this
base's `outcome()` implementation, not assumed. No
`trajectory_outcome_paths` declaration is needed.

**R12 (per-seat primaries): not applicable.** The manifest declares one role,
`agent`, symmetric across every seat (`n_agents` identical scripted-policy
seats acting simultaneously each month; see `roles.agent.scripted_policies`).
There is no subject-vs-opponent or tested-vs-baseline seat distinction
anywhere in this family — every seat runs the same upstream `complex` policy
computed once per month inside the bridge, and every leaf is a population- or
episode-level aggregate (all agents' budget identities, all agents' tax
arithmetic, aggregate GDP/price/unemployment), never "this one seat's own
realized value." No leaf is a `subject_seat` leaf; every leaf stays
`seat_scope="cell"` (the default).

## Paired-history pair: constructible — yes

`EconAgentV1Plugin.outcome()` carries only
`termination_reason, timestep, n_agents, final_inventory_coin` — never
`month_actions`, `world_interest_rate_by_month`, or `dense_log`. Those three
trajectory-bearing fields live only on `terminal()`/`phase_instances`, exactly
this ruling round's own worked case for a constructible pair (govsim: "had a
constructible paired-history pair because its outcome carries only final
aggregates"). Confirmed directly against this base's `outcome()`, not assumed
from that text.

Concretely buildable the same way the reference migration reasons about it
(to be verified against the real bridge in a later milestone, not merely
asserted here): two bridge-backed episodes with different `world_seed`s (or
different per-month action realizations) that happen to land on the same
final per-agent `Coin` inventories, the same `timestep`, and the same
`termination_reason` — same terminal outcome, genuinely different
`dense_log`/`month_actions` per month. Because this family has **no
`terminal_state` leaves**, the paired-history pair's role here is narrower
than govsim's: it is needed only for R9's sensitivity witness (showing each
of the three `trajectory` leaves *can* score differently given a different
trajectory on some pair), not for an R7 mislabelling-contrapositive check
(there is nothing declared `terminal_state` to check).

## Rulings that do not apply here

R9/R10 and R12 are addressed above (each not applicable, confirmed against
this family's own `outcome()`/manifest rather than assumed).

## Not yet decided (deferred to later milestones, as the task instructs)

- `__call__` does not exist on `EconAgentV1Scorer` today — only the three
  named `score_*` methods, exercised directly by tests. Milestone 2 will add
  it as a thin wrapper composing `score_budget_identity`,
  `score_tax_bracket_arithmetic`, and `score_macro_trajectory` into a
  `FamilyScoreSet`, per spec section 5.3 ("no new scoring logic is written").
  `score_tax_bracket_arithmetic` needs a live, stateless `bridge` argument
  (for `recompute_tax`) that `FamilyScoringInput` does not itself carry (it
  carries only replayed data, never a live upstream handle, per R2); how
  `__call__`/`build_scorer` obtains that fresh, stateless bridge instance
  (e.g. via the plugin's own `upstream_root`) is a milestone-2 implementation
  decision, not a milestone-0 classification question, and is not resolved
  here.
