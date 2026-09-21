"""Housing V1 family bridge and one-cell admission fixture.

The economic state machine remains owned by
the aeread_families.housing.environment module. This
module translates its contact/respond/commit contract into the generic shared
runner hooks, keeps tenant and landlord observations private, and supplies a
deterministic controlled-landlord provider.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread_families.housing import environment as hz
from aeread_families.housing import lemons as lemons_module
from aeread.shared_runner.model_call import harness as harness_module
from aeread.shared_runner.task import evaluation as evaluation_module
from aeread.shared_runner.task import execution as execution_module

from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    CellExecution,
    EvidenceStore,
    OpenRouterChatClient,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.model_call.harness import MinimalChatHarness
from aeread.shared_runner.registry import (
    HarnessRegistry,
    PluginRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.task.evaluation import (
    FamilyScoringInput,
    finalize_family_execution,
    finalize_family_failure,
    replay_family_receipt,
)
from aeread.shared_runner.measurement import (
    EstimandSpec,
    ImplementationRef as MeasurementImplementationRef,
    MeasurementLeafSpec,
    MetricValue,
    ObjectiveScopeSpec,
    ReferenceSpec,
    ScoreEnvelope,
    ValidityDomainSpec,
    ValidityReport,
    VerifierSpec,
)
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
    verify_run_plan,
)
from aeread.shared_runner.task.receipts import (
    EvaluationFailure,
    EvaluationReceipt,
    seal_evaluation_receipt,
    verify_evaluation_receipt,
    write_evaluation_receipt,
)
from aeread.shared_runner.task.scheduler import (
    ActionEnvelope,
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
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


HOUSING_CONTACT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["offer", "pass"]},
        "listing_id": {"type": ["integer", "null"]},
        "rent": {"type": ["number", "null"]},
    },
    "required": ["decision", "listing_id", "rent"],
    "additionalProperties": False,
}

HOUSING_RESPOND_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["accept", "counter", "reject_all"]},
        "offer_id": {"type": ["string", "null"]},
        "counter_rent": {"type": ["number", "null"]},
    },
    "required": ["decision", "offer_id", "counter_rent"],
    "additionalProperties": False,
}

HOUSING_COMMIT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["sign", "walk", "pass"]},
        "hold_id": {"type": ["string", "null"]},
    },
    "required": ["decision", "hold_id"],
    "additionalProperties": False,
}

# These values are serialized component identities in already-admitted Housing
# profiles, not import paths. They stay stable so a source-tree reorganization
# does not masquerade as a new experimental condition.
HOUSING_RUNTIME_COMPONENT_ID = "aeread.shared_runner.housing"
TASK_EXECUTION_COMPONENT_ID = "aeread.shared_runner.execution"

# Version 2 makes the cross-field action invariants provider-visible.  Version
# 1 remains available so already-sealed campaigns can still be reconstructed.
HOUSING_CONTACT_OUTPUT_SCHEMA_V2 = {
    "type": "object",
    "oneOf": [
        {
            "properties": {
                "decision": {"const": "pass"},
                "listing_id": {"type": "null"},
                "rent": {"type": "null"},
            },
            "required": ["decision", "listing_id", "rent"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "decision": {"const": "offer"},
                "listing_id": {"type": "integer"},
                "rent": {"type": "number", "minimum": 0},
            },
            "required": ["decision", "listing_id", "rent"],
            "additionalProperties": False,
        },
    ],
}

HOUSING_RESPOND_OUTPUT_SCHEMA_V2 = {
    "type": "object",
    "oneOf": [
        {
            "properties": {
                "decision": {"const": "reject_all"},
                "offer_id": {"type": "null"},
                "counter_rent": {"type": "null"},
            },
            "required": ["decision", "offer_id", "counter_rent"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "decision": {"const": "accept"},
                "offer_id": {"type": "string", "minLength": 1},
                "counter_rent": {"type": "null"},
            },
            "required": ["decision", "offer_id", "counter_rent"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "decision": {"const": "counter"},
                "offer_id": {"type": "string", "minLength": 1},
                "counter_rent": {"type": "number", "minimum": 0},
            },
            "required": ["decision", "offer_id", "counter_rent"],
            "additionalProperties": False,
        },
    ],
}

HOUSING_COMMIT_OUTPUT_SCHEMA_V2 = {
    "type": "object",
    "oneOf": [
        {
            "properties": {
                "decision": {"const": "pass"},
                "hold_id": {"type": "null"},
            },
            "required": ["decision", "hold_id"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "decision": {"enum": ["sign", "walk"]},
                "hold_id": {"type": "string", "minLength": 1},
            },
            "required": ["decision", "hold_id"],
            "additionalProperties": False,
        },
    ],
}

HOUSING_INSPECT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"enum": ["inspect", "pass"]},
        "listing_id": {"type": ["integer", "null"]},
    },
    "required": ["decision", "listing_id"],
    "additionalProperties": False,
}

HOUSING_INSPECT_OUTPUT_SCHEMA_V2 = {
    "type": "object",
    "oneOf": [
        {
            "properties": {
                "decision": {"const": "pass"},
                "listing_id": {"type": "null"},
            },
            "required": ["decision", "listing_id"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "decision": {"const": "inspect"},
                "listing_id": {"type": "integer"},
            },
            "required": ["decision", "listing_id"],
            "additionalProperties": False,
        },
    ],
}

HOUSING_TENANT_LEMONS_PROMPT = """You are one tenant in a scarce housing market in which some listings are lemons.
Use only your private observation and the public board. Every listing posts the same
rent_asked whether it is sound or a lemon. private_values_if_sound[listing_id] is what
a sound listing is worth to you; a lemon is worth lemon_loss less; exactly lemon_count
of the listings are lemons, and only each landlord knows its own listing's quality.
Your objective is your own payoff: the value of the listing you sign minus the rent you
sign at, minus inspection_cost for every inspection you make; if you sign nothing your
payoff is zero minus your inspection spend. Return exactly one JSON object for the
declared action schema. In housing_inspect_v1, inspect one open listing you have not
inspected (its true quality then appears in inspections) or pass. In housing_contact_v1,
either offer one open listing at a rent you can justify or pass. In housing_commit_v1,
sign or walk only the exact immutable hold_id shown in active_hold; pass when no hold
exists. Do not add markdown or explanation."""

HOUSING_TENANT_PROMPT = """You are one tenant in a scarce housing market.
Use only your private observation and the public board. Other tenants' values and
landlords' reservation costs are private. Return exactly one JSON object for the
declared action schema. In housing_contact_v1, either offer one open listing at a
rent you can justify or pass. In housing_commit_v1, sign or walk only the exact
immutable hold_id shown in active_hold; pass when no hold exists. Do not add
markdown or explanation."""

HOUSING_LANDLORD_PROMPT = """You are a deterministic controlled landlord.
Respond only to offers in your private inbox and create at most one binding hold.
Return exactly one JSON object for housing_respond_v1."""


def _seat_index(seat_id: str, prefix: str) -> int:
    marker = prefix + "_"
    if not isinstance(seat_id, str) or not seat_id.startswith(marker):
        raise ValueError(f"invalid {prefix} seat id: {seat_id!r}")
    suffix = seat_id[len(marker) :]
    if not suffix.isdigit():
        raise ValueError(f"invalid {prefix} seat id: {seat_id!r}")
    return int(suffix)


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _housing_source_digests() -> tuple[str, str, str]:
    housing_source = Path(hz.__file__).read_bytes()
    bridge_source = Path(__file__).read_bytes()
    return (
        hashlib.sha256(housing_source).hexdigest(),
        hashlib.sha256(bridge_source).hexdigest(),
        hashlib.sha256(housing_source + bridge_source).hexdigest(),
    )


def _housing_measurement_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    housing_digest, _bridge_digest, combined_digest = _housing_source_digests()
    source_sha256 = hashlib.sha256(
        canonical_json_bytes({"surplus": case["world"].surplus})
    ).hexdigest()
    validity_domain = ValidityDomainSpec(
        domain_id="housing_v1_terminal_domain",
        domain_version="1.0.0",
        schema_ref="housing_v1/outcome/1",
        predicate=MeasurementImplementationRef(
            "housing_outcome_v1", "1.0.0", combined_digest
        ),
    )
    estimand = EstimandSpec(
        estimand_id="social_welfare",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="utility_points",
        validity_domain=validity_domain,
    )
    return MeasurementLeafSpec(
        leaf_id="housing_social_welfare_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="housing_exact_assignment_v1",
                reference_version="1.0.0",
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units="utility_points",
                source_sha256=source_sha256,
                implementation=MeasurementImplementationRef(
                    "housing_exact_assignment_v1", "1.0.0", housing_digest
                ),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id="social_welfare",
                objective_version="1.0.0",
                direction="maximize",
                units="utility_points",
                feasible_set="one tenant and one landlord per signed lease",
                information_set="full case values and private landlord costs",
                horizon="one pinned housing episode",
                environment_condition="pinned housing world and deadline",
                opponent_condition="controlled landlord policy declared in the RunPlan",
                validity_domain=validity_domain,
            ),
        ),
        scorer=MeasurementImplementationRef(
            "housing_outcome_v1", "1.0.0", combined_digest
        ),
    )


def _is_lemons(case: Mapping[str, Any]) -> bool:
    return isinstance(case["world"], lemons_module.LemonsWorld)


def _housing_lemons_source_digests() -> tuple[str, str, str]:
    housing_source = Path(hz.__file__).read_bytes()
    lemons_source = Path(lemons_module.__file__).read_bytes()
    bridge_source = Path(__file__).read_bytes()
    return (
        hashlib.sha256(housing_source).hexdigest(),
        hashlib.sha256(lemons_source).hexdigest(),
        hashlib.sha256(housing_source + lemons_source + bridge_source).hexdigest(),
    )


LEMONS_BOUND_SEMANTICS = "full_information_tenant_capture_relaxation"


def _housing_lemons_measurement_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """The principal's leaf: tenants' net payoff, bracketed by pass, sign-anything and
    the inspect-then-sign reference, under the welfare oracle as upper bound."""
    housing_digest, _lemons_digest, combined_digest = _housing_lemons_source_digests()
    source_sha256 = hashlib.sha256(
        canonical_json_bytes({"surplus": case["world"].surplus})
    ).hexdigest()
    validity_domain = ValidityDomainSpec(
        domain_id="housing_lemons_terminal_domain",
        domain_version="1.0.0",
        schema_ref="housing_v1/lemons_outcome/1",
        predicate=MeasurementImplementationRef(
            "housing_lemons_outcome_v1", "1.0.0", combined_digest
        ),
    )
    estimand = EstimandSpec(
        estimand_id="tenant_net_payoff",
        estimand_version="1.0.0",
        input_scope="terminal_state",
        direction="maximize",
        units="utility_points",
        validity_domain=validity_domain,
    )
    return MeasurementLeafSpec(
        leaf_id="housing_tenant_net_payoff_leaf",
        leaf_version="1.0.0",
        estimand=estimand,
        verifier=VerifierSpec(
            verifier_family="objective_reference",
            evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="housing_exact_assignment_v1",
                reference_version="1.0.0",
                reference_kind="objective_upper_bound",
                input_scope="terminal_state",
                units="utility_points",
                source_sha256=source_sha256,
                implementation=MeasurementImplementationRef(
                    "housing_exact_assignment_v1", "1.0.0", housing_digest
                ),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id="tenant_net_payoff",
                objective_version="1.0.0",
                direction="maximize",
                units="utility_points",
                feasible_set="one tenant and one landlord per signed lease",
                information_set=(
                    "each tenant's own values if sound, the declared lemon count and "
                    "its own paid inspections; true quality and landlord cost private"
                ),
                horizon="one pinned housing episode",
                environment_condition="pinned lemons world and deadline",
                opponent_condition="controlled landlord policy declared in the RunPlan",
                validity_domain=validity_domain,
            ),
        ),
        scorer=MeasurementImplementationRef(
            "housing_lemons_outcome_v1", "1.0.0", combined_digest
        ),
    )


def _housing_case_measurement_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    """The leaf a case scores under, so a failed lemons cell is sealed as typed
    missingness against the lemons pins rather than the bid world's."""
    if _is_lemons(case):
        return _housing_lemons_measurement_leaf(case)
    return _housing_measurement_leaf(case)


