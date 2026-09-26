"""Why each Housing model falls short of the full-information oracle.

A derived analysis in the Tier 1 sense: it reads only the published bundles'
``trajectories/attempted.json`` and the worlds regenerated from the committed
sweep contract (``configs/housing_case_config_sweep_v2.json``) by the
deterministic generator, and regenerates byte-identical output (``--check``).
Regeneration is checked, not assumed: every completed cell's published
``social_welfare`` and ``oracle_upper_bound`` are recomputed from its world and
its published leases, and must match to the cent.

**Endpoint.** Welfare minus the oracle's welfare, per cell: the published
``social_welfare`` minus the published ``oracle_upper_bound``. Higher is better
and zero is the oracle. Welfare is value minus cost summed over the signed
leases; rent cancels in it.

**Decomposition.** The gap is indexed by listing. For every listing, what the
market realized there minus what the oracle realizes there, and each listing
falls in exactly one case, so the parts sum to the cell's gap:

- ``oracle_listing_left_empty``: a listing the oracle leases was never leased;
  minus the oracle pair's surplus (taxonomy class B1, per listing);
- ``missorted_tenant``: a listing the oracle leases went to a tenant other than
  the oracle's; that lease's surplus (floored at zero) minus the oracle pair's;
- ``extra_listing_leased``: a listing the oracle leaves empty was leased; that
  lease's surplus, floored at zero (B2). It is never negative: whatever that
  tenant was worth elsewhere is charged to the oracle listing it left;
- ``value_destroying_pair``: the negative surplus of any lease whose value is
  below the listing's cost, wherever it sits (A4).

A lease that matches the oracle pair contributes nothing. ``missorted_tenant``
is lease level; the taxonomy's B3 is a cell-level counterfactual (could the
leased listings have gone to better tenants) and is reported as a class.

**Classes** are diagnostic and not parts of the sum: A1 to A4 and B1 to B3 as
``failure_taxonomy.classify`` defines and counts them (A per lease, B per
cell), which is asserted here cell by cell, with dollar amounts attached; and
the rent transfer, tenant and landlord payoff, which cancels in welfare.

**A model** is the tenant seat, the campaign's subject. Its cells run against
both landlord models in equal measure, so the landlord seat in any one report
is played by both; the ``panel`` splits every campaign by tenant and landlord.

**Steps.** These bundles publish no step-level log (``trajectories/`` holds
only ``attempted.json``), so contribution rows and instances carry null step
fields and name the lease (tenant, listing, rent) instead.

**Unit.** The world seed, which the sweep declares the independent cluster;
each seed is run under all of the campaign's configurations. A world-clustered
percentile bootstrap with a declared seed; eight worlds, as in the two pilots,
is marginal for it and says so.

    python -m aeread_families.housing.oracle_gap --write
    python -m aeread_families.housing.oracle_gap --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import environment as hz
from . import failure_taxonomy

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence"
OUT = EVIDENCE / "housing" / "housing_oracle_gap"
SWEEP = ROOT / "configs" / "housing_case_config_sweep_v2.json"
CAMPAIGNS: tuple[tuple[str, str], ...] = (
    ("confirmatory_v2", "housing_confirmatory_parasail_v2"),
    ("pilot_v23", "housing_model_sensitivity_openrouter_parasail_v23"),
    ("pilot_v26", "housing_model_sensitivity_openrouter_parasail_v26"),
)
MODELS: tuple[tuple[str, str], ...] = (("glm53flash", "glm_53_flash"), ("deepseekv4flash", "deepseek_v4_flash"))
NAMES = {"glm_53_flash": "GLM 5.3 Flash", "deepseek_v4_flash": "DeepSeek V4 Flash"}
BOOTSTRAP_SEED = 20260925
BOOTSTRAP_DRAWS = 10000
MARGINAL_WORLDS = 10  # below this a world bootstrap is reported but flagged marginal
TOLERANCE = 1e-6

COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("oracle_listing_left_empty", "oracle listing left empty", "outcome",
     "A listing the oracle leases was never leased: minus the surplus of the oracle's pair on it."),
    ("missorted_tenant", "oracle listing, wrong tenant", "decision",
     "A listing the oracle leases went to a different tenant: that lease's surplus (floored at zero) minus the oracle pair's. "
     "Usually negative; positive when the tenant is worth more on this listing than the oracle's own, which the oracle then "
     "loses on the listing that tenant left."),
    ("extra_listing_leased", "listing the oracle leaves empty, leased", "decision",
     "A listing the oracle leaves empty was leased: that lease's surplus, floored at zero. Never negative here; the tenant it "
     "took from the oracle's assignment is charged on the oracle listing it left."),
    ("value_destroying_pair", "value-destroying lease", "decision",
     "A lease whose tenant values the listing below the landlord's cost: its negative surplus, wherever it sits."),
)
PART_KEYS = tuple(key for key, *_ in COMPONENTS)

TAXONOMY = (
    "A1_tenant_signed_above_own_value", "A2_landlord_signed_at_zero_rent", "A3_landlord_signed_below_cost",
    "A4_pair_destroys_value", "B1_oracle_listing_left_empty", "B2_leased_a_listing_the_oracle_leaves_empty",
    "B3_right_listings_wrong_tenants",
)
CLASSES: dict[str, dict[str, str]] = {
    "A1_tenant_signed_above_own_value": {
        "group": "A", "label": "a tenant signed a lease worth less to it than the rent (tenant seat; a transfer)",
        "amount": "rent minus the tenant's value, per lease"},
    "A2_landlord_signed_at_zero_rent": {
        "group": "A", "label": "a landlord signed at exactly zero rent (landlord seat; a transfer)",
        "amount": "the landlord's cost, borne in full, per lease"},
    "A3_landlord_signed_below_cost": {
        "group": "A", "label": "a landlord signed at a positive rent below its cost (landlord seat; a transfer)",
        "amount": "cost minus rent, per lease"},
    "A4_pair_destroys_value": {
        "group": "A", "label": "a lease whose value is below the listing's cost (both seats consented)",
        "amount": "cost minus value, per lease; equal to minus the value-destroying part"},
    "B1_oracle_listing_left_empty": {
        "group": "B", "label": "cells where a listing the oracle leases stayed empty",
        "amount": "oracle surplus of the empty listings, per cell; equal to minus that part"},
    "B2_leased_a_listing_the_oracle_leaves_empty": {
        "group": "B", "label": "cells where a listing the oracle leaves empty was leased",
        "amount": "surplus those leases realized, per cell (either sign)"},
    "B3_right_listings_wrong_tenants": {
        "group": "B", "label": "cells whose leased listings could have gone to higher-value tenants (the taxonomy's counterfactual)",
        "amount": "best assignment of tenants to the leased listings minus the realized welfare, per cell"},
    "T1_tenant_payoff": {
        "group": "T", "label": "tenants' payoff, value minus rent (the transfer; cancels in welfare)",
        "amount": "value minus rent summed over the leases; the oracle sets no rent"},
    "T2_landlord_payoff": {
        "group": "T", "label": "landlords' payoff, rent minus cost (the transfer; cancels in welfare)",
        "amount": "rent minus cost summed over the leases; the oracle sets no rent"},
}
TRANSFER = ("T1_tenant_payoff", "T2_landlord_payoff")


def _money(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _configs() -> dict[str, dict[str, Any]]:
    sweep = json.loads(SWEEP.read_bytes())
    out: dict[str, dict[str, Any]] = {}
    for block, field in (("confirmatory_holdout", "parameter_combinations"), ("development", "candidate_configs")):
        for config in sweep.get(block, {}).get(field, []) or []:
            out[str(config["config_id"])] = config
    return out


_WORLDS: dict[tuple[int, str], Any] = {}


def world(seed: int, config: Mapping[str, Any]) -> Any:
    key = (int(seed), str(config["config_id"]))
    if key not in _WORLDS:
        _WORLDS[key] = hz.make_bid_world(config["tenants"], config["listings"], seed=key[0],
                                         common_weight=config["common_weight"])
    return _WORLDS[key]


def lease_parts(pairs: Sequence[tuple[int, int]], rents: Mapping[int, float], w: Any,
                oracle_pairs: Sequence[tuple[int, int]]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """The cell's gap below the oracle, split by listing, and one row per listing per part."""
    s = lambda t, l: float(w.values[t][l]) - float(w.costs[l])  # noqa: E731
    oracle = {int(l): int(t) for t, l in oracle_pairs}
    realized = {int(l): int(t) for t, l in pairs}
    if len(realized) != len(pairs) or len({t for t, _ in pairs}) != len(pairs):
        raise ValueError("a listing or a tenant is leased twice")
    parts = {key: 0.0 for key in PART_KEYS}
    rows: list[dict[str, Any]] = []

    def add(component: str, amount: float, listing: int, tenant: int | None, note: str) -> None:
        parts[component] += amount
        rows.append({"component": component, "amount": amount, "listing_id": listing, "tenant_id": tenant,
                     "rent": None if tenant is None else float(rents[tenant]), "oracle_tenant_id": oracle.get(listing),
                     "note": note})

    for l in sorted(set(oracle) | set(realized)):
        ot, rt = oracle.get(l), realized.get(l)
        if rt is None:
            add("oracle_listing_left_empty", -s(ot, l), l, None,
                f"listing {l} was never leased; the oracle leases it to tenant {ot} for a surplus of {s(ot, l):.2f}")
            continue
        if rt == ot:
            continue
        here, rent = s(rt, l), float(rents[rt])
        if ot is not None:
            add("missorted_tenant", max(here, 0.0) - s(ot, l), l, rt,
                f"listing {l} went to tenant {rt} at rent {_money(rent)} (surplus {here:.2f}) where the oracle places "
                f"tenant {ot} (surplus {s(ot, l):.2f})")
        elif here >= 0:
            add("extra_listing_leased", here, l, rt,
                f"listing {l}, which the oracle leaves empty, went to tenant {rt} at rent {_money(rent)} (surplus {here:.2f})")
        if here < 0:
            add("value_destroying_pair", here, l, rt,
                f"tenant {rt} signed listing {l} at rent {_money(rent)}, valuing it at {float(w.values[rt][l]):.2f} "
                f"against a cost of {float(w.costs[l]):.2f}: the lease destroys {-here:.2f}")
    return parts, rows


