from __future__ import annotations

import pytest

import asyncio
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    ProviderRequest,
    execute_plan_cell,
)
from aeread_families.datacenter_development.adoption_campaign import (
    build_design,
    load_contract,
)
from aeread_families.datacenter_development.adoption_environment import (
    STAGE_SEQUENCES,
    CounterofferAdoptionPlugin,
)
from aeread_families.datacenter_development.adoption_runner import (
    ForcedCounterpartyProvider,
    _providers,
    build_adoption_setup,
    finalize_adoption_execution,
    load_adoption_case,
    replay_adoption_receipt,
    run_adoption_offline,
)
from aeread_families.datacenter_development.adoption_campaign_v2 import (
    build_design as build_design_v2,
    load_contract as load_contract_v2,
)
from aeread_families.datacenter_development.adoption_environment_v2 import (
    StarterGroundedCounterofferAdoptionPlugin,
)
from aeread_families.datacenter_development.adoption_runner_v2 import (
    finalize_adoption_execution_v2,
    load_adoption_case_v2,
    replay_adoption_receipt_v2,
    run_adoption_offline_v2,
)
from aeread_families.datacenter_development.adoption_campaign_v3 import (
    build_design as build_design_v3,
    load_contract as load_contract_v3,
)
from aeread_families.datacenter_development.adoption_environment_v3 import (
    NullableProseCounterofferAdoptionPlugin,
)
from aeread_families.datacenter_development.adoption_runner_v3 import (
    finalize_adoption_execution_v3,
    load_adoption_case_v3,
    replay_adoption_receipt_v3,
    run_adoption_offline_v3,
)
from aeread_families.datacenter_development.adoption_publication import (
    PROHIBITED_PUBLIC_TEXT,
)
from aeread_families.datacenter_development.stack_runner import _scripted_result


def _request(provider: str, payload: dict) -> ProviderRequest:
    return ProviderRequest(
        provider_call_id="provider_call_test",
        provider=provider,
        base_url=None,
        model="scripted",
        revision="1.0.0",
        instructions="",
        input_text=json.dumps(payload),
        temperature=0.0,
        top_p=None,
        max_output_tokens=1,
        reasoning_effort=None,
        timeout_seconds=1.0,
        request_sha256="0" * 64,
    )


def test_adoption_cases_are_hash_pinned_nested_prefixes() -> None:
    for stage_id, sequence in STAGE_SEQUENCES.items():
        case = load_adoption_case(stage_id)
        assert case.content_sha256 == case_content_sha256(case)
        assert tuple(case.payload["required_sequence"]) == sequence
        assert case.episode.max_logical_actions == 5 * len(sequence)
        assert case.world_seed == 312101


def test_adoption_developer_observation_hides_private_policy() -> None:
    case = load_adoption_case("land_power_epc")
    plugin = CounterofferAdoptionPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]

    observation = plugin.observe(family_case, state, "developer", phase)
    serialized = repr(observation)

    assert observation["counteroffer_adoption_task"]["required_sequence"] == [
        "land",
        "power",
        "epc",
    ]
    assert "private_policy" not in serialized
    assert "policies" not in serialized
    assert "scripted_developer" not in serialized
    assert "baseline" not in serialized


def test_counterparty_forces_first_counter_even_for_exact_terms() -> None:
    case = load_adoption_case("land")
    family_case = CounterofferAdoptionPlugin().validate_payload(case.payload)
    target = family_case["policies"]["land"]["counter_terms"]
    provider = ForcedCounterpartyProvider("landowner")
    request = _request(
        "datacenter_adoption_scripted_landowner",
        {
            "phase_id": "land_landowner_response",
            "observation": {
                "latest_offer": {
                    "offer_id": "offer_test",
                    "round_index": 0,
                    "terms": target,
                },
                "private_policy": family_case["policies"]["land"],
            },
        },
    )

    result = json.loads(asyncio.run(provider.complete(request)).output_text)

    assert result["decision"] == "counter"
    assert result["offer_id"] == "offer_test"
    assert result["terms"] == target


