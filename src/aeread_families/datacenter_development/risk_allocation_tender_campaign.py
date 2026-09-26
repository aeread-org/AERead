"""The tender as shared-runner campaigns.

    python -m aeread_families.datacenter_development.risk_allocation_tender_campaign dry-run runs/<campaign>-dry
    python -m aeread_families.datacenter_development.risk_allocation_tender_campaign smoke   runs/<campaign>-smoke
    python -m aeread_families.datacenter_development.risk_allocation_tender_campaign freeze  runs/<campaign>
    python -m aeread_families.datacenter_development.risk_allocation_tender_campaign run     runs/<campaign>

The model is the client; the three bidders are scripted by the contracts module's hidden
policy. The protocol follows the full-terms campaign (:mod:`.risk_allocation_contracts_campaign`)
with the datacenter scope trims of 2026-09-26: one seed per world, both models at low
effort as the comparison, Gemini at default reasoning on a declared subset of worlds only,
GLM at default reasoning not seated (DC-O-14), and the scripted clients as controls in the
same run: the reference (zero regret by construction) and four rules.

This first campaign is a pilot. It sizes a later run from the spread of the per-world paired
difference; it ranks nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.execution import CanonicalResponse, ProviderRequest, ProviderResult, execute_plan_cell
from aeread.shared_runner.task.execution import TokenPricing
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.task.scheduler import ActionEnvelope

from . import risk_allocation_campaign as oc
from . import risk_allocation_contracts as rc
from . import risk_allocation_contracts_campaign as cc
from . import risk_allocation_tender as rt
from . import risk_allocation_tender_pack as tp
from .risk_allocation_environment import _thaw
from .risk_allocation_tender_environment import (
    PLUGIN_ID,
    SEAT,
    STRICT_ACTION_SCHEMA,
    TenderPlugin,
    parse_tender_move,
    solver_state,
    tender_family_manifest,
)
from .risk_allocation_tender_measurement import (
    REFERENCE_IMPLEMENTATION_ID,
    REFERENCE_SOURCES,
    SCORER_IMPLEMENTATION_ID,
    VALIDITY_IMPLEMENTATION_ID,
    VERSION as MEASUREMENT_VERSION,
    primary_measurement_leaf,
)
from .risk_allocation_two_sided_measurement import combined_sha256

HERE = Path(__file__).parent
REPOSITORY_ROOT = HERE.parents[2]
CAMPAIGN_ID = "datacenter_risk_allocation_tender_pilot_v1"
PACK = "tender_pilot_v1"
SEED = oc.SEED
REQUEST_SEED_BASE = 20260926
SCRIPTED = cc.SCRIPTED
CONTROLS_ARM = cc.CONTROLS_ARM
CONTROL_POLICIES = ("reference", *rt.RULES)
ARMS: dict[str, dict[str, Any]] = {"low_effort": cc.ARMS["low_effort"], "default_reasoning": cc.ARMS["default_reasoning"]}
REPLICATES = 1
WORKERS = {"gemini38_flash": 6, "glm53_flash": 12}
MAX_COST_USD_TOTAL = 4.0
MIN_ACCOUNT_BALANCE_USD = MAX_COST_USD_TOTAL
MAX_WALL_HOURS = 4.0
NOT_SEATED = {("default_reasoning", "glm53_flash"): "DC-O-14"}
SUBSET_ARMS = {"default_reasoning": "the first world of each world type and situation, in pack order"}
CLAIM_STATUS = "pilot: sizes a later tender run; no winner, no ranking"
DECLARED_ANALYSIS = {
    "primary": "at low effort, the mean paired difference in decision regret, GLM 5.3 Flash minus Gemini 3.8 Flash, over worlds valid for both, with its interval; reported as the size a later run must resolve, not as a result",
    "sizing": "the standard deviation of the per-world paired difference, and the number of worlds at one seed that would put a 95% interval's half-width at 25, 50 and 75",
    "also": "Gemini 3.8 Flash, default reasoning minus low effort on the declared subset; each episode's cost over the best attainable split into the bidder chosen (its best contract's cost at its last-round price over the best firm's), the contract signed with it, the price over that bidder's last-round price, walking when a deal was better, and refused counters; how often each signs with a best firm and a best contract with it; how many bidders each negotiates with per turn",
    "interval": "95% percentile bootstrap, 2000 draws, seed 20260926, worlds resampled",
    "missingness": "reported per model, arm and cause; a world missing for either model drops out of its pair, never imputed",
    "controls": "the reference must grade zero regret on every world; four rules are lower controls under the same kernel path",
    "claim": "descriptive: no winner, no ranking, no causal effect",
}
SOURCES = (
    "src/aeread_families/datacenter_development/risk_allocation.py",
    "src/aeread_families/datacenter_development/risk_allocation_menu.py",
    "src/aeread_families/datacenter_development/risk_allocation_contracts.py",
    "src/aeread_families/datacenter_development/risk_allocation_tender.py",
    "src/aeread_families/datacenter_development/risk_allocation_tender_environment.py",
    "src/aeread_families/datacenter_development/risk_allocation_tender_measurement.py",
    "src/aeread_families/datacenter_development/risk_allocation_tender_pack.py",
    "src/aeread_families/datacenter_development/risk_allocation_tender_campaign.py",
    "src/aeread/shared_runner/task/execution.py",
    "src/aeread/shared_runner/task/evaluation.py",
)

SYSTEM_PROMPT = (
    "You are running a tender on behalf of the client. Each turn you receive a JSON object whose observation holds your brief "
    "(observation.brief: the facts, the risks, every contract term, each bidding firm's playbook, what it makes negotiable and its bid, your "
    "walk-away and your objective), the turn, each bidder's status, the standing offers, the answers to your moves so far, and the actions "
    "allowed now. Reply with exactly one JSON object and nothing else:\n"
    '{"action": "accept" | "negotiate" | "walk", "offer": "<standing offer id>" or null, "moves": [{"bidder": "B1" | "B2" | "B3", '
    '"kind": "counter" | "quote", "terms": {"warranty": ..., "damages": ..., "liability_cap": ..., "readiness": ..., "consequential": ..., '
    '"deposit": ..., "escrow": ..., "burn_in": ...}, "price": <number in $ thousands> or null}] or null, "reason": "<one or two sentences>"}\n'
    "Accept takes one standing offer at its price: name it in offer; moves null. Negotiate sends moves to one or more bidders at once, at most "
    "one each: a counter proposes a price for one contract, in that firm's own terms (its fee, if it quotes fees; the all-in price, if it quotes "
    "all in), with every term in terms (null keeps that firm's standard contract's level); a quote asks that firm's price for one contract, "
    "terms as for a counter, price null. Walk manages the deployment yourself: offer and moves null."
)
PROMPT_ID = "datacenter_risk_allocation_tender_client_prompt_v1"


def _cases() -> list[CaseManifest]:
    _, raw = tp.load(PACK)
    return [CaseManifest.from_dict(c) for c in sorted(raw.values(), key=lambda c: c["case_id"])]


def subset_case_ids() -> set[str]:
    """The declared subset for the arms in ``SUBSET_ARMS``: the first world of each world type and situation, in pack order."""
    manifest, _ = tp.load(PACK)
    seen, out = set(), set()
    for w in manifest["worlds"]:
        key = (w["world_type"], w["situation"])
        if key not in seen:
            seen.add(key)
            out.add(w["case_id"])
    return out


def build_setup(arm: str, route_id: str, cases: Sequence[CaseManifest]) -> cc.Setup:
    family = tender_family_manifest()
    scripted = route_id.startswith(SCRIPTED)
    tag = f"{arm}_{route_id}"
    rounds = max(len(c.payload["world"]["terms"]["ask_premium"]) - 1 for c in cases)
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": f"risk_allocation_tender_{tag}_sample_v1",
        "estimand": "decision_regret_on_a_generated_tender_pack", "target": "selecting_and_negotiating_among_simultaneous_bidders",
        "selection": "generated_admitted_cells", "seeds": [SEED], "replicates": 1 if scripted else REPLICATES, "cluster_level": "risk_allocation_world",
        "cluster_id_fields": ["world_seed"], "paired_fields": [], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({"spec_version": EvaluationBlock.SPEC_VERSION, "block_id": "risk_allocation_tender_client_block",
                                       "kind": "reference" if scripted else "self_play", "subject_seats": [SEAT], "controlled_profiles": {},
                                       "repetitions": 1, "seed_policy": "fixed"})
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "risk_allocation_tender_analysis_v1", "estimands": ["decision_regret"],
        "group_by": ["family_id"], "missingness": "report_separately", "resampling_unit": "risk_allocation_world",
        "uncertainty": "world_cluster_bootstrap_95", "multiplicity": "none", "sensitivity": [], "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"risk_allocation_tender_{PACK}", "version": "0.1.0", "family_ids": [family.family.id],
        "case_ids": [c.case_id for c in cases], "sampling_plan_id": sampling.sampling_plan_id, "evaluation_block_ids": [block.block_id],
        "analysis_plan_id": analysis.analysis_plan_id,
    })
    if scripted:
        policy = route_id[len(SCRIPTED):]
        provider = "fake"
        pricing = TokenPricing(0.0, 0.0, 0.0, "scripted_policy_zero_cost_v1")
        model = {"provider": "fake", "model": f"risk-allocation-tender-{policy.replace('_', '-')}", "revision": f"risk_allocation_tender_{policy}_v1", "base_url": None}
        harness_config: dict[str, Any] = {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": STRICT_ACTION_SCHEMA}
        reasoning = {"condition_id": "reasoning_unspecified_v1", "effort": None, "token_budget": None, "rationale_visibility": "hidden"}
        sampling_cfg = {"temperature": 0.0, "max_output_tokens": 1000, "seed": None, "top_p": None}
        budgets = {"max_logical_actions": rounds + 1, "timeout_seconds": 60.0, "max_cost_usd": 0.0}
        retry = {"max_action_attempts": 1, "retryable_conditions": [], "session_mode": "restart", "sdk_retries": 0}
    else:
        spec, r = ARMS[arm], oc.ROUTES[route_id]
        provider, pricing = "openrouter", r.pricing
        model = {"provider": "openrouter", "model": r.model, "revision": r.revision, "base_url": "https://openrouter.ai/api/v1"}
        harness_config = {
            "pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": STRICT_ACTION_SCHEMA,
            "provider_metadata": {"route_provider": r.provider, "quantization": r.quantization, "canonical_model": r.revision,
                                  "max_prompt_price_per_million": r.max_prompt_price_per_million, "max_completion_price_per_million": r.max_completion_price_per_million},
            **oc.RETRY_V2["backoff"], "request_seed_source": "paired_cell_v1", "request_seed_base": REQUEST_SEED_BASE,
        }
        effort = spec["reasoning_effort"]
        reasoning = {"condition_id": f"reasoning_{effort}_v1" if effort else "reasoning_provider_default_v1", "effort": effort, "token_budget": None,
                     "rationale_visibility": "hidden"}
        sampling_cfg = {"temperature": 1.0, "max_output_tokens": spec["max_output_tokens"][route_id], "seed": SEED, "top_p": None}
        budgets = {"max_logical_actions": rounds + 1, "timeout_seconds": spec["timeout_seconds"][route_id], "max_cost_usd": spec["max_cost_usd"][route_id]}
        retry = {"max_action_attempts": oc.RETRY_V2["max_action_attempts"], "retryable_conditions": list(oc.RETRY_V2["retryable_conditions"]),
                 "session_mode": "restart", "sdk_retries": 0}
    profile_id = f"datacenter_risk_allocation_tender_{tag}_v1"
    profile = AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": profile_id, "model": model,
        "harness": {"id": "minimal_chat", "version": "1.0", "config": harness_config},
        "prompt": {"prompt_id": PROMPT_ID, "sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": oc.RUNTIME_ID, "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"}, "reasoning": reasoning, "sampling": sampling_cfg, "budgets": budgets, "retry_policy": retry,
    })
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"datacenter_risk_allocation_tender_{tag}_run_v1", "suite_id": suite.suite_id,
        "evaluation_block_ids": [block.block_id], "agent_profile_ids": [profile_id], "seat_assignments": {SEAT: profile_id},
        "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None,
    })
    registry = PluginRegistry()
    registry.register_trusted(family, TenderPlugin())
    harnesses = default_harnesses()
    harness_registry = HarnessRegistry()
    for h in harnesses.values():
        harness_registry.register(h)
    execution_path = Path(execution_module.__file__)
    pins = (
        oc._pin(PLUGIN_ID, "family_plugin", HERE / "risk_allocation_tender_environment.py"),
        oc._pin(SCORER_IMPLEMENTATION_ID, "scorer", HERE / "risk_allocation_tender_measurement.py", version=MEASUREMENT_VERSION),
        oc._pin(VALIDITY_IMPLEMENTATION_ID, "reference", HERE / "risk_allocation_tender_measurement.py", version=MEASUREMENT_VERSION),
        ImplementationPin.from_dict({"component_id": REFERENCE_IMPLEMENTATION_ID, "kind": "reference", "version": MEASUREMENT_VERSION,
                                     "sha256": combined_sha256(REFERENCE_SOURCES)}),
        oc._pin("minimal_chat", "harness", execution_path, version="1.0"),
        oc._pin(oc.RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
    )
    plan = resolve_run_plan(
        families=(family,), cases=tuple(cases), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis,
        agent_profiles=(profile,), run_spec=run_spec, registry=registry, implementation_pins=pins, harness_registry=harness_registry,
        provider_capabilities={provider: ProviderCapabilities(
            native_tools=False, structured_output=provider == "openrouter", seed=provider == "openrouter", system_prompt=True,
            reasoning_budget=provider == "openrouter" and reasoning["effort"] is not None, reasoning_token_report=provider == "openrouter", max_context_tokens=None)},
    )
    return cc.Setup(plan, registry, {PROMPT_ID: SYSTEM_PROMPT}, {model["model"]: pricing}, harnesses, provider)


def reply(solver: rt.TenderSolver, state: Mapping[str, Any], move: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """A move in the action schema's shape from {action, offer, moves: [{bidder index, contract, price all in or None}]}."""
    out = {"action": move["action"], "offer": move.get("offer"), "moves": None, "reason": reason}
    if move["action"] == "negotiate":
        out["moves"] = [{"bidder": rt.BIDDER_IDS[m["bidder"]], "kind": "quote" if m["price"] is None else "counter", "terms": m["contract"],
                         "price": None if m["price"] is None else rt.show(solver.bidders[m["bidder"]].playbook, solver.w, m["price"])} for m in move["moves"]]
    return out


