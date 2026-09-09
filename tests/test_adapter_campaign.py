from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import pkgutil
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

import aeread_families
from aeread.shared_runner.run.adapter_campaign import PROVIDER, run_adapter_canary
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.tau3_retail.harness import Tau3RetailJsonHarness
from aeread_families.tau3_retail.live import (
    ASSISTANT_PROMPT,
    ASSISTANT_PROMPT_ID,
    PROVIDER as TAU3_PROVIDER,
    _profile as tau3_profile,
    assistant_output_schema,
)


class AdmittedClient:
    def __init__(self):
        self.limits = []

    async def complete(self, request):
        self.limits.append(request.max_output_tokens)
        return SimpleNamespace(
            response_id="fixture-response",
            output_text=json.dumps({"status": "ok"}),
            cost_usd=0.001,
            resolved_model="glm-5p2",
            finish_reason="stop",
            input_tokens=20,
            cached_input_tokens=0,
            output_tokens=5,
            raw_response={
                "id": "fixture-response",
                "usage": {
                    "prompt_tokens": 20,
                    "prompt_tokens_details": {"cached_tokens": 0},
                    "completion_tokens": 5,
                    "cost": 0.001,
                },
            },
        )


class RejectedClient:
    async def complete(self, request):
        raise ProviderFailure(
            "provider_rejected",
            "SECRET PROVIDER PAYLOAD",
            retryable=False,
            status_code=403,
        )


class TruncatedClient(AdmittedClient):
    async def complete(self, request):
        result = await super().complete(request)
        result.finish_reason = "length"
        return result


def _tau3_retail_live_contract() -> None:
    profile = tau3_profile(
        seat="assistant",
        prompt_id=ASSISTANT_PROMPT_ID,
        prompt=ASSISTANT_PROMPT,
        output_schema=assistant_output_schema(),
        tools=("get_order_details",),
        seed=300,
        max_output_tokens=900,
        max_cost_usd=0.03,
    )
    decoded = Tau3RetailJsonHarness._decode(
        '{"kind":"reply","text":"Order checked.","calls":[]}'
    )
    assert TAU3_PROVIDER == PROVIDER == "arena"
    assert profile.model.provider == PROVIDER
    assert profile.harness.id == Tau3RetailJsonHarness.id
    assert decoded == {"kind": "reply", "text": "Order checked.", "calls": []}


# Every later PR that adds an Arena-backed family live module must add one
# provider-free behavioral callback here in the same commit.
ARENA_LIVE_CONTRACTS: dict[str, Callable[[], None]] = {
    "aeread_families.tau3_retail.live": _tau3_retail_live_contract,
}


def _discovered_arena_live_modules() -> set[str]:
    discovered = set()
    for package in pkgutil.iter_modules(aeread_families.__path__):
        module_name = f"aeread_families.{package.name}.live"
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
        if getattr(module, "PROVIDER", None) == PROVIDER:
            discovered.add(module_name)
    return discovered


def test_every_arena_live_module_has_a_provider_free_contract() -> None:
    assert _discovered_arena_live_modules() == set(ARENA_LIVE_CONTRACTS)
    for contract in ARENA_LIVE_CONTRACTS.values():
        contract()


def test_adapter_canary_is_hashed_and_resumable(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    client = AdmittedClient()
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048, 4096, 8192),
            total_max_cost_usd=0.01,
            require_reported_accounting=True,
            client=client,
        )
    )
    second = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048, 4096, 8192),
            total_max_cost_usd=0.01,
            require_reported_accounting=True,
            client=RejectedClient(),
        )
    )
    assert first == second
    assert first["status"] == "admitted"
    assert first["scored"] is False
    assert first["requested_limits"] == [2048, 4096, 8192]
    assert [probe["max_output_tokens"] for probe in first["probes"]] == [
        2048,
        4096,
        8192,
    ]
    assert first["cumulative_cost_usd"] == 0.003
    assert first["cost_usd"] == first["cumulative_cost_usd"]
    assert client.limits == [2048, 4096, 8192]
    assert first["record_sha256"]


def test_adapter_canary_rejects_checkpoint_input_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048, 4096, 8192),
            client=AdmittedClient(),
        )
    )
    with pytest.raises(ValueError, match="canary checkpoint input mismatch"):
        asyncio.run(
            run_adapter_canary(
                family_id="different_family",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=RejectedClient(),
            )
        )


def test_adapter_canary_rejects_a_tampered_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture", checkpoint_path=path, client=AdmittedClient()
        )
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    record["model"] = "tampered-model"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="canary checkpoint digest mismatch"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                client=RejectedClient(),
            )
        )


def test_adapter_canary_rejection_is_sanitized(tmp_path: Path) -> None:
    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "rejected.json",
            client=RejectedClient(),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_type"] == "ProviderFailure"
    assert record["failure_condition"] == "provider_rejected"
    assert b"SECRET" not in canonical_json_bytes(record)


def test_adapter_canary_enforces_one_aggregate_cost_cap(tmp_path: Path) -> None:
    client = AdmittedClient()
    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "over_budget.json",
            max_output_tokens=(2048, 4096, 8192),
            total_max_cost_usd=0.002,
            client=client,
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "cost_budget_exceeded"
    assert record["cumulative_cost_usd"] == 0.002
    assert client.limits == [2048, 4096]


def test_adapter_canary_rejects_parseable_truncated_content(tmp_path: Path) -> None:
    client = TruncatedClient()
    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "truncated.json",
            max_output_tokens=(2048, 4096),
            client=client,
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "length"
    assert client.limits == [2048]


def test_adapter_canary_requires_reported_accounting_when_requested(
    tmp_path: Path,
) -> None:
    class MissingAccountingClient(AdmittedClient):
        async def complete(self, request):
            result = await super().complete(request)
            result.cost_usd = None
            return result

    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "missing_accounting.json",
            max_output_tokens=(2048,),
            require_reported_accounting=True,
            client=MissingAccountingClient(),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "accounting_unavailable"


@pytest.mark.parametrize(
    "usage",
    (
        {},
        {"prompt_tokens": True, "completion_tokens": 5, "cost": 0.001},
        {"prompt_tokens": -1, "completion_tokens": 5, "cost": 0.001},
        {"prompt_tokens": 21, "completion_tokens": 5, "cost": 0.001},
        {"prompt_tokens": 20, "completion_tokens": 5, "cost": float("nan")},
    ),
)
def test_adapter_canary_rejects_unproven_raw_accounting(
    tmp_path: Path, usage: dict[str, object]
) -> None:
    class InvalidRawAccountingClient(AdmittedClient):
        async def complete(self, request):
            result = await super().complete(request)
            result.raw_response = {"id": result.response_id, "usage": usage}
            return result

    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "invalid_raw_accounting.json",
            max_output_tokens=(2048,),
            require_reported_accounting=True,
            client=InvalidRawAccountingClient(),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "accounting_unavailable"
