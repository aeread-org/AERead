"""AERead ``aucarena`` family package.

Milestone 1 (cases + environment): scenario authoring (:mod:`.cases`), the
vendored pure-logic auction rules (:mod:`._vendored_upstream`), and the
phase-graph environment plugin (:mod:`.environment`). Milestone 2 added the
measurement leaves/scorer (:mod:`.measurement`). Milestone 3 (this package)
adds the shipped scripted harness (:mod:`.harness`) and the offline replayer
(:mod:`.replay`) -- see ``docs/aucarena_adapter_spec.md`` section 4 and
``docs/aucarena_adapter_status.md``. ``parity.py`` remains intentionally
unbuilt: ``tests/test_aucarena_parity.py`` covers the same component-parity
claim directly (see that spec section's milestone-1 note).
"""
from .environment import AucArenaPlugin, family_manifest, register_plugin
from .harness import ScriptedAucArenaHarness
from .replay import (
    RecordedDecision,
    RecordedEpisode,
    ReplayReport,
    record_episode,
    replay_and_verify,
    replay_episode,
)

__all__ = [
    "AucArenaPlugin",
    "RecordedDecision",
    "RecordedEpisode",
    "ReplayReport",
    "ScriptedAucArenaHarness",
    "family_manifest",
    "record_episode",
    "register_plugin",
    "replay_and_verify",
    "replay_episode",
]