def reference_move(solver: rt.TenderSolver, state: Mapping[str, Any], s: rt.TState) -> dict[str, Any]:
    a = solver.best(s)
    if a.kind == "walk":
        return {"action": "walk", "offer": None, "moves": None}
    if a.kind == "accept":
        mine = [o for o in state["offers"] if o["bidder"] == a.bidder]
        total = lambda o: o["price"] + float(solver.cc[a.bidder][solver.index(a.bidder, rc.Contract(**o["contract"]))])  # noqa: E731
        return {"action": "accept", "offer": min(mine, key=lambda o: (round(total(o), 6), o["id"]))["id"], "moves": None}
    return {"action": "negotiate", "offer": None, "moves": [{"bidder": m.bidder, "contract": m.contract.as_dict(), "price": m.price} for m in a.moves]}


class ScriptedClient:
    """A scripted client: it rebuilds the episode from the case and its own replies, then answers as its policy."""

    def __init__(self, payload: Mapping[str, Any], policy: str) -> None:
        self.plugin = TenderPlugin()
        self.payload = self.plugin.validate_payload(payload)
        self.policy = policy
        self.replies: list[str] = []

    def _state(self) -> dict[str, Any]:
        state = self.plugin.initial_state(self.payload, None)
        phase = self.plugin.phases(self.payload)[0]
        for text in self.replies:
            parsed = parse_tender_move(CanonicalResponse(text, "stop", False, False, (), (), 0, 0, 0, 0.0))
            legality = self.plugin.legal(self.payload, state, SEAT, phase, parsed.action)
            state = self.plugin.step(self.payload, state, phase, {SEAT: ActionEnvelope(SEAT, True, parsed.action, parsed, legality)}).state
        return state

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        state = self._state()
        solver = rt.solver_for(self.payload)
        s = solver_state(self.payload, state)
        if self.policy == "reference":
            move = reference_move(solver, state, s)
        else:
            open_bidders = [j for j in range(len(solver.bidders)) if solver.open(s, j)]
            move = rt.rule_moves(self.policy, solver, state["turn"], state["final"], state["offers"], open_bidders)
        text = json.dumps(reply(solver, state, move, self.policy))
        self.replies.append(text)
        return ProviderResult(response_id=f"scripted_{len(self.replies)}", requested_model=request.model, resolved_model=request.revision or request.model,
                              output_text=text, finish_reason="stop", input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0,
                              raw_response={"scripted": True, "output_text": text})


