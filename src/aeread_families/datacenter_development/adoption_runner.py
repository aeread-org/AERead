"""Runnable staged counteroffer-adoption diagnostic for data-center terms."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
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
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.task.receipts import EvaluationReceipt

from .adoption_environment import (
    FAMILY_ID,
    PLUGIN_ID,
    SCORER_ID,
    STAGE_SEQUENCES,
    CounterofferAdoptionPlugin,
    adoption_family_manifest,
)
from .adoption_measurement import implementation_refs, primary_measurement_leaf
from .objective_openrouter import ParameterCompatibleOpenRouterClient
from .stack_environment import COUNTERPART_BY_KEY
from .stack_runner import (
    DataCenterStackSetup,
    _scripted_result,
    _strict_schema_from_example,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID / "v1"
CASE_PATH_BY_STAGE = {
    stage_id: CASE_ROOT / f"{stage_id}_001.json"
    for stage_id in STAGE_SEQUENCES
}
RUNTIME_ID = "aeread_families.datacenter_development.adoption_runner"
DEVELOPER_PROMPT_ID = "datacenter_counteroffer_adoption_developer_prompt_v1"
COUNTERPART_PROMPT_ID = "datacenter_counteroffer_adoption_counterparty_prompt_v1"
DEVELOPER_PROMPT = """You are the developer in a staged data-center negotiation.
This diagnostic tests whether you can adopt written counteroffers exactly; it does
not score project NPV. Each controlled counterparty will return a complete written
counteroffer after your first proposal. In the next offer, copy every structured
counteroffer term exactly, without compromise or omission. After acceptance, copy
accepted_offer_id exactly into offer_id and sign. Return exactly one JSON action for
the current phase. You may walk, but walking receives no adoption credit. Never
invent an offer ID; prose does not amend structured terms."""
COUNTERPART_PROMPT = """Return the calibrated complete written counteroffer after
the developer's first offer. On the next round, accept only if every structured term
equals that package exactly; otherwise counter with the same complete package.
Always copy latest_offer.offer_id exactly. Return exactly one JSON action."""
FIRST_OFFER_PERTURB_FIELD = {
    "land": "purchase_price_cents",
    "power": "monthly_demand_charge_cents_per_kw",
    "epc": "delay_liquidated_damages_cents_per_month",
}


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


def load_adoption_case(stage_id: str) -> CaseManifest:
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


def _developer_output_schemas(family_case: Mapping[str, Any]) -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    for key in family_case["adoption_stage"]["required_sequence"]:
        terms = family_case["policies"][key]["counter_terms"]
        term_schema = _strict_schema_from_example(terms)
        schemas[f"datacenter_{key}_offer_v1"] = {
            "type": "object",
            "properties": {
                "decision": {"enum": ["offer", "walk"]},
                "message": {"type": ["string", "null"]},
                "terms": {"anyOf": [term_schema, {"type": "null"}]},
            },
            "required": ["decision", "message", "terms"],
            "additionalProperties": False,
        }
        schemas[f"datacenter_{key}_commit_v1"] = {
            "type": "object",
            "properties": {
                "decision": {"enum": ["sign", "walk"]},
                "offer_id": {"type": "string"},
            },
            "required": ["decision", "offer_id"],
            "additionalProperties": False,
        }
    return schemas


def _profile(
    *,
    profile_id: str,
    provider: str,
    model: str,
    revision: str,
    prompt_id: str,
    prompt: str,
    pricing: TokenPricing,
    max_actions: int,
    timeout_seconds: float,
    max_cost_usd: float,
    max_output_tokens: int,
    seed: int | None,
    reasoning_effort: str | None,
    base_url: str | None,
    harness_config: Mapping[str, Any] | None = None,
) -> AgentProfile:
    config = {
        "pricing_id": pricing.pricing_id,
        "pricing_sha256": pricing.content_sha256(),
        **dict(harness_config or {}),
    }
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": revision,
                "base_url": base_url,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": config},
            "prompt": {
                "prompt_id": prompt_id,
                "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": (
                    f"reasoning_{reasoning_effort}_v1"
                    if reasoning_effort is not None
                    else "reasoning_none_v1"
                ),
                "effort": reasoning_effort,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": max_output_tokens,
                "seed": seed,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": max_actions,
                "timeout_seconds": timeout_seconds,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


class AdoptionScriptedDeveloperProvider:
    """Offer once, then copy the visible counter package exactly and sign."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "datacenter_adoption_scripted_developer":
            raise ProviderFailure(
                "provider_contract", "wrong adoption developer provider", retryable=False
            )
        payload = json.loads(request.input_text)
        phase = payload["phase_id"]
        observation = payload["observation"]
        key = observation["agreement_key"]
        if phase.endswith("_offer"):
            pending = observation.get("pending_counter_terms")
            if pending is not None:
                terms = pending
            else:
                terms = json.loads(
                    canonical_json_bytes(
                        observation["counteroffer_adoption_task"]
                    ).decode("utf-8")
                )
                del terms
                # The public observation intentionally hides private policy. The
                # provider-free fixture receives its first package at construction.
                raise ProviderFailure(
                    "provider_contract",
                    "scripted developer requires stage terms",
                    retryable=False,
                )
            output = {
                "decision": "offer",
                "message": f"Developer adopts the complete {key} counteroffer.",
                "terms": terms,
            }
        elif phase.endswith("_commit"):
            output = {
                "decision": "sign",
                "offer_id": observation["accepted_offer_id"],
            }
        else:
            raise ProviderFailure(
                "provider_contract", "developer received wrong phase", retryable=False
            )
        return _scripted_result(request, output)


