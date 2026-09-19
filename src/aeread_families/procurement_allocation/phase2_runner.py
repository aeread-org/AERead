"""Phase 2 adapter over the shared runner, with a separate family identity."""

from __future__ import annotations
import json
from aeread.shared_runner.run.resolver import canonical_json_bytes
import copy
from pathlib import Path
from aeread.shared_runner.registry import (
    PluginRegistry,
    HarnessRegistry,
    ProviderCapabilities,
)
from aeread.shared_runner.run.resolver import resolve_run_plan, case_content_sha256
from aeread.shared_runner.schemas import (
    AgentProfile,
    CaseManifest,
    SuiteManifest,
    RunSpec,
)
from . import environment as legacy_environment
from . import phase2_environment
from .runner import (
    build_offline_setup,
    build_openrouter_setup,
    ProcurementAllocationSetup,
    _pin,
    default_harnesses,
)
from .phase2_environment import Phase2Plugin, family_manifest
from .phase2_admission import action_schema

COMMON_PROMPT = """You are a procurement buyer. Return exactly one JSON action each turn.
Maximize contribution margin in USD, subject to evidence, service, cash and deadline constraints.
Actions: inquire, request_quote, request_sample, counter_offer, submit_award, defer.
Every award line requires an unexpired formal quote, an exact variant and a verified sample.
A sample proves evidence eligibility; its observed yield is a noisy binomial estimate.
Repeated samples accumulate. Historical yield estimates refer to earlier batches, not current truth.
Listings and verbal claims are nonbinding. The separately labelled certified market floors are guaranteed
constraints on every reachable supplier, including after negotiation; they do not authorize purchases.
Quotes, inquiries and samples consume actions, money and elapsed days. Keep one action for the final decision.
For each component, good on-time units = sum(quantity * yield * on_time_probability), with zero units
if elapsed days + shipping lead exceeds the deadline. Completed kits are the floor of the minimum
component units / BOM requirement, capped by target kits. Margin = kit revenue - purchase - shipping
- information costs - shortfall penalty. This panel has no duty, financing or return recovery.
Defer earns defer_value minus research already spent. Rejected purchases are a separate constraint failure;
they do not purchase inventory, but research costs remain. There is no check_award action.
Action format contract: all eight top-level schema keys must be present. Null is allowed ONLY for
fields unused by the selected action. Required fields for the selected action must never be null:
- request_quote or request_sample: supplier_id and message must both be nonempty strings.
  message is a short supplier-facing request, for example "Please provide a formal quote."
  or "Please provide a verified sample." A reason field does not replace message.
- inquire: supplier_id and message must be nonempty strings; fields must be a nonempty list
  of distinct names from exact_variant, moq_capacity, lead_time, shipping, quality, sample_logistics.
- counter_offer: supplier_id, offer_id and message must be nonempty strings; proposal must be
  an object containing all five schema keys, with at least one non-null proposed value.
  unit_price_usd must be a nonnegative number; moq, payment_terms_days and refund_window_days
  must be positive integers when used; return_freight_payer must be buyer or supplier when used.
  Use null for proposal terms you are not changing. Text in message is not a numeric proposal.
- submit_award: award_lines must be a nonempty list. Each line has ONLY offer_id (nonempty string)
  and quantity (positive integer).
- defer: reason must be a nonempty string.
Before returning the JSON, check these required fields for your selected action.
"""
CONTROL_PROMPT = COMMON_PROMPT + "\nChoose your own sourcing and decision strategy.\n"
TREATMENT_PROMPT = (
    COMMON_PROMPT
    + """
Before searching, check whether market floors make service impossible or uneconomic.
Prioritize suppliers by potential net contribution using price, capacity, delivery and imperfect quality history.
Obtain a formal quote and sample for promising suppliers; never infer eligibility from a listing.
After each result, recalculate feasible allocations and expected margin from the evidence.
Combine suppliers when one cannot meet service; respect each MOQ, capacity and order step.
Treat noisy quality estimates with appropriate caution near feasibility thresholds.
Stop when the current qualified allocation is attractive and another test is unlikely to improve margin
by more than its money, delay and action costs. Search another supplier after poor evidence when worthwhile.
Defer with an evidence-based reason when there is no economically worthwhile reachable allocation.
"""
)
PROMPTS = {"control": CONTROL_PROMPT, "treatment": TREATMENT_PROMPT}


