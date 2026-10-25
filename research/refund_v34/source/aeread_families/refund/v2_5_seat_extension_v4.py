"""Versioned ledger/provenance extension; V3 cases and results remain frozen."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import LegalityResult, TransitionResult
from . import v2_5_seat_design_v3 as v3

REVISION = "refund_v25_seat_extension/4"
TERMS = ("amount", "workflow", "refund_method", "payment_mutation", "return_shipping_payer")
CONTRACT = {
    "version": REVISION,
    "record_rule": "For each event_id use only its highest numeric revision; array order is irrelevant. Revisions for one event are unique.",
    "scope_rule": "Count only records matching order_id, line_item_id and currency of scope. Never convert or combine other scopes.",
    "precedence": ["A settled current idempotency key in scope means no_mutation.",
                   "Any submitted or unknown event in scope means no_mutation until reconciled.",
                   "Otherwise sum settled amounts in scope; failed events contribute zero. Residual cents = max(approved cents - settled cents,0)."],
    "execution_rule": "Execute only a positive residual. Use original rail if open, otherwise the declared fallback. No-op amount=0, refund_method=none and refund_allocations=[].",
    "binding_rule": "Copy proposal_id, idempotency_key and current ledger_snapshot_id from this observation. Positive refunds use original_payment and one allocation to the selected rail. Evaluate every delivery against its current ledger.",
}


def cents(amount):
    return round(float(amount) * 100)


def payment_reference(proposal, ledger):
    """Independent expected execution reducer, solely on public payment inputs."""
    newest = {}
    for record in ledger["records"]:
        previous = newest.get(record["event_id"])
        if previous is None or record["revision"] > previous["revision"]:
            newest[record["event_id"]] = record
    scope = ledger["scope"]
    matching = [r for r in newest.values() if all(r[k] == scope[k] for k in ("order_id", "line_item_id", "currency"))]
    applied = any(r["status"] == "settled" and r["idempotency_key"] == ledger["idempotency_key"] for r in matching)
    held = any(r["status"] in {"submitted", "unknown"} for r in matching)
    settled = sum(r["amount_cents"] for r in matching if r["status"] == "settled")
    residual = 0 if applied or held else max(cents(proposal["amount"]) - settled, 0)
    rail = ledger["original_rail"] if ledger["original_rail_open"] else ledger["fallback_rail"]
    return {"proposal_id": proposal["proposal_id"], "idempotency_key": ledger["idempotency_key"],
            "ledger_snapshot_id": ledger["snapshot_id"], "kind": "execute" if residual > 0 else "no_op",
            "amount": residual / 100, "refund_method": "original_payment" if residual else "none",
            "refund_allocations": [{"instrument": rail, "amount": residual / 100}] if residual else [],
            "already_applied": applied, "state": "pending_reconciliation" if held else "settled" if applied else "reconciled"}


def scripted_payment(obs):
    """Observation-only counterpart; independently traverses revision groups."""
    ledger = obs["payment_ledger"]
    rows = sorted(ledger["records"], key=lambda r: (r["event_id"], -r["revision"]))
    seen, settled, blocked = set(), 0, False
    for row in rows:
        if row["event_id"] in seen:
            continue
        seen.add(row["event_id"])
        if any(row[k] != ledger["scope"][k] for k in ("order_id", "line_item_id", "currency")):
            continue
        if row["status"] in ("submitted", "unknown") or (row["status"] == "settled" and row["idempotency_key"] == ledger["idempotency_key"]):
            blocked = True
        if row["status"] == "settled":
            settled += row["amount_cents"]
    amount = 0 if blocked else max(cents(obs["confirmed_proposal"]["amount"]) - settled, 0)
    return {"decision": "execute_refund" if amount else "no_mutation",
            "proposal_id": obs["confirmed_proposal"]["proposal_id"], "idempotency_key": ledger["idempotency_key"],
            "ledger_snapshot_id": ledger["snapshot_id"], "amount": amount / 100,
            "refund_method": "original_payment" if amount else "none",
            "refund_allocations": [{"instrument": ledger["original_rail"] if ledger["original_rail_open"] else ledger["fallback_rail"], "amount": amount / 100}] if amount else []}


def _record(ledger, **values):
    return {**ledger["scope"], "event_id": "prior_event", "revision": 1,
            "idempotency_key": "older_instruction", "status": "settled", "amount_cents": 0, **values}


def build_panels(seed=301, include_holdout=False):
    base = v3.build_panels(seed)
    positive = [c for c in base["common"] if v3.resolve_policy(c).amount > 0]
    mechanisms = ("order_scope", "pending_finality", "line_item_residual", "revision_precedence")
    if include_holdout:
        mechanisms += ("currency_scope",)
    payments = []
    for i, mechanism in enumerate(mechanisms):
        source = positive[i % len(positive)]
        total = cents(v3.resolve_policy(source).amount)
        ledger = {"scope": {"order_id": f"order_{mechanism}_{seed}", "line_item_id": "line_A", "currency": "USD"},
                  "idempotency_key": "refund-proposal_1", "snapshot_id": f"snapshot_{mechanism}_{seed}",
                  "original_rail": "card_4242", "original_rail_open": False, "fallback_rail": "wallet"}
        if mechanism == "order_scope":
            records = [_record(ledger, idempotency_key=ledger["idempotency_key"], amount_cents=total)]
            field, values = "order_id", ("unrelated_order", ledger["scope"]["order_id"])
        elif mechanism == "pending_finality":
            records = [_record(ledger, amount_cents=total)]
            field, values = "status", ("submitted", "failed")
        elif mechanism == "line_item_residual":
            records = [_record(ledger, amount_cents=total - 1)]
            field, values = "line_item_id", ("other_line", "line_A")
        elif mechanism == "revision_precedence":
            records = [_record(ledger, revision=2, amount_cents=total),
                       _record(ledger, revision=1, status="submitted", amount_cents=total)]
            field, values = "status", ("failed", "settled")
        else:
            records = [_record(ledger, idempotency_key=ledger["idempotency_key"], amount_cents=total)]
            field, values = "currency", ("EUR", "USD")
        # A same-status distractor from a different scope is present in both variants.
        records += [_record(ledger, event_id="distractor", order_id="unrelated_order", status="unknown", amount_cents=total)]
        for variant, value in zip(("a", "b"), values):
            changed = [dict(r) for r in records]
            changed[0][field] = value
            interaction = replace(source.interaction, case_id=f"seat_v4.payments.{mechanism}.{variant}.{seed:06d}",
                                  pair_id=f"seat_v4_payments_{mechanism}", variant=variant, changed_fact_ids=())
            payments.append(v3.SeatCase(interaction, source.product_category, {
                "panel": "payments_v4", "pair_kind": "payment_execution", "mechanism": mechanism,
                "changed_public_fields": [f"payment_ledger.records[0].{field}"],
                "payment_redelivery": True, "payment_ledger": {**ledger, "records": changed},
                "held_out": mechanism == "currency_scope"}))
    selected = {"policy_seller_fault_override", "policy_payment_reconcile"}
    if include_holdout:
        selected.add("policy_evidence_conflict")
    customers = []
    for source in base["customer"]:
        if source.interaction.scenario not in selected:
            continue
        interaction = replace(source.interaction, case_id=f"seat_v4.customer.{source.interaction.scenario}.{source.interaction.variant}.{seed:06d}",
                              pair_id=f"seat_v4_customer_{source.interaction.scenario}")
        customers.append(v3.SeatCase(interaction, source.product_category, {
            "panel": "customer_v4", "pair_kind": "hidden_fact_invariance",
            "overlapping_disclosure": True, "proposal_supersession": True,
            "customer_record_provenance": True, "confirmation_terms": True,
            "held_out": source.interaction.scenario == "policy_evidence_conflict"}))
    result = {"payments": tuple(payments), "customer": tuple(customers)}
    admit_panels(result)
    return result


def admit_panels(panels):
    if panels["customer"]:
        v3.admit_panel(panels["customer"])
    pairs = {}
    for case in panels["payments"]:
        v3.legacy.validate_case_domains(case)
        v3.legacy.validate_resolution_invariants(case, v3.resolve_policy(case))
        ledger = case.seat_context["payment_ledger"]
        for row in ledger["records"]:
            if (row["status"] not in {"submitted", "unknown", "failed", "settled"}
                    or type(row["amount_cents"]) is not int or row["amount_cents"] < 0
                    or type(row["revision"]) is not int or row["revision"] <= 0
                    or any(not isinstance(row[k], str) or not row[k] for k in ("event_id", "order_id", "line_item_id", "currency", "idempotency_key"))):
                raise ValueError("Invalid public ledger record")
        if len({(r["event_id"], r["revision"]) for r in ledger["records"]}) != len(ledger["records"]):
            raise ValueError("Nonunique event revision")
        pairs.setdefault(case.interaction.pair_id, []).append(case)
    for pair in pairs.values():
        if len(pair) != 2:
            raise ValueError("Payment pair must have two variants")
        a, b = pair
        if a.facts != b.facts or a.interaction.changed_fact_ids or v3.resolve_policy(a) != v3.resolve_policy(b):
            raise ValueError("Execution pairs cannot change policy facts or policy resolution")
        x, y = asdict(a), asdict(b)
        for raw in (x, y):
            raw["interaction"].pop("case_id"); raw["interaction"].pop("variant")
        field = a.seat_context["changed_public_fields"][0].rsplit(".", 1)[1]
        x["seat_context"]["payment_ledger"]["records"][0].pop(field)
        y["seat_context"]["payment_ledger"]["records"][0].pop(field)
        if x != y:
            raise ValueError("Pair changes more than declared ledger field")
        proposal = {**asdict(v3.resolve_policy(a)), "proposal_id": "proposal_1"}
        left, right = (payment_reference(proposal, c.seat_context["payment_ledger"]) for c in pair)
        if (left["kind"], left["amount"]) == (right["kind"], right["amount"]):
            raise ValueError("Payment pair has no execution contrast")


def fact_records(case):
    rows = []
    for fact, value in sorted(case.facts.items()):
        wrong = (not value) if type(value) is bool else value + 1 if type(value) in (int, float) else "archived:" + str(value)
        rows += [{"fact_id": fact, "document_id": "current_document", "revision": 2, "value": value},
                 {"fact_id": fact, "document_id": "current_document", "revision": 1, "value": wrong},
                 {"fact_id": fact, "document_id": "other_document", "revision": 3, "value": wrong}]
    shift = case.interaction.world_seed % len(rows)
    return rows[shift:] + rows[:shift]


class ExtensionPlugin(v3.SeatDesignV3Plugin):
    def observe(self, case, state, seat, phase):
        obs = dict(super().observe(case, state, seat, phase))
        if seat == "customer" and case.seat_context.get("customer_record_provenance"):
            obs.pop("private_facts", None)
            obs["private_fact_records"] = fact_records(case)
            obs["disclosure_contract"] = {"document_id": "current_document", "revision": 2,
                "rule": "For each requested fact copy the exact typed value from this document and revision; a higher revision in another document is irrelevant. Disclose only requested IDs."}
            obs["confirmation_protocol"] = "Confirm only pending_proposal: return proposal_id and confirmed_terms with exactly amount, workflow, refund_method, payment_mutation and return_shipping_payer from that proposal. Archived drafts are abandoned, not current."
        if seat == "payments" and case.seat_context.get("pair_kind") == "payment_execution":
            obs = {"phase_id": phase.phase_id, "confirmed_proposal": state["proposal"],
                   "payment_ledger": state["execution_ticket"]["public_ledger"], "execution_contract": CONTRACT}
        return obs

    def legal(self, case, state, seat, phase, action):
        if phase.phase_id == "customer_confirmation" and case.seat_context.get("confirmation_terms"):
            echoed = action.get("confirmed_terms")
            expected = {k: state["proposal"][k] for k in TERMS}
            if not isinstance(echoed, dict) or set(echoed) != set(TERMS) or any(
                not (v3.legacy._valid_amount(echoed[k]) and echoed[k] == expected[k]) if k == "amount"
                else not v3.legacy._same_fact_value(echoed[k], expected[k]) for k in TERMS):
                return LegalityResult.illegal("customer_confirmation_terms_mismatch")
        return super().legal(case, state, seat, phase, action)

    def step(self, case, state, phase, actions):
        result = super().step(case, state, phase, actions)
        new = dict(result.state)
        if new["failures"]:
            return result
        if phase.phase_id == "policy_turn" and result.next_phase_id == "customer_confirmation" and case.seat_context.get("confirmation_terms"):
            new["expired_proposals"] = [{**p, "amount": round(float(p["amount"]) + .01, 2), "draft_status": "abandoned"} for p in new["expired_proposals"]]
        if phase.phase_id == "customer_confirmation" and case.seat_context.get("pair_kind") == "payment_execution":
            ledger = case.seat_context["payment_ledger"]
            ticket = {**payment_reference(new["proposal"], ledger), "public_ledger": ledger}
            new["execution_ticket"] = ticket
            new["original_execution_ticket"] = ticket
        if phase.phase_id == "payments_execute" and case.seat_context.get("pair_kind") == "payment_execution" and result.next_phase_id == "payments_execute":
            ledger = dict(state["execution_ticket"]["public_ledger"])
            records = [dict(r) for r in ledger["records"]]
            if new["transactions"]:
                records.append(_record(ledger, event_id="current_delivery", status="settled",
                    idempotency_key=ledger["idempotency_key"], amount_cents=cents(new["transactions"][-1]["amount"])))
            ledger.update(records=records, snapshot_id=ledger["snapshot_id"] + "_redelivery")
            new["execution_ticket"] = {**payment_reference(new["proposal"], ledger), "public_ledger": ledger}
        return TransitionResult(new, result.next_phase_id)

    def build_scorer(self, case):
        scorer = super().build_scorer(case)
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        leaves = []
        for leaf in scorer.leaves:
            domain = leaf.estimand.validity_domain
            ref = leaf.verifier.reference
            leaves.append(replace(leaf, leaf_version="2.5.4", estimand=replace(leaf.estimand,
                estimand_version="2.5.4", validity_domain=replace(domain, domain_version="2.5.4",
                    predicate=replace(domain.predicate, version="2.5.4", content_sha256=digest))),
                verifier=replace(leaf.verifier, reference=replace(ref, reference_version="2.5.4",
                    implementation=replace(ref.implementation, version="2.5.4", content_sha256=digest)))))
        return replace(scorer, leaves=tuple(leaves))


class ScriptedProvider(v3.ScriptedSeatV3Provider):
    async def complete(self, request):
        inp = json.loads(request.input_text); obs, role = inp["observation"], inp["role"]
        if role == "payments" and "payment_ledger" in obs:
            action = scripted_payment(obs)
        elif role == "customer" and "private_fact_records" in obs and inp["phase_id"] == "customer_disclosure":
            scope = obs["disclosure_contract"]
            selected = {r["fact_id"]: r["value"] for r in obs["private_fact_records"]
                        if r["document_id"] == scope["document_id"] and r["revision"] == scope["revision"]}
            ids = obs["requested_fact_ids"]
            action = {"decision": "disclose_facts", "revealed_fact_ids": ids,
                      "fact_values": {k: selected[k] for k in ids}}
        elif role == "customer" and "private_fact_records" in obs and inp["phase_id"] == "customer_confirmation":
            p = obs["pending_proposal"]
            action = {"decision": "confirm_resolution", "proposal_id": p["proposal_id"],
                      "revealed_fact_ids": [], "confirmed_terms": {k: p[k] for k in TERMS}}
        else:
            return await super().complete(request)
        return v3.legacy.ProviderResult("seat_v4_scripted:" + request.provider_call_id,
            request.model, request.revision or request.model, json.dumps(action), "stop", 0, 0, 0, 0.0, {"reference": True})


def build_run(cases, active_agents=("policy",), provider="scripted", model="refund-v25-scripted", provider_revision=REVISION):
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("Nonempty unique extension case IDs required")
    admit_panels({"payments": tuple(c for c in cases if c.seat_context.get("pair_kind") == "payment_execution"),
                  "customer": tuple(c for c in cases if c.seat_context.get("pair_kind") != "payment_execution")})
    seed = cases[0].interaction.world_seed
    template = v3.build_run(cases=v3.build_panels(seed)["common"], active_agents=active_agents,
                          provider=provider, model=model, provider_revision=provider_revision)
    plugin = ExtensionPlugin(); family = template.plan.families[0]
    old_digest = hashlib.sha256(Path(v3.__file__).read_bytes()).hexdigest()
    pins = tuple(v3.legacy._pin(p.component_id, p.kind, Path(__file__), "2.5.4") if p.sha256 == old_digest else p for p in template.plan.implementation_pins)
    dep = v3.legacy._pin("refund_v25_seat_design_v3_dependency", "reference", Path(v3.__file__), "2.5.3")
    pins += (dep,)
    family = replace(family, scoring=replace(family.scoring, reference_provider_ids=family.scoring.reference_provider_ids + (dep.component_id,)))
    registry = PluginRegistry(); registry.register(family, plugin, contribution=v3.legacy._contribution(), evidence_root=v3.legacy.ROOT / "cases/refund_v2")
    manifests = []
    for c in cases:
        raw = json.loads(canonical_json_bytes(v3.legacy._case_manifest(c)))
        raw["payload"].update(collection_contract=v3.collection_contract(c), design_revision=REVISION)
        raw["provenance"].update(generator_version="2.5.4", review_status="generated")
        raw["content_sha256"] = case_content_sha256(raw)
        manifests.append(CaseManifest.from_dict(raw))
    prompts = dict(template.prompt_sources)
    prompts[v3.legacy.PROMPT_IDS["customer"]] += " In extension cases use private_fact_records and disclosure_contract to select the authoritative source and revision; never use an unrelated higher revision. At confirmation emit confirmed_terms exactly as instructed in confirmation_protocol."
    prompts[v3.legacy.PROMPT_IDS["payments"]] = "You are payments. Use only confirmed_proposal, payment_ledger and the complete public execution_contract. Reduce record revisions, filter scope and apply the precedence rules before calculating the residual. Evaluate each redelivery against its current ledger. Return one JSON object with decision exactly execute_refund or no_mutation, plus proposal_id, idempotency_key, ledger_snapshot_id, amount, refund_method, refund_allocations. Allocations are objects with instrument and amount. A no-op has amount=0, refund_method=none, refund_allocations=[]. Never infer private customer facts or recompute policy eligibility."
    profiles = []
    for p in template.plan.agent_profiles:
        schema = dict(p.harness.config["output_schema"])
        if p.prompt.prompt_id == v3.legacy.PROMPT_IDS["customer"]:
            schema["properties"] = {**schema["properties"], "confirmed_terms": {
                "type": "object", "additionalProperties": False, "required": list(TERMS),
                "properties": {k: {"type": "number" if k == "amount" else "string"} for k in TERMS}}}
        profiles.append(replace(p, harness=replace(p.harness, config={**p.harness.config, "output_schema": schema}), prompt=replace(p.prompt,
            sha256=hashlib.sha256(prompts[p.prompt.prompt_id].encode()).hexdigest())))
    harnesses = HarnessRegistry()
    for h in template.harnesses.values(): harnesses.register(h)
    suite_id = "refund_v25_seat_extension_v4"
    plan = resolve_run_plan(families=(family,), cases=tuple(manifests),
        suite=replace(template.plan.suite, suite_id=suite_id, case_ids=tuple(c.case_id for c in manifests)),
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis, agent_profiles=profiles,
        run_spec=replace(template.plan.run_spec, suite_id=suite_id), registry=registry,
        implementation_pins=pins, harness_registry=harnesses,
        provider_capabilities={provider: ProviderCapabilities(False, False, False, True, True, False, None),
                               "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    return replace(template, registry=registry, plan=plan, prompt_sources=prompts)


async def conformance(output):
    if output.exists(): raise FileExistsError("Fresh provider-free output required")
    rows = []
    for panel, cases in build_panels(include_holdout=True).items():
        for seat in v3.legacy.ROLES:
            setup = build_run(cases, active_agents=(seat,))
            for cell in setup.plan.cells:
                root = output / panel / seat
                execution = await v3.legacy.execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id,
                    registry=setup.registry, evidence_root=root, prompt_sources=setup.prompt_sources,
                    providers={"scripted": ScriptedProvider()}, pricing=setup.pricing,
                    episode_attempt_ordinal=0, harnesses=setup.harnesses)
                receipt = v3.legacy.finalize_family_execution(setup=setup, execution=execution)
                v3.legacy.replay_family_receipt(setup=setup, receipt=receipt, evidence_root=root)
                assert all(s.primary.value == 1 for s in receipt.scores), (cell.case_id, seat)
                metrics = next(s.primary.metadata["collaboration_metrics"] for s in receipt.scores if s.leaf.leaf_id == v3.measurement.END_TO_END_LEAF_ID)
                assert all(m["value"] == 1 and m["coverage"] == 1 for m in metrics.values())
                rows.append({"case_id":cell.case_id, "seat":seat, "full_scores":True, "replayed":True})
    result = {"revision":REVISION, "completed":len(rows), "paid_calls":0, "rows":rows,
              "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "all_collaboration_full_with_coverage": True}
    (output / "summary.json").write_bytes(canonical_json_bytes(result) + b"\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    result=asyncio.run(conformance(a.output)); print(json.dumps({k:v for k,v in result.items() if k != "rows"}))
