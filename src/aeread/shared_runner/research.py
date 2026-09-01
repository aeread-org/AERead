"""Receipt-derived research views and experimental-design preflight.

The canonical shared-runner records remain ``RunPlan``, ``Event`` and
``EvaluationReceipt``. This module projects those records into query-friendly
campaign, cell, attempt and event rows without making the projections a second
source of benchmark truth.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .execution import EvidenceSeal, EvidenceStore, Event
from .measurement import (
    EstimandSpec,
    ImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from .receipts import (
    EvaluationFailure,
    EvaluationReceipt,
    read_evaluation_receipt,
    verify_evaluation_receipt,
)
from .resolver import (
    ImplementationPin,
    PlanCell,
    ProfileAdmission,
    RunPlan,
    canonical_json_bytes,
    verify_run_plan,
)
from .schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
    is_exportable_id,
    parse_authoring_record,
)


class ResearchContractError(ValueError):
    """Research projections would be incomplete, ambiguous or confounded."""


def _require_id(value: object, label: str) -> str:
    if not is_exportable_id(value):
        raise ResearchContractError(f"{label} must be an exportable identifier")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchContractError(f"{label} must be a non-empty string")
    return value


def _freeze_factors(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ResearchContractError("design factors must be a non-empty mapping")
    frozen: dict[str, str] = {}
    for name, level in sorted(value.items()):
        frozen[_require_id(name, "factor name")] = _require_text(
            level, f"factor {name!r} level"
        )
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class DesignObservation:
    """One independent design row with explicit treatment/nuisance factors."""

    observation_id: str
    cluster_id: str
    factors: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_id(self.observation_id, "observation_id")
        _require_id(self.cluster_id, "cluster_id")
        object.__setattr__(self, "factors", _freeze_factors(self.factors))


@dataclass(frozen=True, slots=True)
class DesignIssue:
    code: str
    factor: str | None
    message: str

    def __post_init__(self) -> None:
        _require_id(self.code, "design issue code")
        if self.factor is not None:
            _require_id(self.factor, "design issue factor")
        _require_text(self.message, "design issue message")


@dataclass(frozen=True, slots=True)
class DesignAudit:
    status: str
    issues: tuple[DesignIssue, ...]

    def __post_init__(self) -> None:
        if self.status not in {"valid", "invalid"}:
            raise ResearchContractError("design audit status must be valid or invalid")
        if self.status == "valid" and self.issues:
            raise ResearchContractError("valid design audit cannot contain issues")
        if self.status == "invalid" and not self.issues:
            raise ResearchContractError("invalid design audit requires issues")


def _factor_names(values: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(_require_id(value, label) for value in values)
    if len(result) != len(set(result)):
        raise ResearchContractError(f"{label} contains duplicate factors")
    return result


def audit_experimental_design(
    observations: Sequence[DesignObservation],
    *,
    focal_factors: Sequence[str],
    nuisance_factors: Sequence[str],
    minimum_clusters_per_level: int,
) -> DesignAudit:
    """Detect missing overlap, under-clustering and perfect factor aliasing.

    This structural audit does not claim that a design is powered or causal. It
    rejects layouts where a requested contrast is not identified before model
    calls are purchased.
    """

    rows = tuple(observations)
    if not rows or any(not isinstance(row, DesignObservation) for row in rows):
        raise ResearchContractError(
            "observations must contain at least one DesignObservation"
        )
    identifiers = [row.observation_id for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ResearchContractError("design observation IDs must be unique")
    if (
        isinstance(minimum_clusters_per_level, bool)
        or not isinstance(minimum_clusters_per_level, int)
        or minimum_clusters_per_level < 1
    ):
        raise ResearchContractError("minimum_clusters_per_level must be at least one")

    focal = _factor_names(focal_factors, "focal_factors")
    nuisance = _factor_names(nuisance_factors, "nuisance_factors")
    if not focal:
        raise ResearchContractError("focal_factors must not be empty")
    shared = sorted(set(focal) & set(nuisance))
    if shared:
        raise ResearchContractError(
            f"focal and nuisance factors overlap: {shared}"
        )
    required = set(focal) | set(nuisance)
    for row in rows:
        missing = sorted(required - set(row.factors))
        if missing:
            raise ResearchContractError(
                f"observation {row.observation_id!r} is missing factors: {missing}"
            )

    issues: list[DesignIssue] = []
    levels_by_factor = {
        factor: tuple(sorted({row.factors[factor] for row in rows}))
        for factor in focal
    }
    for factor, levels in levels_by_factor.items():
        if len(levels) < 2:
            issues.append(
                DesignIssue(
                    "single_level",
                    factor,
                    f"factor {factor!r} has fewer than two observed levels",
                )
            )
        for level in levels:
            clusters = {
                row.cluster_id for row in rows if row.factors[factor] == level
            }
            if len(clusters) < minimum_clusters_per_level:
                issues.append(
                    DesignIssue(
                        "insufficient_clusters",
                        factor,
                        f"level {level!r} has {len(clusters)} independent clusters; "
                        f"requires {minimum_clusters_per_level}",
                    )
                )

        if nuisance and len(levels) >= 2:
            strata: dict[tuple[str, ...], set[str]] = {}
            for row in rows:
                key = tuple(row.factors[name] for name in nuisance)
                strata.setdefault(key, set()).add(row.factors[factor])
            overlapping = [present for present in strata.values() if len(present) >= 2]
            if not overlapping:
                issues.append(
                    DesignIssue(
                        "no_overlap",
                        factor,
                        f"factor {factor!r} never varies within a common nuisance stratum",
                    )
                )
            else:
                covered = set().union(*overlapping)
                for level in sorted(set(levels) - covered):
                    issues.append(
                        DesignIssue(
                            "level_no_overlap",
                            factor,
                            f"level {level!r} has no comparison within a nuisance stratum",
                        )
                    )

    for left_index, left in enumerate(focal):
        for right in focal[left_index + 1 :]:
            left_levels = levels_by_factor[left]
            right_levels = levels_by_factor[right]
            if len(left_levels) < 2 or len(right_levels) < 2:
                continue
            left_to_right: dict[str, set[str]] = {}
            right_to_left: dict[str, set[str]] = {}
            for row in rows:
                left_level = row.factors[left]
                right_level = row.factors[right]
                left_to_right.setdefault(left_level, set()).add(right_level)
                right_to_left.setdefault(right_level, set()).add(left_level)
            if all(len(values) == 1 for values in left_to_right.values()) and all(
                len(values) == 1 for values in right_to_left.values()
            ):
                issues.append(
                    DesignIssue(
                        "perfect_alias",
                        left,
                        f"factors {left!r} and {right!r} are perfectly aliased",
                    )
                )

    canonical_issues = tuple(
        sorted(issues, key=lambda issue: (issue.code, issue.factor or "", issue.message))
    )
    return DesignAudit("invalid" if canonical_issues else "valid", canonical_issues)


@dataclass(frozen=True, slots=True)
class CampaignResearchRow:
    run_plan_id: str
    run_plan_sha256: str
    suite_id: str
    suite_version: str
    run_spec_id: str
    harness_by_profile: Mapping[str, str]
    runtime_by_profile: Mapping[str, str]
    price_catalog_by_profile: Mapping[str, str | None]
    expected_cells: int
    receipted_cells: int
    included_cells: int
    excluded_cells: int
    not_started_cells: int
    receipt_attempts: int
    coverage: float


@dataclass(frozen=True, slots=True)
class CellResearchRow:
    run_plan_id: str
    cell_id: str
    case_id: str
    family_id: str
    block_id: str
    cluster_id: str
    cluster_level: str
    pair_id: str | None
    replicate_index: int
    profile_by_seat: Mapping[str, str]
    status: str
    receipt_count: int
    included_receipt_sha256: str | None
    repeat_equivalence_sha256: str


@dataclass(frozen=True, slots=True)
class AttemptResearchRow:
    run_plan_id: str
    cell_id: str
    episode_id: str
    episode_attempt_id: str
    receipt_sha256: str
    status: str
    inclusion_status: str
    failure_class: str | None
    failure_condition: str | None
    replay_level: str
    primary_leaf_id: str
    primary_value: float | None
    primary_unit: str | None
    event_count: int
    artifact_count: int
    event_root_sha256: str
    artifact_root_sha256: str


@dataclass(frozen=True, slots=True)
class ResearchLedger:
    campaign: CampaignResearchRow
    cells: tuple[CellResearchRow, ...]
    attempts: tuple[AttemptResearchRow, ...]


def _profile_sha256(profile: AgentProfile) -> str:
    return hashlib.sha256(canonical_json_bytes(profile)).hexdigest()


def _profile_labels(
    profiles: Sequence[AgentProfile],
) -> tuple[Mapping[str, str], Mapping[str, str], Mapping[str, str | None]]:
    harnesses: dict[str, str] = {}
    runtimes: dict[str, str] = {}
    prices: dict[str, str | None] = {}
    for profile in sorted(profiles, key=lambda item: item.profile_id):
        harnesses[profile.profile_id] = f"{profile.harness.id}@{profile.harness.version}"
        runtimes[profile.profile_id] = (
            f"{profile.runtime.implementation}@{profile.runtime.version}"
        )
        pricing_id = profile.harness.config.get("pricing_id")
        pricing_sha256 = profile.harness.config.get("pricing_sha256")
        if pricing_id is None and pricing_sha256 is None:
            prices[profile.profile_id] = None
        elif (
            isinstance(pricing_id, str)
            and pricing_id
            and isinstance(pricing_sha256, str)
            and len(pricing_sha256) == 64
            and all(character in "0123456789abcdef" for character in pricing_sha256)
        ):
            prices[profile.profile_id] = f"{pricing_id}@sha256:{pricing_sha256}"
        else:
            raise ResearchContractError(
                f"profile {profile.profile_id!r} has incomplete pricing identity"
            )
    return (
        MappingProxyType(harnesses),
        MappingProxyType(runtimes),
        MappingProxyType(prices),
    )


def _repeat_equivalence_sha256(plan: RunPlan, cell: Any) -> str:
    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    profile_payload = {
        seat: profiles[profile_id]
        for seat, profile_id in sorted(cell.profile_by_seat.items())
    }
    payload = {
        "case_id": cell.case_id,
        "case_sha256": cell.case_sha256,
        "family_id": cell.family_id,
        "family_version": cell.family_version,
        "suite_id": cell.suite_id,
        "suite_version": cell.suite_version,
        "block_id": cell.block_id,
        "world_seed": cell.world_seed,
        "cluster_id": cell.cluster_id,
        "cluster_level": cell.cluster_level,
        "pair_id": cell.pair_id,
        "paired_fields": cell.paired_fields,
        "panel_mode": cell.panel_mode,
        "execution_mode": cell.execution_mode,
        "case_max_logical_actions": cell.case_max_logical_actions,
        "profiles_by_seat": profile_payload,
        "implementation_pins": plan.implementation_pins,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _validate_receipt_against_plan(
    plan: RunPlan,
    receipt: EvaluationReceipt,
    cells_by_id: Mapping[str, Any],
    profiles_by_id: Mapping[str, AgentProfile],
) -> None:
    try:
        verify_evaluation_receipt(receipt)
    except Exception as error:
        raise ResearchContractError("research ledger requires verified receipts") from error
    if (
        receipt.run_plan_id != plan.run_plan_id
        or receipt.run_plan_sha256 != plan.plan_sha256
    ):
        raise ResearchContractError("receipt does not belong to this RunPlan")
    cell = cells_by_id.get(receipt.cell_id)
    if cell is None:
        raise ResearchContractError(f"receipt references unknown cell {receipt.cell_id!r}")
    expected = {
        "case_id": cell.case_id,
        "case_sha256": cell.case_sha256,
        "suite_id": cell.suite_id,
        "suite_version": cell.suite_version,
        "block_id": cell.block_id,
        "sampling_plan_id": cell.sampling_plan_id,
        "analysis_plan_id": cell.analysis_plan_id,
        "cluster_id": cell.cluster_id,
        "cluster_level": cell.cluster_level,
        "observations_per_cluster": cell.observations_per_cluster,
        "pair_id": cell.pair_id,
        "replicate_index": cell.replicate_index,
        "panel_mode": cell.panel_mode,
    }
    mismatches = {
        name: (value, getattr(receipt, name))
        for name, value in expected.items()
        if getattr(receipt, name) != value
    }
    if receipt.paired_fields != cell.paired_fields:
        mismatches["paired_fields"] = (cell.paired_fields, receipt.paired_fields)
    expected_profile_hashes = {
        seat: _profile_sha256(profiles_by_id[profile_id])
        for seat, profile_id in cell.profile_by_seat.items()
    }
    if dict(receipt.agent_profile_sha256_by_seat) != expected_profile_hashes:
        mismatches["agent_profile_sha256_by_seat"] = (
            expected_profile_hashes,
            receipt.agent_profile_sha256_by_seat,
        )
    if receipt.plan_implementation_pins != plan.implementation_pins:
        mismatches["plan_implementation_pins"] = (
            plan.implementation_pins,
            receipt.plan_implementation_pins,
        )
    if mismatches:
        raise ResearchContractError(
            f"receipt and planned cell identities differ: {sorted(mismatches)}"
        )


def _attempt_row(receipt: EvaluationReceipt) -> AttemptResearchRow:
    primary = next(
        (score for score in receipt.scores if score.leaf.leaf_id == receipt.primary_leaf_id),
        None,
    )
    metric = None if primary is None else primary.primary
    failure = receipt.failure
    assert receipt.receipt_sha256 is not None
    return AttemptResearchRow(
        run_plan_id=receipt.run_plan_id,
        cell_id=receipt.cell_id,
        episode_id=receipt.episode_id,
        episode_attempt_id=receipt.episode_attempt_id,
        receipt_sha256=receipt.receipt_sha256,
        status=receipt.status,
        inclusion_status=receipt.inclusion_status,
        failure_class=None if failure is None else failure.failure_class,
        failure_condition=None if failure is None else failure.condition,
        replay_level=receipt.replay_level,
        primary_leaf_id=receipt.primary_leaf_id,
        primary_value=None if metric is None else metric.value,
        primary_unit=None if metric is None else metric.unit,
        event_count=receipt.evidence.event_count,
        artifact_count=receipt.evidence.artifact_count,
        event_root_sha256=receipt.evidence.event_root_sha256,
        artifact_root_sha256=receipt.evidence.artifact_root_sha256,
    )


def build_research_ledger(
    plan: RunPlan,
    receipts: Sequence[EvaluationReceipt],
) -> ResearchLedger:
    """Project a complete planned-cell grid plus every verified receipt attempt."""

    try:
        verify_run_plan(plan)
    except Exception as error:
        raise ResearchContractError("research ledger requires a verified RunPlan") from error
    receipt_values = tuple(receipts)
    if any(not isinstance(receipt, EvaluationReceipt) for receipt in receipt_values):
        raise ResearchContractError("receipts must contain only EvaluationReceipt values")
    cells_by_id = {cell.cell_id: cell for cell in plan.cells}
    profiles_by_id = {profile.profile_id: profile for profile in plan.agent_profiles}
    by_cell: dict[str, list[EvaluationReceipt]] = {
        cell.cell_id: [] for cell in plan.cells
    }
    receipt_digests: set[str] = set()
    attempt_ids: set[str] = set()
    for receipt in receipt_values:
        _validate_receipt_against_plan(plan, receipt, cells_by_id, profiles_by_id)
        assert receipt.receipt_sha256 is not None
        if receipt.receipt_sha256 in receipt_digests:
            raise ResearchContractError("duplicate receipt digest in research ledger")
        if receipt.episode_attempt_id in attempt_ids:
            raise ResearchContractError("duplicate episode_attempt_id in research ledger")
        receipt_digests.add(receipt.receipt_sha256)
        attempt_ids.add(receipt.episode_attempt_id)
        by_cell[receipt.cell_id].append(receipt)

    cell_rows: list[CellResearchRow] = []
    for cell in sorted(plan.cells, key=lambda item: item.cell_id):
        attempts = sorted(
            by_cell[cell.cell_id], key=lambda item: item.episode_attempt_id
        )
        included = [item for item in attempts if item.inclusion_status == "included"]
        if len(included) > 1:
            raise ResearchContractError(
                f"cell {cell.cell_id!r} has multiple included receipts"
            )
        status = "included" if included else ("excluded" if attempts else "not_started")
        cell_rows.append(
            CellResearchRow(
                run_plan_id=plan.run_plan_id,
                cell_id=cell.cell_id,
                case_id=cell.case_id,
                family_id=cell.family_id,
                block_id=cell.block_id,
                cluster_id=cell.cluster_id,
                cluster_level=cell.cluster_level,
                pair_id=cell.pair_id,
                replicate_index=cell.replicate_index,
                profile_by_seat=MappingProxyType(dict(cell.profile_by_seat)),
                status=status,
                receipt_count=len(attempts),
                included_receipt_sha256=(
                    None if not included else included[0].receipt_sha256
                ),
                repeat_equivalence_sha256=_repeat_equivalence_sha256(plan, cell),
            )
        )

    attempts = tuple(
        _attempt_row(receipt)
        for receipt in sorted(
            receipt_values, key=lambda item: (item.cell_id, item.episode_attempt_id)
        )
    )
    harnesses, runtimes, prices = _profile_labels(plan.agent_profiles)
    included_cells = sum(row.status == "included" for row in cell_rows)
    excluded_cells = sum(row.status == "excluded" for row in cell_rows)
    not_started_cells = sum(row.status == "not_started" for row in cell_rows)
    receipted_cells = len(cell_rows) - not_started_cells
    expected_cells = len(cell_rows)
    campaign = CampaignResearchRow(
        run_plan_id=plan.run_plan_id,
        run_plan_sha256=plan.plan_sha256,
        suite_id=plan.suite.suite_id,
        suite_version=plan.suite.version,
        run_spec_id=plan.run_spec.run_spec_id,
        harness_by_profile=harnesses,
        runtime_by_profile=runtimes,
        price_catalog_by_profile=prices,
        expected_cells=expected_cells,
        receipted_cells=receipted_cells,
        included_cells=included_cells,
        excluded_cells=excluded_cells,
        not_started_cells=not_started_cells,
        receipt_attempts=len(attempts),
        coverage=0.0 if expected_cells == 0 else receipted_cells / expected_cells,
    )
    return ResearchLedger(campaign, tuple(cell_rows), attempts)


@dataclass(frozen=True, slots=True)
class EventResearchRow:
    event_id: str
    sequence: int
    event_type: str
    harness_phase: str
    domain_phase_id: str | None
    domain_phase_instance_id: str | None
    logical_action_id: str | None
    action_attempt_id: str | None
    provider_call_id: str | None
    tool_invocation_id: str | None
    visibility: str
    payload_sha256: str


_FINALIZATION_EVENTS = {
    "transition_applied",
    "phase_instance_succeeded",
    "episode_terminated",
    "family_outcome_recorded",
}
_EXECUTION_EVENT_PREFIXES = (
    "logical_action_",
    "action_attempt_",
    "provider_call_",
    "tool_invocation_",
)
_EXECUTION_EVENTS = {"action_parsed", "action_legality_checked"}


def _harness_phase(
    event: Event,
    recovery_attempt_ids: set[str],
) -> str:
    if event.event_type == "phase_instance_started":
        return "planning"
    if event.event_type in _FINALIZATION_EVENTS:
        return "finalization"
    if event.action_attempt_id in recovery_attempt_ids:
        return "recovery"
    if event.event_type in _EXECUTION_EVENTS or event.event_type.startswith(
        _EXECUTION_EVENT_PREFIXES
    ):
        return "execution"
    raise ResearchContractError(
        f"event type {event.event_type!r} has no declared harness phase"
    )


def project_evidence_events(evidence: EvidenceStore) -> tuple[EventResearchRow, ...]:
    """Project evidence events with independent operational and domain phases."""

    if not isinstance(evidence, EvidenceStore):
        raise ResearchContractError("evidence must be an EvidenceStore")
    try:
        evidence.verify_chain()
        events = evidence.read_events()
        payloads = {event.event_id: evidence.read_event_payload(event) for event in events}
    except Exception as error:
        raise ResearchContractError("event projection requires valid evidence") from error

    phase_by_instance: dict[str, str] = {}
    recovery_attempt_ids: set[str] = set()
    for event in events:
        payload = payloads[event.event_id]
        if event.event_type == "phase_instance_started":
            phase = payload.get("phase") if isinstance(payload, Mapping) else None
            phase_id = phase.get("phase_id") if isinstance(phase, Mapping) else None
            if event.phase_instance_id is None or not isinstance(phase_id, str) or not phase_id:
                raise ResearchContractError(
                    "phase_instance_started must declare phase instance and phase IDs"
                )
            phase_by_instance[event.phase_instance_id] = phase_id
        elif (
            event.phase_instance_id is not None
            and isinstance(payload, Mapping)
            and isinstance(payload.get("phase_id"), str)
        ):
            observed = payload["phase_id"]
            previous = phase_by_instance.get(event.phase_instance_id)
            if previous is not None and previous != observed:
                raise ResearchContractError("domain phase identity changed within an instance")
            phase_by_instance[event.phase_instance_id] = observed
        if event.event_type == "action_attempt_started" and isinstance(payload, Mapping):
            if payload.get("retry_reason") is not None:
                if event.action_attempt_id is None:
                    raise ResearchContractError("recovery attempt has no action_attempt_id")
                recovery_attempt_ids.add(event.action_attempt_id)

    rows: list[EventResearchRow] = []
    for event in events:
        if (
            event.phase_instance_id is not None
            and event.phase_instance_id not in phase_by_instance
        ):
            raise ResearchContractError(
                f"event {event.event_id!r} references an undeclared domain phase instance"
            )
        rows.append(
            EventResearchRow(
                event_id=event.event_id,
                sequence=event.sequence,
                event_type=event.event_type,
                harness_phase=_harness_phase(event, recovery_attempt_ids),
                domain_phase_id=(
                    None
                    if event.phase_instance_id is None
                    else phase_by_instance[event.phase_instance_id]
                ),
                domain_phase_instance_id=event.phase_instance_id,
                logical_action_id=event.logical_action_id,
                action_attempt_id=event.action_attempt_id,
                provider_call_id=event.provider_call_id,
                tool_invocation_id=event.tool_invocation_id,
                visibility=event.visibility,
                payload_sha256=event.payload_sha256,
            )
        )
    return tuple(rows)


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain(item) for item in value)
    return value


def research_tables(
    ledger: ResearchLedger,
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """Return deterministic table projections; receipts/events remain canonical."""

    if not isinstance(ledger, ResearchLedger):
        raise ResearchContractError("ledger must be a ResearchLedger")
    return MappingProxyType(
        {
            "campaigns": (MappingProxyType(_plain(ledger.campaign)),),
            "cells": tuple(MappingProxyType(_plain(row)) for row in ledger.cells),
            "attempts": tuple(MappingProxyType(_plain(row)) for row in ledger.attempts),
        }
    )


# ---------------------------------------------------------------------------
# Run -> task -> model-call loss-analysis projection.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    benchmark_id: str
    benchmark_version: str
    model_name: str
    harness_name: str
    runner_version: str
    tasks_expected: int
    tasks_executed: int
    tasks_passed: int
    tasks_failed: int
    tasks_not_started: int
    call_count: int
    exception_count: int
    prompt_tokens: int | None
    cached_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    total_cost_usd: float | None
    latency_seconds: float | None
    telemetry_complete: bool


@dataclass(frozen=True, slots=True)
class TaskRecord:
    run_id: str
    task_id: str
    case_id: str
    task_family: str
    difficulty_band: str | None
    task_status: str
    passed: bool | None
    exception_count: int
    call_count: int
    prompt_tokens: int | None
    cached_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    latency_seconds: float | None
    telemetry_complete: bool
    error: str | None
    episode_attempt_id: str | None
    receipt_sha256: str | None


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    call_id: str
    run_id: str
    task_id: str
    call_index: int
    seat_id: str | None
    profile_id: str | None
    harness_phase: str
    domain_phase_id: str | None
    provider: str | None
    requested_model: str | None
    resolved_model: str | None
    status: str
    occurred_at: str
    prompt_tokens: int | None
    cached_tokens: int | None
    completion_tokens: int | None
    latency_seconds: float | None
    exception_type: str | None
    total_cost_usd: float | None
    telemetry_complete: bool


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    step_index: int
    event_id: str
    occurred_at: str
    event_type: str
    harness_phase: str | None
    domain_phase_id: str | None
    domain_phase_instance_id: str | None
    seat_id: str | None
    logical_action_id: str | None
    action_attempt_id: str | None
    provider_call_id: str | None
    tool_invocation_id: str | None
    tool_name: str | None
    messages: Any | None
    input: Any | None
    output: Any | None
    prompt_tokens: int | None
    cached_tokens: int | None
    completion_tokens: int | None
    error: str | None
    payload: Any


@dataclass(frozen=True, slots=True)
class TrajectoryRecord:
    run_id: str
    task_id: str
    episode_id: str
    episode_attempt_id: str
    task_status: str
    passed: bool | None
    receipt_sha256: str | None
    event_root_sha256: str | None
    steps: tuple[TrajectoryStep, ...]


@dataclass(frozen=True, slots=True)
class LossAnalysisTables:
    runs: tuple[RunRecord, ...]
    tasks: tuple[TaskRecord, ...]
    model_calls: tuple[ModelCallRecord, ...]


@dataclass(frozen=True, slots=True)
class ProfileFactRecord:
    """One sealed execution profile, flattened for reuse and comparison."""

    run_id: str
    run_plan_sha256: str
    profile_id: str
    profile_sha256: str
    admission_id: str
    admitted: bool
    provider: str
    requested_model: str
    model_revision: str | None
    model_base_url: str | None
    harness_id: str
    harness_version: str
    harness_config: Mapping[str, Any]
    prompt_id: str
    prompt_sha256: str
    runtime_kind: str
    runtime_implementation: str
    runtime_version: str
    tools: tuple[str, ...]
    memory_mode: str
    memory_implementation: str | None
    reasoning_condition_id: str
    reasoning_effort: str | None
    reasoning_token_budget: int | None
    rationale_visibility: str
    temperature: float
    top_p: float | None
    seed: int | None
    max_output_tokens: int
    max_logical_actions: int
    timeout_seconds: float
    max_cost_usd: float | None
    max_action_attempts: int
    retryable_conditions: tuple[str, ...]
    retry_session_mode: str
    sdk_retries: int


@dataclass(frozen=True, slots=True)
class ModelFeatureFactRecord:
    """One long-form, provenance-qualified model/profile feature fact."""

    fact_id: str
    run_id: str
    profile_id: str
    profile_sha256: str
    provider: str
    requested_model: str
    model_revision: str | None
    harness_id: str
    feature_name: str
    feature_value: bool
    evidence_class: str
    source_kind: str
    source_id: str
    source_sha256: str
    reportable: bool


@dataclass(frozen=True, slots=True)
class BenchmarkResultFactRecord:
    """One typed metric from one verified evaluation-receipt attempt."""

    fact_id: str
    run_id: str
    task_id: str
    case_id: str
    family_id: str
    block_id: str
    episode_attempt_id: str
    receipt_sha256: str
    inclusion_status: str
    leaf_id: str
    leaf_version: str
    estimand_id: str
    estimand_version: str
    metric_role: str
    metric_name: str
    seat_id: str | None
    value: float | None
    unit: str | None
    metric_metadata: Mapping[str, Any]
    score_status: str
    validity_status: str
    validity_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_kind: str
    source_id: str
    source_sha256: str
    reportable: bool


@dataclass(frozen=True, slots=True)
class CanonicalFactTables:
    """Digest-ready fact projections; sealed inputs remain authoritative."""

    profiles: tuple[ProfileFactRecord, ...]
    model_features: tuple[ModelFeatureFactRecord, ...]
    benchmark_results: tuple[BenchmarkResultFactRecord, ...]


def _fact_id(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}_" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:24]


def _profile_fact(
    plan: RunPlan,
    profile: AgentProfile,
    admission: ProfileAdmission,
) -> ProfileFactRecord:
    profile_sha256 = hashlib.sha256(canonical_json_bytes(profile)).hexdigest()
    return ProfileFactRecord(
        run_id=plan.run_plan_id,
        run_plan_sha256=plan.plan_sha256,
        profile_id=profile.profile_id,
        profile_sha256=profile_sha256,
        admission_id=admission.admission_id,
        admitted=admission.admitted,
        provider=profile.model.provider,
        requested_model=profile.model.model,
        model_revision=profile.model.revision,
        model_base_url=profile.model.base_url,
        harness_id=profile.harness.id,
        harness_version=profile.harness.version,
        harness_config=profile.harness.config,
        prompt_id=profile.prompt.prompt_id,
        prompt_sha256=profile.prompt.sha256,
        runtime_kind=profile.runtime.kind,
        runtime_implementation=profile.runtime.implementation,
        runtime_version=profile.runtime.version,
        tools=profile.tools,
        memory_mode=profile.memory.mode,
        memory_implementation=profile.memory.implementation,
        reasoning_condition_id=profile.reasoning.condition_id,
        reasoning_effort=profile.reasoning.effort,
        reasoning_token_budget=profile.reasoning.token_budget,
        rationale_visibility=profile.reasoning.rationale_visibility,
        temperature=profile.sampling.temperature,
        top_p=profile.sampling.top_p,
        seed=profile.sampling.seed,
        max_output_tokens=profile.sampling.max_output_tokens,
        max_logical_actions=profile.budgets.max_logical_actions,
        timeout_seconds=profile.budgets.timeout_seconds,
        max_cost_usd=profile.budgets.max_cost_usd,
        max_action_attempts=profile.retry_policy.max_action_attempts,
        retryable_conditions=profile.retry_policy.retryable_conditions,
        retry_session_mode=profile.retry_policy.session_mode,
        sdk_retries=profile.retry_policy.sdk_retries,
    )


def _model_feature_facts(
    plan: RunPlan,
    profile: AgentProfile,
    admission: ProfileAdmission,
) -> tuple[ModelFeatureFactRecord, ...]:
    profile_sha256 = hashlib.sha256(canonical_json_bytes(profile)).hexdigest()
    rows: list[ModelFeatureFactRecord] = []
    for feature_name, feature_value in sorted(admission.capability_vector.items()):
        identity = {
            "admission_id": admission.admission_id,
            "feature_name": feature_name,
            "feature_value": feature_value,
        }
        rows.append(
            ModelFeatureFactRecord(
                fact_id=_fact_id("feature", identity),
                run_id=plan.run_plan_id,
                profile_id=profile.profile_id,
                profile_sha256=profile_sha256,
                provider=profile.model.provider,
                requested_model=profile.model.model,
                model_revision=profile.model.revision,
                harness_id=profile.harness.id,
                feature_name=feature_name,
                feature_value=feature_value,
                evidence_class="admission_derived",
                source_kind="profile_admission",
                source_id=admission.admission_id,
                source_sha256=plan.plan_sha256,
                reportable=admission.admitted,
            )
        )
    return tuple(rows)


def _result_fact(
    receipt: EvaluationReceipt,
    *,
    family_id: str,
    score: ScoreEnvelope,
    metric_role: str,
    metric_name: str,
    metric: MetricValue | None,
    seat_id: str | None,
) -> BenchmarkResultFactRecord:
    assert receipt.receipt_sha256 is not None
    identity = {
        "receipt_sha256": receipt.receipt_sha256,
        "leaf_id": score.leaf.leaf_id,
        "metric_role": metric_role,
        "metric_name": metric_name,
        "seat_id": seat_id,
    }
    return BenchmarkResultFactRecord(
        fact_id=_fact_id("result", identity),
        run_id=receipt.run_plan_id,
        task_id=receipt.cell_id,
        case_id=receipt.case_id,
        family_id=family_id,
        block_id=receipt.block_id,
        episode_attempt_id=receipt.episode_attempt_id,
        receipt_sha256=receipt.receipt_sha256,
        inclusion_status=receipt.inclusion_status,
        leaf_id=score.leaf.leaf_id,
        leaf_version=score.leaf.leaf_version,
        estimand_id=score.leaf.estimand.estimand_id,
        estimand_version=score.leaf.estimand.estimand_version,
        metric_role=metric_role,
        metric_name=metric_name,
        seat_id=seat_id,
        value=None if metric is None else metric.value,
        unit=None if metric is None else metric.unit,
        metric_metadata=MappingProxyType(
            {} if metric is None else dict(metric.metadata)
        ),
        score_status=score.status,
        validity_status=score.validity.status,
        validity_reasons=score.validity.reasons,
        evidence_refs=score.evidence_refs,
        source_kind="evaluation_receipt",
        source_id=receipt.episode_attempt_id,
        source_sha256=receipt.receipt_sha256,
        reportable=(
            receipt.inclusion_status == "included"
            and score.status == "ok"
            and score.validity.status == "valid"
        ),
    )


def _benchmark_result_facts(
    receipt: EvaluationReceipt,
    family_id: str,
) -> tuple[BenchmarkResultFactRecord, ...]:
    rows: list[BenchmarkResultFactRecord] = []
    for score in sorted(receipt.scores, key=lambda item: item.leaf.leaf_id):
        score_row_count = len(rows)
        if score.primary is not None:
            rows.append(
                _result_fact(
                    receipt,
                    family_id=family_id,
                    score=score,
                    metric_role="primary",
                    metric_name=score.leaf.estimand.estimand_id,
                    metric=score.primary,
                    seat_id=None,
                )
            )
        for role, values in (
            ("metric", score.metrics),
            ("reference", score.reference_values),
            ("utility", score.utility_by_seat),
            ("capture", score.capture_by_seat),
        ):
            for name, metric in sorted(values.items()):
                rows.append(
                    _result_fact(
                        receipt,
                        family_id=family_id,
                        score=score,
                        metric_role=role,
                        metric_name=name,
                        metric=metric,
                        seat_id=name if role in {"utility", "capture"} else None,
                    )
                )
        if len(rows) == score_row_count:
            rows.append(
                _result_fact(
                    receipt,
                    family_id=family_id,
                    score=score,
                    metric_role="status",
                    metric_name="invalid_measurement",
                    metric=None,
                    seat_id=None,
                )
            )
    return tuple(rows)


def project_canonical_fact_tables(
    plan: RunPlan,
    receipts: Sequence[EvaluationReceipt],
) -> CanonicalFactTables:
    """Project reusable, long-form facts from verified plans and receipts.

    Profile feature rows are explicitly admission-derived. They must not be
    interpreted as observations from a live provider call.
    """

    receipt_values = tuple(receipts)
    build_research_ledger(plan, receipt_values)
    admissions = {item.profile_id: item for item in plan.profile_admissions}
    profiles = {item.profile_id: item for item in plan.agent_profiles}
    if set(admissions) != set(profiles):
        raise ResearchContractError(
            "canonical profile facts require exactly one admission per profile"
        )
    profile_rows = tuple(
        _profile_fact(plan, profiles[profile_id], admissions[profile_id])
        for profile_id in sorted(profiles)
    )
    feature_rows = tuple(
        row
        for profile_id in sorted(profiles)
        for row in _model_feature_facts(
            plan, profiles[profile_id], admissions[profile_id]
        )
    )
    family_by_cell = {cell.cell_id: cell.family_id for cell in plan.cells}
    result_rows = tuple(
        row
        for receipt in sorted(
            receipt_values, key=lambda item: (item.cell_id, item.episode_attempt_id)
        )
        for row in _benchmark_result_facts(
            receipt, family_by_cell[receipt.cell_id]
        )
    )
    return CanonicalFactTables(profile_rows, feature_rows, result_rows)


def _seat_from_event(event: Event, payload: Any) -> str | None:
    if event.visibility.startswith("seat:"):
        return event.visibility.split(":", 1)[1] or None
    if isinstance(payload, Mapping):
        request = payload.get("request")
        if isinstance(request, Mapping):
            seat_id = request.get("seat_id")
            if isinstance(seat_id, str) and seat_id:
                return seat_id
    return None


def _evidence_context(
    evidence: EvidenceStore,
) -> tuple[
    tuple[Event, ...],
    Mapping[str, Any],
    Mapping[str, str],
    set[str],
    Mapping[str, str],
    Mapping[str, str],
]:
    try:
        evidence.verify_chain()
        events = evidence.read_events()
        payloads = {
            event.event_id: evidence.read_event_payload(event) for event in events
        }
    except Exception as error:
        raise ResearchContractError("loss analysis requires valid evidence") from error

    phase_by_instance: dict[str, str] = {}
    recovery_attempt_ids: set[str] = set()
    seat_by_action: dict[str, str] = {}
    profile_by_action: dict[str, str] = {}
    for event in events:
        payload = payloads[event.event_id]
        if event.event_type == "phase_instance_started":
            phase = payload.get("phase") if isinstance(payload, Mapping) else None
            phase_id = phase.get("phase_id") if isinstance(phase, Mapping) else None
            if (
                event.phase_instance_id is None
                or not isinstance(phase_id, str)
                or not phase_id
            ):
                raise ResearchContractError(
                    "phase_instance_started must declare phase instance and phase IDs"
                )
            phase_by_instance[event.phase_instance_id] = phase_id
        elif (
            event.phase_instance_id is not None
            and isinstance(payload, Mapping)
            and isinstance(payload.get("phase_id"), str)
        ):
            phase_id = payload["phase_id"]
            previous = phase_by_instance.get(event.phase_instance_id)
            if previous is not None and previous != phase_id:
                raise ResearchContractError(
                    "domain phase identity changed within an evidence store"
                )
            phase_by_instance[event.phase_instance_id] = phase_id
        if event.event_type == "action_attempt_started" and isinstance(payload, Mapping):
            if payload.get("retry_reason") is not None:
                if event.action_attempt_id is None:
                    raise ResearchContractError("recovery attempt has no action_attempt_id")
                recovery_attempt_ids.add(event.action_attempt_id)
        if event.event_type == "logical_action_started" and event.logical_action_id:
            seat_id = _seat_from_event(event, payload)
            if seat_id is not None:
                seat_by_action[event.logical_action_id] = seat_id
            if isinstance(payload, Mapping):
                profile_id = payload.get("profile_id")
                if isinstance(profile_id, str) and profile_id:
                    profile_by_action[event.logical_action_id] = profile_id
    return (
        events,
        MappingProxyType(payloads),
        MappingProxyType(phase_by_instance),
        recovery_attempt_ids,
        MappingProxyType(seat_by_action),
        MappingProxyType(profile_by_action),
    )


def _domain_phase(event: Event, phase_by_instance: Mapping[str, str]) -> str | None:
    if event.phase_instance_id is None:
        return None
    phase_id = phase_by_instance.get(event.phase_instance_id)
    if phase_id is None:
        raise ResearchContractError(
            f"event {event.event_id!r} references an undeclared domain phase instance"
        )
    return phase_id


def _timestamp_seconds(started_at: str, finished_at: str) -> float | None:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        elapsed = (finish - start).total_seconds()
    except (TypeError, ValueError):
        return None
    return elapsed if elapsed >= 0 else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_nonnegative_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def _extract_model_calls(
    evidence: EvidenceStore,
    *,
    task_id: str,
) -> tuple[ModelCallRecord, ...]:
    (
        events,
        payloads,
        phase_by_instance,
        recovery_attempt_ids,
        seat_by_action,
        profile_by_action,
    ) = _evidence_context(evidence)
    started = [event for event in events if event.event_type == "provider_call_started"]
    terminals: dict[str, list[Event]] = {}
    for event in events:
        if event.provider_call_id and event.event_type in {
            "provider_call_succeeded",
            "provider_call_failed",
            "provider_call_outcome_unknown",
        }:
            terminals.setdefault(event.provider_call_id, []).append(event)

    records: list[ModelCallRecord] = []
    for call_index, event in enumerate(started):
        call_id = event.provider_call_id
        if call_id is None:
            raise ResearchContractError("provider_call_started has no provider_call_id")
        matches = terminals.get(call_id, [])
        if len(matches) != 1:
            raise ResearchContractError(
                f"provider call {call_id!r} must have exactly one terminal event"
            )
        terminal = matches[0]
        request_payload = payloads[event.event_id]
        terminal_payload = payloads[terminal.event_id]
        request = (
            request_payload.get("request")
            if isinstance(request_payload, Mapping)
            else None
        )
        request = request if isinstance(request, Mapping) else {}
        result = (
            terminal_payload.get("provider_result")
            if isinstance(terminal_payload, Mapping)
            else None
        )
        result = result if isinstance(result, Mapping) else {}
        status = terminal.event_type.removeprefix("provider_call_")
        if status == "succeeded":
            prompt_tokens = _optional_nonnegative_int(result.get("input_tokens"))
            cached_tokens = _optional_nonnegative_int(
                result.get("cached_input_tokens")
            )
            completion_tokens = _optional_nonnegative_int(result.get("output_tokens"))
            cost = _optional_nonnegative_float(
                terminal_payload.get("cost_usd")
                if isinstance(terminal_payload, Mapping)
                else None
            )
            exception_type = None
        elif status == "failed":
            prompt_tokens = cached_tokens = completion_tokens = 0
            cost = _optional_nonnegative_float(
                terminal_payload.get("cost_usd", 0.0)
                if isinstance(terminal_payload, Mapping)
                else 0.0
            )
            exception_type = (
                terminal_payload.get("failure_condition")
                if isinstance(terminal_payload, Mapping)
                else None
            )
        else:
            prompt_tokens = cached_tokens = completion_tokens = None
            cost = None
            exception_type = (
                terminal_payload.get("failure_condition")
                if isinstance(terminal_payload, Mapping)
                else None
            ) or "outcome_unknown"
        latency = _timestamp_seconds(event.occurred_at, terminal.occurred_at)
        telemetry_complete = (
            prompt_tokens is not None
            and cached_tokens is not None
            and completion_tokens is not None
            and cost is not None
            and latency is not None
        )
        logical_action_id = event.logical_action_id
        seat_id = _seat_from_event(event, request_payload)
        if seat_id is None and logical_action_id is not None:
            seat_id = seat_by_action.get(logical_action_id)
        profile_id = (
            None
            if logical_action_id is None
            else profile_by_action.get(logical_action_id)
        )
        records.append(
            ModelCallRecord(
                call_id=call_id,
                run_id=evidence.run_plan_id,
                task_id=task_id,
                call_index=call_index,
                seat_id=seat_id,
                profile_id=profile_id,
                harness_phase=(
                    "recovery"
                    if event.action_attempt_id in recovery_attempt_ids
                    else "execution"
                ),
                domain_phase_id=_domain_phase(event, phase_by_instance),
                provider=(request.get("provider") if isinstance(request.get("provider"), str) else None),
                requested_model=(
                    result.get("requested_model")
                    if isinstance(result.get("requested_model"), str)
                    else (
                        request.get("model")
                        if isinstance(request.get("model"), str)
                        else None
                    )
                ),
                resolved_model=(
                    result.get("resolved_model")
                    if isinstance(result.get("resolved_model"), str)
                    else None
                ),
                status=status,
                occurred_at=event.occurred_at,
                prompt_tokens=prompt_tokens,
                cached_tokens=cached_tokens,
                completion_tokens=completion_tokens,
                latency_seconds=latency,
                exception_type=(
                    exception_type if isinstance(exception_type, str) else None
                ),
                total_cost_usd=cost,
                telemetry_complete=telemetry_complete,
            )
        )
    unknown_terminals = sorted(set(terminals) - {event.provider_call_id for event in started})
    if unknown_terminals:
        raise ResearchContractError(
            f"terminal provider calls have no start event: {unknown_terminals}"
        )
    return tuple(records)


def _metric_passed(receipt: EvaluationReceipt | None) -> bool | None:
    if receipt is None or receipt.status != "ok":
        return None
    primary = next(
        (score for score in receipt.scores if score.leaf.leaf_id == receipt.primary_leaf_id),
        None,
    )
    if primary is None:
        return None
    passed = primary.metrics.get("passed")
    if passed is not None:
        return bool(passed.value)
    if primary.primary is not None and primary.primary.unit.lower() in {
        "binary",
        "bool",
        "pass",
    }:
        return bool(primary.primary.value)
    return None


def _task_status(
    receipt: EvaluationReceipt | None, evidence: EvidenceStore | None
) -> str:
    if receipt is None:
        return "unreceipted" if evidence is not None else "not_started"
    if receipt.status == "invalid_measurement":
        return "error"
    return "completed"


def _rollup_optional(records: Sequence[Any], field: str) -> int | float | None:
    values = [getattr(record, field) for record in records]
    if any(value is None for value in values):
        return None
    return sum(values)


def _difficulty_band(case: CaseManifest) -> str | None:
    for key in ("difficulty_band", "difficulty"):
        value = case.payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _collapse_labels(values: Sequence[str]) -> str:
    unique = sorted(set(values))
    if not unique:
        return "unknown"
    if len(unique) == 1:
        return unique[0]
    return "mixed[" + "|".join(unique) + "]"


def _evidence_by_cell(
    plan: RunPlan,
    evidence_stores: Mapping[str, EvidenceStore] | None,
) -> Mapping[str, EvidenceStore]:
    if evidence_stores is None:
        return MappingProxyType({})
    if not isinstance(evidence_stores, Mapping):
        raise ResearchContractError("evidence_stores must be a mapping")
    cells = {cell.cell_id for cell in plan.cells}
    resolved: dict[str, EvidenceStore] = {}
    for key, evidence in evidence_stores.items():
        if not isinstance(key, str) or not key:
            raise ResearchContractError("evidence store keys must be non-empty strings")
        if not isinstance(evidence, EvidenceStore):
            raise ResearchContractError("evidence_stores values must be EvidenceStore objects")
        if evidence.run_plan_id != plan.run_plan_id or evidence.cell_id not in cells:
            raise ResearchContractError("evidence store does not belong to this RunPlan")
        if evidence.cell_id in resolved:
            raise ResearchContractError(
                f"multiple evidence stores supplied for task {evidence.cell_id!r}"
            )
        resolved[evidence.cell_id] = evidence
    return MappingProxyType(resolved)


def _selected_receipts(
    plan: RunPlan,
    receipts: Sequence[EvaluationReceipt],
    evidence_by_cell: Mapping[str, EvidenceStore],
) -> Mapping[str, EvaluationReceipt]:
    by_cell: dict[str, list[EvaluationReceipt]] = {cell.cell_id: [] for cell in plan.cells}
    for receipt in receipts:
        by_cell[receipt.cell_id].append(receipt)
    selected: dict[str, EvaluationReceipt] = {}
    for cell_id, values in by_cell.items():
        if not values:
            continue
        evidence = evidence_by_cell.get(cell_id)
        if evidence is not None:
            matches = [
                receipt
                for receipt in values
                if receipt.episode_attempt_id == evidence.episode_attempt_id
            ]
            if len(matches) != 1:
                raise ResearchContractError(
                    f"evidence for task {cell_id!r} must match exactly one receipt attempt"
                )
            selected[cell_id] = matches[0]
            continue
        included = [receipt for receipt in values if receipt.inclusion_status == "included"]
        selected[cell_id] = (
            included[0]
            if included
            else sorted(values, key=lambda item: item.episode_attempt_id)[-1]
        )
    return MappingProxyType(selected)


def project_loss_analysis_tables(
    plan: RunPlan,
    receipts: Sequence[EvaluationReceipt],
    evidence_stores: Mapping[str, EvidenceStore] | None = None,
) -> LossAnalysisTables:
    """Project canonical runner records into Run -> Task -> Model Call tables."""

    receipt_values = tuple(receipts)
    build_research_ledger(plan, receipt_values)
    evidence_by_cell = _evidence_by_cell(plan, evidence_stores)
    selected_receipts = _selected_receipts(plan, receipt_values, evidence_by_cell)
    cases_by_id = {case.case_id: case for case in plan.cases}

    task_rows: list[TaskRecord] = []
    call_rows: list[ModelCallRecord] = []
    for cell in sorted(plan.cells, key=lambda item: item.cell_id):
        evidence = evidence_by_cell.get(cell.cell_id)
        receipt = selected_receipts.get(cell.cell_id)
        calls = () if evidence is None else _extract_model_calls(evidence, task_id=cell.cell_id)
        if evidence is not None:
            permitted_seats = set(cell.profile_by_seat)
            unknown_seats = sorted(
                {
                    call.seat_id
                    for call in calls
                    if call.seat_id is not None and call.seat_id not in permitted_seats
                }
            )
            if unknown_seats:
                raise ResearchContractError(
                    f"model calls reference seats absent from task {cell.cell_id!r}: {unknown_seats}"
                )
        if receipt is not None and evidence is not None:
            try:
                seal = evidence.verify_seal()
            except Exception as error:
                raise ResearchContractError(
                    "receipted loss-analysis evidence must be sealed"
                ) from error
            if seal != receipt.evidence:
                raise ResearchContractError("receipt evidence seal does not match EvidenceStore")
        telemetry_complete = (
            True
            if receipt is None and evidence is None
            else evidence is not None and all(call.telemetry_complete for call in calls)
        )
        prompt_tokens = _rollup_optional(calls, "prompt_tokens") if telemetry_complete else None
        cached_tokens = _rollup_optional(calls, "cached_tokens") if telemetry_complete else None
        completion_tokens = (
            _rollup_optional(calls, "completion_tokens") if telemetry_complete else None
        )
        total_tokens = (
            None
            if prompt_tokens is None or completion_tokens is None
            else int(prompt_tokens + completion_tokens)
        )
        cost = _rollup_optional(calls, "total_cost_usd") if telemetry_complete else None
        latency = _rollup_optional(calls, "latency_seconds") if telemetry_complete else None
        failure = None if receipt is None else receipt.failure
        case = cases_by_id[cell.case_id]
        task_rows.append(
            TaskRecord(
                run_id=plan.run_plan_id,
                task_id=cell.cell_id,
                case_id=cell.case_id,
                task_family=cell.family_id,
                difficulty_band=_difficulty_band(case),
                task_status=_task_status(receipt, evidence),
                passed=_metric_passed(receipt),
                exception_count=sum(call.exception_type is not None for call in calls),
                call_count=len(calls),
                prompt_tokens=None if prompt_tokens is None else int(prompt_tokens),
                cached_tokens=None if cached_tokens is None else int(cached_tokens),
                completion_tokens=(
                    None if completion_tokens is None else int(completion_tokens)
                ),
                total_tokens=total_tokens,
                cost_usd=None if cost is None else float(cost),
                latency_seconds=None if latency is None else float(latency),
                telemetry_complete=telemetry_complete,
                error=None if failure is None else failure.message,
                episode_attempt_id=(
                    evidence.episode_attempt_id
                    if evidence is not None
                    else (None if receipt is None else receipt.episode_attempt_id)
                ),
                receipt_sha256=None if receipt is None else receipt.receipt_sha256,
            )
        )
        call_rows.extend(calls)

    tasks = tuple(task_rows)
    calls = tuple(sorted(call_rows, key=lambda row: (row.task_id, row.call_index)))
    executed = sum(task.task_status != "not_started" for task in tasks)
    failed = sum(
        task.passed is False or task.task_status in {"error", "unreceipted"}
        for task in tasks
    )
    run_telemetry_complete = all(
        task.telemetry_complete for task in tasks if task.task_status != "not_started"
    )
    run_prompt = _rollup_optional(tasks, "prompt_tokens") if run_telemetry_complete else None
    run_cached = _rollup_optional(tasks, "cached_tokens") if run_telemetry_complete else None
    run_completion = (
        _rollup_optional(tasks, "completion_tokens") if run_telemetry_complete else None
    )
    run_total = (
        None
        if run_prompt is None or run_completion is None
        else int(run_prompt + run_completion)
    )
    run_cost = _rollup_optional(tasks, "cost_usd") if run_telemetry_complete else None
    run_latency = (
        _rollup_optional(tasks, "latency_seconds") if run_telemetry_complete else None
    )
    used_profile_ids = {
        profile_id
        for cell in plan.cells
        for profile_id in cell.profile_by_seat.values()
    }
    used_profiles = [
        profile
        for profile in plan.agent_profiles
        if profile.profile_id in used_profile_ids
    ]
    profile_models = [profile.model.model for profile in used_profiles]
    profile_harnesses = [
        f"{profile.harness.id}@{profile.harness.version}"
        for profile in used_profiles
    ]
    profile_runtimes = [
        f"{profile.runtime.implementation}@{profile.runtime.version}"
        for profile in used_profiles
    ]
    run = RunRecord(
        run_id=plan.run_plan_id,
        benchmark_id=plan.suite.suite_id,
        benchmark_version=plan.suite.version,
        model_name=_collapse_labels(profile_models),
        harness_name=_collapse_labels(profile_harnesses),
        runner_version=_collapse_labels(profile_runtimes),
        tasks_expected=len(tasks),
        tasks_executed=executed,
        tasks_passed=sum(task.passed is True for task in tasks),
        tasks_failed=failed,
        tasks_not_started=len(tasks) - executed,
        call_count=len(calls),
        exception_count=sum(task.exception_count for task in tasks),
        prompt_tokens=None if run_prompt is None else int(run_prompt),
        cached_tokens=None if run_cached is None else int(run_cached),
        completion_tokens=None if run_completion is None else int(run_completion),
        total_tokens=run_total,
        total_cost_usd=None if run_cost is None else float(run_cost),
        latency_seconds=None if run_latency is None else float(run_latency),
        telemetry_complete=run_telemetry_complete,
    )
    return LossAnalysisTables((run,), tasks, calls)


def build_trajectory_record(
    evidence: EvidenceStore,
    receipt: EvaluationReceipt | None = None,
) -> TrajectoryRecord:
    """Extract a lossless, event-ordered diagnostic trajectory."""

    if not isinstance(evidence, EvidenceStore):
        raise ResearchContractError("evidence must be an EvidenceStore")
    if receipt is not None:
        try:
            verify_evaluation_receipt(receipt)
            seal = evidence.verify_seal()
        except Exception as error:
            raise ResearchContractError(
                "trajectory receipt and evidence must be verified"
            ) from error
        if (
            receipt.run_plan_id != evidence.run_plan_id
            or receipt.cell_id != evidence.cell_id
            or receipt.episode_id != evidence.episode_id
            or receipt.episode_attempt_id != evidence.episode_attempt_id
            or receipt.evidence != seal
        ):
            raise ResearchContractError("trajectory receipt does not match evidence")
    (
        events,
        payloads,
        phase_by_instance,
        recovery_attempt_ids,
        seat_by_action,
        _profile_by_action,
    ) = _evidence_context(evidence)
    steps: list[TrajectoryStep] = []
    for event in events:
        payload = payloads[event.event_id]
        request = payload.get("request") if isinstance(payload, Mapping) else None
        request = request if isinstance(request, Mapping) else None
        result = (
            payload.get("provider_result") if isinstance(payload, Mapping) else None
        )
        result = result if isinstance(result, Mapping) else None
        tool_name = None
        messages = None
        step_input = None
        step_output = None
        prompt_tokens = cached_tokens = completion_tokens = None
        error = None
        if request is not None:
            messages = request.get("messages")
            step_input = {
                "instructions": request.get("instructions"),
                "input_text": request.get("input_text"),
            }
        elif event.event_type == "logical_action_started" and isinstance(payload, Mapping):
            step_input = payload.get("request")
        if result is not None:
            step_output = result.get("output_text")
            prompt_tokens = _optional_nonnegative_int(result.get("input_tokens"))
            cached_tokens = _optional_nonnegative_int(result.get("cached_input_tokens"))
            completion_tokens = _optional_nonnegative_int(result.get("output_tokens"))
        if event.event_type == "tool_invocation_started" and isinstance(payload, Mapping):
            tool_name = payload.get("tool_id") if isinstance(payload.get("tool_id"), str) else None
            step_input = payload.get("arguments")
        elif event.event_type == "tool_invocation_succeeded" and isinstance(payload, Mapping):
            step_output = payload.get("result")
        if isinstance(payload, Mapping) and isinstance(
            payload.get("failure_condition"), str
        ):
            message = payload.get("message")
            error = payload["failure_condition"]
            if isinstance(message, str) and message:
                error = f"{error}: {message}"
        try:
            harness_phase = _harness_phase(event, recovery_attempt_ids)
        except ResearchContractError:
            # Full trajectories preserve every canonical event. New event types
            # stay visible with an unset operational phase until reviewed.
            harness_phase = None
        seat_id = _seat_from_event(event, payload)
        if seat_id is None and event.logical_action_id is not None:
            seat_id = seat_by_action.get(event.logical_action_id)
        steps.append(
            TrajectoryStep(
                step_index=event.sequence,
                event_id=event.event_id,
                occurred_at=event.occurred_at,
                event_type=event.event_type,
                harness_phase=harness_phase,
                domain_phase_id=_domain_phase(event, phase_by_instance),
                domain_phase_instance_id=event.phase_instance_id,
                seat_id=seat_id,
                logical_action_id=event.logical_action_id,
                action_attempt_id=event.action_attempt_id,
                provider_call_id=event.provider_call_id,
                tool_invocation_id=event.tool_invocation_id,
                tool_name=tool_name,
                messages=messages,
                input=step_input,
                output=step_output,
                prompt_tokens=prompt_tokens,
                cached_tokens=cached_tokens,
                completion_tokens=completion_tokens,
                error=error,
                payload=payload,
            )
        )
    seal = None
    try:
        seal = evidence.verify_seal()
    except Exception:
        if receipt is not None:  # pragma: no cover - handled above
            raise
    return TrajectoryRecord(
        run_id=evidence.run_plan_id,
        task_id=evidence.cell_id,
        episode_id=evidence.episode_id,
        episode_attempt_id=evidence.episode_attempt_id,
        task_status=_task_status(receipt, evidence),
        passed=_metric_passed(receipt),
        receipt_sha256=None if receipt is None else receipt.receipt_sha256,
        event_root_sha256=None if seal is None else seal.event_root_sha256,
        steps=tuple(steps),
    )


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return value
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _csv_bytes(record_type: type, records: Sequence[Any]) -> bytes:
    field_names = [field.name for field in dataclasses.fields(record_type)]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(
            {name: _csv_value(getattr(record, name)) for name in field_names}
        )
    return stream.getvalue().encode("utf-8")


def _publish_export(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ResearchContractError("export destination must not be a symlink")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_file() and path.read_bytes() == payload:
            return path
        raise ResearchContractError(f"refusing to overwrite different export: {path}")
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while publishing loss-analysis export")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def export_canonical_fact_tables(
    plan: RunPlan,
    receipts: Sequence[EvaluationReceipt],
    output_dir: Path | str,
) -> dict[str, Path]:
    """Write deterministic profile, feature, and result fact tables.

    The manifest digest covers its core metadata and every table digest. It is
    intentionally not a new source of truth: each row points back to the sealed
    RunPlan or EvaluationReceipt from which it was projected.
    """

    tables = project_canonical_fact_tables(plan, receipts)
    destination = Path(output_dir)
    if destination.is_symlink():
        raise ResearchContractError("output_dir must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    payloads = {
        "profiles": _csv_bytes(ProfileFactRecord, tables.profiles),
        "model_features": _csv_bytes(
            ModelFeatureFactRecord, tables.model_features
        ),
        "benchmark_results": _csv_bytes(
            BenchmarkResultFactRecord, tables.benchmark_results
        ),
    }
    filenames = {
        "profiles": "profiles.csv",
        "model_features": "model_features.csv",
        "benchmark_results": "benchmark_results.csv",
    }
    paths = {
        name: _publish_export(destination / filenames[name], payload)
        for name, payload in payloads.items()
    }
    manifest_core = {
        "schema_version": "aeread.canonical_fact_tables/0.1",
        "run_id": plan.run_plan_id,
        "run_plan_sha256": plan.plan_sha256,
        "source_truth": ["RunPlan", "EvaluationReceipt"],
        "projection_semantics": (
            "deterministic reportable view; sealed source records remain authoritative"
        ),
        "tables": {
            name: {
                "path": filenames[name],
                "row_count": len(getattr(tables, name)),
                "sha256": hashlib.sha256(payloads[name]).hexdigest(),
            }
            for name in filenames
        },
    }
    manifest = {
        **manifest_core,
        "manifest_sha256": hashlib.sha256(
            canonical_json_bytes(manifest_core)
        ).hexdigest(),
    }
    paths["fact_manifest"] = _publish_export(
        destination / "fact_manifest.json",
        canonical_json_bytes(manifest) + b"\n",
    )
    return paths


_DATA_DICTIONARY = """# AERead loss-analysis data dictionary

