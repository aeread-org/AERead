from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from aeread.runner.planning import (
    CapabilityMismatch,
    IncompleteAgentAssignment,
    InvalidAgentRequest,
    InvalidClusterDeclaration,
    ManifestMismatch,
    build_agent_request_from_plan,
    resolve_run_plan,
    verify_run_plan_identity,
)
from aeread.runner.registry import PluginRegistry
from aeread.sdk.v1 import (
    AgentExecutionConfig,
    AgentContext,
    AgentProfile,
    AgentRequest,
    CanonicalResponse,
    CaseManifest,
    CaseProvenance,
    ClusterSpec,
    ComparativeMeasurementSpec,
    ComparisonBaselineContract,
    BracketedRule,
    EpsilonSolvedRule,
    ExactSolvedRule,
    ImplementationRef,
    LowerBoundOnlyRule,
    MemoryPin,
    ModelPin,
    OptimizableOutcomeMeasurementSpec,
    OptimizationReferenceContract,
    OutcomeSupportContract,
    PropertyAnswerMeasurementSpec,
    ProviderPin,
    RetryPolicy,
    RuntimePin,
    SamplingPin,
    content_sha256,
)

from .fakes import (
    REQUEST,
    FakeAgentAdapter,
    FakeAttemptObserver,
    FakeEnvironment,
    FakeExecutionBackend,
    FakeVerifier,
    fake_agent_profile,
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


def test_run_plan_profile_materializes_the_exact_adapter_execution_config() -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    cell = plan.cells[0]
    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    profile = profiles[cell.seat_profile_id_by_seat[cell.subject_seat_id]]

    request = AgentRequest.from_profile(
        logical_action_id="logical-action-probe",
        phase_id="offers",
        slot=REQUEST.slot,
        observation=REQUEST.observation,
        profile=profile,
        expected_profile_sha256=cell.seat_profile_sha256_by_seat[cell.subject_seat_id],
    )

    assert isinstance(request.execution_config, AgentExecutionConfig)
    assert request.execution_config.prompt == "You are the candidate buyer."
    assert request.execution_config.model.model_id == "fake-model-candidate"
    assert request.execution_config.model.revision == "2026-08-01"
    assert request.execution_config.sampling.content["temperature"] == 0.0
    assert request.execution_config.tools == ()
    assert request.execution_config.memory.mode == "none"
    assert request.budget == request.execution_config.attempt_budget

    class ConfigReadingAdapter:
        async def act(self, incoming, *, attempts):
            config = incoming.execution_config
            return CanonicalResponse(
                content=(
                    f"{config.prompt}|{config.model.model_id}@{config.model.revision}|"
                    f"{config.sampling.content['temperature']}|{config.memory.mode}"
                )
            )

    response = asyncio.run(
        ConfigReadingAdapter().act(request, attempts=FakeAttemptObserver())
    )
    assert response.content == (
        "You are the candidate buyer.|fake-model-candidate@2026-08-01|0.0|none"
    )

    with pytest.raises(ValueError, match="profile hash"):
        AgentRequest.from_profile(
            logical_action_id="logical-action-forged",
            phase_id="offers",
            slot=REQUEST.slot,
            observation=REQUEST.observation,
            profile=profile,
            expected_profile_sha256="f" * 64,
        )


def test_agent_request_rejects_candidate_claims_with_counterpart_config() -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    cell = plan.cells[0]
    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    candidate = profiles["candidate"]
    counterpart = profiles["counterpart"]
    counterpart_config = counterpart.execution_config

    with pytest.raises(ValidationError):
        AgentRequest(
            logical_action_id="logical-action-forged-profile",
            phase_id="offers",
            slot=REQUEST.slot,
            observation=REQUEST.observation,
            context=AgentContext(
                agent_profile_id=candidate.profile_id,
                seat_id=cell.subject_seat_id,
                provider=counterpart_config.provider.provider_id,
                model=counterpart_config.model.model_id,
                harness=counterpart_config.harness.implementation_id,
                runtime=counterpart_config.runtime.implementation.implementation_id,
            ),
            agent_profile_sha256=cell.candidate_agent_config_sha256,
            execution_config_sha256=content_sha256(counterpart_config),
            execution_config=counterpart_config,
            budget=counterpart_config.attempt_budget,
        )


def test_agent_request_builds_from_the_exact_plan_cell_and_seat() -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    cell = plan.cells[0]

    request = build_agent_request_from_plan(
        plan,
        cell_id=cell.cell_id,
        seat_id=cell.subject_seat_id,
        phase_id="offers",
        logical_action_id="logical-action-from-plan",
        slot=REQUEST.slot,
        observation=REQUEST.observation,
    )

    assert request.profile.profile_id == "candidate"
    assert request.agent_profile_sha256 == cell.candidate_agent_config_sha256
    assert request.execution_config.prompt == "You are the candidate buyer."
    assert request.context.seat_id == cell.subject_seat_id


def test_agent_request_plan_builder_rejects_wrong_plan_cell_seat_and_hash() -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    cell = plan.cells[0]

    invalid_plan = plan.model_copy(update={"run_plan_sha256": "f" * 64})
    with pytest.raises(InvalidAgentRequest, match="plan identity"):
        build_agent_request_from_plan(
            invalid_plan,
            cell_id=cell.cell_id,
            seat_id=cell.subject_seat_id,
            phase_id="offers",
            logical_action_id="logical-action-invalid-plan",
            slot=REQUEST.slot,
            observation=REQUEST.observation,
        )

    with pytest.raises(InvalidAgentRequest, match="cell"):
        build_agent_request_from_plan(
            plan,
            cell_id="cell-missing",
            seat_id=cell.subject_seat_id,
            phase_id="offers",
            logical_action_id="logical-action-missing-cell",
            slot=REQUEST.slot,
            observation=REQUEST.observation,
        )

    with pytest.raises(InvalidAgentRequest, match="seat"):
        build_agent_request_from_plan(
            plan,
            cell_id=cell.cell_id,
            seat_id="seat-missing",
            phase_id="offers",
            logical_action_id="logical-action-missing-seat",
            slot=REQUEST.slot,
            observation=REQUEST.observation,
        )

    forged_hashes = dict(cell.seat_profile_sha256_by_seat)
    forged_hashes[cell.subject_seat_id] = "e" * 64
    forged = _replace_first_cell(
        plan,
        seat_profile_sha256_by_seat=forged_hashes,
    )
    with pytest.raises(InvalidAgentRequest, match="plan identity"):
        build_agent_request_from_plan(
            forged,
            cell_id=forged.cells[0].cell_id,
            seat_id=cell.subject_seat_id,
            phase_id="offers",
            logical_action_id="logical-action-forged-hash",
            slot=REQUEST.slot,
            observation=REQUEST.observation,
        )


@pytest.mark.parametrize(
    ("slot", "observation"),
    (
        (None, REQUEST.observation),
        (REQUEST.slot, object()),
        (
            REQUEST.slot.model_copy(
                update={
                    "channels": (
                        REQUEST.slot.channels[0].model_copy(update={"min_actions": -1}),
                    )
                }
            ),
            REQUEST.observation,
        ),
    ),
)
def test_agent_request_builder_normalizes_malformed_slot_and_observation(
    slot: object, observation: object
) -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    cell = plan.cells[0]

    with pytest.raises(InvalidAgentRequest, match="slot|observation") as exc_info:
        build_agent_request_from_plan(
            plan,
            cell_id=cell.cell_id,
            seat_id=cell.subject_seat_id,
            phase_id="offers",
            logical_action_id="logical-action-malformed-input",
            slot=slot,
            observation=observation,
        )

    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_agent_request_builder_wraps_observation_slot_mismatch() -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    cell = plan.cells[0]
    mismatched_observation = REQUEST.observation.model_copy(
        update={"slot_id": "different-slot"}
    )

    with pytest.raises(InvalidAgentRequest, match="planned profile") as exc_info:
        build_agent_request_from_plan(
            plan,
            cell_id=cell.cell_id,
            seat_id=cell.subject_seat_id,
            phase_id="offers",
            logical_action_id="logical-action-mismatched-observation",
            slot=REQUEST.slot,
            observation=mismatched_observation,
        )

    assert isinstance(exc_info.value.__cause__, ValidationError)


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
    config = candidate.execution_config
    assert config.provider.provider_id == "fake-provider"
    assert config.provider.api_version == "2026-08-01"
    assert config.model.model_id == "fake-model-candidate"
    assert config.model.revision == "2026-08-01"
    assert config.harness.content_sha256 == "7" * 64
    assert config.runtime.config["isolation"] == "in_process"
    assert config.prompt == "You are the candidate buyer."
    assert config.prompt_sha256 == content_sha256(config.prompt)
    assert config.sampling.content["temperature"] == 0.0
    assert config.tools == ()
    assert config.memory.mode == "none"
    assert config.attempt_budget.output_token_limit == 64
    assert config.retry_policy.max_attempts == 1
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


def _optimization_contract(kind: str) -> OptimizationReferenceContract:
    return OptimizationReferenceContract(
        kind=kind,
        objective_id="buyer_utility",
        objective_version="1.0.0",
        units="utility_points",
        direction="maximize",
        feasible_set="offers permitted by fake_market/1.0.0",
        information_set="buyer-private observation",
        horizon="two offer rounds",
        opponent_condition="fixed counterpart/1.0.0",
        stochastic_expectation="expectation over declared rollout seeds",
        proof_type="executable feasible witness",
        implementation=fake_implementation(f"buyer_utility_{kind}"),
        validity_domain="fake_market/1.0.0 dev split",
        applicability="fake_market/1.0.0 declared estimand",
    )


def test_property_measurement_cannot_claim_policy_optimality() -> None:
    with pytest.raises(ValidationError):
        PropertyAnswerMeasurementSpec(
            estimand_id="equilibrium_property",
            measurement_kind="property_or_answer",
            direction="maximize",
            primary_metric_id="property_pass",
            verifier_plugin_id="fake_verifier",
            verifier_semantics_id="exact_property_check",
            verifier_semantics_version="1.0.0",
            property_definition_id="market_clears",
            property_definition_version="1.0.0",
            answer_schema_ref="boolean_answer/1.0.0",
            bound_status="exact_solved",
            reference_contracts={
                "optimum_lower_bound": _optimization_contract("optimum_lower_bound"),
                "optimum_upper_bound": _optimization_contract("optimum_upper_bound"),
            },
        )


def test_optimizable_measurement_requires_scope_proof_and_complete_exact_bounds() -> None:
    base = {
        "estimand_id": "buyer_utility",
        "measurement_kind": "optimizable_outcome",
        "direction": "maximize",
        "source_direction": "maximize",
        "source_to_canonical_rule": "identity",
        "primary_metric_id": "buyer_utility",
        "verifier_plugin_id": "fake_verifier",
        "verifier_semantics_id": "realized_utility",
        "verifier_semantics_version": "1.0.0",
        "objective_id": "buyer_utility",
        "objective_version": "1.0.0",
        "units": "utility_points",
        "feasible_set": "offers permitted by fake_market/1.0.0",
        "information_set": "buyer-private observation",
        "horizon": "two offer rounds",
        "opponent_condition": "fixed counterpart/1.0.0",
        "stochastic_expectation": "expectation over declared rollout seeds",
        "validity_domain": "fake_market/1.0.0 dev split",
        "reference_applicability": "fake_market/1.0.0 declared estimand",
        "claim_rule": ExactSolvedRule(certification_rule="computed_bound_gap_eq_zero"),
    }

    for missing_field in ("information_set", "horizon"):
        missing_scope = dict(base)
        del missing_scope[missing_field]
        with pytest.raises(ValidationError, match=missing_field):
            OptimizableOutcomeMeasurementSpec.model_validate(missing_scope)

    lower_without_proof = _optimization_contract("optimum_lower_bound").model_dump(
        mode="python"
    )
    del lower_without_proof["proof_type"]
    with pytest.raises(ValidationError, match="proof_type"):
        OptimizationReferenceContract.model_validate(lower_without_proof)

    with pytest.raises(ValidationError, match="lower and upper"):
        OptimizableOutcomeMeasurementSpec.model_validate(
            {
                **base,
                "reference_contracts": {
                    "optimum_lower_bound": _optimization_contract("optimum_lower_bound")
                },
            }
        )


def test_optimizable_lower_bound_rejects_noncanonical_minimize_direction() -> None:
    raw = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    raw["direction"] = "minimize"
    raw["reference_contracts"]["optimum_lower_bound"]["direction"] = "minimize"

    with pytest.raises(ValidationError, match="direction"):
        OptimizableOutcomeMeasurementSpec.model_validate(raw)


@pytest.mark.parametrize(
    "missing_field", ("source_direction", "source_to_canonical_rule")
)
def test_optimizable_measurement_requires_source_orientation_contract(
    missing_field: str,
) -> None:
    raw = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    del raw[missing_field]

    with pytest.raises(ValidationError, match=missing_field):
        OptimizableOutcomeMeasurementSpec.model_validate(raw)


@pytest.mark.parametrize(
    ("source_direction", "source_to_canonical_rule"),
    (("maximize", "negate"), ("minimize", "identity")),
)
def test_optimizable_measurement_rejects_misstated_orientation_transform(
    source_direction: str, source_to_canonical_rule: str
) -> None:
    raw = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    raw.update(
        {
            "source_direction": source_direction,
            "source_to_canonical_rule": source_to_canonical_rule,
        }
    )

    with pytest.raises(ValidationError, match="source.*canonical"):
        OptimizableOutcomeMeasurementSpec.model_validate(raw)


def test_optimizable_measurement_declares_minimize_source_as_negated_maximize() -> None:
    raw = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    raw.update(
        {
            "source_direction": "minimize",
            "source_to_canonical_rule": "negate",
        }
    )

    measurement = OptimizableOutcomeMeasurementSpec.model_validate(raw)

    assert measurement.direction == "maximize"
    assert measurement.source_direction == "minimize"
    assert measurement.source_to_canonical_rule == "negate"


def test_comparative_measurement_requires_a_typed_baseline() -> None:
    with pytest.raises(ValidationError, match="comparison_baseline"):
        ComparativeMeasurementSpec(
            estimand_id="preference",
            measurement_kind="comparative_or_human_judged",
            direction="maximize",
            primary_metric_id="preference_rate",
            verifier_plugin_id="fake_verifier",
            verifier_semantics_id="paired_preference",
            verifier_semantics_version="1.0.0",
            comparison_target_id="candidate_vs_baseline",
            comparison_protocol_id="paired_blind_review",
            comparison_protocol_version="1.0.0",
            rater_semantics_id="majority_preference",
            rater_semantics_version="1.0.0",
            comparison_baseline=None,
        )

    baseline = ComparisonBaselineContract(
        kind="comparison_baseline",
        comparison_id="fixed_policy",
        comparison_version="1.0.0",
        objective_id="preference",
        objective_version="1.0.0",
        units="preference_rate",
        direction="maximize",
        feasible_set="same cases and action surface",
        information_set="same visible observations",
        horizon="same episode budget",
        opponent_condition="same fixed counterpart",
        stochastic_expectation="paired-case empirical expectation",
        proof_type="executable pinned policy",
        implementation=fake_implementation("fixed_policy"),
        validity_domain="fake_market/1.0.0 dev split",
        provenance={"source": "curated baseline"},
        applicability="paired candidate comparison",
    )
    measurement = ComparativeMeasurementSpec(
        estimand_id="preference",
        measurement_kind="comparative_or_human_judged",
        direction="maximize",
        primary_metric_id="preference_rate",
        verifier_plugin_id="fake_verifier",
        verifier_semantics_id="paired_preference",
        verifier_semantics_version="1.0.0",
        comparison_target_id="candidate_vs_baseline",
        comparison_protocol_id="paired_blind_review",
        comparison_protocol_version="1.0.0",
        rater_semantics_id="majority_preference",
        rater_semantics_version="1.0.0",
        comparison_baseline=baseline,
    )
    assert measurement.comparison_baseline.kind == "comparison_baseline"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("objective_id", "different_objective"),
        ("objective_version", "2.0.0"),
        ("units", "nonsense_units"),
        ("direction", "minimize"),
        ("feasible_set", "different feasible set"),
        ("information_set", "full-information oracle"),
        ("horizon", "unbounded horizon"),
        ("opponent_condition", "live opponent"),
        ("stochastic_expectation", "best observed rollout"),
        ("validity_domain", "different family"),
        ("applicability", "different estimand"),
    ),
)
def test_optimization_reference_must_match_every_estimand_scope_field(
    field: str, bad_value: str
) -> None:
    lower = _optimization_contract("optimum_lower_bound")
    raw_lower = lower.model_dump(mode="python")
    raw_lower[field] = bad_value

    with pytest.raises(ValidationError, match="reference scope"):
        OptimizableOutcomeMeasurementSpec(
            estimand_id="buyer_utility",
            measurement_kind="optimizable_outcome",
            direction="maximize",
            source_direction="maximize",
            source_to_canonical_rule="identity",
            primary_metric_id="buyer_utility",
            verifier_plugin_id="fake_verifier",
            verifier_semantics_id="realized_utility",
            verifier_semantics_version="1.0.0",
            objective_id="buyer_utility",
            objective_version="1.0.0",
            units="utility_points",
            feasible_set="offers permitted by fake_market/1.0.0",
            information_set="buyer-private observation",
            horizon="two offer rounds",
            opponent_condition="fixed counterpart/1.0.0",
            stochastic_expectation="expectation over declared rollout seeds",
            validity_domain="fake_market/1.0.0 dev split",
            reference_applicability="fake_market/1.0.0 declared estimand",
            claim_rule=LowerBoundOnlyRule(
                certification_rule="feasible_witness_lower_bounds_optimum"
            ),
            reference_contracts={"optimum_lower_bound": raw_lower},
        )


