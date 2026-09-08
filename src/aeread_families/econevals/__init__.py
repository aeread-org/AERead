"""AERead ``econevals`` family package.

Wraps the pinned upstream ``econ-evals-paper`` checkout (spec commit
``e1f2a40fec96f0d27f5414873c4310f2b5c51935``) as one AERead family with three
tracks (``procurement``, ``scheduling``, ``pricing``). See
``docs/econevals_adapter_spec.md`` for the governing spec.

Milestone 1 of 3 (cases + environment): the corpus importer (``cases.py``),
the bridge to the pinned upstream checkout (``econevals_bridge.py`` /
``econevals_bridge_driver.py``), and the live period-loop kernel plugin
(``environment.py``). Milestone 2 of 3 (measurement + goldens) adds the two
``MeasurementLeafSpec`` verifier declarations per track (spec section 2,
``measurement.py``), wired into ``environment.py``'s ``build_scorer`` hook.
Milestone 3 of 3 (harness + replay) adds the scripted tool surface
(``tools.py``) and harness (``harness.py``) that drive real episodes
through the kernel scheduler (``run_episode``), and the offline replayer
(``replay.py``) that reproduces a recorded episode's final state and both
measurement leaves with zero further model calls.
"""

from .econevals_bridge import (
    BRIDGE_PYTHON_ENV_VAR,
    DEFAULT_BRIDGE_VENV,
    EconevalsBridge,
    EconevalsBridgeError,
    EconevalsBridgeUnavailableError,
    GurobiLicenseSizeError,
    discover_bridge_python,
)
from .environment import EconevalsPlugin, family_manifest, register_plugin
from .harness import ScriptedEconevalsHarness
from .measurement import EconevalsScorer, build_leaves, build_scorer
from .replay import (
    RecordedEpisode,
    ReplayReport,
    record_episode,
    replay_and_verify,
    replay_episode,
)

__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "DEFAULT_BRIDGE_VENV",
    "EconevalsBridge",
    "EconevalsBridgeError",
    "EconevalsBridgeUnavailableError",
    "EconevalsPlugin",
    "EconevalsScorer",
    "GurobiLicenseSizeError",
    "RecordedEpisode",
    "ReplayReport",
    "ScriptedEconevalsHarness",
    "build_leaves",
    "build_scorer",
    "discover_bridge_python",
    "family_manifest",
    "record_episode",
    "register_plugin",
    "replay_and_verify",
    "replay_episode",
]
