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
from .harness import ScriptedCollusionHarness
from .measurement import CollusionScorer, build_leaves, build_scorer
from .replay import RecordedEpisode, ReplayReport, record_episode, replay_and_verify, replay_episode

__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "HORIZON",
    "SPLIT",
    "TERMINATION_REASONS",
    "CollusionPlugin",
    "CollusionScorer",
    "RecordedEpisode",
    "ReplayReport",
    "ScriptedCollusionHarness",
    "build_all_cases",
    "build_case",
    "build_case_payload",
    "build_leaves",
    "build_scorer",
    "case_id",
    "economics",
    "family_manifest",
    "record_episode",
    "register_plugin",
    "replay_and_verify",
    "replay_episode",
]
