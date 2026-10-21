"""Gate 2 of the agreement case: two scripted pairs on every world of both packs, played through the environment.

Each world is played with the plugin's own hooks, in the order the shared runner's scheduler calls them:
``validate_payload``, ``phases`` and ``initial_state``; then, until ``terminal`` returns a result, ``eligible_actors``,
``observe``, the scripted seat's move as response text, ``parse_action``, ``legal``, an ``ActionEnvelope`` and
``step``. The grade is whatever ``outcome`` computes from the terminal state; nothing hands it a grade. The scripted
rules are full-information controls, so they read the state; a model seat reads only its observation.

The grade is compared with numbers worked out here from the economics alone: the two cost functions of
``risk_allocation_contracts`` over the 600 agreements, built here from the clause levels. ``agreement.best_agreement``
is not used for the comparison, because the grade itself uses it and would agree with any mistake in it.

- The full-information pair (``agreement.POLICIES["oracle"]`` in both seats) loses nothing in every world, signs
  exactly when a deal is worth signing (value available A > 0), walks in the others, and signs c*, the agreement
  ``best_agreement`` names, at the least joint cost.
- The draft pair loses, world by world, what signing the integrator's draft at the midpoint of what it leaves predicts:
  A less the draft's own surplus, or all of A where the draft is worse than walking away.

The last three tests make each check fail on a counterexample. Profile: ``docs/families/datacenter/qc.md`` section 11.
"""

from __future__ import annotations

import itertools
import json
import math
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Mapping

import pytest

from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.task.scheduler import ActionEnvelope
from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import risk_allocation_contracts as rc
from aeread_families.datacenter_development.agreement_environment import AgreementPlugin, _world
from aeread_families.datacenter_development.agreement_measurement import PRIMARY, AgreementScorer

PACKS = ("agreement_dev_v1", "agreement_confirm_v1")
TOL = 1e-6
#: Worlds with no deal worth signing, as the case documents state them: 6 of 58 in each pack.
NO_DEAL_WORLDS = {"agreement_dev_v1": 6, "agreement_confirm_v1": 6}
#: The draft pair's mean joint value lost, $k a world. The dev figure is the $318k of the first slice's dry run (9d7429e0).
DRAFT_MEAN = {"agreement_dev_v1": 317.640, "agreement_confirm_v1": 289.018}
#: Every agreement, one per economic meaning, from the clause levels rather than from ``agreement.ALL_AGREEMENTS``.
AGREEMENTS = sorted({rc.Contract(*levels).normal() for levels in itertools.product(*rc.LEVELS.values())})


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _reply(move: Mapping[str, Any]) -> CanonicalResponse:
    """A scripted move as the response text a provider would return."""
    return CanonicalResponse(text=json.dumps(move), finish_reason="stop", empty=False, truncated=False, provider_call_ids=(),
                             tool_invocation_ids=(), input_tokens=0, cached_input_tokens=0, output_tokens=0, cost_usd=0.0)


def play(payload: Mapping[str, Any], policy: str) -> dict[str, Any]:
    """One negotiation, both seats played by ``policy``, through the plugin's hooks."""
    plugin = AgreementPlugin()
    case = plugin.validate_payload(payload)
    phases = plugin.phases(case)
    by_id = {p.phase_id: p for p in phases}
    cw, it = _world(case)
    state, phase, moves = plugin.initial_state(case, None), phases[0], []
    terminal = plugin.terminal(case, _copy(state))
    for _ in range(ag.MOVES):
        if terminal is not None:
            break
        (seat,) = plugin.eligible_actors(case, _copy(state), phase)
        observation = plugin.observe(case, _copy(state), seat, phase)
        move = ag.POLICIES[policy](_copy(state), cw, it)
        parsed = plugin.parse_action(case, _copy(state), seat, phase, _reply(move))
        legality = plugin.legal(case, _copy(state), seat, phase, parsed.action) if parsed.ok else None
        valid = bool(parsed.ok and legality.legal)
        envelope = ActionEnvelope(seat, valid, parsed.action if valid else None, parsed, legality)
        transition = plugin.step(case, _copy(state), phase, MappingProxyType({seat: envelope}))
        moves.append({"seat": seat, "valid": valid, "move": observation["move"]})
        state = transition.state
        terminal = plugin.terminal(case, _copy(state))
        if terminal is None:
            phase = by_id[transition.next_phase_id]
    if terminal is None:
        raise AssertionError(f"no terminal state after {ag.MOVES} moves")
    return {"case": case, "cw": cw, "it": it, "terminal": terminal, "outcome": plugin.outcome(case, _copy(terminal)), "moves": moves}


