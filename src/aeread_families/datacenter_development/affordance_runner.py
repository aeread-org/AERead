"""Shared-runner setup for counteroffer acceptance-affordance diagnosis."""

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
from aeread.shared_runner.task.execution import (
    CellExecution,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import EvaluationReceipt

from .adoption_environment_v3 import PLUGIN_ID as ADOPTION_V3_PLUGIN_ID
from .adoption_measurement import primary_measurement_leaf
from .adoption_runner import ForcedCounterpartyProvider, _pin
from .adoption_runner_v3 import (
    RUNTIME_ID as ADOPTION_V3_RUNTIME_ID,
    build_adoption_setup_v3,
)
from .affordance_environment import (
    CONDITIONS,
    PLUGIN_ID,
    CounterofferAffordancePlugin,
    affordance_family_manifest,
)
from .objective_openrouter import ParameterCompatibleOpenRouterClient
from .stack_runner import (
    DataCenterStackSetup,
    _scripted_result,
    _strict_schema_from_example,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = (
    REPOSITORY_ROOT / "cases" / "datacenter_counteroffer_affordance_v1" / "v1"
)
CASE_PATH_BY_CONDITION = {
    "reemit_package": CASE_ROOT / "reemit_package_001.json",
    "accept_by_reference": CASE_ROOT / "accept_by_reference_001.json",
}
RUNTIME_ID = "aeread_families.datacenter_development.affordance_runner"
DEVELOPER_PROMPT_ID = "datacenter_counteroffer_affordance_developer_prompt_v1"
DEVELOPER_PROMPT = """You are the developer in a land-agreement diagnostic.
This task measures exact adoption of a controlled written counteroffer, not NPV.

At the first offer, copy starter_offer_terms exactly. Always return all four
offer-phase fields: decision, offer_id, message, and terms. Set offer_id to null
for offer or walk. When counteroffer_resolution appears, follow its required
action exactly. In reemit_package mode, copy pending_counter_terms into terms.
In accept_by_reference mode, return decision accept_counteroffer and copy
pending_counteroffer_offer_id into offer_id; message and terms must be null.
After either path is accepted, sign accepted_offer_id exactly in the commit
phase. Never invent an offer ID. Prose does not amend structured terms."""


def load_affordance_case(condition: str) -> CaseManifest:
    if condition not in CASE_PATH_BY_CONDITION:
        raise ValueError(f"unknown affordance condition: {condition}")
    case = CaseManifest.from_dict(
        json.loads(CASE_PATH_BY_CONDITION[condition].read_text(encoding="utf-8"))
    )
    computed = case_content_sha256(case)
    if computed != case.content_sha256:
        raise ValueError(
            f"case content hash mismatch: declared {case.content_sha256}, "
            f"computed {computed}"
        )
    return case


def _developer_output_schemas(family_case: dict[str, Any]) -> dict[str, Any]:
    terms = family_case["policies"]["land"]["counter_terms"]
    term_schema = _strict_schema_from_example(terms)
    return {
        "datacenter_land_offer_v1": {
            "type": "object",
            "properties": {
                "decision": {
                    "enum": ["offer", "walk", "accept_counteroffer"]
                },
                "offer_id": {"type": ["string", "null"]},
                "message": {"type": ["string", "null"]},
                "terms": {"anyOf": [term_schema, {"type": "null"}]},
            },
            "required": ["decision", "offer_id", "message", "terms"],
            "additionalProperties": False,
        },
        "datacenter_land_commit_v1": {
            "type": "object",
            "properties": {
                "decision": {"enum": ["sign", "walk"]},
                "offer_id": {"type": "string"},
            },
            "required": ["decision", "offer_id"],
            "additionalProperties": False,
        },
    }


def _transformed_profile(
    profile: AgentProfile,
    *,
    developer: bool,
    family_case: dict[str, Any],
) -> AgentProfile:
    data = json.loads(canonical_json_bytes(profile))
    data["profile_id"] = f"{profile.profile_id}_affordance_v1"
    data["runtime"]["implementation"] = RUNTIME_ID
    if developer:
        data["prompt"] = {
            "prompt_id": DEVELOPER_PROMPT_ID,
            "sha256": hashlib.sha256(DEVELOPER_PROMPT.encode("utf-8")).hexdigest(),
        }
        if profile.model.provider == "openrouter":
            data["harness"]["config"]["output_schema_by_action_schema"] = (
                _developer_output_schemas(family_case)
            )
    return AgentProfile.from_dict(data)


def build_affordance_setup(
    condition: str,
    *,
    route: Any | None = None,
    seed: int | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
) -> DataCenterStackSetup:
    base = build_adoption_setup_v3(
        "land",
        route=route,
        seed=seed,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        max_cost_usd=max_cost_usd,
    )
    case = load_affordance_case(condition)
    plugin = CounterofferAffordancePlugin()
    family_case = plugin.validate_payload(case.payload)
    family = affordance_family_manifest()

    old_developer_id = base.plan.cells[0].profile_by_seat["developer"]
    transformed = {
        profile.profile_id: _transformed_profile(
            profile,
            developer=profile.profile_id == old_developer_id,
            family_case=family_case,
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
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"datacenter_counteroffer_affordance_{condition}_controlled_v1",
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
            "sampling_plan_id": f"datacenter_counteroffer_affordance_{condition}_sample_v1",
            "estimand": "counteroffer_adoption_rate",
            "target": case.provenance.generator_id,
            "selection": "fixed_paired_counteroffer_acceptance_affordance",
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
            "analysis_plan_id": f"datacenter_counteroffer_affordance_{condition}_analysis_v1",
            "estimands": [
                "counteroffer_adoption_rate",
                "prefix_completion",
                "exact_package_integrity",
                "counteroffer_opportunity_count",
                "negotiation_temporal_compliance",
                "intentional_resolution",
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
            "suite_id": f"datacenter_counteroffer_affordance_{condition}_v1",
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
            "run_spec_id": f"datacenter_counteroffer_affordance_{condition}_{assignments['developer']}",
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
        if pin.component_id not in {ADOPTION_V3_PLUGIN_ID, ADOPTION_V3_RUNTIME_ID}
    ]
    pins.extend(
        (
            _pin(
                PLUGIN_ID,
                "family_plugin",
                Path(__file__).with_name("affordance_environment.py"),
            ),
            _pin(RUNTIME_ID, "runtime", Path(__file__), version="0.1.0"),
        )
    )
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


class ScriptedAffordanceDeveloper:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "datacenter_adoption_scripted_developer":
            raise ProviderFailure(
                "provider_contract",
                "wrong affordance developer provider",
                retryable=False,
            )
        payload = json.loads(request.input_text)
        phase = payload["phase_id"]
        observation = payload["observation"]
        if phase.endswith("_commit"):
            return _scripted_result(
                request,
                {
                    "decision": "sign",
                    "offer_id": observation["accepted_offer_id"],
                },
            )
        if not phase.endswith("_offer"):
            raise ProviderFailure(
                "provider_contract", "wrong affordance phase", retryable=False
            )
        resolution = observation.get("counteroffer_resolution")
        if resolution is None:
            action = {
                "decision": "offer",
                "offer_id": None,
                "message": "Developer initial land proposal.",
                "terms": observation["starter_offer_terms"],
            }
        elif resolution["mode"] == "reemit_package":
            action = {
                "decision": "offer",
                "offer_id": None,
                "message": "Developer adopts the complete land counteroffer.",
                "terms": observation["pending_counter_terms"],
            }
        else:
            action = {
                "decision": "accept_counteroffer",
                "offer_id": observation["pending_counteroffer_offer_id"],
                "message": None,
                "terms": None,
            }
        return _scripted_result(request, action)


def _providers(setup: DataCenterStackSetup) -> dict[str, Any]:
    return {
        "datacenter_adoption_scripted_developer": ScriptedAffordanceDeveloper(),
        "datacenter_adoption_scripted_landowner": ForcedCounterpartyProvider(
            "landowner"
        ),
    }


async def run_affordance_offline(condition: str, *, evidence_root: Path | str):
    setup = build_affordance_setup(condition)
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


async def run_affordance_openrouter(
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
    setup = build_affordance_setup(
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


def finalize_affordance_execution(
    *, setup: DataCenterStackSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_affordance_failure(
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


def replay_affordance_receipt(
    *,
    setup: DataCenterStackSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


__all__ = [
    "CASE_PATH_BY_CONDITION",
    "CONDITIONS",
    "RUNTIME_ID",
    "build_affordance_setup",
    "finalize_affordance_execution",
    "finalize_affordance_failure",
    "load_affordance_case",
    "replay_affordance_receipt",
    "run_affordance_offline",
    "run_affordance_openrouter",
]
