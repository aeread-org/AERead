"""The agreement case's admitted pack: worlds admitted on their structure before any hidden type exists.

    python -m aeread_families.datacenter_development.agreement_admitted_pack --write   # scan, admit, draw types, write
    python -m aeread_families.datacenter_development.agreement_admitted_pack --check   # rescan every seed, compare with the pack

The case is ``docs/families/datacenter/agreement_case.md`` ("The pack", "Before any model plays"); the QC profile is
``docs/families/datacenter/qc.md`` section 11. The development packs (:mod:`.agreement_pack`) borrowed worlds admitted
for another question, fixed the client's hidden risk charge by pack cell (DC-D-33) and priced the rival turnkey offer
off the drawn integrator type (DC-D-34). This module builds the pack the case's own rules call for, in three steps, and
leaves every hashed module untouched.

**1. The public world.** A seed's own stream (``random.Random(seed)``) draws one of the full-terms generator's
regimes (the ranges of a :data:`risk_allocation_contracts.CELLS` entry; its fixed client charge is ignored), a playbook
that regime allows, and every public parameter from those ranges, rounded as ``risk_allocation_contracts.draw_world``
rounds them. Two things differ from that generator: no type is drawn, and the rival turnkey price is the
prior-weighted least joint cost of the 600 agreements plus the integrator's floor margin, plus the drawn offset, so no
hidden type can move it. Until step 3 the world's client risk charge is ``None``: any code that read it would fail.

**2. Admission**, computed from the public world and the declared priors alone. For each pair of hidden types (an
integrator type of the playbook, a client charge; the declared prior weights each) the economics are exact: every
agreement's joint cost at both sides' true costs, the value available A (the least joint cost against walking away,
never below 0) and the best agreement c*, chosen as ``agreement.best_agreement`` chooses it. A shortcut's loss for a
pair is A less the joint surplus the shortcut realises, and admission takes its expectation over the prior:

- ``sign_the_draft``: the draft as it stands is signed, whatever it is worth: A - S(draft), where S(c) is the
  client's better outside option less the integrator's other work less c's joint cost. A draft worse than walking
  away loses more than A.
- ``haggle_the_price``: the draft's clauses stand and only the price moves, to the best price a side can get. A price
  only divides the value, so the deal is signed exactly when the draft beats walking away at the true types:
  A - max(0, S(draft)). It equals the scripted draft pair of ``agreement.POLICIES["draft"]``.
- ``every_protection_client`` / ``every_protection_integrator``: one side asks for every protection
  (:data:`EVERY_PROTECTION`), signed exactly when it beats walking away: A - max(0, S(c)).
- ``walk``: no deal: A.

Redline fees are left out of every shortcut, which favours the shortcut, so each margin is a lower bound. A world is
admitted only if all of these hold (:func:`admission_failures`):

- **the best agreement differs from the draft by a margin**: E[J(draft) - J(c*)] >= :data:`DRAFT_MARGIN`;
- **it cannot be read off the integrator's own brief**: knowing the client's hidden charge is worth at least
  :data:`INFORMATION_MARGIN` to the integrator's choice of agreement, in expectation over its own types, and for every
  own type the best outcome (an agreement or no deal) differs between at least two client charges. The value of
  knowing is the expected loss of the best single outcome chosen on the seat's own type alone. The client seat's value
  is recorded and not admitted on: in this generator it never reaches the margin (DC-D-35);
- **each shortcut loses a margin**: :data:`SHORTCUT_MARGIN` for the first four, :data:`WALK_MARGIN` for walking.

A world's cell is named by what its best agreement requires, clause by clause against the draft, from the client's
side (:func:`requirement`): ``walk`` (no agreement beats walking away), ``move_the_price`` (c* is the draft),
``take_risk_on`` (c* only gives client protections up), ``hand_risk_over`` (c* only adds them) and ``trade`` (both).
The cell is the first of walk, trade, take_risk_on and move_the_price whose prior mass is at least a third (against
one client type in three, given the three-valued charge), otherwise the class with the most mass. A world *gives a
clause up* when take_risk_on and trade together hold a third of its mass. :data:`QUOTAS` fills the three cells the
generator can produce equally; in the scan ``move_the_price`` never occurs and ``take_risk_on`` once (DC-D-36).

**3. The hidden types**, drawn after admission on their own stream, keyed by the pack and the seed and nothing else
(:func:`hidden_types`): the client's charge at the declared prior (a third each), then the integrator's type at the
declared prior within the playbook. The cell never enters the draw.

The scripted counterpart's ``drawn`` style (``agreement_negotiator.drawn_style``) hashes the whole world, the client's
hidden charge included (DC-D-32). :func:`public_style` draws the same population from the public world and the seat
only; ``Negotiator`` takes a ``Style`` directly, so :func:`public_negotiator_move` uses it without editing the negotiator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from . import agreement as ag
from . import agreement_negotiator as an
from . import risk_allocation as ra
from . import risk_allocation_contracts as rc
from .agreement_environment import FAMILY_ID, FAMILY_VERSION, TERMINATIONS, VISIBILITY_POLICY, AgreementPlugin

PACK = "agreement_admitted_v1"
SPLIT = "admitted"
GENERATOR_ID = "datacenter_agreement_admitted_generator_v1"
GENERATOR_VERSION = "1.0.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / FAMILY_ID
ROOT = CASES_ROOT / PACK
#: The development packs draw from seeds 2,490,000 to 3,520,000 and 2,790,000 to 3,820,000.
BASE_SEED = 6_100_000
MAX_SCAN = 40_000  # the scan stops here if a quota is still open; the pack is then not built
REGIMES = tuple(rc.CELLS)

#: $k. The full-terms case's choice and walk margins (``CHOICE_MARGIN``, ``WALK_MARGIN``); against the about 410 a
#: development deal world makes available, 75 is under a fifth of it and three redline fees, and 150 is twice that.
DRAFT_MARGIN = 75.0
SHORTCUT_MARGIN = 75.0
WALK_MARGIN = 150.0
#: $k. One redline fee: knowing the other side's type must be worth at least the move it costs to learn it.
INFORMATION_MARGIN = 25.0
CELLS = ("walk", "trade", "hand_risk_over", "take_risk_on", "move_the_price")
QUOTAS = {"walk": 20, "trade": 20, "hand_risk_over": 20, "take_risk_on": 0, "move_the_price": 0}
GIVE_UP_SHARE = 1.0 / 3.0  # the least share of admitted worlds that give a clause up
THIRD = 1.0 / 3.0 - 1e-9
SHORTCUTS = ("sign_the_draft", "haggle_the_price", "every_protection_client", "every_protection_integrator", "walk")
MARGIN = {"sign_the_draft": SHORTCUT_MARGIN, "haggle_the_price": SHORTCUT_MARGIN, "every_protection_client": SHORTCUT_MARGIN,
          "every_protection_integrator": SHORTCUT_MARGIN, "walk": WALK_MARGIN}
#: Admission reasons, in the order they are checked and reported.
REASONS = ("draft_near_best", "integrator_reads_best_off_its_brief", *(f"{s}_loses_under_margin" for s in SHORTCUTS))
TYPE_STREAM = PACK + "/hidden_types/v1:{seed}"
STYLE_POPULATION = "agreement_negotiator_population_public_v1"
#: Every protection either side can ask for, over all eight clauses (burn-in counts as the client's, as in ``agreement_reader.protection``).
EVERY_PROTECTION = {
    "client": rc.Contract("fix_and_delay", "200", "uncapped", "integrator", "included", "none", False, True).normal(),
    "integrator": rc.Contract("none", "100", "500", "client", "excluded", "50%", False, False).normal(),
}
AGREEMENTS = ag.ALL_AGREEMENTS
INDEX = {c: i for i, c in enumerate(AGREEMENTS)}
DEVELOPMENT_PACKS = ("agreement_dev_v1", "agreement_dev_walkaway_v1", "agreement_confirm_v1", "agreement_confirm_swap_client_v1",
                     "agreement_confirm_swap_integrator_v1")


# ---------------------------------------------------------------------------
# Step 1: the public world.


@dataclass(frozen=True)
class PublicWorld:
    seed: int
    regime: str
    cw: rc.CWorld  # the client's risk charge is None: no hidden type exists yet
    turnkey_offset: float


def _unanchored(seed: int) -> tuple[str, rc.CWorld, float]:
    rng = random.Random(seed)
    regime = REGIMES[rng.randrange(len(REGIMES))]
    playbooks = rc.CELLS[regime]["playbooks"]
    playbook = playbooks[rng.randrange(len(playbooks))]
    spec = {**rc._RANGES, **rc.CELLS[regime]["ranges"]}
    u = {k: rng.uniform(*v) for k, v in spec.items()}
    r2 = ra._round
    risks = ra.Risks(
        defect_without_test=r2(u["defect_without_test"], 0.01), defect_with_test=r2(u["defect_with_test"], 0.01),
        defect_fix=r2(u["defect_fix"], 10), defect_weeks=r2(u["defect_weeks"], 1), unready=r2(u["unready"], 0.01),
        standby=r2(u["standby"], 10), unready_weeks=r2(u["unready_weeks"], 1), incident=r2(u["incident"], 0.005),
        incident_loss=r2(u["incident_loss"], 100),
    )
    client = ra.Client(delay_per_week=r2(u["delay_per_week"], 5), risk_charge=None, capital_rate=r2(u["capital_rate"], 0.005),
                       insolvency=r2(u["insolvency"], 0.001), turnkey_all_in=None)
    w = ra.World(risks, client, ra.Terms(**ra.FIXED_TERMS, breakoff=r2(u["breakoff"], 0.01)))
    return regime, rc.CWorld(w, rc.Extras(r2(u["team"], 10), r2(u["site_prep"], 5)), playbook), u["turnkey_offset"]


def pairs_of(cw: rc.CWorld) -> list[tuple[tuple[ra.IntegratorType, float], float]]:
    """Each pair of hidden types (integrator type, client charge) the declared priors allow, with its weight."""
    weight = dict(cw.w.prior)
    types = cw.types
    z = math.fsum(weight[t] for t in types)
    return [((t, charge), weight[t] / z * q) for t in types for charge, q in cw.w.client_prior]


def _client_costs(c: rc.Contract, w: ra.World, pre: bool, prep: bool, charges: Sequence[float]) -> list[float]:
    """``risk_allocation_contracts.client_cost`` at each charge, line for line, with the integrator's response computed once."""
    cl, t = w.client, w.terms
    carried = math.fsum(p * lost for p, lost, _, _ in rc.outcomes(c, w, pre, prep))
    out = []
    for charge in charges:
        cost = (1.0 + charge) * carried
        if c.deposit != "none":
            cost += cl.capital_rate * rc.DEPOSIT_SHARE[c.deposit] * t.hardware * t.deposit_weeks / 52.0
        if c.escrow:
            cost += rc.ESCROW_FEE
        if c.burn_in:
            cost += rc.BURN_IN_WEEKS * cl.delay_per_week
        out.append(cost)
    return out


