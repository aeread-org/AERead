"""Versioned V5 payment wire-unit clarification; no historical source edits.

Only V5 active-payments observations/profiles/cases change. Reducers, guards,
references and scoring stay identical. Other cohort/seat plans are untouched.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from aeread.shared_runner.registry import PluginRegistry, HarnessRegistry, ProviderCapabilities
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import AgentProfile, CaseManifest
from . import v2_5_seat_extension_v5 as v5

REVISION = "refund_v25_payment_wire_units/5.1"
VERSION = "2.5.5.1"
UNIT_RULE = (
    "Compute ledger amounts and tender capacities using integer cents internally. "
    "confirmed_proposal.amount is in the scope currency's major units. "
    "Output amount and EVERY refund_allocations[].amount in major currency units, NOT cents: "
    "divide computed integer cents by 100 exactly once at the output boundary. "
    "For example, a generic 1234-cent amount is output as 12.34 USD, not 1234. "
    "Outputs have at most two decimal places. No-op outputs amount=0 and refund_allocations=[]."
)
UNIT_CONTRACT = {"revision": REVISION, "ledger_units": "integer_cents",
    "proposal_amount_units": "scope_currency_major_units",
    "output_amount_units": "scope_currency_major_units",
    "allocation_amount_units": "scope_currency_major_units",
    "output_formula": "output_amount = computed_integer_cents / 100", "rule": UNIT_RULE}


class UnitsPlugin(v5.ExtensionPlugin):
    def validate_payload(self, payload):
        case = super().validate_payload(payload)
        if canonical_json_bytes(payload.get("payment_units_contract")) != canonical_json_bytes(UNIT_CONTRACT):
            raise ValueError("Versioned payment unit contract is missing or changed")
        if case.seat_context["pair_kind"] != "payments_v5":
            raise ValueError("Units amendment is only for V5 payments cases")
        return case

    def observe(self, case, state, seat, phase):
        obs = dict(super().observe(case, state, seat, phase))
        if seat == "payments":
            contract = dict(obs["execution_contract"])
            contract["version"] = REVISION
            contract["execution_rule"] = contract["execution_rule"].replace(
                "Integer cents throughout.", "Integer cents for internal ledger calculations only.")
            contract["amount_units"] = UNIT_CONTRACT
            contract["execution_rule"] += " " + UNIT_RULE
            obs["execution_contract"] = contract
        return obs


def amend_setup(original):
    """Re-resolve only this cohort: changed wire contract is honestly hashed."""
    old = original.plan
    plugin = UnitsPlugin()
    family = old.families[0]
    registry = PluginRegistry()
    registry.register(family, plugin, contribution=v5.v3.legacy._contribution(),
        evidence_root=v5.v3.legacy.QC_ROOT)
    cases = []
    for case in old.cases:
        raw = json.loads(canonical_json_bytes(case))
        raw["payload"]["payment_units_contract"] = UNIT_CONTRACT
        raw["payload"]["payment_units_revision"] = REVISION
        raw["content_sha256"] = case_content_sha256(raw)
        cases.append(CaseManifest.from_dict(raw))
    prompts = dict(original.prompt_sources)
    prompt_id = v5.v3.legacy.PROMPT_IDS["payments"]
    prompts[prompt_id] += " " + UNIT_RULE
    profiles = []
    for profile in old.agent_profiles:
        raw = json.loads(canonical_json_bytes(profile))
        if raw["prompt"]["prompt_id"] == prompt_id:
            raw["prompt"]["sha256"] = hashlib.sha256(prompts[prompt_id].encode()).hexdigest()
            schema = raw["harness"]["config"]["output_schema"]
            schema["properties"]["amount"]["description"] = "Scope currency major units, NOT cents; computed integer cents divided by 100."
            schema["properties"]["refund_allocations"]["items"]["properties"]["amount"]["description"] = "Scope currency major units, NOT cents; computed allocation cents divided by 100."
        profiles.append(AgentProfile.from_dict(raw))
    pins = tuple(v5.v3.legacy._pin(p.component_id, p.kind, Path(__file__), VERSION)
        if p.component_id == "aeread.refund_v25" else p for p in old.implementation_pins)
    harnesses = HarnessRegistry()
    for harness in original.harnesses.values(): harnesses.register(harness)
    plan = resolve_run_plan(families=old.families, cases=tuple(cases), suite=old.suite,
        sampling=old.sampling, evaluation_blocks=old.evaluation_blocks, analysis=old.analysis,
        agent_profiles=tuple(profiles), run_spec=old.run_spec, registry=registry,
        implementation_pins=pins, harness_registry=harnesses,
        provider_capabilities={"arena": ProviderCapabilities(False, False, False, True, True, False, None),
            "scripted": ProviderCapabilities(False, False, False, True, False, False, None)})
    return replace(original, plan=plan, registry=registry, prompt_sources=prompts)