def build_setup(
    case, *, contribution, evidence_root, arm="control", route=None, seed=0
):
    if not isinstance(case, CaseManifest):
        case = CaseManifest.from_dict(case)
    if (
        case.family_id != phase2_environment.FAMILY_ID
        or case_content_sha256(case) != case.content_sha256
    ):
        raise ValueError("wrong Phase 2 case identity or digest")
    prompt_id = f"procurement_phase2_action_format_{arm}_v2"
    kwargs = dict(prompt=PROMPTS[arm], prompt_id=prompt_id)
    # Reuse only the tested boilerplate. Replace family, case, registry, output
    # schema and implementation pins before resolving any executable plan.
    if route is None:
        template = build_offline_setup(**kwargs)
    else:
        template = build_openrouter_setup(
            route,
            seed=seed,
            max_output_tokens=1200,
            max_cost_usd=0.025,
            max_action_attempts=2,
            retryable_conditions=("rate_limit",),
            retry_backoff="exponential_jitter_v1",
            retry_base_seconds=2.0,
            retry_after_max_seconds=180.0,
            **kwargs,
        )
    family = family_manifest()
    registry = PluginRegistry()
    registry.register(
        family, Phase2Plugin(), contribution=contribution, evidence_root=evidence_root
    )
    profile_raw = copy.deepcopy(
        json.loads(canonical_json_bytes(template.plan.agent_profiles[0]))
    )
    profile_raw["profile_id"] = f"phase2_{arm}_" + (
        "fixture" if route is None else route.profile_id
    )
    profile_raw["harness"]["config"]["output_schema"] = action_schema()
    profile = AgentProfile.from_dict(profile_raw)
    suite_raw = json.loads(canonical_json_bytes(template.plan.suite))
    suite_raw.update(
        suite_id="procurement_phase2_panel_v1",
        family_ids=[family.family.id],
        case_ids=[case.case_id],
    )
    suite = SuiteManifest.from_dict(suite_raw)
    run_raw = json.loads(canonical_json_bytes(template.plan.run_spec))
    run_raw.update(
        run_spec_id="procurement_phase2_run_v1",
        suite_id=suite.suite_id,
        agent_profile_ids=[profile.profile_id],
        seat_assignments={"buyer": profile.profile_id},
    )
    run_spec = RunSpec.from_dict(run_raw)
    harness_registry = HarnessRegistry()
    for harness in default_harnesses().values():
        harness_registry.register(harness)
    pins = [
        pin
        for pin in template.plan.implementation_pins
        if pin.kind in {"harness", "runtime"}
    ]
    pins.extend(
        [
            _pin(
                phase2_environment.PLUGIN_ID,
                "family_plugin",
                Path(phase2_environment.__file__),
            ),
            _pin(
                phase2_environment.SCORER_ID,
                "scorer",
                Path(phase2_environment.__file__),
            ),
            _pin(
                "procurement_full_information_upper_bound_v1",
                "reference",
                Path(legacy_environment.__file__),
            ),
        ]
    )
    provider = "fake" if route is None else "openrouter"
    plan = resolve_run_plan(
        families=(family,),
        cases=(case,),
        suite=suite,
        sampling=template.plan.sampling,
        evaluation_blocks=template.plan.evaluation_blocks,
        analysis=template.plan.analysis,
        agent_profiles=(profile,),
        run_spec=run_spec,
        registry=registry,
        implementation_pins=tuple(pins),
        harness_registry=harness_registry,
        provider_capabilities={
            provider: ProviderCapabilities(
                native_tools=False,
                structured_output=route is not None,
                seed=route is not None,
                system_prompt=True,
                reasoning_budget=route is not None
                and route.reasoning_effort is not None,
                reasoning_token_report=route is not None,
                max_context_tokens=None,
            )
        },
    )
    return ProcurementAllocationSetup(
        plan=plan,
        registry=registry,
        prompt_sources={prompt_id: PROMPTS[arm]},
        pricing=template.pricing,
        case=case,
        harnesses=default_harnesses(),
    )
