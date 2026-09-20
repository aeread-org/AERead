"""Decision/payload boundary and saved-attempt replay for the diagnostic."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import urllib.error

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("information_pilot", TOOLS / "run_procurement_information_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
CASES = pilot.load_cases()


def answer(action, quantities=None):
    return json.dumps(dict(action=action, quantities=quantities or {}, explanation="Test decision"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_payload_excludes_labels_and_gold(case):
    payload = pilot.encoded(pilot.request_for(case)).decode()
    for forbidden in (case["id"], '"mechanism"', 'expected_best_actions', 'expected_incremental_value_usd'):
        assert forbidden not in payload
    assert pilot.strategy_text() in pilot.request_for(case)["messages"][0]["content"]


def test_research_option_value_and_eligibility():
    assert pilot.grade(CASES[0], answer("quote_A"))["decision_loss_usd"] == 0
    assert pilot.grade(CASES[0], answer("quote_B"))["decision_loss_usd"] == 3.6
    assert pilot.grade(CASES[0], answer("award_A"))["status"] == "illegal_action"
    assert pilot.grade(CASES[0], answer("defer"))["decision_loss_usd"] == 21


def test_allocation_is_constructed_and_validated():
    assert pilot.grade(CASES[8], answer("award", {"A": 12, "B": 8}))["optimal"]
    assert pilot.grade(CASES[8], answer("award", {"C": 20}))["decision_loss_usd"] == 12.8
    assert pilot.grade(CASES[8], answer("award", {"A": 20}))["status"] == "illegal_action"
    assert pilot.grade(CASES[11], answer("award", {"A": 10, "B": 10, "C": 10, "D": 10}))["status"] == "illegal_action"
    assert pilot.grade(CASES[8], answer("award", {"A": True}))["status"] == "illegal_action"
    assert pilot.grade(CASES[8], answer("defer", {"C": 20}))["status"] == "illegal_action"


def test_missingness_and_malformed_are_not_zero_regret():
    for content in (None, "", "{}", "[]", '{"action":"defer"}'):
        result = pilot.grade(CASES[0], content)
        assert result == dict(status="malformed", decision_loss_usd=None)


def endpoint():
    return {"data": {"endpoints": [{"provider_name": pilot.PROVIDER,
            "pricing": {"prompt": str(pilot.PRICE_INPUT), "completion": str(pilot.PRICE_OUTPUT)}}]}}


def fake_network(monkeypatch, provider_error=False):
    calls = []
    def open_url(request, timeout):
        if isinstance(request, str):
            return io.BytesIO(json.dumps(endpoint()).encode())
        calls.append(json.loads(request.data))
        if provider_error:
            raise urllib.error.HTTPError(pilot.API, 503, "Unavailable", {}, io.BytesIO(b"Unavailable"))
        response = {"model": pilot.MODEL, "provider": pilot.PROVIDER, "id": f"fake_{len(calls)}",
                    "usage": {"cost": .001}, "choices": [{"message": {"content": answer("defer")},
                                                           "finish_reason": "stop"}]}
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(pilot.urllib.request, "urlopen", open_url)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    return calls


def test_full_mock_run_replays_and_cannot_restart(tmp_path, monkeypatch):
    calls = fake_network(monkeypatch)
    directory = tmp_path / "run"
    pilot.prepare(directory)
    pilot.execute(directory)
    assert len(calls) == 12
    result = json.loads((directory / "result.json").read_text())
    assert result == pilot.replay(directory)
    assert result["optimal_decisions"] == 1  # Always defer does not pass the panel.
    assert result["status_counts"] == {"valid": 12}
    assert result["reported_cost_usd"] == "0.012"
    with pytest.raises(RuntimeError, match="restarted"):
        pilot.execute(directory)
    receipt_path = directory / "decision_01.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["final_content"] = answer("quote_A")
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(AssertionError):
        pilot.replay(directory)


def test_provider_failure_stops_without_retry_and_retains_reserve(tmp_path, monkeypatch):
    calls = fake_network(monkeypatch, provider_error=True)
    directory = tmp_path / "run"
    pilot.prepare(directory)
    pilot.execute(directory)
    assert len(calls) == 1
    result = pilot.replay(directory)
    assert result["status_counts"] == {"provider_failure": 1, "unattempted": 11}
    assert result["reported_cost_usd"] == "0"
    assert pilot.number(result["unknown_charge_reserve_usd"]) > 0
    assert result["rows"][0]["decision_loss_usd"] is None


def test_interrupted_request_is_unknown_not_unattempted(tmp_path, monkeypatch):
    fake_network(monkeypatch)
    directory = tmp_path / "run"
    pilot.prepare(directory)
    request = pilot.read_plan(directory)["rows"][0]["request"]
    pilot.save_new(directory / "decision_01.request.json", request)
    result = pilot.replay(directory)
    assert result["status_counts"] == {"interrupted_unknown": 1, "unattempted": 11}
    assert pilot.number(result["unknown_charge_reserve_usd"]) > 0
