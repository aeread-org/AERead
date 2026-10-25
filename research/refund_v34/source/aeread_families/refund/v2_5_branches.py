"""Public typed branch contract v2: partial-information logic, not an oracle.

No case object or hidden facts enter evaluation. The handwritten resolver and
goldens stay separate, so admission can detect a shared-compiler mistake.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Mapping

DESIGN_VERSION = "refund_v25_branch_contract/2"


@dataclass(frozen=True)
class Predicate:
    op: str
    fields: tuple[str, ...] = ()
    value: Any = None
    children: tuple["Predicate", ...] = ()

    def evaluate(self, facts: Mapping[str, Any], public: Mapping[str, Any]) -> tuple[bool | None, tuple[str, ...]]:
        values = {**facts, **public}
        if self.op == "always":
            return True, ()
        if self.op in {"all", "any", "not"}:
            results = [c.evaluate(facts, public) for c in self.children]
            if self.op == "not":
                result, pending = results[0]
                return (None if result is None else not result), pending
            # Evaluate all known predicates before asking anything: a failed
            # conjunction or satisfied disjunction short-circuits even when
            # its decisive operand is not first in the written expression.
            decisive = False if self.op == "all" else True
            if any(r is decisive for r, _ in results):
                return decisive, ()
            unknown = [pending for r, pending in results if r is None]
            if not unknown:
                return not decisive, ()
            pending = unknown[0] if self.op == "any" else tuple(dict.fromkeys(f for group in unknown for f in group))
            return None, pending
        missing = tuple(f for f in self.fields if f not in values)
        if missing:
            return None, missing
        left = values[self.fields[0]]
        right = values[self.fields[1]] if len(self.fields) == 2 else self.value
        if self.op == "eq": return left == right, ()
        if self.op == "ne": return left != right, ()
        if self.op == "le": return float(left) <= float(right), ()
        if self.op == "gt": return float(left) > float(right), ()
        if self.op == "in": return left in right, ()
        raise ValueError(f"Unknown public predicate: {self.op}")

    def text(self) -> str:
        if self.op == "always": return "otherwise"
        if self.op == "not": return "NOT (" + self.children[0].text() + ")"
        if self.children:
            return "(" + (" AND " if self.op == "all" else " OR ").join(c.text() for c in self.children) + ")"
        right = self.fields[1] if len(self.fields) == 2 else json.dumps(self.value)
        return f"{self.fields[0]} {dict(eq='=', ne='!=', le='≤', gt='>', **{'in': 'in'})[self.op]} {right}"

    def fact_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.fields, *(f for c in self.children for f in c.fact_ids()))))


def eq(field, value): return Predicate("eq", (field,), value)
def ne(field, value): return Predicate("ne", (field,), value)
def compare(op, left, right): return Predicate(op, (left, right))
def ALL(*children): return Predicate("all", children=children)
def ANY(*children): return Predicate("any", children=children)
def NOT(child): return Predicate("not", children=(child,))
ALWAYS = Predicate("always")


@dataclass(frozen=True)
class Outcome:
    basis: str
    eligibility: str
    remedy: str
    workflow: str
    amount_kind: str = "zero"
    payer: str = "none"
    amount_fields: tuple[str, ...] = ()

    def formula(self) -> str:
        if self.amount_kind == "zero": return "0"
        if self.amount_kind == "full": return "round(item_net_price + allocated_tax, 2)"
        if self.amount_kind == "residual": return "round(max(0, item_net_price + allocated_tax - settled_refund_cents/100), 2)"
        value = self.amount_fields[0]
        if self.amount_kind == "piecewise":
            return f"round(min({value}, round(item_net_price × category_cap_rate, 2)) + allocated_component_tax, 2)"
        return f"round(min({value}, item_net_price × category_cap_rate), 2)"

    def resolution(self, facts, public) -> dict:
        price, tax = float(public["item_net_price"]), float(public["allocated_tax"])
        amount = 0.0
        if self.amount_kind == "full": amount = round(price + tax, 2)
        elif self.amount_kind == "residual": amount = round(max(0, round(price + tax, 2) - round(int(facts["settled_refund_cents"]) / 100, 2)), 2)
        elif self.amount_kind in {"partial", "piecewise"}:
            cap = price * float(facts["category_cap_rate"])
            if self.amount_kind == "piecewise": cap = round(cap, 2)
            amount = round(min(float(facts[self.amount_fields[0]]), cap) +
                           (float(facts["allocated_component_tax"]) if self.amount_kind == "piecewise" else 0), 2)
        workflow = "no_mutation" if self.workflow == "execute_refund" and amount == 0 else self.workflow
        return dict(eligibility=self.eligibility, remedy=self.remedy, workflow=workflow,
                    amount=amount, refund_method="original_payment" if amount > 0 else "none",
                    payment_mutation="execute" if workflow == "execute_refund" and amount > 0 else "none",
                    return_shipping_payer=self.payer, policy_basis=self.basis, reason_code=self.basis)


@dataclass(frozen=True)
class Branch:
    when: Predicate
    outcome: Outcome


@dataclass(frozen=True)
class BranchSpec:
    scenario: str
    branches: tuple[Branch, ...]
    # Public initial intake order is value-blind. It is routing guidance, not
    # the current terminal outcome or a hidden reference fact set.
    intake_order: tuple[str, ...]

    def pending(self, revealed, public) -> tuple[str, ...]:
        for branch in self.branches:
            result, pending = branch.when.evaluate(revealed, public)
            if result is None: return pending
            if result:
                return tuple(f for f in branch.outcome.amount_fields if f not in revealed)
        raise ValueError("Public branches lack a fallback")

    def resolve(self, revealed, public) -> dict:
        if self.pending(revealed, public):
            raise ValueError("Cannot resolve before decisive evidence")
        for branch in self.branches:
            if branch.when.evaluate(revealed, public)[0] is True:
                return branch.outcome.resolution(revealed, public)
        raise ValueError("Public branches lack a resolution")

    def fact_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f for b in self.branches for f in
                     (*b.when.fact_ids(), *b.outcome.amount_fields) if f not in {"item_net_price", "allocated_tax", "full_refund_cents"}))

    def catalogue(self) -> str:
        return "; ".join(f"{i+1}. {b.outcome.basis} ({b.when.text()} → "
                         f"eligibility={b.outcome.eligibility}, remedy={b.outcome.remedy}, workflow={b.outcome.workflow}, "
                         f"amount={b.outcome.formula()}, payer={b.outcome.payer})" for i, b in enumerate(self.branches))

    def graph(self) -> str:
        return ("inspect {" + ", ".join(self.fact_ids()) + "} conditionally; " +
                "; ".join(f"{i+1}: {b.when.text()} → terminal {b.outcome.workflow}; amount inputs "
                          "{" + ", ".join(b.outcome.amount_fields) + "}" for i, b in enumerate(self.branches)) +
                "; these are possible facts, not an all-fields checklist; evaluate known operands first; "
                "stop when the first applicable branch and its amount are determined")

    def to_dict(self): return {"design_version": DESIGN_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, raw):
        if raw["design_version"] != DESIGN_VERSION: raise ValueError("Unsupported branch contract")
        def pred(p): return Predicate(p["op"], tuple(p["fields"]), p["value"], tuple(pred(c) for c in p["children"]))
        return cls(raw["scenario"], tuple(Branch(pred(b["when"]), Outcome(**{**b["outcome"], "amount_fields": tuple(b["outcome"]["amount_fields"])})) for b in raw["branches"]), tuple(raw["intake_order"]))


def spec_for(s: str) -> BranchSpec:
    """Authored public semantics; every ordered rule has one explicit outcome."""
    def hold(basis, workflow="request_evidence", payer="none"):
        return Outcome(basis, "unresolved", "none", workflow, payer=payer)
    def full(basis, payer="seller"):
        return Outcome(basis, "eligible", "full_refund", "execute_refund", "full", payer)
    def deny(basis): return Outcome(basis, "ineligible", "none", "no_mutation")
    def partial(basis, value, payer="none", piecewise=False):
        fields = (value, "category_cap_rate") + (("allocated_component_tax",) if piecewise else ())
        return Outcome(basis, "eligible", "partial_refund", "execute_refund", "piecewise" if piecewise else "partial", payer, fields)
    verified = eq("defect_evidence", "verified")
    identity = ALL(eq("inspection_stage", "post_return_warehouse"), compare("ne", "order_serial", "inspection_serial"))
    evidence = ALL(eq("customer_evidence", "verified_mismatch"), eq("warehouse_inspection", "verified_mismatch"), eq("listing_snapshot", "ENT-A"))
    payment = eq("chargeback_state", "pending")
    fault = eq("seller_fault_event", "verified_wrong_item")
    identity_order = ("inspection_stage", "order_serial", "inspection_serial")
    rules = []
    order = ()
    if s == "seller_fault_unverified_evidence":
        rules = [(verified, full("R_SELLER_FAULT_VERIFIED")), (ALWAYS, hold("R_SELLER_FAULT_UNVERIFIED"))]
        order = ("defect_evidence",)
    elif s == "wrong_item_received":
        rules = [(ne("sku_evidence_status", "verified"), hold("R_WRONG_ITEM_UNVERIFIED")),
                 (compare("eq", "ordered_sku", "received_sku"), deny("R_WRONG_ITEM_MATCH")),
                 (ALWAYS, full("R_WRONG_ITEM_VERIFIED"))]
        order = ("sku_evidence_status",)
    elif s in {"missing_parts_partial_refund", "multiple_missing_components"}:
        single = s == "missing_parts_partial_refund"
        rules = [(ne("evidence_status", "verified"), hold("R_COMPONENT_UNVERIFIED" if single else "R_COMPONENTS_UNVERIFIED")),
                 (eq("component_role", "core") if single else eq("core_component_missing", True), full("R_MISSING_CORE" if single else "R_CORE_PRECEDENCE")),
                 (ALWAYS, partial("R_MISSING_NONCORE_CAP" if single else "R_NONCORE_COMBINED_CAP", "component_catalog_value" if single else "noncore_catalog_total"))]
        order = ("evidence_status", "component_role" if single else "core_component_missing")
    elif s == "discounted_bundle_component_value":
        rules = [(ne("evidence_status", "verified"), hold("R_BUNDLE_UNVERIFIED")), (ALWAYS, partial("R_BUNDLE_PAID_ALLOCATION", "paid_component_allocation"))]
        order = ("evidence_status",)
    elif s == "late_defect_identity_conflict":
        rules = [(identity, hold("R_IDENTITY_PRECEDENCE", "identity_review")),
                 (ALL(verified, Predicate("le", ("return_request_day",), 90)), full("R_DEFECT_EXCEPTION")),
                 (ALWAYS, hold("R_DEFECT_NOT_VERIFIED"))]
        order = identity_order
    elif s == "returnless_refund_high_value_exception":
        rules = [(NOT(verified), hold("R_DEFECT_UNVERIFIED")),
                 (ALL(eq("identity_risk", "low"), compare("le", "item_net_price", "returnless_threshold")), full("R_RETURNLESS_LOW_RISK")),
                 (ALWAYS, hold("R_RETURNLESS_RISK_EXCEPTION", "return_and_inspect", "seller"))]
        order = ("defect_evidence", "identity_risk")
    elif s in {"carrier_delay_request_date", "policy_time_anchor"}:
        rules = [(Predicate("le", ("return_request_day",), 30), full("R_REQUEST_WITHIN_WINDOW" if s == "carrier_delay_request_date" else "R_RETURN_WINDOW", "customer")),
                 (ALWAYS, deny("R_REQUEST_OUTSIDE_WINDOW" if s == "carrier_delay_request_date" else "R_RETURN_WINDOW"))]
        order = ("return_request_day",)
    elif s == "refund_already_issued_chargeback_pending":
        # This legacy interaction always holds, but branch ID still depends
        # on chargeback. Product-condition facts are not evidence for it.
        rules = [(payment, hold("R_CHARGEBACK_PENDING", "payment_review")), (ALWAYS, hold("R_REFUND_ALREADY_PENDING", "payment_review"))]
        order = ("chargeback_state",)
    elif s in {"condition_deterioration_after_return", "policy_return_liability", "frontier_liability_then_amount"}:
        core = s == "condition_deterioration_after_return"
        rules = [(eq("inspection_cause", "buyer_caused"), hold("R_BUYER_DETERIORATION" if core else "R_POST_RETURN_LIABILITY", "seller_review")),
                 (ne("original_defect_evidence", "verified"), hold("R_ORIGINAL_DEFECT_UNVERIFIED")),
                 (ALWAYS, full("R_CARRIER_DAMAGE_PRESERVES_REMEDY" if core else "R_POST_RETURN_LIABILITY"))]
        order = ("inspection_cause",)
    elif s in {"category_exclusion_seller_fault_override", "policy_seller_fault_override", "frontier_override_window"}:
        override = ne("seller_fault_event", "none") if s == "category_exclusion_seller_fault_override" else fault
        rules = [(override, full("R_SELLER_FAULT_OVERRIDE")), (ALWAYS, deny("R_FINAL_SALE_EXCLUSION"))]
        order = ("seller_fault_event",)
    elif s in {"evidence_contradiction", "policy_evidence_conflict", "intake_evidence_branch"}:
        core = s == "evidence_contradiction"
        extension = s == "intake_evidence_branch"
        left = "customer_photo_status" if extension else "customer_evidence"
        rules = [(NOT(ALL(eq(left, "verified_mismatch"), eq("warehouse_inspection", "verified_mismatch"))), hold("R_EXTENSION_EVIDENCE_CONFLICT" if extension else "R_EVIDENCE_CONFLICT" if core else "R_EVIDENCE_CONFLICT_REVIEW", "seller_review")),
                 (ALWAYS, full("R_EXTENSION_EVIDENCE_ALIGNED" if extension else "R_ALIGNED_VERIFIED_MISMATCH" if core else "R_VERIFIED_SELLER_FAULT_REFUND"))]
        order = (left, "warehouse_inspection")
    elif s in {"policy_identity_override", "policy_identity_followup", "intake_identity_branch", "frontier_hard_evidence_stop"}:
        extension = s == "intake_identity_branch"
        rules = [(identity, hold("R_EXTENSION_IDENTITY_REVIEW" if extension else "R_IDENTITY_HOLD", "identity_review")),
                 (NOT(verified), hold("R_DEFECT_VERIFICATION")),
                 (ALWAYS, full("R_EXTENSION_IDENTITY_CLEAR" if extension else "R_VERIFIED_DEFECT_REFUND"))]
        order = identity_order
    elif s == "policy_perishable_verification":
        rules = [(eq("spoilage_evidence", "verified"), full("R_VERIFIED_SELLER_FAULT_REFUND")), (ALWAYS, hold("R_PERISHABLE_VERIFICATION"))]
        order = ("spoilage_evidence",)
    elif s in {"policy_bundle_cap", "policy_bundle_boundary", "frontier_piecewise_amount", "frontier_hard_piecewise_tax"}:
        rules = [(ne("evidence_status", "verified"), hold("R_DEFECT_VERIFICATION")),
                 (ALWAYS, partial("R_COMPONENT_CAP", "paid_component_allocation", "seller", "piecewise" in s))]
        order = ("evidence_status",)
    elif s in {"policy_payment_hold_precedence", "policy_payment_reconcile", "frontier_branch_reversal", "frontier_precedence_ladder", "frontier_hard_payment_identity"}:
        payment_test = ANY(payment, Predicate("in", ("prior_refund_state",), ("refund_pending", "issued"))) if s in {"policy_payment_reconcile", "frontier_branch_reversal"} else payment
        rules = [(payment_test, hold("R_PAYMENT_HOLD", "payment_review"))]
        if s in {"frontier_precedence_ladder", "frontier_hard_payment_identity"}:
            rules.append((identity, hold("R_IDENTITY_HOLD", "identity_review")))
        rules += [(NOT(verified), hold("R_DEFECT_VERIFICATION")), (ALWAYS, full("R_VERIFIED_DEFECT_REFUND"))]
        order = ("chargeback_state",)
    elif s in {"policy_evidence_inconclusive", "frontier_evidence_provenance", "frontier_hard_evidence_reversal"}:
        rules = [(NOT(evidence), hold("R_EVIDENCE_CONFLICT_REVIEW", "seller_review")), (ALWAYS, full("R_VERIFIED_SELLER_FAULT_REFUND"))]
        order = ("customer_evidence", "warehouse_inspection", "listing_snapshot")
    elif s == "frontier_hard_authority_flip":
        corroborated = ALL(eq("customer_evidence", "verified_mismatch"), eq("warehouse_inspection", "verified_mismatch"), compare("eq", "inspection_serial", "order_serial"))
        rules = [(eq("serial_registry", "mismatch"), hold("R_IDENTITY_HOLD", "identity_review")),
                 (NOT(corroborated), hold("R_EVIDENCE_CONFLICT_REVIEW", "seller_review")), (ALWAYS, full("R_VERIFIED_DEFECT_REFUND"))]
        order = ("serial_registry", "customer_evidence", "warehouse_inspection")
    elif s == "frontier_hard_window_override":
        excluded = ANY(eq("category_final_sale", True), ALL(eq("return_reason", "buyer_remorse"), Predicate("gt", ("return_request_day",), 30)))
        rules = [(fault, full("R_SELLER_FAULT_OVERRIDE")), (excluded, deny("R_FINAL_SALE_EXCLUSION")), (ALWAYS, full("R_RETURN_WINDOW", "customer"))]
        order = ("seller_fault_event", "return_request_day", "return_reason")
    elif s == "frontier_hard_override_liability":
        rules = [(eq("inspection_cause", "buyer_caused"), hold("R_POST_RETURN_LIABILITY", "seller_review")),
                 (ALL(fault, eq("original_defect_evidence", "verified")), full("R_SELLER_FAULT_OVERRIDE")),
                 (eq("category_final_sale", True), deny("R_FINAL_SALE_EXCLUSION")), (ALWAYS, hold("R_DEFECT_VERIFICATION"))]
        order = ("inspection_cause", "seller_fault_event", "original_defect_evidence")
    elif s == "frontier_hard_refund_reconciliation":
        rules = [(NOT(verified), hold("R_DEFECT_VERIFICATION")),
                 (compare("le", "full_refund_cents", "settled_refund_cents"), hold("R_PAYMENT_HOLD", "payment_review")),
                 (ALWAYS, Outcome("R_VERIFIED_DEFECT_REFUND", "eligible", "full_refund", "execute_refund", "residual", "seller", ("settled_refund_cents",)))]
        order = ("defect_evidence",)
    elif s in {"payments_proportional_tender", "payments_three_tender_rounding"}:
        rules = [(ne("evidence_status", "verified"), hold("R_EXTENSION_COMPONENT_UNVERIFIED")),
                 (ALWAYS, partial("R_EXTENSION_PROPORTIONAL_TENDER" if s == "payments_proportional_tender" else "R_EXTENSION_THREE_TENDER_ROUNDING", "component_catalog_value"))]
        order = ("evidence_status",)
    elif s in {"payments_idempotency_retry", "payments_residual_waterfall", "payments_prior_refund_reconciliation", "payments_rail_fallback"}:
        rules = [(NOT(verified), hold("R_EXTENSION_DEFECT_UNVERIFIED")), (ALWAYS, full("R_EXTENSION_VERIFIED_DEFECT"))]
        order = ("defect_evidence",)
    else:
        raise ValueError(f"No public branch specification: {s}")
    return BranchSpec(s, tuple(Branch(p, o) for p, o in rules), order)


def public_inputs(price: float, tax: float) -> dict:
    return dict(item_net_price=price, allocated_tax=tax, full_refund_cents=int(round(round(price + tax, 2) * 100)))
