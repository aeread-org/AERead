"""The agreement case's v2 confirmatory analysis: P1, P2, P3a and P3b, then the secondary measures, as the plan declares.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_analysis.py analyze \\
        --if runs/<IF> --hh runs/<HH> --cf runs/<CF> OUT.json
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_analysis.py sizing

Everything here is declared in ``docs/families/datacenter/agreement_confirmatory_v2_plan.md`` (Sections 4 to 6) and
committed before the confirmatory's freeze; this module only computes it. Every number is read from the sealed receipts'
score leaves through :func:`agreement_confirmatory_analysis.load` (v1's reader: the record's grade is checked against
the receipt and not used). Earnings are the seat's ``*_surplus`` leaf: $k over its own outside option at both sides'
true costs, redline fees deducted. A negotiation counts when its receipt is ``ok`` and ``episode_valid`` is 1.

On the pack's deal worlds, each model's valid plays are averaged within a world first; a world enters a contrast when
every negotiation the contrast needs has at least one valid play. Differences are paired by world.

- **P1** (arm IF): the integrator's earnings against the firm population, Codex less Opus.
- **P2** (arm HH): head-to-head earnings, Codex less Opus, averaged over the two seats (v1's world value).
- **P3a, P3b** (arm IF): Codex's, then Opus's, integrator earnings less the ``price_only`` rule's in the same world
  against the same client, read from the published v2 baselines.

Paired t, two-sided; Holm across the four at a familywise 0.05; 95% intervals and intervals at 1 - 0.05/4; a world
bootstrap as a check. A contrast is *found* when Holm rejects zero, and *at least its minimum effect* only when the lower
end of its 95% interval clears that effect. A contrast that loses more than 10% of its deal worlds is inconclusive
whatever its p-value. Missingness bounds set each missing play to its pairing's lowest or highest earnings.

Secondary, without a claim (Section 5): the client seat against the firm population (arm CF) beside DC-D-35; signings
below a walk-away point per model and seat; the share of the rule-to-ceiling headroom each model captures; joint loss
and its split; the fee replayed at $0, $12.5k and $50k on the recorded actions; how often a model's two plays of a world
end identically (Gate 1's degenerate ground).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import agreement_confirmatory_analysis as v1a
from aeread_families.datacenter_development import agreement as ag
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as pv2
from aeread_families.datacenter_development import agreement_pack as ap
from aeread_families.datacenter_development import risk_allocation_contracts as rc

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASELINES = REPOSITORY_ROOT / "evidence/datacenter_development/agreement_admitted_v2_free_baselines/reports/baselines.json"
PUBLIC = v1a.PUBLIC
MODELS = v1a.MODELS
ALPHA, FAMILY = 0.05, 4
EFFECTS = {"P1": 40.0, "P2": 100.0, "P3a": 40.0, "P3b": 40.0}
DROPOUT = v1a.DROPOUT
FEES = (0.0, 12.5, 50.0)
#: Section 6: power 0.8 at the first Holm step, 5% attrition.
POWER, ATTRITION = 0.8, 0.05
ALPHAS = (0.05, ALPHA / FAMILY)
STRICT = f"ci_{1 - ALPHA / FAMILY:.4f}"


def if_pairing(model: str) -> str:
    return f"{model}_integrator__negotiator_{PUBLIC}_client"


def cf_pairing(model: str) -> str:
    return f"negotiator_{PUBLIC}_integrator__{model}_client"


def play_mean(cells: Mapping, pairing: str, world: str, seat: str, plays: int) -> float | None:
    """The mean of a pairing's valid plays of a world in a seat; None when no play is valid."""
    xs = [v1a.earnings(cells.get((pairing, world, r)), seat) for r in range(plays)]
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _bounds_mean(cells: Mapping, pairing: str, world: str, seat: str, plays: int, high: bool) -> float:
    lo, hi = v1a._pairing_range(cells, pairing, seat)
    xs = [v1a.earnings(cells.get((pairing, world, r)), seat) for r in range(plays)]
    return statistics.fmean(x if x is not None else (hi if high else lo) for x in xs)


