from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.task.scheduler import (
    ActionEnvelope,
    LegalityResult,
    ParseResult,
)
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.stack_environment import (
    DataCenterStackPlugin,
)
from aeread_families.datacenter_development.stack_runner import (
    finalize_stack_execution,
    replay_stack_receipt,
    run_stack_offline,
)
from aeread_families.datacenter_development.stack_worlds import (
    DEFAULT_OUTPUT_ROOT,
    MASTER_SEED,
    STRATA,
    VARIANTS_PER_STRATUM,
    check_pack,
    evaluate_stack,
    generate_pack,
    load_pack_manifest,
)


def test_world_pack_on_disk_is_reproducible_from_the_pinned_seed() -> None:
    result = check_pack(DEFAULT_OUTPUT_ROOT)

    assert result["reproducible"] is True, result["drift"]


def test_world_pack_covers_six_strata_with_four_distinct_variants() -> None:
    manifest = load_pack_manifest()

    assert manifest["master_seed"] == MASTER_SEED
    assert manifest["world_count"] == len(STRATA) * VARIANTS_PER_STRATUM == 24
    by_stratum: dict[str, list[dict]] = {}
    for world in manifest["worlds"]:
        by_stratum.setdefault(world["stratum"], []).append(world)
    assert set(by_stratum) == set(STRATA)
    for stratum, worlds in by_stratum.items():
        assert [world["variant"] for world in worlds] == [1, 2, 3, 4], stratum
        knobs = {json.dumps(world["knobs"], sort_keys=True) for world in worlds}
        assert len(knobs) == 4, stratum
    seeds = [world["world_seed"] for world in manifest["worlds"]]
    assert len(set(seeds)) == 24


def test_every_world_has_feasible_trap_and_walk_away_paths() -> None:
    manifest = load_pack_manifest()

    for world in manifest["worlds"]:
        mechanism = world["mechanism"]
        feasible = mechanism["feasible_path"]
        trap = mechanism["attractive_path"]
        walk = mechanism["walk_away"]
        assert feasible["constraints_satisfied"] is True, world["case_id"]
        assert feasible["financing_succeeded"] is True, world["case_id"]
        assert feasible["developer_equity_npv_cents"] > walk["developer_equity_npv_cents"]
        assert trap["constraints_satisfied"] is False, world["case_id"]
        expected = mechanism["expected_failure"]
        if expected == "loan_never_funds":
            assert trap["loan_conditions_satisfied_month"] is None
        else:
            assert expected in trap["default_reasons"], world["case_id"]


def test_world_case_files_validate_and_match_manifest_hashes() -> None:
    manifest = load_pack_manifest()
    plugin = DataCenterStackPlugin("v2")

    for world in manifest["worlds"]:
        document = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())
        assert document["case_id"] == world["case_id"]
        assert document["content_sha256"] == world["content_sha256"]
        assert case_content_sha256(document) == document["content_sha256"]
        payload = plugin.validate_payload(document["payload"])
        baseline = world["mechanism"]["feasible_path"]
        assert payload["baseline"]["developer_equity_npv_cents"] == (
            baseline["developer_equity_npv_cents"]
        )
        assert payload["outside_option"] == world["mechanism"]["walk_away"]
        # Mechanism annotations never enter the payload the agent can observe.
        assert "mechanism" not in document["payload"]
        assert "explanation" not in document["payload"]


def test_trap_paths_are_accepted_by_every_counterparty_but_fail_admission() -> None:
    pack = generate_pack(MASTER_SEED)
    manifest = pack["manifest"]

    for document, world in zip(pack["cases"], manifest["worlds"]):
        payload = document["payload"]
        recomputed = evaluate_stack(
            payload["project_facts"],
            {key: payload["scripted_developer"][f"{key}_terms"] for key in (
                "land", "power", "epc", "service", "land_amendment", "loan"
            )},
        )
        assert recomputed == world["mechanism"]["feasible_path"]


def test_verbal_written_divergence_counter_message_contradicts_terms() -> None:
    manifest = load_pack_manifest()
    worlds = [w for w in manifest["worlds"] if w["stratum"] == "verbal_written_divergence"]

    for world in worlds:
        document = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())
        loan_policy = document["payload"]["policies"]["loan"]
        scripted = document["payload"]["scripted_developer"]["loan_terms"]
        assert "advance rate" in loan_policy["counter_message"]
        assert loan_policy["counter_terms"]["advance_rate_bps"] < scripted["advance_rate_bps"]


