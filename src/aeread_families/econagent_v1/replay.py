"""Offline replayer for econagent_v1 episodes (spec section 5, milestone 3).

Given a RECORDED episode -- the ordered sequence of raw responses the real,
persistent upstream bridge subprocess already returned for one completed
live run -- rebuild the episode purely from that record and the pinned case,
through the same ``EconAgentV1Plugin``/scheduler machinery, with **the real
bridge subprocess never spawned**, and reproduce the final state and both
``rule_constraint`` leaves exactly. This is econagent_v1's analogue of
``tau3_retail/replay.py``'s "Replay =" guarantee, adapted to a materially
different seam:

Unlike tau3.retail (where the interesting, must-be-replayed-not-re-derived
external call is a *tool* invoked by an assistant seat's own action, so
``tau3_retail``'s replay substitutes the scheduler's ``ResponseSource``),
econagent_v1's seat action carries **no decision content at all** -- every
``agent_i`` seat submits the same acknowledgment every month (spec
milestone-1 correction 4), and the one call that actually determines state
-- ``complex_actions`` plus ``env.step``, run inside the persistent upstream
bridge subprocess -- is invoked directly by ``EconAgentV1Plugin.step()``,
never through the response source at all. Replaying "with the bridge process
disabled entirely" (spec section 5) therefore means substituting the
*bridge*, not the response source: this module records every call
``EconAgentV1Plugin``/``measurement.py`` make against a live
``EconAgentBridge`` (``RecordingEconAgentBridge``, a transparent wrapper
around a real bridge instance) and replays them, in the exact recorded
order, from a bridge-shaped double that spawns no subprocess at all
(``RecordedEconAgentBridge``) -- injected through ``EconAgentV1Plugin``'s
existing ``bridge_factory`` constructor seam, so the *scheduler path*
(``run_episode``/``PluginRegistry``/``PhaseSpec`` dispatch) is exactly the
real one, never a hand-wired shortcut.

``EconAgentV1Plugin.validate_payload`` still reads the pinned upstream
checkout directly (``config.yaml``/``data/profiles.json`` byte hashes, git
commit/status) during replay -- that is a plain, bridge-free file/git read
(mirrors ``cases.py``'s own bridge-free pin computation) and is *not* what
"bridge process disabled" refers to. Only the persistent bridge subprocess
that runs upstream's actual simulation is ever avoided during replay; the
pinned checkout itself must still be present on disk.

No tool body, database mutation, or scoring rule is reimplemented here:
every comparison either replays ``EconAgentV1Plugin``'s own step loop
(unchanged) against recorded bridge responses, or reuses ``measurement.py``'s
own scorers verbatim.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from .econagent_bridge import EconAgentBridge
from .environment import EconAgentV1Plugin, family_manifest, register_plugin
from .harness import ScriptedEconAgentHarness
from .measurement import EconAgentV1Scorer, ScoreEnvelope


class ReplayError(RuntimeError):
    """A recorded econagent_v1 episode could not be replayed offline.

    Covers replay-harness-level problems only (case/record mismatch, a
    bridge-call ordering mismatch against the record, or an unconsumed tail
    of recorded calls) -- never a divergence in the family's own accounting,
    which surfaces instead as a mismatched :class:`StateComparison` or
    :class:`ScoreEnvelope`, exactly like a real bridge failure would.
    """


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers.

    Same round trip through ``canonical_json_bytes`` that
    ``tau3_retail/replay.py``'s identical helper uses -- guarantees every
    recorded bridge response is a plain, ``json.dumps``-able structure,
    never a live object or a frozen scheduler container.
    """
    return json.loads(canonical_json_bytes(value))


# ---------------------------------------------------------------------------
# Recorded bridge call log: the actual "sealed evidence" this module replays.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordedBridgeCall:
    """One bridge method invocation and the plain-JSON response it returned."""

    method: str
    args: Mapping[str, Any]
    response: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "args": _plain(self.args),
            "response": _plain(self.response),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecordedBridgeCall":
        return cls(method=value["method"], args=value["args"], response=value["response"])


