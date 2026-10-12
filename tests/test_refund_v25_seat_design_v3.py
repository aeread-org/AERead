import asyncio
import itertools
import json
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.refund import v2_5_seat_design_v3 as v3


def phase(plugin, case, name):
    return next(p for p in plugin.phases(case) if p.phase_id == name)


def test_panel_counts_and_admission():
    panels = v3.build_panels()
    assert {k: len(v) for k, v in panels.items()} == {"common": 8, "intake": 24, "payments": 18, "customer": 16}
    for cases in panels.values():
        v3.admit_panel(cases)
    assert len({c.product_category for c in panels["common"]}) == 4


def test_observable_pairs_change_only_scope_and_request_not_hidden_outcome():
    cases = [c for c in v3.build_panels()["intake"] if c.seat_context["pair_kind"] == "observable_intake"]
    for left, right in zip(cases[::2], cases[1::2]):
        assert left.facts == right.facts
        assert v3.resolve_policy(left) == v3.resolve_policy(right)
        a, b = v3.intake_observation(left, {}), v3.intake_observation(right, {})
        assert a != b
        assert v3.request_options(a)[0] != v3.request_options(b)[0]
        assert left.interaction.changed_fact_ids == ()
    bad = replace(cases[0], seat_context={**cases[0].seat_context, "changed_public_fields": ["public_claim"]})
    with pytest.raises(ValueError, match="only declared public scope|declaration mismatch"):
        v3.admit_panel((bad, cases[1]))


def test_seeds_change_visible_capacity_and_identity_batch():
    left = next(c for c in v3.build_panels(301)["intake"] if c.seat_context.get("collection_scope") == "identity_documents")
    right = next(c for c in v3.build_panels(302)["intake"] if c.seat_context.get("collection_scope") == "identity_documents")
    a, n = v3.request_options(v3.intake_observation(left, {}))
    b, m = v3.request_options(v3.intake_observation(right, {}))
    assert n != m
    assert a[:n] != b[:m]


def test_equivalent_subsets_and_order_have_equal_quality_and_legality():
    case = next(c for c in v3.build_panels()["intake"] if c.seat_context.get("collection_scope") == "identity_documents")
    plugin = v3.SeatDesignV3Plugin()
    state = plugin.initial_state(case, None)
    obs = v3.intake_observation(case, {})
    allowed, n = v3.request_options(obs)
    for combo in itertools.combinations(allowed, n):
        for permutation in itertools.permutations(combo):
            ids = list(permutation)
            assert v3.request_quality(obs, ids) == 1
            assert plugin.legal(case, state, "intake", phase(plugin, case, "intake_request"), {"action": "request_facts", "requested_fact_ids": ids}).legal
    assert v3.request_quality(obs, allowed[:1]) == .5
    for ids in ([allowed[0], allowed[0]], ["customer_sentiment"], ["nonexistent"]):
        assert v3.request_quality(obs, ids) == 0


def test_intake_contract_and_scripted_provider_do_not_require_hidden_spec(monkeypatch):
    case = v3.build_panels()["intake"][0]
    obs = v3.intake_observation(case, {})
    assert "private_facts" not in obs and "reference_resolution" not in obs and "policy_contract" not in obs
    request = SimpleNamespace(input_text=json.dumps({"role": "intake", "observation": obs}), provider_call_id="offline", model="scripted", revision="3")
    monkeypatch.setattr(v3, "spec_for", lambda *_: pytest.fail("Scripted intake consulted hidden specification"))
    monkeypatch.setattr(v3.legacy, "spec_for", lambda *_: pytest.fail("Scripted intake consulted legacy hidden specification"))
    action = json.loads(asyncio.run(v3.ScriptedSeatV3Provider().complete(request)).output_text)
    assert v3.request_quality(obs, action["requested_fact_ids"]) == 1


def test_ledger_uses_facts_not_scenario_label():
    controls = [c for c in v3.build_panels()["payments"] if c.interaction.scenario == "refund_already_issued_chargeback_pending"]
    assert {c.interaction.variant: v3.payment_ledger(c, 0)["state"] for c in controls} == {"refund_pending": "refund_pending", "chargeback_pending": "chargeback_open"}


def test_payment_shortfall_is_arithmetic_not_id_binding():
    ticket = {"proposal_id": "p", "idempotency_key": "k", "ledger_snapshot_id": "s", "kind": "execute", "amount": 258.08,
              "refund_method": "original_payment", "refund_allocations": [{"instrument": "wallet", "amount": 31.19}, {"instrument": "store_credit", "amount": 17.86}, {"instrument": "card", "amount": 209.03}]}
    good = {**ticket, "action": "execute_refund"}
    assert v3.payment_errors(good, ticket) == []
    wrong = {**good, "refund_allocations": [*ticket["refund_allocations"][:2], {"instrument": "card", "amount": 208.03}]}
    assert set(v3.payment_errors(wrong, ticket)) == {"payment_allocation_conservation_error", "payment_allocation_rule_error"}
    for key, tag in (("proposal_id", "payment_proposal_id_mismatch"), ("idempotency_key", "payment_idempotency_key_mismatch"), ("ledger_snapshot_id", "payment_snapshot_binding_mismatch")):
        assert v3.payment_errors({**good, key: "stale"}, ticket) == [tag]
    duplicate = {**ticket, "kind": "no_op", "already_applied": True, "amount": 0, "refund_method": "none", "refund_allocations": []}
    assert "payment_duplicate_mutation" in v3.payment_errors(good, duplicate)


