import asyncio
import copy
import itertools
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.refund import v2_5_seat_extension_v5 as v5


def phase(plugin, case, name):
    return next(p for p in plugin.phases(case) if p.phase_id == name)


async def trajectory(cases, corrupt=None):
    setup = v5.build_run(cases); plugin = v5.ExtensionPlugin()
    manifest = setup.plan.cases[0]
    cell = next(c for c in setup.plan.cells if c.case_id == manifest.case_id)
    case = plugin.validate_payload(manifest.payload)
    provider = v5.ScriptedProvider()
    async def source(request):
        inp = {"role": request.seat_id, "phase_id": request.phase_id,
               "observation": json.loads(canonical_json_bytes(request.observation))}
        response = await provider.complete(SimpleNamespace(input_text=json.dumps(inp), model="scripted", revision="5", provider_call_id="offline"))
        action = json.loads(response.output_text)
        if corrupt: action = corrupt(request, action)
        return json.dumps(action)
    result = await run_episode(cell=cell, case=manifest, plugin=plugin, response_source=source)
    return case, result.final_state, plugin.outcome(case, result.final_state)


def test_counts_minimal_pairs_and_holdout_separation():
    for seed in (301, 302, 303):
        development = v5.build_panels(seed)
        assert {k: len(v) for k, v in development.items()} == {"intake": 8, "payments": 12, "customer": 6}
        assert sum(len(v) for v in v5.build_panels(seed, True).values()) == 32
        assert not any(c.seat_context["held_out"] for cases in development.values() for c in cases)
        case = development["intake"][0]
        bad = replace(case, interaction=replace(case.interaction, public_claim="undeclared change"))
        with pytest.raises(ValueError, match="beyond declared"):
            v5.admit_panels({"intake": (bad, development["intake"][1])})


def test_intake_independent_search_order_invariance_and_value_blindness(monkeypatch):
    cases = v5.build_panels()["intake"]
    monkeypatch.setattr(v5.v3, "resolve_policy", lambda *_: pytest.fail("intake consulted policy reference"))
    for case in cases:
        obs = v5.intake_observation(case, {})
        assert not {"private_facts", "reference_resolution", "policy_contract", "revealed_facts"} & set(obs)
        expected = v5.intake_reference(obs)
        for rows in (obs["collection_v5"]["catalogue"], list(reversed(obs["collection_v5"]["catalogue"]))):
            changed = {**obs, "collection_v5": {**obs["collection_v5"], "catalogue": rows}}
            assert v5.scripted_intake(changed) == expected


def test_intake_dependencies_round_trace_and_budget_accounting():
    case, state, outcome = asyncio.run(trajectory(v5.build_panels()["intake"][:2]))
    assert outcome["end_to_end"] == 1
    rows = [e for e in state["events"] if e["phase"] == "intake_request"]
    assert len(rows) >= 2
    collected, spent = set(), 0
    costs = {r["fact_id"]: r for r in case.seat_context["collection_v5"]["catalogue"]}
    for e in rows:
        assert set(e["intake_v5_observation"]["disclosed_fact_ids"]) == collected
        batch = e["action"]["requested_fact_ids"]
        assert all(set(costs[k]["requires"]) <= collected for k in batch)
        spent += sum(costs[k]["cost"] for k in batch); collected.update(batch)
    assert state["collection_budget"] == case.seat_context["collection_v5"]["total_budget"] - spent >= 0
    assert outcome["intake_fact_request_quality"] == 1


@pytest.mark.parametrize("mutation", ["dependency", "metadata", "duplicate", "underfill"])
def test_intake_negative_controls_are_not_policy_reasoning_failures(mutation):
    def corrupt(request, action):
        if request.seat_id != "intake": return action
        obs = request.observation
        if mutation == "dependency":
            row = next(r for r in obs["collection_v5"]["catalogue"] if r["requires"])
            action["requested_fact_ids"] = [row["fact_id"]]
        elif mutation == "metadata": action["requested_fact_ids"] = ["document_count"]
        elif mutation == "duplicate": action["requested_fact_ids"] *= 2
        else: action["requested_fact_ids"] = action["requested_fact_ids"][:1]
        return action
    _, state, outcome = asyncio.run(trajectory(v5.build_panels()["intake"][:2], corrupt))
    assert tuple(state["failures"]) == ("intake_dependency_authorization_budget_error",)
    assert outcome["coverage_by_dimension"]["policy_semantic"] == 0
    assert outcome["end_to_end"] == 0
    assert "policy_conditional_fact_plan_error" not in outcome["taxonomy"]


