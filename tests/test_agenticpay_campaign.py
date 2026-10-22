import asyncio
from types import SimpleNamespace

from aeread_families.agenticpay_bilateral.campaign import CASE_IDS, campaign_plan
from aeread_families.agenticpay_bilateral.live import AgenticpayMessageHarness


def test_campaign_freezes_six_diverse_cases() -> None:
    plan = campaign_plan()
    assert len(CASE_IDS) == 6
    assert [row["case_id"] for row in plan["panel"]] == list(CASE_IDS)


def test_message_harness_returns_the_adapter_action_mapping() -> None:
    class Model:
        async def complete(self, **kwargs):
            del kwargs
            return SimpleNamespace(text='{"message":"### BUYER_PRICE($100) ###"}')

    request = SimpleNamespace(
        phase_id="buyer_turn", seat_id="buyer", observation={"current_round": 1}
    )
    output = asyncio.run(
        AgenticpayMessageHarness().act(request, SimpleNamespace(model=Model()))
    )
    assert output.action == {"message": "### BUYER_PRICE($100) ###"}
