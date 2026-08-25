from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from aeread.runner.planning import (
    CapabilityMismatch,
    IncompleteAgentAssignment,
    InvalidClusterDeclaration,
    ManifestMismatch,
    resolve_run_plan,
    verify_run_plan_identity,
)
from aeread.runner.registry import PluginRegistry
from aeread.sdk.v1 import (
    AgentProfile,
    CaseManifest,
    CaseProvenance,
    ClusterSpec,
    ImplementationRef,
    MeasurementSpec,
    MemoryPin,
    ModelPin,
    ProviderPin,
    RetryPolicy,
    RuntimePin,
    SamplingPin,
    content_sha256,
)

from .fakes import (
    FakeAgentAdapter,
    FakeEnvironment,
    FakeExecutionBackend,
    FakeVerifier,
    fake_implementation,
    fake_resolution_inputs,
)


def _registry(*, call_observability: str = "full") -> PluginRegistry:
    return PluginRegistry.from_objects(
        environments=[FakeEnvironment()],
        verifiers=[FakeVerifier()],
        agent_adapters=[FakeAgentAdapter(call_observability=call_observability)],
        execution_backends=[FakeExecutionBackend()],
    )


def _replace(inputs, **updates):
    return inputs.model_copy(update=updates)


def _rehash_top_level(plan):
    basis = plan.model_dump(mode="python", exclude={"run_plan_id", "run_plan_sha256"})
    digest = content_sha256(basis)
    return plan.model_copy(
        update={
            "run_plan_id": "runplan-" + digest[:24],
            "run_plan_sha256": digest,
        }
    )


def _replace_first_cell(plan, **updates):
    first = plan.cells[0].model_copy(update=updates)
    return _rehash_top_level(
        plan.model_copy(update={"cells": (first, *plan.cells[1:])})
    )


def test_run_plan_is_self_contained_for_execution() -> None:
    inputs = fake_resolution_inputs()
    plan = resolve_run_plan(inputs, _registry())

    assert plan.family.phase_graph == inputs.family.phase_graph
    assert plan.suite.blocks[0].estimand_id == "buyer_utility"
    assert plan.run_spec.execution_mode == "local"
    assert [case.case_id for case in plan.cases] == ["case-b"]
    assert plan.cases[0].payload["reserve"] == 3

    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    candidate = profiles["candidate"]
    assert candidate.provider.provider_id == "fake-provider"
    assert candidate.provider.api_version == "2026-08-01"
    assert candidate.model.model_id == "fake-model-candidate"
    assert candidate.model.revision == "2026-08-01"
    assert candidate.harness.content_sha256 == "7" * 64
    assert candidate.runtime.config["isolation"] == "in_process"
    assert candidate.prompt_sha256 == "5" * 64
    assert candidate.sampling.content["temperature"] == 0.0
    assert candidate.tools == ()
    assert candidate.memory.mode == "none"
    assert candidate.attempt_budget.output_token_limit == 64
    assert candidate.retry_policy.max_attempts == 1
    assert dict(plan.adapter_call_observability_by_profile) == {
        "candidate": "full",
        "counterpart": "full",
    }


def test_adapter_observability_is_profile_scoped_and_admission_critical() -> None:
    inputs = fake_resolution_inputs()
    weak_profiles = tuple(
        profile.model_copy(update={"call_observability": "logical_only"})
        for profile in inputs.agent_profiles
    )
    weak_inputs = _replace(inputs, agent_profiles=weak_profiles)

    with pytest.raises(CapabilityMismatch) as exc_info:
        resolve_run_plan(
            weak_inputs,
            _registry(call_observability="logical_only"),
        )
    failed = {
        (check.profile_id, check.axis)
        for check in exc_info.value.report.checks
        if not check.passed
    }
    assert failed == {
        ("candidate", "agent_adapter.call_observability.admission"),
        ("counterpart", "agent_adapter.call_observability.admission"),
    }

    interop = _replace(
        weak_inputs,
        run_spec=weak_inputs.run_spec.model_copy(
            update={"admission_profile": "interop_only"}
        ),
    )
    plan = resolve_run_plan(interop, _registry(call_observability="logical_only"))
    assert dict(plan.adapter_call_observability_by_profile) == {
        "candidate": "logical_only",
        "counterpart": "logical_only",
    }
    assert all(
        check.passed
        for check in plan.admission_report.checks
        if check.profile_id is not None
    )


def test_adapter_observability_must_match_profile_pin() -> None:
    with pytest.raises(CapabilityMismatch) as exc_info:
        resolve_run_plan(
            fake_resolution_inputs(),
            _registry(call_observability="logical_only"),
        )
    assert {
        check.axis for check in exc_info.value.report.checks if not check.passed
    } == {
        "agent_adapter.call_observability.pin",
        "agent_adapter.call_observability.admission",
    }