def _best_sorting(leased: Sequence[int], w: Any) -> float:
    """The best welfare from assigning distinct tenants to exactly these listings (every one filled)."""
    from scipy.optimize import linear_sum_assignment

    if not leased:
        return 0.0
    matrix = [[float(w.values[t][l]) - float(w.costs[l]) for t in range(w.num_tenants)] for l in leased]
    rows, cols = linear_sum_assignment(matrix, maximize=True)
    return sum(matrix[r][c] for r, c in zip(rows, cols))


def cell_classes(pairs: Sequence[tuple[int, int]], rents: Mapping[int, float], w: Any,
                 oracle_pairs: Sequence[tuple[int, int]], landlord: str, tenant_model: str) -> list[dict[str, Any]]:
    """Every class instance in the cell with its amount: A per lease, B per cell, T once per cell."""
    found: list[dict[str, Any]] = []
    s = lambda t, l: float(w.values[t][l]) - float(w.costs[l])  # noqa: E731
    lease = lambda t, l: {"tenant_id": t, "listing_id": l, "rent": float(rents[t])}  # noqa: E731
    for t, l in sorted((int(a), int(b)) for a, b in pairs):
        value, cost, rent = float(w.values[t][l]), float(w.costs[l]), float(rents[t])
        if value - rent < 0:
            found.append({"class": "A1_tenant_signed_above_own_value", "amount": rent - value, **lease(t, l),
                          "note": f"tenant {t} ({NAMES.get(tenant_model, tenant_model)}) signed listing {l} at rent {_money(rent)}, above its own value {value:.2f}"})
        if rent == 0.0:
            found.append({"class": "A2_landlord_signed_at_zero_rent", "amount": cost, **lease(t, l),
                          "note": f"the landlord of listing {l} ({NAMES.get(landlord, landlord)}) signed tenant {t} at zero rent, bearing its whole cost of {cost:.2f}"})
        elif rent - cost < 0:
            found.append({"class": "A3_landlord_signed_below_cost", "amount": cost - rent, **lease(t, l),
                          "note": f"the landlord of listing {l} ({NAMES.get(landlord, landlord)}) signed tenant {t} at rent {_money(rent)}, below its cost {cost:.2f}"})
        if value - cost < 0:
            found.append({"class": "A4_pair_destroys_value", "amount": cost - value, **lease(t, l),
                          "note": f"tenant {t} values listing {l} at {value:.2f}, below its cost {cost:.2f}, and both seats signed at rent {_money(rent)}"})
    oracle = {int(l): int(t) for t, l in oracle_pairs}
    leased = sorted(int(l) for _, l in pairs)
    empty = sorted(set(oracle) - set(leased))
    if empty:
        amount = sum(s(oracle[l], l) for l in empty)
        found.append({"class": "B1_oracle_listing_left_empty", "amount": amount, "tenant_id": None, "listing_id": None, "rent": None,
                      "note": f"listing{'s' if len(empty) > 1 else ''} {', '.join(map(str, empty))}, which the oracle leases, stayed empty: "
                              f"{amount:.2f} of oracle surplus forgone"})
    extra = sorted(set(leased) - set(oracle))
    if extra:
        by_listing = {int(l): int(t) for t, l in pairs}
        amount = sum(s(by_listing[l], l) for l in extra)
        found.append({"class": "B2_leased_a_listing_the_oracle_leaves_empty", "amount": amount, "tenant_id": None, "listing_id": None,
                      "rent": None,
                      "note": f"listing{'s' if len(extra) > 1 else ''} {', '.join(map(str, extra))}, which the oracle leaves empty, "
                              f"{'were' if len(extra) > 1 else 'was'} leased, realizing {amount:.2f} of surplus"})
    if leased and len(leased) <= failure_taxonomy.MAXIMUM_SORTING_WIDTH:
        realized = sum(s(int(t), int(l)) for t, l in pairs)
        shortfall = _best_sorting(leased, w) - realized
        if shortfall > 1e-9:
            found.append({"class": "B3_right_listings_wrong_tenants", "amount": shortfall, "tenant_id": None, "listing_id": None,
                          "rent": None,
                          "note": f"the {len(leased)} leased listings could have gone to other tenants for {shortfall:.2f} more welfare"})
    return found