@pytest.mark.parametrize(
    "file_name",
    ("revenue_without_bankability_001.json", "covenant_cliff_003.json"),
)
def test_two_worlds_from_different_strata_replay_exactly(tmp_path, file_name: str) -> None:
    setup, execution = asyncio.run(
        run_stack_offline(
            "v2",
            evidence_root=tmp_path,
            case_path=DEFAULT_OUTPUT_ROOT / file_name,
        )
    )
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    replayed = replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path)
    outcome = execution.episode_result.outcome

    assert execution.episode_result.logical_action_count == 18
    assert receipt.inclusion_status == "included"
    assert outcome["project_completed"] is True
    assert outcome["project_constraints_satisfied"] is True
    assert replayed == receipt


def test_world_generator_cli_checks_the_pack(tmp_path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "aeread_families.datacenter_development.stack_worlds",
            "--check",
            "--output",
            str(DEFAULT_OUTPUT_ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout)["reproducible"] is True


def test_live_amendment_fields_follow_the_actual_diff_and_reject_no_op() -> None:
    from aeread_families.datacenter_development.stack_environment import amended_fields_for
    from aeread_families.datacenter_development.stack_runner import build_stack_setup

    setup = build_stack_setup("v2", case_path=DEFAULT_OUTPUT_ROOT / "delayed_revenue_002.json")
    plugin = DataCenterStackPlugin("v2")
    case = plugin.validate_payload(setup.case.payload)
    land = case["scripted_developer"]["land_terms"]
    changed = {**land, "site_control_expiry_month": land["site_control_expiry_month"] + 1, "purchase_price_cents": land["purchase_price_cents"] + 1}
    from aeread_families.datacenter_development.contracts import LandAgreement

    assert amended_fields_for(land, LandAgreement.from_dict(changed)) == (
        "site_control_expiry_month",
        "purchase_price_cents",
    )
    assert amended_fields_for(land, LandAgreement.from_dict(dict(land))) == ()

    state = plugin.initial_state(case, None)
    state["executed"]["land"] = {"offer_id": "offer_x", "terms": dict(land), "precedence_index": 0}
    phase = next(p for p in plugin.phases(case) if p.phase_id == "land_amendment_developer_offer")
    no_op = plugin.legal(case, state, "developer", phase, {"decision": "offer", "message": "m", "terms": dict(land)})
    assert not no_op.legal and no_op.reason == "amendment_changes_nothing"
    real = plugin.legal(case, state, "developer", phase, {"decision": "offer", "message": "m", "terms": changed})
    assert real.legal


def test_parse_action_rejects_oversized_integers_as_a_model_error() -> None:
    from aeread.shared_runner.task.execution import CanonicalResponse

    plugin = DataCenterStackPlugin("v2")
    case = plugin.validate_payload(
        json.loads((DEFAULT_OUTPUT_ROOT / "covenant_cliff_001.json").read_text())["payload"]
    )
    phase = next(p for p in plugin.phases(case) if p.phase_id == "land_developer_offer")
    huge = "9" * 5000
    response = CanonicalResponse(
        text='{"decision": "offer", "message": "m", "terms": {"purchase_price_cents": ' + huge + "}}",
        finish_reason="stop",
        empty=False,
        truncated=False,
        provider_call_ids=(),
        tool_invocation_ids=(),
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )
    result = plugin.parse_action(case, plugin.initial_state(case, None), "developer", phase, response)
    # Decoding now succeeds and the magnitude guard rejects the term, so the
    # cell is booked against the model rather than against the provider.
    assert not result.ok and result.error_code == "malformed_datacenter_stack_action"


def _stack(payload, source):
    keys = ("land", "power", "epc", "service", "land_amendment", "loan")
    if source == "scripted":
        return {k: payload["scripted_developer"][f"{k}_terms"] for k in keys}
    return {k: payload["policies"][k]["counter_terms"] for k in keys}


def test_adopting_every_counter_is_admissible_but_never_optimal() -> None:
    """The task must be a negotiation, not a copy of the counterparty's counter."""
    from aeread_families.datacenter_development.stack_environment import (
        AGREEMENT_TYPE_BY_KEY,
        TERM_PARSER_BY_TYPE,
        terms_acceptable,
    )

    manifest = load_pack_manifest()
    matched_baseline = 0
    headroom = []
    for world in manifest["worlds"]:
        payload = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())["payload"]
        scripted = _stack(payload, "scripted")
        counters = _stack(payload, "counter")
        accepted = all(
            terms_acceptable(
                TERM_PARSER_BY_TYPE[AGREEMENT_TYPE_BY_KEY[key]](counters[key]),
                payload["policies"][key],
            )
            for key in counters
        )
        assert accepted, f"{world['file']}: counter terms must stay admissible"
        adopted = evaluate_stack(payload["project_facts"], counters)
        baseline = evaluate_stack(payload["project_facts"], scripted)
        if adopted["developer_equity_npv_cents"] >= baseline["developer_equity_npv_cents"]:
            matched_baseline += 1
        headroom.append(
            baseline["developer_equity_npv_cents"] - adopted["developer_equity_npv_cents"]
        )

    assert matched_baseline == 0, "blind counter-adoption must never reach the baseline"
    assert all(gap > 0 for gap in headroom)
    assert min(headroom) >= 10_000


