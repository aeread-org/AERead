"""Component-level parity harness for the tau3.retail pilot (spec section 8).

For each pilot task this module:

1. Builds a "canonical upstream trajectory" from the task's own gold
   ``evaluation_criteria.actions`` -- the only reproducible, non-model
   trajectory tau2-bench ships per task -- and executes it two independent
   ways:

   * **upstream_direct**: each gold action is executed directly through
     ``Tau2Bridge.call_tool``, i.e. upstream's own ``Environment.get_response``,
     with no ``Tau3RetailPlugin``/scheduler involved at all.
   * **adapter**: the identical ordered gold actions, wrapped in the same
     synthetic opening/closing text, are scripted as one assistant burst
     and run through ``Tau3RetailPlugin``/``run_episode``/
     ``ScriptedTau3RetailHarness`` -- the real kernel-facing code path.

2. Compares the two runs COMPONENT BY COMPONENT -- never behind one
   pass/fail verdict -- using the shared kernel's own
   ``aeread.shared_runner.parity`` primitives: the initial database, the
   ordered tool calls, their ordered results, the final database, the
   deterministic DB-reward component, and (only for tasks whose
   ``nl_assertions`` are non-empty) the judged component's *inputs* --
   never its output, since that would require a live judge call, forbidden
   outright (rule 1).

3. Reports a typed, per-task result. A task that cannot be run (missing
   case file, unavailable bridge, an exception anywhere in construction)
   gets ``status="error"``/``status="skipped"`` and an explicit reason --
   never a silently truncated report. A component that cannot be compared
   for a specific task (most commonly ``nl_judge_inputs`` for the 13/18
   pilot tasks with no non-empty ``nl_assertions``) is represented as an
   explicit, typed ``{"available": False, "reason": ...}`` value on BOTH
   sides of the comparison, never omitted from the ``ParitySpec``.

This module never reimplements a tool body, a database mutation, or a
scoring rule: every comparison delegates to ``Tau2Bridge`` (upstream code)
or to ``Tau3RetailPlugin``/``measurement.py`` (the adapter's own real
production path), and the parity report only records what each side
already independently produced.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.parity import (
    ExternalParityCriterion,
    ParityField,
    ParityReport,
    ParitySpec,
    compare_projections,
)
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.resolver import PlanCell, canonical_json_bytes
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import EpisodeResult, run_episode

from . import measurement as measurement_module
from .cases import CASE_ID_PREFIX, PILOT_UPSTREAM_TASK_IDS, UPSTREAM_COMMIT
from .environment import Tau3RetailPlugin, family_manifest, register_plugin
from .harness import ScriptedTau3RetailHarness
from .tau2_bridge import (
    Tau2Bridge,
    Tau2BridgeUnavailableError,
    discover_bridge_python,
)

DEFAULT_CASES_DIR = Path("cases/tau3_retail/base")

# Shared, literal wording used identically to build BOTH the upstream_direct
# and the adapter trajectories, so any divergence in a downstream component
# (db_reward_component, nl_judge_inputs) reflects a real difference in how
# each side *executes* the identical gold actions, never an artifact of this
# harness phrasing the surrounding conversation differently on each side.
_SYNTHETIC_USER_OPENING = (
    "Please help me with the request described in this task's scenario."
)
_SYNTHETIC_ASSISTANT_CLOSING = "I've completed the requested actions."
_USER_STOP = "###STOP###"

PARITY_SPEC = ParitySpec(
    parity_id="tau3_retail_pilot_parity",
    parity_version="1.0.0",
    criterion=ExternalParityCriterion(
        task_id="tau2_retail_gold_action_pilot",
        treatment_id="aeread_adapter_vs_upstream_direct",
        metric_id="db_reward_component",
        source_reference=f"tau2-bench@{UPSTREAM_COMMIT}",
        original_conclusion=(
            "The upstream retail task's declared gold actions determine its "
            "database transition and deterministic database-reward inputs."
        ),
        tolerance_kind="exact",
        tolerance=0.0,
    ),
    fields=(
        ParityField("initial_database", ("initial_database",), ("initial_database",)),
        ParityField("ordered_tool_calls", ("ordered_tool_calls",), ("ordered_tool_calls",)),
        ParityField(
            "ordered_tool_results", ("ordered_tool_results",), ("ordered_tool_results",)
        ),
        ParityField("final_database", ("final_database",), ("final_database",)),
        ParityField(
            "db_reward_component", ("db_reward_component",), ("db_reward_component",)
        ),
        ParityField("nl_judge_inputs", ("nl_judge_inputs",), ("nl_judge_inputs",)),
    ),
)


class ParityRunError(RuntimeError):
    """A pilot task could not be run at all (distinct from a diverged component)."""


@dataclass(frozen=True, slots=True)
class ComponentResult:
    """One typed, always-present projection value for one parity component.

    Never a bare value: ``available=False`` plus an explicit ``reason`` is
    itself the typed result required when a component cannot be produced or
    compared for a task (spec: "a missing field must produce a typed result
    rather than aborting the whole report").
    """

    available: bool
    value: Any = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.available:
            return {"available": True, "value": self.value}
        return {"available": False, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PilotTaskResult:
    """The parity outcome for exactly one pilot task."""

    upstream_task_id: str
    case_id: str
    status: str  # "ran" | "skipped" | "error"
    reason: str | None
    report: ParityReport | None
    upstream_projection: Mapping[str, Any] | None
    adapted_projection: Mapping[str, Any] | None

    @property
    def matched(self) -> bool:
        return self.report is not None and self.report.status == "match"


@dataclass(frozen=True, slots=True)
class PilotParityReport:
    """The parity outcome for every requested pilot task, never truncated."""

    results: tuple[PilotTaskResult, ...]

    @property
    def ran(self) -> tuple[PilotTaskResult, ...]:
        return tuple(result for result in self.results if result.status == "ran")

    @property
    def matched(self) -> tuple[PilotTaskResult, ...]:
        return tuple(result for result in self.ran if result.matched)

    @property
    def mismatched(self) -> tuple[PilotTaskResult, ...]:
        return tuple(result for result in self.ran if not result.matched)

    @property
    def skipped(self) -> tuple[PilotTaskResult, ...]:
        return tuple(result for result in self.results if result.status == "skipped")

    @property
    def errored(self) -> tuple[PilotTaskResult, ...]:
        return tuple(result for result in self.results if result.status == "error")

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.results),
            "ran": len(self.ran),
            "matched": len(self.matched),
            "mismatched": len(self.mismatched),
            "skipped": len(self.skipped),
            "errored": len(self.errored),
        }


def _plain(value: Any) -> Any:
    """Detach the scheduler's frozen MappingProxyType/tuple containers.

    ``run_episode`` freezes every state/action value it hands back (see
    ``scheduler.py``'s ``_freeze``); ``Tau2Bridge`` methods ship their
    arguments straight to ``json.dumps`` in a subprocess call, so anything
    read off an ``EpisodeResult`` must be converted to a plain,
    JSON-native structure before it can be delegated.
    """
    return json.loads(canonical_json_bytes(value))


def _load_case_payload(cases_dir: Path, task_id: str) -> tuple[CaseManifest, dict[str, Any], dict[str, Any]]:
    path = cases_dir / f"{CASE_ID_PREFIX}.{task_id}.json"
    if not path.is_file():
        raise ParityRunError(f"no checked-in case file for task {task_id!r}: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    case = CaseManifest.from_dict(raw)
    payload = raw["payload"]
    return case, payload["task"], payload["pins"]


def _gold_actions(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    criteria = task.get("evaluation_criteria") or {}
    actions = criteria.get("actions") or []
    return [dict(action) for action in actions]


def _load_db_json(upstream_root: Path) -> dict[str, Any]:
    db_path = upstream_root / "data" / "tau2" / "domains" / "retail" / "db.json"
    return json.loads(db_path.read_text(encoding="utf-8"))


def _nl_judge_inputs_component(
    bridge: Tau2Bridge, task: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]
) -> ComponentResult:
    if not measurement_module.nl_assertions_present(task):
        return ComponentResult(
            available=False,
            reason=(
                "task has no non-empty nl_assertions; upstream's NL judge "
                "never fires for it (spec section 7)"
            ),
        )
    request = bridge.fetch_nl_assertions_judge_request(task=task, messages=list(messages))
    if not request["called"]:
        return ComponentResult(
            available=False,
            reason="upstream's NLAssertionsEvaluator made no judge call for this trajectory",
        )
    return ComponentResult(
        available=True,
        value={
            "model": request["model"],
            "messages": request["messages"],
            "call_name": request["call_name"],
            "args": request["args"],
        },
    )


def _run_upstream_direct(
    *,
    bridge: Tau2Bridge,
    upstream_root: Path,
    task: Mapping[str, Any],
    pins: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute the task's gold actions directly through upstream's own tool layer.

    No ``Tau3RetailPlugin``, no scheduler -- every ``bridge.call_tool`` here
    delegates straight to upstream's ``Environment.get_response``.
    """
    initial_db = bridge.normalize_db(_load_db_json(upstream_root))
    initial_db_hash = bridge.hash_db(initial_db)

    actions = _gold_actions(task)
    db = initial_db
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": pins["greeting_message"], "tool_calls": None},
        {"role": "user", "content": _SYNTHETIC_USER_OPENING, "tool_calls": None},
    ]
    for index, action in enumerate(actions):
        call_id = f"tc_{task['id']}_{index}"
        arguments = dict(action["arguments"])
        requestor = action.get("requestor", "assistant")
        response = bridge.call_tool(
            db=db,
            tool_name=action["name"],
            arguments=arguments,
            requestor=requestor,
            tool_call_id=call_id,
        )
        tool_calls.append({"id": call_id, "name": action["name"], "arguments": arguments})
        tool_results.append(
            {
                "tool_call_id": call_id,
                "name": action["name"],
                "content": response["content"],
                "error": response["error"],
                "db_hash": response["db_hash"],
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "name": action["name"],
                        "arguments": arguments,
                        "requestor": requestor,
                    }
                ],
            }
        )
        messages.append(response["tool_message"])
        db = response["db"]
    messages.append(
        {"role": "assistant", "content": _SYNTHETIC_ASSISTANT_CLOSING, "tool_calls": None}
    )
    messages.append({"role": "user", "content": _USER_STOP, "tool_calls": None})
    normalized_messages = bridge.normalize_messages(messages)
    final_db_hash = bridge.hash_db(db)

    db_reward = bridge.evaluate_env(task=task, messages=normalized_messages)[
        "reward_breakdown"
    ]["DB"]
    nl_judge_inputs = _nl_judge_inputs_component(bridge, task, normalized_messages)

    return {
        "initial_database": ComponentResult(True, initial_db_hash),
        "ordered_tool_calls": ComponentResult(True, tool_calls),
        "ordered_tool_results": ComponentResult(True, tool_results),
        "final_database": ComponentResult(True, final_db_hash),
        "db_reward_component": ComponentResult(True, db_reward),
        "nl_judge_inputs": nl_judge_inputs,
        "messages": normalized_messages,
    }


