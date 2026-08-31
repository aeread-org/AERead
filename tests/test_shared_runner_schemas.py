from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from aeread.shared_runner.registry import (
    DuplicatePluginError,
    IncompletePluginError,
    PluginRegistry,
    PluginResolutionError,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    AuthoringValidationError,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
    is_exportable_id,
    parse_authoring_record,
)


SHA256 = "a" * 64


@pytest.mark.parametrize(
    "value",
    [
        "housing_v1",
        "housing_v1__dev__000001",
        "tau3.retail.base",
        "supply-chain-order-0001",
        "a",
    ],
)
def test_shared_runner_identifiers_are_exportable(value: str) -> None:
    assert is_exportable_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "tau3:retail:0001",
        "Housing_V1",
        "supply chain",
        "_leading",
        "trailing-",
        "case/0001",
        "",
    ],
)
def test_shared_runner_rejects_nonportable_identifiers(value: str) -> None:
    assert not is_exportable_id(value)


def test_case_id_rejects_colon_before_rllm_can_truncate_it() -> None:
    data = case_data()
    data["case_id"] = "tau3:retail:0001"

    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(data)


def family_data() -> dict:
    return {
        "spec_version": "aeread.family/0.1",
        "family": {
            "id": "housing_v1",
            "version": "1.0.0",
            "plugin_id": "aeread.housing_v1",
        },
        "environment": {
            "topology": "market_with_private_preferences",
            "phase_specs": ["contact_v1", "respond_v1", "commit_v1"],
            "needs_tools": False,
            "needs_sandbox": False,
        },
        "roles": {
            "tenant": {"testable": True, "scripted_policies": []},
            "landlord": {
                "testable": False,
                "scripted_policies": ["fixed_landlord_v1"],
            },
        },
        "measurement": {
            "primary_estimand": "tenant_realized_utility",
            "measurement_kind": "optimizable_outcome",
            "direction": "maximize",
            "optimum_lower_bound": "housing_scripted_search_v1",
            "comparison_baseline": "housing_scripted_search_v1",
            "optimum_upper_bound": "housing_exact_assignment_v1",
            "optimum_upper_bound_kind": "full_information_relaxation",
            "bound_status": "bracketed",
            "outcome_support": "undeclared",
        },
        "scoring": {
            "scorer_id": "housing_outcome_v1",
            "oracle_id": "housing_exact_assignment_v1",
            "reference_provider_ids": ["housing_scripted_search_v1"],
        },
        "generator": {
            "generator_id": "housing_generator_v1",
            "difficulty_knobs": ["market_tightness", "information_friction"],
        },
    }