def _nonnegative_count(outcome: Mapping[str, Any], field: str, reasons: list[str]) -> int | None:
    value = outcome.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        reasons.append(f"{field} must be a non-negative integer")
        return None
    return value


def _score_housing_lemons_outcome(
    case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    *,
    evidence_refs: Sequence[str] = (),
) -> ScoreEnvelope:
    leaf = _housing_lemons_measurement_leaf(case)
    reasons: list[str] = []
    if not isinstance(outcome, Mapping):
        outcome = {}
        reasons.append("outcome is not a mapping")
    if outcome.get("valid") is not True:
        reasons.append("family outcome is not marked valid")
    if outcome.get("bound_semantics") != LEMONS_BOUND_SEMANTICS:
        reasons.append("upper-bound semantics are missing or changed")

    numeric: dict[str, float] = {}
    for field in (
        "tenant_net_total",
        "social_welfare",
        "gross_social_welfare",
        "feasible_floor",
        "sign_anything_total",
        "reference_total",
        "oracle_total",
    ):
        value = outcome.get(field)
        if not _finite_number(value):
            reasons.append(f"{field} is missing or non-finite")
        else:
            numeric[field] = float(value)

    if "feasible_floor" in numeric and not math.isclose(
        numeric["feasible_floor"], 0.0, abs_tol=1e-12
    ):
        reasons.append("feasible-policy lower bound is not the declared pass policy")
    if "oracle_total" in numeric:
        upper = numeric["oracle_total"]
        if upper < -1e-12:
            reasons.append("assignment upper bound cannot be negative")
        for field, label in (
            ("sign_anything_total", "sign-anything baseline"),
            ("reference_total", "inspect-then-sign reference"),
            ("tenant_net_total", "observed tenant net payoff"),
        ):
            if field in numeric and numeric[field] > upper + 1e-9:
                reasons.append(f"{label} exceeds the declared upper bound")

    tenant_ids = tuple(f"tenant_{index}" for index in range(case["num_tenants"]))
    landlord_ids = tuple(f"landlord_{index}" for index in range(case["num_listings"]))
    gross = _housing_metric_mapping(
        outcome.get("tenant_payoffs"), label="tenant_payoffs",
        expected_ids=tenant_ids, reasons=reasons,
    )
    spend = _housing_metric_mapping(
        outcome.get("tenant_inspection_spend"), label="tenant_inspection_spend",
        expected_ids=tenant_ids, reasons=reasons,
    )
    net = _housing_metric_mapping(
        outcome.get("tenant_net_payoffs"), label="tenant_net_payoffs",
        expected_ids=tenant_ids, reasons=reasons,
    )
    landlord_payoffs = _housing_metric_mapping(
        outcome.get("landlord_payoffs"), label="landlord_payoffs",
        expected_ids=landlord_ids, reasons=reasons,
    )
    if gross and spend and net:
        if any(value < -1e-12 for value in spend.values()):
            reasons.append("inspection spend cannot be negative")
        if any(
            not math.isclose(net[seat], gross[seat] - spend[seat], rel_tol=1e-9, abs_tol=1e-9)
            for seat in tenant_ids
        ):
            reasons.append("tenant net payoffs are not gross payoffs less inspection spend")
        if "tenant_net_total" in numeric and not math.isclose(
            sum(net.values()), numeric["tenant_net_total"], rel_tol=1e-9, abs_tol=1e-9
        ):
            reasons.append("tenant net payoffs do not sum to tenant_net_total")
    if net and landlord_payoffs and "social_welfare" in numeric and not math.isclose(
        sum(net.values()) + sum(landlord_payoffs.values()),
        numeric["social_welfare"], rel_tol=1e-9, abs_tol=1e-9,
    ):
        reasons.append("seat payoffs do not sum to social welfare")
    if gross and landlord_payoffs and "gross_social_welfare" in numeric and not math.isclose(
        sum(gross.values()) + sum(landlord_payoffs.values()),
        numeric["gross_social_welfare"], rel_tol=1e-9, abs_tol=1e-9,
    ):
        reasons.append("gross seat payoffs do not sum to gross social welfare")

    ir_violations = outcome.get("ir_violations")
    if not isinstance(ir_violations, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in ir_violations
    ):
        reasons.append("ir_violations must be a list of seat identifiers")
    counts = {
        field: _nonnegative_count(outcome, field, reasons)
        for field in (
            "wasted_contacts",
            "inspection_count",
            "abstention_decision_count",
            "abstention_correct_count",
            "lemon_signings",
            "uninspected_lemon_signings",
        )
    }
    decisions = counts["abstention_decision_count"]
    correct = counts["abstention_correct_count"]
    if decisions is not None and correct is not None and correct > decisions:
        reasons.append("abstention_correct_count exceeds abstention_decision_count")
    if (
        counts["lemon_signings"] is not None
        and counts["uninspected_lemon_signings"] is not None
        and counts["uninspected_lemon_signings"] > counts["lemon_signings"]
    ):
        reasons.append("uninspected_lemon_signings exceeds lemon_signings")
    declared_rate = outcome.get("abstention_correctness_rate")
    if decisions is not None and correct is not None:
        if decisions == 0:
            if declared_rate is not None:
                reasons.append("abstention_correctness_rate must be null without decisions")
        elif not _finite_number(declared_rate) or not math.isclose(
            float(declared_rate), correct / decisions, rel_tol=1e-9, abs_tol=1e-9
        ):
            reasons.append("abstention_correctness_rate does not match its counts")

    if {"tenant_net_total", "oracle_total"}.issubset(numeric):
        declared_ratio = outcome.get("within_case_score")
        if numeric["oracle_total"] > 0:
            expected_ratio = numeric["tenant_net_total"] / numeric["oracle_total"]
            if not _finite_number(declared_ratio) or not math.isclose(
                float(declared_ratio), expected_ratio, rel_tol=1e-9, abs_tol=1e-9
            ):
                reasons.append(
                    "within_case_score does not match tenant net payoff over upper bound"
                )
        elif declared_ratio is not None:
            reasons.append("within_case_score must be null when the upper bound is zero")

    if reasons:
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=ValidityReport("invalid", tuple(dict.fromkeys(reasons))),
            evidence_refs=tuple(evidence_refs),
        )

    net_total = numeric["tenant_net_total"]
    baseline = numeric["sign_anything_total"]
    reference = numeric["reference_total"]
    upper = numeric["oracle_total"]
    metrics = {
        "tenant_net_payoff": MetricValue(net_total, "utility_points"),
        "social_welfare": MetricValue(numeric["social_welfare"], "utility_points"),
        "sign_anything_gap": MetricValue(net_total - baseline, "utility_points"),
        "reference_gap": MetricValue(reference - net_total, "utility_points"),
        "upper_bound_gap": MetricValue(upper - net_total, "utility_points"),
        "ir_violation_count": MetricValue(float(len(ir_violations)), "count"),
        "wasted_contacts": MetricValue(float(counts["wasted_contacts"]), "count"),
        "inspection_count": MetricValue(float(counts["inspection_count"]), "count"),
        "inspection_spend": MetricValue(sum(spend.values()), "utility_points"),
        "abstention_decision_count": MetricValue(float(decisions), "count"),
        "uninspected_lemon_signings": MetricValue(
            float(counts["uninspected_lemon_signings"]), "count"
        ),
    }
    if decisions > 0:
        metrics["abstention_correctness_rate"] = MetricValue(correct / decisions, "ratio")
    if upper > 0:
        metrics["within_case_score"] = MetricValue(net_total / upper, "ratio")
    references = {
        "optimum_lower_bound": MetricValue(
            numeric["feasible_floor"],
            "utility_points",
            {"reference_kind": "objective_lower_bound", "policy": "pass"},
        ),
        "comparison_baseline": MetricValue(
            baseline,
            "utility_points",
            {"reference_kind": "comparison_baseline", "policy": "sign_anything"},
        ),
        "scripted_reference": MetricValue(
            reference,
            "utility_points",
            {"reference_kind": "scripted_reference", "policy": "inspect_then_sign"},
        ),
        "optimum_upper_bound": MetricValue(
            upper,
            "utility_points",
            {"reference_kind": "objective_upper_bound", "semantics": LEMONS_BOUND_SEMANTICS},
        ),
    }
    utility = {
        seat_id: MetricValue(payoff, "utility_points", {"disagreement_utility": 0.0})
        for seat_id, payoff in sorted({**net, **landlord_payoffs}.items())
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=metrics["tenant_net_payoff"],
        metrics=metrics,
        reference_values=references,
        validity=ValidityReport("valid"),
        evidence_refs=tuple(evidence_refs),
        utility_by_seat=utility,
        capture_by_seat=utility,
    )


def _housing_metric_mapping(
    value: object, *, label: str, expected_ids: Sequence[str], reasons: list[str]
) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(expected_ids):
        reasons.append(f"{label} does not match the declared seats")
        return {}
    result: dict[str, float] = {}
    for seat_id in sorted(expected_ids):
        payoff = value[seat_id]
        if not _finite_number(payoff):
            reasons.append(f"{label} contains a non-finite payoff")
            return {}
        result[seat_id] = float(payoff)
    return result


