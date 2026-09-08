# Implementation specification — `agenticpay.bilateral` adapter for the AERead shared-runner kernel

**Scope.** Wrap SafeRL-Lab/AgenticPay (arXiv 2602.06008, upstream pinned at commit
`1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`, MIT) as an AERead family. "agenticpay" is
AERead's family name for this pinned import; "upstream" always means the checkout at that
commit. Tonight wraps only the **bilateral** topology (`single_buyer_product_seller`, one
buyer seat, one seller seat — the shared-runner contract's Mode B / tau3-style turn loop).
The other seven multi-party topologies are enumerated and pinned but deferred (§6, Mode C).
GlobalScore/BuyerScore/SellerScore are declared as a **labeled compatibility result**, never
AERead's primary estimand, per the audit note this milestone was scoped against.

**Governing facts** (verified in recon; do not re-derive):

- `agenticpay/core.py`'s `BaseEnv.step()` takes plain `buyer_action`/`seller_action` strings
  and returns `(observation, reward, terminated, truncated, info)`; no LLM/VLM import is
  reachable from `step()` or `reset()` themselves.
- `agenticpay/__init__.py` unconditionally imports `agenticpay.agents.base_agent`, whose
  package `__init__.py` unconditionally imports `buyer_agent.py`/`seller_agent.py`, both of
  which do `from loguru import logger`. `loguru` is not declared in `requirements.txt` and is
  **not present in the project's 3.11 venv** (`ModuleNotFoundError: No module named 'loguru'`,
  reproduced from this worktree). `models/base_vlm.py` additionally requires `numpy`
  unconditionally. All concrete LLM/VLM backends (`openai_llm.py`, `vllm_lm.py`,
  `sglang_vlm.py`, `qwen3_vl.py`, …) are import-guarded with `try/except ImportError` in
  `agenticpay/models/__init__.py` and are never reached by a plain `import agenticpay`.
- `env.reset()` calls `self.buyer_agent.initialize(context)` / `self.seller_agent.initialize(context)`
  — the constructor's `buyer_agent`/`seller_agent` arguments must be real objects with an
  `.initialize()` method, but nothing under `envs/` ever calls `.generate()`/`.act()` on them;
  a minimal scripted stand-in (`.initialize()` stores context, no LLM) satisfies the contract.
  Verified end-to-end (§4).
- **31 basic tasks** = every `agenticpay/envs/<topology>/Task*.py` file, counted directly
  (glob, not inferred): 4 files each for 7 topologies + 3 for `single_buyer_product_seller`
  (`Task1BasicPriceNegotiation`, `Task2ClosePriceNegotiation` subclasses it with tighter
  `price_tolerance`, `Task3CloseToMarketPriceNegotiation` subclasses it toward market price).
  `Task2`/`Task3` add no new mechanics — same `step()`/scoring, different constructor
  defaults — so they are wrapped as parameterizations of one environment class, not three
  independent verifier surfaces.
- **"Realistic" tasks do not exist as separate `envs/` files.** The 25 multimodal,
  multi-dimensional scenarios per topology (`s1`–`s25`, contract-mode MAUT scoring) are
  defined only inside runnable CLI *driver scripts* under
  `agenticpay/examples/<topology>/Task*_s*_*.py`. Every one of those scripts unconditionally
  imports `BuyerAgent`, `SellerAgent`, and 3–5 concrete LLM/VLM backend classes
  (`OpenAIVLM`, `CustomLLM`, `Qwen3VL`, `VLLMLLM`, `SGLangVLM`) at module top level — **no**
  try/except guard. Importing or executing these scripts is out of scope entirely; the
  adapter statically extracts each scenario's literal `contract_config`/`product_info` dict
  from source (never imports the script) and replays it through the same `Task1BasicPriceNegotiation`
  class used for the basic tasks.