def economics(cw: rc.CWorld, it) -> dict[str, Any]:
    """What a world makes available, from the two cost functions alone (no function the mutation tests replace)."""
    joint = {c: math.fsum((rc.integrator_cost(c, cw.w, it, cw.x), rc.client_cost(c, cw.w, it, cw.x))) for c in AGREEMENTS}
    least = min(joint.values())
    no_deal = cw.best_outside[1] - cw.w.terms.floor_margin  # the client's better outside cost less the integrator's other work
    draft = ag.draft(cw)
    return {"joint": joint, "least": least, "no_deal": no_deal, "available": max(0.0, no_deal - least), "draft": draft,
            "draft_surplus": no_deal - joint[draft], "draft_integrator_cost": rc.integrator_cost(draft, cw.w, it, cw.x)}


def lost_from_terminal(e: Mapping[str, Any], terminal: Mapping[str, Any]) -> float:
    """Joint value lost recomputed from the terminal state: A less the surplus realised, redline costs included."""
    signed = terminal["signed"]
    realised = 0.0 if signed is None else e["no_deal"] - e["joint"][rc.Contract(**signed["terms"])]
    return e["available"] - (realised - math.fsum(terminal["round_costs"].values()))


@lru_cache(maxsize=None)
def worlds(pack: str) -> tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]:
    """(pack index row, case payload) for every world of a committed pack."""
    manifest, cases = ap.load(pack)
    return tuple((row, cases[row["case_id"]]["payload"]) for row in manifest["worlds"])


def records(rows, policy: str) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    """Each world played by ``policy``, with its economics. Uncached, so a mutation test plays under its own patch."""
    out = []
    for row, payload in rows:
        r = play(payload, policy)
        out.append((row, {**r, "economics": economics(r["cw"], r["it"])}))
    return out


@lru_cache(maxsize=None)
def recorded(pack: str, policy: str) -> tuple[tuple[Mapping[str, Any], dict[str, Any]], ...]:
    return tuple(records(worlds(pack), policy))


def oracle_failures(recs) -> list[str]:
    failures = []
    for row, r in recs:
        cw, it, terminal, g, e = r["cw"], r["it"], r["terminal"], r["outcome"]["grade"], r["economics"]
        say = lambda what: failures.append(f"{row['case_id']}: {what}")  # noqa: E731
        if not all(m["valid"] for m in r["moves"]):
            say("a move was refused")
        if abs(g["joint_value_lost"]) > TOL or abs(lost_from_terminal(e, terminal)) > TOL:
            say(f"joint value lost {g['joint_value_lost']} (from the terminal: {lost_from_terminal(e, terminal)})")
        if abs(g["available_surplus"] - round(e["available"], 3)) > 1e-9 or abs(row["available_surplus"] - round(e["available"], 3)) > 1e-9:
            say(f"value available {g['available_surplus']} graded, {row['available_surplus']} indexed, {e['available']} from the optimum")
        if (terminal["termination"] == "signed") != (e["available"] > 0):
            say(f"{terminal['termination']} with value available {e['available']}")
        if e["available"] <= 0 and (terminal["termination"], terminal["walked_by"], len(r["moves"])) != ("walked", "integrator", 1):
            say("no deal is worth signing and the integrator did not walk at once")
        if terminal["signed"] is not None:
            signed = rc.Contract(**terminal["signed"]["terms"])
            if signed != ag.best_agreement(cw, it) or signed.label() != row["best_agreement"]:
                say(f"signed {signed.label()}, not c* {row['best_agreement']}")
            if e["joint"][signed] - e["least"] > TOL:
                say(f"signed an agreement {e['joint'][signed] - e['least']} above the least joint cost of the 600")
            if max(abs(g["client_surplus"] - e["available"] / 2), abs(g["integrator_surplus"] - e["available"] / 2)) > 1e-5:
                say(f"surpluses {g['client_surplus']} and {g['integrator_surplus']} are not an even split of {e['available']}")
        if g["client_ir_violation"] or g["integrator_ir_violation"]:
            say("a side signed below its outside option")
    return failures


