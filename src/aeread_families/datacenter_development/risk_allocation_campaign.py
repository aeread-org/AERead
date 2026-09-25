"""The risk-allocation case as shared-runner campaigns: sealed receipts, replay, publication.

The probes (``tools/run_risk_allocation_probe.py``) called the plugin directly and
wrote no receipts. This module runs the same packs through the kernel: every
episode is ``execute_plan_cell`` then ``finalize_family_execution``, verified and
replayed, so the runs can be published as evidence and read by the examiner.

    python -m aeread_families.datacenter_development.risk_allocation_campaign freeze  runs/<campaign>
    python -m aeread_families.datacenter_development.risk_allocation_campaign dry-run runs/<campaign>-reference
    python -m aeread_families.datacenter_development.risk_allocation_campaign smoke   runs/<campaign>-smoke
    python -m aeread_families.datacenter_development.risk_allocation_campaign run     runs/<campaign>
    python -m aeread_families.datacenter_development.risk_allocation_campaign summary runs/<campaign>

``freeze`` writes the campaign plan with every limit and the digest of every
source and case; ``run`` refuses a plan whose sources or cases changed, runs each
cell once into a fresh evidence root, and never reruns a cell that has a record
(a failed cell is typed missingness). ``dry-run`` plays the reference through the
same kernel path with no network and must grade zero regret everywhere.

One plan per (arm, route, seat): a plan's cases must all seat the model in the
same role. Arms change one thing each from the first probe's design:

| arm | pack | reasoning | output limit, Gemini / GLM |
|---|---|---|---|
| one_price_low | risk_allocation_dev_v1 | effort low | 4,000 / 32,000 |
| one_price_default | risk_allocation_dev_v1 | none declared | 27,000 / 93,000 |
| two_prices_low | risk_allocation_two_prices_dev_v1 | effort low | 4,000 / 32,000 |

Output limits come from the probe smokes by the rule "twice the longest reply,
at least 4,000" (DC-O-08, DC-O-09); a reply cut off at the limit is typed
``truncated_reply`` and counted as missingness, not as the model's move.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, RunPlan, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    OpenRouterChatClient,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.task.scheduler import ActionEnvelope

from . import risk_allocation as ra
from . import risk_allocation_pack as rp
from .risk_allocation_environment import (
    _thaw,
    FAMILY_ID,
    PLUGIN_ID,
    STRICT_ACTION_SCHEMA,
    STRICT_ACTION_SCHEMA_ALTERNATES,
    RiskAllocationPlugin,
    alternates_of,
    game_of,
    grade,
    risk_allocation_family_manifest,
    seen_of,
)
from .risk_allocation_measurement import (
    REFERENCE_IMPLEMENTATION_ID,
    SCORER_IMPLEMENTATION_ID,
    VALIDITY_IMPLEMENTATION_ID,
    VERSION as MEASUREMENT_VERSION,
)

HERE = Path(__file__).parent
REPOSITORY_ROOT = HERE.parents[2]
CAMPAIGN_ID = "datacenter_risk_allocation_dev_campaign_v1"
RUNTIME_ID = "aeread.shared_runner.task.execution"
SEED = 1


@dataclass(frozen=True)
class Route:
    route_id: str
    model: str
    revision: str
    provider: str
    quantization: str
    pricing: TokenPricing
    max_prompt_price_per_million: str
    max_completion_price_per_million: str


# The routes of the probes, with the reviewed prices the datacenter and procurement campaigns use.
ROUTES: dict[str, Route] = {
    "gemini38_flash": Route("gemini38_flash", "google/gemini-3.8-flash", "google/gemini-3.8-flash-20260902", "Google AI Studio", "unknown",
                            TokenPricing(0.75, 0.075, 3.75, "openrouter_2026-09-03_gemini38_flash_aistudio_world_panel_v1"), "1.35", "6.75"),
    "glm53_flash": Route("glm53_flash", "z-ai/glm-5.3-flash", "z-ai/glm-5.3-flash-20260826", "Parasail", "fp8",
                         TokenPricing(0.15, 0.03, 0.50, "openrouter_2026-09-03_glm53_flash_parasail"), "0.15", "0.50"),
}

# Every limit that can end or change a run is here and frozen into the plan.
ARMS: dict[str, dict[str, Any]] = {
    "one_price_low": {
        "pack": "risk_allocation_dev_v1", "reasoning_effort": "low",
        "max_output_tokens": {"gemini38_flash": 4000, "glm53_flash": 32000},
        "timeout_seconds": {"gemini38_flash": 300.0, "glm53_flash": 1200.0},
        "max_cost_usd": {"gemini38_flash": 0.10, "glm53_flash": 0.10},
    },
    "one_price_default": {
        "pack": "risk_allocation_dev_v1", "reasoning_effort": None,
        "max_output_tokens": {"gemini38_flash": 27000, "glm53_flash": 93000},
        "timeout_seconds": {"gemini38_flash": 420.0, "glm53_flash": 2000.0},
        "max_cost_usd": {"gemini38_flash": 0.40, "glm53_flash": 0.30},
    },
    "two_prices_low": {
        "pack": "risk_allocation_two_prices_dev_v1", "reasoning_effort": "low",
        "max_output_tokens": {"gemini38_flash": 4000, "glm53_flash": 32000},
        "timeout_seconds": {"gemini38_flash": 300.0, "glm53_flash": 1200.0},
        "max_cost_usd": {"gemini38_flash": 0.10, "glm53_flash": 0.10},
    },
}
WORKERS = {"gemini38_flash": 6, "glm53_flash": 8, "reference": 8}
MAX_COST_USD_TOTAL = 12.0

SOURCES = (
    "src/aeread_families/datacenter_development/risk_allocation.py",
    "src/aeread_families/datacenter_development/risk_allocation_environment.py",
    "src/aeread_families/datacenter_development/risk_allocation_measurement.py",
    "src/aeread_families/datacenter_development/risk_allocation_pack.py",
    "src/aeread_families/datacenter_development/risk_allocation_campaign.py",
    "src/aeread/shared_runner/task/execution.py",
    "src/aeread/shared_runner/task/evaluation.py",
)


def system_prompt(seat: str, alternates: bool) -> str:
    """What the model is told once; the brief and the negotiation so far arrive as the observation."""
    pkg = ('{"warranty": "none|fix|fix_and_delay", "readiness": "client|integrator", '
           '"consequential": "excluded|included", "deposit": "at_signing|on_delivery"}')
    alt_field = f'"alternate": {pkg} or null, ' if alternates else ""
    alt_rule = ("With price null you may also name an alternate package, and the answer prices both; "
                "both then stand, and an accept names the package it takes in package. ") if alternates else ""
    nulls = "package, price and alternate are null" if alternates else "package and price are null"
    return (
        f"You are negotiating a contract on behalf of the {seat}. Each turn you receive a JSON object whose "
        "observation holds your brief (observation.brief: the facts, the risks, the contract terms, the other side's "
        "conduct and your objective), the round, the standing offer (a package and the price at which the other side "
        "has said it will sign it, if any), the history of your proposals and its answers, and the actions allowed now. "
        "Reply with exactly one JSON object and nothing else:\n"
        '{"action": "propose" | "accept" | "walk", '
        f'"package": {pkg} or null, "price": <number in $ thousands> or null, {alt_field}"reason": "<one or two sentences>"}}\n'
        "A proposal always states the full package. Use price null to ask the other side for its price for that package "
        f"without committing. {alt_rule}For walk, {nulls}. Accept takes a standing offer as it stands, so its price is null"
        + (" and its alternate is null; when two offers stand, put the one you accept in package, otherwise package is null." if alternates
           else "; package is null.")
    )


def prompt_id(seat: str, alternates: bool) -> str:
    return f"datacenter_risk_allocation_{seat}{'_two_prices' if alternates else ''}_prompt_v1"


def _pin(component_id: str, kind: str, path: Path, *, version: str = "1.0.0") -> ImplementationPin:
    return ImplementationPin.from_dict({"component_id": component_id, "kind": kind, "version": version,
                                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})


@dataclass
class Setup:
    """What the kernel's finalizer and replay read: plan, registry, prompt sources, pricing."""

    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: dict[str, str]
    pricing: dict[str, TokenPricing]
    harnesses: dict[str, Any]
    provider: str