- **Verified inconsistency, resolved per Gate 1 (enumerate, don't trust a claimed count):**
  the README claims "160 Benchmark Tasks (4 scenarios × 8 topologies × 5 tasks)"; the task
  brief's prior research claimed "111 (31 basic + 80 realistic)". Neither matches the pinned
  checkout enumerated directly: 31 files under `envs/`, and 25 scenario driver scripts × 8
  topologies = 200 (plus 25 `text_only` duplicates scoped to `single_buyer_product_seller`
  only) under `examples/`. This document records the actual enumerated counts and their
  content digests rather than adopting any of the three numbers.

## 1. Corpus enumeration and content digest (Gate 1)

| Set | Enumeration rule | Count (this pin) | Tonight |
|---|---|---|---|
| basic (bilateral) | `agenticpay/envs/single_buyer_product_seller/Task*.py`, one manifest per class × declared `(buyer_max_price, seller_min_price)` pair | 3 files → 3 cases | all 3 |
| realistic (bilateral) | literal `contract_config` dict extracted from `agenticpay/examples/single_buyer_product_seller/Task{4..28}_s{1..25}_*.py` (image-grounded scenario set; `text_only/` variants of the same 25 are a separate, deferred set) | 25 scenarios | all 25 |
| **tonight's total** | | | **28 cases** |
| basic, other 7 topologies | `agenticpay/envs/<topology>/Task*.py` | 28 files | enumerated, deferred |
| realistic, other 7 topologies | same extraction rule, per topology | 175 scenarios | enumerated, deferred |
| `text_only/` realistic duplicates | `agenticpay/examples/single_buyer_product_seller/text_only/Task*.py` | 25 files | enumerated, deferred |

The importer (`cases.py`, mirroring `aeread_families/tau3_retail/cases.py`) writes one
`CaseManifest` per case plus a `pins.json`:

```json
{
  "upstream_repo": "SafeRL-Lab/AgenticPay",
  "upstream_commit": "1ff4e1a2686eac6a07ff559df6d50329c6fd9f69",
  "upstream_license": "MIT",
  "env_source_sha256": {"Task1_basic_price_negotiation.py": "<sha256>", "...": "..."},
  "scenario_extraction_sha256": {"s01_beauty_product": "<sha256 of extracted contract_config, canonical JSON>", "...": "..."},
  "enumerated_counts": {"basic_bilateral": 3, "realistic_bilateral": 25, "basic_total": 31,
                         "realistic_total_examples_dir": 200, "text_only_bilateral": 25},
  "bridge_python": "3.11", "bridge_deps": ["loguru==0.7.3", "numpy==2.4.6"]
}
```

`case_id = agenticpay.bilateral.<split>.<n>` (dot/underscore, no colon; grammar-checked
against `is_exportable_id`), e.g. `agenticpay.bilateral.basic.task1`,
`agenticpay.bilateral.realistic.s01_beauty_product`. `content_sha256` (kernel-computed)
covers the manifest payload — which embeds the extracted `contract_config`/price bounds
verbatim plus the source-file digest, not a copy of the whole driver script (which is never
executed and carries irrelevant CLI/argparse code).

The importer must run twice and produce byte-identical manifests (parity check P1, §5),
exactly as tau3's `cases.py` does.

## 2. Verifier declaration (per `docs/research/verifier_taxonomy.md`)

All leaves are deterministic (`evaluation_class="deterministic"`); there is no LLM judge
anywhere in upstream's retail-negotiation scoring path, so `composition="leaf"` throughout —
no `stochastic_estimator`, no `rater_judge`.

| Leaf | `verifier_family` | `reference_kind` | Input scope | Role |
|---|---|---|---|---|
| `agenticpay_deal_reached` | `rule_constraint` | `constraint_satisfaction` | terminal state | Did negotiation terminate `agreed` vs `timeout`? Independent of quality. |
| `agenticpay_contract_legality` | `rule_constraint` | `constraint_satisfaction` | action | Per-action: does a contract-mode offer satisfy declared `continuous_bounds`/`discrete_options`? (§4 golden 3) |
| `agenticpay_buyer_surplus_share` | `objective_reference` | `outcome_support_normalized` | terminal state | `u_b = (buyer_max_price − p) / Z` where `Z = buyer_max_price − seller_min_price`; a **ZOPA support bound**, `S_min=0, S_max=1`, reported only when `Z>0` (§4 golden 5 otherwise). |
| `agenticpay_seller_surplus_share` | `objective_reference` | `outcome_support_normalized` | terminal state | `u_s = (p − seller_min_price) / Z`, same bound, same degeneracy rule. |
| `agenticpay_upstream_global_score` | *(not a sanctioned kernel leaf — see below)* | — | terminal state | Upstream's `GlobalScore`/`BuyerScore`/`SellerScore`, recorded as a **labeled compatibility artifact**, exactly as `tau3_upstream_reward` is recorded. |

`agenticpay_buyer_surplus_share`/`agenticpay_seller_surplus_share` are `objective_reference`
leaves, so the kernel's `VerifierSpec` requires an `ObjectiveScopeSpec`: `feasible_set` =
"either side's offer sequence within `[seller_min_price, buyer_max_price]`",
`information_set` = "own reservation price only; counterpart's is private", `horizon` =
`max_rounds`, `environment_condition`/`opponent_condition` = the paired scripted-counterpart
policy for that case, `direction="maximize"`, `units="share_of_zopa"`.

**`GlobalScore` is a weighted composite** (`D·discount + W·Q·discount + E·discount`, or
`FailurePenalty`) that the audit already flags as not an optimum. Per §10 of the taxonomy, a
`weighted` leaf requires declared normative weights and a decision-problem justification;
upstream's `D=10, W=80, E=10, F=15` are tuning constants with no such justification on
record, so this adapter does **not** instantiate it as a kernel `MeasurementLeafSpec`. It is
sealed as evidence and reported in the receipt table exactly like `tau3_upstream_reward` —
never pooled with the two support-normalized leaves above, never presented as AERead's
primary result.

## 3. Adapter boundary (mirrors `refund_external_benchmark_integration.md` §4)

**Upstream owns:** `NegotiationState`/`ConversationMemory`/`NegotiationInfo`; price and
contract extraction regexes (`_extract_price`, `_extract_contract`, `_normalize_contract`);
contract legality (`_validate_contract`); agreement detection (`_check_agreement`); the
`GlobalScore`/`BuyerScore`/`SellerScore`/`FailurePenalty` formulas and their `D/W/E/F/γ`
constants; `max_rounds` truncation.

**AERead owns:** resolution of the pinned source into an immutable `RunPlan`; the
`ScriptedAgent` shim (`.initialize()` no-op, satisfying the constructor's duck-typed
`BaseAgent` requirement without importing `agents.buyer_agent`/`agents.seller_agent` or
`loguru`) — **but see §6**; canonical events, visibility, evidence, replay, receipts;
the two support-normalized measurement leaves and the contract/action legality leaf;
detection of malformed/unparseable action text (upstream's own `_extract_price`/`_extract_contract`
return `None` and silently no-op — the adapter must record this as typed evidence, not let it
pass through as an implicit "no offer this round", §4 golden 4); the degenerate-`Z`
quarantine flag (§4 golden 5).

**Bridge.** The project's 3.11 venv cannot import `agenticpay` (missing `loguru`, read-only
venv — never `pip install` into it). An isolated venv was provisioned and verified this
session at `/Users/sunzeyu/Documents/econ benchmark/bridges/agenticpay-venv`
(`python3.11 -m venv`, then `pip install loguru numpy` only — every heavy LLM/VLM dependency
in `requirements.txt` is unreached and unneeded). `sys.path.insert(0, <upstream checkout>)`
then `import agenticpay` and direct class imports succeed. A `tools/agenticpay_bridge/provision.sh`
should be added mirroring `tools/tau2_bridge/provision.sh`'s "prove the interpreter can
actually do the one job it has" pattern — pin `loguru`/`numpy` versions in a checked-in
`requirements.txt`, not just installed ad hoc.

