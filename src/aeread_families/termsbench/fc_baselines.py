"""Fixed-concession baselines FC1, FC10 and FC30, played offline through the reproduction's environment (Stage 0).

The plan's Stage 0 gate (``docs/families/termsbench/reproduction_plan.md``, Section 8): on development seeds, FC1 <
FC10 < FC30 on three-family overlap SE+, each within 0.03 of the paper's Table 16 values (0.249, 0.266, 0.374), and a
median ZOPA width near the paper's 24.6. No model is called.

Each episode runs through :class:`environment_v2.TermsBenchPluginV2` exactly as the kernel would drive it (observe,
parse, legality, step, terminal, outcome) with the counterpart answered by the family's own seeded kernel
(``harness.resolve_counterpart_response``), and is scored by :mod:`.measurement`'s own SE+ and AGR+ functions. The
fixed-concession rule is assumed, because the paper does not state it (plan Section 6): open at the price bound on
one's own side, concede the stated share of the remaining distance to the reservation value each turn, and accept any
counterpart offer within the reservation value.

    python -m aeread_families.termsbench.fc_baselines [--per-cell N]
"""

from __future__ import annotations

import argparse
import json
import statistics
from typing import Any, Mapping

from . import cases_v2, measurement
from .environment import AGENT_PHASE
from .environment_v2 import TermsBenchPluginV2, _Envelope
from .harness import resolve_counterpart_response
from aeread.shared_runner.task.scheduler import ActionEnvelope

SHARES = {"FC1": 0.01, "FC10": 0.10, "FC30": 0.30}
PAPER_SE = {"FC1": 0.249, "FC10": 0.266, "FC30": 0.374}
PAPER_MEDIAN_ZOPA = 24.6
TOLERANCE = 0.03


def fc_move(observation: Mapping[str, Any], share: float) -> dict[str, Any]:
    """The fixed-concession rule on the paper's observation."""
    ctx, proto, obs = observation["private_context"], observation["protocol_state"], observation["observation"]
    buyer, r_a = ctx["agent_role"] == "BUYER", float(ctx["reservation_price"])
    offer = obs["counterpart_offer"]
    if offer is not None and obs["accept_utility"] >= 0.0:
        return {"decision": "Accept", "price": None, "message": "I accept."}
    last = proto["own_previous_offer"]
    if last is None:
        lo, hi = observation["constraints"]["price_bounds"]
        price = lo if buyer else hi
    else:
        price = last + share * (r_a - last)
    return {"decision": "Offer", "price": price, "message": f"I offer {price:.2f}."}


def play(case: Mapping[str, Any], share: float, plugin: TermsBenchPluginV2 | None = None) -> dict[str, Any]:
    """One episode: the outcome the plugin reports at the end."""
    plugin = plugin or TermsBenchPluginV2()
    payload = plugin.validate_payload(case["payload"])
    state = plugin.initial_state(payload, None)
    phases = plugin.phases(payload)
    turn = 0
    while (terminal := plugin.terminal(payload, state)) is None:
        phase = phases[turn % 2]
        seat = "agent" if phase.phase_id == AGENT_PHASE else "counterpart"
        observation = plugin.observe(payload, state, seat, phase)
        response = fc_move(observation, share) if seat == "agent" else resolve_counterpart_response(
            observation, world_seed=case["world_seed"])
        parsed = plugin.parse_action(payload, state, seat, phase, response)
        legality = plugin.legal(payload, state, seat, phase, parsed.action) if parsed.ok else None
        envelope = ActionEnvelope(seat_id=seat, valid=parsed.ok and bool(legality and legality.legal),
                                  action=parsed.action, parse=parsed, legality=legality)
        state = plugin.step(payload, state, phase, {seat: envelope}).state
        turn += 1
    return plugin.outcome(payload, terminal)


def se_agr(case: Mapping[str, Any], outcome: Mapping[str, Any]) -> tuple[float, float]:
    payload = case["payload"]
    se = measurement.score_surplus_efficiency(measurement.build_surplus_efficiency_leaf(payload), outcome=outcome)
    agr = measurement.score_feasible_agreement(measurement.build_feasible_agreement_leaf(payload), outcome=outcome)
    return se.primary.value, agr.primary.value


def report(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    overlap = [c for c in cases if c["payload"]["regime"] == "overlap"]
    plugin = TermsBenchPluginV2()
    out: dict[str, Any] = {"worlds": len(overlap),
                           "median_zopa_width": round(statistics.median(c["payload"]["delta"] for c in overlap), 3),
                           "paper_median_zopa_width": PAPER_MEDIAN_ZOPA, "baselines": {}}
    for name, share in SHARES.items():
        pairs = [se_agr(c, play(c, share, plugin)) for c in overlap]
        by_family = {f: round(statistics.fmean(se for (se, _), c in zip(pairs, overlap) if c["payload"]["family"] == f), 4)
                     for f in cases_v2.FAMILIES}
        se_plus = statistics.fmean(se for se, _ in pairs)
        out["baselines"][name] = {"share": share, "SE_plus": round(se_plus, 4), "AGR_plus": round(statistics.fmean(a for _, a in pairs), 4),
                                  "SE_plus_by_family": by_family, "paper_SE_plus": PAPER_SE[name],
                                  "within_tolerance": abs(se_plus - PAPER_SE[name]) <= TOLERANCE}
    se = [out["baselines"][n]["SE_plus"] for n in SHARES]
    out["ordered"] = se[0] < se[1] < se[2]
    out["gate"] = out["ordered"] and all(b["within_tolerance"] for b in out["baselines"].values())
    return out


def development_overlap_cases(per_cell: int) -> list[dict[str, Any]]:
    """``per_cell`` overlap worlds per family, role and opener on development seeds (block 1), j < 10."""
    out = []
    for family in cases_v2.FAMILIES:
        for role in cases_v2.ROLES:
            for opener in cases_v2.OPENERS:
                for j in range(per_cell):
                    s = cases_v2.seed(family, "overlap", role, opener, cases_v2.DEVELOPMENT, j)
                    out.append(cases_v2.build_case(family, "overlap", role, opener, s, "repro_v1_development"))
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-cell", type=int, default=10)
    args = parser.parse_args(argv)
    result = report(development_overlap_cases(args.per_cell))
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["gate"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
