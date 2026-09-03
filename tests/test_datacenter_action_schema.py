from __future__ import annotations

import asyncio
import csv
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread_families.datacenter_development.action_schema_campaign import (
    _paired_transitions,
    build_design,
    load_contract,
)
from aeread_families.datacenter_development.action_schema_environment import (
    CONDITIONS,
    DEDICATED_ACTION_SCHEMA_ID,
    DEDICATED_PHASE_ID,
    CounterofferActionSchemaPlugin,
)
from aeread_families.datacenter_development.action_schema_runner import (
    build_action_schema_setup,
    finalize_action_schema_execution,
    load_action_schema_case,
    replay_action_schema_receipt,
    run_action_schema_offline,
)
from aeread_families.datacenter_development.action_schema_campaign_v2 import (
    build_design as build_design_v2,
    load_contract as load_contract_v2,
)
from aeread_families.datacenter_development.action_schema_runner_v2 import (
    DEVELOPER_PROMPT as DEVELOPER_PROMPT_V2,
    build_action_schema_setup_v2,
    finalize_action_schema_execution_v2,
    replay_action_schema_receipt_v2,
    run_action_schema_offline_v2,
)
from aeread_families.datacenter_development.action_schema_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.datacenter_development.objective_campaign import _route


def test_action_schema_cases_are_hash_pinned_and_differ_only_by_condition() -> None:
    payloads = {}
    for condition in CONDITIONS:
        case = load_action_schema_case(condition)
        assert case.content_sha256 == case_content_sha256(case)
        assert case.payload["schema_condition"] == condition
        payloads[condition] = {
            key: value
            for key, value in case.payload.items()
            if key != "schema_condition"
        }
    assert payloads["shared_offer_schema"] == payloads["dedicated_accept_schema"]


def test_action_schema_initial_observations_and_profiles_are_identical() -> None:
    plugin = CounterofferActionSchemaPlugin()
    observations = []
    for condition in CONDITIONS:
        family_case = plugin.validate_payload(load_action_schema_case(condition).payload)
        state = plugin.initial_state(family_case, run=None)
        phase = plugin.phases(family_case)[0]
        observation = plugin.observe(family_case, state, "developer", phase)
        observations.append(observation)
        assert "schema_condition" not in repr(observation)
        assert "counteroffer_resolution" not in observation
    assert canonical_json_bytes(observations[0]) == canonical_json_bytes(
        observations[1]
    )

    contract = load_contract()
    route = _route(contract["models"]["mistral32_deepinfra"])
    setups = [
        build_action_schema_setup(condition, route=route, seed=312601)
        for condition in CONDITIONS
    ]
    profiles = []
    for setup in setups:
        developer_id = setup.plan.cells[0].profile_by_seat["developer"]
        profiles.append(
            next(p for p in setup.plan.agent_profiles if p.profile_id == developer_id)
        )
    assert canonical_json_bytes(profiles[0]) == canonical_json_bytes(profiles[1])
    schemas = profiles[0].harness.config["output_schema_by_action_schema"]
    assert DEDICATED_ACTION_SCHEMA_ID in schemas
    assert schemas[DEDICATED_ACTION_SCHEMA_ID]["required"] == (
        "decision",
        "offer_id",
    )


def test_action_schema_phase_graph_declares_both_post_counter_paths() -> None:
    plugin = CounterofferActionSchemaPlugin()
    family_case = plugin.validate_payload(
        load_action_schema_case("dedicated_accept_schema").payload
    )
    phases = {phase.phase_id: phase for phase in plugin.phases(family_case)}

    assert DEDICATED_PHASE_ID in phases
    assert phases[DEDICATED_PHASE_ID].action_schema_by_role["developer"] == (
        DEDICATED_ACTION_SCHEMA_ID
    )
    assert DEDICATED_PHASE_ID in phases["land_landowner_response"].next_phases
    assert phases[DEDICATED_PHASE_ID].next_phases == ("land_developer_commit",)


