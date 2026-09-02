# Implementation specification — `econagent` adapter for the AERead shared-runner kernel

**Scope.** Wrap EconAgent (ACL 2024 main; arXiv 2310.10436; `tsinghua-fib-lab/ACL24-EconAgent`
pinned at `bfada09`) — an LLM-driven macroeconomic simulation built on a copied `ai_economist`
foundation — as family `econagent_v1`. "econagent" is AERead's family name for this pinned
import; "upstream" always means the checkout at `bfada09`. Scope for this pass: 2-3 pinned
scenario configs at reduced scale (10 agents x 12 months) gated on parity against a directly
invoked upstream engine, never a paper reproduction of the full 100-agent x 240-month run.

**Governing facts** (verified in recon; do not re-derive):
- `simulate.py` has no module-level LLM import. `simulate_utils.get_completion` does
  `import openai` lazily, inside the function body, called only from `gpt_actions`, which
  `main()` reaches only when `policy_model=='gpt'`. The **`complex` policy path**
  (`simulate_utils.complex_actions`) is pure `numpy` arithmetic over wealth/income/price —
  no network, no LLM, no API key, ever. This adapter drives the `complex` path exclusively.
- `config.yaml` is an RLlib training config; only its `env` block is consumed by
  `foundation.make_env_instance(**env_config)`. Relevant fields: `scenario_name:
  one-step-economy`, `n_agents`, `episode_length` (months), `period: 1`,
  `components: [SimpleLabor, PeriodicBracketTax, SimpleConsumption, SimpleSaving]`,
  `PeriodicBracketTax.tax_model: us-federal-single-filer-2018-scaled` (7 brackets, scaled
  2018 US federal single-filer schedule), `isoelastic_etas: [0.5, 0.5]`.
- `data/profiles.json` is **not** 100 profiles; it is four sampling pools upstream draws
  from to assign each agent's endogenous fields: `Age` (200 ints), `Name` (160 strings),
  ten income-bracket keys (`"0-2454"` … `"52370-10000000"`, 10 job titles each = 100 titles),
  and `City` (10 strings). The spec below digests the pool, not a per-agent roster.
- `ai_economist/foundation/*` carries verified Salesforce **BSD-3-Clause** file headers
  (`# Copyright (c) 2020/2021, salesforce.com, inc. ... SPDX-License-Identifier:
  BSD-3-Clause`); the upstream repo root has **no LICENSE file** and no license notice on
  `simulate.py`/`simulate_utils.py`/`config.yaml`. Because the wrapping repo's own license
  posture for the top-level files is unstated, this adapter is **import-only**: no upstream
  file, in whole or excerpted, is ever copied into this repository.
- `ai_economist.foundation` needs only `numpy`, `scipy`, and `lz4` to import (`foundation/
  utils.py` does module-level `import lz4.frame`; no `gym`/`tensorflow`/`ray` import
  anywhere under `foundation/`; those only back `config.yaml`'s unused RLlib training
  blocks). `simulate_utils.py` additionally needs `pandas`, `seaborn`, `matplotlib`,
  `scipy`, `python-dateutil` at module scope (used for plotting/logging only, not by
  `complex_actions`, but they still execute on import). The project venv
  (Python 3.11.3, `numpy` 2.4.6, `scipy` 1.17.1) is missing `lz4`, `pyyaml`, `fire`,
  `pandas`, `seaborn`, `matplotlib`, `python-dateutil` — confirmed via direct import probe.
  Per ground rules, none of these may be installed into the project venv, so an **isolated
  bridge venv** is required — not for a Python-version mismatch (upstream declares none),
  purely for package isolation.

---

## 1. Pinned source and corpus enumeration (QC Gate 1)

| Field | Frozen value |
|---|---|
| repository | `tsinghua-fib-lab/ACL24-EconAgent` |
| commit | `bfada09` |
| entry points read | `simulate.py`, `simulate_utils.py` |
| engine | `ai_economist/foundation` (copied foundation, BSD-3-Clause per-file) |
| corpus | `config.yaml` (env block) + `data/profiles.json` (sampling pools) |
| upstream license posture | no root LICENSE; embedded `foundation/*` files are BSD-3-Clause; import-only, never vendor |

There is no upstream task file to enumerate — the "corpus" for this family is a small,
declared set of **scenario configurations**, each a deterministic derivation of
`config.yaml`'s `env` block plus a `world_seed`. Gate 1 digests the two source artifacts
and the declared scenario list rather than per-task records:

```yaml
econagent_pins:
  upstream_repo: tsinghua-fib-lab/ACL24-EconAgent
  upstream_commit: bfada09
  config_yaml_sha256: <sha256 of upstream config.yaml, byte-exact>
  profiles_json_sha256: <sha256 of upstream data/profiles.json, byte-exact>
  bracket_schedule: us-federal-single-filer-2018-scaled   # read from config, not assumed
  policy_model: complex                                   # this adapter never sets 'gpt'
```

