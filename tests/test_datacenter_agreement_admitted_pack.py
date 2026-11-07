"""Gate 1 of the agreement case: the admitted pack ``agreement_admitted_v1`` (``agreement_admitted_pack``).

Each check is made against a counterexample that breaks it. What is tested:

1. The committed pack is reproduced byte for byte from its generator and its scan log; the log's statuses follow from its
   reasons and cells; a fixed sample of its rows recomputes exactly. (``python -m ...agreement_admitted_pack --check``
   rescans all 2,729 seeds and compares every file; it is not run here because it takes a minute on eight cores.)
2. Every admission condition holds in every world. The quantities are recomputed here from the environment's own cost
   functions (``risk_allocation_contracts.integrator_cost`` and ``client_cost``), not from the module's.
3. Each condition rejects a world that breaks it: worlds the scan rejected for that rule alone pass once its margin is
   removed, and constructed worlds (the draft set to the prior-best agreement, a client with one possible charge, a
   turnkey price far below the deal) fail the rule they were built to fail.
4. The hidden types come from their own stream: they are what the stream gives for the seed, the stream ignores the
   world's public parameters and cell, admission is identical whichever type is substituted and fails if it reads one,
   and the counts by cell agree with the declared prior (a third each for the client's charge).
5. Through the environment's hooks (the oracle test's harness): the full-information pair loses 0 in every world and
   the draft pair loses what its midpoint predicts; each shortcut, played for every type pair of the first world of
   each cell, loses exactly what admission assigned it.
6. The publicly drawn counterpart style does not move with the client's hidden charge; ``drawn_style`` does (DC-D-32).
7. No world shares a seed range, a content digest or its drawn public parameters with a development pack.
8. The variance pilot ``agreement_admitted_pilot_v1`` is the same rules on its own seeds: reproduced byte for byte from
   its scan log, at its quotas, keyed by its own pack id, sharing no world with the admitted pack or a development pack,
   and played through the environment the full-information pair loses 0 and the draft pair loses its midpoint. Adding it
   left the admitted pack's files unchanged (``pack.json`` sha256 265770bd..., the digest the confirmatory plan pins).

Profile: ``docs/families/datacenter/qc.md`` section 11.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import replace
from functools import lru_cache

import numpy as np
import pytest
from scipy import stats

from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack as m
from aeread_families.datacenter_development import agreement_negotiator as an
from aeread_families.datacenter_development import risk_allocation as ra
from aeread_families.datacenter_development import risk_allocation_contracts as rc
from aeread_families.datacenter_development.risk_allocation_menu import self_manage_cost
from tests.test_datacenter_agreement_oracle_run import draft_failures, oracle_failures, play, recorded

PACK = m.PACK
TOL = 1e-6
#: Declared before the pack was built: a type-by-cell table this far from the prior would happen less than once in a hundred.
P_FLOOR = 0.01


@lru_cache(maxsize=None)
def committed():
    return m.load()


@lru_cache(maxsize=None)
def public(seed: int):
    return m.public_world(seed)[0]


# ---------------------------------------------------------------------------
# 1. Reproduction.


def test_the_committed_pack_is_reproduced_byte_for_byte_from_its_generator_and_scan_log() -> None:
    manifest, cases, log = committed()
    on_disk = {p.name: p.read_text() for p in m.ROOT.glob("*.json")}
    assert len(on_disk) == 62 and len(cases) == 60
    assert m.files(m.replay(log)) == on_disk
    assert m.sequence_failures(log) == []
    assert manifest["generator"] == m.generator_spec() and manifest["scan"] == m.summary(log)


def test_a_sample_of_the_scan_log_recomputes_exactly_and_a_falsified_row_is_caught() -> None:
    _, _, log = committed()
    sample = [row[0] for row in log[:40]] + [row[0] for row in log[40::40]]
    assert m.verify_rows(log, sample) == []
    falsified = [list(row) for row in log]
    i = next(k for k, row in enumerate(falsified) if row[5] == "rejected")
    falsified[i][4] = []  # the row now claims the seed broke no rule
    assert m.sequence_failures(falsified) and m.verify_rows(falsified, [falsified[i][0]])


# ---------------------------------------------------------------------------
# 2. Every condition, recomputed here from the environment's cost functions.


@lru_cache(maxsize=None)
def economics_here(cw: rc.CWorld) -> list[dict]:
    """For every pair of hidden types: the prior weight, the joint cost of every agreement and the walk-away value."""
    floor = cw.w.terms.floor_margin
    weight = dict(cw.w.prior)
    z = math.fsum(weight[t] for t in cw.types)
    out = []
    for it in cw.types:
        for charge, q in cw.w.client_prior:
            w = replace(cw.w, client=replace(cw.w.client, risk_charge=charge))
            joint = {c: math.fsum((rc.integrator_cost(c, w, it, cw.x), rc.client_cost(c, w, it, cw.x))) for c in ag.ALL_AGREEMENTS}
            no_deal = min(cw.w.client.turnkey_all_in, self_manage_cost(w, cw.x.team, charge)) - floor
            out.append({"it": it, "charge": charge, "p": weight[it] / z * q, "joint": joint, "no_deal": no_deal,
                        "available": max(0.0, no_deal - min(joint.values()))})
    return out


def conditions_here(cw: rc.CWorld) -> dict:
    e = economics_here(cw)
    d = ag.draft(cw)
    S = lambda r, c: r["no_deal"] - r["joint"][c]  # noqa: E731
    E = lambda f: math.fsum(r["p"] * f(r) for r in e)  # noqa: E731
    pc, pi = m.EVERY_PROTECTION["client"], m.EVERY_PROTECTION["integrator"]

    def information(own_key) -> tuple[float, bool]:
        total, varies = [], True
        for own in {own_key(r) for r in e}:
            g = [r for r in e if own_key(r) == own]
            z = math.fsum(r["p"] for r in g)
            walk = math.fsum(r["p"] * r["available"] for r in g) / z
            sign = max(math.fsum(r["p"] * S(r, c) for r in g) / z for c in ag.ALL_AGREEMENTS)
            total.append(z * (walk - max(0.0, sign)))
            outcomes = {min(r["joint"], key=lambda c: (round(r["joint"][c], 6), c != d, c)) if r["available"] > 1e-9 else None for r in g}
            varies = varies and len(outcomes) >= 2
        return math.fsum(total), varies

    info_i, varies_i = information(lambda r: r["it"])
    info_c, _ = information(lambda r: r["charge"])
    return {
        "expected_available": E(lambda r: r["available"]),
        "expected_draft_left": E(lambda r: r["joint"][d] - min(r["joint"].values())),
        "sign_the_draft": E(lambda r: r["available"] - S(r, d)),
        "haggle_the_price": E(lambda r: r["available"] - max(0.0, S(r, d))),
        "every_protection_client": E(lambda r: r["available"] - max(0.0, S(r, pc))),
        "every_protection_integrator": E(lambda r: r["available"] - max(0.0, S(r, pi))),
        "walk": E(lambda r: r["available"]),
        "information_integrator_seat": info_i, "integrator_varies": varies_i, "information_client_seat": info_c,
    }


@lru_cache(maxsize=None)
def all_conditions_here() -> tuple:
    manifest, cases, _ = committed()
    return tuple((w, conditions_here(rc.world_from(cases[w["case_id"]]["payload"])[0])) for w in manifest["worlds"])


def test_every_admission_condition_holds_in_every_world_recomputed_from_the_environments_cost_functions() -> None:
    failures = []
    for w, here in all_conditions_here():
        a = w["admission"]
        say = lambda what: failures.append(f"{w['case_id']}: {what}")  # noqa: E731
        if here["expected_draft_left"] < m.DRAFT_MARGIN - TOL:
            say(f"the draft leaves {here['expected_draft_left']}")
        if here["information_integrator_seat"] < m.INFORMATION_MARGIN - TOL or not here["integrator_varies"]:
            say(f"the integrator's information is worth {here['information_integrator_seat']}")
        for name in m.SHORTCUTS:
            if here[name] < m.MARGIN[name] - TOL:
                say(f"{name} loses only {here[name]}")
            if abs(here[name] - a["expected_loss"][name]) > 1e-3:
                say(f"{name} recorded {a['expected_loss'][name]}, recomputed {here[name]}")
        for key in ("expected_available", "expected_draft_left", "information_integrator_seat", "information_client_seat"):
            if abs(here[key] - a[key]) > 1e-3:
                say(f"{key} recorded {a[key]}, recomputed {here[key]}")
    assert failures == []


def test_the_pack_meets_its_quotas_and_its_give_up_share_and_fails_when_either_is_broken() -> None:
    manifest, cases, _ = committed()
    assert m.pack_failures(manifest, cases) == []
    assert Counter(w["cell"] for w in manifest["worlds"]) == {"walk": 20, "trade": 20, "hand_risk_over": 20}
    assert sum(w["gives_a_clause_up"] for w in manifest["worlds"]) >= 20
    broken = json.loads(json.dumps(manifest))
    for w in broken["worlds"]:
        w["gives_a_clause_up"] = False
    broken["worlds"][0]["cell"] = "trade"
    failures = m.pack_failures(broken, cases)
    assert any("quotas" in f for f in failures) and any("give a clause up" in f for f in failures)


def test_the_turnkey_price_is_anchored_on_the_prior_not_on_a_drawn_type() -> None:
    manifest, cases, _ = committed()
    for w in manifest["worlds"]:
        cw, _ = rc.world_from(cases[w["case_id"]]["payload"])
        _, _, offset = m._unanchored(w["world_seed"])
        e = economics_here(cw)
        anchor = math.fsum(r["p"] * (min(r["joint"].values()) + cw.w.terms.floor_margin) for r in e)
        assert cw.w.client.turnkey_all_in == ra._round(anchor + offset, 10)
        assert public(w["world_seed"]).cw.w.client.turnkey_all_in == cw.w.client.turnkey_all_in


# ---------------------------------------------------------------------------
# 3. Each condition rejects a world that breaks it.


def _first_seed(log, reason: str, alone: bool):
    k = m.REASONS.index(reason)
    return next(row[0] for row in log if (row[4] == [k] if alone else k in row[4]))


@pytest.mark.parametrize("reason", ["every_protection_client_loses_under_margin", "walk_loses_under_margin"])
def test_a_world_rejected_for_one_rule_alone_is_admitted_once_that_rule_is_removed(reason: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, log = committed()
    seed = _first_seed(log, reason, alone=True)
    assert m.screen(seed)["reasons"] == [reason]
    monkeypatch.setitem(m.MARGIN, reason.removesuffix("_loses_under_margin"), -math.inf)
    assert m.screen(seed)["reasons"] == []


@pytest.mark.parametrize("half", ["margin", "every_own_type"])
def test_both_halves_of_the_information_rule_reject_a_world_on_their_own(half: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The margin half: a world whose integrator information is worth under the margin, admitted once the margin is removed.
    The literal half: a world in which some own type of the integrator faces one best outcome whatever the client's charge,
    still rejected with the margin removed. (In the scan the literal half never rejects a world alone.)"""
    _, _, log = committed()
    k = m.REASONS.index("integrator_reads_best_off_its_brief")
    for seed in (row[0] for row in log if (row[4] == [k] if half == "margin" else k in row[4])):
        varies = m.screen(seed)["structure"]["information"]["integrator_varies_for_every_own_type"]
        if varies == (half == "margin"):
            break
    else:
        pytest.fail(f"no scanned world fails the {half} half")
    monkeypatch.setattr(m, "INFORMATION_MARGIN", -math.inf)
    reasons = m.screen(seed)["reasons"]
    assert reasons == [] if half == "margin" else "integrator_reads_best_off_its_brief" in reasons


