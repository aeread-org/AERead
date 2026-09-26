"""The Housing oracle gap: an exact, listing-indexed split of welfare below the full-information oracle."""

from __future__ import annotations

import collections
import itertools
import json
import random
from pathlib import Path

import pytest

from aeread.shared_runner.run.publication import assert_public_payload
from aeread_families.housing import environment as hz
from aeread_families.housing import failure_taxonomy
from aeread_families.housing import oracle_gap as gap

COST = 100.0


def _world(surplus: list[list[float]]) -> hz.BidWorld:
    """A world whose costs are all 100, so a pair's surplus is its value minus 100."""
    listings = len(surplus[0])
    return hz.BidWorld(listings=[None] * listings, values=[[COST + s for s in row] for row in surplus],
                       costs=[COST] * listings, ask=[COST] * listings)


def _split(surplus, pairs, rents=None):
    w = _world(surplus)
    oracle = hz.assignment_oracle(w.surplus)
    rents = rents or {t: COST for t, _ in pairs}
    parts, rows = gap.lease_parts(pairs, rents, w, oracle.pairs)
    welfare = sum(w.values[t][l] - w.costs[l] for t, l in pairs)
    assert sum(parts.values()) == pytest.approx(welfare - oracle.total)
    for key in gap.PART_KEYS:
        assert sum(r["amount"] for r in rows if r["component"] == key) == pytest.approx(parts[key])
    return parts, rows, oracle


# oracle: tenant 0 -> listing 0 (10), 1 -> 1 (8), 2 -> 2 (7); listing 3 is worth leasing to nobody, listing 4 only to tenant 2
SURPLUS = [[10.0, 4.0, 1.0, -5.0, -1.0],
           [6.0, 8.0, 2.0, -5.0, -1.0],
           [-3.0, 5.0, 7.0, -2.0, 3.0]]


def test_the_oracle_itself_has_no_gap() -> None:
    parts, rows, oracle = _split(SURPLUS, [(0, 0), (1, 1), (2, 2)])
    assert oracle.pairs == [(0, 0), (1, 1), (2, 2)]
    assert all(v == 0 for v in parts.values()) and rows == []


def test_swapped_tenants_an_empty_listing_and_a_value_destroying_lease() -> None:
    parts, rows, _ = _split(SURPLUS, [(1, 0), (0, 1), (2, 3)])
    assert parts == pytest.approx({"missorted_tenant": (6 - 10) + (4 - 8), "oracle_listing_left_empty": -7.0,
                                   "extra_listing_leased": 0.0, "value_destroying_pair": -2.0})
    empty = next(r for r in rows if r["component"] == "oracle_listing_left_empty")
    assert (empty["listing_id"], empty["tenant_id"], empty["oracle_tenant_id"], empty["rent"]) == (2, None, 2, None)


def test_an_extra_listing_is_credited_and_its_tenant_charged_where_it_left() -> None:
    parts, _, _ = _split(SURPLUS, [(0, 0), (1, 1), (2, 4)])
    assert parts == pytest.approx({"extra_listing_leased": 3.0, "oracle_listing_left_empty": -7.0,
                                   "missorted_tenant": 0.0, "value_destroying_pair": 0.0})


def test_a_wrong_tenant_can_be_worth_more_on_a_listing_than_the_oracles_own() -> None:
    surplus = [[10.0, 9.0], [1.0, 8.0]]
    parts, _, oracle = _split(surplus, [(0, 1)])
    assert oracle.pairs == [(0, 0), (1, 1)]
    assert parts["missorted_tenant"] == pytest.approx(1.0) and parts["oracle_listing_left_empty"] == pytest.approx(-10.0)


def test_a_value_destroying_lease_on_an_oracle_listing_loses_the_oracle_pair_and_its_own_deficit() -> None:
    parts, rows, _ = _split(SURPLUS, [(2, 0), (1, 1)])
    assert parts["missorted_tenant"] == pytest.approx(-10.0) and parts["value_destroying_pair"] == pytest.approx(-3.0)
    assert parts["oracle_listing_left_empty"] == pytest.approx(-7.0)
    assert [r["component"] for r in rows if r["listing_id"] == 0] == ["missorted_tenant", "value_destroying_pair"]


