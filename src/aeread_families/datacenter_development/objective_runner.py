"""Shared-runner setup for the objective-aware bounded V2 data-center case."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    canonical_json_bytes,
    resolve_run_plan,
)
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
from aeread.shared_runner.task.execution import (
    CellExecution,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import EvaluationReceipt

from .objective_environment import (
    PLUGIN_ID,
    SCORER_ID,
    ObjectiveAwareStackPlugin,
    objective_stack_family_manifest,
)
from .objective_measurement import implementation_refs, primary_measurement_leaf
from .stack_runner import (
    DataCenterStackSetup,
    RUNTIME_ID,
    StackScriptedDeveloperProvider,
    _scripted_result,
    build_stack_openrouter_setup,
    build_stack_setup,
    load_stack_case,
    stack_developer_output_schemas,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OBJECTIVE_CASE_PATH = (
    REPOSITORY_ROOT
    / "cases"
    / "datacenter_development_v1"
    / "v2"
    / "objective_bounded_001.json"
)
OBJECTIVE_PROMPT_ID = "datacenter_v2_objective_developer_prompt_v1"
OBJECTIVE_RUNTIME_ID = "aeread_families.datacenter_development.objective_runner"
OBJECTIVE_PROMPT = """You are the developer negotiating a complete data-center
agreement stack. Your objective is to maximize developer equity NPV, but a
completed deal receives objective credit only when every agreement is binding,
project constraints are satisfied, and negotiation ordering is valid. Your
declared outside option is -100000 cents. You may explicitly walk; an invalid
action, rejection, or exhausted negotiation is not an intentional walk.