def draft_failures(recs) -> tuple[list[str], list[float]]:
    failures, lost = [], []
    for row, r in recs:
        cw, terminal, g, e = r["cw"], r["terminal"], r["outcome"]["grade"], r["economics"]
        say = lambda what: failures.append(f"{row['case_id']}: {what}")  # noqa: E731
        predicted = e["available"] - max(0.0, e["draft_surplus"])
        lost.append(g["joint_value_lost"])
        if abs(g["joint_value_lost"] - predicted) > TOL or abs(lost_from_terminal(e, terminal) - predicted) > TOL:
            say(f"joint value lost {g['joint_value_lost']}, predicted {predicted}")
        if (terminal["termination"] == "signed") != (e["draft_surplus"] > 0) or row["draft_beats_no_deal"] != (e["draft_surplus"] > 0):
            say(f"{terminal['termination']} with the draft's surplus {e['draft_surplus']}")
        if terminal["signed"] is not None:
            if rc.Contract(**terminal["signed"]["terms"]) != e["draft"] or terminal["round_costs"] != {"client": 0.0, "integrator": 0.0}:
                say("the signed agreement is not the draft as it stands, signed on the opening")
            midpoint = e["draft_integrator_cost"] + cw.w.terms.floor_margin + e["draft_surplus"] / 2
            if abs(terminal["signed"]["price"] - midpoint) > TOL:
                say(f"signed at price {terminal['signed']['price']}, not the midpoint {midpoint}")
            if max(abs(g["client_surplus"] - e["draft_surplus"] / 2), abs(g["integrator_surplus"] - e["draft_surplus"] / 2)) > 1e-5:
                say(f"surpluses {g['client_surplus']} and {g['integrator_surplus']} are not the midpoint split of {e['draft_surplus']}")
    return failures, lost


@pytest.mark.parametrize("pack", PACKS)
def test_the_full_information_pair_loses_nothing_signs_c_star_when_a_deal_is_worth_signing_and_walks_otherwise(pack: str) -> None:
    rows = worlds(pack)
    assert len(rows) == 58 and len({row["content_sha256"] for row, _ in rows}) == 58
    assert len(AGREEMENTS) == 600 and AGREEMENTS == list(ag.ALL_AGREEMENTS)
    assert oracle_failures(recorded(pack, "oracle")) == []
    assert sum(row["available_surplus"] <= 0 for row, _ in rows) == NO_DEAL_WORLDS[pack]


@pytest.mark.parametrize("pack", PACKS)
def test_the_draft_pair_loses_what_signing_the_draft_at_its_midpoint_predicts(pack: str) -> None:
    failures, lost = draft_failures(recorded(pack, "draft"))
    assert failures == []
    assert math.fsum(lost) / len(lost) == pytest.approx(DRAFT_MEAN[pack], abs=5e-4)