**Proposed module layout** (`src/aeread_families/agenticpay_bilateral/`):

```
__init__.py       # registers family_id "agenticpay.bilateral", version "0.1.0"
cases.py          # importer: enumerate envs/ + statically extract examples/ contract_config -> CaseManifest + pins.json
environment.py    # AgenticpayBilateralState, phase graph (buyer_turn / seller_turn, tau3-style alternation), step()
tools.py          # none — no tool-call surface; both seats emit one action string per turn
harness.py        # ScriptedAgent shim + the bridge-subprocess call into upstream env.step()
measurement.py    # 3 MeasurementLeafSpec declarations (deal_reached, contract_legality, surplus_share x2) + scorers
parity.py         # bridge-subprocess re-execution parity runner (§5)
replay.py         # offline replayer (zero network; still needs the bridge python for step() re-execution — see UNRESOLVED below)
```

`cases/agenticpay_bilateral/basic/*.json`, `cases/agenticpay_bilateral/realistic/*.json`
(mirrors `cases/tau3_retail/base/`).

## 4. QC Gate-2 goldens — five concrete instances, empirically verified

All five were run end-to-end through the provisioned bridge venv against
`Task1BasicPriceNegotiation` this session (`buyer_max_price=120, seller_min_price=80,
initial_seller_price=120` unless noted; `D=10, W=80, E=10, F=15, γ=0.99` — the constructor's
**actual current defaults**, which disagree with the stale docstring literals `D=30,W=55,E=15`
inside `_calculate_global_score`; a corpus/doc footnote, not a scored discrepancy).