async def trajectory(cases, corrupt=None):
    setup = v3.build_run(cases=cases)
    plugin = v3.SeatDesignV3Plugin()
    manifest = next(c for c in setup.plan.cases if c.case_id == cases[0].case_id)
    cell = next(c for c in setup.plan.cells if c.case_id == manifest.case_id)
    case = plugin.validate_payload(manifest.payload)
    provider = v3.ScriptedSeatV3Provider()

    async def source(request):
        envelope = SimpleNamespace(input_text=json.dumps({"role": request.seat_id, "observation": json.loads(canonical_json_bytes(request.observation))}),
                                   model="scripted", revision="3", provider_call_id="offline")
        response = await provider.complete(envelope)
        action = json.loads(response.output_text)
        if corrupt:
            action = corrupt(request, action)
        return json.dumps(action)

    result = await run_episode(cell=cell, case=manifest, plugin=plugin, response_source=source)
    return case, result.final_state, plugin.outcome(case, result.final_state)


def test_customer_overlap_supersession_and_expired_confirmation_guard():
    cases = v3.build_panels()["customer"][:2]
    case, state, outcome = asyncio.run(trajectory(cases))
    assert outcome["end_to_end"] == 1
    events = [e for e in state["events"] if e["phase"] == "customer_disclosure"]
    assert set(events[0]["requested_fact_ids"]) & set(events[1]["requested_fact_ids"])
    assert state["expired_proposals"][0]["proposal_id"] != state["proposal"]["proposal_id"]
    plugin = v3.SeatDesignV3Plugin()
    p = phase(plugin, case, "customer_confirmation")
    wrong = {"action": "confirm_resolution", "revealed_fact_ids": [], "proposal_id": state["expired_proposals"][0]["proposal_id"]}
    assert not plugin.legal(case, state, "customer", p, wrong).legal


def test_payment_two_real_deliveries_only_one_transaction_and_negative_retry():
    cases = v3.build_panels()["payments"][:2]
    _, state, outcome = asyncio.run(trajectory(cases))
    events = [e for e in state["events"] if e["phase"] == "payments_execute"]
    assert len(events) == 2
    assert [e["action"]["action"] for e in events] == ["execute_refund", "no_mutation"]
    assert len(state["transactions"]) == 1
    assert outcome["payment_proposal_binding"] == outcome["end_to_end"] == 1
    assert events[0]["execution_ticket"]["idempotency_key"] == events[1]["execution_ticket"]["idempotency_key"]

    def corrupt(request, action):
        if request.observation.get("execution_ticket", {}).get("already_applied"):
            action["decision"] = "execute_refund"
        return action

    _, bad, outcome = asyncio.run(trajectory(cases, corrupt))
    assert tuple(bad["failures"]) == ("payment_duplicate_mutation",)
    assert len(bad["transactions"]) == 1
    assert outcome["end_to_end"] == 0


def test_intake_failure_not_mislabeled_as_policy_failure():
    def corrupt(request, action):
        if request.seat_id == "intake":
            action["requested_fact_ids"] = ["customer_sentiment"]
        return action

    _, _, outcome = asyncio.run(trajectory(v3.build_panels()["intake"][:2], corrupt))
    assert "intake_public_scope_or_priority_error" in outcome["taxonomy"]
    assert "policy_conditional_fact_plan_error" not in outcome["taxonomy"]
    assert outcome["coverage_by_dimension"]["policy_semantic"] == 0


def test_visibility_and_sealed_context():
    cases = v3.build_panels()["customer"][:2]
    setup = v3.build_run(cases=cases)
    plugin = v3.SeatDesignV3Plugin()
    c = plugin.validate_payload(setup.plan.cases[0].payload)
    state = plugin.initial_state(c, None)
    for seat in v3.legacy.ROLES:
        obs = plugin.observe(c, state, seat, phase(plugin, c, "customer_claim"))
        assert "reference_resolution" not in obs
        if seat != "customer":
            assert "private_facts" not in obs
        if seat != "policy":
            assert "policy_contract" not in obs
    assert plugin.observe(c, state, "payments", phase(plugin, c, "payments_execute"))["execution_ticket"] is None
    changed = replace(cases[0], seat_context={**cases[0].seat_context, "overlapping_disclosure": False})
    with pytest.raises(ValueError, match="public seat context"):
        v3.build_run(cases=(changed, cases[1]))


def test_new_verifiers_and_generator_are_pinned_to_new_source():
    setup = v3.build_run(cases=v3.build_panels()["common"])
    scorer = v3.SeatDesignV3Plugin().build_scorer(v3.build_panels()["common"][0])
    pins = {p.component_id: p for p in setup.plan.implementation_pins}
    for leaf in scorer.leaves:
        assert leaf.leaf_version == "2.5.3"
        ref = leaf.verifier.reference.implementation
        assert ref.content_sha256 == pins[ref.implementation_id].sha256
    assert pins["refund_v25_unified_panel"].sha256 == pins["aeread.refund_v25"].sha256


def test_operational_failure_recovery_resolves_registered_plugin_for_case_type():
    cases = v3.build_panels()["common"]
    case = cases[0]
    setup = v3.build_run(cases=cases, active_agents=("policy",), provider="arena",
                         model="gemini-2.5-flash-lite", provider_revision="gemini-2.5-flash-lite")
    registered = setup.registry.resolve("refund_v2", "2.5.0", "aeread.refund_v25")
    assert registered.build_scorer(case).leaves[0].leaf_id == "refund_v25_policy_semantic_leaf"


def test_scripted_paths_on_both_visible_seed_configurations():
    for seed in (301, 302):
        for cases in v3.build_panels(seed).values():
            for offset in range(0, len(cases), 2):
                _, state, outcome = asyncio.run(trajectory(cases[offset:offset + 2]))
                assert not state["failures"]
                assert outcome["end_to_end"] == 1
                assert all(outcome[d] == 1 for d in v3.measurement.COLLABORATION_DIMENSIONS)
