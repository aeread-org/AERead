"""AERead shared-runner contracts and implementation stages."""

from .registry import PluginRegistry
from .resolver import (
    ImplementationPin,
    PlanCell,
    PlanIntegrityError,
    PlanResolutionError,
    RunPlan,
    canonical_json_bytes,
    case_content_sha256,
    resolve_run_plan,
    verify_run_plan,
    write_run_plan,
)
from .schemas import (
    AgentProfile,
    AnalysisPlan,
    AuthoringValidationError,
    CaseManifest,
    EvaluationBlock,
    FamilyManifest,
    RunSpec,
    SamplingPlan,
    SuiteManifest,
    parse_authoring_record,
)

__all__ = [
    "AgentProfile",
    "AnalysisPlan",
    "AuthoringValidationError",
    "CaseManifest",
    "EvaluationBlock",
    "FamilyManifest",
    "ImplementationPin",
    "PlanCell",
    "PlanIntegrityError",
    "PlanResolutionError",
    "PluginRegistry",
    "RunPlan",
    "RunSpec",
    "SamplingPlan",
    "SuiteManifest",
    "canonical_json_bytes",
    "case_content_sha256",
    "parse_authoring_record",
    "resolve_run_plan",
    "verify_run_plan",
    "write_run_plan",
]
