from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.task.execution import ProviderRequest, TokenPricing
from aeread_families.datacenter_development.objective_campaign import (
    build_design as build_objective_campaign_design,
    load_contract as load_objective_campaign_contract,
    run_campaign as run_objective_campaign,
)
from aeread_families.datacenter_development.objective_campaign_v2 import (
    build_design as build_objective_campaign_v2_design,
    load_contract as load_objective_campaign_v2_contract,
    run_campaign as run_objective_campaign_v2,
)
from aeread_families.datacenter_development.objective_campaign_v3 import (
    build_design as build_objective_campaign_v3_design,
    load_contract as load_objective_campaign_v3_contract,
    run_campaign as run_objective_campaign_v3,
)
from aeread_families.datacenter_development.objective_environment import (
    ObjectiveAwareStackPlugin,
)
from aeread_families.datacenter_development.objective_measurement import (
    ObjectiveAwareDataCenterScorer,
)
from aeread_families.datacenter_development.objective_openrouter import (
    ParameterCompatibleOpenRouterClient,
)
from aeread_families.datacenter_development.objective_runner import (
    OBJECTIVE_CASE_PATH,
    OBJECTIVE_PROMPT,
    ObjectiveExactCounterpartyProvider,
    build_objective_stack_setup,
    finalize_objective_stack_execution,
    replay_objective_stack_receipt,
    run_objective_stack_offline,
)
from aeread_families.datacenter_development.stack_runner import load_stack_case
from aeread_families.procurement_grounding.runner import OpenRouterRoute


TEST_ROUTE = OpenRouterRoute(
    profile_id="datacenter_objective_test_route",
    model="test/model",
    revision="test/model:fixed",
    route_provider="test-provider",
    quantization="unknown",
    pricing=TokenPricing(0.0, 0.0, 0.0, "datacenter_objective_test_pricing"),
    max_prompt_price_per_million="0",
    max_completion_price_per_million="0",
    reasoning_effort=None,
)


class _ObjectiveOpenRouterCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            model_dump=lambda mode: {
                "id": "objective_adapter_fixture",
                "model": "test/model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"decision":"walk"}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": 0},
                    "cost": 0.0,
                },
                "openrouter_metadata": {
                    "requested": "test/model",
                    "attempt": 1,
                    "endpoints": {
                        "available": [
                            {
                                "provider": "test-provider",
                                "model": "test/model:fixed",
                                "selected": True,
                            }
                        ]
                    },
                },
            }
        )


def _validated_case():
    case = load_stack_case("v2", OBJECTIVE_CASE_PATH)
    family_case = ObjectiveAwareStackPlugin().validate_payload(case.payload)
    return case, family_case


def _score_by_id(outcome, family_case):
    score_set = ObjectiveAwareDataCenterScorer(family_case)(
        outcome,
        evidence_refs=("event_00000001",),
    )
    return {score.leaf.leaf_id: score for score in score_set.scores}