def _plan_cell(case: CaseManifest, *, suffix: str) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id=f"cell_tau3_retail_parity_{suffix}",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_tau3_retail_parity",
        suite_version="0.1.0",
        block_id="block_tau3_retail_parity",
        sampling_plan_id="sampling_tau3_retail_parity",
        analysis_plan_id="analysis_tau3_retail_parity",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id=f"cluster_tau3_retail_parity_{suffix}",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"assistant": "scripted_assistant", "user": "scripted_user"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )


def _run_adapter(
    *,
    bridge: Tau2Bridge,
    upstream_root: Path,
    case: CaseManifest,
    task: Mapping[str, Any],
    pins: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the identical gold actions through the real kernel-facing adapter path."""
    plugin = Tau3RetailPlugin(upstream_root=upstream_root, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())
    cell = _plan_cell(case, suffix=task["id"])

    initial_db = bridge.normalize_db(_load_db_json(upstream_root))
    initial_db_hash = bridge.hash_db(initial_db)

    actions = _gold_actions(task)
    assistant_messages: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        call_id = f"tc_{task['id']}_{index}"
        assistant_messages.append(
            {
                "tool_calls": [
                    {"id": call_id, "name": action["name"], "arguments": dict(action["arguments"])}
                ]
            }
        )
    assistant_messages.append({"content": _SYNTHETIC_ASSISTANT_CLOSING})

    with tempfile.TemporaryDirectory(prefix="tau3_retail_parity_") as tmp_dir:
        evidence = EvidenceStore(
            Path(tmp_dir) / "evidence",
            run_plan_id="runplan_tau3_retail_parity",
            cell_id=cell.cell_id,
            episode_id=f"episode_tau3_retail_parity_{task['id']}",
            episode_attempt_id="attempt_1",
        )
        harness = ScriptedTau3RetailHarness(
            bridge=bridge,
            initial_db=initial_db,
            evidence=evidence,
            script=[
                ("user_turn", {"content": _SYNTHETIC_USER_OPENING}),
                ("assistant_turn", {"messages": assistant_messages}),
                ("user_turn", {"content": _USER_STOP}),
            ],
        )
        result: EpisodeResult = asyncio.run(
            run_episode(cell=cell, case=case, plugin=resolved_plugin, response_source=harness)
        )

    assistant_instance = next(
        instance for instance in result.phase_instances if instance.phase_id == "assistant_turn"
    )
    assistant_action = assistant_instance.actions[0].envelope.action
    tool_calls = [
        {
            "id": execution["tool_call_id"],
            "name": execution["name"],
            "arguments": _plain(execution["arguments"]),
        }
        for execution in assistant_action["tool_executions"]
    ]
    tool_results = [
        {
            "tool_call_id": execution["tool_call_id"],
            "name": execution["name"],
            "content": execution["result"]["content"],
            "error": execution["result"]["error"],
            "db_hash": execution["post_db_hash"],
        }
        for execution in assistant_action["tool_executions"]
    ]

    scorer = resolved_plugin.build_scorer({"task": task, "pins": pins})
    final_messages = _plain(result.final_state["messages"])
    db_score = scorer.score_db_state(
        bridge=bridge,
        messages=final_messages,
        termination_reason=result.terminal["reason"],
    )
    nl_judge_inputs = _nl_judge_inputs_component(bridge, task, final_messages)

    return {
        "initial_database": ComponentResult(True, initial_db_hash),
        "ordered_tool_calls": ComponentResult(True, tool_calls),
        "ordered_tool_results": ComponentResult(True, tool_results),
        "final_database": ComponentResult(True, result.terminal["db_hash"]),
        "db_reward_component": ComponentResult(True, db_score.primary.value),
        "nl_judge_inputs": nl_judge_inputs,
        "episode_result": result,
    }


def run_pilot_task(
    *,
    bridge: Tau2Bridge,
    upstream_root: Path,
    task_id: str,
    cases_dir: Path = DEFAULT_CASES_DIR,
) -> PilotTaskResult:
    """Run and compare one pilot task, never raising for an ordinary failure.

    Any exception while constructing either trajectory is caught and turned
    into a typed ``status="error"`` result with the exact reason -- callers
    (``run_pilot``) can then report every task, including the ones that
    could not be run, without one bad task aborting the rest.
    """
    case_id = f"{CASE_ID_PREFIX}.{task_id}"
    try:
        case, task, pins = _load_case_payload(cases_dir, task_id)
        upstream = _run_upstream_direct(
            bridge=bridge, upstream_root=upstream_root, task=task, pins=pins
        )
        adapted = _run_adapter(
            bridge=bridge, upstream_root=upstream_root, case=case, task=task, pins=pins
        )
    except Exception as error:  # noqa: BLE001 - reported as a typed per-task result
        return PilotTaskResult(
            upstream_task_id=task_id,
            case_id=case_id,
            status="error",
            reason=f"{type(error).__name__}: {error}",
            report=None,
            upstream_projection=None,
            adapted_projection=None,
        )

    upstream_projection = {
        name: result.to_dict()
        for name, result in upstream.items()
        if isinstance(result, ComponentResult)
    }
    adapted_projection = {
        name: result.to_dict()
        for name, result in adapted.items()
        if isinstance(result, ComponentResult)
    }
    report = compare_projections(upstream_projection, adapted_projection, PARITY_SPEC)
    return PilotTaskResult(
        upstream_task_id=task_id,
        case_id=case_id,
        status="ran",
        reason=None,
        report=report,
        upstream_projection=upstream_projection,
        adapted_projection=adapted_projection,
    )


def run_pilot(
    *,
    bridge: Tau2Bridge | None,
    upstream_root: Path,
    task_ids: Sequence[str] = PILOT_UPSTREAM_TASK_IDS,
    cases_dir: Path = DEFAULT_CASES_DIR,
    bridge_unavailable_reason: str | None = None,
) -> PilotParityReport:
    """Run the full pilot parity procedure, reporting every task explicitly.

    When ``bridge`` is ``None`` (no pinned upstream interpreter is
    provisioned in this environment), every task is reported
    ``status="skipped"`` with ``bridge_unavailable_reason`` -- explicit and
    per-task, not one line for the whole run.
    """
    results: list[PilotTaskResult] = []
    for task_id in task_ids:
        if bridge is None:
            results.append(
                PilotTaskResult(
                    upstream_task_id=task_id,
                    case_id=f"{CASE_ID_PREFIX}.{task_id}",
                    status="skipped",
                    reason=bridge_unavailable_reason or "bridge unavailable",
                    report=None,
                    upstream_projection=None,
                    adapted_projection=None,
                )
            )
            continue
        results.append(
            run_pilot_task(
                bridge=bridge, upstream_root=upstream_root, task_id=task_id, cases_dir=cases_dir
            )
        )
    return PilotParityReport(tuple(results))


def main(argv: list[str] | None = None) -> int:
    """Run the pilot parity procedure and print a per-task receipt.

    The parity tests assert on two representative tasks; this runs the whole
    pilot and reports every task explicitly, so "the adapter reproduces
    upstream" is a result somebody can regenerate rather than a claim in a
    document. Exits non-zero unless every task ran and matched -- a skipped
    task is a failure here, because a skip is exactly how this suite hid the
    fact that its fidelity checks had never executed.
    """
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help=(
            "path to the pinned tau2-bench checkout "
            f"(commit {UPSTREAM_COMMIT})"
        ),
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="directory holding the imported case files",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="also write the full per-task report as JSON to this path",
    )
    args = parser.parse_args(argv)

    try:
        bridge: Tau2Bridge | None = Tau2Bridge(
            python_executable=discover_bridge_python(upstream_root=args.upstream_root),
            upstream_root=args.upstream_root,
        )
        unavailable_reason = None
    except Tau2BridgeUnavailableError as error:
        bridge = None
        unavailable_reason = str(error)

    report = run_pilot(
        bridge=bridge,
        upstream_root=args.upstream_root,
        cases_dir=args.cases_dir,
        bridge_unavailable_reason=unavailable_reason,
    )

    for result in report.results:
        if result.status == "ran" and result.report is not None:
            detail = result.report.status
            if result.report.mismatched_fields:
                detail += f"  mismatched: {list(result.report.mismatched_fields)}"
        else:
            detail = f"{result.status}: {result.reason}"
        print(f"task {result.upstream_task_id:>4}  {detail}")

    summary = report.summary()
    print(f"summary: {summary}")

    if args.json is not None:
        args.json.write_text(
            json.dumps(
                {
                    "upstream_commit": UPSTREAM_COMMIT,
                    "summary": summary,
                    "results": [
                        {
                            "upstream_task_id": result.upstream_task_id,
                            "case_id": result.case_id,
                            "status": result.status,
                            "reason": result.reason,
                            "parity_status": (
                                result.report.status if result.report else None
                            ),
                            "mismatched_fields": (
                                list(result.report.mismatched_fields)
                                if result.report
                                else None
                            ),
                        }
                        for result in report.results
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    clean = (
        summary["total"] > 0
        and summary["matched"] == summary["total"]
        and summary["mismatched"] == 0
        and summary["errored"] == 0
        and summary["skipped"] == 0
    )
    print("VERDICT:", "every pilot task matches upstream" if clean else "NOT CLEAN")
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ComponentResult",
    "DEFAULT_CASES_DIR",
    "PARITY_SPEC",
    "ParityRunError",
    "PilotParityReport",
    "PilotTaskResult",
    "main",
    "run_pilot",
    "run_pilot_task",
]
