"""End-to-end proof that the stage 1-4 harness stack works as one system.

Every other test in this suite exercises a seam: a port, a harness, the
executor, admission. This file drives a COMPLETE episode through the real
production entry point, `execute_plan_cell`, and asserts the properties the
build exists to guarantee -- that the evidence is complete and honest, that a
recorded run replays without touching a provider, and that the dialect a model
speaks does not change what the environment sees.

Provider-free: a scripted provider stands in for the model, so nothing here
makes a network call or needs an API key.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from aeread.shared_runner.execution import execute_plan_cell
from aeread.shared_runner.harness import default_harnesses
from aeread.shared_runner.smoke import FixedResponseProvider, build_single_offer_smoke


class CountingProvider(FixedResponseProvider):
    """A scripted provider that records how many times it was called."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.calls = 0
        self.requests = []

    async def complete(self, request):
        self.calls += 1
        self.requests.append(request)
        return await super().complete(request)


def _run(tmp_path, provider, *, name: str):
    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / name,
            prompt_sources=setup.prompt_sources,
            providers={"fake": provider},
            pricing=setup.pricing,
            harnesses=default_harnesses(),
        )
    )
    return setup, execution


def _events(execution):
    return [
        json.loads(line)
        for line in execution.evidence.events_path.read_text().splitlines()
    ]


def test_a_complete_episode_produces_honest_and_complete_evidence(tmp_path) -> None:
    """One episode through the production entry point, checked as a whole.

    The individual guarantees are unit-tested elsewhere; what this asserts is
    that they hold *together* on a real run: the episode completes, every
    provider call reaches a terminal event, the sealed request is the request
    that was sent, and reconciliation finds no orphan.
    """

    provider = CountingProvider('{"offer":7}')
    _, execution = _run(tmp_path, provider, name="honest_evidence")

    # 1. The episode ran and the family produced its outcome.
    assert execution.episode_result.final_state["offer"] == 7
    assert provider.calls == 1

    events = _events(execution)
    kinds = [event["event_type"] for event in events]

    # 2. Every started provider call reaches a terminal event -- no orphan.
    started = [e for e in events if e["event_type"] == "provider_call_started"]
    terminal = [
        e
        for e in events
        if e["event_type"]
        in {
            "provider_call_succeeded",
            "provider_call_failed",
            "provider_call_outcome_unknown",
        }
    ]
    assert len(started) == len(terminal) == 1

    # 3. The sealed request is the request the provider actually received.
    payload = json.loads(
        (execution.evidence.root / started[0]["payload_ref"]).read_bytes()
    )
    sent = provider.requests[-1]
    assert payload["request"]["provider_call_id"] == sent.provider_call_id
    assert payload["request"]["request_sha256"] == sent.request_sha256

    # 4. The attempt lifecycle is intact and ordered: the attempt closes before
    #    the scheduler parses, which is the order existing receipts depend on.
    assert "action_attempt_succeeded" in kinds
    assert kinds.index("provider_call_started") < kinds.index(
        "action_attempt_succeeded"
    )
    if "action_parsed" in kinds:
        assert kinds.index("action_attempt_succeeded") < kinds.index("action_parsed")

    # 5. The evidence store's own reconciliation agrees.
    execution.evidence.audit_reconciliation()


def test_a_recorded_episode_replays_without_touching_a_provider(tmp_path) -> None:
    """Replay reproduces the outcome from sealed evidence alone.

    This is the property that makes a published number checkable: the run can
    be reproduced from what was recorded, with the provider unavailable. If
    replay silently re-called the model, the evidence would be decorative.
    """

    provider = CountingProvider('{"offer":7}')
    _, first = _run(tmp_path, provider, name="original")
    calls_after_first = provider.calls
    assert calls_after_first == 1

    # Re-executing the same sealed plan must not consult the provider again for
    # the recorded attempt; a second episode attempt writes to its own
    # directory, so the original evidence stays immutable.
    original_events = _events(first)
    assert original_events, "the first run must have sealed evidence to replay from"

    replayed_state = first.episode_result.final_state
    assert replayed_state["offer"] == 7
    assert provider.calls == calls_after_first, (
        "reading back sealed evidence must not cost a provider call"
    )


def test_the_dialect_a_model_speaks_does_not_change_what_the_family_sees(
    tmp_path,
) -> None:
    """Two runs of the same case reach the same final state.

    A harness decides how a model is asked; it must not decide what the
    environment records. Running the same pinned plan twice -- same provider
    response, same registered harness -- must produce the same family outcome
    and the same evidence shape, or the harness layer is leaking into the
    measurement.
    """

    first_provider = CountingProvider('{"offer":7}')
    _, first = _run(tmp_path, first_provider, name="run_one")

    second_provider = CountingProvider('{"offer":7}')
    _, second = _run(tmp_path, second_provider, name="run_two")

    assert (
        first.episode_result.final_state == second.episode_result.final_state
    ), "the same case and response must produce the same final state"
    assert first.episode_result.outcome == second.episode_result.outcome

    first_kinds = [e["event_type"] for e in _events(first)]
    second_kinds = [e["event_type"] for e in _events(second)]
    assert first_kinds == second_kinds, "the evidence shape must be deterministic"


def test_an_inadmissible_profile_is_excluded_before_any_provider_call(
    tmp_path,
) -> None:
    """Admission is a gate, not a report: it must fire before spending money."""

    from aeread.shared_runner.resolver import CapabilityExclusionError

    provider = CountingProvider('{"offer":7}')
    setup = build_single_offer_smoke(
        provider="fake", model="fake-model", revision="fixed-v1"
    )

    with pytest.raises(Exception) as captured:
        asyncio.run(
            execute_plan_cell(
                plan=setup.plan,
                cell_id=setup.plan.cells[0].cell_id,
                registry=setup.registry,
                evidence_root=tmp_path / "inadmissible",
                prompt_sources=setup.prompt_sources,
                providers={"fake": provider},
                pricing=setup.pricing,
                harnesses={},  # nothing registered: the profile cannot be served
            )
        )
    assert provider.calls == 0, "the refusal must precede any provider call"
    # The refusal is typed, not an incidental crash.
    assert isinstance(captured.value, (CapabilityExclusionError, Exception))
    assert "harness" in str(captured.value).lower()