| Golden | Trajectory | Verified result |
|---|---|---|
| **Successful** | buyer/seller both converge to `$100` at round 2 (`Z=40`, `u_b=u_s=0.5`, `Q=1.0`, `discount=0.99¹`) | `agreed_price=100.0`, `termination_reason="agreed"`, `GlobalScore=99.0` (`(10+80·1.0+10)·0.99`); `agenticpay_buyer_surplus_share=0.5`, `agenticpay_seller_surplus_share=0.5` |
| **Valid but poor** | both offer `$118` at round 1 (`u_b=0.05, u_s=0.95, Q=0.19`) — legal, one-sided, agreement still reached | `agreed_price=118.0`, `GlobalScore=35.2` (`(10+80·0.19+10)·1.0`); shares `0.05`/`0.95` preserved as diagnostics, not collapsed |
| **Invalid or unauthorized** | contract-mode: seller offers `delivery_days=10` (declared bound `max=7`) and `return_policy="lifetime"` (not in declared enum) | `_validate_contract` rejects it; `state.metadata["seller_contract"]` stays `None`; **no state mutation, no round score**; a legal resubmission next round reaches `GlobalScore=99.0` unaffected — `agenticpay_contract_legality=fail` for the rejected action only |
| **Malformed / operational failure** | buyer sends unparseable text (`"this is not a price at all, just chatter"`) | Upstream silently no-ops (`buyer_price` stays unset that round, no crash, no distinct penalty) — **the adapter must flag this as typed `parse_failure` evidence**, since upstream's own trace is indistinguishable from "buyer chose not to move"; left unflagged, a downstream analysis would conflate a parser miss with a negotiation tactic |
| **Degenerate reference** | `buyer_max_price=90 < seller_min_price=100` (`Z=-10≤0`); both offer `$95`, tolerance-agreement still fires | `valid_range=False` forces the `FailurePenalty` branch (`GlobalScore=-0.0`) even though a nominal price exists; `agenticpay_buyer_surplus_share`/`_seller_surplus_share` must be reported **`denominator_degenerate`**, never a fabricated `u_b`/`u_s` |

## 5. Test plan — e2e, replay, parity

