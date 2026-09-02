"""AERead ``agenticpay.bilateral`` family package.

Milestone 1 (cases + environment): ``cases.py`` (the importer) and
``environment.py`` (the kernel plugin). Milestone 2 (measurement + goldens)
adds ``measurement.py``'s four sanctioned leaves and wires
``environment.py``'s ``build_scorer`` to them. The scripted-policy test
harness and the parity/replay tooling described in
``docs/agenticpay_adapter_spec.md``'s proposed module layout are still not
built -- see that spec's section 5/6 and each module's own docstring.
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
