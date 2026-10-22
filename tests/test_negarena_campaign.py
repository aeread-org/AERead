import asyncio
from types import SimpleNamespace

from aeread_families.negarena.campaign import CASE_IDS, campaign_plan
from aeread_families.negarena.live import NegarenaTextHarness


def test_campaign_freezes_the_six_authored_cases() -> None:
    plan = campaign_plan()
    assert len(CASE_IDS) == 6
    assert [row["case_id"] for row in plan["panel"]] == list(CASE_IDS)


def test_text_harness_returns_the_adapter_action_mapping() -> None:
    class Model:
        async def complete(self, **kwargs):
            del kwargs
            return SimpleNamespace(text='{"response":"<message> hi </message>"}')

    request = SimpleNamespace(
        phase_id="red_turn", seat_id="red", observation={"iteration": 0}
    )
    output = asyncio.run(
        NegarenaTextHarness().act(request, SimpleNamespace(model=Model()))
    )
    assert output.action == {"response": "<message> hi </message>"}
