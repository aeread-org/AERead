# govsim adapter — status

Branch `zeyu/govsim-adapter`. Last verified 2026-09-02.

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

**Suite: 98 passed, 0 failed, 0 skipped** running the entire family test
file set (`tests/test_govsim_cases.py`, `tests/test_govsim_environment.py`,
`tests/test_govsim_measurement.py`, `tests/test_govsim_replay.py`) plus
`tests/test_shared_runner_smoke.py`, with `$AEREAD_GOVSIM_BRIDGE_PYTHON`
pointed at the provisioned `bridges/govsim-venv/bin/python` — every
bridge-gated fidelity test (the five QC Gate-2 goldens against the real
upstream checkout, the gini parity check, both replay episodes) actually
ran, none merely skipped past. Without the bridge set, the same command
reports 80 passed / 18 skipped — the skips are exactly the bridge-gated
tests above, each with a `pytest.skip` reason naming
`$AEREAD_GOVSIM_BRIDGE_PYTHON` and `tools/govsim_bridge/provision.sh`, never
a silent pass.

```bash
export AEREAD_GOVSIM_BRIDGE_PYTHON=<bridges/govsim-venv path>
pytest tests/test_govsim_cases.py tests/test_govsim_environment.py \
       tests/test_govsim_measurement.py tests/test_govsim_replay.py \
       tests/test_shared_runner_smoke.py
```

## What it costs to run

Each bridge call spawns a fresh subprocess that replays `reset(seed=...)`
plus the full ordered action history to date (O(n) upstream `step()` calls
per bridge call, not O(1) — see `docs/govsim_adapter_spec.md` section 7),
so cost grows with episode length. The full bridge-required run above (98
tests, including two full episodes driven live and then independently
replayed, plus every gini-parity and golden-scenario bridge call) took
**~146s wall-clock**. No persistent bridge daemon is used; the same
per-call isolation tradeoff `tau2_bridge.py` makes is repeated here
deliberately, for the same reason — no state can leak between calls through
a long-lived interpreter.

## Known limits, stated rather than implied

- **Spec section 5's parity file, `tests/test_govsim_parity.py` (P1–P3), is
  not built in this milestone.** Only P4 (vendored `gini()` vs. upstream's
  own, byte-for-byte) is covered, in `tests/test_govsim_measurement.py`.
  P1 (import-determinism double-run), P2 (adapter-vs-raw-upstream
  equivalence outside the kernel), and P3 (independent regeneration/collapse
  recomputation cross-checked against upstream's own recorded
  `internal_global_state`) remain open follow-up work. This milestone's
  replay tests are a different, real check — they prove the adapter
  reproduces *itself* deterministically, not that the adapter's kernel path
  agrees with a raw, kernel-free upstream run.
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

## Ledger

Defects/limitations found in the shared kernel or environment during this
work (not in this adapter's own code) are recorded in
`ledger_entries/govsim.md`, not here.