@pytest.mark.parametrize("pack", PACKS)
def test_the_grade_is_computed_from_the_terminal_state_and_the_terminal_from_its_own_moves(pack: str) -> None:
    """The outcome hook reads only the case and the terminal state; the terminal state is what its own moves produce."""
    plugin, changed = AgreementPlugin(), 0
    for i, _ in enumerate(worlds(pack)):
        played = {policy: recorded(pack, policy)[i][1] for policy in ag.POLICIES}
        for r in played.values():
            cw, it, terminal, outcome = r["cw"], r["it"], r["terminal"], r["outcome"]
            rebuilt = ag.initial_state(cw)
            for h in terminal["history"]:
                clauses = {k: h["changes"][k]["now"] if k in h["changes"] else None for k in ag.TERMS} if h["action"] == "redline" else None
                rebuilt = ag.apply(rebuilt, {"action": h["action"], "clauses": clauses, "price": h["price"] if h["action"] == "redline" else None,
                                             "note": h["note"]}, cw)
            assert _copy(rebuilt) == terminal
            assert plugin.outcome(r["case"], _copy(rebuilt)) == outcome
            (primary,) = [s for s in AgreementScorer(r["case"]).score_recorded_outcome(outcome, evidence_refs=()).scores if s.leaf.leaf_id == PRIMARY]
            assert primary.primary.value == outcome["grade"]["joint_value_lost"]
        # The same hook given a different terminal grades that one: the oracle's signature with the draft's terms in place of c*.
        oracle = played["oracle"]
        e = oracle["economics"]
        if oracle["terminal"]["signed"] is not None and ag.best_agreement(oracle["cw"], oracle["it"]) != e["draft"]:
            other = _copy(oracle["terminal"])
            other["signed"]["terms"] = e["draft"].as_dict()
            regraded = plugin.outcome(oracle["case"], other)["grade"]["joint_value_lost"]
            assert regraded == pytest.approx(e["joint"][e["draft"]] - e["least"], abs=TOL) and regraded > 0
            changed += 1
    assert changed > 0


# ---------------------------------------------------------------------------
# Each check fails on a counterexample (benchmark QC section 1). A handful of deal worlds keeps these fast.


def _deal_worlds_off_the_draft(n: int = 3):
    """Deal worlds whose c* is not the draft: n where the draft beats walking away and n where it does not."""
    rows = [(row, payload) for row, payload in worlds("agreement_dev_v1") if row["available_surplus"] > 0 and row["clauses_to_change"]]
    return [r for r in rows if r[0]["draft_beats_no_deal"]][:n] + [r for r in rows if not r[0]["draft_beats_no_deal"]][:n]


def test_the_optimum_computed_here_catches_a_grader_whose_benchmark_is_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    """If ``best_agreement`` named the draft, the grade would read zero loss for an oracle signing it; the check would not."""
    rows = _deal_worlds_off_the_draft()
    monkeypatch.setattr(ag, "best_agreement", lambda cw, it: ag.draft(cw))
    recs = records(rows, "oracle")
    assert all(r["outcome"]["grade"]["joint_value_lost"] == 0.0 for _, r in recs)
    failures = oracle_failures(recs)
    assert {f.split(": ", 1)[0] for f in failures} == {row["case_id"] for row, _ in rows}
    assert any("from the terminal" in f for f in failures) and any("least joint cost" in f for f in failures)


def test_the_oracle_check_catches_an_environment_that_drops_a_redlines_clauses(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _deal_worlds_off_the_draft()
    monkeypatch.setattr(rc, "contract_from", lambda terms, base: base.normal())
    failures = oracle_failures(records(rows, "oracle"))
    assert {f.split(": ", 1)[0] for f in failures} == {row["case_id"] for row, _ in rows}
    assert any("joint value lost" in f for f in failures) and any("not c*" in f for f in failures)


def test_the_midpoint_check_catches_a_draft_pair_off_the_midpoint_that_joint_value_alone_cannot(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [(row, payload) for row, payload in worlds("agreement_dev_v1") if row["draft_beats_no_deal"]][:6]
    assert rows
    honest = ag.POLICIES["draft"]

    def shifted(state, cw, it):
        move = honest(state, cw, it)
        return {**move, "price": move["price"] + 10.0} if move["action"] == "redline" else move

    monkeypatch.setitem(ag.POLICIES, "draft", shifted)
    failures, _ = draft_failures(records(rows, "draft"))
    assert len(failures) == 2 * len(rows)
    assert all("midpoint" in f for f in failures) and not any("joint value lost" in f for f in failures)
