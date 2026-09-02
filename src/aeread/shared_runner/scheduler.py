"""Provider-free R3 phase scheduler for the AERead shared runner.

The scheduler owns phase selection, observation isolation, action collection,
parsing/legality boundaries, transitions, termination, and logical-action
budgets.  Family plugins continue to own all economic state and semantics.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import inspect
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .resolver import PlanCell, canonical_json_bytes, case_content_sha256
from .schemas import CaseManifest


class SchedulerContractError(RuntimeError):
    """A phase graph or family hook violated the generic scheduler contract."""


_PHASE_MODES = {"single", "sequential", "simultaneous"}
_INVALID_ACTION_POLICIES = {"reject", "family_defined"}


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _freeze(value: Any) -> Any:
    """Recursively detach and freeze JSON-like evidence values."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    try:
        return copy.deepcopy(value)
    except Exception as error:  # pragma: no cover - defensive contract surface
        raise SchedulerContractError(
            f"value cannot be detached for immutable execution evidence: {error}"
        ) from error


def _copy_for_hook(value: Any, label: str) -> Any:
    try:
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return dataclasses.replace(
                value,
                **{
                    field.name: _copy_for_hook(getattr(value, field.name), label)
                    for field in dataclasses.fields(value)
                },
            )
        if isinstance(value, Mapping):
            return {
                _copy_for_hook(key, label): _copy_for_hook(item, label)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(_copy_for_hook(item, label) for item in value)
        if isinstance(value, list):
            return [_copy_for_hook(item, label) for item in value]
        if isinstance(value, set):
            return {_copy_for_hook(item, label) for item in value}
        return copy.deepcopy(value)
    except Exception as error:
        raise SchedulerContractError(f"cannot isolate {label}: {error}") from error


def _content_hash(value: Any, label: str) -> str:
    try:
        return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    except (TypeError, ValueError) as error:
        raise SchedulerContractError(f"{label} is not canonically serializable: {error}") from error


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_content_hash(value, prefix)[:20]}"


def _freeze_string_mapping(value: Mapping[str, str], path: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{path} must be a non-empty mapping")
    output: dict[str, str] = {}
    for key, item in value.items():
        clean_key = _nonempty_string(key, f"{path} key")
        output[clean_key] = _nonempty_string(item, f"{path}[{clean_key!r}]")
    return MappingProxyType(dict(sorted(output.items())))


@dataclass(frozen=True, slots=True)
class PhaseSpec:
    """Runner-readable declaration for one reusable family phase.

    ``max_logical_actions`` is a whole-episode cap per ``phase_id``: the count
    is summed across every instance of this phase over the episode and is
    never reset per round or instance. A recurring phase therefore declares
    the total it may consume, not a per-visit allowance — the cap is a
    runaway guard, and a per-instance reset would let a declared cycle burn
    actions up to the case budget unchecked.
    """

    phase_id: str
    actor_selector: str
    mode: str
    observation_schema_by_role: Mapping[str, str]
    action_schema_by_role: Mapping[str, str]
    max_logical_actions: int
    invalid_action_policy: str
    next_phases: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "phase_id", _nonempty_string(self.phase_id, "phase_id"))
        object.__setattr__(
            self,
            "actor_selector",
            _nonempty_string(self.actor_selector, "actor_selector"),
        )
        if self.mode not in _PHASE_MODES:
            raise ValueError(f"mode must be one of {sorted(_PHASE_MODES)}")
        object.__setattr__(
            self,
            "observation_schema_by_role",
            _freeze_string_mapping(
                self.observation_schema_by_role, "observation_schema_by_role"
            ),
        )
        object.__setattr__(
            self,
            "action_schema_by_role",
            _freeze_string_mapping(self.action_schema_by_role, "action_schema_by_role"),
        )
        if isinstance(self.max_logical_actions, bool) or not isinstance(
            self.max_logical_actions, int
        ):
            raise ValueError("max_logical_actions must be an integer")
        if self.max_logical_actions <= 0:
            raise ValueError("max_logical_actions must be positive")
        if self.invalid_action_policy not in _INVALID_ACTION_POLICIES:
            raise ValueError(
                "invalid_action_policy must be one of "
                f"{sorted(_INVALID_ACTION_POLICIES)}"
            )
        if not isinstance(self.next_phases, tuple):
            object.__setattr__(self, "next_phases", tuple(self.next_phases))
        cleaned_next = tuple(
            _nonempty_string(next_phase, "next_phases item")
            for next_phase in self.next_phases
        )
        if len(set(cleaned_next)) != len(cleaned_next):
            raise ValueError("next_phases must not contain duplicates")
        object.__setattr__(self, "next_phases", cleaned_next)


