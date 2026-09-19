"""Provider-free Phase 2 conformance; human approvals below are test fixtures only."""

import asyncio
import copy
from dataclasses import replace
import hashlib
import itertools
import json

import pytest
from aeread.shared_runner.quality import (
    FamilyContribution,
    HumanQCApproval,
    QCEvidenceRef,
    QCCoverage,
    ResourceLimits,
)
from aeread.shared_runner.registry import (
    PluginRegistry,
    family_contribution_sha256,
    ContributionAdmissionError,
    _strict_schema,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.procurement_allocation import environment as legacy
from aeread_families.procurement_allocation.phase2_environment import (
    Phase2Plugin,
    FAMILY_ID,
    PLUGIN_ID,
    family_manifest,
)
from aeread_families.procurement_allocation.phase2_worlds import (
    build_world,
    episode_case,
    SCREEN_SEEDS,
)
from aeread_families.procurement_allocation.phase2_policies import (
    replay_policy,
    choose_action,
    replay_best_qualified,
)
from aeread_families.procurement_allocation.phase2_admission import (
    action_schema,
    observation_schema,
    load_contribution,
)
from aeread_families.procurement_allocation.phase2_runner import build_setup
from aeread_families.procurement_allocation.runner import (
    SequenceResponseProvider,
    finalize_procurement_allocation_execution,
    replay_procurement_allocation_receipt,
)


def fixture_contribution(tmp_path):
    def ref(kind, coverage):
        path = tmp_path / f"{kind}.json"
        path.write_text(json.dumps({"test_only": True, "not_human_approval": True}))
        return QCEvidenceRef(
            artifact_type=kind,
            path=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            family_id=FAMILY_ID,
            family_version="1.0.0",
            profile_id=FAMILY_ID,
            coverage=(QCCoverage(coverage, ("test_fixture",), ("test_fixture",)),),
        )

    provider = ref("provider_free_conformance", "provider_free_validation")
    approval = ref("human_qc_approval", "human_qc")
    c = FamilyContribution(
        family_id=FAMILY_ID,
        family_version="1.0.0",
        plugin_id=PLUGIN_ID,
        registry_namespace="test.procurement_phase2",
        action_schema=action_schema(),
        observation_schema=observation_schema(),
        provider_free_evidence=provider,
        resource_limits=ResourceLimits(1800.0, 10, 20, 100_000, 24_000, 0.025),
        human_qc_approval=HumanQCApproval(
            "test_fixture_not_a_reviewer", "approved", "0" * 64, approval
        ),
    )
    return replace(
        c,
        human_qc_approval=replace(
            c.human_qc_approval, contribution_sha256=family_contribution_sha256(c)
        ),
    )


@pytest.mark.parametrize("index", range(8))
def test_world_identity_limits_and_economic_certificate(index):
    raw = build_world(index)
    assert case_content_sha256(CaseManifest.from_dict(raw)) == raw["content_sha256"]
    p = raw["payload"]
    assert len(p["suppliers"]) == 8 and p["interaction"]["max_actions"] == 10
    upper = legacy.solve_full_information_upper_bound(p)
    assert upper.actions_required <= 10
    if index >= 6:
        assert upper.contribution_margin_usd == 0 and not upper.award_plan
        assert replay_best_qualified(p)["decision"] == "defer"
    else:
        assert upper.contribution_margin_usd > 0
        greedy = replay_policy(p, "greedy")["outcome"]
        assert (
            upper.contribution_margin_usd - greedy["contribution_margin_usd"]
        ) / upper.contribution_margin_usd >= 0.15
    if index < 2:
        assert len(upper.award_plan) == 2
        assert all(
            s["private_terms"]["capacity"] < p["objective"]["minimum_service_kits"]
            for s in p["suppliers"]
        )


@pytest.mark.parametrize("index", [6, 7])
def test_traps_reject_every_action_reachable_purchase_even_with_all_evidence(index):
    case = build_world(index)["payload"]
    offers = {}
    samples = {}
    for s in case["suppliers"]:
        o = legacy._best_offer(s, version=2, issued_day=0)
        offers[o["offer_id"]] = o
        samples[s["supplier_id"]] = {
            "evidence_status": "verified_sample",
            "variant_id": o["variant_id"],
        }
    # Generously grant all evidence for free; even this relaxation cannot buy.
    for n in range(1, 5):
        for subset in itertools.combinations(offers.values(), n):
            result = legacy.evaluate_award(
                case,
                award_lines=[
                    {"offer_id": o["offer_id"], "quantity": o["capacity"]}
                    for o in subset
                ],
                offers=offers,
                quality_evidence=samples,
                elapsed_days=0,
                information_cost_usd=0,
            )
            assert not result["feasible"]


def test_checker_disabled_at_schema_parse_legality_and_step():
    p = Phase2Plugin()
    c = build_world(0)["payload"]
    phase = p.phases(c)[0]
    state = p.initial_state(c, None)
    a = {"action": "check_award", "award_lines": [{"offer_id": "fake", "quantity": 12}]}
    assert "check_award" not in action_schema()["properties"]["action"]["enum"]
    assert not p.parse_action(c, state, "buyer", phase, a).ok
    assert not p.legal(c, state, "buyer", phase, a).legal
    parsed = legacy.ProcurementAllocationPlugin().parse_action(
        c, state, "buyer", phase, a
    )
    legal = legacy.ProcurementAllocationPlugin().legal(c, state, "buyer", phase, a)
    with pytest.raises(ValueError, match="disabled"):
        p.step(
            c, state, phase, {"buyer": ActionEnvelope("buyer", True, a, parsed, legal)}
        )


def test_observation_hides_current_yield_noise_seed_and_category():
    p = Phase2Plugin()
    c = build_world(2)["payload"]
    phase = p.phases(c)[0]
    state = p.initial_state(c, None)
    original = p.observe(c, state, "buyer", phase)
    changed = copy.deepcopy(c)
    for s in changed["suppliers"]:
        s["private_terms"]["quality"]["verified_yield_rate"] = 0.1
    changed["interaction"]["sample_noise"]["seed"] = 999999
    assert p.observe(changed, state, "buyer", phase) == original
    text = json.dumps(original)
    assert (
        "verified_yield_rate" not in text
        and "sample_noise" not in text
        and "award_checks" not in text
    )


def test_costs_survive_defer_and_invalid_awards():
    p = Phase2Plugin()
    c = build_world(6)["payload"]
    t = replay_policy(c)["terminal"]
    t = copy.deepcopy(t)
    t["information_cost_usd"] = 0.75
    o = p.outcome(c, t)
    assert (
        o["decision"] == "defer"
        and o["regret_to_upper_bound_usd"] == 0.75
        and not o["feasible_award"]
    )
    invalid = replay_policy(c, "always_buy")["outcome"]
    assert (
        invalid["decision"] == "award"
        and not invalid["feasible_award"]
        and invalid["violations"]
    )


def test_evidence_gate_rejects_missing_sample_expiry_and_wrong_variant():
    c = build_world(2)["payload"]
    t = replay_policy(c)["terminal"]
    for mutation in ("sample", "expiry", "variant"):
        bad = copy.deepcopy(t)
        o = next(iter(bad["offers"].values()))
        if mutation == "sample":
            bad["quality_evidence"] = {}
        if mutation == "expiry":
            bad["elapsed_days"] = 100
        if mutation == "variant":
            o["variant_id"] = "wrong"
        assert not Phase2Plugin().outcome(c, bad)["feasible_award"]


def test_dynamic_stopping_changes_on_acquired_evidence_only():
    r = replay_policy(build_world(2)["payload"])
    o = copy.deepcopy(r["trace"][-1]["observation"])
    assert choose_action(o)["action"] == "submit_award"
    o["verified_samples"][0].update(observed_yield_rate=17 / 24, observed_defects=7)
    assert choose_action(o)["action"] == "request_quote"


@pytest.mark.parametrize("index", range(8))
def test_catalog_order_does_not_select_reference_actions(index):
    c = build_world(index)["payload"]
    a = replay_policy(c)
    b = replay_policy(c, supplier_order=list(reversed(range(8))))
    assert [r["action"] for r in a["trace"]] == [r["action"] for r in b["trace"]]
    assert a["outcome"] == b["outcome"]


def test_market_certificate_cannot_lie():
    c = build_world(0)["payload"]
    c["policy"]["market_constraints"]["minimum_delivery_days"] = 100
    with pytest.raises(ValueError, match="contradicts"):
        Phase2Plugin().validate_payload(c)


def test_closed_observation_schema_covers_all_offline_frames():
    def validate(value, schema):
        kind = schema["type"]
        if kind == "object":
            assert isinstance(value, dict) and set(value) == set(schema["required"])
            for k, v in value.items():
                validate(v, schema["properties"][k])
        elif kind == "array":
            assert isinstance(value, list)
            for v in value:
                validate(v, schema["items"])
        elif kind == "number":
            assert isinstance(value, (int, float)) and not isinstance(value, bool)
        elif kind == "boolean":
            assert isinstance(value, bool)
        elif kind == "string":
            assert isinstance(value, str)
        else:
            raise AssertionError(kind)

    schema = observation_schema()
    _strict_schema(schema, "observation")
    for i in range(8):
        for row in replay_policy(build_world(i)["payload"])["trace"]:
            validate(row["observation"], schema)


def test_new_family_requires_real_admission_for_production(tmp_path):
    with pytest.raises(ContributionAdmissionError):
        PluginRegistry().register_trusted(family_manifest(), Phase2Plugin())
    with pytest.raises(FileNotFoundError):
        load_contribution(tmp_path)


@pytest.mark.parametrize("index", [0, 2, 6, 7])
def test_shared_runner_receipt_replays_for_awards_and_zero_bound_traps(tmp_path, index):
    raw = build_world(index)
    s = build_setup(
        raw, contribution=fixture_contribution(tmp_path), evidence_root=tmp_path
    )
    script = [json.dumps(r["action"]) for r in replay_policy(raw["payload"])["trace"]]
    provider = SequenceResponseProvider(script)
    e = asyncio.run(
        execute_plan_cell(
            plan=s.plan,
            cell_id=s.plan.cells[0].cell_id,
            registry=s.registry,
            evidence_root=tmp_path / "run",
            prompt_sources=s.prompt_sources,
            providers={"fake": provider},
            pricing=s.pricing,
            harnesses=s.harnesses,
        )
    )
    receipt = finalize_procurement_allocation_execution(setup=s, execution=e)
    replay = replay_procurement_allocation_receipt(
        setup=s, receipt=receipt, evidence_root=tmp_path / "run"
    )
    assert canonical_json_bytes(replay) == canonical_json_bytes(receipt)
    assert provider.exhausted
    assert e.episode_result.outcome["feasible"]
    if index >= 6:
        assert e.episode_result.outcome["upper_bound_usd"] == 0


def test_behavior_diagnostics_bind_sample_to_next_action():
    from aeread_families.procurement_allocation.phase2_policies import (
        behavior_diagnostics,
    )

    c = build_world(2)["payload"]
    r = replay_policy(c)
    d = behavior_diagnostics(c, [x["action"] for x in r["trace"]])
    assert d["first_quote_matches_public_reference"]
    assert d["sample_decision_events"][0]["next_action"] == "submit_award"
    assert d["sample_decision_events"][0]["inspected_units"] == 24
    c = build_world(6)["payload"]
    r = replay_policy(c)
    assert behavior_diagnostics(c, [x["action"] for x in r["trace"]])[
        "deferral_supported_by_market_certificate"
    ]