def test_payment_independent_reducer_permutations_and_exact_conservation():
    for case in v5.build_panels(include_holdout=True)["payments"]:
        proposal = {**asdict(v5.v3.resolve_policy(case)), "proposal_id": "proposal_1"}
        ledger = case.seat_context["payment_ledger"]
        reference = v5.payment_reference(proposal, ledger)
        for records in itertools.permutations(ledger["records"]):
            current = {**ledger, "records": records, "tenders": list(reversed(ledger["tenders"]))}
            assert v5.payment_reference(proposal, current) == reference
            action = v5.scripted_payment({"confirmed_proposal": proposal, "payment_ledger": current})
            action["action"] = action["decision"]
            assert v5.v3.payment_errors(action, reference) == []
            assert sum(v5.v4.cents(r["amount"]) for r in action["refund_allocations"]) == v5.v4.cents(action["amount"])


def test_capacity_shortfall_is_noop_not_truncated_refund():
    cases = [c for c in v5.build_panels()["payments"] if c.seat_context["mechanism"] == "capacity_shortfall"]
    p = {**asdict(v5.v3.resolve_policy(cases[0])), "proposal_id": "proposal_1"}
    a, b = [v5.payment_reference(p, c.seat_context["payment_ledger"]) for c in cases]
    assert a["kind"] == "execute" and b["kind"] == "no_op"
    assert b["amount"] == 0 and b["refund_allocations"] == [] and b["state"] == "pending_reconciliation"


@pytest.mark.parametrize("mutation", ["duplicate", "scope_amount", "allocation", "snapshot"])
def test_payment_negative_controls_and_redelivery(mutation):
    first = None
    def corrupt(request, action):
        nonlocal first
        if request.seat_id != "payments": return action
        if first is None:
            first = dict(action)
            if mutation == "scope_amount": action["amount"] += .01
            elif mutation == "allocation": action["refund_allocations"] = [{"instrument": "wallet", "amount": action["amount"]}]
            elif mutation == "snapshot": action["ledger_snapshot_id"] = "old"
        elif mutation == "duplicate":
            action = {**first, "ledger_snapshot_id": action["ledger_snapshot_id"]}
        return action
    _, state, outcome = asyncio.run(trajectory(v5.build_panels()["payments"][:2], corrupt))
    assert state["failures"] and outcome["payment"] == 0 and outcome["end_to_end"] == 0
    assert outcome["policy_semantic"] == 1
    if mutation == "duplicate": assert len(state["transactions"]) == 1


def test_customer_partial_overlap_terms_and_observation_only_reference():
    cases = [c for c in v5.build_panels()["customer"] if c.seat_context["mechanism"] == "composed_confirmation"]
    _, state, outcome = asyncio.run(trajectory(cases))
    assert outcome["end_to_end"] == 1
    rows = [e for e in state["events"] if e["phase"] == "customer_disclosure"]
    assert set(rows[0]["requested_fact_ids"]) & set(rows[1]["requested_fact_ids"])
    assert len(state["expired_proposals"]) == 3
    confirm = next(e["action"] for e in state["events"] if e["phase"] == "customer_confirmation")
    assert confirm["proposal_id"] == state["proposal"]["proposal_id"]
    assert confirm["confirmed_terms"] == {k: state["proposal"][k] for k in v5.v4.TERMS}


