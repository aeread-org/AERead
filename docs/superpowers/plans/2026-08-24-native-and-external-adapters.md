# Native Housing and External Benchmark Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that the public AERead SDK supports one clean native family and three scientifically faithful external benchmark adapters without adding upstream dependencies or family branches to core.

**Architecture:** Housing wraps its native economic state machine directly. Each external benchmark lives in an isolated adapter distribution registered by entry points; a source adapter materializes pinned upstream cases, an environment plugin executes AERead-controlled interactions, and an official bridge produces an admission parity report. The core runner sees only `aeread.sdk.v1` contracts.

**Tech Stack:** Python 3.10+, Pydantic 2, pytest; per-adapter virtual environments for EconEvals, tau3, and AgenticPay; no Harbor requirement.

**Spec:** [`docs/public_environment_and_external_adapter_spec.md`](../../public_environment_and_external_adapter_spec.md)

## Global Constraints

- Start only after [`2026-08-24-shared-runner-sdk-kernel.md`](2026-08-24-shared-runner-sdk-kernel.md) passes its completion gate.
- Housing PR #6 head `9e3a1a98a87cfbeecda249f89eef629c231ed7b2`, or a reviewed successor containing the same economic contracts, must be present before the Housing task begins.
- External source pins are exact: EconEvals `e1f2a40fec96f0d27f5414873c4310f2b5c51935`; tau3 dereferenced `v1.0.1` `fc0055dc4e0a316c3f83133267fbd6faaa770992`; AgenticPay `1ff4e1a2686eac6a07ff559df6d50329c6fd9f69`.
- An adapter must not make provider calls during case materialization, transition, replay, or deterministic scoring.
- Upstream code is not vendored into the `aeread` wheel.
- Every adapter declares source/license/patch/artifact hashes and the strongest evidence capabilities it actually demonstrates.
- Exact parity, component parity, and statistical agreement are distinct statuses.
- A score of zero is never used for missing, corrupted, or unobservable measurement.
- AgenticPay's first scope is text-only 1v1 multidimensional contract and one parallel 2-buyer × 2-seller task.

## Execution workflow

At implementation start, create one active goal for this plan and use each numbered task as a child milestone. Housing, EconEvals, tau3, and AgenticPay package scaffolds may be delegated as independent subtasks only after the adapter substrate types are frozen. Give each subtask exclusive ownership of its `adapters/<name>/` directory and tests. The primary worker owns shared manifest schema, admission logic, and final integration review.

Do not run all heavy upstream environments in parallel on one Python installation. Each adapter's lock/install/parity command runs in its own environment or subprocess. After each delegated result returns, inspect its source pin and parity fixture before accepting green tests.

---

## File structure

```text
src/aeread/adapters/
  __init__.py
  source.py                 shared checkout verification and materialization records
  admission.py              capability and official-parity report logic

src/aeread/families/
  housing_v1.py             native Housing plugin over housing_env.py

adapters/econevals_procurement/
  pyproject.toml
  src/aeread_adapter_econevals_procurement/{__init__,source,environment,verifier}.py
  fixtures/
  tests/

adapters/tau3_retail/
  pyproject.toml
  src/aeread_adapter_tau3_retail/{__init__,source,environment,verifier}.py
  fixtures/
  tests/

adapters/agenticpay/
  pyproject.toml
  src/aeread_adapter_agenticpay/{__init__,source,environment,verifier}.py
  fixtures/
  tests/

tests/shared_runner/test_housing_conformance.py
tests/shared_runner/test_external_adapter_admission.py
docs/adapter_admission/{housing_v1,econevals_procurement,tau3_retail,agenticpay}.md
```

The three external directories are independently installable plugin packages. Their heavy dependencies and upstream version constraints never appear in core `aeread` dependencies.

---

### Task 1: Add source verification and adapter admission records

**Files:**
- Create: `src/aeread/adapters/__init__.py`
- Create: `src/aeread/adapters/source.py`
- Create: `src/aeread/adapters/admission.py`
- Create: `tests/shared_runner/test_external_adapter_admission.py`

