"""Family-neutral paired batching: durable evidence, resume, stops, and Google accounting."""
import asyncio
import json
from dataclasses import replace

import pytest

from aeread.shared_runner.batch import event_execution_metrics, read_family_batch, run_family_batch
from aeread.shared_runner.execution import ProviderFailure
from aeread.shared_runner.procurement_measurement import procurement_measurement_leaf
from aeread.shared_runner.procurement_rfq import (
    ProcurementScriptedBuyerProvider, ProcurementScriptedSupplierProvider, build_procurement_rfq_smoke,
)


def setups(seeds=(11, 12), replicates=2):
    return {condition: build_procurement_rfq_smoke(world_seeds=seeds, replicates=replicates, condition_id=condition)
            for condition in ("scripted_control", "scripted_repeat")}


class CountingBuyer(ProcurementScriptedBuyerProvider):
    def __init__(self):
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        return await super().complete(request)


def run(root, setup_map, buyer=None, **kwargs):
    buyer = buyer or CountingBuyer()
    clients = {condition: {"procurement_scripted_buyer": buyer,
                           "procurement_scripted_supplier": ProcurementScriptedSupplierProvider()}
               for condition in setup_map}
    return asyncio.run(run_family_batch(setups=setup_map, output_root=root,
        providers_by_condition=clients, leaf_builder=procurement_measurement_leaf,
        spend_limit_usd=kwargs.pop("spend_limit_usd", 1.0), **kwargs))


def test_batch_pairs_cells_resumes_without_calls_and_rejects_tampering(tmp_path):
    setup_map = setups()
    buyer = CountingBuyer()
    first = run(tmp_path, setup_map, buyer)
    assert first["planned_cell_count"] == first["included_count"] == 8
    assert first["known_cost_usd"] == 0 and buyer.calls == 32
    resumed = run(tmp_path, setup_map, buyer)
    assert resumed == first and buyer.calls == 32
    rows = read_family_batch(setups=setup_map, output_root=tmp_path)
    assert len(rows) == 8 and all(r["replay_level"] == "state_and_score" for r in rows)
    result = next(tmp_path.glob("*/results/*.json"))
    value = json.loads(result.read_text())
    value["within_case_score"] = 1.0
    result.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="result"):
        run(tmp_path, setup_map, buyer)
    assert buyer.calls == 32


def test_batch_preserves_failure_and_opens_circuit_without_zero_score(tmp_path):
    class Broken(CountingBuyer):
        async def complete(self, request):
            self.calls += 1
            raise ProviderFailure("provider_contract", "fake failure", retryable=False)
    buyer = Broken()
    setup_map = setups()
    result = run(tmp_path, setup_map, buyer, max_consecutive_failures=1)
    assert result["stop_reason"] == "failure_circuit"
    assert result["excluded_count"] == 1 and result["included_count"] == 0
    assert result["rows"][0]["within_case_score"] is None
    run(tmp_path, setup_map, buyer, max_consecutive_failures=1)
    assert buyer.calls == 1


def test_batch_interrupt_resume_cannot_rerun_an_orphan(tmp_path):
    setup_map = setups()
    buyer = CountingBuyer()
    first = run(tmp_path, setup_map, buyer, max_new_cells=1)
    assert first["attempted_cell_count"] == 1
    condition = next(c for c in setup_map if c != first["rows"][0]["condition_id"])
    cell = sorted(setup_map[condition].plan.cells, key=lambda c: (c.world_seed, c.replicate_index))[0]
    orphan = tmp_path / condition / "evidence" / setup_map[condition].plan.run_plan_id / cell.cell_id / "episode_attempt_orphan"
    orphan.mkdir(parents=True)
    with pytest.raises(ValueError, match="orphan|interrupted"):
        run(tmp_path, setup_map, buyer)
    assert buyer.calls == 4


