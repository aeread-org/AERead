"""Deterministic run-plan resolution for AERead authoring records.

R2 reconciles validated R1 records, performs provider-free preflight, expands
fully explicit plan cells, and seals canonical plan bytes.  It does not schedule
phases, call agents, or create execution evidence.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..registry import (
    HarnessRegistry,
    HarnessResolutionError,
    PluginRegistry,
    PluginRegistryError,
    ProviderCapabilities,
)
from ..schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)


class PlanResolutionError(ValueError):
    """R1 records cannot be reconciled into one complete run plan."""


class PlanIntegrityError(ValueError):
    """A sealed run plan no longer matches its declared content digest."""


class CapabilityExclusionError(PlanResolutionError):
    """A profile's harness/provider/tools/memory combination is inadmissible.

    Raised at plan resolution -- before any episode starts, before any
    provider call is possible -- carrying the sealed `ProfileAdmission`
    receipt that explains exactly why (`.admission`).  This is the typed
    exclusion of §5.3: a rejected combination never surfaces as an
    exception mid-episode, because it never reaches one.
    """

    def __init__(self, admission: "ProfileAdmission") -> None:
        self.admission = admission
        super().__init__(
            f"profile {admission.profile_id!r} is inadmissible: "
            + "; ".join(admission.reasons)
        )


_PIN_KINDS = {
    "family_plugin",
    "scorer",
    "reference",
    "generator",
    "harness",
    "runtime",
}

# The boolean-valued `ProviderCapabilities` fields a `HarnessRequirements.provider`
# frozenset may name (§5.3: "⊆ ProviderCapabilities fields").  `max_context_tokens`
# is excluded: it is an int, not a capability flag a harness can require as a set
# member.
_PROVIDER_CAPABILITY_FLAGS = (
    "native_tools",
    "structured_output",
    "seed",
    "system_prompt",
    "reasoning_budget",
    "reasoning_token_report",
)

# The capability-vector fields sealed on every `ProfileAdmission` (§5.3).  Each
# is derived only from what admission already knows -- the harness's declared
# requirements, the provider's declared capabilities, and the profile's own
# tools/memory/sampling selection -- never from a live provider call, so a
# rejected profile carries every flag False.
_CAPABILITY_VECTOR_FIELDS = (
    "provider_calls_observed",
    "tool_calls_observed",
    "native_history_preserved",
    "state_restorable",
    "seed_enforced",
    "policy_re_executable",
    "cost_complete",
)


def _strict_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanResolutionError(f"{path} must be a non-empty string")
    return value


def _strict_sha256(value: Any, path: str) -> str:
    result = _strict_string(value, path)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PlanResolutionError(
            f"{path} must be 64 lowercase hexadecimal characters"
        )
    return result


@dataclass(frozen=True, slots=True)
class ImplementationPin:
    """Content identity for one executable component referenced by a plan."""

    component_id: str
    kind: str
    version: str
    sha256: str

    @classmethod
    def from_dict(cls, value: Any) -> "ImplementationPin":
        if not isinstance(value, Mapping):
            raise PlanResolutionError("ImplementationPin must be an object")
        required = {"component_id", "kind", "version", "sha256"}
        missing = sorted(required - set(value))
        unexpected = sorted(set(value) - required)
        if missing:
            raise PlanResolutionError(
                f"ImplementationPin is missing required fields: {missing}"
            )
        if unexpected:
            raise PlanResolutionError(
                f"ImplementationPin has unexpected fields: {unexpected}"
            )
        kind = _strict_string(value["kind"], "ImplementationPin.kind")
        if kind not in _PIN_KINDS:
            raise PlanResolutionError(
                f"ImplementationPin.kind must be one of {sorted(_PIN_KINDS)}"
            )
        return cls(
            component_id=_strict_string(
                value["component_id"], "ImplementationPin.component_id"
            ),
            kind=kind,
            version=_strict_string(value["version"], "ImplementationPin.version"),
            sha256=_strict_sha256(value["sha256"], "ImplementationPin.sha256"),
        )


@dataclass(frozen=True, slots=True)
class PlanCell:
    """One fully resolved case × block × seed × repetition execution unit."""

    spec_version: str
    cell_id: str
    case_id: str
    case_sha256: str
    family_id: str
    family_version: str
    suite_id: str
    suite_version: str
    block_id: str
    sampling_plan_id: str
    analysis_plan_id: str
    world_seed: int
    sampling_seed: int
    block_repetition: int
    sampling_replicate: int
    replicate_index: int
    cluster_id: str
    cluster_level: str
    observations_per_cluster: int
    pair_id: str | None
    paired_fields: Mapping[str, Any]
    panel_mode: str
    profile_by_seat: Mapping[str, str]
    execution_mode: str
    case_max_logical_actions: int


@dataclass(frozen=True, slots=True)
class ProfileAdmission:
    """A sealed capability-admission receipt for one agent profile (§5.3).

    Computed at plan resolution from the resolved harness's declared
    `HarnessRequirements`, the named provider's declared `ProviderCapabilities`,
    and the profile's own tools/memory/sampling selection -- never from a live
    provider call.  Only an admitted (`admitted=True`) receipt is ever sealed
    into a `RunPlan`; a rejected combination raises `CapabilityExclusionError`
    carrying this same record instead.
    """

    admission_id: str
    profile_id: str
    harness_id: str
    harness_version: str
    provider: str
    admitted: bool
    capability_vector: Mapping[str, bool]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunPlan:
    """Canonical benchmark truth written before any provider or tool call."""

    spec_version: str
    run_plan_id: str
    plan_sha256: str
    families: tuple[FamilyManifest, ...]
    cases: tuple[CaseManifest, ...]
    suite: SuiteManifest
    sampling: SamplingPlan
    evaluation_blocks: tuple[EvaluationBlock, ...]
    analysis: AnalysisPlan
    agent_profiles: tuple[AgentProfile, ...]
    run_spec: RunSpec
    implementation_pins: tuple[ImplementationPin, ...]
    input_digests: Mapping[str, str]
    cells: tuple[PlanCell, ...]
    profile_admissions: tuple[ProfileAdmission, ...]


def _canonical_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"canonical mapping key must be a string, got {key!r}")
            output[key] = _canonical_value(item)
        return output
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("canonical JSON cannot contain non-finite numbers")
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for supported runner records."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _case_digest_from_manifest(case: CaseManifest) -> str:
    content = _canonical_value(case)
    content.pop("content_sha256", None)
    return _digest(content)


def case_content_sha256(value: Mapping[str, Any] | CaseManifest) -> str:
    """Compute the case digest after normalizing R1 defaults and omitting itself."""
    if isinstance(value, CaseManifest):
        return _case_digest_from_manifest(value)
    if not isinstance(value, Mapping):
        raise TypeError("case content must be a CaseManifest or mapping")
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return _case_digest_from_manifest(CaseManifest.from_dict(normalized))


def _index_unique(
    values: Sequence[Any], attribute: str, label: str
) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for value in values:
        identity = getattr(value, attribute, None)
        if not isinstance(identity, str):
            raise PlanResolutionError(f"{label} has no string {attribute}")
        if identity in indexed:
            raise PlanResolutionError(f"duplicate {label} identity: {identity}")
        indexed[identity] = value
    return indexed


def _family_index(families: Sequence[FamilyManifest]) -> dict[str, FamilyManifest]:
    indexed: dict[str, FamilyManifest] = {}
    for family in families:
        if not isinstance(family, FamilyManifest):
            raise PlanResolutionError("families must contain only FamilyManifest records")
        family_id = family.family.id
        if family_id in indexed:
            raise PlanResolutionError(f"duplicate family identity: {family_id}")
        indexed[family_id] = family
    if not indexed:
        raise PlanResolutionError("at least one FamilyManifest is required")
    return indexed


def _pin_index(
    pins: Sequence[ImplementationPin],
) -> dict[str, ImplementationPin]:
    indexed: dict[str, ImplementationPin] = {}
    for pin in pins:
        if not isinstance(pin, ImplementationPin):
            raise PlanResolutionError(
                "implementation_pins must contain only ImplementationPin records"
            )
        if pin.component_id in indexed:
            raise PlanResolutionError(
                f"duplicate implementation pin: {pin.component_id}"
            )
        indexed[pin.component_id] = pin
    return indexed


def _required_pin_kinds(
    families: Sequence[FamilyManifest], profiles: Sequence[AgentProfile]
) -> dict[str, str]:
    required: dict[str, str] = {}

    def require(component_id: str, kind: str) -> None:
        previous = required.get(component_id)
        if previous is not None and previous != kind:
            raise PlanResolutionError(
                f"component {component_id!r} is referenced as both {previous} and {kind}"
            )
        required[component_id] = kind

    for family in families:
        require(family.family.plugin_id, "family_plugin")
        require(family.scoring.scorer_id, "scorer")
        if family.scoring.oracle_id is not None:
            require(family.scoring.oracle_id, "reference")
        for reference_id in family.scoring.reference_provider_ids:
            require(reference_id, "reference")
        if family.generator is not None:
            require(family.generator.generator_id, "generator")
    for profile in profiles:
        require(profile.harness.id, "harness")
        require(profile.runtime.implementation, "runtime")
    return required


def _check_pins(
    required: Mapping[str, str], pins: Mapping[str, ImplementationPin]
) -> None:
    missing = sorted(set(required) - set(pins))
    if missing:
        raise PlanResolutionError(f"missing implementation pins: {missing}")
    unexpected = sorted(set(pins) - set(required))
    if unexpected:
        raise PlanResolutionError(f"unreferenced implementation pins: {unexpected}")
    wrong_kind = {
        component_id: (required[component_id], pins[component_id].kind)
        for component_id in required
        if pins[component_id].kind != required[component_id]
    }
    if wrong_kind:
        raise PlanResolutionError(
            f"implementation pin kinds do not match references: {wrong_kind}"
        )


def _capability_vector(
    *,
    harness: Any | None,
    capabilities: ProviderCapabilities | None,
    profile: AgentProfile,
    admitted: bool,
) -> Mapping[str, bool]:
    """The declared capability vector each reported claim checks against (§5.3).

    Derived only from admission-time facts.  A rejected profile, an
    unresolved harness, or an unregistered provider carries every flag
    False -- no claim may borrow a capability from a combination admission
    refused.
    """

    if not admitted or harness is None or capabilities is None:
        return MappingProxyType({name: False for name in _CAPABILITY_VECTOR_FIELDS})

    requires = harness.requires
    tool_calls_observed = bool(profile.tools) and requires.tools != "none"
    native_history_preserved = (
        tool_calls_observed
        and "native_tools" in requires.provider
        and capabilities.native_tools
    )
    # Stateful replay (§10) needs a state codec no harness here declares
    # (every registered `requires.memory` is `{"disabled"}`), so neither flag
    # can be proven true yet.
    state_restorable = False
    policy_re_executable = False
    seed_declared = (
        profile.sampling.seed is not None
        or profile.harness.config.get("request_seed_source") == "paired_cell_v1"
    )
    seed_enforced = bool(capabilities.seed) and seed_declared
    # A hidden reasoning token spends cost the receipt cannot see unless the
    # provider reports it back (§7); no requested budget, no unseen spend.
    cost_complete = (
        profile.reasoning.token_budget is None or capabilities.reasoning_token_report
    )
    return MappingProxyType(
        {
            "provider_calls_observed": not requires.blocking,
            "tool_calls_observed": tool_calls_observed,
            "native_history_preserved": native_history_preserved,
            "state_restorable": state_restorable,
            "seed_enforced": seed_enforced,
            "policy_re_executable": policy_re_executable,
            "cost_complete": cost_complete,
        }
    )


def _admit_profile(
    profile: AgentProfile,
    *,
    harness_registry: HarnessRegistry,
    provider_capabilities: Mapping[str, ProviderCapabilities],
    tool_bindings: Mapping[str, frozenset[str]],
) -> ProfileAdmission:
    """Admit one profile against its resolved harness and named provider (§5.3).

    Checks, in order: (1) `harness.requires.provider ⊆` the provider's true
    `ProviderCapabilities` fields; (2) `profile.tools` non-empty requires
    `requires.tools != "none"` and every tool id resolving to a pinned
    `ToolDefinition` in the family bindings; (3) `profile.memory.mode ∈
    requires.memory`.  Never raises: a failed check is recorded as a reason
    and the caller decides whether to exclude.
    """

    reasons: list[str] = []
    harness: Any | None = None
    try:
        harness = harness_registry.resolve(profile.harness.id, profile.harness.version)
    except HarnessResolutionError as error:
        reasons.append(str(error))

    capabilities = provider_capabilities.get(profile.model.provider)
    if capabilities is None:
        reasons.append(
            f"no ProviderCapabilities registered for provider "
            f"{profile.model.provider!r}"
        )

    if harness is not None and capabilities is not None:
        requires = harness.requires
        available = frozenset(
            name for name in _PROVIDER_CAPABILITY_FLAGS if getattr(capabilities, name)
        )
        missing_capabilities = requires.provider - available
        if missing_capabilities:
            reasons.append(
                f"provider {profile.model.provider!r} lacks capabilities required "
                f"by harness {profile.harness.id}/{profile.harness.version}: "
                f"{sorted(missing_capabilities)}"
            )
        if profile.tools:
            if requires.tools == "none":
                reasons.append(
                    f"profile {profile.profile_id!r} declares tools but harness "
                    f"{profile.harness.id}/{profile.harness.version} requires.tools "
                    "== 'none'"
                )
            pinned = tool_bindings.get(profile.profile_id, frozenset())
            unresolved = sorted(set(profile.tools) - pinned)
            if unresolved:
                reasons.append(
                    f"profile {profile.profile_id!r} declares tools with no pinned "
                    f"ToolDefinition in the family bindings: {unresolved}"
                )
        if profile.memory.mode not in requires.memory:
            reasons.append(
                f"profile {profile.profile_id!r} memory mode "
                f"{profile.memory.mode!r} is not permitted by harness "
                f"{profile.harness.id}/{profile.harness.version} "
                f"(allowed: {sorted(requires.memory)})"
            )

    admitted = not reasons
    capability_vector = _capability_vector(
        harness=harness, capabilities=capabilities, profile=profile, admitted=admitted
    )
    payload = {
        "profile_id": profile.profile_id,
        "harness_id": profile.harness.id,
        "harness_version": profile.harness.version,
        "provider": profile.model.provider,
        "admitted": admitted,
        "capability_vector": capability_vector,
        "reasons": tuple(reasons),
    }
    admission_id = "admission_" + _digest(payload)[:20]
    return ProfileAdmission(
        admission_id=admission_id,
        profile_id=profile.profile_id,
        harness_id=profile.harness.id,
        harness_version=profile.harness.version,
        provider=profile.model.provider,
        admitted=admitted,
        capability_vector=capability_vector,
        reasons=tuple(reasons),
    )


def _admit_profiles(
    profiles: Sequence[AgentProfile],
    *,
    harness_registry: HarnessRegistry,
    provider_capabilities: Mapping[str, ProviderCapabilities],
    tool_bindings: Mapping[str, frozenset[str]],
) -> tuple[ProfileAdmission, ...]:
    """Admit every profile, before any provider call is possible (§5.3).

    The first inadmissible profile raises `CapabilityExclusionError` carrying
    its receipt; only when every profile is admitted does a `RunPlan` seal
    the full set.
    """

    admissions: list[ProfileAdmission] = []
    for profile in profiles:
        admission = _admit_profile(
            profile,
            harness_registry=harness_registry,
            provider_capabilities=provider_capabilities,
            tool_bindings=tool_bindings,
        )
        if not admission.admitted:
            raise CapabilityExclusionError(admission)
        admissions.append(admission)
    return tuple(admissions)


def _context_for_cell(
    *,
    case: CaseManifest,
    family: FamilyManifest,
    suite: SuiteManifest,
    block: EvaluationBlock,
    sampling: SamplingPlan,
    run_spec: RunSpec,
    sampling_seed: int,
) -> Mapping[str, Any]:
    subject_profiles = tuple(
        run_spec.seat_assignments[seat_id] for seat_id in block.subject_seats
    )
    subject_profile: str | tuple[str, ...]
    if len(subject_profiles) == 1:
        subject_profile = subject_profiles[0]
    else:
        subject_profile = subject_profiles
    return {
        "family_id": family.family.id,
        "family_version": family.family.version,
        "suite_id": suite.suite_id,
        "case_id": case.case_id,
        "split": case.split,
        "world_seed": case.world_seed,
        "generator_id": case.provenance.generator_id,
        "generator_version": case.provenance.generator_version,
        "review_status": case.provenance.review_status,
        "block_id": block.block_id,
        "block_kind": block.kind,
        "subject_profile": subject_profile,
        "subject_profiles": subject_profiles,
        "sampling_seed": sampling_seed,
        "panel_mode": sampling.panel_mode,
        "replicate_level": sampling.replicate_level,
        "execution_mode": run_spec.execution_mode,
    }


def _select_fields(
    names: Sequence[str], context: Mapping[str, Any], label: str
) -> Mapping[str, Any]:
    missing = sorted(set(names) - set(context))
    if missing:
        raise PlanResolutionError(f"{label} references unknown fields: {missing}")
    return MappingProxyType({name: context[name] for name in names})


def _cluster_id(level: str, values: Mapping[str, Any]) -> str:
    return "cluster_" + _digest({"cluster_level": level, "fields": values})[:20]


def _pair_id(values: Mapping[str, Any]) -> str | None:
    if not values:
        return None
    return "pair_" + _digest({"fields": values})[:20]


def _input_digests(
    *,
    families: Sequence[FamilyManifest],
    cases: Sequence[CaseManifest],
    suite: SuiteManifest,
    sampling: SamplingPlan,
    blocks: Sequence[EvaluationBlock],
    analysis: AnalysisPlan,
    profiles: Sequence[AgentProfile],
    run_spec: RunSpec,
    pins: Sequence[ImplementationPin],
) -> Mapping[str, str]:
    output: dict[str, str] = {}

    def add(key: str, value: Any, digest: str | None = None) -> None:
        if key in output:
            raise PlanResolutionError(f"duplicate input digest identity: {key}")
        output[key] = digest or _digest(value)

    for family in families:
        add(f"family:{family.family.id}@{family.family.version}", family)
    for case in cases:
        add(f"case:{case.case_id}", case, case.content_sha256)
    add(f"suite:{suite.suite_id}@{suite.version}", suite)
    add(f"sampling:{sampling.sampling_plan_id}", sampling)
    for block in blocks:
        add(f"block:{block.block_id}", block)
    add(f"analysis:{analysis.analysis_plan_id}", analysis)
    for profile in profiles:
        add(f"agent:{profile.profile_id}", profile)
    add(f"run_spec:{run_spec.run_spec_id}", run_spec)
    for pin in pins:
        add(f"implementation:{pin.component_id}", pin, pin.sha256)
    return MappingProxyType(dict(sorted(output.items())))


def _plan_payload(plan: RunPlan) -> Mapping[str, Any]:
    return {
        "spec_version": plan.spec_version,
        "families": plan.families,
        "cases": plan.cases,
        "suite": plan.suite,
        "sampling": plan.sampling,
        "evaluation_blocks": plan.evaluation_blocks,
        "analysis": plan.analysis,
        "agent_profiles": plan.agent_profiles,
        "run_spec": plan.run_spec,
        "implementation_pins": plan.implementation_pins,
        "input_digests": plan.input_digests,
        "cells": plan.cells,
        "profile_admissions": plan.profile_admissions,
    }


def _seal_plan(provisional: RunPlan) -> RunPlan:
    plan_sha256 = _digest(_plan_payload(provisional))
    return dataclasses.replace(
        provisional,
        run_plan_id=f"runplan_{plan_sha256[:16]}",
        plan_sha256=plan_sha256,
    )


KERNEL_COMPONENT_PREFIX = "aeread.shared_runner."


def is_kernel_pin(pin: ImplementationPin) -> bool:
    """True when a pin's digest tracks runner-owned code rather than a family's.

    Harness pins and pins naming an ``aeread.shared_runner`` module hash kernel
    bytes that move with every runner commit. That digest is provenance; for
    audit identity such pins are compared by component, kind, and declared
    version, and a digest difference is reported as drift instead of a mismatch.
    """

    return pin.kind == "harness" or pin.component_id.startswith(KERNEL_COMPONENT_PREFIX)


def plan_with_pins(plan: RunPlan, pins: Sequence[ImplementationPin]) -> RunPlan:
    """Re-seal ``plan`` exactly as if it had been resolved with ``pins``.

    The ``implementation:<component_id>`` input digests follow the pins, so the
    result is byte-identical to a fresh resolution from the same inputs.
    """

    order = {pin.component_id: index for index, pin in enumerate(plan.implementation_pins)}
    selected = tuple(
        sorted(pins, key=lambda pin: (order.get(pin.component_id, len(order)), pin.component_id))
    )
    digests = {
        key: value
        for key, value in plan.input_digests.items()
        if not key.startswith("implementation:")
    }
    for pin in selected:
        key = f"implementation:{pin.component_id}"
        if key in digests:
            raise PlanResolutionError(f"duplicate input digest identity: {key}")
        digests[key] = pin.sha256
    provisional = dataclasses.replace(
        plan,
        run_plan_id="",
        plan_sha256="",
        implementation_pins=selected,
        input_digests=MappingProxyType(dict(sorted(digests.items()))),
    )
    return _seal_plan(provisional)


def plan_with_recorded_pins(
    plan: RunPlan, recorded: Sequence[ImplementationPin]
) -> tuple[RunPlan, tuple[str, ...]]:
    """Reconstruct the identity a receipt was sealed under from its recorded pins.

    Every recorded pin must name a component, kind, and version the current
    plan also pins. Family-owned pins must match by digest as well. Kernel-owned
    pins (see ``is_kernel_pin``) may differ in digest; each such difference is
    returned as ``implementation_drift:<component_id>`` and the returned plan
    carries the recorded digests so its ``run_plan_id`` matches the receipt.
    """

    current = {
        (pin.component_id, pin.kind, pin.version): pin for pin in plan.implementation_pins
    }
    seen = {(pin.component_id, pin.kind, pin.version): pin for pin in recorded}
    if len(seen) != len(tuple(recorded)) or set(seen) != set(current):
        raise PlanResolutionError(
            "recorded implementation pins do not name the plan's components"
        )
    drift: list[str] = []
    for key, pin in sorted(current.items()):
        if seen[key].sha256 == pin.sha256:
            continue
        if not is_kernel_pin(pin):
            raise PlanResolutionError(
                f"family implementation pin digest drifted: {pin.component_id}"
            )
        drift.append(f"implementation_drift:{pin.component_id}")
    if not drift:
        return plan, ()
    substituted = tuple(
        seen[(pin.component_id, pin.kind, pin.version)] for pin in plan.implementation_pins
    )
    return plan_with_pins(plan, substituted), tuple(drift)


def _validate_cross_references(
    *,
    family_by_id: Mapping[str, FamilyManifest],
    case_by_id: Mapping[str, CaseManifest],
    suite: SuiteManifest,
    sampling: SamplingPlan,
    block_by_id: Mapping[str, EvaluationBlock],
    analysis: AnalysisPlan,
    profile_by_id: Mapping[str, AgentProfile],
    run_spec: RunSpec,
) -> None:
    if run_spec.suite_id != suite.suite_id:
        raise PlanResolutionError(
            f"RunSpec suite {run_spec.suite_id!r} does not match {suite.suite_id!r}"
        )
    if sampling.sampling_plan_id != suite.sampling_plan_id:
        raise PlanResolutionError(
            f"missing sampling plan {suite.sampling_plan_id!r}"
        )
    if analysis.analysis_plan_id != suite.analysis_plan_id:
        raise PlanResolutionError(f"missing analysis plan {suite.analysis_plan_id!r}")

    missing_families = sorted(set(suite.family_ids) - set(family_by_id))
    if missing_families:
        raise PlanResolutionError(f"missing suite families: {missing_families}")
    missing_cases = sorted(set(suite.case_ids) - set(case_by_id))
    if missing_cases:
        raise PlanResolutionError(f"missing suite cases: {missing_cases}")
    missing_blocks = sorted(set(suite.evaluation_block_ids) - set(block_by_id))
    if missing_blocks:
        raise PlanResolutionError(f"missing suite evaluation blocks: {missing_blocks}")
    if tuple(run_spec.evaluation_block_ids) != tuple(suite.evaluation_block_ids):
        raise PlanResolutionError(
            "RunSpec evaluation_block_ids must exactly match SuiteManifest order"
        )
    missing_profiles = sorted(set(run_spec.agent_profile_ids) - set(profile_by_id))
    if missing_profiles:
        raise PlanResolutionError(f"missing agent profiles: {missing_profiles}")

    for case_id in suite.case_ids:
        case = case_by_id[case_id]
        family = family_by_id.get(case.family_id)
        if family is None or case.family_id not in suite.family_ids:
            raise PlanResolutionError(
                f"case {case_id!r} references unavailable family {case.family_id!r}"
            )
        if case.family_version != family.family.version:
            raise PlanResolutionError(
                f"case {case_id!r} family version {case.family_version!r} does not "
                f"match {family.family.version!r}"
            )
        invalid_roles = sorted(
            {seat.role for seat in case.seats} - set(family.roles)
        )
        if invalid_roles:
            raise PlanResolutionError(
                f"case {case_id!r} references unknown roles: {invalid_roles}"
            )
        seat_ids = {seat.id for seat in case.seats}
        assignment_ids = set(run_spec.seat_assignments)
        if seat_ids != assignment_ids:
            raise PlanResolutionError(
                f"case {case_id!r} seats and RunSpec seat_assignments differ: "
                f"case_only={sorted(seat_ids - assignment_ids)}, "
                f"run_only={sorted(assignment_ids - seat_ids)}"
            )
        for block_id in suite.evaluation_block_ids:
            block = block_by_id[block_id]
            unknown_subjects = sorted(set(block.subject_seats) - seat_ids)
            unknown_controls = sorted(set(block.controlled_profiles) - seat_ids)
            if unknown_subjects or unknown_controls:
                raise PlanResolutionError(
                    f"block {block_id!r} references unavailable seats: "
                    f"subjects={unknown_subjects}, controls={unknown_controls}"
                )
            control_mismatch = {
                seat_id: (profile_id, run_spec.seat_assignments[seat_id])
                for seat_id, profile_id in block.controlled_profiles.items()
                if run_spec.seat_assignments[seat_id] != profile_id
            }
            if control_mismatch:
                raise PlanResolutionError(
                    f"block {block_id!r} controlled profiles conflict with RunSpec: "
                    f"{control_mismatch}"
                )

    missing_estimands = sorted(
        {
            family_by_id[family_id].measurement.primary_estimand
            for family_id in suite.family_ids
        }
        - set(analysis.estimands)
    )
    if missing_estimands:
        raise PlanResolutionError(
            f"AnalysisPlan is missing family primary estimands: {missing_estimands}"
        )


def resolve_run_plan(
    *,
    families: Sequence[FamilyManifest],
    cases: Sequence[CaseManifest],
    suite: SuiteManifest,
    sampling: SamplingPlan,
    evaluation_blocks: Sequence[EvaluationBlock],
    analysis: AnalysisPlan,
    agent_profiles: Sequence[AgentProfile],
    run_spec: RunSpec,
    registry: PluginRegistry,
    implementation_pins: Sequence[ImplementationPin],
    harness_registry: HarnessRegistry,
    provider_capabilities: Mapping[str, ProviderCapabilities],
    tool_bindings: Mapping[str, frozenset[str]] | None = None,
) -> RunPlan:
    """Resolve, preflight, expand, and hash one provider-free R2 run plan."""
    if not isinstance(suite, SuiteManifest):
        raise PlanResolutionError("suite must be a SuiteManifest")
    if not isinstance(sampling, SamplingPlan):
        raise PlanResolutionError("sampling must be a SamplingPlan")
    if not isinstance(analysis, AnalysisPlan):
        raise PlanResolutionError("analysis must be an AnalysisPlan")
    if not isinstance(run_spec, RunSpec):
        raise PlanResolutionError("run_spec must be a RunSpec")
    if not isinstance(registry, PluginRegistry):
        raise PlanResolutionError("registry must be a PluginRegistry")
    if not isinstance(harness_registry, HarnessRegistry):
        raise PlanResolutionError("harness_registry must be a HarnessRegistry")
    for provider_id, capabilities in provider_capabilities.items():
        if not isinstance(capabilities, ProviderCapabilities):
            raise PlanResolutionError(
                f"provider_capabilities[{provider_id!r}] must be ProviderCapabilities"
            )

    family_by_id = _family_index(families)
    case_by_id = _index_unique(cases, "case_id", "case")
    block_by_id = _index_unique(evaluation_blocks, "block_id", "evaluation block")
    profile_by_id = _index_unique(agent_profiles, "profile_id", "agent profile")
    pin_by_id = _pin_index(implementation_pins)

    _validate_cross_references(
        family_by_id=family_by_id,
        case_by_id=case_by_id,
        suite=suite,
        sampling=sampling,
        block_by_id=block_by_id,
        analysis=analysis,
        profile_by_id=profile_by_id,
        run_spec=run_spec,
    )

    selected_families = tuple(family_by_id[family_id] for family_id in suite.family_ids)
    selected_cases = tuple(case_by_id[case_id] for case_id in suite.case_ids)
    selected_blocks = tuple(
        block_by_id[block_id] for block_id in suite.evaluation_block_ids
    )
    selected_profiles = tuple(
        profile_by_id[profile_id] for profile_id in sorted(run_spec.agent_profile_ids)
    )
    selected_pins = tuple(pin_by_id[component_id] for component_id in sorted(pin_by_id))

    for case in selected_cases:
        expected_digest = _case_digest_from_manifest(case)
        if case.content_sha256 != expected_digest:
            raise PlanResolutionError(
                f"case {case.case_id!r} content_sha256 mismatch: "
                f"declared={case.content_sha256}, computed={expected_digest}"
            )

    required_pins = _required_pin_kinds(selected_families, selected_profiles)
    _check_pins(required_pins, pin_by_id)

    # Capability admission (§5.3): sealed before any family plugin work, any
    # provider client, or any episode -- a failed combination is a typed
    # exclusion here, never an exception once an episode is under way.
    profile_admissions = _admit_profiles(
        selected_profiles,
        harness_registry=harness_registry,
        provider_capabilities=provider_capabilities,
        tool_bindings=tool_bindings or {},
    )

    plugin_by_family: dict[str, Any] = {}
    for family in selected_families:
        try:
            plugin_by_family[family.family.id] = registry.resolve_manifest(family)
        except PluginRegistryError as error:
            raise PlanResolutionError(
                f"cannot resolve family plugin for {family.family.id}: {error}"
            ) from error

    # Payload validation occurs only after every shared identity, digest, and pin
    # has passed, keeping invalid authoring inputs ahead of plugin work.
    for case in selected_cases:
        try:
            plugin_by_family[case.family_id].validate_payload(case.payload)
        except Exception as error:
            raise PlanResolutionError(
                f"family validate_payload failed for case {case.case_id!r}: {error}"
            ) from error

    drafts: list[dict[str, Any]] = []
    for case in selected_cases:
        family = family_by_id[case.family_id]
        for block in selected_blocks:
            for sampling_seed in sampling.seeds:
                context = _context_for_cell(
                    case=case,
                    family=family,
                    suite=suite,
                    block=block,
                    sampling=sampling,
                    run_spec=run_spec,
                    sampling_seed=sampling_seed,
                )
                cluster_fields = _select_fields(
                    sampling.cluster_id_fields, context, "cluster_id_fields"
                )
                paired_fields = _select_fields(
                    sampling.paired_fields, context, "paired_fields"
                )
                cluster_id = _cluster_id(sampling.cluster_level, cluster_fields)
                pair_id = _pair_id(paired_fields)
                for block_repetition in range(block.repetitions):
                    for sampling_replicate in range(sampling.replicates):
                        replicate_index = (
                            block_repetition * sampling.replicates
                            + sampling_replicate
                        )
                        drafts.append(
                            {
                                "spec_version": "aeread.plan_cell/0.1",
                                "case_id": case.case_id,
                                "case_sha256": case.content_sha256,
                                "family_id": family.family.id,
                                "family_version": family.family.version,
                                "suite_id": suite.suite_id,
                                "suite_version": suite.version,
                                "block_id": block.block_id,
                                "sampling_plan_id": sampling.sampling_plan_id,
                                "analysis_plan_id": analysis.analysis_plan_id,
                                "world_seed": case.world_seed,
                                "sampling_seed": sampling_seed,
                                "block_repetition": block_repetition,
                                "sampling_replicate": sampling_replicate,
                                "replicate_index": replicate_index,
                                "cluster_id": cluster_id,
                                "cluster_level": sampling.cluster_level,
                                "pair_id": pair_id,
                                "paired_fields": paired_fields,
                                "panel_mode": sampling.panel_mode,
                                "profile_by_seat": MappingProxyType(
                                    dict(sorted(run_spec.seat_assignments.items()))
                                ),
                                "execution_mode": run_spec.execution_mode,
                                "case_max_logical_actions": case.episode.max_logical_actions,
                            }
                        )

    cluster_counts: dict[str, int] = {}
    for draft in drafts:
        cluster_id = draft["cluster_id"]
        cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1

    cells: list[PlanCell] = []
    for draft in drafts:
        completed = {
            **draft,
            "observations_per_cluster": cluster_counts[draft["cluster_id"]],
        }
        cell_id = "cell_" + _digest(completed)[:20]
        cells.append(PlanCell(cell_id=cell_id, **completed))
    cells.sort(key=lambda cell: cell.cell_id)

    input_digests = _input_digests(
        families=selected_families,
        cases=selected_cases,
        suite=suite,
        sampling=sampling,
        blocks=selected_blocks,
        analysis=analysis,
        profiles=selected_profiles,
        run_spec=run_spec,
        pins=selected_pins,
    )
    provisional = RunPlan(
        spec_version="aeread.run_plan/0.1",
        run_plan_id="",
        plan_sha256="",
        families=selected_families,
        cases=selected_cases,
        suite=suite,
        sampling=sampling,
        evaluation_blocks=selected_blocks,
        analysis=analysis,
        agent_profiles=selected_profiles,
        run_spec=run_spec,
        implementation_pins=selected_pins,
        input_digests=input_digests,
        cells=tuple(cells),
        profile_admissions=profile_admissions,
    )
    return _seal_plan(provisional)


def verify_run_plan(plan: RunPlan) -> None:
    """Fail if the plan digest, plan ID, case digests, cell IDs, or admission
    IDs drifted."""
    if not isinstance(plan, RunPlan):
        raise TypeError("plan must be a RunPlan")
    expected_plan_sha256 = _digest(_plan_payload(plan))
    if plan.plan_sha256 != expected_plan_sha256:
        raise PlanIntegrityError(
            f"plan_sha256 mismatch: declared={plan.plan_sha256}, "
            f"computed={expected_plan_sha256}"
        )
    expected_plan_id = f"runplan_{expected_plan_sha256[:16]}"
    if plan.run_plan_id != expected_plan_id:
        raise PlanIntegrityError(
            f"run_plan_id mismatch: declared={plan.run_plan_id!r}, "
            f"computed={expected_plan_id!r}"
        )
    for case in plan.cases:
        expected_case_sha256 = _case_digest_from_manifest(case)
        if case.content_sha256 != expected_case_sha256:
            raise PlanIntegrityError(
                f"case {case.case_id!r} content_sha256 mismatch"
            )
    for cell in plan.cells:
        cell_payload = _canonical_value(cell)
        declared_cell_id = cell_payload.pop("cell_id")
        expected_cell_id = "cell_" + _digest(cell_payload)[:20]
        if declared_cell_id != expected_cell_id:
            raise PlanIntegrityError(
                f"cell_id mismatch: declared={declared_cell_id!r}, "
                f"computed={expected_cell_id!r}"
            )
    for admission in plan.profile_admissions:
        admission_payload = _canonical_value(admission)
        declared_admission_id = admission_payload.pop("admission_id")
        expected_admission_id = "admission_" + _digest(admission_payload)[:20]
        if declared_admission_id != expected_admission_id:
            raise PlanIntegrityError(
                f"admission_id mismatch: declared={declared_admission_id!r}, "
                f"computed={expected_admission_id!r}"
            )


def write_run_plan(plan: RunPlan, destination: str | Path) -> Path:
    """Durably publish canonical plan bytes without overwriting an existing plan."""
    verify_run_plan(plan)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(plan)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, path)
        temporary_path.unlink()
        temporary_path = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = [
    "CapabilityExclusionError",
    "ImplementationPin",
    "PlanCell",
    "PlanIntegrityError",
    "PlanResolutionError",
    "ProfileAdmission",
    "RunPlan",
    "canonical_json_bytes",
    "case_content_sha256",
    "resolve_run_plan",
    "KERNEL_COMPONENT_PREFIX",
    "is_kernel_pin",
    "plan_with_pins",
    "plan_with_recorded_pins",
    "verify_run_plan",
    "write_run_plan",
]