**Interfaces:**
- Consumes: `BenchmarkSourceAdapter`, `OfficialVerifierBridge`, `UpstreamSourceRef`, `CapabilityDeclaration`.
- Produces: `verify_checkout(path, source_ref) -> VerifiedCheckout`, `materialize(adapter, split, output_dir) -> MaterializationIndex`, `run_adapter_admission(adapter, bridge, fixtures) -> AdmissionReport`.

- [ ] **Step 1: Write source-pin and overclaim tests**

```python
def test_checkout_rejects_wrong_commit(tmp_git_repo) -> None:
    ref = UpstreamSourceRef(repo_url=URL, commit="0" * 40, license_spdx="MIT")
    with pytest.raises(SourcePinMismatch):
        verify_checkout(tmp_git_repo, ref)


def test_admission_rejects_exact_claim_for_component_parity(component_bridge) -> None:
    manifest = manifest_with(score_parity="exact")
    report = run_adapter_admission(manifest, component_bridge, FIXTURES)
    assert report.status == "rejected"
    assert "score_parity_overclaim" in report.failed_checks
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/shared_runner/test_external_adapter_admission.py -v`

Expected: FAIL because adapter source/admission utilities do not exist.

- [ ] **Step 3: Implement read-only checkout verification**

Resolve `git rev-parse HEAD`, remote URL, dirty status, expected source paths, and license text hash. Refuse a dirty checkout unless its patch is exported and its SHA-256 equals `patchset_sha256`. Never auto-checkout, reset, or mutate the contributor's upstream repository.

- [ ] **Step 4: Implement materialization and admission**

Write each `CaseManifest`, payload artifact, source index, and content hash atomically. Admission runs provider-free conformance plus every official fixture, checks the claimed capability against observed parity, and emits one signed-by-hash report with no numeric fallback for failed fixtures.

- [ ] **Step 5: Run admission tests**

Run: `pytest tests/shared_runner/test_external_adapter_admission.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aeread/adapters tests/shared_runner/test_external_adapter_admission.py
git commit -m "feat: add external adapter admission gate"
```

---

### Task 2: Admit Housing as the first clean native family

**Files:**
- Consume unchanged: `src/aeread/housing_env.py`
- Create: `src/aeread/families/housing_v1.py`
- Modify: `pyproject.toml`
- Create: `tests/shared_runner/test_housing_conformance.py`
- Create: `docs/adapter_admission/housing_v1.md`

**Interfaces:**
- Consumes: `HousingMarket.board()`, `submit_offers()`, `submit_responses()`, `submit_commits()`, `finished`, `result()`, `assignment_oracle()`.
- Produces: registered `aeread.housing_v1` environment/verifier and an admission report.

- [ ] **Step 1: Encode case-owner-confirmed semantics in fixtures**

Create one fixture where tenants offer simultaneously, scripted landlords respond, and tenants commit; one invalid offer; one landlord double-accept; one walk/no-match terminal. Expected results must be copied from Chenyu-reviewed Housing tests, not inferred from the runner.

- [ ] **Step 2: Write the failing conformance test**

```python
def test_housing_native_plugin_passes_provider_free_conformance(tmp_path) -> None:
    report = run_conformance(housing_plugin(), HOUSING_FIXTURES, tmp_path)
    assert report.status == "admitted"
    assert "paper_primary" in report.admitted_profiles
```

- [ ] **Step 3: Run the test and verify failure**

Run: `pytest tests/shared_runner/test_housing_conformance.py -v`

Expected: FAIL because the Housing plugin does not exist.

- [ ] **Step 4: Implement the phase graph and projections**

Declare `contact -> respond -> commit` phases. `contact` creates one tenant slot with one listing-directed channel; `respond` uses a controlled landlord policy unless landlord seats are explicitly under test; `commit` accepts `sign` or `walk`. `observe()` projects board plus only the tenant's own preferences/offers/holds or landlord's own listing/inbox.

- [ ] **Step 5: Implement atomic transitions and verifier**

Bridge `submit_offers`, `submit_responses`, and `submit_commits` without changing their validation. Map `result()` to realized allocation/welfare, per-tenant utility, per-landlord utility where Chenyu's rule defines it, and typed reference values from `assignment_oracle`. Keep welfare, tenant utility, landlord utility, and capture separate.

- [ ] **Step 6: Register and run conformance**

