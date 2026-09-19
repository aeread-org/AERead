from __future__ import annotations

import asyncio
import copy
import dataclasses
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from aeread.shared_runner.task.execution import TokenPricing
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import (
    ActionEnvelope,
    LegalityResult,
    ParseResult,
)
from aeread_families.datacenter_development.contracts import (
    ContractSignature,
    ContractValidationError,
    LandAgreement,
    apply_executed_amendment,
    execute_offer,
    make_offer,
)
from aeread_families.datacenter_development.stack_environment import (
    DataCenterStackPlugin,
    _baseline_stack,
    _terms,
    terms_acceptable,
)
from aeread_families.datacenter_development.stack_campaign import (
    build_design,
    load_contract,
    run_campaign,
)
from aeread_families.datacenter_development.stack_publication import publish
from aeread_families.datacenter_development.stack_runner import (
    build_stack_model_to_model_setup,
    build_stack_openrouter_setup,
    finalize_stack_execution,
    load_stack_case,
    replay_stack_receipt,
    run_stack_offline,
    stack_counterparty_output_schemas,
    stack_developer_output_schemas,
)
from aeread_families.procurement_grounding import OpenRouterRoute


GLM_ROUTE = OpenRouterRoute(
    profile_id="datacenter_glm53_flash_v1",
    model="z-ai/glm-5.3-flash",
    revision="z-ai/glm-5.3-flash-20260826",
    route_provider="DeepInfra",
    quantization="fp8",
    pricing=TokenPricing(
        input_per_million=0.075,
        cached_input_per_million=0.015,
        output_per_million=0.25,
        pricing_id="datacenter_test_glm53_flash_deepinfra",
    ),
    max_prompt_price_per_million="0.075",
    max_completion_price_per_million="0.25",
    reasoning_effort="low",
)

ROOT = Path(__file__).resolve().parents[1]
INTERACTION_PUBLICATION = (
    ROOT / "evidence" /"datacenter_development" / "datacenter_development_v2_interaction_v1"
)


def _land(*, expiry: int) -> LandAgreement:
    return LandAgreement(
        site_control_start_month=1,
        closing_month=1,
        site_control_expiry_month=expiry,
        purchase_price_cents=20_000,
        extension_option_months=2,
        extension_price_cents=5_000,
        permitted_use_capacity_kw=1_000,
        conditions_precedent=("zoning_approval",),
    )


def _execute_land(offer):
    return execute_offer(
        offer,
        (
            ContractSignature(offer.offer_id, "developer"),
            ContractSignature(offer.offer_id, "landowner"),
        ),
        required_signers=("developer", "landowner"),
    )


def test_land_amendment_requires_exact_superseded_offer_and_changed_fields() -> None:
    prior_offer = make_offer(
        case_id="datacenter_v2_case_001",
        agreement_type="land",
        proposer_seat_id="developer",
        round_index=0,
        message="Initial site-control agreement.",
        terms=_land(expiry=3),
    )
    prior = _execute_land(prior_offer)
    amendment_offer = make_offer(
        case_id="datacenter_v2_case_001",
        agreement_type="land",
        proposer_seat_id="developer",
        round_index=0,
        message="Extend site control through COD.",
        terms=_land(expiry=4),
        supersedes_offer_id=prior.offer_id,
        amended_fields=("site_control_expiry_month",),
        precedence_index=1,
    )
    amendment = _execute_land(amendment_offer)

    assert apply_executed_amendment(prior, amendment) == amendment

    wrong_fields = dataclasses.replace(
        amendment,
        amended_fields=("extension_option_months",),
        offer_id=make_offer(
            case_id="datacenter_v2_case_001",
            agreement_type="land",
            proposer_seat_id="developer",
            round_index=0,
            message="Incorrect field declaration.",
            terms=_land(expiry=4),
            supersedes_offer_id=prior.offer_id,
            amended_fields=("extension_option_months",),
            precedence_index=1,
        ).offer_id,
    )
    with pytest.raises(ContractValidationError, match="exactly match"):
        apply_executed_amendment(prior, wrong_fields)


