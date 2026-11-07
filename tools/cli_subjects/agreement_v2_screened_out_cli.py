"""The v2 addendum's campaigns: arm IF on the 14 worlds the headroom screen dropped, one campaign a subject.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_v2_screened_out_cli.py dry-run runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_v2_screened_out_cli.py freeze  runs/<dir> --arm opus
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_v2_screened_out_cli.py run     runs/<dir>
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_v2_screened_out_cli.py verify  runs/<dir>

Declared in ``docs/families/datacenter/agreement_v2_screened_out_addendum.md``. This module edits no hashed source: it
registers the pack and arms on :mod:`agreement_confirmatory_v2_cli` and runs that driver, so the cell runner, isolation
probes, stops, typed missingness and replay are v2's. A freeze requires the addendum to be committed.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from typing import Any

import agreement_confirmatory_v2_cli as d

PACK = "agreement_v2_screened_out_v1"
PACK_SHA256 = "76d41ec647f8b01d70bb3ca3fe0e23854110beeb6a301ae13890de1df08384b5"
ADDENDUM = "docs/families/datacenter/agreement_v2_screened_out_addendum.md"
ANALYSIS = "tools/cli_subjects/agreement_v2_screened_out_analysis.py"
#: Each subject's measured list price a negotiation on v2 arm IF (tables/cells.jsonl), and the pilot's one slot-minute.
RATES = {"opus": 13.40 / 160, "sol": 6.95 / 160}
SLOT_MINUTES = 79.9 * 4 / 320
PARALLEL = 4
CLAIM = "declared addendum to the v2 confirmatory: a sensitivity beside its primaries, which stand as sealed"

opus, sol = (f"{n}_integrator__negotiator_{d.PUBLIC}_client" for n in ("claude", "codex"))
d.ARMS.update({
    "opus": d.Arm("opus", "datacenter_agreement_v2_screened_out_opus", PACK, (opus,), 2, PARALLEL, "firm", "addendum: Opus's half of A2 and A3"),
    "sol": d.Arm("sol", "datacenter_agreement_v2_screened_out_sol", PACK, (sol,), 2, PARALLEL, "firm", "addendum: Sol's half of A1 and A3"),
    "dry": d.Arm("dry", "datacenter_agreement_v2_screened_out_dry", PACK, d.DRY_PAIRINGS, 1, 8, "scripted", "control: scripted pairs on the 14 worlds, no model"),
})
d.PACK_SHA256[PACK] = PACK_SHA256
d.SOURCES = (*d.SOURCES, "tools/cli_subjects/agreement_v2_screened_out_cli.py", "tools/cli_subjects/agreement_v2_screened_out_pack.py", ANALYSIS)
d.PLAN_DOC = ADDENDUM


def addendum_commit() -> str:
    head = subprocess.run(["git", "-C", str(d.REPOSITORY_ROOT), "log", "-1", "--format=%H", "--", ADDENDUM], capture_output=True, text=True, check=True)
    if not head.stdout.strip():
        raise SystemExit("the addendum is not committed; declare it before freezing")
    return head.stdout.strip()


_base_estimate, _base_plan_for = d.v1_estimate, d.plan_for


def estimate(arm: d.Arm) -> dict[str, float]:
    if arm.kind == "scripted":
        return _base_estimate(arm)
    return {"list_usd": round(RATES[arm.name] * arm.negotiations, 2), "wall_minutes": round(SLOT_MINUTES * arm.negotiations / arm.parallel, 1),
            "source": "each subject's measured rate on v2 arm IF"}


def plan_for(arm: d.Arm, *args: Any, **kwargs: Any) -> dict[str, Any]:
    plan = _base_plan_for(arm, *args, **kwargs)
    plan.pop("plan_sha256")
    plan.update(claim_status=CLAIM if arm.kind == "firm" else "control: no model", declared_analysis=f"{ADDENDUM}, Section 4; {ANALYSIS}")
    plan["plan_sha256"] = hashlib.sha256(d.canonical_json_bytes(plan)).hexdigest()
    return plan


d.v1_estimate, d.plan_for = estimate, plan_for
d.PLAN_COMMITS = (*d.PLAN_COMMITS, addendum_commit())

if __name__ == "__main__":
    sys.exit(d.main())