```toml
[project.entry-points."aeread.environments"]
housing_v1 = "aeread.families.housing_v1:plugin"

[project.entry-points."aeread.verifiers"]
housing_v1 = "aeread.families.housing_v1:verifier"
```

Run: `pytest tests/test_housing_*.py tests/shared_runner/test_housing_conformance.py -v`

Expected: all Housing-native and shared-runner tests PASS.

- [ ] **Step 7: Generate and inspect the admission report**

Run: `aeread env test housing_v1 --report docs/adapter_admission/housing_v1.md`

Expected: `paper_primary` admitted; `training` appears only if per-seat reward attribution is present in every fixture.

- [ ] **Step 8: Commit**

```bash
git add src/aeread/families/housing_v1.py pyproject.toml tests/shared_runner/test_housing_conformance.py docs/adapter_admission/housing_v1.md
git commit -m "feat: add native housing family plugin"
```

---

### Task 3: Build the EconEvals Procurement adapter

**Files:**
- Create: `adapters/econevals_procurement/pyproject.toml`
- Create: `adapters/econevals_procurement/src/aeread_adapter_econevals_procurement/__init__.py`
- Create: `adapters/econevals_procurement/src/aeread_adapter_econevals_procurement/source.py`
- Create: `adapters/econevals_procurement/src/aeread_adapter_econevals_procurement/environment.py`
- Create: `adapters/econevals_procurement/src/aeread_adapter_econevals_procurement/verifier.py`
- Create: `adapters/econevals_procurement/fixtures/basic_seed0.json`
- Create: `adapters/econevals_procurement/tests/test_procurement_adapter.py`
- Create: `docs/adapter_admission/econevals_procurement.md`

**Interfaces:**
- Consumes upstream: `generate_instance.py`, `run_procurement_experiment.py`, `opt_solver.evaluate_alloc`, precomputed `compute_opt` output.
- Produces: `econevals_procurement_v1` source/environment/verifier plugins and exact component parity on a materialized fixture.

- [ ] **Step 1: Materialize a deterministic fixture from the pinned checkout**

Run upstream generation once with seed 0 and the pinned Basic parameters: `num_inputs=3`, `num_alternatives_per_input=4`, `num_entries=12`, `NUM_ITEMS_PER_ENTRY_P=0.8`, `QUANTITY_PER_ITEM_P=0.5`, `OFFER_QTY_IN_SAMPLE_BUNDLE_P=0.5`, `MIN_EFFECTIVENESS=1`, `MAX_EFFECTIVENESS=3`, `agg_type="prod"`. Store the complete menu, budget, item groups, effectiveness, group weights, one scripted allocation, its official evaluation, and exact optimum in `basic_seed0.json`. Record that upstream budget generation uses global `np.random.uniform`; reproducibility is the artifact hash, not seed alone.

- [ ] **Step 2: Write the official evaluation parity test**

```python
def test_scripted_allocation_matches_official_evaluate_alloc(fixture) -> None:
    official = official_evaluate(fixture, fixture.scripted_allocation)
    aeread = procurement_verifier().score_fixture(fixture, fixture.scripted_allocation)
    assert aeread.metrics["cost"].value == official.cost
    assert aeread.metrics["utility"].value == official.utility
    assert aeread.metrics["feasible"].value == official.is_feasible
```

- [ ] **Step 3: Run the test and verify failure**

Run: `pytest adapters/econevals_procurement/tests -v`

Expected: FAIL because the adapter package does not exist.

- [ ] **Step 4: Implement source and environment plugins**

The source adapter validates the pin and reads materialized artifacts only. The environment exposes the upstream tools (`get_previous_purchase_data`, `get_equipment_information`, `get_budget`, `get_attempt_number`, notes, `submit_purchase_plan`) as typed actions. The runner owns every logical call and the maximum 40-query/10-submission budgets; Tenacity/provider retries are disabled in the adapter path.

- [ ] **Step 5: Implement verifier and oracle provenance**

Use upstream `evaluate_alloc` semantics for feasibility/cost/utility. Load the exact optimum from the hashed fixture; do not require Gurobi during ordinary execution or CI. Report native value, feasibility, optimum gap, and official normalized component separately.

- [ ] **Step 6: Run conformance and parity**

Run: `pytest adapters/econevals_procurement/tests -v`

