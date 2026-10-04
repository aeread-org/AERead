import asyncio

from aeread.shared_runner.task.execution import ProviderRequest
from aeread_families.aucarena.campaign import CELLS, campaign_plan
from aeread_families.aucarena.live import RULE_MODEL, RuleNoopClient, build_live_setup


def test_campaign_freezes_six_cells_and_local_rule_profiles() -> None:
    plan = campaign_plan()
    assert len(CELLS) == 6
    assert len(plan["panel"]) == 6
    assert "aucarena.pilot.degenerate_reference_01" not in {
        case_id for case_id, _seed in CELLS
    }
    assert "aucarena.pilot.frozen_field_item5_01" in {
        case_id for case_id, _seed in CELLS
    }
    setup = build_live_setup(case_id="aucarena.pilot.successful_01")
    profiles = dict(setup.plan.cells[0].profile_by_seat)
    assert profiles["agent"].startswith("aucarena_glm5p2_arena")
    assert profiles["field_low"] == "aucarena_frozen_rule_v1"
    assert profiles["field_high"] == "aucarena_frozen_rule_v1"


def test_rule_noop_client_is_local_and_zero_cost() -> None:
    request = ProviderRequest(
        provider_call_id="rule_call",
        provider="aucarena_rule",
        base_url=None,
        model=RULE_MODEL,
        revision="vendored-rule-v1",
        instructions="",
        input_text="{}",
        temperature=0.0,
        top_p=None,
        max_output_tokens=16,
        reasoning_effort=None,
        reasoning_token_budget=None,
        timeout_seconds=5.0,
        request_sha256="",
        max_cost_usd=0.0,
        output_schema=None,
        provider_metadata={},
        seed=None,
    ).with_computed_hash()
    result = asyncio.run(RuleNoopClient().complete(request))
    assert result.output_text == '{"bid_price":-1}'
    assert result.cost_usd == 0.0
