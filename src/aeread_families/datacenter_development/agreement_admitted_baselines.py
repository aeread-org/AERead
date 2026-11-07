"""Free baselines on the agreement case's admitted pack and its pilot: what a stand-in earns against the public firm style.

    python -m aeread_families.datacenter_development.agreement_admitted_baselines --write   # compute and write the report
    python -m aeread_families.datacenter_development.agreement_admitted_baselines --check   # recompute, compare byte for byte

Step 2 of the confirmatory plan's "Before the confirmatory runs" (``docs/families/datacenter/agreement_confirmatory_plan.md``):
the trivial ground of the headroom screen, with no model called. In each world and seat, the scripted negotiator sits in
the other seat in the style drawn from the public world and its seat (``agreement_admitted_pack.public_style``, the
counterpart arm F plays against), and a stand-in that knows both true types (``agreement_negotiator_check.Informed``)
plays this seat:

- ``first_offer``: the stand-in signs the first offer worth signing (``"takes the first offer"``);
- ``best_plan``: the most the stand-in can earn against this script with sign, walk and asks on a grid of shares
  (``agreement_negotiator_check.best_plan``), an exact best reply within that grid.

Both read both types, so ``best_plan`` is a ceiling against this script, not an attainable target; ``first_offer`` is
the anchor a model that accepts at once would land near. Earnings are the seat's surplus over its own outside option,
$k, at both sides' true costs, redline fees deducted (``agreement.grade``), as the plan's primary measure is.
"""

from __future__ import annotations

import argparse
import json
import statistics
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Mapping

from . import agreement as ag
from . import agreement_admitted_pack as aap
from . import agreement_negotiator_check as nc
from . import agreement_pack as ap
from . import risk_allocation_contracts as rc

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OUT = REPOSITORY_ROOT / "evidence" / "datacenter_development" / "agreement_admitted_free_baselines"
PACKS = (aap.ADMITTED.pack, aap.PILOT.pack)
PLAN = "docs/families/datacenter/agreement_confirmatory_plan.md"


def one_world(job: tuple[str, Mapping[str, Any]]) -> dict[str, Any]:
    code, payload = job
    cw, it = rc.world_from({k: payload[k] for k in ("world", "integrator_type", "extras")})
    available = nc.Informed(cw, it, "client").available
    row: dict[str, Any] = {"world": code, "available": round(max(0.0, available), 3), "seats": {}}
    for seat in ag.SEATS:
        style = aap.public_style(cw, ag.other(seat))
        first = ag.grade(cw, it, nc.play(cw, it, seat, style, "takes the first offer"))
        value, path, end = nc.best_plan(cw, it, seat, style)
        best = ag.grade(cw, it, end)
        row["seats"][seat] = {
            "script_style": {"opening": style.opening, "final": style.final, "least": style.least, "reciprocity": style.reciprocity},
            "first_offer": {"earnings": round(first[f"{seat}_surplus"], 3), "termination": first["termination"], "moves": first["moves"]},
            "best_plan": {"earnings": round(value, 3), "plan": path, "termination": best["termination"], "moves": best["moves"],
                          "script_signed_below_its_outside_option": bool(best[f"{ag.other(seat)}_ir_violation"])},
        }
    return row


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deal = [r for r in rows if r["available"] > 0]
    out: dict[str, Any] = {"worlds": len(rows), "deal_worlds": len(deal)}
    for seat in ag.SEATS:
        f = [r["seats"][seat]["first_offer"]["earnings"] for r in deal]
        b = [r["seats"][seat]["best_plan"]["earnings"] for r in deal]
        out[seat] = {"first_offer_mean": round(statistics.fmean(f), 2), "best_plan_mean": round(statistics.fmean(b), 2),
                     "best_less_first_mean": round(statistics.fmean(x - y for x, y in zip(b, f)), 2),
                     "first_offer_signed": sum(r["seats"][seat]["first_offer"]["termination"] == "signed" for r in deal)}
    return out


def report(processes: int = 8) -> dict[str, Any]:
    packs = {}
    for pack in PACKS:
        _, raw = ap.load(pack)
        jobs = [(c["case_id"].rsplit(".", 1)[-1], c["payload"]) for c in sorted(raw.values(), key=lambda c: c["case_id"])]
        if processes > 1:
            with Pool(processes) as pool:
                rows = pool.map(one_world, jobs, chunksize=1)
        else:
            rows = [one_world(j) for j in jobs]
        packs[pack] = {"summary": _summary(rows), "worlds": rows}
    return {"plan": PLAN, "counterpart": "agreement_admitted_pack.public_style (drawn_public_v1)", "grid": list(nc.GRID),
            "stand_in": "knows both true types; best_plan is a ceiling against this script, not an attainable target",
            "earnings": "the seat's surplus over its own outside option, $k, at both sides' true costs, redline fees deducted",
            "summary_over": "deal worlds (available > 0)", "packs": packs}


def readme(r: Mapping[str, Any]) -> str:
    lines = ["# Agreement case: free baselines on the admitted pack and its pilot", "",
             f"Step 2 of `{PLAN}` (\"Before the confirmatory runs\"), no model called. The counterpart in every world and seat is the",
             "scripted negotiator in the style drawn from the public world and its seat (`drawn_public_v1`, arm F's counterpart).",
             "A stand-in that knows both true types plays the other seat: `first_offer` signs the first offer worth signing;",
             "`best_plan` is its best reply on a grid of asks, a ceiling against this script, not an attainable target.",
             "Earnings are the seat's surplus over its own outside option, $k, redline fees deducted. Means over deal worlds.", "",
             "| Pack | Deal worlds | Seat | First offer | Best plan | Best less first | First offer signed |", "|---|---:|---|---:|---:|---:|---:|"]
    for pack in PACKS:
        s = r["packs"][pack]["summary"]
        for seat in ag.SEATS:
            x = s[seat]
            lines.append(f"| {pack} | {s['deal_worlds']} of {s['worlds']} | {seat} | {x['first_offer_mean']} | {x['best_plan_mean']} | "
                         f"{x['best_less_first_mean']} | {x['first_offer_signed']} |")
    lines += ["", "Rebuild: `python -m aeread_families.datacenter_development.agreement_admitted_baselines --check` "
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
