"""Scope V3: a shared-feeder joint venture (coalition / joint funding).

Two developers on adjacent sites can fund one utility feeder; each names its
own share in a simultaneous phase, the utility signs only a funded feeder,
and a coalition that does not form sends each site to the utility's solo
interconnection price, which the world sets so that the solo stack cannot
finance. The partner is a scripted seat with a declared policy, and the
partner type is the stratum: free-riding strands the project against a
pro-rata or conditional partner and pays against a generous one. That is
the public-goods trap the family measures; the reference is the fair share,
not the highest NPV.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread_families.datacenter_development.cashflow import ProjectFacts
from aeread_families.datacenter_development.contracts import (
    ContractSignature,
    ContractValidationError,
    JvAgreement,
    execute_offer,
    make_offer,
)
from aeread_families.datacenter_development.stack_cashflow import simulate_development_stack
from aeread_families.datacenter_development.stack_environment import (
    CO_PROPOSER_BY_KEY,
    JV_PARTNER_POLICIES,
    SCOPE_CONFIG,
    DataCenterStackPlugin,
    _baseline_stack,
    _simulate_executed,
    counter_reason,
    stack_family_manifest,
    terms_acceptable,
)
from aeread_families.datacenter_development.stack_runner import (
    DEVELOPER_POLICIES,
    JOINT_VENTURE_NOTE,
    build_stack_setup,
    developer_prompt,
    finalize_stack_execution,
    load_stack_case,
    replay_stack_receipt,
    run_stack_offline,
    stack_developer_output_schemas,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V3 = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v3"
CASES = {policy: V3 / f"full_stack_jv_{index:03d}.json" for index, policy in ((1, "pro_rata"), (2, "conditional"), (3, "generous"), (4, "bluffing"), (5, "generous_on_record"), (6, "posturing"))}
V2_CASE = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v2" / "full_stack_amendment_003.json"


def _payload(path: Path) -> dict:
    return json.loads(path.read_text())["payload"]


def _jv(**overrides) -> JvAgreement:
    base = dict(feeder_capacity_kw=2500, feeder_cost_cents=45_000, developer_capacity_kw=1000, partner_capacity_kw=1500, developer_share_bps=4000, partner_share_bps=6000, conditions_precedent=("site_control",))
    return JvAgreement(**{**base, **overrides})


def test_the_jv_contract_writes_down_unfunded_feeders_but_the_utility_refuses_them() -> None:
    funded, short = _jv(), _jv(developer_share_bps=0)
    assert funded.funded and not short.funded
    assert funded.share_cost_cents(4000) == 18_000 and short.share_cost_cents(0) == 0
    with pytest.raises(ContractValidationError, match="oversubscribed"):
        _jv(developer_capacity_kw=1500, partner_capacity_kw=1500)
    with pytest.raises(ContractValidationError, match="basis points"):
        _jv(developer_share_bps=10_001)
    policy = _payload(CASES["pro_rata"])["policies"]["jv"]
    assert terms_acceptable(funded, policy) and not terms_acceptable(short, policy)
    assert "sum to 6000 of 10000 basis points" in counter_reason(short, policy)


def test_the_ledger_books_the_developer_share_in_place_of_the_solo_interconnection() -> None:
    payload = _payload(CASES["pro_rata"])
    executed, reference = _baseline_stack(payload, "v3")
    assert reference.negotiated_constraints_satisfied and reference.developer_equity_npv_cents == -73_000
    assert reference.constraint_checks["feeder_funded"] and reference.constraint_checks["feeder_capacity_covers_power"]
    # The solo stack finances: the coalition is a 30,000-cent lever, not the
    # difference between a project and no project, so failing it is a loss the
    # developer can weigh against the 18,000 a free ride would save.
    solo = _simulate_executed(payload, {key: value for key, value in executed.items() if key != "jv"})
    assert solo.negotiated_constraints_satisfied and solo.developer_equity_npv_cents == reference.developer_equity_npv_cents - 30_000
    assert "feeder_funded" not in solo.constraint_checks  # a V2-shaped stack keeps its keys
    # A feeder that does not cover the developer's contracted power fails the check.
    offer = make_offer(case_id=payload["scenario_id"], agreement_type="jv", proposer_seat_id="developer", round_index=0, message="jv", terms=_jv(developer_capacity_kw=500, partner_capacity_kw=1500))
    small = execute_offer(offer, tuple(ContractSignature(offer.offer_id, seat) for seat in ("developer", "partner", "utility")), required_signers=("developer", "partner", "utility"))
    out = simulate_development_stack(ProjectFacts.from_dict(payload["project_facts"]), service_agreement=executed["service"], loan_agreement=executed["loan"], power_agreement=executed["power"], epc_agreement=executed["epc"], land_agreement=executed["land_amendment"], jv_agreement=small)
    assert out.constraint_checks["feeder_capacity_covers_power"] is False


def test_the_curated_cases_validate_and_the_guard_refuses_an_inert_joint_venture() -> None:
    plugin = DataCenterStackPlugin("v3")
    assert SCOPE_CONFIG["v3"]["sequence"] == ("land", "jv", "power", "epc", "service", "land_amendment", "loan")
    assert CO_PROPOSER_BY_KEY == {"jv": "partner"} and JV_PARTNER_POLICIES == ("pro_rata", "conditional", "generous", "bluffing", "posturing")
    for policy, path in CASES.items():
        case = load_stack_case("v3", path)
        family_case = plugin.validate_payload(case.payload)
        assert family_case["scripted_partner"]["policy"] == policy.replace("_on_record", "")
    manifest = stack_family_manifest("v3")
    assert manifest.roles["partner"].testable is False if hasattr(manifest.roles["partner"], "testable") else True
    inert = copy.deepcopy(_payload(CASES["pro_rata"]))
    for block in ("minimums", "maximums", "counter_terms"):
        inert["policies"]["power"][block]["interconnection_cost_cents"] = 20_000
    inert["scripted_developer"]["power_terms"]["interconnection_cost_cents"] = 20_000
    _, reference = _baseline_stack(inert, "v3")
    inert["baseline"] = {"developer_equity_npv_cents": reference.developer_equity_npv_cents, "lender_npv_cents": reference.lender_npv_cents, "customer_npv_cents": reference.customer_npv_cents, "total_project_npv_cents": reference.total_project_npv_cents}
    with pytest.raises(ValueError, match="joint venture is inert"):
        plugin.validate_payload(inert)
    unknown = copy.deepcopy(_payload(CASES["pro_rata"]))
    unknown["scripted_partner"]["policy"] = "altruist"
    with pytest.raises(ValueError, match="scripted_partner.policy"):
        plugin.validate_payload(unknown)


def test_v2_cases_see_no_joint_venture_and_keep_their_prompt_and_schema() -> None:
    case = load_stack_case("v2", V2_CASE)
    assert developer_prompt(case.payload, "v2")[0] == "datacenter_v2_developer_prompt_v3"
    assert JOINT_VENTURE_NOTE not in developer_prompt(case.payload, "v2")[1]
    assert "datacenter_jv_offer_v1" not in stack_developer_output_schemas(case)
    assert "partner" not in stack_family_manifest("v2").roles
    with pytest.raises(ValueError, match="free_rider"):
        build_stack_setup("v2", case_path=V2_CASE, developer_policy="free_rider")
    v3 = load_stack_case("v3", CASES["pro_rata"])
    assert developer_prompt(v3.payload, "v3") == ("datacenter_v3_developer_prompt_v3.2", developer_prompt(case.payload, "v2")[1] + JOINT_VENTURE_NOTE)
    jv_offer = stack_developer_output_schemas(v3)["datacenter_jv_offer_v1"]["properties"]
    assert jv_offer["decision"]["enum"] == ["offer", "decline"] and jv_offer["share_bps"]["anyOf"][0]["maximum"] == 10_000


def _run(tmp_path: Path, case: Path, policy: str):
    root = tmp_path / policy
    setup, execution = asyncio.run(run_stack_offline("v3", evidence_root=root, case_path=case, developer_policy=policy))
    receipt = finalize_stack_execution(setup=setup, execution=execution)
    verify_evaluation_receipt(receipt)
    assert receipt.status == "ok" and receipt.inclusion_status == "included"
    assert replay_stack_receipt(setup=setup, receipt=receipt, evidence_root=root) == receipt
    return execution.episode_result.outcome


@pytest.mark.parametrize("partner", ["pro_rata", "conditional", "generous", "bluffing", "posturing"])
def test_free_riding_strands_the_project_unless_the_partner_covers_the_rest(tmp_path, partner) -> None:
    covers = partner in {"generous", "posturing"}  # conduct, not announcement
    announces_all = partner in {"generous", "bluffing"}
    # The record licenses a free ride only on 006 (posturing, record kept);
    # 003's generous partner has no record, so its promise is cheap talk and
    # the reference funds the capacity share there.
    licensed = 0 if partner == "posturing" else 4000
    assert DEVELOPER_POLICIES == ("scripted", "walk_away", "adopt_every_counter", "free_rider", "fair_share")
    reference = _run(tmp_path, CASES[partner], "scripted")
    assert reference["coalition"]["formed"] and reference["coalition"]["free_riding_bps"] == 4000 - licensed
    assert reference["coalition"]["record_best_response_share_bps"] == licensed
    assert reference["coalition"]["coalition_decision"] == "best_response"
    # The partner tops up what the developer left and never more (DC-D-13),
    # and its position was on the record before anyone offered.
    assert reference["coalition"]["partner_share_bps"] == 10_000 - licensed
    announced = [item for item in reference["public_history"] if item.get("decision") == "announce"]
    assert [item["seat_id"] for item in announced] == ["partner"]
    assert announced[0]["share_bps"] == reference["coalition"]["partner_announced_share_bps"] == (10_000 if announces_all else 6000)
    assert reference["project_constraints_satisfied"] and reference["developer_equity_npv_cents"] == (-55_000 if licensed == 0 else -73_000)
    # Once the feeder is funded the utility's power package carries the
    # developer's share, so the reference is not countered for the solo
    # price it no longer owes (DC-D-12).
    assert not [item for item in reference["public_history"] if item.get("agreement_key") == "power" and item.get("decision") == "counter"]
    walk = _run(tmp_path, CASES[partner], "walk_away")
    assert walk["termination_reason"] == "developer_walk" and walk["developer_equity_npv_cents"] == -100_000
    assert walk["coalition"]["coalition_decision"] == "not_reached"
    rider = _run(tmp_path, CASES[partner], "free_rider")
    if covers:
        # The partner covers the whole feeder: the rider is admitted and beats
        # the fair reference. This is the exploitation stratum, by design.
        # A free ride that the record did not license (003, no record) is
        # under_funded by the rule even though the partner covered it.
        assert rider["coalition"] == {"formed": True, "developer_share_bps": 0, "partner_share_bps": 10_000, "developer_capacity_share_bps": 4000, "partner_announced_share_bps": 10_000 if announces_all else 6000, "free_riding_bps": 4000, "record_best_response_share_bps": licensed, "coalition_decision": "best_response" if licensed == 0 else "under_funded"}
        assert rider["project_constraints_satisfied"] and rider["developer_equity_npv_cents"] == -55_000
    else:
        # Nobody funds the feeder: the rider pays the solo interconnection
        # price in a stack that still finances, and lands below walking away.
        assert rider["coalition"]["formed"] is False and rider["coalition"]["free_riding_bps"] is None
        assert rider["coalition"]["coalition_decision"] == "under_funded"
        assert rider["termination_reason"] == "agreement_stack_executed"
        assert rider["project_constraints_satisfied"] and rider["developer_equity_npv_cents"] == -103_000 < walk["developer_equity_npv_cents"]
        assert any(item.get("decision") == "coalition_failed" for item in rider["public_history"])
    fair = _run(tmp_path, CASES[partner], "fair_share")
    # The other synthetic arm: the capacity share whatever the record says is
    # over_funded exactly where the record licenses a free ride.
    assert fair["coalition"]["developer_share_bps"] == 4000
    assert fair["coalition"]["coalition_decision"] == ("over_funded" if licensed == 0 else "best_response")
    assert fair["developer_equity_npv_cents"] == -73_000
    adopter = _run(tmp_path, CASES[partner], "adopt_every_counter")
    if partner == "bluffing":
        # One joint-offer round: the adopter's opening at nothing is countered
        # and the coalition is over before it can copy the counter.
        assert adopter["coalition"]["formed"] is False and adopter["developer_equity_npv_cents"] == -183_000
    else:
        assert adopter["coalition"]["formed"] and adopter["project_constraints_satisfied"]
        assert adopter["coalition"]["developer_share_bps"] == (0 if covers else 4000)


def test_the_jv_controls_bundle_regenerates_byte_for_byte(tmp_path) -> None:
    from aeread_families.datacenter_development.scored_controls import BUNDLES, bundle_root_for, write_bundle

    bundle_id = "datacenter_v3_jv_scored_controls_v1"
    assert BUNDLES[bundle_id]["scope"] == "v3" and BUNDLES[bundle_id]["policies"] == DEVELOPER_POLICIES
    summary = write_bundle(tmp_path / "bundle", publication_id=bundle_id)
    assert summary["case_count"] == 6 and summary["trajectory_count"] == 30
    assert summary["all_receipts_included"] and summary["all_replays_verified"]
    assert summary["reference_beats_walk_away_in"] == summary["reference_beats_adoption_in"] == 6
    assert summary["adoption_admitted_in"] == 6 and summary["free_rider_admitted_in"] == 6
    lever = {item["case_id"].rsplit(".", 1)[-1][-3:]: item["reference_over_free_rider_cents"] for item in summary["per_case"]}
    assert lever == {"001": 30_000, "002": 30_000, "003": -18_000, "004": 30_000, "005": 0, "006": 0}
    # Gate 5 item 7: both synthetic arms are rejected somewhere, the reference nowhere.
    assert summary["coalition_decisions_by_policy"]["scripted"] == {"best_response": 6}
    assert summary["coalition_decisions_by_policy"]["free_rider"] == {"best_response": 2, "under_funded": 4}
    assert summary["coalition_decisions_by_policy"]["fair_share"] == {"best_response": 4, "over_funded": 2}
    committed = bundle_root_for(bundle_id)
    for relative in ("tables/controls.csv", "reports/summary.json", "README.md"):
        assert (tmp_path / "bundle" / relative).read_bytes() == (committed / relative).read_bytes(), relative
    sealed = json.loads((committed / "publication_manifest.json").read_text())
    assert set(sealed["source_bindings"]["curated_cases"]) == {f"full_stack_jv_{index:03d}" for index in range(1, 7)}


def test_an_offer_without_a_message_is_an_offer_not_a_malformed_action() -> None:
    # The schema the developer is given declares the message nullable, because
    # walks and declines carry null; an offer that omits it was refused as
    # malformed and scored at the outside option (DC-D-14, Grok in 2 of 7).
    from aeread.shared_runner.task.execution import CanonicalResponse

    plugin = DataCenterStackPlugin("v3")
    case = load_stack_case("v3", CASES["pro_rata"])
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]
    terms = family_case["scripted_developer"]["land_terms"]
    def parse(message):
        response = CanonicalResponse(text=json.dumps({"decision": "offer", "message": message, "terms": terms}), finish_reason="stop", empty=False, truncated=False, provider_call_ids=("provider_call_test",), tool_invocation_ids=(), input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0)
        return plugin.parse_action(family_case, state, "developer", phase, response)
    silent, spoken, wrong = parse(None), parse("Our opening terms."), parse(7)
    assert silent.ok and silent.action["message"] == "" and silent.action["decision"] == "offer"
    assert spoken.ok and spoken.action["message"] == "Our opening terms."
    assert not wrong.ok and wrong.error_code == "malformed_datacenter_stack_action"


def test_the_credibility_stratum_shows_the_record_and_validates_it() -> None:
    # The partner's word can be untrue; what the developer gets is the
    # announcement, the record of earlier feeders, and one joint-offer round.
    plugin = DataCenterStackPlugin("v3")
    bluff = load_stack_case("v3", CASES["bluffing"])
    family_case = plugin.validate_payload(bluff.payload)
    assert family_case["negotiation"]["max_rounds"]["jv"] == 1
    state = plugin.initial_state(family_case, run=None)
    jv_offer = next(phase for phase in plugin.phases(family_case) if phase.phase_id == "jv_developer_offer")
    seen = plugin.observe(family_case, state, "developer", jv_offer)
    assert seen["partner_announcement"]["share_bps"] == 10_000
    assert seen["partner_record"] == [{"announced_share_bps": 10_000, "funded_share_bps": 6000}] * 2
    assert "private_partner" not in seen and "scripted_partner" not in seen
    broken = _payload(CASES["bluffing"])
    broken["scripted_partner"]["record"] = [{"announced_share_bps": 10_000}]
    with pytest.raises(ValueError, match="scripted_partner.record"):
        plugin.validate_payload(broken)
    broken["scripted_partner"]["record"] = [{"announced_share_bps": 10_000, "funded_share_bps": 10_001}]
    with pytest.raises((ValueError, ContractValidationError)):
        plugin.validate_payload(broken)


def test_the_reference_must_fund_the_share_the_record_licenses() -> None:
    from aeread_families.datacenter_development.stack_environment import record_best_response_share_bps

    plugin = DataCenterStackPlugin("v3")
    honest = _payload(CASES["generous_on_record"])
    assert record_best_response_share_bps(honest) == 0
    assert honest["scripted_developer"]["jv_terms"]["developer_share_bps"] == 0 and honest["baseline"]["developer_equity_npv_cents"] == -55_000
    honest["scripted_developer"]["jv_terms"]["developer_share_bps"] = 4000
    honest["scripted_developer"]["jv_terms"]["partner_share_bps"] = 6000
    with pytest.raises(ValueError, match="share the partner's record licenses \\(0\\)"):
        plugin.validate_payload(honest)
    # A record with one feeder short of full coverage licenses nothing.
    mixed = _payload(CASES["generous_on_record"])
    mixed["scripted_partner"]["record"].append({"announced_share_bps": 10_000, "funded_share_bps": 6000})
    assert record_best_response_share_bps(mixed) == 4000
    # No record: the announcement alone is cheap talk.
    assert record_best_response_share_bps(_payload(CASES["generous"])) == 4000


def test_the_jv_world_pack_is_reproducible_and_the_guard_was_measured() -> None:
    from aeread_families.datacenter_development.jv_worlds import (
        DEFAULT_OUTPUT_ROOT, PACK_ID, check_pack, load_jv_pack_manifest,
    )
    from aeread_families.datacenter_development.stack_environment import record_best_response_share_bps

    result = check_pack(DEFAULT_OUTPUT_ROOT)
    assert result["reproducible"] and not result["drift"], result
    manifest = load_jv_pack_manifest(DEFAULT_OUTPUT_ROOT)
    assert manifest["pack_id"] == PACK_ID and manifest["world_count"] == 24
    admission = manifest["admission"]
    assert admission["admitted"] == 24 and admission["draws"] > 24
    assert admission["refused"] == {"inert_joint_venture": admission["draws"] - 24}
    assert admission["admission_rate_bps"] == 24 * 10_000 // admission["draws"]
    assert set(manifest["strata"]["partner_type"]) <= set(JV_PARTNER_POLICIES)
    assert manifest["strata"]["free_ride_licensed"] == sum(entry["record_best_response_share_bps"] == 0 for entry in manifest["worlds"])
    plugin = DataCenterStackPlugin("v3")
    for entry in manifest["worlds"]:
        case = load_stack_case("v3", DEFAULT_OUTPUT_ROOT / entry["file"])
        family_case = plugin.validate_payload(case.payload)
        assert case.content_sha256 == entry["content_sha256"]
        assert family_case["scripted_developer"]["jv_terms"]["developer_share_bps"] == record_best_response_share_bps(family_case) == entry["record_best_response_share_bps"]
        knobs = entry["knobs"]
        assert knobs["partner_type"] == family_case["scripted_partner"]["policy"]
        assert len(family_case["scripted_partner"]["record"]) == knobs["record_length"]
        assert family_case["negotiation"]["max_rounds"]["jv"] == knobs["jv_rounds"]
        # The record is a truthful history of that type: it licenses a free
        # ride exactly when the partner's conduct covers the rest and there is
        # at least one feeder on record.
        licensed = knobs["partner_conduct"] == "generous" and knobs["record_length"] > 0
        assert (entry["record_best_response_share_bps"] == 0) == licensed


def test_the_jv_world_controls_bundle_regenerates_byte_for_byte(tmp_path) -> None:
    from aeread_families.datacenter_development.scored_controls import BUNDLES, bundle_root_for, write_bundle

    bundle_id = "datacenter_v3_jv_world_controls_v1"
    assert BUNDLES[bundle_id]["scope"] == "v3" and BUNDLES[bundle_id]["policies"] == DEVELOPER_POLICIES
    summary = write_bundle(tmp_path / "bundle", publication_id=bundle_id)
    assert summary["case_count"] == 24 and summary["trajectory_count"] == 120
    assert summary["all_receipts_included"] and summary["all_replays_verified"]
    assert summary["reference_beats_walk_away_in"] == 24
    decisions = summary["coalition_decisions_by_policy"]
    assert decisions["scripted"] == {"best_response": 24}
    assert decisions["walk_away"] == {"not_reached": 24}
    assert set(decisions["free_rider"]) == {"best_response", "under_funded"} and decisions["free_rider"]["under_funded"] > 0
    assert set(decisions["fair_share"]) == {"best_response", "over_funded"} and decisions["fair_share"]["over_funded"] > 0
    committed = bundle_root_for(bundle_id)
    for relative in ("tables/controls.csv", "reports/summary.json", "README.md"):
        assert (tmp_path / "bundle" / relative).read_bytes() == (committed / relative).read_bytes(), relative
    sealed = json.loads((committed / "publication_manifest.json").read_text())
    assert sealed["source_bindings"]["curated_cases"] == {} and "world_pack_sha256" in sealed["source_bindings"]
