"""The TERMS-Bench live setup (#92): one model seat, one scripted seat.

These tests never reach a provider. They hold the plan the live panel will
resolve -- the agent is the only profile, the counterpart is the kernel's
scripted seat and the block's control -- and the harness's contract: the
model's JSON object reaches the family unchanged, and the only conditions
the harness raises are route faults, never a judgment on the move.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from aeread.shared_runner.task.execution import ProviderFailure
from aeread_families.termsbench.environment import AGENT_PHASE, COUNTERPART_PHASE, TermsBenchPlugin
from aeread_families.termsbench.live import (
    AGENT_SEAT,
    COUNTERPART_SEAT,
    MAX_ROUNDS,
    REASONING_DECLARATION,
    TermsBenchJsonHarness,
    build_live_setup,
    load_case,
)

OVERLAP_CASE_ID = "termsbench.candid.overlap.1000001"
NODEAL_CASE_ID = "termsbench.candid.nodeal.1010011"
POLICY = TermsBenchPlugin.COUNTERPART_POLICY_ID


@pytest.mark.parametrize("case_id", [OVERLAP_CASE_ID, NODEAL_CASE_ID])
def test_the_plan_seats_a_model_agent_against_the_scripted_counterpart(case_id: str) -> None:
    setup = build_live_setup(case_id=case_id, seed=300, max_trajectory_cost_usd=0.05)
    assert len(setup.plan.cells) == 1
    cell = setup.plan.cells[0]
    (profile,) = setup.plan.agent_profiles
    assert dict(cell.profile_by_seat) == {AGENT_SEAT: profile.profile_id}
    assert dict(cell.scripted_seats) == {COUNTERPART_SEAT: POLICY}
    # The scripted counterpart is the block's control, never a subject.
    (block,) = setup.plan.evaluation_blocks
    assert block.subject_seats == (AGENT_SEAT,)
    assert dict(block.controlled_profiles) == {COUNTERPART_SEAT: POLICY}
    # The profile's action budget is the case's own, not a tighter number.
    assert profile.budgets.max_logical_actions == load_case(case_id).episode.max_logical_actions


def test_the_profile_freezes_every_limit_that_can_end_a_turn() -> None:
    setup = build_live_setup(case_id=OVERLAP_CASE_ID, seed=300, max_trajectory_cost_usd=0.05)
    (profile,) = setup.plan.agent_profiles
    assert profile.harness.config["max_rounds"] == MAX_ROUNDS == 1
    assert profile.reasoning.condition_id == REASONING_DECLARATION["condition_id"]
    assert profile.reasoning.effort is None and profile.reasoning.token_budget == 1500
    assert "empty_response" in profile.retry_policy.retryable_conditions
    assert profile.retry_policy.max_action_attempts == 10
    route = profile.harness.config["provider_metadata"]
    assert set(route) == {
        "route_provider",
        "quantization",
        "canonical_model",
        "max_prompt_price_per_million",
        "max_completion_price_per_million",
    }


def test_the_plan_identity_is_a_function_of_its_inputs() -> None:
    a = build_live_setup(case_id=OVERLAP_CASE_ID, seed=300, max_trajectory_cost_usd=0.05)
    b = build_live_setup(case_id=OVERLAP_CASE_ID, seed=300, max_trajectory_cost_usd=0.05)
    c = build_live_setup(case_id=NODEAL_CASE_ID, seed=300, max_trajectory_cost_usd=0.05)
    assert a.plan.plan_sha256 == b.plan.plan_sha256
    assert a.plan.plan_sha256 != c.plan.plan_sha256


def _request(*, phase_id: str = AGENT_PHASE, seat_id: str = AGENT_SEAT) -> SimpleNamespace:
    return SimpleNamespace(
        phase_id=phase_id,
        seat_id=seat_id,
        role=seat_id,
        observation_schema="termsbench_agent_observation_v1",
        action_schema="termsbench_agent_action_v1",
        observation={"role": "buyer", "round": 0},
    )


def _ctx(text: str) -> SimpleNamespace:
    calls: list[dict] = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=text)

    return SimpleNamespace(model=SimpleNamespace(complete=complete), calls=calls)


def test_the_harness_hands_the_model_s_object_to_the_family_unchanged() -> None:
    move = {"decision": "offer", "price": 101.5, "message": "opening"}
    ctx = _ctx(json.dumps(move))
    output = asyncio.run(TermsBenchJsonHarness().act(_request(), ctx))
    assert output.action == move
    assert output.rounds_used == 1
    assert len(ctx.calls) == 1 and ctx.calls[0]["response_mode"] == "json_dialect"


def test_a_protocol_breaking_move_is_not_the_harness_s_to_judge() -> None:
    # A price on an accept is `price_forbidden_for_non_offer` in the family's
    # parse_action, and a measured agreement violation there. The harness
    # must pass it through rather than re-prompt or reject.
    move = {"decision": "accept", "price": 90.0, "message": "deal"}
    output = asyncio.run(TermsBenchJsonHarness().act(_request(), _ctx(json.dumps(move))))
    assert output.action == move


@pytest.mark.parametrize(
    ("text", "condition", "retryable"),
    [
        ("", "empty_response", True),
        ("   \n", "empty_response", True),
        ("I offer 100", "malformed_structured_output", False),
        ("[1, 2]", "malformed_structured_output", False),
    ],
)
def test_route_faults_are_typed_conditions(text: str, condition: str, retryable: bool) -> None:
    with pytest.raises(ProviderFailure) as excinfo:
        asyncio.run(TermsBenchJsonHarness().act(_request(), _ctx(text)))
    assert excinfo.value.condition == condition
    assert excinfo.value.retryable is retryable


def test_the_counterpart_phase_never_reaches_the_model() -> None:
    ctx = _ctx(json.dumps({"decision": "offer", "price": 1.0, "message": ""}))
    with pytest.raises(ProviderFailure) as excinfo:
        asyncio.run(
            TermsBenchJsonHarness().act(
                _request(phase_id=COUNTERPART_PHASE, seat_id=COUNTERPART_SEAT), ctx
            )
        )
    assert excinfo.value.condition == "harness_contract"
    assert ctx.calls == []


# --- offline end to end: the live plan, a fake route, the real kernel -------

from pathlib import Path  # noqa: E402

from aeread.shared_runner.run.resolver import canonical_json_bytes  # noqa: E402
from aeread.shared_runner.task.evaluation import (  # noqa: E402
    finalize_family_execution,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (  # noqa: E402
    ProviderRequest,
    ProviderResult,
    execute_plan_cell,
)
from aeread_families.termsbench.live import PROVIDER  # noqa: E402


class _ScriptedRoute:
    """Serves one scripted agent move per provider call, in order, then
    fails closed -- so the test also proves how many model calls the
    episode made."""

    def __init__(self, moves: list[dict]) -> None:
        self._moves = list(moves)
        self.calls = 0

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if not self._moves:
            raise ProviderFailure("provider_contract", "no scripted moves remain", retryable=False)
        self.calls += 1
        text = canonical_json_bytes(self._moves.pop(0)).decode("utf-8")
        return ProviderResult(
            response_id=f"scripted_{request.provider_call_id}",
            requested_model=request.model,
            resolved_model=request.revision or request.model,
            output_text=text,
            finish_reason="stop",
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            raw_response={"fixture": True, "output_text": text},
        )


def _events(execution, event_type: str) -> list[dict]:
    root = execution.evidence.root
    return [
        json.loads((root / event.payload_ref).read_text())
        for event in execution.evidence.read_events()
        if event.event_type == event_type
    ]


def test_the_live_plan_runs_end_to_end_against_the_scripted_counterpart(tmp_path: Path) -> None:
    setup = build_live_setup(case_id=OVERLAP_CASE_ID, seed=300, max_trajectory_cost_usd=0.05)
    payload = setup.case.payload
    r_a, r_b = float(payload["agent"]["r_a"]), float(payload["t_b"]["r_b"])
    # A buyer opening inside the zone of agreement, then accepting whatever
    # the kernel counters with. Either the counterpart accepts the opening
    # (one model call) or counters and the agent accepts (two).
    route = _ScriptedRoute(
        [
            {"decision": "offer", "price": r_b + 0.5 * (r_a - r_b), "message": "opening"},
            {"decision": "accept", "message": "agreed"},
        ]
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "run",
            prompt_sources=setup.prompt_sources,
            providers={PROVIDER: route},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
            tool_runtime_factories=setup.tool_runtime_factories,
        )
    )
    outcome = execution.episode_result.outcome
    assert outcome["termination_reason"] in {"agent_accept", "counterpart_accept"}
    assert outcome["final_price"] is not None
    # Every provider call was the agent's; the counterpart's turns are
    # sealed as scripted actions and never as provider calls.
    assert len(_events(execution, "provider_call_started")) == route.calls
    scripted = _events(execution, "scripted_action")
    assert scripted and all(s["policy_id"] == POLICY for s in scripted)
    assert all(s["world_seed"] == setup.case.world_seed for s in scripted)
    starts = _events(execution, "logical_action_started")
    by_seat = {s["request"]["seat_id"] for s in starts if s.get("source") == "scripted_policy"}
    assert by_seat == {COUNTERPART_SEAT}

    receipt = finalize_family_execution(setup=setup, execution=execution)
    assert receipt.status == "ok", receipt.status
    assert dict(receipt.scripted_seats) == {COUNTERPART_SEAT: POLICY}
    leaf_ids = {score.leaf.leaf_id for score in receipt.scores}
    assert "termsbench_protocol_compliance_leaf" in leaf_ids
    assert "termsbench_surplus_efficiency_leaf" in leaf_ids
    replayed = replay_family_receipt(setup=setup, receipt=receipt, evidence_root=tmp_path / "run")
    assert replayed.receipt_sha256 == receipt.receipt_sha256
