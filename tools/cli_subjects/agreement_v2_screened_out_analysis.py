"""The v2 addendum's declared analysis: A1, A2 and A3 over 86 deal worlds, and each contrast on the 14 and the 72.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_v2_screened_out_analysis.py \\
        --opus runs/<opus> [--sol runs/<sol>] OUT.json

Declared in ``docs/families/datacenter/agreement_v2_screened_out_addendum.md``, Section 4. Earnings come from the sealed
receipts through v1's reader; the 72 worlds' values are read from the published v2 analysis, unchanged. Without Sol's run
only A2 is computed. Holm runs across the contrasts computed and v2's published P2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import agreement_confirmatory_analysis as v1a
import agreement_confirmatory_v2_analysis as v2a
from aeread_families.datacenter_development import agreement_pack as ap

PACK = "agreement_v2_screened_out_v1"
PUBLISHED = v2a.REPOSITORY_ROOT / "evidence/datacenter_development/agreement_confirmatory_v2_analysis/reports/analysis.json"
PLAYS = 2


def summary(values: Mapping[str, float]) -> dict[str, Any]:
    xs = list(values.values())
    out = v1a.t_summary(xs, v2a.ALPHAS) if len(xs) > 1 else {"n": len(xs), "mean": None, "p": 1.0}
    return {**out, "worlds": len(xs)}


def holm(results: Sequence[dict[str, Any]], alpha: float = 0.05) -> None:
    ranked = sorted(results, key=lambda r: r["p"])
    still = True
    for step, r in enumerate(ranked):
        r["holm_alpha"] = alpha / (len(ranked) - step)
        still = still and r["p"] <= r["holm_alpha"]
        r["rejected"] = still


def analyze(opus_dir: Path, sol_dir: Path | None) -> dict[str, Any]:
    manifest, _ = ap.load(PACK)
    meta = {w["case_id"].rsplit(".", 1)[-1]: w for w in manifest["worlds"]}
    rule = {w: m["integrator_headroom"]["rule"] for w, m in meta.items()}
    published = {r["contrast"]: r for r in json.loads(PUBLISHED.read_text())["primary"]}
    runs = {"claude": v1a.index(v1a.load(opus_dir))}
    if sol_dir is not None:
        runs["codex"] = v1a.index(v1a.load(sol_dir))
    earn = {m: {w: v2a.play_mean(c, v2a.if_pairing(m), w, "integrator", PLAYS) for w in meta} for m, c in runs.items()}
    wanted: dict[str, tuple[str, Any]] = {"A2": ("P3b", lambda w: None if earn["claude"][w] is None else earn["claude"][w] - rule[w])}
    if "codex" in earn:
        wanted["A1"] = ("P3a", lambda w: None if earn["codex"][w] is None else earn["codex"][w] - rule[w])
        wanted["A3"] = ("P1", lambda w: None if earn["codex"][w] is None or earn["claude"][w] is None else earn["codex"][w] - earn["claude"][w])
    results = []
    for name, (source, value) in wanted.items():
        new = {w: value(w) for w in meta}
        played = {w: v for w, v in new.items() if v is not None}
        old = published[source]["world_values"]
        results.append({"contrast": name, "source": source, "minimum_effect": v2a.EFFECTS[source], **summary({**old, **played}),
                        "on_14": summary(played), "on_72": summary(old), "worlds_missing": sorted(set(new) - set(played)),
                        "world_values_14": {w: round(v, 3) for w, v in played.items()}})
    family = [*results, {"contrast": "P2", "p": published["P2"]["p"], "carried": True}]
    holm(family)
    return {"pack": PACK, "plan": "docs/families/datacenter/agreement_v2_screened_out_addendum.md", "contrasts": results,
            "holm_family": [{k: r.get(k) for k in ("contrast", "p", "holm_alpha", "rejected")} for r in family],
            "complete": "codex" in earn, "subject_mean_earnings_14": {m: v1a.t_summary([v for v in e.values() if v is not None], v2a.ALPHAS)["mean"] for m, e in earn.items()},
            "rule_mean_14": sum(rule.values()) / len(rule)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--opus", type=Path, required=True)
    parser.add_argument("--sol", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    result = analyze(args.opus, args.sol)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("holm_family", "complete", "subject_mean_earnings_14", "rule_mean_14")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