def oracle_is_unique(w: Any) -> bool:
    """Whether the oracle's assignment is the only optimum: forbidding any of its pairs must cost welfare.

    The parts are indexed by the oracle's listings and tenants, so a tie between optimal assignments would make
    them depend on which optimum the solver returned."""
    oracle = hz.assignment_oracle(w.surplus)
    for t, l in oracle.pairs:
        forbidden = [list(row) for row in w.surplus]
        forbidden[t][l] = -1e12
        if hz.assignment_oracle(forbidden).total >= oracle.total - 1e-9:
            return False
    return True


def _transfer(pairs: Sequence[tuple[int, int]], rents: Mapping[int, float], w: Any) -> dict[str, float]:
    return {"T1_tenant_payoff": sum(float(w.values[t][l]) - float(rents[t]) for t, l in pairs),
            "T2_landlord_payoff": sum(float(rents[t]) - float(w.costs[l]) for t, l in pairs)}


def _rows(bundle: str) -> list[dict[str, Any]]:
    return json.loads((EVIDENCE / bundle / "trajectories" / "attempted.json").read_bytes())["trajectories"]


def _canonical_models(bundle: str) -> dict[str, str]:
    report = json.loads((EVIDENCE / bundle / "reports" / "qualification.json").read_bytes())
    return {route["model_id"]: route["canonical_model"] for route in report["backend"]["routes"]}


