"""The evaluation setup a published agreement v2 receipt was sealed under, for ``aeread verify-replay``.

    AEREAD_AGREEMENT_RUNS=<directory of run roots> PYTHONPATH=src:tools/cli_subjects \\
        aeread verify-replay evidence/datacenter_development/<campaign_id> \\
        --run-root <directory of run roots>/<run root> --setup agreement_v2_replay:setup_for_receipt

A receipt names its run plan, not its campaign. The candidates are the frozen campaign plans
(``campaign_plan.json``) under ``AEREAD_AGREEMENT_RUNS`` (default: the repository's gitignored ``runs/``) whose
``plan_sha256`` is the one a published bundle's ``reports/summary.json`` records, so a local plan counts only if the
publication names it. Each candidate's setup is rebuilt from current source by the v2 driver
(``agreement_confirmatory_v2_cli.build_setup``) for the receipt's pairing; the one whose plan, with the receipt's
kernel-owned pins put back (``plan_with_recorded_pins``: kernel bytes may have moved since sealing, family bytes may
not), has the receipt's digest is returned. When none matches, the error names the campaigns tried, and verify-replay
reports the row as ``differs``.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import ImplementationPin, PlanResolutionError, plan_with_recorded_pins

REPOSITORY = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY / "evidence" / "datacenter_development"


@lru_cache(maxsize=None)
def published_plan_digests() -> frozenset[str]:
    """The campaign-plan digests the published v2 bundles record."""
    digests = set()
    for path in sorted(EVIDENCE.glob("datacenter_agreement_v2_*/reports/summary.json")):
        digest = json.loads(path.read_text(encoding="utf-8")).get("plan_sha256")
        if isinstance(digest, str):
            digests.add(digest)
    return frozenset(digests)


@lru_cache(maxsize=None)
def campaign_plans() -> tuple[dict[str, Any], ...]:
    """Every frozen v2 campaign plan under the run-root directory that a published bundle names."""
    root = Path(os.environ.get("AEREAD_AGREEMENT_RUNS", REPOSITORY / "runs"))
    plans = []
    for path in sorted(root.glob("*/campaign_plan.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan.get("plan_sha256") in published_plan_digests():
            plans.append(plan)
    return tuple(plans)


def _recorded_pins(receipt: Mapping[str, Any]) -> tuple[ImplementationPin, ...]:
    """The pins the receipt was sealed under, as the kernel's audit reads them."""
    return tuple(ImplementationPin.from_dict(item) for item in receipt.get("plan_implementation_pins") or ())


def setup_for_receipt(receipt: Mapping[str, Any]):
    import agreement_cli as base
    import agreement_confirmatory_v2_cli as v2

    run_plan_id, expected = receipt["run_plan_id"], receipt["run_plan_sha256"]
    tried = []
    for plan in campaign_plans():
        entry = next((e for e in plan["plans"] if e["run_plan_id"] == run_plan_id), None)
        if entry is None:
            continue
        tried.append(plan["campaign_id"])
        v2._use(plan["pack"], plan["controls"])
        setup = v2.build_setup(v2.ARMS[plan["arm"]], entry["pairing"], base.cases(plan["worlds"]), plan["provider_runtimes"])
        try:
            rebuilt, _drift = plan_with_recorded_pins(setup.plan, _recorded_pins(receipt))
        except PlanResolutionError:
            continue
        if rebuilt.plan_sha256 == expected:
            return setup
    raise ValueError(f"no published agreement v2 campaign rebuilds plan {expected[:16]} ({run_plan_id}); tried {tried}")
