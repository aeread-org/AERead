"""The disclosure probe: state collection from a run root, the grouping, and the summary."""

import asyncio
import types

from aeread_families.housing import price_campaign, price_disclosure_probe as probe


def _preflight_root(tmp_path):
    contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT)
    asyncio.run(price_campaign.run(contract, tmp_path, live=False))
    return tmp_path / "preflight"


def test_states_carry_the_recorded_request_and_the_groups_the_summary_needs(tmp_path):
    states = probe.collect_states(_preflight_root(tmp_path))
    assert states and all(s["request"]["input_text"] for s in states)
    assert {s["arm"] for s in states} == {"true_cost", "pooled"}
    # The scripted reference inspects before it signs, so every hold it faces is informed.
    assert all(s["informed"] for s in states)
    assert {probe.group_of(s) for s in states} == {"informed hold"}
    assert len({s["state_id"] for s in states}) == len(states)


def test_probe_replays_each_state_under_each_variant_and_counts_sign_rates(tmp_path):
    states = probe.collect_states(_preflight_root(tmp_path))[:6]

    class Stub:
        def __init__(self):
            self.seen = []

        async def complete(self, request):
            self.seen.append(request)
            explicit = "more than $250 below" in request.instructions
            text = '{"decision":"walk","hold_id":"h"}' if explicit else '{"decision":"sign","hold_id":"h"}'
            return types.SimpleNamespace(output_text=text, cost_usd=0.001)

    stub = Stub()
    results = asyncio.run(probe.run_probe(states, stub, samples=2, concurrency=3))
    assert len(results) == 6 * 3 * 2 == len(stub.seen)
    # The recorded request is replayed unchanged apart from the appended disclosure and the seed.
    original = states[0]["request"]
    assert any(r.input_text == original["input_text"] and r.instructions == original["instructions"] for r in stub.seen)
    assert len({r.seed for r in stub.seen if r.input_text == original["input_text"]}) == 2
    summary = probe.summarize(states, results)["sign_rate_by_group_and_variant"]["informed hold"]
    assert summary["original"]["sign_rate"] == summary["qualitative"]["sign_rate"] == 1.0
    assert summary["explicit"]["sign_rate"] == 0.0


def test_a_failed_call_is_missingness_not_a_decision(tmp_path):
    states = probe.collect_states(_preflight_root(tmp_path))[:2]

    class Failing:
        async def complete(self, request):
            raise RuntimeError("boom")

    results = asyncio.run(probe.run_probe(states, Failing(), samples=1, concurrency=2))
    assert all(r["decision"] is None and r["error"] == "RuntimeError" for r in results)
    cell = probe.summarize(states, results)["sign_rate_by_group_and_variant"]["informed hold"]["original"]
    assert cell["failed"] == cell["calls"] and cell["sign_rate"] is None
