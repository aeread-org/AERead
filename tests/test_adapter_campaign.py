from __future__ import annotations

import asyncio
import errno
import importlib
import importlib.util
import json
import os
import pkgutil
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

import aeread.shared_runner.run.adapter_campaign as adapter_campaign
import aeread_families
from aeread.shared_runner.run.adapter_campaign import (
    PROVIDER,
    _digest,
    _write_once,
    run_adapter_canary,
)
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
    assert first["record_sha256"] == _digest(
        {key: value for key, value in first.items() if key != "record_sha256"}
    )


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
    # A closed vocabulary label, never the raised exception's class name:
    # persisting the class name would leak an implementation detail into a
    # public checkpoint and drift the moment the exception is renamed.
    assert record["failure_type"] == "provider_failure"
    assert record["failure_condition"] == "provider_rejected"
    assert b"SECRET" not in canonical_json_bytes(record)


def test_adapter_canary_provider_failure_records_unknown_cost(tmp_path: Path) -> None:
    # A billed call that raised before returning any accounting never
    # proves it cost nothing: the aggregate cost is recorded as unknown,
    # not coerced to 0.0, and the probe is terminal.
    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "provider_failure_cost.json",
            client=RejectedClient(),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_type"] == "provider_failure"
    assert record["cost_usd"] is None
    assert record["cost_accounting_state"] == "unknown"
    assert record["probes"] == []


def test_adapter_canary_known_cost_path_reports_known_accounting(tmp_path: Path) -> None:
    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "known_cost.json",
            client=AdmittedClient(),
        )
    )
    assert record["status"] == "admitted"
    assert record["cost_accounting_state"] == "known"
    assert record["cost_usd"] == record["cumulative_cost_usd"]


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


class OverBudgetClient(AdmittedClient):
    async def complete(self, request):
        result = await super().complete(request)
        result.cost_usd = 0.10
        return result


def test_adapter_canary_rejects_when_reported_cost_exceeds_remaining_budget(
    tmp_path: Path,
) -> None:
    # No pre-check can catch this: the probe was allowed to start because
    # remaining budget was positive, but the response it returned reports a
    # cost that alone blows through the aggregate ceiling. It is rejected
    # after being charged, never silently admitted.
    client = OverBudgetClient()
    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "cost_ceiling.json",
            max_output_tokens=(2048,),
            total_max_cost_usd=0.01,
            client=client,
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "cost_ceiling_exceeded"
    assert record["cumulative_cost_usd"] == 0.10
    assert client.limits == [2048]


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


# --- write-once atomicity and racing-safety (checkpoint destination) -------


def test_write_once_checks_symlinks_at_open_time_not_before(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.json"
    target.write_text("not a checkpoint", encoding="utf-8")
    path = tmp_path / "canary.json"
    path.symlink_to(target)
    with pytest.raises(ValueError, match="must not be a symlink"):
        _write_once(path, {"status": "ok"})
    # The symlink's target is untouched: a rejected publish never follows
    # the link and writes through it.
    assert target.read_text(encoding="utf-8") == "not a checkpoint"


def test_write_once_leaves_no_final_or_temp_file_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A write that dies partway through must not leave a partial final
    # file, and must not leave a stray temp file behind either: the
    # publish step (``os.link``) is never reached, and the temp file is
    # removed by the outer ``finally`` regardless of where the failure
    # happened.
    path = tmp_path / "canary.json"

    def failing_write(fd, data):
        raise OSError("simulated write failure")

    monkeypatch.setattr(os, "write", failing_write)
    with pytest.raises(OSError, match="simulated write failure"):
        _write_once(path, {"status": "ok"})
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_write_once_rejects_a_symlink_published_after_the_temp_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # By the time our own atomic publish (``os.link``) reaches the
    # filesystem, a concurrent writer has swapped the destination for a
    # symlink. This is only caught if the symlink check runs *after* that
    # race -- i.e. inside the ``FileExistsError`` handler, informed by the
    # path's state at link time -- rather than as an earlier stat performed
    # before the link attempt, back when the path was still ordinary and
    # absent. The temp write itself must have already happened and
    # succeeded by the time this race is injected.
    path = tmp_path / "canary.json"
    elsewhere = tmp_path / "elsewhere.json"
    real_link = os.link
    calls = {"count": 0}

    def racing_link(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1 and Path(dst) == path:
            path.symlink_to(elsewhere)
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(ValueError, match="must not be a symlink"):
        _write_once(path, {"status": "ok"})
    # The symlink's target is untouched: a rejected publish never follows
    # the link and writes through it.
    assert not elsewhere.exists()
    # No stray temp file survives the rejection.
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_write_once_rejects_a_concurrent_writer_with_different_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulates a second writer publishing a different payload in the
    # window between our temp write and our own atomic ``os.link``
    # attempt: the link call itself is the only thing that discovers the
    # race, so we inject the competing write from inside a patched
    # os.link just before the real link() runs.
    path = tmp_path / "canary.json"
    real_link = os.link
    calls = {"count": 0}

    def racing_link(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1 and Path(dst) == path:
            path.write_bytes(b'{"status":"from another writer"}\n')
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        _write_once(path, {"status": "ok"})
    # No silent overwrite and no partial read: the file holds exactly what
    # the winning writer published, byte for byte.
    assert path.read_bytes() == b'{"status":"from another writer"}\n'


def test_write_once_is_idempotent_against_a_concurrent_writer_with_identical_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "canary.json"
    payload = canonical_json_bytes({"status": "ok"}) + b"\n"
    real_link = os.link
    calls = {"count": 0}

    def racing_link(src, dst, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1 and Path(dst) == path:
            path.write_bytes(payload)
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    _write_once(path, {"status": "ok"})
    assert path.read_bytes() == payload


# --- resume identity is recomputed, not merely re-read (request hashes) ----


def test_resume_rejects_a_checkpoint_whose_prompt_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    original_instructions = adapter_campaign._CANARY_INSTRUCTIONS
    monkeypatch.setattr(
        adapter_campaign, "_CANARY_INSTRUCTIONS", "Return a different instruction."
    )
    with pytest.raises(ValueError, match="request hash mismatch"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )

    # Restoring the prompt makes the same-path resume valid again: the
    # rejection above was specific to the prompt change, not a general
    # break in resuming.
    monkeypatch.setattr(adapter_campaign, "_CANARY_INSTRUCTIONS", original_instructions)
    second = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=ExplodingClient(),
        )
    )
    assert second == first


# --- record-wide sanitization -----------------------------------------------


def test_adapter_canary_sanitizes_an_unexpected_resolved_model(tmp_path: Path) -> None:
    class ImpersonatingClient(AdmittedClient):
        async def complete(self, request):
            result = await super().complete(request)
            result.resolved_model = "<<secret>>"
            return result

    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "impersonation.json",
            max_output_tokens=(2048,),
            client=ImpersonatingClient(),
        )
    )
    assert record["status"] == "admitted"
    assert record["probes"][0]["resolved_model"] == "unexpected_model"
    assert b"<<secret>>" not in canonical_json_bytes(record)


