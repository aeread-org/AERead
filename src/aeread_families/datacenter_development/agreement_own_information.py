"""The integrator's own-information best reply against the public firm client: Gate 3's reference for the integrator seat.

``agreement_negotiator_check.best_plan`` is a ceiling: it knows both sides' true types. A subject in the integrator seat
knows its own type and the client's declared prior over the client's risk charge, never the charge itself. This module
computes the most such a player can expect to earn against the scripted client in the style drawn from the public world
(``agreement_admitted_pack.public_style``), the counterpart of the v2 plan's primary arm
(``docs/families/datacenter/agreement_confirmatory_v2_plan.md``, amendment 3):

- **moves**: walk, sign the client's standing version (when allowed), or redline to a candidate clause set at an ask on
  :data:`GRID`. The candidates are each charge's best agreement and the agreement with the most expected joint
  surplus over the charges; an ask is the integrator's cost plus its floor margin plus a share of the keenest charge's
  room on that clause set;
- **beliefs**: one branch per charge the prior allows. The script's reply is deterministic given the charge, so after
  each move the charges are grouped by the reply they produce, and play continues separately in each group;
- **choice**: at every node the move with the highest prior-weighted expected earnings over the charges still live,
  ties going to the earlier move. The result is the ex-ante optimal contingent plan within the grid.

Reported per world: the plan's earnings at the true charge (``at_true``, what the plan realises in this world), its
expected earnings over the prior (``expected``), and the same search told the true charge (``full_information_grid``),
whose difference from ``at_true`` is what not knowing the charge costs on this grid. Earnings are the integrator's
surplus over its outside option, $k, at both sides' true costs, redline fees deducted (``agreement.grade``).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from . import agreement as ag
from . import agreement_admitted_pack as aap
from . import agreement_negotiator as an
from . import risk_allocation as ra
from . import risk_allocation_contracts as rc

GRID = (0.2, 0.4, 0.6, 0.8, 1.0)
EPS = 1e-6


def options(state: Mapping[str, Any], cw_by: Mapping[float, rc.CWorld], it: ra.IntegratorType, charges: list[float]) -> list[dict[str, Any]]:
    """The integrator's moves at a node shared by ``charges``."""
    out: list[dict[str, Any]] = [{"action": "walk", "clauses": None, "price": None, "note": None}]
    allowed = ag.allowed(state)
    if "sign" in allowed:
        out.append({"action": "sign", "clauses": None, "price": None, "note": None})
    if "redline" in allowed:
        cw0 = cw_by[charges[0]]
        candidates = {ag.best_agreement(cw_by[c], it) for c in charges}
        candidates.add(max(ag.ALL_AGREEMENTS, key=lambda k: sum(cw_by[c].best_outside[1] - ag.joint_cost(cw_by[c], it, k) for c in charges)))
        now = rc.Contract(**state["terms"])
        floor = cw0.w.terms.floor_margin
        for k in sorted(candidates):
            ic, _ = ag.costs(cw0, it, k)
            room = max(cw_by[c].best_outside[1] - ag.costs(cw_by[c], it, k)[1] - ic - floor for c in charges)
            if room <= EPS:
                continue
            for share in GRID:
                out.append({"action": "redline", "clauses": {t: (getattr(k, t) if getattr(k, t) != getattr(now, t) else None) for t in ag.TERMS},
                            "price": round(ic + floor + share * room, 3), "note": None})
    return out


def best(cw_by: Mapping[float, rc.CWorld], it: ra.IntegratorType, states: Mapping[float, Mapping[str, Any]], probs: Mapping[float, float],
         style: an.Style) -> dict[float, float]:
    """Charge -> the integrator's earnings under the plan that maximises expected earnings over the live ``states``."""
    charges = list(states)
    if all(states[c]["finished"] for c in charges):
        return {c: ag.grade(cw_by[c], it, states[c])["integrator_surplus"] for c in charges}
    z = sum(probs[c] for c in charges)
    best_value, best_values = -math.inf, None
    for act in options(states[charges[0]], cw_by, it, charges):
        nxt = {}
        for c in charges:
            s = ag.apply(states[c], act, cw_by[c])
            if not s["finished"]:
                s = ag.apply(s, an.negotiator_move(s, cw_by[c], it, style), cw_by[c])
            nxt[c] = s
        groups: dict[str, dict[float, Mapping[str, Any]]] = {}
        for c, s in nxt.items():
            key = json.dumps([s["finished"], s["termination"], s["history"][-1] if s["history"] else None], sort_keys=True, default=str)
            groups.setdefault(key, {})[c] = s
        values: dict[float, float] = {}
        for g in groups.values():
            if all(x["finished"] for x in g.values()):
                values.update({c: ag.grade(cw_by[c], it, g[c])["integrator_surplus"] for c in g})
            else:
                values.update(best(cw_by, it, g, probs, style))
        v = sum(probs[c] / z * values[c] for c in charges)
        if v > best_value + EPS:
            best_value, best_values = v, values
    assert best_values is not None
    return best_values


def own_information(cw: rc.CWorld, it: ra.IntegratorType) -> dict[str, float]:
    """The world's own-information plan at the true charge, in expectation, and the same search told the charge."""
    charges = [c for c, _ in cw.w.client_prior]
    probs = {c: p for c, p in cw.w.client_prior}
    cw_by = {c: aap.with_charge(cw, c) for c in charges}
    style = aap.public_style(cw, "client")
    if any(aap.public_style(cw_by[c], "client") != style for c in charges):
        raise AssertionError("the public style must not depend on the hidden charge")
    values = best(cw_by, it, {c: ag.initial_state(cw_by[c]) for c in charges}, probs, style)
    true = cw.w.client.risk_charge
    full = best({true: cw_by[true]}, it, {true: ag.initial_state(cw_by[true])}, {true: 1.0}, style)[true]
    return {"at_true": round(values[true], 3), "expected": round(sum(probs[c] * values[c] for c in charges), 3),
            "full_information_grid": round(full, 3)}


__all__ = ["GRID", "best", "options", "own_information"]