def test_a_listing_or_tenant_leased_twice_is_refused() -> None:
    with pytest.raises(ValueError):
        _split(SURPLUS, [(0, 0), (1, 0)])


def test_classes_match_the_taxonomy_and_carry_their_amounts() -> None:
    w = _world(SURPLUS)
    oracle = hz.assignment_oracle(w.surplus)
    pairs = [(1, 0), (0, 1), (2, 3)]
    rents = {1: 0.0, 0: 110.0, 2: 99.0}  # a zero rent, a rent above the tenant's value, a rent below cost
    found = gap.cell_classes(pairs, rents, w, oracle.pairs, "glm_53_flash", "deepseek_v4_flash")
    by = collections.defaultdict(list)
    for item in found:
        by[item["class"]].append(item["amount"])
    assert by["A1_tenant_signed_above_own_value"] == pytest.approx([110.0 - 104.0, 99.0 - 98.0])
    assert by["A2_landlord_signed_at_zero_rent"] == pytest.approx([COST])
    assert by["A3_landlord_signed_below_cost"] == pytest.approx([1.0])
    assert by["A4_pair_destroys_value"] == pytest.approx([2.0])
    assert by["B1_oracle_listing_left_empty"] == pytest.approx([7.0])
    assert by["B2_leased_a_listing_the_oracle_leaves_empty"] == pytest.approx([-2.0])
    # best filling of listings {0, 1, 3}: 0->0, 1->1, 2->3 = 10 + 8 - 2 = 16, against 6 + 4 - 2 = 8 realized
    assert by["B3_right_listings_wrong_tenants"] == pytest.approx([8.0])
    row = {"signed_rents": [{"tenant_id": t, "rent": r} for t, r in rents.items()], "assignment_pairs": [list(p) for p in pairs]}
    taxonomy = failure_taxonomy.classify(row, {"tenants": 3}, w)
    assert {k: len(v) for k, v in by.items()} == {k: v for k, v in taxonomy.items() if k in gap.TAXONOMY}
    assert gap._transfer(pairs, rents, w) == pytest.approx({"T1_tenant_payoff": (106 - 0) + (104 - 110) + (98 - 99),
                                                           "T2_landlord_payoff": (0 - 100) + (110 - 100) + (99 - 100)})


def test_the_sorting_counterfactual_equals_the_taxonomys_permutation_search() -> None:
    rng = random.Random(7)
    for seed in range(40):
        tenants, listings = rng.choice([(6, 5), (6, 3), (8, 6), (8, 4)])
        w = hz.make_bid_world(tenants, listings, seed=seed, common_weight=rng.random())
        leased = sorted(rng.sample(range(listings), rng.randint(1, listings)))
        brute = max(sum(w.values[t][l] - w.costs[l] for t, l in zip(choice, leased))
                    for choice in itertools.permutations(range(tenants), len(leased)))
        assert gap._best_sorting(leased, w) == pytest.approx(brute)


@pytest.fixture(scope="module")
def published() -> dict:
    return {key: json.loads((gap.OUT / "reports" / f"gap_decomposition_{key}.json").read_text())
            for key in (f"{c}_{m}" for c, _ in gap.CAMPAIGNS for m, _ in gap.MODELS)}


def _rows(bundle: str) -> dict[str, dict]:
    payload = json.loads((gap.EVIDENCE / bundle / "trajectories" / "attempted.json").read_text())
    return {r["receipt_sha256"]: r for r in payload["trajectories"] if r["status"] == "completed"}