def test_epsilon_and_bound_statuses_require_typed_certification_rules() -> None:
    with pytest.raises(ValidationError, match="epsilon"):
        EpsilonSolvedRule(
            certification_rule="computed_bound_gap_lte_epsilon",
            epsilon_units="utility_points",
        )
    with pytest.raises(ValidationError, match="greater than 0"):
        EpsilonSolvedRule(
            certification_rule="computed_bound_gap_lte_epsilon",
            epsilon=0.0,
            epsilon_units="utility_points",
        )
    with pytest.raises(ValidationError, match="computed_bound_gap_lte_epsilon"):
        EpsilonSolvedRule(
            certification_rule="observed_score_is_close",
            epsilon=0.1,
            epsilon_units="utility_points",
        )
    with pytest.raises(ValidationError, match="computed_bound_gap_eq_zero"):
        ExactSolvedRule(certification_rule="bounds_exist")
    with pytest.raises(ValidationError, match="certified_lower_le_optimum_le_upper"):
        BracketedRule(certification_rule="bounds_exist")

    base = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    with pytest.raises(ValidationError, match="epsilon units"):
        OptimizableOutcomeMeasurementSpec.model_validate(
            {
                **base,
                "claim_rule": EpsilonSolvedRule(
                    certification_rule="computed_bound_gap_lte_epsilon",
                    epsilon=0.1,
                    epsilon_units="dollars",
                ),
                "reference_contracts": {
                    "optimum_lower_bound": _optimization_contract(
                        "optimum_lower_bound"
                    ),
                    "optimum_upper_bound": _optimization_contract(
                        "optimum_upper_bound"
                    ),
                },
            }
        )