def contrast(name: str, values: Mapping[str, float | None], base: int, bounds: tuple[list[float], list[float]]) -> dict[str, Any]:
    used = {w: v for w, v in values.items() if v is not None}
    dropped = sorted(w for w, v in values.items() if v is None)
    out = {"contrast": name, "worlds_base": base, "worlds_used": len(used), "worlds_dropped": dropped,
           "dropout_share": round(1 - len(used) / base, 4) if base else 1.0, "minimum_effect": EFFECTS[name]}
    out.update(v1a.t_summary(list(used.values()), ALPHAS) if len(used) > 1 else {"n": len(used), "mean": None, "p": 1.0})
    out["missingness_bounds_mean"] = [round(statistics.fmean(bounds[0]), 3), round(statistics.fmean(bounds[1]), 3)] if bounds[0] else None
    out["world_values"] = {w: round(v, 3) for w, v in sorted(used.items())}
    return out


def p1(cells: Mapping, deal: Sequence[str], plays: int) -> dict[str, Any]:
    values, lo, hi = {}, [], []
    for w in deal:
        a = play_mean(cells, if_pairing("codex"), w, "integrator", plays)
        b = play_mean(cells, if_pairing("claude"), w, "integrator", plays)
        values[w] = None if a is None or b is None else a - b
        lo.append(_bounds_mean(cells, if_pairing("codex"), w, "integrator", plays, False)
                  - _bounds_mean(cells, if_pairing("claude"), w, "integrator", plays, True))
        hi.append(_bounds_mean(cells, if_pairing("codex"), w, "integrator", plays, True)
                  - _bounds_mean(cells, if_pairing("claude"), w, "integrator", plays, False))
    return contrast("P1", values, len(deal), (lo, hi))


def p2(cells: Mapping, deal: Sequence[str]) -> dict[str, Any]:
    entries = {w: v1a._entries_h(cells, w) for w in deal}
    values = {w: v1a.world_value(e) for w, e in entries.items()}
    bounds = ([v1a._bounded(e, cells, True) for e in entries.values()], [v1a._bounded(e, cells, False) for e in entries.values()])
    return contrast("P2", values, len(deal), bounds)


def p3(name: str, model: str, cells: Mapping, deal: Sequence[str], plays: int, rule: Mapping[str, float]) -> dict[str, Any]:
    values, lo, hi = {}, [], []
    for w in deal:
        a = play_mean(cells, if_pairing(model), w, "integrator", plays)
        values[w] = None if a is None else a - rule[w]
        lo.append(_bounds_mean(cells, if_pairing(model), w, "integrator", plays, False) - rule[w])
        hi.append(_bounds_mean(cells, if_pairing(model), w, "integrator", plays, True) - rule[w])
    return contrast(name, values, len(deal), (lo, hi))


def reading(r: Mapping[str, Any]) -> str:
    if r["inconclusive_by_dropout"]:
        return "inconclusive: more than 10% of its deal worlds dropped out"
    if not r["rejected"]:
        return "not found: Holm does not reject 0"
    lower = r["ci_0.9500"][0] if r["mean"] > 0 else -r["ci_0.9500"][1]
    if lower >= r["minimum_effect"]:
        return f"found, at least its minimum effect of {r['minimum_effect']:g}"
    return f"found; the 95% interval does not clear its minimum effect of {r['minimum_effect']:g}"


def baselines(path: Path = BASELINES, pack: str = pv2.ADMITTED.pack) -> dict[str, dict[str, Any]]:
    report = json.loads(path.read_text())
    return {r["world"]: r for r in report["packs"][pack]["worlds"]}


