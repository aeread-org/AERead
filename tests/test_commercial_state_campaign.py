from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from aeread.shared_runner.execution import ProviderFailure, ProviderResult
from aeread.shared_runner.resolver import canonical_json_bytes
from aeread_families.commercial_state_calibration.campaign import (
    DEFAULT_CONTRACT_PATH,
    design_contract_artifact,
    execute_campaign,
    load_contract,
    run_live_stage,
    run_profile_admission,
)
from aeread_families.commercial_state_calibration.cases import load_cases
from aeread_families.commercial_state_calibration.publication import (
    publish_campaign_evidence,
)


def _strong_by_case_id() -> dict[str, dict[str, Any]]:
    responses: dict[str, dict[str, Any]] = {}
    for case in load_cases():
        gold = case.payload["oracle"]["gold"]
        responses[case.case_id] = {
            "case_id": case.case_id,
            "states": dict(gold["states"]),
            "amounts": dict(gold["amounts"]),
            "actions": list(gold["required_actions"]),
            "claims": list(gold["required_claims"]),
            "evidence_ids": list(gold["required_evidence_ids"]),
            "external_actions_attempted": [],
        }
    return responses


def _endpoint_loader(contract: Mapping[str, Any]):
    by_requested = {
        model["requested_model"]: model for model in contract["models"].values()
    }

    def load(model_name: str) -> Mapping[str, Any]:
        model = by_requested[model_name]
        return {
            "endpoints": [
                {
                    "name": f"test/{model['canonical_model']}",
                    "provider_name": model["provider"],
                    "quantization": model["quantization"],
                    "pricing": {
                        "prompt": str(model["pricing"]["input_per_million"] / 1_000_000),
                        "completion": str(
                            model["pricing"]["output_per_million"] / 1_000_000
                        ),
                    },
                    "supported_parameters": [
                        "max_tokens",
                        "response_format",
                        "seed",
                        "structured_outputs",
                    ],
                }
            ]
        }

    return load


class StrongCampaignProvider:
    def __init__(self, *, fail_model: str | None = None) -> None:
        self.responses = _strong_by_case_id()
        self.fail_model = fail_model
        self.calls = 0

    async def complete(self, request: Any) -> ProviderResult:
        self.calls += 1
        if request.model == self.fail_model:
            raise ProviderFailure(
                "provider_5xx", "synthetic failure", retryable=True, status_code=503
            )
        envelope = json.loads(request.input_text)
        case_id = envelope["observation"]["case_id"]
        return ProviderResult(
            response_id=f"response_{self.calls}",
            requested_model=request.model,
            resolved_model=request.revision,
            output_text=canonical_json_bytes(self.responses[case_id]).decode("utf-8"),
            finish_reason="stop",
            input_tokens=100,
            cached_input_tokens=0,
            output_tokens=50,
            cost_usd=0.00001,
            raw_response={"provider": request.provider_metadata["route_provider"]},
        )


def test_contract_resolves_complete_paired_matrix() -> None:
    contract = load_contract(DEFAULT_CONTRACT_PATH)
    design = design_contract_artifact(contract)

    assert design["status"] == "passed"
    assert design["stage_plan_counts"] == {
        "full_trajectory": 4,
        "variance_pilot": 108,
    }
    assert design["independent_cluster_count"] == 1
    assert design["inferential_model_ranking_allowed"] is False
    assert design["paired_by"] == ["case_slug", "inference_seed"]
    assert len(design["plans"]["variance_pilot"]) == 108


def test_contract_rejects_route_drift(tmp_path: Path) -> None:
    value = json.loads(DEFAULT_CONTRACT_PATH.read_bytes())
    value["models"]["glm53_flash"]["canonical_model"] = "drifted"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="route or price pin drifted"):
        load_contract(path)


def test_provider_free_gate_covers_all_cases_and_failure_classes(tmp_path: Path) -> None:
    result = asyncio.run(
        execute_campaign(
            contract_path=DEFAULT_CONTRACT_PATH,
            output_root=tmp_path / "campaign",
            through="provider_free_validation",
        )
    )

    assert result["gate_summaries"]["design_contract"]["status"] == "passed"
    assert result["gate_summaries"]["provider_free_validation"]["status"] == "passed"
    summary = json.loads(
        (
            tmp_path
            / "campaign"
            / "provider_free_validation"
            / "summary.json"
        ).read_bytes()
    )
    assert summary["case_count"] == 9
    assert summary["check_count"] == 12
    assert summary["replay_verified"] is True
    assert summary["provider_cost_usd"] == 0.0
    assert {row["check_id"] for row in summary["checks"]} >= {
        "boundary.valid_but_poor",
        "boundary.hard_gate_failed",
        "boundary.malformed",
    }


def test_profile_admission_requires_exact_route_and_schema_support() -> None:
    contract = load_contract(DEFAULT_CONTRACT_PATH)
    artifact = asyncio.run(
        run_profile_admission(contract, endpoint_loader=_endpoint_loader(contract))
    )

    assert artifact["status"] == "passed"
    assert artifact["provider_cost_usd"] == 0.0
    assert artifact["live_model_output_observed"] is False
    assert {row["model_id"] for row in artifact["results"]} == set(
        contract["models"]
    )
    assert all(row["eligible_endpoint_count"] == 1 for row in artifact["results"])


