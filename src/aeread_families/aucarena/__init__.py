"""AERead ``aucarena`` family package.

Milestone 1 of 3 (cases + environment): scenario authoring
(:mod:`.cases`), the vendored pure-logic auction rules
(:mod:`._vendored_upstream`), and the phase-graph environment plugin
(:mod:`.environment`). Measurement leaves/scorer, the parity runner, and the
offline replayer land in later milestones -- see
``docs/aucarena_adapter_spec.md`` section 4.
"""
from .environment import AucArenaPlugin, family_manifest, register_plugin

__all__ = [
    "AucArenaPlugin",
    "family_manifest",
    "register_plugin",
]
