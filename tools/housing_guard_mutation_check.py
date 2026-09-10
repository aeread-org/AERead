"""Break each new guard one at a time and report whether the suite notices."""
import subprocess, sys
from pathlib import Path

MS = "src/aeread_families/housing/model_sensitivity.py"
BC = "src/aeread_families/housing/backend_campaign.py"
BP = "src/aeread_families/housing/backend_publication.py"

MUTANTS = [
  ("missingness ceiling never fires", MS,
   "        and failure_fraction > float(missingness_ceiling) + 1e-12",
   "        and False"),
  ("freeze skips the estimable check", BC,
   '    if analysis is None or analysis.get("status") != "estimable":',
   "    if False:"),
  ("freeze accepts an undersized panel", BC,
   "    if planned_worlds < recommended:",
   "    if False:"),
  ("freeze ignores the pilot digest", BC,
   '    if pilot_qualification["artifact_sha256"] != pilot["qualification_artifact_sha256"]:',
   "    if False:"),
  ("freeze accepts a withheld recommendation", BC,
   "    if recommended is None:",
   "    if False:"),
  ("panel skips exclusion justification", MS,
   "        if not any(",
   "        if False and not any("),
  ("panel accepts seeds unlike the sweep", MS,
   '    if panel["world_seeds"] != holdout["world_seeds"]:',
   "    if False:"),
  ("panel accepts development overlap", MS,
   "    if development & set(panel[\"world_seeds\"]):",
   "    if False:"),
  ("paired means count incomplete worlds", MS,
   "            subject_counts[subject] = len(eligible)\n            if len(eligible) == expected_per_subject:\n                subject_means[subject] = statistics.fmean(\n                    float(row[\"within_case_score\"]) for row in eligible\n                )\n        complete_pair = len(subject_means) == 2\n        contrast = (\n            subject_means[\"glm_53_flash\"] - subject_means[\"deepseek_v4_flash\"]",
   "            subject_counts[subject] = len(eligible)\n            if eligible:\n                subject_means[subject] = statistics.fmean(\n                    float(row[\"within_case_score\"]) for row in eligible\n                )\n        complete_pair = len(subject_means) == 2\n        contrast = (\n            subject_means[\"glm_53_flash\"] - subject_means[\"deepseek_v4_flash\"]"),
  ("analysis always allows ranking", MS,
   "    decision_supported = bool(\n        minimum_paired is not None",
   "    decision_supported = bool(\n        True or minimum_paired is not None"),
  ("identity snapshot leaks health", BC,
   '    if policy == "full":\n        snapshot["status"] = endpoint.get("status")',
   '    snapshot["status"] = endpoint.get("status")'),
  ("preflight ignores the status policy", BC,
   '        if route_status != 0 and route_status_policy == "require_active":',
   "        if False:"),
  ("publisher accepts a missing freeze", BP,
   "    if not freeze_path.exists():",
   "    if False:"),
  ("publisher ignores a post-freeze contract edit", BP,
   '    if freeze["contract_sha256"] != contract_sha256:',
   "    if False:"),
  ("concurrency batches ignore the cost reserve", MS,
   "        if cost_so_far + reserve > execution_contract[\"cost_ceiling_usd\"]:",
   "        if False:"),
  ("batch reserve ignores batch size", MS,
   '        reserve = execution_contract["per_trajectory_cost_reserve_usd"] * len(batch)',
   '        reserve = 0.0'),
  ("concurrency cap is not enforced", "src/aeread_families/housing/provider_concurrency.py",
   "        if set(limits) != set(intervals) or any(",
   "        if False and any("),
  ("admission retries a non-retryable failure", BC,
   "                    failure_condition in retryable_conditions",
   "                    True"),
]

TESTS = ["tests/test_housing_backend_campaign.py", "tests/test_housing_model_sensitivity.py",
         "tests/test_source_layout.py"]

caught, missed = [], []
for name, rel, old, new in MUTANTS:
    path = Path(rel); original = path.read_text()
    if original.count(old) != 1:
        missed.append((name, f"anchor not unique ({original.count(old)})")); continue
    path.write_text(original.replace(old, new, 1))
    try:
        r = subprocess.run([".venv/bin/python", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *TESTS],
                           capture_output=True, text=True, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
        (caught if r.returncode != 0 else missed).append((name, "detected" if r.returncode != 0 else "NOT DETECTED"))
    finally:
        path.write_text(original)

print("=== guards the suite catches ===")
for n, _ in caught: print("  OK  ", n)
print("=== guards the suite MISSES ===")
for n, why in missed: print("  GAP ", n, "|", why)
print(f"\n{len(caught)} caught, {len(missed)} missed, of {len(MUTANTS)}")
