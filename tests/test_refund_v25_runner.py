import asyncio
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from aeread_families.refund.v2_5_policy import build_unified_panel, payment_ledger, policy_fact_dependency_graph, policy_required_fact_ids, policy_requestable_fact_ids, render_policy_contract, resolve_policy
from aeread_families.refund.v2_5_runner import PROMPTS, RefundV25Plugin, _load_env_file, admit_panel, build_refund_v25_run, family_manifest, main, run
from aeread_families.refund import v2_5_measurement as measurement
from aeread.shared_runner.task.scheduler import ActionEnvelope, LegalityResult, ParseResult
from aeread.shared_runner.run.resolver import ImplementationPin


def test_v25_measurement_scorecard_is_compact():
    assert measurement.DIMENSIONS == (
        "policy_semantic", "workflow", "payment", "evidence", "contract",
        "end_to_end", "operational",
    )


def test_v25_controlled_plan_replaces_exactly_one_seat():
    for active in ("customer", "intake", "policy", "payments"):
        setup = build_refund_v25_run(active_agents=(active,))
        assert len(setup.plan.cells) == 24
        assert all(active in cell.profile_by_seat[active] for cell in setup.plan.cells)
        assert all("scripted" in cell.profile_by_seat[seat] for cell in setup.plan.cells for seat in cell.profile_by_seat if seat != active)


def test_v25_env_file_loader_preserves_existing_environment(monkeypatch, tmp_path):
    env_path = tmp_path / "env.local"
    env_path.write_text("# local-only test data\nV25_TEST_EXISTING=from-file\nexport V25_TEST_NEW='loaded-value'\n")
    monkeypatch.setenv("V25_TEST_EXISTING", "already-set")

    _load_env_file(env_path)

    import os

    assert os.environ["V25_TEST_EXISTING"] == "already-set"
    assert os.environ["V25_TEST_NEW"] == "loaded-value"


def test_v25_observations_enforce_seat_visibility():
    case = build_unified_panel(1)[0]
    plugin = RefundV25Plugin()
    state = plugin.initial_state(case, None)
    phases = {phase.phase_id: phase for phase in plugin.phases(case)}

    customer = plugin.observe(case, state, "customer", phases["customer_claim"])
    intake = plugin.observe(case, state, "intake", phases["intake_request"])
    policy = plugin.observe(case, state, "policy", phases["policy_turn"])
    payments = plugin.observe(case, state, "payments", phases["payments_execute"])

    assert "private_facts" in customer and "policy_contract" not in customer
    assert "private_facts" not in intake and "revealed_facts" not in intake
    assert "policy_contract" in policy and "private_facts" not in policy
    assert "required_fact_ids" not in policy
    assert set(payments) == {"phase_id", "execution_ticket"}
    assert payments["execution_ticket"] is None


def test_v25_intake_is_value_blind_but_must_route_away_from_decoys():
    case = next(case for case in build_unified_panel(1) if case.interaction.scenario == "refund_already_issued_chargeback_pending")
    observation = RefundV25Plugin().observe(case, RefundV25Plugin().initial_state(case, None), "intake", {phase.phase_id: phase for phase in RefundV25Plugin().phases(case)}["intake_request"])

    assert "required_fact_ids" not in observation
    assert observation["routing_plan"]["route_kind"] == "payment_state"
    assert "customer_sentiment" in observation["available_fact_ids"]
    assert "customer_sentiment" not in observation["routing_plan"].values()


def test_v25_frontier_hard_intake_routes_open_the_correct_branch():
    from aeread_families.refund.v2_5_policy import intake_routing_plan

    cases = build_unified_panel(1, include_policy_frontier_hard_extension=True)
    expected = {
        "frontier_hard_authority_flip": "evidence",
        "frontier_hard_payment_identity": "identity",
        "frontier_hard_evidence_stop": "identity",
        "frontier_hard_evidence_reversal": "evidence",
        "frontier_hard_override_liability": "eligibility",
        "frontier_hard_piecewise_tax": "verification",
        "frontier_hard_window_override": "eligibility",
        "frontier_hard_refund_reconciliation": "verification",
    }
    for scenario, route in expected.items():
        case = next(item for item in cases if item.interaction.scenario == scenario)
        assert intake_routing_plan(case)["route_kind"] == route