@dataclass(frozen=True, slots=True)
class ParseResult:
    ok: bool
    action: Any = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise ValueError("ParseResult.ok must be a boolean")
        if self.ok:
            if self.error_code is not None:
                raise ValueError("successful ParseResult cannot carry error_code")
            object.__setattr__(self, "action", _freeze(self.action))
        else:
            if self.action is not None:
                raise ValueError("failed ParseResult cannot carry an action")
            object.__setattr__(
                self,
                "error_code",
                _nonempty_string(self.error_code, "ParseResult.error_code"),
            )

    @classmethod
    def success(cls, action: Any) -> "ParseResult":
        return cls(ok=True, action=action)

    @classmethod
    def failure(cls, error_code: str) -> "ParseResult":
        return cls(ok=False, error_code=error_code)


@dataclass(frozen=True, slots=True)
class LegalityResult:
    legal: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.legal, bool):
            raise ValueError("LegalityResult.legal must be a boolean")
        if self.legal and self.reason is not None:
            raise ValueError("legal result cannot carry a reason")
        if not self.legal:
            object.__setattr__(
                self,
                "reason",
                _nonempty_string(self.reason, "LegalityResult.reason"),
            )

    @classmethod
    def legal_action(cls) -> "LegalityResult":
        return cls(legal=True)

    @classmethod
    def illegal(cls, reason: str) -> "LegalityResult":
        return cls(legal=False, reason=reason)


@dataclass(frozen=True, slots=True)
class ActionEnvelope:
    seat_id: str
    valid: bool
    action: Any
    parse: ParseResult
    legality: LegalityResult | None


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """Family-owned new state plus a declared scheduler transition."""

    state: Any
    next_phase_id: str | None
    consequences: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.next_phase_id is not None:
            object.__setattr__(
                self,
                "next_phase_id",
                _nonempty_string(self.next_phase_id, "next_phase_id"),
            )
        if not isinstance(self.consequences, Mapping):
            raise ValueError("consequences must be a mapping")
        object.__setattr__(self, "consequences", _freeze(self.consequences))


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    episode_id: str
    phase_instance_id: str
    logical_action_id: str
    cell_id: str
    case_id: str
    phase_id: str
    seat_id: str
    role: str
    profile_id: str
    observation_schema: str
    action_schema: str
    observation: Any


@dataclass(frozen=True, slots=True)
class LogicalActionRecord:
    logical_action_id: str
    seat_id: str
    request: DecisionRequest
    response: Any
    parse: ParseResult
    legality: LegalityResult | None
    envelope: ActionEnvelope


@dataclass(frozen=True, slots=True)
class PhaseInstance:
    phase_instance_id: str
    phase_id: str
    ordinal: int
    mode: str
    eligible_actors: tuple[str, ...]
    pre_state_sha256: str
    post_state_sha256: str
    observations: Mapping[str, Any]
    actions: tuple[LogicalActionRecord, ...]
    transitions: tuple[TransitionResult, ...]


@dataclass(frozen=True, slots=True)
class EpisodeResult:
    episode_id: str
    cell_id: str
    case_id: str
    family_id: str
    final_state: Any
    terminal: Any
    outcome: Any
    logical_action_count: int
    phase_instances: tuple[PhaseInstance, ...]
    # Trailing with a default so pre-existing constructions stay valid. The
    # case manifest's seed rides along so a scorer that must independently
    # reproduce seeded randomness has a kernel-guaranteed route to it instead
    # of every family stashing the seed inside its own state.
    world_seed: int | None = None