This dataset is a derived view. `RunPlan`, `EvaluationReceipt`, and sealed
`EvidenceStore` records remain canonical benchmark truth.

## Relationships

- `runs.run_id` -> `tasks.run_id`
- (`tasks.run_id`, `tasks.task_id`) -> (`model_calls.run_id`, `model_calls.task_id`)
- (`runs.run_id`, `tasks.task_id`) -> `trajectories/trajectory_index.csv`
- `profiles.profile_id` -> `model_features.profile_id`
- (`benchmark_results.run_id`, `benchmark_results.task_id`) -> (`tasks.run_id`, `tasks.task_id`)

## Canonical fact-table projections

`fact_manifest.json` binds the three reusable fact tables to their sealed
`RunPlan` and to the SHA-256 digest of every CSV. The manifest's own digest is
computed over the manifest without the `manifest_sha256` field. These tables
are canonical *projections* for analysis and reporting; they do not supersede
the source plan or receipts.

### `profiles.csv`

One row per sealed `AgentProfile`, including model route, harness and prompt
pins, runtime, tools, memory, reasoning and sampling settings, budgets, retry
policy, profile digest, and admission identity. This is the configuration table
that must be joined into any model or harness comparison.

### `model_features.csv`

One long-form row per `ProfileAdmission.capability_vector` entry. Every row is
labeled `evidence_class=admission_derived`: it describes the sealed admission
decision produced from declared harness requirements, provider capabilities,
and profile configuration. It is not evidence that a live provider call
exhibited the feature. Live behavior remains in `model_calls.csv` and receipts.

