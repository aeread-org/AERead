from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from aeread.shared_runner.registry import (
    DuplicatePluginError,
    HarnessRegistry,
    HarnessRegistryError,
    HarnessRequirements,
    IncompletePluginError,
    PluginRegistry,
    PluginResolutionError,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    AuthoringValidationError,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    LeafPolicyDeclaration,
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


def test_upstream_task_id_rejects_colon_before_rllm_can_collapse_grouping() -> None:
    data = case_data()
    data["upstream_task_id"] = "retail:14"

    with pytest.raises(AuthoringValidationError, match="portable upstream identifier"):
        CaseManifest.from_dict(data)


@pytest.mark.parametrize(
    "value",
    ["Task 14", "retail:14", "a/b", "", "task\t1", "quote'd"],
)
def test_upstream_task_id_rejects_row_id_hazards(value: str) -> None:
    data = case_data()
    data["upstream_task_id"] = value

    with pytest.raises(AuthoringValidationError, match="upstream_task_id"):
        CaseManifest.from_dict(data)


@pytest.mark.parametrize(
    "value",
    [
        # Real foreign ids from the landed external families: the field exists
        # to record the upstream id VERBATIM, so case and underscores survive.
        "Task1BasicPriceNegotiation",
        "Task4_s1_beauty_product_negotiation",
        "tau2_retail.14",
        "14",
        "GovSim-fishing_v6.4",
    ],
)
def test_upstream_task_id_preserves_a_safe_foreign_id_verbatim(value: str) -> None:
    data = case_data()
    data["upstream_task_id"] = value

    assert CaseManifest.from_dict(data).upstream_task_id == value


def test_upstream_task_id_stays_optional() -> None:
    data = case_data()
    data.pop("upstream_task_id", None)

    assert CaseManifest.from_dict(data).upstream_task_id is None


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
    registry.register_trusted(manifest, plugin)

    assert registry.resolve("housing_v1", "1.0.0", "aeread.housing_v1") is plugin
    assert registry.resolve_manifest(manifest) is plugin

    with pytest.raises(PluginResolutionError, match="not registered"):
        registry.resolve("housing_v1", "2.0.0", "aeread.housing_v1")
    with pytest.raises(PluginResolutionError, match="plugin_id"):
        registry.resolve("housing_v1", "1.0.0", "aeread.other")


def test_registry_rejects_duplicate_or_incomplete_plugins() -> None:
    manifest = FamilyManifest.from_dict(family_data())
    registry = PluginRegistry()
    registry.register_trusted(manifest, CompleteHousingPlugin())
    with pytest.raises(DuplicatePluginError, match="already registered"):
        registry.register_trusted(manifest, CompleteHousingPlugin())

    incomplete = object()
    with pytest.raises(IncompletePluginError, match="validate_payload"):
        PluginRegistry().register_trusted(manifest, incomplete)


def _harness_requirements(memory: frozenset[str]) -> HarnessRequirements:
    return HarnessRequirements(
        provider=frozenset({"structured_output"}),
        tools="none",
        memory=memory,
        owns_retries=False,
        owns_tools=False,
        replayable=True,
        blocking=False,
        spawns_subagents=False,
    )


class _ProtocolCompleteHarness:
    id = "fixture_chat"
    version = "1.0"
    requires = _harness_requirements(frozenset({"disabled"}))

    async def open_episode(self, episode):
        return None

    async def act(self, request, ctx):
        raise NotImplementedError

    async def close_episode(self, episode):
        return None

    def classify_failure(self, exc):
        raise NotImplementedError

    def state_reader(self):
        return None


def test_harness_registry_rejects_a_protocol_incomplete_harness() -> None:
    class MissingHooks:
        id = "fixture_chat"
        version = "1.0"
        requires = _harness_requirements(frozenset({"disabled"}))

        async def act(self, request, ctx):
            raise NotImplementedError

    with pytest.raises(HarnessRegistryError, match="open_episode"):
        HarnessRegistry().register(MissingHooks())

    registry = HarnessRegistry()
    registry.register(_ProtocolCompleteHarness())
    assert registry.resolve("fixture_chat", "1.0") is not None


def test_harness_registry_requires_state_reader_only_with_memory_enabled() -> None:
    class MemoryWithoutReader(_ProtocolCompleteHarness):
        requires = _harness_requirements(frozenset({"session"}))
        state_reader = None

    with pytest.raises(HarnessRegistryError, match="state_reader"):
        HarnessRegistry().register(MemoryWithoutReader())

    class DisabledMemoryWithoutReader(_ProtocolCompleteHarness):
        id = "fixture_chat_no_reader"
        state_reader = None

    registry = HarnessRegistry()
    registry.register(DisabledMemoryWithoutReader())
    assert registry.resolve("fixture_chat_no_reader", "1.0") is not None


def _family_data_with_leaves(**overrides) -> dict:
    """``family_data()`` plus a two-leaf policy: one finalize_time, one deferred."""

    data = family_data()
    data["measurement"] = {
        **data["measurement"],
        "leaves": [
            {"leaf_id": "tenant_realized_utility_leaf", "scope": "finalize_time"},
            {
                "leaf_id": "tenant_nl_assertions_leaf",
                "scope": "deferred",
                "deferred_artifact": "nl_judge_verdict",
            },
        ],
        "primary_leaf_id": "tenant_realized_utility_leaf",
        "admission_leaf_ids": ["tenant_realized_utility_leaf"],
        **overrides,
    }
    return data


def test_measurement_declaration_without_leaves_defaults_to_no_policy() -> None:
    family = FamilyManifest.from_dict(family_data())
    assert family.measurement.leaves == ()
    assert family.measurement.primary_leaf_id is None
    assert family.measurement.admission_leaf_ids == ()


def test_measurement_declaration_without_leaves_is_digest_neutral() -> None:
    """Ruling R1 (kernel_scoring_contract_spec.md): an unset leaf policy must be
    ABSENT from canonical JSON, not merely null/empty. ``leaves``,
    ``primary_leaf_id``, and ``admission_leaf_ids`` were added after Housing
    V8/V11 evidence was sealed; a manifest that never declares a leaf policy
    must hash byte-for-byte as it did before those fields existed, or
    plan_sha256 (and the artifact_sha256 values that depend on it) silently
    change out from under already-published evidence.
    """
    family = FamilyManifest.from_dict(family_data())

    pre_leaf_policy_measurement = {
        "primary_estimand": "tenant_realized_utility",
        "measurement_kind": "optimizable_outcome",
        "direction": "maximize",
        "optimum_lower_bound": "housing_scripted_search_v1",
        "comparison_baseline": "housing_scripted_search_v1",
        "optimum_upper_bound": "housing_exact_assignment_v1",
        "optimum_upper_bound_kind": "full_information_relaxation",
        "bound_status": "bracketed",
        "outcome_support": "undeclared",
    }
    expected_bytes = (
        b'{"bound_status":"bracketed","comparison_baseline":'
        b'"housing_scripted_search_v1","direction":"maximize",'
        b'"measurement_kind":"optimizable_outcome","optimum_lower_bound":'
        b'"housing_scripted_search_v1","optimum_upper_bound":'
        b'"housing_exact_assignment_v1","optimum_upper_bound_kind":'
        b'"full_information_relaxation","outcome_support":"undeclared",'
        b'"primary_estimand":"tenant_realized_utility"}'
    )

    assert canonical_json_bytes(pre_leaf_policy_measurement) == expected_bytes
    assert canonical_json_bytes(family.measurement) == expected_bytes
    assert canonical_json_bytes(family.measurement) == canonical_json_bytes(
        pre_leaf_policy_measurement
    )


def test_measurement_declaration_accepts_a_consistent_leaf_policy() -> None:
    family = FamilyManifest.from_dict(_family_data_with_leaves())
    leaves = family.measurement.leaves
    assert leaves == (
        LeafPolicyDeclaration(
            leaf_id="tenant_realized_utility_leaf",
            scope="finalize_time",
            deferred_artifact=None,
        ),
        LeafPolicyDeclaration(
            leaf_id="tenant_nl_assertions_leaf",
            scope="deferred",
            deferred_artifact="nl_judge_verdict",
        ),
    )
    assert family.measurement.primary_leaf_id == "tenant_realized_utility_leaf"
    assert family.measurement.admission_leaf_ids == ("tenant_realized_utility_leaf",)


def test_measurement_declaration_admission_defaults_to_the_primary_leaf() -> None:
    data = _family_data_with_leaves()
    del data["measurement"]["admission_leaf_ids"]
    family = FamilyManifest.from_dict(data)
    assert family.measurement.admission_leaf_ids == ("tenant_realized_utility_leaf",)


def test_finalize_time_leaf_policy_excludes_deferred_leaves_and_orders_primary_first() -> None:
    data = _family_data_with_leaves()
    data["measurement"]["leaves"].append(
        {"leaf_id": "tenant_ambient_leaf", "scope": "finalize_time"}
    )
    data["measurement"]["admission_leaf_ids"] = [
        "tenant_ambient_leaf",
        "tenant_realized_utility_leaf",
    ]
    family = FamilyManifest.from_dict(data)

    policy = family.measurement.finalize_time_leaf_policy()

    # The deferred leaf is declared but excluded from the finalize-time set
    # (section 4); the two finalize_time leaves come back primary-first,
    # then lexical -- never in authoring order.
    assert policy.leaf_ids == ("tenant_realized_utility_leaf", "tenant_ambient_leaf")
    assert policy.primary_leaf_id == "tenant_realized_utility_leaf"
    assert policy.admission_leaf_ids == (
        "tenant_realized_utility_leaf",
        "tenant_ambient_leaf",
    )
    assert family.finalize_time_leaf_policy() == policy


def test_finalize_time_leaf_policy_requires_a_declared_policy() -> None:
    family = FamilyManifest.from_dict(family_data())
    with pytest.raises(AuthoringValidationError, match="leaf policy"):
        family.finalize_time_leaf_policy()


def test_measurement_declaration_rejects_duplicate_leaf_ids() -> None:
    data = _family_data_with_leaves()
    data["measurement"]["leaves"] = [
        {"leaf_id": "tenant_realized_utility_leaf", "scope": "finalize_time"},
        {"leaf_id": "tenant_realized_utility_leaf", "scope": "finalize_time"},
    ]
    with pytest.raises(AuthoringValidationError, match="duplicate leaf_id"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_an_unknown_leaf_scope() -> None:
    data = _family_data_with_leaves()
    data["measurement"]["leaves"][0]["scope"] = "sometimes"
    with pytest.raises(AuthoringValidationError, match="scope"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_a_deferred_leaf_without_its_artifact() -> None:
    data = _family_data_with_leaves()
    data["measurement"]["leaves"][1] = {
        "leaf_id": "tenant_nl_assertions_leaf",
        "scope": "deferred",
    }
    with pytest.raises(AuthoringValidationError, match="deferred_artifact"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_deferred_artifact_on_a_finalize_time_leaf() -> None:
    data = _family_data_with_leaves()
    data["measurement"]["leaves"][0] = {
        "leaf_id": "tenant_realized_utility_leaf",
        "scope": "finalize_time",
        "deferred_artifact": "should not be here",
    }
    with pytest.raises(AuthoringValidationError, match="deferred_artifact"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_a_primary_leaf_not_in_the_leaf_set() -> None:
    data = _family_data_with_leaves(primary_leaf_id="not_a_declared_leaf")
    with pytest.raises(AuthoringValidationError, match="declared leaf"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_a_deferred_leaf_as_primary() -> None:
    data = _family_data_with_leaves(primary_leaf_id="tenant_nl_assertions_leaf")
    data["measurement"]["admission_leaf_ids"] = ["tenant_nl_assertions_leaf"]
    with pytest.raises(AuthoringValidationError, match="finalize_time leaf"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_admission_leaves_outside_the_leaf_set() -> None:
    data = _family_data_with_leaves(
        admission_leaf_ids=["tenant_realized_utility_leaf", "not_a_declared_leaf"]
    )
    with pytest.raises(AuthoringValidationError, match="admission_leaf_ids"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_a_deferred_leaf_as_admission() -> None:
    data = _family_data_with_leaves(
        admission_leaf_ids=["tenant_realized_utility_leaf", "tenant_nl_assertions_leaf"]
    )
    with pytest.raises(AuthoringValidationError, match="deferred leaf"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_a_primary_leaf_excluded_from_admission() -> None:
    data = _family_data_with_leaves()
    data["measurement"]["leaves"].append(
        {"leaf_id": "tenant_secondary_leaf", "scope": "finalize_time"}
    )
    data["measurement"]["admission_leaf_ids"] = ["tenant_secondary_leaf"]
    with pytest.raises(AuthoringValidationError, match="admission_leaf_ids"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_leaves_with_no_finalize_time_member() -> None:
    # No primary_leaf_id/admission_leaf_ids at all: an all-deferred leaf list
    # must be rejected by the "at least one finalize_time leaf" guard itself,
    # not merely as a side effect of some other guard also refusing a
    # (necessarily invalid) primary/admission choice.
    data = _family_data_with_leaves()
    data["measurement"]["leaves"] = [
        {
            "leaf_id": "tenant_nl_assertions_leaf",
            "scope": "deferred",
            "deferred_artifact": "nl_judge_verdict",
        }
    ]
    del data["measurement"]["primary_leaf_id"]
    del data["measurement"]["admission_leaf_ids"]
    with pytest.raises(AuthoringValidationError, match="at least one finalize_time"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_primary_leaf_id_without_declared_leaves() -> None:
    data = family_data()
    data["measurement"] = {
        **data["measurement"],
        "primary_leaf_id": "tenant_realized_utility_leaf",
    }
    with pytest.raises(AuthoringValidationError, match="leaves to be declared"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_admission_leaf_ids_without_declared_leaves() -> None:
    data = family_data()
    data["measurement"] = {
        **data["measurement"],
        "admission_leaf_ids": ["tenant_realized_utility_leaf"],
    }
    with pytest.raises(AuthoringValidationError, match="leaves to be declared"):
        FamilyManifest.from_dict(data)


def test_measurement_declaration_rejects_declared_leaves_without_a_primary_leaf_id() -> None:
    data = _family_data_with_leaves()
    del data["measurement"]["primary_leaf_id"]
    del data["measurement"]["admission_leaf_ids"]
    with pytest.raises(AuthoringValidationError, match="primary_leaf_id is required"):
        FamilyManifest.from_dict(data)


def test_registry_rejects_registration_of_a_plugin_with_an_inconsistent_leaf_policy() -> None:
    """An inconsistent leaf policy never reaches ``PluginRegistry`` at all.

    ``FamilyManifest.from_dict`` is a hard precondition of registration --
    there is no path from an authored, inconsistent manifest dict to a
    registered plugin, so the rejection is necessarily no later than
    registration, never deferred to score time.
    """

    with pytest.raises(AuthoringValidationError, match="declared leaf"):
        FamilyManifest.from_dict(
            _family_data_with_leaves(primary_leaf_id="not_a_declared_leaf")
        )
