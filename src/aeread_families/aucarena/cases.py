"""Authoring: AERead-authored auction scenarios -> ``aucarena`` cases.

Unlike ``tau3_retail``'s importer (114 pre-existing upstream task records),
upstream ``jiangjiechen/auction-arena`` ships no enumerable task list -- only
a raw 26-item pool (``data/pseudo_items.jsonl``) and a generator
(``auction_workflow.py --shuffle --repeat``) over declared pools. AERead
therefore *authors* the scenario corpus itself: an ordered subset of item
ids, a bidder roster, and a world seed, materialized against the pinned item
pool. See ``docs/aucarena_adapter_spec.md`` sections 1 and 5 for the
governing facts and the five QC Gate-2 goldens this module encodes.

This module never reimplements the auction rules (bid legality, hammer
determination, profit bookkeeping) -- those are vendored in
``_vendored_upstream.py`` and applied only by ``environment.py``. It only
resolves item ids against the pinned pool and seals each scenario into a
``CaseManifest``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "aucarena"
FAMILY_VERSION = "0.1.0"
SPLIT = "pilot"
CASE_ID_PREFIX = "aucarena.pilot"

# All bidder seats observe the same publicly-known auction state (current
# highest bid/bidder, item description, own budget) -- there is no seat-
# private information in this domain, unlike tau3 retail's user_scenario.
VISIBILITY_POLICY = "aucarena_full_observation_v1"

# The only reason this family's environment can terminate for: every item in
# the scenario has been presented and resolved (sold or failed to sell).
TERMINATION_REASONS = ("auction_complete",)

# A generous, uniform per-episode logical-action budget. Every decision slot
# in this family is one seat's bid in one round, so this bounds "seats x
# rounds x items" well above anything the five goldens can reach (see
# ``environment.py``'s termination proof: each round strictly reduces either
# an eligible bidder's remaining `max_bid_cnt` or ends the item).
MAX_LOGICAL_ACTIONS = 200

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "jiangjiechen/auction-arena"
UPSTREAM_COMMIT = "d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3"
UPSTREAM_LICENSE = "Apache-2.0"
ITEM_POOL_RELATIVE_PATH = Path("data") / "pseudo_items.jsonl"
ITEM_POOL_SHA256 = "7418dba88c65ffd82797b6a2cbfab854cc1ebfabf87b5f40019834b84f21cf9b"
ITEM_POOL_COUNT = 26


class ItemPoolPinMismatchError(ValueError):
    """The on-disk item pool no longer matches the pinned sha256/count."""


# --------------------------------------------------------------------------
# Item pool access (plain file read; no upstream import required).
# --------------------------------------------------------------------------


def load_item_pool(upstream_root: Path | str) -> dict[int, dict[str, Any]]:
    """Load and pin-check the upstream item pool, keyed by item id.

    Reads ``data/pseudo_items.jsonl`` from the pinned upstream checkout as
    plain data -- never imports upstream's ``Item`` class or
    ``create_items`` helper (which live in a module upstream never marks
    import-heavy, but this adapter still never imports upstream code at
    all; see ``_vendored_upstream.py``'s module docstring).
    """
    path = Path(upstream_root) / ITEM_POOL_RELATIVE_PATH
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != ITEM_POOL_SHA256:
        raise ItemPoolPinMismatchError(
            f"{path} sha256 {actual_sha256!r} does not match the pinned "
            f"{ITEM_POOL_SHA256!r}"
        )
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(records) != ITEM_POOL_COUNT:
        raise ItemPoolPinMismatchError(
            f"{path} has {len(records)} items, pinned count is {ITEM_POOL_COUNT}"
        )
    pool: dict[int, dict[str, Any]] = {}
    for record in records:
        item_id = record["id"]
        if item_id in pool:
            raise ItemPoolPinMismatchError(f"duplicate item id in pool: {item_id}")
        pool[item_id] = {
            "id": item_id,
            "name": record["name"],
            "price": record["price"],
            "desc": record["desc"],
            "true_value": record["true_value"],
        }
    return pool


# --------------------------------------------------------------------------
# Scenario authoring: the five QC Gate-2 goldens (spec section 5).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterSeat:
    seat_id: str
    model_name: str  # "rule" (vendored bid_rule) or "scripted" (tested seat)
    budget: int
    max_bid_cnt: int  # only consulted for model_name == "rule"


@dataclass(frozen=True)
class GoldenScenario:
    golden_name: str
    item_ids: tuple[int, ...]
    roster: tuple[RosterSeat, ...]
    world_seed: int


# Shared 3-seat roster used by goldens 1-4 (spec section 5 preamble):
# `field_low` always withdraws immediately (max_bid_cnt=0 makes every
# vendored `bid_rule` call return -1 with no logic beyond the shared
# function itself -- see _vendored_upstream.bid_rule); `field_high` is a
# normal rule bidder with room to contest four rounds.
_FIELD_LOW = RosterSeat(seat_id="field_low", model_name="rule", budget=2000, max_bid_cnt=0)
_FIELD_HIGH = RosterSeat(seat_id="field_high", model_name="rule", budget=9000, max_bid_cnt=4)
# 3200 is not an upstream-given number -- it is the budget a seat scripted
# to "always bid the legal minimum markup, else withdraw"
# (tests/test_aucarena_environment.py's `agent_min_markup` policy) starts
# with against `_FIELD_HIGH` under this family's deterministic tie-break
# RNG (verified by running the environment, not derived by hand; the
# concrete win/loss split is whatever that run produces, never a
# hand-picked target -- see docs/aucarena_codex_triage.md Finding 4 on why
# a per-round, not per-call, tie-break RNG stream is the fix this budget
# was re-verified against). Item 1 resolves at $1700, leaving $1500 --
# enough to keep pace through $1500 but not the $1600+ item 2 needs, so
# the seat wins exactly item 1 and withdraws on items 2-4, reproducing
# golden 1's narrated "wins 1 of 4, loses 3" (spec section 5) exactly.
_AGENT = RosterSeat(seat_id="agent", model_name="scripted", budget=3200, max_bid_cnt=4)
_SHARED_ROSTER = (_AGENT, _FIELD_LOW, _FIELD_HIGH)

MIN_MARKUP_PCT = 0.1
ENABLE_DISCOUNT = False  # fixed for every case in this spec (SS7)

GOLDENS: tuple[GoldenScenario, ...] = (
    GoldenScenario(
        golden_name="successful",
        item_ids=(1, 2, 3, 4),
        roster=_SHARED_ROSTER,
        world_seed=1001,
    ),
    GoldenScenario(
        golden_name="valid_but_poor",
        item_ids=(1, 2, 3, 4),
        roster=_SHARED_ROSTER,
        world_seed=1002,
    ),
    GoldenScenario(
        golden_name="invalid_unauthorized",
        item_ids=(1,),
        roster=_SHARED_ROSTER,
        world_seed=1003,
    ),
    GoldenScenario(
        golden_name="malformed_operational",
        item_ids=(1,),
        roster=_SHARED_ROSTER,
        world_seed=1004,
    ),
    GoldenScenario(
        golden_name="degenerate_reference",
        item_ids=(5,),
        roster=(RosterSeat(seat_id="agent", model_name="scripted", budget=6000, max_bid_cnt=4),),
        world_seed=1005,
    ),
)


def _case_id(golden_name: str, number: int = 1) -> str:
    return f"{CASE_ID_PREFIX}.{golden_name}_{number:02d}"


def build_case(scenario: GoldenScenario, item_pool: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one AERead-authored scenario."""
    missing = [item_id for item_id in scenario.item_ids if item_id not in item_pool]
    if missing:
        raise ValueError(
            f"scenario {scenario.golden_name!r} references item ids not in the "
            f"pinned pool: {missing}"
        )
    if len(set(scenario.item_ids)) != len(scenario.item_ids):
        raise ValueError(f"scenario {scenario.golden_name!r} repeats an item id")
    seat_ids = [seat.seat_id for seat in scenario.roster]
    if len(set(seat_ids)) != len(seat_ids):
        raise ValueError(f"scenario {scenario.golden_name!r} repeats a seat id")
    if not scenario.roster:
        raise ValueError(f"scenario {scenario.golden_name!r} has an empty roster")

    case_id = _case_id(scenario.golden_name)
    items = [dict(item_pool[item_id]) for item_id in scenario.item_ids]
    roster = [
        {
            "seat_id": seat.seat_id,
            "model_name": seat.model_name,
            "budget": seat.budget,
            "max_bid_cnt": seat.max_bid_cnt,
        }
        for seat in scenario.roster
    ]

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": SPLIT,
        "world_seed": scenario.world_seed,
        "seats": [{"id": seat.seat_id, "role": "bidder"} for seat in scenario.roster],
        "episode": {
            "max_logical_actions": MAX_LOGICAL_ACTIONS,
            "termination": TERMINATION_REASONS,
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "item_ids": list(scenario.item_ids),
            "item_pool_sha256": ITEM_POOL_SHA256,
            "items": items,
            "roster": roster,
            "min_markup_pct": MIN_MARKUP_PCT,
            "enable_discount": ENABLE_DISCOUNT,
            # Duplicated from the outer CaseManifest.world_seed above, not
            # an independent value: task.evaluation._replay_family_
            # trajectory calls plugin.initial_state(family_case, run=None),
            # so world_seed must be reachable from family_case alone for
            # replay to reconstruct the identical initial state
            # (environment.py's initial_state docstring).
            "world_seed": scenario.world_seed,
        },
        "provenance": {
            "generator_id": "aucarena_importer",
            "generator_version": FAMILY_VERSION,
            # AERead-authored scenario against a pinned upstream data pool --
            # not an import of an upstream-published task list (there isn't
            # one; see spec section 1's Governing facts).
            "review_status": "curated",
        },
        "upstream_task_id": None,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (paranoia; cheap and catches canonicalization bugs
    # early rather than at resolve time).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def import_all_cases(upstream_root: Path | str) -> dict[str, dict[str, Any]]:
    """Materialize all five goldens against the pinned item pool.

    Returns ``{case_id: case_dict}`` in ``GOLDENS`` order.
    """
    item_pool = load_item_pool(upstream_root)
    cases: dict[str, dict[str, Any]] = {}
    for scenario in GOLDENS:
        case = build_case(scenario, item_pool)
        if case["case_id"] in cases:
            raise ValueError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    return cases


def build_provenance(upstream_root: Path | str) -> dict[str, Any]:
    """Build the QC Gate-1 provenance record (pin, corpus enumeration)."""
    item_pool = load_item_pool(upstream_root)
    return {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_license": UPSTREAM_LICENSE,
        "item_pool_path": str(ITEM_POOL_RELATIVE_PATH),
        "item_pool_sha256": ITEM_POOL_SHA256,
        "item_pool_count": len(item_pool),
        "case_ids": [_case_id(scenario.golden_name) for scenario in GOLDENS],
    }


# --------------------------------------------------------------------------
# Disk I/O.
# --------------------------------------------------------------------------


def _dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def write_cases(
    output_dir: Path,
    provenance: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
) -> None:
    """Write ``provenance.json`` and one file per case."""
    _dump_json(output_dir / "provenance.json", provenance)
    for case_id, case in cases.items():
        _dump_json(output_dir / f"{case_id}.json", case)


def run_import(upstream_root: Path | str, output_dir: Path) -> None:
    """End-to-end: materialize the five goldens and write them to disk."""
    cases = import_all_cases(upstream_root)
    provenance = build_provenance(upstream_root)
    write_cases(output_dir, provenance, cases)


def _default_output_dir() -> Path:
    # src/aeread_families/aucarena/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "aucarena" / "pilot"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        required=True,
        help="path to the pinned auction-arena checkout (commit "
        f"{UPSTREAM_COMMIT})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write provenance.json and the five case files",
    )
    args = parser.parse_args(argv)
    run_import(args.upstream_root, args.output_dir)


if __name__ == "__main__":
    main()