def _score_housing_outcome(
    case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    *,
    evidence_refs: Sequence[str] = (),
) -> ScoreEnvelope:
    leaf = _housing_measurement_leaf(case)
    reasons: list[str] = []
    if not isinstance(outcome, Mapping):
        outcome = {}
        reasons.append("outcome is not a mapping")
    if outcome.get("valid") is not True:
        reasons.append("family outcome is not marked valid")
    if outcome.get("bound_semantics") != "full_information_allocation_relaxation":
        reasons.append("upper-bound semantics are missing or changed")

    numeric: dict[str, float] = {}
    for field in ("social_welfare", "feasible_floor", "baseline_total", "oracle_total"):
        value = outcome.get(field)
        if not _finite_number(value):
            reasons.append(f"{field} is missing or non-finite")
        else:
            numeric[field] = float(value)

    if "feasible_floor" in numeric and not math.isclose(
        numeric["feasible_floor"], 0.0, abs_tol=1e-12
    ):
        reasons.append("feasible-policy lower bound is not the declared zero policy")
    if "oracle_total" in numeric and numeric["oracle_total"] < -1e-12:
        reasons.append("assignment upper bound cannot be negative")
    if {"feasible_floor", "oracle_total"}.issubset(numeric) and (
        numeric["feasible_floor"] > numeric["oracle_total"] + 1e-9
    ):
        reasons.append("optimum lower bound exceeds the upper bound")
    if {"baseline_total", "oracle_total"}.issubset(numeric) and (
        numeric["baseline_total"] > numeric["oracle_total"] + 1e-9
    ):
        reasons.append("comparison baseline exceeds the declared upper bound")
    if {"social_welfare", "oracle_total"}.issubset(numeric) and (
        numeric["social_welfare"] > numeric["oracle_total"] + 1e-9
    ):
        reasons.append("observed welfare exceeds the declared upper bound")

    tenant_ids = tuple(f"tenant_{index}" for index in range(case["num_tenants"]))
    landlord_ids = tuple(f"landlord_{index}" for index in range(case["num_listings"]))
    tenant_payoffs = _housing_metric_mapping(
        outcome.get("tenant_payoffs"),
        label="tenant_payoffs",
        expected_ids=tenant_ids,
        reasons=reasons,
    )
    landlord_payoffs = _housing_metric_mapping(
        outcome.get("landlord_payoffs"),
        label="landlord_payoffs",
        expected_ids=landlord_ids,
        reasons=reasons,
    )
    payoffs = {**tenant_payoffs, **landlord_payoffs}
    if (
        payoffs
        and "social_welfare" in numeric
        and not math.isclose(
            sum(payoffs.values()), numeric["social_welfare"], rel_tol=1e-9, abs_tol=1e-9
        )
    ):
        reasons.append("seat payoffs do not sum to social welfare")

    ir_violations = outcome.get("ir_violations")
    if not isinstance(ir_violations, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in ir_violations
    ):
        reasons.append("ir_violations must be a list of seat identifiers")
    wasted_contacts = outcome.get("wasted_contacts")
    if (
        isinstance(wasted_contacts, bool)
        or not isinstance(wasted_contacts, int)
        or wasted_contacts < 0
    ):
        reasons.append("wasted_contacts must be a non-negative integer")

    if {"social_welfare", "oracle_total"}.issubset(numeric):
        declared_ratio = outcome.get("within_case_score")
        if numeric["oracle_total"] > 0:
            expected_ratio = numeric["social_welfare"] / numeric["oracle_total"]
            if not _finite_number(declared_ratio) or not math.isclose(
                float(declared_ratio), expected_ratio, rel_tol=1e-9, abs_tol=1e-9
            ):
                reasons.append(
                    "within_case_score does not match welfare over upper bound"
                )
        elif declared_ratio is not None:
            reasons.append(
                "within_case_score must be null when the upper bound is zero"
            )

    if reasons:
        return ScoreEnvelope(
            status="invalid_measurement",
            leaf=leaf,
            primary=None,
            metrics={},
            reference_values={},
            validity=ValidityReport("invalid", tuple(dict.fromkeys(reasons))),
            evidence_refs=tuple(evidence_refs),
        )

    welfare = numeric["social_welfare"]
    lower = numeric["feasible_floor"]
    baseline = numeric["baseline_total"]
    upper = numeric["oracle_total"]
    metrics = {
        "social_welfare": MetricValue(welfare, "utility_points"),
        "comparison_baseline_gap": MetricValue(welfare - baseline, "utility_points"),
        "upper_bound_gap": MetricValue(upper - welfare, "utility_points"),
        "ir_violation_count": MetricValue(float(len(ir_violations)), "count"),
        "wasted_contacts": MetricValue(float(wasted_contacts), "count"),
    }
    if upper > 0:
        metrics["within_case_score"] = MetricValue(welfare / upper, "ratio")
    references = {
        "optimum_lower_bound": MetricValue(
            lower,
            "utility_points",
            {"reference_kind": "objective_lower_bound", "policy": "do_nothing"},
        ),
        "comparison_baseline": MetricValue(
            baseline,
            "utility_points",
            {"reference_kind": "comparison_baseline", "policy": "naive"},
        ),
        "optimum_upper_bound": MetricValue(
            upper,
            "utility_points",
            {
                "reference_kind": "objective_upper_bound",
                "semantics": "full_information_allocation_relaxation",
            },
        ),
    }
    utility = {
        seat_id: MetricValue(
            payoff,
            "utility_points",
            {"disagreement_utility": 0.0},
        )
        for seat_id, payoff in sorted(payoffs.items())
    }
    return ScoreEnvelope(
        status="ok",
        leaf=leaf,
        primary=metrics["social_welfare"],
        metrics=metrics,
        reference_values=references,
        validity=ValidityReport("valid"),
        evidence_refs=tuple(evidence_refs),
        utility_by_seat=utility,
        capture_by_seat=utility,
    )


def _snapshot_market(market: hz.HousingMarket) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "round_index": market.round_index,
        "phase": market.phase,
        "pairs": [list(pair) for pair in market.pairs],
        "signed_rents": [
            {"tenant_id": tenant_id, "rent": rent}
            for tenant_id, rent in sorted(market.signed_rent.items())
        ],
        "taken_listing_ids": sorted(market._taken),
        "matched_tenant_ids": sorted(market._matched),
        "offers": [
            {
                "listing_id": listing_id,
                "items": [dataclasses.asdict(offer) for offer in offers],
            }
            for listing_id, offers in sorted(market._offers.items())
        ],
        "holds": [
            dataclasses.asdict(hold) for _, hold in sorted(market._holds.items())
        ],
        "rejected": [
            {"tenant_id": tenant_id, "listing_ids": sorted(listing_ids)}
            for tenant_id, listing_ids in sorted(market.rejected.items())
        ],
        "wasted_contacts": market.wasted_contacts,
    }
    if market.lemons:
        snapshot["inspected"] = [
            {
                "tenant_id": tenant_id,
                "items": [
                    {"listing_id": listing_id, "quality": quality}
                    for listing_id, quality in sorted(known.items())
                ],
            }
            for tenant_id, known in sorted(market.inspected.items())
        ]
        snapshot["inspection_spend"] = [
            {"tenant_id": tenant_id, "spend": spend}
            for tenant_id, spend in sorted(market.inspection_spend.items())
        ]
        snapshot["commit_decisions"] = [dict(row) for row in market.commit_decisions]
    return snapshot


def _restore_market(
    family_case: Mapping[str, Any], state: Mapping[str, Any]
) -> hz.HousingMarket:
    market = hz.HousingMarket(family_case["world"], rounds=family_case["rounds"])
    market.round_index = int(state["round_index"])
    market.phase = str(state["phase"])
    market.pairs = [tuple(pair) for pair in state["pairs"]]
    market.signed_rent = {
        int(item["tenant_id"]): float(item["rent"]) for item in state["signed_rents"]
    }
    market._taken = {int(value) for value in state["taken_listing_ids"]}
    market._matched = {int(value) for value in state["matched_tenant_ids"]}
    market._offers = {
        int(item["listing_id"]): tuple(
            hz.Offer(**dict(offer)) for offer in item["items"]
        )
        for item in state["offers"]
    }
    market._holds = {
        int(item["tenant_id"]): hz.Hold(**dict(item)) for item in state["holds"]
    }
    market.rejected = {
        int(item["tenant_id"]): {int(value) for value in item["listing_ids"]}
        for item in state["rejected"]
    }
    market.wasted_contacts = int(state["wasted_contacts"])
    if market.lemons:
        market.inspected = {
            int(item["tenant_id"]): {
                int(row["listing_id"]): int(row["quality"]) for row in item["items"]
            }
            for item in state["inspected"]
        }
        market.inspection_spend = {
            int(item["tenant_id"]): float(item["spend"])
            for item in state["inspection_spend"]
        }
        market.commit_decisions = [dict(row) for row in state["commit_decisions"]]
    return market


def _phase_consequences(result: hz.PhaseResult) -> dict[str, Any]:
    return {
        "phase": result.phase,
        "verdicts": [
            dataclasses.asdict(verdict)
            for _, verdict in sorted(
                result.verdicts.items(), key=lambda item: str(item[0])
            )
        ],
        "inbox": [
            {
                "listing_id": listing_id,
                "offers": [dataclasses.asdict(offer) for offer in offers],
            }
            for listing_id, offers in sorted(result.inbox.items())
        ],
        "holds": [dataclasses.asdict(hold) for _, hold in sorted(result.holds.items())],
    }


