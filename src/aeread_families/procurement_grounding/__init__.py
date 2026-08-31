"""AERead procurement-grounding family."""

from .environment import (
    FAMILY_ID,
    FAMILY_VERSION,
    ProcurementGroundingPlugin,
    ProcurementGroundingScorer,
    family_manifest,
    register_plugin,
)
from .runner import (
    CASE_PATH,
    PROMPT,
    OpenRouterRoute,
    ProcurementGroundingSetup,
    build_offline_setup,
    build_openrouter_setup,
    load_case,
    procurement_report_output_schema,
    run_fixture_response,
)

__all__ = [
    "CASE_PATH",
    "FAMILY_ID",
    "FAMILY_VERSION",
    "OpenRouterRoute",
    "PROMPT",
    "ProcurementGroundingPlugin",
    "ProcurementGroundingScorer",
    "ProcurementGroundingSetup",
    "build_offline_setup",
    "build_openrouter_setup",
    "family_manifest",
    "load_case",
    "procurement_report_output_schema",
    "register_plugin",
    "run_fixture_response",
]
