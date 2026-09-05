"""AERead ``amazonbarg.bilateral`` family package.

Milestone 1: cases + environment. Milestone 2 (this update): measurement --
five leaves (``amazonbarg_deal_authenticity``, ``amazonbarg_zopa_membership``,
the two bound leaves, ``amazonbarg_bargained_ratio``), each delegated to
upstream's own ``eval.py:Metrics``, plus the five QC Gate-2 goldens (see
``docs/amazonbarg_adapter_spec.md`` and ``measurement.py``).
``AmazonbargPlugin.build_scorer`` now returns a real
``measurement.AmazonbargScorer``. Milestone 3 (later): the scripted
counterpart harness, parity, and replay.
"""

from .environment import AmazonbargPlugin, family_manifest, register_plugin
from .measurement import AmazonbargScorer, build_scorer

__all__ = [
    "AmazonbargPlugin",
    "AmazonbargScorer",
    "build_scorer",
    "family_manifest",
    "register_plugin",
]