def test_no_within_policy_stack_earns_unbounded_self_written_damages() -> None:
    """Liability terms must be two-sided so damages cannot be self-awarded."""
    from aeread_families.datacenter_development.stack_environment import (
        AGREEMENT_TYPE_BY_KEY,
        TERM_PARSER_BY_TYPE,
        terms_acceptable,
    )

    manifest = load_pack_manifest()
    for world in manifest["worlds"]:
        payload = json.loads((DEFAULT_OUTPUT_ROOT / world["file"]).read_text())["payload"]
        inflated = json.loads(json.dumps(_stack(payload, "scripted")))
        # Scale-independent: an order of magnitude above the EPC contract, so
        # the assertion cannot silently pass by inflating to a small number.
        outrageous = inflated["epc"]["contract_price_cents"] * 10
        for key, field in (
            ("power", "delay_liquidated_damages_cents_per_month"),
            ("power", "delay_liquidated_damages_cap_cents"),
            ("epc", "delay_liquidated_damages_cents_per_month"),
            ("epc", "delay_liquidated_damages_cap_cents"),
            ("epc", "completion_guarantee_cents"),
        ):
            inflated[key][field] = outrageous
        assert not all(
            terms_acceptable(
                TERM_PARSER_BY_TYPE[AGREEMENT_TYPE_BY_KEY[key]](inflated[key]),
                payload["policies"][key],
            )
            for key in inflated
        ), f"{world['file']}: inflated liability terms must be rejected"


def test_optional_amendment_can_be_declined_without_ending_the_episode() -> None:
    from aeread_families.datacenter_development.stack_environment import (
        OPTIONAL_AGREEMENT_KEYS,
    )

    plugin = DataCenterStackPlugin("v2")
    payload = json.loads((DEFAULT_OUTPUT_ROOT / "covenant_cliff_001.json").read_text())
    case = plugin.validate_payload(payload["payload"])
    assert "land_amendment" in OPTIONAL_AGREEMENT_KEYS

    state = plugin.initial_state(case, None)
    state["executed"]["land"] = {
        "offer_id": "offer_x",
        "terms": dict(case["scripted_developer"]["land_terms"]),
        "precedence_index": 0,
    }
    phase = next(
        p for p in plugin.phases(case) if p.phase_id == "land_amendment_developer_offer"
    )
    decline = {"decision": "decline", "message": "the executed lease already fits"}
    assert plugin.legal(case, state, "developer", phase, decline).legal

    land_phase = next(
        p for p in plugin.phases(case) if p.phase_id == "land_developer_offer"
    )
    refused = plugin.legal(case, state, "developer", land_phase, decline)
    assert not refused.legal and refused.reason == "agreement_is_not_optional"


def test_every_transition_lands_on_a_declared_next_phase() -> None:
    """The phase graph must declare every jump the environment can take."""
    plugin = DataCenterStackPlugin("v2")
    payload = json.loads((DEFAULT_OUTPUT_ROOT / "covenant_cliff_001.json").read_text())
    case = plugin.validate_payload(payload["payload"])
    by_id = {phase.phase_id: phase for phase in plugin.phases(case)}

    state = plugin.initial_state(case, None)
    state["executed"]["land"] = {
        "offer_id": "offer_x",
        "terms": dict(case["scripted_developer"]["land_terms"]),
        "precedence_index": 0,
    }
    phase = by_id["land_amendment_developer_offer"]
    action = {"decision": "decline", "message": "no change needed"}
    envelope = ActionEnvelope(
        seat_id="developer",
        valid=True,
        action=action,
        parse=ParseResult.success(action),
        legality=LegalityResult.legal_action(),
    )
    result = plugin.step(case, state, phase, {"developer": envelope})

    assert result.next_phase_id is not None
    assert result.next_phase_id in phase.next_phases