Expected: all tests PASS with no provider call and no Gurobi import.

Run: `aeread benchmark parity econevals_procurement_v1 --report docs/adapter_admission/econevals_procurement.md`

Expected: exact component parity on the fixture and `paper_primary` admission for the materialized pilot.

- [ ] **Step 7: Commit**

```bash
git add adapters/econevals_procurement docs/adapter_admission/econevals_procurement.md
git commit -m "feat: adapt econevals procurement"
```

---

### Task 4: Build the tau3 Retail frozen-user adapter

**Files:**
- Create: `adapters/tau3_retail/pyproject.toml`
- Create: `adapters/tau3_retail/src/aeread_adapter_tau3_retail/__init__.py`
- Create: `adapters/tau3_retail/src/aeread_adapter_tau3_retail/source.py`
- Create: `adapters/tau3_retail/src/aeread_adapter_tau3_retail/environment.py`
- Create: `adapters/tau3_retail/src/aeread_adapter_tau3_retail/verifier.py`
- Create: `adapters/tau3_retail/fixtures/pilot_task_ids.json`
- Create: `adapters/tau3_retail/tests/test_tau3_adapter.py`
- Create: `docs/adapter_admission/tau3_retail.md`

**Interfaces:**
- Consumes upstream: `data/tau2/domains/retail/{db,policy,tasks}.json`, `src/tau2/domains/retail/environment.py`, half-duplex orchestrator semantics, `evaluate_simulation` component evaluators.
- Produces: `tau3_retail_v1` with candidate assistant, controlled user, tool environment, and component parity.

- [ ] **Step 1: Freeze the 18-task pilot identity**

Write these reviewed `retail/base` pilot IDs into the fixture, preserving the declared strata from `docs/refund_external_benchmark_integration.md`: `5`, `10`, `11`, `14`, `16`, `28`, `30`, `46`, `48`, `53`, `73`, `82`, `83`, `84`, `91`, `103`, `104`, `108`. Record the source commit, policy hash, database hash, and user-simulator profile hash. Reject any materialization whose IDs or content hashes drift.

- [ ] **Step 2: Write half-duplex and terminal-state tests**

```python
def test_tau3_turn_order_and_db_parity(scripted_fixture) -> None:
    receipt = run_scripted_tau3_fixture(scripted_fixture)
    assert receipt.outcome["terminal_db_hash"] == scripted_fixture.expected_db_hash
    assert receipt.score.metrics["db"].value == 1.0
    assert alternating_roles(receipt) == ("user", "assistant")
```

- [ ] **Step 3: Run the test and verify failure**

Run: `pytest adapters/tau3_retail/tests -v`

Expected: FAIL because the adapter package does not exist.

- [ ] **Step 4: Implement source and environment plugins**

Map the assistant, frozen user simulator, and tool environment to declared half-duplex phases. Preserve tau3 policy/tool semantics and record tool calls as structured actions. The frozen user's exact agent configuration is part of the controlled counterpart profile, not hidden environment state.

- [ ] **Step 5: Implement component verifier**

Reproduce deterministic DB/environment and action checks from `evaluate_simulation`. Store communicate and NL-assertion judge results in separate metrics with evaluator-agent provenance. Do not multiply unavailable judge results into the deterministic primary score.

- [ ] **Step 6: Run pilot parity**

Run: `pytest adapters/tau3_retail/tests -v`

Expected: exact deterministic component parity for all fixtures.

Run: `aeread benchmark parity tau3_retail_v1 --report docs/adapter_admission/tau3_retail.md`

Expected: deterministic components admitted; judge agreement labeled statistical or not evaluated.

- [ ] **Step 7: Commit**

```bash
git add adapters/tau3_retail docs/adapter_admission/tau3_retail.md
git commit -m "feat: adapt tau3 retail tasks"
```

---

### Task 5: Build the AgenticPay text-only 1v1 adapter

**Files:**
- Create: `adapters/agenticpay/pyproject.toml`
- Create: `adapters/agenticpay/src/aeread_adapter_agenticpay/__init__.py`
- Create: `adapters/agenticpay/src/aeread_adapter_agenticpay/source.py`
- Create: `adapters/agenticpay/src/aeread_adapter_agenticpay/environment.py`
- Create: `adapters/agenticpay/src/aeread_adapter_agenticpay/verifier.py`
- Create: `adapters/agenticpay/fixtures/text_1v1_contract.json`
- Create: `adapters/agenticpay/tests/test_agenticpay_1v1.py`

