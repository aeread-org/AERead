"""The integrator-client risk-allocation case: its economics, reference and pack.

What is pinned here is what makes the case a negotiation over risk rather than a
judgment of quality: price never changes the joint value, a clause creates
value only by moving a risk to its cheaper bearer or buying a test, the only
private information is what the integrator charges to carry risk, and the
integrator's counter is how the client learns it.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

import pytest

from aeread_families.datacenter_development import risk_allocation as ra

WORLD = ra.World(
    ra.Risks(0.30, 0.06, 250, 4, 0.25, 180, 3, 0.05, 3000),
    ra.Client(delay_per_week=110, risk_charge=0.7, capital_rate=0.06, insolvency=0.01, turnkey_all_in=11700),
    ra.Terms(**ra.FIXED_TERMS, breakoff=0.05),
)
TYPES = [t for t, _ in WORLD.prior]


@lru_cache(maxsize=1)
def _pack() -> tuple[dict, ...]:
    return tuple(ra.build_pack(seeds_per_cell=2))


def test_price_divides_the_value_and_never_changes_it() -> None:
    for t in TYPES:
        for pkg in ra.PACKAGES:
            price = ra.floor_price(pkg, WORLD, t) + 123.0
            integrator_profit = price - ra.integrator_cost(pkg, WORLD, t)
            client_total = price + ra.client_cost(pkg, WORLD, t)
            assert client_total - integrator_profit == pytest.approx(ra.joint_cost(pkg, WORLD, t))


def test_a_risk_the_integrator_cannot_control_is_never_worth_moving() -> None:
    for row in _pack():
        w = ra.world_from_dict(row["world"])
        for t in TYPES:
            for pkg in ra.PACKAGES:
                if pkg.readiness == "integrator":
                    kept = replace(pkg, readiness="client")
                    assert ra.joint_cost(pkg, w, t) > ra.joint_cost(kept, w, t)


def test_the_warranty_buys_a_test_only_when_it_makes_testing_pay_for_the_integrator() -> None:
    fix = ra.Package("fix", "client", "excluded", "at_signing")
    full = ra.Package("fix_and_delay", "client", "excluded", "at_signing")
    cheap, dear = ra.IntegratorType(40.0, 0.3), ra.IntegratorType(200.0, 0.3)
    assert not ra.pre_stages(ra.OPENING, WORLD, cheap)  # no warranty, no reason to test
    assert ra.pre_stages(fix, WORLD, cheap) and ra.pre_stages(full, WORLD, cheap)
    mid = ra.IntegratorType(120.0, 0.3)
    assert not ra.pre_stages(fix, WORLD, mid) and ra.pre_stages(full, WORLD, mid)  # only delay damages make it test
    # the boundary is exact: 0.24 of defects avoided x 1.3 risk charge x $650k borne = $202.8k against a $200k test
    assert ra.pre_stages(full, WORLD, dear)
    assert not ra.pre_stages(full, WORLD, ra.IntegratorType(203.0, 0.3))
    assert ra.defect_probability(fix, WORLD, dear) == WORLD.risks.defect_without_test


def test_the_opening_reveals_nothing_private_and_one_priced_alternative_reveals_the_type() -> None:
    assert len({ra.opening_price(WORLD, t) for t in TYPES}) == 1
    probe = ra.Package("fix_and_delay", "client", "included", "at_signing")
    assert len({round(ra.ask_price(probe, WORLD, t, 1), 6) for t in TYPES}) == len(TYPES)
    assert len({round(ra.ask_price(ra.OPENING, WORLD, t, 1), 6) for t in TYPES}) == 1  # haggling the opening learns nothing


def test_the_reference_is_the_best_policy_and_its_value_is_the_solver_value() -> None:
    policy = ra.reference_policy(WORLD)
    ref = ra.prior_expected(WORLD, policy)
    root = ra.solve(WORLD, TYPES[0])
    assert ref == pytest.approx(root["expected_cost"], abs=1e-6)
    for name, rule in ra.rules(WORLD).items():
        assert ra.prior_expected(WORLD, rule) >= ref - 1e-6, name


def test_decision_regret_is_zero_for_the_reference_and_prices_a_copied_counter() -> None:
    truth = TYPES[2]
    opening = ra.opening_price(WORLD, truth)
    seen = ra.Seen(1, opening, (ra.OPENING, opening), (), False)
    best = ra.reference_policy(WORLD)(seen)
    assert ra.decision_regret(WORLD, seen, best) == pytest.approx(0.0, abs=1e-9)
    assert ra.decision_regret(WORLD, seen, ra.Action("accept")) > 100
    probe = ra.Package("fix_and_delay", "client", "included", "at_signing")
    counter = ra.ask_price(probe, WORLD, truth, 1)
    after = ra.Seen(2, opening, (probe, counter), ({"round": 1, "package": probe, "price": ra.LOWBALL, "counter": counter},), False)
    assert ra.decision_regret(WORLD, after, ra.Action("accept")) >= WORLD.terms.ask_premium[1] - WORLD.terms.ask_premium[2] - 1e-6


def test_every_number_the_reference_uses_is_in_the_brief() -> None:
    text = ra.brief_text(WORLD, ra.opening_price(WORLD, TYPES[0]))
    for needle in ("30%", "6%", "$250k", "4 weeks", "25%", "$180k", "5%", "$3,000k", "$110k", "$1.70", "$11,700k",
                   "0.3 or 1.2", "$40k or $120k or $200k", "150%", "14%", "$500k", "$200k in round 1", "$0k in round 2",
                   "$400k", "$25k", "$100k per week", "$4,800k", "13 weeks"):
        assert needle in text, needle


def test_each_cell_admits_only_worlds_where_its_move_wins_and_its_losers_lose() -> None:
    pack = _pack()
    assert {row["cell"] for row in pack} == set(ra.CELLS)
    for row in pack:
        spec = ra.CELLS[row["cell"]]
        values = row["first_move_values"]
        assert min(values[k] for k in spec["first"]) == pytest.approx(0.0, abs=1e-6)
        for name in spec["losers"]:
            assert row["rule_regret_prior"][name] >= ra.LOSER_MARGIN


def test_no_rule_is_right_everywhere_and_copying_the_counter_is_never_right() -> None:
    pack = _pack()
    for name in ra.rules(WORLD):
        assert max(row["rule_regret_prior"][name] for row in pack) >= ra.LOSER_MARGIN, name
    assert min(row["rule_regret_prior"]["take_the_first_counter"] for row in pack) >= 100


def test_twins_share_every_public_fact_and_the_first_move_but_not_the_contract() -> None:
    pack = _pack()
    by_slug = {row["slug"]: row for row in pack}
    twins = [row for row in pack if "twin_of" in row]
    assert twins
    for twin in twins:
        base = by_slug[twin["twin_of"]]
        assert twin["world"] == base["world"] and twin["opening_price"] == base["opening_price"]
        assert twin["reference_first_move"] == base["reference_first_move"]
        assert twin["efficient_package"] != base["efficient_package"]
        assert twin["hidden_type"] != base["hidden_type"]


def test_no_single_contract_is_always_efficient() -> None:
    signed = {row["efficient_package"] for row in _pack() if row["cell"] != "walk_away"}
    assert len(signed) >= 3
