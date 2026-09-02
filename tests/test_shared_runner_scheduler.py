from __future__ import annotations

import asyncio
from dataclasses import replace
from types import MappingProxyType

import pytest

from aeread.shared_runner.resolver import PlanCell, case_content_sha256
from aeread.shared_runner.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    SchedulerContractError,
    TransitionResult,
    run_episode,
)
from aeread.shared_runner.schemas import CaseManifest


def _case() -> CaseManifest:
    raw = {
        "spec_version": "aeread.case/0.1",
        "case_id": "fixture_v1__dev__000001",
        "family_id": "fixture_v1",
        "family_version": "1.0.0",
        "split": "dev",
        "world_seed": 41001,
        "seats": [
            {"id": "buyer", "role": "buyer"},
            {"id": "seller", "role": "seller"},
        ],
        "episode": {
            "max_logical_actions": 8,
            "termination": ["settled", "deadline", "forfeit"],
        },
        "visibility_policy": "fixture_private_values_v1",
        "payload": {"buyer_value": 11, "seller_value": 29},
        "provenance": {
            "generator_id": "fixture_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def _cell() -> PlanCell:
    return PlanCell(
        spec_version="aeread.plan_cell/0.1",
        cell_id="cell_fixture000000000001",
        case_id="fixture_v1__dev__000001",
        case_sha256=_case().content_sha256,
        family_id="fixture_v1",
        family_version="1.0.0",
        suite_id="fixture_dev_v1",
        suite_version="1.0.0",
        block_id="controlled_fixture",
        sampling_plan_id="fixture_sample_v1",
        analysis_plan_id="fixture_analysis_v1",
        world_seed=41001,
        sampling_seed=51,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_fixture",
        cluster_level="world_seed",
        observations_per_cluster=1,
        pair_id="pair_fixture",
        paired_fields=MappingProxyType({"world_seed": 41001}),
        panel_mode="fixed_panel",
        profile_by_seat=MappingProxyType(
            {"buyer": "buyer_profile", "seller": "seller_profile"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=8,
    )


class SimultaneousFixturePlugin:
    def __init__(self) -> None:
        self.observed_state_ids: list[int] = []
        self.step_inputs: list[tuple[dict, dict]] = []

    def validate_payload(self, payload):
        return dict(payload)

    def initial_state(self, case, run):
        return {
            "private": {
                "buyer": case["buyer_value"],
                "seller": case["seller_value"],
            },
            "done": False,
        }

    def phases(self, case):
        return (
            PhaseSpec(
                phase_id="submit",
                actor_selector="all_parties",
                mode="simultaneous",
                observation_schema_by_role={"buyer": "private_value_v1", "seller": "private_value_v1"},
                action_schema_by_role={"buyer": "offer_v1", "seller": "offer_v1"},
                max_logical_actions=2,
                invalid_action_policy="reject",
                next_phases=(),
            ),
        )

    def eligible_actors(self, case, state, phase):
        return ("buyer", "seller")

    def observe(self, case, state, seat, phase):
        self.observed_state_ids.append(id(state))
        own_value = state["private"][seat]
        # Deliberately mutate the supplied view. Isolation must prevent this from
        # changing either the other actor's view or the transition state.
        other = "seller" if seat == "buyer" else "buyer"
        state["private"][other] = -999
        return {"seat": seat, "own_value": own_value}

    def parse_action(self, case, state, seat, phase, response):
        if not isinstance(response, dict) or not isinstance(response.get("offer"), int):
            return ParseResult.failure("malformed_offer")
        return ParseResult.success({"offer": response["offer"]})

    def legal(self, case, state, seat, phase, action):
        if action["offer"] < 0:
            return LegalityResult.illegal("negative_offer")
        return LegalityResult.legal_action()

    def step(self, case, state, phase, actions):
        assert set(actions) == {"buyer", "seller"}
        self.step_inputs.append((dict(state), dict(actions)))
        next_state = dict(state)
        next_state["offers"] = {
            seat: envelope.action["offer"] for seat, envelope in actions.items()
        }
        next_state["done"] = True
        return TransitionResult(state=next_state, next_phase_id=None)

    def terminal(self, case, state):
        if state["done"]:
            return {"reason": "settled"}
        return None

    def outcome(self, case, terminal):
        return {"valid": True, "reason": terminal["reason"]}


async def _offers(requests: list, *, buyer_offer: int = 7):
    async def respond(request):
        requests.append(request)
        return {"offer": buyer_offer if request.seat_id == "buyer" else 13}

    return await run_episode(
        cell=_cell(),
        case=_case(),
        plugin=SimultaneousFixturePlugin(),
        response_source=respond,
    )


def test_simultaneous_phase_freezes_private_observations_and_steps_once() -> None:
    requests: list = []
    plugin = SimultaneousFixturePlugin()

    async def respond(request):
        requests.append(request)
        return {"offer": 7 if request.seat_id == "buyer" else 13}

    result = asyncio.run(
        run_episode(
            cell=_cell(), case=_case(), plugin=plugin, response_source=respond
        )
    )

    assert [request.seat_id for request in requests] == ["buyer", "seller"]
    assert [request.observation["own_value"] for request in requests] == [11, 29]
    assert len(set(plugin.observed_state_ids)) == 2
    assert len(plugin.step_inputs) == 1
    transition_state, action_bundle = plugin.step_inputs[0]
    assert transition_state["private"] == {"buyer": 11, "seller": 29}
    assert set(action_bundle) == {"buyer", "seller"}
    assert result.logical_action_count == 2
    assert result.terminal == {"reason": "settled"}
    assert result.outcome == {"valid": True, "reason": "settled"}
    assert len(result.phase_instances) == 1
    assert len(result.phase_instances[0].transitions) == 1


def test_episode_result_carries_the_world_seed_for_score_time_replay() -> None:
    """A scorer that must independently reproduce seeded randomness needs a
    kernel-guaranteed route to the seed; the per-family workaround of stashing
    it inside state is not a contract."""

    requests: list = []
    result = asyncio.run(_offers(requests))

    assert result.world_seed == 41001


def test_simultaneous_peer_observation_is_independent_of_other_peer_action() -> None:
    first_requests: list = []
    second_requests: list = []
    first = asyncio.run(_offers(first_requests, buyer_offer=1))
    second = asyncio.run(_offers(second_requests, buyer_offer=999))

    first_seller = next(r.observation for r in first_requests if r.seat_id == "seller")
    second_seller = next(r.observation for r in second_requests if r.seat_id == "seller")
    assert first_seller == second_seller == {"seat": "seller", "own_value": 29}
    assert first.episode_id == second.episode_id
    assert [a.logical_action_id for a in first.phase_instances[0].actions] == [
        a.logical_action_id for a in second.phase_instances[0].actions
    ]


class SequentialFixturePlugin(SimultaneousFixturePlugin):
    def phases(self, case):
        return (
            PhaseSpec(
                phase_id="take_turns",
                actor_selector="all_parties",
                mode="sequential",
                observation_schema_by_role={"buyer": "running_total_v1", "seller": "running_total_v1"},
                action_schema_by_role={"buyer": "increment_v1", "seller": "increment_v1"},
                max_logical_actions=2,
                invalid_action_policy="reject",
                next_phases=(),
            ),
        )

    def initial_state(self, case, run):
        return {"total": 0, "done": False}

    def observe(self, case, state, seat, phase):
        return {"seat": seat, "total": state["total"]}

    def parse_action(self, case, state, seat, phase, response):
        return ParseResult.success({"increment": response["increment"]})

    def legal(self, case, state, seat, phase, action):
        return LegalityResult.legal_action()

    def step(self, case, state, phase, actions):
        assert len(actions) == 1
        envelope = next(iter(actions.values()))
        next_state = dict(state)
        next_state["total"] += envelope.action["increment"]
        if next(iter(actions)) == "seller":
            next_state["done"] = True
        return TransitionResult(state=next_state, next_phase_id=None)

    def outcome(self, case, terminal):
        return terminal


def test_sequential_phase_observes_state_after_each_prior_transition() -> None:
    requests: list = []

    async def respond(request):
        requests.append(request)
        return {"increment": 3 if request.seat_id == "buyer" else 5}

    result = asyncio.run(
        run_episode(
            cell=_cell(),
            case=_case(),
            plugin=SequentialFixturePlugin(),
            response_source=respond,
        )
    )

    assert [request.observation["total"] for request in requests] == [0, 3]
    assert len(result.phase_instances[0].transitions) == 2
    assert result.final_state["total"] == 8


class InvalidActionFixturePlugin(SequentialFixturePlugin):
    def __init__(self, invalid_action_policy: str) -> None:
        super().__init__()
        self.invalid_action_policy = invalid_action_policy
        self.received_envelope = None

    def phases(self, case):
        return (
            replace(
                super().phases(case)[0],
                mode="single",
                actor_selector="buyer_only",
                max_logical_actions=1,
                invalid_action_policy=self.invalid_action_policy,
            ),
        )

    def eligible_actors(self, case, state, phase):
        return ("buyer",)

    def parse_action(self, case, state, seat, phase, response):
        return ParseResult.failure("not_an_increment")

    def step(self, case, state, phase, actions):
        self.received_envelope = actions["buyer"]
        return TransitionResult(state={"total": 0, "done": True}, next_phase_id=None)


def test_reject_invalid_action_policy_stops_before_transition() -> None:
    plugin = InvalidActionFixturePlugin("reject")

    async def malformed(_request):
        return "not structured"

    with pytest.raises(SchedulerContractError, match="not_an_increment"):
        asyncio.run(
            run_episode(
                cell=_cell(), case=_case(), plugin=plugin, response_source=malformed
            )
        )
    assert plugin.received_envelope is None


def test_family_defined_invalid_action_policy_passes_typed_envelope() -> None:
    plugin = InvalidActionFixturePlugin("family_defined")

    async def malformed(_request):
        return "not structured"

    result = asyncio.run(
        run_episode(
            cell=_cell(), case=_case(), plugin=plugin, response_source=malformed
        )
    )
    assert plugin.received_envelope is not None
    assert plugin.received_envelope.valid is False
    assert plugin.received_envelope.parse.error_code == "not_an_increment"
    assert result.terminal == {"reason": "settled"}


class BrokenGraphPlugin(SimultaneousFixturePlugin):
    def phases(self, case):
        return (
            replace(super().phases(case)[0], next_phases=("missing_phase",)),
        )


def test_phase_graph_fails_before_requesting_any_action() -> None:
    calls = 0

    async def should_not_run(_request):
        nonlocal calls
        calls += 1
        return {"offer": 1}

    with pytest.raises(SchedulerContractError, match="missing_phase"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=BrokenGraphPlugin(),
                response_source=should_not_run,
            )
        )
    assert calls == 0


class EndlessPlugin(SequentialFixturePlugin):
    def phases(self, case):
        return (
            replace(
                super().phases(case)[0],
                mode="single",
                actor_selector="buyer_only",
                max_logical_actions=2,
                next_phases=("take_turns",),
            ),
        )

    def eligible_actors(self, case, state, phase):
        return ("buyer",)

    def step(self, case, state, phase, actions):
        return TransitionResult(state=state, next_phase_id="take_turns")

    def terminal(self, case, state):
        return None


def test_phase_budget_stops_an_endless_declared_cycle() -> None:
    async def respond(_request):
        return {"increment": 1}

    with pytest.raises(SchedulerContractError, match="phase logical-action budget"):
        asyncio.run(
            run_episode(
                cell=_cell(), case=_case(), plugin=EndlessPlugin(), response_source=respond
            )
        )


class ClosingPlugin(SimultaneousFixturePlugin):
    def __init__(self) -> None:
        super().__init__()
        self.close_calls: list = []

    def close(self, case, state):
        self.close_calls.append((case, state))


def test_optional_close_hook_runs_once_after_terminal_with_the_final_state() -> None:
    plugin = ClosingPlugin()

    async def respond(request):
        return {"offer": 7 if request.seat_id == "buyer" else 13}

    result = asyncio.run(
        run_episode(
            cell=_cell(), case=_case(), plugin=plugin, response_source=respond
        )
    )

    assert len(plugin.close_calls) == 1
    closed_case, closed_state = plugin.close_calls[0]
    assert closed_case == plugin.validate_payload(_case().payload)
    assert closed_state == result.final_state
    assert result.terminal == {"reason": "settled"}


def test_close_hook_failure_is_a_typed_scheduler_error() -> None:
    class BrokenClosePlugin(ClosingPlugin):
        def close(self, case, state):
            raise RuntimeError("daemon refused to die")

    async def respond(request):
        return {"offer": 7 if request.seat_id == "buyer" else 13}

    with pytest.raises(SchedulerContractError, match="family close failed"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=BrokenClosePlugin(),
                response_source=respond,
            )
        )


def test_close_hook_runs_when_preflight_fails_after_the_case_validates() -> None:
    """validate_payload is where a family would spawn its long-lived process;
    a later preflight failure must still reach teardown, or the hook leaks
    exactly the resource it exists to release."""

    closed: list = []

    class PreflightFailurePlugin(ClosingPlugin):
        def phases(self, case):
            raise RuntimeError("phase graph could not be built")

        def close(self, case, state):
            closed.append((case, state))

    async def respond(_request):
        raise AssertionError("no action may be requested")

    with pytest.raises(SchedulerContractError, match="family preflight failed"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=PreflightFailurePlugin(),
                response_source=respond,
            )
        )

    assert len(closed) == 1
    closed_case, closed_state = closed[0]
    assert closed_case == PreflightFailurePlugin().validate_payload(_case().payload)
    assert closed_state is None, "no state exists yet when phases() fails"


def test_close_is_skipped_when_the_family_case_itself_never_validated() -> None:
    """Nothing to tear down that the kernel could name: the plugin never
    received a validated case, so no per-episode resource is keyed to one."""

    closed: list = []

    class ValidationFailurePlugin(ClosingPlugin):
        def validate_payload(self, payload):
            raise RuntimeError("payload rejected")

        def close(self, case, state):
            closed.append((case, state))

    async def respond(_request):
        raise AssertionError("no action may be requested")

    with pytest.raises(SchedulerContractError, match="family preflight failed"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=ValidationFailurePlugin(),
                response_source=respond,
            )
        )
    assert closed == []


