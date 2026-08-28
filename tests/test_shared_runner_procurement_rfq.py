"""Shared-runner conformance tests for the native procurement RFQ family."""
from __future__ import annotations

import asyncio
import json
import pytest

from aeread.shared_runner.execution import execute_plan_cell
from aeread.shared_runner.procurement_rfq import (
    PROCUREMENT_APPROVAL_OUTPUT_SCHEMA,
    PROCUREMENT_AWARD_OUTPUT_SCHEMA,
    PROCUREMENT_COUNTER_OUTPUT_SCHEMA,
    PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA,
    PROCUREMENT_QUOTE_OUTPUT_SCHEMA,
    PROCUREMENT_RFQ_OUTPUT_SCHEMA,
    ProcurementRFQPlugin,
    ProcurementScriptedBuyerProvider,
    ProcurementScriptedSupplierProvider,
    build_procurement_rfq_smoke,
    _scripted_result,
)
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread.shared_runner.family_evaluation import finalize_family_execution, replay_family_receipt
from aeread.shared_runner.housing import OpenRouterRoutePin


DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash-0731"
DEEPSEEK_REVISION = "deepseek/deepseek-v4-flash-20260731"
GEMINI_MODEL = "gemini-3.7-flash"
GEMINI_REVISION = "3.7-flash-08-2026"


def test_procurement_plugin_declares_real_workflow_and_private_observations() -> None:
    setup = build_procurement_rfq_smoke()
    plugin = ProcurementRFQPlugin()
    case = setup.plan.cases[0]
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phases = plugin.phases(family_case)

    assert [phase.phase_id for phase in phases] == [
        "rfq",
        "quote",
        "negotiate",
        "counter",
        "approval",
        "award",
    ]
    buyer = plugin.observe(family_case, state, "buyer_0", phases[0])
    assert "unit_cost" not in str(buyer)
    assert buyer["mandate"]["budget"] == 2400.0
    assert buyer["mandate"]["max_contacts"] == 5