def test_objective_case_is_hash_pinned_bounded_and_mutually_beneficial() -> None:
    case, family_case = _validated_case()

    assert case.family_version == "2.1.0"
    assert case.content_sha256 == case_content_sha256(case)
    assert family_case["baseline"] == {
        "developer_equity_npv_cents": -95_000,
        "lender_npv_cents": 0,
        "customer_npv_cents": 40_000,
        "total_project_npv_cents": -55_000,
    }
    assert family_case["outside_option"]["developer_equity_npv_cents"] == -100_000
    for policy in family_case["policies"].values():
        numeric = {
            field: value
            for field, value in policy["counter_terms"].items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        assert policy["minimums"] == policy["maximums"] == numeric
        assert set(policy["required_conditions"]) == set(
            policy["counter_terms"]["conditions_precedent"]
        )


def test_objective_case_rejects_unbounded_counterparty_terms() -> None:
    _, family_case = _validated_case()
    unbounded = copy.deepcopy(family_case)
    del unbounded["policies"]["power"]["maximums"][
        "delay_liquidated_damages_cap_cents"
    ]

    with pytest.raises(ValueError, match="bind every numeric counter term"):
        ObjectiveAwareStackPlugin().validate_payload(unbounded)


def test_developer_observes_objective_but_not_private_policy_or_reference() -> None:
    _, family_case = _validated_case()
    plugin = ObjectiveAwareStackPlugin()
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    observation = plugin.observe(family_case, state, "developer", phase)
    serialized = repr(observation)

    assert observation["developer_objective"] == {
        "objective_id": "safe_developer_objective_attainment",
        "decision_rule": (
            "maximize developer_equity_npv_cents subject to completed binding "
            "contracts, project constraints, and temporal compliance"
        ),
        "outside_option_developer_equity_npv_cents": -100_000,
        "explicit_walk_allowed": True,
        "involuntary_failure_is_not_a_walk": True,
        "currency_unit": "cents",
        "project_month_indexing": "one_based",
    }
    assert "policies" not in serialized
    assert "private_policy" not in serialized
    assert "scripted_developer" not in serialized
    assert "baseline" not in serialized


def test_exact_counterparty_counters_any_nonidentical_package() -> None:
    _, family_case = _validated_case()
    target = family_case["policies"]["power"]["counter_terms"]
    provider = ObjectiveExactCounterpartyProvider("utility")

    async def decide(terms):
        request = ProviderRequest(
            provider_call_id="provider_call_test",
            provider="datacenter_stack_scripted_utility",
            base_url=None,
            model="scripted",
            revision="1.0.0",
            instructions="",
            input_text=json.dumps(
                {
                    "phase_id": "power_utility_response",
                    "observation": {
                        "latest_offer": {"offer_id": "offer_test", "terms": terms},
                        "private_policy": family_case["policies"]["power"],
                    },
                }
            ),
            temperature=0.0,
            top_p=None,
            max_output_tokens=1,
            reasoning_effort=None,
            timeout_seconds=1.0,
            request_sha256="0" * 64,
        )
        return json.loads((await provider.complete(request)).output_text)

    exact = asyncio.run(decide(target))
    changed = copy.deepcopy(target)
    changed["delay_liquidated_damages_cap_cents"] += 1
    countered = asyncio.run(decide(changed))

    assert exact["decision"] == "accept"
    assert countered["decision"] == "counter"
    assert countered["terms"] == target


def test_parameter_compatible_openrouter_omits_undeclared_reasoning() -> None:
    completions = _ObjectiveOpenRouterCompletions()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = ParameterCompatibleOpenRouterClient(sdk_client=sdk)
    request = ProviderRequest(
        provider_call_id="provider_call_objective_adapter",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        model="test/model",
        revision="test/model:fixed",
        instructions="Return JSON.",
        input_text="{}",
        temperature=0.0,
        top_p=None,
        max_output_tokens=32,
        reasoning_effort=None,
        timeout_seconds=1.0,
        request_sha256="",
        max_cost_usd=0.01,
        output_schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
            "additionalProperties": False,
        },
        provider_metadata={
            "route_provider": "test-provider",
            "quantization": "unknown",
            "canonical_model": "test/model:fixed",
            "max_prompt_price_per_million": "1",
            "max_completion_price_per_million": "1",
        },
        seed=1,
    ).with_computed_hash()

    result = asyncio.run(client.complete(request))

    assert result.output_text == '{"decision":"walk"}'
    assert "reasoning" not in completions.kwargs["extra_body"]
    assert completions.kwargs["extra_body"]["provider"]["require_parameters"] is True


def test_invalid_action_gets_no_objective_credit_and_walk_is_distinct() -> None:
    _, family_case = _validated_case()
    outside = family_case["outside_option"]["developer_equity_npv_cents"]
    invalid_outcome = {
        "project_completed": False,
        "termination_reason": "invalid_action",
        "binding_contract_integrity": False,
        "project_constraints_satisfied": False,
        "temporal_violations": ["malformed_datacenter_stack_action"],
        "developer_equity_npv_cents": outside,
    }
    invalid = _score_by_id(invalid_outcome, family_case)

    assert invalid["safe_developer_objective_attainment"].primary.value == 0.0
    assert invalid["intentional_resolution"].primary.value == 0.0
    assert invalid["negotiation_temporal_compliance"].primary.value == 0.0

    walked = _score_by_id(
        {
            **invalid_outcome,
            "termination_reason": "developer_walk",
            "temporal_violations": [],
        },
        family_case,
    )
    assert walked["safe_developer_objective_attainment"].primary.value == 0.0
    assert walked["intentional_resolution"].primary.value == 1.0
    assert walked["negotiation_temporal_compliance"].primary.value == 1.0


