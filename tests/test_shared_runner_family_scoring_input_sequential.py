"""Replay fidelity for a ``mode="sequential"`` phase (kernel_contract_impl_review.md
findings 2 and 3).

No family registered on ``main`` uses ``mode="sequential"`` today, so these two
defects are latent: nothing exercises them until a future family does. This
module builds the smallest possible provider-free family with one
``sequential`` phase and two actors -- production applies one transition per
actor, so a genuine sequential phase instance carries *two*
``transition_applied`` events, not one. It exists purely to prove
``replay_family_scoring_input`` reproduces that trajectory exactly (finding 2)
and cross-checks the sealed ``phase_instance_succeeded`` completion boundary
rather than ignoring it (finding 3).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

import aeread.shared_runner.task.execution as execution_module
from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
)
from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry, ProviderCapabilities
from aeread.shared_runner.schemas import (
    AgentProfile,
    AnalysisPlan,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
)
from aeread.shared_runner.model_call.harness import default_harnesses
from aeread.shared_runner.task.evaluation import SeatContext, replay_family_scoring_input
from aeread.shared_runner.task.execution import (
    CanonicalResponse,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    TokenPricing,
    execute_plan_cell,
)
from aeread.shared_runner.task.scheduler import LegalityResult, ParseResult, PhaseSpec


_FAMILY_ID = "kernel_contract_sequential_v1"
_FAMILY_VERSION = "1.0.0"
_PLUGIN_ID = "kernel_contract_sequential_plugin"
_PROVIDER_ID = "kernel_contract_sequential_scripted_participant"
_RUNTIME_ID = (
    "tests.test_shared_runner_family_scoring_input_sequential.kernel_contract_sequential"
)

_MODULE_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_EXECUTION_DIGEST = hashlib.sha256(Path(execution_module.__file__).read_bytes()).hexdigest()


def _family_manifest() -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": _FAMILY_ID,
                "version": _FAMILY_VERSION,
                "plugin_id": _PLUGIN_ID,
            },
            "environment": {
                "topology": "one_sequential_round_two_actors",
                "phase_specs": ["round"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "participant": {
                    "testable": True,
                    "scripted_policies": ["kernel_contract_sequential_scripted_v1"],
                },
            },
            "measurement": {
                "primary_estimand": "pick_total",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
            },
            "scoring": {
                "scorer_id": "kernel_contract_sequential_scorer_v1",
                "reference_provider_ids": [],
            },
        }
    )


class _SequentialPlugin:
    """One ``mode="sequential"`` phase; two actors each pick a number in turn."""

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if set(payload) != {"scenario_id"} or not isinstance(payload["scenario_id"], str):
            raise ValueError("payload must contain only a string scenario_id")
        return {"scenario_id": payload["scenario_id"]}

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del family_case, run
        return {"picks": ()}

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        observation_schemas = {"participant": "kernel_contract_sequential_observation_v1"}
        action_schemas = {"participant": "kernel_contract_sequential_pick_v1"}
        return (
            PhaseSpec(
                "round", "participant", "sequential",
                observation_schemas, action_schemas, 2, "reject", (),
            ),
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, phase
        if len(state["picks"]) >= 2:
            return ()
        return ("seat_a", "seat_b")

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        del family_case, phase
        return {"seat": seat, "prior_picks": list(state["picks"])}

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del family_case, state, seat, phase
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, ValueError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict) or not isinstance(value.get("pick"), int):
            return ParseResult.failure("malformed_pick")
        return ParseResult.success({"pick": value["pick"]})

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del family_case, state, seat, phase, action
        return LegalityResult.legal_action()

    def step(self, family_case, state, phase, actions) -> "TransitionResult":
        from aeread.shared_runner.task.scheduler import TransitionResult

        del family_case, phase
        # Exactly one actor's envelope per call: production applies one
        # transition per sequential actor (kernel_contract_impl_review.md
        # finding 2), never the whole phase's actions at once.
        assert len(actions) == 1, "sequential step must receive exactly one actor"
        (seat_id, envelope), = actions.items()
        pick = envelope.action["pick"]
        next_state = {"picks": tuple(state["picks"]) + ((seat_id, pick),)}
        return TransitionResult(state=next_state, next_phase_id=None)

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        picks = tuple(state["picks"])
        return {"picks": picks} if len(picks) == 2 else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        del family_case
        return {"pick_total": sum(pick for _seat, pick in terminal["picks"])}

    def build_scorer(self, family_case: Mapping[str, Any]):
        del family_case
        raise NotImplementedError("this module tests replay, not scoring")

    def build_reference_providers(self, family_case) -> tuple[str, ...]:
        del family_case
        return ()

    def generator(self):
        return lambda *args, **kwargs: None


class _ScriptedPickProvider:
    """Serves one scripted pick per call, in order, then fails closed."""

    def __init__(self, picks) -> None:
        self._picks = list(picks)

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        if not self._picks:
            raise ProviderFailure(
                "provider_contract", "no scripted picks remain", retryable=False
            )
        output = {"pick": self._picks.pop(0)}
        text = canonical_json_bytes(output).decode("utf-8")
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


def _case() -> CaseManifest:
    raw = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": "kernel_contract_sequential_case_v1",
        "family_id": _FAMILY_ID,
        "family_version": _FAMILY_VERSION,
        "split": "dev",
        "world_seed": 1,
        "seats": [
            {"id": "seat_a", "role": "participant"},
            {"id": "seat_b", "role": "participant"},
        ],
        "episode": {"max_logical_actions": 2, "termination": ["both_picks_recorded"]},
        "visibility_policy": "kernel_contract_sequential_full_visibility_v1",
        "payload": {"scenario_id": "kernel_contract_sequential_case_v1"},
        "provenance": {
            "generator_id": "kernel_contract_sequential_generator_v1",
            "generator_version": "1.0.0",
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


@dataclasses.dataclass(frozen=True, slots=True)
class _SequentialSetup:
    plan: Any
    registry: PluginRegistry
    prompt_sources: Mapping[str, str]
    pricing: Mapping[str, TokenPricing]
    harnesses: Mapping[str, Any]


def _build_setup() -> _SequentialSetup:
    case = _case()
    family = _family_manifest()
    sampling = SamplingPlan.from_dict(
        {
            "spec_version": SamplingPlan.SPEC_VERSION,
            "sampling_plan_id": "kernel_contract_sequential_sample_v1",
            "estimand": "fixed_sequential_pick_case",
            "target": "kernel_contract_sequential_case_v1",
            "selection": "fixed_curated",
            "seeds": [case.world_seed],
            "replicates": 1,
            "cluster_level": "world_seed",
            "cluster_id_fields": ["generator_version", "world_seed"],
            "paired_fields": [],
            "replicate_level": "episode_attempt",
            "panel_mode": "fixed_panel",
        }
    )
    block = EvaluationBlock.from_dict(
        {
            "spec_version": EvaluationBlock.SPEC_VERSION,
            "block_id": "kernel_contract_sequential_self_play_v1",
            "kind": "self_play",
            "subject_seats": ["seat_a", "seat_b"],
            "controlled_profiles": {},
            "repetitions": 1,
            "seed_policy": "fixed",
        }
    )
    analysis = AnalysisPlan.from_dict(
        {
            "spec_version": AnalysisPlan.SPEC_VERSION,
            "analysis_plan_id": "kernel_contract_sequential_analysis_v1",
            "estimands": ["pick_total"],
            "group_by": ["family_id"],
            "missingness": "report_separately",
            "resampling_unit": "world_seed",
            "uncertainty": "none",
            "multiplicity": "none",
            "sensitivity": [],
            "cross_family_scalar": "disabled",
        }
    )
    suite = SuiteManifest.from_dict(
        {
            "spec_version": SuiteManifest.SPEC_VERSION,
            "suite_id": "kernel_contract_sequential_suite_v1",
            "version": "1.0.0",
            "family_ids": [family.family.id],
            "case_ids": [case.case_id],
            "sampling_plan_id": sampling.sampling_plan_id,
            "evaluation_block_ids": [block.block_id],
            "analysis_plan_id": analysis.analysis_plan_id,
        }
    )
    pricing = TokenPricing(0.0, 0.0, 0.0, "kernel_contract_sequential_zero_cost_v1")
    profile = AgentProfile.from_dict(
        {
            "spec_version": AgentProfile.SPEC_VERSION,
            "profile_id": "kernel_contract_sequential_participant_v1",
            "model": {
                "provider": _PROVIDER_ID,
                "model": "kernel_contract_sequential_scripted_participant_v1",
                "revision": "1.0.0",
                "base_url": None,
            },
            "harness": {
                "id": "minimal_chat",
                "version": "1.0",
                "config": {
                    "pricing_id": pricing.pricing_id,
                    "pricing_sha256": pricing.content_sha256(),
                },
            },
            "prompt": {
                "prompt_id": "kernel_contract_sequential_prompt_v1",
                "sha256": hashlib.sha256(b"pick a number each turn").hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": _RUNTIME_ID,
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "scripted_no_reasoning_v1",
                "effort": None,
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 64,
                "seed": None,
                "top_p": None,
            },
            "budgets": {
                "max_logical_actions": 2,
                "timeout_seconds": 30.0,
                "max_cost_usd": 0.0,
            },
            "retry_policy": {
                "max_action_attempts": 1,
                "retryable_conditions": [],
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )
    run_spec = RunSpec.from_dict(
        {
            "spec_version": RunSpec.SPEC_VERSION,
            "run_spec_id": "kernel_contract_sequential_run_spec_v1",
            "suite_id": suite.suite_id,
            "evaluation_block_ids": [block.block_id],
            "agent_profile_ids": [profile.profile_id],
            "seat_assignments": {
                "seat_a": profile.profile_id,
                "seat_b": profile.profile_id,
            },
            "execution_mode": "evaluate",
            "replicate_override": None,
            "budget_overrides": None,
        }
    )
    registry = PluginRegistry()
    registry.register_trusted(family, _SequentialPlugin())
    harness_registry = HarnessRegistry()
    harnesses = default_harnesses()
    for harness in harnesses.values():
        harness_registry.register(harness)
    pins = (
        ImplementationPin.from_dict(
            {
                "component_id": _PLUGIN_ID,
                "kind": "family_plugin",
                "version": "1.0.0",
                "sha256": _MODULE_DIGEST,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": "kernel_contract_sequential_scorer_v1",
                "kind": "scorer",
                "version": "1.0.0",
                "sha256": _MODULE_DIGEST,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": "minimal_chat",
                "kind": "harness",
                "version": "1.0",
                "sha256": _EXECUTION_DIGEST,
            }
        ),
        ImplementationPin.from_dict(
            {
                "component_id": _RUNTIME_ID,
                "kind": "runtime",
                "version": "0.1.0",
                "sha256": _MODULE_DIGEST,
            }
        ),
    )
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=sampling,
        evaluation_blocks=(block,),
        analysis=analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=pins,
        harness_registry=harness_registry,
        provider_capabilities={
            _PROVIDER_ID: ProviderCapabilities(
                native_tools=False,
                structured_output=False,
                seed=False,
                system_prompt=True,
                reasoning_budget=False,
                reasoning_token_report=False,
                max_context_tokens=None,
            )
        },
    )
    return _SequentialSetup(
        plan=plan,
        registry=registry,
        prompt_sources={
            "kernel_contract_sequential_prompt_v1": "pick a number each turn"
        },
        pricing={profile.model.model: pricing},
        harnesses=harnesses,
    )


def _run_episode(picks, *, evidence_root: Path):
    setup = _build_setup()
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=evidence_root,
            prompt_sources=setup.prompt_sources,
            providers={_PROVIDER_ID: _ScriptedPickProvider(picks)},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
        )
    )
    case = setup.plan.cases[0]
    family = setup.plan.families[0]
    plugin = setup.registry.resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    return execution, plugin, family_case


def test_sequential_phase_produces_two_transitions_in_one_instance(tmp_path) -> None:
    """Sanity-check the fixture itself before trusting it to test replay."""

    execution, _plugin, _family_case = _run_episode((3, 4), evidence_root=tmp_path)
    (phase_instance,) = execution.episode_result.phase_instances
    assert phase_instance.mode == "sequential"
    assert len(phase_instance.transitions) == 2
    assert [action.seat_id for action in phase_instance.actions] == ["seat_a", "seat_b"]


def test_replay_reproduces_a_sequential_phase_instance_exactly(tmp_path) -> None:
    """kernel_contract_impl_review.md finding 2.

    Before the mode-aware replay fix, ``_replay_family_trajectory`` required
    exactly one ``transition_applied`` event per phase instance and stepped
    the plugin once with every actor's action together -- both wrong for a
    genuine ``mode="sequential"`` phase with more than one actor.
    """

    execution, plugin, family_case = _run_episode((3, 4), evidence_root=tmp_path)

    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        seat_context=SeatContext((), {}),
    )

    assert canonical_json_bytes(scoring_input.phase_instances) == canonical_json_bytes(
        execution.episode_result.phase_instances
    )
    assert canonical_json_bytes(scoring_input.outcome) == canonical_json_bytes(
        execution.episode_result.outcome
    )
    assert scoring_input.outcome["pick_total"] == 7


def test_replay_rejects_a_phase_completion_boundary_that_understates_the_actors(
    tmp_path,
) -> None:
    """kernel_contract_impl_review.md finding 3.

    A ``phase_instance_succeeded`` event whose ``logical_action_ids`` omits an
    actor who actually acted must fail replay, not be silently ignored.
    """

    execution, plugin, family_case = _run_episode((3, 4), evidence_root=tmp_path)

    events_path = execution.evidence.root / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    tampered_lines = []
    tampered = False
    for line in lines:
        record = json.loads(line)
        if not tampered and record["event_type"] == "phase_instance_succeeded":
            artifact_path = execution.evidence.root / record["payload_ref"]
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            payload["logical_action_ids"] = list(payload["logical_action_ids"])[:1]
            new_bytes = canonical_json_bytes(payload)
            artifact_path.write_text(new_bytes.decode("utf-8"), encoding="utf-8")
            record["payload_sha256"] = hashlib.sha256(new_bytes).hexdigest()
            tampered = True
        tampered_lines.append(json.dumps(record))
    assert tampered, "fixture must contain a phase_instance_succeeded event"
    events_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="completion boundary"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            seat_context=SeatContext((), {}),
        )