ResponseSource = Callable[[DecisionRequest], Awaitable[Any]]


def _validate_phase_graph(raw_phases: Sequence[PhaseSpec]) -> tuple[PhaseSpec, ...]:
    if not isinstance(raw_phases, Sequence) or isinstance(raw_phases, (str, bytes)):
        raise SchedulerContractError("plugin phases() must return a sequence")
    phases = tuple(raw_phases)
    if not phases:
        raise SchedulerContractError("phase graph must contain at least one PhaseSpec")
    by_id: dict[str, PhaseSpec] = {}
    for phase in phases:
        if not isinstance(phase, PhaseSpec):
            raise SchedulerContractError("phase graph must contain only PhaseSpec records")
        if phase.phase_id in by_id:
            raise SchedulerContractError(f"duplicate phase_id: {phase.phase_id}")
        by_id[phase.phase_id] = phase
    for phase in phases:
        missing = sorted(set(phase.next_phases) - set(by_id))
        if missing:
            raise SchedulerContractError(
                f"phase {phase.phase_id!r} references missing next phases: {missing}"
            )
    reachable = {phases[0].phase_id}
    frontier = [phases[0].phase_id]
    while frontier:
        current = frontier.pop()
        for target in by_id[current].next_phases:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    unreachable = sorted(set(by_id) - reachable)
    if unreachable:
        raise SchedulerContractError(f"phase graph contains unreachable phases: {unreachable}")
    return phases


def _validate_cell_case(cell: PlanCell, case: CaseManifest) -> Mapping[str, str]:
    if not isinstance(cell, PlanCell):
        raise SchedulerContractError("cell must be a PlanCell")
    if not isinstance(case, CaseManifest):
        raise SchedulerContractError("case must be a CaseManifest")
    checks = {
        "case_id": (cell.case_id, case.case_id),
        "family_id": (cell.family_id, case.family_id),
        "family_version": (cell.family_version, case.family_version),
        "case_sha256": (cell.case_sha256, case.content_sha256),
        "world_seed": (cell.world_seed, case.world_seed),
    }
    mismatches = {
        key: values for key, values in checks.items() if values[0] != values[1]
    }
    if mismatches:
        raise SchedulerContractError(f"PlanCell and CaseManifest mismatch: {mismatches}")
    computed_case_hash = case_content_sha256(case)
    if computed_case_hash != case.content_sha256:
        raise SchedulerContractError(
            f"case {case.case_id!r} content hash changed after plan resolution"
        )
    role_by_seat = {seat.id: seat.role for seat in case.seats}
    if set(role_by_seat) != set(cell.profile_by_seat):
        raise SchedulerContractError("cell profile assignments do not cover case seats exactly")
    if cell.case_max_logical_actions != case.episode.max_logical_actions:
        raise SchedulerContractError(
            "cell logical-action budget does not match the sealed case budget"
        )
    return MappingProxyType(role_by_seat)


def _eligible_actors(
    plugin: Any,
    family_case: Any,
    state: Any,
    phase: PhaseSpec,
    role_by_seat: Mapping[str, str],
) -> tuple[str, ...]:
    try:
        actors = tuple(
            plugin.eligible_actors(
                family_case, _copy_for_hook(state, "eligible-actor state"), phase
            )
        )
    except Exception as error:
        raise SchedulerContractError(
            f"eligible_actors failed for phase {phase.phase_id!r}: {error}"
        ) from error
    if not actors:
        raise SchedulerContractError(f"phase {phase.phase_id!r} has no eligible actors")
    if any(not isinstance(actor, str) or not actor for actor in actors):
        raise SchedulerContractError(
            f"phase {phase.phase_id!r} returned an invalid actor identity"
        )
    if len(set(actors)) != len(actors):
        raise SchedulerContractError(
            f"phase {phase.phase_id!r} returned duplicate eligible actors"
        )
    missing = sorted(set(actors) - set(role_by_seat))
    if missing:
        raise SchedulerContractError(
            f"phase {phase.phase_id!r} returned unknown actors: {missing}"
        )
    if phase.mode == "single" and len(actors) != 1:
        raise SchedulerContractError(
            f"single phase {phase.phase_id!r} requires exactly one eligible actor"
        )
    for actor in actors:
        role = role_by_seat[actor]
        if role not in phase.observation_schema_by_role:
            raise SchedulerContractError(
                f"phase {phase.phase_id!r} has no observation schema for role {role!r}"
            )
        if role not in phase.action_schema_by_role:
            raise SchedulerContractError(
                f"phase {phase.phase_id!r} has no action schema for role {role!r}"
            )
    return actors


