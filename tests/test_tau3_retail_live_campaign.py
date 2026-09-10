from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from aeread.shared_runner.task.evaluation import (
    finalize_family_execution,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import (
    ProviderFailure,
    ProviderResult,
    execute_plan_cell,
)
from aeread_families.tau3_retail.campaign import (
    CAMPAIGN_ID,
    PANEL_CASE_IDS,
    PANEL_STRATA,
    _accounted_failure_cost,
    _cap_cost,
    _is_malformed_response,
    _sealed_successful_provider_cost,
    _provider_failure_condition,
    _digest,
    build_campaign_plan,
    publish_campaign,
)
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.tau3_retail.live import build_live_setup
from aeread_families.tau3_retail.live import PROVIDER
from aeread_families.tau3_retail.harness import Tau3RetailJsonHarness
from aeread_families.tau3_retail.tau2_bridge import (
    Tau2Bridge,
    Tau2BridgeUnavailableError,
    discover_bridge_python,
)


def test_campaign_plan_freezes_route_panel_order_and_budget() -> None:
    plan = build_campaign_plan()
    assert plan["campaign_id"] == CAMPAIGN_ID
    assert [row["case_id"] for row in plan["panel"]] == list(PANEL_CASE_IDS)
    assert plan["route"]["provider"] == "arena"
    assert plan["route"]["model"] == "glm-5p2"
    assert plan["route"]["provider_cost_status"] == "response_reported"
    assert plan["canary"]["max_output_tokens"] == 256
    assert plan["route"]["fallbacks"] == "not_reported"
    assert plan["execution"]["max_parallel_cells"] == 1
    assert plan["execution"]["abort_on_operational_failure"] is True
    assert plan["execution"]["continue_on_case_cost_cap"] is True
    assert plan["execution"]["continue_on_malformed_response"] is True
    assert plan["budget"]["planned_maximum_usd"] <= plan["budget"][
        "hard_total_cost_ceiling_usd"
    ]


def test_malformed_failure_preserves_the_accounted_execution_cost() -> None:
    provider_failure = ProviderFailure(
        "malformed_structured_output",
        "tau3 retail response is not valid JSON",
        retryable=False,
    )
    scheduler_failure = RuntimeError("response_source failed")
    scheduler_failure.__cause__ = provider_failure
    scheduler_failure.aeread_total_cost_usd = 0.0412

    assert _provider_failure_condition(scheduler_failure) == "malformed_structured_output"
    assert _accounted_failure_cost(scheduler_failure) == pytest.approx(0.0412)


def test_arena_schema_mismatch_is_a_malformed_campaign_response() -> None:
    provider_failure = ProviderFailure(
        "provider_contract",
        "Arena response contains no JSON action matching the schema",
        retryable=False,
    )
    scheduler_failure = RuntimeError("response_source failed")
    scheduler_failure.__cause__ = provider_failure

    assert _is_malformed_response(scheduler_failure)


def test_unknown_provider_failure_is_not_treated_as_malformed() -> None:
    provider_failure = ProviderFailure(
        "provider_contract",
        "Arena request was rejected by the provider",
        retryable=False,
    )

    assert not _is_malformed_response(provider_failure)


def test_malformed_response_cost_can_be_recovered_from_sealed_events(tmp_path: Path) -> None:
    attempt_root = tmp_path / "run" / "attempts" / "one"
    attempt_root.mkdir(parents=True)
    payload_path = attempt_root / "artifacts" / "sha256" / "aa" / "payload"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_text(json.dumps({"cost_usd": 0.0086}), encoding="utf-8")
    (attempt_root / "events.jsonl").write_text(
        json.dumps(
            {
                "event_type": "provider_call_succeeded",
                "payload_ref": "artifacts/sha256/aa/payload",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert _sealed_successful_provider_cost(tmp_path / "run") == pytest.approx(0.0086)


def test_assistant_request_places_static_policy_and_tools_before_turn_state() -> None:
    message = Tau3RetailJsonHarness.request_message(
        SimpleNamespace(
            phase_id="assistant_turn",
            seat_id="assistant",
            role="assistant",
            observation_schema="assistant_observation",
            action_schema="assistant_action",
            observation={
                "messages": [{"role": "user", "content": "hello"}],
                "policy": "fixed policy",
                "tools": {"lookup": {"description": "fixed tool"}},
                "policy_sha256": "a" * 64,
                "tool_schema_sha256": "b" * 64,
                "upstream_step_count": 1,
            },
        )
    )

    assert message.content.startswith("STATIC_CONTEXT\n")
    assert message.content.index("fixed policy") < message.content.index("TURN_CONTEXT")
    assert message.content.index("fixed tool") < message.content.index("hello")


def test_tau3_harness_rejects_prose_prefixed_structured_output() -> None:
    with pytest.raises(ProviderFailure) as captured:
        Tau3RetailJsonHarness._decode(
            'Let me look that up.\n{"kind":"tool_calls","calls":[]}'
        )

    assert captured.value.condition == "malformed_structured_output"


def test_tau3_harness_recovers_prose_prefixed_json_only_under_the_sealed_policy() -> None:
    notes = []
    harness = object.__new__(Tau3RetailJsonHarness)
    harness.prose_prefixed_json_recovery = True
    value = harness._decode_turn(
        'I will check that now.\n{"kind":"tool_calls","text":null,"calls":[]}',
        SimpleNamespace(note=lambda kind, payload: notes.append((kind, payload))),
    )

    assert value["kind"] == "tool_calls"
    assert notes == [
        (
            "tau3_retail_response_normalized",
            {
                "policy": "prose_prefixed_json_recovery_v1",
                "prefix_length": len("I will check that now.\n"),
            },
        )
    ]
    with pytest.raises(ProviderFailure):
        harness._decode_turn(
            'prefix {"kind":"reply","text":"ok","calls":[]} trailing',
            SimpleNamespace(note=lambda *_: None),
        )


def test_publish_only_is_provider_free_digest_bound_and_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = tmp_path / "run"
    publication_root = tmp_path / "publication"
    plan = build_campaign_plan()
    (run_root / "checkpoints").mkdir(parents=True)
    (run_root / "campaign_plan.json").write_bytes(canonical_json_bytes(plan) + b"\n")
    canary = {
        "status": "admitted",
        "plan_sha256": plan["plan_sha256"],
        "cost_usd": 0.001,
    }
    canary["record_sha256"] = _digest(canary)
    (run_root / "checkpoints" / "canary.json").write_bytes(
        canonical_json_bytes(canary) + b"\n"
    )
    receipts: dict[str, dict[str, str]] = {}
    for ordinal, case_id in enumerate(PANEL_CASE_IDS):
        receipt_path = Path("receipts") / f"{case_id}.json"
        receipts[str(run_root / receipt_path)] = {"case_id": case_id}
        checkpoint = {
            "status": "complete",
            "plan_sha256": plan["plan_sha256"],
            "receipt_path": str(receipt_path),
            "termination_reason": "user_stop",
            "upstream_step_count": ordinal + 1,
            "cost_usd": 0.002,
            "receipt_sha256": f"receipt-{ordinal}",
            "receipt_replayed": True,
        }
        checkpoint["record_sha256"] = _digest(checkpoint)
        checkpoint_path = run_root / "checkpoints" / f"{ordinal:02d}_{case_id}.json"
        checkpoint_path.write_bytes(canonical_json_bytes(checkpoint) + b"\n")

    score = SimpleNamespace(
        primary=SimpleNamespace(value=1.0),
        metrics={
            "tool_error_count": SimpleNamespace(value=0),
            "redundant_tool_call_count": SimpleNamespace(value=0),
        },
    )
    monkeypatch.setattr(
        "aeread_families.tau3_retail.campaign.read_evaluation_receipt",
        lambda path: receipts[str(path)],
    )
    monkeypatch.setattr(
        "aeread_families.tau3_retail.campaign.deserialize_evaluation_receipt",
        lambda serialized: SimpleNamespace(scores=(score,)),
    )
    monkeypatch.setattr(
        "aeread_families.tau3_retail.campaign.receipt_projection",
        lambda serialized, campaign_cell_key: {
            "case_id": serialized["case_id"],
            "campaign_cell_key": campaign_cell_key,
        },
    )

    publish_campaign(run_root=run_root, publication_root=publication_root)
    first = {
        path.relative_to(publication_root): path.read_bytes()
        for path in publication_root.rglob("*")
        if path.is_file()
    }
    publish_campaign(run_root=run_root, publication_root=publication_root)
    second = {
        path.relative_to(publication_root): path.read_bytes()
        for path in publication_root.rglob("*")
        if path.is_file()
    }
    assert first == second
    assert len(first) == len(PANEL_CASE_IDS) + 4
    archive = (publication_root / "trajectories" / "archive.jsonl").read_text()
    assert all(case_id in archive for case_id in PANEL_CASE_IDS)
    assert all(stratum in archive for stratum in PANEL_STRATA)

    canary["cost_usd"] = 0.002
    (run_root / "checkpoints" / "canary.json").write_bytes(
        canonical_json_bytes(canary) + b"\n"
    )
    with pytest.raises(RuntimeError, match="rejected canary"):
        publish_campaign(run_root=run_root, publication_root=tmp_path / "rejected")


def _bridge() -> tuple[Path, Tau2Bridge]:
    root = Path(os.environ.get("AEREAD_TAU2_UPSTREAM_ROOT", ""))
    marker = root / "data" / "tau2" / "domains" / "retail" / "tasks.json"
    if not marker.is_file():
        pytest.skip(f"pinned upstream tau2-bench checkout not found at {root}")
    try:
        python = discover_bridge_python(upstream_root=root)
    except Tau2BridgeUnavailableError as error:
        pytest.skip(str(error))
    return root, Tau2Bridge(python_executable=python, upstream_root=root)


class _ToolPathProvider:
    def __init__(self) -> None:
        self.requests = []
        self._outputs = iter(
            (
                {"kind": "reply", "text": "Please check order #W5272531."},
                {
                    "kind": "tool_calls",
                    "text": None,
                    "calls": [
                        {
                            "id": "call_get_order",
                            "name": "get_order_details",
                            "arguments": {"order_id": "#W5272531"},
                        }
                    ],
                },
                {"kind": "reply", "text": "I checked the order.", "calls": []},
                {"kind": "reply", "text": "###STOP###"},
            )
        )

    async def complete(self, request):
        self.requests.append(request)
        output = json.dumps(next(self._outputs), separators=(",", ":"))
        return ProviderResult(
            response_id="fixture",
            requested_model=request.model,
            resolved_model=request.revision,
            output_text=output,
            finish_reason="stop",
            input_tokens=20,
            cached_input_tokens=0,
            output_tokens=10,
            cost_usd=0.00001,
            raw_response={},
        )


def test_live_tool_path_finalizes_and_replays_a_shared_runner_receipt(tmp_path) -> None:
    upstream_root, bridge = _bridge()
    provider = _ToolPathProvider()
    setup = build_live_setup(
        case_id="tau3.retail.base.14",
        upstream_root=upstream_root,
        bridge=bridge,
        seed=300,
    )
    profiles = {profile.profile_id: profile for profile in setup.plan.agent_profiles}
    assert setup.plan.run_spec.budget_overrides is not None
    assert setup.plan.run_spec.budget_overrides.max_cost_usd == pytest.approx(0.05)
    assert profiles["tau3_retail_assistant_glm5p2_arena_v3"].harness.config[
        "prose_prefixed_json_recovery"
    ] == "prose_prefixed_json_recovery_v1"
    assert profiles[
        "tau3_retail_assistant_glm5p2_arena_v3"
    ].retry_policy.retryable_conditions == ("length",)
    assert (
        profiles["tau3_retail_assistant_glm5p2_arena_v3"].retry_policy.max_action_attempts
        == 2
    )
    assert profiles["tau3_retail_assistant_glm5p2_arena_v3"].budgets.max_cost_usd == pytest.approx(
        0.03
    )
    assert profiles["tau3_retail_user_glm5p2_arena_v3"].budgets.max_cost_usd == pytest.approx(
        0.02
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path / "run",
            prompt_sources=setup.prompt_sources,
            providers={PROVIDER: provider},
            pricing=setup.pricing,
            harnesses=setup.harnesses,
            tool_runtime_factories=setup.tool_runtime_factories,
        )
    )
    assistant_requests = [
        json.loads(request.input_text)
        for request in provider.requests
        if "messages" in json.loads(request.input_text)
        and "STATIC_CONTEXT"
        in json.loads(request.input_text)["messages"][0]["content"]
    ]
    assert assistant_requests
    assert assistant_requests[0]["messages"][0]["content"].startswith(
        "STATIC_CONTEXT\n"
    )
    receipt = finalize_family_execution(setup=setup, execution=execution)
    replayed = replay_family_receipt(
        setup=setup,
        receipt=receipt,
        evidence_root=tmp_path / "run",
    )
    invocation_ids = tuple(
        invocation_id
        for action in execution.action_executions
        for attempt in action.attempts
        for invocation_id in attempt.tool_invocations
    )
    assert invocation_ids
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.primary_leaf_id == "tau3_retail_db_state_leaf"
    assert receipt.deferred_leaf_ids == ("tau3_retail_nl_assertions_leaf",)
    assert replayed.receipt_sha256 == receipt.receipt_sha256
