"""Runner for V3 nullable nonbinding prose counteroffer adoption."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_execution, finalize_family_failure, replay_family_receipt
from aeread.shared_runner.task.execution import CellExecution, execute_plan_cell
from aeread.shared_runner.task.receipts import EvaluationReceipt

from .adoption_environment import STAGE_SEQUENCES
from .adoption_environment_v2 import PLUGIN_ID as V2_PLUGIN_ID
from .adoption_environment_v3 import PLUGIN_ID, NullableProseCounterofferAdoptionPlugin, adoption_family_manifest_v3
from .adoption_measurement import primary_measurement_leaf
from .adoption_runner import _pin, _providers
from .adoption_runner_v2 import DEVELOPER_PROMPT_V2, DEVELOPER_PROMPT_V2_ID, RUNTIME_ID as V2_RUNTIME_ID, build_adoption_setup_v2
from .objective_openrouter import ParameterCompatibleOpenRouterClient
from .stack_runner import DataCenterStackSetup


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = REPOSITORY_ROOT / "cases" / "datacenter_counteroffer_adoption_v1" / "v3"
CASE_PATH_BY_STAGE = {stage_id: CASE_ROOT / f"{stage_id}_001.json" for stage_id in STAGE_SEQUENCES}
RUNTIME_ID = "aeread_families.datacenter_development.adoption_runner_v3"


def load_adoption_case_v3(stage_id: str) -> CaseManifest:
    if stage_id not in CASE_PATH_BY_STAGE:
        raise ValueError(f"unknown adoption stage: {stage_id}")
    case = CaseManifest.from_dict(json.loads(CASE_PATH_BY_STAGE[stage_id].read_text(encoding="utf-8")))
    computed = case_content_sha256(case)
    if computed != case.content_sha256:
        raise ValueError(f"case content hash mismatch: declared {case.content_sha256}, computed {computed}")
    return case


def _profile(profile: AgentProfile) -> AgentProfile:
    data = json.loads(canonical_json_bytes(profile))
    data["profile_id"] = f"{profile.profile_id}_nullable_prose_v3"
    data["runtime"]["implementation"] = RUNTIME_ID
    return AgentProfile.from_dict(data)


def build_adoption_setup_v3(
    stage_id: str,
    *,
    route: Any | None = None,
    seed: int | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
) -> DataCenterStackSetup:
    base = build_adoption_setup_v2(stage_id, route=route, seed=seed, max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds, max_cost_usd=max_cost_usd)
    case = load_adoption_case_v3(stage_id)
    plugin = NullableProseCounterofferAdoptionPlugin()
    plugin.validate_payload(case.payload)
    family = adoption_family_manifest_v3()

    transformed = {profile.profile_id: _profile(profile) for profile in base.plan.agent_profiles}
    profiles = tuple(transformed[profile.profile_id] for profile in base.plan.agent_profiles)
    assignments = {seat: transformed[profile_id].profile_id for seat, profile_id in base.plan.cells[0].profile_by_seat.items()}
    controlled = {seat: profile_id for seat, profile_id in assignments.items() if seat != "developer"}

    block_data = json.loads(canonical_json_bytes(base.plan.evaluation_blocks[0]))
    block_data["block_id"] = f"datacenter_adoption_{stage_id}_nullable_prose_controlled_v3"
    block_data["controlled_profiles"] = controlled
    block = EvaluationBlock.from_dict(block_data)
    sampling_data = json.loads(canonical_json_bytes(base.plan.sampling))
    sampling_data["sampling_plan_id"] = f"datacenter_adoption_{stage_id}_nullable_prose_sample_v3"
    sampling_data["selection"] = "fixed_nested_prefix_starter_grounded_nullable_prose"
    sampling = SamplingPlan.from_dict(sampling_data)
    analysis_data = json.loads(canonical_json_bytes(base.plan.analysis))
    analysis_data["analysis_plan_id"] = f"datacenter_adoption_{stage_id}_nullable_prose_analysis_v3"
    analysis = AnalysisPlan.from_dict(analysis_data)
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION,
        "suite_id": f"datacenter_counteroffer_adoption_{stage_id}_nullable_prose_v3",
        "version": "1.0.0",
        "family_ids": [case.family_id],
        "case_ids": [case.case_id],
        "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id],
        "analysis_plan_id": analysis.analysis_plan_id,
    })
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION,
        "run_spec_id": f"datacenter_adoption_{stage_id}_{assignments['developer']}",
        "suite_id": suite.suite_id,
        "evaluation_block_ids": [block.block_id],
        "agent_profile_ids": [profile.profile_id for profile in profiles],
        "seat_assignments": assignments,
        "execution_mode": "evaluate",
        "replicate_override": None,
        "budget_overrides": None,
    })
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness_registry = HarnessRegistry()
    seen = set()
    for harness in base.harnesses.values():
        identity = (harness.id, harness.version)
        if identity not in seen:
            harness_registry.register(harness)
            seen.add(identity)
    pins = [pin for pin in base.plan.implementation_pins if pin.component_id not in {V2_PLUGIN_ID, V2_RUNTIME_ID}]
    pins.extend((
        _pin(PLUGIN_ID, "family_plugin", Path(__file__).with_name("adoption_environment_v3.py")),
        _pin(RUNTIME_ID, "runtime", Path(__file__), version="0.1.0"),
    ))
    capabilities = {}
    for profile in profiles:
        live = profile.model.provider == "openrouter"
        capabilities[profile.model.provider] = ProviderCapabilities(native_tools=False, structured_output=live, seed=live, system_prompt=True, reasoning_budget=live and profile.reasoning.effort is not None, reasoning_token_report=live, max_context_tokens=None)
    plan = resolve_run_plan(
        families=(family,), cases=(case,), suite=suite, sampling=sampling,
        evaluation_blocks=(block,), analysis=analysis, agent_profiles=profiles,
        run_spec=run_spec, registry=registry, implementation_pins=tuple(pins),
        harness_registry=harness_registry, provider_capabilities=capabilities,
    )
    return DataCenterStackSetup(plan=plan, registry=registry, prompt_sources={**dict(base.prompt_sources), DEVELOPER_PROMPT_V2_ID: DEVELOPER_PROMPT_V2}, pricing=base.pricing, case=case, harnesses=base.harnesses, scope_version=stage_id)


async def run_adoption_offline_v3(stage_id: str, *, evidence_root: Path | str):
    setup = build_adoption_setup_v3(stage_id)
    execution = await execute_plan_cell(plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry, evidence_root=Path(evidence_root), prompt_sources=setup.prompt_sources, providers=_providers(setup), pricing=setup.pricing, harnesses=setup.harnesses)
    return setup, execution


async def run_adoption_openrouter_v3(stage_id: str, route: Any, *, evidence_root: Path | str, seed: int, max_output_tokens: int = 1600, timeout_seconds: float = 180.0, max_cost_usd: float = 0.03, provider: Any | None = None):
    setup = build_adoption_setup_v3(stage_id, route=route, seed=seed, max_output_tokens=max_output_tokens, timeout_seconds=timeout_seconds, max_cost_usd=max_cost_usd)
    providers = _providers(setup)
    providers.pop("datacenter_adoption_scripted_developer")
    providers["openrouter"] = provider or ParameterCompatibleOpenRouterClient()
    execution = await execute_plan_cell(plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry, evidence_root=Path(evidence_root), prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing, harnesses=setup.harnesses)
    return setup, execution


def finalize_adoption_execution_v3(*, setup: DataCenterStackSetup, execution: CellExecution) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_adoption_failure_v3(*, setup: DataCenterStackSetup, cell_id: str, evidence_root: Path | str, error: BaseException) -> EvaluationReceipt:
    return finalize_family_failure(setup=setup, cell_id=cell_id, evidence_root=evidence_root, error=error, leaf_builder=primary_measurement_leaf)


def replay_adoption_receipt_v3(*, setup: DataCenterStackSetup, receipt: EvaluationReceipt, evidence_root: Path | str) -> EvaluationReceipt:
    return replay_family_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)


__all__ = ["CASE_PATH_BY_STAGE", "RUNTIME_ID", "build_adoption_setup_v3", "finalize_adoption_execution_v3", "finalize_adoption_failure_v3", "load_adoption_case_v3", "replay_adoption_receipt_v3", "run_adoption_offline_v3", "run_adoption_openrouter_v3"]
