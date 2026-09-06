# alympics.wac migration plan (kernel_scoring_contract_spec.md)

Milestone 0 output. Precondition checks recorded below; no code changed in this
milestone. Shape to follow is the reference migration (worktree
`.../AERead/.worktrees/govsim-migrate`, commits `35cf3d73..6aabb5fd`), read in
full before writing this plan, plus the collusion migration
(`.../AERead/.worktrees/collusion-migrate`) for how a genuine reference gap is
argued and escalated rather than guessed at.

## Preconditions confirmed on this base

- `git fetch origin` run; worktree is on branch
  `zeyu/alympics-contract-migration`; `git log --oneline zeyu/kernel-r9r10..HEAD`
  is empty, i.e. this branch has not yet diverged from `zeyu/kernel-r9r10` — the
  starting point for this migration.
- `FamilyScoringInput` exists in `src/aeread/shared_runner/task/evaluation.py`;
  `LeafPolicyDeclaration` exists in `src/aeread/shared_runner/schemas.py`
  (alongside `FinalizeTimeLeafPolicy` and `MeasurementDeclaration`'s
  `leaves` / `primary_leaf_id` / `admission_leaf_ids` / `trajectory_outcome_paths`
  fields, all digest-neutral per ruling R1).
- `('alympics.wac', '0.1.0', 'alympics_wac_environment')` is in
  `TRUSTED_BUILTIN_PLUGIN_KEYS` (`src/aeread/shared_runner/registry.py:69`), and
  `("alympics.wac", "0.1.0")` is in `_NOT_YET_MIGRATED_TRUSTED_KEYS`
  (`tests/test_shared_runner_scoring_contract.py:1667`).
  `environment.py::register_plugin` already calls
  `registry.register_trusted(...)`, so this family is not exposed to the
  rebase-breaks-registration trap the worked example describes (trap 1) — it
  was already carried this way before this branch forked.
- `grep -c trajectory_outcome_paths src/aeread/shared_runner/schemas.py` → `11`
  (nonzero). Per the task framing this means we do **not** hit the STOP
  condition regardless of what the embeds-trajectory check below finds.
- Family test suite, bridge exported
  (`AEREAD_ALYMPICS_UPSTREAM_ROOT`): `tests/test_alympics_wac_parity.py`,
  `test_alympics_wac_environment.py`, `test_alympics_wac_upstream_required_gate.py`,
  `test_alympics_wac_cases.py`, `test_alympics_wac_harness.py`,
  `test_alympics_wac_replay.py`, `test_alympics_wac_measurement.py` —
  **112 passed, 0 failed, 0 skipped**, in 6.21s. This is the green baseline this
  migration must not regress.

## Does `outcome()` embed the trajectory?

`AlympicsWacPlugin.outcome()` (`environment.py`) returns:

```python
{
    "termination_reason": terminal["reason"],
    "final_round_id": terminal["round_id"],
    "final_players": terminal["players"],
    "eliminated_order": terminal["eliminated_order"],
}
```

`round_log` (the full per-round detail: `bids`, `bid_legal`, `winners`,
`players_before`/`players_after`) is **not** in `outcome()` — it lives only on
`terminal()`. But `eliminated_order` is: it is built the same way `round_log` is
(`new_state["eliminated_order"].extend(outcome.eliminated_this_round)` inside
`step`, once per round, `environment.py` line 696) — an accumulated, ordered
record of *when* each seat died, not a final aggregate. Two trajectories that
end with the same set of surviving/eliminated seats can still disagree on the
*order* in which the eliminated ones died (a dead seat's balance freezes at the
round it dies, so an earlier vs. later death also perturbs `final_players` in
the general case, but the ordering fact itself is carried nowhere except this
field). This is structurally the same shape as collusion's `/history` and
datacenter_development's `public_history` — an ordered, round-by-round event
record embedded directly in the outcome — just far more compressed.

`final_round_id` and `final_players` are **not** trajectory-bearing by the same
test the reference migrations use: `final_round_id` is a scalar count,
analogous to collusion's own non-declared `rounds_played` and govsim's
non-declared `num_round`; `final_players` is a final-aggregate snapshot
(ending balance/hp/no_drink/alive per seat), analogous to govsim's non-declared
`resource_in_pool`/`collected_resource` — cumulative across rounds, but not
itself an ordered sequence of events.

**Conclusion: `outcome()` does embed a trajectory-bearing field
(`eliminated_order`).** Per the task's rule this means the **whole-outcome**
paired-history pair is not constructible, and rulings R9/R10 apply: this family
must declare `trajectory_outcome_paths = ("/eliminated_order",)` and R7's
paired-history check operates on the *projection* (outcome with that path
removed), exactly as collusion does for `/history`. Since `schemas.py` already
carries `trajectory_outcome_paths` (confirmed nonzero above), this is a
manifest declaration to add in the implementation milestone, not a kernel gap.

## Today's declared leaves and their `input_scope`

All four leaves are declared unconditionally per `(focal_seat, panel_policy_ids,
baseline_policy_id)` (`measurement.py::build_leaves`); both the `EstimandSpec`
and the `ReferenceSpec` on every leaf declare `input_scope="trajectory"` — none
is `terminal_state` under the existing (pre-contract) vocabulary.

| Leaf id | Estimand id | `input_scope` | Verifier family | Reference kind | Evaluation class |
|---|---|---|---|---|---|
| `alympics_wac_terminal_wealth_leaf` | `alympics_wac_terminal_wealth` | `trajectory` | `comparative` | `baseline_delta` | `deterministic` |
| `alympics_wac_survival_leaf` | `alympics_wac_survival` | `trajectory` | `comparative` | `baseline_delta` | `deterministic` |
| `alympics_wac_bid_legality_leaf` | `alympics_wac_bid_legality` | `trajectory` | `rule_constraint` | `constraint_satisfaction` | `deterministic` |
| `alympics_wac_settlement_exactness_leaf` | `alympics_wac_settlement_exactness` | `trajectory` | `rule_constraint` | `state_invariant` | `deterministic` |

No leaf has a judge/rater/rubric field anywhere in `measurement.py`
(`measurement.py`'s own module docstring: "unlike `tau3.retail`, this family
declares no rater/judge component at all"); every scorer is deterministic
arithmetic/comparison over replayed state plus, for leaves 1/2, a deterministic
in-process recompute (see below).

## Reference-source classification

| Leaf | What it needs | Classification | Reasoning |
|---|---|---|---|
| `alympics_wac_terminal_wealth_leaf` (primary) | (a) `actual_final_players`, `actual_round_log`, `actual_termination_reason` for the focal seat; (b) `baseline_final_players` for the same seat run under `baseline_policy_id` on the same case | (a) **replayed-episode**; (b) **closed-form-from-case** | (a) comes from this episode's own outcome/trajectory. (b) is produced by `_recompute_baseline_episode` (`measurement.py`), which is a pure, deterministic function of `family_case` alone (`seat_order`, `personas`, `supply_schedule`, `grid_cell.rounds`, the leaf's own opponent panel) plus the pinned upstream module (code, not an artifact) — it re-simulates the whole episode round-by-round through the same `environment._delegate_round` every live run uses, using `harness.POLICY_FUNCTIONS`, which are pure functions of only `(requirement, no_drink)`. Critically: every panel seat (every seat but the one under test) is *always* one of the four named scripted policies declared in `family_case["grid_cell"]["policy_assignment"]` (`docs/alympics_adapter_spec.md` §2, §4 row 4: "one seat rotates as focal ... comparative estimand") — never another live/LLM-driven seat. This is the opposite shape from collusion's leaf 4 (where the opponent can itself be a live model and the baseline recompute is therefore genuinely unreachable, per `docs/collusion_migration_review.md` Finding 2); here nothing outside `family_case` + pinned code is ever required, so the estimand itself, not merely today's plumbing, is closed-form. |
| `alympics_wac_survival_leaf` (diagnostic) | Same shape as leaf 1, but rounds-survived instead of balance | (a) **replayed-episode**; (b) **closed-form-from-case** | Same reasoning as leaf 1 — `score_survival` calls the identical `_recompute_baseline_episode`. |
| `alympics_wac_bid_legality_leaf` | Focal seat's per-round `bid_legal` flags, read off the episode's own `round_log` | **replayed-episode** | `score_bid_legality` never recomputes legality itself — it reduces `round_log[i]["bid_legal"][focal_seat]`, already recorded by `environment.step`'s `_check_winner_wrapper`, to one typed result. |
| `alympics_wac_settlement_exactness_leaf` | The episode's own `round_log` (`players_before`, `bids`, `players_after`, `winners`, `bid_legal`), shadow-recomputed a second time via `environment._delegate_round` | **replayed-episode** (the sealed pre-state/bids being reconstructed) composed with a **closed-form** recompute (upstream's own deterministic settlement, given that sealed pre-state) | `score_settlement_exactness` recomputes from `round_log[i]["players_before"]` + the recorded bids — both replayed-episode data — through the pinned, deterministic upstream mechanics. No external artifact. |

All four leaves resolve to inputs reachable from `FamilyScoringInput`
(`scoring_input.outcome`/`scoring_input.phase_instances` for the replayed parts,
`family_case` — already an argument to `build_scorer` — for the closed-form
baseline recompute). `actual_round_log` (needed by leaves 1, 2, 4) is not
carried in `outcome()` but is reconstructable from `phase_instances`: replay is
a verified deterministic re-execution (ruling R2) that actually calls
`plugin.step` per round, so the accumulated `round_log` is present on the state
each `TransitionResult.state` in `phase_instances[i].transitions` carries.

**No leaf here requires a separate-run or judge artifact.** This is a departure
from the naive reading of "a baseline policy run under the same condition" as
automatically separate-run: it is *not* separate-run in this family specifically
because the baseline policy and every opponent-panel seat are always drawn from
a small, fixed, deterministic scripted-policy vocabulary
(`harness.POLICY_FUNCTIONS`, four named policies, pure functions of public
per-seat state) declared in `family_case` itself — there is never a second,
independently-executed episode whose artifact would need to be sealed and
supplied. The family's own status doc
(`docs/alympics_adapter_status.md`, "Known limits") currently describes
`score_replayed_episode` as requiring "the caller to already have run and
replayed a second, baseline episode" — that is an accurate description of
*today's calling convention* (`replay.py` actually drives a second
harness/`run_episode`/`replay_episode` pass and hands its output to the
scorer), not of the estimand's requirements: `AlympicsWacScorer.
score_terminal_wealth`/`score_survival` already independently recompute that
same baseline via `_recompute_baseline_episode` and reject a caller-supplied
one that disagrees. The migration's `__call__` can call
`_recompute_baseline_episode` directly instead of depending on a caller-run
second episode — a simplification the contract enables, not a gap it exposes.
This is flagged here as a plumbing note for the implementation milestone, not
decided or coded now.

## Proposed primary: `alympics_wac_terminal_wealth_leaf`

`family_manifest()` (`environment.py`) already declares
`measurement.primary_estimand = "alympics_wac_terminal_wealth"`, which is
exactly `TERMINAL_WEALTH_ESTIMAND_ID`, the estimand of
`alympics_wac_terminal_wealth_leaf` — the leaf proposed as primary is the one
the manifest's existing family-level field already names in meaning, not a
same-named coincidence. Per ruling R8 the kernel does not enforce this
correspondence mechanically (`primary_estimand` and leaf ids are parallel,
unenforced namespaces for other families), which is exactly why a human has to
check it here: the module docstring (`measurement.py`) independently calls this
"Leaf 1 — ... (primary, comparative)" and the adapter spec
(`docs/alympics_adapter_spec.md` §2) calls it "Leaf 1 ... (primary, comparative)"
too — three independent sources agree. It is not "the one that was easiest to
compute" (spec section 3's forbidden reasoning): leaf 3 (bid legality, a single
recorded-flag lookup) is materially simpler and is not proposed as primary.

As established above, leaf 1 is finalize-time-constructible without any
deferred artifact, so nothing forces a different choice.

## Admission — recommendation, for reviewer confirmation

- `alympics_wac_terminal_wealth_leaf` (primary): always in admission by rule.
- `alympics_wac_bid_legality_leaf` and `alympics_wac_settlement_exactness_leaf`:
  recommended **in** admission. Unlike govsim's rule-constraint leaves
  (`govsim_no_collapse`/`govsim_threshold_adherence`, diagnostics because
  over-harvesting is a legitimate strategic tradeoff in that game, per
  `docs/govsim_migration_plan.md`), alympics's two rule-constraint leaves are
  not strategic tradeoffs — they are measurement-integrity checks:
  `alympics_wac_bid_legality` catches upstream's own silent
  bid-exceeds-balance exclusion "masquerading as an ordinary legal loss"
  (spec section 4 golden 3, quoted verbatim in `measurement.py`'s module
  docstring), and `alympics_wac_settlement_exactness` catches a sealed
  `round_log` entry whose recorded post-state cannot be reproduced from its
  recorded pre-state and bids (Gate 2 requirement 2) — a corrupted-evidence
  signal, not a normative judgment about strategy. Both already gate leaves
  1/2 *internally* (`score_terminal_wealth`/`score_survival` call the same
  `_bid_legality_invalid_reason` helper and return `invalid_measurement`
  themselves on violation), so admission membership here is largely
  confirmatory for leaf 3, but genuinely load-bearing for leaf 4: a
  settlement-recompute divergence is a distinct failure mode from an illegal
  bid and is not otherwise mirrored in leaf 1/2's own status.
- `alympics_wac_survival_leaf`: **not** in admission, matching its own
  declared status as "diagnostic" (spec section 2, `measurement.py` module
  docstring: "reported *separately* from wealth so a degenerate zero-information
  elimination ... is never averaged into wealth as if it were an ordinary
  loss") — a diagnostic companion to the primary, not itself a gate.

This is exactly the kind of semantic judgment call spec section 5.5 puts on a
human reviewer, not on validation; recorded here for the reviewer to confirm or
override before the implementation milestone writes it into the manifest.

## Deferred leaves: none

All four leaves are `scope="finalize_time"`. None depends on a judge verdict,
external rater protocol, or another episode's sealed artifact that might not
exist at finalization — every scorer in `measurement.py` is either replayed
state or a closed-form deterministic recompute reachable from `family_case`.
There is no artifact for a `deferred_artifact` field to name, and therefore no
reference gap to record.

## Reference gap

None. (Leaf 1's primary estimand — "same seat, same case, under a named
scripted baseline policy" — is realizable purely from `family_case` and pinned
upstream code, as established above; no estimand redefinition is needed.)

## Paired-history pair: constructible in the R9/R10 projected sense — yes; whole-outcome sense — no

Per the embeds-trajectory finding above, the **whole-outcome** pair (byte-identical
full `outcome`, differing `phase_instances`) is not the applicable construction
for this family — `eliminated_order` is trajectory-bearing and would need to
match too, which a genuinely different elimination sequence will generally
break (a seat's frozen balance depends on which round it died in). Once
`trajectory_outcome_paths = ("/eliminated_order",)` is declared, R9's
**projected** pair (outcome minus `/eliminated_order` identical; `phase_instances`
differing) is the correct construction, and it is buildable: two cases with the
same seat order, supply schedule, and opponent panel, where two panel seats'
bid amounts are swapped between two rounds in a way that changes which specific
round each of them is outbid in (hence a different `eliminated_order` and
different per-round `round_log` content) while leaving the terminal
`termination_reason`, `final_round_id`, and every seat's `final_players`
unchanged — concretely achievable here because `_check_winner`'s admission is
order-of-construction-tie-broken and several of this family's declared cases
already differ only in which policy is assigned to which seat
(`docs/alympics_adapter_spec.md` §4 rows), giving a starting point to search
from rather than constructing from nothing. Building the actual fixture pair
(and verifying it against the real upstream bridge, per the worked example's
warning against trusting an unconfirmed pair) is implementation-milestone work,
not decided further here.

The four `trajectory`-scoped leaves (all of them, per the table above) are
subject to R9's *sensitivity witness* — for each, some fixture pair must show
its score can differ — not R7's contrapositive (which applies only to
`terminal_state`-scoped leaves, and none of this family's leaves are declared
that way).

## Ledger items this migration touches

- `docs/alympics_adapter_status.md`'s "Baseline comparisons are not
  auto-derived" known limit is a candidate to close as a byproduct of this
  migration (see the plumbing note above) — the migration should update that
  doc if `__call__` stops depending on a caller-supplied second episode.
