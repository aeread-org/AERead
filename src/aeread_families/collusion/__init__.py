"""AERead ``collusion`` family package (see docs/collusion_adapter_spec.md)."""

from . import economics
from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    HORIZON,
    SPLIT,
    TERMINATION_REASONS,
    build_all_cases,
    build_case,
    build_case_payload,
    case_id,
)
from .environment import CollusionPlugin, family_manifest, register_plugin

__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "HORIZON",
    "SPLIT",
    "TERMINATION_REASONS",
    "CollusionPlugin",
    "build_all_cases",
    "build_case",
    "build_case_payload",
    "case_id",
    "economics",
    "family_manifest",
    "register_plugin",
]
