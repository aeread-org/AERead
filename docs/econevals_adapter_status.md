# econevals adapter — status

Branch `zeyu/econevals-adapter`. Last verified 2026-09-02.

A second-reviewer fix pass ran against `docs/econevals_review_claude.md`
(`docs/econevals_review_codex.md` was never produced) this session; see
`docs/econevals_review_disposition.md` for the per-finding verification and
fix record. Nothing found was a kernel/runner defect, so no
`ledger_entries/econevals.md` entry was added on this pass.

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

**107 passed, 0 failed**, the full econevals family test file set plus
`tests/test_shared_runner_smoke.py`:

```bash
PYTHONPATH=src pytest \
  tests/test_econevals_cases.py tests/test_econevals_environment.py \
  tests/test_econevals_measurement.py tests/test_econevals_tools.py \
  tests/test_econevals_replay.py tests/test_shared_runner_smoke.py -q
# 107 passed in 154.80s (0:02:34)
```

Breakdown: cases 22, environment 29, measurement 24, tools 12, replay 10,
shared-runner smoke 10. The delta from the previous 101 (cases 21,
environment 25, replay 9) is the second-reviewer fix pass
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