**Pinned scenarios for this pass** (case ids obey the repo's `_ID_RE` grammar — lower-case,
`[a-z0-9_.-]`, no colons):

| `case_id` | `n_agents` | `episode_length` (months) | Purpose |
|---|---|---|---|
| `econagent.pilot.small10x12.seed0` | 10 | 12 | primary parity + goldens target |
| `econagent.pilot.small10x12.seed1` | 10 | 12 | second world seed, same shape |
| `econagent.pilot.tiny4x6.seed0` | 4 | 6 | fast-running smoke/degenerate-edge case |

The full paper configuration — `n_agents=100`, `episode_length=240` — is **declared but not
run**: recorded in the manifest as `scenario_id: econagent.full.baseline100x240`,
`review_status: not_run`, so the corpus enumeration is complete even though only the three
reduced scenarios above are executed and gated this pass.

**Content digest.** The importer (`cases.py`) hashes `config.yaml` and `data/profiles.json`
byte-exact (no `yaml.safe_load` round-trip before hashing — a re-serialization would hide a
formatting-only upstream change), and independently hashes the *resolved* `env` sub-mapping
actually passed to `make_env_instance`, since only that slice is causally relevant. All
three scenarios embed the same two source digests; only `n_agents`/`episode_length`/
`world_seed` vary per case. Because there are only three declared scenarios (plus one
declared-not-run), Gate 1's duplicate/near-duplicate and split-disjointness checks degrade
to: assert the three ids are distinct, assert no two share a `world_seed`, and record the
small-corpus size explicitly rather than silently treating it as adequate for a saturation
claim (none is made — see §6).

## 2. Verifier declaration (per `docs/verifier_taxonomy.md`)

EconAgent has no upstream reward or task-success criterion at all — `simulate.py` never
scores an episode; it only dumps `dense_log`. There is nothing to reproduce as a canonical
score. AERead therefore declares a vector, all diagnostic or admission-layer, with **no
`objective_reference` and no optimum claim of any kind**:

| Estimand | Semantic verifier family | Reference kind | Claim |
|---|---|---|---|
| `econagent_budget_identity` | `rule_constraint` | `state_invariant` | Per-agent, per-step: `inventory_coin[t] == inventory_coin[t-1] + labor_income - tax_paid + lump_sum - consumption_spend + saving_interest` (all six terms read from the executed upstream state/dense_log, never recomputed independently). Deterministic leaf; violation is an adapter/bridge bug, not a policy failure. |
| `econagent_tax_bracket_arithmetic` | `rule_constraint` | `constraint_satisfaction` | `tax_paid` for each agent-month equals upstream's own bracket computation over the config-declared 7-bracket US-2018-scaled schedule, checked by re-invoking upstream's `PeriodicBracketTax` component method on the recorded income — never a reimplemented piecewise formula. |
| `econagent_macro_trajectory` | `comparative` | `baseline_delta` (mode: `descriptive`/`baseline_only`, no comparator required for this pass) | GDP-proxy (aggregate consumption), price level, and unemployment-proxy (fraction with `job == "Unemployment"`) time series. `objective_value_only`-style native numbers **explicitly not wrapped in `objective_reference`** — there is no declared optimum, no bound, no headroom. Diagnostic only. |
| replay/hash/admission surface | `measurement_validity` | n/a | schema legality, bridge-call integrity, before/after state hashes, deterministic replay. |

`econagent_macro_trajectory` is intentionally **not** given an `objective_reference` family
even though it looks numeric: per §5 of the taxonomy, an objective verifier requires a
feasible policy class, a declared optimum or certified bound, and a comparator, none of
which EconAgent's upstream defines. Presenting GDP/price/unemployment as anything but
`baseline_only` descriptive diagnostics would misclassify a simulation output as an
optimality claim — this is the one framing error this spec must not make.

`composition_kind` is `vector`; no weighted scalar is produced. The two `rule_constraint`
leaves are `hybrid_gate`-eligible (a budget-identity violation should invalidate the episode
before any diagnostic is read), but no gate is currently wired past logging the violation —
recorded as a stated limit (§6).

## 3. Adapter boundary (mirrors `refund_external_benchmark_integration.md` §4)

Upstream remains authoritative for:
- the `OneStepEconomy` scenario and its four components (`SimpleLabor`,
  `PeriodicBracketTax`, `SimpleConsumption`, `SimpleSaving`) — all budget, tax-bracket,
  consumption-clearing, and interest-rate mechanics;
- the `complex_actions` scripted-policy formulas (`consumption_len`/`consumption_cats`/
  `work_income_wealth`);
