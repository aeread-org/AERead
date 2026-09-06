# Implementation Specification — `econevals` adapter for the AERead shared-runner kernel

**Scope.** Wrap EconEvals (`sara-fish/econ-evals-paper`, MIT, pinned at
`e1f2a40fec96f0d27f5414873c4310f2b5c51935`) as one AERead family with three
tracks — `procurement`, `scheduling`, `pricing` — each an `objective_reference`
exact-solved single-agent task: an agent submits a decision each of up to 100
periods against a deterministically generated instance, judged against an
exact optimum. Tonight's milestone is a **pilot corpus** (28 instances, all
Basic difficulty: 8 procurement + 12 scheduling + 8 pricing seeds), not the
full Basic/Medium/Hard grid — gated on corpus admission (this doc §1) and five
component-level goldens (§4), not on paid agent runs.

**Governing facts** (verified in recon; do not re-derive):
- Upstream is **generator-based**, not a fixed task list: `run_<track>_batch.py`
  takes `--difficulty {Basic,Medium,Hard}` and `--seeds INT...`; each seed
  deterministically builds one instance via `generate_instance`
  (procurement/pricing) or `generate_preferences` (scheduling).
- **Procurement's generator is not fully seed-reproducible.**
  `generate_instance.py` computes `budget` via `np.random.uniform(0, 1)` — the
  *global* NumPy RNG — instead of the `my_random: RandomState` argument every
  other draw in the function uses. Same-seed reruns reproduce entries, item
  groups, effectiveness, and `start_alloc` byte-for-byte but **not** `budget`,
  whenever anything else drew from the global RNG first (measured: same-seed
  budget 109.77 clean vs. 109.94 after one intervening `np.random.uniform()`
  call). Fix verified: one instance per fresh subprocess, `np.random.seed(seed)`
  called immediately before `generate_instance` — 3/3 probed seeds then
  reproduce byte-for-byte. Scheduling/pricing need no such workaround (both use
  only `my_random.*`; 3/3 and 4/4 probed seeds byte-identical already).
- **Exact optimum construction, per track, is upstream code, never reimplemented:**
  procurement — `opt_solver.compute_opt` (MILP via `gurobipy`); scheduling —
  no upstream optimum solver exists (`calculate_scheduling_baseline.py` only
  bootstraps a *random*-matching expectation), so the reference is the
  **Gale–Shapley existence theorem**: a 0-blocking-pair stable matching is
  always attainable, verified via upstream's own `get_blocking_pairs`/
  `is_valid_matching`; pricing — `pricing_market_logic_multiproduct.get_monopoly_prices`
  (`scipy.optimize.minimize`, a **numerical**, not closed-form, optimum — a
  tolerance is required, not bit-exact equality).
