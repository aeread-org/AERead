"""AERead ``termsbench`` family package.

A faithful reimplementation from the paper of TERMS-Bench's bilateral
alternating-offer price-negotiation environment (arXiv 2605.13909v2). There is
no upstream code -- the paper's own repository link is dead -- so this
package never "ports" or "wraps upstream code"; every formula is transcribed
from a cited paper equation. See ``docs/termsbench_adapter_spec.md``.
"""

from .cases import FAMILY_ID, FAMILY_VERSION, TERMINATION_REASONS
from .environment import TermsBenchPlugin, family_manifest, register_plugin
from .harness import ScriptedTermsBenchHarness, render_counterpart_message

__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "ScriptedTermsBenchHarness",
    "TERMINATION_REASONS",
    "TermsBenchPlugin",
    "family_manifest",
    "register_plugin",
    "render_counterpart_message",
]