def test_action_schema_provider_free_paths_score_one_and_replay(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        for condition in CONDITIONS:
            root = tmp_path / condition
            setup, execution = await run_action_schema_offline(
                condition, evidence_root=root
            )
            receipt = finalize_action_schema_execution(
                setup=setup, execution=execution
            )
            replayed = replay_action_schema_receipt(
                setup=setup, receipt=receipt, evidence_root=root
            )
            outcome = execution.episode_result.outcome
            primary = next(
                score.primary.value
                for score in receipt.scores
                if score.leaf.leaf_id == "counteroffer_adoption_rate"
            )
            assert primary == 1.0
            assert outcome["schema_condition"] == condition
            assert outcome["counteroffer_opportunity_count"] == 1
            assert outcome["reference_acceptance_count"] == 1
            assert outcome["prefix_completed"] is True
            assert outcome["exact_package_integrity"] is True
            assert replayed == receipt

    asyncio.run(run())


def test_action_schema_campaign_is_paired_bounded_and_noninferential() -> None:
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


def test_action_schema_pair_summary_keeps_operational_missingness() -> None:
    contract = load_contract()
    rows = []
    for model_id in contract["models"]:
        for seed in contract["inference_seeds"]:
            for condition in CONDITIONS:
                excluded = (
                    model_id == "mistral32_deepinfra"
                    and seed == 312602
                    and condition == "dedicated_accept_schema"
                )
                score = float(
                    condition == "dedicated_accept_schema" and seed == 312601
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
        "dedicated_only_adopted": 1,
        "shared_only_adopted": 0,
        "both_adopted": 0,
    }


def test_action_schema_v2_prompt_pins_the_opening_action_fields() -> None:
    assert 'decision: "offer"' in DEVELOPER_PROMPT_V2
    assert "offer_id: null" in DEVELOPER_PROMPT_V2
    assert "exact copy of starter_offer_terms" in DEVELOPER_PROMPT_V2


def test_action_schema_v2_conditions_keep_identical_live_profiles() -> None:
    contract = load_contract_v2()
    route = _route(contract["models"]["qwen3_235b_novita"])
    setups = [
        build_action_schema_setup_v2(condition, route=route, seed=312701)
        for condition in CONDITIONS
    ]
    profiles = []
    for setup in setups:
        developer_id = setup.plan.cells[0].profile_by_seat["developer"]
        profiles.append(
            next(p for p in setup.plan.agent_profiles if p.profile_id == developer_id)
        )
    assert canonical_json_bytes(profiles[0]) == canonical_json_bytes(profiles[1])


def test_action_schema_v2_provider_free_paths_score_one_and_replay(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        for condition in CONDITIONS:
            root = tmp_path / condition
            setup, execution = await run_action_schema_offline_v2(
                condition, evidence_root=root
            )
            receipt = finalize_action_schema_execution_v2(
                setup=setup, execution=execution
            )
            replayed = replay_action_schema_receipt_v2(
                setup=setup, receipt=receipt, evidence_root=root
            )
            outcome = execution.episode_result.outcome
            assert outcome["counteroffer_adoption_rate"] == 1.0
            assert outcome["reference_acceptance_count"] == 1
            assert replayed == receipt

    asyncio.run(run())


def test_action_schema_v2_is_a_fresh_full_panel() -> None:
    contract = load_contract_v2()
    design = build_design_v2(contract)

    assert contract["inference_seeds"] == [312701, 312702, 312703, 312704, 312705]
    assert design["planned_cells"] == 20
    assert design["planned_pair_count"] == 10
    assert design["worst_case_declared_cost_usd"] == 0.6
    assert design["predecessor_campaign_id"] == (
        "datacenter_counteroffer_action_schema_v1"
    )
    assert design["instrument_change"] == (
        "explicit_field_by_field_opening_action_contract"
    )


def test_published_action_schema_campaigns_are_sealed_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development/"
            "action_schema_publication.py"
        ).read_bytes()
    ).hexdigest()
    helper_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development/"
            "affordance_publication.py"
        ).read_bytes()
    ).hexdigest()

    for version in ("v1", "v2"):
        publication = (
            root / f"evidence/datacenter_counteroffer_action_schema_{version}"
        )
        manifest = json.loads(
            (publication / "publication_manifest.json").read_text()
        )
        core = {
            key: value
            for key, value in manifest.items()
            if key != "artifact_sha256"
        }

        assert manifest["artifact_sha256"] == hashlib.sha256(
            canonical_json_bytes(core)
        ).hexdigest()
        assert manifest["publisher_implementation_sha256"] == publisher_hash
        assert manifest["publisher_helper_sha256"] == helper_hash
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