def test_reference_dominance_violation_cannot_receive_objective_credit() -> None:
    _, family_case = _validated_case()
    above_reference = {
        "project_completed": True,
        "termination_reason": "agreement_stack_executed",
        "binding_contract_integrity": True,
        "project_constraints_satisfied": True,
        "temporal_violations": [],
        "developer_equity_npv_cents": -94_999,
    }
    scores = _score_by_id(above_reference, family_case)

    assert scores["controlled_reference_dominance"].primary.value == 0.0
    assert scores["safe_developer_objective_attainment"].primary.value == 0.0
    assert (
        scores["safe_developer_objective_attainment"].metrics[
            "eligible_completion"
        ].value
        == 0.0
    )


def test_objective_provider_free_run_seals_seven_leaves_and_replays(tmp_path) -> None:
    setup, execution = asyncio.run(
        run_objective_stack_offline(evidence_root=tmp_path)
    )
    receipt = finalize_objective_stack_execution(setup=setup, execution=execution)
    replayed = replay_objective_stack_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=tmp_path,
    )
    score_by_id = {score.leaf.leaf_id: score for score in receipt.scores}

    assert execution.episode_result.logical_action_count == 18
    assert execution.episode_result.outcome["project_completed"] is True
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.primary_leaf_id == "safe_developer_objective_attainment"
    assert len(score_by_id) == 7
    assert score_by_id["safe_developer_objective_attainment"].primary.value == 1.0
    assert score_by_id["controlled_reference_dominance"].primary.value == 1.0
    assert replayed == receipt


def test_live_objective_setup_pins_prompt_family_scorer_and_route() -> None:
    setup = build_objective_stack_setup(route=TEST_ROUTE, seed=312101)
    developer_id = setup.plan.cells[0].profile_by_seat["developer"]
    developer = next(
        profile
        for profile in setup.plan.agent_profiles
        if profile.profile_id == developer_id
    )
    pins = {pin.component_id for pin in setup.plan.implementation_pins}

    assert setup.plan.families[0].family.version == "2.1.0"
    assert developer.model.provider == "openrouter"
    assert developer.prompt.prompt_id == "datacenter_v2_objective_developer_prompt_v1"
    assert setup.prompt_sources[developer.prompt.prompt_id] == OBJECTIVE_PROMPT
    assert all(admission.admitted for admission in setup.plan.profile_admissions)
    assert "datacenter_development_objective_environment_v1" in pins
    assert "datacenter_objective_score_set_v1" in pins
    assert "datacenter_objective_references_v1" in pins
    assert "datacenter_objective_validity_v1" in pins
    assert "aeread_families.datacenter_development.objective_runner" in pins


def test_objective_campaign_is_controlled_paired_and_budget_bounded() -> None:
    contract = load_objective_campaign_contract()
    design = build_objective_campaign_design(contract)

    assert design["planned_cells"] == 6
    assert design["paired_seed_count"] == 3
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.18)
    assert design["campaign_max_cost_usd"] == pytest.approx(0.25)
    assert {
        (cell["condition"], cell["evaluation_block_kind"], cell["live_profile_count"])
        for cell in design["cells"]
    } == {("controlled_exact_package_counterparties", "controlled", 1)}
    assert {
        (cell["inference_seed"], cell["model_id"])
        for cell in design["cells"]
    } == {
        (seed, model_id)
        for seed in contract["inference_seeds"]
        for model_id in contract["models"]
    }

    source_root = OBJECTIVE_CASE_PATH.parents[3] / "src" / "aeread_families" / "datacenter_development"
    for name in (
        "contracts.py",
        "stack_environment.py",
        "stack_runner.py",
        "objective_environment.py",
        "objective_measurement.py",
        "objective_runner.py",
        "objective_campaign.py",
    ):
        assert design["implementation_source_sha256s"][name] == hashlib.sha256(
            (source_root / name).read_bytes()
        ).hexdigest()


def test_objective_campaign_rejects_aggregate_budget_overflow(tmp_path) -> None:
    contract = load_objective_campaign_contract()
    contract["execution"]["max_cost_usd_per_live_profile"] = 0.05
    contract_path = tmp_path / "over_budget.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="cost ceilings"):
        load_objective_campaign_contract(contract_path)


