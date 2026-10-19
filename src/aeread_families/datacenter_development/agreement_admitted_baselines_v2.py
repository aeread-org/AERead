"""Free baselines on the v2 packs: the ceiling, the fixed rules and the integrator's own-information reference.

    python -m aeread_families.datacenter_development.agreement_admitted_baselines_v2 --write
    python -m aeread_families.datacenter_development.agreement_admitted_baselines_v2 --check

Section 2 of ``docs/families/datacenter/agreement_confirmatory_v2_plan.md`` publishes, before the freeze, the ceiling
and the free baselines of every v2 world; amendment 3 adds the integrator's own-information reference. No model is
called. In each world and seat the scripted negotiator sits in the other seat in the style drawn from the public world
and its seat (``agreement_admitted_pack.public_style``, the counterpart of the "vs firm" arms), and this seat is played by:

- v1's two stand-ins that know both true types (:func:`agreement_admitted_baselines.one_world`): ``first_offer`` and
  ``best_plan``, the ceiling;
- each fixed style of the scripted negotiator (:data:`STYLES`), knowing only its own costs and the declared odds;
  ``price_only`` in the integrator seat is the rule of contrasts P3a and P3b;
- in the integrator seat, the own-information best reply (:mod:`.agreement_own_information`), Gate 3's reference.

Earnings are the seat's surplus over its own outside option, $k, at both sides' true costs, redline fees deducted.
"""

from __future__ import annotations

import argparse
import json
import statistics
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Mapping

from . import agreement as ag
from . import agreement_admitted_baselines as v1b
from . import agreement_admitted_pack as aap
from . import agreement_admitted_pack_v2 as v2
from . import agreement_own_information as oi
from . import risk_allocation_contracts as rc

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OUT = REPOSITORY_ROOT / "evidence" / "datacenter_development" / "agreement_admitted_v2_free_baselines"
PACKS = (v2.ADMITTED.pack, v2.PILOT.pack)
STYLES = ("even", "firm", "hard", "soft", "overreach", "price_only", "collapse", "public")


def one_world(job: tuple[str, Mapping[str, Any]]) -> dict[str, Any]:
    code, payload = job
    row = v1b.one_world((code, payload))
    cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
    for seat in ag.SEATS:
        row["seats"][seat]["styles"] = {
            s: v2.rule_earnings(cw, it, seat, aap.public_style(cw, seat) if s == "public" else s) for s in STYLES}
    row["seats"]["integrator"]["own_information"] = oi.own_information(cw, it)
    return row


def _mean(xs: list[float]) -> float:
    return round(statistics.fmean(xs), 2)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deal = [r for r in rows if r["available"] > 0]
    out: dict[str, Any] = {"worlds": len(rows), "deal_worlds": len(deal)}
    for seat in ag.SEATS:
        x = {"first_offer": _mean([r["seats"][seat]["first_offer"]["earnings"] for r in deal]),
             "ceiling": _mean([r["seats"][seat]["best_plan"]["earnings"] for r in deal]),
             "styles": {s: _mean([r["seats"][seat]["styles"][s]["earnings"] for r in deal]) for s in STYLES},
             "style_ir_violations_all_worlds": {s: sum(r["seats"][seat]["styles"][s]["ir_violation"] for r in rows) for s in STYLES}}
        if seat == "integrator":
            own = [r["seats"][seat]["own_information"] for r in deal]
            rule = [r["seats"][seat]["styles"][v2.RULE]["earnings"] for r in deal]
            x["own_information"] = {k: _mean([o[k] for o in own]) for k in ("at_true", "expected", "full_information_grid")}
            x["own_information_less_rule"] = _mean([o["at_true"] - q for o, q in zip(own, rule)])
            x["ceiling_less_rule"] = _mean([r["seats"][seat]["best_plan"]["earnings"] - q for r, q in zip(deal, rule)])
            x["worlds_own_information_beats_rule_by_25"] = sum(o["at_true"] - q >= 25 for o, q in zip(own, rule))
        out[seat] = x
    return out


def report(processes: int = 8) -> dict[str, Any]:
    packs = {}
    for pack in PACKS:
        _, raw, _ = v2.load(v2.SPECS[pack])
        jobs = [(c["case_id"].rsplit(".", 1)[-1], c["payload"]) for c in sorted(raw.values(), key=lambda c: c["case_id"])]
        if processes > 1:
            with Pool(processes) as pool:
                rows = pool.map(one_world, jobs, chunksize=1)
        else:
            rows = [one_world(j) for j in jobs]
        packs[pack] = {"summary": _summary(rows), "worlds": rows}
    return {"plan": v2.PLAN, "counterpart": "agreement_admitted_pack.public_style (drawn_public_v1)", "styles": list(STYLES),
            "rule": v2.RULE, "own_information_grid": list(oi.GRID),
            "earnings": "the seat's surplus over its own outside option, $k, at both sides' true costs, redline fees deducted",
            "summary_over": "deal worlds (available > 0)", "packs": packs}


def readme(r: Mapping[str, Any]) -> str:
    lines = ["# Agreement case v2: free baselines, the ceiling and the own-information reference", "",
             f"Published before the freeze, as `{v2.PLAN}` Section 2 and amendment 3 require; no model called. The",
             "counterpart in every world and seat is the scripted negotiator in the style drawn from the public world and its",
             "seat (`drawn_public_v1`). The ceiling knows both true types; the fixed styles and the own-information reference",
             "know only their own costs and the declared odds. Means over deal worlds, $k above the seat's outside option.", "",
             "| Pack | Deal worlds | Seat | Ceiling | Own information (at true charge) | price_only | Best other style | First offer |",
             "|---|---:|---|---:|---:|---:|---:|---:|"]
    for pack in PACKS:
        s = r["packs"][pack]["summary"]
        for seat in ag.SEATS:
            x = s[seat]
            other = max((k for k in STYLES if k != "price_only"), key=lambda k: x["styles"][k])
            own = x.get("own_information", {}).get("at_true", "")
            lines.append(f"| {pack} | {s['deal_worlds']} of {s['worlds']} | {seat} | {x['ceiling']} | {own} | {x['styles']['price_only']} | "
                         f"{other} {x['styles'][other]} | {x['first_offer']} |")
    lines += ["", "Rebuild: `python -m aeread_families.datacenter_development.agreement_admitted_baselines_v2 --check` "
              "(per world and seat in `reports/baselines.json`).", ""]
    return "\n".join(lines)


def files(r: Mapping[str, Any]) -> dict[str, str]:
    return {"reports/baselines.json": json.dumps(r, indent=1, sort_keys=True) + "\n", "README.md": readme(r)}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--processes", type=int, default=8)
    args = parser.parse_args(argv)
    made = files(report(args.processes))
    if args.write:
        for name, text in made.items():
            (OUT / name).parent.mkdir(parents=True, exist_ok=True)
            (OUT / name).write_text(text)
        print(made["README.md"])
    if args.check:
        differ = [name for name, text in made.items() if not (OUT / name).is_file() or (OUT / name).read_text() != text]
        print("differs: " + ", ".join(differ) if differ else f"identical: {len(made)} files")
        return 1 if differ else 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