def test_provider_free_adoption_ladder_scores_one_and_replays(tmp_path: Path) -> None:
    async def run() -> None:
        for stage_id, sequence in STAGE_SEQUENCES.items():
            evidence_root = tmp_path / stage_id
            setup, execution = await run_adoption_offline(
                stage_id, evidence_root=evidence_root
            )
            receipt = finalize_adoption_execution(setup=setup, execution=execution)
            replayed = replay_adoption_receipt(
                setup=setup, receipt=receipt, evidence_root=evidence_root
            )
            primary = next(
                score
                for score in receipt.scores
                if score.leaf.leaf_id == "counteroffer_adoption_rate"
            )
            outcome = execution.episode_result.outcome
            assert receipt.inclusion_status == "included"
            assert primary.primary.value == 1.0
            assert outcome["counteroffer_opportunity_count"] == len(sequence)
            assert outcome["counteroffer_adoption_count"] == len(sequence)
            assert outcome["exact_package_integrity"] is True
            assert replayed == receipt

    asyncio.run(run())


def test_invalid_developer_action_is_included_with_zero(tmp_path: Path) -> None:
    class MalformedDeveloper:
        async def complete(self, request: ProviderRequest):
            return _scripted_result(request, {"unexpected": True})

    async def run() -> None:
        setup = build_adoption_setup("land")
        providers = _providers(setup)
        providers["datacenter_adoption_scripted_developer"] = MalformedDeveloper()
        execution = await execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers=providers,
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
        receipt = finalize_adoption_execution(setup=setup, execution=execution)
        primary = next(
            score
            for score in receipt.scores
            if score.leaf.leaf_id == "counteroffer_adoption_rate"
        )
        assert receipt.status == "ok"
        assert receipt.inclusion_status == "included"
        assert primary.primary.value == 0.0
        assert execution.episode_result.outcome["termination_reason"] == "invalid_action"

    asyncio.run(run())


def test_adoption_campaign_is_paired_bounded_and_noninferential() -> None:
    contract = load_contract()
    design = build_design(contract)

    assert design["planned_cells"] == 18
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.54)
    assert design["worst_case_declared_cost_usd"] <= design["campaign_max_cost_usd"]
    assert design["independent_cluster_count"] == 1
    assert design["nested_stage_variants_independent"] is False
    assert contract["analysis"]["winner_claim_allowed"] is False
    assert contract["analysis"]["inferential_model_ranking_allowed"] is False
    assert contract["analysis"]["causal_depth_effect_allowed"] is False
    assert {
        (cell["stage_id"], cell["model_id"], cell["inference_seed"])
        for cell in design["cells"]
    } == {
        (stage_id, model_id, seed)
        for stage_id in STAGE_SEQUENCES
        for model_id in contract["models"]
        for seed in contract["inference_seeds"]
    }


def test_v2_cases_and_starter_terms_are_hash_pinned() -> None:
    for stage_id, sequence in STAGE_SEQUENCES.items():
        case = load_adoption_case_v2(stage_id)
        plugin = StarterGroundedCounterofferAdoptionPlugin()
        family_case = plugin.validate_payload(case.payload)
        state = plugin.initial_state(family_case, run=None)
        phase = plugin.phases(family_case)[0]
        observation = plugin.observe(family_case, state, "developer", phase)

        assert case.content_sha256 == case_content_sha256(case)
        assert case.family_version == "1.1.0"
        assert tuple(case.payload["required_sequence"]) == sequence
        assert observation["starter_offer_terms"] != family_case["policies"][
            "land"
        ]["counter_terms"]
        assert "private_policy" not in repr(observation)


def test_v2_walk_with_explanation_is_valid_not_malformed() -> None:
    case = load_adoption_case_v2("land")
    plugin = StarterGroundedCounterofferAdoptionPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]
    response = CanonicalResponse(
        text=json.dumps(
            {"decision": "walk", "message": "Decline.", "terms": None}
        ),
        finish_reason="stop",
        empty=False,
        truncated=False,
        provider_call_ids=("provider_call_test",),
        tool_invocation_ids=(),
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )

    parsed = plugin.parse_action(
        family_case, state, "developer", phase, response
    )

    assert parsed.ok is True
    assert parsed.action == {"decision": "walk"}


def test_v2_provider_free_ladder_scores_one_and_replays(tmp_path: Path) -> None:
    async def run() -> None:
        for stage_id in STAGE_SEQUENCES:
            evidence_root = tmp_path / stage_id
            setup, execution = await run_adoption_offline_v2(
                stage_id, evidence_root=evidence_root
            )
            receipt = finalize_adoption_execution_v2(
                setup=setup, execution=execution
            )
            replayed = replay_adoption_receipt_v2(
                setup=setup, receipt=receipt, evidence_root=evidence_root
            )
            primary = next(
                score
                for score in receipt.scores
                if score.leaf.leaf_id == "counteroffer_adoption_rate"
            )
            assert primary.primary.value == 1.0
            assert replayed == receipt

    asyncio.run(run())