def _validate_transition(phase: PhaseSpec, transition: Any) -> TransitionResult:
    if not isinstance(transition, TransitionResult):
        raise SchedulerContractError(
            f"step for phase {phase.phase_id!r} must return TransitionResult"
        )
    if (
        transition.next_phase_id is not None
        and transition.next_phase_id not in phase.next_phases
    ):
        raise SchedulerContractError(
            f"phase {phase.phase_id!r} selected undeclared next phase "
            f"{transition.next_phase_id!r}"
        )
    return transition


async def _notify_action_failure(
    response_source: ResponseSource,
    logical_action_id: str,
    failure_code: str,
) -> None:
    callback = getattr(response_source, "fail_logical_action", None)
    if callback is None:
        return
    try:
        pending = callback(logical_action_id, failure_code=failure_code)
        if inspect.isawaitable(pending):
            await pending
    except Exception as error:
        raise SchedulerContractError(
            f"response source could not close {logical_action_id}: {error}"
        ) from error


async def _notify_lifecycle(
    response_source: ResponseSource, callback_name: str, **payload: Any
) -> None:
    callback = getattr(response_source, callback_name, None)
    if callback is None:
        return
    try:
        pending = callback(**payload)
        if inspect.isawaitable(pending):
            await pending
    except Exception as error:
        raise SchedulerContractError(
            f"response source lifecycle callback {callback_name!r} failed: {error}"
        ) from error


async def _notify_action_result(
    response_source: ResponseSource, record: LogicalActionRecord
) -> None:
    callback = getattr(response_source, "finalize_action", None)
    if callback is None:
        return
    try:
        pending = callback(record)
        if inspect.isawaitable(pending):
            await pending
    except Exception as error:
        raise SchedulerContractError(
            f"response source could not finalize {record.logical_action_id}: {error}"
        ) from error


