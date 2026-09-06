"""QC Gate 2 goldens for econagent_v1 (docs/econagent_adapter_spec.md section 4).

Per ``docs/benchmark_qc.md``'s Gate 2 ("Environment and verifier"), every
family maintains five goldens: successful, valid-but-poor, invalid-or-
unauthorized, malformed-or-operational-failure, and degenerate-reference.
Milestone 1's spec left two of these flagged as needing re-derivation before
they could be built (section 4's "Not built this pass" note); the concrete
instances below resolve both, and are recorded here (rather than only in the
spec) as the actual, executable goldens:

* **Invalid or unauthorized** -- the literal spec text ("a hand-crafted
  out-of-range consumption action fed to the bridge's step call") assumed a
  seat that submits a real ``[labor, consumption]`` decision. Milestone-1
  correction 4 rules that out for this scripted-only pass: every seat
  submits a trivial acknowledgment, and the real decision is computed
  entirely inside the bridge. This golden instead demonstrates, at BOTH
  layers a real illegal/unauthorized input could appear:
    (a) kernel layer -- ``legal()``/``parse_action()`` reject a malformed
        seat action before ``step()`` is ever called, and ``step()`` itself
        refuses an incomplete/extra actions mapping without touching the
        bridge or any protected state;
    (b) bridge-protocol layer -- a hand-crafted extra field on a raw
        ``step_month`` request (attempting to inject an action, bypassing
        ``complex_actions`` entirely) has provably zero effect, because the
        driver's ``_op_step_month`` never reads any caller-supplied action
        field at all.
* **Degenerate reference** -- milestone-1 correction 7: a literal
  ``n_agents=1`` scenario fails upstream's own ``BaseEnvironment.__init__``
  assertion before any degenerate behavior could be observed. This uses
  ``n_agents=2``, upstream's actual floor, where ``PeriodicBracketTax``'s
  lump-sum redistribution is well-defined but degenerate (self-funding: two
  agents fully fund each other's redistribution).

All five goldens run through the real bridge (they depend on the real
upstream engine for budget/tax arithmetic) and are skipped, honestly, when
no provisioned bridge interpreter is available -- following
``tests/test_econagent_environment.py``'s ``_require_bridge()`` convention.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import PlanCell
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.scheduler import SchedulerContractError, run_episode
from aeread_families.econagent_v1 import econagent_bridge as econagent_bridge_module
from aeread_families.econagent_v1.econagent_bridge import (
    EconAgentBridge,
    EconAgentBridgeError,
    EconAgentBridgeMutationOutcomeUnknownError,
    EconAgentBridgeUnavailableError,
    discover_bridge_python,
)
from aeread_families.econagent_v1.environment import (
    EconAgentV1Plugin,
    family_manifest,
    register_plugin,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_ECONAGENT_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-econagent",
    )
    root = Path(candidate)
    if not (root / "config.yaml").is_file():
        pytest.skip(
            f"pinned upstream EconAgent checkout not found at {root}",
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except EconAgentBridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _require_bridge() -> None:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    os.environ["AEREAD_ECONAGENT_BRIDGE_PYTHON"] = str(BRIDGE_PYTHON)


def _case(case_id: str = "econagent.pilot.small10x12.seed0") -> CaseManifest:
    path = Path("cases/econagent_v1") / f"{case_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    """Mirrors ``test_econagent_e2e.py``'s ``_cell`` -- a real ``PlanCell``
    for driving this case through the real scheduler (``run_episode``)."""
    n_agents = case.payload["scenario"]["n_agents"]
    profile_by_seat = {
        f"agent_{index}": "econagent_v1_scripted_complex" for index in range(n_agents)
    }
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_econagent_golden_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_econagent_golden",
        suite_version="0.1.0",
        block_id="block_econagent_golden",
        sampling_plan_id="sampling_econagent_golden",
        analysis_plan_id="analysis_econagent_golden",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_econagent_golden_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(profile_by_seat),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _scenario_payload(
    *,
    case_id: str,
    n_agents: int,
    episode_length: int,
    world_seed: int,
    beta: float = 0.1,
    gamma: float = 0.1,
    h: float = 1.0,
    pins: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an ad hoc payload for a scenario shape not in cases.py's pinned table.

    Pins never depend on n_agents/episode_length/beta/gamma/h (they pin the
    upstream source, not a specific scenario instance), so reusing a real
    case's pins is faithful, not a shortcut -- mirrors
    ``test_econagent_environment.py``'s existing tamper-payload pattern.
    """
    real_pins = dict(pins if pins is not None else _case().payload["pins"])
    return {
        "scenario": {
            "case_id": case_id,
            "n_agents": n_agents,
            "episode_length": episode_length,
            "world_seed": world_seed,
            "beta": beta,
            "gamma": gamma,
            "h": h,
            "purpose": "golden test fixture",
        },
        "pins": real_pins,
    }