def joint_costs(cw: rc.CWorld) -> dict[tuple[ra.IntegratorType, float], list[float]]:
    """Every agreement's joint cost for each pair of hidden types, at both sides' true costs (no outside option needed)."""
    charges = [charge for charge, _ in cw.w.client_prior]
    out: dict[tuple[ra.IntegratorType, float], list[float]] = {(t, charge): [] for t in cw.types for charge in charges}
    for t in cw.types:
        for c in AGREEMENTS:
            pre, prep, ic = rc.best_response(c, cw.w, t, cw.x)
            for charge, cc in zip(charges, _client_costs(c, cw.w, pre, prep, charges)):
                out[(t, charge)].append(math.fsum((ic, cc)))
    return out


def best_index(joint: Sequence[float], draft: rc.Contract) -> int:
    """c* as ``agreement.best_agreement`` picks it: least joint cost to 1e-6, then the draft, then the first agreement."""
    d = INDEX[draft]
    return min(range(len(AGREEMENTS)), key=lambda i: (round(joint[i], 6), i != d, AGREEMENTS[i]))


def with_charge(cw: rc.CWorld, charge: float) -> rc.CWorld:
    return replace(cw, w=replace(cw.w, client=replace(cw.w.client, risk_charge=charge)))


def public_world(seed: int) -> tuple[PublicWorld, dict[tuple[ra.IntegratorType, float], list[float]]]:
    """The seed's public world with its turnkey price anchored, and the joint costs it was anchored on."""
    regime, cw, offset = _unanchored(seed)
    joint = joint_costs(cw)
    d = ag.draft(cw)
    floor = cw.w.terms.floor_margin
    anchor = math.fsum(p * (joint[pair][best_index(joint[pair], d)] + floor) for pair, p in pairs_of(cw))
    cw = replace(cw, w=replace(cw.w, client=replace(cw.w.client, turnkey_all_in=ra._round(anchor + offset, 10))))
    return PublicWorld(seed, regime, cw, offset), joint


