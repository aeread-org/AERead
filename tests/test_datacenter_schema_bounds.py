"""DC-D-07: the closed output schema carries the contract parser's bounds.

Five of the first ten pilot cells died at their first action because Gemini
emitted `site_control_start_month: 0`, which the parser refuses and the
schema had allowed. A case that opts into `construct_controls` now carries
every parser minimum in its strict schema and a v2 prompt that says months
start at 1; the sealed cases keep their v1 schema and prompt byte for byte.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from aeread_families.datacenter_development.stack_runner import (
    DEVELOPER_PROMPT,
    MONTH_INDEXING_NOTE,
    TERM_MINIMUMS,
    build_stack_openrouter_setup,
    developer_prompt,
    load_stack_case,
    stack_developer_output_schemas,
)
from aeread_families.procurement_grounding import OpenRouterRoute
from aeread.shared_runner.task.execution import TokenPricing

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SEALED = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v2" / "full_stack_amendment_001.json"
REPAIRED = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v2" / "full_stack_amendment_002.json"
WORLD = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "worlds_v2" / "covenant_cliff_001.json"
ROUTE = OpenRouterRoute(
    profile_id="datacenter_v2_gemini38_probe",
    model="google/gemini-3.8-flash",
    revision="google/gemini-3.8-flash-20260902",
    route_provider="Google AI Studio",
    quantization="unknown",
    pricing=TokenPricing(0.75, 0.075, 3.75, "test_pricing"),
    max_prompt_price_per_million="1.35",
    max_completion_price_per_million="6.75",
)


def _land_properties(case_path: Path) -> dict:
    schemas = stack_developer_output_schemas(load_stack_case("v2", case_path))
    return schemas["datacenter_land_offer_v1"]["properties"]["terms"]["anyOf"][0]["properties"]


def test_bounded_cases_carry_the_parser_minimums_in_their_schema() -> None:
    for case_path in (REPAIRED, WORLD):
        land = _land_properties(case_path)
        assert land["site_control_start_month"] == {"type": "integer", "minimum": 1}
        assert land["permitted_use_capacity_kw"]["minimum"] == 1
        assert land["purchase_price_cents"]["minimum"] == 0  # non-negative, like the parser
        assert land["extension_price_cents"]["minimum"] == 0
        schemas = stack_developer_output_schemas(load_stack_case("v2", case_path))
        epc = schemas["datacenter_epc_offer_v1"]["properties"]["terms"]["anyOf"][0]["properties"]
        assert epc["contract_price_cents"]["minimum"] == TERM_MINIMUMS["contract_price_cents"] == 1
        assert epc["notice_to_proceed_month"]["minimum"] == 1
        schedule = epc["payment_schedule"]["items"]["properties"]
        assert schedule["month"]["minimum"] == 0 and schedule["amount_cents"]["minimum"] == 0


def test_the_sealed_case_keeps_its_unbounded_schema_and_v1_prompt() -> None:
    land = _land_properties(SEALED)
    assert land["site_control_start_month"] == {"type": "integer"}
    assert all("minimum" not in spec for spec in land.values() if isinstance(spec, dict))
    prompt_id, text = developer_prompt(load_stack_case("v2", SEALED).payload, "v2")
    assert prompt_id == "datacenter_v2_developer_prompt_v1" and text == DEVELOPER_PROMPT


def test_bounded_cases_get_the_v2_prompt_with_the_month_note() -> None:
    prompt_id, text = developer_prompt(load_stack_case("v2", REPAIRED).payload, "v2")
    assert prompt_id == "datacenter_v2_developer_prompt_v2"
    assert text == DEVELOPER_PROMPT + MONTH_INDEXING_NOTE
    assert "month 1 is the first month" in text

    setup = build_stack_openrouter_setup("v2", ROUTE, seed=1, case_path=REPAIRED)
    developer = next(p for p in setup.plan.agent_profiles if p.model.provider == "openrouter")
    assert developer.prompt.prompt_id == "datacenter_v2_developer_prompt_v2"
    assert developer.prompt.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert setup.prompt_sources["datacenter_v2_developer_prompt_v2"] == text

    sealed_setup = build_stack_openrouter_setup("v2", ROUTE, seed=1, case_path=SEALED)
    sealed_developer = next(p for p in sealed_setup.plan.agent_profiles if p.model.provider == "openrouter")
    assert sealed_developer.prompt.prompt_id == "datacenter_v2_developer_prompt_v1"