@pytest.mark.parametrize(
    ("scope", "family_version", "expected_actions", "developer_npv", "total_npv"),
    (
        ("v1", "1.1.0", 12, -50_000, 150_000),
        ("v2", "2.0.0", 18, -155_000, -55_000),
    ),
)
def test_versioned_cases_validate_execute_seal_and_replay(
    tmp_path, scope, family_version, expected_actions, developer_npv, total_npv
) -> None:
    case = load_stack_case(scope)
    assert case.family_version == family_version
    DataCenterStackPlugin(scope).validate_payload(case.payload)

    evidence_root = tmp_path / scope
    setup, execution = asyncio.run(
        run_stack_offline(scope, evidence_root=evidence_root)
    )
    outcome = execution.episode_result.outcome

    assert execution.episode_result.logical_action_count == expected_actions
    assert execution.total_cost_usd == 0.0
    assert outcome["project_completed"] is True
    assert outcome["binding_contract_integrity"] is True
    assert outcome["project_constraints_satisfied"] is True
    assert outcome["developer_equity_npv_cents"] == developer_npv
    assert outcome["total_project_npv_cents"] == total_npv

    receipt = finalize_stack_execution(setup=setup, execution=execution)
    score_by_id = {score.leaf.leaf_id: score for score in receipt.scores}
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert len(receipt.scores) == 5
    assert score_by_id["binding_contract_integrity"].primary.value == 1.0
    assert score_by_id["project_constraint_satisfaction"].primary.value == 1.0
    assert score_by_id["negotiation_temporal_compliance"].primary.value == 1.0
    assert replay_stack_receipt(
        setup=setup, receipt=receipt, evidence_root=evidence_root
    ) == receipt

    if scope == "v2":
        assert outcome["amendment_precedence_valid"] is True
        adjustments = outcome["project_outcome"]["adjustments"]
        assert adjustments["site_control_valid_through_cod"] is True
        assert adjustments["land_extension_exercised"] is False
        amendment_offer = next(
            row
            for row in outcome["public_history"]
            if row.get("agreement_key") == "land_amendment"
            and row["decision"] == "offer"
        )
        assert amendment_offer["supersedes_offer_id"].startswith("offer_")
        assert tuple(amendment_offer["amended_fields"]) == (
            "site_control_expiry_month",
        )


