"""The agreement case's v2 admitted pack and its pilot: v1's admission, the walk-away brief, and a headroom screen.

    python -m aeread_families.datacenter_development.agreement_admitted_pack_v2 --write             # both packs
    python -m aeread_families.datacenter_development.agreement_admitted_pack_v2 --check             # rebuild, compare byte for byte
    python -m aeread_families.datacenter_development.agreement_admitted_pack_v2 --pack agreement_admitted_pilot_v2 --write

The plan is ``docs/families/datacenter/agreement_confirmatory_v2_plan.md`` (Section 2 and amendment 3). Every step of
:mod:`.agreement_admitted_pack` is reused unchanged and that module is not edited: the public world, v1's admission
on structure, the cell, the hidden types on their own stream (keyed here by the v2 pack id) and the index row. Three
things are added:

- **the walk-away brief**: every case's payload carries ``brief_version: walkaway_stated_v1``
  (:data:`agreement.BRIEFS`), which adds one line to the client's brief and leaves the integrator's unchanged;
- **the headroom screen** (amendment 3): after the types are drawn, a deal world is admitted only if the integrator's
  full-information ceiling against the client's publicly drawn firm style
  (``agreement_negotiator_check.best_plan``, both types known) less the ``price_only`` style's earnings in the
  integrator seat against the same client is at least :data:`HEADROOM_MARGIN`. Below it the seed is logged
  ``headroom_under_margin`` and the cell stays open. A world without a deal is admitted without the screen;
- **the extension**: if the filled quotas give fewer than :data:`MIN_DEAL_WORLDS` deal worlds, the scan continues and
  admits only deal worlds that pass the screen (``admitted_extension``) until that many exist.

The screen reads the drawn types and the scripted counterpart, never a subject's play. Seeds start at 8,000,000 (the
pack) and 8,500,000 (the pilot), above every earlier agreement pack, and :func:`pack_failures` checks that no world is
shared with v1's admitted pack, v1's pilot, a development pack, or the other v2 pack.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256

from . import agreement as ag
from . import agreement_admitted_pack as aap
from . import agreement_negotiator as an
from . import agreement_negotiator_check as nc
from . import risk_allocation_contracts as rc
from .agreement_environment import BRIEF_FIELD, AgreementPlugin

GENERATOR_ID = "datacenter_agreement_admitted_generator_v2"
GENERATOR_VERSION = "2.0.0"
BRIEF_VERSION = "walkaway_stated_v1"
PLAN = "docs/families/datacenter/agreement_confirmatory_v2_plan.md"
#: $k: the integrator's full-information ceiling less the price_only rule, on a deal world (Section 2).
HEADROOM_MARGIN = 25.0
RULE = "price_only"
#: The extension's floor on deal worlds for the confirmatory pack (Section 2); the pilot has none.
MIN_DEAL_WORLDS = 56
EPS = 1e-9
QUOTAS = {"walk": 27, "trade": 27, "hand_risk_over": 26, "take_risk_on": 0, "move_the_price": 0}
ADMITTED = aap.PackSpec(
    "agreement_admitted_v2", "admitted_v2", 8_000_000, QUOTAS,
    claim_status=("admitted on its structure, then screened for the integrator's headroom over the price_only rule on the "
                  "drawn types; no model has played it. For the plan " + PLAN))
PILOT = aap.PackSpec(
    "agreement_admitted_pilot_v2", "pilot_v2", 8_500_000,
    {"walk": 4, "trade": 4, "hand_risk_over": 4, "take_risk_on": 0, "move_the_price": 0},
    claim_status=("the pilot of " + PLAN + " (amendment 3): the v2 pack's rules on their own seeds; development "
                  "evidence, never a confirmatory world"))
SPECS = {s.pack: s for s in (ADMITTED, PILOT)}
MIN_DEAL = {ADMITTED.pack: MIN_DEAL_WORLDS, PILOT.pack: 0}
STATUSES = ("rejected", "cell_full", "headroom_under_margin", "admitted", "admitted_extension")
#: v1's log fields, then whether the drawn types give a deal and the headroom where it was computed.
LOG_FIELDS = (*aap.LOG_FIELDS, "deal", "headroom")


def case_of(seed: int, cw: rc.CWorld, spec: aap.PackSpec) -> dict[str, Any]:
    """v1's case for this pack and seed, with the walk-away brief in its payload and its digest recomputed."""
    raw = aap.case_of(seed, cw, spec)
    raw["payload"][BRIEF_FIELD] = BRIEF_VERSION
    raw["provenance"] = {**raw["provenance"], "generator_id": GENERATOR_ID, "generator_version": GENERATOR_VERSION}
    AgreementPlugin().validate_payload(raw["payload"])
    raw.pop("content_sha256")
    raw["content_sha256"] = case_content_sha256(raw)
    return raw