### `benchmark_results.csv`

One row per typed receipt metric, reference, utility, or capture value, plus an
explicit status row for a measurement leaf with no numeric outputs. All verified
attempts remain present. `reportable=true` only when the receipt was included
and the score and validity statuses both passed; analysis must still obey the
sealed `AnalysisPlan` rather than treating metric rows as independent samples.

## `runs.csv`

One row per sealed RunPlan. Coverage fields retain planned-but-unstarted tasks.
Token, cost, and latency totals are null when any executed task lacks telemetry.

| Column | Type | Meaning |
|---|---|---|
| `run_id` | string | Canonical `RunPlan.run_plan_id`; joins every table. |
| `benchmark_id`, `benchmark_version` | string | Sealed suite identity. |
| `model_name` | string | Model label, or a deterministic `mixed[...]` label for multi-model plans. |
| `harness_name`, `runner_version` | string | Harness and runtime identities used by planned cells. |
| `tasks_expected` | integer | Number of planned cells. |
| `tasks_executed` | integer | Tasks with a receipt or supplied evidence. |
| `tasks_passed`, `tasks_failed` | integer | Explicit binary passes and failures; continuous outcomes can be neither. |
| `tasks_not_started` | integer | Planned tasks with neither receipt nor evidence. |
| `call_count`, `exception_count` | integer | Rolled-up provider calls and calls with typed exceptions. |
| `prompt_tokens`, `cached_tokens`, `completion_tokens` | nullable integer | Usage summed from model calls. Cached tokens are included in prompt tokens. |
| `total_tokens` | nullable integer | `prompt_tokens + completion_tokens`. |
| `total_cost_usd`, `latency_seconds` | nullable number | Sum across tasks. |
| `telemetry_complete` | boolean | Whether every executed task has complete call telemetry. |

