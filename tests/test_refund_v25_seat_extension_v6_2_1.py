import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import run_episode
from aeread_families.refund import v2_5_seat_extension_v6_2_1 as v6


@pytest.mark.parametrize("seat,mutation", [
    ("customer", "extra"), ("customer", "missing_message"),
    ("intake", "extra")])
def test_schema_only_failures_preserve_semantics_but_fail_strict(seat, mutation):
    pair = select(seat, "authority_precedence" if seat == "customer" else "horizon")
    def corrupt(request, action):
        if request.seat_id != seat:
            return action
        if mutation == "missing_message" and request.phase_id == "customer_claim":
            return action
        if mutation == "extra":
            action["unexpected_field"] = "not allowed"
        else:
            action.pop("message", None)
        return action
    _, state, outcome = asyncio.run(trajectory(pair, corrupt))
    assert not state["failures"]
    assert outcome["policy_semantic"] == outcome["workflow"] == outcome["payment"] == 1
    assert outcome["contract"] == outcome["end_to_end"] == 0
    assert v6.seat_strict(outcome, state, seat) == 0
    assert any("contract_schema_" in tag for tag in outcome["taxonomy_by_dimension"]["contract"])
    other = "intake" if seat == "customer" else "customer"
    assert v6.seat_strict(outcome, state, other) == 1


@pytest.mark.parametrize("mutation,reason", [
    ("wrong_action", "customer_confirmation_action_mismatch"),
    ("missing_id", "customer_confirmation_missing_proposal_id"),
    ("old_id", "customer_confirmation_stale_proposal"),
    ("wrong_id", "customer_confirmation_proposal_binding_mismatch"),
    ("wrong_terms", "customer_confirmation_terms_mismatch")])
def test_confirmation_taxonomy_preserves_root_cause(mutation, reason):
    pair = select("customer", "scope_binding")
    def corrupt(request, action):
        if request.phase_id != "customer_confirmation":
            return action
        if mutation == "wrong_action":
            action = {"decision":"state_claim", "message":request.observation["public_claim"], "revealed_fact_ids":[]}
        elif mutation == "missing_id":
            action.pop("proposal_id")
        elif mutation == "old_id":
            action["proposal_id"] = request.observation["expired_proposals"][0]["proposal_id"]
        elif mutation == "wrong_id":
            action["proposal_id"] = "unknown"
        else:
            action["confirmed_terms"]["amount"] += .01
        return action
    _, state, outcome = asyncio.run(trajectory(pair, corrupt))
    assert tuple(state["failures"]) == (reason,)
    assert outcome["customer_confirmation_integrity"] == 0


def test_current_prompts_and_single_public_intake_contract():
    panels = v6.build_panels()
    for case in panels["intake"]:
        obs = v6.intake_observation(case, {})
        assert "collection_contract" not in obs and "collection_v5" not in obs
        assert obs["collection_v6"] == case.seat_context["collection_v6"]
    setup = v6.build_run(panels["customer"])
    assert setup.prompt_sources[v6.v3.legacy.PROMPT_IDS["intake"]] == v6.INTAKE_PROMPT
    assert setup.prompt_sources[v6.v3.legacy.PROMPT_IDS["customer"]] == v6.CUSTOMER_PROMPT
    assert "Hand off after this batch" not in v6.INTAKE_PROMPT
    assert "confirmed_terms" in v6.CUSTOMER_PROMPT
    assert v6.schema_errors({"decision":"confirm_resolution", "message":"ok", "revealed_fact_ids":[]},
                            v6.action_schema("customer"))


def test_confirmation_accepts_equal_integer_number_but_rejects_bool():
    pair = select("customer", "scope_binding")[::-1]
    def integer_zero(request, action):
        if request.phase_id == "customer_confirmation":
            assert action["confirmed_terms"]["amount"] == 0.0
            action["confirmed_terms"]["amount"] = 0
        return action
    _, state, outcome = asyncio.run(trajectory(pair, integer_zero))
    assert not state["failures"]
    assert v6.seat_strict(outcome, state, "customer") == 1
    def bool_zero(request, action):
        if request.phase_id == "customer_confirmation":
            action["confirmed_terms"]["amount"] = False
        return action
    _, state, outcome = asyncio.run(trajectory(pair, bool_zero))
    assert tuple(state["failures"]) == ("customer_confirmation_terms_mismatch",)
    assert outcome["customer_confirmation_integrity"] == 0


