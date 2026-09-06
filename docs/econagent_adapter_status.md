# econagent adapter — status

Branch `zeyu/econagent-contract-migration`. Last verified 2026-09-06.

## What the adapter claims

For three pinned, reduced-scale EconAgent (ACL 2024; `tsinghua-fib-lab/ACL24-EconAgent`,
commit `bfada09`) scenarios, it drives upstream's real, non-LLM `complex` scripted policy
end to end — through the REAL AERead shared-runner path
(`aeread.shared_runner.scheduler.run_episode`, not a hand-wired plugin-hook loop — see
"What milestone 3 added" below) — and publishes a **vector** of three separately-labelled
measurement leaves, never one blended number, with **no `objective_reference` and no
optimum claim of any kind**:

| Leaf | Verifier family | Reference kind | Claim |
|---|---|---|---|
| `econagent_budget_identity` | `rule_constraint` | `state_invariant` | Per-agent, per-month, the six-term budget identity (income, tax, lump-sum redistribution, consumption, saving interest, inventory) holds exactly — every term read from upstream's own executed state, never recomputed independently. |
| `econagent_tax_bracket_arithmetic` | `rule_constraint` | `constraint_satisfaction` | Every recorded `tax_paid` matches upstream's own `PeriodicBracketTax` bracket computation, re-invoked live — never a reimplemented piecewise formula. |
| `econagent_macro_trajectory` | `comparative` | `baseline_delta` (mode: descriptive/baseline-only) | GDP-proxy, price level, unemployment-proxy time series. Diagnostic only — no comparator, no optimum, no pass/fail meaning. |

EconAgent itself defines no reward and no task-success criterion (`simulate.py` only dumps
a dense log); this spec deliberately never manufactures one. See
`docs/econagent_adapter_spec.md` section 2 for the full verifier declaration and section 6
for the stated scope limits.

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf policy
explicitly (spec section 3), and `EconAgentV1Scorer.__call__` takes a
`FamilyScoringInput` and returns a `FamilyScoreSet` carrying every one of the three
leaves below. There was no pre-existing `__call__` to retire a shim from (only the
three named `score_*` methods existed before this milestone, exercised directly by
tests); `__call__` is new this milestone, composing those three methods and no new
scoring logic.

| Leaf | Scope | Primary | Admission |
|---|---|---|---|
| `econagent_budget_identity_leaf` | `finalize_time` | **yes** | **yes** |
| `econagent_tax_bracket_arithmetic_leaf` | `finalize_time` | no | **yes** |
| `econagent_macro_trajectory_leaf` | `finalize_time` | no | no |

**Why `econagent_budget_identity` is primary.** It is this family's own
already-declared `primary_estimand` (`family_manifest()`'s `measurement` block,
present since before this milestone) and this adapter's foundational correctness
claim: the six-term accounting identity every agent's inventory must satisfy every
month, sourced entirely from upstream's own executed state (see this module's own
docstring, "Leaf 1"). It was not picked because it was the easiest leaf to compute:
`econagent_tax_bracket_arithmetic` (a single `tax_paid <= tax_due` inequality per
agent-month) is materially simpler to check than the six-term identity, and
`econagent_macro_trajectory` is disqualified from primary status by its own declared
estimand — descriptive-only, "no comparator, no optimum, no pass/fail meaning" — which
cannot support the `outcome_support: "pass_fail"` this family's manifest declares.

**Why `econagent_budget_identity` and `econagent_tax_bracket_arithmetic` alone gate
admission.** Both are `rule_constraint` leaves checking whether the recorded episode is
*internally consistent* with upstream's own executed accounting — a violation on either
is an adapter/bridge bug, never a policy-quality slack (this module's own docstring,
"a violation past this tolerance is an adapter/bridge bug, not a policy failure"). An
`invalid_measurement` on either therefore means the measurement itself could not be
produced (a missing or malformed `dense_log`, or — for the tax-bracket leaf specifically
— a bridge failure re-invoking `recompute_tax`), not that a legitimate policy behavior
was observed; excluding the receipt in that case is the correct admission semantics.
`econagent_macro_trajectory` is comparative/diagnostic by its own estimand (no pass/fail
meaning, no optimum, no bound) — per spec section 3, "Diagnostic leaves are receipted
but do not gate admission unless declared," and it is not declared here.

