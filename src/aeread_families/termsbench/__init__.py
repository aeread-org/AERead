"""AERead ``termsbench`` family package.

A faithful reimplementation from the paper of TERMS-Bench's bilateral
alternating-offer price-negotiation environment (arXiv 2605.13909v2). There is
no upstream code -- the paper's own repository link is dead -- so this
package never "ports" or "wraps upstream code"; every formula is transcribed
from a cited paper equation. See ``docs/termsbench_adapter_spec.md``.

One package, two regime-specific family VERSIONS: ``termsbench.overlap`` and
``termsbench.nodeal`` (owner decision, kernel_scoring_contract_spec.md ruling
R13 rule 1 -- see ``docs/termsbench_migration_plan.md``). ``TermsBenchPlugin``
carries a ``regime`` attribute fixed at construction; ``family_manifest``/
``register_plugin`` take ``regime`` explicitly.
"""

from .cases import FAMILY_ID_BY_REGIME, FAMILY_VERSION, TERMINATION_REASONS
from .environment import TermsBenchPlugin, family_manifest, register_plugin
from .harness import ScriptedTermsBenchHarness, render_counterpart_message

__all__ = [
    "FAMILY_ID_BY_REGIME",
    "FAMILY_VERSION",
    "ScriptedTermsBenchHarness",
    "TERMINATION_REASONS",
    "TermsBenchPlugin",
    "family_manifest",
    "register_plugin",
    "render_counterpart_message",
]
