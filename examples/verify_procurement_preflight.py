"""Independent numerical checks for the procurement readiness/preflight reports.

Run without arguments for planning arithmetic. Add --evidence-root to cross-check
the completed provider-free 600-cell bundle directly against its sealed receipts.
This is verification code: it makes no model calls and writes no artifacts.
"""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from scipy import optimize, stats

from aeread.shared_runner.receipts import read_evaluation_receipt


WORLDS, CONDITIONS, REPEATS = 100, 2, 3
ALPHA, POWER = .05, .80
SMOKE_COST = .01016025
EXPECTED_COMPLETE = {.3: 90, .4: 52, .5: 34}
EXPECTED_ENROLLMENT = {.9: (100, 58, 38), .83: (109, 63, 41)}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--evidence-root", type=Path)
args = parser.parse_args()
checks = []
checks.extend([
    ("two-condition sample cells", WORLDS * CONDITIONS * REPEATS == 600),
    ("one-condition paid sample cells", WORLDS * REPEATS == 300),
    ("separate admission cells", 3 * CONDITIONS == 6),
    ("300-cell one-smoke extrapolation", math.isclose(300 * SMOKE_COST, 3.048075)),
    ("600-cell one-smoke extrapolation", math.isclose(600 * SMOKE_COST, 6.09615)),
    ("old purchase-only reference", 2000 - (50 * 10.50 + 50 * 10.52) - 2 * 5 == 939),
    ("repaired one-vendor reference", 2000 - 100 * 10.52 - 5 == 943),
])
for index, (effect, claimed) in enumerate(EXPECTED_COMPLETE.items()):
    candidates = range(2, 501)
    powers = [stats.nct.sf(stats.t.ppf(1-ALPHA/2, n-1), n-1, effect*math.sqrt(n))
              + stats.nct.cdf(-stats.t.ppf(1-ALPHA/2, n-1), n-1, effect*math.sqrt(n)) for n in candidates]
    required = next(n for n, power in zip(candidates, powers) if power >= POWER)
    checks.append((f"complete worlds at d={effect}", required == claimed))
    for retention, enrollment in EXPECTED_ENROLLMENT.items():
        checks.append((f"enrollment d={effect}, retention={retention}", math.ceil(required/retention) == enrollment[index]))
for n, claimed in ((50, .404), (100, .283), (150, .230)):
    critical = stats.t.ppf(1-ALPHA/2, n-1)
    effect = optimize.brentq(lambda d: stats.nct.sf(critical, n-1, d*math.sqrt(n))
                            + stats.nct.cdf(-critical, n-1, d*math.sqrt(n)) - POWER, .001, .6)
    checks.append((f"detectable effect with {n} worlds", abs(effect-claimed) < .0006))

if args.evidence_root:
    root = args.evidence_root / "offline"
    summary = json.loads((root / "summary.json").read_bytes())
    batch = summary["batch"]
    rows = batch["rows"]
    conditions = list(summary["conditions"])
    grouped = defaultdict(list)
    receipts = []
    buyer_calls = 0
    result_paths = list(root.glob("*/results/*.json"))
    checks.extend([
        ("600 result files", len(result_paths) == 600),
        ("600 included and no exclusions", batch["included_count"] == 600 and batch["excluded_count"] == 0),
        ("600 attempted cells", len(rows) == batch["attempted_cell_count"] == 600),
        ("100 unique worlds", len(set(summary["world_seeds"])) == 100),
        ("provider-free evidence label", summary["evidence_kind"] == "scripted_instrumentation_only"),
        ("not live admission", summary["live_admission"] is False),
        ("zero known and unknown billing", batch["known_cost_usd"] == batch["unknown_cost_provider_call_count"] == 0),
        ("zero external calls", sum(row["external_provider_call_count"] for row in rows) == 0),
    ])
    for row in rows:
        receipt = read_evaluation_receipt(root / row["receipt_path"])
        receipts.append(receipt)
        assert receipt["receipt_sha256"] == row["receipt_sha256"]
        assert receipt["paired_fields"]["world_seed"] == row["world_seed"]
        for field in ("cell_id", "run_plan_id", "cluster_id", "pair_id", "replicate_index"):
            assert receipt[field] == row[field]
        assert receipt["inclusion_status"] == "included" and receipt["replay_level"] == "state_and_score"
        score = receipt["scores"][0]
        assert math.isclose(score["metrics"]["within_case_score"]["value"], row["within_case_score"], abs_tol=1e-12)
        assert math.isclose(score["primary"]["value"], row["primary_value"], abs_tol=1e-9)
        assert score["leaf"]["verifier"]["verifier_family"] == "objective_reference"
        evidence = (root / row["receipt_path"]).parent
        for line in (evidence / "events.jsonl").read_text().splitlines():
            event = json.loads(line)
            if event["event_type"] != "provider_call_started":
                continue
            request = json.loads((evidence / event["payload_ref"]).read_bytes())["request"]
            if request["provider"] == "procurement_scripted_buyer":
                buyer_calls += 1
                assert "unit_cost" not in json.dumps(request), "supplier-private cost leaked into buyer request"
        grouped[(row["world_seed"], row["condition_id"])].append(row)
    differences = []
    for seed in summary["world_seeds"]:
        values = []
        for condition in conditions:
            group = grouped[(seed, condition)]
            assert len(group) == 3 and {row["replicate_index"] for row in group} == {0, 1, 2}
            values.append(sum(row["within_case_score"] for row in group)/3)
        differences.append(values[1]-values[0])
    analysis = summary["analysis"]["analysis"]
    checks.extend([
        ("100 complete paired clusters", len(differences) == analysis["complete_pair_world_count"] == 100),
        ("zero paired difference independently recomputed", sum(differences)/len(differences) == analysis["mean_paired_difference"] == 0),
        ("identical-policy bootstrap interval", analysis["cluster_bootstrap_95"] == [0., 0.]),
        ("identical-policy missingness interval", analysis["missingness_difference_bounds"] == [0., 0.]),
        ("all 600 receipt hashes checked", len(receipts) == 600),
        ("2400 buyer requests checked for private-cost leakage", buyer_calls == 2400),
        ("reported mean score", all(math.isclose(sum(r["within_case_score"] for r in rows if r["condition_id"] == c)/300, analysis["condition_means"][c], abs_tol=1e-12) and abs(analysis["condition_means"][c]-.9051533128) < 1e-10 for c in conditions)),
        ("reported minimum score", abs(min(r["within_case_score"] for r in rows)-.8616819202) < 1e-10),
        ("reported maximum score", abs(max(r["within_case_score"] for r in rows)-.9342829988) < 1e-10),
    ])

failures = [label for label, passed in checks if not passed]
print(json.dumps({"checks": len(checks), "passed": len(checks)-len(failures), "failed": failures}, indent=2))
if failures:
    raise SystemExit(1)
