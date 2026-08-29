"""Family-neutral paired batching: durable evidence, resume, stops, and Google accounting."""
import asyncio
import json
from dataclasses import replace

import pytest

from aeread.shared_runner.batch import (
    event_execution_metrics, prepare_unknown_billing_recovery, read_family_batch,
    run_family_batch,
)
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


class RateLimitedBuyer(CountingBuyer):
    async def complete(self, request):
        self.calls += 1
        raise ProviderFailure("rate_limit", "temporary shared-pool throttling", retryable=True, status_code=429)


class UnknownBillingBuyer(CountingBuyer):
    async def complete(self, request):
        self.calls += 1
        raise ProviderFailure("timeout", "provider outcome is unknown", retryable=True)


def prepare_unknown_recovery(source, target, setup_map, **overrides):
    manifest = json.loads((source / "batch_manifest.json").read_text())
    arguments = {
        "setups": setup_map,
        "source_root": source,
        "output_root": target,
        "expected_manifest_sha256": manifest["result_sha256"],
        "reason": "Operator reconciled the aggregate usage delta and reserved the full unknown-call ceiling.",
        "account_usage_before_usd": 100.0,
        "account_usage_after_usd": 100.001,
        "account_known_cost_usd": 0.0,
        "unknown_call_reserve_usd_each": 0.01,
        "request_cost_upper_bounds_usd": [0.002],
    }
    arguments.update(overrides)
    return prepare_unknown_billing_recovery(**arguments)


def test_unknown_billing_recovery_preserves_receipts_and_reserves_full_cost(tmp_path):
    setup_map = setups()
    source, target = tmp_path / "unknown", tmp_path / "recovery"
    first = run(source, setup_map, UnknownBillingBuyer())
    assert first["stop_reason"] == "unknown_billing"
    assert first["unknown_cost_provider_call_count"] == 1
    original_files = {str(p.relative_to(source)): p.read_bytes()
                      for p in source.rglob("*") if p.is_file()}

    checkpoint = prepare_unknown_recovery(source, target, setup_map)
    assert checkpoint["acknowledged_unknown_cost_provider_call_count"] == 1
    assert checkpoint["reserved_unknown_cost_usd"] == .01
    assert checkpoint["account_unexplained_delta_usd"] == pytest.approx(.001)

    buyer = CountingBuyer()
    resumed = run(target, setup_map, buyer, max_new_cells=2)
    assert resumed["attempted_cell_count"] == 3
    assert resumed["included_count"] == 2 and resumed["excluded_count"] == 1
    assert resumed["unknown_cost_provider_call_count"] == 0
    assert resumed["acknowledged_unknown_cost_provider_call_count"] == 1
    assert resumed["reserved_unknown_cost_usd"] == .01
    assert resumed["conservative_cost_usd"] == .01
    assert buyer.calls == 8
    assert read_family_batch(setups=setup_map, output_root=target) == resumed["rows"]
    assert all((source / name).read_bytes() == content
               for name, content in original_files.items())


def test_unknown_billing_recovery_rejects_underreserved_or_unreconciled_delta(tmp_path):
    setup_map = setups()
    source = tmp_path / "unknown"
    run(source, setup_map, UnknownBillingBuyer())
    with pytest.raises(ValueError, match="reserve|usage|delta"):
        prepare_unknown_recovery(source, tmp_path / "underreserved", setup_map,
            account_usage_after_usd=100.02)
    with pytest.raises(ValueError, match="bound|reserve"):
        prepare_unknown_recovery(source, tmp_path / "bad-bound", setup_map,
            request_cost_upper_bounds_usd=[0.02])


def prepare_recovery(source, target, setup_map):
    from aeread.shared_runner.batch import prepare_rate_limit_recovery
    manifest = json.loads((source / "batch_manifest.json").read_text())
    return prepare_rate_limit_recovery(
        setups=setup_map, source_root=source, output_root=target,
        expected_manifest_sha256=manifest["result_sha256"],
        reason="Operator reviewed the upstream 429 stop; resume only unattempted cells.")


def test_explicit_rate_limit_recovery_preserves_rows_and_never_repeats_attempts(tmp_path):
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    first = run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    original_files = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    checkpoint = prepare_recovery(source, target, setup_map)
    assert checkpoint["prefix_result_sha256s"] == [r["result_sha256"] for r in first["rows"]]
    buyer = CountingBuyer()
    resumed = run(target, setup_map, buyer, max_consecutive_failures=1, max_new_cells=2)
    assert resumed["attempted_cell_count"] == 3 and resumed["included_count"] == 2
    assert resumed["rows"][0] == first["rows"][0] and buyer.calls == 8
    assert resumed["rows"][0]["within_case_score"] is None
    complete = run(target, setup_map, buyer, max_consecutive_failures=1)
    while complete["stop_reason"] == "invocation_cell_limit":
        complete = run(target, setup_map, buyer, max_consecutive_failures=1)
    assert complete["attempted_cell_count"] == 8 and complete["excluded_count"] == 1
    assert buyer.calls == 28
    assert read_family_batch(setups=setup_map, output_root=target) == complete["rows"]
    assert all((source / name).read_bytes() == content for name, content in original_files.items())


def test_recovery_acknowledges_only_the_old_circuit_and_new_failures_still_latch(tmp_path):
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    prepare_recovery(source, target, setup_map)
    buyer = RateLimitedBuyer()
    first = run(target, setup_map, buyer, max_consecutive_failures=1)
    assert first["attempted_cell_count"] == 2 and first["stop_reason"] == "failure_circuit"
    assert run(target, setup_map, buyer, max_consecutive_failures=1) == first
    assert buyer.calls == 1
    with pytest.raises(ValueError, match="recovery|acknowledge"):
        prepare_recovery(target, tmp_path / "another", setup_map)