async def trajectory(cases, corrupt=None):
    setup = v6.build_run(cases); plugin = v6.ExtensionPlugin()
    manifest = setup.plan.cases[0]
    cell = next(c for c in setup.plan.cells if c.case_id == manifest.case_id)
    case = plugin.validate_payload(manifest.payload)
    provider = v6.ScriptedProvider()
    async def source(request):
        inp = {"role": request.seat_id, "phase_id": request.phase_id,
               "observation": json.loads(canonical_json_bytes(request.observation))}
        response = await provider.complete(SimpleNamespace(input_text=json.dumps(inp), model="scripted", revision="6", provider_call_id="offline"))
        action = json.loads(response.output_text)
        if corrupt:
            action = corrupt(request, action)
        return json.dumps(action)
    result = await run_episode(cell=cell, case=manifest, plugin=plugin, response_source=source)
    return case, result.final_state, plugin.outcome(case, result.final_state)


def select(panel, mechanism, seed=301):
    return tuple(c for c in v6.build_panels(seed, True)[panel] if c.seat_context["mechanism"] == mechanism)


def test_counts_pair_labels_and_holdout():
    for seed in (301, 302, 303):
        panels = v6.build_panels(seed)
        assert {k: len(v) for k, v in panels.items()} == {"intake": 12, "customer": 8}
        assert sum(len(v) for v in v6.build_panels(seed, True).values()) == 24
        assert not any(c.seat_context["held_out"] for cases in panels.values() for c in cases)
        for a, b in zip(panels["intake"][::2], panels["intake"][1::2]):
            oa, ob = v6.intake_observation(a, {}), v6.intake_observation(b, {})
            if a.seat_context["pair_effect"] == "hidden_invariance":
                assert oa == ob and v6.intake_plan_reference(oa) == v6.intake_plan_reference(ob)
            else:
                assert oa != ob and v6.intake_plan_reference(oa)[0] != v6.intake_plan_reference(ob)[0]


def test_horizon_really_defeats_myopic_baseline():
    a, b = select("intake", "horizon")
    obs = v6.intake_observation(b, {})
    current = {**obs, "collection_v5": obs["collection_v6"]}
    assert v6.v5.intake_reference(current) != v6.scripted_intake(obs)
    assert len(v6.intake_plan_reference(obs)) == 2
    assert len(v6.intake_plan_reference(v6.intake_observation(a, {}))) == 1


def test_independent_planners_at_every_reachable_state(monkeypatch):
    cases = v6.build_panels(include_holdout=True)["intake"]
    reference = v6.intake_plan_reference
    for case in cases:
        c = case.seat_context["collection_v6"]
        def visit(known, budget, round_number):
            obs = v6.intake_observation(case, {"revealed_facts": {k: case.facts[k] for k in known},
                                             "collection_budget": budget, "collection_round": round_number})
            plan = reference(obs)
            assert v6.scripted_intake(obs) == (list(plan[0]) if plan else [])
            reversed_obs = {**obs, "collection_v6": {**c, "catalogue": list(reversed(c["catalogue"]))}}
            assert reference(reversed_obs) == plan and v6.scripted_intake(reversed_obs) == v6.scripted_intake(obs)
            assert not {"private_facts", "revealed_facts", "reference_resolution", "policy_contract"} & set(obs)
            if round_number < c["max_rounds"]:
                for batch, cost, _ in v6._batches(c, known, budget):
                    visit(set(known) | set(batch), budget - cost, round_number + 1)
        visit(set(), c["total_budget"], 0)
    monkeypatch.setattr(v6, "intake_plan_reference", lambda *_: pytest.fail("script consulted reference"))
    monkeypatch.setattr(v6, "_batches", lambda *_: pytest.fail("script consulted reference enumerator"))
    assert v6.scripted_intake(v6.intake_observation(cases[0], {}))