def test_v2_developer_observation_excludes_every_private_policy() -> None:
    case = load_stack_case("v2")
    plugin = DataCenterStackPlugin("v2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    observation = plugin.observe(family_case, state, "developer", phase)
    serialized = repr(observation)

    assert "private_policy" not in serialized
    assert "policies" not in serialized
    assert "scripted_developer" not in serialized
    assert "baseline" not in serialized
    assert "outside_option" not in serialized
    assert "customer_usage_kw_by_month" not in serialized
    assert "customer_value_cents_per_kw_month" not in serialized


def test_v2_counterparty_observation_contains_only_current_private_policy() -> None:
    case = load_stack_case("v2")
    plugin = DataCenterStackPlugin("v2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = next(
        item
        for item in plugin.phases(family_case)
        if item.phase_id == "land_landowner_response"
    )

    observation = plugin.observe(
        family_case, state, "landowner", phase
    )

    assert observation["private_policy"] == family_case["policies"]["land"]
    assert "policies" not in observation
    assert "scripted_developer" not in observation
    assert "outside_option" not in observation
    assert "baseline" not in observation


def test_final_round_counter_terminates_as_valid_outside_option() -> None:
    case = load_stack_case("v1")
    plugin = DataCenterStackPlugin("v1")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    state["rounds"]["power"] = family_case["negotiation"]["max_rounds"][
        "power"
    ]
    phase = next(
        item
        for item in plugin.phases(family_case)
        if item.phase_id == "power_utility_response"
    )
    action = {
        "decision": "counter",
        "offer_id": "offer_final_round",
        "message": "Final controlled counteroffer.",
        "terms": family_case["policies"]["power"]["counter_terms"],
    }
    transition = plugin.step(
        family_case,
        state,
        phase,
        {
            "utility": ActionEnvelope(
                seat_id="utility",
                valid=True,
                action=action,
                parse=ParseResult.success(action),
                legality=LegalityResult.legal_action(),
            )
        },
    )
    outcome = plugin.outcome(family_case, plugin.terminal(family_case, transition.state))

    assert transition.next_phase_id is None
    assert transition.state["finished"] is True
    assert transition.state["termination_reason"] == (
        "power_negotiation_rounds_exhausted"
    )
    assert outcome["project_completed"] is False
    assert outcome["temporal_violations"] == []
    assert outcome["developer_equity_npv_cents"] == family_case[
        "outside_option"
    ]["developer_equity_npv_cents"]


@pytest.mark.parametrize(("scope", "schema_count"), (("v1", 8), ("v2", 12)))
def test_live_stack_plan_admits_glm_with_every_phase_schema(
    scope: str, schema_count: int
) -> None:
    setup = build_stack_openrouter_setup(
        scope, GLM_ROUTE, seed=20260831
    )
    schemas = stack_developer_output_schemas(setup.case)
    developer_profile_id = setup.plan.cells[0].profile_by_seat["developer"]
    developer_profile = next(
        profile
        for profile in setup.plan.agent_profiles
        if profile.profile_id == developer_profile_id
    )

    assert developer_profile.model.provider == "openrouter"
    assert len(schemas) == schema_count
    assert canonical_json_bytes(
        developer_profile.harness.config["output_schema_by_action_schema"]
    ) == canonical_json_bytes(schemas)
    assert all(admission.admitted for admission in setup.plan.profile_admissions)
    assert {
        profile.model.provider
        for profile in setup.plan.agent_profiles
        if profile.profile_id != developer_profile_id
    } == {
        f"datacenter_stack_scripted_{seat}"
        for seat in setup.plan.cells[0].profile_by_seat
        if seat != "developer"
    }


@pytest.mark.parametrize(
    ("scope", "expected_seats"),
    (
        ("v1", {"developer", "utility", "contractor", "customer", "lender"}),
        (
            "v2",
            {
                "developer",
                "landowner",
                "utility",
                "contractor",
                "customer",
                "lender",
            },
        ),
    ),
)
def test_model_to_model_plan_puts_every_seat_behind_the_harness(
    scope: str, expected_seats: set[str]
) -> None:
    setup = build_stack_model_to_model_setup(
        scope, GLM_ROUTE, seed=20260831
    )
    cell = setup.plan.cells[0]
    profile_by_id = {
        profile.profile_id: profile for profile in setup.plan.agent_profiles
    }
    block = setup.plan.evaluation_blocks[0]

    assert block.kind == "self_play"
    assert dict(block.controlled_profiles) == {}
    assert set(block.subject_seats) == expected_seats
    assert set(cell.profile_by_seat) == expected_seats
    assert len(set(cell.profile_by_seat.values())) == len(expected_seats)
    assert all(admission.admitted for admission in setup.plan.profile_admissions)
    for seat_id, profile_id in cell.profile_by_seat.items():
        profile = profile_by_id[profile_id]
        assert profile.model.provider == "openrouter"
        assert profile.harness.id == "minimal_chat"
        assert profile.sampling.seed == 20260831
        declared = profile.harness.config[
            "output_schema_by_action_schema"
        ]
        expected = (
            stack_developer_output_schemas(setup.case)
            if seat_id == "developer"
            else stack_counterparty_output_schemas(setup.case, seat_id)
        )
        assert canonical_json_bytes(declared) == canonical_json_bytes(expected)


def test_v2_interaction_campaign_is_paired_and_budget_bounded() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 12
    assert design["paired_seed_count"] == 3
    assert design["worst_case_declared_cost_usd"] == pytest.approx(1.26)
    assert design["campaign_max_cost_usd"] == pytest.approx(1.5)
    assert {
        (
            cell["condition"],
            cell["evaluation_block_kind"],
            cell["live_profile_count"],
        )
        for cell in design["cells"]
    } == {
        ("controlled_developer", "controlled", 1),
        ("homogeneous_model_to_model", "self_play", 6),
    }
    by_seed_and_model: dict[tuple[int, str], set[str]] = {}
    for cell in design["cells"]:
        key = (cell["inference_seed"], cell["model_id"])
        by_seed_and_model.setdefault(key, set()).add(cell["condition"])
    assert all(
        conditions == set(contract["conditions"])
        for conditions in by_seed_and_model.values()
    )


def test_v2_interaction_campaign_rejects_aggregate_budget_overflow(tmp_path) -> None:
    contract = load_contract()
    contract["execution"]["max_cost_usd_per_live_profile"] = 0.04
    contract_path = tmp_path / "over_budget.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="cost ceilings"):
        load_contract(contract_path)


def test_v2_interaction_campaign_passes_pre_live_gates(tmp_path) -> None:
    summary = asyncio.run(
        run_campaign(
            run_root=tmp_path / "campaign",
            stop_after="profile_admission",
        )
    )

    assert summary["status"] == "passed"
    assert len(summary["admitted_cells"]) == 12


def test_v2_interaction_campaign_module_invokes_cli(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread_families.datacenter_development.stack_campaign",
            "--run-root",
            str(tmp_path / "campaign"),
            "--stop-after",
            "design",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    design = json.loads(completed.stdout)

    assert design["planned_cells"] == 12
    assert design["worst_case_declared_cost_usd"] == pytest.approx(1.26)


@pytest.mark.local_run("datacenter_development_v2_interaction_v1")
def test_v2_interaction_publication_is_reproducible_and_sanitized(tmp_path) -> None:
    manifest = json.loads(
        (INTERACTION_PUBLICATION / "publication_manifest.json").read_text()
    )
    manifest_core = {
        key: value for key, value in manifest.items() if key != "artifact_sha256"
    }
    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(manifest_core)
    ).hexdigest()
    assert len(manifest["source_receipt_sha256s"]) == 12
    assert len(set(manifest["source_receipt_sha256s"])) == 12
    assert len(manifest["source_result_sha256s"]) == 12
    assert len(set(manifest["source_result_sha256s"])) == 12

    for relative, expected in manifest["files"].items():
        payload = (INTERACTION_PUBLICATION / relative).read_bytes()
        assert len(payload) == expected["bytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    fact_manifest = json.loads(
        (INTERACTION_PUBLICATION / "tables" / "fact_manifest.json").read_text()
    )
    assert (
        manifest["files"]["tables/benchmark_results.csv"]["row_count"]
        == fact_manifest["tables"]["benchmark_results"]["row_count"]
        == 56
    )
    assert (
        manifest["files"]["tables/profiles.csv"]["row_count"]
        == fact_manifest["tables"]["profiles"]["row_count"]
        == 12
    )

    summary = json.loads(
        (INTERACTION_PUBLICATION / "reports" / "summary.json").read_text()
    )
    trajectories = [
        json.loads(line)
        for line in (
            INTERACTION_PUBLICATION / "trajectories" / "sanitized.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    projections = [
        json.loads(line)
        for line in (
            INTERACTION_PUBLICATION / "receipts" / "projections.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    assert len(trajectories) == len(projections) == 12
    assert sum(row["inclusion_status"] == "included" for row in trajectories) == 11
    assert sum(row["inclusion_status"] == "excluded" for row in trajectories) == 1
    assert all(
        row["route_verified"] and row["verified_openrouter_call_count"] > 0
        for row in trajectories
        if row["status"] == "completed"
    )
    excluded = next(row for row in trajectories if row["inclusion_status"] == "excluded")
    assert excluded["outcome"] is None
    assert excluded["scores"] is None
    assert excluded["failure"]["failure_condition"] == "rate_limit"
    assert next(
        row for row in projections if row["inclusion_status"] == "excluded"
    )["replay_level"] == "none"
    assert all(
        group["project_completion_rate"] == 0.0
        for group in summary["group_summaries"]
    )
    assert summary["reported_cost_usd"] == pytest.approx(0.01559065365)
    assert summary["provider_cost_complete"] is False
    assert summary["cost_qualifier"] == "lower_bound"
    assert summary["winner_claim_allowed"] is False
    assert summary["inferential_model_ranking_allowed"] is False
    assert summary["causal_condition_effect_allowed"] is False

    public_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in INTERACTION_PUBLICATION.rglob("*")
        if path.is_file()
    )
    for prohibited in (
        '"raw_response"',
        '"failure_message"',
        '"output_text"',
        '"user_id"',
        "authorization:",
        "api_key",
        "/users/",
    ):
        assert prohibited not in public_text

    reproduced = publish(publication_root=tmp_path / "publication")
    assert reproduced == manifest


# --- DC-D-01: the repaired V2 case and the opt-in construct guard -----------

REPAIRED_V2_CASE = (
    Path(__file__).resolve().parents[1]
    / "cases"
    / "datacenter_development_v1"
    / "v2"
    / "full_stack_amendment_002.json"
)


def _repaired_payload() -> dict:
    return json.loads(REPAIRED_V2_CASE.read_text(encoding="utf-8"))["payload"]


def test_repaired_v2_case_reference_dominates_walking_and_seals(tmp_path) -> None:
    """The scripted reference negotiates to the floor of two-sided bands and
    beats the outside option by the declared margin; the sealed 001 case,
    whose reference loses to walking away by 55,000, is untouched."""

    case = load_stack_case("v2", REPAIRED_V2_CASE)
    assert case.case_id == "datacenter_development_v1.v2.full_stack_amendment_002"
    family_case = DataCenterStackPlugin("v2").validate_payload(case.payload)
    controls = family_case["construct_controls"]
    assert controls["baseline_must_dominate_outside_option"] is True
    assert controls["two_sided_price_bands"] is True
    assert family_case["baseline"]["developer_equity_npv_cents"] == -72_000
    assert family_case["outside_option"]["developer_equity_npv_cents"] == -100_000
    assert -72_000 - (-100_000) >= controls["minimum_baseline_margin_cents"] == 25_000

    evidence_root = tmp_path / "v2_repaired"
    setup, execution = asyncio.run(
        run_stack_offline("v2", evidence_root=evidence_root, case_path=REPAIRED_V2_CASE)
    )
    outcome = execution.episode_result.outcome
    assert execution.episode_result.logical_action_count == 18
    assert outcome["project_completed"] is True
    assert outcome["binding_contract_integrity"] is True
    assert outcome["project_constraints_satisfied"] is True
    assert outcome["developer_equity_npv_cents"] == -72_000
    assert outcome["total_project_npv_cents"] == -32_000
    assert outcome["customer_npv_cents"] == 40_000  # the customer still gains at 160

    receipt = finalize_stack_execution(setup=setup, execution=execution)
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert len(receipt.scores) == 5
    assert (
        replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        == receipt
    )


def test_repaired_v2_case_admits_counter_adoption_but_not_overpayment_or_lowball() -> None:
    """Copying every counter stays admissible and loses (the trap the case
    sets); paying 15x for land, an EPC price of one cent, and charging the
    customer three times its ceiling are all refused by the counterparties."""

    payload = _repaired_payload()
    policies = payload["policies"]
    for key, policy in policies.items():
        agreement = "land" if key == "land_amendment" else key
        assert terms_acceptable(_terms(agreement, policy["counter_terms"]), policy), key

    adopted = copy.deepcopy(payload)
    for key, policy in policies.items():
        adopted["scripted_developer"][f"{key}_terms"] = copy.deepcopy(policy["counter_terms"])
    _, outcome = _baseline_stack(adopted, "v2")
    assert outcome.developer_equity_npv_cents == -155_000
    assert outcome.developer_equity_npv_cents < payload["outside_option"]["developer_equity_npv_cents"]

    scripted = payload["scripted_developer"]
    overpay = dict(scripted["land_terms"], purchase_price_cents=300_000)
    assert not terms_acceptable(_terms("land", overpay), policies["land"])
    lowball = dict(
        scripted["epc_terms"],
        contract_price_cents=1,
        payment_schedule=[{"month": 1, "amount_cents": 1}],
    )
    assert not terms_acceptable(_terms("epc", lowball), policies["epc"])
    over_cap = dict(scripted["service_terms"], monthly_capacity_charge_cents_per_kw=300)
    assert not terms_acceptable(_terms("service", over_cap), policies["service"])


def test_construct_controls_guard_kills_the_sealed_dominated_case() -> None:
    """Mutation evidence for the guard: switched on against the sealed 001
    payload it dies for the intended reason on each control, and the sealed
    payload without the block still validates exactly as before."""

    plugin = DataCenterStackPlugin("v2")
    sealed = dict(load_stack_case("v2").payload)
    plugin.validate_payload(sealed)

    dominance_only = {
        "baseline_must_dominate_outside_option": True,
        "minimum_baseline_margin_cents": 0,
        "two_sided_price_bands": False,
    }
    with pytest.raises(ValueError, match="does not strictly dominate the outside option"):
        plugin.validate_payload({**sealed, "construct_controls": dominance_only})
    bands_only = {**dominance_only, "baseline_must_dominate_outside_option": False, "two_sided_price_bands": True}
    with pytest.raises(ValueError, match="bounded on one side only"):
        plugin.validate_payload({**sealed, "construct_controls": bands_only})

    repaired = _repaired_payload()
    plugin.validate_payload(repaired)
    too_strict = {**repaired["construct_controls"], "minimum_baseline_margin_cents": 1_000_000}
    with pytest.raises(ValueError, match="below the declared minimum"):
        plugin.validate_payload({**repaired, "construct_controls": too_strict})
    one_sided = copy.deepcopy(repaired)
    del one_sided["policies"]["epc"]["minimums"]["contract_price_cents"]
    with pytest.raises(ValueError, match=r"policies\.epc\.contract_price_cents is bounded on one side only"):
        plugin.validate_payload(one_sided)
    with pytest.raises(ValueError, match="construct_controls fields differ"):
        plugin.validate_payload(
            {**repaired, "construct_controls": {"baseline_must_dominate_outside_option": True}}
        )
    with pytest.raises(ValueError, match="non-negative integer"):
        plugin.validate_payload(
            {**repaired, "construct_controls": {**repaired["construct_controls"], "minimum_baseline_margin_cents": -1}}
        )



def test_repaired_v2_case_observation_hides_bands_and_controls() -> None:
    """The floors, the guard block and the reference stay private to the
    developer seat exactly as the sealed case's private policy does."""

    case = load_stack_case("v2", REPAIRED_V2_CASE)
    plugin = DataCenterStackPlugin("v2")
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    serialized = repr(plugin.observe(family_case, state, "developer", phase))

    for token in (
        "construct_controls",
        "minimums",
        "maximums",
        "private_policy",
        "scripted_developer",
        "baseline",
        "outside_option",
        "17000",  # the land floor
        "184000",  # the EPC floor
    ):
        assert token not in serialized, token