def test_procurement_smoke_seals_roles_schemas_and_typed_references() -> None:
    setup = build_procurement_rfq_smoke()
    plan = setup.plan
    case = plan.cases[0]

    assert [(seat.id, seat.role) for seat in case.seats] == [
        ("buyer_0", "buyer"),
        *[(f"supplier_{seller_id}", "supplier") for seller_id in range(2, 9)],
    ]
    assert case.episode.max_logical_actions == 14

    family = plan.families[0]
    assert family.family.id == "procurement_rfq_v1"
    assert family.measurement.primary_estimand == "buyer_surplus"
    assert family.measurement.optimum_lower_bound == "procurement_rfq_no_action_v1"
    assert family.measurement.comparison_baseline == "procurement_rfq_visible_baseline_v1"
    assert family.measurement.optimum_upper_bound == "procurement_rfq_full_info_terms_v1"
    assert family.measurement.optimum_upper_bound_kind == "full_information_relaxation"

    profiles = {profile.profile_id: profile for profile in plan.agent_profiles}
    buyer = profiles["procurement_scripted_buyer_v1"]
    assert canonical_json_bytes(
        buyer.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(
        {
            "procurement_rfq_v1": PROCUREMENT_RFQ_OUTPUT_SCHEMA,
            "procurement_negotiate_v1": PROCUREMENT_NEGOTIATE_OUTPUT_SCHEMA,
            "procurement_approval_v1": PROCUREMENT_APPROVAL_OUTPUT_SCHEMA,
            "procurement_award_v1": PROCUREMENT_AWARD_OUTPUT_SCHEMA,
        }
    )
    supplier = profiles["procurement_scripted_supplier_v1"]
    assert canonical_json_bytes(
        supplier.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(
        {
            "procurement_quote_v1": PROCUREMENT_QUOTE_OUTPUT_SCHEMA,
            "procurement_counter_v1": PROCUREMENT_COUNTER_OUTPUT_SCHEMA,
        }
    )


def test_procurement_live_probe_seals_openrouter_buyer_and_controlled_suppliers() -> None:
    setup = build_procurement_rfq_smoke(
        buyer_provider="openrouter",
        buyer_model=DEEPSEEK_MODEL,
        buyer_revision=DEEPSEEK_REVISION,
    )

    profiles = {profile.profile_id: profile for profile in setup.plan.agent_profiles}
    buyer = profiles["procurement_deepseek_buyer_v1"]
    assert buyer.model.provider == "openrouter"
    assert buyer.model.model == DEEPSEEK_MODEL
    assert buyer.model.revision == DEEPSEEK_REVISION
    assert buyer.model.base_url == "https://openrouter.ai/api/v1"
    assert buyer.retry_policy.max_action_attempts == 2
    assert buyer.retry_policy.retryable_conditions == ("length",)
    assert buyer.harness.config["provider_metadata"]["route_provider"] == "DeepInfra"
    assert buyer.budgets.max_cost_usd == 0.01
    assert buyer.budgets.timeout_seconds == 180.0
    assert buyer.sampling.max_output_tokens == 2048

    supplier = profiles["procurement_scripted_supplier_v1"]
    assert supplier.model.provider == "procurement_scripted_supplier"
    assert setup.plan.cells[0].profile_by_seat == {
        "buyer_0": "procurement_deepseek_buyer_v1",
        **{
            f"supplier_{seller_id}": "procurement_scripted_supplier_v1"
            for seller_id in range(2, 9)
        },
    }
    assert set(setup.pricing) == {DEEPSEEK_MODEL, "procurement_scripted_supplier_v1"}


def test_procurement_gemini_probe_seals_native_buyer_and_controlled_suppliers() -> None:
    setup = build_procurement_rfq_smoke(
        buyer_provider="google",
        buyer_model=GEMINI_MODEL,
        buyer_revision=GEMINI_REVISION,
    )

    profiles = {profile.profile_id: profile for profile in setup.plan.agent_profiles}
    buyer = profiles["procurement_gemini37_buyer_v1"]
    assert buyer.model.provider == "google"
    assert buyer.model.model == GEMINI_MODEL
    assert buyer.model.revision == GEMINI_REVISION
    assert buyer.model.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert buyer.reasoning.effort == "low"
    assert buyer.sampling.max_output_tokens == 4096
    assert buyer.budgets.timeout_seconds == 90.0
    assert buyer.budgets.max_cost_usd == 0.02
    assert buyer.retry_policy.max_action_attempts == 2
    assert buyer.retry_policy.retryable_conditions == ("length",)
    assert buyer.harness.config["provider_metadata"] == {
        "canonical_model": GEMINI_MODEL,
        "catalog_version": GEMINI_REVISION,
        "thinking_level": "low",
        "max_input_price_per_million": "0.75",
        "max_cached_input_price_per_million": "0.075",
        "max_output_price_per_million": "3.75",
    }

    supplier = profiles["procurement_scripted_supplier_v1"]
    assert supplier.model.provider == "procurement_scripted_supplier"
    assert setup.plan.cells[0].profile_by_seat["buyer_0"] == (
        "procurement_gemini37_buyer_v1"
    )
    assert set(setup.pricing) == {GEMINI_MODEL, "procurement_scripted_supplier_v1"}


def test_provider_free_procurement_cell_executes_and_reconciles_evidence(tmp_path) -> None:
    setup = build_procurement_rfq_smoke()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "procurement_scripted_buyer": ProcurementScriptedBuyerProvider(),
                "procurement_scripted_supplier": ProcurementScriptedSupplierProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )

    result = execution.episode_result
    assert [phase.phase_id for phase in result.phase_instances] == [
        "rfq",
        "quote",
        "negotiate",
        "counter",
        "approval",
        "award",
    ]
    assert result.logical_action_count == 14
    assert result.outcome["valid"] is True
    assert result.outcome["executed"] is True
    assert result.outcome["approval_granted"] is True
    assert result.outcome["buyer_surplus"] == result.outcome["baseline_total"]
    assert 0.0 < result.outcome["buyer_surplus"] < result.outcome["oracle_total"]
    assert result.outcome["disclosed_rfq_count"] == 0
    assert result.outcome["bound_semantics"] == "full_information_terms_relaxation"
    assert execution.total_cost_usd == 0.0
    execution.evidence.audit_reconciliation()


def test_generated_procurement_plans_pair_worlds_not_repeated_fixture_labels():
    common = dict(buyer_provider="google", buyer_model=GEMINI_MODEL,
                  buyer_revision=GEMINI_REVISION, world_seeds=(11, 12), replicates=3)
    low = build_procurement_rfq_smoke(**common, reasoning_effort="low")
    high = build_procurement_rfq_smoke(**common, reasoning_effort="high")
    assert len(low.plan.cases) == 2 and len(low.plan.cells) == 6
    assert low.plan.run_plan_id != high.plan.run_plan_id
    assert low.plan.analysis.uncertainty == "cluster_bootstrap_95"
    assert low.plan.sampling.selection == "seeded_simple_random"
    assert low.plan.cases[0].payload["world"] != low.plan.cases[1].payload["world"]
    assert sorted((c.world_seed, c.replicate_index, c.cluster_id, c.pair_id) for c in low.plan.cells) == sorted(
        (c.world_seed, c.replicate_index, c.cluster_id, c.pair_id) for c in high.plan.cells
    )
    for setup, effort in [(low, "low"), (high, "high")]:
        profile = next(p for p in setup.plan.agent_profiles if p.model.provider == "google")
        assert profile.reasoning.effort == effort
        assert profile.harness.config["provider_metadata"]["thinking_level"] == effort
        assert profile.harness.config["request_seed_source"] == "paired_cell_v1"


@pytest.mark.parametrize("seeds", [(), (1, 1), (True,), (-1,), (1.5,)])
def test_procurement_panel_rejects_bad_world_seeds(seeds):
    with pytest.raises(ValueError, match="seed"):
        build_procurement_rfq_smoke(world_seeds=seeds, replicates=3)


def test_procurement_uses_shared_typed_receipts_and_no_call_replay(tmp_path):
    setup = build_procurement_rfq_smoke()
    execution = asyncio.run(execute_plan_cell(
        plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry,
        evidence_root=tmp_path, prompt_sources=setup.prompt_sources, pricing=setup.pricing,
        providers={"procurement_scripted_buyer": ProcurementScriptedBuyerProvider(),
                   "procurement_scripted_supplier": ProcurementScriptedSupplierProvider()},
    ))
    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert receipt.status == "ok" and receipt.replay_level == "state_and_score"
    assert receipt.scores[0].primary.value == pytest.approx(728.6)
    assert receipt.scores[0].leaf.verifier.verifier_family == "objective_reference"
    assert replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path) == receipt