async def _request_action(
    *,
    plugin: Any,
    family_case: Any,
    state: Any,
    cell: PlanCell,
    episode_id: str,
    phase: PhaseSpec,
    phase_instance_id: str,
    seat_id: str,
    role: str,
    observation: Any,
    action_ordinal: int,
    response_source: ResponseSource,
) -> LogicalActionRecord:
    logical_action_id = _stable_id(
        "logical_action",
        {
            "episode_id": episode_id,
            "phase_instance_id": phase_instance_id,
            "seat_id": seat_id,
            "action_ordinal": action_ordinal,
        },
    )
    request = DecisionRequest(
        episode_id=episode_id,
        phase_instance_id=phase_instance_id,
        logical_action_id=logical_action_id,
        cell_id=cell.cell_id,
        case_id=cell.case_id,
        phase_id=phase.phase_id,
        seat_id=seat_id,
        role=role,
        profile_id=cell.profile_by_seat[seat_id],
        observation_schema=phase.observation_schema_by_role[role],
        action_schema=phase.action_schema_by_role[role],
        observation=_freeze(observation),
    )
    try:
        pending_response = response_source(request)
        if not inspect.isawaitable(pending_response):
            raise TypeError("response_source must return an awaitable")
        raw_response = await pending_response
    except Exception as error:
        raise SchedulerContractError(
            f"response_source failed for {logical_action_id}: {error}"
        ) from error
    try:
        parsed = plugin.parse_action(
            family_case,
            _copy_for_hook(state, "parse state"),
            seat_id,
            phase,
            _copy_for_hook(raw_response, "canonical response"),
        )
    except Exception as error:
        await _notify_action_failure(
            response_source, logical_action_id, "parse_action_exception"
        )
        raise SchedulerContractError(
            f"parse_action failed for {logical_action_id}: {error}"
        ) from error
    if not isinstance(parsed, ParseResult):
        await _notify_action_failure(
            response_source, logical_action_id, "invalid_parse_result"
        )
        raise SchedulerContractError(
            f"parse_action for {logical_action_id} must return ParseResult"
        )
    legality: LegalityResult | None = None
    if parsed.ok:
        try:
            legality = plugin.legal(
                family_case,
                _copy_for_hook(state, "legality state"),
                seat_id,
                phase,
                _copy_for_hook(parsed.action, "parsed action"),
            )
        except Exception as error:
            await _notify_action_failure(
                response_source, logical_action_id, "legality_exception"
            )
            raise SchedulerContractError(
                f"legal failed for {logical_action_id}: {error}"
            ) from error
        if not isinstance(legality, LegalityResult):
            await _notify_action_failure(
                response_source, logical_action_id, "invalid_legality_result"
            )
            raise SchedulerContractError(
                f"legal for {logical_action_id} must return LegalityResult"
            )
    valid = parsed.ok and legality is not None and legality.legal
    failure_code = parsed.error_code if not parsed.ok else legality.reason
    envelope = ActionEnvelope(
        seat_id=seat_id,
        valid=valid,
        action=parsed.action if valid else None,
        parse=parsed,
        legality=legality,
    )
    record = LogicalActionRecord(
        logical_action_id=logical_action_id,
        seat_id=seat_id,
        request=request,
        response=_freeze(raw_response),
        parse=parsed,
        legality=legality,
        envelope=envelope,
    )
    await _notify_action_result(response_source, record)
    if not valid and phase.invalid_action_policy == "reject":
        raise SchedulerContractError(
            f"invalid action for seat {seat_id!r} in phase {phase.phase_id!r}: "
            f"{failure_code}"
        )
    return record


def _observe(
    *,
    plugin: Any,
    family_case: Any,
    state: Any,
    seat_id: str,
    phase: PhaseSpec,
) -> Any:
    try:
        observation = plugin.observe(
            family_case,
            _copy_for_hook(state, "observation state"),
            seat_id,
            phase,
        )
    except Exception as error:
        raise SchedulerContractError(
            f"observe failed for seat {seat_id!r} in phase {phase.phase_id!r}: {error}"
        ) from error
    _content_hash(observation, f"observation for {seat_id}")
    return _freeze(observation)


def _step(
    *,
    plugin: Any,
    family_case: Any,
    state: Any,
    phase: PhaseSpec,
    actions: Mapping[str, ActionEnvelope],
) -> TransitionResult:
    try:
        raw_transition = plugin.step(
            family_case,
            _copy_for_hook(state, "transition state"),
            phase,
            MappingProxyType(dict(actions)),
        )
    except Exception as error:
        raise SchedulerContractError(
            f"step failed for phase {phase.phase_id!r}: {error}"
        ) from error
    transition = _validate_transition(phase, raw_transition)
    _content_hash(transition.state, f"state returned by phase {phase.phase_id}")
    return TransitionResult(
        state=_freeze(transition.state),
        next_phase_id=transition.next_phase_id,
        consequences=transition.consequences,
    )


def _terminal(plugin: Any, family_case: Any, state: Any) -> Any:
    try:
        return plugin.terminal(
            family_case, _copy_for_hook(state, "terminal-check state")
        )
    except Exception as error:
        raise SchedulerContractError(f"terminal hook failed: {error}") from error