def test_v25_payment_ledger_requires_exact_original_tender_allocations():
    case = next(case for case in build_unified_panel(1) if case.interaction.scenario == "discounted_bundle_component_value")
    amount = resolve_policy(case).amount
    ledger = payment_ledger(case, amount)

    assert ledger["state"] == "captured_multi_tender"
    assert round(sum(row["amount"] for row in ledger["refund_allocations"]), 2) == amount
    assert len(ledger["refund_allocations"]) == 2


def test_v25_operational_extension_has_eight_counterfactual_pairs():
    cases = build_unified_panel(1, include_operational_extension=True)
    extension = [case for case in cases if case.interaction.scenario.startswith(("intake_", "payments_"))]

    assert len(cases) == 40
    assert len(extension) == 16
    assert {case.interaction.pair_id for case in extension} == {
        "v25_intake_identity", "v25_intake_evidence",
        "v25_payment_tender", "v25_payment_idempotency",
        "v25_payment_waterfall", "v25_payment_rounding",
        "v25_payment_reconcile", "v25_payment_rail",
    }


def test_v25_policy_stress_extension_is_nonleaky_and_conditional():
    cases = build_unified_panel(1, include_policy_stress_extension=True)
    extension = [case for case in cases if case.interaction.scenario.startswith("policy_")]
    assert len(cases) == 48
    assert len(extension) == 24

    mismatch = next(case for case in extension if case.interaction.scenario == "policy_identity_override" and case.interaction.variant == "serial_mismatch")
    contract = render_policy_contract(mismatch)
    assert "Rule catalogue:" in contract and "Fact dependency graph:" in contract
    assert "Canonical policy_basis and reason_code identifier for this fact pattern:" not in contract
    revealed = {key: mismatch.facts[key] for key in ("inspection_stage", "order_serial", "inspection_serial")}
    assert policy_requestable_fact_ids(mismatch, revealed) == ()
    assert policy_required_fact_ids(mismatch, revealed) == ()

    hold = next(case for case in extension if case.interaction.scenario == "policy_payment_hold_precedence" and case.interaction.variant == "chargeback_open")
    assert policy_required_fact_ids(hold, {"chargeback_state": "pending"}) == ()

    for pair_id in ("v25_policy_identity_followup", "v25_policy_reconcile_hold"):
        pair = [case for case in extension if case.interaction.pair_id == pair_id]
        assert len(pair) == 2
        assert pair[0].interaction.public_claim == pair[1].interaction.public_claim
        assert render_policy_contract(pair[0]) == render_policy_contract(pair[1])

    admit_panel(tuple(cases), include_policy_stress_extension=True)


def test_v25_policy_stress_extension_provider_free_conformance(tmp_path):
    async def check() -> None:
        report = await run(output=tmp_path, active_agents=("policy",), include_policy_stress_extension=True)
        assert report["planned_cells"] == report["completed_cells"] == 48
        assert report["operational_failures"] == 0

    asyncio.run(check())


def test_v25_frontier_branch_traces_are_conditional():
    from aeread_families.refund.v2_5_policy import build_policy_frontier_panel

    cases = build_policy_frontier_panel(1)
    ladder = next(c for c in cases if c.interaction.scenario == "frontier_precedence_ladder" and c.interaction.variant == "serial_mismatch")
    assert policy_requestable_fact_ids(ladder, {}) == ("chargeback_state",)
    assert policy_requestable_fact_ids(ladder, {"chargeback_state": "pending"}) == ()
    assert policy_requestable_fact_ids(ladder, {"chargeback_state": "none"}) == ("inspection_stage", "order_serial", "inspection_serial")
    identity = {"chargeback_state": "none", "inspection_stage": "post_return_warehouse", "order_serial": "L-1", "inspection_serial": "L-2"}
    assert policy_requestable_fact_ids(ladder, identity) == ()

    reversal = next(c for c in cases if c.interaction.scenario == "frontier_branch_reversal" and c.interaction.variant == "no_prior_refund")
    assert policy_requestable_fact_ids(reversal, {}) == ("chargeback_state",)
    assert policy_requestable_fact_ids(reversal, {"chargeback_state": "none"}) == ("prior_refund_state",)
    assert policy_requestable_fact_ids(reversal, {"chargeback_state": "none", "prior_refund_state": "issued"}) == ()
    assert policy_requestable_fact_ids(reversal, {"chargeback_state": "none", "prior_refund_state": "none"}) == ("defect_evidence",)