def test_baseline_and_support_contracts_cannot_escape_estimand_scope() -> None:
    base = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    shared = {
        "objective_id": "buyer_utility",
        "objective_version": "1.0.0",
        "units": "utility_points",
        "direction": "minimize",
        "feasible_set": "offers permitted by fake_market/1.0.0",
        "information_set": "buyer-private observation",
        "horizon": "two offer rounds",
        "opponent_condition": "fixed counterpart/1.0.0",
        "stochastic_expectation": "expectation over declared rollout seeds",
        "proof_type": "pinned executable policy",
        "validity_domain": "fake_market/1.0.0 dev split",
        "applicability": "fake_market/1.0.0 declared estimand",
    }
    baseline = ComparisonBaselineContract(
        kind="comparison_baseline",
        comparison_id="fixed_policy",
        comparison_version="1.0.0",
        implementation=fake_implementation("fixed_policy"),
        provenance={"source": "curated"},
        **shared,
    )
    support_min = OutcomeSupportContract(
        kind="outcome_support_min",
        implementation=fake_implementation("support_min"),
        **shared,
    )
    support_max = OutcomeSupportContract(
        kind="outcome_support_max",
        implementation=fake_implementation("support_max"),
        **{**shared, "direction": "maximize"},
    )

    for references in (
        {
            "optimum_lower_bound": _optimization_contract("optimum_lower_bound"),
            "comparison_baseline": baseline,
        },
        {
            "optimum_lower_bound": _optimization_contract("optimum_lower_bound"),
            "outcome_support_min": support_min,
            "outcome_support_max": support_max,
        },
    ):
        with pytest.raises(ValidationError, match="reference scope"):
            OptimizableOutcomeMeasurementSpec.model_validate(
                {**base, "reference_contracts": references}
            )


