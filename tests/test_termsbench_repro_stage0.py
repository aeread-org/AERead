"""Stage 0 of the TERMS-Bench reproduction (``docs/families/termsbench/reproduction_plan.md``), offline.

1. Generator v0.2.0 draws the paper's geometry, balances role and opener, regenerates byte for byte, and keeps its
   blocks and the published pilot's seeds apart; the re-stamped pilot keeps v0.1.0's payloads.
2. The v2 plugin shows the paper's five keys, reads decisions case-insensitively, executes an Accept that carries a
   price at the standing offer, clamps an out-of-bounds offer and records it, and replaces an unparseable or illegal
   move with the paper's fallback without ending the episode; v0.1.0's plugin is unchanged.
3. Harness 2.0 sends the observation alone and finds the move by balanced-brace scanning.
4. The prompts are the paper's buyer prompt and its stated seller mirror.
5. The FC baselines run through the v2 plugin and the family's own scorer; the gate reports what it found.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest

from aeread.shared_runner.task.scheduler import ActionEnvelope, ParseResult
from aeread_families.termsbench import cases as v1cases
from aeread_families.termsbench import cases_v2 as c
from aeread_families.termsbench import environment as v1env
from aeread_families.termsbench import environment_v2 as env
from aeread_families.termsbench import fc_baselines as fb
from aeread_families.termsbench import harness_v2 as h
from aeread_families.termsbench import prompts_v2 as pr


def test_generator_draws_the_paper_geometry_balanced_and_reproducibly() -> None:
    conf = c.corpus(c.CONFIRMATORY)
    assert len(conf) == 60 and sum(x["payload"]["regime"] == "overlap" for x in conf) == 48
    for x in conf:
        p = x["payload"]
        assert p["price_bounds"] == {"p_min": 0.0, "p_max": 100.0} and x["family_version"] == "0.2.0"
        width = abs(p["delta"])
        assert 10.0 <= width <= 40.0
        assert 0.0 <= min(p["agent"]["r_a"], p["t_b"]["r_b"]) and max(p["agent"]["r_a"], p["t_b"]["r_b"]) <= 100.0
    overlap = [x["payload"] for x in conf if x["payload"]["regime"] == "overlap"]
    cells = {(p["family"], p["agent"]["role"], p["chi"]) for p in overlap}
    assert len(cells) == 12 and all(sum((p["family"], p["agent"]["role"], p["chi"]) == cell for p in overlap) == 4 for cell in cells)
    assert c.corpus(c.CONFIRMATORY) == conf
    dev, pilot = c.corpus(c.DEVELOPMENT), c.restamped_pilot()
    assert not {x["world_seed"] for x in conf} & {x["world_seed"] for x in dev}
    published = {seed for *_rest, seed in v1cases.pilot_cells()}
    assert not ({x["world_seed"] for x in conf} | {x["world_seed"] for x in dev}) & published
    assert {x["world_seed"] for x in pilot} == published
    for x in pilot:
        assert x["payload"] == v1cases.generate_payload(x["payload"]["family"], x["payload"]["regime"], x["world_seed"])


def _case(regime: str = "overlap", role: str = "buyer", opener: str = "counterpart_opens") -> dict:
    return c.build_case("candid", regime, role, opener, c.seed("candid", regime, role, opener, c.DEVELOPMENT, 0), "t")


@dataclass
class _Phase:
    phase_id: str


def _agent_step(plugin, payload, state, response):
    phase = next(p for p in plugin.phases(payload) if p.phase_id == v1env.AGENT_PHASE)
    parsed = plugin.parse_action(payload, state, "agent", phase, response)
    legality = plugin.legal(payload, state, "agent", phase, parsed.action) if parsed.ok else None
    envelope = ActionEnvelope("agent", parsed.ok and bool(legality and legality.legal), parsed.action, parsed, legality)
    return plugin.step(payload, state, phase, {"agent": envelope}).state


def _with_counterpart_offer(price: float, payload: dict) -> dict:
    plugin = env.TermsBenchPluginV2()
    state = plugin.initial_state(payload, None)
    state["counterpart_offers"] = [price]
    state["transcript"] = [{"speaker": "counterpart", "decision": "offer", "price": price, "message": "Here is where things stand."}]
    state["round"] = 2
    return state


def test_the_observation_is_the_papers_five_keys() -> None:
    plugin, payload = env.TermsBenchPluginV2(), _case()["payload"]
    phase = next(p for p in plugin.phases(payload) if p.phase_id == v1env.AGENT_PHASE)
    first = plugin.observe(payload, plugin.initial_state(payload, None), "agent", phase)
    assert set(first) == {"private_context", "protocol_state", "constraints", "observation", "history"}
    assert first["protocol_state"]["legal_decisions"] == ["Offer"] and first["observation"]["counterpart_offer"] is None
    state = _with_counterpart_offer(40.0, payload)
    seen = plugin.observe(payload, state, "agent", phase)
    r_a = payload["agent"]["r_a"]
    assert seen["observation"]["counterpart_offer"] == 40.0 and seen["observation"]["accept_utility"] == pytest.approx(r_a - 40.0)
    assert seen["protocol_state"]["rounds_remaining"] == payload["horizon"] - 1
    assert "t_b" not in json.dumps(seen) and "kappa_b" not in json.dumps(seen)


def test_parsing_fallback_and_clamping_follow_the_paper() -> None:
    plugin, payload = env.TermsBenchPluginV2(), _case()["payload"]
    r_a = payload["agent"]["r_a"]
    # an Accept carrying a price executes at the standing offer (TB-D-05)
    state = _agent_step(plugin, payload, _with_counterpart_offer(r_a - 5.0, payload), {"decision": "Accept", "price": 1.0, "message": "ok"})
    assert state["termination"] == "agent_accept" and state["final_price"] == r_a - 5.0 and not state["critical_violations"]["invalid_action"]
    # an unparseable move: the standing offer is acceptable, so the fallback accepts it, recorded as invalid
    state = _agent_step(plugin, payload, _with_counterpart_offer(r_a - 5.0, payload), {"raw_text": "I think we should"})
    assert state["termination"] == "agent_accept" and state["critical_violations"]["invalid_action"] and state["fallback_moves"] == 1
    assert not state["malformed_action_schema"]
    # the standing offer is above the buyer's reservation: the fallback offers the reservation and play goes on
    state = _agent_step(plugin, payload, _with_counterpart_offer(r_a + 5.0, payload), {"decision": "maybe"})
    assert state["termination"] is None and state["agent_offers"][-1] == r_a and state["fallback_moves"] == 1
    # an Accept with nothing on the table is illegal and falls back to an offer
    fresh = plugin.initial_state(payload, None)
    state = _agent_step(plugin, payload, fresh, {"decision": "accept", "message": "deal"})
    assert state["termination"] is None and state["agent_offers"] == [r_a] and state["critical_violations"]["invalid_action"]
    # an offer above the bounds is clamped and recorded
    state = _agent_step(plugin, payload, plugin.initial_state(payload, None), {"decision": "OFFER", "price": 250.0, "message": "x"})
    assert state["agent_offers"] == [100.0] and state["critical_violations"]["price_bound"]


def test_v1s_plugin_still_ends_an_unparseable_move_as_before() -> None:
    plugin = v1env.TermsBenchPlugin()
    payload = v1cases.generate_payload("candid", "overlap", 1000046)
    phase = next(p for p in plugin.phases(payload) if p.phase_id == v1env.AGENT_PHASE)
    state = plugin.initial_state(payload, None)
    parsed = plugin.parse_action(payload, state, "agent", phase, {"raw_text": "x"})
    envelope = ActionEnvelope("agent", False, None, parsed, None)
    after = plugin.step(payload, state, phase, {"agent": envelope}).state
    assert after["termination"] == "agreement_violation" and after["malformed_action_schema"]


@pytest.mark.parametrize(("text", "expected"), [
    ('{"decision": "Offer", "price": 12.5, "message": "a {brace} in text"}', {"decision": "Offer", "price": 12.5, "message": "a {brace} in text"}),
    ('Thinking... {not json} then {"decision": "Reject", "price": null, "message": "no"} done', {"decision": "Reject", "price": None, "message": "no"}),
    ('```json\n{"decision": "Accept", "price": null, "message": "ok", "belief": {"r_hat": 40}}\n```',
     {"decision": "Accept", "price": None, "message": "ok", "belief": {"r_hat": 40}}),
    ("no json at all", None),
])
def test_balanced_brace_extraction(text, expected) -> None:
    assert h.balanced_json_object(text) == expected


def test_the_harness_sends_the_observation_alone_and_wraps_text_without_json() -> None:
    sent = {}

    class Model:
        async def complete(self, *, messages, response_mode):
            sent.update(messages=messages, mode=response_mode)
            return type("T", (), {"text": "I would rather not answer in JSON."})()

    @dataclass
    class Request:
        phase_id: str = v1env.AGENT_PHASE
        seat_id: str = "agent"
        observation: dict = None

    out = asyncio.run(h.TermsBenchPaperHarness().act(Request(observation={"private_context": {"agent_role": "BUYER"}}),
                                                     type("Ctx", (), {"model": Model()})()))
    assert sent["mode"] == "text" and json.loads(sent["messages"][0].content) == {"private_context": {"agent_role": "BUYER"}}
    assert out.action == {"raw_text": "I would rather not answer in JSON."}


def test_the_prompts_are_the_papers_buyer_and_its_stated_seller_mirror() -> None:
    assert pr.BUYER_PROMPT.startswith("You are a rational negotiating agent playing the role of a BUYER")
    assert "Lower agreement prices are better" in pr.BUYER_PROMPT and "counterpart_offer <= reservation_price" in pr.BUYER_PROMPT
    assert "Higher agreement prices are better" in pr.SELLER_PROMPT and "counterpart_offer >= reservation_price" in pr.SELLER_PROMPT
    assert pr.BUYER_PROMPT.count("BUYER") == 2 and pr.SELLER_PROMPT.count("SELLER") == 2 and "BUYER" not in pr.SELLER_PROMPT
    assert pr.PROMPT_FOR_ROLE == {"buyer": pr.BUYER_PROMPT_ID, "seller": pr.SELLER_PROMPT_ID}


def test_the_fc_baselines_run_through_the_v2_plugin_and_are_ordered() -> None:
    result = fb.report(fb.development_overlap_cases(2))
    se = [result["baselines"][n]["SE_plus"] for n in ("FC1", "FC10", "FC30")]
    assert result["worlds"] == 24 and all(0.0 <= v <= 1.0 for v in se)
    assert set(result) >= {"gate", "ordered", "median_zopa_width"}
