"""Four-seat, controlled shared runner for the Refund V2.5 panel."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.quality import FamilyContribution, HumanQCApproval, QCCoverage, QCEvidenceRef, ResourceLimits
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities, family_contribution_sha256
from aeread.shared_runner.run.resolver import ImplementationPin, RunPlan, case_content_sha256, canonical_json_bytes, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, AnalysisPlan, CaseManifest, EvaluationBlock, FamilyManifest, RunSpec, SamplingPlan, SuiteManifest
from aeread.shared_runner.task.evaluation import finalize_family_execution, replay_family_receipt
from aeread.shared_runner.task.execution import ArenaChatClient, ProviderFailure, ProviderRequest, ProviderResult, TokenPricing, execute_plan_cell
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult

from . import v2_5_measurement as measurement
from .v2_4_cases import MarketplaceV24Case
from .v2_5_policy import FAMILY_VERSION, SCENARIO_CATEGORY, UnifiedRefundCase, build_unified_panel, intake_routing_plan, payment_ledger, policy_fact_dependency_graph, policy_requestable_fact_ids, policy_required_fact_ids, render_policy_contract, resolve_policy, validate_catalog
from .v2_5_branches import BranchSpec, DESIGN_VERSION, public_inputs, spec_for
from .v2_5_policy import validate_case_domains, validate_resolution_invariants

ROOT = Path(__file__).resolve().parents[3]
# Source checkouts and wheels keep data at different roots.
import aeread as _aeread_package
QC_ROOT = ROOT / "cases" / "refund_v25"
if not QC_ROOT.is_dir():
    QC_ROOT = Path(_aeread_package.__file__).parent / "cases" / "refund_v25"
FAMILY_ID = "refund_v2"
ROLES = ("customer", "intake", "policy", "payments")
_RESOLUTION_FIELDS = (
    "eligibility", "remedy", "workflow", "amount", "refund_method",
    "payment_mutation", "return_shipping_payer", "policy_basis", "reason_code",
)
_SEMANTIC_FIELDS = (
    ("eligibility", "policy_eligibility_boundary_error"),
    ("remedy", "policy_remedy_selection_error"),
    ("amount", "policy_amount_calculation_error"),
    ("return_shipping_payer", "policy_liability_assignment_error"),
)
_CANONICAL_VALUES = {
    "eligibility": {"eligible", "ineligible", "unresolved"},
    "remedy": {"full_refund", "partial_refund", "none"},
    "workflow": {"execute_refund", "no_mutation", "request_evidence", "identity_review", "seller_review", "payment_review", "return_and_inspect"},
    "payment_mutation": {"execute", "none"},
    "return_shipping_payer": {"seller", "customer", "none"},
    "refund_method": {"original_payment", "none"},
}
# Exact V2.4 spelling aliases only; these never rewrite the raw candidate.
_SCORING_ALIASES = {
    "eligibility": {"not_eligible": "ineligible", "requires_clarification": "unresolved"},
    "remedy": {"refund": "full_refund", "deny_refund": "none", "issue_clarification": "none"},
    "workflow": {
        "refund": "execute_refund", "approve_refund": "execute_refund",
        "deny": "no_mutation", "deny_refund": "no_mutation",
        "clarify_issue": "request_issue_clarification",
    },
    "payment_mutation": {"refund": "execute", "no_refund": "none"},
    "return_shipping_payer": {"buyer": "customer", "not_applicable": "none"},
}


def _scoring_value(field: str, value: Any) -> Any:
    return _SCORING_ALIASES.get(field, {}).get(value, value) if isinstance(value, str) else value


def _valid_amount(value: Any) -> bool:
    try:
        return type(value) in (int, float) and value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


PROMPTS = {
    "customer": "You are the customer. Always return JSON, never prose or markdown. Use only the fields decision, message, revealed_fact_ids, fact_values, proposal_id. In customer_claim, copy the public_claim exactly into message and reveal nothing. In customer_disclosure, copy exactly the requested fact IDs into revealed_fact_ids and fact_values, with each original value copied exactly (including type); do not disclose any other private fact. In customer_confirmation, copy only the current proposal_id. Never infer policy or invent facts.",
    "intake": "You are intake. Select a minimal, relevant batch of up to three unrevealed fact IDs using the public routing objective. You never see private values or the policy oracle. Do not request convenience metadata, repeat a fact, or collect amount facts before an eligibility/risk/evidence branch is resolved. Use a top-level decision string; do not wrap it in another object. Return one JSON object.",
    "policy": "You are policy. Use only the public claim, complete rendered policy contract, and revealed facts. Apply the public rule catalogue and fact-dependency graph: request relevant unrevealed facts, or submit a canonical resolution once the applicable branch is decided. A terminal higher-precedence route may be submitted without collecting lower-priority facts. The top-level field decision must be exactly request_facts or submit_resolution. For request_facts emit a non-empty requested_fact_ids array. For submit_resolution emit requested_fact_ids: [] plus every field: eligibility, remedy, workflow, amount (calculate from the applicable public Amount formula; use 0 for a hold/review or no-refund route), refund_method (use original_payment for any positive refund, otherwise none), payment_mutation, return_shipping_payer, policy_basis, reason_code, and proposal_id. policy_basis and reason_code must both equal the selected public Rule catalogue ID. Return one JSON object.",
    "payments": "You are payments. You receive one confirmed, immutable execution ticket only. Echo proposal_id, idempotency_key, ledger_snapshot_id, amount, refund_method, and refund_allocations. When the ticket gives exact allocations, copy them. For proportional_original_tender, calculate allocations from amount and original_tender_shares, round non-final tenders to cents, and assign remaining cents to the final tender. For waterfall_remaining_capacity, allocate through tender_capacities in listed order without exceeding each capacity. For residual_after_settled_refunds, calculate requested_amount - settled_refund_amount yourself; if the residual is zero, select no_mutation with amount 0, refund_method none, and no allocations; otherwise allocate only the positive residual to original_tender. For original_rail_then_allowed_fallback, use original_rail when open and allowed_fallback_rail only when primary_rail_closed. Execute iff the ticket says kind=execute. If kind is withheld, derive the safe action from the visible ledger state. If ledger state is idempotency_key_already_applied, select no_mutation with amount 0 and no allocations even if the confirmed proposal originally approved a refund. Never create a duplicate mutation or execute while the ticket is a hold/review. Use a top-level decision string; do not wrap it in another object. Return one JSON object.",
}
PROMPT_IDS = {role: f"refund_v25_{role}_prompt" for role in ROLES}
SCHEMAS = {
    "customer": {"type": "object", "properties": {"decision": {"enum": ["state_claim", "disclose_facts", "confirm_resolution"]}, "message": {"type": "string"}, "revealed_fact_ids": {"type": "array", "items": {"type": "string"}}, "fact_values": {"type": "object"}, "proposal_id": {"type": ["string", "null"]}}, "required": ["decision", "message", "revealed_fact_ids"], "additionalProperties": False},
    "intake": {"type": "object", "properties": {"decision": {"enum": ["request_facts"]}, "requested_fact_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["decision", "requested_fact_ids"], "additionalProperties": False},
    "policy": {"type": "object", "properties": {"decision": {"enum": ["request_facts", "submit_resolution"]}, "action": {"type": "object"}, "requested_fact_ids": {"type": "array", "items": {"type": "string"}}, "eligibility": {"type": "string"}, "remedy": {"type": "string"}, "workflow": {"type": "string"}, "amount": {"type": "number"}, "refund_method": {"type": ["string", "null"]}, "payment_mutation": {"type": "string"}, "return_shipping_payer": {"type": "string"}, "policy_basis": {"type": "string"}, "reason_code": {"type": "string"}, "proposal_id": {"type": ["string", "null"]}}, "required": [], "additionalProperties": False},
    "payments": {"type": "object", "properties": {"decision": {"enum": ["execute_refund", "no_mutation"]}, "proposal_id": {"type": ["string", "null"]}, "idempotency_key": {"type": ["string", "null"]}, "ledger_snapshot_id": {"type": ["string", "null"]}, "amount": {"type": "number"}, "refund_method": {"type": ["string", "null"]}, "refund_allocations": {"type": "array", "items": {"type": "object", "properties": {"instrument": {"type": "string"}, "amount": {"type": "number"}}, "required": ["instrument", "amount"], "additionalProperties": False}}}, "required": ["decision", "proposal_id", "idempotency_key", "ledger_snapshot_id", "amount", "refund_method", "refund_allocations"], "additionalProperties": False},
}

_SCRIPTED_INTAKE_ORDER = {
    "identity": ("inspection_stage", "order_serial", "inspection_serial", "defect_evidence", "identity_risk"),
    "payment_state": ("prior_refund_state", "chargeback_state"),
    "evidence": ("sku_evidence_status", "ordered_sku", "received_sku", "customer_photo_status", "customer_evidence", "warehouse_inspection", "listing_snapshot", "defect_evidence", "spoilage_evidence", "original_defect_evidence", "inspection_cause"),
    "eligibility": ("return_request_day", "return_reason", "seller_fault_event", "category_final_sale"),
    "verification": ("defect_evidence", "evidence_status", "component_role", "core_component_missing", "paid_component_allocation", "inspection_cause"),
}


def _scripted_intake_batch(observation: Mapping[str, Any]) -> list[str]:
    """Reference intake uses routing class plus visible IDs, never values."""
    scenario = str(observation["routing_plan"]["interaction_id"])
    available = set(observation["available_fact_ids"])
    disclosed = set(observation["disclosed_fact_ids"])
    preferred = [fact for fact in spec_for(scenario).intake_order if fact in available and fact not in disclosed]
    return preferred[:3]


def _ticket_amount(ticket: Mapping[str, Any]) -> float:
    if ticket.get("allocation_rule") == "residual_after_settled_refunds":
        return round(max(0.0, float(ticket["requested_amount"]) - float(ticket["settled_refund_amount"])), 2)
    return round(float(ticket.get("amount", 0.0)), 2)


def _ticket_allocations(ticket: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Derive payment allocations from the visible ledger constraints."""
    amount = _ticket_amount(ticket)
    if ticket.get("allocation_rule") == "waterfall_remaining_capacity":
        remaining = amount; rows = []
        for tender in ticket["tender_capacities"]:
            allocated = round(min(remaining, float(tender["remaining_capacity"])), 2)
            rows.append({"instrument": tender["instrument"], "amount": allocated})
            remaining = round(remaining - allocated, 2)
        return rows
    if ticket.get("allocation_rule") == "original_rail_then_allowed_fallback":
        instrument = ticket["allowed_fallback_rail"] if ticket["state"] == "primary_rail_closed" else ticket["original_rail"]
        return [{"instrument": instrument, "amount": amount}]
    if ticket.get("allocation_rule") == "residual_after_settled_refunds":
        return [{"instrument": ticket["original_tender"], "amount": amount}] if amount else []
    if ticket.get("allocation_rule") != "proportional_original_tender":
        return list(ticket.get("refund_allocations", ()))
    shares = list(ticket.get("original_tender_shares", ()))
    if not shares:
        return []
    rows = []
    remaining = amount
    for row in shares[:-1]:
        allocated = round(amount * float(row["share"]), 2)
        rows.append({"instrument": row["instrument"], "amount": allocated})
        remaining = round(remaining - allocated, 2)
    rows.append({"instrument": shares[-1]["instrument"], "amount": remaining})
    return rows