@pytest.mark.parametrize("condition", ["timeout", "provider_contract"])
def test_rate_limit_recovery_cannot_acknowledge_other_failures_or_unknown_billing(tmp_path, condition):
    class Broken(CountingBuyer):
        async def complete(self, request):
            self.calls += 1
            raise ProviderFailure(condition, "test failure", retryable=False)
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    run(source, setup_map, Broken(), max_consecutive_failures=1)
    with pytest.raises(ValueError, match="rate.limit|billing"):
        prepare_recovery(source, target, setup_map)
    assert not target.exists()


def test_recovery_cannot_reset_spend_or_change_frozen_batch_policy(tmp_path):
    class SpendThenThrottle(CountingBuyer):
        async def complete(self, request):
            if json.loads(request.input_text)["phase_id"] != "rfq":
                raise ProviderFailure("rate_limit", "test throttling", retryable=True, status_code=429)
            return replace(await super().complete(request), cost_usd=.0002)
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    first = run(source, setup_map, SpendThenThrottle(), max_consecutive_failures=1)
    prepare_recovery(source, target, setup_map)
    buyer = CountingBuyer()
    resumed = run(target, setup_map, buyer, max_consecutive_failures=1, max_new_cells=1)
    assert resumed["known_cost_usd"] == first["known_cost_usd"] == .0002
    with pytest.raises(ValueError, match="manifest"):
        run(target, setup_map, buyer, max_consecutive_failures=2)
    exhausted = tmp_path / "exhausted"
    run(exhausted, setup_map, SpendThenThrottle(), max_consecutive_failures=1, spend_limit_usd=.0001)
    with pytest.raises(ValueError, match="budget|spend"):
        prepare_recovery(exhausted, tmp_path / "forbidden", setup_map)


def test_recovery_is_single_destination_and_never_overwrites_a_collision(tmp_path):
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("user data")
    with pytest.raises(FileExistsError):
        prepare_recovery(source, occupied, setup_map)
    assert (occupied / "keep.txt").read_text() == "user data"
    checkpoint = prepare_recovery(source, target, setup_map)
    assert prepare_recovery(source, target, setup_map) == checkpoint
    with pytest.raises(ValueError, match="destination|child"):
        prepare_recovery(source, tmp_path / "duplicate", setup_map)


def test_recovery_rejects_a_tampered_checkpoint_before_provider_calls(tmp_path):
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    prepare_recovery(source, target, setup_map)
    checkpoint_path = target / "recovery_checkpoint.json"
    value = json.loads(checkpoint_path.read_text())
    value["prefix_result_sha256s"] = []
    checkpoint_path.write_text(json.dumps(value))
    buyer = CountingBuyer()
    with pytest.raises(ValueError, match="checkpoint|sealed"):
        run(target, setup_map, buyer, max_consecutive_failures=1)
    assert buyer.calls == 0


def test_recovery_requires_an_actual_circuit_and_an_unlocked_source(tmp_path):
    import fcntl
    setup_map = setups()
    healthy = tmp_path / "healthy"
    run(healthy, setup_map, max_new_cells=1)
    with pytest.raises(ValueError, match="circuit"):
        prepare_recovery(healthy, tmp_path / "invalid", setup_map)
    source = tmp_path / "original"
    run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    with (source / ".batch.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="lock"):
            prepare_recovery(source, tmp_path / "locked", setup_map)


def test_recovery_refuses_a_dangling_destination_symlink(tmp_path):
    setup_map = setups()
    source, destination = tmp_path / "original", tmp_path / "link"
    run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    outside = tmp_path / "not_the_requested_destination"
    destination.symlink_to(outside)
    with pytest.raises(FileExistsError):
        prepare_recovery(source, destination, setup_map)
    assert not outside.exists()


def test_recovery_defaults_to_a_sealed_four_new_cell_limit(tmp_path):
    setup_map = setups()
    source, target = tmp_path / "original", tmp_path / "recovery"
    run(source, setup_map, RateLimitedBuyer(), max_consecutive_failures=1)
    checkpoint = prepare_recovery(source, target, setup_map)
    buyer = CountingBuyer()
    resumed = run(target, setup_map, buyer, max_consecutive_failures=1)
    assert resumed["attempted_cell_count"] == 5
    assert resumed["stop_reason"] == "invocation_cell_limit" and buyer.calls == 16
    assert checkpoint["max_new_cells_per_invocation"] == 4
    with pytest.raises(ValueError, match="four|limit"):
        run(target, setup_map, buyer, max_consecutive_failures=1, max_new_cells=5)
    assert buyer.calls == 16


def test_recovery_pauses_on_a_new_rate_limit_without_waiting_for_three_failures(tmp_path):
    class ThrottleOnce(CountingBuyer):
        async def complete(self, request):
            if self.calls == 0:
                self.calls += 1
                raise ProviderFailure("rate_limit", "new throttling", retryable=True, status_code=429)
            return await super().complete(request)
    setup_map = setups(seeds=(11, 12, 13, 14))
    source, target = tmp_path / "original", tmp_path / "recovery"
    first = run(source, setup_map, RateLimitedBuyer())
    prepare_recovery(source, target, setup_map)
    buyer = ThrottleOnce()
    paused = run(target, setup_map, buyer)
    assert paused["attempted_cell_count"] == first["attempted_cell_count"] + 1
    assert paused["stop_reason"] == "rate_limit_pause" and buyer.calls == 1
