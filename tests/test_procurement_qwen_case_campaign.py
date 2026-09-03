from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import aeread_families.procurement_allocation.qwen_case_campaign as campaign_module
from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.procurement_allocation.case_matrix import CASE_VARIANCE_PATHS
from aeread_families.procurement_allocation.qwen_case_campaign import (
    CAMPAIGN_ID,
    HARD_TOTAL_COST_CEILING_USD,
    PAIRED_INFERENCE_SEEDS,
    QWEN_CANDIDATE,
    build_plan,
    run_admission_canary,
    run_campaign,
)
from aeread_families.procurement_allocation.runner import SequenceResponseProvider


def test_qwen_plan_freezes_matched_panel_route_and_budget() -> None:
    plan = build_plan()
    scored = plan["scored_plan"]

    assert plan["campaign_id"] == CAMPAIGN_ID
    assert plan["freeze_status"] == "frozen_before_live_execution"
    assert plan["candidate"] == {
        "candidate_id": "qwen3_30b_a3b_instruct_2507_coreweave",
        "model": "qwen/qwen3-30b-a3b-instruct-2507",
        "revision": "qwen/qwen3-30b-a3b-instruct-2507",
        "provider": "CoreWeave",
        "quantization": "bf16",
        "access_class": "open_source",
        "license_id": "Apache-2.0",
        "model_card_url": (
            "https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507"
        ),
    }
    assert scored["cases"] == [
        {
            "case_id": f"procurement_allocation_v1.dev.{path.stem}",
            "content_sha256": json.loads(path.read_text())["content_sha256"],
        }
        for path in CASE_VARIANCE_PATHS
    ]
    assert scored["inference_seeds"] == list(PAIRED_INFERENCE_SEEDS)
    assert scored["planned_trajectory_count"] == 18
    assert scored["max_parallel_cells"] == 1
    assert scored["max_new_trajectories_per_invocation"] == 6
    assert scored["max_cost_usd_per_trajectory"] == pytest.approx(0.01)
    assert scored["conservative_cost_ceiling_usd"] == pytest.approx(0.1692)
    assert plan["conservative_total_cost_ceiling_usd"] == pytest.approx(0.1792)
    assert plan["hard_total_cost_ceiling_usd"] == pytest.approx(0.19)
    assert scored["retry_policy"]["max_action_attempts"] == 3
    assert scored["retry_policy"]["retry_base_seconds"] == pytest.approx(15.0)
    assert plan["plan_sha256"] == (
        "fc7febffe7f3aa947a00c30821d7da87935c6ce12a7d39e275cf2155d3d57d02"
    )


def test_qwen_candidate_reaches_exact_request_builder(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(
        (json.dumps({"action": "defer", "reason": "route test"}),)
    )

    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "canary.json",
            provider_factory=lambda: provider,
        )
    )

    assert canary["status"] == "admitted"
    assert canary["output_contract_status"] == "valid_structured_action"
    assert canary["cost_accounting"] == "exact"
    assert provider.requests[0].model == QWEN_CANDIDATE.route.model
    assert provider.requests[0].revision == QWEN_CANDIDATE.route.revision
    assert provider.requests[0].provider_metadata["route_provider"] == "CoreWeave"
    assert provider.requests[0].provider_metadata["quantization"] == "bf16"


def test_qwen_canary_admits_nonempty_malformed_output(tmp_path: Path) -> None:
    provider = SequenceResponseProvider(('{"action":',))

    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "canary.json",
            provider_factory=lambda: provider,
        )
    )

    assert canary["status"] == "admitted"
    assert canary["output_contract_status"] == "malformed_json"
    assert canary["structured_action"] is None
    assert canary["provider_call_count"] == 1


def test_qwen_canary_retries_declared_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    async def no_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(campaign_module.asyncio, "sleep", no_wait)

    class RetryThenAdmit:
        def __init__(self) -> None:
            self.calls = 0
            self.delegate = SequenceResponseProvider(
                (json.dumps({"action": "defer", "reason": "admitted"}),)
            )

        async def complete(self, request):
            self.calls += 1
            if self.calls == 1:
                raise ProviderFailure(
                    "rate_limit", "synthetic throttle", retryable=True, status_code=429
                )
            return await self.delegate.complete(request)

    provider = RetryThenAdmit()
    canary = asyncio.run(
        run_admission_canary(
            path=tmp_path / "canary.json",
            provider_factory=lambda: provider,
        )
    )

    assert canary["status"] == "admitted"
    assert canary["provider_call_count"] == 2
    assert canary["runner_retry_count"] == 1
    assert canary["retry_condition_counts"] == {"rate_limit": 1}
    assert waits == [15.0]


def test_qwen_campaign_writes_plan_before_rejected_canary(tmp_path: Path) -> None:
    class RejectingProvider:
        async def complete(self, _request):
            raise ProviderFailure(
                "provider_rejected",
                "synthetic rejection",
                retryable=False,
                status_code=400,
            )

    root = tmp_path / "runs" / CAMPAIGN_ID / "attempt_001"
    status = asyncio.run(
        run_campaign(
            run_root=root,
            provider_factory=RejectingProvider,
            preflight_fn=lambda _candidate: pytest.fail("preflight must not run"),
        )
    )

    assert (root / "campaign_plan.json").is_file()
    assert status["canary"]["status"] == "rejected"
    assert status["summary"]["completed_trajectory_count"] == 0
    assert status["summary"]["unattempted_trajectory_count"] == 18
    assert status["summary"]["execution_qualified"] is False
    assert not (root / "scored").exists()


def test_qwen_campaign_rejects_a_lower_runtime_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="below the frozen hard total ceiling"):
        asyncio.run(
            run_campaign(
                run_root=tmp_path / "runs" / CAMPAIGN_ID / "attempt_001",
                max_spend_usd=HARD_TOTAL_COST_CEILING_USD - 0.01,
            )
        )
