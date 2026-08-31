"""Deterministic tests for the shared LLM client request construction."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]

from aeread.inference import llm_agent  # noqa: E402


class _FakeCompletions:
    def __init__(self, responses: list[str] | None = None, usage=None) -> None:
        self.kwargs = None
        self.responses = responses or ["OK"]
        self.usage = usage
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        message = SimpleNamespace(content=self.responses.pop(0))
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice], usage=self.usage)


class _FakeClient:
    def __init__(self, responses: list[str] | None = None, usage=None) -> None:
        self.completions = _FakeCompletions(responses, usage)
        self.chat = SimpleNamespace(completions=self.completions)


class _FailingRawResponseCompletions:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.with_raw_response = self

    def create(self, **kwargs):
        raise self.error


class _FailingRawResponseClient:
    def __init__(self, error: Exception) -> None:
        self.chat = SimpleNamespace(completions=_FailingRawResponseCompletions(error))


def test_direct_gpt5_calls_support_low_reasoning_effort_without_token_floor(monkeypatch, tmp_path):
    fake = _FakeClient()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_GPT5_REASONING_EFFORT", "low")
    monkeypatch.delenv("OPENAI_GPT5_MIN_COMPLETION_TOKENS", raising=False)
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    response = llm_agent.call_llm(
        "system",
        "user",
        model="gpt-5.1",
        max_tokens=256,
        cache_dir=tmp_path,
    )

    assert response.text == "OK"
    assert fake.completions.kwargs["max_completion_tokens"] == 256
    assert fake.completions.kwargs["reasoning_effort"] == "low"
    assert "max_tokens" not in fake.completions.kwargs
    assert "temperature" not in fake.completions.kwargs


def test_openrouter_connection_failure_falls_back_to_raw_http(monkeypatch, tmp_path):
    fake = _FailingRawResponseClient(RuntimeError("Connection error."))
    captured = {}

    def fake_raw(api_key, base_url, payload):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": "raw-ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        }

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)
    monkeypatch.setattr(llm_agent, "_post_chat_completions_raw", fake_raw)

    response = llm_agent.call_llm(
        "system",
        "user",
        model="deepseek/deepseek-v4-flash",
        max_tokens=256,
        cache_dir=tmp_path,
    )

    assert response.text == "raw-ok"
    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["payload"]["model"] == "deepseek/deepseek-v4-flash"
    assert captured["payload"]["messages"][0] == {"role": "system", "content": "system"}
    assert response.usage == {
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 3,
        "total_tokens": 13,
        "reasoning_tokens": 0,
    }


def test_direct_gpt5_response_reports_usage_and_estimated_cost(monkeypatch, tmp_path):
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=2000,
        total_tokens=3000,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=600),
    )
    fake = _FakeClient(usage=usage)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_GPT5_REASONING_EFFORT", "low")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_INPUT_PER_1M", "1.00")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_OUTPUT_PER_1M", "2.00")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    response = llm_agent.call_llm(
        "system",
        "user",
        model="gpt-5.1",
        max_tokens=256,
        cache_dir=tmp_path,
    )

    assert response.usage == {
        "input_tokens": 1000,
        "cached_input_tokens": 400,
        "output_tokens": 2000,
        "total_tokens": 3000,
        "reasoning_tokens": 600,
    }
    assert response.estimated_cost_usd == 0.005
    assert response.cost_note == "estimated from configured per-1M token prices"


def test_cached_llm_response_reports_zero_incremental_cost(monkeypatch, tmp_path):
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=2000, total_tokens=3000)
    fake = _FakeClient(usage=usage)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_INPUT_PER_1M", "1.00")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_OUTPUT_PER_1M", "2.00")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    llm_agent.call_llm("system", "user", model="gpt-5.1", cache_dir=tmp_path)
    cached = llm_agent.call_llm("system", "user", model="gpt-5.1", cache_dir=tmp_path)

    assert cached.cached is True
    assert cached.estimated_cost_usd == 0.0
    assert cached.cost_note == "cache hit; no API cost for this call"


def test_cache_key_distinguishes_completion_budget(monkeypatch, tmp_path):
    fake = _FakeClient(["short-budget", "long-budget"])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    first = llm_agent.call_llm("system", "user", model="gpt-5.1", max_tokens=64, cache_dir=tmp_path)
    second = llm_agent.call_llm("system", "user", model="gpt-5.1", max_tokens=256, cache_dir=tmp_path)

    assert first.text == "short-budget"
    assert second.text == "long-budget"
    assert fake.completions.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_cache_key_distinguishes_reasoning_effort(monkeypatch, tmp_path):
    fake = _FakeClient(["low-effort", "high-effort"])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    monkeypatch.setenv("OPENAI_GPT5_REASONING_EFFORT", "low")
    low = llm_agent.call_llm("system", "user", model="gpt-5.1", max_tokens=256, cache_dir=tmp_path)
    monkeypatch.setenv("OPENAI_GPT5_REASONING_EFFORT", "high")
    high = llm_agent.call_llm("system", "user", model="gpt-5.1", max_tokens=256, cache_dir=tmp_path)

    assert low.text == "low-effort"
    assert high.text == "high-effort"
    assert fake.completions.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_cost_estimate_can_use_batch_price_mode(monkeypatch, tmp_path):
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=2000, total_tokens=3000)
    fake = _FakeClient(usage=usage)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_PRICE_MODE", "BATCH")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_BATCH_INPUT_PER_1M", "0.50")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_BATCH_OUTPUT_PER_1M", "1.00")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    response = llm_agent.call_llm("system", "user", model="gpt-5.1", cache_dir=tmp_path)

    assert response.estimated_cost_usd == 0.0025
    assert response.cost_note == "estimated from configured BATCH per-1M token prices"


def test_call_llm_batch_uses_gemini_batch_price_mode(monkeypatch, tmp_path):
    class _FakeGeminiResult:
        def __init__(self, text):
            self.text = text
            self.cached = False
            self.usage = {
                "input_tokens": 1000,
                "cached_input_tokens": 400,
                "output_tokens": 200,
                "total_tokens": 1200,
                "reasoning_tokens": 0,
            }

    captured = {}

    def fake_call_gemini_batch(requests, model, poll_interval=None, display_name=None):
        captured["requests"] = requests
        captured["model"] = model
        return [_FakeGeminiResult("A"), _FakeGeminiResult("B")]

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    # audit R7: the batch path now requires the explicit ordering-verified flag
    monkeypatch.setenv("GEMINI_BATCH_ORDERING_VERIFIED", "1")
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_BATCH_INPUT_PER_1M", "0.75")
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_BATCH_CACHED_INPUT_PER_1M", "0.075")
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_BATCH_OUTPUT_PER_1M", "4.50")
    monkeypatch.setattr(llm_agent, "_import_call_gemini_batch", lambda: fake_call_gemini_batch)

    responses = llm_agent.call_llm_batch(
        [
            {"system": "s1", "user": "u1", "max_tokens": 111},
            {"system": "s2", "user": "u2", "max_tokens": 222},
        ],
        model="google/gemini-3.5-flash",
        cache_dir=tmp_path,
    )

    assert [r.text for r in responses] == ["A", "B"]
    assert captured["model"] == "google/gemini-3.5-flash"
    assert captured["requests"][0]["max_tokens"] == 111
    assert responses[0].estimated_cost_usd == 0.00138
    assert responses[0].cost_note == "estimated from configured BATCH per-1M token prices"


def test_cost_estimate_uses_cached_input_price_when_available(monkeypatch, tmp_path):
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=2000,
        total_tokens=3000,
        prompt_tokens_details=SimpleNamespace(cached_tokens=600),
    )
    fake = _FakeClient(usage=usage)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_INPUT_PER_1M", "1.00")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_CACHED_INPUT_PER_1M", "0.25")
    monkeypatch.setenv("LLM_PRICE_GPT_5_1_OUTPUT_PER_1M", "2.00")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    response = llm_agent.call_llm("system", "user", model="gpt-5.1", cache_dir=tmp_path)

    assert response.usage["cached_input_tokens"] == 600
    assert response.estimated_cost_usd == 0.00455
    assert response.provider_cache_hit_rate == 0.6


def test_cost_estimate_includes_context_cache_storage_token_hours(monkeypatch):
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_INPUT_PER_1M", "1.00")
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_CACHED_INPUT_PER_1M", "0.10")
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_OUTPUT_PER_1M", "2.00")
    monkeypatch.setenv("LLM_PRICE_GOOGLE_GEMINI_3_5_FLASH_CACHE_STORAGE_PER_1M_TOKEN_HOUR", "10.00")
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 900,
        "output_tokens": 100,
        "total_tokens": 1100,
        "reasoning_tokens": 0,
        "context_cache_storage_token_hours": 900,
    }

    cost, note = llm_agent._estimate_cost_usd("google/gemini-3.5-flash", usage, cached=False)

    assert cost == 0.00939
    assert note == "estimated from configured per-1M token prices, including context-cache storage"


def test_empty_llm_responses_are_not_cached_as_success(monkeypatch, tmp_path):
    fake = _FakeClient(["", "OK-after-retry"])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_GPT5_REASONING_EFFORT", "low")
    monkeypatch.setattr(llm_agent, "_get_client", lambda: fake)

    first = llm_agent.call_llm(
        "system",
        "user",
        model="gpt-5.1-empty-test",
        max_tokens=256,
        cache_dir=tmp_path,
    )
    second = llm_agent.call_llm(
        "system",
        "user",
        model="gpt-5.1-empty-test",
        max_tokens=256,
        cache_dir=tmp_path,
    )

    assert first.text == ""
    assert second.text == "OK-after-retry"
    cached_payloads = [path.read_text() for path in tmp_path.glob("*.json")]
    assert len(cached_payloads) == 1
    assert "OK-after-retry" in cached_payloads[0]


def test_empty_openrouter_body_is_retryable():
    # OpenRouter occasionally returns an empty/malformed body under load; the
    # _parse_openrouter_body JSONDecodeError must be retried, not surfaced as a
    # hard failure (2026-07-21: leaked through as harness_error in a sweep).
    import json as _json
    err = _json.JSONDecodeError("no JSON object in OpenRouter body", "", 0)
    assert llm_agent._is_retryable_error(err) is True
    # but a real auth error must still NOT be retried
    assert llm_agent._is_retryable_error(Exception("401 invalid api key")) is False


def test_openrouter_completion_floor_env(monkeypatch):
    """Mute-audit fix: OPENROUTER_MIN_COMPLETION_TOKENS lifts small caps."""
    from aeread.inference import llm_agent as la

    monkeypatch.delenv("OPENROUTER_MIN_COMPLETION_TOKENS", raising=False)
    assert la._openrouter_completion_token_budget(1200) == 1200
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "4096")
    assert la._openrouter_completion_token_budget(1200) == 4096
    assert la._openrouter_completion_token_budget(8000) == 8000
    monkeypatch.setenv("OPENROUTER_MIN_COMPLETION_TOKENS", "abc")
    import pytest
    with pytest.raises(RuntimeError):
        la._openrouter_completion_token_budget(1200)


def test_call_llm_batch_length_mismatch_is_loud(monkeypatch, tmp_path):
    """Audit R7: a shortened batch result must raise, never zip-misalign."""
    import pytest

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_BATCH_ORDERING_VERIFIED", "1")

    class _R:
        text = "only-one"
        cached = False
        usage = None

    monkeypatch.setattr(
        llm_agent, "_import_call_gemini_batch",
        lambda: (lambda requests, model, poll_interval=None: [_R()]))
    with pytest.raises(RuntimeError, match="refusing positional alignment"):
        llm_agent.call_llm_batch(
            [{"system": "s", "user": "u1"}, {"system": "s", "user": "u2"}],
            model="google/gemini-3.5-flash", cache_dir=tmp_path)