def test_measurement_reference_combinations_are_settled_before_execution() -> None:
    base = fake_resolution_inputs().family.measurements[0].model_dump(mode="python")
    lower = _optimization_contract("optimum_lower_bound")
    upper = _optimization_contract("optimum_upper_bound")
    support_min = OutcomeSupportContract(
        kind="outcome_support_min",
        objective_id="buyer_utility",
        objective_version="1.0.0",
        units="utility_points",
        direction="maximize",
        feasible_set="offers permitted by fake_market/1.0.0",
        information_set="buyer-private observation",
        horizon="two offer rounds",
        opponent_condition="fixed counterpart/1.0.0",
        stochastic_expectation="expectation over declared rollout seeds",
        proof_type="analytical support proof",
        implementation=fake_implementation("support_min", marker="c"),
        validity_domain="fake_market/1.0.0 dev split",
        applicability="fake_market/1.0.0 declared estimand",
    )

    with pytest.raises(ValidationError, match="lower.*upper"):
        OptimizableOutcomeMeasurementSpec.model_validate(
            {
                **base,
                "claim_rule": ExactSolvedRule(
                    certification_rule="computed_bound_gap_eq_zero"
                ),
                "reference_contracts": {"optimum_lower_bound": lower},
            }
        )
    with pytest.raises(ValidationError, match="support"):
        OptimizableOutcomeMeasurementSpec.model_validate(
            {
                **base,
                "claim_rule": BracketedRule(
                    certification_rule="certified_lower_le_optimum_le_upper"
                ),
                "reference_contracts": {
                    "optimum_lower_bound": lower,
                    "optimum_upper_bound": upper,
                    "outcome_support_min": support_min,
                },
            }
        )
    with pytest.raises(ValidationError):
        OptimizableOutcomeMeasurementSpec.model_validate(
            {
                **base,
                "claim_rule": {
                    "bound_status": "invented",
                    "certification_rule": "invented",
                },
            }
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
        dict(cell.reference_refs)
        == {
            kind: contract.implementation
            for kind, contract in measurement.reference_contracts.items()
        }
        for cell in plan.cells
    )

    suite_without_cluster = inputs.suite.model_copy(update={"cluster_by_estimand": {}})
    with pytest.raises(InvalidClusterDeclaration):
        resolve_run_plan(_replace(inputs, suite=suite_without_cluster), _registry())


