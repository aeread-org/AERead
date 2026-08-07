"""rLLM rollout adapter for AERead (experimental).

The framework-neutral core is :func:`run_episode`. Only the submitted seat
uses the rLLM model-gateway session; external scoring services remain outside
the policy trace.

Compatibility is pinned to rLLM revision
``1d1109a655e291b3001d8526d7c9ecc5b9328226``. Import-time feature probes fail
loudly if the episode contract changes.
"""
from __future__ import annotations

from typing import Any

try:
    import rllm
    from rllm.types import AgentConfig, Episode, Step, Task, Trajectory
    from rllm.workflows.workflow import TerminationReason
except ModuleNotFoundError as err:
    if err.name != "rllm":
        raise
    rllm = None
    AgentConfig = Episode = Step = Task = Trajectory = Any
    TerminationReason = Any
    _RLLM_IMPORT_ERROR: ModuleNotFoundError | None = err
else:
    _RLLM_IMPORT_ERROR = None

from aeread.integrations.episode_core import (
    DEFAULT_EXTERNAL_SCORING_MAX_TOKENS,
    DEFAULT_EXTERNAL_SCORING_TEMPERATURE,
    run_episode,
)
from aeread.integrations.failure_taxonomy import (
    EpisodeMeasurement,
    FlowTelemetry,
    IntegrationConfigurationError,
    normalize_integration_exception,
)
from aeread.integrations.gateway_candidate import (
    NO_ACTION,
    CandidateTraceMismatch,
    EmptyModelResponse,
    GatewayCandidate,
)
from aeread.integrations.rllm_dataset import resolve_case_resource


RLLM_PINNED_REVISION = "1d1109a655e291b3001d8526d7c9ecc5b9328226"
RLLM_COMPATIBILITY_MESSAGE = (
    "AERead requires the rLLM API verified at revision "
    f"{RLLM_PINNED_REVISION}; install integrations/rllm/constraints.txt"
)
_FLOW_TELEMETRY = FlowTelemetry()


class RllmCompatibilityError(RuntimeError):
    """The installed rLLM API cannot preserve AERead episode semantics."""


def _require_rllm_compatibility(
    *,
    episode_type: type[Any] | None = None,
    trajectory_type: type[Any] | None = None,
    step_type: type[Any] | None = None,
    agent_config_type: type[Any] | None = None,
    termination_error: Any = None,
) -> None:
    """Feature-probe the complete constructor contract used by the adapter."""
    episode_type = episode_type or Episode
    trajectory_type = trajectory_type or Trajectory
    step_type = step_type or Step
    agent_config_type = agent_config_type or AgentConfig
    termination_error = termination_error or TerminationReason.ERROR
    required_fields = {
        episode_type: {
            "trajectories",
            "artifacts",
            "termination_reason",
            "is_correct",
            "metadata",
        },
        trajectory_type: {"name", "steps", "reward"},
        step_type: {
            "chat_completions",
            "model_response",
            "action",
            "done",
        },
    }
    try:
        for model_type, names in required_fields.items():
            fields = set(model_type.model_fields)
            missing = sorted(names - fields)
            if missing:
                raise TypeError(
                    f"{model_type.__name__} is missing fields {missing}"
                )
        config_fields = set(agent_config_type.__dataclass_fields__)
        if "sampling_params" not in config_fields:
            raise TypeError("AgentConfig is missing sampling_params")

        step = step_type(
            chat_completions=[{"role": "user", "content": "probe"}],
            model_response="probe",
            action="probe",
            done=True,
        )
        trajectory = trajectory_type(
            name="compatibility_probe", steps=[step], reward=-0.25
        )
        episode = episode_type(
            trajectories=[trajectory],
            artifacts={"aer": -0.25},
            termination_reason=termination_error,
            is_correct=False,
            metadata={"probe": True},
        )
        if episode.artifacts.get("aer") != -0.25:
            raise TypeError("Episode discarded artifacts")
        if episode.termination_reason != termination_error:
            raise TypeError("Episode discarded termination_reason")
        if episode.is_correct is not False:
            raise TypeError("Episode discarded is_correct")
        if episode.metadata.get("probe") is not True:
            raise TypeError("Episode discarded metadata")
    except Exception as err:
        raise RllmCompatibilityError(
            f"{RLLM_COMPATIBILITY_MESSAGE}: {err}"
        ) from err


