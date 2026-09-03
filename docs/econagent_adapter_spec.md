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
  (`simulate.complex_actions` — **not** `simulate_utils.complex_actions`; see the
  milestone-1 correction below) is `numpy` arithmetic over wealth/income/price, but it also
  reads and mutates the live `env`/agent objects directly (`env.get_agent(idx).endogenous`,
  `env.world.price`, `env._components_dict['SimpleLabor']`), not just the returned `obs`
  dict — no network, no LLM, no API key, ever. This adapter drives the `complex` path
  exclusively.
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

### Milestone 1 corrections (recon gaps found while building `cases.py`/`environment.py`)

Ground rule: "if reality forces a deviation, update the spec in the same commit." Eight
gaps surfaced during milestone-1 implementation, all confirmed directly against the pinned
`bfada09` checkout:

1. **`complex_actions` lives in `simulate.py`, not `simulate_utils.py`.** `simulate_utils.py`
   contains only `get_completion`/`get_multiple_completion`/`prettify_document`/format
   helpers — no `complex_actions` def anywhere in it. `complex_actions` (and `gpt_actions`,
   `main`) are defined directly in `simulate.py` (line 148). Every place below that said
   "imports … `simulate_utils.complex_actions` directly (never `simulate.py`, which has the
   cwd-relative top-level `config.yaml` read)" was therefore describing an import path that
   cannot reach the function it names. Resolution: the bridge driver **does** import
   `complex_actions` from `simulate.py` (`from simulate import complex_actions`), which
   necessarily executes `simulate.py`'s module-level `with open('config.yaml') as f: ...`
   (line 19) as a side effect. This is harmless — not a new risk — only if the driver's
   process `cwd` is the upstream checkout root when the import happens, which turns out to
   be required anyway (next point), so the two cwd-relative reads are satisfied by the same
   one fix rather than compounding into two problems.
2. **`data/profiles.json` is *also* read via a bare, cwd-relative `open('data/profiles.json')`
   from inside the engine itself**, not only from `simulate.py`'s top-level `config.yaml`
   read as the bullet above originally implied. `ai_economist/foundation/scenarios/
   one_step_economy/one_step_economy.py`'s `set_offer` and `reset_agent_states` (both called
   from `env.reset()`) each do a bare `open('data/profiles.json', 'r')`. Resolution: the
   bridge driver subprocess must be spawned with `cwd=<upstream_root>` (never AERead's own
   cwd) for the entire lifetime of an episode — one `cwd` fix covers both this and point 1,
   and matches this spec's own already-stated principle that AERead never reads
   `config.yaml` relative to a mutable cwd the way `simulate.py` does.
3. **The bridge cannot be "one short-lived subprocess per call" like `tau2_bridge.py`.**
   That pattern works for tau2 because `RetailDB` is a plain, fully JSON-serializable
   Pydantic model — the whole call is stateless, with all state traveling in the request/
   response payload. `complex_actions` needs the *live* `env` object (agent objects with
   mutable `endogenous` dict entries it caches across months — `consumption_fun_idx`/
   `work_fun_idx`, assigned once via `np.random.choice` the first time an agent is seen —
   plus `env.world.price`/`interest_rate` history and the shared numpy global RNG stream
   advancing in a fixed per-agent order), none of which is a clean JSON round-trip target
   without either reimplementing upstream's RNG-driven formula selection ourselves
   (forbidden — this adapter never reimplements upstream arithmetic) or re-deriving it by
   replaying every prior month from scratch on every call (unnecessary complexity given the
   simpler fix). Resolution: **the bridge subprocess is persistent for the lifetime of one
   episode** — spawned once at `initial_state()`, held open (stdin/stdout newline-delimited
   JSON, one request per month) across all `episode_length` months, and closed at
   `terminal()`. This is a deliberate, documented divergence from the tau2 bridge's
   per-call-subprocess pattern, not an oversight; see `econagent_bridge.py`.
