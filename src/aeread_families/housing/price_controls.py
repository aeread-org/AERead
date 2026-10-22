"""Scripted controls of the v14 price pack, and the declared rule for its $0-ceiling cells.

A derived analysis (Gate 3 of the QC standard): every world of the v14 pack (260 main, 40
holdout) under both landlord arms, played offline through the sealed market
(``price_reference.run_world``: the environment, the price landlord, the outside-demand seats)
by four scripted seat-0 tenants, beside the full-information ceiling and the three models'
published values:

* ``pass``, the no-op anchor: never inspects, never offers, nets $0;
* ``sign_anything``, the weak control: never inspects, offers at the ask on its best listing if
  sound, signs any hold its value-if-sound covers;
* ``inspect_then_sign``, the simple baseline: inspects when the expected gain covers the fee and
  signs only verified sound listings;
* ``inspect_lowball``, the reachable reference v14 subtracts (``price_reference``);
* ``ceiling``, full information (``price_reference.ceiling``), verified cell by cell in
  ``tests/test_housing_price_oracle_run.py``.

Each control cell is scored as a model cell is: realized net, the v14 primary measure (v1,
``price_endpoint``) and measure v2 (``price_reply_posterior``). The best-informed tenant
(``price_best_informed``) lives on branch ``codex/housing-best-informed`` and is not on this
branch, so it is left out. These are seat-0 controls in the v14 market; the
``sign_anything_total`` and ``reference_total`` in the v14 receipts are not, since the generic
lemons scorer plays every one of the six tenants by the policy without outside demand (HL-D-09).

**The $0-ceiling rule** (``ZERO_CEILING_RULE``). A cell whose ceiling is $0 has no listing worth
its landlord's lowest acceptable rent to seat 0, so the best play is to do nothing and every
share of the ceiling there is 0/0. Such a cell stays in every net measure, per-world mean and
contrast; it is excluded from the numerator and the denominator of every share-of-ceiling
ratio; and it is counted and listed wherever a share is reported. On the v14 pack this is ten
pooled-arm favourite-lemon cells (seven main, three holdout).

    python -m aeread_families.housing.price_controls --write
    python -m aeread_families.housing.price_controls --check

Nothing here is hashed into a Housing plan.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from aeread.shared_runner.run.publication import assert_public_payload, jsonl

from . import lemons, price_campaign, price_reference
from . import price_publication as pp
from . import price_reply_posterior as posterior

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "evidence/housing/housing_lemons_price_v14_controls"
V14 = ROOT / "evidence/housing/housing_lemons_price_confirmatory_v14"
SCHEMA_VERSION = "aeread.housing_price_controls/1"
ARMS = pp.ARMS
CONTROLS: dict[str, price_reference.Policy] = {
    "pass": lemons.pass_action,
    "sign_anything": lemons.sign_anything_action,
    "inspect_then_sign": lemons.inspect_then_sign_action,
    "inspect_lowball": price_reference.inspect_lowball_action,
}
MEASURES = ("net_realized", "primary_v1", "primary_v2")
SCOPES = {"main": {"population": "main"}, "holdout": {"population": "holdout"},
          "main_favourite_is_lemon": {"population": "main", "stratum": "favourite_is_lemon"},
          "main_favourite_is_sound": {"population": "main", "stratum": "favourite_is_sound"}}
SHORT = {"housing_lemons_price_confirmatory_v14_glm53_flash_nextbit": "GLM",
         "housing_lemons_price_confirmatory_v14_gpt6_luna": "Luna",
         "housing_lemons_price_confirmatory_v14_gemini38_flash": "Gemini"}
NOT_ON_THIS_BRANCH = {"best_informed": "price_best_informed is on branch codex/housing-best-informed, not here"}

ZERO_CEILING_RULE: dict[str, Any] = {
    "rule_id": "housing_price_zero_ceiling_v1",
    "applies_to": "a cell whose full-information ceiling (price_reference.ceiling) is $0: no listing is worth its "
                  "landlord's lowest acceptable rent to seat 0",
    "net_measures": "kept: the cell enters every per-world mean and every contrast",
    "share_of_ceiling": "excluded from the numerator and the denominator of every share-of-ceiling ratio",
    "reporting": "counted and listed, by population, stratum and arm, wherever a share of the ceiling is reported",
    "declared": "2026-10-13, after v14 ran; no declared v14 verdict uses a share of the ceiling",
}


def zero_ceiling(ceiling: float) -> bool:
    return abs(float(ceiling)) < 0.005


def share_of_ceiling(cells: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    """Σ field / Σ ceiling over the cells with a positive ceiling, under ``ZERO_CEILING_RULE``.

    Each cell needs ``ceiling`` and ``field``. A negative ceiling is not a degenerate denominator
    but an oracle error, and stops the computation.
    """
    if any(float(c["ceiling"]) < -0.005 for c in cells):
        raise ValueError("a negative ceiling is an oracle error, not a degenerate cell")
    kept = [c for c in cells if not zero_ceiling(c["ceiling"])]
    top = sum(float(c["ceiling"]) for c in kept)
    return {"share": round(sum(float(c[field]) for c in kept) / top, 4) if kept else None,
            "cells": len(kept), "zero_ceiling_cells_excluded": len(cells) - len(kept)}


def _population() -> tuple[dict[int, str], dict[int, str]]:
    return pp._population()


def control_cells() -> list[dict[str, Any]]:
    """One row per pack world and arm: every control under every measure, and the ceiling."""
    population, stratum = _population()
    rows = []
    for seed in price_campaign.PACK_WORLD_SEEDS:
        for arm in ARMS:
            row: dict[str, Any] = {"world_seed": seed, "arm": arm, "population": population[seed],
                                   "stratum": stratum[seed], "ceiling": price_reference.ceiling(seed, arm)}
            row["zero_ceiling"] = zero_ceiling(row["ceiling"])
            for name, policy in CONTROLS.items():
                market, trajectory = posterior.run_recorded(seed, arm, policy)
                scored = posterior.score_market(market, trajectory)
                if scored["net_realized"] != price_reference.seat_net(market):
                    raise ValueError(f"accounting differs for {name} in {seed} {arm}")
                leased = dict(market.pairs).get(price_reference.FOCAL_SEAT)
                row[name] = {**{m: scored[m] for m in MEASURES}, "signed": leased is not None,
                             "signed_blind": len(scored["blind_signings"]),
                             "inspections": len(market.inspected[price_reference.FOCAL_SEAT])}
            rows.append(row)
    return rows


def _per_world(cells: Sequence[Mapping[str, Any]], value: Callable[[Mapping[str, Any]], float],
               **selector: str) -> dict[int, float]:
    by_world: dict[int, list[float]] = {}
    for c in cells:
        if all(c[k] == v for k, v in selector.items()):
            by_world.setdefault(c["world_seed"], []).append(value(c))
    return {s: statistics.fmean(v) for s, v in by_world.items() if len(v) == len(ARMS)}


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 2) if values else None


def summarise(cells: Sequence[Mapping[str, Any]], model_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {"scopes": {}, "beatability_main_pack_primary_v1": {}}
    for scope, selector in SCOPES.items():
        in_scope = [c for c in cells if all(c[k] == v for k, v in selector.items())]
        entry: dict[str, Any] = {"worlds": len(_per_world(in_scope, lambda c: 0.0)),
                                 "ceiling": {"per_world": _mean(list(_per_world(in_scope, lambda c: c["ceiling"]).values())),
                                             **{arm: _mean([c["ceiling"] for c in in_scope if c["arm"] == arm]) for arm in ARMS}},
                                 "zero_ceiling_cells": [[c["world_seed"], c["arm"]] for c in in_scope if c["zero_ceiling"]],
                                 "controls": {}, "models": {}}
        for name in CONTROLS:
            flat = [{"ceiling": c["ceiling"], "arm": c["arm"], **c[name]} for c in in_scope]
            entry["controls"][name] = {
                **{m: pp._interval(list(_per_world([{**c, "v": c[name][m]} for c in in_scope], lambda c: c["v"]).values()))
                   for m in MEASURES},
                **{f"net_realized_{arm}": _mean([c[name]["net_realized"] for c in in_scope if c["arm"] == arm]) for arm in ARMS},
                "realized_share_of_ceiling": share_of_ceiling(flat, "net_realized"),
                **{f"realized_share_of_ceiling_{arm}": share_of_ceiling([c for c in flat if c["arm"] == arm], "net_realized")
                   for arm in ARMS},
                "cells_signed": sum(c[name]["signed"] for c in in_scope),
                "cells_signed_blind": sum(c[name]["signed_blind"] > 0 for c in in_scope),
            }
        for model, rows in model_rows.items():
            done = [r for r in rows if r["status"] == "completed" and all(r[k] == v for k, v in selector.items())]
            both = set(pp.per_world(done, pp.PRIMARY, population=None))
            paired = [r for r in done if r["world_seed"] in both]
            entry["models"][SHORT[model]] = {
                "primary_v1": pp._interval(list(pp.per_world(done, pp.PRIMARY, population=None).values())),
                "net_realized": pp._interval(list(pp.per_world(done, "net_realized", population=None).values())),
                "realized_share_of_ceiling": share_of_ceiling(paired, "net_realized"),
                **{f"realized_share_of_ceiling_{arm}": share_of_ceiling([r for r in paired if r["arm"] == arm], "net_realized")
                   for arm in ARMS},
                "realized_share_of_ceiling_as_published": (
                    round(sum(r["net_realized"] for r in paired) / sum(r["ceiling"] for r in paired), 4) if paired else None),
            }
        out["scopes"][scope] = entry
    main = [c for c in cells if c["population"] == "main"]
    for model, rows in model_rows.items():
        level = pp.per_world(rows, pp.PRIMARY)
        out["beatability_main_pack_primary_v1"][SHORT[model]] = {
            name: pp._interval([level[s] - v for s, v in _per_world([{**c, "v": c[name]["primary_v1"]} for c in main],
                                                                   lambda c: c["v"]).items() if s in level])
            for name in CONTROLS}
    return out


def analyse() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cells = control_cells()
    published = [json.loads(line) for line in (V14 / "tables/cells.jsonl").read_text().splitlines()]
    by_cell = {(r["world_seed"], r["arm"]): r for r in published}
    for c in cells:
        pub = by_cell[(c["world_seed"], c["arm"])]
        if (c["inspect_lowball"]["net_realized"], c["ceiling"]) != (pub["reference_net"], pub["ceiling"]):
            raise ValueError(f"reference or ceiling differs from the published bundle in {c['world_seed']} {c['arm']}")
    model_rows = {cid: [r for r in published if r["campaign_id"] == cid] for cid in pp.V14_PANEL}
    report = {
        "schema_version": SCHEMA_VERSION,
        "zero_ceiling_rule": ZERO_CEILING_RULE,
        "controls": {name: (CONTROLS[name].__module__ + "." + CONTROLS[name].__qualname__) for name in CONTROLS},
        "not_included": NOT_ON_THIS_BRANCH,
        "measures": {"net_realized": "seat 0's realized net", "primary_v1": "the v14 primary (price_endpoint)",
                     "primary_v2": posterior.MEASURE_ID},
        "inputs": {"v14_manifest_sha256": json.loads((V14 / "publication_manifest.json").read_text())["manifest_sha256"],
                   "pack_sha256": price_campaign.PACK["sha256"]},
        "reproduction": "the inspect_lowball net and the ceiling equal the bundle's reference_net and ceiling in all 600 "
                        "cells; each model's share of the ceiling as published equals the bundle's analysis.json",
        **summarise(cells, model_rows),
    }
    analysis = json.loads((V14 / "reports/analysis.json").read_text())
    for cid in pp.V14_PANEL:
        for scope in SCOPES:
            mine = report["scopes"][scope]["models"][SHORT[cid]]["realized_share_of_ceiling_as_published"]
            if mine != analysis["models"][cid]["by_scope"][scope]["realized_share_of_ceiling"]:
                raise ValueError(f"share of ceiling as published differs for {cid} {scope}")
    return report, cells


def _fmt(x: Mapping[str, Any] | None) -> str:
    return "n/a" if not x or x.get("mean") is None else f"{x['mean']:+.0f}"


def _pct(x: Mapping[str, Any]) -> str:
    return "n/a" if x["share"] is None else f"{100 * x['share']:.0f}%"


def _readme(report: Mapping[str, Any]) -> str:
    main, lemon, sound = (report["scopes"][k] for k in ("main", "main_favourite_is_lemon", "main_favourite_is_sound"))
    hold = report["scopes"]["holdout"]
    labels = {"pass": "`pass` (no-op)", "sign_anything": "`sign_anything` (weak)",
              "inspect_then_sign": "`inspect_then_sign` (baseline)", "inspect_lowball": "`inspect_lowball` (reference)"}
    lines = [
        f"# {OUT.name}",
        "",
        "Scripted seat-0 controls on every world of the v14 price pack, both landlord arms, played offline through the "
        "sealed market, beside the ceiling and the three models' published values. A derived analysis: "
        "`python -m aeread_families.housing.price_controls`; `--check` regenerates these bytes. The reference and the "
        "ceiling reproduce the v14 bundle's `reference_net` and `ceiling` in all 600 cells.",
        "",
        "Dollars per world (mean of the two arms), main pack (260 worlds). Primary v1 is the v14 primary measure; v2 is "
        "`price_reply_posterior`. Shares of the ceiling follow the $0-ceiling rule below.",
        "",
        "| Seat 0 | Realized | Primary v1 | Primary v2 | Share of ceiling | Favourite lemon, realized | Favourite sound, realized | Holdout, realized |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, label in labels.items():
        c = main["controls"][name]
        lines.append(f"| {label} | {_fmt(c['net_realized'])} | {_fmt(c['primary_v1'])} | {_fmt(c['primary_v2'])} | "
                     f"{_pct(c['realized_share_of_ceiling'])} | {_fmt(lemon['controls'][name]['net_realized'])} | "
                     f"{_fmt(sound['controls'][name]['net_realized'])} | {_fmt(hold['controls'][name]['net_realized'])} |")
    for model in ("GLM", "Luna", "Gemini"):
        m = main["models"][model]
        lines.append(f"| {model} (published) | {_fmt(m['net_realized'])} | {_fmt(m['primary_v1'])} | see "
                     f"`housing_lemons_price_v14_reply_conditioned` | {_pct(m['realized_share_of_ceiling'])} | "
                     f"{_fmt(lemon['models'][model]['net_realized'])} | {_fmt(sound['models'][model]['net_realized'])} | "
                     f"{_fmt(hold['models'][model]['net_realized'])} |")
    lines.append(f"| ceiling | {main['ceiling']['per_world']:+.0f} | | | 100% | {lemon['ceiling']['per_world']:+.0f} | "
                 f"{sound['ceiling']['per_world']:+.0f} | {hold['ceiling']['per_world']:+.0f} |")
    zero = [cell for scope in ("main", "holdout") for cell in report["scopes"][scope]["zero_ceiling_cells"]]
    lines += [
        "",
        "Model minus control on the v14 primary, paired by world, main pack, 95% Student-t: "
        + "; ".join(f"{model} minus `sign_anything` {_iv(report['beatability_main_pack_primary_v1'][model]['sign_anything'])}, "
                    f"minus `pass` {_iv(report['beatability_main_pack_primary_v1'][model]['pass'])}"
                    for model in ("GLM", "Luna", "Gemini")) + ".",
        "",
        f"**$0-ceiling rule** (`{report['zero_ceiling_rule']['rule_id']}`): a cell whose ceiling is $0 stays in every net "
        "measure, per-world mean and contrast, is excluded from the numerator and denominator of every share of the "
        f"ceiling, and is counted here. On this pack: {len(zero)} cells, "
        + ", ".join(f"{seed} {arm}" for seed, arm in zero) + ", all pooled-arm favourite-lemon "
        f"({len(main['zero_ceiling_cells'])} main, {len(hold['zero_ceiling_cells'])} holdout). The v14 bundle's "
        "`realized_share_of_ceiling` kept them in the ratio; `reports/controls.json` gives both per model.",
        "",
        "Not included: the best-informed tenant (`price_best_informed`), which is on branch "
        "`codex/housing-best-informed` and not on this branch. The `sign_anything_total` and `reference_total` in the "
        "v14 receipts are six-tenant figures from a market without outside demand, not these seat-0 controls (HL-D-09).",
        "",
        "Files: `tables/cells.jsonl` (one row per world and arm: every control under every measure, and the ceiling), "
        "`reports/controls.json` (every scope: intervals, shares under the rule, the models beside the controls).",
        "",
    ]
    return "\n".join(lines)


def _iv(x: Mapping[str, Any]) -> str:
    return f"{x['mean']:+.0f} [{x['lo']:+.0f}, {x['hi']:+.0f}]"


def _files() -> dict[str, bytes]:
    report, cells = analyse()
    files = {"tables/cells.jsonl": jsonl(cells),
             "reports/controls.json": (json.dumps(report, indent=1, sort_keys=True) + "\n").encode("utf-8"),
             "README.md": _readme(report).encode("utf-8")}
    for name, payload in files.items():
        assert_public_payload(name, payload)
    return files


def write() -> None:
    for name, payload in _files().items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def check() -> bool:
    ok = all((OUT / name).is_file() and (OUT / name).read_bytes() == payload for name, payload in _files().items())
    print("controls regenerate to the committed bytes" if ok else "controls differ from their generator")
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
    report, _ = analyse()
    print(json.dumps(report["scopes"]["main"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