class HousingV1Plugin:
    """Strict Housing V1 adapter for the generic family-plugin boundary."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("housing payload must be a mapping")
        expected = {
            "world_kind",
            "world_seed",
            "num_tenants",
            "num_listings",
            "rounds",
            "common_weight",
        }
        world_kind = payload.get("world_kind")
        if world_kind == "lemons":
            expected |= {"lemon_share", "lemon_loss", "inspection_cost"}
        if set(payload) != expected:
            raise ValueError("housing payload fields are incomplete or unexpected")
        if world_kind not in {"bid", "lemons"}:
            raise ValueError("only the pinned bid and lemons worlds are supported")
        integers: dict[str, int] = {}
        for field, minimum in (
            ("world_seed", 0),
            ("num_tenants", 1),
            ("num_listings", 1),
            ("rounds", 1),
        ):
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{field} must be an integer >= {minimum}")
            integers[field] = value
        common_weight = payload["common_weight"]
        if not _finite_number(common_weight) or not 0.0 <= float(common_weight) <= 1.0:
            raise ValueError("common_weight must be between zero and one")
        if world_kind == "lemons":
            for field in ("lemon_share", "lemon_loss", "inspection_cost"):
                if not _finite_number(payload[field]) or float(payload[field]) < 0.0:
                    raise ValueError(f"{field} must be a finite non-negative number")
            if float(payload["lemon_share"]) > 1.0:
                raise ValueError("lemon_share must be between zero and one")
            world = lemons_module.make_lemons_world(
                integers["num_tenants"],
                integers["num_listings"],
                seed=integers["world_seed"],
                common_weight=float(common_weight),
                lemon_share=float(payload["lemon_share"]),
                lemon_loss=float(payload["lemon_loss"]),
                inspection_cost=float(payload["inspection_cost"]),
            )
            return {
                **integers,
                "common_weight": float(common_weight),
                "lemon_share": float(payload["lemon_share"]),
                "lemon_loss": float(payload["lemon_loss"]),
                "inspection_cost": float(payload["inspection_cost"]),
                "world": world,
            }
        world = hz.make_bid_world(
            integers["num_tenants"],
            integers["num_listings"],
            seed=integers["world_seed"],
            common_weight=float(common_weight),
        )
        return {**integers, "common_weight": float(common_weight), "world": world}

    def initial_state(self, case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        return _snapshot_market(hz.HousingMarket(case["world"], rounds=case["rounds"]))

    def phases(self, case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        tenant_budget = case["num_tenants"] * case["rounds"]
        landlord_budget = case["num_listings"] * case["rounds"]
        lemons = _is_lemons(case)
        inspect_phase = (
            PhaseSpec(
                phase_id="inspect",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={
                    "tenant": "housing_tenant_inspect_observation_v1"
                },
                action_schema_by_role={"tenant": "housing_inspect_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("contact",),
            ),
        ) if lemons else ()
        return (
            *inspect_phase,
            PhaseSpec(
                phase_id="contact",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={
                    "tenant": "housing_tenant_contact_observation_v1"
                },
                action_schema_by_role={"tenant": "housing_contact_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("respond",),
            ),
            PhaseSpec(
                phase_id="respond",
                actor_selector="open_landlords",
                mode="simultaneous",
                observation_schema_by_role={
                    "landlord": "housing_landlord_respond_observation_v1"
                },
                action_schema_by_role={"landlord": "housing_respond_v1"},
                max_logical_actions=landlord_budget,
                invalid_action_policy="family_defined",
                next_phases=("commit",),
            ),
            PhaseSpec(
                phase_id="commit",
                actor_selector="unmatched_tenants",
                mode="simultaneous",
                observation_schema_by_role={
                    "tenant": "housing_tenant_commit_observation_v1"
                },
                action_schema_by_role={"tenant": "housing_commit_v1"},
                max_logical_actions=tenant_budget,
                invalid_action_policy="family_defined",
                next_phases=("inspect",) if lemons else ("contact",),
            ),
        )

    def eligible_actors(self, case, state, phase) -> tuple[str, ...]:
        market = _restore_market(case, state)
        if phase.phase_id in {"inspect", "contact", "commit"}:
            return tuple(
                f"tenant_{tenant_id}" for tenant_id in market.unmatched_tenants()
            )
        if phase.phase_id == "respond":
            return tuple(
                f"landlord_{listing_id}" for listing_id in market.open_listings()
            )
        raise ValueError(f"unknown housing phase: {phase.phase_id!r}")

    def observe(self, case, state, seat, phase) -> dict[str, Any]:
        market = _restore_market(case, state)
        if phase.phase_id in {"inspect", "contact", "commit"}:
            return market.tenant_observation(_seat_index(seat, "tenant"))
        if phase.phase_id == "respond":
            return market.landlord_observation(_seat_index(seat, "landlord"))
        raise ValueError(f"unknown housing phase: {phase.phase_id!r}")

    def parse_action(self, case, state, seat, phase, response) -> ParseResult:
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict):
            return ParseResult.failure("malformed_action")

        if phase.phase_id == "inspect":
            if set(value) != {"decision", "listing_id"}:
                return ParseResult.failure("malformed_inspection")
            if value["decision"] == "pass" and value["listing_id"] is None:
                return ParseResult.success({"decision": "pass"})
            if (
                value["decision"] == "inspect"
                and isinstance(value["listing_id"], int)
                and not isinstance(value["listing_id"], bool)
            ):
                return ParseResult.success(
                    {"decision": "inspect", "listing_id": value["listing_id"]}
                )
            return ParseResult.failure("malformed_inspection")

        if phase.phase_id == "contact":
            if set(value) != {"decision", "listing_id", "rent"}:
                return ParseResult.failure("malformed_contact")
            if (
                value["decision"] == "pass"
                and value["listing_id"] is None
                and value["rent"] is None
            ):
                return ParseResult.success({"decision": "pass"})
            if (
                value["decision"] == "offer"
                and isinstance(value["listing_id"], int)
                and not isinstance(value["listing_id"], bool)
                and _finite_number(value["rent"])
            ):
                return ParseResult.success(
                    {
                        "decision": "offer",
                        "listing_id": value["listing_id"],
                        "rent": float(value["rent"]),
                    }
                )
            return ParseResult.failure("malformed_contact")

        if phase.phase_id == "respond":
            if set(value) != {"decision", "offer_id", "counter_rent"}:
                return ParseResult.failure("malformed_response")
            decision = value["decision"]
            if (
                decision == "reject_all"
                and value["offer_id"] is None
                and value["counter_rent"] is None
            ):
                return ParseResult.success({"decision": "reject_all"})
            if (
                decision == "accept"
                and isinstance(value["offer_id"], str)
                and value["counter_rent"] is None
            ):
                return ParseResult.success(
                    {"decision": "accept", "offer_id": value["offer_id"]}
                )
            if (
                decision == "counter"
                and isinstance(value["offer_id"], str)
                and _finite_number(value["counter_rent"])
            ):
                return ParseResult.success(
                    {
                        "decision": "counter",
                        "offer_id": value["offer_id"],
                        "counter_rent": float(value["counter_rent"]),
                    }
                )
            return ParseResult.failure("malformed_response")

        if phase.phase_id == "commit":
            if set(value) != {"decision", "hold_id"}:
                return ParseResult.failure("malformed_commit")
            if value["decision"] == "pass" and value["hold_id"] is None:
                return ParseResult.success({"decision": "pass"})
            if value["decision"] in {"sign", "walk"} and isinstance(
                value["hold_id"], str
            ):
                return ParseResult.success(
                    {"decision": value["decision"], "hold_id": value["hold_id"]}
                )
            return ParseResult.failure("malformed_commit")

        return ParseResult.failure("unknown_phase")

    def legal(self, case, state, seat, phase, action) -> LegalityResult:
        market = _restore_market(case, state)
        decision = action["decision"]
        if decision in {"pass", "reject_all"}:
            return LegalityResult.legal_action()
        if phase.phase_id == "inspect":
            tenant_id = _seat_index(seat, "tenant")
            if tenant_id not in market.unmatched_tenants():
                return LegalityResult.illegal("unavailable_tenant")
            if action["listing_id"] not in market.open_listings():
                return LegalityResult.illegal("unavailable_listing")
            if action["listing_id"] in market.inspected[tenant_id]:
                return LegalityResult.illegal("already_inspected")
            return LegalityResult.legal_action()
        if phase.phase_id == "contact":
            tenant_id = _seat_index(seat, "tenant")
            if tenant_id not in market.unmatched_tenants():
                return LegalityResult.illegal("unavailable_tenant")
            if action["listing_id"] not in market.open_listings():
                return LegalityResult.illegal("unavailable_listing")
            if action["rent"] < 0:
                return LegalityResult.illegal("invalid_rent")
            return LegalityResult.legal_action()
        if phase.phase_id == "respond":
            listing_id = _seat_index(seat, "landlord")
            offer_ids = {offer.offer_id for offer in market._offers.get(listing_id, ())}
            if action["offer_id"] not in offer_ids:
                return LegalityResult.illegal("unknown_offer")
            if decision == "counter" and action["counter_rent"] < 0:
                return LegalityResult.illegal("invalid_rent")
            return LegalityResult.legal_action()
        if phase.phase_id == "commit":
            tenant_id = _seat_index(seat, "tenant")
            hold = market.active_holds().get(tenant_id)
            if hold is None or hold.hold_id != action["hold_id"]:
                return LegalityResult.illegal("unknown_hold")
            return LegalityResult.legal_action()
        return LegalityResult.illegal("unknown_phase")

    def step(self, case, state, phase, actions) -> TransitionResult:
        market = _restore_market(case, state)
        if phase.phase_id == "inspect":
            requests: dict[int, int] = {}
            for seat_id, envelope in actions.items():
                if envelope.valid and envelope.action["decision"] == "inspect":
                    requests[_seat_index(seat_id, "tenant")] = envelope.action["listing_id"]
            result = market.submit_inspections(requests)
            next_phase = "contact"
        elif phase.phase_id == "contact":
            offers: dict[int, tuple[int, float]] = {}
            for seat_id, envelope in actions.items():
                if envelope.valid and envelope.action["decision"] == "offer":
                    offers[_seat_index(seat_id, "tenant")] = (
                        envelope.action["listing_id"],
                        envelope.action["rent"],
                    )
            result = market.submit_offers(offers)
            next_phase = "respond"
        elif phase.phase_id == "respond":
            responses: dict[int, dict[int, tuple[str, float | None]]] = {}
            for seat_id, envelope in actions.items():
                if not envelope.valid:
                    continue
                listing_id = _seat_index(seat_id, "landlord")
                inbox = market._offers.get(listing_id, ())
                action = envelope.action
                if action["decision"] == "reject_all":
                    responses[listing_id] = {
                        offer.tenant_id: ("reject", None) for offer in inbox
                    }
                    continue
                chosen = next(
                    offer for offer in inbox if offer.offer_id == action["offer_id"]
                )
                per_listing = {offer.tenant_id: ("reject", None) for offer in inbox}
                if action["decision"] == "accept":
                    per_listing[chosen.tenant_id] = ("accept", None)
                else:
                    per_listing[chosen.tenant_id] = (
                        "counter",
                        action["counter_rent"],
                    )
                responses[listing_id] = per_listing
            result = market.submit_responses(responses)
            next_phase = "commit"
        elif phase.phase_id == "commit":
            commits: dict[int, tuple[str, str]] = {}
            for seat_id, envelope in actions.items():
                if envelope.valid and envelope.action["decision"] in {"sign", "walk"}:
                    commits[_seat_index(seat_id, "tenant")] = (
                        envelope.action["decision"],
                        envelope.action["hold_id"],
                    )
            result = market.submit_commits(commits)
            next_phase = market.round_start_phase
        else:
            raise ValueError(f"unknown housing phase: {phase.phase_id!r}")
        return TransitionResult(
            state=_snapshot_market(market),
            next_phase_id=next_phase,
            consequences=_phase_consequences(result),
        )

    def terminal(self, case, state) -> dict[str, Any] | None:
        market = _restore_market(case, state)
        if not market.finished:
            return None
        if _is_lemons(case):
            return self._lemons_terminal(case, market)
        economics = market.economics()
        oracle = hz.assignment_oracle(market.world.surplus)
        baseline = hz.run_scripted_market(
            market.world,
            rounds=case["rounds"],
            strategy="naive",
        )
        score = economics.social_welfare / oracle.total if oracle.total > 0 else None
        return {
            "reason": (
                "deadline" if market.round_index >= market.rounds else "allocation"
            ),
            "assignment_pairs": [list(pair) for pair in economics.assignment.pairs],
            "signed_rents": [
                {"tenant_id": tenant_id, "rent": rent}
                for tenant_id, rent in sorted(economics.signed_rents.items())
            ],
            "tenant_payoffs": {
                f"tenant_{tenant_id}": payoff
                for tenant_id, payoff in sorted(economics.tenant_payoffs.items())
            },
            "landlord_payoffs": {
                f"landlord_{listing_id}": payoff
                for listing_id, payoff in sorted(economics.landlord_payoffs.items())
            },
            "social_welfare": economics.social_welfare,
            "feasible_floor": 0.0,
            "baseline_total": baseline.total,
            "oracle_total": oracle.total,
            "within_case_score": score,
            "ir_violations": list(economics.ir_violations),
            "wasted_contacts": market.wasted_contacts,
            "bound_semantics": "full_information_allocation_relaxation",
        }

    @staticmethod
    def _lemons_terminal(case: Mapping[str, Any], market: hz.HousingMarket) -> dict[str, Any]:
        economics = market.economics()
        accounting = market.lemons_accounting()
        world = market.world
        oracle = hz.assignment_oracle(world.surplus)
        rounds = case["rounds"]
        sign_anything = lemons_module.run_lemons_policy(
            world, rounds, "sign_anything"
        ).lemons_accounting()["tenant_net_total"]
        reference = lemons_module.run_lemons_policy(
            world, rounds, "inspect_then_sign"
        ).lemons_accounting()["tenant_net_total"]
        net_total = accounting["tenant_net_total"]
        score = net_total / oracle.total if oracle.total > 0 else None
        tenants = sorted(economics.tenant_payoffs)
        return {
            "reason": (
                "deadline" if market.round_index >= market.rounds else "allocation"
            ),
            "assignment_pairs": [list(pair) for pair in economics.assignment.pairs],
            "signed_rents": [
                {"tenant_id": tenant_id, "rent": rent}
                for tenant_id, rent in sorted(economics.signed_rents.items())
            ],
            "quality": [hz.QUALITY_LABEL[quality] for quality in world.quality],
            "tenant_payoffs": {
                f"tenant_{tenant_id}": economics.tenant_payoffs[tenant_id]
                for tenant_id in tenants
            },
            "tenant_inspection_spend": {
                f"tenant_{tenant_id}": accounting["tenant_inspection_spend"][tenant_id]
                for tenant_id in tenants
            },
            "tenant_net_payoffs": {
                f"tenant_{tenant_id}": accounting["tenant_net_payoffs"][tenant_id]
                for tenant_id in tenants
            },
            "landlord_payoffs": {
                f"landlord_{listing_id}": payoff
                for listing_id, payoff in sorted(economics.landlord_payoffs.items())
            },
            "tenant_net_total": net_total,
            "social_welfare": accounting["net_social_welfare"],
            "gross_social_welfare": economics.social_welfare,
            "feasible_floor": 0.0,
            "sign_anything_total": sign_anything,
            "reference_total": reference,
            "oracle_total": oracle.total,
            "within_case_score": score,
            "ir_violations": list(economics.ir_violations),
            "wasted_contacts": market.wasted_contacts,
            "inspection_count": accounting["inspection_count"],
            "commit_decisions": accounting["commit_decisions"],
            "abstention_decision_count": accounting["abstention_decision_count"],
            "abstention_correct_count": accounting["abstention_correct_count"],
            "abstention_correctness_rate": accounting["abstention_correctness_rate"],
            "lemon_signings": accounting["lemon_signings"],
            "uninspected_lemon_signings": accounting["uninspected_lemon_signings"],
            "bound_semantics": LEMONS_BOUND_SEMANTICS,
        }

    def outcome(self, case, terminal) -> dict[str, Any]:
        return {"valid": True, **dict(terminal)}

    def build_scorer(self, case):
        scorer = _score_housing_lemons_outcome if _is_lemons(case) else _score_housing_outcome

        def score(
            scoring_input: FamilyScoringInput, *, evidence_refs: Sequence[str] = ()
        ) -> ScoreEnvelope:
            return scorer(case, scoring_input.outcome, evidence_refs=evidence_refs)

        return score

    def build_reference_providers(self, case):
        if _is_lemons(case):
            return (
                "housing_feasible_zero_v1",
                "housing_sign_anything_v1",
                "housing_inspect_then_sign_v1",
                "housing_exact_assignment_v1",
            )
        return (
            "housing_feasible_zero_v1",
            "housing_naive_v1",
            "housing_exact_assignment_v1",
        )

    def generator(self):
        return hz.make_bid_world


def _scripted_result(
    request: ProviderRequest, output: Mapping[str, Any]
) -> ProviderResult:
    text = canonical_json_bytes(output).decode("utf-8")
    return ProviderResult(
        response_id=f"scripted_{request.provider_call_id}",
        requested_model=request.model,
        resolved_model=request.revision or request.model,
        output_text=text,
        finish_reason="stop",
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        raw_response={"fixture": True, "output_text": text},
    )


# The sealed scripted-tenant model id selects the policy. ``None`` is the
# legacy bid-world tenant; the others are the lemons-world bracket policies
# shared with the offline admission gate (``lemons.TENANT_POLICIES``).
SCRIPTED_TENANT_MODELS: dict[str, str | None] = {
    "housing_scripted_tenant_v1": None,
    "housing_scripted_tenant_sign_anything_v1": "sign_anything",
    "housing_scripted_tenant_inspect_then_sign_v1": "inspect_then_sign",
    "housing_scripted_tenant_pass_v1": "pass",
}
SCRIPTED_TENANT_REVISION = "1.0.0"
LEMONS_SCRIPTED_TENANT_MODELS = tuple(
    model for model, policy in SCRIPTED_TENANT_MODELS.items() if policy is not None
)


class HousingScriptedTenantProvider:
    """Dispatch the sealed model id to a scripted tenant policy."""

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "housing_scripted_tenant":
            raise ProviderFailure(
                "provider_contract", "wrong scripted tenant provider", retryable=False
            )
        if (
            request.model not in SCRIPTED_TENANT_MODELS
            or request.revision != SCRIPTED_TENANT_REVISION
        ):
            raise ProviderFailure(
                "provider_contract",
                "unknown scripted tenant model/revision",
                retryable=False,
            )
        payload = json.loads(request.input_text)
        observation = payload["observation"]
        policy_id = SCRIPTED_TENANT_MODELS[request.model]
        if policy_id is not None:
            if "private_values_if_sound" not in observation:
                raise ProviderFailure(
                    "provider_contract",
                    "scripted lemons tenant requires a lemons observation",
                    retryable=False,
                )
            if payload["phase_id"] not in {"inspect", "contact", "commit"}:
                raise ProviderFailure(
                    "provider_contract",
                    "scripted tenant received wrong phase",
                    retryable=False,
                )
            output = lemons_module.TENANT_POLICIES[policy_id](
                observation, payload["phase_id"]
            )
            return _scripted_result(request, output)
        if "private_values" not in observation:
            raise ProviderFailure(
                "provider_contract",
                "legacy scripted tenant cannot play a lemons world",
                retryable=False,
            )
        if payload["phase_id"] == "contact":
            values = observation["private_values"]
            candidates = [
                row for row in observation["board"] if row["status"] == "OPEN"
            ]
            viable = [
                row
                for row in candidates
                if values[row["listing_id"]] > row["rent_asked"]
            ]
            if not viable:
                output = {"decision": "pass", "listing_id": None, "rent": None}
            else:
                chosen = max(
                    viable,
                    key=lambda row: values[row["listing_id"]] - row["rent_asked"],
                )
                listing_id = chosen["listing_id"]
                output = {
                    "decision": "offer",
                    "listing_id": listing_id,
                    "rent": min(values[listing_id], chosen["rent_asked"] + 1.0),
                }
        elif payload["phase_id"] == "commit":
            hold = observation.get("active_hold")
            if not hold:
                output = {"decision": "pass", "hold_id": None}
            else:
                listing_id = hold["listing_id"]
                decision = (
                    "sign"
                    if hold["rent"] <= observation["private_values"][listing_id]
                    else "walk"
                )
                output = {"decision": decision, "hold_id": hold["hold_id"]}
        else:
            raise ProviderFailure(
                "provider_contract",
                "scripted tenant received wrong phase",
                retryable=False,
            )
        return _scripted_result(request, output)


class HousingScriptedLandlordProvider:
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if request.provider != "housing_scripted_landlord":
            raise ProviderFailure(
                "provider_contract", "wrong scripted landlord provider", retryable=False
            )
        payload = json.loads(request.input_text)
        if payload["phase_id"] != "respond":
            raise ProviderFailure(
                "provider_contract",
                "scripted landlord received wrong phase",
                retryable=False,
            )
        observation = payload["observation"]
        inbox = observation["inbox"]
        if not inbox:
            output = {
                "decision": "reject_all",
                "offer_id": None,
                "counter_rent": None,
            }
        else:
            viable = [
                offer for offer in inbox if offer["rent"] >= observation["private_cost"]
            ]
            if viable:
                chosen = max(
                    viable, key=lambda offer: (offer["rent"], -offer["tenant_id"])
                )
                output = {
                    "decision": "accept",
                    "offer_id": chosen["offer_id"],
                    "counter_rent": None,
                }
            else:
                chosen = max(
                    inbox, key=lambda offer: (offer["rent"], -offer["tenant_id"])
                )
                output = {
                    "decision": "counter",
                    "offer_id": chosen["offer_id"],
                    "counter_rent": round(
                        (chosen["rent"] + observation["listing"]["rent_asked"]) / 2.0,
                        2,
                    ),
                }
        return _scripted_result(request, output)


@dataclass(frozen=True, slots=True)
class HousingSmokeSetup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    harnesses: Mapping[str, Any]


def finalize_housing_execution(
    *, setup: HousingSmokeSetup, execution: CellExecution
) -> EvaluationReceipt:
    """Finalize Housing through the shared family receipt implementation."""
    if not isinstance(setup, HousingSmokeSetup):
        raise TypeError("setup must be a HousingSmokeSetup")
    return finalize_family_execution(setup=setup, execution=execution)


def finalize_housing_failure(
    *,
    setup: HousingSmokeSetup,
    cell_id: str,
    evidence_root: str | Path,
    error: BaseException,
) -> EvaluationReceipt:
    """Retain operational failure as a shared typed receipt exclusion."""
    return finalize_family_failure(
        setup=setup,
        cell_id=cell_id,
        evidence_root=evidence_root,
        error=error,
        leaf_builder=_housing_case_measurement_leaf,
    )


def replay_housing_receipt(
    *,
    setup: HousingSmokeSetup,
    receipt: EvaluationReceipt,
    evidence_root: str | Path,
) -> EvaluationReceipt:
    """Recompute Housing state and score without another provider call."""
    return replay_family_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    )


@dataclass(frozen=True, slots=True)
class OpenRouterRoutePin:
    """Exact OpenRouter endpoint identity and price ceiling sealed into a plan."""

    provider: str
    quantization: str
    canonical_model: str
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    pricing_id: str

    def __post_init__(self) -> None:
        for name in ("provider", "quantization", "canonical_model", "pricing_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        self.token_pricing()

    def token_pricing(self) -> TokenPricing:
        return TokenPricing(
            self.input_per_million,
            self.cached_input_per_million,
            self.output_per_million,
            self.pricing_id,
        )

    def provider_metadata(self) -> dict[str, str]:
        return {
            "route_provider": self.provider,
            "quantization": self.quantization,
            "canonical_model": self.canonical_model,
            "max_prompt_price_per_million": format(self.input_per_million, ".15g"),
            "max_completion_price_per_million": format(self.output_per_million, ".15g"),
        }


DEEPINFRA_HOUSING_ROUTE = OpenRouterRoutePin(
    provider="DeepInfra",
    quantization="fp8",
    canonical_model="deepseek/deepseek-v4-flash-20260731",
    input_per_million=0.08,
    cached_input_per_million=0.016,
    output_per_million=0.18,
    pricing_id="openrouter_deepinfra_2026-08-26_deepseek-v4-flash-0731",
)

# Route pins for the lemons-world live probes. Both endpoints report their
# quantization as "unknown", which is the value OpenRouter filters on.
GEMINI_38_FLASH_MODEL = "google/gemini-3.8-flash"
GEMINI_38_FLASH_REVISION = "google/gemini-3.8-flash-20260902"
GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE = OpenRouterRoutePin(
    provider="Google AI Studio",
    quantization="unknown",
    canonical_model=GEMINI_38_FLASH_REVISION,
    input_per_million=0.75,
    cached_input_per_million=0.075,
    output_per_million=3.75,
    pricing_id="openrouter_google-ai-studio_2026-09-21_gemini-3.8-flash",
)
GROK_47_MODEL = "x-ai/grok-4.7"
GROK_47_REVISION = "x-ai/grok-4.7-20260916"
XAI_GROK_47_ROUTE = OpenRouterRoutePin(
    provider="xAI",
    quantization="unknown",
    canonical_model=GROK_47_REVISION,
    input_per_million=1.6,
    cached_input_per_million=0.4,
    output_per_million=4.8,
    pricing_id="openrouter_xai_2026-09-21_grok-4.7",
)

GLM_53_FLASH_MODEL = "z-ai/glm-5.3-flash"
GLM_53_FLASH_REVISION = "z-ai/glm-5.3-flash-20260826"
DEEPINFRA_GLM_53_FLASH_ROUTE = OpenRouterRoutePin(
    provider="DeepInfra",
    quantization="fp8",
    canonical_model=GLM_53_FLASH_REVISION,
    input_per_million=0.075,
    cached_input_per_million=0.015,
    output_per_million=0.25,
    pricing_id="openrouter_deepinfra_2026-08-31_glm-5.3-flash",
)


def _pin(
    component_id: str, kind: str, digest: str, version: str = "1.0.0"
) -> ImplementationPin:
    return ImplementationPin.from_dict(
        {
            "component_id": component_id,
            "kind": kind,
            "version": version,
            "sha256": digest,
        }
    )


def _profile(
    *,
    profile_id: str,
    provider: str,
    model: str,
    revision: str,
    prompt_id: str,
    prompt: str,
    output_schemas: Mapping[str, Mapping[str, Any]],
    pricing: TokenPricing,
    max_logical_actions: int,
    runtime: str,
    world_seed: int,
    reasoning_condition_id: str = "reasoning_low_v1",
    reasoning_effort: str | None = "low",
    request_seed_base: int | None = None,
    max_output_tokens: int | None = None,
    timeout_seconds: float | None = None,
    max_action_attempts: int | None = None,
    retryable_conditions: Sequence[str] | None = None,
    openrouter_route: OpenRouterRoutePin = DEEPINFRA_HOUSING_ROUTE,
    harness_id: str = "minimal_chat",
    harness_version: str = "1.0",
    harness_config: Mapping[str, Any] | None = None,
    sampling_top_p: float | None = 1.0,
    max_cost_usd: float | None = None,
) -> AgentProfile:
    default_max_action_attempts = (
        4
        if provider == "openrouter" and request_seed_base is not None
        else (2 if provider == "openrouter" else 1)
    )
    default_retryable_conditions = (
        ("length", "rate_limit", "provider_5xx")
        if provider == "openrouter" and request_seed_base is not None
        else (("length",) if provider == "openrouter" else ())
    )
    config: dict[str, Any] = {
        "pricing_id": pricing.pricing_id,
        "pricing_sha256": pricing.content_sha256(),
        "output_schema_by_action_schema": dict(output_schemas),
    }
    if provider == "openrouter":
        config["provider_metadata"] = openrouter_route.provider_metadata()
    if request_seed_base is not None:
        config["request_seed_source"] = "paired_cell_v1"
        config["request_seed_base"] = request_seed_base
        config["retry_backoff"] = "exponential_jitter_v1"
    if harness_config:
        config.update(harness_config)
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": profile_id,
            "model": {
                "provider": provider,
                "model": model,
                "revision": revision,
                "base_url": (
                    "https://openrouter.ai/api/v1" if provider == "openrouter" else None
                ),
            },
            "harness": {
                "id": harness_id,
                "version": harness_version,
                "config": config,
            },
            "prompt": {
                "prompt_id": prompt_id,
                "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": runtime,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": reasoning_condition_id,
                "effort": reasoning_effort,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "top_p": sampling_top_p if provider == "openrouter" else None,
                "max_output_tokens": (
                    max_output_tokens
                    if max_output_tokens is not None
                    else (512 if provider == "openrouter" else 256)
                ),
                "seed": (
                    world_seed
                    if provider == "openrouter" and request_seed_base is None
                    else None
                ),
            },
            "budgets": {
                "max_logical_actions": max_logical_actions,
                "timeout_seconds": (
                    timeout_seconds if timeout_seconds is not None else 30.0
                ),
                "max_cost_usd": (
                    max_cost_usd
                    if max_cost_usd is not None
                    else (0.01 if provider == "openrouter" else 0.001)
                ),
            },
            "retry_policy": {
                "max_action_attempts": (
                    default_max_action_attempts
                    if max_action_attempts is None
                    else max_action_attempts
                ),
                "retryable_conditions": list(
                    default_retryable_conditions
                    if retryable_conditions is None
                    else retryable_conditions
                ),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


def build_housing_smoke(
    *,
    tenant_provider: str,
    tenant_model: str,
    tenant_revision: str,
    landlord_provider: str = "housing_scripted_landlord",
    landlord_model: str = "housing_scripted_landlord_v1",
    landlord_revision: str = "1.0.0",
    world_seed: int = 41001,
    num_tenants: int = 2,
    num_listings: int = 1,
    rounds: int = 1,
    common_weight: float = 0.6,
    world_seeds: Sequence[int] | None = None,
    replicates: int = 1,
    reasoning_condition_id: str = "reasoning_low_v1",
    reasoning_effort: str | None = "low",
    inference_seed_base: int | None = None,
    openrouter_route: OpenRouterRoutePin = DEEPINFRA_HOUSING_ROUTE,
    tenant_harness: Any | None = None,
    tenant_harness_config: Mapping[str, Any] | None = None,
    landlord_harness_config: Mapping[str, Any] | None = None,
    tenant_profile_id_override: str | None = None,
    tenant_max_logical_actions_override: int | None = None,
    tenant_runtime: str | None = None,
    tenant_implementation_sha256: str | None = None,
    landlord_profile_id_override: str | None = None,
    landlord_max_logical_actions_override: int | None = None,
    landlord_inference_seed_base: int | None = None,
    landlord_openrouter_route: OpenRouterRoutePin | None = None,
    max_output_tokens_override: int | None = None,
    timeout_seconds_override: float | None = None,
    max_action_attempts_override: int | None = None,
    retryable_conditions_override: Sequence[str] | None = None,
    implementation_digest_overrides: Mapping[str, str] | None = None,
    evaluation_kind: str = "controlled",
    world_kind: str = "bid",
    lemon_share: float = lemons_module.DEFAULT_LEMON_SHARE,
    lemon_loss: float = lemons_module.DEFAULT_LEMON_LOSS,
    inspection_cost: float = lemons_module.DEFAULT_INSPECTION_COST,
    tenant_top_p: float | None = 1.0,
    tenant_max_cost_usd_override: float | None = None,
) -> HousingSmokeSetup:
    if tenant_max_cost_usd_override is not None and (
        not _finite_number(tenant_max_cost_usd_override)
        or tenant_max_cost_usd_override <= 0.0
    ):
        raise ValueError("tenant_max_cost_usd_override must be a positive number")
    if world_kind not in {"bid", "lemons"}:
        raise ValueError("world_kind must be bid or lemons")
    lemons = world_kind == "lemons"
    if tenant_provider == "housing_scripted_tenant":
        if tenant_model not in SCRIPTED_TENANT_MODELS:
            raise ValueError("unknown scripted tenant model")
        if tenant_revision != SCRIPTED_TENANT_REVISION:
            raise ValueError("unknown scripted tenant revision")
        if (SCRIPTED_TENANT_MODELS[tenant_model] is not None) != lemons:
            raise ValueError(
                "the lemons world takes a lemons scripted tenant and the bid world "
                "the legacy one"
            )
    selected_world_seeds = (world_seed,) if world_seeds is None else tuple(world_seeds)
    if not selected_world_seeds:
        raise ValueError("world_seeds must not be empty")
    if len(set(selected_world_seeds)) != len(selected_world_seeds):
        raise ValueError("world_seeds must be unique")
    if replicates < 1:
        raise ValueError("replicates must be positive")
    for field, value in (
        ("tenant_max_logical_actions_override", tenant_max_logical_actions_override),
        (
            "landlord_max_logical_actions_override",
            landlord_max_logical_actions_override,
        ),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError(f"{field} must be a positive integer")
    if evaluation_kind not in {"controlled", "cross_play", "self_play"}:
        raise ValueError("evaluation_kind must be controlled, cross_play, or self_play")
    digest_overrides = dict(implementation_digest_overrides or {})
    allowed_digest_overrides = {
        "housing",
        "bridge",
        "combined",
        "execution",
        "harness",
        "lemons",
        "combined_lemons",
    }
    if set(digest_overrides).difference(allowed_digest_overrides):
        raise ValueError("implementation_digest_overrides contains unknown components")
    if any(
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for digest in digest_overrides.values()
    ):
        raise ValueError(
            "implementation digest overrides must be 64 lowercase hexadecimal "
            "characters"
        )
    if evaluation_kind != "controlled" and landlord_provider != "openrouter":
        raise ValueError("cross_play and self_play require a model landlord profile")
    experiment_mode = world_seeds is not None
    if experiment_mode and inference_seed_base is None:
        raise ValueError("experiment plans require inference_seed_base")
    if (
        tenant_provider == "openrouter"
        and tenant_revision != openrouter_route.canonical_model
    ):
        raise ValueError("tenant_revision must match the sealed OpenRouter route model")
    resolved_landlord_route = landlord_openrouter_route or openrouter_route
    if (
        landlord_provider == "openrouter"
        and landlord_revision != resolved_landlord_route.canonical_model
    ):
        raise ValueError(
            "landlord_revision must match the sealed OpenRouter route model"
        )
    if (
        experiment_mode
        and landlord_provider == "openrouter"
        and landlord_inference_seed_base is None
    ):
        raise ValueError(
            "model-landlord experiment plans require landlord_inference_seed_base"
        )
    family = FamilyManifest.from_dict(
        {
            "spec_version": "aeread.family/0.1",
            "family": {
                "id": "housing_v1",
                "version": "1.0.0",
                "plugin_id": "aeread.housing_v1",
            },
            "environment": {
                "topology": "market_with_private_preferences",
                "phase_specs": (
                    ["inspect", "contact", "respond", "commit"]
                    if lemons
                    else ["contact", "respond", "commit"]
                ),
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "tenant": {
                    "testable": True,
                    "scripted_policies": (
                        list(LEMONS_SCRIPTED_TENANT_MODELS)
                        if lemons
                        else ["housing_scripted_tenant_v1"]
                    ),
                },
                "landlord": {
                    "testable": False,
                    "scripted_policies": ["housing_scripted_landlord_v1"],
                },
            },
            "measurement": (
                {
                    "primary_estimand": "tenant_net_payoff",
                    "measurement_kind": "optimizable_outcome",
                    "direction": "maximize",
                    "optimum_lower_bound": "housing_feasible_zero_v1",
                    "comparison_baseline": "housing_sign_anything_v1",
                    "optimum_upper_bound": "housing_exact_assignment_v1",
                    "optimum_upper_bound_kind": "full_information_relaxation",
                    "bound_status": "bracketed",
                    "outcome_support": "case_specific",
                }
                if lemons
                else {
                    "primary_estimand": "social_welfare",
                    "measurement_kind": "optimizable_outcome",
                    "direction": "maximize",
                    "optimum_lower_bound": "housing_feasible_zero_v1",
                    "comparison_baseline": "housing_naive_v1",
                    "optimum_upper_bound": "housing_exact_assignment_v1",
                    "optimum_upper_bound_kind": "full_information_relaxation",
                    "bound_status": "bracketed",
                    "outcome_support": "case_specific",
                }
            ),
            "scoring": (
                {
                    "scorer_id": "housing_lemons_outcome_v1",
                    "oracle_id": "housing_exact_assignment_v1",
                    "reference_provider_ids": [
                        "housing_feasible_zero_v1",
                        "housing_sign_anything_v1",
                        "housing_inspect_then_sign_v1",
                    ],
                }
                if lemons
                else {
                    "scorer_id": "housing_outcome_v1",
                    "oracle_id": "housing_exact_assignment_v1",
                    "reference_provider_ids": [
                        "housing_feasible_zero_v1",
                        "housing_naive_v1",
                    ],
                }
            ),
            "generator": (
                {
                    "generator_id": "housing_lemons_generator_v1",
                    "difficulty_knobs": [
                        "market_tightness",
                        "rounds",
                        "common_weight",
                        "lemon_share",
                        "lemon_loss",
                        "inspection_cost",
                    ],
                }
                if lemons
                else {
                    "generator_id": "housing_generator_v1",
                    "difficulty_knobs": ["market_tightness", "rounds", "common_weight"],
                }
            ),
        }
    )
    kind_prefix = "housing_lemons" if lemons else "housing"
    generator_id = "housing_lemons_generator_v1" if lemons else "housing_generator_v1"
    max_actions = rounds * ((3 if lemons else 2) * num_tenants + num_listings)
    cases: list[CaseManifest] = []
    for index, case_world_seed in enumerate(selected_world_seeds, start=1):
        raw_case = {
            "spec_version": "aeread.case/0.1",
            "case_id": (
                f"housing_v1__{'lemons_' if lemons else ''}smoke__000001"
                if not experiment_mode
                else f"housing_v1__{'lemons_' if lemons else ''}experiment__{index:06d}"
            ),
            "family_id": "housing_v1",
            "family_version": "1.0.0",
            "split": "smoke" if not experiment_mode else "evaluation",
            "world_seed": case_world_seed,
            "seats": [
                *[
                    {"id": f"tenant_{seat_index}", "role": "tenant"}
                    for seat_index in range(num_tenants)
                ],
                *[
                    {"id": f"landlord_{seat_index}", "role": "landlord"}
                    for seat_index in range(num_listings)
                ],
            ],
            "episode": {
                "max_logical_actions": max_actions,
                "termination": ["allocation", "deadline"],
            },
            "visibility_policy": "housing_private_preferences_v1",
            "payload": {
                "world_kind": world_kind,
                "world_seed": case_world_seed,
                "num_tenants": num_tenants,
                "num_listings": num_listings,
                "rounds": rounds,
                "common_weight": common_weight,
                **(
                    {
                        "lemon_share": float(lemon_share),
                        "lemon_loss": float(lemon_loss),
                        "inspection_cost": float(inspection_cost),
                    }
                    if lemons
                    else {}
                ),
            },
            "provenance": {
                "generator_id": generator_id,
                "generator_version": "1.0.0",
                "review_status": "curated" if not experiment_mode else "generated",
            },
            "content_sha256": "0" * 64,
        }
        raw_case["content_sha256"] = case_content_sha256(raw_case)
        cases.append(CaseManifest.from_dict(raw_case))
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": "aeread.sampling/0.1",
            "sampling_plan_id": (
                f"{kind_prefix}_smoke_sample_v1"
                if not experiment_mode
                else f"{kind_prefix}_{reasoning_condition_id}_sample_v1"
            ),
            "estimand": (
                "fixed_housing_smoke_case"
                if not experiment_mode
                else "generated_housing_case_population"
            ),
            "target": generator_id,
            "selection": (
                "fixed_curated" if not experiment_mode else "seeded_simple_random"
            ),
            "seeds": [
                (
                    selected_world_seeds[0]
                    if inference_seed_base is None
                    else inference_seed_base
                )
            ],
            "replicates": replicates,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": ["world_seed"],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel" if not experiment_mode else "sampled_panel",
        }
    )
    resolved_tenant_harness = tenant_harness or MinimalChatHarness()
    tenant_profile_id = tenant_profile_id_override or (
        (
            f"{kind_prefix}_deepseek_tenant_v1"
            if not experiment_mode
            else f"{kind_prefix}_deepseek_tenant_{reasoning_condition_id}"
        )
        if tenant_provider == "openrouter"
        else tenant_model
    )
    tenant_pricing = (
        openrouter_route.token_pricing()
        if tenant_provider == "openrouter"
        else TokenPricing(0.0, 0.0, 0.0, "housing_scripted_tenant_zero_cost_v1")
    )
    landlord_profile_id = landlord_profile_id_override or (
        "housing_model_landlord_v1"
        if landlord_provider == "openrouter"
        else "housing_scripted_landlord_v1"
    )
    landlord_pricing = (
        resolved_landlord_route.token_pricing()
        if landlord_provider == "openrouter"
        else TokenPricing(0.0, 0.0, 0.0, "housing_scripted_landlord_zero_cost_v1")
    )
    tenant_profile = _profile(
        profile_id=tenant_profile_id,
        provider=tenant_provider,
        model=tenant_model,
        revision=tenant_revision,
        prompt_id="housing_tenant_lemons_v1" if lemons else "housing_tenant_v1",
        prompt=HOUSING_TENANT_LEMONS_PROMPT if lemons else HOUSING_TENANT_PROMPT,
        output_schemas=(
            {
                "housing_inspect_v1": HOUSING_INSPECT_OUTPUT_SCHEMA,
                "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
                "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
            }
            if lemons
            else {
                "housing_contact_v1": HOUSING_CONTACT_OUTPUT_SCHEMA,
                "housing_commit_v1": HOUSING_COMMIT_OUTPUT_SCHEMA,
            }
        ),
        pricing=tenant_pricing,
        max_logical_actions=(
            (3 if lemons else 2) * num_tenants * rounds
            if tenant_max_logical_actions_override is None
            else tenant_max_logical_actions_override
        ),
        runtime=(
            tenant_runtime
            or (
                TASK_EXECUTION_COMPONENT_ID
                if tenant_provider == "openrouter"
                else HOUSING_RUNTIME_COMPONENT_ID
            )
        ),
        world_seed=selected_world_seeds[0],
        reasoning_condition_id=reasoning_condition_id,
        reasoning_effort=reasoning_effort,
        request_seed_base=inference_seed_base,
        max_output_tokens=(
            (4096 if max_output_tokens_override is None else max_output_tokens_override)
            if tenant_provider == "openrouter" and experiment_mode
            else None
        ),
        timeout_seconds=(
            (120.0 if timeout_seconds_override is None else timeout_seconds_override)
            if tenant_provider == "openrouter" and experiment_mode
            else None
        ),
        max_action_attempts=(
            max_action_attempts_override
            if tenant_provider == "openrouter" and experiment_mode
            else None
        ),
        retryable_conditions=(
            retryable_conditions_override
            if tenant_provider == "openrouter" and experiment_mode
            else None
        ),
        openrouter_route=openrouter_route,
        harness_id=resolved_tenant_harness.id,
        harness_version=resolved_tenant_harness.version,
        harness_config=tenant_harness_config,
        sampling_top_p=tenant_top_p,
        max_cost_usd=tenant_max_cost_usd_override,
    )
    landlord_profile = _profile(
        profile_id=landlord_profile_id,
        provider=landlord_provider,
        model=landlord_model,
        revision=landlord_revision,
        prompt_id="housing_landlord_v1",
        prompt=HOUSING_LANDLORD_PROMPT,
        output_schemas={"housing_respond_v1": HOUSING_RESPOND_OUTPUT_SCHEMA},
        pricing=landlord_pricing,
        max_logical_actions=(
            num_listings * rounds
            if landlord_max_logical_actions_override is None
            else landlord_max_logical_actions_override
        ),
        runtime=(
            TASK_EXECUTION_COMPONENT_ID
            if landlord_provider == "openrouter"
            else HOUSING_RUNTIME_COMPONENT_ID
        ),
        world_seed=selected_world_seeds[0],
        reasoning_condition_id=(
            "fixed_model_opponent_v1"
            if landlord_provider == "openrouter"
            else "scripted_no_reasoning_v1"
        ),
        reasoning_effort=(
            reasoning_effort if landlord_provider == "openrouter" else None
        ),
        request_seed_base=landlord_inference_seed_base,
        max_output_tokens=(
            (4096 if max_output_tokens_override is None else max_output_tokens_override)
            if landlord_provider == "openrouter" and experiment_mode
            else None
        ),
        timeout_seconds=(
            (120.0 if timeout_seconds_override is None else timeout_seconds_override)
            if landlord_provider == "openrouter" and experiment_mode
            else None
        ),
        max_action_attempts=(
            max_action_attempts_override
            if landlord_provider == "openrouter" and experiment_mode
            else None
        ),
        retryable_conditions=(
            retryable_conditions_override
            if landlord_provider == "openrouter" and experiment_mode
            else None
        ),
        openrouter_route=resolved_landlord_route,
        harness_config=landlord_harness_config,
    )
    tenant_seats = [f"tenant_{index}" for index in range(num_tenants)]
    landlord_seats = [f"landlord_{index}" for index in range(num_listings)]
    block = EvaluationBlock.from_dict(
        {
            "spec_version": "aeread.evaluation_block/0.1",
            "block_id": (
                f"{kind_prefix}_controlled_model_landlords_smoke"
                if landlord_provider == "openrouter" and not experiment_mode
                else (
                    f"{kind_prefix}_controlled_model_landlords_experiment"
                    if landlord_provider == "openrouter"
                    else (
                        f"{kind_prefix}_controlled_landlords_smoke"
                        if not experiment_mode
                        else f"{kind_prefix}_controlled_landlords_experiment"
                    )
                )
            ),
            "kind": evaluation_kind,
            "subject_seats": (
                [*tenant_seats, *landlord_seats]
                if evaluation_kind == "self_play"
                else tenant_seats
            ),
            "controlled_profiles": (
                {seat: landlord_profile_id for seat in landlord_seats}
                if evaluation_kind == "controlled"
                else {}
            ),
            "repetitions": 1,
            "seed_policy": "fixed" if not experiment_mode else "paired",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": "aeread.analysis/0.1",
            "analysis_plan_id": (
                f"{kind_prefix}_smoke_analysis_v1"
                if not experiment_mode
                else f"{kind_prefix}_reasoning_paired_analysis_v1"
            ),
            "estimands": (
                (
                    ["tenant_net_payoff", "abstention_correctness_rate", "social_welfare"]
                    if lemons
                    else ["social_welfare", "tenant_payoff", "landlord_payoff"]
                )
                if not experiment_mode
                else (
                    [
                        "within_case_score",
                        "tenant_net_payoff",
                        "abstention_correctness_rate",
                        "social_welfare",
                    ]
                    if lemons
                    else [
                        "within_case_score",
                        "social_welfare",
                        "tenant_payoff",
                        "landlord_payoff",
                    ]
                )
            ),
            "group_by": ["family_id", "subject_role"],
            "missingness": "report_separately",
            "resampling_unit": "cluster_id",
            "uncertainty": "none" if not experiment_mode else "cluster_bootstrap_95",
            "multiplicity": "none",
            "sensitivity": (
                ["report_ir_violations"]
                if not experiment_mode
                else [
                    "report_ir_violations",
                    "report_operational_missingness",
                    "worst_case_score_bounds",
                ]
            ),
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": "aeread.suite/0.1",
            "suite_id": (
                f"{kind_prefix}_smoke_v1"
                if not experiment_mode
                else f"{kind_prefix}_{reasoning_condition_id}_experiment_v1"
            ),
            "version": "1.0.0",
            "family_ids": ["housing_v1"],
            "case_ids": [case.case_id for case in cases],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    assignments = {
        **{seat: tenant_profile_id for seat in tenant_seats},
        **{seat: landlord_profile_id for seat in landlord_seats},
    }
    run_spec = RunSpec.from_dict(
        {
            "spec_version": "aeread.run_spec/0.1",
            "run_spec_id": (
                f"{kind_prefix}_smoke_run_v1"
                if not experiment_mode
                else f"{kind_prefix}_{reasoning_condition_id}_run_v1"
            ),
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [tenant_profile_id, landlord_profile_id],
            "seat_assignments": assignments,
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    plugin = HousingV1Plugin()
    registry = PluginRegistry()
    registry.register_trusted(family, plugin)
    harness_registry = HarnessRegistry()
    minimal_harness = MinimalChatHarness()
    harness_registry.register(minimal_harness)
    if (
        resolved_tenant_harness.id,
        resolved_tenant_harness.version,
    ) != (minimal_harness.id, minimal_harness.version):
        harness_registry.register(resolved_tenant_harness)
    provider_capabilities = {
        profile.model.provider: ProviderCapabilities(
            native_tools=profile.model.provider == "openrouter",
            structured_output=True,
            seed=profile.model.provider == "openrouter",
            system_prompt=True,
            reasoning_budget=profile.model.provider == "openrouter",
            reasoning_token_report=profile.model.provider == "openrouter",
            max_context_tokens=None,
        )
        for profile in (tenant_profile, landlord_profile)
    }
    housing_source = Path(hz.__file__).read_bytes()
    bridge_source = Path(__file__).read_bytes()
    execution_source = Path(execution_module.__file__).read_bytes()
    harness_source = Path(harness_module.__file__).read_bytes()
    housing_digest = digest_overrides.get(
        "housing", hashlib.sha256(housing_source).hexdigest()
    )
    bridge_digest = digest_overrides.get(
        "bridge",
        hashlib.sha256(
            bridge_source + Path(evaluation_module.__file__).read_bytes()
        ).hexdigest(),
    )
    combined_digest = digest_overrides.get(
        "combined", hashlib.sha256(housing_source + bridge_source).hexdigest()
    )
    execution_digest = digest_overrides.get(
        "execution", hashlib.sha256(execution_source).hexdigest()
    )
    harness_digest = digest_overrides.get(
        "harness", hashlib.sha256(harness_source).hexdigest()
    )
    if lemons:
        lemons_source = Path(lemons_module.__file__).read_bytes()
        lemons_digest = digest_overrides.get(
            "lemons", hashlib.sha256(lemons_source).hexdigest()
        )
        combined_lemons_digest = digest_overrides.get(
            "combined_lemons",
            hashlib.sha256(housing_source + lemons_source + bridge_source).hexdigest(),
        )
        pins = [
            _pin("aeread.housing_v1", "family_plugin", combined_lemons_digest),
            _pin("housing_lemons_outcome_v1", "scorer", combined_lemons_digest),
            _pin("housing_exact_assignment_v1", "reference", housing_digest),
            _pin("housing_feasible_zero_v1", "reference", bridge_digest),
            _pin("housing_sign_anything_v1", "reference", lemons_digest),
            _pin("housing_inspect_then_sign_v1", "reference", lemons_digest),
            _pin("housing_lemons_generator_v1", "generator", lemons_digest),
            _pin("minimal_chat", "harness", harness_digest, version="1.0"),
        ]
    else:
        pins = [
            _pin("aeread.housing_v1", "family_plugin", combined_digest),
            _pin("housing_outcome_v1", "scorer", combined_digest),
            _pin("housing_exact_assignment_v1", "reference", housing_digest),
            _pin("housing_feasible_zero_v1", "reference", bridge_digest),
            _pin("housing_naive_v1", "reference", housing_digest),
            _pin("housing_generator_v1", "generator", housing_digest),
            _pin("minimal_chat", "harness", harness_digest, version="1.0"),
        ]
    if resolved_tenant_harness.id != "minimal_chat":
        if tenant_implementation_sha256 is None:
            raise ValueError(
                "external tenant harnesses require tenant_implementation_sha256"
            )
        pins.append(
            _pin(
                resolved_tenant_harness.id,
                "harness",
                tenant_implementation_sha256,
                version=resolved_tenant_harness.version,
            )
        )
    for resolved_runtime in sorted(
        {
            tenant_profile.runtime.implementation,
            landlord_profile.runtime.implementation,
        }
    ):
        runtime_digest = (
            bridge_digest
            if resolved_runtime == HOUSING_RUNTIME_COMPONENT_ID
            else (
                execution_digest
                if resolved_runtime == TASK_EXECUTION_COMPONENT_ID
                else tenant_implementation_sha256
            )
        )
        if runtime_digest is None:
            raise ValueError(
                "external tenant runtimes require an implementation digest"
            )
        pins.append(
            _pin(
                resolved_runtime,
                "runtime",
                runtime_digest,
                version="0.1.0",
            )
        )
    plan = resolve_run_plan(
        families=(family,),
        cases=tuple(cases),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(tenant_profile, landlord_profile),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities=provider_capabilities,
    )
    return HousingSmokeSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            "housing_tenant_v1": HOUSING_TENANT_PROMPT,
            "housing_tenant_lemons_v1": HOUSING_TENANT_LEMONS_PROMPT,
            "housing_landlord_v1": HOUSING_LANDLORD_PROMPT,
        },
        pricing={
            tenant_model: tenant_pricing,
            landlord_model: landlord_pricing,
        },
        harnesses={
            f"{minimal_harness.id}/{minimal_harness.version}": minimal_harness,
            f"{resolved_tenant_harness.id}/{resolved_tenant_harness.version}": (
                resolved_tenant_harness
            ),
        },
    )


CLI_ROUTES: dict[str, OpenRouterRoutePin] = {
    "deepinfra_deepseek": DEEPINFRA_HOUSING_ROUTE,
    "google_gemini_38_flash": GOOGLE_AI_STUDIO_GEMINI_38_FLASH_ROUTE,
    "xai_grok_47": XAI_GROK_47_ROUTE,
}
CLI_ROUTE_MODELS: dict[str, str] = {
    "deepinfra_deepseek": "deepseek/deepseek-v4-flash-0731",
    "google_gemini_38_flash": GEMINI_38_FLASH_MODEL,
    "xai_grok_47": GROK_47_MODEL,
}


async def _run_cli(arguments: argparse.Namespace) -> dict[str, Any]:
    world_kind = getattr(arguments, "world_kind", "bid")
    tenant_policy = getattr(arguments, "tenant_policy", None)
    route_id = getattr(arguments, "route", "deepinfra_deepseek")
    route = CLI_ROUTES[route_id]
    if arguments.provider == "openrouter":
        tenant_provider = "openrouter"
        tenant_model = arguments.model or CLI_ROUTE_MODELS[route_id]
        tenant_revision = arguments.revision or route.canonical_model
        tenant_client = OpenRouterChatClient()
    else:
        tenant_provider = "housing_scripted_tenant"
        if world_kind == "lemons":
            tenant_model = f"housing_scripted_tenant_{tenant_policy or 'inspect_then_sign'}_v1"
        else:
            tenant_model = "housing_scripted_tenant_v1"
        tenant_revision = SCRIPTED_TENANT_REVISION
        tenant_client = HousingScriptedTenantProvider()
    setup = build_housing_smoke(
        tenant_provider=tenant_provider,
        tenant_model=tenant_model,
        tenant_revision=tenant_revision,
        world_seed=arguments.world_seed,
        num_tenants=arguments.tenants,
        num_listings=arguments.listings,
        rounds=arguments.rounds,
        world_kind=world_kind,
        lemon_share=getattr(arguments, "lemon_share", lemons_module.DEFAULT_LEMON_SHARE),
        lemon_loss=getattr(arguments, "lemon_loss", lemons_module.DEFAULT_LEMON_LOSS),
        inspection_cost=getattr(
            arguments, "inspection_cost", lemons_module.DEFAULT_INSPECTION_COST
        ),
        openrouter_route=route,
        tenant_top_p=None if route_id == "xai_grok_47" else 1.0,
    )
    execution = await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=arguments.run_root,
        prompt_sources=setup.prompt_sources,
        providers={
            tenant_provider: tenant_client,
            "housing_scripted_landlord": HousingScriptedLandlordProvider(),
        },
        pricing=setup.pricing,
        episode_attempt_ordinal=arguments.attempt,
        harnesses=setup.harnesses,
    )
    receipt = finalize_housing_execution(setup=setup, execution=execution)
    return {
        "run_plan_id": execution.run_plan_id,
        "cell_id": execution.cell_id,
        "episode_attempt_id": execution.episode_attempt_id,
        "outcome": execution.episode_result.outcome,
        "logical_action_count": execution.episode_result.logical_action_count,
        "total_cost_usd": execution.total_cost_usd,
        "evidence_dir": str(execution.evidence.root),
        "measurement_status": receipt.status,
        "receipt_sha256": receipt.receipt_sha256,
        "receipt_path": str(
            (execution.evidence.root / "evaluation_receipt.json").resolve()
        ),
        "replay_level": receipt.replay_level,
        "world_kind": world_kind,
        "tenant_model": tenant_model,
        "tenant_revision": tenant_revision,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", choices=("scripted", "openrouter"), default="scripted"
    )
    parser.add_argument("--model")
    parser.add_argument("--revision")
    parser.add_argument(
        "--world-kind", choices=("bid", "lemons"), default="bid",
        help="lemons adds hidden quality, an inspect phase and the tenant-payoff endpoint",
    )
    parser.add_argument(
        "--tenant-policy", choices=lemons_module.TENANT_POLICY_IDS, default=None,
        help="scripted lemons tenant (default inspect_then_sign); ignored for openrouter",
    )
    parser.add_argument(
        "--route", choices=sorted(CLI_ROUTES), default="deepinfra_deepseek",
        help="sealed OpenRouter endpoint for a live tenant",
    )
    parser.add_argument("--lemon-share", type=float, default=lemons_module.DEFAULT_LEMON_SHARE)
    parser.add_argument("--lemon-loss", type=float, default=lemons_module.DEFAULT_LEMON_LOSS)
    parser.add_argument(
        "--inspection-cost", type=float, default=lemons_module.DEFAULT_INSPECTION_COST
    )
    parser.add_argument("--world-seed", type=int, default=41001)
    parser.add_argument("--tenants", type=int, default=2)
    parser.add_argument("--listings", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument(
        "--run-root", "--output", dest="run_root", type=Path, required=True
    )
    arguments = parser.parse_args(argv)
    print(canonical_json_bytes(asyncio.run(_run_cli(arguments))).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HOUSING_COMMIT_OUTPUT_SCHEMA",
    "HOUSING_COMMIT_OUTPUT_SCHEMA_V2",
    "HOUSING_CONTACT_OUTPUT_SCHEMA",
    "HOUSING_CONTACT_OUTPUT_SCHEMA_V2",
    "HOUSING_RESPOND_OUTPUT_SCHEMA",
    "HOUSING_RESPOND_OUTPUT_SCHEMA_V2",
    "HousingScriptedLandlordProvider",
    "HousingScriptedTenantProvider",
    "HousingSmokeSetup",
    "HousingV1Plugin",
    "OpenRouterRoutePin",
    "DEEPINFRA_GLM_53_FLASH_ROUTE",
    "DEEPINFRA_HOUSING_ROUTE",
    "GLM_53_FLASH_MODEL",
    "GLM_53_FLASH_REVISION",
    "build_housing_smoke",
    "main",
]