def _digest_file(rel: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / rel).read_bytes()).hexdigest()


def _entries(arms: Sequence[str], routes: Sequence[str]) -> list[tuple[str, str]]:
    out = [(arm, route) for arm in arms for route in routes if (arm, route) not in NOT_SEATED]
    return out + [(CONTROLS_ARM, f"{SCRIPTED}{p}") for p in CONTROL_POLICIES]


def freeze(directory: Path, *, arms: Sequence[str] | None = None, routes: Sequence[str] | None = None, controls: bool = True,
           campaign_id: str = CAMPAIGN_ID) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    arms, routes = list(arms if arms is not None else ARMS), list(routes if routes is not None else oc.ROUTES)
    entries = _entries(arms, routes) if controls else [(a, r) for a in arms for r in routes if (a, r) not in NOT_SEATED]
    cases = _cases()
    subset = subset_case_ids()
    plans = []
    for arm, route in entries:
        setup = build_setup(arm, route, cases)
        cells = [c for c in setup.plan.cells if arm not in SUBSET_ARMS or c.case_id in subset]
        plans.append({"arm": arm, "route_id": route, "run_plan_id": setup.plan.run_plan_id,
                      "cells": [{"cell_id": c.cell_id, "case_id": c.case_id, "replicate_index": c.replicate_index} for c in cells]})
    manifest, _ = tp.load(PACK)
    plan = {
        "campaign_id": campaign_id, "claim_status": CLAIM_STATUS, "pack": PACK, "arms": {a: ARMS[a] for a in arms},
        "subset_arms": {a: why for a, why in SUBSET_ARMS.items() if a in arms}, "subset_case_ids": sorted(subset),
        "routes": {r: asdict(oc.ROUTES[r]) for r in routes}, "controls": list(CONTROL_POLICIES) if controls else [], "replicates": REPLICATES,
        "not_seated": {f"{a}/{r}": why for (a, r), why in NOT_SEATED.items()},
        "retry": oc.RETRY_V2, "request_seed_base": REQUEST_SEED_BASE, "workers": WORKERS, "max_cost_usd_total": MAX_COST_USD_TOTAL,
        "max_wall_hours": MAX_WALL_HOURS, "min_account_balance_usd": MIN_ACCOUNT_BALANCE_USD,
        "stop_rule": "the first provider reply of HTTP 402 (insufficient credits) stops the campaign; cells not yet started stay not attempted",
        "seed": SEED, "system_prompt": SYSTEM_PROMPT,
        "pack_manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(), "declared_analysis": DECLARED_ANALYSIS,
        "sources": {rel: _digest_file(rel) for rel in SOURCES}, "plans": plans,
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    (directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
    return plan


def _check(directory: Path) -> dict[str, Any]:
    plan = json.loads((directory / "campaign_plan.json").read_text())
    if any(_digest_file(rel) != d for rel, d in plan["sources"].items()):
        raise SystemExit("sources changed since the plan was frozen; freeze a new campaign directory")
    return plan


async def _run_cell(directory: Path, entry: Mapping[str, Any], setup: cc.Setup, cell: Any, spend: oc.Spend, sem: asyncio.Semaphore) -> dict[str, Any]:
    scripted = entry["route_id"].startswith(SCRIPTED)
    key = f"{entry['arm']}__{entry['route_id']}__{cell.case_id.rsplit('.', 1)[-1]}" + ("" if scripted else f"__r{cell.replicate_index}")
    record_path = directory / "cells" / f"{key}.json"
    if record_path.exists():
        return json.loads(record_path.read_text())
    async with sem:
        if cc.HALT["reason"]:
            return {"cell_key": key, "status": f"not_attempted_{cc.HALT['reason']}"}
        if spend.exhausted:
            return {"cell_key": key, "status": "not_attempted_budget"}
        if spend.past_deadline:
            return {"cell_key": key, "status": "not_attempted_wall_limit"}
        evidence_root = directory / "evidence" / key
        payload = next(c.payload for c in setup.plan.cases if c.case_id == cell.case_id)
        if scripted:
            providers = {"fake": ScriptedClient(payload, entry["route_id"][len(SCRIPTED):])}
        else:
            providers = {"openrouter": oc._client(entry["route_id"], ARMS[entry["arm"]]["timeout_seconds"][entry["route_id"]])}
        record: dict[str, Any] = {"cell_key": key, "arm": entry["arm"], "route_id": entry["route_id"], "case_id": cell.case_id, "cell_id": cell.cell_id,
                                  "replicate_index": cell.replicate_index, "run_plan_id": setup.plan.run_plan_id}
        try:
            execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                                                prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing, harnesses=setup.harnesses)
            receipt = finalize_family_execution(setup=setup, execution=execution)
            verify_evaluation_receipt(receipt)
            replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("replay produced a different receipt")
            cost, answered, unknown = oc._events_cost(evidence_root)
            spend.add(cost)
            outcome = _thaw(execution.episode_result.outcome)
            record.update(status=receipt.status, receipt_sha256=receipt.receipt_sha256, episode_attempt_id=execution.episode_attempt_id, cost_usd=cost,
                          kernel_cost_usd=float(execution.total_cost_usd or 0.0), provider_calls=answered, calls_outcome_unknown=unknown,
                          termination=outcome.get("termination"), grade=outcome.get("grade"))
        except Exception as error:  # a failed cell is sealed as a typed exclusion, never rerun
            if cc.is_out_of_credit(error):
                cc.HALT["reason"] = "account_out_of_credit"
            try:
                receipt = finalize_family_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error, leaf_builder=primary_measurement_leaf)
                record.update(status=receipt.status, receipt_sha256=receipt.receipt_sha256, error=f"{type(error).__name__}: {str(error)[:300]}")
                cost, answered, unknown = oc._events_cost(evidence_root)
                spend.add(cost)
                record.update(cost_usd=cost, provider_calls=answered, calls_outcome_unknown=unknown)
            except Exception as sealing_error:
                record.update(status="unsealed_failure", error=f"{type(error).__name__}: {str(error)[:300]}",
                              sealing_error=f"{type(sealing_error).__name__}: {str(sealing_error)[:300]}")
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=1, default=str))
        g = record.get("grade") or {}
        print(f"{key:72} {record['status']:22} {record.get('termination') or ''} {g.get('decision_regret', '')}", flush=True)
        return record