@pytest.mark.parametrize("reason", ["draft_near_best", "sign_the_draft_loses_under_margin", "haggle_the_price_loses_under_margin",
                                    "every_protection_integrator_loses_under_margin"])
def test_the_rules_that_never_reject_alone_still_reject_a_scanned_world(reason: str) -> None:
    _, _, log = committed()
    assert reason in m.screen(_first_seed(log, reason, alone=False))["reasons"]


def _admitted_public(cell: str):
    manifest, _, _ = committed()
    seed = next(w["world_seed"] for w in manifest["worlds"] if w["cell"] == cell)
    return public(seed)


def test_a_draft_that_is_already_the_best_agreement_fails_the_draft_and_draft_shortcut_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """The world of an admitted hand-over cell with one possible pair of types, and the integrator's paper set to that pair's c*."""
    world = _admitted_public("hand_risk_over")
    cw = world.cw
    it, charge = cw.types[0], cw.w.client_prior[-1][0]
    one = replace(world, cw=replace(cw, w=replace(cw.w, prior=((it, 1.0),), client_prior=((charge, 1.0),))))
    (row,) = m.structure(one)["rows"]
    assert row["available"] > 0 and row["best"] != ag.draft(cw)
    monkeypatch.setattr(ag, "draft", lambda _: row["best"])
    s = m.structure(one)
    assert s["expected"]["draft_left"] == 0.0 and s["expected"]["haggle_the_price"] == pytest.approx(0.0, abs=1e-9)
    reasons = m.admission_failures(s)
    assert {"draft_near_best", "sign_the_draft_loses_under_margin", "haggle_the_price_loses_under_margin"} <= set(reasons)