def test_fake_campaign_runs_all_cells_exports_facts_and_resumes(tmp_path: Path) -> None:
    contract = load_contract(DEFAULT_CONTRACT_PATH)
    provider = StrongCampaignProvider()
    output_root = tmp_path / "campaign"
    first = asyncio.run(
        execute_campaign(
            contract_path=DEFAULT_CONTRACT_PATH,
            output_root=output_root,
            through="variance_pilot",
            provider_factory=lambda: provider,
            endpoint_loader=_endpoint_loader(contract),
        )
    )

    assert all(
        value["status"] == "passed" for value in first["gate_summaries"].values()
    )
    assert provider.calls == 112
    full = json.loads((output_root / "full_trajectory" / "summary.json").read_bytes())
    pilot = json.loads((output_root / "variance_pilot" / "summary.json").read_bytes())
    assert full["planned_cells"] == full["completed_cells"] == 4
    assert pilot["planned_cells"] == pilot["completed_cells"] == 108
    assert pilot["independent_cluster_count"] == 1
    assert pilot["inferential_model_ranking_allowed"] is False
    assert len(pilot["model_summaries"]) == 4
    assert len(pilot["pairwise_contrasts"]) == 6
    assert all(row["complete_pair_count"] == 27 for row in pilot["pairwise_contrasts"])
    assert all(row["confidence_interval"] is None for row in pilot["pairwise_contrasts"])

    manifest = json.loads(
        (output_root / "variance_pilot" / "analysis" / "fact_manifest.json").read_bytes()
    )
    assert manifest["tables"]["profiles"]["row_count"] == 108
    assert manifest["tables"]["model_features"]["row_count"] == 108 * 5
    assert manifest["tables"]["benchmark_results"]["row_count"] == 108 * 9

    publication_root = tmp_path / "publication"
    publication = publish_campaign_evidence(
        campaign_root=output_root,
        publication_root=publication_root,
    )
    assert publication["source_stage"] == "variance_pilot"
    assert publication["sanitization"] == {
        "raw_provider_responses_included": False,
        "full_prompts_included": False,
        "model_reasoning_included": False,
        "complete_receipts_included": False,
        "failure_messages_included": False,
    }
    transcript_rows = [
        json.loads(line)
        for line in (
            publication_root / "trajectories" / "sanitized.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert len(transcript_rows) == 108
    assert all(row["parsed_output"] for row in transcript_rows)
    public_bytes = b"".join(
        path.read_bytes() for path in publication_root.rglob("*") if path.is_file()
    ).lower()
    assert b"raw_response" not in public_bytes
    assert b'"failure_message":' not in public_bytes
    assert b"user_id" not in public_bytes

    repeated_publication = publish_campaign_evidence(
        campaign_root=output_root,
        publication_root=publication_root,
    )
    assert repeated_publication == publication

    second = asyncio.run(
        execute_campaign(
            contract_path=DEFAULT_CONTRACT_PATH,
            output_root=output_root,
            through="variance_pilot",
            provider_factory=lambda: provider,
            endpoint_loader=_endpoint_loader(contract),
        )
    )
    assert provider.calls == 112
    assert all(
        value["status"] == "already_passed"
        for value in second["gate_summaries"].values()
    )


def test_full_trajectory_failure_is_typed_and_blocks_gate(tmp_path: Path) -> None:
    contract = load_contract(DEFAULT_CONTRACT_PATH)
    failed_model = contract["models"]["mistral_small4"]["requested_model"]
    provider = StrongCampaignProvider(fail_model=failed_model)
    output_root = tmp_path / "campaign"

    with pytest.raises(RuntimeError, match="full_trajectory failed"):
        asyncio.run(
            run_live_stage(
                contract,
                stage="full_trajectory",
                output_root=output_root,
                provider_factory=lambda: provider,
            )
        )

    summary = json.loads((output_root / "full_trajectory" / "summary.json").read_bytes())
    assert summary["status"] == "failed"
    assert summary["completed_cells"] == 3
    assert summary["operational_failure_cells"] == 1
    failed = [row for row in summary["rows"] if row["status"] == "operational_failure"]
    assert len(failed) == 1
    assert failed[0]["failure_condition"] == "provider_5xx"
    assert failed[0]["inclusion_status"] == "excluded"
    assert failed[0]["replay_verified"] is True

    publication_root = tmp_path / "failed_publication"
    publish_campaign_evidence(
        campaign_root=output_root,
        publication_root=publication_root,
    )
    public_summary = json.loads(
        (publication_root / "reports" / "summary.json").read_bytes()
    )
    assert public_summary["status"] == "failed"
    assert public_summary["provider_cost_complete"] is False
    assert public_summary["cost_qualifier"] == "lower_bound"
    assert public_summary["failure_conditions"] == {"provider_5xx": 1}
    public_bytes = b"".join(
        path.read_bytes() for path in publication_root.rglob("*") if path.is_file()
    )
    assert b"synthetic failure" not in public_bytes