@dataclass(frozen=True, slots=True)
class RecordedEconAgentEpisode:
    """The complete, plain-JSON-serializable bridge call log for one episode.

    ``session_calls`` is the ordered call log of the ONE persistent bridge
    session ``EconAgentV1Plugin`` opens for the whole episode (spec
    milestone-1 correction 3): ``start_episode``, then ``step_month``/
    ``agent_snapshot`` pairs per month, then ``dense_log``/``close`` at
    termination -- in exactly that order, since that is the order
    ``environment.py``'s ``initial_state``/``step`` issue them.
    """

    case_id: str
    session_calls: tuple[RecordedBridgeCall, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_calls": [call.to_dict() for call in self.session_calls],
        }

    def to_json(self) -> str:
        """Serialize to a JSON string -- a genuinely portable, on-disk record."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RecordedEconAgentEpisode":
        return cls(
            case_id=value["case_id"],
            session_calls=tuple(
                RecordedBridgeCall.from_dict(call) for call in value["session_calls"]
            ),
        )

    @classmethod
    def from_json(cls, text: str) -> "RecordedEconAgentEpisode":
        return cls.from_dict(json.loads(text))


class RecordingEconAgentBridge:
    """Transparent observer wrapper: forwards every call to a real bridge.

    Used only to build a replayable record from a genuine, live bridge-driven
    episode or a genuine live ``recompute_tax`` scoring call -- the plugin/
    scorer still receives exactly ``inner``'s real return values; this is a
    pure recorder, never a source of state or scoring on its own. Appends one
    :class:`RecordedBridgeCall` per method invocation, in call order.
    """

    def __init__(self, inner: EconAgentBridge) -> None:
        self._inner = inner
        self.calls: list[RecordedBridgeCall] = []

    def _record(self, method: str, args: Mapping[str, Any], response: Any) -> None:
        self.calls.append(RecordedBridgeCall(method=method, args=_plain(args), response=response))

    def start_episode(self, **kwargs: Any) -> dict[str, Any]:
        response = self._inner.start_episode(**kwargs)
        self._record("start_episode", kwargs, response)
        return response

    def step_month(self) -> dict[str, Any]:
        response = self._inner.step_month()
        self._record("step_month", {}, response)
        return response

    def agent_snapshot(self) -> dict[str, Any]:
        response = self._inner.agent_snapshot()
        self._record("agent_snapshot", {}, response)
        return response

    def dense_log(self) -> dict[str, Any]:
        response = self._inner.dense_log()
        self._record("dense_log", {}, response)
        return response

    def recompute_tax(self, incomes: Mapping[str, float]) -> dict[str, dict[str, float]]:
        response = self._inner.recompute_tax(incomes)
        self._record("recompute_tax", {"incomes": incomes}, response)
        return response

    def close(self) -> None:
        self._inner.close()
        self._record("close", {}, None)


class RecordedEconAgentBridge:
    """A bridge-shaped double that spawns no subprocess: pure record replay.

    Serves each recorded call's response, in the exact recorded order, and
    raises :class:`ReplayError` on any ordering mismatch or on exhaustion --
    the same "recorded decision order does not match" contract
    ``tau3_retail/replay.py``'s ``RecordedResponseSource`` enforces at the
    response-source layer, enforced here at the bridge layer instead (see
    this module's docstring for why the seam differs).
    """

    def __init__(self, calls: Sequence[RecordedBridgeCall]) -> None:
        self._calls = tuple(calls)
        self._cursor = 0

    def _next(self, method: str, args: Mapping[str, Any] | None = None) -> Any:
        if self._cursor >= len(self._calls):
            raise ReplayError(
                f"recorded bridge calls exhausted before a {method!r} call was requested"
            )
        call = self._calls[self._cursor]
        self._cursor += 1
        if call.method != method:
            raise ReplayError(
                "recorded bridge call order does not match the replayed request: "
                f"expected {call.method!r}, got {method!r}"
            )
        if args is not None:
            replayed_args = _plain(args)
            if replayed_args != call.args:
                raise ReplayError(
                    "recorded bridge call arguments do not match the replayed "
                    f"request: {method!r} was recorded with args={call.args!r}, "
                    f"replayed with args={replayed_args!r}"
                )
        return call.response

    def start_episode(self, **kwargs: Any) -> Any:
        del kwargs
        return self._next("start_episode")

    def step_month(self) -> Any:
        return self._next("step_month")

    def agent_snapshot(self) -> Any:
        return self._next("agent_snapshot")

    def dense_log(self) -> Any:
        return self._next("dense_log")

    def recompute_tax(self, incomes: Mapping[str, float]) -> Any:
        """Serve the next recorded ``recompute_tax`` response.

        Unlike the other replayed methods, ``incomes`` is not discarded: it
        is the replayed episode's own re-derivation of each agent-month's
        income (``score_tax_bracket_arithmetic``'s ``incomes`` dict, built
        fresh from the replayed ``dense_log``), so it must equal the
        original live scoring call's own recorded ``args["incomes"]`` --
        otherwise a divergence in the replayed ``dense_log`` could silently
        reuse a stale recorded ``tax_due`` against different incomes and
        still report leaf 2 as ``"ok"`` (see this module's own review
        trail; call order alone cannot catch that class of bug).
        """
        return self._next("recompute_tax", args={"incomes": incomes})

    def close(self) -> None:
        # A recorded "close" entry is optional tail bookkeeping (the real
        # bridge's close() always succeeds and returns nothing meaningful);
        # consume it if present so `exhausted` reads True at the end of a
        # full, clean replay, but never raise here -- close() must be safe
        # to call unconditionally, mirroring EconAgentBridge.close()'s own
        # "safe to call more than once" contract.
        if self._cursor < len(self._calls) and self._calls[self._cursor].method == "close":
            self._cursor += 1

    @property
    def exhausted(self) -> bool:
        return self._cursor == len(self._calls)


# ---------------------------------------------------------------------------
# Recording a live episode (and a live tax-bracket scoring call) for replay.
# ---------------------------------------------------------------------------


def _recording_bridge_factory(
    upstream_root: Any, created: list[RecordingEconAgentBridge]
) -> Callable[[], RecordingEconAgentBridge]:
    def factory() -> RecordingEconAgentBridge:
        wrapper = RecordingEconAgentBridge(EconAgentBridge.discover(upstream_root))
        created.append(wrapper)
        return wrapper

    return factory


async def run_and_record_episode(
    *,
    cell: PlanCell,
    case: CaseManifest,
    upstream_root: Any,
    response_source: Any | None = None,
) -> tuple[EpisodeResult, RecordedEconAgentEpisode]:
    """Run one real episode end to end and record its bridge session's call log.

    Drives the REAL shared-runner path (``PluginRegistry``/``run_episode``),
    never a hand-wired step loop -- the only difference from a plain live run
    is that ``EconAgentV1Plugin``'s bridge is a recording wrapper around a
    real ``EconAgentBridge``, so every call it makes is captured for later
    offline replay.
    """
    created: list[RecordingEconAgentBridge] = []
    plugin = EconAgentV1Plugin(
        upstream_root=upstream_root,
        bridge_factory=_recording_bridge_factory(upstream_root, created),
    )
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    harness = response_source if response_source is not None else ScriptedEconAgentHarness()
    result = await run_episode(
        cell=cell, case=case, plugin=resolved_plugin, response_source=harness
    )
    if len(created) != 1:
        raise ReplayError(
            "expected exactly one bridge session per econagent_v1 episode "
            f"(spec milestone-1 correction 3), recorded {len(created)}"
        )
    recorded = RecordedEconAgentEpisode(case_id=case.case_id, session_calls=tuple(created[0].calls))
    return result, recorded


def score_tax_bracket_arithmetic_and_record(
    scorer: EconAgentV1Scorer,
    *,
    dense_log: Mapping[str, Any] | None,
    n_agents: int,
    upstream_root: Any,
) -> tuple[ScoreEnvelope, tuple[RecordedBridgeCall, ...]]:
    """Score leaf 2 for real and record its (separate, stateless) bridge calls.

    Mirrors ``measurement.py``'s own leaf-2 scoring exactly (a fresh,
    stateless bridge -- never the episode's own, already-closed, session
    bridge, per spec milestone-2 correction 4) but wraps that fresh bridge in
    a :class:`RecordingEconAgentBridge` so its ``recompute_tax`` calls can be
    replayed later with zero live calls.
    """
    bridge = RecordingEconAgentBridge(EconAgentBridge.discover(upstream_root))
    score = scorer.score_tax_bracket_arithmetic(
        dense_log=dense_log, n_agents=n_agents, bridge=bridge
    )
    return score, tuple(bridge.calls)


# ---------------------------------------------------------------------------
# Offline replay: zero bridge subprocess, zero live calls.
# ---------------------------------------------------------------------------


async def replay_episode(
    *,
    cell: PlanCell,
    case: CaseManifest,
    upstream_root: Any,
    recorded: RecordedEconAgentEpisode,
    response_source: Any | None = None,
) -> EpisodeResult:
    """Re-run one recorded episode with the real bridge subprocess disabled.

    Rebuilds ``initial_state`` from the pinned case/cell exactly as a live
    run would (``EconAgentV1Plugin.validate_payload`` still reads the pinned
    upstream checkout's files directly -- see this module's docstring for why
    that is not what "bridge disabled" refers to), but every call the plugin
    would otherwise make against a live persistent bridge subprocess is
    served instead from ``recorded.session_calls``, in order, by
    :class:`RecordedEconAgentBridge` -- no subprocess is ever spawned. Raises
    :class:`ReplayError` only for replay-harness-level problems (wrong case,
    a bridge-call ordering mismatch, an unconsumed record tail).
    """
    if recorded.case_id != case.case_id:
        raise ReplayError(
            f"recorded episode is for case {recorded.case_id!r}, not {case.case_id!r}"
        )
    replay_bridge = RecordedEconAgentBridge(recorded.session_calls)
    plugin = EconAgentV1Plugin(
        upstream_root=upstream_root, bridge_factory=lambda: replay_bridge
    )
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    harness = response_source if response_source is not None else ScriptedEconAgentHarness()
    result = await run_episode(
        cell=cell, case=case, plugin=resolved_plugin, response_source=harness
    )
    if not replay_bridge.exhausted:
        raise ReplayError(
            "replay terminated before every recorded bridge call was consumed"
        )
    return result


# ---------------------------------------------------------------------------
# Comparing a live run against its replay.
# ---------------------------------------------------------------------------


def _strip_bridge_session_id(value: Any) -> Any:
    """Recursively drop every ``"bridge_session_id"`` key from state-shaped values.

    ``EconAgentV1Plugin.initial_state`` mints a fresh ``uuid.uuid4().hex`` as
    the dict key it uses internally to look up the live bridge for this
    episode (``environment.py``: ``session_id = uuid.uuid4().hex``) -- pure
    adapter-internal bookkeeping, never surfaced through ``terminal()``/
    ``outcome()``, and never causally relevant to any accounting leaf. It is,
    however, part of the full per-phase ``state`` the scheduler hashes for
    ``pre_state_sha256``/``post_state_sha256`` and freezes into
    ``final_state`` -- discovered empirically while building this replayer
    (a live run replayed from its own exact recorded bridge call log still
    did not hash-match itself). Unlike ``tau3_retail``'s message timestamps
    (a real per-message field on every recorded response), this is a single,
    always-top-level key on the family's own ``state`` dict, so stripping it
    is a narrow, general (not task-specific) correction, not a broad rewrite
    of the comparison.
    """
    if isinstance(value, Mapping):
        return {
            key: _strip_bridge_session_id(item)
            for key, item in value.items()
            if key != "bridge_session_id"
        }
    if isinstance(value, (list, tuple)):
        return [_strip_bridge_session_id(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class StateComparison:
    """Component-level agreement between a live run and its offline replay.

    Two families of fields, deliberately kept distinct rather than collapsed
    into one number (mirrors ``tau3_retail/replay.py``'s identical split,
    for an analogous reason with a narrower cause here):

    * **Raw, byte-exact** (``state_hashes_match``, ``final_state_matches``):
      compares the scheduler's own sealed state exactly as sealed. Given
      ``EconAgentV1Plugin.initial_state``'s freshly-minted
      ``bridge_session_id`` (see ``_strip_bridge_session_id``), these are
      expected to read ``False`` for every replay -- a real, general
      property of the current adapter, not a bug in this comparator, and
      reported honestly rather than hidden.
    * **Semantic, session-id-independent** (``final_state_content_matches``,
      and ``matches`` overall): the actual replay guarantee this module
      exists to provide -- same terminal, same outcome, same economic state
      content (agents, world, dense_log, month_actions) once the one
      nondeterministic bookkeeping key is stripped.
    """

    phase_instance_count_matches: bool
    state_hashes_match: bool
    mismatched_phase_instance_ids: tuple[str, ...]
    terminal_matches: bool
    outcome_matches: bool
    final_state_matches: bool
    final_state_content_matches: bool

    @property
    def matches(self) -> bool:
        """The semantic replay guarantee: phase count, terminal, outcome,
        and final state *content* agree -- deliberately independent of the
        known, general-purpose ``bridge_session_id`` non-determinism
        documented on ``_strip_bridge_session_id`` and surfaced separately
        via ``state_hashes_match``/``final_state_matches``."""
        return (
            self.phase_instance_count_matches
            and self.terminal_matches
            and self.outcome_matches
            and self.final_state_content_matches
        )


def compare_episode_results(
    original: EpisodeResult, replayed: EpisodeResult
) -> StateComparison:
    """Compare a live run and its offline replay, component by component.

    Never raises on a mismatch: returns a typed report so callers (tests, a
    future parity harness) can assert on exactly what diverged.
    """
    original_instances = {
        instance.phase_instance_id: instance for instance in original.phase_instances
    }
    replayed_instances = {
        instance.phase_instance_id: instance for instance in replayed.phase_instances
    }
    count_matches = len(original.phase_instances) == len(replayed.phase_instances)
    mismatched_ids: list[str] = []
    shared_ids = sorted(set(original_instances) & set(replayed_instances))
    for phase_instance_id in shared_ids:
        left = original_instances[phase_instance_id]
        right = replayed_instances[phase_instance_id]
        if (
            left.pre_state_sha256 != right.pre_state_sha256
            or left.post_state_sha256 != right.post_state_sha256
        ):
            mismatched_ids.append(phase_instance_id)
    only_in_original = sorted(set(original_instances) - set(replayed_instances))
    only_in_replayed = sorted(set(replayed_instances) - set(original_instances))
    mismatched_ids.extend(only_in_original)
    mismatched_ids.extend(only_in_replayed)

    return StateComparison(
        phase_instance_count_matches=count_matches,
        state_hashes_match=not mismatched_ids,
        mismatched_phase_instance_ids=tuple(sorted(set(mismatched_ids))),
        terminal_matches=canonical_json_bytes(original.terminal)
        == canonical_json_bytes(replayed.terminal),
        outcome_matches=canonical_json_bytes(original.outcome)
        == canonical_json_bytes(replayed.outcome),
        final_state_matches=canonical_json_bytes(original.final_state)
        == canonical_json_bytes(replayed.final_state),
        final_state_content_matches=canonical_json_bytes(
            _strip_bridge_session_id(original.final_state)
        )
        == canonical_json_bytes(_strip_bridge_session_id(replayed.final_state)),
    )


def assert_replay_matches(comparison: StateComparison) -> None:
    """Raise :class:`ReplayError` with a specific reason if any component diverged."""
    if comparison.matches:
        return
    reasons = []
    if not comparison.phase_instance_count_matches:
        reasons.append("phase instance count differs")
    if not comparison.final_state_content_matches:
        reasons.append("final state content (agents/world/dense_log) differs")
    if not comparison.terminal_matches:
        reasons.append("terminal record differs")
    if not comparison.outcome_matches:
        reasons.append("outcome differs")
    raise ReplayError("replay diverged from the original run: " + "; ".join(reasons))


# ---------------------------------------------------------------------------
# Re-scoring a replayed episode -- zero live calls for either rule_constraint leaf.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplayScoreResult:
    """All three declared leaves recomputed from a replayed episode's own state."""

    budget_identity: ScoreEnvelope
    tax_bracket_arithmetic: ScoreEnvelope
    macro_trajectory: ScoreEnvelope