def _outcome(plugin: Any, family_case: Any, terminal: Any) -> Any:
    try:
        outcome = plugin.outcome(
            family_case, _copy_for_hook(terminal, "terminal result")
        )
    except Exception as error:
        raise SchedulerContractError(f"outcome hook failed: {error}") from error
    _content_hash(outcome, "family outcome")
    return outcome


def episode_id_for_cell(cell: PlanCell) -> str:
    """Derive the R3 episode identity for one sealed R2 plan cell."""
    if not isinstance(cell, PlanCell):
        raise TypeError("cell must be a PlanCell")
    return _stable_id(
        "episode", {"cell_id": cell.cell_id, "case_sha256": cell.case_sha256}
    )


async def run_episode(
    *,
    cell: PlanCell,
    case: CaseManifest,
    plugin: Any,
    response_source: ResponseSource,
) -> EpisodeResult:
    """Execute one resolved cell without owning or invoking a model provider."""
    role_by_seat = _validate_cell_case(cell, case)
    if not callable(response_source):
        raise SchedulerContractError("response_source must be callable")
    try:
        family_case = plugin.validate_payload(_copy_for_hook(case.payload, "case payload"))
        phases = _validate_phase_graph(plugin.phases(family_case))
        state = plugin.initial_state(family_case, cell)
    except SchedulerContractError:
        raise
    except Exception as error:
        raise SchedulerContractError(f"family preflight failed: {error}") from error
    _content_hash(state, "initial family state")

    phase_by_id = {phase.phase_id: phase for phase in phases}
    episode_id = episode_id_for_cell(cell)
    current_phase_id = phases[0].phase_id
    phase_ordinal = 0
    logical_action_count = 0
    phase_action_counts: dict[str, int] = {}
    instances: list[PhaseInstance] = []
    terminal = _terminal(plugin, family_case, state)

    while terminal is None:
        phase = phase_by_id[current_phase_id]
        phase_instance_id = _stable_id(
            "phase_instance",
            {
                "episode_id": episode_id,
                "phase_id": phase.phase_id,
                "ordinal": phase_ordinal,
            },
        )
        actors = _eligible_actors(plugin, family_case, state, phase, role_by_seat)
        pre_state_sha256 = _content_hash(state, "pre-phase state")
        await _notify_lifecycle(
            response_source,
            "phase_started",
            phase_instance_id=phase_instance_id,
            phase=phase,
            eligible_actors=actors,
            pre_state_sha256=pre_state_sha256,
        )
        observations: dict[str, Any] = {}
        action_records: list[LogicalActionRecord] = []
        transitions: list[TransitionResult] = []
        next_phase_id: str | None = None

        if phase.mode in {"single", "simultaneous"}:
            # Freeze every view before dispatch. Even a response source with
            # synchronous side effects cannot change a peer's observation.
            for seat_id in actors:
                observations[seat_id] = _observe(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    seat_id=seat_id,
                    phase=phase,
                )
            envelopes: dict[str, ActionEnvelope] = {}
            for seat_id in actors:
                logical_action_count += 1
                phase_action_counts[phase.phase_id] = (
                    phase_action_counts.get(phase.phase_id, 0) + 1
                )
                if logical_action_count > cell.case_max_logical_actions:
                    raise SchedulerContractError(
                        "case logical-action budget exceeded before termination"
                    )
                if phase_action_counts[phase.phase_id] > phase.max_logical_actions:
                    raise SchedulerContractError(
                        f"phase logical-action budget exceeded for {phase.phase_id!r}"
                    )
                record = await _request_action(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    cell=cell,
                    episode_id=episode_id,
                    phase=phase,
                    phase_instance_id=phase_instance_id,
                    seat_id=seat_id,
                    role=role_by_seat[seat_id],
                    observation=observations[seat_id],
                    action_ordinal=logical_action_count - 1,
                    response_source=response_source,
                )
                action_records.append(record)
                envelopes[seat_id] = record.envelope
            transition = _step(
                plugin=plugin,
                family_case=family_case,
                state=state,
                phase=phase,
                actions=envelopes,
            )
            transitions.append(transition)
            state = _copy_for_hook(transition.state, "post-transition state")
            await _notify_lifecycle(
                response_source,
                "transition_applied",
                phase_instance_id=phase_instance_id,
                phase=phase,
                transition=transition,
                post_state_sha256=_content_hash(state, "post-transition state"),
            )
            terminal = _terminal(plugin, family_case, state)
            next_phase_id = transition.next_phase_id
        else:
            for actor_index, seat_id in enumerate(actors):
                observations[seat_id] = _observe(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    seat_id=seat_id,
                    phase=phase,
                )
                logical_action_count += 1
                phase_action_counts[phase.phase_id] = (
                    phase_action_counts.get(phase.phase_id, 0) + 1
                )
                if logical_action_count > cell.case_max_logical_actions:
                    raise SchedulerContractError(
                        "case logical-action budget exceeded before termination"
                    )
                if phase_action_counts[phase.phase_id] > phase.max_logical_actions:
                    raise SchedulerContractError(
                        f"phase logical-action budget exceeded for {phase.phase_id!r}"
                    )
                record = await _request_action(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    cell=cell,
                    episode_id=episode_id,
                    phase=phase,
                    phase_instance_id=phase_instance_id,
                    seat_id=seat_id,
                    role=role_by_seat[seat_id],
                    observation=observations[seat_id],
                    action_ordinal=logical_action_count - 1,
                    response_source=response_source,
                )
                action_records.append(record)
                transition = _step(
                    plugin=plugin,
                    family_case=family_case,
                    state=state,
                    phase=phase,
                    actions={seat_id: record.envelope},
                )
                transitions.append(transition)
                state = _copy_for_hook(transition.state, "post-transition state")
                await _notify_lifecycle(
                    response_source,
                    "transition_applied",
                    phase_instance_id=phase_instance_id,
                    phase=phase,
                    transition=transition,
                    post_state_sha256=_content_hash(state, "post-transition state"),
                )
                terminal = _terminal(plugin, family_case, state)
                next_phase_id = transition.next_phase_id
                if terminal is not None or next_phase_id is not None:
                    break
                if actor_index == len(actors) - 1:
                    next_phase_id = None

        post_state_sha256 = _content_hash(state, "post-phase state")
        instance = PhaseInstance(
            phase_instance_id=phase_instance_id,
            phase_id=phase.phase_id,
            ordinal=phase_ordinal,
            mode=phase.mode,
            eligible_actors=actors,
            pre_state_sha256=pre_state_sha256,
            post_state_sha256=post_state_sha256,
            observations=_freeze(observations),
            actions=tuple(action_records),
            transitions=tuple(transitions),
        )
        instances.append(instance)
        await _notify_lifecycle(
            response_source,
            "phase_completed",
            phase_instance=instance,
        )
        if terminal is not None:
            break
        if next_phase_id is None:
            raise SchedulerContractError(
                f"nonterminal phase {phase.phase_id!r} did not select a next phase"
            )
        current_phase_id = next_phase_id
        phase_ordinal += 1

    outcome = _outcome(plugin, family_case, terminal)
    result = EpisodeResult(
        episode_id=episode_id,
        cell_id=cell.cell_id,
        case_id=case.case_id,
        family_id=case.family_id,
        final_state=_freeze(state),
        terminal=_freeze(terminal),
        outcome=_freeze(outcome),
        logical_action_count=logical_action_count,
        phase_instances=tuple(instances),
        world_seed=case.world_seed,
    )
    await _notify_lifecycle(
        response_source,
        "episode_completed",
        episode_result=result,
    )
    return result


__all__ = [
    "ActionEnvelope",
    "DecisionRequest",
    "EpisodeResult",
    "LegalityResult",
    "LogicalActionRecord",
    "ParseResult",
    "PhaseInstance",
    "PhaseSpec",
    "ResponseSource",
    "SchedulerContractError",
    "TransitionResult",
    "episode_id_for_cell",
    "run_episode",
]