def _floats(value: Any) -> Any:
    """Every number as a float, so a world read back from its case file (``world_from`` casts the extras) digests the same."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Mapping):
        return {k: _floats(v) for k, v in value.items()}
    return [_floats(v) for v in value]


def public_dict(cw: rc.CWorld) -> dict[str, Any]:
    """What both sides may know of a world: everything but the client's risk charge (the integrator's type is not in it)."""
    world = ra.world_to_dict(cw.w)
    world["client"] = {k: v for k, v in world["client"].items() if k != "risk_charge"}
    return _floats({"world": world, "extras": {"team": cw.x.team, "site_prep": cw.x.site_prep}, "playbook": cw.playbook})


def public_sha256(cw: rc.CWorld) -> str:
    return hashlib.sha256(json.dumps(public_dict(cw), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Step 2: admission, from the public world and the declared priors.


def protection(c: rc.Contract) -> dict[str, int]:
    """Each clause's position from the least to the most protective for the client. A delay-damages rate counts with the
    warranty: under fix and delay a higher rate protects more."""
    warranty = {"none": 0, "fix": 1}.get(c.warranty)
    if warranty is None:
        warranty = 1 + {"50": 1, "100": 2, "200": 3}[c.damages]
    return {"warranty": warranty, "liability_cap": {"500": 0, "1500": 1, "uncapped": 2}[c.liability_cap],
            "readiness": int(c.readiness == "integrator"), "consequential": int(c.consequential == "included"),
            "deposit": {"50%": 0, "25%": 1, "none": 2}[c.deposit], "escrow": int(c.escrow), "burn_in": int(c.burn_in)}


def requirement(best: rc.Contract | None, draft: rc.Contract) -> str:
    """What the best outcome asks of the client against the draft; None means no agreement beats walking away."""
    if best is None:
        return "walk"
    a, b = protection(best), protection(draft)
    signs = {(a[k] > b[k]) - (a[k] < b[k]) for k in a if a[k] != b[k]}
    if not signs:
        return "move_the_price"
    return "hand_risk_over" if signs == {1} else "take_risk_on" if signs == {-1} else "trade"


def _information(rows: list[dict[str, Any]], seat: str) -> tuple[float, list[float], bool]:
    """What knowing the other side's type is worth to this seat's choice of outcome: (in expectation over its own types,
    for each own type, whether every own type faces at least two best outcomes)."""
    key = (lambda r: r["pair"][0]) if seat == "integrator" else (lambda r: r["pair"][1])
    groups: dict[Any, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    per, varies, total = [], True, []
    for own in sorted(groups, key=lambda o: (o.test_cost, o.risk_charge) if seat == "integrator" else o):
        g = groups[own]
        z = math.fsum(r["p"] for r in g)
        walk = math.fsum(r["p"] * r["available"] for r in g) / z
        best_sign = max(math.fsum(r["p"] * (r["no_deal"] - r["joint"][i]) for r in g) / z for i in range(len(AGREEMENTS)))
        value = walk - max(0.0, best_sign)
        per.append(value)
        total.append(z * value)
        varies = varies and len({r["outcome"] for r in g}) >= 2
    return math.fsum(total), per, varies


def structure(world: PublicWorld, joint: Mapping[tuple[ra.IntegratorType, float], Sequence[float]] | None = None) -> dict[str, Any]:
    """Everything admission reads, from the public world and the declared priors: no hidden type has been drawn."""
    cw = world.cw
    joint = joint_costs(cw) if joint is None else joint
    d = ag.draft(cw)
    floor = cw.w.terms.floor_margin
    rows = []
    for pair, p in pairs_of(cw):
        js = joint[pair]
        no_deal = with_charge(cw, pair[1]).best_outside[1] - floor
        i = best_index(js, d)
        available = max(0.0, no_deal - js[i])
        surplus = {name: no_deal - js[INDEX[c]] for name, c in (("draft", d), *EVERY_PROTECTION.items())}
        loss = {"sign_the_draft": available - surplus["draft"], "haggle_the_price": available - max(0.0, surplus["draft"]),
                "every_protection_client": available - max(0.0, surplus["client"]),
                "every_protection_integrator": available - max(0.0, surplus["integrator"]), "walk": available}
        best = AGREEMENTS[i] if available > 1e-9 else None
        rows.append({"pair": pair, "p": p, "joint": js, "no_deal": no_deal, "available": available, "best": best,
                     "outcome": "no deal" if best is None else best.label(), "requirement": requirement(best, d), "loss": loss,
                     "draft_left": js[INDEX[d]] - js[i]})
    mass = {cell: math.fsum(r["p"] for r in rows if r["requirement"] == cell) for cell in CELLS}
    info_i, per_i, varies_i = _information(rows, "integrator")
    info_c, per_c, varies_c = _information(rows, "client")
    return {
        "rows": rows, "mass": mass,
        "expected": {"available": math.fsum(r["p"] * r["available"] for r in rows),
                     "draft_left": math.fsum(r["p"] * r["draft_left"] for r in rows),
                     **{s: math.fsum(r["p"] * r["loss"][s] for r in rows) for s in SHORTCUTS}},
        "information": {"integrator": info_i, "integrator_by_own_type": per_i, "integrator_varies_for_every_own_type": varies_i,
                        "client": info_c, "client_by_own_charge": per_c, "client_varies_for_every_own_charge": varies_c},
        "draft_is_best_somewhere": any(r["requirement"] == "move_the_price" for r in rows),
    }


def admission_failures(s: Mapping[str, Any]) -> list[str]:
    """The admission rules this world breaks, in :data:`REASONS` order; empty when it is admitted."""
    e, info = s["expected"], s["information"]
    out = []
    if e["draft_left"] < DRAFT_MARGIN:
        out.append("draft_near_best")
    if info["integrator"] < INFORMATION_MARGIN or not info["integrator_varies_for_every_own_type"]:
        out.append("integrator_reads_best_off_its_brief")
    out += [f"{name}_loses_under_margin" for name in SHORTCUTS if e[name] < MARGIN[name]]
    return out


def cell_of(mass: Mapping[str, float]) -> str:
    for cell in ("walk", "trade", "take_risk_on", "move_the_price"):
        if mass[cell] >= THIRD:
            return cell
    return max(CELLS, key=lambda c: (round(mass[c], 9), -CELLS.index(c)))


def gives_a_clause_up(mass: Mapping[str, float]) -> bool:
    return mass["take_risk_on"] + mass["trade"] >= THIRD


def screen(seed: int) -> dict[str, Any]:
    """One seed through steps 1 and 2: what the scan log records, and the world itself."""
    world, joint = public_world(seed)
    s = structure(world, joint)
    return {"seed": seed, "world": world, "structure": s, "reasons": admission_failures(s), "cell": cell_of(s["mass"])}


# ---------------------------------------------------------------------------
# Step 3: the hidden types, on their own stream.


def hidden_types(seed: int, cw: rc.CWorld) -> tuple[ra.IntegratorType, float]:
    """The client's charge, then the integrator's type, at the declared priors. Keyed by the pack and the seed only."""
    rng = random.Random(int.from_bytes(hashlib.sha256(TYPE_STREAM.format(seed=seed).encode("utf-8")).digest(), "big"))
    charge = _pick(rng, [(c, q) for c, q in cw.w.client_prior])
    weight = dict(cw.w.prior)
    it = _pick(rng, [(t, weight[t]) for t in cw.types])
    return it, charge


def _pick(rng: random.Random, weighted: Sequence[tuple[Any, float]]) -> Any:
    """One draw at the given weights from one ``random()``, by cumulative weight (no library sampler whose method could change)."""
    u = rng.random() * math.fsum(q for _, q in weighted)
    acc = 0.0
    for item, q in weighted:
        acc += q
        if u < acc:
            return item
    return weighted[-1][0]


# ---------------------------------------------------------------------------
# The scripted counterpart's population, drawn from the public world (DC-D-32).


def public_style(cw: rc.CWorld, seat: str) -> an.Style:
    """``agreement_negotiator.drawn_style``'s population, drawn from what both sides may know of the world and the seat."""
    key = json.dumps([public_dict(cw), seat, STYLE_POPULATION], sort_keys=True, separators=(",", ":"))
    rng = random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16))
    pop = an.POPULATION
    opening = rng.uniform(*pop["opening"])
    final = max(pop["final_at_least"], opening - rng.uniform(*pop["comes_down"]))
    return an.Style(opening=round(opening, 3), final=round(final, 3), least=round(rng.uniform(*pop["least"]), 3),
                    reciprocity=rng.choice(pop["reciprocity"]))