def analyse_campaign(bundle: str) -> dict[str, Any]:
    """Every completed cell of a campaign, decomposed and classified, with the regeneration checked."""
    configs = _configs()
    cells: list[dict[str, Any]] = []
    missing: collections.Counter = collections.Counter()
    bounds: dict[tuple[int, str], float] = {}
    for row in _rows(bundle):
        if row.get("status") != "completed":
            missing[(row["subject"], row["opponent"])] += 1
            continue
        config = configs[str(row["config_id"])]
        w = world(int(row["world_seed"]), config)
        oracle = hz.assignment_oracle(w.surplus)
        pairs = [(int(t), int(l)) for t, l in row["assignment_pairs"]]
        rents = {int(item["tenant_id"]): float(item["rent"]) for item in row["signed_rents"]}
        if set(rents) != {t for t, _ in pairs}:
            raise ValueError(f"{row['receipt_sha256']}: signed rents do not match the leases")
        welfare, bound = float(row["social_welfare"]), float(row["oracle_upper_bound"])
        if round(sum(float(w.values[t][l]) - float(w.costs[l]) for t, l in pairs), 2) != welfare:
            raise ValueError(f"{row['receipt_sha256']}: regenerated welfare does not match the published social_welfare")
        if oracle.total != bound:
            raise ValueError(f"{row['receipt_sha256']}: regenerated oracle does not match the published oracle_upper_bound")
        case = (int(row["world_seed"]), str(row["config_id"]))
        if case not in bounds and not oracle_is_unique(w):
            raise ValueError(f"{case}: the oracle assignment is not unique, so the parts would depend on the solver")
        if bounds.setdefault(case, bound) != bound:
            raise ValueError(f"{case}: two rows publish different oracle bounds")
        parts, contributions = lease_parts(pairs, rents, w, oracle.pairs)
        endpoint = round(welfare - bound, 2)
        instances = cell_classes(pairs, rents, w, oracle.pairs, row["opponent"], row["subject"])
        counted = collections.Counter(i["class"] for i in instances)
        taxonomy = failure_taxonomy.classify(row, config, w)
        if any(counted[key] != taxonomy.get(key, 0) for key in TAXONOMY):
            raise ValueError(f"{row['receipt_sha256']}: class counts differ from failure_taxonomy.classify")
        amounts = collections.Counter()
        for item in instances:
            amounts[item["class"]] += item["amount"]
        amounts.update(_transfer(pairs, rents, w))
        counted.update({key: len(pairs) for key in TRANSFER})
        cells.append({
            "receipt_sha256": row["receipt_sha256"], "world_seed": int(row["world_seed"]),
            "replicate_index": int(row["replicate_index"]), "config_id": str(row["config_id"]),
            "tenant": row["subject"], "landlord": row["opponent"], "leases": len(pairs),
            "welfare": welfare, "oracle": bound, "score": float(row["within_case_score"]), "endpoint": endpoint,
            "parts": parts, "residual": sum(parts.values()) - endpoint, "contributions": contributions,
            "instances": instances, "counts": counted, "amounts": amounts,
        })
    return {"bundle": bundle, "cells": cells, "missing": missing, "cases": sorted(bounds)}