if rllm is not None:
    _require_rllm_compatibility()


def _unscorable_reason(result: dict[str, Any]) -> str | None:
    """Describe an unscorable result for diagnostics only."""
    status = result.get("status")
    if status != "ok":
        return (
            f"aeread episode did not complete: status={status!r}. "
            "The seat under test produced no scorable run. This is a harness "
            "failure, not a score of zero."
        )
    if result.get("aer") is None:
        return (
            "aeread episode has no AER: "
            f"denominator={result.get('denominator')!r}. Degenerate "
            "denominators are reported, never imputed."
        )
    return None


def _trace_safe_turns(result: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    """Validate the candidate-side one-request/one-step contract."""
    turns = list(result.get("turns") or [])
    request_count = int(result.get("candidate_request_count", len(turns)))
    blank_count = int(result.get("blank_completion_count", 0))
    if blank_count:
        raise EmptyModelResponse(
            request_count=request_count,
            blank_completion_count=blank_count,
            completed_turn_count=len(turns),
        )
    for turn in turns:
        if not str(turn.get("response") or "").strip():
            raise EmptyModelResponse(
                request_count=request_count,
                blank_completion_count=1,
                completed_turn_count=len(turns) - 1,
            )
    if result.get("status") == "ok" and request_count != len(turns):
        raise CandidateTraceMismatch(
            "successful episode cannot align candidate requests with turns "
            f"(requests={request_count}, turns={len(turns)})"
        )
    return turns, request_count, blank_count


def _build_measured_episode(
    task: Task | dict[str, Any], config: AgentConfig
) -> Episode:
    """Build one measured episode or raise a typed integration failure."""
    metadata = getattr(task, "metadata", None) or {}
    if isinstance(task, dict):
        metadata = {**task, **metadata}
    required_row_fields = {
        "id",
        "case_id",
        "case_resource",
        "case_sha256",
        "seed",
        "split",
        "caseset_version",
        "caseset_sha256",
        "protocol_version",
        "prompt_spec",
        "panel_spec",
        "scorer_version",
    }
    missing = sorted(required_row_fields - set(metadata))
    if missing:
        raise IntegrationConfigurationError(
            f"aeread task row is missing fields {missing} -- "
            "build them with aeread.integrations.rllm_dataset.build_rows()"
        )
    case_path = resolve_case_resource(metadata)
    seed = metadata["seed"]

    base_url = config.base_url
    model = config.model
    sampling_params = dict(config.sampling_params)
    config_metadata = config.metadata or {}
    external_temperature = float(
        config_metadata.get(
            "external_scoring_temperature",
            DEFAULT_EXTERNAL_SCORING_TEMPERATURE,
        )
    )
    external_max_tokens = int(
        config_metadata.get(
            "external_scoring_max_tokens",
            DEFAULT_EXTERNAL_SCORING_MAX_TOKENS,
        )
    )

    def candidate_factory() -> GatewayCandidate:
        return GatewayCandidate(
            base_url,
            model,
            sampling_params=sampling_params,
        )

    result = run_episode(
        case_path,
        int(seed),
        candidate_factory=candidate_factory,
        external_scoring_temperature=external_temperature,
        external_scoring_max_tokens=external_max_tokens,
    )
    turns, request_count, blank_count = _trace_safe_turns(result)
    measurement = EpisodeMeasurement.from_result(result)

    steps: list[Step] = []
    for index, turn in enumerate(turns):
        response = str(turn["response"])
        step_kwargs: dict[str, Any] = {
            "chat_completions": [
                {"role": "user", "content": turn["observation"]}
            ],
            "model_response": response,
            "action": response,
            "done": index == len(turns) - 1,
            "metadata": {
                "phase": turn.get("phase"),
                "candidate_response_id": turn.get("response_id"),
            },
        }
        if turn.get("response_id"):
            step_kwargs["id"] = str(turn["response_id"])
        steps.append(Step(**step_kwargs))

    trajectory = Trajectory(
        name="under_test",
        steps=steps,
        reward=measurement.aer,
    )
    candidate_sampling = result.get("candidate_sampling") or {
        "source": "rllm_gateway_session",
        "params": sampling_params,
    }
    expected_sampling = {
        "source": "rllm_gateway_session",
        "params": sampling_params,
    }
    if candidate_sampling != expected_sampling:
        raise CandidateTraceMismatch(
            "recorded candidate sampling does not match the rLLM gateway session"
        )
    score = result.get("score") or {}
    scorer = {
        "version": metadata["scorer_version"],
        "tier": score.get("tier"),
    }
    dataset_fields = (
        "id",
        "case_id",
        "case_resource",
        "case_sha256",
        "seed",
        "split",
        "caseset_version",
        "caseset_sha256",
        "protocol_version",
        "prompt_spec",
        "panel_spec",
        "scorer_version",
    )
    artifacts = {
        "status": "ok",
        "aer": measurement.aer,
        "w_real": measurement.w_real,
        "denominator": measurement.denominator,
        "denominator_tier": result.get("denominator_tier"),
        "candidate_request_count": request_count,
        "blank_completion_count": blank_count,
        "completed_turn_count": len(turns),
        "model": model,
        "candidate_sampling": candidate_sampling,
        "caseset_sha256": metadata["caseset_sha256"],
        "prompt_spec": metadata["prompt_spec"],
        "panel_spec": metadata["panel_spec"],
        "scorer_version": metadata["scorer_version"],
        "scorer": scorer,
        "external_scoring": result.get("external_scoring")
        or {
            "temperature": external_temperature,
            "max_tokens": external_max_tokens,
        },
        "candidate_response_ids": [
            turn.get("response_id") for turn in turns
        ],
        "dataset": {name: metadata[name] for name in dataset_fields},
        "rllm_revision": RLLM_PINNED_REVISION,
        "is_validation": bool(config.is_validation),
    }
    return Episode(
        trajectories=[trajectory],
        artifacts=artifacts,
        is_correct=measurement.aer > 0.0,
    )


def get_flow_telemetry() -> dict[str, Any]:
    """Return process-local attempted, measured, and failed counters."""
    return _FLOW_TELEMETRY.snapshot()


def reset_flow_telemetry() -> None:
    """Reset process-local counters before a bounded audit run."""
    _FLOW_TELEMETRY.reset()


def _aeread_flow_impl(
    task: Task | dict[str, Any], config: AgentConfig
) -> Episode:
    """Run one AERead task and expose measurement/failure counters."""
    _FLOW_TELEMETRY.record_attempt()
    try:
        episode = _build_measured_episode(task, config)
    except Exception as error:
        typed = normalize_integration_exception(error)
        flow_counters = _FLOW_TELEMETRY.record_failure(typed.failure_class)
        typed.telemetry = {
            "attempt": {
                "attempted": 1,
                "measured": 0,
                "failed": 1,
                "failed_by_class": {typed.failure_class.value: 1},
            },
            "flow": flow_counters,
        }
        if typed is error:
            raise
        raise typed from error

    flow_counters = _FLOW_TELEMETRY.record_measurement()
    episode.artifacts["measurement_counters"] = {
        "attempted": 1,
        "measured": 1,
        "failed": 0,
        "failed_by_class": {},
    }
    episode.artifacts["flow_counters"] = flow_counters
    return episode


if rllm is not None:
    try:
        aeread_flow = rllm.rollout(name="under_test")(_aeread_flow_impl)
    except Exception as err:
        raise RllmCompatibilityError(
            f"{RLLM_COMPATIBILITY_MESSAGE}: rollout decorator mismatch: {err}"
        ) from err
    # rLLM eval honors this hint; training uses prototype_train.yaml's
    # explicit workflow.n_parallel_tasks setting.
    aeread_flow.max_concurrent = 2
else:
    def aeread_flow(*args: Any, **kwargs: Any) -> Any:
        raise ModuleNotFoundError(
            f"{RLLM_COMPATIBILITY_MESSAGE}: rllm is not installed"
        ) from _RLLM_IMPORT_ERROR


__all__ = [
    "EmptyModelResponse",
    "GatewayCandidate",
    "NO_ACTION",
    "RLLM_PINNED_REVISION",
    "RllmCompatibilityError",
    "aeread_flow",
    "get_flow_telemetry",
    "reset_flow_telemetry",
    "run_episode",
]