def public_negotiator_move(state: Mapping[str, Any], cw: rc.CWorld, it: ra.IntegratorType) -> dict[str, Any]:
    """The scripted negotiator in the publicly drawn style for the seat to move."""
    return an.negotiator_move(state, cw, it, public_style(cw, state["to_move"]))


# ---------------------------------------------------------------------------
# The scan and the pack.


def _r(x: float, n: int = 3) -> float:
    return round(float(x), n) + 0.0


def scan(processes: int = 1, base_seed: int = BASE_SEED, quotas: Mapping[str, int] = QUOTAS, max_scan: int = MAX_SCAN) -> dict[str, Any]:
    """Every seed from ``base_seed`` in order until each quota is filled: one log row per seed (:func:`log_row`)."""
    left = dict(quotas)
    log, admitted = [], []
    pool = None
    if processes > 1:
        from multiprocessing import get_context
        pool = get_context("spawn").Pool(processes)
    try:
        seed, chunk = base_seed, max(8, 4 * processes)
        while any(left.values()) and seed < base_seed + max_scan:
            seeds = list(range(seed, min(seed + chunk, base_seed + max_scan)))
            results = pool.map(screen, seeds) if pool else [screen(s) for s in seeds]
            for r in results:
                if not any(left.values()):
                    break
                if r["reasons"]:
                    status = "rejected"
                elif left[r["cell"]] > 0:
                    status = "admitted"
                    left[r["cell"]] -= 1
                    admitted.append(r)
                else:
                    status = "cell_full"
                log.append(log_row(r, status))
            seed = seeds[-1] + 1
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    if any(left.values()):
        raise RuntimeError(f"the scan stopped at {base_seed + max_scan} with quotas open: {left}")
    return {"log": log, "admitted": admitted}


