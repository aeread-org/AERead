from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aeread.shared_runner.run.adapter_campaign import run_adapter_canary
from aeread.shared_runner.task.execution import ProviderFailure


class _Client:
    def __init__(
        self,
        *,
        output_text: str = '{"status":"ok"}',
        cost_usd: float = 0.001,
        finish_reason: str = "stop",
        error: Exception | None = None,
    ) -> None:
        self.output_text = output_text
        self.cost_usd = cost_usd
        self.finish_reason = finish_reason
        self.error = error
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            output_text=self.output_text,
            cost_usd=self.cost_usd,
            resolved_model="glm-5p2",
            finish_reason=self.finish_reason,
            input_tokens=20,
            cached_input_tokens=0,
            output_tokens=5,
        )


def test_adapter_canary_is_hashed_and_resumable(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    client = _Client()
    first = asyncio.run(run_adapter_canary(family_id="steer", checkpoint_path=path, client=client))
    second = asyncio.run(
        run_adapter_canary(family_id="steer", checkpoint_path=path, client=_Client())
    )
    assert first == second
    assert first["status"] == "admitted"
    assert first["scored"] is False
    assert first["record_sha256"]
    assert client.calls == 1


def test_adapter_canary_rejects_a_truncated_json_response(tmp_path: Path) -> None:
    path = tmp_path / "truncated.json"
    record = asyncio.run(
        run_adapter_canary(
            family_id="steer",
            checkpoint_path=path,
            client=_Client(finish_reason="length"),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "truncated_response"


def test_adapter_canary_does_not_resume_a_checkpoint_for_another_family(
    tmp_path: Path,
) -> None:
    path = tmp_path / "family-bound.json"
    asyncio.run(
        run_adapter_canary(family_id="steer", checkpoint_path=path, client=_Client())
    )
    other_client = _Client()
    with pytest.raises(ValueError, match="different family"):
        asyncio.run(
            run_adapter_canary(
                family_id="alympics.wac",
                checkpoint_path=path,
                client=other_client,
            )
        )
    assert other_client.calls == 0


def test_adapter_canary_sanitizes_provider_failure_fields(tmp_path: Path) -> None:
    raw = "<<RAW PROVIDER BODY: this could be a payload>>"
    path = tmp_path / "provider-failure.json"
    record = asyncio.run(
        run_adapter_canary(
            family_id="steer",
            checkpoint_path=path,
            client=_Client(
                error=ProviderFailure(raw, raw, retryable=False),
            ),
        )
    )
    assert record["failure_type"] == "provider_error"
    assert record["failure_condition"] == "provider_error"
    assert raw not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("cost", [-5.0, float("nan"), float("inf")])
def test_adapter_canary_rejects_non_finite_or_negative_costs(
    tmp_path: Path, cost: float
) -> None:
    path = tmp_path / "invalid-cost.json"
    record = asyncio.run(
        run_adapter_canary(
            family_id="steer",
            checkpoint_path=path,
            client=_Client(cost_usd=cost),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "invalid_provider_cost"
    assert record["cost_usd"] == 0.0


def test_adapter_canary_does_not_checkpoint_unexpected_internal_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "internal-error.json"
    with pytest.raises(AttributeError, match="internal bug"):
        asyncio.run(
            run_adapter_canary(
                family_id="steer",
                checkpoint_path=path,
                client=_Client(error=AttributeError("internal bug")),
            )
        )
    assert not path.exists()
