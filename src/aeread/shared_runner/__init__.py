"""AERead shared-runner contracts and implementation stages."""

from .registry import PluginRegistry
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
    "PluginRegistry",
    "RunSpec",
    "SamplingPlan",
    "SuiteManifest",
    "parse_authoring_record",
]
