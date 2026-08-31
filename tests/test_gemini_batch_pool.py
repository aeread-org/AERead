"""Cross-run batch pool + context-local llm_agent hook state (keyless).

The lockstep orchestrator's two foundations: (1) many concurrent runs' live calls
funnel into grouped call_gemini_batch submissions with alignment/error defenses;
(2) per-run observer/replay state is context-local so concurrent runs in one
process cannot cross-contaminate manifests."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread.inference import gemini as gemini_llm  # noqa: E402
from aeread.inference import llm_agent  # noqa: E402
from aeread.inference.gemini_batch_pool import GeminiBatchPool  # noqa: E402


def _r(text):
    return gemini_llm._R(text, cached=False, usage={"input_tokens": 1, "output_tokens": 1})


def _submit_many(pool, n, model="gemini-2.5-flash"):
    results, errors = [None] * n, [None] * n

    def worker(i):
        try:
            results[i] = pool.submit(model, "sys", f"user-{i}", 100, 0.0, "")
        except BaseException as err:  # noqa: BLE001
            errors[i] = err

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_pool_groups_concurrent_calls_into_one_batch(monkeypatch):
    calls = []

    def fake_batch(requests, model, **kwargs):
        calls.append((model, len(requests)))
        return [_r(f"echo:{req['user']}") for req in requests]

    monkeypatch.setattr(gemini_llm, "call_gemini_batch", fake_batch)
    monkeypatch.setenv("GEMINI_BATCH_ORDERING_VERIFIED", "1")
    pool = GeminiBatchPool(flush_interval=0.05)
    pool.start()
    try:
        results, errors = _submit_many(pool, 8)
    finally:
        pool.stop()
    assert errors == [None] * 8
    assert [r.text for r in results] == [f"echo:user-{i}" for i in range(8)]
    assert sum(n for _, n in calls) == 8
    assert len(calls) <= 3            # flushed in a few batches, not 8 singles
    assert pool.stats["batched_items"] == 8 and pool.stats["sync_fallbacks"] == 0


def test_pool_falls_back_per_item_on_misaligned_batch(monkeypatch):
    def bad_batch(requests, model, **kwargs):
        return [_r("only-one")]  # dropped entries (the call_gemini_batch filter)

    sync_calls = []

    def fake_sync(system, user, model="m", max_tokens=0, temperature=0.0,
                  cache_salt="", _bypass_pool=False):
        assert _bypass_pool is True   # fallback must not re-enter the pool
        sync_calls.append(user)
        if user == "user-1":
            raise RuntimeError("boom on user-1")
        return _r(f"sync:{user}")

    monkeypatch.setattr(gemini_llm, "call_gemini_batch", bad_batch)
    monkeypatch.setattr(gemini_llm, "call_gemini", fake_sync)
    monkeypatch.setenv("GEMINI_BATCH_ORDERING_VERIFIED", "1")
    pool = GeminiBatchPool(flush_interval=0.05)
    pool.start()
    try:
        results, errors = _submit_many(pool, 3)
    finally:
        pool.stop()
    assert sorted(sync_calls) == ["user-0", "user-1", "user-2"]
    assert results[0].text == "sync:user-0" and results[2].text == "sync:user-2"
    assert isinstance(errors[1], RuntimeError)        # only that caller fails
    assert pool.stats["batches"] == 0


def test_call_gemini_routes_to_active_pool(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_VERTEX", raising=False)
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)

    class FakePool:
        def __init__(self):
            self.calls = []

        def submit(self, model, system, user, max_tokens, temperature, cache_salt):
            self.calls.append(user)
            return _r("pooled")

    fake = FakePool()
    monkeypatch.setattr(gemini_llm, "_CROSSRUN_POOL", fake)
    r = gemini_llm.call_gemini("sys", "hello", model="gemini-2.5-flash")
    assert r.text == "pooled" and fake.calls == ["hello"]
    # a cached response must bypass the pool entirely
    cf = gemini_llm._response_cache_file(
        "gemini-2.5-flash", "sys", "cached-q", 0.0, "", 2000, 0, False)
    cf.write_text('{"text": "from-cache", "usage": {}}')
    r2 = gemini_llm.call_gemini("sys", "cached-q", model="gemini-2.5-flash")
    assert r2.cached is True and r2.text == "from-cache" and fake.calls == ["hello"]


def test_pool_refuses_vertex(monkeypatch):
    monkeypatch.setenv("GEMINI_VERTEX", "1")
    with pytest.raises(RuntimeError, match="Batch API"):
        GeminiBatchPool().start()


def test_pool_refuses_until_ordering_verified(monkeypatch):
    # launch blocker: upstream inline-response ordering is unreliable
    # (python-genai #1909/#1886) — the pool must refuse scored work by default
    monkeypatch.delenv("GEMINI_VERTEX", raising=False)
    monkeypatch.delenv("GEMINI_BATCH_ORDERING_VERIFIED", raising=False)
    with pytest.raises(RuntimeError, match="ordering"):
        GeminiBatchPool().start()


def test_observer_and_replay_dir_are_context_local():
    seen_a, seen_b = [], []
    barrier = threading.Barrier(2)

    def runner(tag, sink, replay):
        llm_agent.set_call_observer(sink.append)
        llm_agent.set_replay_dir(replay)
        barrier.wait()                    # both threads have installed their hooks
        llm_agent._notify_observer(
            llm_agent.LLMResponse(model=tag, text="t", cached=False, usage={}),
            system="s", user="u", replay_key="k", provider_path="p",
            max_tokens=1, temperature=0.0, sample=0)
        assert llm_agent.get_replay_dir() == Path(replay)

    ta = threading.Thread(target=runner, args=("a", seen_a, "/tmp/replay-a"))
    tb = threading.Thread(target=runner, args=("b", seen_b, "/tmp/replay-b"))
    ta.start(); tb.start(); ta.join(); tb.join()
    assert [d["model"] for d in seen_a] == ["a"]
    assert [d["model"] for d in seen_b] == ["b"]
    assert llm_agent.get_replay_dir() is None         # main thread untouched
