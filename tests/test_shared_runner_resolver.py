from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import (
    ImplementationPin,
    PlanResolutionError,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
    verify_run_plan,
    write_run_plan,
)
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)


PROMPT_SHA = "b" * 64


class HousingFixturePlugin:
    def __init__(self, *, reject_payload: bool = False) -> None:
        self.reject_payload = reject_payload
        self.validated_case_ids: list[str] = []

    def validate_payload(self, payload):
        if self.reject_payload:
            raise ValueError("invalid housing payload")
        self.validated_case_ids.append(str(payload["case_marker"]))
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


def _family() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
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
                "tenant": {"testable": True},
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
                "difficulty_knobs": ["market_tightness"],
            },
        }
    )


def _case(case_number: int, world_seed: int) -> CaseManifest:
    data = {
        "spec_version": "aeread.case/0.1",
        "case_id": f"housing_v1__dev__{case_number:06d}",
        "family_id": "housing_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": world_seed,
        "seats": [
            {"id": "tenant_0", "role": "tenant"},
            {"id": "landlord_0", "role": "landlord"},
        ],
        "episode": {
            "max_logical_actions": 8,
            "termination": ["allocation", "withdrawal", "deadline", "forfeit"],
        },
        "visibility_policy": "housing_private_preferences_v1",
        "payload": {"case_marker": f"case-{case_number}", "listings": []},
        "provenance": {
            "generator_id": "housing_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    data["content_sha256"] = case_content_sha256(data)
    return CaseManifest.from_dict(data)


def _sampling() -> SamplingPlan:
    return SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": "housing_sample_v1",
            "estimand": "generated_housing_case_population",
            "target": "housing_generator_v1",
            "selection": "seeded_generator",
            "seeds": [51, 52],
            "replicates": 2,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": ["world_seed", "subject_profile"],
            "replicate_level": "episode_attempt",
            "panel_mode": "sampled_panel",
        }
    )


def _block() -> EvaluationBlock:
    return EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": "controlled_fixed_counterpart",
            "kind": "controlled",
            "subject_seats": ["tenant_0"],
            "controlled_profiles": {"landlord_0": "fixed_landlord_v1"},
            "repetitions": 2,
            "seed_policy": "paired",
        }
    )


def _analysis() -> AnalysisPlan:
    return AnalysisPlan.from_dict(
        {
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
    )


def _profile(profile_id: str, *, scripted: bool) -> AgentProfile:
    if scripted:
        model = {"provider": "aeread", "model": "fixed_landlord_v1", "revision": "1.0.0"}
        harness = {"id": "scripted", "version": "1.0", "config": {}}
        runtime = {
            "kind": "python",
            "implementation": "aeread.fixed_policy",
            "version": "1.0.0",
        }
    else:
        model = {"provider": "openai", "model": "test-model", "revision": "pinned"}
        harness = {"id": "minimal_chat", "version": "1.0", "config": {}}
        runtime = {
            "kind": "python",
            "implementation": "aeread.gateway_candidate",
            "version": "1.0.0",
        }
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": profile_id,
            "model": model,
            "harness": harness,
            "prompt": {"prompt_id": f"{profile_id}_prompt", "sha256": PROMPT_SHA},
            "runtime": runtime,
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "declared_v1",
                "effort": None if scripted else "low",
                "token_budget": None,
                "rationale_visibility": "unavailable" if scripted else "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 200,
                "seed": 7,
            },
            "budgets": {
                "max_logical_actions": 8,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.10,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "continue",
                "sdk_retries": 0,
            },
        }
    )


def _pin(component_id: str, kind: str) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": "1.0.0",
            "sha256": hashlib.sha256(component_id.encode("utf-8")).hexdigest(),
        }
    )


def _inputs(*, plugin: HousingFixturePlugin | None = None) -> dict:
    family = _family()
    cases = (_case(1, 41001), _case(2, 41002))
    block = _block()
    profiles = (
        _profile("subject_model_v1", scripted=False),
        _profile("fixed_landlord_v1", scripted=True),
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": "housing_dev_v1",
            "version": "1.0.0",
            "family_ids": ["housing_v1"],
            "case_ids": [case.case_id for case in cases],
            "sampling_plan_id": "housing_sample_v1",
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": "housing_primary_v1",
        }
    )
    run = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": "housing_subject_dev_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id for profile in profiles],
            "seat_assignments": {
                "tenant_0": "subject_model_v1",
                "landlord_0": "fixed_landlord_v1",
            },
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    plugin = plugin or HousingFixturePlugin()
    registry = PluginRegistry()
    registry.register(family, plugin)
    pins = (
        _pin("aeread.housing_v1", "family_plugin"),
        _pin("housing_outcome_v1", "scorer"),
        _pin("housing_exact_assignment_v1", "reference"),
        _pin("housing_scripted_search_v1", "reference"),
        _pin("housing_generator_v1", "generator"),
        _pin("minimal_chat", "harness"),
        _pin("scripted", "harness"),
        _pin("aeread.gateway_candidate", "runtime"),
        _pin("aeread.fixed_policy", "runtime"),
    )
    return {
        "families": (family,),
        "cases": cases,
        "suite": suite,
        "sampling": _sampling(),
        "evaluation_blocks": (block,),
        "analysis": _analysis(),
        "agent_profiles": profiles,
        "run_spec": run,
        "registry": registry,
        "implementation_pins": pins,
    }


