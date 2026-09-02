"""AERead ``amazonbarg.bilateral`` family package.

Milestone 1 of 3: cases + environment (see
``docs/amazonbarg_adapter_spec.md``). The scorer (five measurement leaves
delegated to upstream's ``eval.py:Metrics``) is a later milestone --
``AmazonbargPlugin.build_scorer`` raises ``NotImplementedError`` until then.
"""

from .environment import AmazonbargPlugin, family_manifest, register_plugin

__all__ = [
    "AmazonbargPlugin",
    "family_manifest",
    "register_plugin",
]