def case_data() -> dict:
    return {
        "spec_version": "aeread.case/0.1",
        "case_id": "housing_v1__dev__000001",
        "family_id": "housing_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": 41001,
        "seats": [
            {"id": "tenant_0", "role": "tenant"},
            {"id": "landlord_0", "role": "landlord"},
        ],
        "episode": {
            "max_logical_actions": 8,
            "termination": ["allocation", "withdrawal", "deadline", "forfeit"],
        },
        "visibility_policy": "housing_private_preferences_v1",
        "payload": {
            "listings": [{"listing_id": 0, "ask": 1800}],
            "private_values": {"tenant_0": [2100]},
        },
        "provenance": {
            "generator_id": "housing_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": SHA256,
    }


def sampling_data() -> dict:
    return {
        "spec_version": "aeread.sampling/0.1",
        "sampling_plan_id": "housing_sample_v1",
        "estimand": "generated_housing_case_population",
        "target": "housing_generator_v1",
        "selection": "seeded_generator",
        "seeds": [41001, 41002],
        "replicates": 5,
        "cluster_level": "world_seed",
        "cluster_id_fields": ["generator_version", "world_seed"],
        "paired_fields": ["world_seed", "subject_profile"],
        "replicate_level": "episode_attempt",
        "panel_mode": "sampled_panel",
    }


def block_data() -> dict:
    return {
        "spec_version": "aeread.evaluation_block/0.1",
        "block_id": "controlled_fixed_counterpart",
        "kind": "controlled",
        "subject_seats": ["tenant_0"],
        "controlled_profiles": {"landlord_0": "fixed_landlord_v1"},
        "repetitions": 5,
        "seed_policy": "paired",
    }


def analysis_data() -> dict:
    return {
        "spec_version": "aeread.analysis/0.1",
        "analysis_plan_id": "housing_primary_v1",
        "estimands": ["tenant_realized_utility", "social_welfare"],
        "group_by": ["family_id", "primary_metric", "subject_role"],
        "missingness": "report_separately",
        "resampling_unit": "cluster_id",
        "uncertainty": "cluster_bootstrap_95",
        "multiplicity": "report_unadjusted",
        "sensitivity": ["exclude_invalid_measurements"],
        "cross_family_scalar": "disabled",
    }


def suite_data() -> dict:
    return {
        "spec_version": "aeread.suite/0.1",
        "suite_id": "housing_dev_v1",
        "version": "1.0.0",
        "family_ids": ["housing_v1"],
        "case_ids": ["housing_v1__dev__000001"],
        "sampling_plan_id": "housing_sample_v1",
        "evaluation_block_ids": ["controlled_fixed_counterpart"],
        "analysis_plan_id": "housing_primary_v1",
    }


def agent_data() -> dict:
    return {
        "spec_version": "aeread.agent_profile/0.1",
        "profile_id": "gpt5_minimal_medium_v1",
        "model": {
            "provider": "openai",
            "model": "gpt-5",
            "revision": "2026-08-01",
        },
        "harness": {
            "id": "minimal_chat",
            "version": "1.0",
            "config": {},
        },
        "prompt": {"prompt_id": "housing_tenant_v1", "sha256": SHA256},
        "runtime": {
            "kind": "python",
            "implementation": "aeread.gateway_candidate",
            "version": "1.0.0",
        },
        "tools": [],
        "memory": {"mode": "disabled"},
        "reasoning": {
            "condition_id": "medium_hidden_v1",
            "effort": "medium",
            "token_budget": None,
            "rationale_visibility": "hidden",
        },
        "sampling": {
            "temperature": 0.0,
            "max_output_tokens": 1200,
            "seed": 7,
        },
        "budgets": {
            "max_logical_actions": 8,
            "timeout_seconds": 60.0,
            "max_cost_usd": 1.0,
        },
        "retry_policy": {
            "max_action_attempts": 2,
            "retryable_conditions": ["empty_finish_reason_length"],
            "session_mode": "continue",
            "sdk_retries": 0,
        },
    }


def run_data() -> dict:
    return {
        "spec_version": "aeread.run_spec/0.1",
        "run_spec_id": "housing_gpt5_dev_v1",
        "suite_id": "housing_dev_v1",
        "evaluation_block_ids": ["controlled_fixed_counterpart"],
        "agent_profile_ids": ["gpt5_minimal_medium_v1", "fixed_landlord_v1"],
        "seat_assignments": {
            "tenant_0": "gpt5_minimal_medium_v1",
            "landlord_0": "fixed_landlord_v1",
        },
        "execution_mode": "evaluate",
        "replicate_override": None,
        "budget_overrides": {"max_cost_usd": 20.0},
    }


RECORD_FIXTURES = [
    (family_data, FamilyManifest),
    (case_data, CaseManifest),
    (suite_data, SuiteManifest),
    (sampling_data, SamplingPlan),
    (block_data, EvaluationBlock),
    (analysis_data, AnalysisPlan),
    (agent_data, AgentProfile),
    (run_data, RunSpec),
]


@pytest.mark.parametrize(("factory", "record_type"), RECORD_FIXTURES)
def test_parse_all_r1_authoring_records(factory, record_type) -> None:
    record = parse_authoring_record(factory())
    assert isinstance(record, record_type)


@pytest.mark.parametrize(("factory", "record_type"), RECORD_FIXTURES)
def test_every_r1_record_rejects_unknown_top_level_fields(factory, record_type) -> None:
    data = factory()
    data["unexpected"] = "must fail before any runner side effect"
    with pytest.raises(AuthoringValidationError, match="unexpected"):
        record_type.from_dict(data)


def test_nested_shared_records_are_strict_but_family_payload_is_opaque() -> None:
    data = family_data()
    data["roles"]["tenant"]["unknown_role_setting"] = True
    with pytest.raises(AuthoringValidationError, match="unknown_role_setting"):
        FamilyManifest.from_dict(data)

    case = CaseManifest.from_dict(case_data())
    assert case.payload["listings"][0]["ask"] == 1800
    with pytest.raises(TypeError):
        case.payload["listings"] = []


def test_case_world_and_experiment_assignment_remain_separate() -> None:
    data = case_data()
    data["model"] = "gpt-5"
    with pytest.raises(AuthoringValidationError, match="model"):
        CaseManifest.from_dict(data)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.update(world_seed=True), "world_seed"),
        (lambda data: data.update(content_sha256="not-a-digest"), "content_sha256"),
        (lambda data: data["seats"].append({"id": "tenant_0", "role": "tenant"}), "duplicate"),
    ],
)
def test_case_manifest_rejects_ambiguous_identity(mutator, message) -> None:
    data = case_data()
    mutator(data)
    with pytest.raises(AuthoringValidationError, match=message):
        CaseManifest.from_dict(data)