def test_v25_frontier_four_seat_provider_free_conformance(tmp_path):
    async def check() -> None:
        for active in ("customer", "intake", "policy", "payments"):
            report = await run(output=tmp_path / active, active_agents=(active,), include_policy_frontier_extension=True)
            assert report["planned_cells"] == report["completed_cells"] == 36
            assert report["operational_failures"] == 0

    asyncio.run(check())


def test_v25_frontier_hard_branch_traces():
    from aeread_families.refund.v2_5_policy import build_policy_frontier_hard_panel

    cases = build_policy_frontier_hard_panel(1)
    payment = next(c for c in cases if c.interaction.scenario == "frontier_hard_payment_identity")
    assert policy_requestable_fact_ids(payment, {}) == ("chargeback_state",)
    assert policy_requestable_fact_ids(payment, {"chargeback_state": "pending"}) == ()
    assert policy_requestable_fact_ids(payment, {"chargeback_state": "none"}) == ("inspection_stage", "order_serial", "inspection_serial")
    stop = next(c for c in cases if c.interaction.scenario == "frontier_hard_evidence_stop")
    assert policy_requestable_fact_ids(stop, {"inspection_stage": "post_return_warehouse", "order_serial": "S-1", "inspection_serial": "S-1"}) == ("defect_evidence",)
    assert policy_requestable_fact_ids(stop, {"inspection_stage": "post_return_warehouse", "order_serial": "S-1", "inspection_serial": "S-1", "defect_evidence": "customer_assertion"}) == ()


def test_v25_frontier_hard_contract_branches_match_reference():
    from aeread_families.refund.v2_5_policy import build_policy_frontier_hard_panel

    cases = build_policy_frontier_hard_panel(101)
    pairs = {}
    for case in cases:
        pairs.setdefault(case.interaction.pair_id, []).append(case)
        expected = resolve_policy(case)
        contract = render_policy_contract(case)
        graph = policy_fact_dependency_graph(case)
        assert expected.policy_basis in contract
        assert expected.workflow in contract
        assert all(fact in graph for fact in expected.required_fact_ids)
        assert all(fact in graph for fact in case.interaction.changed_fact_ids)

    by_scenario = {case.interaction.scenario: cases for cases in pairs.values() for case in cases}
    expected_workflows = {
        "frontier_hard_authority_flip": {"authoritative_mismatch": "identity_review", "non_authoritative_mismatch": "execute_refund"},
        "frontier_hard_override_liability": {"buyer_caused": "seller_review", "carrier_damage": "execute_refund"},
        "frontier_hard_payment_identity": {"serial_mismatch": "identity_review", "serial_match": "execute_refund"},
        "frontier_hard_evidence_reversal": {"stale_listing": "seller_review", "current_listing": "execute_refund"},
        "frontier_hard_window_override": {"ordinary_late": "no_mutation", "fault_late": "execute_refund"},
        "frontier_hard_refund_reconciliation": {"positive_residual": "execute_refund", "zero_residual": "payment_review"},
        "frontier_hard_evidence_stop": {"assertion": "request_evidence", "verified": "execute_refund"},
    }
    for scenario, variants in expected_workflows.items():
        observed = {case.interaction.variant: resolve_policy(case).workflow for case in by_scenario[scenario]}
        assert observed == variants

    amount_pair = by_scenario["frontier_hard_piecewise_tax"]
    amounts = {case.interaction.variant: resolve_policy(case).amount for case in amount_pair}
    assert round(amounts["at_cap"] - amounts["below_cap"], 2) == 0.01
    for case in amount_pair:
        facts = case.interaction.facts
        cap = round(case.interaction.item_net_price * facts["category_cap_rate"], 2)
        expected_amount = round(min(facts["paid_component_allocation"], cap) + facts["allocated_component_tax"], 2)
        assert resolve_policy(case).amount == expected_amount


def test_v25_comparison_seeds_change_substantive_shared_facts():
    from aeread_families.refund.v2_5_policy import build_policy_frontier_hard_panel

    panels = {seed: build_policy_frontier_hard_panel(seed) for seed in (101, 102, 103)}
    for seed, cases in panels.items():
        pairs = {}
        for case in cases:
            pairs.setdefault(case.interaction.pair_id, []).append(case)
        assert len(pairs) == 8
        for left, right in pairs.values():
            actual = {fact for fact in left.facts if left.facts[fact] != right.facts[fact]}
            assert actual == set(left.interaction.changed_fact_ids)
            assert render_policy_contract(left) == render_policy_contract(right)
        assert len({case.case_id for case in cases}) == 16
    first, second = panels[101], panels[102]
    changed = {case.interaction.scenario for case, other in zip(first, second, strict=True)
               if case.interaction.facts != other.interaction.facts}
    assert len(changed) >= 5


