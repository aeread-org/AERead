"""Importer: pinned upstream STEER MCQA corpus -> AERead cases.

Turns the 8 declared elements of STEER (``narunraman/STEER``, pinned at
commit ``d66673c8277b9112fc5e39751524ccda6d852446``, no license file) into
one ``CaseManifest`` JSON file per admitted question plus a shared
``pins.json`` pin record and a ``corpus_manifest.json`` enumeration. See
``docs/steer_adapter_spec.md`` section 1 for the governing spec.

The corpus has no repo license, so its real question/option text never
enters this git repository. This module delegates all pandas-dependent
unpickling, joining, schema probing, and row admission to
``steer_bridge.SteerBridge`` (a subprocess running under a separate,
pandas-capable interpreter -- see ``steer_bridge.py``'s module docstring);
it never reimplements that classification itself, and it never writes
question/option/explanation text into a ``CaseManifest.payload`` -- only
``source_sha256`` and ``options_count``. The real text the bridge returns is
cached at ``bridges/steer-data/<element>/cases.jsonl`` (outside version
control), which is what the runtime environment plugin reads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .steer_bridge import SteerBridge

# --------------------------------------------------------------------------
# Family / case identity constants (spec section 1).
# --------------------------------------------------------------------------

FAMILY_ID = "steer"
FAMILY_VERSION = "0.1.0"
CASE_ID_PREFIX = "steer"

# Mode A: single-agent, one-shot MCQA. Full observability -- question and
# every option are always shown; there is no hidden information to police.
VISIBILITY_POLICY = "steer_full_observability_v1"

# The only two ways this family's one-shot phase can terminate: a legal
# option_id was submitted, or the submission was invalid (illegal or
# malformed) -- declared here, next to the manifest that publishes it, and
# enforced in environment.py's `step` so the declaration and the behaviour
# cannot drift apart (mirrors tau3_retail's identical discipline).
TERMINATION_REASONS = ("answered", "error")

# --------------------------------------------------------------------------
# Upstream pin constants (spec section 1).
# --------------------------------------------------------------------------

UPSTREAM_REPO = "narunraman/STEER"
UPSTREAM_COMMIT = "d66673c8277b9112fc5e39751524ccda6d852446"

# 8 declared elements, 2 per taxonomy branch -- tonight's pilot corpus, not
# all 48 elements upstream defines (spec section 6's first stated limit).
# Branch assignment was done manually from element name + README
# description, NOT by parsing upstream's own `taxonomy.pkl` (itself another
# unfetched git-lfs pointer) -- a stated limit, not a claim of upstream's own
# taxonomy structure (spec section 1).
BRANCH_BY_ELEMENT: dict[str, str] = {
    "transitivity": "utility_theory",
    "certainty_effect": "utility_theory",
    "pure_nash": "game_theory",
    "backward_induction": "game_theory",
    "plurality_voting": "social_choice",
    "borda_count": "social_choice",
    "dsic_mechanism": "mechanism_design",
    "ir_mechanism": "mechanism_design",
}
DECLARED_ELEMENTS: tuple[str, ...] = tuple(BRANCH_BY_ELEMENT)

HEAD_N = 200
CORPUS_ID = "steer_pilot_v1"


# --------------------------------------------------------------------------
# pins.json
# --------------------------------------------------------------------------


def build_pins(
    file_hashes_by_element: Mapping[str, Mapping[str, str]],
    counts_by_element: Mapping[str, Mapping[str, int]],
    zero_correct_sample_by_element: Mapping[str, str | None],
    excluded_sha256_by_element: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the pin record shared by every case (spec section 1).

    ``excluded_sha256_by_element`` pins the FULL per-question-id exclusion
    ledger (docs/steer_codex_triage.md finding 6) by content hash rather
    than embedding it -- mirrors ``file_sha256_by_element``'s existing
    content-addressed convention, keeping this committed file small while
    still making the uncommitted ``excluded.jsonl`` ledger (``write_excluded``)
    independently verifiable against exactly this pin.
    """
    pins: dict[str, Any] = {
        "upstream_repo": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "declared_elements": list(DECLARED_ELEMENTS),
        "branch_by_element": dict(BRANCH_BY_ELEMENT),
        "head_n": HEAD_N,
        "file_sha256_by_element": {
            element: dict(hashes) for element, hashes in file_hashes_by_element.items()
        },
        "counts_by_element": {
            element: dict(counts) for element, counts in counts_by_element.items()
        },
        "zero_correct_sample_by_element": dict(zero_correct_sample_by_element),
    }
    if excluded_sha256_by_element is not None:
        pins["excluded_question_ids_sha256_by_element"] = dict(excluded_sha256_by_element)
    return pins


