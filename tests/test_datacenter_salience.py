from __future__ import annotations

import pytest

import asyncio
import csv
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development.adoption_environment_v2 import starter_terms
from aeread_families.datacenter_development.salience_campaign import (
    _paired_transitions,
    build_design,
    load_contract,
)
from aeread_families.datacenter_development.salience_environment import (
    CONDITIONS,
    CounterofferSaliencePlugin,
)
from aeread_families.datacenter_development.salience_runner import (
    build_salience_setup,
    finalize_salience_execution,
    load_salience_case,
    replay_salience_receipt,
    run_salience_offline,
)
from aeread_families.datacenter_development.salience_publication import (
    PROHIBITED_PUBLIC_TEXT,
)


def _second_offer_state(family_case):
    plugin = CounterofferSaliencePlugin()
    state = plugin.initial_state(family_case, run=None)
    initial = starter_terms(family_case, "land")
    state["rounds"]["land"] = 1
    state["offers"].append(
        {
            "offer_id": "offer_public_initial",
            "case_id": family_case["scenario_id"],
            "agreement_type": "land",
            "proposer_seat_id": "developer",
            "round_index": 0,
            "message": "Initial structured offer.",
            "terms": initial,
            "supersedes_offer_id": None,
            "amended_fields": [],
            "precedence_index": 0,
        }
    )
    state["latest_offer_id"]["land"] = "offer_public_initial"
    state["pending_counter_terms"]["land"] = family_case["policies"]["land"][
        "counter_terms"
    ]
    return state


def test_salience_cases_are_hash_pinned_and_differ_only_by_presentation() -> None:
    payloads = {}
    for condition in CONDITIONS:
        case = load_salience_case(condition)
        assert case.content_sha256 == case_content_sha256(case)
        assert case.payload["salience_condition"] == condition
        payloads[condition] = {
            key: value
            for key, value in case.payload.items()
            if key != "salience_condition"
        }
    assert payloads["full_package"] == payloads["explicit_delta"]


def test_delta_is_derived_from_public_packages_without_private_policy() -> None:
    plugin = CounterofferSaliencePlugin()
    observations = {}
    for condition in CONDITIONS:
        family_case = plugin.validate_payload(load_salience_case(condition).payload)
        state = _second_offer_state(family_case)
        phase = plugin.phases(family_case)[0]
        observations[condition] = plugin.observe(
            family_case, state, "developer", phase
        )

    assert "counteroffer_delta" not in observations["full_package"]
    assert observations["explicit_delta"]["counteroffer_delta"] == [
        {
            "field": "purchase_price_cents",
            "prior_value": 19_999,
            "counter_value": 20_000,
        }
    ]
    assert "private_policy" not in repr(observations)
    for field in ("latest_offer", "pending_counter_terms"):
        assert canonical_json_bytes(observations["full_package"][field]) == (
            canonical_json_bytes(observations["explicit_delta"][field])
        )


def test_salience_provider_free_conditions_score_one_and_replay(tmp_path: Path) -> None:
    async def run() -> None:
        for condition in CONDITIONS:
            root = tmp_path / condition
            setup, execution = await run_salience_offline(
                condition, evidence_root=root
            )
            receipt = finalize_salience_execution(
                setup=setup, execution=execution
            )
            replayed = replay_salience_receipt(
                setup=setup, receipt=receipt, evidence_root=root
            )
            primary = next(
                score.primary.value
                for score in receipt.scores
                if score.leaf.leaf_id == "counteroffer_adoption_rate"
            )
            assert primary == 1.0
            assert execution.episode_result.outcome["salience_condition"] == condition
            assert replayed == receipt

    asyncio.run(run())


def test_salience_conditions_use_identical_live_profile_treatment() -> None:
    contract = load_contract()
    model = contract["models"]["mistral32_deepinfra"]
    from aeread_families.datacenter_development.objective_campaign import _route

    setups = [
        build_salience_setup(condition, route=_route(model), seed=312401)
        for condition in CONDITIONS
    ]
    profiles = []
    for setup in setups:
        developer_id = setup.plan.cells[0].profile_by_seat["developer"]
        profiles.append(
            next(
                profile
                for profile in setup.plan.agent_profiles
                if profile.profile_id == developer_id
            )
        )
    assert canonical_json_bytes(profiles[0]) == canonical_json_bytes(profiles[1])


def test_salience_campaign_is_paired_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 20
    assert design["planned_pair_count"] == 10
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.6)
    assert design["worst_case_declared_cost_usd"] <= design["campaign_max_cost_usd"]
    assert contract["analysis"]["population_causal_effect_allowed"] is False
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert all(cell["live_profile_count"] == 1 for cell in design["cells"])
    assert {
        (cell["condition"], cell["model_id"], cell["inference_seed"])
        for cell in design["cells"]
    } == {
        (condition, model_id, seed)
        for condition in CONDITIONS
        for model_id in contract["models"]
        for seed in contract["inference_seeds"]
    }