def primary(IF: Mapping[str, Any], HH: Mapping[str, Any], deal: Sequence[str], base: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    ic, hc = v1a.index(IF), v1a.index(HH)
    plays = IF["plan"]["controls"]["replicates"]
    rule = {w: base[w]["seats"]["integrator"]["styles"][pv2.RULE]["earnings"] for w in deal}
    results = [p1(ic, deal, plays), p2(hc, deal), p3("P3a", "codex", ic, deal, plays, rule), p3("P3b", "claude", ic, deal, plays, rule)]
    v1a.holm(results)
    for r in results:
        r["inconclusive_by_dropout"] = r["dropout_share"] > DROPOUT
        r["reading"] = reading(r)
    return results


def headroom_captured(IF: Mapping[str, Any], deal: Sequence[str], base: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """(model mean - rule mean) / (ceiling mean - rule mean), and the same against the own-information reference."""
    ic, plays = v1a.index(IF), IF["plan"]["controls"]["replicates"]
    rule = statistics.fmean(base[w]["seats"]["integrator"]["styles"][pv2.RULE]["earnings"] for w in deal)
    ceiling = statistics.fmean(base[w]["seats"]["integrator"]["best_plan"]["earnings"] for w in deal)
    own = statistics.fmean(base[w]["seats"]["integrator"]["own_information"]["at_true"] for w in deal)
    out = {"rule_mean": round(rule, 2), "ceiling_mean": round(ceiling, 2), "own_information_mean": round(own, 2)}
    for m in MODELS:
        xs = [play_mean(ic, if_pairing(m), w, "integrator", plays) for w in deal]
        mean = statistics.fmean(x for x in xs if x is not None)
        out[m] = {"mean": round(mean, 2), "share_of_ceiling_headroom": round((mean - rule) / (ceiling - rule), 3),
                  "share_of_own_information_headroom": round((mean - rule) / (own - rule), 3) if own != rule else None}
    return out


def below_walk_away(campaign: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pairing, (integ, client) in campaign["plan"]["pairings"].items():
        cs = [c for c in campaign["cells"] if c["pairing"] == pairing and c["valid"]]
        for seat, subject in (("integrator", integ), ("client", client)):
            if not subject.startswith("scripted_"):
                out[f"{subject} as {seat} ({pairing})"] = f"{sum(int(c['leaves'][f'{seat}_ir_violation']) for c in cs)} of {len(cs)}"
    return out


def identical_plays(IF: Mapping[str, Any]) -> dict[str, Any]:
    """Gate 1's degenerate ground: a model's two plays of a world that end the same (termination, agreement, price, moves)."""
    ic, plays = v1a.index(IF), IF["plan"]["controls"]["replicates"]
    out = {}
    for m in MODELS:
        same = pairs = 0
        for w in sorted({k[1] for k in ic}):
            ends = []
            for r in range(plays):
                c = ic.get((if_pairing(m), w, r))
                if c is None or not c["valid"]:
                    break
                g = c.get("grade") or {}
                ends.append((g.get("termination"), g.get("signed_agreement"), g.get("signed_price"), g.get("moves")))
            if len(ends) == plays:
                pairs += 1
                same += int(len(set(ends)) == 1)
        out[m] = f"{same} of {pairs} worlds"
    return out


def _actions(run_dir: Path, cell: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The parsed actions of a cell from its sealed events, each payload checked against its digest, and the final state."""
    events_path = next((run_dir / "evidence" / cell["cell_key"]).rglob("events.jsonl"))
    actions, final = [], None
    for line in events_path.read_text().splitlines():
        e = json.loads(line)
        if e["event_type"] not in ("action_parsed", "transition_applied"):
            continue
        raw = (events_path.parent / e["payload_ref"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != e["payload_sha256"]:
            raise SystemExit(f"{cell['cell_key']}: a sealed payload does not match its digest")
        p = json.loads(raw)
        if e["event_type"] == "action_parsed":
            actions.append(p["parse_result"]["action"])
        else:
            final = p["transition"]["state"]
    return actions, final


def fee_sensitivity(run_dir: Path, campaign: Mapping[str, Any], cases: Mapping[str, Mapping[str, Any]], deal: Sequence[str]) -> dict[str, Any]:
    """Each valid negotiation's recorded actions replayed with the redline fee at each of :data:`FEES`; the moves stay the
    agent's, only the fee changes. Mean joint loss and each model seat's mean earnings on deal worlds."""
    rows: dict[str, dict[float, list[float]]] = {}
    for c in campaign["cells"]:
        if not c["valid"] or c["world"] not in deal:
            continue
        cw, it = rc.world_from({k: cases[c["case_id"]]["payload"][k] for k in ("world", "integrator_type", "extras")})
        actions, final = _actions(run_dir, c)
        state = ag.initial_state(cw)
        for a in actions:
            state = ag.apply(state, a, cw)
        if state != final:
            raise SystemExit(f"{c['cell_key']}: the replayed actions do not reach the sealed final state")
        integ, client = campaign["plan"]["pairings"][c["pairing"]]
        for fee in FEES:
            world = replace(cw, w=replace(cw.w, terms=replace(cw.w.terms, round_cost=fee)))
            s = ag.initial_state(world)
            for a in actions:
                s = ag.apply(s, a, world)
            g = ag.grade(world, it, s)
            rows.setdefault(f"{c['pairing']}:joint_value_lost", {}).setdefault(fee, []).append(g["joint_value_lost"])
            for seat, subject in (("integrator", integ), ("client", client)):
                if not subject.startswith("scripted_"):
                    rows.setdefault(f"{subject} as {seat} ({c['pairing']})", {}).setdefault(fee, []).append(g[f"{seat}_surplus"])
    return {k: {f"{fee:g}": round(statistics.fmean(v), 2) for fee, v in sorted(by.items())} for k, by in sorted(rows.items())}


def analyze(if_dir: Path, hh_dir: Path, cf_dir: Path | None, baselines_path: Path = BASELINES,
            pack: str = pv2.ADMITTED.pack) -> dict[str, Any]:
    """The declared analysis on the confirmatory pack; ``pack`` names the pilot's only to check the code end to end."""
    manifest, cases = ap.load(pack)
    meta = {w["case_id"].rsplit(".", 1)[-1]: w for w in manifest["worlds"]}
    worlds = sorted(meta)
    deal = [w for w in worlds if meta[w]["available_surplus"] > 0]
    base = baselines(baselines_path, pack)
    IF, HH = v1a.load(if_dir), v1a.load(hh_dir)
    out: dict[str, Any] = {"pack": pack, "worlds": len(worlds), "deal_worlds": len(deal),
                           "plan": "docs/families/datacenter/agreement_confirmatory_v2_plan.md",
                           "primary": primary(IF, HH, deal, base),
                           "campaigns": {"IF": v1a._campaign_meta(IF, if_dir), "HH": v1a._campaign_meta(HH, hh_dir)}}
    secondary: dict[str, Any] = {"IF": v1a.secondary_of(IF, meta), "HH": v1a.secondary_of(HH, meta),
                                 "headroom_captured": headroom_captured(IF, deal, base),
                                 "below_walk_away": {"IF": below_walk_away(IF), "HH": below_walk_away(HH)},
                                 "identical_plays": identical_plays(IF),
                                 "fee_sensitivity": {"IF": fee_sensitivity(if_dir, IF, cases, deal), "HH": fee_sensitivity(hh_dir, HH, cases, deal)}}
    if cf_dir is not None:
        CF = v1a.load(cf_dir)
        out["campaigns"]["CF"] = v1a._campaign_meta(CF, cf_dir)
        cc = v1a.index(CF)
        client_gap = {w: (lambda a, b: None if a is None or b is None else a - b)(
            play_mean(cc, cf_pairing("codex"), w, "client", 1), play_mean(cc, cf_pairing("claude"), w, "client", 1)) for w in deal}
        used = [v for v in client_gap.values() if v is not None]
        secondary["CF"] = v1a.secondary_of(CF, meta)
        secondary["CF"]["codex_less_claude_client_earnings"] = {**v1a.t_summary(used, ALPHAS), "claim": "none",
                                                               "limit": "DC-D-35: the client seat has little to infer"}
        secondary["below_walk_away"]["CF"] = below_walk_away(CF)
        secondary["fee_sensitivity"]["CF"] = fee_sensitivity(cf_dir, CF, cases, deal)
    out["secondary"] = secondary
    return out


def sizing() -> dict[str, Any]:
    """Section 6's table from the committed sizing module (``aeread.design.sizing`` at 159cba3c)."""
    module, digest = v1a._sizing_module()
    need = lambda sd, effect: module.worlds_needed(sd, effect, power=POWER, alpha=ALPHA / FAMILY, attrition=ATTRITION)  # noqa: E731
    return {"sizing_module_sha256": digest, "power": POWER, "alpha": ALPHA / FAMILY, "attrition": ATTRITION,
            "P1_two_plays": [need(62, 40), need(73, 40)], "P2": need(140.6, 100), "P3": [need(69, 40), need(70, 40)]}


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["analyze", "sizing"])
    parser.add_argument("out", type=Path, nargs="?")
    parser.add_argument("--if", dest="if_dir", type=Path)
    parser.add_argument("--hh", type=Path)
    parser.add_argument("--cf", type=Path)
    parser.add_argument("--pack", default=pv2.ADMITTED.pack, choices=sorted(pv2.SPECS))
    args = parser.parse_args(argv)
    result = sizing() if args.command == "sizing" else analyze(args.if_dir, args.hh, args.cf, pack=args.pack)
    text = json.dumps(result, indent=1, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text)
    json.dump(result if args.command == "sizing" else result["primary"], sys.stdout, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