## `tasks.csv`

One row per planned PlanCell. `task_status` is `not_started`, `unreceipted`,
`completed`, or `error`. `passed` is nullable because continuous economic
measurements do not necessarily define a pass/fail threshold. Token totals count
prompt and completion tokens; cached tokens are a subset of prompt tokens.

| Column | Type | Meaning |
|---|---|---|
| `run_id`, `task_id` | string | Composite task key; `task_id` is the canonical cell ID. |
| `case_id`, `task_family` | string | Canonical case and family identities. |
| `difficulty_band` | nullable string | Case-declared `difficulty_band` or `difficulty`, when present. |
| `task_status` | enum | `not_started`, `unreceipted`, `completed`, or `error`. |
| `passed` | nullable boolean | Verifier result when the primary measurement declares a binary pass metric. |
| `exception_count`, `call_count` | integer | Provider-call counts for this task. |
| `prompt_tokens`, `cached_tokens`, `completion_tokens` | nullable integer | Usage summed from this task's model calls. |
| `total_tokens` | nullable integer | `prompt_tokens + completion_tokens`. |
| `cost_usd`, `latency_seconds` | nullable number | Sum across this task's calls. |
| `telemetry_complete` | boolean | Whether every call has tokens, cost, and measurable latency. |
| `error` | nullable string | Typed receipt failure message. |
| `episode_attempt_id` | nullable string | Evidence or receipt attempt identity. |
| `receipt_sha256` | nullable string | Verified receipt digest. |