def score_replayed_episode(
    *,
    scorer: EconAgentV1Scorer,
    replayed: EpisodeResult,
    tax_recompute_calls: Sequence[RecordedBridgeCall],
) -> ReplayScoreResult:
    """Recompute all three declared leaves from a replayed episode, zero live calls.

    Leaves 1 (``econagent_budget_identity``) and 3 (``econagent_macro_trajectory``)
    are pure Python over the replayed episode's own ``terminal()`` output --
    no bridge involvement at all, live or recorded (see ``measurement.py``).
    Leaf 2 (``econagent_tax_bracket_arithmetic``) is recomputed by replaying
    the recorded ``recompute_tax`` calls from the original live scoring run
    (``tax_recompute_calls``, produced by
    :func:`score_tax_bracket_arithmetic_and_record`) through the same
    bridge-free :class:`RecordedEconAgentBridge` double this module uses for
    state replay -- never a fresh live bridge call.
    """
    terminal = replayed.terminal
    if not isinstance(terminal, Mapping):
        raise ReplayError(
            "score_replayed_episode requires a terminated episode with a "
            "mapping-shaped terminal record"
        )
    dense_log = terminal["dense_log"]
    n_agents = terminal["n_agents"]
    world_period = terminal["final_world"]["period"]
    month_actions = terminal["month_actions"]
    world_interest_rate_by_month = terminal["world_interest_rate_by_month"]

    budget_identity = scorer.score_budget_identity(
        dense_log=dense_log,
        n_agents=n_agents,
        world_period=world_period,
        month_actions=month_actions,
        world_interest_rate_by_month=world_interest_rate_by_month,
    )
    tax_bridge = RecordedEconAgentBridge(tax_recompute_calls)
    tax_bracket_arithmetic = scorer.score_tax_bracket_arithmetic(
        dense_log=dense_log, n_agents=n_agents, bridge=tax_bridge
    )
    if not tax_bridge.exhausted:
        raise ReplayError(
            "replay left recorded recompute_tax calls unconsumed for leaf 2"
        )
    macro_trajectory = scorer.score_macro_trajectory(
        dense_log=dense_log, n_agents=n_agents, month_actions=month_actions
    )
    return ReplayScoreResult(
        budget_identity=budget_identity,
        tax_bracket_arithmetic=tax_bracket_arithmetic,
        macro_trajectory=macro_trajectory,
    )


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The complete, auditable result of replaying and re-scoring one episode."""

    case_id: str
    replayed: EpisodeResult
    comparison: StateComparison | None
    scores: ReplayScoreResult

    @property
    def status(self) -> str:
        if self.comparison is not None and not self.comparison.matches:
            return "mismatch"
        return "match"


async def replay_and_verify(
    *,
    cell: PlanCell,
    case: CaseManifest,
    upstream_root: Any,
    scorer: EconAgentV1Scorer,
    recorded: RecordedEconAgentEpisode,
    tax_recompute_calls: Sequence[RecordedBridgeCall],
    original: EpisodeResult | None = None,
) -> ReplayReport:
    """End-to-end: replay a recorded episode, compare it, and re-score it.

    ``original`` is optional -- when supplied (e.g. immediately after the
    live recorded run), ``comparison`` reports full state-hash-level
    agreement; when absent (a genuinely offline replay from a previously
    written record, with no original run in memory), replay still runs and
    re-scores, and ``comparison`` is ``None`` -- an explicit, typed "not
    comparable" rather than a fabricated match.
    """
    replayed = await replay_episode(
        cell=cell, case=case, upstream_root=upstream_root, recorded=recorded
    )
    comparison = (
        compare_episode_results(original, replayed) if original is not None else None
    )
    scores = score_replayed_episode(
        scorer=scorer, replayed=replayed, tax_recompute_calls=tax_recompute_calls
    )
    return ReplayReport(
        case_id=case.case_id, replayed=replayed, comparison=comparison, scores=scores
    )


__all__ = [
    "RecordedBridgeCall",
    "RecordedEconAgentEpisode",
    "RecordedEconAgentBridge",
    "RecordingEconAgentBridge",
    "ReplayError",
    "ReplayReport",
    "ReplayScoreResult",
    "StateComparison",
    "assert_replay_matches",
    "compare_episode_results",
    "replay_and_verify",
    "replay_episode",
    "run_and_record_episode",
    "score_replayed_episode",
    "score_tax_bracket_arithmetic_and_record",
]
