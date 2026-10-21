"""The kernel plan for one pay or test version 3 world: ``runner.build_offline_setup`` with version 3's plugin.

``runner.py`` is hashed into sealed procurement plans and registers version 1's plugin, so version 3 builds its plan
here instead. Everything is the same except the family identity (``procurement_allocation_v1`` 1.1.0, plugin
``procurement_pay_or_test_v3_environment``), the action schema (``pay_or_test_v3_environment.action_output_schema``)
and the pins: the plugin, its scorer and the full-information oracle are pinned to one digest over this family's two
environment modules (``pay_or_test_v3_environment.source_digest``), so a change to either moves the plan.

The plan resolves only once the kernel trusts the version 3 plugin (``registry.TRUSTED_BUILTIN_PLUGIN_KEYS``, a
kernel-lane change); until then ``build_offline_setup`` raises the registry's own refusal.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import ImplementationPin, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, EvaluationBlock, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_failure
from aeread.shared_runner.task.execution import TokenPricing

from . import runner as v1_runner
from .pay_or_test_v3_environment import (
    PLUGIN_ID, SCORER_ID, PayOrTestV3Plugin, action_output_schema, family_manifest, measurement_leaf, source_digest,
)

ORACLE_ID = "procurement_full_information_upper_bound_v1"


def _digest_pin(component_id: str, kind: str, digest: str, *, version: str = "1.0.0") -> ImplementationPin:
    return ImplementationPin.from_dict({"component_id": component_id, "kind": kind, "version": version, "sha256": digest})


def build_offline_setup(*, case_path: Path | str, prompt: str, prompt_id: str) -> v1_runner.ProcurementAllocationSetup:
    if not prompt.strip() or not prompt_id.strip():
        raise ValueError("prompt and prompt_id cannot be empty")
    case = v1_runner.load_case(case_path)
    family = family_manifest()
    sampling = SamplingPlan.from_dict({
        "spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": "procurement_pay_or_test_v3_sample_v1",
        "estimand": "fixed_interactive_procurement_case", "target": "pay_or_test_option_value",
        "selection": "fixed_curated", "seeds": [1], "replicates": 1, "cluster_level": "procurement_world",
        "cluster_id_fields": ["generator_version", "world_seed"], "paired_fields": [],
        "replicate_level": "episode_attempt", "panel_mode": "fixed_panel",
    })
    block = EvaluationBlock.from_dict({
        "spec_version": EvaluationBlock.SPEC_VERSION, "block_id": "procurement_pay_or_test_v3_block", "kind": "self_play",
        "subject_seats": ["buyer"], "controlled_profiles": {}, "repetitions": 1, "seed_policy": "fixed",
    })
    analysis = AnalysisPlan.from_dict({
        "spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "procurement_pay_or_test_v3_analysis_v1",
        "estimands": ["buyer_contribution_margin"], "group_by": ["family_id"], "missingness": "report_separately",
        "resampling_unit": "procurement_world", "uncertainty": "none", "multiplicity": "none", "sensitivity": [],
        "cross_family_scalar": "disabled",
    })
    suite = SuiteManifest.from_dict({
        "spec_version": SuiteManifest.SPEC_VERSION, "suite_id": "procurement_pay_or_test_v3_v1", "version": "1.0.0",
        "family_ids": [family.family.id], "case_ids": [case.case_id], "sampling_plan_id": sampling.sampling_plan_id,
        "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id,
    })
    zero_pricing = TokenPricing(0.0, 0.0, 0.0, "fixed_response_zero_cost_v1")
    profile = AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION, "profile_id": "procurement_pay_or_test_v3_buyer_fixture_v1",
        "model": {"provider": "fake", "model": "fake-model", "revision": "fixed-v1", "base_url": None},
        "harness": {"id": "minimal_chat", "version": "1.0", "config": {
            "pricing_id": zero_pricing.pricing_id, "pricing_sha256": zero_pricing.content_sha256(),
            "output_schema": action_output_schema()}},
        "prompt": {"prompt_id": prompt_id, "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()},
        "runtime": {"kind": "python", "implementation": "aeread.shared_runner.task.execution", "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"},
        "reasoning": {"condition_id": "reasoning_unspecified_v1", "effort": None, "token_budget": None,
                      "rationale_visibility": "hidden"},
        "sampling": {"temperature": 0.0, "max_output_tokens": 1800, "seed": None, "top_p": None},
        "budgets": {"max_logical_actions": 10, "timeout_seconds": 60.0, "max_cost_usd": 0.0},
        "retry_policy": {"max_action_attempts": 1, "retryable_conditions": [], "session_mode": "restart", "sdk_retries": 0},
    })
    run_spec = RunSpec.from_dict({
        "spec_version": RunSpec.SPEC_VERSION, "run_spec_id": "procurement_pay_or_test_v3_dev_run_v1",
        "suite_id": suite.suite_id, "evaluation_block_ids": [block.block_id], "agent_profile_ids": [profile.profile_id],
        "seat_assignments": {"buyer": profile.profile_id}, "execution_mode": "evaluate", "replicate_override": None,
        "budget_overrides": None,
    })
    registry = PluginRegistry()
    registry.register_trusted(family, PayOrTestV3Plugin())
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    digest = source_digest()
    execution_path = Path(execution_module.__file__)
    pins = (
        _digest_pin(PLUGIN_ID, "family_plugin", digest),
        _digest_pin(SCORER_ID, "scorer", digest),
        _digest_pin(ORACLE_ID, "reference", digest),
        v1_runner._pin("minimal_chat", "harness", execution_path, version="1.0"),
        v1_runner._pin("aeread.shared_runner.task.execution", "runtime", execution_path, version="0.1.0"),
    )
    plan = resolve_run_plan(
        families=(family,), cases=(case,), suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis,
        agent_profiles=(profile,), run_spec=run_spec, registry=registry, implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={"fake": ProviderCapabilities(
            native_tools=False, structured_output=False, seed=False, system_prompt=True, reasoning_budget=False,
            reasoning_token_report=False, max_context_tokens=None)},
    )
    return v1_runner.ProcurementAllocationSetup(
        plan=plan, registry=registry, prompt_sources={prompt_id: prompt}, pricing={"fake-model": zero_pricing},
        case=case, harnesses=default_harnesses(),
    )


def finalize_failure(*, setup, cell_id: str, evidence_root, error: BaseException):
    """``runner.finalize_procurement_allocation_failure`` with version 3's leaf."""
    return finalize_family_failure(setup=setup, cell_id=cell_id, evidence_root=evidence_root, error=error,
                                   leaf_builder=measurement_leaf)


__all__ = ["ORACLE_ID", "build_offline_setup", "finalize_failure"]