- the endogenous-field sampling pools (`data/profiles.json`) and how `foundation` draws
  from them into `agent.endogenous`.

AERead owns:
- resolution of `config.yaml` + `world_seed` into an immutable scenario `CaseManifest`
  (never reading `config.yaml` relative to a mutable cwd, unlike upstream's own
  `simulate.py`, which does `open('config.yaml')` at *module import time* — a defect in
  upstream's own script, not ours, worth a ledger note only if it were our code);
- the bridge driver that calls `foundation.make_env_instance`, seeds it, and drives
  `env.step(complex_actions(env, obs, **params))` for `episode_length` steps — this driver
  is AERead-owned orchestration, not a copy of `simulate.py`'s `main()` (which also builds
  gpt dialog state, matplotlib figures, and pickle dumps this adapter does not need);
  it reproduces only the step-loop *shape*, never the tax/consumption arithmetic;
- the `PhaseSpec`/seat model, canonical events, replay, receipts, and the four typed
  measurement leaves in §2;
- the two `rule_constraint` scorers, which call back into the same bridge process to
  re-derive `tax_paid`/budget deltas from upstream's own component state rather than
  reimplementing bracket math or accounting identities on the AERead side.

**Seating.** All `n_agents` seats act every month with no ordering dependency (upstream
sends every agent's action into one `env.step(actions_dict)` call) — this is Mode C, the
`mode="simultaneous"` `PhaseSpec` pattern already used by `housing_v1`'s `contact`/
`respond`/`commit` phases (`src/aeread/shared_runner/housing.py`). One phase,
`agent_month`, self-loops via `next_phases=("agent_month",)` for `episode_length`
instances; `actor_selector="all_agents"`; terminal fires at `episode_length`. There is no
planner seat — `simulate.py` always submits `actions['p'] = [0]` (the null planner action);
`config.yaml`'s `planner_policy`/`trainer` blocks back an RL training loop this adapter
never runs and are not modeled as a seat.

**Bridge.** `ai_economist.foundation` needs `numpy`/`scipy`/`lz4`; `simulate_utils.py`
additionally needs `pandas`/`seaborn`/`matplotlib`/`python-dateutil` at import scope.
None may enter the project venv. Following the `tools/tau2_bridge/provision.sh` pattern,
provision an isolated venv at `/Users/sunzeyu/Documents/econ benchmark/bridges/
econagent-venv` (any Python 3.11+ — no version floor from upstream, unlike tau2's 3.12+),
installing a pinned `requirements.txt` (`numpy`, `scipy`, `lz4`, `pyyaml`, `pandas`,
`seaborn`, `matplotlib`, `python-dateutil`). A `tau2_bridge_driver.py`-style subprocess
script (`econagent_bridge_driver.py`, AERead-owned plumbing) runs inside that venv, adds
the upstream checkout to `sys.path`, imports `ai_economist.foundation` and
`simulate_utils.complex_actions` directly (never `simulate.py`, which has the cwd-relative
top-level `config.yaml` read), and exchanges JSON-serializable requests/responses with the
project-venv adapter over stdin/stdout — mirroring `tau2_bridge.py`/`tau2_bridge_driver.py`.
An `AEREAD_ECONAGENT_BRIDGE_REQUIRED=1` env var (mirroring `AEREAD_TAU2_BRIDGE_REQUIRED`)
turns a missing-bridge skip into a failure for CI and any fidelity-certifying run.

## 4. QC Gate 2 goldens

Per `docs/benchmark_qc.md` §Gate 2 (see §6 on why this citation needed reconstruction),
five goldens against `econagent.pilot.small10x12.seed0`:

| Golden | Concrete planned instance |
|---|---|
| **Successful** | Full 12-month `complex` run, 10 agents, default `beta=gamma=0.1, h=1`. Assert: every month's per-agent budget identity holds exactly (leaf 1), every `tax_paid` matches upstream's own bracket computation replayed on the recorded income (leaf 2), dense_log length == 12, no bridge error. |
| **Valid but poor** | Same scenario, `beta=5.0` (drives `consumption_len` near its `0`/`50`-step clamp every month — agents consume almost nothing). Trajectory stays legal and fully accounted; budget identity and tax arithmetic still hold exactly; the macro diagnostics (leaf 3) show depressed GDP-proxy and rising average savings — recorded as a diagnostic outcome, never scored as a failure. |
| **Invalid or unauthorized** | Bridge request with an out-of-range action (`consumption` action index outside `[0, n_actions)`, hand-crafted rather than upstream-emitted) fed directly to the bridge's `step` call, bypassing `complex_actions`. Assert: upstream itself rejects/clips per its own masking, and the harness's `legal()` hook marks the action illegal *before* any state mutation is applied — no protected state (`inventory["Coin"]`) changes as a result. |
| **Malformed or operational failure** | Kill the bridge subprocess mid-episode (e.g. `SIGKILL` between month 5 and 6 in a test harness). Assert the adapter records `outcome_unknown`/typed bridge failure, not a scored zero on any of the three diagnostic leaves, and that no partial, silently-committed state is treated as terminal. |
| **Degenerate reference** | `n_agents=1` scenario (`econagent.pilot.tiny4x6.seed0` reduced further, or a dedicated 1-agent case). `PeriodicBracketTax`'s redistribution divides collected tax by `n_agents`; with one agent, lump-sum redistribution is a well-defined but degenerate (self-funding) special case. Assert the adapter reports the actual computed value rather than suppressing or replacing a `0`/`1`-agent edge case, per the declared non-fabrication rule. |

All five run through the bridge (they depend on the real upstream engine for the budget and
tax arithmetic) and are therefore skipped, never faked, without a provisioned bridge venv —
guarded by `AEREAD_ECONAGENT_BRIDGE_REQUIRED`.

## 5. Test plan — e2e, replay, parity

- **e2e** (`tests/test_econagent_e2e.py`): run the scheduler end-to-end over
  `econagent.pilot.small10x12.seed0` and `.seed1` through the real bridge; assert episode
  completion, dense_log length, and all three scenario ids' manifests round-trip through
  the importer byte-identically on a second run (import determinism, mirroring tau3 §8 P1).
- **replay** (`tests/test_econagent_replay.py`): record one full episode's decision log
  (per-slot observation, `complex_actions` output, tool/bridge call, resulting state hash);
  replay offline with the bridge process disabled entirely; assert every per-step state hash
  and the two `rule_constraint` leaves reproduce exactly with zero live calls.
- **parity** (`tests/test_econagent_parity.py`, since upstream code executes via the bridge):
  for each of the three pilot scenarios, independently invoke upstream's own
  `foundation.make_env_instance` + `complex_actions` loop directly inside the bridge venv
  (an "oracle" driver script, not through the adapter's `step()`), and require the
  adapter's per-agent terminal `inventory["Coin"]`, cumulative `tax_paid`, and dense_log
  length match the oracle's exactly. This is the delegate-not-reimplement proof: the adapter
  must not silently diverge from a bare call into the same upstream code.
- **golden fixtures** (`tests/test_econagent_goldens.py`): the five §4 instances as
  individually named, always-run structural assertions (schema/typing checks that do not
  require the bridge) plus bridge-gated numeric assertions (skipped/required per
  `AEREAD_ECONAGENT_BRIDGE_REQUIRED`, same convention as tau3).

## 6. Stated limits

- **Scale.** Only 10-agent x 12-month (and one 4x6, one 1-agent degenerate) scenarios are
  gated. The paper's 100-agent x 240-month configuration is declared in the manifest but
  explicitly `not_run`; no claim about that scale's behavior is made.
- **License posture.** No LICENSE file exists at the upstream repo root; only the copied
  `ai_economist/foundation/*` files carry BSD-3-Clause headers. This adapter never vendors
  any upstream file (import-only via bridge `sys.path`), which sidesteps redistribution
  risk but means the adapter has zero availability guarantee if the upstream repository
  disappears — there is no local fallback copy, by design.
- **No optimality or benchmark score.** EconAgent defines no reward, no task success
  criterion, and no baseline policy comparison upstream. This spec deliberately produces
  only `rule_constraint` accounting leaves plus `baseline_only` descriptive macro
  diagnostics — never an `objective_reference`, never a leaderboard number.
  `econagent_macro_trajectory` cannot support any capability or saturation claim.
- **Scripted policy only.** This pass wires `complex_actions` (scripted, upstream
  non-LLM path) exclusively. The `gpt` policy path exists upstream and is provider-free at
  import time, but wiring an actual LLM-driven agent seat is out of scope for tonight and
  is not addressed by any test here.
- **Gate 2 hard-gate not wired.** The two `rule_constraint` leaves are declared
  `hybrid_gate`-eligible but no invalidating gate currently blocks a budget-identity
  violation from reaching the diagnostic leaves — logged as a limit, not silently assumed
  fixed.
- **`docs/benchmark_qc.md` citation.** This spec's Gate 1/Gate 2 structure is taken from the
  real `docs/benchmark_qc.md` (found at commit `2b831fe`, not yet merged to `main` or any
  adapter branch checked) rather than independently reconstructed — see the econagent
  ledger for the discovery trail and reconciliation note against three prior independent
  reconstructions (aucarena, negarena, govsim).
- **Seat cardinality at N=100.** Nothing in `schemas.py`/`scheduler.py` caps `len(seats)`,
  but no existing family exercises 100 simultaneous seats; this spec assumes it works and
  flags it as unverified at that scale, not confirmed by any test in §5.