@pytest.mark.parametrize("campaign,bundle", gap.CAMPAIGNS)
@pytest.mark.parametrize("model,tenant", gap.MODELS)
def test_published_parts_sum_to_the_published_welfare_gap(published, campaign, bundle, model, tenant) -> None:
    report = published[f"{campaign}_{model}"]
    rows = _rows(bundle)
    mine = {k: r for k, r in rows.items() if r["subject"] == tenant}
    left = [c for c in report["cell_parts"] if c["side"] == "left"]
    assert {c["receipt_sha256"] for c in left} == set(mine)
    by_world = collections.defaultdict(list)
    for cell in left:
        row = mine[cell["receipt_sha256"]]
        assert sum(cell["parts"].values()) == pytest.approx(row["social_welfare"] - row["oracle_upper_bound"], abs=1e-6)
        by_world[row["world_seed"]].append(row["social_welfare"] - row["oracle_upper_bound"])
    worlds = [sum(v) / len(v) for v in by_world.values()]
    assert report["realized"]["difference"] == pytest.approx(sum(worlds) / len(worlds), abs=1e-5)
    assert sum(c["difference"] for c in report["components"]) == pytest.approx(report["realized"]["difference"], abs=1e-5)
    assert report["paired_worlds"] == len(by_world) and report["reference_side"] == "right"
    assert all(set(c["parts"].values()) == {0.0} for c in report["cell_parts"] if c["side"] == "right")


@pytest.mark.parametrize("campaign,bundle", gap.CAMPAIGNS)
@pytest.mark.parametrize("model,tenant", gap.MODELS)
def test_contribution_rows_sum_to_their_cells_and_carry_no_step_because_none_is_published(
        published, campaign, bundle, model, tenant) -> None:
    report = published[f"{campaign}_{model}"]
    assert sorted(p.name for p in (gap.EVIDENCE / bundle / "trajectories").iterdir()) == ["attempted.json"]
    table = [json.loads(line) for line in (gap.OUT / report["contributions"]["table"]).read_text().splitlines()]
    assert len(table) == report["contributions"]["rows"]
    sums = collections.defaultdict(float)
    for row in table:
        assert (row["step_index"], row["round_index"], row["phase_id"], row["seat_id"]) == (None, None, None, None)
        assert row["listing_id"] is not None and row["note"]
        sums[(row["receipt_sha256"], row["component"])] += row["amount"]
    for cell in report["cell_parts"]:
        for key, value in cell["parts"].items():
            assert sums.get((cell["receipt_sha256"], key), 0.0) == pytest.approx(value, abs=1e-6)
    for item in report["instances"]:
        assert (item["step_index"], item["phase_id"], item["seat_id"]) == (None, None, None)


@pytest.mark.parametrize("campaign,bundle", gap.CAMPAIGNS)
@pytest.mark.parametrize("model,tenant", gap.MODELS)
def test_class_counts_are_the_taxonomys(published, campaign, bundle, model, tenant) -> None:
    report = published[f"{campaign}_{model}"]
    configs = gap._configs()
    totals: collections.Counter = collections.Counter()
    for row in _rows(bundle).values():
        if row["subject"] == tenant:
            config = configs[row["config_id"]]
            totals.update(failure_taxonomy.classify(row, config, gap.world(row["world_seed"], config)))
    counts = {c["key"]: c["left_count"] for c in report["classes"]}
    assert {k: counts[k] for k in gap.TAXONOMY} == {k: totals.get(k, 0) for k in gap.TAXONOMY}
    assert collections.Counter(i["class"] for i in report["instances"]) == +collections.Counter({k: counts[k] for k in gap.TAXONOMY})


def test_the_bundle_regenerates_byte_for_byte() -> None:
    assert gap.check()


def test_every_new_file_passes_the_prohibited_text_scan() -> None:
    files = [p for p in gap.OUT.rglob("*") if p.is_file()] + [Path(gap.__file__), Path(__file__)]
    assert len(files) >= 14
    for path in files:
        assert_public_payload(str(path.name), path.read_bytes())


def test_a_tied_oracle_is_detected() -> None:
    assert gap.oracle_is_unique(_world(SURPLUS))
    assert not gap.oracle_is_unique(_world([[5.0, 5.0], [5.0, 5.0]]))
