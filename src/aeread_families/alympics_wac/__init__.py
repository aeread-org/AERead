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
    "build_all_cases",
    "build_case",
    "build_corpus_manifest",
    "family_manifest",
    "register_plugin",
]
