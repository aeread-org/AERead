"""Housing's failure reader delegates settlement and missingness to the kernel."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from aeread.shared_runner import attempt_spend
from aeread.shared_runner.run.layout import RunLayout
from aeread.shared_runner.task.execution import EvidenceIntegrityError, EvidenceStore, ProviderFailure
from aeread_families.housing.population_campaign import _failure_usage
from tests.test_shared_runner_execution import _decision, _executor, _profile, _success_result
from tests.test_shared_runner_harness import ScriptedProvider


def store(tmp_path):
    root = RunLayout(tmp_path, "runplan_fixture").attempt_dir("cell_fixture", "episode_attempt_fixture_0")
    return EvidenceStore(root, run_plan_id="runplan_fixture", cell_id="cell_fixture",
                         episode_id="episode_fixture", episode_attempt_id="episode_attempt_fixture_0")


def usage(tmp_path):
    return _failure_usage(evidence_root=tmp_path, run_plan_id="runplan_fixture", cell_id="cell_fixture")


def failure(*, condition="provider_contract", raw_usage=None):
    return ProviderFailure(condition, "synthetic failure", retryable=False).with_reported_usage(
        {"choices": [1], "usage": raw_usage})


@pytest.mark.parametrize("sealed", [False, True])
def test_paid_failed_call_and_tokens_are_read_even_without_a_receipt(tmp_path, sealed):
    evidence = store(tmp_path)
    paid = failure(raw_usage={"cost": 0.25, "prompt_tokens": 40, "completion_tokens": 10})
    provider = ScriptedProvider([paid])
    executor = _executor(tmp_path, provider, evidence=evidence, profile=_profile(max_cost_usd=None))
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    if sealed:
        evidence.seal()
    evidence.close()
    assert usage(tmp_path) == {"cost_usd": 0.25, "provider_calls": 1,
                               "input_tokens": 40, "output_tokens": 10, "cost_accounting": "exact"}
    assert not list(tmp_path.rglob("evaluation_receipt.json"))


def test_mixed_failed_and_token_priced_success_uses_settled_terminal_cost(tmp_path):
    evidence = store(tmp_path)
    provider = ScriptedProvider([_success_result(cost=None), failure(raw_usage={"cost": 0.25, "prompt_tokens": 40, "completion_tokens": 10})])
    executor = _executor(tmp_path, provider, evidence=evidence, profile=_profile(max_cost_usd=None))
    prior = replace(_decision(), logical_action_id="prior_action")
    asyncio.run(executor(prior))
    executor.finalize_logical_action(prior.logical_action_id, valid=True, failure_code=None)
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    expected = attempt_spend(evidence)
    evidence.close()
    result = usage(tmp_path)
    assert result == {"cost_usd": expected.cost_usd, "provider_calls": 2,
                      "input_tokens": 60, "output_tokens": 15, "cost_accounting": "exact"}
    assert result["cost_usd"] == pytest.approx(0.250003)


@pytest.mark.parametrize("condition,raw_usage", [("timeout", {"cost": 0.25}),
    ("provider_contract", None), ("provider_contract", {"prompt_tokens": -1})])
def test_unknown_outcomes_and_unusable_usage_keep_lower_bound(tmp_path, condition, raw_usage):
    evidence = store(tmp_path)
    provider = ScriptedProvider([failure(condition=condition, raw_usage=raw_usage)])
    executor = _executor(tmp_path, provider, evidence=evidence, profile=_profile(max_cost_usd=None))
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(_decision()))
    evidence.close()
    assert usage(tmp_path) == {"cost_usd": 0.25 if condition == "timeout" else 0.0, "provider_calls": 1, "input_tokens": 0,
                               "output_tokens": 0, "cost_accounting": "lower_bound"}


def test_open_call_is_read_without_requiring_reconciliation(tmp_path):
    evidence = store(tmp_path)
    evidence.append_event("provider_call_started", {"request": None}, provider_call_id="unclosed_call")
    evidence.close()
    assert usage(tmp_path) == {"cost_usd": 0.0, "provider_calls": 1, "input_tokens": 0,
                               "output_tokens": 0, "cost_accounting": "lower_bound"}


@pytest.mark.parametrize("count", [0, 2])
def test_absent_and_ambiguous_attempts_keep_numeric_fallback_with_unknown_qualification(tmp_path, count):
    layout = RunLayout(tmp_path, "runplan_fixture")
    for index in range(count):
        layout.attempt_dir("cell_fixture", f"attempt_{index}").mkdir(parents=True)
    assert usage(tmp_path) == {"cost_usd": 0.0, "provider_calls": 0, "input_tokens": 0,
                               "output_tokens": 0, "cost_accounting": "lower_bound"}


@pytest.mark.parametrize("malformed", [False, True])
def test_identified_missing_or_malformed_evidence_propagates(tmp_path, malformed):
    root = RunLayout(tmp_path, "runplan_fixture").attempt_dir("cell_fixture", "one_attempt")
    root.mkdir(parents=True)
    if malformed:
        (root / "events.jsonl").write_text("not-json\n")
    with pytest.raises(EvidenceIntegrityError):
        usage(tmp_path)
