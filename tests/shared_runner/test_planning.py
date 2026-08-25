from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from aeread.runner.planning import (
    ADMISSION_REQUIREMENTS,
    CapabilityMismatch,
    ContentHashMismatch,
    IncompleteAgentAssignment,
    InvalidClusterDeclaration,
    ManifestMismatch,
    UnresolvedImplementation,
    evaluate_admission,
    resolve_run_plan,
    verify_run_plan_identity,
)
from aeread.runner.registry import PluginRegistry
from aeread.sdk.v1 import (
    AgentProfile,
    CapabilityDeclaration,
    CaseManifest,
    CaseProvenance,
    FamilyManifest,
    PinnedPluginRef,
    ResolutionInputs,
    RetryPolicy,
    UpstreamSourceRef,
    content_sha256,
)

from .fakes import (
    FakeAgentAdapter,
    FakeEnvironment,
    FakeExecutionBackend,
    FakeVerifier,
    fake_agent_profile,
    fake_implementation,
    fake_resolution_inputs,
)


def _registry() -> PluginRegistry:
    return PluginRegistry.from_objects(
        environments=[FakeEnvironment()],
        verifiers=[FakeVerifier()],
        agent_adapters=[FakeAgentAdapter()],
        execution_backends=[FakeExecutionBackend()],
    )


def _replace(inputs: ResolutionInputs, **updates: object) -> ResolutionInputs:
    return inputs.model_copy(update=updates)


def test_manifest_versions_unknown_fields_and_nested_values_are_strict() -> None:
    inputs = fake_resolution_inputs()

    with pytest.raises(ValidationError):
        FamilyManifest.model_validate(
            {
                **inputs.family.model_dump(mode="python"),
                "spec_version": "aeread.family/9",
            }
        )
    with pytest.raises(ValidationError):
        FamilyManifest.model_validate(
            {**inputs.family.model_dump(mode="python"), "unknown": True}
        )
    with pytest.raises(ValidationError):
        type(inputs.family.roles[0]).model_validate(
            {**inputs.family.roles[0].model_dump(mode="python"), "unknown": True}
        )

    with pytest.raises(TypeError):
        inputs.family.limits["max_rounds"] = 9
    with pytest.raises(TypeError):
        inputs.run_spec.subject_profile_by_role["buyer"] = "other"


@pytest.mark.parametrize(
    ("manifest", "wrong_version"),
    (
        (lambda inputs: inputs.family, "aeread.family/9"),
        (lambda inputs: inputs.cases[0], "aeread.case/9"),
        (lambda inputs: inputs.suite, "aeread.suite/9"),
        (lambda inputs: inputs.agent_profiles[0], "aeread.agent_profile/9"),
        (lambda inputs: inputs.run_spec, "aeread.run/9"),
        (
            lambda inputs: resolve_run_plan(inputs, _registry()),
            "aeread.run_plan/9",
        ),
    ),
)
def test_every_manifest_rejects_the_wrong_own_spec_version(
    manifest, wrong_version: str
) -> None:
    record = manifest(fake_resolution_inputs())
    raw = record.model_dump(mode="python")
    raw["spec_version"] = wrong_version
    with pytest.raises(ValidationError, match="spec_version"):
        type(record).model_validate(raw)


