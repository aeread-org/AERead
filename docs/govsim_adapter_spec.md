# Implementation Specification — `govsim` adapter for the AERead shared-runner kernel

**Scope.** Wrap GovSim's three common-pool-resource scenarios (fishing, sheep pasture,
pollution — upstream [`giorgiopiatti/govsim`](https://github.com/giorgiopiatti/govsim), pinned
`1d11adf047b24fa2ba0d44a1d4931015ea2e5210`, MIT) inside the AERead kernel, driven by
AERead-authored **scripted** policies (`sustainable_v1`, `greedy_v1`, `mixed_v1`) — never
upstream's `persona_v3`/pathfinder LLM cognition stack, not imported, bridged, or reimplemented
in any form. "govsim" is AERead's family name for this pinned import; "upstream" always means
the govsim checkout at that commit.

**Governing facts** (verified in recon; do not re-derive):
- All three scenarios share one base class, `ConcurrentEnv`
  (`simulation/scenarios/common/environment/concurrent_env.py`), overridden per scenario only
  for prompt text. Resource/regeneration/collapse **arithmetic is identical across all
  three** — only the framing differs (tons of fish / hectares of grass / % unpolluted water).
- Despite the class name, `ConcurrentEnv` is a **PettingZoo AEC (turn-based) environment**:
  `step()` accepts one action from `self.agent_selection` at a time via an `agent_selector`.
  "Concurrent" harvesting means each agent's observation hides every other agent's
  `wanted_resource` until the round's last agent has acted, at which point `_assign_resource()`
  runs once — a noninterference property of the *observations*, matching the kernel's
  `mode="simultaneous"` contract even though upstream expresses it as N sequential calls.
- Confirmed identical across all three scenarios' `*_baseline_concurrent.yaml`: `num_agents=5`,
  `initial_resource_in_pool=100`, `max_num_rounds=12`, `harvesting_order=concurrent`,
  `assign_resource_strategy=stochastic`, `inject_universalization=false`.
- Regeneration (`concurrent_env.py:434-444`, once per round after the last agent's "home"
  step): `resource_in_pool = min(initial_resource_in_pool, resource_in_pool * 2)`;
  `sustainability_threshold = (resource_in_pool // 2) // num_agents`, both from the
  **regenerated** pool. Collapse test: `resource_in_pool < 5 or num_round >= max_num_rounds`.
  The threshold is **advisory only** — nothing rejects or clamps a harvest above it;
  `_assign_stochastic`/`_assign_proportional` just allocate from whatever remains.
- No pydantic or Hydra composition is needed at runtime (`hydra-core` only backs the unused
  `simulation.main` entrypoint; we construct `omegaconf.DictConfig` directly). The brief's
  assumed Python 3.11.5 pin was not found in the checkout (no `.python-version`; the ROCm
  Dockerfile targets `py3.10`) — treated as unverified, not repeated as fact.
- `simulation.persona.common` (the plain-class file holding `PersonaAction`,
  `PersonaActionHarvesting`, `PersonaActionChat`, `PersonaEvent`, `PersonaIdentity` — zero
  third-party imports) is a submodule of the `simulation.persona` **package**, whose
  `__init__.py` unconditionally imports the full pathfinder cognition stack
  (`sentence_transformers`, `wandb`, `act/converse/perceive/plan/...`) — see
  `ledger_entries/govsim.md` and §3.2. No bug equivalent to tau3's `modify_pending_order_items`
  was found, so §5 has no bug-preservation test (see §6).

## 1. Pinned source and corpus enumeration (QC Gate 1)

| Field | Value |
|---|---|
| repository | `giorgiopiatti/govsim` |
| commit | `1d11adf047b24fa2ba0d44a1d4931015ea2e5210` |
| license | MIT |
| scenarios wrapped | `fishing`, `sheep`, `pollution` (all via `*ConcurrentEnv`, not `*PerturbationEnv`) |
| modules executed | `simulation/scenarios/common/environment/concurrent_env.py`, one `env.py` per scenario, `simulation/persona/common.py` |
| modules never imported | `simulation/persona/{persona,cognition,embedding_model}.py`, `pathfinder/`, `subskills/`, any `PerturbationEnv` |