def _boot(values: Sequence[float], rng: random.Random) -> list[float] | None:
    if len(values) < 2:
        return None
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_DRAWS))
    return [round(means[int(0.025 * BOOTSTRAP_DRAWS)], 6), round(means[min(BOOTSTRAP_DRAWS - 1, int(0.975 * BOOTSTRAP_DRAWS))], 6)]


def _world_means(cells: Sequence[Mapping[str, Any]], pick) -> dict[int, float]:
    by: dict[int, list[float]] = collections.defaultdict(list)
    for cell in cells:
        by[cell["world_seed"]].append(float(pick(cell)))
    return {w: sum(v) / len(v) for w, v in sorted(by.items())}


def _mean(cells: Sequence[Mapping[str, Any]], pick) -> float:
    means = _world_means(cells, pick)
    return sum(means.values()) / len(means)


def _panel(campaigns: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for label, bundle in CAMPAIGNS:
        cells = campaigns[bundle]["cells"]
        for _, tenant in MODELS:
            for landlord in (None,) + tuple(m for _, m in MODELS):
                chosen = [c for c in cells if c["tenant"] == tenant and (landlord is None or c["landlord"] == landlord)]
                rows.append({"campaign_id": bundle, "campaign_label": label, "tenant_model": tenant,
                             "landlord_model": landlord or "both", "cells": len(chosen),
                             "worlds": len({c["world_seed"] for c in chosen}),
                             "realized": round(_mean(chosen, lambda c: c["endpoint"]), 6),
                             "components": {k: round(_mean(chosen, lambda c, k=k: c["parts"][k]), 6) for k in PART_KEYS},
                             "welfare": round(_mean(chosen, lambda c: c["welfare"]), 6),
                             "oracle": round(_mean(chosen, lambda c: c["oracle"]), 6),
                             "within_case_score": round(_mean(chosen, lambda c: c["score"]), 6)})
    return rows


def _report(label: str, model_label: str, bundle: str, tenant: str, campaign: Mapping[str, Any],
            panel: list[dict[str, Any]], names: Mapping[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    left = [c for c in campaign["cells"] if c["tenant"] == tenant]
    worlds = sorted({c["world_seed"] for c in left})
    cases = sorted({(c["world_seed"], c["config_id"]) for c in left})
    rng = random.Random(BOOTSTRAP_SEED)

    def block(pick) -> dict[str, Any]:
        means = _world_means(left, pick)
        values = [means[w] for w in worlds]
        mean = sum(values) / len(values)
        return {"left": round(mean, 6), "right": 0.0, "difference": round(mean, 6), "difference_ci": _boot(values, rng)}

    realized = block(lambda c: c["endpoint"])
    components = [{"key": k, "label": lab, "group": grp, "description": desc, **block(lambda c, k=k: c["parts"][k])}
                  for k, lab, grp, desc in COMPONENTS]
    classes = []
    for key, meta in CLASSES.items():
        count = sum(c["counts"][key] for c in left)
        if key in TRANSFER:
            amount = round(_mean(left, lambda c, key=key: c["amounts"][key]), 6)
            classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                            "left_count": count, "right_count": None, "left_amount_per_market": amount,
                            "right_amount_per_market": None, "amount_difference": None, "amount_difference_ci": None})
            continue
        b = block(lambda c, key=key: c["amounts"][key])
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                        "left_count": count, "right_count": 0, "left_amount_per_market": b["left"],
                        "right_amount_per_market": 0.0, "amount_difference": b["difference"], "amount_difference_ci": b["difference_ci"]})
    null_step = {"step_index": None, "round_index": None, "phase_id": None, "seat_id": None}
    table, instances, cell_parts = [], [], []
    unexplained: list[float] = []
    for c in left:
        where = {"side": "left", "campaign_id": bundle, "receipt_sha256": c["receipt_sha256"], "world_seed": c["world_seed"],
                 "replicate_index": c["replicate_index"], **null_step, "config_id": c["config_id"], "landlord": c["landlord"]}
        sums: collections.Counter = collections.Counter()
        for row in c["contributions"]:
            sums[row["component"]] += row["amount"]
            table.append({**where, **row, "amount": round(row["amount"], 6)})
        unexplained.extend(c["parts"][k] - sums[k] for k in PART_KEYS)
        for item in c["instances"]:
            instances.append({**where, **item, "amount": round(item["amount"], 6)})
        cell_parts.append({"side": "left", "campaign_id": bundle, "receipt_sha256": c["receipt_sha256"], "world_seed": c["world_seed"],
                           "replicate_index": c["replicate_index"], "config_id": c["config_id"], "landlord": c["landlord"],
                           "parts": {k: round(v, 6) for k, v in c["parts"].items()}})
    for seed, config_id in cases:
        cell_parts.append({"side": "right", "campaign_id": bundle, "receipt_sha256": f"oracle:{config_id}:{seed}", "world_seed": seed,
                           "replicate_index": None, "config_id": config_id, "landlord": None, "parts": {k: 0.0 for k in PART_KEYS}})
    residual = max(abs(c["residual"]) for c in left)
    contribution_residual = max(abs(r) for r in unexplained)
    if residual > TOLERANCE or contribution_residual > TOLERANCE:
        raise ValueError(f"{bundle}/{tenant}: the parts do not add up (cell {residual}, rows {contribution_residual})")
    missing = sum(v for (s, _), v in campaign["missing"].items() if s == tenant)
    marginal = len(worlds) < MARGINAL_WORLDS
    order = {k: i for i, k in enumerate(PART_KEYS)}
    report = {
        "schema_version": "aeread.gap_decomposition/0.1",
        "family": "housing", "world_kind": "bid_market",
        "title": "Why it falls short of the oracle",
        "left": bundle, "right": bundle, "reference_side": "right",
        "left_model": names[tenant], "right_model": "full-information oracle (max-weight assignment of the regenerated world)",
        "right_label": "oracle",
        "endpoint": "welfare minus the oracle's welfare: published social_welfare minus published oracle_upper_bound, per cell (zero at the oracle)",
        "unit": "dollars of welfare per market, averaged over the model's completed tenant-seat cells in each world, then over worlds",
        "unit_label": "world", "per_label": "market", "amount_label": "$/market",
        "class_heading": "failure class (Housing taxonomy A, B) and rent transfer (T, cancels in welfare)",
        "direction": "higher",
        "claim_status": "descriptive_against_oracle" + ("_marginal_worlds" if marginal else ""),
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "model_seat": "tenant (the campaign's subject); the landlord seat is played by both models in equal measure, see panel",
        "paired_worlds": len(worlds), "cells": {"left": len(left), "right": len(cases)},
        "missing_cells": {"left": missing, "statement": "typed operational missingness, excluded from every mean; never rerun"},
        "bootstrap": {"seed": BOOTSTRAP_SEED, "draws": BOOTSTRAP_DRAWS, "interval": "percentile_95", "unit": "world_seed",
                      "stream": "a fresh random.Random(seed) per report: realized, then components in declared order, then class amounts in declared order (A1 to B3; the transfer classes have no oracle counterpart and draw nothing)",
                      **({"caveat": f"{len(worlds)} worlds is marginal for a percentile bootstrap, which understates the spread with this few clusters"} if marginal else {})},
        "realized": realized,
        "components": components,
        "accounting_check": {"max_abs_residual_per_cell": residual,
                             "statement": "each cell's parts sum to its published social_welfare minus its published oracle_upper_bound",
                             "max_abs_contribution_residual": contribution_residual,
                             "contribution_statement": "per cell, the contribution rows of each part sum to that cell's part"},
        "regeneration_check": {"cells": len(left), "statement": "every cell's social_welfare and oracle_upper_bound recomputed from the regenerated world and its published leases match to the cent; the oracle assignment is unique in every world"},
        "welfare_view": {"left": {"welfare": round(_mean(left, lambda c: c["welfare"]), 6), "oracle": round(_mean(left, lambda c: c["oracle"]), 6),
                                  "within_case_score": round(_mean(left, lambda c: c["score"]), 6),
                                  "leases": round(_mean(left, lambda c: c["leases"]), 6)},
                         "right": {"welfare": round(_mean(left, lambda c: c["oracle"]), 6), "within_case_score": 1.0},
                         "statement": "per market, averaged per world then over worlds; the score is welfare over the oracle bound as published"},
        "classes": classes,
        "instances": sorted(instances, key=lambda i: (i["class"], i["world_seed"], i["config_id"], i["landlord"], i["replicate_index"],
                                                      -1 if i["listing_id"] is None else i["listing_id"])),
        "panel": panel,
        "cell_parts": sorted(cell_parts, key=lambda c: (c["side"], c["world_seed"], c["config_id"], c["landlord"] or "", c["replicate_index"] or 0)),
        "contributions": {"table": f"tables/contributions_{label}_{model_label}.jsonl", "rows": len(table),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "step_index", "round_index",
                                     "phase_id", "seat_id", "config_id", "landlord", "listing_id", "tenant_id", "rent", "oracle_tenant_id",
                                     "component", "amount", "note"],
                          "steps": "none published: these bundles carry no step-level log, so step_index, round_index, phase_id and seat_id are null and each row names its lease"},
        "oracle_cells": "the oracle has no receipts: its cells are the campaign's world-configuration cases, identified as oracle:<config_id>:<world_seed>, with the bound every row of the case publishes",
        "source_manifest_sha256": {bundle: hashlib.sha256((EVIDENCE / bundle / "trajectories" / "attempted.json").read_bytes()).hexdigest()},
        "source_artifact": "trajectories/attempted.json (these bundles publish no publication_manifest.json)",
        "world_source_sha256": {"configs/housing_case_config_sweep_v2.json": hashlib.sha256(SWEEP.read_bytes()).hexdigest()},
    }
    rows = sorted(table, key=lambda r: (r["world_seed"], r["config_id"], r["landlord"], r["replicate_index"], r["listing_id"],
                                        order[r["component"]]))
    return report, rows


