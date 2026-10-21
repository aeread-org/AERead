"""Failed settlement enforces accumulated profile budgets without losing facts."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from aeread.shared_runner import attempt_spend
from aeread.shared_runner.model_call.harness import AttemptExecutor, CanonicalMessage, HarnessOutput, MinimalChatHarness
from aeread.shared_runner.task.execution import EvidenceIntegrityError, MinimalChatExecutor, ProviderFailure, failed_call_cost
from tests.test_shared_runner_execution import FAKE_PRICING, SYSTEM_PROMPT, _decision, _evidence, _profile, _success_result
from tests.test_shared_runner_harness import ScriptedProvider


def billed(condition="provider_5xx", *, cost=0.25, retryable=True, usage=None):
    return ProviderFailure(condition, "synthetic paid failure", retryable=retryable,
                           status_code=503 if condition == "provider_5xx" else None).with_reported_usage(
        {"choices": [{"index": 0}], "usage": {"cost": cost} if usage is None else usage})


class Rounds(MinimalChatHarness):
    """A real model-port loop; each action declares its synthetic round count."""
    async def act(self, request, ctx):
        count = request.observation.get("rounds", 1)
        for _ in range(count):
            await ctx.model.complete(messages=(CanonicalMessage(role="user", content="fixture"),), response_mode="text")
        return HarnessOutput(action=None, claimed_tool_calls=(), rounds_used=count, notes={})


def make_executor(tmp_path, outcomes, *, cap=0.125, attempts=3, conditions=("provider_5xx", "length", "timeout"), harness=False, profiles=None):
    profile = _profile(max_cost_usd=cap, max_action_attempts=attempts, retryable_conditions=conditions)
    evidence = _evidence(tmp_path)
    provider = ScriptedProvider(outcomes)
    kwargs = dict(evidence=evidence, profiles=profiles or [profile],
                  prompt_sources={profile.prompt.prompt_id: SYSTEM_PROMPT}, providers={"fake": provider},
                  pricing={"fake-model": FAKE_PRICING})
    executor = AttemptExecutor(**kwargs, harnesses={"minimal_chat/1.0": Rounds()}) if harness else MinimalChatExecutor(**kwargs)
    return executor, provider, evidence


def payloads(evidence, kind):
    return [evidence.read_event_payload(e) for e in evidence.read_events() if e.event_type == kind]


@pytest.mark.parametrize("harness", [False, True])
@pytest.mark.parametrize("condition,retryable,attempts", [("provider_5xx", True, 3), ("provider_contract", False, 3), ("provider_5xx", True, 1), ("length", True, 3)])
def test_first_overrun_terminalizes_once_before_retry_or_growth(tmp_path, monkeypatch, harness, condition, retryable, attempts):
    failure = billed(condition, retryable=retryable)
    executor, provider, evidence = make_executor(tmp_path, [failure], harness=harness, attempts=attempts)
    async def no_backoff(**kwargs):
        pytest.fail("over-budget failure entered backoff")
    monkeypatch.setattr(executor, "_wait_before_provider_retry", no_backoff)
    monkeypatch.setattr(executor, "_grow_length_budget", lambda *_: pytest.fail("over-budget failure grew length"))
    with pytest.raises(EvidenceIntegrityError, match="cost budget exceeded") as caught:
        asyncio.run(executor(_decision()))
    assert caught.value.__cause__ is failure
    assert (failure.condition, failure.retryable, failure.cost_usd) == (condition, retryable, 0.25)
    assert len(provider.requests) == 1
    assert executor.total_cost_usd == executor._cost_by_profile[_decision().profile_id] == 0.25
    execution = executor._executions[_decision().logical_action_id]
    assert execution.status == "failed" and execution.failure_code == "cost_budget_exceeded"
    assert len(execution.attempts) == len(execution.attempts[0].provider_calls) == 1
    record = execution.attempts[0].provider_calls[0]
    assert record.failure_condition == condition and record.cost_usd == 0.25
    failed = payloads(evidence, "provider_call_failed")
    assert len(failed) == 1 and failed[0]["failure_condition"] == condition
    assert failed[0]["cost_usd"] == 0.25
    attempt = payloads(evidence, "action_attempt_failed")
    assert attempt == [{"failure_condition": "cost_budget_exceeded", "profile_cost_usd": 0.25, "max_cost_usd": 0.125,
                        "triggering_failure": {"original_condition": condition, "effective_condition": condition,
                                               "message": str(failure), "retryable": retryable,
                                               "status_code": failure.status_code, "billing": "reported",
                                               "reported_cost_usd": 0.25, "settled_failed_call_cost_usd": 0.25}}]
    assert len(payloads(evidence, "logical_action_failed")) == 1
    kinds = [e.event_type for e in evidence.read_events()]
    assert kinds.index("provider_call_failed") < kinds.index("action_attempt_failed") < kinds.index("logical_action_failed")
    assert attempt_spend(evidence).cost_usd == 0.25
    evidence.audit_reconciliation()
    evidence.close()
    assert attempt_spend(tmp_path / "evidence").cost_usd == 0.25


@pytest.mark.parametrize("harness", [False, True])
@pytest.mark.parametrize("cap", [0.5, 0.25, None])
def test_below_equal_and_unlimited_keep_retry_eligibility(tmp_path, harness, cap):
    executor, provider, evidence = make_executor(tmp_path, [billed(), _success_result(cost=0)], cap=cap, harness=harness)
    asyncio.run(executor(_decision()))
    assert len(provider.requests) == 2
    assert executor.total_cost_usd == 0.25
    assert payloads(evidence, "action_attempt_failed") == [{"failure_condition": "provider_5xx"}]
    assert len(payloads(evidence, "action_attempt_succeeded")) == 1
    assert executor._executions[_decision().logical_action_id].status == "awaiting_action_result"


def test_exact_cap_allows_one_more_attempt_then_stops_crossing(tmp_path):
    executor, provider, evidence = make_executor(tmp_path, [billed(), billed()], cap=0.25)
    with pytest.raises(EvidenceIntegrityError):
        asyncio.run(executor(_decision()))
    assert len(provider.requests) == 2 and executor.total_cost_usd == 0.5
    assert len(payloads(evidence, "action_attempt_failed")) == 2
    assert len(payloads(evidence, "logical_action_failed")) == 1


@pytest.mark.parametrize("final", ["zero", "unknown"])
def test_prior_action_and_round_are_settled_once_even_without_final_charge(tmp_path, final):
    failure = billed(cost=0) if final == "zero" else billed(usage={"prompt_tokens": -1})
    executor, provider, evidence = make_executor(tmp_path, [_success_result(cost=0.40), _success_result(cost=0.70), failure], cap=1, harness=True)
    first = replace(_decision(), logical_action_id="logical_action_previous")
    asyncio.run(executor(first))
    executor.finalize_logical_action(first.logical_action_id, valid=True, failure_code=None)
    with pytest.raises(EvidenceIntegrityError) as caught:
        asyncio.run(executor(replace(_decision(), observation={"rounds": 2})))
    assert caught.value.__cause__ is failure
    assert len(provider.requests) == 3
    assert executor.total_cost_usd == pytest.approx(1.1)
    assert executor._cost_by_profile[_decision().profile_id] == pytest.approx(1.1)
    current = executor._executions[_decision().logical_action_id]
    assert [r.cost_usd for r in current.attempts[0].provider_calls] == [0.70, 0]
    stop = payloads(evidence, "action_attempt_failed")[0]
    assert stop["profile_cost_usd"] == pytest.approx(1.1)
    assert stop["triggering_failure"]["settled_failed_call_cost_usd"] == (0 if final == "zero" else None)
    spend = attempt_spend(evidence)
    assert spend.cost_usd == pytest.approx(1.1)
    assert spend.cost_accounting == ("exact" if final == "zero" else "lower_bound")
    assert spend.provider_call_count == 3
    evidence.audit_reconciliation()


def test_prior_attempt_rounds_are_neither_omitted_nor_charged_twice(tmp_path):
    executor, provider, evidence = make_executor(tmp_path, [_success_result(cost=0.4), billed(cost=0), _success_result(cost=0.7), billed(cost=0)], cap=1, harness=True)
    with pytest.raises(EvidenceIntegrityError):
        asyncio.run(executor(replace(_decision(), observation={"rounds": 2})))
    assert len(provider.requests) == 4 and executor.total_cost_usd == pytest.approx(1.1)
    assert len(executor._executions[_decision().logical_action_id].attempts) == 2
    assert attempt_spend(evidence).cost_usd == pytest.approx(1.1)


def test_caps_are_per_profile_even_when_route_and_executor_are_shared(tmp_path):
    one = _profile(max_cost_usd=0.4)
    two = replace(one, profile_id="second_profile")
    executor, provider, evidence = make_executor(tmp_path, [_success_result(cost=0.25), billed(cost=0.25, retryable=False)], profiles=[one, two])
    asyncio.run(executor(_decision()))
    with pytest.raises(ProviderFailure):
        asyncio.run(executor(replace(_decision(), profile_id=two.profile_id, logical_action_id="second_action")))
    assert executor.total_cost_usd == 0.5
    assert executor._cost_by_profile == {one.profile_id: 0.25, two.profile_id: 0.25}
    assert payloads(evidence, "action_attempt_failed") == [{"failure_condition": "provider_5xx"}]


@pytest.mark.parametrize("usage,expected,qualifier", [({"cost": 0.25}, 0.25, "exact"), ({"cost": 0}, 0, "exact"),
    ({"prompt_tokens": 20, "completion_tokens": 5}, 0.000003, "exact"), ({}, None, "lower_bound"),
    ({"prompt_tokens": 20}, None, "lower_bound"), (None, None, "lower_bound"),
    ({"prompt_tokens": -1, "cost": 0.25}, 0.25, "exact"),
    # The cache breakdown is optional: unreported means full-rate input, not unknown usage.
    ({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": None}, 0.000003, "exact"),
    ({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {}}, 0.000003, "exact"),
    ({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": None}}, 0.000003, "exact"),
    ({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {"audio_tokens": 0}}, 0.000003, "exact"),
    ({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": -3}}, None, "lower_bound")])
def test_existing_usage_and_missingness_qualifications_are_preserved(tmp_path, usage, expected, qualifier):
    failure = ProviderFailure("provider_contract", "usage fixture", retryable=False).with_reported_usage({"choices": [1], "usage": usage})
    executor, provider, evidence = make_executor(tmp_path, [failure], cap=None)
    with pytest.raises(ProviderFailure) as caught:
        asyncio.run(executor(_decision()))
    assert caught.value is failure
    cost = failed_call_cost(failure, FAKE_PRICING)
    assert cost == pytest.approx(expected) if expected is not None else cost is None
    spend = attempt_spend(evidence)
    assert spend.cost_usd == pytest.approx(expected or 0)
    assert spend.cost_accounting == qualifier


def test_outcome_unknown_keeps_disk_lower_bound_while_budget_uses_known_charge(tmp_path):
    failure = billed("timeout")
    executor, provider, evidence = make_executor(tmp_path, [failure])
    with pytest.raises(EvidenceIntegrityError) as caught:
        asyncio.run(executor(_decision()))
    assert caught.value.__cause__ is failure
    assert executor.total_cost_usd == 0.25
    assert attempt_spend(evidence).cost_usd == 0.25
    assert attempt_spend(evidence).cost_accounting == "lower_bound"
    assert len(payloads(evidence, "provider_call_outcome_unknown")) == 1


@pytest.mark.parametrize("terminal", ["provider_call_failed", "action_attempt_failed", "logical_action_failed"])
def test_evidence_write_failure_propagates_and_keeps_only_written_prefix(tmp_path, monkeypatch, terminal):
    executor, provider, evidence = make_executor(tmp_path, [billed()])
    append = evidence.append_event
    write_error = OSError("synthetic write failure")
    def fail_selected(kind, *args, **kwargs):
        if kind == terminal:
            raise write_error
        return append(kind, *args, **kwargs)
    monkeypatch.setattr(evidence, "append_event", fail_selected)
    with pytest.raises(OSError) as caught:
        asyncio.run(executor(_decision()))
    assert caught.value is write_error
    assert executor.total_cost_usd == 0.25 and len(provider.requests) == 1
    kinds = [e.event_type for e in evidence.read_events()]
    assert terminal not in kinds
    assert "logical_action_failed" not in kinds
    assert len(payloads(evidence, "action_attempt_failed")) == (1 if terminal == "logical_action_failed" else 0)


@pytest.mark.parametrize("harness", [False, True])
def test_cancellation_keeps_its_existing_unknown_outcome_and_propagates(tmp_path, harness):
    executor, provider, evidence = make_executor(tmp_path, [asyncio.CancelledError()], harness=harness)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor(_decision()))
    assert len(provider.requests) == 1 and executor.total_cost_usd == 0
    assert len(payloads(evidence, "provider_call_outcome_unknown")) == 1
    assert not payloads(evidence, "action_attempt_failed")
    assert attempt_spend(evidence).cost_accounting == "lower_bound"


@pytest.mark.parametrize("harness", [False, True])
def test_within_budget_length_growth_and_ceiling_stay_declared(tmp_path, harness):
    executor, provider, evidence = make_executor(tmp_path, [billed("length", cost=0)] * 5, cap=1, attempts=5, harness=harness)
    with pytest.raises(ProviderFailure) as caught:
        asyncio.run(executor(_decision()))
    assert caught.value.condition == "length"
    assert [r.max_output_tokens for r in provider.requests] == [80, 160, 320, 640]
    assert executor.total_cost_usd == 0
    assert len(payloads(evidence, "action_attempt_failed")) == 4
    assert len(payloads(evidence, "logical_action_failed")) == 1


def test_within_budget_nonretryable_and_exhausted_failures_keep_original_error(tmp_path):
    failure = billed("provider_5xx", cost=0, retryable=True)
    executor, provider, evidence = make_executor(tmp_path, [failure], cap=1, attempts=1)
    with pytest.raises(ProviderFailure) as caught:
        asyncio.run(executor(_decision()))
    assert caught.value is failure
    assert payloads(evidence, "action_attempt_failed") == [{"failure_condition": "provider_5xx"}]


def test_budget_diagnostics_keep_original_and_existing_effective_route_condition(tmp_path):
    failure = ProviderFailure("provider_rejected", "synthetic post-admission 404", retryable=False, status_code=404).with_reported_usage({"choices": [1], "usage": {"cost": 0.25}})
    executor, provider, evidence = make_executor(tmp_path, [_success_result(cost=0), failure])
    asyncio.run(executor(replace(_decision(), logical_action_id="route_proof")))
    with pytest.raises(EvidenceIntegrityError) as caught:
        asyncio.run(executor(_decision()))
    assert caught.value.__cause__ is failure
    diagnostic = payloads(evidence, "action_attempt_failed")[0]["triggering_failure"]
    assert diagnostic["original_condition"] == failure.condition == "provider_rejected"
    assert diagnostic["effective_condition"] == "provider_rejected_after_route_proven"
    assert diagnostic["retryable"] is False
    assert payloads(evidence, "provider_call_failed")[0]["failure_condition"] == "provider_rejected_after_route_proven"


def test_cancelled_later_round_settles_completed_round_once_without_new_budget_policy(tmp_path):
    executor, provider, evidence = make_executor(tmp_path, [_success_result(cost=0.25), asyncio.CancelledError()], harness=True)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor(replace(_decision(), observation={"rounds": 2})))
    assert executor.total_cost_usd == 0.25 and len(provider.requests) == 2
    assert attempt_spend(evidence).cost_usd == 0.25
    assert attempt_spend(evidence).cost_accounting == "lower_bound"
    assert not payloads(evidence, "action_attempt_failed")

@pytest.mark.parametrize("usage", [{"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 21}}, {"completion_tokens": 5}, {"prompt_tokens": True, "completion_tokens": 0},
    *({"prompt_tokens": 20, "completion_tokens": 5, "prompt_tokens_details": details}
      for details in ({"cached_tokens": -3}, {"cached_tokens": "4"}, {"cached_tokens": 1.5}, {"cached_tokens": True}, "4"))])
def test_invalid_or_partial_tokens_do_not_support_price_fallback(tmp_path, usage):
    failure = billed(usage=usage)
    assert failed_call_cost(failure, FAKE_PRICING) is None


def test_timeout_known_fee_is_additive_and_stays_unsettled(tmp_path):
    failure = billed("timeout")
    executor, provider, evidence = make_executor(tmp_path, [failure])
    with pytest.raises(EvidenceIntegrityError):
        asyncio.run(executor(_decision()))
    terminal = payloads(evidence, "provider_call_outcome_unknown")[0]
    assert terminal["cost_usd"] == "unknown"
    assert terminal["known_cost_usd"] == 0.25
    assert terminal["cost_accounting"] == "lower_bound"
    spend = attempt_spend(evidence)
    assert spend.cost_usd == 0.25 and spend.unsettled_call_count == 1
    assert spend.cost_accounting == "lower_bound"
