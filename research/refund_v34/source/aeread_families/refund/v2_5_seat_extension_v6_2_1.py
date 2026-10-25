"""Developmental, provider-free customer/intake extension; historical panels unchanged."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import itertools
import json
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import LegalityResult, TransitionResult, ParseResult
from . import v2_5_seat_extension_v5 as v5

v3 = v5.v3
REVISION = "refund_v25_seat_extension/6.2.1"
VERSION = "2.5.9"
INTAKE_RULE = (
    "Plan over ALL remaining rounds, not just this batch. Only material undisclosed facts from authorized sources "
    "are collectible. ALL prerequisites must be disclosed at ROUND START; this batch cannot unlock itself. "
    "Each fact earns its utility once. Maximize TOTAL collected utility across the remaining horizon within "
    "the remaining TOTAL budget and per-round batch cap. Among equal utilities minimize total cost; then "
    "choose the lexicographically smallest sequence of sorted fact-ID batches. Return ONLY its first batch. "
    "No empty waiting rounds. Replan after disclosure; policy collects remaining evidence after intake finishes."
)
CUSTOMER_RULE = (
    "For EACH requested fact: keep records in request_scope with recorded_at <= as_of. Within each authorized "
    "document select its highest numeric revision BEFORE inspecting status. Revocation is FACT-SCOPED: a latest "
    "revoked record invalidates only this (fact_id, document_id, scope), not other facts in the document. "
    "Never resurrect an older revision for that fact. Choose the live document of lowest authority "
    "priority; priority outranks revision across documents. Copy its exact JSON value/type. Ignore other scopes, "
    "future records and unauthorized documents. Return all and ONLY requested IDs, including explicitly "
    "re-requested IDs. Array order is irrelevant. At confirmation, copy ONLY pending_proposal ID and its five "
    "confirmed_terms; archived proposals are never authoritative, irrespective of ID number or amount."
)


def _batches(contract, known, budget):
    rows = {r["fact_id"]: r for r in contract["catalogue"]}
    eligible = sorted(k for k, r in rows.items() if r["material"] and k not in known
                      and r["source"] in contract["authorized_sources"] and set(r["requires"]) <= set(known))
    for size in range(1, min(contract["max_batch_size"], len(eligible)) + 1):
        for batch in itertools.combinations(eligible, size):
            cost = sum(rows[k]["cost"] for k in batch)
            if cost <= budget:
                yield batch, cost, sum(rows[k]["utility"] for k in batch)


def intake_plan_reference(obs):
    """Exhaustive full-path enumeration, with public-only inputs."""
    c = obs["collection_v6"]
    paths = []
    def enumerate_paths(known, budget, rounds, path, utility, cost):
        paths.append((utility, cost, path))
        if not rounds:
            return
        for batch, spent, reward in _batches(c, known, budget):
            enumerate_paths(set(known) | set(batch), budget - spent, rounds - 1,
                            path + (batch,), utility + reward, cost + spent)
    enumerate_paths(set(obs["disclosed_fact_ids"]), obs["remaining_collection_budget"],
                    c["max_rounds"] - obs["collection_round"], (), 0, 0)
    return min(paths, key=lambda p: (-p[0], p[1], p[2]))[2]


def scripted_intake(obs):
    """Independent backward dynamic program, not a call to the reference/search helper."""
    c = obs["collection_v6"]
    rows = sorted(c["catalogue"], key=lambda r: r["fact_id"])
    @lru_cache(None)
    def solve(known, budget, rounds):
        best = (0, 0, ())
        if rounds == 0:
            return best
        available = [r for r in rows if r["material"] and r["fact_id"] not in known
                     and r["source"] in c["authorized_sources"] and all(k in known for k in r["requires"])]
        for mask in range(1, 1 << len(available)):
            selected = [r for i, r in enumerate(available) if mask & (1 << i)]
            cost = sum(r["cost"] for r in selected)
            if len(selected) > c["max_batch_size"] or cost > budget:
                continue
            batch = tuple(r["fact_id"] for r in selected)
            tail = solve(tuple(sorted(set(known) | set(batch))), budget - cost, rounds - 1)
            candidate = (sum(r["utility"] for r in selected) + tail[0], cost + tail[1], (batch,) + tail[2])
            if (-candidate[0], candidate[1], candidate[2]) < (-best[0], best[1], best[2]):
                best = candidate
        return best
    plan = solve(tuple(sorted(obs["disclosed_fact_ids"])), obs["remaining_collection_budget"],
                 c["max_rounds"] - obs["collection_round"])[2]
    return list(plan[0]) if plan else []


def intake_assessment(obs, ids, valid=True):
    """Objective optimality is distinct from canonical tie-break adherence."""
    c = obs["collection_v6"]
    canonical = intake_plan_reference(obs)
    feasible = {batch: (cost, reward) for batch, cost, reward in
                _batches(c, set(obs["disclosed_fact_ids"]), obs["remaining_collection_budget"])}
    batch = tuple(sorted(ids))
    if not valid or not canonical or len(ids) != len(set(ids)) or batch not in feasible:
        return False, True, "intake_infeasible_request"
    rows = {r["fact_id"]: r for r in c["catalogue"]}
    def objective(plan):
        return (sum(rows[k]["utility"] for b in plan for k in b),
                sum(rows[k]["cost"] for b in plan for k in b))
    spent, _ = feasible[batch]
    next_obs = {**obs, "disclosed_fact_ids": sorted(set(obs["disclosed_fact_ids"]) | set(batch)),
                "remaining_collection_budget": obs["remaining_collection_budget"] - spent,
                "collection_round": obs["collection_round"] + 1}
    forced = (batch,) + intake_plan_reference(next_obs)
    if objective(forced) != objective(canonical):
        return False, True, "intake_suboptimal_horizon_plan"
    if batch != canonical[0]:
        return True, False, "contract_intake_plan_tiebreak"
    return True, True, None


def _allowed_interventions(case):
    """Narrow field-level allowlist; whole-contract masking is never admissible."""
    if "collection_v6" in case.seat_context:
        allowed = {"collection_v6.max_rounds", "collection_v6.total_budget",
                   "collection_v6.max_batch_size", "collection_v6.authorized_sources"}
        allowed.update(f"collection_v6.catalogue.{i}.requires" for i, _ in enumerate(case.seat_context["collection_v6"]["catalogue"]))
        return allowed
    return {"customer_contract_v6.request_scope", "customer_contract_v6.as_of"} | {
        f"customer_contract_v6.authorities.{i}.priority" for i, _ in enumerate(case.seat_context["customer_contract_v6"]["authorities"])}


def _value_at(obj, path):
    for part in path.split("."):
        obj = obj[int(part)] if isinstance(obj, (list, tuple)) else obj[part]
    return obj


def disclosure_reference(obs):
    c = obs["customer_contract_v6"]
    result = {}
    for fact in obs["requested_fact_ids"]:
        candidates = []
        for authority in c["authorities"]:
            rows = [r for r in obs["private_fact_records"] if r["fact_id"] == fact
                    and r["document_id"] == authority["document_id"] and r["scope"] == c["request_scope"]
                    and r["recorded_at"] <= c["as_of"]]
            if not rows:
                continue
            newest = max(rows, key=lambda r: r["revision"])
            if newest["status"] == "live":
                candidates.append((authority["priority"], newest))
        if not candidates:
            raise ValueError("No live authorized source for requested fact")
        result[fact] = min(candidates, key=lambda x: x[0])[1]["value"]
    return result


def scripted_disclosure(obs):
    """Independent sorted stream reducer; no oracle/private case access."""
    c = obs["customer_contract_v6"]
    latest = {}
    for r in sorted(obs["private_fact_records"], key=lambda x: x["revision"]):
        if r["scope"] == c["request_scope"] and r["recorded_at"] <= c["as_of"]:
            latest[(r["fact_id"], r["document_id"])] = r
    chosen = {}
    for authority in sorted(c["authorities"], key=lambda a: a["priority"]):
        for fact in obs["requested_fact_ids"]:
            row = latest.get((fact, authority["document_id"]))
            if fact not in chosen and row and row["status"] == "live":
                chosen[fact] = row["value"]
    if set(chosen) != set(obs["requested_fact_ids"]):
        raise ValueError("Unsatisfiable disclosure")
    return chosen


def intake_observation(case, state):
    c = case.seat_context["collection_v6"]
    return {"phase_id": "intake_request", "public_claim": case.interaction.public_claim,
            "available_fact_ids": sorted(case.facts), "disclosed_fact_ids": sorted(state.get("revealed_facts", {})), "collection_v6": c,
            "remaining_collection_budget": state.get("collection_budget", c["total_budget"]),
            "collection_round": state.get("collection_round", 0)}


def build_panels(seed=301, include_holdout=False):
    sources = v3.build_panels(seed)
    base = next(c for c in sources["customer"] if c.interaction.scenario == "policy_identity_override")
    ids = list(v3.spec_for(base.interaction.scenario).fact_ids())
    intake = []
    mechanisms = ["horizon", "budget", "permission", "batch_capacity", "dependency", "hidden_invariance"]
    if include_holdout:
        mechanisms.append("permission_horizon_holdout")
    for mechanism in mechanisms:
        rows = [{"fact_id": k, "material": True, "source": "order", "requires": [], "cost": 1,
                 "utility": (1, 20, 8, 7)[i] if i < 4 else 2} for i, k in enumerate(ids)]
        rows[1]["requires"] = [ids[0]]
        rows.append({"fact_id": "document_count", "material": False, "source": "order", "requires": [], "cost": 1, "utility": 999})
        contract = {"catalogue": rows, "authorized_sources": ["order", "inspection"], "max_batch_size": 1,
                    "total_budget": 2, "max_rounds": 2, "rule": INTAKE_RULE}
        if mechanism == "horizon":
            path, values = "max_rounds", (1, 2)
        elif mechanism == "budget":
            path, values = "total_budget", (1, 2)
        elif mechanism in ("permission", "permission_horizon_holdout"):
            rows[0]["source"] = "inspection"
            if "holdout" in mechanism:
                contract["max_rounds"] = 3; contract["total_budget"] = 3
                rows[2]["requires"] = [ids[1]]; rows[2]["utility"] = 40
            path, values = "authorized_sources", (["order"], ["order", "inspection"])
        elif mechanism == "batch_capacity":
            contract["max_rounds"] = 1
            path, values = "max_batch_size", (1, 2)
        elif mechanism == "dependency":
            path, values = "catalogue.1.requires", ([], [ids[0]])
        else:
            path, values = None, (0, 1)
        for variant, value in zip(("a", "b"), values):
            current = copy.deepcopy(contract)
            facts = dict(base.facts)
            if path:
                v5._set_path(current, path, value)
            else:
                facts["document_count"] = value
            interaction = replace(base.interaction, case_id=f"seat_v621.intake.{mechanism}.{variant}.{seed:06d}",
                                  pair_id=f"seat_v621_intake_{mechanism}", variant=variant, facts=facts,
                                  changed_fact_ids=() if path else ("document_count",))
            intake.append(v3.SeatCase(interaction, base.product_category, {"panel": "intake_v6", "pair_kind": "intake_v5",
                "mechanism": mechanism, "held_out": "holdout" in mechanism,
                "pair_effect": "observable_action_change" if path else "hidden_invariance",
                "stratum": "frontier" if "holdout" in mechanism else "composed" if mechanism in ("permission", "dependency") else "standard",
                "changed_public_fields": ["collection_v6." + path] if path else [],
                "collection_v5": current, "collection_v6": current}))
    customers = []
    mechanisms = ["scope_binding", "asof_revision", "revocation_fallback", "authority_precedence"]
    if include_holdout:
        mechanisms.append("revocation_scope_holdout")
    for mechanism in mechanisms:
        scenario = {"scope_binding": "policy_identity_override", "asof_revision": "policy_bundle_boundary",
                    "revocation_fallback": "policy_evidence_inconclusive", "authority_precedence": "policy_payment_reconcile",
                    "revocation_scope_holdout": "policy_identity_followup"}[mechanism]
        pair = sorted((c for c in sources["customer"] if c.interaction.scenario == scenario), key=lambda c: c.interaction.variant)
        contract = {"request_scope": "order_A", "as_of": 2,
                    "authorities": [{"document_id": "primary", "priority": 0}, {"document_id": "backup", "priority": 1}],
                    "rule": CUSTOMER_RULE}
        records = []
        changed = set(pair[0].interaction.changed_fact_ids)
        for fact, original in pair[0].facts.items():
            other = pair[1].facts[fact] if fact in changed else original
            def add(doc, scope, revision, time, status, value):
                records.append({"fact_id": fact, "document_id": doc, "scope": scope, "revision": revision,
                                "recorded_at": time, "status": status, "value": value})
            add("primary", "order_A", 1, 1, "live", original)
            if mechanism == "scope_binding":
                add("primary", "order_B", 1, 1, "live", other)
                path, values = "request_scope", ("order_A", "order_B")
            elif mechanism == "asof_revision":
                add("primary", "order_A", 2, 2, "live", other)
                path, values = "as_of", (1, 2)
            elif mechanism in ("revocation_fallback", "revocation_scope_holdout"):
                if fact in changed:
                    add("primary", "order_A", 2, 2, "revoked", None)
                add("backup", "order_A", 1, 1, "live", other)
                path, values = "as_of", (1, 2)
            else:
                add("backup", "order_A", 99, 1, "live", other)
                path, values = "authorities.0.priority", (0, 2)
            add("primary", "foreign_order", 100, 1, "live", "out_of_scope")
            add("primary", "order_A", 101, 9, "live", "future")
            add("unauthorized", "order_A", 102, 1, "live", "unauthorized")
            if "holdout" in mechanism:
                add("backup", "foreign_order", 103, 1, "revoked", None)
        records = records[seed % len(records):] + records[:seed % len(records)]
        for variant, value, source in zip(("a", "b"), values, pair):
            c = copy.deepcopy(contract); v5._set_path(c, path, value)
            interaction = replace(pair[0].interaction, case_id=f"seat_v621.customer.{mechanism}.{variant}.{seed:06d}",
                                  pair_id=f"seat_v621_customer_{mechanism}", variant=variant, facts=dict(source.facts))
            customers.append(v3.SeatCase(interaction, pair[0].product_category, {"panel": "customer_v6", "pair_kind": "customer_v5",
                "mechanism": mechanism, "held_out": "holdout" in mechanism, "pair_effect": "disclosure_value_change",
                "stratum": "frontier" if "holdout" in mechanism else "composed" if mechanism == "revocation_fallback" else "standard",
                "changed_public_fields": ["customer_contract_v6." + path], "customer_contract_v6": c,
                "private_records_v6": records, "customer_record_provenance": True, "confirmation_terms": True,
                "overlapping_disclosure": True, "proposal_supersession": True}))
    panels = {"intake": tuple(intake), "customer": tuple(customers)}
    admit_panels(panels)
    return panels


def admit_panels(panels):
    cases = [c for group in panels.values() for c in group]
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("Unique nonempty V6 cases required")
    pairs = {}
    for case in cases:
        v3.legacy.validate_case_domains(case)
        v3.legacy.validate_resolution_invariants(case, v3.resolve_policy(case))
        spec = v3.spec_for(case.interaction.scenario)
        compiled = spec.resolve(case.facts, v3.public_inputs(case.interaction.item_net_price, case.interaction.allocated_tax))
        reference = asdict(v3.resolve_policy(case)); expected = {k: reference[k] for k in v3.legacy._RESOLUTION_FIELDS if k != "reason_code"}
        expected["reason_code"] = reference["policy_basis"]
        if compiled != expected:
            raise ValueError("Rendered policy/reference disagreement")
        pairs.setdefault(case.interaction.pair_id, []).append(case)
        ctx = case.seat_context
        if "collection_v6" in ctx:
            c = ctx["collection_v6"]; rows = c["catalogue"]
            ids = {r["fact_id"] for r in rows}
            if len(ids) != len(rows) or len(rows) > 8 or not ids <= set(case.facts):
                raise ValueError("Invalid bounded catalogue")
            if ctx["collection_v5"] != c or c["rule"] != INTAKE_RULE:
                raise ValueError("Conflicting collection contracts")
            if c["max_rounds"] not in (1, 2, 3) or c["max_batch_size"] not in (1, 2, 3) or type(c["total_budget"]) is not int or not 0 < c["total_budget"] <= 12:
                raise ValueError("Invalid bounded horizon/budget")
            material = {r["fact_id"] for r in rows if r["material"]}
            if not material <= set(spec.fact_ids()):
                raise ValueError("Irrelevant material fact")
            reached = set()
            for r in rows:
                if type(r["cost"]) is not int or r["cost"] <= 0 or type(r["utility"]) is not int or r["utility"] <= 0 or not set(r["requires"]) <= material:
                    raise ValueError("Invalid cost/utility/dependency")
            for _ in rows:
                reached |= {r["fact_id"] for r in rows if set(r["requires"]) <= reached}
            if reached != ids:
                raise ValueError("Cyclic dependencies")
            if not intake_plan_reference(intake_observation(case, {})):
                raise ValueError("No feasible first batch")
        else:
            c = ctx["customer_contract_v6"]; records = ctx["private_records_v6"]
            auth = c["authorities"]
            if c["rule"] != CUSTOMER_RULE or len({r["priority"] for r in auth}) != len(auth) or len({r["document_id"] for r in auth}) != len(auth):
                raise ValueError("Ambiguous authority")
            if type(c["as_of"]) is not int or not isinstance(c["request_scope"], str):
                raise ValueError("Invalid snapshot")
            keys = [(r["fact_id"], r["document_id"], r["scope"], r["revision"]) for r in records]
            if len(keys) != len(set(keys)):
                raise ValueError("Ambiguous record revision")
            for r in records:
                if r["fact_id"] not in case.facts or r["status"] not in ("live", "revoked") or type(r["revision"]) is not int or r["revision"] < 1 or type(r["recorded_at"]) is not int:
                    raise ValueError("Invalid record")
            obs = {"requested_fact_ids": list(case.facts), "private_fact_records": records, "customer_contract_v6": c}
            if canonical_json_bytes(disclosure_reference(obs)) != canonical_json_bytes(dict(case.facts)):
                raise ValueError("Customer authoritative facts disagree with case")
    for pair in pairs.values():
        if len(pair) != 2 or {c.interaction.variant for c in pair} != {"a", "b"}:
            raise ValueError("Exactly two variants required")
        a, b = pair
        changed = {k for k in a.facts if canonical_json_bytes(a.facts[k]) != canonical_json_bytes(b.facts[k])}
        if changed != set(a.interaction.changed_fact_ids) or changed != set(b.interaction.changed_fact_ids):
            raise ValueError("Undeclared private fact change")
        x, y = asdict(a), asdict(b)
        declared = a.seat_context["changed_public_fields"]
        if declared != b.seat_context["changed_public_fields"]:
            raise ValueError("Inconsistent declared public change")
        invariance = a.seat_context["pair_effect"] == "hidden_invariance"
        if invariance:
            if declared or not changed or "collection_v6" not in a.seat_context:
                raise ValueError("Invariance requires private-only intervention")
        else:
            if len(declared) != 1 or declared[0] not in _allowed_interventions(a):
                raise ValueError("Exactly one allowed field-level public intervention required")
            if canonical_json_bytes(_value_at(a.seat_context, declared[0])) == canonical_json_bytes(_value_at(b.seat_context, declared[0])):
                raise ValueError("Declared intervention must actually change")
        for raw in (x, y):
            raw["interaction"].pop("case_id"); raw["interaction"].pop("variant")
            for fact in changed:
                raw["interaction"]["facts"][fact] = None
            for path in declared:
                v5._set_path(raw["seat_context"], path, None)
                if path.startswith("collection_v6."):
                    v5._set_path(raw["seat_context"], path.replace("collection_v6.", "collection_v5."), None)
        if x != y:
            raise ValueError("Pair changes beyond declared intervention")
        if "collection_v6" in a.seat_context:
            oa, ob = intake_observation(a, {}), intake_observation(b, {})
            pa, pb = intake_plan_reference(oa), intake_plan_reference(ob)
            if a.seat_context["pair_effect"] == "hidden_invariance":
                if oa != ob or pa != pb or v3.resolve_policy(a) != v3.resolve_policy(b):
                    raise ValueError("Broken hidden invariance")
            elif pa[0] == pb[0] or v3.resolve_policy(a) != v3.resolve_policy(b):
                raise ValueError("No first-action contrast / policy changed")
        elif v3.resolve_policy(a) == v3.resolve_policy(b):
            raise ValueError("No downstream policy difference")


TERMS = ("amount", "workflow", "refund_method", "payment_mutation", "return_shipping_payer")
INTAKE_PROMPT = "You are intake. Use only collection_v6, collection_round, remaining_collection_budget and disclosed_fact_ids. Never infer private values or decide a remedy. Return one JSON object with decision=request_facts and requested_fact_ids. " + INTAKE_RULE
CUSTOMER_PROMPT = (
    "You are the customer. Return only JSON using decision, message, revealed_fact_ids, fact_values, proposal_id, confirmed_terms. "
    "message is always required. In customer_claim use decision=state_claim, copy public_claim exactly into message, and revealed_fact_ids=[]. "
    "In customer_disclosure use decision=disclose_facts; emit all and only requested IDs in revealed_fact_ids and fact_values. "
    "When customer_contract_v6 is present select exact typed values from private_fact_records by that contract; otherwise copy private_facts. "
    "In customer_confirmation use decision=confirm_resolution, revealed_fact_ids=[], proposal_id from pending_proposal, "
    "and confirmed_terms containing its five exact fields. Never disclose facts at confirmation. "
    "Never infer policy or invent facts. " + CUSTOMER_RULE
)


def action_schema(seat):
    schema = copy.deepcopy(v3.legacy.SCHEMAS[seat])
    if seat == "customer":
        schema["properties"]["confirmed_terms"] = {
            "type": "object", "additionalProperties": False, "required": list(TERMS),
            "properties": {k: {"type": "number" if k == "amount" else "string"} for k in TERMS}}
        schema["oneOf"] = [
            {"properties": {"decision": {"enum": ["state_claim"]}}, "required": ["decision", "message", "revealed_fact_ids"]},
            {"properties": {"decision": {"enum": ["disclose_facts"]}}, "required": ["decision", "message", "revealed_fact_ids", "fact_values"]},
            {"properties": {"decision": {"enum": ["confirm_resolution"]}}, "required": ["decision", "message", "revealed_fact_ids", "proposal_id", "confirmed_terms"]}]
    return schema


def schema_errors(value, schema, path=""):
    """Validate the complete vocabulary used by these two public schemas."""
    import math
    errors = []
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else types
        checks = {"object": isinstance(value, dict), "array": isinstance(value, list),
                  "string": isinstance(value, str), "null": value is None,
                  "number": type(value) in (int, float) and math.isfinite(value),
                  "integer": type(value) is int, "boolean": type(value) is bool}
        if not any(checks.get(t, False) for t in types):
            return [f"contract_schema_type:{path or '$'}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"contract_schema_enum:{path or '$'}")
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                errors.append(f"contract_schema_missing:{path + key}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                errors.extend(schema_errors(item, props[key], path + key + "."))
            elif schema.get("additionalProperties") is False:
                errors.append(f"contract_schema_extra:{path + key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(schema_errors(item, schema["items"], path + str(i) + "."))
    if "oneOf" in schema:
        branches = [schema_errors(value, branch, path) for branch in schema["oneOf"]]
        if sum(not branch for branch in branches) != 1:
            errors.append(f"contract_schema_branch:{path or '$'}")
            if isinstance(value, dict):
                for branch, branch_errors in zip(schema["oneOf"], branches):
                    if value.get("decision") in branch.get("properties", {}).get("decision", {}).get("enum", ()):
                        errors.extend(branch_errors)
    return sorted(errors)


class ExtensionPlugin(v5.ExtensionPlugin):
    def observe(self, case, state, seat, phase):
        if seat == "intake" and "collection_v6" in case.seat_context:
            return intake_observation(case, state)
        obs = dict(super().observe(case, state, seat, phase))
        if seat == "customer" and "customer_contract_v6" in case.seat_context:
            obs.pop("private_facts", None); obs.pop("source_authorizations", None)
            obs.pop("disclosure_contract", None)
            obs.update(private_fact_records=case.seat_context["private_records_v6"],
                       customer_contract_v6=case.seat_context["customer_contract_v6"])
        if seat == "customer":
            if phase.phase_id == "customer_confirmation":
                obs["confirmation_protocol"] = "Return decision=confirm_resolution, message, revealed_fact_ids=[], proposal_id from pending_proposal, and confirmed_terms containing exactly amount, workflow, refund_method, payment_mutation, return_shipping_payer from pending_proposal. Archived proposals are not current."
            else:
                obs.pop("confirmation_protocol", None)
        return obs

    def parse_action(self, case, state, seat, phase, response):
        parsed = super().parse_action(case, state, seat, phase, response)
        if parsed.ok and seat in ("intake", "customer"):
            errors = schema_errors(v3.legacy._json(response), action_schema(seat))
            action = dict(parsed.action)
            action["_v62_contract_errors"] = errors
            return ParseResult.success(action)
        return parsed

    def legal(self, case, state, seat, phase, action):
        if phase.phase_id == "customer_confirmation":
            if action.get("action") != "confirm_resolution":
                return LegalityResult.illegal("customer_confirmation_action_mismatch")
            proposal = state.get("proposal")
            if not action.get("proposal_id"):
                return LegalityResult.illegal("customer_confirmation_missing_proposal_id")
            if proposal is None or action["proposal_id"] != proposal["proposal_id"]:
                old = {p["proposal_id"] for p in state.get("expired_proposals", ())}
                return LegalityResult.illegal("customer_confirmation_stale_proposal" if action["proposal_id"] in old else "customer_confirmation_proposal_binding_mismatch")
            echoed = action.get("confirmed_terms")
            if not isinstance(echoed, dict) or set(echoed) != set(TERMS) or any(
                not (v3.legacy._valid_amount(echoed[k]) and echoed[k] == proposal[k]) if k == "amount"
                else not v3.legacy._same_fact_value(echoed[k], proposal[k]) for k in TERMS):
                return LegalityResult.illegal("customer_confirmation_terms_mismatch")
        if phase.phase_id == "intake_request" and "collection_v6" in case.seat_context:
            obs = intake_observation(case, state)
            ids = list(action.get("requested_fact_ids", ()))
            feasible = [set(batch) for batch, _, _ in _batches(obs["collection_v6"], set(obs["disclosed_fact_ids"]), obs["remaining_collection_budget"])]
            if obs["collection_round"] >= obs["collection_v6"]["max_rounds"] or action.get("action") != "request_facts" or len(ids) != len(set(ids)) or set(ids) not in feasible:
                return LegalityResult.illegal("intake_infeasible_request")
            return LegalityResult.legal_action()
        return super().legal(case, state, seat, phase, action)

    def step(self, case, state, phase, actions):
        if "collection_v6" not in case.seat_context:
            return self._annotate_contract(super().step(case, state, phase, actions))
        result = v5.v4.ExtensionPlugin.step(self, case, state, phase, actions)
        result = self._annotate_contract(result)
        new = dict(result.state)
        if phase.phase_id == "intake_request":
            new["events"][-1]["intake_v6_observation"] = intake_observation(case, state)
        if new["failures"]:
            return TransitionResult(new, result.next_phase_id)
        if phase.phase_id == "intake_request":
            rows = {r["fact_id"]: r for r in case.seat_context["collection_v6"]["catalogue"]}
            new["collection_budget"] -= sum(rows[k]["cost"] for k in new["pending_requested"])
            new["collection_round"] += 1; new["disclosure_owner"] = "intake"
        elif phase.phase_id == "policy_turn":
            new["disclosure_owner"] = "policy"
        elif phase.phase_id == "customer_disclosure" and state["disclosure_owner"] == "intake":
            if intake_plan_reference(intake_observation(case, new)):
                return TransitionResult(new, "intake_request")
        return TransitionResult(new, result.next_phase_id)

    def _annotate_contract(self, result):
        state = dict(result.state)
        events = list(state["events"])
        event = dict(events[-1])
        action = event.get("action", event.get("action_candidate", {}))
        if event["seat"] in ("intake", "customer"):
            event["seat_contract_errors"] = list(action.get("_v62_contract_errors", ()))
            if not action:
                event["seat_contract_errors"] = ["contract_schema_unparseable"]
        events[-1] = event
        state["events"] = events
        return TransitionResult(state, result.next_phase_id)

    def outcome(self, case, terminal):
        projected = json.loads(canonical_json_bytes(terminal))
        assessments = []
        for event in projected["events"]:
            if "intake_v6_observation" in event:
                action = event.get("action", event.get("action_candidate", {}))
                actual = list(action.get("requested_fact_ids", ()))
                semantic, contract, tag = intake_assessment(event["intake_v6_observation"], actual, event["valid"])
                assessments.append((semantic, contract, tag))
                plan = intake_plan_reference(event["intake_v6_observation"])
                ids = actual if semantic else list(plan[0]) if plan else []
                event["intake_observation"] = {"available_fact_ids": ids, "disclosed_fact_ids": [], "collection_contract": {
                    "fact_catalogue": [{"fact_id": k, "material": True, "priority_group": 0} for k in ids], "scoped": False, "max_batch_size": len(ids)}}
        outcome = dict(v5.v4.ExtensionPlugin.outcome(self, case, projected))
        if assessments:
            outcome["intake_fact_request_quality"] = sum(float(a[0]) for a in assessments) / len(assessments)
            intake_tags = {tag for semantic, _, tag in assessments if not semantic}
            outcome["taxonomy_by_dimension"]["intake_fact_request_quality"] = tuple(sorted(intake_tags))
            contract_tags = {tag for _, contract, tag in assessments if not contract}
            if contract_tags:
                outcome["contract"] = 0.0
                outcome["taxonomy_by_dimension"]["contract"] = tuple(sorted(set(outcome["taxonomy_by_dimension"]["contract"]) | contract_tags))
            if intake_tags or contract_tags:
                outcome["end_to_end"] = 0.0
            outcome["taxonomy"] = tuple(sorted(set(terminal["failures"]).union(*outcome["taxonomy_by_dimension"].values())))
        schema_tags = {f"{e['seat']}:{tag}" for e in terminal["events"] for tag in e.get("seat_contract_errors", ())}
        if schema_tags:
            outcome["contract"] = 0.0
            outcome["coverage_by_dimension"]["contract"] = 1.0
            outcome["end_to_end"] = 0.0
            outcome["taxonomy_by_dimension"]["contract"] = tuple(sorted(set(outcome["taxonomy_by_dimension"]["contract"]) | schema_tags))
            outcome["taxonomy"] = tuple(sorted(set(outcome["taxonomy"]) | schema_tags | {"strict_trajectory_incomplete"}))
        return outcome

    def build_scorer(self, case):
        scorer = super().build_scorer(case)
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        leaves = []
        for leaf in scorer.leaves:
            domain = leaf.estimand.validity_domain; ref = leaf.verifier.reference
            leaves.append(replace(leaf, leaf_version=VERSION, estimand=replace(leaf.estimand, estimand_version=VERSION,
                validity_domain=replace(domain, domain_version=VERSION, predicate=replace(domain.predicate, version=VERSION, content_sha256=digest))),
                verifier=replace(leaf.verifier, reference=replace(ref, reference_version=VERSION,
                    implementation=replace(ref.implementation, version=VERSION, content_sha256=digest)))))
        return replace(scorer, leaves=tuple(leaves))


def seat_strict(outcome, terminal, seat):
    """Active-seat contract failures never penalize an unrelated active seat."""
    phases = {"intake": {"intake_request"}, "customer": {"customer_claim", "customer_disclosure", "customer_confirmation"}}[seat]
    events = [e for e in terminal["events"] if e["phase"] in phases]
    if not events:
        raise ValueError("Active seat not observed")
    if any(not e["valid"] or e.get("seat_contract_errors") for e in events):
        return 0
    if seat == "intake":
        return int(outcome["intake_fact_request_quality"] == 1 and
                   "contract_intake_plan_tiebreak" not in outcome["taxonomy_by_dimension"]["contract"])
    if {e["phase"] for e in events} != phases:
        raise ValueError("Customer lifecycle interrupted elsewhere")
    return int(outcome["customer_disclosure_integrity"] == 1 and outcome["customer_confirmation_integrity"] == 1)


class ScriptedProvider(v5.ScriptedProvider):
    async def complete(self, request):
        inp = json.loads(request.input_text); obs, role = inp["observation"], inp["role"]
        if role == "intake" and "collection_v6" in obs:
            action = {"decision": "request_facts", "requested_fact_ids": scripted_intake(obs)}
        elif role == "customer" and "customer_contract_v6" in obs and inp["phase_id"] == "customer_disclosure":
            action = {"decision": "disclose_facts", "revealed_fact_ids": obs["requested_fact_ids"], "fact_values": scripted_disclosure(obs)}
        else:
            response = await super().complete(request)
            if role != "customer":
                return response
            action = json.loads(response.output_text)
        if role == "customer":
            action.setdefault("message", "Here are the requested facts." if inp["phase_id"] == "customer_disclosure" else "I confirm the current resolution.")
            if inp["phase_id"] == "customer_confirmation":
                action["confirmed_terms"] = {k: obs["pending_proposal"][k] for k in TERMS}
        errors = schema_errors(action, action_schema(role)) if role in ("customer", "intake") else []
        if errors:
            raise ValueError("Scripted schema mismatch: " + str(errors))
        return v3.legacy.ProviderResult("seat_v621_scripted:" + request.provider_call_id, request.model,
            request.revision or request.model, json.dumps(action), "stop", 0, 0, 0, 0.0, {"reference": True})


def build_run(cases, active_agents=("policy",), provider="scripted", model="refund-v25-scripted", provider_revision=REVISION):
    admit_panels({"selected": cases})
    template = v5.build_run(v5.build_panels(cases[0].interaction.world_seed)["customer"], active_agents, provider, model, provider_revision)
    family = template.plan.families[0]; plugin = ExtensionPlugin()
    digest = hashlib.sha256(Path(v5.__file__).read_bytes()).hexdigest()
    pins = tuple(v3.legacy._pin(p.component_id, p.kind, Path(__file__), VERSION) if p.sha256 == digest else p for p in template.plan.implementation_pins)
    dep = v3.legacy._pin("refund_v25_seat_extension_v5_dependency", "reference", Path(v5.__file__), "2.5.5")
    pins += (dep,)
    family = replace(family, scoring=replace(family.scoring, reference_provider_ids=family.scoring.reference_provider_ids + (dep.component_id,)))
    registry = PluginRegistry(); registry.register(family, plugin, contribution=v3.legacy._contribution(),
        evidence_root=getattr(v3.legacy, "QC_ROOT", v3.legacy.ROOT / "cases/refund_v2"))
    manifests = []
    for case in cases:
        raw = json.loads(canonical_json_bytes(v3.legacy._case_manifest(case)))
        raw["episode"]["max_logical_actions"] = max(36, v3.collection_bounds(case)["whole_case"] + 10)
        raw["payload"].update(collection_contract=v3.collection_contract(case), design_revision=REVISION)
        raw["payload"]["semantic_case_sha256"] = hashlib.sha256(canonical_json_bytes({"case": asdict(case), "revision": REVISION})).hexdigest()
        raw["provenance"].update(generator_version=VERSION, review_status="generated")
        raw["content_sha256"] = case_content_sha256(raw); manifests.append(CaseManifest.from_dict(raw))
    prompts = dict(template.prompt_sources)
    prompts[v3.legacy.PROMPT_IDS["intake"]] = INTAKE_PROMPT
    prompts[v3.legacy.PROMPT_IDS["customer"]] = CUSTOMER_PROMPT
    roles = {prompt_id: seat for seat, prompt_id in v3.legacy.PROMPT_IDS.items()}
    profiles = tuple(replace(p, harness=replace(p.harness, config={**p.harness.config, "output_schema": action_schema(roles[p.prompt.prompt_id])}) if roles[p.prompt.prompt_id] in ("customer", "intake") else p.harness,
        prompt=replace(p.prompt, sha256=hashlib.sha256(prompts[p.prompt.prompt_id].encode()).hexdigest())) for p in template.plan.agent_profiles)
    harnesses = HarnessRegistry()
    for h in template.harnesses.values():
        harnesses.register(h)
    suite = "refund_v25_seat_extension_v6_2_1"
    plan = resolve_run_plan(families=(family,), cases=tuple(manifests), suite=replace(template.plan.suite, suite_id=suite, case_ids=tuple(c.case_id for c in manifests)),
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks, analysis=template.plan.analysis, agent_profiles=profiles,
        run_spec=replace(template.plan.run_spec, suite_id=suite), registry=registry, implementation_pins=pins, harness_registry=harnesses,
        provider_capabilities={provider: v5.ProviderCapabilities(False, False, False, True, True, False, None),
                               "scripted": v5.ProviderCapabilities(False, False, False, True, False, False, None)})
    return replace(template, registry=registry, plan=plan, prompt_sources=prompts)


async def conformance(output, seeds=(301, 302, 303)):
    """All four controlled seats, including heldout templates: no provider initialization."""
    if output.exists():
        raise FileExistsError("Fresh offline output required")
    rows = []
    for seed in seeds:
        for panel, cases in build_panels(seed, include_holdout=True).items():
            for seat in v3.legacy.ROLES:
                setup = build_run(cases, active_agents=(seat,))
                for cell in setup.plan.cells:
                    root = output / str(seed) / panel / seat
                    execution = await v3.legacy.execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry, evidence_root=root,
                        prompt_sources=setup.prompt_sources, providers={"scripted": ScriptedProvider()}, pricing=setup.pricing, episode_attempt_ordinal=0, harnesses=setup.harnesses)
                    receipt = v3.legacy.finalize_family_execution(setup=setup, execution=execution)
                    v3.legacy.replay_family_receipt(setup=setup, receipt=receipt, evidence_root=root)
                    if not all(s.primary.value == 1 for s in receipt.scores):
                        raise AssertionError((cell.case_id, seat, [(s.leaf.leaf_id, s.primary.value) for s in receipt.scores]))
                    metrics = next(s.primary.metadata["collaboration_metrics"] for s in receipt.scores if s.leaf.leaf_id == v3.measurement.END_TO_END_LEAF_ID)
                    if not all(m["value"] == 1 and m["coverage"] == 1 for m in metrics.values()):
                        raise AssertionError((cell.case_id, seat, metrics))
                    rows.append({"case_id": cell.case_id, "seat": seat, "full_scores": True, "replayed": True})
        print(json.dumps({"seed": seed, "completed": len(rows)}), flush=True)
    result = {"revision": REVISION, "seeds": list(seeds), "completed": len(rows), "paid_calls": 0,
              "rows": rows, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "all_collaboration_full_with_coverage": True}
    (output / "summary.json").write_bytes(canonical_json_bytes(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(conformance(args.output))