def test_a_client_with_one_possible_charge_fails_the_information_rule() -> None:
    world = _admitted_public("trade")
    cw = world.cw
    one = replace(world, cw=replace(cw, w=replace(cw.w, client_prior=((0.75, 1.0),))))
    s = m.structure(one)
    assert s["information"]["integrator"] == pytest.approx(0.0, abs=1e-9)
    assert "integrator_reads_best_off_its_brief" in m.admission_failures(s)


def test_a_turnkey_price_far_below_the_deal_fails_the_walk_rule() -> None:
    world = _admitted_public("walk")
    cw = world.cw
    cheap = replace(world, cw=replace(cw, w=replace(cw.w, client=replace(cw.w.client, turnkey_all_in=cw.w.client.turnkey_all_in - 1500.0))))
    reasons = m.admission_failures(m.structure(cheap))
    assert "walk_loses_under_margin" in reasons


# ---------------------------------------------------------------------------
# 4. The hidden types come from their own stream.


def test_the_hidden_types_are_what_their_own_stream_gives_and_the_stream_ignores_the_world() -> None:
    manifest, cases, _ = committed()
    by_playbook = {}
    for w in manifest["worlds"]:
        cw, it = rc.world_from(cases[w["case_id"]]["payload"])
        assert m.hidden_types(w["world_seed"], cw) == (it, cw.w.client.risk_charge)
        assert w["hidden_types"] == {"client_risk_charge": cw.w.client.risk_charge, "integrator_type": {"test_cost": it.test_cost, "risk_charge": it.risk_charge}}
        by_playbook.setdefault(cw.playbook, []).append((w, cw))
    for group in by_playbook.values():  # another world of the same playbook, in another cell or regime, draws the same types for a seed
        for (w, cw), (_, other) in zip(group, group[1:] + group[:1]):
            assert m.hidden_types(w["world_seed"], other) == m.hidden_types(w["world_seed"], cw)


