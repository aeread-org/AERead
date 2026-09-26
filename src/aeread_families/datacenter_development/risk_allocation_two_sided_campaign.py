"""The two-sided risk-allocation case as shared-runner campaigns.

    python -m aeread_families.datacenter_development.risk_allocation_two_sided_campaign dry-run runs/<campaign>-dry
    python -m aeread_families.datacenter_development.risk_allocation_two_sided_campaign smoke   runs/<campaign>-smoke
    python -m aeread_families.datacenter_development.risk_allocation_two_sided_campaign freeze  runs/<campaign>
    python -m aeread_families.datacenter_development.risk_allocation_two_sided_campaign run     runs/<campaign>

Both seats are players. Four model pairings cross each model as client with each
as integrator, on the 32 worlds of the one-sided eval pack, two replicates each;
two scripted pairings are controls in the same run: the one-sided counterparts'
pricing rules playing each other, and a full-information oracle that signs the
efficient contract at once (joint value lost zero, which checks the grader).

The arm is low effort with the one-sided limits and v2's retries for provider
faults; the request seed depends on world and replicate, so every pairing meets
the same seed in the same world. Everything that can end a run is in the plan.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, RunPlan, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.execution import CanonicalResponse, ProviderRequest, ProviderResult, TokenPricing, execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.task.scheduler import ActionEnvelope

from . import risk_allocation as ra
from . import risk_allocation_campaign as oc  # the one-sided campaign: routes, limits, retries, cost reader
from . import risk_allocation_two_sided as ts
from . import risk_allocation_two_sided_pack as tp
from .risk_allocation_environment import _thaw
from .risk_allocation_two_sided_environment import (
    PHASE_OF,
    PLUGIN_ID,
    STRICT_ACTION_SCHEMA_TWO_SIDED,
    TwoSidedPlugin,
    parse_move,
    two_sided_family_manifest,
    world_and_type,
)
from .risk_allocation_two_sided_measurement import (
    REFERENCE_IMPLEMENTATION_ID,
    REFERENCE_SOURCES,
    SCORER_IMPLEMENTATION_ID,
    VALIDITY_IMPLEMENTATION_ID,
    VERSION as MEASUREMENT_VERSION,
    combined_sha256,
    primary_measurement_leaf,
)

HERE = Path(__file__).parent
REPOSITORY_ROOT = HERE.parents[2]
CAMPAIGN_ID = "datacenter_risk_allocation_two_sided_dev_campaign_v1"
PACK = "two_sided_eval_v1"
RUNTIME_ID = oc.RUNTIME_ID
SEED = oc.SEED
REQUEST_SEED_BASE = 20260926
ARM = "low_effort"
LIMITS = {k: oc.ARMS["one_price_low"][k] for k in ("reasoning_effort", "max_output_tokens", "timeout_seconds", "max_cost_usd")}
SCRIPTED = "scripted_"
# client route, integrator route
PAIRINGS: dict[str, tuple[str, str]] = {
    "gemini_client_gemini_integrator": ("gemini38_flash", "gemini38_flash"),
    "gemini_client_glm_integrator": ("gemini38_flash", "glm53_flash"),
    "glm_client_gemini_integrator": ("glm53_flash", "gemini38_flash"),
    "glm_client_glm_integrator": ("glm53_flash", "glm53_flash"),
    "rule_client_rule_integrator": ("scripted_rule", "scripted_rule"),
    "oracle_client_oracle_integrator": ("scripted_oracle", "scripted_oracle"),
}
REPLICATES = 2
WORKERS_PER_PAIRING = 6
MAX_COST_USD_TOTAL = 8.0
MAX_WALL_HOURS = 4.0
CLAIM_STATUS = "diagnostic two-sided campaign with declared seat contrasts; no winner, no ranking"
DECLARED_ANALYSIS = {
    "primary": "per pairing, mean joint value lost with a world-clustered interval; the four model pairings cross each model as client with each as integrator",
    "contrasts": "swapping one seat's model with the other seat's model held fixed, paired on world and replicate (GLM minus Gemini): "
                 "client seat against a Gemini integrator and against a GLM integrator; integrator seat against a Gemini client and against a GLM client; "
                 "each on joint value lost and on the swapped seat's own surplus",
    "interval": "95% percentile bootstrap, 2000 draws, seed 20260926, worlds resampled as clusters (a twin with its base world)",
    "missingness": "an invalid or failed episode is missing for its pairing, by cause and by the seat that made it invalid; never imputed",
    "also": "individual-rationality violations per seat and model; deal and efficient-contract rates; split of the realised surplus",
    "controls": "the oracle pair must lose zero on every world; the rule pair is the scripted baseline",
    "claim": "descriptive: no winner, no ranking, no causal effect; the eight contrasts are reported without a multiplicity correction",
}
SOURCES = (
    "src/aeread_families/datacenter_development/risk_allocation.py",
    "src/aeread_families/datacenter_development/risk_allocation_two_sided.py",
    "src/aeread_families/datacenter_development/risk_allocation_two_sided_environment.py",
    "src/aeread_families/datacenter_development/risk_allocation_two_sided_measurement.py",
    "src/aeread_families/datacenter_development/risk_allocation_two_sided_pack.py",
    "src/aeread_families/datacenter_development/risk_allocation_two_sided_campaign.py",
    "src/aeread/shared_runner/task/execution.py",
    "src/aeread/shared_runner/task/evaluation.py",
)


def system_prompt(seat: str) -> str:
    pkg = ('{"warranty": "none|fix|fix_and_delay", "readiness": "client|integrator", '
           '"consequential": "excluded|included", "deposit": "at_signing|on_delivery"}')
    them = "client" if seat == "integrator" else "integrator"
    return (
        f"You are negotiating a contract on behalf of the {seat}; the {them} is another negotiator acting for itself. Each turn you receive a JSON "
        "object whose observation holds your brief (observation.brief: the facts, the risks, the contract terms, what you know about the other "
        "side and your objective), the move number, the other side's standing offer (a package and the price at which it has offered to sign "
        "it, if any), a package it asked you to price (if any), the moves so far, and the actions allowed now. Reply with exactly one JSON "
        "object and nothing else:\n"
        '{"action": "propose" | "accept" | "walk", '
        f'"package": {pkg} or null, "price": <number in $ thousands> or null, "reason": "<one or two sentences>"}}\n'
        "A proposal always states the full package, and its price is what you offer to sign at; use price null to ask the other side for its "
        "price for that package without committing. Accept takes the other side's standing offer as it stands, so its package and price are "
        "null. For walk, package and price are null."
    )


def prompt_id(seat: str) -> str:
    return f"datacenter_risk_allocation_two_sided_{seat}_prompt_v1"


@dataclass
class Setup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: dict[str, str]
    pricing: dict[str, TokenPricing]
    harnesses: dict[str, Any]
    providers: tuple[str, ...]


def _cases() -> list[CaseManifest]:
    _, raw = tp.load(PACK)
    return [CaseManifest.from_dict(c) for c in sorted(raw.values(), key=lambda c: c["case_id"])]


def _profile(pairing: str, seat: str, route_id: str) -> tuple[dict[str, Any], TokenPricing]:
    pid = prompt_id(seat)
    prompt = system_prompt(seat)
    moves = max(ts.max_moves(ra.world_from_dict(c.payload["world"])) for c in _cases()[:1])
    if route_id.startswith(SCRIPTED):
        policy = route_id[len(SCRIPTED):]
        pricing = TokenPricing(0.0, 0.0, 0.0, "scripted_policy_zero_cost_v1")
        model = {"provider": "fake", "model": f"risk-allocation-two-sided-{policy}-{seat}", "revision": f"risk_allocation_two_sided_{policy}_v1", "base_url": None}
        harness_config: dict[str, Any] = {"pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": STRICT_ACTION_SCHEMA_TWO_SIDED}
        reasoning = {"condition_id": "reasoning_unspecified_v1", "effort": None, "token_budget": None, "rationale_visibility": "hidden"}
        sampling_cfg = {"temperature": 0.0, "max_output_tokens": 1000, "seed": None, "top_p": None}
        budgets = {"max_logical_actions": moves, "timeout_seconds": 60.0, "max_cost_usd": 0.0}
        retry = {"max_action_attempts": 1, "retryable_conditions": [], "session_mode": "restart", "sdk_retries": 0}
    else:
        r = oc.ROUTES[route_id]
        pricing = r.pricing
        model = {"provider": "openrouter", "model": r.model, "revision": r.revision, "base_url": "https://openrouter.ai/api/v1"}
        harness_config = {
            "pricing_id": pricing.pricing_id, "pricing_sha256": pricing.content_sha256(), "output_schema": STRICT_ACTION_SCHEMA_TWO_SIDED,
            "provider_metadata": {"route_provider": r.provider, "quantization": r.quantization, "canonical_model": r.revision,
                                  "max_prompt_price_per_million": r.max_prompt_price_per_million,
                                  "max_completion_price_per_million": r.max_completion_price_per_million},
            **oc.RETRY_V2["backoff"], "request_seed_source": "paired_cell_v1", "request_seed_base": REQUEST_SEED_BASE,
        }
        effort = LIMITS["reasoning_effort"]
        reasoning = {"condition_id": f"reasoning_{effort}_v1", "effort": effort, "token_budget": None, "rationale_visibility": "hidden"}
        sampling_cfg = {"temperature": 1.0, "max_output_tokens": LIMITS["max_output_tokens"][route_id], "seed": SEED, "top_p": None}
        budgets = {"max_logical_actions": moves, "timeout_seconds": LIMITS["timeout_seconds"][route_id], "max_cost_usd": LIMITS["max_cost_usd"][route_id]}
        retry = {"max_action_attempts": oc.RETRY_V2["max_action_attempts"], "retryable_conditions": list(oc.RETRY_V2["retryable_conditions"]),
                 "session_mode": "restart", "sdk_retries": 0}
    profile = {
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": f"datacenter_risk_allocation_two_sided_{ARM}_{pairing}_{seat}_v1", "model": model,
        "harness": {"id": "minimal_chat", "version": "1.0", "config": harness_config},
        "prompt": {"prompt_id": pid, "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": RUNTIME_ID, "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"}, "reasoning": reasoning, "sampling": sampling_cfg, "budgets": budgets, "retry_policy": retry,
    }
    return profile, pricing


def build_setup(pairing: str, cases: Sequence[CaseManifest]) -> Setup:
    family = two_sided_family_manifest()
    client_route, integrator_route = PAIRINGS[pairing]
    scripted = client_route.startswith(SCRIPTED)
    tag = f"{ARM}_{pairing}"
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": f"risk_allocation_two_sided_{tag}_sample_v1",
        "estimand": "joint_value_lost_on_a_generated_eval_pack", "target": "negotiating_the_allocation_of_risk_between_two_players",
        "selection": "generated_admitted_cells", "seeds": [SEED], "replicates": 1 if scripted else REPLICATES, "cluster_level": "risk_allocation_world",
        "cluster_id_fields": ["world_seed"], "paired_fields": [], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"risk_allocation_two_sided_{pairing}_block",
        "kind": "reference" if scripted else ("self_play" if client_route == integrator_route else "cross_play"),
        "subject_seats": list(ts.SEATS), "controlled_profiles": {}, "repetitions": 1, "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "risk_allocation_two_sided_analysis_v1",
        "estimands": ["joint_value_lost"], "group_by": ["family_id"], "missingness": "report_separately",
        "resampling_unit": "risk_allocation_world", "uncertainty": "world_cluster_bootstrap_95", "multiplicity": "none", "sensitivity": [],
        "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": f"risk_allocation_two_sided_{PACK}", "version": "0.1.0",
        "family_ids": [family.family.id], "case_ids": [c.case_id for c in cases], "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id,
    })
    profiles, pricing = {}, {}
    for seat, route in (("client", client_route), ("integrator", integrator_route)):
        p, pr = _profile(pairing, seat, route)
        profiles[seat] = AgentProfile.from_dict(p)
        pricing[p["model"]["model"]] = pr
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": f"datacenter_risk_allocation_two_sided_{tag}_run_v1", "suite_id": suite.suite_id,
        "evaluation_block_ids": [block.block_id], "agent_profile_ids": sorted(p.profile_id for p in profiles.values()),
        "seat_assignments": {seat: p.profile_id for seat, p in profiles.items()},
        "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None,
    })
    registry = PluginRegistry()
    registry.register_trusted(family, TwoSidedPlugin())
    harnesses = default_harnesses()
    harness_registry = HarnessRegistry()
    for h in harnesses.values():
        harness_registry.register(h)
    execution_path = Path(execution_module.__file__)
    pins = (
        oc._pin(PLUGIN_ID, "family_plugin", HERE / "risk_allocation_two_sided_environment.py"),
        oc._pin(SCORER_IMPLEMENTATION_ID, "scorer", HERE / "risk_allocation_two_sided_measurement.py", version=MEASUREMENT_VERSION),
        oc._pin(VALIDITY_IMPLEMENTATION_ID, "reference", HERE / "risk_allocation_two_sided_measurement.py", version=MEASUREMENT_VERSION),
        ImplementationPin.from_dict({"component_id": REFERENCE_IMPLEMENTATION_ID, "kind": "reference", "version": MEASUREMENT_VERSION,
                                     "sha256": combined_sha256(REFERENCE_SOURCES)}),
        oc._pin("minimal_chat", "harness", execution_path, version="1.0"),
        oc._pin(RUNTIME_ID, "runtime", execution_path, version="0.1.0"),
    )
    providers = tuple(sorted({p.model.provider for p in profiles.values()}))
    reasoning_budget = any(p.reasoning.effort is not None for p in profiles.values())
    plan = resolve_run_plan(
        families=(family,), cases=tuple(cases), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis,
        agent_profiles=tuple(profiles.values()), run_spec=run_spec, registry=registry, implementation_pins=pins, harness_registry=harness_registry,
        provider_capabilities={prov: ProviderCapabilities(
            native_tools=False, structured_output=prov == "openrouter", seed=prov == "openrouter", system_prompt=True,
            reasoning_budget=prov == "openrouter" and reasoning_budget, reasoning_token_report=prov == "openrouter", max_context_tokens=None)
            for prov in providers},
    )
    prompts = {prompt_id(s): system_prompt(s) for s in ts.SEATS}
    return Setup(plan, registry, prompts, pricing, harnesses, providers)


class PairClient:
    """Both seats of a scripted pairing: it rebuilds the episode from the case and its own
    earlier replies (the seats alternate), then answers as the named policy for the seat to move."""

    def __init__(self, payload: Mapping[str, Any], policy: str) -> None:
        self.plugin = TwoSidedPlugin()
        self.payload = self.plugin.validate_payload(payload)
        self.policy = ts.POLICIES[policy]
        self.replies: list[str] = []

    def _state(self) -> dict[str, Any]:
        w, _ = world_and_type(self.payload)
        state = self.plugin.initial_state(self.payload, None)
        for text in self.replies:
            parsed = parse_move(CanonicalResponse(text, "stop", False, False, (), (), 0, 0, 0, 0.0))
            state = ts.apply(state, parsed.action, w, list(self.payload["breakoff_draws"]))
        return state

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        w, it = world_and_type(self.payload)
        move = self.policy(self._state(), w, it)
        text = json.dumps(move)
        self.replies.append(text)
        return ProviderResult(response_id=f"scripted_{len(self.replies)}", requested_model=request.model, resolved_model=request.revision or request.model,
                              output_text=text, finish_reason="stop", input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0,
                              raw_response={"scripted": True, "output_text": text})


# ---------------------------------------------------------------------------


def _digest_file(rel: str) -> str:
    return hashlib.sha256((REPOSITORY_ROOT / rel).read_bytes()).hexdigest()


def freeze(directory: Path, *, pairings: Sequence[str] | None = None, campaign_id: str = CAMPAIGN_ID) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    pairings = list(pairings or PAIRINGS)
    cases = _cases()
    plans = []
    for pairing in pairings:
        setup = build_setup(pairing, cases)
        plans.append({"pairing": pairing, "client_route": PAIRINGS[pairing][0], "integrator_route": PAIRINGS[pairing][1],
                      "run_plan_id": setup.plan.run_plan_id,
                      "cells": [{"cell_id": c.cell_id, "case_id": c.case_id, "replicate_index": c.replicate_index} for c in setup.plan.cells]})
    manifest, _ = tp.load(PACK)
    plan = {
        "campaign_id": campaign_id, "claim_status": CLAIM_STATUS, "arm": ARM, "limits": LIMITS, "pack": PACK,
        "routes": {r: asdict(oc.ROUTES[r]) for r in sorted({x for p in pairings for x in PAIRINGS[p]} & set(oc.ROUTES))},
        "pairings": {p: list(PAIRINGS[p]) for p in pairings}, "replicates": REPLICATES, "retry": oc.RETRY_V2,
        "request_seed_base": REQUEST_SEED_BASE, "workers_per_pairing": WORKERS_PER_PAIRING,
        "max_cost_usd_total": MAX_COST_USD_TOTAL, "max_wall_hours": MAX_WALL_HOURS, "seed": SEED,
        "system_prompts": {prompt_id(s): system_prompt(s) for s in ts.SEATS},
        "pack_manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "declared_analysis": DECLARED_ANALYSIS,
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


async def _run_cell(directory: Path, entry: Mapping[str, Any], setup: Setup, cell: Any, spend: oc.Spend, sem: asyncio.Semaphore) -> dict[str, Any]:
    key = f"{entry['pairing']}__{cell.case_id.rsplit('.', 1)[-1]}__r{cell.replicate_index}"
    record_path = directory / "cells" / f"{key}.json"
    if record_path.exists():
        return json.loads(record_path.read_text())
    async with sem:
        if spend.exhausted:
            return {"cell_key": key, "status": "not_attempted_budget"}
        if spend.past_deadline:
            return {"cell_key": key, "status": "not_attempted_wall_limit"}
        evidence_root = directory / "evidence" / key
        payload = next(c.payload for c in setup.plan.cases if c.case_id == cell.case_id)
        providers: dict[str, Any] = {}
        if "fake" in setup.providers:
            providers["fake"] = PairClient(payload, entry["client_route"][len(SCRIPTED):])
        if "openrouter" in setup.providers:
            routes = [r for r in (entry["client_route"], entry["integrator_route"]) if r in oc.ROUTES]
            providers["openrouter"] = oc._client(routes[0], max(LIMITS["timeout_seconds"][r] for r in routes))
        record: dict[str, Any] = {"cell_key": key, "pairing": entry["pairing"], "client_route": entry["client_route"],
                                  "integrator_route": entry["integrator_route"], "case_id": cell.case_id, "cell_id": cell.cell_id,
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
                          termination=outcome.get("termination"), grade=outcome.get("grade"),
                          evidence_dir=str(execution.evidence.root.relative_to(directory)))
        except Exception as error:  # a failed cell is sealed as a typed exclusion, never rerun
            try:
                receipt = finalize_family_failure(setup=setup, cell_id=cell.cell_id, evidence_root=evidence_root, error=error,
                                                  leaf_builder=primary_measurement_leaf)
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
        print(f"{key:70} {record['status']:22} {record.get('termination') or ''} {g.get('joint_value_lost', '')}", flush=True)
        return record


async def run(directory: Path, *, only: Sequence[str] | None = None, first_cells: int | None = None) -> None:
    plan = _check(directory)
    spend = oc.Spend(plan["max_cost_usd_total"], plan.get("max_wall_hours"))
    for p in (directory / "cells").glob("*.json") if (directory / "cells").exists() else ():
        spend.add(float(json.loads(p.read_text()).get("cost_usd") or 0.0))
    cases = _cases()
    jobs = []
    for entry in plan["plans"]:
        if only and entry["pairing"] not in only:
            continue
        setup = build_setup(entry["pairing"], cases)
        if setup.plan.run_plan_id != entry["run_plan_id"]:
            raise SystemExit(f"run plan {entry['run_plan_id']} no longer resolves identically; freeze a new campaign")
        sem = asyncio.Semaphore(plan["workers_per_pairing"])
        wanted = {c["cell_id"] for c in entry["cells"]}
        cells = [c for c in setup.plan.cells if c.cell_id in wanted][: first_cells or None]
        jobs += [_run_cell(directory, entry, setup, cell, spend, sem) for cell in cells]
    await asyncio.gather(*jobs)
    print(f"spent ${spend.spent:.4f} of ${spend.cap:.2f}")


def summary(directory: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in sorted((directory / "cells").glob("*.json")):
        r = json.loads(p.read_text())
        s = out.setdefault(r["pairing"], {"cells": 0, "valid": 0, "lost": [], "signed": 0, "efficient": 0, "ir_client": 0, "ir_integrator": 0,
                                           "cost_usd": 0.0, "status": {}})
        s["cells"] += 1
        s["status"][r["status"]] = s["status"].get(r["status"], 0) + 1
        s["cost_usd"] += float(r.get("cost_usd") or 0.0)
        g = r.get("grade") or {}
        if r["status"] == "ok" and g.get("valid"):
            s["valid"] += 1
            s["lost"].append(g["joint_value_lost"])
            s["signed"] += g["signed_package"] is not None
            s["efficient"] += bool(g["efficient_contract_signed"])
            s["ir_client"] += bool(g["client_ir_violation"])
            s["ir_integrator"] += bool(g["integrator_ir_violation"])
    for s in out.values():
        s["mean_joint_value_lost"] = round(sum(s["lost"]) / len(s["lost"]), 3) if s["lost"] else None
        s["lost"] = len(s["lost"])
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
            freeze(args.directory, pairings=[p for p in PAIRINGS if PAIRINGS[p][0].startswith(SCRIPTED)], campaign_id=CAMPAIGN_ID + "_scripted_dry_run")
        asyncio.run(run(args.directory))
        print(json.dumps(summary(args.directory), indent=1))
    elif args.command == "smoke":
        # one cell of each model pairing: are both seats served, and do the two phases alternate?
        if not args.directory.exists():
            freeze(args.directory, pairings=[p for p in PAIRINGS if not PAIRINGS[p][0].startswith(SCRIPTED)], campaign_id=CAMPAIGN_ID + "_smoke")
        asyncio.run(run(args.directory, first_cells=1))
        print(json.dumps(summary(args.directory), indent=1))
    elif args.command == "run":
        asyncio.run(run(args.directory))
        print(json.dumps(summary(args.directory), indent=1))
    else:
        print(json.dumps(summary(args.directory), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