All currency fields are integer cents and all project months are one-based.
`cost_overrun_cap_cents: 0` means the developer bears zero permitted overrun,
not unlimited exposure. Return exactly one JSON action for the current phase.
In an offer phase, return decision, message, and every structured term. In a
commit phase, copy accepted_offer_id exactly into offer_id and either sign or
walk. Never invent an offer ID. If you adopt a pending written counteroffer,
copy its complete structured terms exactly; prose does not amend written terms.
Only complete structured terms and signatures over accepted offer IDs bind.
Respect explicit land-amendment precedence."""


def _pin(
    component_id: str,
    kind: str,
    source_path: Path,
    *,
    version: str = "1.0.0",
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def _objective_profile(
    profile: AgentProfile,
    case: Any,
    *,
    developer: bool,
) -> AgentProfile:
    data = json.loads(canonical_json_bytes(profile))
    if developer:
        data["profile_id"] = f"{profile.profile_id}_objective_v1"
        data["prompt"] = {
            "prompt_id": OBJECTIVE_PROMPT_ID,
            "sha256": hashlib.sha256(OBJECTIVE_PROMPT.encode("utf-8")).hexdigest(),
        }
    elif profile.model.provider.startswith("datacenter_stack_scripted_"):
        data["profile_id"] = f"{profile.profile_id}_objective_exact_v1"
    if profile.model.provider.startswith("datacenter_stack_scripted_"):
        data["runtime"]["implementation"] = OBJECTIVE_RUNTIME_ID
    if developer and profile.model.provider == "openrouter":
        data["harness"]["config"]["output_schema_by_action_schema"] = (
            stack_developer_output_schemas(case)
        )
    return AgentProfile.from_dict(data)


class ObjectiveExactCounterpartyProvider:
    """Counter unless the written offer equals the calibrated package exactly."""

    def __init__(self, seat_id: str) -> None:
        self._seat_id = seat_id

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        expected_provider = f"datacenter_stack_scripted_{self._seat_id}"
        if request.provider != expected_provider:
            raise ProviderFailure(
                "provider_contract",
                "wrong objective counterparty provider",
                retryable=False,
            )
        payload = json.loads(request.input_text)
        if not payload["phase_id"].endswith("_response"):
            raise ProviderFailure(
                "provider_contract",
                "objective counterparty received wrong phase",
                retryable=False,
            )
        observation = payload["observation"]
        offer = observation["latest_offer"]
        target = observation["private_policy"]["counter_terms"]
        acceptable = canonical_json_bytes(offer["terms"]) == canonical_json_bytes(target)
        output = (
            {
                "decision": "accept",
                "offer_id": offer["offer_id"],
                "message": f"{self._seat_id} accepts the exact written package.",
                "terms": None,
            }
            if acceptable
            else {
                "decision": "counter",
                "offer_id": offer["offer_id"],
                "message": f"{self._seat_id} returns the calibrated package.",
                "terms": target,
            }
        )
        return _scripted_result(request, output)


def _objective_providers(setup: DataCenterStackSetup) -> dict[str, Any]:
    seats = sorted(
        seat.id for seat in setup.case.seats if seat.id != "developer"
    )
    return {
        "datacenter_stack_scripted_developer": StackScriptedDeveloperProvider(
            setup.case.payload["scripted_developer"]
        ),
        **{
            f"datacenter_stack_scripted_{seat}": ObjectiveExactCounterpartyProvider(
                seat
            )
            for seat in seats
        },
    }


def build_objective_stack_setup(
    *,
    route: Any | None = None,
    seed: int | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
) -> DataCenterStackSetup:
    """Resolve one controlled-counterparty plan with an objective-visible developer."""

    if route is None:
        if seed is not None:
            raise ValueError("offline objective setup does not accept an inference seed")
        base = build_stack_setup("v2")
    else:
        if seed is None or seed < 0:
            raise ValueError("live objective setup requires a non-negative seed")
        base = build_stack_openrouter_setup(
            "v2",
            route,
            seed=seed,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            max_cost_usd=max_cost_usd,
        )

    case = load_stack_case("v2", OBJECTIVE_CASE_PATH)
    plugin = ObjectiveAwareStackPlugin()
    family_case = plugin.validate_payload(case.payload)
    family = objective_stack_family_manifest()
    old_developer_id = base.plan.cells[0].profile_by_seat["developer"]
    transformed_by_old_id = {
        profile.profile_id: _objective_profile(
            profile,
            case,
            developer=profile.profile_id == old_developer_id,
        )
        for profile in base.plan.agent_profiles
    }
    developer = transformed_by_old_id[old_developer_id]
    profiles = tuple(
        transformed_by_old_id[profile.profile_id]
        for profile in base.plan.agent_profiles
    )
    seat_assignments = {
        seat_id: transformed_by_old_id[profile_id].profile_id
        for seat_id, profile_id in base.plan.cells[0].profile_by_seat.items()
    }
    controlled_profiles = {
        seat_id: profile_id
        for seat_id, profile_id in seat_assignments.items()
        if seat_id != "developer"
    }
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "datacenter_v2_objective_controlled_counterparties_v1",
            "kind": "controlled",
            "subject_seats": ["developer"],
            "controlled_profiles": controlled_profiles,
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": "datacenter_v2_objective_bounded_sample_v1",
            "estimand": "safe_developer_objective_attainment",
            "target": case.provenance.generator_id,
            "selection": "fixed_curated_objective_calibration",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "datacenter_v2_objective_bounded_analysis_v1",
            "estimands": [
                "safe_developer_objective_attainment",
                "developer_equity_npv",
                "binding_contract_integrity",
                "project_constraint_satisfaction",
                "negotiation_temporal_compliance",
                "intentional_resolution",
                "controlled_reference_dominance",
            ],
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
            "suite_id": "datacenter_development_v2_objective_bounded_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
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
                "datacenter_v2_objective_bounded_offline_v1"
                if route is None
                else f"datacenter_v2_objective_bounded_{developer.profile_id}"
            ),
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id for profile in profiles],
            "seat_assignments": seat_assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness_registry = HarnessRegistry()
    seen_harnesses: set[tuple[str, str]] = set()
    for harness in base.harnesses.values():
        identity = (harness.id, harness.version)
        if identity not in seen_harnesses:
            harness_registry.register(harness)
            seen_harnesses.add(identity)

    replaced_ids = {
        RUNTIME_ID,
        "datacenter_development_environment_v2",
        "datacenter_development_score_set_v1",
        "datacenter_measurement_references_v1",
        "datacenter_measurement_validity_v1",
    }
    pins = [
        pin
        for pin in base.plan.implementation_pins
        if pin.component_id not in replaced_ids
    ]
    pins.append(
        _pin(
            PLUGIN_ID,
            "family_plugin",
            Path(__file__).with_name("objective_environment.py"),
        )
    )
    pins.append(
        _pin(
            OBJECTIVE_RUNTIME_ID,
            "runtime",
            Path(__file__),
            version="0.1.0",
        )
    )
    measurement_path = Path(__file__).with_name("objective_measurement.py")
    for implementation in implementation_refs():
        pins.append(
            _pin(
                implementation.implementation_id,
                (
                    "scorer"
                    if implementation.implementation_id == SCORER_ID
                    else "reference"
                ),
                measurement_path,
                version=implementation.version,
            )
        )

    capabilities: dict[str, ProviderCapabilities] = {}
    for profile in profiles:
        provider_id = profile.model.provider
        if provider_id == "openrouter":
            capabilities[provider_id] = ProviderCapabilities(
                native_tools=False,
                structured_output=True,
                seed=True,
                system_prompt=True,
                reasoning_budget=profile.reasoning.effort is not None,
                reasoning_token_report=True,
                max_context_tokens=None,
            )
        else:
            capabilities[provider_id] = ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
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
    del family_case
    return DataCenterStackSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            **dict(base.prompt_sources),
            OBJECTIVE_PROMPT_ID: OBJECTIVE_PROMPT,
        },
        pricing=base.pricing,
        case=case,
        harnesses=base.harnesses,
        scope_version="v2",
    )


async def run_objective_stack_offline(
    *, evidence_root: Path | str
) -> tuple[DataCenterStackSetup, CellExecution]:
    setup = build_objective_stack_setup()
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers=_objective_providers(setup),
        pricing=setup.pricing,
        harnesses=setup.harnesses,
    )
    return setup, execution


async def run_objective_stack_openrouter(
    route: Any,
    *,
    evidence_root: Path | str,
    seed: int,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
    provider: Any | None = None,
) -> tuple[DataCenterStackSetup, CellExecution]:
    setup = build_objective_stack_setup(
        route=route,
        seed=seed,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
    )
    providers = _objective_providers(setup)
    providers.pop("datacenter_stack_scripted_developer", None)
    providers["openrouter"] = provider or OpenRouterChatClient()
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


def finalize_objective_stack_execution(
    *, setup: DataCenterStackSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_objective_stack_failure(
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


def replay_objective_stack_receipt(
    *,
    setup: DataCenterStackSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=evidence_root,
    )


__all__ = [
    "OBJECTIVE_CASE_PATH",
    "OBJECTIVE_PROMPT",
    "OBJECTIVE_PROMPT_ID",
    "OBJECTIVE_RUNTIME_ID",
    "ObjectiveExactCounterpartyProvider",
    "build_objective_stack_setup",
    "finalize_objective_stack_execution",
    "finalize_objective_stack_failure",
    "replay_objective_stack_receipt",
    "run_objective_stack_offline",
    "run_objective_stack_openrouter",
]