def test_v25_frontier_hard_four_seat_provider_free_conformance(tmp_path):
    async def check() -> None:
        for active in ("customer", "intake", "policy", "payments"):
            report = await run(output=tmp_path / active, active_agents=(active,), include_policy_frontier_hard_extension=True)
            assert report["planned_cells"] == report["completed_cells"] == 40
            assert report["operational_failures"] == 0
            assert all(
                score["primary"]["value"] == 1.0
                for receipt in report["receipts"]
                for score in receipt["scores"]
            )

    asyncio.run(check())


def test_v25_operational_extension_conformance(tmp_path):
    async def check() -> None:
        for active in ("intake", "payments"):
            report = await run(output=tmp_path / active, active_agents=(active,), include_operational_extension=True)
            assert report["planned_cells"] == report["completed_cells"] == 40
            assert report["operational_failures"] == 0

    asyncio.run(check())


def test_v25_provider_free_conformance_for_each_active_seat(tmp_path):
    dimensions = (
        "policy_semantic", "workflow", "payment", "evidence", "contract",
        "end_to_end", "operational",
    )

    async def check() -> None:
        for active in ("customer", "intake", "policy", "payments"):
            report = await run(output=tmp_path / active, active_agents=(active,))
            assert report["planned_cells"] == report["completed_cells"] == 24
            assert report["operational_failures"] == 0

    asyncio.run(check())

    # Replaying from the sealed artifacts checks every active-seat trajectory.
    import json

    for active in ("customer", "intake", "policy", "payments"):
        outcomes = []
        for path in (tmp_path / active).glob("runplan_*/tasks/*/attempts/*/artifacts/sha256/*/*"):
            try:
                value = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(value.get("outcome"), dict):
                outcomes.append(value["outcome"])
        assert len(outcomes) == 24
        assert all(all(outcome[dimension] == 1.0 for dimension in dimensions) for outcome in outcomes)


def test_v25_contract_failure_preserves_raw_policy_attribution():
    case = build_unified_panel(1)[0]
    expected = asdict(resolve_policy(case))
    candidate = {
        "action": "submit_resolution",
        "requested_fact_ids": [],
        **expected,
        "reason_code": expected["policy_basis"],
    }
    candidate.pop("refund_method")
    terminal = {
        "policy_candidate": candidate,
        "proposal": None,
        "revealed_facts": dict(case.facts),
        "confirmed_proposal_id": None,
        "transactions": [],
        "failures": ["incomplete_resolution"],
    }

    outcome = RefundV25Plugin().outcome(case, terminal)

    assert outcome["policy_semantic"] == outcome["workflow"] == outcome["payment"] == 1.0
    assert outcome["evidence"] == outcome["operational"] == 1.0
    assert outcome["contract"] == outcome["end_to_end"] == 0.0
    assert outcome["coverage_by_dimension"]["payment"] == 0.5
    assert "contract_missing_refund_method" in outcome["taxonomy_by_dimension"]["contract"]


def test_v25_rejected_resolution_keeps_semantic_candidate():
    case = build_unified_panel(1)[0]
    plugin = RefundV25Plugin()
    state = plugin.initial_state(case, None)
    expected = asdict(resolve_policy(case))
    submitted = {"action": "submit_resolution", "requested_fact_ids": [], **expected,
                 "reason_code": expected["policy_basis"]}
    phase = next(p for p in plugin.phases(case) if p.phase_id == "policy_turn")
    parsed = ParseResult.success(submitted)
    envelope = ActionEnvelope("policy", False, None, parsed, LegalityResult.illegal("decision_before_required_facts"))
    terminal = plugin.step(case, state, phase, {"policy": envelope}).state
    outcome = plugin.outcome(case, terminal)
    assert outcome["policy_semantic"] == 1.0
    assert outcome["coverage_by_dimension"]["policy_semantic"] == 1.0
    assert outcome["evidence"] == outcome["end_to_end"] == 0.0
    assert "protocol_policy_candidate_missing" not in outcome["taxonomy"]