**Interfaces:**
- Consumes upstream: `agenticpay/core.py`, single buyer/seller environment, structured contract fields, score weights.
- Produces: bilateral `agenticpay_text_v1` environment and component verifier.

- [ ] **Step 1: Write a scripted terminal parity fixture**

Capture private buyer/seller limits, public product terms, contract schema, scripted offer/counter/accept actions, expected agreement, price/terms, round count, utilities, and every Global/Buyer/Seller score component.

- [ ] **Step 2: Write the failing parity test**

```python
def test_agenticpay_1v1_script_matches_upstream(fixture) -> None:
    upstream = fixture.expected_official
    receipt = run_aeread_scripted(fixture)
    assert receipt.outcome["contract"] == upstream["contract"]
    assert receipt.score.metrics_as_numbers() == upstream["score_components"]
```

- [ ] **Step 3: Run the test and verify failure**

Run: `pytest adapters/agenticpay/tests/test_agenticpay_1v1.py -v`

Expected: FAIL because the adapter package does not exist.

- [ ] **Step 4: Implement isolated imports and bilateral phases**

Keep AgenticPay, loguru, Torch, vLLM, and SGLang out of core imports. Map buyer/seller turns to explicit slots and one directed channel each. Project each seat's private reservation value and conversation history separately.

- [ ] **Step 5: Implement compatibility metrics without optimum claims**

Expose GlobalScore, BuyerScore, SellerScore, deal, utility, efficiency, time, and failure components with the upstream weights. Mark them `comparative_or_human_judged` or descriptive as appropriate; do not label the weighted score as a certified optimum.

- [ ] **Step 6: Run 1v1 tests**

Run: `pytest adapters/agenticpay/tests/test_agenticpay_1v1.py -v`

Expected: exact terminal and component parity.

- [ ] **Step 7: Commit**

```bash
git add adapters/agenticpay
git commit -m "feat: adapt agenticpay bilateral contracts"
```

---

### Task 6: Extend AgenticPay to parallel 2×2 multi-channel negotiation

**Files:**
- Modify: `adapters/agenticpay/src/aeread_adapter_agenticpay/environment.py`
- Modify: `adapters/agenticpay/src/aeread_adapter_agenticpay/verifier.py`
- Create: `adapters/agenticpay/fixtures/text_parallel_2x2.json`
- Create: `adapters/agenticpay/tests/test_agenticpay_2x2.py`
- Create: `docs/adapter_admission/agenticpay.md`

**Interfaces:**
- Consumes upstream: `Task1_parallel_two_buyer_two_seller_negotiation.py` eight directed action arguments and pair-specific memories.
- Produces: multiple edge-level `DecisionSlot` objects per buyer/seller seat, pending buyer-action state between declared subphases, private projections, one upstream round transition, and component parity.

- [ ] **Step 1: Write the slot/channel and privacy tests**

```python
def test_buyer_has_one_slot_per_seller_edge(two_by_two_case) -> None:
    slots = plugin.decision_slots(two_by_two_case, STATE0, BUYER_PHASE)
    buyer1 = [slot for slot in slots if slot.seat_id == "buyer1"]
    assert {slot.slot_id for slot in buyer1} == {"buyer1-seller1-r0", "buyer1-seller2-r0"}
    assert all(len(slot.channels) == 1 for slot in buyer1)


def test_unrelated_private_history_does_not_change_projection(two_by_two_case) -> None:
    before = plugin.observe(two_by_two_case, STATE0, BUYER_PHASE, BUYER1_SLOT)
    changed = mutate_private_history(STATE0, pair="buyer2-seller2")
    after = plugin.observe(two_by_two_case, changed, BUYER_PHASE, BUYER1_SLOT)
    assert before == after
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest adapters/agenticpay/tests/test_agenticpay_2x2.py -v`

Expected: FAIL until multi-channel mapping exists.

- [ ] **Step 3: Implement edge-level buyer and seller slots**

