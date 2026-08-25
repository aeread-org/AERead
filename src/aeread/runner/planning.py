"""Pure manifest admission and deterministic RunPlan resolution."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, cast

from pydantic import BaseModel, ValidationError

from aeread.sdk.v1.base import content_sha256
from aeread.sdk.v1.errors import SDKError
from aeread.sdk.v1.records import (
    AdmissionCheck,
    AdmissionReport,
    AgentProfile,
    CapabilityDeclaration,
    CaseManifest,
    ComparativeMeasurementSpec,
    EpisodeCell,
    FamilyManifest,
    ImplementationRef,
    MeasurementSpec,
    OptimizableOutcomeMeasurementSpec,
    ResolutionInputs,
    RunPlan,
    RunSpec,
    SuiteManifest,
)

from .registry import PluginRegistry, PluginRegistryError


AdmissionProfile = Literal["paper_primary", "training", "interop_only"]


class PlanningError(Exception):
    """Base class for deterministic planning failures."""


class ManifestMismatch(PlanningError):
    """Manifests are invalid or disagree across identity boundaries."""


class ContentHashMismatch(ManifestMismatch):
    """A case's stored digest does not match its canonical content."""


class CapabilityMismatch(PlanningError):
    """Requested admission profile is not supported by declared capabilities."""

    def __init__(self, report: AdmissionReport) -> None:
        self.report = report
        failed = tuple(check.axis for check in report.checks if not check.passed)
        super().__init__(
            f"capabilities reject {report.requested_profile!r}: {failed!r}"
        )


class IncompleteAgentAssignment(PlanningError):
    """A planned subject or controlled seat has no unique agent profile."""


class UnresolvedImplementation(PlanningError):
    """A pinned implementation cannot be resolved by the trusted registry."""


class InvalidClusterDeclaration(PlanningError):
    """A suite requests an unsupported or unavailable cluster field."""


_CAPABILITY_VALUES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "schedule_control": ("runner", "upstream", "opaque"),
        "observation_visibility": ("full", "partial", "opaque"),
        "call_observability": ("full", "logical_only", "opaque"),
        "state_replay": ("deterministic", "score_only", "none"),
        "score_parity": ("exact", "component", "statistical", "none"),
        "privacy_enforcement": ("runner", "upstream", "unverified"),
        "trainability": ("per_seat", "joint_only", "none"),
    }
)

_PAPER_REQUIREMENTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "schedule_control": ("runner",),
        "observation_visibility": ("full", "partial"),
        "call_observability": ("full",),
        "state_replay": ("deterministic",),
        "score_parity": ("exact", "component"),
        "privacy_enforcement": ("runner",),
        "trainability": _CAPABILITY_VALUES["trainability"],
    }
)

ADMISSION_REQUIREMENTS: Mapping[
    AdmissionProfile, Mapping[str, tuple[str, ...]]
] = MappingProxyType(
    {
        "paper_primary": _PAPER_REQUIREMENTS,
        "training": MappingProxyType(
            {**_PAPER_REQUIREMENTS, "trainability": ("per_seat",)}
        ),
        "interop_only": MappingProxyType(dict(_CAPABILITY_VALUES)),
    }
)

SUPPORTED_CLUSTER_FIELDS = frozenset(
    {
        "family_id",
        "family_version",
        "case_id",
        "world_seed",
        "generator_version",
        "block_id",
        "subject_role",
        "subject_seat_id",
        "subject_profile_id",
        "rollout_seed",
    }
)


def evaluate_admission(
    capabilities: CapabilityDeclaration, profile: AdmissionProfile
) -> AdmissionReport:
    """Evaluate all seven capability axes without fallback or downgrade."""

    requirements = ADMISSION_REQUIREMENTS[profile]
    checks = tuple(
        AdmissionCheck(
            axis=axis,
            actual_value=cast(str, getattr(capabilities, axis)),
            allowed_values=allowed,
            passed=getattr(capabilities, axis) in allowed,
        )
        for axis, allowed in requirements.items()
    )
    return AdmissionReport(
        requested_profile=profile,
        status="admitted" if all(check.passed for check in checks) else "rejected",
        checks=checks,
    )


