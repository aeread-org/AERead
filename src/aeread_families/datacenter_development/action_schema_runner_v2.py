"""V2 action-schema runner with an explicit opening-action contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    EvaluationBlock,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import CellExecution, execute_plan_cell
from aeread.shared_runner.task.receipts import EvaluationReceipt

from .action_schema_environment import (
    CounterofferActionSchemaPlugin,
    action_schema_family_manifest,
)
from .action_schema_runner import (
    RUNTIME_ID as V1_RUNTIME_ID,
    _providers,
    build_action_schema_setup,
)
from .adoption_measurement import primary_measurement_leaf
from .adoption_runner import _pin
from .objective_openrouter import ParameterCompatibleOpenRouterClient
from .stack_runner import DataCenterStackSetup


RUNTIME_ID = "aeread_families.datacenter_development.action_schema_runner_v2"
DEVELOPER_PROMPT_ID = "datacenter_counteroffer_action_schema_developer_prompt_v2"
DEVELOPER_PROMPT = """You are the developer in a land-agreement diagnostic.
This task measures exact adoption of a controlled written counteroffer, not NPV.

For the opening offer, return exactly these four fields:
- decision: "offer"
- offer_id: null
- message: a short string or null
- terms: an exact copy of starter_offer_terms, including every field and array

After the formal counteroffer appears, accept it by copying
pending_counteroffer_offer_id exactly. The current phase's output schema is
authoritative. Under the shared offer schema return decision
"accept_counteroffer", that offer_id, and message and terms both null. Under
the dedicated acceptance schema return only decision and offer_id. Then sign
accepted_offer_id exactly. Never create or guess an offer ID."""


def _profile(profile: AgentProfile, *, developer: bool) -> AgentProfile:
    data = json.loads(canonical_json_bytes(profile))
    data["profile_id"] = f"{profile.profile_id}_opening_contract_v2"
    data["runtime"]["implementation"] = RUNTIME_ID
    if developer:
        data["prompt"] = {
            "prompt_id": DEVELOPER_PROMPT_ID,
            "sha256": hashlib.sha256(DEVELOPER_PROMPT.encode("utf-8")).hexdigest(),
        }
    return AgentProfile.from_dict(data)


def build_action_schema_setup_v2(
    condition: str,
    *,
    route: Any | None = None,
    seed: int | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
) -> DataCenterStackSetup:
    base = build_action_schema_setup(
        condition,
        route=route,
        seed=seed,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
    )
    case = base.case
    plugin = CounterofferActionSchemaPlugin()
    plugin.validate_payload(case.payload)
    family = action_schema_family_manifest()
    old_developer_id = base.plan.cells[0].profile_by_seat["developer"]
    transformed = {
        profile.profile_id: _profile(
            profile, developer=profile.profile_id == old_developer_id
        )
        for profile in base.plan.agent_profiles
    }
    profiles = tuple(transformed[p.profile_id] for p in base.plan.agent_profiles)
    assignments = {
        seat: transformed[profile_id].profile_id
        for seat, profile_id in base.plan.cells[0].profile_by_seat.items()
    }
    controlled = {
        seat: profile_id
        for seat, profile_id in assignments.items()
        if seat != "developer"
    }
    block_data = json.loads(canonical_json_bytes(base.plan.evaluation_blocks[0]))
    block_data["block_id"] = (
        f"datacenter_counteroffer_action_schema_{condition}_controlled_v2"
    )
    block_data["controlled_profiles"] = controlled
    block = EvaluationBlock.from_dict(block_data)
    sampling_data = json.loads(canonical_json_bytes(base.plan.sampling))
    sampling_data["sampling_plan_id"] = (
        f"datacenter_counteroffer_action_schema_{condition}_sample_v2"
    )
    sampling_data["selection"] = (
        "fixed_paired_counteroffer_action_schema_explicit_opening_contract"
    )
    sampling = SamplingPlan.from_dict(sampling_data)
    analysis_data = json.loads(canonical_json_bytes(base.plan.analysis))
    analysis_data["analysis_plan_id"] = (
        f"datacenter_counteroffer_action_schema_{condition}_analysis_v2"
    )
    analysis = AnalysisPlan.from_dict(analysis_data)
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"datacenter_counteroffer_action_schema_{condition}_v2",
            "version": "1.0.0",
            "family_ids": [case.family_id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": f"datacenter_counteroffer_action_schema_{condition}_{assignments['developer']}_v2",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id for profile in profiles],
            "seat_assignments": assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness_registry = HarnessRegistry()
    seen: set[tuple[str, str]] = set()
    for harness in base.harnesses.values():
        identity = (harness.id, harness.version)
        if identity not in seen:
            harness_registry.register(harness)
            seen.add(identity)
    pins = [
        pin
        for pin in base.plan.implementation_pins
        if pin.component_id != V1_RUNTIME_ID
    ]
    pins.append(_pin(RUNTIME_ID, "runtime", Path(__file__), version="0.2.0"))
    capabilities = {}
    for profile in profiles:
        live = profile.model.provider == "openrouter"
        capabilities[profile.model.provider] = ProviderCapabilities(
            native_tools=False,
            structured_output=live,
            seed=live,
            system_prompt=True,
            reasoning_budget=live and profile.reasoning.effort is not None,
            reasoning_token_report=live,
            max_context_tokens=None,
        )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=profiles,
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities=capabilities,
    )
    return DataCenterStackSetup(
        plan=plan,
        registry=registry,
        prompt_sources={**dict(base.prompt_sources), DEVELOPER_PROMPT_ID: DEVELOPER_PROMPT},
        pricing=base.pricing,
        case=case,
        harnesses=base.harnesses,
        scope_version=condition,
    )


async def run_action_schema_offline_v2(
    condition: str, *, evidence_root: Path | str
):
    setup = build_action_schema_setup_v2(condition)
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers=_providers(setup),
        pricing=setup.pricing,
        harnesses=setup.harnesses,
    )
    return setup, execution


async def run_action_schema_openrouter_v2(
    condition: str,
    route: Any,
    *,
    evidence_root: Path | str,
    seed: int,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
    provider: Any | None = None,
):
    setup = build_action_schema_setup_v2(
        condition,
        route=route,
        seed=seed,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
    )
    providers = _providers(setup)
    providers.pop("datacenter_adoption_scripted_developer")
    providers["openrouter"] = provider or ParameterCompatibleOpenRouterClient()
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers=providers,
        pricing=setup.pricing,
        harnesses=setup.harnesses,
    )
    return setup, execution


def finalize_action_schema_execution_v2(
    *, setup: DataCenterStackSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_action_schema_failure_v2(
    *,
    setup: DataCenterStackSetup,
    cell_id: str,
    evidence_root: Path | str,
    error: BaseException,
) -> EvaluationReceipt:
    return finalize_family_failure(
        setup=setup,
        cell_id=cell_id,
        evidence_root=evidence_root,
        error=error,
        leaf_builder=primary_measurement_leaf,
    )


def replay_action_schema_receipt_v2(
    *,
    setup: DataCenterStackSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


__all__ = [
    "RUNTIME_ID",
    "build_action_schema_setup_v2",
    "finalize_action_schema_execution_v2",
    "finalize_action_schema_failure_v2",
    "replay_action_schema_receipt_v2",
    "run_action_schema_offline_v2",
    "run_action_schema_openrouter_v2",
]