def test_a_close_attribute_with_the_wrong_arity_is_a_named_contract_error() -> None:
    """A plugin inheriting an unrelated zero-argument close() must fail with a
    message that names the collision, not an opaque TypeError."""

    class UnrelatedClosePlugin(SimultaneousFixturePlugin):
        def close(self):
            return None

    async def respond(request):
        return {"offer": 7 if request.seat_id == "buyer" else 13}

    with pytest.raises(SchedulerContractError, match="close\\(family_case, state\\)"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=UnrelatedClosePlugin(),
                response_source=respond,
            )
        )


def test_close_hook_runs_on_episode_failure_and_never_masks_it() -> None:
    close_attempts: list = []

    class ClosingEndlessPlugin(EndlessPlugin):
        def close(self, case, state):
            close_attempts.append(state)
            raise RuntimeError("teardown also failed")

    async def respond(_request):
        return {"increment": 1}

    with pytest.raises(SchedulerContractError, match="phase logical-action budget"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=ClosingEndlessPlugin(),
                response_source=respond,
            )
        )
    assert len(close_attempts) == 1, "teardown must be attempted on failure"


class RecurringPairPlugin(SimultaneousFixturePlugin):
    """Both seats act each instance and the phase cycles back to itself."""

    def phases(self, case):
        return (
            replace(
                super().phases(case)[0],
                max_logical_actions=5,
                next_phases=("submit",),
            ),
        )

    def step(self, case, state, phase, actions):
        return TransitionResult(state=state, next_phase_id="submit")

    def terminal(self, case, state):
        return None


def test_phase_budget_sums_across_recurring_instances_never_resets_per_round() -> None:
    """max_logical_actions is a whole-episode cap per phase_id: two actions per
    instance against a cap of five must trip on the sixth action (third
    instance), even though every single instance stays under the cap. A
    per-instance reset would instead run on to the case budget and fail with a
    different error."""

    requests: list = []

    async def respond(request):
        requests.append(request)
        return {"offer": 7 if request.seat_id == "buyer" else 13}

    with pytest.raises(SchedulerContractError, match="phase logical-action budget"):
        asyncio.run(
            run_episode(
                cell=_cell(),
                case=_case(),
                plugin=RecurringPairPlugin(),
                response_source=respond,
            )
        )
    assert len(requests) == 5, "the sixth action must be refused before dispatch"

