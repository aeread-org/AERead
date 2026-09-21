"""Developer interface 3: a decline for the amendment phase, and a walk that
may say why (DC-D-08, DC-D-10).

The first confirmatory lost 22 of 72 cells at the land-amendment phase: 16
re-proposed the executed terms ("reaffirming executed land terms") and 6
"walked" to say no amendment was needed, because the phase offered no way to
say so. A case opts in through ``construct_controls.developer_interface``;
every sealed case is interface 2 and keeps its bytes, prompt, schema, plan
and receipts, which these tests pin from both sides.
"""

from __future__ import annotations

import asyncio
import copy
import functools
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope, LegalityResult, ParseResult
from aeread_families.datacenter_development import stack_environment
from aeread_families.datacenter_development.cashflow import ProjectFacts
from aeread_families.datacenter_development.stack_cashflow import simulate_development_stack
from aeread_families.datacenter_development.stack_environment import (
    DEVELOPER_INTERFACES,
    DataCenterStackPlugin,
    _baseline_stack,
    _executed_from_dict,
    _plain,
    developer_interface,
)
from aeread_families.datacenter_development.stack_runner import (
    AMENDMENT_DECLINE_NOTE,
    build_stack_setup,
    developer_prompt,
    finalize_stack_execution,
    load_stack_case,
    replay_stack_receipt,
    run_stack_offline,
    stack_developer_output_schemas,
)
from aeread_families.datacenter_development.stack_worlds import MASTER_SEED, generate_pack
from aeread_families.datacenter_development.world_campaign import (
    CONTRACT_SCHEMA_VERSION,
    CONTRACT_SCHEMA_VERSIONS,
    _declared_maximum,
    load_contract,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASES = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v2"
CASE_002 = CASES / "full_stack_amendment_002.json"
CASE_003 = CASES / "full_stack_amendment_003.json"
WORLDS_V2 = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "worlds_v2"
CONFIRMATORY = REPOSITORY_ROOT / "configs" / "datacenter_development_v2_world_panel_confirmatory_v1.json"


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def _envelope(seat, action, legality=None):
    legality = legality or LegalityResult.legal_action()
    return ActionEnvelope(
        seat_id=seat,
        valid=legality == LegalityResult.legal_action(),
        action=action,
        parse=ParseResult.success(action),
        legality=legality,
    )


def _response(text: str):
    return stack_environment.CanonicalResponse(
        text=text,
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


def _phase(plugin, family_case, phase_id):
    return next(item for item in plugin.phases(family_case) if item.phase_id == phase_id)


def _state_after_land(plugin, family_case, payload):
    executed, _ = _baseline_stack(payload, "v2")
    state = plugin.initial_state(family_case, run=None)
    state["executed"]["land"] = _plain(executed["land"])
    return state


@functools.lru_cache(maxsize=None)
def _interface_three_pack() -> dict:
    return generate_pack(MASTER_SEED, split="worlds_v3", pack_id="test_worlds_v3", developer_interface=3)


def test_interface_is_two_unless_a_case_opts_in() -> None:
    assert DEVELOPER_INTERFACES == (2, 3, 4)
    assert developer_interface(_payload(CASE_002)) == 2
    assert developer_interface(_payload(CASE_003)) == 3
    assert developer_interface(load_stack_case("v2").payload) == 2  # the sealed 001 case
    plugin = DataCenterStackPlugin("v2")
    for bad in (5, True, "3"):
        payload = copy.deepcopy(_payload(CASE_003))
        payload["construct_controls"]["developer_interface"] = bad
        with pytest.raises(ValueError, match="developer_interface"):
            plugin.validate_payload(payload)


def test_prompt_and_schema_change_only_for_interface_three() -> None:
    two, three = _payload(CASE_002), _payload(CASE_003)
    assert developer_prompt(two, "v2")[0] == "datacenter_v2_developer_prompt_v2"
    assert developer_prompt(three, "v2")[0] == "datacenter_v2_developer_prompt_v3"
    assert developer_prompt(three, "v2")[1] == developer_prompt(two, "v2")[1] + AMENDMENT_DECLINE_NOTE
    assert "decline" in AMENDMENT_DECLINE_NOTE and "reason" in AMENDMENT_DECLINE_NOTE
    schemas_two = stack_developer_output_schemas(load_stack_case("v2", CASE_002))
    schemas_three = stack_developer_output_schemas(load_stack_case("v2", CASE_003))
    for key, schema in schemas_two.items():
        if key.endswith("_offer_v1"):
            assert schema["properties"]["decision"]["enum"] == ["offer", "walk"], key
    for key, schema in schemas_three.items():
        if key == "datacenter_land_amendment_offer_v1":
            assert schema["properties"]["decision"]["enum"] == ["offer", "decline", "walk"]
        elif key.endswith("_offer_v1"):
            assert schema["properties"]["decision"]["enum"] == ["offer", "walk"], key


def test_a_decline_is_parsed_and_legal_only_where_interface_three_allows_it() -> None:
    plugin = DataCenterStackPlugin("v2")
    decline = json.dumps({"decision": "decline", "message": "The executed land terms already cover the schedule.", "terms": None})
    for path, expected in ((CASE_002, False), (CASE_003, True)):
        family_case = plugin.validate_payload(_payload(path))
        state = _state_after_land(plugin, family_case, _payload(path))
        amendment = _phase(plugin, family_case, "land_amendment_developer_offer")
        parsed = plugin.parse_action(family_case, state, "developer", amendment, _response(decline))
        assert parsed.ok is expected, path.name
        if not expected:
            assert parsed.error_code == "malformed_datacenter_stack_action"
            assert amendment.next_phases == ("land_amendment_landowner_response",)
            continue
        assert parsed.action == {"decision": "decline", "message": "The executed land terms already cover the schedule."}
        assert amendment.next_phases == ("land_amendment_landowner_response", "loan_developer_offer")
        assert plugin.legal(family_case, state, "developer", amendment, parsed.action) == LegalityResult.legal_action()
        land = _phase(plugin, family_case, "land_developer_offer")
        assert plugin.legal(family_case, state, "developer", land, parsed.action).reason == "decline_only_amends"
        # A bare decline (no reason) is also fine; an empty reason is not.
        assert plugin.parse_action(family_case, state, "developer", amendment, _response(json.dumps({"decision": "decline", "message": None, "terms": None}))).ok
        assert not plugin.parse_action(family_case, state, "developer", amendment, _response(json.dumps({"decision": "decline", "message": "  ", "terms": None}))).ok


def test_a_decline_keeps_the_executed_land_and_the_stack_proceeds_to_the_loan() -> None:
    payload = _payload(CASE_003)
    plugin = DataCenterStackPlugin("v2")
    family_case = plugin.validate_payload(payload)
    state = _state_after_land(plugin, family_case, payload)
    amendment = _phase(plugin, family_case, "land_amendment_developer_offer")
    action = {"decision": "decline", "message": None}
    transition = plugin.step(family_case, state, amendment, {"developer": _envelope("developer", action)})
    assert transition.next_phase_id == "loan_developer_offer"
    assert transition.state["declined"] == ["land_amendment"]
    assert transition.state["finished"] is False
    assert transition.state["public_history"][-1] == {
        "phase_id": "land_amendment_developer_offer",
        "seat_id": "developer",
        "agreement_key": "land_amendment",
        "decision": "decline",
        "message": None,
    }

    # Finish the stack on the reference path for the remaining agreements: the
    # outcome scores the land agreement as signed, not the amendment the
    # reference would have made.
    executed, _ = _baseline_stack(payload, "v2")
    terminal = _plain(transition.state)
    for key in ("power", "epc", "service", "loan"):
        terminal["executed"][key] = _plain(executed[key])
    terminal["finished"] = True
    terminal["termination_reason"] = "agreement_stack_executed"
    outcome = plugin.outcome(family_case, terminal)
    assert outcome["project_completed"] is True
    assert outcome["declined_agreements"] == ["land_amendment"]
    assert outcome["binding_contract_integrity"] is True
    stack = simulate_development_stack(
        ProjectFacts.from_dict(payload["project_facts"]),
        service_agreement=executed["service"],
        loan_agreement=executed["loan"],
        power_agreement=executed["power"],
        epc_agreement=executed["epc"],
        land_agreement=_executed_from_dict(terminal["executed"]["land"]),
    )
    assert outcome["developer_equity_npv_cents"] == stack.developer_equity_npv_cents
    assert outcome["project_constraints_satisfied"] == stack.negotiated_constraints_satisfied


def test_a_walk_may_state_its_reason_under_interface_three_only() -> None:
    plugin = DataCenterStackPlugin("v2")
    reason = "The lender's minimum credit support exceeds what the customer signed."
    walk = json.dumps({"decision": "walk", "message": reason, "terms": None})
    bare = json.dumps({"decision": "walk", "message": None, "terms": None})
    for path, allowed in ((CASE_002, False), (CASE_003, True)):
        family_case = plugin.validate_payload(_payload(path))
        state = _state_after_land(plugin, family_case, _payload(path))
        phase = _phase(plugin, family_case, "loan_developer_offer")
        parsed = plugin.parse_action(family_case, state, "developer", phase, _response(walk))
        assert parsed.ok is allowed, path.name
        assert plugin.parse_action(family_case, state, "developer", phase, _response(bare)).action == {"decision": "walk"}
        if allowed:
            assert parsed.action == {"decision": "walk", "message": reason}
            after = plugin.step(family_case, state, phase, {"developer": _envelope("developer", parsed.action)})
            assert after.state["termination_reason"] == "developer_walk"
            assert after.state["public_history"][-1]["message"] == reason
        else:
            assert parsed.error_code == "malformed_datacenter_stack_action"
            after = plugin.step(family_case, state, phase, {"developer": _envelope("developer", {"decision": "walk"})})
            assert "message" not in after.state["public_history"][-1]  # sealed history bytes


def _run(tmp_path: Path, case: Path, policy: str):
    root = tmp_path / policy
    setup, execution = asyncio.run(
        run_stack_offline("v2", evidence_root=root, case_path=case, developer_policy=policy)
    )
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    assert receipt.status == "ok" and receipt.inclusion_status == "included"
    assert replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=root) == receipt
    return setup, execution.episode_result.outcome


def test_the_curated_interface_three_case_seals_and_its_controls_bracket_it(tmp_path) -> None:
    case = load_stack_case("v2", CASE_003)
    assert case.case_id == "datacenter_development_v1.v2.full_stack_amendment_003"
    scripted, walk, adopt = (_run(tmp_path, CASE_003, policy) for policy in ("scripted", "walk_away", "adopt_every_counter"))
    assert scripted[1]["developer_equity_npv_cents"] == -72_000  # the reference amends, as on 002
    assert walk[1]["developer_equity_npv_cents"] == -100_000
    assert adopt[1]["developer_equity_npv_cents"] == -155_000
    developer_id = scripted[0].plan.cells[0].profile_by_seat["developer"]
    developer = next(p for p in scripted[0].plan.agent_profiles if p.profile_id == developer_id)
    assert developer.prompt.prompt_id == "datacenter_v2_developer_prompt_v3"


def test_a_generated_interface_three_pack_differs_from_the_sealed_one_only_by_the_key() -> None:
    three = _interface_three_pack()
    two = generate_pack(MASTER_SEED, split="worlds_v3", pack_id="test_worlds_v3")
    assert three["manifest"]["developer_interface"] == 3 and "developer_interface" not in two["manifest"]
    assert three["manifest"]["artifact_sha256"] != two["manifest"]["artifact_sha256"]
    assert [w["knobs"] for w in three["manifest"]["worlds"]] == [w["knobs"] for w in two["manifest"]["worlds"]]
    for a, b in zip(three["cases"], two["cases"]):
        pa, pb = copy.deepcopy(a["payload"]), copy.deepcopy(b["payload"])
        assert pa["construct_controls"].pop("developer_interface") == 3
        assert pa == pb
        assert a["content_sha256"] != b["content_sha256"]


def test_the_adoption_control_declines_the_amendment_and_reaches_the_loan_on_an_interface_three_world(tmp_path) -> None:
    """On the sealed pack the adopter walks at the amendment (DC-D-09); with a
    decline available it keeps the land as signed, copies the lender's counter
    and executes the stack, so its admission is decided by the world's traps
    and not by the interface."""

    document = _interface_three_pack()["cases"][0]
    path = tmp_path / "world.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sealed = json.loads((WORLDS_V2 / f"{document['case_id'].rsplit('.', 1)[1]}.json").read_text())
    assert sealed["payload"]["scenario_id"] == document["payload"]["scenario_id"]

    _, three = _run(tmp_path, path, "adopt_every_counter")
    _, two = _run(tmp_path / "sealed", WORLDS_V2 / f"{document['case_id'].rsplit('.', 1)[1]}.json", "adopt_every_counter")
    assert two["termination_reason"] == "developer_walk" and two["project_completed"] is False
    assert three["termination_reason"] == "agreement_stack_executed"
    assert three["project_completed"] is True
    assert list(three["declined_agreements"]) == ["land_amendment"]
    assert list(three["temporal_violations"]) == []
    assert three["developer_equity_npv_cents"] != two["developer_equity_npv_cents"]


def test_contract_zero_two_sums_declared_costs_in_integer_cents(tmp_path) -> None:
    cells = [{"declared_cell_max_cost_usd": 0.2}] * 72
    assert _declared_maximum({"schema_version": CONTRACT_SCHEMA_VERSIONS[1]}, cells) == 14.4
    assert _declared_maximum({"schema_version": CONTRACT_SCHEMA_VERSION}, cells) == sum(0.2 for _ in cells)
    contract = json.loads(CONFIRMATORY.read_text())
    contract["schema_version"] = CONTRACT_SCHEMA_VERSIONS[1]
    contract["campaign_id"] = "datacenter_development_v2_world_panel_test_v2"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract))
    assert load_contract(path)["schema_version"].endswith("/0.2")
    contract["schema_version"] = "aeread.datacenter_world_campaign_contract/0.9"
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="schema version"):
        load_contract(path)
