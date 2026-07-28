"""Deterministic offline tests for the EverOS memory-augmented candidate.

No EverOS server, no LLM provider: the candidate takes an injectable
``llm_fn`` and memory client, and the HTTP client is exercised against an
in-process stub server.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aeread.integrations.everos_memory import (
    EverOSMemory,
    MemoryCandidate,
)


class FakeMemory:
    """Duck-typed EverOSMemory recording every call."""

    def __init__(self, hits: dict | None = None, fail: bool = False):
        self.hits = hits or {}
        self.fail = fail
        self.add_calls: list = []
        self.flush_calls: list = []
        self.search_calls: list = []

    def search(self, query, **kw):
        self.search_calls.append((query, kw))
        if self.fail:
            raise ConnectionError("everos down")
        return self.hits

    def add(self, session_id, messages):
        self.add_calls.append((session_id, messages))
        if self.fail:
            raise ConnectionError("everos down")
        return "accumulated"

    def flush(self, session_id):
        self.flush_calls.append(session_id)
        if self.fail:
            raise ConnectionError("everos down")
        return "extracted"


def make_candidate(memory, responses=None, **kw):
    prompts: list[str] = []
    responses = list(responses or ["PROPOSE trade 2 X for 1 Y"])

    def llm_fn(prompt: str) -> str:
        prompts.append(prompt)
        return responses[min(len(prompts) - 1, len(responses) - 1)]

    cand = MemoryCandidate(llm_fn, memory, clock=lambda: 1_700_000_000.0, **kw)
    return cand, prompts


def test_act_passes_observation_and_returns_llm_text():
    mem = FakeMemory()
    cand, prompts = make_candidate(mem)
    out = cand.act("You are seat 1. Propose a trade.", "proposal")
    assert out == "PROPOSE trade 2 X for 1 Y"
    assert "You are seat 1. Propose a trade." in prompts[0]
    # no hits -> no memory block injected
    assert "PRIOR EXPERIENCE" not in prompts[0]


def test_act_injects_recalled_memories():
    hits = {
        "episodes": [{"summary": "panel concedes to 2:1 when countered"}],
        "agent_cases": [{"title": "case01 lesson",
                         "content": "counter aggressive opening offers"}],
    }
    mem = FakeMemory(hits=hits)
    cand, prompts = make_candidate(mem)
    out = cand.act("Round 2 observation.", "response")
    assert out
    assert "PRIOR EXPERIENCE" in prompts[0]
    assert "panel concedes to 2:1 when countered" in prompts[0]
    assert "counter aggressive opening offers" in prompts[0]
    assert "Round 2 observation." in prompts[0]


def test_search_query_includes_episode_label_and_phase():
    mem = FakeMemory()
    cand, _ = make_candidate(mem)
    cand.begin_episode("case01_visible_bilateral_ir-s1200")
    cand.act("obs text", "proposal")
    assert mem.search_calls, "act() must consult memory"
    query = mem.search_calls[0][0]
    assert "case01_visible_bilateral_ir" in query
    assert "proposal" in query


def test_end_episode_posts_transcript_and_flushes():
    mem = FakeMemory()
    cand, _ = make_candidate(mem, responses=["counter 2:1", "accept"])
    cand.begin_episode("case01-s7")
    cand.act("obs one", "proposal")
    cand.act("obs two", "response")
    cand.end_episode("AER=0.42 (w_real=1.1 denominator=2.6)")

    assert len(mem.add_calls) == 1
    session_id, msgs = mem.add_calls[0]
    assert session_id == cand.session_id
    assert "case01-s7" in session_id
    # 2 observation turns + 2 assistant turns + 1 reflection
    assert len(msgs) == 5
    assert [m["role"] for m in msgs] == [
        "user", "assistant", "user", "assistant", "assistant"]
    assert msgs[0]["sender_id"] == cand.arena_user_id
    assert msgs[1]["sender_id"] == cand.agent_id
    assert "AER=0.42" in msgs[-1]["content"]
    ts = [m["timestamp"] for m in msgs]
    assert all(isinstance(t, int) for t in ts)
    assert all(t > 10 ** 12 for t in ts), "timestamps must be epoch ms"
    assert ts == sorted(ts) and len(set(ts)) == len(ts), "strictly increasing"
    assert mem.flush_calls == [session_id]


def test_memory_failure_is_nonfatal():
    mem = FakeMemory(fail=True)
    cand, _ = make_candidate(mem)
    out = cand.act("obs", "proposal")
    assert out == "PROPOSE trade 2 X for 1 Y"
    cand.end_episode("AER=0.0")  # must not raise
    assert cand.memory_errors >= 2


def test_begin_episode_resets_buffer_and_session():
    mem = FakeMemory()
    cand, _ = make_candidate(mem)
    cand.begin_episode("case01-s1")
    cand.act("obs", "proposal")
    first_session = cand.session_id
    cand.begin_episode("case01-s2")
    assert cand.session_id != first_session
    cand.end_episode("AER=0.1")
    _, msgs = mem.add_calls[0]
    assert len(msgs) == 1, "only the reflection: buffer was reset"


# ---------------------------------------------------------------------------
# HTTP client against an in-process stub server
# ---------------------------------------------------------------------------

class _StubHandler(BaseHTTPRequestHandler):
    calls: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append((self.path, body))
        if self.path.endswith("/memory/search"):
            data = {"episodes": [{"summary": "s1"}], "profiles": [],
                    "agent_cases": [], "agent_skills": [],
                    "unprocessed_messages": []}
        elif self.path.endswith("/memory/add"):
            data = {"message_count": len(body["messages"]),
                    "status": "accumulated"}
        else:
            data = {"status": "extracted"}
        payload = json.dumps({"request_id": "t", "data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):  # noqa: ARG002 - silence test output
        pass


@pytest.fixture()
def stub_server():
    _StubHandler.calls = []
    srv = HTTPServer(("127.0.0.1", 0), _StubHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_client_add_flush_search_round_trip(stub_server):
    client = EverOSMemory(stub_server, app_id="aeread", project_id="case01")
    status = client.add("sess-1", [{"sender_id": "arena", "role": "user",
                                    "timestamp": 1_700_000_000_000,
                                    "content": "hi"}])
    assert status == "accumulated"
    assert client.flush("sess-1") == "extracted"
    data = client.search("query text", user_id="arena", top_k=3)
    assert data["episodes"][0]["summary"] == "s1"

    paths = [p for p, _ in _StubHandler.calls]
    assert paths == ["/api/v2/memory/add", "/api/v2/memory/flush",
                     "/api/v2/memory/search"]
    add_body = _StubHandler.calls[0][1]
    assert add_body["app_id"] == "aeread"
    assert add_body["project_id"] == "case01"
    search_body = _StubHandler.calls[2][1]
    assert search_body["user_id"] == "arena"
    assert search_body["method"] == "vector"
    assert search_body["top_k"] == 3


def test_client_search_requires_exactly_one_scope(stub_server):
    client = EverOSMemory(stub_server)
    with pytest.raises(ValueError):
        client.search("q")
    with pytest.raises(ValueError):
        client.search("q", user_id="u", agent_id="a")