**Deferred leaves: none.** Every leaf in this family is `evaluation_class="deterministic"`
with no judge, rater, or other not-yet-existing artifact anywhere in its verifier
declaration (`measurement.py`'s `build_*_leaf` functions); nothing here waits on an
artifact that "may not exist yet" (spec section 4), so all three are declared
`scope="finalize_time"` and none is `scope="deferred"`.

**Seat policy: not applicable.** Every leaf stays `seat_scope="cell"` (the default,
ruling R12) — the manifest declares one role, `agent`, symmetric across every seat (all
`n_agents` seats run the same upstream `complex` scripted policy), with no
subject-vs-opponent or tested-vs-baseline seat distinction anywhere in this family; every
leaf is a population- or episode-level aggregate, never one seat's own realized value.
See `docs/econagent_migration_plan.md`'s "Ruling applicability" section for the fuller
argument, made against this family's real `outcome()`/manifest rather than assumed.

`EconAgentV1Scorer.__call__`'s three leaves are all declared `input_scope="trajectory"`:
`scoring_input.outcome` (`environment.py`'s `outcome()`) carries only
`termination_reason, timestep, n_agents, final_inventory_coin` — never `dense_log`,
`month_actions`, or `world_interest_rate_by_month` — so every one reads those fields off
`scoring_input.phase_instances` instead, via `measurement.py`'s
`_terminal_fields_from_phase_instances` (this family's `mode="simultaneous"` phase
produces exactly one transition per phase instance -- one per month -- so the last phase
instance's last transition's state carries the full, cumulative, terminal content for the
whole episode). `econagent_tax_bracket_arithmetic`'s live, stateless
`EconAgentBridge.recompute_tax` re-invocation is threaded through via
`EconAgentV1Scorer.bridge_factory`, the same factory
`EconAgentV1Plugin.build_scorer` already uses for a live episode's own scoring.

## Scoring-contract enrollment (kernel_scoring_contract_spec.md, migration milestone 3 of 3)

`econagent_v1` is dropped from `_NOT_YET_MIGRATED_TRUSTED_KEYS` in
`tests/test_shared_runner_scoring_contract.py` and enrolled via
`_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS` (mirroring govsim's identical treatment): its
fixture needs the real, provisioned EconAgent bridge, so it is verified in its own
per-test-skippable `test_econagent_obeys_the_scoring_contract`, not folded into the
always-on `test_every_registered_family_obeys_the_scoring_contract` (which would make
every other family's own coverage there skip too whenever the bridge is unavailable).
`AEREAD_ECONAGENT_BRIDGE_REQUIRED` already existed in the root `conftest.py` before this
milestone (see "Open items" below — the prior note there describing it as unwired was
stale) and needed no change: it already turns a skip of any econagent-family test,
including the new one, into a failed run when set.

**A receipt now comes back — this family's first.** `tests/test_econagent_replay.py`'s
new `test_finalize_wires_econagent_to_the_shared_family_finalizer` drives one real,
bridge-backed episode (the checked-in `tiny4x6.seed0` case) end to end through
`task.evaluation.finalize_family_execution` and asserts `status == "ok"`,
`inclusion_status == "included"`, exactly the three declared leaves, and
`primary_leaf_id == econagent_budget_identity_leaf`.

**A genuine kernel-replay defect this milestone's own first attempt surfaced and fixed**
(mirrors the worked example's own trap 1, a different instance of "the rebase-era kernel
contract breaks an assumption no earlier milestone exercised"): `task.evaluation.
_replay_family_trajectory` calls `plugin.initial_state(family_case, run=None)` — no
`PlanCell` at all, unlike the real scheduler. `EconAgentV1Plugin.initial_state` used to
derive `bridge_session_id` from `cell.cell_id` (docs/econagent_codex_triage.md finding 6,
deliberately, to make a live run byte-identical to its own `replay.py`-driven offline
replay, which always reuses the same real `cell`) and fall back to a random id when no
cell was given — a random id can never be reproduced by kernel replay, so every phase's
`pre_state_sha256` cross-check failed on the very first phase boundary. Fixed by having
`EconAgentV1Plugin` remember, per distinct `family_case` digest, a FIFO queue of every id
a real cell minted for it; the no-cell fallback consumes the oldest still-queued entry
instead of minting a random one. This preserves the existing, test-guarded property that
two different cells of the identical case never share a session id (`_mint_session_id`'s
own docstring and `test_initial_state_mints_distinct_session_ids_for_two_different_cells_
of_the_same_case` are unaffected — that path is untouched), while letting kernel replay
reproduce whichever real cell's id the corresponding live run actually used. Also renamed
`initial_state`'s second parameter from `cell` to `run` (the kernel calls it by that
keyword; a positional call from the real scheduler is unaffected) — the identical fix
`govsim`'s own migration needed for the identical reason.

**The whole-outcome paired-history pair is constructible — verified, not merely asserted.**
The migration plan flagged this as "to be verified against the real bridge in a later
milestone." Verified here:
`tests/test_econagent_replay.py::test_paired_history_pair_has_a_byte_identical_outcome_and_a_differing_trajectory`
drives two real episodes (`world_seed=0` and `world_seed=1`, `gamma=-1.0`) and asserts,
directly (not in a comment), `canonical_json_bytes(left.outcome) ==
canonical_json_bytes(right.outcome)` (both `{"termination_reason":
"episode_length_reached", "timestep": 1, "n_agents": 2, "final_inventory_coin": {"0": 0.0,
"1": 0.0}}`) and `left.phase_instances != right.phase_instances`. The construction is
domain reasoning, not luck: upstream's own `complex_actions` decides labor via
`int(np.random.uniform() < (income / (wealth * (1+interest_rate) + 1e-8)) ** gamma)`; at
month 1 every agent's `wealth` is exactly the pinned config's own starting balance of `0`
(seed-independent), so a negative `gamma` makes the huge positive base raised to a negative
power underflow to `0.0`, forcing every agent's labor draw to `False` with certainty
regardless of `world_seed` — zero income, zero tax, zero lump-sum redistribution, and
upstream's own consumption components clip nominal spend to available wealth (`0`), so
actual `consumption_spend` is also `0`. Two different seeds therefore land on the identical
(degenerate) terminal Coin balance from genuinely different skill draws, prices, and
nominal per-agent actions (also asserted in the test, not merely claimed).

**Ruling R9(b)'s same-case sensitivity witness cannot be satisfied by this family, and the
pair above cannot be routed through `_assert_family_obeys_the_scoring_contract`.** That
witness requires a SAME-CASE pair (byte-identical `family_case`) whose score differs for
each trajectory leaf. This family's whole trajectory is a deterministic function of
`family_case` alone (every seat's action is a content-free acknowledgment, spec
milestone-1 correction 4 — confirmed directly against the real bridge: running the
identical scenario twice reproduces the identical `dense_log`/`month_actions`/final state
bit-for-bit), so any two same-case fixtures always share identical economics, hence
identical `ScoreEnvelope` content for every leaf — the witness can never fire `True` for
this family, by construction. (The FIFO fix above makes a same-case pair *replayable* at
all; replayability was never the blocker, identical scoring content is.) Since every one
of this family's three leaves is genuinely `input_scope="trajectory"` — no
`terminal_state` leaf exists at all — supplying a second, different-case fixture (like the
pair above) still trips the SAME witness check, which runs unconditionally whenever a
family has any trajectory leaf and two or more supplied fixtures. `econagent_v1` is
therefore added to `tests/test_shared_runner_scoring_contract.py`'s
`_SINGLE_FIXTURE_EXEMPT_FAMILIES` — for a different, stronger reason than that set's four
existing members ("not yet supplied" there; "cannot be supplied at all" here) — and
`test_econagent_obeys_the_scoring_contract` therefore supplies exactly one fixture. The
paired-history pair's own byte-identity and differing-trajectory claims are still verified,
directly, by the dedicated test named above; only routing them through this one shared
helper is what the witness makes impossible.

**Independent review finding 3, confirmed and fixed.** Because the exemption above keeps
`econagent_v1` out of `_assert_family_obeys_the_scoring_contract`'s multi-fixture path
entirely, R9(b)'s sensitivity witness never runs for this family at all, and the
paired-history test's own final loop asserts only `status == "ok"` for each leaf on each
fixture — no metric or content comparison. `docs/econagent_migration_review.md` finding 3
(independent review, 2026-09-06) confirmed this as a genuine gap: a scorer regressed to a
constant, always-`"ok"` output that never read its own call's `scoring_input.
phase_instances` would still pass every check above. Fixed with a new test,
`tests/test_econagent_replay.py::
test_call_output_is_sensitive_to_phase_instances_for_every_declared_leaf`, that witnesses
non-constancy a different way that needs no same-case pair: two fixtures with the same
`world_seed` but a different `episode_length` (one month vs. two) must report a different
`checked_agent_months` metric for both `rule_constraint` leaves and a different metric
count for `econagent_macro_trajectory`, since both are derived from that call's own
`phase_instances`. This proves non-constancy, not genuine economic trajectory-dependence —
the same class of claim R9(b)'s own (unavailable, for this family) same-case witness
makes. Verified by mutation: caching `__call__`'s first call's trajectory fields and
reusing them for every later call makes the new test fail with exactly the
`AssertionError` `docs/econagent_migration_review.md`'s finding 3 disposition records
(`checked_agent_months is identical across two fixtures with a different
episode_length`), reverted immediately after.

## What milestone 3 added

Milestones 1-2 (cases, environment, measurement, goldens, parity) all exercised
`EconAgentV1Plugin` by calling its hooks directly in a hand-wired loop — never through the
real scheduler. Milestone 3 built:

- **`harness.py`** — `ScriptedEconAgentHarness`, a provider-free `ResponseSource`. Every
  `agent_i` seat submits the same acknowledgment every month regardless of observation (per
  milestone-1 correction 4, the real `[labor, consumption]` decision is computed once per
  month inside the persistent bridge session), so unlike `tau3_retail`'s harness there is no
  tool/action content to script at all.
- **`tests/test_econagent_e2e.py`** — both `econagent.pilot.small10x12.seed0` and `.seed1`
  driven end to end through `run_episode`/`PluginRegistry.resolve_manifest`, plus an
  importer-determinism check (running the importer twice, and against the committed case
  files, produces byte-identical output for all three scenario ids).
- **`replay.py`/`tests/test_econagent_replay.py`** — offline replay with the real upstream
  bridge subprocess never spawned. See "Evidence" below for what this actually proves and
  "Open items" below for its one real residual caveat (out-of-order replay of same-case
  episodes).
- **A real defect this pass's own first scheduler-driven run exposed and fixed**: `cases.py`
  and `environment.py` had set the per-episode logical-action budget to `episode_length`
  (months) rather than `n_agents * episode_length` (one logical action per agent seat per
  month, for this family's `mode="simultaneous"` phase) — undercounting by a factor of
  `n_agents` and undetected through two milestones of hand-wired tests. Fixed in the same
  commit as this milestone, following this spec's own established "reality forces a
  deviation" convention (see the spec's "Milestone 3 correction" section); the three on-disk
  case files were regenerated (`content_sha256` changed as a direct, sole consequence).

## Evidence

**Two full pilot episodes run end to end through the real scheduler**
(`test_econagent_e2e.py`): `small10x12.seed0` and `.seed1`, 10 agents x 12 months each — one
simultaneous phase instance per month, all 10 seats acting in each, 120 logical actions per
episode, terminal reason `episode_length_reached` both times, with genuinely different final
agent states (different `world_seed`).

**Replay reproduces state and score with the real bridge subprocess never spawned**
(`test_econagent_replay.py`'s other 22 tests — the file's remaining three tests, the
finalizer receipt test and the two scoring-contract witness tests, are described in the
"Scoring-contract enrollment" section above). A live 4-agent x 6-month episode's bridge call log
(`start_episode`, `agent_snapshot`, then `(step_month, agent_snapshot)` x 6, then
`dense_log`, `close` — 16 calls) is recorded, round-tripped through plain JSON text, and
replayed through the real scheduler with `EconAgentBridge._spawn` monkeypatched to raise if
ever called — the replay still completes, proving no subprocess is spawned. The replayed
episode's terminal record, outcome, and final-state *content* match the live run's exactly;
all three measurement leaves recomputed from the replay (including
`econagent_tax_bracket_arithmetic`, itself replayed from a separately recorded
`recompute_tax` call log) equal the live run's `ScoreEnvelope`s exactly. A mutation test
(tampering one recorded `step_month` response's `actions` field before replay) confirms the
comparator genuinely detects divergence rather than being vacuously true.

**Suite: 164 econagent-family + smoke + scoring-contract-protocol tests passed, 0 failed,
0 skipped**, re-verified against this branch's HEAD (this list now also includes
`tests/test_shared_runner_scoring_contract.py` — this family's own hunk there,
`_econagent_fixture`/`test_econagent_obeys_the_scoring_contract` plus the rest of that
file's protocol-test suite, was not previously listed here), with a provisioned bridge
(`bridges/econagent-venv`) and the pinned upstream checkout present:

```
tests/test_econagent_bridge_required_enforcement.py tests/test_econagent_e2e.py
tests/test_econagent_parity.py tests/test_econagent_environment.py
tests/test_econagent_goldens.py tests/test_econagent_cases.py
tests/test_econagent_measurement.py tests/test_econagent_replay.py
tests/test_shared_runner_smoke.py tests/test_shared_runner_scoring_contract.py
164 passed in 110.34s
```

Re-run with none of `AEREAD_ECONAGENT_BRIDGE_PYTHON`/`AEREAD_ECONAGENT_BRIDGE_REQUIRED`
exported: still **164 passed, 0 skipped** on this machine, because
`discover_bridge_python`'s own fallback resolves the provisioned
`bridges/econagent-venv` default even unset, and `AEREAD_ECONAGENT_UPSTREAM_ROOT`'s
default already points at the pinned checkout -- so this particular pair of runs never
exercises this suite's own skip path (there is no vacuous-green gap to guard against
here; every bridge-gated test genuinely executed both times).

**Full repository regression check (812 passed, 31 skipped, 1 xfailed, 0 failed,
`pytest tests/` from the worktree root): last verified 2026-09-02, predates this
milestone and was not re-run here** — the family-scoped suite above is this milestone's
own verification; the 31 skips recorded then were other adapters' own bridge-gated tests
(tau2, etc.), not econagent's.

**Parity** (`test_econagent_parity.py`, built in milestone 2, re-verified here): for each of
the three pilot scenarios, the adapter's per-agent terminal `inventory["Coin"]`, cumulative
`tax_paid`, and dense-log length match an independently-invoked oracle call into the same
pinned upstream engine exactly — never the driver agreeing with itself. A mutation test
(two runs with different `world_seed`s) confirms the comparison detects real divergence.

**Goldens** (`test_econagent_goldens.py`, built in milestone 2, re-verified here): all five
QC Gate 2 instances (successful, valid-but-poor, invalid-or-unauthorized,
malformed-or-operational-failure, degenerate-reference) pass against the real bridge.

## Known limits, stated rather than implied

- **A lost `step_month` response leaves genuine mutation-outcome ambiguity that is
  contained, not eliminated.** `econagent_bridge_driver.py`'s `_op_step_month` runs the
  real, mutating `env.step(actions)` before its response is ever computed and flushed
  (the response's own content — timestep, done, the real upstream-computed actions — IS
  that mutation's result, so there is no way to confirm success before running it). If the
  subprocess or pipe fails in that exact window, the caller cannot tell "the month never
  ran" from "the month ran but the result was lost." `EconAgentBridge` raises a distinctly
  typed `EconAgentBridgeMutationOutcomeUnknownError` for this one case (never the plain
  `EconAgentBridgeError` every other request failure raises), and
  `test_golden_a_lost_step_month_response_aborts_the_whole_episode_via_the_real_scheduler`
  (`tests/test_econagent_goldens.py`) proves — through the real production path
  (`aeread.shared_runner.scheduler.run_episode`, not just an isolated `_request()` call) —
  that this ambiguity's one safe consequence holds end to end: the whole episode aborts as
  a `SchedulerContractError`, never a completed `EpisodeResult`, never a partially-scored
  month, never a silent retry. This is a genuine narrowing, not a fix: eliminating the
  ambiguity itself (rather than safely containing it) would require either modifying the
  pinned upstream engine to make `env.step` itself resumable/idempotent (forbidden by this
  adapter's own spec, which never reimplements or alters upstream mechanics) or adding a
  full state-journaling/recovery layer that would let a fresh process resume a crashed
  episode — neither this adapter nor the shared kernel has that today, and building it is a
  kernel-level architecture decision, not something fixable from this adapter's own code.
  One driver subprocess already serves exactly one episode by design (spec milestone-1
  correction 3); a crashed process is never resumed or interrogated after the fact regardless.
- **Seat action is an acknowledgment, not a decision.** Per milestone-1 correction 4, this
  pass's `PhaseSpec`/seat plumbing does not exercise a genuine per-seat decision surface —
  the real `complex_actions` computation happens once per month inside the bridge, not
  through any seat's parsed action. A non-scripted (e.g. LLM) policy seat is out of scope
  here and unaddressed by any test.
- **Only two shapes gated: 10 agents x 12 months and 4 agents x 6 months.** The paper's
  100-agent x 240-month configuration is declared in the manifest but explicitly `not_run`;
  no claim about that scale's behavior is made, including whether 100 simultaneous seats
  work at all through the scheduler (unverified by any test in this family).
- **No optimality or benchmark score, by design.** EconAgent defines no reward or baseline
  policy comparison upstream; `econagent_macro_trajectory` is descriptive-only and supports
  no capability or saturation claim.
- **Gate 2 hard-gate not wired.** The two `rule_constraint` leaves are declared
  `hybrid_gate`-eligible but no invalidating gate currently blocks a budget-identity
  violation from reaching the diagnostic leaves.
- **License posture.** No LICENSE file exists at the upstream repo root; this adapter never
  vendors any upstream file (import-only via bridge `sys.path`), which means zero
  availability guarantee if the upstream repository disappears.

## Open items noted in the ledger, not fixed here

- **Escalated, not fixed here: two live episodes of the identical `family_case`,
  finalized out of mint order, can consume each other's `bridge_session_id`.**
  `docs/econagent_migration_review.md` finding 1 (independent review, 2026-09-06):
  `_mint_session_id`'s no-cell fallback (`environment.py:645-716`) is an in-order FIFO,
  and kernel replay has no way to name which live episode it is replaying — see that
  method's own "Stated limit" paragraph. A genuine fix needs
  `task.evaluation._replay_family_trajectory` to thread the sealed evidence's own
  `cell_id` through as `run`, which is a shared-kernel change touching every migrated
  family's replay path, not something this adapter's own code can fix. Confirmed
  reachable (two evaluation blocks running the identical case) and recorded there with
  full evidence for an owner decision.
- No static Gate-1/Gate-2 check in the shared kernel cross-validates a case's declared
  `episode.max_logical_actions` against its phases' actual seat cardinality before an
  episode is really run through `run_episode` — the exact gap that let the
  `n_agents`-undercounted budget above survive two milestones of hand-wired tests
  undetected. See `ledger_entries/econagent.md` for the reproduction and a suggested static
  preflight check.
- ~~`AEREAD_ECONAGENT_BRIDGE_REQUIRED` has no enforcement hook generalized beyond tau2 in
  the shared root `conftest.py`~~ — stale as of the kernel_scoring_contract_spec.md
  migration milestone-3 pass: `conftest.py`'s `_BRIDGE_FAMILIES`/`_BRIDGE_FAMILY_DISPLAY`
  already carry a dedicated `AEREAD_ECONAGENT_BRIDGE_REQUIRED` entry (confirmed directly
  against this base's `conftest.py`, not assumed from the earlier note), which already
  turns a matching skip — including the new scoring-contract fixture/receipt tests this
  milestone added — into a failed run when set. No remaining gap here.

## What it costs to run

Unlike `tau2_bridge` (one fresh subprocess per call), this bridge is one persistent
subprocess per episode (spec milestone-1 correction 3, since `complex_actions` needs the
live upstream `env` object's shared RNG stream across the whole episode) — the full
164-test econagent + smoke + scoring-contract-protocol suite (grown from 96 by milestone
2's leaf-policy/`__call__` tests, then further grown by milestone 3's finalizer/
paired-history/sensitivity-witness tests and by this list now folding in this family's own
hunk of `tests/test_shared_runner_scoring_contract.py`), including every bridge-gated test
(goldens, parity, e2e, replay, and `__call__` driven both through a real scheduler episode
and through the scoring-contract protocol test), runs in under two minutes on this machine.
There is no multi-hour corpus sweep here: the entire declared, run corpus is three small
scenarios (10x12, 10x12, 4x6), by design (spec section 1) — the 100x240 paper
configuration is declared but never executed.