# --------------------------------------------------------------------------
# CaseManifest construction (spec section 1's case-manifest field table).
# --------------------------------------------------------------------------


def build_case(element: str, row: Mapping[str, Any], pins: Mapping[str, Any]) -> dict[str, Any]:
    """Build one ``CaseManifest`` dict for one admitted, flattened question."""
    question_id = row["question_id"]
    if not isinstance(question_id, str) or not question_id:
        raise ValueError(f"row.question_id must be a non-empty string, got {question_id!r}")
    if element not in BRANCH_BY_ELEMENT:
        raise ValueError(f"element {element!r} is not one of the declared elements")
    case_id = f"{CASE_ID_PREFIX}.{element}.{question_id}"
    options_count = len(row["options"])
    if options_count < 2:
        raise ValueError(f"{case_id}: options_count must be at least 2, got {options_count}")

    data: dict[str, Any] = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": case_id,
        "family_id": FAMILY_ID,
        "family_version": FAMILY_VERSION,
        "split": BRANCH_BY_ELEMENT[element],
        "world_seed": 0,
        "seats": [{"id": "agent", "role": "assistant"}],
        "episode": {"max_logical_actions": 1, "termination": list(TERMINATION_REASONS)},
        "visibility_policy": VISIBILITY_POLICY,
        "payload": {
            "element": element,
            "question_id": question_id,
            "options_count": options_count,
            "source_sha256": row["source_sha256"],
            "pins": dict(pins),
        },
        "provenance": {
            "generator_id": "steer_importer",
            "generator_version": FAMILY_VERSION,
            "review_status": "upstream_pinned",
        },
        "upstream_task_id": question_id,
        "content_sha256": "0" * 64,
    }
    digest = case_content_sha256(data)
    data["content_sha256"] = digest

    # Round-trip through the strict R1 grammar and re-confirm the digest is
    # stable under re-hash (mirrors tau3_retail.cases.build_case's identical
    # paranoia -- cheap, and catches canonicalization bugs early rather than
    # at resolve time).
    CaseManifest.from_dict(data)
    if case_content_sha256(data) != digest:
        raise AssertionError(f"content_sha256 is not stable for case {case_id!r}")
    return data