def analyse() -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    campaigns = {bundle: analyse_campaign(bundle) for _, bundle in CAMPAIGNS}
    panel = _panel(campaigns)
    out = {}
    for label, bundle in CAMPAIGNS:
        names = _canonical_models(bundle)
        for model_label, tenant in MODELS:
            out[f"{label}_{model_label}"] = _report(label, model_label, bundle, tenant, campaigns[bundle], panel, names)
    return out


def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _readme(reports: Mapping[str, tuple[dict[str, Any], list]]) -> str:
    items = [(key.rsplit("_", 1)[0], _tenant(key), report) for key, (report, _) in reports.items()]
    first = items[0][2]
    ci = lambda b: "" if b["difference_ci"] is None else f" ({b['difference_ci'][0]:.1f} to {b['difference_ci'][1]:.1f})"  # noqa: E731
    part = lambda r, k: next(c for c in r["components"] if c["key"] == k)  # noqa: E731
    main = ["| campaign, tenant model | worlds / cells | welfare minus oracle | " + " | ".join(lab for _, lab, *_ in COMPONENTS) + " |",
            "|---" * (3 + len(COMPONENTS)) + "|"]
    for label, tenant, r in items:
        main.append(f"| {label}, {NAMES[tenant]} | {r['paired_worlds']} / {r['cells']['left']} | "
                    f"**{r['realized']['difference']:.1f}**{ci(r['realized'])} | "
                    + " | ".join(f"{part(r, k)['difference']:.1f}{ci(part(r, k))}" for k in PART_KEYS) + " |")
    by_landlord = ["| campaign | tenant | landlord | cells | welfare minus oracle | " + " | ".join(lab for _, lab, *_ in COMPONENTS) + " |",
                   "|---" * (5 + len(COMPONENTS)) + "|"]
    for p in first["panel"]:
        if p["landlord_model"] != "both":
            by_landlord.append(f"| {p['campaign_label']} | {NAMES[p['tenant_model']]} | {NAMES[p['landlord_model']]} | {p['cells']} | "
                               f"{p['realized']:.1f} | " + " | ".join(f"{p['components'][k]:.1f}" for k in PART_KEYS) + " |")
    classes = ["| class | " + " | ".join(f"{label}, {NAMES[tenant].split(' ')[0]}" for label, tenant, _ in items) + " |",
               "|---" * (1 + len(items)) + "|"]
    for i, meta in enumerate(first["classes"]):
        classes.append(f"| `{meta['key']}` | " + " | ".join(
            f"{r['classes'][i]['left_count']} ({r['classes'][i]['left_amount_per_market']:.1f})" for _, _, r in items) + " |")
    share = lambda r, k: 100.0 * part(r, k)["difference"] / r["realized"]["difference"]  # noqa: E731
    lo, hi = min(share(r, "missorted_tenant") for *_, r in items), max(share(r, "missorted_tenant") for *_, r in items)
    largest = sum(all(abs(part(r, "missorted_tenant")["difference"]) >= abs(part(r, k)["difference"]) for k in PART_KEYS)
                  for *_, r in items)
    confirmatory = {tenant: r for label, tenant, r in items if label == CAMPAIGNS[0][0]}
    empty = {t: part(r, "oracle_listing_left_empty")["difference"] for t, r in confirmatory.items()}
    residual = max(r["accounting_check"]["max_abs_residual_per_cell"] for *_, r in items)
    rows = sum(r["contributions"]["rows"] for *_, r in items)
    labels = "; ".join(f"`{label}` is `{bundle}`" for label, bundle in CAMPAIGNS)
    return "\n".join([
        f"# {OUT.name}",
        "",
        "Why each Housing model falls short of the full-information oracle, in the confirmatory holdout (30 worlds) and the "
        "two eight-world variance pilots on the development panel, which ran the same worlds and configurations with action "
        f"attempt limits of 10 and 30 ({labels}). Derived from each bundle's `trajectories/attempted.json` and the worlds "
        "regenerated from the committed sweep contract by `python -m aeread_families.housing.oracle_gap`; `--check` "
        "regenerates these bytes. Every cell's published welfare and oracle bound are recomputed from its world and leases "
        "and match to the cent. Descriptive: no winner, no ranking.",
        "",
        "The endpoint is welfare minus the oracle's welfare per market (published `social_welfare` minus "
        "`oracle_upper_bound`; zero is the oracle). Rent cancels in welfare. The gap is indexed by listing, so each listing "
        f"lands in one part and the parts sum to each cell's gap exactly (largest residual {residual:.2g}). A model is the "
        "tenant seat, the campaign's subject, pooled over both landlord models. The unit is the world seed, with a "
        f"world-clustered percentile bootstrap (seed {BOOTSTRAP_SEED}, {BOOTSTRAP_DRAWS} draws); eight worlds is marginal "
        "for it, so the pilots' intervals understate their spread.",
        "",
        f"In {'every report' if largest == len(items) else f'{largest} of {len(items)} reports'} the "
        f"largest part is the wrong tenant on a listing the oracle leases, {lo:.0f} to {hi:.0f} percent of the gap. Most "
        "of the rest is oracle listings left empty, which in the confirmatory run cost "
        f"{-empty['deepseek_v4_flash']:.1f} per market with DeepSeek as tenant against {-empty['glm_53_flash']:.1f} with GLM. "
        "Per market, dollars, 95% world-bootstrap interval in brackets:",
        "",
        *main,
        "",
        "An oracle listing left empty costs the oracle pair's whole surplus. A wrong tenant on an oracle listing costs the "
        "difference between the two pairs. An extra listing is credited with what its lease realized; the tenant it took is "
        "charged on the oracle listing that tenant left. A value-destroying lease is its negative surplus. The estimand "
        "review's split of this gap (20 percent empty, 68 wrong tenant, 12 value-destroying) does not reproduce under these "
        "definitions or the variants tried (incident J-7).",
        "",
        "By landlord (per market, no interval):",
        "",
        *by_landlord,
        "",
        "Classes, count (dollars per market). A1 to B3 are `failure_taxonomy.classify`'s classes and counts, checked cell by "
        "cell: A per lease, B per cell. A2 and A3 belong to the landlord seat, which both models play in every report. T1 and "
        "T2 split welfare into the tenants' and landlords' payoffs; the transfer between them cancels, and the oracle sets no "
        "rent. Diagnostic, overlapping, not parts of the sum:",
        "",
        *classes,
        "",
        "No step-level log is published for these campaigns (`trajectories/` holds only `attempted.json`). Contribution rows "
        "and instances therefore carry null `step_index`, `round_index`, `phase_id` and `seat_id`, and name the lease "
        "(tenant, listing, rent) instead. Each report is `reports/gap_decomposition_<campaign>_<model>.json`; "
        f"`tables/contributions_<campaign>_<model>.jsonl` ({rows} rows in all) gives one row per listing per part, and per "
        "cell a part's rows sum to that cell's part. The oracle has no receipts: its cells are the world-configuration cases, "
        "identified as `oracle:<config_id>:<world_seed>`. These bundles publish no `publication_manifest.json`, so "
        "`source_manifest_sha256` is the digest of the `attempted.json` read.",
        "",
    ])


def _tenant(key: str) -> str:
    return next(tenant for label, tenant in MODELS if key.endswith(f"_{label}"))


def write() -> None:
    reports = analyse()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for key, (report, table) in reports.items():
        (OUT / "reports" / f"gap_decomposition_{key}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (OUT / "tables" / f"contributions_{key}.jsonl").write_text(_table_bytes(table))
    (OUT / "README.md").write_text(_readme(reports))
    print(f"housing oracle gap written to {OUT.relative_to(ROOT)}")


def check() -> bool:
    reports = analyse()
    ok = (OUT / "README.md").exists() and (OUT / "README.md").read_text() == _readme(reports)
    for key, (report, table) in reports.items():
        rp, tp = OUT / "reports" / f"gap_decomposition_{key}.json", OUT / "tables" / f"contributions_{key}.jsonl"
        ok = ok and rp.exists() and rp.read_text() == json.dumps(report, indent=2, sort_keys=True) + "\n"
        ok = ok and tp.exists() and tp.read_text() == _table_bytes(table)
    print("housing oracle gap regenerates to the committed bytes" if ok else "housing oracle gap differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    for key, (report, _) in analyse().items():
        print(key, report["realized"]["difference"], {c["key"]: c["difference"] for c in report["components"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
