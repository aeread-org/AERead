"""Provider-free scheduler coverage for the tau3.retail environment plugin."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from aeread.shared_runner.execution import EvidenceStore
from aeread.shared_runner.registry import (
    REQUIRED_FAMILY_PLUGIN_HOOKS,
    PluginRegistry,
)
from aeread.shared_runner.resolver import (
    PlanCell,
    canonical_json_bytes,
)
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.scheduler import run_episode
from aeread.shared_runner.scheduler import SchedulerContractError
from aeread_families.tau3_retail.environment import (
    Tau3RetailPlugin,
    family_manifest,
    register_plugin,
)
from aeread_families.tau3_retail.harness import ScriptedTau3RetailHarness
from aeread_families.tau3_retail.tau2_bridge import (
    Tau2Bridge,
    Tau2BridgeUnavailableError,
    discover_bridge_python,
)


def _upstream_root() -> Path:
    candidate = os.environ.get(
        "AEREAD_TAU2_UPSTREAM_ROOT",
        "/Users/sunzeyu/Documents/econ benchmark/upstream-tau2",
    )
    root = Path(candidate)
    marker = root / "data" / "tau2" / "domains" / "retail" / "tasks.json"
    if not marker.is_file():
        pytest.skip(
            f"pinned upstream tau2-bench checkout not found at {root}",
            # Every test in this module needs the checkout, so skipping the
            # module is the intent. Without this flag pytest treats a
            # module-level skip as an error and the whole file fails to
            # collect -- which is what CI hit, since CI has no checkout.
            allow_module_level=True,
        )
    return root


UPSTREAM_ROOT = _upstream_root()

try:
    BRIDGE_PYTHON = discover_bridge_python(upstream_root=UPSTREAM_ROOT)
except Tau2BridgeUnavailableError as error:
    BRIDGE_PYTHON = None
    _BRIDGE_SKIP_REASON = str(error)
else:
    _BRIDGE_SKIP_REASON = ""


def _bridge() -> Tau2Bridge:
    if BRIDGE_PYTHON is None:
        pytest.skip(_BRIDGE_SKIP_REASON or "bridge python unavailable")
    return Tau2Bridge(
        python_executable=BRIDGE_PYTHON,
        upstream_root=UPSTREAM_ROOT,
    )


def _case(task_id: str = "73") -> CaseManifest:
    path = Path("cases/tau3_retail_base") / f"tau3.retail.base.{task_id}.json"
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _cell(case: CaseManifest) -> PlanCell:
    return PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_tau3_retail_environment",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_tau3_retail_environment",
        suite_version="0.1.0",
        block_id="block_tau3_retail_environment",
        sampling_plan_id="sampling_tau3_retail_environment",
        analysis_plan_id="analysis_tau3_retail_environment",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_tau3_retail_environment",
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


RETURN_ARGUMENTS = {
    "item_ids": ["7228247242", "2698416822", "8098621301", "3320557165"],
    "order_id": "#W5272531",
    "payment_method_id": "credit_card_6824399",
}


def test_plugin_registers_every_required_hook_through_normal_registry() -> None:
    plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    registry = PluginRegistry()
    manifest = family_manifest()
    registered = register_plugin(registry, plugin=plugin)

    assert registered is plugin
    assert registry.resolve_manifest(manifest) is plugin
    assert set(REQUIRED_FAMILY_PLUGIN_HOOKS) == {
        name
        for name in REQUIRED_FAMILY_PLUGIN_HOOKS
        if callable(getattr(plugin, name, None))
    }
    family_case = json.loads(canonical_json_bytes(_case().payload))
    phases = plugin.phases(family_case)
    assert [(phase.phase_id, phase.mode, phase.next_phases) for phase in phases] == [
        ("user_turn", "single", ("assistant_turn",)),
        ("assistant_turn", "single", ("user_turn",)),
    ]


def test_checked_in_null_schema_pin_is_accepted_only_as_a_declared_derivation_gap() -> None:
    plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)

    family_case = plugin.validate_payload(_case().payload)
    assert family_case["pins"]["tool_schema_sha256"] is None
    assert family_case["pins"]["tool_schema_sha256_unavailable_reason"]


def test_bridge_runtime_is_offline_and_loaded_from_the_pinned_checkout() -> None:
    runtime = _bridge().runtime_info()

    assert runtime["python_version"].startswith("3.12.")
    assert Path(runtime["tau2_package_file"]).resolve().is_relative_to(
        (UPSTREAM_ROOT / "src" / "tau2").resolve()
    )
    assert runtime["local_model_cost_map"] == "True"
    assert runtime["dont_write_bytecode"] == "1"


def test_scripted_real_task_runs_end_to_end_through_kernel_scheduler(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case = _case()
    cell = _cell(case)
    plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    raw_db = json.loads(
        (UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json").read_text(
            encoding="utf-8"
        )
    )
    normalized_db = bridge.normalize_db(raw_db)
    expected = bridge.call_tool(
        db=normalized_db,
        tool_name="return_delivered_order_items",
        arguments=RETURN_ARGUMENTS,
        tool_call_id="call_return_items",
    )
    assert expected["error"] is False

    evidence = EvidenceStore(
        tmp_path / "evidence",
        run_plan_id="runplan_tau3_retail_environment",
        cell_id=cell.cell_id,
        episode_id="episode_tau3_retail_environment",
        episode_attempt_id="attempt_tau3_retail_environment",
    )
    scripted = ScriptedTau3RetailHarness(
        bridge=bridge,
        initial_db=normalized_db,
        evidence=evidence,
        script=[
            (
                "user_turn",
                {
                    "content": (
                        "Please return the four non-coffee items from order "
                        "#W5272531 to my card."
                    )
                },
            ),
            (
                "assistant_turn",
                {
                    "messages": [
                        {
                            "tool_calls": [
                                {
                                    "id": "call_get_order",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "#W5272531"},
                                }
                            ]
                        },
                        {
                            "tool_calls": [
                                {
                                    "id": "call_return_items",
                                    "name": "return_delivered_order_items",
                                    "arguments": RETURN_ARGUMENTS,
                                }
                            ]
                        },
                        {
                            "content": (
                                "The four non-coffee items have been returned."
                            )
                        },
                    ]
                },
            ),
            ("user_turn", {"content": "###STOP###"}),
        ],
    )
    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            response_source=scripted,
        )
    )

    # One user decision, one assistant decision containing the whole tool burst,
    # then one user decision that ends the conversation.
    assert result.logical_action_count == 3
    assert scripted.exhausted is True
    assert [instance.phase_id for instance in result.phase_instances] == [
        "user_turn",
        "assistant_turn",
        "user_turn",
    ]
    assert len(result.phase_instances[1].actions) == 1
    assert len(result.phase_instances[1].actions[0].envelope.action["messages"]) == 3
    assistant_action = result.phase_instances[1].actions[0].envelope.action
    assert [execution["name"] for execution in assistant_action["tool_executions"]] == [
        "get_order_details",
        "return_delivered_order_items",
    ]

    assert result.terminal["reason"] == "user_stop"
    assert result.final_state["upstream_step_count"] == 7
    assert result.final_state["num_tool_errors"] == 0
    assert canonical_json_bytes(result.final_state["db"]) == canonical_json_bytes(
        expected["db"]
    )
    assert result.final_state["db_hash"] == expected["db_hash"]
    assert result.final_state["live_tool_schema_sha256"] == bridge.fetch_tool_schema()[
        "tool_schema_sha256"
    ]
    assert canonical_json_bytes(result.outcome) == canonical_json_bytes(
        {
            "termination_reason": "user_stop",
            "final_db_sha256": expected["db_hash"],
            "upstream_step_count": 7,
            "message_count": 8,
        }
    )
    canonical_json_bytes(result.final_state)
    thawed_messages = json.loads(canonical_json_bytes(result.final_state["messages"]))
    assert canonical_json_bytes(bridge.normalize_messages(thawed_messages)) == (
        canonical_json_bytes(result.final_state["messages"])
    )
    thawed_final_db = json.loads(canonical_json_bytes(result.final_state["db"]))
    assert canonical_json_bytes(bridge.normalize_db(thawed_final_db)) == (
        canonical_json_bytes(expected["db"])
    )

    evidence.verify_chain()
    assert [event.event_type for event in evidence.read_events()] == [
        "tool_invocation_started",
        "tool_invocation_succeeded",
        "tool_invocation_started",
        "tool_invocation_succeeded",
    ]

    assistant_observation = scripted.requests[1].observation
    assert "user_scenario" not in assistant_observation
    assert "Please return" in canonical_json_bytes(assistant_observation).decode()
    assert "fatima.wilson5721@example.com" not in canonical_json_bytes(
        assistant_observation
    ).decode()

    final_user_observation = scripted.requests[2].observation
    serialized_user_view = canonical_json_bytes(final_user_observation).decode()
    assert all(
        message.get("tool_calls") is None
        for message in final_user_observation["messages"]
    )
    assert all(message["role"] != "tool" for message in final_user_observation["messages"])
    assert "return_delivered_order_items" not in serialized_user_view
    assert "The four non-coffee items have been returned." in serialized_user_view


def test_step_counts_tool_errors_and_still_records_the_erroring_tool_message(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    case = _case()
    cell = _cell(case)
    plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
    registry = PluginRegistry()
    register_plugin(registry, plugin=plugin)
    resolved_plugin = registry.resolve_manifest(family_manifest())

    raw_db = json.loads(
        (UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json").read_text(
            encoding="utf-8"
        )
    )
    normalized_db = bridge.normalize_db(raw_db)
    initial_db_hash = bridge.hash_db(normalized_db)

    # Verify empirically -- never assume -- that this call genuinely errors
    # upstream, and inspect upstream's own real response before building the
    # trajectory around it: a nonexistent order id upstream itself rejects
    # in-band (no exception), and (per this real response) leaves the DB
    # byte-for-byte unchanged since the call never reaches a mutation.
    probe = bridge.call_tool(
        db=normalized_db,
        tool_name="get_order_details",
        arguments={"order_id": "#W0000000"},
        tool_call_id="call_bad_order",
    )
    assert probe["error"] is True
    assert probe["content"] == "Error: Order not found"
    assert probe["db_hash"] == initial_db_hash
    assert canonical_json_bytes(probe["db"]) == canonical_json_bytes(normalized_db)

    evidence = EvidenceStore(
        tmp_path / "error_evidence",
        run_plan_id="runplan_tau3_retail_error",
        cell_id=cell.cell_id,
        episode_id="episode_tau3_retail_error",
        episode_attempt_id="attempt_tau3_retail_error",
    )
    scripted = ScriptedTau3RetailHarness(
        bridge=bridge,
        initial_db=normalized_db,
        evidence=evidence,
        script=[
            ("user_turn", {"content": "Please check order #W0000000."}),
            (
                "assistant_turn",
                {
                    "messages": [
                        {
                            "tool_calls": [
                                {
                                    "id": "call_bad_order",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "#W0000000"},
                                }
                            ]
                        },
                        {"content": "I could not find that order, sorry."},
                    ]
                },
            ),
            ("user_turn", {"content": "###STOP###"}),
        ],
    )

    result = asyncio.run(
        run_episode(
            cell=cell,
            case=case,
            plugin=resolved_plugin,
            response_source=scripted,
        )
    )

    assert result.terminal["reason"] == "user_stop"
    assert result.final_state["num_tool_errors"] == 1
    assert result.terminal["num_tool_errors"] == 1

    # Upstream records an erroring tool call as an in-band tool result
    # message; it is never dropped from the transcript.
    tool_messages = [
        message for message in result.final_state["messages"] if message["role"] == "tool"
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0]["error"] is True
    assert tool_messages[0]["content"] == "Error: Order not found"
    assert tool_messages[0]["id"] == "call_bad_order"

    # The erroring call is verified above to leave upstream's own db_hash
    # unchanged, so the whole episode's final db_hash still matches the
    # untouched initial db -- no other tool call ran in this trajectory.
    assert result.final_state["db_hash"] == initial_db_hash

    evidence.verify_chain()
    assert [event.event_type for event in evidence.read_events()] == [
        "tool_invocation_started",
        "tool_invocation_succeeded",
    ]


def test_step_rejects_a_harness_tool_replay_mismatch(tmp_path: Path) -> None:
    bridge = _bridge()
    case = _case()
    cell = _cell(case)
    raw_db = json.loads(
        (UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json").read_text(
            encoding="utf-8"
        )
    )
    initial_db = bridge.normalize_db(raw_db)
    evidence = EvidenceStore(
        tmp_path / "tamper_evidence",
        run_plan_id="runplan_tau3_retail_tamper",
        cell_id=cell.cell_id,
        episode_id="episode_tau3_retail_tamper",
        episode_attempt_id="attempt_tau3_retail_tamper",
    )

    class TamperingHarness(ScriptedTau3RetailHarness):
        async def __call__(self, request):
            response = await super().__call__(request)
            if request.phase_id == "assistant_turn":
                response["tool_executions"][0]["result"]["content"] = "tampered"
            return response

    scripted = TamperingHarness(
        bridge=bridge,
        initial_db=initial_db,
        evidence=evidence,
        script=[
            ("user_turn", {"content": "Please check order #W5272531."}),
            (
                "assistant_turn",
                {
                    "messages": [
                        {
                            "tool_calls": [
                                {
                                    "id": "call_get_order",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "#W5272531"},
                                }
                            ]
                        },
                        {"content": "I found the order."},
                    ]
                },
            ),
        ],
    )

    with pytest.raises(SchedulerContractError, match="tool replay result differs"):
        asyncio.run(
            run_episode(
                cell=cell,
                case=case,
                plugin=Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge),
                response_source=scripted,
            )
        )


def test_step_rejects_a_harness_tool_replay_db_hash_mismatch(tmp_path: Path) -> None:
    bridge = _bridge()
    case = _case()
    cell = _cell(case)
    raw_db = json.loads(
        (UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json").read_text(
            encoding="utf-8"
        )
    )
    initial_db = bridge.normalize_db(raw_db)
    evidence = EvidenceStore(
        tmp_path / "hash_tamper_evidence",
        run_plan_id="runplan_tau3_retail_hash_tamper",
        cell_id=cell.cell_id,
        episode_id="episode_tau3_retail_hash_tamper",
        episode_attempt_id="attempt_tau3_retail_hash_tamper",
    )

    class HashTamperingHarness(ScriptedTau3RetailHarness):
        async def __call__(self, request):
            # Run the real path first (per the sibling result-mismatch test
            # above) so the recorded execution is upstream-correct in every
            # field except the one this test deliberately corrupts.
            response = await super().__call__(request)
            if request.phase_id == "assistant_turn":
                recorded = response["tool_executions"][0]["post_db_hash"]
                assert isinstance(recorded, str) and len(recorded) == 64
                flipped_first_char = "0" if recorded[0] != "0" else "1"
                response["tool_executions"][0]["post_db_hash"] = (
                    flipped_first_char + recorded[1:]
                )
            return response

    scripted = HashTamperingHarness(
        bridge=bridge,
        initial_db=initial_db,
        evidence=evidence,
        script=[
            ("user_turn", {"content": "Please check order #W5272531."}),
            (
                "assistant_turn",
                {
                    "messages": [
                        {
                            "tool_calls": [
                                {
                                    "id": "call_get_order",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "#W5272531"},
                                }
                            ]
                        },
                        {"content": "I found the order."},
                    ]
                },
            ),
        ],
    )

    with pytest.raises(SchedulerContractError, match="tool replay DB hash differs"):
        asyncio.run(
            run_episode(
                cell=cell,
                case=case,
                plugin=Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge),
                response_source=scripted,
            )
        )


def test_multiple_assistant_tool_rounds_are_one_parsed_logical_action() -> None:
    plugin = Tau3RetailPlugin(upstream_root=UPSTREAM_ROOT, bridge=None)
    family_case = json.loads(canonical_json_bytes(_case().payload))
    assistant_phase = plugin.phases(family_case)[1]
    result = plugin.parse_action(
        family_case,
        {},
        "assistant",
        assistant_phase,
        {
            "messages": [
                {
                    "tool_calls": [
                        {"id": "one", "name": "get_order_details", "arguments": {}}
                    ]
                },
                {
                    "tool_calls": [
                        {"id": "two", "name": "get_order_details", "arguments": {}}
                    ]
                },
                {"content": "done"},
            ],
            "tool_executions": [
                {
                    "tool_call_id": "one",
                    "name": "get_order_details",
                    "arguments": {},
                    "result": {"content": "one", "error": False},
                    "post_db_hash": "a" * 64,
                    "invocation_record_id": "invocation_one",
                },
                {
                    "tool_call_id": "two",
                    "name": "get_order_details",
                    "arguments": {},
                    "result": {"content": "two", "error": False},
                    "post_db_hash": "b" * 64,
                    "invocation_record_id": "invocation_two",
                },
            ],
        },
    )

    assert result.ok is True
    assert len(result.action["messages"]) == 3
    assert len(result.action["tool_executions"]) == 2


def test_scripted_harness_does_not_execute_a_post_terminal_tool_round(
    tmp_path: Path,
) -> None:
    bridge = _bridge()
    raw_db = json.loads(
        (UPSTREAM_ROOT / "data" / "tau2" / "domains" / "retail" / "db.json").read_text(
            encoding="utf-8"
        )
    )
    initial_db = bridge.normalize_db(raw_db)
    evidence = EvidenceStore(
        tmp_path / "terminal_boundary_evidence",
        run_plan_id="runplan_tau3_retail_boundary",
        cell_id="cell_tau3_retail_boundary",
        episode_id="episode_tau3_retail_boundary",
        episode_attempt_id="attempt_tau3_retail_boundary",
    )
    scripted = ScriptedTau3RetailHarness(
        bridge=bridge,
        initial_db=initial_db,
        evidence=evidence,
        script=[
            (
                "assistant_turn",
                {
                    "messages": [
                        {
                            "tool_calls": [
                                {
                                    "id": "first",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "#W5272531"},
                                }
                            ]
                        },
                        {
                            "tool_calls": [
                                {
                                    "id": "must_not_run",
                                    "name": "get_order_details",
                                    "arguments": {"order_id": "#W5918442"},
                                }
                            ]
                        },
                        {"content": "must not be generated"},
                    ]
                },
            )
        ],
    )
    request = SimpleNamespace(
        phase_id="assistant_turn",
        logical_action_id="logical_action_boundary",
        observation={
            "upstream_step_count": 1,
            "num_tool_errors": 0,
            "max_steps": 3,
        },
    )

    response = asyncio.run(scripted(request))

    assert response["terminated_after_tools"] is True
    assert len(response["messages"]) == 1
    assert [execution["tool_call_id"] for execution in response["tool_executions"]] == [
        "first"
    ]
    assert [event.event_type for event in evidence.read_events()] == [
        "tool_invocation_started",
        "tool_invocation_succeeded",
    ]