def test_batch_rejects_changed_policy_or_unpaired_worlds(tmp_path):
    setup_map = setups()
    run(tmp_path, setup_map, max_new_cells=1)
    with pytest.raises(ValueError, match="manifest"):
        run(tmp_path, setup_map, spend_limit_usd=2)
    setup_map["scripted_repeat"] = build_procurement_rfq_smoke(world_seeds=(11, 13), replicates=2, condition_id="scripted_repeat")
    with pytest.raises(ValueError, match="paired"):
        run(tmp_path, setup_map)


def test_google_metrics_count_native_calls_thoughts_and_unknown_billing():
    class Event:
        def __init__(self, kind, payload):
            self.event_type, self.payload = kind, payload
            self.provider_call_id = "call1"
    class Evidence:
        def read_events(self):
            return [Event("provider_call_started", {"request": {"provider": "google", "seed": 7, "reasoning_effort": "low"}}),
                    Event("provider_call_succeeded", {"cost_usd": .01, "provider_result": {
                        "resolved_model": "gemini-3.7-flash", "raw_response": {"usageMetadata": {"thoughtsTokenCount": 42}}}}),
                    Event("provider_call_outcome_unknown", {"cost_usd": "unknown"})]
        def read_event_payload(self, event):
            return event.payload
    metrics = event_execution_metrics(Evidence(), external_providers={"google"})
    assert metrics["external_provider_call_count"] == 1
    assert metrics["reasoning_tokens"] == 42
    assert metrics["unknown_cost_provider_call_count"] == 1
    assert metrics["request_seeds"] == [7]
    assert metrics["cost_usd"] == .01


def test_recorded_cost_stop_is_global_across_conditions(tmp_path):
    class Priced(CountingBuyer):
        async def complete(self, request):
            return replace(await super().complete(request), cost_usd=.0002)
    buyer = Priced()
    result = run(tmp_path, setups(), buyer, spend_limit_usd=.0005)
    assert result["stop_reason"] == "recorded_cost_limit"
    assert result["attempted_cell_count"] == 1 and buyer.calls == 4
    assert result["known_cost_usd"] == pytest.approx(.0008)


def test_unknown_billing_stops_before_another_condition(tmp_path):
    class Timeout(CountingBuyer):
        async def complete(self, request):
            self.calls += 1
            raise ProviderFailure("timeout", "unknown provider outcome", retryable=True)
    buyer = Timeout()
    result = run(tmp_path, setups(), buyer)
    assert result["stop_reason"] == "unknown_billing"
    assert result["unknown_cost_provider_call_count"] == 1 and buyer.calls == 1


def test_receipt_only_crash_recovers_result_without_model_calls(tmp_path):
    setup_map = setups()
    buyer = CountingBuyer()
    run(tmp_path, setup_map, buyer)
    next(tmp_path.glob("*/results/*.json")).unlink()
    resumed = run(tmp_path, setup_map, buyer)
    assert resumed["included_count"] == 8 and buyer.calls == 32