def test_multi_estimand_suite_uses_an_estimand_keyed_cluster_contract() -> None:
    inputs = fake_resolution_inputs()
    second_measurement = PropertyAnswerMeasurementSpec(
        estimand_id="deal_rate",
        measurement_kind="property_or_answer",
        direction="maximize",
        primary_metric_id="deal_rate",
        verifier_plugin_id="fake_verifier",
        verifier_semantics_id="exact_deal_check",
        verifier_semantics_version="1.0.0",
        property_definition_id="terminal_deal",
        property_definition_version="1.0.0",
        answer_schema_ref="boolean_answer/1.0.0",
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


def test_declared_controlled_profile_on_subject_role_must_still_resolve() -> None:
    inputs = fake_resolution_inputs()
    block = inputs.suite.blocks[0].model_copy(
        update={
            "controlled_profile_by_role": {
                "buyer": "ghost",
                "seller": "counterpart",
            }
        }
    )
    suite = inputs.suite.model_copy(update={"blocks": (block,)})

    with pytest.raises(IncompleteAgentAssignment, match="ghost"):
        resolve_run_plan(_replace(inputs, suite=suite), _registry())


def test_unreferenced_agent_profile_is_rejected_before_registry_resolution() -> None:
    inputs = fake_resolution_inputs()
    unused = fake_agent_profile("unused", adapter_id="unregistered_agent")

    with pytest.raises(IncompleteAgentAssignment, match="unreferenced"):
        resolve_run_plan(
            _replace(inputs, agent_profiles=(*inputs.agent_profiles, unused)),
            _registry(),
        )


@pytest.mark.parametrize("alias", ("latest", "current", "default", "stable"))
def test_agent_configuration_rejects_mutable_version_aliases(alias: str) -> None:
    profile = fake_resolution_inputs().agent_profiles[0]
    raw = profile.model_dump(mode="python")
    raw["execution_config"]["model"]["revision"] = alias

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
    raw["execution_config"]["retry_policy"] = {
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


def test_deep_verifier_reconstructs_curated_missing_pair_and_parent_failure() -> None:
    inputs = fake_resolution_inputs()
    cluster = inputs.suite.cluster_by_estimand["buyer_utility"].model_copy(
        update={
            "paired_fields": ("generator_version",),
            "parent_field": "generator_version",
        }
    )
    suite = inputs.suite.model_copy(
        update={"cluster_by_estimand": {"buyer_utility": cluster}}
    )
    plan = resolve_run_plan(_replace(inputs, suite=suite), _registry())

    generated = plan.cases[0]
    case_data = generated.model_dump(
        mode="python", exclude={"content_sha256", "provenance"}
    )
    curated = CaseManifest.from_content(
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
    forged_cells = []
    for cell in plan.cells:
        forged = cell.model_copy(
            update={
                "case_sha256": curated.content_sha256,
                "pairing_values": {"generator_version": None},
                "cluster_parent_value": None,
            }
        )
        basis = forged.model_dump(mode="python", exclude={"cell_id"})
        forged_cells.append(
            forged.model_copy(update={"cell_id": "cell-" + content_sha256(basis)[:24]})
        )
    forged_plan = _rehash_top_level(
        plan.model_copy(
            update={
                "cases": (curated,),
                "case_sha256_by_id": {curated.case_id: curated.content_sha256},
                "cells": tuple(forged_cells),
            }
        )
    )

    assert not verify_run_plan_identity(forged_plan)


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
    ("target", "update"),
    (
        ("plan", {"spec_version": "aeread.run_plan/0.1"}),
        ("cell", {"spec_version": "aeread.episode_cell/0.1"}),
        ("cell", {"record_type": "episode_cell"}),
    ),
)
def test_deep_verifier_rejects_unchecked_retired_plan_identities(
    target: str, update: dict[str, str]
) -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    if target == "plan":
        forged = _rehash_top_level(plan.model_copy(update=update))
    else:
        forged_cell = plan.cells[0].model_copy(update=update)
        forged = _rehash_top_level(
            plan.model_copy(update={"cells": (forged_cell, *plan.cells[1:])})
        )

    assert not verify_run_plan_identity(forged)


_MISSING_IDENTITY_FIELD = object()


@pytest.mark.parametrize(
    ("target", "field", "replacement"),
    (
        ("cell", "record_type", "episode_cell"),
        ("cell", "record_type", _MISSING_IDENTITY_FIELD),
        ("cell", "spec_version", "aeread.episode_cell/0.1"),
        ("cell", "spec_version", _MISSING_IDENTITY_FIELD),
        ("plan", "spec_version", "aeread.run_plan/0.1"),
        ("plan", "spec_version", _MISSING_IDENTITY_FIELD),
    ),
)
def test_model_construct_plan_identity_bypasses_fail_closed(
    target: str, field: str, replacement: object
) -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())
    plan_state = dict(vars(plan))

    if target == "cell":
        cell = plan.cells[0]
        cell_state = dict(vars(cell))
        if replacement is _MISSING_IDENTITY_FIELD:
            cell_state.pop(field)
        else:
            cell_state[field] = replacement
        pending_cell = type(cell).model_construct(**cell_state)
        cell_basis = pending_cell.model_dump(
            mode="python", exclude={"cell_id"}, warnings=False
        )
        cell_digest = content_sha256(cell_basis)
        cell_state["cell_id"] = "cell-" + cell_digest[:24]
        forged_cell = type(cell).model_construct(**cell_state)
        plan_state["cells"] = (forged_cell, *plan.cells[1:])
        identity_holder = forged_cell
    else:
        if replacement is _MISSING_IDENTITY_FIELD:
            plan_state.pop(field)
        else:
            plan_state[field] = replacement
        identity_holder = None

    pending = type(plan).model_construct(**plan_state)
    basis = pending.model_dump(
        mode="python",
        exclude={"run_plan_id", "run_plan_sha256"},
        warnings=False,
    )
    digest = content_sha256(basis)
    plan_state.update(
        {
            "run_plan_id": "runplan-" + digest[:24],
            "run_plan_sha256": digest,
        }
    )
    forged = type(plan).model_construct(**plan_state)
    if target == "plan":
        identity_holder = forged
    else:
        forged_cell_basis = identity_holder.model_dump(
            mode="python", exclude={"cell_id"}, warnings=False
        )
        assert identity_holder.cell_id == (
            "cell-" + content_sha256(forged_cell_basis)[:24]
        )

    if replacement is _MISSING_IDENTITY_FIELD:
        assert not hasattr(identity_holder, field)
    else:
        assert getattr(identity_holder, field) == replacement
    assert not verify_run_plan_identity(forged)


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
