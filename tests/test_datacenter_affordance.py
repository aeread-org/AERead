from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development.affordance_campaign import (
    _paired_transitions,
    build_design,
    load_contract,
)
from aeread_families.datacenter_development.affordance_environment import (
    CONDITIONS,
    CounterofferAffordancePlugin,
)
from aeread_families.datacenter_development.affordance_runner import (
    build_affordance_setup,
    finalize_affordance_execution,
    load_affordance_case,
    replay_affordance_receipt,
    run_affordance_offline,
)
from aeread_families.datacenter_development.objective_campaign import _route
from aeread_families.datacenter_development.affordance_publication import (
    PROHIBITED_PUBLIC_TEXT,
)


def test_affordance_cases_are_hash_pinned_and_differ_only_by_condition() -> None:
    payloads = {}
    for condition in CONDITIONS:
        case = load_affordance_case(condition)
        assert case.content_sha256 == case_content_sha256(case)
        assert case.payload["affordance_condition"] == condition
        payloads[condition] = {
            key: value
            for key, value in case.payload.items()
            if key != "affordance_condition"
        }
    assert payloads["reemit_package"] == payloads["accept_by_reference"]


def test_affordance_initial_observations_are_identical_and_hide_policy() -> None:
    plugin = CounterofferAffordancePlugin()
    observations = []
    for condition in CONDITIONS:
        family_case = plugin.validate_payload(load_affordance_case(condition).payload)
        state = plugin.initial_state(family_case, run=None)
        phase = plugin.phases(family_case)[0]
        observation = plugin.observe(family_case, state, "developer", phase)
        observations.append(observation)
        assert "private_policy" not in repr(observation)
        assert "affordance_condition" not in repr(observation)
        assert "counteroffer_resolution" not in observation
    assert canonical_json_bytes(observations[0]) == canonical_json_bytes(
        observations[1]
    )