def _evaluate_resolved_admission(
    capabilities: CapabilityDeclaration,
    admission_profile: AdmissionProfile,
    profiles: Mapping[str, AgentProfile],
    adapter_observability: Mapping[str, str],
) -> AdmissionReport:
    family_report = evaluate_admission(capabilities, admission_profile)
    checks = list(family_report.checks)
    admission_allowed = (
        ("full",)
        if admission_profile in {"paper_primary", "training"}
        else ("full", "logical_only", "opaque")
    )
    for profile_id in sorted(adapter_observability):
        profile = profiles.get(profile_id)
        if profile is None:
            raise IncompleteAgentAssignment(
                f"adapter metadata references unknown profile {profile_id!r}"
            )
        actual = adapter_observability[profile_id]
        checks.extend(
            (
                AdmissionCheck(
                    axis="agent_adapter.call_observability.pin",
                    actual_value=actual,
                    allowed_values=(profile.call_observability,),
                    passed=actual == profile.call_observability,
                    profile_id=profile_id,
                ),
                AdmissionCheck(
                    axis="agent_adapter.call_observability.admission",
                    actual_value=actual,
                    allowed_values=admission_allowed,
                    passed=actual in admission_allowed,
                    profile_id=profile_id,
                ),
            )
        )
    return AdmissionReport(
        requested_profile=admission_profile,
        status="admitted" if all(check.passed for check in checks) else "rejected",
        checks=tuple(checks),
    )