def import_all_cases(
    bridge: SteerBridge, *, head_n: int = HEAD_N
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    """Flatten every declared element and build its admitted case records.

    Returns ``(pins, {case_id: case_dict}, {element: [admitted_row, ...]},
    {element: [excluded_row, ...]})``. The third element carries the real
    question/option text and gold ``correct_option_id`` for ``write_cache``
    -- it is never written into a committed case file. The fourth,
    ``excluded_rows_by_element``, is the per-question-id exclusion ledger
    (docs/steer_codex_triage.md finding 6): every excluded question_id and
    the exact reason it was excluded, never just an aggregate count plus
    one sample -- also never written into a committed case file, for
    ``write_excluded``.
    """
    file_hashes_by_element: dict[str, dict[str, str]] = {}
    counts_by_element: dict[str, dict[str, int]] = {}
    admitted_rows_by_element: dict[str, list[dict[str, Any]]] = {}
    excluded_rows_by_element: dict[str, list[dict[str, Any]]] = {}
    zero_correct_sample_by_element: dict[str, str | None] = {}

    for element in DECLARED_ELEMENTS:
        response = bridge.flatten_element(element, head_n=head_n)
        file_hashes_by_element[element] = response["file_hashes"]
        counts_by_element[element] = response["counts"]
        admitted_rows_by_element[element] = response["admitted"]
        excluded_rows_by_element[element] = sorted(
            response["excluded"], key=lambda row: row["question_id"]
        )
        zero_correct_sample_by_element[element] = response["zero_correct_sample_question_id"]

    excluded_sha256_by_element = {
        element: hashlib.sha256(
            canonical_json_bytes(excluded_rows_by_element[element])
        ).hexdigest()
        for element in DECLARED_ELEMENTS
    }
    pins = build_pins(
        file_hashes_by_element,
        counts_by_element,
        zero_correct_sample_by_element,
        excluded_sha256_by_element,
    )

    cases: dict[str, dict[str, Any]] = {}
    for element in DECLARED_ELEMENTS:
        for row in admitted_rows_by_element[element]:
            case = build_case(element, row, pins)
            if case["case_id"] in cases:
                raise ValueError(f"duplicate case_id: {case['case_id']!r}")
            cases[case["case_id"]] = case
    return pins, cases, admitted_rows_by_element, excluded_rows_by_element


# --------------------------------------------------------------------------
# corpus_manifest.json
# --------------------------------------------------------------------------


def _corpus_content_sha256(value: Mapping[str, Any]) -> str:
    normalized = dict(value)
    normalized["content_sha256"] = "0" * 64
    return hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()


def build_corpus_manifest(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the declared-corpus enumeration and its own content hash."""
    case_ids_by_element: dict[str, list[str]] = {element: [] for element in DECLARED_ELEMENTS}
    for case_id, case in cases.items():
        case_ids_by_element[case["payload"]["element"]].append(case_id)
    for element in case_ids_by_element:
        case_ids_by_element[element].sort()
    case_ids = [
        case_id for element in DECLARED_ELEMENTS for case_id in case_ids_by_element[element]
    ]

    data: dict[str, Any] = {
        "corpus_id": CORPUS_ID,
        "family_id": FAMILY_ID,
        "declared_elements": list(DECLARED_ELEMENTS),
        "branch_by_element": dict(BRANCH_BY_ELEMENT),
        "case_ids_by_element": case_ids_by_element,
        "case_ids": case_ids,
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
    """Write ``pins.json``, one file per case under its branch, and the
    corpus manifest -- all committed; never any question/option text."""
    _dump_json(output_dir / "pins.json", pins)
    for case_id, case in cases.items():
        branch = case["payload"]["element"]
        branch = BRANCH_BY_ELEMENT[branch]
        _dump_json(output_dir / branch / f"{case_id}.json", case)
    _dump_json(output_dir / "corpus_manifest.json", corpus_manifest)


def write_cache(cache_root: Path, admitted_rows_by_element: Mapping[str, list[dict[str, Any]]]) -> None:
    """Write ``bridges/steer-data/<element>/cases.jsonl`` -- outside version
    control; carries the real question/option text and gold
    ``correct_option_id`` the runtime environment plugin reads."""
    for element, rows in admitted_rows_by_element.items():
        path = cache_root / element / "cases.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")


def write_excluded(
    cache_root: Path, excluded_rows_by_element: Mapping[str, list[dict[str, Any]]]
) -> None:
    """Write ``bridges/steer-data/<element>/excluded.jsonl`` -- outside
    version control, alongside ``cases.jsonl``.

    The per-question-id exclusion ledger (docs/steer_codex_triage.md
    finding 6): every question_id this element's flatten classification
    excluded, and the exact reason (``zero_correct``/``multi_correct``) --
    never just the aggregate ``counts_by_element`` totals ``pins.json``
    alone carried before this. Rows are already sorted by
    ``question_id`` (see :func:`import_all_cases`), matching exactly the
    content ``pins.json``'s ``excluded_question_ids_sha256_by_element``
    pins.
    """
    for element, rows in excluded_rows_by_element.items():
        path = cache_root / element / "excluded.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")


def run_import(
    bridge: SteerBridge, output_dir: Path, cache_root: Path, *, head_n: int = HEAD_N
) -> None:
    """End-to-end: flatten every declared element and write cases + cache."""
    pins, cases, admitted_rows_by_element, excluded_rows_by_element = import_all_cases(
        bridge, head_n=head_n
    )
    corpus_manifest = build_corpus_manifest(cases)
    write_cases(output_dir, pins, cases, corpus_manifest)
    write_cache(cache_root, admitted_rows_by_element)
    write_excluded(cache_root, excluded_rows_by_element)


# --------------------------------------------------------------------------
# Default paths.
# --------------------------------------------------------------------------


def _default_output_dir() -> Path:
    # src/aeread_families/steer/cases.py -> repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "cases" / "steer"


def default_upstream_root() -> Path:
    return Path(
        os.environ.get(
            "AEREAD_STEER_UPSTREAM_ROOT",
            "/Users/sunzeyu/Documents/econ benchmark/upstream-steer",
        )
    )


def default_cache_root() -> Path:
    return Path(
        os.environ.get(
            "AEREAD_STEER_DATA_ROOT",
            "/Users/sunzeyu/Documents/econ benchmark/bridges/steer-data",
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        type=Path,
        default=default_upstream_root(),
        help="path to the pinned narunraman/STEER checkout (commit "
        "d66673c8277b9112fc5e39751524ccda6d852446)",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=default_cache_root(),
        help="directory holding bridges/steer-data/<element>/*.pkl and "
        "receiving cases.jsonl, outside version control",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_default_output_dir(),
        help="directory to write pins.json, one case file per branch, and "
        "corpus_manifest.json",
    )
    args = parser.parse_args(argv)
    bridge = SteerBridge.discover(
        upstream_root=args.upstream_root,
        cache_root=args.cache_root,
        expected_commit=UPSTREAM_COMMIT,
    )
    run_import(bridge, args.output_dir, args.cache_root)


if __name__ == "__main__":
    main()