## `model_calls.csv`

One row per canonical `provider_call_started` event paired with its terminal
event. `harness_phase` is operational (`execution` or `recovery`) and remains
separate from the family-owned `domain_phase_id`. Outcome-unknown calls retain
null token and cost telemetry instead of being reported as zero.

| Column | Type | Meaning |
|---|---|---|
| `call_id` | string | Canonical provider-call ID. |
| `run_id`, `task_id` | string | Parent run and task keys. |
| `call_index` | integer | Zero-based call order within the task. |
| `seat_id`, `profile_id` | nullable string | Attributed seat and agent profile. |
| `harness_phase` | enum | `execution` or `recovery` for model calls. |
| `domain_phase_id` | nullable string | Family-owned phase identity. |
| `provider`, `requested_model`, `resolved_model` | nullable string | Recorded provider and model routing. |
| `status` | enum | `succeeded`, `failed`, or `outcome_unknown`. |
| `occurred_at` | timestamp string | Start-event timestamp. |
| `prompt_tokens`, `cached_tokens`, `completion_tokens` | nullable integer | Call-level usage. |
| `latency_seconds` | nullable number | Terminal timestamp minus start timestamp. |
| `exception_type` | nullable string | Recorded failure condition. |
| `total_cost_usd` | nullable number | Recorded call cost; never repriced by this export. |
| `telemetry_complete` | boolean | Whether usage, cost, and latency are all known. |