def _json(response: Any) -> Mapping[str, Any] | None:
    try:
        value = json.loads(getattr(response, "text", response))
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _load_env_file(path: Path | None) -> None:
    """Load simple KEY=VALUE entries without printing or overriding env vars."""
    if path is None:
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _case(payload: Mapping[str, Any]) -> UnifiedRefundCase:
    value = payload.get("case")
    if not isinstance(value, Mapping) or not isinstance(value.get("interaction"), Mapping):
        raise ValueError("V2.5 payload lacks unified case")
    return UnifiedRefundCase(MarketplaceV24Case(**dict(value["interaction"])), str(value["product_category"]))


def _required(case: UnifiedRefundCase) -> tuple[str, ...]:
    return spec_for(case.interaction.scenario).fact_ids()


def _same_fact_value(candidate: Any, reference: Any) -> bool:
    """Compare disclosed JSON facts without Python's bool/int equivalence."""
    return type(candidate) is type(reference) and candidate == reference


def _collaboration_measurements(case: UnifiedRefundCase, terminal: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float], dict[str, tuple[str, ...]], dict[str, int]]:
    """Score the four cross-seat integrity measures with explicit opportunities."""
    names = measurement.COLLABORATION_DIMENSIONS
    observations: dict[str, list[float]] = {name: [] for name in names}
    tags: dict[str, set[str]] = {name: set() for name in names}
    events = tuple(event for event in terminal.get("events", ()) if isinstance(event, Mapping))
    determinative = set(_required(case))
    priority = tuple(fact for fact in spec_for(case.interaction.scenario).intake_order if fact in case.facts)

    def candidate(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
        raw = event.get("action") if event.get("valid") else event.get("action_candidate")
        return raw if isinstance(raw, Mapping) else None

    for event in events:
        phase = event.get("phase")
        action = candidate(event)
        if phase == "intake_request":
            requested = action.get("requested_fact_ids") if action else None
            request_ids = list(requested) if isinstance(requested, (list, tuple)) and all(isinstance(x, str) for x in requested) else []
            relevant = sum(fact in determinative for fact in request_ids)
            precision = relevant / len(request_ids) if request_ids else 0.0
            first_rank = priority.index(request_ids[0]) if request_ids and request_ids[0] in priority else len(priority)
            priority_score = 1.0 / (first_rank + 1) if first_rank < len(priority) else 0.0
            shape_ok = bool(request_ids) and len(request_ids) <= 3 and len(set(request_ids)) == len(request_ids)
            value = 0.35 * precision + 0.45 * priority_score + 0.20 * float(shape_ok)
            observations["intake_fact_request_quality"].append(value)
            if value < 1.0:
                tags["intake_fact_request_quality"].add("intake_request_quality_error")
        elif phase == "customer_disclosure":
            requested = set(event.get("requested_fact_ids", ()))
            ids = set(action.get("revealed_fact_ids", ())) if action else set()
            values = action.get("fact_values") if action else None
            exact_values = isinstance(values, Mapping) and set(values) == requested and all(_same_fact_value(values.get(fact), case.facts.get(fact)) for fact in requested)
            ok = bool(action and event.get("valid") and action.get("action") == "disclose_facts" and ids == requested and exact_values)
            observations["customer_disclosure_integrity"].append(float(ok))
            if not ok:
                tags["customer_disclosure_integrity"].add("customer_disclosure_integrity_error")
        elif phase == "customer_confirmation":
            expected_id = event.get("expected_proposal_id")
            ok = bool(action and event.get("valid") and action.get("action") == "confirm_resolution" and action.get("proposal_id") == expected_id and not action.get("revealed_fact_ids", ()))
            observations["customer_confirmation_integrity"].append(float(ok))
            if not ok:
                tags["customer_confirmation_integrity"].add("customer_confirmation_integrity_error")

    payment_events = [event for event in events if event.get("phase") == "payments_execute"]
    ticket = terminal.get("execution_ticket")
    transactions = terminal.get("transactions", ())
    for event in payment_events:
        action = candidate(event)
        execute = isinstance(ticket, Mapping) and ticket.get("kind") == "execute"
        expected_action = "execute_refund" if execute else "no_mutation"
        exact = bool(action and isinstance(ticket, Mapping) and event.get("valid"))
        if exact:
            expected_allocations = tuple(ticket.get("refund_allocations", ()))
            actual_allocations = tuple(action.get("refund_allocations", ()))
            exact = (
                action.get("action") == expected_action
                and action.get("proposal_id") == ticket.get("proposal_id")
                and action.get("idempotency_key") == ticket.get("idempotency_key")
                and action.get("ledger_snapshot_id") == ticket.get("ledger_snapshot_id")
                and round(float(action.get("amount", -1)), 2) == round(float(ticket.get("amount", 0)), 2)
                and (action.get("refund_method") or "none") == ticket.get("refund_method")
                and actual_allocations == expected_allocations
                and len(transactions) == (1 if execute else 0)
            )
        observations["payment_proposal_binding"].append(float(exact))
        if not exact:
            tags["payment_proposal_binding"].add("payment_proposal_binding_error")

    values: dict[str, float] = {}
    coverage: dict[str, float] = {}
    opportunities: dict[str, int] = {}
    for name in names:
        rows = observations[name]
        opportunities[name] = len(rows)
        coverage[name] = 1.0 if rows else 0.0
        values[name] = sum(rows) / len(rows) if rows else 0.0
    return values, coverage, {name: tuple(sorted(value)) for name, value in tags.items()}, opportunities


def admit_panel(cases: tuple[UnifiedRefundCase, ...], *, include_operational_extension: bool = False, include_policy_stress_extension: bool = False, include_policy_frontier_extension: bool = False, include_policy_frontier_hard_extension: bool = False) -> None:
    """Provider-free admission for the complete V2.5 fixed panel."""
    validate_catalog(cases[0].interaction.world_seed if cases else 1, include_operational_extension=include_operational_extension, include_policy_stress_extension=include_policy_stress_extension, include_policy_frontier_extension=include_policy_frontier_extension, include_policy_frontier_hard_extension=include_policy_frontier_hard_extension)
    # Counterfactual pairs are local to a world seed.  Multiple seeds reuse
    # the same pair_id by design, so grouping by pair_id alone incorrectly
    # turns a two-case pair into a six-case group in a three-seed run.
    pairs: dict[tuple[int, str], list[UnifiedRefundCase]] = {}
    for case in cases:
        validate_case_domains(case)
        missing = set(spec_for(case.interaction.scenario).fact_ids()) - set(case.facts)
        if missing:
            raise ValueError(f"{case.case_id}: required facts unavailable: {sorted(missing)}")
        expected = resolve_policy(case)
        validate_resolution_invariants(case, expected)
        contract = render_policy_contract(case)
        if not set(expected.required_fact_ids) <= set(case.facts):
            raise ValueError(f"{case.case_id}: required facts unavailable")
        for marker in ("Category base rule:", "Interaction rule for this case:", "Precedence", "Canonical outputs:", "Amount formula:", "Rule catalogue:", "Fact dependency graph:"):
            if marker.lower() not in contract.lower():
                raise ValueError(f"{case.case_id}: incomplete rendered contract: {marker}")
        graph = policy_fact_dependency_graph(case)
        if expected.policy_basis not in contract or expected.workflow not in contract:
            raise ValueError(f"{case.case_id}: rendered contract cannot express the reference branch")
        specification = spec_for(case.interaction.scenario)
        compiled = specification.resolve(case.facts, public_inputs(case.interaction.item_net_price, case.interaction.allocated_tax))
        independent = {field: getattr(expected, field) for field in _RESOLUTION_FIELDS if field != "reason_code"}
        independent["reason_code"] = expected.policy_basis
        if compiled != independent:
            raise ValueError(f"{case.case_id}: public branch specification disagrees with independent reference")
        missing_graph_facts = [fact for fact in specification.fact_ids() if fact not in graph or fact not in case.facts]
        if missing_graph_facts:
            raise ValueError(f"{case.case_id}: required facts absent from dependency graph: {missing_graph_facts}")
        if case.interaction.pair_id.startswith("hard_"):
            missing_changed = [fact for fact in case.interaction.changed_fact_ids if fact not in graph]
            if missing_changed:
                raise ValueError(f"{case.case_id}: changed facts absent from dependency graph: {missing_changed}")
        pairs.setdefault((case.interaction.world_seed, case.interaction.pair_id), []).append(case)
    for (world_seed, pair_id), pair in pairs.items():
        if len(pair) != 2:
            raise ValueError(f"{pair_id}: counterfactual pair must contain two cases")
        left, right = pair
        actual = {key for key in set(left.facts) | set(right.facts) if left.facts.get(key) != right.facts.get(key)}
        declared = set(left.interaction.changed_fact_ids) | set(right.interaction.changed_fact_ids)
        if actual != declared:
            raise ValueError(f"{pair_id}: changed facts {actual} do not match declaration {declared}")
        if left.interaction.public_claim != right.interaction.public_claim:
            raise ValueError(f"{pair_id}: counterfactual pair changes public claim")
        if left.product_category != right.product_category or left.interaction.policy_summary != right.interaction.policy_summary:
            raise ValueError(f"{pair_id}: counterfactual pair changes public policy context")
        if render_policy_contract(left) != render_policy_contract(right):
            raise ValueError(f"{pair_id}: counterfactual pair changes rendered policy contract")
        def reference_signature(item: UnifiedRefundCase) -> tuple[object, ...]:
            resolution = resolve_policy(item)
            ledger = payment_ledger(item, resolution.amount)
            return asdict(resolution), ledger.get("state"), tuple(ledger.get("refund_allocations", ()))
        if reference_signature(left) == reference_signature(right):
            raise ValueError(f"{pair_id}: counterfactual outcome did not change")
        if pair_id.startswith("hard_"):
            left_resolution, right_resolution = resolve_policy(left), resolve_policy(right)
            policy_fields = ("eligibility", "remedy", "workflow", "amount", "return_shipping_payer", "policy_basis")
            if all(getattr(left_resolution, field) == getattr(right_resolution, field) for field in policy_fields):
                raise ValueError(f"{pair_id}: counterfactual pair does not change policy compliance")


class RefundV25Plugin:
    def validate_payload(self, payload: Mapping[str, Any]) -> UnifiedRefundCase:
        return _case(payload)

    def initial_state(self, case: UnifiedRefundCase, run: Any) -> dict[str, Any]:
        del case, run
        return {"revealed_facts": {}, "pending_requested": [], "proposal": None, "policy_candidate": None, "confirmed_proposal_id": None, "execution_ticket": None, "transactions": [], "events": [], "failures": [], "done": False}

    def phases(self, case: UnifiedRefundCase) -> tuple[PhaseSpec, ...]:
        del case
        observations = {role: "refund_v25_observation" for role in ROLES}
        schemas = {role: f"refund_v25_{role}_action" for role in ROLES}
        return (
            PhaseSpec("customer_claim", "customer_only", "single", observations, schemas, 2, "family_defined", ("intake_request",)),
            PhaseSpec("intake_request", "intake_only", "single", observations, schemas, 3, "family_defined", ("customer_disclosure",)),
            PhaseSpec("customer_disclosure", "customer_only", "single", observations, schemas, 3, "family_defined", ("policy_turn",)),
            PhaseSpec("policy_turn", "policy_only", "single", observations, schemas, 10, "family_defined", ("customer_disclosure", "customer_confirmation")),
            PhaseSpec("customer_confirmation", "customer_only", "single", observations, schemas, 2, "family_defined", ("payments_execute",)),
            PhaseSpec("payments_execute", "payments_only", "single", observations, schemas, 2, "family_defined", ()),
        )

    def eligible_actors(self, case: UnifiedRefundCase, state: Mapping[str, Any], phase: PhaseSpec) -> tuple[str, ...]:
        del case, state
        return {"customer_claim": ("customer",), "intake_request": ("intake",), "customer_disclosure": ("customer",), "policy_turn": ("policy",), "customer_confirmation": ("customer",), "payments_execute": ("payments",)}[phase.phase_id]

    @staticmethod
    def _intake_priority_ok(case: UnifiedRefundCase, fields: list[str]) -> bool:
        """The first intake batch must open the documented risk/evidence branch."""
        priority = set(spec_for(case.interaction.scenario).intake_order)
        return bool(priority.intersection(fields))

    def observe(self, case: UnifiedRefundCase, state: Mapping[str, Any], seat: str, phase: PhaseSpec) -> Mapping[str, Any]:
        if seat == "customer":
            return {"phase_id": phase.phase_id, "public_claim": case.interaction.public_claim, "private_facts": dict(case.facts), "requested_fact_ids": list(state["pending_requested"]), "pending_proposal": state["proposal"] if phase.phase_id == "customer_confirmation" else None}
        if seat == "intake":
            return {"phase_id": phase.phase_id, "public_claim": case.interaction.public_claim, "available_fact_ids": sorted(case.facts), "disclosed_fact_ids": sorted(state["revealed_facts"]), "routing_plan": intake_routing_plan(case)}
        if seat == "policy":
            return {"phase_id": phase.phase_id, "public_claim": case.interaction.public_claim, "policy_contract": render_policy_contract(case), "revealed_facts": dict(state["revealed_facts"])}
        ticket = state["execution_ticket"] if state["confirmed_proposal_id"] else None
        if isinstance(ticket, Mapping) and ticket.get("allocation_rule") in {"proportional_original_tender", "waterfall_remaining_capacity", "original_rail_then_allowed_fallback", "residual_after_settled_refunds"}:
            # The evaluator keeps the exact result private; payments receives
            # enough ledger state to calculate it, but cannot simply echo it.
            ticket = {key: value for key, value in ticket.items() if key != "refund_allocations"}
        if isinstance(ticket, Mapping) and ticket.get("allocation_rule") == "residual_after_settled_refunds":
            ticket = {
                key: value for key, value in ticket.items()
                if key not in {"amount", "executable_amount", "kind"}
            }
        if isinstance(ticket, Mapping) and ticket.get("state") == "idempotency_key_already_applied":
            # This extension deliberately withholds the evaluator's execution
            # decision.  Payments must infer a safe no-op from ledger state.
            ticket = {key: value for key, value in ticket.items() if key != "kind"}
        return {"phase_id": phase.phase_id, "execution_ticket": ticket}

    def parse_action(self, case: UnifiedRefundCase, state: Mapping[str, Any], seat: str, phase: PhaseSpec, response: Any) -> ParseResult:
        del case, state, phase
        action = _json(response)
        if action is None:
            return ParseResult.failure("malformed_json")
        # Gemini occasionally emits the pre-V2.5 envelope, with the actual
        # decision nested under `action` while keeping requested_fact_ids at
        # the top level. Accept that transport shape, then score only the
        # normalized canonical action below.
        nested = action.get("action")
        if isinstance(nested, Mapping):
            normalized_envelope = dict(nested)
            normalized_envelope.update({key: value for key, value in action.items() if key != "action"})
            action = normalized_envelope
        action_name = action.get("decision", action.get("action"))
        valid = (
            seat == "customer" and isinstance(action_name, str) and action_name in {"state_claim", "disclose_facts", "confirm_resolution"} and isinstance(action.get("revealed_fact_ids"), list) and (action_name != "disclose_facts" or isinstance(action.get("fact_values"), Mapping))
        ) or (seat == "intake" and isinstance(action_name, str) and action_name == "request_facts" and isinstance(action.get("requested_fact_ids"), list)
        ) or (seat == "policy" and isinstance(action_name, str) and action_name in {"request_facts", "submit_resolution"} and isinstance(action.get("requested_fact_ids"), list)
        ) or (seat == "payments" and isinstance(action_name, str) and action_name in {"execute_refund", "no_mutation"})
        if not valid:
            return ParseResult.failure("invalid_action")
        normalized = dict(action)
        normalized["action"] = action_name
        for field in ("requested_fact_ids", "revealed_fact_ids"):
            if field in normalized and (not isinstance(normalized[field], list) or not all(isinstance(item, str) for item in normalized[field])):
                return ParseResult.failure("invalid_fact_ids")
        return ParseResult.success(normalized)

    def legal(self, case: UnifiedRefundCase, state: Mapping[str, Any], seat: str, phase: PhaseSpec, action: Mapping[str, Any]) -> LegalityResult:
        required, revealed = set(_required(case)), set(state["revealed_facts"])
        if phase.phase_id == "customer_claim":
            if action.get("action") != "state_claim":
                return LegalityResult.illegal("customer_claim_required")
            if action.get("message") != case.interaction.public_claim:
                return LegalityResult.illegal("customer_claim_mismatch")
            if action.get("revealed_fact_ids") or action.get("fact_values"):
                return LegalityResult.illegal("customer_unsolicited_disclosure")
        if phase.phase_id == "customer_disclosure":
            fields = set(action.get("revealed_fact_ids", ()))
            requested = set(state["pending_requested"])
            values = action.get("fact_values")
            exact_values = isinstance(values, Mapping) and set(values) == requested and all(_same_fact_value(values.get(field), case.facts.get(field)) for field in requested)
            if action.get("action") != "disclose_facts" or not fields or fields != requested or not exact_values:
                return LegalityResult.illegal("customer_disclosure_mismatch")
        if phase.phase_id == "intake_request" or (phase.phase_id == "policy_turn" and action.get("action") == "request_facts"):
            fields = list(action.get("requested_fact_ids", ()))
            if not fields or len(fields) > 3 or len(set(fields)) != len(fields):
                return LegalityResult.illegal("invalid_fact_request_batch")
            allowed = set(policy_requestable_fact_ids(case, state["revealed_facts"])) if phase.phase_id == "policy_turn" else required - revealed
            if not set(fields) <= allowed:
                if phase.phase_id == "policy_turn" and not allowed:
                    return LegalityResult.illegal("policy_overcollection_after_terminal_route")
                return LegalityResult.illegal("irrelevant_or_repeated_fact_request")
            if phase.phase_id == "intake_request" and not self._intake_priority_ok(case, fields):
                return LegalityResult.illegal("intake_wrong_branch_request")
        if phase.phase_id == "policy_turn" and action.get("action") == "submit_resolution":
            if policy_required_fact_ids(case, state["revealed_facts"]):
                return LegalityResult.illegal("decision_before_required_facts")
            if action.get("requested_fact_ids"):
                return LegalityResult.illegal("final_decision_requested_facts")
            output = set(_RESOLUTION_FIELDS)
            if not output <= set(action):
                return LegalityResult.illegal("incomplete_resolution")
            if not _valid_amount(action["amount"]):
                return LegalityResult.illegal("invalid_resolution_amount")
            if action["payment_mutation"] == "execute" and (round(float(action["amount"]), 2) == 0 or action["workflow"] != "execute_refund"):
                return LegalityResult.illegal("unsafe_policy_payment_mutation")
        if phase.phase_id == "customer_confirmation":
            proposal = state["proposal"]
            if action.get("action") != "confirm_resolution" or proposal is None or action.get("proposal_id") != proposal["proposal_id"] or action.get("revealed_fact_ids") or action.get("fact_values"):
                return LegalityResult.illegal("customer_confirmation_mismatch")
        if phase.phase_id == "payments_execute":
            proposal = state["proposal"]
            ticket = state.get("execution_ticket")
            if proposal is None or state["confirmed_proposal_id"] != proposal["proposal_id"]:
                return LegalityResult.illegal("payments_unconfirmed_proposal")
            if not isinstance(ticket, Mapping):
                return LegalityResult.illegal("payments_missing_execution_ticket")
            if not _valid_amount(action.get("amount")):
                return LegalityResult.illegal("payment_proposal_binding_mismatch")
            expected_action = "execute_refund" if ticket["kind"] == "execute" else "no_mutation"
            if action.get("action") != expected_action or action.get("proposal_id") != proposal["proposal_id"] or action.get("idempotency_key") != ticket["idempotency_key"] or action.get("ledger_snapshot_id") != ticket["ledger_snapshot_id"] or round(float(action.get("amount", -1)), 2) != ticket["amount"] or (action.get("refund_method") or "none") != ticket["refund_method"] or tuple(action.get("refund_allocations", ())) != tuple(ticket["refund_allocations"]):
                return LegalityResult.illegal("payment_proposal_binding_mismatch")
            if (ticket["amount"] > 0) != (ticket["kind"] == "execute") or (ticket["kind"] == "no_op" and ticket["refund_allocations"]):
                return LegalityResult.illegal("invalid_payment_mutation")
        return LegalityResult.legal_action()

    def step(self, case: UnifiedRefundCase, state: Mapping[str, Any], phase: PhaseSpec, actions: Mapping[str, Any]) -> TransitionResult:
        envelope = next(iter(actions.values()))
        next_state = {key: value for key, value in state.items()}
        if phase.phase_id == "policy_turn" and envelope.parse.ok and isinstance(envelope.parse.action, Mapping):
            # Keep the candidate for independent semantic scoring even when
            # the strict transition guard rejects it.
            next_state["policy_candidate"] = dict(envelope.parse.action)
        if not envelope.valid:
            reason = envelope.legality.reason if envelope.legality else envelope.parse.error_code or "invalid_action"
            next_state["failures"] = list(next_state["failures"]) + [reason]
            event = {"phase": phase.phase_id, "seat": next(iter(actions)), "valid": False, "reason": reason}
            if envelope.parse.ok and isinstance(envelope.parse.action, Mapping):
                event["action_candidate"] = dict(envelope.parse.action)
            if phase.phase_id == "customer_disclosure":
                event["requested_fact_ids"] = list(state["pending_requested"])
            if phase.phase_id == "customer_confirmation" and isinstance(state.get("proposal"), Mapping):
                event["expected_proposal_id"] = state["proposal"].get("proposal_id")
            next_state["events"] = list(next_state["events"]) + [event]
            next_state["done"] = True
            return TransitionResult(next_state, None)
        action = dict(envelope.action)
        event = {"phase": phase.phase_id, "seat": next(iter(actions)), "valid": True, "action": action}
        if phase.phase_id == "customer_disclosure":
            event["requested_fact_ids"] = list(state["pending_requested"])
        if phase.phase_id == "customer_confirmation" and isinstance(state.get("proposal"), Mapping):
            event["expected_proposal_id"] = state["proposal"].get("proposal_id")
        next_state["events"] = list(next_state["events"]) + [event]
        if phase.phase_id == "customer_claim":
            return TransitionResult(next_state, "intake_request")
        if phase.phase_id == "intake_request":
            next_state["pending_requested"] = list(action["requested_fact_ids"])
            return TransitionResult(next_state, "customer_disclosure")
        if phase.phase_id == "customer_disclosure":
            fields = list(action["revealed_fact_ids"])
            next_state["revealed_facts"] = {**next_state["revealed_facts"], **dict(action["fact_values"])}
            next_state["pending_requested"] = []
            return TransitionResult(next_state, "policy_turn")
        if phase.phase_id == "policy_turn":
            if action["action"] == "request_facts":
                next_state["pending_requested"] = list(action["requested_fact_ids"])
                return TransitionResult(next_state, "customer_disclosure")
            proposal = {key: action[key] for key in _RESOLUTION_FIELDS}
            proposal["proposal_id"] = str(action.get("proposal_id") or "proposal_1")
            proposal["amount"] = round(float(proposal["amount"]), 2)
            proposal["refund_method"] = proposal["refund_method"] or "none"
            next_state["proposal"] = proposal
            return TransitionResult(next_state, "customer_confirmation")
        if phase.phase_id == "customer_confirmation":
            next_state["confirmed_proposal_id"] = action["proposal_id"]
            proposal = next_state["proposal"]
            ledger = payment_ledger(case, proposal["amount"])
            already_applied = bool(ledger.get("already_applied"))
            execution_amount = round(float(ledger.get("executable_amount", proposal["amount"])), 2)
            execute = (
                not already_applied
                and execution_amount > 0
                and proposal["payment_mutation"] == "execute"
            )
            next_state["execution_ticket"] = {
                "proposal_id": proposal["proposal_id"],
                "kind": "execute" if execute else "no_op",
                "amount": execution_amount if execute else 0.0,
                "refund_method": proposal["refund_method"] if execute else "none",
                "idempotency_key": f"refund-{proposal['proposal_id']}",
                **{**ledger, "refund_allocations": ledger["refund_allocations"] if execute else ()},
            }
            return TransitionResult(next_state, "payments_execute")
        proposal = next_state["proposal"]
        if action["action"] == "execute_refund":
            ticket = next_state["execution_ticket"]
            next_state["transactions"] = list(next_state["transactions"]) + [{"proposal_id": proposal["proposal_id"], "idempotency_key": ticket["idempotency_key"], "amount": ticket["amount"], "refund_method": ticket["refund_method"], "refund_allocations": ticket["refund_allocations"]}]
        next_state["done"] = True
        return TransitionResult(next_state, None)

    def terminal(self, case: UnifiedRefundCase, state: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return dict(state) if state.get("done") else None

    def outcome(self, case: UnifiedRefundCase, terminal: Mapping[str, Any]) -> Mapping[str, Any]:
        expected = asdict(resolve_policy(case))
        candidate = terminal.get("policy_candidate")
        failures = tuple(str(reason) for reason in terminal.get("failures", ()))
        tags: dict[str, set[str]] = {name: set() for name in measurement.SCORING_DIMENSIONS}
        coverage: dict[str, float] = {name: 1.0 for name in measurement.SCORING_DIMENSIONS}

        def add(dimension: str, tag: str) -> None:
            tags[dimension].add(tag)

        if not isinstance(candidate, Mapping):
            values = {name: 0.0 for name in ("policy_semantic", "workflow", "payment", "evidence", "contract")}
            for name in values:
                coverage[name] = 0.0
                # Keep a missing candidate attributable.  A controlled policy
                # run can terminate before policy sees a turn because a
                # scripted upstream seat selected an illegal branch; that is
                # not evidence that the active policy model failed to emit a
                # resolution.
                last_seat = next((event.get("seat") for event in reversed(terminal.get("events", ())) if isinstance(event, Mapping) and not event.get("valid", True)), None)
                if last_seat == "intake":
                    add(name, "protocol_upstream_intake_failure")
                elif last_seat == "policy":
                    add(name, "protocol_policy_action_invalid")
                else:
                    add(name, "protocol_policy_candidate_missing")
        elif candidate.get("action") == "request_facts":
            requested = candidate.get("requested_fact_ids")
            evidence_ok = isinstance(requested, (list, tuple)) and bool(requested) and all(isinstance(item, str) for item in requested) and set(requested) <= set(policy_requestable_fact_ids(case, terminal.get("revealed_facts", {})))
            values = {"policy_semantic": 0.0, "workflow": 0.0, "payment": 0.0, "evidence": float(evidence_ok), "contract": 0.0}
            for name in ("policy_semantic", "workflow", "payment", "contract"):
                coverage[name] = 0.0
                add(name, "policy_no_final_resolution")
            if not evidence_ok:
                add("evidence", "policy_invalid_fact_request")
                add("evidence", "policy_conditional_fact_plan_error")
        else:
            present_semantic = [(field, tag) for field, tag in _SEMANTIC_FIELDS if field in candidate]
            semantic_matches = []
            mismatched_fields = set()
            for field, tag in present_semantic:
                matches = _scoring_value(field, candidate[field]) == expected[field]
                if field == "amount":
                    matches = _valid_amount(candidate[field]) and matches
                semantic_matches.append(matches)
                if not matches:
                    mismatched_fields.add(field)
                    add("policy_semantic", tag)
            values = {"policy_semantic": sum(semantic_matches) / len(semantic_matches) if semantic_matches else 0.0}
            coverage["policy_semantic"] = len(present_semantic) / len(_SEMANTIC_FIELDS)

            workflow_present = "workflow" in candidate
            values["workflow"] = float(workflow_present and _scoring_value("workflow", candidate["workflow"]) == expected["workflow"])
            coverage["workflow"] = float(workflow_present)
            if workflow_present and not values["workflow"]:
                add("workflow", "workflow_routing_error")

            payment_fields = ("payment_mutation", "refund_method")
            payment_matches = [_scoring_value(field, candidate[field]) == expected[field] for field in payment_fields if field in candidate]
            values["payment"] = sum(payment_matches) / len(payment_matches) if payment_matches else 0.0
            coverage["payment"] = len(payment_matches) / len(payment_fields)
            for field in payment_fields:
                if field in candidate and _scoring_value(field, candidate[field]) != expected[field]:
                    add("payment", "payment_mutation_error" if field == "payment_mutation" else "payment_refund_method_error")

            sufficient = not policy_required_fact_ids(case, terminal.get("revealed_facts", {}))
            values["evidence"] = float(sufficient)
            if not sufficient:
                add("evidence", "evidence_insufficient_before_decision")
                add("evidence", "policy_missing_decisive_fact")

            if case.interaction.scenario.startswith("policy_") and mismatched_fields:
                if case.interaction.scenario in {"policy_identity_override", "policy_evidence_conflict", "policy_payment_hold_precedence", "policy_return_liability"} and mismatched_fields.intersection({"eligibility", "remedy", "workflow"}):
                    add("policy_semantic", "policy_precedence_error")
                if case.interaction.scenario in {"policy_seller_fault_override", "policy_time_anchor", "policy_perishable_verification", "policy_bundle_cap"} and mismatched_fields.intersection({"eligibility", "remedy", "amount"}):
                    add("policy_semantic", "policy_category_override_error")

            # The request/submit branch above already separates fact requests.
            # Do not make the score depend on a duplicate transport field here:
            # completeness is the resolution payload itself.
            complete = not candidate.get("requested_fact_ids") and set(_RESOLUTION_FIELDS).issubset(candidate)
            for field in _RESOLUTION_FIELDS:
                if field not in candidate:
                    add("contract", f"contract_missing_{field}")
            canonical = complete
            for field, allowed in _CANONICAL_VALUES.items():
                if field in candidate and (not isinstance(candidate[field], str) or candidate[field] not in allowed):
                    canonical = False
                    add("contract", f"contract_noncanonical_{field}")
            if "amount" in candidate and not _valid_amount(candidate["amount"]):
                canonical = False
                add("contract", "contract_noncanonical_amount")
            if complete:
                if candidate["policy_basis"] != expected["policy_basis"] or candidate["reason_code"] != expected["policy_basis"]:
                    canonical = False
                    add("contract", "contract_reason_code_noncanonical")
            values["contract"] = float(complete and canonical)

        proposal, ticket, transactions = terminal.get("proposal"), terminal.get("execution_ticket"), terminal.get("transactions", ())
        binding = proposal is not None and isinstance(ticket, Mapping) and ((ticket["kind"] == "execute" and len(transactions) == 1 and transactions[0]["idempotency_key"] == ticket["idempotency_key"] and transactions[0]["amount"] == ticket["amount"] and transactions[0]["refund_method"] == ticket["refund_method"] and tuple(transactions[0]["refund_allocations"]) == tuple(ticket["refund_allocations"])) or (ticket["kind"] == "no_op" and not transactions))
        payment_attempted = any(event.get("phase") == "payments_execute" for event in terminal.get("events", ()) if isinstance(event, Mapping))
        if payment_attempted and not binding:
            values["payment"] = 0.0
            add("payment", "payment_proposal_binding_error")
        for failure in failures:
            if failure.startswith("intake_") or failure == "irrelevant_or_repeated_fact_request":
                add("evidence", failure)
            if failure.startswith("payment_") or failure.startswith("payments_") or failure == "invalid_payment_mutation":
                add("payment", failure)
            if failure == "decision_before_required_facts":
                add("evidence", "policy_missing_decisive_fact")
            if failure == "irrelevant_or_repeated_fact_request":
                add("evidence", "policy_conditional_fact_plan_error")
            if failure == "policy_overcollection_after_terminal_route":
                add("evidence", failure)
        strict = not failures and proposal is not None and terminal.get("confirmed_proposal_id") == proposal.get("proposal_id") and binding and all(values[name] == 1.0 and coverage[name] == 1.0 for name in ("policy_semantic", "workflow", "payment", "evidence", "contract"))
        values["end_to_end"] = float(strict)
        if not strict:
            add("end_to_end", "strict_trajectory_incomplete")
            for failure in failures:
                add("end_to_end", failure)
        values["operational"] = 1.0
        collaboration_values, collaboration_coverage, collaboration_tags, opportunities = _collaboration_measurements(case, terminal)
        values.update(collaboration_values)
        coverage.update(collaboration_coverage)
        for name, dimension_tags in collaboration_tags.items():
            tags[name].update(dimension_tags)
        all_tags = tuple(sorted(set(failures).union(*(tags[name] for name in measurement.SCORING_DIMENSIONS))))
        return {
            **values,
            "taxonomy": all_tags,
            "taxonomy_by_dimension": {name: tuple(sorted(value)) for name, value in tags.items()},
            "coverage_by_dimension": coverage,
            "opportunities_by_collaboration_dimension": opportunities,
        }

    def build_scorer(self, case: UnifiedRefundCase): return measurement.build_scorer(case)
    def build_reference_providers(self, case: UnifiedRefundCase) -> tuple[Any, ...]: del case; return ()
    def generator(self) -> None: return None


class ScriptedV25Provider:
    """Deterministic counterparts operating only on their seat observations."""
    async def complete(self, request: ProviderRequest) -> ProviderResult:
        try: payload = json.loads(request.input_text)
        except json.JSONDecodeError as error: raise ProviderFailure("provider_contract", str(error), retryable=False) from error
        role, obs = str(payload["role"]), payload["observation"]
        phase = obs["phase_id"]
        if role == "customer":
            if phase == "customer_claim": action = {"decision": "state_claim", "message": obs["public_claim"], "revealed_fact_ids": []}
            elif phase == "customer_disclosure":
                requested = list(obs["requested_fact_ids"])
                action = {"decision": "disclose_facts", "message": "Here are the requested facts.", "revealed_fact_ids": requested, "fact_values": {fact: obs["private_facts"][fact] for fact in requested}, "proposal_id": None}
            else: action = {"decision": "confirm_resolution", "message": "I confirm the resolution.", "revealed_fact_ids": [], "proposal_id": obs["pending_proposal"]["proposal_id"]}
        elif role == "intake":
            action = {"decision": "request_facts", "requested_fact_ids": _scripted_intake_batch(obs)}
        elif role == "payments":
            ticket = obs["execution_ticket"] or {}
            amount = _ticket_amount(ticket)
            if ticket.get("kind") is not None:
                execute = ticket["kind"] == "execute"
            else:
                execute = amount > 0 and ticket.get("state") != "idempotency_key_already_applied"
            action = {"decision": "execute_refund" if execute else "no_mutation", "proposal_id": ticket.get("proposal_id"), "idempotency_key": ticket.get("idempotency_key"), "ledger_snapshot_id": ticket.get("ledger_snapshot_id"), "amount": amount if execute else 0.0, "refund_method": ticket.get("refund_method", "none") if execute else "none", "refund_allocations": _ticket_allocations(ticket) if execute else []}
        else:
            contract = str(obs["policy_contract"])
            scenario_match = re.search(r"Interaction ID: ([a-z_]+)\.", contract)
            if scenario_match is None:
                raise ProviderFailure("provider_contract", "policy contract lacks interaction ID", retryable=False)
            scenario = scenario_match.group(1)
            revealed = dict(obs["revealed_facts"])
            specification = re.search(r"^Public branch specification JSON: (.+)$", contract, re.MULTILINE)
            if specification is None:
                raise ProviderFailure("provider_contract", "missing versioned public branch specification", retryable=False)
            branch_spec = BranchSpec.from_dict(json.loads(specification.group(1)))
            money = re.search(r"item_net_price = ([0-9]+(?:\.[0-9]{2})?); allocated_tax = ([0-9]+(?:\.[0-9]{2})?)", contract)
            if money is None or branch_spec.scenario != scenario:
                raise ProviderFailure("provider_contract", "public branch inputs do not bind scenario", retryable=False)
            public = public_inputs(float(money.group(1)), float(money.group(2)))
            missing = branch_spec.pending(revealed, public)
            if missing:
                action = {"decision": "request_facts", "requested_fact_ids": list(missing[:3])}
            else:
                # Resolve solely from public JSON and revealed facts. Never
                # manufacture missing private values for the full-case oracle.
                resolution = branch_spec.resolve(revealed, public)
                action = {"decision": "submit_resolution", **resolution, "requested_fact_ids": [], "proposal_id": "proposal_1"}
        return ProviderResult(f"refund_v25_scripted:{request.provider_call_id}", request.model, request.revision or request.model, json.dumps(action, sort_keys=True), "stop", 0, 0, 0, 0.0, {"reference": True})


@dataclass(frozen=True, slots=True)
class RefundV25Setup:
    plan: RunPlan
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    harnesses: Mapping[str, Any]


def _pin(identifier: str, kind: str, path: Path, version: str = FAMILY_VERSION) -> ImplementationPin:
    return ImplementationPin.from_dict({"component_id": identifier, "kind": kind, "version": version, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})


def _case_manifest(case: UnifiedRefundCase) -> CaseManifest:
    payload = {"case": asdict(case), "rendered_policy_contract": render_policy_contract(case), "reference_resolution": asdict(resolve_policy(case)), "semantic_case_sha256": hashlib.sha256(canonical_json_bytes({"case": asdict(case), "contract": render_policy_contract(case)})).hexdigest()}
    raw = {"spec_version": CaseManifest.SPEC_VERSION, "case_id": case.case_id, "family_id": FAMILY_ID, "family_version": FAMILY_VERSION, "split": "dev", "world_seed": case.interaction.world_seed, "seats": [{"id": role, "role": role} for role in ROLES], "episode": {"max_logical_actions": 30, "termination": ["completed", "invalid_action"]}, "visibility_policy": "refund_v25_four_seat_visibility", "payload": payload, "provenance": {"generator_id": "refund_v25_unified_panel", "generator_version": FAMILY_VERSION, "review_status": "reviewed"}, "content_sha256": "0" * 64}
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _profile(role: str, provider: str, model: str, revision: str) -> AgentProfile:
    """Build a profile while omitting unsupported sampling controls."""
    pricing = TokenPricing(0, 0, 0, f"refund_v25_{provider}_{model}")
    config = {
        "pricing_id": pricing.pricing_id,
        "pricing_sha256": pricing.content_sha256(),
        "output_schema": SCHEMAS[role],
    }
    if provider == "arena" and model.startswith("gpt-6"):
        config["sampling_controls"] = {"temperature": "unavailable"}
    return AgentProfile.from_dict({
        "spec_version": AgentProfile.SPEC_VERSION,
        "profile_id": f"refund_v25_{role}_{provider}_{model.replace('/', '_')}",
        "model": {"provider": provider, "model": model, "revision": revision, "base_url": "https://api.preview.arena.ai/v1" if provider == "arena" else None},
        "harness": {"id": "minimal_chat", "version": "1.0", "config": config},
        "prompt": {"prompt_id": PROMPT_IDS[role], "sha256": hashlib.sha256(PROMPTS[role].encode()).hexdigest()},
        "runtime": {"kind": "python", "implementation": "aeread.shared_runner.task.execution", "version": "0.1.0"},
        "tools": [], "memory": {"mode": "disabled"},
        "reasoning": {"condition_id": f"refund_v25_{role}_default", "effort": None, "token_budget": None, "rationale_visibility": "hidden"},
        "sampling": {"temperature": 0.0, "max_output_tokens": 4096 if provider == "arena" else 512, "seed": None, "top_p": None},
        "budgets": {"max_logical_actions": 30, "timeout_seconds": 180.0 if provider == "arena" else 30.0, "max_cost_usd": None},
        "retry_policy": {"max_action_attempts": 2, "retryable_conditions": ["empty_response", "length"], "sdk_retries": 0, "session_mode": "restart"},
    })


def _contribution() -> FamilyContribution:
    qc = QC_ROOT / "qc"
    approval = json.loads((qc / "human_qc.json").read_bytes())
    if approval.get("family_version") != FAMILY_VERSION or approval.get("decision") != "approved" or approval.get("scope") != "developmental_design":
        raise ValueError("V2.5 requires its own explicit developmental design approval")
    provider = QCEvidenceRef("provider_free_conformance", "qc/provider_free.json", hashlib.sha256((qc / "provider_free.json").read_bytes()).hexdigest(), FAMILY_ID, FAMILY_VERSION, FAMILY_ID, (QCCoverage("provider_free_validation", (FAMILY_ID,), (FAMILY_ID,)),))
    human = QCEvidenceRef("human_qc_approval", "qc/human_qc.json", hashlib.sha256((qc / "human_qc.json").read_bytes()).hexdigest(), FAMILY_ID, FAMILY_VERSION, FAMILY_ID, (QCCoverage("human_qc", (FAMILY_ID,), (FAMILY_ID,)),))
    base = FamilyContribution(FAMILY_ID, FAMILY_VERSION, "aeread.refund_v25", "contributed.refund_v25.2.5", {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, provider, ResourceLimits(120, 30, 60, 200000, 100000, 100), HumanQCApproval("refund-v25-user-design-approval", "approved", "0" * 64, human))
    return replace(base, human_qc_approval=replace(base.human_qc_approval, contribution_sha256=family_contribution_sha256(base)))


def family_manifest() -> FamilyManifest:
    refs = ["refund_v24_case_dependency", "refund_v24_reference_dependency", "refund_v25_domain", "refund_v25_policy_reference", "refund_v25_public_branches", *[f"{estimand}_verifier" for estimand in measurement.ESTIMANDS]]
    return FamilyManifest.from_dict({"spec_version": FamilyManifest.SPEC_VERSION, "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": "aeread.refund_v25"}, "environment": {"topology": "customer_intake_policy_payments", "phase_specs": ["customer_claim", "intake_request", "customer_disclosure", "policy_turn", "customer_confirmation", "payments_execute"], "needs_tools": False, "needs_sandbox": False}, "roles": {role: {"testable": True, "scripted_policies": ["scripted"]} for role in ROLES}, "measurement": {"primary_estimand": "refund_v25_end_to_end", "measurement_kind": "property_or_answer", "direction": "none", "optimum_lower_bound": "0", "optimum_upper_bound": "1", "optimum_upper_bound_kind": "known", "bound_status": "family_defined", "outcome_support": "pass_fail", "leaves": [{"leaf_id": leaf, "scope": "finalize_time"} for leaf in measurement.LEAF_IDS], "primary_leaf_id": measurement.END_TO_END_LEAF_ID, "admission_leaf_ids": [measurement.END_TO_END_LEAF_ID, measurement.POLICY_LEAF_ID, measurement.PAYMENT_LEAF_ID, measurement.OPERATIONAL_LEAF_ID]}, "scoring": {"scorer_id": "refund_v25_scorer", "reference_provider_ids": refs}, "generator": {"generator_id": "refund_v25_unified_panel", "difficulty_knobs": ["product_category", "scenario", "counterfactual_pair", "world_seed"]}})


def build_refund_v25_run(*, provider: str = "scripted", model: str = "refund-v25-scripted", revision: str = FAMILY_VERSION, world_seeds: tuple[int, ...] = (1,), active_agents: tuple[str, ...] = ("policy",), evaluation_kind: str = "controlled", include_operational_extension: bool = False, include_policy_stress_extension: bool = False, include_policy_frontier_extension: bool = False, include_policy_frontier_hard_extension: bool = False, case_ids: tuple[str, ...] | None = None, repetitions: int = 1, comparison_campaign: bool = False, comparison_campaign_id: str | None = None, cases: tuple[UnifiedRefundCase, ...] | None = None, extra_implementation_pins: tuple[ImplementationPin, ...] = ()) -> RefundV25Setup:
    """Resolve cases into independent repeated cells without provider calls.

    Supplied cases replace generation; their seeds are authoritative. V3
    comparison overrides admit all extensions and declare template bootstrap
    stratified uncertainty with Holm multiplicity. Extra reference pins bind
    wrapper dependencies.
    Generic case manifests use dev; the frozen campaign rows own split labels.
    """
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    if type(comparison_campaign) is not bool:
        raise ValueError("comparison_campaign must be a boolean")
    if comparison_campaign and (active_agents != ("policy",) or evaluation_kind != "controlled"):
        raise ValueError("comparison_campaign requires controlled policy-only evaluation")
    if comparison_campaign_id is not None and (not comparison_campaign or not comparison_campaign_id.replace("_", "").isalnum()):
        raise ValueError("comparison_campaign_id must be a simple identifier on a comparison campaign")
    if any(pin.kind != "reference" for pin in extra_implementation_pins):
        raise ValueError("extra_implementation_pins must use kind=reference for campaign dependencies")
    if not active_agents or not set(active_agents) <= set(ROLES): raise ValueError(f"active_agents must be selected from {ROLES}")
    if evaluation_kind not in {"controlled", "self_play"}: raise ValueError("evaluation_kind must be controlled or self_play")
    if evaluation_kind == "controlled" and len(active_agents) != 1: raise ValueError("controlled mode requires exactly one active seat")
    raw_cases = cases if cases is not None else tuple(case for seed in world_seeds for case in build_unified_panel(seed, include_operational_extension=include_operational_extension, include_policy_stress_extension=include_policy_stress_extension, include_policy_frontier_extension=include_policy_frontier_extension, include_policy_frontier_hard_extension=include_policy_frontier_hard_extension))
    comparison_override = comparison_campaign and cases is not None
    admit_panel(raw_cases, include_operational_extension=include_operational_extension or comparison_override, include_policy_stress_extension=include_policy_stress_extension or comparison_override, include_policy_frontier_extension=include_policy_frontier_extension or comparison_override, include_policy_frontier_hard_extension=include_policy_frontier_hard_extension or comparison_override)
    selected_ids = set(case_ids) if case_ids else None
    unknown_ids = selected_ids - {case.case_id for case in raw_cases} if selected_ids else set()
    if unknown_ids:
        raise ValueError(f"unknown case_ids: {sorted(unknown_ids)}")
    selected_cases = tuple(case for case in raw_cases if selected_ids is None or case.case_id in selected_ids)
    if not selected_cases:
        raise ValueError("case_ids selected no cases")
    cases = tuple(_case_manifest(case) for case in selected_cases)
    profiles = tuple(_profile(role, provider if role in active_agents else "scripted", model if role in active_agents else f"refund-v25-scripted-{role}", revision if role in active_agents else FAMILY_VERSION) for role in ROLES)
    sampling = SamplingPlan.from_dict({"spec_version": SamplingPlan.SPEC_VERSION, "sampling_plan_id": "refund_v25_fixed_panel", "estimand": "refund_v25_unified", "target": "refund_v25_unified_panel", "selection": "seeded_case_panel", "seeds": [0], "replicates": 1, "cluster_level": "world_seed", "cluster_id_fields": ["generator_version", "world_seed"], "paired_fields": ["world_seed"], "replicate_level": "episode_attempt", "panel_mode": "fixed_panel"})
    controlled = {role: next(profile.profile_id for profile in profiles if profile.profile_id.startswith(f"refund_v25_{role}_scripted_")) for role in ROLES if role not in active_agents}
    block = EvaluationBlock.from_dict({"spec_version": EvaluationBlock.SPEC_VERSION, "block_id": f"refund_v25_{evaluation_kind}_{'_'.join(active_agents)}", "kind": evaluation_kind, "subject_seats": list(active_agents), "controlled_profiles": controlled if evaluation_kind == "controlled" else {}, "repetitions": repetitions, "seed_policy": "fixed"})
    analysis = AnalysisPlan.from_dict({"spec_version": AnalysisPlan.SPEC_VERSION, "analysis_plan_id": "refund_v25_branch_contract_v2_attribution", "estimands": list(measurement.ESTIMANDS), "group_by": ["family_id", "subject_role", "product_category", "scenario"], "missingness": "report_separately", "resampling_unit": "world_seed", "uncertainty": "none", "multiplicity": "none", "sensitivity": ["failure_taxonomy", "counterfactual_pairs"], "cross_family_scalar": "disabled"})
    if comparison_campaign:
        # AnalysisPlan validates these fields as identifiers, not enums.
        # Scenario identifies a template; seeds, variants and repetitions
        # remain observations within it. This declares analysis, not execution.
        campaign_id = comparison_campaign_id or "refund_v25_policy_comparison_branch_v1"
        analysis = AnalysisPlan.from_dict({
            **asdict(analysis),
            "analysis_plan_id": campaign_id,
            "resampling_unit": "template",
            "uncertainty": "stratified_template_bootstrap",
            "multiplicity": "holm",
        })
    suite_id = f"{comparison_campaign_id}_suite" if comparison_campaign_id else "refund_v25_branch_contract_v2_suite"
    run_spec_id = f"{comparison_campaign_id}_run" if comparison_campaign_id else "refund_v25_branch_contract_v2_run"
    suite = SuiteManifest.from_dict({"spec_version": SuiteManifest.SPEC_VERSION, "suite_id": suite_id, "version": FAMILY_VERSION, "family_ids": [FAMILY_ID], "case_ids": [case.case_id for case in cases], "sampling_plan_id": sampling.sampling_plan_id, "evaluation_block_ids": [block.block_id], "analysis_plan_id": analysis.analysis_plan_id})
    run_spec = RunSpec.from_dict({"spec_version": RunSpec.SPEC_VERSION, "run_spec_id": run_spec_id, "suite_id": suite.suite_id, "evaluation_block_ids": [block.block_id], "agent_profile_ids": [profile.profile_id for profile in profiles], "seat_assignments": {role: next(profile.profile_id for profile in profiles if profile.profile_id.startswith(f"refund_v25_{role}_")) for role in ROLES}, "execution_mode": "evaluate", "replicate_override": None, "budget_overrides": None})
    manifest = family_manifest()
    if extra_implementation_pins:
        manifest = replace(manifest, scoring=replace(
            manifest.scoring,
            reference_provider_ids=manifest.scoring.reference_provider_ids + tuple(pin.component_id for pin in extra_implementation_pins),
        ))
    registry = PluginRegistry(); registry.register(manifest, RefundV25Plugin(), contribution=_contribution(), evidence_root=QC_ROOT)
    harnesses = default_harnesses(); harness_registry = HarnessRegistry()
    for harness in harnesses.values(): harness_registry.register(harness)
    execution_path = Path(execution_module.__file__)
    pins = [_pin("aeread.refund_v25", "family_plugin", Path(__file__)), _pin("refund_v25_unified_panel", "generator", Path(__file__).with_name("v2_5_policy.py")), _pin("refund_v25_policy_reference", "reference", Path(__file__).with_name("v2_5_policy.py")), _pin("refund_v25_scorer", "scorer", Path(__file__).with_name("v2_5_measurement.py"), measurement.VERSION), _pin("minimal_chat", "harness", execution_path, "1.0"), _pin("aeread.shared_runner.task.execution", "runtime", execution_path, "0.1.0")]
    pins.append(_pin("refund_v25_public_branches", "reference", Path(__file__).with_name("v2_5_branches.py"), "2.0"))
    pins.extend(_pin(f"{estimand}_verifier", "reference", Path(__file__), measurement.VERSION) for estimand in measurement.ESTIMANDS); pins.append(_pin("refund_v25_domain", "reference", Path(__file__), measurement.VERSION))
    pins.extend((_pin("refund_v24_case_dependency", "reference", Path(__file__).with_name("v2_4_cases.py")), _pin("refund_v24_reference_dependency", "reference", Path(__file__).with_name("v2_4_reference.py"))))
    pins.extend(extra_implementation_pins)
    plan = resolve_run_plan(families=(manifest,), cases=cases, suite=suite, sampling=sampling, evaluation_blocks=(block,), analysis=analysis, agent_profiles=profiles, run_spec=run_spec, registry=registry, implementation_pins=tuple(pins), harness_registry=harness_registry, provider_capabilities={provider: ProviderCapabilities(False, False, False, True, True, False, None), "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    return RefundV25Setup(plan, registry, {PROMPT_IDS[role]: PROMPTS[role] for role in ROLES}, {profile.model.model: TokenPricing(0, 0, 0, f"refund_v25_{profile.model.provider}_{profile.model.model}") for profile in profiles}, harnesses)


async def run(*, output: Path, provider: str = "scripted", model: str = "refund-v25-scripted", revision: str = FAMILY_VERSION, world_seeds: tuple[int, ...] = (1,), active_agents: tuple[str, ...] = ("policy",), evaluation_kind: str = "controlled", include_operational_extension: bool = False, include_policy_stress_extension: bool = False, include_policy_frontier_extension: bool = False, include_policy_frontier_hard_extension: bool = False, case_ids: tuple[str, ...] | None = None, repetitions: int = 1, comparison_campaign: bool = False, comparison_campaign_id: str | None = None, cases: tuple[UnifiedRefundCase, ...] | None = None, extra_implementation_pins: tuple[ImplementationPin, ...] = (), env_file: Path | None = None) -> dict[str, Any]:
    if provider != "scripted":
        raise ValueError("Public V2.5 execution is provider-free pending Arena qualification (#267); build_refund_v25_run can still prepare profiles without calls")
    setup = build_refund_v25_run(provider=provider, model=model, revision=revision, world_seeds=world_seeds, active_agents=active_agents, evaluation_kind=evaluation_kind, include_operational_extension=include_operational_extension, include_policy_stress_extension=include_policy_stress_extension, include_policy_frontier_extension=include_policy_frontier_extension, include_policy_frontier_hard_extension=include_policy_frontier_hard_extension, case_ids=case_ids, repetitions=repetitions, comparison_campaign=comparison_campaign, comparison_campaign_id=comparison_campaign_id, cases=cases, extra_implementation_pins=extra_implementation_pins)
    providers: dict[str, Any] = {"scripted": ScriptedV25Provider()}
    if provider == "arena": providers["arena"] = ArenaChatClient()
    receipts = []
    for cell in setup.plan.cells:
        execution = await execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=output, prompt_sources=setup.prompt_sources, providers=providers, pricing=setup.pricing, episode_attempt_ordinal=0, harnesses=setup.harnesses)
        receipt = finalize_family_execution(setup=setup, execution=execution)
        replay_family_receipt(setup=setup, receipt=receipt, evidence_root=output)
        receipts.append(receipt)
    return {"run_plan_id": setup.plan.run_plan_id, "active_agents": list(active_agents), "planned_cells": len(setup.plan.cells), "completed_cells": len(receipts), "operational_failures": 0, "receipts": [json.loads(canonical_json_bytes(receipt)) for receipt in receipts]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("scripted",), default="scripted")
    parser.add_argument("--model", default="refund-v25-scripted")
    parser.add_argument("--revision", default=FAMILY_VERSION)
    parser.add_argument("--world-seeds", default="1")
    parser.add_argument("--active-agents", default="policy")
    parser.add_argument("--evaluation-kind", choices=("controlled", "self_play"), default="controlled")
    parser.add_argument("--repetitions", type=int, default=1, help="independent evaluation cells per case (positive integer)")
    parser.add_argument("--comparison-campaign", action="store_true", help="declare the v3 policy-only template bootstrap/Holm analysis contract")
    parser.add_argument("--include-operational-extension", action="store_true")
    parser.add_argument("--include-policy-stress-extension", action="store_true")
    parser.add_argument("--include-policy-frontier-extension", action="store_true")
    parser.add_argument("--include-policy-frontier-hard-extension", action="store_true")
    parser.add_argument("--case-ids", default=None, help="comma-separated case IDs to run after full-panel admission")
    parser.add_argument("--env-file", type=Path, default=None, help="simple KEY=VALUE file used only to load provider credentials")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = asyncio.run(run(output=args.output, provider=args.provider, model=args.model, revision=args.revision, world_seeds=tuple(int(seed) for seed in args.world_seeds.split(",") if seed), active_agents=tuple(agent.strip() for agent in args.active_agents.split(",") if agent.strip()), evaluation_kind=args.evaluation_kind, include_operational_extension=args.include_operational_extension, include_policy_stress_extension=args.include_policy_stress_extension, include_policy_frontier_extension=args.include_policy_frontier_extension, include_policy_frontier_hard_extension=args.include_policy_frontier_hard_extension, repetitions=args.repetitions, comparison_campaign=args.comparison_campaign, case_ids=tuple(case_id.strip() for case_id in args.case_ids.split(",") if case_id.strip()) if args.case_ids else None, env_file=args.env_file))
    print(json.dumps({key: report[key] for key in ("active_agents", "planned_cells", "completed_cells", "operational_failures")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
