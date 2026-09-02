"""Corpus authoring: the alympics.wac parameter grid -> AERead cases.

Unlike ``tau3.retail`` (which imports an upstream task bank verbatim), the
pinned ``microsoft/Alympics`` checkout ships no task corpus for the Water
Allocation Challenge: ``waterAllocation.__init__`` hardcodes exactly one
5-persona scenario with no constructor parameter to vary it (see
``docs/alympics_adapter_spec.md`` "Governing facts" and section 1). AERead is
therefore the corpus's provenance owner ("generated; no static JSON
fixtures", the same posture as ``housing_v1``), and this module *authors* one
``CaseManifest`` per declared grid cell instead of importing upstream rows.

Nothing here reimplements upstream settlement math, tool bodies, or database
mutations (rule 2 of the adapter build). The one thing this module computes
that upstream itself never fixes -- a reproducible per-case supply schedule
-- is generated once, here, from an AERead-owned ``numpy.random.RandomState``
seeded per case, and frozen into the case payload; it is never regenerated
at run time and never reads upstream's own unseeded global ``numpy.random``
state (see the spec's corrected governing fact on ``run.py``'s
``generate_data``).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "alympics.wac"
FAMILY_VERSION = "0.1.0"
SPLIT = "base"
CASE_ID_PREFIX = "alympics.wac"

# Seats are symmetric in shape (same phase, same action schema); each carries
# the single declared family role.
SEAT_ROLE = "player"

# Nothing in a bidder's own observation may leak another seat's not-yet-
# revealed bid before that round's allocation is announced (spec section 2,
# leaf 4's leakage-audit prerequisite; enforced by environment.py's
# ``observe``, declared here as the case-level policy identifier).
VISIBILITY_POLICY = "alympics_wac_seat_private_bids_v1"

# Every reason this family's environment can terminate for, and nothing else
# (mirrors tau3_retail's ``TERMINATION_REASONS`` discipline: declared next to
# the manifest that publishes it, enforced in environment.py's
# ``_set_termination`` so the declaration and the behaviour cannot drift).
#
# `malformed_action` is reachable only through environment.py's internal
# test-only `force_malformed` hook (spec section 4's malformed-parse
# golden), never through any real scripted policy in the 7 grid cells; it is
# still declared here so a real occurrence (an adapter bug) fails loudly
# through the same typed vocabulary instead of an undeclared value.
TERMINATION_REASONS = ("rounds_exhausted", "all_seats_eliminated", "malformed_action")

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "microsoft/Alympics"
UPSTREAM_COMMIT = "caed7c8c3b8f9de9ac8be1ba54407a51087affc5"
UPSTREAM_LICENSE = "MIT"

# Upstream's own hardcoded 5-persona roster (``waterAllocation.__init__``,
# ``src/waterAllocation.py:82-88``): identity, water requirement, and daily
# salary are read verbatim from the pinned source, never a grid dimension
# (governing fact: "no constructor parameter to vary them"). Construction
# order also fixes ``_check_winner``'s tie-break order for this persona set
# (verified concretely in recon, not a declared upstream sort).
SEAT_ORDER: tuple[str, ...] = ("alex", "bob", "cindy", "david", "eric")

PERSONAS: Mapping[str, Mapping[str, Any]] = {
    "alex": {"upstream_name": "Alex", "requirement": 8, "daily_salary": 70},
    "bob": {"upstream_name": "Bob", "requirement": 9, "daily_salary": 75},
    "cindy": {"upstream_name": "Cindy", "requirement": 10, "daily_salary": 100},
    "david": {"upstream_name": "David", "requirement": 11, "daily_salary": 120},
    "eric": {"upstream_name": "Eric", "requirement": 12, "daily_salary": 120},
}

# Upstream-fixed starting player state (``myPlayer.__init__``,
# ``src/waterAllocation.py:9-30``), identical for every persona.
STARTING_BALANCE = 0
STARTING_HP = 8
STARTING_NO_DRINK = 1
MAXIMUM_HEALTH = 10

# The four scripted policies this adapter's harness implements against the
# grid's declared ``policy_assignment`` (spec section 6: "illustrative of the
# family's shape, not claimed-optimal"). Declared here as the closed
# vocabulary a case's ``policy_assignment`` may reference; the policy
# *functions* themselves are harness-owned, not environment-owned.
POLICY_IDS = ("proportional", "aggressive", "conservative", "myopic_need")


class GridValidationError(ValueError):
    """An authored grid cell is internally inconsistent."""


# --------------------------------------------------------------------------
# Grid definition (spec section 1's 7-row table).
# --------------------------------------------------------------------------

_ALL_PROPORTIONAL = {seat: "proportional" for seat in SEAT_ORDER}
_MIXED_POLICIES_A = {
    "alex": "aggressive",
    "bob": "conservative",
    "cindy": "proportional",
    "david": "myopic_need",
    "eric": "proportional",
}

# One dict per grid cell. ``supply_regime`` is either
# ``{"kind": "uniform", "lower": int, "upper": int}`` (numpy's own
# half-open ``[lower, upper)`` convention, matching upstream's own
# ``--lower``/``--upper`` reference defaults) or
# ``{"kind": "constant", "value": int}`` (golden 5's degenerate case, which
# needs no seed at all).
GRID: tuple[Mapping[str, Any], ...] = (
    {
        "case_id": f"{CASE_ID_PREFIX}.reference_baseline",
        "supply_regime": {"kind": "uniform", "lower": 10, "upper": 20},
        "rounds": 20,
        "supply_schedule_seed": 0,
        "policy_assignment": dict(_ALL_PROPORTIONAL),
        "note": (
            "parity anchor: reproduces upstream's own reference `run.py` "
            "defaults (round=20, lower=10, upper=20), seeded for "
            "reproducibility upstream itself lacks"
        ),
    },
    {
        "case_id": f"{CASE_ID_PREFIX}.generous_supply",
        "supply_regime": {"kind": "uniform", "lower": 20, "upper": 30},
        "rounds": 10,
        "supply_schedule_seed": 0,
        "policy_assignment": dict(_ALL_PROPORTIONAL),
        "note": "low survival pressure, high headroom",
    },
    {
        "case_id": f"{CASE_ID_PREFIX}.scarce_supply",
        "supply_regime": {"kind": "uniform", "lower": 3, "upper": 8},
        "rounds": 10,
        "supply_schedule_seed": 0,
        "policy_assignment": dict(_ALL_PROPORTIONAL),
        "note": "high survival pressure, low headroom",
    },
    {
        "case_id": f"{CASE_ID_PREFIX}.mixed_policies_a",
        "supply_regime": {"kind": "uniform", "lower": 10, "upper": 20},
        "rounds": 15,
        "supply_schedule_seed": 1,
        "policy_assignment": dict(_MIXED_POLICIES_A),
        "note": "heterogeneous panel; one seat rotates as focal across paired trials",
    },
    {
        "case_id": f"{CASE_ID_PREFIX}.mixed_policies_a_seed2",
        "supply_regime": {"kind": "uniform", "lower": 10, "upper": 20},
        "rounds": 15,
        "supply_schedule_seed": 3,
        "policy_assignment": dict(_MIXED_POLICIES_A),
        "note": (
            "disjoint-seed pairing of mixed_policies_a, required by Gate 1 "
            "before treating repeats as independent clusters"
        ),
    },
    {
        "case_id": f"{CASE_ID_PREFIX}.short_horizon",
        "supply_regime": {"kind": "uniform", "lower": 15, "upper": 25},
        "rounds": 5,
        "supply_schedule_seed": 2,
        "policy_assignment": dict(_ALL_PROPORTIONAL),
        "note": "low elimination risk, isolates early-round policy differences",
    },
    {
        "case_id": f"{CASE_ID_PREFIX}.zero_supply_degenerate",
        "supply_regime": {"kind": "constant", "value": 0},
        "rounds": 20,
        "supply_schedule_seed": None,
        "policy_assignment": dict(_ALL_PROPORTIONAL),
        "note": (
            "degenerate-reference golden anchor: no requirement is ever <= 0, "
            "so every policy is tied at zero information by construction"
        ),
    },
)


# --------------------------------------------------------------------------
# Supply-schedule generation (spec section 1's content-digest paragraph).
# --------------------------------------------------------------------------


def generate_supply_schedule(regime: Mapping[str, Any], rounds: int) -> list[int]:
    """Generate one frozen per-round supply schedule for a grid cell.

    ``kind="uniform"`` draws from an AERead-owned
    ``numpy.random.RandomState(supply_schedule_seed)`` -- never upstream's
    own unseeded global ``numpy.random`` state (``src/run.py``'s
    ``generate_data`` calls ``np.random.randint(lower, upper)`` in a loop of
    ``round`` unseeded scalar draws with no seed set anywhere in the script;
    see the spec's corrected governing fact). ``kind="constant"`` needs no
    randomness at all.
    """
    kind = regime["kind"]
    if kind == "uniform":
        rng = np.random.RandomState(regime["supply_schedule_seed"])
        lower, upper = regime["lower"], regime["upper"]
        if not (isinstance(lower, int) and isinstance(upper, int) and lower < upper):
            raise GridValidationError(f"invalid uniform supply regime: {regime!r}")
        return [int(value) for value in rng.randint(lower, upper, size=rounds)]
    if kind == "constant":
        value = regime["value"]
        if not isinstance(value, int) or value < 0:
            raise GridValidationError(f"invalid constant supply regime: {regime!r}")
        return [value] * rounds
    raise GridValidationError(f"unknown supply regime kind: {kind!r}")


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1).
# --------------------------------------------------------------------------


def _validate_grid_cell(cell: Mapping[str, Any]) -> None:
    rounds = cell["rounds"]
    if not isinstance(rounds, int) or rounds <= 0:
        raise GridValidationError(f"rounds must be a positive integer: {cell!r}")
    policy_assignment = cell["policy_assignment"]
    if set(policy_assignment) != set(SEAT_ORDER):
        raise GridValidationError(
            f"policy_assignment must cover exactly {SEAT_ORDER}: {cell!r}"
        )
    bad_policies = set(policy_assignment.values()) - set(POLICY_IDS)
    if bad_policies:
        raise GridValidationError(f"undeclared policy id(s) {bad_policies}: {cell!r}")


def build_case(cell: Mapping[str, Any]) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one authored grid cell."""
    _validate_grid_cell(cell)
    case_id = cell["case_id"]
    regime = dict(cell["supply_regime"])
    rounds = cell["rounds"]
    seed = cell["supply_schedule_seed"]
    if regime["kind"] == "uniform":
        regime["supply_schedule_seed"] = seed
    supply_schedule = generate_supply_schedule(regime, rounds)

    world_seed = seed if isinstance(seed, int) else 0

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": SPLIT,
        "world_seed": world_seed,
        "seats": [{"id": seat, "role": SEAT_ROLE} for seat in SEAT_ORDER],
        "episode": {
            # Upper bound: the scheduler counts phase actions across every
            # loop instance for the whole episode, never reset per round --
            # this is the exact bound, only reached if no seat is ever
            # eliminated (already-ledgered kernel behavior, see spec §3).
            "max_logical_actions": len(SEAT_ORDER) * rounds,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "grid_cell": {
                "supply_regime": cell["supply_regime"],
                "rounds": rounds,
                "supply_schedule_seed": seed,
                "policy_assignment": dict(cell["policy_assignment"]),
            },
            "supply_schedule": supply_schedule,
            # A defensive deep copy, never the shared module-level `PERSONAS`
            # object aliased by reference: every case built by this function
            # must own its own independent payload, so a future code path
            # that mutates one case's `payload["personas"]` in place can
            # never silently corrupt every other case sharing the same
            # object (including ones already loaded in a long-lived
            # process).
            "personas": copy.deepcopy(PERSONAS),
            "seat_order": list(SEAT_ORDER),
            "starting_state": {
                "balance": STARTING_BALANCE,
                "hp": STARTING_HP,
                "no_drink": STARTING_NO_DRINK,
                "maximum_health": MAXIMUM_HEALTH,
            },
            "upstream_pin": {
                "repo": UPSTREAM_REPO,
                "commit": UPSTREAM_COMMIT,
                "license": UPSTREAM_LICENSE,
            },
        },
        "provenance": {
            "generator_id": "alympics_wac_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "curated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap and catches canonicalization bugs
    # early, mirroring tau3_retail.cases.build_case).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def build_all_cases() -> dict[str, dict[str, Any]]:
    """Build every grid-cell case, keyed by case id, in declared grid order."""
    cases: dict[str, dict[str, Any]] = {}
    for cell in GRID:
        case = build_case(cell)
        if case["case_id"] in cases:
            raise GridValidationError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    return cases


# --------------------------------------------------------------------------
# Corpus manifest (mirrors tau3_retail's pilot_manifest.json).
# --------------------------------------------------------------------------

CORPUS_ID = "alympics_wac_grid_v1"


def _corpus_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def build_corpus_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the corpus-enumeration manifest covering every grid cell."""
    expected_ids = [cell["case_id"] for cell in GRID]
    missing = [case_id for case_id in expected_ids if case_id not in cases]
    if missing:
        raise ValueError(f"grid case ids not found in built corpus: {missing}")
    data: dict[str, Any] = {
        "corpus_id": CORPUS_ID,
        "family_id": FAMILY_ID,
        "split": SPLIT,
        "case_ids": expected_ids,
        "case_sha256_by_id": {
            case_id: cases[case_id]["content_sha256"] for case_id in expected_ids
        },
        "content_sha256": "0" * 64,
    }
    digest = _corpus_content_sha256(data)
    data["content_sha256"] = digest
    return data


# --------------------------------------------------------------------------
# Disk I/O.
# --------------------------------------------------------------------------


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_cases(
    output_dir: Path,
    cases: Mapping[str, Mapping[str, Any]],
    corpus_manifest: Mapping[str, Any],
) -> None:
    """Write one file per case plus the corpus-enumeration manifest."""
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)
    _dump_json(output_dir / "corpus_manifest.json", corpus_manifest)


def run_import(output_dir: Path) -> None:
    """End-to-end: author every grid cell and write the case set + manifest."""
    cases = build_all_cases()
    corpus_manifest = build_corpus_manifest(cases)
    write_cases(output_dir, cases, corpus_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/alympics_wac/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "alympics_wac" / "base"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write the 7 grid-cell case files plus corpus_manifest.json",
    )
    args = parser.parse_args(argv)
    run_import(args.output_dir)


if __name__ == "__main__":
    main()