class ConfiguredAdoptionScriptedDeveloperProvider(AdoptionScriptedDeveloperProvider):
    def __init__(self, first_terms_by_key: Mapping[str, Mapping[str, Any]]) -> None:
        self._first_terms_by_key = {
            str(key): dict(value) for key, value in first_terms_by_key.items()
        }

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        payload = json.loads(request.input_text)
        phase = payload["phase_id"]
        observation = payload["observation"]
        if phase.endswith("_offer") and observation.get("pending_counter_terms") is None:
            key = observation["agreement_key"]
            terms = json.loads(
                canonical_json_bytes(self._first_terms_by_key[key]).decode("utf-8")
            )
            field = FIRST_OFFER_PERTURB_FIELD[key]
            terms[field] = int(terms[field]) - 1
            return _scripted_result(
                request,
                {
                    "decision": "offer",
                    "message": f"Developer initial {key} proposal.",
                    "terms": terms,
                },
            )
        return await super().complete(request)


class ForcedCounterpartyProvider:
    """Guarantee one written counter opportunity, then require exact adoption."""

    def __init__(self, seat_id: str) -> None:
        self._seat_id = seat_id

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        expected = f"datacenter_adoption_scripted_{self._seat_id}"
        if request.provider != expected:
            raise ProviderFailure(
                "provider_contract", "wrong adoption counterparty provider", retryable=False
            )
        payload = json.loads(request.input_text)
        if not payload["phase_id"].endswith("_response"):
            raise ProviderFailure(
                "provider_contract", "counterparty received wrong phase", retryable=False
            )
        observation = payload["observation"]
        offer = observation["latest_offer"]
        target = observation["private_policy"]["counter_terms"]
        exact = canonical_json_bytes(offer["terms"]) == canonical_json_bytes(target)
        if offer["round_index"] > 0 and exact:
            output = {
                "decision": "accept",
                "offer_id": offer["offer_id"],
                "message": f"{self._seat_id} accepts the exact counter package.",
                "terms": None,
            }
        else:
            output = {
                "decision": "counter",
                "offer_id": offer["offer_id"],
                "message": f"{self._seat_id} returns its complete written package.",
                "terms": target,
            }
        return _scripted_result(request, output)