def _run_episode(
    plugin: EconAgentV1Plugin, payload: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Run one episode to termination; return (family_case, terminal, n_agents)."""
    family_case = plugin.validate_payload(payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, run=None)
    n_agents = family_case["scenario"]["n_agents"]
    while state["termination"] is None:
        actors = plugin.eligible_actors(family_case, state, phase)
        actions = {
            seat: plugin.parse_action(family_case, state, seat, phase, {"acknowledge": True})
            for seat in actors
        }
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
    terminal = plugin.terminal(family_case, state)
    return family_case, terminal, n_agents


# ---------------------------------------------------------------------------
# Golden 1: successful.
# ---------------------------------------------------------------------------


def test_golden_successful_full_run_holds_every_accounting_identity_exactly() -> None:
    """Full 12-month complex run, 10 agents, default beta=gamma=0.1, h=1.

    Assert: every month's per-agent budget identity holds exactly (leaf 1),
    every tax_paid matches upstream's own bracket computation (leaf 2),
    dense_log length == 12, no bridge error.
    """
    _require_bridge()
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    case = _case("econagent.pilot.small10x12.seed0")
    family_case, terminal, n_agents = _run_episode(plugin, case.payload)

    assert terminal["reason"] == "episode_length_reached"
    assert terminal["episode_length"] == 12
    assert len(terminal["dense_log"]["PeriodicTax"]) == 12
    assert len(terminal["dense_log"]["states"]) == 13  # post-reset + 12 months

    scorer = plugin.build_scorer(family_case)
    world_period = terminal["final_world"]["period"]
    budget_score = scorer.score_budget_identity(
        dense_log=terminal["dense_log"],
        n_agents=n_agents,
        world_period=world_period,
        month_actions=terminal["month_actions"],
        world_interest_rate_by_month=terminal["world_interest_rate_by_month"],
    )
    assert budget_score.status == "ok"
    assert budget_score.primary.value == 1.0
    assert budget_score.metrics["violation_count"].value == 0.0

    bridge = EconAgentBridge.discover(UPSTREAM_ROOT)
    tax_score = scorer.score_tax_bracket_arithmetic(
        dense_log=terminal["dense_log"], n_agents=n_agents, bridge=bridge
    )
    assert tax_score.status == "ok"
    assert tax_score.primary.value == 1.0
    assert tax_score.metrics["violation_count"].value == 0.0


# ---------------------------------------------------------------------------
# Golden 2: valid but poor.
# ---------------------------------------------------------------------------


def test_golden_valid_but_poor_stays_fully_accounted_and_never_scored_as_a_failure() -> None:
    """Same scenario, beta=5.0 -- depresses consumption without breaking legality.

    Assert: the trajectory stays legal and fully accounted (budget/tax
    leaves still pass exactly); the macro diagnostic (leaf 3) shows
    depressed GDP-proxy relative to the default-beta run -- recorded as a
    diagnostic outcome, never a failure (leaf 3 has no pass/fail meaning at
    all; only its comparatively lower native value is asserted).
    """
    _require_bridge()
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    case = _case("econagent.pilot.small10x12.seed0")

    default_family_case, default_terminal, n_agents = _run_episode(plugin, case.payload)
    poor_payload = _scenario_payload(
        case_id="econagent.golden.poor10x12.seed0",
        n_agents=10,
        episode_length=12,
        world_seed=0,
        beta=5.0,
        pins=case.payload["pins"],
    )
    poor_family_case, poor_terminal, _n_agents = _run_episode(plugin, poor_payload)

    assert poor_terminal["reason"] == "episode_length_reached"  # stayed legal to completion

    default_scorer = plugin.build_scorer(default_family_case)
    poor_scorer = plugin.build_scorer(poor_family_case)
    world_period = poor_terminal["final_world"]["period"]

    for scorer, terminal in (
        (default_scorer, default_terminal),
        (poor_scorer, poor_terminal),
    ):
        budget_score = scorer.score_budget_identity(
            dense_log=terminal["dense_log"],
            n_agents=n_agents,
            world_period=world_period,
            month_actions=terminal["month_actions"],
            world_interest_rate_by_month=terminal["world_interest_rate_by_month"],
        )
        assert budget_score.primary.value == 1.0
        bridge = EconAgentBridge.discover(UPSTREAM_ROOT)
        tax_score = scorer.score_tax_bracket_arithmetic(
            dense_log=terminal["dense_log"], n_agents=n_agents, bridge=bridge
        )
        assert tax_score.primary.value == 1.0

    default_macro = default_scorer.score_macro_trajectory(
        dense_log=default_terminal["dense_log"],
        n_agents=n_agents,
        month_actions=default_terminal["month_actions"],
    )
    poor_macro = poor_scorer.score_macro_trajectory(
        dense_log=poor_terminal["dense_log"],
        n_agents=n_agents,
        month_actions=poor_terminal["month_actions"],
    )
    # Diagnostic only -- both remain "ok", neither is a scored failure.
    assert default_macro.status == "ok"
    assert poor_macro.status == "ok"
    assert poor_macro.primary.value < default_macro.primary.value  # depressed GDP-proxy


# ---------------------------------------------------------------------------
# Golden 3: invalid or unauthorized.
# ---------------------------------------------------------------------------


def test_golden_invalid_action_never_reaches_step_and_touches_no_protected_state() -> None:
    """Kernel layer: an illegal/malformed seat action never mutates state."""
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    case = _case("econagent.pilot.tiny4x6.seed0")
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]

    malformed = plugin.parse_action(family_case, {}, "agent_0", phase, {"acknowledge": False})
    assert not malformed.ok  # rejected before it could ever become an "action"

    unauthorized_seat = plugin.parse_action(
        family_case, {}, "planner", phase, {"acknowledge": True}
    )
    legality = plugin.legal(family_case, {}, "planner", phase, {"acknowledge": True})
    assert not unauthorized_seat.ok
    assert not legality.legal

    # Simulate "if this illegal/unauthorized action had incorrectly been
    # forwarded to step()": submit fewer seats than required (as if the
    # rejected seat's contribution were simply dropped, the correct
    # behavior). step() must refuse outright and must never call the
    # bridge/mutate the passed-in state object.
    _require_bridge()
    registry_plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=registry_plugin)
    state = registry_plugin.initial_state(family_case, run=None)
    n_agents = family_case["scenario"]["n_agents"]
    actors = registry_plugin.eligible_actors(family_case, state, phase)
    incomplete_actions = {
        seat: registry_plugin.parse_action(family_case, state, seat, phase, {"acknowledge": True})
        for seat in list(actors)[: n_agents - 1]  # missing exactly one seat
    }
    original_state_snapshot = dict(state)
    with pytest.raises(RuntimeError, match="expected acknowledgments from all"):
        registry_plugin.step(family_case, state, phase, incomplete_actions)
    # Protected state (agents/world/bridge session) is completely unchanged --
    # step() raised before ever calling the bridge.
    assert state == original_state_snapshot
    assert state["timestep"] == 0

    # Clean up the still-open session this test started.
    for session_id in list(registry_plugin._sessions):
        registry_plugin._sessions[session_id].close()
        registry_plugin._sessions.pop(session_id)


def test_golden_invalid_action_never_reaches_step_via_the_real_scheduler() -> None:
    """Strengthens the golden above: the claim ("an illegal seat action never
    reaches step()/mutates protected state") is proven here against the REAL
    scheduler path (``aeread.shared_runner.task.scheduler.run_episode``), not
    only the hand-wired plugin-hook loop the previous golden exercises.

    One seat (``agent_0``) submits a malformed response (``parse_action``
    rejects it, per milestone-1 correction 4's acknowledgment-only
    contract); the real scheduler's ``invalid_action_policy="reject"``
    (``environment.py``'s ``AGENT_MONTH_PHASE``) must raise
    ``SchedulerContractError`` from inside its per-seat action loop, before
    it ever reaches the phase's single post-loop ``step()`` call. Proven,
    not merely asserted, by making ``EconAgentV1Plugin.step`` itself raise
    if it is ever invoked -- if the scheduler's own reject-before-step
    ordering ever regressed, this test would fail on a mismatched exception
    message (``"step failed for phase"`` instead of ``"invalid action for
    seat"``), not silently pass.
    """
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    cell = _cell(case, suffix="illegal-seat-real-scheduler")

    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    def _step_must_not_be_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "run_episode must never call step() when a seat's action is illegal"
        )

    async def _one_illegal_seat_response_source(request: Any) -> dict[str, Any]:
        if request.seat_id == "agent_0":
            return {"acknowledge": False}  # malformed -- parse_action rejects it
        return {"acknowledge": True}

    original_step = EconAgentV1Plugin.step
    EconAgentV1Plugin.step = _step_must_not_be_called  # type: ignore[assignment]
    try:
        with pytest.raises(SchedulerContractError, match="invalid action for seat"):
            asyncio.run(
                run_episode(
                    cell=cell,
                    case=case,
                    plugin=resolved_plugin,
                    response_source=_one_illegal_seat_response_source,
                )
            )
    finally:
        EconAgentV1Plugin.step = original_step  # type: ignore[assignment]
        # Clean up the still-open session `initial_state` opened before the
        # illegal action was ever discovered.
        for session_id in list(plugin._sessions):
            plugin._sessions[session_id].close()
            plugin._sessions.pop(session_id)


def test_golden_a_hand_crafted_bridge_request_cannot_bypass_complex_actions() -> None:
    """Bridge-protocol layer: an injected 'actions' field on step_month is a no-op.

    Sends a raw, hand-crafted request directly to the bridge subprocess
    (bypassing the ``EconAgentBridge.step_month()`` public API entirely,
    which accepts no caller-supplied action at all) carrying an
    out-of-range, invented action payload. Compares the resulting state
    against an untampered parallel run with the identical seed: the driver's
    own ``_op_step_month`` never reads any caller-supplied action field, so
    the tampered request must produce byte-identical results to a clean one
    -- proof, not assertion, that no hand-crafted input can reach
    ``env.step`` except through the real ``complex_actions`` computation.
    """
    _require_bridge()

    clean = EconAgentBridge.discover(UPSTREAM_ROOT)
    clean.start_episode(n_agents=4, episode_length=2, world_seed=0, beta=0.1, gamma=0.1, h=1.0)
    clean.step_month()
    clean_snapshot = clean.agent_snapshot()
    clean.close()

    tampered = EconAgentBridge.discover(UPSTREAM_ROOT)
    tampered.start_episode(n_agents=4, episode_length=2, world_seed=0, beta=0.1, gamma=0.1, h=1.0)
    # Reach past the public API on purpose: a hand-crafted, out-of-contract
    # request the real client never sends.
    response = tampered._request(
        {
            "op": "step_month",
            "actions": {"0": [999, 999], "1": [-5, -5]},  # out-of-range, invented
        }
    )
    assert response["ok"] is True  # driver ignored the extra field, did not error
    tampered_snapshot = tampered.agent_snapshot()
    tampered.close()

    assert tampered_snapshot["agents"] == clean_snapshot["agents"]
    assert tampered_snapshot["world"] == clean_snapshot["world"]


# ---------------------------------------------------------------------------
# Golden 4: malformed or operational failure.
# ---------------------------------------------------------------------------


def test_golden_bridge_killed_mid_episode_yields_a_typed_failure_never_a_scored_zero() -> None:
    """SIGKILL the bridge subprocess between months; assert a typed failure.

    Assert: step() raises a typed ``EconAgentBridgeError`` (never a
    fabricated zero-credit result on any leaf), and the episode's own
    ``state["termination"]`` remains ``None`` -- no partial, silently-
    committed state is ever treated as terminal.
    """
    _require_bridge()
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    case = _case("econagent.pilot.small10x12.seed0")
    family_case = plugin.validate_payload(case.payload)
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, run=None)
    n_agents = family_case["scenario"]["n_agents"]

    # Run months 1-5 normally.
    for _ in range(5):
        actors = plugin.eligible_actors(family_case, state, phase)
        actions = {
            seat: plugin.parse_action(family_case, state, seat, phase, {"acknowledge": True})
            for seat in actors
        }
        transition = plugin.step(family_case, state, phase, actions)
        state = transition.state
        assert state["termination"] is None

    # Kill the bridge subprocess out from under the plugin, between month 5
    # and month 6.
    bridge = plugin._sessions[state["bridge_session_id"]]
    bridge._process.kill()
    bridge._process.wait(timeout=10)

    actors = plugin.eligible_actors(family_case, state, phase)
    actions = {
        seat: plugin.parse_action(family_case, state, seat, phase, {"acknowledge": True})
        for seat in actors
    }
    pre_failure_state = dict(state)
    with pytest.raises(EconAgentBridgeError):
        plugin.step(family_case, state, phase, actions)

    # The original state object (the one the scheduler would still be
    # holding) is untouched -- no partial commit, no silent termination.
    assert state == pre_failure_state
    assert state["termination"] is None
    assert state["timestep"] == 5

    # Clean up (the process is already dead; this just drops the handle).
    plugin._sessions.pop(state["bridge_session_id"], None)


def test_request_raises_a_distinctly_typed_error_when_a_step_month_response_never_arrives() -> None:
    """Pure, no subprocess: ``EconAgentBridge._request``'s own dispatch logic
    must raise :class:`EconAgentBridgeMutationOutcomeUnknownError` -- never
    the plain :class:`EconAgentBridgeError` an ordinary bridge failure
    raises -- specifically for a ``step_month`` request whose response never
    arrives (docs/econagent_codex_triage.md finding 3: the driver's real
    mutation runs before it writes and flushes a response, so this ambiguity
    can never be safely treated the same as "the month was never
    attempted"). A minimal fake process double (write succeeds, then EOF on
    read) exercises the real, unmodified ``_request`` method deterministically.
    """

    class _EOFStdout:
        def readline(self) -> str:
            return ""  # EOF: no response ever arrives

    class _FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = _EOFStdout()
            self.stderr = io.StringIO("simulated crash")

        def poll(self) -> int:
            return -9  # simulated SIGKILL exit code

    bridge = EconAgentBridge(
        python_executable=Path("/nonexistent/python"),
        upstream_root=UPSTREAM_ROOT,
    )
    bridge._process = _FakeProcess()  # type: ignore[assignment]

    with pytest.raises(EconAgentBridgeMutationOutcomeUnknownError):
        bridge._request({"op": "step_month"})


def test_request_raises_the_generic_error_when_a_non_mutating_response_never_arrives() -> None:
    """Companion guard: an op other than ``step_month`` hitting the exact
    same "no response ever arrives" branch must still raise the plain,
    generic ``EconAgentBridgeError`` -- proving the new, more specific
    exception type is scoped to the one genuinely ambiguous, mutating
    request, not applied indiscriminately to every bridge failure."""

    class _EOFStdout:
        def readline(self) -> str:
            return ""

    class _FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = _EOFStdout()
            self.stderr = io.StringIO("simulated crash")

        def poll(self) -> int:
            return -9

    bridge = EconAgentBridge(
        python_executable=Path("/nonexistent/python"),
        upstream_root=UPSTREAM_ROOT,
    )
    bridge._process = _FakeProcess()  # type: ignore[assignment]

    with pytest.raises(EconAgentBridgeError) as excinfo:
        bridge._request({"op": "agent_snapshot"})
    assert not isinstance(excinfo.value, EconAgentBridgeMutationOutcomeUnknownError)


def test_golden_a_lost_step_month_response_is_a_distinctly_typed_mutation_outcome_unknown_error() -> None:
    """Regression test for the "mutation can precede every durable outcome"
    finding (docs/econagent_codex_triage.md finding 3):
    ``econagent_bridge_driver.py`` calls the real, mutating
    ``env.step(actions)`` before writing and flushing its response; if the
    process crashes in that window, upstream has already executed the month
    even though the caller never receives a result -- a retry could not
    distinguish "not executed" from "executed, response lost".

    A hand-crafted, test-only fault-injection marker on an otherwise-real
    ``step_month`` request (``_test_crash_before_responding``, reachable
    only by this test, never by any real caller -- see
    ``econagent_bridge_driver.py``'s own docstring) performs the exact same
    real mutation ``_op_step_month`` performs and then exits immediately
    without responding, deterministically reproducing this exact race
    through the real upstream engine, never a mock. Assert the caller
    receives the distinctly-typed
    :class:`EconAgentBridgeMutationOutcomeUnknownError`, never the generic
    :class:`EconAgentBridgeError`, so this ambiguity can never be silently
    mistaken for "the month was never attempted".
    """
    _require_bridge()
    bridge = EconAgentBridge.discover(UPSTREAM_ROOT)
    bridge.start_episode(n_agents=4, episode_length=6, world_seed=0, beta=0.1, gamma=0.1, h=1.0)
    try:
        with pytest.raises(EconAgentBridgeMutationOutcomeUnknownError):
            bridge._request(
                {"op": "step_month", "_test_crash_before_responding": True}
            )
    finally:
        # The process already exited on its own (os._exit inside the
        # driver's crash op) -- mirrors the "bridge killed mid-episode"
        # golden's own cleanup: calling bridge.close() here would try to
        # write another request into an already-broken pipe, so just reap
        # the dead process and drop the handle instead.
        if bridge._process is not None:
            bridge._process.wait(timeout=10)
            bridge._process = None


def test_golden_a_lost_step_month_response_aborts_the_whole_episode_via_the_real_scheduler() -> None:
    """Strengthens the golden above (docs/econagent_codex_triage.md finding
    3), which only exercises ``EconAgentBridge._request`` directly. A later,
    independent cross-model verification pass
    (docs/econagent_fix_verification.md) found that fix's own regression
    tests "asserted only a new exception type" without ever proving what
    happens to a real, in-flight episode -- this drives the identical lost-
    response race through the REAL production path
    (``aeread.shared_runner.task.scheduler.run_episode``) and proves the
    documented "abandon this episode's session for good, never retry"
    consequence actually holds end to end there too.

    Why the underlying race itself is not "fixed away" here, and cannot be
    without a kernel change or a product decision (see
    ``docs/econagent_adapter_status.md``'s "Known limits" for the narrowed
    claim): the driver's real, mutating ``env.step(actions)``
    (``econagent_bridge_driver.py``'s ``_op_step_month``) necessarily runs
    BEFORE its response is computed and flushed, because the response's own
    content (timestep, done, the real upstream-computed actions) IS that
    mutation's result -- there is no way to confirm success before running
    it. And because one driver subprocess is a bare in-memory Python ``env``
    object serving exactly one episode with no on-disk journal, a crashed
    process can never be resumed or interrogated after the fact. Eliminating
    the ambiguity would require either modifying the pinned upstream engine
    itself (forbidden by this adapter's own spec) or adding a full state-
    journaling/recovery layer neither this adapter nor the shared kernel has
    today. What this test proves instead is that the ambiguity's one safe
    consequence -- discard the whole episode, no partial state, no partial
    score, no silent retry -- is what the real production path actually
    does, not merely what an isolated ``_request()`` call raises.

    ``EconAgentBridge._request`` is monkeypatched, for its own first
    ``step_month`` call only, to add the real driver's crash fault-injection
    marker (the same one the golden above uses) to the outgoing request --
    every other request (``reset``, and any later ``step_month`` calls, of
    which there are none here since the episode aborts on month 1) passes
    through completely unmodified. Everything downstream of that single
    substitution is completely real: the real driver subprocess, the real
    crash, the real ``EconAgentV1Plugin.step``, the real ``run_episode``/
    scheduler.
    """
    _require_bridge()
    case = _case("econagent.pilot.tiny4x6.seed0")
    cell = _cell(case, suffix="lost-step-month-real-scheduler")

    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    async def _all_seats_acknowledge(request: Any) -> dict[str, Any]:
        del request
        return {"acknowledge": True}

    original_request = econagent_bridge_module.EconAgentBridge._request
    fault_injected = {"count": 0}

    def _request_that_loses_its_first_step_month_response(
        self: "EconAgentBridge", request: Mapping[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if request.get("op") == "step_month" and fault_injected["count"] == 0:
            fault_injected["count"] += 1
            request = dict(request)
            request["_test_crash_before_responding"] = True
        return original_request(self, request, **kwargs)

    econagent_bridge_module.EconAgentBridge._request = (  # type: ignore[assignment]
        _request_that_loses_its_first_step_month_response
    )
    try:
        with pytest.raises(SchedulerContractError, match="step failed for phase") as excinfo:
            asyncio.run(
                run_episode(
                    cell=cell,
                    case=case,
                    plugin=resolved_plugin,
                    response_source=_all_seats_acknowledge,
                )
            )
        # The whole episode aborted as a scheduler contract failure -- never
        # a completed EpisodeResult, never a partially-scored month -- and
        # the wrapped cause is the same distinctly-typed exception the
        # isolated-_request golden above asserts, proving the classification
        # survives the full production path, not just a direct call.
        assert isinstance(
            excinfo.value.__cause__, EconAgentBridgeMutationOutcomeUnknownError
        )
        assert fault_injected["count"] == 1  # the fault fired exactly once, as intended
    finally:
        econagent_bridge_module.EconAgentBridge._request = original_request  # type: ignore[assignment]
        # The crashed subprocess already exited on its own (os._exit inside
        # the driver's crash op) -- reap it and drop the handle, mirroring
        # the isolated-_request golden's identical cleanup above; never call
        # bridge.close(), which would try to write into an already-broken
        # pipe.
        for session_id in list(plugin._sessions):
            bridge = plugin._sessions.pop(session_id)
            if bridge._process is not None:
                bridge._process.wait(timeout=10)


class _StdoutThatMustNeverBeReadDirectly:
    """A fake ``stdout`` standing in for a genuinely hung peer: it reports a
    working file descriptor (so ``_readline_with_timeout`` takes its real,
    select-polled path rather than the "not backed by a real fd" fallback
    branch meant only for a fileno-less double), but its ``readline()`` never
    blocks -- it raises immediately.

    This is the crux of the finding-7-verification fix
    (docs/econagent_fix_verification.md): the ORIGINAL version of these two
    tests used a real OS pipe whose write end nothing ever wrote to, so
    ``readline()`` genuinely blocked forever. That is correct when the
    bounded-wait fix is present (``_readline_with_timeout`` never reaches
    ``readline()`` before the deadline kills the process), but reverting
    JUST the fix restores a direct, unbounded ``process.stdout.readline()``
    call -- which, against a real never-written pipe, hangs the test itself
    rather than failing it. Swapping in this trap instead means a reverted
    guard is caught the INSTANT it tries to read directly, with a fast,
    deterministic ``AssertionError`` -- never a hang -- while a correct,
    still-bounded implementation never calls this method at all (it always
    kills and raises once the deadline passes, before ever reading).
    """

    def fileno(self) -> int:
        return 999  # a placeholder fd; the fake select below never touches the OS

    def readline(self) -> str:
        raise AssertionError(
            "stdout.readline() was called directly, bypassing the bounded "
            "select.select wait -- exactly what a reverted read-timeout "
            "guard would do. Failing fast here instead of hanging is the "
            "whole point of this test (docs/econagent_fix_verification.md "
            "finding 7)."
        )


class _FakeSelectModuleThatNeverReportsReady:
    """Stands in for the ``select`` module ``econagent_bridge.py`` imports,
    recording every bounded-wait call it receives and always reporting "not
    ready" -- modelling a subprocess that is genuinely, indefinitely hung.
    Never touches a real file descriptor or the OS select() syscall, so this
    can never itself block."""

    def __init__(self) -> None:
        self.remaining_seen: list[float] = []

    def select(
        self, rlist: Any, wlist: Any, xlist: Any, timeout: float
    ) -> tuple[list[Any], list[Any], list[Any]]:
        self.remaining_seen.append(timeout)
        return ([], [], [])


class _FakeHungProcess:
    def __init__(self, stdout: Any) -> None:
        self.stdin = io.StringIO()
        self.stdout = stdout
        self.stderr = io.StringIO("still running")
        self.killed = False

    def poll(self) -> None:
        return None  # still "running" -- never exited on its own

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> None:
        return None


def test_readline_with_timeout_raises_before_a_hung_step_month_response_blocks_forever() -> None:
    """Pure, no bridge subprocess required: reproduces
    docs/econagent_codex_triage.md finding 7 ("persistent requests do not
    enforce their timeout") deterministically, without needing the real
    upstream engine to actually hang.

    Restructured per docs/econagent_fix_verification.md's own follow-up
    finding on this exact test: the earlier version waited on a real,
    never-written OS pipe, which is fast when the fix is present but HANGS
    (rather than fails) if the fix is ever reverted -- a hang on regression
    is worse than no test, since CI stalls instead of reporting red. This
    now asserts on the bounded-wait MECHANISM's own observable behaviour
    (``select.select`` was actually called, bounded by ``timeout_seconds``,
    and a working, non-blocking fake stands in for a genuinely hung peer)
    rather than by ever letting an actually-unbounded call run:

    * With the fix present, ``_readline_with_timeout`` only ever calls the
      fake ``select.select`` (never the trap ``readline()``, since "ready"
      is never reported), observably bounded by ``self.timeout_seconds``,
      kills the fake hung process, and raises the typed
      ``EconAgentBridgeMutationOutcomeUnknownError`` -- fast, deterministic,
      never a real wait on anything slow.
    * If the fix is reverted (a direct, unbounded ``process.stdout.readline()``
      restored), the trap's ``readline()`` raises ``AssertionError``
      immediately -- failing this test in milliseconds, never hanging.
    """
    fake_stdout = _StdoutThatMustNeverBeReadDirectly()
    fake_select = _FakeSelectModuleThatNeverReportsReady()
    fake_process = _FakeHungProcess(fake_stdout)

    bridge = EconAgentBridge(
        python_executable=Path("/nonexistent/python"),
        upstream_root=UPSTREAM_ROOT,
        timeout_seconds=0.05,
    )
    bridge._process = fake_process  # type: ignore[assignment]

    original_select = econagent_bridge_module.select
    econagent_bridge_module.select = fake_select  # type: ignore[assignment]
    try:
        started = time.monotonic()
        with pytest.raises(EconAgentBridgeMutationOutcomeUnknownError):
            bridge._request({"op": "step_month"})
        elapsed = time.monotonic() - started
    finally:
        econagent_bridge_module.select = original_select  # type: ignore[assignment]

    assert elapsed < 1.0  # bounded by timeout_seconds, nowhere near a hang
    assert fake_select.remaining_seen  # the bounded-wait mechanism actually ran
    assert all(
        0 < remaining <= bridge.timeout_seconds for remaining in fake_select.remaining_seen
    )
    assert fake_process.killed  # the hung process was actually reaped


def test_readline_with_timeout_raises_the_generic_error_for_a_hung_non_mutating_request() -> None:
    """Companion guard, mirroring
    ``test_request_raises_the_generic_error_when_a_non_mutating_response_never_arrives``
    above: an op other than ``step_month`` hitting the same timeout branch
    must still raise the plain, generic ``EconAgentBridgeError``, proving
    the timeout fix reuses finding 3's existing step_month-vs-everything-
    else distinction rather than applying the mutation-specific error
    indiscriminately. Restructured for the same hang-to-fail reason as the
    test above -- see its docstring."""
    fake_stdout = _StdoutThatMustNeverBeReadDirectly()
    fake_select = _FakeSelectModuleThatNeverReportsReady()
    fake_process = _FakeHungProcess(fake_stdout)

    bridge = EconAgentBridge(
        python_executable=Path("/nonexistent/python"),
        upstream_root=UPSTREAM_ROOT,
        timeout_seconds=0.05,
    )
    bridge._process = fake_process  # type: ignore[assignment]

    original_select = econagent_bridge_module.select
    econagent_bridge_module.select = fake_select  # type: ignore[assignment]
    try:
        with pytest.raises(EconAgentBridgeError) as excinfo:
            bridge._request({"op": "agent_snapshot"})
    finally:
        econagent_bridge_module.select = original_select  # type: ignore[assignment]

    assert not isinstance(excinfo.value, EconAgentBridgeMutationOutcomeUnknownError)
    assert fake_select.remaining_seen
    assert fake_process.killed


def test_golden_a_hung_step_month_request_times_out_instead_of_blocking_forever() -> None:
    """Regression test for finding 7 (docs/econagent_codex_triage.md):
    "persistent requests do not enforce their timeout". Unlike finding 3's
    crash marker (which closes the pipe immediately, so even the pre-fix
    code detected it via a normal EOF), this fault injector
    (``_test_hang_before_responding``) performs the real mutation and then
    blocks forever, keeping the driver subprocess and its stdout pipe alive
    -- exactly the case the pre-fix ``process.stdout.readline()`` could
    never detect regardless of ``timeout_seconds``. A short
    ``timeout_seconds`` bridge asserts the caller gets the same distinctly-
    typed :class:`EconAgentBridgeMutationOutcomeUnknownError` well within a
    few seconds, not the driver's own multi-hour sleep, through the real
    upstream engine, never a mock.

    Restructured per docs/econagent_fix_verification.md's follow-up finding
    on this exact test: this golden must keep exercising the REAL bridge
    subprocess and the REAL driver hang (no fake stands in for either --
    that would defeat the point of a golden), so unlike the pure test above,
    the underlying wait genuinely depends on production code behaving. If
    the read-timeout guard were ever reverted, the previous version of this
    test called ``bridge._request(...)`` directly in the test's own thread
    and would have blocked for up to the driver's multi-hour sleep instead
    of failing -- stalling CI rather than reporting red. The call now runs
    on a background thread with a bounded, TEST-OWNED join: a small, fixed
    wall-clock bound that is enforced by this test regardless of whether the
    code under test behaves, so a regressed guard fails this test fast
    (within that bound) rather than hanging it.
    """
    _require_bridge()
    # Full default timeout for start_episode (spawning the subprocess and
    # importing/constructing the real upstream env takes longer than the
    # short timeout below); only the hung request itself needs a short one.
    bridge = EconAgentBridge.discover(UPSTREAM_ROOT)
    bridge.start_episode(n_agents=4, episode_length=6, world_seed=0, beta=0.1, gamma=0.1, h=1.0)
    bridge.timeout_seconds = 1.0

    outcome: dict[str, Any] = {}

    def _run_the_potentially_hanging_request() -> None:
        started = time.monotonic()
        try:
            bridge._request({"op": "step_month", "_test_hang_before_responding": True})
        except BaseException as error:  # noqa: BLE001 -- carried across the thread boundary
            outcome["error"] = error
        outcome["elapsed"] = time.monotonic() - started

    worker = threading.Thread(target=_run_the_potentially_hanging_request, daemon=True)
    worker.start()
    # A generous but FINITE bound owned by this test, independent of
    # `bridge.timeout_seconds` -- comfortably above the configured 1.0s
    # timeout, nowhere near the driver's multi-hour sleep. This bound, not
    # the production code, is what guarantees "fails fast, never hangs".
    worker.join(timeout=15.0)
    try:
        if worker.is_alive():
            # The read-timeout guard did not fire -- kill the hung
            # subprocess so the leaked thread unblocks and this process
            # doesn't sit on an indefinitely-sleeping child, then fail fast
            # rather than hang the suite.
            if bridge._process is not None:
                bridge._process.kill()
            pytest.fail(
                "bridge._request did not return within 15s of a hung "
                "step_month request -- the read-timeout guard appears to "
                "have regressed (this must fail fast, never hang)"
            )
        error = outcome.get("error")
        assert isinstance(error, EconAgentBridgeMutationOutcomeUnknownError), (
            f"expected EconAgentBridgeMutationOutcomeUnknownError, got {error!r}"
        )
        assert outcome["elapsed"] < 10.0  # bounded by timeout_seconds, not the driver's hang
    finally:
        # _readline_with_timeout already killed the hung subprocess on
        # timeout -- just reap it and drop the handle (mirrors the crash
        # golden's identical cleanup above).
        if bridge._process is not None:
            bridge._process.wait(timeout=10)
            bridge._process = None


# ---------------------------------------------------------------------------
# Golden 5: degenerate reference.
# ---------------------------------------------------------------------------


def test_golden_degenerate_two_agent_lump_sum_reports_the_real_computed_value() -> None:
    """n_agents=2 (upstream's actual floor, per milestone-1 correction 7).

    ``PeriodicBracketTax``'s redistribution divides collected tax by
    ``n_agents``; with exactly two agents this is a well-defined but
    degenerate (mutually self-funding) special case. Assert the adapter
    reports the actual computed lump_sum rather than suppressing or
    replacing this edge case, and that the budget identity still holds
    exactly at this floor.
    """
    _require_bridge()
    plugin = EconAgentV1Plugin(upstream_root=UPSTREAM_ROOT)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)

    payload = _scenario_payload(
        case_id="econagent.golden.degenerate2x3.seed0",
        n_agents=2,
        episode_length=3,
        world_seed=0,
    )
    family_case, terminal, n_agents = _run_episode(plugin, payload)
    assert n_agents == 2
    assert terminal["reason"] == "episode_length_reached"

    dense_log = terminal["dense_log"]
    for month_tax in dense_log["PeriodicTax"]:
        lump_sum_0 = month_tax["0"]["lump_sum"]
        lump_sum_1 = month_tax["1"]["lump_sum"]
        # Real, finite, computed values -- never suppressed/replaced/None.
        assert isinstance(lump_sum_0, float)
        assert lump_sum_0 == lump_sum_1  # net_tax_revenue split two ways, evenly
        assert lump_sum_0 >= 0.0

    scorer = plugin.build_scorer(family_case)
    world_period = terminal["final_world"]["period"]
    budget_score = scorer.score_budget_identity(
        dense_log=dense_log,
        n_agents=n_agents,
        world_period=world_period,
        month_actions=terminal["month_actions"],
        world_interest_rate_by_month=terminal["world_interest_rate_by_month"],
    )
    assert budget_score.status == "ok"
    assert budget_score.primary.value == 1.0
    assert budget_score.metrics["checked_agent_months"].value == 2 * 3
