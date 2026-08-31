"""Deterministic tests for the native Gemini REST cache."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.error

ROOT = Path(__file__).resolve().parents[1]

from aeread.inference import gemini as gemini_llm  # noqa: E402


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class _FakeUrlopen:
    def __init__(self, texts: list[str] | None = None) -> None:
        self.calls = 0
        self.texts = texts or []

    def __call__(self, req, timeout=90):
        self.calls += 1
        body = json.loads(req.data.decode())
        cfg = body["generationConfig"]
        if self.texts:
            text = self.texts.pop(0)
        else:
            text = f"max={cfg['maxOutputTokens']} think={cfg['thinkingConfig']['thinkingBudget']}"
        return _FakeHTTPResponse(
            {
                "candidates": [{"content": {"parts": [{"text": text}]}}],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": len(text.split()) or 1,
                    "totalTokenCount": 12,
                },
            }
        )


class _TimeoutThenSuccessUrlopen:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, req, timeout=90):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("simulated read timeout")
        return _FakeHTTPResponse(
            {
                "candidates": [{"content": {"parts": [{"text": "OK-after-timeout"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 11,
                },
            }
        )


class _HTTP503ThenSuccessUrlopen:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, req, timeout=90):
        self.calls += 1
        if self.calls == 1:
            raise urllib.error.HTTPError(
                req.full_url,
                503,
                "Service Unavailable",
                hdrs=None,
                fp=None,
            )
        return _FakeHTTPResponse(
            {
                "candidates": [{"content": {"parts": [{"text": "OK-after-503"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 11,
                },
            }
        )


class _FakeContextCacheUrlopen:
    def __init__(self) -> None:
        self.create_calls = 0
        self.generate_calls = 0
        self.create_bodies = []
        self.generate_bodies = []

    def __call__(self, req, timeout=90):
        body = json.loads(req.data.decode())
        url = req.full_url
        if url.endswith("/cachedContents"):
            self.create_calls += 1
            self.create_bodies.append(body)
            return _FakeHTTPResponse({"name": "cachedContents/shared-prefix"})
        self.generate_calls += 1
        self.generate_bodies.append(body)
        return _FakeHTTPResponse(
            {
                "candidates": [{"content": {"parts": [{"text": f"OK-{self.generate_calls}"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "cachedContentTokenCount": 90,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 123,
                },
            }
        )


class _FailContextCacheThenGenerateUrlopen:
    def __init__(self) -> None:
        self.create_calls = 0
        self.generate_calls = 0
        self.generate_bodies = []

    def __call__(self, req, timeout=90):
        body = json.loads(req.data.decode())
        url = req.full_url
        if url.endswith("/cachedContents"):
            self.create_calls += 1
            raise urllib.error.URLError("simulated context-cache handshake timeout")
        self.generate_calls += 1
        self.generate_bodies.append(body)
        return _FakeHTTPResponse(
            {
                "candidates": [{"content": {"parts": [{"text": "OK-without-context-cache"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 123,
                },
            }
        )


class _FakeBatchUrlopen:
    def __init__(self) -> None:
        self.create_bodies = []
        self.get_calls = 0

    def __call__(self, req, timeout=90):
        url = req.full_url
        if url.endswith(":batchGenerateContent"):
            self.create_bodies.append(json.loads(req.data.decode()))
            return _FakeHTTPResponse({"name": "batches/test-batch", "done": False})
        if url.endswith("/batches/test-batch"):
            self.get_calls += 1
            return _FakeHTTPResponse(
                {
                    "name": "batches/test-batch",
                    "done": True,
                    "response": {
                        "inlinedResponses": {
                            "inlinedResponses": [
                                {
                                    "metadata": {"key": "req-0"},
                                    "response": {
                                        "candidates": [{"content": {"parts": [{"text": "A"}]}}],
                                        "usageMetadata": {
                                            "promptTokenCount": 11,
                                            "cachedContentTokenCount": 7,
                                            "candidatesTokenCount": 1,
                                            "totalTokenCount": 12,
                                        },
                                    },
                                },
                                {
                                    "metadata": {"key": "req-1"},
                                    "response": {
                                        "candidates": [{"content": {"parts": [{"text": "B"}]}}],
                                        "usageMetadata": {
                                            "promptTokenCount": 13,
                                            "candidatesTokenCount": 1,
                                            "totalTokenCount": 14,
                                        },
                                    },
                                },
                            ]
                        }
                    },
                }
            )
        raise AssertionError(f"unexpected URL {url}")


def test_gemini_batch_posts_inline_requests_and_parses_responses(monkeypatch, tmp_path):
    fake = _FakeBatchUrlopen()
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")

    responses = gemini_llm.call_gemini_batch(
        [
            {"system": "system one", "user": "user one", "max_tokens": 17},
            {"system": "system two", "user": "user two", "max_tokens": 19},
        ],
        model="gemini-3.5-flash",
        poll_interval=0,
    )

    assert [r.text for r in responses] == ["A", "B"]
    assert responses[0].usage["input_tokens"] == 11
    assert responses[0].usage["cached_input_tokens"] == 7
    assert responses[1].usage["input_tokens"] == 13
    assert fake.get_calls == 1
    body = fake.create_bodies[0]
    assert body["batch"]["display_name"].startswith("aeread-")
    inline = body["batch"]["input_config"]["requests"]["requests"]
    assert [item["metadata"]["key"] for item in inline] == ["req-0", "req-1"]
    assert inline[0]["request"]["contents"][0]["parts"][0]["text"] == "user one"
    assert inline[0]["request"]["systemInstruction"]["parts"][0]["text"] == "system one"
    assert inline[0]["request"]["generationConfig"]["maxOutputTokens"] == 17


def test_gemini_context_cache_reuses_shared_prompt_prefix(monkeypatch, tmp_path):
    fake = _FakeContextCacheUrlopen()
    marker = "Viewer-specific contact context:"
    shared_prefix = "Round 1.\nShared public context:\n" + ("same public facts\n" * 60)
    user_one = f"{shared_prefix}{marker}\na1 visible rows\nPrivate agent context:\na1"
    user_two = f"{shared_prefix}{marker}\na2 visible rows\nPrivate agent context:\na2"

    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_CONTEXT_CACHE", "1")
    monkeypatch.setenv("GEMINI_CONTEXT_CACHE_MIN_CHARS", "1")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")

    first = gemini_llm.call_gemini("system", user_one, model="gemini-3.5-flash", max_tokens=128)
    second = gemini_llm.call_gemini("system", user_two, model="gemini-3.5-flash", max_tokens=128)

    assert first.text == "OK-1"
    assert second.text == "OK-2"
    assert fake.create_calls == 1
    assert fake.generate_calls == 2
    assert fake.create_bodies[0]["contents"][0]["parts"][0]["text"] == shared_prefix
    assert fake.create_bodies[0]["systemInstruction"]["parts"][0]["text"] == "system"
    assert fake.generate_bodies[0]["cachedContent"] == "cachedContents/shared-prefix"
    assert fake.generate_bodies[1]["cachedContent"] == "cachedContents/shared-prefix"
    assert fake.generate_bodies[0]["contents"][0]["parts"][0]["text"].startswith(marker)
    assert shared_prefix not in fake.generate_bodies[0]["contents"][0]["parts"][0]["text"]
    assert "systemInstruction" not in fake.generate_bodies[0]
    assert first.usage["cached_input_tokens"] == 90
    assert first.usage["context_cache_storage_token_hours"] == 90
    assert "context_cache_storage_token_hours" not in second.usage


def test_gemini_context_cache_create_urlerror_falls_back_to_uncached_call(monkeypatch, tmp_path):
    fake = _FailContextCacheThenGenerateUrlopen()
    marker = "Viewer-specific contact context:"
    shared_prefix = "Round 1.\nShared public context:\n" + ("same public facts\n" * 60)
    user = f"{shared_prefix}{marker}\na1 visible rows\nPrivate agent context:\na1"

    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_CONTEXT_CACHE", "1")
    monkeypatch.setenv("GEMINI_CONTEXT_CACHE_MIN_CHARS", "1")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")

    response = gemini_llm.call_gemini("system", user, model="gemini-3.5-flash", max_tokens=128)

    assert response.text == "OK-without-context-cache"
    assert fake.create_calls == 1
    assert fake.generate_calls == 1
    assert "cachedContent" not in fake.generate_bodies[0]
    assert fake.generate_bodies[0]["contents"][0]["parts"][0]["text"] == user
    assert fake.generate_bodies[0]["systemInstruction"]["parts"][0]["text"] == "system"


def test_gemini_cache_key_distinguishes_completion_budget(monkeypatch, tmp_path):
    fake = _FakeUrlopen()
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")

    first = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=64)
    second = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)

    assert first.text == "max=64 think=0"
    assert second.text == "max=128 think=0"
    assert fake.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_gemini_cache_key_distinguishes_thinking_budget(monkeypatch, tmp_path):
    fake = _FakeUrlopen()
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_DELAY", "0")

    monkeypatch.setenv("GEMINI_THINKING", "0")
    first = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)
    monkeypatch.setenv("GEMINI_THINKING", "32")
    second = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)

    assert first.text == "max=128 think=0"
    assert second.text == "max=128 think=32"
    assert fake.calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_empty_gemini_responses_are_not_cached_as_success(monkeypatch, tmp_path):
    fake = _FakeUrlopen(["", "OK-after-retry"])
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")

    first = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)
    second = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)

    assert first.text == ""
    assert second.text == "OK-after-retry"
    assert fake.calls == 2
    cached_payloads = [path.read_text() for path in tmp_path.glob("*.json")]
    assert len(cached_payloads) == 1
    assert "OK-after-retry" in cached_payloads[0]


def test_gemini_retries_transient_read_timeout(monkeypatch, tmp_path):
    fake = _TimeoutThenSuccessUrlopen()
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")
    monkeypatch.setenv("GEMINI_RETRY_BASE_DELAY", "0")

    response = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)

    assert response.text == "OK-after-timeout"
    assert fake.calls == 2


def test_gemini_retries_transient_http_503(monkeypatch, tmp_path):
    fake = _HTTP503ThenSuccessUrlopen()
    monkeypatch.setattr(gemini_llm, "_CACHE", tmp_path)
    monkeypatch.setattr(gemini_llm.urllib.request, "urlopen", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_DELAY", "0")
    monkeypatch.setenv("GEMINI_THINKING", "0")
    monkeypatch.setenv("GEMINI_RETRY_BASE_DELAY", "0")

    response = gemini_llm.call_gemini("system", "user", model="gemini-3.5-flash", max_tokens=128)

    assert response.text == "OK-after-503"
    assert fake.calls == 2