def test_admission_is_the_same_whichever_type_is_substituted_and_cannot_read_one() -> None:
    manifest, _, _ = committed()
    for w in manifest["worlds"][::6]:
        world = public(w["world_seed"])
        with pytest.raises(TypeError):
            world.cw.best_outside  # the public world has no client charge: anything reading it fails
        base = m.structure(world)
        for charge, _ in world.cw.w.client_prior:
            typed = replace(world, cw=m.with_charge(world.cw, charge))
            s = m.structure(typed)
            assert m.admission_failures(s) == m.admission_failures(base) == []
            assert s["expected"] == base["expected"] and s["mass"] == base["mass"] and s["information"] == base["information"]


def _chi2_against_prior(table: np.ndarray, prior: np.ndarray) -> float:
    expected = table.sum(axis=1, keepdims=True) * prior[None, :]
    return float(((table - expected) ** 2 / expected).sum())


def test_the_client_charge_is_independent_of_the_cell_and_at_the_declared_prior() -> None:
    manifest, _, _ = committed()
    cells = ("walk", "trade", "hand_risk_over")
    charges = (0.15, 0.75, 1.55)
    table = np.array([[sum(1 for w in manifest["worlds"] if w["cell"] == c and w["hidden_types"]["client_risk_charge"] == x) for x in charges] for c in cells])
    observed = _chi2_against_prior(table, np.full(3, 1 / 3))
    p_prior = float(stats.chi2.sf(observed, df=len(cells) * (len(charges) - 1)))
    # the same statistic under draws at the prior for these cell sizes, so small counts need no asymptotics
    rng = np.random.default_rng(20261013)
    sims = np.array([_chi2_against_prior(np.array([rng.multinomial(n, [1 / 3] * 3) for n in table.sum(axis=1)]), np.full(3, 1 / 3)) for _ in range(20000)])
    p_exact = float((sims >= observed - 1e-12).mean())
    p_independent = float(stats.chi2_contingency(table)[1])
    assert table.sum() == 60 and min(p_prior, p_exact, p_independent) >= P_FLOOR, (table.tolist(), p_prior, p_exact, p_independent)