def test_affordance_provider_free_paths_execute_exactly_and_replay(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        for condition in CONDITIONS:
            root = tmp_path / condition
            setup, execution = await run_affordance_offline(
                condition, evidence_root=root
            )
            receipt = finalize_affordance_execution(
                setup=setup, execution=execution
            )
            replayed = replay_affordance_receipt(
                setup=setup, receipt=receipt, evidence_root=root
            )
            outcome = execution.episode_result.outcome
            primary = next(
                score.primary.value
                for score in receipt.scores
                if score.leaf.leaf_id == "counteroffer_adoption_rate"
            )
            decisions = [row["decision"] for row in outcome["public_history"]]

            assert primary == 1.0
            assert outcome["counteroffer_opportunity_count"] == 1
            assert outcome["counteroffer_adoption_count"] == 1
            assert outcome["prefix_completed"] is True
            assert outcome["exact_package_integrity"] is True
            assert decisions.count("counter") == 1
            assert replayed == receipt
            if condition == "reemit_package":
                assert outcome["reference_acceptance_count"] == 0
                assert "accept_counteroffer" not in decisions
            else:
                assert outcome["reference_acceptance_count"] == 1
                assert decisions.count("accept_counteroffer") == 1

    asyncio.run(run())


def test_affordance_conditions_share_live_profile_and_output_schema() -> None:
    contract = load_contract()
    model = contract["models"]["mistral32_deepinfra"]
    setups = [
        build_affordance_setup(condition, route=_route(model), seed=312501)
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
    schemas = [
        profile.harness.config["output_schema_by_action_schema"] for profile in profiles
    ]
    assert canonical_json_bytes(schemas[0]) == canonical_json_bytes(schemas[1])
    offer = schemas[0]["datacenter_land_offer_v1"]
    assert set(offer["properties"]["decision"]["enum"]) == {
        "offer",
        "walk",
        "accept_counteroffer",
    }


def test_affordance_campaign_is_paired_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 20
    assert design["planned_pair_count"] == 10
    assert design["worst_case_declared_cost_usd"] == 0.6
    assert design["worst_case_declared_cost_usd"] <= design[
        "campaign_max_cost_usd"
    ]
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


def test_affordance_pair_summary_keeps_provider_failure_as_missing() -> None:
    contract = load_contract()
    rows = []
    for model_id in contract["models"]:
        for seed in contract["inference_seeds"]:
            for condition in CONDITIONS:
                excluded = (
                    model_id == "mistral32_deepinfra"
                    and seed == 312502
                    and condition == "accept_by_reference"
                )
                score = float(
                    condition == "accept_by_reference" and seed == 312501
                )
                rows.append(
                    {
                        "model_id": model_id,
                        "inference_seed": seed,
                        "condition": condition,
                        "status": "operational_failure" if excluded else "completed",
                        "inclusion_status": "excluded" if excluded else "included",
                        "scores": (
                            None
                            if excluded
                            else {
                                "counteroffer_adoption_rate": {"value": score}
                            }
                        ),
                    }
                )
    summaries = {
        row["model_id"]: row for row in _paired_transitions(contract, rows)
    }
    assert summaries["mistral32_deepinfra"] == {
        "model_id": "mistral32_deepinfra",
        "planned_pairs": 5,
        "usable_pairs": 4,
        "missing_pairs": 1,
        "neither_adopted": 3,
        "reference_only_adopted": 1,
        "reemit_only_adopted": 0,
        "both_adopted": 0,
    }


def test_published_affordance_campaign_is_sealed_complete_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publication = root / "evidence/datacenter_counteroffer_affordance_v1"
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development/affordance_publication.py"
        ).read_bytes()
    ).hexdigest()
    manifest = json.loads((publication / "publication_manifest.json").read_text())
    core = {key: value for key, value in manifest.items() if key != "artifact_sha256"}

    assert manifest["artifact_sha256"] == hashlib.sha256(
        canonical_json_bytes(core)
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


def test_published_affordance_results_preserve_mechanism_pattern() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_counteroffer_affordance_v1"
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

    assert summary["planned_cells"] == 20
    assert summary["completed_cells"] == 20
    assert summary["included_cells"] == 20
    assert summary["operational_failure_cells"] == 0
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["initial_provider_requests_match_within_all_pairs"] is True
    assert summary["assignment_level_usable_pairs"] == 10
    assert summary["counteroffer_exposed_cells"] == 20
    assert summary["exposure_qualified_pairs"] == 10
    assert summary["paired_transition_counts_published"] == {
        "both_adopted": 5,
        "neither_adopted": 1,
        "reemit_only_adopted": 4,
    }
    assert summary["reported_cost_usd"] == 0.0066795844500000005
    assert summary["observed_reported_cost_usd"] == summary["reported_cost_usd"]
    assert summary["observed_cost_qualifier"] == "exact"
    assert summary["winner_claim_allowed"] is False
    assert summary["population_generalization_allowed"] is False
    assert summary["population_causal_effect_allowed"] is False

    assert len(trajectories) == 20
    assert len(receipts) == 20
    assert all(row["status"] == "completed" for row in trajectories)
    assert all(row["inclusion_status"] == "included" for row in trajectories)
    assert all(row["route_verified"] is True for row in trajectories)
    assert all(row["replay_verified"] is True for row in trajectories)
    assert all("public_history" not in row["outcome"] for row in trajectories)
    assert all(
        row["outcome"]["counteroffer_opportunity_count"] == 1
        for row in trajectories
    )

    reference_rows = [
        row for row in trajectories if row["condition"] == "accept_by_reference"
    ]
    mistral_reference = [
        row for row in reference_rows if row["model_id"] == "mistral32_deepinfra"
    ]
    qwen_reference = [
        row for row in reference_rows if row["model_id"] == "qwen3_235b_novita"
    ]
    assert all(row["outcome"]["reference_acceptance_used"] for row in mistral_reference)
    assert all(
        row["scores"]["counteroffer_adoption_rate"]["value"] == 1.0
        for row in mistral_reference
    )
    assert all(
        not row["outcome"]["reference_acceptance_used"]
        and row["outcome"]["unchanged_second_offer"]
        and row["scores"]["counteroffer_adoption_rate"]["value"] == 0.0
        for row in qwen_reference
    )

    assert len(pairs) == 10
    assert all(row["pair_reportable"] == "True" for row in pairs)
    assert all(row["initial_provider_request_match"] == "True" for row in pairs)
    assert all(row["exposure_qualified"] == "True" for row in pairs)
    assert sum(row["transition"] == "both_adopted" for row in pairs) == 5
    assert sum(row["transition"] == "reemit_only_adopted" for row in pairs) == 4
    assert sum(row["transition"] == "neither_adopted" for row in pairs) == 1