def test_resume_rejects_a_record_with_an_extra_key_even_with_matching_digest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["provider_message"] = "not part of the schema"
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="unexpected key set"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_record_with_a_probe_removed(tmp_path: Path) -> None:
    # An admitted record must have exactly as many probes as limits it was
    # admitted against: an attacker who deletes one probe and recomputes
    # the digest correctly produces a record that is internally
    # consistent, but no longer the shape an admission promises.
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048, 4096),
            client=AdmittedClient(),
        )
    )
    assert first["status"] == "admitted"
    assert len(first["probes"]) == 2
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["probes"] = tampered["probes"][:1]
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="probe count does not match"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048, 4096),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_provider_failure_checkpoint_whose_prompt_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A ProviderFailure checkpoint carries no probes, so it has nothing to
    # hash-check against the current prompt unless it is re-validated
    # through its own sealed ``first_request_sha256``.
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=RejectedClient(),
        )
    )
    assert first["status"] == "rejected"
    assert first["failure_type"] == "provider_failure"
    assert first["probes"] == []

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    monkeypatch.setattr(
        adapter_campaign, "_CANARY_INSTRUCTIONS", "Return a different instruction."
    )
    with pytest.raises(ValueError, match="request hash mismatch"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_probe_with_an_extra_key(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["probes"] = [dict(first["probes"][0], extra_field="not part of the schema")]
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="unexpected key set"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_probe_with_a_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    incomplete_probe = dict(first["probes"][0])
    del incomplete_probe["cached_input_tokens"]
    tampered["probes"] = [incomplete_probe]
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="unexpected key set"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_record_with_an_unrecognized_failure_condition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=RejectedClient(),
        )
    )
    assert first["status"] == "rejected"
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["failure_condition"] = "not_a_real_condition"
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="unexpected failure_condition"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


# --- resume must not follow a symlinked checkpoint path ---------------------


def test_resume_rejects_a_symlink_checkpoint_path_without_calling_the_provider(
    tmp_path: Path,
) -> None:
    real_path = tmp_path / "canary_real.json"
    asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=real_path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    symlink_path = tmp_path / "canary_link.json"
    symlink_path.symlink_to(real_path)

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError(
                "provider must not be called when checkpoint path is a symlink"
            )

    with pytest.raises(ValueError, match="must not be a symlink"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=symlink_path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_dangling_symlink_checkpoint_path_without_calling_the_provider(
    tmp_path: Path,
) -> None:
    symlink_path = tmp_path / "canary_dangling.json"
    symlink_path.symlink_to(tmp_path / "does_not_exist.json")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError(
                "provider must not be called when checkpoint path is a symlink"
            )

    with pytest.raises(ValueError, match="must not be a symlink"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=symlink_path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


# --- provider-reported token fields are validated before persisting --------


def test_adapter_canary_rejects_non_numeric_token_counts(tmp_path: Path) -> None:
    class LyingTokenClient(AdmittedClient):
        async def complete(self, request):
            result = await super().complete(request)
            result.input_tokens = "SECRET"
            return result

    record = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=tmp_path / "bad_tokens.json",
            max_output_tokens=(2048,),
            client=LyingTokenClient(),
        )
    )
    assert record["status"] == "rejected"
    assert record["failure_condition"] == "invalid_token_accounting"
    assert b"SECRET" not in canonical_json_bytes(record)
    assert record["probes"] == []