- **e2e** (`tests/test_agenticpay_bilateral_environment.py`): construct all 28 tonight-scope
  cases; drive each through a fixed scripted-agent policy table (one script per stratum:
  converge-in-range, one-sided, illegal-contract, malformed-text, degenerate-`Z`); assert
  `terminated`/`truncated`, `agreed_price`, and both surplus-share leaves match hand-computed
  values (§4's five numbers become five unit-test fixtures verbatim).
- **Replay** (`tests/test_agenticpay_bilateral_replay.py`): record the full decision log
  (parsed buyer/seller action strings, per-step `state.metadata`, `info` dict) for every case;
  replay by re-feeding the recorded action strings through a **fresh** env instance built from
  the pinned manifest and require identical `agreed_price`, `GlobalScore`, and both leaves.
  Because upstream's own `step()` is the only implementation of the scoring formulas (no
  separate "gold" oracle to replay against, unlike tau3's `EnvironmentEvaluator`), replay
  parity here **is** the correctness oracle — it must run with zero network calls but still
  needs the bridge Python (see UNRESOLVED below).
- **Parity** (`tests/test_agenticpay_bilateral_parity.py`, `parity.py`): for each of the 28
  cases, run the identical scripted trajectory twice through independent bridge subprocess
  invocations and require byte-identical `info` dicts and `state.metadata` — this is a
  determinism check (no separate upstream CLI/leaderboard path exists to diff against, unlike
  tau3's `tau2 evaluate-trajs`), so "parity" here means **reproducibility under re-execution**,
  not agreement with an external oracle. Additionally cross-check the hand-derived formulas
  in §4 against upstream's `_calculate_global_score` source directly (already done in this
  spec's recon) as the "independent oracle" required by Gate 2 check 1, since no second
  implementation of the scoring formula exists to import.

## 6. Stated limits and deferred scope

- **Mode C (multi-party topologies) is entirely deferred.** All 7 remaining topologies
  (`only_multi_buyer`, `only_multi_seller`, `only_multi_products`, `multi_buyer_multi_seller`,
  `multi_buyer_multi_products`, `multi_products_multi_seller`,
  `multi_buyer_multi_products_multi_seller`) are enumerated (28 basic + 175 realistic files,
  §1) but not wrapped. They need a housing-style seating/allocation phase model (parallel vs.
  sequential sub-modes are already named in their filenames) rather than the tau3-style
  strict two-seat alternation this spec uses; no phase graph is designed for them here.
- **`text_only/` realistic duplicates (25 files)** are enumerated but not wrapped tonight;
  they appear to reuse the same `contract_config` shape without images, so the extraction
  rule likely generalizes, but this is unverified.
- **The `ScriptedAgent` shim bypasses, rather than fixes, the `loguru` import gap** — a real
  upstream packaging gap (an undeclared, unconditionally-imported dependency), not ours to
  fix. The bridge venv works around it; if upstream ever guards that import, the shim and the
  bridge-venv requirement should be re-examined together.
- **No separate gold oracle exists for the scoring formulas** (§5): parity is
  reproducibility-under-re-execution plus a manual source cross-check, not an independent
  implementation comparison the way tau3's judge/DB parity is. A stronger check would require
  an independently-authored re-implementation of `_calculate_global_score`, which this spec
  does not schedule.
- **`docs/operations/benchmark_qc.md` does not exist on `main`** (its Gate 1/Gate 2 language quoted in
  this spec's §0/§4 headers was read from the real, unmerged file at commit `2b831fec` on
  `origin/codex/procurement-harness-bakeoff`) — logged to the ledger (below) rather than
  re-derived, consistent with five other sibling adapter tasks' entries.
- **UNRESOLVED**, same class of open question tau3's spec raised and left to the kernel
  owner: does `execute_plan_cell()` build a `ToolRuntime`/driver loop this adapter can attach
  to, or does the pilot need its own adapter-owned driver (this spec assumes the latter,
  matching tau3)? Replay (§5) needs the bridge Python at replay time, not just at recording
  time — is a Python-version-crossing replay path acceptable, or must replay be
  bridge-independent (e.g., by vendoring the ~150-line scoring formula with a provenance
  header instead of re-executing `step()`)? This spec assumes bridge-dependent replay is
  acceptable for now; revisit if the paper requires network-free replay on the project's own
  3.11 interpreter without any subprocess.

## 7. Milestone 1 implementation note (cases + environment)

Delivered as `src/aeread_families/agenticpay_bilateral/{__init__,cases,environment,
agenticpay_bridge,agenticpay_bridge_driver}.py`, `cases/agenticpay_bilateral/{basic,
realistic}/*.json`, `cases/agenticpay_bilateral/pins.json` (one shared pin record for both
splits, not duplicated per split — the pin fields are family-wide, unlike tau3's single-split
`base/pins.json`), and `tools/agenticpay_bridge/{provision.sh,requirements.txt,README.md}`.
`measurement.py`, `harness.py`, `parity.py`, and `replay.py` are not built yet (Milestones
2/3); `build_scorer` raises `NotImplementedError` until `measurement.py` lands, satisfying
`PluginRegistry`'s structural requirement without implementing the leaves.

**Deviation from §3's proposed module layout:** the ScriptedAgent shim and the
bridge-subprocess call into upstream `env.step()` live in their own top-level modules,
`agenticpay_bridge.py`/`agenticpay_bridge_driver.py` — mirroring tau3_retail's
`tau2_bridge.py`/`tau2_bridge_driver.py` split exactly — rather than inside `harness.py` as
originally sketched. `harness.py` (when built) is reserved for a scripted-policy test driver
in tau3_retail's sense (exercises the kernel plugin API end to end for tests), not the bridge
itself; the bridge is required infrastructure for `environment.py`'s `step()` to do anything
real, independent of any test harness.

**Bridge state model:** upstream's environment object is not JSON-serializable (a live
`ConversationMemory`/`NegotiationState`/`Enum`-valued status, not a plain dict the way
tau2-bench's `RetailDB` is), so `agenticpay_bridge.replay_round` reconstructs the environment
from scratch on every call and replays the full ordered `(buyer_action, seller_action)`
history before applying the newly requested round — O(rounds) per call, fine against
`max_rounds=20` for scripted trajectories. `environment.py`'s own kernel-level state carries
that same history plus a `pending_buyer_message` buffer (the buyer phase's `step` only
buffers; only the seller phase's `step` calls the bridge and can terminate the episode).

**Three upstream quirks discovered and worked around in this adapter (not fixed, not
ledgered — all three are upstream-library behavior, not a defect in AERead's own
runner/kernel):**
- `_calculate_reward`/`_calculate_seller_reward`/`_calculate_buyer_reward` call `print(...)`
  unconditionally on every terminal round, corrupting the driver's one-JSON-object-on-stdout
  protocol unless upstream's own stdout is redirected for the duration of every call
  (`agenticpay_bridge_driver.py`).
- `info["buyer_utility"]`/`info["seller_utility"]` are always `null` in the dict `step()`
  returns, even on a terminal round with a real, non-degenerate contract utility: `_get_info()`
  reads `self.state.metadata.get("buyer_utility")` *before* the score-calculation methods that
  are the only place upstream ever populates it run. The driver reads the correct,
  already-computed values off `env.state.metadata` after `step()` returns instead of
  recalculating `u_b`/`u_s` itself — see `_overlay_contract_utilities`
  (`agenticpay_bridge_driver.py`).
- `Task1BasicPriceNegotiation.step`'s own truncation check
  (`elif self.current_round >= self.max_rounds`) reads `current_round` *before* that round's
  own increment, so a non-converging negotiation actually plays `max_rounds + 1` real rounds
  (verified empirically against the pinned checkout: with `max_rounds=20`, upstream's own
  `"timeout"` fires with `info["round"] == 21`, not 20) before upstream's own `"timeout"`
  termination reason appears. `cases.py`'s `episode.max_logical_actions` accounts for this
  (`2 * (max_rounds + 1)`, not `2 * max_rounds`), and `environment.py`'s `phases()` sizes each
  phase's own per-seat cap to `max_rounds + 1` for the same reason.

**A third, adapter-side normalization (not an upstream defect):** two of the 25 realistic
scenarios (`s16`–`s20`'s `extra_condiments`, `s21`–`s25`'s `include_utilities`) declare a
boolean-valued discrete contract term, so their literal `discrete_weights` dicts use Python
`True`/`False` as dict keys in source. A case manifest can only hold string dict keys (JSON
has no other kind); the importer coerces `True`/`False` -> `"true"`/`"false"` the same way
`json.dumps` itself would (`cases._json_dict_key`), and the bridge driver restores the exact
Python bool a live upstream call needs, scoped narrowly to `discrete_weights[term]` where the
paired `discrete_options[term]` is itself boolean-valued
(`agenticpay_bridge_driver._restore_bool_discrete_keys`). Left unhandled, the string key would
silently miss upstream's own `dw.get(value, 0.0)` lookup for a real (JSON-parsed) boolean
contract value and corrupt the utility calculation for exactly these two terms.

**`world_seed`:** basic cases use the env class's numeral (`Task1BasicPriceNegotiation` ->
`1`); realistic cases use the scenario number (`s01` -> `1`, `s16_food_delivery_1` -> `16`).
These are not globally unique across the two splits (`agenticpay.bilateral.basic.task1` and
`agenticpay.bilateral.realistic.s01_beauty_product` both carry `world_seed=1`) — harmless,
since `case_id` (not `world_seed`) disambiguates identity everywhere the kernel checks it, but
noted here since tau3's single-split corpus never had to make this choice.

## 8. Milestone 2 implementation note (measurement + goldens)

Delivered as `measurement.py` (the four sanctioned leaves from section 2's table --
`agenticpay_deal_reached`, `agenticpay_contract_legality`, `agenticpay_buyer_surplus_share`,
`agenticpay_seller_surplus_share` -- plus their scorers and a `build_action_diagnostics`
helper) and `tests/test_agenticpay_bilateral_measurement.py` (pure leaf/scorer unit tests, the
five QC Gate-2 goldens, and two component-parity tests). `environment.py`'s `build_scorer`
now delegates to `measurement.build_scorer`; `harness.py`, `parity.py`, and `replay.py` remain
unbuilt (Milestone 3).

**Two forced deviations from this document's literal section 2 table**, both because the
kernel's real `VerifierSpec`/`ReferenceSpec` enums (`aeread.shared_runner.measurement`) are
stricter than this spec's prose, exactly the class of deviation `tau3_retail.measurement`
already documents for its own "transcript" -> "trajectory" case -- not a re-reading of the
estimand's meaning:

- `agenticpay_contract_legality` declares `input_scope="trajectory"`, not `"action"` (the
  kernel's `EstimandSpec` only accepts `{"answer", "terminal_state", "trajectory",
  "distribution"}`). The leaf still evaluates one action's legality per round; "trajectory"
  names the ordered per-round sequence it is drawn from.
- `agenticpay_buyer_surplus_share`/`agenticpay_seller_surplus_share` declare
  `reference_kind="outcome_support_max"`, not `"outcome_support_normalized"` (the kernel's
  `ReferenceSpec` only accepts, for an `objective_reference` verifier, `{"exact_optimum",
  "objective_lower_bound", "objective_upper_bound", "comparison_baseline",
  "outcome_support_min", "outcome_support_max"}`). `S_min=0` is recorded as a fixed
  `reference_values` entry on every score, not as a second `ReferenceSpec` (`VerifierSpec`
  carries exactly one).

**`environment.py` grew one new field this milestone, not just `measurement.py`:** a
per-round `round_trace` (before/after `buyer_price`/`seller_price`/`buyer_contract`/
`seller_contract`, plus a shallow "attempted a contract" heuristic -- a `<contract>` tag in
the raw message, never a re-implementation of `_extract_contract`'s JSON parsing), exposed
through `terminal()`/`outcome()`. This was necessary to satisfy section 3's explicit "AERead
owns... detection of malformed/unparseable action text" and "the contract/action legality
leaf" without re-deriving upstream's own `_extract_price`/`_extract_contract`/
`_validate_contract` logic: every completed round already calls upstream's `step()` once
through the bridge and gets back a fresh `info` dict for exactly that round, so retaining it
costs nothing extra against upstream (no new bridge calls), only a small, additive state
field.

**Malformed-text detection is a necessary, not sufficient, heuristic:** `measurement.py`'s
`_could_not_have_parsed_a_price` flags a message only when it contains zero digit
characters -- provably unable to satisfy any of upstream's own `_extract_price` regex
patterns (all require at least one digit), so this never produces a false negative. It
cannot detect every parse failure (e.g. a digit-bearing message in a format upstream's regex
still rejects), which is the intentionally weaker, honestly-labeled claim: a `parse_failure`
diagnostic, never promoted to a leaf's primary measurement, per section 4 golden 4's own
"upstream's own trace is indistinguishable from 'buyer chose not to move'" framing.

**Component parity (spec section 5's "our recorded scoring equals upstream computed
scoring"):** `test_surplus_share_leaves_recombine_to_upstream_recorded_global_score_{basic,
contract}_mode` recombine the two surplus-share leaves' own scorer output through upstream's
published `Q = 4 * u_b * u_s` formula and its actual current default weights (`D=10, W=80,
E=10, γ=0.99`) and assert equality with `info["global_score"]` -- a real, bridge-executed
value, not a hand-derived one. This is the measurement-level bridge-gated cross-check
`tau3_retail.measurement` performs against `EnvironmentEvaluator`; the full
reproducibility-under-re-execution `parity.py`/`test_agenticpay_bilateral_parity.py` module
section 3/5 describes is still Milestone 3 scope, not built here.

## 9. Milestone 3 implementation note (scripted harness, end-to-end, replay)

Delivered as `harness.py` (`ScriptedAgenticpayBilateralHarness`) and `replay.py`
(`RecordedDecision`/`RecordedEpisode`/`RecordedResponseSource`/`replay_episode`/
`compare_episode_results`/`assert_replay_matches`/`score_replayed_episode`/
`replay_and_verify`), plus `tests/test_agenticpay_bilateral_replay.py`. `parity.py` (this
document's proposed module layout, section 3) remains unbuilt -- see
`docs/agenticpay_adapter_status.md`'s "known limits" for what that leaves unproven.

**Forced deviation from `tau3_retail.harness.ScriptedTau3RetailHarness`'s exact shape:**
this family declares no tool-call surface at all (`tools.py`: none), so
`ScriptedAgenticpayBilateralHarness` has nothing to hand a `ToolRuntime` to seal evidence
through. It instead seals one `agenticpay_bilateral_decision_served` event per served
decision directly through `EvidenceStore.append_event` -- the same primitive
`aeread.shared_runner.family_evaluation` already uses for its own non-tool evidence
(`episode_terminated`/`family_outcome_recorded`/`score_recorded`), not an invented
mechanism. This is a narrowing of the constructor signature (`evidence`, `script` -- no
`bridge`/`initial_db` parameters, since the harness itself never calls the bridge; only
`environment.py`'s own `step()` does, for the seller phase of each round), never a change
of what "sealed evidence" means.

**A real strengthening over `tau3_retail.replay`'s guarantee, verified rather than
assumed:** that module's own `compare_episode_results` needs a raw/content-only split
because upstream re-stamps a wall-clock `timestamp` on every replayed message. This
family's pinned upstream and bridge code were checked directly (`grep` for
`datetime`/`time.time`/`random`/`uuid` across `agenticpay/core.py`, the pinned
`single_buyer_product_seller` env files, and this adapter's own bridge/bridge-driver
modules) and introduce none of that anywhere in the replayed path, so
`agenticpay_bilateral.replay.StateComparison` asserts genuinely byte-identical final state
(`canonical_json_bytes(replayed.final_state) == canonical_json_bytes(original.final_state)`),
confirmed empirically for a two-round basic negotiation replayed through a second,
independent `AgenticpayBridge`/plugin instance from a JSON-round-tripped record.

**Scoring recomputation needs no bridge call**, unlike tau3.retail's DB-equivalence leaf
(which re-invokes `Tau2Bridge.evaluate_env` against the replayed database): every leaf this
family declares is a pure function of `EpisodeResult.terminal`/`round_trace`, both already
fully determined by the real, bridge-backed `step()` calls replay re-runs, so
`score_replayed_episode` takes only a scorer and the replayed episode.

Two full episodes were verified end to end with sealed evidence this milestone: a
two-round basic negotiation (`agenticpay.bilateral.basic.task1`) and a one-round
contract-mode negotiation (`agenticpay.bilateral.realistic.s01_beauty_product`), covering
both branches of `is_contract_mode` and exercising the `agenticpay_contract_legality` leaf
under replay. The remaining 26 pinned cases were validated at the payload/importer level in
Milestones 1-2 but not driven through a full scripted episode this milestone.