async def run(directory: Path, *, first_cells: int | None = None) -> None:
    plan = _check(directory)
    cc.preflight(plan)
    spend = oc.Spend(plan["max_cost_usd_total"], plan.get("max_wall_hours"))
    for p in (directory / "cells").glob("*.json") if (directory / "cells").exists() else ():
        spend.add(float(json.loads(p.read_text()).get("cost_usd") or 0.0))
    cases = _cases()
    sems = {r: asyncio.Semaphore(plan["workers"].get(r, 8)) for r in {e["route_id"] for e in plan["plans"]}}
    jobs = []
    for entry in plan["plans"]:
        setup = build_setup(entry["arm"], entry["route_id"], cases)
        if setup.plan.run_plan_id != entry["run_plan_id"]:
            raise SystemExit(f"run plan {entry['run_plan_id']} no longer resolves identically; freeze a new campaign")
        wanted = {c["cell_id"] for c in entry["cells"]}
        cells = [c for c in setup.plan.cells if c.cell_id in wanted][: first_cells or None]
        jobs += [_run_cell(directory, entry, setup, cell, spend, sems[entry["route_id"]]) for cell in cells]
    await asyncio.gather(*jobs)
    print(f"spent ${spend.spent:.4f} of ${spend.cap:.2f}" + (f"; stopped: {cc.HALT['reason']}" if cc.HALT["reason"] else ""))


