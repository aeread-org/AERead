"""AERead ``agenticpay.bilateral`` family package.

Milestone 1 (cases + environment): ``cases.py`` (the importer) and
``environment.py`` (the kernel plugin). Milestone 2 (measurement + goldens)
adds ``measurement.py``'s four sanctioned leaves and wires
``environment.py``'s ``build_scorer`` to them. Milestone 3 (scripted harness +
end-to-end + replay) adds ``harness.py``'s ``ScriptedAgenticpayBilateralHarness``
and ``replay.py``'s offline replayer -- see each module's own docstring. A
component-level ``parity.py`` (spec section 5's reproducibility-under-
re-execution check) is not built yet.
"""

from .environment import (
    AgenticpayBilateralPlugin,
    family_manifest,
    register_plugin,
)
from .harness import ScriptedAgenticpayBilateralHarness
from .replay import RecordedEpisode, ReplayReport, record_episode, replay_and_verify, replay_episode

__all__ = [
    "AgenticpayBilateralPlugin",
    "RecordedEpisode",
    "ReplayReport",
    "ScriptedAgenticpayBilateralHarness",
    "family_manifest",
    "record_episode",
    "register_plugin",
    "replay_and_verify",
    "replay_episode",
]