def test_agent_profile_rejects_hidden_sdk_retries_and_unknown_retry_fields() -> None:
    data = agent_data()
    data["retry_policy"]["sdk_retries"] = 1
    with pytest.raises(AuthoringValidationError, match="sdk_retries"):
        AgentProfile.from_dict(data)

    data = agent_data()
    data["retry_policy"]["provider_magic_retry"] = True
    with pytest.raises(AuthoringValidationError, match="provider_magic_retry"):
        AgentProfile.from_dict(data)


def test_authoring_records_are_frozen() -> None:
    family = FamilyManifest.from_dict(family_data())
    with pytest.raises(FrozenInstanceError):
        family.spec_version = "changed"
    with pytest.raises(TypeError):
        family.roles["new_role"] = family.roles["tenant"]


def test_partial_run_budget_overrides_preserve_unset_fields() -> None:
    run = RunSpec.from_dict(run_data())
    assert run.budget_overrides is not None
    assert run.budget_overrides.max_cost_usd == 20.0
    assert run.budget_overrides.max_logical_actions is None
    assert run.budget_overrides.timeout_seconds is None


class CompleteHousingPlugin:
    def validate_payload(self, payload):
        return payload

    def initial_state(self, case, run):
        return {}

    def phases(self, case):
        return ()

    def eligible_actors(self, case, state, phase):
        return ()

    def observe(self, case, state, seat, phase):
        return {}

    def parse_action(self, case, state, seat, phase, response):
        return response

    def legal(self, case, state, seat, phase, action):
        return True

    def step(self, case, state, phase, actions):
        return state

    def terminal(self, case, state):
        return None

    def outcome(self, case, terminal):
        return terminal

    def build_scorer(self, case):
        return object()

    def build_reference_providers(self, case):
        return ()

    def generator(self):
        return None


def test_registry_resolves_only_exact_trusted_family_version_and_plugin() -> None:
    manifest = FamilyManifest.from_dict(family_data())
    plugin = CompleteHousingPlugin()
    registry = PluginRegistry()
    registry.register(manifest, plugin)

    assert registry.resolve("housing_v1", "1.0.0", "aeread.housing_v1") is plugin
    assert registry.resolve_manifest(manifest) is plugin

    with pytest.raises(PluginResolutionError, match="not registered"):
        registry.resolve("housing_v1", "2.0.0", "aeread.housing_v1")
    with pytest.raises(PluginResolutionError, match="plugin_id"):
        registry.resolve("housing_v1", "1.0.0", "aeread.other")


def test_registry_rejects_duplicate_or_incomplete_plugins() -> None:
    manifest = FamilyManifest.from_dict(family_data())
    registry = PluginRegistry()
    registry.register(manifest, CompleteHousingPlugin())
    with pytest.raises(DuplicatePluginError, match="already registered"):
        registry.register(manifest, CompleteHousingPlugin())

    incomplete = object()
    with pytest.raises(IncompletePluginError, match="validate_payload"):
        PluginRegistry().register(manifest, incomplete)