def test_measurement_reference_combinations_are_settled_before_execution() -> None:
    lower = fake_implementation("lower_bound", marker="a")
    upper = fake_implementation("upper_bound", marker="b")
    baseline = fake_implementation("baseline", marker="c")

    with pytest.raises(ValidationError, match="lower.*upper"):
        MeasurementSpec(
            estimand_id="welfare",
            measurement_kind="optimizable_outcome",
            direction="maximize",
            primary_metric_id="welfare",
            verifier_plugin_id="fake_verifier",
            bound_status="exact_solved",
            reference_implementations={"optimum_lower_bound": lower},
        )
    with pytest.raises(ValidationError, match="comparison_baseline"):
        MeasurementSpec(
            estimand_id="preference",
            measurement_kind="comparative_or_human_judged",
            direction="maximize",
            primary_metric_id="preference",
            verifier_plugin_id="fake_verifier",
            bound_status="baseline_only",
            reference_implementations={},
        )
    with pytest.raises(ValidationError, match="support"):
        MeasurementSpec(
            estimand_id="welfare",
            measurement_kind="optimizable_outcome",
            direction="maximize",
            primary_metric_id="welfare",
            verifier_plugin_id="fake_verifier",
            bound_status="bracketed",
            reference_implementations={
                "optimum_lower_bound": lower,
                "optimum_upper_bound": upper,
                "outcome_support_min": baseline,
            },
        )
    with pytest.raises(ValidationError):
        MeasurementSpec(
            estimand_id="welfare",
            measurement_kind="optimizable_outcome",
            direction="maximize",
            primary_metric_id="welfare",
            verifier_plugin_id="fake_verifier",
            bound_status="invented",
            reference_implementations={"invented": baseline},
        )


def test_cells_pin_estimand_verifier_references_and_cluster_contract() -> None:
    inputs = fake_resolution_inputs()
    plan = resolve_run_plan(inputs, _registry())
    measurement = inputs.family.measurements[0]

    assert all(cell.estimand_id == "buyer_utility" for cell in plan.cells)
    assert all(
        cell.measurement_sha256 == content_sha256(measurement) for cell in plan.cells
    )
    assert all(
        cell.verifier_ref.implementation_id == "fake_verifier" for cell in plan.cells
    )
    assert all(
        dict(cell.reference_refs) == dict(measurement.reference_implementations)
        for cell in plan.cells
    )

    suite_without_cluster = inputs.suite.model_copy(update={"cluster_by_estimand": {}})
    with pytest.raises(InvalidClusterDeclaration):
        resolve_run_plan(_replace(inputs, suite=suite_without_cluster), _registry())


def test_multi_estimand_suite_uses_an_estimand_keyed_cluster_contract() -> None:
    inputs = fake_resolution_inputs()
    second_measurement = MeasurementSpec(
        estimand_id="deal_rate",
        measurement_kind="property_or_answer",
        direction="maximize",
        primary_metric_id="deal_rate",
        verifier_plugin_id="fake_verifier",
        bound_status="descriptive_only",
        reference_implementations={},
    )
    family = inputs.family.model_copy(
        update={
            "measurements": (
                inputs.family.measurements[0],
                second_measurement,
            )
        }
    )
    second_block = inputs.suite.blocks[0].model_copy(
        update={"block_id": "deal_rate", "estimand_id": "deal_rate"}
    )
    second_cluster = ClusterSpec(
        cluster_level="case",
        identity_fields=("case_id",),
        paired_fields=("rollout_seed",),
        parent_field=None,
        panel_mode="fixed_panel",
    )
    suite = inputs.suite.model_copy(
        update={
            "blocks": (inputs.suite.blocks[0], second_block),
            "cluster_by_estimand": {
                "buyer_utility": inputs.suite.cluster_by_estimand["buyer_utility"],
                "deal_rate": second_cluster,
            },
        }
    )

    plan = resolve_run_plan(_replace(inputs, family=family, suite=suite), _registry())
    assert {cell.estimand_id for cell in plan.cells} == {
        "buyer_utility",
        "deal_rate",
    }
    assert len(plan.cells) == 8


def test_controlled_profile_allowlist_is_not_a_wildcard() -> None:
    inputs = fake_resolution_inputs()
    roles = tuple(
        role.model_copy(update={"controlled_profile_ids": ()})
        if role.role_id == "seller"
        else role
        for role in inputs.family.roles
    )
    family = inputs.family.model_copy(update={"roles": roles})

    with pytest.raises(IncompleteAgentAssignment, match="not allowed"):
        resolve_run_plan(_replace(inputs, family=family), _registry())


@pytest.mark.parametrize("alias", ("latest", "current", "default", "stable"))
def test_agent_configuration_rejects_mutable_version_aliases(alias: str) -> None:
    profile = fake_resolution_inputs().agent_profiles[0]
    raw = profile.model_dump(mode="python")
    raw["model"]["revision"] = alias

    with pytest.raises(ValidationError, match="revision"):
        AgentProfile.model_validate(raw)