#: A scan log row: seed, regime, playbook, cell, reasons (indices into REASONS), status, the prior mass of each
#: requirement (in CELLS order), the client seat's and the integrator seat's information value, and whether the
#: draft is the best agreement for some type pair.
LOG_FIELDS = ("seed", "regime", "playbook", "cell", "reasons", "status", "mass", "information_client", "information_integrator", "draft_best_somewhere")


def log_row(r: Mapping[str, Any], status: str) -> list[Any]:
    s = r["structure"]
    return [r["seed"], r["world"].regime, r["world"].cw.playbook, r["cell"], [REASONS.index(x) for x in r["reasons"]], status,
            [_r(s["mass"][c], 4) for c in CELLS], _r(s["information"]["client"], 2), _r(s["information"]["integrator"], 2),
            int(s["draft_is_best_somewhere"])]


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    v = sorted(values)
    return {q: v[min(len(v) - 1, int(float(q) * len(v)))] for q in ("0.5", "0.9", "0.99")} | {"max": v[-1]}


def summary(log: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """What the scan found, from its log alone."""
    reasons = Counter(REASONS[i] for row in log for i in row[4])
    only = Counter(REASONS[row[4][0]] for row in log if len(row[4]) == 1)
    admitted = [row for row in log if row[5] == "admitted"]
    return {
        "seeds": {"first": log[0][0], "last": log[-1][0], "scanned": len(log)},
        "status": dict(sorted(Counter(row[5] for row in log).items())),
        "rejected_for": {k: reasons.get(k, 0) for k in REASONS},
        "rejected_for_this_alone": {k: only.get(k, 0) for k in REASONS},
        "admissible_by_cell": {c: sum(1 for row in log if not row[4] and row[3] == c) for c in CELLS},
        "admitted_by_cell": {c: sum(1 for row in admitted if row[3] == c) for c in CELLS},
        "admissible_by_playbook": dict(sorted(Counter(row[2] for row in log if not row[4]).items())),
        "type_pair_share_by_requirement": {c: _r(math.fsum(row[6][i] for row in log) / len(log), 4) for i, c in enumerate(CELLS)},
        "worlds_where_the_draft_is_best_for_some_type_pair": sum(row[9] for row in log),
        "client_seat_information_value": _quantiles([row[7] for row in log]),
        "integrator_seat_information_value_admitted": _quantiles([row[8] for row in admitted]),
    }


def case_of(seed: int, cw: rc.CWorld) -> dict[str, Any]:
    payload = {"world": ra.world_to_dict(cw.w), "integrator_type": None, "extras": {"team": cw.x.team, "site_prep": cw.x.site_prep}}
    it, charge = hidden_types(seed, cw)
    payload["world"]["client"]["risk_charge"] = charge
    payload["integrator_type"] = {"test_cost": it.test_cost, "risk_charge": it.risk_charge}
    AgreementPlugin().validate_payload(payload)
    code = hashlib.sha256(f"{PACK}:{seed}".encode()).hexdigest()[:8]
    raw = {
        "spec_version": CaseManifest.SPEC_VERSION, "case_id": f"{FAMILY_ID}.{SPLIT}.{code}", "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION, "split": SPLIT, "world_seed": seed,
        "seats": [{"id": s, "role": s} for s in ag.SEATS],
        "episode": {"max_logical_actions": ag.MOVES, "termination": list(TERMINATIONS)},
        "visibility_policy": VISIBILITY_POLICY, "payload": payload,
        "provenance": {"generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION, "review_status": "generated"},
    }
    raw["content_sha256"] = case_content_sha256(raw)
    return raw


def index_row(r: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    """The pack's record of one admitted world: its admission, its hidden types, and the drawn types' economics."""
    world, s = r["world"], r["structure"]
    cw, it = rc.world_from(raw["payload"])
    charge = cw.w.client.risk_charge
    row = next(x for x in s["rows"] if x["pair"] == (it, charge))
    d = ag.draft(cw)
    best = AGREEMENTS[best_index(row["joint"], d)]
    info = s["information"]
    return {
        "case_id": raw["case_id"], "content_sha256": raw["content_sha256"], "public_sha256": public_sha256(world.cw),
        "world_seed": world.seed, "regime": world.regime, "playbook": cw.playbook, "cell": r["cell"],
        "gives_a_clause_up": gives_a_clause_up(s["mass"]),
        "requirement_mass": {c: _r(m, 6) for c, m in s["mass"].items()},
        "admission": {
            "expected_available": _r(s["expected"]["available"]), "expected_draft_left": _r(s["expected"]["draft_left"]),
            "expected_loss": {k: _r(s["expected"][k]) for k in SHORTCUTS},
            "information_integrator_seat": _r(info["integrator"]),
            "information_integrator_seat_by_own_type": [_r(v) for v in info["integrator_by_own_type"]],
            "information_client_seat": _r(info["client"]),
            "information_client_seat_by_own_charge": [_r(v) for v in info["client_by_own_charge"]],
        },
        "hidden_types": {"client_risk_charge": charge, "integrator_type": {"test_cost": it.test_cost, "risk_charge": it.risk_charge}},
        "draft": d.label(), "best_agreement": best.label(),
        "clauses_to_change": sorted(k for k in ag.TERMS if getattr(best, k) != getattr(d, k)),
        "requirement": row["requirement"],
        "available_surplus": round(row["available"], 3),
        "left_on_the_table_by_the_draft": round(row["draft_left"], 3),
        "draft_beats_no_deal": bool(row["no_deal"] - row["joint"][INDEX[d]] > 0),
    }


def generator_spec() -> dict[str, Any]:
    return {
        "id": GENERATOR_ID, "version": GENERATOR_VERSION, "split": SPLIT, "base_seed": BASE_SEED, "max_scan": MAX_SCAN,
        "public_stream": "random.Random(seed): a regime of risk_allocation_contracts.CELLS (its ranges; its client charge ignored), "
                         "a playbook it allows, then each public range in risk_allocation_contracts.draw_world's order and rounding",
        "turnkey_price": "round to $10k of (the prior-weighted least joint cost over the 600 agreements + floor margin + the drawn turnkey offset)",
        "margins": {"draft": DRAFT_MARGIN, "shortcut": SHORTCUT_MARGIN, "walk": WALK_MARGIN, "information": INFORMATION_MARGIN},
        "shortcuts": list(SHORTCUTS), "every_protection": {k: c.label() for k, c in EVERY_PROTECTION.items()},
        "quotas": dict(QUOTAS), "give_up_share_at_least": round(GIVE_UP_SHARE, 6),
        "hidden_type_stream": "random.Random(int(sha256('" + TYPE_STREAM + "'))): the client's charge, then the integrator's type, at the declared priors",
        "style_population": STYLE_POPULATION,
    }


def build(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[list[Any]]]:
    """The case files, ``pack.json`` and ``scan.json`` from a scan's result."""
    cases, worlds = [], []
    for r in result["admitted"]:
        raw = case_of(r["seed"], r["world"].cw)
        cases.append(raw)
        worlds.append(index_row(r, raw))
    manifest = {
        "pack": PACK, "family_id": FAMILY_ID, "family_version": FAMILY_VERSION, "generator": generator_spec(),
        "claim_status": "admitted on its structure before any hidden type was drawn; no model has played it. For the plan "
                        "docs/families/datacenter/agreement_confirmatory_plan.md",
        "scan": summary(result["log"]), "scan_log_fields": list(LOG_FIELDS), "worlds": worlds,
    }
    return cases, manifest, [list(row) for row in result["log"]]


def _dump(value: Any) -> str:
    return json.dumps(value, indent=1, sort_keys=True) + "\n"


def files(result: Mapping[str, Any]) -> dict[str, str]:
    """Each file of the pack, by its name under :data:`ROOT`, as the bytes that are committed."""
    cases, manifest, log = build(result)
    out = {f"{raw['case_id'].rsplit('.', 1)[-1]}.json": _dump(raw) for raw in cases}
    out["pack.json"] = _dump(manifest)
    out["scan.json"] = "[\n" + ",\n".join(json.dumps(row, separators=(",", ":")) for row in log) + "\n]\n"
    return out


def load() -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[list[Any]]]:
    manifest = json.loads((ROOT / "pack.json").read_text())
    cases = {w["case_id"]: json.loads((ROOT / f"{w['case_id'].rsplit('.', 1)[-1]}.json").read_text()) for w in manifest["worlds"]}
    return manifest, cases, json.loads((ROOT / "scan.json").read_text())


def replay(log: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """The scan's result rebuilt from its log, recomputing the admitted seeds; the other rows are taken as they stand, and
    :func:`verify_rows` recomputes any of them."""
    admitted = []
    for row in log:
        if row[5] == "admitted":
            r = screen(row[0])
            if log_row(r, "admitted") != list(row):
                raise ValueError(f"seed {row[0]} does not reproduce its log row")
            admitted.append(r)
    return {"log": [list(row) for row in log], "admitted": admitted}


def verify_rows(log: Sequence[Sequence[Any]], seeds: Sequence[int]) -> list[str]:
    """Recompute these seeds' log rows (their status apart) and name those that differ."""
    at = {row[0]: row for row in log}
    out = []
    for seed in seeds:
        r = screen(seed)
        if log_row(r, at[seed][5]) != list(at[seed]):
            out.append(f"seed {seed}: logged {at[seed]}, recomputed {log_row(r, at[seed][5])}")
    return out


def sequence_failures(log: Sequence[Sequence[Any]], quotas: Mapping[str, int] = QUOTAS) -> list[str]:
    """Whether the log's statuses follow from its reasons and cells: seeds in order from the base seed, a seed admitted exactly
    when it breaks no rule and its cell is still open, and the scan stopping on the seed that fills the last quota."""
    out, left = [], dict(quotas)
    if [row[0] for row in log] != list(range(BASE_SEED, BASE_SEED + len(log))):
        out.append("the log is not every seed in order from the base seed")
    for row in log:
        expected = "rejected" if row[4] else "admitted" if left[row[3]] > 0 else "cell_full"
        if expected == "admitted":
            left[row[3]] -= 1
        if row[5] != expected:
            out.append(f"seed {row[0]} is {row[5]}, its reasons and cell make it {expected}")
    if any(left.values()) or (log and log[-1][5] != "admitted"):
        out.append("the scan did not stop on the seed that filled the last quota")
    return out


# ---------------------------------------------------------------------------
# Checks on the pack as a whole.


def development_worlds() -> dict[str, set[str]]:
    """The full-content and public digests of every world in the development packs."""
    full, public = set(), set()
    for pack in DEVELOPMENT_PACKS:
        manifest = json.loads((CASES_ROOT / pack / "pack.json").read_text())
        for w in manifest["worlds"]:
            raw = json.loads((CASES_ROOT / pack / f"{w['case_id'].rsplit('.', 1)[-1]}.json").read_text())
            cw, _ = rc.world_from(raw["payload"])
            full.add(raw["content_sha256"])
            public.add(public_sha256(cw))
    return {"full": full, "public": public}


def pack_failures(manifest: Mapping[str, Any], cases: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Pack-level admission: quotas, the share giving a clause up, distinct worlds, nothing shared with a development pack."""
    worlds = manifest["worlds"]
    out = []
    by_cell = Counter(w["cell"] for w in worlds)
    if dict(by_cell) != {c: q for c, q in QUOTAS.items() if q}:
        out.append(f"cells {dict(by_cell)} are not the quotas {QUOTAS}")
    if sum(w["gives_a_clause_up"] for w in worlds) < GIVE_UP_SHARE * len(worlds) - 1e-9:
        out.append("too few worlds give a clause up")
    for key in ("public_sha256", "content_sha256", "world_seed"):
        if len({w[key] for w in worlds}) != len(worlds):
            out.append(f"two worlds share a {key}")
    dev = development_worlds()
    if {w["content_sha256"] for w in worlds} & dev["full"] or {w["public_sha256"] for w in worlds} & dev["public"]:
        out.append("a world equals a development world")
    if min(w["world_seed"] for w in worlds) < BASE_SEED:
        out.append("a seed below the pack's range")
    if set(cases) != {w["case_id"] for w in worlds}:
        out.append("the case files are not the indexed worlds")
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="scan, admit, draw the types and write the pack")
    parser.add_argument("--check", action="store_true", help="rescan every seed and compare with the committed pack, byte for byte")
    parser.add_argument("--processes", type=int, default=8)
    args = parser.parse_args(argv)
    result = scan(args.processes)
    made = files(result)
    if args.write:
        ROOT.mkdir(parents=True, exist_ok=True)
        for name, text in made.items():
            (ROOT / name).write_text(text)
        print(f"{ROOT}: {len(made) - 2} worlds, {len(result['log'])} seeds scanned")
    if args.check:
        on_disk = {p.name: p.read_text() for p in ROOT.glob("*.json")}
        if on_disk != made:
            print("differs:", sorted(k for k in set(on_disk) | set(made) if on_disk.get(k) != made.get(k)))
            return 1
        print(f"identical: {len(made)} files from {len(result['log'])} seeds")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["BASE_SEED", "CELLS", "DRAFT_MARGIN", "EVERY_PROTECTION", "GIVE_UP_SHARE", "INFORMATION_MARGIN", "MARGIN", "PACK", "QUOTAS", "REASONS",
           "SHORTCUTS", "SHORTCUT_MARGIN", "WALK_MARGIN", "PublicWorld", "admission_failures", "best_index", "build", "case_of", "cell_of", "files",
           "gives_a_clause_up", "hidden_types", "joint_costs", "load", "pack_failures", "pairs_of", "protection", "public_dict", "public_negotiator_move",
           "public_sha256", "public_style", "public_world", "replay", "requirement", "scan", "screen", "sequence_failures", "structure", "summary",
           "verify_rows", "with_charge"]
