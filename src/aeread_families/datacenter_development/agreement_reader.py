"""Scripted counterparts for testing what a client's first offer gives away without words.

Two things are here.

``first_move_only`` is a counterpart that lets the other side make exactly one move: in the integrator's seat it makes
the scripted opening in the fixed ``firm`` style and then walks; in the client's seat it walks. The style is fixed, not
drawn, because a drawn style is a function of the whole world, the client's hidden type included, and the opening must
be the same whichever type the client is given. A negotiation against it costs one model call
and records the model's first move, which is all a type-swap comparison needs.

``Reader`` is the firm scripted integrator (:mod:`.agreement_negotiator`, the ``drawn`` style) that also reads the
client's first counter-offer and reweights its belief about the client's hidden risk charge by how likely each declared
charge makes that offer. It reads one channel only:

- ``price``: where the offered price sits against the limit each charge would give the client for the terms offered;
- ``clauses``: how many of the six clauses protecting the client the offer asks for.

The reading rule is a normal likelihood whose parameters, in ``FITTED``, were estimated once from the development-pack
runs up to 2026-10-12 (``tools/cli_subjects/agreement_signals.py``) and are frozen here. They are per model: this is a
counterpart that has studied the model it faces. Nothing here was fitted to a confirmatory world. The script then plays
as the firm script does on the reweighted belief, so it still never signs below its own walk-away point, and a wrong
reading costs it deals.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

from . import agreement as ag
from . import agreement_negotiator as an
from . import risk_allocation as ra
from . import risk_allocation_contracts as rc

WALK = {"action": "walk", "clauses": None, "price": None, "note": None}
#: price: (intercept, slope on the client's own limit, residual sd) of offer price against limit, both less the prior-mean limit.
#: clauses: (mean protecting clauses asked for at the lowest, middle and highest declared charge), residual sd.
FITTED: dict[str, dict[str, Any]] = {
    "codex": {"price": (-260.8, 0.149, 134.0), "clauses": ((3.05, 4.12, 5.13), 1.01), "offers": 493},
    "claude": {"price": (-134.0, 0.521, 166.4), "clauses": ((3.79, 3.60, 4.52), 1.03), "offers": 316},
}
CHANNELS = ("price", "clauses")
FIRST_MOVE_STYLE = "firm"


def protection(terms: rc.Contract) -> int:
    """How many of the six clauses that protect the client stand at their most protective position."""
    return sum([terms.warranty == "fix_and_delay", str(terms.damages) == "200", str(terms.liability_cap) == "uncapped", terms.readiness == "integrator",
                terms.consequential == "included", bool(terms.burn_in)])


def client_limit(cw: rc.CWorld, it: ra.IntegratorType, terms: rc.Contract, charge: float) -> float:
    """The most a client with this risk charge could pay for these terms without being worse off than walking away."""
    return an._outside(cw, charge) - rc.client_cost(terms, cw.w, it, cw.x, charge)


def first_move_only(state: Mapping[str, Any], cw: rc.CWorld, it: ra.IntegratorType) -> dict[str, Any]:
    if state["to_move"] == "integrator" and state["move"] == 1:
        return an.negotiator_move(state, cw, it, FIRST_MOVE_STYLE)
    return dict(WALK)


class Reader(an.Negotiator):
    def __init__(self, cw: rc.CWorld, own: ra.IntegratorType, channel: str, model: str, style: str | an.Style = an.DRAWN) -> None:
        if channel not in CHANNELS or model not in FITTED:
            raise ValueError("unknown channel or model")
        super().__init__(cw, "integrator", own, style)
        self.channel, self.fitted = channel, FITTED[model]

    def first_offer(self, state: Mapping[str, Any]) -> tuple[rc.Contract, float] | None:
        """The client's first redline: the terms it left on the table and its price."""
        terms = ag.draft(self.cw)
        for h in state["history"]:
            if h["action"] != "redline":
                continue
            terms = rc.contract_from({k: v["now"] for k, v in h["changes"].items()}, terms)
            if h["by"] == "client":
                return terms, float(h["price"])
        return None

    def likelihood(self, terms: rc.Contract, price: float) -> dict[float, float]:
        """How likely each declared charge makes this offer, on the one channel this reader uses."""
        charges = sorted(c for c, _ in self.cw.w.client_prior)
        if self.channel == "clauses":
            means, sd = self.fitted["clauses"]
            level = {c: min(i, len(means) - 1) for i, c in enumerate(charges)}
            return {c: math.exp(-0.5 * ((protection(terms) - means[level[c]]) / sd) ** 2) for c in charges}
        a, b, sd = self.fitted["price"]
        limits = {c: client_limit(self.cw, self.own, terms, c) for c in charges}
        mean = math.fsum(p * limits[c] for c, p in self.cw.w.client_prior)
        return {c: math.exp(-0.5 * (((price - mean) - (a + b * (limits[c] - mean))) / sd) ** 2) for c in charges}

    def belief(self, state: Mapping[str, Any]) -> list[an.Other]:
        live = super().belief(state)
        offer = self.first_offer(state)
        if offer is None:
            return live
        like = self.likelihood(*offer)
        weighted = [replace(o, p=o.p * like[o.charge]) for o in live]
        mass = math.fsum(o.p for o in weighted)
        return live if mass <= 0 else [replace(o, p=o.p / mass) for o in weighted]


def reader_move(state: Mapping[str, Any], cw: rc.CWorld, it: ra.IntegratorType, channel: str, model: str) -> dict[str, Any]:
    if state["to_move"] != "integrator":
        raise ValueError("the reader plays the integrator's seat only")
    return Reader(cw, it, channel, model).move(state)


__all__ = ["CHANNELS", "FITTED", "Reader", "client_limit", "first_move_only", "protection", "reader_move"]