# --- resume validates every field's value, not just key names --------------


def test_resume_rejects_a_tampered_status(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["status"] = "tampered_status"
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_tampered_token_field(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["probes"] = [dict(first["probes"][0], input_tokens="SECRET")]
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_tampered_cost_usd(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["cost_usd"] = "SECRET-COST"
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_tampered_cost_accounting_state(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    # cost_usd is known and numeric, so "unknown" is an inconsistent pairing.
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    assert tampered["cost_usd"] is not None
    tampered["cost_accounting_state"] = "unknown"
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


# --- resume checks status/probe consistency, not just per-field vocabulary -


class InvalidContentClient(AdmittedClient):
    async def complete(self, request):
        result = await super().complete(request)
        result.output_text = json.dumps({"status": "not_ok"})
        return result


def test_resume_rejects_an_invalid_response_rejection_rewritten_as_admitted(
    tmp_path: Path,
) -> None:
    # The probe that triggered "invalid_response" completed fully (its
    # finish_reason is "stop", not truncated) but never ran the later
    # limits, so its probe count can never satisfy an admitted record's
    # requirement that every requested limit was tried.
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048, 4096),
            client=InvalidContentClient(),
        )
    )
    assert first["status"] == "rejected"
    assert first["failure_condition"] == "invalid_response"
    assert len(first["probes"]) == 1

    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["status"] = "admitted"
    tampered["failure_type"] = None
    tampered["failure_condition"] = None
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048, 4096),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_a_truncated_response_rejection_missing_its_terminal_probe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048, 4096),
            client=TruncatedClient(),
        )
    )
    assert first["status"] == "rejected"
    assert first["failure_condition"] == "length"
    assert len(first["probes"]) == 1

    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["probes"] = []
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="no probes"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048, 4096),
                client=ExplodingClient(),
            )
        )


def test_resume_rejects_an_admitted_record_with_a_non_stop_probe(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    assert first["status"] == "admitted"
    tampered = {key: value for key, value in first.items() if key != "record_sha256"}
    tampered["probes"] = [dict(first["probes"][0], finish_reason="tool_calls")]
    tampered["record_sha256"] = _digest(tampered)
    path.write_text(json.dumps(tampered), encoding="utf-8")

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a rejected resume")

    with pytest.raises(ValueError, match="non-stop probe"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )


# --- resume reads the checkpoint through a single O_NOFOLLOW descriptor ----


def test_resume_rejects_a_symlink_substituted_after_lstat_without_calling_the_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The symlink check performed before calling _resume (via os.lstat) and
    # the checkpoint read inside _resume are two separate filesystem calls.
    # A concurrent writer can swap the destination for a symlink in between;
    # this is only caught if _resume's own open (not the earlier lstat) is
    # what decides whether the path is safe to read.
    path = tmp_path / "canary.json"
    asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=AdmittedClient(),
        )
    )
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("not a checkpoint", encoding="utf-8")
    real_lstat = os.lstat

    def racing_lstat(target, *args, **kwargs):
        result = real_lstat(target, *args, **kwargs)
        if Path(target) == path:
            path.unlink()
            path.symlink_to(elsewhere)
        return result

    monkeypatch.setattr(os, "lstat", racing_lstat)

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError(
                "provider must not be called when the checkpoint path is a symlink"
            )

    with pytest.raises(ValueError, match="must not be a symlink"):
        asyncio.run(
            run_adapter_canary(
                family_id="contract_fixture",
                checkpoint_path=path,
                max_output_tokens=(2048,),
                client=ExplodingClient(),
            )
        )
    # The race never followed the link and wrote or read through it.
    assert elsewhere.read_text(encoding="utf-8") == "not a checkpoint"


# --- write-once falls back when hard links are unsupported -----------------


def test_write_once_falls_back_when_hard_links_are_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Some filesystems do not support hard links at all and raise EPERM (or
    # EOPNOTSUPP/ENOTSUP) from os.link. A paid canary result must still be
    # durably published rather than left with no checkpoint on disk.
    path = tmp_path / "canary.json"

    def failing_link(src, dst, *args, **kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", failing_link)
    client = AdmittedClient()
    first = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=client,
        )
    )
    assert first["status"] == "admitted"
    assert json.loads(path.read_text(encoding="utf-8")) == first

    class ExplodingClient:
        async def complete(self, request):
            raise AssertionError("provider must not be called on a resumed canary")

    second = asyncio.run(
        run_adapter_canary(
            family_id="contract_fixture",
            checkpoint_path=path,
            max_output_tokens=(2048,),
            client=ExplodingClient(),
        )
    )
    assert second == first