def world_of(raw: Mapping[str, Any]) -> tuple[rc.CWorld, Any]:
    return rc.world_from({k: raw["payload"][k] for k in ("world", "integrator_type", "extras")})


def rule_earnings(cw: rc.CWorld, it: Any, seat: str, style: str | an.Style) -> dict[str, Any]:
    """A fixed style in ``seat`` against the other seat's publicly drawn firm style: the grade's view of the seat."""
    other = aap.public_style(cw, ag.other(seat))
    state = ag.initial_state(cw)
    while not state["finished"]:
        mover = style if state["to_move"] == seat else other
        state = ag.apply(state, an.negotiator_move(state, cw, it, mover), cw)
    g = ag.grade(cw, it, state)
    return {"earnings": round(g[f"{seat}_surplus"], 3), "termination": g["termination"], "ir_violation": bool(g[f"{seat}_ir_violation"])}


def headroom(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The screen's quantities for one drawn world: whether it has a deal, and on a deal world the ceiling, the rule and
    their difference."""
    cw, it = world_of(raw)
    available = max(0.0, nc.Informed(cw, it, "client").available)
    if available <= EPS:
        return {"deal": False, "available": 0.0, "ceiling": None, "rule": None, "headroom": None}
    ceiling, _, _ = nc.best_plan(cw, it, "integrator", aap.public_style(cw, "client"))
    rule = rule_earnings(cw, it, "integrator", RULE)["earnings"]
    return {"deal": True, "available": round(available, 3), "ceiling": round(ceiling, 3), "rule": rule,
            "headroom": round(ceiling - rule, 3)}


def _screened(job: tuple[int, str]) -> dict[str, Any]:
    seed, pack = job
    r = aap.screen(seed)
    raw = case_of(seed, r["world"].cw, SPECS[pack])
    return {"seed": seed, "headroom": headroom(raw)}


def log_row(r: Mapping[str, Any], status: str, h: Mapping[str, Any] | None) -> list[Any]:
    return [*aap.log_row(r, status), None if h is None else int(h["deal"]), None if h is None else h["headroom"]]


def decide(r: Mapping[str, Any], h: Mapping[str, Any] | None, left: Mapping[str, int], deal_worlds: int, minimum: int) -> str:
    """A seed's status from its admission reasons, its cell's quota, the deal count so far and its screen."""
    if r["reasons"]:
        return "rejected"
    if any(left.values()):
        if left[r["cell"]] <= 0:
            return "cell_full"
        if h["deal"] and h["headroom"] < HEADROOM_MARGIN:
            return "headroom_under_margin"
        return "admitted"
    if deal_worlds < minimum:
        if not h["deal"]:
            return "cell_full"
        return "headroom_under_margin" if h["headroom"] < HEADROOM_MARGIN else "admitted_extension"
    raise AssertionError("the scan should have stopped")


def needs_screen(r: Mapping[str, Any], left: Mapping[str, int], deal_worlds: int, minimum: int) -> bool:
    if r["reasons"]:
        return False
    if any(left.values()):
        return left[r["cell"]] > 0
    return deal_worlds < minimum


def scan(spec: aap.PackSpec, processes: int = 1, chunk: int = 256) -> dict[str, Any]:
    """Every seed from the spec's base seed in order until the quotas and the deal-world floor are met. The public screen
    and the headroom screen run in parallel; each seed's status is decided in seed order."""
    minimum = MIN_DEAL[spec.pack]
    left, deal_worlds = dict(spec.quotas), 0
    log: list[list[Any]] = []
    admitted: list[dict[str, Any]] = []
    pool = None
    if processes > 1:
        from multiprocessing import get_context
        pool = get_context("spawn").Pool(processes)
    mapper = pool.map if pool else lambda f, xs: [f(x) for x in xs]
    try:
        seed = spec.base_seed
        while (any(left.values()) or deal_worlds < minimum) and seed < spec.base_seed + spec.max_scan:
            seeds = list(range(seed, min(seed + chunk, spec.base_seed + spec.max_scan)))
            publics = mapper(aap.screen, seeds)
            # speculative: the headroom of every seed that could need it given the state at the start of the chunk
            wanted = [r["seed"] for r in publics if needs_screen(r, left, deal_worlds, minimum)]
            screened = {x["seed"]: x["headroom"] for x in mapper(_screened, [(s, spec.pack) for s in wanted])}
            for r in publics:
                if not (any(left.values()) or deal_worlds < minimum):
                    break
                h = screened.get(r["seed"]) if needs_screen(r, left, deal_worlds, minimum) else None
                status = decide(r, h, left, deal_worlds, minimum)
                if status in ("admitted", "admitted_extension"):
                    if status == "admitted":
                        left[r["cell"]] -= 1
                    deal_worlds += int(h["deal"])
                    admitted.append({**r, "headroom": h, "status": status})
                log.append(log_row(r, status, h))
            seed = seeds[-1] + 1
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    if any(left.values()) or deal_worlds < minimum:
        raise RuntimeError(f"the scan stopped at {spec.base_seed + spec.max_scan} with quotas {left}, {deal_worlds} deal worlds")
    return {"log": log, "admitted": admitted}


def summary(log: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """v1's scan summary, with the v2 statuses and the screen's distribution."""
    out = aap.summary([row[: len(aap.LOG_FIELDS)] for row in log])
    screened = [row for row in log if row[11] is not None]
    out["status"] = dict(sorted(Counter(row[5] for row in log).items()))
    out["admitted_by_cell"] = {c: sum(1 for row in log if row[5] in ("admitted", "admitted_extension") and row[3] == c) for c in aap.CELLS}
    out["headroom_screen"] = {
        "margin": HEADROOM_MARGIN, "rule": RULE, "screened_deal_worlds": len(screened),
        "below_margin": sum(row[5] == "headroom_under_margin" for row in log),
        "headroom_quantiles_screened": aap._quantiles([row[11] for row in screened]) if screened else None,
        "no_deal_worlds_reaching_the_screen": sum(1 for row in log if row[10] == 0),
    }
    return out


def generator_spec(spec: aap.PackSpec) -> dict[str, Any]:
    out = aap.generator_spec(spec)
    out.update(id=GENERATOR_ID, version=GENERATOR_VERSION, brief_version=BRIEF_VERSION,
               headroom_screen={"margin": HEADROOM_MARGIN, "rule": RULE, "ceiling": "agreement_negotiator_check.best_plan, integrator seat, "
                                "against the client's public firm style, both types known",
                                "on": "deal worlds after the hidden types are drawn"},
               min_deal_worlds=MIN_DEAL[spec.pack], statuses=list(STATUSES), plan=PLAN)
    return out


def build(result: Mapping[str, Any], spec: aap.PackSpec) -> tuple[list[dict[str, Any]], dict[str, Any], list[list[Any]]]:
    cases, worlds = [], []
    for r in result["admitted"]:
        raw = case_of(r["seed"], r["world"].cw, spec)
        row = aap.index_row(r, raw)
        h = r["headroom"]
        row["brief_version"] = BRIEF_VERSION
        row["integrator_headroom"] = {"ceiling": h["ceiling"], "rule": h["rule"], "headroom": h["headroom"]} if h["deal"] else None
        row["status"] = r["status"]
        if abs(row["available_surplus"] - h["available"]) > 2e-3:  # both rounded to 3 decimals from different floats
            raise RuntimeError(f"seed {r['seed']}: the index's available surplus differs from the screen's")
        cases.append(raw)
        worlds.append(row)
    manifest = {
        "pack": spec.pack, "family_id": aap.FAMILY_ID, "family_version": aap.FAMILY_VERSION, "generator": generator_spec(spec),
        "claim_status": spec.claim_status, "scan": summary(result["log"]), "scan_log_fields": list(LOG_FIELDS), "worlds": worlds,
    }
    return cases, manifest, [list(row) for row in result["log"]]


def files(result: Mapping[str, Any], spec: aap.PackSpec) -> dict[str, str]:
    cases, manifest, log = build(result, spec)
    out = {f"{raw['case_id'].rsplit('.', 1)[-1]}.json": aap._dump(raw) for raw in cases}
    out["pack.json"] = aap._dump(manifest)
    out["scan.json"] = "[\n" + ",\n".join(json.dumps(row, separators=(",", ":")) for row in log) + "\n]\n"
    return out


def load(spec: aap.PackSpec = ADMITTED) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[list[Any]]]:
    return aap.load(spec)


def log_failures(log: Sequence[Sequence[Any]], spec: aap.PackSpec) -> list[str]:
    """Whether every status follows from the row's reasons, cell, screen and the counts before it, and the scan stopped
    on the seed that met the last requirement."""
    out, left, deals, minimum = [], dict(spec.quotas), 0, MIN_DEAL[spec.pack]
    if [row[0] for row in log] != list(range(spec.base_seed, spec.base_seed + len(log))):
        out.append("the log is not every seed in order from the base seed")
    for row in log:
        r = {"reasons": row[4], "cell": row[3]}
        h = None if row[10] is None else {"deal": bool(row[10]), "headroom": row[11]}
        if needs_screen(r, left, deals, minimum) != (h is not None):
            out.append(f"seed {row[0]} records a screen exactly when it should not")
            continue
        expected = decide(r, h, left, deals, minimum) if needs_screen(r, left, deals, minimum) else (
            "rejected" if row[4] else "cell_full")
        if row[5] != expected:
            out.append(f"seed {row[0]} is {row[5]}, its row makes it {expected}")
        if expected == "admitted":
            left[row[3]] -= 1
        if expected in ("admitted", "admitted_extension"):
            deals += int(h["deal"])
    if any(left.values()) or deals < minimum or (log and log[-1][5] not in ("admitted", "admitted_extension")):
        out.append("the scan did not stop on the seed that met the last requirement")
    return out


def verify_rows(log: Sequence[Sequence[Any]], seeds: Sequence[int], spec: aap.PackSpec) -> list[str]:
    """Recompute these seeds' rows: the public screen always, the headroom where the row records one."""
    at = {row[0]: row for row in log}
    out = []
    for seed in seeds:
        row = at[seed]
        r = aap.screen(seed)
        h = None if row[10] is None else _screened((seed, spec.pack))["headroom"]
        if log_row(r, row[5], h) != list(row):
            out.append(f"seed {seed}: logged {row}, recomputed {log_row(r, row[5], h)}")
    return out


def pack_failures(manifest: Mapping[str, Any], cases: Mapping[str, Mapping[str, Any]], spec: aap.PackSpec) -> list[str]:
    """v1's pack checks (quotas, the give-up share, distinct worlds, no development world, none of v1's admitted worlds),
    the extension's floor, the brief, the screen on every deal world, and no world of v1's pilot or the other v2 pack."""
    worlds = manifest["worlds"]
    in_quota = {**manifest, "worlds": [w for w in worlds if w["status"] == "admitted"]}
    out = aap.pack_failures(in_quota, {k: v for k, v in cases.items() if k in {w["case_id"] for w in in_quota["worlds"]}}, spec)
    out = [x for x in out if x != "the case files are not the indexed worlds"]
    if set(cases) != {w["case_id"] for w in worlds}:
        out.append("the case files are not the indexed worlds")
    deals = [w for w in worlds if w["available_surplus"] > EPS]
    if len(deals) < MIN_DEAL[spec.pack]:
        out.append(f"{len(deals)} deal worlds, below {MIN_DEAL[spec.pack]}")
    for w in worlds:
        if cases[w["case_id"]]["payload"].get(BRIEF_FIELD) != BRIEF_VERSION:
            out.append(f"{w['case_id']} does not carry the walk-away brief")
        h = w["integrator_headroom"]
        if (w["available_surplus"] > EPS) != (h is not None) or (h is not None and h["headroom"] < HEADROOM_MARGIN):
            out.append(f"{w['case_id']} breaks the headroom screen")
    others = [aap.PILOT, *(s for s in SPECS.values() if s != spec)]
    for other in others:
        if not (other.root / "pack.json").exists():
            continue
        theirs = aap.load(other)[0]["worlds"]
        if ({w["public_sha256"] for w in worlds} & {w["public_sha256"] for w in theirs}
                or {w["world_seed"] for w in worlds} & {w["world_seed"] for w in theirs}):
            out.append(f"a world equals a world of {other.pack}")
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--pack", choices=sorted(SPECS), action="append")
    args = parser.parse_args(argv)
    status = 0
    for pack in args.pack or sorted(SPECS, key=lambda p: p != ADMITTED.pack):
        spec = SPECS[pack]
        result = scan(spec, args.processes)
        made = files(result, spec)
        if args.write:
            spec.root.mkdir(parents=True, exist_ok=True)
            for name, text in made.items():
                (spec.root / name).write_text(text)
            print(f"{spec.root}: {len(made) - 2} worlds, {len(result['log'])} seeds scanned")
        if args.check:
            on_disk = {p.name: p.read_text() for p in spec.root.glob("*.json")}
            if on_disk != made:
                print(pack, "differs:", sorted(k for k in set(on_disk) | set(made) if on_disk.get(k) != made.get(k)))
                status = 1
            else:
                print(f"{pack} identical: {len(made)} files from {len(result['log'])} seeds")
    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["ADMITTED", "BRIEF_VERSION", "HEADROOM_MARGIN", "MIN_DEAL_WORLDS", "PILOT", "QUOTAS", "RULE", "SPECS", "build", "case_of",
           "decide", "files", "headroom", "load", "log_failures", "pack_failures", "rule_earnings", "scan", "summary", "verify_rows"]