def _candidate_terminal(case, **overrides):
    expected = asdict(resolve_policy(case))
    return {
        "policy_candidate": {"action": "submit_resolution", "requested_fact_ids": [],
                             **expected, "reason_code": expected["policy_basis"], **overrides},
        "proposal": None, "revealed_facts": dict(case.facts),
        "confirmed_proposal_id": None, "transactions": [], "failures": [],
    }


@pytest.mark.parametrize("field,alias,canonical,dimension", [
    ("eligibility", "not_eligible", "ineligible", "policy_semantic"),
    ("eligibility", "requires_clarification", "unresolved", "policy_semantic"),
    ("remedy", "refund", "full_refund", "policy_semantic"),
    ("remedy", "deny_refund", "none", "policy_semantic"),
    ("remedy", "issue_clarification", "none", "policy_semantic"),
    ("workflow", "refund", "execute_refund", "workflow"),
    ("workflow", "approve_refund", "execute_refund", "workflow"),
    ("workflow", "deny", "no_mutation", "workflow"),
    ("workflow", "deny_refund", "no_mutation", "workflow"),
    ("payment_mutation", "refund", "execute", "payment"),
    ("payment_mutation", "no_refund", "none", "payment"),
    ("return_shipping_payer", "buyer", "customer", "policy_semantic"),
    ("return_shipping_payer", "not_applicable", "none", "policy_semantic"),
])
def test_v25_unambiguous_v24_aliases_only_affect_attribution(field, alias, canonical, dimension):
    case = next(case for case in build_unified_panel(1) if asdict(resolve_policy(case))[field] == canonical)
    terminal = _candidate_terminal(case, **{field: alias})
    outcome = RefundV25Plugin().outcome(case, terminal)
    assert outcome[dimension] == outcome["policy_semantic"] == outcome["workflow"] == outcome["payment"] == 1.0
    assert outcome["contract"] == outcome["end_to_end"] == 0.0
    assert f"contract_noncanonical_{field}" in outcome["taxonomy_by_dimension"]["contract"]
    assert terminal["policy_candidate"][field] == alias


@pytest.mark.parametrize("field,dimension", [
    ("eligibility", "policy_semantic"), ("remedy", "policy_semantic"),
    ("return_shipping_payer", "policy_semantic"), ("workflow", "workflow"),
    ("payment_mutation", "payment"), ("refund_method", "payment"),
])
@pytest.mark.parametrize("value", ["unknown", "REFUND", [], {}, None, True, 1])
def test_v25_unknown_or_unhashable_values_fail_safely(field, dimension, value):
    case = build_unified_panel(1)[0]
    outcome = RefundV25Plugin().outcome(case, _candidate_terminal(case, **{field: value}))
    assert outcome[dimension] < 1.0
    assert outcome["contract"] == outcome["end_to_end"] == 0.0
    assert f"contract_noncanonical_{field}" in outcome["taxonomy_by_dimension"]["contract"]


def test_v25_clarification_alias_does_not_invent_a_v25_route():
    case = next(case for case in build_unified_panel(1) if resolve_policy(case).workflow == "request_evidence")
    outcome = RefundV25Plugin().outcome(case, _candidate_terminal(case, workflow="clarify_issue"))
    assert outcome["workflow"] == outcome["contract"] == 0.0


@pytest.mark.parametrize("amount", [[], {}, None, True, "0", float("nan"), float("inf"), -1, 10**400])
def test_v25_invalid_amount_types_fail_safely(amount):
    case = build_unified_panel(1)[0]
    terminal = _candidate_terminal(case, amount=amount)
    outcome = RefundV25Plugin().outcome(case, terminal)
    assert outcome["policy_semantic"] == 0.75
    assert outcome["contract"] == 0.0
    assert "contract_noncanonical_amount" in outcome["taxonomy"]
    plugin = RefundV25Plugin()
    phase = next(p for p in plugin.phases(case) if p.phase_id == "policy_turn")
    state = {**plugin.initial_state(case, None), "revealed_facts": dict(case.facts)}
    assert not plugin.legal(case, state, "policy", phase, terminal["policy_candidate"]).legal