def test_active_batch_lock_blocks_second_writer(tmp_path):
    import fcntl
    with (tmp_path / ".batch.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="lock"):
            run(tmp_path, setups())


def test_openrouter_metrics_verify_selected_route_from_response_metadata():
    class Event:
        def __init__(self, kind, payload):
            self.event_type, self.payload, self.provider_call_id = kind, payload, "call1"
    class Evidence:
        def __init__(self, provider):
            self.provider = provider
        def read_events(self):
            return [Event("provider_call_started", {"request": {
                "provider": "openrouter", "model": "deepseek/deepseek-v4-flash-0731",
                "temperature": 1.0,
                "provider_metadata": {"route_provider": "Parasail", "canonical_model": "deepseek/deepseek-v4-flash-20260731"}}}),
                Event("provider_call_succeeded", {"cost_usd": .001, "provider_result": {
                    "resolved_model": "deepseek/deepseek-v4-flash-20260731", "raw_response": {
                        "openrouter_metadata": {"requested": "deepseek/deepseek-v4-flash-0731", "attempt": 1,
                            "endpoints": {"available": [{"selected": True, "provider": self.provider,
                                "model": "deepseek/deepseek-v4-flash-20260731"}]}}}}})]
        def read_event_payload(self, event):
            return event.payload
    good = event_execution_metrics(Evidence("Parasail"), external_providers={"openrouter"})
    assert good["route_providers"] == ["Parasail"] and good["route_verification_failures"] == 0
    assert good["temperatures"] == [1.0]
    bad = event_execution_metrics(Evidence("another_provider"), external_providers={"openrouter"})
    assert bad["route_providers"] == [] and bad["route_verification_failures"] == 1


def test_parallel_batch_reserves_budget_and_resumes_without_duplicate_calls(tmp_path):
    class PricedConcurrent(CountingBuyer):
        def __init__(self):
            super().__init__()
            self.active = self.peak = 0

        async def complete(self, request):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(.01)
                return replace(await super().complete(request), cost_usd=.0002)
            finally:
                self.active -= 1

    buyer = PricedConcurrent()
    setup_map = setups()
    kwargs = dict(max_concurrency=2, inflight_episode_reserve_usd=.001, spend_limit_usd=.003)
    result = run(tmp_path, setup_map, buyer, **kwargs)
    assert buyer.peak == 2 and buyer.calls == 12
    assert result["included_count"] == 3 and result["stop_reason"] == "budget_reservation"
    assert result["known_cost_usd"] == pytest.approx(.0024)
    resumed = run(tmp_path, setup_map, buyer, **kwargs)
    assert resumed == result and buyer.calls == 12
    with pytest.raises(ValueError, match="manifest"):
        run(tmp_path, setup_map, buyer, **{**kwargs, "max_concurrency": 3})


@pytest.mark.parametrize("failure, expected", [("provider_contract", "failure_circuit"),
                                             ("timeout", "unknown_billing")])
def test_parallel_batch_drains_inflight_failures_but_does_not_start_another_wave(tmp_path, failure, expected):
    class Broken(CountingBuyer):
        async def complete(self, request):
            self.calls += 1
            await asyncio.sleep(.01)
            raise ProviderFailure(failure, "test failure", retryable=False)
    buyer = Broken()
    result = run(tmp_path, setups(), buyer, max_concurrency=2,
        inflight_episode_reserve_usd=.01, max_consecutive_failures=1)
    assert result["stop_reason"] == expected
    assert result["attempted_cell_count"] == result["excluded_count"] == buyer.calls == 2
    assert all(row["within_case_score"] is None for row in result["rows"])


def test_parallel_batch_refuses_unreserved_dispatch_and_detects_bad_reservation(tmp_path):
    with pytest.raises(ValueError, match="reserve|reservation"):
        run(tmp_path, setups(), max_concurrency=2)
    class Underreserved(CountingBuyer):
        async def complete(self, request):
            return replace(await super().complete(request), cost_usd=.0002)
    result = run(tmp_path, setups(), Underreserved(), max_concurrency=2,
        inflight_episode_reserve_usd=.0005)
    assert result["stop_reason"] == "inflight_reservation_exceeded"
    assert result["attempted_cell_count"] == 2


def test_parallel_failure_circuit_latches_even_if_later_inflight_cells_succeed(tmp_path):
    class FailThenRecover(CountingBuyer):
        def __init__(self):
            super().__init__()
            self.episodes = 0

        async def complete(self, request):
            if json.loads(request.input_text)["phase_id"] == "rfq":
                self.episodes += 1
                if self.episodes <= 6:
                    self.calls += 1
                    raise ProviderFailure("provider_contract", "test failure", retryable=False)
            return await super().complete(request)
    buyer = FailThenRecover()
    setup_map = setups(seeds=(11, 12, 13))
    kwargs = dict(max_concurrency=8, inflight_episode_reserve_usd=.01)
    result = run(tmp_path, setup_map, buyer, **kwargs)
    assert result["attempted_cell_count"] == 8
    assert result["included_count"] == 2 and result["excluded_count"] == 6
    assert result["stop_reason"] == "failure_circuit"
    calls = buyer.calls
    assert run(tmp_path, setup_map, buyer, **kwargs) == result
    assert buyer.calls == calls
