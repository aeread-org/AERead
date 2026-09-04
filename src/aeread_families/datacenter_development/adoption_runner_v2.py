"""Runner for the starter-grounded V2 counteroffer-adoption ladder."""

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
from aeread.shared_runner.run.resolver import (
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
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

from .adoption_environment import (
    PLUGIN_ID as V1_PLUGIN_ID,
    STAGE_SEQUENCES,
)
from .adoption_environment_v2 import (
    PLUGIN_ID,
    StarterGroundedCounterofferAdoptionPlugin,
    adoption_family_manifest_v2,
)
from .adoption_measurement import primary_measurement_leaf
from .adoption_runner import (
    COUNTERPART_PROMPT_ID,
    DEVELOPER_PROMPT_ID,
    RUNTIME_ID as V1_RUNTIME_ID,
    _developer_output_schemas,
    _pin,
    _providers,
    build_adoption_setup,
)
from .objective_openrouter import ParameterCompatibleOpenRouterClient
from .stack_runner import DataCenterStackSetup


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = REPOSITORY_ROOT / "cases" / "datacenter_counteroffer_adoption_v1" / "v2"
CASE_PATH_BY_STAGE = {
    stage_id: CASE_ROOT / f"{stage_id}_001.json"
    for stage_id in STAGE_SEQUENCES
}
RUNTIME_ID = "aeread_families.datacenter_development.adoption_runner_v2"
DEVELOPER_PROMPT_V2_ID = "datacenter_counteroffer_adoption_developer_prompt_v2"
DEVELOPER_PROMPT_V2 = """You are the developer in a staged data-center
counteroffer-adoption diagnostic. This does not score project NPV.

At the first offer for each agreement, the observation contains
starter_offer_terms. Copy that complete object exactly as your structured first
offer. The controlled counterparty will then return a different complete written
counteroffer. On the next offer, copy pending_counter_terms exactly, with every
field and array preserved. After acceptance, copy accepted_offer_id exactly into
offer_id and sign.

Return exactly one JSON action for the current phase. Never wait for the
counterparty to open; you must submit starter_offer_terms first. Never invent an
offer ID. Prose does not amend structured terms. If you walk, return decision
"walk" with message and terms both null; walking receives zero adoption credit."""


def load_adoption_case_v2(stage_id: str) -> CaseManifest:
    if stage_id not in CASE_PATH_BY_STAGE:
        raise ValueError(f"unknown adoption stage: {stage_id}")
    path = CASE_PATH_BY_STAGE[stage_id]
    case = CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    computed = case_content_sha256(case)
    if computed != case.content_sha256:
        raise ValueError(
            f"case content hash mismatch: declared {case.content_sha256}, "
            f"computed {computed}"
        )
    return case


def _transformed_profile(
    profile: AgentProfile,
    *,
    developer: bool,
    family_case: dict[str, Any],
) -> AgentProfile:
    data = json.loads(canonical_json_bytes(profile))
    data["profile_id"] = f"{profile.profile_id}_starter_v2"
    data["runtime"]["implementation"] = RUNTIME_ID
    if developer:
        data["prompt"] = {
            "prompt_id": DEVELOPER_PROMPT_V2_ID,
            "sha256": hashlib.sha256(DEVELOPER_PROMPT_V2.encode("utf-8")).hexdigest(),
        }
        if profile.model.provider == "openrouter":
            data["harness"]["config"]["output_schema_by_action_schema"] = (
                _developer_output_schemas(family_case)
            )
    return AgentProfile.from_dict(data)


def build_adoption_setup_v2(
    stage_id: str,
    *,
    route: Any | None = None,
    seed: int | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
) -> DataCenterStackSetup:
    base = build_adoption_setup(
        stage_id,
        route=route,
        seed=seed,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
    )
    case = load_adoption_case_v2(stage_id)
    plugin = StarterGroundedCounterofferAdoptionPlugin()
    family_case = plugin.validate_payload(case.payload)
    family = adoption_family_manifest_v2()

    old_developer_id = base.plan.cells[0].profile_by_seat["developer"]
    transformed_by_old_id = {
        profile.profile_id: _transformed_profile(
            profile,
            developer=profile.profile_id == old_developer_id,
            family_case=family_case,
        )
        for profile in base.plan.agent_profiles
    }
    profiles = tuple(
        transformed_by_old_id[profile.profile_id]
        for profile in base.plan.agent_profiles
    )
    assignments = {
        seat_id: transformed_by_old_id[profile_id].profile_id
        for seat_id, profile_id in base.plan.cells[0].profile_by_seat.items()
    }
    controlled = {
        seat_id: profile_id
        for seat_id, profile_id in assignments.items()
        if seat_id != "developer"
    }
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"datacenter_adoption_{stage_id}_starter_controlled_v2",
            "kind": "controlled",
            "subject_seats": ["developer"],
            "controlled_profiles": controlled,
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": f"datacenter_adoption_{stage_id}_starter_sample_v2",
            "estimand": "counteroffer_adoption_rate",
            "target": case.provenance.generator_id,
            "selection": "fixed_nested_prefix_starter_grounded_diagnostic",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    estimands = [
        "counteroffer_adoption_rate",
        "prefix_completion",
        "exact_package_integrity",
        "executed_agreement_count",
        "counteroffer_opportunity_count",
        "negotiation_temporal_compliance",
        "intentional_resolution",
    ]
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": f"datacenter_adoption_{stage_id}_starter_analysis_v2",
            "estimands": estimands,
            "group_by": ["family_id", "family_version"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": f"datacenter_counteroffer_adoption_{stage_id}_starter_v2",
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
            "run_spec_id": (
                f"datacenter_adoption_{stage_id}_starter_offline_v2"
                if route is None
                else f"datacenter_adoption_{stage_id}_{assignments['developer']}"
            ),
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
        if pin.component_id not in {V1_PLUGIN_ID, V1_RUNTIME_ID}
    ]
    pins.extend(
        (
            _pin(
                PLUGIN_ID,
                "family_plugin",
                Path(__file__).with_name("adoption_environment_v2.py"),
            ),
            _pin(RUNTIME_ID, "runtime", Path(__file__), version="0.1.0"),
        )
    )
    capabilities: dict[str, ProviderCapabilities] = {}
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
        prompt_sources={
            **dict(base.prompt_sources),
            DEVELOPER_PROMPT_V2_ID: DEVELOPER_PROMPT_V2,
        },
        pricing=base.pricing,
        case=case,
        harnesses=base.harnesses,
        scope_version=stage_id,
    )


async def run_adoption_offline_v2(
    stage_id: str, *, evidence_root: Path | str
) -> tuple[DataCenterStackSetup, CellExecution]:
    setup = build_adoption_setup_v2(stage_id)
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


async def run_adoption_openrouter_v2(
    stage_id: str,
    route: Any,
    *,
    evidence_root: Path | str,
    seed: int,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
    provider: Any | None = None,
) -> tuple[DataCenterStackSetup, CellExecution]:
    setup = build_adoption_setup_v2(
        stage_id,
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


def finalize_adoption_execution_v2(
    *, setup: DataCenterStackSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_adoption_failure_v2(
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


def replay_adoption_receipt_v2(
    *,
    setup: DataCenterStackSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


__all__ = [
    "CASE_PATH_BY_STAGE",
    "DEVELOPER_PROMPT_V2",
    "RUNTIME_ID",
    "build_adoption_setup_v2",
    "finalize_adoption_execution_v2",
    "finalize_adoption_failure_v2",
    "load_adoption_case_v2",
    "replay_adoption_receipt_v2",
    "run_adoption_offline_v2",
    "run_adoption_openrouter_v2",
]