def build_adoption_setup(
    stage_id: str,
    *,
    route: Any | None = None,
    seed: int | None = None,
    max_output_tokens: int = 1600,
    timeout_seconds: float = 180.0,
    max_cost_usd: float = 0.03,
) -> DataCenterStackSetup:
    if route is None and seed is not None:
        raise ValueError("offline adoption setup does not accept an inference seed")
    if route is not None and (seed is None or seed < 0):
        raise ValueError("live adoption setup requires a non-negative seed")
    case = load_adoption_case(stage_id)
    plugin = CounterofferAdoptionPlugin()
    family_case = plugin.validate_payload(case.payload)
    sequence = tuple(family_case["adoption_stage"]["required_sequence"])
    family = adoption_family_manifest()
    seats = tuple(sorted({COUNTERPART_BY_KEY[key] for key in sequence}))

    pricing: dict[str, TokenPricing] = {}
    profiles: list[AgentProfile] = []
    if route is None:
        developer_model = f"datacenter_adoption_{stage_id}_scripted_developer_v1"
        developer_pricing = TokenPricing(0, 0, 0, f"{developer_model}_zero_cost")
        developer_profile = _profile(
            profile_id=developer_model,
            provider="datacenter_adoption_scripted_developer",
            model=developer_model,
            revision="1.0.0",
            prompt_id=DEVELOPER_PROMPT_ID,
            prompt=DEVELOPER_PROMPT,
            pricing=developer_pricing,
            max_actions=3 * len(sequence),
            timeout_seconds=30,
            max_cost_usd=0,
            max_output_tokens=max_output_tokens,
            seed=None,
            reasoning_effort=None,
            base_url=None,
        )
        pricing[developer_model] = developer_pricing
    else:
        developer_profile = _profile(
            profile_id=f"{route.profile_id}_adoption_{stage_id}_v1",
            provider="openrouter",
            model=route.model,
            revision=route.revision,
            prompt_id=DEVELOPER_PROMPT_ID,
            prompt=DEVELOPER_PROMPT,
            pricing=route.pricing,
            max_actions=3 * len(sequence),
            timeout_seconds=timeout_seconds,
            max_cost_usd=max_cost_usd,
            max_output_tokens=max_output_tokens,
            seed=seed,
            reasoning_effort=route.reasoning_effort,
            base_url="https://openrouter.ai/api/v1",
            harness_config={
                "output_schema_by_action_schema": _developer_output_schemas(
                    family_case
                ),
                "provider_metadata": {
                    "route_provider": route.route_provider,
                    "quantization": route.quantization,
                    "canonical_model": route.revision,
                    "max_prompt_price_per_million": route.max_prompt_price_per_million,
                    "max_completion_price_per_million": route.max_completion_price_per_million,
                },
                **(
                    {"sampling_controls": {"temperature": "unavailable"}}
                    if not route.temperature_supported
                    else {}
                ),
            },
        )
        pricing[route.model] = route.pricing
    profiles.append(developer_profile)

    controlled_profiles: dict[str, str] = {}
    for seat in seats:
        model = f"datacenter_adoption_{stage_id}_scripted_{seat}_v1"
        seat_pricing = TokenPricing(0, 0, 0, f"{model}_zero_cost")
        profile = _profile(
            profile_id=model,
            provider=f"datacenter_adoption_scripted_{seat}",
            model=model,
            revision="1.0.0",
            prompt_id=COUNTERPART_PROMPT_ID,
            prompt=COUNTERPART_PROMPT,
            pricing=seat_pricing,
            max_actions=2 * sum(COUNTERPART_BY_KEY[key] == seat for key in sequence),
            timeout_seconds=30,
            max_cost_usd=0,
            max_output_tokens=max_output_tokens,
            seed=None,
            reasoning_effort=None,
            base_url=None,
        )
        profiles.append(profile)
        pricing[model] = seat_pricing
        controlled_profiles[seat] = model

    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": f"datacenter_adoption_{stage_id}_controlled_v1",
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
            "sampling_plan_id": f"datacenter_adoption_{stage_id}_sample_v1",
            "estimand": "counteroffer_adoption_rate",
            "target": case.provenance.generator_id,
            "selection": "fixed_nested_prefix_diagnostic",
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
            "analysis_plan_id": f"datacenter_adoption_{stage_id}_analysis_v1",
            "estimands": [
                "counteroffer_adoption_rate",
                "prefix_completion",
                "exact_package_integrity",
                "executed_agreement_count",
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
            "suite_id": f"datacenter_counteroffer_adoption_{stage_id}_v1",
            "version": "1.0.0",
            "family_ids": [FAMILY_ID],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    assignments = {"developer": developer_profile.profile_id, **controlled_profiles}
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": (
                f"datacenter_adoption_{stage_id}_offline_v1"
                if route is None
                else f"datacenter_adoption_{stage_id}_{developer_profile.profile_id}"
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
    harnesses = default_harnesses()
    harness_registry = HarnessRegistry()
    for harness in harnesses.values():
        harness_registry.register(harness)

    source_root = Path(__file__).parent
    pins = [
        _pin(PLUGIN_ID, "family_plugin", source_root / "adoption_environment.py"),
        _pin("minimal_chat", "harness", Path(execution_module.__file__), version="1.0"),
        _pin(RUNTIME_ID, "runtime", Path(__file__), version="0.1.0"),
    ]
    for implementation in implementation_refs():
        pins.append(
            _pin(
                implementation.implementation_id,
                "scorer" if implementation.implementation_id == SCORER_ID else "reference",
                source_root / "adoption_measurement.py",
                version=implementation.version,
            )
        )
    capabilities = {
        profile.model.provider: ProviderCapabilities(
            native_tools=False,
            structured_output=profile.model.provider == "openrouter",
            seed=profile.model.provider == "openrouter",
            system_prompt=True,
            reasoning_budget=(
                profile.model.provider == "openrouter"
                and profile.reasoning.effort is not None
            ),
            reasoning_token_report=profile.model.provider == "openrouter",
            max_context_tokens=None,
        )
        for profile in profiles
    }
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=tuple(profiles),
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
            DEVELOPER_PROMPT_ID: DEVELOPER_PROMPT,
            COUNTERPART_PROMPT_ID: COUNTERPART_PROMPT,
        },
        pricing=pricing,
        case=case,
        harnesses=harnesses,
        scope_version=stage_id,
    )


