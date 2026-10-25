"""Prospective Refund 3.1 development repair; old 3.0 cases are immutable.

One world is one original claim followed by its explicitly authored appeal /
authorization / settlement lifecycle. It is NOT a bundle of counterfactual
twins. The old native decision remains a separately reported component and a
necessary conjunct of primary compliance. No post-hoc case selection occurs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json

from aeread.shared_runner.run.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import PhaseSpec, ParseResult, LegalityResult, TransitionResult
from . import v3_cases as old_cases, v3_environment as old, v3_oracles as independent
from .v2_5_branches import Branch, BranchSpec, Outcome, eq, ALWAYS

VERSION = "3.1.0"
REVISION = "refund_v3_claim_lifecycle/2"
FAMILY = "refund_v3_lifecycle"
PRIMARY = "refund_v3_lifecycle_seat_strict_leaf"
SEEDS = (401, 402, 403)


@dataclass(frozen=True)
class Case:
    base: old_cases.Case

    @property
    def case_id(self): return "refund_v31." + self.base.case_id
    @property
    def pair_id(self): return "refund_v31." + self.base.pair_id
    @property
    def seat(self): return self.base.seat
    @property
    def seed(self): return self.base.seed
    @property
    def cluster_id(self): return self.base.cluster_id


def build_catalog(seed=401):
    return tuple(Case(c) for c in old_cases.build_catalog(seed))


def contract(case):
    return dict(revision=REVISION, source_case_id=case.base.case_id,
        source_payload_sha256=old.digest(old_cases.payload(case.base)),
        seat=case.seat, role=case.base.role, cluster_id=case.cluster_id,
        pair_kind=case.base.pair_kind, original_changed_paths=list(case.base.changed_paths),
        primary="native_seat_strict AND complete_lifecycle_compliance",
        upper_bound=1, margin=1, split="development_exposed", blind=False,
        lifecycle={
            "policy": "Same claim appeal: identity verification, signed seller correction, then settlement reconciliation. Ordered public law supersedes the initial category decision only after the signed correction; original decision is still scored.",
            "intake": "Same claim appeal evidence work order: budgeted provenance chain and competing immediate-value records. Prerequisites must be disclosed before a batch; maximize material utility, then minimize cost; all optimal plans receive credit.",
            "customer": "Same claim record audit, followed by a proposed buyer-paid return rejected under private consent, a compliant revision, and explicit current-proposal rebinding. No policy oracle is shown.",
            "payments": "Same claim processor reversal/re-authorization: old settled credit is reversed, uncertain attempt fails, a confirmed replacement is executed, duplicate is suppressed, then a reversal and smaller confirmed revision create a new obligation. Net credit never exceeds the confirmed ceiling."
        }[case.seat],
        lineage_rule="Original source/pair/cluster retained; lifecycle fields are new public/private inputs under a new identity, not claimed byte-identical.")


def payload(case):
    return dict(version=VERSION, base=old_cases.payload(case.base), lifecycle_contract=contract(case))


def decode(raw):
    if set(raw) != {"version", "base", "lifecycle_contract"} or raw["version"] != VERSION:
        raise ValueError("Unknown lifecycle payload")
    case = Case(old_cases.case_from_payload(raw["base"]))
    if old.plain(raw["lifecycle_contract"]) != contract(case):
        raise ValueError("Lifecycle contract drift")
    return case


def sources():
    from . import v3_runner, v3_lifecycle_controls
    return {**v3_runner.implementation_sources(), **{
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("v3_lifecycle.py", "v3_lifecycle_controls.py", "v3_lifecycle_measurement.py", "v3_oracles.py")}}


def episode_contract(case, control="reference"):
    raw = dict(spec_version=CaseManifest.SPEC_VERSION, case_id=case.case_id,
        family_id=FAMILY, family_version=VERSION, split="dev", world_seed=case.seed,
        seats=[dict(id=s, role=s) for s in old.ROLES],
        episode=dict(max_logical_actions=512, termination=["completed", "invalid_action"]),
        visibility_policy="refund_v31_four_seat", payload=payload(case),
        provenance=dict(generator_id=FAMILY, generator_version=VERSION, review_status="generated"),
        content_sha256="0" * 64)
    raw["content_sha256"] = case_content_sha256(raw)
    manifest = CaseManifest.from_dict(raw)
    identity = old.digest(dict(case=manifest.content_sha256, control=control, sources=sources()))
    cell = PlanCell("1", "refund_v31_" + identity[:32], case.case_id, manifest.content_sha256,
        FAMILY, VERSION, "refund_v31_development", VERSION, "controlled_" + case.seat,
        "fixed", "development", case.seed, 0, 0, 0, 0, case.cluster_id, "mechanism", 2,
        case.pair_id, {"pair_id": case.pair_id}, "fixed_panel",
        {s: "active_" + control if s == case.seat else "scripted_reference" for s in old.ROLES}, "controlled", 512)
    return cell, manifest


def appeal_spec():
    return BranchSpec("same_claim_signed_correction", (
        Branch(eq("identity_verified", False), Outcome("APPEAL_IDENTITY", "unresolved", "none", "identity_review")),
        Branch(eq("seller_correction_signed", False), Outcome("APPEAL_REVIEW", "unresolved", "none", "manual_review")),
        Branch(ALWAYS, Outcome("APPEAL_RECONCILIATION", "eligible", "full_refund", "execute_refund",
                               "residual", "seller", ("settled_refund_cents",)))),
        ("identity_verified",))


def work_order(case):
    # Four rounds describe one provenance chain, not repeated independent tasks.
    # The tempting immediate record exhausts budget needed for the final audit.
    u = 30 + case.seed % 5
    rows = [dict(fact_id="audit_01", source="claim_archive", cost=2, utility=7, material=True, requires=[]),
            dict(fact_id="audit_02", source="claim_archive", cost=1, utility=0, material=True, requires=[]),
            dict(fact_id="audit_03", source="claim_archive", cost=1, utility=1, material=True, requires=["audit_02"]),
            dict(fact_id="audit_04", source="claim_archive", cost=1, utility=2, material=True, requires=["audit_03"]),
            dict(fact_id="audit_05", source="claim_archive", cost=2, utility=u, material=True, requires=["audit_04"]),
            dict(fact_id="audit_06", source="claim_archive", cost=1, utility=0, material=False, requires=[])]
    return dict(catalogue=rows, authorized_sources=["claim_archive"], max_batch_size=2,
                max_rounds=4, total_budget=5,
                rule="Maximize sum of material utility, then minimize total cost. No within-batch prerequisite satisfaction. All tied optimum plans count.")


def audit_records(case):
    facts = sorted(case.base.source.facts)[:2]
    rows = []
    for i, fact in enumerate(facts):
        value = case.base.source.facts[fact]
        for doc, rev, at, status in (("secondary", 1, 1, "live"), ("primary", 2, 2, "live" if i == 0 else "revoked"),
                                    ("primary", 99, 9, "live")):
            rows.append(dict(record_id=f"appeal_record_{len(rows):02d}", fact_id=fact,
                document_id=doc, revision=rev, recorded_at=at, status=status,
                scope="same_claim", value=value))
    return dict(request_scope="same_claim", as_of=3,
                authorities=[dict(document_id="primary", priority=0), dict(document_id="secondary", priority=1)]), rows


def consent_proposal(case, stage):
    total = round(case.base.source.interaction.item_net_price + case.base.source.interaction.allocated_tax, 2)
    return dict(proposal_id=f"appeal_revision_{stage}", amount=total, workflow="execute_refund",
        refund_method="original_payment", payment_mutation="execute",
        return_shipping_payer="buyer" if stage == 1 else "seller")


def consent_allowed(obs):
    p, c = obs["pending_proposal"], obs["private_consent"]
    return (p["amount"] <= c["maximum_amount"] and p["refund_method"] in c["permitted_refund_methods"]
            and p["return_shipping_payer"] in c["permitted_shipping_payers"])


def lifecycle_ledger(case, native_state):
    """Bridge actual historical rows and submitted native transactions.

    A scripted processor acknowledgement reverses each outstanding settled row
    and resolves each uncertain transfer. Both revisions remain. The bridge
    never invents a full-price earlier payment or clears the native history.
    """
    total = round((case.base.source.interaction.item_net_price + case.base.source.interaction.allocated_tax) * 100)
    scope = dict(order_id="same_claim", line_item_id="original_item", currency="USD")
    def row(event, revision, status, amount, key, allocations=None):
        return dict(event_id=event, revision=revision, status=status, amount_cents=amount,
                    idempotency_key=key, allocations_cents=allocations or ([dict(instrument="historical_rail", amount_cents=amount)] if amount else []), **scope)
    proposal = native_state["proposal"]
    opening = old.payment_observation(case.base, proposal)["payment_ledger"]
    records = []
    if case.base.ledger["kind"] in ("v4", "v5"):
        for original in opening["records"]:
            r = old.plain(original)
            r["event_id"] = "source_" + r["event_id"]
            relevant = all(r[k] == opening["scope"][k] for k in scope)
            r.update(scope if relevant else dict(order_id="foreign_order", line_item_id="foreign_item", currency=r["currency"]))
            r.setdefault("allocations_cents", [dict(instrument="historical_rail", amount_cents=r["amount_cents"])] if r["amount_cents"] else [])
            records.append(r)
    else:
        prior = round(float(opening.get("settled_refund_amount", 0)) * 100)
        if opening.get("already_applied") and not prior: prior = round(proposal["amount"] * 100)
        if prior: records.append(row("source_previous_credit", 1, "settled", prior, "source_previous_credit"))
    for i, tx in enumerate(native_state["transactions"]):
        records.append(row("native_transfer_" + str(i), 1, "settled", round(tx["amount"] * 100), tx["idempotency_key"],
            [dict(instrument=a["instrument"], amount_cents=round(a["amount"] * 100)) for a in tx["refund_allocations"]]))
    latest = {}
    for r in records:
        if r["event_id"] not in latest or r["revision"] > latest[r["event_id"]]["revision"]: latest[r["event_id"]] = r
    for r in latest.values():
        if all(r[k] == scope[k] for k in scope) and r["status"] in ("settled", "submitted", "unknown"):
            records.append(dict(r, revision=r["revision"] + 1, status="reversed" if r["status"] == "settled" else "failed"))
    return dict(scope=scope, snapshot_id="appeal_snapshot_0", idempotency_key="appeal_credit_0", records=records,
        tenders=[dict(instrument="card", priority=0, capacity_cents=max(1, total // 3), open=False, fallback="bank"),
                 dict(instrument="wallet", priority=1, capacity_cents=total, open=True, fallback="bank")])


def lifecycle_observation(case, state):
    l, seat = state["life"], case.seat
    stage = l["stage"]
    if state["mode"] == "disclose":
        return dict(phase_id="customer_disclosure", requested_fact_ids=l["pending"],
                    private_records=l["records"], source_contract=l["source_contract"])
    if seat == "intake":
        return dict(phase_id="intake_request", public_claim=case.base.source.interaction.public_claim,
            collection_contract=work_order(case), round=l["round"], remaining_budget=l["budget"],
            disclosed_fact_ids=l["known"])
    if seat == "customer":
        if stage == 0:
            c, rows = audit_records(case)
            return dict(phase_id="customer_disclosure", requested_fact_ids=sorted({r["fact_id"] for r in rows}),
                        private_records=rows, source_contract=c)
        proposal = consent_proposal(case, stage)
        return dict(phase_id="customer_confirmation", pending_proposal=proposal,
            archived_proposals=[consent_proposal(case, stage - 1)],
            private_consent=dict(maximum_amount=proposal["amount"], permitted_refund_methods=["original_payment"],
                                 permitted_shipping_payers=["seller", "none"]),
            confirmation_contract="Reject current proposal if any private consent constraint fails; otherwise confirm its current ID and exact terms. Archived consent never authorizes a revised proposal.")
    if seat == "policy":
        return dict(phase_id="policy_turn", public_claim=case.base.source.interaction.public_claim,
            policy_contract="Appeal overlay: verified identity precedes signed seller correction; only a signed correction overrides the initial category decision. Reconcile settled credit against original paid price plus tax; no new collection after final resolution. " + appeal_spec().catalogue(),
            branch_specification=appeal_spec().to_dict(), financial_inputs=old.public_policy(case.base),
            fact_types={"identity_verified": "boolean", "seller_correction_signed": "boolean", "settled_refund_cents": "number", "archive_note": "string"},
            revealed_facts=l["revealed"], attempted_fact_ids=l["attempted"], remaining_budget=l["budget"],
            catalogue=[dict(fact_id=k, cost=1) for k in ("identity_verified", "seller_correction_signed", "settled_refund_cents", "archive_note")],
            assigned_proposal_id="proposal_1", max_batch_size=4,
            canonical_enums=dict(eligibility=["eligible", "ineligible", "unresolved"], remedy=["full_refund", "none"],
                workflow=["identity_review", "manual_review", "execute_refund", "no_mutation"],
                refund_method=["original_payment", "none"], payment_mutation=["execute", "none"], return_shipping_payer=["seller", "none"]),
            collection_contract="Only requested evidence is disclosed. First applicable ordered branch and its formula must be determined; irrelevant collection loses evidence credit.")
    ledger = old.plain(l["ledger"])
    total = round(case.base.source.interaction.item_net_price + case.base.source.interaction.allocated_tax, 2)
    proposal = dict(proposal_id="appeal_payment_0" if stage < 2 else "appeal_payment_1",
        amount=total if stage < 2 else round(total / 2, 2), payment_mutation="execute", refund_method="original_payment")
    from .v3_contracts import payment_contract
    return dict(phase_id="payments_execute", confirmed_proposal=proposal, ledger_kind="v5", payment_ledger=ledger,
        delivery_already_applied=False, execution_contract=payment_contract("v5", ledger))


def reference(seat, obs):
    if seat == "customer" and obs["phase_id"] == "customer_confirmation" and "private_consent" in obs:
        p = obs["pending_proposal"]
        return dict(decision="confirm_resolution", proposal_id=p["proposal_id"],
                    confirmed_terms={k: p[k] for k in old.TERMS}) if consent_allowed(obs) else dict(decision="reject_resolution", proposal_id=p["proposal_id"])
    return old.scripted_action(seat, obs)


def independent_action(seat, obs):
    phase = obs["phase_id"]
    if seat == "policy":
        needed, resolution = independent.policy(obs["branch_specification"], old.usable(obs["revealed_facts"], obs["fact_types"]), obs["financial_inputs"])
        if needed:
            return dict(decision="request_facts", fact_ids=[needed[0]])
        return dict(decision="submit_resolution", proposal_id=obs.get("assigned_proposal_id", "proposal_1"), **resolution)
    if seat == "payments": return independent.payments(obs)
    if phase == "customer_disclosure":
        chosen = independent.customer_records(obs)
        return dict(decision="disclose_facts", disclosures=[dict(fact_id=k, record_id=v) for k, v in sorted(chosen.items())])
    if phase == "customer_claim": return dict(decision="state_claim", message=obs["public_claim"])
    if seat == "customer":
        p = obs["pending_proposal"]
        c = obs.get("private_consent")
        reject = c is not None and (p["amount"] > c["maximum_amount"] or p["refund_method"] not in c["permitted_refund_methods"] or p["return_shipping_payer"] not in c["permitted_shipping_payers"])
        return dict(decision="reject_resolution", proposal_id=p["proposal_id"]) if reject else dict(decision="confirm_resolution", proposal_id=p["proposal_id"], confirmed_terms={k: p[k] for k in old.TERMS})
    # Separate breadth-first oracle certifies the scripted DP objective rather
    # than its arbitrary lexicographic choice among equal optimal plans.
    return old.scripted_intake(obs)


def begin_life(case, state):
    l = dict(stage=0, round=0, budget=work_order(case)["total_budget"] if case.seat == "intake" else 4,
             known=[], revealed={}, attempted=[], events=[], pending=[], records=[], source_contract={},
             transactions=[], ledger=lifecycle_ledger(case, state["native"]) if case.seat == "payments" else {},
             bridge_native_transactions_sha256=old.digest(state["native"]["transactions"]), utility=0, cost=0)
    state.update(mode="life", life=l, done=False)
    return state


def policy_facts(case, stage):
    total = round((case.base.source.interaction.item_net_price + case.base.source.interaction.allocated_tax) * 100)
    return dict(identity_verified=stage != 0, seller_correction_signed=True,
                settled_refund_cents=total if stage == 2 else 0, archive_note="same claim administrative archive")


class Plugin:
    native = old.RefundV3Plugin()

    def validate_payload(self, raw): return decode(raw)
    def generator(self): return build_catalog
    def build_reference_providers(self, case): return ()
    def phases(self, case):
        phases = self.native.phases(case.base)
        observations = {r: "refund_v31_" + r + "_observation" for r in old.ROLES}
        actions = {r: "refund_v31_" + r + "_action" for r in old.ROLES}
        return tuple(replace(p, next_phases=tuple(sorted(set(p.next_phases) | {"lifecycle_review"}))) for p in phases) + (
            PhaseSpec("lifecycle_review", "native_focal_only", "single", observations, actions, 64, "family_defined", ("lifecycle_review", "lifecycle_disclosure")),
            PhaseSpec("lifecycle_disclosure", "customer_only", "single", observations, actions, 32, "family_defined", ("lifecycle_review",)))

    def eligible_actors(self, case, state, phase):
        if phase.phase_id == "lifecycle_review": return (case.seat,)
        if phase.phase_id == "lifecycle_disclosure": return ("customer",)
        return self.native.eligible_actors(case.base, state["native"], phase)

    def initial_state(self, case, run):
        return dict(native=self.native.initial_state(case.base, run), mode="native", life=None, done=False)

    def observe(self, case, state, seat, phase):
        if state["mode"] == "native": return self.native.observe(case.base, state["native"], seat, phase)
        return lifecycle_observation(case, state)

    def parse_action(self, case, state, seat, phase, response):
        from aeread.shared_runner.task.execution import CanonicalResponse
        if isinstance(response, CanonicalResponse): response = response.text
        if state["mode"] == "native": return self.native.parse_action(case.base, state["native"], seat, phase, response)
        obs = self.observe(case, state, seat, phase)
        try: raw = json.loads(response) if isinstance(response, str) else old.plain(response)
        except (ValueError, TypeError): return ParseResult.failure("malformed_json")
        if not old.conforms(raw, old.action_schema(obs["phase_id"])): return ParseResult.failure("closed_schema_violation")
        action = dict(raw, raw=raw)
        if seat == "policy" and raw["decision"] == "submit_resolution":
            for field, aliases in old.old._SCORING_ALIASES.items():
                if field in action: action[field] = aliases.get(action[field], action[field])
        return ParseResult.success(action)

    def legal(self, case, state, seat, phase, action):
        if state["mode"] == "native": return self.native.legal(case.base, state["native"], seat, phase, action)
        obs, l = self.observe(case, state, seat, phase), state["life"]
        fail = LegalityResult.illegal
        if obs["phase_id"] == "customer_disclosure":
            rows = action["disclosures"]; records = {r["record_id"]: r for r in obs["private_records"]}
            ids = [r["fact_id"] for r in rows]
            if len(ids) != len(set(ids)) or not set(ids) <= set(obs["requested_fact_ids"]): return fail("unsolicited_disclosure")
            if any(r["record_id"] not in records or records[r["record_id"]]["fact_id"] != r["fact_id"] for r in rows): return fail("unowned_record")
        elif seat == "intake":
            if action["decision"] != "handoff" and (l["round"] >= work_order(case)["max_rounds"] or not any(tuple(sorted(action["fact_ids"])) == b for b, _, _ in old.collection_batches(obs))): return fail("collection_access_or_budget")
        elif seat == "policy":
            if action["decision"] == "request_facts":
                ids = action["fact_ids"]
                if len(ids) != len(set(ids)) or not ids or not set(ids) <= {r["fact_id"] for r in obs["catalogue"]} or set(ids) & set(l["attempted"]) or len(ids) > l["budget"]: return fail("collection_access_or_budget")
            elif action["proposal_id"] != obs["assigned_proposal_id"] or not old.money(action["amount"]): return fail("policy_proposal_binding")
        elif seat == "customer":
            if action["proposal_id"] != obs["pending_proposal"]["proposal_id"]: return fail("stale_consent")
            if action["decision"] == "confirm_resolution" and old.plain(action["confirmed_terms"]) != {k: obs["pending_proposal"][k] for k in old.TERMS}: return fail("consent_terms_mismatch")
        else:
            ledger, p = obs["payment_ledger"], obs["confirmed_proposal"]
            if any(action[k] != v for k, v in dict(proposal_id=p["proposal_id"], idempotency_key=ledger["idempotency_key"], ledger_snapshot_id=ledger["snapshot_id"]).items()): return fail("payment_binding_error")
            rows = action["refund_allocations"]
            if not old.money(action["amount"]) or any(not old.money(r["amount"]) for r in rows): return fail("invalid_amount")
            if action["decision"] == "no_mutation":
                if action["amount"] or rows or action["refund_method"] != "none": return fail("unsafe_noop")
            else:
                limit, caps = old.payment_safety_limits(obs)
                if not action["amount"] or round(action["amount"] * 100) > limit or action["refund_method"] != "original_payment": return fail("unsafe_or_duplicate_mutation")
                if len({r["instrument"] for r in rows}) != len(rows) or round(sum(r["amount"] for r in rows), 2) != action["amount"]: return fail("allocation_conservation")
                if any(r["instrument"] not in caps or round(r["amount"] * 100) > caps[r["instrument"]] for r in rows): return fail("capacity_exceeded")
        return LegalityResult.legal_action()

    def step(self, case, state, phase, actions):
        new = old.plain(state)
        if state["mode"] == "native":
            result = self.native.step(case.base, state["native"], phase, actions)
            new["native"] = old.plain(result.state)
            if new["native"]["done"]:
                # Invalid native activity is terminal, not repaired by extension.
                if new["native"]["failures"]:
                    new["done"] = True
                    return TransitionResult(new, None)
                begin_life(case, new)
                return TransitionResult(new, "lifecycle_review")
            return TransitionResult(new, result.next_phase_id)
        seat, envelope = next(iter(actions.items()))
        obs, l = self.observe(case, state, seat, phase), new["life"]
        action = old.plain(envelope.parse.action) if envelope.parse.ok else None
        event = dict(seat=seat, phase=obs["phase_id"], valid=envelope.valid, action=action,
                     stage=l["stage"], quality=0, parse_ok=envelope.parse.ok)
        if not envelope.valid:
            event["reason"] = envelope.legality.reason if envelope.legality else envelope.parse.error_code
            l["events"].append(event); new["done"] = True
            return TransitionResult(new, None)
        if state["mode"] == "disclose":
            expected = independent_action("customer", obs)
            event["quality"] = float(action["raw"] == expected)
            by_id = {r["record_id"]: r for r in obs["private_records"]}
            l["revealed"].update({r["fact_id"]: by_id[r["record_id"]]["value"] for r in action["disclosures"]})
            l["known"] = sorted(set(l["known"]) | set(l["revealed"]))
            new["mode"] = "life"
        elif case.seat == "intake":
            if action["decision"] == "handoff":
                start = dict(obs, round=0, remaining_budget=work_order(case)["total_budget"], disclosed_fact_ids=[])
                event["quality"] = float((l["utility"], l["cost"]) == independent.intake_objective(start))
                new["done"] = True
            else:
                ids = action["fact_ids"]; rows = [r for r in work_order(case)["catalogue"] if r["fact_id"] in ids]
                spent = sum(r["cost"] for r in rows)
                l["round"] += 1; l["budget"] -= spent; l["cost"] += spent
                l["utility"] += sum(r["utility"] for r in rows if r["material"])
                event["quality"] = 1
                self._request(new, {k: "claim archive receipt" for k in ids})
        elif case.seat == "policy":
            if action["decision"] == "request_facts":
                needed, _ = independent.policy(obs["branch_specification"], obs["revealed_facts"], obs["financial_inputs"])
                ids = action["fact_ids"]
                event["quality"] = float(set(ids) <= set(needed))
                l["attempted"] += ids; l["budget"] -= len(ids)
                self._request(new, {k: policy_facts(case, l["stage"])[k] for k in ids})
            else:
                needed, resolution = independent.policy(obs["branch_specification"], obs["revealed_facts"], obs["financial_inputs"])
                expected = dict(decision="submit_resolution", proposal_id=obs["assigned_proposal_id"], **resolution) if resolution else None
                event["quality"] = float(not needed and action["raw"] == expected)
                semantic = ("eligibility", "remedy", "amount", "refund_method", "payment_mutation", "return_shipping_payer")
                event["policy_semantic"] = sum(action[k] == resolution[k] for k in semantic) / len(semantic) if resolution else None
                event["workflow"] = float(action["workflow"] == resolution["workflow"]) if resolution else None
                event["contract"] = float(expected is not None and all(action["raw"][k] == expected[k] for k in old.RESOLUTION))
                event["evidence"] = float(not needed)
                l["stage"] += 1; l.update(revealed={}, attempted=[], budget=4)
                new["done"] = l["stage"] == 3
        elif case.seat == "customer":
            expected = independent_action(seat, obs)
            event["quality"] = float(action["raw"] == expected)
            l["stage"] += 1; new["done"] = l["stage"] == 4
        else:
            expected = independent_action(seat, obs)
            event["quality"] = float(action["raw"] == expected)
            if action["decision"] == "execute_refund":
                tx = {k: action[k] for k in ("proposal_id", "idempotency_key", "amount", "refund_allocations")}
                l["transactions"].append(tx)
                l["ledger"]["records"].append(dict(event_id=f"appeal_transfer_{l['stage']}", revision=1, status="settled",
                    amount_cents=round(action["amount"] * 100), idempotency_key=action["idempotency_key"],
                    allocations_cents=[dict(instrument=r["instrument"], amount_cents=round(r["amount"] * 100)) for r in action["refund_allocations"]], **l["ledger"]["scope"]))
            l["stage"] += 1
            if l["stage"] == 2:
                for row in list(l["ledger"]["records"]):
                    if row["event_id"].startswith("appeal_transfer_") and row["status"] == "settled":
                        l["ledger"]["records"].append(dict(row, revision=2, status="reversed"))
                l["ledger"]["idempotency_key"] = "appeal_credit_1"
            l["ledger"]["snapshot_id"] = f"appeal_snapshot_{l['stage']}"
            new["done"] = l["stage"] == 4
        l["events"].append(event)
        return TransitionResult(new, None if new["done"] else "lifecycle_disclosure" if new["mode"] == "disclose" else "lifecycle_review")

    @staticmethod
    def _request(state, values):
        l = state["life"]
        l["pending"] = sorted(values)
        l["records"] = [dict(record_id="requested_" + k, fact_id=k, document_id="claim_archive", revision=1,
                             recorded_at=1, status="live", scope="same_claim", value=v) for k, v in sorted(values.items())]
        l["source_contract"] = dict(request_scope="same_claim", as_of=1, authorities=[dict(document_id="claim_archive", priority=0)])
        state["mode"] = "disclose"

    def terminal(self, case, state): return state if state["done"] else None

    def outcome(self, case, state):
        native = self.native.outcome(case.base, state["native"])
        events = state["life"]["events"] if state["life"] else []
        completed = bool(state["life"]) and state["done"] and not any(not e["valid"] for e in events)
        focal = [e for e in events if e["seat"] == case.seat]
        good = completed and bool(focal) and all(e["quality"] == 1 for e in focal)
        strict = dict(native["seat_strict"])
        strict[case.seat] *= float(good)
        components = {}
        if case.seat == "policy":
            for dimension in ("policy_semantic", "workflow", "contract", "evidence"):
                values = [e[dimension] for e in focal if e.get(dimension) is not None]
                components[dimension] = sum(values) / len(values) if values else None
        else:
            components[case.seat + "_compliance"] = sum(e["quality"] for e in focal) / len(focal) if focal else None
        return dict(native, seat_strict=strict, system_strict=float(native["system_strict"] == 1 and good),
            native_seat_strict=native["seat_strict"][case.seat], lifecycle_strict=float(good),
            lifecycle_components=components,
            lifecycle_events=events, lifecycle_transactions=state["life"]["transactions"] if state["life"] else [],
            lifecycle_complete=completed)

    def build_scorer(self, case):
        from .v3_lifecycle_measurement import build_scorer
        return build_scorer(case)


async def execute(case, arm="reference", tape=None, mutate=None, certify=False):
    """Real scheduler execution; no model I/O. Source/receipt identities differ from 3.0."""
    from aeread.shared_runner.task.scheduler import run_episode
    from .v3_lifecycle_controls import action, arms
    if arm not in arms(case.seat): raise ValueError("Undeclared control")
    transcript, checks, memory = [], [], {}
    cell, manifest = episode_contract(case, arm)
    plugin = Plugin()
    async def source(request):
        obs = old.plain(request.observation)
        seat = request.seat_id
        if tape is not None:
            row = tape[len(transcript)]
            if row["observation"] != obs or row["seat"] != seat: raise ValueError("Replay observation mismatch")
            text = row["response"]
        else:
            chosen = action(seat, obs, arm, memory) if seat == case.seat else reference(seat, obs)
            if certify:
                if seat == "intake":
                    target = independent.intake_objective(obs)
                    actual = old.intake_plan(obs)[:2]
                    if target != actual: raise ValueError("Independent Intake objective disagreement")
                else:
                    independent_value = independent_action(seat, obs)
                    if chosen != independent_value: raise ValueError("Independent observation-policy disagreement")
                checks.append(dict(seat=seat, phase=request.phase_id, observation_sha256=old.digest(obs), independent=True))
            if mutate: chosen = mutate(request, chosen)
            text = json.dumps(chosen, allow_nan=False)
        transcript.append(dict(seat=seat, phase=request.phase_id, observation=obs, response=text))
        return text
    result = await run_episode(cell=cell, case=manifest, plugin=plugin, response_source=source)
    if tape is not None and len(tape) != len(transcript): raise ValueError("Unconsumed replay actions")
    parse_errors = [a.parse.error_code for p in result.phase_instances for a in p.actions if not a.parse.ok]
    out = old.plain(result.outcome)
    return dict(case_id=case.case_id, pair_id=case.pair_id, seed=case.seed, seat=case.seat, arm=arm,
        case_sha256=manifest.content_sha256, source_sha256=case.base.source_sha256,
        implementation_sha256=old.digest(sources()), transcript=transcript, state=old.plain(result.final_state),
        outcome=out, strict=out["seat_strict"][case.seat] if not parse_errors else None,
        validity=not parse_errors, parse_errors=parse_errors, independent_checks=checks,
        real_provider_calls=0, real_cost_usd=0)


async def verify_replay(case, record):
    replay = await execute(case, record["arm"], tape=record["transcript"])
    # Certificate checks are derived extra evidence, not actions/replay inputs.
    replay["independent_checks"] = record["independent_checks"]
    if replay != record: raise ValueError("Lifecycle state/score replay mismatch")
    return True