def test_paired_transition_summary_requires_both_included_conditions() -> None:
    contract = load_contract()
    model_id = "mistral32_deepinfra"
    rows = []
    for seed in contract["inference_seeds"]:
        for condition in CONDITIONS:
            score = 1.0 if condition == "explicit_delta" and seed == 312401 else 0.0
            rows.append(
                {
                    "model_id": model_id,
                    "inference_seed": seed,
                    "condition": condition,
                    "status": (
                        "operational_failure"
                        if condition == "explicit_delta" and seed == 312402
                        else "completed"
                    ),
                    "inclusion_status": (
                        "excluded"
                        if condition == "explicit_delta" and seed == 312402
                        else "included"
                    ),
                    "scores": {
                        "counteroffer_adoption_rate": {"value": score}
                    },
                }
            )
    rows.extend(
        {**row, "model_id": "qwen3_235b_novita"}
        for row in list(rows)
    )

    summaries = {
        row["model_id"]: row for row in _paired_transitions(contract, rows)
    }

    assert summaries[model_id] == {
        "model_id": model_id,
        "planned_pairs": 5,
        "usable_pairs": 4,
        "missing_pairs": 1,
        "neither_adopted": 3,
        "delta_only_adopted": 1,
        "full_only_adopted": 0,
        "both_adopted": 0,
    }


def test_published_salience_campaign_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_counteroffer_salience_v1"
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development/salience_publication.py"
        ).read_bytes()
    ).hexdigest()
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    manifest_core = {
        key: value for key, value in manifest.items() if key != "artifact_sha256"
    }

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(manifest_core)
    ).hexdigest()
    assert manifest["publisher_implementation_sha256"] == publisher_hash
    assert len(manifest["source_receipt_sha256s"]) == 20
    assert len(set(manifest["source_receipt_sha256s"])) == 20
    assert len(manifest["source_result_sha256s"]) == 20
    assert len(set(manifest["source_result_sha256s"])) == 20
    assert all(value is False for value in manifest["sanitization"].values())

    for relative, metadata in manifest["files"].items():
        payload = (publication / relative).read_bytes()
        assert len(payload) == metadata["bytes"]
        assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
        lowered = payload.decode("utf-8").lower()
        assert not any(token in lowered for token in PROHIBITED_PUBLIC_TEXT)


def test_published_salience_results_retain_all_pairs_and_claim_boundaries() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_counteroffer_salience_v1"
    )
    summary = json.loads((publication / "reports/summary.json").read_text())
    trajectories = [
        json.loads(line)
        for line in (publication / "trajectories/sanitized.jsonl")
        .read_text()
        .splitlines()
    ]
    receipts = (
        publication / "receipts/projections.jsonl"
    ).read_text().splitlines()
    with (publication / "tables/paired_results.csv").open(newline="") as handle:
        pairs = list(csv.DictReader(handle))

    assert summary["publication_interpretation"] == (
        "paired_public_delta_salience_diagnostic"
    )
    assert summary["planned_cells"] == 20
    assert summary["completed_cells"] == 20
    assert summary["included_cells"] == 20
    assert summary["operational_failure_cells"] == 0
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["reported_cost_usd"] == 0.0047416594500000004
    assert summary["observed_reported_cost_usd"] == summary["reported_cost_usd"]
    assert summary["observed_cost_qualifier"] == "exact"
    assert summary["winner_claim_allowed"] is False
    assert summary["population_generalization_allowed"] is False
    assert summary["population_causal_effect_allowed"] is False
    assert summary["initial_provider_requests_match_within_all_pairs"] is True
    assert summary["assignment_level_usable_pairs"] == 10
    assert summary["counteroffer_exposed_cells"] == 19
    assert summary["exposure_qualified_pairs"] == 9
    assert summary["unexposed_pairs"] == 1
    assert summary["exposure_qualified_transition_counts"] == {
        "both_adopted": 0,
        "delta_only_adopted": 0,
        "full_only_adopted": 0,
        "neither_adopted": 9,
    }

    assert len(trajectories) == 20
    assert len(receipts) == 20
    assert all(row["status"] == "completed" for row in trajectories)
    assert all(row["inclusion_status"] == "included" for row in trajectories)
    assert all(row["route_verified"] is True for row in trajectories)
    assert all(row["replay_verified"] is True for row in trajectories)
    assert sum(
        row["outcome"]["counteroffer_opportunity_count"] == 1
        for row in trajectories
    ) == 19
    assert all(
        row["outcome"]["counteroffer_adoption_count"] == 0
        and row["outcome"]["prefix_completed"] is False
        for row in trajectories
    )
    assert all("public_history" not in row["outcome"] for row in trajectories)
    assert len(pairs) == 10
    assert all(row["pair_reportable"] == "True" for row in pairs)
    assert all(row["initial_provider_request_match"] == "True" for row in pairs)
    assert all(row["transition"] == "neither_adopted" for row in pairs)
    assert sum(row["exposure_qualified"] == "True" for row in pairs) == 9
    assert sum(row["exposure_transition"] == "unexposed_pair" for row in pairs) == 1