def test_declining_the_amendment_completes_a_scripted_episode(tmp_path) -> None:
    """A declined optional agreement still yields a complete, admitted project."""
    from aeread_families.datacenter_development.stack_runner import (
        StackScriptedDeveloperProvider,
        build_stack_setup,
        _providers,
    )
    from aeread.shared_runner.task.execution import execute_plan_cell

    case_path = DEFAULT_OUTPUT_ROOT / "covenant_cliff_001.json"
    setup = build_stack_setup("v2", case_path=case_path)

    class DecliningDeveloper(StackScriptedDeveloperProvider):
        async def complete(self, request):
            payload = json.loads(request.input_text)
            if payload["phase_id"] == "land_amendment_developer_offer":
                from aeread_families.datacenter_development.stack_runner import (
                    _scripted_result,
                )

                return _scripted_result(
                    request,
                    {"decision": "decline", "message": "the executed lease already fits", "terms": None},
                )
            return await super().complete(request)

    providers = dict(_providers(setup))
    providers["datacenter_stack_scripted_developer"] = DecliningDeveloper(
        setup.case.payload["scripted_developer"]
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers=providers,
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )
    outcome = execution.episode_result.outcome
    receipt = finalize_stack_execution(setup=setup, execution=execution)

    assert list(outcome["declined_agreements"]) == ["land_amendment"]
    assert outcome["project_completed"] is True
    assert outcome["binding_contract_integrity"] is True
    assert outcome["project_constraints_satisfied"] is True
    assert receipt.inclusion_status == "included"
    assert replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path) == receipt


def test_verbal_written_diagnostic_counts_adopted_undisclosed_terms() -> None:
    """Adopting a counter whose prose hid a changed term must be recorded."""
    plugin = DataCenterStackPlugin("v2")
    payload = json.loads(
        (DEFAULT_OUTPUT_ROOT / "verbal_written_divergence_001.json").read_text()
    )["payload"]
    case = plugin.validate_payload(payload)
    counter = case["policies"]["loan"]["counter_terms"]

    terminal = {
        "public_history": [
            {"agreement_key": "loan", "decision": "counter", "terms": dict(counter)}
        ],
        "executed": {"loan": {"terms": dict(counter)}},
    }
    adopted = plugin._verbal_written_mismatch(case, terminal)
    assert adopted["undisclosed_counters_presented"] == 1
    assert adopted["undisclosed_counters_adopted"] == 1
    assert adopted["declared_fields"]["loan"] == [
        "advance_rate_bps",
        "maximum_loan_to_cost_bps",
    ]

    # A counter recorded without structured terms still resolves through the
    # declared package rather than silently counting zero.
    terminal["public_history"][0].pop("terms")
    assert plugin._verbal_written_mismatch(case, terminal)[
        "undisclosed_counters_adopted"
    ] == 1

    # A developer that held its own advance rate is not counted as adopting.
    held = dict(counter)
    held["advance_rate_bps"] = case["scripted_developer"]["loan_terms"]["advance_rate_bps"]
    held["maximum_loan_to_cost_bps"] = case["scripted_developer"]["loan_terms"][
        "maximum_loan_to_cost_bps"
    ]
    terminal["executed"]["loan"]["terms"] = held
    assert plugin._verbal_written_mismatch(case, terminal)[
        "undisclosed_counters_adopted"
    ] == 0


def test_counter_terms_are_recorded_in_public_history() -> None:
    plugin = DataCenterStackPlugin("v2")
    payload = json.loads((DEFAULT_OUTPUT_ROOT / "covenant_cliff_001.json").read_text())
    case = plugin.validate_payload(payload["payload"])
    state = plugin.initial_state(case, None)
    terms = dict(case["policies"]["land"]["counter_terms"])
    state["offers"].append(
        {
            "offer_id": "offer_a",
            "case_id": case["scenario_id"],
            "agreement_type": "land",
            "proposer_seat_id": "developer",
            "round_index": 0,
            "message": "m",
            "terms": dict(case["scripted_developer"]["land_terms"]),
        }
    )
    state["latest_offer_id"]["land"] = "offer_a"
    state["rounds"]["land"] = 1
    phase = next(p for p in plugin.phases(case) if p.phase_id == "land_landowner_response")
    action = {
        "decision": "counter",
        "offer_id": "offer_a",
        "message": "landowner counterproposal.",
        "terms": terms,
    }
    envelope = ActionEnvelope(
        seat_id="landowner",
        valid=True,
        action=action,
        parse=ParseResult.success(action),
        legality=LegalityResult.legal_action(),
    )
    result = plugin.step(case, state, phase, {"landowner": envelope})
    recorded = result.state["public_history"][-1]

    assert recorded["decision"] == "counter"
    assert recorded["terms"] == terms
