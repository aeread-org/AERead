"""AERead ``agenticpay.bilateral`` family package.

Milestone 1 scope (cases + environment): ``cases.py`` (the importer) and
``environment.py`` (the kernel plugin). Measurement leaves, the scripted-
policy test harness, and the parity/replay tooling described in
``docs/agenticpay_adapter_spec.md``'s proposed module layout are deliberately
not built yet -- see that spec's section 5/6 and each module's own
docstring.
"""

from .environment import (
    AgenticpayBilateralPlugin,
    family_manifest,
    register_plugin,
)

__all__ = [
    "AgenticpayBilateralPlugin",
    "family_manifest",
    "register_plugin",
]
