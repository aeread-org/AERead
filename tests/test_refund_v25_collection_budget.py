"""Collection-budget regression tests without private campaign artifacts."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from aeread.shared_runner.task.scheduler import run_episode, SchedulerContractError
from aeread_families.refund import v2_5_collection_budget as repair


def setup():
    return repair.legacy.build_refund_v25_run(include_policy_frontier_hard_extension=True)


def test_repair_preserves_cases_profiles_and_scoring():
    old = setup()
    new = repair.repair_setup(old)
    encode = repair.legacy.canonical_json_bytes
    assert encode(old.plan.cases) == encode(new.plan.cases)
    assert encode(old.plan.agent_profiles) == encode(new.plan.agent_profiles)
    assert old.plan.run_plan_id != new.plan.run_plan_id


def test_single_fact_collection_reaches_terminal_without_budget_exclusion():
    old = setup()
    new = repair.repair_setup(old)
    case = next(c for c in new.plan.cases if "frontier_hard_payment_identity.serial_match." in c.case_id)
    cell = next(c for c in new.plan.cells if c.case_id == case.case_id)
    provider = repair.legacy.ScriptedV25Provider()
    async def respond(request):
        result = await provider.complete(SimpleNamespace(
            input_text=json.dumps({"role": request.role,
                "observation": json.loads(repair.legacy.canonical_json_bytes(request.observation))}),
            provider_call_id="collection_regression", model="scripted", revision="offline"))
        action = json.loads(result.output_text)
        if request.role == "policy" and action["decision"] == "request_facts":
            action["requested_fact_ids"] = action["requested_fact_ids"][:1]
        return json.dumps(action)
    with pytest.raises(SchedulerContractError, match="phase logical-action budget"):
        asyncio.run(run_episode(cell=cell, case=case, plugin=repair.legacy.RefundV25Plugin(), response_source=respond))
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=repair.RefundV25CollectionBudgetPlugin(), response_source=respond))
    assert not result.final_state["failures"]
    assert result.outcome["end_to_end"] == 1


def test_bounds_and_insufficient_case_budget():
    old = setup()
    plugin = repair.RefundV25CollectionBudgetPlugin()
    for manifest in old.plan.cases:
        case = plugin.validate_payload(manifest.payload)
        bounds = repair.collection_bounds(case)
        assert bounds["whole_case"] <= manifest.episode.max_logical_actions
        cell = next(c for c in old.plan.cells if c.case_id == manifest.case_id)
        with pytest.raises(ValueError, match="Whole-case budget"):
            plugin.initial_state(case, replace(cell, case_max_logical_actions=3))