def build_setup(arm: str, route_id: str, seat: str, cases: Sequence[CaseManifest]) -> Setup:
    """One plan: every case of one seat, one route (or the reference), one arm, one seed."""
    spec = ARMS[arm]
    alternates = any(alternates_of(c.payload) for c in cases)
    if alternates != (spec["pack"] == "risk_allocation_two_prices_dev_v1"):
        raise ValueError("the arm's pack and its cases' protocol disagree")
    family = risk_allocation_family_manifest()
    tag = f"{arm}_{route_id}_{seat}"
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": f"risk_allocation_{tag}_sample_v1",
        "estimand": "decision_regret_on_a_generated_dev_pack", "target": "negotiating_the_allocation_of_risk",
        "selection": "generated_admitted_cells", "seeds": [SEED], "replicates": 1, "cluster_level": "risk_allocation_world",
        "cluster_id_fields": ["world_seed"], "paired_fields": [], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"risk_allocation_{seat}_block", "kind": "self_play",
        "subject_seats": [seat], "controlled_profiles": {}, "repetitions": 1, "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "risk_allocation_analysis_v1",
        "estimands": ["decision_regret"], "group_by": ["family_id"], "missingness": "report_separately",
        "resampling_unit": "risk_allocation_world", "uncertainty": "none", "multiplicity": "none", "sensitivity": [],
        "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"risk_allocation_{spec['pack']}_{seat}", "version": "0.1.0",
        "family_ids": [family.family.id], "case_ids": [c.case_id for c in cases], "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id,
    })
    schema = STRICT_ACTION_SCHEMA_ALTERNATES if alternates else STRICT_ACTION_SCHEMA
    pid, prompt = prompt_id(seat, alternates), system_prompt(seat, alternates)
    rounds = max(len(c.payload["world"]["terms"]["ask_premium"]) - 1 for c in cases)
    if route_id == "reference":
        provider = "fake"
        pricing = TokenPricing(0.0, 0.0, 0.0, "reference_policy_zero_cost_v1")
        model = {"provider": "fake", "model": "risk-allocation-reference", "revision": "risk_allocation_reference_v1", "base_url": None}
        harness_config: dict[str, Any] = {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": schema}
        reasoning = {"condition_id": "reasoning_unspecified_v1", "effort": None, "token_budget": None, "rationale_visibility": "hidden"}
        sampling_cfg = {"temperature": 0.0, "max_output_tokens": 1000, "seed": None, "top_p": None}
        budgets = {"max_logical_actions": rounds + 1, "timeout_seconds": 60.0, "max_cost_usd": 0.0}
    else:
        r = ROUTES[route_id]
        provider = "openrouter"
        pricing = r.pricing
        model = {"provider": "openrouter", "model": r.model, "revision": r.revision, "base_url": "https://openrouter.ai/api/v1"}
        harness_config = {
            "pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": schema,
            "provider_metadata": {"route_provider": r.provider, "quantization": r.quantization, "canonical_model": r.revision,
                                  "max_prompt_price_per_million": r.max_prompt_price_per_million,
                                  "max_completion_price_per_million": r.max_completion_price_per_million},
        }
        effort = spec["reasoning_effort"]
        reasoning = {"condition_id": f"reasoning_{effort}_v1" if effort else "reasoning_provider_default_v1", "effort": effort,
                     "token_budget": None, "rationale_visibility": "hidden"}
        sampling_cfg = {"temperature": 1.0, "max_output_tokens": spec["max_output_tokens"][route_id], "seed": SEED, "top_p": None}
        budgets = {"max_logical_actions": rounds + 1, "timeout_seconds": spec["timeout_seconds"][route_id],
                   "max_cost_usd": spec["max_cost_usd"][route_id]}
    profile_id = f"datacenter_risk_allocation_{tag}_v1"
    profile = AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": profile_id, "model": model,
        "harness": {"id": "minimal_chat", "version": "1.0", "config": harness_config},
        "prompt": {"prompt_id": pid, "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": RUNTIME_ID, "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"}, "reasoning": reasoning, "sampling": sampling_cfg, "budgets": budgets,
        "retry_policy": {"max_action_attempts": 1, "retryable_conditions": [], "session_mode": "restart", "sdk_retries": 0},
    })
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"datacenter_risk_allocation_{tag}_run_v1", "suite_id": suite.suite_id,
        "evaluation_block_ids": [block.block_id], "agent_profile_ids": [profile_id], "seat_assignments": {seat: profile_id},
        "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None,
    })
    registry = PluginRegistry()
    registry.register_trusted(family, RiskAllocationPlugin())
    harnesses = default_harnesses()
    harness_registry = HarnessRegistry()
    for h in harnesses.values():
        harness_registry.register(h)
    execution_path = Path(execution_module.__file__)
    pins = (
        _pin(PLUGIN_ID, "family_plugin", HERE / "risk_allocation_environment.py"),
        _pin(SCORER_IMPLEMENTATION_ID, "scorer", HERE / "risk_allocation_measurement.py", version=MEASUREMENT_VERSION),
        _pin(VALIDITY_IMPLEMENTATION_ID, "reference", HERE / "risk_allocation_measurement.py", version=MEASUREMENT_VERSION),
        _pin(REFERENCE_IMPLEMENTATION_ID, "reference", HERE / "risk_allocation.py", version=MEASUREMENT_VERSION),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
    )
    plan = resolve_run_plan(
        families=(family,), cases=tuple(cases), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis,
        agent_profiles=(profile,), run_spec=run_spec, registry=registry, implementation_pins=pins, harness_registry=harness_registry,
        provider_capabilities={provider: ProviderCapabilities(
            native_tools=False, structured_output=provider == "openrouter", seed=provider == "openrouter", system_prompt=True,
            reasoning_budget=provider == "openrouter" and reasoning["effort"] is not None,
            reasoning_token_report=provider == "openrouter", max_context_tokens=None)},
    )
    return Setup(plan, registry, {pid: prompt}, {model["model"]: pricing}, harnesses, provider)