def test_case_factory_computes_hash_and_manifest_rejects_tampering() -> None:
    case = fake_resolution_inputs().cases[0]
    assert len(case.content_sha256) == 64

    raw = case.model_dump(mode="python")
    raw["content_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="content_sha256"):
        CaseManifest.model_validate(raw)


def test_nested_manifest_identifiers_and_versions_cannot_be_empty_or_floating() -> None:
    case = fake_resolution_inputs().cases[0]
    raw_case = case.model_dump(mode="python", exclude={"content_sha256"})
    raw_case["terminal_reasons"] = ("deal", "")
    with pytest.raises(ValidationError, match="terminal_reasons"):
        CaseManifest.from_content(**raw_case)

    suite = fake_resolution_inputs().suite
    with pytest.raises(ValidationError, match="case_id"):
        type(suite).model_validate(
            {**suite.model_dump(mode="python"), "case_ids": ("",)}
        )

    with pytest.raises(ValidationError, match="generator_version"):
        CaseProvenance(
            source_kind="generated",
            generator_id="generator",
            generator_version="latest",
            review_status="curated",
        )


def test_pinned_plugin_requires_matching_implementation_identity() -> None:
    with pytest.raises(ValidationError, match="implementation"):
        PinnedPluginRef(
            plugin={"plugin_id": "fake_market", "plugin_version": "1.0.0"},
            implementation=fake_implementation("different"),
        )


def test_upstream_source_requires_real_repository_url_and_artifact_hashes() -> None:
    with pytest.raises(ValidationError, match="repository_url"):
        UpstreamSourceRef(
            repository_url="not-a-url",
            commit="a" * 40,
            license_spdx="MIT",
            source_paths=("src",),
        )
    with pytest.raises(ValidationError, match="artifact"):
        UpstreamSourceRef(
            repository_url="https://example.com/org/repo",
            commit="a" * 40,
            license_spdx="MIT",
            source_paths=("src",),
            materialized_artifact_hashes={"cases.json": "unpinned"},
        )


@pytest.mark.parametrize(
    ("axis", "bad_value"),
    (
        ("schedule_control", "upstream"),
        ("observation_visibility", "opaque"),
        ("call_observability", "logical_only"),
        ("state_replay", "score_only"),
        ("score_parity", "statistical"),
        ("privacy_enforcement", "upstream"),
    ),
)
def test_paper_admission_rejects_every_required_axis(axis: str, bad_value: str) -> None:
    capabilities = fake_resolution_inputs().family.capabilities.model_copy(
        update={axis: bad_value}
    )

    report = evaluate_admission(capabilities, "paper_primary")

    assert report.status == "rejected"
    failed = {check.axis for check in report.checks if not check.passed}
    assert failed == {axis}


def test_training_requires_per_seat_and_interop_accepts_disclosed_limits() -> None:
    capabilities = CapabilityDeclaration(
        schedule_control="opaque",
        observation_visibility="opaque",
        call_observability="opaque",
        state_replay="none",
        score_parity="none",
        privacy_enforcement="unverified",
        trainability="none",
    )
    assert evaluate_admission(capabilities, "interop_only").status == "admitted"

    training_caps = fake_resolution_inputs().family.capabilities.model_copy(
        update={"trainability": "joint_only"}
    )
    report = evaluate_admission(training_caps, "training")
    assert report.status == "rejected"
    assert {check.axis for check in report.checks if not check.passed} == {
        "trainability"
    }
    assert tuple(ADMISSION_REQUIREMENTS) == (
        "paper_primary",
        "training",
        "interop_only",
    )
    with pytest.raises(TypeError):
        ADMISSION_REQUIREMENTS["paper_primary"] = {}  # type: ignore[index]


def test_resolver_pins_sorted_cells_and_complete_seat_assignments() -> None:
    plan = resolve_run_plan(fake_resolution_inputs(), _registry())

    assert len(plan.cells) == 4
    assert [cell.rollout_seed for cell in plan.cells] == [3, 7, 3, 7]
    assert [cell.repetition_index for cell in plan.cells] == [0, 0, 1, 1]
    assert all(cell.subject_seat_id == "buyer-1" for cell in plan.cells)
    assert all(
        dict(cell.seat_profile_id_by_seat)
        == {"buyer-1": "candidate", "seller-1": "counterpart"}
        for cell in plan.cells
    )
    assert all(cell.environment_ref.version == "1.0.0" for cell in plan.cells)
    assert all(
        cell.verifier_ref.implementation_id == "fake_verifier" for cell in plan.cells
    )
    assert all(cell.observations_per_cluster == 4 for cell in plan.cells)
    assert all(
        dict(cell.pairing_values) == {"rollout_seed": cell.rollout_seed}
        for cell in plan.cells
    )
    assert plan.admission_report.status == "admitted"
    assert verify_run_plan_identity(plan)

    raw_plan = plan.model_dump(mode="python")
    raw_plan["agent_profile_sha256_by_id"] = {"candidate": "not-a-hash"}
    with pytest.raises(ValidationError, match="agent_profile_sha256_by_id"):
        type(plan).model_validate(raw_plan)


def test_resolution_is_order_independent_but_identity_sensitive() -> None:
    inputs = fake_resolution_inputs()
    first = resolve_run_plan(inputs, _registry())
    original_case = inputs.cases[0]
    reordered_case_data = original_case.model_dump(
        mode="python", exclude={"content_sha256"}
    )
    reordered_case_data["seats"] = tuple(reversed(original_case.seats))
    reordered_case_data["terminal_reasons"] = tuple(
        reversed(original_case.terminal_reasons)
    )
    reordered_case = CaseManifest.from_content(**reordered_case_data)
    reordered_block = inputs.suite.blocks[0].model_copy(
        update={"rollout_seeds": tuple(sorted(inputs.suite.blocks[0].rollout_seeds))}
    )
    reordered = _replace(
        inputs,
        family=inputs.family.model_copy(
            update={"roles": tuple(reversed(inputs.family.roles))}
        ),
        cases=(reordered_case,),
        agent_profiles=tuple(reversed(inputs.agent_profiles)),
        suite=inputs.suite.model_copy(
            update={
                "case_ids": tuple(reversed(inputs.suite.case_ids)),
                "blocks": (reordered_block,),
            }
        ),
    )
    second = resolve_run_plan(reordered, _registry())
    assert second.run_plan_id == first.run_plan_id
    assert second.run_plan_sha256 == first.run_plan_sha256
    assert second.cells == first.cells

    changed_config = inputs.agent_profiles[0].execution_config.model_copy(
        update={
            "prompt": "A materially different candidate prompt.",
            "prompt_sha256": content_sha256("A materially different candidate prompt."),
        }
    )
    changed_profile = inputs.agent_profiles[0].model_copy(
        update={"execution_config": changed_config}
    )
    changed = resolve_run_plan(
        _replace(
            inputs,
            agent_profiles=(changed_profile, inputs.agent_profiles[1]),
        ),
        _registry(),
    )
    assert changed.run_plan_sha256 != first.run_plan_sha256
    assert {cell.cell_id for cell in changed.cells} != {
        cell.cell_id for cell in first.cells
    }

    changed_case_data = original_case.model_dump(
        mode="python", exclude={"content_sha256"}
    )
    changed_case_data["payload"] = {"reserve": 4}
    changed_case = CaseManifest.from_content(**changed_case_data)
    changed_environment = inputs.family.environment.model_copy(
        update={
            "implementation": inputs.family.environment.implementation.model_copy(
                update={"content_sha256": "8" * 64}
            )
        }
    )
    changed_cluster = inputs.suite.cluster_by_estimand["buyer_utility"].model_copy(
        update={"identity_fields": ("case_id", "world_seed", "rollout_seed")}
    )
    variants = (
        _replace(inputs, cases=(changed_case,)),
        _replace(
            inputs,
            family=inputs.family.model_copy(
                update={"environment": changed_environment}
            ),
        ),
        _replace(
            inputs,
            suite=inputs.suite.model_copy(
                update={"cluster_by_estimand": {"buyer_utility": changed_cluster}}
            ),
        ),
    )
    for variant in variants:
        variant_plan = resolve_run_plan(variant, _registry())
        assert variant_plan.run_plan_sha256 != first.run_plan_sha256
        assert {cell.cell_id for cell in variant_plan.cells} != {
            cell.cell_id for cell in first.cells
        }


def test_resolver_rejects_incomplete_or_ambiguous_seat_assignment() -> None:
    inputs = fake_resolution_inputs()
    block = inputs.suite.blocks[0].model_copy(update={"controlled_profile_by_role": {}})
    suite = inputs.suite.model_copy(update={"blocks": (block,)})

    with pytest.raises(IncompleteAgentAssignment):
        resolve_run_plan(_replace(inputs, suite=suite), _registry())


def test_resolver_rejects_phase_schema_roles_absent_from_family() -> None:
    inputs = fake_resolution_inputs()
    phase = inputs.family.phase_graph.phases[0].model_copy(
        update={"observation_schema_by_role": {"ghost": "obs/1"}}
    )
    graph = inputs.family.phase_graph.model_copy(update={"phases": (phase,)})
    family = inputs.family.model_copy(update={"phase_graph": graph})

    with pytest.raises(ManifestMismatch, match="phase"):
        resolve_run_plan(_replace(inputs, family=family), _registry())


@pytest.mark.parametrize(
    "profile",
    (
        lambda profile: profile.model_copy(
            update={
                "execution_config": profile.execution_config.model_copy(
                    update={"model": ""}
                )
            }
        ),
        lambda profile: profile.model_copy(
            update={
                "execution_config": profile.execution_config.model_copy(
                    update={"prompt_sha256": "unpinned"}
                )
            }
        ),
        lambda profile: profile.model_copy(
            update={
                "execution_config": profile.execution_config.model_copy(
                    update={
                        "retry_policy": RetryPolicy(
                            max_attempts=2,
                            retryable_conditions=("length",),
                            length_retry_output_tokens=32,
                        )
                    }
                )
            }
        ),
    ),
)
def test_resolver_revalidates_rejected_model_prompt_and_retry_profiles(profile) -> None:
    inputs = fake_resolution_inputs()
    invalid = profile(inputs.agent_profiles[0])
    with pytest.raises(ManifestMismatch):
        resolve_run_plan(
            _replace(inputs, agent_profiles=(invalid, inputs.agent_profiles[1])),
            _registry(),
        )


def test_length_retry_requires_declared_condition_attempt_and_larger_budget() -> None:
    base = fake_agent_profile("candidate")
    raw = base.model_dump(mode="python")
    raw["execution_config"]["retry_policy"] = {
        "max_attempts": 1,
        "retryable_conditions": ("length",),
        "length_retry_output_tokens": 128,
    }
    with pytest.raises(ValidationError, match="length"):
        AgentProfile.model_validate(raw)

    raw = base.model_dump(mode="python")
    raw["execution_config"]["retry_policy"] = {
        "max_attempts": 2,
        "retryable_conditions": (),
        "length_retry_output_tokens": 128,
    }
    with pytest.raises(ValidationError, match="length"):
        AgentProfile.model_validate(raw)


def test_cluster_rejects_unknown_field_and_missing_parent_value() -> None:
    inputs = fake_resolution_inputs()
    bad_cluster = inputs.suite.cluster_by_estimand["buyer_utility"].model_copy(
        update={"identity_fields": ("case_id", "unknown_field")}
    )
    with pytest.raises(InvalidClusterDeclaration):
        resolve_run_plan(
            _replace(
                inputs,
                suite=inputs.suite.model_copy(
                    update={"cluster_by_estimand": {"buyer_utility": bad_cluster}}
                ),
            ),
            _registry(),
        )

    missing_parent = inputs.suite.cluster_by_estimand["buyer_utility"].model_copy(
        update={"parent_field": "not_available"}
    )
    with pytest.raises(InvalidClusterDeclaration):
        resolve_run_plan(
            _replace(
                inputs,
                suite=inputs.suite.model_copy(
                    update={"cluster_by_estimand": {"buyer_utility": missing_parent}}
                ),
            ),
            _registry(),
        )


def test_unchecked_case_copy_and_nested_manifest_copy_are_revalidated() -> None:
    inputs = fake_resolution_inputs()
    tampered_case = inputs.cases[0].model_copy(update={"payload": {"reserve": 99}})
    with pytest.raises(ContentHashMismatch):
        resolve_run_plan(_replace(inputs, cases=(tampered_case,)), _registry())

    invalid_caps = inputs.family.capabilities.model_copy(
        update={"call_observability": "invented"}
    )
    invalid_family = inputs.family.model_copy(update={"capabilities": invalid_caps})
    with pytest.raises(ManifestMismatch):
        resolve_run_plan(_replace(inputs, family=invalid_family), _registry())

    with pytest.raises(ManifestMismatch):
        resolve_run_plan(_replace(inputs, cases=None), _registry())

    unsafe_plugin = inputs.agent_profiles[0].adapter.plugin.model_copy(
        update={"plugin_id": "package.module:agent"}
    )
    unsafe_adapter = inputs.agent_profiles[0].adapter.model_copy(
        update={"plugin": unsafe_plugin}
    )
    unsafe_profile = inputs.agent_profiles[0].model_copy(
        update={"adapter": unsafe_adapter}
    )
    with pytest.raises(ManifestMismatch):
        resolve_run_plan(
            _replace(
                inputs,
                agent_profiles=(unsafe_profile, inputs.agent_profiles[1]),
            ),
            _registry(),
        )


def test_registry_failures_and_pin_mismatches_are_normalized() -> None:
    inputs = fake_resolution_inputs()
    with pytest.raises(UnresolvedImplementation) as exc_info:
        resolve_run_plan(inputs, PluginRegistry.from_objects())
    assert exc_info.value.__cause__ is not None

    bad_impl = inputs.family.environment.implementation.model_copy(
        update={"version": "2.0.0"}
    )
    bad_pin = inputs.family.environment.model_copy(update={"implementation": bad_impl})
    bad_family = inputs.family.model_copy(update={"environment": bad_pin})
    with pytest.raises(ManifestMismatch):
        resolve_run_plan(_replace(inputs, family=bad_family), _registry())


def test_capability_rejection_carries_full_report_without_downgrade() -> None:
    inputs = fake_resolution_inputs()
    capabilities = inputs.family.capabilities.model_copy(
        update={"call_observability": "logical_only", "state_replay": "score_only"}
    )
    family = inputs.family.model_copy(update={"capabilities": capabilities})

    with pytest.raises(CapabilityMismatch) as exc_info:
        resolve_run_plan(_replace(inputs, family=family), _registry())

    assert exc_info.value.report.requested_profile == "paper_primary"
    assert (
        len(
            [
                check
                for check in exc_info.value.report.checks
                if check.profile_id is None
            ]
        )
        == 7
    )
    assert {
        check.axis for check in exc_info.value.report.checks if not check.passed
    } == {
        "call_observability",
        "state_replay",
    }


def test_planning_does_not_call_plugin_hooks_or_import_family_modules() -> None:
    class NoHookEnvironment(FakeEnvironment):
        def phase_graph(self, case: object):
            raise AssertionError("planning called environment hook")

    registry = PluginRegistry.from_objects(
        environments=[NoHookEnvironment()],
        verifiers=[FakeVerifier()],
        agent_adapters=[FakeAgentAdapter()],
        execution_backends=[FakeExecutionBackend()],
    )
    resolve_run_plan(fake_resolution_inputs(), registry)

    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import aeread.runner.planning; "
                "assert 'aeread.exchange_economy' not in sys.modules"
            ),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr
