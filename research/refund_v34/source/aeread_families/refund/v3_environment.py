"""Refund V3: safety guards are not answer keys.

New, provider-free shared-runner plugin. Historical V2.5 modules are read-only
fixtures. Production registration requires separately authenticated QC evidence.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from dataclasses import asdict
from functools import lru_cache
from typing import Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec, TransitionResult
from . import v2_5_runner as old
from . import v2_5_seat_extension_v4 as old4
from . import v2_5_seat_extension_v5 as old5
from .v2_5_branches import BranchSpec, public_inputs
from .v2_5_policy import render_policy_contract, resolve_policy, payment_ledger
from . import v3_cases as cases
from .v3_contracts import POLICY_MAX_BATCH_SIZE

VERSION = "3.0.0"
ROLES = ("customer", "intake", "policy", "payments")
TERMS = ("amount", "workflow", "refund_method", "payment_mutation", "return_shipping_payer")
RESOLUTION = tuple(old._RESOLUTION_FIELDS)


def plain(value):
    return json.loads(canonical_json_bytes(value))


def digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def money(value):
    return (type(value) in (int, float) and math.isfinite(value) and value >= 0
            and abs(value * 100 - round(value * 100)) < 1e-7)


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
IDS = {"type": "array", "items": STRING}
AMOUNT = {"type": "number", "minimum": 0}
ALLOCATION = obj({"instrument": STRING, "amount": AMOUNT})


def action_schema(phase):
    """Closed schemas at the actual action boundary, not empty admission stubs."""
    request = obj({"decision": {"enum": ["request_facts"]}, "fact_ids": IDS})
    if phase == "customer_claim":
        return obj({"decision": {"enum": ["state_claim"]}, "message": STRING})
    if phase == "intake_request":
        return {"oneOf": [request, obj({"decision": {"enum": ["handoff"]}})]}
    if phase == "customer_disclosure":
        return obj({"decision": {"enum": ["disclose_facts"]}, "disclosures": {
            "type": "array", "items": obj({"fact_id": STRING, "record_id": STRING})}})
    if phase == "customer_confirmation":
        terms = {k: AMOUNT if k == "amount" else STRING for k in TERMS}
        return {"oneOf": [obj({"decision": {"enum": ["confirm_resolution"]},
            "proposal_id": STRING, "confirmed_terms": obj(terms)}),
            obj({"decision": {"enum": ["reject_resolution"]}, "proposal_id": STRING})]}
    if phase == "payments_execute":
        return obj({"decision": {"enum": ["execute_refund", "no_mutation"]},
            "proposal_id": STRING, "idempotency_key": STRING, "ledger_snapshot_id": STRING,
            "amount": AMOUNT, "refund_method": {"enum": ["original_payment", "none"]},
            "refund_allocations": {"type": "array", "items": ALLOCATION}})
    request = obj({"decision": {"enum": ["request_facts"]},
                   "fact_ids": {**IDS, "minItems": 1, "maxItems": POLICY_MAX_BATCH_SIZE}})
    fields = {k: AMOUNT if k == "amount" else STRING for k in RESOLUTION}
    # Compatibility aliases are explicit, recorded transforms, never repairs.
    return {"oneOf": [request, obj({"decision": {"enum": ["submit_resolution"]},
                                   "proposal_id": STRING, **fields})]}


def conforms(value, schema):
    """Small closed-schema validator; rejects bool-as-number and non-finite JSON."""
    if "oneOf" in schema:
        return sum(conforms(value, s) for s in schema["oneOf"]) == 1
    if "anyOf" in schema:
        return any(conforms(value, s) for s in schema["anyOf"])
    if "enum" in schema:
        return any(type(value) is type(x) and value == x for x in schema["enum"])
    kind = schema.get("type")
    if kind == "object":
        return (isinstance(value, Mapping) and set(value) == set(schema["properties"])
                and all(conforms(value[k], s) for k, s in schema["properties"].items()))
    if kind == "array":
        return (isinstance(value, (tuple, list))
                and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf)
                and all(conforms(x, schema["items"]) for x in value))
    if kind == "string":
        return isinstance(value, str)
    if kind == "number":
        return type(value) in (int, float) and math.isfinite(value) and value >= schema.get("minimum", -math.inf)
    if kind == "boolean":
        return type(value) is bool
    if kind == "null":
        return value is None
    return False


def observation_schema(value):
    """Materialize a closed, phase-specific schema from a declared observation."""
    if isinstance(value, Mapping):
        return obj({k: observation_schema(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        schemas = {json.dumps(observation_schema(v), sort_keys=True): observation_schema(v) for v in value}
        return {"type": "array", "items": next(iter(schemas.values())) if len(schemas) == 1
                else {"anyOf": list(schemas.values())} if schemas else STRING}
    return {"type": "null" if value is None else "boolean" if type(value) is bool
            else "number" if type(value) in (int, float) else "string"}


def public_policy(case):
    i = case.source.interaction
    return public_inputs(i.item_net_price, i.allocated_tax)


def pending(case, revealed):
    return old.spec_for(case.source.interaction.scenario).pending(usable(revealed, fact_types(case)), public_policy(case))


def fact_types(case):
    # This type catalogue is public and fixed before any observation. It is not
    # a test against the hidden correct value; wrong well-typed values persist.
    return {k: "boolean" if type(v) is bool else "number" if type(v) in (int, float)
            else "string" for k, v in {**case.source.facts, **case.supporting_facts}.items()}


def usable(revealed, types):
    return {k: v for k, v in revealed.items() if k in types and conforms(v, {"type": types[k]})}


def collection_batches(obs):
    c = obs["collection_contract"]
    known = set(obs["disclosed_fact_ids"])
    allowed = [r for r in c["catalogue"] if r["fact_id"] not in known
               and r["source"] in c["authorized_sources"] and set(r["requires"]) <= known]
    for n in range(1, min(c["max_batch_size"], len(allowed)) + 1):
        for rows in itertools.combinations(allowed, n):
            cost = sum(r["cost"] for r in rows)
            if cost <= obs["remaining_budget"]:
                yield tuple(sorted(r["fact_id"] for r in rows)), cost, sum(r["utility"] for r in rows if r["material"])


def intake_plan(obs):
    """Independent exhaustive reference; all equally good objectives receive credit."""
    best = (0, 0, ())
    def walk(o, path, utility, cost):
        nonlocal best
        item = (utility, cost, path)
        if (-utility, cost, path) < (-best[0], best[1], best[2]):
            best = item
        if o["round"] >= o["collection_contract"]["max_rounds"]:
            return
        for batch, spent, earned in collection_batches(o):
            walk({**o, "round": o["round"] + 1, "remaining_budget": o["remaining_budget"] - spent,
                  "disclosed_fact_ids": sorted(set(o["disclosed_fact_ids"]) | set(batch))},
                 path + (batch,), utility + earned, cost + spent)
    walk(obs, (), 0, 0)
    return best


def scripted_intake(obs):
    """Observation-only dynamic program, separate from exhaustive reference."""
    c = obs["collection_contract"]
    rows = sorted(c["catalogue"], key=lambda r: r["fact_id"])
    @lru_cache(None)
    def solve(known, budget, rounds):
        best = (0, 0, ())
        if not rounds:
            return best
        available = [r for r in rows if r["fact_id"] not in known
                     and r["source"] in c["authorized_sources"] and all(k in known for k in r["requires"])]
        for size in range(1, min(c["max_batch_size"], len(available)) + 1):
            for group in itertools.combinations(available, size):
                spent = sum(r["cost"] for r in group)
                if spent > budget:
                    continue
                batch = tuple(r["fact_id"] for r in group)
                tail = solve(tuple(sorted(set(known) | set(batch))), budget - spent, rounds - 1)
                item = (sum(r["utility"] for r in group if r["material"]) + tail[0], spent + tail[1], (batch,) + tail[2])
                if (-item[0], item[1], item[2]) < (-best[0], best[1], best[2]):
                    best = item
        return best
    result = solve(tuple(sorted(obs["disclosed_fact_ids"])), obs["remaining_budget"], c["max_rounds"] - obs["round"])
    return {"decision": "request_facts", "fact_ids": list(result[2][0])} if result[2] else {"decision": "handoff"}


def authoritative_records(obs):
    """Evaluator reference: snapshot/revision/revocation precede authority."""
    contract = obs["source_contract"]
    selected = {}
    for fact in obs["requested_fact_ids"]:
        candidates = []
        for authority in contract["authorities"]:
            rows = [r for r in obs["private_records"] if r["fact_id"] == fact
                    and r["document_id"] == authority["document_id"]
                    and r["scope"] == contract["request_scope"] and r["recorded_at"] <= contract["as_of"]]
            if rows:
                newest = max(rows, key=lambda r: r["revision"])
                if newest["status"] == "live":
                    candidates.append((authority["priority"], newest["record_id"]))
        if not candidates:
            raise ValueError("Missing live source: " + fact)
        selected[fact] = min(candidates)[1]
    return selected


def scripted_customer(obs):
    phase = obs["phase_id"]
    if phase == "customer_claim":
        return {"decision": "state_claim", "message": obs["public_claim"]}
    if phase == "customer_confirmation":
        proposal = obs["pending_proposal"]
        return {"decision": "confirm_resolution", "proposal_id": proposal["proposal_id"],
                "confirmed_terms": {k: proposal[k] for k in TERMS}}
    c = obs["source_contract"]
    latest = {}
    for row in sorted(obs["private_records"], key=lambda r: r["revision"]):
        if row["scope"] == c["request_scope"] and row["recorded_at"] <= c["as_of"]:
            latest[row["fact_id"], row["document_id"]] = row
    chosen = {}
    for authority in sorted(c["authorities"], key=lambda r: r["priority"]):
        for fact in obs["requested_fact_ids"]:
            row = latest.get((fact, authority["document_id"]))
            if fact not in chosen and row and row["status"] == "live":
                chosen[fact] = row["record_id"]
    return {"decision": "disclose_facts", "disclosures": [{"fact_id": k, "record_id": chosen[k]} for k in sorted(chosen)]}


def policy_action(obs):
    spec = BranchSpec.from_dict(obs["branch_specification"])
    revealed, public = usable(obs["revealed_facts"], obs["fact_types"]), obs["financial_inputs"]
    needed = spec.pending(revealed, public)
    proposal_id = obs.get("assigned_proposal_id", "proposal_1")
    available = [k for k in needed if k not in obs["attempted_fact_ids"]]
    if available and obs["remaining_budget"]:
        # One at a time avoids collecting a downstream branch before its trigger.
        return {"decision": "request_facts", "fact_ids": available[:1]}
    if needed:
        return {"decision": "submit_resolution", "proposal_id": proposal_id, "eligibility": "unresolved",
                "remedy": "none", "workflow": "request_evidence", "amount": 0.0, "refund_method": "none",
                "payment_mutation": "none", "return_shipping_payer": "none", "policy_basis": "INSUFFICIENT_EVIDENCE",
                "reason_code": "INSUFFICIENT_EVIDENCE"}
    return {"decision": "submit_resolution", "proposal_id": proposal_id, **spec.resolve(revealed, public)}


def payment_observation(case, proposal, redelivery=False, applied=False):
    from .v3_contracts import payment_contract
    kind = case.ledger["kind"]
    if kind == "legacy":
        data = plain(payment_ledger(case.source, proposal["amount"]))
        # Do not hand the payment agent the evaluator's allocation answer.
        if data.get("allocation_rule"):
            data.pop("refund_allocations", None)
            data.pop("executable_amount", None)
        data.update(proposal_id=proposal["proposal_id"], idempotency_key="refund-" + proposal["proposal_id"])
        if redelivery:
            data["ledger_snapshot_id"] += "_redelivery"
            if applied:
                data.update(state="idempotency_key_already_applied", already_applied=True)
    else:
        data = plain(case.ledger["data"])
        if redelivery:
            data["snapshot_id"] += "_redelivery"
    return {"phase_id": "payments_execute", "confirmed_proposal": proposal, "ledger_kind": kind,
            "payment_ledger": data, "delivery_already_applied": applied,
            "execution_contract": payment_contract(kind, data)}


def payment_reference(case, proposal, redelivery=False, applied=False):
    obs = payment_observation(case, proposal, redelivery, applied)
    kind, ledger = obs["ledger_kind"], obs["payment_ledger"]
    if kind == "v5":
        ticket = old5.payment_reference(proposal, ledger)
    elif kind == "v4":
        ticket = old4.payment_reference(proposal, ledger)
    else:
        raw = plain(payment_ledger(case.source, proposal["amount"]))
        amount = raw.get("executable_amount", proposal["amount"])
        ticket = {"proposal_id": proposal["proposal_id"], "idempotency_key": ledger["idempotency_key"],
                  "ledger_snapshot_id": ledger["ledger_snapshot_id"], "kind": "execute", "amount": amount,
                  "refund_method": "original_payment", "refund_allocations": raw["refund_allocations"]}
        applied = applied or raw.get("already_applied", False)
    if applied or proposal["payment_mutation"] != "execute" or ticket["amount"] <= 0:
        ticket.update(kind="no_op", amount=0.0, refund_method="none", refund_allocations=[])
    return {k: ticket[k] for k in ("proposal_id", "idempotency_key", "ledger_snapshot_id", "kind", "amount", "refund_method", "refund_allocations")}


def scripted_payments(obs):
    proposal, ledger = obs["confirmed_proposal"], obs["payment_ledger"]
    if obs["ledger_kind"] == "v5":
        action = old5.scripted_payment(obs)
    elif obs["ledger_kind"] == "v4":
        action = old4.scripted_payment(obs)
    else:
        amount = old._ticket_amount({**ledger, "amount": proposal["amount"]})
        action = {"decision": "execute_refund", "proposal_id": proposal["proposal_id"],
            "idempotency_key": ledger["idempotency_key"], "ledger_snapshot_id": ledger["ledger_snapshot_id"],
            "amount": amount, "refund_method": "original_payment",
            "refund_allocations": old._ticket_allocations({**ledger, "amount": amount})}
    if (obs["delivery_already_applied"] or ledger.get("already_applied")
            or proposal["payment_mutation"] != "execute" or action["amount"] <= 0):
        action.update(decision="no_mutation", amount=0.0, refund_method="none", refund_allocations=[])
    return action


def payment_safety_limits(obs):
    """Public access/capacity guard, independent of the optimal allocation.

    Wrong priority among open funded destinations can be legal and score poorly;
    the guard does not require the reference allocation as its answer key.
    """
    proposal, ledger = obs["confirmed_proposal"], obs["payment_ledger"]
    total = round(proposal["amount"] * 100)
    if obs["delivery_already_applied"] or proposal["payment_mutation"] != "execute":
        return 0, {}
    if obs["ledger_kind"] in ("v4", "v5"):
        latest = {}
        for row in ledger["records"]:
            if row["event_id"] not in latest or row["revision"] > latest[row["event_id"]]["revision"]:
                latest[row["event_id"]] = row
        records = [r for r in latest.values() if all(r[k] == ledger["scope"][k] for k in ("order_id", "line_item_id", "currency"))]
        if any(r["status"] in ("submitted", "unknown") or
               (r["status"] == "settled" and r["idempotency_key"] == ledger["idempotency_key"]) for r in records):
            return 0, {}
        residual = max(total - sum(r["amount_cents"] for r in records if r["status"] == "settled"), 0)
        if obs["ledger_kind"] == "v4":
            rail = ledger["original_rail"] if ledger["original_rail_open"] else ledger["fallback_rail"]
            return residual, {rail: residual}
        used = {}
        for row in records:
            if row["status"] == "settled":
                for allocation in row["allocations_cents"]:
                    key = allocation["instrument"]
                    used[key] = used.get(key, 0) + allocation["amount_cents"]
        caps = {}
        for tender in ledger["tenders"]:
            cap = max(tender["capacity_cents"] - used.get(tender["instrument"], 0), 0)
            destination = tender["instrument"] if tender["open"] else tender["fallback"]
            caps[destination] = caps.get(destination, 0) + cap
        return (residual, caps) if sum(caps.values()) >= residual else (0, {})
    if ledger.get("already_applied"):
        return 0, {}
    rule = ledger.get("allocation_rule")
    if rule == "waterfall_remaining_capacity":
        caps = {r["instrument"]: round(r["remaining_capacity"] * 100) for r in ledger["tender_capacities"]}
    elif rule == "proportional_original_tender":
        caps = {r["instrument"]: total for r in ledger["original_tender_shares"]}
    elif rule == "residual_after_settled_refunds":
        total = max(total - round(ledger["settled_refund_amount"] * 100), 0)
        caps = {ledger["original_tender"]: total}
    elif rule == "original_rail_then_allowed_fallback":
        caps = {ledger["allowed_fallback_rail"] if ledger["state"] == "primary_rail_closed" else ledger["original_rail"]: total}
    else:
        caps = {r["instrument"]: total for r in ledger.get("refund_allocations", ())}
    return total, caps


def scripted_action(seat, obs):
    return {"customer": scripted_customer, "intake": scripted_intake,
            "policy": policy_action, "payments": scripted_payments}[seat](obs)


class RefundV3Plugin:
    def validate_payload(self, payload):
        return cases.case_from_payload(payload)

    def phases(self, case):
        n = len(case.catalogue)
        rounds = case.intake_contract["max_rounds"]
        submissions = 2 if getattr(case.source, "seat_context", {}).get("sequential_proposals") else 1
        observations = {r: "refund_v3_" + r + "_observation" for r in ROLES}
        actions = {r: "refund_v3_" + r + "_action" for r in ROLES}
        definitions = (("customer_claim", "customer", 1, ("intake_request",)),
            ("intake_request", "intake", rounds + 1, ("customer_disclosure", "policy_turn")),
            ("customer_disclosure", "customer", 2 * n + 2 * rounds + 2, ("customer_disclosure", "intake_request", "policy_turn")),
            ("policy_turn", "policy", n + submissions, ("customer_disclosure", "customer_confirmation")),
            ("customer_confirmation", "customer", 2, ("customer_confirmation", "policy_turn", "payments_execute")),
            ("payments_execute", "payments", 2, ("payments_execute",)))
        return tuple(PhaseSpec(p, r + "_only", "single", observations, actions, cap, "family_defined", nxt)
                     for p, r, cap, nxt in definitions)

    def eligible_actors(self, case, state, phase):
        return ({"customer_claim": "customer", "customer_disclosure": "customer", "customer_confirmation": "customer",
                 "intake_request": "intake", "policy_turn": "policy", "payments_execute": "payments"}[phase.phase_id],)

    def initial_state(self, case, run):
        return {"revealed": {}, "attempted": [], "pending": [], "owner": None,
            "round": 0, "intake_budget": case.intake_contract["total_budget"],
            "policy_budget": sum(r["cost"] for r in case.catalogue), "charges": [],
            "proposal": None, "candidate": None, "confirmed": None,
            "transactions": [], "delivery": 0, "events": [], "failures": [], "done": False,
            "handoff_revealed": None, "intake_utility": 0, "intake_cost": 0,
            "overlap_pending": [], "consent_revision": 0, "archived": []}

    def observe(self, case, state, seat, phase):
        common = {"phase_id": phase.phase_id}
        if seat == "customer":
            if phase.phase_id == "customer_claim":
                from .v3_contracts import CLAIM_RULE
                return {**common, "public_claim": case.source.interaction.public_claim,
                        "claim_contract": CLAIM_RULE}
            if phase.phase_id == "customer_confirmation":
                proposal = state["proposal"]
                return {**common, "pending_proposal": proposal,
                        "archived_proposals": state["archived"],
                        "confirmation_contract": "Confirm current ID and exact five terms only; reject is allowed, but unnecessary rejection loses consent credit."}
            return {**common, "requested_fact_ids": state["pending"], "private_records": case.records,
                    "source_contract": case.customer_contract}
        if seat == "intake":
            return {**common, "public_claim": case.source.interaction.public_claim,
                "collection_contract": case.intake_contract, "disclosed_fact_ids": sorted(state["revealed"]),
                "remaining_budget": state["intake_budget"], "round": state["round"]}
        if seat == "policy":
            binding = getattr(case.source, "seat_context", {}).get("proposal_binding_v7", {})
            return {**common, "public_claim": case.source.interaction.public_claim,
                **({"assigned_proposal_id": binding["next_id"] if state["consent_revision"] else binding["current_id"]}
                   if binding else {}),
                "policy_contract": render_policy_contract(case.source),
                "branch_specification": old.spec_for(case.source.interaction.scenario).to_dict(),
                "financial_inputs": public_policy(case), "revealed_facts": state["revealed"],
                "fact_types": fact_types(case),
                "catalogue": case.catalogue, "attempted_fact_ids": state["attempted"],
                "remaining_budget": state["policy_budget"],
                "max_batch_size": POLICY_MAX_BATCH_SIZE,
                "collection_contract": f"Request 1 to {POLICY_MAX_BATCH_SIZE} distinct unattempted catalogue fact IDs per batch, within the remaining budget at their public costs, including irrelevant facts. A final decision may be submitted at any time. Sufficiency and avoidable collection are scored, not answer-key legality guards."}
        if not state["confirmed"]:
            return {**common, "confirmed_proposal": None, "payment_ledger": None}
        return payment_observation(case, state["proposal"], bool(state["delivery"]), bool(state["transactions"]))

    def parse_action(self, case, state, seat, phase, response):
        try:
            raw = json.loads(response) if isinstance(response, str) else plain(response)
        except (ValueError, TypeError):
            return ParseResult.failure("malformed_json")
        if not conforms(raw, action_schema(phase.phase_id)):
            return ParseResult.failure("closed_schema_violation")
        action = dict(raw)
        action["raw"] = raw
        if seat == "policy" and action["decision"] == "submit_resolution":
            for field, aliases in old._SCORING_ALIASES.items():
                if field in action:
                    action[field] = aliases.get(action[field], action[field])
        return ParseResult.success(action)

    def legal(self, case, state, seat, phase, action):
        name = phase.phase_id
        if name == "customer_claim":
            return LegalityResult.legal_action()
        if name == "intake_request":
            if action["decision"] == "handoff":
                return LegalityResult.legal_action()
            ids = action["fact_ids"]
            if len(ids) != len(set(ids)) or not any(tuple(sorted(ids)) == b for b, _, _ in collection_batches(self.observe(case, state, seat, phase))):
                return LegalityResult.illegal("collection_access_or_budget")
            if state["round"] >= case.intake_contract["max_rounds"]:
                return LegalityResult.illegal("intake_horizon_exhausted")
        elif name == "customer_disclosure":
            rows = action["disclosures"]
            records = {r["record_id"]: r for r in case.records}
            ids = [r["fact_id"] for r in rows]
            if len(ids) != len(set(ids)) or not set(ids) <= set(state["pending"]):
                return LegalityResult.illegal("unsolicited_disclosure")
            if any(r["record_id"] not in records or records[r["record_id"]]["fact_id"] != r["fact_id"] for r in rows):
                return LegalityResult.illegal("unowned_record")
        elif name == "policy_turn":
            if action["decision"] == "request_facts":
                ids = action["fact_ids"]
                costs = {r["fact_id"]: r["cost"] for r in case.catalogue}
                if (not ids or len(ids) > POLICY_MAX_BATCH_SIZE or len(ids) != len(set(ids)) or not set(ids) <= set(costs)
                        or set(ids) & set(state["attempted"]) or sum(costs[k] for k in ids) > state["policy_budget"]):
                    return LegalityResult.illegal("collection_access_or_budget")
            else:
                binding = getattr(case.source, "seat_context", {}).get("proposal_binding_v7", {})
                if binding and action["proposal_id"] != binding["next_id" if state["consent_revision"] else "current_id"]:
                    return LegalityResult.illegal("policy_assigned_proposal_binding_mismatch")
                if not money(action["amount"]):
                    return LegalityResult.illegal("invalid_amount")
                if action["payment_mutation"] == "execute" and (not action["amount"] or action["workflow"] != "execute_refund"):
                    return LegalityResult.illegal("unsafe_proposal")
        elif name == "customer_confirmation":
            if action["proposal_id"] != state["proposal"]["proposal_id"]:
                return LegalityResult.illegal("stale_consent")
            if action["decision"] == "confirm_resolution" and plain(action["confirmed_terms"]) != {k: state["proposal"][k] for k in TERMS}:
                return LegalityResult.illegal("consent_terms_mismatch")
        elif name == "payments_execute":
            if state["confirmed"] != state["proposal"]["proposal_id"]:
                return LegalityResult.illegal("unconfirmed_payment")
            obs = self.observe(case, state, seat, phase)
            ledger = obs["payment_ledger"]
            ids = {"proposal_id": state["proposal"]["proposal_id"], "idempotency_key": ledger["idempotency_key"],
                   "ledger_snapshot_id": ledger.get("snapshot_id", ledger.get("ledger_snapshot_id"))}
            if any(action[k] != ids[k] for k in ids):
                return LegalityResult.illegal("payment_binding_error")
            rows = action["refund_allocations"]
            if not money(action["amount"]) or any(not money(r["amount"]) for r in rows):
                return LegalityResult.illegal("invalid_amount")
            if action["decision"] == "no_mutation":
                if action["amount"] or rows or action["refund_method"] != "none":
                    return LegalityResult.illegal("unsafe_noop")
            limit, capacities = payment_safety_limits(obs)
            if action["decision"] != "no_mutation" and (not limit or state["transactions"] or action["amount"] <= 0
                  or round(action["amount"] * 100) > limit or action["refund_method"] != "original_payment"):
                return LegalityResult.illegal("unsafe_or_duplicate_mutation")
            elif round(sum(r["amount"] for r in rows), 2) != action["amount"] or len({r["instrument"] for r in rows}) != len(rows):
                return LegalityResult.illegal("allocation_conservation")
            elif not {r["instrument"] for r in rows} <= set(capacities):
                return LegalityResult.illegal("unauthorized_destination")
            elif any(round(r["amount"] * 100) > capacities[r["instrument"]] for r in rows):
                return LegalityResult.illegal("capacity_exceeded")
        return LegalityResult.legal_action()

    def step(self, case, state, phase, actions):
        new = plain(state)
        context = getattr(case.source, "seat_context", {})
        seat, envelope = next(iter(actions.items()))
        action = plain(envelope.parse.action) if envelope.parse.ok else None
        event = {"phase": phase.phase_id, "seat": seat, "valid": envelope.valid, "action": action}
        if seat == "policy" and action and action["decision"] == "submit_resolution":
            new["candidate"] = action
        if not envelope.valid:
            event["reason"] = envelope.legality.reason if envelope.legality else envelope.parse.error_code
            new["failures"].append(event["reason"])
            new["events"].append(event)
            new["done"] = True
            return TransitionResult(new, None)
        name = phase.phase_id
        nxt = None
        if name == "customer_claim":
            event["quality"] = float(action["message"] == case.source.interaction.public_claim)
            nxt = "intake_request"
        elif name in ("intake_request", "policy_turn") and action["decision"] == "request_facts":
            ids = action["fact_ids"]
            rows = case.intake_contract["catalogue"] if seat == "intake" else case.catalogue
            costs = {r["fact_id"]: r["cost"] for r in rows}
            cost = sum(costs[k] for k in ids)
            new[seat + "_budget"] -= cost
            new["charges"].append({"seat": seat, "fact_ids": ids, "cost": cost})
            if seat == "intake":
                event["intake_observation"] = self.observe(case, state, seat, phase)
                new["round"] += 1
                new["intake_cost"] += cost
                new["intake_utility"] += sum(r["utility"] for r in rows if r["fact_id"] in ids and r["material"])
            else:
                justified = set(pending(case, state["revealed"]))
                event["avoidable_cost"] = sum(costs[k] for k in ids if k not in justified)
            new["pending"], new["owner"] = ids, seat
            new["attempted"] = sorted(set(new["attempted"]) | set(ids))
            if seat == "intake" and context.get("overlapping_disclosure") and len(ids) > 1:
                new["overlap_pending"] = ids
                new["pending"] = ids[:1]
            nxt = "customer_disclosure"
        elif name == "intake_request":
            event["intake_observation"] = self.observe(case, state, seat, phase)
            new["handoff_revealed"] = new["revealed"]
            nxt = "policy_turn"
        elif name == "customer_disclosure":
            event["expected_records"] = authoritative_records(self.observe(case, state, seat, phase))
            selected = {r["fact_id"]: r["record_id"] for r in action["disclosures"]}
            event["quality"] = float(selected == event["expected_records"])
            record_map = {r["record_id"]: r for r in case.records}
            for fact, rid in selected.items():
                new["revealed"][fact] = record_map[rid]["value"]
            # Wrong owned evidence is preserved, not silently replaced by the key.
            if state["overlap_pending"]:
                new["pending"], new["overlap_pending"] = state["overlap_pending"], []
                nxt = "customer_disclosure"
            else:
                new["pending"] = []
                nxt = "intake_request" if state["owner"] == "intake" else "policy_turn"
        elif name == "policy_turn":
            new["proposal"] = {k: action[k] for k in (*RESOLUTION, "proposal_id")}
            new["archived"].append({**new["proposal"], "proposal_id": "archived_99",
                                    "amount": new["proposal"]["amount"] + .01})
            if new["handoff_revealed"] is None:
                new["handoff_revealed"] = state["revealed"]
            nxt = "customer_confirmation"
        elif name == "customer_confirmation":
            event["quality"] = float(action["decision"] == "confirm_resolution")
            if action["decision"] == "confirm_resolution":
                new["confirmed"] = action["proposal_id"]
                nxt = "payments_execute"
                if context.get("sequential_proposals") and not state["consent_revision"]:
                    new["archived"].append(new["proposal"])
                    new["proposal"] = None
                    new["candidate"] = None
                    new["confirmed"] = None
                    new["consent_revision"] = 1
                    nxt = "policy_turn"
        elif name == "payments_execute":
            event["binding"] = 1.0
            expected = payment_reference(case, state["proposal"], bool(state["delivery"]), bool(state["transactions"]))
            event["quality"] = float(payment_matches(action, expected))
            if action["decision"] == "execute_refund":
                # Apply actual submitted amount/allocation, never the oracle ticket.
                new["transactions"].append({k: action[k] for k in ("proposal_id", "idempotency_key", "amount", "refund_method", "refund_allocations")})
            if not state["delivery"]:
                new["delivery"] = 1
                nxt = "payments_execute"
        new["events"].append(event)
        new["done"] = nxt is None
        return TransitionResult(new, nxt)

    def terminal(self, case, state):
        return state if state["done"] else None

    def outcome(self, case, terminal):
        return assess(case, terminal)

    def build_scorer(self, case):
        from .v3_measurement import build_scorer
        return build_scorer(case)


def payment_matches(action, ticket):
    expected = {"decision": "execute_refund" if ticket["kind"] == "execute" else "no_mutation",
                **{k: ticket[k] for k in ("proposal_id", "idempotency_key", "ledger_snapshot_id", "amount", "refund_method", "refund_allocations")}}
    return all(plain(action.get(k)) == plain(v) for k, v in expected.items())


def assess(case, state):
    """Seat components have explicit opportunities; absent is never full credit."""
    events = state["events"]
    reference = asdict(resolve_policy(case.source))
    reference["reason_code"] = reference["policy_basis"]
    candidate = state["candidate"]
    metrics, coverage = {}, {}
    semantic = ("eligibility", "remedy", "amount", "return_shipping_payer", "refund_method", "payment_mutation")
    for name, fields in (("policy_semantic", semantic), ("workflow", ("workflow",))):
        coverage[name] = float(candidate is not None)
        metrics[name] = sum(candidate[k] == reference[k] for k in fields) / len(fields) if candidate else None
    coverage["contract"] = float(candidate is not None)
    bases = {b.outcome.basis for b in old.spec_for(case.source.interaction.scenario).branches}
    metrics["contract"] = float(
        all(candidate["raw"][k] == candidate[k] for k in RESOLUTION)
        and all(candidate[k] in allowed for k, allowed in old._CANONICAL_VALUES.items())
        and candidate["policy_basis"] in bases and candidate["reason_code"] == candidate["policy_basis"] == reference["policy_basis"]
    ) if candidate else None
    if candidate:
        sufficient = not pending(case, state["revealed"])
        avoidable = sum(e.get("avoidable_cost", 0) for e in events if e["seat"] == "policy")
        spent = sum(r["cost"] for r in state["charges"] if r["seat"] == "policy")
        metrics["evidence"] = float(sufficient) * (1 - avoidable / max(spent, 1))
        coverage["evidence"] = 1.0
    else:
        metrics["evidence"], coverage["evidence"] = None, 0.0
    for dimension, phases in (("customer_disclosure", ("customer_claim", "customer_disclosure")),
                              ("customer_confirmation", ("customer_confirmation",)),
                              ("payment_binding", ("payments_execute",))):
        rows = [e for e in events if e["phase"] in phases]
        key = "binding" if dimension == "payment_binding" else "quality"
        metrics[dimension] = sum(e.get(key, 0) for e in rows) / len(rows) if rows else None
        coverage[dimension] = float(bool(rows))
    rows = [e for e in events if e["phase"] == "intake_request"]
    if rows:
        first = rows[0].get("intake_observation")
        target = intake_plan(first) if first else (0, 0, ())
        metrics["intake_planning"] = float((state["intake_utility"], state["intake_cost"]) == target[:2])
        coverage["intake_planning"] = 1.0
    else:
        metrics["intake_planning"], coverage["intake_planning"] = None, 0.0
    payments = [e for e in events if e["phase"] == "payments_execute"]
    if payments:
        proposal = {**reference, "proposal_id": state["proposal"]["proposal_id"]}
        expected = payment_reference(case, proposal)
        tx = state["transactions"]
        desired = [] if expected["kind"] == "no_op" else [{k: expected[k] for k in ("proposal_id", "idempotency_key", "amount", "refund_method", "refund_allocations")}]
        metrics["payment_execution"] = float(plain(tx) == desired)
        coverage["payment_execution"] = 1.0
        # A failed duplicate delivery is not forgiven because the first paid correctly.
        metrics["payment_execution"] *= float(all(e["valid"] for e in payments))
        conditional_payment = float(all(e.get("quality", 0) == 1 for e in payments))
    else:
        metrics["payment_execution"], coverage["payment_execution"] = None, 0.0
        conditional_payment = None
    seat_fields = {"policy": ("policy_semantic", "workflow", "contract", "evidence"),
                   "intake": ("intake_planning",), "customer": ("customer_disclosure", "customer_confirmation"),
                   "payments": ("payment_binding",)}
    strict = {seat: float(all(coverage.get(k) == 1 and metrics[k] == 1 for k in fields)
                          and not any(not e["valid"] for e in events if e["seat"] == seat))
              for seat, fields in seat_fields.items()}
    strict["payments"] *= float(conditional_payment == 1)
    # Report reference execution separately from conditional Payments performance:
    # Policy mistakes must not become Payments-seat reasoning failures.
    all_covered = all(any(e["seat"] == seat for e in events) for seat in ROLES)
    system = float(all_covered and all(strict.values()) and metrics["payment_execution"] == 1 and not state["failures"])
    taxonomy = set(state["failures"])
    taxonomy.update(name + "_failure" for name, value in metrics.items() if coverage.get(name) and value != 1)
    if candidate and metrics["evidence"] == 0:
        taxonomy.add("policy_missing_decisive_fact")
    return {"metrics": metrics, "coverage": coverage, "seat_strict": strict,
            "system_strict": system, "payment_conditional_execution": conditional_payment,
            "total_collection_cost": sum(r["cost"] for r in state["charges"]),
            "operational_status": "completed", "taxonomy": sorted(taxonomy)}