def summary(directory: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in sorted((directory / "cells").glob("*.json")):
        r = json.loads(p.read_text())
        s = out.setdefault(f"{r['arm']}/{r['route_id']}", {"cells": 0, "valid": 0, "regret": [], "best_bidder": 0, "cost_usd": 0.0, "status": {}})
        s["cells"] += 1
        s["status"][r["status"]] = s["status"].get(r["status"], 0) + 1
        s["cost_usd"] += float(r.get("cost_usd") or 0.0)
        g = r.get("grade") or {}
        if r["status"] == "ok" and g.get("valid"):
            s["valid"] += 1
            s["regret"].append(g["decision_regret"])
            s["best_bidder"] += bool(g["signed_best_bidder"])
    for s in out.values():
        s["mean_regret"] = round(math.fsum(s["regret"]) / len(s["regret"]), 3) if s["regret"] else None
        s["regret"] = len(s["regret"])
        s["cost_usd"] = round(s["cost_usd"], 4)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["freeze", "dry-run", "smoke", "run", "summary"])
    ap.add_argument("directory", type=Path)
    args = ap.parse_args(argv)
    if args.command == "freeze":
        p = freeze(args.directory)
        print(f"froze {sum(len(x['cells']) for x in p['plans'])} cells in {len(p['plans'])} plans: {p['plan_sha256'][:12]}")
    elif args.command == "dry-run":
        if not args.directory.exists():
            freeze(args.directory, arms=[], routes=[], campaign_id=CAMPAIGN_ID + "_scripted_dry_run")
        asyncio.run(run(args.directory))
        print(json.dumps(summary(args.directory), indent=1))
    elif args.command == "smoke":
        if not args.directory.exists():
            freeze(args.directory, arms=["low_effort"], controls=False, campaign_id=CAMPAIGN_ID + "_smoke")
        asyncio.run(run(args.directory, first_cells=2))
        print(json.dumps(summary(args.directory), indent=1))
    elif args.command == "run":
        asyncio.run(run(args.directory))
        print(json.dumps(summary(args.directory), indent=1))
    else:
        print(json.dumps(summary(args.directory), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