In the buyer phase, create one slot per buyer-seller edge, matching the upstream driver's separate `respond()` calls. Its phase transition stores four pending buyer actions without advancing the upstream environment. In the seller phase, create one slot per seller-buyer edge; each observation includes only that edge's history plus its pending buyer message. After the four seller actions close, convert all eight edge actions into the upstream named inputs in deterministic order and call exactly one upstream environment `step()` for the round.

- [ ] **Step 4: Enforce frozen snapshots and pair privacy**

Generate every buyer observation before any buyer action and every seller observation after buyer bundles close but before any seller action. Build each projection from the addressed pair history plus only the permitted pending messages; never pass the upstream global observation dictionary directly to an agent.

- [ ] **Step 5: Match terminal and score components**

For the scripted fixture, compare selected buyer, selected seller, final price/contract, four pair states, per-seat utilities/rewards, Global/Buyer/Seller components, round count, and terminal reason.

- [ ] **Step 6: Run AgenticPay admission**

Run: `pytest adapters/agenticpay/tests -v`

Expected: 1v1 and 2×2 tests PASS.

Run: `aeread benchmark parity agenticpay_text_v1 --report docs/adapter_admission/agenticpay.md`

Expected: component parity and privacy checks PASS; admitted profile reflects actual call observability and replay level.

- [ ] **Step 7: Commit**

```bash
git add adapters/agenticpay docs/adapter_admission/agenticpay.md
git commit -m "feat: support agenticpay parallel markets"
```

---

### Task 7: Publish the external contribution workflow and final matrix

**Files:**
- Modify: `CONTRIBUTING.md`
- Create: `docs/external_benchmark_adapters.md`
- Create: `adapters/template/pyproject.toml`
- Create: `adapters/template/src/aeread_adapter_example/{__init__,source,environment,verifier}.py`
- Create: `adapters/template/tests/test_adapter.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: all four admission reports.
- Produces: a copyable external adapter package, contributor commands, and isolated CI jobs.

- [ ] **Step 1: Add a template smoke test**

Install the template package in editable mode, discover its entry points, materialize one case, run one provider-free episode, and verify its receipt.

- [ ] **Step 2: Run the smoke test and verify failure**

Run: `pytest adapters/template/tests -v`

Expected: FAIL until the template exists.

- [ ] **Step 3: Write the template and guide**

Document source pinning, license checks, data-only versus code plugin choice, environment/verifier separation, slot/channel modeling, privacy, optional dependencies, official parity, capability claims, admission profiles, and paper-reporting limitations. Include exact `env validate`, `env test`, `benchmark materialize`, and `benchmark parity` commands.

- [ ] **Step 4: Add isolated CI jobs**

Core CI runs without adapter dependencies. Separate jobs install each adapter environment and run only its provider-free fixtures. Gurobi, provider keys, vLLM/SGLang, GPUs, Docker, Harbor, and network calls are not required for PR CI.

- [ ] **Step 5: Run final verification**

Run: `pytest -q`

Expected: core and native tests PASS.

Run each adapter's documented isolated test command.

Expected: all provider-free adapter parity fixtures PASS.

- [ ] **Step 6: Inspect the admission matrix**

Confirm that each row reports source pin, license, schedule/visibility/call/replay/parity/privacy/trainability capabilities, admitted profiles, failed or waived checks, and report hash. No row may claim a stronger status than its fixtures demonstrate.

- [ ] **Step 7: Commit**

```bash
git add CONTRIBUTING.md docs/external_benchmark_adapters.md adapters/template .github/workflows/ci.yml
git commit -m "docs: publish external benchmark adapter workflow"
```

---

## Completion gate

This plan is complete only when:

- Housing passes the same provider-free conformance suite as external plugins;
- all three external repos are pinned and license/source/artifact hashes appear in reports;
- EconEvals matches official allocation components without Gurobi at runtime;
- tau3 matches deterministic retail state/action components and separates judge metrics;
- AgenticPay matches 1v1 and 2×2 outcomes/components and passes private noninterference;
- core AERead imports and tests run without any external adapter dependency;
- each adapter installs and tests in isolation;
- a contributor can copy the template without editing runner core;
- no `if family_id == ...` or external benchmark import appears under `src/aeread/runner/`.
