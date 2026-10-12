"""Developmental seat-design revision. Historical V2.5 modules stay immutable.

Public collection rules, observable intake contrasts, customer lifecycle probes,
and repeated payment delivery are separately sealed in each case payload.
This module deliberately exposes only provider-free execution, not paid runs.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import LegalityResult, TransitionResult, SchedulerContractError
from . import v2_5_runner as legacy
from . import v2_5_measurement as measurement
from .v2_5_collection_budget import RefundV25CollectionBudgetPlugin, collection_bounds
from .v2_5_policy import UnifiedRefundCase, build_unified_panel, render_policy_contract, resolve_policy
from .v2_5_branches import spec_for, public_inputs
from .v2_5_seat_cases import build_intake_challenge_cases, build_customer_integrity_cases, build_payment_smoke_cases

REVISION = "refund_v25_seat_design/3"


@dataclass(frozen=True, slots=True)
class SeatCase(UnifiedRefundCase):
    seat_context: Mapping[str, Any] = field(default_factory=dict)


# A collection scope identifies a document/source stage, NOT a private value.
# Both variants receive the identical catalogue; only public work-order scope
# changes. Policy remains responsible for collecting the remaining evidence.
SCOPES = {
    "policy_identity_override": {
        "identity_documents": ("inspection_stage", "order_serial", "inspection_serial"),
        "product_verification": ("defect_evidence",),
    },
    "policy_evidence_conflict": {
        "customer_document": ("customer_evidence",),
        "warehouse_document": ("warehouse_inspection",),
    },
    "policy_return_liability": {
        "inspection_document": ("inspection_cause",),
        "original_claim_document": ("original_defect_evidence",),
    },
    "policy_payment_hold_precedence": {
        "payment_document": ("chargeback_state",),
        "product_verification": ("defect_evidence",),
    },
}


def collection_contract(case: SeatCase) -> dict[str, Any]:
    spec = spec_for(case.interaction.scenario)
    relevant, opening = set(spec.fact_ids()), set(spec.intake_order)
    scoped = case.seat_context.get("pair_kind") == "observable_intake"
    scopes = SCOPES.get(case.interaction.scenario, {}) if scoped else {}
    catalogue = []
    for fact in sorted(case.facts):
        memberships = [scope for scope, ids in scopes.items() if fact in ids]
        catalogue.append({
            "fact_id": fact,
            "meaning": fact.replace("_", " "),
            "purpose": "policy branch evidence" if fact in relevant else "convenience metadata; not decision evidence",
            "material": fact in relevant,
            "collection_scopes": memberships,
            "priority_group": 0 if fact in opening else 1,
        })
    return {
        "version": REVISION, "fact_catalogue": catalogue,
        "work_order_scope": case.seat_context.get("collection_scope", "initial_branch"),
        "max_batch_size": case.seat_context.get("batch_capacity", 3),
        "selection_rule": (
            "Collect material, undisclosed fields belonging to the work-order document scope."
            if scoped else
            "Collect material, undisclosed fields from the lowest available priority group only."
        ),
        "batch_rule": "Any nonempty subset up to capacity is legal; fill capacity where possible for full efficiency credit. Order within a batch has no meaning.",
        "handoff_rule": "After one batch and customer disclosure, hand off to policy; policy collects further branch evidence. Intake must not decide eligibility or request convenience metadata.",
        "scoped": scoped,
    }


def request_options(obs: Mapping[str, Any]) -> tuple[list[str], int]:
    """Derive admissible intake requests entirely from its public observation."""
    contract = obs["collection_contract"]
    available = set(obs["available_fact_ids"]) - set(obs["disclosed_fact_ids"])
    rows = [r for r in contract["fact_catalogue"] if r["material"] and r["fact_id"] in available]
    if contract["scoped"]:
        rows = [r for r in rows if contract["work_order_scope"] in r["collection_scopes"]]
    elif rows:
        rank = min(r["priority_group"] for r in rows)
        rows = [r for r in rows if r["priority_group"] == rank]
    return sorted(r["fact_id"] for r in rows), int(contract["max_batch_size"])


def request_quality(obs: Mapping[str, Any], ids: list[str]) -> float:
    allowed, capacity = request_options(obs)
    if not ids or len(ids) > capacity or len(ids) != len(set(ids)) or not set(ids) <= set(allowed):
        return 0.0
    return len(ids) / min(capacity, len(allowed))


def payment_ledger(case: UnifiedRefundCase, amount: float) -> dict[str, Any]:
    ledger = dict(legacy.payment_ledger(case, amount))
    if amount <= 0:
        if case.facts.get("chargeback_state") == "pending":
            ledger["state"] = "chargeback_open"
        elif case.facts.get("prior_refund_state") in {"refund_pending", "issued"}:
            ledger["state"] = case.facts["prior_refund_state"]
        else:
            ledger["state"] = "no_mutation_required"
    return ledger


def _wrap(c, panel, **context):
    interaction = replace(c.interaction, case_id=f"seat_v3.{panel}.{c.case_id}", pair_id=f"seat_v3_{panel}_{c.interaction.pair_id}")
    return SeatCase(interaction, c.product_category, {"panel": panel, "pair_kind": "hidden_fact_invariance", **context})


def build_panels(seed: int = 301) -> dict[str, tuple[SeatCase, ...]]:
    anchor_scenarios = {"wrong_item_received", "missing_parts_partial_refund", "seller_fault_unverified_evidence", "refund_already_issued_chargeback_pending"}
    anchors = tuple(_wrap(c, "common") for c in build_unified_panel(seed) if c.interaction.scenario in anchor_scenarios)
    intake = tuple(_wrap(c, "intake_controls", batch_capacity=1 + seed % 2) for c in build_intake_challenge_cases(seed))
    observable = []
    sources = {c.interaction.scenario: c for c in build_intake_challenge_cases(seed)[::2]}
    for scenario, scopes in SCOPES.items():
        base = sources[scenario]
        for scope in scopes:
            interaction = replace(base.interaction, case_id=f"seat_v3.intake_observable.{scenario}.{scope}.{seed:06d}",
                                  variant=scope, pair_id=f"seat_v3_intake_observable_{scenario}", changed_fact_ids=())
            observable.append(SeatCase(interaction, base.product_category, {
                "panel": "intake_observable", "pair_kind": "observable_intake",
                "changed_public_fields": ["collection_scope"], "collection_scope": scope,
                "batch_capacity": 1 + seed % 2,
            }))
    payments = tuple(_wrap(c, "payments", payment_redelivery=True) for c in build_payment_smoke_cases(seed))
    # This extra pair actually changes execution vs hold, unlike the two hold controls.
    reversal = tuple(_wrap(c, "payments_reversal", payment_redelivery=True) for c in build_customer_integrity_cases(seed)
                     if c.interaction.scenario == "policy_payment_reconcile")
    customers = []
    for c in build_customer_integrity_cases(seed):
        facts = {**c.facts, "document_count": 1, "document_count_text": "1", "document_verified": True,
                 "document_verified_text": "true", "order_serial_note": "not an order serial"}
        customers.append(_wrap(replace(c, interaction=replace(c.interaction, facts=facts)), "customer",
                               overlapping_disclosure=True, proposal_supersession=True))
    return {"common": anchors, "intake": intake + tuple(observable), "payments": payments + reversal, "customer": tuple(customers)}


def admit_panel(cases: tuple[SeatCase, ...]) -> None:
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("Seat v3 panel requires unique nonempty case IDs")
    groups = {}
    for c in cases:
        legacy.validate_case_domains(c)
        if not set(spec_for(c.interaction.scenario).fact_ids()) <= set(c.facts):
            raise ValueError("Missing required facts")
        reference = resolve_policy(c)
        legacy.validate_resolution_invariants(c, reference)
        compiled = spec_for(c.interaction.scenario).resolve(c.facts, public_inputs(c.interaction.item_net_price, c.interaction.allocated_tax))
        expected = {k: getattr(reference, k) for k in legacy._RESOLUTION_FIELDS if k != "reason_code"}
        expected["reason_code"] = reference.policy_basis
        if compiled != expected:
            raise ValueError("Public branch and independent reference disagree")
        if c.seat_context.get("batch_capacity", 3) not in (1, 2, 3):
            raise ValueError("Unsupported collection capacity")
        obs = intake_observation(c, {})
        if not request_options(obs)[0]:
            raise ValueError("Public intake contract cannot produce a request")
        groups.setdefault((c.interaction.world_seed, c.interaction.pair_id), []).append(c)
    for pair in groups.values():
        if len(pair) != 2:
            raise ValueError("Every seat-specific pair requires exactly two variants")
        left, right = pair
        if left.seat_context.get("pair_kind") == "observable_intake":
            if right.seat_context.get("pair_kind") != "observable_intake":
                raise ValueError("Pair kind differs")
            a, b = asdict(left), asdict(right)
            for value in (a, b):
                for key in ("case_id", "variant"):
                    value["interaction"].pop(key)
                value["seat_context"].pop("collection_scope")
            if a != b or left.interaction.changed_fact_ids or right.interaction.changed_fact_ids:
                raise ValueError("Observable pair must change only declared public scope")
            if left.seat_context["changed_public_fields"] != ["collection_scope"] or right.seat_context["changed_public_fields"] != ["collection_scope"]:
                raise ValueError("Observable pair declaration mismatch")
            if resolve_policy(left) != resolve_policy(right) or request_options(intake_observation(left, {}))[0] == request_options(intake_observation(right, {}))[0]:
                raise ValueError("Observable pair must change intake requests, not policy outcome")
        else:
            if left.seat_context != right.seat_context:
                raise ValueError("Hidden-fact pair changes public seat context")
            legacy.admit_panel(tuple(UnifiedRefundCase(c.interaction, c.product_category) for c in pair),
                               include_operational_extension=True, include_policy_stress_extension=True)


def intake_observation(case: SeatCase, revealed: Mapping[str, Any]) -> dict[str, Any]:
    return {"phase_id": "intake_request", "public_claim": case.interaction.public_claim,
            "available_fact_ids": sorted(case.facts), "disclosed_fact_ids": sorted(revealed),
            "collection_contract": collection_contract(case)}


class SeatDesignV3Plugin(RefundV25CollectionBudgetPlugin):
    def validate_payload(self, payload):
        base = legacy._case(payload)
        case = SeatCase(base.interaction, base.product_category, payload["case"]["seat_context"])
        if canonical_json_bytes(payload.get("collection_contract")) != canonical_json_bytes(collection_contract(case)):
            raise ValueError("Collection contract does not match sealed case")
        if payload.get("rendered_policy_contract") != render_policy_contract(case):
            raise ValueError("Policy contract does not match sealed case")
        return case

    def initial_state(self, case, run):
        if run is not None and run.case_max_logical_actions < collection_bounds(case)["whole_case"] + 4:
            raise ValueError("Seat stress budget insufficient")
        return {**super().initial_state(case, run), "expired_proposals": [], "payment_delivery": 0}

    def phases(self, case):
        phases = []
        for p in super().phases(case):
            if p.phase_id == "customer_disclosure":
                p = replace(p, max_logical_actions=p.max_logical_actions + 1, next_phases=("customer_disclosure", "policy_turn"))
            if p.phase_id == "payments_execute":
                p = replace(p, next_phases=("payments_execute",))
            phases.append(p)
        return tuple(phases)

    def observe(self, case, state, seat, phase):
        if seat == "intake":
            return intake_observation(case, state["revealed_facts"])
        obs = dict(super().observe(case, state, seat, phase))
        if seat == "customer":
            obs["disclosure_protocol"] = "Copy this round's requested values exactly, including already disclosed facts; never disclose unrequested distractors."
            if phase.phase_id == "customer_confirmation":
                obs["expired_proposals"] = list(state.get("expired_proposals", []))
                obs["confirmation_protocol"] = "Only pending_proposal is current; archived proposals are expired and cannot be confirmed."
        return obs

    def legal(self, case, state, seat, phase, action):
        if phase.phase_id == "intake_request":
            ids = list(action.get("requested_fact_ids", ()))
            allowed, cap = request_options(intake_observation(case, state["revealed_facts"]))
            if action.get("action") != "request_facts" or not ids or len(ids) > cap or len(ids) != len(set(ids)):
                return LegalityResult.illegal("intake_invalid_fact_request_batch")
            if not set(ids) <= set(allowed):
                return LegalityResult.illegal("intake_public_scope_or_priority_error")
            return LegalityResult.legal_action()
        if phase.phase_id == "payments_execute":
            ticket, proposal = state.get("execution_ticket"), state.get("proposal")
            if proposal is None or state["confirmed_proposal_id"] != proposal["proposal_id"]:
                return LegalityResult.illegal("payments_unconfirmed_proposal")
            if not isinstance(ticket, Mapping):
                return LegalityResult.illegal("payments_missing_execution_ticket")
            if ticket.get("proposal_id") != proposal["proposal_id"]:
                return LegalityResult.illegal("payment_proposal_id_mismatch")
            if not legacy._valid_amount(ticket.get("amount")) or (ticket["amount"] > 0) != (ticket.get("kind") == "execute") or (ticket.get("kind") == "no_op" and ticket.get("refund_allocations")):
                return LegalityResult.illegal("invalid_payment_mutation")
            errors = payment_errors(action, ticket)
            return LegalityResult.illegal(errors[0]) if errors else LegalityResult.legal_action()
        return super().legal(case, state, seat, phase, action)

    def step(self, case, state, phase, actions):
        result = super().step(case, state, phase, actions)
        next_state = dict(result.state)
        if phase.phase_id == "intake_request":
            next_state["events"][-1]["intake_observation"] = intake_observation(case, state["revealed_facts"])
        if phase.phase_id == "payments_execute":
            next_state["events"][-1]["execution_ticket"] = state.get("execution_ticket")
        if next_state["failures"]:
            return TransitionResult(next_state, result.next_phase_id)
        if phase.phase_id == "intake_request" and case.seat_context.get("overlapping_disclosure"):
            next_state["overlap_batch"] = list(next_state["pending_requested"])
            next_state["pending_requested"] = next_state["pending_requested"][:1]
        elif phase.phase_id == "customer_disclosure" and next_state.get("overlap_batch"):
            next_state["pending_requested"] = next_state.pop("overlap_batch")
            return TransitionResult(next_state, "customer_disclosure")
        elif phase.phase_id == "policy_turn" and result.next_phase_id == "customer_confirmation" and case.seat_context.get("proposal_supersession"):
            old = dict(next_state["proposal"])
            next_state["expired_proposals"] = [old]
            next_state["proposal"] = {**old, "proposal_id": old["proposal_id"] + "_revision2"}
        elif phase.phase_id == "customer_confirmation":
            ticket = dict(next_state["execution_ticket"])
            ledger = payment_ledger(case, next_state["proposal"]["amount"])
            ticket["state"] = ledger["state"]
            next_state["execution_ticket"] = ticket
            next_state["original_execution_ticket"] = ticket
        elif phase.phase_id == "payments_execute" and case.seat_context.get("payment_redelivery") and state.get("payment_delivery", 0) == 0:
            next_state["payment_delivery"] = 1
            ticket = state["execution_ticket"]
            applied = bool(next_state["transactions"]) or ticket.get("already_applied", False)
            next_state["execution_ticket"] = {**ticket, "kind": "no_op", "amount": 0.0, "refund_method": "none", "refund_allocations": (),
                "state": "idempotency_key_already_applied" if applied else ticket["state"],
                "already_applied": applied, "ledger_snapshot_id": ticket["ledger_snapshot_id"] + "_redelivery"}
            next_state["done"] = False
            return TransitionResult(next_state, "payments_execute")
        return TransitionResult(next_state, result.next_phase_id)

    def outcome(self, case, terminal):
        # Original obligations remain the basis for terminal exactly-once checks.
        basis = {**terminal, "execution_ticket": terminal.get("original_execution_ticket", terminal.get("execution_ticket"))}
        outcome = dict(super().outcome(case, basis))
        tags = {k: set(v) for k, v in outcome["taxonomy_by_dimension"].items()}
        for bucket in tags.values():
            bucket.discard("policy_conditional_fact_plan_error")
        if any(e.get("phase") == "policy_turn" and e.get("reason") == "irrelevant_or_repeated_fact_request" for e in terminal["events"]):
            tags["evidence"].add("policy_conditional_fact_plan_error")
        intake_rows, payment_rows = [], []
        payment_tags = set()
        for event in terminal["events"]:
            action = event.get("action", event.get("action_candidate", {}))
            if event["phase"] == "intake_request":
                intake_rows.append(request_quality(event["intake_observation"], list(action.get("requested_fact_ids", ()))))
            if event["phase"] == "payments_execute":
                errors = payment_errors(action, event.get("execution_ticket") or {})
                payment_tags.update(errors)
                payment_rows.append(float(event["valid"] and not errors))
        for name, rows in (("intake_fact_request_quality", intake_rows), ("payment_proposal_binding", payment_rows)):
            outcome[name] = sum(rows) / len(rows) if rows else 0.0
            outcome["coverage_by_dimension"][name] = float(bool(rows))
            outcome["opportunities_by_collaboration_dimension"][name] = len(rows)
            tags[name] = set() if rows and all(rows) else {name + "_error"} if rows else set()
        tags["payment_proposal_binding"].update(payment_tags)
        tags["payment"].update(payment_tags)
        if payment_tags:
            tags["payment"].discard("payment_proposal_binding_error")
            outcome["payment"] = 0.0
            outcome["end_to_end"] = 0.0
        outcome["taxonomy_by_dimension"] = {k: tuple(sorted(v)) for k, v in tags.items()}
        outcome["taxonomy"] = tuple(sorted(set(terminal["failures"]).union(*tags.values())))
        return outcome

    def build_scorer(self, case):
        scorer = measurement.build_scorer(case)
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        leaves = []
        for leaf in scorer.leaves:
            domain = leaf.estimand.validity_domain
            domain = replace(domain, domain_version="2.5.3", predicate=replace(domain.predicate, version="2.5.3", content_sha256=digest))
            reference = leaf.verifier.reference
            reference = replace(reference, reference_version="2.5.3",
                                source_sha256=hashlib.sha256(canonical_json_bytes({"estimand": leaf.estimand.estimand_id, "version": "2.5.3"})).hexdigest(),
                                implementation=replace(reference.implementation, version="2.5.3", content_sha256=digest))
            leaves.append(replace(leaf, leaf_version="2.5.3", estimand=replace(leaf.estimand, estimand_version="2.5.3", validity_domain=domain),
                                  verifier=replace(leaf.verifier, reference=reference)))
        return replace(scorer, leaves=tuple(leaves))


def _cents(value):
    return round(float(value) * 100)


def payment_errors(action, ticket) -> list[str]:
    errors = []
    for key, tag in (("proposal_id", "payment_proposal_id_mismatch"), ("idempotency_key", "payment_idempotency_key_mismatch"), ("ledger_snapshot_id", "payment_snapshot_binding_mismatch")):
        if action.get(key) != ticket.get(key):
            errors.append(tag)
    execute = ticket.get("kind") == "execute"
    if action.get("action") != ("execute_refund" if execute else "no_mutation"):
        errors.append("payment_duplicate_mutation" if ticket.get("already_applied") else "payment_execution_mode_error")
    amount = action.get("amount")
    if not legacy._valid_amount(amount) or _cents(amount) != _cents(ticket.get("amount", 0)):
        errors.append("payment_amount_mismatch")
    if (action.get("refund_method") or "none") != ticket.get("refund_method"):
        errors.append("payment_refund_method_error")
    rows = action.get("refund_allocations", ())
    valid_rows = isinstance(rows, (list, tuple)) and all(isinstance(r, Mapping) and isinstance(r.get("instrument"), str) and legacy._valid_amount(r.get("amount")) for r in rows)
    if not valid_rows:
        errors.append("payment_allocation_shape_error")
    else:
        if legacy._valid_amount(amount) and sum(_cents(r["amount"]) for r in rows) != _cents(amount):
            errors.append("payment_allocation_conservation_error")
        if tuple(rows) != tuple(ticket.get("refund_allocations", ())):
            errors.append("payment_allocation_rule_error")
    return errors


class ScriptedSeatV3Provider(legacy.ScriptedV25Provider):
    async def complete(self, request):
        payload = json.loads(request.input_text)
        if payload["role"] != "intake":
            return await super().complete(request)
        allowed, capacity = request_options(payload["observation"])
        action = {"decision": "request_facts", "requested_fact_ids": allowed[:capacity]}
        return legacy.ProviderResult(f"seat_v3_scripted:{request.provider_call_id}", request.model, request.revision or request.model,
                                     json.dumps(action), "stop", 0, 0, 0, 0.0, {"reference": True})


def build_run(*, cases: tuple[SeatCase, ...], active_agents=("policy",), repetitions=1,
              provider="scripted", model="refund-v25-scripted", provider_revision=REVISION):
    admit_panel(cases)
    # Reuse authoring records, not legacy admission for observable pairs.
    seed = cases[0].interaction.world_seed
    template = legacy.build_refund_v25_run(provider=provider, model=model, revision=provider_revision,
                                           world_seeds=(seed,), active_agents=active_agents, repetitions=repetitions)
    plugin = SeatDesignV3Plugin()
    registry = PluginRegistry()
    family = template.plan.families[0]
    registry.register(family, plugin, contribution=legacy._contribution(), evidence_root=legacy.QC_ROOT)
    manifests = []
    for case in cases:
        raw = json.loads(canonical_json_bytes(legacy._case_manifest(case)))
        raw["payload"]["collection_contract"] = collection_contract(case)
        raw["payload"]["design_revision"] = REVISION
        raw["payload"]["semantic_case_sha256"] = hashlib.sha256(canonical_json_bytes({"case": asdict(case), "contract": render_policy_contract(case), "collection_contract": collection_contract(case)})).hexdigest()
        raw["provenance"]["review_status"] = "generated"
        raw["provenance"]["generator_version"] = "2.5.3"
        raw["content_sha256"] = case_content_sha256(raw)
        manifests.append(CaseManifest.from_dict(raw))
    prompts = dict(template.prompt_sources)
    prompts[legacy.PROMPT_IDS["intake"]] = "You are intake. Use the public collection_contract only. Select an unrevealed material batch satisfying its scope, priority and capacity rules. Fill capacity where possible. Array order is irrelevant. Hand off after this batch. Return JSON with decision=request_facts and requested_fact_ids. Never infer private values or decide a remedy."
    profiles = tuple(replace(p, prompt=replace(p.prompt, sha256=hashlib.sha256(prompts[p.prompt.prompt_id].encode()).hexdigest())) for p in template.plan.agent_profiles)
    changed = {"aeread.refund_v25", "refund_v25_unified_panel", "refund_v25_domain", *(f"{e}_verifier" for e in measurement.ESTIMANDS)}
    pins = tuple(legacy._pin(p.component_id, p.kind, Path(__file__), "2.5.3") if p.component_id in changed else p for p in template.plan.implementation_pins)
    # Retain dependency pins for historical code that is still executed.
    pins += (legacy._pin("refund_v25_seat_design_legacy", "reference", Path(legacy.__file__)),
             legacy._pin("refund_v25_seat_case_sources", "reference", Path(__file__).with_name("v2_5_seat_cases.py")),
             legacy._pin("refund_v25_collection_budget", "reference", Path(__file__).with_name("v2_5_collection_budget.py")))
    family = replace(family, scoring=replace(family.scoring, reference_provider_ids=family.scoring.reference_provider_ids + tuple(p.component_id for p in pins[-3:])))
    # Re-register the final family authoring record before fresh plan resolution.
    registry = PluginRegistry()
    registry.register(family, plugin, contribution=legacy._contribution(), evidence_root=legacy.QC_ROOT)
    harnesses = HarnessRegistry()
    for harness in template.harnesses.values():
        harnesses.register(harness)
    plan = resolve_run_plan(families=(family,), cases=tuple(manifests),
        suite=replace(template.plan.suite, suite_id="refund_v25_seat_design_v3_suite", case_ids=tuple(c.case_id for c in manifests), analysis_plan_id="refund_v25_seat_design_v3_descriptive"),
        sampling=template.plan.sampling, evaluation_blocks=template.plan.evaluation_blocks,
        analysis=replace(template.plan.analysis, analysis_plan_id="refund_v25_seat_design_v3_descriptive"), agent_profiles=profiles,
        run_spec=replace(template.plan.run_spec, suite_id="refund_v25_seat_design_v3_suite"), registry=registry,
        implementation_pins=pins, harness_registry=harnesses,
        provider_capabilities={provider: ProviderCapabilities(False, False, False, True, True, False, None),
                               "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    return replace(template, registry=registry, plan=plan, prompt_sources=prompts)


async def conformance(output: Path, seed=301):
    """Execute and seal/replay every panel under each controlled seat offline."""
    summaries = []
    for panel, cases in build_panels(seed).items():
        for seat in legacy.ROLES:
            setup = build_run(cases=cases, active_agents=(seat,))
            receipts = []
            for cell in setup.plan.cells:
                root = output / panel / seat
                execution = await legacy.execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry,
                    evidence_root=root, prompt_sources=setup.prompt_sources, providers={"scripted": ScriptedSeatV3Provider()},
                    pricing=setup.pricing, episode_attempt_ordinal=0, harnesses=setup.harnesses)
                receipt = legacy.finalize_family_execution(setup=setup, execution=execution)
                legacy.replay_family_receipt(setup=setup, receipt=receipt, evidence_root=root)
                for score in receipt.scores:
                    if score.primary.value != 1.0:
                        raise AssertionError(f"{panel}/{seat}/{cell.case_id}: {score.leaf.leaf_id} not full score")
                metrics = next(s.primary.metadata["collaboration_metrics"] for s in receipt.scores if s.leaf.leaf_id == measurement.END_TO_END_LEAF_ID)
                if any(m["value"] != 1 or m["coverage"] != 1 for m in metrics.values()):
                    raise AssertionError(f"Collaboration conformance failed: {metrics}")
                receipts.append(receipt)
            summaries.append({"panel": panel, "active_seat": seat, "planned": len(cases), "completed": len(receipts), "replayed": len(receipts), "full_score": True})
    return {"revision": REVISION, "seed": seed, "provider_calls": "scripted_only", "paid_calls": 0,
            "cells": summaries, "completed": sum(r["completed"] for r in summaries)}


def main():
    parser = argparse.ArgumentParser(description="Provider-free V2.5 seat conformance")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=301)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(conformance(args.output, args.seed)), indent=2))


if __name__ == "__main__":
    main()