def test_objective_campaign_passes_provider_free_and_admission_gates(tmp_path) -> None:
    summary = asyncio.run(
        run_objective_campaign(
            run_root=tmp_path / "campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 6


def test_objective_campaign_v2_is_new_route_bounded_identity() -> None:
    contract = load_objective_campaign_v2_contract()
    design = build_objective_campaign_v2_design(contract)

    assert design["campaign_id"] == "datacenter_development_v2_objective_grounding_v2"
    assert design["planned_cells"] == 6
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.18)
    assert design["campaign_max_cost_usd"] == pytest.approx(0.25)
    assert set(contract["models"]) == {"mistral32_deepinfra", "qwen38_alibaba"}
    assert {
        contract["models"][cell["model_id"]]["provider"]
        for cell in design["cells"]
    } == {"Alibaba", "DeepInfra"}
    assert "objective_campaign_v2.py" in design["implementation_source_sha256s"]
    assert design["route_catalog_snapshot"] == contract["route_catalog_snapshot"]


def test_objective_campaign_v2_passes_provider_free_and_admission_gates(tmp_path) -> None:
    summary = asyncio.run(
        run_objective_campaign_v2(
            run_root=tmp_path / "campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 6


def test_objective_campaign_v3_binds_parameter_compatible_adapter() -> None:
    contract = load_objective_campaign_v3_contract()
    design = build_objective_campaign_v3_design(contract)

    assert design["campaign_id"] == "datacenter_development_v2_objective_grounding_v3"
    assert design["planned_cells"] == 6
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.18)
    assert design["adapter_implementation_id"] == (
        "datacenter_objective_openrouter_parameter_compatible_v1"
    )
    assert design["adapter_implementation_sha256"] == (
        design["implementation_source_sha256s"]["objective_openrouter.py"]
    )
    assert {model["reasoning_effort"] for model in contract["models"].values()} == {
        None
    }
    assert {
        model["provider"] for model in contract["models"].values()
    } == {"DeepInfra", "Novita"}


def test_objective_campaign_v3_passes_provider_free_and_admission_gates(tmp_path) -> None:
    summary = asyncio.run(
        run_objective_campaign_v3(
            run_root=tmp_path / "campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 6


@pytest.mark.parametrize("version", ("v1", "v2", "v3"))
def test_objective_campaign_publication_is_digest_bound_and_sanitized(
    version: str,
) -> None:
    root = (
        OBJECTIVE_CASE_PATH.parents[3]
        / "evidence"
        / f"datacenter_development_v2_objective_grounding_{version}"
    )
    manifest = json.loads((root / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}

    assert manifest["artifact_sha256"] == hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert len(manifest["source_receipt_sha256s"]) == 6
    assert len(set(manifest["source_receipt_sha256s"])) == 6
    for relative, expected in manifest["files"].items():
        payload = (root / relative).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    public_text = "\n".join(
        path.read_text(errors="ignore").lower()
        for path in root.rglob("*")
        if path.is_file()
    )
    for token in (
        '"raw_response"',
        '"failure_message"',
        '"output_text"',
        '"user_id"',
        "authorization:",
        "api_key",
        "/users/",
    ):
        assert token not in public_text


def test_objective_campaign_v3_reports_model_outcomes_and_missingness_separately() -> None:
    root = (
        OBJECTIVE_CASE_PATH.parents[3]
        / "evidence"
        / "datacenter_development_v2_objective_grounding_v3"
    )
    summary = json.loads((root / "reports" / "summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (root / "trajectories" / "sanitized.jsonl").read_text().splitlines()
    ]

    assert summary["planned_cells"] == 6
    assert summary["completed_cells"] == 4
    assert summary["operational_failure_cells"] == 2
    assert summary["failure_conditions"] == ["provider_contract", "provider_contract"]
    assert summary["reported_cost_usd"] == pytest.approx(0.00250361595)
    assert summary["observed_reported_cost_usd"] == pytest.approx(0.00346668795)
    assert summary["observed_cost_qualifier"] == "lower_bound"
    included = [row for row in trajectories if row["inclusion_status"] == "included"]
    excluded = [row for row in trajectories if row["inclusion_status"] == "excluded"]
    assert len(included) == 4
    assert len(excluded) == 2
    assert all(row["scores"]["safe_developer_objective_attainment"]["value"] == 0 for row in included)
    assert all(row["route_verified"] for row in included)
    assert all(row["scores"] is None and row["outcome"] is None for row in excluded)
    assert {
        row["outcome"]["termination_reason"] for row in included
    } == {"land_negotiation_rounds_exhausted", "epc_negotiation_rounds_exhausted"}
