# econevals adapter — status

Branch `zeyu/econevals-contract-migration`. Last verified 2026-09-05.

A second-reviewer fix pass ran against `docs/econevals_review_claude.md`
(`docs/econevals_review_codex.md` was never produced) this session; see
`docs/econevals_review_disposition.md` for the per-finding verification and
fix record. Nothing found was a kernel/runner defect, so no
`ledger_entries/econevals.md` entry was added on this pass.

## Leaf policy (kernel_scoring_contract_spec.md, migration milestone 2 of 3)

`family_manifest()`'s `measurement` block now declares this family's leaf
policy explicitly (spec section 3), and `EconevalsScorer.__call__`
(`measurement.py`) takes a `FamilyScoringInput` and returns a
`FamilyScoreSet` carrying both leaves below. Before this milestone this
family had no `__call__` at all — spec section 7 named econevals as one of
the three terminal-only families deliberately held back from migrating
under the old, single-envelope convention, so there is no pre-existing shim
to retire here, only new code to add.

| Leaf | Scope | Primary | Admission |
|---|---|---|---|
| `econevals_gate_leaf` | `finalize_time` | no | no |
| `econevals_objective_leaf` | `finalize_time` | **yes** | **yes** |

Both `leaf_id`s are now track-agnostic (`econevals_{track}_gate_leaf` /
`econevals_{track}_objective_leaf` before this milestone): the manifest
declares ONE static leaf set for the whole family/version, but the pre-
migration ids were parameterized by track, so a procurement case and a
scheduling case produced disjoint `leaf_id` sets — incompatible with one
static declaration (`docs/econevals_migration_plan.md`'s "Leaf-identity
finding"). The per-track distinctions — `estimand_id`, `units`, `direction`,
`reference.source_sha256` — are untouched by this rename; they still live
one level down inside each case's own `MeasurementLeafSpec`, and
`_enforce_declared_leaf_policy` never inspects them.

**Why `econevals_objective_leaf` is primary.** The manifest's own
`primary_estimand` field names `econevals_headroom_capture`, but **no leaf
realizes it** — this is a recorded reference gap, not an oversight; see
below. Per ruling R8 (kernel_scoring_contract_spec.md), a leaf-policy
primary need not name the same estimand as `primary_estimand`, so this is
not a same-named coincidence being forced apart, it is a real gap with a
closest-available substitute: `econevals_objective_leaf` is the leaf that
already reports this family's substantive economic headline — the achieved
value `V_agent`, in the track's own native units, against the case's own
pinned exact optimum `V*` (`measurement.py`'s own module docstring,
`docs/econevals_adapter_spec.md`'s milestone-2 build note: "the objective
leaf primary is native-units, not `headroom_capture`"). `headroom_capture`'s
own formula (`(V_agent - B) / (V_UB - B)`, verifier_taxonomy.md 5.3) divides
an achieved-value-vs-optimum quantity by a baseline-relative denominator;
the achieved-value-vs-optimum half is exactly what the objective leaf
already reports, without the baseline term this family cannot yet compute.
The gate leaf is not proposed as primary: it is a legality precondition
(`hybrid_gate`'s "deterministic prerequisite"), not the outcome being
measured.

**The `econevals_headroom_capture` reference gap, and why it is not
implemented as a leaf.** `headroom_capture`'s own definition needs a
`comparison_baseline` separate-run artifact — the output of an executable
baseline policy's own episode under the same case — which no leaf in this
family can honestly produce today: `measurement.py`'s own module docstring
states plainly that it "deliberately never computes `headroom_capture`
itself," and no baseline-episode machinery exists anywhere in this adapter.
Declaring a leaf for it and having that leaf report
`invalid_measurement` on every production episode was considered and
rejected for this family, for a reason specific to econevals rather than a
general objection to that pattern: `docs/econevals_migration_plan.md`'s own
milestone-0 analysis already established that **no `MeasurementLeafSpec`
for `headroom_capture` exists anywhere in this codebase** — there is no
estimand, verifier, or reference declared for it to attach a scope to, only
a bare `primary_estimand` string naming something no leaf realizes.
Inventing one now, solely so it can always fail, would be new leaf
authorship this migration's own rule forbids ("no family invents its own
finalize glue" / never write new scoring logic during this migration), not
a plumbing widening of something that already exists the way
`_objective_not_computed` below is. The estimand split this would properly
need — an `_own` finalize-time metric (what the two existing leaves already
report) plus a `_vs_baseline` deferred metric, once a baseline-run artifact
exists — is recorded here as an owner decision outside this migration's
scope, exactly as the plan states; `primary_estimand`, the manifest's
declared primary leaf, and admission membership are all left exactly as
this migration set them, not adjusted to manufacture an included
`headroom_capture` receipt.

**Why `econevals_objective_leaf` alone gates admission.** In this family's
own vocabulary, `invalid_measurement` was, before this milestone, triggered
only by a malformed/unparseable submission on the gate leaf — never by a
well-formed-but-illegal one, which stays `status="ok", primary=0.0`, a real
scored domain fact (`_gate_fail`'s own contract, unchanged). The pre-
migration `score_procurement`/`score_scheduling`/`score_pricing` return
`None` for the objective whenever the gate does not pass, for ANY reason
(malformed, illegal, or infeasible) — never only for the malformed case.
kernel_scoring_contract_spec.md section 3 requires every declared leaf to
be returned on every case, and `ScoreEnvelope` has only two statuses, so
this milestone's `_objective_not_computed` (`measurement.py`) turns that
`None` into an explicit `invalid_measurement` for the objective leaf,
reasoned distinctly from the malformed case but sharing its status — there
is no achieved value to report when the gate did not pass, for any reason,
and fabricating one is exactly what this module refuses to do. Concretely,
this means a well-formed-but-illegal submission (spec golden 3) now also
excludes the receipt from the family's own admitted-episode aggregate, via
the objective leaf alone, even though its GATE leaf stays `ok` and fully
receipted. This is an honest consequence, not a design flaw: there is no
legally-scoreable `V_agent` to average in for that episode, so excluding it
from the objective-based aggregate is correct; the gate's own `0.0` fact
remains visible on the receipt regardless of admission. `admission_leaf_ids
= (econevals_objective_leaf,)` is the default the spec gives when nothing
beyond the primary is declared, and nothing here motivates widening it to
include the gate leaf, which would be redundant with the objective leaf's
own invalid_measurement on exactly the cases that should exclude a receipt.

**Deferred leaves: none.** Both leaves are `evaluation_class="deterministic"`
with no judge, rater, or other not-yet-existing artifact anywhere in either
leaf's own verifier declaration (`measurement.py`'s `build_gate_leaf`/
`build_objective_leaf`): the gate reads this episode's own last recorded
attempt against a deterministic legality rule, and the objective compares
that same attempt's achieved value against the case's own pinned
`gold_optimum`, computed once at case-generation time. Nothing here waits
on an artifact that "may not exist yet" (spec section 4), so both are
declared `scope="finalize_time"` and neither is `scope="deferred"`.

**Scope of this milestone.** This pass implements the three pieces spec
sections 3/5 require per family (manifest leaf policy, `__call__`/
`score_all`, and this reasoning) plus family-level tests
(`tests/test_econevals_measurement.py`) that construct a
`FamilyScoringInput` by hand and mutation-verify the returned leaf set. It
does **not** yet drive a real episode through
`aeread.shared_runner.task.evaluation.finalize_family_execution`
end-to-end, nor enroll this family in
`tests/test_shared_runner_scoring_contract.py`'s registry-driven protocol
test (spec section 6) — both remain for a later milestone, matching how the
reference migration's own finalizer-wiring and protocol-test-enrollment
work landed as separate, later commits on top of the equivalent `__call__`
change. `("econevals", "0.1.0")` therefore stays listed in that test
file's own `_NOT_YET_MIGRATED_TRUSTED_KEYS` exemption for now.

**A latent signature mismatch, found but not yet fixed here.**
`task.evaluation._replay_family_trajectory` calls `plugin.initial_state(family_case,
run=None)` by keyword, but `EconevalsPlugin.initial_state`'s second
parameter is still named `cell` (`environment.py`) — the same defect the
reference migration's own `088e2693` fixed for govsim. Every existing call
site in this family's own tests passes that argument positionally
(`plugin.initial_state(family_case, None)`), so the rename is a safe,
zero-behavior-change fix, but nothing in *this* milestone's own tests
drives replay far enough to need it (they construct `FamilyScoringInput`
directly, never through `replay_family_scoring_input`). Left unfixed here
rather than expanding this milestone's scope; it will surface — and must be
fixed — the moment a future milestone drives a real episode through
`finalize_family_execution`, exactly as it did for govsim.

## What the adapter claims

For each of the 28 pilot instances (8 procurement + 12 scheduling + 8 pricing,
all Basic difficulty), it drives a scripted, gold-trajectory episode through
the REAL kernel scheduler (`aeread.shared_runner.scheduler.run_episode`) — not
a hand-wired call to the plugin's own `step` — with every period's terminating
submit call delegated to the pinned upstream scoring primitive
(`evaluate_alloc` / `is_valid_matching`+`get_blocking_pairs` /
`get_monopoly_prices`+`get_profits`) across a subprocess bridge, and reports
two separately-labelled measurement leaves per track (spec section 2), never
one blended number:

| Leaf | Verifier family | Units | Declared when |
|---|---|---|---|
| gate | `rule_constraint` | `pass` | always |
| objective | `objective_reference` | track-native (`workers_supported` / `blocking_pairs` / `profit_usd`) | only when the gate passes |

A recorded episode replays offline — zero further model calls, and (unlike
`tau3_retail`) zero re-timestamped state — reproducing the final FSM state
byte-for-byte and both leaves exactly, by folding the recorded tool calls back
through the real plugin's `step`, which independently re-executes each one
against the pinned bridge and hard-fails on any divergence.

## Evidence

**113 passed, 0 failed, 0 skipped**, the full econevals family test file set
plus `tests/test_shared_runner_smoke.py`, re-verified both with
`$AEREAD_ECONEVALS_BRIDGE_PYTHON`/`$AEREAD_ECONEVALS_UPSTREAM_ROOT` exported
and with neither exported (this workspace's `discover_bridge_python`/
`UPSTREAM_ROOT` both fall back to the same provisioned default paths either
way, so both runs are bridge-backed here and neither shows a skip; a machine
without that default provisioned would see the documented bridge-gated
skips instead, never a silent pass):

```bash
export AEREAD_ECONEVALS_BRIDGE_PYTHON=<bridges/econevals-venv path>
export AEREAD_ECONEVALS_UPSTREAM_ROOT=<upstream-econevals checkout path>
PYTHONPATH=src pytest \
  tests/test_econevals_cases.py tests/test_econevals_environment.py \
  tests/test_econevals_measurement.py tests/test_econevals_tools.py \
  tests/test_econevals_replay.py tests/test_shared_runner_smoke.py -q
# 113 passed in 142.33s (0:02:22)
```

Breakdown: cases 22, environment 29, measurement 30, tools 12, replay 10,
shared-runner smoke 10. The delta from the previous 107 (measurement 24) is
this migration's six new `EconevalsScorer.__call__`/leaf-policy tests
(`tests/test_econevals_measurement.py`); see "Leaf policy" above. The prior
delta from 101 (cases 21, environment 25, replay 9) was the second-reviewer
fix pass
(`docs/econevals_review_disposition.md`): a `conftest.py` marker-coverage
regression test in `test_econevals_cases.py`; four goldens (1, 2, 3, 5)
driven through the real `step()` path in `test_econevals_environment.py`;
and a bridge-required-during-replay regression test in
`test_econevals_replay.py`.

**Milestone 3 additions, specifically:**

- `harness.py` (`ScriptedEconevalsHarness`) drives full multi-period episodes
  through `run_episode` for all three tracks (`test_econevals_environment.py`'s
  three `test_*_full_episode_runs_through_the_real_kernel_scheduler` tests),
  each reaching a genuine `"max_periods"` termination — not an early stop the
  test manufactures. A fourth test seals the evidence store
  (`EvidenceStore.seal()`) and asserts the exact
  `tool_invocation_started`/`tool_invocation_succeeded` event pairs the
  scripted tool calls produced.
- `replay.py` reproduces one of those live episodes from a JSON-round-tripped
  record with a second, independent bridge/plugin: same final state
  byte-for-byte (`canonical_json_bytes` equal, not merely content-equivalent),
  same terminal record, same outcome, both measurement leaves recomputed
  identical to a direct `score_terminal_state` call on the original run's own
  final state. A tampered recorded tool result is rejected by `step`'s own
  cross-check (`RuntimeError: tool replay result differs...`), not silently
  absorbed by the replayer.
- Driving the plugin through the real scheduler for the first time (nothing
  in milestones 1–2 did; every prior test called `plugin.step()` directly)
  surfaced a real bug in this family's own code: `phases()` keyed
  `observation_schema_by_role`/`action_schema_by_role` by the seat id
  (`"agent"`) instead of the role (`"assistant"`) the scheduler actually
  indexes them by. Fixed directly (see `docs/econevals_adapter_spec.md`
  section 6's milestone-3 build notes); not filed to the ledger since it is
  this adapter's own code, not the shared kernel.

## What it costs to run

Each bridge call spawns a fresh subprocess (required by the procurement
global-RNG finding, spec section 1) that imports the pinned upstream checkout
from scratch. Measured this session: `procurement_evaluate` ~1.0s/call,
`pricing_profits` ~0.4s/call, `scheduling_validate`+`scheduling_blocking_pairs`
~0.2s/call combined. `test_econevals_cases.py`'s 28-instance corpus admission
sweep (two independent generations plus a reference computation per instance)
takes ~2 minutes end to end.

The pilot cases are pinned at the full upstream `num_attempts = 100` periods
per instance. A live 100-period episode would cost roughly 100 bridge
round-trips; the milestone-3 harness/replay tests instead run a test-scoped
`CaseManifest` copy with `pins.max_steps`/`episode.max_logical_actions`
shrunk to 2–3, keeping the REAL pinned `generated_instance`/`gold_optimum`
payload and REAL bridge calls for every period, with `content_sha256`
recomputed through the kernel's own `case_content_sha256` resolver (never
hand-typed). This is a test-runtime optimization only — it does not touch the
checked-in pilot corpus, the scheduler path, or any scoring rule.

## Known limits, stated rather than implied

- **The five QC Gate-2 goldens now have `step()`-level coverage but are not
  yet individually sealed and offline-replayed.** `docs/econevals_review_disposition.md`
  finding 2: each golden is now driven through a real `parse_action`/
  `legal`/`step` period (`tests/test_econevals_environment.py`), not merely
  a hand-typed `attempt` dict fed to the scorer, but spec section 5's
  literal "replay each of the 5 goldens from its sealed episode record" is
  not yet wired up for all five — `tests/test_econevals_replay.py` replays
  one live pricing episode end to end, and the same already-proven
  machinery would need to be pointed at each golden's own scripted
  trajectory. Left for a follow-up pass.
- **No mutation testing was performed this milestone.** `tau3_retail`'s own
  status doc reports two coverage gaps mutation testing found; the same
  exercise has not been run against this family's harness/replay/step
  cross-check paths, so an equivalent claim cannot be made here. Worth doing
  before this adapter is relied on for anything beyond integration-gate
  status.
- **The e2e/replay tests exercise pricing most, procurement and scheduling
  once each.** Three tracks × one live-episode/replay pair each is what spec
  section 5's "e2e" bullet asks for; it is not equivalent to running all 28
  pilot instances through the full period loop (that remains Gate 1's
  corpus-admission sweep, which does not itself drive the scheduler).
- **Replay's byte-identical claim is specific to this family's state shape.**
  It holds because econevals's FSM state carries no wall-clock or
  otherwise-nondeterministic field anywhere — this is not a general kernel
  guarantee (`tau3_retail`'s own state cannot make the same claim, because
  upstream's message models re-timestamp on every `model_validate`).
- **Determinism was checked within one process/run, not across machines or
  Python versions.** The bridge interpreter's own pinned dependency versions
  (spec section 3) are the only portability control in place.
- Every limit already stated in `docs/econevals_adapter_spec.md` section 6
  (Basic-only procurement scope, pricing's tolerance-based optimum, the pilot
  being an integration gate rather than a population estimate, the
  `upstream_task_id`/tolerance schema gaps, scheduling's existence-only
  optimum) still applies unchanged; this document does not repeat them.