def test_the_integrator_type_is_at_the_declared_prior_within_each_playbook() -> None:
    manifest, cases, _ = committed()
    stat, df = 0.0, 0
    for playbook in rc.PLAYBOOKS:
        group = [rc.world_from(cases[w["case_id"]]["payload"]) for w in manifest["worlds"] if w["playbook"] == playbook]
        types = group[0][0].types if group else ()
        if len(types) < 2:
            continue
        counts = np.array([sum(1 for _, it in group if it == t) for t in types])
        expected = len(group) / len(types)
        stat += float(((counts - expected) ** 2 / expected).sum())
        df += len(types) - 1
    assert float(stats.chi2.sf(stat, df)) >= P_FLOOR


def test_the_independence_check_catches_types_tied_to_the_cell() -> None:
    """DC-D-33's pattern: the charge set by the cell. The check must reject it."""
    tied = np.array([[20, 0, 0], [0, 20, 0], [0, 0, 20]])
    assert float(stats.chi2.sf(_chi2_against_prior(tied, np.full(3, 1 / 3)), df=6)) < P_FLOOR


# ---------------------------------------------------------------------------
# 5. Through the environment.


def test_the_full_information_pair_loses_nothing_in_every_admitted_world_and_walks_where_no_deal_is_worth_signing() -> None:
    assert oracle_failures(recorded(PACK, "oracle")) == []
    manifest, _, _ = committed()
    no_deal = sum(w["available_surplus"] <= 0 for w in manifest["worlds"])
    assert no_deal == sum(w["requirement"] == "walk" for w in manifest["worlds"]) and 0 < no_deal < 60


def test_the_draft_pair_loses_what_signing_the_draft_at_its_midpoint_predicts() -> None:
    recs = recorded(PACK, "draft")
    failures, lost = draft_failures(recs)
    assert failures == []
    # the draft is never the best agreement, so it loses something in every world with a deal worth signing
    assert all(x > 0 for (row, _), x in zip(recs, lost) if row["available_surplus"] > 0)


def _shortcut_policies():
    def protect(side: str):
        target = m.EVERY_PROTECTION[side]

        def move(state, cw, it):
            if state["to_move"] == "client":
                return {"action": "sign" if state["standing"] is not None else "walk", "clauses": None, "price": None, "note": "shortcut"}
            ic, cc = ag.costs(cw, it, target)
            surplus = cw.best_outside[1] - cw.w.terms.floor_margin - ic - cc
            if surplus <= 1e-9:
                return {"action": "walk", "clauses": None, "price": None, "note": "shortcut"}
            now = ag.draft(cw)
            return {"action": "redline", "clauses": {k: (getattr(target, k) if getattr(target, k) != getattr(now, k) else None) for k in ag.TERMS},
                    "price": round(ic + cw.w.terms.floor_margin + surplus / 2.0, 6), "note": "shortcut"}
        return move

    def sign_the_draft(state, cw, it):
        if state["to_move"] == "client":
            return {"action": "sign", "clauses": None, "price": None, "note": "shortcut"}
        ic, _ = ag.costs(cw, it, ag.draft(cw))
        return {"action": "redline", "clauses": {k: None for k in ag.TERMS}, "price": round(ic + cw.w.terms.floor_margin, 6), "note": "shortcut"}

    def walk(state, cw, it):
        return {"action": "walk", "clauses": None, "price": None, "note": "shortcut"}

    return {"sign_the_draft": sign_the_draft, "haggle_the_price": ag.POLICIES["draft"], "every_protection_client": protect("client"),
            "every_protection_integrator": protect("integrator"), "walk": walk}