4. **Per-seat action decomposition is deferred; this pass's seats acknowledge rather than
   decide.** `complex_actions(env, obs, beta, gamma, h)` computes every agent's `[labor,
   consumption]` pair in one function call against the one live `env`/shared-RNG state; it
   is not decomposable into independently-invoked per-seat calls without either breaking the
   spec-5 parity requirement (the adapter's own run must match a bare oracle call to
   `complex_actions` exactly, agent-by-agent) or reimplementing upstream's formula-selection
   RNG draws on the AERead side (forbidden). Since the `gpt` (LLM) policy path is explicitly
   out of scope for this pass (§6) and `complex` is the only wired policy, each `agent_i`
   seat's declared action schema this pass is a trivial acknowledgment
   (`econagent_v1_month_ack_v1`) rather than a real `[labor, consumption]` decision;
   `step()` asks the persistent bridge to run the *real* `complex_actions` **and** `env.step`
   together for the month (exactly mirroring `main()`'s loop), then reports the resulting
   per-agent `[labor, consumption]` split back through `outcome()`/dense-log surfaces for
   audit. A decomposed, harness-authored per-seat action schema is deferred to whenever an
   LLM-driven agent seat is actually wired (already out of scope per §6); wiring one will
   also have to resolve how a non-scripted policy's action is supposed to interleave with
   upstream's own shared-RNG-driven formula selection, which is a new design question, not
   one this pass answers.
5. **`fire` is missing from the bridge `requirements.txt`.** `simulate.py` does
   `import fire` at module scope (line 3); reaching `complex_actions` via `from simulate
   import complex_actions` therefore requires `fire` in the bridge venv too, alongside the
   `pyyaml`/`pandas`/`seaborn`/`matplotlib`/`python-dateutil` already listed. Also note
   `simulate.py` itself (not only `simulate_utils.py`) does module-level `import
   matplotlib.pyplot`, `import yaml`, and `from dateutil.relativedelta import
   relativedelta` — the set of required packages is a union across both files, not
   `simulate_utils.py` alone. `tools/econagent_bridge/requirements.txt` includes `fire`.
6. **The "no two share a `world_seed`" Gate-1 check (§1) must be scoped per
   scenario shape, not global.** The pinned scenario table itself reuses
   `world_seed=0` across `econagent.pilot.small10x12.seed0` (10 agents, 12
   months) and `econagent.pilot.tiny4x6.seed0` (4 agents, 6 months) --
   different shapes entirely. A literal global uniqueness check would reject
   the very table it is meant to admit. `cases.py`'s `import_all_cases` scopes
   the duplicate/near-duplicate check to `(n_agents, episode_length,
   world_seed)` instead, which still catches a genuinely duplicated run
   (same shape, same seed) without rejecting two unrelated shapes that
   happen to reuse a seed value.
7. **Golden #5 (§4) as literally written cannot run.** `BaseEnvironment.__init__` asserts
   `n_agents >= 2` (`ai_economist/foundation/base/base_env.py`); an `n_agents=1` scenario
   fails upstream's own constructor assertion before any degenerate-redistribution behavior
   could be observed. This is a Gate-2/goldens (later milestone) problem, flagged here rather
   than silently fixed, since no golden fixtures are built this pass: whoever builds §4
   needs a different concrete degenerate case (e.g. `n_agents=2`, the actual floor) or must
   accept upstream's assertion itself as the observed "degenerate" behavior and assert that.
8. **`world_seed=0` cannot be passed to upstream's own seeding verbatim.**
   `BaseEnvironment.seed()` (called from `__init__` when given a non-`None` `seed=` kwarg)
   asserts `seed > 0`; the pinned scenario table uses `world_seed=0` for two of the three
   scenarios. AERead's own `world_seed` is (and stays) zero-based -- `CaseManifest.
   world_seed`'s grammar allows `0`, and neither the case id nor the manifest field changes.
   The bridge driver applies a fixed `+1` offset only at the point it hands the seed to
   upstream (`env_config["seed"] = world_seed + 1`); two distinct `world_seed` values still
   map to two distinct upstream seeds, and nothing about the case's own declared identity
   or content digest depends on this offset.

### Milestone 2 corrections (recon gaps found while building measurement.py/goldens/parity)

Same ground rule as milestone 1: update the spec in the same commit reality forces a
deviation. Five gaps surfaced while building §2's three leaves, §4's goldens, and §5's
parity harness, all confirmed directly against the pinned `bfada09` checkout and against a
real bridge-driven episode.

1. **`labor_income` must be sourced from `dense_log["PeriodicTax"][...]["income"]`, not
   `dense_log["states"][...][agent_id]["income"]["Coin"]`.** Both are upstream-recorded, but
   `SimpleLabor.component_step` only assigns `agent.income["Coin"] = payoff` inside its
   `if 1 <= action <= num_labor_hours:` branch -- on a month an agent's `complex_actions`-
   chosen labor action is 0, that field is never reset and keeps showing the last month's
   positive value ("last positive income", not "this month's income"). `PeriodicBracketTax`'s
   own `income` field (`agent.state["production"] - last_coin`, a production delta) correctly
   reads 0 on that same no-op month, because `agent.state["production"]` is only incremented
   inside the identical branch. Confirmed empirically: sourcing from `states[...]["income"]`
   produced large spurious `econagent_budget_identity` residuals on any no-op-labor month;
   sourcing from `PeriodicTax[...]["income"]` produces an exact-zero residual instead.
2. **`consumption_spend` has the identical staleness problem, one component later, and it is
   not hypothetical -- it fired in the very first `n_agents=2` degenerate-golden run built for
   §4.** `SimpleConsumption.component_step` also does `if action == 0: continue` for its own
   consumption action; `agent.consumption["Coin"]` is never reset on that branch either. Unlike
   `labor_income`, there is no substitute upstream-recorded field analogous to the tax
   component's production-delta, so the fix instead reads the actual action `complex_actions`
   chose that month -- `month_actions[month-1][agent_id][1]` (upstream's own returned
   `[labor, consumption]` pair, already reported back by the bridge's `step_month` response for
   exactly this kind of audit, per milestone-1 correction 4) -- and treats `consumption_spend`
   as `0` whenever that action is `0`. `measurement.py`'s `compute_budget_identity_residuals`
   and `compute_macro_trajectory` both take `month_actions` as a required argument now, not an
   optional one.
3. **`saving_interest` has no upstream-recorded value anywhere to read.**
   `SimpleSaving.component_step` adds the interest payoff straight to
   `agent.state["inventory"]["Coin"]`; `agent.state["saving"]` is a vestigial field upstream
   initializes to 0 and never mutates (confirmed empirically: it reads 0 in every recorded
   month of every probed episode), and no dense-log entry captures the payoff either.
   `econagent_budget_identity`'s sixth term is therefore derived as the closing residual of
   the other five already-recorded terms, not read directly. This is not a weaker check: by
   upstream's own component ORDER (`SimpleLabor`, `PeriodicBracketTax`, `SimpleConsumption`,
   `SimpleSaving` always last) and its own documented `timestep % world.period == 0` gate on
   `SimpleSaving.component_step`, the residual is a real, falsifiable invariant -- exactly `0`
   on every month that is not a `world.period` boundary, and (since upstream's own interest
   rate is clamped `>= 0`) never negative on a boundary month. `world.period` itself (distinct
   from `PeriodicBracketTax`'s *own* `"period"` config field, which is `1`) is exposed by a
   milestone-2 addition to `econagent_bridge_driver.py`'s `agent_snapshot` op rather than
   hardcoded.
4. **`econagent_tax_bracket_arithmetic`'s "re-invoke upstream's own component method" requirement
   cannot use the episode's own bridge session, because that session is already closed by the
   time post-episode scoring runs** (`environment.py`'s `step()` calls `bridge.close()` as soon
   as the episode terminates). Resolution: `econagent_bridge_driver.py` gained a new, stateless
   op, `recompute_tax` -- constructs a throwaway env from the pinned config alone (no `reset`
   required) and calls the live `PeriodicBracketTax.taxes_due`/`marginal_rate` methods directly.
   This is sound because the `"us-federal-single-filer-2018-scaled"` bracket schedule is a pure
   function of config (no RNG, no dependency on `n_agents`/`world_seed`/prior episode state) --
   confirmed empirically: a freshly-constructed component with different `n_agents`/seed than
   the real episode reproduced its `tax_paid` values exactly. Separately, upstream's own
   `effective_taxes = min(inventory, tax_due)` clipping means a recorded `tax_paid` can
   legitimately be *less than* the recomputed bracket amount; the leaf enforces the one
   direction that is always a bug (`tax_paid` exceeding `tax_due`) and reports clipping as a
   diagnostic, never a violation.
5. **Per-component dense logs (e.g. `"PeriodicTax"`) are only backfilled by upstream's own
   `_finalize_logs()` once the episode's LAST `step_month` completes** -- confirmed empirically:
   calling the bridge's `dense_log` op mid-episode returns only `"world"`/`"states"`/
   `"actions"`/`"rewards"`, never the per-component keys, until the final step. `environment.py`'s
   `step()` therefore fetches the complete dense log exactly once, immediately after the
   terminal `step_month` response and before `bridge.close()` -- a sequencing detail load-bearing
   enough to note here for whoever next touches `step()`.

§4's two goldens flagged in milestone 1 as needing re-derivation are now built, concretely:
"invalid or unauthorized" is realized at both the kernel layer (an illegal/malformed seat
action never reaches `step()`, and `step()` itself refuses an incomplete actions mapping
without touching the bridge) and the bridge-protocol layer (a hand-crafted extra field on a
raw `step_month` request has provably zero effect, since the driver never reads any
caller-supplied action field); "degenerate reference" uses `n_agents=2` (upstream's actual
floor), confirming `PeriodicBracketTax`'s lump-sum redistribution is well-defined, evenly
split, and reported as the real computed value rather than suppressed. See
`tests/test_econagent_goldens.py` for both.

### Milestone 3 correction (found building the scripted harness/e2e/replay pass)

Same ground rule as milestones 1 and 2. One gap surfaced immediately on the first attempt
to run a pinned scenario through the REAL shared-runner path
(`aeread.shared_runner.scheduler.run_episode`) rather than by calling `EconAgentV1Plugin`'s
hooks directly in a hand-wired loop, which is how every milestone-1/2 test (cases,
environment, measurement, goldens, parity) exercises the family:

1. **`episode.max_logical_actions`/`PhaseSpec.max_logical_actions` were set to
   `episode_length`, undercounting by a factor of `n_agents`.** The kernel counts one
   logical action per *seat* per phase instance, not one per phase instance overall — for
   `agent_month` (`mode="simultaneous"`, all `n_agents` seats acting every month, self-looping
   for `episode_length` months), the true per-episode ceiling is `n_agents * episode_length`,
   exactly mirroring `housing_v1`'s own `num_tenants * rounds`/`num_listings * rounds`
   convention for its simultaneous, self-looping phases
   (`src/aeread/shared_runner/housing.py`). A literal `episode_length` budget (`12` for
   `small10x12`, `6` for `tiny4x6`) made `run_episode` raise `SchedulerContractError: case
   logical-action budget exceeded before termination` partway through the very first month
   for every pinned scenario with `n_agents > 1` — undetected through milestones 1-2 because
   nothing in those tests ever drove an episode through the real scheduler. Fixed in
   `cases.py`'s `build_case` and `environment.py`'s `phases()`; the on-disk case files under
   `cases/econagent_v1/` were regenerated (their `content_sha256` changed as a direct
   consequence — no other field changed), and the two milestone-1/2 tests that had hardcoded
   the old, wrong value (`test_econagent_cases.py`, `test_econagent_environment.py`) were
   corrected alongside. See `tests/test_econagent_e2e.py` for the first test that actually
   exercises `run_episode` for this family, and the econagent ledger for the corresponding
   kernel-side observation (no static Gate-1/Gate-2 check cross-validates a case's declared
   logical-action budget against its phases' seat cardinality without actually running a full
   episode).
2. **A live episode's raw, byte-exact state never matches its own replay, because
   `EconAgentV1Plugin.initial_state` mints a fresh `uuid.uuid4().hex` `bridge_session_id`
   bookkeeping key on every call.** That key is never surfaced through `terminal()`/
   `outcome()` and is never causally relevant to any accounting leaf, but it IS part of the
   full per-phase `state` the scheduler hashes into `pre_state_sha256`/`post_state_sha256` and
   freezes into `final_state` — discovered building `replay.py` (a live run replayed from its
   own exact recorded bridge call log still did not raw-hash-match itself). Resolution:
   `replay.py`'s `StateComparison` reports both the raw, byte-exact fields (documented to
   always read `False` across any two independent runs, replay or not — not a bug in the
   comparator) and a session-id-stripped content comparison
   (`final_state_content_matches`/`_strip_bridge_session_id`), and `.matches` uses only the
   latter — the same *shape* of split `tau3_retail/replay.py`'s
   `_strip_message_timestamps`/`final_state_content_matches` already uses, for an unrelated,
   adapter-specific cause (there a per-message wall-clock timestamp; here a per-episode random
   UUID bookkeeping key). Deliberately not "fixed" by making `bridge_session_id` deterministic
   (e.g. derived from the `PlanCell`'s own `cell_id`, which `initial_state` currently ignores
   entirely — `del cell`): that would touch a method every milestone-1/2 test already exercises
   with `cell=None`, for a benefit (raw byte-exact equality) no test or claim in this spec
   actually needs beyond what the content comparison already proves.

Milestone 3 built: `harness.py` (`ScriptedEconAgentHarness`, a provider-free
`ResponseSource` — every `agent_i` seat gets the fixed acknowledgment every month, per
milestone-1 correction 4, so there is no tool/action content to script, unlike
`tau3_retail`'s harness); `tests/test_econagent_e2e.py` (two full pilot episodes —
`small10x12.seed0` and `.seed1` — through the real scheduler, plus the importer's
byte-identical-on-a-second-run determinism check for all three scenario ids, per section 5's
e2e bullet); and `replay.py`/`tests/test_econagent_replay.py` (offline replay with the real
bridge subprocess disabled entirely, per section 5's replay bullet — see `replay.py`'s own
module docstring for why the seam that gets replayed here is the *bridge*, not the response
source, unlike `tau3_retail`).

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
| `econagent_budget_identity` | `rule_constraint` | `state_invariant` | Per-agent, per-step: `inventory_coin[t] == inventory_coin[t-1] + labor_income - tax_paid + lump_sum - consumption_spend + saving_interest` (five terms read verbatim from the executed upstream state/dense_log; the sixth, `saving_interest`, is derived as the closing residual of the other five and checked against its own documented invariant — see milestone-2 correction 3 — never read directly or recomputed independently). Deterministic leaf; violation is an adapter/bridge bug, not a policy failure. |
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
- the bridge driver that calls `foundation.make_env_instance`, seeds it via `env.seed(...)`
  /the constructor's own `seed=` kwarg, and drives `env.step(complex_actions(env, obs,
  **params))` for `episode_length` steps — this driver is AERead-owned orchestration, not a
  copy of `simulate.py`'s `main()` (which also builds gpt dialog state, matplotlib figures,
  and pickle dumps this adapter does not need); it reproduces only the step-loop *shape*,
  never the tax/consumption arithmetic;
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
never runs and are not modeled as a seat. Per milestone-1 correction 4 above, each
`agent_i` seat's declared action this pass is an acknowledgment
(`econagent_v1_month_ack_v1`), not a decomposed `[labor, consumption]` decision — the real
`complex_actions` computation happens inside the bridge, once per month, against the one
live `env`/RNG state it holds for the whole episode.

**Bridge.** `ai_economist.foundation` needs `numpy`/`scipy`/`lz4`; `simulate.py` and
`simulate_utils.py` together additionally need `pandas`/`seaborn`/`matplotlib`/
`python-dateutil`/`pyyaml`/`fire` at import scope (milestone-1 correction 5). None may
enter the project venv. Following the `tools/tau2_bridge/provision.sh` pattern, provision
an isolated venv at `/Users/sunzeyu/Documents/econ benchmark/bridges/econagent-venv` (any
Python 3.11+ — no version floor from upstream, unlike tau2's 3.12+), installing a pinned
`requirements.txt` (`numpy`, `scipy`, `lz4`, `pyyaml`, `pandas`, `seaborn`, `matplotlib`,
`python-dateutil`, `fire`). Unlike `tau2_bridge.py`/`tau2_bridge_driver.py`'s one-fresh-
subprocess-per-call design, `econagent_bridge_driver.py` runs as **one persistent
subprocess per episode** (milestone-1 correction 3): spawned with `cwd=<upstream_root>`
(correction 1+2), it adds the upstream checkout to `sys.path`, imports
`ai_economist.foundation` and `complex_actions` from `simulate.py` (**not**
`simulate_utils.py`) once, then serves newline-delimited JSON requests over stdin/stdout
for the lifetime of one episode — `reset` once, then one `step_month` request per month,
then `shutdown`. An `AEREAD_ECONAGENT_BRIDGE_REQUIRED=1` env var (mirroring
`AEREAD_TAU2_BRIDGE_REQUIRED`) turns a missing-bridge skip into a failure for CI and any
fidelity-certifying run, matching tau2's convention; the shared root `conftest.py`'s
`pytest_terminal_summary` hook now declares each family's own requirement flag and skip
markers independently (fix for docs/econagent_codex_triage.md finding 5 -- it used to
recognize only tau2's own flag and markers, so setting econagent's requirement flag with no
usable interpreter still produced a silent, zero-exit skip).

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

**Built in milestone 2 (`tests/test_econagent_goldens.py`) — this row records the two
literal-text goldens above that needed re-derivation, and how, rather than pretending the
table above was ever executable verbatim.** No golden fixture was implemented in milestone 1
(cases + environment only). "Invalid or unauthorized" as originally written assumes a seat
submits a `consumption` action index the harness can corrupt, which milestone-1 correction 4
rules out for the scripted-only pass (the seat action is an acknowledgment; the real decision
is computed inside the bridge); the built golden instead demonstrates illegality/
unauthorization at both layers where it can actually occur — a malformed/unauthorized seat
action rejected by `legal()`/`parse_action()` before `step()` is ever called (kernel layer),
and a hand-crafted extra field on a raw `step_month` request proven to have zero effect
because the driver never reads any caller-supplied action field at all (bridge-protocol
layer). "Degenerate reference" as originally written needs a different scenario per
milestone-1 correction 7 (`n_agents=1` cannot construct); the built golden uses `n_agents=2`,
upstream's actual floor. See "Milestone 2 corrections" above for the full reasoning trail.

## 5. Test plan — e2e, replay, parity

- **e2e** (`tests/test_econagent_e2e.py`) — **built in milestone 3**: runs both
  `econagent.pilot.small10x12.seed0` and `.seed1` through the REAL shared-runner path
  (`aeread.shared_runner.scheduler.run_episode` + `PluginRegistry.resolve_manifest`, driven by
  the new `ScriptedEconAgentHarness` — never the hand-wired plugin-hook loop every milestone-1/
  2 test uses); asserts episode completion, per-phase-instance seat/mode shape, dense_log
  length, and that all three scenario ids' manifests round-trip through the importer
  byte-identically on a second run, including against the actually-committed case files
  (import determinism, mirroring tau3 §8 P1). Running a real episode through the scheduler for
  the first time immediately surfaced the milestone-3 `max_logical_actions` gap documented
  above; `tests/test_econagent_goldens.py`'s "successful" golden exercises an equivalent full
  run but never through `run_episode` itself.
- **replay** (`tests/test_econagent_replay.py`) — **built in milestone 3**: records one full
  live episode's bridge call log (`replay.py`'s `RecordingEconAgentBridge`, injected through
  `EconAgentV1Plugin`'s existing `bridge_factory` seam — start_episode/step_month/
  agent_snapshot/dense_log/close, in call order) and one live tax-bracket-scoring call log
  (`recompute_tax`), then replays both through the real scheduler with the real bridge
  subprocess never spawned (`RecordedEconAgentBridge`, proven by monkeypatching
  `EconAgentBridge._spawn` to raise during a passing replay). Asserts the replayed episode's
  terminal/outcome/final-state *content* reproduces the live run's exactly, and that all three
  measurement leaves recomputed from the replay equal the live run's `ScoreEnvelope`s exactly,
  with zero live bridge subprocess calls. One caveat found building this, stated rather than
  implied: `EconAgentV1Plugin.initial_state` mints a fresh `uuid.uuid4().hex`
  `bridge_session_id` bookkeeping key on every call, so the scheduler's own raw, byte-exact
  per-phase state hashes and frozen `final_state` do **not** match between a live run and its
  replay (`StateComparison.state_hashes_match`/`final_state_matches` are both `False`, always,
  by construction) — only the session-id-stripped content comparison
  (`final_state_content_matches`) is the real guarantee, exactly the same *shape* of finding as
  `tau3_retail/replay.py`'s message-timestamp non-determinism, with a different, adapter-
  internal cause. See `replay.py`'s module and `StateComparison` docstrings.
- **parity** (`tests/test_econagent_parity.py`, since upstream code executes via the bridge)
  — **built in milestone 2**: for each of the three pilot scenarios, independently invoke
  upstream's own `foundation.make_env_instance` + `complex_actions` loop directly inside the
  bridge venv (`parity.py`'s inline oracle script, run via `python -c` -- never importing
  `econagent_bridge_driver.py`, so agreement is not the driver agreeing with itself), and
  require the adapter's per-agent terminal `inventory["Coin"]`, cumulative `tax_paid`, and
  dense_log length match the oracle's exactly. This is the delegate-not-reimplement proof:
  the adapter must not silently diverge from a bare call into the same upstream code. A
  mutation test (two runs with different `world_seed`s) confirms the comparison actually
  detects real divergence, not just agreement.
- **golden fixtures** (`tests/test_econagent_goldens.py`) — **built in milestone 2**: the
  five §4 instances (two re-derived per the note above), run against the real bridge and
  skipped, honestly, without a provisioned bridge interpreter -- following the same
  `_require_bridge()` convention as every other econagent test file, not literally gated by
  `AEREAD_ECONAGENT_BRIDGE_REQUIRED` (that env var still has no enforcement hook generalized
  beyond tau2 in the shared root `conftest.py`; see the econagent ledger).

## 6. Stated limits

- **Scale.** Only 10-agent x 12-month and 4-agent x 6-month scenarios are gated (see
  milestone-1 correction 7 for why a literal 1-agent scenario is not constructible upstream).
  The paper's 100-agent x 240-month configuration is declared in the manifest but explicitly
  `not_run`; no claim about that scale's behavior is made.
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
- **Seat action is an acknowledgment, not a decision, this pass.** Per milestone-1
  correction 4, `agent_i` seats submit a trivial `econagent_v1_month_ack_v1` action rather
  than a `[labor, consumption]` decision the environment then validates; the bridge computes
  and applies the real `complex_actions` result each month. This keeps the adapter's own run
  bit-identical to a bare oracle call (spec-5's parity requirement) without reimplementing
  upstream's RNG-driven formula-selection on the AERead side, but it also means this pass's
  `PhaseSpec`/seat plumbing does not yet exercise a genuine per-seat decision surface — that
  only becomes meaningful once a non-scripted (e.g. LLM) policy is wired, which is already
  out of scope here and raises its own unresolved question about how such a policy's action
  is supposed to interleave with upstream's shared-RNG-driven formula selection.
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