GovSim ships **no discrete upstream task list** (unlike tau2-bench's 114 JSON records) — only
Hydra experiment YAML configs describing one canonical starting condition per scenario. The
case corpus is therefore **procedurally generated**, in the style of `housing_v1` (`cases/
README.md`: "Deterministic generated worlds; no static JSON fixtures"), not imported like
`tau3_retail`.

Tonight's planned corpus: **3 scenarios × 3 scripted policies = 9 case cells**
(`fishing`/`sheep`/`pollution` × `sustainable_v1`/`greedy_v1`/`mixed_v1`), each one fixed
`world_seed`. Case id: `govsim.<scenario>.<policy>.<world_seed>`, e.g.
`govsim.fishing.sustainable.0` — dot-separated, passes `is_exportable_id` (no colon).

Each case's `payload` freezes the exact upstream `cfg` fields plus our policy assignment —
there is no upstream per-task file to hash, so the **whole manifest is the content boundary**:

```json
{
  "upstream_repo": "govsim", "upstream_commit": "1d11adf047b24fa2ba0d44a1d4931015ea2e5210",
  "scenario": "fishing",
  "env_cfg": {
    "num_agents": 5, "initial_resource_in_pool": 100, "max_num_rounds": 12,
    "harvesting_order": "concurrent", "assign_resource_strategy": "stochastic",
    "inject_universalization": false
  },
  "personas": ["John", "Kate", "Jack", "Emma", "Luke"],
  "policy_assignment": {"persona_0": "sustainable_v1", "persona_1": "sustainable_v1", "...": "..."},
  "world_seed": 0
}
```

`content_sha256` is computed exactly as `tau3_retail`/`housing_v1` do it — via
`aeread.shared_runner.resolver.case_content_sha256(manifest)` (canonical JSON,
`content_sha256` zeroed before digesting), no bespoke hash. A `pins.json` alongside the corpus
records `upstream_commit`, the per-scenario `env.py` source hashes, and the bridge venv's
resolved `numpy`/`pandas`/`omegaconf`/`pettingzoo` versions (§3), so a matching commit checkout
cannot silently hide a different dependency resolution.

Stratum note: `stochastic` assignment consumes upstream's own `np.random.RandomState` seeded
in `reset(seed=...)`; `world_seed` is that seed — deterministic and sufficient for replay
(§5), not yet verified against a live bridge run (spec-time only, no adapter code has run).

## 2. Verifier declaration

Per `docs/verifier_taxonomy.md` and validated against the live `_REFERENCE_KINDS` /
`_REFERENCE_SCOPE` enums in `src/aeread/shared_runner/measurement.py` (not just the doc
prose). Per `docs/problem_bound_case_audit.md` row **P06** ("GovSim / Cooperate or Collapse
… `baseline_only`; survival/efficiency/equality endpoints are not solved policies. A natural
maximum score is not a certified policy upper bound."), **no `objective_reference` leaf is
declared** — survival months, total harvest, and equality are declared purely `comparative`,
never framed as an approach to a bound.

| Leaf | Verifier family | Reference kind | Evaluation class | Input scope |
|---|---|---|---|---|
| `govsim_no_collapse` | `rule_constraint` | `state_invariant` | `deterministic` | `trajectory` |
| `govsim_threshold_adherence` | `rule_constraint` | `constraint_satisfaction` | `deterministic` | `trajectory` |
| `govsim_survival_months` | `comparative` | `baseline_delta` | `deterministic` | `terminal_state` |
| `govsim_total_harvest` | `comparative` | `baseline_delta` | `deterministic` | `terminal_state` |
| `govsim_equality_gini` | `comparative` | `baseline_delta` | `deterministic` | `terminal_state` |

`govsim_no_collapse`: pass iff `internal_global_state["resource_in_pool"]` never drops below 5
before `num_round == max_num_rounds`, read from the recorded per-round trace and never
re-derived independently of upstream's own state (§5, P3). A **diagnostic constraint, not an
admission gate** — a collapsed episode is a valid, scoreable trial (taxonomy §4: "a hard gate
... should not silently convert a normative tradeoff into invalidity").

`govsim_threshold_adherence`: per round, whether each agent's `wanted_resource` exceeded that
round's `sustainability_threshold` — a vector of pass/fail per agent-round, never one rate.

`govsim_survival_months`/`total_harvest`/`equality_gini`: `comparison_baseline =
govsim_sustainable_v1` (an AERead-authored reference policy, not an upstream oracle);
`bound_status: baseline_only` in the family manifest, `optimum_upper_bound` deliberately
absent. `equality_gini` vendors upstream's 10-line `gini()` (`plots.py:669-681`) verbatim with
a provenance header — not imported, since `plots.py` needs `plotly`/`statsmodels`/`lifelines`
and multi-run wide dataframes, a different shape than one episode's harvest vector.
`survival_months` mirrors `compute_survival_months_stats`'s rule (first round index+1 where
the value `<5`, else `max_num_rounds`; `plots.py:14-56`) computed from the single episode's own
trace for the same reason.

```yaml
leaf_id: govsim_no_collapse
verifier: {verifier_family: rule_constraint, evaluation_class: deterministic,
  reference: {reference_kind: state_invariant, input_scope: trajectory,
    implementation: {package: aeread_families.govsim.measurement, commit: ...}}}
estimand: {input_scope: trajectory, direction: none, units: pass}
```

## 3. Adapter boundary

Mirrors `docs/refund_external_benchmark_integration.md` §4.

**Upstream remains authoritative for:**
- `ConcurrentEnv.reset`/`step` state transitions, phase sequencing
  (`lake→pool_after_harvesting→restaurant→home`), and the `agent_selector` cursor;
- the regeneration formula, `sustainability_threshold` recomputation, and the collapse test;
- `_assign_stochastic`/`_assign_proportional` resource-allocation arithmetic;
- scenario prompt-text construction (unused by scripted policies, but still upstream's).

**AERead owns:**
- the three scripted policies standing in for personas (never `persona_v3`);
- the kernel-facing phase/seat mapping and its translation into upstream `step()` calls;
- the bridge process, case corpus authoring, receipts/evidence, measurement leaves/scorers,
  and the parity harness.

### 3.1 Phase graph (Mode C simultaneous, mirroring `housing_v1`'s `contact/respond/commit`)

```
harvest  mode=simultaneous, seats=persona_0..persona_4
         -> 2N upstream env.step() calls/round (lake, then pool_after_harvesting),
            agent_selector order; peer wanted_resource hidden until the bundle closes
discuss  mode=single, seat=persona_0 (fixed "spokesperson", matches post-harvest cursor)
         -> 1 env.step(PersonaActionChat(conversation=[])) call — no cheap talk in v1
            (upstream's own `language_nature: none` shape is the precedent; §6)
reflect  mode=simultaneous, seats=persona_0..persona_4, housekeeping only
         -> N env.step(PersonaAction(location="home")) calls; the last triggers
            upstream's regeneration + collapse-check + threshold recompute
-> loop to harvest, or terminal when upstream's own termination flag fires
```

### 3.2 Bridge design

The project venv lacks `pettingzoo`, `pandas`, and `omegaconf` (its `numpy`/`pydantic` are
moot — neither `ConcurrentEnv` nor `env.py` imports pydantic). Per the ground rules, never
install into the project venv: provision an isolated venv at `bridges/govsim-venv`, mirroring
`tools/tau2_bridge/provision.sh` — `tools/govsim_bridge/provision.sh` (default target
`bridges/govsim-venv`), a `requirements.txt` pinning `numpy`/`pandas`/`omegaconf`/`pettingzoo`,
and an import-and-verify smoke check. Execution goes through a **subprocess driver**
(`src/aeread_families/govsim/govsim_bridge_driver.py`, mirroring `tau2_bridge_driver.py`), not
an in-process `sys.path` merge — rejected because it would let the bridge venv's `numpy`
collide with the project's own already-imported `numpy` in the same interpreter, a silent
version-shadowing risk. Unlike tau2-bench, this bridge needs no different Python **version**
(govsim runs fine under 3.11) — only different site-packages — but the subprocess isolation
is identical, with the same env-var naming: `AEREAD_GOVSIM_UPSTREAM_ROOT`,
`AEREAD_GOVSIM_BRIDGE_PYTHON`, `AEREAD_GOVSIM_BRIDGE_REQUIRED`.

**Package-init workaround** (see `ledger_entries/govsim.md`): before importing
`simulation.scenarios.<scenario>.environment.env`, the driver installs stub package objects
into `sys.modules` for `simulation` and `simulation.persona` (empty `types.ModuleType`s with
`__path__` pointed at the real upstream directory), so importing `simulation.persona.common`
loads only that 157-line file, never the real `simulation/persona/__init__.py` — a controlled
avoidance of an unrelated sibling module's import graph, not a reimplementation of upstream's.

## 4. Five QC Gate-2 goldens

| Category | Construction | Expected outcome |
|---|---|---|
| successful | `fishing`, `sustainable_v1` for all 5 seats, `world_seed=0` | Runs all 12 rounds; `govsim_no_collapse=pass`; high `survival_months` (=12) |
| valid-but-poor | `fishing`, `greedy_v1` for all 5 seats, `world_seed=0` | Every action legal and well-formed, env executes cleanly, but drives `resource_in_pool<5` well before round 12; `govsim_no_collapse=fail`, low `survival_months`, positive `total_harvest` |
| invalid-unauthorized | During the `discuss` phase, submit a `PersonaActionHarvesting` from a seat that is not `persona_0` (not the phase's eligible actor) | Adapter's `legal()` hook rejects before any upstream `step()` call — upstream itself only has a bare `assert action.agent_id == self.agent_selection`, which would crash the process rather than return a typed result; the adapter must intercept first |
| malformed-operational | A well-turned, correctly-timed action whose `location` field is wrong (e.g. `"restaurant"` submitted during the `lake` phase) | Upstream's own `assert action.location == self.POOL_LOCATION` fires inside the bridge subprocess; the adapter must catch the resulting error and record a typed operational failure (`outcome_unknown`, per `shared_runner_portability_contract.md` §4), never crash the harness or silently promote it to a scored zero |
| degenerate-reference | `fishing`, `num_agents=1`, `sustainable_v1` | The common-pool dilemma structurally vanishes (no peer to free-ride against; `sustainability_threshold=(pool//2)//1` is just "harvest at most half"); `comparison_baseline` against `greedy_v1` is uninformative by construction and must be flagged, not reported as a clean win/loss |

## 5. Test plan

**Structural (run everywhere, no bridge needed):** `tests/test_govsim_cases.py` (manifest
construction, `content_sha256` determinism), `tests/test_govsim_environment.py` (phase graph,
seat eligibility, the goldens' legality paths), `tests/test_govsim_measurement.py` (leaf
construction, vendored `gini()` vs. hand-computed values).

**Replay (needs the bridge; skip-with-marker convention identical to
`tests/test_tau3_retail_replay.py`):** `tests/test_govsim_replay.py` — replays a recorded
scripted-action sequence through the bridge subprocess a second time, asserts every per-round
`resource_in_pool`/`collected_resource` value and the terminal outcome match the sealed
episode record exactly, and recomputes all five leaves. Zero network calls — the subprocess is
local IPC, the same standing `tau2_bridge` already has in a "provider-free" suite.

**Parity (needs the bridge):** `tests/test_govsim_parity.py`.
- **P1 — Import determinism.** Corpus generator run twice produces byte-identical 9 manifests.
- **P2 — Adapter/raw-upstream equivalence.** Drive one scripted-action sequence two ways: (a)
  through the kernel's phase graph and `ToolRuntime`-mediated `step()` calls, (b) directly
  against a raw upstream `ConcurrentEnv` with no kernel involved. Assert identical
  `resource_in_pool`, `collected_resource`, and termination trace every round — GovSim has no
  single "evaluate" oracle like tau2's `evaluate_simulation`, so this is the correct parity
  target, not a forced fit of tau3's shape onto a different upstream.
- **P3 — Regeneration/collapse cross-check.** Independently recompute
  `min(initial_resource_in_pool, 2*pool)` and `<5 or round>=max` from the recorded trace and
  diff against upstream's own recorded `internal_global_state` — never trust our arithmetic
  without this diff.
- **P4 — Gini parity.** The vendored `gini()` matches upstream's function (called through the
  bridge) byte-for-byte on the same sample arrays, negative-shift and NaN-removal included.

## 6. Stated limits

- Scripted policies only — no `persona_v3`/pathfinder LLM cognition wrapped tonight, and none
  of its prompt/system-prompt-version machinery is exercised.
- `PerturbationEnv` variants, `subskills/`, and multi-LLM (`multiple_llm.yaml`) configs are
  out of scope.
- No free-form multi-turn negotiation this milestone — every scripted policy submits an empty
  conversation, upstream's own supported "no language" shape (`language_nature: none`). Real
  cheap-talk is a follow-up and, per `ledger_entries/govsim.md`, may need a kernel `PhaseSpec`
  mode that does not exist yet (multi-turn-composed-then-atomically-submitted).
- No certified policy upper bound exists for any comparative leaf (P06); they are
  baseline-only comparisons against AERead's own scripted policies, never a solved optimum — a
  high `survival_months` must never be reported as evidence of saturation.
- Corpus tonight is 9 cells (3 scenarios × 3 policies, one world seed each), not the paper's
  full grid (persona-name variants, universalization on/off, perturbations, multi-seed
  statistics) — a follow-up, mirroring how the tau3 pilot preceded its 114-task expansion.
- No upstream bug equivalent to tau3's `modify_pending_order_items` was found; if one surfaces
  during implementation, add a P5-equivalent bug-preservation test then.

## 7. Milestone 1 implementation notes (cases + environment; reality-forced deviations)

This section records where building `src/aeread_families/govsim/` against the plan above
forced a concrete decision the earlier sections left open, per the rule that reality-forced
deviations are recorded in the spec, not silently improvised.

**Bridge protocol is per-call stateless replay, not raw state passing.** §3.2 said the
subprocess driver would "mirror `tau2_bridge_driver.py`" without settling the wire protocol.
tau2's bridge passes `db` (a plain dict that fully describes `RetailDB`) in and out of a
stateless per-call subprocess. Upstream's `ConcurrentEnv` cannot be handed back and forth the
same way: `internal_global_state["next_time"]` holds `datetime` values and
`internal_global_state["action"]` holds live `PersonaAction` instances, neither JSON-safe --
and the kernel's own `TransitionResult.state` must be canonical-JSON-freezable
(`scheduler.py`'s `_freeze`/`_content_hash`, which call `canonical_json_bytes`). The
implemented design (`govsim_bridge.py`/`govsim_bridge_driver.py`) instead sends the complete
ordered action history for the episode on every call; the driver subprocess replays
`reset(seed=...)` followed by every recorded action, in order, then applies the newest one.
Verified during implementation (not merely assumed): upstream's own `np.random.RandomState` is
seeded once by `reset` and consumes draws in the exact same call sequence on every replay (its
`get_state()`/`set_state()` round-trip byte-for-byte after a JSON round-trip too, confirmed by
direct probe, though the shipped design does not need that path since it never serializes
`RandomState` at all -- replay reproduces its draws for free). This keeps the same per-call,
no-daemon subprocess discipline as `tau2_bridge.py` (one subprocess, one call, complete state in
and out) at the cost of O(n) upstream `step()` calls replayed per bridge call instead of O(1); a
full 12-round, 5-agent episode is ~192 kernel-level `step()` calls and took ~108s end-to-end
against the real bridge during verification -- noticeable, not disqualifying for this milestone,
and a documented follow-up (an O(1) design round-tripping `RandomState.get_state()` plus
hand-serialized `datetime`/`PersonaAction` fields) if the replay/parity milestone's wall-clock
cost becomes a bottleneck. See `ledger_entries/govsim.md` for the related kernel-contract
observation this design sidesteps (no plugin teardown hook exists for a daemon-shaped
alternative).

**Operational-failure handling.** §4's malformed-operational golden ("the adapter must catch
the resulting error and record a typed operational failure... never crash the harness") named
the required behavior but not the mechanism. The kernel's `outcome_unknown` machinery
(`shared_runner_portability_contract.md` §4) is wired through `ToolRuntime`/`ToolPort`, which
this family does not use (native phase actions, no external tool loop, matching `housing_v1`).
Implemented instead: a new declared termination reason, `operational_failure` (alongside
`collapse_or_horizon`, which covers upstream's single `resource_in_pool < 5 or num_round >=
max_num_rounds` test -- a collapsed episode is a valid, scoreable trial, not a distinct failure
mode). `GovsimPlugin.step` catches `GovsimActionError` from the bridge, sets this reason, and
returns a normal `TransitionResult` with `next_phase_id=None` rather than raising (a raised
exception from `step()` is a hard `SchedulerContractError`, not a graceful outcome, per
`scheduler.py`'s `_step` wrapper). `outcome()` reports `outcome_status: "outcome_unknown"` for
this reason and `"known"` otherwise.

**Phase logical-action budget is per-phase, whole-episode, and distinct from the bridge's own
per-round action-dict count.** `scheduler.py`'s `phase_action_counts` accumulates across every
instance of a phase over the whole episode, never resetting per round (see
`ledger_entries/govsim.md`), so `PhaseSpec.max_logical_actions` for `harvest`/`reflect` is
`num_agents * max_num_rounds` and for `discuss` is `1 * max_num_rounds` -- three different
values, not one shared constant the way `tau3_retail`'s two phases share `max_steps`. This is
the kernel-level logical-action count (one per seat per phase-instance); it is distinct from
the bridge-level action-dict count `step()` submits per call (`2*num_agents` for harvest -- N
real quantities plus N `pool_after_harvesting` dummies -- `1` for discuss, `num_agents` for
reflect), which is `3*num_agents+1` per round, not `2*num_agents+1`. `cases.py`'s
`episode.max_logical_actions` (the case-level budget) uses the kernel-level total,
`(2*num_agents+1) * max_num_rounds`.

**Corpus location and format.** Cases are committed (not purely code-generated at runtime like
`housing_v1`) under `cases/govsim/v1/`: 9 case files (`govsim.<scenario>.<policy>.<world_seed>
.json`), `pins.json`, and `corpus_manifest.json` (an index of all 9 case ids, mirroring
`tau3_retail`'s `pilot_manifest.json` but covering the whole corpus rather than a subset, since
govsim has no train/test split). `pins.json`'s `bridge_versions` field is populated only when
`cases.py`'s CLI is run with `--bridge-python`; otherwise it records an explicit
`bridge_versions_unavailable_reason`, mirroring `tau3_retail`'s identical convention for
`tool_schema_sha256`.

**`docs/benchmark_qc.md`.** The QC Gate 1/2 terminology this spec uses is self-defined within
this file (section 1 and section 4 respectively); the referenced `docs/benchmark_qc.md` does
not exist on this branch or on `main` as of this milestone (it exists only on an unmerged
sibling branch/commit -- see `ledger_entries/govsim.md` for the exact commit and reconciliation
note). Nothing in this milestone depends on that file's contents beyond the two section
headings already defined here.

**Scorer deferred.** Per this milestone's scope, `GovsimPlugin.build_scorer` raises
`NotImplementedError` rather than returning a stub scorer; it exists only to satisfy
`PluginRegistry.register`'s callable-hook check (`registry.py`'s
`REQUIRED_FAMILY_PLUGIN_HOOKS`), which checks `callable(...)`, never invokes the hook, at
registration time. `measurement.py` (the five leaves in section 2) lands in a later milestone.