@pytest.mark.parametrize("panel,mechanism", [
    ("intake", "horizon"), ("intake", "budget"), ("intake", "permission"), ("intake", "batch_capacity"),
    ("intake", "dependency"), ("intake", "hidden_invariance"), ("intake", "permission_horizon_holdout"),
    ("customer", "scope_binding"), ("customer", "asof_revision"), ("customer", "revocation_fallback"),
    ("customer", "authority_precedence"), ("customer", "revocation_scope_holdout")])
def test_complete_both_variants_and_branch_traces(panel, mechanism):
    pair = select(panel, mechanism)
    for cases in (pair, pair[::-1]):
        case, state, outcome = asyncio.run(trajectory(cases))
        assert not state["failures"] and outcome["end_to_end"] == 1
        if panel == "intake":
            spent = 0; known = set()
            rows = {r["fact_id"]: r for r in case.seat_context["collection_v6"]["catalogue"]}
            for event in state["events"]:
                if event["phase"] == "intake_request":
                    obs = event["intake_v6_observation"]
                    assert set(obs["disclosed_fact_ids"]) == known
                    batch = event["action"]["requested_fact_ids"]
                    assert all(set(rows[k]["requires"]) <= known for k in batch)
                    spent += sum(rows[k]["cost"] for k in batch); known.update(batch)
            assert state["collection_budget"] == case.seat_context["collection_v6"]["total_budget"] - spent >= 0
            assert outcome["intake_fact_request_quality"] == 1
        else:
            events = [e for e in state["events"] if e["phase"] == "customer_disclosure"]
            assert len(events) >= 2 and set(events[0]["requested_fact_ids"]) & set(events[1]["requested_fact_ids"])
            assert len(state["expired_proposals"]) == 3
            assert outcome["customer_disclosure_integrity"] == outcome["customer_confirmation_integrity"] == 1


@pytest.mark.parametrize("mutation", ["myopic", "same_batch_unlock", "unauthorized", "decoy", "duplicate"])
def test_intake_negative_controls(mutation):
    mechanism = "permission" if mutation == "unauthorized" else "horizon"
    pair = select("intake", mechanism)
    pair = pair if mutation == "unauthorized" else pair[::-1]
    def corrupt(request, action):
        if request.seat_id != "intake":
            return action
        c = request.observation["collection_v6"]; rows = c["catalogue"]
        if mutation == "myopic":
            action["requested_fact_ids"] = v6.v5.intake_reference({**request.observation, "collection_v5": c})
        elif mutation == "same_batch_unlock":
            dependent = next(r for r in rows if r["requires"])
            action["requested_fact_ids"] = list(dependent["requires"]) + [dependent["fact_id"]]
        elif mutation == "unauthorized":
            action["requested_fact_ids"] = [next(r["fact_id"] for r in rows if r["source"] not in c["authorized_sources"])]
        elif mutation == "decoy":
            action["requested_fact_ids"] = ["document_count"]
        else:
            action["requested_fact_ids"] *= 2
        return action
    _, state, outcome = asyncio.run(trajectory(pair, corrupt))
    assert outcome["end_to_end"] == 0 and outcome["intake_fact_request_quality"] < 1
    if mutation == "myopic":
        assert not state["failures"] and outcome["policy_semantic"] == 1
        assert "intake_suboptimal_horizon_plan" in outcome["taxonomy"]
    else:
        assert tuple(state["failures"]) == ("intake_infeasible_request",)
        assert outcome["coverage_by_dimension"]["policy_semantic"] == 0


