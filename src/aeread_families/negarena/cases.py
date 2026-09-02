"""Authoring: the negarena scenario grid -> AERead cases.

Unlike ``tau3.retail`` (which *imports* a pinned upstream task bank),
upstream ``NegotiationArena`` ships **no static task corpus** -- scenarios are
constructed programmatically (``player_goals``, ``player_starting_resources``,
``iterations``) via Python calls. AERead therefore *authors* the scenario
grid here and is the corpus's provenance owner
(``ProvenanceSpec.review_status="curated"``, not ``"upstream_pinned"`` -- the
inverse of tau3). See ``docs/negarena_adapter_spec.md`` section 1 for the
governing spec and the six authored scenarios.

This module never reimplements upstream game-object arithmetic, settlement
math, or the parser/admission-gate logic (that is ``negarena_bridge.py``'s
job, delegated to the pinned upstream checkout at
``c447fafd439a20b84cdedeb2f8a85c4fad764745``); it only resolves the authored
scenario parameters (goals, starting resources, iterations, seats) into
immutable ``CaseManifest`` records plus a corpus manifest with content
digests (QC Gate 1).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "negarena"
FAMILY_VERSION = "0.1.0"

BUY_SELL_SPLIT = "buy_sell"
ULTIMATUM_SPLIT = "ultimatum"

# Every seat in every negarena split is one of these two -- both
# ``BuySellGame`` and ``MultiTurnUltimatumGame`` are instantiated by
# upstream's own runner scripts (``runner/buysell_main.py``,
# ``runner/ultimatum_main.py``) with ``player_conversation_roles`` /
# ``player_roles`` of ``"You are Player RED."`` / ``"You are Player BLUE."``
# (``negotiationarena/constants.py``: ``AGENT_ONE = "Player RED"``,
# ``AGENT_TWO = "Player BLUE"``) -- there is no separate proposer/responder
# role name upstream; RED always moves first (``AlternatingGame.turn = 0``
# at construction) and, for ultimatum, holds the whole endowment.
RED = "red"
BLUE = "blue"

# Each seat's own resources/goal/reasoning are ``AgentMessage.secret`` --
# never shown to the other seat (``negotiationarena/agent_message.py``); only
# ``message``/``player answer``/``newly proposed trade`` are public.
VISIBILITY_POLICY = "negarena_seat_private_resources_v1"

# Declared here, next to the manifest that publishes it, mirroring
# ``tau3_retail/cases.py``'s discipline of keeping the termination
# vocabulary and the environment's actual `_set_termination` calls from
# drifting apart.
#
# ``buy_sell`` (``AlternatingGameEndsOnTag.game_over``) only ends the game
# early on an ``ACCEPT`` answer or the iteration cap -- there is no early
# ``REJECT`` branch (a REJECT-style answer is simply not the end tag and the
# game continues, "TODO: this is pretty buggy" per upstream's own comment).
# ``ultimatum`` (``MultiTurnUltimatumGame.game_over``) ends early on either
# ``ACCEPT`` or ``REJECT``, or the iteration cap.
#
# ``malformed_action`` / ``invalid_measurement`` are adapter-owned additions
# (spec section 3): upstream's own ``write_game_state`` re-raises on an
# unparseable response instead of terminating the episode in-band, and
# upstream never gates a trade proposal against the offering seat's actual
# holdings before it could be executed -- both must be catchable, first-class
# termination reasons here, never silent crashes or unchecked negative
# resource counts.
BUY_SELL_TERMINATION_REASONS = (
    "accepted",
    "iteration_cap",
    "malformed_action",
    "invalid_measurement",
)
ULTIMATUM_TERMINATION_REASONS = (
    "accepted",
    "rejected",
    "iteration_cap",
    "malformed_action",
    "invalid_measurement",
)

# --------------------------------------------------------------------------
# Upstream pin constants (spec header).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "vinid/NegotiationArena"
UPSTREAM_COMMIT = "c447fafd439a20b84cdedeb2f8a85c4fad764745"
UPSTREAM_LICENSE = "MIT"


def build_pins() -> dict[str, Any]:
    """Return the shared upstream pin record for every negarena case.

    Unlike tau3.retail there is no corpus file, DB, or tool schema to hash --
    upstream ships no static data for this family at all (governing fact).
    The pin is the repository/commit/license identity only.
    """
    return {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_license": UPSTREAM_LICENSE,
    }


# --------------------------------------------------------------------------
# The authored scenario grid (spec section 1).
# --------------------------------------------------------------------------


def _buy_sell_payload(
    *, red_cost: int, blue_max_pay: int, iterations: int = 10
) -> dict[str, Any]:
    """One ``BuySellGame`` scenario: RED sells ``X`` for ``ZUP``.

    Mirrors upstream's own reference construction
    (``runner/buysell_main.py``): ``SellerGoal(cost_of_production=...)`` /
    ``BuyerGoal(willingness_to_pay=...)``, ``Resources({"X": 1})`` /
    ``Resources({"ZUP": 1000})``.
    """
    return {
        "game_kind": "buy_sell",
        "iterations": iterations,
        "resource_token": "X",
        "money_token": "ZUP",
        "seats": {
            RED: {
                "goal_kind": "seller",
                "starting_resources": {"X": 1},
                "valuation": {"X": red_cost},
            },
            BLUE: {
                "goal_kind": "buyer",
                "starting_resources": {"ZUP": 1000},
                "valuation": {"X": blue_max_pay},
            },
        },
    }


def _ultimatum_payload(
    *, red_dollars: int, blue_dollars: int, iterations: int
) -> dict[str, Any]:
    """One ``MultiTurnUltimatumGame`` scenario: split ``Dollars``.

    Mirrors upstream's own reference construction
    (``runner/ultimatum_main.py``): ``UltimatumGoal()`` for both seats,
    ``resources_support_set=Resources({"Dollars": 0})``.
    """
    return {
        "game_kind": "ultimatum",
        "iterations": iterations,
        "money_token": "Dollars",
        "seats": {
            RED: {"starting_resources": {"Dollars": red_dollars}},
            BLUE: {"starting_resources": {"Dollars": blue_dollars}},
        },
    }


# Each entry: (split, index, termination_reasons, payload_builder).
# Descriptions mirror spec section 1 verbatim.
_SCENARIOS: tuple[tuple[str, int, tuple[str, ...], dict[str, Any]], ...] = (
    (
        # Reference scenario / parity anchor: upstream's own shipped
        # example_logs/buysell/1707347676639/ settles at 40 ZUP,
        # player_outcome = [0, 20].
        BUY_SELL_SPLIT,
        0,
        BUY_SELL_TERMINATION_REASONS,
        _buy_sell_payload(red_cost=40, blue_max_pay=60),
    ),
    (
        # Thin-ZOPA variant: only a narrow agreement region exists (55-60).
        BUY_SELL_SPLIT,
        1,
        BUY_SELL_TERMINATION_REASONS,
        _buy_sell_payload(red_cost=55, blue_max_pay=60),
    ),
    (
        # No-ZOPA variant: no legal trade benefits both seats (cost 65 >
        # willingness to pay 60); the informative outcome is disagreement.
        BUY_SELL_SPLIT,
        2,
        BUY_SELL_TERMINATION_REASONS,
        _buy_sell_payload(red_cost=65, blue_max_pay=60),
    ),
    (
        # Reference scenario from runner/ultimatum_main.py: proposer RED
        # holds Dollars:100, responder BLUE holds Dollars:0, iterations=6.
        ULTIMATUM_SPLIT,
        0,
        ULTIMATUM_TERMINATION_REASONS,
        _ultimatum_payload(red_dollars=100, blue_dollars=0, iterations=6),
    ),
    (
        # Low-iteration-cap variant: one proposal round only.
        ULTIMATUM_SPLIT,
        1,
        ULTIMATUM_TERMINATION_REASONS,
        _ultimatum_payload(red_dollars=100, blue_dollars=0, iterations=2),
    ),
    (
        # Degenerate endowment: every legal proposal is the empty split;
        # agreement is possible but economically inert.
        ULTIMATUM_SPLIT,
        2,
        ULTIMATUM_TERMINATION_REASONS,
        _ultimatum_payload(red_dollars=0, blue_dollars=0, iterations=6),
    ),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# CaseManifest construction.
# --------------------------------------------------------------------------


def build_case(
    split: str,
    index: int,
    termination_reasons: tuple[str, ...],
    scenario_payload: Mapping[str, Any],
    pins: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one authored negarena scenario."""
    case_id = f"{FAMILY_ID}.{split}.{index}"
    payload = {"scenario": dict(scenario_payload), "pins": dict(pins)}

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": split,
        "world_seed": index,
        "seats": [
            {"id": RED, "role": RED},
            {"id": BLUE, "role": BLUE},
        ],
        "episode": {
            "max_logical_actions": scenario_payload["iterations"],
            # Stored as a list (not the authored tuple): this dict is
            # compared byte-for-byte against the checked-in JSON files,
            # which round-trip every array through JSON as a list.
            "termination": list(termination_reasons),
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": "negarena_case_authoring",
            "generator_version": FAMILY_VERSION,
            # AERead authors the scenario grid (no upstream corpus to import
            # from); "curated" is the closest legal ``review_status`` value
            # to the spec's originally-proposed "aeread_authored", which is
            # not one of ``ProvenanceSpec``'s four allowed values
            # (``generated``/``reviewed``/``curated``/``upstream_pinned`` --
            # see docs/negarena_adapter_spec.md section 1's "Correction
            # (found during implementation)" note).
            "review_status": "curated",
        },
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (mirrors tau3_retail/cases.py's identical
    # paranoia check).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def author_all_cases() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Author every scenario in the grid into a case record.

    Returns ``(pins, {case_id: case_dict})`` in authoring order.
    """
    pins = build_pins()
    cases: dict[str, dict[str, Any]] = {}
    for split, index, termination_reasons, scenario_payload in _SCENARIOS:
        case = build_case(split, index, termination_reasons, scenario_payload, pins)
        if case["case_id"] in cases:
            raise ValueError(f"duplicate case_id: {case['case_id']!r}")
        cases[case["case_id"]] = case
    return pins, cases


# --------------------------------------------------------------------------
# Corpus manifest (spec section 1's six-scenario enumeration; QC Gate 1).
# --------------------------------------------------------------------------

CORPUS_ID = "negarena_corpus_v1"


def _corpus_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return _sha256_bytes(canonical_json_bytes(normalized))


def build_corpus_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the whole-corpus manifest and its own content hash.

    Every negarena case is authored (there is no upstream corpus to draw a
    partial pilot from, unlike tau3.retail's 18-task pilot), so this
    enumerates all six case ids rather than a subset.
    """
    expected_case_ids = [f"{FAMILY_ID}.{split}.{index}" for split, index, _, _ in _SCENARIOS]
    missing = [cid for cid in expected_case_ids if cid not in cases]
    if missing:
        raise ValueError(f"corpus case ids not found in authored cases: {missing}")

    data: dict[str, Any] = {
        "corpus_id": CORPUS_ID,
        "family_id": FAMILY_ID,
        "splits": [BUY_SELL_SPLIT, ULTIMATUM_SPLIT],
        "case_ids": expected_case_ids,
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
    pins: Mapping[str, Any],
    cases: Mapping[str, Mapping[str, Any]],
    corpus_manifest: Mapping[str, Any],
) -> None:
    """Write ``pins.json``, one file per case (split subdirectory), and the
    corpus manifest."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        split = case["split"]
        _dump_json(output_dir / split / f"{case_id}.json", case)
    _dump_json(output_dir / "corpus_manifest.json", corpus_manifest)


def run_author(output_dir: Path) -> None:
    """End-to-end: author all six scenarios and write the case set + corpus manifest."""
    pins, cases = author_all_cases()
    corpus_manifest = build_corpus_manifest(cases)
    write_cases(output_dir, pins, cases, corpus_manifest)


def _default_output_dir() -> Path:
    # src/aeread_families/negarena/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "negarena"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, the six case files, and corpus_manifest.json",
    )
    args = parser.parse_args(argv)
    run_author(args.output_dir)


if __name__ == "__main__":
    main()
