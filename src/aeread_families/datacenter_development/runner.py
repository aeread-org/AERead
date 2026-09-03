"""Build and run the V0 data-center negotiation through AERead's shared runner."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.execution as execution_module
from aeread.shared_runner.execution import (
    CellExecution,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.family_evaluation import (
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.harness import default_harnesses
from aeread.shared_runner.receipts import EvaluationReceipt
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.resolver import (
    ImplementationPin,
    RunPlan,
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

from .environment import (
    LOAN_DEVELOPER_COMMIT,
    LOAN_DEVELOPER_OFFER,
    LOAN_LENDER_RESPONSE,
    PLUGIN_ID,
    SCORER_ID,
    SERVICE_CUSTOMER_RESPONSE,
    SERVICE_DEVELOPER_COMMIT,
    SERVICE_DEVELOPER_OFFER,
    DataCenterDevelopmentPlugin,
    family_manifest,
)
from .measurement import implementation_refs, primary_measurement_leaf


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_PATH = (
    REPOSITORY_ROOT
    / "cases"
    / "datacenter_development_v1"
    / "dev"
    / "service_loan_bankability_001.json"
)
RUNTIME_ID = "aeread_families.datacenter_development.runner"

DEVELOPER_PROMPT = """Negotiate the project service agreement and construction loan.
Return exactly one JSON action matching the current phase. Written terms, not prose,
control execution and future cash flow. Sign only an offer ID that was accepted."""
CUSTOMER_PROMPT = """Apply the private customer policy deterministically to the latest
written service offer. Return exactly one JSON accept, counter, or reject action."""
LENDER_PROMPT = """Apply the private lender credit policy deterministically to the
latest written loan offer and executed service agreement. Return exactly one JSON action."""


@dataclass(frozen=True, slots=True)
class DataCenterDevelopmentSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    case: CaseManifest
    harnesses: Mapping[str, Any]


def load_case(path: Path | str = CASE_PATH) -> CaseManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    case = CaseManifest.from_dict(raw)
    computed = case_content_sha256(case)
    if computed != case.content_sha256:
        raise ValueError(
            f"case content hash mismatch: declared {case.content_sha256}, computed {computed}"
        )
    return case


def _pin(
    component_id: str, kind: str, source_path: Path, *, version: str = "1.0.0"
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        }
    )


def _profile(
    *,
    profile_id: str,
    provider: str,
    model: str,
    prompt_id: str,
    prompt: str,
    pricing: TokenPricing,
    max_actions: int,
) -> AgentProfile:
    return AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": pricing.pricing_id,
                    "pricing_sha256": pricing.content_sha256(),
                },
            },
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
                "condition_id": "scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 1024,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": max_actions,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def build_offline_setup(
    *, case_path: Path | str = CASE_PATH
) -> DataCenterDevelopmentSetup:
    case = load_case(case_path)
    family = family_manifest()
    validated = DataCenterDevelopmentPlugin().validate_payload(case.payload)
    service_rounds = validated["negotiation"]["max_service_rounds"]
    loan_rounds = validated["negotiation"]["max_loan_rounds"]
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": "datacenter_development_dev_sample_v1",
            "estimand": "fixed_service_loan_bankability_case",
            "target": "curated_datacenter_case_v1",
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "datacenter_controlled_counterparties_v1",
            "kind": "controlled",
            "subject_seats": ["developer"],
            "controlled_profiles": {
                "customer": "datacenter_scripted_customer_v1",
                "lender": "datacenter_scripted_lender_v1",
            },
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "datacenter_development_analysis_v1",
            "estimands": [
                "developer_equity_npv",
                "binding_contract_integrity",
                "project_constraint_satisfaction",
                "negotiation_temporal_compliance",
                "total_project_npv",
            ],
            "group_by": ["family_id"],
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
            "suite_id": "datacenter_development_dev_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    developer_pricing = TokenPricing(0.0, 0.0, 0.0, "datacenter_developer_zero_cost_v1")
    customer_pricing = TokenPricing(0.0, 0.0, 0.0, "datacenter_customer_zero_cost_v1")
    lender_pricing = TokenPricing(0.0, 0.0, 0.0, "datacenter_lender_zero_cost_v1")
    developer = _profile(
        profile_id="datacenter_scripted_developer_v1",
        provider="datacenter_scripted_developer",
        model="datacenter_scripted_developer_v1",
        prompt_id="datacenter_developer_prompt_v1",
        prompt=DEVELOPER_PROMPT,
        pricing=developer_pricing,
        max_actions=service_rounds + loan_rounds + 2,
    )
    customer = _profile(
        profile_id="datacenter_scripted_customer_v1",
        provider="datacenter_scripted_customer",
        model="datacenter_scripted_customer_v1",
        prompt_id="datacenter_customer_prompt_v1",
        prompt=CUSTOMER_PROMPT,
        pricing=customer_pricing,
        max_actions=service_rounds,
    )
    lender = _profile(
        profile_id="datacenter_scripted_lender_v1",
        provider="datacenter_scripted_lender",
        model="datacenter_scripted_lender_v1",
        prompt_id="datacenter_lender_prompt_v1",
        prompt=LENDER_PROMPT,
        pricing=lender_pricing,
        max_actions=loan_rounds,
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": "datacenter_development_scripted_dev_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [
                developer.profile_id,
                customer.profile_id,
                lender.profile_id,
            ],
            "seat_assignments": {
                "developer": developer.profile_id,
                "customer": customer.profile_id,
                "lender": lender.profile_id,
            },
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, DataCenterDevelopmentPlugin())
    harness_registry = HarnessRegistry()
    harnesses = default_harnesses()
    for harness in harnesses.values():
        harness_registry.register(harness)
    environment_path = Path(__file__).with_name("environment.py")
    measurement_path = Path(__file__).with_name("measurement.py")
    runner_path = Path(__file__)
    execution_path = Path(execution_module.__file__)
    measurement_digest = hashlib.sha256(measurement_path.read_bytes()).hexdigest()
    pins = [
        _pin(PLUGIN_ID, "family_plugin", environment_path),
        _pin("minimal_chat", "harness", execution_path, version="1.0"),
        _pin(RUNTIME_ID, "runtime", runner_path, version="0.1.0"),
    ]
    for implementation in implementation_refs():
        pins.append(
            ImplementationPin.from_dict(
                {
                    "component_id": implementation.implementation_id,
                    "kind": "scorer" if implementation.implementation_id == SCORER_ID else "reference",
                    "version": implementation.version,
                    "sha256": measurement_digest,
                }
            )
        )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(developer, customer, lender),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities={
            provider: ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
            for provider in (
                "datacenter_scripted_developer",
                "datacenter_scripted_customer",
                "datacenter_scripted_lender",
            )
        },
    )
    return DataCenterDevelopmentSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            "datacenter_developer_prompt_v1": DEVELOPER_PROMPT,
            "datacenter_customer_prompt_v1": CUSTOMER_PROMPT,
            "datacenter_lender_prompt_v1": LENDER_PROMPT,
        },
        pricing={
            "datacenter_scripted_developer_v1": developer_pricing,
            "datacenter_scripted_customer_v1": customer_pricing,
            "datacenter_scripted_lender_v1": lender_pricing,
        },
        case=case,
        harnesses=harnesses,
    )


def _scripted_result(request: ProviderRequest, output: Mapping[str, Any]) -> ProviderResult:
    text = canonical_json_bytes(output).decode("utf-8")
    return ProviderResult(
        response_id=f"scripted_{request.provider_call_id}",
        requested_model=request.model,
        resolved_model=request.revision or request.model,
        output_text=text,
        finish_reason="stop",
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        raw_response={"fixture": True, "output_text": text},
    )


class ScriptedDeveloperProvider:
    def __init__(self, *, service_terms: Mapping[str, Any], loan_terms: Mapping[str, Any]) -> None:
        self._service_terms = dict(service_terms)
        self._loan_terms = dict(loan_terms)

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "datacenter_scripted_developer":
            raise ProviderFailure("provider_contract", "wrong developer provider", retryable=False)
        payload = json.loads(request.input_text)
        phase = payload["phase_id"]
        observation = payload["observation"]
        if phase == SERVICE_DEVELOPER_OFFER:
            terms = observation.get("pending_service_counter_terms") or self._service_terms
            output = {"decision": "offer", "message": "Written service proposal.", "terms": terms}
        elif phase == LOAN_DEVELOPER_OFFER:
            terms = observation.get("pending_loan_counter_terms") or self._loan_terms
            output = {"decision": "offer", "message": "Written construction-loan proposal.", "terms": terms}
        elif phase == SERVICE_DEVELOPER_COMMIT:
            output = {"decision": "sign", "offer_id": observation["service_accepted_offer_id"]}
        elif phase == LOAN_DEVELOPER_COMMIT:
            output = {"decision": "sign", "offer_id": observation["loan_accepted_offer_id"]}
        else:
            raise ProviderFailure("provider_contract", "developer received wrong phase", retryable=False)
        return _scripted_result(request, output)


class ScriptedCustomerProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "datacenter_scripted_customer":
            raise ProviderFailure("provider_contract", "wrong customer provider", retryable=False)
        payload = json.loads(request.input_text)
        if payload["phase_id"] != SERVICE_CUSTOMER_RESPONSE:
            raise ProviderFailure("provider_contract", "customer received wrong phase", retryable=False)
        observation = payload["observation"]
        offer = observation["latest_service_offer"]
        terms = offer["terms"]
        policy = observation["private_policy"]
        acceptable = (
            terms["committed_capacity_kw"] >= policy["minimum_capacity_kw"]
            and terms["monthly_capacity_charge_cents_per_kw"] <= policy["maximum_capacity_charge_cents_per_kw"]
            and terms["take_or_pay_bps"] <= policy["maximum_take_or_pay_bps"]
            and terms["credit_support_cents"] <= policy["maximum_credit_support_cents"]
            and terms["delay_damages_cents_per_month"] >= policy["minimum_delay_damages_cents_per_month"]
        )
        output = (
            {"decision": "accept", "offer_id": offer["offer_id"], "message": "Customer accepts the written terms.", "terms": None}
            if acceptable
            else {"decision": "counter", "offer_id": offer["offer_id"], "message": "Customer counterproposal.", "terms": policy["counter_terms"]}
        )
        return _scripted_result(request, output)


class ScriptedLenderProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "datacenter_scripted_lender":
            raise ProviderFailure("provider_contract", "wrong lender provider", retryable=False)
        payload = json.loads(request.input_text)
        if payload["phase_id"] != LOAN_LENDER_RESPONSE:
            raise ProviderFailure("provider_contract", "lender received wrong phase", retryable=False)
        observation = payload["observation"]
        offer = observation["latest_loan_offer"]
        terms = offer["terms"]
        service = observation["executed_service"]["terms"]
        policy = observation["private_policy"]
        acceptable = (
            terms["maximum_commitment_cents"] >= policy["minimum_commitment_cents"]
            and terms["advance_rate_bps"] <= policy["maximum_advance_rate_bps"]
            and terms["spread_bps"] >= policy["minimum_spread_bps"]
            and terms["minimum_dscr_bps"] >= policy["minimum_dscr_bps"]
            and terms["maximum_loan_to_cost_bps"] <= policy["maximum_loan_to_cost_bps"]
            and terms["maximum_loan_to_value_bps"] <= policy["maximum_loan_to_value_bps"]
            and terms["maturity_month"] <= policy["maximum_maturity_month"]
            and service["committed_capacity_kw"] >= terms["minimum_contracted_capacity_kw"]
            and service["take_or_pay_bps"] >= terms["minimum_take_or_pay_bps"]
            and service["credit_support_cents"] >= terms["minimum_customer_credit_support_cents"]
        )
        output = (
            {"decision": "accept", "offer_id": offer["offer_id"], "message": "Lender accepts the written credit terms.", "terms": None}
            if acceptable
            else {"decision": "counter", "offer_id": offer["offer_id"], "message": "Lender counterproposal.", "terms": policy["counter_terms"]}
        )
        return _scripted_result(request, output)


def _providers(setup: DataCenterDevelopmentSetup) -> Mapping[str, Any]:
    payload = setup.case.payload
    return {
        "datacenter_scripted_developer": ScriptedDeveloperProvider(
            service_terms=payload["scripted_developer"]["service_terms"],
            loan_terms=payload["scripted_developer"]["loan_terms"],
        ),
        "datacenter_scripted_customer": ScriptedCustomerProvider(),
        "datacenter_scripted_lender": ScriptedLenderProvider(),
    }


async def run_offline(
    *, evidence_root: Path | str, episode_attempt_ordinal: int = 0
) -> tuple[DataCenterDevelopmentSetup, CellExecution]:
    setup = build_offline_setup()
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=Path(evidence_root),
        prompt_sources=setup.prompt_sources,
        providers=_providers(setup),
        pricing=setup.pricing,
        episode_attempt_ordinal=episode_attempt_ordinal,
        harnesses=setup.harnesses,
    )
    return setup, execution


def finalize_datacenter_execution(
    *, setup: DataCenterDevelopmentSetup, execution: CellExecution
) -> EvaluationReceipt:
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_datacenter_failure(
    *,
    setup: DataCenterDevelopmentSetup,
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


def replay_datacenter_receipt(
    *,
    setup: DataCenterDevelopmentSetup,
    receipt: EvaluationReceipt,
    evidence_root: Path | str,
) -> EvaluationReceipt:
    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    setup, execution = await run_offline(
        evidence_root=arguments.run_root,
        episode_attempt_ordinal=arguments.attempt,
    )
    receipt = finalize_datacenter_execution(setup=setup, execution=execution)
    replayed = replay_datacenter_receipt(
        setup=setup, receipt=receipt, evidence_root=arguments.run_root
    )
    return {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "logical_action_count": execution.episode_result.logical_action_count,
        "total_cost_usd": execution.total_cost_usd,
        "measurement_status": receipt.status,
        "inclusion_status": receipt.inclusion_status,
        "primary_leaf_id": receipt.primary_leaf_id,
        "scores": {
            item.leaf.leaf_id: item.primary.value if item.primary is not None else None
            for item in receipt.scores
        },
        "receipt_sha256": receipt.receipt_sha256,
        "replay_matches": replayed == receipt,
        "receipt_path": str((execution.evidence.root / "evaluation_receipt.json").resolve()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("v0", "v1", "v2"), default="v0")
    parser.add_argument(
        "--run-root", "--output", dest="run_root", type=Path, required=True
    )
    parser.add_argument("--attempt", type=int, default=0)
    arguments = parser.parse_args(argv)
    if arguments.scope != "v0":
        from .stack_runner import main as stack_main

        return stack_main(
            [
                "--scope",
                arguments.scope,
                "--run-root",
                str(arguments.run_root),
                "--attempt",
                str(arguments.attempt),
            ]
        )
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


__all__ = [
    "CASE_PATH",
    "DataCenterDevelopmentSetup",
    "ScriptedCustomerProvider",
    "ScriptedDeveloperProvider",
    "ScriptedLenderProvider",
    "build_offline_setup",
    "finalize_datacenter_execution",
    "finalize_datacenter_failure",
    "load_case",
    "main",
    "replay_datacenter_receipt",
    "run_offline",
]