@pytest.mark.parametrize("mutation", ["foreign_scope", "future", "unauthorized", "resurrect", "unsolicited", "wrong_type", "old_id", "old_terms"])
def test_customer_negative_controls(mutation):
    pair = select("customer", "revocation_fallback")[::-1]
    def corrupt(request, action):
        obs = request.observation
        if request.phase_id == "customer_disclosure" and mutation not in ("old_id", "old_terms"):
            fact = obs["requested_fact_ids"][0]
            if mutation == "unsolicited":
                extra = next(k for k in pair[0].facts if k not in obs["requested_fact_ids"])
                action["revealed_fact_ids"].append(extra); action["fact_values"][extra] = pair[0].facts[extra]
            elif mutation == "wrong_type":
                action["fact_values"][fact] = {"wrapped": action["fact_values"][fact]}
            elif mutation == "resurrect":
                fact = pair[0].interaction.changed_fact_ids[0]
                if fact not in action["fact_values"]:
                    return action
                action["fact_values"][fact] = next(r["value"] for r in obs["private_fact_records"] if r["fact_id"] == fact and r["document_id"] == "primary" and r["scope"] == "order_A" and r["revision"] == 1)
            else:
                value = {"foreign_scope": "out_of_scope", "future": "future", "unauthorized": "unauthorized"}[mutation]
                action["fact_values"][fact] = value
        elif request.phase_id == "customer_confirmation":
            if mutation == "old_id":
                action["proposal_id"] = obs["expired_proposals"][0]["proposal_id"]
            elif mutation == "old_terms":
                action["confirmed_terms"]["amount"] += .01
        return action
    _, state, outcome = asyncio.run(trajectory(pair, corrupt))
    assert state["failures"] and outcome["end_to_end"] == 0
    assert outcome["customer_confirmation_integrity" if mutation in ("old_id", "old_terms") else "customer_disclosure_integrity"] < 1


def test_customer_reference_order_invariance_visibility_and_independence(monkeypatch):
    cases = v6.build_panels(include_holdout=True)["customer"]
    for case in cases:
        ctx = case.seat_context
        obs = {"requested_fact_ids": list(case.facts), "private_fact_records": ctx["private_records_v6"], "customer_contract_v6": ctx["customer_contract_v6"]}
        assert v6.disclosure_reference(obs) == dict(case.facts) == v6.scripted_disclosure(obs)
        assert v6.scripted_disclosure({**obs, "private_fact_records": list(reversed(obs["private_fact_records"]))}) == dict(case.facts)
        plugin = v6.ExtensionPlugin(); state = plugin.initial_state(case, None)
        phase = next(p for p in plugin.phases(case) if p.phase_id == "customer_disclosure")
        state["pending_requested"] = list(case.facts)
        visible = plugin.observe(case, state, "customer", phase)
        assert not {"private_facts", "reference_resolution", "policy_contract", "source_authorizations"} & set(visible)
    monkeypatch.setattr(v6, "disclosure_reference", lambda *_: pytest.fail("script consulted reference"))
    assert v6.scripted_disclosure(obs) == dict(cases[-1].facts)


@pytest.mark.parametrize("mutation", ["cycle", "ambiguous_revision", "ambiguous_authority", "undeclared", "unsatisfiable"])
def test_admission_rejects_ambiguous_or_undeclared_design(mutation):
    pair = select("intake" if mutation == "cycle" else "customer", "horizon" if mutation == "cycle" else "revocation_fallback")
    a = pair[0]; ctx = copy.deepcopy(a.seat_context)
    if mutation == "cycle":
        ctx["collection_v6"]["catalogue"][0]["requires"] = [ctx["collection_v6"]["catalogue"][1]["fact_id"]]
        ctx["collection_v5"] = ctx["collection_v6"]
    elif mutation == "ambiguous_revision":
        ctx["private_records_v6"].append(copy.deepcopy(ctx["private_records_v6"][0]))
    elif mutation == "ambiguous_authority":
        ctx["customer_contract_v6"]["authorities"][1]["priority"] = 0
    elif mutation == "unsatisfiable":
        ctx["customer_contract_v6"]["as_of"] = 0
    else:
        ctx["stratum"] = "undeclared"
    with pytest.raises(ValueError):
        v6.admit_panels({"bad": (replace(a, seat_context=ctx), pair[1])})


def test_controlled_only_and_scorer_pins():
    cases = v6.build_panels()["customer"]
    with pytest.raises(ValueError, match="exactly one"):
        v6.build_run(cases, active_agents=("customer", "intake"))
    setup = v6.build_run(cases)
    pins = {p.component_id: p for p in setup.plan.implementation_pins}
    for leaf in v6.ExtensionPlugin().build_scorer(cases[0]).leaves:
        ref = leaf.verifier.reference.implementation
        assert leaf.leaf_version == v6.VERSION and ref.content_sha256 == pins[ref.implementation_id].sha256