def _raw_state(value: object) -> object:
    """Expose copied Pydantic state so unchecked model_copy updates are seen."""

    if isinstance(value, BaseModel):
        raw = dict(vars(value))
        extra = getattr(value, "__pydantic_extra__", None)
        if extra:
            raw.update(extra)
        return {key: _raw_state(item) for key, item in raw.items()}
    if isinstance(value, Mapping):
        return {key: _raw_state(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_raw_state(item) for item in value)
    return value


def _validate_model(model_type: type[BaseModel], value: object) -> BaseModel:
    try:
        return model_type.model_validate(_raw_state(value))
    except (ValidationError, SDKError) as exc:
        raise ManifestMismatch(f"invalid {model_type.__name__}: {exc}") from exc


def _revalidate_inputs(inputs: ResolutionInputs) -> ResolutionInputs:
    raw = _raw_state(inputs)
    if not isinstance(raw, dict):
        raise ManifestMismatch("ResolutionInputs must be an object")
    expected = {
        "family",
        "cases",
        "suite",
        "agent_profiles",
        "run_spec",
        "spec_version",
    }
    if set(raw) != expected:
        raise ManifestMismatch("ResolutionInputs has missing or unknown fields")

    family = cast(FamilyManifest, _validate_model(FamilyManifest, raw["family"]))
    try:
        suite = cast(SuiteManifest, _validate_model(SuiteManifest, raw["suite"]))
    except ManifestMismatch as exc:
        if "cluster" in str(exc):
            raise InvalidClusterDeclaration(str(exc)) from exc
        raise
    run_spec = cast(RunSpec, _validate_model(RunSpec, raw["run_spec"]))
    raw_profiles = raw["agent_profiles"]
    raw_cases = raw["cases"]
    if not isinstance(raw_profiles, (tuple, list)) or not isinstance(
        raw_cases, (tuple, list)
    ):
        raise ManifestMismatch("cases and agent_profiles must be sequences")
    profiles = tuple(
        cast(AgentProfile, _validate_model(AgentProfile, profile))
        for profile in raw_profiles
    )

    cases: list[CaseManifest] = []
    for case in raw_cases:
        try:
            cases.append(CaseManifest.model_validate(case))
        except ValidationError as exc:
            if "content_sha256" in str(exc):
                raise ContentHashMismatch(str(exc)) from exc
            raise ManifestMismatch(f"invalid CaseManifest: {exc}") from exc

    try:
        return ResolutionInputs.model_validate(
            {
                "spec_version": raw["spec_version"],
                "family": family,
                "cases": tuple(cases),
                "suite": suite,
                "agent_profiles": profiles,
                "run_spec": run_spec,
            }
        )
    except ValidationError as exc:
        raise ManifestMismatch(f"invalid ResolutionInputs: {exc}") from exc


def _family_hash(family: FamilyManifest) -> str:
    basis = family.model_dump(mode="python")
    basis["verifiers"] = sorted(
        basis["verifiers"],
        key=lambda item: (
            item["plugin"]["plugin_id"],
            item["plugin"]["plugin_version"],
        ),
    )
    basis["roles"] = sorted(basis["roles"], key=lambda item: item["role_id"])
    for role in basis["roles"]:
        role["controlled_profile_ids"] = sorted(role["controlled_profile_ids"])
    basis["measurements"] = sorted(
        basis["measurements"], key=lambda item: item["estimand_id"]
    )
    graph = basis["phase_graph"]
    graph["phases"] = sorted(graph["phases"], key=lambda item: item["phase_id"])
    for phase in graph["phases"]:
        phase["next_phases"] = sorted(phase["next_phases"])
    upstream = basis.get("upstream_source")
    if upstream is not None:
        upstream["source_paths"] = sorted(upstream["source_paths"])
    return content_sha256(basis)


def _suite_hash(suite: SuiteManifest) -> str:
    basis = suite.model_dump(mode="python")
    basis["case_ids"] = sorted(basis["case_ids"])
    basis["blocks"] = sorted(basis["blocks"], key=lambda item: item["block_id"])
    for block in basis["blocks"]:
        block["subject_roles"] = sorted(block["subject_roles"])
        block["rollout_seeds"] = sorted(block["rollout_seeds"])
    for cluster in basis["cluster_by_estimand"].values():
        cluster["identity_fields"] = sorted(cluster["identity_fields"])
        cluster["paired_fields"] = sorted(cluster["paired_fields"])
    basis["aggregation_group_fields"] = sorted(basis["aggregation_group_fields"])
    return content_sha256(basis)


def _profile_hash(profile: AgentProfile) -> str:
    basis = profile.model_dump(mode="python")
    config = basis["execution_config"]
    config["tools"] = sorted(
        config["tools"],
        key=lambda item: (
            item["implementation_id"],
            item["version"],
            item["content_sha256"],
        ),
    )
    config["retry_policy"]["retryable_conditions"] = sorted(
        config["retry_policy"]["retryable_conditions"]
    )
    return content_sha256(basis)


def _run_hash(run_spec: RunSpec) -> str:
    return content_sha256(run_spec)


def _reference_implementations(
    measurement: MeasurementSpec,
) -> dict[str, ImplementationRef]:
    if isinstance(measurement, OptimizableOutcomeMeasurementSpec):
        return {
            kind: contract.implementation
            for kind, contract in measurement.reference_contracts.items()
        }
    if isinstance(measurement, ComparativeMeasurementSpec):
        return {
            "comparison_baseline": measurement.comparison_baseline.implementation,
            **{
                kind: contract.implementation
                for kind, contract in measurement.support_contracts.items()
            },
        }
    return {}


def _normalized_inputs(inputs: ResolutionInputs) -> ResolutionInputs:
    phases = tuple(
        phase.model_copy(update={"next_phases": tuple(sorted(phase.next_phases))})
        for phase in sorted(
            inputs.family.phase_graph.phases, key=lambda item: item.phase_id
        )
    )
    phase_graph = inputs.family.phase_graph.model_copy(update={"phases": phases})
    roles = tuple(
        role.model_copy(
            update={
                "controlled_profile_ids": tuple(sorted(role.controlled_profile_ids))
            }
        )
        for role in sorted(inputs.family.roles, key=lambda item: item.role_id)
    )
    upstream_source = inputs.family.upstream_source
    if upstream_source is not None:
        upstream_source = upstream_source.model_copy(
            update={"source_paths": tuple(sorted(upstream_source.source_paths))}
        )
    family = inputs.family.model_copy(
        update={
            "verifiers": tuple(
                sorted(
                    inputs.family.verifiers,
                    key=lambda item: (
                        item.plugin.plugin_id,
                        item.plugin.plugin_version,
                    ),
                )
            ),
            "phase_graph": phase_graph,
            "roles": roles,
            "measurements": tuple(
                sorted(inputs.family.measurements, key=lambda item: item.estimand_id)
            ),
            "upstream_source": upstream_source,
        }
    )
    cases = tuple(
        case.model_copy(
            update={
                "seats": tuple(sorted(case.seats, key=lambda item: item.seat_id)),
                "terminal_reasons": tuple(sorted(case.terminal_reasons)),
            }
        )
        for case in sorted(inputs.cases, key=lambda item: item.case_id)
    )
    blocks = tuple(
        block.model_copy(
            update={
                "subject_roles": tuple(sorted(block.subject_roles)),
                "rollout_seeds": tuple(sorted(block.rollout_seeds)),
            }
        )
        for block in sorted(inputs.suite.blocks, key=lambda item: item.block_id)
    )
    clusters = {
        estimand_id: cluster.model_copy(
            update={
                "identity_fields": tuple(sorted(cluster.identity_fields)),
                "paired_fields": tuple(sorted(cluster.paired_fields)),
            }
        )
        for estimand_id, cluster in inputs.suite.cluster_by_estimand.items()
    }
    suite = inputs.suite.model_copy(
        update={
            "case_ids": tuple(sorted(inputs.suite.case_ids)),
            "blocks": blocks,
            "cluster_by_estimand": clusters,
            "aggregation_group_fields": tuple(
                sorted(inputs.suite.aggregation_group_fields)
            ),
        }
    )
    profiles = tuple(
        profile.model_copy(
            update={
                "execution_config": profile.execution_config.model_copy(
                    update={
                        "tools": tuple(
                            sorted(
                                profile.execution_config.tools,
                                key=lambda item: (
                                    item.implementation_id,
                                    item.version,
                                    item.content_sha256,
                                ),
                            )
                        ),
                        "retry_policy": profile.execution_config.retry_policy.model_copy(
                            update={
                                "retryable_conditions": tuple(
                                    sorted(
                                        profile.execution_config.retry_policy.retryable_conditions
                                    )
                                )
                            }
                        ),
                    }
                ),
            }
        )
        for profile in sorted(inputs.agent_profiles, key=lambda item: item.profile_id)
    )
    return ResolutionInputs.model_validate(
        {
            "family": family,
            "cases": cases,
            "suite": suite,
            "agent_profiles": profiles,
            "run_spec": inputs.run_spec,
        }
    )


def _validate_identities(inputs: ResolutionInputs) -> None:
    family = inputs.family
    cases_by_id = {case.case_id: case for case in inputs.cases}
    if len(cases_by_id) != len(inputs.cases):
        raise ManifestMismatch("supplied case_id values must be unique")
    if set(cases_by_id) != set(inputs.suite.case_ids):
        raise ManifestMismatch("suite cases must be supplied exactly once")

    roles = {role.role_id: role for role in family.roles}
    for phase in family.phase_graph.phases:
        declared_phase_roles = set(phase.observation_schema_by_role) | set(
            phase.action_schema_by_role
        )
        unknown_phase_roles = declared_phase_roles - set(roles)
        if unknown_phase_roles:
            raise ManifestMismatch(
                f"phase {phase.phase_id!r} uses undeclared roles: "
                f"{sorted(unknown_phase_roles)!r}"
            )
    for case in inputs.cases:
        if (
            case.family_id != family.family_id
            or case.family_version != family.family_version
        ):
            raise ManifestMismatch(
                "case family identity does not match family manifest"
            )
        unknown_roles = {seat.role_id for seat in case.seats} - set(roles)
        if unknown_roles:
            raise ManifestMismatch(
                f"case seats use undeclared roles: {unknown_roles!r}"
            )

    verifier_ids = {pin.plugin.plugin_id for pin in family.verifiers}
    measurements = {
        measurement.estimand_id: measurement for measurement in family.measurements
    }
    for measurement in family.measurements:
        if measurement.verifier_plugin_id not in verifier_ids:
            raise ManifestMismatch(
                f"measurement {measurement.estimand_id!r} has no pinned verifier"
            )
    block_estimands = {block.estimand_id for block in inputs.suite.blocks}
    unknown_estimands = block_estimands - set(measurements)
    if unknown_estimands:
        raise ManifestMismatch(
            f"suite blocks select undeclared estimands: {sorted(unknown_estimands)!r}"
        )
    if set(inputs.suite.cluster_by_estimand) != block_estimands:
        raise InvalidClusterDeclaration(
            "cluster_by_estimand must exactly cover suite block estimands"
        )

    for case in inputs.cases:
        provenance = case.provenance
        if provenance.source_kind == "generated":
            if family.generator is None:
                raise ManifestMismatch("generated case has no family generator pin")
            if (
                provenance.generator_id != family.generator.implementation_id
                or provenance.generator_version != family.generator.version
            ):
                raise ManifestMismatch(
                    f"case {case.case_id!r} generator does not match family generator"
                )

    profile_ids = [profile.profile_id for profile in inputs.agent_profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ManifestMismatch("agent profile IDs must be unique")
    referenced_profile_ids = _used_profile_ids(inputs)
    missing_profile_ids = referenced_profile_ids - set(profile_ids)
    if missing_profile_ids:
        raise IncompleteAgentAssignment(
            f"declared profiles are unresolved: {sorted(missing_profile_ids)!r}"
        )
    unreferenced_profile_ids = set(profile_ids) - referenced_profile_ids
    if unreferenced_profile_ids:
        raise IncompleteAgentAssignment(
            f"unreferenced agent profiles are not part of the run: "
            f"{sorted(unreferenced_profile_ids)!r}"
        )
    adapter_pins: dict[tuple[str, str], object] = {}
    for profile in inputs.agent_profiles:
        key = (
            profile.adapter.plugin.plugin_id,
            profile.adapter.plugin.plugin_version,
        )
        prior = adapter_pins.setdefault(key, profile.adapter.implementation)
        if prior != profile.adapter.implementation:
            raise ManifestMismatch(
                f"agent adapter {key!r} has conflicting implementation pins"
            )

    needed_subject_roles = {
        role for block in inputs.suite.blocks for role in block.subject_roles
    }
    if set(inputs.run_spec.subject_profile_by_role) != needed_subject_roles:
        raise IncompleteAgentAssignment(
            "run subject assignments must exactly cover suite subject roles"
        )
    for role_id in needed_subject_roles:
        role = roles.get(role_id)
        if role is None or not role.testable:
            raise IncompleteAgentAssignment(
                f"subject role {role_id!r} is absent or not testable"
            )
        if inputs.run_spec.admission_profile == "training" and not role.trainable:
            raise IncompleteAgentAssignment(
                f"training subject role {role_id!r} is not trainable"
            )


def _used_profile_ids(inputs: ResolutionInputs) -> set[str]:
    return set(inputs.run_spec.subject_profile_by_role.values()) | {
        profile_id
        for block in inputs.suite.blocks
        for profile_id in block.controlled_profile_by_role.values()
    }


def _resolve_plugins(
    inputs: ResolutionInputs, registry: PluginRegistry
) -> dict[str, str]:
    adapter_observability: dict[str, str] = {}
    try:
        environment = inputs.family.environment.plugin
        registry.resolve_environment(environment.plugin_id, environment.plugin_version)
        for pin in inputs.family.verifiers:
            registry.resolve_verifier(pin.plugin.plugin_id, pin.plugin.plugin_version)
        used_profiles = _used_profile_ids(inputs)
        for profile in inputs.agent_profiles:
            if profile.profile_id not in used_profiles:
                continue
            adapter = registry.resolve_agent_adapter(
                profile.adapter.plugin.plugin_id,
                profile.adapter.plugin.plugin_version,
            )
            actual = getattr(adapter, "call_observability")
            if type(actual) is not str or actual not in {
                "full",
                "logical_only",
                "opaque",
            }:
                raise UnresolvedImplementation(
                    f"agent adapter for {profile.profile_id!r} has invalid call_observability"
                )
            adapter_observability[profile.profile_id] = actual
        backend = inputs.run_spec.execution_backend.plugin
        registry.resolve_execution_backend(backend.plugin_id, backend.plugin_version)
    except UnresolvedImplementation:
        raise
    except PluginRegistryError as exc:
        raise UnresolvedImplementation(str(exc)) from exc
    except Exception as exc:
        raise UnresolvedImplementation("plugin metadata inspection failed") from exc
    return adapter_observability


def _cluster_fields(suite: SuiteManifest, estimand_id: str) -> tuple[str, ...]:
    cluster = suite.cluster_by_estimand.get(estimand_id)
    if cluster is None:
        raise InvalidClusterDeclaration(
            f"missing cluster declaration for estimand {estimand_id!r}"
        )
    requested = (
        tuple(cluster.identity_fields)
        + tuple(cluster.paired_fields)
        + ((cluster.parent_field,) if cluster.parent_field else ())
    )
    unknown = set(requested) - SUPPORTED_CLUSTER_FIELDS
    if unknown:
        raise InvalidClusterDeclaration(
            f"unsupported cluster fields: {sorted(unknown)!r}"
        )
    return requested


def _cluster_values(
    *,
    family: FamilyManifest,
    case: CaseManifest,
    block_id: str,
    subject_role: str,
    subject_seat_id: str,
    subject_profile_id: str,
    rollout_seed: int,
) -> dict[str, str | int | None]:
    return {
        "family_id": family.family_id,
        "family_version": family.family_version,
        "case_id": case.case_id,
        "world_seed": case.world_seed,
        "generator_version": case.provenance.generator_version,
        "block_id": block_id,
        "subject_role": subject_role,
        "subject_seat_id": subject_seat_id,
        "subject_profile_id": subject_profile_id,
        "rollout_seed": rollout_seed,
    }


def _cell_digest_basis(cell: EpisodeCell) -> dict[str, object]:
    return cell.model_dump(mode="python", exclude={"cell_id"})


def _plan_digest_basis(plan: RunPlan) -> dict[str, object]:
    return plan.model_dump(mode="python", exclude={"run_plan_id", "run_plan_sha256"})


def _reconstruct_expected_plan_content(
    inputs: ResolutionInputs,
    adapter_observability: Mapping[str, str],
) -> tuple[AdmissionReport, tuple[EpisodeCell, ...]]:
    """Reconstruct the only admissible cell tuple from normalized semantic inputs."""

    profiles = {profile.profile_id: profile for profile in inputs.agent_profiles}
    if set(adapter_observability) != set(profiles):
        missing = set(profiles) - set(adapter_observability)
        extra = set(adapter_observability) - set(profiles)
        raise IncompleteAgentAssignment(
            f"adapter observability does not match profile closure; "
            f"missing={sorted(missing)!r}, extra={sorted(extra)!r}"
        )
    report = _evaluate_resolved_admission(
        inputs.family.capabilities,
        inputs.run_spec.admission_profile,
        profiles,
        adapter_observability,
    )
    if report.status == "rejected":
        raise CapabilityMismatch(report)

    profile_hashes = {
        profile_id: _profile_hash(profile) for profile_id, profile in profiles.items()
    }
    family_hash = _family_hash(inputs.family)
    suite_hash = _suite_hash(inputs.suite)
    run_hash = _run_hash(inputs.run_spec)
    roles = {role.role_id: role for role in inputs.family.roles}
    measurements = {
        measurement.estimand_id: measurement
        for measurement in inputs.family.measurements
    }
    verifiers = {pin.plugin.plugin_id: pin for pin in inputs.family.verifiers}

    draft_cells: list[dict[str, object]] = []
    for case in inputs.cases:
        seats = tuple(sorted(case.seats, key=lambda item: item.seat_id))
        roles_present = {seat.role_id for seat in seats}
        for block in inputs.suite.blocks:
            measurement = measurements[block.estimand_id]
            verifier = verifiers[measurement.verifier_plugin_id]
            cluster = inputs.suite.cluster_by_estimand[block.estimand_id]
            unknown_controlled = set(block.controlled_profile_by_role) - roles_present
            if unknown_controlled:
                raise IncompleteAgentAssignment(
                    f"controlled assignments name absent roles: {unknown_controlled!r}"
                )
            for subject_role in block.subject_roles:
                subject_profile_id = inputs.run_spec.subject_profile_by_role.get(
                    subject_role
                )
                if subject_profile_id is None or subject_profile_id not in profiles:
                    raise IncompleteAgentAssignment(
                        f"no resolved subject profile for role {subject_role!r}"
                    )
                subject_seats = tuple(
                    seat for seat in seats if seat.role_id == subject_role
                )
                if not subject_seats:
                    raise IncompleteAgentAssignment(
                        f"case {case.case_id!r} has no seat for subject role "
                        f"{subject_role!r}"
                    )
                for subject_seat in subject_seats:
                    seat_profile_ids: dict[str, str] = {}
                    for seat in seats:
                        if seat.seat_id == subject_seat.seat_id:
                            profile_id = subject_profile_id
                        else:
                            profile_id = block.controlled_profile_by_role.get(
                                seat.role_id
                            )
                            if profile_id is None:
                                raise IncompleteAgentAssignment(
                                    f"seat {seat.seat_id!r} has no controlled profile"
                                )
                            allowed = roles[seat.role_id].controlled_profile_ids
                            if profile_id not in allowed:
                                raise IncompleteAgentAssignment(
                                    f"profile {profile_id!r} is not allowed for role "
                                    f"{seat.role_id!r}"
                                )
                        if profile_id not in profiles:
                            raise IncompleteAgentAssignment(
                                f"unknown agent profile {profile_id!r}"
                            )
                        seat_profile_ids[seat.seat_id] = profile_id

                    for repetition_index in range(block.repetitions):
                        for rollout_seed in block.rollout_seeds:
                            available = _cluster_values(
                                family=inputs.family,
                                case=case,
                                block_id=block.block_id,
                                subject_role=subject_role,
                                subject_seat_id=subject_seat.seat_id,
                                subject_profile_id=subject_profile_id,
                                rollout_seed=rollout_seed,
                            )
                            identity_values = {
                                field: available[field]
                                for field in cluster.identity_fields
                            }
                            pairing_values = {
                                field: available[field]
                                for field in cluster.paired_fields
                            }
                            if any(value is None for value in identity_values.values()):
                                raise InvalidClusterDeclaration(
                                    "cluster identity field is unavailable for a cell"
                                )
                            if any(value is None for value in pairing_values.values()):
                                raise InvalidClusterDeclaration(
                                    "cluster pairing field is unavailable for a cell"
                                )
                            parent_value = (
                                available[cluster.parent_field]
                                if cluster.parent_field
                                else None
                            )
                            if cluster.parent_field and parent_value is None:
                                raise InvalidClusterDeclaration(
                                    "cluster parent field is unavailable for a cell"
                                )
                            cluster_digest = content_sha256(identity_values)
                            draft_cells.append(
                                {
                                    "cell_id": "pending",
                                    "case_id": case.case_id,
                                    "family_id": inputs.family.family_id,
                                    "family_version": inputs.family.family_version,
                                    "block_id": block.block_id,
                                    "estimand_id": block.estimand_id,
                                    "measurement_sha256": content_sha256(measurement),
                                    "subject_role": subject_role,
                                    "subject_seat_id": subject_seat.seat_id,
                                    "repetition_index": repetition_index,
                                    "rollout_seed": rollout_seed,
                                    "world_seed": case.world_seed,
                                    "cluster_id": "cluster-" + cluster_digest[:24],
                                    "cluster_level": cluster.cluster_level,
                                    "observations_per_cluster": 1,
                                    "cluster_parent_value": parent_value,
                                    "pairing_values": pairing_values,
                                    "panel_mode": cluster.panel_mode,
                                    "case_sha256": case.content_sha256,
                                    "family_sha256": family_hash,
                                    "suite_sha256": suite_hash,
                                    "run_spec_sha256": run_hash,
                                    "candidate_agent_config_sha256": profile_hashes[
                                        subject_profile_id
                                    ],
                                    "seat_profile_id_by_seat": seat_profile_ids,
                                    "seat_profile_sha256_by_seat": {
                                        seat_id: profile_hashes[profile_id]
                                        for seat_id, profile_id in seat_profile_ids.items()
                                    },
                                    "environment_ref": inputs.family.environment.implementation,
                                    "verifier_ref": verifier.implementation,
                                    "reference_refs": _reference_implementations(
                                        measurement
                                    ),
                                    "oracle_ref": measurement.oracle,
                                    "adapter_refs_by_seat": {
                                        seat_id: profiles[
                                            profile_id
                                        ].adapter.implementation
                                        for seat_id, profile_id in seat_profile_ids.items()
                                    },
                                    "execution_backend_ref": inputs.run_spec.execution_backend.implementation,
                                    "admission_profile": inputs.run_spec.admission_profile,
                                }
                            )

    if not draft_cells:
        raise ManifestMismatch("resolution produced no episode cells")
    counts = Counter(
        (cast(str, draft["estimand_id"]), cast(str, draft["cluster_id"]))
        for draft in draft_cells
    )
    cells: list[EpisodeCell] = []
    for draft in draft_cells:
        draft["observations_per_cluster"] = counts[
            (cast(str, draft["estimand_id"]), cast(str, draft["cluster_id"]))
        ]
        pending = EpisodeCell.model_validate(draft)
        digest = content_sha256(_cell_digest_basis(pending))
        complete = pending.model_dump(mode="python")
        complete["cell_id"] = "cell-" + digest[:24]
        cells.append(EpisodeCell.model_validate(complete))

    cells.sort(
        key=lambda cell: (
            cell.case_id,
            cell.block_id,
            cell.estimand_id,
            cell.subject_role,
            cell.subject_seat_id,
            cell.repetition_index,
            cell.rollout_seed,
            cell.cell_id,
        )
    )
    return report, tuple(cells)


def verify_run_plan_identity(plan: RunPlan) -> bool:
    """Verify the exact resolver reconstruction before accepting plan identity."""

    try:
        checked = RunPlan.model_validate(_raw_state(plan))
        embedded = ResolutionInputs(
            family=checked.family,
            cases=checked.cases,
            suite=checked.suite,
            agent_profiles=checked.agent_profiles,
            run_spec=checked.run_spec,
        )
        normalized = _normalized_inputs(embedded)
        if (
            checked.family != normalized.family
            or checked.cases != normalized.cases
            or checked.suite != normalized.suite
            or checked.agent_profiles != normalized.agent_profiles
            or checked.run_spec != normalized.run_spec
        ):
            return False
        _validate_identities(normalized)
        for estimand_id in normalized.suite.cluster_by_estimand:
            _cluster_fields(normalized.suite, estimand_id)

        expected_case_hashes = {
            case.case_id: case.content_sha256 for case in normalized.cases
        }
        expected_profile_hashes = {
            profile.profile_id: _profile_hash(profile)
            for profile in normalized.agent_profiles
        }
        if (
            checked.family_sha256 != _family_hash(normalized.family)
            or dict(checked.case_sha256_by_id) != expected_case_hashes
            or checked.suite_sha256 != _suite_hash(normalized.suite)
            or checked.run_spec_sha256 != _run_hash(normalized.run_spec)
            or dict(checked.agent_profile_sha256_by_id) != expected_profile_hashes
        ):
            return False

        expected_report, expected_cells = _reconstruct_expected_plan_content(
            normalized,
            dict(checked.adapter_call_observability_by_profile),
        )
        if (
            checked.admission_report != expected_report
            or checked.cells != expected_cells
        ):
            return False

        digest = content_sha256(_plan_digest_basis(checked))
        return checked.run_plan_sha256 == digest and checked.run_plan_id == (
            "runplan-" + digest[:24]
        )
    except Exception:
        return False


def resolve_run_plan(inputs: ResolutionInputs, registry: PluginRegistry) -> RunPlan:
    """Resolve immutable experiment inputs without invoking any plugin hook."""

    resolved = _normalized_inputs(_revalidate_inputs(inputs))
    _validate_identities(resolved)
    for estimand_id in resolved.suite.cluster_by_estimand:
        _cluster_fields(resolved.suite, estimand_id)
    adapter_observability = _resolve_plugins(resolved, registry)

    report, cells = _reconstruct_expected_plan_content(resolved, adapter_observability)
    profile_hashes = {
        profile.profile_id: _profile_hash(profile)
        for profile in resolved.agent_profiles
    }
    family_hash = _family_hash(resolved.family)
    suite_hash = _suite_hash(resolved.suite)
    run_hash = _run_hash(resolved.run_spec)
    case_hashes = {case.case_id: case.content_sha256 for case in resolved.cases}
    plan_data = {
        "spec_version": "aeread.run_plan/0.1",
        "run_plan_id": "pending",
        "run_plan_sha256": "0" * 64,
        "family_sha256": family_hash,
        "case_sha256_by_id": case_hashes,
        "suite_sha256": suite_hash,
        "run_spec_sha256": run_hash,
        "agent_profile_sha256_by_id": profile_hashes,
        "family": resolved.family,
        "cases": resolved.cases,
        "suite": resolved.suite,
        "agent_profiles": resolved.agent_profiles,
        "run_spec": resolved.run_spec,
        "adapter_call_observability_by_profile": adapter_observability,
        "admission_report": report,
        "cells": cells,
    }
    pending_plan = RunPlan.model_validate(plan_data)
    digest = content_sha256(_plan_digest_basis(pending_plan))
    plan_data["run_plan_id"] = "runplan-" + digest[:24]
    plan_data["run_plan_sha256"] = digest
    return RunPlan.model_validate(plan_data)


__all__ = [
    "ADMISSION_REQUIREMENTS",
    "CapabilityMismatch",
    "ContentHashMismatch",
    "IncompleteAgentAssignment",
    "InvalidClusterDeclaration",
    "ManifestMismatch",
    "PlanningError",
    "SUPPORTED_CLUSTER_FIELDS",
    "UnresolvedImplementation",
    "evaluate_admission",
    "resolve_run_plan",
    "verify_run_plan_identity",
]
