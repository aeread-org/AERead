# govsim adapter — status

Branch `zeyu/govsim-contract-migration`, stacked on `zeyu/kernel-r9r10` (rulings
R9/R10). Last verified 2026-09-06.

## What the adapter claims

For each of GovSim's three common-pool-resource scenarios (fishing, sheep
pasture, pollution — one shared `ConcurrentEnv` arithmetic core, upstream pin
`1d11adf047b24fa2ba0d44a1d4931015ea2e5210`), driven by AERead-authored
scripted policies (`sustainable_v1`, `greedy_v1`, `mixed_v1` — never
upstream's `persona_v3` pathfinder LLM stack), the adapter reproduces
upstream's own regeneration/collapse/allocation arithmetic exactly by
delegating every `step()` call to the pinned checkout across a subprocess
bridge, then publishes five separately-labelled measurement leaves, all
deterministic (no leaf in this family depends on a judge or a model call):

| Leaf | Verifier family | Evaluation class |
|---|---|---|
| `govsim_no_collapse_leaf` | `rule_constraint` | `deterministic` |
| `govsim_threshold_adherence_leaf` | `rule_constraint` | `deterministic` |
| `govsim_survival_months_leaf` | `comparative` | `deterministic` |
| `govsim_total_harvest_leaf` | `comparative` | `deterministic` |
| `govsim_equality_gini_leaf` | `comparative` | `deterministic` |

This milestone (3 of 3) adds the scripted harness and the offline replayer,
so an episode can now be driven end to end through the REAL kernel path and
independently reproduced from a sealed record with zero further policy
evaluation and zero network calls.

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf
policy explicitly (spec section 3), and `GovsimScorer.__call__` takes a
`FamilyScoringInput` and returns a `FamilyScoreSet` carrying every one of the
five leaves below — the shim that previously returned only
`govsim_survival_months` (see the retired "Known limits" entry below) is
gone.

| Leaf | Scope | Primary | Admission |
|---|---|---|---|
| `govsim_no_collapse_leaf` | `finalize_time` | no | no |
| `govsim_threshold_adherence_leaf` | `finalize_time` | no | no |
| `govsim_survival_months_leaf` | `finalize_time` | **yes** | **yes** |
| `govsim_total_harvest_leaf` | `finalize_time` | no | no |
| `govsim_equality_gini_leaf` | `finalize_time` | no | no |

**Why `govsim_survival_months` is primary.** It is this family's own
already-declared `primary_estimand` (`family_manifest()`'s `measurement`
block, present since before this milestone) and its headline economic
quantity: how long the commons survives before collapse-or-horizon under the
policy being evaluated. It was not picked because it was the easiest leaf to
compute through the pre-migration seam (if anything it is the opposite —
`govsim_survival_months`'s inputs (`num_round`, `collected_resource`,
`termination_reason`) come straight off `scoring_input.outcome`, while the
two rule/constraint leaves are the ones that need trajectory reconstruction:
they read `round_trace`, which `outcome` never carries, so
`GovsimScorer.__call__` reconstructs it via
`_round_trace_from_phase_instances`, off the last replayed `PhaseInstance`'s
last transition state; the choice tracks the family's own declared
estimand, not convenience).

**Why it alone gates admission.** The other four are diagnostics, not
admission gates, for two independent reasons already recorded in
`measurement.py`'s own module docstring before this milestone:

- `govsim_no_collapse_leaf`/`govsim_threshold_adherence_leaf` are
  `rule_constraint` diagnostics per `docs/verifier_taxonomy.md` section 4
  ("a hard gate … should not silently convert a normative tradeoff into
  invalidity") — a policy that lets the commons collapse, or exceeds the
  advisory threshold, did something economically informative, not something
  unmeasurable.
- `govsim_total_harvest_leaf`/`govsim_equality_gini_leaf` are `comparative`,
  `direction="none"` leaves with no certified policy upper bound
  (`docs/problem_bound_case_audit.md` row P06) and are explicitly flagged
  unreliable for the degenerate `num_agents=1` golden. A low harvest or a
  high Gini is a measured (`status="ok"`) outcome, never grounds to exclude
  the receipt — gating admission on any of these would misuse
  `invalid_measurement` for "the model did economically poorly" rather than
  its actual meaning, "this could not be measured."

Only an `operational_failure` termination invalidates every leaf at once
(all five scorers share that one check), so in practice admission today
tracks whether the episode could be measured at all, never a comparative
value's magnitude.

**Deferred leaves: none.** Every leaf in this family is
`evaluation_class="deterministic"` with no judge, rater, or other
not-yet-existing artifact anywhere in its verifier declaration
(`measurement.py`'s `build_*_leaf` functions); nothing here waits on an
artifact that "may not exist yet" (spec section 4), so all five are declared
`scope="finalize_time"` and none is `scope="deferred"`.

## Evidence

**Corpus: 9 cases committed** under `cases/govsim/v1/`
(`govsim.<scenario>.<policy>.<world_seed>.json`, 3 scenarios × 3 policies,
one world seed each), plus `corpus_manifest.json` and `pins.json`.
`pins.json`'s `bridge_versions` is populated against the provisioned bridge
venv (numpy 1.24.4, pandas 2.0.3, omegaconf 2.3.0, pettingzoo 1.24.2, Python
3.11.3) — not the `bridge_versions_unavailable_reason` fallback.

**Scripted harness drives the REAL scheduler path, not a shortcut.**
`ScriptedGovsimHarness` (`src/aeread_families/govsim/harness.py`) implements
the actual `response_source` protocol `aeread.shared_runner.scheduler.
run_episode` requires — the same shape a live model-backed run would use —
and every test in `tests/test_govsim_replay.py` resolves its `GovsimPlugin`
through a real `aeread.shared_runner.registry.PluginRegistry`, never by
constructing the plugin by hand. This replaces
`tests/test_govsim_measurement.py`'s earlier `_drive_episode` helper (still
present there for that file's own leaf-construction tests), which called
`GovsimPlugin`'s hooks directly and never exercised the scheduler's own
budget checks, envelope construction, or state hashing.

**Two full episodes, sealed evidence.** `test_live_run_produces_sealed_
evidence_that_verifies` drives `fishing/sustainable_v1` (all 5 seats, full
12-round horizon, ends `collapse_or_horizon` at round 12) and
`fishing/greedy_v1` (collapses well before round 12,
`resource_in_pool < 5`) each through `run_episode`, appending one
`EvidenceStore` event per completed logical action via the harness's
`finalize_action` hook, and confirms `evidence.verify_seal()` reports an
event count matching every logical action actually taken.

**Replay reproduces state, terminal, and outcome byte-identically, not just
in content.** `replay.py`'s `RecordedEpisode`/`RecordedResponseSource` carry
only the raw per-decision `{"quantity": int}` / `{}` responses already
recorded on the live `EpisodeResult` — never upstream state or scores —
round-tripped through plain JSON text (`RecordedEpisode.to_json`/
`from_json`) so replay never depends on reusing the original run's in-memory
objects. `GovsimPlugin.step()` alone recomputes the resulting state each
call by replaying `reset(seed=...)` plus the full ordered action history
through a second, independent `GovsimBridge`/plugin. Because this family's
state carries no wall-clock timestamp (unlike `tau3_retail`'s per-message
`timestamp`), both full episodes replay with
`canonical_json_bytes(replayed.final_state) ==
canonical_json_bytes(live.result.final_state)` and the same for `terminal` —
a byte-exact match, verified as a fact for both the full-horizon and the
early-collapse episode, not merely asserted as a design property. All five
measurement leaves recomputed from the replayed result match the live scores
exactly (`test_replayed_episode_recomputes_all_five_leaves_matching_the_
live_scores`).

**A tampered recording is caught.** Unlike `tau3_retail` (whose plugin
cross-checks each recorded tool call against upstream inside `step()`
itself), `GovsimPlugin.step()` has no external tool result to cross-check —
every call recomputes state from scratch via the bridge. A tampered
recorded decision is therefore caught one layer up, at
`compare_episode_results`: `test_replay_of_a_tampered_response_diverges_
from_the_original_and_is_caught_by_comparison` mutates one recorded
`quantity` and confirms the replay's resulting state genuinely diverges and
`assert_replay_matches` raises rather than silently passing.

**A real receipt now exists.** Before this milestone this family had never
produced an `EvaluationReceipt`. `test_finalize_wires_govsim_to_the_shared_
family_finalizer` (`tests/test_govsim_replay.py`) drives one small, real,
bridge-backed two-agent/two-round episode through
`EvidenceRecordingGovsimHarness` (which writes the full generic evidence
trail `finalize_family_execution`'s internal replay can consume, unlike
`ScriptedGovsimHarness`'s own convenience-only event) and then calls
`aeread.shared_runner.task.evaluation.finalize_family_execution` directly —
the real production finalizer, not a stand-in. The returned receipt has
`status == "ok"`, `inclusion_status == "included"`, carries all five
declared leaf ids, and `primary_leaf_id == govsim_survival_months_leaf`.

**The scoring-contract protocol test is enrolled, and a silent skip is now
caught.** `test_govsim_obeys_the_scoring_contract`
(`tests/test_shared_runner_scoring_contract.py`) enrolls this family in the
shared scoring-contract protocol check via `_govsim_fixture_pair`, a
bridge-gated fixture set run through the same `_assert_family_obeys_the_
scoring_contract` every other migrated family is checked against (renamed
from `_assert_family_scoring_contract` when this branch stacked onto
`zeyu/kernel-r9r10`, which had already extracted the identical per-family
protocol body under that name for its own R9/R10 end-to-end tests — govsim's
copy was dropped in favor of the kernel's one helper, never kept alongside
it). Because that fixture set needs the real bridge, the test itself is
per-test skipped when the bridge is unavailable — independent review
finding 1 (`docs/govsim_migration_review.md`) flagged that a plain green CI
run could hide this skip entirely, since the closed-world catalog closure
counted govsim as enrolled regardless of whether this test ran. The fix
(commit `b853ed74`, root `conftest.py`) added a dedicated
`AEREAD_GOVSIM_BRIDGE_REQUIRED` entry: setting it to `1` turns that skip
into a failed run instead of a silent pass, mirroring the already-
established mechanism for tau2-bench/econ-evals/etc.
`tests/test_govsim_bridge_required_gate.py`'s six cases verify this
directly against the real `conftest.pytest_terminal_summary` hook, never a
reimplementation of it.

`_govsim_fixture_pair` now returns four fixtures, not two. The first two are
unchanged from before this rebase — the paired-history pair (byte-identical
terminal outcome, genuinely differing trajectory) `_assert_family_obeys_
the_scoring_contract` reads via `produced_by_case[:2]` for ruling R7's
mislabelling contrapositive over the three `terminal_state`-scoped leaves.
The kernel's own ruling R9(b) sensitivity witness
(`_assert_trajectory_leaves_are_witnessed`) additionally requires each
`trajectory`-scoped leaf to change on some same-case pair (same
`family_case`, differing `phase_instances`) — the paired-history pair alone
cannot show this for either of govsim's two trajectory leaves: it is a
symmetric per-seat swap, so `govsim_threshold_adherence` stays identical,
and neither fixture collapses early, so `govsim_no_collapse` stays
identical too (confirmed as a real, observed failure before the fixtures
below were added, not assumed). Two more same-case fixtures were added
purely to satisfy that witness: `_GOVSIM_COLLAPSE_HARVEST_SCHEDULE` (a
round-0 harvest of 98 out of a pool of 100 drives the pre-regeneration pool
under upstream's own `< 5` collapse test before the horizon, witnessing
`govsim_no_collapse`) and `_GOVSIM_ASYMMETRIC_THRESHOLD_BREACH_SCHEDULE`
(one seat harvests above round 0's advisory `sustainability_threshold` of
10 while the other stays under it, witnessing `govsim_threshold_adherence`,
then both seats harvest well under round 1's recomputed threshold so the
episode still reaches the horizon, isolating the difference to that one
leaf).

**Suite (re-verified after stacking on `zeyu/kernel-r9r10`): 214 passed, 0
failed, 0 skipped** (one pre-existing `RuntimeWarning` from
`_vendored_gini`'s all-zero-array nan case, unrelated to this change) running
the extended family test file set — the original file set below plus the
two files this stack adds beyond the milestone-3 set
(`tests/test_govsim_bridge_required_gate.py` and
`tests/test_shared_runner_schemas.py`, the latter exercised because ruling
R9 added `trajectory_outcome_paths` to the same `MeasurementDeclaration`
schema this family's manifest uses) —
`tests/test_govsim_bridge_driver.py`, `tests/test_govsim_cases.py`,
`tests/test_govsim_environment.py`, `tests/test_govsim_measurement.py`,
`tests/test_govsim_parity.py`, `tests/test_govsim_replay_skip_behavior.py`,
`tests/test_govsim_replay.py`, `tests/test_shared_runner_smoke.py`, with
`$AEREAD_GOVSIM_BRIDGE_PYTHON` and `$AEREAD_GOVSIM_UPSTREAM_ROOT` both
pointed at the provisioned bridge — every bridge-gated fidelity test (the
five QC Gate-2 goldens against the real upstream checkout, the gini parity
check, both replay episodes, and — following the independent review's fix
pass (`docs/govsim_review_disposition.md`) — the `sheep`/`pollution`
cross-scenario parity check and the `run_episode`-driven reject-policy abort
test) actually ran, none merely skipped past. Without the bridge set, the
same command reports **188 passed, 26 skipped, 0 failed** — the skips are
exactly the bridge-gated tests above, each with a `pytest.skip`
reason naming `$AEREAD_GOVSIM_BRIDGE_PYTHON` and
`tools/govsim_bridge/provision.sh`, never a silent pass.
`tests/test_govsim_bridge_required_gate.py`'s own six cases never touch the
bridge (they drive `conftest.py`'s hook against hand-built fakes), so they
pass either way.

`tests/test_shared_runner_scoring_contract.py` on its own (the full file —
every test, not only `test_govsim_obeys_the_scoring_contract`), bridge
exported: **32 passed, 0 failed, 0 skipped**, including the new
`test_sensitivity_witness_*` cases ruling R9(b) adds and govsim's own
four-fixture `test_govsim_obeys_the_scoring_contract` above.

```bash
export AEREAD_GOVSIM_BRIDGE_PYTHON=<bridges/govsim-venv path>
export AEREAD_GOVSIM_UPSTREAM_ROOT=<upstream-govsim checkout path>
pytest tests/test_govsim_bridge_driver.py tests/test_govsim_cases.py \
       tests/test_govsim_environment.py tests/test_govsim_measurement.py \
       tests/test_govsim_parity.py tests/test_govsim_replay_skip_behavior.py \
       tests/test_govsim_replay.py tests/test_shared_runner_smoke.py \
       tests/test_govsim_bridge_required_gate.py \
       tests/test_shared_runner_schemas.py \
       tests/test_shared_runner_scoring_contract.py
```

## What it costs to run

Each bridge call spawns a fresh subprocess that replays `reset(seed=...)`
plus the full ordered action history to date (O(n) upstream `step()` calls
per bridge call, not O(1) — see `docs/govsim_adapter_spec.md` section 7),
so cost grows with episode length. The full bridge-required run above (127
tests, including two full episodes driven live and then independently
replayed, the finalizer-receipt episode, the scoring-contract fixture pair,
plus every gini-parity, golden-scenario, and cross-scenario parity bridge
call) took **~260s wall-clock**. No persistent bridge daemon
is used; the same
per-call isolation tradeoff `tau2_bridge.py` makes is repeated here
deliberately, for the same reason — no state can leak between calls through
a long-lived interpreter.

## Known limits, stated rather than implied

- **Spec section 5's parity file, `tests/test_govsim_parity.py`, now checks
  P2/P3 every round, not only at the terminal aggregate.** An independent
  cross-model verification pass (`docs/govsim_fix_verification.md`)
  flagged that this file's first version checked P2 against only three
  terminal aggregate values and never checked P3's `collected_resource`
  per round at all — exactly the gap spec section 5 itself warns about,
  "a transient per-round collection/trace mismatch that later converges to
  the same terminal aggregates" could have passed both. Both
  `test_p2_adapter_translation_matches_an_independently_constructed_raw_
  action_sequence` and `test_p3_recorded_regeneration_and_collapse_match_
  the_documented_formula_independently` now assert `resource_in_pool`,
  `collected_resource`, and the collapse/termination trace at EVERY round;
  confirmed to have teeth by mutation test — zeroing out `round_trace`'s
  per-round `wanted_resource` in `environment.py` left the TERMINAL
  aggregates untouched (proving the old terminal-only checks would have
  stayed green) while both per-round tests failed immediately at round 0
  (see `docs/govsim_review_disposition.md`'s "Verification follow-up"
  section). P1 (import-determinism) and P4 (gini parity) remain covered
  where already documented (`tests/test_govsim_cases.py`, `tests/test_
  govsim_measurement.py`).
- **Scripted policies only.** No `persona_v3`/pathfinder LLM cognition is
  wrapped, bridged, or reimplemented; every policy submits an empty
  conversation (upstream's `language_nature: none`).
- **No certified policy upper bound for any comparative leaf.** The three
  comparative leaves (`survival_months`, `total_harvest`, `equality_gini`)
  are baseline-only comparisons against AERead's own scripted policies —
  never a solved optimum. A high `survival_months` must never be read as
  evidence of saturation.
- **The degenerate-reference golden's `comparison_baseline` is flagged, not
  a clean result.** `fishing`/`num_agents=1`/`sustainable_v1` has no peer to
  free-ride against, so any comparison against `greedy_v1` there is
  uninformative by construction.
- **Corpus is 9 cells, not the paper's full grid** (persona-name variants,
  universalization on/off, perturbations, multi-seed statistics) — a
  follow-up, mirroring how the `tau3_retail` pilot preceded its 114-task
  expansion.
- **Byte-identical replay depends on reusing the same `PlanCell`.** Both
  replay tests deliberately construct the replay plugin against the
  original run's own `cell` so `episode_id`/`phase_instance_id`/
  `logical_action_id` derivations line up; replaying the same recorded
  decisions under a genuinely different cell was not tested and is not
  claimed to reproduce byte-identically.
- **No mutation-testing pass has been run against this milestone's new
  code** (`harness.py`, `replay.py`) the way `tau3_retail`'s adapter was
  mutation tested; the tampered-response test above covers one specific
  mutation (a changed `quantity`), not a systematic sweep.
- ~~**`GovsimScorer.__call__` surfaces only ONE of this family's five
  declared leaves, never all five.**~~ **Resolved by this milestone**
  (`kernel_scoring_contract_spec.md`'s `FamilyScoringInput`/`FamilyScoreSet`
  contract, migration milestone 2 of 3). `__call__` now takes a
  `FamilyScoringInput` and returns a `FamilyScoreSet` carrying every one of
  the five declared leaves; see "Leaf policy" above. This resolves the
  mismatch ledger entry **D-16** (`runner_defect_ledger.md`) recorded as an
  open kernel-owner decision: the kernel's finalizer call site no longer
  expects exactly one `ScoreEnvelope` back, so this family's five
  separately-labelled leaves no longer need to be collapsed into one to
  satisfy it. `runner_defect_ledger.md` is not tracked in this branch's
  worktree, so its own entry is not updated here; this bullet records the
  resolution from this adapter's side.

## Ledger

Defects/limitations found in the shared kernel or environment during this
work (not in this adapter's own code) are recorded in
`ledger_entries/govsim.md`, not here.