## Trajectories

`trajectories/selected/*.json` contains one event-ordered record per supplied
EvidenceStore. `trajectory_index.csv` is the query index. `archive.jsonl` stores
the same records as a deterministic append-friendly stream. Each step retains
the full verified event payload plus extracted messages, inputs, outputs, tool
identity, token usage, and errors where present.

The index contains run/task/episode identities, task status, nullable pass result,
step and call counts, receipt and event-root digests, and the relative trajectory
path. Each JSON trajectory adds an ordered `steps` array whose entries retain event
identity and time, both phase axes, seat/action/call/tool IDs, extracted diagnostic
fields, and the complete canonical payload.
"""


def export_loss_analysis_dataset(
    plan: RunPlan,
    receipts: Sequence[EvaluationReceipt],
    evidence_stores: Mapping[str, EvidenceStore],
    output_dir: Path | str,
) -> dict[str, Path]:
    """Write relational/fact CSVs, selected trajectories, and schema docs."""

    tables = project_loss_analysis_tables(plan, receipts, evidence_stores)
    evidence_by_cell = _evidence_by_cell(plan, evidence_stores)
    selected_receipts = _selected_receipts(plan, tuple(receipts), evidence_by_cell)
    destination = Path(output_dir)
    if destination.is_symlink():
        raise ResearchContractError("output_dir must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    selected_dir = destination / "trajectories" / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "runs": _publish_export(
            destination / "runs.csv", _csv_bytes(RunRecord, tables.runs)
        ),
        "tasks": _publish_export(
            destination / "tasks.csv", _csv_bytes(TaskRecord, tables.tasks)
        ),
        "model_calls": _publish_export(
            destination / "model_calls.csv",
            _csv_bytes(ModelCallRecord, tables.model_calls),
        ),
    }
    paths.update(export_canonical_fact_tables(plan, receipts, destination))
    trajectories: list[TrajectoryRecord] = []
    index_rows: list[Mapping[str, Any]] = []
    for task_id, evidence in sorted(evidence_by_cell.items()):
        trajectory = build_trajectory_record(
            evidence, selected_receipts.get(task_id)
        )
        trajectories.append(trajectory)
        relative = Path("selected") / f"{plan.run_plan_id}__{task_id}.json"
        _publish_export(
            destination / "trajectories" / relative,
            canonical_json_bytes(trajectory) + b"\n",
        )
        index_rows.append(
            {
                "run_id": trajectory.run_id,
                "task_id": trajectory.task_id,
                "episode_id": trajectory.episode_id,
                "episode_attempt_id": trajectory.episode_attempt_id,
                "task_status": trajectory.task_status,
                "passed": trajectory.passed,
                "step_count": len(trajectory.steps),
                "call_count": sum(
                    step.event_type == "provider_call_started"
                    for step in trajectory.steps
                ),
                "receipt_sha256": trajectory.receipt_sha256,
                "event_root_sha256": trajectory.event_root_sha256,
                "trajectory_path": relative.as_posix(),
            }
        )
    index_field_names = (
        "run_id",
        "task_id",
        "episode_id",
        "episode_attempt_id",
        "task_status",
        "passed",
        "step_count",
        "call_count",
        "receipt_sha256",
        "event_root_sha256",
        "trajectory_path",
    )
    index_stream = io.StringIO(newline="")
    index_writer = csv.DictWriter(
        index_stream, fieldnames=index_field_names, lineterminator="\n"
    )
    index_writer.writeheader()
    for row in index_rows:
        index_writer.writerow({key: _csv_value(row[key]) for key in index_field_names})
    archive = b"".join(canonical_json_bytes(row) + b"\n" for row in trajectories)
    paths.update(
        {
            "trajectory_index": _publish_export(
                destination / "trajectories" / "trajectory_index.csv",
                index_stream.getvalue().encode("utf-8"),
            ),
            "trajectory_archive": _publish_export(
                destination / "trajectories" / "archive.jsonl", archive
            ),
            "data_dictionary": _publish_export(
                destination / "data_dictionary.md", _DATA_DICTIONARY.encode("utf-8")
            ),
            "selected_trajectories": selected_dir,
        }
    )
    return paths


# ---------------------------------------------------------------------------
# Durable artifact loading for the CLI. Constructors are intentionally private:
# callers with in-memory typed records should use the projection API directly.
# ---------------------------------------------------------------------------


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearchContractError(f"{label} must be an object")
    return value


def _deserialize_run_plan(value: Mapping[str, Any]) -> RunPlan:
    try:
        families = tuple(parse_authoring_record(item) for item in value["families"])
        cases = tuple(parse_authoring_record(item) for item in value["cases"])
        suite = parse_authoring_record(value["suite"])
        sampling = parse_authoring_record(value["sampling"])
        blocks = tuple(
            parse_authoring_record(item) for item in value["evaluation_blocks"]
        )
        analysis = parse_authoring_record(value["analysis"])
        profiles = tuple(
            parse_authoring_record(item) for item in value["agent_profiles"]
        )
        run_spec = parse_authoring_record(value["run_spec"])
        pins = tuple(
            ImplementationPin.from_dict(item) for item in value["implementation_pins"]
        )
        cells = tuple(
            PlanCell(
                **{
                    **dict(item),
                    "paired_fields": MappingProxyType(dict(item["paired_fields"])),
                    "profile_by_seat": MappingProxyType(
                        dict(item["profile_by_seat"])
                    ),
                }
            )
            for item in value["cells"]
        )
        admissions = tuple(
            ProfileAdmission(
                **{
                    **dict(item),
                    "capability_vector": MappingProxyType(
                        dict(item["capability_vector"])
                    ),
                    "reasons": tuple(item["reasons"]),
                }
            )
            for item in value["profile_admissions"]
        )
        if not all(isinstance(item, FamilyManifest) for item in families):
            raise TypeError("families contain a non-FamilyManifest")
        if not all(isinstance(item, CaseManifest) for item in cases):
            raise TypeError("cases contain a non-CaseManifest")
        if not isinstance(suite, SuiteManifest):
            raise TypeError("suite is not a SuiteManifest")
        if not isinstance(sampling, SamplingPlan):
            raise TypeError("sampling is not a SamplingPlan")
        if not all(isinstance(item, EvaluationBlock) for item in blocks):
            raise TypeError("evaluation_blocks contain a non-EvaluationBlock")
        if not isinstance(analysis, AnalysisPlan):
            raise TypeError("analysis is not an AnalysisPlan")
        if not all(isinstance(item, AgentProfile) for item in profiles):
            raise TypeError("agent_profiles contain a non-AgentProfile")
        if not isinstance(run_spec, RunSpec):
            raise TypeError("run_spec is not a RunSpec")
        plan = RunPlan(
            spec_version=value["spec_version"],
            run_plan_id=value["run_plan_id"],
            plan_sha256=value["plan_sha256"],
            families=families,
            cases=cases,
            suite=suite,
            sampling=sampling,
            evaluation_blocks=blocks,
            analysis=analysis,
            agent_profiles=profiles,
            run_spec=run_spec,
            implementation_pins=pins,
            input_digests=MappingProxyType(dict(value["input_digests"])),
            cells=cells,
            profile_admissions=admissions,
        )
        verify_run_plan(plan)
        return plan
    except Exception as error:
        raise ResearchContractError("serialized RunPlan is invalid") from error


def _implementation_ref(value: Any) -> ImplementationRef:
    data = _mapping(value, "implementation_ref")
    return ImplementationRef(
        data["implementation_id"], data["version"], data["content_sha256"]
    )


def _validity_domain(value: Any) -> ValidityDomainSpec:
    data = _mapping(value, "validity_domain")
    return ValidityDomainSpec(
        data["domain_id"],
        data["domain_version"],
        data["schema_ref"],
        _implementation_ref(data["predicate"]),
    )


def _estimand(value: Any) -> EstimandSpec:
    data = _mapping(value, "estimand")
    return EstimandSpec(
        data["estimand_id"],
        data["estimand_version"],
        data["input_scope"],
        data["direction"],
        data["units"],
        _validity_domain(data["validity_domain"]),
    )


def _reference(value: Any) -> ReferenceSpec:
    data = _mapping(value, "reference")
    return ReferenceSpec(
        data["reference_id"],
        data["reference_version"],
        data["reference_kind"],
        data["input_scope"],
        data["units"],
        data["source_sha256"],
        _implementation_ref(data["implementation"]),
    )


def _objective_scope(value: Any) -> ObjectiveScopeSpec | None:
    if value is None:
        return None
    data = _mapping(value, "objective_scope")
    return ObjectiveScopeSpec(
        data["objective_id"],
        data["objective_version"],
        data["direction"],
        data["units"],
        data["feasible_set"],
        data["information_set"],
        data["horizon"],
        data["environment_condition"],
        data["opponent_condition"],
        _validity_domain(data["validity_domain"]),
    )


def _verifier(value: Any) -> VerifierSpec:
    data = _mapping(value, "verifier")
    return VerifierSpec(
        data["verifier_family"],
        data["evaluation_class"],
        _reference(data["reference"]),
        _objective_scope(data.get("objective_scope")),
    )


def _leaf(value: Any) -> MeasurementLeafSpec:
    data = _mapping(value, "measurement_leaf")
    return MeasurementLeafSpec(
        data["leaf_id"],
        data["leaf_version"],
        _estimand(data["estimand"]),
        _verifier(data["verifier"]),
        _implementation_ref(data["scorer"]),
    )


def _metric(value: Any) -> MetricValue:
    data = _mapping(value, "metric")
    return MetricValue(data["value"], data["unit"], data.get("metadata", {}))


def _metric_mapping(value: Any, label: str) -> Mapping[str, MetricValue]:
    data = _mapping(value, label)
    return {key: _metric(item) for key, item in data.items()}


def _score(value: Any) -> ScoreEnvelope:
    data = _mapping(value, "score")
    return ScoreEnvelope(
        status=data["status"],
        leaf=_leaf(data["leaf"]),
        primary=None if data.get("primary") is None else _metric(data["primary"]),
        metrics=_metric_mapping(data["metrics"], "score.metrics"),
        reference_values=_metric_mapping(
            data["reference_values"], "score.reference_values"
        ),
        validity=ValidityReport(
            data["validity"]["status"], tuple(data["validity"].get("reasons", ()))
        ),
        evidence_refs=tuple(data["evidence_refs"]),
        utility_by_seat=_metric_mapping(
            data.get("utility_by_seat", {}), "score.utility_by_seat"
        ),
        capture_by_seat=_metric_mapping(
            data.get("capture_by_seat", {}), "score.capture_by_seat"
        ),
    )


def _deserialize_receipt(value: Mapping[str, Any]) -> EvaluationReceipt:
    try:
        failure_data = value.get("failure")
        failure = (
            None
            if failure_data is None
            else EvaluationFailure(
                failure_data["failure_class"],
                failure_data["condition"],
                failure_data["message"],
            )
        )
        receipt = EvaluationReceipt(
            spec_version=value["spec_version"],
            receipt_sha256=value["receipt_sha256"],
            status=value["status"],
            inclusion_status=value["inclusion_status"],
            run_plan_id=value["run_plan_id"],
            run_plan_sha256=value["run_plan_sha256"],
            cell_id=value["cell_id"],
            case_id=value["case_id"],
            case_sha256=value["case_sha256"],
            suite_id=value["suite_id"],
            suite_version=value["suite_version"],
            block_id=value["block_id"],
            sampling_plan_id=value["sampling_plan_id"],
            analysis_plan_id=value["analysis_plan_id"],
            episode_id=value["episode_id"],
            episode_attempt_id=value["episode_attempt_id"],
            cluster_id=value["cluster_id"],
            cluster_level=value["cluster_level"],
            observations_per_cluster=value["observations_per_cluster"],
            parent_cluster_id=value.get("parent_cluster_id"),
            pair_id=value.get("pair_id"),
            paired_fields=value["paired_fields"],
            replicate_index=value["replicate_index"],
            panel_mode=value["panel_mode"],
            agent_profile_sha256_by_seat=value["agent_profile_sha256_by_seat"],
            implementation_refs=tuple(
                _implementation_ref(item) for item in value["implementation_refs"]
            ),
            plan_implementation_pins=tuple(
                ImplementationPin.from_dict(item)
                for item in value["plan_implementation_pins"]
            ),
            evidence=EvidenceSeal(**value["evidence"]),
            primary_leaf_id=value["primary_leaf_id"],
            scores=tuple(_score(item) for item in value["scores"]),
            failure=failure,
            observability_limits=tuple(value.get("observability_limits", ())),
            replay_level=value.get("replay_level", "none"),
        )
        verify_evaluation_receipt(receipt)
        return receipt
    except Exception as error:
        raise ResearchContractError("serialized EvaluationReceipt is invalid") from error


def _load_run_plan(path: Path) -> RunPlan:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ResearchContractError(f"cannot read RunPlan: {path}") from error
    if not isinstance(value, Mapping) or raw != canonical_json_bytes(value):
        raise ResearchContractError("RunPlan JSON is not canonical")
    return _deserialize_run_plan(value)


def _load_receipts(path: Path | None) -> tuple[EvaluationReceipt, ...]:
    if path is None:
        return ()
    candidates = (path,) if path.is_file() else tuple(sorted(path.rglob("*.json")))
    receipts: list[EvaluationReceipt] = []
    for candidate in candidates:
        try:
            value = json.loads(candidate.read_bytes())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, Mapping) or value.get("spec_version") != EvaluationReceipt.SPEC_VERSION:
            continue
        receipts.append(_deserialize_receipt(read_evaluation_receipt(candidate)))
    if not receipts:
        raise ResearchContractError(f"no canonical evaluation receipts found under {path}")
    return tuple(
        sorted(receipts, key=lambda item: (item.cell_id, item.episode_attempt_id))
    )


def _load_evidence_stores(path: Path | None) -> dict[str, EvidenceStore]:
    if path is None:
        return {}
    event_logs = (
        (path / "events.jsonl",)
        if (path / "events.jsonl").is_file()
        else tuple(sorted(path.rglob("events.jsonl")))
    )
    stores: dict[str, EvidenceStore] = {}
    for event_log in event_logs:
        evidence = EvidenceStore.audit_existing(event_log.parent)
        if evidence.episode_attempt_id in stores:
            evidence.close()
            raise ResearchContractError("duplicate evidence attempt discovered")
        stores[evidence.episode_attempt_id] = evidence
    if not stores:
        raise ResearchContractError(f"no EvidenceStore event logs found under {path}")
    return stores


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export canonical shared-runner records as loss-analysis tables"
    )
    parser.add_argument("--plan", type=Path, required=True, help="canonical run_plan.json")
    parser.add_argument(
        "--receipts",
        type=Path,
        help="receipt JSON file or directory recursively containing receipts",
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="EvidenceStore directory or parent tree containing events.jsonl files",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    evidence: dict[str, EvidenceStore] = {}
    try:
        plan = _load_run_plan(arguments.plan)
        receipts = _load_receipts(arguments.receipts)
        evidence = _load_evidence_stores(arguments.evidence_root)
        paths = export_loss_analysis_dataset(
            plan, receipts, evidence, arguments.output_dir
        )
        print(
            json.dumps(
                {key: str(path) for key, path in paths.items()},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    finally:
        for store in evidence.values():
            store.close()


__all__ = [
    "AttemptResearchRow",
    "BenchmarkResultFactRecord",
    "CampaignResearchRow",
    "CanonicalFactTables",
    "CellResearchRow",
    "DesignAudit",
    "DesignIssue",
    "DesignObservation",
    "EventResearchRow",
    "LossAnalysisTables",
    "ModelFeatureFactRecord",
    "ModelCallRecord",
    "ProfileFactRecord",
    "ResearchContractError",
    "ResearchLedger",
    "RunRecord",
    "TaskRecord",
    "TrajectoryRecord",
    "TrajectoryStep",
    "audit_experimental_design",
    "build_trajectory_record",
    "build_research_ledger",
    "export_loss_analysis_dataset",
    "export_canonical_fact_tables",
    "main",
    "project_evidence_events",
    "project_loss_analysis_tables",
    "project_canonical_fact_tables",
    "research_tables",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
