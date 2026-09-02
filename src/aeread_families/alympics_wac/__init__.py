"""AERead ``alympics.wac`` family package.

Wraps the Water Allocation Challenge from the pinned ``microsoft/Alympics``
checkout (MIT). See ``docs/alympics_adapter_spec.md`` for the governing
adapter specification.
"""
from __future__ import annotations

from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    GRID,
    PERSONAS,
    SEAT_ORDER,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
    build_all_cases,
    build_case,
    build_corpus_manifest,
)
from .environment import AlympicsWacPlugin, family_manifest, register_plugin
from .measurement import AlympicsWacScorer, build_leaves
from .parity import ReferenceBaselineParityReport, run_reference_baseline_parity

__all__ = [
    "FAMILY_ID",
    "FAMILY_VERSION",
    "GRID",
    "PERSONAS",
    "SEAT_ORDER",
    "TERMINATION_REASONS",
    "UPSTREAM_COMMIT",
    "UPSTREAM_REPO",
    "AlympicsWacPlugin",
    "AlympicsWacScorer",
    "ReferenceBaselineParityReport",
    "build_all_cases",
    "build_case",
    "build_corpus_manifest",
    "build_leaves",
    "family_manifest",
    "register_plugin",
    "run_reference_baseline_parity",
]
