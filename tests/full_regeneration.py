"""How much of a pack's regeneration a test run checks.

Rebuilding every world of a procurement pay-or-test pack from its seed, and screening every earlier seed of its block
again, takes most of an hour on eight cores (a full run: 609 passed in 53 minutes, 2026-10-20), past CI's job limit.
CI therefore checks a fixed sample: the first and the last world of each pack, and every ``SEED_STRIDE``-th earlier
seed. ``AEREAD_FULL_REGENERATION=1`` checks every world and every seed, and the family's QC profile records that run
before anything built on the pack is published.
"""
from __future__ import annotations

import os

FULL = os.environ.get("AEREAD_FULL_REGENERATION") == "1"
SEED_STRIDE = 97


def indices(count: int) -> list[int]:
    """Every world's index in a full run; the first and the last otherwise."""
    return list(range(count)) if FULL else sorted({0, count - 1})


def seeds(start: int, stop: int) -> range:
    """Every seed of ``[start, stop)`` in a full run; every ``SEED_STRIDE``-th from ``start`` otherwise."""
    return range(start, stop) if FULL else range(start, stop, SEED_STRIDE)
