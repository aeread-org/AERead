"""What each subject gave up, action by action, on pay or test version 2, and the contrasts its plan declares.

    PYTHONPATH=src python tools/cli_subjects/pay_or_test_v2_report.py <runs/procurement_allocation> \\
        --panel gate|pilot|confirmatory [--json out.json] [--design-src <copy of src/aeread/design>]

The primary number is decision loss, as in version 1 (``pay_or_test_report``):
for every action a subject took, the best informed policy's value at that point
less the value of the action, summed over the episode, here priced by
``pay_or_test_v2_reference.score_actions``. A world's value is the mean over
its completed plays. A rejected or malformed action ends the episode and is
priced as walking away from the state the executed actions reached.

The declared contrasts
(``docs/families/procurement-allocation/pay_or_test_v2_confirmatory_plan.md``):

- ``P1-<subject>``: the subject's loss less the one-step rule's exact expected
  loss on the same world (``rule_loss_usd.one_step_value`` in the pack);
- ``P2``: Gemini 3.8 Flash's loss less GPT-6 Luna's, paired by world.

Each is a paired t on world values, two-sided, Holm across the three at a
familywise 0.05, with its interval at 95% and at its Holm step's level. A
contrast that loses more than 5% of its worlds to missingness is reported as
not confirmatory. On the pilot the same differences are split into a
world-to-world and a play-to-play variance, the SD of a world's difference at
the planned number of plays is computed with ``aeread.design.sd_of_differences``,
and the largest is sized with ``aeread.design.worlds_needed`` and sealed with
``aeread.design.sizing_record``. ``aeread.design`` is on an unmerged branch
(``codex/methods-design``, 159cba3c); pass ``--design-src`` pointing at a copy
of its ``src/aeread/design`` if the package is not importable.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from scipy import stats

from aeread_families.procurement_allocation import pay_or_test_v2_case_matrix as pack_module
from aeread_families.procurement_allocation.environment import ACTION_FIELDS
from aeread_families.procurement_allocation.pay_or_test_reference import _describe, run as replay
from aeread_families.procurement_allocation.pay_or_test_v2_reference import Reference, score_actions

SMALL_USD = 1.0
ALPHA = 0.05
MINIMUM_EFFECT_USD = 10.0
MISSING_SHARE_LIMIT = 0.05
PLANNED_PLAYS = 2
POWER = 0.8
ATTRITION = 0.05
#: Run-root prefix and suffix of each panel (``pay_or_test_v2_openrouter.campaign_id`` less the family prefix).
PREFIX = "pay_or_test_v2_shared_source_openrouter_"
SUBJECTS = ("gemini38_flash", "gpt6_luna")
PARTS = ("requests", "strays", "walk_away", "award_timing", "award_terms")
#: Rules the plan reports beside the subjects: the contrast rule, always paying, and the two-test lookahead.
RULES_BESIDE = ("one_step_value", "pay_premium", "two_step_value")


def load_pack(pack_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    root = pack_module.pack_root(pack_id)
    manifest = json.loads((root / "pack.json").read_text(encoding="utf-8"))
    payloads = {}
    for path in pack_module.case_paths(split=pack_id):
        case = json.loads(path.read_text(encoding="utf-8"))
        payloads[case["case_id"]] = case["payload"]
    return manifest, payloads


def as_parsed(step: Mapping[str, Any]) -> dict[str, Any]:
    """A trace step reduced to the fields its action takes, as the family parser reduces it (version 1's rule)."""
    fields = ACTION_FIELDS.get(step.get("action"))
    if fields is None:
        return dict(step)
    return {k: v for k, v in step.items() if k in fields or k in ("ordinal", "status")}


def score_trace(payload: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[dict[str, Any], float]:
    """``score_actions`` on one completed row, and the margin its replay gives (version 1's ``score_trace``, v2 reference)."""
    trace = [as_parsed(step) for step in row["action_trace"]]
    rejected = [i for i, step in enumerate(trace) if step.get("status") != "succeeded"]
    if not rejected:
        scored = score_actions(payload, trace)
        if scored["outcome"] is None:
            raise RuntimeError(f"replay of {row['case_id']} did not end the episode (termination {row.get('termination_reason')})")
        return scored, float(scored["outcome"]["contribution_margin_usd"])
    if rejected != [len(trace) - 1] or row.get("termination_reason") != "invalid_action":
        raise RuntimeError(f"{row['case_id']}: rejected steps {rejected} of {len(trace)} with termination "
                           f"{row.get('termination_reason')!r}; only a rejected last step that ended the episode is scored")
    executed = trace[:-1]
    scored = score_actions(payload, executed)
    ref = Reference(payload)
    state = replay(payload, executed)
    if state["done"]:
        raise RuntimeError(f"{row['case_id']}: the episode ended before the rejected step")
    status, left, day = ref.status_of(state), ref.max_actions - state["actions_used"], state["elapsed_days"]
    best = ref.value(status, left, day)
    lost = best - ref.defer_value
    step = {"action": trace[-1].get("action"), "supplier_id": trace[-1].get("supplier_id"), "day": day, "actions_left": left,
            "best_value_usd": round(best, 4), "best_action": _describe(ref, ref.best_action(status, left, day)),
            "value_taken_usd": round(ref.defer_value, 4), "loss_usd": round(lost, 4), "valid": False, "rejected": True}
    parts = dict(scored["loss_by_part_usd"])
    parts["walk_away"] = round(parts["walk_away"] + lost, 4)
    scored = {**scored, "steps": [*scored["steps"], step], "loss_by_part_usd": parts,
              "decision_loss_usd": round(scored["decision_loss_usd"] + lost, 4), "outcome": None}
    return scored, ref.defer_value - float(state["information_cost_usd"])


def probe_of(world: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], awarded: str | None) -> bool:
    """The plan's probe: the first sample is on a newcomer, of a kind with a dearer sample, that the play does not award."""
    samples = [s["supplier_id"] for s in steps if s["action"] == "request_sample" and not s.get("rejected")]
    newcomers = {n["supplier_id"]: n for n in world["newcomers"]}
    if not samples or samples[0] not in newcomers:
        return False
    first = newcomers[samples[0]]
    dearer = any(n["kind"] == first["kind"] and n["sample_fee_usd"] > first["sample_fee_usd"]
                 for sid, n in newcomers.items() if sid != samples[0])
    return dearer and awarded != samples[0]


def _awarded(row: Mapping[str, Any]) -> str | None:
    for step in row["action_trace"]:
        if step.get("action") == "submit_award" and step.get("status") == "succeeded":
            line = (step.get("award_lines") or [{}])[0]
            offer = str(line.get("offer_id") or "")
            return offer.removeprefix("offer_").rsplit("_v", 1)[0] or None
    return None


def score_run(root: Path, manifest: Mapping[str, Any], payloads: Mapping[str, Any]) -> dict[str, Any]:
    """Every play of one run root, priced; failed cells listed by world and seed."""
    artifact = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    by_case = {w["case_id"]: w for w in manifest["worlds"]}
    plays, failed = [], []
    for row in artifact["rows"]:
        world = by_case[row["case_id"]]
        seed = int(row["inference_seed"])
        if row.get("status") != "completed":
            failed.append({"slug": world["slug"], "inference_seed": seed,
                           "failure": row.get("failure_condition") or row.get("error_type")})
            continue
        scored, replayed = score_trace(payloads[row["case_id"]], row)
        if abs(replayed - float(row["contribution_margin_usd"])) > 1e-6:
            raise RuntimeError(f"replay of {world['slug']} seed {seed} in {root.name} gives {replayed}, "
                               f"the run recorded {row['contribution_margin_usd']}")
        executed = [s for s in scored["steps"] if not s.get("rejected")]
        newcomers = {n["supplier_id"] for n in world["newcomers"]}
        plays.append({
            "slug": world["slug"], "kind": world["kind"], "clock": world["clock"], "inference_seed": seed,
            "decision_loss_usd": scored["decision_loss_usd"],
            **{f"loss_{k}_usd": v for k, v in scored["loss_by_part_usd"].items()},
            "margin_usd": replayed, "best_policy_value_usd": world["best_policy_value_usd"],
            "decision": row["decision"], "feasible_award": bool(row["feasible_award"]),
            "actions": len(scored["steps"]), "requests": scored["requests"],
            "newcomers_touched": len({s["supplier_id"] for s in executed if s["supplier_id"] in newcomers}),
            "probe": probe_of(world, scored["steps"], _awarded(row)),
            "rejected_action": next((s["action"] for s in scored["steps"] if s.get("rejected")), None),
            "trace": " ".join(_short(s) for s in scored["steps"]),
            "cost_usd": float(row.get("cost_usd") or 0.0), "seconds": float(row.get("elapsed_seconds") or 0.0),
        })
    return {"campaign_id": artifact["plan"]["campaign_id"], "model": artifact["plan"]["model"],
            "halted": artifact.get("halted"), "planned": artifact["plan"]["planned_trajectory_count"],
            "plays": plays, "failed": failed,
            "cost_usd": round(sum(float(r.get("cost_usd") or 0.0) for r in artifact["rows"]
                                  if isinstance(r.get("cost_usd"), (int, float))), 4)}


def _short(step: Mapping[str, Any]) -> str:
    code = {"request_quote": "q", "request_sample": "s", "submit_award": "AWARD", "defer": "DEFER", "inquire": "inq",
            "counter_offer": "ctr", "check_award": "chk"}.get(step["action"], str(step["action"]))
    who = (step["supplier_id"] or "").rsplit("_", 1)[-1]
    lost = f"(-{step['loss_usd']:.0f})" if step["loss_usd"] >= SMALL_USD else ""
    return f"{code}{':' + who if who else ''}{'[REJECTED]' if step.get('rejected') else ''}{lost}"


def world_values(run: Mapping[str, Any], key: str = "decision_loss_usd") -> dict[str, float]:
    """Each world's mean over its completed plays."""
    by_world: dict[str, list[float]] = {}
    for play in run["plays"]:
        by_world.setdefault(play["slug"], []).append(float(play[key]))
    return {slug: statistics.fmean(values) for slug, values in by_world.items()}


def plays_by_world(run: Mapping[str, Any]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for play in run["plays"]:
        out.setdefault(play["slug"], {})[int(play["inference_seed"])] = float(play["decision_loss_usd"])
    return out


def paired_t(differences: Sequence[float], levels: Sequence[float]) -> dict[str, Any]:
    """Mean, SD, two-sided p and t intervals at each level (``1 - alpha``) for paired world differences."""
    n = len(differences)
    mean = statistics.fmean(differences)
    sd = statistics.stdev(differences) if n > 1 else float("nan")
    se = sd / math.sqrt(n) if n > 1 else float("nan")
    t = mean / se if se and se > 0 else (0.0 if mean == 0 else math.copysign(math.inf, mean))
    p = float(2 * stats.t.sf(abs(t), n - 1)) if n > 1 else float("nan")
    intervals = {}
    for level in levels:
        half = float(stats.t.ppf(1 - (1 - level) / 2, n - 1)) * se
        intervals[f"{level:.4f}"] = [round(mean - half, 2), round(mean + half, 2)]
    return {"n_worlds": n, "mean_usd": round(mean, 2), "sd_usd": round(sd, 2), "t": round(t, 3), "p": p,
            "intervals_usd": intervals}


def holm(pvalues: Mapping[str, float], alpha: float = ALPHA) -> dict[str, dict[str, Any]]:
    """Holm's step-down: adjusted p, the level each contrast is tested at, and whether it rejects."""
    order = sorted(pvalues, key=lambda k: pvalues[k])
    m = len(order)
    out: dict[str, dict[str, Any]] = {}
    running, still = 0.0, True
    for rank, name in enumerate(order):
        level = alpha / (m - rank)
        running = max(running, min(1.0, (m - rank) * pvalues[name]))
        still = still and pvalues[name] <= level
        out[name] = {"holm_step": rank + 1, "holm_alpha": level, "holm_p": running, "rejects": still}
    return out


def contrasts(runs: Mapping[str, Mapping[str, Any]], manifest: Mapping[str, Any]) -> dict[str, Any]:
    """The plan's three contrasts on the worlds each can use, Holm-corrected together."""
    all_worlds = [w["slug"] for w in manifest["worlds"]]
    rule_loss = {w["slug"]: float(w["rule_loss_usd"]["one_step_value"]) for w in manifest["worlds"]}
    differences: dict[str, dict[str, float]] = {}
    for subject in SUBJECTS:
        if subject in runs:
            values = world_values(runs[subject])
            differences[f"P1-{subject}"] = {s: values[s] - rule_loss[s] for s in all_worlds if s in values}
    if all(subject in runs for subject in SUBJECTS):
        a, b = (world_values(runs[s]) for s in SUBJECTS)
        differences["P2"] = {s: a[s] - b[s] for s in all_worlds if s in a and s in b}
    tested = {name: d for name, d in differences.items() if len(d) > 1}
    rows: dict[str, Any] = {}
    p_values = {}
    for name, d in tested.items():
        values = [d[s] for s in all_worlds if s in d]
        p_values[name] = paired_t(values, [0.95])["p"]
    corrected = holm(p_values) if p_values else {}
    for name, d in differences.items():
        values = [d[s] for s in all_worlds if s in d]
        lost = [s for s in all_worlds if s not in d]
        levels = [0.95] + ([1 - corrected[name]["holm_alpha"]] if name in corrected else [])
        result = paired_t(values, levels) if len(values) > 1 else {"n_worlds": len(values)}
        missing_share = len(lost) / len(all_worlds)
        rows[name] = {**result, **corrected.get(name, {}), "worlds_missing": lost,
                      "missing_share": round(missing_share, 4),
                      "confirmatory": missing_share <= MISSING_SHARE_LIMIT,
                      "meaningful_effect_usd": MINIMUM_EFFECT_USD}
    return rows


def _design(name: str, design_src: Path | None) -> Any:
    try:
        return importlib.import_module(f"aeread.design.{name}")
    except ImportError:
        if design_src is None:
            raise
        spec = importlib.util.spec_from_file_location(f"aeread_design_copy_{name}", design_src / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


def variance(runs: Mapping[str, Mapping[str, Any]], manifest: Mapping[str, Any], *, design_src: Path | None,
             pilot_source: str) -> dict[str, Any]:
    """World and play components of each contrast's per-play difference, the SD at the planned plays, and the sizing."""
    sizing = _design("sizing", design_src)
    rule_loss = {w["slug"]: float(w["rule_loss_usd"]["one_step_value"]) for w in manifest["worlds"]}
    per_play: dict[str, dict[str, dict[int, float]]] = {}
    for subject in SUBJECTS:
        if subject in runs:
            per_play[f"P1-{subject}"] = {s: {k: v - rule_loss[s] for k, v in plays.items()}
                                         for s, plays in plays_by_world(runs[subject]).items()}
    if all(subject in runs for subject in SUBJECTS):
        a, b = (plays_by_world(runs[s]) for s in SUBJECTS)
        per_play["P2"] = {s: {k: a[s][k] - b[s][k] for k in a[s] if k in b[s]} for s in a if s in b}
    out: dict[str, Any] = {}
    for name, worlds in per_play.items():
        complete = {s: v for s, v in worlds.items() if len(v) >= PLANNED_PLAYS}
        if len(complete) < 2:
            out[name] = {"worlds_with_both_plays": len(complete)}
            continue
        plays = PLANNED_PLAYS
        within = statistics.fmean(statistics.variance(list(v.values())[:plays]) for v in complete.values())
        means = [statistics.fmean(list(v.values())[:plays]) for v in complete.values()]
        var_world = max(0.0, statistics.variance(means) - within / plays)
        out[name] = {"worlds_with_both_plays": len(complete), "var_world": round(var_world, 4),
                     "var_play": round(within, 4),
                     "sd_of_differences_at_planned_plays": round(sizing.sd_of_differences(var_world, within, plays), 4),
                     "sd_of_world_means": round(statistics.stdev(means), 4),
                     "mean_difference_usd": round(statistics.fmean(means), 2)}
    usable = {k: v for k, v in out.items() if "sd_of_differences_at_planned_plays" in v}
    if usable:
        largest = max(usable, key=lambda k: usable[k]["sd_of_differences_at_planned_plays"])
        sd = usable[largest]["sd_of_differences_at_planned_plays"]
        alpha = ALPHA / 3
        record = sizing.sizing_record(sd_of_differences=sd, minimum_effect=MINIMUM_EFFECT_USD,
                                      pilot_worlds=usable[largest]["worlds_with_both_plays"], pilot_source=pilot_source,
                                      power=POWER, alpha=alpha, attrition=ATTRITION)
        worlds = record["worlds"]
        decision = ("the committed 24, twice each" if worlds <= 24 else
                    f"a fresh confirmatory pack of {4 * math.ceil(worlds / 4)} worlds" if worlds <= 96 else
                    "no confirmatory run: the plan is revised")
        out["sizing"] = {"largest_contrast": largest, "sd_used": sd, "alpha": alpha, "power": POWER,
                         "attrition": ATTRITION, "worlds_needed": worlds, "decision": decision, "record": record,
                         "smallest_effect_at_24_worlds_usd": round(sizing.smallest_detectable_effect(
                             sd, 24, power=POWER, alpha=alpha), 2)}
    return out


def summarize(run: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    plays = run["plays"]
    worlds = {w["slug"]: w for w in manifest["worlds"]}
    values = world_values(run)
    loss = list(values.values())
    by_cell: dict[str, Any] = {}
    for kind, clock in pack_module.CELLS:
        mine = [s for s in values if (worlds[s]["kind"], worlds[s]["clock"]) == (kind, clock)]
        if mine:
            by_cell[f"{kind}/{clock}"] = {"worlds": len(mine), "decision_loss_usd": round(statistics.fmean(values[s] for s in mine), 2)}
    for label, key in (("by_kind", "kind"), ("by_clock", "clock")):
        groups: dict[str, list[float]] = {}
        for s, v in values.items():
            groups.setdefault(worlds[s][key], []).append(v)
        by_cell[label] = {k: round(statistics.fmean(v), 2) for k, v in sorted(groups.items())}
    rules = {}
    for rule in RULES_BESIDE:
        d = [values[s] - float(worlds[s]["rule_loss_usd"][rule]) for s in values]
        rules[f"subject_less_{rule}_usd"] = {"rule_loss_usd": round(statistics.fmean(float(worlds[s]["rule_loss_usd"][rule]) for s in values), 2),
                                             "mean_difference_usd": round(statistics.fmean(d), 2)}
    probe_worlds = {p["slug"] for p in plays if p["probe"]}
    return {
        "campaign_id": run["campaign_id"], "model": run["model"], "halted": run["halted"],
        "plays": len(plays), "planned_plays": run["planned"], "failed_cells": len(run["failed"]),
        "worlds": len(values),
        "decision_loss_usd": {"mean": round(statistics.fmean(loss), 2),
                              "sd": round(statistics.stdev(loss), 2) if len(loss) > 1 else None},
        "worlds_with_no_loss": sum(v < SMALL_USD for v in loss),
        "loss_by_part_usd": {part: round(statistics.fmean(statistics.fmean(p[f"loss_{part}_usd"] for p in plays if p["slug"] == s)
                                                          for s in values), 2) for part in PARTS},
        "share_of_best_policy_value": round(1.0 - sum(loss) / sum(worlds[s]["best_policy_value_usd"] for s in values), 4),
        "probe_rate": {"worlds": len(probe_worlds), "of": len(values), "plays": sum(p["probe"] for p in plays)},
        "rejected_actions": dict(sorted(Counter(p["rejected_action"] for p in plays if p["rejected_action"]).items())),
        "no_supply_plays": sum(not p["feasible_award"] for p in plays),
        "by_cell": by_cell,
        "beside_rules": rules,
        "cost_usd": run["cost_usd"],
        "seconds_per_play": round(statistics.fmean(p["seconds"] for p in plays), 1) if plays else None,
    }


def report(runs_dir: Path, panel: str, *, design_src: Path | None = None) -> dict[str, Any]:
    roots = {s: runs_dir / f"{PREFIX}{s}_{panel}_v1" for s in SUBJECTS}
    roots = {s: r for s, r in roots.items() if (r / "summary.json").exists()}
    if not roots:
        raise FileNotFoundError(f"no {panel} run root with a summary under {runs_dir}")
    plans = {s: json.loads((r / "model_plan.json").read_text(encoding="utf-8")) for s, r in roots.items()}
    packs = {p["pack"] for p in plans.values()}
    if len(packs) != 1:
        raise ValueError(f"the {panel} runs played different packs: {sorted(packs)}")
    manifest, payloads = load_pack(packs.pop())
    runs = {s: score_run(r, manifest, payloads) for s, r in roots.items()}
    out: dict[str, Any] = {"panel": panel, "pack": manifest["pack_id"], "world_count": manifest["world_count"],
                           "subjects": {s: summarize(run, manifest) for s, run in runs.items() if run["plays"]},
                           "failed": {s: run["failed"] for s, run in runs.items()},
                           "cost_usd": round(sum(run["cost_usd"] for run in runs.values()), 4)}
    if panel != "gate":
        out["contrasts"] = contrasts(runs, manifest)
    if panel == "pilot":
        source = ", ".join(sorted(r.name for r in roots.values()))
        out["variance"] = variance(runs, manifest, design_src=design_src, pilot_source=source)
    out["plays"] = {s: [{k: p[k] for k in ("slug", "inference_seed", "decision_loss_usd", "margin_usd", "probe", "trace")}
                        for p in run["plays"]] for s, run in runs.items()}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--panel", choices=("gate", "pilot", "confirmatory"), required=True)
    parser.add_argument("--design-src", type=Path, help="a copy of src/aeread/design from codex/methods-design")
    parser.add_argument("--json", type=Path)
    arguments = parser.parse_args(argv)
    out = report(arguments.runs, arguments.panel, design_src=arguments.design_src)
    text = json.dumps(out, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in out.items() if k != "plays"}, indent=1, sort_keys=True))
    for subject, plays in out["plays"].items():
        print(subject)
        for p in plays:
            print(f"  {p['slug']:26s} seed {p['inference_seed']}  loss {p['decision_loss_usd']:7.1f}  "
                  f"margin {p['margin_usd']:7.1f}  {'probe ' if p['probe'] else ''}{p['trace']}")
    if arguments.json:
        arguments.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