- Gurobipy's pip package ships a size-limited free license. Basic procurement
  (3 inputs × 4 alternatives/input, 12 menu entries) solved under it with no
  license error (verified: `compute_opt` returned an integer-optimal
  allocation). Medium/Hard procurement are out of scope tonight for this
  reason (upstream's own comment: "if using Gurobi free version, highest you
  can do is about num_inputs=5, num_alternatives=8").
- `evaluate_alloc` (procurement's feasibility/utility scorer) raises an
  uncaught `AssertionError` if the submitted allocation references an
  offer ID absent from the menu (`Menu.__getitem__` asserts membership) —
  this is not a graceful `is_feasible=False`. The adapter must validate
  offer-ID membership before calling upstream, or catch and retype the
  assertion, rather than let it propagate as an infrastructure crash.
- All three tracks share one tool shape: read-only info tools
  (`get_*`), a `write_notes`/`read_notes` scratchpad, and one mutating
  `submit_purchase_plan` / `submit_assignment` / `set_prices` call that ends
  a period (`MAX_LLM_QUERIES_PER_PERIOD = 40` non-submit calls per period,
  `num_attempts = 100` periods per instance — identical across all three
  `run_<track>_batch.py` files). No opponent, user simulator, or second seat.

## 1. Pinned source, corpus enumeration, and content digest (Gate 1)

**Pin.** Repository `sara-fish/econ-evals-paper`, commit
`e1f2a40fec96f0d27f5414873c4310f2b5c51935`, MIT. Frozen module hashes (sha256
of file bytes at the pin; any change here invalidates the pilot manifest):

| Module | sha256 |
|---|---|
| `experiments/procurement/generate_instance.py` | `75507abd8487...c9e97aee` |
| `experiments/procurement/opt_solver.py` | `e2710eadb1ea...2babab892` |
| `experiments/scheduling/generate_preferences.py` | `a932725fb1c4...9631041b56` |
| `experiments/scheduling/stable_matching_environment.py` | `6e44d8150941...562ab23e1b128` |
| `experiments/pricing/generate_instance.py` | `45d7743df9a6...5f3572ce35fe` |
| `experiments/pricing/pricing_market_logic_multiproduct.py` | `b2bac943c421...857e6dc07b1723` |
| `utils/helper_functions.py` (`parse_dict`) | `25487b347004...744d0506` |

**Enumeration.** The corpus is the Cartesian set `{track} × {"Basic"} ×
{seeds}`. Tonight's pilot seed lists (chosen for coverage, not randomly):
procurement `0..7`; scheduling `0..11` (upstream's own `SCORE_GAP_*` arrays
cycle every 12 seeds through 4 preference regimes 3× each — using 0..11 gets
full regime balance, not an arbitrary slice); pricing `0..7` (even/odd seeds
alternate `linear_shifts`/`periodic_shifts` via `seed % 2`, so 8 seeds cover
4 of each). 28 instances total.

**Build procedure, per candidate `(track, "Basic", seed)`** — every step runs
in the `tools/econevals_bridge` interpreter, one fresh subprocess per call
(§1's procurement-RNG finding makes this non-negotiable, not a style choice):
1. Generate the instance twice, independently. Byte-compare canonical JSON
   (`json.dumps(..., sort_keys=True, default=str)` over every generator
   output field). Mismatch → **do not admit**; log as a typed exclusion with
   the two digests, not a silent drop.
2. Procurement only: call `compute_opt` on the instance. A Gurobi
   license-size rejection → typed exclusion (`reason: "gurobi_license_size"`),
   never a silent skip. (Not hit tonight — all 8 Basic seeds solved.)
3. Wrap the (now verified-reproducible) instance plus its computed exact
   optimum into `payload = {"track", "difficulty", "seed", "generated_instance",
   "gold_optimum", "pins"}` and write one `CaseManifest` (spec
   `"aeread.case/0.1"`) per admitted instance.

`content_sha256` (kernel resolver, `case_content_sha256`) covers the full
manifest, so it is sensitive to `generated_instance` — the byte-compare in
step 1 is what makes that hash meaningful rather than an artifact of
generator nondeterminism.

**Case-manifest fields:**

| field | value |
|---|---|
| `case_id` | `econevals.<track>.basic.<seed>`, e.g. `econevals.procurement.basic.7` — dot-separated, no colon |
| `family_id` / `family_version` | `econevals` / `0.1.0` |
| `split` | `"<track>_basic"`, e.g. `"procurement_basic"` |
| `world_seed` | the generator seed (int); not required unique across tracks, only `case_id` is |
| `seats` | `(SeatSpec(id="agent", role="assistant"),)` — single-agent, no counterpart |
| `episode` | `EpisodeSpec(max_logical_actions=100, termination=("max_periods","error"))` — one logical action = one period (all info/notes calls plus the terminating `submit_*`/`set_prices` call), mirroring tau3's decision-slot bundling; no early-stop path was found in any of the three `run_*_experiment.py` drivers |
| `visibility_policy` | full observability — all read-only tools are always callable; no hidden information |
| `payload` | `{track, difficulty, seed, generated_instance, gold_optimum, pins}` |
| `provenance` | `ProvenanceSpec(generator_id="econevals_importer", generator_version="0.1.0", review_status="upstream_pinned")` |
| `upstream_task_id` | `null` — EconEvals has no upstream task list to key off; the natural key is `(track, difficulty, seed)`, carried in `payload` (schema gap, not silently worked around) |

## 2. Verifier declarations

Every track composes two leaves as a `hybrid_gate` (verifier_taxonomy.md §10):
a deterministic legality/feasibility gate, then the objective leaf, reported
as a vector — never collapsed into one scalar.

**Procurement — full example of the objective leaf** (the gate leaf is
declared identically for all three tracks: `verifier_family="rule_constraint"`,
`reference_kind="constraint_satisfaction"`, `input_scope="answer"`,
`units="pass"`, `evaluation_class="deterministic"`, scorer = the track's own
legality primitive — see table below for which primitive each track binds):

```python
objective = MeasurementLeafSpec(
  leaf_id="econevals_objective_leaf", leaf_version="0.1.0",
  estimand=EstimandSpec(estimand_id="econevals_procurement_utility",
    estimand_version="0.1.0", input_scope="terminal_state", direction="maximize",
    units="workers_supported", validity_domain=...),
  verifier=VerifierSpec(verifier_family="objective_reference",
    evaluation_class="deterministic",
    reference=ReferenceSpec(reference_kind="exact_optimum",
      input_scope="terminal_state", units="workers_supported", ...),
    objective_scope=ObjectiveScopeSpec(objective_id="econevals_procurement_utility_v1",
      objective_version="0.1.0", direction="maximize", units="workers_supported",
      feasible_set="alloc: Offer_id->qty with total_cost<=budget, per-entry minimums met",
      information_set="full menu, item groups, effectiveness, budget observable each period",
      horizon="final submitted allocation (period 100)",
      environment_condition="static menu/budget fixed at instance generation",
      opponent_condition="none (single-agent)", validity_domain=...)),
  scorer=ImplementationRef(implementation_id="econevals_bridge.compute_opt",
    version="0.1.0", content_sha256="<opt_solver.py hash above>"))
```

Leaf ids are track-agnostic since the scoring-contract migration (`measurement.py`'s `GATE_LEAF_ID`/`OBJECTIVE_LEAF_ID`, shared by all three tracks); per-track identity lives in `estimand_id`/`units`/`direction`/`reference.source_sha256`, not in the leaf id.

`gold_optimum` in the case payload is this scorer's output, computed once at
import time by the bridge (§1) — never recomputed live, so a live gurobi call
is never on the scoring path (deterministic replay only, §5).

All three tracks share the two-leaf shape; only the gate primitive, objective
units, and reference construction differ:

| Track | Gate primitive | Objective leaf | Reference construction |
|---|---|---|---|
| procurement | `evaluate_alloc` (budget/min-quantity feasibility) | direction `maximize`, units `workers_supported` | `compute_opt` (MILP, gurobipy) — bit-exact |
| scheduling | `is_valid_matching` (bijection over declared ids) | direction `minimize`, units `blocking_pairs` | analytic: 0 always attainable (Gale–Shapley); `get_blocking_pairs` on the submission is upstream code, never reimplemented |
| pricing | prices non-negative, keyed to declared `product_ids` | direction `maximize`, units `profit_usd` | `get_monopoly_prices`→`get_profits`; **numerical** (scipy), so a tolerance (`atol=1e-6` on profit) rides in the scorer's pinned `ImplementationRef` hash — `VerifierSpec` has no first-class tolerance field at the current schema version |

## 3. Adapter boundary

**Upstream owns:** instance generation (`generate_instance`, `generate_preferences`), exact-optimum construction (`compute_opt`, `get_monopoly_prices`), and scoring primitives (`evaluate_alloc`, `get_blocking_pairs`/`is_valid_matching`, `get_profits`) — all invoked through the bridge, never reimplemented.

**AERead owns:** resolution into `CaseManifest`/pilot manifest; the period-loop harness (agent seat only, no user simulator to port); tool declarations for `get_*`/`write_notes`/`read_notes`/`submit_*` (`effect="read_only"` for every info/notes tool, `"mutating"` for the one terminating submit tool per track, `state_reader` = the running attempt-history list); defensive pre-validation of submitted IDs before calling `evaluate_alloc`/`is_valid_matching` (upstream crashes on an unknown offer ID, per "Governing facts"); canonical event/evidence/replay sealing; the two `MeasurementLeafSpec`s per track and their `ScoreEnvelope`s.

**Bridge**, mirroring `tools/tau2_bridge`: `tools/econevals_bridge/` (`provision.sh`, `requirements.txt`, `README.md` — added and verified this session, see §5). One subprocess per generation/scoring call — required by the procurement RNG finding, not merely upstream's Python-3.12 requirement. Env var `AEREAD_ECONEVALS_BRIDGE_PYTHON`, default venv `bridges/econevals-venv` (sibling of both checkouts), pinned deps `numpy 2.5.2`, `scipy 1.18.1`, `pandas 3.0.5`, `pydantic 2.13.5`, `inflect 7.5.0`, `gurobipy 13.0.3`.

## 4. Five QC Gate-2 goldens

One scripted (gold-trajectory) fixture per category, no live model calls:

1. **Successful** — pricing `econevals.pricing.basic.0`: trajectory sets prices to `get_monopoly_prices`'s output every period; expect gate pass and objective pass within the pinned tolerance.
2. **Valid-but-poor** — scheduling `econevals.scheduling.basic.0`: a legal bijection (gate passes) built from a deliberately reversed preference order, producing >1 blocking pair (Basic's own threshold is 1) — the below-optimum path, distinct from illegality.
3. **Invalid-unauthorized** — procurement `econevals.procurement.basic.0`: submission whose total cost exceeds budget; `evaluate_alloc` returns `is_feasible=False` with a populated reason, gate fails, objective is not scored. Companion **unit test** (not a corpus golden): an unknown-offer-ID submission must come back as a typed illegal-action result, not upstream's raw `AssertionError`.
4. **Malformed-operational** — scheduling `econevals.scheduling.basic.1`: `submit_assignment`'s argument is prose, not a parseable dict; upstream's own `parse_dict` fails all three of its parse strategies. Must report `invalid_measurement` (measurement_validity layer), never an economic zero — distinct from golden 3's domain-legality failure.
5. **Degenerate-reference** — a **hand-authored** procurement fixture (not one of the 8 pilot seeds): a single-entry-per-item-group menu where upstream's own `start_alloc` is already feasible and optimal, forcing `V_LB == V_agent == V_UB`. Exercises verifier_taxonomy.md §5.3's zero-headroom edge (`headroom_capture` denominator `V_UB - B = 0`) without depending on finding such a seed organically.

## 5. Test plan

**Gate 1 (corpus admission).** `test_econevals_cases.py`: for every pilot `(track, seed)`, generate twice in independent bridge subprocesses and assert byte-identical canonical JSON — the regression test for the procurement RNG finding, which must fail loudly if the fresh-subprocess convention is ever dropped; assert module hashes match §1's table; assert Gurobi resolves each procurement instance without a license error.

**Component parity.** For each pilot instance: adapter's `gold_optimum` byte-equals a second independent bridge call to `compute_opt`/`get_monopoly_prices`/`get_blocking_pairs`-existence; adapter's gate-leaf verdict on a fixed scripted submission equals a direct call to `evaluate_alloc`/`is_valid_matching` outside the adapter.

**Offline replay.** Zero model calls: replay each of the 5 goldens from its sealed episode record, recorded parsed actions folded through `step()` reproduce the same gate/objective verdicts recorded at generation time. `step()`'s own tool-replay cross-check independently re-derives every recorded tool result from the pinned bridge and hard-fails on any divergence (this is the replay guarantee, not a gap in it) — so the deterministic bridge subprocess IS still spawned once per period during replay, exactly as `tau3_retail`'s replay still re-executes every recorded tool call through its own bridge (`Tau2Bridge`); "offline" means no network/model call, not "no local subprocess to a pinned local venv." (`tau3_retail`'s analogous "reads recorded judge verdicts rather than re-invoking a judge" applies only to its judge-dependent leaf, which has no econevals equivalent — every econevals leaf is deterministic, so there is nothing here to skip re-verifying.) See section 6's milestone-3 build note.

**e2e.** One scripted trajectory per track through the full period loop (info tools → notes → one `submit_*`), asserting tool-declaration `effect`/`state_reader` wiring and exactly one terminating call per period.

## 6. Stated limits

- Procurement's Basic-only scope is a **license constraint**, not a design choice: Medium/Hard need an academic Gurobi license.
- Pricing's exact-optimum claim is **tolerance-based, not bit-exact** (`scipy.optimize.minimize`); do not present it as equivalent in kind to procurement's MILP-exact or scheduling's analytic-exact optimum without flagging the numerical solver.
- The pilot is an **integration gate on 28 instances**, not a population estimate; no saturation or capability claim is licensed by it (per `refund_external_benchmark_integration.md` §9's reasoning, applied here).
- `CaseManifest.upstream_task_id` has no natural filler for a generator-based corpus (left `null`) — a schema-shape gap for the kernel owner, not silently worked around.
- `VerifierSpec` has no first-class tolerance/match-mode field for pricing's numerical optimum (§2); it rides in the scorer's pinned `ImplementationRef` hash instead.
- Scheduling's "exact optimum" is an **existence claim** (Gale–Shapley), not a certificate upstream computes; a concrete witness-matching solver, if ever needed, would be new AERead code, not upstream reimplementation — worth flagging before writing it.
- No defect was found in AERead's own runner/kernel during this recon. The one defect found — procurement's global-RNG budget draw — is upstream's, so it is not filed to `ledger_entries/econevals.md`; it is instead the load-bearing regression test in §5.
- **Milestone 1 build note (environment scope).** `environment.py`'s period loop always treats the last tool call of a burst as the period-ending submission, regardless of whether it turns out structurally valid (e.g. scheduling's non-bijective matching, procurement's over-budget allocation): the period ends and the attempt is recorded either way. This does not replicate upstream's own in-period retry loop (`use_tool`'s `RETRY_ERROR` status, which lets the SAME period continue until a structurally valid submission arrives) — that retry policy is treated as a harness-level concern, analogous to how tau3.retail's environment does not itself retry a malformed tool call. Revisit if exact per-period retry-count parity with upstream is ever required.
- **Milestone 1 build note (pricing `gold_optimum` shape).** Because pricing's demand shifts every period (`alpha_list`/`multiplier_list` vary by `env_type`), a single import-time optimum does not describe the whole instance the way procurement's `opt_alloc` does. `gold_optimum.pricing` is therefore `{"prices_by_period", "profits_by_period"}`, one bit-exact `get_monopoly_prices`/`get_profits` call per of the instance's 100 periods, computed once at import time (never upstream's own interpolated `get_monopoly_prices_varying_alphas`). Flagging this shape explicitly for whoever writes the pricing objective leaf in the next milestone.
- **Milestone 2 build note (`objective_id` vs `estimand_id`).** §2's worked example writes `estimand_id="econevals_procurement_utility"` for the estimand but `objective_id="econevals_procurement_utility_v1"` (a different string) for the paired `ObjectiveScopeSpec`. The kernel's real `MeasurementLeafSpec.__post_init__` requires these to be identical (verified empirically: constructing the spec's literal two ids raises `MeasurementContractError`). `measurement.py` uses one identical id for both — not a kernel defect, a spec-prose slip, so not filed to the ledger.
- **Milestone 2 build note (objective leaf primary is native-units, not `headroom_capture`).** `measurement.py`'s objective leaf reports `primary = V_agent` in the track's own native units and `reference_values["v_star"] = V*` (the pinned exact optimum) — never a blended ratio. `headroom_capture` (verifier_taxonomy.md §5.3) is deliberately never computed here, matching `environment.py`'s own family-manifest comment that bound fields are omitted for this reason. Golden 5's degenerate fixture (`V_LB == V_agent == V_UB`) is exactly the case that would force a `V_UB - B` division by zero for a headroom-style scorer; this design has no such division to break.
- **Milestone 2 build note (pricing's gate has no upstream primitive).** Unlike procurement (`evaluate_alloc`) and scheduling (`is_valid_matching`), pricing's declared gate ("prices non-negative, keyed to declared product_ids", §2's table) is not delegated to any upstream function: verified in recon against `run_pricing_experiment.py`'s own `set_prices` tool handler, which validates key-completeness/extraneousness but never price sign. `measurement.py`'s `score_pricing` therefore checks non-negativity itself (AERead's own declared rule_constraint, pinned to this adapter's own file hash rather than an upstream module hash) rather than assuming upstream enforces it.
- **Milestone 2 build note (scheduling/pricing information sets, confirmed in recon).** Neither `run_scheduling_experiment.py` nor `run_pricing_experiment.py` exposes a tool that reveals worker/task preferences or the per-period demand shift (`alpha`/`multiplier`) to the agent — confirmed by reading both files' `use_tool` dispatch tables this session. `measurement.py`'s objective-leaf `information_set` text reflects this: the agent can only infer these hidden primitives from feedback on its own previous submissions, exactly as upstream's own environments already withhold them.
- **Milestone 3 build note (a real `phases()` bug, found and fixed, not filed to the ledger).** Driving the plugin through the REAL kernel scheduler (`run_episode`) for the first time — nothing in milestones 1–2 ever did; every prior test called `plugin.step()` directly — surfaced that `phases()` keyed `observation_schema_by_role`/`action_schema_by_role` by `SEAT_ID` (`"agent"`) instead of `ROLE_ID` (`"assistant"`). `scheduler._eligible_actors` indexes these dicts by role (`role_by_seat[actor]`), which tau3.retail's own phases never exposed as a distinct bug because its seat ids and roles happen to be the same strings (`"user"`/`"assistant"`). Fixed directly in `environment.py` (this family's own code, not the shared kernel) rather than filed to `ledger_entries/econevals.md`.
- **Milestone 3 build note (harness/replay module layout).** `tools.py` (`ToolDefinition`/`ToolBinding` declarations plus `EconevalsToolSession`, the harness's mutable state mirror) and `harness.py` (`ScriptedEconevalsHarness`, driving the kernel `ToolRuntime` per period) both delegate to `environment.py`'s own `dispatch_read_only`/`dispatch_submit` — renamed public (from `_dispatch_read_only`/`_dispatch_submit`) precisely so the harness and `step()`'s own tool-replay cross-check share one tool-body implementation, never two. The per-period bookkeeping (`period += 1`, `"max_periods"` once `pins.max_steps` is reached) is likewise factored out of `step()` into a public `advance_period()`, called both by `step()` and by the harness's session mirror after each scripted period.
- **Milestone 3 build note (replay's byte-identical claim, stronger than tau3.retail's).** `replay.py`'s `StateComparison` asserts genuinely byte-identical final state (`final_state_matches`/`state_hashes_match`), not merely content-equivalent state as `tau3_retail.replay` must (upstream's own message models re-timestamp on every `model_validate`). econevals's FSM state (`track`/`period`/`termination`/`notes`/`attempts`) is entirely AERead's own deterministic data with no wall-clock field anywhere, so there is no `_strip_message_timestamps`-style helper needed at all — replay reproduces the sealed episode byte-for-byte.
- **Milestone 3 build note (offline replay still spawns the bridge subprocess; §5's earlier wording was wrong, corrected by the second-reviewer pass).** §5's "Offline replay" bullet previously read "no bridge subprocess spawned" / "replay reads sealed evidence only" — that was never true and was never implemented that way: `replay.py`'s own module docstring, `environment.py`'s `step()`, and `tests/test_econevals_replay.py::test_replay_raises_when_a_recorded_tool_result_is_tampered_with` (which only works BECAUSE replay re-derives the tool result from a live bridge call and compares it to the recorded one) all agree that replay still spawns one bridge subprocess per period, exactly mirroring `tau3_retail.replay`'s own tool-body re-execution during replay (that family's "reads recorded judge verdicts" language applies only to its judge-dependent leaf; econevals has no judge leaf, so there is no analogous "recorded verdict, never re-derived" component here — every leaf is deterministic and is actively re-verified). §5's text is now corrected to say "zero model calls," not "no bridge subprocess." `docs/econevals_adapter_status.md`'s own status prose already described the real behavior correctly; only this spec section's wording was stale.
- **Milestone 3 build note (test-scoped `pins.max_steps` shrinking).** The pilot cases are pinned at the full upstream `num_attempts = 100` periods; running a live 100-period episode through the bridge for every harness/replay test would cost roughly 100 subprocess round-trips per episode (procurement's `evaluate_alloc` call alone measured ~1s/call). `tests/test_econevals_environment.py`/`tests/test_econevals_replay.py` instead build a test-scoped `CaseManifest` copy with a much smaller `payload.pins.max_steps`/`episode.max_logical_actions` (2–3), keeping the REAL pinned `generated_instance`/`gold_optimum` data and REAL bridge calls for every period, with `content_sha256` recomputed through the kernel's own `case_content_sha256` resolver (never hand-typed) so `run_episode`'s own hash cross-check passes for the right reason. This shortens test runtime without touching the checked-in pilot corpus or hand-wiring around the scheduler.