@pytest.mark.parametrize("mutation", ["wrong_source", "revoked", "ceiling", "unsolicited", "old_terms", "old_id"])
def test_customer_negative_controls(mutation):
    def corrupt(request, action):
        obs = request.observation
        if request.phase_id == "customer_disclosure" and mutation in ("wrong_source", "revoked", "ceiling", "unsolicited"):
            fact = obs["requested_fact_ids"][0]
            rule = obs["source_authorizations"][fact]
            if mutation == "unsolicited":
                extra = next(k for k in obs["source_authorizations"] if k not in obs["requested_fact_ids"])
                action["revealed_fact_ids"].append(extra); action["fact_values"][extra] = "extra"
            else:
                row = next(r for r in obs["private_fact_records"] if r["fact_id"] == fact and (
                    r["document_id"] != rule["document_id"] if mutation == "wrong_source" else
                    r["revoked"] if mutation == "revoked" else r["revision"] > rule["max_revision"] and not r["revoked"]))
                action["fact_values"][fact] = row["value"]
        if request.phase_id == "customer_confirmation":
            if mutation == "old_terms": action["confirmed_terms"]["amount"] += .01
            elif mutation == "old_id": action["proposal_id"] = obs["expired_proposals"][0]["proposal_id"]
        return action
    cases = [c for c in v5.build_panels()["customer"] if c.seat_context["mechanism"] == "composed_confirmation"]
    _, state, outcome = asyncio.run(trajectory(cases, corrupt))
    assert state["failures"] and outcome["end_to_end"] == 0


def test_ambiguous_ledger_and_cyclic_dependencies_rejected():
    panels = v5.build_panels()
    c = panels["payments"][0]; context = copy.deepcopy(c.seat_context)
    context["payment_ledger"]["records"].append(copy.deepcopy(context["payment_ledger"]["records"][0]))
    with pytest.raises(ValueError, match="Nonunique"):
        v5.admit_panels({"p": (replace(c, seat_context=context), panels["payments"][1])})
    c = panels["intake"][0]; context = copy.deepcopy(c.seat_context)
    rows = context["collection_v5"]["catalogue"]
    rows[0]["requires"] = [rows[1]["fact_id"]]; rows[1]["requires"] = [rows[0]["fact_id"]]
    with pytest.raises(ValueError, match="Cyclic"):
        v5.admit_panels({"p": (replace(c, seat_context=context), panels["intake"][1])})


def test_controlled_only_schema_and_implementation_pins():
    cases = v5.build_panels()["customer"]
    with pytest.raises(ValueError, match="exactly one"):
        v5.build_run(cases, active_agents=("intake", "customer"))
    setup = v5.build_run(cases, active_agents=("customer",))
    pins = {p.component_id: p for p in setup.plan.implementation_pins}
    for leaf in v5.ExtensionPlugin().build_scorer(cases[0]).leaves:
        assert leaf.leaf_version == "2.5.5"
        ref = leaf.verifier.reference.implementation
        assert ref.content_sha256 == pins[ref.implementation_id].sha256
    profile = next(p for p in setup.plan.agent_profiles if p.prompt.prompt_id == v5.v3.legacy.PROMPT_IDS["customer"])
    assert set(profile.harness.config["output_schema"]["properties"]["confirmed_terms"]["required"]) == set(v5.v4.TERMS)


def test_payment_visibility_before_confirmation_and_revision_before_scope():
    case = v5.build_panels()["payments"][0]
    plugin = v5.ExtensionPlugin(); state = plugin.initial_state(case, None)
    p = {**asdict(v5.v3.resolve_policy(case)), "proposal_id": "proposal_1"}
    state["proposal"] = p
    obs = plugin.observe(case, state, "payments", phase(plugin, case, "payments_execute"))
    assert obs["confirmed_proposal"] is None and obs["payment_ledger"] is None
    assert not {"private_facts", "policy_contract", "reference_resolution"} & set(obs)
    ledger = copy.deepcopy(case.seat_context["payment_ledger"])
    old = {**ledger["records"][0], **ledger["scope"], "revision": 1, "idempotency_key": ledger["idempotency_key"]}
    ledger["records"] = [old, {**old, "revision": 2, "order_id": "unrelated"}]
    result = v5.payment_reference(p, ledger)
    assert result["kind"] == "execute" and result["amount"] == p["amount"]
    assert not result["already_applied"]
