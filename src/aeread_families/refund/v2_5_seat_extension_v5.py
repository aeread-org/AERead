"""Offline-only V5 collection/provenance/multi-tender environment.

Historical V3/V4 generators and results are deliberately not modified.
Reference reducers and scripted counterparts consume the same public inputs
but have separate implementations. No paid execution entry point is provided.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import itertools
import json
from dataclasses import asdict, replace
from pathlib import Path

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import LegalityResult, TransitionResult
from . import v2_5_seat_extension_v4 as v4

v3 = v4.v3
REVISION = "refund_v25_seat_extension/5"
VERSION = "2.5.5"
PAYMENT_CONTRACT = {
    **v4.CONTRACT, "version": REVISION,
    "statuses": ["settled", "submitted", "unknown", "failed", "reversed"],
    "precedence": [
        "Reduce each event_id to its highest numeric revision BEFORE filtering order/line/currency.",
        "A settled current key in scope blocks redelivery; submitted/unknown in scope blocks execution.",
        "Only settled latest in-scope events contribute; failed/reversed contribute zero. Each settled record allocates its cents to original instrument IDs.",
        "Residual=max(approved cents - sum settled cents,0). Per-instrument available capacity=max(original capacity - settled on that instrument,0).",
        "If total available capacity is below residual, no_mutation (reconciliation required), never truncate the refund.",
        "Otherwise distribute residual by ascending unique tender priority, exhausting each available capacity in turn. Closed original instruments route to their declared fallback; capacity remains attached to the original instrument.",
    ],
    "execution_rule": "Integer cents throughout. Aggregate allocations to the same destination, sorted by destination ID; omit zero allocations. Positive residual uses original_payment; no-op uses amount=0, refund_method=none, refund_allocations=[].",
    "binding_rule": "Copy confirmed proposal_id, current idempotency_key and snapshot_id. Re-evaluate each delivery; current settled key always no-ops. Never recompute policy eligibility.",
}
INTAKE_RULE = (
    "At round start, consider only material undisclosed facts with an authorized source and ALL prerequisites already disclosed. "
    "A prerequisite requested in this batch does not unlock its dependent until the next round. "
    "Select the nonempty subset maximizing sum of utility within remaining TOTAL cost budget and max_batch_size; "
    "ties use the lexicographically smallest sorted fact-ID tuple. Order within output is irrelevant. "
    "After disclosure repeat until max_rounds or no feasible fact remains, then policy collects its remaining branch evidence."
)


def intake_reference(obs):
    contract = obs["collection_v5"]
    disclosed = set(obs["disclosed_fact_ids"])
    rows = [r for r in contract["catalogue"] if r["material"] and r["fact_id"] not in disclosed
            and r["source"] in contract["authorized_sources"] and set(r["requires"]) <= disclosed]
    candidates = []
    for n in range(1, min(contract["max_batch_size"], len(rows)) + 1):
        for subset in itertools.combinations(rows, n):
            if sum(r["cost"] for r in subset) <= obs["remaining_collection_budget"]:
                candidates.append((-sum(r["utility"] for r in subset), tuple(sorted(r["fact_id"] for r in subset))))
    return list(min(candidates)[1]) if candidates else []


def scripted_intake(obs):
    """Independent search with include/exclude recursion, not the reference reducer."""
    c = obs["collection_v5"]; known = set(obs["disclosed_fact_ids"])
    rows = sorted(c["catalogue"], key=lambda r: r["fact_id"])
    best = (0, ())
    def visit(i, budget, chosen, utility):
        nonlocal best
        candidate = (-utility, tuple(chosen))
        if chosen and candidate < best:
            best = candidate
        if i == len(rows) or len(chosen) == c["max_batch_size"]:
            return
        row = rows[i]
        visit(i + 1, budget, chosen, utility)
        if (row["material"] and row["fact_id"] not in known and row["source"] in c["authorized_sources"]
                and all(k in known for k in row["requires"]) and row["cost"] <= budget):
            visit(i + 1, budget - row["cost"], chosen + [row["fact_id"]], utility + row["utility"])
    visit(0, obs["remaining_collection_budget"], [], 0)
    return list(best[1])


def payment_reference(proposal, ledger):
    latest = {}
    for row in ledger["records"]:
        if row["event_id"] not in latest or row["revision"] > latest[row["event_id"]]["revision"]:
            latest[row["event_id"]] = row
    relevant = [r for r in latest.values() if all(r[k] == ledger["scope"][k] for k in ("order_id", "line_item_id", "currency"))]
    applied = any(r["status"] == "settled" and r["idempotency_key"] == ledger["idempotency_key"] for r in relevant)
    held = any(r["status"] in {"submitted", "unknown"} for r in relevant)
    used = {t["instrument"]: 0 for t in ledger["tenders"]}
    for r in relevant:
        if r["status"] == "settled":
            for allocation in r["allocations_cents"]:
                used[allocation["instrument"]] += allocation["amount_cents"]
    residual = max(v4.cents(proposal["amount"]) - sum(used.values()), 0)
    capacities = {t["instrument"]: max(t["capacity_cents"] - used[t["instrument"]], 0) for t in ledger["tenders"]}
    shortfall = sum(capacities.values()) < residual
    if applied or held or shortfall or proposal["payment_mutation"] != "execute":
        residual = 0
    remaining, allocation = residual, {}
    for tender in sorted(ledger["tenders"], key=lambda t: t["priority"]):
        take = min(remaining, capacities[tender["instrument"]]); remaining -= take
        destination = tender["instrument"] if tender["open"] else tender["fallback"]
        allocation[destination] = allocation.get(destination, 0) + take
    return {"proposal_id": proposal["proposal_id"], "idempotency_key": ledger["idempotency_key"],
            "ledger_snapshot_id": ledger["snapshot_id"], "kind": "execute" if residual else "no_op",
            "amount": residual / 100, "refund_method": "original_payment" if residual else "none",
            "refund_allocations": [{"instrument": k, "amount": v / 100} for k, v in sorted(allocation.items()) if v],
            "already_applied": applied, "state": "pending_reconciliation" if held or shortfall else "reconciled"}


def scripted_payment(obs):
    ledger, proposal = obs["payment_ledger"], obs["confirmed_proposal"]
    seen, amounts, blocked = set(), {}, proposal["payment_mutation"] != "execute"
    for row in sorted(ledger["records"], key=lambda r: (r["event_id"], -r["revision"])):
        if row["event_id"] in seen:
            continue
        seen.add(row["event_id"])
        if any(row[k] != ledger["scope"][k] for k in ("order_id", "line_item_id", "currency")):
            continue
        blocked |= row["status"] in ("submitted", "unknown") or (row["status"] == "settled" and row["idempotency_key"] == ledger["idempotency_key"])
        if row["status"] == "settled":
            for a in row["allocations_cents"]:
                amounts[a["instrument"]] = amounts.get(a["instrument"], 0) + a["amount_cents"]
    needed = max(v4.cents(proposal["amount"]) - sum(amounts.values()), 0)
    capacity = [max(t["capacity_cents"] - amounts.get(t["instrument"], 0), 0) for t in ledger["tenders"]]
    if blocked or sum(capacity) < needed:
        needed = 0
    allocations, left = {}, needed
    for t in sorted(ledger["tenders"], key=lambda r: r["priority"]):
        take = min(left, max(t["capacity_cents"] - amounts.get(t["instrument"], 0), 0)); left -= take
        rail = t["instrument"] if t["open"] else t["fallback"]
        allocations[rail] = allocations.get(rail, 0) + take
    return {"decision": "execute_refund" if needed else "no_mutation", "proposal_id": proposal["proposal_id"],
            "idempotency_key": ledger["idempotency_key"], "ledger_snapshot_id": ledger["snapshot_id"],
            "amount": needed / 100, "refund_method": "original_payment" if needed else "none",
            "refund_allocations": [{"instrument": rail, "amount": allocations[rail] / 100} for rail in sorted(allocations) if allocations[rail]]}


def provenance(case):
    rules, records = {}, []
    for i, (fact, value) in enumerate(sorted(case.facts.items())):
        document = f"source_{i % 3}"; revision = 1 + (i + case.interaction.world_seed) % 3
        rules[fact] = {"document_id": document, "max_revision": revision}
        wrong = not value if type(value) is bool else value + 1 if type(value) in (int, float) else "stale:" + str(value)
        records.extend([
            {"fact_id": fact, "document_id": document, "revision": revision, "revoked": False, "value": value},
            {"fact_id": fact, "document_id": document, "revision": revision + 1, "revoked": True, "value": wrong},
            {"fact_id": fact, "document_id": document, "revision": revision + 2, "revoked": False, "value": wrong},
            {"fact_id": fact, "document_id": "unrelated", "revision": 99, "revoked": False, "value": wrong},
        ])
        if revision > 1:
            records.append({"fact_id": fact, "document_id": document, "revision": revision - 1, "revoked": False, "value": wrong})
    shift = case.interaction.world_seed % len(records)
    if case.seat_context["mechanism"] == "source_authority":
        records = [r for r in records if r["document_id"] == "unrelated" or (
            r["document_id"] == rules[r["fact_id"]]["document_id"] and r["revision"] == rules[r["fact_id"]]["max_revision"])]
        shift %= len(records)
    return rules, records[shift:] + records[:shift]


def disclosure_reference(obs):
    values = {}
    for fact in obs["requested_fact_ids"]:
        rule = obs["source_authorizations"][fact]
        eligible = [r for r in obs["private_fact_records"] if r["fact_id"] == fact and r["document_id"] == rule["document_id"]
                    and not r["revoked"] and r["revision"] <= rule["max_revision"]]
        values[fact] = max(eligible, key=lambda r: r["revision"])["value"]
    return values


def build_panels(seed=301, include_holdout=False):
    sources = v3.build_panels(seed)
    identity = next(c for c in sources["customer"] if c.interaction.scenario == "policy_identity_override")
    ids = list(v3.spec_for(identity.interaction.scenario).fact_ids())
    intake = []
    mechanisms = ("dependencies", "source_permission", "budget_tradeoff", "composed_collection")
    if include_holdout:
        mechanisms += ("permission_dependency_holdout",)
    for mechanism in mechanisms:
        catalogue = [{"fact_id": k, "material": True, "source": "order" if i < 2 else "inspection",
                      "requires": [], "cost": 1, "utility": 8 - i} for i, k in enumerate(ids)]
        catalogue.append({"fact_id": "document_count", "material": False, "source": "order", "requires": [], "cost": 1, "utility": 100})
        contract = {"catalogue": catalogue, "authorized_sources": ["order", "inspection"],
                    "max_batch_size": 2, "total_budget": 4, "max_rounds": 3, "rule": INTAKE_RULE}
        if mechanism in ("dependencies", "composed_collection", "permission_dependency_holdout"):
            catalogue[1]["requires"] = [ids[0]]; catalogue[2]["requires"] = [ids[1]]
        if mechanism == "dependencies":
            path, values = "catalogue.1.requires", ([], [ids[0]])
        elif mechanism in ("source_permission", "permission_dependency_holdout"):
            path, values = "authorized_sources", (["order", "inspection"], ["inspection"])
        else:
            catalogue[0]["cost"] = 2; catalogue[2]["utility"] = 12
            if mechanism == "budget_tradeoff": catalogue[2]["cost"] = 2
            path, values = "total_budget", (3, 4) if mechanism == "budget_tradeoff" else (2, 3)
        for variant, value in zip(("a", "b"), values):
            c = copy.deepcopy(contract); _set_path(c, path, value)
            interaction = replace(identity.interaction, case_id=f"seat_v5.intake.{mechanism}.{variant}.{seed:06d}",
                                  pair_id=f"seat_v5_intake_{mechanism}", variant=variant, changed_fact_ids=())
            intake.append(v3.SeatCase(interaction, identity.product_category, {"panel": "intake_v5", "pair_kind": "intake_v5",
                "mechanism": mechanism, "held_out": "holdout" in mechanism, "changed_public_fields": ["collection_v5." + path], "collection_v5": c}))
    payments = []
    source = next(c for c in sources["common"] if v3.resolve_policy(c).amount > 0)
    total = v4.cents(v3.resolve_policy(source).amount)
    mechanisms = ("scope_capacity", "revision_partial", "pending_release", "rail_fallback", "composed_reversal", "capacity_shortfall")
    if include_holdout:
        mechanisms += ("currency_capacity_holdout",)
    for mechanism in mechanisms:
        ledger = {"scope": {"order_id": f"order_{seed}", "line_item_id": "line_A", "currency": "USD"},
                  "idempotency_key": "refund-proposal_1", "snapshot_id": f"snapshot_{seed}",
                  "tenders": [{"instrument": f"card_{i}", "priority": i, "capacity_cents": total // 3 if i < 2 else total - 2 * (total // 3),
                               "open": i != 0, "fallback": "wallet"} for i in range(3)]}
        record = {**ledger["scope"], "event_id": "partial", "revision": 2, "idempotency_key": "older", "status": "settled",
                  "amount_cents": total // 4 + seed % 7, "allocations_cents": [{"instrument": "card_0", "amount_cents": total // 4 + seed % 7}]}
        ledger["records"] = [record]
        if mechanism == "scope_capacity":
            path, values = "records.0.order_id", ("other_order", ledger["scope"]["order_id"])
        elif mechanism in ("revision_partial", "composed_reversal"):
            ledger["records"].append({**copy.deepcopy(record), "revision": 1, "status": "submitted"})
            path, values = "records.0.status", ("reversed", "settled")
        elif mechanism == "pending_release":
            path, values = "records.0.status", ("submitted", "reversed")
        elif mechanism == "rail_fallback":
            path, values = "tenders.0.open", (False, True)
        elif mechanism == "capacity_shortfall":
            ledger["records"] = []; path, values = "tenders.2.capacity_cents", (ledger["tenders"][2]["capacity_cents"], ledger["tenders"][2]["capacity_cents"] - 1)
        else:
            path, values = "records.0.currency", ("EUR", "USD")
        if mechanism == "composed_reversal":
            ledger["tenders"][1]["open"] = False
            ledger["records"].append({**copy.deepcopy(record), "event_id": "out_of_scope", "order_id": "other_order", "status": "unknown"})
        for variant, value in zip(("a", "b"), values):
            changed = copy.deepcopy(ledger); _set_path(changed, path, value)
            interaction = replace(source.interaction, case_id=f"seat_v5.payments.{mechanism}.{variant}.{seed:06d}",
                                  pair_id=f"seat_v5_payments_{mechanism}", variant=variant, changed_fact_ids=())
            payments.append(v3.SeatCase(interaction, source.product_category, {"panel": "payments_v5", "pair_kind": "payments_v5",
                "mechanism": mechanism, "held_out": "holdout" in mechanism, "changed_public_fields": ["payment_ledger." + path],
                "payment_ledger": changed, "payment_redelivery": True}))
    customers = []
    scenarios = {"policy_identity_override": "source_authority", "policy_bundle_boundary": "typed_partial_request",
                 "policy_evidence_inconclusive": "composed_confirmation"}
    if include_holdout:
        scenarios["policy_identity_followup"] = "source_conflict_holdout"
    for source in sources["customer"]:
        if source.interaction.scenario not in scenarios:
            continue
        mechanism = scenarios[source.interaction.scenario]
        interaction = replace(source.interaction, case_id=f"seat_v5.customer.{mechanism}.{source.interaction.variant}.{seed:06d}",
                              pair_id=f"seat_v5_customer_{mechanism}")
        customers.append(v3.SeatCase(interaction, source.product_category, {"panel": "customer_v5", "pair_kind": "customer_v5",
            "mechanism": mechanism, "held_out": "holdout" in mechanism, "customer_record_provenance": True,
            "confirmation_terms": True, "overlapping_disclosure": mechanism != "source_authority",
            "proposal_supersession": mechanism == "composed_confirmation"}))
    panels = {"intake": tuple(intake), "payments": tuple(payments), "customer": tuple(customers)}
    admit_panels(panels)
    return panels


def _set_path(obj, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    obj[int(parts[-1]) if isinstance(obj, list) else parts[-1]] = copy.deepcopy(value)


def intake_observation(case, state):
    c = case.seat_context["collection_v5"]
    return {**v3.intake_observation(case, state.get("revealed_facts", {})), "collection_v5": c,
            "remaining_collection_budget": state.get("collection_budget", c["total_budget"]),
            "collection_round": state.get("collection_round", 0)}


def admit_panels(panels):
    cases = [c for group in panels.values() for c in group]
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("Unique nonempty V5 cases required")
    pairs = {}
    for case in cases:
        v3.legacy.validate_case_domains(case)
        v3.legacy.validate_resolution_invariants(case, v3.resolve_policy(case))
        if not set(v3.spec_for(case.interaction.scenario).fact_ids()) <= set(case.facts):
            raise ValueError("Missing policy facts")
        compiled = v3.spec_for(case.interaction.scenario).resolve(case.facts, v3.public_inputs(case.interaction.item_net_price, case.interaction.allocated_tax))
        reference = v3.resolve_policy(case)
        expected = {k: getattr(reference, k) for k in v3.legacy._RESOLUTION_FIELDS if k != "reason_code"}
        expected["reason_code"] = reference.policy_basis
        if compiled != expected:
            raise ValueError("Public policy contract and independent reference disagree")
        pairs.setdefault(case.interaction.pair_id, []).append(case)
        kind = case.seat_context["pair_kind"]
        if kind == "intake_v5":
            c = case.seat_context["collection_v5"]; rows = c["catalogue"]
            if len({r["fact_id"] for r in rows}) != len(rows) or not {r["fact_id"] for r in rows} <= set(case.facts):
                raise ValueError("Invalid collection catalogue")
            material = {r["fact_id"] for r in rows if r["material"]}
            if not material <= set(v3.spec_for(case.interaction.scenario).fact_ids()):
                raise ValueError("Non-policy collection material")
            for row in rows:
                if type(row["cost"]) is not int or row["cost"] <= 0 or type(row["utility"]) is not int or row["utility"] <= 0 or not set(row["requires"]) <= material:
                    raise ValueError("Invalid dependency/cost")
            reached = set()
            while True:
                new = reached | {r["fact_id"] for r in rows if set(r["requires"]) <= reached}
                if new == reached: break
                reached = new
            if reached != {r["fact_id"] for r in rows}:
                raise ValueError("Cyclic prerequisites")
            if c["max_batch_size"] not in (1, 2, 3) or type(c["total_budget"]) is not int or c["total_budget"] <= 0 or c["max_rounds"] not in (1, 2, 3):
                raise ValueError("Invalid collection limits")
            if not intake_reference(intake_observation(case, {})):
                raise ValueError("No initial feasible collection")
        elif kind == "payments_v5":
            ledger = case.seat_context["payment_ledger"]; tenders = ledger["tenders"]
            instruments = {t["instrument"] for t in tenders}
            if len(instruments) != len(tenders) or len({t["priority"] for t in tenders}) != len(tenders):
                raise ValueError("Nonunique tender/priority")
            for t in tenders:
                if type(t["capacity_cents"]) is not int or t["capacity_cents"] < 0 or type(t["priority"]) is not int or type(t["open"]) is not bool or not isinstance(t["fallback"], str) or not t["fallback"]:
                    raise ValueError("Invalid tender")
            records = ledger["records"]
            if len({(r["event_id"], r["revision"]) for r in records}) != len(records):
                raise ValueError("Nonunique event revision")
            for r in records:
                if r["status"] not in PAYMENT_CONTRACT["statuses"] or type(r["revision"]) is not int or r["revision"] <= 0 or type(r["amount_cents"]) is not int or r["amount_cents"] < 0:
                    raise ValueError("Invalid ledger record")
                if any(type(a["amount_cents"]) is not int or a["amount_cents"] < 0 or a["instrument"] not in instruments for a in r["allocations_cents"]) or sum(a["amount_cents"] for a in r["allocations_cents"]) != r["amount_cents"]:
                    raise ValueError("Nonconserving prior allocation")
        elif kind != "customer_v5":
            raise ValueError("Unknown V5 pair kind")
    for pair in pairs.values():
        if len(pair) != 2: raise ValueError("Two variants per pair required")
        a, b = pair
        if a.seat_context["pair_kind"] == "customer_v5":
            v3.admit_panel(tuple(pair))
            continue
        x, y = asdict(a), asdict(b)
        declared = a.seat_context["changed_public_fields"]
        if len(declared) != 1 or b.seat_context["changed_public_fields"] != declared:
            raise ValueError("Exactly one public change required")
        for raw in (x, y):
            raw["interaction"].pop("case_id"); raw["interaction"].pop("variant")
            _set_path(raw["seat_context"], declared[0], None)
        if x != y or a.interaction.changed_fact_ids or b.interaction.changed_fact_ids or v3.resolve_policy(a) != v3.resolve_policy(b):
            raise ValueError("Pair changes beyond declared public field")
        if a.seat_context["pair_kind"] == "intake_v5":
            different = intake_reference(intake_observation(a, {})) != intake_reference(intake_observation(b, {}))
        else:
            p = {**asdict(v3.resolve_policy(a)), "proposal_id": "proposal_1"}
            different = payment_reference(p, a.seat_context["payment_ledger"]) != payment_reference(p, b.seat_context["payment_ledger"])
        if not different: raise ValueError("No target-seat contrast")


class ExtensionPlugin(v4.ExtensionPlugin):
    def initial_state(self, case, run):
        state = dict(super().initial_state(case, run))
        if case.seat_context["pair_kind"] == "intake_v5":
            state.update(collection_budget=case.seat_context["collection_v5"]["total_budget"], collection_round=0, disclosure_owner=None)
        return state

    def phases(self, case):
        phases = super().phases(case)
        if case.seat_context["pair_kind"] != "intake_v5": return phases
        return tuple(replace(p, max_logical_actions=3) if p.phase_id == "intake_request" else
                     replace(p, next_phases=p.next_phases + ("intake_request",)) if p.phase_id == "customer_disclosure" else p for p in phases)

    def observe(self, case, state, seat, phase):
        kind = case.seat_context["pair_kind"]
        if seat == "intake" and kind == "intake_v5": return intake_observation(case, state)
        if seat == "payments" and kind == "payments_v5":
            if not state.get("confirmed_proposal_id"):
                return {"phase_id": phase.phase_id, "confirmed_proposal": None, "payment_ledger": None, "execution_contract": PAYMENT_CONTRACT}
            return {"phase_id": phase.phase_id, "confirmed_proposal": state["proposal"],
                    "payment_ledger": state["execution_ticket"]["public_ledger"], "execution_contract": PAYMENT_CONTRACT}
        obs = dict(super().observe(case, state, seat, phase))
        if seat == "customer" and kind == "customer_v5":
            rules, records = provenance(case)
            obs.update(private_fact_records=records, source_authorizations=rules,
                       disclosure_contract={"rule": "For EACH requested fact use its authorized document; exclude revoked records and revisions above its authorization ceiling; take highest remaining numeric revision. Copy exact JSON value/type; disclose no unrequested ID. Array order is irrelevant."})
        return obs

    def legal(self, case, state, seat, phase, action):
        if phase.phase_id == "intake_request" and case.seat_context["pair_kind"] == "intake_v5":
            ids = list(action.get("requested_fact_ids", ()))
            expected = intake_reference(intake_observation(case, state))
            if action.get("action") != "request_facts" or len(ids) != len(set(ids)) or set(ids) != set(expected) or not expected:
                return LegalityResult.illegal("intake_dependency_authorization_budget_error")
            return LegalityResult.legal_action()
        return super().legal(case, state, seat, phase, action)

    def step(self, case, state, phase, actions):
        result = super().step(case, state, phase, actions); new = dict(result.state)
        kind = case.seat_context["pair_kind"]
        if phase.phase_id == "intake_request" and kind == "intake_v5":
            new["events"][-1]["intake_v5_observation"] = intake_observation(case, state)
        if new["failures"]: return TransitionResult(new, result.next_phase_id)
        if kind == "intake_v5":
            if phase.phase_id == "intake_request":
                costs = {r["fact_id"]: r["cost"] for r in case.seat_context["collection_v5"]["catalogue"]}
                new["collection_budget"] -= sum(costs[k] for k in new["pending_requested"])
                new["collection_round"] += 1; new["disclosure_owner"] = "intake"
            elif phase.phase_id == "policy_turn": new["disclosure_owner"] = "policy"
            elif phase.phase_id == "customer_disclosure" and state["disclosure_owner"] == "intake":
                if new["collection_round"] < case.seat_context["collection_v5"]["max_rounds"] and intake_reference(intake_observation(case, new)):
                    return TransitionResult(new, "intake_request")
        if kind == "customer_v5" and phase.phase_id == "policy_turn" and result.next_phase_id == "customer_confirmation" and case.seat_context.get("proposal_supersession"):
            p = new["proposal"]
            new["expired_proposals"] = [{**p, "proposal_id": "proposal_revision99", "draft_status": "abandoned", "workflow": "manual_review"},
                                       {**p, "proposal_id": "proposal_revision10", "draft_status": "abandoned", "amount": p["amount"] + .01},
                                       {**p, "proposal_id": "proposal_revision9", "draft_status": "abandoned", "return_shipping_payer": "customer"}]
        if kind == "payments_v5":
            if phase.phase_id == "customer_confirmation":
                ledger = case.seat_context["payment_ledger"]
                new["execution_ticket"] = {**payment_reference(new["proposal"], ledger), "public_ledger": ledger}
                new["original_execution_ticket"] = new["execution_ticket"]
            elif phase.phase_id == "payments_execute" and result.next_phase_id == "payments_execute":
                ledger = json.loads(canonical_json_bytes(state["execution_ticket"]["public_ledger"]))
                if new["transactions"]:
                    tx = new["transactions"][-1]
                    latest = {}
                    for r in ledger["records"]:
                        if r["event_id"] not in latest or r["revision"] > latest[r["event_id"]]["revision"]:
                            latest[r["event_id"]] = r
                    used = {t["instrument"]: 0 for t in ledger["tenders"]}
                    for r in latest.values():
                        if r["status"] == "settled" and all(r[k] == ledger["scope"][k] for k in ("order_id", "line_item_id", "currency")):
                            for a in r["allocations_cents"]: used[a["instrument"]] += a["amount_cents"]
                    original_allocations, left = [], v4.cents(tx["amount"])
                    for t in sorted(ledger["tenders"], key=lambda t: t["priority"]):
                        take = min(left, max(t["capacity_cents"] - used[t["instrument"]], 0)); left -= take
                        if take: original_allocations.append({"instrument": t["instrument"], "amount_cents": take})
                    assert left == 0
                    ledger["records"].append({**ledger["scope"], "event_id": "current_delivery", "revision": 1,
                        "idempotency_key": ledger["idempotency_key"], "status": "settled", "amount_cents": v4.cents(tx["amount"]),
                        "allocations_cents": original_allocations})
                ledger["snapshot_id"] += "_redelivery"
                new["execution_ticket"] = {**payment_reference(new["proposal"], ledger), "public_ledger": ledger}
        return TransitionResult(new, result.next_phase_id)

    def outcome(self, case, terminal):
        # V3's quality reducer expects a flat admissible batch. Supply a
        # scorer-only projection of the independently derived optimal set.
        projected = json.loads(canonical_json_bytes(terminal))
        for event in projected["events"]:
            if "intake_v5_observation" in event:
                ids = intake_reference(event["intake_v5_observation"])
                event["intake_observation"] = {"available_fact_ids": ids, "disclosed_fact_ids": [], "collection_contract": {
                    "fact_catalogue": [{"fact_id": k, "material": True, "priority_group": 0} for k in ids], "scoped": False, "max_batch_size": len(ids)}}
        return super().outcome(case, projected)

    def build_scorer(self, case):
        scorer = super().build_scorer(case); digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        leaves = []
        for leaf in scorer.leaves:
            domain = leaf.estimand.validity_domain; ref = leaf.verifier.reference
            leaves.append(replace(leaf, leaf_version=VERSION, estimand=replace(leaf.estimand, estimand_version=VERSION,
                validity_domain=replace(domain, domain_version=VERSION, predicate=replace(domain.predicate, version=VERSION, content_sha256=digest))),
                verifier=replace(leaf.verifier, reference=replace(ref, reference_version=VERSION,
                    implementation=replace(ref.implementation, version=VERSION, content_sha256=digest)))))
        return replace(scorer, leaves=tuple(leaves))


class ScriptedProvider(v4.ScriptedProvider):
    async def complete(self, request):
        inp = json.loads(request.input_text); obs, role = inp["observation"], inp["role"]
        if role == "intake" and "collection_v5" in obs:
            action = {"decision": "request_facts", "requested_fact_ids": scripted_intake(obs)}
        elif role == "payments" and "payment_ledger" in obs and "tenders" in obs["payment_ledger"]:
            action = scripted_payment(obs)
        elif role == "customer" and "source_authorizations" in obs and inp["phase_id"] == "customer_disclosure":
            selected = {}
            for row in sorted(obs["private_fact_records"], key=lambda r: r["revision"]):
                rule = obs["source_authorizations"][row["fact_id"]]
                if row["document_id"] == rule["document_id"] and row["revision"] <= rule["max_revision"] and not row["revoked"]:
                    selected[row["fact_id"]] = row["value"]
            ids = obs["requested_fact_ids"]
            action = {"decision": "disclose_facts", "revealed_fact_ids": ids, "fact_values": {k: selected[k] for k in ids}}
        else: return await super().complete(request)
        return v3.legacy.ProviderResult("seat_v5_scripted:" + request.provider_call_id, request.model,
            request.revision or request.model, json.dumps(action), "stop", 0, 0, 0, 0.0, {"reference": True})


def build_run(cases, active_agents=("policy",), provider="scripted", model="refund-v25-scripted", provider_revision=REVISION):
    if len(active_agents) != 1 or active_agents[0] not in v3.legacy.ROLES:
        raise ValueError("Controlled V5 requires exactly one active seat")
    admit_panels({"selected": cases})
    template = v4.build_run(v4.build_panels(cases[0].interaction.world_seed)["customer"], active_agents, provider, model, provider_revision)
    family = template.plan.families[0]; plugin = ExtensionPlugin()
    digest = hashlib.sha256(Path(v4.__file__).read_bytes()).hexdigest()
    pins = tuple(v3.legacy._pin(p.component_id, p.kind, Path(__file__), VERSION) if p.sha256 == digest else p for p in template.plan.implementation_pins)
    dep = v3.legacy._pin("refund_v25_seat_extension_v4_dependency", "reference", Path(v4.__file__), "2.5.4")
    pins += (dep,)
    family = replace(family, scoring=replace(family.scoring, reference_provider_ids=family.scoring.reference_provider_ids + (dep.component_id,)))
    registry = PluginRegistry(); registry.register(family, plugin, contribution=v3.legacy._contribution(), evidence_root=v3.legacy.QC_ROOT)
    manifests = []
    for case in cases:
        raw = json.loads(canonical_json_bytes(v3.legacy._case_manifest(case)))
        raw["episode"]["max_logical_actions"] = max(30, v3.collection_bounds(case)["whole_case"] + 6)
        raw["payload"].update(collection_contract=v3.collection_contract(case), design_revision=REVISION)
        raw["payload"]["semantic_case_sha256"] = hashlib.sha256(canonical_json_bytes({"case": asdict(case), "revision": REVISION})).hexdigest()
        raw["provenance"].update(generator_version=VERSION, review_status="generated")
        raw["content_sha256"] = case_content_sha256(raw); manifests.append(CaseManifest.from_dict(raw))
    prompts = dict(template.prompt_sources)
    prompts[v3.legacy.PROMPT_IDS["intake"]] += " When collection_v5 is present it supersedes collection_contract: obey prerequisites, source authorization, total budget, utility optimization and tie-break; return one request batch only. Never read or guess private values."
    prompts[v3.legacy.PROMPT_IDS["customer"]] += " When source_authorizations is present, follow its per-fact authority, revision ceiling and revocation rules instead of a single global document. Never merge archived draft terms into pending_proposal."
    prompts[v3.legacy.PROMPT_IDS["payments"]] += " In V5 the execution_contract supersedes V4 single-rail rules: use remaining tender capacities and waterfall priorities; combine shared fallback destinations and sort allocations. A reversed latest event contributes zero."
    profiles = tuple(replace(p, prompt=replace(p.prompt, sha256=hashlib.sha256(prompts[p.prompt.prompt_id].encode()).hexdigest())) for p in template.plan.agent_profiles)
    harnesses = HarnessRegistry()
    for h in template.harnesses.values(): harnesses.register(h)
    suite = "refund_v25_seat_extension_v5"
    plan = resolve_run_plan(families=(family,), cases=tuple(manifests), suite=replace(template.plan.suite, suite_id=suite, case_ids=tuple(c.case_id for c in manifests)),
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks, analysis=template.plan.analysis, agent_profiles=profiles,
        run_spec=replace(template.plan.run_spec, suite_id=suite), registry=registry, implementation_pins=pins, harness_registry=harnesses,
        provider_capabilities={provider: ProviderCapabilities(False, False, False, True, True, False, None), "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    return replace(template, registry=registry, plan=plan, prompt_sources=prompts)


async def conformance(output, seeds=(301, 302, 303)):
    if output.exists(): raise FileExistsError("Fresh offline output required")
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
                    assert all(s.primary.value == 1 for s in receipt.scores), (cell.case_id, seat)
                    metrics = next(s.primary.metadata["collaboration_metrics"] for s in receipt.scores if s.leaf.leaf_id == v3.measurement.END_TO_END_LEAF_ID)
                    assert all(m["value"] == 1 and m["coverage"] == 1 for m in metrics.values()), (cell.case_id, seat, metrics)
                    rows.append({"case_id": cell.case_id, "seat": seat, "full_scores": True, "replayed": True})
        print(json.dumps({"seed": seed, "completed": len(rows)}), flush=True)
    result = {"revision": REVISION, "seeds": list(seeds), "completed": len(rows), "paid_calls": 0,
              "rows": rows, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "all_collaboration_full_with_coverage": True}
    (output / "summary.json").write_bytes(canonical_json_bytes(result) + b"\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--output", type=Path, required=True); args = p.parse_args()
    result = asyncio.run(conformance(args.output)); print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