def test_resolver_produces_identical_canonical_plan_for_identical_inputs() -> None:
    inputs = _inputs()
    first = resolve_run_plan(**inputs)

    reordered = dict(inputs)
    reordered["cases"] = tuple(reversed(inputs["cases"]))
    reordered["agent_profiles"] = tuple(reversed(inputs["agent_profiles"]))
    reordered["implementation_pins"] = tuple(reversed(inputs["implementation_pins"]))
    second = resolve_run_plan(**reordered)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first.plan_sha256 == second.plan_sha256
    assert first.run_plan_id == f"runplan_{first.plan_sha256[:16]}"
    verify_run_plan(first)


def test_resolver_expands_cells_and_records_cluster_nesting() -> None:
    plan = resolve_run_plan(**_inputs())

    # 2 cases x 2 sampling seeds x 2 block repetitions x 2 nested replicates.
    assert len(plan.cells) == 16
    assert len({cell.cell_id for cell in plan.cells}) == 16
    by_cluster: dict[str, list] = {}
    for cell in plan.cells:
        by_cluster.setdefault(cell.cluster_id, []).append(cell)
        assert cell.cluster_level == "world_seed"
        assert cell.panel_mode == "sampled_panel"
        assert cell.profile_by_seat == {
            "tenant_0": "subject_model_v1",
            "landlord_0": "fixed_landlord_v1",
        }
        assert cell.paired_fields["subject_profile"] == "subject_model_v1"

    assert len(by_cluster) == 2
    assert {cell.observations_per_cluster for cell in plan.cells} == {8}
    assert all(len(cells) == 8 for cells in by_cluster.values())


def test_resolver_validates_case_hashes_before_calling_family_plugin() -> None:
    plugin = HousingFixturePlugin()
    inputs = _inputs(plugin=plugin)
    damaged = dict(inputs)
    case = inputs["cases"][0]
    object.__setattr__(case, "content_sha256", "f" * 64)

    with pytest.raises(PlanResolutionError, match="content_sha256"):
        resolve_run_plan(**damaged)
    assert plugin.validated_case_ids == []


def test_resolver_runs_family_payload_preflight_and_wraps_failures() -> None:
    plugin = HousingFixturePlugin(reject_payload=True)
    with pytest.raises(PlanResolutionError, match="validate_payload"):
        resolve_run_plan(**_inputs(plugin=plugin))


def test_resolver_requires_every_referenced_implementation_pin() -> None:
    inputs = _inputs()
    inputs["implementation_pins"] = tuple(
        pin for pin in inputs["implementation_pins"] if pin.component_id != "housing_outcome_v1"
    )
    with pytest.raises(PlanResolutionError, match="housing_outcome_v1"):
        resolve_run_plan(**inputs)


def test_resolver_rejects_cross_record_reference_mismatch() -> None:
    inputs = _inputs()
    bad_suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": "housing_dev_v1",
            "version": "1.0.0",
            "family_ids": ["housing_v1"],
            "case_ids": ["missing_case"],
            "sampling_plan_id": "housing_sample_v1",
            "evaluation_block_ids": ["controlled_fixed_counterpart"],
            "analysis_plan_id": "housing_primary_v1",
        }
    )
    inputs["suite"] = bad_suite
    with pytest.raises(PlanResolutionError, match="missing_case"):
        resolve_run_plan(**inputs)


def test_write_run_plan_is_canonical_durable_and_refuses_overwrite(tmp_path: Path) -> None:
    plan = resolve_run_plan(**_inputs())
    destination = tmp_path / "run_plan.json"

    write_run_plan(plan, destination)
    assert destination.read_bytes() == canonical_json_bytes(plan)
    with pytest.raises(FileExistsError):
        write_run_plan(plan, destination)
