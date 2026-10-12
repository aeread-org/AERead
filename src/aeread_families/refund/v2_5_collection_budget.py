"""Versioned fact-collection budgets; legacy runner bytes stay replayable.

Every legal intake/policy request reveals at least one new relevant fact.
For N public-contract fact IDs, disclosures <= N, policy actions <= N+1,
and the entire six-phase trajectory uses at most 2*N+5 logical actions.
Only phase budgets change. Cases, observations, agents and scoring do not.
"""
from dataclasses import replace
from pathlib import Path

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import plan_with_pins
from . import v2_5_runner as legacy
from .v2_5_branches import spec_for

REVISION = "refund_v25_fact_collection_budget/1"


def collection_bounds(case):
    fact_ids = spec_for(case.interaction.scenario).fact_ids()
    if not fact_ids or not set(fact_ids) <= set(case.facts):
        raise ValueError("Collection budget requires a complete finite public fact domain")
    n = len(fact_ids)
    return {"fact_count": n, "customer_disclosure": n,
            "policy_turn": n + 1, "whole_case": 2 * n + 5}


class RefundV25CollectionBudgetPlugin(legacy.RefundV25Plugin):
    def initial_state(self, case, run):
        required = collection_bounds(case)["whole_case"]
        if run is not None and run.case_max_logical_actions < required:
            raise ValueError("Whole-case budget cannot cover legal fact collection")
        return super().initial_state(case, run)

    def phases(self, case):
        bounds = collection_bounds(case)
        return tuple(replace(phase, max_logical_actions=max(phase.max_logical_actions,
                         bounds.get(phase.phase_id, phase.max_logical_actions)))
                     for phase in super().phases(case))


def repair_setup(setup):
    """Register a separately pinned plugin, preserving case/profile identities."""
    plugin = RefundV25CollectionBudgetPlugin()
    for manifest_case in setup.plan.cases:
        case = plugin.validate_payload(manifest_case.payload)
        bounds = collection_bounds(case)
        cells = [c for c in setup.plan.cells if c.case_id == case.case_id]
        if any(c.case_max_logical_actions < bounds["whole_case"] for c in cells):
            raise ValueError("Existing case budgets are insufficient for this repair")
    manifest = setup.plan.families[0]
    registry = PluginRegistry()
    registry.register(manifest, plugin, contribution=legacy._contribution(),
                      evidence_root=legacy.QC_ROOT)
    pins = tuple(legacy._pin(p.component_id, p.kind, Path(__file__), p.version)
                 if p.component_id == "aeread.refund_v25" else p
                 for p in setup.plan.implementation_pins)
    return replace(setup, registry=registry, plan=plan_with_pins(setup.plan, pins))


def build_refund_v25_run(**kwargs):
    """Current repaired builder; the legacy builder remains historical."""
    return repair_setup(legacy.build_refund_v25_run(**kwargs))
