"""The hidden-information draft: profiles drawn from a declared market, an
exact posterior, and a pack whose cells each reward a different decision."""

from __future__ import annotations

import random
import re

import pytest

from aeread_families.procurement_allocation import supplier_profiles as sp


def test_posterior_is_calibrated_on_new_suppliers() -> None:
    # Among suppliers the posterior calls p-likely bad, about p of them are bad.
    rng = random.Random(11)
    bins: dict[int, list[float]] = {}
    for _ in range(3000):
        kind = "bad" if rng.random() < sp.MARKET["prior_bad"]["new"] else "good"
        q = sp.posterior_bad(sp.draw_profile(rng, supplier_id="x", segment="new", kind=kind))
        bins.setdefault(min(int(q * 4), 3), []).append((q, kind == "bad"))  # type: ignore[arg-type]
    for rows in bins.values():
        if len(rows) < 150:
            continue
        mean_q = sum(q for q, _ in rows) / len(rows)
        share = sum(b for _, b in rows) / len(rows)
        se = (mean_q * (1 - mean_q) / len(rows)) ** 0.5
        assert abs(mean_q - share) < 4 * se + 0.01


def test_brushed_orders_never_count_as_protected() -> None:
    rng = random.Random(3)
    for _ in range(400):
        p = sp.draw_profile(rng, supplier_id="x", segment="new", kind="bad")
        assert p.protected_orders <= p.orders
        assert p.on_time_protected <= p.protected_orders
        assert sp.posterior_bad(p) > 0.0  # every drawn record is possible under the model


def test_supplier_ids_carry_no_type_word() -> None:
    world = sp.build_world(2441000, "test_thin_record")
    assert world is not None
    for profile in world["profiles_in_listing_order"].values():
        assert re.fullmatch(r"supplier_[a-z2-9]{4}", profile["supplier_id"])
    text = " ".join(world["profile_text"].values()).lower()
    for word in ("good", "bad", "reliable", "flaky", "known", "unproven", "partner", "spot"):
        assert word not in text


@pytest.fixture(scope="module")
def pack() -> list[dict]:
    return sp.build_pack(seeds_per_cell=2)


def test_each_cell_rewards_its_intended_first_action(pack: list[dict]) -> None:
    for world in pack:
        ref = world["buyer_information_reference"]
        assert ref["first_action"] == sp.CELLS[world["cell"]]["intended"]
        values = sorted(ref["first_action_values"].values(), reverse=True)
        assert values[0] - values[1] >= sp.MIN_MARGIN_USD


def test_no_rule_is_optimal_across_the_pack(pack: list[dict]) -> None:
    for rule in sp.RULES:
        assert max(w["ex_ante_regret_usd"][rule] for w in pack) >= sp.MIN_MARGIN_USD, rule


def test_twins_share_the_record_and_differ_only_in_the_hidden_type(pack: list[dict]) -> None:
    twins = [w for w in pack if "twin_of" in w]
    assert twins
    for twin in twins:
        base = next(w for w in pack if w["seed"] == twin["twin_of"] and "twin_of" not in w)
        assert twin["profile_text"] == base["profile_text"]
        assert twin["buyer_information_reference"] == base["buyer_information_reference"]
        assert twin["hidden"]["C"] != base["hidden"]["C"]
        assert sp.TWIN_BAND[0] < twin["posterior_bad"]["C"] < sp.TWIN_BAND[1]


def test_reference_never_beats_the_oracle(pack: list[dict]) -> None:
    for world in pack:
        assert world["realised"]["buyer_information_reference"] <= world["oracle_value"] + 1e-9


def test_market_facts_state_every_prior() -> None:
    text = sp.market_facts_text()
    for share in ("5%", "30%", "25%", "35%"):
        assert share in text
