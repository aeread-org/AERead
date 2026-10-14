"""Table 5.2, last row of each block: each model minus the scripted inspect-then-sign tenant, paired by world.

Reads only published tables on branch codex/housing-lemons-outside-demand:
  evidence/housing/housing_lemons_price_v14_controls/tables/cells.jsonl        (the controls, offline)
  evidence/housing/housing_lemons_price_v14_reply_conditioned/tables/cells.jsonl (the models, both measures)
Run: AEREAD_HOUSING_ROOT=<checkout> python housing_controls_v14.py
The declared-measure values reproduce `beatability_main_pack_primary_v1` in the controls bundle.
"""
import json
import os
import statistics as st
from collections import defaultdict
from pathlib import Path

from scipy import stats

EV = Path(os.environ["AEREAD_HOUSING_ROOT"]) / "evidence/housing"
CONTROL = "inspect_then_sign"


def interval(xs):
    n, m = len(xs), st.mean(xs)
    h = stats.t.ppf(0.975, n - 1) * st.stdev(xs) / n ** 0.5
    return {"n": n, "mean": round(m, 2), "lo": round(m - h, 2), "hi": round(m + h, 2)}


controls = {}
for line in open(EV / "housing_lemons_price_v14_controls/tables/cells.jsonl"):
    row = json.loads(line)
    if row["population"] == "main":
        controls[(row["world_seed"], row["arm"])] = row
models = defaultdict(dict)
for line in open(EV / "housing_lemons_price_v14_reply_conditioned/tables/cells.jsonl"):
    row = json.loads(line)
    if not row["campaign_id"].endswith("_fill"):
        models[row["campaign_id"]][(row["world_seed"], row["arm"])] = row
worlds = sorted({w for w, _ in controls})
out = {}
for campaign, cells in sorted(models.items()):
    for measure in ("primary_v1", "primary_v2"):
        diffs = [
            sum(cells[(w, a)][measure] - controls[(w, a)][CONTROL][measure] for a in ("pooled", "true_cost")) / 2
            for w in worlds
            if (w, "pooled") in cells and (w, "true_cost") in cells
        ]
        out.setdefault(campaign, {})[measure] = interval(diffs)
print(json.dumps(out, indent=1, sort_keys=True))