def test_published_action_schema_v1_preserves_instrumentation_failure() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_counteroffer_action_schema_v1"
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
    assert summary["completed_cells"] == 19
    assert summary["included_cells"] == 19
    assert summary["operational_failure_cells"] == 1
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["paired_initial_request_matches"] == 10
    assert summary["assignment_level_usable_pairs"] == 9
    assert summary["counteroffer_exposed_cells"] == 2
    assert summary["exposure_qualified_pairs"] == 0
    assert summary["opening_invalid_action_cells"] == 17
    assert summary["opening_non_null_offer_id_cells"] == 17
    assert summary["opening_null_terms_cells"] == 9
    assert summary["opening_object_terms_cells"] == 8
    assert summary["paired_transition_counts_published"] == {
        "dedicated_only_adopted": 1,
        "missing_pair": 1,
        "neither_adopted": 7,
        "shared_only_adopted": 1,
    }
    assert summary["exposure_qualified_transition_counts"] == {}
    assert summary["observed_reported_cost_usd"] == 0.00241979265
    assert summary["observed_cost_qualifier"] == "lower_bound"
    assert summary["winner_claim_allowed"] is False
    assert summary["population_generalization_allowed"] is False
    assert summary["population_causal_effect_allowed"] is False

    assert len(trajectories) == 20
    assert len(receipts) == 20
    assert sum(row["inclusion_status"] == "included" for row in trajectories) == 19
    assert sum(row["inclusion_status"] == "excluded" for row in trajectories) == 1
    assert all(
        row["route_verified"] is True
        for row in trajectories
        if row["status"] == "completed"
    )
    assert all(
        "public_history" not in row["outcome"]
        for row in trajectories
        if row["outcome"] is not None
    )
    opening_failures = [
        row
        for row in trajectories
        if row["outcome"] is not None
        and row["outcome"]["termination_reason"] == "invalid_action"
        and row["outcome"]["public_history_row_count"] == 0
    ]
    assert len(opening_failures) == 17
    assert all(
        row["first_action_shape"]["offer_id_state"] == "string"
        for row in opening_failures
    )
    assert {
        row["first_action_shape"]["terms_state"] for row in opening_failures
    } == {"null", "object"}

    assert len(pairs) == 10
    assert sum(row["pair_reportable"] == "True" for row in pairs) == 9
    assert all(row["initial_provider_request_match"] == "True" for row in pairs)
    assert all(row["exposure_qualified"] == "False" for row in pairs)


def test_published_action_schema_v2_preserves_qualified_null_result() -> None:
    publication = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_counteroffer_action_schema_v2"
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
    assert summary["completed_cells"] == 14
    assert summary["included_cells"] == 14
    assert summary["operational_failure_cells"] == 6
    assert summary["all_receipts_audited"] is True
    assert summary["all_completed_routes_verified"] is True
    assert summary["paired_initial_request_matches"] == 10
    assert summary["assignment_level_usable_pairs"] == 6
    assert summary["counteroffer_exposed_cells"] == 14
    assert summary["exposure_qualified_pairs"] == 6
    assert summary["opening_invalid_action_cells"] == 0
    assert summary["paired_transition_counts_published"] == {
        "both_adopted": 6,
        "missing_pair": 4,
    }
    assert summary["exposure_qualified_transition_counts"] == {
        "both_adopted": 6,
    }
    assert summary["observed_reported_cost_usd"] == 0.00539515845
    assert summary["observed_cost_qualifier"] == "lower_bound"
    assert summary["winner_claim_allowed"] is False
    assert summary["population_generalization_allowed"] is False
    assert summary["population_causal_effect_allowed"] is False

    assert len(trajectories) == 20
    assert len(receipts) == 20
    included = [
        row for row in trajectories if row["inclusion_status"] == "included"
    ]
    excluded = [
        row for row in trajectories if row["inclusion_status"] == "excluded"
    ]
    assert len(included) == 14
    assert len(excluded) == 6
    assert all(row["failure"]["failure_condition"] == "rate_limit" for row in excluded)
    assert all(row["route_verified"] is True for row in included)
    assert all(row["replay_verified"] is True for row in included)
    assert all(
        "public_history" not in row["outcome"]
        and row["outcome"]["counteroffer_opportunity_count"] == 1
        and row["outcome"]["reference_acceptance_used"] is True
        and row["outcome"]["exact_package_integrity"] is True
        and row["scores"]["counteroffer_adoption_rate"]["value"] == 1.0
        for row in included
    )

    assert len(pairs) == 10
    assert sum(row["pair_reportable"] == "True" for row in pairs) == 6
    assert all(row["initial_provider_request_match"] == "True" for row in pairs)
    qualified = [row for row in pairs if row["exposure_qualified"] == "True"]
    assert len(qualified) == 6
    assert all(row["transition"] == "both_adopted" for row in qualified)
    assert sum(row["transition"] == "missing_pair" for row in pairs) == 4
