"""Typed objective-reference measurement for the controlled RFQ family."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread import exchange_procurement as procurement
from aeread import procurement_rfq_env as rfq
from .measurement import (
    EstimandSpec, ImplementationRef, MeasurementLeafSpec, MetricValue,
    ObjectiveScopeSpec, ReferenceSpec, ScoreEnvelope, ValidityDomainSpec,
    ValidityReport, VerifierSpec,
)
from .resolver import canonical_json_bytes


def procurement_source_digests() -> dict[str, str]:
    here = Path(__file__)
    substrate = Path(procurement.__file__).read_bytes()
    environment = Path(rfq.__file__).read_bytes()
    bridge = here.with_name("procurement_rfq.py").read_bytes()
    measurement = here.read_bytes()
    generator = here.parent.parent.joinpath("procurement_rfq_cases.py").read_bytes()
    finalizer = here.with_name("family_evaluation.py").read_bytes()
    return {
        "combined": hashlib.sha256(substrate + environment + bridge + measurement).hexdigest(),
        "reference": hashlib.sha256(substrate + environment).hexdigest(),
        "generator": hashlib.sha256(substrate + generator).hexdigest(),
        "runtime": hashlib.sha256(bridge + measurement + finalizer).hexdigest(),
    }


def procurement_measurement_leaf(case: Mapping[str, Any]) -> MeasurementLeafSpec:
    digests = procurement_source_digests()
    scorer = ImplementationRef("procurement_rfq_outcome_v1", "1.0.0", digests["combined"])
    domain = ValidityDomainSpec("procurement_terminal_domain_v1", "1.0.0", "procurement_rfq/outcome/1", scorer)
    units = "synthetic_currency"
    return MeasurementLeafSpec(
        leaf_id="procurement_buyer_surplus_leaf", leaf_version="1.0.0",
        estimand=EstimandSpec("buyer_surplus", "1.0.0", "terminal_state", "maximize", units, domain),
        verifier=VerifierSpec(
            verifier_family="objective_reference", evaluation_class="deterministic",
            reference=ReferenceSpec(
                reference_id="procurement_rfq_full_info_terms_v1", reference_version="1.0.0",
                reference_kind="objective_upper_bound", input_scope="terminal_state", units=units,
                source_sha256=hashlib.sha256(canonical_json_bytes({
                    "world": rfq.world_to_payload(case["world"]),
                    "max_contacts": case["max_contacts"], "contact_cost": case["contact_cost"],
                })).hexdigest(),
                implementation=ImplementationRef("procurement_rfq_full_info_terms_v1", "1.0.0", digests["reference"]),
            ),
            objective_scope=ObjectiveScopeSpec(
                objective_id="buyer_surplus", objective_version="1.0.0", direction="maximize", units=units,
                feasible_set="approved complete integer award respecting budget, capacity, MOQ, deadline and contact limit",
                information_set="evaluator-private supplier costs and full public vendor terms",
                horizon="one six-phase RFQ episode",
                environment_condition="pinned generated or curated procurement world",
                opponent_condition="controlled supplier quote and counter policy with 5 percent floor margin",
                validity_domain=domain,
            ),
        ),
        scorer=scorer,
    )


def procurement_score_support(case: Mapping[str, Any]) -> tuple[float, float]:
    """Conservative legal-outcome support, distinct from the optimum's zero floor."""
    world = case["world"]
    upper = rfq.buyer_surplus_upper_bound(world, max_contacts=case["max_contacts"], contact_cost=case["contact_cost"])
    if upper <= 0:
        raise ValueError("normalized score support requires a positive upper bound")
    lower = min(0.0, world.demand.contract_value - world.authz.budget) - case["max_contacts"] * case["contact_cost"]
    return lower / upper, 1.0


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def score_procurement_outcome(
    case: Mapping[str, Any], outcome: Mapping[str, Any], *, evidence_refs: Sequence[str] = (),
) -> ScoreEnvelope:
    leaf = procurement_measurement_leaf(case)
    reasons: list[str] = []
    if not isinstance(outcome, Mapping):
        outcome = {}
    if outcome.get("valid") is not True:
        reasons.append("family outcome is not marked valid")
    if outcome.get("bound_semantics") != "full_information_terms_relaxation":
        reasons.append("reference semantics changed")
    fields = ("buyer_surplus", "supplier_margin", "social_welfare", "spend", "production_cost", "contact_cost_total", "baseline_total", "oracle_total", "buyer_surplus_upper_bound", "disclosure_quote_uplift")
    numbers = {field: float(outcome[field]) for field in fields if _finite(outcome.get(field))}
    if len(numbers) != len(fields):
        reasons.append("economic fields are missing or non-finite")
    world = case["world"]
    expected_upper = rfq.buyer_surplus_upper_bound(world, max_contacts=case["max_contacts"], contact_cost=case["contact_cost"])
    baseline = rfq.run_scripted_rfq_baseline(world, max_contacts=case["max_contacts"], contact_cost=case["contact_cost"], disclosure_anchor=case["disclosure_anchor"])
    expected = {"oracle_total": expected_upper, "buyer_surplus_upper_bound": expected_upper, "baseline_total": baseline.buyer_surplus}
    contacts = outcome.get("contacted_supplier_ids")
    if (not isinstance(contacts, (list, tuple)) or
        any(isinstance(item, bool) or not isinstance(item, int) for item in contacts) or
        len(set(contacts)) != len(contacts) or len(contacts) > case["max_contacts"] or
        not set(contacts).issubset({s.seller_id for s in world.suppliers})):
        reasons.append("contact identities do not match the declared world and limit")
        contacts = ()
    expected["contact_cost_total"] = len(contacts) * case["contact_cost"]
    disclosed = outcome.get("disclosed_rfq_count")
    if isinstance(disclosed, bool) or not isinstance(disclosed, int) or not 0 <= disclosed <= len(contacts):
        reasons.append("disclosed RFQ count is invalid")
    for flag in ("executed", "approval_granted"):
        if not isinstance(outcome.get(flag), bool):
            reasons.append(f"{flag} must be boolean")
    violations = outcome.get("violations")
    if not isinstance(violations, (list, tuple)) or any(not isinstance(item, str) for item in violations):
        reasons.append("violations must be a sequence of strings")
    executed = outcome.get("executed") is True
    if executed and (outcome.get("approval_granted") is not True or violations):
        reasons.append("executed purchase lacks valid approval")
    if len(numbers) == len(fields):
        spend = numbers["spend"]
        production = numbers["production_cost"]
        expected["buyer_surplus"] = (world.demand.contract_value if executed else 0.0) - spend - expected["contact_cost_total"]
        expected["supplier_margin"] = spend - production
        expected["social_welfare"] = numbers["buyer_surplus"] + numbers["supplier_margin"]
        if not 0 <= spend <= world.authz.budget + 1e-8 or production < 0 or numbers["supplier_margin"] < -1e-8:
            reasons.append("purchase price, cost, or supplier margin violates the controlled market")
        if not executed and (spend != 0 or production != 0):
            reasons.append("non-executed award cannot incur purchase or production spend")
        if numbers["disclosure_quote_uplift"] < 0:
            reasons.append("disclosure uplift cannot be negative")
        lower = min(0.0, world.demand.contract_value - world.authz.budget) - case["max_contacts"] * case["contact_cost"]
        if not lower - 1e-8 <= numbers["buyer_surplus"] <= expected_upper + 1e-8:
            reasons.append("buyer surplus is outside legal reference support")
        for ratio_field in ("within_case_score", "buyer_surplus_score"):
            ratio = outcome.get(ratio_field)
            if expected_upper > 0:
                if not _finite(ratio) or not math.isclose(ratio, numbers["buyer_surplus"] / expected_upper, rel_tol=1e-9, abs_tol=1e-9):
                    reasons.append(f"{ratio_field} does not match native surplus over the reference")
            elif ratio is not None:
                reasons.append("normalized score must be null for zero reference headroom")
    for field, value in expected.items():
        if field in numbers and not math.isclose(numbers[field], value, rel_tol=1e-9, abs_tol=1e-8):
            reasons.append(f"{field} does not reconcile")
    if reasons:
        return ScoreEnvelope("invalid_measurement", leaf, None, {}, {}, ValidityReport("invalid", tuple(reasons)), tuple(evidence_refs))
    units = leaf.estimand.units
    metrics = {field: MetricValue(numbers[field], units) for field in fields}
    metrics["comparison_baseline_gap"] = MetricValue(numbers["buyer_surplus"] - baseline.buyer_surplus, units)
    metrics["upper_bound_gap"] = MetricValue(expected_upper - numbers["buyer_surplus"], units)
    metrics["disclosed_rfq_count"] = MetricValue(disclosed, "count")
    if expected_upper > 0:
        metrics["within_case_score"] = MetricValue(numbers["buyer_surplus"] / expected_upper, "ratio")
    references = {
        "optimum_lower_bound": MetricValue(0.0, units, {"policy": "no_action"}),
        "comparison_baseline": MetricValue(baseline.buyer_surplus, units, {"policy": "visible_terms_v1"}),
        "optimum_upper_bound": MetricValue(expected_upper, units, {"semantics": "full_information_terms_relaxation"}),
    }
    buyer = {"buyer_0": metrics["buyer_surplus"]}
    return ScoreEnvelope("ok", leaf, metrics["buyer_surplus"], metrics, references, ValidityReport("valid"), tuple(evidence_refs), buyer, buyer)