def test_v25_partial_semantics_report_coverage_and_fail_strict_primary():
    case = build_unified_panel(1)[0]
    terminal = _candidate_terminal(case)
    for field in ("amount", "remedy", "refund_method"):
        terminal["policy_candidate"].pop(field)
    outcome = RefundV25Plugin().outcome(case, terminal)
    assert outcome["policy_semantic"] == outcome["payment"] == 1.0
    assert outcome["coverage_by_dimension"]["policy_semantic"] == 0.5
    assert outcome["coverage_by_dimension"]["payment"] == 0.5
    score_set = measurement.build_scorer(case)(SimpleNamespace(outcome=outcome))
    assert score_set.primary_leaf_id == measurement.END_TO_END_LEAF_ID
    assert score_set.scores[0].primary.value == 0.0
    declared = family_manifest().measurement
    assert declared.primary_estimand == "refund_v25_end_to_end"
    assert declared.primary_leaf_id == score_set.primary_leaf_id
    assert set(declared.admission_leaf_ids) == set(score_set.admission_leaf_ids)


def test_v25_partial_alias_candidate_keeps_contract_attribution():
    case = next(case for case in build_unified_panel(1) if resolve_policy(case).remedy == "full_refund")
    terminal = _candidate_terminal(case, remedy="refund")
    terminal["policy_candidate"].pop("refund_method")
    outcome = RefundV25Plugin().outcome(case, terminal)
    assert outcome["policy_semantic"] == outcome["payment"] == 1.0
    assert outcome["coverage_by_dimension"]["payment"] == 0.5
    assert outcome["contract"] == 0.0
    assert "contract_noncanonical_remedy" in outcome["taxonomy_by_dimension"]["contract"]


@pytest.mark.parametrize("repetitions", [0, -1, True, False, 1.5, "3", None])
def test_v25_repetitions_must_be_positive_integers(repetitions, tmp_path):
    with pytest.raises(ValueError, match="positive integer"):
        build_refund_v25_run(repetitions=repetitions)
    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(run(output=tmp_path, repetitions=repetitions))


def test_v25_repeat_identity_and_comparison_analysis_contract():
    setup = build_refund_v25_run(repetitions=3, comparison_campaign=True)
    assert len(setup.plan.cells) == len({cell.cell_id for cell in setup.plan.cells}) == 72
    assert setup.plan.evaluation_blocks[0].repetitions == 3
    assert setup.plan.sampling.replicates == 1
    for case in setup.plan.cases:
        repeats = [cell for cell in setup.plan.cells if cell.case_id == case.case_id]
        assert {cell.block_repetition for cell in repeats} == {0, 1, 2}
        assert {cell.replicate_index for cell in repeats} == {0, 1, 2}
        assert {cell.sampling_replicate for cell in repeats} == {0}
    analysis = asdict(setup.plan.analysis)
    assert analysis == {
        "spec_version": "aeread.analysis/0.1",
        "analysis_plan_id": "refund_v25_policy_comparison_branch_v1",
        "estimands": measurement.ESTIMANDS,
        "group_by": ("family_id", "subject_role", "product_category", "scenario"),
        "missingness": "report_separately", "resampling_unit": "template",
        "uncertainty": "stratified_template_bootstrap", "multiplicity": "holm",
        "sensitivity": ("failure_taxonomy", "counterfactual_pairs"),
        "cross_family_scalar": "disabled",
    }
    default = build_refund_v25_run().plan
    assert len(default.cells) == 24
    assert {cell.world_seed for cell in default.cells} == {1}
    assert default.analysis.analysis_plan_id == "refund_v25_branch_contract_v2_attribution"
    assert (default.analysis.resampling_unit, default.analysis.uncertainty, default.analysis.multiplicity) == ("world_seed", "none", "none")