def test_agent_configuration_and_retry_taxonomy_are_strict() -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(
            max_attempts=2,
            retryable_conditions=("network",),
        )
    with pytest.raises(ValidationError, match="retryable_conditions"):
        RetryPolicy(max_attempts=2, retryable_conditions=())
    with pytest.raises(ValidationError, match="length"):
        RetryPolicy(
            max_attempts=2,
            retryable_conditions=("length",),
            length_retry_output_tokens=None,
        )
    with pytest.raises(ValidationError, match="memory"):
        MemoryPin(mode="persistent", policy=None, config={})
    profile = fake_resolution_inputs().agent_profiles[0]
    raw = profile.model_dump(mode="python")
    raw["retry_policy"] = {
        "max_attempts": 2,
        "retryable_conditions": (),
        "length_retry_output_tokens": None,
    }
    with pytest.raises(ValidationError, match="retryable_conditions"):
        AgentProfile.model_validate(raw)

    assert ProviderPin(provider_id="provider", api_version="2026-08-01")
    assert ModelPin(model_id="model", revision="sha-123")
    assert RuntimePin(implementation=fake_implementation("runtime"), config={})
    assert SamplingPin(schema_id="sampling", schema_version="1.0.0", content={})


def test_generated_case_must_match_family_generator_pin() -> None:
    inputs = fake_resolution_inputs()
    generator = inputs.family.generator.model_copy(update={"version": "2.0.0"})
    family = inputs.family.model_copy(update={"generator": generator})

    with pytest.raises(ManifestMismatch, match="generator"):
        resolve_run_plan(_replace(inputs, family=family), _registry())


def test_curated_case_uses_explicit_no_generator_path() -> None:
    inputs = fake_resolution_inputs()
    case_data = inputs.cases[0].model_dump(
        mode="python", exclude={"content_sha256", "provenance"}
    )
    curated_case = CaseManifest.from_content(
        **case_data,
        provenance=CaseProvenance(
            source_kind="curated",
            generator_id=None,
            generator_version=None,
            curator_id="curator",
            curator_version="1.0.0",
            review_status="curated",
        ),
    )
    family = inputs.family.model_copy(update={"generator": None})
    cluster = inputs.suite.cluster_by_estimand["buyer_utility"].model_copy(
        update={"parent_field": None}
    )
    suite = inputs.suite.model_copy(
        update={"cluster_by_estimand": {"buyer_utility": cluster}}
    )

    plan = resolve_run_plan(
        _replace(
            inputs,
            family=family,
            cases=(curated_case,),
            suite=suite,
        ),
        _registry(),
    )
    assert plan.cases[0].provenance.source_kind == "curated"


def _tamper_cell_id(plan):
    return _replace_first_cell(plan, cell_id="cell-forged")


def _tamper_input_hash(plan):
    return _replace_first_cell(plan, family_sha256="d" * 64)


def _tamper_candidate_hash(plan):
    return _replace_first_cell(plan, candidate_agent_config_sha256="e" * 64)


def _tamper_seat_maps(plan):
    first = plan.cells[0]
    return _replace_first_cell(
        plan,
        seat_profile_id_by_seat={"buyer-1": "candidate"},
        seat_profile_sha256_by_seat={"buyer-1": first.candidate_agent_config_sha256},
    )


def _tamper_measurement_pin(plan):
    return _replace_first_cell(
        plan,
        verifier_ref=fake_implementation("fake_backend", marker="f"),
    )


def _tamper_admission_report(plan):
    check = plan.admission_report.checks[0].model_copy(update={"passed": False})
    report = plan.admission_report.model_copy(
        update={"checks": (check, *plan.admission_report.checks[1:])}
    )
    return _rehash_top_level(plan.model_copy(update={"admission_report": report}))


def _tamper_cell_order(plan):
    return _rehash_top_level(
        plan.model_copy(update={"cells": tuple(reversed(plan.cells))})
    )


def _tamper_cluster_count(plan):
    return _replace_first_cell(plan, observations_per_cluster=99)


def _tamper_missing_cell(plan):
    return _rehash_top_level(plan.model_copy(update={"cells": plan.cells[:-1]}))


def _tamper_rollout_coordinate_with_rehashed_cell(plan):
    first = plan.cells[0].model_copy(update={"rollout_seed": 999})
    basis = first.model_dump(mode="python", exclude={"cell_id"})
    first = first.model_copy(update={"cell_id": "cell-" + content_sha256(basis)[:24]})
    return _rehash_top_level(
        plan.model_copy(update={"cells": (first, *plan.cells[1:])})
    )


@pytest.mark.parametrize(
    "tamper",
    (
        _tamper_cell_id,
        _tamper_input_hash,
        _tamper_candidate_hash,
        _tamper_seat_maps,
        _tamper_measurement_pin,
        _tamper_admission_report,
        _tamper_cell_order,
        _tamper_cluster_count,
        _tamper_missing_cell,
        _tamper_rollout_coordinate_with_rehashed_cell,
    ),
)
def test_deep_verifier_rejects_tampering_even_after_top_level_rehash(
    tamper: Callable[[object], object]
) -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    forged = tamper(plan)

    assert not verify_run_plan_identity(forged)