def test_deepseek_generated_panel_can_seal_the_current_parasail_route():
    route = OpenRouterRoutePin("Parasail", "fp8", DEEPSEEK_REVISION, .14, .05, .28,
                               "openrouter_parasail_2026-08-28_deepseek-v4-flash-0731")
    setup = build_procurement_rfq_smoke(buyer_provider="openrouter", buyer_model=DEEPSEEK_MODEL,
        buyer_revision=DEEPSEEK_REVISION, world_seeds=(11, 12), replicates=3,
        reasoning_effort="none", openrouter_route=route)
    buyer = next(p for p in setup.plan.agent_profiles if p.model.provider == "openrouter")
    assert buyer.reasoning.effort == "none"
    assert buyer.harness.config["provider_metadata"] == route.provider_metadata()
    assert setup.pricing[DEEPSEEK_MODEL] == route.token_pricing()
    assert len(setup.plan.cells) == 6


def test_deepseek_route_revision_cannot_silently_change():
    with pytest.raises(ValueError, match="revision|route"):
        build_procurement_rfq_smoke(buyer_provider="openrouter", buyer_model=DEEPSEEK_MODEL,
                                   buyer_revision="wrong_revision")


def test_live_buyer_output_and_runtime_limits_are_explicit_and_sealed():
    common = dict(buyer_provider="openrouter", buyer_model=DEEPSEEK_MODEL,
                  buyer_revision=DEEPSEEK_REVISION, world_seeds=(11,))
    original = build_procurement_rfq_smoke(**common)
    setup = build_procurement_rfq_smoke(**common, buyer_max_output_tokens=8192,
        buyer_timeout_seconds=600, buyer_max_cost_usd=.04)
    buyer = next(p for p in setup.plan.agent_profiles if p.model.provider == "openrouter")
    supplier = next(p for p in setup.plan.agent_profiles if p.model.provider == "procurement_scripted_supplier")
    assert buyer.sampling.max_output_tokens == 8192
    assert buyer.budgets.timeout_seconds == 600 and buyer.budgets.max_cost_usd == .04
    assert supplier.sampling.max_output_tokens == 512
    assert original.plan.plan_sha256 != setup.plan.plan_sha256


@pytest.mark.parametrize("world_seeds", [None, (336577221,)])
@pytest.mark.parametrize("skip_phase, action", [
    ("rfq", {"decision": "pass", "requests": []}),
    ("rfq", {"decision": "submit", "requests": []}),
    ("negotiate", {"decision": "pass", "counters": []}),
    ("negotiate", {"decision": "counter", "counters": []}),
])
def test_legal_empty_buyer_actions_skip_supplier_phases_and_replay(
    tmp_path, world_seeds, skip_phase, action,
):
    class Buyer(ProcurementScriptedBuyerProvider):
        def __init__(self):
            self.observations = {}

        async def complete(self, request):
            payload = json.loads(request.input_text)
            phase = payload["phase_id"]
            self.observations[phase] = payload["observation"]
            if phase == skip_phase:
                return _scripted_result(request, action)
            return await super().complete(request)

    setup = build_procurement_rfq_smoke(world_seeds=world_seeds)
    buyer = Buyer()
    execution = asyncio.run(execute_plan_cell(
        plan=setup.plan, cell_id=setup.plan.cells[0].cell_id, registry=setup.registry,
        evidence_root=tmp_path, prompt_sources=setup.prompt_sources, pricing=setup.pricing,
        providers={"procurement_scripted_buyer": buyer,
                   "procurement_scripted_supplier": ProcurementScriptedSupplierProvider()},
    ))
    expected_phases = ["rfq", "negotiate", "approval", "award"]
    if skip_phase == "negotiate":
        expected_phases.insert(1, "quote")
        offers = buyer.observations["approval"]["final_offers"]
        quotes = buyer.observations["negotiate"]["opening_quotes"]
        assert offers and len(offers) == len(quotes)
        assert all(offer["source"] == "opening" for offer in offers)
    else:
        assert execution.episode_result.outcome["buyer_surplus"] == 0
    assert [phase.phase_id for phase in execution.episode_result.phase_instances] == expected_phases
    assert set(buyer.observations) == {"rfq", "negotiate", "approval", "award"}
    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert receipt.inclusion_status == "included" and receipt.replay_level == "state_and_score"
    assert replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path) == receipt