class ReferenceClient:
    """Answers as the reference, for dry runs: it rebuilds the episode from the case and
    its own earlier replies, then returns the reference's move for what the model sees."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.plugin = RiskAllocationPlugin()
        self.payload = self.plugin.validate_payload(payload)
        self.replies: list[str] = []

    def _state(self) -> dict[str, Any]:
        seat = self.payload["seat"]
        phase = self.plugin.phases(self.payload)[0]
        state = self.plugin.initial_state(self.payload, None)
        for text in self.replies:
            parsed = self.plugin.parse_action(self.payload, state, seat, phase, CanonicalResponse(text, "stop", False, False, (), (), 0, 0, 0, 0.0))
            legality = self.plugin.legal(self.payload, state, seat, phase, parsed.action)
            state = self.plugin.step(self.payload, state, phase, {seat: ActionEnvelope(seat, True, parsed.action, parsed, legality)}).state
        return state

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        game, _ = game_of(self.payload)
        a = ra.reference_policy(game)(seen_of(self.payload, self._state()))
        move: dict[str, Any] = {"action": a.kind, "package": None, "price": None}
        if alternates_of(self.payload):
            move["alternate"] = None
        if a.kind == "accept" and a.package is not None:
            move["package"] = a.package.as_dict()
        if a.kind == "propose":
            move.update(package=a.package.as_dict(), price=None if a.price == ra.PRICE_IT else a.price)
            if a.alternate is not None:
                move["alternate"] = a.alternate.as_dict()
        move["reason"] = "reference"
        text = json.dumps(move)
        self.replies.append(text)
        return ProviderResult(response_id=f"reference_{len(self.replies)}", requested_model=request.model,
                              resolved_model=request.revision or request.model, output_text=text, finish_reason="stop",
                              input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0,
                              raw_response={"reference": True, "output_text": text})


# ---------------------------------------------------------------------------
# Plans, cells and records.


def _digest_file(rel: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / rel).read_bytes()).hexdigest()


def _cases(pack: str, seat: str) -> list[CaseManifest]:
    _, raw = rp.load(pack)
    return [CaseManifest.from_dict(c) for c in sorted(raw.values(), key=lambda c: c["case_id"]) if c["payload"]["seat"] == seat]


def freeze(directory: Path, *, routes: Sequence[str], arms: Sequence[str], campaign_id: str = CAMPAIGN_ID) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    plans = []
    for arm in arms:
        for route_id in routes:
            for seat in ra.SEATS:
                setup = build_setup(arm, route_id, seat, _cases(ARMS[arm]["pack"], seat))
                plans.append({"arm": arm, "route_id": route_id, "seat": seat, "run_plan_id": setup.plan.run_plan_id,
                              "cells": [{"cell_id": c.cell_id, "case_id": c.case_id} for c in setup.plan.cells]})
    manifests = {pack: rp.load(pack)[0] for pack in {ARMS[a]["pack"] for a in arms}}
    plan = {
        "campaign_id": campaign_id, "claim_status": "diagnostic dev campaign; no model ranking",
        "routes": {r: asdict(ROUTES[r]) if r in ROUTES else {"route_id": r} for r in routes},
        "arms": {a: ARMS[a] for a in arms}, "workers": WORKERS, "max_cost_usd_total": MAX_COST_USD_TOTAL, "seed": SEED,
        "system_prompts": {prompt_id(s, alt): system_prompt(s, alt) for s in ra.SEATS for alt in (False, True)},
        "pack_manifest_sha256": {k: hashlib.sha256(canonical_json_bytes(v)).hexdigest() for k, v in manifests.items()},
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


class Spend:
    def __init__(self, cap: float) -> None:
        self.cap, self.spent = cap, 0.0

    def add(self, x: float) -> None:
        self.spent += x

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.cap


def _client(route_id: str, timeout: float):
    if route_id == "reference":
        return None
    from openai import AsyncOpenAI  # the kernel's own dependency

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY must be set (source the checkout's .env; never print it)")
    return OpenRouterChatClient(sdk_client=AsyncOpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", max_retries=0, timeout=timeout + 100.0))


async def _run_cell(directory: Path, entry: Mapping[str, Any], setup: Setup, cell: Any, spend: Spend, sem: asyncio.Semaphore) -> dict[str, Any]:
    key = f"{entry['arm']}__{entry['route_id']}__{entry['seat']}__{cell.case_id.rsplit('.', 1)[-1]}"
    record_path = directory / "cells" / f"{key}.json"
    if record_path.exists():
        return json.loads(record_path.read_text())
    async with sem:
        if spend.exhausted:
            return {"cell_key": key, "status": "not_attempted_budget"}
        evidence_root = directory / "evidence" / key
        payload = next(c.payload for c in setup.plan.cases if c.case_id == cell.case_id)
        if setup.provider == "fake":
            providers = {"fake": ReferenceClient(payload)}
        else:
            providers = {"openrouter": _client(entry["route_id"], ARMS[entry["arm"]]["timeout_seconds"][entry["route_id"]])}
        record: dict[str, Any] = {"cell_key": key, "arm": entry["arm"], "route_id": entry["route_id"], "seat": entry["seat"],
                                  "case_id": cell.case_id, "cell_id": cell.cell_id, "run_plan_id": setup.plan.run_plan_id}
        try:
            execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=evidence_root,
                                                prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing,
                                                harnesses=setup.harnesses)
            receipt = finalize_family_execution(setup=setup, execution=execution)
            verify_evaluation_receipt(receipt)
            replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
            if replayed.receipt_sha256 != receipt.receipt_sha256:
                raise RuntimeError("replay produced a different receipt")
            cost = float(execution.total_cost_usd or 0.0)
            spend.add(cost)
            outcome = _thaw(execution.episode_result.outcome)
            record.update(status=receipt.status, receipt_sha256=receipt.receipt_sha256, episode_attempt_id=execution.episode_attempt_id,
                          cost_usd=cost, termination=outcome.get("termination") if isinstance(outcome, Mapping) else None,
                          grade=outcome.get("grade") if isinstance(outcome, Mapping) else None,
                          evidence_dir=str(execution.evidence.root.relative_to(directory)))
        except Exception as error:  # a failed cell is sealed as a typed exclusion, never rerun
            try:
                receipt = finalize_family_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error,
                                                  leaf_builder=lambda case: __import__(
                                                      "aeread_families.datacenter_development.risk_allocation_measurement",
                                                      fromlist=["primary_measurement_leaf"]).primary_measurement_leaf(case))
                record.update(status=receipt.status, receipt_sha256=receipt.receipt_sha256, error=f"{type(error).__name__}: {str(error)[:300]}")
            except Exception as sealing_error:
                record.update(status="unsealed_failure", error=f"{type(error).__name__}: {str(error)[:300]}",
                              sealing_error=f"{type(sealing_error).__name__}: {str(sealing_error)[:300]}")
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=1, default=str))
        print(f"{key:70} {record['status']:22} {record.get('termination') or ''} {record.get('grade', {}) and record['grade'].get('decision_regret', '')}", flush=True)
        return record


async def run(directory: Path, *, only_route: str | None = None) -> None:
    plan = _check(directory)
    spend = Spend(plan["max_cost_usd_total"])
    for p in (directory / "cells").glob("*.json") if (directory / "cells").exists() else ():
        spend.add(float(json.loads(p.read_text()).get("cost_usd") or 0.0))
    sems = {r: asyncio.Semaphore(WORKERS.get(r, 4)) for r in plan["routes"]}
    jobs = []
    for entry in plan["plans"]:
        if only_route and entry["route_id"] != only_route:
            continue
        setup = build_setup(entry["arm"], entry["route_id"], entry["seat"], _cases(ARMS[entry["arm"]]["pack"], entry["seat"]))
        if setup.plan.run_plan_id != entry["run_plan_id"]:
            raise SystemExit(f"run plan {entry['run_plan_id']} no longer resolves identically; freeze a new campaign")
        for cell in setup.plan.cells:
            jobs.append(_run_cell(directory, entry, setup, cell, spend, sems[entry["route_id"]]))
    await asyncio.gather(*jobs)
    print(f"spent ${spend.spent:.4f} of ${spend.cap:.2f}")


def summary(directory: Path) -> dict[str, Any]:
    rows = [json.loads(p.read_text()) for p in sorted((directory / "cells").glob("*.json"))]
    out: dict[str, Any] = {}
    for r in rows:
        k = f"{r.get('arm')}/{r.get('route_id')}/{r.get('seat')}"
        s = out.setdefault(k, {"cells": 0, "sealed_ok": 0, "valid": 0, "regret": [], "switched": 0, "signed": 0, "efficient": 0, "cost_usd": 0.0, "status": {}})
        s["cells"] += 1
        s["status"][r["status"]] = s["status"].get(r["status"], 0) + 1
        s["cost_usd"] += float(r.get("cost_usd") or 0.0)
        g = r.get("grade")
        if r["status"] == "ok" and g:
            s["sealed_ok"] += 1
            if g["valid"]:
                s["valid"] += 1
                s["regret"].append(g["decision_regret"])
                if g["signed_package"]:
                    s["signed"] += 1
                    s["switched"] += int(g["switched_package"])
                    s["efficient"] += int(g["signed_package"] == g["efficient_package"])
    for s in out.values():
        s["mean_regret"] = round(sum(s["regret"]) / len(s["regret"]), 3) if s["regret"] else None
        s["regret"] = len(s["regret"])
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["freeze", "dry-run", "smoke", "run", "summary"])
    ap.add_argument("directory", type=Path)
    ap.add_argument("--route")
    args = ap.parse_args(argv)
    if args.command == "freeze":
        p = freeze(args.directory, routes=list(ROUTES), arms=list(ARMS))
        print(f"froze {sum(len(x['cells']) for x in p['plans'])} cells in {len(p['plans'])} plans: {p['plan_sha256'][:12]}")
    elif args.command == "dry-run":
        if not args.directory.exists():
            freeze(args.directory, routes=["reference"], arms=list(ARMS), campaign_id=CAMPAIGN_ID + "_reference_dry_run")
        asyncio.run(run(args.directory))
        print(json.dumps(summary(args.directory), indent=1))
    elif args.command == "smoke":
        # one client-seat and one integrator-seat cell per route under the strictest arm: is the strict schema served?
        if not args.directory.exists():
            freeze(args.directory, routes=list(ROUTES), arms=["one_price_low"], campaign_id=CAMPAIGN_ID + "_schema_smoke")
            plan = json.loads((args.directory / "campaign_plan.json").read_text())
            for entry in plan["plans"]:
                entry["cells"] = entry["cells"][:1]
            (args.directory / "campaign_plan.json").write_text(json.dumps(plan, indent=1, default=str))
        asyncio.run(_smoke(args.directory))
    elif args.command == "run":
        asyncio.run(run(args.directory, only_route=args.route))
        print(json.dumps(summary(args.directory), indent=1))
    else:
        print(json.dumps(summary(args.directory), indent=1))
    return 0


async def _smoke(directory: Path) -> None:
    plan = _check(directory)
    spend = Spend(1.0)
    sems = {r: asyncio.Semaphore(4) for r in plan["routes"]}
    jobs = []
    for entry in plan["plans"]:
        setup = build_setup(entry["arm"], entry["route_id"], entry["seat"], _cases(ARMS[entry["arm"]]["pack"], entry["seat"]))
        wanted = {c["cell_id"] for c in entry["cells"]}
        for cell in setup.plan.cells:
            if cell.cell_id in wanted:
                jobs.append(_run_cell(directory, entry, setup, cell, spend, sems[entry["route_id"]]))
    await asyncio.gather(*jobs)
    print(json.dumps(summary(directory), indent=1))


if __name__ == "__main__":
    raise SystemExit(main())