def test_equal_objective_alternative_is_contract_only_failure():
    pair = select("intake", "dependency")
    first = True
    def alternative(request, action):
        nonlocal first
        if request.seat_id == "intake" and first:
            first = False; action["requested_fact_ids"] = ["order_serial"]
        return action
    _, state, outcome = asyncio.run(trajectory(pair, alternative))
    assert not state["failures"]
    assert outcome["intake_fact_request_quality"] == outcome["policy_semantic"] == 1
    assert outcome["contract"] == outcome["end_to_end"] == 0
    assert outcome["taxonomy_by_dimension"]["intake_fact_request_quality"] == ()
    assert "contract_intake_plan_tiebreak" in outcome["taxonomy_by_dimension"]["contract"]
    assert "intake_suboptimal_horizon_plan" not in outcome["taxonomy"]


def test_intake_assessment_separates_cost_ties_and_utility():
    obs = {"collection_v6": {"catalogue": [
        {"fact_id": "a", "material": True, "source": "S", "requires": [], "cost": 2, "utility": 10},
        {"fact_id": "b", "material": True, "source": "S", "requires": [], "cost": 1, "utility": 10},
        {"fact_id": "c", "material": True, "source": "S", "requires": [], "cost": 1, "utility": 10}],
        "authorized_sources": ["S"], "max_rounds": 1, "max_batch_size": 1, "total_budget": 2},
        "disclosed_fact_ids": [], "remaining_collection_budget": 2, "collection_round": 0}
    assert v6.intake_assessment(obs, ["a"]) == (False, True, "intake_suboptimal_horizon_plan")
    assert v6.intake_assessment(obs, ["b"]) == (True, True, None)
    assert v6.intake_assessment(obs, ["c"]) == (True, False, "contract_intake_plan_tiebreak")


def test_partial_revocation_is_explicitly_fact_scoped_and_order_independent():
    pair = select("customer", "revocation_fallback")
    case = pair[1]; ctx = case.seat_context
    requested = list(case.facts)
    obs = {"requested_fact_ids": requested, "private_fact_records": ctx["private_records_v6"],
           "customer_contract_v6": ctx["customer_contract_v6"]}
    assert "FACT-SCOPED" in obs["customer_contract_v6"]["rule"]
    revoked = {r["fact_id"] for r in obs["private_fact_records"] if r["status"] == "revoked" and r["scope"] == "order_A"}
    assert revoked == set(case.interaction.changed_fact_ids) and revoked != set(requested)
    # Backup is deliberately different for an unaffected fact. Its primary
    # remains authoritative even though another fact in that document revoked.
    other = next(k for k in requested if k not in revoked)
    records = copy.deepcopy(obs["private_fact_records"])
    for row in records:
        if row["fact_id"] == other and row["document_id"] == "backup":
            row["value"] = "must_not_use"
    expected = dict(case.facts)
    for rows in (records, records[::-1]):
        current = {**obs, "private_fact_records": rows}
        assert v6.disclosure_reference(current) == v6.scripted_disclosure(current) == expected


@pytest.mark.parametrize("mutation", ["two_fields", "whole_contract", "undeclared_second_field", "no_op", "unknown_path"])
def test_single_field_admission_cannot_be_bypassed(mutation):
    pair = select("intake", "horizon")
    modified = []
    for case, budget in zip(pair, (1, 2)):
        ctx = copy.deepcopy(case.seat_context)
        if mutation in ("two_fields", "whole_contract", "undeclared_second_field"):
            ctx["collection_v6"]["total_budget"] = budget
        if mutation == "two_fields":
            ctx["changed_public_fields"] = ["collection_v6.max_rounds", "collection_v6.total_budget"]
        elif mutation == "whole_contract":
            ctx["changed_public_fields"] = ["collection_v6"]
        elif mutation == "no_op":
            ctx["changed_public_fields"] = ["collection_v6.total_budget"]
        elif mutation == "unknown_path":
            ctx["changed_public_fields"] = ["collection_v6.not_a_rule"]
        ctx["collection_v5"] = ctx["collection_v6"]
        modified.append(replace(case, seat_context=ctx))
    with pytest.raises(ValueError):
        v6.admit_panels({"bad": tuple(modified)})