def test_each_shortcut_played_through_the_environment_loses_what_admission_assigned_it(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, policy in _shortcut_policies().items():
        monkeypatch.setitem(ag.POLICIES, f"shortcut_{name}", policy)
    manifest, cases, _ = committed()
    checked = 0
    for cell in ("walk", "trade", "hand_risk_over"):
        w = next(x for x in manifest["worlds"] if x["cell"] == cell)
        s = m.structure(public(w["world_seed"]))
        expected = {name: 0.0 for name in m.SHORTCUTS}
        for row in s["rows"]:
            it, charge = row["pair"]
            payload = json.loads(json.dumps(cases[w["case_id"]]["payload"]))
            payload["world"]["client"]["risk_charge"] = charge
            payload["integrator_type"] = {"test_cost": it.test_cost, "risk_charge": it.risk_charge}
            for name in m.SHORTCUTS:
                lost = play(payload, f"shortcut_{name}")["outcome"]["grade"]["joint_value_lost"]
                assert lost == pytest.approx(row["loss"][name], abs=1e-5), (w["case_id"], row["pair"], name)
                expected[name] += row["p"] * lost
                checked += 1
        for name in m.SHORTCUTS:
            assert expected[name] == pytest.approx(w["admission"]["expected_loss"][name], abs=1e-3)
    assert checked >= 3 * 5 * 3


# ---------------------------------------------------------------------------
# 6. The counterpart's style.


def test_the_public_style_ignores_the_hidden_charge_where_drawn_style_does_not() -> None:
    manifest, cases, _ = committed()
    old_moves = 0
    for i, w in enumerate(manifest["worlds"]):
        cw, it = rc.world_from(cases[w["case_id"]]["payload"])
        assert m.public_style(cw, "client") == m.public_style(public(w["world_seed"]).cw, "client")  # the case file and the generator agree
        for seat in ag.SEATS:
            by_charge = {charge: m.public_style(m.with_charge(cw, charge), seat) for charge, _ in cw.w.client_prior}
            assert len(set(by_charge.values())) == 1
            old_moves += len({an.drawn_style(m.with_charge(cw, charge), seat) for charge, _ in cw.w.client_prior}) > 1
        if i % 5:
            continue
        # the integrator's scripted opening cannot depend on a charge it is not told (every fifth world: each opening prices 600 agreements)
        openings = {json.dumps(m.public_negotiator_move(ag.initial_state(m.with_charge(cw, charge)), m.with_charge(cw, charge), it), sort_keys=True)
                    for charge, _ in cw.w.client_prior}
        assert len(openings) == 1
    assert old_moves == 2 * len(manifest["worlds"])  # DC-D-32: the old draw changes with the charge in every world and seat


# ---------------------------------------------------------------------------
# 7. Disjoint from the development packs.


def _draw_signature(cw: rc.CWorld) -> str:
    client = {k: v for k, v in vars(cw.w.client).items() if k not in ("risk_charge", "turnkey_all_in")}
    return json.dumps([vars(cw.w.risks), client, vars(cw.x), cw.playbook], sort_keys=True)


def test_no_world_shares_seeds_content_or_drawn_parameters_with_a_development_pack() -> None:
    manifest, cases, _ = committed()
    dev_seeds, dev_sigs = set(), set()
    for pack in m.DEVELOPMENT_PACKS:
        dev_manifest = json.loads((m.CASES_ROOT / pack / "pack.json").read_text())
        for w in dev_manifest["worlds"]:
            raw = json.loads((m.CASES_ROOT / pack / f"{w['case_id'].rsplit('.', 1)[-1]}.json").read_text())
            dev_seeds.add(raw["world_seed"])
            dev_sigs.add(_draw_signature(rc.world_from(raw["payload"])[0]))
    dev = m.development_worlds()
    assert min(w["world_seed"] for w in manifest["worlds"]) > max(dev_seeds) + 2_000_000
    assert manifest["scan"]["seeds"]["first"] == m.BASE_SEED > max(dev_seeds)
    for w in manifest["worlds"]:
        cw, _ = rc.world_from(cases[w["case_id"]]["payload"])
        assert w["content_sha256"] not in dev["full"] and m.public_sha256(cw) == w["public_sha256"] not in dev["public"]
        assert _draw_signature(cw) not in dev_sigs
    # the check is not vacuous: a development world is caught
    dev_manifest = json.loads((m.CASES_ROOT / "agreement_dev_v1" / "pack.json").read_text())
    planted = json.loads(json.dumps(manifest))
    planted["worlds"][0]["public_sha256"] = next(iter(dev["public"]))
    assert "a world equals a development world" in m.pack_failures(planted, cases)
    assert dev_manifest["worlds"]


# ---------------------------------------------------------------------------
# 8. The variance pilot.

ADMITTED_PACK_SHA256 = "265770bd86576c0577035a9f3e2943d1a058e06b7845743474737a8ec3ed700b"


@lru_cache(maxsize=None)
def pilot():
    return m.load(m.PILOT)


def test_the_admitted_pack_is_the_one_the_confirmatory_plan_pins() -> None:
    assert hashlib.sha256((m.ROOT / "pack.json").read_bytes()).hexdigest() == ADMITTED_PACK_SHA256
    assert m.ADMITTED.root == m.ROOT and m.ADMITTED.type_stream == m.TYPE_STREAM and m.generator_spec() == m.generator_spec(m.ADMITTED)


def test_the_pilot_pack_is_reproduced_byte_for_byte_from_its_scan_log_at_its_own_quotas() -> None:
    manifest, cases, log = pilot()
    on_disk = {p.name: p.read_text() for p in m.PILOT.root.glob("*.json")}
    assert m.files(m.replay(log), m.PILOT) == on_disk
    assert m.sequence_failures(log, spec=m.PILOT) == [] and m.sequence_failures(log)  # not the admitted pack's sequence
    assert manifest["generator"] == m.generator_spec(m.PILOT) and manifest["scan"] == m.summary(log)
    assert manifest["scan"]["seeds"]["first"] == m.PILOT.base_seed == 6_500_000
    assert Counter(w["cell"] for w in manifest["worlds"]) == {"walk": 4, "trade": 4, "hand_risk_over": 4}
    assert all(w["case_id"].split(".")[1] == "pilot" for w in manifest["worlds"])


def test_the_pilot_shares_no_world_with_the_admitted_pack_and_its_types_come_from_its_own_stream() -> None:
    manifest, cases, _ = pilot()
    assert m.pack_failures(manifest, cases, m.PILOT) == []
    admitted, _, _ = committed()
    assert min(w["world_seed"] for w in manifest["worlds"]) > max(w["world_seed"] for w in admitted["worlds"])
    for w in manifest["worlds"]:
        cw, it = rc.world_from(cases[w["case_id"]]["payload"])
        assert m.hidden_types(w["world_seed"], cw, m.PILOT) == (it, cw.w.client.risk_charge)
    # the check is not vacuous: an admitted world planted in the pilot is caught
    planted = json.loads(json.dumps(manifest))
    planted["worlds"][0]["public_sha256"] = admitted["worlds"][0]["public_sha256"]
    assert "a world equals an admitted world" in m.pack_failures(planted, cases, m.PILOT)


def test_through_the_environment_the_pilot_oracle_loses_nothing_and_the_draft_pair_loses_its_midpoint() -> None:
    assert oracle_failures(recorded(m.PILOT.pack, "oracle")) == []
    failures, _ = draft_failures(recorded(m.PILOT.pack, "draft"))
    assert failures == []


# ---------------------------------------------------------------------------
# 9. The free baselines against the public firm style (agreement_admitted_baselines).


def test_the_committed_free_baselines_recompute_and_the_best_plan_is_never_below_the_first_offer() -> None:
    from aeread_families.datacenter_development import agreement_admitted_baselines as fb
    from aeread_families.datacenter_development import agreement_pack as ap

    committed_report = json.loads((fb.OUT / "reports" / "baselines.json").read_text())
    assert (fb.OUT / "README.md").read_text() == fb.readme(committed_report)
    assert set(committed_report["packs"]) == set(fb.PACKS)
    for pack in fb.PACKS:
        rows = committed_report["packs"][pack]["worlds"]
        assert committed_report["packs"][pack]["summary"] == fb._summary(rows)
        _, raw = ap.load(pack)
        assert len(rows) == len(raw)
        for row in rows:
            for seat in ag.SEATS:
                s = row["seats"][seat]
                assert s["best_plan"]["earnings"] >= s["first_offer"]["earnings"] - 1e-3
        # two worlds of each pack recomputed from scratch
        by_code = {c["case_id"].rsplit(".", 1)[-1]: c["payload"] for c in raw.values()}
        for row in (rows[0], rows[-1]):
            assert fb.one_world((row["world"], by_code[row["world"]])) == row