def _providers(setup: DataCenterStackSetup) -> dict[str, Any]:
    family_case = CounterofferAdoptionPlugin().validate_payload(setup.case.payload)
    sequence = family_case["adoption_stage"]["required_sequence"]
    return {
        "datacenter_adoption_scripted_developer": (
            ConfiguredAdoptionScriptedDeveloperProvider(
                {
                    key: family_case["policies"][key]["counter_terms"]
                    for key in sequence
                }
            )
        ),
        **{
            f"datacenter_adoption_scripted_{seat}": ForcedCounterpartyProvider(seat)
            for seat in sorted({COUNTERPART_BY_KEY[key] for key in sequence})
        },
    }


async def run_adoption_offline(
    stage_id: str, *, evidence_root: Path | str
) -> tuple[DataCenterStackSetup, CellExecution]:
    setup = build_adoption_setup(stage_id)
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


async def run_adoption_openrouter(
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
    setup = build_adoption_setup(
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


def finalize_adoption_execution(
    *, setup: DataCenterStackSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_adoption_failure(
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


def replay_adoption_receipt(
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
    "DEVELOPER_PROMPT",
    "ForcedCounterpartyProvider",
    "RUNTIME_ID",
    "build_adoption_setup",
    "finalize_adoption_execution",
    "finalize_adoption_failure",
    "load_adoption_case",
    "replay_adoption_receipt",
    "run_adoption_offline",
    "run_adoption_openrouter",
]