def test_v2_campaign_is_full_panel_not_selective_retry() -> None:
    contract = load_contract_v2()
    design = build_design_v2(contract)

    assert design["planned_cells"] == 18
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.54)
    assert design["predecessor_campaign_id"] == "datacenter_counteroffer_adoption_v1"
    assert design["instrument_change"] == (
        "public_valid_nonexact_starter_terms_and_schema_aligned_walk"
    )
    assert len({cell["cell_key"] for cell in design["cells"]}) == 18


def test_v3_nullable_offer_prose_preserves_structured_terms() -> None:
    case = load_adoption_case_v3("land")
    plugin = NullableProseCounterofferAdoptionPlugin()
    family_case = plugin.validate_payload(case.payload)
    state = plugin.initial_state(family_case, run=None)
    phase = plugin.phases(family_case)[0]
    observation = plugin.observe(family_case, state, "developer", phase)
    terms = observation["starter_offer_terms"]
    response = CanonicalResponse(
        text=json.dumps(
            {"decision": "offer", "message": None, "terms": terms}
        ),
        finish_reason="stop",
        empty=False,
        truncated=False,
        provider_call_ids=("provider_call_test",),
        tool_invocation_ids=(),
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
    )

    parsed = plugin.parse_action(
        family_case, state, "developer", phase, response
    )

    assert parsed.ok is True
    assert canonical_json_bytes(parsed.action["terms"]) == canonical_json_bytes(terms)
    assert parsed.action["message"] == "Structured written offer; terms control."


def test_v3_provider_free_ladder_and_design(tmp_path: Path) -> None:
    async def run() -> None:
        for stage_id in STAGE_SEQUENCES:
            evidence_root = tmp_path / stage_id
            setup, execution = await run_adoption_offline_v3(
                stage_id, evidence_root=evidence_root
            )
            receipt = finalize_adoption_execution_v3(
                setup=setup, execution=execution
            )
            replayed = replay_adoption_receipt_v3(
                setup=setup, receipt=receipt, evidence_root=evidence_root
            )
            assert next(
                score.primary.value
                for score in receipt.scores
                if score.leaf.leaf_id == "counteroffer_adoption_rate"
            ) == 1.0
            assert replayed == receipt

    asyncio.run(run())
    contract = load_contract_v3()
    design = build_design_v3(contract)
    assert design["planned_cells"] == 18
    assert design["worst_case_declared_cost_usd"] == pytest.approx(0.54)
    assert design["predecessor_campaign_id"] == "datacenter_counteroffer_adoption_v2"
    assert design["instrument_change"] == "nullable_nonbinding_offer_prose_normalized"


def test_published_adoption_campaigns_are_sealed_and_sanitized() -> None:
    root = Path(__file__).resolve().parents[1]
    publisher_hash = hashlib.sha256(
        (
            root
            / "src/aeread_families/datacenter_development/adoption_publication.py"
        ).read_bytes()
    ).hexdigest()
    interpretations = {
        "v1": "instrumentation_preflight_initial_offer_confound",
        "v2": "instrumentation_preflight_nullable_prose_mismatch",
        "v3": "scoreable_counteroffer_adoption_diagnostic",
    }
    for version, interpretation in interpretations.items():
        publication = (
            root / "evidence" / f"datacenter_counteroffer_adoption_{version}"
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
        for relative, metadata in manifest["files"].items():
            payload = (publication / relative).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
            lowered = payload.decode("utf-8").lower()
            assert not any(
                token in lowered for token in PROHIBITED_PUBLIC_TEXT
            )
        summary = json.loads(
            (publication / "reports/summary.json").read_text()
        )
        assert summary["publication_interpretation"] == interpretation
        assert summary["all_receipts_audited"] is True
        assert len(
            (
                publication / "trajectories/sanitized.jsonl"
            ).read_text().splitlines()
        ) == 18


def test_v3_publication_records_real_counteroffer_opportunities() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "evidence/datacenter_counteroffer_adoption_v3/trajectories/sanitized.jsonl"
    )
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    included = [row for row in rows if row["inclusion_status"] == "included"]

    assert len(included) == 15
    assert all(
        row["outcome"]["counteroffer_opportunity_count"] == 1
        for row in included
    )
    assert sum(
        row["outcome"]["counteroffer_adoption_count"] for row in included
    ) == 1
    assert sum(row["outcome"]["prefix_completed"] for row in included) == 1
    assert all(
        row["outcome"]["fields_changed_between_first_and_second_land_offer"]
        in ([], ["purchase_price_cents"])
        for row in included
    )
