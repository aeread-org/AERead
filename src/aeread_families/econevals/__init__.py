"""AERead ``econevals`` family package.

Wraps the pinned upstream ``econ-evals-paper`` checkout (spec commit
``e1f2a40fec96f0d27f5414873c4310f2b5c51935``) as one AERead family with three
tracks (``procurement``, ``scheduling``, ``pricing``). See
``docs/econevals_adapter_spec.md`` for the governing spec.

Milestone 1 of 3 (cases + environment): the corpus importer (``cases.py``),
the bridge to the pinned upstream checkout (``econevals_bridge.py`` /
``econevals_bridge_driver.py``), and the live period-loop kernel plugin
(``environment.py``). The two ``MeasurementLeafSpec`` verifier declarations
per track (spec section 2) land in a later milestone.
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

__all__ = [
    "BRIDGE_PYTHON_ENV_VAR",
    "DEFAULT_BRIDGE_VENV",
    "EconevalsBridge",
    "EconevalsBridgeError",
    "EconevalsBridgeUnavailableError",
    "EconevalsPlugin",
    "GurobiLicenseSizeError",
    "discover_bridge_python",
    "family_manifest",
    "register_plugin",
]
