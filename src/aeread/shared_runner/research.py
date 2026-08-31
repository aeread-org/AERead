"""Receipt-derived research views and experimental-design preflight.

The canonical shared-runner records remain ``RunPlan``, ``Event`` and
``EvaluationReceipt``. This module projects those records into query-friendly
campaign, cell, attempt and event rows without making the projections a second
source of benchmark truth.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .execution import EvidenceStore, Event
from .receipts import EvaluationReceipt, verify_evaluation_receipt
from .resolver import RunPlan, canonical_json_bytes, verify_run_plan
from .schemas import AgentProfile, is_exportable_id


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


__all__ = [
    "AttemptResearchRow",
    "CampaignResearchRow",
    "CellResearchRow",
    "DesignAudit",
    "DesignIssue",
    "DesignObservation",
    "EventResearchRow",
    "ResearchContractError",
    "ResearchLedger",
    "audit_experimental_design",
    "build_research_ledger",
    "project_evidence_events",
    "research_tables",
]
