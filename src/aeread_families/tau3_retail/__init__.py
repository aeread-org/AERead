"""AERead ``tau3.retail`` family package."""

from .environment import Tau3RetailPlugin, family_manifest, register_plugin
from .harness import ScriptedTau3RetailHarness
from .measurement import Tau3RetailScorer, build_leaves
from .parity import PilotParityReport, run_pilot, run_pilot_task
from .replay import RecordedEpisode, ReplayReport, record_episode, replay_and_verify, replay_episode

__all__ = [
    "PilotParityReport",
    "RecordedEpisode",
    "ReplayReport",
    "ScriptedTau3RetailHarness",
    "Tau3RetailPlugin",
    "Tau3RetailScorer",
    "build_leaves",
    "family_manifest",
    "record_episode",
    "register_plugin",
    "replay_and_verify",
    "replay_episode",
    "run_pilot",
    "run_pilot_task",
]