def test_v25_comparison_override_admits_all_extensions_and_keeps_supplied_seeds(monkeypatch, tmp_path):
    from aeread_families.refund import v2_5_runner as runner
    from aeread_families.refund.v2_5_policy import build_policy_frontier_hard_panel

    cases = tuple(case for seed in (201, 202, 203) for case in build_policy_frontier_hard_panel(seed)[:2])
    pin = ImplementationPin.from_dict({"component_id": "refund_v25_v3_analysis", "kind": "reference", "version": "3.0.0", "sha256": "a" * 64})
    admission = runner.admit_panel
    calls = []

    def check_admission(panel, **flags):
        calls.append(flags)
        assert panel == cases
        return admission(panel, **flags)

    def forbidden_generator(*args, **kwargs):
        raise AssertionError("override must bypass panel generation")

    monkeypatch.setattr(runner, "admit_panel", check_admission)
    monkeypatch.setattr(runner, "build_unified_panel", forbidden_generator)
    setup = build_refund_v25_run(cases=cases, repetitions=3, comparison_campaign=True, extra_implementation_pins=(pin,))
    assert len(setup.plan.cells) == 18
    assert pin in setup.plan.implementation_pins
    assert pin.component_id in setup.plan.families[0].scoring.reference_provider_ids
    assert all(case.split == "dev" for case in setup.plan.cases)
    assert {cell.world_seed for cell in setup.plan.cells} == {201, 202, 203}
    report = asyncio.run(run(output=tmp_path, cases=cases, repetitions=3, comparison_campaign=True, extra_implementation_pins=(pin,)))
    assert report["run_plan_id"] == setup.plan.run_plan_id
    assert report["planned_cells"] == report["completed_cells"] == 18
    assert len({receipt["cell_id"] for receipt in report["receipts"]}) == 18
    assert {receipt["replicate_index"] for receipt in report["receipts"]} == {0, 1, 2}
    assert all(receipt["primary_leaf_id"] == measurement.END_TO_END_LEAF_ID for receipt in report["receipts"])
    assert all(asdict(pin) in receipt["plan_implementation_pins"] for receipt in report["receipts"])
    assert all(receipt["scores"][0]["primary"]["value"] == 1.0 for receipt in report["receipts"])
    assert all(all(flags.values()) for flags in calls)


def test_v25_extra_implementation_pins_bind_run_plan_identity():
    options = {"cases": build_unified_panel(1)[:2], "comparison_campaign": True, "repetitions": 3}
    baseline = build_refund_v25_run(**options)
    first = ImplementationPin.from_dict({"component_id": "refund_v25_v3_config", "kind": "reference", "version": "3.0.0", "sha256": "a" * 64})
    second = ImplementationPin.from_dict({**asdict(first), "sha256": "b" * 64})
    pinned = build_refund_v25_run(**options, extra_implementation_pins=(first,))
    changed = build_refund_v25_run(**options, extra_implementation_pins=(second,))
    assert len({baseline.plan.run_plan_id, pinned.plan.run_plan_id, changed.plan.run_plan_id}) == 3


def test_v25_campaign_dependency_pins_must_be_references():
    pin = ImplementationPin.from_dict({"component_id": "campaign_panel", "kind": "generator", "version": "3.0.0", "sha256": "a" * 64})
    with pytest.raises(ValueError, match="kind=reference"):
        build_refund_v25_run(extra_implementation_pins=(pin,))


def test_v25_empty_case_override_is_rejected():
    with pytest.raises(ValueError, match="selected no cases"):
        build_refund_v25_run(cases=())


@pytest.mark.parametrize("options", [
    {"comparison_campaign": "yes"}, {"comparison_campaign": 1},
    {"comparison_campaign": True, "active_agents": ("intake",)},
    {"comparison_campaign": True, "evaluation_kind": "self_play"},
])
def test_v25_comparison_contract_requires_boolean_and_controlled_policy(options):
    with pytest.raises(ValueError, match="comparison_campaign"):
        build_refund_v25_run(**options)


def test_v25_repetition_cli_and_formula_prompt(tmp_path, capsys):
    case_ids = ",".join(case.case_id for case in build_unified_panel(1)[:2])
    assert main(["--output", str(tmp_path), "--case-ids", case_ids, "--repetitions", "2", "--comparison-campaign"]) == 0
    import json
    report = json.loads(capsys.readouterr().out)
    assert report["planned_cells"] == report["completed_cells"] == 4
    assert "amount (use 0)" not in PROMPTS["policy"]
    assert "Amount formula" in PROMPTS["policy"]
    assert "use 0 for a hold/review" in PROMPTS["policy"]


@pytest.mark.parametrize("requested", [[{}], [[]]])
def test_v25_unhashable_fact_ids_are_rejected(requested):
    import json
    case = build_unified_panel(1)[0]
    plugin = RefundV25Plugin()
    phase = next(p for p in plugin.phases(case) if p.phase_id == "policy_turn")
    action = {"decision": "request_facts", "requested_fact_ids": requested}
    assert not plugin.parse_action(case, {}, "policy", phase, json.dumps(action)).ok
    outcome = plugin.outcome(case, {**_candidate_terminal(case), "policy_candidate": {"action": "request_facts", "requested_fact_ids": requested}})
    assert outcome["evidence"] == 0.0
